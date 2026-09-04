---
status: active
owner: release-qa
summary: Finite release-first execution order for iOS, macOS, and the downloadable CLI; maps the September audit to existing defect authorities.
sourceOfTruth:
  - config/roadmap.json
  - config/quality-promotion-contract.json
  - config/release-evidence-contract.json
  - project.yml
---
# Release-first execution

The maintainer adopted this programme on 2026-09-04. The external September 3 audit
reviewed `86696036`; the initial implementation baseline is clean `main` at `2f392484`.
Its readiness score is advisory, not a release gate. Source and the roadmap remain authoritative.

`config/roadmap.json` designates **`release-first-3-0-2026-09` as `primaryPlan`**. Its
`RF-01` through `RF-12` milestones are the execution roadmap from now on, in the order below.
Both `roadmap.py status` and the generated `docs/ROADMAP.md` present it first. Older plans retain
technical defect ownership, evidence and deferred backlog; their active status does not independently
schedule another workstream. RF milestone completion never closes a referenced defect implicitly:
for example RF-03 source proof does not close F-15's packaged-candidate acceptance.

## Decisions and order

Keep and repair long-form and segment regeneration. Complete the 201-take iOS campaign.
Qualify macOS and a separately downloadable, signed CLI without waiting for iOS-only gates.
The maintainer-selected next release is **3.0.0**, marking the new phase of Vocello across
iOS, macOS, and the downloadable CLI. This supersedes the original 2.5.0 planning default.
Reconcile the App Store Connect version and select an unused build number through the existing
collision preflight before freezing. The September 4 source-preparation checkpoint sets
`project.yml` to 3.0.0/build 24 and regenerates the project. A complete read-only account preflight
found zero matching builds. This is not a reservation; repeat it immediately before archive.
The live App Store version still requires separately authorized reconciliation.
`candidateRelease` in the public-facts contract is version/tag-matched, explicitly unpublished,
and strictly newer than `stableMacRelease`; public links and stable-version fact scans do not
advertise the candidate. Remove the candidate declaration when an authorized publication moves
the stable release forward. Build numbers remain solely owned by `project.yml`.
Candidate verification is distinct from implementation completion and from explicit publication
or submission authorization. No release, account mutation, or legal conclusion follows from a
source checkpoint.

1. **RF-01:** Reconcile retained evidence and map findings below.
2. **RF-02:** Start bounded read-only account/signing inspection and the qualified-decision packet.
3. **RF-03:** Fix macOS Design request preservation (F-15).
4. **RF-04:** Repair shared long-form durability and platform integration (F-16).
5. **RF-05:** Expose History enqueue failures without losing playable output (F-06).
6. **RF-06:** Localize remaining natural-text Custom and French Design failures (ICA-15, VLR-07).
7. **RF-07:** Repair only observation durability, focus, terminal bookkeeping, and bounded shards needed
   to finish the existing campaign (ICA-18, AV-09).
8. **RF-08:** Package and verify the optimized downloadable CLI (F-17).
9. **RF-09:** Complete deterministic checks, collision validation, exact-SHA CI, and candidate freeze.
10. **RF-10:** Qualify desktop/CLI packages and applicable promotion lanes (F-05, F-17).
11. **RF-11:** Complete the frozen iPhone campaign with every attempt represented (ICA-04/ICA-05).
12. **RF-12:** Finish distribution-candidate acceptance, account/rights decisions, and submission preparation
    (ASR-02, ASR-04 through ASR-12).

Use focused verification after each coherent change and one complete checkpoint before freeze.
While a campaign is frozen, keep resumable progress in its pinned, untracked run artifacts; do not
edit unrelated source or documentation and then bypass the full-tree identity check. Incorporate
results in the roadmap at the next source checkpoint. A changed product needs fresh applicable
acceptance; old results remain historical evidence, not replacement candidate proof.

## Audit finding disposition

