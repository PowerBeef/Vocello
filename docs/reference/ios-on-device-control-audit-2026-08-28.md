---
status: historical
owner: ios
summary: Point-in-time implementation and execution checkpoint for the source-bound exhaustive physical-iPhone control, accessibility, model-lifecycle, and pairwise generation audit.
contentDigest: sha256:bdd889c6475858ef51e66ebb5af6206c860777c257469fd7ebc6d31a95ff039e
sourceOfTruth:
  - config/ios-control-audit.json
  - scripts/ios_control_audit.py
  - scripts/ui_test.sh
  - Tests/VocelloiOSUITests/VocelloiOSControlAuditUITests.swift
  - config/roadmap.json
---
# iOS on-device control audit — 2026-08-28

> **Pinned historical pause checkpoint.** This report describes the harness and the retained
> evidence available when device work paused after the ninth performance scenario on 2026-08-28.
> It is not a clean device verdict, App Store authorization, or product-fix authority. Source,
> machine-readable contracts, repository scripts, and
> [`config/roadmap.json`](../../config/roadmap.json) remain authoritative. The report must be
> deliberately re-pinned after the physical campaign adds device findings.

## Executive assessment

The implementation and a substantial first physical-device campaign are complete. Inventory,
stateful controls, external handoffs, direct Clone import, isolated model queue/acceptance, smoke,
and all nine performance scenarios have authoritative retained outcomes. The performance XCTest
suite passed 9/9 and its host gate passed with explicit warnings; its compact record is
`ios-xcui-perf-20260828-172155-32e5b71e` in the PASS-only benchmark registry.

The physical-device audit is **not complete** and no clean verdict is claimed. Accessibility found
a 33.68-point Voices tab target, the model diagnostic reproduced a stale/inaccurate progress bar,
and the pairwise generation campaign stopped without retry on its second take when Qwen3-TTS
reached `maxNewTokens` before EOS. Every unexecuted generation row remains
`SKIPPED_AFTER_FAILURE`; permission mutation that could not be restored remains
`BLOCKED_PRESERVATION_POLICY`. ICA-04 and ICA-05 are therefore in flight rather than complete.

One confirmed harness defect was corrected during implementation: the existing smoke journey
located `iosSettings_openSourceRow` after scrolling to Privacy but attempted to tap the row while it
was still below the floating dock. The shared journey now explicitly reveals the row before tapping.
The corrected physical journey passed. Additional harness defects found while running the campaign
were fixed without converting earlier failed evidence into passes: scenario ownership drift,
History-menu dismissal, failure-observation capture, bounded warning syntax, and offline recovery
of iOS version/build from the retained `.xcresult` for benchmark publication.

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

## Retained physical-device checkpoint

Device work stopped immediately after the ninth performance scenario, as requested. No later
phone command belongs to this checkpoint.

| Phase | Authoritative run | Outcome | Evidence summary |
| --- | --- | --- | --- |
| Inventory | `ios-xcui-control-audit-20260828-163446-1dca3c73` | `PASS` | Tabs, three modes, nine speakers and previews, eight deliveries, ten languages, and custom-tone navigation. |
| Stateful | `ios-xcui-control-audit-20260828-163043-fc88fb36` | `PASS` | Reversible preferences restored, all variations exercised, model rows observed, and global History deletion opened then cancelled. |
| External | `ios-xcui-control-audit-20260828-164234-6509e3fa` | `PASS` with one policy block | Privacy, support, source, attribution, iOS Settings, and Files-cancel handoffs passed. Recording-permission mutation is `BLOCKED_PRESERVATION_POLICY`. |
| Accessibility | `ios-xcui-control-audit-20260828-143417-45184a63` | `PRODUCT_FAIL` | `rootTab_voices` measured 33.6767 points wide at Default size, below the 44-point contract. Later size/surface coverage stopped at that failure. |
| Direct Clone import | `ios-xcui-saved-voice-lifecycle-20260828-143515-86a2b339` | `PASS` | Files import without sidecar, automatic editable transcription, Save Voice, Clone selection/generation, preview/delete, and draft cleanup passed. |
| Model diagnose | `ios-xcui-model-download-20260828-143816-b6a21224` | `PRODUCT_FAIL` | Durable bytes advanced while UI/accessibility progress remained stale; fill mismatch exceeded five points and contrast fell below 3:1. Install still reached Ready and removal completed. |
| Model queue | `ios-xcui-model-download-20260828-144508-d60b4368` | `PASS` | Active/queued requests and independent cancellation converged without cross-model contamination. |
| Model acceptance | `ios-xcui-model-download-20260828-144815-3ba68250` | `PASS` | Governed acceptance path passed; it does not waive the separate diagnose failure. |
| Generation | `ios-xcui-control-audit-20260828-160326-950de77a` | `PRODUCT_FAIL` | `custom-001` passed; `custom-002` reached decoded/published audio then failed at token cap without EOS. No retry or seed substitution occurred. |
| Initial smoke | `ios-xcui-smoke-20260828-164500-f4b01e19` | `BLOCKED_PREREQUISITE` | Canonical clone fixture was absent; Settings accessibility and long-form subtests passed. |
| Fixture restoration | `ios-enroll-voice-20260828-165800-bbb83fe1` | `PASS` | Governed benchmark clone fixture restored; staged inputs removed. |
| Smoke | `ios-xcui-smoke-20260828-165939-d9d57039` | `PASS` | Primary journey, Settings accessibility, long-form, pressure event order, post-pressure generation, crash delta, and retention passed. |
| Performance | `ios-xcui-perf-20260828-172155-32e5b71e` | `PASS` with warnings | Nine of nine XCUITests and the frame gate passed; history publication is now source-bound to retained result identity and does not require the phone. |

