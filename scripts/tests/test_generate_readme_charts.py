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
        self.assertIn(MODULE.chart_pool()[0][-8:], rendered["rtf-by-mode-dark.svg"])
        self.assertIn("benchmarks/HISTORY.md", rendered["rtf-by-mode-dark.svg"])
        self.assertIn(MODULE.LONGFORM_RUN_ID[-8:], rendered["longform-memory-dark.svg"])

    def test_the_readme_block_is_fresh_for_the_pooled_medians(self) -> None:
        medians, _ = MODULE.load_rtf_medians(MODULE.chart_pool())
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
                 classification: str = "canonical", key: str = "lineage-a",
                 rtf: float = 0.5, app_build: str = "24", lock: str = "lock-a") -> None:
    marketing = {
        "mac-mini-m2-8gb": "Mac mini (M2, 8 GB)",
        "mac-mini-m6-16gb": "Mac mini (M6, 16 GB)",
    }[profile]
    (directory / f"{run_id}.json").write_text(json.dumps({
        "run": {
            "id": run_id, "kind": "ui-generation", "finishedAt": finished_at,
            "classification": classification, "rtfDefinition": "wall/audio",
        },
        "hardware": {"profileID": profile, "marketingName": marketing},
        "toolchain": {"appVersion": "3.0.0", "appBuild": app_build},
        "inputs": {"dependencyLockHash": lock},
        "comparison": {"key": key},
        "takes": [
            {"cell": f"{mode}/{length}/warm#{index}", "metrics": {"rtf": rtf + index / 100}}
            for mode in MODULE.MODES for length in MODULE.LENGTHS for index in range(3)
        ],
    }), encoding="utf-8")


class ChartPoolTests(unittest.TestCase):
    """The public medians pool recent canonical records of one lineage (audit #72)."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.records = Path(self.temporary.name)
        write_record(self.records, "macos-xcui-benchmark-20260801-000000-olderm2", "mac-mini-m2-8gb",
                     "2026-08-01T00:00:00Z", key="lineage-old")
        write_record(self.records, "macos-xcui-benchmark-20260914-000000-latestm2", "mac-mini-m2-8gb",
                     "2026-09-14T06:35:58Z")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def pool(self) -> list[str]:
        return MODULE.chart_pool(self.records)

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
        anchor = MODULE.load_record(MODULE.chart_pool()[0])
        self.assertIn(MODULE.hardware_label(anchor), MODULE.render_all()["rtf-by-mode-dark.svg"])

    def test_without_a_canonical_profile_record_the_anchor_is_the_newest_canonical(self) -> None:
        self.assertEqual(self.pool(), ["macos-xcui-benchmark-20260914-000000-latestm2"])
        write_record(self.records, "macos-xcui-benchmark-20260920-000000-m6partial", "mac-mini-m6-16gb",
                     "2026-09-20T00:00:00Z", classification="focused")
        self.assertEqual(self.pool(), ["macos-xcui-benchmark-20260914-000000-latestm2"])

    def test_the_first_canonical_m6_record_becomes_the_anchor_and_fails_the_check(self) -> None:
        first_m6 = "macos-xcui-benchmark-20260923-000000-firstm6"
        write_record(self.records, first_m6, "mac-mini-m6-16gb", "2026-09-23T00:00:00Z")
        # A later M2 record never competes with the canonical profile's series,
        # and M2 records never join an M6 pool even under an equal key.
        write_record(self.records, "macos-xcui-benchmark-20260930-000000-laterm2", "mac-mini-m2-8gb",
                     "2026-09-30T00:00:00Z")
        self.assertEqual(self.pool(), [first_m6])
        stderr = io.StringIO()
        with (
            mock.patch.object(MODULE, "RECORDS_DIR", self.records),
            mock.patch("sys.argv", ["generate_readme_charts.py", "--check"]),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(MODULE.main(), 1)
        self.assertIn(first_m6, stderr.getvalue())
        self.assertIn("Engineering.jsx", stderr.getvalue())

    def test_the_pool_holds_one_lineage_up_to_the_pool_size(self) -> None:
        for day in range(15, 22):
            write_record(self.records, f"macos-xcui-benchmark-202609{day}-000000-same{day}",
                         "mac-mini-m2-8gb", f"2026-09-{day}T00:00:00Z")
        pool = self.pool()
        self.assertEqual(len(pool), MODULE.POOL_SIZE)
        self.assertEqual(pool[0], "macos-xcui-benchmark-20260921-000000-same21")
        # A lineage change resets the pool to the new anchor alone.
        write_record(self.records, "macos-xcui-benchmark-20260922-000000-newkey", "mac-mini-m2-8gb",
                     "2026-09-22T00:00:00Z", key="lineage-b")
        self.assertEqual(self.pool(), ["macos-xcui-benchmark-20260922-000000-newkey"])

    def test_the_pool_never_spans_builds_or_dependency_pins(self) -> None:
        """A lineage key leaves the app build and pins out; the public pool does not."""
        write_record(self.records, "macos-xcui-benchmark-20260915-000000-samebuild", "mac-mini-m2-8gb",
                     "2026-09-15T00:00:00Z")
        self.assertEqual(len(self.pool()), 2)
        rebuilt = "macos-xcui-benchmark-20260916-000000-newbuild"
        write_record(self.records, rebuilt, "mac-mini-m2-8gb", "2026-09-16T00:00:00Z", app_build="25")
        self.assertEqual(self.pool(), [rebuilt])
        repinned = "macos-xcui-benchmark-20260917-000000-newlock"
        write_record(self.records, repinned, "mac-mini-m2-8gb", "2026-09-17T00:00:00Z",
                     app_build="25", lock="lock-b")
        self.assertEqual(self.pool(), [repinned])

    def test_the_website_provenance_mirrors_the_chart_footer(self) -> None:
        medians = {f"{mode}/{length}/warm": 0.5 for mode in MODULE.MODES for length in MODULE.LENGTHS}
        one = ["macos-xcui-benchmark-20260914-000000-latestm2"]
        self.assertIn("Record latestm2", MODULE.website_medians_text(one, medians))
        pooled = ["macos-xcui-benchmark-20260915-000000-pooledm2", *one]
        self.assertEqual(MODULE.provenance_text(pooled), "median of 2 records through pooledm2")
        self.assertIn("Median of 2 records through pooledm2", MODULE.website_medians_text(pooled, medians))

    def test_pooled_medians_take_every_take_of_the_pool(self) -> None:
        write_record(self.records, "macos-xcui-benchmark-20260915-000000-second", "mac-mini-m2-8gb",
                     "2026-09-15T00:00:00Z", rtf=0.7)
        pool = self.pool()
        self.assertEqual(len(pool), 2)
        medians, derived = MODULE.load_rtf_medians(pool, self.records)
        self.assertFalse(derived)
        # Takes 0.50, 0.51, 0.52 and 0.70, 0.71, 0.72: the pooled median, not either record's.
        self.assertAlmostEqual(medians["custom/short/warm"], 0.61)


if __name__ == "__main__":
    unittest.main()
