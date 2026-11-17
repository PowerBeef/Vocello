"""Self-tests for the deterministic README chart generator."""

from __future__ import annotations

import contextlib
import html
import importlib.util
import io
import json
import re
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
        self.assertEqual(MODULE.render_all(), MODULE.render_all())

    def test_every_image_is_self_contained_and_labelled(self) -> None:
        """GitHub renders README SVGs as images: no script, no outside fetch, a name for each."""
        for name, content in MODULE.render_all().items():
            self.assertTrue(content.startswith("<svg "), name)
            self.assertTrue(content.rstrip().endswith("</svg>"), name)
            self.assertNotIn("<script", content, name)
            self.assertNotIn("—", content, name)
            for target in re.findall(r'href="([^"]*)"', content):
                self.assertTrue(target.startswith("data:image/png;base64,"), f"{name} fetches {target[:40]}")
            if name.startswith("icons/"):
                self.assertIn('aria-hidden="true"', content, name)
            else:
                self.assertIn('role="img"', content, name)
                self.assertRegex(content, r"<title id=\"title\">[^<]+</title>", name)
                self.assertRegex(content, r"<desc id=\"desc\">[^<]+</desc>", name)

    def test_charts_cite_their_data_provenance(self) -> None:
        rendered = MODULE.render_all()
        for name in ("rtf-by-mode.svg", "rtf-by-mode-narrow.svg", "performance.svg"):
            self.assertIn(MODULE.chart_pool()[0][-8:], rendered[name], name)
        self.assertIn("benchmarks/HISTORY.md", rendered["rtf-by-mode.svg"])
        self.assertIn(MODULE.measured().memory_record, rendered["performance.svg"])

    def test_the_performance_card_draws_the_pooled_numbers(self) -> None:
        pool = MODULE.chart_pool()
        measured = MODULE.measured()
        self.assertAlmostEqual(measured.seconds_per_minute, MODULE.median_warm_rtf(pool) * 60)
        first = MODULE.first_audio_seconds(pool)
        self.assertEqual((measured.first_audio_low, measured.first_audio_high), (min(first.values()), max(first.values())))
        # Built-in Voice answers first and Voice Cloning last, in the newest records.
        self.assertLess(first["custom"], first["clone"])
        self.assertLess(measured.peak_low_gb, measured.peak_high_gb)
        self.assertLess(measured.peak_high_gb, 16, "a peak above the benchmark Mac's memory is a unit error")
        svg = MODULE.render_all()["performance.svg"]
        for figure in MODULE.art.performance_figures(measured):
            self.assertIn(html.escape(figure), svg)

    def test_the_calls_to_action_follow_the_product_facts(self) -> None:
        facts = json.loads(MODULE.FACTS_PATH.read_text(encoding="utf-8"))
        version = facts["stableMacRelease"]["version"]
        rendered = MODULE.render_all()
        self.assertIn(f"Vocello {version} · macOS 26+", rendered["download-mac.svg"])
        self.assertIn(f"vocello {version} · macOS 26+", rendered["install-cli.svg"])
        self.assertIn("iOS 26+", rendered["join-iphone-beta.svg"])
        readme = MODULE.README_PATH.read_text(encoding="utf-8")
        self.assertIn(f"releases/download/v{version}/Vocello-macos26.dmg", readme)

    def test_every_readme_image_exists(self) -> None:
        readme = MODULE.README_PATH.read_text(encoding="utf-8")
        paths = set(re.findall(r'(?:src|srcset)="(docs/[^"]+)"', readme))
        self.assertTrue(paths)
        for path in sorted(paths):
            self.assertTrue((ROOT / path).is_file(), f"README shows a missing image: {path}")

    def test_the_readme_block_is_fresh_for_the_pooled_medians(self) -> None:
        pool = MODULE.chart_pool()
        medians, _ = MODULE.load_rtf_medians(pool)
        self.assertEqual(
            MODULE.README_PATH.read_text(encoding="utf-8"),
            MODULE.render_readme(medians, MODULE.pool_model_label(pool)),
            "README rtf-chart block is stale: run scripts/generate_readme_charts.py",
        )
        alt = MODULE.readme_alt_text(medians)
        self.assertIn("lower is faster", alt)
        self.assertNotIn("×", alt)
        for mode in MODULE.MODES:
            for length in MODULE.LENGTHS:
                value = medians[f"{mode}/{length}/warm"]
                self.assertLess(value, 1.0, "the chart claims every bar sits below the real-time line")

    def test_rtf_chart_uses_the_standard_definition(self) -> None:
        for name in ("rtf-by-mode.svg", "rtf-by-mode-narrow.svg"):
            svg = MODULE.render_all()[name]
            self.assertIn("lower is faster", svg)
            self.assertIn("1.0 · real time", svg)
            self.assertNotIn("×", svg)

    def test_committed_images_are_fresh_and_nothing_else_is_there(self) -> None:
        rendered = MODULE.render_all()
        for name, content in rendered.items():
            on_disk = MODULE.OUTPUT_DIR / name
            self.assertTrue(on_disk.is_file(), f"missing committed image: {name}")
            self.assertEqual(
                on_disk.read_text(encoding="utf-8"), content,
                f"committed image is stale: {name}; run scripts/generate_readme_charts.py",
            )
        committed = {path.relative_to(MODULE.OUTPUT_DIR).as_posix() for path in MODULE.OUTPUT_DIR.rglob("*.svg")}
        self.assertEqual(committed - set(rendered), set(), "every SVG under docs/readme/ is generated")


