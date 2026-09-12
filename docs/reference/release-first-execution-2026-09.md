---
status: active
owner: release-qa
summary: Finite release-first execution order for iOS, macOS, and the downloadable CLI; current scheduling and durable gates only; dated programme checkpoints are archived.
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
`RF-01` through `RF-13` milestones remain the execution roadmap. The September 6 iOS-first
amendment below supersedes their original numeric scheduling order, not their closure gates.
Both `roadmap.py status` and the generated `docs/ROADMAP.md` present it first. Older plans retain
technical defect ownership, evidence and deferred backlog; their active status does not independently
schedule another workstream. RF milestone completion never closes a referenced defect implicitly:
for example RF-03 source proof does not close F-15's packaged-candidate acceptance.

## Decisions and order

Keep and repair long-form and segment regeneration. Complete the 201-take iOS campaign.
Prioritize iOS; park Mac/CLI-only packaging and qualification until the iOS critical path clears.
Shared-code regression tests remain required. This changes scheduling, not previous failure results.
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

## September 6 accelerated iOS queue

Baseline: clean `793439ad`. RF-03/04/05/07 stay implementation-complete; do not reimplement
their accepted repairs. `config/roadmap.json` remains the only status ledger. The following maps
the approved ten-step execution sequence onto existing owners; it is not a second defect register.

| Order / class | Owner and next action | Required evidence / exit |
| --- | --- | --- |
| 1 — scheduling | RF-01: classify the existing queue and preserve historical outcomes | Roadmap, documentation and instruction validators agree; original gates retained |
| 2 — external dependency | RF-02 / ASR-02/04/08/10/11: use the consolidated rights/account packet | Qualified decisions or an explicit owner/service blocker; separate authorization for edits, candidate operations and uploads |
| 3 — correction before freeze | ICA-15 / VLR-07 / F-16: severe gaps and cadence/recognition findings; RF-06 is retained as a known limitation per the September 7 scheduling amendment (explicit rejection, recovery and accepted-output preservation verified; incidence measured by RF-11) | Exact retained inputs, first divergent boundary, verified correction or explicit release blocker; for RF-06 no new research matrix and no PASS relabeling |
| 3a — accessibility qualification before freeze | ISU-4 / ISU-5: Settings and App Language reachability at AX-XXXL and pseudo-AX-XXXL on post-ISU-5 source | One authorized `scripts/ui_test.sh ios localization` walk in English/French; existing identifiers, strict visibility predicates, no automatic retry |
| 4 — verification correction before freeze | RF-09 / RF-12: source-validated platform applicability and preinstalled-candidate route | iOS Speed requirements retained, macOS Quality retained, historical compatibility; no target replacement or diagnostics dependence |
| 4a — monetization before freeze | RF-13: one-time iOS Design/Clone export unlock | Verified StoreKit entitlement and all outward export paths; generation/listening/internal History free in every mode, Built-in export free; focused purchase, restore, offline and refund tests |
| 5 — freeze | RF-09: coherent deterministic checkpoint, exact-SHA CI/Security, fresh collision check, authorized tag/archive/IPA | Frozen candidate with signing, entitlements, notices, privacy, architecture and UUID proof; no internal diagnostics |
| 6 — implemented, candidate verification | RF-11 / F-01/06/16/18/23 / ICI-4 / VLR-07: targeted correction acceptance | Long-form/regeneration, all modes, enrollment, player, History, export and preservation pass before expansion |
| 7 — implemented, campaign verification | RF-11 / ICA-04/05 / AV-09 / ASR-12: all 201 takes and applicable remaining lanes | Five-take pilot then up to 20 per invocation, mode boundaries respected; all outcomes and restoration accounted for, no unresolved required failures |
| 8 — processed candidate verification | RF-12 / ASR-06/07/10/12: separately authorized TestFlight, then black-box upgrade/fresh-install acceptance | Approved identity unchanged; no debug app substitution. Fresh install only after usable encrypted recovery and immediate separate approval; otherwise blocked |
| 9 — external and candidate materials | RF-12 / ASR-05/09/11: genuine screenshots, approved metadata/declarations, fresh regional host proofs | Authentic accepted-size layouts, reviewer journey, NA/Europe/East Asia proofs inside the 24-hour freshness window |
| 10 — submission decision | RF-12: issue READY TO SUBMIT or the remaining owner/action blockers | All required gates passed; actual App Review submission still separately authorized |
| Deferred — non-iOS qualification / research | RF-08/RF-10; broad evaluator, prompt and prosody studies | Preserve existing evidence and gates; no Mac/CLI-only job or semantic research milestone on the iOS critical path |

