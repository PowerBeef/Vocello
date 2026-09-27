#!/usr/bin/env python3
"""AQ-06 panel qualification on the canonical M6 (audit phase P8, sections 5.8-5.9).

The lead runs this in a consent-bound session on a quiet host; nothing here
downloads anything, and every model runs through the orchestrator's supervised,
admitted workers (`scripts/audio_qc_orchestrator.py`). A panel judge moves from
`candidate` to `shadow` only through `promote`, on committed records:

- **Two clean resource runs.** `run` runs every requested judge twice over
  the same takes: the committed procedural canary set
  (`config/audio-qc-canary-set.json`, rendered and checked against its golden
  digests) plus the lead's latest language-bench takes (`--manifest`, an
  independent-ASR or orchestrator manifest; generated from the committed
  corpus). Each run is its own orchestrator session with a fresh cache, so
  every row runs a model. Per judge and run it records the peak resident memory
  and physical footprint, wall time, model load, warm-up and threads, and
  whether the run was clean: every envelope qualified on the canonical
  hardware profile, no retry, no unavailable row, and a quiet host
  (`require_quiet_host`; `QVOICE_ALLOW_BUSY_HOST=1` records a busy host and
  makes the run unclean).
- **Determinism class.** The two runs' raw outputs are compared row by row:
  D0 bit-exact, D1 equal on every discrete output with the largest numeric
  difference as the measured tolerance, D2 otherwise (never shadow).
- **Canary record.** One privacy-safe record per judge: its output identity
  and components, both runs' resources, the determinism class, and per canary
  take the audio and raw-output digests and the flat metrics. No transcript,
  text or path.
- **Recovery reports.** One `recovery-report` per run over that run's
  envelopes: the committed evidence the recovery-rule switch reads
  (`config/audio-qc-judges.json#admission.recoveryRule`).
- **Flip analysis.** When whisper-small (`--judge-config
  asr.whisper-small@1=...`) and Whisper large-v3 both ran: the fraction of
  language and accuracy verdicts that flip on the speech takes, and which.

Commands:
  plan      the judges, their lanes, ceilings and threads, the canary takes each
            judge has in scope and whether the recovery reports can cover
            every orchestrated worker (no model runs)
  run       the two runs, then `analyze`; everything stays in the untracked
            session directory (build/artifacts/diagnostics/...)
  analyze   recompute a session's records from its saved runs
  publish   copy a complete session's publishable records (the passing
            judges' canary records, the session record, the flip analysis
            and both recovery reports) into benchmarks/audio-qc-qualification/
            <session>/; it never stages or commits
  promote   after the records are committed: move each passing candidate to
            shadow in config/audio-qc-judges.json (status, determinism class,
            measured peak, canary citation); `--bind-recovery-rule` also cites
            the session's two recovery reports and makes the child-attributed
            recovery rule binding when they meet its promotion
  validate  every committed record under benchmarks/audio-qc-qualification/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audio_qc_judges import (  # noqa: E402
    JudgeRegistryError,
    canonical_profiles,
    host_profile,
    load_registry,
    validate_repository,
)
import audio_qc_orchestrator as orchestrator  # noqa: E402
from delivery_analysis_cache import DeliveryAnalysisCache, atomic_json, file_sha256  # noqa: E402
from delivery_resource_supervisor import (  # noqa: E402
    envelopes_in,
    host_hardware_profile_id,
    host_snapshot,
    recovery_report,
    run_supervised,
)
from lib.qc_pipeline import qualification as q  # noqa: E402
from lib.qc_pipeline.admission import AdmissionError, AdmissionPolicy, HostAdmission  # noqa: E402
from lib.qc_pipeline.evidence import EvidenceError, write_private_bundle  # noqa: E402

REPO = SCRIPT_DIR.parent
REGISTRY_PATH = REPO / "config/audio-qc-judges.json"
DEFAULT_SESSION_PARENT = Path(os.environ.get("QVOICE_ARTIFACTS_DIAGNOSTICS", REPO / "build/artifacts/diagnostics")) \
    / "audio-qc-panel-qualification"
HOST_PREFLIGHT = SCRIPT_DIR / "lib/host_preflight.sh"
PRIVATE_SESSION_SCHEMA = "vocello.audioqc.qualification-session-private/1"
RUN_SCHEMA = "vocello.audioqc.qualification-run/1"
RAW_SCHEMA = "vocello.audioqc.qualification-raw/1"
LANE = "audio-qc-panel-qualification"
# A qualification run waits its turn behind every other judge on a one-worker host.
DEFAULT_ADMISSION_WAIT_SECONDS = 6 * 3600.0


class QualificationRunError(RuntimeError):
    """The session cannot run, or its runs cannot be analyzed."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationRunError(f"cannot read {path.name}: {error}") from None
    if not isinstance(value, dict):
        raise QualificationRunError(f"{path.name} must contain an object")
    return value


