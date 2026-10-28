---
status: active
owner: release-qa
reviewed: 2026-10-28
summary: Operator checklist for shipping Vocello for iPhone to TestFlight / the App Store — account prerequisites, App Store Connect privacy and compliance rows, App Review notes, and the credential-bound archive/upload steps.
sourceOfTruth:
  - project.yml
  - config/roadmap.json
  - Sources/iOSSupport/Services/IOSDeviceEligibilityPolicy.swift
  - scripts/ios_device_eligibility.py
  - scripts/verify_ios_release_artifacts.py
  - docs/reference/eu-ai-act-article50-assessment.md
---
# iOS App Store submission runbook

The end-to-end steps to ship **Vocello for iPhone** (`com.patricedery.vocello`) to TestFlight and
the App Store. `config/roadmap.json` owns the live status of every gate below (the release-first
plan's `RF-*` items and the remaining `ASR-*` items); this document is the operator checklist.

Source-of-truth rule: if this disagrees with the code, the code wins.

This runbook is release-only. Commits, pushes, CI, archive, and internal TestFlight
packaging/upload use deterministic verification and do not require a phone, models, or
XCUITest evidence. External TestFlight distribution, App Review submission, and public App Store
release require the exact-tag iOS manifest in
[`quality-promotion.md`](quality-promotion.md).

**Current state (2026-10-28):** `release.yml` has archived, verified and uploaded 3.0.0 builds 24,
25 and 26 (ASR-10 closed on build 24's release run 40103005257). Build 26 is in the TestFlight
Public Beta; build 27 (RF-37, the Game Mode opt-out) is the next candidate. The App Review
submission waits for the exact-tag iOS promotion (RF-17) and the maintainer's go (RF-16). Any App
Store Connect metadata change, upload or submission still needs its own authorization.
Physical-device XCUITest runs separately at coherent checkpoints; CI and archive packaging are
deterministic-only ([`testing-runbook.md`](testing-runbook.md)). Local development builds derive the
signing team from the keychain's Apple Development certificate (`scripts/ios_device.sh`).

Before any local generic-device compile or archive, verify the selected Xcode installation:

```sh
python3 scripts/lib/ios_platform_preflight.py check
```

The generic physical-device destination needs matching iOS Platform Support/runtime availability
even though it does not run a Simulator. If the check is blocked, restore the component through
Xcode → Settings → Components before signing or archiving; repository release scripts never
download it automatically.

## 0. One-time account prerequisites

- [ ] Apple Developer Program membership active; latest Program License Agreement accepted.
- [x] **iOS Distribution certificate** with its private key, held as the `IOS_DIST_CERT_P12` CI
      secret (§4). This checkbox does not authorize signing or upload.
- [x] App ID `com.patricedery.vocello` has **App Groups** + **Increased Memory Limit** capabilities enabled.
      The `increased-memory-limit` capability is self-serve (no Apple review). It MUST be on the App Store
      provisioning profile or the multi-gigabyte model load is Jetsam-killed on a signed build. The
      exact remote App ID reported both capabilities on 2026-09-04; archive verification remains the
      authority for what the signed candidate actually receives.
- [x] **App Store provisioning profile** for `com.patricedery.vocello` (Distribution → App Store),
      carrying `increased-memory-limit` and the App Group; it expires 2027-07-25. Every candidate's
      exported IPA proves both entitlements and the signing identity through
      `verify_ios_release_artifacts.py` (first on build 24, ASR-10). Regenerate the profile after
      any capability change.
- [x] App record exists in App Store Connect for `com.patricedery.vocello`, with one `en-US`
      localization. Version 3.0.0 (Prepare for Submission) replaced the unreleased 1.0 draft on
      2026-10-12, in category Productivity (secondary Music) (RF-02). Its train holds builds 24 to
      26; every candidate needs an unused build number (§4, ASR-08).
- [x] App Store installation eligibility matches the app's runtime hardware floor before the first
      public version. The built bundle requires exactly `arm64` and Apple's
      `iphone-performance-gaming-tier`; the runtime guard independently enforces iPhone 15 Pro or
      newer. Deterministic source and archive/IPA verification reject future drift (ASR-01).
      The bundle also sets `LSSupportsGameMode` to NO, because the gaming-tier capability otherwise
      shows the Game Mode banner at every launch; build 27 is the first candidate with it (RF-37).

## 1. Privacy + compliance (App Store Connect)

**Implemented and locally accepted (RF-13, closed 2026-10-16); live product entered (RF-02,
2026-10-12):** the iOS app remains free to generate and listen in all three modes, with free
Built-in output export. The StoreKit entitlement owner and output-provenance export boundary are
implemented, and the local StoreKit exports scenario passed (RF-13). The product has en-US,
fr-CA and fr-FR names and descriptions. Still open:
- the Paid Apps agreement and its banking and tax steps, which are the maintainer's (RF-02); 3.0
  ships outside the EU, so the EU trader step waits for the EU release (BKL-41);
- the product's review screenshot and the purchase checks on the processed TestFlight build (RF-12);
- review, which happens with the first submission.
Monetization and App Store submission apply only to iOS. The macOS app remains distributed through
GitHub Releases with unrestricted exports; neither macOS nor CLI gains an entitlement requirement.

The approved identifier is `com.patricedery.vocello.design_clone_export`, reference name
**Design & Clone Export**. The approved US base price is **USD 19.99**, with Apple-managed regional
pricing and no manual regional overrides. Readback confirmed USA/USD, one manual base price and
automatic schedules for 174 other territories. Family Sharing was not enabled during creation;
the API readback omits that flag; it was confirmed off in the web portal on 2026-10-12, when the
localized names and descriptions were entered (RF-02). Review remains pending until submission.
The local-only `Tests/Fixtures/VocelloExports.storekit` fixture carries an arbitrary price, is not
an approved live offer and is never bundled in the app or activated in shipping schemes. RF-02 owns
the remaining account and product metadata work. Settings → Design & Clone Export
provides the StoreKit-localized price, Restore, status, privacy/support links and dismissal.
See the [app guide](ios-app-guide.md#ios-export-purchase) for routes and compatibility.

Phone-independent checks: `scripts/macos_test.sh core-test --only IOSExportPurchaseTests` executes
production state/policy with deterministic StoreKit-boundary fixtures, including StoreKit-fixture
parity, and `--only IOSSavedOutputsDestinationTests` proves the automatic folder copy never moves a
locked Design/Clone clip; `scripts/repo_invariants.sh` (run by `scripts/dev.sh contracts` and by CI)
holds the one-StoreKit-owner grep, the one-export-boundary grep over every source root the iOS app
compiles, the Files-visible-Documents rule and the fixture-ownership greps. The audited surface list
is the [outward export inventory](ios-app-guide.md#outward-export-inventory-audited-2026-09-14-source-side).
These **do not execute an Apple transaction**; generic iOS compilation checks the real adapter and
UI.

On the phone, `scripts/ui_test.sh ios purchase --retain-result` (and `--scenario exports`) drives the
local StoreKit lifecycle and every export surface through the real sheet against a UI-test-only
fixture; the [device-testing guide](ios-device-testing.md#local-storekit-purchase-lane) owns the
lane. RF-13 closed on the exports scenario's 26-phase pass
(`ios-xcui-purchase-20261016-175234-5cbdbead`). The other export routes have no paid device path to
drive: failed-storage recovery exports are always free, long-form segments have no export of their
own (a project leaves as its History row or through the automatic folder copy, whose purchase
gating `IOSSavedOutputsDestinationTests` cover), and saved-voice provenance is covered by
`IOSExportPurchaseTests`.

The local lane does not qualify the live App Store's offline cache, the App Store sandbox or the
processed TestFlight candidate. RF-12 checks owned exports in Airplane Mode on the processed
TestFlight build, and RF-15's with-purchase export, Restore and Cancel rows wait for RF-02; a
sandbox session needs a confirmed test account and an available configured product. The stateful
control audit reaches and dismisses the purchase options but never buys. Never fake entitlements
for the release acceptance (RF-15) or the 201-take campaign.

- [x] Approve product identifier/reference name, USD 19.99 and automatic regional pricing; create
      the non-consumable and price schedule under explicit authorization, leaving Family Sharing off.
- [x] Complete localized product details (en-US, fr-CA, fr-FR) and territory availability (free
      and iPhone only; 148 territories since the EU removal of 2026-10-27); Family Sharing confirmed
      off (2026-10-12, RF-02). No submission is authorized.
- [x] Verify purchase/cancellation/pending/failure, restore, relaunch/offline owned access and
      refund/revocation, including every output export surface and Built-in free-export controls,
      in the local StoreKit session (RF-13, `ios-xcui-purchase-20261016-175234-5cbdbead`; the
      lane has since added AUD-07's unverified purchase).
- [ ] Repeat the owned-export check on the processed TestFlight build in Airplane Mode (RF-12).
- [ ] Accept the updated Apple Developer Program License Agreement (the Account Holder, at
      developer.apple.com/account; it blocks new submissions), then the Paid Apps agreement, and
      complete tax and banking. The Paid Apps agreement stopped at Apple's two-factor prompt on
      2026-10-12; these steps are the maintainer's (RF-02).
- [ ] Capture the IAP review screenshot from the processed TestFlight build at the live USD 19.99
      (decision 2026-10-13), and attach the first IAP to the app version for review. Explain the
      free/paid boundary and the restore path in the reviewer notes.

Apple references: [purchase types](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-types),
[IAP configuration](https://developer.apple.com/help/app-store-connect/configure-in-app-purchase-settings/overview-for-configuring-in-app-purchases),
[review rules](https://developer.apple.com/app-store/review/guidelines/#in-app-purchase).

Current account state (2026-10-12, set in the web portal with the maintainer's approval; RF-02):
- version 3.0.0, which replaced the unreleased 1.0 draft;
- category Productivity, secondary Music;
- free and iPhone only (Apple-silicon Mac and Vision Pro availability off), in 148 territories
  since 2026-10-27, when the 27 EU territories were removed (maintainer decision; BKL-41);
- age rating 4+;
- App Privacy published as Data Not Collected, with the privacy policy URL;
- the export purchase entered as above;
- EU Digital Services Act: declared non-trader with no EU distribution intended (2026-10-27).

The `en-US` Support URL and the `USES_THIRD_PARTY_CONTENT` declaration remain configured. Still open:
- the updated Apple Developer Program License Agreement, the Paid Apps agreement, banking and tax;
- the accessibility declaration;
- the processed candidate's export-compliance check.

App Store Connect readiness is a manual, read-only pass: review the live app identity, platforms,
category, pricing/availability, metadata, localizations and URLs, screenshots, review contact,
content rights, age rating and version state in the App Store Connect web portal, or through the
maintainer's `asc` plugin skills (rorkai's app-store-connect-cli-skills, which drive the Homebrew `asc`
CLI from Rork; reads only, any write needs an explicit
request). The repository pins no App Store Connect CLI and keeps no automated inventory. App Privacy
publication, agreement/tax/banking readiness, DSA trader status and regional-compliance fields are
owner/web checks; record an unavailable answer as pending, never as PASS. Keep only redacted outcomes
(states and counts), never credentials or account identifiers. ASR-11 remains open until that pass
is complete.

- [x] **Privacy Policy URL** = `https://vocello.vercel.app/privacy` (hosted by this repo's website; the in-app
      Settings → Privacy & Permissions → Privacy Policy row links to the same URL).
- [x] **App Privacy "nutrition label"**: published as **Data Not Collected** on 2026-10-12 (the
      maintainer's ASR-02 decision of the same day). The rationale and the source facts it rests on are in the
      [content-rights review](content-rights-review.md#asr-02-app-privacy-label-is-data-not-collected).
      Mic audio, transcripts, prompts and generated audio stay local; Hugging Face's request logging
      during model downloads is its own processing as the host and is disclosed in the privacy
      policy. `PrivacyInfo.xcprivacy`, the policy and the review notes already agree; revisit the
      decision if the app adds network code, an SDK, an account, analytics or a non-Apple purchase path.
- [ ] **Encryption**: `ITSAppUsesNonExemptEncryption=false` is already in `Sources/iOS/Info.plist`,
      and the 2026-09-04 API read returned no separate encryption-declaration resource. Answer "No"
      to non-exempt encryption (only HTTPS + CryptoKit SHA-256 for download integrity), then verify
      that the processed 3.0.0 candidate does not request additional export-compliance information.
- [x] **Age rating**: 4+, set in App Store Connect on 2026-10-12 (RF-02). Revisit it if the
      product's content behavior changes.
- [ ] **Accessibility declaration**: the 2026-09-04 API read returned no declaration. Complete it only
      from the exact-candidate accessibility evidence; do not infer supported features from source or
      historical device runs.
- [x] **Pricing and availability**: free, iPhone only (2026-10-12, RF-02), in 148 territories: the
      27 EU territories were removed on 2026-10-27. Review the release behavior and new-territory
      policy at submission.
- [ ] **Account deletion / Sign in with Apple**: N/A — there is no account and no third-party login.
- [x] **EU DSA status**: declared non-trader with no EU distribution intended (2026-10-27), and the
      EU territories are unavailable. An EU release needs trader status first (BKL-41).
- [ ] **EU AI Act Article 50**: published audio must ship with the built-in AI marking enabled
      (AudioSeal watermark + WAV provenance chunk; the only off-switch is a registered debug knob).
      Review [`eu-ai-act-article50-assessment.md`](eu-ai-act-article50-assessment.md) for the
      posture and the paid-launch gates (C2PA, Code of Practice, legal review).

## 2. App Review demo notes (paste into "App Review Information → Notes")

The notes text to paste is in [`app-store-listing.md`](app-store-listing.md#app-review-notes-4000),
with the rest of the 3.0.0 listing draft. No demo account is needed (no login); the notes spell out
the model download requirement so the app is not judged non-functional under Guideline 2.1.

Storage guidance is grounded in `IOSModelDeliverySupport.ensureSufficientDiskSpace`:
`max(2 × catalog bytes, catalog bytes + 256 MiB)`. The coordinator supplies the full model
catalog total, even when components can be reused. Current admission needs are approximately
4.10–4.15 GB of available space; the 4.5 GB advice provides reviewer headroom, not a different
runtime policy or a guarantee against concurrent storage use. Recheck against the candidate
catalog before pasting these notes into App Store Connect.

Before using these notes, close ASR-09. By the maintainer's 2026-10-12 decision, North America,
where App Review runs, is the verified download region, and Europe and East Asia stay unverified as
a recorded residual risk. On 2026-09-01 the North America host passed range and full SHA-256
verification of the three exact iOS artifacts. A fresh full-artifact North America proof within 24
hours of submission remains (ASR-09).

## 3. Screenshots + metadata

- [ ] iPhone screenshots: Apple currently requires one highest-resolution iPhone set. Prefer an accepted
      6.9-inch portrait size (1260×2736, 1290×2796, or 1320×2868); an accepted 6.5-inch set
      (1284×2778 or 1242×2688) is the fallback when 6.9-inch screenshots are absent. Capture from the
      exact signed candidate on the supported **physical device** for Studio, model installation,
      Voice Design, Voice Cloning, Voices, History, and Settings. Reject clipping, stale UI, diagnostic
      state, personal data, and misleading claims. Do not submit the tracked 780×1696 historical image
      or the 1440×1224 Mac images as iPhone screenshots.
- [ ] App name, subtitle (≤30 chars each), description, keywords (≤100), marketing URL
      (`https://vocello.vercel.app`), and copyright. The en-US draft, awaiting the maintainer's
      review, is [`app-store-listing.md`](app-store-listing.md); copyright is not drafted yet.
- [x] Source support identity is single-sourced in `config/support-contact.json`: the unauthenticated
      support page exposes the monitored address and response owner, the website privacy/footer surfaces
      link it, and Settings opens the exact route. `scripts/support_contact_contract.py` rejects drift,
      placeholders, insecure URLs, and ungoverned response-time promises.
- [x] The production support route returned HTTPS 200 with the expected monitored contact, response owner,
      and privacy link. The `en-US` localization read back the exact governed Support URL in App Store
      Connect on 2026-08-27, on the 1.0 draft that version 3.0.0 replaced. Verify it again on 3.0.0,
      and add the same URL to any new localization.
- [x] The accessible in-app Open Source & Licenses browser reads the deterministic offline manifest generated
      from the exact SwiftPM graph, owned-runtime NOTICE/origins, and all six catalog-pinned model cards.
      Archive/IPA verification rejects a missing, malformed, duplicated, or byte-different manifest.
- [x] App Store Connect declares `USES_THIRD_PARTY_CONTENT` and read it back on 2026-08-27.
- [ ] Complete the remaining qualified ASR-04 rights decisions for model-license delivery/NOTICE/trademark
      obligations, Qwen outputs and built-in speaker presentation, the voice-clone marketing source,
      other marketing audio/scripts, and artwork. Use
      [`content-rights-review.md`](content-rights-review.md); the App Store checkbox is not legal clearance.

## 4. Build the signed IPA

Before producing a signed candidate, run a generic-device Release Analyze with the repository's
governed caches and validate its log with
`python3 scripts/ios_release_analyzer_warnings.py check --log <log>`. Application-source warnings
are not allowlisted. The reviewed residual MLX isolation, cross-platform shim, no-App-Intents,
mlx-swift Metal header (C++17 extensions) and shared-folder project group classes are count-bounded
by `config/ios-release-analyzer-warning-policy.json`; a warning from a resolved package checkout is
attributed to that dependency, never to repository source. A new warning or count increase blocks
the candidate. Run the analyze in the isolated `build/scratch/derived-data/release-ios` root and
remove it afterwards: an incremental cache skips package compilation, so its log omits the MLX
classes.

Two paths produce the same App-Store-uploadable IPA.

### A. CI (the candidate route)

Add these repo **Secrets** (Settings → Secrets and variables → Actions):

| Secret | What |
| --- | --- |
| `IOS_DIST_CERT_P12` | base64 of the iOS Distribution `.p12` (`base64 -i dist.p12 \| pbcopy`) |
| `IOS_DIST_CERT_PASSWORD` | the `.p12` export password |
| `IOS_PROVISION_PROFILE` | base64 of the App Store `.mobileprovision` (must carry increased-memory-limit) |
| `QWENVOICE_DEVELOPMENT_TEAM` | the 10-char Apple team id |
| `ASC_API_KEY_ID` / `ASC_API_ISSUER_ID` / `ASC_API_KEY_P8` | App Store Connect API key (id, issuer, base64 of `.p8`) |

For a TestFlight candidate, push `main`, wait for its `CI required` check, then run
`python3 scripts/ios_candidate_tag.py` (`--dry-run` first if you like). It refuses a dirty tree, a
`HEAD` other than `origin/main`, a commit whose CI has not passed and a build number App Store Connect
already has, then signs the next `v<version>-ios.N` tag with the configured SSH key, verifies it and
pushes only that tag. That push runs the iPhone path of `release.yml` alone (source authority, the
signed archive, IPA verification and evidence, and the TestFlight upload; no Mac packages) once the
`release` environment is approved. Claude Code may run the script on the maintainer's request
(CLAUDE.md: Main is the only published branch); any other release tag stays maintainer-run.

To rebuild an existing tag instead, run the **Release** workflow from the Actions tab, choosing the version tag itself under
"Use workflow from" and entering the same `tag`, with `archive_ios = true`, `package_macos = false`
and optionally `upload_to_testflight = true` to push straight to TestFlight (from the CLI:
`gh workflow run release.yml --ref <tag> -f tag=<tag> -f archive_ios=true -f package_macos=false`).
A dispatch from any other ref is refused by the `release-trigger` job. With `package_macos = false`
the dispatch leaves the macOS draft and its DMGs untouched; left at its default (true) it rebuilds,
re-notarizes and re-uploads the macOS candidate, replacing every asset on the draft. Runs for one
tag, including promotion, never overlap (`concurrency` group `release-<tag>`). The workflow
first executes `scripts/macos_test.sh gate` plus the generic iOS device-SDK compile as one
contract-bound `platform-readiness` subprocess. Only then does it archive `VocelloiOS`, assert the
bundled catalog, export via `ExportOptions-appstore.plist`, and run the release-blocking
`verify_ios_release_artifacts.py` contract. That verifier checks the
archive and IPA bundle/version/build identities, arm64 Mach-O UUID plus signature-normalized code
continuity, the root privacy manifest, App Group and memory entitlements, configured-team and App ID
prefix consistency, and signing-certificate membership in each provisioning profile. The archive
may be validly development- or distribution-signed; only the exported IPA must use App Store
provisioning, Apple Distribution signing, and no `get-task-allow`. CI deliberately signs the archive
with the imported Distribution certificate/profile UUID. Both signing chains must also pass a local
Apple code-signing trust and validity evaluation. The standalone verifier still accepts Xcode's
normal two-phase local archive/export route. The schema-v2 compact summary omits the team and App ID
prefix. It and the IPA are both hashed into the release evidence before SPDX/CycloneDX
inventories, checksums, provenance attestation, candidate upload, or the optional TestFlight upload
can proceed.

The optional upload is an internal candidate step. Before assigning that build to external testers,
submitting it for App Review, or releasing it publicly, produce and validate the iOS
`quality-promotion.json` against this exact release evidence. This preserves TestFlight as a useful
validation environment without allowing a source-stale phone verdict to authorize public promotion.
Build 26 joined the Public Beta under the maintainer's one-time RF-17 waiver of 2026-10-26; App
Review still requires the manifest.

`release.yml` does not query App Store Connect for an existing build, and it never invents or
increments a build number. The candidate-tag script checks it before tagging; for a dispatch rebuild
or the local route, confirm read-only in App Store Connect (the web portal or the asc-* skills) that
the exact bundle/version/build identity (`com.patricedery.vocello` with `MARKETING_VERSION` and
`CURRENT_PROJECT_VERSION` from `project.yml`) is unused. When it is not, bump
`CURRENT_PROJECT_VERSION` in `project.yml`, run `./scripts/regenerate_project.sh --fast`, review the
diff and rerun deterministic validation. Apple
rejects a reused build number at the altool upload, so a missed check fails the upload; it cannot
replace an existing build.

**Distributing a processed candidate.** Each step is an App Store Connect or GitHub write, done by
the maintainer or by Claude Code on the maintainer's request for that candidate.

1. The run pauses for the `release` environment. Approve it in the Actions tab or with
   `gh api -X POST repos/PowerBeef/Vocello/actions/runs/<run>/pending_deployments
   -F 'environment_ids[]=22764362076' -f state=approved -f comment="<reason>"`.
2. Wait until `asc builds list --app 6794692745 --platform IOS --build-number <N>
   --processing-state all` shows the build VALID, and take its build id.
3. `asc builds test-notes create --build-id <ID> --locale en-US --whats-new <TEXT>`, where TEXT is the
   "TestFlight: what to test" section of `docs/releases/v<version>.md`
   ([`macos-release-qa.md`](macos-release-qa.md) owns that section's rules).
4. `asc testflight review submit --build-id <ID> --confirm` submits the build for beta review.
   Internal testers get every build already: the Internal group has access to all builds, so adding
   it by hand is refused.
5. Add the Public Beta group (`asc builds add-groups --build-id <ID> --group
   2375b641-4224-486c-8c0a-0fa326d7b641`) only with the exact-tag promotion or the maintainer's
   explicit waiver for that build.

A new TestFlight build's first launch shows TestFlight's What to Test sheet; tap Continue before a
candidate row ([`ios-device-testing.md`](ios-device-testing.md)).

### B. Local (Xcode-logged-in maintainer)

Do the same manual build-identity check in App Store Connect before resolving or archiving.

```sh
export QWENVOICE_DEVELOPMENT_TEAM=<your-team-id>
./scripts/regenerate_project.sh
scripts/ios_device.sh preflight
mkdir -p build/cache/xcode/source-packages build/scratch/derived-data/release-ios \
  build/scratch/transient/ios-release build/dist/ios
xcodebuild -resolvePackageDependencies -project QwenVoice.xcodeproj -scheme VocelloiOS \
  -clonedSourcePackagesDirPath build/cache/xcode/source-packages \
  -derivedDataPath build/scratch/derived-data/release-ios
xcodebuild archive -project QwenVoice.xcodeproj -scheme VocelloiOS -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath build/scratch/derived-data/release-ios \
  -clonedSourcePackagesDirPath build/cache/xcode/source-packages \
  -disableAutomaticPackageResolution \
  -archivePath build/dist/ios/Vocello.xcarchive -allowProvisioningUpdates \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=YES
export_options=build/scratch/transient/ios-release/ExportOptions-appstore.plist
cp ExportOptions-appstore.plist "$export_options"
/usr/libexec/PlistBuddy -c "Add :teamID string $QWENVOICE_DEVELOPMENT_TEAM" "$export_options"
xcodebuild -exportArchive -archivePath build/dist/ios/Vocello.xcarchive \
  -exportOptionsPlist "$export_options" -exportPath build/dist/ios/export \
  -allowProvisioningUpdates
```

Then run the mandatory non-device artifact check:

```sh
./scripts/check_ios_catalog.sh
python3 scripts/verify_ios_release_artifacts.py \
  --archive build/dist/ios/Vocello.xcarchive \
  --export-dir build/dist/ios/export \
  --expected-team-id-env QWENVOICE_DEVELOPMENT_TEAM \
  --output build/dist/ios/ios-release-artifact-verification.json
```

This local route may produce a development-signed archive that Xcode re-signs during export. That is
valid: the verifier requires a trusted Apple signing/profile relationship on the archive, then applies
the final App Store distribution rules to the exported IPA and compares signature-normalized code.
The tracked export-options template is read-only input; inject maintainer identity only into the
governed scratch copy shown above.

When a separate physical-device release-validation session was explicitly performed, its local
metadata can additionally be checked with the older device-context verifier. That optional evidence
does not replace the mandatory archive/IPA contract above and does not gate packaging:

```sh
./scripts/verify_ios_release_archive.sh build/dist/ios/Vocello.xcarchive build/dist/ios/export release_metadata.txt
```

For frontend acceptance, run `scripts/ui_test.sh ios smoke` and `scripts/ui_test.sh ios benchmark`
separately at a coherent checkpoint; their result bundles do not gate the archive.

Upload the IPA via Transporter or `xcrun altool --upload-app -f build/dist/ios/export/Vocello.ipa -t ios \
  --apiKey <KEY_ID> --apiIssuer <ISSUER_ID>` (with `AuthKey_<KEY_ID>.p8` in `~/.appstoreconnect/private_keys/`).

## 5. Pre-flight (run before every submission)

The repo's standing iOS quality work covers the code side (audio-session lifecycle, accessibility, dismissible
onboarding, error/empty states, portrait lock, privacy link). Before submitting, additionally confirm on a real
device: launch + all 4 tabs; install a model; generate in each mode; record→enroll→clone with mic/speech permission
**denial + recovery** via Settings → Privacy & Permissions → Permissions (iOS Settings); cancel mid-generation; an incoming call mid-record
keeps the take; VoiceOver reads the primary controls; the largest Dynamic Type doesn't clip the composer.
Most of these are rows of the candidate acceptance (RF-15): run them on the processed build with
`scripts/ui_test.sh ios smoke --preinstalled-candidate` ([Already installed distribution
candidate](ios-device-testing.md#already-installed-distribution-candidate)). What XCUITest cannot drive
goes to computer use or the maintainer ([Checks XCUITest does not cover](ios-device-testing.md#checks-xcuitest-does-not-cover));
permission prompts, calls and VoiceOver stay the maintainer's.

## 6. Submit

App Store Connect → the version → attach the build → Submit for Review. For the first submission, the privacy
URL, age rating, and screenshots must all be set or submission is blocked.
