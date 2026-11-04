---
status: active
owner: release-qa
reviewed: 2026-11-04
summary: Read-only assessment, on 2026-11-04, of how ready Vocello for iPhone 3.0 (build 29, v3.0.0-ios.8) is for App Review, using an external November 2026 App Review rules report as the reference and checking its claims against Apple's live guideline text and the repository. Verdict, gaps ranked by risk, tracked blockers and tiered recommendations; it changes no code, roadmap item or App Store Connect field. On 2026-11-04, at the maintainer's request, the doc drift in section 6 was fixed, the review-notes safeguards paragraph was entered in App Store Connect and read back, and the wording check in section 8 was done.
sourceOfTruth:
  - docs/reference/ios-appstore-submission.md
  - docs/reference/app-store-listing.md
  - docs/reference/content-rights-review.md
  - config/roadmap.json
  - Sources/iOS/Info.plist
  - Sources/PrivacyInfo.xcprivacy
---
# App Review readiness for Vocello for iPhone 3.0 (2026-11-04)

The maintainer supplied an external research report, "Getting Vocello Through Apple App Review in
November 2026: Rules, Risks, and a Submission Checklist" (11 pages). Its facts about Vocello come
from the June 14, 2026 runbook. This audit uses it as a reference. It checks the report's claims
against Apple's live pages, and checks each recommendation against the current repository and
roadmap. The candidate is build 29 (`v3.0.0-ios.8`, `a60dd204`), targeted for App Review on
November 12.

Code citations are to `main` at `6a50f39b`. Since build 29, `main`'s product sources differ only by
`c878917a`, which changes diagnostics-build startup paths (`Sources/iOS/IOSAppBootstrap.swift`,
`Sources/iOSSupport/Services/AppPaths.swift`). None of the behaviour cited below is affected.
Account, agreement, tax and DSA status live in the maintainer's private record and are not stated
here.

## 1. Verdict

Vocello is not ready to submit today, but the reasons are the process items the roadmap already
tracks, not new rule violations.
- **What already conforms:** the toolchain, the privacy manifest, encryption, permissions, the
  privacy policy, the download architecture, branding, the purchase sheet and the review notes.
- **What carries judgment risk:**
  - **The October 2026 change to Guideline 1.2:** it now names "AI content creation apps" and
    asks for filtering, reporting, blocking and published contact. Vocello has almost none of
    these. This is the most likely new rejection reason.
  - **Two UX gaps:** Studio's install button starts a 2 GB download with no size or prompt
    (4.2.3(ii)), and voice-cloning consent is a single global switch.
- **None of these is a release blocker** under the release plan's definition. They are rejection
  risks for the maintainer to weigh against the cost of a new candidate.

## 2. How the uploaded report was checked

**Confirmed against Apple's live App Review Guidelines (fetched 2026-11-04):**
- **1.2:** now reads "This includes social media, user-generated content platforms, and AI content
  creation apps". It requires "A method for filtering objectionable material from being posted to
  the app", "A mechanism to report offensive content", "The ability to block abusive users" and
  "Published contact information".
- **2.5.19:** forbids "hidden, dormant, or undocumented features", with removal and account
  termination as the penalty.
- **4.2.3(ii):** "If your app needs to download additional resources in order to function on
  initial launch, disclose the size of the download and prompt users before doing so."
- **2.5.14:** requires explicit consent and "a clear visual and/or audible indication when
  recording".
- **2.3.1(a), 4.1(c) and 5.1.2(i):** read as the report quotes them.
- **No guideline names voice cloning or deepfakes.** 4.1(b) covers impersonating apps, not people.

**Confirmed on Apple's upcoming-requirements page:** since April 28, 2026, uploads need Xcode 26 or
later with the iOS 26 SDK. Since September 9, 2026, iPhone apps must target iOS 13 or later.

**Not confirmed:**
- **The age-rating descriptors** that the report says arrive in App Store Connect on November 16,
  2026, with answers due January 12, 2027. The upcoming-requirements page lists only the
  January 31, 2026 age-rating update.
- **The 3.2(f) termination statistics and triggers.** The report itself labels them anecdotal.

**Advice that doesn't fit Vocello:**
- **Subscriptions:** the report's paywall, trial, auto-renew and 3.1.2 advice assumes them.
  Vocello sells one non-consumable, Design & Clone Export.