Before each RF-06 experiment, register hypothesis, exact inputs, discriminating observation and
production decision in the existing untracked run bundle. The first pass is limited to two targeted
experiments per finding. Recover the failed long-form text/seed once; do not substitute approximations.
Replace the acceptance fixture's random spoken marker with deterministic natural text and existing
History/metadata ownership. That fixture correction does not resolve the original product failure.
Do not repeat excluded decoder permutations, trim silence, raise the token cap arbitrarily, change
seeds/prompts, weaken QC or introduce hidden retries. If no actionable defect is localized, record a
decision checkpoint and continue independent host work without calling the audio finding fixed.

During RF-11 reserve at least 20 minutes before each phone deadline for collection/restoration.
Derive ETA from the first shard. Resume only at an independent next row after terminal cleanup and
identity validation; no failed-row retry. Stop for crash, unsafe device conditions, uncertain ownership
or data-loss risk. Source changes start a new campaign identity; previous results remain historical.
End device work with the existing French-compatible three-minute Auto-Lock readback and verified lock.
Candidate marketing overlays must retain genuine captures/aspect ratio and never claim native Pro Max
testing. No uninstall, legal clearance, account mutation or upload is authorized by a roadmap update.

Use focused verification after each coherent change and one complete checkpoint before freeze.
While a campaign is frozen, keep resumable progress in its pinned, untracked run artifacts; do not
edit unrelated source or documentation and then bypass the full-tree identity check. Incorporate
results in the roadmap at the next source checkpoint. A changed product needs fresh applicable
acceptance; old results remain historical evidence, not replacement candidate proof.

## External decisions and final gates

September 7 monetization amendment: implement the maintainer's one-time iOS export purchase before
RF-09's final source freeze and RF-11's 201-take campaign. RF-13 is the new product owner, not a new
plan or harness. Use one StoreKit non-consumable entitlement for Design and Clone output export;
do not charge for generation, playback, internal History or Built-in output export. Preserve original
imported references and personal data. Inventory every outward path (Studio/full player/History,
sharing, Files/save destination, long-form/segments, recovery and automation) and bind eligibility
to the output's recorded generation provenance, not the currently selected Studio mode. Review
document sharing and generated storage before claiming there is no export bypass. Do not turn data
recovery into a payment demand or migrate/delete user files without a safe, explicitly scoped policy.

First define the test product configuration and export policy, then implement one verified StoreKit
owner and common export authorization boundary, followed by focused deterministic and physical
purchase acceptance. Pending/cancelled/failed/unverified transactions cannot unlock paid export;
restore, relaunch, offline owned access and refund/revocation behavior require tests. Sandbox and
processed-candidate checks supplement local tests; never buy with a real account automatically or
introduce a diagnostics-only entitlement bypass to green the campaign. RF-02 owns the separate
price/product/account decisions and RF-12 the first-IAP submission materials and processed-candidate
purchase proof. Local configuration is not a live product. Price, identifier, name and Family Sharing
remain explicit choices. Monetization and App Store submission are iOS-only: macOS remains a
GitHub Releases distribution with unrestricted exports, and the CLI gains no paywall. Do not add
a Mac App Store route or propagate iOS entitlement checks into macOS/CLI export paths. No account edit, purchase or candidate
operation is authorized by this amendment alone.

