#!/usr/bin/env python3
"""Build Vocello's hybrid (mixed-precision) Qwen3-TTS model from the two installed, verified artifacts
of each mode (RF-55): every tensor of the 4-bit model, except the talker layer tensors a recipe names,
which come from the 8-bit model of the same mode, quantized as that model is (affine, group size 64).
No requantization: the two artifacts were quantized from the same weights by the same scheme, so a
tensor copied from either is exactly what that artifact ships.

The output is deterministic (tensors written in sorted key order, fixed metadata), so its digest is
reproducible from the same inputs. Inputs are refused unless each source file matches its installed
integrity record (size and SHA-256) and that record names the contract's repository and revision.

usage:
  build_hybrid_model.py build --recipe attn --out <dir> [--models <installed models dir>] [--modes custom,design,base]
  build_hybrid_model.py self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "Sources/Resources/qwenvoice_contract.json"
DEFAULT_MODELS = Path.home() / "Library/Application Support/QwenVoice-Debug/models"
INTEGRITY = ".qwenvoice-model-integrity.json"
SHARED = ".qwenvoice-shared-components.json"
MODES = {"custom": "CustomVoice", "design": "VoiceDesign", "base": "Base"}
CONTRACT_IDS = {"custom": "pro_custom", "design": "pro_design", "base": "pro_clone"}
# Each recipe's talker layer modules; mirrors Qwen3MixedPrecisionRecipe in the package
# (Qwen3StreamingMemoryTuning.swift), which the diagnostic key selects with.
RECIPES = {
    "down": ("mlp.down_proj",),
    "attn": ("self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj"),
    "attn-down": ("self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj", "mlp.down_proj"),
    "mlp": ("mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"),
}
LAYER_TENSOR = re.compile(r"^talker\.(model\.layers\.(\d+)\.([a-z_]+\.[a-z_]+))\.(weight|scales|biases)$")
CHUNK = 64 * 1024 * 1024


class BuildError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def read_header(path: Path) -> tuple[dict, int]:
    with path.open("rb") as handle:
        length = struct.unpack("<Q", handle.read(8))[0]
        header = json.loads(handle.read(length))
    return header, 8 + length


def selected_module(key: str, recipe: str) -> str | None:
    """The talker-relative module path (`model.layers.3.self_attn.q_proj`) when the recipe takes this
    tensor from the 8-bit model, else None."""
    match = LAYER_TENSOR.match(key)
    if match and match.group(3) in RECIPES[recipe]:
        return match.group(1)
    return None


def write_safetensors(out: Path, sources: dict[str, tuple[Path, dict, int]]) -> int:
    """Writes the tensors `sources` maps (key -> (file, its header entry, its data start)) in sorted key
    order with a space-padded header, as safetensors does. Returns the total tensor bytes."""
    header: dict = {}
    offset = 0
    for key in sorted(sources):
        _path, entry, _start = sources[key]
        size = entry["data_offsets"][1] - entry["data_offsets"][0]
        header[key] = {"dtype": entry["dtype"], "shape": entry["shape"], "data_offsets": [offset, offset + size]}
        offset += size
    encoded = json.dumps(header, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    with out.open("wb") as handle:
        handle.write(struct.pack("<Q", len(encoded)))
        handle.write(encoded)
        for key in sorted(sources):
            path, entry, start = sources[key]
            begin, end = entry["data_offsets"]
            with path.open("rb") as source:
                source.seek(start + begin)
                remaining = end - begin
                while remaining:
                    block = source.read(min(CHUNK, remaining))
                    if not block:
                        raise BuildError(f"{path.name}: truncated tensor {key}")
                    handle.write(block)
                    remaining -= len(block)
    return offset


def verified_source(folder: Path, repo: str, revision: str) -> dict:
    """The source's integrity record, after checking model.safetensors and config.json against it."""
    record = json.loads((folder / INTEGRITY).read_text())
    if record.get("repo") != repo or record.get("revision") != revision:
        raise BuildError(f"{folder.name}: installed record names {record.get('repo')}@{record.get('revision')}, the contract {repo}@{revision}")
    entries = {entry["path"]: entry for entry in record["files"]}
    for name in ("model.safetensors", "config.json"):
        path = folder / name
        if path.stat().st_size != entries[name]["size"] or sha256(path) != entries[name]["sha256"]:
            raise BuildError(f"{folder.name}/{name} differs from its installed integrity record")
    return record


