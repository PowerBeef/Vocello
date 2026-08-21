#!/usr/bin/env python3
"""Tests for the single-source vocello CLI version contract."""

from __future__ import annotations

from pathlib import Path
import stat
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import cli_version_contract  # noqa: E402


VALID_PROJECT = """\
settings:
  base:
    MARKETING_VERSION: "2.4.0"
    CURRENT_PROJECT_VERSION: "23"
targets:
  VocelloCLI:
    type: tool
    settings:
      base:
        GENERATE_INFOPLIST_FILE: YES
        CREATE_INFOPLIST_SECTION_IN_BINARY: YES
        INFOPLIST_KEY_CFBundleShortVersionString: "$(MARKETING_VERSION)"
        INFOPLIST_KEY_CFBundleVersion: "$(CURRENT_PROJECT_VERSION)"
"""

VALID_SUPPORT = """\
import Foundation

let vocelloCLIVersion: String =
    (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
        .flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
"""


class CLIVersionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Sources/VocelloCLI").mkdir(parents=True)
        self.project = self.root / "project.yml"
        self.support = self.root / "Sources/VocelloCLI/Support.swift"
        self.project.write_text(VALID_PROJECT, encoding="utf-8")
        self.support.write_text(VALID_SUPPORT, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_binary(self, body: str) -> Path:
        binary = self.root / "vocello"
        binary.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        return binary

    def test_valid_source_and_all_binary_aliases_pass(self) -> None:
        version = cli_version_contract.validate_source_contract(self.root)
        binary = self.make_binary("printf 'vocello 2.4.0\\n'\n")

        cli_version_contract.validate_binary(binary, version)
        self.assertEqual(version, "2.4.0")

    def test_missing_or_duplicate_project_versions_fail(self) -> None:
        for key, value in (
            ("MARKETING_VERSION", "2.4.0"),
            ("CURRENT_PROJECT_VERSION", "23"),
        ):
            line = f'    {key}: "{value}"\n'
            for label, replacement in (("missing", ""), ("duplicate", line + line)):
                with self.subTest(key=key, label=label):
                    self.project.write_text(
                        VALID_PROJECT.replace(line, replacement),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        cli_version_contract.ContractError,
                        f"{key} exactly once",
                    ):
                        cli_version_contract.validate_source_contract(self.root)

    def test_each_required_embedding_setting_is_enforced(self) -> None:
        for key in cli_version_contract.REQUIRED_CLI_SETTINGS:
            with self.subTest(key=key):
                lines = [line for line in VALID_PROJECT.splitlines() if key not in line]
                self.project.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(cli_version_contract.ContractError, key):
                    cli_version_contract.validate_source_contract(self.root)

    def test_numeric_source_fallback_is_rejected(self) -> None:
        self.support.write_text(
            VALID_SUPPORT.replace('?? "unknown"', '?? "0.1.0"'),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(cli_version_contract.ContractError, "non-numeric fallback"):
            cli_version_contract.validate_source_contract(self.root)

    def test_binary_failure_is_rejected(self) -> None:
        binary = self.make_binary("printf 'broken\\n' >&2\nexit 9\n")

        with self.assertRaisesRegex(cli_version_contract.ContractError, "exited 9"):
            cli_version_contract.validate_binary(binary, "2.4.0")

    def test_binary_output_mismatch_is_rejected(self) -> None:
        binary = self.make_binary(
            "if [ \"$1\" = \"-v\" ]; then\n"
            "  printf 'vocello 0.1.0\\n'\n"
            "else\n"
            "  printf 'vocello 2.4.0\\n'\n"
            "fi\n"
        )

        with self.assertRaisesRegex(cli_version_contract.ContractError, "vocello -v output"):
            cli_version_contract.validate_binary(binary, "2.4.0")

    def test_repository_wires_source_and_binary_validation_into_local_and_ci_gates(self) -> None:
        build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
        validator_call = 'python3 "$SCRIPT_DIR/cli_version_contract.py" validate'
        self.assertIn(validator_call, build)
        self.assertLess(build.index(validator_call), build.index('rm -f "$CLI_BINARY"'))

        project_gate = (ROOT / "scripts/check_project_inputs.sh").read_text(encoding="utf-8")
        self.assertIn('python3 "$SCRIPT_DIR/cli_version_contract.py" validate', project_gate)

        workflow_gate = (ROOT / "scripts/check_test_workflows.sh").read_text(encoding="utf-8")
        self.assertIn("python3 scripts/python_test_contract.py validate", workflow_gate)
        self.assertIn("python3 -m unittest discover -s scripts/tests -p 'test_*.py'", workflow_gate)

        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("Verify source-built CLI version identity", ci)
        self.assertIn("run: ./scripts/build.sh cli --version", ci)


if __name__ == "__main__":
    unittest.main()
