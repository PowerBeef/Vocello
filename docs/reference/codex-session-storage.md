---
status: active
owner: release-qa
summary: Operator runbook for the optional Codex task/session storage workflow — inventory, checksummed plan, exact approval, supported deletion, verification; live user state never enters the repository.
sourceOfTruth:
  - scripts/codex_session_storage.py
  - config/codex-session-storage-policy.json
---
# Codex Task And Session Storage

This is the operator runbook for keeping QwenVoice Codex work bounded without making private Codex
state a repository prerequisite. The tracked authority is
`config/codex-session-storage-policy.json`; `scripts/codex_session_storage.py` implements its
privacy-safe inventory, review plan, explicit execution, and verification stages.
The reason this workflow was proposed is recorded separately in
[`codex-storage-ballooning-incident.md`](codex-storage-ballooning-incident.md).

This workflow is optional, local, and manually initiated. It is not a development, CI, packaging,
release, or benchmark gate. The repository tracks the process and synthetic tests only. It never
tracks a live inventory, task UUID, task title, rollout filename, manifest, execution journal, or
absolute user path.

## Keep New Work Bounded

Use these habits before cleanup becomes necessary:

1. At a coherent major checkpoint or workstream change, the operator should start a new top-level
   Codex task. Codex may create that user-owned task only when the operator explicitly requests it.
   First preserve the source checkpoint, update `docs/development-progress.md` when the
   authoritative continuation point changed, and leave a short repository-only handoff.
2. Give subagents the smallest self-contained brief. Prefer `fork_turns="none"` or a small bounded
   recent context; never fork a complete long-running task history by default.
3. Use `codex exec --ephemeral` for disposable, non-interactive investigations that do not need a
   saved task.
4. Avoid repeatedly attaching the same image or large file. Persist reusable conclusions in code,
   a machine-readable contract, or an appropriate repository document rather than only in chat.
5. Run the aggregate status command before and after a major convergence phase, or when a heavy
   lane approaches its free-space floor. Do not turn the check into scheduled automation.

The repository checkpoint, not a transcript, is implementation truth. A handoff may name a branch,
commit, repository-relative file, decision, verification result, and open work. It must not copy raw
conversation, private paths, prompts, user data, or task/session identifiers into tracked content.

## Product Semantics And Boundaries

