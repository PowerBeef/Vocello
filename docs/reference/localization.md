---
status: active
owner: ios
reviewed: 2026-09-10
summary: Vocello localization architecture, String Catalog ownership, typed presentation vocabulary, literal-growth guard, and pseudo-localization acceptance.
sourceOfTruth:
  - project.yml
  - Sources/Resources/Localizable.xcstrings
  - Sources/iOS/InfoPlist.xcstrings
  - Sources/iOS/IOSRootNavigationModels.swift
  - Sources/SharedSupport/Services/VocelloPresentationText.swift
  - Sources/SharedSupport/Services/VocelloLocalization.swift
  - Sources/iOSSupport/Services/IOSAppLanguage.swift
  - scripts/localization_contract.py
  - config/localization-unlocalized-baseline.json
  - Tests/VocelloMacUITests/VocelloMacSmokeUITests.swift
  - Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift
---
# Localization architecture

English is the source language. The current checkout maintains English/French coverage for every
manually owned entry in the main catalog, including Settings/purchase copy, enrollment transcription
states, storage recovery, model terminal states, onboarding, tab labels and primary Studio actions.
The iOS permission catalog supplies microphone and Speech purpose strings separately, as required
by the system. The expanded migration covers secondary sheets, recording and enrollment warnings,
History filters/actions/recovery, player controls, download transfer details, long-form progress,
displayed language/preset names and additional accessibility descriptions. Catalog completeness is
**not whole-app acceptance**: rendered layouts and indirect errors from shared/system services
still require review. Canonical starter briefs shown as editable model content, stored names,
technical diagnostics, raw system error details and original license bodies are not translated by
string substitution.

The generated-audio language and app UI language are independent. Never translate user scripts,
reference transcripts, saved voice names, model IDs, enum raw values, seeds, or model-facing delivery
instructions as part of UI localization. Delivery instruction variants retain their own routing
contract. StoreKit remains the authority for the localized price; never format a fixed US price.
Original license/NOTICE bodies remain unchanged; translate their surrounding browser controls only.

## Authorities

- `IOSAppLanguage.shared` is the observable, app-lifetime iOS interface-language owner.
  Settings → App Language stores `vocello.ios.interfaceLanguage`; absence or an unsupported value
  means System Default. Choices are filtered against compiled bundle localizations: currently
  English/French only. The ten-language identifier list is preparation, not shipped translations.
  System Default uses OS language preferences and bundle matching, with English fallback.
  No `AppleLanguages` preference mutation, bundle swizzling, or root identity reset is used.
  The SwiftUI locale retains the current region; StoreKit prices remain opaque supplied strings.
- `VocelloLocalization` resolves the selected compiled catalog bundle. `IOSInterfaceText` and
  `IOSSettingsText` read the observable owner; iOS dynamic copy uses its `presentation` context.
  Shared/macOS callers retain default-bundle text through the existing static interfaces.
  Startup and unsupported-device presentation receive the same app-boundary locale.
  Already stored error strings are not reverse-translated; completing indirect error/status
  ownership remains part of the EN/FR review. Do not claim whole-app live switching from catalog tests.

- `Sources/Resources/Localizable.xcstrings` owns interface translations. Manual entries require
  English and French content and non-empty translator context. Both languages retain complete
  plural forms and matching format-argument positions/types/counts. Positional reordering is allowed.
- `Sources/iOS/InfoPlist.xcstrings` owns only the two system purpose-string translations. English
  must match the declared Info.plist text. It is explicitly included in the iOS resources phase.
- `IOSInterfaceText` supplies iOS-only onboarding/navigation/Studio, enrollment, History/player,
  warning and display-only language/preset copy; `IOSSettingsText`
  supplies Settings copy. These presentation owners never assemble generation requests.
- `VocelloPresentationText` owns dynamic errors and statuses that would otherwise concatenate
  independently translated fragments. Callers pass substitutions into complete localized format
  strings.
- `project.yml` enables String Catalog symbol generation, emitted localization strings, and catalog
  preference globally. The macOS app receives the catalog through its existing Resources bundle;
  the iOS app lists it explicitly in `sources:` with `buildPhase: resources`, as required by the
  repository's XcodeGen resource policy.
- `scripts/localization_contract.py validate` verifies the catalog, project settings, target
  placement, typed adoption, plural contract, and both pseudo-localization XCUITest surfaces.

## Direct-literal growth guard

