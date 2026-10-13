---
status: active
owner: release-qa
reviewed: 2026-10-12
summary: The maintainer's recorded privacy, region and content-rights decisions for the 3.0 App Store submission, with the evidence behind them for model artifacts, built-in voice previews, marketing audio, product artwork and the App Store Connect declarations.
sourceOfTruth:
  - config/third-party-attribution-policy.json
  - Sources/Resources/qwenvoice_production_model_catalog.json
  - Sources/Resources/voice-previews/README.md
  - website/src/data/samples.js
  - config/roadmap.json
---
# Content rights and redistribution review

This is a decision packet, not legal advice or an independent status authority. Source assets,
machine-readable contracts, and `config/roadmap.json` remain authoritative. A source-proven fact does
not become a qualified legal conclusion merely because it is recorded here.

Apple's [upload requirements](https://developer.apple.com/news/upcoming-requirements/) were rechecked
September 6: iOS uploads require Xcode 26 or later and the iOS 26 SDK or later. The installed iOS
26.5 SDK clears that minimum; signed-candidate verification is still separate. Apple's
[privacy definition](https://developer.apple.com/app-store/app-privacy-details/) still requires
consideration of third-party partner collection. No disclosure decision is inferred from local
inference alone.

## Maintainer decisions of 2026-10-12

On 2026-10-12 the maintainer chose to decide the privacy and content-rights questions personally,
with no paid counsel (the release plan, `docs/reference/release-first-execution-2026-09.md`). Where
this document asks for counsel or a "qualified reviewer", read it as the maintainer's recorded
decision. Each decision records its factual basis; none is a legal opinion.

### ASR-02: App Privacy label is "Data Not Collected"

The facts below were verified in source at `d1c5fb7b`:
- **No tracking, analytics or advertising code.** `PrivacyInfo.xcprivacy` declares no tracking and no
  collected data types.
- **The model download is the app's only own network path.** `HuggingFaceDownloader` makes anonymous
  HTTPS requests for pinned files to `huggingface.co` and its allowlisted CDN hosts, with no account,
  token or cookie. It sends only byte-range headers beyond the system defaults, and receives nothing
  but the model files.
- **Hugging Face's own libraries make no network calls in the shipped app.** Its open-source Swift
  libraries (`swift-huggingface`, the `Hub` module of `swift-transformers`) are compiled into the app
  through the owned engine package, but production uses them only for local cache and configuration
  types. The facade loads models from the prepared directory (`Runtime.swift` →
  `TTS.loadModel(fromPreparedDirectory:)`). Their downloading entry points (`fromPretrained`,
  `ModelUtils.resolveOrDownloadModel`, `resolveModelType`) are not reachable from it.
- **Transcription stays on the device.** Reference transcription sets
  `requiresOnDeviceRecognition = true`, so recorded audio, scripts, transcripts and outputs never
  leave the device.
- **Purchases go through Apple.** On iPhone, the export purchase uses StoreKit.

Apple defines collection as data accessible to "you and/or your third-party partners" beyond what
servicing the request needs. It defines third-party partners as vendors "whose code you've added to
your app". It also states that an IP address sent on a server call and not retained needs no
disclosure. Hugging Face serves the files as a host and logs requests under its own privacy policy.
Vocello neither receives nor keeps that data, and no Hugging Face code that sends data runs in the
app. The label is therefore "Data Not Collected".

The website privacy policy discloses the downloads, Hugging Face's own request logging with a link to
its policy, and Apple's handling of purchases. Revisit this decision if the app ever adds network
code, an SDK, an account, analytics, or a non-Apple purchase path.

### ASR-09: model downloads are verified for North America only

3.0 is sold worldwide, but download verification covers North America only, where App Review runs.
- **Existing evidence:** the North America proof of 2026-09-01 (full digests of the three largest
  iOS files) is the evidence class.
- **Before submission:** one fresh full-artifact North America proof runs within its 24-hour
  freshness window. It downloads about 4 GB and needs the maintainer's go.
- **Residual risk, accepted:** Europe and East Asia are unverified. Hugging Face serves through a
  global CDN, and support reports from those regions are the monitor. No paid regional hosts are used.

### ASR-04: per-asset attestations from the maintainer

The maintainer attests each shipped asset's provenance in a private record, using the inventory
below. The product artwork is mixed: own work, stock and AI-assisted. The tracked record keeps only
a decision ID and the evidence digest. Every asset is either attested or replaced before submission.

For each group the maintainer answers who made it (self, another person, an AI tool and which one,
or stock with its site and license) and roughly when. Each fingerprint is the first 12 hex characters
of SHA-256 over the group's sorted `sha256  path` lines at `36236682`. A changed asset changes its
fingerprint and needs a fresh answer.

| # | Asset group | Files | Fingerprint | What the repository knows |
|---|---|---|---|---|
| 1 | macOS app icon (`AppIcon.appiconset`) | 10 sizes | `1a43162c7cde` | Nothing |
| 2 | iPhone app icon (`VocelloIOSIcon.appiconset`) | 9 sizes | `28f60184c798` | Nothing |
| 3 | Website favicon and touch icon | 2 | `78b0860bb22e` | Brand art |
| 4 | Header mark (app and website) | 4 | `386564067946` | Brand art |
| 5 | Launch logo | 3 sizes | `b11af58e5a56` | Nothing |
| 6 | Launch background | 3 sizes | `fcb8bc9835ee` | Nothing |
| 7 | Website social preview | 1 | `125eba9aa004` | Brand art |
| 8 | README banner | 1 | `9f202800a5fd` | Nothing |
| 9 | Website app screenshots (PNG and AVIF) | 14 | `7c5615a0c52c` | Captures of Vocello's own UI; some are historical 2.x iPhone captures |
| 10 | Website voice samples | 4 | `141776ca135c` | Vocello outputs (`website/src/data/samples.js`) |
| 11 | In-app voice previews | 9 | `51dd17e72695` | Vocello outputs from documented neutral scripts (`Sources/Resources/voice-previews/README.md`) |

Two confirmations complete the record:
- **12.** Qwen and Hugging Face names appear only descriptively, never as Vocello's own brand.
- **13.** The maintainer wrote the scripts behind groups 10 and 11 and accepts presenting Qwen's
  built-in speaker names in the app.

## Account declaration

On 2026-08-27 the exact Vocello iOS app record was updated to and read back as
`USES_THIRD_PARTY_CONTENT`. This is the truthful App Store Connect declaration because Vocello downloads
and uses third-party Qwen model artifacts. Raw account responses, account identifiers, and credentials
remain untracked. The declaration satisfies the account-field task; it does not establish that Vocello
has every right Apple requires for every territory.

Apple's content-rights field requires an app that contains, shows, or accesses third-party content to
have the necessary rights or otherwise be legally permitted to use that content. See Apple's current
[App information reference](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information).

## Decision matrix

| Surface | Source-proven evidence | Current decision | Qualified reviewer and closure evidence |
| --- | --- | --- | --- |
| Six downloadable model artifacts | Every production fork and base artifact is bound to an immutable revision and model-card digest. The exact fork and base revisions declare Apache-2.0. The forks identify their base lineage and the quantized tensor modification. Vocello bundles the Apache-2.0 text and offline model attribution. | **Conditional source support; qualified redistribution decision pending.** Apache-2.0 grants broad reproduction, derivative, and distribution rights subject to its conditions, but the repository cannot adjudicate whether the app's license-delivery mechanism, NOTICE handling, trademark references, and every distribution territory fully satisfy them. | Open-source/IP counsel records a signed decision covering Apache-2.0 section 4 delivery and modification notices, absence or handling of upstream NOTICE material, Qwen/Hugging Face names and marks, the public quantized forks, and commercial App Store redistribution. Attach a dated decision reference without credentials or private correspondence. |
| AudioSeal watermark code and weights (3.0 candidate) | `MLXAudioMark` ports Meta's MIT-licensed AudioSeal generator, and every model package downloads its fp16 weights (`marking/audioseal_wm16_generator_fp16.safetensors`, digest pinned in the catalog). Meta's copyright and MIT notice are in `Packages/VocelloQwen3Core/NOTICES.md` and therefore in the bundled attribution manifest. The port's reference is the `audioseal` 0.2.0 Python package (GitHub `facebookresearch/audioseal` commit `a0ce2564ff2b`, which sets that version) with weights from `facebook/audioseal` `generator_base.pth`, whose content (SHA-256 `7a845b5fbe93…`) is identical at every Hugging Face revision; reconstructed on 2026-09-24 from public metadata and recorded in `ORIGINS.md` (the `cc2700db` hash cited before 2026-09-24 was the UTMOSv2 pin). The fp16 conversion is shape-consistent with that checkpoint but not byte-reproduced. | **Attribution present; upstream revision identified from metadata.** | Optional stronger proof: reproduce the fp16 conversion from `generator_base.pth` and match the catalog digest (needs the maintainer's consent to download the checkpoint). Counsel confirms the MIT notice delivery for the redistributed weights with the other model artifacts. |
| Built-in voice previews and speaker presentation | The nine bundled WAVs are locally generated by Vocello from documented neutral scripts and built-in Qwen speakers. The official model card names and describes those speakers. | **Qualified output/personality-rights decision pending.** Reproducibility and model licensing do not themselves prove rights to commercially distribute voice output or use speaker identities/names in product presentation. | IP/publicity-rights counsel reviews the official Qwen terms and obtains written vendor clarification if needed. Record whether audio, speaker names, and personality presentation are permitted in each intended territory; otherwise replace the previews/presentation with independently cleared voices. |
| Marketing audio other than cloning | `website/src/data/samples.js` identifies the mode, displayed speaker, delivery, script, and tracked audio asset. | **Creator provenance and output-rights decision pending.** The repository does not contain a signed script-ownership attestation, generation receipt, or qualified conclusion for using Qwen outputs in advertising. | The maintainer signs the factual asset attestation below for every clip; counsel then approves the relevant model/output terms and marketing use. Replace any clip lacking both records. |
| Voice-cloning marketing sample | Removed from the website on 2026-09-22 (the Listen section no longer ships a Voice Cloning clip). | **Fail-closed: removed.** The repository did not identify the reference speaker, source recording, consent scope, or license. | Record the reference speaker's explicit consent for cloning and commercial marketing, source-audio ownership/license, permitted territories/duration, and revocation handling. Remove the sample until that record exists. Do not put private consent records in the repository. |
| App and marketing artwork | The repository contains app icons, launch artwork, product marks, screenshots, and website images. Git history alone is not authorship or license proof. Apple system fonts and SF Symbols are referenced through platform APIs and are not redistributed as standalone assets. | **Qualified provenance decision pending for non-system assets.** | The maintainer or rights owner signs the factual asset attestation below, including creator, source files, commission/assignment, stock or generator terms, and trademark authority. Counsel reviews third-party/AI-tool terms where applicable. Replace any asset with an incomplete chain. |

