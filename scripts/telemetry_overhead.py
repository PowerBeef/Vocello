#!/usr/bin/env python3
"""Matched seeded telemetry overhead/parity lane for vocello bench."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import wave


ROOT = Path(__file__).resolve().parents[1]
DEBUG_ROOT = Path.home() / "Library" / "Application Support" / "QwenVoice-Debug"
MODES = ("off", "lightweight", "verbose")
TELEMETRY_SCHEMA_VERSION = 8
MODEL_ID = "pro_custom_speed"
ROTATIONS = (
    ("off", "lightweight", "verbose"),
    ("lightweight", "verbose", "off"),
    ("verbose", "off", "lightweight"),
)

MODEL_RUNTIME_IDENTITY_FIELDS = (
    "resolvedModelID",
    "modelRepository",
    "huggingFaceRevision",
    "artifactVersion",
    "quantization",
    "integrityManifestDigest",
    "runtimeProfileSignature",
)
OPTIONAL_MODEL_RUNTIME_IDENTITY_FIELDS = (
    "nativeLoadCapabilityProfile",
    "fixtureDigest",
)


def build_policy_environment() -> dict[str, str]:
    """Load validated repository-owned build paths without duplicating the manifest."""
    helper = ROOT / "scripts" / "build_output_policy.py"
    completed = subprocess.run(
        [sys.executable, str(helper), "shell-env"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"could not load build-output policy: {detail}")

    environment: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        fields = shlex.split(line)
        if len(fields) != 2 or fields[0] != "export" or "=" not in fields[1]:
            raise RuntimeError("build-output policy emitted malformed shell environment")
        name, value = fields[1].split("=", 1)
        environment[name] = value
    return environment


def managed_output_path(variable: str) -> Path:
    environment = build_policy_environment()
    raw_path = environment.get(variable)
    if not raw_path:
        raise RuntimeError(f"build-output policy did not define {variable}")
    path = Path(raw_path)
    try:
        path.relative_to(ROOT / "build")
    except ValueError as error:
        raise RuntimeError(f"build-output policy path escapes the build root: {path}") from error
    return path


def pcm_digest(path: Path) -> str:
    try:
        with wave.open(str(path), "rb") as stream:
            frames = stream.getnframes()
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            sample_rate = stream.getframerate()
            if frames <= 0 or channels <= 0 or sample_width <= 0 or sample_rate <= 0:
                raise RuntimeError(f"measured WAV has empty or invalid PCM: {path}")
            payload = stream.readframes(frames)
    except (OSError, wave.Error) as error:
        raise RuntimeError(f"measured WAV is unreadable: {path}: {error}") from error
    expected_bytes = frames * channels * sample_width
    if not payload or len(payload) != expected_bytes:
        raise RuntimeError(f"measured WAV has incomplete PCM: {path}")
    return hashlib.sha256(payload).hexdigest()


def throughput_regression(candidate: float, baseline: float) -> float:
    """Positive when higher-is-better throughput (e.g. a speedup) regresses."""
    return 0.0 if baseline <= 0 else (1.0 - (candidate / baseline)) * 100.0


def latency_regression(candidate: float, baseline: float) -> float:
    """Positive when lower-is-better latency regresses."""
    return 0.0 if baseline <= 0 else ((candidate / baseline) - 1.0) * 100.0


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def machine_context() -> dict:
    """Low-cost, privacy-safe load/thermal context around one measured process."""
    load_average = list(os.getloadavg())
    free_storage = shutil.disk_usage(ROOT).free
    uptime = time.monotonic()
    thermal: dict[str, int] = {}
    completed = subprocess.run(
        ["pmset", "-g", "therm"], text=True, capture_output=True, check=False
    )
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, raw = (part.strip() for part in line.split("=", 1))
        normalized = "".join(character for character in key if character.isalnum())
        try:
            thermal[normalized] = int(raw)
        except ValueError:
            continue
    thermal_state = "nominal" if "No thermal warning level has been recorded" in completed.stdout else "unknown"
    speed_limits = [value for key, value in thermal.items() if key.lower().endswith("limit")]
    if speed_limits:
        minimum_limit = min(speed_limits)
        thermal_state = "critical" if minimum_limit < 50 else "serious" if minimum_limit < 80 else "fair" if minimum_limit < 100 else "nominal"
    low_power = False
    power = subprocess.run(["pmset", "-g", "custom"], text=True, capture_output=True, check=False)
    for line in power.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() == "lowpowermode":
            low_power = fields[-1] == "1"
            break
    return {
        "capturedAt": utc_now(),
        "loadAverage": load_average,
        "freeStorageBytes": free_storage,
        "uptimeSeconds": uptime,
        "lowPowerMode": low_power,
        "thermalState": thermal_state,
        "thermal": thermal,
    }


def load_bench_results(data_dir: Path) -> dict:
    path = data_dir / "diagnostics" / "bench-results.json"
    if not path.is_file():
        raise RuntimeError(f"bench results are missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read bench results: {error}") from error
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("takes"), list):
        raise RuntimeError("bench results use an unsupported schema")
    return payload


def _require_lower_hex(value: object, *, length: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"telemetry has invalid {field}")
    return value


def _normalized_model_runtime_identity(row: dict, *, generation_id: str) -> dict:
    if row.get("schemaVersion") != TELEMETRY_SCHEMA_VERSION:
        raise RuntimeError(
            f"generation {generation_id} is not schema-v{TELEMETRY_SCHEMA_VERSION} telemetry"
        )
    if row.get("layer") != "engine" or row.get("modelID") != MODEL_ID:
        raise RuntimeError(f"generation {generation_id} has the wrong engine model identity")
    identity = row.get("modelRuntimeIdentity")
    if not isinstance(identity, dict):
        raise RuntimeError(f"generation {generation_id} lacks modelRuntimeIdentity")
    normalized: dict[str, str] = {}
    for field in MODEL_RUNTIME_IDENTITY_FIELDS:
        value = identity.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"generation {generation_id} lacks modelRuntimeIdentity.{field}")
        normalized[field] = value
    if normalized["resolvedModelID"] != MODEL_ID:
        raise RuntimeError(f"generation {generation_id} resolved the wrong model")
    if normalized["quantization"] not in {"4-bit", "8-bit", "unquantized"}:
        raise RuntimeError(f"generation {generation_id} has invalid model quantization")
    _require_lower_hex(
        normalized["huggingFaceRevision"], length=40, field="huggingFaceRevision"
    )
    _require_lower_hex(
        normalized["integrityManifestDigest"], length=64, field="integrityManifestDigest"
    )
    for field in OPTIONAL_MODEL_RUNTIME_IDENTITY_FIELDS:
        value = identity.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"generation {generation_id} has invalid modelRuntimeIdentity.{field}")
        if field == "fixtureDigest":
            _require_lower_hex(value, length=64, field="fixtureDigest")
        normalized[field] = value
    return normalized


def load_model_runtime_identity(
    data_dir: Path, generation_ids: list[str], *, run_id: str
) -> dict:
    """Load one exact typed identity for measured enabled-telemetry generations."""
    if (
        not generation_ids
        or any(not generation_id for generation_id in generation_ids)
        or len(set(generation_ids)) != len(generation_ids)
    ):
        raise RuntimeError("measured generation IDs must be unique and non-empty")
    path = data_dir / "diagnostics" / "engine" / "generations.jsonl"
    if not path.is_file():
        raise RuntimeError(f"engine telemetry is missing: {path}")
    expected = set(generation_ids)
    selected: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"cannot read engine telemetry: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"engine telemetry line {line_number} is invalid JSON: {error}"
            ) from error
        if not isinstance(row, dict) or row.get("generationID") not in expected:
            continue
        generation_id = str(row["generationID"])
        if generation_id in selected:
            raise RuntimeError(f"generation {generation_id} has duplicate engine telemetry rows")
        notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
        if notes.get("benchRunID") != run_id:
            raise RuntimeError(f"generation {generation_id} belongs to another benchmark run")
        selected[generation_id] = _normalized_model_runtime_identity(
            row, generation_id=generation_id
        )
    missing = [generation_id for generation_id in generation_ids if generation_id not in selected]
    if missing:
        raise RuntimeError(
            f"engine telemetry is missing {len(missing)} measured generation row(s)"
        )
    identities = [selected[generation_id] for generation_id in generation_ids]
    first = identities[0]
    if any(identity != first for identity in identities[1:]):
        raise RuntimeError("measured generations do not share one exact modelRuntimeIdentity")
    return first


def run_lane(args: argparse.Namespace) -> dict:
    started_at = utc_now()
    nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
    run_id = "telemetry-overhead-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S") + f"-{nonce}"
    run_dir = managed_output_path("QVOICE_ARTIFACTS_MACOS") / "telemetry-overhead" / run_id
    run_dir.mkdir(parents=True)
    snapshot = run_dir / "benchmark-source.json"
    snapshot_command = [
        sys.executable, str(ROOT / "scripts" / "publish_benchmark_history.py"),
        "snapshot", "--output", str(snapshot), "--crash-scope", "macos",
    ]
    captured = subprocess.run(snapshot_command, cwd=ROOT, text=True, capture_output=True)
    if captured.returncode:
        raise RuntimeError(
            "could not capture pre-run source provenance: "
            + (captured.stderr.strip() or captured.stdout.strip())
        )
    source_models = DEBUG_ROOT / "models"
    if not source_models.exists():
        raise RuntimeError(f"debug model root is missing: {source_models}")
    vocello = managed_output_path("QVOICE_BUILD_ROOT") / "vocello"

    results: dict[str, dict] = {mode: {"samples": [], "pcmSHA256": {}} for mode in MODES}
    contexts: list[dict] = []
    observed_model_identities: list[dict] = []
    for rotation_index, rotation in enumerate(ROTATIONS, start=1):
        for order_index, mode in enumerate(rotation, start=1):
            data_dir = run_dir / f"rotation-{rotation_index}-{order_index}-{mode}"
            data_dir.mkdir()
            (data_dir / "models").symlink_to(source_models.resolve(), target_is_directory=True)
            subrun_id = f"{run_id}-r{rotation_index}-{mode}"
            before = machine_context()
            command = [
                str(vocello), "bench",
                "--modes", "custom", "--variants", "speed", "--lengths", "medium",
                "--warm", "3", "--seed", str(args.seed), "--run-id", subrun_id,
                "--telemetry", mode, "--data-dir", str(data_dir), "--no-summary",
            ]
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            after = machine_context()
            log_stem = f"rotation-{rotation_index}-{order_index}-{mode}"
            (run_dir / f"{log_stem}.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / f"{log_stem}.stderr.log").write_text(completed.stderr, encoding="utf-8")
            contexts.append({
                "rotation": rotation_index, "order": order_index, "mode": mode,
                "before": before, "after": after,
            })
            if completed.returncode:
                raise RuntimeError(f"{mode} bench failed in rotation {rotation_index} with exit {completed.returncode}")

            manifest = load_bench_results(data_dir)
            warm_takes = [
                take for take in manifest["takes"]
                if take.get("warmState") == "warm" and take.get("delivery") is None
            ]
            if len(warm_takes) != 3:
                raise RuntimeError(
                    f"{mode} rotation {rotation_index} produced {len(warm_takes)} warm takes, expected 3"
                )
            measured = warm_takes[1:]
            if mode != "off":
                observed_model_identities.append(load_model_runtime_identity(
                    data_dir,
                    [str(take.get("generationID", "")) for take in measured],
                    run_id=subrun_id,
                ))
            output_dir = data_dir / "outputs" / "bench"
            for measured_index, take in enumerate(measured, start=1):
                audio = float(take["audioSeconds"])
                wall = float(take["wallSeconds"])
                ttfc = take.get("firstChunkMS")
                if audio <= 0 or wall <= 0 or not isinstance(ttfc, (int, float)):
                    raise RuntimeError(f"{mode} rotation {rotation_index} has invalid machine-readable timing")
                sample = {
                    "rotation": rotation_index,
                    "modeOrder": order_index,
                    "measuredTake": measured_index,
                    "generationID": take["generationID"],
                    "audioSeconds": audio,
                    "wallSeconds": wall,
                    # Standard RTF: wall ÷ audio, lower is faster (bench wall
                    # time on the CLI's monotonic clock).
                    "rtf": wall / audio,
                    "ttfcMS": float(ttfc),
                    "environment": take.get("environment"),
                }
                environment = sample["environment"]
                required_environment = {
                    "loadAverage1Minute", "freeStorageBytes", "uptimeSeconds",
                    "lowPowerModeEnabled", "thermalState",
                }
                if not isinstance(environment, dict) or not required_environment.issubset(environment):
                    raise RuntimeError(
                        f"{mode} rotation {rotation_index} lacks per-take environment context"
                    )
                results[mode]["samples"].append(sample)
                output_path = output_dir / take["outputFileName"]
                if not output_path.is_file():
                    raise RuntimeError(f"missing measured WAV: {output_path}")
                results[mode]["pcmSHA256"][f"r{rotation_index}-t{measured_index}"] = pcm_digest(output_path)

    for mode in MODES:
        samples = results[mode]["samples"]
        if len(samples) != 6:
            raise RuntimeError(f"{mode} produced {len(samples)} measured takes, expected 6")
        results[mode]["medianRTF"] = statistics.median(sample["rtf"] for sample in samples)
        results[mode]["medianTTFCMS"] = statistics.median(sample["ttfcMS"] for sample in samples)

    if len(observed_model_identities) != len(ROTATIONS) * 2:
        raise RuntimeError("enabled telemetry did not provide every measured model identity")
    model_runtime_identity = observed_model_identities[0]
    if any(identity != model_runtime_identity for identity in observed_model_identities[1:]):
        raise RuntimeError("telemetry modes do not share one exact modelRuntimeIdentity")

    baseline = results["off"]
    thresholds = {"lightweight": 5.0, "verbose": 10.0}
    failures = []
    parity = all(results[mode]["pcmSHA256"] == baseline["pcmSHA256"] for mode in MODES[1:])
    if not parity:
        failures.append("seeded PCM differs across telemetry modes")
    for mode, limit in thresholds.items():
        # RTF is lower-is-better, so it regresses like a latency.
        results[mode]["rtfRegressionPercent"] = latency_regression(
            results[mode]["medianRTF"], baseline["medianRTF"]
        )
        results[mode]["ttfcRegressionPercent"] = latency_regression(
            results[mode]["medianTTFCMS"], baseline["medianTTFCMS"]
        )
        if results[mode]["rtfRegressionPercent"] > limit:
            failures.append(f"{mode} median RTF regression exceeds {limit:.0f}%")
        if results[mode]["ttfcRegressionPercent"] > limit:
            failures.append(f"{mode} median TTFC regression exceeds {limit:.0f}%")

    verdict = {
        "schemaVersion": 2,
        "runID": run_id,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "status": "pass" if not failures else "fail",
        "attestationSummary": {
            "seed": args.seed,
            "rotationCount": len(ROTATIONS),
            "measuredWarmTakesPerMode": 6,
            "pcmParity": parity,
            "thresholdsPercent": thresholds,
            "modes": {
                mode: {
                    key: results[mode][key]
                    for key in (
                        "medianRTF", "medianTTFCMS", "rtfRegressionPercent",
                        "ttfcRegressionPercent",
                    )
                    if key in results[mode]
                }
                for mode in MODES
            },
        },
        "summary": {
            "seed": args.seed,
            "telemetrySchemaVersion": TELEMETRY_SCHEMA_VERSION,
            "modelID": MODEL_ID,
            "modelRuntimeIdentity": model_runtime_identity,
            "warmupTakesPerModePerRotation": 1,
            "measuredWarmTakesPerModePerRotation": 2,
            "measuredWarmTakesPerMode": 6,
            "modeOrderRotations": ROTATIONS,
            "pcmParity": parity,
            "thresholdsPercent": thresholds,
            "results": results,
            "machineContext": contexts,
            "failures": failures,
        },
    }
    verdict_path = run_dir / "verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    if failures:
        raise RuntimeError("; ".join(failures))

    # This diagnostic intentionally compares telemetry-off with enabled modes.
    # Instrumenting the off lane with the in-process v8 memory sampler would
    # change the observer whose overhead is being measured.  Keep the complete
    # verdict local instead of publishing a memory-incomplete schema-v2 history
    # record.  A future external observer may make this lane publishable without
    # changing the experiment, but absence of such evidence must fail closed.
    print(verdict_path)
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1_264_849_675)
    args = parser.parse_args()
    try:
        run_lane(args)
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
