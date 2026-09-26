#!/usr/bin/env python3
"""Independent full-file speech recognition of generated audio (whisper family).

The language lanes and the delivery cascade judge spoken content with recognizer
*families*; one family is one witness. Apple Speech runs only inside the iPhone
app, so this producer supplies the second family on the Mac: a pinned
`whisper-small` MLX model, decoded greedily with the language locked to the
expected language, detecting the language separately from the first 30 seconds.

Design rules for the 8 GB support floor:
  * Nothing here loads a model while the Qwen3 engine may be resident. The
    manifest must declare `generationProcessExited: true`; the lanes build it
    after their generation loop.
  * Exactly one supervised subprocess (`delivery_resource_supervisor`) runs
    `independent_asr_worker.py`, which loads and warms the model once and
    transcribes every uncached audio once (rows with byte-identical audio and
    one language share a recognition); the parent never imports MLX.
  * The worker's raw result is cached in `DeliveryAnalysisCache` under an
    identity that binds the audio bytes, the canonical derivative, the model,
    the runtime (the worker's source, not this file's) and the per-language
    decode options, so re-analysis launches nothing. The recognition entry is
    derived from it here after every hit as after every miss, so an edit to
    the derivation is never served stale.
  * Evidence carries transcripts of tracked corpus scripts, digests and
    envelopes; never audio bytes or local paths. It stays untracked.

Commands:
  manifest    build the row manifest for a macOS or iOS language run, or for a
              cascade input
  transcribe  run the producer over a manifest and write recognition evidence
  verdict     score the evidence per row, with the Apple Speech verdict when the
              manifest carries one, and report the family consensus (or one
              witness) for a lane that publishes no record, such as a cohort
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable
import wave

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.language_metrics import (  # noqa: E402
    INDEPENDENT_ASR_ALGORITHM,
    INDEPENDENT_RECOGNITION_SCHEMA,
    LANGUAGE_LOCALE_CODES,
    channel_consensus,
    edges_covered,
    is_sha256,
    recognition_issues,
    score_recognition,
    single_family_meets_expectation,
    text_sha256,
)


SCHEMA_VERSION = 1
WORKER_SOURCE = SCRIPT_DIR / "independent_asr_worker.py"
FAMILY = "whisper"
ADAPTER_ID = "whisper-small-mlx"
# The registry judge this producer loads (`config/audio-qc-judges.json`).
JUDGE_ID = "asr.whisper-small@1"
LAYER_ID = "independent-asr"
# 2 (2026-09-25): entries hold the worker's raw result, not the derived
# recognition, so version-1 entries are never read as raw results.
LAYER_VERSION = "2"
REVIEW_POLICY = "automated-evidence-1"
# Measured envelope for whisper-small on MLX is about 1 GiB; the compact-model
# layer keeps its own contract-pinned 5 GiB ceiling in the supervisor.
MAXIMUM_RSS_BYTES = int(2.5 * 1024**3)
DEFAULT_TIMEOUT_SECONDS = 900.0
REPO = SCRIPT_DIR.parent
DEFAULT_CACHE_ROOT = Path(os.environ.get(
    "QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"
))


class IndependentASRError(ValueError):
    """The manifest, the pinned adapter or the recognizer run is unusable."""


# --------------------------------------------------------------------------- #
# Manifest builders
# --------------------------------------------------------------------------- #

def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IndependentASRError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise IndependentASRError(f"{path.name} must contain an object")
    return value


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as stream:
            rate = stream.getframerate()
            frames = stream.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise IndependentASRError(f"{path.name} is not a readable WAV: {error}") from error
    if rate <= 0 or frames <= 0:
        raise IndependentASRError(f"{path.name} has no audio")
    return frames / rate


def _row(*, row_id: str, generation_id: str, audio: Path, audio_sha256: str,
         expected_language: str, reference_text: str, expected_outcome: str = "pass",
         role: str | None = None, cell_id: str | None = None,
         apple_speech_pass: bool | None = None,
         apple_speech_channels: dict[str, bool] | None = None) -> dict[str, Any]:
    if not isinstance(reference_text, str) or not reference_text.strip():
        raise IndependentASRError(f"{row_id}: reference text is empty")
    if expected_language not in LANGUAGE_LOCALE_CODES:
        raise IndependentASRError(f"{row_id}: unsupported expected language {expected_language!r}")
    entry = {
        "id": row_id,
        "generationID": generation_id,
        "audioPath": str(audio),
        "audioSHA256": audio_sha256,
        "durationSeconds": _wav_duration_seconds(audio),
        "expectedLanguage": expected_language,
        "referenceText": reference_text,
        "scriptSHA256": text_sha256(reference_text),
        "expectedOutcome": expected_outcome,
    }
    if role is not None:
        entry["role"] = role
    if cell_id is not None:
        entry["cellID"] = cell_id
    if apple_speech_pass is not None:
        entry["appleSpeechPass"] = apple_speech_pass
    if apple_speech_channels is not None:
        entry["appleSpeechChannels"] = dict(apple_speech_channels)
    return entry


def _manifest(rows: list[dict[str, Any]], *, run_id: str, platform: str,
              generation_process_exited: bool) -> dict[str, Any]:
    if not rows:
        raise IndependentASRError("manifest has no rows")
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise IndependentASRError("manifest row identities are duplicated")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "independent-asr-manifest",
        "runID": run_id,
        "platform": platform,
        "generationProcessExited": bool(generation_process_exited),
        "rows": rows,
    }


def build_macos_manifest(*, diagnostics: Path, run_id: str, matrix: Path, corpus: Path,
                         subset: str, wav_dir: Path, generation_process_exited: bool) -> dict[str, Any]:
    """One row per output-verified cell; the WAV is bound to the engine row's digest."""
    from check_language_hints import corpus_scripts, load_json, read_engine_rows, select_cells
    from delivery_analysis_cache import file_sha256

    cells = select_cells(load_json(str(matrix)), subset)
    scripts = corpus_scripts(load_json(str(corpus)))
    try:
        engine_rows = read_engine_rows(str(diagnostics), run_id)
    except FileNotFoundError as error:
        raise IndependentASRError(f"engine telemetry is missing: {error}") from error
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in engine_rows:
        cell_id = (row.get("notes") or {}).get("benchCell")
        if isinstance(cell_id, str):
            by_cell.setdefault(cell_id, []).append(row)
    rows: list[dict[str, Any]] = []
    for cell in cells:
        if cell.get("skipOutputVerification"):
            continue
        cell_id = str(cell["id"])
        matches = by_cell.get(cell_id, [])
        if len(matches) != 1:
            raise IndependentASRError(f"{cell_id}: expected one engine row, found {len(matches)}")
        row = matches[0]
        published = (row.get("notes") or {}).get("samplingWAVDigest")
        if not is_sha256(published):
            raise IndependentASRError(f"{cell_id}: engine row lacks the published WAV digest")
        audio = wav_dir / f"{cell_id}.wav"
        if not audio.is_file():
            raise IndependentASRError(f"{cell_id}: output WAV is missing")
        if file_sha256(audio) != published:
            raise IndependentASRError(f"{cell_id}: output WAV bytes differ from the engine's published digest")
        script = scripts.get(str(cell.get("scriptLang")))
        if not isinstance(script, str):
            raise IndependentASRError(f"{cell_id}: corpus lacks scriptLang {cell.get('scriptLang')!r}")
        rows.append(_row(
            row_id=cell_id, generation_id=str(row.get("generationID")), audio=audio,
            audio_sha256=published, expected_language=str(cell.get("expectedHint")),
            reference_text=script, expected_outcome=str(cell.get("expectedOutcome", "pass")),
        ))
    return _manifest(rows, run_id=run_id, platform="macos",
                     generation_process_exited=generation_process_exited)


