"""scripts/build_hybrid_model.py: the recipe selection and a deterministic, valid output."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_hybrid_model", ROOT / "scripts/build_hybrid_model.py")
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

    def test_the_recipes_match_the_engines_selector(self):
        source = (ROOT / "Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/"
                  "Qwen3StreamingMemoryTuning.swift").read_text()
        for recipe, modules in builder.RECIPES.items():
            for module in modules:
                self.assertIn(f'"{module.split(".")[-1]}"', source, f"{recipe}: {module}")


if __name__ == "__main__":
    unittest.main()