`config/localization-unlocalized-baseline.json` records content-addressed identities for existing
direct string-literal arguments to common SwiftUI presentation APIs under `Sources/iOS`,
`Sources/Views`, and `Sources/SharedSupport`. The validator permits removal but rejects a new or
additional occurrence. It is an incremental migration boundary, not proof that every indirect or
computed string is localized.

Prefer a typed catalog entry. If an exceptional direct literal is deliberate, review it and then
refresh the baseline explicitly:

```sh
python3 scripts/localization_contract.py snapshot \
  --output config/localization-unlocalized-baseline.json
python3 scripts/localization_contract.py validate
```

Never refresh the baseline merely to silence an unexplained failure. The baseline stores repository
paths, presentation API names, counts, and SHA-256 identities; it does not duplicate user-facing
copy.

## Migration and acceptance order

Work status remains in `config/roadmap.json`: ASR-12 owns candidate-wide localization/layout
acceptance and cross-references ISU-4 for the existing Settings navigation defect.

1. Complete English/French source migration, including indirect strings, errors, permissions,
   enrollment, player/History controls and VoiceOver descriptions. Keep identifiers and behavior.
2. Qualify the large-text layouts on post-ISU-5 source. The AX-L fixed-padding defect is corrected
   by measured dock clearance and has partial physical confirmation. The AX-XXXL/pseudo overshoot
   had a product cause, not only a harness one: the persistent tab dock had no Dynamic Type ceiling
   and grew upward into the region a Settings scroll gesture starts in. ISU-5 (2026-09-11) caps the
   dock at the first accessibility size, restores the switch trait on the compact toggles, hides the
   duplicated tab icon from VoiceOver and stacks the App Language rows at accessibility sizes. The
   two earlier element-swipe experiments treated the symptom and stay reverted. What remains is one
   separately authorized `scripts/ui_test.sh ios localization` walk covering English/French AX-XXXL
   and pseudo-AX-XXXL; ISU-4 owns that run. Preserve the helper's strict visibility predicates and
   bounded failure observations. A visible screenshot is not proof of hittability, and clipping-audit
   success is not proof of every row's visibility.
3. After the English/French and long-string walks qualify, expand in bounded batches:
   Spanish/German/Italian/Brazilian Portuguese, then Simplified Chinese/Japanese/Korean/Russian.
   The maintainer selected Brazilian Portuguese (`pt-BR`) and Simplified Chinese (`zh-Hans`)
   on September 10. This choice does not change generated-speech language identities.
   Do not add partially translated locales to shipping resources just to advertise ten languages.
4. Prepare matching App Store text/screenshots separately for accepted UI locales. Account metadata
   changes need separate authorization. Generated speech support does not imply localized UI support.

The implementation batches are not permission to skip remaining English/French review or claim a
ten-language release. Device work remains separately authorized.

## Existing acceptance routes

The focused `scripts/ui_test.sh macos localization` readiness journey launches with Foundation's
double-length and untranslated-string diagnostics. The `scripts/ui_test.sh ios localization`
Settings layout walk adds a `Pseudo-AX-XXXL` arm combining the same diagnostics with the largest
tested accessibility content-size category. Both use stable accessibility identifiers and genuine
product controls; there is no hidden test UI. iOS acceptance remains physical-device XCUITest only.

The existing iOS localization walk additionally selects English/French through
`iosSettings_appLanguageOption_<locale>`, verifies immediate Settings copy, relaunch selection
and unchanged Studio text, then returns to System Default. Test sessions record the original
interface preference before selecting System Default for process-local language fixtures and restore
it during cleanup; failed restoration is not a pass. New page IDs are
`iosSettings_appLanguageRow`, `screen_settings_appLanguage` and `iosSettings_appLanguageBackButton`.
Authorized September 10 runs exercised English/French selection, relaunch and draft preservation.
The latest bounded run completed Default/French-Default/AX-L, but was interrupted for the phone
deadline before AX-XXXL/pseudo acceptance. These are source-bound partial observations, not a
passing whole-lane result; see the current development checkpoint for retained run identities.

Broad translations may be accepted only after the relevant deterministic checks, macOS smoke, and
physical-iPhone long-string/accessibility walk pass for the exact source change. Completed
English/French Default and AX-L Settings checks from September 10 remain historical evidence;
AX-XXXL/pseudo navigation failures and incomplete broader accessibility coverage remain open,
not inherited PASS for later translations. See the current development checkpoint for exact runs.
