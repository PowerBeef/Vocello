#!/usr/bin/env python3
"""Pinned subprocess adapter for compact local delivery representations.

No external checkpoint is selected or acquired here. A caller must provide a
fully pinned, commercially compatible configuration of a registered judge
(`config/audio-qc-judges.json`); each adapter names its registry judge in
`ADAPTER_JUDGES`, and the registry's load-time gate (`require_loadable`) runs
before every launch. SenseVoiceSmall Q8 is the permitted research candidate and
whisper-small MLX the recognizer; neither is adopted until the separate
untouched-holdout and two-clean-canonical-host-run gates pass. DistilHuBERT was
retired from every QC path on 2026-09-26 (AQ-05): it transcribes nothing and
fed only the uncalibrated heads.

`run_compact_adapter_batch` analyzes a run's clips in one persistent worker
(`audio_qc_worker.py`, audit AQ-F42); `run_compact_adapter` launches one
process for one clip and remains for the two cold qualification probes. Both
fix the judge's declared thread count in the worker's environment and key the
cache on it and on the worker host's source digest, so either path reuses the
other's entries. The batch path's worker timeout scales with its clips (a
start-up allowance plus the caller's per-clip `timeout_seconds`), and it caches
only rows from a qualified launch: a row kept from a worker that later crashed
is returned for this run, never cached. Both paths re-check the cache before
launching and adopt an entry another run stored first.

Identity v4 (audit AQ-F47) splits what a run produced from how it was
supervised. The output identity (model, weights, runtime binary and
dependencies, adapter and adapter-layer source, the repository-relative command
template, label map, output format, preprocessing and, until cross-host
determinism is measured, the host) lives in the preprocessing digest, so it
keys the cache and any calibration. The adapter source the template names is
hashed again before every run, so an edited source is refused rather than
served from the cache. The envelope identity (the resource supervisor's source
and probe) is provenance recorded with each run; a supervisor-only change
neither refuses a prepared configuration nor misses a cache entry.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Sequence
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
from lib.qc_pipeline.layered_cache import store_or_adopt
from audio_qc_judges import JudgeRegistryError, host_profile, load_registry, require_loadable
from audio_qc_worker import thread_environment
from delivery_resource_supervisor import SupervisedResult, run_supervised
import delivery_resource_supervisor


SCHEMA_VERSION = 1
# Each permitted adapter and the registry judge it loads.
ADAPTER_JUDGES = {
    "sensevoice-small-q8": "compact.sensevoice-small-q8@1",
    "whisper-small-mlx": "asr.whisper-small@1",
}
PERMITTED_ADAPTERS = tuple(ADAPTER_JUDGES)
# Adapters whose runtime allocates on the GPU through MLX; their supervised
# envelope measures physical footprint by default.
MLX_ADAPTERS = frozenset({"whisper-small-mlx"})
# Only v4 executes; every older configuration is prepared again.
EXECUTION_IDENTITY_VERSION = 4
RETIRED_IDENTITY_VERSIONS = {
    1: "binds no output identity",
    2: "binds the resource supervisor into the cache key",
    3: "binds neither its command template nor its host",
}
# Every field that can change what an adapter emits; bound into the
# preprocessing digest, which keys the cache, with the normalized command
# template and the host.
OUTPUT_IDENTITY_FIELDS = (
    "adapterSourceSHA256", "adapterLayerSHA256", "runtimeDependenciesDigest",
    "labelMapDigest", "outputFormat",
)
REPOSITORY = Path(__file__).resolve().parents[1]
ADAPTER_LAYER_SOURCE = Path(__file__).resolve()
SUPERVISOR_SOURCE = Path(delivery_resource_supervisor.__file__).resolve()
WORKER_HOST = REPOSITORY / "scripts/audio_qc_worker.py"
# The worker engine each adapter runs under the persistent worker host.
ADAPTER_ENGINES = {"sensevoice-small-q8": "native-command", "whisper-small-mlx": "whisper-mlx"}
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


def normalized_command_template(command: list[str]) -> list[str]:
    """The command template with repository paths made relative, the same on every checkout."""
    normalized = []
    for item in command:
        path = Path(item)
        if path.is_absolute():
            try:
                item = "{repository}/" + path.resolve().relative_to(REPOSITORY).as_posix()
            except ValueError:
                pass
        normalized.append(item)
    return normalized


def named_source(command: list[str]) -> Path | None:
    """The adapter source file a command template runs (a Python file), or None for a native binary."""
    sources = [
        item for item in command
        if "{" not in item and not item.startswith("-") and item.endswith(".py")
    ]
    if len(sources) > 1:
        raise CompactAdapterError("compact adapter commandTemplate names more than one source file")
    if not sources:
        return None
    source = Path(sources[0])
    if not source.is_absolute():
        raise CompactAdapterError("compact adapter commandTemplate names its source by absolute path")
    return source


def _output_identity(config: dict[str, Any]) -> dict[str, Any]:
    return {
        **{field: config[field] for field in OUTPUT_IDENTITY_FIELDS},
        "commandTemplate": normalized_command_template(config["commandTemplate"]),
        "hostProfile": config["hostProfile"],
    }


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
    """Bind a configuration's output identity into its preprocessing digest (identity v4).

    The configuration must already carry every `OUTPUT_IDENTITY_FIELDS` value
    and its command template; binding records this host. Returns a new
    configuration; the supervisor never enters it.
    """
    bound = dict(config)
    bound["hostProfile"] = host_profile()
    preprocessing = dict(bound.get("preprocessingConfig") or {})
    preprocessing.pop("executionIdentity", None)
    preprocessing["outputIdentity"] = _output_identity(bound)
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
    for field in ("modelID", "sourceRevision", "license", "trainingDataDeclaration"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise CompactAdapterError(f"compact adapter requires {field}")
    dependencies = config.get("runtimeDependencies")
    try:
        # The registry's load-time gate: an unregistered, retired, quarantined,
        # tier-C or unknown-tier judge, an excluded model or package, or another
        # repository or revision never launches, whatever the config says.
        require_loadable(
            ADAPTER_JUDGES[adapter_id], config["modelID"], config["sourceRevision"],
            packages=list(dependencies) if isinstance(dependencies, dict) else (),
        )
    except JudgeRegistryError as error:
        raise CompactAdapterError(str(error)) from None
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
    if type(identity_version) is not int or identity_version != EXECUTION_IDENTITY_VERSION:
        known = type(identity_version) is int and identity_version in RETIRED_IDENTITY_VERSIONS
        reason = RETIRED_IDENTITY_VERSIONS[identity_version] if known else "is unsupported"
        raise CompactAdapterError(
            f"compact adapter execution identity v{identity_version} {reason}; "
            f"prepare the configuration again (identity v{EXECUTION_IDENTITY_VERSION})"
        )
    for field in ("sourceURI", "trainingDataSourceURI"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise CompactAdapterError(f"compact adapter requires {field}")
    if config.get("outputFormat") not in {"json", "sensevoice-tagged-text", "whisper-json"}:
        raise CompactAdapterError("compact adapter output format is unsupported")
    label_map = config.get("labelMap")
    if not isinstance(label_map, dict) or digest(label_map) != label_digest:
        raise CompactAdapterError("compact adapter label map drifted")
    if not isinstance(dependencies, dict) or digest(dependencies) != _sha(
        config.get("runtimeDependenciesDigest"), "runtimeDependenciesDigest"
    ):
        raise CompactAdapterError("compact adapter runtime dependency identity drifted")
    # The source the template runs is hashed again before every run: an edit
    # is a refusal, never a stale cache hit. A native runtime is its binary.
    source = named_source(command)
    if source is not None and not source.is_file():
        raise CompactAdapterError("compact adapter source named by the command template is missing")
    current_source = file_sha256(source) if source is not None else config["binarySHA256"]
    if _sha(config.get("adapterSourceSHA256"), "adapterSourceSHA256") != current_source:
        raise CompactAdapterError("compact adapter source drifted; prepare the configuration again")
    if _sha(config.get("adapterLayerSHA256"), "adapterLayerSHA256") != file_sha256(ADAPTER_LAYER_SOURCE):
        raise CompactAdapterError("compact adapter layer source drifted")
    if config.get("hostProfile") != host_profile():
        raise CompactAdapterError("compact adapter configuration was prepared on another host; prepare it here")
    if "executionIdentity" in preprocessing or "resourceSupervisorSHA256" in config:
        raise CompactAdapterError("the resource supervisor is envelope identity, never output identity")
    if preprocessing.get("outputIdentity") != _output_identity(config):
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
        raise CompactAdapterError("compact adapter output format is not recognized")
    for field in required:
        if field not in payload:
            raise CompactAdapterError(f"compact adapter output lacks {field}")
    # Paths, raw bytes and non-finite values are rejected again by the cache.
    return payload


def adapter_threads(adapter_id: str, registry: dict[str, Any] | None = None) -> int:
    """The thread count the registry declares for an adapter's judge (output identity)."""
    registry = registry if registry is not None else load_registry()
    judge = (registry.get("judges") or {}).get(ADAPTER_JUDGES.get(adapter_id, ""))
    threads = ((judge or {}).get("execution") or {}).get("threads")
    if type(threads) is not int or threads <= 0:
        raise CompactAdapterError(f"the judge registry declares no thread count for {adapter_id}")
    return threads


