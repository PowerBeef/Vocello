---
status: historical
owner: release-qa
summary: Cause record for the Codex task-storage ballooning observed during the runtime work. Incident explanation from a point-in-time snapshot; not a cleanup authorization, policy, or current inventory.
contentDigest: sha256:db39324f249bac4cf275e0a25be2421692dd6522b65c92420b56b18ee42c35d9
---
# Codex Session Storage Ballooning — Cause Record

This note records why Codex task storage grew unusually large during the QwenVoice runtime work.
It is an incident explanation, not a cleanup authorization or a repository build-output policy.
The figures below come from the earlier read-only handoff snapshot and must not be treated as a
current inventory.

## Observed Snapshot

- Persisted Codex session storage was approximately **65.1 GB** across about **332 rollout files**.
- Approximately **62.25 GB** belonged to completed forked descendants of one unusually long-lived
  QwenVoice task.
- Content classification estimated that roughly **90% of the stored bytes were repeated compaction
  data**.
- Repeatedly embedded inline images added further duplicated payload.

No transcript bodies, prompts, image contents, rollout filenames, user paths, or task identifiers
are recorded here.

## Root Cause

The growth came from a persisted transcript tree, not from QwenVoice source, models, benchmarks, or
ordinary build caches.

1. **One top-level task lived through too many major work phases.** Its saved rollout accumulated a
   very large conversation, tool-result, and attachment history instead of ending at a coherent
   project checkpoint.
2. **Many descendants were created from that large context and were also persisted.** Completed
   subagent/fork tasks remained as saved rollout files. Reusing the long task history across those
   descendants multiplied storage instead of keeping each investigation small and self-contained.
3. **Context compaction reduced model-visible context, not the persisted transcript footprint.**
   Repeated compaction records were themselves retained in the rollouts. Across the parent and its
   descendants, those repeated compaction payloads became the dominant byte source.
4. **Inline images amplified the duplication.** Large image-bearing records were retained in the
   long history and could be represented again through descendants and subsequent compaction data.
5. **Archiving did not reclaim the bytes.** Archive changes task organization while preserving the
   saved transcript, so archived descendants continued occupying session storage.

The incident was therefore multiplicative: a large durable parent history was carried through many
durable descendants, then repeated compaction and image-bearing history magnified each copy.

## What Was Not The Cause

- QwenVoice `build/` output and Xcode caches use the separate tracked build-output policy.
- Model files and benchmark evidence were not included in the measured Codex rollout total.
- `/compact` was not a disk-cleanup mechanism; it changed context presentation while leaving the
  saved task history durable.
- Archive was not a disk-cleanup mechanism because it retained transcript storage.

## Prevention Boundary

Future work should keep repository state as the durable handoff and treat task transcripts as
bounded working state:

- recommend a new top-level task at major project checkpoints; Codex creates one only after an
  explicit operator request;
- give subagents a small self-contained brief and use `fork_turns="none"` or the smallest necessary
  bounded context;
- use `codex exec --ephemeral` for disposable investigations;
- avoid repeatedly embedding the same screenshots or large attachments;
- preserve implementation truth in committed code, machine-readable contracts, and
  `docs/development-progress.md`;
- use periodic aggregate read-only inventory to detect renewed growth early.

Permanent deletion remains a separate, explicitly approved operator action. This cause record does
not identify deletion targets and does not permit any change to live Codex state.