| External finding | Grounded disposition and authority |
| --- | --- |
| VRA-001 | Confirmed incomplete macOS Design draft capture: F-15. |
| VRA-002 | Premature replacement History publication: F-16. |
| VRA-003 | Silent manifest serialization/write failure: F-16. |
| VRA-004 | Rejected segment/joined artifact cleanup gaps: F-16. |
| VRA-005 | iOS resumed progress counts reused segments twice: F-16. |
| VRA-006 | Segment versus project terminal ownership must be explicit: F-16; preserve F-08. |
| VRA-007 | Unchanged segment QC/provenance must survive regeneration: F-16. |
| VRA-008 | Outbox enqueue failure has no durable entry to recover: reopen F-06. |
| VRA-009 | Sampled-output failures remain; natural-text custom-008 is separate: ICA-15. |
| VRA-010 | Marker-removal experiment completed; schema-v3 metadata ownership implemented: ICA-18. Retain original numeric failures. |
| VRA-011 | Full-tree churn is real; freeze source rather than redesign evidence authority this release: ICA-04/ICA-18. |
| VRA-012 | Add behavioral tests at changed boundaries; no mass source-contract rewrite: F-15/F-16/F-06. |
| VRA-013 | Shared iOS policy assertions already execute on macOS; duplicate iOS bundle is compile-only: F-03 remains closed. |
| VRA-014 | Third-party processing/disclosure requires qualified review: ASR-02. |
| VRA-015 | Attribution implementation exists; qualified asset rights remain: ASR-04. |
| VRA-016 | Distribution identity/profile/archive must be freshly verified: ASR-10. |
| VRA-017 | Current qualified regional host evidence required: ASR-09. |
| VRA-018 | Exact candidate, screenshots, and reviewer journey: ASR-05/ASR-12. |
| VRA-019 | Broad engine decomposition deferred unless causally necessary; no reopening F-09. |
| VRA-020 | Generation continuation is session-scoped; durability repair does not add relaunch continuation: F-16. |
| VRA-021 | Milestones distinguish source completion, candidate verification, and release authorization; roadmap remains singular. |
| VRA-022 | Pin failures and apply existing bounded retention; no new storage-management framework. |

Additional grounded gap: the source-built CLI has no downloadable release package (F-17).
Retained VLR French accuracy findings must distinguish production Neutral from experimental
no-delivery/Calm arms before deciding remediation (VLR-07); do not repeat completed Clone studies.

## Preserved September 4 device boundary

`ios-xcui-control-audit-20260904-065457-e2ec8911` has seven correlated passes and
`custom-008` PRODUCT_FAIL: marker-free French CustomVoice with a 12.362-second interior gap.
The successor `ios-xcui-control-audit-20260904-151935-164b4ee3` failed History keyboard focus
after 1115.371 seconds. Five additional engine attempts exist (three Fast-QC passes, two warnings),
but no accepted current-run control-observation attachment. They are not UI acceptance and must
not be silently replayed. The composer preserves seven inherited passes, one inherited product
failure, and 193 unvalidated generation cells plus three aggregate controls.

The retained attachment manifest contains 1710 attachments and no canonical observations; a
bounded read-only inspection of exported attachment names and retained Staging found no recoverable
structured observation stream. Preserve the original result and ledger. Screenshots or engine
records alone cannot manufacture missing ownership/cleanup receipts. A new-source campaign may
explicitly revalidate cells, but must not overwrite these original failed/unverified attempts.

No phone work is active at this checkpoint. The previous run did not prove final app termination,
restoration, or screen lock; verify those before the next unattended run. Do not assume ownership
of existing History rows from text alone.

## RF-06 retained-evidence review and bounded follow-up (September 4)

No original result was rewritten. The review and three bounded Mac reproductions narrow the next
device diagnostic rather than claiming the remaining release finding is resolved.

