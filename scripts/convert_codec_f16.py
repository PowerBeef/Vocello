#!/usr/bin/env python3
"""Convert the Qwen3-TTS speech tokenizer's F32 tensors to F16.

Operator tooling for the codec-precision artifact promotion (see
benchmarks/OPTIMIZATION.md §R). NOT a CI or packaging dependency: this script
runs on a maintainer machine to produce the file that is then uploaded to the
pinned Hugging Face repos; the fail-closed catalog consumes only the uploaded
bytes' exact digests.

What it does, deterministically (pure numpy, no torch/mlx):
  1. Verifies the input is the known fp32 speech tokenizer: 496 tensors,
     650.6 MiB of F32, containing the four T-Mimi-excluded output tensors
     (`decoder.decoder.5.alpha/.beta`, `decoder.decoder.6.conv.weight/.bias`).
  2. Casts every other F32 tensor to F16 (IEEE round-to-nearest-even via
     numpy's astype); the four excluded tensors stay F32.
  3. Writes a safetensors file with tensors in ascending original data-offset
     order and a `qvoice_codec_precision: f16` metadata stamp, plus a receipt
     JSON with the output SHA-256 + size for the catalog re-pin step.

The experiment-grade validation behind this conversion (RTF, QC, memory,
waveform SNR vs fp32) is recorded in OPTIMIZATION.md §R.

Usage:
  convert_codec_f16.py INPUT_SAFETENSORS OUTPUT_SAFETENSORS [--receipt PATH]
"""

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

EXCLUDED = re.compile(r"^decoder\.decoder\.[56]\.")
EXPECTED_TENSORS = 496
EXPECTED_EXCLUDED = 4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--receipt")
    args = parser.parse_args()

    src, dst = Path(args.input), Path(args.output)
    raw = src.read_bytes()
    (hlen,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + hlen])
    body = raw[8 + hlen :]

    names = [k for k in header if k != "__metadata__"]
    if len(names) != EXPECTED_TENSORS:
        raise SystemExit(f"unexpected tensor count {len(names)} (want {EXPECTED_TENSORS})")
    excluded = sorted(n for n in names if EXCLUDED.match(n))
    if len(excluded) != EXPECTED_EXCLUDED:
        raise SystemExit(f"unexpected excluded set {excluded}")
    non_f32 = [n for n in names if header[n]["dtype"] != "F32"]
    if non_f32:
        raise SystemExit(f"input is not the fp32 tokenizer (non-F32: {non_f32[:3]})")

    order = sorted(names, key=lambda k: header[k]["data_offsets"][0])
    new_header: dict = {
        "__metadata__": {
            **header.get("__metadata__", {}),
            "qvoice_codec_precision": "f16",
        }
    }
    chunks: list[bytes] = []
    cursor = 0
    converted = 0
    for name in order:
        info = header[name]
        start, end = info["data_offsets"]
        data = body[start:end]
        dtype = info["dtype"]
        if not EXCLUDED.match(name):
            data = np.frombuffer(data, dtype=np.float32).astype(np.float16).tobytes()
            dtype = "F16"
            converted += 1
        new_header[name] = {
            "dtype": dtype,
            "shape": info["shape"],
            "data_offsets": [cursor, cursor + len(data)],
        }
        chunks.append(data)
        cursor += len(data)

    hjson = json.dumps(new_header, separators=(",", ":")).encode()
    hjson += b" " * ((8 - len(hjson) % 8) % 8)
    with open(dst, "wb") as fh:
        fh.write(struct.pack("<Q", len(hjson)))
        fh.write(hjson)
        for chunk in chunks:
            fh.write(chunk)

    receipt = {
        "converter": "convert_codec_f16.py",
        "inputSHA256": sha256(src),
        "inputSizeBytes": src.stat().st_size,
        "outputSHA256": sha256(dst),
        "outputSizeBytes": dst.stat().st_size,
        "convertedTensors": converted,
        "excludedTensors": excluded,
        "numpyVersion": np.__version__,
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