def compact_layer_identity(canonical: CanonicalAudio, config: dict[str, Any], threads: int) -> LayerIdentity:
    """The cache key of one clip's compact output: the output identity, the thread count and the worker host.

    The worker host (`audio_qc_worker.py`) writes the canonical WAV the native
    binary reads and parses what it prints, so its source is output identity.
    """
    return LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id="compact-speech-representation",
        layer_version=str(config["executionIdentityVersion"]),
        binary_sha256=config["binarySHA256"],
        model_id=config["modelID"],
        model_revision=config["sourceRevision"],
        weights_sha256=config["weightsSHA256"],
        preprocessing_config_digest=digest({
            "preprocessingConfigDigest": config["preprocessingConfigDigest"], "threads": threads,
            "workerHostSHA256": file_sha256(WORKER_HOST),
        }),
    )


def _payload(config: dict[str, Any], output: dict[str, Any], envelope_report: dict[str, Any],
             envelope: dict[str, str], threads: int) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "compact-delivery-representation",
        "promotionAuthority": False,
        "adapterID": config["adapterID"],
        "outputs": output,
        "resourceEnvelope": envelope_report,
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
            "threads": threads,
            # The supervisor that ran this measurement: provenance of the
            # cached result, never part of its key.
            "envelopeIdentity": envelope,
            "executionIdentityVersion": config["executionIdentityVersion"],
            "outputFormat": config.get("outputFormat", "json"),
            "offlineAfterAcquisition": True,
            "adopted": False,
        },
    }