- **EU commissions and the DSA trader display:** they don't apply to 3.0, which ships outside the
  EU (BKL-41).
- **US link-out commissions:** irrelevant, because Vocello sells only through in-app purchase.
- **Stale items:** the increased-memory-limit entitlement and the privacy policy's mention of the
  download host are already in place (section 3).

## 3. Already satisfied

| Report item | Status | Evidence |
|---|---|---|
| Xcode 26 / iOS 26 SDK uploads | Meets it | Release archives use Xcode 26.6 (`config/toolchain.json:5`); deployment target iOS 26.0 (`project.yml:578`) |
| Privacy manifest, required-reason APIs | Meets it | `Sources/PrivacyInfo.xcprivacy` declares UserDefaults (CA92.1), system boot time (35F9.1), file timestamps (C617.1, 3B52.1) and disk space (E174.1). Every use found in the iOS sources falls under these. Tracking is false, with no tracking domains. Build 29 processed VALID |
| Export compliance | Meets it | `ITSAppUsesNonExemptEncryption` false (`Sources/iOS/Info.plist:72-73`). Only CryptoKit and HTTPS (`Sources/QwenVoiceCore/FileStreamIO.swift:17-29`). Build 29 needed no further answer |
| Purpose strings that explain cloning | Meets it | Microphone and speech recognition strings (`Sources/iOS/Info.plist:69-71`), translated into 10 languages in `Sources/iOS/InfoPlist.xcstrings` |
| 2.5.14 recording indication | Meets it | The recorder shows the phase label, a running timer, a live level meter and Stop (`Sources/iOS/Overlays/IOSRecordingOverlay.swift:155-245`). iOS shows its own microphone indicator. The system permission prompt is the consent |
| 5.1.1 privacy policy, in the app and in App Store Connect | Meets it | Settings (`Sources/iOS/Settings/SettingsScreen.swift:911-920`) and the purchase sheet (`Sources/iOS/Commerce/IOSExportGate.swift:321-355`) link to the policy. It names Hugging Face as the only download host and says the host sees the IP address (`website/public/privacy/index.html:120-127`) |
| Account deletion, demo account | Not applicable | No login or account |
| 5.1.2(i) third-party AI | Not applicable | Inference is local; downloads send no identifiers |
| 2.5.2 / 2.5.19, weights as data, no hidden features | Meets it, low residual risk | The catalog is bundled, revision-pinned and SHA-256-pinned to huggingface.co (`Sources/Resources/qwenvoice_production_model_catalog.json`). Diagnostics need a compile flag that only local scripts set (`Sources/QwenVoiceCore/RuntimeDebugGate.swift:14-79`), and the release verifier rejects it (`scripts/verify_ios_release_artifacts.py:41,49`). No remote flags, hidden gestures or debug menus were found. What remains is unreachable diagnostics-runner code and an unused remote-catalog branch |
| Branding, 4.1(c) | Meets it | The name is Vocello, the subtitle "Local AI voice studio", and the keywords carry no brands (`docs/reference/app-store-listing.md:37-89`). The display name is Vocello (`Sources/iOS/Info.plist:25-26`). Qwen appears in the licenses screen (`Sources/Resources/third_party_attributions.json`) |
| Purchase sheet, 3.1.1 | Meets it | StoreKit price on the buy button (`Sources/iOS/Commerce/IOSExportGate.swift:209-221`), what it unlocks, "One-time purchase. No subscription.", Restore (`IOSExportGate.swift:249-261`) and the privacy link. It's reachable from Settings without a model |
| 2.3.1(a) specific review notes | Meets it | Entered 2026-11-01 and 2026-11-02 and read back byte-identical. They cover sizes, Wi-Fi, free space, no login, the mode steps, the iPhone 15 Pro preview pause, consent, the purchase and Restore (`docs/reference/app-store-listing.md:106-121`) |
| Accept pending agreements | Tracked | RF-02 and the maintainer's private record |

## 4. Gaps, ranked by risk

### G1. Guideline 1.2 safeguards for AI content apps (highest new risk)

**Evidence:**
- **No filter:** nothing screens the script text or the Voice Design description for objectionable
  content.
- **Narrow celebrity guard:** the only guard catches a few markers ("celebrity", "impersonate",
  "imitate the voice", "clone the voice") and two likeness phrases
  (`Sources/QwenVoiceCore/Qwen3TTSRuntimeProfile.swift:395-411`, called from
  `Sources/QwenVoiceCore/GenerationSemantics.swift:891-918`). "Sounds like" a named person gets
  through, and the refusal text is English-only.
