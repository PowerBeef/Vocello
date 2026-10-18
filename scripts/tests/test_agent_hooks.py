"""Exercise repository safeguards through Claude Code payloads and checked-in configuration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/hooks"
SETTINGS = ROOT / ".claude/settings.json"
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
EDIT_MATCHER = "^(Edit|Write|MultiEdit|NotebookEdit)$"


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
    interpreter = "python3" if name.endswith(".py") else "bash"
    return subprocess.run(
        [interpreter, str(hooks / name)], input=json.dumps(payload), text=True, capture_output=True,
        cwd=cwd or root, timeout=20,
        env=dict(os.environ, VOCELLO_PROJECT_ROOT=str(root), CLAUDE_PROJECT_DIR=str(root)),
    )


def edit(path, tool="Edit"):
    return {EDIT_TOOLS[tool]: path}


def matches(matcher: str, tool: str) -> bool:
    """Claude Code matcher semantics: `*`/empty match all, a plain name list is exact, else a regex."""
    if matcher in ("", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_|, -]+", matcher):
        return tool in {part.strip() for part in re.split(r"[|,]", matcher)}
    return re.search(matcher, tool) is not None


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
SIM_SUFFIX = "_" + "sim"
SIM = "Sim" + "ulator"
SDK = "iphone" + SIM.lower()
COMMIT = "git com" "mit"

# The guard corpus (DW-01, audit W-07 and W-10): every command a guard must refuse and every known false
# positive it must let through, run through the real hook entry points.
AGENT_REFUSED = (
    "xcodebuild -scheme QwenVoice build", "xcrun xctest -XCTest A b.xctest", "swift build",
    "swift test --package-path Packages/VocelloQwen3Core", "scripts/dev.sh build",
    "./scripts/dev.sh test --only A", "scripts/dev.sh ios", "scripts/dev.sh check",
    "scripts/macos_test.sh test", "bash scripts/ui_test.sh ios smoke", "scripts/ios_device.sh doctor",
    "./scripts/build.sh cli", "scripts/build_ui_test_bundles.sh macos",
    "xcrun devicectl device process launch x", "python3 scripts/qc.py run --x",
    '"$(python3 scripts/select_python.py)" scripts/qc.py run --x', "build/vocello custom --text hi",
    "build/vocello models install pro_custom", "env QVOICE_LEAD_ONLY=1 scripts/macos_test.sh qc-takes",
    "echo ok && scripts/dev.sh build", "bash -c 'xcodebuild build'",
    "sh <<'EOF'\nscripts/dev.sh build\nEOF\n", "git pu" "sh origin main",
    # Usage text and reporting stay narrow: any other verb or action is still a lane or a build.
    "scripts/ui_test.sh macos smoke", "scripts/ios_device.sh build", "scripts/macos_test.sh models install",
    "scripts/ui_test.sh help; scripts/ui_test.sh ios smoke", "scripts/dev.sh help && scripts/dev.sh build",
    "bash scripts/dev.sh check", "xcodebuild -list build", "xcodebuild -sdk -list",
    "xcodebuild -list -scheme QwenVoice", "xcodebuild -version && xcodebuild -scheme QwenVoice build",
    "xcodebuild -showsdks -destination generic/platform=iOS", "xcrun xcodebuild -scheme QwenVoice build",
    # -list can resolve the project's packages outside the native lock and the owned caches.
    "xcodebuild -list", "xcodebuild -list -project QwenVoice.xcodeproj", "xcodebuild -list -json -workspace W.xcworkspace",
)
AGENT_ALLOWED = (
    "git status --short", "git diff -- scripts/ui_test.sh", "scripts/dev.sh py scripts/tests/test_a.py",
    "scripts/dev.sh lint", "scripts/dev.sh check --dry-run --json", "scripts/dev.sh status",
    "scripts/dev.sh triage build/artifacts/x --json", "scripts/dev.sh regen",
    "./scripts/regenerate_project.sh --fast", "python3 -m pytest scripts/tests/test_x.py -k foo",
    "python3 scripts/qc.py report --run R --json", "build/vocello models list",
    "xcrun xcresulttool get object --path r.xcresult", "xcrun devicectl list devices",
    "cat scripts/macos_test.sh", "grep -n xcodebuild scripts/build.sh", "swift --version",
    "cat > notes.md <<'EOF'\nscripts/dev.sh build\nEOF\n", "npm --prefix website run check",
    # Known false positives: the usage text the skills send agents to, and xcodebuild's reports.
    "scripts/ui_test.sh help", "scripts/ui_test.sh --help", "scripts/ui_test.sh -h", "scripts/macos_test.sh help",
    "./scripts/macos_test.sh --help", "bash scripts/ios_device.sh -h", "scripts/ios_device.sh help 2>&1 | head -40",
    "scripts/dev.sh help", "scripts/dev.sh --help", "bash scripts/dev.sh check --dry-run --json",
    "xcodebuild -version", "/usr/bin/xcodebuild -version", "xcrun xcodebuild -version",
    "xcodebuild -version -sdk iphoneos", "xcodebuild -showsdks", "xcodebuild -showsdks -json",
)
SIMULATOR_REFUSED = (
    # A command substitution runs even inside a commit message or a search pattern.
    'git commit -m "notes $(xcrun simctl boot 1234)"', 'rg "$(xcrun simctl boot 1234)" docs',
    "git commit -m \"notes `xcrun simctl boot 1234`\"",
    f"xcodebuild test -scheme VocelloiOSUI -destination 'platform=iOS {SIM},name=iPhone 17 Pro'",
    "xcrun simctl boot 1234", "xcrun simctl create test-device com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro",
    f"xcodebuild -scheme VocelloiOS -sdk {SDK} build", f"xcodebuild build -destination 'platform=iOS{SIM}'",
    f"swift build --triple arm64-apple-ios26.0-{SIM.lower()}", f"open -a {SIM}", f"open -g -a '{SIM}'",
    "xcrun simctl --set /tmp/devices boot 1234", f"xcodebuild -destination platform=iOS\\ {SIM},name=iPhone\\ 17",
    f"xcodebuild -destination 'platform=visionOS {SIM}'", f"open -na {SIM}",
    f"open /Applications/Xcode.app/Contents/Developer/Applications/{SIM}.app",
    "xcrun simctl bootstatus 1234 -b", "xcrun simctl spawn booted log stream",
    # Every simctl subcommand but maintenance, and real use beside a search or a message.
    *(f"xcrun simctl {sub} booted x" for sub in ("clone", "install", "launch", "openurl", "io", "push", "privacy",
                                                 "ui", "status_bar", "addmedia", "erase", "terminate", "uninstall",
                                                 "get_app_container", "getenv")),
    "xcrun simctl delete 1234", "xcrun simctl shutdown 1234", "xcrun simctl runtime add runtime.dmg",
    "rg -n 'simctl boot' scripts && xcrun simctl boot 1234", f"{COMMIT} -m note && xcodebuild -sdk {SDK} build",
    "git log --grep=x; xcrun simctl create d t", "timeout 60 xcrun simctl boot 1234",
    "bash -lc 'xcrun simctl boot 1234'", "echo `xcrun simctl boot 1234`", "eval 'xcrun simctl boot 1234'",
    "git bisect run xcrun simctl boot 1234", f"npx mcp call build_run{SIM_SUFFIX}",
    f"bash <<'EOF'\nxcodebuild -destination 'platform=iOS {SIM}'\nEOF\n",
)
SIMULATOR_ALLOWED = (
    'git commit -m "notes $(date +%F)"', "rg -n 'xcrun\\(' docs",
    "xcodebuild -scheme VocelloiOS -sdk iphoneos build", "xcrun simctl list\nnpm install",
    "xcrun simctl list devices\necho boot done", "xcrun simctl list devices | grep Booted; echo install done",
    f"gh issue list --search 'ios-{SIM.lower()} crash'", "echo open -a Preview",
    f"cat > notes.txt <<'EOF'\nxcodebuild -destination 'platform=iOS {SIM}'\nEOF\n",
    # Known false positives: search patterns, commit messages and simulator maintenance.
    "rg 'simctl boot' scripts", "rg -n 'xcrun simctl (boot|create)' docs", f"git log --grep={SDK}",
    f"git log --oneline --grep='{SDK}' -- scripts", f'grep -n "platform=iOS {SIM}" docs/reference/x.md',
    f"git grep -n 'platform=iOS {SIM}'", f'{COMMIT} -m "docs: never pass -sdk {SDK} or run xcrun simctl boot"',
    f"{COMMIT} -q -m 'subject' -m 'body: platform=iOS {SIM}'", f"{COMMIT} -F - <<'EOF'\nxcrun simctl boot 1\nEOF\n",
    "xcrun simctl list", "xcrun simctl list devices available -j", "xcrun simctl list runtimes", "xcrun simctl help",
    "xcrun simctl runtime list", "xcrun simctl runtime delete 1A2B3C4D", "xcrun simctl delete unavailable",
    "xcrun simctl shutdown all",
)


def run_all(function, commands):
    """Each command's hook result, in order; the hooks run concurrently to keep the corpus fast."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(zip(commands, pool.map(function, commands)))


