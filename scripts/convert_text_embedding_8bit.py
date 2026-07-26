#!/usr/bin/env python3
"""Convert a Qwen3-TTS talker artifact's BF16 text embedding to 8-bit.

Operator tooling for the Stage 2.2 artifact promotion (see
benchmarks/OPTIMIZATION.md §N). NOT a CI or packaging dependency: this script
runs on a maintainer machine to produce the artifacts that are then uploaded
to the pinned Hugging Face repos; the fail-closed catalog consumes only the
uploaded bytes' exact digests.

What it does, deterministically:
  1. Verifies `talker.model.text_embedding.weight` is BF16 [151936, 2048]
     and not already quantized.
  2. Quantizes it to affine 8-bit, group size 64 (`mlx.core.quantize`),
     replacing the key with packed weight + scales + biases.
  3. Patches config.json's `quantization` dict with the per-layer entry
     `"model.text_embedding": {group_size: 64, bits: 8, mode: affine}` —
     the loader's existing PerLayerQuantization path needs no code change.
  4. Regenerates model.safetensors.index.json for the new tensor set.
  5. Mirrors every other catalog-referenced file into the output directory
     (APFS clonefile when available) and writes a receipt JSON with the
     SHA-256 + size of every produced file for the catalog re-pin step.

Requires the python `mlx` package (records its version in the receipt).

Usage:
  convert_text_embedding_8bit.py SOURCE_MODEL_DIR OUTPUT_DIR [--receipt PATH]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

EMBEDDING_KEY = "talker.model.text_embedding.weight"
EXPECTED_SHAPE = (151936, 2048)
GROUP_SIZE = 64
BITS = 8

# Catalog-referenced files mirrored verbatim (model.safetensors, its index,
# and config.json are produced fresh instead).
MIRRORED_FILES = [
    "README.md",
    "generation_config.json",
    "merges.txt",
    "preprocessor_config.json",
    "speech_tokenizer/config.json",
    "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
]


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clone_or_copy(source: str, target: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    result = subprocess.run(["cp", "-c", source, target], capture_output=True)
    if result.returncode != 0:
        shutil.copyfile(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="installed source model directory")
    parser.add_argument("output", help="output staging directory")
    parser.add_argument("--receipt", help="receipt JSON path (default OUTPUT/.conversion-receipt.json)")
    args = parser.parse_args()

    import mlx.core as mx  # noqa: PLC0415 — optional operator dependency

    source = os.path.abspath(args.source)
    output = os.path.abspath(args.output)
    if os.path.exists(output) and os.listdir(output):
        print(f"error: output directory is not empty: {output}", file=sys.stderr)
        return 2
    os.makedirs(output, exist_ok=True)

    weights = mx.load(os.path.join(source, "model.safetensors"))
    if EMBEDDING_KEY not in weights:
        print(f"error: {EMBEDDING_KEY} missing from checkpoint", file=sys.stderr)
        return 2
    if EMBEDDING_KEY.replace(".weight", ".scales") in weights:
        print("error: text embedding already quantized", file=sys.stderr)
        return 2
    embedding = weights[EMBEDDING_KEY]
    if embedding.dtype != mx.bfloat16 or tuple(embedding.shape) != EXPECTED_SHAPE:
        print(
            f"error: unexpected embedding {embedding.dtype} {tuple(embedding.shape)}; "
            f"expected bfloat16 {EXPECTED_SHAPE}",
            file=sys.stderr,
        )
        return 2

    packed, scales, biases = mx.quantize(embedding, group_size=GROUP_SIZE, bits=BITS)
    del weights[EMBEDDING_KEY]
    weights[EMBEDDING_KEY] = packed
    weights[EMBEDDING_KEY.replace(".weight", ".scales")] = scales
    weights[EMBEDDING_KEY.replace(".weight", ".biases")] = biases

    # mlx appends ".safetensors" to the given prefix.
    produced_model = os.path.join(output, "model.safetensors")
    mx.save_safetensors(os.path.join(output, "model"), weights)
    if not os.path.exists(produced_model):
        print("error: converted checkpoint was not written", file=sys.stderr)
        return 2

    # Shard index for the new tensor set (single shard).
    itemsize = {
        "bfloat16": 2, "float16": 2, "float32": 4, "uint32": 4, "int32": 4,
    }
    weight_map = {}
    total = 0
    for key, value in weights.items():
        weight_map[key] = "model.safetensors"
        dtype_name = str(value.dtype).replace("mlx.core.", "")
        size = 1
        for dim in value.shape:
            size *= dim
        total += size * itemsize.get(dtype_name, value.itemsize if hasattr(value, "itemsize") else 4)
    index = {"metadata": {"total_size": total}, "weight_map": dict(sorted(weight_map.items()))}
    with open(os.path.join(output, "model.safetensors.index.json"), "w") as handle:
        json.dump(index, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with open(os.path.join(source, "config.json")) as handle:
        config = json.load(handle)
    quantization = config.get("quantization")
    if not isinstance(quantization, dict):
        print("error: source config has no quantization dict", file=sys.stderr)
        return 2
    quantization["model.text_embedding"] = {
        "group_size": GROUP_SIZE,
        "bits": BITS,
        "mode": "affine",
    }
    with open(os.path.join(output, "config.json"), "w") as handle:
        json.dump(config, handle, indent=2, sort_keys=False)
        handle.write("\n")

    for relative in MIRRORED_FILES:
        source_file = os.path.join(source, relative)
        if os.path.exists(source_file):
            clone_or_copy(source_file, os.path.join(output, relative))

    receipt = {
        "tool": "convert_text_embedding_8bit.py",
        "mlxVersion": mx.__version__,
        "sourceDirectory": os.path.basename(source),
        "quantization": {"layer": "model.text_embedding", "groupSize": GROUP_SIZE, "bits": BITS, "mode": "affine"},
        "files": {},
    }
    for root, _, names in os.walk(output):
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, output)
            receipt["files"][relative] = {
                "sha256": sha256_file(path),
                "sizeBytes": os.path.getsize(path),
            }
    receipt_path = args.receipt or os.path.join(output, ".conversion-receipt.json")
    with open(receipt_path, "w") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"converted: {output}")
    print(f"  model.safetensors {receipt['files']['model.safetensors']['sizeBytes']/1e6:.1f} MB")
    print(f"  receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
