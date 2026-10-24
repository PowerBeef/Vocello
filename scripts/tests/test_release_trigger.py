"""Release trigger guard (scripts/ci/release_trigger.py): tag ref and safe output names."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/release_trigger.py"
SPEC = importlib.util.spec_from_file_location("release_trigger", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseTriggerTests(unittest.TestCase):
    def test_a_tag_push_and_a_dispatch_from_the_same_tag_are_allowed(self) -> None:
        MODULE.validate("push", "refs/tags/v3.0.0", "v3.0.0", "")
        MODULE.validate("workflow_dispatch", "refs/tags/v3.0.0-rc.1", "v3.0.0-rc.1", "Vocello-macos26")

    def test_iphone_candidate_tags_have_exactly_one_shape(self) -> None:
        MODULE.validate("push", "refs/tags/v3.0.0-ios.3", "v3.0.0-ios.3", "")
        for tag in ("v3.0.0-ios", "v3.0.0-ios.0", "v3.0.0-ios.3.1", "v3.0.0-ios.x", "v3.0.0-iosfix.1",
                    "v3.0.0-rc.1-ios.2", "v3.0.0-iOS.1", "v3.0.0-IOS.1", "v3.0.0-iOS", "v3.0.0-rc.1-iOS.2"):
            with self.subTest(tag=tag), self.assertRaises(MODULE.TriggerError):
                MODULE.validate("push", f"refs/tags/{tag}", tag, "")

    def test_only_an_exact_candidate_sets_the_ios_candidate_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for tag, expected in (("v3.0.0-ios.3", "true"), ("v3.0.0", "false"), ("v3.0.0-rc.1", "false")):
                with self.subTest(tag=tag):
                    output = Path(directory) / f"{tag}.txt"
                    status = MODULE.main(["--event", "push", "--ref", f"refs/tags/{tag}", "--tag", tag,
                                          "--github-output", str(output)])
                    self.assertEqual(status, 0)
                    self.assertEqual(output.read_text(encoding="utf-8"), f"ios_candidate={expected}\n")
            refused = Path(directory) / "refused.txt"
            self.assertEqual(MODULE.main(["--event", "push", "--ref", "refs/tags/v3.0.0-iOS.1", "--tag",
                                          "v3.0.0-iOS.1", "--github-output", str(refused)]), 1)
            self.assertFalse(refused.exists())

    def test_a_dispatch_from_a_branch_is_refused(self) -> None:
        # The branch's own (possibly edited) release.yml would receive the secrets.
        with self.assertRaises(MODULE.TriggerError) as raised:
            MODULE.validate("workflow_dispatch", "refs/heads/main", "v3.0.0", "")
        self.assertIn("gh workflow run release.yml --ref v3.0.0 -f tag=v3.0.0", str(raised.exception))

    def test_a_dispatch_from_another_tag_is_refused(self) -> None:
        with self.assertRaises(MODULE.TriggerError):
            MODULE.validate("workflow_dispatch", "refs/tags/v2.4.0", "v3.0.0", "")

    def test_other_events_and_malformed_tags_are_refused(self) -> None:
        for event, ref, tag in (("pull_request", "refs/tags/v3.0.0", "v3.0.0"),
                                ("workflow_dispatch", "refs/tags/v3.0", "v3.0"),
                                ("workflow_dispatch", "refs/tags/v3.0.0;x", "v3.0.0;x")):
            with self.subTest(event=event, tag=tag):
                with self.assertRaises(MODULE.TriggerError):
                    MODULE.validate(event, ref, tag, "")

    def test_output_names_follow_the_contract_pattern(self) -> None:
        for name in ("$(id)", 'a"b', "../x", "a/b", "x" * 161, " leading-space", "a;b"):
            with self.subTest(name=name):
                with self.assertRaises(MODULE.TriggerError):
                    MODULE.validate("workflow_dispatch", "refs/tags/v3.0.0", "v3.0.0", name)
        for name in ("", "Vocello-macos26", "Vocello 3.0.0 rc"):
            with self.subTest(name=name):
                MODULE.validate("workflow_dispatch", "refs/tags/v3.0.0", "v3.0.0", name)

    def test_a_contract_without_the_named_template_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "orchestration-contract.json"
            contract.write_text(json.dumps({"workflows": {"release-macos-candidate": {
                "commandTemplates": {"release-build": [{"id": "other", "argv": ["./scripts/release.sh"]}]}}}}))
            with self.assertRaises(MODULE.TriggerError):
                MODULE.validate("workflow_dispatch", "refs/tags/v3.0.0", "v3.0.0", "Vocello", contract_path=contract)

    def test_command_line_exit_codes(self) -> None:
        refused = subprocess.run([sys.executable, str(SCRIPT), "--event", "workflow_dispatch",
                                  "--ref", "refs/heads/main", "--tag", "v3.0.0"],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("release-trigger:", refused.stderr)
        allowed = subprocess.run([sys.executable, str(SCRIPT), "--event", "push",
                                  "--ref", "refs/tags/v3.0.0", "--tag", "v3.0.0", "--output-name", ""],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)


if __name__ == "__main__":
    unittest.main()
