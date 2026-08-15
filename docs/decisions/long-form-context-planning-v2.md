---
status: historical
owner: backend-mlx
summary: Adopted 2026-08-01: long-form planner v2 text-first design — lookahead boundary scoring over the greedy v1 scan, fixtures-first, with generation-time context explicitly out of scope.
contentDigest: sha256:5e58c3a966e0bf3e0f42ff7d9079b6ec7d1895b4f126f854e787ccc04b4c8915
---
# Long-form context-aware planning (planner v2) — Tier 4 text-first design

- **Status:** adopted and implemented 2026-08-01 (maintainer-directed Tier-4 start);
  fixtures landed first and drove one design correction (R-pull removed as dead by
  construction — see Alternatives).
- **Scope:** `LongFormPlanner` text-only planning quality. Explicitly **not** in scope:
  generation-time context prefixes (no prompt-assembly change), acoustic/KV carryover
  (stage 2, its own design gated on segment memory budgets), cross-segment seed
  coupling, any engine-loop change.

## Problem

Planner v1 is a greedy forward scan: fill the token window, take the best-precedence
boundary in the window (paragraph > sentence > semicolon/colon > safe clause >
whitespace > grapheme, last candidate wins within a kind), trim, repeat. It is
deterministic and identity-versioned, but myopic — it never looks at what a boundary
choice does to the *next* segment:

1. **Orphan tails.** The final segment can be a single short sentence. Short segments
   pace differently (§P: short cells run hotter/looser), so an orphan tail is an
   audible pacing step at the exact place a listener expects closure.
2. **Last-wins tie-break.** Among same-kind candidates the planner takes the latest,
   maximizing the current segment with no balance consideration for its successor —
   the mechanism that manufactures orphan tails.

Roadmap basis: Q2 "text first — adjacent-sentence text into segment planning, no
acoustic risk" (`docs/reference/optimization-report-review-2026-07-25.md`, Stage 5).

## Design

### v2 rules (all pure, deterministic, bounded by `runtimeTokenLimit`)

- **R-tail (orphan avoidance):** after selecting a candidate, if the remaining text
  would fit in a single segment whose conservative token estimate is below
  `minimumTailFraction` (0.25) of the limit, re-select the boundary to balance the
  final two segments: choose the same-or-better-precedence candidate closest to the
  midpoint of the combined span that keeps both halves under the limit. If no such
  candidate exists, keep the original selection (never degrade boundary kind).
The rule consults adjacent-sentence structure only — no audio, no seeds, no engine
state. The threshold (`minimumTailFraction` 0.25) is a planner constant implied by
algorithm version 2, not a configuration parameter — the configuration and identity
serialization shapes are unchanged. Grapheme candidates are never used for
re-selection, and boundary kinds never degrade (re-selection considers only
same-or-better precedence).

### Identity and compatibility

- `currentPlannerAlgorithmVersion` bumps 1 → 2. The version is already a serialized
  component of `long-form-plan-v1` and `long-form-segment-v1` digests, so every new
  plan's segment IDs and derived sub-seeds re-version **deliberately**; there is no
  silent collision by construction.
- Retained projects are untouched: execution and single-segment regeneration replay the
  **recorded** plan object (`request.plan.segments[...]`; verified — no re-planning
  path exists for a retained project), and `validated()` gates only new planning.
- The serialization namespaces do not change; no manifest migration is required.

### Evidence plan

1. **Fixtures first** (`Tests/VocelloCoreTests/LongFormPlanningTests.swift`): a small
   corpus of representative texts (multi-paragraph narration, prose ending in a short
   sentence, short-sentence-after-paragraph, uniform long prose, protected-span text)
   asserting v2 properties — no tail segment under the minimum fraction unless the text
   forces it, boundary kinds never degrade
   relative to v1 on the same text, identities stable across runs, v1-recorded plans
   replay untouched.
2. **Fixed-seed planner A/B** (deterministic, no generation): plan the fixture corpus
   with v1 and v2 configurations and record segment-count/length-variance/orphan
   incidence deltas in the test log — the planning-level acceptance evidence.
3. **Generation-level check (bounded, macOS):** one long fixture text, same baseSeed,
   v1 vs v2 plan → sequential generation → existing assembler edge metrics
   (`maximumSegmentBoundaryJump`, boundary-adjacent pitch/rate deltas via the standing
   analyzer). Advisory evidence, not a promotion gate: text-only planning does not
   touch the engine, so deterministic core tests + fixtures are the merge gate per the
   publishing rules.
4. **R3 rider hook:** the same fixture harness is the designated re-evaluation point
   for the parked neutral rate profile (segment-to-segment pacing spread, knob-on vs
   off) — a separate future decision, not part of this change.

## Alternatives considered

- **Generation-time text prefix (unspoken context turn):** rejected for this stage —
  custom/design prompt assembly has no non-spoken text mechanism (only clone ICL
  interleaves reference text); adding one is an engine/prompt change with acoustic
  risk, i.e. stage-2 territory at the earliest.
- **R-pull adjacent-sentence pull-in (implemented, then removed by fixture
  analysis):** pulling a short following sentence into the current segment is dead by
  construction — any sentence whose terminator fits the window is already taken by
  greedy precedence (the last in-window sentence candidate wins), and a terminator
  outside the window violates the token limit. The fixtures-first discipline caught
  this before it shipped as dead code.
- **R-balance same-kind tie-break (considered, folded):** a balance-aware last-wins
  modification duplicates R-tail's effect in the motivating cases; one live rule
  beats three overlapping ones.
- **Global DP segmentation (optimal split):** rejected — whole-text dynamic
  programming changes every boundary on every text for marginal gain over the three
  targeted rules, and makes plans harder to reason about; v2 keeps greedy-with-repair
  semantics that diff cleanly against v1.
