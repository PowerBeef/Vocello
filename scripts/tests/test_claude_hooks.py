#!/usr/bin/env python3
"""Behaviour tests for the Claude Code guard hooks under scripts/hooks/.

Each hook receives the same JSON Claude Code sends on stdin. Exit 0 allows the
tool call, exit 2 blocks it with a reason on stderr. These tests pin the policy
each guard enforces, not its wording, so messages may change freely as long as
they still name the sanctioned route.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS = REPO_ROOT / "scripts" / "hooks"
SIM = "Sim" + "ulator"  # assembled so this file never carries the rejected literal


def run_hook(name: str, tool_input: dict, *, tool_name: str = "Bash", cwd: Path | None = None, env=None):
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run(
        [str(HOOKS / name)], input=payload, text=True, capture_output=True,
        cwd=str(cwd or REPO_ROOT), env=env, check=False, timeout=20,
    )


class PolicyGuardTests(unittest.TestCase):
    def guard(self, command: str):
        return run_hook("policy_guard.sh", {"command": command})

    def test_ordinary_commands_are_allowed_quickly(self):
        for command in (
            "git status --short --branch",
            "scripts/dev.sh checkpoint --full",
            "xcodebuild -project QwenVoice.xcodeproj -scheme QwenVoice -destination 'platform=macOS,arch=arm64' build",
            "git push",
            "git branch --show-current",
            "git branch -a",
            "rm -rf build/scratch/transient/probe",
            "cat QwenVoice.xcodeproj/project.pbxproj | head",
            "xcrun devicectl list devices",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_destinations_are_blocked(self):
        for command in (
            f"xcodebuild test -scheme VocelloiOSUI -destination 'platform=iOS {SIM},name=iPhone 17 Pro'",
            "xcrun simctl boot 1234",
            "xcrun simctl create test-device com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Physical iPhone only", result.stderr)

    def test_whole_cache_deletion_is_blocked_but_scratch_is_not(self):
        for command in ("rm -rf build/cache", "rm -rf build/cache/xcode/macos", "rm -rf build", "rm -Rf ./build/"):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("clean_build_caches.sh", result.stderr)
        self.assertEqual(self.guard("rm -rf build/scratch/derived-data/foundation").returncode, 0)

    def test_force_push_and_branching_are_blocked(self):
        for command in (
            "git push --force origin main",
            "git push -f",
            "git push origin +main",
            "git checkout -b experiment",
            "git switch -c topic",
            "git switch --create topic",
            "git worktree add ../wt",
            "git branch feature/x",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Main only", result.stderr)

    def test_shell_writes_to_pbxproj_are_blocked(self):
        for command in (
            "sed -i '' 's/a/b/' QwenVoice.xcodeproj/project.pbxproj",
            "echo x >> QwenVoice.xcodeproj/project.pbxproj",
            "cat patch | tee QwenVoice.xcodeproj/project.pbxproj",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("regenerate_project.sh", result.stderr)

    def test_commit_gate_bypass_needs_acknowledgement(self):
        blocked = self.guard("QVOICE_SKIP_COMMIT_GATE=1 git com" "mit -m x")
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("QVOICE_SKIP_COMMIT_GATE_ACK=user", blocked.stderr)
        allowed = self.guard("QVOICE_SKIP_COMMIT_GATE_ACK=user QVOICE_SKIP_COMMIT_GATE=1 git com" "mit -m x")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_unparsable_payload_is_allowed(self):
        result = subprocess.run([str(HOOKS / "policy_guard.sh")], input="not json", text=True,
                                capture_output=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0)


class GeneratedFileGuardTests(unittest.TestCase):
    def guard(self, relative: str, root: Path | None = None):
        root = root or REPO_ROOT
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        return run_hook("generated_file_guard.sh", {"file_path": str(root / relative)}, tool_name="Edit", cwd=root, env=env)

    def test_generated_files_are_blocked_with_their_generator(self):
        cases = {
            "docs/INDEX.md": "rebuild-index",
            "docs/INDEX.json": "rebuild-index",
            "docs/ROADMAP.md": "roadmap.py render",
            "docs/project-health.md": "project_health.py",
            "config/derived-doc-facts.json": "derive-facts",
            "Sources/Resources/qwenvoice_production_model_catalog.json": "model_catalog_contract.py rebuild",
            "docs/charts/architecture-dark.svg": "generate_readme_charts.py",
            "benchmarks/HISTORY.md": "benchmark_history.py",
            "benchmarks/runs/engine-generation/example.json": "publish_benchmark_history.py",
            "QwenVoice.xcodeproj/project.pbxproj": "regenerate_project.sh",
            "Packages/VocelloQwen3Core/CURRENT_INVENTORY.json": "rebuild-current-inventory",
        }
        for relative, generator in cases.items():
            with self.subTest(path=relative):
                result = self.guard(relative)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(generator, result.stderr)

    def test_ordinary_files_are_allowed_silently(self):
        for relative in ("docs/reference/development-workflow.md", "Sources/QwenVoiceCore/EmotionPreset.swift",
                         "config/roadmap.json", "project.yml", "CLAUDE.md"):
            with self.subTest(path=relative):
                result = self.guard(relative)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "")

    def test_pinned_documents_ask_for_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            pinned = root / "docs" / "old.md"
            pinned.write_text("---\nstatus: historical\nowner: release-qa\nsummary: s\ncontentDigest: sha256:x\n---\nbody\n")
            live = root / "docs" / "live.md"
            live.write_text("---\nstatus: active\nowner: release-qa\nsummary: s\n---\nbody\n")
            asked = self.guard("docs/old.md", root)
            self.assertEqual(asked.returncode, 0, asked.stderr)
            decision = json.loads(asked.stdout)["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "ask")
            self.assertIn("contentDigest", decision["permissionDecisionReason"])
            self.assertEqual(self.guard("docs/live.md", root).stdout.strip(), "")


class ProjectYmlReminderTests(unittest.TestCase):
    def test_project_yml_edit_returns_regeneration_context(self):
        result = run_hook("project_yml_reminder.sh", {"file_path": str(REPO_ROOT / "project.yml")}, tool_name="Edit")
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("regenerate_project.sh --fast", context)

    def test_other_edits_are_silent(self):
        result = run_hook("project_yml_reminder.sh", {"file_path": str(REPO_ROOT / "README.md")}, tool_name="Edit")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class SessionStartTests(unittest.TestCase):
    def test_session_start_is_bounded_and_never_fails_without_a_device(self):
        # A PATH without xcrun/devicectl makes the probe fail fast; the hook must still exit 0.
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp)
            for tool in ("git", "python3", "perl", "awk", "head", "basename", "dirname", "bash", "sh", "cat", "tr"):
                real = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
                if real:
                    (fake_bin / tool).symlink_to(real)
            env = dict(os.environ, PATH=str(fake_bin), CLAUDE_PROJECT_DIR=str(REPO_ROOT))
            result = subprocess.run([str(HOOKS / "session_start.sh")], input="{}", text=True,
                                    capture_output=True, env=env, cwd=str(REPO_ROOT), check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Start and resume work", result.stdout)
        self.assertIn("-- git --", result.stdout)
        self.assertIn("Resume now", result.stdout)
        self.assertIn("paired iPhone", result.stdout)


class DevStatusTests(unittest.TestCase):
    def test_dev_status_reports_branch_receipt_and_primary_plan(self):
        result = subprocess.run(["scripts/dev.sh", "status"], cwd=str(REPO_ROOT), text=True,
                                capture_output=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in ("branch:", "dirty:", "verification:", "receipt:", "primaryPlan:"):
            self.assertIn(key, result.stdout)


if __name__ == "__main__":
    unittest.main()
