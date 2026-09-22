"""Exercise shared guards through Codex payloads and checked-in client wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/hooks"


def fixture_hooks(root):
    if root == ROOT:
        return HOOKS
    hooks = root / "scripts/hooks"
    shutil.copytree(HOOKS, hooks, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "scripts/privacy_scan.py", root / "scripts/privacy_scan.py")
    return hooks


def invoke(name, tool_input, *, tool_name="apply_patch", cwd=None, root=ROOT):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name,
               "tool_input": tool_input, "cwd": str(cwd or root)}
    hooks = fixture_hooks(root)
    return subprocess.run(
        [str(hooks / name)], input=json.dumps(payload), text=True, capture_output=True,
        cwd=cwd or root, timeout=20,
    )


def patch(*sections):
    return {"command": "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"}


class PatchGuardTests(unittest.TestCase):
    def test_each_edit_operation_protects_generated_files(self):
        for operation in ("Add", "Update", "Delete"):
            for path in ("docs/ROADMAP.md", "QwenVoice.xcodeproj/project.pbxproj",
                         "benchmarks/runs/engine-generation/frozen.json",
                         "Sources/Resources/qwenvoice_production_model_catalog.json",
                         "docs/charts/architecture-dark.svg", "benchmarks/HISTORY.md",
                         "Packages/VocelloQwen3Core/CURRENT_INVENTORY.json",
                         "Packages/VocelloQwen3Core/FACADE_API_BASELINE.json"):
                with self.subTest(operation=operation, path=path):
                    result = invoke("generated_file_guard.sh", patch(f"*** {operation} File: {path}"))
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("Regenerate", result.stderr)

    def test_a_later_file_in_a_multi_file_patch_is_checked(self):
        result = invoke("generated_file_guard.sh", patch(
            "*** Add File: docs/ordinary.md\n+ok",
            "*** Update File: docs/ROADMAP.md\n@@\n-old\n+new",
        ))
        self.assertEqual(result.returncode, 2)
        self.assertIn("roadmap.py render", result.stderr)

    def test_both_sides_of_a_move_are_protected(self):
        for source, destination in (("docs/ordinary.md", "docs/ROADMAP.md"),
                                    ("docs/ROADMAP.md", "docs/ordinary.md")):
            with self.subTest(source=source):
                result = invoke("generated_file_guard.sh", patch(
                    f"*** Update File: {source}\n*** Move to: {destination}\n@@\n-x\n+y"))
                self.assertEqual(result.returncode, 2)

    def test_relative_absolute_and_symlink_paths_resolve_to_the_same_guard(self):
        with tempfile.TemporaryDirectory(prefix="vocello hooks ") as tmp:
            root = Path(tmp).resolve()
            (root / "docs").mkdir()
            (root / "website").mkdir()
            (root / "alias").symlink_to(root / "docs", target_is_directory=True)
            for path in ("../docs/ROADMAP.md", str(root / "docs/ROADMAP.md"),
                         "../alias/ROADMAP.md", "../docs/../docs/ROADMAP.md"):
                with self.subTest(path=path):
                    result = invoke("generated_file_guard.sh", patch(f"*** Update File: {path}"),
                                    root=root, cwd=root / "website")
                    self.assertEqual(result.returncode, 2, result.stderr)

    def test_normal_edits_are_allowed_and_patch_content_is_not_a_path(self):
        result = invoke("generated_file_guard.sh", patch(
            "*** Add File: docs/ordinary file.md\n+*** Delete File: docs/ROADMAP.md",
            "*** Update File: scripts/tool.py\n*** Move to: scripts/new_tool.py\n@@\n-x\n+y",
        ))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_uninspectable_patch_fails_closed(self):
        for value in ({}, {"command": 5}, {"command": "not a patch"},
                      {"command": "*** Begin Patch\n*** End Patch"}):
            with self.subTest(value=value):
                result = invoke("generated_file_guard.sh", value)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_regeneration_reminder_finds_later_changes_and_moves(self):
        for section in ("*** Update File: project.yml\n@@\n-x\n+y",
                        "*** Update File: project.yml\n*** Move to: renamed.yml\n@@\n-x\n+y",
                        "*** Update File: source.yml\n*** Move to: project.yml\n@@\n-x\n+y"):
            with self.subTest(section=section):
                result = invoke("project_yml_reminder.sh", patch("*** Add File: docs/ok.md\n+x", section))
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "PostToolUse")
                self.assertIn("regenerate_project.sh --fast", output["additionalContext"])

    def test_unrelated_project_yml_does_not_trigger_a_root_regeneration(self):
        result = invoke("project_yml_reminder.sh", patch("*** Add File: fixtures/project.yml\n+x"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


class CodexWiringTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / ".codex/hooks.json").read_text())

    def test_wiring_resolves_shared_executable_hooks_from_root_and_website(self):
        referenced = set()
        for entries in self.config["hooks"].values():
            for entry in entries:
                re.compile(entry["matcher"])
                for hook in entry["hooks"]:
                    for cwd in (ROOT, ROOT / "website"):
                        # Resolve the command exactly as a lifecycle hook does,
                        # without executing session/device probes or a build.
                        command = 'printf "%s\\n" ' + hook["command"]
                        result = subprocess.run(["bash", "-c", command], cwd=cwd,
                                                capture_output=True, text=True, check=True)
                        path = Path(result.stdout.strip())
                        self.assertEqual(path.parent, HOOKS)
                        self.assertTrue(path.is_file() and os.access(path, os.X_OK))
                        referenced.add(path.name)
                    self.assertLessEqual(hook["timeout"], 15)
        self.assertEqual(referenced, {p.name for p in HOOKS.glob("*.sh")})

    def test_configured_pretool_hooks_allow_and_block_from_root_and_website(self):
        for cwd in (ROOT, ROOT / "website"):
            prefix = "../" if cwd.name == "website" else ""
            cases = [("Bash", {"command": "git push --force origin main"}, True),
                     ("Bash", {"command": "git status --short"}, False),
                     ("apply_patch", patch(f"*** Delete File: {prefix}docs/ROADMAP.md"), True),
                     ("apply_patch", patch(f"*** Add File: {prefix}docs/note.md\n+hello"), False)]
            for name, tool_input, blocked in cases:
                with self.subTest(cwd=cwd, tool=name, blocked=blocked):
                    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name,
                                          "tool_input": tool_input, "cwd": str(cwd)})
                    results = []
                    for entry in self.config["hooks"]["PreToolUse"]:
                        if re.search(entry["matcher"], name):
                            for hook in entry["hooks"]:
                                results.append(subprocess.run(
                                    ["bash", "-c", hook["command"]], cwd=cwd, input=payload,
                                    capture_output=True, text=True, timeout=20))
                    self.assertTrue(results)
                    self.assertEqual(any(r.returncode == 2 for r in results), blocked)
                    self.assertTrue(all(r.returncode in (0, 2) for r in results))

    def test_environment_actions_use_existing_entrypoints_without_automatic_setup(self):
        config = tomllib.loads((ROOT / ".codex/environments/environment.toml").read_text())
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["setup"]["script"], "")
        names = set()
        for action in config["actions"]:
            self.assertNotIn(action["name"], names)
            names.add(action["name"])
            args = shlex.split(action["command"])
            if args[0] == "scripts/dev.sh":
                self.assertIn(args[1], ("status", "check", "test", "build", "run"))
                self.assertTrue(os.access(ROOT / args[0], os.X_OK))
            elif args[0] == "npm":
                package = json.loads((ROOT / "website/package.json").read_text())
                self.assertEqual(args, ["npm", "--prefix", "website", "run", "check"])
                self.assertIn("check", package["scripts"])
            else:
                self.assertEqual(args, ["python3", "scripts/supply_chain_contract.py", "--installed", "all"])
                self.assertTrue((ROOT / args[1]).is_file())
        self.assertEqual(len(names), 7)


SIM = "Sim" + "ulator"

class PolicyGuardTests(unittest.TestCase):
    def guard(self, command: str):
        return invoke("policy_guard.sh", {"command": command}, tool_name="Bash")

    def test_ordinary_commands_are_allowed_quickly(self):
        for command in (
            "git status --short --branch",
            "scripts/dev.sh check",
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

    def test_heredoc_bodies_are_data_not_commands(self):
        # A commit message or generated file may mention guarded patterns.
        heredoc = ("git com" "mit -F - <<'EOF'\nExplain rm -rf build/cache and git push --force\n"
                   f"and platform=iOS {SIM} in prose.\nEOF\n")
        self.assertEqual(self.guard(heredoc).returncode, 0)
        # But a real command after the heredoc is still inspected.
        self.assertEqual(self.guard(heredoc + "git push --force").returncode, 2)

    def test_unparsable_payload_is_allowed(self):
        result = subprocess.run([str(HOOKS / "policy_guard.sh")], input="not json", text=True,
                                capture_output=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0)



class CommitLintTests(unittest.TestCase):
    def repo(self, root: Path, *, branch: str = "main") -> None:
        subprocess.run(["git", "init", "-q", "-b", branch, str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)

    def lint(self, root: Path, command: str = "git com" "mit -m x"):
        return invoke("commit_lint.sh", {"command": command}, tool_name="Bash", root=root)

    def test_non_commit_commands_are_allowed_without_touching_git(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.lint(Path(temp), "git status")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_commit_off_main_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo(root, branch="topic")
            result = self.lint(root)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("main", result.stderr)

    def test_global_git_options_before_the_commit_do_not_bypass_the_lint(self):
        commit = "com" "mit"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo(root, branch="topic")
            for command in (f"git -c core.hooksPath=/dev/null {commit} -q -F -",
                            f"git -C . {commit} -m x", f"git --no-pager {commit} -m x",
                            f"cd . && git {commit} -m x"):
                with self.subTest(command=command):
                    self.assertEqual(self.lint(root, command).returncode, 2)
            for command in ("git -c color.ui=never status", f"git log --grep={commit}",
                            f"git {commit}-tree HEAD^{{tree}}"):
                with self.subTest(command=command):
                    self.assertEqual(self.lint(root, command).returncode, 0)

    def test_staged_private_path_or_trailing_whitespace_is_blocked_and_clean_staging_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.repo(root)
            (root / "notes.md").write_text("logs live in " + "/Users/" + "someone/Library\n")
            subprocess.run(["git", "-C", str(root), "add", "notes.md"], check=True)
            self.assertEqual(self.lint(root).returncode, 2)
            (root / "notes.md").write_text("logs live in /Users/example/Library \n")
            subprocess.run(["git", "-C", str(root), "add", "notes.md"], check=True)
            self.assertEqual(self.lint(root).returncode, 2)
            (root / "notes.md").write_text("logs live in /Users/example/Library\n")
            subprocess.run(["git", "-C", str(root), "add", "notes.md"], check=True)
            result = self.lint(root)
            self.assertEqual(result.returncode, 0, result.stderr)


class DevStatusTests(unittest.TestCase):
    def test_dev_status_reports_branch_lanes_and_primary_plan(self):
        result = subprocess.run(["scripts/dev.sh", "status"], cwd=str(ROOT), text=True,
                                capture_output=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in ("branch:", "dirty:", "lanes:", "primaryPlan:"):
            self.assertIn(key, result.stdout)




class SessionStartTests(unittest.TestCase):
    def test_startup_uses_only_bounded_local_context_from_root_or_website(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hooks = fixture_hooks(root)
            (root / "docs").mkdir()
            (root / "website").mkdir()
            (root / "docs/development-progress.md").write_text("## Resume now\n### Current\nCheckpoint\n")
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            dev = root / "scripts/dev.sh"
            dev.write_text('#!/bin/sh\n[ "$1" = status ] || exit 1\necho local-status\n')
            dev.chmod(0o755)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for name in ("xcrun", "curl", "xcodebuild", "python3"):
                tool = fake_bin / name
                tool.write_text('#!/bin/sh\ntouch "' + str(root / "unexpected-operation") + '"\nexit 1\n')
                tool.chmod(0o755)
            for cwd in (root, root / "website"):
                result = subprocess.run([str(hooks / "session_start.sh")], cwd=cwd,
                                        env=dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}"),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("local-status", result.stdout)
                self.assertIn("Checkpoint", result.stdout)
                self.assertFalse((root / "unexpected-operation").exists())


class ProjectSkillTests(unittest.TestCase):
    def test_explicit_skills_have_discoverable_metadata(self):
        skills = sorted((ROOT / ".agents/skills").glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in skills},
                         {"ios-lane", "macos-ui-lane", "device-diagnostics", "release-evidence"})
        for path in skills:
            with self.subTest(skill=path.parent.name):
                # The checked-in skill metadata is a flat name/description header.
                # Keep this smoke check dependency-free like the hook runtime.
                metadata = dict(line.split(": ", 1) for line in
                                path.read_text().split("---", 2)[1].strip().splitlines())
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertTrue(metadata["description"])
                policy = (path.parent / "agents/openai.yaml").read_text()
                self.assertRegex(policy, r"(?m)^policy:\s*\n +allow_implicit_invocation: false\s*$")
