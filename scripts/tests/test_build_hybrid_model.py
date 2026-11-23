"""scripts/build_hybrid_model.py: the recipe selection and a deterministic, valid output."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_hybrid_model", ROOT / "scripts/build_hybrid_model.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class HybridBuildTests(unittest.TestCase):
    def test_the_synthetic_build_takes_exactly_the_recipes_tensors_and_is_deterministic(self):
        self.assertEqual(builder.self_test(), 0)

    def test_the_sources_are_the_3_0_packages_in_the_research_folder(self):
        """RF-59: the shipped contract names only the hybrids; the builder reads the 4-bit and 8-bit
        sources from the last two-package contract and the research folder."""
        contract = json.loads(builder.CONTRACT.read_text())
        for model_id in builder.CONTRACT_IDS.values():
            entry = next(model for model in contract["models"] if model["id"] == model_id)
            speed = next(variant for variant in entry["variants"] if variant["kind"] == "speed")
            self.assertTrue(speed["folder"].endswith("-4bit"), speed["folder"])
            self.assertTrue(entry["folder"].endswith("-8bit"), entry["folder"])
        self.assertEqual(builder.DEFAULT_MODELS.parent.name, "QwenVoice-Research")

    def test_a_recipe_selects_talker_layer_modules_only(self):
        self.assertEqual(builder.selected_module("talker.model.layers.27.self_attn.o_proj.weight", "attn"),
                         "model.layers.27.self_attn.o_proj")
        self.assertIsNone(builder.selected_module("talker.model.layers.27.mlp.down_proj.weight", "attn"))
        self.assertEqual(builder.selected_module("talker.model.layers.0.mlp.down_proj.scales", "attn-down"),
                         "model.layers.0.mlp.down_proj")
        self.assertIsNone(builder.selected_module("talker.code_predictor.model.layers.0.self_attn.q_proj.weight", "attn"))
        self.assertIsNone(builder.selected_module("talker.model.text_embedding.weight", "attn-down"))

    def test_a_built_revision_has_the_form_the_contract_registry_requires(self):
        # ContractBackedModelRegistry refuses any revision that is not 40 lowercase hex characters.
        files = [{"path": "model.safetensors", "size": 3, "sha256": "a" * 64},
                 {"path": "config.json", "size": 2, "sha256": "b" * 64}]
        revision = builder.content_revision(files)
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        self.assertEqual(revision, builder.content_revision(list(reversed(files))), "independent of file order")
        changed = [dict(files[0], sha256="c" * 64), files[1]]
        self.assertNotEqual(revision, builder.content_revision(changed), "any byte changes it")
        registry = (ROOT / "Sources/QwenVoiceCore/ContractBackedModelRegistry.swift").read_text()
        self.assertIn("revision.count == 40", registry, "the registry's rule this mirrors")

    def test_a_built_artifact_names_qwen3_tts_as_the_runtime_profile_requires(self):
        # Qwen3TTSRuntimeProfile refuses a model whose folder or repository does not name Qwen3-TTS.
        folder = "Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn"
        self.assertEqual(builder.local_repo(folder), f"local/{folder}")
        self.assertIn("qwen3-tts", builder.local_repo(folder).lower())
        profile = (ROOT / "Sources/QwenVoiceCore/Qwen3TTSRuntimeProfile.swift").read_text()
        self.assertIn('descriptor.huggingFaceRepo.localizedCaseInsensitiveContains("Qwen3-TTS")', profile,
                      "the profile's rule this mirrors")

    def test_a_published_card_names_its_licence_sources_and_recipe(self):
        card = builder.model_card(
            "owner", "Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn", "attn", 28, 176_000_000,
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit", "a" * 40),
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit", "b" * 40))
        front, body = card.split("---\n")[1], card.split("---\n")[2]
        self.assertIn("license: apache-2.0", front)
        self.assertIn("- owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit\n- owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit", front)
        self.assertTrue(body.startswith("# owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn\n"))
        for text in ("a" * 40, "b" * 40, "`self_attn.v_proj`", "28 layers", "176 MB", "AudioSeal", "MIT", "nobody listened"):
            self.assertIn(text, body)
        self.assertNotIn("Development build", card)

        io_card = builder.model_card(
            "owner", "Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn-io", "attn-io", 28, 200_280_000,
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit", "a" * 40),
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit", "b" * 40))
        self.assertIn("`text_projection.linear_fc1`", io_card)
        self.assertIn("`code_predictor.lm_head`", io_card)
        self.assertNotIn("the code predictor's included, is the 4-bit artifact's own", io_card)

        edge_card = builder.model_card(
            "owner", "Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn-io-edge", "attn-io-edge", 28, 275_780_000,
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit", "a" * 40),
            ("owner/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit", "b" * 40))
        self.assertIn("edge layers 0, 1, 26, 27", edge_card)
        self.assertIn("`mlp.gate_proj`", edge_card)

    def test_attn_io_and_attn_io_edge_select_io_biases_and_edge_mlps(self):
        # Biased I/O modules carry `.bias` alongside `.weight/.scales/.biases`.
        for mod in (
            "text_projection.linear_fc1",
            "text_projection.linear_fc2",
            "code_predictor.small_to_mtp_projection",
        ):
            for part in ("weight", "scales", "biases", "bias"):
                key = f"talker.{mod}.{part}"
                self.assertEqual(builder.selected_module(key, "attn-io"), mod)
                self.assertEqual(builder.selected_module(key, "attn-io-edge"), mod)
                self.assertIsNone(builder.selected_module(key, "attn"))

        # Codec heads and lm_head.0..14 are promoted; code predictor layers & embeddings stay 4-bit.
        self.assertEqual(builder.selected_module("talker.codec_head.weight", "attn-io"), "codec_head")
        self.assertEqual(builder.selected_module("talker.code_predictor.lm_head.14.scales", "attn-io"),
                         "code_predictor.lm_head.14")
        self.assertIsNone(builder.selected_module("talker.code_predictor.model.layers.0.self_attn.q_proj.weight", "attn-io"))
        self.assertIsNone(builder.selected_module("talker.code_predictor.model.codec_embedding.0.weight", "attn-io-edge"))
        self.assertIsNone(builder.selected_module("talker.model.text_embedding.weight", "attn-io-edge"))

        # Edge layers {0, 1, 26, 27} promote MLPs in attn-io-edge only.
        for layer in range(28):
            expected_edge = f"model.layers.{layer}.mlp.gate_proj" if layer in {0, 1, 26, 27} else None
            key = f"talker.model.layers.{layer}.mlp.gate_proj.weight"
            self.assertEqual(builder.selected_module(key, "attn-io-edge"), expected_edge)
            self.assertIsNone(builder.selected_module(key, "attn-io"))

    def test_build_mode_copies_io_biases_and_avoids_non_layer_index_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            out = root / "out"
            four = models / "Qwen3-TTS-12Hz-1.7B-Base-4bit"
            eight = models / "Qwen3-TTS-12Hz-1.7B-Base-8bit"
            four.mkdir(parents=True)
            eight.mkdir(parents=True)

            keys = []
            for layer in (0, 2, 27):
                for mod in builder.ATTENTION_MODULES + builder.MLP_MODULES:
                    for part in ("weight", "scales", "biases"):
                        keys.append(f"talker.model.layers.{layer}.{mod}.{part}")
            for mod in ("text_projection.linear_fc1", "text_projection.linear_fc2",
                        "code_predictor.small_to_mtp_projection"):
                for part in ("weight", "scales", "biases", "bias"):
                    keys.append(f"talker.{mod}.{part}")
            for mod in ("codec_head", "code_predictor.lm_head.0", "code_predictor.lm_head.1"):
                for part in ("weight", "scales", "biases"):
                    keys.append(f"talker.{mod}.{part}")
            keys.append("talker.code_predictor.model.layers.0.mlp.down_proj.weight")

            def write_fixture(folder: Path, fill: int, bits: int, repo: str, rev: str) -> None:
                raw = folder / "raw.bin"
                raw.write_bytes(bytes([fill]) * 4 * len(keys))
                sources = {
                    key: (raw, {"dtype": "U32", "shape": [1], "data_offsets": [4 * i, 4 * i + 4]}, 0)
                    for i, key in enumerate(sorted(keys))
                }
                builder.write_safetensors(folder / "model.safetensors", sources)
                raw.unlink()
                cfg = {"quantization": {"group_size": 64, "bits": bits, "mode": "affine"}}
                (folder / "config.json").write_text(json.dumps(cfg))
                files = [
                    {"path": name, "size": (folder / name).stat().st_size, "sha256": builder.sha256(folder / name)}
                    for name in ("config.json", "model.safetensors")
                ]
                (folder / builder.INTEGRITY).write_text(json.dumps({
                    "repo": repo, "revision": rev, "files": files,
                }))

            write_fixture(four, 4, 4, "owner/Qwen3-TTS-12Hz-1.7B-Base-4bit", "a" * 40)
            write_fixture(eight, 8, 8, "owner/Qwen3-TTS-12Hz-1.7B-Base-8bit", "b" * 40)
            contract = {
                "models": [{
                    "id": "pro_clone",
                    "folder": eight.name,
                    "huggingFaceRepo": "owner/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                    "huggingFaceRevision": "b" * 40,
                    "variants": [{
                        "kind": "speed",
                        "folder": four.name,
                        "huggingFaceRepo": "owner/Qwen3-TTS-12Hz-1.7B-Base-4bit",
                        "huggingFaceRevision": "a" * 40,
                        "requiredRelativePaths": ["config.json", "model.safetensors"],
                    }],
                }]
            }
            for recipe in ("attn-io", "attn-io-edge"):
                result = builder.build_mode("base", recipe, models, out, contract, owner="owner")
                built = out / result["folder"]
                header, start = builder.read_header(built / "model.safetensors")
                blob = (built / "model.safetensors").read_bytes()
                for key, entry in header.items():
                    byte = blob[start + entry["data_offsets"][0]]
                    expected = 8 if builder.selected_module(key, recipe) else 4
                    self.assertEqual(byte, expected, f"{recipe}: {key}")
                cfg = json.loads((built / "config.json").read_text())
                self.assertEqual(cfg["quantization"]["codec_head"]["bits"], 8)
                self.assertEqual(cfg["quantization"]["text_projection.linear_fc1"]["bits"], 8)
                self.assertEqual(cfg["quantization"]["code_predictor.lm_head.0"]["bits"], 8)
                self.assertEqual("model.layers.0.mlp.gate_proj" in cfg["quantization"], recipe == "attn-io-edge")
                self.assertNotIn("model.layers.2.mlp.gate_proj", cfg["quantization"])
                card = (built / "README.md").read_text()
                self.assertIn("3 layers", card)

    def test_the_recipes_match_the_engines_selector(self):
        source = (ROOT / "Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/"
                  "Qwen3StreamingMemoryTuning.swift").read_text()
        for recipe in builder.RECIPES:
            self.assertIn(f'"{recipe}"' if "-" in recipe else f"case {recipe}", source, recipe)
        for token in (
            '"q_proj"', '"k_proj"', '"v_proj"', '"o_proj"',
            '"gate_proj"', '"up_proj"', '"down_proj"',
            '"text_projection.linear_fc1"', '"text_projection.linear_fc2"',
            '"codec_head"', '"code_predictor.small_to_mtp_projection"',
            '"code_predictor.lm_head."',
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
