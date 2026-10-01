#!/usr/bin/env python3
"""The lane gating contract of the audio QC detectors, and its enforcement (AQ-07, AQ-09).

`config/audio-qc-lane-gates.json` names, per evidence lane, the registered
detectors that gate it and at which level (`warn` or `fail`). A detector gates
only inside the scope of a qualified record (A1), so `validate` refuses a listed
detector unless one committed calibration record under
`benchmarks/audio-qc-calibration/<id>/`:

- is a valid qc-calibration record (`audio_qc_detector_calibration.record_errors`)
  of that detector, filed as `record-<plan digest 16>.json`;
- qualified it at the gate's level or a stricter one (a fail record covers a
  warn gate, never the reverse);
- was confirmed under the detector's current registry definition (A7: a changed
  entry needs a new version, a new plan and a new record);
- was confirmed at an operating point that applies to the lane's kind
  (`operatingPoints.<point>.appliesTo` in the qualification policy, so the
  evidence-lane fail bar never backs a product lane);
- covers the lane's scope: each lane language is in the record's scope with a
  measured per-language FAR; the lane's modes are among the modes the record,
  or its detector's entry, declares, and a record that declares none was
  confirmed on mode-independent audio (N2 is a codec round trip of human
  speech); and the record's confirmation population is the lane's FAR
  population.

A lane lists only detectors of the classes or stages that its `laneGatingSets`
entry in the qualification policy names, and a lane that names a matrix declares
exactly the languages and modes of the matrix's cells. The records' own
integrity (plan, ledger, rewrites) is `audio_qc_detector_calibration.py
validate`, which the contract gate runs first.

Enforcement. A lane run writes its takes as a lane takes manifest
(`audio-qc-takes.json` beside its WAVs: an `audio-qc-calibration-takes` schema 1
manifest marked with the lane, holding the takes a gate can score, and under
`excluded` the others with a reason: a negative control, or a language or mode
outside the lane). `run` then computes the gates over it after the generator
has exited:

1. the panel manifest from the takes (`audio_qc_orchestrator.py manifest
   --from-calibration-takes`, which hands a clone take's reference clip to the
   speaker judges);
2. the orchestrator with exactly the panel judges the lane's gating detectors
   read in the takes' languages (components and required content voters), on
   the run's own cache root,
   `<analysis cache>/confirmation/lane-<lane>-<run>` (the per-panel roots
   `clean_build_caches.sh --prune-confirmation-caches` removes once idle);
3. Stage 0 (`audio_qc_calibration_set.py score`) when a detector reads
   `measurements.json`, and a raw-output export per judge a detector reduces;
4. `evaluate`, which scores every gating detector on every take with the
   calibration's own code path (`audio_qc_detector_calibration.build_scores`
   over the lane takes manifest, the bundle and the measurements, so a gate
   computes exactly the score its record qualified) and compares it with the
   threshold the detector's qualifying record pre-registered
   (`threshold.values` per stratum, in the record's `direction`), never one
   derived here. A take abstains with a reason code when it is outside the
   lane's or the record's scope (language, mode), when the record holds no
   threshold for its stratum, or when its evidence is missing (no bundle row,
   a judge unavailable or out of scope, a content voter incomplete, no
   measurement). A take's verdict is `warn` when a warn gate flags it and
   `fail` when a fail gate does, the lane's the worst of its takes'; a fail
   gate whose lane evidence was produced by other judges, metric reductions or
   scoring code than its record's flags at warn only.

`gates.json` (`<run dir>/audio-qc/gates.json`) holds the result: detector and
take ids, numbers, reason codes and digests, never text, a transcript or a
path. Exit codes of `run` and `evaluate`: 0 pass, 3 warn, 1 fail, 2 when the
gates could not be computed (1 instead when the lane has a fail gate). A warn
gate reports and never fails a lane.

    python3 scripts/audio_qc_lane_gates.py validate
    python3 scripts/audio_qc_lane_gates.py run --lane language-bench --run-dir <lang-bench artifacts>
    python3 scripts/audio_qc_lane_gates.py evaluate --lane L --takes <audio-qc-takes.json>
        [--bundle DIR] [--measurements FILE] [--raw-outputs FILE ...] --output <gates.json>
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import audio_qc_detector_calibration as calibration  # noqa: E402
from lib import language_metrics  # noqa: E402
from lib.jsonio import atomic_json, sha256_json  # noqa: E402
from lib.qc_pipeline.evidence import is_token, privacy_errors  # noqa: E402
from lib.qc_qualification import detectors as registry_lib, thresholds  # noqa: E402

GATES = "config/audio-qc-lane-gates.json"
KIND = "audio-qc-lane-gates"
SCHEMA_VERSION = 1
# In order of strictness: a record qualified at a later level covers a gate at an earlier one.
LEVELS = ("warn", "fail")
# The `appliesTo` vocabulary of the policy's operating points.
LANE_KINDS = ("product", "evidence-lane")
MODES = ("custom", "design", "clone")
LANE_KEYS = frozenset({"kind", "scope", "gates"})
OPTIONAL_LANE_KEYS = frozenset({"matrix", "note"})
SCOPE_KEYS = frozenset({"languages", "modes", "farPopulation"})

# Enforcement: the lane takes manifest, the result and where a run writes them.
TAKES_FILE = "audio-qc-takes.json"
TAKES_GENERATOR = "audio-qc-lane-gates/1"
OUTPUT_DIRECTORY = "audio-qc"
RESULT_FILE = "gates.json"
RESULT_KIND = "audio-qc-lane-gate-result"
RESULT_SCHEMA = "vocello.audioqc.lane-gate-result/1"
VERDICTS = ("pass", "warn", "fail")
EXIT_CODES = {"pass": 0, "warn": 3, "fail": 1}
EXIT_ERROR = 2
TAKE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
ORCHESTRATOR = REPO / "scripts" / "audio_qc_orchestrator.py"
CALIBRATION_SET = REPO / "scripts" / "audio_qc_calibration_set.py"
DEFAULT_ANALYSIS_CACHE = REPO / "build" / "cache" / "delivery-analysis"
# The per-panel cache roots of config/build-output-policy.json (childRetention.analysisConfirmation).
PANEL_ROOTS = "confirmation"
LANGUAGE_PLAN = "language-run-plan.json"
LANGUAGE_ASR_MANIFEST = "independent-asr-manifest.json"
# Why a lane take is not scored by any gate (the takes manifest's `excluded`).
EXCLUSION_REASONS = ("negative-control", "no-output", "language-outside-lane", "mode-outside-lane")


class GateError(ValueError):
    """A lane-gates file or an input it names that cannot be read."""


def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"{what} {Path(path).name} is unreadable: {error}") from error


def detector_records(root: Path, detector: str) -> list[tuple[str, Any]]:
    """The committed records of one detector as (repository-relative path, parsed JSON or None)."""
    directory = Path(root) / calibration.RECORDS / detector
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("record-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = None
        records.append((path.relative_to(root).as_posix(), record))
    return records


def record_population(record: Mapping[str, Any]) -> str | None:
    """The population the record's FAR was confirmed on, from its confirmation cohort's kind."""
    cohort = (record.get("cohorts") or {}).get("confirmation") or {}
    return calibration.COHORT_KINDS.get(cohort.get("kind"))


def record_modes(record: Mapping[str, Any], entry: Mapping[str, Any]) -> list[str] | None:
    """The modes a record is scoped to (its own, else its detector's), or None when mode-independent."""
    for scope in (record.get("scope") or {}, entry.get("scope") or {}):
        if scope.get("modes") is not None:
            return list(scope["modes"])
    return None


def coverage_problems(record: Any, path: str, *, entry: Mapping[str, Any], level: str,
                      lane: Mapping[str, Any], policy: Mapping[str, Any]) -> list[str]:
    """Why one record does not back a gate at `level` on `lane`; empty when it does."""
    if record is None:
        return ["unreadable"]
    invalid = calibration.record_errors(record)
    if invalid:
        return [f"not a valid record ({invalid[0]})"]
    if record["detector"] != entry["id"] or Path(path).name != f"record-{record['planSHA256'][:16]}.json":
        return [f"not filed as {entry['id']}/record-<plan digest 16>.json"]
    if record["verdict"] != "qualified":
        return [f"refused ({', '.join(record['reasons'])})"]
    problems = []
    if record["level"] not in LEVELS or LEVELS.index(record["level"]) < LEVELS.index(level):
        problems.append(f"qualified at {record['level']}, not {level}")
    if record["detectorDefinitionSHA256"] != registry_lib.definition_digest(entry):
        problems.append("confirmed an earlier definition of the detector (A7)")
    point = (policy.get("operatingPoints") or {}).get(record["operatingPoint"])
    if not isinstance(point, Mapping):
        problems.append(f"operating point {record['operatingPoint']} is not in the policy")
    elif point.get("appliesTo") is not None and lane["kind"] not in point["appliesTo"]:
        problems.append(f"operating point {record['operatingPoint']} does not apply to the lane's kind "
                        f"({lane['kind']})")
    scope = lane["scope"]
    covered = set(record["scope"].get("languages") or ())
    measured = set(((record["rates"].get("farPerLanguage") or {}).get("languages") or {}))
    outside = [language for language in scope["languages"] if language not in covered]
    if outside:
        problems.append(f"its scope lacks {', '.join(outside)}")
    unmeasured = [language for language in scope["languages"] if language in covered and language not in measured]
    if unmeasured:
        problems.append(f"it measured no FAR in {', '.join(unmeasured)}")
    modes = record_modes(record, entry)
    if modes is not None and not set(scope["modes"]) <= set(modes):
        problems.append(f"its modes {', '.join(modes)} do not cover {', '.join(scope['modes'])}")
    population = record_population(record)
    if population != scope["farPopulation"]:
        problems.append(f"its FAR was confirmed on {population}, not {scope['farPopulation']}")
    return problems


def _names(value: Any, allowed: Sequence[str]) -> bool:
    return (isinstance(value, list) and bool(value) and len(set(value)) == len(value)
            and all(isinstance(item, str) and item in allowed for item in value))


def scope_errors(root: Path, lane: Mapping[str, Any], where: str) -> list[str]:
    scope = lane.get("scope")
    if not isinstance(scope, Mapping) or set(scope) != SCOPE_KEYS:
        return [f"{where}.scope declares exactly {sorted(SCOPE_KEYS)}"]
    errors = []
    if not _names(scope["languages"], language_metrics.PRODUCT_LANGUAGES):
        errors.append(f"{where}.scope.languages lists distinct product languages")
    if not _names(scope["modes"], MODES):
        errors.append(f"{where}.scope.modes lists distinct modes of {MODES}")
    if scope["farPopulation"] not in registry_lib.POPULATIONS:
        errors.append(f"{where}.scope.farPopulation is one of {registry_lib.POPULATIONS}")
    matrix = lane.get("matrix")
    if matrix is None or errors:
        return errors
    path = Path(root) / str(matrix)
    if not isinstance(matrix, str) or Path(matrix).is_absolute() or ".." in Path(matrix).parts or not path.is_file():
        return [f"{where}.matrix names a committed matrix file"]
    document = load_json(path, "the lane matrix")
    cells = document.get("cells") if isinstance(document, Mapping) else None
    if not isinstance(cells, list) or not cells:
        return [f"{where}.matrix {matrix} lists no cells"]
    languages = sorted({cell.get("scriptLang") for cell in cells if isinstance(cell, Mapping)})
    modes = sorted({cell.get("mode") for cell in cells if isinstance(cell, Mapping)})
    if sorted(scope["languages"]) != languages or sorted(scope["modes"]) != modes:
        errors.append(f"{where}.scope declares the languages {languages} and modes {modes} of {matrix}")
    return errors


@dataclass(frozen=True)
class Sources:
    """The lane-gates file, the detector registry's entries and the qualification policy, under one root."""

    root: Path
    config: Mapping[str, Any]
    entries: Mapping[str, Mapping[str, Any]]
    policy: Mapping[str, Any]

    @classmethod
    def load(cls, root: Path) -> "Sources":
        root = Path(root)
        config = load_json(root / GATES, "the lane gates")
        registry = load_json(root / calibration.REGISTRY, "the detector registry")
        policy = load_json(root / calibration.POLICY, "the qualification policy")
        detectors = registry.get("detectors") if isinstance(registry, Mapping) else None
        entries = {entry["id"]: entry for entry in detectors or ()
                   if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)}
        return cls(root, config, entries, policy if isinstance(policy, Mapping) else {})

    def file_errors(self) -> list[str]:
        config = self.config
        if not isinstance(config, Mapping) or config.get("kind") != KIND or config.get("schemaVersion") != SCHEMA_VERSION:
            return [f"the file declares kind {KIND} and schemaVersion {SCHEMA_VERSION}"]
        lanes = config.get("lanes")
        if not isinstance(lanes, Mapping) or not lanes:
            return ["lanes names at least one lane"]
        return []

    def covering(self, entry: Mapping[str, Any], level: str,
                 lane: Mapping[str, Any]) -> tuple[list[tuple[str, Mapping[str, Any]]], dict[str, list[str]]]:
        """The committed records of a detector that back a gate at `level` on `lane`, and why each other does not."""
        records = detector_records(self.root, entry["id"])
        reasons = {path: coverage_problems(record, path, entry=entry, level=level, lane=lane, policy=self.policy)
                   for path, record in records}
        return [(path, record) for path, record in records if not reasons[path]], reasons

    def lane_errors(self, name: str, lane: Any) -> list[str]:
        """Every problem of one lane; empty when each of its gates is backed by a covering record."""
        where = f"lanes.{name}"
        gating_sets = self.policy.get("laneGatingSets") or {}
        gating = gating_sets.get(name)
        if not isinstance(gating, Mapping):
            return [f"{where} is not a lane of the policy's laneGatingSets {sorted(gating_sets)}"]
        if not isinstance(lane, Mapping) or not LANE_KEYS <= set(lane) <= LANE_KEYS | OPTIONAL_LANE_KEYS:
            return [f"{where} declares {sorted(LANE_KEYS)} and optionally {sorted(OPTIONAL_LANE_KEYS)}"]
        if lane["kind"] not in LANE_KINDS:
            return [f"{where}.kind is one of {LANE_KINDS}"]
        errors = scope_errors(self.root, lane, where)
        gates = lane["gates"]
        if not isinstance(gates, list):
            return errors + [f"{where}.gates must be a list"]
        if errors:
            return errors
        seen: set[str] = set()
        for index, gate in enumerate(gates):
            spot = f"{where}.gates[{index}]"
            if not isinstance(gate, Mapping) or set(gate) != {"detector", "level"}:
                errors.append(f"{spot} names exactly a detector and a level")
                continue
            detector, level = gate["detector"], gate["level"]
            if level not in LEVELS:
                errors.append(f"{spot}.level is one of {LEVELS}")
                continue
            entry = self.entries.get(detector)
            if entry is None:
                errors.append(f"{spot}: {detector} is not in {calibration.REGISTRY}")
                continue
            if detector in seen:
                errors.append(f"{spot}: {detector} is listed twice")
                continue
            seen.add(detector)
            if entry.get("class") not in (gating.get("classes") or ()) \
                    and entry.get("stage") not in (gating.get("stages") or ()):
                errors.append(f"{spot}: {detector} (class {entry.get('class')}, stage {entry.get('stage')}) is "
                              f"outside the classes {gating.get('classes')} and stages {gating.get('stages')} "
                              f"that {name} gates on")
                continue
            covering, reasons = self.covering(entry, level, lane)
            if not reasons:
                errors.append(f"{spot}: {detector} gates {name} at {level} without a committed calibration record")
                continue
            if not covering:
                detail = "; ".join(f"{Path(path).name}: {', '.join(found)}" for path, found in reasons.items())
                errors.append(f"{spot}: {detector} gates {name} at {level} without a qualified record whose scope "
                              f"covers the lane ({detail})")
        return errors