- **Marker-free Custom:** `custom-008` in `065457-e2ec8911` has a correct French model-facing
  receipt, the recorded seed, zero allocation retries, and voluntary EOS. Persisted QC locates
  12.362 seconds of interior silence starting at 6.074 seconds. Pre-write chunk reports 11–32
  cover 6.16–18.48 seconds with RMS between −77.16 and −69.26 dBFS. These reports are computed
  from decoded samples before the final writer (`GenerationOutputAdapter.swift`), so the defect
  is already observable upstream of file assembly/History/playback. The retained bundle has the
  rejected-WAV digest but no matching WAV or codec trace. The exact current-source request then
  passed three fresh Mac processes without a retry: streaming produced 199 codec frames and a
  15.92-second clip twice with identical QC, while non-streaming produced 325 frames and a
  26.00-second clip. The retained iPhone row produced 1,347 frames and 107.76 seconds of audio.
  This rules out the tracked script, instruction/language routing, and final WAV writer as a shared
  deterministic cause, and establishes stable same-path Mac sampling. It does not distinguish an
  iPhone-specific sampled continuation from code-to-audio decoding because the device codec trace
  is missing. Next: the exact existing row/seed on the physical phone with scoped codec/rejected-
  audio collection, then incremental/full replay. Do not infer an RNG, decoder, prompt, token-cap,
  or QC fix from telemetry alone.
- **French Design:** the September 2 corrected characterization has 28 rows per arm. Shipped
  Neutral has 26 passing output verifications and two accuracy rejects; no-delivery has 23 passes,
  four verification rejects and one mandatory QC rejection; Calm has 19 passes, eight verification
  rejects and one mandatory QC rejection. These are this run's counts, not the earlier cohort's.
  Keep the original terminal results and prompt copy.
- **Verifier completeness was the first divergence for one shipped Design row:** the shipped Neutral long row,
  seed `32060824` (`t96-60c01edf`), is a 16-second WAV. All three `fr-CA` recognition passes cover
  only 8.16–15.84 seconds; the score counts 20 deletions out of 39 reference words. The first
  eight seconds are not blank: one-second RMS windows range from −37.7 to −15.9 dBFS. An offline,
  locally cached Whisper Small analysis of the immutable WAV then transcribed the complete file.
  Its hypothesis has three edits over 39 normalized words (WER 0.077),
  below the unchanged 0.15 threshold; the first half has high speech probability. This establishes
  that Apple Speech consistently discarded the first utterance in this row. It is verifier evidence
  failure, not proof of a French synthesis defect, and the independent analyzer remains diagnostic
  rather than promotion authority.
- **Narrow source correction:** current live verification now binds the Speech timing ranges to the
  immutable WAV duration. Every consensus pass must cover both source edges within the bounded
  one-second/15%-of-duration allowance, capped at 2.5 seconds. A partial but internally consistent
  utterance produces `speech_recognition_incomplete_temporal_coverage`, no WER/CER score, and a
  harness-owned inconclusive VLR result. Historical records remain decodable and unchanged. The
  focused Swift and Python tests cover the retained 8.16–15.84/16-second shape and complete-edge
  control. This is fail-closed classification, not a retroactive PASS or a replacement ASR result.
- **Complete retained Design screen:** the same offline, cached, serial full-file analysis was
  applied to all 14 rows whose successful audio had not cleared the original verifier. Every WAV
  is shorter than the analyzer's 30-second context, so no artificial split boundary was needed.
  Twelve fall at or below WER 0.15: both shipped Neutral rows, all four no-delivery rows, and six
  of eight Calm rows. The only two remaining diagnostic misses are short Calm controls at WER
  0.167. Of the 12 original numeric accuracy rejects, four have incomplete Apple Speech edge
  coverage; the other eight cover the WAV but still contain evaluator disagreement. The two
  shipped Neutral rows are 2/2 under the diagnostic analyzer, but the short row remains an Apple
  Speech 0.167 failure versus diagnostic WER 0.083 and is not promoted by the independent result.
  This preserves the distinction between proven temporal truncation, unresolved evaluator
  disagreement, and actual experimental-arm defects.
