"""Self-tests for the deterministic README chart generator."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        # The chart renders the warm cells; a record's single cold take may sit above 1.0.
        for mode in MODULE.MODES:
            for length in MODULE.LENGTHS:
                value = medians[f"{mode}/{length}/warm"]
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


def write_record(directory: Path, run_id: str, profile: str, finished_at: str,
                 classification: str = "canonical") -> None:
    marketing = {
        "mac-mini-m2-8gb": "Mac mini (M2, 8 GB)",
        "mac-mini-m6-16gb": "Mac mini (M6, 16 GB)",
    }[profile]
    (directory / f"{run_id}.json").write_text(json.dumps({
        "run": {"id": run_id, "finishedAt": finished_at, "classification": classification},
        "hardware": {"profileID": profile, "marketingName": marketing},
    }), encoding="utf-8")


class CanonicalRecordSelectionTests(unittest.TestCase):
    PINNED = "macos-xcui-benchmark-20260914-062114-pinned00"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.records = Path(self.temporary.name)
        write_record(self.records, "macos-xcui-benchmark-20260801-000000-olderm2", "mac-mini-m2-8gb",
                     "2026-08-01T00:00:00Z")
        write_record(self.records, self.PINNED, "mac-mini-m2-8gb", "2026-09-14T06:35:58Z")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def newest(self) -> str:
        return MODULE.newest_canonical_record(self.records, self.PINNED)

    def test_registry_names_the_m6_as_canonical_and_the_chart_labels_its_own_record(self) -> None:
        self.assertEqual(MODULE.canonical_macos_profile_id(), "mac-mini-m6-16gb")
        self.assertEqual(
            MODULE.hardware_label({"hardware": {"marketingName": "Mac mini (M2, 8 GB)"}}),
            "Mac mini M2, 8 GB",
        )
        self.assertEqual(
            MODULE.hardware_label({"hardware": {"marketingName": "Mac mini (M6, 16 GB)"}}),
            "Mac mini M6, 16 GB",
        )
        pinned = MODULE.load_record(MODULE.RTF_RECORD)
        self.assertIn(MODULE.hardware_label(pinned), MODULE.render_all()["rtf-by-mode-dark.svg"])

    def test_without_a_canonical_profile_record_the_pin_falls_back_to_its_own_profile(self) -> None:
        self.assertEqual(self.newest(), self.PINNED)
        write_record(self.records, "macos-xcui-benchmark-20260920-000000-m6partial", "mac-mini-m6-16gb",
                     "2026-09-20T00:00:00Z", classification="focused")
        self.assertEqual(self.newest(), self.PINNED)
        write_record(self.records, "macos-xcui-benchmark-20260915-000000-newerm2", "mac-mini-m2-8gb",
                     "2026-09-15T00:00:00Z")
        self.assertEqual(self.newest(), "macos-xcui-benchmark-20260915-000000-newerm2")

    def test_the_first_canonical_m6_record_forces_a_repin(self) -> None:
        first_m6 = "macos-xcui-benchmark-20260923-000000-firstm6"
        write_record(self.records, first_m6, "mac-mini-m6-16gb", "2026-09-23T00:00:00Z")
        # A later M2 record never competes with the canonical profile's series.
        write_record(self.records, "macos-xcui-benchmark-20260930-000000-laterm2", "mac-mini-m2-8gb",
                     "2026-09-30T00:00:00Z")
        self.assertEqual(self.newest(), first_m6)
        stderr = io.StringIO()
        with (
            mock.patch.object(MODULE, "RECORDS_DIR", self.records),
            mock.patch.object(MODULE, "RTF_RECORD", self.PINNED),
            mock.patch("sys.argv", ["generate_readme_charts.py", "--check"]),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(MODULE.main(), 1)
        self.assertIn(first_m6, stderr.getvalue())
        self.assertIn("update the pin", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