September 7 implementation checkpoint: the source now includes the iOS-only StoreKit owner,
output-provenance export gate, restore/options sheet, legacy-reference preservation and free actual
storage-failure recovery. The test product is provisional and not active in shipping schemes.
Deterministic checks and generic compilation are distinct from the still-required physical purchase
and processed-candidate acceptance. Use [the app guide](ios-app-guide.md#ios-export-purchase) and
[submission procedure](ios-appstore-submission.md#1-privacy--compliance-app-store-connect); RF-13
stays in flight until its focused acceptance gate passes. Do not create a second purchase harness.

September 8 account checkpoint: the maintainer approved and authorized the non-consumable
`com.patricedery.vocello.design_clone_export`, reference name Design & Clone Export, USD 19.99 base
in USA, automatic regional pricing, and Family Sharing off. Creation and pricing readback succeeded;
localized metadata, availability and physical/processed purchase acceptance remain pending. The
product is MISSING_METADATA and was not submitted. The earlier invalid hyphenated identifier was
rejected without creation; source and TEST fixture now match the approved identifier.

September 7 scheduling amendment: retain the English long-form generated-code failure as an open
known limitation and defer further causal research. Preserve its original evidence and uncertainty;
independent-decoder reproduction is not proof of the original generating trigger. Verify explicit
rejection, recovery and accepted-output preservation, then use the already-required frozen 201-take
campaign to assess incidence rather than adding a research matrix. RF-09 still precedes that full
campaign. This does not waive QC, close the separate French/Chinese findings, or authorize shipping
with an unresolved required failure. A release-risk exception requires a separate recorded decision.

September 11 reconciliation note: `config/roadmap.json` was compared item by item against the tree
(`2f06f21a`). Items whose only open clause is packaged, frozen-source or device evidence owned by a
parked or unfrozen owner are now `planned` with that owner in `blockedBy` (F-05/15/17/18/20/21/23,
ICA-04/05, ISR-06, DP-32); F-19 and F-22 are done; ASR-04 is in flight; RF-06's title and gate now
match the amendment above; two code defects found during the review are filed as F-25 (busy Saved
Voice store is fatal to engine initialization) and F-26 (CLI playback children and signal edges).
Step 5's CI dependency was not satisfiable between September 9 and September 11: `main` was red on a
PyYAML import the runner cannot satisfy and then on a locale-dependent French plural test; both are
fixed. A host cleanup on September 11 removed every retained run bundle under `build/artifacts`, so
no earlier campaign phase can be resumed and the 201-take plan starts from take 1.

Use the existing [consolidated content-rights packet](content-rights-review.md),
[App Store submission procedure](ios-appstore-submission.md), and
[quality-promotion contract](quality-promotion.md). Account snapshots are dated evidence, not
current availability or a build-number reservation. The roadmap names unresolved owner/service
dependencies. No repeated polling replaces a qualified decision or required fresh preflight.

Qualified privacy/rights judgment, signing assets, owner-only account fields, internal TestFlight
upload authorization and final publication authority cannot be replaced by automated tests.
Fresh-install proof must not erase personal data without usable verified recovery and separate
immediate approval. Candidate release copy is the active [v3.0.0 body](../releases/v3.0.0.md);
it becomes pinned historical release copy only after authorized publication.

Defer evaluator research, prompt-population studies, broad runtime refactoring, hosting migration
and general evidence redesign. Preserve model pins, QC, fixed seeds and one-take behavior.
An accounted-for failed campaign is not a passing campaign.

## Historical programme checkpoints

The earlier dispositions, measurements, source identities and commands, the mapping of audit
findings VRA-001 through VRA-022 to their owners, the September 4 device boundary (seven correlated
passes, one product failure and five unverified attempts) and the RF-06 retained-evidence review
live in git history. None of it is replayed or promoted; later evidence does not rewrite the original
results. Current item status is in the roadmap; use
[the current checkpoint](../development-progress.md) for next work, not dated commands.
