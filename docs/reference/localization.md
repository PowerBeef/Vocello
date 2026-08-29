---
status: active
owner: ios
reviewed: 2026-08-29
summary: Vocello localization architecture, String Catalog ownership, typed presentation vocabulary, literal-growth guard, and pseudo-localization acceptance.
sourceOfTruth:
  - project.yml
  - Sources/Resources/Localizable.xcstrings
  - Sources/SharedSupport/Services/VocelloPresentationText.swift
  - scripts/localization_contract.py
  - config/localization-unlocalized-baseline.json
  - Tests/VocelloMacUITests/VocelloMacSmokeUITests.swift
  - Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift
---
# Localization architecture

> **Currency review (2026-08-27):** the catalog now includes the Help & Support and offline-license
> browser copy with translator context. The direct-literal baseline remains contract-owned and the
> app still ships English UI only. The bilingual Angry engine instruction is governed delivery data,
> not a claim that Mandarin UI localization ships.

Vocello currently ships English source copy. The repository has localization architecture before
translations: one Xcode String Catalog, typed keys for dynamic presentation text, translator
context, plural rules, a deterministic direct-literal growth guard, and long-string acceptance on
macOS plus the paired physical iPhone. This does not claim that the complete existing interface is
already cataloged or that any additional language is supported.

## Authorities

- `Sources/Resources/Localizable.xcstrings` is the owned source-language catalog. Manual entries
  require English content and non-empty translator context. Pluralized counts require `one` and
  `other` categories.
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

## Acceptance before translations

The focused `scripts/ui_test.sh macos localization` readiness journey launches with Foundation's
double-length and untranslated-string diagnostics. The `scripts/ui_test.sh ios localization`
Settings layout walk adds a `Pseudo-AX-XXXL` arm combining the same diagnostics with the largest
tested accessibility content-size category. Both use stable accessibility identifiers and genuine
product controls; there is no hidden test UI. iOS acceptance remains physical-device XCUITest only.

Broad translations may be accepted only after the relevant deterministic checks, macOS smoke, and
physical-iPhone long-string/accessibility walk pass for the exact source change.
