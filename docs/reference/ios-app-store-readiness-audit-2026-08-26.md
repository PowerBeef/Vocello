---
status: historical
owner: release-qa
summary: Point-in-time, code-grounded iOS App Store readiness audit covering Apple review policy, the built app, privacy, signing, licensing, reviewer access, accessibility, metadata, and the evidence still required before submission.
contentDigest: sha256:65db244ff419d7fc1c7932ab4ac047f3a93c1fa2b44a4b540cfef9f037da9c0e
sourceOfTruth:
  - config/roadmap.json
  - project.yml
  - Sources/iOS/Info.plist
  - Sources/PrivacyInfo.xcprivacy
  - .github/workflows/release.yml
---
# iOS App Store readiness audit — 2026-08-26

> **Pinned historical report.** This document describes revision
> `25a1aa59f1a3b7bdfc8858f14028ecc61d584874` as inspected on 2026-08-26. It is
> not a release authorization and does not override source code, `project.yml`, machine-readable
> contracts, or [`config/roadmap.json`](../../config/roadmap.json). Account, legal, signing, and
> physical-device conclusions remain pending where the necessary evidence was unavailable.

## Executive verdict

**Vocello is not yet submission-ready.** The unsigned Release build and source pipeline are mature,
but a submission-ready conclusion would currently be false for four reasons:

1. the App Store installation declaration allows devices that the app rejects at runtime;
2. the present “Data Not Collected” instruction is not justified while Hugging Face receives and may
   retain request metadata during model downloads;
3. reviewer support, third-party attribution, content-rights, and current metadata evidence are
   incomplete; and
4. no signed archive/exported IPA, read-only App Store Connect audit, or current signed-candidate
   physical-device acceptance exists.

There is no source evidence of private API use, downloaded executable code, analytics, advertising,
tracking, account/login requirements, or cloud inference. The generic arm64 Release build succeeds,
Xcode static analysis succeeds, model payloads are digest-pinned data, required-reason API declarations
exist, and the release workflow fails closed over source, signature, entitlements, privacy manifest,
UUID, SBOM, and attestation identity. These are meaningful strengths, but they do not replace the
credential-, account-, legal-, and device-bound evidence Apple reviews.

### Status and confidence vocabulary

| Status | Meaning |
| --- | --- |
| `PASS` | The inspected evidence satisfies the bounded requirement. |
| `FAIL` | A concrete contradiction or missing required surface was established. |
| `PENDING` | The necessary account, legal, signed-artifact, or physical-device evidence was unavailable. |
| `NOT APPLICABLE` | The feature or policy does not apply to Vocello. |

| Confidence | Meaning |
| --- | --- |
| `source-proven` | Established from checked-in source, contracts, or resources. |
| `build-reproduced` | Established in the unsigned generic Release product or Xcode analysis. |
| `archive-reproduced` | Established in a freshly signed archive and exported IPA. Not available here. |
| `account-verified` | Established from the live App Store Connect record. Not available here. |
| `device-deferred` | Requires the supported physical iPhone and repository XCUITest. |
| `legal-review-required` | Repository evidence cannot make the final legal/privacy/rights judgment. |

Severity is rejection or material-user-risk oriented: P0 blocks any truthful submission-readiness
claim, P1 is a likely rejection or primary-flow blocker, P2 is a material completeness/operational
gap, and P3 is hardening or hygiene.

## Audit basis

The audit inspected the source tree, generated Xcode project, resolved SwiftPM graph, generic Release
app, model catalogs, privacy manifests, entitlement files, release workflow, deterministic contracts,
existing device evidence, website policy and build, and current Apple documentation. No app behavior,
metadata, model repository, account record, signing asset, or device state was changed.

| Evidence | Result |
| --- | --- |
| Branch and source | `main`, clean at audit start, revision above |
| Toolchain | Xcode 26.6 (`17F113`), Swift 6.3.3, iPhoneOS 26.5 SDK (`23F81a`) |
| Generic iOS Release compile | `PASS`; arm64, iPhone, iOS 26.0 |
| Xcode static analysis | `PASS` with four P3 compiler warnings recorded below |
| Generic built app | 69 MB; `Vocello` plus `QwenVoiceCore.framework` are the only executable files |
| Signing/archive | Generic app unsigned; no valid Distribution identity/profile, archive, or IPA available |
| Account/device | No read-only App Store Connect credentials; supported iPhone unavailable |

