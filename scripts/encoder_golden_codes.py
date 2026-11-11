#!/usr/bin/env python3
"""Pins the Swift speech-tokenizer encoder against the reference encoder (RF-50).

A clone's reference audio is turned into codec codes by the 12 Hz tokenizer's
encoder. Upstream runs that encoder as Hugging Face's `MimiModel`; Vocello runs
its own MLX port. This tool keeps the two comparable on a synthetic fixture
that needs no recorded speech:

    fixture    write three deterministic clips and the round-trip job
    reference  run the reference encoder on the fixture, under the reference
               rotary convention (split-half) and under the adjacent-pair
               convention the Swift encoder applies today (A-02), and write
               the golden file
    swift      run the Swift encoder on the fixture (`vocello bench
               --codec-roundtrip`, an internal-diagnostics build)
    compare    say which convention the Swift codes follow, and how closely

`compare` exits 0 when the Swift codes follow the expected convention, 1 when
they do not and 2 on an error. Two frameworks never agree on every code, so the
rule is an agreement rate, recorded in the golden file with the rates measured
when it was made.

`fixture`, `swift` and `compare` need only the repository's Python.
`reference` needs torch, transformers, safetensors and soundfile (the QC torch
runtime has them), and the tokenizer directory of an installed model. The
golden file is committed, so `reference` runs only when the fixture or the
tokenizer changes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

SAMPLE_RATE = 24_000
CODEBOOKS = 16
SECONDS = 6
JOB_KIND = "audio-qc-n2-roundtrip-job"
GOLDEN_KIND = "speech-tokenizer-encoder-golden-codes"
CONVENTIONS = ("reference", "adjacent")
# Half a second of zeros, as the clone path appends before it encodes.
PADDING_SAMPLES = SAMPLE_RATE // 2
PADDINGS = {"as-is": 0, "padded": PADDING_SAMPLES}

# The rule `compare` applies, written into the golden file. The first codebook
# carries the coarse content and agrees almost everywhere across frameworks;
# the later ones split near-ties differently, so they are held to less.
DEFAULT_RULE = {
    "minimumFirstCodebookAgreement": 0.95,
    "minimumOverallAgreement": 0.85,
    "maximumOtherConventionOverallAgreement": 0.70,
}


class GoldenError(Exception):
    pass


# ---------------------------------------------------------------- fixture


class _Noise:
    """A fixed linear congruential generator: the same samples on every host."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> float:
        self.state = (1_664_525 * self.state + 1_013_904_223) & 0xFFFFFFFF
        return self.state / 0x80000000 - 1.0


def _envelope(position: float, length: float, edge: float = 0.03) -> float:
    if position < 0 or position > length:
        return 0.0
    return min(1.0, position / edge, (length - position) / edge)


def _formant_gain(frequency: float, formants: tuple[float, float, float]) -> float:
    return sum(1.0 / (1.0 + ((frequency - centre) / 90.0) ** 2) for centre in formants)


def _voiced(seconds: float, pitch: tuple[float, float], formants: tuple[float, float, float]) -> list[float]:
    """A harmonic source with a gliding pitch, weighted by three resonances."""
    count = int(seconds * SAMPLE_RATE)
    phase = 0.0
    out = []
    for index in range(count):
        time = index / SAMPLE_RATE
        glide = pitch[0] + (pitch[1] - pitch[0]) * time / seconds
        frequency = glide * (1.0 + 0.012 * math.sin(2 * math.pi * 5.3 * time))
        phase += 2 * math.pi * frequency / SAMPLE_RATE
        sample = 0.0
        for harmonic in range(1, 25):
            partial = harmonic * frequency
            if partial > 7_500:
                break
            sample += _formant_gain(partial, formants) / harmonic * math.sin(harmonic * phase)
        out.append(sample * _envelope(time, seconds))
    peak = max(abs(value) for value in out) or 1.0
    return [0.5 * value / peak for value in out]


def _fricative(seconds: float, seed: int) -> list[float]:
    """Differenced noise: energy toward the top of the band, like a consonant."""
    noise = _Noise(seed)
    previous = 0.0
    out = []
    for index in range(int(seconds * SAMPLE_RATE)):
        current = noise.next()
        out.append(0.18 * (current - previous) * _envelope(index / SAMPLE_RATE, seconds, 0.015))
        previous = current
    return out


def _silence(seconds: float) -> list[float]:
    return [0.0] * int(seconds * SAMPLE_RATE)


def _fit(samples: list[float]) -> list[float]:
    count = SECONDS * SAMPLE_RATE
    return (samples + [0.0] * count)[:count]


