---
status: historical
owner: ios
summary: Point-in-time implementation and execution checkpoint for the source-bound exhaustive physical-iPhone control, accessibility, model-lifecycle, and pairwise generation audit.
contentDigest: sha256:9c2359202b8e343cf406e05196cb7fd41af49f4d91e3f462f645a08ae46040fa
sourceOfTruth:
  - config/ios-control-audit.json
  - scripts/ios_control_audit.py
  - scripts/ui_test.sh
  - Tests/VocelloiOSUITests/VocelloiOSControlAuditUITests.swift
  - config/roadmap.json
---
# iOS on-device control audit — 2026-08-28

> **Pinned historical implementation checkpoint.** This report describes the harness and the
> evidence available on 2026-08-28. It is not a clean device verdict, App Store authorization, or
> product-fix authority. Source, machine-readable contracts, repository scripts, and
> [`config/roadmap.json`](../../config/roadmap.json) remain authoritative. The report must be
> deliberately re-pinned after the physical campaign adds device findings.

## Executive assessment

The phone-independent implementation is complete. Vocello now has one source-bound
`control-audit` lane layered over the existing physical-device XCUITest runner. It inventories the
production control surface, freezes the complete source-tree identity, generates a deterministic
all-pairs generation campaign, records terminal outcomes without automatic retries, and composes
untracked observations without converting missing or blocked rows into passes.

The physical-device audit is **not complete**. No product defect, accessibility pass, generation
pass, model-lifecycle pass, or clean restoration conclusion is claimed by this checkpoint. The
paired iPhone campaign remains ICA-04, and the evidence-linked device report remains ICA-05.

One confirmed harness defect was corrected during implementation: the existing smoke journey
located `iosSettings_openSourceRow` after scrolling to Privacy but attempted to tap the row while it
was still below the floating dock. The shared journey now explicitly reveals the row before tapping.
This remains a harness reachability correction unless the corrected physical journey reproduces a
product failure.

## Machine-readable inventory

[`config/ios-control-audit.json`](../../config/ios-control-audit.json) and its schema define the
auditable surface. The validator currently accounts for:

| Layer | Count | Authority |
| --- | ---: | --- |
| Production Swift files containing interactive constructs | 21 | `Sources/iOS/**/*.swift` source scan |
| Interactive source occurrences | 76 | `Button`, `Toggle`, `Picker`, navigation/link, editor, gesture, importer, dialog, and alert scan |
| Governed control families | 24 | `controlFamilies` contract |
| Expanded inventory rows | 60 | Checked-in dynamic catalogs |
| Built-in speakers | 9 | `qwenvoice_contract.json` |
| Delivery presets | 8 | `EmotionPreset.all` |
| Selectable output languages | 10 | `Qwen3SupportedLanguage.selectableCases` |
| Variation profiles | 3 | `Qwen3SamplingVariation.allCases` |
| iOS model identities | 3 | Production model catalog |

Every family records its screen, prerequisite, accessibility role, action, expected result,
expected label/value/hint behavior, minimum target geometry, mutation class, scenario owner, and
availability. A new interactive Swift file without a coverage policy, an unresolved source token,
or a required family missing from the XCUITest owner fails deterministic validation.

The contract deliberately distinguishes read-only, reversible, test-owned destructive,
confirm-only, isolated-model, and external-system mutations. Conditional controls are not silently
removed when their state is unavailable.

## Generation campaign

The plan generator uses deterministic greedy set cover over every pair of applicable dimensions.
Its current immutable plan has 201 takes:

| Mode | Rows | Dimensions |
| --- | ---: | --- |
| Built-in Voice | 91 | 9 speakers × 8 deliveries × 10 languages × 3 variations × 2 lengths |
| Voice Design | 80 | 2 brief types × 8 deliveries × 10 languages × 3 variations × 2 lengths |
| Voice Cloning | 30 | 2 run-owned reference types × 10 languages × 3 variations × 2 lengths |

The 201 rows are not a full Cartesian product. They are the deterministic covering array needed to
place every pair of values together at least once. Tests reconstruct the complete pair requirement
set and prove that no pair or individual option is missing.

The ordinary transcript-backed and direct-import Clone references do not expose a delivery-preset
control because Qwen Base cloning has no instruction channel. The matrix therefore does not invent
an eight-preset Clone dimension. Curated voice-bank delivery rows remain a separate conditional
control surface and are exercised only when a governed run-owned bank prerequisite exists.

Each mode begins with an expected cold sentinel; remaining rows are expected warm. The harness does
not inject a seed or use a hidden launch override. It observes the engine-generated seed from the
first successful take in each mode, pins that exact seed through the visible History action, and
requires every remaining take in the mode to expose the same visible seed and matching engine
receipt. A successful campaign removes only audit-created pins; a failed campaign retains them for
source- and plan-bound resume. Pre-existing user pins are preserved. Language-matched short and long scripts live in the
privacy-safe [`config/ios-control-audit-corpus.json`](../../config/ios-control-audit-corpus.json).
Each rendered script includes a unique search token, allowing XCUITest to locate and delete
the exact run-owned History row without clearing or guessing at unrelated user data.

The live validator must correlate visible selections, engine receipts, decoded/published audio,
mandatory PCM/cadence/language QC, History, player actions, crash state, and cleanup. A failed take
is represented once; there is no retry, regeneration with another seed, or row substitution.

## Scenarios and mutation boundary

The canonical entry points are:

