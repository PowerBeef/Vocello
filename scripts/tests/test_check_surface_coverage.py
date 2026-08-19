#!/usr/bin/env python3
"""Unit tests for scripts/check_surface_coverage.py.

This is an omission check, which is the class none of the other gates can see:
a contradiction check needs a claim to contradict, and a surface nobody wrote
down makes no claim at all.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check_surface_coverage import (  # noqa: E402
    CoverageError,
    assists_findings,
    evaluate,
    guidance_size_findings,
    main,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

ASSISTS = """
<!-- BEGIN OPTIONAL ASSISTS -->
### Optional assists
no gate can validate this table; no entry is ever a prerequisite.

| Task | Reach for |
| --- | --- |
| a | one |
| b | two |
| c | three |
| d | four |
| e | five |
<!-- END OPTIONAL ASSISTS -->
"""



GATE = '''#!/usr/bin/env bash
python3 "$SCRIPT_DIR/documented_gate.py"
python3 "$SCRIPT_DIR/undocumented_gate.py"
'''


class Harness(unittest.TestCase):
    def build(self, agents_text, exemptions=None, gate=GATE, contracts=("kept.json",)):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "scripts").mkdir()
        (root / "config").mkdir()
        (root / ".agents" / "rules").mkdir(parents=True)
        (root / "website").mkdir()
        (root / "scripts" / "check_project_inputs.sh").write_text(gate)
        (root / "AGENTS.md").write_text(agents_text + ASSISTS)
        (root / "website" / "AGENTS.md").write_text("# Website guidance\n")
        for name in contracts:
            (root / "config" / name).write_text("{}")
        if exemptions is not None:
            (root / "config" / "surface-coverage-exemptions.json").write_text(
                json.dumps({"exemptions": exemptions})
            )
        return root

    def missing_from(self, report):
        return {entry["surface"] for entry in report["missing"]}


class CoverageTests(Harness):
    def test_an_undocumented_gate_fails(self):
        root = self.build("we mention scripts/documented_gate.py only")
        report = evaluate(root)
        self.assertFalse(report["ok"])
        self.assertIn("scripts/undocumented_gate.py", self.missing_from(report))
        self.assertNotIn("scripts/documented_gate.py", self.missing_from(report))

    def test_naming_every_surface_passes(self):
        root = self.build(
            "scripts/documented_gate.py, scripts/undocumented_gate.py, config/kept.json"
        )
        self.assertTrue(evaluate(root)["ok"])

    def test_a_bare_filename_counts_as_documentation(self):
        # Guidance names a script by filename in prose and by path in tables;
        # requiring the full path would fail correctly-documented surfaces.
        root = self.build("run undocumented_gate.py after documented_gate.py; see kept.json")
        self.assertTrue(evaluate(root)["ok"])

    def test_a_domain_rule_counts_as_documentation(self):
        root = self.build("scripts/documented_gate.py and config/kept.json")
        (root / ".agents" / "rules" / "backend.md").write_text(
            "the gate is scripts/undocumented_gate.py"
        )
        self.assertTrue(evaluate(root)["ok"])

    def test_a_glob_documents_a_whole_family(self):
        # AGENTS.md names `config/language-bench-*.json` for three real files.
        root = self.build(
            "gates: documented_gate.py undocumented_gate.py; data: `config/bench-*.json`",
            contracts=("bench-corpus.json", "bench-matrix.json"),
        )
        self.assertTrue(evaluate(root)["ok"], self.missing_from(evaluate(root)))

    def test_an_undocumented_contract_fails(self):
        root = self.build("documented_gate.py undocumented_gate.py", contracts=("orphan.json",))
        self.assertIn("config/orphan.json", self.missing_from(evaluate(root)))


class ExemptionTests(Harness):
    def test_an_exemption_with_a_reason_passes(self):
        root = self.build(
            "documented_gate.py kept.json",
            exemptions=[{"surface": "scripts/undocumented_gate.py", "why": "internal"}],
        )
        report = evaluate(root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["exempted"], ["scripts/undocumented_gate.py"])

    def test_an_exemption_without_a_reason_is_rejected(self):
        root = self.build("documented_gate.py kept.json",
                          exemptions=[{"surface": "scripts/undocumented_gate.py"}])
        with self.assertRaises(CoverageError):
            evaluate(root)

    def test_an_exemption_that_is_now_documented_fails(self):
        # Otherwise the list silently accumulates entries that no longer apply.
        root = self.build(
            "documented_gate.py undocumented_gate.py kept.json",
            exemptions=[{"surface": "scripts/undocumented_gate.py", "why": "internal"}],
        )
        report = evaluate(root)
        self.assertFalse(report["ok"])
        self.assertIn("scripts/undocumented_gate.py", report["staleExemptions"])


class SafetyTests(Harness):
    def test_a_gate_file_with_no_invocations_fails_loudly(self):
        root = self.build("anything", gate="#!/usr/bin/env bash\necho hi\n")
        with self.assertRaises(CoverageError):
            evaluate(root)

    def test_missing_guidance_is_an_error(self):
        root = self.build("x")
        (root / "AGENTS.md").unlink()
        with self.assertRaises(CoverageError):
            evaluate(root)


class AssistsSectionTests(unittest.TestCase):
    """The optional-assists table is unverifiable by design, which makes it the
    section most likely to be deleted by something acting in good faith."""

    def write(self, body):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "AGENTS.md").write_text(body)
        return root

    def test_a_complete_section_passes(self):
        self.assertEqual(assists_findings(self.write(ASSISTS)), [])

    def test_deleting_the_section_fails(self):
        findings = assists_findings(self.write("# Guidance\n\nnothing here\n"))
        self.assertTrue(any("markers are missing" in f for f in findings))

    def test_stripping_the_markers_fails(self):
        body = ASSISTS.replace("<!-- BEGIN OPTIONAL ASSISTS -->", "").replace(
            "<!-- END OPTIONAL ASSISTS -->", "")
        self.assertTrue(assists_findings(self.write(body)))

    def test_duplicated_markers_fail(self):
        self.assertTrue(assists_findings(self.write(ASSISTS + ASSISTS)))

    def test_losing_the_unverifiability_disclaimer_fails(self):
        body = ASSISTS.replace("no gate can validate this table",
                               "this table is fully checked")
        findings = assists_findings(self.write(body))
        self.assertTrue(any("unverifiable" in f for f in findings))

    def test_losing_the_optional_framing_fails(self):
        body = ASSISTS.replace("no entry is ever a prerequisite", "every entry is required")
        findings = assists_findings(self.write(body))
        self.assertTrue(any("prerequisite" in f for f in findings))

    def test_gutting_the_table_to_a_stub_fails(self):
        body = ASSISTS.replace("| c | three |\n| d | four |\n| e | five |\n", "")
        findings = assists_findings(self.write(body))
        self.assertTrue(any("gutted" in f for f in findings))

    def test_rows_may_change_freely(self):
        # User tooling changes; the rows should follow it without ceremony.
        body = ASSISTS.replace("| a | one |", "| a | something entirely different |")
        self.assertEqual(assists_findings(self.write(body)), [])


class GuidanceSizeTests(Harness):
    def test_root_and_nested_guidance_below_budget_pass(self):
        root = self.build("documented_gate.py undocumented_gate.py kept.json")
        findings, sizes = guidance_size_findings(root)
        self.assertEqual(findings, [])
        self.assertIn("website/AGENTS.md", sizes)

    def test_combined_root_and_nested_guidance_above_budget_fails(self):
        root = self.build("documented_gate.py undocumented_gate.py kept.json")
        (root / "website" / "AGENTS.md").write_text("x" * (30 * 1024))
        findings, _ = guidance_size_findings(root)
        self.assertTrue(any("exceeding" in finding for finding in findings))

    def test_missing_nested_guidance_fails(self):
        root = self.build("documented_gate.py undocumented_gate.py kept.json")
        (root / "website" / "AGENTS.md").unlink()
        findings, _ = guidance_size_findings(root)
        self.assertTrue(any("missing nested" in finding for finding in findings))


class RepositoryTests(unittest.TestCase):
    def test_the_repository_documents_every_enforced_surface(self):
        self.assertEqual(main(["--root", str(REPO_ROOT)]), 0)

    def test_the_shipped_assists_section_is_intact(self):
        self.assertEqual(assists_findings(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
