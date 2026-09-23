"""Exercise the repository guards through Claude Code payloads and the checked-in wiring."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/hooks"
SETTINGS = ROOT / ".claude/settings.json"
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}


def fixture_hooks(root):
    if root == ROOT:
        return HOOKS
    hooks = root / "scripts/hooks"
    shutil.copytree(HOOKS, hooks, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "scripts/privacy_scan.py", root / "scripts/privacy_scan.py")
    return hooks


def invoke(name, tool_input, *, tool_name="Edit", cwd=None, root=ROOT, event="PreToolUse"):
    payload = {"hook_event_name": event, "tool_name": tool_name,
               "tool_input": tool_input, "cwd": str(cwd or root)}
    hooks = fixture_hooks(root)
    return subprocess.run(
        [str(hooks / name)], input=json.dumps(payload), text=True, capture_output=True,
        cwd=cwd or root, timeout=20, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
    )


def edit(tool_name, path):
    return {EDIT_TOOLS[tool_name]: path}


def frontmatter(path: Path) -> dict[str, str]:
    """Flat `key: value` header; list values keep their raw lines. Dependency-free."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    fields: dict[str, str] = {}
    key = None
    for line in text.split("---\n", 2)[1].splitlines():
        if line.startswith("  - ") and key:
            fields[key] += line + "\n"
        elif ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return fields


GENERATED = ("docs/ROADMAP.md", "QwenVoice.xcodeproj/project.pbxproj",
             "benchmarks/runs/engine-generation/frozen.json",
             "Sources/Resources/qwenvoice_production_model_catalog.json",
             "docs/charts/architecture-dark.svg", "benchmarks/HISTORY.md",
             "Packages/VocelloQwen3Core/CURRENT_INVENTORY.json",
             "Packages/VocelloQwen3Core/FACADE_API_BASELINE.json")


class EditGuardTests(unittest.TestCase):
    def test_every_edit_tool_is_refused_on_generated_files(self):
        for tool_name in EDIT_TOOLS:
            for path in GENERATED:
                with self.subTest(tool=tool_name, path=path):
                    result = invoke("generated_file_guard.sh", edit(tool_name, path), tool_name=tool_name)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("Regenerate", result.stderr)

    def test_the_refusal_names_the_generator(self):
        result = invoke("generated_file_guard.sh", edit("Edit", "docs/ROADMAP.md"))
        self.assertIn("roadmap.py render", result.stderr)

    def test_relative_absolute_and_symlink_paths_resolve_to_the_same_guard(self):
        with tempfile.TemporaryDirectory(prefix="vocello hooks ") as tmp:
            root = Path(tmp).resolve()
            (root / "docs").mkdir()
            (root / "website").mkdir()
            (root / "alias").symlink_to(root / "docs", target_is_directory=True)
            for path in ("../docs/ROADMAP.md", str(root / "docs/ROADMAP.md"),
                         "../alias/ROADMAP.md", "../docs/../docs/ROADMAP.md"):
                with self.subTest(path=path):
                    result = invoke("generated_file_guard.sh", edit("Write", path),
                                    tool_name="Write", root=root, cwd=root / "website")
                    self.assertEqual(result.returncode, 2, result.stderr)

    def test_generated_files_stay_guarded_inside_agent_worktrees(self):
        worktree = ROOT / ".claude/worktrees/agent-1"
        for path, cwd in ((str(worktree / "docs/ROADMAP.md"), ROOT),
                          ("docs/ROADMAP.md", worktree),
                          (str(worktree / "benchmarks/runs/x.json"), ROOT)):
            with self.subTest(path=path, cwd=cwd):
                payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                                      "tool_input": {"file_path": path}, "cwd": str(cwd)})
                result = subprocess.run([str(HOOKS / "generated_file_guard.sh")], input=payload, text=True,
                                        capture_output=True, timeout=20,
                                        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)))
                self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": str(worktree / "project.yml")}, "cwd": str(ROOT)})
        result = subprocess.run([str(HOOKS / "project_yml_reminder.sh")], input=payload, text=True,
                                capture_output=True, timeout=20, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)))
        self.assertIn("regenerate_project.sh --fast", result.stdout)

    def test_ordinary_files_are_allowed(self):
        for path in ("CLAUDE.md", ".claude/rules/native.md", "docs/ordinary file.md",
                     "scripts/tool.py", "benchmarks/README.md"):
            for tool_name in EDIT_TOOLS:
                with self.subTest(tool=tool_name, path=path):
                    result = invoke("generated_file_guard.sh", edit(tool_name, path), tool_name=tool_name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_uninspectable_input_fails_closed(self):
        for tool_name, tool_input in (("Edit", {}), ("Edit", {"file_path": 5}), ("Write", {"file_path": ""}),
                                      ("Edit", {"file_path": "docs/a\nb.md"}),
                                      ("NotebookEdit", {"file_path": "docs/ROADMAP.md"}),
                                      ("TodoWrite", {"file_path": "docs/ordinary.md"})):
            with self.subTest(tool=tool_name, value=tool_input):
                result = invoke("generated_file_guard.sh", tool_input, tool_name=tool_name)
                self.assertEqual(result.returncode, 2, result.stderr)
        result = subprocess.run([str(HOOKS / "generated_file_guard.sh")], input="not json", text=True,
                                capture_output=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 2)

    def test_regeneration_reminder_follows_root_project_edits_only(self):
        for tool_name, path in (("Edit", "project.yml"), ("Write", str(ROOT / "project.yml")),
                                ("MultiEdit", "project.yml")):
            with self.subTest(tool=tool_name, path=path):
                result = invoke("project_yml_reminder.sh", edit(tool_name, path), tool_name=tool_name,
                                event="PostToolUse")
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "PostToolUse")
                self.assertIn("regenerate_project.sh --fast", output["additionalContext"])
        for path in ("fixtures/project.yml", "website/project.yml", "docs/ok.md"):
            with self.subTest(path=path):
                result = invoke("project_yml_reminder.sh", edit("Edit", path), event="PostToolUse")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