def lane_gate_errors(root: Path = REPO) -> list[str]:
    """Every problem in the lane-gates file; empty when each gate is backed by a covering record."""
    sources = Sources.load(root)
    errors = sources.file_errors()
    if errors:
        return errors
    for name, lane in sources.config["lanes"].items():
        errors.extend(sources.lane_errors(name, lane))
    return errors


# --------------------------------------------------------------------------- #
# The gates of one lane
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LaneGate:
    """One gate of a lane with the committed record that backs it: the record's threshold is the gate's."""

    detector: str
    level: str
    entry: Mapping[str, Any]
    record: Mapping[str, Any]
    record_file: str


def _record_preference(level: str, item: tuple[str, Mapping[str, Any]]) -> tuple:
    """Among covering records: the gate's own level first, then the latest committed plan."""
    path, record = item
    committed = str((record.get("evidence") or {}).get("planCommittedAt") or "")
    return record["level"] == level, committed, path


def lane_config(root: Path, lane_name: str) -> Mapping[str, Any]:
    """One lane's entry of the lane-gates file (its scope and gates), without checking its records."""
    sources = Sources.load(root)
    errors = sources.file_errors()
    if errors:
        raise GateError(f"{GATES}: {errors[0]}")
    lane = sources.config["lanes"].get(lane_name)
    if not isinstance(lane, Mapping) or not isinstance(lane.get("scope"), Mapping):
        raise GateError(f"{GATES} names no lane {lane_name!r}")
    return lane