- **No report path:** there's no "report this output" or feedback path.
- **Contact is web-only:** the Help & Support row opens the support page
  (`Sources/iOS/Settings/SettingsScreen.swift:945-955`). There's no in-app email link.
- **Never discussed:** no submission doc mentions 1.2.

**Why it may not bite:** the guideline is written around content "posted to the app" and abusive
users on a service. Vocello has no feed, posting, accounts or other users. Output stays on the
phone unless the user shares their own file. Blocking users has nothing to apply to. Whether
reviewers apply 1.2 fully to a single-user local generator is untested, so assume they might.

**Fix without a new build:** add a safeguards paragraph to the review notes, covering:
- local and single-user, with no posting, sharing service, feed or accounts;
- the contact published on the support page and linked in Settings;
- the celebrity and impersonation refusal;
- the cloning consent requirement;
- the watermark and provenance metadata on every take.

**Fix that needs a new build:**
- an in-app contact or "Report a problem" action, for example a `mailto:` on takes or in Settings;
- a basic objectionable-term check on Voice Design descriptions;
- a broader likeness check.

### G2. Guideline 4.2.3(ii): the download size and a prompt before downloading

**Evidence:**
- **Studio:** with no model installed, the primary button reads "Install Built-in Voice" with no
  size (`Sources/iOS/IOSStudioCanvas.swift:357-366`). Tapping it switches to Settings and starts a
  download of about 2 GB at once (`Sources/iOS/App/AppModel.swift:74-80`).
- **Onboarding:** it says to "Download the 4-bit Speed model" and mentions Wi-Fi, but never the
  size (`Sources/iOS/IOSRootNavigationModels.swift:1190-1192`).
- **Settings:** the Voice Models rows do show the size before Install
  (`Sources/iOS/IOSSettingsViews.swift:698-702`), and the tap there is an explicit choice.
- **Listing:** the description and review notes give exact sizes.

**Risk:** moderate to low. A reviewer who follows review notes step 2 uses the Settings path. A
reviewer who taps Studio's button first sees a 2 GB download start with no size.

**Fix without a new build:** the review notes already route the reviewer through Settings. The
safeguards paragraph can add that every install shows its size there.

**Fix that needs a new build:** put the size on Studio's install button and onboarding, and
confirm before a download starts from Studio.

### G3. Voice-cloning consent and AI disclosure

**Evidence:**
- **What the switch gates:** consent is one global switch, "I own or have permission to clone the
  voices I use" (`Sources/iOS/Settings/SettingsScreen.swift:350-357`). It gates clone generation
  and saving a voice (`Sources/QwenVoiceCore/VoiceCloningConsentPolicy.swift:104-109`), but not
  recording, importing or local transcription of a reference.
- **What's missing:** a per-voice attestation and a spoken consent phrase. There are no
  famous-voice presets: the nine built-in speakers come with the model, and ASR-04 approved
  presenting them.
- **Disclosure is invisible:** every take carries an AudioSeal watermark and an "AI-generated
  audio" WAV metadata chunk
  (`Sources/QwenVoiceCore/AudioPublicationMarking.swift:77-115`), and every export path shares
  that marked file. Nothing visible in the player, History or the share flow says the take is
  AI-generated. The only visible statement is a Settings note
  (`Sources/iOS/Settings/SettingsScreen.swift:358-360`).

**Risk:** moderate. Apple names no cloning rule, but 5.1.1 (consent for personal data) and its
stated stance on AI that harms real people make this an area a reviewer may probe. Similar apps on
the store ship with a permission statement and a warning, which Vocello has.

**Fix without a new build:** the review notes explain the switch, the watermark and provenance,
and the refusal.

**Fix that needs a new build:**
- a per-voice attestation when a voice is saved;
- a visible "AI-generated" label on takes or the share sheet;
- the same consent before recording a reference.

### G4. Age rating

**Evidence:**
- **Rating:** 4+, set on 2026-10-12 (RF-02) and read back on 2026-10-30 (ASR-11).
- **Answers (read 2026-11-04):** every content answer is None and every capability answer is no,
  including User-Generated Content. Apple defines that one as "the broad distribution of content
  created by users", which Vocello doesn't do, so no is the correct answer.
