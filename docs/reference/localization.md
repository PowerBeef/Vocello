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

English is the source language. The main catalog contains 951 entries with complete English, French,
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
- `VocelloLocalization` resolves the selected compiled catalog bundle; since PA-20 its `fileSize`
  and `dateTime` helpers format model and file sizes and History dates in the interface locale on
  both platforms, never the process locale. `IOSInterfaceText` and
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
  strings. Since PA-20, typed engine and generation failures reach both apps through
  `generationFailureMessage(_:)`, keyed on the path-free `GenerationFailurePresentationReason`
  (QwenVoiceCore: memory pressure, runtime and preparation failures, the generation limit, the
  audio-quality rejections, and the reference-audio, storage, memory and model errors an engine
  failure wraps). The engine's English messages stay the CLI and diagnostic text; each app host
  installs the mapper as `MLXTTSEngine.visibleErrorDescription`, so the engine's visible error, a
  failed load and a failed clone preparation read the interface language too. Errors without a typed
  reason keep their own description.
- `MacInterfaceText` (`Sources/Services/MacInterfaceText.swift`; the macOS app, and also compiled
  into `VocelloCoreTests`, so it must not reference app-only types) owns the macOS
  interface copy: sidebar, menus, Settings, Saved Voices, History, the generation surfaces and their
  sheets read plain `String`s from `vocello.mac.*` entries with all ten locales and translator context.
  Since 2026-09-14 no direct presentation literal remains under `Sources/Views` except the empty
  keyboard-shortcut bridge button and the brief starters label, whose interpolation key holds two
  placeholders and no words (`Text + Text` is deprecated on macOS 26); since 2026-09-15 the
  model-driven labels (sidebar items and sections, variant names, model statuses, readiness copy,
  batch and alert text) read the catalog too, through the owner's hand-maintained `modeName`,
  `qualityWarningShortLabel` and `activityLabel` helpers, so `GenerationMode.displayName` and
  `EngineActivityLabels` stay English identities for the engine, CLI and telemetry. Since PA-20
  the speech-language names, saved-voice quality warnings, the delivery duration advisory, voice-bank
  preset names and suggested voice names follow the same rule (`languageName`, `presetName`,
  `qualityWarningHeadline`, `qualityWarningSummary`), and `MacInterfaceLanguageTests` holds their
  English copy equal to the QwenVoiceCore identities. The validator
  binds every `vocello.mac.` key to exactly one default there, like the iOS and shared prefixes.
  Numeric-only displays (timers, counts, seeds) use `Text(verbatim:)` so they never become catalog
  keys. During a macOS UI lane, doubled or UPPERCASE text is the pseudo-localization diagnostic, not
  a bug (see [macOS testing](macos-testing.md)).
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
  relaunch, with screenshots and restoration of the original language. Before the doubled-text
  fixture, it preserves the current selection and selects English through genuine controls.
  Offscreen popup options are revealed with bounded arrow-key navigation. Compact translations
  use the rendered line height as their glyph-width floor; English/pseudo word-width minima and
  all height/window checks remain. The journey passes
  `-ApplePersistenceIgnoreState YES` only in its launch argument domain to isolate saved window
  state; it does not clear stored preferences or drafts. Apple documents this option for automated
  tests in its [AppKit notes](https://developer.apple.com/library/archive/releasenotes/AppKit/RN-AppKitOlderNotes/index.html).
- `scripts/ui_test.sh ios localization` now prepares all ten explicit language selections in its
  Default arm, checking Settings copy, persisted choice and unchanged Studio text. The existing
  French, AX-L, AX-XXXL and pseudo-AX-XXXL arms remain. Every run observes and restores the original
  interface preference through genuine controls. This expanded journey has not yet run on a phone.

## September 21 Mac evidence

`macos-xcui-localization-20260922-004619-79391bc0` passed the complete ten-language journey in
1,807 seconds on source `25f27b62` plus the unchanged paused marketing-test edit. All required
steps, including crash delta, passed; the original development-profile language was restored.
The production preference suite was untouched. Representative Russian, Japanese, Korean and
German screenshots were visually reviewed. Evidence remains untracked under `build/artifacts/ui-tests/macos`.
The actual compact outer window was 780x612 pt. The September 22 follow-up corrected the initial
interpretation: its 52-point toolbar leaves the declared 780x560 content area. Strict content/viewport
assertions now prove that minimum. The complete ten-language journey also passed inside smoke run
`macos-xcui-smoke-20260922-041322-1258c968` on `d7058ea6`; see the
[Mac acceptance scope and limits](macos-ios-ui-reset-2026-09.md#mac-acceptance-september-22).
This is local UI evidence, not signed-candidate, VoiceOver or native-speaker acceptance.

Earlier attempts remain separate failures, never combined into this PASS:

| Run | Finding and correction |
| --- | --- |
| `macos-xcui-localization-20260921-230026-368d03bf` | Restored app launch exposed no window; isolate saved window state with Apple's launch-only option. |
| `macos-xcui-localization-20260921-230850-985cf668` | Picker announced App Language twice; remove its redundant accessibility label. |
| `macos-xcui-localization-20260921-232214-16021619` | English width assumption rejected a readable Chinese badge. |
| `macos-xcui-localization-20260921-235914-d88393d2` | Fixed 20 pt floor rejected a readable 19.5 pt Korean badge; use a glyph-sized floor for localized labels. |
| `macos-xcui-localization-20260922-002001-fbdd0a9d` | English was above the display in AppKit's scrolling menu after selecting Russian; reveal offscreen choices with real keyboard navigation. Cleanup encountered the same issue in this failed run. |

The application/catalog commit `4ed9d357` passed [CI](https://github.com/PowerBeef/Vocello/actions/runs/35669981154),
including the generic iOS compile. Final UI-test source `25f27b62` passed
[CI](https://github.com/PowerBeef/Vocello/actions/runs/35673303543), including deterministic Mac tests
and TSan. Local Xcode 27/Swift 6.4 results are separate from the pinned CI toolchain.

The September 21 physical run `ios-xcui-localization-20260921-054309-966a91d7` passed its then-current
EN/FR and text-size walk. The later variation-label fix passed the accessibility control audit
`ios-xcui-control-audit-20260921-064147-ef16ae49`. These precede the eight new catalogs and cannot
qualify them. Full French accessibility-size coverage, spoken VoiceOver, the remaining purchase
lifecycle and broader signed-candidate scenarios remain open under ISU-4/ASR-12. Earlier September
10 partial evidence and failed navigation attempts remain historical; see the roadmap and Git history.