The current supported CLI describes `codex delete SESSION` as permanent deletion of one saved
interactive session and requires a UUID when `--force` is used. The CLI documentation does not
promise that this command cascades, so this workflow never assumes a cascade: it plans every proven
descendant explicitly and deletes deepest-first, with the selected root last. The interactive
`/delete` command has separate documented current-task-and-descendant behavior and is not used by
the helper. See the official [Codex CLI command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli#cli-codex-delete)
and [slash-command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli#delete-the-current-session-with-delete).

Archiving only removes a saved task from active lists while preserving its transcript; it is
organization, not storage reclamation. `/compact` summarizes visible context for the model and is
also not a persisted-transcript cleanup operation. The helper therefore performs neither action.

The live read boundary is deliberately narrow:

- covered roots: `sessions/` and `archived_sessions/` beneath the selected Codex home;
- covered files: plain `rollout-*.jsonl` and cold-compressed `rollout-*.jsonl.zst`;
- read content: exactly one bounded physical line, which must be the first `session_meta` record;
- allowed fields: task ID, declared root ID, immediate and redundant spawn parent IDs, timestamp,
  and working-directory classification;
- excluded content: every later JSONL line, task title, prompt, transcript, tool output, image,
  database, config, memory, log, attachment, plugin, skill, package, generated image, repository
build output, model, and benchmark record.

Compressed metadata uses Python's standard-library `compression.zstd` reader with the same
decompressed first-line byte limit. If that reader is unavailable, the aggregate status reports a
metadata error and planning fails closed instead of omitting the compressed rollout. Use Python
3.14 or newer for live inventory when compressed rollouts are present.

An invalid, duplicated, cyclic, incomplete, changing, symlinked, or target-adjacent record fails
closed. Anything unrelated or unresolved is protected. The helper never edits SQLite and never
unlinks a rollout directly; the only mutation route is the exact supported Codex CLI command bound
into the reviewed manifest.

## Stage 1 — Aggregate Status

This command reads local metadata and prints counts, logical bytes, allocated bytes, graph-health
counts, and filesystem availability. It does not print IDs, filenames, task names, or paths.

```sh
python3 scripts/codex_session_storage.py status
```

Use `--json` only for an untracked local diagnostic. Do not redirect it into the repository.

The helper uses `stat.st_size`, allocated blocks, and filesystem usage as its direct authorities.
For a one-off investigation, `du -A`, `du`, and `df` may corroborate apparent, allocated, and free
space. Mole is optional and Analyze-only: read the installed help first, suppress entry names and
paths, and treat its result as supplemental because its cached analysis can be stale. Mole Clean or
Delete never belongs in this workflow.

## Stage 2 — Preserve The Project Checkpoint

Before proposing permanent deletion, confirm that coherent implementation work is already shared:

```sh
git fetch
git status --short --branch
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git rev-parse HEAD
git rev-parse '@{upstream}'
git diff --check
python3 scripts/documentation_contract.py
python3 scripts/benchmark_history.py validate --all
python3 scripts/benchmark_history.py rebuild-index --check
```

Use the active branch's configured upstream, or an explicitly reviewed remote branch when no
upstream exists. `HEAD` must equal that freshly fetched ref. A dirty or unpushed tree does not make
a transcript safe to delete; preserve the coherent source checkpoint first. Do not duplicate a
giant transcript tree on the same nearly full disk. If full transcript retention is explicitly
required, stop and use a separate external volume with independently verified capacity. A Git
checkpoint, the compact checksummed plan, and a sanitized handoff are the default preservation set.

## Stage 3 — Create A Review Plan

Identify the completed old top-level root and the current top-level task to protect. The protected
root is mandatory and must differ from the old root.

```sh
python3 scripts/codex_session_storage.py plan \
  --delete-root <old-root-uuid> \
  --protect-root <current-root-uuid> \
  --output-dir /tmp/codex-session-cleanup-review
```

Use a new, nonexistent temporary directory for every proposal. The helper validates the installed
`codex --version` and `codex delete --help`, binds their digests into a 24-hour plan, and writes
mode-0600 `deletion-plan.json` plus `deletion-plan.sha256` inside a mode-0700 system-temporary
directory. It also binds the selected Codex home's filesystem identity without recording its path.
The manifest contains only privacy-safe
metadata: UUID relationships, timestamps, repository/other/missing working-directory class,
logical and allocated bytes, classification/reason codes, target fingerprints, and deterministic
bottom-up order. It never contains task names, transcript content, or raw paths.

Review the complete manifest locally. The approval checkpoint must state:

- exact old root UUID and manifest SHA-256;
- number and logical/allocated bytes of proposed targets;
- number and bytes of protected and ambiguous records;
- current filesystem availability;
- explicit deepest-first `codex delete --force UUID` execution, root last;
- backup choice and confirmation that the current task is protected.

Stop here. Storage pressure, an approximate size, or a broad request to clean old tasks is not
approval. Execution requires a separate explicit approval for the exact root and SHA-256. A changed
manifest, not-yet-active or expired plan, updated Codex executable/help contract, or changed target
graph invalidates that approval. The approval window is exactly `createdAt <= now <= expiresAt`;
moving both timestamps into the future cannot extend it.

## Stage 4 — Execute The Approved Plan

This command is permanently destructive. Run it only after the exact approval checkpoint above:

```sh
python3 scripts/codex_session_storage.py execute \
  --manifest /tmp/codex-session-cleanup-review/deletion-plan.json \
  --approved-sha256 <reviewed-sha256> \
  --approved-root <old-root-uuid>
```

Execution never rebuilds or broadens the target list. It performs two live scans before mutation,
requires every target fingerprint and protected baseline to match, then invokes the supported
Codex command with an argument array, no shell, and `CODEX_HOME` explicitly bound to the same
fingerprinted state root used for planning. Before each command the next target must be a
leaf. After every command, exactly that UUID must be absent, every pending target must remain, and
every protected or ambiguous baseline record must still exist. New unrelated tasks are protected;
new target descendants, references to any approved ID (including one already deleted), or
target-adjacent ambiguity stop execution.

Every newly observed non-target becomes part of the in-memory preservation baseline before the
next command. If it disappears or changes identity during this execution, the batch stops even
though it was created after the reviewed manifest.

The mode-0600 `execution-journal.json` is local and single-use. Any 120-second command timeout,
nonzero exit, database error, unexpected UUID, target drift, extra deletion, or protected
disappearance stops the batch.
Never resume blindly or reconstruct a remaining list from a wildcard. Inspect the journal, verify
live state, create a fresh plan for any remaining proven tree, and request new approval.

## Stage 5 — Verify And Handoff

Verification remains read-only and works after the plan expires:

```sh
python3 scripts/codex_session_storage.py verify \
  --manifest /tmp/codex-session-cleanup-review/deletion-plan.json \
  --approved-sha256 <reviewed-sha256>

codex doctor --json
git fetch
git status --short --branch
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
git rev-parse HEAD
git rev-parse '@{upstream}'
```

Keep the `codex doctor` report local because it may contain installation details. Confirm that all
approved UUIDs and residual edges are absent, the exact execution journal is complete and passing,
protected task identities and lineages remain unchanged, the state diagnostic passes,
and repository refs remain equal and clean. Re-run aggregate status plus optional `du`/`df`; post-
action filesystem availability is the authority for actual reclamation. APFS accounting, active
task appends, directory metadata, and tool caches can make byte deltas non-additive.

Permanent deletion has no repository-provided rollback. If the post-check mismatches the approved
delta, stop immediately, preserve the journal and manifest locally, do not start another batch, and
ask the operator how to proceed. Do not file an external issue or upload diagnostics without
separate approval.

## Deterministic Repository Verification

Only policy validation and synthetic temporary-home fixtures belong in ordinary repository checks:

```sh
python3 scripts/codex_session_storage.py validate
python3 -m unittest scripts.tests.test_codex_session_storage
```

These commands do not require Codex to be installed and never inspect a real Codex home. They are
repository gates; live `status`, `plan`, `execute`, and `verify` subcommands remain operator-local
non-gates and stay outside CI, releases, benchmarks, and release evidence.
