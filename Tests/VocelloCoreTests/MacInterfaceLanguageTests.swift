import Foundation
import QwenVoiceCore
import XCTest

/// The nonisolated copy owner reads one localization from every context:
/// the observable owner on the main thread, the published snapshot elsewhere.
@MainActor
final class MacInterfaceLanguageTests: XCTestCase {
    private let suiteName = "vocello.tests.MacInterfaceLanguage"

    // `setUp`/`tearDown` overrides keep XCTestCase's nonisolated signature whatever the
    // class annotation says, so the owner swap hops to the main actor explicitly.
    override func setUp() async throws {
        try await super.setUp()
        let suiteName = suiteName
        await MainActor.run {
            let defaults = UserDefaults(suiteName: suiteName)!
            defaults.removePersistentDomain(forName: suiteName)
            // The test bundle carries the same catalog as both apps.
            MacInterfaceLanguage.bootstrap(IOSAppLanguage(
                defaults: defaults,
                bundle: Bundle(for: MacInterfaceLanguageTests.self),
                preferredLanguages: { ["en-CA"] }
            ))
        }
    }

    override func tearDown() async throws {
        let suiteName = suiteName
        await MainActor.run {
            UserDefaults(suiteName: suiteName)?.removePersistentDomain(forName: suiteName)
            MacInterfaceLanguage.bootstrap(IOSAppLanguage())
        }
        try await super.tearDown()
    }

    func testSystemDefaultFollowsThePreferredLanguage() {
        XCTAssertEqual(MacInterfaceLanguage.selection, IOSAppLanguage.system)
        XCTAssertEqual(MacInterfaceLanguage.current.language, "en")
        XCTAssertTrue(MacInterfaceLanguage.availableLanguages.contains(.french))
    }

    func testSelectionPublishesToEveryContext() async {
        MacInterfaceLanguage.select(IOSUILanguage.french.rawValue)
        XCTAssertEqual(MacInterfaceLanguage.selection, "fr")
        XCTAssertEqual(MacInterfaceLanguage.current.language, "fr")
        XCTAssertEqual(UserDefaults(suiteName: suiteName)?.string(forKey: IOSAppLanguage.preferenceKey), "fr")
        let offMain = await Task.detached {
            XCTAssertFalse(Thread.isMainThread)
            return MacInterfaceLanguage.current.language
        }.value
        XCTAssertEqual(offMain, "fr")

        MacInterfaceLanguage.select(IOSAppLanguage.system)
        let restored = await Task.detached { MacInterfaceLanguage.current.language }.value
        XCTAssertEqual(restored, "en")
        XCTAssertNil(UserDefaults(suiteName: suiteName)?.string(forKey: IOSAppLanguage.preferenceKey))
    }

    func testEveryCompiledLanguagePersistsAndPublishesWithoutChangingUserContent() async {
        let expected = ["en": "Ready", "fr": "Prêt", "es": "Listo", "de": "Bereit",
                        "it": "Pronto", "pt-BR": "Pronto", "zh-Hans": "就绪", "ja": "準備完了",
                        "ko": "준비됨", "ru": "Готово"]
        let defaults = UserDefaults(suiteName: suiteName)!
        let bundle = Bundle(for: Self.self)
        defaults.set("french", forKey: "test.speechLanguage")
        defaults.set("Exact 日本語 draft", forKey: "test.draft")
        XCTAssertEqual(Set(MacInterfaceLanguage.availableLanguages.map(\.rawValue)), Set(expected.keys))
        for language in IOSUILanguage.allCases {
            let identifier = language.rawValue
            MacInterfaceLanguage.select(identifier)
            XCTAssertEqual(MacInterfaceLanguage.owner.presentation.status(.ready), expected[identifier], identifier)
            let restored = IOSAppLanguage(defaults: defaults, bundle: bundle, preferredLanguages: { ["en"] })
            XCTAssertEqual(restored.selection, identifier)
            XCTAssertEqual(restored.resolvedLanguage, identifier)
            XCTAssertEqual(restored.interfaceLocale.region, Locale.current.region)
            let snapshotLanguage = await Task.detached { MacInterfaceLanguage.current.language }.value
            XCTAssertEqual(snapshotLanguage, identifier)
            XCTAssertEqual(defaults.string(forKey: "test.speechLanguage"), "french")
            XCTAssertEqual(defaults.string(forKey: "test.draft"), "Exact 日本語 draft")
        }
        MacInterfaceLanguage.select("unsupported")
        XCTAssertEqual(MacInterfaceLanguage.selection, IOSAppLanguage.system)
        XCTAssertEqual(MacInterfaceLanguage.current.language, "en")
    }

    func testSystemLanguageRegionalMatchingAcrossShippedLocales() {
        let regions = ["en-CA": "en", "fr-CA": "fr", "es-MX": "es", "de-AT": "de",
                       "it-CH": "it", "pt-BR": "pt-BR", "zh-CN": "zh-Hans", "ja-JP": "ja",
                       "ko-KR": "ko", "ru-RU": "ru", "ar": "en"]
        for (preferred, expected) in regions {
            XCTAssertEqual(IOSAppLanguage.resolve(selection: IOSAppLanguage.system,
                                                 available: IOSUILanguage.allCases,
                                                 preferred: [preferred]), expected, preferred)
        }
    }

    func testCompiledRussianAndEastAsianPlurals() {
        let bundle = Bundle(for: Self.self)
        let russian = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: "ru"))
        for (count, expected) in [(0, "0 моделей готовы"), (1, "1 модель готова"), (2, "2 модели готовы"),
                                  (5, "5 моделей готовы"), (11, "11 моделей готовы"), (21, "21 модель готова"),
                                  (22, "22 модели готовы"), (25, "25 моделей готовы")] {
            XCTAssertEqual(russian.readyModelCount(count), expected)
        }
        for (language, format) in [("zh-Hans", "%d 个模型已就绪"), ("ja", "%d モデル準備完了"),
                                    ("ko", "모델 %d개 준비됨")] {
            let text = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: language))
            for count in [0, 1, 2, 5] {
                XCTAssertEqual(text.readyModelCount(count), String(format: format, count), language)
            }
        }
    }
}
