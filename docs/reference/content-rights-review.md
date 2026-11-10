---
status: active
owner: release-qa
reviewed: 2026-11-10
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
September 6: iOS uploads require Xcode 26 or later and the iOS 26 SDK or later. CI's pinned
Xcode 26.6 (`config/toolchain.json`) and the local Xcode 27.1 both clear that minimum;
signed-candidate verification is still separate. Apple's
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

3.0 is available in 148 territories outside the EU (since 2026-10-27), but download verification
covers North America only, where App Review runs.
- **Existing evidence:** the North America proof of 2026-09-01 (full digests of the three largest
  iOS files) is the evidence class.
- **Before submission:** one fresh full-artifact North America proof runs within its 24-hour
  freshness window. It downloads about 4 GB and needs the maintainer's go.
- **Residual risk, accepted:** Europe and East Asia are unverified. Hugging Face serves through a
  global CDN, and support reports from those regions are the monitor. No paid regional hosts are used.

### ASR-04: per-asset attestations from the maintainer

The maintainer attests each shipped asset's provenance in a private record, using the inventory
below. The tracked record keeps only a decision ID and the evidence digest.

**Attested 2026-11-01** (decision `ASR04-2026-11-01`, maintainer as sole owner, scope: the apps,
the website, the README and App Store marketing, worldwide). Every group below and confirmations 12
and 13 are attested. The private record lists each file's SHA-256 at build 29 (`a60dd204`); its own
SHA-256 is `0aacc904771e863bb56b35021557883be0d39599b34c39139ec587300c6322e1`. Groups 1 to 8 are
AI-assisted original work, group 9 is captures of Vocello's own interface, and groups 10 and 11 are
Vocello outputs from the maintainer's own scripts.

Each fingerprint is the first 12 hex characters of SHA-256 over the group's sorted `sha256  path`
lines (joined by newlines, no trailing newline) at `a60dd204`. A changed asset changes its
fingerprint and needs a fresh answer. No app asset changed between the October 12 inventory and
build 29; group 9 gained the 1040-pixel AVIF variants and a new custom-voice capture. Build 29 was
the candidate on the attestation date; the checkpoint
([`../development-progress.md`](../development-progress.md), Resume now) owns the current
candidate's state, and no inventoried path changed between `a60dd204` and build 30's `14c51659`.

| # | Asset group | Files | Fingerprint | Paths |
|---|---|---|---|---|
| 1 | macOS app icon | 10 | `f80a3d65442a` | `Sources/Assets.xcassets/AppIcon.appiconset/*.png` |
| 2 | iPhone app icon | 9 | `6e101f471202` | `Sources/Assets.xcassets/VocelloIOSIcon.appiconset/*.png` |
| 3 | Website favicon and touch icon | 2 | `44367a6d13b2` | `website/public/assets/apple-touch-icon.png`, `favicon-32.png` |
| 4 | Header mark (app and website) | 4 | `4a26c4871218` | `Sources/Assets.xcassets/VocelloHeaderMark.imageset/*.png`, `website/public/assets/vocello-header-mark.png` |
| 5 | Launch logo | 3 | `f8e963075a0a` | `Sources/Assets.xcassets/VocelloLaunchLogo.imageset/*.png` |
| 6 | Launch background | 3 | `fcb8bc9835ee` | `Sources/Assets.xcassets/VocelloLaunchBackground.imageset/*.png` |
| 7 | Website social preview | 1 | `125eba9aa004` | `website/public/assets/social_preview.png` |
| 8 | README banner | 1 | `9f202800a5fd` | `docs/readme_banner_vocello.png` |
| 9 | Website app screenshots | 20 | `cd5489e7d394` | `website/public/assets/screens/*.png`, `*.avif` |
| 10 | Website voice samples | 4 | `d7eefde05e19` | `website/public/assets/voice-samples/*.wav` |
| 11 | In-app voice previews | 9 | `dccd9303c7fc` | `Sources/Resources/voice-previews/*.wav` |

Two confirmations complete the record, both given on 2026-11-01:
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

This matrix records each surface's evidence and decision before closure. ASR-04 closed on
2026-11-01 with the maintainer's attestation `ASR04-2026-11-01`, which covers every row (see
below), so a "pending" in this table is history, not open work.

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

