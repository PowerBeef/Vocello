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

from check_surface_coverage import CoverageError, evaluate, main  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

GATE = '''#!/usr/bin/env bash
python3 "$SCRIPT_DIR/documented_gate.py"
python3 "$SCRIPT_DIR/undocumented_gate.py"
'''


class Harness(unittest.TestCase):
    def build(self, claude_text, exemptions=None, gate=GATE, contracts=("kept.json",)):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "scripts").mkdir()
        (root / "config").mkdir()
        (root / ".claude" / "rules").mkdir(parents=True)
        (root / "scripts" / "check_project_inputs.sh").write_text(gate)
        (root / "CLAUDE.md").write_text(claude_text)
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
        (root / ".claude" / "rules" / "backend.md").write_text(
            "the gate is scripts/undocumented_gate.py"
        )
        self.assertTrue(evaluate(root)["ok"])

    def test_a_glob_documents_a_whole_family(self):
        # CLAUDE.md names `config/language-bench-*.json` for three real files.
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
        (root / "CLAUDE.md").unlink()
        with self.assertRaises(CoverageError):
            evaluate(root)


class RepositoryTests(unittest.TestCase):
    def test_the_repository_documents_every_enforced_surface(self):
        self.assertEqual(main(["--root", str(REPO_ROOT)]), 0)


if __name__ == "__main__":
    unittest.main()
