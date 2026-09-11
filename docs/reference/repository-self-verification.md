---
status: active
owner: release-qa
reviewed: 2026-09-06
summary: Verification boundaries and evidence-led replacement of tests, harnesses and gates; prove detection, measure cost, retain necessary compatibility and retire redundant execution paths.
sourceOfTruth:
  - scripts/check_project_inputs.sh
  - scripts/check_surface_coverage.py
  - scripts/doc_metadata.py
  - scripts/roadmap.py
  - scripts/build_output_policy.py
appliesTo:
  - release-qa
---

# Repository self-verification

Vocello checks a great deal about itself before every commit. This document explains **what kind of
wrong each check can find**, because that turns out to matter more than the list of checks: on
2026-08-02 a stale preset count, an undocumented set of gates, an orphaned 3.4 GB build directory,
and a security workflow that never completed were all live at once, and every gate passed. They
were the same class of failure, and no check in the repository could see that class at all.

Architecture and gate tiers live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and the root
[`CLAUDE.md`](../../CLAUDE.md). This file is about the verification system itself.

The project-input gate also executes localization, entitlement, support-contact and deterministic
attribution-manifest contracts. `scripts/python_test_contract.py` discovers Python tests, rejects
zero-test modules and checks runner coverage; use its output and the generated project health for
current counts. Inventory completeness establishes discovery, not behavioral correctness.

## Replace and retire tests and harnesses

This procedure applies to **all** tests, fixtures, evaluators, benchmarks, runners and release
validators, not only Audio QC. Existing sources/contracts remain the execution authority until a
coherent correction lands; that hierarchy does not establish scientific or behavioral validity.
An inherited implementation is not a gold standard. A replacement earns no exemption from the
same scrutiny because it is newer or written with a more capable agent.

Use the existing owning roadmap item and checkpoint, not a new review registry or gate:

1. **State the claim and risk.** Identify the user-visible behavior or invariant the check protects,
   its real callers and the specific defect, false verdict, duplicate work or measured cost that
   motivates change. A version suffix or old test framework alone is not a defect. Prefer
   release-blocking and touched paths over a repository-wide rewrite before shipping.
2. **Establish an independent expectation.** Use an external specification, mathematical reference,
   observable product behavior, independently labeled data or a controlled failure schedule as
   appropriate. Do not derive both expected and actual values from the same helper. Include known
   good, known bad and boundary cases; demonstrate that the check detects the relevant defect.
   Snapshots and historical equality are compatibility evidence, not correctness by themselves.
3. **Exercise the connection.** Test real request builders, adapters and consumers together where
   an integration claim crosses them. Mocks isolate failure handling; a mock-only pass cannot
   qualify the production boundary or packaged product. Classify missing/invalid observations as
   evidence gaps, not clean passes or unsupported product failures.
4. **Choose a finite disposition.** Keep a justified check; repair a demonstrated flaw; consolidate
   duplicate responsibility; or retire a redundant/obsolete check. Before replacement, state its
   acceptance cases, supported consumers, compatibility need, cost budget and retirement trigger.
   Distinguish measurement validity from the calibration needed for any resulting product verdict.
   Unsubstantiated thresholds are findings to resolve, not values to preserve merely to stay green.
5. **Qualify and switch.** Compare against the independent expectation, not blind agreement with
   the predecessor. Measure representative runtime, peak memory, flakiness and false verdicts in
   proportion to risk. On the 8 GB Mac keep heavy work serial. A bounded comparison may use both
   paths temporarily; record the exit condition instead of accumulating permanent challenger lanes.
6. **Retire execution, preserve meaning.** Once criteria pass, make the replacement the normal route
   for all supported callers and remove obsolete writers, runners, flags and duplicate assertions.
   Retain a reader/migration fixture only for identified persisted data, public clients or retained
   evidence; an old executable path additionally needs a concrete reproduction requirement and a
   named review/removal milestone. Preserve original artifacts and append corrected interpretations
   with provenance when a previous evaluator was wrong. Never rewrite an old failure into a pass.

For a replacement, record **claim → evidence → replacement → remaining consumers → retirement
condition** briefly in the existing item. A named ongoing archival requirement may justify a small
reader; it does not justify keeping the old generator/scorer as a competing default. Do not call a
migration complete while normal callers still depend on the obsolete path. No new project-wide
inventory, automatic mutation campaign or recurring approval ritual is required.

| Surface | Evidence required for a meaningful change |
| --- | --- |
| Unit, integration, persistence and CLI tests | Intended behavior plus failure cases; real producer/consumer compatibility, cancellation/ownership and durable bytes where applicable |
| Native UI and system-handoff harnesses | Genuine visible state and independently captured outcomes; failed/missing observations and cleanup remain explicit; XCUITest is still the sole app UI driver |
| Audio/language/delivery evaluators | Numerical references and adversarial audio for measurements; representative independent reference calibration for decisions; frozen automated holdouts for named metric claims. Listening is optional, and machine scores are not listener-proven semantic quality. |
| Performance, memory and benchmark tools | Correct process/lifecycle attribution, representative inputs, observer overhead and measured variance; historical numbers are comparisons, not universal limits |
| Build, CI, security, packaging and release validators | Positive and deliberate-negative fixtures at the actual execution boundary; justified applicability, identity, privacy and provenance checks |

