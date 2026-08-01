#!/usr/bin/env python3
"""Validate non-UI benchmark evidence and publish a compact history record.

This is the sole adapter between model-dependent non-UI runners and
``scripts/benchmark_history.py``.  It never copies raw audio, telemetry, labels,
or traces into Git.  Every subcommand first writes an atomic, allowlisted
``benchmark-evidence.json`` beside the untracked run artifacts, then asks the
registry to record it.  Once that manifest exists, delayed repair always calls
the registry directly so the frozen evidence is never regenerated.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata
import wave
from typing import Any, Iterable
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HISTORY_SCRIPT = ROOT / "scripts" / "benchmark_history.py"
MEMORY_POLICY_PATH = ROOT / "config" / "memory-qualification-policy.json"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_memory import (  # noqa: E402
    MemoryEvidenceError,
    REQUIRED_TELEMETRY_SCHEMA,
    qualify_memory_rows,
)
from language_bench_evidence import stable_default_seed  # noqa: E402
SUCCESS_FINISH = {"eos", "max_tokens", "maxtokens", "completed", "complete", "success", "ok"}
TRIM_SEVERITY = {"softTrim": 1, "hardTrim": 2, "fullUnload": 3}
UINT64_MAX = (1 << 64) - 1
LANGUAGE_SENTINEL_SCHEMA = 2
LANGUAGE_OUTPUT_SCHEMA = 3
LANGUAGE_OUTPUT_ALGORITHM = "language-output-verifier-v3"
ASR_EVIDENCE_SCHEMA = 2
ASR_EVIDENCE_ALGORITHM = "apple-speech-file-consensus-v2"
ASR_REQUIRED_PASS_COUNT = 3
LANGUAGE_ACCURACY_METRIC_VERSION = "normalized-edit-rate-v1"
LANGUAGE_SEED_POLICY = "sha256-v1-mode-script-language-63bit"
LANGUAGE_SAMPLING_VARIATION = "expressive"
LANGUAGE_PASS_SCORE = 0.5
LANGUAGE_ACCURACY_THRESHOLDS = {
    "wordErrorRate": 0.15,
    "characterErrorRate": 0.15,
}
LANGUAGE_LOCALE_CODES = {
    "english": "en",
    "chinese": "zh",
    "german": "de",
    "french": "fr",
    "russian": "ru",
    "portuguese": "pt",
    "spanish": "es",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
}
SAFE_LOCALE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")
SAFE_CUSTOM_SPEAKER = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PublicationError(RuntimeError):
    pass


def _load_history_module():
    spec = importlib.util.spec_from_file_location("benchmark_history_runtime", HISTORY_SCRIPT)
    if spec is None or spec.loader is None:
        raise PublicationError("benchmark history module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise PublicationError(f"expected a JSON object: {path}")
    return payload


def canonical_hardware_profile(platform: str) -> dict[str, Any]:
    payload = load_json(ROOT / "benchmarks" / "hardware-profiles.json")
    profiles = payload.get("profiles")
    if payload.get("schemaVersion") != 1 or not isinstance(profiles, list):
        raise PublicationError("hardware-profiles.json has an unsupported schema")
    matches = [
        profile for profile in profiles
        if isinstance(profile, dict)
        and profile.get("platform") == platform
        and profile.get("canonical") is True
    ]
    if len(matches) != 1:
        raise PublicationError(f"expected exactly one canonical {platform} hardware profile")
    return matches[0]


def _required_command_output(arguments: list[str], description: str) -> str:
    completed = subprocess.run(
        arguments, cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
        raise PublicationError(f"could not verify {description}: {detail}")
    value = completed.stdout.strip()
    if not value:
        raise PublicationError(f"could not verify {description}: empty result")
    return value


def verify_canonical_hardware(
    platform: str,
    *,
    ios_evidence: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prove the live benchmark host matches the tracked canonical profile.

    The registry's profile defaults are descriptive metadata, not runtime
    evidence.  Publication therefore performs this independent check before a
    profile ID is allowed into a manifest.
    """
    profile = canonical_hardware_profile(platform)
    if platform == "macos":
        model = _required_command_output(["sysctl", "-n", "hw.model"], "Mac model")
        memory_text = _required_command_output(
            ["sysctl", "-n", "hw.memsize"], "Mac physical memory"
        )
        try:
            memory_bytes = int(memory_text)
        except ValueError as error:
            raise PublicationError("Mac physical-memory evidence is not an integer") from error
        if model != profile.get("modelIdentifier") or memory_bytes != profile.get("memoryBytes"):
            raise PublicationError(
                "live Mac hardware does not match the canonical benchmark profile "
                f"({model}, {memory_bytes} bytes)"
            )
        return {"profileID": str(profile["id"])}

    if platform != "ios":
        raise PublicationError(f"unsupported benchmark platform: {platform}")
    records = list(ios_evidence or [])
    if not records:
        raise PublicationError("iOS hardware verification requires device sentinel evidence")
    versions: set[str] = set()
    for record in records:
        if (
            record.get("deviceModel") != "iPhone"
            or record.get("systemName") != "iOS"
            or not isinstance(record.get("systemVersion"), str)
            or not record.get("systemVersion")
        ):
            raise PublicationError("iOS sentinel lacks exact physical-iPhone OS evidence")
        versions.add(str(record["systemVersion"]))
    if len(versions) != 1:
        raise PublicationError("iOS benchmark sentinels do not share one OS version")

    descriptor, temporary = tempfile.mkstemp(prefix="vocello-hardware-", suffix=".json")
    os.close(descriptor)
    try:
        completed = subprocess.run(
            [
                "xcrun", "devicectl", "list", "devices", "--quiet", "--timeout", "5",
                "--json-output", temporary,
            ],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
            raise PublicationError(f"could not verify physical iPhone hardware: {detail}")
        payload = load_json(Path(temporary))
    finally:
        Path(temporary).unlink(missing_ok=True)

    devices = (payload.get("result") or {}).get("devices")
    if not isinstance(devices, list):
        raise PublicationError("devicectl returned no device inventory")
    expected_version = next(iter(versions))
    candidates: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        hardware = device.get("hardwareProperties") or {}
        properties = device.get("deviceProperties") or {}
        connection = device.get("connectionProperties") or {}
        reachable = (
            connection.get("pairingState") == "paired"
            or connection.get("tunnelState") in {"connected", "available"}
        )
        if (
            hardware.get("platform") == "iOS"
            and properties.get("osVersionNumber") == expected_version
            and reachable
        ):
            candidates.append(device)
    if len(candidates) != 1:
        raise PublicationError(
            "iOS sentinel evidence does not resolve to exactly one reachable CoreDevice"
        )
    observed_model = (candidates[0].get("hardwareProperties") or {}).get("productType")
    if observed_model != profile.get("modelIdentifier"):
        raise PublicationError(
            "physical iPhone does not match the canonical benchmark profile "
            f"({observed_model!r})"
        )
    return {"profileID": str(profile["id"])}


def ios_run_hardware_evidence(diagnostics: Path, run_id: str) -> list[dict[str, Any]]:
    """Return privacy-reduced physical-device evidence for one headless iOS run."""
    candidates = [diagnostics / run_id / "manifest.json"]
    if diagnostics.name == run_id:
        candidates.append(diagnostics / "manifest.json")
    existing = list(dict.fromkeys(path for path in candidates if path.is_file()))
    if len(existing) != 1:
        raise PublicationError(
            "iOS headless benchmark requires exactly one run-scoped diagnostics manifest"
        )
    manifest = load_json(existing[0])
    if manifest.get("runID") != run_id:
        raise PublicationError("iOS diagnostics manifest does not match the benchmark run")
    return [{
        "deviceModel": manifest.get("deviceModel"),
        "systemName": manifest.get("systemName"),
        "systemVersion": manifest.get("systemVersion"),
    }]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PublicationError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def history_git_state() -> dict[str, Any]:
    return _load_history_module().git_state()


def crash_digests(scope: str, diagnostics: Path | None = None) -> list[str]:
    if scope == "none":
        return []
    if scope == "macos":
        root = Path.home() / "Library" / "Logs" / "DiagnosticReports"
        candidates = [
            path for path in root.glob("*.ips")
            if path.name.startswith(("Vocello-", "QwenVoiceEngineService-"))
            or "engine-service" in path.name.lower()
        ] if root.is_dir() else []
    elif scope == "ios":
        if diagnostics is None or not diagnostics.is_dir():
            raise PublicationError("iOS crash proof requires a pulled pre-run diagnostics directory")
        candidates = [
            path for path in diagnostics.rglob("*")
            if path.is_file() and "crashes" in {part.lower() for part in path.parts}
        ]
    else:
        raise PublicationError(f"unsupported crash proof scope: {scope}")
    return sorted({digest_file(path) for path in candidates})


def capture_snapshot(output: Path, crash_scope: str, crash_diagnostics: Path | None = None) -> None:
    state = history_git_state()
    atomic_json(output, {
        "schemaVersion": 1,
        "capturedAt": utc_now(),
        "source": state,
        "crashEvidence": {
            "scope": crash_scope,
            "digests": crash_digests(crash_scope, crash_diagnostics),
        },
    })


def source_from_snapshot(snapshot_path: Path) -> dict[str, Any]:
    if not snapshot_path.is_file():
        raise PublicationError(
            f"missing pre-run source snapshot: {snapshot_path}; rerun the benchmark from the start"
        )
    if snapshot_path.name != "benchmark-source.json":
        raise PublicationError("pre-run snapshot must be named benchmark-source.json")
    return _load_history_module().source_state_for_artifact(snapshot_path.parent)


def crash_delta_from_snapshot(
    snapshot_path: Path,
    *,
    expected_scope: str,
    diagnostics: Path | None = None,
) -> dict[str, Any]:
    snapshot = load_json(snapshot_path)
    crash_evidence = snapshot.get("crashEvidence")
    if not isinstance(crash_evidence, dict) or crash_evidence.get("scope") != expected_scope:
        raise PublicationError(f"pre-run snapshot lacks {expected_scope} crash evidence")
    before = crash_evidence.get("digests")
    if not isinstance(before, list) or not all(isinstance(item, str) for item in before):
        raise PublicationError("pre-run crash digest set is malformed")
    after = crash_digests(expected_scope, diagnostics)
    added = sorted(set(after) - set(before))
    if added:
        raise PublicationError(f"benchmark produced {len(added)} new crash report(s)")
    return {"passed": True, "count": 0}


def finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def find_engine_files(diagnostics: Path) -> list[Path]:
    direct = diagnostics / "engine" / "generations.jsonl"
    if direct.is_file():
        return [direct]
    paths = sorted(
        path for path in diagnostics.rglob("generations.jsonl")
        if path.parent.name == "engine" and path.is_file()
    )
    if not paths:
        raise PublicationError(f"no engine/generations.jsonl under {diagnostics}")
    return paths


def load_engine_rows(diagnostics: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in find_engine_files(diagnostics):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise PublicationError(f"invalid telemetry JSON at {path}:{line_number}: {error}") from error
            if isinstance(row, dict) and row.get("layer") == "engine":
                rows.append(row)
    return rows


def load_app_rows(diagnostics: Path) -> list[dict[str, Any]]:
    direct = diagnostics / "app" / "generations.jsonl"
    paths = [direct] if direct.is_file() else sorted(
        path for path in diagnostics.rglob("generations.jsonl")
        if path.parent.name == "app" and path.is_file()
    )
    if not paths:
        raise PublicationError(f"no app/generations.jsonl under {diagnostics}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise PublicationError(
                    f"invalid app telemetry JSON at {path}:{line_number}: {error}"
                ) from error
            if isinstance(row, dict) and row.get("layer") == "app":
                rows.append(row)
    return rows


def validate_language_app_row(
    row: dict[str, Any], *, run_id: str, cell_id: str, planned_take: dict[str, Any]
) -> None:
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    finish = str(row.get("finishReason", "")).lower()
    frontend = row.get("frontendMetrics") if isinstance(row.get("frontendMetrics"), dict) else {}
    submit_to_completed = finite_number(frontend.get("submitToCompletedMS"))
    if (
        not isinstance(row.get("schemaVersion"), int) or row["schemaVersion"] < 7
        or row.get("layer") != "app"
        or row.get("generationID") is None
        or row.get("mode") != planned_take.get("mode")
        or finish not in SUCCESS_FINISH
        or notes.get("benchRunID") != run_id
        or notes.get("benchCell") != cell_id
        or submit_to_completed is None
        or submit_to_completed <= 0
    ):
        raise PublicationError(f"language cell {cell_id} app telemetry identity is invalid")


def correlated_ios_app_rows(
    *,
    diagnostics: Path,
    engine_rows: Iterable[dict[str, Any]],
    takes: Iterable[dict[str, Any]],
    run_id: str,
) -> list[dict[str, Any]]:
    """Select one completed app row for each ordered iOS engine generation.

    iOS uses one process, so the engine sampler remains the sole owner of process
    memory and its sidecar. The app row is nevertheless mandatory frontend
    lifecycle evidence and is bound into the selected-evidence digest.
    """
    ordered_engine = list(engine_rows)
    ordered_takes = list(takes)
    if len(ordered_engine) != len(ordered_takes) or not ordered_engine:
        raise PublicationError("iOS app correlation requires matching non-empty engine/take rows")
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in load_app_rows(diagnostics):
        generation_id = row.get("generationID")
        if isinstance(generation_id, str):
            indexed.setdefault(generation_id.lower(), []).append(row)

    selected: list[dict[str, Any]] = []
    for index, (engine, take) in enumerate(zip(ordered_engine, ordered_takes), start=1):
        generation_id = engine.get("generationID")
        if not isinstance(generation_id, str) or not generation_id:
            raise PublicationError("iOS engine telemetry lacks a generation ID")
        if str(take.get("generationID", "")).lower() != generation_id.lower():
            raise PublicationError(
                f"iOS take {index} does not identify engine generation {generation_id}"
            )
        matches = indexed.get(generation_id.lower(), [])
        if len(matches) != 1:
            raise PublicationError(
                f"iOS generation {generation_id} has {len(matches)} app rows; expected exactly one"
            )
        app = matches[0]
        notes = app.get("notes") if isinstance(app.get("notes"), dict) else {}
        frontend = (
            app.get("frontendMetrics")
            if isinstance(app.get("frontendMetrics"), dict) else {}
        )
        timings = app.get("timingsMS") if isinstance(app.get("timingsMS"), dict) else {}
        frontend_completed = finite_number(frontend.get("submitToCompletedMS"))
        timing_completed = finite_number(timings.get("submitToCompletedMS"))
        finish = str(app.get("finishReason", "")).lower()
        expected_cell = take.get("cell")
        expected_mode = take.get("mode")
        if (
            not isinstance(app.get("schemaVersion"), int) or app["schemaVersion"] < 8
            or app.get("layer") != "app"
            or str(app.get("generationID", "")).lower() != generation_id.lower()
            or app.get("mode") != expected_mode
            or finish not in SUCCESS_FINISH
            or notes.get("benchRunID") != run_id
            or str(notes.get("benchTakeIndex", "")) != str(index)
            or notes.get("benchCell") != expected_cell
            or frontend_completed is None or frontend_completed <= 0
            or timing_completed is None or timing_completed != frontend_completed
        ):
            raise PublicationError(
                f"iOS generation {generation_id} app telemetry identity/completion is invalid"
            )
        if app.get("summary") not in (None, {}) or app.get("memoryMetrics") not in (None, {}):
            raise PublicationError(
                f"iOS generation {generation_id} app row must not own process-memory evidence"
            )
        selected.append(app)
    return selected


def rows_by_generation(rows: Iterable[dict[str, Any]], generation_ids: Iterable[str]) -> list[dict[str, Any]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        generation_id = row.get("generationID")
        if isinstance(generation_id, str):
            indexed.setdefault(generation_id.lower(), []).append(row)
    selected: list[dict[str, Any]] = []
    for generation_id in generation_ids:
        matches = indexed.get(generation_id.lower(), [])
        if len(matches) != 1:
            raise PublicationError(
                f"generation {generation_id} has {len(matches)} engine rows; expected exactly one"
            )
        selected.append(matches[0])
    return selected


def successful_row(row: dict[str, Any]) -> None:
    finish = str(row.get("finishReason", "")).lower()
    if finish not in SUCCESS_FINISH:
        raise PublicationError(f"generation {row.get('generationID')} has unsuccessful finishReason={finish!r}")
    output = row.get("outputMetrics")
    if not isinstance(output, dict) or output.get("readableWAV") is not True or output.get("atomicallyPublished") is not True:
        raise PublicationError(f"generation {row.get('generationID')} lacks readable atomic WAV proof")
    qc = row.get("audioQC")
    if int(row.get("schemaVersion", 0)) >= 7 and (
        not isinstance(qc, dict)
        or any(qc.get(key) is None for key in ("verdict", "instabilityVerdict", "writtenOutputVerdict"))
    ):
        raise PublicationError(
            f"generation {row.get('generationID')} lacks schema-v7 instability/written-output QC verdicts"
        )
    if int(row.get("schemaVersion", 0)) >= 7 and not isinstance(row.get("backendMetrics"), dict):
        raise PublicationError(f"generation {row.get('generationID')} lacks schema-v7 backendMetrics")
    verdicts = [
        str(qc.get(key)).lower()
        for key in ("verdict", "instabilityVerdict", "writtenOutputVerdict")
        if isinstance(qc, dict) and qc.get(key) is not None
    ]
    if not verdicts or any(verdict not in {"pass", "warn"} for verdict in verdicts):
        raise PublicationError(f"generation {row.get('generationID')} has unacceptable audio QC={verdicts!r}")


def row_metrics(row: dict[str, Any], take: dict[str, Any] | None = None) -> dict[str, float]:
    derived = row.get("derivedMetrics") if isinstance(row.get("derivedMetrics"), dict) else {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    timings = row.get("timingsMS") if isinstance(row.get("timingsMS"), dict) else {}
    backend = row.get("backendMetrics") if isinstance(row.get("backendMetrics"), dict) else {}
    typed_timings = {
        item.get("key"): item.get("milliseconds")
        for item in backend.get("timings", [])
        if isinstance(item, dict)
    }
    resources = summary.get("processResourceUsage") if isinstance(summary.get("processResourceUsage"), dict) else {}
    minor_faults = finite_number(resources.get("minorPageFaults")) or 0.0
    major_faults = finite_number(resources.get("majorPageFaults")) or 0.0
    voluntary_switches = finite_number(resources.get("voluntaryContextSwitches")) or 0.0
    involuntary_switches = finite_number(resources.get("involuntaryContextSwitches")) or 0.0
    block_inputs = finite_number(resources.get("blockInputOperations")) or 0.0
    block_outputs = finite_number(resources.get("blockOutputOperations")) or 0.0
    stage_marks = backend.get("stages") or row.get("stageMarks") or summary.get("stageMarks") or []
    trim_levels = [
        (mark.get("metadata") or {}).get("level")
        for mark in stage_marks
        if isinstance(mark, dict) and mark.get("stage") == "memory_trim"
    ]
    candidates = {
        "rtf": derived.get("audioSecondsPerWallSecond"),
        "tokensPerSecond": derived.get("tokensPerSecond"),
        "decodeWallSeconds": derived.get("decodeWallSeconds"),
        "audioSeconds": derived.get("audioSeconds"),
        "generatedTokens": derived.get("generatedTokenCount"),
        "modelLoadMS": typed_timings.get("modelLoad", timings.get("native_model_load_ms")),
        "prewarmMS": typed_timings.get("explicitPrewarm", timings.get("native_prewarm_ms")),
        "finalizationMS": typed_timings.get("finalWAVFinish", timings.get("native_final_wav_finish_ms")),
        "peakPhysicalFootprintMB": summary.get("physFootprintPeakMB"),
        "peakResidentMB": summary.get("residentPeakMB"),
        "peakCompressedMB": summary.get("compressedPeakMB"),
        "peakGPUAllocatedMB": summary.get("gpuAllocatedPeakMB"),
        "minimumHeadroomMB": summary.get("headroomMinMB"),
        "cpuUserSeconds": (
            float(resources["userCPUTimeMS"]) / 1_000.0
            if finite_number(resources.get("userCPUTimeMS")) is not None else None
        ),
        "cpuSystemSeconds": (
            float(resources["systemCPUTimeMS"]) / 1_000.0
            if finite_number(resources.get("systemCPUTimeMS")) is not None else None
        ),
        "pageFaults": minor_faults + major_faults if resources else None,
        "contextSwitches": voluntary_switches + involuntary_switches if resources else None,
        "blockIOOperations": block_inputs + block_outputs if resources else None,
        "samplerTargetIntervalMS": (
            float(summary["targetIntervalNS"]) / 1_000_000.0
            if finite_number(summary.get("targetIntervalNS")) is not None else None
        ),
        "samplerEffectiveMedianIntervalMS": (
            float(summary["effectiveIntervalNS"]) / 1_000_000.0
            if finite_number(summary.get("effectiveIntervalNS")) is not None else None
        ),
        "samplerMaximumLatenessMS": (
            float(summary["maximumLatenessNS"]) / 1_000_000.0
            if finite_number(summary.get("maximumLatenessNS")) is not None else None
        ),
        "samplerMaximumDriftMS": (
            float(summary["maximumDriftNS"]) / 1_000_000.0
            if finite_number(summary.get("maximumDriftNS")) is not None else None
        ),
        "samplerBoundarySampleCount": summary.get("boundarySampleCount"),
        "samplerCaptureFailureCount": summary.get("captureFailureCount"),
        "memoryTrimCount": len(trim_levels),
        "maximumTrimLevel": max(
            (TRIM_SEVERITY.get(level, 0) for level in trim_levels), default=0
        ),
    }
    if take is not None:
        candidates["ttfcMS"] = take.get("firstChunkMS")
        wall = finite_number(take.get("wallSeconds"))
        audio = finite_number(take.get("audioSeconds"))
        if wall and wall > 0 and audio is not None:
            candidates["rtf"] = audio / wall
    return {
        key: number for key, value in candidates.items()
        if (number := finite_number(value)) is not None
    }


def qc_record(row: dict[str, Any]) -> dict[str, Any]:
    qc = row["audioQC"]
    verdicts = [
        str(qc.get(key)).lower()
        for key in ("verdict", "instabilityVerdict", "writtenOutputVerdict")
        if qc.get(key) is not None
    ]
    rank = {"pass": 0, "warn": 1, "fail": 2}
    verdict = max(verdicts or ["pass"], key=lambda item: rank.get(item, 99))
    flags = [str(item) for item in qc.get("flags", []) if isinstance(item, str)]
    if str(qc.get("instabilityVerdict", "pass")).lower() == "warn":
        flags.append("instability-warn")
    if str(qc.get("writtenOutputVerdict", "pass")).lower() == "warn":
        flags.append("written-output-warn")
    metrics: dict[str, float] = {}
    for source, target in (
        ("clickEvents", "discontinuityCount"),
        ("clippedSamples", "clipCount"),
        ("nonFiniteSamples", "nonFiniteCount"),
        ("longestSilenceMS", "longestSilenceMS"),
        ("dcOffset", "dcOffset"),
    ):
        if (value := finite_number(qc.get(source))) is not None:
            metrics[target] = value
    return {
        "algorithmVersion": int(qc.get("algorithmVersion", 1)),
        "verdict": verdict,
        "instabilityVerdict": str(qc.get("instabilityVerdict", qc.get("verdict", "pass"))).lower(),
        "writtenOutputVerdict": str(qc.get("writtenOutputVerdict", qc.get("verdict", "pass"))).lower(),
        "warningCodes": sorted(set(flags)) if verdict == "warn" else [],
        "metrics": metrics,
    }


def thermal_state(row: dict[str, Any]) -> str:
    thermal = row.get("thermalState")
    if isinstance(thermal, dict):
        value = thermal.get("worst") or thermal.get("end") or thermal.get("start")
    else:
        value = thermal
    return str(value or "unknown").lower()


def hardware_context(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    environments: list[dict[str, Any]] = []
    thermal_values: list[str] = []
    for row in rows:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        environment = summary.get("runEnvironment")
        if isinstance(environment, dict):
            environments.append(environment)
            thermal_values.append(str(environment.get("thermalState", "unknown")).lower())
        thermal_values.append(thermal_state(row))
    result: dict[str, Any] = {}
    if environments:
        first = environments[0]
        if (value := finite_number(first.get("loadAverage1Minute"))) is not None:
            result["loadAverage1M"] = value
        free_values = [
            value for environment in environments
            if (value := finite_number(environment.get("freeStorageBytes"))) is not None
        ]
        uptime_values = [
            value for environment in environments
            if (value := finite_number(environment.get("uptimeSeconds"))) is not None
        ]
        if free_values:
            result["freeStorageBytes"] = int(min(free_values))
        if uptime_values:
            result["uptimeSeconds"] = min(uptime_values)
        low_power = [environment.get("lowPowerModeEnabled") for environment in environments]
        if all(isinstance(value, bool) for value in low_power):
            result["lowPowerMode"] = any(low_power)
    thermal_rank = {"nominal": 0, "fair": 1, "serious": 2, "critical": 3, "unknown": -1}
    known_thermal = [value for value in thermal_values if value in thermal_rank and value != "unknown"]
    if known_thermal:
        result["thermalState"] = max(known_thermal, key=lambda value: thermal_rank[value])
    return result


def uses_forced_memory_profile(rows: Iterable[dict[str, Any]]) -> bool:
    for row in rows:
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        if str(notes.get("deviceClassForced", "false")).lower() == "true":
            return True
        if notes.get("memoryProfile") or notes.get("simulatedProcessLimitMB"):
            return True
    return False


def prompt_corpus_digest(rows: Iterable[dict[str, Any]]) -> str:
    ordered: list[str] = []
    for row in rows:
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        digest = notes.get("promptDigest")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise PublicationError(
                f"generation {row.get('generationID')} lacks a privacy-safe prompt digest"
            )
        ordered.append(digest)
    if not ordered:
        raise PublicationError("benchmark has no prompt corpus identity")
    return digest_bytes(canonical_bytes(ordered))


def exact_models(platform: str, takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _load_history_module().default_models({
        "run": {"platform": platform},
        "takes": takes,
    })


def runtime_identity(row: dict[str, Any], *, mode: str, model_id: str) -> dict[str, str]:
    """Return the complete typed model/runtime identity for one engine row.

    Schema-v7 evidence must never fall back to the historical free-form maps.
    Older rows remain decodable for local analysis, but only the typed payload is
    authoritative for a new v1 history record.
    """
    schema = int(row.get("schemaVersion", 0))
    identity = row.get("modelRuntimeIdentity")
    if schema >= 7:
        if not isinstance(identity, dict):
            raise PublicationError("schema-v7 engine telemetry lacks modelRuntimeIdentity")
        resolved = identity.get("resolvedModelID")
        required = {
            "modelRepository": identity.get("modelRepository"),
            "modelRevision": identity.get("huggingFaceRevision"),
            "modelArtifactVersion": identity.get("artifactVersion"),
            "modelQuantization": identity.get("quantization"),
            "modelIntegrityDigest": identity.get("integrityManifestDigest"),
            "runtimeProfileSignature": identity.get("runtimeProfileSignature"),
        }
        if resolved != model_id:
            raise PublicationError(
                f"typed resolved model {resolved!r} does not match telemetry model {model_id!r}"
            )
        for field, value in required.items():
            if not isinstance(value, str) or not value:
                raise PublicationError(f"schema-v7 engine telemetry lacks {field}")
        if required["modelQuantization"] not in {"4-bit", "8-bit", "unquantized"}:
            raise PublicationError("schema-v7 engine telemetry has invalid modelQuantization")
        for field in ("modelRevision", "modelIntegrityDigest"):
            value = required[field]
            expected_length = 40 if field == "modelRevision" else 64
            if len(value) != expected_length or any(character not in "0123456789abcdef" for character in value):
                raise PublicationError(f"schema-v7 engine telemetry has invalid {field}")
        fixture_digest = identity.get("fixtureDigest")
    else:
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        required = {
            "modelRepository": str(notes.get("modelRepository", "not-applicable")),
            "modelRevision": str(notes.get("huggingFaceRevision", "not-applicable")),
            "modelArtifactVersion": str(notes.get("artifactVersion", "not-applicable")),
            "modelQuantization": str(notes.get("quantization", "not-applicable")),
            "modelIntegrityDigest": str(notes.get("integrityManifestDigest", "not-applicable")),
            "runtimeProfileSignature": str(notes.get("qwen3RuntimeProfileSignature") or model_id),
        }
        fixture_digest = notes.get("fixtureDigest")
    if fixture_digest is not None:
        if (
            not isinstance(fixture_digest, str)
            or len(fixture_digest) != 64
            or any(character not in "0123456789abcdef" for character in fixture_digest)
        ):
            raise PublicationError(f"invalid typed fixture digest for {mode}")
    if mode in {"design", "clone"} and fixture_digest is None:
        raise PublicationError(f"schema-v7 {mode} telemetry lacks fixtureDigest")
    required["fixtureDigest"] = str(fixture_digest or "not-applicable")
    return {field: str(value) for field, value in required.items()}


def require_fixture_cross_check(
    takes: list[dict[str, Any]],
    expected: dict[str, str],
    *,
    source: str,
) -> None:
    for mode in {str(take.get("mode")) for take in takes} & {"design", "clone"}:
        observed = {take.get("fixtureDigest") for take in takes if take.get("mode") == mode}
        if len(observed) != 1 or None in observed:
            raise PublicationError(f"{mode} takes do not share one typed fixture digest")
        expected_digest = expected.get(mode)
        if expected_digest != next(iter(observed)):
            raise PublicationError(f"{source} {mode} fixture digest does not match engine telemetry")


def wave_output(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise PublicationError(f"benchmark output is missing: {path}")
    try:
        with wave.open(str(path), "rb") as stream:
            frames = stream.getnframes()
            sample_rate = stream.getframerate()
            channels = stream.getnchannels()
    except (OSError, wave.Error) as error:
        raise PublicationError(f"benchmark output is not a readable WAV: {path}: {error}") from error
    if frames <= 0 or sample_rate <= 0 or channels <= 0:
        raise PublicationError(f"benchmark output has an invalid WAV header: {path}")
    duration = frames / sample_rate
    return {
        "readableWAV": True,
        "atomicPublish": True,
        "durationSeconds": duration,
        "sampleRate": sample_rate,
        "channels": channels,
        "frames": frames,
        "fileDigest": digest_file(path),
    }


def telemetry_output(row: dict[str, Any]) -> dict[str, Any]:
    output = row["outputMetrics"]
    duration = finite_number(output.get("durationSeconds"))
    result: dict[str, Any] = {"readableWAV": True, "atomicPublish": True}
    if duration is not None:
        result["durationSeconds"] = duration
    return result


def fold_delivery_prosody(
    result_takes: list[dict[str, Any]],
    takes: list[dict[str, Any]],
    prosody_rows: list[dict[str, Any]],
) -> None:
    """Fold the delivery sidecar's per-take metrics and prosody gate verdict
    into the tracked takes. Stage 3: the gate verdict computed by the same
    analysis pass must reach PASS-only history — advisory flags become
    machine warnings; an absent or incomplete verdict cannot publish."""
    for result_take, tracked_take in zip(result_takes, takes):
        delivery = result_take.get("delivery")
        if not delivery:
            continue
        matches = [
            row for row in prosody_rows
            if row.get("mode") == result_take.get("mode")
            and row.get("model") == result_take.get("modelID")
            and row.get("delivery") == delivery
        ]
        if len(matches) != 1:
            raise PublicationError(
                f"delivery take {tracked_take['generationID']} has {len(matches)} prosody rows"
            )
        metrics = matches[0].get("deliveryMetrics")
        if not isinstance(metrics, dict) or "error" in metrics:
            raise PublicationError("delivery prosody analysis is incomplete")
        mapping = {
            "f0_mean_hz": "f0MeanHz",
            "f0_std_hz": "f0StdHz",
            "f0_turning_points_per_sec": "f0TurningPointsPerSecond",
            "rate_syllable_rate_hz": "syllableRateHz",
            "rate_local_rate_cv": "localRateCV",
            "pauses_max_pause_seconds": "maximumPauseSeconds",
            "pauses_pause_speech_ratio": "pauseSpeechRatio",
            "energy_envelope_roughness": "energyEnvelopeRoughness",
        }
        for source, target in mapping.items():
            if (value := finite_number(metrics.get(source))) is not None:
                tracked_take["metrics"][target] = value
        # Paired neutral-vs-instructed deltas: the calibration signal for the
        # per-preset delivery expectations. Banked so committed records grow
        # fittable distributions instead of prose summaries.
        paired_mapping = {
            "dF0Std": "deliveryDF0StdHz",
            "dRateCV": "deliveryDRateCV",
            "dPauseRatio": "deliveryDPauseRatio",
            "dRoughness": "deliveryDRoughness",
            "prosodyEffect": "deliveryProsodyEffect",
        }
        for source, target in paired_mapping.items():
            if (value := finite_number(matches[0].get(source))) is not None:
                tracked_take["metrics"][target] = value
        gate = matches[0].get("qualityGate")
        if not isinstance(gate, dict) or gate.get("passed") not in (True, False) \
                or not isinstance(gate.get("flags"), list):
            raise PublicationError(
                f"delivery take {tracked_take['generationID']} lacks a prosody gate verdict"
            )
        gate_flags = [str(flag) for flag in gate["flags"]]
        if {"metrics_incomplete", "analysis_failed"} & set(gate_flags):
            raise PublicationError(
                f"delivery take {tracked_take['generationID']} prosody gate analysis is incomplete"
            )
        if gate_flags:
            tracked_take["warnings"] = sorted(
                set(tracked_take.get("warnings", []))
                | {f"prosody_gate:{flag}" for flag in gate_flags}
            )
            tracked_take["status"] = "passedWithWarnings"
        delivery_gate = matches[0].get("deliveryGate")
        if not isinstance(delivery_gate, dict) \
                or delivery_gate.get("passed") not in (True, False) \
                or not isinstance(delivery_gate.get("flags"), list):
            raise PublicationError(
                f"delivery take {tracked_take['generationID']} lacks a delivery adherence verdict"
            )
        delivery_flags = [str(flag) for flag in delivery_gate["flags"]]
        failure_flags = {
            "analysis_failed", "metrics_incomplete", "expectation_missing", "cohort_too_small",
        }
        if failure_flags & set(delivery_flags):
            raise PublicationError(
                f"delivery take {tracked_take['generationID']} delivery gate analysis is incomplete"
            )
        gate_metrics = delivery_gate.get("metrics")
        if isinstance(gate_metrics, dict):
            for source, target in (
                ("pitch_shift_semitones", "deliveryPitchShiftSemitones"),
                ("arousal_score", "deliveryArousalScore"),
            ):
                if (value := finite_number(gate_metrics.get(source))) is not None:
                    tracked_take["metrics"][target] = value
        if delivery_flags:
            tracked_take["warnings"] = sorted(
                set(tracked_take.get("warnings", []))
                | {f"delivery_gate:{flag}" for flag in delivery_flags}
            )
            tracked_take["status"] = "passedWithWarnings"


def quality_identity_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Phase 13: typed quality-registry identity from the engine row's open
    telemetry notes. Empty when the row predates the phase-12 registry —
    the record then publishes at schema v2; a run mixing both is an error
    resolved by the record-version chooser."""
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    outcome = notes.get("quality_registry_outcome")
    gates = notes.get("quality_registry_required_gates")
    if not isinstance(outcome, str) or not isinstance(gates, str) or not gates:
        return {}
    fields: dict[str, Any] = {
        "qualityRegistryOutcome": outcome,
        "qualityRegistryRequiredGates": sorted(set(gates.split(","))),
    }
    issues = notes.get("quality_registry_issues")
    if isinstance(issues, str) and issues:
        fields["qualityRegistryIssues"] = sorted(set(issues.split(",")))
    return fields


def history_record_schema_version(takes: list[dict[str, Any]]) -> int:
    """3 when every take carries the quality identity, 2 when none does.
    A mix would publish a record silently missing evidence for some takes."""
    carrying = sum(1 for take in takes if "qualityRegistryOutcome" in take)
    if carrying == 0:
        return 2
    if carrying == len(takes):
        return 3
    raise PublicationError(
        "takes mix quality-registry identity presence; refusing a partial schema-v3 record"
    )


def engine_take(
    index: int,
    take: dict[str, Any],
    row: dict[str, Any],
    output_dir: Path | None,
    *,
    run_id: str,
) -> dict[str, Any]:
    successful_row(row)
    generation_id = str(take.get("generationID", ""))
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    if notes.get("benchRunID") != run_id:
        raise PublicationError(f"generation {generation_id} has the wrong or missing benchRunID")
    if notes.get("benchTakeIndex") is None or str(notes.get("benchTakeIndex")) != str(index):
        raise PublicationError(f"generation {generation_id} has the wrong benchTakeIndex")
    if not isinstance(notes.get("benchCell"), str) or notes.get("benchCell") != take.get("cell"):
        raise PublicationError(f"generation {generation_id} has the wrong ordered cell")
    if row.get("mode") != take.get("mode") or row.get("modelID") != take.get("modelID"):
        raise PublicationError(f"generation {generation_id} telemetry identity does not match bench results")
    mode = str(take.get("mode"))
    model_id = str(take.get("modelID"))
    identity = runtime_identity(row, mode=mode, model_id=model_id)
    qc = qc_record(row)
    output = (
        wave_output(output_dir / str(take.get("outputFileName", "")), row)
        if output_dir is not None else telemetry_output(row)
    )
    duration = finite_number(take.get("wallSeconds"))
    result: dict[str, Any] = {
        "takeIndex": index,
        "generationID": generation_id,
        "cell": str(take.get("cell")),
        "mode": mode,
        "modelID": model_id,
        "variant": str(take.get("variant", "speed")),
        "warmState": str(take.get("warmState", row.get("warmState", "unknown"))),
        "length": str(take.get("length", "not-applicable")),
        "finishReason": "completed",
        "status": "passedWithWarnings" if qc["verdict"] == "warn" else "passed",
        "layerCompleteness": "complete",
        "layers": ["engine"],
        "metrics": row_metrics(row, take),
        "output": output,
        "audioQC": qc,
        "thermalState": thermal_state(row),
        "warnings": list(qc["warningCodes"]),
        **identity,
        **quality_identity_fields(row),
    }
    if duration is not None:
        result["durationSeconds"] = duration
    return result


def apply_memory_qualification(
    takes: list[dict[str, Any]],
    qualified: Iterable[Any],
) -> None:
    by_id = {item.generation_id: item for item in qualified}
    if set(by_id) != {take.get("generationID") for take in takes}:
        raise PublicationError("memory-sidecar selection does not match the ordered benchmark takes")
    for take in takes:
        memory = by_id[str(take["generationID"])]
        take["metrics"].update(memory.metrics)
        take["sampleSidecarDigest"] = memory.sidecar_digest
        take["memoryStatus"] = memory.status
        take["warnings"] = sorted(set(take.get("warnings", [])).union(memory.warnings))
        take["status"] = "passedWithWarnings" if take["warnings"] else "passed"


def compact_memory_evidence(memory_run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: memory_run[key]
        for key in (
            "memoryContractVersion", "memoryQualified", "sampleSidecarCount",
            "sampleSidecarsDigest",
        )
    }


def memory_retention_evidence(
    results: dict[str, Any],
    takes: list[dict[str, Any]],
    platform: str,
) -> tuple[dict[str, Any], str]:
    if not MEMORY_POLICY_PATH.is_file():
        raise PublicationError(
            "memory qualification policy is missing: config/memory-qualification-policy.json"
        )
    policy = load_json(MEMORY_POLICY_PATH)
    required_policy = {
        "schemaVersion": 1,
        "policyID": "retained-memory-v1",
        "metric": "withinModeRetainedPhysicalFootprintGrowth",
        "modes": ["custom", "design", "clone"],
        "variant": "speed",
        "length": "medium",
        "repetitionsPerMode": 3,
        "seed": 19790615,
        "retentionThresholdFractionOfPhysicalMemory": 0.05,
        "expectedTakeCounts": {"macos": 11, "ios": 9},
    }
    if policy != required_policy:
        raise PublicationError("memory qualification policy differs from the retained-memory-v1 contract")
    declaration = results.get("memoryQualification")
    if not isinstance(declaration, dict) or declaration.get("policyID") != policy["policyID"]:
        raise PublicationError(
            "bench-results.json is missing memoryQualification.policyID=retained-memory-v1; "
            "run the benchmark with the memory-qualification option"
        )
    if results.get("seed") != policy["seed"]:
        raise PublicationError("memory qualification seed does not match the canonical policy")
    if len(takes) != policy["expectedTakeCounts"][platform]:
        raise PublicationError("memory qualification take count does not match the platform policy")
    expected_modes: list[str] = []
    expected_states: list[str] = []
    for mode in policy["modes"]:
        if platform == "macos" and mode != "clone":
            expected_modes.append(mode)
            expected_states.append("cold#0")
        expected_modes.extend([mode] * policy["repetitionsPerMode"])
        expected_states.extend(
            f"retained#{index}" for index in range(policy["repetitionsPerMode"])
        )
    observed_modes = [str(take.get("mode")) for take in takes]
    observed_states = [str(take.get("cell")).rsplit("/", 1)[-1] for take in takes]
    if observed_modes != expected_modes or observed_states != expected_states:
        raise PublicationError("memory qualification ordered matrix differs from canonical policy")
    for take in takes:
        if take.get("mode") not in policy["modes"]:
            raise PublicationError("memory qualification contains an unexpected mode")
        if take.get("variant") != policy["variant"] or take.get("length") != policy["length"]:
            raise PublicationError("memory qualification variant/length differs from policy")

    growth_by_mode: dict[str, float] = {}
    for mode in policy["modes"]:
        retained_takes = [
            take for take in takes
            if take.get("mode") == mode and "/retained#" in str(take.get("cell"))
        ]
        if len(retained_takes) != policy["repetitionsPerMode"]:
            raise PublicationError(
                f"memory qualification mode {mode} does not contain exactly three retained takes"
            )
        retained_ends = [
            finite_number(take["metrics"].get("physicalFootprintEndMB"))
            for take in retained_takes
        ]
        if any(value is None for value in retained_ends):
            raise PublicationError(f"memory qualification mode {mode} lacks post-trim footprint evidence")
        baseline = float(retained_ends[0])
        growth_by_mode[mode] = max(
            0.0,
            max(float(value) for value in retained_ends[1:]) - baseline,
        )
    maximum_growth_mb = max(growth_by_mode.values(), default=0.0)
    memory_mb = float(canonical_hardware_profile(platform)["memoryBytes"]) / 1_048_576.0
    growth_fraction = maximum_growth_mb / memory_mb
    threshold = float(policy["retentionThresholdFractionOfPhysicalMemory"])
    if growth_fraction > threshold:
        raise PublicationError(
            f"retained-memory growth {growth_fraction:.3%} exceeds policy threshold {threshold:.3%}"
        )
    return ({
        "memoryPolicyID": policy["policyID"],
        "retentionMetric": policy["metric"],
        "retentionThresholdFraction": threshold,
        "maximumRetainedGrowthMB": maximum_growth_mb,
        "maximumRetainedGrowthFraction": growth_fraction,
        "retentionPassed": True,
    }, digest_file(MEMORY_POLICY_PATH))


def minimal_take(index: int, cell: str, row: dict[str, Any]) -> dict[str, Any]:
    successful_row(row)
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    qc = qc_record(row)
    model_id = str(row.get("modelID", "not-applicable"))
    mode = str(row.get("mode", "not-applicable"))
    identity = runtime_identity(row, mode=mode, model_id=model_id)
    variant = "quality" if model_id.endswith("quality") else "speed"
    result = {
        "takeIndex": index,
        "generationID": str(row.get("generationID")),
        "cell": cell,
        "mode": mode,
        "modelID": model_id,
        "variant": variant,
        "warmState": str(row.get("warmState", notes.get("benchWarmState", "unknown"))),
        "length": "not-applicable",
        "finishReason": "completed",
        "status": "passedWithWarnings" if qc["verdict"] == "warn" else "passed",
        "layerCompleteness": "complete",
        "layers": ["engine"],
        "metrics": row_metrics(row),
        "output": telemetry_output(row),
        "audioQC": qc,
        "thermalState": thermal_state(row),
        "warnings": list(qc["warningCodes"]),
        **identity,
        **quality_identity_fields(row),
    }
    return result


def record_shell(
    *,
    kind: str,
    platform: str,
    run_id: str,
    label: str,
    started_at: str,
    finished_at: str,
    matrix_scope: str,
    artifact_dir: Path,
    snapshot: Path,
    takes: list[dict[str, Any]],
    raw_digest: str,
    telemetry_schema: int | str,
    qc_algorithm: int | str,
    inputs: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    executable_paths: dict[str, str] | None = None,
    optimization: str = "-Onone",
    classification: str | None = None,
    hardware: dict[str, Any] | None = None,
    hardware_evidence: Iterable[dict[str, Any]] | None = None,
    models: list[dict[str, Any]] | None = None,
    crash_delta: dict[str, Any] | None = None,
    memory_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_label = label or run_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", effective_label):
        raise PublicationError(
            "benchmark label must be an opaque 1-96 character identifier"
        )
    source = source_from_snapshot(snapshot)
    verified_hardware = verify_canonical_hardware(
        platform, ios_evidence=hardware_evidence
    )
    runtime_hardware = dict(hardware or {})
    supplied_profile = runtime_hardware.pop("profileID", None)
    if supplied_profile is not None and supplied_profile != verified_hardware["profileID"]:
        raise PublicationError("supplied hardware profile conflicts with live hardware evidence")
    warnings = sorted({warning for take in takes for warning in take.get("warnings", [])})
    status = "passedWithWarnings" if warnings else "passed"
    if crash_delta is None or crash_delta.get("passed") is not True:
        raise PublicationError("an observed crash-delta verdict is required before publication")
    evidence: dict[str, Any] = {
        "validatorSchemaVersion": 1,
        "telemetrySchemaVersion": telemetry_schema,
        "qcAlgorithmVersion": qc_algorithm,
        "validatorPassed": True,
        "crashDeltaPassed": True,
        "crashCount": int(crash_delta.get("count", 0)),
        "expectedTakeCount": len(takes),
        "actualTakeCount": len(takes),
        "resultBundleDigest": "not-applicable",
        "rawTelemetryDigest": raw_digest,
        "screenshotDigests": [],
    }
    if trace is not None:
        evidence["trace"] = trace
    if memory_evidence is not None:
        evidence.update(memory_evidence)
    history_record: dict[str, Any] = {
        # v3 when every take carries the phase-13 quality-registry identity;
        # v2 for pre-registry evidence. The outer evidence manifest below
        # keeps its own independent schema version.
        "schemaVersion": history_record_schema_version(takes),
        "run": {
            "id": run_id,
            "kind": kind,
            "platform": platform,
            "label": effective_label,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "status": status,
            "matrixScope": matrix_scope,
            "warnings": warnings,
            **({"classification": classification} if classification else {}),
        },
        "toolchain": {"optimization": optimization},
        "hardware": {
            **verified_hardware,
            **runtime_hardware,
        },
        "source": source,
        "inputs": inputs or {},
        "evidence": evidence,
        "takes": takes,
    }
    if models is not None:
        history_record["models"] = models
    outer: dict[str, Any] = {
        "schemaVersion": 2,
        "benchmarkKind": kind,
        "platform": platform,
        "runID": run_id,
        "status": status,
        "matrixScope": matrix_scope,
        "expectedTakeCount": len(takes),
        "actualTakeCount": len(takes),
        "telemetrySchemaVersion": telemetry_schema,
        "qcAlgorithmVersion": qc_algorithm,
        "crashDeltaPassed": True,
        "crashCount": int(crash_delta.get("count", 0)),
        "rawTelemetryDigest": raw_digest,
        "historyRecord": history_record,
    }
    outer["optimization"] = optimization
    if executable_paths is not None:
        outer["executableRelativePaths"] = executable_paths
    return outer


def write_and_record(
    artifact_dir: Path,
    manifest: dict[str, Any],
    *,
    defer_record: bool = False,
) -> Path:
    manifest_path = artifact_dir / "benchmark-evidence.json"
    atomic_json(manifest_path, manifest)
    if defer_record:
        return manifest_path
    completed = subprocess.run(
        [sys.executable, str(HISTORY_SCRIPT), "record", "--artifact-dir", str(artifact_dir)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown registry failure"
        repair = shlex.join([
            sys.executable,
            "scripts/benchmark_history.py",
            "record",
            "--artifact-dir",
            str(artifact_dir),
        ])
        raise PublicationError(f"history publication failed: {detail}\nrepair: {repair}")
    return manifest_path


def engine_command(args: argparse.Namespace, *, kind: str = "engine-generation", trace: dict[str, Any] | None = None) -> Path:
    results = load_json(args.results)
    if results.get("schemaVersion") != 1 or results.get("runID") != args.run_id:
        raise PublicationError("bench-results.json identity or schema does not match the requested run")
    result_takes = results.get("takes")
    if not isinstance(result_takes, list) or not result_takes:
        raise PublicationError("bench-results.json contains no takes")
    telemetry_mode = results.get("telemetryMode")
    streaming = results.get("streaming")
    seed = results.get("seed")
    if telemetry_mode not in {"lightweight", "verbose"} or not isinstance(streaming, bool):
        raise PublicationError("bench-results.json lacks exact telemetry/streaming configuration")
    if telemetry_mode != "verbose":
        raise PublicationError("memory-qualified benchmark publication requires telemetryMode=verbose")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
        raise PublicationError("bench-results.json has an invalid sampling seed")
    generation_ids: list[str] = []
    for index, take in enumerate(result_takes, start=1):
        if not isinstance(take, dict) or take.get("takeIndex") != index:
            raise PublicationError("bench-results take indices must be contiguous and one-based")
        generation_id = take.get("generationID")
        if not isinstance(generation_id, str) or not generation_id or generation_id.lower() in {item.lower() for item in generation_ids}:
            raise PublicationError("bench-results generation IDs must be unique non-empty strings")
        generation_ids.append(generation_id)
    selected = rows_by_generation(load_engine_rows(args.diagnostics), generation_ids)
    selected_app = (
        correlated_ios_app_rows(
            diagnostics=args.diagnostics,
            engine_rows=selected,
            takes=result_takes,
            run_id=args.run_id,
        )
        if args.platform == "ios" else []
    )
    takes = [
        engine_take(index, result_take, row, args.output_dir, run_id=args.run_id)
        for index, (result_take, row) in enumerate(zip(result_takes, selected), start=1)
    ]
    if selected_app:
        for take in takes:
            take["layers"] = ["engine", "app"]
    hardware_evidence = (
        ios_run_hardware_evidence(args.diagnostics, args.run_id)
        if args.platform == "ios" else None
    )
    try:
        qualified_memory, memory_run = qualify_memory_rows(
            rows=selected,
            diagnostics=args.diagnostics,
            platform=args.platform,
        )
    except MemoryEvidenceError as error:
        raise PublicationError(str(error)) from error
    apply_memory_qualification(takes, qualified_memory)
    retention_evidence: dict[str, Any] = {}
    memory_policy_digest = "not-applicable"
    if kind == "memory-qualification":
        retention_evidence, memory_policy_digest = memory_retention_evidence(
            results, takes, args.platform
        )
    delivery_takes = [take for take in result_takes if take.get("delivery")]
    prosody_path = args.diagnostics / "bench-prosody.json"
    prosody_rows: list[dict[str, Any]] = []
    analysis_profile_digest = "not-applicable"
    if delivery_takes:
        try:
            loaded = json.loads(prosody_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublicationError(f"delivery benchmark lacks valid prosody evidence: {error}") from error
        if not isinstance(loaded, list):
            raise PublicationError("bench-prosody.json must be an array")
        prosody_rows = [row for row in loaded if isinstance(row, dict)]
        profile_digests = {
            row.get("profileDigest") for row in prosody_rows
            if isinstance(row.get("profileDigest"), str)
        }
        if len(profile_digests) != 1:
            raise PublicationError("delivery prosody rows do not share one analysis profile")
        analysis_profile_digest = profile_digests.pop()
        if (
            len(analysis_profile_digest) != 64
            or any(character not in "0123456789abcdef" for character in analysis_profile_digest)
        ):
            raise PublicationError("delivery prosody analysis profile digest is invalid")
        fold_delivery_prosody(result_takes, takes, prosody_rows)
    telemetry_schema = max(
        int(row.get("schemaVersion", 0)) for row in [*selected, *selected_app]
    )
    qc_algorithm = max(int((row.get("audioQC") or {}).get("algorithmVersion", 1)) for row in selected)
    raw_digest_payload: dict[str, Any] = {
        "telemetry": selected,
        "prosody": prosody_rows,
        "sampleSidecars": memory_run["digestPayload"],
    }
    if selected_app:
        raw_digest_payload["appTelemetry"] = selected_app
    raw_digest = digest_bytes(canonical_bytes(raw_digest_payload))
    started_at = str(results.get("startedAt"))
    finished_at = str(results.get("finishedAt"))
    matrix_scope = "instrumented" if kind == "instrument-profile" else "focused"
    fixture_digests = results.get("fixtureDigests")
    if not isinstance(fixture_digests, dict):
        raise PublicationError("bench-results fixtureDigests must be an object")
    require_fixture_cross_check(takes, fixture_digests, source="bench-results")
    manifest = record_shell(
        kind=kind, platform=args.platform, run_id=args.run_id,
        label=str(results.get("label") or args.label or args.run_id),
        started_at=started_at, finished_at=finished_at, matrix_scope=matrix_scope,
        artifact_dir=args.artifact_dir, snapshot=args.snapshot, takes=takes,
        raw_digest=raw_digest, telemetry_schema=telemetry_schema,
        qc_algorithm=qc_algorithm, trace=trace,
        inputs={
            "corpusHash": prompt_corpus_digest(selected),
            "matrixHash": digest_bytes(canonical_bytes({
                "cells": [take.get("cell") for take in result_takes],
                "telemetryMode": telemetry_mode,
                "streaming": streaming,
                "seed": seed,
            })),
            "analysisProfileHash": (
                memory_policy_digest if kind == "memory-qualification"
                else analysis_profile_digest
            ),
        },
        hardware=hardware_context(selected),
        hardware_evidence=hardware_evidence,
        models=exact_models(args.platform, takes),
        crash_delta=crash_delta_from_snapshot(
            args.snapshot,
            expected_scope="macos" if args.platform == "macos" else "ios",
            diagnostics=args.diagnostics if args.platform == "ios" else None,
        ),
        executable_paths={"vocello": "build/vocello"} if args.platform == "macos" else {"Vocello": "build/cache/xcode/ios-device/Build/Products/Release-iphoneos/Vocello.app/Vocello"},
        optimization="-Onone",
        classification=(
            "instrumented" if kind == "instrument-profile"
            else "exploratory" if uses_forced_memory_profile(selected)
            else None
        ),
        memory_evidence={**compact_memory_evidence(memory_run), **retention_evidence},
    )
    return write_and_record(
        args.artifact_dir, manifest,
        defer_record=bool(getattr(args, "defer_record", False)),
    )


def ios_engine_command(
    args: argparse.Namespace,
    *,
    kind: str = "engine-generation",
    trace: dict[str, Any] | None = None,
) -> Path:
    sentinel = load_json(args.sentinel)
    if sentinel.get("runID") != args.run_id or sentinel.get("status") != "ok":
        raise PublicationError("iOS sentinel does not describe this successful run")
    generation_id = sentinel.get("generationID")
    if not isinstance(generation_id, str) or not generation_id:
        raise PublicationError("iOS sentinel has no generation ID")
    rows = rows_by_generation(load_engine_rows(args.diagnostics), [generation_id])
    row = rows[0]
    successful_row(row)
    mode = str(sentinel.get("mode"))
    model_id = str(row.get("modelID", sentinel.get("modelID", "not-applicable")))
    variant = str(sentinel.get("variant", "speed"))
    take_source = {
        "generationID": generation_id,
        "cell": f"{mode}/{variant}/device",
        "mode": mode,
        "modelID": model_id,
        "variant": variant,
        "warmState": str(row.get("warmState", "unknown")),
        "length": "not-applicable",
        "wallSeconds": sentinel.get("wallSeconds"),
        "audioSeconds": sentinel.get("durationSeconds"),
    }
    selected_app = correlated_ios_app_rows(
        diagnostics=args.diagnostics,
        engine_rows=rows,
        takes=[take_source],
        run_id=args.run_id,
    )
    take = engine_take(1, take_source, row, None, run_id=args.run_id)
    take["layers"] = ["engine", "app"]
    try:
        qualified_memory, memory_run = qualify_memory_rows(
            rows=rows,
            diagnostics=args.diagnostics,
            platform="ios",
        )
    except MemoryEvidenceError as error:
        raise PublicationError(str(error)) from error
    apply_memory_qualification([take], qualified_memory)
    fixture_digest = sentinel.get("fixtureDigest")
    require_fixture_cross_check(
        [take],
        {mode: fixture_digest} if isinstance(fixture_digest, str) else {},
        source="iOS sentinel",
    )
    manifest = record_shell(
        kind=kind, platform="ios", run_id=args.run_id,
        label=args.label or args.run_id,
        started_at=str(sentinel.get("startedAt")), finished_at=str(sentinel.get("finishedAt")),
        matrix_scope="instrumented" if kind == "instrument-profile" else "focused",
        artifact_dir=args.artifact_dir, snapshot=args.snapshot,
        takes=[take], raw_digest=digest_bytes(canonical_bytes({
            "telemetry": rows,
            "appTelemetry": selected_app,
            "sampleSidecars": memory_run["digestPayload"],
        })),
        telemetry_schema=max(
            int(candidate.get("schemaVersion", 0)) for candidate in [*rows, *selected_app]
        ),
        qc_algorithm=int((row.get("audioQC") or {}).get("algorithmVersion", 1)),
        inputs={"corpusHash": prompt_corpus_digest(rows)},
        trace=trace,
        hardware=hardware_context(rows),
        hardware_evidence=[sentinel],
        models=exact_models("ios", [take]),
        crash_delta=crash_delta_from_snapshot(
            args.snapshot, expected_scope="ios", diagnostics=args.diagnostics
            if getattr(args, "crash_diagnostics", None) is None else args.crash_diagnostics
        ),
        executable_paths={"Vocello": "build/cache/xcode/ios-device/Build/Products/Release-iphoneos/Vocello.app/Vocello"},
        optimization="-Onone",
        classification=(
            "instrumented" if kind == "instrument-profile"
            else "exploratory" if uses_forced_memory_profile(rows)
            else None
        ),
        memory_evidence=compact_memory_evidence(memory_run),
    )
    return write_and_record(
        args.artifact_dir, manifest,
        defer_record=bool(getattr(args, "defer_record", False)),
    )


def selected_language_cells(matrix_path: Path, subset: str) -> list[dict[str, Any]]:
    matrix = load_json(matrix_path)
    cells = matrix.get("cells")
    if not isinstance(cells, list):
        raise PublicationError("language matrix has no cells")
    selected = cells if subset == "full" else [cell for cell in cells if cell.get("quick")]
    if not selected:
        raise PublicationError("language matrix selection is empty")
    return selected


def language_corpus_scripts(corpus_path: Path) -> dict[str, str]:
    payload = load_json(corpus_path)
    languages = payload.get("languages")
    if not isinstance(languages, list) or not languages:
        raise PublicationError("language corpus has no scripts")
    scripts: dict[str, str] = {}
    for entry in languages:
        if not isinstance(entry, dict):
            raise PublicationError("language corpus contains a malformed script")
        language_id = entry.get("id")
        script = entry.get("script")
        if (
            not isinstance(language_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", language_id) is None
            or not isinstance(script, str)
            or not script.strip()
            or language_id in scripts
        ):
            raise PublicationError("language corpus contains an invalid or duplicate script")
        scripts[language_id] = script
    return scripts


def language_corpus_fixtures(corpus_path: Path) -> dict[str, dict[str, str]]:
    payload = load_json(corpus_path)
    languages = payload.get("languages")
    if not isinstance(languages, list) or not languages:
        raise PublicationError("language corpus has no mode fixtures")
    fixtures: dict[str, dict[str, str]] = {}
    for entry in languages:
        if not isinstance(entry, dict):
            raise PublicationError("language corpus contains a malformed mode fixture")
        language_id = entry.get("id")
        speaker_id = entry.get("customSpeakerID")
        design_instruction = entry.get("designInstruction")
        if (
            not isinstance(language_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", language_id) is None
            or language_id in fixtures
            or not isinstance(speaker_id, str)
            or SAFE_CUSTOM_SPEAKER.fullmatch(speaker_id) is None
            or not isinstance(design_instruction, str)
            or not design_instruction
            or design_instruction != design_instruction.strip()
            or len(design_instruction) > 240
        ):
            raise PublicationError("language corpus contains an invalid or duplicate mode fixture")
        fixtures[language_id] = {
            "customSpeakerID": speaker_id,
            "designInstruction": design_instruction,
            "designInstructionDigest": digest_bytes(design_instruction.encode("utf-8")),
        }
    return fixtures


def locale_matches_expected_language(identifier: str, expected_language: str) -> bool:
    expected_code = LANGUAGE_LOCALE_CODES.get(expected_language)
    if expected_code is None:
        return False
    return re.split(r"[-_]", identifier, maxsplit=1)[0].lower() == expected_code


def normalized_language_word_tokens(
    text: str, *, preserve_diacritics: bool = False
) -> list[str]:
    """Mirror Swift's language-aware POSIX lowercasing and tokenization."""
    if preserve_diacritics:
        folded = unicodedata.normalize("NFKC", text)
    else:
        folded = unicodedata.normalize("NFKD", text)
        folded = "".join(
            character for character in folded
            if unicodedata.category(character) != "Mn"
        )
    folded = folded.lower()
    tokens: list[str] = []
    current: list[str] = []
    for character in folded:
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def language_edit_metrics(
    reference: str,
    hypothesis: str,
    *,
    characters: bool,
    expected_language: str,
) -> dict[str, Any]:
    preserve_diacritics = characters and expected_language in {"chinese", "japanese"}
    lhs_words = normalized_language_word_tokens(
        reference, preserve_diacritics=preserve_diacritics
    )
    rhs_words = normalized_language_word_tokens(
        hypothesis, preserve_diacritics=preserve_diacritics
    )
    lhs: list[Any] = list("".join(lhs_words)) if characters else lhs_words
    rhs: list[Any] = list("".join(rhs_words)) if characters else rhs_words
    # Stable tie policy matches VoiceClipTranscriber: diagonal, deletion, insertion.
    previous = [(0, index, 0) for index in range(len(rhs) + 1)]
    for left_index, left in enumerate(lhs):
        current = [(0, 0, left_index + 1)]
        for right_index, right in enumerate(rhs):
            diagonal = list(previous[right_index])
            if left != right:
                diagonal[0] += 1
            deletion = list(previous[right_index + 1])
            deletion[2] += 1
            insertion = list(current[right_index])
            insertion[1] += 1
            candidates = (tuple(diagonal), tuple(deletion), tuple(insertion))
            best = candidates[0]
            for candidate in candidates[1:]:
                if sum(candidate) < sum(best):
                    best = candidate
            current.append(best)
        previous = current
    substitutions, insertions, deletions = previous[len(rhs)]
    distance = substitutions + insertions + deletions
    error_rate = (distance / len(lhs)) if lhs else (0.0 if not rhs else 1.0)
    return {
        "referenceCount": len(lhs),
        "hypothesisCount": len(rhs),
        "substitutions": substitutions,
        "insertions": insertions,
        "deletions": deletions,
        "errorRate": error_rate,
    }


def uint64_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= UINT64_MAX:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
        return parsed if parsed <= UINT64_MAX else None
    return None


def load_language_plan(
    args: argparse.Namespace,
    cells: list[dict[str, Any]],
) -> dict[str, Any] | None:
    plan_path = getattr(args, "plan", None)
    if args.platform == "ios" and plan_path is None:
        raise PublicationError("iOS language publication requires the immutable run plan")
    if plan_path is None:
        return None
    plan = load_json(Path(plan_path))
    unsigned = dict(plan)
    plan_digest = unsigned.pop("planDigest", None)
    if (
        plan.get("schemaVersion") != 1
        or plan.get("kind") != "languageBenchmark"
        or plan.get("runID") != args.run_id
        or not isinstance(plan_digest, str)
        or plan_digest != digest_bytes(canonical_bytes(unsigned))
    ):
        raise PublicationError("language run plan identity or digest is invalid")
    if plan.get("matrixDigest") != digest_file(args.matrix):
        raise PublicationError("language run plan matrix digest does not match")
    if plan.get("corpusDigest") != digest_file(args.corpus):
        raise PublicationError("language run plan corpus digest does not match")
    if plan.get("subset") != args.subset or plan.get("requireEveryTakePass") is not True:
        raise PublicationError("language run plan scope or success policy does not match")
    if plan.get("seedPolicy") != LANGUAGE_SEED_POLICY:
        raise PublicationError("language run plan seed policy does not match the tracked contract")
    if plan.get("samplingVariation") != LANGUAGE_SAMPLING_VARIATION:
        raise PublicationError(
            "language run plan sampling variation does not match the tracked contract"
        )
    if plan.get("cohortID") is not None or plan.get("cohortDigest") is not None:
        raise PublicationError("diagnostic language cohorts are intentionally unpublished")
    takes = plan.get("takes")
    if not isinstance(takes, list) or len(takes) != len(cells) or plan.get("takeCount") != len(cells):
        raise PublicationError("language run plan must contain exactly one take per selected cell")
    expected_ids = [str(cell.get("id")) for cell in cells]
    if [take.get("cellID") if isinstance(take, dict) else None for take in takes] != expected_ids:
        raise PublicationError("language run plan cell ordering does not match the matrix")
    seen_children: set[str] = set()
    group_counts: dict[str, int] = {}
    corpus_fixtures = language_corpus_fixtures(args.corpus)
    for index, (take, cell) in enumerate(zip(takes, cells), start=1):
        if not isinstance(take, dict) or take.get("takeIndex") != index:
            raise PublicationError("language run plan take indexes must be one-based and ordered")
        child = take.get("childRunID")
        if (
            not isinstance(child, str)
            or child != f"{args.run_id}--{cell['id']}"
            or child in seen_children
        ):
            raise PublicationError("language run plan contains an invalid child run identity")
        seen_children.add(child)
        seed = uint64_value(take.get("seed"))
        if seed is None or seed != take.get("seed"):
            raise PublicationError(f"language cell {cell['id']} has an invalid planned seed")
        if take.get("seedIndex") is not None or seed != stable_default_seed(cell):
            raise PublicationError(
                f"language cell {cell['id']} does not use its deterministic tracked seed"
            )
        variation = take.get("samplingVariation")
        if variation != LANGUAGE_SAMPLING_VARIATION:
            raise PublicationError(
                f"language cell {cell['id']} must use expressive sampling variation"
            )
        if (
            take.get("mode") != cell.get("mode")
            or take.get("variant", "speed") != cell.get("variant", "speed")
            or take.get("uiHint", "auto") != cell.get("uiHint", "auto")
            or take.get("scriptLang") != cell.get("scriptLang")
            or take.get("expectedHint") != cell.get("expectedHint")
            or bool(take.get("skipOutputVerification"))
            != bool(cell.get("skipOutputVerification"))
            or take.get("promptEquivalenceGroup") != cell.get("promptEquivalenceGroup")
        ):
            raise PublicationError(f"language cell {cell['id']} plan identity does not match the matrix")
        fixture = corpus_fixtures.get(str(cell.get("scriptLang")))
        if fixture is None:
            raise PublicationError(
                f"language cell {cell['id']} has no corpus-owned mode fixture"
            )
        if take.get("mode") == "custom":
            fixture_matches = (
                take.get("customSpeakerID") == fixture["customSpeakerID"]
                and take.get("designInstruction") is None
                and take.get("designInstructionDigest") is None
            )
        elif take.get("mode") == "design":
            fixture_matches = (
                take.get("customSpeakerID") is None
                and take.get("designInstruction") == fixture["designInstruction"]
                and take.get("designInstructionDigest")
                == fixture["designInstructionDigest"]
            )
        else:
            fixture_matches = False
        if not fixture_matches:
            raise PublicationError(
                f"language cell {cell['id']} mode fixture does not match the corpus"
            )
        group = take.get("promptEquivalenceGroup")
        if group is not None:
            if not isinstance(group, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", group) is None:
                raise PublicationError(f"language cell {cell['id']} has an invalid prompt group")
            group_counts[group] = group_counts.get(group, 0) + 1
        matrix_seed = cell.get("seed")
        if matrix_seed is not None and seed != uint64_value(matrix_seed):
            raise PublicationError(f"language cell {cell['id']} plan seed does not match the matrix")
        matrix_variation = cell.get("samplingVariation")
        if matrix_variation is not None and variation != matrix_variation:
            raise PublicationError(
                f"language cell {cell['id']} plan variation does not match the matrix"
            )
    expected_groups = sorted(group_counts)
    if plan.get("promptEquivalenceGroups") != expected_groups:
        raise PublicationError("language run plan prompt-equivalence groups do not match the matrix")
    if any(count < 2 for count in group_counts.values()):
        raise PublicationError("language run plan prompt-equivalence groups require paired cells")
    return plan


def validate_language_sampling_identity(
    *,
    cell_id: str,
    planned_take: dict[str, Any],
    sentinel: dict[str, Any],
    engine_row: dict[str, Any],
) -> int:
    if sentinel.get("schemaVersion") != LANGUAGE_SENTINEL_SCHEMA:
        raise PublicationError(f"language cell {cell_id} lacks sentinel schema v2 evidence")
    seed = uint64_value(planned_take.get("seed"))
    notes = engine_row.get("notes") if isinstance(engine_row.get("notes"), dict) else {}
    if seed is None or uint64_value(sentinel.get("seed")) != seed:
        raise PublicationError(f"language cell {cell_id} sentinel seed does not match the plan")
    if uint64_value(notes.get("samplingSeed")) != seed:
        raise PublicationError(f"language cell {cell_id} engine seed does not match the plan")
    variation = planned_take.get("samplingVariation")
    if sentinel.get("samplingVariation") != variation:
        raise PublicationError(f"language cell {cell_id} sentinel variation does not match the plan")
    if notes.get("samplingVariation") != variation:
        raise PublicationError(f"language cell {cell_id} engine variation does not match the plan")
    requested_hint = planned_take.get("uiHint", "auto")
    expected_source = "auto" if requested_hint == "auto" else "explicit"
    if sentinel.get("requestedLanguageHint") != requested_hint:
        raise PublicationError(f"language cell {cell_id} requested hint does not match the plan")
    if sentinel.get("languageHintSource") != expected_source:
        raise PublicationError(f"language cell {cell_id} hint source does not match the plan")
    return seed


def validate_language_mode_fixture_identity(
    *,
    cell_id: str,
    planned_take: dict[str, Any],
    sentinel: dict[str, Any],
) -> None:
    """Bind the actual privacy-safe mode fixture to the immutable run plan."""
    mode = planned_take.get("mode")
    if mode == "custom":
        speaker_id = planned_take.get("customSpeakerID")
        if (
            not isinstance(speaker_id, str)
            or SAFE_CUSTOM_SPEAKER.fullmatch(speaker_id) is None
            or planned_take.get("designInstruction") is not None
            or planned_take.get("designInstructionDigest") is not None
        ):
            raise PublicationError(f"language cell {cell_id} has an invalid planned Custom fixture")
        if sentinel.get("customSpeakerID") != speaker_id:
            raise PublicationError(
                f"language cell {cell_id} Custom speaker does not match the plan"
            )
        if sentinel.get("fixtureDigest") is not None:
            raise PublicationError(
                f"language cell {cell_id} Custom sentinel has an unexpected fixture digest"
            )
        return
    if mode == "design":
        instruction = planned_take.get("designInstruction")
        instruction_digest = planned_take.get("designInstructionDigest")
        if (
            planned_take.get("customSpeakerID") is not None
            or not isinstance(instruction, str)
            or not instruction
            or instruction != instruction.strip()
            or len(instruction) > 240
            or not isinstance(instruction_digest, str)
            or SAFE_DIGEST.fullmatch(instruction_digest) is None
            or digest_bytes(instruction.encode("utf-8")) != instruction_digest
        ):
            raise PublicationError(f"language cell {cell_id} has an invalid planned Design fixture")
        if sentinel.get("customSpeakerID") is not None:
            raise PublicationError(
                f"language cell {cell_id} Design sentinel has an unexpected Custom speaker"
            )
        if sentinel.get("fixtureDigest") != instruction_digest:
            raise PublicationError(
                f"language cell {cell_id} Design fixture digest does not match the plan"
            )
        return
    raise PublicationError(f"language cell {cell_id} has an unsupported planned mode fixture")


def validate_prompt_equivalence(
    *,
    planned_takes: list[dict[str, Any]],
    sentinels: dict[str, dict[str, Any]],
    rows_by_cell: dict[str, dict[str, Any]],
) -> None:
    grouped: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for take in planned_takes:
        group = take.get("promptEquivalenceGroup")
        if not isinstance(group, str):
            continue
        cell_id = str(take["cellID"])
        sentinel = sentinels[cell_id]
        digest = sentinel.get("resolvedPromptAssemblyDigest")
        if (
            sentinel.get("promptDigestScope") != "resolved"
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise PublicationError(f"language cell {cell_id} lacks a resolved prompt digest")
        notes = rows_by_cell[cell_id].get("notes")
        engine_digest = notes.get("resolvedPromptAssemblyDigest") if isinstance(notes, dict) else None
        if engine_digest is not None and engine_digest != digest:
            raise PublicationError(f"language cell {cell_id} prompt digest disagrees across layers")
        seed = uint64_value(take.get("seed"))
        if seed is None:
            raise PublicationError(f"language cell {cell_id} prompt group lacks a seed")
        grouped.setdefault((group, seed), []).append((cell_id, digest))
    for (group, seed), members in grouped.items():
        if len(members) < 2 or len({digest for _, digest in members}) != 1:
            raise PublicationError(
                f"language prompt-equivalence group {group} seed {seed} is inconsistent"
            )


def sanitized_asr_evidence(
    *,
    cell: dict[str, Any],
    planned_take: dict[str, Any],
    sentinel: dict[str, Any],
    engine_row: dict[str, Any],
    parent_run_id: str,
    reference_script: str,
) -> dict[str, Any]:
    """Return the bounded, non-transcript ASR proof bound to one engine row."""
    cell_id = str(cell.get("id"))
    expected_child_run = planned_take.get("childRunID")
    if expected_child_run != f"{parent_run_id}--{cell_id}":
        raise PublicationError(f"language cell {cell_id} has invalid planned child identity")
    if sentinel.get("runID") != expected_child_run:
        raise PublicationError(f"language cell {cell_id} has the wrong child run ID")
    if sentinel.get("generationID") != engine_row.get("generationID"):
        raise PublicationError(f"language cell {cell_id} ASR evidence belongs to another generation")
    validate_language_sampling_identity(
        cell_id=cell_id,
        planned_take=planned_take,
        sentinel=sentinel,
        engine_row=engine_row,
    )
    verification = sentinel.get("outputVerification")
    if not isinstance(verification, dict):
        raise PublicationError(f"language cell {cell_id} lacks output-verification evidence")
    if (
        verification.get("schemaVersion") != LANGUAGE_OUTPUT_SCHEMA
        or verification.get("algorithmVersion") != LANGUAGE_OUTPUT_ALGORITHM
    ):
        raise PublicationError(f"language cell {cell_id} has unsupported output-verifier evidence")
    expected_language = cell.get("expectedHint")
    if verification.get("expectedLanguage") != expected_language:
        raise PublicationError(f"language cell {cell_id} has the wrong expected ASR language")
    detected_language = verification.get("detectedLanguage")
    if not isinstance(detected_language, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", detected_language):
        raise PublicationError(f"language cell {cell_id} has invalid detected-language evidence")
    language_score = finite_number(verification.get("languageMatchScore"))
    word_error_rate = finite_number(verification.get("wordErrorRate"))
    character_error_rate = finite_number(verification.get("characterErrorRate"))
    count_fields: dict[str, int] = {}
    for key in (
        "referenceTokenCount", "hypothesisTokenCount", "referenceCharacterCount",
        "hypothesisCharacterCount", "substitutions", "insertions", "deletions",
        "characterSubstitutions", "characterInsertions", "characterDeletions",
    ):
        value = verification.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PublicationError(f"language cell {cell_id} has invalid {key}")
        count_fields[key] = value
    boolean_fields = {
        key: verification.get(key) for key in ("languagePass", "accuracyPass", "pass")
    }
    if (
        language_score is None or not 0.0 <= language_score <= 1.0
        or language_score < LANGUAGE_PASS_SCORE
        or word_error_rate is None or word_error_rate < 0.0
        or character_error_rate is None or character_error_rate < 0.0
        or count_fields["referenceTokenCount"] <= 0
        or count_fields["referenceCharacterCount"] <= 0
    ):
        raise PublicationError(f"language cell {cell_id} has non-finite ASR scores")
    if any(not isinstance(value, bool) for value in boolean_fields.values()):
        raise PublicationError(f"language cell {cell_id} has malformed ASR verdicts")
    if verification.get("skipReason") is not None or not all(boolean_fields.values()):
        raise PublicationError(f"language cell {cell_id} failed output verification")
    edit_count = sum(count_fields[key] for key in ("substitutions", "insertions", "deletions"))
    if not math.isclose(
        word_error_rate,
        edit_count / count_fields["referenceTokenCount"],
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise PublicationError(f"language cell {cell_id} WER does not match its edit counts")

    recognition = verification.get("recognition")
    if not isinstance(recognition, dict) or (
        recognition.get("schemaVersion") != ASR_EVIDENCE_SCHEMA
        or recognition.get("algorithmVersion") != ASR_EVIDENCE_ALGORITHM
    ):
        raise PublicationError(f"language cell {cell_id} has unsupported recognition evidence")
    locale = recognition.get("selectedLocaleIdentifier")
    if not isinstance(locale, str) or SAFE_LOCALE.fullmatch(locale) is None:
        raise PublicationError(f"language cell {cell_id} has invalid locale evidence")
    if not locale_matches_expected_language(locale, str(expected_language)):
        raise PublicationError(
            f"language cell {cell_id} locale does not match expected language"
        )
    if (
        recognition.get("expectedLanguage") != expected_language
        or recognition.get("authorizationStatus") != "authorized"
        or recognition.get("recognizerAvailable") is not True
        or recognition.get("supportsOnDeviceRecognition") is not True
        or recognition.get("requiredPassCount") != ASR_REQUIRED_PASS_COUNT
        or recognition.get("evidenceConsistency") is not True
        or recognition.get("consensusStatus") != "consistent"
    ):
        raise PublicationError(f"language cell {cell_id} failed the on-device consensus contract")
    recognition_duration = finite_number(recognition.get("recognitionDurationSeconds"))
    repetitions = recognition.get("repetitions")
    if recognition_duration is None or recognition_duration <= 0 or not isinstance(repetitions, list):
        raise PublicationError(f"language cell {cell_id} has malformed recognition timing")
    if len(repetitions) != ASR_REQUIRED_PASS_COUNT:
        raise PublicationError(f"language cell {cell_id} lacks exactly three recognition passes")
    transcripts: list[str] = []
    pass_duration = 0.0
    for index, repetition in enumerate(repetitions, start=1):
        if not isinstance(repetition, dict):
            raise PublicationError(f"language cell {cell_id} has malformed recognition passes")
        duration = finite_number(repetition.get("recognitionDurationSeconds"))
        segment_start = finite_number(repetition.get("segmentStartSeconds"))
        segment_end = finite_number(repetition.get("segmentEndSeconds"))
        timing_coverage = finite_number(repetition.get("timingCoverageSeconds"))
        average_confidence = finite_number(repetition.get("averageConfidence"))
        minimum_confidence = finite_number(repetition.get("minimumConfidence"))
        transcript = repetition.get("transcript")
        if (
            repetition.get("passIndex") != index
            or repetition.get("localeIdentifier") != locale
            or repetition.get("authorizationStatus") != "authorized"
            or repetition.get("recognizerAvailable") is not True
            or repetition.get("supportsOnDeviceRecognition") is not True
            or repetition.get("finalResultStatus") != "finalResult"
            or duration is None or duration <= 0
            or not isinstance(transcript, str) or not transcript.strip() or transcript != transcript.strip()
            or isinstance(repetition.get("segmentCount"), bool)
            or not isinstance(repetition.get("segmentCount"), int)
            or repetition.get("segmentCount") <= 0
            or segment_start is None or segment_start < 0
            or segment_end is None or segment_end <= segment_start
            or timing_coverage is None or timing_coverage <= 0
            or not math.isclose(
                timing_coverage, segment_end - segment_start, rel_tol=1e-9, abs_tol=1e-9
            )
            or average_confidence is None or not 0 <= average_confidence <= 1
            or minimum_confidence is None or not 0 <= minimum_confidence <= 1
            or minimum_confidence > average_confidence
            or repetition.get("errorDomain") is not None
            or repetition.get("errorCode") is not None
        ):
            raise PublicationError(f"language cell {cell_id} recognition pass {index} is invalid")
        pass_duration += duration
        transcripts.append(transcript)
    if (
        len(set(transcripts)) != 1
        or recognition.get("transcript") != transcripts[0]
        or verification.get("transcript") != transcripts[0]
        or not math.isclose(recognition_duration, pass_duration, rel_tol=1e-9, abs_tol=1e-9)
    ):
        raise PublicationError(f"language cell {cell_id} recognition consensus is inconsistent")
    word_metrics = language_edit_metrics(
        reference_script,
        transcripts[0],
        characters=False,
        expected_language=str(expected_language),
    )
    character_metrics = language_edit_metrics(
        reference_script,
        transcripts[0],
        characters=True,
        expected_language=str(expected_language),
    )
    recomputed_fields = {
        "referenceTokenCount": word_metrics["referenceCount"],
        "hypothesisTokenCount": word_metrics["hypothesisCount"],
        "referenceCharacterCount": character_metrics["referenceCount"],
        "hypothesisCharacterCount": character_metrics["hypothesisCount"],
        "substitutions": word_metrics["substitutions"],
        "insertions": word_metrics["insertions"],
        "deletions": word_metrics["deletions"],
        "characterSubstitutions": character_metrics["substitutions"],
        "characterInsertions": character_metrics["insertions"],
        "characterDeletions": character_metrics["deletions"],
    }
    if count_fields != recomputed_fields or not math.isclose(
        word_error_rate, word_metrics["errorRate"], rel_tol=1e-9, abs_tol=1e-12
    ) or not math.isclose(
        character_error_rate, character_metrics["errorRate"], rel_tol=1e-9, abs_tol=1e-12
    ):
        raise PublicationError(f"language cell {cell_id} metrics do not match corpus and consensus")
    expected_accuracy_metric = (
        "characterErrorRate"
        if expected_language in {"chinese", "japanese"}
        else "wordErrorRate"
    )
    accuracy_metric = verification.get("accuracyMetric")
    accuracy_threshold = finite_number(verification.get("accuracyThreshold"))
    accuracy_value = finite_number(verification.get("accuracyValue"))
    expected_threshold = LANGUAGE_ACCURACY_THRESHOLDS[expected_accuracy_metric]
    primary_score = (
        character_error_rate if expected_accuracy_metric == "characterErrorRate" else word_error_rate
    )
    if (
        verification.get("accuracyMetricVersion") != LANGUAGE_ACCURACY_METRIC_VERSION
        or accuracy_metric != expected_accuracy_metric
        or accuracy_threshold is None
        or not math.isclose(accuracy_threshold, expected_threshold, rel_tol=0, abs_tol=1e-12)
        or accuracy_value is None
        or not math.isclose(accuracy_value, primary_score, rel_tol=1e-9, abs_tol=1e-12)
        or verification.get("accuracyPass") != (primary_score <= expected_threshold)
        or primary_score > expected_threshold
    ):
        raise PublicationError(f"language cell {cell_id} has an invalid primary accuracy gate")
    return {
        "cell": cell_id,
        "generationID": str(engine_row.get("generationID")),
        "expectedLanguage": str(expected_language),
        "detectedLanguage": detected_language,
        "selectedLocaleIdentifier": locale,
        "outputVerifierSchemaVersion": LANGUAGE_OUTPUT_SCHEMA,
        "outputVerifierAlgorithm": LANGUAGE_OUTPUT_ALGORITHM,
        "recognitionSchemaVersion": ASR_EVIDENCE_SCHEMA,
        "recognitionAlgorithm": ASR_EVIDENCE_ALGORITHM,
        "recognitionPassCount": ASR_REQUIRED_PASS_COUNT,
        "recognitionDurationSeconds": recognition_duration,
        "authorizationVerified": True,
        "recognizerAvailable": True,
        "onDeviceRecognition": True,
        "consensusStatus": "consistent",
        "evidenceConsistency": True,
        "languageMatchScore": language_score,
        "wordErrorRate": word_error_rate,
        "characterErrorRate": character_error_rate,
        "accuracyMetric": expected_accuracy_metric,
        "accuracyMetricVersion": LANGUAGE_ACCURACY_METRIC_VERSION,
        "accuracyThreshold": expected_threshold,
        "primaryAccuracyScore": primary_score,
        **count_fields,
        **boolean_fields,
    }


def language_output_evidence(
    sentinel: dict[str, Any], output_path: Path, cell_id: str
) -> dict[str, Any]:
    output = sentinel.get("outputEvidence")
    if not isinstance(output, dict) or output.get("artifactRelativePath") != "output.wav":
        raise PublicationError(f"language cell {cell_id} lacks bounded output evidence")
    digest = output.get("sha256")
    byte_count = output.get("byteCount")
    duration = finite_number(output.get("durationSeconds"))
    sample_rate = finite_number(output.get("sampleRate"))
    channels = output.get("channelCount")
    frames = output.get("frameCount")
    try:
        stat = output_path.stat()
        with wave.open(str(output_path), "rb") as stream:
            actual_sample_rate = stream.getframerate()
            actual_channels = stream.getnchannels()
            actual_frames = stream.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise PublicationError(f"language cell {cell_id} output.wav is unreadable: {error}") from error
    actual_duration = actual_frames / actual_sample_rate if actual_sample_rate > 0 else 0.0
    if (
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count <= 0
        or duration is None or duration <= 0
        or sample_rate is None or sample_rate <= 0 or not sample_rate.is_integer()
        or isinstance(channels, bool) or not isinstance(channels, int) or channels <= 0
        or isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0
        or not math.isclose(duration, frames / sample_rate, rel_tol=1e-6, abs_tol=1e-6)
        or stat.st_size != byte_count
        or digest_file(output_path) != digest
        or actual_sample_rate != int(sample_rate)
        or actual_channels != channels
        or actual_frames != frames
        or not math.isclose(actual_duration, duration, rel_tol=1e-6, abs_tol=1e-6)
    ):
        raise PublicationError(f"language cell {cell_id} has invalid output metadata")
    return {
        "readableWAV": True,
        "atomicPublish": True,
        "durationSeconds": duration,
        "sampleRate": int(sample_rate),
        "channels": channels,
        "frames": frames,
        "fileDigest": digest,
    }


def language_command(args: argparse.Namespace) -> Path:
    cells = selected_language_cells(args.matrix, args.subset)
    output_verified = args.output_gate == "pass"
    corpus_scripts = language_corpus_scripts(args.corpus) if output_verified else {}
    if output_verified:
        missing_scripts = sorted({
            str(cell.get("scriptLang")) for cell in cells
            if not cell.get("skipOutputVerification")
            and str(cell.get("scriptLang")) not in corpus_scripts
        })
        if missing_scripts:
            raise PublicationError(
                "language corpus is missing selected scripts: " + ", ".join(missing_scripts)
            )
    expected_ids = [str(cell.get("id")) for cell in cells]
    plan = load_language_plan(args, cells)
    planned_takes = plan.get("takes") if isinstance(plan, dict) else None
    rows = [
        row for row in load_engine_rows(args.diagnostics)
        if (row.get("notes") or {}).get("benchRunID") == args.run_id
    ]
    selected: list[dict[str, Any]] = []
    selected_app: list[dict[str, Any]] = []
    sentinels: dict[str, dict[str, Any]] = {}
    selected_sentinel_paths: dict[str, Path] = {}
    if planned_takes is not None:
        by_generation: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_generation.setdefault(str(row.get("generationID")), []).append(row)
        app_rows = [
            row for row in load_app_rows(args.diagnostics)
            if (row.get("notes") or {}).get("benchRunID") == args.run_id
        ] if args.platform == "ios" else []
        app_by_generation: dict[str, list[dict[str, Any]]] = {}
        for row in app_rows:
            app_by_generation.setdefault(str(row.get("generationID")), []).append(row)
        expected_children = {str(take["childRunID"]) for take in planned_takes}
        sentinel_paths: dict[str, list[Path]] = {child: [] for child in expected_children}
        unexpected_children: set[str] = set()
        prefix = f"{args.run_id}--"
        for path in args.diagnostics.rglob("device-diagnostics-done.json"):
            child = path.parent.name
            if child in sentinel_paths:
                sentinel_paths[child].append(path)
            elif child.startswith(prefix):
                unexpected_children.add(child)
        if unexpected_children:
            raise PublicationError(
                "language run has unexpected sentinels: " + ", ".join(sorted(unexpected_children))
            )
        selected_generations: set[str] = set()
        for cell, planned_take in zip(cells, planned_takes):
            cell_id = str(cell["id"])
            child = str(planned_take["childRunID"])
            paths = sentinel_paths[child]
            if len(paths) != 1:
                raise PublicationError(
                    f"language cell {cell_id} has {len(paths)} exact sentinels; expected one"
                )
            sentinel = load_json(paths[0])
            generation_id = sentinel.get("generationID")
            if sentinel.get("runID") != child or not isinstance(generation_id, str):
                raise PublicationError(f"language cell {cell_id} sentinel identity is invalid")
            if generation_id in selected_generations:
                raise PublicationError("language run reuses one generation across multiple cells")
            matches = by_generation.get(generation_id, [])
            if len(matches) != 1:
                raise PublicationError(
                    f"language cell {cell_id} generation has {len(matches)} rows; expected one"
                )
            row = matches[0]
            notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
            if notes.get("benchCell") != cell_id or row.get("mode") != planned_take.get("mode"):
                raise PublicationError(f"language cell {cell_id} telemetry identity is invalid")
            expected_hint = str(cell.get("expectedHint"))
            if notes.get("languageHint") != expected_hint:
                raise PublicationError(f"language cell {cell_id} has the wrong resolved hint")
            if sentinel.get("status") != "ok":
                raise PublicationError(f"language cell {cell_id} sentinel did not complete")
            successful_row(row)
            validate_language_sampling_identity(
                cell_id=cell_id,
                planned_take=planned_take,
                sentinel=sentinel,
                engine_row=row,
            )
            validate_language_mode_fixture_identity(
                cell_id=cell_id,
                planned_take=planned_take,
                sentinel=sentinel,
            )
            if args.platform == "ios":
                app_matches = app_by_generation.get(generation_id, [])
                if len(app_matches) != 1:
                    raise PublicationError(
                        f"language cell {cell_id} generation has {len(app_matches)} app rows; expected one"
                    )
                app_row = app_matches[0]
                validate_language_app_row(
                    app_row, run_id=args.run_id, cell_id=cell_id, planned_take=planned_take
                )
                selected_app.append(app_row)
            selected.append(row)
            sentinels[cell_id] = sentinel
            selected_sentinel_paths[cell_id] = paths[0]
            selected_generations.add(generation_id)
        unexpected_generations = sorted(set(by_generation) - selected_generations)
        if unexpected_generations:
            raise PublicationError(
                "language run has unexpected generations: " + ", ".join(unexpected_generations)
            )
        unexpected_app_generations = sorted(set(app_by_generation) - selected_generations)
        if unexpected_app_generations:
            raise PublicationError(
                "language run has unexpected app generations: "
                + ", ".join(unexpected_app_generations)
            )
    else:
        by_cell: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_cell.setdefault(str((row.get("notes") or {}).get("benchCell")), []).append(row)
        for cell in cells:
            cell_id = str(cell.get("id"))
            matches = by_cell.get(cell_id, [])
            if len(matches) != 1:
                raise PublicationError(f"language cell {cell_id} has {len(matches)} rows; expected one")
            row = matches[0]
            successful_row(row)
            expected_hint = str(cell.get("expectedHint"))
            if (row.get("notes") or {}).get("languageHint") != expected_hint:
                raise PublicationError(f"language cell {cell_id} has the wrong resolved hint")
            selected.append(row)
        unexpected = sorted(set(by_cell) - set(expected_ids))
        if unexpected:
            raise PublicationError(f"language run has unexpected cells: {', '.join(unexpected)}")
    takes = [minimal_take(index, cell_id, row) for index, (cell_id, row) in enumerate(zip(expected_ids, selected), start=1)]
    if planned_takes is not None:
        validate_prompt_equivalence(
            planned_takes=planned_takes,
            sentinels=sentinels,
            rows_by_cell={str(cell["id"]): row for cell, row in zip(cells, selected)},
        )
        for cell, planned_take, take in zip(cells, planned_takes, takes):
            cell_id = str(cell["id"])
            take["seed"] = int(planned_take["seed"])
            if args.platform == "ios":
                take["layers"] = ["engine", "app"]
                take["layerCompleteness"] = "complete"
            take["output"] = language_output_evidence(
                sentinels[cell_id], selected_sentinel_paths[cell_id].parent / "output.wav", cell_id
            )
    asr_evidence: list[dict[str, Any]] = []
    if output_verified:
        if planned_takes is None:
            raise PublicationError("output verification publication requires an immutable run plan")
        for cell, planned_take, row, take in zip(cells, planned_takes, selected, takes):
            if cell.get("skipOutputVerification"):
                continue
            cell_id = str(cell.get("id"))
            sentinel = sentinels.get(cell_id)
            if not isinstance(sentinel, dict) or sentinel.get("status") != "ok":
                raise PublicationError(f"language cell {cell_id} lacks successful output-verification evidence")
            evidence = sanitized_asr_evidence(
                cell=cell,
                planned_take=planned_take,
                sentinel=sentinel,
                engine_row=row,
                parent_run_id=args.run_id,
                reference_script=corpus_scripts[str(cell["scriptLang"])],
            )
            asr_evidence.append(evidence)
            take["accuracyMetric"] = evidence["accuracyMetric"]
            take["accuracyThreshold"] = evidence["accuracyThreshold"]
            take["metrics"].update({
                "wordErrorRate": evidence["wordErrorRate"],
                "characterErrorRate": evidence["characterErrorRate"],
                "languageMatchScore": evidence["languageMatchScore"],
                "outputLanguagePass": 1.0,
                "outputAccuracyPass": 1.0,
                "referenceTokenCount": float(evidence["referenceTokenCount"]),
                "hypothesisTokenCount": float(evidence["hypothesisTokenCount"]),
                "referenceCharacterCount": float(evidence["referenceCharacterCount"]),
                "hypothesisCharacterCount": float(evidence["hypothesisCharacterCount"]),
                "substitutions": float(evidence["substitutions"]),
                "insertions": float(evidence["insertions"]),
                "deletions": float(evidence["deletions"]),
                "characterSubstitutions": float(evidence["characterSubstitutions"]),
                "characterInsertions": float(evidence["characterInsertions"]),
                "characterDeletions": float(evidence["characterDeletions"]),
                "recognitionPassCount": float(evidence["recognitionPassCount"]),
                "recognitionDurationSeconds": evidence["recognitionDurationSeconds"],
                "primaryAccuracyScore": evidence["primaryAccuracyScore"],
                "accuracyThreshold": evidence["accuracyThreshold"],
            })
    for take in takes:
        take["metrics"]["hintCellsPassed"] = float(len(cells))
        take["metrics"]["hintCellsExpected"] = float(len(cells))
        if output_verified:
            expected_output = sum(not bool(cell.get("skipOutputVerification")) for cell in cells)
            take["metrics"]["outputCellsPassed"] = float(expected_output)
            take["metrics"]["outputCellsExpected"] = float(expected_output)
    # Language benchmarks are generation benchmarks, not metadata-only checks.
    # New schema-v2 publication therefore binds the same exact schema-v8 raw
    # memory sidecars as UI and engine lanes. iOS is a single process, so its
    # engine sample stream owns app+engine memory even though frontend timing
    # remains correlated through the separate app telemetry row.
    try:
        qualified_memory, memory_run = qualify_memory_rows(
            rows=selected,
            diagnostics=args.diagnostics,
            platform=args.platform,
            require_app_layer=False,
        )
    except MemoryEvidenceError as error:
        raise PublicationError(f"language memory qualification failed: {error}") from error
    apply_memory_qualification(takes, qualified_memory)
    matrix_scope = "focused" if output_verified else "partial"
    started = args.started_at
    finished = args.finished_at or utc_now()
    fixture_digests: dict[str, str] = {}
    if args.platform == "ios" and any(take["mode"] == "design" for take in takes):
        design_digests = {
            str(sentinels.get(cell_id, {}).get("fixtureDigest"))
            for cell_id, take in zip(expected_ids, takes)
            if take["mode"] == "design" and sentinels.get(cell_id, {}).get("fixtureDigest")
        }
        if len(design_digests) != 1:
            raise PublicationError(
                "iOS language design cells must expose one consistent payload fixture digest"
            )
        fixture_digests["design"] = design_digests.pop()
    elif getattr(args, "design_fixture_digest", None):
        fixture_digests["design"] = args.design_fixture_digest
    require_fixture_cross_check(takes, fixture_digests, source=f"{args.platform} language runner")
    analysis_profile: dict[str, Any] | None = None
    if asr_evidence:
        evidence_by_cell = {evidence["cell"]: evidence for evidence in asr_evidence}
        analysis_takes: list[dict[str, Any]] = []
        for cell, take, planned in zip(cells, takes, planned_takes or []):
            cell_id = str(cell["id"])
            entry: dict[str, Any] = {
                "cell": cell_id,
                "seed": take.get("seed"),
                "samplingVariation": planned.get("samplingVariation"),
                "promptEquivalenceGroup": planned.get("promptEquivalenceGroup"),
                "outputVerificationRequired": not bool(cell.get("skipOutputVerification")),
                "customSpeakerID": planned.get("customSpeakerID"),
                "designInstructionDigest": planned.get("designInstructionDigest"),
            }
            evidence = evidence_by_cell.get(cell_id)
            if evidence is not None:
                entry.update({
                    "expectedLanguage": evidence["expectedLanguage"],
                    "selectedLocaleIdentifier": evidence["selectedLocaleIdentifier"],
                    "accuracyMetricVersion": evidence["accuracyMetricVersion"],
                    "accuracyMetric": evidence["accuracyMetric"],
                    "accuracyThreshold": evidence["accuracyThreshold"],
                    "outputVerifierSchemaVersion": evidence["outputVerifierSchemaVersion"],
                    "outputVerifierAlgorithm": evidence["outputVerifierAlgorithm"],
                    "recognitionSchemaVersion": evidence["recognitionSchemaVersion"],
                    "recognitionAlgorithm": evidence["recognitionAlgorithm"],
                    "requiredPassCount": evidence["recognitionPassCount"],
                })
            analysis_takes.append(entry)
        analysis_profile = {
            "contract": "autonomous-language-output-v3",
            "seedPolicy": plan.get("seedPolicy") if isinstance(plan, dict) else None,
            "takes": analysis_takes,
        }
    selected_digest_payload: dict[str, Any] = {
        "telemetry": selected,
        "outputVerification": asr_evidence,
        "memorySidecars": memory_run["digestPayload"],
    }
    if selected_app:
        selected_digest_payload["appTelemetry"] = selected_app
    if analysis_profile is not None:
        selected_digest_payload["analysisProfile"] = analysis_profile
    inputs = {"matrixHash": digest_file(args.matrix), "corpusHash": digest_file(args.corpus)}
    if analysis_profile is not None:
        inputs["analysisProfileHash"] = digest_bytes(canonical_bytes(analysis_profile))
    manifest = record_shell(
        kind="language", platform=args.platform, run_id=args.run_id,
        label=args.label or args.run_id, started_at=started, finished_at=finished,
        matrix_scope=matrix_scope, artifact_dir=args.artifact_dir, snapshot=args.snapshot,
        takes=takes, raw_digest=digest_bytes(canonical_bytes(selected_digest_payload)),
        telemetry_schema=max(int(row.get("schemaVersion", 0)) for row in selected),
        qc_algorithm=max(int((row.get("audioQC") or {}).get("algorithmVersion", 1)) for row in selected),
        inputs=inputs,
        hardware=hardware_context(selected),
        hardware_evidence=[
            sentinels[cell_id] for cell_id in expected_ids if cell_id in sentinels
        ] if args.platform == "ios" else None,
        models=exact_models(args.platform, takes),
        crash_delta=crash_delta_from_snapshot(
            args.snapshot,
            expected_scope="macos" if args.platform == "macos" else "ios",
            diagnostics=(getattr(args, "crash_diagnostics", None) or args.diagnostics)
            if args.platform == "ios" else None,
        ),
        executable_paths={"vocello": "build/vocello"} if args.platform == "macos" else {"Vocello": "build/cache/xcode/ios-device/Build/Products/Release-iphoneos/Vocello.app/Vocello"},
        optimization="-Onone",
        classification=("exploratory" if uses_forced_memory_profile(selected) else None),
        memory_evidence=compact_memory_evidence(memory_run),
    )
    if asr_evidence:
        manifest["historyRecord"]["evidence"]["languageVerification"] = {
            "outputSchemaVersion": LANGUAGE_OUTPUT_SCHEMA,
            "outputAlgorithm": LANGUAGE_OUTPUT_ALGORITHM,
            "recognitionSchemaVersion": ASR_EVIDENCE_SCHEMA,
            "recognitionAlgorithm": ASR_EVIDENCE_ALGORITHM,
            "accuracyMetricVersion": LANGUAGE_ACCURACY_METRIC_VERSION,
            "requiredPassCount": ASR_REQUIRED_PASS_COUNT,
        }
    return write_and_record(
        args.artifact_dir, manifest,
        defer_record=bool(getattr(args, "defer_record", False)),
    )


def telemetry_overhead_command(args: argparse.Namespace) -> Path:
    raise PublicationError(
        "telemetry-overhead is an observer-effect diagnostic and cannot publish "
        "schema-v2 history without memory-complete evidence for the telemetry-off lane"
    )


def _legacy_telemetry_overhead_record(args: argparse.Namespace) -> Path:
    """Retained parser for old local verdict fixtures; not history-publishable."""
    verdict = load_json(args.verdict)
    if verdict.get("status") != "pass" or verdict.get("schemaVersion") != 2:
        raise PublicationError("telemetry-overhead verdict is not successful schema v2 evidence")
    summary = verdict.get("summary")
    if not isinstance(summary, dict) or summary.get("pcmParity") is not True or summary.get("failures"):
        raise PublicationError("telemetry-overhead parity or threshold gate did not pass")
    telemetry_schema = summary.get("telemetrySchemaVersion")
    model_id = summary.get("modelID")
    model_runtime_identity = summary.get("modelRuntimeIdentity")
    if not isinstance(telemetry_schema, int) or telemetry_schema < 8 or model_id != "pro_custom_speed":
        raise PublicationError("telemetry-overhead lacks schema-v8 Custom Speed identity")
    typed_identity = runtime_identity({
        "schemaVersion": telemetry_schema,
        "modelID": model_id,
        "modelRuntimeIdentity": model_runtime_identity,
    }, mode="custom", model_id=model_id)
    results = summary.get("results")
    if not isinstance(results, dict):
        raise PublicationError("telemetry-overhead results are missing")
    expected_pcm_keys = {
        f"r{rotation}-t{measured}"
        for rotation in range(1, 4) for measured in range(1, 3)
    }
    empty_pcm_digest = hashlib.sha256(b"").hexdigest()
    pcm_maps: dict[str, dict[str, str]] = {}
    for mode in ("off", "lightweight", "verbose"):
        pcm = (results.get(mode) or {}).get("pcmSHA256")
        if not isinstance(pcm, dict) or set(pcm) != expected_pcm_keys:
            raise PublicationError(
                f"telemetry-overhead mode {mode} lacks six exact PCM digests"
            )
        normalized = {str(key): str(value) for key, value in pcm.items()}
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", value) or value == empty_pcm_digest
            for value in normalized.values()
        ):
            raise PublicationError(
                f"telemetry-overhead mode {mode} contains empty or invalid PCM evidence"
            )
        pcm_maps[mode] = normalized
    if any(pcm_maps[mode] != pcm_maps["off"] for mode in ("lightweight", "verbose")):
        raise PublicationError("telemetry-overhead PCM digest maps do not have exact parity")
    ordered_samples: list[dict[str, Any]] = []
    for mode in ("off", "lightweight", "verbose"):
        samples = (results.get(mode) or {}).get("samples")
        if not isinstance(samples, list) or len(samples) != 6:
            raise PublicationError(f"telemetry-overhead mode {mode} does not contain six measured takes")
        for sample in samples:
            ordered_samples.append({**sample, "telemetryMode": mode})
    ordered_samples.sort(key=lambda sample: (
        int(sample.get("rotation", 0)),
        int(sample.get("modeOrder", 0)),
        int(sample.get("measuredTake", 0)),
    ))
    contexts = summary.get("machineContext")
    context_by_lane: dict[tuple[int, int, str], dict[str, Any]] = {}
    if isinstance(contexts, list):
        for context in contexts:
            if isinstance(context, dict):
                context_by_lane[(
                    int(context.get("rotation", 0)),
                    int(context.get("order", 0)),
                    str(context.get("mode", "")),
                )] = context
    thermal_rank = {"nominal": 0, "fair": 1, "serious": 2, "critical": 3, "unknown": -1}
    takes: list[dict[str, Any]] = []
    for index, sample in enumerate(ordered_samples, start=1):
        mode = str(sample["telemetryMode"])
        rotation = int(sample["rotation"])
        mode_order = int(sample["modeOrder"])
        measured_take = int(sample["measuredTake"])
        context = context_by_lane.get((rotation, mode_order, mode), {})
        before = context.get("before") if isinstance(context.get("before"), dict) else {}
        after = context.get("after") if isinstance(context.get("after"), dict) else {}
        environment = sample.get("environment") if isinstance(sample.get("environment"), dict) else {}
        audio_seconds = finite_number(sample.get("audioSeconds"))
        rtf = finite_number(sample.get("rtf"))
        ttfc = finite_number(sample.get("ttfcMS"))
        if audio_seconds is None or audio_seconds <= 0 or rtf is None or rtf <= 0 or ttfc is None or ttfc < 0:
            raise PublicationError(
                f"telemetry-overhead mode {mode} contains empty audio or invalid timing"
            )
        take_metrics = {
            "rtf": rtf,
            "ttfcMS": ttfc,
            "audioSeconds": audio_seconds,
        }
        load = environment.get("loadAverage1Minute")
        if (value := finite_number(load)) is not None:
            take_metrics["loadAverage1M"] = value
        elif isinstance(before.get("loadAverage"), list) and before["loadAverage"] \
                and (value := finite_number(before["loadAverage"][0])) is not None:
            take_metrics["loadAverage1M"] = value
        if (value := finite_number(environment.get("freeStorageBytes"))) is not None:
            take_metrics["freeStorageBytes"] = value
        elif (value := finite_number(before.get("freeStorageBytes"))) is not None:
            take_metrics["freeStorageBytes"] = value
        if (value := finite_number(environment.get("uptimeSeconds"))) is not None:
            take_metrics["uptimeSeconds"] = value
        elif (value := finite_number(before.get("uptimeSeconds"))) is not None:
            take_metrics["uptimeSeconds"] = value
        if isinstance(environment.get("lowPowerModeEnabled"), bool):
            take_metrics["lowPowerMode"] = 1.0 if environment["lowPowerModeEnabled"] else 0.0
        elif isinstance(before.get("lowPowerMode"), bool):
            take_metrics["lowPowerMode"] = 1.0 if before["lowPowerMode"] else 0.0
        thermal_values = [
            str(value).lower() for value in (
                environment.get("thermalState"), before.get("thermalState"), after.get("thermalState")
            )
            if str(value).lower() in thermal_rank
        ]
        take_thermal = max(thermal_values, key=lambda value: thermal_rank[value]) if thermal_values else "unknown"
        takes.append({
                "takeIndex": index,
                "generationID": str(sample.get("generationID")),
                "cell": f"rotation-{rotation}/order-{mode_order}/{mode}/take-{measured_take}",
                "mode": "custom",
                "modelID": "pro_custom_speed",
                "variant": "speed",
                "warmState": "warm",
                "length": "medium",
                "finishReason": "completed",
                "status": "passed",
                "output": {
                    "readableWAV": True,
                    "atomicPublish": True,
                    "durationSeconds": audio_seconds,
                    "fileDigest": pcm_maps[mode][f"r{rotation}-t{measured_take}"],
                },
                "metrics": take_metrics,
                "thermalState": take_thermal,
                "warnings": [],
                **typed_identity,
            })
    overhead_hardware: dict[str, Any] = {}
    if isinstance(contexts, list) and contexts and isinstance(contexts[0], dict):
        before = contexts[0].get("before")
        if isinstance(before, dict):
            load = before.get("loadAverage")
            if isinstance(load, list) and load and (value := finite_number(load[0])) is not None:
                overhead_hardware["loadAverage1M"] = value
            if (value := finite_number(before.get("freeStorageBytes"))) is not None:
                overhead_hardware["freeStorageBytes"] = int(value)
            if (value := finite_number(before.get("uptimeSeconds"))) is not None:
                overhead_hardware["uptimeSeconds"] = value
    manifest = record_shell(
        kind="telemetry-overhead", platform="macos", run_id=str(verdict.get("runID")),
        label=str(verdict.get("runID")), started_at=str(verdict.get("startedAt")),
        finished_at=str(verdict.get("completedAt")), matrix_scope="focused",
        artifact_dir=args.artifact_dir, snapshot=args.snapshot, takes=takes,
        raw_digest=digest_file(args.verdict), telemetry_schema=telemetry_schema,
        qc_algorithm="not-applicable",
        inputs={"matrixHash": digest_bytes(canonical_bytes({
            "seed": summary.get("seed"),
            "modeOrderRotations": summary.get("modeOrderRotations"),
            "warmupTakesPerModePerRotation": summary.get("warmupTakesPerModePerRotation"),
            "measuredWarmTakesPerModePerRotation": summary.get("measuredWarmTakesPerModePerRotation"),
        }))},
        hardware=overhead_hardware,
        models=exact_models("macos", takes),
        crash_delta=crash_delta_from_snapshot(args.snapshot, expected_scope="macos"),
        executable_paths={"vocello": "build/vocello"},
        optimization="-Onone",
    )
    return write_and_record(args.artifact_dir, manifest)


def _xml_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower().replace("_", "-")


def _pid_from_text(value: str | None) -> int | None:
    if not value:
        return None
    token = value.strip()
    try:
        return int(token, 0)
    except ValueError:
        pass
    for pattern in (r"\bpid\s*[=:]\s*(\d+)\b", r"\((\d+)\)\s*$"):
        match = re.search(pattern, token, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _element_pid(element: ET.Element) -> int | None:
    attributes = {
        key.rsplit("}", 1)[-1].lower().replace("_", "-"): value
        for key, value in element.attrib.items()
    }
    for key in ("pid", "process-id", "process-identifier"):
        if (pid := _pid_from_text(attributes.get(key))) is not None:
            return pid
    if _xml_tag(element) in {"pid", "process-id", "process-identifier", "process"}:
        for key in ("fmt", "formatted", "value", "name"):
            if (pid := _pid_from_text(attributes.get(key))) is not None:
                return pid
        return _pid_from_text(element.text)
    return None


def _process_reference_pids(root: ET.Element) -> dict[str, int]:
    references: dict[str, int] = {}
    for element in root.iter():
        if _xml_tag(element) != "process":
            continue
        pid = _element_pid(element)
        if pid is None:
            for child in element:
                if (pid := _element_pid(child)) is not None:
                    break
        identifier = element.get("id")
        if identifier and pid is not None:
            references[identifier] = pid
    return references


def _row_process_pid(row: ET.Element, references: dict[str, int]) -> int | None:
    if (direct := _element_pid(row)) is not None:
        return direct
    observed: set[int] = set()
    for element in row.iter():
        tag = _xml_tag(element)
        if tag not in {"pid", "process-id", "process-identifier", "process"}:
            continue
        if (pid := _element_pid(element)) is not None:
            observed.add(pid)
        reference = element.get("ref")
        if reference in references:
            observed.add(references[reference])
    return next(iter(observed)) if len(observed) == 1 else None


def extract_trace_data_summary(
    trace: Path,
    schemas: Iterable[str],
    *,
    run_id: str,
    target_pid: int,
    expected_correlations: set[tuple[str, int, str]],
) -> dict[str, Any]:
    relevant = sorted({
        schema for schema in schemas
        if re.fullmatch(r"[A-Za-z0-9._-]+", schema)
        and any(token in schema.lower() for token in (
            "cpu-profile", "time-profile", "signpost", "allocation", "vm", "energy", "gpu", "wakeup",
        ))
    })
    if not relevant:
        raise PublicationError("xctrace table-of-contents exposes no performance-data schema")

    rows_by_schema: dict[str, int] = {}
    cpu_weights_ns: list[float] = []
    cpu_cycle_weights: list[float] = []
    cpu_sample_times_ns: list[float] = []
    signpost_events = 0
    correlated_signposts = 0
    observed_correlations: set[tuple[str, int, str]] = set()
    for schema in relevant:
        descriptor, temporary = tempfile.mkstemp(prefix="vocello-xctrace-", suffix=".xml")
        os.close(descriptor)
        try:
            completed = subprocess.run(
                [
                    "xcrun", "xctrace", "export", "--input", str(trace),
                    "--xpath", f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]',
                    "--output", temporary,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode:
                detail = completed.stderr.strip() or completed.stdout.strip() or "unknown export failure"
                raise PublicationError(f"could not export xctrace schema {schema}: {detail}")
            try:
                root = ET.parse(temporary).getroot()
            except (OSError, ET.ParseError) as error:
                raise PublicationError(f"xctrace schema {schema} exported invalid XML") from error
            all_rows = [element for element in root.iter() if _xml_tag(element) == "row"]
            process_references = _process_reference_pids(root)
            rows = [
                row for row in all_rows
                if _row_process_pid(row, process_references) == target_pid
            ]
            rows_by_schema[schema] = len(rows)
            if schema in {"cpu-profile", "time-profile"}:
                resolved: dict[tuple[str, str], float] = {}
                for element in root.iter():
                    tag = element.tag.rsplit("}", 1)[-1]
                    if tag not in {"cycle-weight", "weight", "sample-time"} or not element.get("id"):
                        continue
                    try:
                        resolved[(tag, element.get("id", ""))] = float((element.text or "").strip())
                    except ValueError:
                        continue
                for row in rows:
                    fields = [("sample-time", cpu_sample_times_ns)]
                    fields.append(
                        ("cycle-weight", cpu_cycle_weights)
                        if schema == "cpu-profile" else ("weight", cpu_weights_ns)
                    )
                    for tag, destination in fields:
                        element = next(
                            (child for child in row.iter() if child.tag.rsplit("}", 1)[-1] == tag),
                            None,
                        )
                        if element is None:
                            continue
                        value = resolved.get((tag, element.get("ref", "")))
                        if value is None:
                            try:
                                value = float((element.text or "").strip())
                            except ValueError:
                                continue
                        destination.append(value)
            if "signpost" in schema.lower():
                signpost_events += len(rows)
                elements_by_id = {
                    element.get("id"): element
                    for element in root.iter()
                    if element.get("id")
                }

                def resolved_text(element: ET.Element, seen: frozenset[str] = frozenset()) -> str:
                    reference = element.get("ref")
                    if reference and reference not in seen and reference in elements_by_id:
                        return resolved_text(elements_by_id[reference], seen | {reference})
                    rendered = element.get("fmt")
                    if rendered:
                        return rendered
                    pieces = [element.text.strip()] if element.text and element.text.strip() else []
                    pieces.extend(
                        value for child in element
                        if (value := resolved_text(child, seen))
                    )
                    return " ".join(pieces)

                for row in rows:
                    serialized = " ".join(
                        value for element in row.iter()
                        if (value := resolved_text(element))
                    )
                    generation = re.search(r"\bgenerationID=\s*([A-Za-z0-9._-]+)", serialized)
                    take_index = re.search(r"\btakeIndex=\s*([1-9][0-9]*)", serialized)
                    cell = re.search(r"\bcell=\s*([^\s<]+)", serialized)
                    run = re.search(r"\brunID=\s*([A-Za-z0-9._-]+)", serialized)
                    if run is None or run.group(1) != run_id or not all(
                        (generation, take_index, cell)
                    ):
                        continue
                    correlation = (
                        generation.group(1), int(take_index.group(1)), cell.group(1)
                    )
                    if correlation in expected_correlations:
                        correlated_signposts += 1
                        observed_correlations.add(correlation)
        finally:
            Path(temporary).unlink(missing_ok=True)

    captured_rows = sum(rows_by_schema.values())
    if captured_rows == 0:
        raise PublicationError("xctrace exported no performance data rows")
    if not ({"cpu-profile", "time-profile"} & set(relevant)):
        raise PublicationError("trace lacks an exportable CPU Profiler or Time Profiler table")
    if not cpu_sample_times_ns:
        raise PublicationError("CPU profile trace contains no target-process samples")
    correlation_fields_verified = correlated_signposts > 0
    if signpost_events == 0 or not correlation_fields_verified:
        raise PublicationError("trace lacks a run/generation/take/cell-correlated signpost")
    missing_correlations = expected_correlations - observed_correlations
    if missing_correlations:
        raise PublicationError(
            f"trace lacks exact signpost correlation for {len(missing_correlations)} profiled take(s)"
        )
    summary = {
        "capturedRowsBySchema": rows_by_schema,
        "capturedDataRowCount": captured_rows,
        "cpuSampleCount": len(cpu_sample_times_ns),
        "cpuSampleSpanMS": round(
            (max(cpu_sample_times_ns) - min(cpu_sample_times_ns)) / 1_000_000.0, 6
        ) if len(cpu_sample_times_ns) >= 2 else 0.0,
        "signpostEventCount": signpost_events,
        "correlatedSignpostEventCount": correlated_signposts,
        "correlationFieldsVerified": correlation_fields_verified,
    }
    if cpu_weights_ns:
        summary["cpuSampleWeightMS"] = round(sum(cpu_weights_ns) / 1_000_000.0, 6)
    if cpu_cycle_weights:
        summary["cpuCycleWeight"] = int(sum(cpu_cycle_weights))
    return summary


def _memory_trace_export_evidence(rows_by_schema: dict[str, int]) -> dict[str, Any]:
    """Describe target-PID memory rows without confusing TOC labels with data.

    Xcode currently exposes Allocations and VM Tracker as configured tracks even
    when it does not expose their backing data as an exportable table.  A table
    advertised in the trace TOC is exportable, however, and in that case a
    memory profile is only valid when the table contains rows owned by the
    requested PID.  `extract_trace_data_summary` has already applied that PID
    filter, so zero here also covers the wrong-PID-only case.
    """

    allocation_schemas = {
        name: count for name, count in rows_by_schema.items()
        if "allocation" in name.lower()
    }
    vm_schemas = {
        name: count for name, count in rows_by_schema.items()
        if (
            name.lower().startswith("vm")
            or "vm-tracker" in name.lower()
            or "vm_tracker" in name.lower()
            or "virtual-memory" in name.lower()
            or "virtual_memory" in name.lower()
        )
    }
    allocation_rows = sum(allocation_schemas.values())
    vm_rows = sum(vm_schemas.values())
    if allocation_schemas and allocation_rows <= 0:
        raise PublicationError(
            "memory profile exposes Allocations tables but contains no target-PID rows"
        )
    if vm_schemas and vm_rows <= 0:
        raise PublicationError(
            "memory profile exposes VM Tracker tables but contains no target-PID rows"
        )
    return {
        "allocationDataExportStatus": "targetRows" if allocation_schemas else "notExportable",
        "allocationTargetRowCount": allocation_rows,
        "vmTrackerDataExportStatus": "targetRows" if vm_schemas else "notExportable",
        "vmTrackerTargetRowCount": vm_rows,
    }


def require_vm_tracker_auto_snapshot_disabled(trace: Path) -> None:
    """Reject macOS memory traces that can suspend their own telemetry source.

    A standalone VM Tracker instrument added to a Blank trace enables automatic
    snapshots. Those snapshots stop the exact target process, so its in-process
    500 ms sampler cannot observe the interval and correctly reports missed
    deadlines. Apple's Allocations template contains the same Allocations and
    VM Tracker tracks with ``XRVMInstrumentKey_autoSnapshot`` disabled. Inspect
    the captured template rather than trusting the requested template name.
    """

    template = trace / "form.template"
    if not template.is_file():
        raise PublicationError("memory trace is missing its captured Instruments template")
    try:
        with template.open("rb") as stream:
            archive = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as error:
        raise PublicationError("memory trace contains an invalid captured Instruments template") from error
    objects = archive.get("$objects") if isinstance(archive, dict) else None
    if not isinstance(objects, list):
        raise PublicationError("memory trace template is not a keyed Instruments archive")
    key_indexes = {
        index for index, value in enumerate(objects)
        if value == "XRVMInstrumentKey_autoSnapshot"
    }
    observed: list[bool] = []
    for value in objects:
        if not isinstance(value, dict):
            continue
        keys = value.get("NS.keys")
        values = value.get("NS.objects")
        if not isinstance(keys, list) or not isinstance(values, list) or len(keys) != len(values):
            continue
        for key, setting in zip(keys, values, strict=True):
            if not isinstance(key, plistlib.UID) or key.data not in key_indexes:
                continue
            resolved = objects[setting.data] if isinstance(setting, plistlib.UID) else setting
            if not isinstance(resolved, bool):
                raise PublicationError("VM Tracker automatic-snapshot setting is not boolean")
            observed.append(resolved)
    if not observed:
        raise PublicationError("memory trace does not expose the VM Tracker automatic-snapshot setting")
    if any(observed):
        raise PublicationError(
            "VM Tracker automatic snapshots are enabled and can invalidate sampler coverage"
        )


def _build_relative_artifact(path: Path, *, suffix: str, description: str) -> str:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except ValueError as error:
        raise PublicationError(
            f"{description} must remain under the repository's untracked build directory"
        ) from error
    if not relative.parts or relative.parts[0] != "build" or relative.suffix != suffix:
        raise PublicationError(
            f"{description} must be a {suffix} artifact under the repository build directory"
        )
    return relative.as_posix()


def write_trace_summary_artifact(
    args: argparse.Namespace,
    *,
    trace_digest: str,
    original_ephemeral_path: str,
    trace_summary: dict[str, Any],
) -> dict[str, Any]:
    """Freeze compact trace evidence before history publication and retention.

    The platform runner owns deletion.  This function records the intended
    post-publication policy but deliberately leaves the raw bundle untouched;
    therefore a failed manifest or history step always preserves the trace.
    """

    retention_policy = getattr(args, "retention_policy", "summaryOnly")
    if retention_policy not in {"summaryOnly", "keptExplicitly"}:
        raise PublicationError(f"unsupported trace retention policy: {retention_policy!r}")
    profile_kind = getattr(args, "profile_kind", "cpu")
    template = Path(args.template).name
    capture_settings = {
        "profileKind": profile_kind,
        "template": template,
        "requestedDurationSeconds": float(args.duration),
        "targetProcess": str(args.target_process),
        "exactPID": True,
    }
    capture_settings_digest = digest_bytes(canonical_bytes(capture_settings))

    configured_summary = getattr(args, "summary_artifact", None)
    summary_path = (
        Path(configured_summary)
        if configured_summary is not None
        else args.trace.with_name(f"{args.trace.stem}-summary.json")
    )
    if not summary_path.is_absolute():
        summary_path = ROOT / summary_path
    try:
        summary_path.resolve().relative_to(args.trace.resolve())
    except ValueError:
        pass
    else:
        raise PublicationError("trace summary artifact must live outside the raw trace bundle")
    summary_reference = _build_relative_artifact(
        summary_path, suffix=".json", description="trace summary artifact"
    )
    summary_payload = {
        "schemaVersion": 1,
        "runID": str(args.run_id),
        "traceDigest": trace_digest,
        "originalEphemeralPath": original_ephemeral_path,
        "retentionPolicy": retention_policy,
        # Intended durable state after successful history publication. The
        # runner retains the raw trace and writes failure metadata if any later
        # validation/publication step fails before this policy is finalized.
        "rawTraceRetained": retention_policy == "keptExplicitly",
        "captureSettings": capture_settings,
        "captureSettingsDigest": capture_settings_digest,
        "validated": True,
        "traceSummary": trace_summary,
    }
    atomic_json(summary_path, summary_payload)
    return {
        "originalEphemeralPath": original_ephemeral_path,
        "summaryArtifact": {
            "path": summary_reference,
            "digest": digest_file(summary_path),
        },
        "rawTraceRetained": retention_policy == "keptExplicitly",
        "retentionPolicy": retention_policy,
        "captureSettings": capture_settings,
        "captureSettingsDigest": capture_settings_digest,
    }


def trace_evidence(
    args: argparse.Namespace,
    *,
    expected_correlations: set[tuple[str, int, str]],
    require_disabled_vm_auto_snapshot: bool = False,
) -> dict[str, Any]:
    if not expected_correlations:
        raise PublicationError("profile publication has no expected take correlation")
    if not args.trace.is_dir():
        raise PublicationError(f"trace is missing: {args.trace}")
    if not args.toc.is_file() or args.toc.stat().st_size == 0:
        raise PublicationError("xctrace table-of-contents export is missing or empty")
    try:
        toc = ET.parse(args.toc)
    except (OSError, ET.ParseError) as error:
        raise PublicationError(f"xctrace table-of-contents is invalid XML: {error}") from error
    artifact_reference = _build_relative_artifact(
        args.trace, suffix=".trace", description="trace"
    )
    table_count = sum(
        element.tag.rsplit("}", 1)[-1].lower() == "table"
        for element in toc.getroot().iter()
    )
    if table_count == 0:
        raise PublicationError("xctrace table-of-contents contains no captured data tables")
    process_entries: list[tuple[str, int | None]] = []
    for element in toc.getroot().iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag != "process":
            continue
        attributes = {
            key.rsplit("}", 1)[-1].lower().replace("_", "-"): value
            for key, value in element.attrib.items()
        }
        name = next(
            (attributes[key] for key in ("name", "process-name", "executable", "path") if attributes.get(key)),
            None,
        )
        pid_raw = next(
            (attributes[key] for key in ("pid", "process-id", "process-identifier") if attributes.get(key)),
            None,
        )
        if name is None:
            for child in element:
                child_tag = child.tag.rsplit("}", 1)[-1].lower().replace("_", "-")
                if child_tag in {"name", "process-name", "executable", "path"} and child.text:
                    name = child.text.strip()
                    break
        if pid_raw is None:
            for child in element:
                child_tag = child.tag.rsplit("}", 1)[-1].lower().replace("_", "-")
                if child_tag in {"pid", "process-id", "process-identifier"} and child.text:
                    pid_raw = child.text.strip()
                    break
        pid: int | None = None
        if pid_raw is not None:
            try:
                pid = int(pid_raw, 0)
            except ValueError:
                pid = None
        if name:
            process_entries.append((Path(name).name, pid))
    matching_processes = [entry for entry in process_entries if entry[0] == args.target_process]
    if not matching_processes:
        raise PublicationError(
            f"xctrace table-of-contents does not contain target process {args.target_process!r}"
        )
    requested_pid = getattr(args, "target_pid", None)
    if requested_pid is not None and not any(pid == requested_pid for _, pid in matching_processes):
        raise PublicationError(
            f"xctrace table-of-contents does not contain target PID {requested_pid}"
        )
    if requested_pid is None:
        matching_pids = {pid for _, pid in matching_processes if pid is not None}
        if len(matching_pids) != 1:
            raise PublicationError(
                "xctrace table-of-contents does not resolve the target process to one exact PID"
            )
        target_pid = next(iter(matching_pids))
    else:
        target_pid = requested_pid
    schemas: set[str] = set()
    signpost_schemas: set[str] = set()
    for element in toc.getroot().iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"table", "schema"}:
            continue
        name = next(
            (value for key, value in element.attrib.items() if key.rsplit("}", 1)[-1].lower() in {"schema", "name", "id"}),
            tag,
        )
        token = str(name).strip().lower()
        schemas.add(token)
        if "signpost" in token:
            signpost_schemas.add(token)
    profile_kind = getattr(args, "profile_kind", "cpu")
    track_details: dict[str, set[str]] = {}
    for element in toc.getroot().iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "track":
            continue
        name = str(element.attrib.get("name") or "").strip().lower()
        if not name:
            continue
        track_details[name] = {
            str(child.attrib.get("name") or "").strip().lower()
            for child in element.iter()
            if child.tag.rsplit("}", 1)[-1].lower() == "detail"
        }
    if profile_kind == "memory":
        if "allocations" not in track_details:
            raise PublicationError("memory profile lacks the Allocations track")
        if "vm tracker" not in track_details:
            raise PublicationError("memory profile lacks the VM Tracker track")
        if "allocations list" not in track_details["allocations"]:
            raise PublicationError("memory profile lacks the Allocations List detail")
        if "regions map" not in track_details["vm tracker"]:
            raise PublicationError("memory profile lacks the VM Tracker Regions Map detail")
        if require_disabled_vm_auto_snapshot:
            require_vm_tracker_auto_snapshot_disabled(args.trace)
    extracted = extract_trace_data_summary(
        args.trace,
        schemas,
        run_id=str(args.run_id),
        target_pid=target_pid,
        expected_correlations=expected_correlations,
    )
    if profile_kind == "memory":
        allocation_files = list(args.trace.glob(f"Trace*.run/event_data_{target_pid}.oa"))
        allocation_target_bytes = sum(
            path.stat().st_size for path in allocation_files if path.is_file()
        )
        if allocation_target_bytes <= 0:
            raise PublicationError("memory profile contains no exact-PID allocation event data")
        exported_memory = _memory_trace_export_evidence(extracted["capturedRowsBySchema"])
        extracted = {
            **extracted,
            "memoryTraceEvidenceVersion": 2,
            "allocationTargetDataBytes": allocation_target_bytes,
            # These are deliberately named as TOC-presence facts.  They do not
            # claim that xctrace exported target-process rows.
            "allocationTrackPresent": True,
            "allocationListPresent": True,
            "vmTrackerTrackPresent": True,
            "vmTrackerRegionMapPresent": True,
            **exported_memory,
        }
    trace_digest = digest_bytes(canonical_bytes([
        [path.relative_to(args.trace).as_posix(), digest_file(path)]
        for path in sorted(args.trace.rglob("*")) if path.is_file()
    ]))
    summary = {
        "artifact": artifact_reference,
        "tocDigest": digest_file(args.toc),
        "tableCount": table_count,
        "schemaCount": len(schemas),
        "signpostSchemaCount": len(signpost_schemas),
        "processCount": len(set(process_entries)),
        "targetProcess": args.target_process,
        "targetPIDVerified": True,
        **extracted,
    }
    retention = write_trace_summary_artifact(
        args,
        trace_digest=trace_digest,
        original_ephemeral_path=artifact_reference,
        trace_summary=summary,
    )
    return {
        "digest": trace_digest,
        "template": Path(args.template).name,
        "durationSeconds": float(args.duration),
        "validated": True,
        "summary": summary,
        **retention,
    }


def _profile_correlations(args: argparse.Namespace, *, ios: bool) -> set[tuple[str, int, str]]:
    if ios:
        sentinel = load_json(args.sentinel)
        generation_id = sentinel.get("generationID")
        mode = sentinel.get("mode")
        variant = sentinel.get("variant", "speed")
        if (
            sentinel.get("runID") != args.run_id
            or not isinstance(generation_id, str) or not generation_id
            or not isinstance(mode, str) or not mode
            or not isinstance(variant, str) or not variant
        ):
            raise PublicationError("iOS profile sentinel lacks exact signpost identity")
        return {(generation_id, 1, f"{mode}/{variant}/device")}

    results = load_json(args.results)
    takes = results.get("takes")
    if results.get("runID") != args.run_id or not isinstance(takes, list) or not takes:
        raise PublicationError("profile bench results lack exact signpost identity")
    expected: set[tuple[str, int, str]] = set()
    for index, take in enumerate(takes, start=1):
        if not isinstance(take, dict) or take.get("takeIndex") != index:
            raise PublicationError("profile bench take indices are not exact")
        generation_id = take.get("generationID")
        cell = take.get("cell")
        if not isinstance(generation_id, str) or not generation_id or not isinstance(cell, str) or not cell:
            raise PublicationError("profile bench take lacks generation or cell identity")
        expected.add((generation_id, index, cell))
    if len(expected) != len(takes):
        raise PublicationError("profile bench correlations are not unique")
    return expected


def profile_command(args: argparse.Namespace) -> Path:
    trace = trace_evidence(
        args,
        expected_correlations=_profile_correlations(args, ios=False),
        require_disabled_vm_auto_snapshot=args.profile_kind == "memory",
    )
    return engine_command(args, kind="instrument-profile", trace=trace)


def ios_profile_command(args: argparse.Namespace) -> Path:
    trace = trace_evidence(
        args, expected_correlations=_profile_correlations(args, ios=True)
    )
    return ios_engine_command(args, kind="instrument-profile", trace=trace)


def prosody_command(args: argparse.Namespace) -> Path:
    result = load_json(args.results)
    if result.get("status") != "pass" or result.get("analysisFailureCount") != 0:
        raise PublicationError("prosody calibration did not pass without analysis failures")
    if int(result.get("goodClipCount", 0)) < 2 or int(result.get("badClipCount", 0)) < 2:
        raise PublicationError("prosody calibration corpus lacks the required good/bad clips")
    profile = load_json(args.profile)
    profile_digest = digest_file(args.profile)
    if result.get("profileDigest") != profile_digest:
        raise PublicationError("prosody result does not identify the published profile")
    thresholds = profile.get("thresholds")
    flag_rates = result.get("flagRates")
    if not isinstance(thresholds, dict) or not isinstance(flag_rates, dict):
        raise PublicationError("prosody calibration lacks threshold or flag-rate evidence")
    metric_sources = {
        "analyzerAlgorithmVersion": result.get(
            "analyzerAlgorithmVersion",
            profile.get("analyzer_algorithm_version", 1),
        ),
        "goodClipCount": result.get("goodClipCount"),
        "badClipCount": result.get("badClipCount"),
        "targetFalsePositiveRate": result.get("targetFalsePositiveRate"),
        "observedFalsePositiveRate": flag_rates.get("false_positive_rate"),
        "observedTruePositiveRate": flag_rates.get("true_positive_rate"),
        "goodFlagRate": flag_rates.get("good_flag_rate"),
        "badFlagRate": flag_rates.get("bad_flag_rate"),
        "monotoneF0StdThresholdHz": thresholds.get("monotone_f0_std_hz"),
        "monotoneTurningPointsThresholdPerSecond": thresholds.get("monotone_turning_points_per_sec"),
        "rushedSyllableRateThresholdHz": thresholds.get("rushed_syllable_rate_hz"),
        "rushedMaximumPauseRatio": thresholds.get("rushed_max_pause_ratio"),
        "flatEnvelopeRoughnessThreshold": thresholds.get("flat_envelope_roughness"),
        "flatRateCVThreshold": thresholds.get("flat_rate_cv"),
        "maximumPauseThresholdSeconds": thresholds.get("pause_max_seconds"),
        "maximumPauseRatioThreshold": thresholds.get("pause_ratio_max"),
    }
    metrics = {key: finite_number(value) for key, value in metric_sources.items()}
    if any(value is None for value in metrics.values()):
        raise PublicationError("prosody calibration contains non-finite aggregate evidence")
    run_id = str(result.get("runID"))
    take = {
        "takeIndex": 1,
        "generationID": f"{run_id}-analysis",
        "cell": "prosody-calibration/corpus",
        "mode": "not-applicable",
        "modelID": "not-applicable",
        "variant": "not-applicable",
        "warmState": "not-applicable",
        "length": "not-applicable",
        "finishReason": "completed",
        "status": "passed",
        "metrics": metrics,
        "warnings": [],
    }
    combined_digest = digest_bytes(canonical_bytes({
        "results": result,
        "profileDigest": profile_digest,
    }))
    manifest = record_shell(
        kind="prosody-calibration", platform="macos", run_id=run_id,
        label=run_id, started_at=str(result.get("startedAt")),
        finished_at=str(result.get("finishedAt")), matrix_scope="focused",
        artifact_dir=args.artifact_dir, snapshot=args.snapshot, takes=[take],
        raw_digest=combined_digest, telemetry_schema="not-applicable", qc_algorithm="not-applicable",
        inputs={
            "corpusHash": str(result.get("corpusDigest")),
            "analysisProfileHash": profile_digest,
        },
        # Calibration analyzes an existing labeled corpus and launches no app or
        # engine process. Its crash delta is therefore explicitly not applicable;
        # the registry's boolean means that this benchmark introduced no target crash.
        crash_delta={"passed": True, "count": 0},
        executable_paths={},
        optimization="not-applicable",
    )
    return write_and_record(args.artifact_dir, manifest)


def add_snapshot(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)


def add_engine(parser: argparse.ArgumentParser) -> None:
    add_snapshot(parser)
    parser.add_argument("--platform", choices=("macos", "ios"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--defer-record", action="store_true",
        help="write validated benchmark-evidence.json without updating tracked history",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot", help="capture pre-run Git provenance")
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--crash-scope", choices=("macos", "ios", "none"), required=True)
    snapshot.add_argument("--crash-diagnostics", type=Path)

    engine = subparsers.add_parser("engine", help="publish a vocello bench run")
    add_engine(engine)

    memory = subparsers.add_parser(
        "memory-qualification", help="publish a retained-memory qualification run"
    )
    add_engine(memory)

    ios_engine = subparsers.add_parser("ios-engine", help="publish one physical-iPhone headless run")
    add_snapshot(ios_engine)
    ios_engine.add_argument("--run-id", required=True)
    ios_engine.add_argument("--sentinel", type=Path, required=True)
    ios_engine.add_argument("--diagnostics", type=Path, required=True)
    ios_engine.add_argument("--crash-diagnostics", type=Path)
    ios_engine.add_argument("--label", default="")
    ios_engine.add_argument("--defer-record", action="store_true")

    language = subparsers.add_parser("language", help="publish a gated language matrix")
    add_snapshot(language)
    language.add_argument("--platform", choices=("macos", "ios"), required=True)
    language.add_argument("--run-id", required=True)
    language.add_argument("--diagnostics", type=Path, required=True)
    language.add_argument("--crash-diagnostics", type=Path)
    language.add_argument("--matrix", type=Path, required=True)
    language.add_argument("--corpus", type=Path, required=True)
    language.add_argument("--plan", type=Path)
    language.add_argument("--subset", choices=("quick", "full"), required=True)
    language.add_argument("--output-gate", choices=("pass", "not-performed"), required=True)
    language.add_argument("--started-at", required=True)
    language.add_argument("--finished-at")
    language.add_argument("--label", default="")
    language.add_argument("--design-fixture-digest")
    language.add_argument("--defer-record", action="store_true")

    overhead = subparsers.add_parser(
        "telemetry-overhead",
        help="reject schema-v2 publication of the local-only rotated parity lane",
    )
    add_snapshot(overhead)
    overhead.add_argument("--verdict", type=Path, required=True)

    profile = subparsers.add_parser("profile", help="publish a validated Instruments capture")
    add_engine(profile)
    profile.add_argument("--trace", type=Path, required=True)
    profile.add_argument("--toc", type=Path, required=True)
    profile.add_argument("--template", required=True)
    profile.add_argument("--duration", type=float, required=True)
    profile.add_argument("--target-process", required=True)
    profile.add_argument("--target-pid", type=int)
    profile.add_argument("--profile-kind", choices=("cpu", "memory"), default="cpu")
    profile.add_argument(
        "--retention-policy", choices=("summaryOnly", "keptExplicitly"),
        default="summaryOnly",
    )
    profile.add_argument("--summary-artifact", type=Path)

    ios_profile = subparsers.add_parser("ios-profile", help="publish a validated physical-iPhone Instruments capture")
    add_snapshot(ios_profile)
    ios_profile.add_argument("--run-id", required=True)
    ios_profile.add_argument("--sentinel", type=Path, required=True)
    ios_profile.add_argument("--diagnostics", type=Path, required=True)
    ios_profile.add_argument("--crash-diagnostics", type=Path)
    ios_profile.add_argument("--label", default="")
    ios_profile.add_argument("--trace", type=Path, required=True)
    ios_profile.add_argument("--toc", type=Path, required=True)
    ios_profile.add_argument("--template", required=True)
    ios_profile.add_argument("--duration", type=float, required=True)
    ios_profile.add_argument("--target-process", required=True)
    ios_profile.add_argument("--target-pid", type=int)
    ios_profile.add_argument("--profile-kind", choices=("cpu", "memory"), default="cpu")
    ios_profile.add_argument(
        "--retention-policy", choices=("summaryOnly", "keptExplicitly"),
        default="summaryOnly",
    )
    ios_profile.add_argument("--summary-artifact", type=Path)
    ios_profile.add_argument("--defer-record", action="store_true")

    prosody = subparsers.add_parser("prosody", help="publish a successful calibration corpus")
    add_snapshot(prosody)
    prosody.add_argument("--results", type=Path, required=True)
    prosody.add_argument("--profile", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "snapshot":
            capture_snapshot(args.output, args.crash_scope, args.crash_diagnostics)
            print(args.output)
        elif args.command == "engine":
            print(engine_command(args))
        elif args.command == "memory-qualification":
            print(engine_command(args, kind="memory-qualification"))
        elif args.command == "ios-engine":
            print(ios_engine_command(args))
        elif args.command == "language":
            print(language_command(args))
        elif args.command == "telemetry-overhead":
            print(telemetry_overhead_command(args))
        elif args.command == "profile":
            print(profile_command(args))
        elif args.command == "ios-profile":
            print(ios_profile_command(args))
        elif args.command == "prosody":
            print(prosody_command(args))
        return 0
    except (PublicationError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"benchmark publication: FAIL: {error}", file=sys.stderr)
        if args.command != "snapshot" and "repair:" not in str(error):
            print(f"repair: {shlex.join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
