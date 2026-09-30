#!/usr/bin/env python3
"""Oracle ladders for pYIN, HNR and the advisory quality composite (AQ-08).

The ladders and their pass criteria live in `lib.qc_qualification.ladders`
(audit 2026-09-25 sections 4.4, 4.6 and 5.8). This command writes them, scores
them and records the result; it loads no model itself:

- **build** renders one ladder (or all three) under the owned build root
  (`build/artifacts/diagnostics/audio-qc-oracle-ladders/<ladder>/` by default,
  never a tracked path): `wav/<clip>.wav`, `truth.json` (every clip's PCM and
  WAV digests and its truth, bound by the ladder's golden `clipsSHA256`) and,
  for the two ladders that need judges (pyin, quality), `manifest.json`, an
  orchestrator language-lane manifest of procedural canaries (no reference
  text) that `scripts/audio_qc_orchestrator.py run --manifest` accepts as is.
  `--quality-sources` swaps the procedural quality sources for recordings from
  an orchestrator manifest (N1 or N3 takes), whose reference text then rides in
  the private manifest so a recognizer's WER can enter the composite.
- **evaluate** scores a built ladder: pyin from the orchestrator bundle's
  records and each clip's per-frame F0 in the run's L1 cache entry (the bundle
  keeps only statistics); quality from the bundle's Audiobox PQ and DNSMOS OVRL
  (and `--wer-judge`'s error rate); hnr in-process, running the Stage 1
  prosody analyzer (`prosody@3`, the frozen proxy of AQ-F16) and the
  window-corrected candidate (`audio_phonation.py`) on the ladder's WAVs, and,
  with `--oracle-hnr`, comparing them with an isolated Parselmouth run's
  readings (never linked or run from here). It writes `evaluation.json` beside
  the truth: clip ids, digests and numbers only.
- **report** combines evaluations into one privacy-safe record
  (`vocello.audioqc.oracle-ladder-report/1`), validated by the evidence
  privacy walker, written once.

Exit status: 0 when every evaluated ladder passes (`pass` or
`pass-provisional`), 2 when one fails or is incomplete, 1 on a usage, input or
integrity error.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
import wave

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.jsonio import atomic_json, sha256_file, utc_now  # noqa: E402
from lib.language_metrics import LANGUAGE_LOCALE_CODES, text_sha256  # noqa: E402
from lib.qc_pipeline.evidence import (  # noqa: E402
    is_sha256,
    is_token,
    privacy_errors,
    untracked_location_errors,
    validate_private_bundle,
)
from lib.qc_qualification import ladders as L  # noqa: E402
from lib.qc_qualification.recordings import RecordingError, load_recording, write_pcm16_wav  # noqa: E402

REPO = SCRIPT_DIR.parent
DEFAULT_ROOT = Path(os.environ.get("QVOICE_ARTIFACTS_DIAGNOSTICS", REPO / "build/artifacts/diagnostics")) \
    / "audio-qc-oracle-ladders"
DEFAULT_CACHE_ROOT = Path(os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"))
TRUTH_FILE = "truth.json"
MANIFEST_FILE = "manifest.json"
EVALUATION_FILE = "evaluation.json"
# Pitch and quality judges are language-free; the orchestrator manifest still names a product language.
LADDER_LANGUAGE = "english"
LADDER_ROLE = "oracle-ladder"
DEFAULT_MAX_QUALITY_SOURCES = 8
GENERATOR_SOURCES = (SCRIPT_DIR / "lib/qc_qualification/ladders.py", Path(__file__).resolve())
MAXIMUM_REPORT_BYTES = 256 * 1024


class LadderCommandError(ValueError):
    """A ladder cannot be built, evaluated or reported as asked."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LadderCommandError(f"cannot read {Path(path).name}: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise LadderCommandError(f"{Path(path).name} must contain an object")
    return value