# --------------------------------------------------------------------------- #
# The session's takes
# --------------------------------------------------------------------------- #

def speech_manifest(path: Path | None) -> dict[str, Any] | None:
    """The lead's speech takes: an independent-ASR manifest (lang-bench) or an orchestrator manifest."""
    if path is None:
        return None
    value = _read(path)
    if value.get("kind") == "independent-asr-manifest":
        value = orchestrator.manifest_from_independent_asr(value, source_sha256=file_sha256(path))
    manifest = orchestrator.validate_manifest(value)
    if manifest["lane"] != "language-bench":
        raise QualificationRunError("the speech takes come from a language-bench manifest")
    return manifest


def combined_manifest(session_id: str, canary_takes: Sequence[Mapping[str, Any]],
                      speech: Mapping[str, Any] | None) -> dict[str, Any]:
    takes = []
    for take in canary_takes:
        text = take.get("referenceText")
        takes.append(orchestrator._take(
            take_id=take["id"], generation_id=take["id"], audio=take["audioPath"], audio_sha256=take["audioSHA256"],
            language=take["language"], reference_text=text,
            script_sha256=orchestrator.text_sha256(text) if isinstance(text, str) else None,
            role=q.CANARY_ROLE, duration=take.get("durationSeconds"), cell_id=take["id"],
            reference_audio=take.get("referenceAudioPath"), reference_audio_sha256=take.get("referenceAudioSHA256"),
        ))
    seen = {take["id"] for take in takes}
    for take in (speech or {}).get("takes") or []:
        if take["id"] in seen:
            raise QualificationRunError(f"{take['id']}: a speech take reuses a canary id")
        takes.append(dict(take))
    return orchestrator.validate_manifest({
        "schema": orchestrator.MANIFEST_SCHEMA, "runID": session_id, "lane": "language-bench",
        "platform": "macos", "generationProcessExited": True,
        "source": {"kind": "panel-qualification", "sha256": q.json_digest([take["audioSHA256"] for take in takes])},
        "takes": takes, "pairs": [],
    })


def start_session(session_root: Path, *, speech: Mapping[str, Any] | None, panel: Sequence[str],
                  legacy: Sequence[str], spec: Mapping[str, Any] | None = None,
                  today: dt.date | None = None) -> tuple[Path, dict[str, Any]]:
    """A new private session directory: the rendered canary set, the combined manifest and the session plan."""
    today = today or dt.date.today()
    session_id = f"{today:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    session_dir = session_root / session_id
    session_dir.mkdir(parents=True)
    spec = spec or q.load_canary_set()
    canary = q.materialize_canary_set(spec, session_dir / "canary")
    manifest = combined_manifest(session_id, canary, speech)
    atomic_json(session_dir / "manifest.json", manifest)
    atomic_json(session_dir / "session.json", {
        "schema": PRIVATE_SESSION_SCHEMA, "id": session_id, "date": today.isoformat(),
        "manifestSHA256": q.json_digest(manifest), "canarySet": q.canary_set_identity(spec),
        "judges": {"panel": list(panel), "legacy": list(legacy)},
    })
    return session_dir, manifest