def _render(config: dict[str, Any], *, audio: str) -> list[str]:
    substitutions = {"binary": str(config["binaryPath"]), "audio": audio, "weights": str(config["weightsPath"])}
    command = []
    for item in config["commandTemplate"]:
        rendered = item
        for name, value in substitutions.items():
            rendered = rendered.replace("{" + name + "}", value)
        command.append(rendered)
    return command


def run_compact_adapter(
    *, wav_path: Path, config: dict[str, Any], cache: DeliveryAnalysisCache,
    lock_root: Path | None = None,
    supervisor: Callable[..., SupervisedResult] = run_supervised,
    supervisor_options: dict[str, Any] | None = None,
    return_unqualified: bool = False,
) -> tuple[dict[str, Any], bool]:
    """One process for one clip: the two cold qualification probes use it."""
    config = validate_adapter_config(config)
    if cache.resampler_version != configured_resampler(config):
        raise CompactAdapterError("cache resampler differs from pinned model preprocessing")
    threads = adapter_threads(config["adapterID"])
    canonical = cache.canonicalize(wav_path)
    identity = compact_layer_identity(canonical, config, threads)
    retained = cache.load(identity)
    if retained is not None:
        return retained, True
    envelope = envelope_identity()
    with tempfile.TemporaryDirectory(prefix="vocello-compact-adapter-") as temporary:
        model_input = Path(temporary) / "canonical.wav"
        _canonical_wav(canonical, model_input)
        command = _render(config, audio=str(model_input))
        environment = dict(os.environ)
        environment.update({"VOCELLO_DELIVERY_ADAPTER_DEVICE": "cpu", **thread_environment(threads)})
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
    payload = _payload(config, output, result.report, envelope, threads)
    if result.report.get("qualified"):
        try:
            stored, adopted = store_or_adopt(cache, identity, payload)
        except AnalysisCacheError as error:
            raise CompactAdapterError(str(error)) from error
        if adopted:
            return stored, True
    return payload, False


# Options the persistent-worker runner sets itself from the registry. A
# caller's `timeout_seconds` is the per-clip budget (as on the one-clip path);
# the runner scales each launch's timeout from it.
_RUNNER_OWNED_OPTIONS = frozenset({
    "timeout_seconds", "maximum_rss_bytes", "maximum_physical_footprint_bytes",
    "measure_physical_footprint", "environment", "admission", "recovery_rule", "lock_root",
})