Version a persisted/public wire format, cache identity or changed measurement meaning when needed
to prevent silent reinterpretation. Ordinary internal refactors should replace the implementation
in place. Do not rename frameworks or create V2/V3 pipelines just to signal modernization.
Fewer tests or gates can be better when unique risk coverage is preserved and verified; counts,
coverage percentages and inherited health scores are not substitutes for defect detection.

This policy does not silently relax user-data protection, privacy, source binding, fixed inputs,
no-retry rules or the maintainer's 201-take prerequisite. A flawed gate can be corrected with a
scoped source/contract/test migration, including evidence that valid cases pass and invalid ones
remain rejected. Until then its unresolved claim blocks a clean verdict; neither a waiver nor a
known-wrong baseline is a substitute for a demonstrated correction. Review changes at coherent
checkpoints, never by changing a frozen campaign or reinterpreting its original result files.

## The five classes

Every check answers a different question. Placing a new check in the wrong class is the usual way
to build something that passes while the problem persists.

| Class | The question | Needs | Example |
| --- | --- | --- | --- |
| **Contradiction** | Does prose disagree with the code? | a claim to test against | `doc_metadata.py` scanning docs against facts derived from `EmotionPreset.swift` |
| **Drift** | Has the source moved since the doc was written? | a declared binding | `sourceOfTruth` in document frontmatter, compared by commit time |
| **Omission** | Does something exist that nobody declared? | an inventory of what *should* be declared | `check_surface_coverage.py`; the deep unowned-root walk in `build_output_policy.py` |
| **Integrity** | Did something change that must not? | a pinned digest | `contentDigest` on `historical` and `superseded` documents |
| **Evidence** | Is this claim supported by an artifact that exists? | resolvable references | `roadmap.py` resolving `commit:`, `benchmark:`, `doc:`, `file:` |

**Omission is the class that was missing**, and its absence is not obvious, because contradiction
and drift checks both need a *claim* to work against. A gate script nobody documented makes no
claim. An ad hoc build directory nobody declared makes no claim. There is nothing to contradict and
nothing to drift from, so a repository can be exhaustively verified and still full of undeclared
things. Every omission check therefore starts from an inventory of what ought to exist — the set of
gates the build actually runs, the set of governed output paths — and reports the difference.

## What runs, and in which class

`./scripts/check_project_inputs.sh` is the complete deterministic gate used by CI/release. The T1
hook requires the path-aware local checkpoint's exact-tree receipt; it blocks rather than launching
long checks itself. See [development-workflow.md](development-workflow.md).
None of these deterministic checks needs a model, a device, or XCUITest.

| Check | Class | Guards |
| --- | --- | --- |
| `build_output_policy.py validate` | omission + integrity | Every directory under `build/` is governed at any depth; heavy-lane free-space floors |
| `localization_contract.py validate` | omission + contradiction | String Catalog settings/context/plurals, typed dynamic presentation use, pseudo-localization coverage, and content-addressed rejection of new direct UI literals |
| `documentation_contract.py` | contradiction | Frontmatter-resolved lifecycle inventory, link/anchor resolution and public-fact consistency; groups are taxonomy/legacy defaults, not a second status |
| `doc_metadata.py validate` | contradiction + drift + integrity | Per-file status, pinned bodies, derived-fact contradictions in docs, `CLAUDE.md`, and `README.md` |
| `check_surface_coverage.py` | omission | Every enforced gate and contract is named in guidance; the optional-assists section survives |
| `roadmap.py validate` | evidence + contradiction | Plans and items; every evidence reference resolved against the repository; an optional primary execution plan must exist and remain active |
| `check_delivery_instructions.py` | contradiction | Delivery-copy tier parity, repeated intensifiers, direction conflicts |
| `prepare_delivery_compact_model_config.py --validate-only` | omission + integrity | Experimental local evaluator candidates, exact source/weight/runtime pins, research-only boundary, and untouched-holdout adoption gates |
| `model_catalog_contract.py` | integrity | Catalog reproducibility and completeness |
| `vendor_runtime_contract.py` | contradiction | Owned-runtime inventory and facade API baseline |
| `runtime_security_contract.py` | omission | Debug knobs and concurrency exceptions are registered |
| `benchmark_history.py` | integrity | Registry validity and generated index |
| `project_health.py` | contradiction | Generated health summary matches the tree |
| `check_qwen3_backend_only.sh` | omission | MLX is the only backend |
| `repo_invariants.sh` | omission | Product invariants expressed as exact greps |

## Three patterns worth reusing

### Derive facts; never hand-maintain them

`config/derived-doc-facts.json` is generated from code and contracts — preset count and intensity
tiers from `EmotionPreset.swift`, speaker count from the model contract, release version from
`project.yml`, canonical benchmark chip from the profile flagged `canonical` in
`benchmarks/hardware-profiles.json`. A hand-typed facts file is simply one more document that goes
stale, and it fails silently because nothing checks the checker.