Earlier harness-failed attempts remain represented under their original run IDs. They are not
product findings and were not overwritten or merged with the authoritative runs above. Routine
latest-pass cleanup did prune the top-level raw bundles for the inventory, stateful, and model
queue PASS runs before this pause was requested. Their run IDs, verdicts, and bounded device
diagnostic remnants remain, but their `.xcresult` and complete host bundle do not. They must be
recaptured with `--retain-result` before final ICA-04 closure. Every surviving authoritative run
listed above now has an untracked `retention-pin.json`; a cleanup dry-run reports all nine as
`explicitly-pinned`, so routine cleanup cannot prune them. The runner writes that pin before Xcode
starts, and explicit pins take precedence even when older run metadata is malformed or legacy-shaped.

The host-only pause checkpoint passed the complete project-input gate after documentation refresh:
1,223 Python tests, derived artifacts, documentation, roadmap, surface coverage, and the 271-record
benchmark registry were all green. This validates the recorded checkpoint machinery; it does not
convert any device failure, blocked row, or pruned raw bundle into passing evidence.

The generation failure is request-specific and source-bound. Its second row used Built-in/Aiden,
canonical `angry.normal`, Chinese output, Consistent variation, and long Chinese corpus token
`28400002`; generation ID `79DCD038-6FCD-4647-8F4D-AA02ACE8B3EA`, seed
`1051465817978323110`, streaming enabled, retry attempt zero, and operation generation two. The
engine published 293 chunks over about 96.8 seconds with nominal thermal state, about 2.51 GiB peak
footprint, no underruns, and then reported exactly: `Qwen3-TTS reached maxNewTokens before EOS. The
output was discarded.` The visible UI incorrectly described this post-stream failure as inability
to start native generation. The receipt was also cold although the plan expected warm. These are
ICA-06 evidence, not permission to change prompt, seed, sampling, token limit, or retry policy.

The performance run produced these bounded measurements:

| Scenario | Cadence | Hitch time | Max gap | Classification |
| --- | ---: | ---: | ---: | --- |
| Idle baseline | 60 Hz | 0.021 ms/s | 16.75 ms | confirmatory pass |
| Tab navigation | 57.15 Hz | 82.147 ms/s | 103.58 ms | confirmatory pass |
| History scroll | 60 Hz | 76.231 ms/s | 83.35 ms | confirmatory pass |
| Voices scroll | 59.94 Hz | 57.173 ms/s | 62.29 ms | confirmatory pass |
| Settings scroll | 60 Hz | 41.476 ms/s | 50.01 ms | confirmatory pass |
| Composer typing | 60 Hz | 23.947 ms/s | 66.71 ms | confirmatory pass |
| Sheet present/dismiss | 48 Hz | 208.640 ms/s | 160.89 ms | confirmatory, cadence/hitch warnings |
| Player scrub | 34.4 Hz | 386.149 ms/s | 211.53 ms | exploratory cadence warning |
| Generation active | 60 Hz | 78.714 ms/s | 518.34 ms | exploratory pass |

