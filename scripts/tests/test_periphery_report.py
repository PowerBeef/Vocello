"""The nightly dead-code report: what Periphery's JSON says about owned code, and nothing else."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("periphery_report", ROOT / "scripts/ci/periphery_report.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # dataclasses resolve string annotations through sys.modules
SPEC.loader.exec_module(MODULE)

REPO = "/Users/example/work/Vocello Repo/Vocello"


def result(location: str, kind: str = "function.method.instance", hints: tuple[str, ...] = ("unused",)) -> dict:
    """One result as Periphery 3.8's `--format json` writes it."""
    return {"name": "declaration()", "modules": ["QwenVoiceCore"], "kind": kind, "modifiers": [],
            "hints": list(hints), "accessibility": "internal", "ids": ["s:13QwenVoiceCore1fyyF"],
            "location": location, "attributes": []}


CHECKOUT = "build/cache/xcode/source-packages/checkouts/swift-transformers/Sources/Tokenizers/BPETokenizer.swift"
RESULTS = [
    result("Sources/QwenVoiceCore/MLXTTSEngine.swift:12:9"),
    result("Sources/QwenVoiceCore/MLXTTSEngine.swift:40:5", "var.instance", ("assignOnlyProperty",)),
    result("Sources/QwenVoiceCore/TTSEngine.swift:7:3", "struct", ("redundantPublicAccessibility",)),
    result("Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift:3:1", "module"),
    result("Sources/ContentView.swift:23:36", "var.instance"),
    # --relative-results makes every path relative; an absolute one inside the repository still counts.
    result(f"{REPO}/Sources/iOS/TTSEngineStore.swift:5:1"),
    # Outside owned code: a package checkout, another directory, the test targets.
    result(f"{CHECKOUT}:130:10"),
    result("/Users/example/elsewhere/Other.swift:1:1"),
    result("Tests/VocelloCoreTests/StoreTests.swift:1:1"),
]


class ParseTests(unittest.TestCase):
    def test_only_owned_code_counts_and_every_path_is_repository_relative(self) -> None:
        findings, excluded = MODULE.parse(RESULTS, REPO)
        self.assertEqual(excluded, 3)
        self.assertEqual([(finding.file, finding.line, finding.kind, finding.hints) for finding in findings], [
            ("Sources/QwenVoiceCore/MLXTTSEngine.swift", 12, "function.method.instance", ("unused",)),
            ("Sources/QwenVoiceCore/MLXTTSEngine.swift", 40, "var.instance", ("assignOnlyProperty",)),
            ("Sources/QwenVoiceCore/TTSEngine.swift", 7, "struct", ("redundantPublicAccessibility",)),
            ("Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift", 3, "module", ("unused",)),
            ("Sources/ContentView.swift", 23, "var.instance", ("unused",)),
            ("Sources/iOS/TTSEngineStore.swift", 5, "function.method.instance", ("unused",)),
        ])

    def test_locations_resolve_inside_the_repository_or_not_at_all(self) -> None:
        self.assertEqual(MODULE.relative_file("./Sources/A.swift:1:2", REPO), "Sources/A.swift")
        self.assertEqual(MODULE.relative_file(f"{REPO}/Sources/A.swift:1:2", REPO), "Sources/A.swift")
        self.assertEqual(MODULE.relative_file("Sources/A.swift", REPO), "Sources/A.swift")
        self.assertIsNone(MODULE.relative_file("/Users/example/other/Sources/A.swift:1:2", REPO))
        self.assertFalse(MODULE.is_owned("Sources/../../outside/A.swift"))
        self.assertFalse(MODULE.is_owned("Packages/OtherPackage/A.swift"))
        self.assertTrue(MODULE.is_owned("Packages/VocelloQwen3Core/Sources/A.swift"))

    def test_malformed_results_are_excluded_and_a_result_without_hints_is_named(self) -> None:
        findings, excluded = MODULE.parse([42, {"kind": "struct"}, {"location": 7},
                                           {"location": "Sources/A.swift:3:1", "hints": []}], REPO)
        self.assertEqual(excluded, 3)
        self.assertEqual([(finding.kind, finding.hints) for finding in findings], [("(unknown)", ("(none)",))])

    def test_areas_are_the_first_two_path_components(self) -> None:
        self.assertEqual(MODULE.area("Sources/QwenVoiceCore/MLXTTSEngine.swift"), "Sources/QwenVoiceCore")
        self.assertEqual(MODULE.area("Sources/ContentView.swift"), "Sources")
        self.assertEqual(MODULE.area("Packages/VocelloQwen3Core/Sources/A.swift"), "Packages/VocelloQwen3Core")


