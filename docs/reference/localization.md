---
status: active
owner: ios
reviewed: 2026-09-21
summary: Vocello localization architecture, String Catalog ownership, typed presentation vocabulary, literal-growth guard, and pseudo-localization acceptance.
sourceOfTruth:
  - project.yml
  - Sources/Resources/Localizable.xcstrings
  - Sources/iOS/InfoPlist.xcstrings
  - Sources/iOS/IOSRootNavigationModels.swift
  - Sources/SharedSupport/Services/VocelloPresentationText.swift
  - Sources/SharedSupport/Services/VoiceDesignBriefCatalog.swift
  - Sources/Services/MacInterfaceText.swift
  - Sources/SharedSupport/Services/VocelloLocalization.swift
  - Sources/iOSSupport/Services/IOSAppLanguage.swift
  - Sources/Services/MacInterfaceLanguage.swift
  - scripts/localization_contract.py
  - config/localization-unlocalized-baseline.json
  - Tests/VocelloMacUITests/VocelloMacSmokeUITests.swift
  - Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift
---
# Localization architecture

English is the source language. The main catalog contains 948 entries with complete English, French,
Spanish, German, Italian, Brazilian Portuguese (`pt-BR`), Simplified Chinese (`zh-Hans`), Japanese,
Korean and Russian translations, including Settings/purchase copy, enrollment transcription
states, storage recovery, model terminal states, onboarding, tab labels and primary Studio actions.
The iOS permission catalog supplies microphone and Speech purpose strings separately, as required
by the system. The expanded migration covers secondary sheets, recording and enrollment warnings,
History filters/actions/recovery, player controls, download transfer details, long-form progress,
displayed language/preset names and additional accessibility descriptions. Catalog completeness is
**not whole-app acceptance**: rendered layouts and indirect errors from shared/system services
still require review. Stored names, user-authored briefs, technical diagnostics, raw system error
details and original license bodies are not translated by string substitution.

Studio's Voice Design starting points and delivery preset names/descriptions follow the selected
speech language, independently of interface localization. `StudioPromptContent` in
`VoiceDesignBriefCatalog.swift` owns this bounded content for all ten speech languages (Simplified
Chinese and Brazilian Portuguese). Auto follows script detection; without a detected language it
uses the resolved interface language, then English. This speech-language content has its own selection rules; the interface catalog separately
provides the ten UI locales. Selecting a starter explicitly
inserts its displayed text into the editable brief; changing language alone never replaces that
brief or a custom delivery. Preset translations are presentation only: IDs, intensity and canonical
model-facing instructions remain unchanged. macOS menu help and accessibility hints carry the
delivery descriptions; iOS displays them below each preset. Starting-point placeholders use the
same speech-language content. Ordinary labels and controls still follow the interface language.

The generated-audio language and app UI language are independent. Never translate user scripts,
reference transcripts, saved voice names, model IDs, enum raw values, seeds, or model-facing delivery
instructions as part of UI localization. Delivery instruction variants retain their own routing
contract. StoreKit remains the authority for the localized price; never format a fixed US price.
Original license/NOTICE bodies remain unchanged; translate their surrounding browser controls only.

## Authorities

- `IOSAppLanguage.shared` is the observable, app-lifetime iOS interface-language owner.
  Settings → App Language stores `vocello.ios.interfaceLanguage`; absence or an unsupported value
  means System Default. Choices are filtered against compiled bundle localizations; both apps now compile all ten
  complete locales listed above.
  System Default uses OS language preferences and bundle matching, with English fallback.
  No `AppleLanguages` preference mutation, bundle swizzling, or root identity reset is used.
  The SwiftUI locale retains the current region; StoreKit prices remain opaque supplied strings.