class EditGuardTests(unittest.TestCase):
    def test_every_edit_tool_is_refused_on_generated_files(self):
        for tool in EDIT_TOOLS:
            for path in GENERATED:
                with self.subTest(tool=tool, path=path):
                    result = invoke("generated_file_guard.sh", edit(path, tool), tool_name=tool)
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
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "worktree-agent", str(worktree)],
                           check=True)
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
        for path in ("CLAUDE.md", "docs/reference/native-engineering.md", "docs/ordinary file.md",
                     "scripts/tool.py", "benchmarks/README.md"):
            for tool in EDIT_TOOLS:
                with self.subTest(tool=tool, path=path):
                    result = invoke("generated_file_guard.sh", edit(path, tool), tool_name=tool)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_project_root_fallback_works_without_an_environment_override(self):
        with tempfile.TemporaryDirectory(prefix="vocello fallback hooks ") as tmp:
            root = Path(tmp).resolve()
            initialize_repo(root)
            (root / "website").mkdir()
            hooks = fixture_hooks(root)
            environment = dict(os.environ)
            environment.pop("VOCELLO_PROJECT_ROOT", None)
            environment.pop("CLAUDE_PROJECT_DIR", None)
            for path, expected in (("../docs/ROADMAP.md", 2), ("../docs/ordinary file.md", 0)):
                payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                           "tool_input": edit(path, "Write"), "cwd": str(root / "website")}
                result = subprocess.run(["bash", str(hooks / "generated_file_guard.sh")],
                                        input=json.dumps(payload), text=True, capture_output=True,
                                        cwd=root / "website", env=environment, timeout=20)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_uninspectable_input_fails_closed(self):
        for tool_name, tool_input in (("Edit", {}), ("Edit", {"file_path": 5}), ("Edit", {"file_path": ""}),
                                      ("Write", {"file_path": "docs/a\nb.md"}), ("Edit", {"notebook_path": "a.ipynb"}),
                                      ("NotebookEdit", {"file_path": "docs/a.ipynb"}), ("Edit", "not an object")):
            with self.subTest(tool=tool_name, value=tool_input):
                result = invoke("generated_file_guard.sh", tool_input, tool_name=tool_name)
                self.assertEqual(result.returncode, 2, result.stderr)
        # Unknown tools, including the retired Codex patch tool, are not inspectable.
        patch = {"command": "*** Begin Patch\n*** Update File: docs/ordinary.md\n@@\n-a\n+b\n*** End Patch\n"}
        for tool_name, tool_input in (("UnknownTool", edit("docs/ordinary.md")), ("apply_patch", patch)):
            with self.subTest(tool=tool_name):
                result = invoke("generated_file_guard.sh", tool_input, tool_name=tool_name)
                self.assertEqual(result.returncode, 2, result.stderr)
        for payload in ("not json", "[]", '"not an object"', "null"):
            with self.subTest(payload=payload):
                result = subprocess.run(["bash", str(HOOKS / "generated_file_guard.sh")], input=payload, text=True,
                                        capture_output=True, check=False, timeout=20)
                self.assertEqual(result.returncode, 2)

    def test_regeneration_reminder_follows_specification_and_membership_inputs(self):
        for path in ("project.yml", str(ROOT / "project.yml"), "Sources/Fixture.swift", "Tests/New Test.swift"):
            for tool in EDIT_TOOLS:
                with self.subTest(path=path, tool=tool):
                    result = invoke("project_yml_reminder.sh", edit(path, tool), tool_name=tool, event="PostToolUse")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(output["hookEventName"], "PostToolUse")
                    self.assertIn("regenerate_project.sh --fast", output["additionalContext"])
        for path in ("fixtures/project.yml", "website/project.yml", "docs/ok.md"):
            with self.subTest(path=path):
                result = invoke("project_yml_reminder.sh", edit(path), event="PostToolUse")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


