"""An audio LLM as a QC judge through llama.cpp's `llama-server`, shared by the Gemma and Qwen-Omni
runners.

The runner starts one `llama-server` on 127.0.0.1 with the model and its audio projector, then asks
two questions per take (or per chunk of at most 30 seconds: Gemma 4 hears at most 30 s and llama.cpp
does not split its audio, so longer takes are cut evenly here and the answers merged):

1. a verbatim transcript, with no reference text, so the model cannot smooth stutters away;
2. a rubric over the QC classes in one JSON object constrained by a JSON schema (present, severity,
   start, end, evidence), with the take's language and its script, which only the stutter and
   mispronunciation classes may use. `pYes` is P(true) / (P(true) + P(false)) at each class's
   `present` value, from the returned top log-probabilities (llama.cpp computes them from the raw
   logits, before the grammar), or null when the server returns none.

Requests are deterministic: temperature 0, a fixed seed, no prompt cache, thinking off (Gemma 4
loops with thinking on, llama.cpp issue #24138). Audio goes as 16 kHz mono 16-bit WAV, resampled
here rather than by llama.cpp's linear resampler. Standard library and numpy only (the llama.cpp
runners run on the onnx venv's python).
"""
from __future__ import annotations

import base64
import json
import math
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from qc.runners import _kit

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 30.0
SEVERITIES = ("none", "mild", "moderate", "severe")

# The label classes of config/qc/protocol.json, with the definitions the judge hears. They live in
# code, not read at run time, so the runner identity covers them; a test keeps the ids equal to the
# protocol's.
CLASSES: tuple[tuple[str, str], ...] = (
    ("stutter", "a stutter or a missing syllable: a sound, syllable or word repeated, prolonged or "
                "blocked, or syllables or words of the script skipped or swallowed"),
    ("mispronunciation", "a mispronounced word or a foreign accent: a word said wrongly for the "
                         "language, or the language spoken with another language's accent"),
    ("wrong-language", "speech, or part of it, in a language other than the expected one"),
    ("cutoff", "speech that stops abruptly or is cut off mid-word or mid-sentence"),
    ("pitch", "pitch instability: pitch jumping, wobbling or swinging unnaturally, or an abrupt "
              "register jump"),
    ("tonal-collapse", "the voice collapsing into a sustained tone, hum or buzz instead of speech"),
    ("voice-change", "the speaker's identity, gender, age or timbre changing within the clip"),
    ("artifact", "clicks, pops, glitches, metallic or robotic distortion, or noise bursts"),
    ("unnatural", "unnatural delivery: robotic or monotone, wrong rhythm or stress, odd pauses or "
                  "breathing"),
    ("other", "any other defect a careful listener would object to"),
)


def class_ids() -> list[str]:
    return [name for name, _ in CLASSES]


# Every request: no prompt cache (llama.cpp warns it can make results nondeterministic) and no
# thinking, through both the template kwarg and the reasoning-effort switch.
REQUEST_DEFAULTS: Mapping[str, Any] = {
    "cache_prompt": False,
    "chat_template_kwargs": {"enable_thinking": False},
    "reasoning_effort": "none",
}


@dataclass(frozen=True)
class Profile:
    """What differs between judge models: their default file names and request extras."""

    name: str
    model_file: str | None = None
    mmproj_file: str | None = None
    context: int = 8192
    extra_body: Mapping[str, Any] = field(default_factory=dict)
    server_args: Sequence[str] = ("--reasoning", "off")


# --- requests ----------------------------------------------------------------------------------


def audio_part(wav: bytes) -> dict[str, Any]:
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode("ascii"), "format": "wav"}}


def transcript_prompt() -> str:
    """No script and no expected language: the transcript is what the judge hears, unprompted."""
    return (
        "Transcribe this audio verbatim, exactly as spoken, in the language actually spoken; do not "
        "translate. Keep every repetition, false start, stutter, cut-off word and mispronounced word "
        "as heard; do not correct, complete or tidy anything. Output only the transcript."
    )