class MemoryRecordTests(unittest.TestCase):
    """The memory span comes from the newest passed, qualified record of the release on the profile."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.records = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, run_id: str, finished_at: str, *, version: str = "3.1.0", qualified: bool = True,
              status: str = "passed", profile: str = "mac-mini-m6-16gb", clone_mb: float = 4096.0) -> None:
        peaks = {"custom": 2048.0, "design": 3072.0, "clone": clone_mb}
        (self.records / f"{run_id}.json").write_text(json.dumps({
            "run": {"id": run_id, "finishedAt": finished_at, "status": status, "platform": "macos"},
            "hardware": {"profileID": profile},
            "toolchain": {"appVersion": version},
            "evidence": {"memoryQualified": qualified},
            "takes": [{"mode": mode, "metrics": {"kernelPhysFootprintPeakMB": mb}} for mode, mb in peaks.items()],
        }), encoding="utf-8")

    def test_the_newest_qualifying_record_wins(self) -> None:
        self.write("mac-memory-qualification-a", "2026-11-10T00:00:00Z", clone_mb=5120.0)
        self.write("mac-memory-qualification-b", "2026-11-12T00:00:00Z")
        self.write("mac-memory-qualification-c", "2026-11-13T00:00:00Z", qualified=False)
        self.write("mac-memory-qualification-d", "2026-11-14T00:00:00Z", status="failed")
        self.write("mac-memory-qualification-e", "2026-11-15T00:00:00Z", version="3.0.2")
        self.write("mac-memory-qualification-f", "2026-11-16T00:00:00Z", profile="mac-mini-m2-8gb")
        run_id, peaks = MODULE.memory_peaks("mac-mini-m6-16gb", "3.1", self.records)
        self.assertEqual(run_id, "mac-memory-qualification-b")
        self.assertEqual(peaks, {"custom": 2.0, "design": 3.0, "clone": 4.0})

    def test_no_qualifying_record_fails_closed(self) -> None:
        self.write("mac-memory-qualification-a", "2026-11-10T00:00:00Z", version="3.0.2")
        with self.assertRaises(SystemExit):
            MODULE.memory_peaks("mac-mini-m6-16gb", "3.1", self.records)


def write_record(directory: Path, run_id: str, profile: str, finished_at: str,
                 classification: str = "canonical", key: str = "lineage-a",
                 rtf: float = 0.5, app_build: str = "24", lock: str = "lock-a",
                 variant: str = "speed", app_version: str = "3.0.0", repository: str | None = None) -> None:
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
        "toolchain": {"appVersion": app_version, "appBuild": app_build},
        "inputs": {"dependencyLockHash": lock},
        "comparison": {"key": key},
        "takes": [
            {"cell": f"{mode}/{length}/warm#{index}", "variant": variant,
             "metrics": {"rtf": rtf + index / 100, "submitToFirstChunkMS": 250.0 + index},
             **({"modelRepository": repository} if repository else {})}
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
        self.assertIn(MODULE.hardware_label(anchor), MODULE.render_all()["rtf-by-mode.svg"])

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
        memory = self.records / "memory"
        memory.mkdir()
        (memory / "mac-memory-qualification-x.json").write_text(json.dumps({
            "run": {"id": "mac-memory-qualification-x", "finishedAt": "2026-09-23T01:00:00Z",
                    "status": "passed", "platform": "macos"},
            "hardware": {"profileID": "mac-mini-m6-16gb"}, "toolchain": {"appVersion": "3.0.0"},
            "evidence": {"memoryQualified": True},
            "takes": [{"mode": mode, "metrics": {"kernelPhysFootprintPeakMB": 3072.0}} for mode in MODULE.MODES],
        }), encoding="utf-8")
        stderr = io.StringIO()
        with (
            mock.patch.object(MODULE, "RECORDS_DIR", self.records),
            mock.patch.object(MODULE, "MEMORY_RECORDS_DIR", memory),
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

    def test_the_label_names_the_models_the_pool_ran(self) -> None:
        """audit #17: the chart never publishes numbers under a hardware-only label."""
        self.assertEqual(MODULE.pool_model_label(self.pool(), self.records), "Speed models")
        # Both drawings name the committed pool's hardware and models together.
        pool = MODULE.chart_pool()
        label = f"{MODULE.hardware_label(MODULE.load_record(pool[0]))} · {MODULE.pool_model_label(pool)}"
        for name in ("rtf-by-mode.svg", "rtf-by-mode-narrow.svg"):
            self.assertIn(f">{label}</text>", MODULE.render_all()[name], name)
        self.assertIn("of the Speed models", MODULE.readme_alt_text(
            {f"{mode}/{length}/warm": 0.5 for mode in MODULE.MODES for length in MODULE.LENGTHS}, "Speed models",
        ))
        write_record(self.records, "macos-xcui-benchmark-20260915-000000-quality", "mac-mini-m2-8gb",
                     "2026-09-15T00:00:00Z", variant="quality")
        pool = self.pool()
        self.assertEqual(MODULE.pool_model_label(pool[:1], self.records), "Quality models")
        with self.assertRaises(SystemExit):
            MODULE.pool_model_label(pool, self.records)

    def test_the_one_model_per_mode_is_never_called_speed(self) -> None:
        """Since 3.1 each mode has one model whose variant id is still `speed` (RF-59)."""
        hybrid = "PowerBeef02/Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn"
        first = "macos-xcui-benchmark-20261115-000000-onemodel"
        write_record(self.records, first, "mac-mini-m2-8gb", "2026-11-15T00:00:00Z",
                     key="lineage-one-model", app_build="31", app_version="3.1.0", repository=hybrid)
        self.assertEqual(self.pool(), [first])
        label = MODULE.pool_model_label(self.pool(), self.records)
        self.assertEqual(label, "Vocello 3.1 models")
        self.assertNotIn("Speed", MODULE.readme_alt_text(
            {f"{mode}/{length}/warm": 0.5 for mode in MODULE.MODES for length in MODULE.LENGTHS}, label,
        ))
        # A pool that mixes the one model with the 3.0 Speed package is never charted under one label.
        with self.assertRaises(SystemExit):
            MODULE.pool_model_label([first, "macos-xcui-benchmark-20260914-000000-latestm2"], self.records)
        # Nor is one whose record states no app version to name the models by.
        unversioned = "macos-xcui-benchmark-20261116-000000-noversion"
        write_record(self.records, unversioned, "mac-mini-m2-8gb", "2026-11-16T00:00:00Z",
                     key="lineage-one-model", app_build="31", app_version="", repository=hybrid)
        with self.assertRaises(SystemExit):
            MODULE.pool_model_label([unversioned], self.records)

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