```sh
scripts/ui_test.sh ios control-audit --scenario inventory
scripts/ui_test.sh ios control-audit --scenario stateful
scripts/ui_test.sh ios control-audit --scenario external
scripts/ui_test.sh ios control-audit --scenario accessibility
scripts/ui_test.sh ios control-audit --scenario generation
scripts/ui_test.sh ios control-audit --scenario all
scripts/ui_test.sh ios control-audit --scenario all --resume <run-id>
```

The runner validates the inventory before contacting a phone, captures the complete dirty-tree
fingerprint, generates an untracked plan, and rejects resume when the prior run, source, or plan
digest differs. Xcode receives only test-runner configuration; no app launch environment seeds
product state or adds hidden UI.

The test exercises tabs, modes, speakers, previews, deliveries, languages, variations, custom tone,
settings preferences, models, History confirmation, external handoffs, attributions, Files cancel,
layout sizes, and planned generations through visible production controls. Reversible preferences
are read, changed, and restored through those same controls. Before generation it snapshots the
three mode scripts, Built-in speaker/delivery/language, Voice Design brief/delivery/language, Clone
reference/language, current mode, variation, and per-mode seed-pin state in test-process memory.
Cleanup restores them through production controls. When an originally empty Clone reference must
be restored, deletion first selects the run-owned imported reference and relies on the ordinary
saved-voice deletion path to clear the draft; no hidden reset hook is used.

Operations that could alter unrelated data remain bounded:

- Global History deletion is opened and cancelled. It is classified
  `BLOCKED_PRESERVATION_POLICY`, never `PASS`.
- Permission mutation is refused unless the exact app-specific state can be restored. A refusal is
  retained as `BLOCKED_PRESERVATION_POLICY`.
- Saved-voice import, transcription, Clone handoff, and deletion remain owned by the explicit
  `saved-voice-lifecycle` phase and its run-owned fixture.
- Model install/cancel/retry/remove remains owned by the established isolated model-management root;
  canonical model storage is not used for destructive coverage.
- Conditional Update Available or Repair Needed rows are reported unavailable when they do not
  arise naturally; state is never fabricated.

## Evidence and classification

Every raw artifact stays below `build/artifacts/ui-tests/ios/<run-id>/` and remains untracked. A run
retains its plan, JSONL control observations, summary, screenshots, `.xcresult`, console log, crash
delta, model/generation correlations, and cleanup proof. Failed `.xcresult` bundles are never
overwritten by an automatic retry.

The only terminal classifications are:

- `PASS`
- `PRODUCT_FAIL`
- `HARNESS_FAIL`
- `INFRASTRUCTURE_FAIL`
- `BLOCKED_PREREQUISITE`
- `BLOCKED_PRESERVATION_POLICY`
- `NOT_APPLICABLE`
- `SKIPPED_AFTER_FAILURE`

The composer rejects observations from another run or source, rejects unknown classifications, and
emits `SKIPPED_AFTER_FAILURE` for an expected row with no observation. A completed campaign may have
explicit preservation limitations, but it cannot be described as clean when a required row fails,
is skipped, or remains unexplained.

## Accessibility scope

The XCUITest scenario launches Default, AX-L, AX-XXXL, and the existing pseudo-AX-XXXL
configuration. It checks accessible labels, values where applicable, minimum 44-point targets,
bounds, major-surface tree audits, and retained screenshots. Progress identity remains tied to the
same presentation value used by the model-management diagnostics.

Public XCUITest cannot establish actual VoiceOver speech output, rotor navigation, or every
system-global state transition while also proving restoration. Those boundaries must be reported as
manual/device gaps, not represented as automated passes.

## Current findings

| ID | Severity | Kind | Confidence | Finding | Closure |
| --- | --- | --- | --- | --- | --- |
| ICA-H01 | P2 | Harness | source-proven | Settings smoke attempted to tap the Open Source row before scrolling it above the floating dock. | Corrected journey must pass once on the paired physical iPhone. |
| ICA-PENDING | — | Prerequisite | device-deferred | No live control, accessibility, generation, isolated-model, stress, or restoration campaign has run against this implementation. | Complete ICA-04 and re-pin this report from retained run evidence. |

There are no confirmed product findings in this checkpoint. That absence means “not executed,” not
“no defects found.” Product remediation is outside this audit and requires a separate maintainer
request after a source- or device-reproduced root cause exists.

## Physical execution order

When the paired iPhone is unlocked, charging, on stable Wi-Fi, and has adequate free space:

```sh
scripts/ios_device.sh preflight
scripts/ui_test.sh ios control-audit --scenario inventory
scripts/ui_test.sh ios control-audit --scenario stateful
scripts/ui_test.sh ios control-audit --scenario external
scripts/ui_test.sh ios control-audit --scenario accessibility
scripts/ui_test.sh ios saved-voice-lifecycle
scripts/ui_test.sh ios model-download --scenario diagnose
scripts/ui_test.sh ios model-download --scenario queue
scripts/ui_test.sh ios model-download --scenario acceptance
scripts/ui_test.sh ios control-audit --scenario generation
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios perf
```

The campaign is expected to require multiple phone windows. Resume is permitted only across an
identical source and plan; it is not permission to merge a prior failure into a later pass.

## Roadmap authority

The authoritative plan is `ios-control-audit-2026-08`:

- ICA-01: source inventory — done.
- ICA-02: resumable physical-device harness — done in source.
- ICA-03: pairwise generation plan — done.
- ICA-04: live physical-device campaign — planned.
- ICA-05: evidence-linked device findings checkpoint — planned.

Related work remains with its existing authority: AV-09 owns XCUITest bootstrap reliability,
ASR-12 owns exact signed-candidate acceptance, ICI-4 owns direct Clone import acceptance, MD-3 owns
isolated model-management closure, and ISR-04/ISR-06 own startup reliability.