External authorities used were Apple’s current
[App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/),
[App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/),
[App Store Connect privacy management](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/),
[required device capabilities](https://developer.apple.com/documentation/bundleresources/information-property-list/uirequireddevicecapabilities),
[screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/),
[required metadata properties](https://developer.apple.com/help/app-store-connect/reference/app-information/required-localizable-and-editable-properties),
[app information fields](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information),
[age-rating guidance](https://developer.apple.com/help/app-store-connect/manage-app-information/set-an-app-age-rating/),
and [upcoming submission requirements](https://developer.apple.com/news/upcoming-requirements/).
Hugging Face’s [privacy policy](https://huggingface.co/privacy) was used only to identify the
third-party disclosure question; qualified privacy/legal review remains authoritative.

## Submission blockers and authoritative remediation

| Roadmap | Status | Sev. | Confidence | Independent root cause | Closure dependency |
| --- | --- | --- | --- | --- | --- |
| ASR-01 | FAIL | P1 | source-proven | Installation eligibility contradicts the runtime iPhone 15 Pro floor | source + built plist |
| ASR-02 | FAIL | P1 | source-proven / legal-review-required | “Data Not Collected” is unsupported for Hugging Face request metadata | privacy/legal + ASC |
| ASR-03 | FAIL | P1 | source-proven | No dedicated monitored support/contact surface in app or current Support URL plan | source + website + ASC |
| ASR-04 | FAIL | P1 | source-proven / legal-review-required | No bundled complete attributions or recorded content/model/preview rights decision | source + legal |
| ASR-05 | FAIL | P2 | source-proven | Review notes and screenshot instructions are stale; current assets are not eligible | docs + device + ASC |
| ASR-06 | PENDING | P2 | source-proven / archive-reproduced | Sensitive-file protection policy and final-bundle enforcement are not established | source + archive + device |
| ASR-07 | FAIL | P2 | source-proven / build-reproduced | Release logging/diagnostic strings and analyzer warnings need a final privacy/API audit | source + archive |
| ASR-08 | FAIL | P2 | source-proven / account-verified | Fixed build number has no duplicate-build preflight | pipeline + ASC |
| ASR-09 | PENDING | P1 | source-proven / account-verified | Primary review journey depends on large Hugging Face downloads with no availability proof | hosting + reviewer proof |
| ASR-10 | PENDING | P0 | archive-reproduced | No fresh signed archive and exported IPA have passed the verifier | signing assets |
| ASR-11 | PENDING | P0 | account-verified / legal-review-required | Live App Store Connect and regional/compliance fields have not been audited | read-only ASC + legal |
| ASR-12 | PENDING | P1 | device-deferred | No current signed-candidate functional, accessibility, or screenshot acceptance | physical iPhone |

The objective gates for these items live in `config/roadmap.json`. Existing F, AV, ISR, MD, and
release items are cross-referenced rather than duplicated.

## 1. Binary, platform, and device eligibility

### Requirement matrix

| Requirement | Status | Sev. | Confidence | Evidence and impact |
| --- | --- | --- | --- | --- |
| Current submission toolchain | PASS | — | build-reproduced | Xcode 26.6 and iOS 26 SDK exceed Apple’s Xcode 26+/iOS 26 requirement effective 2026-04-28. |
| Deployment/architecture/family | PASS | — | build-reproduced | iOS 26.0, arm64, iPhone family only. The bundle contains no simulator slice. |
| Runtime and App Store device eligibility agree | FAIL | P1 | source-proven | Info.plist declares only `arm64`, while `IOSDeviceSupport` rejects devices older than iPhone 15 Pro. Eligible older devices can install a nonfunctional app. |
| Version/build identity | PASS | — | build-reproduced | `2.4.0 (23)` comes from `project.yml` through bundle settings. ASR-08 separately covers reuse/collision. |
| Orientations, appearance, launch, icons | PASS | — | source-proven / build-reproduced | Portrait-only and dark-only are explicit; launch storyboard is present; required icon slots including 1024 px are RGB without alpha. Device presentation remains part of ASR-12. |
| Encryption declaration | PASS | — | source-proven | `ITSAppUsesNonExemptEncryption=false`; app uses HTTPS and hashing, with final export-compliance answers account-pending. |
| Downloaded-code rule 2.5.2 | PASS | — | source-proven / build-reproduced | Catalog payloads are safetensors, tokenizer/config data, and marking resources pinned by revision, byte count, and SHA-256. No downloaded binary or script is executed. |
| Public API/static analysis | PASS | P3 notes | build-reproduced | Xcode Analyze succeeded. Owned iOS/core source exposes no direct dynamic loading/private symbol lookup. A signed-archive scan remains ASR-07/10. |
| Initial bundle size | PASS | — | build-reproduced | Generic app is 69 MB and does not bundle model weights. |
| Model download disclosure | PASS | — | source-proven | UI prompts before download, displays exact catalog-derived size/progress, checks space, and supports cancel/retry/removal. Each Speed package is about 1.7 GB. |
| Full installed storage/reviewer feasibility | PENDING | P1 | device-deferred / account-verified | Three Speed packages total about 5.15 GB before shared-component reuse. Real download availability and end-to-end review are ASR-09/12. |

### ASR-01 — installation eligibility contradicts runtime support

`Sources/iOS/Info.plist` advertises only `arm64`. `IOSDeviceSupport` permits `iPhone16,1`,
`iPhone16,2`, and later major identifiers, and otherwise renders **Unsupported Device — Vocello for
iPhone currently requires iPhone 15 Pro or newer**. Apple documents the
`iphone-performance-gaming-tier` capability as the iPhone 15 Pro/Max performance tier. Because
capability restrictions affect who can install the app and generally cannot safely be tightened
after distribution, this should be settled before the first public version.

**Rejection/user scenario:** App Review or a customer installs on an arm64/iOS 26 device accepted by
the store but cannot use any feature. **Remediation:** encode the real hardware requirement in the
shipping Info.plist (or remove the runtime restriction only with measured support evidence), then
verify the archived plist and App Store eligibility. Do not ship the present contradiction.

### Executable and resource inventory

The inspected app has two executable Mach-O files: the app and `QwenVoiceCore.framework`. It also
contains a root privacy manifest, dependency privacy manifests for GRDB and swift-crypto, English
strings, app icons, launch storyboard, Metal library, the model/speaker/catalog contracts, and nine
built-in preview WAV files. No model weights are bundled. Final conclusions about bitcode/debug
support files, signatures, embedded profiles, dSYMs, UUID continuity, and forbidden strings require
the exported IPA under ASR-10.

Xcode Analyze emitted nonblocking hygiene warnings: an unused `deliveryStyle`, two unnecessary
`nonisolated(unsafe)` annotations, and two ignored `withLock` return values. They are not evidence of
an App Review failure but should be cleared or justified before freezing the candidate.

## 2. Signing, entitlements, archive, and release pipeline

| Requirement | Status | Sev. | Confidence | Evidence and impact |
| --- | --- | --- | --- | --- |
| Development/release entitlement separation | PASS | — | source-proven | Development adds `get-task-allow`; release contains only App Group and increased-memory entitlement. Workflow overrides the target to release entitlements. |
| Increased-memory capability eligibility | PENDING | P0 | archive-reproduced / account-verified | Source requests it; the Distribution App ID/profile and exported signature cannot be verified without credentials. |
| Root/dependency privacy manifests | PASS for generic build | — | build-reproduced | Root manifest plus embedded GRDB/swift-crypto manifests are present. Final IPA scan remains pending. |
| Hardened Release optimization/symbols | PASS for generic build | — | build-reproduced | `-O`, whole-module optimization, dead stripping, dSYM generation. Signed-archive inspection is still required. |
| Clean source/release evidence | PASS in pipeline design | — | source-proven | Manual workflow binds version tag, exact source, platform readiness, evidence, SBOM, checksums, and provenance before upload. |
| Signature/profile/certificate/UUID verification | PASS in verifier design; PENDING live | P0 | source-proven / archive-reproduced | Verifier checks archive/IPA continuity, Apple Distribution trust, profiles, team/App ID prefixes, entitlements, privacy manifest, architecture, UUIDs, and code identity. No fresh input exists. |
| Build-number collision prevention | FAIL | P2 | source-proven / account-verified | Project is fixed at build 23 and export disables automatic version/build management; no live duplicate-build preflight was found. |
| Upload/submission | NOT APPLICABLE | — | — | The audit had no authority to upload, mutate TestFlight, tag, or submit. |

### ASR-08 — build-number collision

A repeated archive/upload of version 2.4.0 build 23 can be rejected once that build exists in App
Store Connect. Add a fail-closed read-only preflight for the exact bundle/version/build identity and
a documented maintainer-owned increment operation. It must not silently mutate the project during a
release run.

### ASR-10 — signed archive and IPA

No valid Apple Distribution identity, App Store provisioning profile, `.xcarchive`, exported IPA,
or release-verification record was available. The unsigned generic app is compile evidence only.
Closure requires a clean-source signed archive and exported IPA through the existing workflow and a
PASS from `verify_ios_release_artifacts.py`, including profile entitlement, signature trust, privacy
manifest, architecture, executable continuity, UUID/dSYM, SBOM, checksums, and release-evidence
checks. This audit neither produced nor uploaded a candidate.

## 3. Privacy, security, and data lifecycle

### Data-flow inventory

| Data or event | Creation/use | Storage/deletion | Off-device behavior | Audit status |
| --- | --- | --- | --- | --- |
| TTS text and generated audio | User types text; local MLX generation | History/output files; user can delete/clear/export | No product network path found | PASS source; device deletion pending |
| Clone recording/import | Microphone or visible Files/open-in-place path | Staging/prepared/reference/voice-bank files; regenerable caches excluded from backup | On-device speech recognition explicitly requires on-device support | PASS source; permissions/deletion pending |
| Saved voices/history/preferences | User-created identity, reference artifacts, SQLite, UserDefaults | User content intentionally backed up; model/cache intermediates excluded | No sync/analytics SDK found | PASS source; ASR-06 protection policy pending |
| Model artifacts | HTTPS from immutable Hugging Face revisions | App Group model/download roots, digest verified, removable, excluded from backup | Hugging Face receives network request metadata | FAIL current disclosure; ASR-02 |
| Diagnostics/telemetry | Debug-master-gated local files and MetricKit/system evidence | Bounded, redacted, backup-excluded where registered; untracked collection | No app analytics endpoint found | PASS architecture; ASR-07 final string/log scan |
| Links | Privacy policy, GitHub, iOS Settings | None | User explicitly opens external URL | PASS; support destination fails ASR-03 |

### ASR-02 — privacy label and third-party processing

`PrivacyInfo.xcprivacy` declares no tracking and no app-collected data types. The privacy policy and
submission runbook then go further and instruct “Data Not Collected,” treating Hugging Face model
downloads as immaterial. Apple requires privacy answers to include third-party partners. Hugging
Face states that it automatically records information including IP address, location, usage/session
date, device type, model/version, operating system, and browser. Whether each field satisfies
Apple’s definition of “collected” depends on purpose and whether it is retained beyond servicing the
request; the repository cannot establish Hugging Face’s applicable retention/processor terms.

**Rejection scenario:** network observation and the privacy label/policy disagree, triggering
Guideline 5.1.1 or App Privacy rejection. **Remediation:** obtain a documented vendor/retention and
legal determination; update the App Privacy answers, website/in-app policy, and review notes
consistently; capture the exact account answers read-only. Do not keep or replace “Data Not
Collected” by inference.

### Permissions and privacy controls

Microphone and speech-recognition purpose strings specifically describe clone recording and local
transcription. `VoiceClipTranscriber` requires `supportsOnDeviceRecognition` and sets
`requiresOnDeviceRecognition = true`; unsupported locales fail rather than fall back to a cloud
recognizer. The visible Privacy section requires ownership/permission consent for cloning and tells
publishers to disclose AI-generated cloned speech. These are source passes. Physical denial,
recovery, interruption, and deletion behavior remains part of ASR-12.

The manifest declares the four observed required-reason categories: UserDefaults, system boot time,
file timestamps, and disk space. No tracking domain, advertising identifier, tracking SDK, or product
analytics endpoint was found. Final dependency-manifest merging and binary API use must be checked in
the exported IPA rather than inferred from source.

### ASR-06 — file protection and backup policy

The app explicitly excludes downloaded models, transfer/staging roots, and regenerable caches from
backup, while retaining user outputs, voices, and History in backup by design. No explicit
`NSFileProtection` application or Data Protection entitlement was found for sensitive recordings,
saved voices, generated speech, History, or transient files. This is not proof that iOS leaves files
unprotected; it is proof that the intended protection class is undocumented and unverified.

Define a path-by-path protection/backup contract, apply an appropriate protection class to sensitive
files and directories without breaking background downloads, and verify file attributes plus
backup behavior on the signed candidate. Legal/product review should decide the user-content backup
policy explicitly.

## 4. Licensing, intellectual property, and supply chain

### Dependency and asset inventory

The root SwiftPM graph resolves 17 pinned packages: EventSource 1.4.1, GRDB 7.10.0, mlx-swift
0.31.6, mlx-swift-lm 3.31.4, swift-argument-parser 1.8.2, swift-asn1 1.7.0, swift-atomics 1.3.0,
swift-collections 1.4.1, swift-crypto 4.4.0, swift-huggingface 0.9.0, swift-jinja 2.4.2,
swift-nio 2.100.0, swift-numerics 1.1.1, swift-syntax 603.0.2, swift-system 1.6.4,
swift-transformers 1.3.3, and yyjson 0.12.0. The dependency families are predominantly MIT or
Apache-2.0 and are immutable in Package.resolved. The release pipeline produces SPDX and CycloneDX
SBOMs, but an SBOM is not an end-user attribution/NOTICE surface.

The app bundles owned/forked Qwen/Mimi runtime code, nine preview WAVs, icons, and model metadata;
at runtime it downloads six possible Speed/Quality model repositories, with iOS using the three 4-bit
Speed artifacts. Catalog revision, size, and digest binding is strong. License terms and content
rights need an equally immutable, distributable record.

### ASR-04 — notices and content rights

Only the repository root MIT license and owned-runtime `LICENSE`/`NOTICES.md` are tracked as explicit
notice files. The built app has no complete license/NOTICE resource. Settings → Open Source &
Licenses merely opens GitHub; it is neither offline nor bound to the shipped dependency graph. The
model catalogs pin artifact bytes but do not pin model license/NOTICE text, model-card terms, or a
maintainer rights decision. The preview WAV recipe and digests establish reproducibility, not the
rights to distribute the speaker identities/audio. Marketing/generated audio rights are likewise
not consolidated.

Generate a deterministic attribution manifest from the locked graph and owned runtime, bundle it,
and expose it in an accessible in-app screen. Bind every downloadable model to a revisioned
license/model-card/NOTICE receipt. Record qualified content-rights decisions for built-in speaker
names/previews, generated marketing audio, voice cloning, fonts/icons, and model redistribution.
The App Store content-rights declaration must match those records. A qualified reviewer, not this
report, makes the legal conclusion.

Supply-chain controls are otherwise strong: exact Swift pins, owned-runtime compatibility records,
model digests, catalog receipts, immutable GitHub Action pins, dependency review, CodeQL, SBOMs, and
attestation are present and machine-enforced.

## 5. Product completeness and reviewer journey

| Reviewer journey | Source/existing evidence | Current conclusion |
| --- | --- | --- |
| First launch | Onboarding explains on-device model requirement; no login/demo account | PASS on supported hardware; ASR-01 for wrongly eligible devices |
| Install/cancel/retry/relaunch/update/remove | Correlated ledger, exact byte progress, disk preflight, visible actions; MD-3 device closure exists | Strong historical PASS; current candidate pending ASR-12 |
| Built-in/Design/Clone generation | In-process engine, mandatory audio QC, visible errors/retry; no cloud inference | Source PASS; current signed candidate pending |
| Record/import/permission recovery | Visible microphone/Files routes, consent, local transcription | Source PASS; physical denial/recovery pending |
| History/saved voices/export/deletion | Durable outbox, recovery, clear/delete flows, Files export | Deterministic PASS; physical lifecycle pending |
| Offline operation | Generation is local after install; model acquisition needs network | PENDING explicit current-device proof |
| Background/interruption/low storage/poor network | Lifecycle and downloader contracts exist | PENDING current-candidate acceptance |
| Memory admission/failure recovery | Increased-memory path, typed admission and recent device reliability evidence | PENDING signed entitlement and current candidate |
| Reviewer access | No hidden state or login; primary mode needs ~1.7 GB external download | PENDING ASR-09 availability and notes |

### ASR-03 — support/contact surface

The app exposes Privacy Policy and a GitHub “Open Source & Licenses” link but no Support contact.
The website privacy page tells users to open a GitHub issue, and the runbook treats the repository or
generic website as an acceptable Support URL. Guideline 1.5 requires easy-to-find, accurate contact
information in the app and Support URL.

Provide a stable support page with a monitored contact route and response ownership, link it from
Settings, and enter that exact URL in App Store Connect. Verify it without authentication, in all
distribution regions, and include privacy/contact identity suitable for reviewer and customer use.

### ASR-09 — model-host and reviewer availability

The first primary workflow depends on a roughly 1.7 GB download from `huggingface.co`; all three modes
need about 5.15 GB before shared reuse. The repositories are maintainer-controlled and bytes are
immutable, but no current evidence establishes anonymous geographic availability, rate limits,
uptime, ownership continuity, or a reviewer-access fallback. A reviewer can therefore experience an
apparently incomplete app under Guideline 2.1 even if the client is correct.

Before submission, probe the exact catalog URLs anonymously from representative regions, document
hosting ownership/availability and a monitored response plan, and make reviewer notes state exact
size, expected time, disk/network needs, progress/retry behavior, and offline behavior after install.
Any fallback must preserve the same digest-pinned catalog; do not bundle or redirect to unverified
weights.

## 6. Accessibility, interface quality, and screenshots

Source inspection found extensive stable accessibility identifiers, labels/hints/traits, semantic
fonts and scaling metrics, 44-point control tests, native toggles/pickers where appropriate, and
explicit Reduce Motion and Reduce Transparency preferences. Model states use text/symbols rather
than color alone. XCUITest includes AX-L, AX-XXXL, and pseudo-localized stress walks. No current
candidate VoiceOver focus-order, announcement, contrast, motion, transparency, or largest-size
device acceptance was run during this audit; there is also no explicit Differentiate Without Color
adaptation, which should be included in the visual review rather than presumed defective.

### ASR-05 — metadata, reviewer notes, and screenshots

The active runbook tells reviewers a model becomes **Active**, while the UI now says **Ready**. It
also says both 6.9-inch and 6.5-inch screenshot sets are required. Apple’s current rule accepts one
highest-resolution iPhone set: 6.9-inch is preferred, while 6.5-inch may be supplied when 6.9-inch
screenshots are absent. Accepted portrait sizes include 1260×2736, 1290×2796, or 1320×2868 for
6.9-inch, and 1284×2778 or 1242×2688 for 6.5-inch.

The only tracked iOS screenshot is 780×1696; the remaining tracked screenshots are 1440×1224 Mac
images. None is the current App Store iPhone set. Refresh the runbook and reviewer notes, then capture
privacy-safe current-candidate screenshots on the supported physical phone for the primary journey,
model installation, all modes, Voices, History, and Settings. Validate exact dimensions, no clipping,
stale status, diagnostic state, personal data, or misleading feature claims.

### ASR-12 — physical-device and accessibility acceptance

Historical evidence is substantial: model-management diagnose/acceptance, saved-voice, startup,
performance, localization, and accessibility-size lanes have run on the paired phone. It is not a
substitute for the signed candidate that will be submitted. Closure requires installation on a
supported physical iPhone and repository XCUITest coverage of smoke, all model lifecycle states,
saved voices, startup parity, all generation modes, consent/permission denial and recovery, offline
and interrupted downloads, cancellation/relaunch/removal/reinstallation, backgrounding, storage and
memory pressure, VoiceOver, AX-L/AX-XXXL, Reduce Motion/Transparency, and current screenshots. No
Simulator, hidden UI, alternate driver, retry, or old result may substitute.

## 7. App Store Connect and compliance

No untracked read-only App Store Connect credential was available. Every live field below is
therefore `PENDING/account-verified`; source guesses are not account evidence.

| App Store Connect surface | Required read-only evidence |
| --- | --- |
| App identity | Record, bundle ID, SKU, primary language, categories, platforms, copyright |
| Commerce/availability | Price, territories, agreements, tax/banking readiness, regional restrictions |
| Version metadata | Name, subtitle, description, keywords, promotional text, marketing/support/privacy URLs and localization |
| Media | Screenshot sets and any previews, dimensions, localization, current-build truthfulness |
| Review information | Contact identity, notes, attachment/demo needs, primary workflow, download/storage expectations |
| Compliance | Export compliance, content rights, age-rating questionnaire/result, EU DSA trader status and regional fields |
| Privacy | Each App Privacy category/purpose/identity link, reconciled with ASR-02 and source data flow |
| Builds | Existing uploaded/expired/invalid/rejected builds, exact bundle/version/build collision, processing state |
| Account readiness | Program agreements and required administrative roles; no raw account response retained |

### ASR-11 — live account and legal/compliance audit

Use a least-privilege untracked read-only API key to capture and redact the above fields. Do not edit
metadata or builds during the audit. Qualified decisions are required for App Privacy, content
rights, age rating, export compliance, EU DSA trader status, AI/voice-cloning obligations, regional
availability, and agreements. Raw API responses and credentials remain untracked. Closure requires
all required fields present, internally consistent, and free of rejected/invalid/duplicate candidate
state.

The age rating must be answered using the current questionnaire; the old runbook’s assumed **4+** is
not evidence. Account deletion, Sign in with Apple, in-app purchase, advertising, children’s category,
and demo credentials are `NOT APPLICABLE` in the inspected product because it has no account, login,
commerce, ads, or gated server content. Those conclusions must be revisited if product scope changes.

## Positive controls that must not be weakened

- Local-first generation: text, clone references, saved voices, and generated audio have no product
  cloud inference path.
- Downloaded artifacts are immutable data with revision, byte-count, and digest verification.
- Model acquisition is explicit, size-aware, cancellable, retryable, removable, and backup-excluded.
- On-device speech recognition is required rather than preferred.
- Voice-cloning ownership consent and AI-audio disclosure are visible and persistent.
- Root/dependency privacy manifests and required-reason declarations exist in the generic app.
- Release and development entitlement roles are distinct; release excludes `get-task-allow`.
- Release verification is source-, command-, signature-, profile-, entitlement-, UUID-, SBOM-, and
  attestation-bound.
- Stable accessibility identifiers and physical-device-only XCUITest policy prevent hidden reviewer
  state or alternate UI evidence.
- The deterministic repository, model catalog, supply-chain, security, evidence, and documentation
  gates remain the release engineering authority.

## Required closure order

1. Close ASR-01 through ASR-09 at source/policy level without claiming archive or device evidence.
2. Complete qualified privacy/content-rights decisions and update every policy/metadata surface
   consistently.
3. Audit App Store Connect read-only and resolve build identity/account/compliance gaps.
4. Produce the fresh signed archive and exported IPA; pass the existing verifier and full bundle scan.
5. Install that candidate on a supported physical iPhone and pass ASR-12, including screenshots.
6. Re-run the deterministic release-evidence and quality-promotion contracts for the exact release tag.
7. Request separate explicit maintainer authorization for TestFlight upload, metadata mutation, review
   submission, release tagging, or publication.

Until every P0/P1 item is closed and the signed archive, live account, and current physical-device
evidence all pass, no document or generic build may describe Vocello as ready for App Review.
