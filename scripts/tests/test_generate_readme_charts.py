"""Self-tests for the deterministic README chart generator."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SPEC = importlib.util.spec_from_file_location(
    "generate_readme_charts", ROOT / "scripts/generate_readme_charts.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateReadmeChartsTests(unittest.TestCase):
    def test_rendering_is_deterministic(self) -> None:
        first = MODULE.render_all()
        second = MODULE.render_all()
        self.assertEqual(first, second)

    def test_every_chart_has_both_theme_variants(self) -> None:
        rendered = MODULE.render_all()
        for chart_name in MODULE.CHARTS:
            for theme in ("dark", "light"):
                name = f"{chart_name}-{theme}.svg"
                self.assertIn(name, rendered)
                content = rendered[name]
                self.assertTrue(content.startswith("<svg "), name)
                self.assertTrue(content.rstrip().endswith("</svg>"), name)

    def test_charts_cite_their_data_provenance(self) -> None:
        rendered = MODULE.render_all()
        self.assertIn(MODULE.RTF_RECORD[-8:], rendered["rtf-by-mode-dark.svg"])
        self.assertIn("benchmarks/HISTORY.md", rendered["rtf-by-mode-dark.svg"])
        self.assertIn(MODULE.LONGFORM_RUN_ID[-8:], rendered["longform-memory-dark.svg"])

    def test_committed_charts_are_fresh(self) -> None:
        rendered = MODULE.render_all()
        for name, content in rendered.items():
            on_disk = MODULE.OUTPUT_DIR / name
            self.assertTrue(on_disk.is_file(), f"missing committed chart: {name}")
            self.assertEqual(
                on_disk.read_text(encoding="utf-8"), content,
                f"committed chart is stale: {name} — run scripts/generate_readme_charts.py",
            )


if __name__ == "__main__":
    unittest.main()
