"""Exercise shared guards through Codex payloads and checked-in client wiring."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts/hooks"


def invoke(name, tool_input, *, tool_name="apply_patch", cwd=None, root=ROOT):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool_name,
               "tool_input": tool_input, "cwd": str(cwd or root)}
    return subprocess.run(
        [str(HOOKS / name)], input=json.dumps(payload), text=True, capture_output=True,
        cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)), timeout=20,
    )


def patch(*sections):
    return {"command": "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"}


class PatchGuardTests(unittest.TestCase):
    def test_each_edit_operation_protects_generated_files(self):
        for operation in ("Add", "Update", "Delete"):
            for path in ("docs/ROADMAP.md", "QwenVoice.xcodeproj/project.pbxproj",
                         "benchmarks/runs/engine-generation/frozen.json"):
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

    def test_claude_notebook_and_edit_paths_share_the_guard(self):
        for name, field in (("Edit", "file_path"), ("Write", "file_path"),
                            ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")):
            with self.subTest(name=name):
                result = invoke("generated_file_guard.sh", {field: "docs/ROADMAP.md"}, tool_name=name)
                self.assertEqual(result.returncode, 2)

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

    def test_configured_pretool_hooks_block_without_executing_the_tool(self):
        cases = [("Bash", {"command": "git push --force origin main"}),
                 ("apply_patch", patch("*** Delete File: docs/ROADMAP.md"))]
        for name, tool_input in cases:
            payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": name,
                                  "tool_input": tool_input, "cwd": str(ROOT)})
            results = []
            for entry in self.config["hooks"]["PreToolUse"]:
                if re.search(entry["matcher"], name):
                    for hook in entry["hooks"]:
                        results.append(subprocess.run(["bash", "-c", hook["command"]], cwd=ROOT,
                                                      input=payload, capture_output=True, text=True, timeout=20))
            self.assertTrue(any(r.returncode == 2 for r in results), name)

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
