#!/usr/bin/env python3
"""Independent full-file speech recognition of generated audio (whisper family).

The language lanes and the delivery cascade judge spoken content with recognizer
*families*; one family is one witness. Apple Speech runs only inside the iPhone
app, so this producer supplies the second family on the Mac: a pinned
`whisper-small` MLX model, decoded greedily with the language locked to the
expected language, detecting the language separately from the first 30 seconds.

Design rules for the 8 GB host:
  * Nothing here loads a model while the Qwen3 engine may be resident. The
    manifest must declare `generationProcessExited: true`; the lanes build it
    after their generation loop.
  * Exactly one supervised subprocess (`delivery_resource_supervisor`) loads the
    model once and transcribes every uncached row; the parent never imports MLX.
  * Results are cached in `DeliveryAnalysisCache` under an identity that binds
    the audio bytes, the canonical derivative, the model, the runtime and the
    per-language decode options, so re-analysis launches nothing.
  * Evidence carries transcripts of tracked corpus scripts, digests and
    envelopes; never audio bytes or local paths. It stays untracked.

Commands:
  manifest    build the row manifest for a macOS or iOS language run, or for a
              cascade input
  transcribe  run the producer over a manifest and write recognition evidence
  worker      internal child process (the only place MLX loads)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable
import wave

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.language_metrics import (  # noqa: E402
    INDEPENDENT_ASR_ALGORITHM,
    INDEPENDENT_RECOGNITION_SCHEMA,
    LANGUAGE_LOCALE_CODES,
    edges_covered,
    is_sha256,
    text_sha256,
)


SCHEMA_VERSION = 1
FAMILY = "whisper"
ADAPTER_ID = "whisper-small-mlx"
LAYER_ID = "independent-asr"
LAYER_VERSION = "1"
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
         role: str | None = None) -> dict[str, Any]:
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
        rows.append(_row(
            row_id=str(take["cellID"]), generation_id=str(record.get("generationID")), audio=audio,
            audio_sha256=declared, expected_language=str(take.get("expectedHint")),
            reference_text=script, expected_outcome=str(take.get("expectedOutcome", "pass")),
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
        "workerSourceSHA256": file_sha256(Path(__file__)),
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
        "processedDurationSeconds": duration,
        "segmentCount": len(segments),
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
    from delivery_analysis_cache import LayerIdentity, configured_resampler, file_sha256
    from delivery_compact_model_adapter import CompactAdapterError, validate_adapter_config
    from delivery_resource_supervisor import run_supervised

    manifest = validate_manifest(manifest)
    try:
        config = validate_adapter_config(config)
    except CompactAdapterError as error:
        raise IndependentASRError(str(error)) from error
    if config["adapterID"] != ADAPTER_ID:
        raise IndependentASRError("independent ASR requires the whisper-small-mlx adapter configuration")
    if cache.resampler_version != configured_resampler(config):
        raise IndependentASRError("cache resampler differs from the pinned adapter preprocessing")
    language_codes = {name: code for code, name in _code_to_language(config).items()}
    code_to_language = _code_to_language(config)
    supervise = supervisor or run_supervised

    pending: list[tuple[dict[str, Any], LayerIdentity, dict[str, str], str, Path]] = []
    recognitions: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    for row in manifest["rows"]:
        audio = Path(row["audioPath"])
        if not audio.is_file() or file_sha256(audio) != row["audioSHA256"]:
            raise IndependentASRError(f"{row['id']}: audio is missing or its bytes changed")
        code = language_codes.get(row["expectedLanguage"])
        if code is None:
            raise IndependentASRError(f"{row['id']}: adapter cannot lock {row['expectedLanguage']}")
        canonical = cache.canonicalize(audio)
        provenance = _provenance(config, language_code=code)
        # The runtime digest covers the interpreter, the dependency pins and this
        # worker's source, so a recognizer code change is a cache miss, never a
        # stale hit.
        identity = LayerIdentity(
            original_wav_sha256=canonical.original_wav_sha256,
            canonical_derivative_sha256=canonical.canonical_derivative_sha256,
            layer_id=LAYER_ID, layer_version=LAYER_VERSION,
            binary_sha256=provenance["runtimeSHA256"], model_id=config["modelID"],
            model_revision=config["sourceRevision"], weights_sha256=config["weightsSHA256"],
            preprocessing_config_digest=provenance["configSHA256"],
        )
        retained = cache.load(identity)
        if retained is not None:
            recognitions[row["id"]] = retained
            cache_hits += 1
            continue
        pending.append((row, identity, provenance, code, canonical.derivative_path))

    envelope: dict[str, Any] | None = None
    if pending:
        with tempfile.TemporaryDirectory(prefix="vocello-independent-asr-") as temporary:
            job_path = Path(temporary) / "job.json"
            job_path.write_text(json.dumps({
                "schemaVersion": SCHEMA_VERSION,
                "weights": str(config["weightsPath"]),
                "decodeOptions": config.get("decodeOptions") or {},
                "rows": [
                    {"id": row["id"], "pcmPath": str(pcm), "language": code}
                    for row, _identity, _provenance, code, pcm in pending
                ],
            }), encoding="utf-8")
            command = [str(config["binaryPath"]), str(Path(__file__).resolve()), "worker", "--job", str(job_path)]
            environment = dict(os.environ)
            environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
            result = supervise(
                command, lock_root=lock_root, timeout_seconds=timeout_seconds,
                maximum_rss_bytes=maximum_rss_bytes,
                maximum_physical_footprint_bytes=maximum_rss_bytes,
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
        by_id = {item.get("id"): item for item in output.get("rows", []) if isinstance(item, dict)}
        for row, identity, provenance, _code, _pcm in pending:
            item = by_id.get(row["id"])
            if item is None:
                raise IndependentASRError(f"{row['id']}: recognizer produced no result")
            entry = _recognition(row, item, provenance=provenance, code_to_language=code_to_language)
            recognitions[row["id"]] = cache.store(identity, entry)

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
        "resourceEnvelope": envelope,
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
                "generationID": row["generationID"],
                "audioSHA256": row["audioSHA256"],
                "expectedLanguage": row["expectedLanguage"],
                "expectedOutcome": row.get("expectedOutcome", "pass"),
                "recognitions": [recognitions[row["id"]]],
            }
            for row in manifest["rows"]
        },
    }


# --------------------------------------------------------------------------- #
# Worker (child process; the only place MLX loads)
# --------------------------------------------------------------------------- #

def _read_pcm16(path: Path) -> Any:
    import numpy as np
    data = np.frombuffer(path.read_bytes(), dtype="<i2")
    return (data.astype(np.float32) / 32768.0)


def _read_wav16k(path: Path) -> Any:
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        if stream.getframerate() != 16_000 or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise IndependentASRError("worker single-file input must be 16 kHz mono PCM16")
        frames = stream.readframes(stream.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def _worker_recognize(model_dir: Path, audio: Any, language: str | None, decode: dict[str, Any]) -> dict[str, Any]:
    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.audio import N_SAMPLES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.transcribe import ModelHolder

    fp16 = decode.get("fp16", True) is not False
    dtype = mx.float16 if fp16 else mx.float32
    started = time.monotonic()
    model = ModelHolder.get_model(str(model_dir), dtype)
    # Language identification reads the first 30 s exactly as upstream Whisper
    # does: pad or trim the *audio* to 30 s, then take its log-mel spectrogram.
    segment = log_mel_spectrogram(pad_or_trim(mx.array(audio), N_SAMPLES), n_mels=model.dims.n_mels).astype(dtype)
    _tokens, probabilities = model.detect_language(segment)
    detected = max(probabilities, key=probabilities.get)
    options: dict[str, Any] = {
        "path_or_hf_repo": str(model_dir),
        "temperature": float(decode.get("temperature", 0.0)),
        "condition_on_previous_text": bool(decode.get("conditionOnPreviousText", False)),
        "fp16": fp16,
        "word_timestamps": bool(decode.get("wordTimestamps", False)),
        "verbose": None,
    }
    if language is not None:
        options["language"] = language
    result = mlx_whisper.transcribe(audio, **options)
    segments = [
        {
            "start": float(item.get("start", 0.0)),
            "end": float(item.get("end", 0.0)),
            "noSpeechProb": float(item.get("no_speech_prob", 0.0)),
            "avgLogprob": float(item.get("avg_logprob", 0.0)),
        }
        for item in result.get("segments", [])
    ]
    return {
        "transcript": str(result.get("text", "")).strip(),
        "language": result.get("language"),
        "detectedLanguage": detected,
        "detectedLanguageProbability": float(probabilities[detected]),
        "expectedLanguageProbability": float(probabilities.get(language, 0.0)) if language else float(probabilities[detected]),
        "segments": segments,
        "wallSeconds": time.monotonic() - started,
    }


def worker_main(args: argparse.Namespace) -> int:
    if args.job is not None:
        job = _load_json(args.job)
        model_dir = Path(str(job["weights"])).parent
        decode = job.get("decodeOptions") or {}
        rows = []
        for row in job.get("rows", []):
            audio = _read_pcm16(Path(str(row["pcmPath"])))
            rows.append({"id": row["id"], **_worker_recognize(model_dir, audio, row.get("language"), decode)})
        payload = {"schemaVersion": SCHEMA_VERSION, "kind": "independent-asr-worker-output", "rows": rows}
    else:
        if args.weights is None or args.audio is None:
            raise IndependentASRError("worker needs --job or --weights with --audio")
        audio = _read_wav16k(args.audio)
        payload = _worker_recognize(Path(args.weights).parent, audio, args.language, {})
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


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

    worker = commands.add_parser("worker", help=argparse.SUPPRESS)
    worker.add_argument("--job", type=Path)
    worker.add_argument("--weights", type=Path)
    worker.add_argument("--audio", type=Path)
    worker.add_argument("--language")

    args = parser.parse_args()
    try:
        if args.command == "worker":
            return worker_main(args)
        from delivery_analysis_cache import DeliveryAnalysisCache, atomic_json, configured_resampler
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
