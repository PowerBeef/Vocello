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
import re
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
import delivery_resource_supervisor


SCHEMA_VERSION = 1
PERMITTED_ADAPTERS = ("sensevoice-small-q8", "distilhubert")
EXECUTION_IDENTITY_VERSION = 2
SENSEVOICE_OUTPUT = re.compile(
    r"^<\|(?P<language>[^|]+)\|><\|(?P<emotion>[^|]+)\|>"
    r"<\|(?P<event>[^|]+)\|><\|(?P<textnorm>[^|]+)\|>(?P<transcript>.*)$",
    re.DOTALL,
)


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
    identity_version = config.get("executionIdentityVersion", 1)
    if identity_version not in (1, EXECUTION_IDENTITY_VERSION):
        raise CompactAdapterError("compact adapter execution identity version is unsupported")
    if identity_version == EXECUTION_IDENTITY_VERSION:
        for field in ("sourceURI", "trainingDataSourceURI"):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise CompactAdapterError(f"v2 compact adapter requires {field}")
        output_format = config.get("outputFormat")
        if output_format not in {"json", "sensevoice-tagged-text"}:
            raise CompactAdapterError("v2 compact adapter output format is unsupported")
        label_map = config.get("labelMap")
        if not isinstance(label_map, dict) or digest(label_map) != label_digest:
            raise CompactAdapterError("compact adapter label map drifted")
        dependencies = config.get("runtimeDependencies")
        if not isinstance(dependencies, dict) or digest(dependencies) != _sha(
            config.get("runtimeDependenciesDigest"), "runtimeDependenciesDigest"
        ):
            raise CompactAdapterError("compact adapter runtime dependency identity drifted")
        source_digest = _sha(config.get("adapterSourceSHA256"), "adapterSourceSHA256")
        layer_digest = _sha(config.get("adapterLayerSHA256"), "adapterLayerSHA256")
        supervisor_digest = _sha(
            config.get("resourceSupervisorSHA256"), "resourceSupervisorSHA256"
        )
        if layer_digest != file_sha256(Path(__file__)):
            raise CompactAdapterError("compact adapter layer source drifted")
        if supervisor_digest != file_sha256(Path(delivery_resource_supervisor.__file__)):
            raise CompactAdapterError("compact adapter supervisor source drifted")
        bound = preprocessing.get("executionIdentity")
        expected = {
            "adapterSourceSHA256": source_digest,
            "adapterLayerSHA256": layer_digest,
            "resourceSupervisorSHA256": supervisor_digest,
            "runtimeDependenciesDigest": config["runtimeDependenciesDigest"],
            "labelMapDigest": label_digest,
            "outputFormat": output_format,
        }
        if bound != expected:
            raise CompactAdapterError("compact adapter preprocessing does not bind execution identity")
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
    if config.get("outputFormat") == "sensevoice-tagged-text":
        try:
            text = output.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise CompactAdapterError("SenseVoice output is not UTF-8") from error
        match = SENSEVOICE_OUTPUT.fullmatch(text)
        if match is None:
            raise CompactAdapterError("SenseVoice output lacks the four governed tags")
        payload = {
            "transcript": match.group("transcript").strip(),
            "languageTag": match.group("language"),
            "emotionTag": match.group("emotion"),
            "eventTag": match.group("event"),
            "textNormalizationTag": match.group("textnorm"),
        }
        label_map = config.get("labelMap", {})
        for field, key in (
            ("languageTag", "languages"), ("emotionTag", "emotions"),
            ("eventTag", "events"), ("textNormalizationTag", "textNormalization"),
        ):
            allowed = label_map.get(key, [])
            if not isinstance(allowed, list) or payload[field] not in allowed:
                raise CompactAdapterError(f"SenseVoice emitted undeclared {field}")
        return payload
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
    return_unqualified: bool = False,
) -> tuple[dict[str, Any], bool]:
    config = validate_adapter_config(config)
    canonical = cache.canonicalize(wav_path)
    identity = LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id="compact-speech-representation",
        layer_version=str(config.get("executionIdentityVersion", 1)),
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
    if not result.report.get("qualified") and not return_unqualified:
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
            "sourceURI": config.get("sourceURI"),
            "trainingDataSourceURI": config.get("trainingDataSourceURI"),
            "labelMapDigest": config["labelMapDigest"],
            "preprocessingConfigDigest": config["preprocessingConfigDigest"],
            "runtimeDependenciesDigest": config.get("runtimeDependenciesDigest"),
            "adapterSourceSHA256": config.get("adapterSourceSHA256"),
            "adapterLayerSHA256": config.get("adapterLayerSHA256"),
            "resourceSupervisorSHA256": config.get("resourceSupervisorSHA256"),
            "executionIdentityVersion": config.get("executionIdentityVersion", 1),
            "outputFormat": config.get("outputFormat", "json"),
            "offlineAfterAcquisition": True,
            "adopted": False,
        },
    }
    if result.report.get("qualified"):
        try:
            cache.store(identity, payload)
        except AnalysisCacheError as error:
            raise CompactAdapterError(str(error)) from error
    return payload, False