class SettingsWiringTests(unittest.TestCase):
    EXPECTED = {
        ("SessionStart", "startup|resume|clear|compact"): {"session_start.sh"},
        ("PreToolUse", "^Bash$"): {"commit_lint.sh", "policy_guard.sh"},
        ("PreToolUse", "^(Edit|Write|MultiEdit|NotebookEdit)$"): {"generated_file_guard.sh"},
        ("PostToolUse", "^(Edit|Write|MultiEdit)$"): {"project_yml_reminder.sh"},
    }

    def setUp(self):
        self.settings = json.loads(SETTINGS.read_text(encoding="utf-8"))

    def resolve(self, command: str, cwd: Path) -> Path:
        # Resolve the command exactly as a lifecycle hook does, without running it.
        result = subprocess.run(["bash", "-c", 'printf "%s\\n" ' + command], cwd=cwd,
                                env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)),
                                capture_output=True, text=True, check=True)
        return Path(result.stdout.strip())

    def test_the_hook_matrix_is_exact_and_every_hook_is_wired(self):
        matrix: dict[tuple[str, str], set[str]] = {}
        for event, entries in self.settings["hooks"].items():
            for entry in entries:
                re.compile(entry["matcher"])
                for hook in entry["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    self.assertLessEqual(hook["timeout"], 15)
                    self.assertTrue(hook["command"].startswith('"$CLAUDE_PROJECT_DIR"/scripts/hooks/'))
                    for cwd in (ROOT, ROOT / "website"):
                        path = self.resolve(hook["command"], cwd)
                        self.assertEqual(path.parent, HOOKS)
                        self.assertTrue(path.is_file() and os.access(path, os.X_OK))
                    matrix.setdefault((event, entry["matcher"]), set()).add(path.name)
        self.assertEqual(matrix, self.EXPECTED)
        self.assertEqual(set().union(*matrix.values()), {p.name for p in HOOKS.glob("*.sh")})

    def test_edit_matchers_select_only_file_edit_tools(self):
        edit_matchers = [entry["matcher"] for event in ("PreToolUse", "PostToolUse")
                         for entry in self.settings["hooks"][event] if entry["matcher"] != "^Bash$"]
        for matcher in edit_matchers:
            for tool_name in ("TodoWrite", "Read", "NotebookRead", "Bash", "WebFetch", "mcp__x__Write"):
                with self.subTest(matcher=matcher, tool=tool_name):
                    self.assertIsNone(re.search(matcher, tool_name))
        self.assertTrue(all(re.search(edit_matchers[0], tool) for tool in EDIT_TOOLS))

    def test_configured_pretool_hooks_allow_and_block_from_root_and_website(self):
        for cwd in (ROOT, ROOT / "website"):
            prefix = "../" if cwd.name == "website" else ""
            cases = [("Bash", {"command": "git push --force origin main"}, True),
                     ("Bash", {"command": "git push origin worktree-agent-1"}, True),
                     ("Bash", {"command": "git status --short"}, False),
                     ("Edit", {"file_path": f"{prefix}docs/ROADMAP.md"}, True),
                     ("Write", {"file_path": f"{prefix}docs/note.md"}, False),
                     ("NotebookEdit", {"notebook_path": f"{prefix}benchmarks/runs/x.ipynb"}, True)]
            for name, tool_input, blocked in cases:
                with self.subTest(cwd=cwd, tool=name, blocked=blocked):
                    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name,
                                          "tool_input": tool_input, "cwd": str(cwd)})
                    results = []
                    for entry in self.settings["hooks"]["PreToolUse"]:
                        if re.search(entry["matcher"], name):
                            for hook in entry["hooks"]:
                                results.append(subprocess.run(
                                    ["bash", "-c", hook["command"]], cwd=cwd, input=payload,
                                    env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)),
                                    capture_output=True, text=True, timeout=20))
                    self.assertTrue(results)
                    self.assertEqual(any(r.returncode == 2 for r in results), blocked)
                    self.assertTrue(all(r.returncode in (0, 2) for r in results))

    def test_consent_bound_lanes_are_never_pre_approved(self):
        permissions = self.settings["permissions"]
        for rule in permissions["allow"]:
            for lane in ("ui_test.sh", "ios_device.sh", "release.sh", "clean_build_caches.sh"):
                self.assertNotIn(lane, rule)
        self.assertTrue(any("scripts/ui_test.sh" in rule for rule in permissions["ask"]))
        self.assertTrue(any("scripts/ios_device.sh" in rule for rule in permissions["ask"]))
        for boundary in ("Bash(git push --force*)", "Bash(git worktree add*)", "Bash(git stash*)",
                         "Edit(QwenVoice.xcodeproj/**)"):
            self.assertIn(boundary, permissions["deny"])

    def test_agent_worktrees_are_allowed_but_only_main_is_pushed(self):
        permissions = self.settings["permissions"]
        # Worktree-isolated agents are allowed and branch from local main.
        for tool in ("EnterWorktree", "Agent(isolation:*)", "Agent(isolation:worktree)"):
            self.assertNotIn(tool, permissions["deny"])
        self.assertEqual(self.settings["worktree"]["baseRef"], "head")
        for boundary in ("Bash(git push --all*)", "Bash(git push --mirror*)", "Bash(git push --tags*)",
                         "Bash(git push --delete*)", "Bash(git push -u*)", "Bash(git push origin HEAD*)",
                         "Bash(git push origin worktree-*)", "Bash(git update-ref*)",
                         "Bash(git checkout -B*)", "Bash(git switch -C*)"):
            self.assertIn(boundary, permissions["deny"])
        self.assertEqual({rule for rule in permissions["allow"] if rule.startswith("Bash(git push")},
                         {"Bash(git push)", "Bash(git push origin main)"})
        for rule in ("Bash(git branch -D*)", "Bash(git worktree remove --force*)"):
            self.assertIn(rule, permissions["ask"])

    def test_xcodebuildmcp_simulator_tools_are_denied_and_never_allowed(self):
        permissions = self.settings["permissions"]
        suffix = "_" "sim"
        for name in ("build" + suffix, "build_run" + suffix, "test" + suffix, "boot" + suffix,
                     "install_app" + suffix, "launch_app" + suffix, "debug_attach" + suffix):
            self.assertIn(f"mcp__XcodeBuildMCP__{name}", permissions["deny"])
        for rule in permissions["allow"] + permissions["ask"]:
            self.assertFalse(rule.endswith(suffix), rule)


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
            "git worktree add .claude/worktrees/x -b worktree-x",
            "git branch feature/x",
            "git checkout -B experiment",
            "git switch -C topic",
            "git switch --force-create topic",
            "git update-ref refs/heads/main HEAD",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Main only", result.stderr)

    def test_only_main_is_pushed(self):
        for command in ("git push origin worktree-agent-1", "git push origin HEAD", "git push origin HEAD:main",
                        "git push --all", "git push --mirror", "git push --tags", "git push origin --delete main",
                        "git push origin :main", "git push -u origin topic", "git push origin main topic",
                        "git push origin v3.0.0", "git -C .claude/worktrees/a push origin worktree-a",
                        "git status && git push origin topic"):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("only main is ever pushed", result.stderr)
        for command in ("git push", "git push origin", "git push origin main", "git push -q origin main",
                        "git push origin main:main"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0)

    def test_git_spellings_do_not_bypass_the_main_only_rules(self):
        push = "pu" "sh"
        for command in (
            f"git -C . {push} --force origin main", f"git -c x=y {push} -f origin main",
            f"git {push} origin main -vf", f"git {push} -qf origin main",
            f"git --git-dir .git {push} origin topic", f"git -c alias.p={push} p origin topic",
            f"git -c remote.origin.{push}=refs/heads/topic:refs/heads/topic {push}",
            f"bash -c 'git {push} origin topic'", f"echo `git {push} origin topic`",
            f"echo $(git {push} origin topic)", f"(cd .. && git {push} origin topic)",
            "git -C . checkout -b topic", "git -c a=b switch -c topic",
            "git -C . update-ref refs/heads/main HEAD", "git branch -f main abc1234",
            "git branch -m topic main", "git checkout --orphan x", "git switch --orphan x",
            "git worktree move .claude/worktrees/a ../a",
            "git worktree remove .claude/worktrees/x --force", "git branch -d worktree-x --force",
            # abbreviated long options, flag clusters and --track
            f"git {push} --mirr origin", f"git {push} --al origin", f"git {push} --ta origin",
            f"git {push} --set-up origin main", "git checkout -qb x", "git checkout --track origin/topic",
            "git switch --cre x", "git branch --sort=refname x",
            # a command after a heredoc opener, wrappers, shells and substitutions
            f"cat <<EOF && git {push} origin topic\nbody\nEOF", f"timeout 60 git {push} origin topic",
            f"if true; then git {push} origin topic; fi", f"{{ git {push} origin topic; }}",
            f"bash -lc 'git {push} origin topic'", f"sh <<EOF\ngit {push} origin topic\nEOF",
            f"git status \"$(git {push} origin topic)\"", f"git \\\n {push} origin topic",
            # configuration that changes what git runs or publishes, and other ref writers
            f"git config remote.origin.mirror true && git {push}", "git config alias.x status",
            "git -calias.x=status x", "git --config-env alias.x=VAR x",
            f"GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0={push} git x origin topic",
            "git send-pack https://example.invalid/r.git topic", "git fetch . main:x", "git tag v9",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Main only", result.stderr)
        for command in (f"git {push} origin main 2>&1 | tail -5", f"git {push} origin main >/dev/null",
                        f"git {push} 2>&1", "git branch --list 'worktree-*'", "git branch -D worktree-x",
                        "git worktree remove --force .claude/worktrees/x", "git branch --contains abc1234",
                        f"git {push} origin main && git status", "git -C website status",
                        "git fetch origin", "git fetch origin main:refs/remotes/origin/main", "git tag -l",
                        "git config --get alias.x", "git branch --sort=refname", f"grep -rn {push} scripts",
                        f"git commit -F - <<'EOF'\nmention git {push} origin topic\nEOF"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0, self.guard(command).stderr)

    def test_lead_integration_commands_are_allowed(self):
        for command in ("git merge --ff-only worktree-agent-1", "git cherry-pick abc1234",
                        "git branch -d worktree-agent-1", "git worktree remove .claude/worktrees/agent-1",
                        "git worktree list --porcelain", "git worktree prune"):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 0, result.stderr)

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


