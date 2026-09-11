#!/usr/bin/env python3
"""Contract tests for the repository-local Claude Code commit hook."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOK_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "precommit_gate.sh"
TREE_FINGERPRINT = REPO_ROOT / "scripts" / "tree_fingerprint.py"
GATE_COMMAND = '"$CLAUDE_PROJECT_DIR"/scripts/hooks/precommit_gate.sh'


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def commit_payload() -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
        }
    )


class ClaudeHookContractTests(unittest.TestCase):
    def test_settings_wire_the_repository_commit_gate_as_a_bash_pre_tool_use_hook(self) -> None:
        payload = json.loads(SETTINGS.read_text(encoding="utf-8"))
        groups = payload["hooks"]["PreToolUse"]
        gate_handlers = [
            handler
            for group in groups
            if "Bash" in group["matcher"]
            for handler in group["hooks"]
            if handler.get("command") == GATE_COMMAND
        ]
        self.assertEqual(len(gate_handlers), 1, "exactly one commit-gate handler")
        handler = gate_handlers[0]
        self.assertEqual(handler["type"], "command")
        # Hooks check a receipt; they never run the checkpoint itself, so a short
        # explicit timeout documents that a slow hook is a defect, not a build.
        self.assertEqual(handler["timeout"], 30)

    def test_non_commit_json_input_is_allowed_without_running_the_gate(self) -> None:
        result = subprocess.run(
            [str(HOOK_SCRIPT)],
            input=json.dumps({"tool_input": {"command": "git status --short"}}),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_receipt_check_blocks_missing_stale_corrupt_or_unreadable_identity_without_running_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hook_dir = root / "scripts" / "hooks"
            hook_dir.mkdir(parents=True)

            hook = hook_dir / "precommit_gate.sh"
            shutil.copy2(HOOK_SCRIPT, hook)
            make_executable(hook)

            fingerprint = root / "scripts" / "tree_fingerprint.py"
            shutil.copy2(TREE_FINGERPRINT, fingerprint)
            make_executable(fingerprint)

            gate = root / "scripts" / "dev.sh"
            gate.write_text("#!/usr/bin/env bash\ntouch gate-ran\nexit 1\n", encoding="utf-8")
            make_executable(gate)

            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            (root / ".gitignore").write_text("build/\n", encoding="utf-8")
            (root / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Vocello Tests", "-c", "user.email=tests@vocello.local",
                 "commit", "-q", "-m", "fixture"],
                cwd=root,
                check=True,
            )

            env = dict(os.environ)
            env.pop("QVOICE_SKIP_COMMIT_GATE", None)
            result = subprocess.run(
                [str(hook)], cwd=root, env=env, input=commit_payload(),
                text=True, capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("receipt is missing or stale", result.stderr)
            self.assertIn("Run scripts/dev.sh checkpoint outside the hook", result.stderr)
            self.assertFalse((root / "gate-ran").exists())

            marker = root / "build/scratch/gate-fingerprint/last-pass"
            marker.parent.mkdir(parents=True)
            exact = subprocess.check_output(
                [sys.executable, str(fingerprint), "--root", str(root), "--checkpoint"], text=True, env=env
            ).strip()
            for receipt, expected in (("corrupt", 2), ("", 2), (exact, 0)):
                with self.subTest(receipt="exact" if receipt == exact else "invalid"):
                    marker.write_text(receipt + "\n", encoding="utf-8")
                    result = subprocess.run([str(hook)], cwd=root, env=env, input=commit_payload(),
                                            text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertFalse((root / "gate-ran").exists())
            (root / "fixture.txt").write_text("changed after checkpoint\n", encoding="utf-8")
            result = subprocess.run([str(hook)], cwd=root, env=env, input=commit_payload(),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            fingerprint.write_text("raise SystemExit(1)\n", encoding="utf-8")
            result = subprocess.run([str(hook)], cwd=root, env=env, input=commit_payload(),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("unable to verify", result.stderr)
            self.assertFalse((root / "gate-ran").exists())

    def test_non_main_branch_blocks_commit_even_when_validation_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hook_dir = root / "scripts" / "hooks"
            hook_dir.mkdir(parents=True)

            hook = hook_dir / "precommit_gate.sh"
            shutil.copy2(HOOK_SCRIPT, hook)
            make_executable(hook)

            gate = root / "scripts" / "dev.sh"
            gate.write_text("#!/usr/bin/env bash\ntouch gate-ran\nexit 0\n", encoding="utf-8")
            make_executable(gate)

            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            (root / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Vocello Tests", "-c", "user.email=tests@vocello.local",
                 "commit", "-q", "-m", "fixture"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "switch", "-q", "-c", "topic"], cwd=root, check=True)

            env = dict(os.environ)
            env["QVOICE_SKIP_COMMIT_GATE"] = "1"
            result = subprocess.run(
                [str(hook)], cwd=root, env=env, input=commit_payload(),
                text=True, capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("commits must be made directly on main", result.stderr)
            self.assertIn("current: topic", result.stderr)
            self.assertFalse((root / "gate-ran").exists())


if __name__ == "__main__":
    unittest.main()