class RenderTests(unittest.TestCase):
    def test_the_tables_count_hints_kinds_areas_and_files(self) -> None:
        findings, excluded = MODULE.parse(RESULTS, REPO)
        text = MODULE.render(findings, excluded)
        self.assertIn("6 finding(s) in owned code (`Sources/`, `Packages/VocelloQwen3Core/`) across 5 file(s); "
                      "3 result(s) outside owned code are not counted.", text)
        self.assertIn("| `unused` | never referenced | 4 |", text)
        self.assertIn("| `assignOnlyProperty` | assigned but never read | 1 |", text)
        self.assertIn("| `redundantPublicAccessibility` | public, but used only inside its own module | 1 |", text)
        self.assertIn("| `function.method.instance` | 2 |", text)
        self.assertIn("| `module` (an unused import) | 1 |", text)
        self.assertIn("| Area | Findings | `unused` | `assignOnlyProperty` | `redundantPublicAccessibility` |", text)
        self.assertIn("| Sources/QwenVoiceCore | 3 | 1 | 1 | 1 |", text)
        self.assertIn("| Sources | 1 | 1 | 0 | 0 |", text)
        self.assertIn("#### Files with the most findings (5 of 5)", text)
        self.assertIn("| `Sources/QwenVoiceCore/MLXTTSEngine.swift` | 2 | 1 | 1 | 0 |", text)
        # Only repository-relative owned paths: no home directory, checkout or test target is named.
        for absent in ("/Users/", "checkouts", "Tests/", "Other.swift"):
            self.assertNotIn(absent, text)

    def test_the_file_list_is_capped(self) -> None:
        findings, _ = MODULE.parse([result(f"Sources/F{index}.swift:1:1") for index in range(5)], REPO)
        text = MODULE.render(findings, 0, top=3)
        self.assertIn("#### Files with the most findings (3 of 5)", text)
        self.assertNotIn("Sources/F4.swift", text)
        self.assertNotIn("not counted", text)

    def test_a_hint_without_a_known_meaning_is_still_counted(self) -> None:
        findings, _ = MODULE.parse([result("Sources/A.swift:1:1", hints=("someFutureHint",))], REPO)
        self.assertIn("| `someFutureHint` |  | 1 |", MODULE.render(findings, 0))

    def test_no_owned_finding_says_so(self) -> None:
        text = MODULE.render([], 2)
        self.assertIn("No finding in owned code (`Sources/`, `Packages/VocelloQwen3Core/`); 2 result(s) outside "
                      "owned code are not counted.", text)
        self.assertNotIn("####", text)


class MainTests(unittest.TestCase):
    def run_main(self, results: Path, *extra: str, summary: Path) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = MODULE.main([str(results), "--root", REPO, *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_findings_never_fail_and_every_output_is_the_same_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vocello periphery ") as tmp:
            results = Path(tmp) / "periphery.json"
            results.write_text(json.dumps(RESULTS), encoding="utf-8")
            output = Path(tmp) / "report/periphery-report.md"
            summary = Path(tmp) / "summary.md"
            code, stdout, _ = self.run_main(results, "--output", str(output), summary=summary)
            self.assertEqual(code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertEqual(stdout, output.read_text(encoding="utf-8"))
            self.assertIn("6 finding(s) in owned code", stdout)

    def test_unreadable_results_exit_non_zero_and_name_only_the_file(self) -> None:
        cases = {"missing.json": None, "truncated.json": '[{"location": ', "object.json": '{"results": []}'}
        reasons = {"missing.json": "no Periphery results at `missing.json`",
                   "truncated.json": "the Periphery results at `truncated.json` are not JSON",
                   "object.json": "the Periphery results at `object.json` are not a JSON array"}
        for name, text in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="vocello periphery ") as tmp:
                results = Path(tmp) / name
                if text is not None:
                    results.write_text(text, encoding="utf-8")
                summary = Path(tmp) / "summary.md"
                code, stdout, stderr = self.run_main(results, summary=summary)
                self.assertEqual(code, 1)
                self.assertIn(reasons[name], stderr)
                written = summary.read_text(encoding="utf-8")
                self.assertIn(f"No report: {reasons[name]}", written)
                self.assertEqual(written, stdout)
                self.assertNotIn(tmp, written)


if __name__ == "__main__":
    unittest.main()