class WorktreeCommitLintTests(unittest.TestCase):
    """Commits and pushes are judged in the checkout they act on, not the hook's."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        for key, value in (("user.email", "fixture@example.invalid"), ("user.name", "Fixture")):
            subprocess.run(["git", "-C", str(self.root), "config", key, value], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--allow-empty", "-m", "init"], check=True)

    def worktree(self, relative: str, branch: str) -> Path:
        path = self.root / relative
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", "-b", branch, str(path)],
                       check=True)
        return path

    def stage(self, checkout: Path, text: str = "ok\n") -> None:
        (checkout / "notes.md").write_text(text)
        subprocess.run(["git", "-C", str(checkout), "add", "notes.md"], check=True)

    def lint(self, command: str, cwd: Path):
        return invoke("commit_lint.sh", {"command": command}, tool_name="Bash", root=self.root, cwd=cwd)

    commit = "git com" "mit -m x"

    def test_agent_worktree_on_its_branch_may_commit(self):
        agent = self.worktree(".claude/worktrees/agent-1", "worktree-agent-1")
        self.stage(agent)
        result = self.lint(self.commit, agent)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.lint("git -C .claude/worktrees/agent-1 com" "mit -m x", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_misplaced_or_misnamed_worktrees_and_main_checkout_branches_are_blocked(self):
        cases = (
            (self.worktree("wt/agent-2", "worktree-agent-2"), "outside .claude/worktrees"),
            (self.worktree(".claude/worktrees/agent-3", "topic"), "worktree-* branch"),
        )
        for checkout, reason in cases:
            with self.subTest(checkout=checkout.name):
                result = self.lint(self.commit, checkout)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(reason, result.stderr)
        subprocess.run(["git", "-C", str(self.root), "switch", "-q", "-c", "worktree-z"], check=True)
        result = self.lint(self.commit, self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("directly on main", result.stderr)

    def test_the_worktree_index_is_scanned_not_the_main_checkout(self):
        agent = self.worktree(".claude/worktrees/agent-4", "worktree-agent-4")
        self.stage(agent, "logs live in " + "/Users/" + "someone/Library\n")
        result = self.lint(self.commit, agent)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("private path", result.stderr)

    def test_quoted_paths_with_spaces_chains_and_unresolvable_targets_are_judged(self):
        spaced = self.root.parent / "agent work"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", "-b", "topic", str(spaced)],
                       check=True)
        commit = "com" "mit"
        result = self.lint(f'git -C "{spaced}" {commit} -m x', self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("outside .claude/worktrees", result.stderr)
        # Every commit in a chain is judged in its own checkout: the second one
        # scans the main index, which holds a private path.
        agent = self.worktree(".claude/worktrees/agent-6", "worktree-agent-6")
        self.stage(self.root, "logs live in " + "/Users/" + "someone/Library\n")
        result = self.lint(f"git -C .claude/worktrees/agent-6 {commit} --dry-run -m z; git {commit} -m x",
                           self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("private path", result.stderr)
        subprocess.run(["git", "-C", str(self.root), "reset", "-q"], check=True)
        result = self.lint(f"git {commit} -m x && git -C .claude/worktrees/agent-6 pu" "sh", self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("only main is pushed", result.stderr)
        for command in (f'cd "$SOMEWHERE" && git {commit} -m x', f"GIT_DIR=/tmp/x git {commit} -m x",
                        f"git --work-tree=. {commit} -m x", f"pushd /tmp && git {commit} -m x"):
            with self.subTest(command=command):
                result = self.lint(command, agent)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("cannot tell which checkout", result.stderr)
        result = self.lint(f"git checkout worktree-agent-6 && git {commit} -m x", self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("may change the branch", result.stderr)
        result = self.lint(f"git checkout -- notes.md && git {commit} -m x", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.lint("git pu" "sh origin main 2>&1 | tail -5", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pushes_leave_only_the_main_checkout_on_main(self):
        agent = self.worktree(".claude/worktrees/agent-5", "worktree-agent-5")
        for command in ("git push", "git push origin main"):
            with self.subTest(command=command):
                result = self.lint(command, agent)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("only main is pushed", result.stderr)
                self.assertEqual(self.lint(command, self.root).returncode, 0)


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
                self.assertIn("CLAUDE.md: Start here", result.stdout)
                self.assertIn("local-status", result.stdout)
                self.assertIn("Checkpoint", result.stdout)
                self.assertFalse((root / "unexpected-operation").exists())


class ProjectSkillTests(unittest.TestCase):
    def test_skills_are_explicit_user_invoked_shortcuts(self):
        skills = sorted((ROOT / ".claude/skills").glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in skills},
                         {"ios-lane", "macos-ui-lane", "device-diagnostics", "release-evidence"})
        for path in skills:
            with self.subTest(skill=path.parent.name):
                metadata = frontmatter(path)
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertTrue(metadata["description"])
                self.assertTrue(metadata["argument-hint"])
                self.assertEqual(metadata["disable-model-invocation"], "true")
                self.assertRegex(path.read_text(encoding="utf-8"), r"\$(ARGUMENTS|0)")


class SubagentTests(unittest.TestCase):
    def test_project_subagents_are_read_only(self):
        agents = sorted((ROOT / ".claude/agents").glob("*.md"))
        self.assertEqual({p.stem for p in agents}, {"swift-review", "xcresult-triage"})
        for path in agents:
            with self.subTest(agent=path.stem):
                metadata = frontmatter(path)
                self.assertEqual(metadata["name"], path.stem)
                self.assertTrue(metadata["description"])
                tools = {tool.strip() for tool in metadata["tools"].split(",")}
                self.assertFalse(tools & set(EDIT_TOOLS), tools)
                self.assertFalse({"isolation", "memory", "permissionMode"} & set(metadata))


class RuleTests(unittest.TestCase):
    def test_every_rule_path_scope_matches_tracked_files(self):
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                                 check=True).stdout.splitlines()
        rules = sorted((ROOT / ".claude/rules").glob("*.md"))
        self.assertEqual({p.stem for p in rules}, {"native", "release"})
        for path in rules:
            globs = re.findall(r'^  - "([^"]+)"$', frontmatter(path).get("paths", ""), re.M)
            self.assertTrue(globs, path)
            for pattern in globs:
                with self.subTest(rule=path.stem, pattern=pattern):
                    self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for name in tracked))


if __name__ == "__main__":
    unittest.main()