def rubric_schema(classes: Sequence[str] = ()) -> dict[str, Any]:
    names = list(classes) or class_ids()
    seconds = {"anyOf": [{"type": "number"}, {"type": "null"}]}
    verdict = {
        "type": "object",
        "properties": {  # `present` first: its token carries pYes
            "present": {"type": "boolean"},
            "severity": {"enum": list(SEVERITIES)},
            "start": seconds,
            "end": seconds,
            "evidence": {"type": "string", "maxLength": 240},
        },
        "required": ["present", "severity", "start", "end", "evidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {name: verdict for name in names},
        "required": names,
        "additionalProperties": False,
    }


def rubric_prompt(language: str | None, script: str | None, duration: float, chunk: tuple[int, int] = (1, 1)) -> str:
    index, count = chunk
    lines = [
        "You are a strict quality-control listener for a text-to-speech system.",
        f"Listen to the audio clip ({duration:.1f} seconds"
        + (f", part {index} of {count} of a longer take" if count > 1 else "")
        + ")."
    ]
    if language:
        lines.append(f"The speech should be in {language.capitalize()}.")
    if script:
        lines.append(
            "The intended script follows. Use it only to judge the stutter and mispronunciation "
            "classes (skipped, repeated or wrongly pronounced words); judge every other class by ear."
            + (" The script covers the whole take, not only this part." if count > 1 else "")
        )
        lines.append(f"<script>\n{script}\n</script>")
    lines.append(
        "For each defect class below decide whether it is present anywhere in the clip, rate its "
        "severity (none, mild, moderate or severe; none exactly when absent), give the start and end "
        "in seconds of the worst instance (null when absent or unsure) and a short evidence note "
        "saying what you heard."
    )
    lines.extend(f"- {name}: {definition}" for name, definition in CLASSES)
    lines.append("Answer with the JSON object only.")
    return "\n".join(lines)


def chat_request(
    content_text: str,
    wav: bytes,
    *,
    seed: int,
    max_tokens: int,
    schema: Mapping[str, Any] | None = None,
    logprobs: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": [audio_part(wav), {"type": "text", "text": content_text}]}],
        "temperature": 0.0,
        "top_k": 1,
        "seed": seed,
        "max_tokens": max_tokens,
        "stream": False,
        **REQUEST_DEFAULTS,
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "qc_rubric", "strict": True, "schema": schema}}
    if logprobs:
        body["logprobs"] = True
        body["top_logprobs"] = int(logprobs)
    if extra:
        body.update(extra)
    return body


# --- responses ---------------------------------------------------------------------------------