- **Exact current-source Mac confirmation:** the retained short and long shipped-Neutral French
  requests were regenerated in fresh CLI processes with their exact scripts, briefs, delivery,
  and seeds `32060828` and `32060824`. Both passed mandatory Fast-QC, emitted matching request
  receipts, and scored diagnostic full-file WER 0.000. This is useful same-source Mac evidence;
  it is not physical-iPhone or Apple Speech closure.

Evidence stays in the original ignored UI/VLR run bundles. Engine JSONL SHA-256 for the Custom
row's bundle: `09d6a537b4da25a5434a30c79a47943acb7fec6a82b4030936a9270d57aa5b3a`.
The current VLR composer correctly refuses to qualify historical input against the changed full
tree; that guard was not bypassed. The observations above are diagnostic, not newly qualified
candidate evidence. RF-06 remains open for the iPhone codec/replay boundary, the shipped Neutral
short-row Apple/Whisper disagreement, and fixed-source physical-device confirmation of the
coverage classifier; independent RF-07/RF-08 engineering may continue.

The coherent source checkpoint passed the full project-input gate (121 Python modules and 1,468
declared tests), generic physical-iOS SDK app and logic-test builds, and all deterministic macOS
core, transport, and owned-runtime suites (`mac-test-20260904-145600`). No phone, model download,
or release action was used by that checkpoint.

## RF-08 source checkpoint (September 4)

The existing release workflow now produces and verifies the separate CLI DMG through the same
managed build/artifact steps, with backward-compatible app-only historical verification. The
payload includes the executable, MLX/dependency resource bundles, two source-bound catalogs,
project license, complete governed attribution JSON, rendered notices and usage instructions.
Both DMGs enter checksums, attestation, draft upload and exact remote-asset validation together.

The optimized development CLI built successfully and its 32-file copied payload passed real
model-free discovery outside the checkout, including a path containing spaces. The first test
demonstrated that Xcode's tool product omitted the catalog JSON; release staging now copies the
authoritative source bytes explicitly and refuses a mismatching built catalog. Ad-hoc resource
signatures legitimately have empty CMS placeholders; a narrow fixture covers these without
permitting empty shaders/data. No Swift resource-lookup change was necessary.

Local report: `cli-packaging-local-20260904.json` in ignored macOS release artifacts; executable
SHA-256 `8ba1c5a3ef95e5098e26251b320eb17966f0a113a3e026f4bcc8456fc8fa7217`.
It declares development/internal-diagnostics scope, not candidate acceptance. The later all-mode
and cancellation proof below uses that same 2.4.0/build 23 development artifact. Developer ID/
notarized DMG qualification and RF-10 promotion remain open; current source is 3.0.0/build 24.

The real ad-hoc DMG route then passed independently: a 11,969,269-byte image with SHA-256
`ad109cb15c610d8964fc3429daac46fab9622ca2e9816b9fd2fc95b88816ca69` attached read-only,
copied its `Vocello CLI` folder to a path with spaces, repeated all nine model-free checks, and
detached cleanly. The ignored proof bundle is `rf08-cli-dmg-roundtrip-20260904`. Ad-hoc signing
and no-generation scope are explicit; this is not Developer ID, notarization or RF-10 evidence.

The package verifier now also has an opt-in, privacy-safe real-generation qualifier. It revalidates
the copied payload before using an isolated runtime and an already-installed model store, runs all
three Speed modes serially, requires exact request/result identities and strict QC PASS, observes
live cancellation before sending SIGINT, and checks stable failure exits. The existing ad-hoc
2.4.0/build 23 DMG passed: Built-in English (3.28 s), French Voice Design (7.68 s), and English
Clone (4.08 s) each produced a valid QC-PASS WAV with the exact expected model; live cancellation
exited 130, unknown command exited 2, and invalid mode exited 1. The ignored report is
`rf08-cli-dmg-roundtrip-20260904/cli-generation-qualification.json`. It records no source text,
transcript, path, or audio and explicitly grants no publication authority. Because the artifact is
an older ad-hoc development package at source `089328d3`, this proves the qualification mechanism
and package self-containment only; RF-10 must repeat it on the signed/notarized 3.0.0 candidate.