def build_ios_manifest(*, diagnostics: Path, run_id: str, plan: Path, corpus: Path,
                       generation_process_exited: bool) -> dict[str, Any]:
    """One row per planned, output-verified take over the collected `output.wav` files."""
    from check_language_hints import corpus_scripts, load_json
    from delivery_analysis_cache import file_sha256
    from language_bench_evidence import exact_sentinels, load_json as load_plan, validate_plan

    plan_payload = load_plan(plan)
    if plan_payload.get("runID") != run_id:
        raise IndependentASRError("run plan belongs to another run ID")
    takes = validate_plan(plan_payload)
    scripts = corpus_scripts(load_json(str(corpus)))
    sentinels = exact_sentinels(diagnostics, plan_payload)
    rows: list[dict[str, Any]] = []
    for take in takes:
        if take.get("skipOutputVerification"):
            continue
        child = str(take["childRunID"])
        sentinel_path, record = sentinels[child]
        if record.get("status") != "ok":
            raise IndependentASRError(f"{child}: diagnostics did not complete")
        evidence = record.get("outputEvidence")
        declared = evidence.get("sha256") if isinstance(evidence, dict) else None
        if not is_sha256(declared):
            raise IndependentASRError(f"{child}: sentinel lacks bounded output evidence")
        audio = sentinel_path.parent / "output.wav"
        if not audio.is_file() or file_sha256(audio) != declared:
            raise IndependentASRError(f"{child}: collected output.wav is missing or differs from the sentinel digest")
        script = scripts.get(str(take.get("scriptLang")))
        if not isinstance(script, str):
            raise IndependentASRError(f"{child}: corpus lacks scriptLang {take.get('scriptLang')!r}")
        verification = record.get("outputVerification")
        apple_pass = verification.get("pass") if isinstance(verification, dict) else None
        # Each channel's in-app verdict, voted separately (audit #42).
        apple_channels = {
            "language": verification.get("languagePass"),
            "accuracy": verification.get("accuracyPass"),
        } if isinstance(verification, dict) else {}
        # Rows are keyed by the take's child run ID (audit #44): a diagnostic
        # cohort repeats each cell across seeds, which cell keys rejected as
        # duplicates and so kept whisper out of every cohort.
        rows.append(_row(
            row_id=child, cell_id=str(take["cellID"]),
            generation_id=str(record.get("generationID")), audio=audio,
            audio_sha256=declared, expected_language=str(take.get("expectedHint")),
            reference_text=script, expected_outcome=str(take.get("expectedOutcome", "pass")),
            apple_speech_pass=apple_pass if isinstance(apple_pass, bool) else None,
            apple_speech_channels=apple_channels if apple_channels and all(
                isinstance(value, bool) for value in apple_channels.values()
            ) else None,
        ))
    return _manifest(rows, run_id=run_id, platform="ios",
                     generation_process_exited=generation_process_exited)


