"""Tests for scripts/npm_audit_gate.py over recorded `npm audit --json` shapes: nothing here runs npm."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import npm_audit_gate as gate  # noqa: E402

PICOMATCH = "GHSA-fc5q-39xc-vjpf"
MINIMATCH = "GHSA-g3hv-75wg-m249"
TODAY = dt.date(2026, 11, 17)


def advisory(ghsa: str, name: str, severity: str) -> dict:
    return {"source": 1, "name": name, "title": f"{name} advisory", "severity": severity,
            "url": f"https://github.com/advisories/{ghsa}", "range": "*"}


def report(*entries: tuple[str, str, str]) -> dict:
    """The 2026-11-17 shape: an advisory on its own package, paths on the packages above it."""
    vulnerabilities = {}
    for ghsa, name, severity in entries:
        vulnerabilities[name] = {"name": name, "severity": severity, "via": [advisory(ghsa, name, severity)]}
        vulnerabilities[f"{name}-parent"] = {"name": f"{name}-parent", "severity": severity, "via": [name]}
    return {"auditReportVersion": 2, "vulnerabilities": vulnerabilities,
            "metadata": {"vulnerabilities": {"total": len(vulnerabilities)}}}


class GateCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def exceptions(self, *items: dict) -> Path:
        path = self.directory / "exceptions.json"
        path.write_text(json.dumps({"schemaVersion": 1, "exceptions": list(items)}), encoding="utf-8")
        return path

    @staticmethod
    def exception(ghsa: str = PICOMATCH, decided: str = "2026-11-17", expires: str = "2026-12-01") -> dict:
        return {"advisory": ghsa, "package": "picomatch", "decided": decided, "expires": expires,
                "reason": "build tooling only"}

    def judge(self, audit: dict, exceptions: Path, today: dt.date = TODAY) -> tuple[int, list[str]]:
        return gate.evaluate(audit, exceptions, today)


class SeverityTests(GateCase):
    def test_a_clean_audit_passes(self) -> None:
        status, _ = self.judge(report(), self.exceptions())
        self.assertEqual(status, 0)

    def test_a_high_advisory_fails_like_audit_level_high(self) -> None:
        status, lines = self.judge(report((PICOMATCH, "picomatch", "high")), self.exceptions())
        self.assertEqual(status, 1)
        self.assertTrue(any(PICOMATCH in line and line.startswith("error:") for line in lines))

    def test_critical_fails_and_moderate_never_does(self) -> None:
        self.assertEqual(self.judge(report((PICOMATCH, "picomatch", "critical")), self.exceptions())[0], 1)
        self.assertEqual(self.judge(report((MINIMATCH, "minimatch", "moderate")), self.exceptions())[0], 0)


class ExceptionTests(GateCase):
    def test_an_unexpired_exception_excepts_only_its_own_advisory(self) -> None:
        exceptions = self.exceptions(self.exception())
        status, lines = self.judge(report((PICOMATCH, "picomatch", "high")), exceptions)
        self.assertEqual(status, 0)
        self.assertTrue(any(line.startswith(f"excepted: {PICOMATCH}") for line in lines))
        other = "GHSA-2222-3333-4444"
        status, _ = self.judge(report((PICOMATCH, "picomatch", "high"), (other, "other", "high")), exceptions)
        self.assertEqual(status, 1, "an exception never covers another advisory")

    def test_an_expired_exception_fails_the_audit(self) -> None:
        status, lines = self.judge(report((PICOMATCH, "picomatch", "high")),
                                   self.exceptions(self.exception()), today=dt.date(2026, 12, 2))
        self.assertEqual(status, 1)
        self.assertTrue(any("expired on 2026-12-01" in line for line in lines))
        # It fails even after the advisory is gone: an expired entry must be removed or renewed.
        self.assertEqual(self.judge(report(), self.exceptions(self.exception()), today=dt.date(2026, 12, 2))[0], 1)

    def test_an_exception_is_refused_past_thirty_days_or_before_its_decision(self) -> None:
        for expires in ("2026-12-18", "2026-11-16"):
            with self.subTest(expires=expires):
                status, lines = self.judge(report((PICOMATCH, "picomatch", "high")),
                                           self.exceptions(self.exception(expires=expires)))
                self.assertEqual(status, 1)
                self.assertTrue(any("within 30 days" in line for line in lines))

    def test_malformed_exceptions_are_refused(self) -> None:
        cases = {
            "id": self.exception(ghsa="CVE-2026-0001"),
            "date": {**self.exception(), "expires": "next month"},
            "reason": {**self.exception(), "reason": " "},
        }
        for name, item in cases.items():
            with self.subTest(name=name):
                status, _ = self.judge(report((PICOMATCH, "picomatch", "high")), self.exceptions(item))
                self.assertEqual(status, 1)

    def test_a_decision_still_to_come_is_refused(self) -> None:
        """Measured from a future decision, 30 days could cover a year from today."""
        item = self.exception(decided="2027-10-20", expires="2027-11-19")
        status, lines = self.judge(report((PICOMATCH, "picomatch", "high")), self.exceptions(item))
        self.assertEqual(status, 1)
        self.assertTrue(any("a date still to come" in line for line in lines))

    def test_an_exception_covers_only_the_package_it_names(self) -> None:
        item = {**self.exception(), "package": "fdir"}
        status, lines = self.judge(report((PICOMATCH, "picomatch", "high")), self.exceptions(item))
        self.assertEqual(status, 1)
        self.assertTrue(any("does not cover this package" in line for line in lines))

    def test_an_unused_exception_is_reported_but_does_not_fail(self) -> None:
        status, lines = self.judge(report(), self.exceptions(self.exception()))
        self.assertEqual(status, 0)
        self.assertTrue(any(line.startswith(f"notice: {PICOMATCH}") for line in lines))

    def test_the_committed_exception_file_is_valid(self) -> None:
        excepted, problems = gate.load_exceptions(gate.EXCEPTIONS_PATH, TODAY)
        self.assertEqual(problems, [])
        self.assertIn(PICOMATCH, excepted)


class FailClosedTests(GateCase):
    def test_unreadable_audit_output_exits_two(self) -> None:
        for text in ("", "npm ERR! network", json.dumps({"error": {"code": "ENOTFOUND"}}), json.dumps([])):
            with self.subTest(text=text[:20]):
                audit = self.directory / "audit.json"
                audit.write_text(text, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    code = gate.main(["--audit-json", str(audit), "--exceptions", str(self.exceptions())])
                self.assertEqual(code, 2)

    def test_an_unknown_severity_is_unreadable(self) -> None:
        audit = report((PICOMATCH, "picomatch", "high"))
        audit["vulnerabilities"]["picomatch"]["via"][0]["severity"] = "severe"
        with self.assertRaises(gate.Unreadable):
            gate.advisories(audit)

    def test_an_advisory_without_a_github_id_is_unreadable(self) -> None:
        audit = report((PICOMATCH, "picomatch", "high"))
        audit["vulnerabilities"]["picomatch"]["via"][0]["url"] = "https://example.invalid/advisory"
        with self.assertRaises(gate.Unreadable):
            gate.advisories(audit)

    def test_the_command_line_reads_a_saved_report(self) -> None:
        audit = self.directory / "audit.json"
        audit.write_text(json.dumps(report((PICOMATCH, "picomatch", "high"))), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            failing = gate.main(["--audit-json", str(audit), "--exceptions", str(self.exceptions()),
                                 "--today", "2026-11-17"])
            passing = gate.main(["--audit-json", str(audit), "--exceptions", str(self.exceptions(self.exception())),
                                 "--today", "2026-11-17"])
        self.assertEqual((failing, passing), (1, 0))


if __name__ == "__main__":
    unittest.main()