# --------------------------------------------------------------------------- #
# Host preflight
# --------------------------------------------------------------------------- #

def quiet_host_preflight() -> dict[str, Any]:
    """`require_quiet_host` (the timing lanes' refusal), plus the numbers the record keeps."""
    completed = subprocess.run(
        ["bash", "-c", 'source "$1" && require_quiet_host "$2"', "preflight", str(HOST_PREFLIGHT), LANE],
        env={**os.environ, "ROOT_DIR": str(REPO)}, capture_output=True, text=True, check=False,
    )
    sys.stderr.write(completed.stdout + completed.stderr)
    if completed.returncode != 0:
        raise QualificationRunError("the host is busy; qualification runs on a quiet host "
                                    "(QVOICE_ALLOW_BUSY_HOST=1 records the numbers and makes the runs unclean)")
    load = os.getloadavg()[0]
    cores = os.cpu_count() or 1
    level = host_snapshot().kernel_pressure_level
    busy = load > 2 * cores or (level is not None and level > 1)
    return {"loadAverage1M": round(load, 2), "cores": cores, "kernelPressureLevel": level, "busy": busy}


# --------------------------------------------------------------------------- #
# The runs
# --------------------------------------------------------------------------- #

def run_session(*, registry: dict[str, Any], manifest: dict[str, Any], judges: Sequence[orchestrator.Stage2Judge],
                resampler: str, session_dir: Path, supervisor: Callable[..., Any] = run_supervised,
                lock_root: Path | None = None, admission_wait_seconds: float = DEFAULT_ADMISSION_WAIT_SECONDS,
                preflight: Callable[[], Mapping[str, Any]] = quiet_host_preflight,
                host: Mapping[str, Any] | None = None, host_profile_id: str | None = None) -> None:
    """Both runs, each its own orchestrator session with a fresh cache; everything private."""
    policy = AdmissionPolicy.from_registry(registry)
    identities = {judge.judge_id: {"outputIdentity": judge.identity.output_identity,
                                   "components": dict(judge.identity_components)
                                   if judge.identity_components is not None else None}
                  for judge in judges}
    for run in range(1, q.REQUIRED_RUNS + 1):
        directory = session_dir / f"run-{run}"
        if directory.exists():
            raise QualificationRunError(f"{directory.name} exists; a session's runs are written once")
        before = dict(preflight())
        started = time.monotonic()
        started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        cache = DeliveryAnalysisCache(directory / "cache", resampler_version=resampler)
        runner = orchestrator.Orchestrator(
            registry=registry, cache=cache, stage2=judges, supervisor=supervisor, lock_root=lock_root,
            host_admission=HostAdmission(lock_root, policy, wait_seconds=admission_wait_seconds),
        )
        result = runner.run(manifest)
        after = dict(preflight())
        write_private_bundle(directory / "bundle", header=result["header"],
                             takes=zip(result["records"], result["privates"]), repository=REPO)
        atomic_json(directory / "raw.json", {"schema": RAW_SCHEMA, "raw": result["raw"]})
        atomic_json(directory / "run.json", {
            "schema": RUN_SCHEMA, "run": run, "startedAt": started_at,
            "wallSeconds": round(time.monotonic() - started, 3), "hostBefore": before, "hostAfter": after,
            "hostProfile": dict(host if host is not None else host_profile()),
            "hostProfileID": host_profile_id if host_profile_id is not None else host_hardware_profile_id(),
            "identities": identities, "registrySHA256": q.json_digest(registry),
        })


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