- **The report's suggestion:** 13+ for an unfiltered free-text generator, since 1.2 now frames
  AI generation as user content.

**Risk:** low to moderate. Text-to-speech tools are commonly 4+. A reviewer applying 1.2's framing
could still question 4+ for unfiltered output.

**Result (2026-11-04):** the answers are recorded in the runbook and 4+ stays. Apple's definitions
page names no AI or generative descriptor in the part read. A rating change is a metadata edit if a
reviewer asks for one. If the new descriptors the report mentions appear, answer "no" to dating and
companion content.

### G5. No demo video

The docs plan no App Review demo video. Apple's 2.1 rejection template asks for one recorded on a
physical device for hardware-dependent flows. Vocello needs a 2 GB download before anything works,
and the live preview pauses on an iPhone 15 Pro. A 2 to 3 minute video on the iPhone 17 Pro,
linked in the review notes, would cover all of that:
- install with its size;
- a take in each mode;
- Voice Design's description chip;
- cloning consent with the permission prompts;
- the purchase and Restore.

It needs the maintainer's hands for the permission prompts and the purchase sheet.

### G6. No submission or rejection log

The report counts rapid resubmissions, renames and cosmetic fixes as reported account-risk
signals. The repository records TestFlight beta reviews but has no App Review log. RF-16's notes
can carry one: each submission, rejection, the cited guideline and the complete fix. Per the
repository rules, no new ledger is needed.

### G7. Polish (not review-blocking)

- **Raw download errors:** failures show unlocalized English text, including SHA-256 hex
  (`Sources/QwenVoiceCore/HuggingFaceDownloader.swift:209-221`).
- **English-only refusal:** the impersonation refusal has no localized presentation.
- **Wrong section name:** consent refusal copy says "Settings → Privacy", but the section is
  named Privacy & Permissions.
- **"Use Qwen3's path":** the language picker shows a "Use Qwen3's %@ path." subtitle
  (`Sources/iOS/IOSRootNavigationModels.swift:310`). It is descriptive and allowed by 4.1(c), which
  covers names and icons, and by ASR-04's confirmation 12. It still reads as internal wording.
- **No Terms of Use link on the purchase sheet:** optional for a non-consumable, since Apple's
  standard licence applies.

## 5. Tracked blockers before the submission (RF-16)

The report does not cover these; they come from the roadmap.

| Item | Due | What is left |
|---|---|---|
| RF-02 | Nov 6 | The remaining account steps that activate the Paid Apps agreement |
| Purchase metadata (ASR-05, ASR-11) | Nov 9 | Design & Clone Export is MISSING_METADATA: its review screenshot from the processed build, and attaching it to the version |
| ASR-05 | Nov 9 | One 6.3-inch screenshot set (1206x2622) from the signed candidate on the iPhone 17 Pro |
| ASR-11, ASR-02 | Nov 5 to 6 | The App Privacy readback and the accessibility declaration (no Larger Text or Sufficient Contrast claims, per BKL-31) |
| RF-15 | Nov 9 | The purchase rows (export with and without the purchase, Restore, Cancel), the attended rows (AUD-01's onboarding file, AUD-02's hand checks, VoiceOver, the offline relaunch) and the machine screen |
| RF-17 | Nov 9 | Five of six exact-tag records passed on 2026-11-03 and expire on November 10. The language record failed and needs a maintainer decision |
| ASR-06, RF-35, RF-12, AUD-07, AUD-09 | Nov 9 | Signed-device file-protection proof, a completed cellular download, the Airplane Mode export, and device proofs |
| ASR-09 | Nov 12 | The North America download proof within 24 hours of submitting |

Phone state to restore first:
- Reinstall TestFlight build 29; the phone runs a development build of the tag.
- Set App Language back to English.

## 6. Doc drift found on the way

Fixed on 2026-11-04 at the maintainer's request.

- **The runbook's current-state paragraph** still names build 27 as the next candidate
  (`docs/reference/ios-appstore-submission.md:28-31`).
- **Export compliance is still listed as open** in two places
  (`docs/reference/ios-appstore-submission.md:162`, `docs/reference/content-rights-review.md:196`),
  though it was answered for build 29.
- **The content-rights decision table** still says "pending"
  (`docs/reference/content-rights-review.md:126-133`). Sections above it supersede the table.
- **ASR-02's and RF-16's notes** in `config/roadmap.json` still say "on hold".