def lane_gates(root: Path, lane_name: str) -> tuple[Mapping[str, Any], list[LaneGate]]:
    """The lane's entry and each of its gates with its qualifying record; refused like `validate` when a gate has
    no committed record that qualified it at its level and covers the lane."""
    sources = Sources.load(root)
    errors = sources.file_errors()
    lane = sources.config["lanes"].get(lane_name) if not errors else None
    if not errors and lane is None:
        errors = [f"names no lane {lane_name!r}"]
    errors = errors or sources.lane_errors(lane_name, lane)
    if errors:
        raise GateError(f"{GATES}: " + "; ".join(errors))
    gates = []
    for gate in lane["gates"]:
        entry = sources.entries[gate["detector"]]
        covering, _ = sources.covering(entry, gate["level"], lane)
        path, record = max(covering, key=lambda item: _record_preference(gate["level"], item))
        rule = (record.get("threshold") or {}).get("rule")
        if rule not in thresholds.RULES or record.get("direction") not in registry_lib.DIRECTIONS:
            raise GateError(f"{Path(path).name} of {gate['detector']} pre-registers no known rule and direction")
        gates.append(LaneGate(gate["detector"], gate["level"], entry, record, Path(path).name))
    return lane, gates


def lane_has_fail_gate(root: Path, lane_name: str) -> bool:
    """Whether the lane names a gate at fail: then gates that cannot be computed fail the lane."""
    try:
        lane = lane_config(root, lane_name)
    except GateError:
        return False
    return any(isinstance(gate, Mapping) and gate.get("level") == "fail" for gate in lane.get("gates") or ())


