#!/usr/bin/env python3
"""Pinned subprocess adapter for compact local delivery representations.

No external checkpoint is selected or acquired here. A caller must provide a
fully pinned, commercially compatible configuration of a registered judge
(`config/audio-qc-judges.json`). SenseVoiceSmall Q8 is the first permitted
candidate; DistilHuBERT is the second. Neither is adopted until the separate
untouched-holdout and two-clean-canonical-host-run gates pass.

Identity v3 (audit AQ-F47) splits what a run produced from how it was
supervised. The output identity (model, weights, runtime binary and
dependencies, adapter and adapter-layer source, label map, output format,
preprocessing) lives in the preprocessing digest, so it keys the cache and any
calibration. The envelope identity (the resource supervisor's source and
probe) is provenance recorded with each run; a supervisor-only change neither
refuses a prepared configuration nor misses a cache entry.
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
    configured_resampler,
)
from audio_qc_judges import JudgeRegistryError, judge_for_adapter, require_executable
from delivery_resource_supervisor import SupervisedResult, run_supervised
import delivery_resource_supervisor


SCHEMA_VERSION = 1
PERMITTED_ADAPTERS = ("sensevoice-small-q8", "distilhubert", "whisper-small-mlx")
# Adapters whose runtime allocates on the GPU through MLX; their supervised
# envelope measures physical footprint by default.
MLX_ADAPTERS = frozenset({"whisper-small-mlx"})
# 1: historical, unbound. 2 bound the resource supervisor into the output
# identity, so a supervisor fix invalidated every prepared config and cache
# entry; it is refused and must be prepared again. 3: output and envelope split.
EXECUTION_IDENTITY_VERSION = 3
SUPERVISOR_BOUND_IDENTITY_VERSION = 2
# Every field that can change what an adapter emits; bound into the
# preprocessing digest, which keys the cache.
OUTPUT_IDENTITY_FIELDS = (
    "adapterSourceSHA256", "adapterLayerSHA256", "runtimeDependenciesDigest",
    "labelMapDigest", "outputFormat",
)
ADAPTER_LAYER_SOURCE = Path(__file__).resolve()
SUPERVISOR_SOURCE = Path(delivery_resource_supervisor.__file__).resolve()
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


def envelope_identity() -> dict[str, str]:
    """How a run is supervised. Provenance only: never part of a cache key."""
    return {
        "resourceSupervisorSHA256": file_sha256(SUPERVISOR_SOURCE),
        "probeAlgorithmVersion": delivery_resource_supervisor.PROBE_ALGORITHM_VERSION,
    }


def output_identity_digest(config: dict[str, Any]) -> str:
    """The digest that keys caches and calibration records for one adapter configuration."""
    return digest({
        field: config.get(field) for field in (
            "adapterID", "modelID", "sourceRevision", "weightsSHA256", "binarySHA256",
            "preprocessingConfigDigest", "decodeOptions",
        )
    })


def bind_output_identity(config: dict[str, Any]) -> dict[str, Any]:
    """Bind a configuration's output identity into its preprocessing digest (identity v3).

    The configuration must already carry every `OUTPUT_IDENTITY_FIELDS` value.
    Returns a new configuration; the supervisor never enters it.
    """
    bound = dict(config)
    preprocessing = dict(bound.get("preprocessingConfig") or {})
    preprocessing.pop("executionIdentity", None)
    preprocessing["outputIdentity"] = {field: bound[field] for field in OUTPUT_IDENTITY_FIELDS}
    bound["preprocessingConfig"] = preprocessing
    bound["preprocessingConfigDigest"] = digest(preprocessing)
    bound["executionIdentityVersion"] = EXECUTION_IDENTITY_VERSION
    bound.pop("resourceSupervisorSHA256", None)
    bound["outputIdentityDigest"] = output_identity_digest(bound)
    return bound


def validate_adapter_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA_VERSION:
        raise CompactAdapterError("compact adapter schemaVersion must be 1")
    adapter_id = config.get("adapterID")
    if adapter_id not in PERMITTED_ADAPTERS:
        raise CompactAdapterError("compact adapter is not in the contract candidate order")
    try:
        # The registry is the execution gate: a retired, quarantined, tier-C or
        # unknown-tier judge never launches, whatever its prepared config says.
        require_executable(*judge_for_adapter(adapter_id))
    except JudgeRegistryError as error:
        raise CompactAdapterError(str(error)) from None
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
    configured_resampler(config)
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
    if identity_version == SUPERVISOR_BOUND_IDENTITY_VERSION:
        raise CompactAdapterError(
            "compact adapter execution identity v2 binds the resource supervisor into the cache key; "
            "prepare the configuration again (identity v3)"
        )
    if identity_version not in (1, EXECUTION_IDENTITY_VERSION):
        raise CompactAdapterError("compact adapter execution identity version is unsupported")
    if identity_version == EXECUTION_IDENTITY_VERSION:
        for field in ("sourceURI", "trainingDataSourceURI"):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise CompactAdapterError(f"v3 compact adapter requires {field}")
        if config.get("outputFormat") not in {"json", "sensevoice-tagged-text", "whisper-json"}:
            raise CompactAdapterError("v3 compact adapter output format is unsupported")
        label_map = config.get("labelMap")
        if not isinstance(label_map, dict) or digest(label_map) != label_digest:
            raise CompactAdapterError("compact adapter label map drifted")
        dependencies = config.get("runtimeDependencies")
        if not isinstance(dependencies, dict) or digest(dependencies) != _sha(
            config.get("runtimeDependenciesDigest"), "runtimeDependenciesDigest"
        ):
            raise CompactAdapterError("compact adapter runtime dependency identity drifted")
        _sha(config.get("adapterSourceSHA256"), "adapterSourceSHA256")
        if _sha(config.get("adapterLayerSHA256"), "adapterLayerSHA256") != file_sha256(ADAPTER_LAYER_SOURCE):
            raise CompactAdapterError("compact adapter layer source drifted")
        if "executionIdentity" in preprocessing or "resourceSupervisorSHA256" in config:
            raise CompactAdapterError("the resource supervisor is envelope identity, never output identity")
        expected = {field: config[field] for field in OUTPUT_IDENTITY_FIELDS}
        if preprocessing.get("outputIdentity") != expected:
            raise CompactAdapterError("compact adapter preprocessing does not bind its output identity")
        if _sha(config.get("outputIdentityDigest"), "outputIdentityDigest") != output_identity_digest(config):
            raise CompactAdapterError("compact adapter output identity digest drifted")
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
    elif config["adapterID"] == "whisper-small-mlx":
        required = ("transcript", "language", "detectedLanguage", "segments")
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
    if cache.resampler_version != configured_resampler(config):
        raise CompactAdapterError("cache resampler differs from pinned model preprocessing")
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
    envelope = envelope_identity()
    with tempfile.TemporaryDirectory(prefix="vocello-compact-adapter-") as temporary:
        model_input = Path(temporary) / "canonical.wav"
        _canonical_wav(canonical, model_input)
        substitutions = {
            "binary": str(config["binaryPath"]),
            "audio": str(model_input),
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
        if config["adapterID"] in MLX_ADAPTERS:
            # MLX allocates Metal memory that RSS cannot see (audit #101).
            options.setdefault("measure_physical_footprint", True)
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
            "outputIdentityDigest": config.get("outputIdentityDigest"),
            # The supervisor that ran this measurement: provenance of the
            # cached result, never part of its key.
            "envelopeIdentity": envelope,
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
