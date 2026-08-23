#!/usr/bin/env python3
"""Pinned subprocess adapter for compact local delivery representations.

No external checkpoint is selected or acquired here. A caller must provide a
fully pinned, commercially compatible configuration. SenseVoiceSmall Q8 is the
first permitted candidate; DistilHuBERT is the second. Neither is adopted until
the separate untouched-human-holdout and two-run resource gates pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
import wave

from delivery_analysis_cache import (
    AnalysisCacheError,
    CanonicalAudio,
    DeliveryAnalysisCache,
    LayerIdentity,
    digest,
    file_sha256,
)
from delivery_resource_supervisor import SupervisedResult, run_supervised


SCHEMA_VERSION = 1
PERMITTED_ADAPTERS = ("sensevoice-small-q8", "distilhubert")


class CompactAdapterError(ValueError):
    """An external adapter is unpinned, unsafe, invalid, or unqualified."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise CompactAdapterError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_adapter_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA_VERSION:
        raise CompactAdapterError("compact adapter schemaVersion must be 1")
    adapter_id = config.get("adapterID")
    if adapter_id not in PERMITTED_ADAPTERS:
        raise CompactAdapterError("compact adapter is not in the contract candidate order")
    for field in ("modelID", "sourceRevision", "license", "trainingDataDeclaration"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise CompactAdapterError(f"compact adapter requires {field}")
    if config.get("commercialUseCompatible") is not True:
        raise CompactAdapterError("compact adapter license is not commercially compatible")
    if config.get("offlineAfterAcquisition") is not True:
        raise CompactAdapterError("compact adapter must be offline after acquisition")
    binary = Path(str(config.get("binaryPath", "")))
    weights = Path(str(config.get("weightsPath", "")))
    if not binary.is_file() or not weights.is_file():
        raise CompactAdapterError("compact adapter binary and weights must exist locally")
    if file_sha256(binary) != _sha(config.get("binarySHA256"), "binarySHA256"):
        raise CompactAdapterError("compact adapter binary digest mismatch")
    if file_sha256(weights) != _sha(config.get("weightsSHA256"), "weightsSHA256"):
        raise CompactAdapterError("compact adapter weights digest mismatch")
    label_digest = _sha(config.get("labelMapDigest"), "labelMapDigest")
    preprocessing = config.get("preprocessingConfig")
    if not isinstance(preprocessing, dict) or digest(preprocessing) != _sha(
        config.get("preprocessingConfigDigest"), "preprocessingConfigDigest"
    ):
        raise CompactAdapterError("compact adapter preprocessing configuration drifted")
    command = config.get("commandTemplate")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        raise CompactAdapterError("compact adapter commandTemplate must be a string array")
    flattened = "\n".join(command)
    if "{binary}" not in flattened or "{audio}" not in flattened or "{weights}" not in flattened:
        raise CompactAdapterError("compact adapter command must bind binary, audio, and weights")
    if any(token in flattened for token in ("{preset}", "{requestedLabel}", "{targetDelivery}")):
        raise CompactAdapterError("requested labels may not enter compact feature extraction")
    if adapter_id == "sensevoice-small-q8" and "q8" not in config["modelID"].lower():
        raise CompactAdapterError("SenseVoice first candidate must identify a Q8 artifact")
    _ = label_digest
    return config


def _canonical_wav(canonical: CanonicalAudio, destination: Path) -> None:
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        with canonical.derivative_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                output.writeframesraw(block)


def _parse_output(config: dict[str, Any], output: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompactAdapterError("compact adapter did not emit one JSON object") from error
    if not isinstance(payload, dict):
        raise CompactAdapterError("compact adapter output must be an object")
    if config["adapterID"] == "sensevoice-small-q8":
        required = ("transcript", "languageTag", "emotionTag", "eventTag")
    else:
        required = ("embedding",)
    for field in required:
        if field not in payload:
            raise CompactAdapterError(f"compact adapter output lacks {field}")
    # Paths, raw bytes and non-finite values are rejected again by the cache.
    return payload


def run_compact_adapter(
    *, wav_path: Path, config: dict[str, Any], cache: DeliveryAnalysisCache,
    lock_root: Path,
    supervisor: Callable[..., SupervisedResult] = run_supervised,
    supervisor_options: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    config = validate_adapter_config(config)
    canonical = cache.canonicalize(wav_path)
    identity = LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id="compact-speech-representation",
        layer_version="1",
        binary_sha256=config["binarySHA256"],
        model_id=config["modelID"],
        model_revision=config["sourceRevision"],
        weights_sha256=config["weightsSHA256"],
        preprocessing_config_digest=config["preprocessingConfigDigest"],
    )
    retained = cache.load(identity)
    if retained is not None:
        return retained, True
    with tempfile.TemporaryDirectory(prefix="vocello-compact-adapter-") as temporary:
        canonical_wav = Path(temporary) / "canonical.wav"
        _canonical_wav(canonical, canonical_wav)
        substitutions = {
            "binary": str(config["binaryPath"]),
            "audio": str(canonical_wav),
            "weights": str(config["weightsPath"]),
        }
        command = []
        for item in config["commandTemplate"]:
            rendered = item
            for name, value in substitutions.items():
                rendered = rendered.replace("{" + name + "}", value)
            command.append(rendered)
        environment = dict(os.environ)
        environment.update({"VOCELLO_DELIVERY_ADAPTER_DEVICE": "cpu"})
        options = dict(supervisor_options or {})
        result = supervisor(
            command, lock_root=lock_root, environment=environment, **options
        )
    if not result.report.get("qualified"):
        raise CompactAdapterError(
            "compact adapter resource envelope is unqualified: "
            + ",".join(result.report.get("qualificationFailures", []))
        )
    output = _parse_output(config, result.stdout)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "compact-delivery-representation",
        "promotionAuthority": False,
        "adapterID": config["adapterID"],
        "outputs": output,
        "resourceEnvelope": result.report,
        "modelProvenance": {
            "modelID": config["modelID"],
            "sourceRevision": config["sourceRevision"],
            "weightsSHA256": config["weightsSHA256"],
            "binarySHA256": config["binarySHA256"],
            "license": config["license"],
            "trainingDataDeclaration": config["trainingDataDeclaration"],
            "labelMapDigest": config["labelMapDigest"],
            "preprocessingConfigDigest": config["preprocessingConfigDigest"],
            "offlineAfterAcquisition": True,
            "adopted": False,
        },
    }
    try:
        cache.store(identity, payload)
    except AnalysisCacheError as error:
        raise CompactAdapterError(str(error)) from error
    return payload, False
