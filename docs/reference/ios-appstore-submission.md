---
status: active
owner: release-qa
reviewed: 2026-09-04
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

The end-to-end steps to ship **Vocello for iPhone** (`com.patricedery.vocello`) to TestFlight / the App Store. The generic Release target, assets, privacy manifest, entitlement sources, in-app privacy link, and signed-archive CI lane are in place. That is not yet submission readiness: the pinned
[`2026-08-26 readiness audit`](ios-app-store-readiness-audit-2026-08-26.md) records source,
privacy/legal, support, licensing, metadata, signing/account, hosting, and physical-device gaps.
`config/roadmap.json` owns their live `ASR-*` status. This document is the operator checklist after
those gates are closed.

Source-of-truth rule: if this disagrees with the code, the code wins.

This runbook is release-only. Commits, pushes, pull requests, merges, CI, archive, and internal
TestFlight packaging/upload use deterministic verification and do not require a phone, models, or
XCUITest evidence. External TestFlight distribution, App Review submission, and public App Store
release require the exact-tag iOS manifest in
[`quality-promotion.md`](quality-promotion.md).

**Historical device checkpoint (2026-06-13, iPhone 17 Pro):** the development build signed, installed, and ran
end-to-end. `scripts/ios_device.sh` now **auto-derives the signing team** from the keychain's Apple
Development certificate (no `QWENVOICE_DEVELOPMENT_TEAM` needed for local dev builds; it also falls back to
offline manual signing if no Apple ID is in Xcode). The development provisioning profile already carries
`increased-memory-limit`, and that dated run passed its generation and audio-QC checks. Current performance
and memory truth comes from the schema-v2 records in `benchmarks/HISTORY.md`, not these historical figures.
Physical-device XCUITest can be run independently when explicit frontend acceptance is requested;
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
      2026-09-04 found configured 2.4.0/build 23 state and one `en-US` localization. The next candidate
      is 3.0.0, but its unused build number and account version are not selected until RF-09.
      Category and the rest of the live account remain part of ASR-11.
- [x] App Store installation eligibility matches the app's runtime hardware floor before the first
      public version. The built bundle requires exactly `arm64` and Apple's
      `iphone-performance-gaming-tier`; the runtime guard independently enforces iPhone 15 Pro or
      newer. Deterministic source and archive/IPA verification reject future drift (ASR-01).

## 1. Privacy + compliance (App Store Connect)

Current account checkpoint (2026-09-04): authentication and exact app resolution succeeded in a
bounded read-only inventory. The exact `en-US` Support URL and `USES_THIRD_PARTY_CONTENT`
declaration remain configured. App/version, release, localization, app-info, content-rights,
age-rating, and review-state reads succeeded; no metadata, build, TestFlight, or submission state
changed. Pricing/availability has no readable initialized record, strict readiness for the currently
configured 2.4.0 version is unavailable, and App Privacy publication, agreements/tax/banking, DSA,
and regional fields still require owner/web or qualified review. Empty accessibility and encryption
declaration lists are observations, not completed questionnaires.

The guarded inventory command is read-only, paginated where applicable, and retains only response
digests, resource counts, and safe state tokens:

```sh
python3 scripts/app_store_connect_readiness.py validate
python3 scripts/app_store_connect_readiness.py inventory \
  --profile primary \
  --output build/artifacts/app-store/app-store-connect-readiness.json
```

The public API cannot establish App Privacy publication, agreement/tax/banking readiness, DSA
trader status, or every regional-compliance field. The inventory marks those checks pending owner
or web review rather than converting absence into PASS. On 2026-09-01 the unattended `primary`
profile read timed out at its first authenticated request; the shared runner killed the complete
CLI process group, no account data was retained, and ASR-11 remains open.

- [ ] **Privacy Policy URL** = `https://vocello.vercel.app/privacy` (hosted by this repo's website; the in-app
      Settings → About → Privacy Policy row links to the same URL).
- [ ] **App Privacy "nutrition label"**: do not select **Data Not Collected** until ASR-02 closes.
      Mic audio, transcripts, prompts, and generated audio remain local, but Hugging Face receives
      network request metadata during model downloads. Record the vendor retention and qualified
      privacy/legal determination, then make the App Store answers, `PrivacyInfo.xcprivacy`, policy,
      and review notes agree. Apple requires third-party partner processing in the answers.
- [ ] **Encryption**: `ITSAppUsesNonExemptEncryption=false` is already in `Sources/iOS/Info.plist`,
      and the 2026-09-04 API read returned no separate encryption-declaration resource. Answer "No"
      to non-exempt encryption (only HTTPS + CryptoKit SHA-256 for download integrity), then verify
      that the processed 3.0.0 candidate does not request additional export-compliance information.
- [ ] **Age rating**: complete the current App Store Connect questionnaire from actual product and
      content-rights behavior. A declaration is readable and contains three answered fields, but that
      does not establish a complete/current rating. Do not predeclare a rating from this runbook;
      preserve the account result as read-only evidence under ASR-11.
- [ ] **Accessibility declaration**: the 2026-09-04 API read returned no declaration. Complete it only
      from the exact-candidate accessibility evidence; do not infer supported features from source or
      historical device runs.
- [ ] **Pricing and availability**: initialize and review the intended territories, price/free status,
      preorder/release behavior, and new-territory policy. The read-only API currently returns no
      availability record, so absence is a submission dependency rather than a passing default.
- [ ] **Account deletion / Sign in with Apple**: N/A — there is no account and no third-party login.
- [ ] EU DSA trader status: complete if distributing in the EU.
- [ ] **EU AI Act Article 50**: published audio must ship with the built-in AI marking enabled
      (AudioSeal watermark + WAV provenance chunk; the only off-switch is a registered debug knob).
      Review [`eu-ai-act-article50-assessment.md`](eu-ai-act-article50-assessment.md) for the
      posture and the paid-launch gates (C2PA, Code of Practice, legal review).