def _bundle(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    bundle = _read(directory / "bundle.json")
    records, units = [], {}
    for entry in bundle.get("takes") or []:
        record = _read(directory / entry["evidence"])
        private = _read(directory / entry["private"])
        records.append(record)
        units[record["take"]["takeID"]] = private["manifestTakeID"]
    return bundle, records, units


def _orchestrated_workers(registry: Mapping[str, Any]) -> list[str]:
    """Every orchestrated GPU and CPU worker judge the recovery-rule promotion needs serial envelopes of."""
    return sorted(
        judge_id for judge_id, judge in (registry.get("judges") or {}).items()
        if judge.get("status") not in ("retired", "quarantined") and isinstance(judge.get("execution"), dict)
        and judge["execution"].get("orchestrated") is True and judge["execution"].get("lane") in ("gpu", "cpu")
    )


def analyze_session(session_dir: Path, *, registry: Mapping[str, Any]) -> dict[str, Any]:
    """Every record of a session, from its saved runs: publishable ones under `records/`, the rest private."""
    private = _read(session_dir / "session.json")
    profiles = canonical_profiles(dict(registry))
    canonical = str(profiles[0]["id"]) if len(profiles) == 1 else None
    runs = []
    for run in range(1, q.REQUIRED_RUNS + 1):
        directory = session_dir / f"run-{run}"
        if not (directory / "run.json").is_file():
            raise QualificationRunError(f"run {run} of the session did not finish; it cannot be analyzed")
        meta = _read(directory / "run.json")
        bundle, records, units = _bundle(directory / "bundle")
        raw = _read(directory / "raw.json")["raw"]
        runs.append({"meta": meta, "bundle": bundle, "records": records, "units": units, "raw": raw})
    session = {"id": private["id"], "date": private["date"], "hostProfileID": runs[0]["meta"].get("hostProfileID")
               or "unknown"}
    admission = registry["admission"]
    records_dir = session_dir / "records"
    failed_dir = session_dir / "failed-judges"
    for directory in (records_dir, failed_dir):
        if directory.exists():
            shutil.rmtree(directory)
    takes = [{"takeID": record["take"]["takeID"], "unit": runs[0]["units"][record["take"]["takeID"]],
              "role": record["take"].get("role"), "language": record["take"]["language"],
              "audioSHA256": record["take"]["audioSHA256"], "canonicalPCMSHA256": record["take"]["canonicalPCMSHA256"]}
             for record in runs[0]["records"]]
    workers = [{worker["judge"]: worker for worker in run["bundle"].get("workers") or []} for run in runs]
    busy = [bool(run["meta"]["hostBefore"].get("busy") or run["meta"]["hostAfter"].get("busy")) for run in runs]
    judges_summary: dict[str, Any] = {}
    legacy: dict[str, Any] = {}
    for judge_id in private["judges"]["panel"] + private["judges"]["legacy"]:
        resources = []
        for index, run in enumerate(runs):
            summary = q.run_resources(workers[index].get(judge_id), canonical_host=canonical)
            if busy[index]:
                summary["failures"] = sorted({*summary["failures"], "host-busy"})
                summary["clean"] = False
            resources.append(summary)
        if judge_id in private["judges"]["legacy"]:
            legacy[judge_id] = {"runs": [{"run": index, **summary} for index, summary in enumerate(resources, 1)]}
            continue
        run_data = []
        for index, run in enumerate(runs):
            measurements = {}
            for record in run["records"]:
                for measurement in record["measurements"]:
                    if measurement["judge"] == judge_id:
                        measurements[record["take"]["takeID"]] = measurement
            run_data.append({"resources": resources[index], "raw": run["raw"].get(judge_id) or {},
                             "measurements": measurements})
        record = q.judge_analysis(
            judge_id, runs=run_data, identity=runs[0]["meta"]["identities"][judge_id], takes=takes, session=session,
            canary_set=private["canarySet"], registry_sha256=runs[0]["meta"]["registrySHA256"],
            budget_bytes=admission["budgetBytes"], reservation_bytes=admission["orchestratorReservationBytes"],
        )
        problems = q.validate_canary_record(record)
        if problems:
            raise QualificationRunError(f"{judge_id}: its canary record does not validate: {problems[0]}")
        passed = record["qualification"]["passed"]
        target = (records_dir / "judges" if passed else failed_dir) / q.record_file_name(judge_id)
        atomic_json(target, record)
        judges_summary[judge_id] = {
            "passed": passed, "reasons": record["qualification"]["reasons"],
            "record": f"judges/{q.record_file_name(judge_id)}" if passed else None,
            "determinismClass": record["determinism"]["class"],
            "canonicalHostPeakBytes": record["resources"]["canonicalHostPeakBytes"],
            "registryStatus": (registry["judges"].get(judge_id) or {}).get("status"),
        }
    run_rows = []
    required = _orchestrated_workers(registry)
    for index, run in enumerate(runs, start=1):
        report = recovery_report(envelopes_in(run["bundle"]))
        atomic_json(records_dir / f"recovery-report-run-{index}.json", report)
        serial = report.get("serialByJudge") or {}
        run_rows.append({
            "run": index, "recoveryReport": f"recovery-report-run-{index}.json",
            "sessionIDs": report.get("sessionIDs"), "wallSeconds": run["meta"].get("wallSeconds"),
            "loadAverage1MBefore": run["meta"]["hostBefore"].get("loadAverage1M"),
            "loadAverage1MAfter": run["meta"]["hostAfter"].get("loadAverage1M"),
            "hostBusy": busy[index - 1],
            "workersWithoutSerialEnvelope": [judge_id for judge_id in required if not serial.get(judge_id)],
        })
    flip = None
    if q.BASELINE_RECOGNIZER in private["judges"]["legacy"] and q.CANDIDATE_RECOGNIZER in private["judges"]["panel"]:
        first = q.flip_analysis(runs[0]["records"])
        second = q.flip_analysis(runs[1]["records"])
        flip_record = {**first, "session": session, "run2Consistent": q.flipped_ids(first) == q.flipped_ids(second)}
        atomic_json(records_dir / "flip-analysis.json", flip_record)
        flip = "flip-analysis.json"
    session_record = {
        "schema": q.SESSION_SCHEMA, "session": session, "canarySet": private["canarySet"],
        "manifest": {"takes": len(takes), "canaryTakes": sum(1 for take in takes if take["role"] == q.CANARY_ROLE),
                     "manifestSHA256": private["manifestSHA256"]},
        "runs": run_rows, "judges": judges_summary, "legacyJudges": legacy, "flipAnalysis": flip,
    }
    problems = q.validate_session_record(session_record)
    if problems:
        raise QualificationRunError(f"the session record does not validate: {problems[0]}")
    atomic_json(records_dir / "session.json", session_record)
    return {"session": session, "judges": judges_summary, "runs": run_rows, "flipAnalysis": flip,
            "recordsDirectory": str(records_dir)}


# --------------------------------------------------------------------------- #
# Publication and promotion
# --------------------------------------------------------------------------- #

def publish(session_dir: Path, records_root: Path) -> Path:
    """Copy a complete session's publishable records into the tracked records root (never staged)."""
    source = session_dir / "records"
    session = _read(source / "session.json")
    session_id = session["session"]["id"]
    destination = records_root / session_id
    if destination.exists():
        raise QualificationRunError(f"{destination} exists; a session is published once")
    staging = records_root / f".{session_id}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging)
    staging.rename(destination)
    errors = q.validate_session_directory(destination)
    if errors:
        shutil.rmtree(destination)
        raise QualificationRunError("the session's records do not validate: " + "; ".join(errors[:3]))
    return destination


def promote(records_dir: Path, *, root: Path = REPO, registry_path: Path | None = None, dry_run: bool = False,
            bind_recovery_rule: bool = False) -> dict[str, Any]:
    """Edit the registry for each passing candidate of a committed session; write only if it still validates."""
    registry_path = registry_path or root / "config/audio-qc-judges.json"
    records_dir = records_dir.resolve()
    errors = q.validate_session_directory(records_dir)
    if errors:
        raise QualificationRunError("the session's records do not validate: " + "; ".join(errors[:3]))
    session, records = q.session_records(records_dir)
    relative = records_dir.relative_to(root.resolve()).as_posix()
    paths = {judge_id: f"{relative}/{entry['record']}" for judge_id, entry in session["judges"].items()
             if entry.get("record")}
    reports = [f"{relative}/{run['recoveryReport']}" for run in session["runs"]]
    uncommitted = q.committed_errors(root, [f"{relative}/session.json", *paths.values(),
                                            *(reports if bind_recovery_rule else [])])
    if uncommitted:
        raise QualificationRunError("commit the session's records before promoting: " + "; ".join(uncommitted[:3]))
    digests = {judge_id: file_sha256(root / path) for judge_id, path in paths.items()}
    text = registry_path.read_text(encoding="utf-8")
    registry = json.loads(text)
    edits, skipped = q.promotion_edits(registry, session, records, record_paths=paths, record_digests=digests)
    if bind_recovery_rule:
        edits[("admission", "recoveryRule", "candidateBinding")] = True
        edits[("admission", "recoveryRule", "promotion", "evidence")] = [
            *registry["admission"]["recoveryRule"]["promotion"]["evidence"],
            *({"path": path, "sha256": file_sha256(root / path), "date": session["session"]["date"]}
              for path in reports),
        ]
    if not edits:
        return {"promoted": [], "skipped": skipped, "written": False}
    updated = q.replace_json_values(text, edits)
    problems = validate_repository(root, json.loads(updated))
    if problems:
        raise QualificationRunError("the promoted registry would not validate; nothing was written: "
                                    + "; ".join(problems[:3]))
    if not dry_run:
        temporary = registry_path.with_name(f".{registry_path.name}.promote")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, registry_path)
    promoted = sorted({path[1] for path in edits if path[0] == "judges"})
    return {"promoted": promoted, "skipped": skipped, "recoveryRuleBinding": bind_recovery_rule,
            "written": not dry_run}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _judges(args: argparse.Namespace, registry: dict[str, Any]) -> tuple[list[orchestrator.Stage2Judge], str,
                                                                           list[str], list[str]]:
    panel = orchestrator.select_panel_judges(registry, args.judge or [], panel=not args.judge)
    configs = orchestrator._parse_judge_configs(args.judge_config or [])
    judges, resampler = orchestrator.build_stage2_judges(
        registry, judge_configs=configs, panel_judges=panel, model_root=args.model_root,
        resampler=None, row_timeout_seconds=args.timeout_seconds,
    )
    return judges, resampler, panel, list(configs)


