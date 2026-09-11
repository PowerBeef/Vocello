---
status: active
owner: release-qa
reviewed: 2026-09-11
summary: Domain rule for the repository-owned Claude Code configuration — hooks, permissions, path-scoped rules, project skills, project subagents, MCP routing (XcodeBuildMCP, GitHub, Sosumi) and Axiom usage.
sourceOfTruth:
  - .claude/settings.json
  - scripts/hooks/commit_lint.sh
  - scripts/development_workflow.py
---
# Claude Code tooling — hooks, skills, subagents, MCP

Claude Code is the development environment. Everything it needs from the repository lives under
`.claude/`; the hooks are behaviour-tested in `scripts/tests/test_claude_hooks.py`. Nothing here is a
prerequisite for CI, commits or packaging:
scripts remain the gates, and this configuration only makes the scripted routes easier to follow.

## Layout

| Path | Loaded | Purpose |
| --- | --- | --- |
| `CLAUDE.md` | every session | Product, commands, hard invariants, routing, verification tiers |
| `.claude/rules/*.md` | by `paths:` frontmatter; this file always | Domain rules; each keeps the repository frontmatter (`status`, `owner`, `summary`, `sourceOfTruth`) so `scripts/doc_metadata.py` governs it like any other doc |
| `website/CLAUDE.md` | when working under `website/` | Nested website guidance |
| `.claude/settings.json` | always | Hooks and permission defaults (tracked) |
| `settings.local.json` (untracked, under `.claude/`) | always | Personal overrides (untracked, never validated) |
| `.claude/skills/<name>/SKILL.md` | on `/name` or when relevant | Procedures that route to existing scripts and docs |
| `.claude/agents/<name>.md` | on delegation | Read-mostly subagents that keep long outputs out of the main context |
| `.xcodebuildmcp/config.yaml` | by the XcodeBuildMCP server | Shared macOS and physical-device profiles; validated by `scripts/dev.sh assists` |

## Hooks (`.claude/settings.json`)

All hook scripts live in `scripts/hooks/`, read the hook JSON from stdin, and exit 0 (allow) or 2
(block, message on stderr). No hook runs a build; a hook that needs more than a few seconds is a defect.

| Event | Script | Behavior |
| --- | --- | --- |
| `PreToolUse` Bash | `commit_lint.sh` | `git commit` requires `main`, a whitespace-clean staged diff and no private path or credential in staged files; under 15 s, never a build |
| `PreToolUse` Bash | `policy_guard.sh` | Blocks Simulator destinations, whole-cache deletion, force pushes, new branches or worktrees, and direct `project.pbxproj` writes |
| `PreToolUse` Edit/Write | `generated_file_guard.sh` | Blocks hand edits of generated or frozen files and names the generator; warns on pinned historical docs |
| `PostToolUse` Edit/Write | `project_yml_reminder.sh` | After editing `project.yml`, reminds to run `scripts/regenerate_project.sh --fast` |
| `SessionStart` | `session_start.sh` | Prints branch/dirty state, `scripts/dev.sh status` (lanes, primary plan), the "Resume now" excerpt, iPhone reachability (no identifier) and the TSan deadline |

`permissions.allow` pre-approves read-only and deterministic commands; `permissions.ask` covers device,
model and publication routes; `permissions.deny` mirrors the guards. Permissions reduce prompts, hooks
enforce policy; the deny entries for Simulator boot, `project.pbxproj` writes, force pushes and
`rm -rf build/cache` stay in place.

## Skills (`.claude/skills/`)

| Skill | Invocation | Routes to |
| --- | --- | --- |
| `/checkpoint` | Claude or user | `scripts/dev.sh check`, then the commit (no receipt; CI on push is the gate) |
| `/refresh-docs` | Claude or user | `scripts/refresh_derived_artifacts.py`, `scripts/doc_metadata.py validate`, contentDigest re-pins |
| `/roadmap-checkpoint` | Claude or user | `config/roadmap.json` item update, narrative block, `scripts/roadmap.py validate` and `render` |
| `/ios-lane` | user only | `scripts/ui_test.sh ios <lane>` with probe, storage floor and consent statement; triage afterwards |
| `/macos-ui-lane` | user only | `scripts/ui_test.sh macos <lane>` |
| `/device-diagnostics` | user only | `scripts/ios_device.sh <verb>` |
| `/release-evidence` | user only, read-only | `scripts/release_source_authority.py`, `scripts/quality_promotion.py validate` |