The resumed qualifier additionally removes an assumed Clone transcript: use audio-only conditioning
or provide the actual reviewed reference transcript. The historical Clone take therefore proves
execution/QC only, not reference fidelity. Current qualification retains WAVs, atomic partial rows,
the active stage, and sanitized failure types on failure/interruption. It refuses report reuse,
terminates/awaits process groups on timeout, and handles newline-free progress output. Its 25 focused
fixtures pass; requested seed/streaming fields are not claimed as observed engine receipts.

## RF-09 host verification and safe next step (September 4)

The full project-input gate passed all 1,481 Python tests. macOS core, XPC transport and owned-runtime
tests passed (`mac-test-20260904-160540`); macOS app and 3.0.0 CLI builds, generic iOS app/logic
compiles, and the complete website check (including both rendered browser layouts) passed.
Ignored logs in `rf09-host-checkpoint-20260904` preserve the initial failed gate attempts as well
as the successful run. Version separation, attribution regeneration and the guidance byte budget
were corrected, not waived. Advisory currency warnings remain distinct from required failures.

The existing classifier against `v2.4.0` requires eight promotion lanes for each platform:
engine, Quality-engine, delivery, language, model lifecycle, retained memory, UI benchmark and UI
performance. `quality_promotion.py` filters them by platform; desktop qualification is independent
of the phone. Recompute from the exact committed candidate before expensive execution. These are
promotion requirements, not commit/candidate-build prerequisites, and unsupported dimensions must
remain explicit in the contract's capability coverage.

Phone-independent source work is ready for a coherent commit. Exact-SHA CI/Security, the authorized
verified tag and signed candidate remain separate; do not call source preparation a frozen release.
No iPhone or Simulator ran. RF-06 and RF-07's focused physical proof precede RF-11's fresh campaign;
the seven earlier correlated passes, one product failure and five unverified attempts are preserved.

## External decisions and final gates

The [prepared 3.0 candidate notes](release-3-0-candidate-notes.md) cover the user-facing changes,
delivery-roster correction, complete-folder CLI installation and candidate-specific What to Test.
They are active preparation, not a published release or an immutable acceptance record. Move the
finished text into the exact tag's governed release notes only at an authorized candidate freeze.

RF-02's September 4 read-only checkpoint now proves a valid Keychain profile, usable local Apple
Development, Apple Distribution, and Developer ID identities, one active matching App Store profile,
and registered App Group plus Increased Memory Limit capabilities for the exact iOS bundle. It also
confirms the existing third-party-content declaration. This supersedes the September 1 observation
that no matching App Store profile was available. It does not prove the profile payload's
entitlements or produce an archive/IPA; those remain ASR-10/RF-12 gates.

The account inventory remains incomplete: pricing/availability has no readable initialized record;
the old 2.4.0/build 23 identity is already used; accessibility declarations are empty; and App
Privacy publication, agreements/tax/banking, DSA trader status, and regional compliance require
owner/web or qualified review. The iOS plist already declares non-exempt encryption false and the
API reports no separate encryption-declaration resource, but the processed 3.0.0 candidate must still
confirm export-compliance behavior. No account value changed during this inspection. RF-09 now
selects source 3.0.0/build 24 with a passing read-only collision check; the live version still needs
an authorized edit and archive-time collision revalidation.

Use the existing [content-rights review](content-rights-review.md),
[App Store submission procedure](ios-appstore-submission.md), and
[quality-promotion contract](quality-promotion.md). Qualified privacy/rights judgment, signing
assets, owner-only account fields, internal TestFlight upload authorization, and final publication
authorization cannot be replaced by automated tests. Fresh-install proof must not erase the
maintainer's current app without separately authorized, verified recovery.

Defer evaluator research, prompt-population studies, broad runtime refactoring, hosting migration,
and general evidence redesign. Preserve existing model pins, QC rules, fixed seeds, and one-take
behavior. An accounted-for failed campaign is not a passing campaign.