## 7. Recommendations

### This week, without a new build

1. **Review notes:** add a safeguards paragraph covering G1 to G3: local single-user use with no
   posting or accounts, the published contact, the celebrity and impersonation refusal, the
   cloning consent switch, the watermark and provenance, a bundled hash-pinned catalog with no
   remote features, and that every install shows its size in Settings. It is an App Store Connect
   write, made on the maintainer's go. Entered on 2026-11-04 and read back byte-identical
   ([`app-store-listing.md`](../reference/app-store-listing.md), the notes' last paragraph).
2. **Demo video:** record it on the iPhone 17 Pro (G5) and link it in the review notes.
3. **Age rating:** done on 2026-11-04; the answers are recorded and 4+ stays (G4).
4. **Small Business Program:** confirm enrollment before the first sale. It sets the 15%
   commission; its status lives in the private record.
5. **Tracked blockers:** close them in the planned phone session (section 5). Decide on RF-17's
   language record, and validate the manifest by November 10 or rerun the expired records.
6. **Doc drift:** fix it (section 6).

### The maintainer's decision: product safeguards before or after 3.0

**Option A:** fix G1 to G3 in the product before submitting. That means a build 30 and a new tag,
then all of RF-17's records and RF-15's rows again. Corrected on 2026-11-04: this first said the
build would likely move the submission past November 12. The six lanes took about an hour on
November 3 and the main phone session hasn't happened, so it fits, with little margin.

**Option B:** submit build 29 with the stronger review notes, and prepare complete fixes for G1 to
G3 for 3.0.1. If App Review cites 1.2, 4.2.3 or cloning consent, answer in Resolution Center with
a complete fix rather than a cosmetic one.

**Recommendation: B.** The guidelines' examples target posting, services and concealment.
Vocello's architecture (local, single-user, no remote switches) and its review notes answer them
directly. A new candidate now costs the whole evidence set and most of the margin.

**Maintainer decision (2026-11-04): B.** A real Download button, which would have copied takes to
Files instead of opening the share sheet, was considered and cancelled with any build 30. Build 29
stays the candidate.

### Account hygiene, from the report

- Submit one candidate. Don't withdraw and resubmit to jump the queue, and don't rename the app.
- Answer each rejection with a complete fix and a specific Resolution Center reply. Log it in
  RF-16's notes.
- Plan for one to three weeks of review on a first app, and treat November 12 as the submission
  date, not the launch date.

## 8. Wording check (2026-11-04)

At the maintainer's request, everything live in App Store Connect was read and each claim checked
against the app's source, labels, retained run evidence and public pages.

**Confirmed, unchanged:**
- **Listing:** the name, subtitle, description, keywords, URLs and copyright. The description's
  claims hold: nine speakers, ten speech and ten interface languages, the delivery presets and custom
  delivery, the reference file types, long-form projects, seed pinning, the iPhone 15 Pro minimum,
  about 2 GB per model (the phone shows 2.05 GB), 4.5 GB of free space (the code needs up to about
  4.15 GB), the free and paid boundary, the watermark, and rejected takes.
- **Purchase text:** the name and description in en-US, fr-CA and fr-FR match the app's own terms.
- **Age rating and content rights:** see G4; third-party content stays declared.
- **Public pages:** the privacy policy and support page load and agree with the listing, and the
  support page publishes an email address.

**Corrected in App Store Connect, read back byte-identical:**
- **Promotional text:** "one cloned from a clip you own" became "a clone of a voice you own or have
  permission to use", matching the consent switch and the description.
- **Review notes step 2:** one run-on sentence became two.
- **Review notes step 3:** the iPhone 15 Pro range became "about one and a half to a little over two
  times", since the measured steady rate is 2.2 (RF-40).
- **Review notes step 5:** it now says where to open the purchase, not only where Restore is.

**Left open:**
- **Secondary category Music:** the maintainer's choice from 2026-10-12. Vocello makes speech, not
  music, so Utilities or no secondary category may fit better. Guideline 2.3 asks for an honest
  category.
- **Website at launch:** the Marketing URL page calls the iPhone app a TestFlight beta, which stays
  true until release. Its "Free" comparison is framed around the Mac and is accurate there, but the
  iPhone line doesn't mention the optional purchase, so add it when that line changes at launch.
- **Release type:** automatic on approval, so the app goes live as soon as App Review approves it.
