"""Worker engines for the AQ-06 judge panel (audit section 4), run by `scripts/audio_qc_worker.py`.

Each engine runs inside its judge's pinned runtime venv (or, for the native
SenseVoice runtime, on the pinned standalone interpreter) under the persistent
worker protocol: it verifies, loads and warms once, then streams the job's rows.

**Nothing loads before verification.** Every engine first runs the registry's
load gate for the judge the job names:

- a judge with weights calls `verify_judge_snapshot`, which runs
  `require_loadable` (registered, runnable, tier A or B, the pinned repository
  and revision, and no excluded model or installed package) and then checks the
  snapshot directory holds exactly the pinned files, each matching its pin;
- pYIN, which has no weights, calls `require_runnable` over the installed
  packages;
- the native SenseVoice binary must also match the registry's pinned digest;
- the registry must run the judge under this engine.

A failure raises before the `ready` line, so the worker ends unready and its
rows are retried once, then unavailable: it fails closed. Hubs are switched off
(`HF_HUB_OFFLINE` and friends) before any library is imported, so a load that
tried to reach the network fails instead.

**Library calls are isolated.** Each backend keeps its library calls in its
`__init__` and `analyze`, so the offline tests replace a backend with a fake and
exercise everything around it; the libraries' own calls are exercised for the
first time on the M6 in the AQ-06 qualification session (audit P8), which is
where a call that drifted from the pinned library is corrected.

Rows carry the canonical 16 kHz PCM16 derivative (`pcmPath`) and, where the
judge needs them, the locked language and the reference text (the job file is
private, like every worker job). A row's result is the judge's raw output (L1);
`wallSeconds` rides beside it and the runner keeps it out of the cache.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

SAMPLE_RATE_HZ = 16_000
OFFLINE_ENVIRONMENT = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
# The exceptions a row's analysis can raise without the worker being broken.
ROW_FAILURES = (OSError, ValueError, KeyError, IndexError, RuntimeError)

Emit = Callable[[dict[str, Any]], None]


class PanelEngineError(ValueError):
    """The job's configuration, the judge's registration or its pinned files do not allow a load."""


# --------------------------------------------------------------------------- #
# Verification before load
# --------------------------------------------------------------------------- #

def go_offline() -> None:
    os.environ.update(OFFLINE_ENVIRONMENT)


def installed_packages() -> list[str]:
    """Every distribution installed where this worker runs (checked against the exclusion list)."""
    from importlib import metadata

    from audio_qc_judges import canonical_package

    return sorted({canonical_package(str(dist.metadata["Name"])) for dist in metadata.distributions()
                   if dist.metadata["Name"]})


def _config_text(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise PanelEngineError(f"the panel engine configuration lacks {key}")
    return value


def registered_judge(config: dict[str, Any], engine: str) -> dict[str, Any]:
    """The registry judge the job names; it must be registered to run under this engine."""
    from audio_qc_judges import load_registry

    judge_id = _config_text(config, "judge")
    judge = (load_registry().get("judges") or {}).get(judge_id)
    execution = judge.get("execution") if isinstance(judge, dict) else None
    if not isinstance(execution, dict) or execution.get("engine") != engine:
        raise PanelEngineError(f"{judge_id} is not registered to run under the {engine} engine")
    return judge


def verified_snapshot(config: dict[str, Any], engine: str) -> tuple[Path, dict[str, str]]:
    """The judge's snapshot after the registry's load gate and every file's digest check."""
    from audio_qc_judges import verify_judge_snapshot

    registered_judge(config, engine)
    snapshot = Path(_config_text(config, "snapshot"))
    digests = verify_judge_snapshot(
        _config_text(config, "judge"), snapshot, repository=_config_text(config, "repository"),
        revision=_config_text(config, "revision"), packages=installed_packages(),
    )
    return snapshot, digests


def runnable_without_weights(config: dict[str, Any], engine: str) -> None:
    from audio_qc_judges import require_runnable

    registered_judge(config, engine)
    require_runnable(_config_text(config, "judge"), packages=installed_packages())


