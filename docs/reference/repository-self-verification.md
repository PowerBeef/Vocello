---
status: active
owner: release-qa
summary: How the repository checks itself — the five classes of failure the gates detect, which class each check belongs to, what none of them can see, and how to add a new one.
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

`./scripts/check_project_inputs.sh` is the deterministic gate. It runs on every commit through the
T1 hook and on every push through CI. None of it needs a model, a device, or XCUITest.

| Check | Class | Guards |
| --- | --- | --- |
| `build_output_policy.py validate` | omission + integrity | Every directory under `build/` is governed at any depth; heavy-lane free-space floors |
| `documentation_contract.py` | contradiction | Doc lifecycle groups, link and anchor resolution, public-fact consistency |
| `doc_metadata.py validate` | contradiction + drift + integrity | Per-file status, pinned bodies, derived-fact contradictions in docs, `CLAUDE.md`, and `README.md` |
| `check_surface_coverage.py` | omission | Every enforced gate and contract is named in guidance; the optional-assists section survives |
| `roadmap.py validate` | evidence | Plans and items; every evidence reference resolved against the repository |
| `check_delivery_instructions.py` | contradiction | Delivery-copy tier parity, repeated intensifiers, direction conflicts |
| `model_catalog_contract.py` | integrity | Catalog reproducibility and completeness |
| `vendor_runtime_contract.py` | contradiction | Owned-runtime inventory and facade API baseline |
| `runtime_security_contract.py` | omission | Debug knobs and concurrency exceptions are registered |
| `benchmark_history.py` | integrity | Registry validity and generated index |
| `project_health.py` | contradiction | Generated health summary matches the tree |
| `check_qwen3_backend_only.sh` | omission | MLX is the only backend |
| `check_test_workflows.sh` | omission | One UI stack; no retired harness artifacts |

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
release* fails.

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

- **Behavioral claims.** "The T1 gate takes ~0–45 s" was measured by hand. Nothing re-measures it.
- **Delivery and audio quality.** These need models, seeds, and audio. The text-level contract
  checks what is deterministic about the instruction copy and says nothing about how a take sounds.
- **User-scoped tooling.** Skills and MCP servers live outside the repository, so the optional-assists
  table in `CLAUDE.md` cannot be validated. It is marked unverifiable in place, and the guard
  protects its *presence*, not the accuracy of its rows.
- **Whether a document is simply wrong** about something the machine does not know. Fact scanning
  catches contradictions with derived truth; it cannot check an assertion no fact covers.

## Adding a check

1. **Name the class first.** If the answer is "omission", the check must start from an inventory of
   what should exist, not from what does.
2. **Prove it against a deliberate failure.** Every check here was verified by planting the defect
   it targets — a fabricated commit sha, a nested orphan directory, a stale tier count taken from
   git history — and confirming a red build. A check that has only ever passed has not been tested.
3. **Decide severity from precision**, per the calibration rule above.
4. **Register it everywhere it must appear.** A gate typically spans four places: the script, its
   self-test, `scripts/check_project_inputs.sh`, and `scripts/check_test_workflows.sh`. Contracts
   with an `env` field span the manifest, `scripts/lib/build_paths.sh`, and the test's
   `REQUIRED_EXPORTS`. Landing a partial set leaves the tree green locally while CI fails from a
   clean checkout — that exact split broke `main` on 2026-08-02.
5. **Name it in `CLAUDE.md` or a domain rule**, or `check_surface_coverage.py` will fail —
   deliberately, since a gate no guidance mentions is invisible to anyone reading the docs.

## Related

- [`../../CLAUDE.md`](../../CLAUDE.md) — hard rules and the full list of what the gate runs
- [`macos-release-qa.md`](macos-release-qa.md) — the release-evidence chain, a separate and stricter system
- [`../../.claude/rules/derived-artifacts.md`](../../.claude/rules/derived-artifacts.md) — generated-inventory freshness
- [`privacy-storage.md`](privacy-storage.md) — the build-output ownership table