class SettingsWiringTests(unittest.TestCase):
    EXPECTED = {
        ("SessionStart", "startup|resume|clear|compact|fork"): {"worker_lifecycle.py", "session_start.sh"},
        ("PreToolUse", "^Bash$"): {"commit_lint.sh", "policy_guard.sh", "agent_guard.py"},
        ("PreToolUse", EDIT_MATCHER): {"generated_file_guard.sh", "agent_guard.py"},
        ("PreToolUse", "^mcp__"): {"simulator_tool_guard.py"},
        ("PostToolUse", EDIT_MATCHER): {"project_yml_reminder.sh"},
        ("SubagentStart", "*"): {"worker_lifecycle.py"},
        ("SubagentStop", "*"): {"worker_lifecycle.py"},
        ("SessionEnd", "*"): {"worker_lifecycle.py"},
    }

    def setUp(self):
        self.settings = json.loads(SETTINGS.read_text(encoding="utf-8"))

    def resolve(self, command: str, cwd: Path) -> tuple[str, Path]:
        # Expand the trusted checked-in command as Claude Code would, without
        # running the hook itself. Each configured command is interpreter+path.
        result = subprocess.run(["bash", "-c", 'printf "%s\\n" ' + command], cwd=cwd,
                                env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)),
                                capture_output=True, text=True, check=True)
        interpreter, path = result.stdout.splitlines()
        return interpreter, Path(path)

    def test_the_hook_matrix_is_exact_and_commands_do_not_depend_on_the_working_directory(self):
        matrix = {}
        with tempfile.TemporaryDirectory() as outside:
            for event, entries in self.settings["hooks"].items():
                for entry in entries:
                    matcher = entry.get("matcher", "")
                    if matcher != "*":
                        re.compile(matcher)
                    for hook in entry["hooks"]:
                        self.assertEqual(hook["type"], "command")
                        self.assertLessEqual(hook.get("timeout", 600), 5 if event == "SessionEnd" else 15)
                        for cwd in (ROOT, ROOT / "website", Path(outside)):
                            interpreter, path = self.resolve(hook["command"], cwd)
                            self.assertEqual(hook["command"],
                                             f'{interpreter} "$CLAUDE_PROJECT_DIR/scripts/hooks/{path.name}"')
                            self.assertEqual(interpreter, "python3" if path.suffix == ".py" else "bash")
                            self.assertEqual(path.parent, HOOKS)
                            self.assertTrue(path.is_file())
                        matrix.setdefault((event, matcher), set()).add(path.name)
        self.assertEqual(matrix, self.EXPECTED)
        wired = set().union(*matrix.values())
        self.assertEqual({p.name for p in HOOKS.glob("*.sh")}, {name for name in wired if name.endswith(".sh")})

    def test_python_hooks_run_under_the_host_default_interpreter(self):
        # Hook commands run bare `python3`, which on macOS is often the system 3.9: a hook that
        # needs a newer interpreter fails at import and silently registers nothing.
        interpreters = {sys.executable}
        system = shutil.which("python3", path="/usr/bin:/bin")
        if system:
            interpreters.add(system)
        cases = [("worker_lifecycle.py", {"hook_event_name": event, "session_id": "fixture", "agent_id": "a"}, 0)
                 for event in ("SessionStart", "SubagentStart", "SubagentStop", "SessionEnd")]
        cases += [("simulator_tool_guard.py", {"tool_name": "mcp__x__list_schemes"}, 0),
                  ("simulator_tool_guard.py", {"tool_name": "mcp__x__boot" + SIM_SUFFIX}, 2),
                  ("agent_guard.py", {"tool_name": "Bash", "agent_id": "a", "cwd": str(ROOT),
                                      "tool_input": {"command": "scripts/dev.sh build"}}, 2),
                  ("agent_guard.py", {"tool_name": "Bash", "agent_id": "a", "cwd": str(ROOT),
                                      "tool_input": {"command": "git status"}}, 0),
                  ("agent_guard.py", {"tool_name": "Bash", "agent_id": "a", "cwd": str(ROOT),
                                      "tool_input": {"command": "scripts/ui_test.sh help && xcodebuild -version"}}, 0)]
        for interpreter in sorted(interpreters):
            for name, payload, expected in cases:
                with self.subTest(interpreter=interpreter, hook=name, payload=payload), \
                        tempfile.TemporaryDirectory() as workers:
                    result = subprocess.run(
                        [interpreter, str(HOOKS / name)], input=json.dumps(payload), text=True,
                        capture_output=True, timeout=20,
                        env=dict(os.environ, QVOICE_WORKER_DIRECTORY=workers,
                                 CLAUDE_ENV_FILE=str(Path(workers) / "env")))
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    if name == "worker_lifecycle.py":
                        json.loads(result.stdout)
            for mode, command, expected in (("git-policy", "git status", ""),
                                            ("simulator-policy", "rg 'simctl boot' && xcrun simctl list", ""),
                                            ("simulator-policy", "xcrun simctl boot 1234", "`simctl boot`\n")):
                with self.subTest(interpreter=interpreter, hook="agent_hook_input.py", mode=mode, command=command):
                    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}
                    result = subprocess.run([interpreter, str(HOOKS / "agent_hook_input.py"), mode],
                                            input=json.dumps(payload), text=True, capture_output=True, timeout=20)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ""))

    def test_matchers_select_only_the_intended_tool_family(self):
        simulator_tool = "mcp__MobileBuildMCP__build" + SIM_SUFFIX
        for event in ("PreToolUse", "PostToolUse"):
            for entry in self.settings["hooks"][event]:
                matcher = entry["matcher"]
                for tool in (*EDIT_TOOLS, "Bash", "Read", "NotebookRead", "TodoWrite", "WebFetch",
                             "mcp__x__Write", simulator_tool):
                    with self.subTest(matcher=matcher, tool=tool):
                        expected = ((matcher == EDIT_MATCHER and tool in EDIT_TOOLS)
                                    or (matcher == "^Bash$" and tool == "Bash")
                                    or (matcher == "^mcp__" and tool.startswith("mcp__")))
                        self.assertEqual(matches(matcher, tool), expected)

    def test_configured_pretool_hooks_allow_and_block_from_root_and_website(self):
        for cwd in (ROOT, ROOT / "website"):
            prefix = "../" if cwd.name == "website" else ""
            cases = [("Bash", {"command": "git push --force origin main"}, True),
                     ("Bash", {"command": "git push origin worktree-agent-1"}, True),
                     ("Bash", {"command": "git status --short"}, False),
                     ("Edit", edit(f"{prefix}docs/ROADMAP.md"), True),
                     ("NotebookEdit", edit(f"{prefix}benchmarks/runs/x.ipynb", "NotebookEdit"), True),
                     ("Write", edit(f"{prefix}docs/note.md", "Write"), False),
                     ("mcp__MobileBuildMCP__build" + SIM_SUFFIX, {}, True),
                     ("mcp__MobileBuildMCP__list_schemes", {}, False)]
            for name, tool_input, blocked in cases:
                with self.subTest(cwd=cwd, tool=name, blocked=blocked):
                    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name,
                                          "tool_input": tool_input, "cwd": str(cwd)})
                    results = []
                    for entry in self.settings["hooks"]["PreToolUse"]:
                        if matches(entry["matcher"], name):
                            for hook in entry["hooks"]:
                                results.append(subprocess.run(
                                    ["bash", "-c", hook["command"]], cwd=cwd, input=payload,
                                    env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT)),
                                    capture_output=True, text=True, timeout=20))
                    self.assertTrue(results)
                    self.assertEqual(any(r.returncode == 2 for r in results), blocked)
                    self.assertTrue(all(r.returncode in (0, 2) for r in results))