def read_pcm16(path: Path) -> Any:
    import numpy as np

    data = np.frombuffer(path.read_bytes(), dtype="<i2")
    return data.astype(np.float32) / 32768.0


def _finite(values: Any) -> list[float | None]:
    """A float array as JSON: NaN (an unvoiced frame) becomes null."""
    return [None if not math.isfinite(float(value)) else float(value) for value in values]


# --------------------------------------------------------------------------- #
# The engine loop
# --------------------------------------------------------------------------- #

def run_backend(engine: str, job: dict[str, Any], emit: Emit, factory: Callable[..., Any], *,
                weights: bool = True) -> None:
    """Verify, load and warm once; then analyze every row in job order."""
    go_offline()
    config = job["engineConfig"]
    threads = int(job["threads"])
    if weights:
        snapshot, digests = verified_snapshot(config, engine)
    else:
        runnable_without_weights(config, engine)
        snapshot, digests = None, {}
    started = time.monotonic()
    backend = factory(snapshot, config, threads)
    load_seconds = time.monotonic() - started
    started = time.monotonic()
    warm = getattr(backend, "warm", None)
    if callable(warm):
        warm()
    warmup_seconds = time.monotonic() - started
    emit({"kind": "ready", "engine": engine, "threads": threads,
          "modelLoadSeconds": getattr(backend, "model_load_seconds", load_seconds),
          "warmupSeconds": getattr(backend, "warmup_seconds", warmup_seconds), "verifiedFiles": len(digests)})
    for row in job["rows"]:
        try:
            audio = read_pcm16(Path(str(row["pcmPath"])))
            started = time.monotonic()
            result = backend.analyze(audio, row)
        except ROW_FAILURES:
            emit({"kind": "row-error", "id": row["id"], "reason": "analysis-failed"})
            continue
        emit({"kind": "row", "id": row["id"],
              "result": {**result, "decodedSampleCount": int(len(audio)), "sampleRateHz": SAMPLE_RATE_HZ,
                         "wallSeconds": time.monotonic() - started}})


# --------------------------------------------------------------------------- #
# Backends (the only places a panel library is called)
# --------------------------------------------------------------------------- #

class ParakeetBackend:
    """Parakeet TDT 0.6B v3 through parakeet-mlx: greedy, no chunking under 120 s."""

    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        import mlx.core as mx
        from parakeet_mlx import from_pretrained

        options = config.get("decodeOptions") or {}
        self.maximum_samples = int(float(options.get("maximumUnchunkedSeconds", 120)) * SAMPLE_RATE_HZ)
        self.model = from_pretrained(str(snapshot), dtype=getattr(mx, str(options.get("dtype", "bfloat16"))))
        if int(self.model.preprocessor_config.sample_rate) != SAMPLE_RATE_HZ:
            raise PanelEngineError("the pinned Parakeet model does not read 16 kHz audio")

    def warm(self) -> None:
        import numpy as np

        self.analyze(np.zeros(SAMPLE_RATE_HZ, dtype=np.float32), {})

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        if len(audio) > self.maximum_samples:
            raise ValueError("the take needs chunking, which this judge's decode never uses")
        result = self.model.generate(get_logmel(mx.array(audio), self.model.preprocessor_config))[0]
        return {"transcript": str(result.text).strip(), "language": row.get("language")}


class ParaformerBackend:
    """Paraformer-zh through FunASR on the CPU: no hotwords, punctuation or VAD model."""

    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        import torch
        from funasr import AutoModel

        torch.set_num_threads(threads)
        self.model = AutoModel(model=str(snapshot), device="cpu", ncpu=threads, disable_update=True,
                               disable_pbar=True, disable_log=True)

    def warm(self) -> None:
        import numpy as np

        self.analyze(np.zeros(SAMPLE_RATE_HZ, dtype=np.float32), {})

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        output = self.model.generate(input=audio, batch_size=1)
        text = output[0].get("text", "") if output else ""
        return {"transcript": str(text).strip(), "language": row.get("language")}


