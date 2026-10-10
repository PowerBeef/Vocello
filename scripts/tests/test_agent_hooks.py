"""Exercise repository safeguards through Codex payloads and checked-in configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/hooks"
SETTINGS = ROOT / ".codex/hooks.json"


def fixture_hooks(root):
    if root == ROOT:
        return HOOKS
    hooks = root / "scripts/hooks"
    shutil.copytree(HOOKS, hooks, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "scripts/privacy_scan.py", root / "scripts/privacy_scan.py")
    return hooks


def invoke(name, tool_input, *, tool_name="apply_patch", cwd=None, root=ROOT, event="PreToolUse"):
    payload = {"hook_event_name": event, "tool_name": tool_name,
               "tool_input": tool_input, "cwd": str(cwd or root)}
    hooks = fixture_hooks(root)
    interpreter = "python3" if name.endswith(".py") else "bash"
    return subprocess.run(
        [interpreter, str(hooks / name)], input=json.dumps(payload), text=True, capture_output=True,
        cwd=cwd or root, timeout=20, env=dict(os.environ, VOCELLO_PROJECT_ROOT=str(root)),
    )


def edit(path, operation="update", *, move_to=None):
    header = {"add": "Add", "update": "Update", "delete": "Delete"}[operation]
    lines = ["*** Begin Patch", f"*** {header} File: {path}"]
    if move_to is not None:
        lines.append(f"*** Move to: {move_to}")
    if operation == "add":
        lines.append("+fixture")
    elif operation == "update":
        lines.extend(["@@", "-before", "+after"])
    lines.append("*** End Patch")
    return {"command": "\n".join(lines) + "\n"}


def initialize_repo(root):
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, value in (("user.email", "fixture@example.invalid"), ("user.name", "Fixture")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "init"], check=True)


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
             "Sources/Resources/third_party_attributions.json",
             "Sources/SharedSupport/Services/HantHansFoldTable.swift",
             "docs/charts/architecture-dark.svg", "benchmarks/HISTORY.md",
             "Packages/VocelloQwen3Core/CURRENT_INVENTORY.json",
             "Packages/VocelloQwen3Core/FACADE_API_BASELINE.json")


class EditGuardTests(unittest.TestCase):
    def test_every_patch_operation_is_refused_on_generated_files(self):
        for operation in ("add", "update", "delete"):
            for path in GENERATED:
                with self.subTest(operation=operation, path=path):
                    result = invoke("generated_file_guard.sh", edit(path, operation))
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("Regenerate", result.stderr)

    def test_the_refusal_names_the_generator(self):
        result = invoke("generated_file_guard.sh", edit("docs/ROADMAP.md"))
        self.assertIn("roadmap.py render", result.stderr)

    def test_relative_absolute_and_symlink_paths_resolve_to_the_same_guard(self):
        with tempfile.TemporaryDirectory(prefix="vocello hooks ") as tmp:
            root = Path(tmp).resolve()
            initialize_repo(root)
            (root / "docs").mkdir()
            (root / "website").mkdir()
            (root / "alias").symlink_to(root / "docs", target_is_directory=True)
            for path in ("../docs/ROADMAP.md", str(root / "docs/ROADMAP.md"),
                         "../alias/ROADMAP.md", "../docs/../docs/ROADMAP.md"):
                with self.subTest(path=path):
                    result = invoke("generated_file_guard.sh", edit(path), root=root, cwd=root / "website")
                    self.assertEqual(result.returncode, 2, result.stderr)

    def test_generated_files_stay_guarded_in_registered_worktrees_at_any_path(self):
        with tempfile.TemporaryDirectory(prefix="vocello linked hooks ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            worktree = root.parent / "agent workspace"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "codex/agent", str(worktree)], check=True)
            for path, cwd in ((str(worktree / "docs/ROADMAP.md"), root),
                              ("docs/ROADMAP.md", worktree),
                              (str(worktree / "benchmarks/runs/x.json"), root)):
                with self.subTest(path=path, cwd=cwd):
                    result = invoke("generated_file_guard.sh", edit(path), root=root, cwd=cwd)
                    self.assertEqual(result.returncode, 2, result.stderr)
            result = invoke("project_yml_reminder.sh", edit(str(worktree / "project.yml")),
                            event="PostToolUse", root=root)
            self.assertIn("regenerate_project.sh --fast", result.stdout)

    def test_case_variants_of_a_generated_path_are_the_same_file(self):
        for path in ("docs/roadmap.md", "DOCS/ROADMAP.MD", "qwenvoice.xcodeproj/project.pbxproj"):
            with self.subTest(path=path):
                self.assertEqual(invoke("generated_file_guard.sh", edit(path)).returncode, 2)

    def test_ordinary_files_with_spaces_are_allowed(self):
        for path in ("AGENTS.md", "docs/reference/native-engineering.md", "docs/ordinary file.md",
                     "scripts/tool.py", "benchmarks/README.md"):
            for operation in ("add", "update", "delete"):
                with self.subTest(operation=operation, path=path):
                    result = invoke("generated_file_guard.sh", edit(path, operation))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_every_file_in_a_multi_file_patch_is_guarded(self):
        ordinary = edit("docs/ordinary file.md", "add")["command"].splitlines()[1:-1]
        generated = edit("docs/ROADMAP.md")["command"].splitlines()[1:-1]
        for body in ([*ordinary, *generated], [*generated, *ordinary]):
            command = "\n".join(["*** Begin Patch", *body, "*** End Patch", ""])
            result = invoke("generated_file_guard.sh", {"command": command})
            self.assertEqual(result.returncode, 2, result.stderr)
        other = edit("scripts/ordinary.py")["command"].splitlines()[1:-1]
        command = "\n".join(["*** Begin Patch", *ordinary, *other, "*** End Patch", ""])
        result = invoke("generated_file_guard.sh", {"command": command})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_project_root_fallback_works_without_an_environment_override(self):
        with tempfile.TemporaryDirectory(prefix="vocello fallback hooks ") as tmp:
            root = Path(tmp).resolve()
            initialize_repo(root)
            (root / "website").mkdir()
            hooks = fixture_hooks(root)
            environment = dict(os.environ)
            environment.pop("VOCELLO_PROJECT_ROOT", None)
            for path, expected in (("../docs/ROADMAP.md", 2), ("../docs/ordinary file.md", 0)):
                payload = {"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                           "tool_input": edit(path), "cwd": str(root / "website")}
                result = subprocess.run(["bash", str(hooks / "generated_file_guard.sh")],
                                        input=json.dumps(payload), text=True, capture_output=True,
                                        cwd=root / "website", env=environment, timeout=20)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_rename_source_and_destination_are_both_guarded(self):
        for source, destination in (("docs/ordinary file.md", "docs/ROADMAP.md"),
                                    ("docs/ROADMAP.md", "docs/ordinary file.md")):
            with self.subTest(source=source, destination=destination):
                result = invoke("generated_file_guard.sh", edit(source, move_to=destination))
                self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(invoke("generated_file_guard.sh", edit("docs/ordinary file.md", move_to="docs/moved file.md")).returncode, 0)

    def test_uninspectable_input_fails_closed(self):
        inputs = [{}, {"command": 5}, {"command": ""}, {"command": "not a patch"},
                  {"command": "*** Begin Patch\n*** End Patch\n"},
                  {"command": "*** Begin Patch\n*** Add File: docs/a.md\n+content\n"},
                  {"command": "*** Begin Patch\n*** Add File: \n+x\n*** End Patch\n"},
                  {"command": "*** Begin Patch\n*** Add File: docs/a.md\ninvalid body\n*** End Patch\n"},
                  {"command": "*** Begin Patch\n*** Update File: docs/a.md\n*** Move to: docs/b.md\n*** Move to: docs/c.md\n@@\n-x\n+y\n*** End Patch\n"},
                  {"command": "*** Begin Patch\n*** Unexpected File: docs/a.md\n*** End Patch\n"}]
        for tool_input in inputs:
            with self.subTest(value=tool_input):
                result = invoke("generated_file_guard.sh", tool_input)
                self.assertEqual(result.returncode, 2, result.stderr)
        result = invoke("generated_file_guard.sh", edit("docs/ordinary.md"), tool_name="UnknownTool")
        self.assertEqual(result.returncode, 2, result.stderr)
        for payload in ("not json", "[]", '"not an object"', "null"):
            with self.subTest(payload=payload):
                result = subprocess.run(["bash", str(HOOKS / "generated_file_guard.sh")], input=payload, text=True,
                                        capture_output=True, check=False, timeout=20)
                self.assertEqual(result.returncode, 2)

    def test_regeneration_reminder_follows_specification_and_membership_inputs(self):
        for path in ("project.yml", str(ROOT / "project.yml"), "Sources/Fixture.swift", "Tests/New Test.swift"):
            for operation in ("add", "update", "delete"):
                with self.subTest(path=path, operation=operation):
                    result = invoke("project_yml_reminder.sh", edit(path, operation), event="PostToolUse")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(output["hookEventName"], "PostToolUse")
                    self.assertIn("regenerate_project.sh --fast", output["additionalContext"])
        result = invoke("project_yml_reminder.sh", edit("docs/old.md", move_to="Sources/New.swift"), event="PostToolUse")
        self.assertIn("regenerate_project.sh --fast", result.stdout)
        for path in ("fixtures/project.yml", "website/project.yml", "docs/ok.md"):
            with self.subTest(path=path):
                result = invoke("project_yml_reminder.sh", edit(path), event="PostToolUse")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


class SettingsWiringTests(unittest.TestCase):
    EXPECTED = {
        ("SessionStart", "startup|resume|clear|compact"): {"worker_lifecycle.py", "session_start.sh"},
        ("PreToolUse", "^Bash$"): {"commit_lint.sh", "policy_guard.sh"},
        ("PreToolUse", "^apply_patch$"): {"generated_file_guard.sh"},
        ("PreToolUse", "^mcp__.*$"): {"simulator_tool_guard.py"},
        ("PostToolUse", "^apply_patch$"): {"project_yml_reminder.sh"},
        ("SubagentStart", "*"): {"worker_lifecycle.py"},
        ("SubagentStop", "*"): {"worker_lifecycle.py"},
        ("SessionEnd", "*"): {"worker_lifecycle.py"},
    }

    def setUp(self):
        self.settings = json.loads(SETTINGS.read_text(encoding="utf-8"))

    def resolve(self, command: str, cwd: Path) -> tuple[str, Path]:
        # Expand the trusted checked-in command as a hook would, without running
        # the hook itself. Each configured command has exactly interpreter+path.
        result = subprocess.run(["bash", "-c", 'printf "%s\\n" ' + command], cwd=cwd,
                                capture_output=True, text=True, check=True)
        interpreter, path = result.stdout.splitlines()
        return interpreter, Path(path)

    def test_the_hook_matrix_is_exact_and_commands_resolve_from_nested_directories(self):
        matrix = {}
        for event, entries in self.settings["hooks"].items():
            for entry in entries:
                matcher = entry.get("matcher", "")
                if matcher != "*":
                    re.compile(matcher)
                for hook in entry["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    self.assertLessEqual(hook.get("timeout", 15), 15)
                    for cwd in (ROOT, ROOT / "website"):
                        interpreter, path = self.resolve(hook["command"], cwd)
                        self.assertEqual(hook["command"], f'{interpreter} "$(git rev-parse --show-toplevel)/scripts/hooks/{path.name}"')
                        self.assertEqual(interpreter, "python3" if path.suffix == ".py" else "bash")
                        self.assertEqual(path.parent, HOOKS)
                        self.assertTrue(path.is_file())
                    matrix.setdefault((event, matcher), set()).add(path.name)
        self.assertEqual(matrix, self.EXPECTED)

    def test_matchers_select_only_the_intended_tool_family(self):
        for event in ("PreToolUse", "PostToolUse"):
            for entry in self.settings["hooks"][event]:
                matcher = entry["matcher"]
                for tool in ("apply_patch", "Bash", "Read", "WebFetch", "mcp__x__Write", "mcp__xcodebuildmcp__build_sim"):
                    expected = ((matcher == "^apply_patch$" and tool == "apply_patch")
                                or (matcher == "^Bash$" and tool == "Bash")
                                or (matcher == "^mcp__.*$" and tool.startswith("mcp__")))
                    self.assertEqual(bool(re.search(matcher, tool)), expected)

    def test_configured_pretool_hooks_allow_and_block_from_root_and_website(self):
        for cwd in (ROOT, ROOT / "website"):
            prefix = "../" if cwd.name == "website" else ""
            cases = [("Bash", {"command": "git push --force origin main"}, True),
                     ("Bash", {"command": "git push origin codex/agent-1"}, True),
                     ("Bash", {"command": "git status --short"}, False),
                     ("apply_patch", edit(f"{prefix}docs/ROADMAP.md"), True),
                     ("apply_patch", edit(f"{prefix}docs/note.md", "add"), False),
                     ("mcp__xcodebuildmcp__build_sim", {}, True),
                     ("mcp__xcodebuildmcp__list_devices", {}, False)]
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
                                    env=dict(os.environ, VOCELLO_PROJECT_ROOT=str(ROOT)),
                                    capture_output=True, text=True, timeout=20))
                    self.assertTrue(results)
                    self.assertEqual(any(r.returncode == 2 for r in results), blocked)
                    self.assertTrue(all(r.returncode in (0, 2) for r in results))


class SimulatorToolGuardTests(unittest.TestCase):
    def test_simulator_mcp_routes_are_blocked_and_device_routes_remain_available(self):
        for tool in ("mcp__xcodebuildmcp__build_sim", "mcp__XcodeBuildMCP__boot_sim",
                     "mcp__xcodebuildmcp__debug_attach_sim", "mcp__xcodebuildmcp__simctl"):
            with self.subTest(tool=tool):
                result = invoke("simulator_tool_guard.py", {}, tool_name=tool)
                self.assertEqual(result.returncode, 2, result.stderr)
        for tool in ("mcp__xcodebuildmcp__list_devices", "mcp__xcodebuildmcp__build_device",
                     "mcp__sosumi__search", "mcp__xcodebuildmcp__build_macos"):
            with self.subTest(tool=tool):
                result = invoke("simulator_tool_guard.py", {}, tool_name=tool)
                self.assertEqual(result.returncode, 0, result.stderr)

SIM = "Sim" + "ulator"

class PolicyGuardTests(unittest.TestCase):
    def guard(self, command: str):
        return invoke("policy_guard.sh", {"command": command}, tool_name="Bash")

    def test_linked_worktree_cache_paths_resolve_against_the_actual_checkout(self):
        with tempfile.TemporaryDirectory(prefix="vocello cache hooks ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            agent = root.parent / "agent workspace"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "codex/cache", str(agent)], check=True)
            for command in ("rm -rf build/cache", "rm -rf build", f'rm -rf "{agent}/build/cache"'):
                with self.subTest(command=command):
                    result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root, cwd=agent)
                    self.assertEqual(result.returncode, 2, result.stderr)
            result = invoke("policy_guard.sh", {"command": "rm -rf build/scratch/probe"},
                            tool_name="Bash", root=root, cwd=agent)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_a_scoped_branch_creation_in_a_registered_linked_checkout_is_allowed(self):
        with tempfile.TemporaryDirectory(prefix="vocello branch hooks ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            agent = root.parent / "detached agent"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(agent), "HEAD"], check=True)
            allowed = ("git switch -c codex/scoped", "git switch -c codex/scoped HEAD")
            for command in allowed:
                with self.subTest(command=command):
                    result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root, cwd=agent)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root)
                    self.assertEqual(result.returncode, 2, result.stderr)
            for command in ("git switch -c topic", "git switch -c codex/scoped origin/main",
                            "git switch -C codex/scoped", "git checkout -b codex/scoped",
                            "git worktree add ../another", "git branch codex/scoped"):
                with self.subTest(command=command):
                    result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root, cwd=agent)
                    self.assertEqual(result.returncode, 2, result.stderr)

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

    def test_other_spellings_of_unsupported_destinations_are_blocked(self):
        sdk = "iphone" + SIM.lower()
        for command in (
            f"xcodebuild -scheme VocelloiOS -sdk {sdk} build",
            f"xcodebuild build -destination 'platform=iOS{SIM}'",
            f"swift build --triple arm64-apple-ios26.0-{SIM.lower()}",
            f"open -a {SIM}", f"open -g -a '{SIM}'",
            "xcrun simctl --set /tmp/devices boot 1234",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Physical iPhone only", result.stderr)
        self.assertEqual(self.guard("xcodebuild -scheme VocelloiOS -sdk iphoneos build").returncode, 0)
        for command in (
            f"xcodebuild -destination platform=iOS\\ {SIM},name=iPhone\\ 17",
            f"xcodebuild -destination 'platform=visionOS {SIM}'",
            f"open -na {SIM}", f"open /Applications/Xcode.app/Contents/Developer/Applications/{SIM}.app",
            "xcrun simctl bootstatus 1234 -b", "xcrun simctl spawn booted log stream",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 2)
        # A pattern never reaches across a line or a separator, and prose is not a destination.
        for command in ("xcrun simctl list\nnpm install", "xcrun simctl list devices\necho boot done",
                        "xcrun simctl list devices | grep Booted; echo install done",
                        f"gh issue list --search 'ios-{SIM.lower()} crash'", "echo open -a Preview"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0)

    def test_whole_cache_deletion_is_blocked_in_every_spelling(self):
        for command in ("rm -r -f build", "rm --recursive --force build", 'rm -rf "build"', "rm -rf build/*",
                        "rm -rf ./build/.", 'rm -rf "$PWD/build"', "rm -fr tmp build/cache", "sudo rm -rf build",
                        "find build -delete", "find ./build/cache -type f -delete",
                        "ls && rm -rf build/cache/xcode"):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("clean_build_caches.sh", result.stderr)
        for command in ("rm -rf tmp && ls build", "rm build/notes.txt", "rm -rf build/artifacts/old-run",
                        "find build -name '*.log'", "rm -rf rebuild"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0)

    def test_build_output_paths_are_resolved_not_matched_as_text(self):
        root = str(ROOT)
        for command in (f'rm -rf "{root}/build"', 'rm -rf "$VOCELLO_PROJECT_ROOT/build"', "rm -rf ../Vocello/build"
                        if ROOT.name == "Vocello" else "rm -rf ./build", "cd build && rm -rf cache",
                        "cd build && rm -rf ./cache/xcode", "rm -rf build/c*", "rm -rf build/{cache,artifacts}",
                        "rm -rf build//cache", "rm -rf build/artifacts/../cache", "bash -c 'rm -rf build'",
                        "find build -exec rm -rf {} +", "find build/cache -type f -exec rm {} \\;",
                        "mv build /tmp/gone", "/bin/rm -rf build"):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("clean_build_caches.sh", result.stderr)
        heredoc_note = "bash scripts/x.sh <<'EOF'\nnote: never rm -rf build\nEOF\n"
        message = "git com" "mit -m 'note\n\nfind build -delete\n'"
        for command in ("cd website && rm -rf build", "git log --grep='rm -rf build/cache'",
                        "rm -rf build/cache-old-notes.txt", "find build -name '*.log' -newer x -delete",
                        "find build -type d -empty -delete", 'rm -rf "$TMPDIR/build"', heredoc_note, message,
                        "python3 - <<'EOF'\nimport shutil  # rm -rf build\nEOF\n"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0)

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
            "git worktree add wt/x -b worktree-x",
            "git branch feature/x",
            "git checkout -B experiment",
            "git switch -C topic",
            "git switch --force-create topic",
            "git update-ref refs/heads/main HEAD",
        ):
            with self.subTest(command=command):
                result = self.guard(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("only published branch", result.stderr)

    def test_only_main_is_pushed(self):
        for command in ("git push origin codex/agent-1", "git push origin HEAD", "git push origin HEAD:main",
                        "git push --all", "git push --mirror", "git push --tags", "git push origin --delete main",
                        "git push origin :main", "git push -u origin topic", "git push origin main topic",
                        "git push origin v3.0.0", "git -C wt/a push origin worktree-a",
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
            "git worktree move wt/a ../a",
            "git worktree remove wt/x --force", "git branch -d worktree-x --force",
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
                self.assertIn("only published branch", result.stderr)
        for command in (f"git {push} origin main 2>&1 | tail -5", f"git {push} origin main >/dev/null",
                        f"git {push} 2>&1", "git branch --list 'worktree-*'", "git branch -D worktree-x",
                        "git worktree remove --force wt/x", "git branch --contains abc1234",
                        f"git {push} origin main && git status", "git -C website status",
                        "git fetch origin", "git fetch origin main:refs/remotes/origin/main", "git tag -l",
                        "git config --get alias.x", "git branch --sort=refname", f"grep -rn {push} scripts",
                        f"git commit -F - <<'EOF'\nmention git {push} origin topic\nEOF"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0, self.guard(command).stderr)

    def test_lead_integration_commands_are_allowed(self):
        for command in ("git merge --ff-only codex/agent-1", "git cherry-pick abc1234",
                        "git branch -d codex/agent-1", "git worktree remove wt/agent-1",
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

    def test_copies_onto_pbxproj_are_blocked_but_copies_from_it_are_not(self):
        for command in ("cp /tmp/edited.pbxproj QwenVoice.xcodeproj/project.pbxproj",
                        "mv x QwenVoice.xcodeproj/project.pbxproj && echo done"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 2)
        self.assertEqual(self.guard("cp QwenVoice.xcodeproj/project.pbxproj /tmp/backup").returncode, 0)
        target = "QwenVoice.xcodeproj/project.pbxproj"
        for command in (f"cp /tmp/x {target}\nls", f"mv /tmp/x {target} 2>/dev/null", f"cp /tmp/x {target} # restore",
                        f"(cp /tmp/x {target})", f"/bin/cp /tmp/x {target}", "cp /tmp/project.pbxproj QwenVoice.xcodeproj/",
                        f"rsync /tmp/x {target}", f"dd if=/tmp/x of={target}",
                        "cd QwenVoice.xcodeproj && cp /tmp/x project.pbxproj"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 2)
        commit = "git com" "mit"
        for command in (f"pip install x\nwc -l {target}", f"cp a b\ngit diff --stat -- {target}",
                        f"mv a b\ngrep -c PBX {target}", f'{commit} -m "docs: cp over project.pbxproj"'):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 0)

    def test_a_heredoc_fed_to_a_shell_is_commands(self):
        for body in ("rm -rf build/cache", f"xcodebuild -destination 'platform=iOS {SIM}'",
                     "echo x >> QwenVoice.xcodeproj/project.pbxproj"):
            with self.subTest(body=body):
                self.assertEqual(self.guard(f"bash <<'EOF'\n{body}\nEOF\n").returncode, 2)
                self.assertEqual(self.guard(f"cat > notes.txt <<'EOF'\n{body}\nEOF\n").returncode, 0)

    def test_git_lookups_and_mid_word_hashes_do_not_hide_a_command(self):
        push = "pu" "sh"
        for command in (f"$(which git) {push} --force origin main", f'"$(command -v git)" {push} -f origin main',
                        f"`which git` {push} --force origin main",
                        f"echo issue#12 && git {push} --force origin main",
                        f"git log --grep=fix#3; git {push} origin topic"):
            with self.subTest(command=command):
                self.assertEqual(self.guard(command).returncode, 2)
        self.assertEqual(self.guard("echo issue#12 && git status").returncode, 0)

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


class CommitContentLintTests(CommitLintTests):
    """A commit that records more than the index holds when the hook runs is checked on the working tree."""

    PRIVATE = "logs live in " + "/Users/" + "someone/Library\n"

    def committed(self, root: Path) -> None:
        self.repo(root)
        (root / "notes.md").write_text("ok\n")
        subprocess.run(["git", "-C", str(root), "add", "notes.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)

    def test_the_staged_blob_is_scanned_not_the_working_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.committed(root)
            (root / "notes.md").write_text(self.PRIVATE)
            subprocess.run(["git", "-C", str(root), "add", "notes.md"], check=True)
            (root / "notes.md").write_text("cleaned in the working copy only\n")
            result = self.lint(root)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("staged content", result.stderr)
            # The reverse: a private working copy that is not staged does not block a plain commit.
            subprocess.run(["git", "-C", str(root), "reset", "-q", "--hard"], check=True)
            (root / "other.md").write_text("ok\n")
            subprocess.run(["git", "-C", str(root), "add", "other.md"], check=True)
            (root / "notes.md").write_text(self.PRIVATE)
            self.assertEqual(self.lint(root).returncode, 0)

    def test_commits_that_take_working_tree_content_are_scanned_there(self):
        commit = "com" "mit"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.committed(root)
            (root / "notes.md").write_text(self.PRIVATE)
            for command in (f"git {commit} --all -m x", f"git {commit} -am x", f"git {commit} -qa -m x",
                            f"git {commit} -m x notes.md", f"git {commit} -m x -- notes.md",
                            f"git {commit} --only notes.md -m x", f"git add notes.md && git {commit} -m x",
                            f"git add -A; git {commit} -q -F -"):
                with self.subTest(command=command):
                    result = self.lint(root, command)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("working-tree file", result.stderr)
            # An untracked file a chained add would take in is scanned too.
            subprocess.run(["git", "-C", str(root), "checkout", "-q", "--", "notes.md"], check=True)
            (root / "new.md").write_text(self.PRIVATE)
            self.assertEqual(self.lint(root, f"git add new.md && git {commit} -m x").returncode, 2)
            (root / "new.md").write_text("ok \n")
            subprocess.run(["git", "-C", str(root), "add", "-N", "new.md"], check=True)
            result = self.lint(root, f"git {commit} -am x")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("whitespace", result.stderr)
            (root / "new.md").write_text("ok\n")
            self.assertEqual(self.lint(root, f"git add new.md && git {commit} -m x").returncode, 0)
            self.assertEqual(self.lint(root, f"git {commit} -m 'a message' --author 'A <a@example.invalid>'").returncode, 0)

    def test_a_message_that_spans_lines_does_not_hide_what_follows_it(self):
        commit = "com" "mit"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.committed(root)
            (root / "notes.md").write_text(self.PRIVATE)
            heredoc = "$(cat <<'EOF'\nsubject\n\nbody\nEOF\n)"
            for command in (f'git {commit} -m "subject\n\nbody" -a', f'git {commit} -m "subject\n\nbody" notes.md',
                            f'git {commit} -m "{heredoc}" notes.md', f'git {commit} -m "{heredoc}" --all',
                            f"git {commit} -vam x", f"git -c x=y {commit} -a -m x"):
                with self.subTest(command=command):
                    self.assertEqual(self.lint(root, command).returncode, 2)
            # Attached option values are not flags, and a redirection is not a pathspec.
            for command in (f"git {commit} -Spatrice -m x", f"git {commit} -uno -m x",
                            f'git {commit} -m "fix: handle -a flag"', f"git {commit} -m x >| /dev/null",
                            f"git {commit} --amend --no-edit", f"git {commit} -qm -a"):
                with self.subTest(command=command):
                    self.assertEqual(self.lint(root, command).returncode, 0)

    def test_the_scan_follows_what_the_commit_takes_and_nothing_else(self):
        commit = "com" "mit"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.committed(root)
            (root / ".gitignore").write_text("out/\n*.log\n")
            (root / "a.py").write_text("ok\n")
            # Unrelated work in the tree never blocks a commit of named paths.
            (root / "scratch.txt").write_text(self.PRIVATE)
            (root / "notes.md").write_text("unrelated trailing space \n")
            result = self.lint(root, f"git add a.py .gitignore && git {commit} -q -F - <<'EOF'\nmsg\nEOF")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.lint(root, f"git {commit} -m x a.py").returncode, 0)
            # But a directory, `-u` and `-A` take what they reach.
            self.assertEqual(self.lint(root, f"git add . && git {commit} -m x").returncode, 2)
            self.assertEqual(self.lint(root, f"git add -u && git {commit} -m x").returncode, 2)  # the whitespace
            self.assertEqual(self.lint(root, f"git add -A && git {commit} -m x").returncode, 2)
            # A force-added ignored file is scanned although git does not list it.
            (root / "out").mkdir()
            (root / "out/evidence.json").write_text(self.PRIVATE)
            (root / "run.log").write_text(self.PRIVATE)
            for command in (f"git add -f out/evidence.json && git {commit} -m x",
                            f"git add --force run.log && git {commit} -m x"):
                with self.subTest(command=command):
                    self.assertEqual(self.lint(root, command).returncode, 2)


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
        agent = self.worktree("wt/agent-1", "codex/agent-1")
        self.stage(agent)
        result = self.lint(self.commit, agent)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.lint("git -C wt/agent-1 com" "mit -m x", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_branch_and_unrelated_repository_worktrees_are_blocked(self):
        checkout = self.worktree("wt/wrong-branch", "topic")
        result = self.lint(self.commit, checkout)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("codex/* branch", result.stderr)
        unrelated = self.root.parent / "unrelated repository"
        initialize_repo(unrelated)
        foreign = unrelated.parent / "foreign agent"
        subprocess.run(["git", "-C", str(unrelated), "worktree", "add", "-q", "-b", "codex/foreign", str(foreign)], check=True)
        result = self.lint(self.commit, foreign)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("another repository", result.stderr)
        subprocess.run(["git", "-C", str(self.root), "switch", "-q", "-c", "codex/wrong-main"], check=True)
        result = self.lint(self.commit, self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("directly on main", result.stderr)

    def test_the_worktree_index_is_scanned_not_the_main_checkout(self):
        agent = self.worktree("wt/agent-4", "codex/agent-4")
        self.stage(agent, "logs live in " + "/Users/" + "someone/Library\n")
        result = self.lint(self.commit, agent)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("private path", result.stderr)

    def test_quoted_paths_with_spaces_chains_and_unresolvable_targets_are_judged(self):
        spaced = self.root.parent / "agent work"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", "-b", "codex/spaced", str(spaced)],
                       check=True)
        commit = "com" "mit"
        result = self.lint(f'git -C "{spaced}" {commit} -m x', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Every commit in a chain is judged in its own checkout: the second one
        # scans the main index, which holds a private path.
        agent = self.worktree("wt/agent-6", "codex/agent-6")
        self.stage(self.root, "logs live in " + "/Users/" + "someone/Library\n")
        result = self.lint(f"git -C wt/agent-6 {commit} --dry-run -m z; git {commit} -m x",
                           self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("private path", result.stderr)
        subprocess.run(["git", "-C", str(self.root), "reset", "-q"], check=True)
        result = self.lint(f"git {commit} -m x && git -C wt/agent-6 pu" "sh", self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("only main is pushed", result.stderr)
        for command in (f'cd "$SOMEWHERE" && git {commit} -m x', f"GIT_DIR=/tmp/x git {commit} -m x",
                        f"git --work-tree=. {commit} -m x", f"pushd /tmp && git {commit} -m x"):
            with self.subTest(command=command):
                result = self.lint(command, agent)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("cannot tell which checkout", result.stderr)
        result = self.lint(f"git checkout codex/agent-6 && git {commit} -m x", self.root)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("may change the branch", result.stderr)
        result = self.lint(f"git checkout -- notes.md && git {commit} -m x", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.lint("git pu" "sh origin main 2>&1 | tail -5", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pushes_leave_only_the_main_checkout_on_main(self):
        agent = self.worktree("wt/agent-5", "codex/agent-5")
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
                self.assertIn("AGENTS.md: Start here", result.stdout)
                self.assertIn("local-status", result.stdout)
                self.assertIn("Checkpoint", result.stdout)
                self.assertFalse((root / "unexpected-operation").exists())


class ProjectSkillTests(unittest.TestCase):
    def test_skills_use_codex_discovery_and_supported_metadata(self):
        skills = sorted((ROOT / ".agents/skills").glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in skills}, {
            "vocello-ios-validation", "vocello-macos-ui", "vocello-device-diagnostics",
            "vocello-benchmark", "vocello-debug", "vocello-release-readiness",
        })
        for path in skills:
            with self.subTest(skill=path.parent.name):
                metadata = frontmatter(path)
                self.assertEqual(set(metadata), {"name", "description"})
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertTrue(metadata["description"])
                self.assertIn("scripts/", path.read_text(encoding="utf-8"))
                policy = path.parent / "agents/openai.yaml"
                self.assertTrue(policy.is_file())
                self.assertRegex(policy.read_text(encoding="utf-8"), r"allow_implicit_invocation:\s*true")


class SubagentTests(unittest.TestCase):
    def test_project_subagents_are_read_only_and_inherit_the_selected_model(self):
        agents = sorted((ROOT / ".codex/agents").glob("*.toml"))
        self.assertEqual({p.stem for p in agents}, {"vocello-swift-review", "vocello-xcresult-triage"})
        for path in agents:
            with self.subTest(agent=path.stem):
                metadata = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["name"], path.stem)
                self.assertTrue(metadata["description"])
                self.assertEqual(metadata["sandbox_mode"], "read-only")
                self.assertNotIn("model", metadata)
                self.assertNotIn("model_reasoning_effort", metadata)
                self.assertTrue(metadata["developer_instructions"])
        configuration = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(configuration["agents"]["max_concurrent_threads_per_session"], 4)


class RuleTests(unittest.TestCase):
    def test_domain_guidance_is_explicitly_linked_from_agent_instructions(self):
        instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for relative in ("docs/reference/native-engineering.md", "docs/reference/tooling-and-evidence.md"):
            with self.subTest(path=relative):
                self.assertIn(relative, instructions)
                self.assertTrue((ROOT / relative).is_file())
        self.assertTrue((ROOT / "website/AGENTS.md").is_file())

    def test_claude_files_are_not_active_tracked_configuration(self):
        tracked = subprocess.run(["git", "ls-files", "--", ".claude", "CLAUDE.md", "website/CLAUDE.md"],
                                 cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual([name for name in tracked if (ROOT / name).is_file()], [])


if __name__ == "__main__":
    unittest.main()
