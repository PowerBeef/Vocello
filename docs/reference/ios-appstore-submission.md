---
status: active
owner: release-qa
reviewed: 2026-10-25
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

The end-to-end steps to ship **Vocello for iPhone** (`com.patricedery.vocello`) to TestFlight / the App Store. The generic Release target, assets, privacy manifest, entitlement sources, in-app privacy link, and signed-archive CI lane are in place. That is not yet submission readiness: the August 2026 readiness audit found source,
privacy/legal, support, licensing, metadata, signing/account, hosting, and physical-device gaps, and
`config/roadmap.json` owns their live `ASR-*` status. This document is the operator checklist after
those gates are closed.

Source-of-truth rule: if this disagrees with the code, the code wins.

This runbook is release-only. Commits, pushes, CI, archive, and internal TestFlight
packaging/upload use deterministic verification and do not require a phone, models, or
XCUITest evidence. External TestFlight distribution, App Review submission, and public App Store
release require the exact-tag iOS manifest in
[`quality-promotion.md`](quality-promotion.md).

**Historical device checkpoint (2026-06-13, iPhone 17 Pro):** the development build signed, installed, and ran
end-to-end. `scripts/ios_device.sh` now **auto-derives the signing team** from the keychain's Apple
Development certificate (no `QWENVOICE_DEVELOPMENT_TEAM` needed for local dev builds; it also falls back to
offline manual signing if no Apple ID is in Xcode). The development provisioning profile already carries
`increased-memory-limit`, and that dated run passed its generation and audio-QC checks. Current performance
and memory truth comes from the tracked records in `benchmarks/HISTORY.md` (`rtf` = synthesis wall ÷ audio,
lower is faster), not these historical figures.
Physical-device XCUITest runs separately, at coherent checkpoints;
ordinary GitHub CI and archive packaging are deterministic-only — see
[`testing-runbook.md`](testing-runbook.md); and the UI holds with no clipping at the largest
accessibility Dynamic Type size. A read-only 2026-09-04 inspection found usable local Development,
Distribution, and Developer ID identities, one active matching App Store profile, and the exact App
ID's registered App Group and Increased Memory Limit capabilities. The profile payload has not yet
been downloaded and decoded, and no signed archive/IPA exists. **Still maintainer-authorized below:**
select the unused 3.0.0 build identity at freeze, verify the profile's emitted entitlements through
the exact archive/export, and authorize any ASC metadata change, upload, or submission separately.

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
- [x] **iOS Distribution certificate** installed with its private key. Read-only Keychain inspection
      found one usable Apple Distribution identity on 2026-09-01; exact archive verification remains
      required and this checkbox does not authorize signing or upload.
- [x] App ID `com.patricedery.vocello` has **App Groups** + **Increased Memory Limit** capabilities enabled.
      The `increased-memory-limit` capability is self-serve (no Apple review). It MUST be on the App Store
      provisioning profile or the multi-gigabyte model load is Jetsam-killed on a signed build. The
      exact remote App ID reported both capabilities on 2026-09-04; archive verification remains the
      authority for what the signed candidate actually receives.
- [ ] **App Store provisioning profile** for `com.patricedery.vocello` (Distribution → App Store), regenerated
      after enabling the capabilities so it carries `increased-memory-limit` + the App Group. The
      2026-09-04 read-only account inventory found one active matching `IOS_APP_STORE` profile with a
      2027-07-25 expiry. Keep this row open until its payload or the exported IPA proves both required
      entitlements and the exact signing identity; an active account record alone is insufficient.
- [x] App record exists in App Store Connect for `com.patricedery.vocello`; exact CLI resolution on
      2026-09-04 found configured 2.4.0/build 23 state and one `en-US` localization. The 3.0.0 account
      version exists (Prepare for Submission), and a read-only check on 2026-10-14 found build 24
      unused, with no build in the 3.0.0 train (ASR-08); the check repeats right before archiving.
      On 2026-10-12 version 3.0.0 replaced the unreleased 1.0 draft, and the category became
      Productivity (secondary Music) (RF-02).
- [x] App Store installation eligibility matches the app's runtime hardware floor before the first
      public version. The built bundle requires exactly `arm64` and Apple's
      `iphone-performance-gaming-tier`; the runtime guard independently enforces iPhone 15 Pro or
      newer. Deterministic source and archive/IPA verification reject future drift (ASR-01).

## 1. Privacy + compliance (App Store Connect)