def message_text(response: Mapping[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise _kit.TakeError("llm-response-malformed") from None
    if isinstance(content, list):  # some servers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, Mapping))
    return str(content or "").strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise _kit.TakeError("llm-invalid-json")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise _kit.TakeError("llm-invalid-json") from None
    if not isinstance(value, dict):
        raise _kit.TakeError("llm-invalid-json")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_verdict(raw: Any) -> dict[str, Any]:
    """One class verdict in the llm schema; absent classes are `present: false, severity: none`."""
    raw = raw if isinstance(raw, Mapping) else {}
    present = raw.get("present") is True
    severity = raw.get("severity") if raw.get("severity") in SEVERITIES else None
    if not present:
        severity = "none"
    elif severity in (None, "none"):
        severity = "mild"
    start, end = _number(raw.get("start")), _number(raw.get("end"))
    if not present:
        start = end = None
    elif start is not None and end is not None and end < start:
        start, end = end, start
    evidence = raw.get("evidence")
    return {
        "present": present,
        "severity": severity,
        "start": start,
        "end": end,
        "evidence": evidence.strip()[:240] if isinstance(evidence, str) else "",
        "pYes": None,
    }


def present_probabilities(response: Mapping[str, Any], classes: Sequence[str]) -> dict[str, float | None]:
    """P(present = true) per class from `choices[0].logprobs.content`, renormalized over true/false."""
    try:
        tokens = response["choices"][0]["logprobs"]["content"]
    except (KeyError, IndexError, TypeError):
        tokens = None
    result: dict[str, float | None] = {name: None for name in classes}
    if not tokens:
        return result
    spans: list[tuple[int, int, Mapping[str, Any]]] = []
    text = ""
    for entry in tokens:
        piece = str(entry.get("token", ""))
        spans.append((len(text), len(text) + len(piece), entry))
        text += piece
    cursor = 0
    for name in classes:
        key = text.find(json.dumps(name), cursor)
        if key < 0:
            continue
        field_at = text.find('"present"', key)
        if field_at < 0:
            continue
        colon = text.find(":", field_at)
        literal = colon + 1
        while literal < len(text) and text[literal] in " \t\r\n":
            literal += 1
        cursor = literal
        entry = next((e for s, t, e in spans if s <= literal < t), None)
        if entry is None:
            continue
        p_true = p_false = 0.0
        alternatives = list(entry.get("top_logprobs") or []) or [entry]
        for alternative in alternatives:
            # A token may carry the separator with it (`: true`, `":true`); keep the literal's start.
            word = str(alternative.get("token", "")).lstrip(" \t\r\n\":").rstrip()
            logprob = _number(alternative.get("logprob"))
            if not word or logprob is None:
                continue
            if "true".startswith(word) or word.startswith("true"):
                p_true += math.exp(logprob)
            elif "false".startswith(word) or word.startswith("false"):
                p_false += math.exp(logprob)
        if p_true + p_false > 0:
            result[name] = round(p_true / (p_true + p_false), 6)
    return result


def parse_rubric(response: Mapping[str, Any], classes: Sequence[str] = ()) -> dict[str, dict[str, Any]]:
    names = list(classes) or class_ids()
    payload = _parse_json_object(message_text(response))
    verdicts = {name: normalize_verdict(payload.get(name)) for name in names}
    for name, probability in present_probabilities(response, names).items():
        verdicts[name]["pYes"] = probability
    return verdicts


def merge_chunks(parts: Sequence[tuple[float, str, dict[str, dict[str, Any]]]]) -> dict[str, Any]:
    """Merge per-chunk `(offset, transcript, classes)`: present if any chunk hears it, the worst
    severity and its times (offset to the take), the present chunks' evidence, the highest pYes."""
    transcript = " ".join(text for _, text, _ in parts if text).strip()
    merged: dict[str, dict[str, Any]] = {}
    names = list(parts[0][2]) if parts else class_ids()
    for name in names:
        verdicts = [(offset, classes[name]) for offset, _, classes in parts]
        present = [(offset, v) for offset, v in verdicts if v["present"]]
        probabilities = [v["pYes"] for _, v in verdicts if v["pYes"] is not None]
        if present:
            offset, worst = max(present, key=lambda item: SEVERITIES.index(item[1]["severity"]))
            evidence = " | ".join(v["evidence"] for _, v in present if v["evidence"])
            verdict = {
                "present": True,
                "severity": worst["severity"],
                "start": None if worst["start"] is None else round(offset + worst["start"], 3),
                "end": None if worst["end"] is None else round(offset + worst["end"], 3),
                "evidence": evidence[:480],
            }
        else:
            verdict = {"present": False, "severity": "none", "start": None, "end": None,
                       "evidence": verdicts[0][1]["evidence"] if verdicts else ""}
        verdict["pYes"] = max(probabilities) if probabilities else None
        merged[name] = verdict
    return {"transcript": transcript, "classes": merged}


def chunk_audio(samples: np.ndarray, sr: int, limit: float = CHUNK_SECONDS) -> list[tuple[float, np.ndarray]]:
    """Even chunks of at most `limit` seconds: `(offset seconds, samples)`."""
    duration = samples.size / float(sr)
    count = max(1, math.ceil(duration / limit - 1e-9))
    bounds = np.linspace(0, samples.size, count + 1).round().astype(int)
    return [(bounds[i] / float(sr), samples[bounds[i]:bounds[i + 1]]) for i in range(count)]


# --- server ------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def find_server_binary(options: Mapping[str, Any]) -> Path:
    explicit = options.get("server")
    if explicit:
        return Path(explicit)
    root = Path(options.get("llamacppDir") or _kit.repository_root() / "build/cache/qc/runtimes/llamacpp")
    found = sorted(p for p in root.rglob("llama-server") if p.is_file()) if root.is_dir() else []
    if not found:
        raise FileNotFoundError("llama-server")
    return found[0]


def find_model_files(model_dir: Path, profile: Profile, options: Mapping[str, Any]) -> tuple[Path, Path]:
    model = options.get("modelFile") or profile.model_file
    mmproj = options.get("mmprojFile") or profile.mmproj_file
    ggufs = sorted(model_dir.glob("*.gguf"))
    if not mmproj:
        projectors = [p for p in ggufs if p.name.startswith("mmproj")]
        if len(projectors) != 1:
            raise FileNotFoundError("mmproj")
        mmproj = projectors[0].name
    if not model:
        weights = [p for p in ggufs if not p.name.startswith("mmproj")]
        if len(weights) != 1:
            raise FileNotFoundError("model gguf")
        model = weights[0].name
    return model_dir / str(model), model_dir / str(mmproj)


def server_command(binary: Path, model: Path, mmproj: Path, port: int, profile: Profile, options: Mapping[str, Any]) -> list[str]:
    command = [
        str(binary),
        "-m", str(model),
        "--mmproj", str(mmproj),
        "--host", "127.0.0.1",
        "--port", str(port),
        "-c", str(int(options.get("context", profile.context))),
        "-ngl", str(options.get("gpuLayers", 99)),
        "-np", "1",
        "--jinja",
        "--no-webui",
    ]
    if options.get("threads"):
        command += ["-t", str(int(options["threads"]))]
    command += list(profile.server_args) + [str(a) for a in options.get("serverArgs", [])]
    return command


class Server:
    """A `llama-server` child process, or an already-running server at `options.serverURL`."""

    def __init__(self, base_url: str, process: subprocess.Popen | None = None, timeout: float = 600.0, log: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.process = process
        self.timeout = timeout
        self.log = log

    @classmethod
    def start(cls, job: Mapping[str, Any], profile: Profile) -> "Server":
        """Start `llama-server` (or attach to `options.serverURL`) and wait for `/health`. Its output
        goes nowhere unless `options.serverLog` names a file, as runners write only results."""
        options = job.get("options") or {}
        request_timeout = float(options.get("requestTimeout", 600))
        if options.get("serverURL"):
            server = cls(str(options["serverURL"]), None, request_timeout)
        else:
            binary = find_server_binary(options)
            model, mmproj = find_model_files(Path(job["modelDir"]), profile, options)
            port = free_port()
            log = open(options["serverLog"], "ab") if options.get("serverLog") else None  # noqa: SIM115 - closed in stop()
            process = subprocess.Popen(
                server_command(binary, model, mmproj, port, profile, options),
                stdin=subprocess.DEVNULL,
                stdout=log or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            server = cls(f"http://127.0.0.1:{port}", process, request_timeout, log)
        try:
            server.wait_ready(float(options.get("startupTimeout", 900)))
            server.check_audio()
        except BaseException:
            server.stop()
            raise
        return server

    def check_audio(self) -> None:
        """Read `/props`: refuse a server whose projector has no audio, and keep its build id."""
        self.build: str | None = None
        try:
            with urllib.request.urlopen(f"{self.base_url}/props", timeout=10) as reply:
                props = json.loads(reply.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return
        modalities = props.get("modalities") if isinstance(props, Mapping) else None
        if isinstance(modalities, Mapping) and modalities.get("audio") is False:
            raise RuntimeError("llama-server has no audio input (check the mmproj)")
        build = props.get("build_info") if isinstance(props, Mapping) else None
        self.build = str(build) if build else None

    def wait_ready(self, limit: float) -> None:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("llama-server exited during startup")
            try:
                with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as reply:
                    if reply.status == 200:
                        return
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.5)
        raise TimeoutError("llama-server did not become ready")

    def chat(self, body: Mapping[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                return json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as failure:
            raise _kit.TakeError(f"llm-http-{failure.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise _kit.TakeError("llm-unreachable") from None
        except json.JSONDecodeError:
            raise _kit.TakeError("llm-response-malformed") from None

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self.log is not None:
            self.log.close()
            self.log = None


# --- runner ------------------------------------------------------------------------------------


@dataclass
class Judge:
    server: Server
    profile: Profile
    seed: int
    logprobs: int
    chunk_seconds: float


def judge_take(judge: Judge, take: Mapping[str, Any]) -> dict[str, Any]:
    samples, sr, duration = _kit.load_take_audio(take, SAMPLE_RATE)
    language, script = take.get("language"), take.get("text")
    chunks = chunk_audio(samples, sr, judge.chunk_seconds)
    parts = []
    for index, (offset, piece) in enumerate(chunks, start=1):
        wav = _kit.wav_bytes(piece, sr)
        seconds = piece.size / float(sr)
        transcript = message_text(judge.server.chat(chat_request(
            transcript_prompt(), wav, seed=judge.seed, max_tokens=1024, extra=judge.profile.extra_body,
        )))
        rubric = judge.server.chat(chat_request(
            rubric_prompt(language, script, seconds, (index, len(chunks))), wav, seed=judge.seed, max_tokens=2048,
            schema=rubric_schema(), logprobs=judge.logprobs, extra=judge.profile.extra_body,
        ))
        parts.append((offset, transcript, parse_rubric(rubric)))
    outputs = merge_chunks(parts)
    outputs["chunks"] = len(chunks)
    outputs["judge"] = judge.profile.name
    outputs["llamaBuild"] = getattr(judge.server, "build", None)
    return {"outputs": outputs, "duration": duration}


def make_runner(profile: Profile):
    """`(load, process, close, variant_of)` for `_kit.main`."""

    def load(job: Mapping[str, Any]) -> Judge:
        options = job.get("options") or {}
        server = Server.start(job, profile)
        return Judge(
            server=server,
            profile=profile,
            seed=int(options.get("seed", 1234)),
            logprobs=int(options.get("topLogprobs", 10)),
            chunk_seconds=min(float(options.get("chunkSeconds", CHUNK_SECONDS)), CHUNK_SECONDS),
        )

    def process(judge: Judge, take: Mapping[str, Any], job: Mapping[str, Any]) -> tuple[dict[str, Any], float, str]:
        result = judge_take(judge, take)
        return result["outputs"], result["duration"], _kit.variant_key(take)

    def close(judge: Judge) -> None:
        judge.server.stop()

    return load, process, close, _kit.variant_key


def run(profile: Profile, argv: Sequence[str] | None = None) -> int:
    load, process, close, variant_of = make_runner(profile)
    return _kit.main(load, process, variant_of=variant_of, argv=argv, close=close)