def build_cascade_manifest(*, cascade_input: Path) -> dict[str, Any]:
    """Instructed and neutral rows of a source-bound cascade input."""
    payload = _load_json(cascade_input)
    if payload.get("kind") != "source-bound-delivery-cascade-input":
        raise IndependentASRError("cascade input is not source-bound")
    if payload.get("generationProcessExited") is not True:
        raise IndependentASRError("cascade input does not declare that the generator exited")
    execution_digest = payload.get("executionPlanDigest")
    if not is_sha256(execution_digest):
        raise IndependentASRError("cascade execution plan identity is invalid")
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        generation_id = str(row.get("generationID"))
        language = str(row.get("outputLanguage", "")).lower()
        text = row.get("referenceText")
        for role, wav_key, digest_key in (
            ("instructed", "instructedWAV", "instructedSHA256"),
            ("neutral", "neutralWAV", "neutralSHA256"),
        ):
            rows.append(_row(
                row_id=f"{generation_id}:{role}", generation_id=generation_id,
                audio=Path(str(row.get(wav_key))), audio_sha256=str(row.get(digest_key)),
                expected_language=language, reference_text=text if isinstance(text, str) else "",
                role=role,
            ))
    manifest = _manifest(rows, run_id=str(payload.get("runID", execution_digest)), platform="cascade",
                         generation_process_exited=True)
    manifest["executionPlanDigest"] = execution_digest
    return manifest