def gate_judges(gates: Sequence[LaneGate], languages: Sequence[str]) -> list[str]:
    """The panel judges the gates read in these languages: each score group's panel components and the content
    voters it requires complete (Stage 0 is not a panel judge)."""
    judges: set[str] = set()
    for gate in gates:
        for language in languages:
            if not registry_lib.in_scope(gate.entry, language):
                continue
            group = registry_lib.group_for(gate.entry, language) or {}
            judges.update(component["judge"] for component in group.get("components") or ()
                          if component.get("source") in registry_lib.PANEL_SOURCES)
            judges.update(group.get("requiresComplete") or ())
    judges.discard(registry_lib.STAGE0_JUDGE)
    return sorted(judges)


def needs_stage0(gates: Sequence[LaneGate]) -> bool:
    return any(registry_lib.needs_measurements(gate.entry) for gate in gates)


def raw_output_judges(gates: Sequence[LaneGate]) -> list[str]:
    return sorted({judge for gate in gates for judge in calibration.raw_output_judges(gate.entry)})


# --------------------------------------------------------------------------- #
# The lane takes manifest
# --------------------------------------------------------------------------- #

def _inside(path: Path, directory: Path) -> str | None:
    """`path` relative to `directory` (POSIX), or None when it lies outside it."""
    try:
        return path.resolve().relative_to(directory.resolve()).as_posix()
    except ValueError:
        return None


def write_lane_takes(lane_name: str, takes: Sequence[Mapping[str, Any]], *, run_id: str, directory: Path,
                     root: Path = REPO) -> Path:
    """Write the lane takes manifest `<directory>/audio-qc-takes.json` and return its path.

    Each take names its `takeID`, `language`, `mode`, and, when a gate can score
    it, its `wav` (inside `directory`), the `text` it was generated from and
    optionally its `reference` clip (a clone's), `voice` and `scriptID`. A take
    that is a `control` (a negative control: a deliberate defect, another
    voice), carries an `exclude` reason, or lies outside the lane's languages or
    modes goes under `excluded` with its reason; the others are the manifest's
    takes, which the panel and Stage 0 measure. A WAV whose bytes differ from a
    `wavSHA256` the take declares is refused.
    """
    scope = lane_config(root, lane_name)["scope"]
    directory = Path(directory)
    gated, excluded, seen = [], [], set()
    for take in takes:
        take_id = take.get("takeID")
        if not isinstance(take_id, str) or not TAKE_ID.fullmatch(take_id) or take_id in seen:
            raise GateError("every lane take has a unique takeID of letters, digits, '.', '_' and '-'")
        seen.add(take_id)
        language, mode = take.get("language"), take.get("mode")
        reason = take.get("exclude") or ("negative-control" if take.get("control") else None) \
            or ("language-outside-lane" if language not in scope["languages"] else None) \
            or ("mode-outside-lane" if mode not in scope["modes"] else None)
        if reason is not None:
            if reason not in EXCLUSION_REASONS:
                raise GateError(f"{take_id}: an excluded take's reason is one of {EXCLUSION_REASONS}")
            excluded.append({"takeID": take_id, "language": language if isinstance(language, str) else None,
                             "mode": mode if isinstance(mode, str) else None, "reason": reason})
            continue
        wav = Path(take.get("wav") or "")
        relative = _inside(wav, directory) if take.get("wav") else None
        if relative is None or not wav.is_file():
            raise GateError(f"{take_id}: its WAV is missing or outside the lane's run directory")
        digest = calibration.file_sha256(wav)
        if take.get("wavSHA256") not in (None, digest):
            raise GateError(f"{take_id}: its WAV's bytes differ from the digest the lane recorded")
        text = take.get("text")
        if not isinstance(text, str) or not text.strip():
            raise GateError(f"{take_id}: a scored lane take names the text it was generated from")
        entry: dict[str, Any] = {
            "takeID": take_id, "family": take_id, "status": "generated", "language": language, "mode": mode,
            "scriptID": str(take.get("scriptID") or take_id), "text": text,
            "textSHA256": language_metrics.text_sha256(text), "wavPath": relative, "wavSHA256": digest,
        }
        if isinstance(take.get("voice"), Mapping):
            entry["voice"] = dict(take["voice"])
        if take.get("reference") is not None:
            reference = Path(take["reference"])
            if not reference.is_file():
                raise GateError(f"{take_id}: its reference clip is missing")
            # Relative beside the manifest when it lies there, else absolute (a saved voice's clip).
            entry["reference"] = {"wavPath": _inside(reference, directory) or str(reference.resolve()),
                                  "wavSHA256": calibration.file_sha256(reference)}
        gated.append(entry)
    manifest: dict[str, Any] = {"schemaVersion": 1, "kind": calibration.N3_KIND, "generator": TAKES_GENERATOR,
                                "lane": lane_name, "runID": run_id, "takes": gated, "excluded": excluded}
    manifest["manifestDigest"] = sha256_json(manifest, ascii=False)
    path = directory / TAKES_FILE
    atomic_json(path, manifest, ascii=False, allow_nan=False)
    return path