class AgentGuardTests(unittest.TestCase):
    """Only subagent hook input carries agent_id; the lead's calls pass through untouched."""

    def guard(self, tool_input, *, tool_name="Bash", agent=True, cwd=ROOT, root=ROOT):
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input,
                   "cwd": str(cwd), **({"agent_id": "agent-1", "agent_type": "general-purpose"} if agent else {})}
        hooks = fixture_hooks(root)
        return subprocess.run(["python3", str(hooks / "agent_guard.py")], input=json.dumps(payload), text=True,
                              capture_output=True, timeout=20, cwd=cwd,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))

    def test_agents_cannot_run_native_device_model_or_measured_work(self):
        agent = run_all(lambda command: self.guard({"command": command}), AGENT_REFUSED)
        lead = dict(run_all(lambda command: self.guard({"command": command}, agent=False), AGENT_REFUSED))
        for command, result in agent:
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("agent guard: BLOCKED", result.stderr)
                self.assertEqual(lead[command].returncode, 0)

    def test_agents_keep_research_checks_usage_text_and_xcodebuild_reports(self):
        for command, result in run_all(lambda command: self.guard({"command": command}), AGENT_ALLOWED):
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_agents_commit_only_in_their_own_worktree(self):
        with tempfile.TemporaryDirectory(prefix="vocello agent commits ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            worktree = root / ".claude/worktrees/agent-1"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "worktree-agent-1", str(worktree)],
                           check=True)
            commit = "git com" "mit -m x"
            blocked = self.guard({"command": commit}, cwd=root, root=root)
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("own worktree", blocked.stderr)
            self.assertEqual(self.guard({"command": f"git -C '{root}' com" "mit -m x"}, cwd=worktree, root=root).returncode, 2)
            self.assertEqual(self.guard({"command": commit}, cwd=worktree, root=root).returncode, 0)
            self.assertEqual(self.guard({"command": commit}, cwd=root, root=root, agent=False).returncode, 0)

    def test_agents_never_edit_the_roadmap_or_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="vocello agent edits ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            worktree = root / ".claude/worktrees/agent-1"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "worktree-agent-1", str(worktree)],
                           check=True)
            for tool in EDIT_TOOLS:
                for path, cwd in (("config/roadmap.json", root), ("docs/development-progress.md", root),
                                  ("config/roadmap.json", worktree), (str(worktree / "docs/development-progress.md"), root)):
                    with self.subTest(tool=tool, path=path, cwd=cwd.name):
                        result = self.guard(edit(path, tool), tool_name=tool, cwd=cwd, root=root)
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertEqual(self.guard(edit(path, tool), tool_name=tool, cwd=cwd, root=root,
                                                    agent=False).returncode, 0)
                with self.subTest(tool=tool, path="ordinary"):
                    self.assertEqual(self.guard(edit("Sources/A.swift", tool), tool_name=tool, cwd=worktree,
                                                root=root).returncode, 0)


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        self.allow, self.ask, self.deny = (self.settings["permissions"][kind] for kind in ("allow", "ask", "deny"))

    def test_pushes_always_ask_and_only_fast_forward_main_can_be_pushed(self):
        self.assertEqual([rule for rule in self.allow if rule.startswith("Bash(git push")], [])
        for rule in ("Bash(git push)", "Bash(git push *)"):
            self.assertIn(rule, self.ask)
        for rule in ("Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push --tags*)",
                     "Bash(git push origin HEAD*)", "Bash(git push origin worktree-*)", "Bash(git push -u*)",
                     "Bash(git checkout -b*)", "Bash(git switch -c*)", "Bash(git worktree add*)",
                     "Bash(git update-ref*)", "Bash(git add -A*)", "Bash(git add .)",
                     "Bash(git commit -a*)"):
            self.assertIn(rule, self.deny)

    def test_stash_mutations_are_denied_but_its_reads_are_not(self):
        def denied(command: str) -> bool:
            return any(rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[len("Bash("):-1])
                       for rule in self.deny)

        for command in ("git stash", "git stash -u", "git stash --include-untracked", "git stash -m wip",
                        "git stash -- scripts/x.py", "git stash push -u -m tag", "git stash save wip",
                        "git stash pop", "git stash apply abc1234", "git stash drop stash@{0}", "git stash clear",
                        "git stash create", "git stash store abc1234", "git stash branch topic"):
            with self.subTest(mutation=command):
                self.assertTrue(denied(command))
        for command in ("git stash list", "git stash list --format=%H", "git stash show", "git stash show -p"):
            with self.subTest(read=command):
                self.assertFalse(denied(command))

    def test_releases_generated_project_and_authorization_bound_actions(self):
        for rule in ("Edit(/QwenVoice.xcodeproj/**)", "Bash(scripts/release.sh*)", "Bash(gh release create*)",
                     "Bash(gh release upload*)", "Bash(rm -rf build/cache*)"):
            self.assertIn(rule, self.deny)
        for rule in ("Bash(scripts/macos_test.sh models install*)", "Bash(scripts/macos_test.sh models ensure*)",
                     "Bash(scripts/ui_test.sh * model-download*)", "Bash(scripts/clean_build_caches.sh*)",
                     "Bash(scripts/install_pinned_tools.sh*)", "Bash(python3 scripts/publish_benchmark_history.py*)",
                     "Bash(gh workflow run*)", "Bash(git branch -D*)", "Bash(git worktree remove --force*)",
                     "Bash(git reset --hard*)", "Bash(hf download*)"):
            self.assertIn(rule, self.ask)

    def test_hugging_face_cli_and_mcp_reads_are_allowed_while_writes_ask_and_the_token_stays_hidden(self):
        def matches(command: str, rules: list[str], tool: str = "Bash") -> bool:
            if tool != "Bash":
                return any(fnmatch.fnmatchcase(command, rule) for rule in rules)
            return any(rule.startswith("Bash(") and fnmatch.fnmatchcase(command, rule[len("Bash("):-1])
                       for rule in rules)

        reads = ("hf version", "hf auth whoami", "hf models info Qwen/Qwen3-ForcedAligner-0.6B",
                 "hf models card nvidia/parakeet-tdt-0.6b-v3", "hf datasets info owner/corpus",
                 "hf papers read 2609.16989", "hf cache ls", "hf cache verify owner/model")
        writes = ("hf download owner/model", "hf upload owner/model .", "hf repos create owner/model",
                  "hf repos delete owner/model", "hf cp ./a hf://owner/model/a", "hf sync ./a hf://buckets/o/b",
                  "hf jobs run python:3.12 python -c 1", "hf endpoints deploy x", "hf spaces restart owner/space",
                  "hf collections create Vocello", "hf discussions comment owner/model 1", "hf auth login",
                  "hf cache rm model/owner/model", "hf skills add owner/skill", "hf update")
        for command in reads:
            with self.subTest(read=command):
                self.assertTrue(matches(command, self.allow))
                self.assertFalse(matches(command, self.ask) or matches(command, self.deny))
        for command in writes:
            with self.subTest(write=command):
                self.assertTrue(matches(command, self.ask))
                self.assertFalse(matches(command, self.allow))
        self.assertTrue(matches("hf auth token", self.deny))
        server = "mcp__hf-mcp-server__"
        for tool in ("hf_fs", "hub_repo_search", "hub_repo_details", "hf_whoami"):
            self.assertIn(server + tool, self.allow)
            self.assertFalse(matches(server + tool, self.ask, tool="mcp"))
        for tool in ("dynamic_space", "gr1_z_image_turbo_generate"):
            self.assertTrue(matches(server + tool, self.ask, tool="mcp"), tool)

    def test_unsupported_destination_and_ui_driving_tools_are_denied_but_device_tools_are_not(self):
        server = "mcp__MobileBuildMCP__"
        denied = [server + name for name in (f"boot{SIM_SUFFIX}", f"build{SIM_SUFFIX}", f"build_run{SIM_SUFFIX}",
                                             f"test{SIM_SUFFIX}", f"list{SIM_SUFFIX}s", f"record{SIM_SUFFIX}_video",
                                             f"get{SIM_SUFFIX}_app_path", f"install_app{SIM_SUFFIX}",
                                             f"launch_app{SIM_SUFFIX}", f"open{SIM_SUFFIX}", f"stop_app{SIM_SUFFIX}",
                                             "screenshot", "snapshot_ui", "clean", "tap")]
        denied.append(f"mcp__XcodeBuildMCP__debug_attach{SIM_SUFFIX}")
        retained = [server + name for name in ("list_schemes", "discover_projs", "show_build_settings",
                                               "get_coverage_report", "session_show_defaults")]
        retained += ["mcp__XcodeBuildMCP__build_device", "mcp__XcodeBuildMCP__test_macos",
                     "mcp__claude-in-chrome__computer", "mcp__sosumi__searchAppleDocumentation",
                     "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_screenshot"]
        patterns = [rule for rule in self.deny if rule.startswith("mcp__")]
        for name in denied:
            with self.subTest(denied=name):
                self.assertTrue(any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns))
        for name in retained:
            with self.subTest(retained=name):
                self.assertFalse(any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns))
        for rule in (*self.allow, *self.ask):
            self.assertIsNone(re.search(r"_sims?($|_)", rule), rule)
        for agent in ("simulator-tester", "test-runner", "test-debugger"):
            self.assertIn(f"Agent(axiom:{agent})", self.deny)

    def test_worktrees_follow_local_head_and_allowed_scripts_exist(self):
        self.assertEqual(self.settings["worktree"], {"baseRef": "head"})
        self.assertNotIn("EnterWorktree", self.deny)
        self.assertFalse([rule for rule in self.deny if rule.startswith(("Agent(Explore", "Agent(general"))])
        for rule in ("Bash(git worktree remove .claude/worktrees/*)", "Bash(git merge --ff-only worktree-*)",
                     "Bash(git branch -d worktree-*)", "Bash(git cherry-pick *)"):
            self.assertIn(rule, self.allow)
        for rule in self.allow:
            words = rule[len("Bash("):-1].split() if rule.startswith("Bash(") else []
            if words[:1] == ["python3"] and len(words) > 1:
                words = words[1:]
            if words and words[0].removeprefix("./").startswith("scripts/"):
                with self.subTest(rule=rule):
                    self.assertTrue(list(ROOT.glob(words[0].removeprefix("./"))), rule)


