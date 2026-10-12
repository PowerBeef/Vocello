---
status: active
owner: backend-and-platform
reviewed: 2026-10-12
summary: Claude Code takeover audit — what bound the harness to Codex, how hooks, permissions, skills, agents, rules and instructions were moved to Claude Code, what was verified live, and the open follow-ups (DA-15).
sourceOfTruth:
  - CLAUDE.md
  - .claude/settings.json
  - scripts/active_workers.py
  - scripts/tests/test_agent_hooks.py
---
# Vocello: Claude Code takeover audit

**Baseline:** `d14b070a`, reviewed October 12, 2026. The harness moved from Codex back to Claude Code
in `446ea479` (worker ownership and doctor), `c5f8e290` (hook wiring and permissions), `14ad9393`
(instructions, skills, agents, rules; `.codex/` and `.agents/` retired) and `7d68a7ad` (reference
docs). It supplements the [October 10 Codex takeover audit](2026-10-10-codex-workflow-audit.md), whose
CW findings and evidence remain intact; open work belongs to [`config/roadmap.json`](../../config/roadmap.json).

## Evidence and limits

Each commit ran the routed `scripts/dev.sh check`. The final batch passed 2,312 Python tests (one
existing skip, 2,838 subtests), the contract gate, repository invariants, the build-output policy, two
phone-free generic iOS compiles and the website check with its Playwright smoke. No model load,
download, device interaction, native UI lane, listening, benchmark, push or release operation ran.
Swift sources were not changed. The fresh-session activation check listed below is still outstanding.

## Project state at takeover

- `main` held 36 unpushed commits before this batch; pushes still wait for an explicit request.
- The primary plan `release-first-3-0-2026-09` is at 38%. The ordered audio-quality remediation is
  paused before step 1 (QC-06 in flight; QC-04, QC-08 and RF-14 open), with no fabricated labels.
- Local Xcode 27.0 differs from the CI pin 26.6 (CONV-21) and local gh 2.102 from the pinned 2.96;
  local builds do not prove the pinned compiler accepts a change.

## Findings and disposition

| ID | Finding at baseline | Disposition |
| --- | --- | --- |
| TK-01 | `active_workers.py` accepted only a `codex` owner process, so every lease failed under Claude Code and measured lanes needed `QVOICE_LEAD_ONLY=1`. | Owner is the native `claude` process; Codex and Node-hosted owners count as stale. SessionStart exports `QVOICE_WORKER_SESSION` through `CLAUDE_ENV_FILE`; SubagentStart hands agents their code-only rules. |
| TK-02 | `commit_lint.sh` required `codex/*` branches in linked worktrees; Claude Code agent worktrees use `worktree-*`. | Linked worktrees commit only on `worktree-*`; registration (not directory spelling) still establishes identity. A retired `codex/*` branch is refused. |
| TK-03 | `test_agent_hooks.py` failed whenever `CLAUDE.md` or `.claude/` was tracked. | Replaced by the inverse: the retired `.codex/`, `.agents/` and `AGENTS.md` files must not be tracked. |
| TK-04 | `dev.sh doctor` reported a Codex section and looked for Axiom helpers under the Codex plugin cache, so they appeared missing. | Doctor reports `claudeCode` (instructions, skills, agents, rules, parsed settings hooks) and finds the helpers in the Claude plugin cache. |
| TK-05 | The guards were wired only through `.codex/hooks.json`; the adapters still parsed Claude payloads beside a Codex patch parser and a `codex/` branch-creation exemption. | `.claude/settings.json` wires every guard through `$CLAUDE_PROJECT_DIR`; the Codex-only paths are removed and unknown tools fail closed. Tests pin the matrix, matcher semantics, live dispatch and permissions. |
| TK-06 | The Xcode MCP server is exposed as `MobileBuildMCP` with only its simulator workflows, which the project forbids; the old deny list named the `XcodeBuildMCP` prefix. | Wildcard deny rules remove the unsupported-destination and UI-driving tools without literal names in the tree. Enabling the macOS, device and debugging workflows described by `.xcodebuildmcp/config.yaml` is a user-level MCP setting (open). |
| TK-07 | The Axiom simulator-tester, test-runner and test-debugger agents drive simulators or rerun tests outside the repository lanes. | Denied in project permissions; the `xcui` helper stays excluded by instruction. |
| TK-08 | Comments in `project.yml`, three Swift files, the owned-package README and `benchmarks/OPTIMIZATION.md` pointed at the deleted `.claude/rules/native.md`. | The path exists again as a symlink to `docs/reference/native-engineering.md`, whose `paths:` front matter scopes it. |
| TK-09 | `Packages/VocelloQwen3Core/README.md` says `macos_test.sh test` runs `VocelloEngineIntegrationTests`, a target `project.yml` does not define. | Open documentation drift; recorded under DA-15. |
| TK-10 | Eleven `~/.codex/worktrees` registrations pointed at removed directories; four agent branches were fully merged. | Pruned and deleted. Twenty-five unmerged agent branches remain: sixteen are patch-equivalent to `main`; nine hold commits not on `main` (`codex/clone-asr-review`, `codex/clone-reference-ui`, five `worktree-agent-*` branches including the two live `.claude/worktrees`, and `worktree-wf_cdf39e2b-85c-1`). Nothing unmerged was deleted. |

## Observed in the migration session

- Edits to the tracked `.claude/settings.json` applied to the running session immediately.
- The wildcard deny rules removed the session's unsupported-destination MobileBuildMCP tools (including
  list, record and app-path variants, screenshot, UI snapshot and clean) and the three Axiom agents.
- A denied staging command (`git add -A -n`) was refused before it ran, and a harmless `echo` naming a
  simulator lifecycle command was blocked by the live `policy_guard.sh` PreToolUse hook, which cited
  `CLAUDE.md: Physical iPhone only`. The commits after `c5f8e290` passed through the live commit lint.
- The tooling rule loaded through its `.claude/rules` symlink when `CLAUDE.md` was written, and the six
  skills were listed as soon as they moved.

SessionStart output, worker receipts, the exported marker and SubagentStart/Stop leases need a new
session; this one started before the settings existed. `scripts/dev.sh doctor` reports Claude Code
2.1.296 and finds the Axiom helpers.

## Carried forward

CW-01 (generation signature) and CW-02 (live worker leases) stay fixed; CW-02's ownership check now
names Claude Code. CW-03 is reversed by this migration, including routing and scanners. CW-04 to CW-07
keep their existing dispositions (CW-05 under DA-14, CW-06 and CW-07 under DA-13).

## Fresh-session acceptance (DA-15)

Start `claude` at the repository root and confirm: the SessionStart banner ("CLAUDE.md: Start here");
`/memory` lists `CLAUDE.md` and no `AGENTS.md`; `/hooks` shows eight entries; `/permissions` reports no
invalid rule; `QVOICE_WORKER_SESSION` is set and `python3 scripts/active_workers.py status` reports
`trackingAvailable: true`; a trivial subagent moves `activeWorkers` to 1 and back; `git switch -c smoke`
and an Edit of a generated file are refused; reading a Swift source loads `.claude/rules/native.md`;
the six `/vocello-*` skills and both agents (model `inherit`) are listed. Record the client version.
