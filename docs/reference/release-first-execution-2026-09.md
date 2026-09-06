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
`RF-01` through `RF-12` milestones remain the execution roadmap. The September 6 iOS-first
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
| 3 — correction before freeze | RF-06 / ICA-15 / VLR-07 / F-16: long-form cap first, severe gaps second, cadence/recognition third | Exact retained inputs, first divergent boundary, verified correction or explicit release blocker |
| 4 — verification correction before freeze | RF-09 / RF-12: source-validated platform applicability and preinstalled-candidate route | iOS Speed requirements retained, macOS Quality retained, historical compatibility; no target replacement or diagnostics dependence |
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

All earlier dispositions, measurements, source identities and commands are preserved in
[the pinned programme history](release-first-execution-history-2026-09-06.md).
Use [the current checkpoint](../development-progress.md) for next work, not those dated commands.

### Audit finding disposition

Historical mapping of VRA-001 through VRA-022 to existing owners:
[preserved disposition](release-first-execution-history-2026-09-06.md#audit-finding-disposition).
Current item status remains in the roadmap.

### Preserved September 4 device boundary

[preserved original attempts](release-first-execution-history-2026-09-06.md#preserved-september-4-device-boundary).
Seven correlated passes, one product failure and five unverified attempts remain historical;
none is silently replayed or promoted.

### RF-06 retained-evidence review and bounded follow-up (September 4)

[preserved causal review](release-first-execution-history-2026-09-06.md#rf-06-retained-evidence-review-and-bounded-follow-up-september-4).
Later evidence does not rewrite the original results or make these old next commands current.