def load_lane_takes(path: Path, lane_name: str) -> dict:
    """A lane takes manifest of this lane, bound to its own digest."""
    manifest = load_json(path, "the lane takes manifest")
    if not isinstance(manifest, dict) or manifest.get("kind") != calibration.N3_KIND \
            or manifest.get("schemaVersion") != 1 or manifest.get("generator") != TAKES_GENERATOR:
        raise GateError(f"{Path(path).name} is not a lane takes manifest ({TAKES_GENERATOR})")
    if manifest.get("lane") != lane_name:
        raise GateError(f"{Path(path).name} holds the takes of {manifest.get('lane')!r}, not {lane_name!r}")
    body = {key: value for key, value in manifest.items() if key != "manifestDigest"}
    if manifest.get("manifestDigest") != sha256_json(body, ascii=False):
        raise GateError(f"{Path(path).name} does not match its manifestDigest (edited after it was written)")
    if not isinstance(manifest.get("takes"), list) or not isinstance(manifest.get("excluded"), list):
        raise GateError(f"{Path(path).name} lists its takes and its excluded takes")
    return manifest


def language_bench_takes(run_dir: Path) -> tuple[str, list[dict]]:
    """The language bench's takes from its immutable run plan and its independent-ASR manifest, which binds each
    take's WAV to the digest the engine published: (run id, takes). A control cell (an expected failure, or a
    script in another language than the one expected) is a negative control; a planned take without a row (its
    output is not verified) has no output to gate."""
    import independent_asr
    import language_bench_evidence

    plan = load_json(run_dir / LANGUAGE_PLAN, "the language run plan")
    try:
        planned = language_bench_evidence.validate_plan(plan)
        manifest = independent_asr.validate_manifest(load_json(run_dir / LANGUAGE_ASR_MANIFEST,
                                                               "the independent-ASR manifest"))
    except (language_bench_evidence.EvidenceError, independent_asr.IndependentASRError) as error:
        raise GateError(str(error)) from error
    if manifest.get("runID") != plan["runID"]:
        raise GateError("the independent-ASR manifest belongs to another run than the plan")
    rows = {row["id"]: row for row in manifest["rows"]}
    takes = []
    for take in planned:
        # A normal plan's takes are its cells; a diagnostic cohort repeats a cell per seed.
        take_id = take["cellID"] if plan["kind"] == "languageBenchmark" else take["childRunID"]
        row = rows.get(take["cellID"]) or rows.get(take["childRunID"])
        language, mode = take.get("expectedHint"), take.get("mode")
        if row is None:
            takes.append({"takeID": take_id, "language": language, "mode": mode, "exclude": "no-output"})
            continue
        speaker, brief = take.get("customSpeakerID"), take.get("designInstructionDigest")
        voice = {"kind": "builtin", "id": speaker} if mode == "custom" and speaker else \
            {"kind": "design", "briefID": f"brief-{str(brief)[:16]}"} if mode == "design" and brief else None
        takes.append({
            "takeID": take_id, "wav": Path(row["audioPath"]), "wavSHA256": row["audioSHA256"],
            "language": row["expectedLanguage"], "mode": mode, "text": row["referenceText"],
            "scriptID": f"{take.get('scriptLang')}-corpus", "voice": voice,
            "control": row.get("expectedOutcome", "pass") == "fail" or take.get("scriptLang") != row["expectedLanguage"],
        })
    return str(plan["runID"]), takes


# --------------------------------------------------------------------------- #
# evaluate
# --------------------------------------------------------------------------- #