class _MlxAudioBackend:
    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        from mlx_audio.stt.utils import load_model

        self.options = config.get("decodeOptions") or {}
        self.model = load_model(str(snapshot))


class Qwen3AsrBackend(_MlxAudioBackend):
    """Qwen3-ASR 1.7B through mlx-audio: greedy, no context string; a row without a language is an LID pass."""

    def warm(self) -> None:
        import numpy as np

        self.analyze(np.zeros(SAMPLE_RATE_HZ, dtype=np.float32), {"language": "English"})

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        import mlx.core as mx

        language = row.get("language")
        output = self.model.generate(mx.array(audio), language=language)
        return {"transcript": str(getattr(output, "text", "")).strip(), "language": language,
                "detectedLanguage": getattr(output, "language", None)}


class Qwen3AlignerBackend(_MlxAudioBackend):
    """Qwen3-ForcedAligner 0.6B through mlx-audio: intervals for the reference text's units."""

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        import mlx.core as mx

        text = row.get("referenceText")
        language = row.get("language")
        if not isinstance(text, str) or not text.strip() or not isinstance(language, str):
            raise ValueError("an alignment row names its reference text and language")
        output = self.model.generate(mx.array(audio), text=text, language=language)
        intervals = [
            {"unit": str(getattr(item, "text", "")), "start": float(item.start), "end": float(item.end)}
            for item in getattr(output, "segments", None) or []
        ]
        return {"language": language, "units": alignment_units(text, language), "intervals": intervals}


def alignment_units(text: str, language: str) -> list[str]:
    """The units intervals are reported for (audit section 4.1): whitespace eojeol for Korean
    (no soynlp), characters for Chinese and Japanese, words for alphabetic languages."""
    if language in ("zh", "ja", "chinese", "japanese", "Chinese", "Japanese"):
        return [character for character in text if not character.isspace()]
    return text.split()


class VoxLinguaBackend:
    """The VoxLingua107 ECAPA language classifier through SpeechBrain on the CPU."""

    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        import torch
        from speechbrain.inference.classifiers import EncoderClassifier

        torch.set_num_threads(threads)
        self._collect = tempfile.TemporaryDirectory(prefix="vocello-lid-")
        # The card's hyperparameters point at the Hub; the verified snapshot replaces that path.
        self.model = EncoderClassifier.from_hparams(
            source=str(snapshot), savedir=self._collect.name, run_opts={"device": "cpu"},
            overrides={"pretrained_path": str(snapshot)},
        )
        encoder = self.model.hparams.label_encoder
        self.labels = [str(encoder.ind2lab[index]) for index in range(len(encoder))]

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        import torch

        with torch.no_grad():
            log_posteriors, _score, index, _label = self.model.classify_batch(torch.from_numpy(audio).unsqueeze(0))
        values = log_posteriors.squeeze(0).tolist()
        return {"logPosteriors": {label.split(":")[0].strip(): float(value) for label, value in zip(self.labels, values)},
                "top1": self.labels[int(index.item())].split(":")[0].strip()}