ASR-04 closed on 2026-11-01: source remediation and the bundled attribution are shipped, and the
maintainer's attestation `ASR04-2026-11-01` covers every asset group and both confirmations. The third-party-content declaration proves only the account field; it
does not replace the model-redistribution, voice/publicity, cloned-reference consent,
marketing-audio or artwork decisions. ASR-11 separately owns pricing/availability, accessibility,
privacy, financial and regional account fields.

## Consolidated RF-02 decision checkpoint

On 2026-10-12 (RF-02) version 3.0.0 replaced the 1.0 draft, the app became free and iPhone only,
the age rating became 4+, and App Privacy was published as Data Not Collected; the account keeps
`USES_THIRD_PARTY_CONTENT` and the configured Support URL. The rows below record what each decision
needed, with the outcome where it is decided. This packet groups the decisions without creating
another status ledger or authorizing account changes.

| Decision and authority | Owner class | Evidence needed to close |
| --- | --- | --- |
| Download-provider processing and privacy labels — ASR-02 | Privacy counsel, with provider clarification if needed | Establish request metadata retained by Hugging Face/CDN operators, retention periods and purposes, linkage/tracking treatment, relevant territories, and resulting App Store questionnaire answers. Reconcile the signed candidate, policy and live labels. **Decided 2026-10-12:** Data Not Collected, on the facts recorded under ASR-02 above, and published the same day. |
| Model redistribution, notices, previews, marketing audio and artwork — ASR-04 | Maintainer/asset owner plus qualified IP/privacy reviewer | Complete every asset row and signed factual attestation above; record allowed uses and restrictions with private-evidence digests. Existing bundled notices do not replace these decisions. **Done 2026-11-01:** attestation `ASR04-2026-11-01` (above). |
| Source/account version and build — ASR-08 | Release maintainer | **Done:** version 3.0.0 replaced the 1.0 draft (2026-10-12), and ASR-08 closed on 2026-10-14. Remaining: confirm read-only in App Store Connect (web portal or the asc-* skills) that the build number is still unused immediately before archive, and verify the processed build. The unused number is not reserved; Apple rejects a reused one at upload. |
| Distribution profile and entitlements — ASR-10 | Signing/release owner | **Done 2026-10-24:** release run 40103005257 archived, exported and verified build 24's IPA (entitlements, signing identity, profiles); every later candidate repeats the verification. |
| Age rating, content declaration and encryption — ASR-11 | Maintainer with qualified reviewer for ambiguous declarations | Age rating 4+ set on 2026-10-12 (RF-02); `USES_THIRD_PARTY_CONTENT` declared. **Done 2026-11-01:** build 29, the candidate on that date, reads back VALID with `usesNonExemptEncryption` false, and App Store Connect asked no further export-compliance question. Repeat the read on any later candidate ([runbook §1](ios-appstore-submission.md#1-privacy--compliance-app-store-connect)); the checkpoint ([`../development-progress.md`](../development-progress.md), Resume now) owns the current candidate's state. |
| Pricing/availability, agreements/financial, DSA and regional obligations — ASR-11 | Account holder; counsel where required | Pricing and availability set on 2026-10-12: free, 175 territories, iPhone only (RF-02). **Decided 2026-10-27:** 3.0 ships outside the EU for now; the 27 EU territories were removed (148 remain) on the maintainer's explicit instruction. The EU release needs the trader step first (BKL-41). Remaining: the account holder's agreement, banking and tax steps, whose status stays in the maintainer's private record, never in Git. The agent cannot accept agreements or provide legal clearance. |

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

### Owner checkpoint and timing

Use the decision rows above as one maintainer checkpoint, not repeated account polling. Since
2026-10-12 the maintainer records these decisions directly; no paid reviewer is engaged. The account
holder supplies pricing, territories, review contact and applicable agreement/regional decisions;
the signing owner authorizes candidate operations separately. Record only sanitized decision, date,
scope and evidence digest in the repository; private correspondence stays untracked. A missing
response keeps its item (ASR-04, ASR-11) blocked, not implicitly approved.

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