- `VocelloLocalization` resolves the selected compiled catalog bundle. `IOSInterfaceText` and
  `IOSSettingsText` read the observable owner; iOS dynamic copy uses its `presentation` context.
  Since 2026-09-15 (CONV-14) macOS has the same owner type: `MacInterfaceLanguage` holds an
  `IOSAppLanguage` over `AppDefaults.store` (the same `vocello.ios.interfaceLanguage` key, in the
  debug suite under `QWENVOICE_DEBUG=1`, so a lane never sees a maintainer's pick) and republishes
  its localization to `MacInterfaceText`: the observable owner on the main thread, the last
  published snapshot for nonisolated callers. Shared callers retain default-bundle text through
  the existing static interfaces.
  Startup and unsupported-device presentation receive the same app-boundary locale.
  Already stored error strings are not reverse-translated; completing indirect error/status
  ownership remains part of interface acceptance. Do not claim whole-app live switching from catalog tests.

- `Sources/Resources/Localizable.xcstrings` owns interface translations. Manual entries require
  all ten locales and non-empty translator context. Locale-specific cardinal categories are
  enforced: EN/DE one/other; FR/ES/IT/pt-BR one/many/other; Russian one/few/many/other;
  Chinese/Japanese/Korean other. Every form preserves format-argument positions/types/counts;
  positional reordering is allowed. The French many form retains the existing plural wording.
- `Sources/iOS/InfoPlist.xcstrings` owns only the two system purpose-string translations. English
  must match the declared Info.plist text. It is explicitly included in the iOS resources phase.
- `IOSInterfaceText` supplies iOS-only onboarding/navigation/Studio, enrollment, History/player,
  warning and display-only language/preset copy; `IOSSettingsText`
  supplies Settings copy. These presentation owners never assemble generation requests.
- `VocelloPresentationText` owns dynamic errors and statuses that would otherwise concatenate
  independently translated fragments. Callers pass substitutions into complete localized format
  strings.
- `MacInterfaceText` (`Sources/Services/MacInterfaceText.swift`, macOS target only) owns the macOS
  interface copy: sidebar, menus, Settings, Saved Voices, History, the generation surfaces and their
  sheets read plain `String`s from `vocello.mac.*` entries with all ten locales and translator context.
  Since 2026-09-14 no direct presentation literal remains under `Sources/Views` except the empty
  keyboard-shortcut bridge button and the brief starters label, whose interpolation key holds two
  placeholders and no words (`Text + Text` is deprecated on macOS 26); since 2026-09-15 the
  model-driven labels (sidebar items and sections, variant names, model statuses, readiness copy,
  batch and alert text) read the catalog too, through the owner's hand-maintained `modeName`,
  `qualityWarningShortLabel` and `activityLabel` helpers, so `GenerationMode.displayName` and
  `EngineActivityLabels` stay English identities for the engine, CLI and telemetry. The validator
  binds every `vocello.mac.` key to exactly one default there, like the iOS and shared prefixes.
- `project.yml` enables String Catalog symbol generation, emitted localization strings, and catalog
  preference globally. The macOS app receives the catalog through its existing Resources bundle;
  the iOS app lists it explicitly in `sources:` with `buildPhase: resources`, as required by the
  repository's XcodeGen resource policy.
- `scripts/localization_contract.py validate` verifies the catalog, project settings, target
  placement, typed adoption, plural contract, and both pseudo-localization XCUITest surfaces.

## Direct-literal growth guard

`config/localization-unlocalized-baseline.json` records content-addressed identities for existing
direct string-literal arguments to common SwiftUI presentation APIs under `Sources/iOS`,
`Sources/Views`, and `Sources/SharedSupport`. After the 2026-09-14 macOS migration it holds eleven iOS records
and no macOS exception since 2026-09-15 (the empty keyboard-shortcut bridge button left with the legacy composer, the wordless starters-label key with the legacy brief editor). The validator permits removal but rejects a new or
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

## Acceptance scope and routes

The September 21 assignment completes all eight additional UI catalogs for both apps, with
macOS UI validation and phone-free iOS compilation. Physical-iPhone acceptance is deferred until
the phone is available. Website and App Store metadata are separate work. Catalog completeness
and a successful compile do not qualify a ten-language release or prove native-speaker review.
`config/roadmap.json` remains the work authority: ASR-12 owns signed-candidate device acceptance;
ISU-4 owns the remaining Settings/accessibility and purchase qualification.

- `scripts/localization_contract.py validate` requires every locale in every entry, matching format
  arguments and locale-specific plurals. Its Python fixtures reject missing locales/categories,
  malformed catalogs and permission-catalog gaps.
- `scripts/dev.sh test --only MacInterfaceLanguageTests` uses the actual compiled catalog to check
  all ten choices, immediate lookup, persisted selection, detached-reader snapshots, regional
  matching and Russian/East Asian plural boundaries. Both apps share the language owner.
- `scripts/ui_test.sh macos localization` runs the existing pseudo-localized minimum-window walk,
  then selects all ten languages through the real Settings picker. It checks translated labels,
  Settings/library/Studio geometry, unchanged drafts, Voice Design's popover and selection after
  relaunch, with screenshots and restoration of the original language. The journey passes
  `-ApplePersistenceIgnoreState YES` only in its launch argument domain to isolate saved window
  state; it does not clear stored preferences or drafts. Apple documents this option for automated
  tests in its [AppKit notes](https://developer.apple.com/library/archive/releasenotes/AppKit/RN-AppKitOlderNotes/index.html).
- `scripts/ui_test.sh ios localization` now prepares all ten explicit language selections in its
  Default arm, checking Settings copy, persisted choice and unchanged Studio text. The existing
  French, AX-L, AX-XXXL and pseudo-AX-XXXL arms remain. Every run observes and restores the original
  interface preference through genuine controls. This expanded journey has not yet run on a phone.

The September 21 physical run `ios-xcui-localization-20260921-054309-966a91d7` passed its then-current
EN/FR and text-size walk. The later variation-label fix passed the accessibility control audit
`ios-xcui-control-audit-20260921-064147-ef16ae49`. These precede the eight new catalogs and cannot
qualify them. Full French accessibility-size coverage, spoken VoiceOver, the remaining purchase
lifecycle and broader signed-candidate scenarios remain open under ISU-4/ASR-12. Earlier September
10 partial evidence and failed navigation attempts remain historical; see the roadmap and Git history.
