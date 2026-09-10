import Foundation
import Observation
import XCTest

final class IOSAppLanguageTests: XCTestCase {
    @MainActor
    func testPreferencePersistsWithoutChangingOtherPreferences() throws {
        let suite = "IOSAppLanguageTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("french", forKey: "test.outputLanguage")
        defaults.set("reviewed transcript", forKey: "test.transcript")
        let bundle = Bundle(for: Self.self)
        let owner = IOSAppLanguage(defaults: defaults, bundle: bundle, preferredLanguages: { ["fr-CA"] })
        XCTAssertEqual(owner.selection, "system")
        XCTAssertEqual(owner.resolvedLanguage, "fr")
        XCTAssertTrue(owner.availableLanguages.contains(.english))
        XCTAssertTrue(owner.availableLanguages.contains(.french))
        owner.select("en")
        XCTAssertEqual(owner.presentation.status(.ready), "Ready")
        let restored = IOSAppLanguage(defaults: defaults, bundle: bundle, preferredLanguages: { ["fr-CA"] })
        XCTAssertEqual(restored.selection, "en")
        XCTAssertEqual(restored.resolvedLanguage, "en")
        owner.select("fr")
        XCTAssertEqual(owner.presentation.status(.ready), "Prêt")
        XCTAssertEqual(defaults.string(forKey: "test.outputLanguage"), "french")
        XCTAssertEqual(defaults.string(forKey: "test.transcript"), "reviewed transcript")
        owner.select("system")
        XCTAssertNil(defaults.object(forKey: IOSAppLanguage.preferenceKey))
        XCTAssertEqual(owner.resolvedLanguage, "fr")
    }

    @MainActor
    func testInvalidPreferenceAndMissingResourcesFallBackWithoutAdvertisingMissingLocales() throws {
        let suite = "IOSAppLanguageTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("unsupported", forKey: IOSAppLanguage.preferenceKey)
        let owner = IOSAppLanguage(defaults: defaults, bundle: Bundle(for: Self.self), preferredLanguages: { ["ar"] })
        XCTAssertEqual(owner.selection, "system")
        XCTAssertEqual(owner.resolvedLanguage, "en")
        XCTAssertEqual(Set(owner.availableLanguages.map(\.rawValue)),
                       Set(Bundle(for: Self.self).localizations).intersection(Set(IOSUILanguage.allCases.map(\.rawValue))))
        owner.select("unsupported")
        XCTAssertEqual(owner.selection, "system")
    }

    @MainActor
    func testBundleResolutionHandlesRegionalVariantsAndExplicitChoiceWins() {
        XCTAssertEqual(IOSAppLanguage.resolve(selection: "system", available: [.english, .french], preferred: ["fr-CA"]), "fr")
        XCTAssertEqual(IOSAppLanguage.resolve(selection: "en", available: [.english, .french], preferred: ["fr"]), "en")
        XCTAssertEqual(IOSAppLanguage.resolve(selection: "system", available: [.english, .portuguese], preferred: ["pt-BR"]), "pt-BR")
        XCTAssertEqual(IOSAppLanguage.resolve(selection: "system", available: [.english, .chinese], preferred: ["zh-CN"]), "zh-Hans")
        XCTAssertEqual(IOSAppLanguage.resolve(selection: "system", available: [], preferred: ["fr"]), "en")
    }

    @MainActor
    func testActualSharedPresentationTracksLanguageAndPreservesPriceAndUserText() async throws {
        let suite = "IOSAppLanguageTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let owner = IOSAppLanguage(defaults: defaults, bundle: Bundle(for: Self.self), preferredLanguages: { ["en"] })
        let changed = expectation(description: "Presentation observes language changes")
        withObservationTracking {
            XCTAssertEqual(owner.presentation.status(.ready), "Ready")
        } onChange: { changed.fulfill() }
        owner.select("fr")
        await fulfillment(of: [changed], timeout: 1)
        XCTAssertEqual(owner.presentation.status(.generationFailed), "Échec de la génération")
        let price = "19,99 $US"
        XCTAssertTrue(owner.presentation.exportBuy(price).contains(price))
        let original = "Exact %1$@ 日本語 transcript"
        XCTAssertEqual(owner.presentation.playerSubtitle(original, duration: "1:02"), original + " · 1:02")
        XCTAssertEqual(owner.interfaceLocale.region, Locale.current.region)
        XCTAssertEqual(owner.interfaceLocale.language.languageCode?.identifier, "fr")
    }

    func testCompiledFrenchPluralFormsAndFallback() {
        let context = VocelloLocalization(bundle: Bundle(for: Self.self), language: "fr")
        let text = VocelloPresentationText(localization: context)
        XCTAssertEqual(text.readyModelCount(0), "0 modèle prêt")
        XCTAssertEqual(text.readyModelCount(1), "1 modèle prêt")
        XCTAssertEqual(text.readyModelCount(2), "2 modèles prêts")
        XCTAssertEqual(context.string(localized: "unknown.test.key", defaultValue: "Fallback", comment: "Test"), "Fallback")
    }
}