def _plan(args: argparse.Namespace, registry: dict[str, Any]) -> dict[str, Any]:
    judges, resampler, panel, legacy = _judges(args, registry)
    spec = q.load_canary_set()
    speech = speech_manifest(args.manifest)
    # Scope reads only each take's language and whether it has a script.
    takes = [{"id": entry["id"], "language": entry["language"],
              "referenceText": "script" if entry.get("script") else None, "scriptSHA256": "0" * 64}
             for entry in spec["takes"]] + list((speech or {}).get("takes") or [])
    rows = []
    for judge in judges:
        admission = orchestrator.judge_admission(registry, judge.judge_id)
        in_scope = sum(1 for take in takes if judge.request(take) is not None)
        rows.append({"judge": judge.judge_id, "lane": admission.lane, "threads": admission.threads,
                     "ceilingBytes": admission.ceiling_bytes, "ceilingBasis": admission.ceiling_basis,
                     "takesInScope": in_scope, "reportOnly": judge.report_only if judge.panel else None})
    covered = {judge.judge_id for judge in judges}
    return {
        "judges": rows, "canaryTakes": len(spec["takes"]), "speechTakes": len((speech or {}).get("takes") or []),
        "resampler": resampler,
        "recoveryReportsCoverEveryWorker": not [judge_id for judge_id in _orchestrated_workers(registry)
                                                if judge_id not in covered],
        "workersNotRun": [judge_id for judge_id in _orchestrated_workers(registry) if judge_id not in covered],
        "flipAnalysis": q.BASELINE_RECOGNIZER in legacy and q.CANDIDATE_RECOGNIZER in panel and speech is not None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path,
                             help="the latest language-bench independent-asr-manifest.json (speech takes)")
        command.add_argument("--judge", action="append", metavar="ID",
                             help="a panel judge (repeatable; default: every runnable panel judge)")
        command.add_argument("--judge-config", action="append", metavar="JUDGE=CONFIG",
                             help="a legacy worker judge from its prepared configuration "
                                  "(asr.whisper-small@1=..., compact.sensevoice-small-q8@1=...)")
        command.add_argument("--model-root", type=Path)
        command.add_argument("--timeout-seconds", type=float, default=orchestrator.DEFAULT_ROW_TIMEOUT_SECONDS)
        if name == "run":
            command.add_argument("--session-root", type=Path, default=DEFAULT_SESSION_PARENT)
            command.add_argument("--admission-wait-seconds", type=float, default=DEFAULT_ADMISSION_WAIT_SECONDS)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("session", type=Path)
    publisher = commands.add_parser("publish")
    publisher.add_argument("session", type=Path)
    publisher.add_argument("--records-root", type=Path, default=q.RECORDS_ROOT)
    promoter = commands.add_parser("promote")
    promoter.add_argument("records", type=Path, help="benchmarks/audio-qc-qualification/<session>")
    promoter.add_argument("--dry-run", action="store_true")
    promoter.add_argument("--bind-recovery-rule", action="store_true")
    validator = commands.add_parser("validate")
    validator.add_argument("--records-root", type=Path, default=q.RECORDS_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            errors = q.validate_records(args.records_root)
            errors += [f"canary set: {problem}" for problem in q.canary_set_errors(
                json.loads(q.CANARY_SET_PATH.read_text(encoding="utf-8")))]
            sessions = [path.name for path in sorted(args.records_root.iterdir()) if path.is_dir()] \
                if args.records_root.is_dir() else []
            print(json.dumps({"status": "FAIL" if errors else "PASS", "sessions": len(sessions), "errors": errors},
                             sort_keys=True))
            return 1 if errors else 0
        registry = load_registry()
        if args.command == "plan":
            print(json.dumps(_plan(args, registry), indent=2, sort_keys=True))
            return 0
        if args.command == "run":
            judges, resampler, panel, legacy = _judges(args, registry)
            session_dir, manifest = start_session(args.session_root, speech=speech_manifest(args.manifest),
                                                  panel=panel, legacy=legacy)
            run_session(registry=registry, manifest=manifest, judges=judges, resampler=resampler,
                        session_dir=session_dir, admission_wait_seconds=args.admission_wait_seconds)
            summary = analyze_session(session_dir, registry=registry)
        elif args.command == "analyze":
            summary = analyze_session(args.session, registry=registry)
        elif args.command == "publish":
            destination = publish(args.session, args.records_root)
            print(json.dumps({"published": str(destination),
                              "next": "commit it, then run: promote " + str(destination)}, indent=2))
            return 0
        else:
            print(json.dumps(promote(args.records, dry_run=args.dry_run, bind_recovery_rule=args.bind_recovery_rule),
                             indent=2, sort_keys=True))
            return 0
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except (QualificationRunError, q.QualificationError, orchestrator.OrchestratorError, AdmissionError,
            EvidenceError, JudgeRegistryError, OSError, ValueError, KeyError) as error:
        print(f"audio-qc-panel-qualification: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
