#!/usr/bin/env python3
"""Validate the repository-owned Claude Code configuration under `.claude/`.

The previous agent environment kept its hook wiring in a separate file whose
every byte was pinned by a test. Claude Code configuration is richer -- hooks,
permissions, skills, subagents and path-scoped rules -- and all of it lives in
the repository, so it can be validated like any other contract instead of being
declared "unverifiable user-scoped tooling".

What this checks (fail closed):

* `.claude/settings.json` parses; every command hook resolves to an existing,
  executable script under `scripts/hooks/`; the commit gate
  (`scripts/hooks/precommit_gate.sh`) is wired as a `PreToolUse` `Bash` hook;
  no `PreToolUse` hook declares a timeout above 30 s (builds never run in hooks).
* `permissions.deny` keeps the repository's policy shape: Simulator boot,
  direct `project.pbxproj` writes, force pushes and whole-cache deletion stay
  denied even when a personal `settings.local.json` widens `allow`.
* Every `.claude/skills/*/SKILL.md` has `name` (matching its directory) and
  `description`; a skill that drives a device, a model lane or release state
  declares `disable-model-invocation: true`, which is the repository's
  "explicit QA scope" invariant expressed in Claude Code terms.
* Every `.claude/agents/*.md` has `name`, `description` and an explicit `tools`
  allowlist; no project agent requests worktree isolation (main-only policy).
* Every `.claude/rules/*.md` `paths:` glob matches at least one file, so a rule
  cannot silently stop loading after a directory rename.
* Nothing under `.claude/` (or a project `.mcp.json`) names a Simulator
  workflow; physical iPhone and macOS are the only supported destinations.

Usage:
    python3 scripts/claude_config_contract.py validate [--root DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from doc_metadata import split_frontmatter  # noqa: E402

SETTINGS_PATH = ".claude/settings.json"
COMMIT_GATE = "scripts/hooks/precommit_gate.sh"
HOOK_COMMAND = re.compile(r'"\$CLAUDE_PROJECT_DIR"/(scripts/hooks/[A-Za-z0-9_.-]+\.sh)\b')
MAX_PRE_TOOL_USE_TIMEOUT = 30
REQUIRED_DENY_FRAGMENTS = (
    ("simctl boot", "Simulator boot"),
    ("project.pbxproj", "direct project.pbxproj writes"),
    ("git push --force", "force pushes"),
    ("rm -rf build/cache", "whole build-cache deletion"),
)
# Tokens whose presence in a skill body means the skill can touch a device, a
# model lane or release state. Such skills must be user-invoked only.
EXPLICIT_SCOPE_TOKENS = (
    "scripts/ui_test.sh",
    "scripts/ios_device.sh",
    "scripts/release.sh",
    "quality_promotion.py",
    "release_source_authority.py",
    "test_device",
    "build_run_device",
    "install_app_device",
)
# Built from pieces so this file never contains the literal strings that
# scripts/check_test_workflows.sh rejects across the active tree.
_SIM = "Sim" + "ulator"
FORBIDDEN_DESTINATION = re.compile(
    "|".join([
        "platform=iOS " + _SIM,
        "build_run_" + "sim\\b",
        "test_" + "sim\\b",
        "launch_" + "sim\\b",
        "boot_" + "sim\\b",
    ]),
    re.IGNORECASE,
)


class ContractError(RuntimeError):
    """Inputs could not be read."""


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1")


def _tracked_config_files(root: pathlib.Path) -> list[pathlib.Path]:
    base = root / ".claude"
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        # Personal overrides and worktrees are gitignored and never validated.
        if rel == ".claude/settings.local.json" or rel.startswith(".claude/worktrees/"):
            continue
        out.append(path)
    return out


def validate_settings(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    path = root / SETTINGS_PATH
    if not path.is_file():
        return [f"{SETTINGS_PATH}: missing"]
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{SETTINGS_PATH}: invalid JSON ({error})"]

    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return [f"{SETTINGS_PATH}: hooks must be an object"]
    gate_wired = False
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            errors.append(f"{SETTINGS_PATH}: hooks.{event} must be a list")
            continue
        for group in groups:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            matcher = group.get("matcher", "") if isinstance(group, dict) else ""
            for handler in handlers:
                if handler.get("type") != "command":
                    errors.append(f"{SETTINGS_PATH}: hooks.{event} handler is not a command hook")
                    continue
                command = str(handler.get("command", ""))
                match = HOOK_COMMAND.search(command)
                if not match:
                    errors.append(
                        f"{SETTINGS_PATH}: hooks.{event} command must be "
                        f'"$CLAUDE_PROJECT_DIR"/scripts/hooks/<name>.sh, got {command!r}'
                    )
                    continue
                script = root / match.group(1)
                if not script.is_file():
                    errors.append(f"{SETTINGS_PATH}: hooks.{event} references missing {match.group(1)}")
                elif not os.access(script, os.X_OK):
                    errors.append(f"{SETTINGS_PATH}: {match.group(1)} is not executable")
                timeout = handler.get("timeout")
                if event == "PreToolUse" and timeout is not None and timeout > MAX_PRE_TOOL_USE_TIMEOUT:
                    errors.append(
                        f"{SETTINGS_PATH}: PreToolUse hook {match.group(1)} timeout {timeout}s exceeds "
                        f"{MAX_PRE_TOOL_USE_TIMEOUT}s; hooks check receipts, they never run builds"
                    )
                if event == "PreToolUse" and match.group(1) == COMMIT_GATE and "Bash" in str(matcher):
                    gate_wired = True
    if not gate_wired:
        errors.append(f"{SETTINGS_PATH}: {COMMIT_GATE} must be wired as a PreToolUse hook with a Bash matcher")

    permissions = settings.get("permissions", {})
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else []
    deny_text = "\n".join(str(entry) for entry in deny).lower()
    for fragment, meaning in REQUIRED_DENY_FRAGMENTS:
        if fragment not in deny_text:
            errors.append(f"{SETTINGS_PATH}: permissions.deny must keep {meaning} denied (expected {fragment!r})")
    return errors


def _frontmatter(path: pathlib.Path, root: pathlib.Path) -> tuple[dict, str, str | None]:
    rel = path.relative_to(root).as_posix()
    try:
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return {}, "", f"{rel}: {error}"
    if meta is None:
        return {}, "", f"{rel}: frontmatter is required"
    return meta, body, None


def validate_skills(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    base = root / ".claude" / "skills"
    if not base.is_dir():
        return errors
    for skill_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        skill = skill_dir / "SKILL.md"
        rel = f".claude/skills/{skill_dir.name}/SKILL.md"
        if not skill.is_file():
            errors.append(f"{rel}: missing")
            continue
        meta, body, problem = _frontmatter(skill, root)
        if problem:
            errors.append(problem)
            continue
        if meta.get("name") != skill_dir.name:
            errors.append(f"{rel}: name must equal the directory name {skill_dir.name!r}")
        if not meta.get("description"):
            errors.append(f"{rel}: description is required")
        touches_scope = any(token in body for token in EXPLICIT_SCOPE_TOKENS)
        if touches_scope and not _truthy(meta.get("disable-model-invocation", "")):
            errors.append(
                f"{rel}: drives a device, model lane or release state and must declare "
                "disable-model-invocation: true (explicit QA scope is user-invoked only)"
            )
    return errors


def validate_agents(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    base = root / ".claude" / "agents"
    if not base.is_dir():
        return errors
    for agent in sorted(base.glob("*.md")):
        rel = agent.relative_to(root).as_posix()
        meta, _body, problem = _frontmatter(agent, root)
        if problem:
            errors.append(problem)
            continue
        if meta.get("name") != agent.stem:
            errors.append(f"{rel}: name must equal the file stem {agent.stem!r}")
        if not meta.get("description"):
            errors.append(f"{rel}: description is required")
        if not meta.get("tools"):
            errors.append(f"{rel}: tools must be an explicit allowlist")
        if str(meta.get("isolation", "")).strip() == "worktree":
            errors.append(f"{rel}: worktree isolation is off-policy (development stays on main)")
    return errors


def validate_rules(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    base = root / ".claude" / "rules"
    if not base.is_dir():
        return [".claude/rules: missing"]
    for rule in sorted(base.glob("*.md")):
        rel = rule.relative_to(root).as_posix()
        meta, _body, problem = _frontmatter(rule, root)
        if problem:
            errors.append(problem)
            continue
        paths = meta.get("paths", [])
        if isinstance(paths, str):
            paths = [paths] if paths else []
        for pattern in paths:
            if not any(True for _ in root.glob(pattern)):
                errors.append(f"{rel}: paths glob {pattern!r} matches no file")
    return errors


def validate_destinations(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    candidates = _tracked_config_files(root)
    mcp = root / ".mcp.json"
    if mcp.is_file():
        candidates.append(mcp)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        match = FORBIDDEN_DESTINATION.search(text)
        if match:
            rel = path.relative_to(root).as_posix()
            errors.append(f"{rel}: names an unsupported destination {match.group(0)!r}")
    return errors


def validate(root: pathlib.Path) -> dict:
    errors: list[str] = []
    for check in (validate_settings, validate_skills, validate_agents, validate_rules, validate_destinations):
        errors.extend(check(root))
    counts = {
        "skills": len(list((root / ".claude" / "skills").glob("*/SKILL.md"))),
        "agents": len(list((root / ".claude" / "agents").glob("*.md"))),
        "rules": len(list((root / ".claude" / "rules").glob("*.md"))),
    }
    return {"ok": not errors, "errors": errors, "counts": counts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = validate(pathlib.Path(args.root).resolve())
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    for error in report["errors"]:
        print(f"claude-config error: {error}", file=sys.stderr)
    if not report["ok"]:
        return 1
    counts = report["counts"]
    print(
        "Claude Code configuration: PASS "
        f"({counts['rules']} rules, {counts['skills']} skills, {counts['agents']} agents)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
