"""scripts/build_hybrid_model.py: the recipe selection and a deterministic, valid output."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_hybrid_model", ROOT / "scripts/build_hybrid_model.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class HybridBuildTests(unittest.TestCase):
    def test_the_synthetic_build_takes_exactly_the_recipes_tensors_and_is_deterministic(self):
        self.assertEqual(builder.self_test(), 0)

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

    def test_the_recipes_match_the_engines_selector(self):
        source = (ROOT / "Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/"
                  "Qwen3StreamingMemoryTuning.swift").read_text()
        for recipe, modules in builder.RECIPES.items():
            for module in modules:
                self.assertIn(f'"{module.split(".")[-1]}"', source, f"{recipe}: {module}")


if __name__ == "__main__":
    unittest.main()