_VOWELS = {
    "a": (730.0, 1_090.0, 2_440.0),
    "i": (270.0, 2_290.0, 3_010.0),
    "u": (300.0, 870.0, 2_240.0),
    "e": (530.0, 1_840.0, 2_480.0),
    "o": (570.0, 840.0, 2_410.0),
}


def fixture_clips() -> dict[str, list[float]]:
    vowels: list[float] = []
    for name, pitch in (("a", (118, 132)), ("i", (135, 120)), ("u", (112, 126)), ("e", (128, 150)), ("o", (140, 108))):
        vowels += _voiced(0.95, pitch, _VOWELS[name]) + _silence(0.2)
    syllables: list[float] = []
    for index, name in enumerate(("a", "e", "i", "o", "u", "a", "i", "e")):
        syllables += _fricative(0.14, 9_001 + index) + _voiced(0.42, (190 - 6 * index, 176 + 5 * index), _VOWELS[name])
        syllables += _silence(0.12 if index % 3 else 0.3)
    high: list[float] = []
    for index, name in enumerate(("i", "e", "a", "o")):
        high += _voiced(1.1, (228 + 12 * index, 205 + 20 * index), _VOWELS[name]) + _fricative(0.1, 4_242 + index)
        high += _silence(0.25)
    return {"vowels-low": _fit(vowels), "syllables": _fit(syllables), "vowels-high": _fit(high)}