def record_threshold(record: Mapping[str, Any], language: str) -> float | None:
    """The threshold the record pre-registered for the take's stratum (its language, or pooled)."""
    threshold = record.get("threshold") or {}
    key = registry_lib.POOLED if threshold.get("strata") == registry_lib.POOLED else language
    value = (threshold.get("values") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def evidence_agreement(document: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, bool]:
    """Whether the lane's evidence came from what the record qualified: the same judge output identities, metric
    reductions, scoring code and orchestrator."""
    evidence = record.get("evidence") or {}
    recorded = {item.get("judge"): set(item.get("outputIdentities") or ()) for item in record.get("judges") or ()
                if isinstance(item, Mapping)}
    judges = all(set(values) <= recorded.get(judge, set())
                 for judge, values in (document.get("judgeIdentities") or {}).items())
    reductions = evidence.get("judgeMetrics") or {}
    metrics = all(pair in (reductions.get(judge) or [])
                  for judge, pairs in ((document.get("evidenceIdentity") or {}).get("judgeMetrics") or {}).items()
                  for pair in pairs)
    orchestrators = set((document.get("evidenceIdentity") or {}).get("orchestratorSHA256") or ())
    return {"judgeIdentities": judges, "judgeMetrics": metrics,
            "scoringCode": document.get("scoringCodeSHA256") == evidence.get("scoringCodeSHA256"),
            "orchestrator": orchestrators <= set(evidence.get("orchestratorSHA256") or ())}


def drifted(agreement: Mapping[str, bool] | None) -> bool:
    """Evidence another judge, metric reduction or scoring code produced than the record's (the orchestrator's
    own digest is reported only: the metric reductions name what shapes a panel metric)."""
    return agreement is not None and not all(agreement[key] for key in ("judgeIdentities", "judgeMetrics",
                                                                         "scoringCode"))


def gate_result(gate: LaneGate, take: Mapping[str, Any], unit: Mapping[str, Any] | None,
                lane: Mapping[str, Any]) -> dict:
    """One gate's result on one take: its score against the record's threshold, or the reason it abstained."""
    record, scope = gate.record, lane["scope"]
    language, mode = take.get("language"), take.get("mode")
    result = {"detector": gate.detector, "level": gate.level, "score": None, "threshold": None,
              "direction": record["direction"], "flagged": None, "abstain": None, "components": {}}
    modes = record_modes(record, gate.entry)
    reason = ("language-outside-lane" if language not in scope["languages"] else
              "mode-outside-lane" if mode not in scope["modes"] else
              "language-outside-record" if language not in (record.get("scope") or {}).get("languages", ()) else
              "mode-outside-record" if modes is not None and mode not in modes else None)
    if reason is not None:
        return {**result, "abstain": reason}
    threshold = record_threshold(record, language)
    if threshold is None:
        return {**result, "abstain": "no-threshold"}
    result["threshold"] = threshold
    if unit is None:
        return {**result, "abstain": "no-evidence"}
    result["components"] = dict(unit.get("components") or {})
    if unit.get("score") is None:
        return {**result, "abstain": unit.get("abstain") or "no-score"}
    return {**result, "score": unit["score"],
            "flagged": registry_lib.component_alarm(unit["score"], threshold, record["direction"])}


def _worst(verdicts: Sequence[str]) -> str:
    return max(verdicts, key=VERDICTS.index, default="pass")


def evaluate(lane_name: str, takes_path: Path, *, bundle: Path | None = None, measurements: Path | None = None,
             raw_outputs: Sequence[Path] = (), root: Path = REPO) -> dict:
    """The lane's gate result (`gates.json`) over a lane takes manifest and the evidence its gates read.

    Every gating detector is scored on every take by `build_scores`, the code
    path its record was confirmed with, and compared with the record's
    pre-registered threshold. A detector that reads panel evidence needs the
    bundle the orchestrator wrote over this manifest, one that reads Stage 0
    the manifest's measurements, one that reduces a raw output that judge's
    export. Refused (GateError) when a gate has no qualifying record or an
    input is missing or bound to other takes.
    """
    root = Path(root)
    lane, gates = lane_gates(root, lane_name)
    manifest = load_lane_takes(takes_path, lane_name)
    takes = {take["takeID"]: take for take in manifest["takes"]}
    try:
        cohort = calibration.load_cohort(takes_path) if takes else None
        panel = calibration.Bundle(bundle) if bundle is not None else None
        measured = calibration.load_measurements(measurements) if measurements is not None else None
        exports = [calibration.load_raw_outputs(path) for path in raw_outputs]
    except calibration.CalibrationError as error:
        raise GateError(str(error)) from error
    results: dict[str, list[dict]] = {take_id: [] for take_id in takes}
    detectors = []
    for gate in gates:
        entry = gate.entry
        units: dict[str, Mapping[str, Any]] = {}
        agreement = None
        if cohort is not None:
            if registry_lib.needs_panel(entry) and panel is None:
                raise GateError(f"{gate.detector} reads panel evidence: pass the lane panel's bundle")
            if registry_lib.needs_measurements(entry) and measured is None:
                raise GateError(f"{gate.detector} reads Stage 0: pass the lane takes' measurements.json")
            wanted = calibration.raw_output_judges(entry)
            try:
                document = calibration.build_scores(
                    entry, cohort, role="lane",
                    bundle=panel if registry_lib.needs_panel(entry) else None,
                    measurements=measured if registry_lib.needs_measurements(entry) else None,
                    raw_outputs=[export for export in exports if export["judge"] in wanted])
            except (calibration.CalibrationError, registry_lib.DetectorError) as error:
                raise GateError(f"{gate.detector}: {error}") from error
            units = {unit["unitID"]: unit for unit in document["units"]}
            agreement = evidence_agreement(document, gate.record)
        effective = "warn" if gate.level == "fail" and drifted(agreement) else gate.level
        scored = []
        for take_id, take in takes.items():
            outcome = gate_result(gate, take, units.get(take_id), lane)
            results[take_id].append({**outcome, "effectiveLevel": effective})
            scored.append(outcome)
        abstained: dict[str, int] = {}
        for outcome in scored:
            if outcome["abstain"] is not None:
                abstained[outcome["abstain"]] = abstained.get(outcome["abstain"], 0) + 1
        threshold = gate.record["threshold"]
        detectors.append({
            "detector": gate.detector, "level": gate.level, "effectiveLevel": effective,
            "record": {"file": gate.record_file, "planSHA256": gate.record["planSHA256"],
                       "operatingPoint": gate.record["operatingPoint"], "level": gate.record["level"]},
            "rule": threshold["rule"], "strata": threshold["strata"], "direction": gate.record["direction"],
            "thresholds": {key: value for key, value in sorted(threshold["values"].items())
                           if key == registry_lib.POOLED or key in lane["scope"]["languages"]},
            "evidenceMatchesRecord": agreement,
            "counts": {"scored": sum(1 for outcome in scored if outcome["score"] is not None),
                       "flagged": sum(1 for outcome in scored if outcome["flagged"]),
                       "abstained": dict(sorted(abstained.items()))},
        })
    rows = []
    for take_id, take in takes.items():
        flagged = [outcome["effectiveLevel"] for outcome in results[take_id] if outcome["flagged"]]
        rows.append({"take": take_id, "language": take.get("language"), "mode": take.get("mode"),
                     "excluded": None, "verdict": _worst(flagged),
                     "scored": sum(1 for outcome in results[take_id] if outcome["score"] is not None),
                     "gates": [{key: value for key, value in outcome.items() if key != "effectiveLevel"}
                               for outcome in results[take_id]]})
    gated_verdicts = [row["verdict"] for row in rows]
    # A take no gate may score (a negative control, a language or mode outside the lane) has no verdict.
    for item in manifest["excluded"]:
        rows.append({"take": item.get("takeID"), "language": item.get("language"), "mode": item.get("mode"),
                     "excluded": item.get("reason"), "verdict": None, "scored": 0,
                     "gates": [{"detector": gate.detector, "level": gate.level, "score": None, "threshold": None,
                                "direction": gate.record["direction"], "flagged": None,
                                "abstain": item.get("reason"), "components": {}} for gate in gates]})
    run_id = manifest.get("runID")
    result = {
        "schema": RESULT_SCHEMA, "kind": RESULT_KIND,
        "lane": lane_name, "runID": run_id if is_token(run_id) else sha256_json(run_id),
        "verdict": _worst(gated_verdicts),
        "inputs": {
            "takesManifestSHA256": calibration.file_sha256(takes_path),
            "manifestDigest": manifest["manifestDigest"],
            "bundleDigest": panel.identity()["bundleDigest"] if panel is not None else None,
            "measurementsSHA256": measured["fileSHA256"] if measured is not None else None,
            "rawOutputsSHA256": sorted(export["fileSHA256"] for export in exports),
            "laneGatesSHA256": calibration.file_sha256(root / GATES),
            "detectorRegistrySHA256": calibration.file_sha256(root / calibration.REGISTRY),
            "scoringCodeSHA256": registry_lib.scoring_code_sha256(),
        },
        "detectors": detectors,
        "counts": {"takes": len(rows), "gated": len(takes), "excluded": len(manifest["excluded"]),
                   "flagged": sum(1 for verdict in gated_verdicts if verdict != "pass"),
                   "unscored": sum(1 for row in rows if row["excluded"] is None and not row["scored"]),
                   "scored": sum(item["counts"]["scored"] for item in detectors),
                   "byVerdict": {name: gated_verdicts.count(name) for name in VERDICTS}},
        "takes": rows,
    }
    errors = result_errors(result)
    if errors:
        raise GateError("the gate result is not privacy-safe: " + "; ".join(errors[:3]))
    return result


def result_errors(result: Mapping[str, Any]) -> list[str]:
    """Errors in a gate result: its kind and verdict, and any text, path or unsafe string anywhere in it."""
    errors = []
    if result.get("kind") != RESULT_KIND or result.get("schema") != RESULT_SCHEMA:
        errors.append(f"a gate result declares {RESULT_SCHEMA} and kind {RESULT_KIND}")
    if result.get("verdict") not in VERDICTS:
        errors.append(f"verdict is one of {VERDICTS}")
    return errors + privacy_errors(dict(result), "gates")


def check_output(path: Path, root: Path = REPO) -> Path:
    """A gate result is lane evidence: never written into the tree outside build/."""
    resolved, root = Path(path).resolve(), Path(root).resolve()
    if resolved.is_relative_to(root) and not resolved.is_relative_to(root / "build"):
        raise GateError(f"{path} is inside the repository; write the gate result under build/ (untracked)")
    return resolved


def write_result(result: Mapping[str, Any], path: Path, root: Path = REPO) -> Path:
    errors = result_errors(result)
    if errors:
        raise GateError("the gate result is not privacy-safe: " + "; ".join(errors[:3]))
    output = check_output(path, root)
    atomic_json(output, dict(result), allow_nan=False)
    return output


def summary_lines(result: Mapping[str, Any], path: Path | None = None) -> list[str]:
    """What a lane prints of its gates: the verdict, each detector's counts, and each flag."""
    counts = result["counts"]
    lines = [f"audio-qc gates · {result['lane']}: {result['verdict'].upper()} · {counts['gated']} takes gated "
             f"({counts['unscored']} scored by no gate), {counts['excluded']} excluded, {counts['flagged']} flagged"]
    for item in result["detectors"]:
        abstained = ", ".join(f"{reason} {count}" for reason, count in item["counts"]["abstained"].items()) or "none"
        agreement = item["evidenceMatchesRecord"]
        drift = ", ".join(key for key, value in (agreement or {}).items() if not value)
        level = item["level"] if item["effectiveLevel"] == item["level"] else \
            f"{item['level']}, flags at {item['effectiveLevel']}"
        lines.append(f"  {item['detector']} ({level}; {item['record']['file']}): {item['counts']['scored']} scored, "
                     f"{item['counts']['flagged']} flagged; abstained: {abstained}"
                     + (f"; evidence differs from the record's: {drift}" if drift else ""))
    for row in result["takes"]:
        for outcome in row["gates"]:
            if outcome["flagged"]:
                sign = ">" if outcome["direction"] == "above" else "<"
                lines.append(f"  flag {row['take']} ({row['language']}/{row['mode']}): {outcome['detector']} "
                             f"{outcome['score']:.4g} {sign} {outcome['threshold']:.4g}")
    if path is not None:
        lines.append(f"  -> {path}")
    return lines


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #

def default_cache_root(lane_name: str, run_id: str) -> Path:
    """The run's own panel cache root under the analysis cache's per-panel roots."""
    cache = Path(os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE") or DEFAULT_ANALYSIS_CACHE)
    name = re.sub(r"[^A-Za-z0-9._-]", "-", f"lane-{lane_name}-{run_id}")[:160]
    return cache / PANEL_ROOTS / name


def _step(runner: Callable[..., Any], argv: Sequence[Any], logs: Path, name: str) -> None:
    """One tool of the panel run; its output goes to `audio-qc/logs/<name>.log`."""
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / f"{name}.log").open("w", encoding="utf-8") as handle:
        completed = runner([str(item) for item in argv], stdout=handle, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise GateError(f"{name} exited {completed.returncode} (see {OUTPUT_DIRECTORY}/logs/{name}.log)")


def run_gates(lane_name: str, run_dir: Path, *, takes: Sequence[Mapping[str, Any]] | None = None,
              run_id: str | None = None, cache_root: Path | None = None, jobs: int | None = None,
              root: Path = REPO, runner: Callable[..., Any] = subprocess.run,
              python: str = sys.executable) -> tuple[dict, Path]:
    """Compute a lane run's gates after its generator has exited, and write `<run_dir>/audio-qc/gates.json`.

    `takes` are the lane's takes (`write_lane_takes`); the language bench's come
    from its run plan and independent-ASR manifest when none are given, and
    another lane's from the takes manifest it already wrote. Refused before any
    model runs when a gate has no qualifying record or the gates already ran on
    this run directory. Returns the result and the path written.
    """
    run_dir = Path(run_dir)
    _, gates = lane_gates(root, lane_name)
    output = run_dir / OUTPUT_DIRECTORY
    if output.exists():
        raise GateError(f"{OUTPUT_DIRECTORY}/ already exists in this run directory: the gates ran on it; move it "
                        "aside to run them again")
    takes_path = run_dir / TAKES_FILE
    if takes is None and lane_name == "language-bench":
        run_id, takes = language_bench_takes(run_dir)
    if takes is not None:
        takes_path = write_lane_takes(lane_name, takes, run_id=str(run_id or run_dir.name), directory=run_dir,
                                      root=root)
    elif not takes_path.is_file():
        raise GateError(f"{lane_name} writes its takes ({TAKES_FILE}) before its gates run")
    manifest = load_lane_takes(takes_path, lane_name)
    output.mkdir(parents=True)
    logs = output / "logs"
    bundle = measurements = None
    exports: list[Path] = []
    if manifest["takes"]:
        languages = sorted({take["language"] for take in manifest["takes"]})
        judges = gate_judges(gates, languages)
        cache = Path(cache_root) if cache_root is not None else default_cache_root(lane_name, manifest["runID"])
        if judges:
            panel_manifest = output / "panel-manifest.json"
            _step(runner, [python, ORCHESTRATOR, "manifest", "--from-calibration-takes", takes_path,
                           "--output", panel_manifest], logs, "panel-manifest")
            bundle = output / "panel-bundle"
            flags = [item for judge in judges for item in ("--judge", judge)]
            _step(runner, [python, ORCHESTRATOR, "run", "--manifest", panel_manifest, *flags, "--cache-root", cache,
                           "--bundle", bundle], logs, "panel")
            for judge in raw_output_judges(gates):
                export = output / f"raw-outputs-{judge}.json"
                _step(runner, [python, CALIBRATION_SET, "raw-outputs", "--takes", takes_path, "--bundle", bundle,
                               "--judge", judge, "--output", export, "--cache-root", cache], logs, f"raw-{judge}")
                exports.append(export)
        if needs_stage0(gates):
            stage0 = output / "stage0"
            _step(runner, [python, CALIBRATION_SET, "score", "--takes", takes_path, "--output", stage0,
                           *(["--jobs", jobs] if jobs else [])], logs, "stage0")
            measurements = stage0 / "measurements.json"
    result = evaluate(lane_name, takes_path, bundle=bundle, measurements=measurements, raw_outputs=exports,
                      root=root)
    return result, write_result(result, output / RESULT_FILE, root)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def command_validate(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    try:
        errors = lane_gate_errors(root)
    except GateError as error:
        errors = [str(error)]
    for error in errors:
        print(f"audio-qc lane gates: {GATES}: {error}", file=sys.stderr)
    if errors:
        return 1
    lanes = load_json(root / GATES, "the lane gates")["lanes"]
    count = sum(len(lane["gates"]) for lane in lanes.values())
    print(f"audio-qc lane gates: {len(lanes)} lanes, {count} gates, each backed by a qualified record covering "
          "its lane")
    return 0


def _report(result: Mapping[str, Any], path: Path) -> int:
    for line in summary_lines(result, path):
        print(line)
    return EXIT_CODES[result["verdict"]]


def _failed(args: argparse.Namespace, error: Exception) -> int:
    fail = lane_has_fail_gate(Path(args.repo_root), args.lane)
    print(f"audio-qc gates · {args.lane}: {'FAIL' if fail else 'ERROR'} · not computed: {error}", file=sys.stderr)
    return EXIT_CODES["fail"] if fail else EXIT_ERROR


def command_evaluate(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    try:
        result = evaluate(args.lane, args.takes, bundle=args.bundle, measurements=args.measurements,
                          raw_outputs=args.raw_outputs or (), root=root)
        path = write_result(result, args.output, root)
    except GateError as error:
        return _failed(args, error)
    return _report(result, path)


def command_run(args: argparse.Namespace) -> int:
    try:
        result, path = run_gates(args.lane, args.run_dir, cache_root=args.cache_root, jobs=args.jobs,
                                 root=Path(args.repo_root))
    except GateError as error:
        return _failed(args, error)
    return _report(result, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="refuse a gate without a qualified scope-covering record")
    evaluate_parser = commands.add_parser("evaluate", help="score a lane's takes against its gates")
    evaluate_parser.add_argument("--lane", required=True)
    evaluate_parser.add_argument("--takes", type=Path, required=True, help=f"the lane takes manifest ({TAKES_FILE})")
    evaluate_parser.add_argument("--bundle", type=Path, help="the panel bundle over that manifest")
    evaluate_parser.add_argument("--measurements", type=Path, help="Stage 0 measurements.json over that manifest")
    evaluate_parser.add_argument("--raw-outputs", type=Path, action="append", help="a raw-output export (repeatable)")
    evaluate_parser.add_argument("--output", type=Path, required=True, help="the gate result (gates.json)")
    run_parser = commands.add_parser("run", help="run the gates' judges and Stage 0 over a lane run, then evaluate")
    run_parser.add_argument("--lane", required=True)
    run_parser.add_argument("--run-dir", type=Path, required=True, help="the lane run's artifact directory")
    run_parser.add_argument("--cache-root", type=Path,
                            help="the panel's cache root (default: <analysis cache>/confirmation/lane-<lane>-<run>)")
    run_parser.add_argument("--jobs", type=int, help="Stage 0 worker processes (default: half the cores)")
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return command_evaluate(args)
    if args.command == "run":
        return command_run(args)
    return command_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
