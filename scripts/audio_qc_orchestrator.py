#!/usr/bin/env python3
"""The audio QC orchestrator: Stages 1-3 after the generator exits (AQ-05).

One orchestrator (audit section 3.1) runs the evidence stages for a manifest
of takes and loads no model itself:

- **L0.** Every take's WAV is bound to its digest and canonicalized once
  (16 kHz mono PCM16, `polyphase-kaiser5-v2`).
- **Stage 1 (DSP, in-process).** For the delivery lane: canonical PCM
  integrity, the prosody analyzer and the temporal contours, each cached as L1
  under its source digest and declared thread count. L0 and Stage 1 hold a
  dsp slot of the admission ledger, which counts against the host's one-worker
  cap while the whole-host recovery rule binds.
- **Stage 2 (workers).** Each requested neural judge (the whisper-small
  recognizer, optionally SenseVoice) runs in **one persistent worker per run**
  (`audio_qc_worker.py`), admitted by the budgeted semaphore of
  `config/audio-qc-judges.json#admission` (decision 9a) under the shared host
  lock of the one host-wide analysis lock root, with the judge's registry
  ceiling enforced live by the supervisor on the worker's process group. Each
  launch's timeout is a start-up allowance plus a per-row budget
  (`--timeout-seconds`, per row). Rows already in L1 launch nothing; rows
  another run stored after this one planned them are adopted after admission,
  and each judge's rows are stored as soon as its worker finishes. A judge
  never admitted in time leaves its takes `unavailable` (`admission-timeout`)
  without discarding the other judges' results.
- **L2.** Each raw output is reduced to its metrics (for a recognizer: the
  edit operations and rates of `score_recognition`, without verdicts or
  thresholds), keyed by the L1 key, the metric definition and the digest of
  every source that shapes it (a declared list per judge).
- **Stage 3 (never cached).** The current verdicts are replayed from L2: the
  language lane's witness verdict (`independent_asr.witness_verdict`) and the
  delivery lane's automated review and route (`run_local_delivery_cascade`),
  with each recognition scored from its L2 metrics. Beside them the pure
  composer emits one detector verdict per channel, each naming its judges and
  calibration record, and the lane's take verdict.
- **Stage 4.** A take-evidence record per take (digests and metrics only) and
  the untracked private bundle (`lib.qc_pipeline.evidence`).

Commands:
  manifest         build an orchestrator manifest from an independent-ASR
                   manifest (language lane) or a delivery cascade input
  run              run Stages 1-3 and write the private bundle
  replay           recompute Stage 3 from the cache (no model runs) and compare
                   it with a bundle's records
  validate-bundle  re-hash and re-validate a private bundle
  admission-status the host's admission ledger and policy

The host lock and the admission ledger always live under the host-wide
analysis lock root (`delivery_resource_supervisor.host_analysis_lock_root`),
never under the cache root, so every orchestrator, generator and analyzer on
the host contends on one lock and one budget.
"""

from __future__ import annotations

import os

if __name__ == "__main__":
    # In-process Stage 1 runs with its declared single numerical thread, fixed
    # before NumPy loads (workers get theirs from the launcher's environment).
    for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[_name] = "1"

import argparse
import concurrent.futures
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import numpy as np  # noqa: E402

from audio_qc_judges import JudgeRegistryError, load_registry  # noqa: E402
from delivery_analysis_cache import (  # noqa: E402
    NO_MODEL_DIGEST,
    SUPPORTED_RESAMPLERS,
    CanonicalAudio,
    DeliveryAnalysisCache,
    atomic_json,
    canonicalization_identity,
    digest,
    file_sha256,
    select_resampler,
)
from delivery_resource_supervisor import run_supervised  # noqa: E402
import independent_asr  # noqa: E402
from lib.language_metrics import (  # noqa: E402
    INDEPENDENT_ASR_ALGORITHM,
    LANGUAGE_LOCALE_CODES,
    is_sha256,
    recognition_issues,
    text_sha256,
)
from lib.qc_pipeline.admission import (  # noqa: E402
    AdmissionError,
    AdmissionPolicy,
    AdmissionTimeout,
    HostAdmission,
    judge_admission,
)
from lib.qc_pipeline.evidence import (  # noqa: E402
    PRIVATE_SCHEMA,
    TAKE_EVIDENCE_SCHEMA,
    EvidenceError,
    evidence_digest,
    is_token,
    validate_private_bundle,
    write_private_bundle,
)
from lib.qc_pipeline.layered_cache import (  # noqa: E402
    JudgeIdentity,
    LayeredCache,
    l1_identity,
    l2_identity,
    metric_sources_digest,
    output_identity_digest,
)
from lib.qc_pipeline.verdicts import (  # noqa: E402
    ASR_METRIC_DEFINITION,
    ASR_METRIC_SOURCES,
    SENSEVOICE_METRIC_SOURCES,
    L2Scorer,
    asr_metrics,
    channel_detectors,
    compose_take,
    integrity_detector,
    replay_committed_language_record,
    sensevoice_tag_metrics,
    stage0_detector,
)
from lib.qc_pipeline.workers import (  # noqa: E402
    DEFAULT_ROW_TIMEOUT_SECONDS,
    DEFAULT_STARTUP_SECONDS,
    WorkerOutcome,
    WorkerSpec,
    run_persistent_worker,
)
from prosody_quality_gate import evaluate_metrics  # noqa: E402
import run_local_delivery_cascade as cascade  # noqa: E402