def pcm16(samples: list[float]) -> bytes:
    return b"".join(
        struct.pack("<h", max(-32_768, min(32_767, int(round(value * 32_767))))) for value in samples
    )


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_fixture(out: Path, golden: dict | None = None) -> dict:
    """Writes the clips and the job. With a golden file, the clips must be the
    ones it was made from: the codes describe those bytes and no others."""
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for clip_id, samples in fixture_clips().items():
        pcm = pcm16(samples)
        path = out / f"{clip_id}.wav"
        write_wav(path, pcm)
        items.append({"id": clip_id, "wavPath": path.name, "wavSHA256": sha256_file(path),
                      "pcmSHA256": hashlib.sha256(pcm).hexdigest(), "samples": len(samples)})
    if golden is not None:
        pinned = {clip["id"]: clip["pcmSHA256"] for clip in golden["fixture"]["clips"]}
        made = {item["id"]: item["pcmSHA256"] for item in items}
        if pinned != made:
            raise GoldenError("this host generates different fixture samples than the golden file was made from")
    job = {"schemaVersion": 1, "kind": JOB_KIND, "sampleRate": SAMPLE_RATE,
           "items": [{key: item[key] for key in ("id", "wavPath", "wavSHA256")} for item in items]}
    (out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return {"clips": [{key: item[key] for key in ("id", "pcmSHA256", "samples")} for item in items]}


# ---------------------------------------------------------------- codes


def read_codes(path: Path) -> list[list[int]]:
    """A `VQCT` codec trace: frames of 16 little-endian 32-bit codes."""
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"VQCT":
        raise GoldenError(f"{path.name} is not a codec trace")
    version, frame_count = struct.unpack_from("<II", data, 4)
    if version != 1:
        raise GoldenError(f"{path.name} has an unknown trace version")
    cursor = 16
    frames = []
    for _ in range(frame_count):
        if cursor + 2 > len(data):
            raise GoldenError(f"{path.name} is truncated")
        (count,) = struct.unpack_from("<H", data, cursor)
        cursor += 2
        if count != CODEBOOKS or cursor + 4 * count > len(data):
            raise GoldenError(f"{path.name} holds a frame that is not {CODEBOOKS} codes")
        frames.append(list(struct.unpack_from(f"<{count}i", data, cursor)))
        cursor += 4 * count
    if cursor != len(data) or not frames:
        raise GoldenError(f"{path.name} has no frames or trailing bytes")
    return frames


def agreement(swift: list[list[int]], golden: list[list[int]]) -> dict:
    """Shares of equal codes over the frames both have, per codebook and overall."""
    frames = min(len(swift), len(golden))
    if frames == 0:
        raise GoldenError("nothing to compare")
    equal = [0] * CODEBOOKS
    for index in range(frames):
        for codebook in range(CODEBOOKS):
            equal[codebook] += swift[index][codebook] == golden[index][codebook]
    return {"frames": frames, "equalPerCodebook": equal}


def pooled(parts: list[dict]) -> dict:
    frames = sum(part["frames"] for part in parts)
    equal = [sum(part["equalPerCodebook"][codebook] for part in parts) for codebook in range(CODEBOOKS)]
    return {
        "frames": frames,
        "firstCodebook": equal[0] / frames,
        "overall": sum(equal) / (frames * CODEBOOKS),
        "perCodebook": [round(count / frames, 4) for count in equal],
    }


def compare(golden: dict, swift_codes: dict[str, list[list[int]]], expect: str) -> dict:
    if expect not in CONVENTIONS:
        raise GoldenError(f"unknown convention '{expect}'")
    clip_ids = [clip["id"] for clip in golden["fixture"]["clips"]]
    if sorted(swift_codes) != sorted(clip_ids):
        raise GoldenError("the Swift codes do not cover the fixture's clips")
    rates: dict[str, dict] = {}
    for convention in CONVENTIONS:
        # The encoder is causal, so trailing zeros change no earlier frame and
        # the two paddings differ only in length. The one that covers more of
        # the Swift frames is reported: a change to the padding step shows as
        # a change of that label and of the frame count.
        pools = [
            dict(pooled([agreement(swift_codes[clip], golden["codes"][convention][padding][clip]) for clip in clip_ids]),
                 padding=padding)
            for padding in PADDINGS
        ]
        rates[convention] = max(pools, key=lambda pool: (pool["overall"], pool["frames"]))
    other = next(name for name in CONVENTIONS if name != expect)
    rule = golden["rule"]
    reasons = []
    if rates[expect]["firstCodebook"] < rule["minimumFirstCodebookAgreement"]:
        reasons.append("the first codebook agrees too rarely with the expected convention")
    if rates[expect]["overall"] < rule["minimumOverallAgreement"]:
        reasons.append("the codes agree too rarely with the expected convention")
    if rates[other]["overall"] > rule["maximumOtherConventionOverallAgreement"]:
        reasons.append("the codes agree with the other convention as well, so the fixture does not separate them")
    return {"expect": expect, "follows": max(CONVENTIONS, key=lambda name: rates[name]["overall"]),
            "rates": rates, "rule": rule, "passed": not reasons, "reasons": reasons}


# ---------------------------------------------------------------- reference


def _adjacent_pair_rotary(torch):
    def apply(q, k, cos, sin, unsqueeze_dim=1):
        """MLX `RoPE(traditional: true)`: rotate (x[2i], x[2i+1]) by the i-th frequency."""
        cos = cos.unsqueeze(unsqueeze_dim)
        sin = sin.unsqueeze(unsqueeze_dim)
        half = cos.shape[-1] // 2
        c, s = cos[..., :half], sin[..., :half]

        def rotate(x):
            x1, x2 = x[..., 0::2], x[..., 1::2]
            return torch.stack((x1 * c - x2 * s, x1 * s + x2 * c), dim=-1).flatten(-2)

        return rotate(q), rotate(k)

    return apply


def reference_codes(fixture: Path, tokenizer: Path) -> dict:
    """Both conventions' codes from Hugging Face's `MimiModel` with the tokenizer's encoder weights."""
    try:
        # Present only in the QC torch runtime, never in the repository's Python.
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        mimi = importlib.import_module("transformers.models.mimi.modeling_mimi")
        load_file = importlib.import_module("safetensors.torch").load_file
    except ImportError as error:
        raise GoldenError(f"the reference encoder needs torch, transformers and safetensors ({error.name} is missing)")
    MimiConfig, MimiModel = transformers.MimiConfig, transformers.MimiModel
    config = MimiConfig(**json.loads((tokenizer / "config.json").read_text(encoding="utf-8"))["encoder_config"])
    model = MimiModel(config)
    weights = load_file(str(tokenizer / "model.safetensors"))
    state = {key[len("encoder."):]: value for key, value in weights.items() if key.startswith("encoder.")}
    loaded = model.load_state_dict(state, strict=False)
    missing = [key for key in loaded.missing_keys if not key.startswith(("decoder", "upsample"))]
    if missing or loaded.unexpected_keys:
        raise GoldenError("the tokenizer's encoder weights do not fit the reference model")
    model.eval()
    stock = mimi.apply_rotary_pos_emb
    rotary = {"reference": stock, "adjacent": _adjacent_pair_rotary(torch)}
    job = json.loads((fixture / "job.json").read_text(encoding="utf-8"))
    codes: dict = {convention: {padding: {} for padding in PADDINGS} for convention in CONVENTIONS}
    try:
        for item in job["items"]:
            with wave.open(str(fixture / item["wavPath"]), "rb") as handle:
                raw = handle.readframes(handle.getnframes())
            samples = torch.tensor(struct.unpack(f"<{len(raw) // 2}h", raw), dtype=torch.float32) / 32_768.0
            for padding, zeros in PADDINGS.items():
                wave_in = torch.cat([samples, torch.zeros(zeros)]) if zeros else samples
                for convention in CONVENTIONS:
                    mimi.apply_rotary_pos_emb = rotary[convention]
                    with torch.no_grad():
                        encoded = model.encode(wave_in.reshape(1, 1, -1), num_quantizers=CODEBOOKS).audio_codes[0]
                    codes[convention][padding][item["id"]] = encoded.transpose(0, 1).tolist()
    finally:
        mimi.apply_rotary_pos_emb = stock
    return {"codes": codes,
            "tokenizer": {"modelSHA256": sha256_file(tokenizer / "model.safetensors")},
            "runtime": {"torch": torch.__version__, "transformers": transformers.__version__}}


# ---------------------------------------------------------------- commands


def command_fixture(args: argparse.Namespace) -> int:
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8")) if args.golden else None
    described = write_fixture(Path(args.out), golden)
    print(json.dumps(described, indent=2))
    return 0


def command_reference(args: argparse.Namespace) -> int:
    fixture = Path(args.fixture)
    described = write_fixture(fixture)
    made = reference_codes(fixture, Path(args.tokenizer))
    golden = {"schemaVersion": 1, "kind": GOLDEN_KIND, "sampleRate": SAMPLE_RATE, "codebooks": CODEBOOKS,
              "fixture": described, "tokenizer": made["tokenizer"], "runtime": made["runtime"],
              "paddingSamples": PADDINGS, "rule": DEFAULT_RULE, "codes": made["codes"]}
    pair = pooled([agreement(made["codes"]["reference"]["as-is"][clip["id"]], made["codes"]["adjacent"]["as-is"][clip["id"]])
                   for clip in described["clips"]])
    golden["conventionsAgree"] = {"firstCodebook": round(pair["firstCodebook"], 4), "overall": round(pair["overall"], 4)}
    Path(args.out).write_text(json.dumps(golden, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"clips": len(described["clips"]), "conventionsAgree": golden["conventionsAgree"]}, indent=2))
    return 0