**Implemented and locally accepted (RF-13, closed 2026-10-16); live product entered (RF-02,
2026-10-12):** the iOS app remains free to generate and listen in all three modes, with free
Built-in output export. The StoreKit entitlement owner and output-provenance export boundary are
implemented, and the local StoreKit exports scenario passed all 26 phases. The product has en-US,
fr-CA and fr-FR names and descriptions. Still open:
- the Paid Apps agreement and its banking, tax and EU trader (DSA) steps, which are the maintainer's
  (RF-02);
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
The rejected earlier hyphenated identifier created no product. The local-only
`Tests/Fixtures/VocelloExports.storekit` uses a TEST product and arbitrary fixture price, not an
approved live offer. It is not bundled in the app or activated in shipping schemes. RF-02 owns the
remaining account and product metadata work. Settings → Design & Clone Export
provides the StoreKit-localized price, Restore, status, privacy/support links and dismissal.
See the [app guide](ios-app-guide.md#ios-export-purchase) for routes and compatibility.

Phone-independent checks: `scripts/macos_test.sh core-test --only IOSExportPurchaseTests` executes
production state/policy with deterministic StoreKit-boundary fixtures, including StoreKit-fixture
parity, and `--only IOSSavedOutputsDestinationTests` proves the automatic folder copy never moves a
locked Design/Clone clip; `scripts/repo_invariants.sh` (run by `scripts/dev.sh contracts` and by CI)
holds the one-StoreKit-owner grep, the one-export-boundary grep over every source root the iOS app
compiles, the Files-visible-Documents rule and the fixture-ownership greps. The audited surface list
is the [outward export inventory](ios-app-guide.md#outward-export-inventory-audited-2026-09-14-source-side).
These **do not execute an Apple transaction**. Generic iOS compilation checks the real adapter/UI.
For explicitly authorized **local** physical-device transaction testing, run:

```sh
scripts/ios_device.sh preflight
scripts/ui_test.sh ios purchase --retain-result
# Extend the same local session with offline owned access and every export surface:
scripts/ui_test.sh ios purchase --scenario exports --retain-result
```

The existing runner builds the UI-test target with `VocelloExports.storekit`; shipping targets and
schemes never activate or bundle it. `SKTestSession` owns a serial local session: native Xcode
transaction environment and the fixture's $0.99 price must be proven before visible Buy/Restore.
The lane covers initial lock, restore without ownership, simulated cancellation, purchase, relaunch,
restore, revocation, pending approval and approval delivery.
The cancellation arm reads back cleared error injection and resets session options before the
positive purchase: on the canonical phone, clearing the error alone left the next transaction failing.
Keep the original failed evidence; do not replace this isolation with retries or a production bypass.
Standard process-local Apple language
arguments make assertions English without changing the phone's French settings. No live Apple
Account, charge, account edits, app-data deletion or production entitlement override is authorized.
Preexisting local test transactions block execution; test-owned transactions are deleted on normal
failure/success and the app is terminated. Cleanup failure blocks acceptance. A runner crash can
prevent teardown; retain evidence and resolve the local session before another attempt.
`local-purchase-summary.json` requires every ordered phase, exact run/fixture identity and cleanup;
the `.xcresult`, screenshots, source receipt and crash delta remain untracked. Zero-test bootstrap
failures remain failed infrastructure runs, never retries or purchase passes.
The optional `exports` scenario requires an existing accessible History clip in each mode and the
installed Design model. It selects one visible-provenance row per mode and reuses its exact identity
for the revoked comparison; no existing row is edited, pinned or deleted. It generates one short
Design take, which stays in History, so the Studio inline card's export is tested too. History-menu,
full-player and Studio inline sharing are tested while owned and revoked, with free Built-in controls
and internal playback/pause. System sharing is cancelled, never sent or saved. The owned half runs
with StoreKit offline as the app sees it: Apple's fault injection fails product loading, purchase
and App Store sync (the device stays connected), and the unlock must survive a relaunch and a failed
Restore. The test restores the History filter, the Studio mode, Design brief and Design script, and
verifies the original tab after dismissing any modal, then stops the app. Current schema 4 records
the scenario and separate transaction, tab, History-filter, Studio and app-stop restoration
observations. The exports scenario requires all 26 phases; lifecycle requires ten.
The test snapshots the selected History filter before changing it and restores that filter, not an
assumed All selection. Background interruption never triggers foreground takeover during cleanup:
skipped or unobserved restoration fails qualification even if transactions were cleared and the app
stopped. `--require-restoration` is mandatory in the current runner. Historical schemas 1/2 remain
readable without that option but cannot establish current restoration proof (schema 3 is readable
with its own restoration fields, but cannot qualify the current runner either). Cross-scenario
qualification is rejected. The French system share sheet is queried by its stable
`header.closeButton`, not the English app locale's Close label.

RF-13 closed on the exports scenario's 26-phase pass (`ios-xcui-purchase-20261016-175234-5cbdbead`).
The other export routes have no paid device path to drive: failed-storage recovery exports are
always free, long-form segments have no export of their own (a project leaves as its History row or
through the automatic folder copy, whose purchase gating `IOSSavedOutputsDestinationTests` cover),
and saved-voice provenance is covered by `IOSExportPurchaseTests`. Neither scenario qualifies the
live App Store's own offline cache, App Store sandbox, or the processed TestFlight candidate: RF-12
checks owned exports in Airplane Mode on the processed TestFlight build. Sandbox needs a confirmed
test account and available configured product; processed proof additionally needs the separately
authorized command-bound archive/IPA and TestFlight upload, not a development build substituted in
place.

The existing stateful control audit inspects/dismisses purchase options but blocks transaction actions.
A separately authorized physical StoreKit/sandbox session must qualify purchase/restore/pending/
cancel/refund and all paid/free export paths, followed by processed-candidate checks. Do not fake
entitlements for the release acceptance (RF-15, risk-based since 2026-10-12) or the later 201-take
campaign; prepare the approved test purchase before freezing it.

- [x] Approve product identifier/reference name, USD 19.99 and automatic regional pricing; create
      the non-consumable and price schedule under explicit authorization, leaving Family Sharing off.
- [x] Complete localized product details (en-US, fr-CA, fr-FR) and territory availability (free in
      175 territories, iPhone only); Family Sharing confirmed off (2026-10-12, RF-02). No submission
      is authorized.
- [x] Verify purchase/cancellation/pending/failure, restore, relaunch/offline owned access and
      refund/revocation, including every output export surface and Built-in free-export controls,
      in the local StoreKit session (RF-13, `ios-xcui-purchase-20261016-175234-5cbdbead`).
- [ ] Repeat the owned-export check on the processed TestFlight build in Airplane Mode (RF-12).
- [ ] Accept the Paid Apps agreement and complete tax, banking and EU trader (DSA) status. The
      agreement stopped at Apple's two-factor prompt on 2026-10-12; these steps are the maintainer's
      (RF-02).
- [ ] Capture the IAP review screenshot from the processed TestFlight build at the live USD 19.99
      (decision 2026-10-13), and attach the first IAP to the app version for review. Explain the
      free/paid boundary and the restore path in the reviewer notes.

Apple references: [purchase types](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-types),
[IAP configuration](https://developer.apple.com/help/app-store-connect/configure-in-app-purchase-settings/overview-for-configuring-in-app-purchases),
[review rules](https://developer.apple.com/app-store/review/guidelines/#in-app-purchase).

Current account state (2026-10-12, set in the web portal with the maintainer's approval; RF-02):
- version 3.0.0, which replaced the unreleased 1.0 draft;
- category Productivity, secondary Music;
- free in all 175 territories, iPhone only (Apple-silicon Mac and Vision Pro availability off);
- age rating 4+;
- App Privacy published as Data Not Collected, with the privacy policy URL;
- the export purchase entered as above.

The `en-US` Support URL and the `USES_THIRD_PARTY_CONTENT` declaration remain configured. Still open:
- the Paid Apps agreement, banking, tax and EU trader status;
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
- [x] **Pricing and availability**: free in all 175 territories, iPhone only (2026-10-12, RF-02).
      Review the release behavior and new-territory policy at submission.
- [ ] **Account deletion / Sign in with Apple**: N/A — there is no account and no third-party login.
- [ ] EU DSA trader status: complete if distributing in the EU.
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

### A. CI (recommended once secrets are set)

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

The workflow does not query App Store Connect for an existing build, and it never invents or
increments a build number. Before archiving, on CI or locally, confirm read-only in App Store Connect
(the web portal or the asc-* skills) that the exact bundle/version/build identity
(`com.patricedery.vocello` with `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` from `project.yml`)
is unused. When it is not, bump `CURRENT_PROJECT_VERSION` in `project.yml`, run
`./scripts/regenerate_project.sh --fast`, review the diff and rerun deterministic validation. Apple
rejects a reused build number at the altool upload, so a missed check fails the upload; it cannot
replace an existing build.

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