## 2. App Review demo notes (paste into "App Review Information → Notes")

> Vocello generates speech entirely on-device. It ships with **no bundled model weights** to keep the app
> small. On first launch, open Settings → Voice Models and tap **Install** for the Studio mode you want:
> Built-in Voice is 1,708,583,689 bytes, Voice Design is 1,708,583,196 bytes, and Voice Cloning is
> 1,732,600,769 bytes. One model is sufficient to review its matching mode. Downloads require Wi-Fi and
> roughly 2 GB of free space per model; completion time depends on the review network and may take several
> minutes. Progress reports exact downloaded catalog bytes. A download can be cancelled and restarted, and
> an interrupted background download is adopted after relaunch. Final verification/installation is shown as
> an indeterminate finishing step. Once the model shows **Ready**, that mode works offline. Open Studio,
> type a short line, choose a speaker where applicable, and tap Generate. No account or login is required.
> Voice Cloning records its reference with the microphone or imports an audio file the user has rights to;
> Microphone and Speech Recognition permissions are requested only for recording and local transcription.
> If a pinned model host is temporarily unavailable, retry later on stable Wi-Fi or use the Support link in
> Settings. Vocello never substitutes a different model artifact.

No demo account is needed (no login). Note the model download requirement so the app is not judged
non-functional under Guideline 2.1.

Before using these notes, close ASR-09 with anonymous availability evidence from all representative
regions. On 2026-09-01 the North America host passed range and full SHA-256 verification of the
three exact iOS artifacts. Regional closure still requires qualified, fresh Europe and East Asia
execution evidence; a locally relabeled probe is rejected by the closure composer.

## 3. Screenshots + metadata

- [ ] iPhone screenshots: Apple currently requires one highest-resolution iPhone set. Prefer an accepted
      6.9-inch portrait size (1260×2736, 1290×2796, or 1320×2868); an accepted 6.5-inch set
      (1284×2778 or 1242×2688) is the fallback when 6.9-inch screenshots are absent. Capture from the
      exact signed candidate on the supported **physical device** for Studio, model installation,
      Voice Design, Voice Cloning, Voices, History, and Settings. Reject clipping, stale UI, diagnostic
      state, personal data, and misleading claims. Do not submit the tracked 780×1696 historical image
      or the 1440×1224 Mac images as iPhone screenshots.
- [ ] App name, subtitle (≤30 chars each), description, keywords (≤100), marketing URL
      (`https://vocello.vercel.app`), and copyright.
- [x] Source support identity is single-sourced in `config/support-contact.json`: the unauthenticated
      support page exposes the monitored address and response owner, the website privacy/footer surfaces
      link it, and Settings opens the exact route. `scripts/support_contact_contract.py` rejects drift,
      placeholders, insecure URLs, and ungoverned response-time promises.
- [x] The production support route returned HTTPS 200 with the expected monitored contact, response owner,
      and privacy link. The sole iOS 1.0 localization (`en-US`) read back the exact governed Support URL in
      App Store Connect on 2026-08-27. Add and verify the same URL when another localization is introduced.
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
are not allowlisted. The reviewed residual MLX isolation, cross-platform shim, and no-App-Intents
classes are count-bounded by `config/ios-release-analyzer-warning-policy.json`; a new warning or
count increase blocks the candidate.

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

Then run the **Release** workflow from the Actions tab with the exact existing version `tag`,
`archive_ios = true`, and optionally `upload_to_testflight = true` to push straight to TestFlight.
This job is gated to manual dispatch only, so it never affects the macOS DMG release. The workflow
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

Before archiving, the workflow installs the digest-pinned `asc` binary and performs a
least-privilege read-only collision check for the exact bundle/version/build identity. Any existing
App Store Connect build with that identity blocks the archive. The workflow never invents or
increments a build number. To advance it, edit `CURRENT_PROJECT_VERSION` in `project.yml`,
regenerate the project, review the diff, and rerun deterministic validation.

### B. Local (Xcode-logged-in maintainer)

Run the same collision check before resolving or archiving:

```sh
python3 scripts/app_store_build_preflight.py identity
python3 scripts/app_store_build_preflight.py check \
  --profile primary \
  --output build/artifacts/app-store/build-collision-preflight.json
```

The second command performs no mutation and must PASS. A Keychain/authentication timeout is not
permission to archive; restore the least-privilege profile and rerun it.

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

When frontend acceptance is explicitly requested, run `scripts/ui_test.sh ios smoke` and
`scripts/ui_test.sh ios benchmark` separately; their result bundles do not gate the archive.

Upload the IPA via Transporter or `xcrun altool --upload-app -f build/dist/ios/export/Vocello.ipa -t ios \
  --apiKey <KEY_ID> --apiIssuer <ISSUER_ID>` (with `AuthKey_<KEY_ID>.p8` in `~/.appstoreconnect/private_keys/`).

## 5. Pre-flight (run before every submission)

The repo's standing iOS quality work covers the code side (audio-session lifecycle, accessibility, dismissible
onboarding, error/empty states, portrait lock, privacy link). Before submitting, additionally confirm on a real
device: launch + all 4 tabs; install a model; generate in each mode; record→enroll→clone with mic/speech permission
**denial + recovery** via Settings → About → Open iOS Settings; cancel mid-generation; an incoming call mid-record
keeps the take; VoiceOver reads the primary controls; the largest Dynamic Type doesn't clip the composer.

## 6. Submit

App Store Connect → the version → attach the build → Submit for Review. For the first submission, the privacy
URL, age rating, and screenshots must all be set or submission is blocked.