def generator_digests() -> dict[str, str]:
    return {path.name: sha256_file(path) for path in GENERATOR_SOURCES}


def _require_untracked(directory: Path) -> None:
    errors = untracked_location_errors(directory, REPO)
    if errors:
        raise LadderCommandError("ladder outputs live under the build root or outside the repository, "
                                 "never in a tracked path")


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def check_pyin_grid(registry: Mapping[str, Any]) -> None:
    """The ladder's frame grid must be the registry's pitch.pyin@1 configuration."""
    configuration = ((registry.get("judges") or {}).get(L.PYIN_JUDGE) or {}).get("configuration") or {}
    expected = {"sampleRateHz": L.PYIN_RATE, "hopLength": L.PYIN_HOP, "frameLength": L.PYIN_FRAME, "center": True}
    differing = sorted(key for key, value in expected.items() if configuration.get(key) != value)
    if differing:
        raise LadderCommandError(f"{L.PYIN_JUDGE}'s configuration differs from the ladder's grid "
                                 f"({', '.join(differing)}): the ladder needs a new version")


def _registry() -> dict[str, Any]:
    from audio_qc_judges import JudgeRegistryError, load_registry

    try:
        return load_registry()
    except JudgeRegistryError as error:
        raise LadderCommandError(str(error)) from None


def recording_sources(manifest_path: Path, limit: int) -> tuple[list[tuple[str, Any, dict[str, Any]]], dict[str, str]]:
    """Quality sources from an orchestrator manifest's takes: (id, 24 kHz fixture, truth extras), and texts by id.

    Takes are chosen by audio digest (deterministic), at most `limit`. A take's
    text stays private: only its digest enters the truth.
    """
    manifest = _read(manifest_path)
    if manifest.get("schema") != "vocello.audioqc.manifest/1" or not isinstance(manifest.get("takes"), list):
        raise LadderCommandError("--quality-sources names an orchestrator manifest (vocello.audioqc.manifest/1)")
    takes = sorted((take for take in manifest["takes"] if isinstance(take, dict) and is_sha256(take.get("audioSHA256"))),
                   key=lambda take: take["audioSHA256"])
    sources, texts, seen = [], {}, set()
    for take in takes:
        if len(sources) >= limit:
            break
        digest = take["audioSHA256"]
        if digest in seen:
            continue
        seen.add(digest)
        path = Path(str(take.get("audioPath")))
        try:
            with wave.open(str(path), "rb") as reader:
                rate = reader.getframerate()
            source_id = f"rec-{digest[:12]}"
            fixture, _sha = load_recording(path, take_id=source_id, family=source_id, stratum="recording",
                                           expected_sha256=digest, source_rate=rate)
        except (OSError, EOFError, wave.Error, RecordingError) as error:
            raise LadderCommandError(f"a quality source is unusable: {type(error).__name__}") from None
        language = take.get("language")
        text = take.get("referenceText")
        extra: dict[str, Any] = {"language": language if language in LANGUAGE_LOCALE_CODES else LADDER_LANGUAGE,
                                 "textSHA256": text_sha256(text) if isinstance(text, str) and text.strip() else None}
        if isinstance(text, str) and text.strip():
            texts[source_id] = text
        sources.append((source_id, fixture, extra))
    if not sources:
        raise LadderCommandError("--quality-sources lists no usable take")
    return sources, texts