XCTest also reported a user-interactive thread waiting on Default QoS at
`LiveStreamingPlaybackEngine.swift:147`. ICA-08 owns investigation. The warning-range grammar and
offline result-owned OS identity defects were harness defects and are fixed in the current working
tree; the retained run now validates in the 271-record history.

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
| ICA-P01 / ICA-06 | P1 | Product | device-reproduced | The second pairwise row published 293 chunks then reached max tokens without EOS; UI misclassified it as startup failure, and its observed receipt was cold instead of planned warm. | Localize first divergence, preserve exact request/seed/prompt/sampling/QC, correct terminal mapping, add deterministic coverage, and pass the affected row once without retry before restarting the matrix. |
| ICA-P02 / MD-3 | P1 | Product | device-reproduced | Durable model bytes advanced while the visible/accessibility fraction froze; rendered width diverged by more than five points and contrast fell below 3:1. | Causal fix plus two consecutive diagnose passes and one acceptance pass under the unchanged MD-3 gate. |
| ICA-P03 / ICA-07 | P2 | Product | device-reproduced | `rootTab_voices` exposed a 33.6767-point width at Default instead of a 44-point activation target. | Geometry regression coverage and one clean four-size physical-device accessibility run. |
| ICA-P04 / ICA-08 | P2 | Product/performance | device-reproduced | Sheet presentation crossed warn-only cadence/hitch ceilings; player scrub recorded an exploratory cadence warning; XCTest reported playback priority inversion. | Explain ownership, fix causal source where applicable, then repeat the nine-scenario lane without weakening thresholds or classification. |
| ICA-H01 | P2 | Harness | source- and fixture-proven | Settings reachability, scenario ownership, History dismissal, product-failure capture, warning-range parsing, and delayed iOS history publication each had a harness defect. | Current targeted tests and corrected live journeys pass; full deterministic checkpoint remains required before commit. |
| ICA-B01 | P2 | Preservation | device-reproduced | Microphone/speech permission mutation could not be proven autonomously restorable. | Keep `BLOCKED_PRESERVATION_POLICY` until a reliable app-specific restore route exists; manual acceptance remains separate. |
| ICA-R01 | P2 | Prerequisite | device-reproduced | Initial smoke lacked the canonical clone fixture. | Governed restoration succeeded and a separate smoke run passed; retain the first run as blocked evidence. |
| ICA-PENDING | — | Coverage | device-deferred | The generation rows after `custom-002`, full four-size accessibility walk, actual VoiceOver speech/rotor behavior, conditional Update/Repair states, permission denial/recovery, three-repeat stress/restoration, and exact signed-candidate acceptance remain incomplete. | Resume only after the corresponding causal fixes and prerequisites; do not merge evidence across a changed source identity. |

Product remediation remains outside this audit and requires a separate maintainer request. A clean
conclusion is prohibited while the required rows above fail, are skipped, or remain blocked.

## Safe resume checkpoint

Do not repeat preserved successful phases merely to obtain a green aggregate. Inventory, stateful,
and model queue require one evidence-recapture pass because their raw bundles were pruned; this is
an evidence-retention requirement, not a change to their recorded functional result. The next
device window begins only after the relevant source remediation and deterministic checks:

1. ICA-06: localize and fix the exact non-EOS terminal path and false UI classification; then run
   the affected generation row as a focused physical-device proof. Because a source fix changes
   the frozen identity, generate a new campaign rather than using the old resume token.
2. ICA-07: fix the root-tab activation geometry and repeat the accessibility scenario across
   Default, AX-L, AX-XXXL, and pseudo-AX-XXXL.
3. MD-3: fix the progress presentation divergence and complete two fresh diagnose passes followed
   by one acceptance pass. Queue need not repeat unless the causal change touches queue semantics.
4. Recapture inventory, stateful, and model queue with `--retain-result` so final closure has their
   complete `.xcresult`, observations, and host artifacts.
5. Continue the remaining Built-in, Voice Design, and Clone generation matrix under one new frozen
   source identity. Do not retry or replace a failing row.
6. Complete actual VoiceOver/rotor review, any authorized permission denial/recovery, conditional
   Update/Repair states if they arise naturally, three-repeat stress, and final restoration proof.
7. Repeat the nine-scenario performance lane only if ICA-08 changes performance-sensitive source;
   otherwise the retained 9/9 record remains the checkpoint evidence.
8. ASR-12 still requires the exact signed candidate and cannot be closed by these development
   builds.

Canonical entry points remain:

```sh
scripts/ios_device.sh preflight
scripts/ui_test.sh ios control-audit --scenario inventory --retain-result
scripts/ui_test.sh ios control-audit --scenario stateful --retain-result
scripts/ui_test.sh ios control-audit --scenario accessibility --retain-result
scripts/ui_test.sh ios model-download --scenario diagnose --retain-result
scripts/ui_test.sh ios model-download --scenario queue --retain-result
scripts/ui_test.sh ios model-download --scenario acceptance --retain-result
scripts/ui_test.sh ios control-audit --scenario generation --retain-result
```

Use `--resume` only when source, app build, device, plan, and retained run identities are unchanged.
It never merges a prior failure into a later pass and is invalid after any product fix.

## Roadmap authority

The authoritative plan is `ios-control-audit-2026-08`:

- ICA-01: source inventory — done.
- ICA-02: resumable physical-device harness — done in source.
- ICA-03: pairwise generation plan — done.
- ICA-04: live physical-device campaign — in flight at the post-performance pause.
- ICA-05: evidence-linked findings checkpoint — in flight; this report is the safe-resume re-pin.
- ICA-06: long-Chinese non-EOS generation and terminal classification — planned.
- ICA-07: Voices root-tab 44-point target — planned.
- ICA-08: cadence warnings and playback priority inversion — planned.

Related work remains with its existing authority: AV-09 owns XCUITest bootstrap reliability,
ASR-12 owns exact signed-candidate acceptance, ICI-4 is closed by the retained direct-import and
smoke runs, MD-3 is reopened for the fresh model-progress regression, and ISR-04/ISR-06 own startup
reliability.