def validate_manifest(manifest: Any) -> dict[str, Any]:
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA_VERSION
            or manifest.get("kind") != "independent-asr-manifest"):
        raise IndependentASRError("manifest schema is not independent-asr-manifest v1")
    if manifest.get("generationProcessExited") is not True:
        raise IndependentASRError(
            "the generator process must have exited before recognition starts "
            "(manifest.generationProcessExited must be true)"
        )
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise IndependentASRError("manifest rows must be non-empty")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in seen:
            raise IndependentASRError("manifest rows need unique string identities")
        seen.add(row["id"])
        for field in ("generationID", "audioPath", "expectedLanguage", "referenceText"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise IndependentASRError(f"{row['id']}: {field} is required")
        if not is_sha256(row.get("audioSHA256")) or row.get("scriptSHA256") != text_sha256(row["referenceText"]):
            raise IndependentASRError(f"{row['id']}: audio or script digest is invalid")
        if row["expectedLanguage"] not in LANGUAGE_LOCALE_CODES:
            raise IndependentASRError(f"{row['id']}: unsupported expected language")
    return manifest


# --------------------------------------------------------------------------- #
# Producer (parent process)
# --------------------------------------------------------------------------- #

def _code_to_language(config: dict[str, Any]) -> dict[str, str]:
    languages = config.get("labelMap", {}).get("languages")
    if not isinstance(languages, dict) or not languages:
        raise IndependentASRError("adapter label map lacks the language table")
    return {str(code): str(name) for name, code in languages.items()}


def _provenance(config: dict[str, Any], *, language_code: str) -> dict[str, str]:
    from delivery_analysis_cache import digest, file_sha256
    runtime = digest({
        "runtimeDependencies": config.get("runtimeDependencies"),
        "binarySHA256": config["binarySHA256"],
        # Narrowed to the recognizer child (audit #89): editing a manifest
        # builder or this producer never invalidates cached recognitions.
        "workerSourceSHA256": file_sha256(WORKER_SOURCE),
        "algorithm": INDEPENDENT_ASR_ALGORITHM,
    })
    model = digest({
        "modelID": config["modelID"],
        "sourceRevision": config["sourceRevision"],
        "weightsSHA256": config["weightsSHA256"],
        "labelMapDigest": config["labelMapDigest"],
    })
    decode = digest({
        "decodeOptions": config.get("decodeOptions"),
        "language": language_code,
        "preprocessingConfigDigest": config["preprocessingConfigDigest"],
    })
    return {"runtimeSHA256": runtime, "modelIdentitySHA256": model, "configSHA256": decode}


def _recognition(row: dict[str, Any], result: dict[str, Any], *, provenance: dict[str, str],
                 code_to_language: dict[str, str]) -> dict[str, Any]:
    segments = result.get("segments") or []
    starts = [float(segment["start"]) for segment in segments]
    ends = [float(segment["end"]) for segment in segments]
    duration = float(row["durationSeconds"])
    full = bool(segments) and edges_covered(min(starts), max(ends), duration)
    detected_code = str(result.get("detectedLanguage", ""))
    transcript = str(result.get("transcript", "")).strip()
    # The duration the recognizer decoded, from its own sample count (audit
    # #89); the WAV header value made the mismatch check unable to fire.
    samples, rate = result.get("decodedSampleCount"), result.get("sampleRateHz")
    processed = (
        samples / rate
        if type(samples) is int and samples > 0 and type(rate) is int and rate > 0 else None
    )
    no_speech = [float(segment["noSpeechProb"]) for segment in segments if "noSpeechProb" in segment]
    log_probabilities = [float(segment["avgLogprob"]) for segment in segments if "avgLogprob" in segment]
    return {
        "schemaVersion": INDEPENDENT_RECOGNITION_SCHEMA,
        "algorithmVersion": INDEPENDENT_ASR_ALGORITHM,
        "modelFamily": FAMILY,
        "audioSHA256": row["audioSHA256"],
        "inputTextSHA256": row["scriptSHA256"],
        "status": "complete" if transcript else "empty",
        "outputLanguage": row["expectedLanguage"],
        "decodeLanguage": result.get("language"),
        "detectedLanguage": code_to_language.get(detected_code, detected_code),
        "languageMatchScore": float(result.get("expectedLanguageProbability", 0.0)),
        "detectedLanguageProbability": float(result.get("detectedLanguageProbability", 0.0)),
        "fullFileProcessed": full,
        "processedDurationSeconds": processed,
        "decodedSampleCount": samples if processed is not None else None,
        "segmentCount": len(segments),
        # Whisper's own confidence, kept rather than computed and dropped.
        "maximumNoSpeechProbability": max(no_speech) if no_speech else None,
        "meanAverageLogProbability": (
            sum(log_probabilities) / len(log_probabilities) if log_probabilities else None
        ),
        "firstSegmentStartSeconds": min(starts) if starts else None,
        "lastSegmentEndSeconds": max(ends) if ends else None,
        "recognitionDurationSeconds": float(result.get("wallSeconds", 0.0)),
        "transcript": transcript,
        "provenance": provenance,
    }


def transcribe_manifest(
    *, manifest: dict[str, Any], config: dict[str, Any], cache: Any, lock_root: Path,
    supervisor: Callable[..., Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_rss_bytes: int = MAXIMUM_RSS_BYTES,
) -> dict[str, Any]:
    """Recognize every manifest row; cached rows launch nothing."""
    from audio_qc_judges import JudgeRegistryError, require_loadable
    from delivery_analysis_cache import LayerIdentity, configured_resampler, file_sha256
    from delivery_compact_model_adapter import CompactAdapterError, envelope_identity, validate_adapter_config
    from delivery_resource_supervisor import run_supervised

    manifest = validate_manifest(manifest)
    try:
        config = validate_adapter_config(config)
    except CompactAdapterError as error:
        raise IndependentASRError(str(error)) from error
    if config["adapterID"] != ADAPTER_ID:
        raise IndependentASRError("independent ASR requires the whisper-small-mlx adapter configuration")
    try:
        # The load-time gate, named for the judge this producer loads.
        require_loadable(JUDGE_ID, config["modelID"], config["sourceRevision"],
                         packages=list(config.get("runtimeDependencies") or {}))
    except JudgeRegistryError as error:
        raise IndependentASRError(str(error)) from error
    if cache.resampler_version != configured_resampler(config):
        raise IndependentASRError("cache resampler differs from the pinned adapter preprocessing")
    language_codes = {name: code for code, name in _code_to_language(config).items()}
    code_to_language = _code_to_language(config)
    supervise = supervisor or run_supervised

    # One recognition per cache identity: the pinned and Auto cells of a prompt
    # group regenerate byte-identical audio (audit #86), and two timed decodes
    # of one identity could never share one cache entry.
    identities: dict[str, LayerIdentity] = {}
    provenances: dict[str, dict[str, str]] = {}
    results: dict[LayerIdentity, dict[str, Any]] = {}
    cached: set[LayerIdentity] = set()
    pending: dict[LayerIdentity, tuple[str, str, Path]] = {}
    for row in manifest["rows"]:
        audio = Path(row["audioPath"])
        if not audio.is_file() or file_sha256(audio) != row["audioSHA256"]:
            raise IndependentASRError(f"{row['id']}: audio is missing or its bytes changed")
        code = language_codes.get(row["expectedLanguage"])
        if code is None:
            raise IndependentASRError(f"{row['id']}: adapter cannot lock {row['expectedLanguage']}")
        canonical = cache.canonicalize(audio)
        provenance = _provenance(config, language_code=code)
        # The runtime digest covers the interpreter, the dependency pins and the
        # worker's source, so a recognizer code change is a cache miss, never a
        # stale hit; the entry holds only what the worker measured.
        identity = LayerIdentity(
            original_wav_sha256=canonical.original_wav_sha256,
            canonical_derivative_sha256=canonical.canonical_derivative_sha256,
            layer_id=LAYER_ID, layer_version=LAYER_VERSION,
            binary_sha256=provenance["runtimeSHA256"], model_id=config["modelID"],
            model_revision=config["sourceRevision"], weights_sha256=config["weightsSHA256"],
            preprocessing_config_digest=provenance["configSHA256"],
        )
        identities[row["id"]] = identity
        provenances[row["id"]] = provenance
        if identity in results or identity in pending:
            continue
        retained = cache.load(identity)
        if retained is not None:
            results[identity] = retained
            cached.add(identity)
            continue
        pending[identity] = (row["id"], code, canonical.derivative_path)
    cache_hits = sum(1 for row in manifest["rows"] if identities[row["id"]] in cached)

    envelope: dict[str, Any] | None = None
    supervision: dict[str, str] | None = None
    model_load_seconds: Any = None
    warmup_seconds: Any = None
    if pending:
        with tempfile.TemporaryDirectory(prefix="vocello-independent-asr-") as temporary:
            job_path = Path(temporary) / "job.json"
            job_path.write_text(json.dumps({
                "schemaVersion": SCHEMA_VERSION,
                "weights": str(config["weightsPath"]),
                "decodeOptions": config.get("decodeOptions") or {},
                "rows": [
                    {"id": job_id, "pcmPath": str(pcm), "language": code}
                    for job_id, code, pcm in pending.values()
                ],
            }), encoding="utf-8")
            command = [str(config["binaryPath"]), str(WORKER_SOURCE.resolve()), "--job", str(job_path)]
            environment = dict(os.environ)
            environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
            # The supervisor that measures this launch: envelope provenance,
            # never part of a cache key (audit AQ-F47).
            supervision = envelope_identity()
            # Whisper runs on MLX: its Metal memory is invisible to RSS, so the
            # footprint (with the kernel's lifetime peak) is measured and its
            # ceiling evaluated (audit #101).
            result = supervise(
                command, lock_root=lock_root, timeout_seconds=timeout_seconds,
                maximum_rss_bytes=maximum_rss_bytes,
                maximum_physical_footprint_bytes=maximum_rss_bytes,
                measure_physical_footprint=True,
                environment=environment,
            )
        envelope = result.report
        if not envelope.get("qualified"):
            # The tail of stderr is the only diagnostic a failed worker leaves;
            # keep it short and strip the home directory before surfacing it.
            tail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()[-6:]
            home = str(Path.home())
            tail = [line.replace(home, "~") for line in tail]
            raise IndependentASRError(
                "recognizer resource envelope is unqualified: "
                + ",".join(envelope.get("qualificationFailures", []))
                + ("\n" + "\n".join(tail) if tail else "")
            )
        try:
            output = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IndependentASRError("recognizer worker did not emit one JSON object") from error
        if not isinstance(output, dict) or output.get("kind") != "independent-asr-worker-output":
            raise IndependentASRError("recognizer worker output is not typed")
        model_load_seconds = output.get("modelLoadSeconds")
        warmup_seconds = output.get("warmupSeconds")
        by_id = {item.get("id"): item for item in output.get("rows", []) if isinstance(item, dict)}
        for identity, (job_id, _code, _pcm) in pending.items():
            item = by_id.get(job_id)
            if item is None:
                raise IndependentASRError(f"{job_id}: recognizer produced no result")
            # The row label is not part of the result: one entry serves every
            # row with this audio and language.
            results[identity] = cache.store(
                identity, {key: value for key, value in item.items() if key != "id"},
            )

    # Derived after a hit exactly as after a miss (see the module docstring).
    recognitions = {
        row["id"]: _recognition(
            row, results[identities[row["id"]]], provenance=provenances[row["id"]],
            code_to_language=code_to_language,
        )
        for row in manifest["rows"]
    }

    producer = {
        "adapterID": config["adapterID"],
        "modelID": config["modelID"],
        "sourceRevision": config["sourceRevision"],
        "weightsSHA256": config["weightsSHA256"],
        "algorithmVersion": INDEPENDENT_ASR_ALGORITHM,
        "provenance": _provenance(config, language_code="*") | {"configSHA256": "per-row"},
        "rowCount": len(manifest["rows"]),
        "cacheHits": cache_hits,
        "modelLaunches": 1 if pending else 0,
        # Paid once per launch and kept out of every row's recognition time.
        "modelLoadSeconds": model_load_seconds,
        "warmupSeconds": warmup_seconds,
        "resourceEnvelope": envelope,
        # The resource supervisor's source and probe for the launch above;
        # None when every row was a cache hit and nothing launched.
        "envelopeIdentity": supervision,
    }
    if manifest.get("platform") == "cascade":
        rows_by_generation: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for row in manifest["rows"]:
            rows_by_generation.setdefault(row["generationID"], {}).setdefault(
                str(row.get("role")), []).append(recognitions[row["id"]])
        return {
            "policyID": REVIEW_POLICY,
            "executionPlanDigest": manifest.get("executionPlanDigest"),
            "rows": rows_by_generation,
            "producer": producer,
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "independent-asr-language-evidence",
        "runID": manifest["runID"],
        "platform": manifest["platform"],
        "generationProcessExited": True,
        "families": [FAMILY],
        "producer": producer,
        "cells": {
            row["id"]: {
                "cellID": row.get("cellID", row["id"]),
                "generationID": row["generationID"],
                "audioSHA256": row["audioSHA256"],
                "expectedLanguage": row["expectedLanguage"],
                "expectedOutcome": row.get("expectedOutcome", "pass"),
                "recognitions": [recognitions[row["id"]]],
            }
            for row in manifest["rows"]
        },
    }


def witness_verdict(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Per-row family consensus for a lane that publishes no record (audit #44).

    Each row's whisper recognition is re-qualified and re-scored from its
    transcript; when the manifest carries the in-app Apple Speech channel
    verdicts, the two families vote each channel (language, accuracy) through
    the shared consensus rule (audit #42). A row passes only when the families
    agree on every channel its expected outcome constrains (the negative
    control is an accuracy control); with one family the result is labelled
    one witness, never consensus. An unqualified recognition (a truncated
    decode, an empty transcript, uncovered edges) is no witness at all, as the
    publisher refuses it: its row is `unqualified` and never meets its
    expectation, so a broken decode cannot confirm a negative control.
    """
    manifest = validate_manifest(manifest)
    cells = evidence.get("cells") if isinstance(evidence, dict) else None
    if not isinstance(cells, dict):
        raise IndependentASRError("recognition evidence has no cells")
    rows: list[dict[str, Any]] = []
    for row in manifest["rows"]:
        entry = cells.get(row["id"])
        recognitions = entry.get("recognitions") if isinstance(entry, dict) else None
        if not isinstance(recognitions, list) or len(recognitions) != 1:
            raise IndependentASRError(f"{row['id']}: evidence needs exactly one recognition")
        recognition = recognitions[0]
        issues = recognition_issues(
            recognition, audio_sha256=row["audioSHA256"], script=row["referenceText"],
            script_sha256=row["scriptSHA256"], language=row["expectedLanguage"],
            duration_seconds=float(row["durationSeconds"]),
        )
        whisper = score_recognition(recognition, script=row["referenceText"], language=row["expectedLanguage"])
        family_channels: dict[str, dict[str, bool]] = {
            "whisper": {"language": bool(whisper["languagePass"]), "accuracy": bool(whisper["accuracyPass"])},
        }
        apple_channels = row.get("appleSpeechChannels")
        if isinstance(apple_channels, dict) and all(
            isinstance(apple_channels.get(channel), bool) for channel in ("language", "accuracy")
        ):
            family_channels["apple-speech"] = {
                "language": apple_channels["language"], "accuracy": apple_channels["accuracy"],
            }
        expected = "fail" if row.get("expectedOutcome") == "fail" else "pass"
        agreement = channel_consensus(family_channels, expect_failure=expected == "fail")
        if issues:
            status, met = "unqualified", False
        elif len(family_channels) >= 2:
            # `pass` means the families agreed on the expected outcome per
            # channel; `fail` that a channel contradicted it by consensus.
            status = {"met": "pass", "contradicted": "fail"}.get(agreement["outcome"], "inconclusive")
            met = agreement["outcome"] == "met"
        else:
            status = "one-witness"
            met = single_family_meets_expectation(
                whisper["languagePass"], whisper["accuracyPass"], expect_failure=expected == "fail",
            )
        rows.append({
            "id": row["id"], "cellID": row.get("cellID", row["id"]), "expectedOutcome": expected,
            "families": sorted(family_channels), "status": status, "expectationMet": met,
            "channels": agreement["statuses"],
            "whisperIssues": issues, "whisperErrorRate": whisper["errorRate"],
            "reasons": sorted({
                reason for channel in agreement["channels"].values() for reason in channel["reasons"]
            }),
        })
    families = sorted({family for row in rows for family in row["families"]})
    if any(row["status"] == "unqualified" for row in rows):
        overall = "unqualified"
    elif any(row["status"] == "inconclusive" for row in rows):
        overall = "inconclusive"
    elif not all(row["expectationMet"] for row in rows):
        overall = "fail"
    elif len(families) >= 2 and all(len(row["families"]) >= 2 for row in rows):
        overall = "pass"
    else:
        overall = "one-witness"
    return {"status": overall, "families": families, "rowCount": len(rows), "rows": rows}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_summary(evidence: dict[str, Any]) -> None:
    producer = evidence.get("producer", {})
    envelope = producer.get("resourceEnvelope") or {}
    print(
        f"independent-asr: rows={producer.get('rowCount')} cacheHits={producer.get('cacheHits')} "
        f"modelLaunches={producer.get('modelLaunches')} "
        f"peakRSSMB={(envelope.get('peakRSSBytes') or 0) // (1024 * 1024)} "
        f"wallSeconds={envelope.get('wallSeconds')}"
    )
    for cell_id, cell in sorted(evidence.get("cells", {}).items()):
        recognition = cell["recognitions"][0]
        print(
            f"  {cell_id:<28} detected={recognition.get('detectedLanguage')} "
            f"p={recognition.get('languageMatchScore'):.3f} fullFile={recognition.get('fullFileProcessed')} "
            f"segments={recognition.get('segmentCount')} status={recognition.get('status')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="build the recognition manifest")
    manifest.add_argument("--platform", choices=("macos", "ios", "cascade"), required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--diagnostics", type=Path)
    manifest.add_argument("--run-id")
    manifest.add_argument("--matrix", type=Path)
    manifest.add_argument("--corpus", type=Path)
    manifest.add_argument("--subset", choices=("quick", "full"))
    manifest.add_argument("--plan", type=Path)
    manifest.add_argument("--wav-dir", type=Path)
    manifest.add_argument("--cascade-input", type=Path)
    manifest.add_argument(
        "--generation-process-exited", action="store_true",
        help="the caller attests that no TTS engine process is running; required before any model loads",
    )

    transcribe = commands.add_parser("transcribe", help="recognize every manifest row")
    transcribe.add_argument("--manifest", type=Path, required=True)
    transcribe.add_argument("--adapter-config", type=Path, required=True,
                            help="untracked config from prepare_delivery_compact_model_config.py whisper-small-mlx")
    transcribe.add_argument("--output", type=Path, required=True)
    transcribe.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    transcribe.add_argument("--lock-root", type=Path)
    transcribe.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    transcribe.add_argument("--maximum-rss-bytes", type=int, default=MAXIMUM_RSS_BYTES)

    verdict = commands.add_parser("verdict", help="score evidence per row and report the family consensus")
    verdict.add_argument("--manifest", type=Path, required=True)
    verdict.add_argument("--evidence", type=Path, required=True)
    verdict.add_argument("--output", type=Path)

    args = parser.parse_args()
    try:
        from delivery_analysis_cache import DeliveryAnalysisCache, atomic_json, configured_resampler
        if args.command == "verdict":
            report = witness_verdict(_load_json(args.manifest), _load_json(args.evidence))
            if args.output is not None:
                atomic_json(args.output, report)
            for row in report["rows"]:
                print(f"  {row['id']:<48} {row['status']:<12} expected={row['expectedOutcome']} "
                      f"families={','.join(row['families'])}")
            print(f"witnesses={','.join(report['families'])} consensus={report['status']} "
                  f"rows={report['rowCount']}")
            # A labelled single witness is reported, not failed; a caller that
            # needs two families checks consensus=pass.
            return 0 if report["status"] in {"pass", "one-witness"} else 1
        if args.command == "manifest":
            if args.platform == "macos":
                missing = [name for name in ("diagnostics", "run_id", "matrix", "corpus", "subset", "wav_dir")
                           if getattr(args, name) is None]
                if missing:
                    raise IndependentASRError("macos manifest requires --" + ", --".join(m.replace("_", "-") for m in missing))
                value = build_macos_manifest(
                    diagnostics=args.diagnostics, run_id=args.run_id, matrix=args.matrix,
                    corpus=args.corpus, subset=args.subset, wav_dir=args.wav_dir,
                    generation_process_exited=args.generation_process_exited,
                )
            elif args.platform == "ios":
                missing = [name for name in ("diagnostics", "run_id", "plan", "corpus") if getattr(args, name) is None]
                if missing:
                    raise IndependentASRError("ios manifest requires --" + ", --".join(m.replace("_", "-") for m in missing))
                value = build_ios_manifest(
                    diagnostics=args.diagnostics, run_id=args.run_id, plan=args.plan, corpus=args.corpus,
                    generation_process_exited=args.generation_process_exited,
                )
            else:
                if args.cascade_input is None:
                    raise IndependentASRError("cascade manifest requires --cascade-input")
                value = build_cascade_manifest(cascade_input=args.cascade_input)
            atomic_json(args.output, value)
            print(json.dumps({"rows": len(value["rows"]), "platform": value["platform"],
                              "generationProcessExited": value["generationProcessExited"]}))
            return 0
        config = _load_json(args.adapter_config)
        cache = DeliveryAnalysisCache(args.cache_root, resampler_version=configured_resampler(config))
        evidence = transcribe_manifest(
            manifest=_load_json(args.manifest), config=config, cache=cache,
            lock_root=args.lock_root or args.cache_root,
            timeout_seconds=args.timeout_seconds, maximum_rss_bytes=args.maximum_rss_bytes,
        )
        atomic_json(args.output, evidence)
        _print_summary(evidence)
        return 0
    except (IndependentASRError, ValueError, OSError) as error:
        print(f"independent-asr: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