class WespeakerBackend:
    """A WeSpeaker ONNX speaker embedding (CAM++ or ResNet293) with owned Kaldi fbank features."""

    FEATURE_BINS = 80

    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        import onnxruntime

        models = sorted(snapshot.glob("*.onnx"))
        if len(models) != 1:
            raise PanelEngineError("a WeSpeaker snapshot holds exactly one ONNX model")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        self.session = onnxruntime.InferenceSession(str(models[0]), sess_options=options,
                                                    providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        windows = ((config.get("preprocessing") or {}).get("windows") or {})
        self.window = int(float(windows.get("seconds", 2.0)) * SAMPLE_RATE_HZ)
        self.hop = int(float(windows.get("hopSeconds", 0.5)) * SAMPLE_RATE_HZ)

    def features(self, audio: Any) -> Any:
        import kaldi_native_fbank as knf
        import numpy as np

        options = knf.FbankOptions()
        options.frame_opts.samp_freq = SAMPLE_RATE_HZ
        options.frame_opts.frame_length_ms = 25
        options.frame_opts.frame_shift_ms = 10
        options.frame_opts.dither = 0.0
        options.frame_opts.window_type = "hamming"
        options.frame_opts.snip_edges = True
        options.mel_opts.num_bins = self.FEATURE_BINS
        bank = knf.OnlineFbank(options)
        bank.accept_waveform(SAMPLE_RATE_HZ, (audio * 32768.0).tolist())
        bank.input_finished()
        frames = np.array([bank.get_frame(index) for index in range(bank.num_frames_ready)], dtype=np.float32)
        if frames.size == 0:
            raise ValueError("the take is too short for one feature frame")
        return frames - frames.mean(axis=0, keepdims=True)

    def embed(self, audio: Any) -> list[float]:
        feats = self.features(audio)[None, :, :]
        return [float(value) for value in self.session.run([self.output_name], {self.input_name: feats})[0][0]]

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        starts = range(0, len(audio) - self.window + 1, self.hop) if len(audio) >= self.window else range(0)
        windows = [{"startSeconds": start / SAMPLE_RATE_HZ, "embedding": self.embed(audio[start:start + self.window])}
                   for start in starts]
        embedding = self.embed(audio)
        return {"embedding": embedding, "dimension": len(embedding), "windows": windows}


class PyinBackend:
    """librosa's probabilistic YIN at the registry's fixed configuration."""

    def __init__(self, snapshot: None, config: dict[str, Any], threads: int) -> None:
        import librosa

        self.librosa = librosa
        self.options = dict(config.get("configuration") or {})
        if int(self.options.get("sampleRateHz", 0)) != SAMPLE_RATE_HZ:
            raise PanelEngineError("pYIN's configuration must read the canonical 16 kHz audio")

    def warm(self) -> None:
        import numpy as np

        self.analyze(np.zeros(SAMPLE_RATE_HZ, dtype=np.float32), {})

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        options = self.options
        f0, voiced, probability = self.librosa.pyin(
            audio, fmin=float(options["fmin"]), fmax=float(options["fmax"]), sr=SAMPLE_RATE_HZ,
            frame_length=int(options["frameLength"]), hop_length=int(options["hopLength"]),
            center=bool(options["center"]), pad_mode=str(options["padMode"]),
            n_thresholds=int(options["nThresholds"]), beta_parameters=tuple(options["betaParameters"]),
            boltzmann_parameter=float(options["boltzmannParameter"]), resolution=float(options["resolution"]),
            max_transition_rate=float(options["maxTransitionRate"]), switch_prob=float(options["switchProb"]),
            no_trough_prob=float(options["noTroughProb"]),
        )
        return {"hopSeconds": int(options["hopLength"]) / SAMPLE_RATE_HZ, "f0Hz": _finite(f0),
                "voiced": [bool(value) for value in voiced], "voicedProbability": _finite(probability)}


class AudioboxBackend:
    """Audiobox Aesthetics (CE, CU, PC, PQ) on the CPU from the verified safetensors snapshot."""

    def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
        import torch
        from audiobox_aesthetics import infer

        torch.set_num_threads(threads)
        local = infer.AesMultiOutput.from_pretrained(str(snapshot))

        class _Pinned:
            @staticmethod
            def from_pretrained(*_args: Any, **_kwargs: Any) -> Any:
                return local

        # The predictor asks the Hub for its model by name; it gets the verified local one.
        original = infer.AesMultiOutput
        infer.AesMultiOutput = _Pinned
        try:
            self.predictor = infer.initialize_predictor()
        finally:
            infer.AesMultiOutput = original

    def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
        import torch

        scores = self.predictor.forward([{"path": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE_HZ}])[0]
        return {axis: float(scores[axis]) for axis in ("CE", "CU", "PC", "PQ")}


BACKENDS: dict[str, Callable[..., Any]] = {
    "parakeet-mlx": ParakeetBackend,
    "funasr-paraformer": ParaformerBackend,
    "qwen3-asr-mlx": Qwen3AsrBackend,
    "qwen3-aligner-mlx": Qwen3AlignerBackend,
    "speechbrain-lid": VoxLinguaBackend,
    "wespeaker-onnx": WespeakerBackend,
    "audiobox-aesthetics": AudioboxBackend,
    "pyin-librosa": PyinBackend,
}
NO_WEIGHTS = frozenset({"pyin-librosa"})


# --------------------------------------------------------------------------- #
# Whisper large-v3 and the native SenseVoice runtime
# --------------------------------------------------------------------------- #

def whisper_panel(job: dict[str, Any], emit: Emit) -> None:
    """Whisper large-v3: the whisper-small recognizer's decode, plus the panel's
    `noSpeechThreshold` and `initialPrompt` options, loaded from the verified snapshot."""
    from independent_asr_worker import Recognizer

    class PanelRecognizer(Recognizer):  # type: ignore[misc, valid-type]
        def _options(self, language: str | None) -> dict[str, Any]:
            options = super()._options(language)
            if "noSpeechThreshold" in self.decode:
                options["no_speech_threshold"] = self.decode["noSpeechThreshold"]
            if "initialPrompt" in self.decode:
                options["initial_prompt"] = self.decode["initialPrompt"]
            return options

    class WhisperBackend:
        def __init__(self, snapshot: Path, config: dict[str, Any], threads: int) -> None:
            self.recognizer = PanelRecognizer(snapshot, config.get("decodeOptions") or {},
                                              warmup_language=job["rows"][0].get("language"))
            self.model_load_seconds = self.recognizer.model_load_seconds
            self.warmup_seconds = self.recognizer.warmup_seconds

        def analyze(self, audio: Any, row: dict[str, Any]) -> dict[str, Any]:
            result = dict(self.recognizer.recognize(audio, row.get("language")))
            for key in ("decodedSampleCount", "sampleRateHz", "wallSeconds"):
                result.pop(key, None)
            return result

    run_backend("whisper-mlx", job, emit, WhisperBackend)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sensevoice_llamacpp(job: dict[str, Any], emit: Emit) -> None:
    """SenseVoice f16 on the pinned llama.cpp binary, one invocation per row (`native-command`)."""
    from audio_qc_judges import load_registry
    from audio_qc_worker import native_command

    go_offline()
    config = job["engineConfig"]
    snapshot, digests = verified_snapshot(config, "sensevoice-llamacpp")
    acquisition = load_registry().get("acquisition") or {}
    family = (acquisition.get("runtimes") or {}).get("sensevoice-llamacpp") or {}
    artifact = (acquisition.get("artifacts") or {}).get(family.get("artifact")) or {}
    pinned = (artifact.get("members") or {}).get(family.get("binary"))
    binary = Path(_config_text(config, "binary"))
    if not pinned or not binary.is_file() or _file_sha256(binary) != pinned:
        raise PanelEngineError("the SenseVoice runtime binary is missing or differs from its pinned digest")
    models = sorted(name for name in digests if name.endswith(".gguf"))
    if len(models) != 1:
        raise PanelEngineError("the SenseVoice snapshot pins exactly one GGUF model")
    command = [str(binary), "-m", str(snapshot / models[0]), "-a", "{audio}", "--backend", "cpu", "--keep-tags"]

    def relabel(payload: dict[str, Any]) -> None:
        if payload.get("kind") == "ready":
            payload = {**payload, "engine": "sensevoice-llamacpp", "verifiedFiles": len(digests)}
        emit(payload)

    native_command({**job, "engineConfig": {**config, "command": command}}, relabel)


def run_engine(name: str, job: dict[str, Any], emit: Emit) -> None:
    if name == "sensevoice-llamacpp":
        sensevoice_llamacpp(job, emit)
        return
    factory = BACKENDS.get(name)
    if factory is None:
        raise PanelEngineError(f"unknown panel engine {name!r}")
    run_backend(name, job, emit, factory, weights=name not in NO_WEIGHTS)


ENGINE_NAMES = (*BACKENDS, "sensevoice-llamacpp")