def orchestrator_manifest(ladder: str, directory: Path, entries: Sequence[Mapping[str, Any]], digest: str,
                          texts: Mapping[str, str] | None = None) -> dict[str, Any]:
    """A language-lane manifest of the ladder's clips, as `audio_qc_orchestrator.py run --manifest` reads it."""
    import audio_qc_orchestrator as orchestrator

    texts = texts or {}
    takes = []
    for entry in entries:
        truth = entry["truth"]
        text = texts.get(str(truth.get("source"))) if ladder == "quality" else None
        takes.append(orchestrator._take(
            take_id=entry["clipID"], generation_id=entry["clipID"],
            audio=str((directory / entry["wav"]).resolve()), audio_sha256=entry["wavSHA256"],
            language=truth.get("language") or LADDER_LANGUAGE, reference_text=text,
            script_sha256=text_sha256(text) if text else None, role=LADDER_ROLE,
            duration=entry["durationSeconds"], cell_id=f"oracle-ladder-{ladder}",
        ))
    return orchestrator.validate_manifest({
        "schema": orchestrator.MANIFEST_SCHEMA,
        "runID": f"oracle-ladder-{ladder}-v{L.LADDER_VERSION}-{digest[:12]}",
        "lane": "language-bench", "platform": "macos", "generationProcessExited": True,
        "source": {"kind": "oracle-ladder", "ladder": ladder, "sha256": digest}, "takes": takes, "pairs": [],
    })


def _built(directory: Path, digest: str) -> dict[str, Any] | None:
    """The existing build when it is this exact ladder with every WAV intact; refuse any other content."""
    truth_path = directory / TRUTH_FILE
    if not truth_path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise LadderCommandError(f"{directory.name} holds an incomplete or foreign build; choose a new --root")
        return None
    truth = _read(truth_path)
    if truth.get("clipsSHA256") != digest:
        raise LadderCommandError(f"{directory.name} holds another build of the ladder; choose a new --root")
    for entry in truth["clips"]:
        path = directory / entry["wav"]
        if not path.is_file() or sha256_file(path) != entry["wavSHA256"]:
            raise LadderCommandError(f"{entry['clipID']}: its WAV is missing or changed; choose a new --root")
    return truth