Deny patterns are generated from the derived value, so they cannot rot either: if the tier count
ever becomes three, the pattern that rejects "10 × N where N is not 3" follows automatically. They
also target **claim forms rather than bare values** — release notes legitimately name old versions,
so `v2.3.0 was cut 2026-07-31` passes, while asserting that a superseded version *is the current
release* fails. Matches embedded in a longer multiplication chain are likewise excluded
(2026-08-05): a codec guide's upsample arithmetic (`2 × 2 × 8 × …`) is factor math, not a
preset-by-tier claim.

That rule is strict enough to have caught this document: an earlier draft spelled the failing form
out literally as an example, and the gate rejected it. Illustrating a banned claim requires
describing it rather than writing it.

### Acknowledge open findings; never suppress them

Some findings are real but their *resolution* is unknown. Failing the build forces a blind fix;
silencing them loses the finding. Both
[`config/delivery-instruction-contract.json`](../../config/delivery-instruction-contract.json) and
[`config/surface-coverage-exemptions.json`](../../config/surface-coverage-exemptions.json) take the
same shape: a listed finding is known-open and passes, a new one fails, **and a listed finding that
no longer occurs also fails**. That last rule is what stops the list becoming a graveyard. Each
entry carries a reason and, where applicable, how it gets settled.

### Calibrate severity to precision

A check that fires spuriously teaches people to bypass it, which costs more than the drift it
catches. So precision decides severity, not importance:

- **Fail** on precise checks — digest mismatches, unresolvable evidence, tier-parity defects,
  derived-fact contradictions.
- **Warn** on inherently noisy ones — `sourceOfTruth` drift trips on *any* edit to a declared
  source, including edits that cannot affect the prose. On its first run it produced one true
  positive and one false; roughly half precision is a useful triage signal and would be a miserable
  blocker.

## What none of this verifies

Stating the boundary honestly matters more than the coverage table, because the gaps are where
confidence becomes misplaced.

- **Behavioral claims.** Timings in [`development-workflow.md`](development-workflow.md) were
  measured on one host. Gates protect behavior and cache routing, not a permanent wall-clock SLA.
- **Delivery and audio quality.** These need models, seeds, and audio. The text-level contract
  checks what is deterministic about the instruction copy and says nothing about how a take sounds.
- **User-scoped tooling.** Repository-owned Claude Code configuration under `.claude/` is covered by
  the hook behaviour tests (`scripts/tests/test_claude_hooks.py`) and the Simulator grep in
  `repo_invariants.sh`. User-scoped skills, plugins and MCP servers still live
  outside the repository, so the tooling table in `CLAUDE.md` is only partly verifiable; the guard
  protects its *presence* and its optional framing, not the accuracy of user-scoped rows.
- **Whether a document is simply wrong** about something the machine does not know. Fact scanning
  catches contradictions with derived truth; it cannot check an assertion no fact covers.

## Adding a check

1. **Name the class first.** If the answer is "omission", the check must start from an inventory of
   what should exist, not from what does.
2. **Prove it against a deliberate failure.** Every check here was verified by planting the defect
   it targets — a fabricated commit sha, a nested orphan directory, a stale tier count taken from
   git history — and confirming a red build. A check that has only ever passed has not been tested.
3. **Decide severity from precision**, per the calibration rule above.
4. **Register it once at its execution boundary.** A gate spans its script, its self-test and
   `scripts/check_project_inputs.sh`; `scripts/repo_invariants.sh` holds the exact greps and
   asserts nothing about the text of other scripts or workflows. Contracts
   with an `env` field span the manifest, `scripts/lib/build_paths.sh`, and the test's
   `REQUIRED_EXPORTS`. Landing a partial set leaves the tree green locally while CI fails from a
   clean checkout — that exact split broke `main` on 2026-08-02.
5. **Name it in `CLAUDE.md` or a domain rule**, or `check_surface_coverage.py` will fail —
   deliberately, since a gate no guidance mentions is invisible to anyone reading the docs.

`tree_fingerprint.py` keeps the full-tree identity device-lane evidence binds to (HEAD, tracked
content and non-ignored paths/bytes). There is no local commit receipt: `scripts/dev.sh check` is
advisory and CI on `main` is the gate.
It can satisfy the commit hook but never stand in for CI, candidate or promotion evidence.

The root Swift dependency watch follows this pattern: `swift_dependency_updates.py` validates exact
pin agreement without network access in the deterministic gate, while its scheduled workflow uses
release/advisory data only to produce a read-only coordinated review proposal. Availability never
authorizes a pin change.

## Related

- [`../../CLAUDE.md`](../../CLAUDE.md) — hard invariants and domain routing; the release/QA rule owns the enforced-surface catalog
- [`macos-release-qa.md`](macos-release-qa.md) — the release-evidence chain, a separate and stricter system
- [`../../.claude/rules/derived-artifacts.md`](../../.claude/rules/derived-artifacts.md) — generated-inventory freshness
- [`privacy-storage.md`](privacy-storage.md) — the build-output ownership table
