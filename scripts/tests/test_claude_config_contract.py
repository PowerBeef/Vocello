#!/usr/bin/env python3
"""Tests for scripts/claude_config_contract.py against synthetic .claude trees."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import claude_config_contract as contract  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GATE = '"$CLAUDE_PROJECT_DIR"/scripts/hooks/precommit_gate.sh'


def settings(deny=None, hooks=None) -> dict:
    return {
        "hooks": hooks if hooks is not None else {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": GATE, "timeout": 30}]}
            ]
        },
        "permissions": {
            "deny": deny if deny is not None else [
                "Bash(xcrun simctl boot*)",
                "Edit(QwenVoice.xcodeproj/project.pbxproj)",
                "Bash(git push --force*)",
                "Bash(rm -rf build/cache*)",
            ]
        },
    }


class Harness(unittest.TestCase):
    def build(self, cfg=None, skill=None, agent=None, rule_paths=("Sources/**",)) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "Sources").mkdir()
        (root / "Sources" / "A.swift").write_text("// swift\n")
        hooks = root / "scripts" / "hooks"
        hooks.mkdir(parents=True)
        gate = hooks / "precommit_gate.sh"
        gate.write_text("#!/usr/bin/env bash\nexit 0\n")
        gate.chmod(gate.stat().st_mode | stat.S_IXUSR)
        claude = root / ".claude"
        (claude / "rules").mkdir(parents=True)
        (claude / "settings.json").write_text(json.dumps(cfg or settings()))
        paths = "".join(f"  - \"{p}\"\n" for p in rule_paths)
        (claude / "rules" / "ios.md").write_text(
            f"---\nstatus: active\nowner: ios\nsummary: rule\nsourceOfTruth:\n  - Sources/A.swift\npaths:\n{paths}---\n# rule\n"
        )
        if skill is not None:
            name, text = skill
            (claude / "skills" / name).mkdir(parents=True)
            (claude / "skills" / name / "SKILL.md").write_text(text)
        if agent is not None:
            name, text = agent
            (claude / "agents").mkdir(exist_ok=True)
            (claude / "agents" / f"{name}.md").write_text(text)
        return root


class SettingsTests(Harness):
    def test_valid_tree_passes(self):
        report = contract.validate(self.build())
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["ok"])

    def test_missing_commit_gate_wiring_fails(self):
        cfg = settings(hooks={"PreToolUse": []})
        errors = contract.validate(self.build(cfg))["errors"]
        self.assertTrue(any("precommit_gate.sh must be wired" in e for e in errors))

    def test_hook_pointing_at_missing_script_fails(self):
        cfg = settings()
        cfg["hooks"]["PostToolUse"] = [
            {"matcher": "Edit", "hooks": [{"type": "command",
              "command": '"$CLAUDE_PROJECT_DIR"/scripts/hooks/nope.sh'}]}
        ]
        errors = contract.validate(self.build(cfg))["errors"]
        self.assertTrue(any("missing scripts/hooks/nope.sh" in e for e in errors))

    def test_hook_command_outside_scripts_hooks_fails(self):
        cfg = settings()
        cfg["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "rm -rf build"})
        errors = contract.validate(self.build(cfg))["errors"]
        self.assertTrue(any("must be" in e and "scripts/hooks" in e for e in errors))

    def test_pre_tool_use_timeout_above_budget_fails(self):
        cfg = settings()
        cfg["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 600
        errors = contract.validate(self.build(cfg))["errors"]
        self.assertTrue(any("exceeds 30s" in e for e in errors))

    def test_each_required_deny_fragment_is_enforced(self):
        for dropped in ("simctl boot", "project.pbxproj", "git push --force", "rm -rf build/cache"):
            with self.subTest(dropped=dropped):
                deny = [d for d in settings()["permissions"]["deny"] if dropped not in d]
                errors = contract.validate(self.build(settings(deny=deny)))["errors"]
                self.assertTrue(any(repr(dropped) in e for e in errors), errors)

    def test_invalid_json_is_reported(self):
        root = self.build()
        (root / ".claude" / "settings.json").write_text("{not json")
        errors = contract.validate(root)["errors"]
        self.assertTrue(any("invalid JSON" in e for e in errors))


class SkillTests(Harness):
    def test_device_lane_skill_must_be_user_invoked_only(self):
        body = "---\nname: ios-lane\ndescription: run\n---\nRun scripts/ui_test.sh ios smoke\n"
        errors = contract.validate(self.build(skill=("ios-lane", body)))["errors"]
        self.assertTrue(any("disable-model-invocation" in e for e in errors))
        body = body.replace("description: run\n", "description: run\ndisable-model-invocation: true\n")
        self.assertEqual(contract.validate(self.build(skill=("ios-lane", body)))["errors"], [])

    def test_skill_name_must_match_directory(self):
        body = "---\nname: other\ndescription: d\n---\nbody\n"
        errors = contract.validate(self.build(skill=("checkpoint", body)))["errors"]
        self.assertTrue(any("name must equal the directory" in e for e in errors))

    def test_skill_without_description_fails(self):
        body = "---\nname: checkpoint\n---\nbody\n"
        errors = contract.validate(self.build(skill=("checkpoint", body)))["errors"]
        self.assertTrue(any("description is required" in e for e in errors))


class AgentAndRuleTests(Harness):
    def test_agent_requires_explicit_tools_and_no_worktree(self):
        text = "---\nname: gate-runner\ndescription: d\n---\nbody\n"
        errors = contract.validate(self.build(agent=("gate-runner", text)))["errors"]
        self.assertTrue(any("tools must be an explicit allowlist" in e for e in errors))
        text = "---\nname: gate-runner\ndescription: d\ntools: Read, Grep\nisolation: worktree\n---\nbody\n"
        errors = contract.validate(self.build(agent=("gate-runner", text)))["errors"]
        self.assertTrue(any("worktree isolation is off-policy" in e for e in errors))

    def test_rule_paths_must_match_a_file(self):
        errors = contract.validate(self.build(rule_paths=("Nowhere/**",)))["errors"]
        self.assertTrue(any("matches no file" in e for e in errors))

    def test_unsupported_destination_strings_are_rejected(self):
        forbidden = "platform=iOS " + "Sim" + "ulator"
        text = f"---\nname: gate-runner\ndescription: d\ntools: Bash\n---\nxcodebuild -destination '{forbidden}'\n"
        errors = contract.validate(self.build(agent=("gate-runner", text)))["errors"]
        self.assertTrue(any("unsupported destination" in e for e in errors))

    def test_personal_overrides_are_never_validated(self):
        root = self.build()
        forbidden = "build_run_" + "sim"
        (root / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"allow": [forbidden]}}))
        self.assertEqual(contract.validate(root)["errors"], [])


class RepositoryTests(unittest.TestCase):
    def test_repository_configuration_validates(self):
        report = contract.validate(REPO_ROOT)
        self.assertEqual(report["errors"], [])
        self.assertGreaterEqual(report["counts"]["rules"], 5)


if __name__ == "__main__":
    unittest.main()