class SimulatorToolGuardTests(unittest.TestCase):
    def test_physical_device_only_mcp_routes_preserve_device_discovery(self):
        for tool in ("mcp__xcodebuildmcp__build" + SIM_SUFFIX, "mcp__XcodeBuildMCP__boot" + SIM_SUFFIX,
                     "mcp__xcodebuildmcp__debug_attach" + SIM_SUFFIX, "mcp__xcodebuildmcp__simctl",
                     "mcp__MobileBuildMCP__list" + SIM_SUFFIX + "s",
                     "mcp__MobileBuildMCP__record" + SIM_SUFFIX + "_video",
                     "mcp__MobileBuildMCP__get" + SIM_SUFFIX + "_app_path"):
            with self.subTest(tool=tool):
                result = invoke("simulator_tool_guard.py", {}, tool_name=tool)
                self.assertEqual(result.returncode, 2, result.stderr)
        for tool in ("mcp__xcodebuildmcp__list_devices", "mcp__xcodebuildmcp__build_device",
                     "mcp__sosumi__search", "mcp__xcodebuildmcp__build_macos",
                     "mcp__MobileBuildMCP__list_schemes", "mcp__github__find_similar_issues"):
            with self.subTest(tool=tool):
                result = invoke("simulator_tool_guard.py", {}, tool_name=tool)
                self.assertEqual(result.returncode, 0, result.stderr)