Skills that touch a device, a model lane or release state declare `disable-model-invocation: true`;
the contract rejects one that does not. That is the "explicit QA scope" invariant in Claude Code terms.

## Subagents (`.claude/agents/`)

| Agent | Tools | Use for |
| --- | --- | --- |
| `gate-runner` | Bash, Read, Grep | Running `scripts/dev.sh checkpoint` or `./scripts/check_project_inputs.sh` and returning only failures and the next command |
| `xcresult-triage` | Bash, Read, Grep, Glob | Classifying a finished run under `build/artifacts/ui-tests/` or `build/artifacts/macos/tests/` from its xcresult, ledger and classifiers; never reruns a lane |
| `doc-governance-reviewer` | Bash, Read, Grep | Listing docs that need regeneration, re-pin or frontmatter fixes |
| `swift-review` | Read, Grep, Glob | Reviewing a Swift diff against the domain rules before a checkpoint |

Every project agent declares an explicit tool allowlist and none uses worktree isolation (main-only).

## MCP servers and skills routing

- **XcodeBuildMCP** (user-scoped server, repository `.xcodebuildmcp/config.yaml`): call
  `session_show_defaults` first, then `session_use_defaults_profile` with `macos` (scheme `QwenVoice`)
  or `ios-device` (scheme `VocelloiOS`). Set the physical-device id only at runtime; never write it to
  the yaml. Allowed: scratch builds under `build/scratch/derived-data/xcodebuildmcp/`, `test_macos`
  for one XCTest class, device LLDB and log capture on request. `test_device`, `build_run_device`
  and `install_app_device` need an explicit user request and are never evidence; `scripts/ui_test.sh`
  remains the only UI driver. Simulator, preview and UI-automation routes are never enabled.
- **GitHub MCP** for PRs, checks, issues and releases (read first); `gh` is the fallback. No
  `gh release create|edit` outside `.github/workflows/promote-release.yml`.
- **Sosumi MCP** and `axiom-apple-docs` for Apple API questions; the `xcodebuildmcp` skill for the
  server above. The `axiom-xcode-mcp` skill documents Apple's own Xcode MCP bridge and is not used here.
- **Axiom** agents: `axiom:crash-analyzer` (`xcsym`, also used by `scripts/macos_test.sh crashes`),
  `axiom:concurrency-auditor` before TSan promotion review (`config/tsan-policy.json`),
  `axiom:iap-auditor` for the iOS StoreKit unlock, `axiom:accessibility-auditor` for Dynamic Type and
  pseudo-locale work, `axiom:test-failure-analyzer` after `xcresult-triage`, `axiom:build-fixer` only
  with the repository caveat (no Simulator, no cache wipes outside `scripts/clean_build_caches.sh`),
  `axiom:performance-profiler` for ad hoc `xcprof` traces while repository `profile` lanes own evidence.
  Axiom's `xcui` and `simulator-tester` are Simulator-only and are not used.
- **Built-ins**: `/code-review` before each checkpoint commit, `/simplify` on Swift-only diffs,
  `/security-review` on entitlement, plist or StoreKit changes.
- **swift-lsp** (optional): needs `sourcekit-lsp` plus `xcode-build-server` (Homebrew) configured
  against the repository's persistent macOS cache, which already holds a full build and index:
  `xcode-build-server config -project QwenVoice.xcodeproj -scheme QwenVoice --build_root "$PWD/build/cache/xcode/macos"`
  writes the untracked `buildServer.json`. Xcode's default DerivedData has no build, so without
  `--build_root` SourceKit reports missing modules. Verify one symbol lookup before relying on it; never a gate.

## What is checked

`scripts/tests/test_claude_hooks.py` runs every hook against real payloads (allowed, blocked, ask) and
`scripts/repo_invariants.sh` rejects Simulator destinations anywhere under `.claude/`. There is no
separate configuration validator: a hook that stops working fails its behaviour test.

Authority: `CLAUDE.md` hard invariants **Scripts outrank assists**, **One UI driver**, **Physical
iPhone only** and **Main only**. Scripts win over this rule.