def run_compact_adapter_batch(
    *, wav_paths: Sequence[Path], config: dict[str, Any], cache: DeliveryAnalysisCache,
    lock_root: Path | None = None,
    supervisor: Callable[..., SupervisedResult] = run_supervised,
    supervisor_options: dict[str, Any] | None = None,
    run_admission: Any | None = None,
    recovery_rule: str = delivery_resource_supervisor.WHOLE_HOST_RECOVERY_RULE,
    registry: dict[str, Any] | None = None,
) -> dict[Path, tuple[dict[str, Any], bool]]:
    """Every clip's compact output from one persistent worker for the run (AQ-F42).

    Cache hits launch nothing; clips with byte-identical canonical audio share
    one row. The worker runs under the judge's registry ceiling and thread
    count, admitted when `run_admission` is given (the orchestrator) or under
    the exclusive host lock otherwise, with a timeout of a start-up allowance
    plus the per-clip `timeout_seconds` of `supervisor_options` for each clip.
    Rows from a qualified launch are cached before any unavailable row is
    reported, so a rerun resumes rather than repeats; a row kept from a launch
    that ended abnormally is returned for this run and never cached.
    """
    from lib.qc_pipeline.admission import AdmissionError, judge_admission as admission_for, judge_ceiling
    from lib.qc_pipeline.workers import DEFAULT_ROW_TIMEOUT_SECONDS, WorkerSpec, run_persistent_worker

    config = validate_adapter_config(config)
    if cache.resampler_version != configured_resampler(config):
        raise CompactAdapterError("cache resampler differs from pinned model preprocessing")
    registry = registry if registry is not None else load_registry()
    adapter_id = config["adapterID"]
    judge_id = ADAPTER_JUDGES[adapter_id]
    threads = adapter_threads(adapter_id, registry)
    judge = registry["judges"][judge_id]
    try:
        ceiling = judge_ceiling(judge)[0]
    except AdmissionError as error:
        raise CompactAdapterError(f"{judge_id}: {error}") from None
    results: dict[Path, tuple[dict[str, Any], bool]] = {}
    pending: dict[str, tuple[LayerIdentity, CanonicalAudio, list[Path]]] = {}
    for path in wav_paths:
        canonical = cache.canonicalize(path)
        identity = compact_layer_identity(canonical, config, threads)
        retained = cache.load(identity)
        if retained is not None:
            results[path] = (retained, True)
            continue
        pending.setdefault(identity.key, (identity, canonical, []))[2].append(path)
    if not pending:
        return results
    engine = ADAPTER_ENGINES[adapter_id]
    if engine == "native-command":
        command: tuple[str, ...] = (sys.executable, str(WORKER_HOST))
        engine_config: dict[str, Any] = {"command": _render(config, audio="{audio}"), "ceilingBytes": ceiling}
        rows = [{"id": key, "pcmPath": str(canonical.derivative_path)} for key, (_i, canonical, _p) in pending.items()]
    else:
        # The single-file whisper mode: default decode options, no locked language.
        command = (str(config["binaryPath"]), str(WORKER_HOST))
        engine_config = {"weights": str(config["weightsPath"]), "decodeOptions": {}}
        rows = [{"id": key, "pcmPath": str(canonical.derivative_path), "language": None}
                for key, (_i, canonical, _p) in pending.items()]
    requested = dict(supervisor_options or {})
    row_timeout = requested.get("timeout_seconds", DEFAULT_ROW_TIMEOUT_SECONDS)
    options = {key: value for key, value in requested.items() if key not in _RUNNER_OWNED_OPTIONS}
    try:
        spec = WorkerSpec(
            judge_id=judge_id, engine=engine, command=command, threads=threads,
            lane=str((judge.get("execution") or {}).get("lane")), ceiling_bytes=ceiling,
            engine_config=engine_config, measure_physical_footprint=adapter_id in MLX_ADAPTERS,
            row_timeout_seconds=row_timeout, environment={"VOCELLO_DELIVERY_ADAPTER_DEVICE": "cpu"},
        )
    except ValueError as error:
        raise CompactAdapterError(str(error)) from None

    def adopt(batch: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        # Another run may have stored a clip after this one planned it.
        found = {}
        for row in batch:
            retained = cache.load(pending[str(row["id"])][0])
            if retained is not None:
                found[str(row["id"])] = retained
        return found

    envelope = envelope_identity()
    with tempfile.TemporaryDirectory(prefix="vocello-compact-batch-") as temporary:
        outcome = run_persistent_worker(
            spec, rows, workdir=Path(temporary), lock_root=lock_root,
            run_admission=run_admission,
            judge_admission=admission_for(registry, judge_id) if run_admission is not None else None,
            supervisor=supervisor, recovery_rule=recovery_rule, supervisor_options=options, adopt=adopt,
        )
    missing: list[str] = []
    for key, (identity, _canonical, paths) in pending.items():
        if key in outcome.adopted:
            for path in paths:
                results[path] = (outcome.adopted[key], True)
            continue
        raw = outcome.results.get(key)
        if raw is None:
            missing.append(outcome.unavailable.get(key, "crash"))
            continue
        stdout = raw["stdout"].encode("utf-8") if engine == "native-command" else json.dumps(raw).encode("utf-8")
        output = _parse_output(config, stdout)
        launch = outcome.launches[outcome.row_launch[key] - 1]
        payload = _payload(config, output, launch["resourceEnvelope"], envelope, threads)
        hit = False
        if launch["resourceEnvelope"].get("qualified") is True:
            try:
                payload, hit = store_or_adopt(cache, identity, payload)
            except AnalysisCacheError as error:
                raise CompactAdapterError(str(error)) from error
        for path in paths:
            results[path] = (payload, hit)
    if missing:
        raise CompactAdapterError(
            f"compact adapter worker left {len(missing)} clip(s) unavailable: " + ",".join(sorted(set(missing)))
        )
    return results