class PolicyGuardTests(unittest.TestCase):
    def guard(self, command: str):
        return invoke("policy_guard.sh", {"command": command}, tool_name="Bash")

    def test_linked_worktree_cache_paths_resolve_against_the_actual_checkout(self):
        with tempfile.TemporaryDirectory(prefix="vocello cache hooks ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            agent = root.parent / "agent workspace"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "worktree-cache", str(agent)], check=True)
            for command in ("rm -rf build/cache", "rm -rf build", f'rm -rf "{agent}/build/cache"'):
                with self.subTest(command=command):
                    result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root, cwd=agent)
                    self.assertEqual(result.returncode, 2, result.stderr)
            result = invoke("policy_guard.sh", {"command": f'rm -rf "{agent}/build/cache"'},
                            tool_name="Bash", root=root, cwd=root)
            self.assertEqual(result.returncode, 2, result.stderr)
            result = invoke("policy_guard.sh", {"command": "rm -rf build/scratch/probe"},
                            tool_name="Bash", root=root, cwd=agent)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_branch_creation_is_refused_in_every_checkout(self):
        # Agent worktrees and their branches come from Claude Code itself, never a shell command.
        with tempfile.TemporaryDirectory(prefix="vocello branch hooks ") as tmp:
            root = Path(tmp).resolve() / "main checkout"
            initialize_repo(root)
            agent = root.parent / "detached agent"
            subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(agent), "HEAD"], check=True)
            for command in ("git switch -c codex/scoped", "git switch -c worktree-x", "git switch -c worktree-x HEAD",
                            "git switch -c topic", "git switch -C worktree-x", "git checkout -b worktree-x",
                            "git worktree add ../another", "git branch worktree-x"):
                for cwd in (agent, root):
                    with self.subTest(command=command, cwd=cwd.name):
                        result = invoke("policy_guard.sh", {"command": command}, tool_name="Bash", root=root, cwd=cwd)
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

    def test_unsupported_destinations_are_blocked_in_every_spelling(self):
        for command, result in run_all(self.guard, SIMULATOR_REFUSED):
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Physical iPhone only", result.stderr)

    def test_searches_messages_prose_and_maintenance_are_not_destinations(self):
        # Each simple command is judged on its own words: a pattern never reaches across a line or a
        # separator, and a search pattern, a commit message or a heredoc body is text, not use.
        for command, result in run_all(self.guard, SIMULATOR_ALLOWED):
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 0, result.stderr)

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
        for command in (f'rm -rf "{root}/build"', 'rm -rf "$VOCELLO_PROJECT_ROOT/build"',
                        'rm -rf "$CLAUDE_PROJECT_DIR/build"', 'rm -rf "${CLAUDE_PROJECT_DIR}/build/cache"',
                        "rm -rf ../Vocello/build"
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
        for command in ("git push origin worktree-agent-1", "git push origin HEAD", "git push origin HEAD:main",
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
        agent = self.worktree(".claude/worktrees/agent-1", "worktree-agent-1")
        self.stage(agent)
        result = self.lint(self.commit, agent)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.lint("git -C .claude/worktrees/agent-1 com" "mit -m x", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_retired_codex_branches_cannot_commit_in_a_linked_worktree(self):
        legacy = self.worktree(".claude/worktrees/legacy", "codex/legacy")
        self.stage(legacy)
        result = self.lint(self.commit, legacy)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("worktree-* branch", result.stderr)

    def test_wrong_branch_and_unrelated_repository_worktrees_are_blocked(self):
        checkout = self.worktree("wt/wrong-branch", "topic")
        result = self.lint(self.commit, checkout)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("worktree-* branch", result.stderr)
        unrelated = self.root.parent / "unrelated repository"
        initialize_repo(unrelated)
        foreign = unrelated.parent / "foreign agent"
        subprocess.run(["git", "-C", str(unrelated), "worktree", "add", "-q", "-b", "worktree-foreign", str(foreign)], check=True)
        result = self.lint(self.commit, foreign)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("another repository", result.stderr)
        subprocess.run(["git", "-C", str(self.root), "switch", "-q", "-c", "worktree-wrong-main"], check=True)
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
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "-q", "-b", "worktree-spaced", str(spaced)],
                       check=True)
        commit = "com" "mit"
        result = self.lint(f'git -C "{spaced}" {commit} -m x', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
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
            # The hook runs under the macOS system bash 3.2 as well as a newer bash on PATH.
            shells = [[], ["/bin/bash"]] if Path("/bin/bash").exists() else [[]]
            for cwd in (root, root / "website"):
                for shell in shells:
                    with self.subTest(cwd=cwd.name, shell=shell):
                        result = subprocess.run([*shell, str(hooks / "session_start.sh")], cwd=cwd,
                                                env=dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}"),
                                                capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("CLAUDE.md: Start here", result.stdout)
                        self.assertIn("local-status", result.stdout)
                        self.assertIn("Checkpoint", result.stdout)
                        self.assertIn("cache health: ", result.stdout)
                        self.assertFalse((root / "unexpected-operation").exists())

    def session(self, root: Path, progress: str, *, available_kb: int = 400 * 1024 * 1024) -> str:
        """The hook's output in a fixture checkout whose volume reports `available_kb` free."""
        hooks = fixture_hooks(root)
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs/development-progress.md").write_text(progress, encoding="utf-8")
        if not (root / ".git").exists():
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        fake_bin = root / "bin"
        fake_bin.mkdir(exist_ok=True)
        df = fake_bin / "df"
        df.write_text("#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
                      f"echo 'map volume 900000000 1 {available_kb} 99% /Volumes/Fixture Disk'\n")
        df.chmod(0o755)
        shell = "/bin/bash" if Path("/bin/bash").exists() else "bash"   # macOS: the system bash 3.2
        result = subprocess.run([shell, str(hooks / "session_start.sh")],
                                cwd=root, env=dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}"),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_first_checkpoint_prints_whole_and_stops_at_the_next(self):
        progress = ("# Checkpoint\n\n## Resume now\n\n### Newest\n\nIntro.\n\n- **One:** first\n  continued\n"
                    "- **Two:** `scripts/ui_test.sh ios smoke`\n\n### Older\n\nOLDER-MARKER\n")
        with tempfile.TemporaryDirectory() as temp:
            output = self.session(Path(temp), progress)
        checkpoint = output.split("-- docs/development-progress.md: Resume now --\n", 1)[1]
        self.assertEqual(checkpoint, "### Newest\n\nIntro.\n\n- **One:** first\n  continued\n"
                                     "- **Two:** `scripts/ui_test.sh ios smoke`\n")

    def test_a_long_checkpoint_is_cut_at_a_bullet_near_four_kilobytes_with_a_pointer(self):
        bullets = "".join(f"- **Item {n}:** {'word ' * 14}\n  {'more ' * 16}\n  last line of item {n}\n"
                          for n in range(60))
        progress = f"## Resume now\n\n### Newest\n\nIntro.\n\n{bullets}\n### Older\n\nOLDER-MARKER\n"
        with tempfile.TemporaryDirectory() as temp:
            output = self.session(Path(temp), progress)
        checkpoint = output.split("-- docs/development-progress.md: Resume now --\n", 1)[1]
        *kept, pointer = checkpoint.splitlines()
        self.assertLessEqual(len(checkpoint.encode()), 4096)
        self.assertGreater(len(checkpoint.encode()), 3000)
        self.assertIn("docs/development-progress.md", pointer)
        self.assertNotIn("OLDER-MARKER", output)
        source = progress.splitlines()[2:]
        self.assertEqual(kept, source[:len(kept)])
        self.assertTrue(source[len(kept)].startswith("- **Item"), source[len(kept)])

    def test_cache_health_reports_dangling_public_links_and_low_free_space(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            (root / "config/build-output-policy.json").write_text(json.dumps({
                "entries": [{"path": "build/not-a-link"}],
                "publicLinks": [{"path": "build/fixture-cli", "targetSuffix": "x"},
                                {"path": "build/Fixture.app", "alternateTargetEntries": ["y"]}],
                "migrations": [{"path": "build/never-read"}]}, indent=2))
            (root / "build").mkdir()
            (root / "build/fixture-cli").symlink_to("cache/xcode/gone/vocello")
            (root / "build/never-read").symlink_to("cache/gone")
            (root / "build/cache").mkdir()
            (root / "build/Fixture.app").symlink_to("cache")
            output = self.session(root, "## Resume now\n### Current\nCheckpoint\n", available_kb=10 * 1024 * 1024)
            health = [line for line in output.splitlines() if line.startswith("cache health: ")]
            self.assertEqual(len(health), 1, output)
            self.assertIn("WARN build/fixture-cli dangles", health[0])
            self.assertIn("10 GiB free on the repository volume, below the 40 GiB floor", health[0])
            self.assertNotIn("Fixture.app", health[0])
            self.assertNotIn("never-read", health[0])
            (root / "build/fixture-cli").unlink()
            output = self.session(root, "## Resume now\n### Current\nCheckpoint\n")
            self.assertIn("cache health: ok (400 GiB free; no public build link dangles)", output)


class ProjectSkillTests(unittest.TestCase):
    SKILLS = {"vocello-ios-validation", "vocello-macos-ui", "vocello-device-diagnostics",
              "vocello-benchmark", "vocello-debug", "vocello-release-readiness"}

    def test_skills_use_claude_discovery_and_supported_metadata(self):
        skills = sorted((ROOT / ".claude/skills").glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in skills}, self.SKILLS)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                metadata = frontmatter(path)
                self.assertTrue({"name", "description", "argument-hint"} <= set(metadata))
                self.assertTrue(set(metadata) <= {"name", "description", "argument-hint", "disable-model-invocation"})
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertTrue(metadata["description"])
                self.assertTrue(metadata["argument-hint"].strip('"'))
                # Local validation is authorized, so no skill is hidden from the model.
                self.assertIn(metadata.get("disable-model-invocation", "false"), ("false",))
                body = path.read_text(encoding="utf-8")
                self.assertIn("$ARGUMENTS", body)
                self.assertIn("scripts/", body)
                self.assertEqual([p.name for p in path.parent.iterdir()], ["SKILL.md"])


class SubagentTests(unittest.TestCase):
    WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Agent", "Task"}

    def test_project_subagents_are_read_only_and_inherit_the_selected_model(self):
        agents = sorted((ROOT / ".claude/agents").glob("*.md"))
        self.assertEqual({p.stem for p in agents}, {"vocello-swift-review", "vocello-xcresult-triage"})
        for path in agents:
            with self.subTest(agent=path.stem):
                metadata = frontmatter(path)
                self.assertEqual(metadata["name"], path.stem)
                self.assertTrue(metadata["description"])
                self.assertEqual(metadata["model"], "inherit")
                tools = {tool.strip() for tool in metadata["tools"].split(",")}
                self.assertFalse(tools & self.WRITE_TOOLS)
                self.assertTrue({"Read", "Grep", "Glob"} <= tools)
                for key in ("isolation", "permissionMode", "memory", "hooks", "mcpServers"):
                    self.assertNotIn(key, metadata)
                if path.stem == "vocello-swift-review":
                    self.assertNotIn("Bash", tools)


class RuleTests(unittest.TestCase):
    RULES = {"native.md": "docs/reference/native-engineering.md",
             "tooling.md": "docs/reference/tooling-and-evidence.md"}

    def test_domain_guidance_is_linked_and_path_scoped(self):
        instructions = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(instructions.startswith("# CLAUDE.md\n"))
        tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                                     check=True).stdout.splitlines())
        for rule, relative in self.RULES.items():
            with self.subTest(rule=rule):
                self.assertIn(relative, instructions)
                link = ROOT / ".claude/rules" / rule
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (ROOT / relative).resolve())
                patterns = [line.strip()[2:].strip().strip('"')
                            for line in frontmatter(ROOT / relative)["paths"].splitlines() if line.strip()]
                self.assertTrue(patterns)
                for pattern in patterns:
                    with self.subTest(pattern=pattern):
                        self.assertTrue(any(fnmatch.fnmatch(name, pattern) for name in tracked), pattern)
        self.assertEqual({p.name for p in (ROOT / ".claude/rules").iterdir()}, set(self.RULES))
        website = (ROOT / "website/CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("../CLAUDE.md", website)

    def test_retired_codex_harness_is_not_tracked(self):
        tracked = subprocess.run(["git", "ls-files", "--", ".codex", ".agents", "AGENTS.md", "website/AGENTS.md"],
                                 cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual([name for name in tracked if (ROOT / name).exists()], [])


if __name__ == "__main__":
    unittest.main()
