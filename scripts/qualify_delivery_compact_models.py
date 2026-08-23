#!/usr/bin/env python3
"""Run two serial, cache-cold compact evaluator probes on the canonical host."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

from delivery_analysis_cache import DeliveryAnalysisCache, atomic_json, digest, file_sha256
from delivery_compact_model_adapter import run_compact_adapter


SCHEMA_VERSION = 1


class QualificationError(ValueError):
    """A live compact-model qualification run is incomplete or unclean."""


def _required_command_output(command: list[str], label: str) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise QualificationError(f"cannot attest canonical host {label}")
    return value


def canonical_hardware_attestation() -> dict[str, Any]:
    profiles_path = Path(__file__).resolve().parents[1] / "benchmarks/hardware-profiles.json"
    profiles = _read(profiles_path).get("profiles")
    matches = [
        profile for profile in profiles or []
        if isinstance(profile, dict)
        and profile.get("platform") == "macos"
        and profile.get("canonical") is True
    ]
    if len(matches) != 1:
        raise QualificationError("canonical macOS hardware profile is missing or ambiguous")
    profile = matches[0]
    model = _required_command_output(["/usr/sbin/sysctl", "-n", "hw.model"], "model")
    memory_text = _required_command_output(
        ["/usr/sbin/sysctl", "-n", "hw.memsize"], "physical memory"
    )
    try:
        memory_bytes = int(memory_text)
    except ValueError as error:
        raise QualificationError("canonical host memory evidence is invalid") from error
    if model != profile.get("modelIdentifier") or memory_bytes != profile.get("memoryBytes"):
        raise QualificationError("live host does not match the canonical delivery-evaluator profile")
    return {
        "profileID": profile.get("id"),
        "modelIdentifier": model,
        "memoryBytes": memory_bytes,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationError(f"cannot read {path.name}") from error
    if not isinstance(value, dict):
        raise QualificationError(f"{path.name} must contain an object")
    return value


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = payload["outputs"]
    if payload["adapterID"] == "sensevoice-small-q8":
        transcript = str(outputs["transcript"]).encode("utf-8")
        return {
            "languageTag": outputs["languageTag"],
            "emotionTag": outputs["emotionTag"],
            "eventTag": outputs["eventTag"],
            "textNormalizationTag": outputs["textNormalizationTag"],
            "transcriptSHA256": hashlib.sha256(transcript).hexdigest(),
            "transcriptByteCount": len(transcript),
        }
    embedding = outputs.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise QualificationError("DistilHuBERT did not emit an embedding")
    values = [float(value) for value in embedding]
    if any(not math.isfinite(value) for value in values):
        raise QualificationError("DistilHuBERT embedding is non-finite")
    return {
        "embeddingDimensions": len(values),
        "embeddingSHA256": digest(values),
        "embeddingNorm": math.sqrt(sum(value * value for value in values)),
        "projectionVersion": outputs.get("projectionVersion"),
        "frameCount": outputs.get("frameCount"),
    }


def qualify(
    *, config_path: Path, audio_paths: list[Path], output_root: Path,
    hardware_attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hardware = hardware_attestation or canonical_hardware_attestation()
    if (
        not isinstance(hardware.get("profileID"), str)
        or not isinstance(hardware.get("modelIdentifier"), str)
        or isinstance(hardware.get("memoryBytes"), bool)
        or not isinstance(hardware.get("memoryBytes"), int)
    ):
        raise QualificationError("hardware attestation is incomplete")
    config = _read(config_path)
    if len(audio_paths) != 2:
        raise QualificationError("qualification requires exactly two audio probes")
    audio_digests = [file_sha256(path) for path in audio_paths]
    if len(set(audio_digests)) != 2:
        raise QualificationError("qualification audio probes must be byte-distinct")
    cache = DeliveryAnalysisCache(output_root / "analysis-cache")
    runs = []
    for index, (audio, audio_sha) in enumerate(zip(audio_paths, audio_digests), start=1):
        payload, cache_hit = run_compact_adapter(
            wav_path=audio, config=config, cache=cache,
            lock_root=output_root / "supervisor",
            return_unqualified=True,
        )
        if cache_hit:
            raise QualificationError("qualification unexpectedly reused a compact-model cache entry")
        envelope = payload["resourceEnvelope"]
        runs.append({
            "run": index,
            "audioSHA256": audio_sha,
            "output": _summary(payload),
            "resourceEnvelope": envelope,
        })
        if envelope.get("qualified") is not True:
            break
    qualification_failures = [
        f"run-{row['run']}:" + ",".join(row["resourceEnvelope"].get("qualificationFailures", []))
        for row in runs if row["resourceEnvelope"].get("qualified") is not True
    ]
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-compact-model-live-qualification",
        "promotionAuthority": False,
        "qualifierSHA256": file_sha256(Path(__file__).resolve()),
        "hardware": hardware,
        "adapterID": config["adapterID"],
        "modelProvenance": {
            key: config[key] for key in (
                "modelID", "sourceRevision", "weightsSHA256", "binarySHA256",
                "adapterSourceSHA256", "runtimeDependenciesDigest", "labelMapDigest",
                "preprocessingConfigDigest", "adapterLayerSHA256",
                "resourceSupervisorSHA256",
            )
        },
        "configSHA256": file_sha256(config_path),
        "runs": runs,
        "serialRunCount": len(runs),
        "qualificationFailures": qualification_failures,
        "qualifiedForHoldoutBakeoff": len(runs) == 2 and not qualification_failures,
        "adopted": False,
    }
    report["reportDigest"] = digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--audio", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = qualify(
            config_path=args.config, audio_paths=args.audio,
            output_root=args.output_root,
        )
        atomic_json(args.output_root / "qualification.json", report)
        print(json.dumps({
            "adapterID": report["adapterID"],
            "qualifiedForHoldoutBakeoff": report["qualifiedForHoldoutBakeoff"],
            "reportDigest": report["reportDigest"],
            "serialRunCount": report["serialRunCount"],
        }, sort_keys=True))
        return 0 if report["qualifiedForHoldoutBakeoff"] else 2
    except (QualificationError, ValueError) as error:
        print(f"Delivery compact model qualification: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