The official upstream references currently used for the model review are the
[Qwen3-TTS CustomVoice model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice),
[Qwen3-TTS Apache-2.0 license](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE),
[Hugging Face repository-license guidance](https://huggingface.co/docs/hub/repositories-licenses),
and [Hugging Face Terms](https://huggingface.co/terms-of-service). The immutable catalog receipts,
not these live pages, own production artifact identity.

## Factual asset attestation required from the maintainer

For every preview, marketing-audio file, script, icon, illustration, screenshot, and promotional
composition, preserve an untracked signed record containing:

- exact file SHA-256 and repository-relative public asset name;
- creator and current rights owner;
- creation date and source application or service;
- whether the work was original, commissioned/assigned, licensed stock, or AI-assisted;
- the applicable license, assignment, service terms, and any attribution requirement;
- for generated audio, exact model family/revision, mode, script owner, and generation receipt when
  available;
- for cloned audio, reference-source owner, recorded speaker consent, commercial-marketing scope,
  territories, duration, and revocation process;
- a declaration that the signer has authority to make the factual attestation.

Private names, signatures, consent records, contracts, and service-account data stay outside the
repository. The tracked record may contain only a privacy-safe decision ID, reviewer role, decision
date, allowed scope, expiry/review date, and digest of the private evidence packet.

## Qualified decision record

A qualified decision is complete only when it records:

1. reviewer identity and qualification in the private file;
2. every reviewed artifact digest and governing upstream revision;
3. allowed uses, territories, distribution channels, attribution/NOTICE duties, and restrictions;
4. the decision date, review trigger, and any expiry;
5. a privacy-safe decision ID and evidence-packet digest that can be referenced from
   `config/third-party-attribution-policy.json`.

ASR-04 may move to `done` only after all rows have an affirmative qualified decision or the affected
asset/surface has been removed and the removal is verified in source and the release artifact.

Currency review (2026-09-04, status reconciled 2026-09-11): the roadmap has kept ASR-04 `parked`
since 2026-09-26 — source remediation is shipped, and only the qualified counsel decisions above remain open. A fresh authenticated,
read-only App Store Connect inventory again found the third-party-content declaration; it proves only
the account field and does not replace the qualified model-redistribution, voice/publicity,
cloned-reference consent, marketing-audio, or artwork decisions above. The exact source-bound bundled
attribution implementation remains complete. ASR-11 separately owns pricing/availability,
accessibility, privacy, financial, and regional account fields.

## Consolidated RF-02 decision checkpoint

The September 5 read-only inventory again confirms `USES_THIRD_PARTY_CONTENT`, the configured
Support URL, and no existing App Store build for source 3.0.0/build 24. The current iOS version
record does not match 3.0.0; pricing/availability and configured-version readiness remain
unavailable. This packet groups the outstanding decisions without creating another status ledger
or authorizing account changes. Retained summaries live in the ignored `rf02-20260905-readonly`
artifact directory.

| Decision and authority | Owner class | Evidence needed to close |
| --- | --- | --- |
| Download-provider processing and privacy labels — ASR-02 | Privacy counsel, with provider clarification if needed | Establish request metadata retained by Hugging Face/CDN operators, retention periods and purposes, linkage/tracking treatment, relevant territories, and resulting App Store questionnaire answers. Reconcile the signed candidate, policy and live labels; do not infer “Data Not Collected” from local synthesis. |
| Model redistribution, notices, previews, marketing audio and artwork — ASR-04 | Maintainer/asset owner plus qualified IP/privacy reviewer | Complete every asset row and signed factual attestation above; record allowed uses and restrictions with private-evidence digests. Existing bundled notices do not replace these decisions. |
| Source/account version and build — ASR-08 | Release maintainer | Authorize reconciliation to 3.0.0, confirm read-only in App Store Connect (web portal or the asc-* skills) that the build number is still unused immediately before archive, and verify the processed build. The unused number is not reserved; Apple rejects a reused one at upload. |
| Distribution profile and entitlements — ASR-10 | Signing/release owner | Decode the exact profile, match private-key identity and entitlements, then verify the command-bound archive/IPA. Local identity availability and earlier remote capability reads are not archive evidence. |
| Age rating, content declaration and encryption — ASR-11 | Maintainer with qualified reviewer for ambiguous declarations | Review the actual user-content/generation capabilities, current questionnaire and source encryption declaration against the processed candidate. A readable account field is not proof its answers are correct. |
| Pricing/availability, agreements/financial, DSA and regional obligations — ASR-11 | Account holder; counsel where required | Resolve unavailable account surfaces, document selected territories and applicable obligations, and capture approved readback. The agent cannot accept agreements, select trading status or provide legal clearance. |

Apple's [privacy definitions](https://developer.apple.com/app-store/app-privacy-details/) require
considering third-party practices and retention beyond real-time request service. Hugging Face's
[current privacy policy](https://huggingface.co/privacy), reviewed September 5, describes logging
IP/session/device information and retention for service, security, legal and other stated purposes.
It does not establish a specific retention duration for Vocello's unauthenticated model downloads.
Whether those network flows fit particular Apple disclosure categories requires a documented
assessment of the actual request path and provider practice. No private user audio is sent to
Hugging Face by the model-download flow; that fact alone does not decide metadata disclosure.

Keep any vendor inquiry or private legal correspondence untracked and send it only on separate
authorization. One consolidated private review can resolve these rows; a missing decision remains
an external dependency, not an inferred approval. Publication/submission stays separately gated.

### September 6 owner checkpoint and timing

Use the six decision rows above as one maintainer checkpoint, not repeated account polling.
Since 2026-10-12 the maintainer records these decisions directly; no paid reviewer is engaged. The account holder supplies pricing,
territories, review contact and applicable agreement/regional decisions. The signing owner supplies
the approved profile/private-key match and authorizes candidate operations separately. Record only
sanitized decision, date, scope and evidence digest in the repository; private correspondence stays
untracked. Missing responses keep ASR-02/04/08/10/11 blocked, not implicitly approved.

ASR-09 verifies North America only for 3.0 (see the 2026-10-12 decisions above). Run its
full-artifact host proof only near submission: its freshness window is **24 hours**. Do not purchase
hosts, send vendor or legal inquiries, edit account fields or accept agreements without separate
authority.
Repeat the manual read-only build-number check in App Store Connect immediately before archive, not
continuously while waiting.

## Fail-closed release choices

If the maintainer cannot attest an asset or decision before submission:

- keep the App Store declaration as `USES_THIRD_PARTY_CONTENT`;
- do not weaken or omit Apache-2.0 attribution and modification notices;
- remove the voice-cloning marketing sample unless its reference-source and consent chain is complete;
- remove public built-in previews or speaker-personality marketing that lacks output/publicity clearance;
- replace unproven artwork with newly created first-party work carrying a signed provenance record;
- do not mark ASR-04 complete or describe the app as submission-ready.
