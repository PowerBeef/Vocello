"""Nightly report helpers: coverage of the watched files and the build-setting probe."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/ci/{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COVERAGE = load("coverage_report")
PROBE = load("probe_build_settings")


def export(root: str, entries: list[tuple[str, int, int]]) -> dict:
    return {"data": [{"files": [
        {"filename": f"{root}/{path}", "summary": {"lines": {"covered": covered, "count": count}}}
        for path, covered, count in entries
    ]}]}


class CoverageReportTests(unittest.TestCase):
    def test_totals_and_watched_rows(self) -> None:
        root = "/repo"
        watched = COVERAGE.WATCHED[0]
        data = export(root, [(watched, 30, 120), ("Sources/Other.swift", 50, 80),
                             ("build/cache/xcode/checkouts/mlx.swift", 9, 9)])
        text = COVERAGE.render(data, root)
        self.assertIn("| All repository sources | 80/200 | 40.0% |", text)
        self.assertIn(f"| `{watched}` | 30/120 | 25.0% |", text)
        self.assertIn("not instrumented", text)  # the other watched files are absent
        self.assertNotIn("mlx.swift", text)

    def test_a_file_in_two_binaries_counts_once(self) -> None:
        root = "/repo"
        path = "Sources/QwenVoiceCore/Shared.swift"
        data = {"data": [export(root, [(path, 10, 40)])["data"][0],
                         export(root, [(path, 25, 40)])["data"][0]]}
        (covered, count), files = COVERAGE.summarize(data, root)
        self.assertEqual(files[path], (25, 40))
        self.assertEqual((covered, count), (25, 40))


class BuildSettingProbeTests(unittest.TestCase):
    def test_defined_and_absent_settings(self) -> None:
        text = 'Name = "SWIFT_STRICT_MEMORY_SAFETY"; Name = DEAD_CODE_STRIPPING;'
        found = PROBE.probe(text, ("SWIFT_STRICT_MEMORY_SAFETY", "DEAD_CODE_STRIPPING",
                                   "ENABLE_ENHANCED_SECURITY"))
        self.assertEqual(found, {"SWIFT_STRICT_MEMORY_SAFETY": True, "DEAD_CODE_STRIPPING": True,
                                 "ENABLE_ENHANCED_SECURITY": False})

    def test_a_longer_name_does_not_count_as_its_prefix(self) -> None:
        found = PROBE.probe("SWIFT_DEFAULT_ACTOR_ISOLATION_EXTRA", ("SWIFT_DEFAULT_ACTOR_ISOLATION",))
        self.assertFalse(found["SWIFT_DEFAULT_ACTOR_ISOLATION"])

    def test_specs_are_read_from_the_owning_xcode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Xcode.app"
            spec = app / "Contents/SharedFrameworks/X.framework/Resources/Swift.xcspec"
            spec.parent.mkdir(parents=True)
            spec.write_text("SWIFT_STRICT_MEMORY_SAFETY")
            developer = app / "Contents/Developer"
            developer.mkdir(parents=True)
            self.assertIn("SWIFT_STRICT_MEMORY_SAFETY", PROBE.spec_texts(developer))

    def test_render_marks_absent_settings(self) -> None:
        text = PROBE.render("Xcode 26.6", {"A": True, "B": False})
        self.assertIn("| `A` | yes |", text)
        self.assertIn("| `B` | **no** |", text)


if __name__ == "__main__":
    unittest.main()