def command_swift(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise GoldenError("the output directory must not exist: the round trip never overwrites")
    out.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, QWENVOICE_DEBUG="1")
    for assignment in args.env or []:
        name, separator, value = assignment.partition("=")
        if not separator or not name:
            raise GoldenError(f"--env takes NAME=VALUE, not '{assignment}'")
        environment[name] = value
    command = [args.vocello, "bench", "--codec-roundtrip", str(Path(args.fixture) / "job.json"),
               "--output-dir", str(out)]
    if args.data_dir:
        command += ["--data-dir", args.data_dir]
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        raise GoldenError(f"the round trip failed (exit {result.returncode}): {tail[0][:200]}")
    print(json.dumps({"written": len(list(out.glob('*.codes.bin')))}))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    if golden.get("kind") != GOLDEN_KIND or golden.get("schemaVersion") != 1:
        raise GoldenError("not a golden-codes file")
    swift = {clip["id"]: read_codes(Path(args.swift) / f"{clip['id']}.codes.bin") for clip in golden["fixture"]["clips"]}
    verdict = compare(golden, swift, args.expect)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pin the Swift speech-tokenizer encoder against the reference encoder.")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="write the synthetic clips and the round-trip job")
    fixture.add_argument("--out", required=True)
    fixture.add_argument("--golden", help="require the clips the golden file was made from")
    fixture.set_defaults(run=command_fixture)
    reference = commands.add_parser("reference", help="write the golden file from the reference encoder")
    reference.add_argument("--fixture", required=True, help="directory to write the fixture into")
    reference.add_argument("--tokenizer", required=True, help="an installed model's speech_tokenizer directory")
    reference.add_argument("--out", required=True)
    reference.set_defaults(run=command_reference)
    swift = commands.add_parser("swift", help="encode the fixture with the Swift encoder")
    swift.add_argument("--fixture", required=True)
    swift.add_argument("--out", required=True, help="a new output directory")
    swift.add_argument("--vocello", default="build/vocello")
    swift.add_argument("--data-dir")
    swift.add_argument("--env", action="append", help="NAME=VALUE for the encoder's process (a diagnostic knob); repeatable")
    swift.set_defaults(run=command_swift)
    comparison = commands.add_parser("compare", help="say which convention the Swift codes follow")
    comparison.add_argument("--golden", default="config/encoder-golden-codes.json")
    comparison.add_argument("--swift", required=True)
    comparison.add_argument("--expect", choices=CONVENTIONS, required=True)
    comparison.set_defaults(run=command_compare)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except GoldenError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
