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

    def test_pinned_record_is_the_newest_canonical_and_the_readme_block_is_fresh(self) -> None:
        self.assertEqual(MODULE.newest_canonical_record(), MODULE.RTF_RECORD)
        medians, _ = MODULE.load_rtf_medians(MODULE.RTF_RECORD)
        self.assertEqual(
            MODULE.README_PATH.read_text(encoding="utf-8"), MODULE.render_readme(medians),
            "README rtf-chart block is stale — run scripts/generate_readme_charts.py",
        )
        alt = MODULE.readme_alt_text(medians)
        self.assertIn("lower is faster", alt)
        self.assertNotIn("×", alt)
        for value in medians.values():
            self.assertLess(value, 1.0, "the chart claims every bar sits below the real-time line")

    def test_rtf_chart_uses_the_standard_definition(self) -> None:
        svg = MODULE.render_all()["rtf-by-mode-light.svg"]
        self.assertIn("lower is faster", svg)
        self.assertIn("1.0 · realtime", svg)
        self.assertNotIn("×", svg)

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