def build(ladder: str, root: Path, *, quality_sources: Path | None = None,
          max_quality_sources: int = DEFAULT_MAX_QUALITY_SOURCES,
          registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if ladder not in L.LADDERS:
        raise LadderCommandError(f"unknown ladder {ladder!r}")
    directory = root / ladder
    _require_untracked(directory)
    if ladder == "pyin":
        check_pyin_grid(registry if registry is not None else _registry())
    sources, texts = None, {}
    if ladder == "quality" and quality_sources is not None:
        sources, texts = recording_sources(quality_sources, max_quality_sources)
    clips = L.ladder_clips(ladder, quality_sources=sources)
    digest = L.clips_digest(clips)
    existing = _built(directory, digest)
    if existing is None:
        entries = []
        for clip in clips:
            relative = f"wav/{clip.clip_id}.wav"
            wav_sha = write_pcm16_wav(directory / relative, clip.samples, sample_rate=clip.sample_rate)
            entries.append({**clip.describe(), "wav": relative, "wavSHA256": wav_sha,
                            "durationSeconds": round(clip.duration_seconds, 6)})
        if ladder in ("pyin", "quality"):
            atomic_json(directory / MANIFEST_FILE, orchestrator_manifest(ladder, directory, entries, digest, texts),
                        allow_nan=False)
        # Written last: a truth file marks a complete build.
        atomic_json(directory / TRUTH_FILE, {
            "schema": L.LADDER_SCHEMA, "ladder": ladder, "ladderVersion": L.LADDER_VERSION, "clipsSHA256": digest,
            "criteria": L.criteria_description(ladder), "generatorSHA256": generator_digests(),
            "recordingSources": sources is not None, "clips": entries,
        }, allow_nan=False)
    else:
        entries = existing["clips"]
    return {"ladder": ladder, "clips": len(entries), "clipsSHA256": digest, "reused": existing is not None,
            "audioSeconds": round(sum(entry["durationSeconds"] for entry in entries), 3),
            "directory": str(directory),
            "manifest": str(directory / MANIFEST_FILE) if ladder in ("pyin", "quality") else None}


# --------------------------------------------------------------------------- #
# evaluate
# --------------------------------------------------------------------------- #

def read_truth(directory: Path, ladder: str) -> dict[str, Any]:
    truth = _read(directory / TRUTH_FILE)
    if truth.get("schema") != L.LADDER_SCHEMA or truth.get("ladder") != ladder \
            or truth.get("ladderVersion") != L.LADDER_VERSION or not isinstance(truth.get("clips"), list):
        raise LadderCommandError(f"{directory.name} holds no {ladder} ladder of version {L.LADDER_VERSION}")
    return truth


def bundle_records(bundle: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The validated bundle's header and its take-evidence records by take id."""
    errors = validate_private_bundle(bundle, repository=REPO)
    if errors:
        raise LadderCommandError(f"the bundle does not validate: {errors[0]}")
    header = _read(bundle / "bundle.json")
    records = {entry["takeID"]: _read(bundle / entry["evidence"]) for entry in header["takes"]}
    return header, records


def measurement(record: Mapping[str, Any] | None, judge_id: str) -> dict[str, Any] | None:
    for item in (record or {}).get("measurements") or []:
        if item.get("judge") == judge_id and item.get("status") == "complete":
            return item
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _matching(records: Mapping[str, dict[str, Any]], entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """The clip's record, when the bundle measured exactly the ladder's WAV."""
    record = records.get(entry["clipID"])
    if record is None or record["take"].get("audioSHA256") != entry["wavSHA256"]:
        return None
    return record


def pitch_l1(cache: Any, record: Mapping[str, Any], found: Mapping[str, Any],
             registry: Mapping[str, Any]) -> dict[str, Any] | None:
    """The run's raw pYIN output for a take: its L1 entry, keyed exactly as the orchestrator keyed it.

    As `audio_qc_calibration_set.py alignments` rebuilds the aligner's keys: the
    take's original and canonical digests from its evidence, the judge's model
    fields from its registry pins (`panel_identity`), the output identity the
    evidence recorded, and the request `panel_request` builds (empty for pitch).
    """
    from dataclasses import replace

    from delivery_analysis_cache import CanonicalAudio
    from lib.qc_pipeline.layered_cache import l1_identity
    from lib.qc_pipeline.panel_jobs import judge_scope, panel_identity, panel_request, profile

    judge = (registry.get("judges") or {}).get(L.PYIN_JUDGE) or {}
    identity = replace(panel_identity(L.PYIN_JUDGE, registry, {"threads": None}),
                       output_identity=found["outputIdentity"])
    take = record["take"]
    request = panel_request(profile(L.PYIN_JUDGE), judge_scope(judge),
                            {"language": take["language"], "referenceText": None})
    canonical = CanonicalAudio(take["audioSHA256"], take["canonicalPCMSHA256"], 0, 0.0, Path("."), "")
    return cache.load(l1_identity(canonical, identity, request or {}))


def evaluate_pyin(directory: Path, bundle: Path, cache_root: Path,
                  registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from delivery_analysis_cache import AnalysisCacheError, DeliveryAnalysisCache

    truth = read_truth(directory, "pyin")
    header, records = bundle_records(bundle)
    registry = registry if registry is not None else _registry()
    cache = DeliveryAnalysisCache(cache_root)
    estimates: dict[str, dict[str, Any] | None] = {}
    identities: set[str] = set()
    unavailable = {"record": 0, "measurement": 0, "l1": 0, "l1Invalid": 0, "grid": 0}
    for entry in truth["clips"]:
        clip_id = entry["clipID"]
        estimates[clip_id] = None
        record = _matching(records, entry)
        if record is None:
            unavailable["record"] += 1
            continue
        found = measurement(record, L.PYIN_JUDGE)
        if found is None or not is_sha256(found.get("outputIdentity")):
            unavailable["measurement"] += 1
            continue
        identities.add(found["outputIdentity"])
        try:
            raw = pitch_l1(cache, record, found, registry)
        except AnalysisCacheError:
            unavailable["l1Invalid"] += 1
            continue
        if raw is None:
            unavailable["l1"] += 1
            continue
        if _finite(raw.get("hopSeconds")) != L.PYIN_HOP / L.PYIN_RATE:
            unavailable["grid"] += 1
            continue
        estimates[clip_id] = raw
    truths = {entry["clipID"]: entry["truth"] for entry in truth["clips"]}
    groups = {entry["clipID"]: entry["group"] for entry in truth["clips"]}
    result = L.evaluate_pitch(truths, groups, estimates)
    return _evaluation(truth, "pyin", {L.PYIN_JUDGE: result}, verdict=result["verdict"],
                       bundle=header, judges={L.PYIN_JUDGE: sorted(identities)}, unavailable=unavailable)


def hnr_readings(directory: Path, truth: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    """Each tracker's clip-level HNR, run in this process on the ladder's WAVs (no model)."""
    from analyze_prosody import analyze
    from audio_phonation import analyze_phonation

    readings: dict[str, dict[str, float | None]] = {tracker: {} for tracker in L.HNR_TRACKERS}
    for entry in truth["clips"]:
        path = directory / entry["wav"]
        if not path.is_file() or sha256_file(path) != entry["wavSHA256"]:
            raise LadderCommandError(f"{entry['clipID']}: its WAV is missing or changed")
        prosody = analyze(str(path))
        readings["prosody@3"][entry["clipID"]] = None if "error" in prosody else _finite(prosody.get("voice_hnr_db_mean"))
        phonation = analyze_phonation(str(path))
        readings["window-corrected-ac-v1"][entry["clipID"]] = _finite(phonation.get("windowCorrectedPeriodicityHNRDB"))
    return readings


def read_oracle(path: Path | None, truth: Mapping[str, Any]) -> tuple[dict[str, float] | None, str | None]:
    """An isolated Parselmouth run's readings per clip id (`vocello.audioqc.hnr-oracle/1`), and its tool token."""
    if path is None:
        return None, None
    oracle = _read(path)
    values = oracle.get("values")
    if oracle.get("schema") != L.HNR_ORACLE_SCHEMA or not isinstance(values, dict) or not is_token(oracle.get("tool")):
        raise LadderCommandError(f"--oracle-hnr names a {L.HNR_ORACLE_SCHEMA} file with a tool token and values")
    known = {entry["clipID"] for entry in truth["clips"]}
    parsed = {}
    for clip_id, value in values.items():
        if clip_id not in known or _finite(value) is None:
            raise LadderCommandError("--oracle-hnr values name ladder clips with finite readings")
        parsed[clip_id] = float(value)
    return parsed, oracle["tool"]


def evaluate_hnr(directory: Path, *, oracle_path: Path | None = None,
                 readings: Mapping[str, Mapping[str, float | None]] | None = None) -> dict[str, Any]:
    truth = read_truth(directory, "hnr")
    oracle, tool = read_oracle(oracle_path, truth)
    readings = readings if readings is not None else hnr_readings(directory, truth)
    truths = {entry["clipID"]: entry["truth"] for entry in truth["clips"]}
    trackers = {tracker: L.evaluate_hnr_tracker(truths, readings[tracker], oracle) for tracker in L.HNR_TRACKERS}
    return _evaluation(truth, "hnr", trackers, verdict=trackers[L.HNR_GATED_TRACKER]["verdict"],
                       oracle={"tool": tool, "clips": len(oracle)} if oracle is not None else None)


def evaluate_quality(directory: Path, bundle: Path, *, wer_judge: str | None = None) -> dict[str, Any]:
    truth = read_truth(directory, "quality")
    header, records = bundle_records(bundle)
    columns: dict[str, dict[str, float]] = {name: {} for name, *_ in L.COMPOSITE_COLUMNS}
    diagnostics: dict[str, dict[str, float]] = {name: {} for name, _judge in L.DIAGNOSTIC_COLUMNS}
    wer: dict[str, float] = {}
    durations: dict[str, float] = {}
    identities: dict[str, set[str]] = {}
    unavailable = 0
    for entry in truth["clips"]:
        clip_id = entry["clipID"]
        record = _matching(records, entry)
        if record is None:
            unavailable += 1
            continue
        durations[clip_id] = float(record["take"]["durationSeconds"])
        wanted = [(name, judge, metric, columns) for name, judge, metric, _weight in L.COMPOSITE_COLUMNS]
        wanted += [(name, judge, name, diagnostics) for name, judge in L.DIAGNOSTIC_COLUMNS]
        if wer_judge:
            wanted.append(("errorRate", wer_judge, "errorRate", None))
        for name, judge_id, metric, target in wanted:
            found = measurement(record, judge_id)
            value = _finite(((found or {}).get("metrics") or {}).get(metric))
            if found is not None and is_sha256(found.get("outputIdentity")):
                identities.setdefault(judge_id, set()).add(found["outputIdentity"])
            if value is None:
                continue
            if target is None:
                wer[clip_id] = value
            else:
                target[name][clip_id] = value
    truths = {entry["clipID"]: entry["truth"] for entry in truth["clips"]}
    result = L.evaluate_quality(truths, columns, durations, wer=wer if wer_judge else None, diagnostics=diagnostics)
    return _evaluation(truth, "quality", {"composite": result}, verdict=result["verdict"], bundle=header,
                       judges={judge_id: sorted(values) for judge_id, values in sorted(identities.items())},
                       unavailable={"record": unavailable}, werJudge=wer_judge)


def _evaluation(truth: Mapping[str, Any], ladder: str, trackers: Mapping[str, Any], *, verdict: str,
                bundle: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "schema": L.EVALUATION_SCHEMA, "ladder": ladder, "ladderVersion": L.LADDER_VERSION,
        "clipsSHA256": truth["clipsSHA256"], "clipCount": len(truth["clips"]),
        "recordingSources": bool(truth.get("recordingSources")),
        "bundleDigest": (bundle or {}).get("bundleDigest") if is_sha256((bundle or {}).get("bundleDigest")) else None,
        "bundleRunID": (bundle or {}).get("runID") if is_token((bundle or {}).get("runID")) else None,
        "generatorSHA256": generator_digests(), "evaluatedAt": utc_now(),
        "trackers": dict(trackers), "verdict": verdict, **extra,
    }


def write_evaluation(directory: Path, evaluation: Mapping[str, Any]) -> Path:
    errors = privacy_errors(dict(evaluation), "evaluation")
    if errors:
        raise LadderCommandError(f"the evaluation is not privacy-safe: {errors[0]}")
    path = directory / EVALUATION_FILE
    atomic_json(path, dict(evaluation), allow_nan=False)
    return path


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def report(evaluations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One record over the evaluated ladders, with the AQ-08 ladder part of the gate."""
    ladders: dict[str, Any] = {}
    for evaluation in evaluations:
        if evaluation.get("schema") != L.EVALUATION_SCHEMA or evaluation.get("ladder") not in L.LADDERS:
            raise LadderCommandError(f"an evaluation declares {L.EVALUATION_SCHEMA} and a known ladder")
        if evaluation["ladder"] in ladders:
            raise LadderCommandError(f"two evaluations of the {evaluation['ladder']} ladder")
        ladders[evaluation["ladder"]] = dict(evaluation)
    verdicts = {ladder: value["verdict"] for ladder, value in sorted(ladders.items())}
    record = {
        "schema": L.REPORT_SCHEMA, "ladderVersion": L.LADDER_VERSION, "createdAt": utc_now(),
        "generatorSHA256": generator_digests(), "verdicts": verdicts,
        "aq08LaddersPass": set(verdicts) == set(L.LADDERS)
        and all(value in ("pass", "pass-provisional") for value in verdicts.values()),
        "ladders": ladders,
    }
    errors = privacy_errors(record, "report")
    if errors:
        raise LadderCommandError(f"the report is not privacy-safe: {errors[0]}")
    if len(json.dumps(record, sort_keys=True).encode("utf-8")) > MAXIMUM_REPORT_BYTES:
        raise LadderCommandError("the report exceeds 256 KB")
    return record


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _exit_for(verdicts: Sequence[str]) -> int:
    return 0 if all(value in ("pass", "pass-provisional") for value in verdicts) else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="render a ladder's WAVs, truth and orchestrator manifest")
    build_parser.add_argument("--ladder", choices=(*L.LADDERS, "all"), default="all")
    build_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    build_parser.add_argument("--quality-sources", type=Path,
                              help="an orchestrator manifest whose takes replace the procedural quality sources")
    build_parser.add_argument("--max-quality-sources", type=int, default=DEFAULT_MAX_QUALITY_SOURCES)
    evaluate_parser = commands.add_parser("evaluate", help="score a built ladder")
    evaluate_parser.add_argument("--ladder", choices=L.LADDERS, required=True)
    evaluate_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    evaluate_parser.add_argument("--bundle", type=Path, help="the orchestrator bundle of the ladder's manifest")
    evaluate_parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT,
                                 help="the orchestrator run's cache root (pyin reads its L1 entries)")
    evaluate_parser.add_argument("--oracle-hnr", type=Path, help=f"a {L.HNR_ORACLE_SCHEMA} file (Parselmouth)")
    evaluate_parser.add_argument("--wer-judge", help="a recognizer judge whose errorRate enters the composite")
    report_parser = commands.add_parser("report", help="combine evaluations into one privacy-safe record")
    report_parser.add_argument("--evaluation", type=Path, action="append", required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            ladders = L.LADDERS if args.ladder == "all" else (args.ladder,)
            if args.max_quality_sources < 1:
                raise LadderCommandError("--max-quality-sources is at least 1")
            summaries = [build(ladder, args.root, quality_sources=args.quality_sources,
                               max_quality_sources=args.max_quality_sources) for ladder in ladders]
            print(json.dumps(summaries, indent=2, sort_keys=True))
            return 0
        if args.command == "evaluate":
            directory = args.root / args.ladder
            if args.ladder in ("pyin", "quality") and args.bundle is None:
                raise LadderCommandError(f"the {args.ladder} ladder is evaluated from an orchestrator bundle (--bundle)")
            if args.ladder == "pyin":
                evaluation = evaluate_pyin(directory, args.bundle, args.cache_root)
            elif args.ladder == "hnr":
                evaluation = evaluate_hnr(directory, oracle_path=args.oracle_hnr)
            else:
                evaluation = evaluate_quality(directory, args.bundle, wer_judge=args.wer_judge)
            path = write_evaluation(directory, evaluation)
            print(json.dumps({"ladder": args.ladder, "verdict": evaluation["verdict"], "evaluation": str(path),
                              "criteria": {tracker: {item["id"]: item["status"] for item in value["criteria"]}
                                           for tracker, value in evaluation["trackers"].items()}},
                             indent=2, sort_keys=True))
            return _exit_for([evaluation["verdict"]])
        record = report([_read(path) for path in args.evaluation])
        if args.output.exists():
            raise LadderCommandError(f"{args.output.name} exists; a report is written once")
        atomic_json(args.output, record, allow_nan=False)
        print(json.dumps({"report": str(args.output), "verdicts": record["verdicts"],
                          "aq08LaddersPass": record["aq08LaddersPass"]}, indent=2, sort_keys=True))
        return _exit_for(list(record["verdicts"].values()))
    except (ValueError, OSError) as error:
        # Includes LadderCommandError, LadderError, a corrupt cache entry and an invalid bundle.
        print(f"audio-qc-oracle-ladders: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
