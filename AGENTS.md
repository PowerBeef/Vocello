# Codex entry point — Vocello

Read `CLAUDE.md` before working here. It is the shared repository policy, including the source-of-truth
order, commands, main-only workflow, generated files, privacy and explicit device/UI/release consent.
Follow its startup sequence and read the current roadmap and development checkpoint.

Then load the guidance for the files in scope:

- Swift, owned packages, tests or project inputs: `.claude/rules/native.md`.
- Scripts, contracts, CI, evidence, documentation or agent configuration: `.claude/rules/release.md`.
- Anything in `website/`: `website/CLAUDE.md`; use the website commands independently of native lanes.

Claude is the primary developer; Codex reviews and implements explicitly assigned work. Take turns
editing the existing checkout. Follow the handoff procedure in
`docs/reference/development-workflow.md#claude-and-codex-handoffs`; reconcile an unexpected HEAD or
dirty-tree change before editing or staging overlapping files. Review is read-only unless fixes were
assigned. Application findings belong in the existing roadmap, not a second task ledger.

The project Codex hooks share the repository guards with Claude. Hooks require platform trust and
are best-effort guardrails, not a sandbox or a grant of permission. Tools and skills never override
repository invariants. Keep personal settings, credentials and transcripts out of tracked files.