REPO = SCRIPT_DIR.parent
MANIFEST_SCHEMA = "vocello.audioqc.manifest/1"
LANES = ("language-bench", "delivery-bench")
ORCHESTRATOR_SOURCE = Path(__file__).resolve()
WORKER_HOST = SCRIPT_DIR / "audio_qc_worker.py"
REGISTRY_PATH = REPO / "config/audio-qc-judges.json"
POLICY_PATH = REPO / "config/audio-qc-qualification-policy.json"
DEFAULT_CACHE_ROOT = Path(os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"))
DEFAULT_BUNDLE_PARENT = Path(os.environ.get("QVOICE_ARTIFACTS_MACOS", REPO / "build/artifacts/macos")) / "audio-qc"
WHISPER_JUDGE = "asr.whisper-small@1"
SENSEVOICE_JUDGE = "compact.sensevoice-small-q8@1"
INTEGRITY_JUDGE = "integrity.canonical-pcm@1"
PROSODY_JUDGE = "prosody@3"
TEMPORAL_JUDGE = "temporal-contour@1"
DSP_METRIC_DEFINITION = "dsp-feature-vector-v1"
SENSEVOICE_METRIC_DEFINITION = "sensevoice-tags-v1"
ADMISSION_TIMEOUT = "admission-timeout"


class OrchestratorError(ValueError):
    """The manifest, a judge configuration or a run is unusable."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrchestratorError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise OrchestratorError(f"{path.name} must contain an object")
    return value


# --------------------------------------------------------------------------- #
# Manifests
# --------------------------------------------------------------------------- #

def _take(*, take_id: str, generation_id: str, audio: str, audio_sha256: str, language: str,
          reference_text: Any, script_sha256: Any, expected_outcome: str = "pass", role: str | None = None,
          stage0: Any = None, external: Any = None, apple: Any = None, duration: Any = None,
          cell_id: str | None = None) -> dict[str, Any]:
    return {
        "id": take_id, "generationID": generation_id, "cellID": cell_id, "role": role,
        "audioPath": audio, "audioSHA256": audio_sha256, "language": language,
        "referenceText": reference_text if isinstance(reference_text, str) else None,
        "scriptSHA256": script_sha256 if isinstance(script_sha256, str) else None,
        "expectedOutcome": "fail" if expected_outcome == "fail" else "pass",
        "durationSeconds": duration, "stage0": stage0 if isinstance(stage0, dict) else None,
        "externalRecognitions": [item for item in external or [] if isinstance(item, dict)],
        "appleSpeechChannels": apple if isinstance(apple, dict) else None,
    }


def manifest_from_independent_asr(source: dict[str, Any], *, source_sha256: str) -> dict[str, Any]:
    """The language lane: one take per row of an independent-ASR manifest."""
    source = independent_asr.validate_manifest(source)
    takes = [
        _take(
            take_id=row["id"], generation_id=row["generationID"], audio=row["audioPath"],
            audio_sha256=row["audioSHA256"], language=row["expectedLanguage"],
            reference_text=row["referenceText"], script_sha256=row["scriptSHA256"],
            expected_outcome=row.get("expectedOutcome", "pass"), apple=row.get("appleSpeechChannels"),
            duration=row.get("durationSeconds"), cell_id=row.get("cellID"),
        )
        for row in source["rows"]
    ]
    return {
        "schema": MANIFEST_SCHEMA, "runID": str(source.get("runID")), "lane": "language-bench",
        "platform": source.get("platform"), "generationProcessExited": True,
        "source": {"kind": "independent-asr-manifest", "sha256": source_sha256}, "takes": takes, "pairs": [],
    }


def manifest_from_cascade_input(source: dict[str, Any], *, source_sha256: str) -> dict[str, Any]:
    """The delivery lane: an instructed and a neutral take per row of a cascade input."""
    if source.get("kind") != "source-bound-delivery-cascade-input" or source.get("generationProcessExited") is not True:
        raise OrchestratorError("a delivery manifest needs a source-bound cascade input whose generator exited")
    takes, pairs = [], []
    for row in source.get("rows") or []:
        generation = str(row["generationID"])
        evidence = row.get("reviewEvidence") if isinstance(row.get("reviewEvidence"), dict) else {}
        pair = {"id": generation}
        for role, wav, sha in (("instructed", "instructedWAV", "instructedSHA256"),
                               ("neutral", "neutralWAV", "neutralSHA256")):
            role_evidence = evidence.get(role) if isinstance(evidence.get(role), dict) else {}
            take_id = f"{generation}:{role}"
            takes.append(_take(
                take_id=take_id, generation_id=generation, audio=str(row[wav]), audio_sha256=str(row[sha]),
                language=str(row["outputLanguage"]).lower(), reference_text=row.get("referenceText"),
                script_sha256=row.get("scriptSHA256"), role=role, stage0=role_evidence.get("audioQC"),
                external=role_evidence.get("recognitions"),
            ))
            pair[role] = take_id
        pair.update({key: row.get(key) for key in (
            "speakerID", "scriptID", "scriptTranslationGroup", "seed", "outputLanguage", "preset",
        )})
        pairs.append(pair)
    return {
        "schema": MANIFEST_SCHEMA, "runID": str(source.get("executionPlanDigest")), "lane": "delivery-bench",
        "platform": "macos", "generationProcessExited": True,
        "source": {"kind": "delivery-cascade-input", "sha256": source_sha256}, "takes": takes, "pairs": pairs,
    }


def validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise OrchestratorError(f"the manifest is not {MANIFEST_SCHEMA}")
    if manifest.get("lane") not in LANES:
        raise OrchestratorError(f"the manifest lane must be one of {LANES}")
    if manifest.get("generationProcessExited") is not True:
        raise OrchestratorError("the generator must have exited before any evaluator runs")
    takes = manifest.get("takes")
    if not isinstance(takes, list) or not takes:
        raise OrchestratorError("the manifest has no takes")
    seen: set[str] = set()
    for take in takes:
        if not isinstance(take, dict) or not isinstance(take.get("id"), str) or take["id"] in seen:
            raise OrchestratorError("manifest takes need unique string identities")
        seen.add(take["id"])
        if not is_sha256(take.get("audioSHA256")) or not isinstance(take.get("audioPath"), str):
            raise OrchestratorError(f"{take['id']}: audio path and digest are required")
        if take.get("language") not in LANGUAGE_LOCALE_CODES:
            raise OrchestratorError(f"{take['id']}: unsupported language")
        text = take.get("referenceText")
        if text is not None and take.get("scriptSHA256") != text_sha256(text):
            raise OrchestratorError(f"{take['id']}: the script digest does not bind its reference text")
    if manifest["lane"] == "delivery-bench":
        pairs = manifest.get("pairs")
        if not isinstance(pairs, list) or not pairs or any(
            not isinstance(pair, dict) or pair.get("instructed") not in seen or pair.get("neutral") not in seen
            for pair in pairs
        ):
            raise OrchestratorError("a delivery manifest pairs every instructed take with its neutral take")
    return manifest


# --------------------------------------------------------------------------- #
# Judges
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Stage2Judge:
    """One Stage 2 judge as the orchestrator runs it."""

    judge_id: str
    engine: str
    command: tuple[str, ...]
    engine_config: Mapping[str, Any]
    identity: JudgeIdentity
    threads: int
    family: str | None = None
    language_codes: Mapping[str, str] = field(default_factory=dict)
    model_identity_sha256: str = NO_MODEL_DIGEST
    measure_physical_footprint: bool = False
    # A launch's timeout: the start-up allowance plus this budget per row.
    row_timeout_seconds: float = DEFAULT_ROW_TIMEOUT_SECONDS
    startup_seconds: float = DEFAULT_STARTUP_SECONDS
    metric_definition: str = ASR_METRIC_DEFINITION
    # Every source that shapes this judge's L2 value, hashed together into its key.
    metric_sources: tuple[Path, ...] = ASR_METRIC_SOURCES
    # Raw output -> (L2 metrics, private text) for a judge that is not a recognizer.
    reduce: Callable[[dict[str, Any]], tuple[dict[str, Any], str | None]] | None = None

    @property
    def code_to_language(self) -> dict[str, str]:
        return {code: name for name, code in self.language_codes.items()}

    def request(self, take: Mapping[str, Any]) -> dict[str, Any] | None:
        """What the judge is asked for this take; None when it cannot judge it."""
        if self.family is None:
            return {}
        code = self.language_codes.get(take["language"])
        return None if code is None else {"lockedLanguage": code}

    def job_row(self, key: str, canonical: CanonicalAudio, request: Mapping[str, Any]) -> dict[str, Any]:
        row = {"id": key, "pcmPath": str(canonical.derivative_path)}
        if self.family is not None:
            row["language"] = request["lockedLanguage"]
        return row

    def spec(self, ceiling_bytes: int, lane: str) -> WorkerSpec:
        config = dict(self.engine_config)
        if self.engine == "native-command":
            config["ceilingBytes"] = ceiling_bytes
        return WorkerSpec(
            judge_id=self.judge_id, engine=self.engine, command=self.command, threads=self.threads,
            lane=lane, ceiling_bytes=ceiling_bytes, engine_config=config,
            measure_physical_footprint=self.measure_physical_footprint,
            row_timeout_seconds=self.row_timeout_seconds, startup_seconds=self.startup_seconds,
        )


def stage2_judge_from_adapter_config(judge_id: str, config: dict[str, Any], registry: Mapping[str, Any], *,
                                     row_timeout_seconds: float = DEFAULT_ROW_TIMEOUT_SECONDS) -> Stage2Judge:
    """A Stage 2 judge from a prepared, verified adapter configuration (identity v4)."""
    from delivery_compact_model_adapter import (
        ADAPTER_JUDGES, CompactAdapterError, _parse_output, validate_adapter_config,
    )

    try:
        config = validate_adapter_config(config)
    except CompactAdapterError as error:
        raise OrchestratorError(str(error)) from None
    if ADAPTER_JUDGES.get(config["adapterID"]) != judge_id:
        raise OrchestratorError(f"the adapter configuration is not {judge_id}'s")
    admission = judge_admission(registry, judge_id)
    common = {
        "adapterOutputIdentityDigest": config["outputIdentityDigest"],
        "workerHostSHA256": file_sha256(WORKER_HOST),
        "threads": admission.threads,
    }
    if judge_id == WHISPER_JUDGE:
        languages = config["labelMap"].get("languages")
        if not isinstance(languages, dict) or not languages:
            raise OrchestratorError("the whisper configuration lacks its language table")
        output = output_identity_digest(judge_id, {
            **common, "engine": "whisper-mlx", "algorithm": INDEPENDENT_ASR_ALGORITHM,
            "decodeOptions": config.get("decodeOptions"),
        })
        return Stage2Judge(
            judge_id=judge_id, engine="whisper-mlx", command=(str(config["binaryPath"]), str(WORKER_HOST)),
            engine_config={"weights": str(config["weightsPath"]), "decodeOptions": config.get("decodeOptions") or {}},
            identity=JudgeIdentity(judge_id, output, config["modelID"], config["sourceRevision"], config["weightsSHA256"]),
            threads=admission.threads, family="whisper", language_codes=dict(languages),
            model_identity_sha256=digest({key: config[key] for key in (
                "modelID", "sourceRevision", "weightsSHA256", "labelMapDigest")}),
            measure_physical_footprint=True, row_timeout_seconds=row_timeout_seconds,
        )
    if judge_id == SENSEVOICE_JUDGE:
        command = []
        for item in config["commandTemplate"]:
            command.append(item.replace("{binary}", str(config["binaryPath"])).replace("{weights}", str(config["weightsPath"])))
        output = output_identity_digest(judge_id, {**common, "engine": "native-command"})

        def reduce(raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            return sensevoice_tag_metrics(_parse_output(config, str(raw.get("stdout", "")).encode("utf-8")))

        return Stage2Judge(
            judge_id=judge_id, engine="native-command", command=(sys.executable, str(WORKER_HOST)),
            engine_config={"command": command},
            identity=JudgeIdentity(judge_id, output, config["modelID"], config["sourceRevision"], config["weightsSHA256"]),
            threads=admission.threads, metric_definition=SENSEVOICE_METRIC_DEFINITION,
            metric_sources=SENSEVOICE_METRIC_SOURCES, reduce=reduce, row_timeout_seconds=row_timeout_seconds,
        )
    raise OrchestratorError(f"{judge_id} is not a Stage 2 judge the orchestrator runs")


@dataclass(frozen=True)
class Stage1Judge:
    judge_id: str
    layer_version: str
    sources: tuple[Path, ...]
    compute: Callable[[CanonicalAudio, Path], dict[str, Any]]


STAGE1_JUDGES = (
    Stage1Judge(INTEGRITY_JUDGE, "1", (Path(cascade.__file__).resolve(),),
                lambda canonical, _path: cascade._pcm_integrity_layer(canonical)),
    Stage1Judge(PROSODY_JUDGE, "3", (cascade.GLOBAL_ANALYZER,), lambda _canonical, path: cascade._global_layer(path)),
    Stage1Judge(TEMPORAL_JUDGE, "1", (cascade.TEMPORAL_ANALYZER, cascade.GLOBAL_ANALYZER),
                lambda _canonical, path: cascade._temporal_layer(path)),
)


def _stage1_identity(judge: Stage1Judge, threads: int, resampler: str) -> JudgeIdentity:
    return JudgeIdentity(judge.judge_id, output_identity_digest(judge.judge_id, {
        "analyzerSourceSHA256": {source.name: file_sha256(source) for source in judge.sources},
        "cacheSourceSHA256": file_sha256(SCRIPT_DIR / "delivery_analysis_cache.py"),
        "layerVersion": judge.layer_version,
        "numpyVersion": np.__version__,
        "pythonVersion": sys.version,
        "canonicalizationIdentity": canonicalization_identity(resampler),
        "threads": threads,
    }))


# --------------------------------------------------------------------------- #
# Evidence helpers
# --------------------------------------------------------------------------- #

def _flat(value: Any, prefix: str, output: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            _flat(value[key], f"{prefix}.{key}" if prefix else str(key), output)
    elif isinstance(value, (list, tuple)):
        return
    elif isinstance(value, bool) or value is None:
        output[prefix] = value
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not np.isfinite(value):
            return
        output[prefix] = value
    elif isinstance(value, str) and is_token(value):
        output[prefix] = value


def _metrics(value: Any, prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    _flat(value, prefix, output)
    return {key: item for key, item in output.items() if is_token(key)}


# What a recognition measured; its wall time is the measurement's `wallSeconds`
# (provenance of the launch that produced it), never a metric.
RECOGNITION_METRICS = (
    "languageMatchScore", "detectedLanguageProbability", "fullFileProcessed", "processedDurationSeconds",
    "segmentCount", "maximumNoSpeechProbability", "meanAverageLogProbability", "decodeLanguage",
)


def _safe_take_id(take_id: str) -> str:
    """A take's identity in its record and its private file alike."""
    return take_id if is_token(take_id) else digest(take_id)


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #

class Orchestrator:
    def __init__(
        self, *, registry: dict[str, Any], cache: DeliveryAnalysisCache, lock_root: Path | None = None,
        stage2: Sequence[Stage2Judge] = (), host_admission: HostAdmission | None = None,
        supervisor: Callable[..., Any] = run_supervised, supervisor_options: Mapping[str, Any] | None = None,
        offline: bool = False,
    ) -> None:
        self.registry = registry
        self.policy = AdmissionPolicy.from_registry(registry)
        self.layered = LayeredCache(cache)
        # None is the host-wide analysis lock root; only a test names its own.
        self.lock_root = lock_root
        self.stage2 = {judge.judge_id: judge for judge in stage2}
        self.host = host_admission or HostAdmission(lock_root, self.policy)
        self.supervisor = supervisor
        self.supervisor_options = dict(supervisor_options or {})
        # Replay: every Stage 2 row must already be in L1; no model may run.
        self.offline = offline

    # -- Stage 1 ----------------------------------------------------------- #

    def _stage1(self, take: Mapping[str, Any], canonical: CanonicalAudio) -> dict[str, Any]:
        resampler = self.layered.resampler_version
        layers: dict[str, Any] = {}
        states: dict[str, str] = {}
        identities: dict[str, str] = {}
        for judge in STAGE1_JUDGES:
            threads = int(((self.registry["judges"][judge.judge_id].get("execution")) or {}).get("threads", 1))
            judge_identity = _stage1_identity(judge, threads, resampler)
            identities[judge.judge_id] = judge_identity.output_identity
            if judge.judge_id == PROSODY_JUDGE and layers[INTEGRITY_JUDGE].get("status") != "complete":
                layers[judge.judge_id] = {"status": "skipped", "errorCode": "pcm-integrity-rejected"}
                states[judge.judge_id] = "none"
                continue
            if judge.judge_id == TEMPORAL_JUDGE and layers[PROSODY_JUDGE].get("status") != "complete":
                layers[judge.judge_id] = {"status": "skipped", "errorCode": "earlier-deterministic-layer-rejected"}
                states[judge.judge_id] = "none"
                continue
            identity = l1_identity(canonical, judge_identity, {})
            value, hit = self.layered.l1_or_compute(
                identity, lambda judge=judge: judge.compute(canonical, Path(take["audioPath"])),
            )
            layers[judge.judge_id] = value
            states[judge.judge_id] = "hit" if hit else "miss"
        return {"layers": layers, "cache": states, "identities": identities}

    # -- Stage 2 ----------------------------------------------------------- #

    def _run_workers(self, plans: dict[str, dict[str, Any]], run_admission: Any, workdir: Path,
                     accept: Callable[[str, WorkerOutcome], None]) -> dict[str, dict[str, Any]]:
        """Run every judge's worker; `accept` stores each judge's rows as soon as it finishes.

        A judge whose admission times out leaves its rows `unavailable`
        (`admission-timeout`); another judge's failure is raised only after
        every finished judge's rows were stored, so nothing already measured is
        discarded.
        """
        reports: dict[str, dict[str, Any]] = {}

        def adopt_for(judge_id: str) -> Callable[[Sequence[Mapping[str, Any]]], dict[str, dict[str, Any]]]:
            def adopt(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
                found = {}
                for row in rows:
                    value = self.layered.adopt_l1(plans[judge_id][str(row["id"])]["identity"])
                    if value is not None:
                        found[str(row["id"])] = value
                return found
            return adopt

        def launch(judge_id: str) -> WorkerOutcome:
            judge = self.stage2[judge_id]
            admission = judge_admission(self.registry, judge_id)
            rows = [entry["row"] for entry in plans[judge_id].values()]
            return run_persistent_worker(
                judge.spec(admission.ceiling_bytes, admission.lane), rows,
                workdir=workdir / judge_id.replace("@", "-"), lock_root=self.lock_root,
                run_admission=run_admission, judge_admission=admission, supervisor=self.supervisor,
                recovery_rule=self.policy.recovery_rule, supervisor_options=self.supervisor_options,
                adopt=adopt_for(judge_id),
            )

        pending = [judge_id for judge_id, plan in plans.items() if plan]
        if not pending:
            return reports
        failure: BaseException | None = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending)) as pool:
            futures = {pool.submit(launch, judge_id): judge_id for judge_id in pending}
            for future in concurrent.futures.as_completed(futures):
                judge_id = futures[future]
                try:
                    outcome = future.result()
                except AdmissionTimeout:
                    outcome = WorkerOutcome(judge_id, unavailable={key: ADMISSION_TIMEOUT for key in plans[judge_id]})
                except Exception as error:  # noqa: BLE001 - raised once the others are stored
                    failure = failure or error
                    continue
                accept(judge_id, outcome)
                reports[judge_id] = outcome.report()
        if failure is not None:
            raise failure
        return reports

    # -- the run ----------------------------------------------------------- #

    def run(self, manifest: dict[str, Any]) -> dict[str, Any]:
        manifest = validate_manifest(manifest)
        lane = manifest["lane"]
        takes = manifest["takes"]
        with self.host.run() as run_admission:
            # L0 and Stage 1 run in this process. They hold a dsp slot, which
            # counts against the host's one-worker cap while the whole-host
            # recovery rule binds, so no admitted worker's envelope overlaps them.
            with run_admission.stage1():
                canonical: dict[str, CanonicalAudio] = {}
                for take in takes:
                    path = Path(take["audioPath"])
                    if not path.is_file() or file_sha256(path) != take["audioSHA256"]:
                        raise OrchestratorError(f"{take['id']}: audio is missing or its bytes changed")
                    canonical[take["id"]] = self.layered.canonical(path)
                stage1 = {take["id"]: self._stage1(take, canonical[take["id"]]) for take in takes} \
                    if lane == "delivery-bench" else {}
            # Plan Stage 2: an L1 hit launches nothing; identical audio and
            # requests share one worker row.
            l1_keys: dict[str, dict[str, Any]] = {judge_id: {} for judge_id in self.stage2}
            raw: dict[str, dict[str, Any]] = {judge_id: {} for judge_id in self.stage2}
            timings: dict[str, dict[str, float]] = {judge_id: {} for judge_id in self.stage2}
            states: dict[str, dict[str, str]] = {judge_id: {} for judge_id in self.stage2}
            out_of_scope: dict[str, set[str]] = {judge_id: set() for judge_id in self.stage2}
            plans: dict[str, dict[str, Any]] = {judge_id: {} for judge_id in self.stage2}
            for judge_id, judge in self.stage2.items():
                for take in takes:
                    request = judge.request(take)
                    if request is None:
                        out_of_scope[judge_id].add(take["id"])
                        continue
                    identity = l1_identity(canonical[take["id"]], judge.identity, request)
                    l1_keys[judge_id][take["id"]] = (identity, request)
                    cached = self.layered.load_l1(identity)
                    if cached is not None:
                        raw[judge_id][take["id"]] = cached
                        states[judge_id][take["id"]] = "hit"
                        continue
                    states[judge_id][take["id"]] = "miss"
                    entry = plans[judge_id].setdefault(identity.key, {
                        "identity": identity, "takes": [],
                        "row": judge.job_row(identity.key, canonical[take["id"]], request),
                    })
                    entry["takes"].append(take["id"])
            if self.offline and any(plans.values()):
                missing = sorted(judge_id for judge_id, plan in plans.items() if plan)
                raise OrchestratorError(f"replay needs every L1 entry; a model would have to run for {', '.join(missing)}")
            unavailable: dict[str, dict[str, str]] = {judge_id: {} for judge_id in self.stage2}

            def accept(judge_id: str, outcome: WorkerOutcome) -> None:
                """Store one finished judge's rows in L1 (adopting what another run stored first)."""
                for key, entry in plans[judge_id].items():
                    adopted = outcome.adopted.get(key)
                    if adopted is not None:
                        for take_id in entry["takes"]:
                            raw[judge_id][take_id] = adopted
                            states[judge_id][take_id] = "hit"
                        continue
                    result = outcome.results.get(key)
                    if result is None:
                        for take_id in entry["takes"]:
                            unavailable[judge_id][take_id] = outcome.unavailable.get(key, "crash")
                        continue
                    try:
                        stored, _adopted = self.layered.store_l1(entry["identity"], result)
                    except ValueError:
                        for take_id in entry["takes"]:
                            unavailable[judge_id][take_id] = "analysis-failed"
                        continue
                    for take_id in entry["takes"]:
                        raw[judge_id][take_id] = stored
                        if key in outcome.timings:
                            timings[judge_id][take_id] = outcome.timings[key]

            with tempfile.TemporaryDirectory(prefix="vocello-audio-qc-") as temporary:
                workers = self._run_workers(plans, run_admission, Path(temporary), accept)
            return self._compose(manifest, canonical, stage1, raw, l1_keys, states, unavailable, out_of_scope,
                                 workers, timings)

    # -- L2, Stage 3 and Stage 4 -------------------------------------------- #

    def _recognition(self, judge: Stage2Judge, take: Mapping[str, Any], canonical: CanonicalAudio,
                     raw: dict[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
        duration = take.get("durationSeconds")
        row = {
            "audioSHA256": take["audioSHA256"], "scriptSHA256": take.get("scriptSHA256"),
            "expectedLanguage": take["language"],
            "durationSeconds": duration if isinstance(duration, (int, float)) else canonical.duration_seconds,
        }
        provenance = {
            "runtimeSHA256": judge.identity.output_identity,
            "modelIdentitySHA256": judge.model_identity_sha256,
            "configSHA256": digest({"request": dict(request), "threads": judge.threads}),
        }
        recognition = independent_asr._recognition(row, raw, provenance=provenance,
                                                   code_to_language=judge.code_to_language)
        recognition["modelFamily"] = judge.family
        return recognition

    def _compose(self, manifest, canonical, stage1, raw, l1_keys, states, unavailable, out_of_scope, workers,
                 timings):
        lane = manifest["lane"]
        takes = manifest["takes"]
        scorer = L2Scorer()
        registries = {
            "judges": file_sha256(REGISTRY_PATH), "detectors": None, "policy": file_sha256(POLICY_PATH),
        }
        measurements: dict[str, list[dict[str, Any]]] = {take["id"]: [] for take in takes}
        recognitions: dict[str, list[dict[str, Any]]] = {take["id"]: [] for take in takes}
        transcripts: dict[str, dict[str, str]] = {take["id"]: {} for take in takes}
        metric_source = {judge_id: metric_sources_digest(judge.metric_sources) for judge_id, judge in self.stage2.items()}
        for take in takes:
            take_id = take["id"]
            for judge_id, judge in self.stage2.items():
                base = {"judge": judge_id, "outputIdentity": judge.identity.output_identity,
                        "transcriptSHA256": None, "metricsSHA256": None, "wallSeconds": None, "reasons": []}
                if take_id in out_of_scope[judge_id]:
                    measurements[take_id].append({**base, "status": "out-of-scope", "metrics": {},
                                                  "cache": {"l1": "none", "l2": "none"}, "reasons": ["out-of-scope"]})
                    continue
                if take_id not in raw[judge_id]:
                    measurements[take_id].append({**base, "status": "unavailable", "metrics": {},
                                                  "cache": {"l1": states[judge_id].get(take_id, "none"), "l2": "none"},
                                                  "reasons": [unavailable[judge_id].get(take_id, "crash")]})
                    continue
                identity, request = l1_keys[judge_id][take_id]
                value = raw[judge_id][take_id]
                # Timing of this run's launch, never of the cached entry.
                wall = timings[judge_id].get(take_id)
                l2_state = "none"
                if judge.family is not None:
                    recognition = self._recognition(
                        judge, take, canonical[take_id], value if wall is None else {**value, "wallSeconds": wall},
                        request,
                    )
                    recognitions[take_id].append(recognition)
                    transcripts[take_id][judge_id] = recognition["transcript"]
                    metrics: dict[str, Any] = {}
                    script = take.get("referenceText")
                    if isinstance(script, str) and script.strip():
                        l2 = l2_identity(identity, metric_definition=judge.metric_definition,
                                         metric_source_sha256=metric_source[judge_id],
                                         inputs={"scriptSHA256": take["scriptSHA256"], "language": take["language"],
                                                 "family": judge.family})
                        metrics, hit = self.layered.l2_or_compute(
                            l2, lambda: asr_metrics(recognition, script=script, language=take["language"]),
                        )
                        l2_state = "hit" if hit else "miss"
                        scorer.add(recognition, script=script, language=take["language"], metrics=metrics)
                    flat = {**_metrics(metrics), **_metrics({key: recognition.get(key) for key in RECOGNITION_METRICS},
                                                           "recognition")}
                    transcript_sha = hashlib.sha256(recognition["transcript"].encode("utf-8")).hexdigest()
                else:
                    l2 = l2_identity(identity, metric_definition=judge.metric_definition,
                                     metric_source_sha256=metric_source[judge_id], inputs={})
                    reduced: dict[str, Any] = {}

                    def compute(value=value) -> dict[str, Any]:
                        metrics, text = judge.reduce(value) if judge.reduce else ({}, None)
                        reduced["text"] = text
                        return {"metrics": metrics,
                                "transcriptSHA256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None}

                    stored, hit = self.layered.l2_or_compute(l2, compute)
                    l2_state = "hit" if hit else "miss"
                    metrics = stored["metrics"]
                    flat = _metrics(metrics)
                    transcript_sha = stored.get("transcriptSHA256")
                    if judge.reduce is not None:
                        text = reduced.get("text")
                        if text is None:
                            text = judge.reduce(value)[1]
                        if text:
                            transcripts[take_id][judge_id] = text
                measurements[take_id].append({
                    **base, "status": "complete", "metrics": flat, "metricsSHA256": digest(metrics),
                    "transcriptSHA256": transcript_sha,
                    "wallSeconds": wall if isinstance(wall, (int, float)) else None,
                    "cache": {"l1": states[judge_id].get(take_id, "none"), "l2": l2_state},
                })
            for judge in STAGE1_JUDGES:
                if take_id not in stage1:
                    continue
                layer = stage1[take_id]["layers"][judge.judge_id]
                measurements[take_id].append({
                    "judge": judge.judge_id, "outputIdentity": stage1[take_id]["identities"][judge.judge_id],
                    "status": "complete" if layer.get("status") == "complete" else "skipped",
                    "metrics": _metrics(layer), "metricsSHA256": digest(layer), "transcriptSHA256": None,
                    "wallSeconds": None, "reasons": [layer["errorCode"]] if is_token(layer.get("errorCode")) else [],
                    # A DSP judge's raw output is its metric vector: its L2 is its L1.
                    "cache": {"l1": stage1[take_id]["cache"][judge.judge_id], "l2": "none"},
                })
        legacy, run_summary = self._legacy(manifest, canonical, stage1, recognitions, unavailable, scorer)
        records, privates = [], []
        for take in takes:
            take_id = take["id"]
            record = self._evidence(lane, take, canonical[take_id], registries, measurements[take_id],
                                    recognitions[take_id], stage1.get(take_id), unavailable, out_of_scope,
                                    legacy.get(take_id, {}), scorer)
            records.append(record)
            privates.append({
                # The record's take identity, and the manifest's own beside it.
                "schema": PRIVATE_SCHEMA, "takeID": _safe_take_id(take_id), "manifestTakeID": take_id,
                "audioPath": take["audioPath"],
                "referenceText": take.get("referenceText"), "transcripts": transcripts[take_id],
                "externalRecognitionCount": len(take.get("externalRecognitions") or []),
            })
        run_id = manifest["runID"] if is_token(manifest.get("runID")) else digest(manifest.get("runID"))
        header = {
            "runID": run_id, "lane": lane, "manifestSHA256": digest(manifest),
            "registries": registries,
            "orchestratorSHA256": file_sha256(ORCHESTRATOR_SOURCE),
            "workerHostSHA256": file_sha256(WORKER_HOST),
            "admission": self.policy.report(),
            "cache": self.layered.report(),
            "scorer": {"l2Metrics": scorer.cached, "suppliedRecognitionsScored": scorer.computed},
            "workers": [workers[judge_id] for judge_id in sorted(workers)],
            "run": run_summary,
        }
        # `recognitions` is private and in memory only (the replay tests read
        # it); the bundle writer stores the header, records and private files.
        return {"header": header, "records": records, "privates": privates, "recognitions": recognitions}

    def _legacy(self, manifest, canonical, stage1, recognitions, unavailable, scorer):
        """The current verdicts, replayed from L2 metrics."""
        lane = manifest["lane"]
        takes = {take["id"]: take for take in manifest["takes"]}
        legacy: dict[str, dict[str, Any]] = {take_id: {} for take_id in takes}
        if lane == "language-bench":
            own = WHISPER_JUDGE if WHISPER_JUDGE in self.stage2 else None
            rows, cells = [], {}
            for take_id, take in takes.items():
                whisper = [item for item in recognitions[take_id] if item.get("modelFamily") == "whisper"]
                if len(whisper) != 1:
                    reason = unavailable.get(own or "", {}).get(take_id, "missing-verdict")
                    legacy[take_id]["languageWitness"] = {"status": "unavailable", "reasons": [reason]}
                    continue
                row = {key: take[key] for key in ("id", "generationID", "audioPath", "audioSHA256",
                                                   "referenceText", "scriptSHA256")}
                row.update(expectedLanguage=take["language"], expectedOutcome=take["expectedOutcome"],
                           durationSeconds=take["durationSeconds"] if isinstance(take.get("durationSeconds"), (int, float))
                           else canonical[take_id].duration_seconds)
                if take.get("cellID"):
                    row["cellID"] = take["cellID"]
                if take.get("appleSpeechChannels"):
                    row["appleSpeechChannels"] = take["appleSpeechChannels"]
                rows.append(row)
                cells[take_id] = {"recognitions": whisper}
            summary: dict[str, Any] = {"status": "unavailable", "families": [], "rowCount": 0}
            if rows:
                verdict = independent_asr.witness_verdict(
                    {"schemaVersion": 1, "kind": "independent-asr-manifest", "runID": manifest["runID"],
                     "platform": manifest.get("platform") or "macos", "generationProcessExited": True, "rows": rows},
                    {"cells": cells}, scorer=scorer,
                )
                for row in verdict["rows"]:
                    legacy[row["id"]]["languageWitness"] = {key: row[key] for key in (
                        "status", "expectationMet", "families", "channels", "whisperIssues", "whisperErrorRate",
                        "reasons", "expectedOutcome")}
                summary = {key: verdict[key] for key in ("status", "families", "rowCount")}
                if len(rows) != len(takes):
                    summary["status"] = "unavailable"
            summary["unavailableTakes"] = len(takes) - len(rows)
            return legacy, {"languageWitness": summary}
        pairs = []
        for pair in manifest["pairs"]:
            row = {
                "generationID": pair["id"], "outputLanguage": pair.get("outputLanguage") or takes[pair["instructed"]]["language"],
                "referenceText": takes[pair["instructed"]].get("referenceText"),
                "scriptSHA256": takes[pair["instructed"]].get("scriptSHA256"),
                "reviewEvidence": {},
            }
            per_audio, automated, prosody = {}, {}, {}
            for role in cascade.ROLES:
                take = takes[pair[role]]
                row[f"{role}SHA256"] = take["audioSHA256"]
                row["reviewEvidence"][role] = {
                    "audioSHA256": take["audioSHA256"], "audioQC": take.get("stage0"),
                    "recognitions": list(take.get("externalRecognitions") or []) + recognitions[take["id"]],
                }
                layers = stage1[take["id"]]["layers"]
                per_audio[role] = {"qc": layers[INTEGRITY_JUDGE], "global": layers[PROSODY_JUDGE],
                                   "temporal": layers[TEMPORAL_JUDGE]}
            for role in cascade.ROLES:
                take = takes[pair[role]]
                automated[role] = cascade.review_automated_audio(
                    row, role, canonical[take["id"]].duration_seconds, scorer=scorer,
                )
                report = evaluate_metrics(per_audio[role]["global"].get("features", {}))
                report.pop("clip", None)
                prosody[role] = report
            route, reasons = cascade.compose_route(per_audio, automated, prosody)
            pair_id = pair["id"] if is_token(pair["id"]) else digest(pair["id"])
            pairs.append({"pairID": pair_id, "route": route, "reasons": reasons})
            for role in cascade.ROLES:
                review = automated[role]
                legacy[pair[role]] = {
                    "automatedReview": {key: review[key] for key in (
                        "status", "safety", "spokenContent", "reasons", "independentASRFamilies", "policyID",
                        "accuracyMetricVersion")},
                    "prosodyGate": {"status": "pass" if prosody[role].get("passed") else "warn"},
                    "pairRoute": {"status": route, "reasons": reasons, "pairID": pair_id},
                }
        return legacy, {"pairs": pairs, "reviewCounts": {
            route: sum(1 for pair in pairs if pair["route"] == route)
            for route in ("accepted-for-continued-screening", "rejected", "abstained")}}

    def _evidence(self, lane, take, canonical, registries, measurements, recognitions, stage1, unavailable,
                  out_of_scope, legacy, scorer) -> dict[str, Any]:
        take_id = take["id"]
        families: dict[str, list[dict[str, bool]]] = {}
        unqualified: list[str] = []
        script = take.get("referenceText")
        witnesses = list(take.get("externalRecognitions") or []) + recognitions
        for recognition in witnesses:
            issues = recognition_issues(
                recognition, audio_sha256=take["audioSHA256"], script=script, script_sha256=take.get("scriptSHA256"),
                language=take["language"],
                duration_seconds=take["durationSeconds"] if isinstance(take.get("durationSeconds"), (int, float))
                else canonical.duration_seconds,
            )
            family = str(recognition.get("modelFamily"))
            if issues:
                unqualified.append(family)
                continue
            verdict = scorer(recognition, script=script, language=take["language"])
            families.setdefault(family, []).append({"language": verdict["languagePass"], "accuracy": verdict["accuracyPass"]})
        apple = take.get("appleSpeechChannels")
        if isinstance(apple, dict) and all(isinstance(apple.get(key), bool) for key in ("language", "accuracy")):
            families.setdefault("apple-speech", []).append({"language": apple["language"], "accuracy": apple["accuracy"]})
        failed = {judge_id: unavailable[judge_id][take_id] for judge_id in self.stage2
                  if self.stage2[judge_id].family is not None and take_id in unavailable[judge_id]}
        scope = [judge_id for judge_id in self.stage2
                 if self.stage2[judge_id].family is not None and take_id in out_of_scope[judge_id]]
        detectors = [stage0_detector(take.get("stage0"))]
        if stage1 is not None:
            detectors.append(integrity_detector(stage1["layers"][INTEGRITY_JUDGE]))
        detectors.extend(channel_detectors(families, unqualified=unqualified, unavailable=failed, out_of_scope=scope))
        composed = compose_take(lane, detectors)
        receipt = take.get("stage0")
        stage0 = None
        if isinstance(receipt, dict):
            stage0 = {"audioQC": {
                "algorithmVersion": receipt.get("algorithmVersion") if type(receipt.get("algorithmVersion")) is int else None,
                "verdict": receipt.get("verdict") if receipt.get("verdict") in ("pass", "warn", "fail") else None,
                "flags": [flag for flag in receipt.get("flags") or [] if is_token(flag)],
            }}
        return {
            "schema": TAKE_EVIDENCE_SCHEMA,
            "take": {
                "takeID": _safe_take_id(take_id),
                "audioSHA256": take["audioSHA256"],
                "canonicalPCMSHA256": canonical.canonical_derivative_sha256,
                "canonicalSampleRateHz": 16_000,
                "durationSeconds": canonical.duration_seconds,
                "textSHA256": take.get("scriptSHA256"),
                "language": take["language"],
                "role": take.get("role"),
                "expectedOutcome": take["expectedOutcome"],
            },
            "registries": registries,
            "stage0": stage0,
            "measurements": sorted(measurements, key=lambda item: item["judge"]),
            "verdicts": composed["verdicts"],
            "takeVerdict": {key: composed[key] for key in ("lane", "status", "composition", "decidedBy", "reasons")},
            "legacyVerdicts": legacy,
        }


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #

REPLAYED_FIELDS = ("takeVerdict", "verdicts", "legacyVerdicts")


def compare_with_bundle(result: dict[str, Any], bundle: Path) -> dict[str, Any]:
    """Recomputed Stage 3 against a bundle's records, take by take."""
    stored = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    by_take = {}
    for entry in stored.get("takes") or []:
        by_take[entry["takeID"]] = json.loads((bundle / entry["evidence"]).read_text(encoding="utf-8"))
    differences = []
    for record in result["records"]:
        take_id = record["take"]["takeID"]
        previous = by_take.get(take_id)
        if previous is None:
            differences.append({"takeID": take_id, "field": "take", "reason": "not-in-bundle"})
            continue
        for key in REPLAYED_FIELDS:
            if json.dumps(record[key], sort_keys=True) != json.dumps(previous[key], sort_keys=True):
                differences.append({"takeID": take_id, "field": key, "reason": "differs"})
        metrics = {item["judge"]: item.get("metrics") for item in record["measurements"]}
        previous_metrics = {item["judge"]: item.get("metrics") for item in previous["measurements"]}
        if json.dumps(metrics, sort_keys=True) != json.dumps(previous_metrics, sort_keys=True):
            differences.append({"takeID": take_id, "field": "measurements.metrics", "reason": "differs"})
    return {"takes": len(result["records"]), "identical": not differences, "differences": differences,
            "cache": result["header"]["cache"]}


def replay_committed_records(records: Path, matrix: Path) -> dict[str, Any]:
    """Stage 3 over every committed language record, against its recorded verdicts."""
    cells = {str(cell.get("id")): cell for cell in _read(matrix).get("cells") or [] if isinstance(cell, dict)}
    rows = {}
    for path in sorted(records.glob("*.json")):
        rows[path.name] = replay_committed_language_record(_read(path), cells)
    return {
        "records": len(rows),
        "recordsWithMetrics": sum(1 for row in rows.values() if row["takesWithMetrics"]),
        "takesWithMetrics": sum(row["takesWithMetrics"] for row in rows.values()),
        "accuracyReplayed": sum(row["accuracyReplayed"] for row in rows.values()),
        "languageReplayed": sum(row["languageReplayed"] for row in rows.values()),
        "languageFromRecord": sum(row["languageFromRecord"] for row in rows.values()),
        "identical": all(row["identical"] for row in rows.values()),
        "byRecord": rows,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_judge_configs(values: Sequence[str]) -> dict[str, Path]:
    configs = {}
    for value in values:
        judge_id, separator, path = value.partition("=")
        if not separator or not judge_id or not path:
            raise OrchestratorError("--judge-config takes <judge id>=<prepared adapter config>")
        configs[judge_id] = Path(path)
    return configs


def _orchestrator(args: argparse.Namespace, *, offline: bool) -> Orchestrator:
    registry = load_registry()
    configs = _parse_judge_configs(args.judge_config or [])
    judges = []
    resampler = None
    for judge_id, path in configs.items():
        config = _read(path)
        chosen = select_resampler(args.resampler, config)
        if resampler not in (None, chosen):
            raise OrchestratorError("every judge configuration must share one resampler")
        resampler = chosen
        judges.append(stage2_judge_from_adapter_config(judge_id, config, registry,
                                                      row_timeout_seconds=args.timeout_seconds))
    cache = DeliveryAnalysisCache(args.cache_root, resampler_version=resampler or select_resampler(args.resampler))
    # The lock and the ledger are the host's, never the cache root's.
    return Orchestrator(registry=registry, cache=cache, stage2=judges, offline=offline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest", help="build an orchestrator manifest")
    source = manifest.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-independent-asr-manifest", type=Path)
    source.add_argument("--from-cascade-input", type=Path)
    manifest.add_argument("--output", type=Path, required=True)
    for name in ("run", "replay"):
        command = commands.add_parser(name, help="run Stages 1-3" if name == "run" else "recompute Stage 3 from the cache")
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--judge-config", action="append", metavar="JUDGE=CONFIG",
                             help="a prepared adapter configuration per Stage 2 judge (asr.whisper-small@1=...)")
        command.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
        command.add_argument("--resampler", choices=SUPPORTED_RESAMPLERS)
        command.add_argument("--timeout-seconds", type=float, default=DEFAULT_ROW_TIMEOUT_SECONDS,
                             help="per-row timeout of each Stage 2 worker; a launch also gets a fixed "
                                  f"start-up allowance ({DEFAULT_STARTUP_SECONDS:g} s)")
        if name == "run":
            command.add_argument("--bundle", type=Path, help="a new, untracked bundle directory")
        else:
            command.add_argument("--bundle", type=Path, required=True)
    validate = commands.add_parser("validate-bundle", help="re-hash and re-validate a private bundle")
    validate.add_argument("bundle", type=Path)
    records = commands.add_parser("replay-records",
                                  help="Stage 3 over the committed language records' metrics, against their verdicts")
    records.add_argument("--records", type=Path, default=REPO / "benchmarks/runs/language")
    records.add_argument("--matrix", type=Path, default=REPO / "config/language-bench-matrix.json")
    commands.add_parser("admission-status", help="the host's admission ledger and policy")
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            path = args.from_independent_asr_manifest or args.from_cascade_input
            payload = _read(path)
            build = manifest_from_independent_asr if args.from_independent_asr_manifest else manifest_from_cascade_input
            value = validate_manifest(build(payload, source_sha256=file_sha256(path)))
            atomic_json(args.output, value)
            print(json.dumps({"lane": value["lane"], "takes": len(value["takes"])}))
            return 0
        if args.command == "validate-bundle":
            errors = validate_private_bundle(args.bundle, repository=REPO)
            print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, indent=2))
            return 0 if not errors else 1
        if args.command == "admission-status":
            policy = AdmissionPolicy.from_registry(load_registry())
            print(json.dumps(HostAdmission(None, policy).status(), indent=2, sort_keys=True))
            return 0
        if args.command == "replay-records":
            report = replay_committed_records(args.records, args.matrix)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["identical"] else 1
        orchestrator = _orchestrator(args, offline=args.command == "replay")
        result = orchestrator.run(_read(args.manifest))
        if args.command == "replay":
            comparison = compare_with_bundle(result, args.bundle)
            print(json.dumps(comparison, indent=2, sort_keys=True))
            return 0 if comparison["identical"] else 1
        bundle = args.bundle or DEFAULT_BUNDLE_PARENT / result["header"]["runID"]
        written = write_private_bundle(bundle, header=result["header"],
                                       takes=zip(result["records"], result["privates"]), repository=REPO)
        print(json.dumps({"bundle": str(bundle), "takes": len(written["takes"]),
                          "failingTakes": written["failingTakes"], "run": result["header"]["run"],
                          "cache": result["header"]["cache"]}, indent=2, sort_keys=True))
        return 0
    except (OrchestratorError, AdmissionError, EvidenceError, JudgeRegistryError, ValueError, OSError,
            RuntimeError) as error:
        print(f"audio-qc-orchestrator: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