def build_mode(mode: str, recipe: str, models: Path, out: Path, contract: dict) -> dict:
    entry = next(model for model in contract["models"] if model["id"] == CONTRACT_IDS[mode])
    speed = next(variant for variant in entry["variants"] if variant["kind"] == "speed")
    four, eight = models / speed["folder"], models / entry["folder"]
    four_record = verified_source(four, speed["huggingFaceRepo"], speed["huggingFaceRevision"])
    verified_source(eight, entry["huggingFaceRepo"], entry["huggingFaceRevision"])
    four_header, four_start = read_header(four / "model.safetensors")
    eight_header, eight_start = read_header(eight / "model.safetensors")
    four_header.pop("__metadata__", None)
    eight_header.pop("__metadata__", None)
    if set(four_header) != set(eight_header):
        raise BuildError(f"{mode}: the 4-bit and 8-bit artifacts name different tensors")

    sources, modules = {}, set()
    for key, value in four_header.items():
        module = selected_module(key, recipe)
        if module:
            modules.add(module)
            sources[key] = (eight / "model.safetensors", eight_header[key], eight_start)
        else:
            sources[key] = (four / "model.safetensors", value, four_start)
    if not modules:
        raise BuildError(f"{mode}: recipe {recipe} selected nothing")
    for module in modules:  # weight, scales and biases move together
        for tensor in ("weight", "scales", "biases"):
            if f"talker.{module}.{tensor}" not in sources or sources[f"talker.{module}.{tensor}"][0].parent != eight:
                raise BuildError(f"{mode}: {module} is incomplete in the 8-bit artifact")

    folder = out / f"{speed['folder'].removesuffix('-4bit')}-hybrid-{recipe}"
    if folder.exists():
        raise BuildError(f"{folder} exists; a build never overwrites")
    folder.mkdir(parents=True)
    total = write_safetensors(folder / "model.safetensors", sources)

    config = json.loads((four / "config.json").read_text())
    eight_quant = json.loads((eight / "config.json").read_text())["quantization"]
    per_layer = {"group_size": eight_quant["group_size"], "bits": eight_quant["bits"], "mode": eight_quant["mode"]}
    for module in sorted(modules):
        config["quantization"][module] = dict(per_layer)
    (folder / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    index = {"metadata": {"total_size": total}, "weight_map": {key: "model.safetensors" for key in sorted(sources)}}
    (folder / "model.safetensors.index.json").write_text(json.dumps(index, indent=2) + "\n")
    (folder / "README.md").write_text(
        f"# Vocello hybrid ({recipe}) — Qwen3-TTS-12Hz-1.7B-{MODES[mode]}\n\n"
        "A derivative of Qwen/Qwen3-TTS (Apache-2.0) made by Vocello: the 4-bit model with the talker's "
        f"{', '.join(RECIPES[recipe])} taken from the 8-bit model of the same conversion. Development build; not published.\n")

    # Every other required file is the 4-bit artifact's own, linked where the volume allows.
    for relative in speed["requiredRelativePaths"]:
        target = folder / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(four / relative, target)
        except OSError:
            shutil.copy2(four / relative, target)
    if (four / SHARED).exists():
        shutil.copy2(four / SHARED, folder / SHARED)

    files = [{"path": relative, "size": (folder / relative).stat().st_size, "sha256": sha256(folder / relative)}
             for relative in sorted(speed["requiredRelativePaths"])]
    weights_digest = next(item["sha256"] for item in files if item["path"] == "model.safetensors")
    record = dict(four_record, repo=f"local/vocello-hybrid-{recipe}-{MODES[mode]}", revision=weights_digest,
                  target_folder=folder.name, created_at_utc="1970-01-01T00:00:00Z", files=files)
    (folder / INTEGRITY).write_text(json.dumps(record, indent=1) + "\n")
    return {"mode": mode, "folder": folder.name, "repo": record["repo"], "revision": weights_digest,
            "bytes": sum(item["size"] for item in files), "selectedModules": len(modules),
            "weightsBytes": total, "addedWeightBytes": total - (four / "model.safetensors").stat().st_size + four_start}


def development_contract(contract: dict, built: list[dict], out: Path, recipe: str) -> Path:
    """A copy of the bundled contract whose Speed variants are the hybrid folders, for `vocello --manifest`."""
    by_mode = {item["mode"]: item for item in built}
    for mode, model_id in CONTRACT_IDS.items():
        if mode not in by_mode:
            continue
        item = by_mode[mode]
        entry = next(model for model in contract["models"] if model["id"] == model_id)
        speed = next(variant for variant in entry["variants"] if variant["kind"] == "speed")
        speed.update(folder=item["folder"], huggingFaceRepo=item["repo"], huggingFaceRevision=item["revision"],
                     artifactVersion=f"hybrid-{recipe}", estimatedDownloadBytes=item["bytes"])
    path = out / f"qwenvoice_contract.hybrid-{recipe}.json"
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n")
    return path


def build(args: argparse.Namespace) -> int:
    if args.recipe not in RECIPES:
        raise BuildError(f"unknown recipe {args.recipe}")
    out, models = Path(args.out).resolve(), Path(args.models).resolve()
    contract = json.loads(CONTRACT.read_text())
    built = [build_mode(mode, args.recipe, models, out, contract) for mode in args.modes.split(",")]
    # The installed Quality folders, linked so the development data root still offers them.
    for mode in args.modes.split(","):
        entry = next(model for model in contract["models"] if model["id"] == CONTRACT_IDS[mode])
        link = out / entry["folder"]
        if not link.exists():
            link.symlink_to(models / entry["folder"], target_is_directory=True)
    manifest = development_contract(json.loads(CONTRACT.read_text()), built, out, args.recipe)
    print(json.dumps({"recipe": args.recipe, "contract": str(manifest), "built": built}, indent=1))
    return 0


def self_test() -> int:
    """Two synthetic artifacts that differ only in their bytes: the hybrid takes exactly the recipe's
    tensors from the 8-bit one, writes a valid, deterministic file and names each module in its config."""
    def tensor_file(path: Path, fill: int) -> None:
        keys = [f"talker.model.layers.0.{module}.{part}" for module in RECIPES["attn-down"] + ("mlp.up_proj",)
                for part in ("weight", "scales", "biases")] + ["talker.model.norm.weight", "talker.code_predictor.lm_head.0.weight"]
        sources, scratch = {}, path.with_suffix(".raw")
        scratch.write_bytes(bytes([fill]) * 4 * len(keys))
        for index, key in enumerate(sorted(keys)):
            sources[key] = (scratch, {"dtype": "U32", "shape": [1], "data_offsets": [4 * index, 4 * index + 4]}, 0)
        write_safetensors(path, sources)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tensor_file(root / "four.safetensors", 4)
        tensor_file(root / "eight.safetensors", 8)
        four_header, four_start = read_header(root / "four.safetensors")
        eight_header, eight_start = read_header(root / "eight.safetensors")
        outputs = []
        for name in ("a", "b"):
            sources = {key: ((root / "eight.safetensors", eight_header[key], eight_start) if selected_module(key, "attn")
                             else (root / "four.safetensors", value, four_start)) for key, value in four_header.items()}
            write_safetensors(root / f"{name}.safetensors", sources)
            outputs.append(sha256(root / f"{name}.safetensors"))
        assert outputs[0] == outputs[1], "deterministic"
        header, start = read_header(root / "a.safetensors")
        data = (root / "a.safetensors").read_bytes()
        for key, entry in header.items():
            byte = data[start + entry["data_offsets"][0]]
            expected = 8 if selected_module(key, "attn") else 4
            assert byte == expected, (key, byte)
        assert selected_module("talker.model.layers.12.self_attn.v_proj.scales", "attn") == "model.layers.12.self_attn.v_proj"
        assert selected_module("talker.model.layers.12.mlp.down_proj.weight", "attn") is None
        assert selected_module("talker.code_predictor.model.layers.0.self_attn.q_proj.weight", "attn") is None
        assert selected_module("talker.model.layers.3.mlp.down_proj.biases", "attn-down") == "model.layers.3.mlp.down_proj"
        assert len(start.to_bytes(8, "little")) == 8 and (start - 8) % 8 == 0, "header padded to 8 bytes"
    print("self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("build")
    run.add_argument("--recipe", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--models", default=str(DEFAULT_MODELS))
    run.add_argument("--modes", default="custom,design,base")
    commands.add_parser("self-test")
    args = parser.parse_args()
    try:
        return build(args) if args.command == "build" else self_test()
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
