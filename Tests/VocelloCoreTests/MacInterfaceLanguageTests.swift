import Foundation
import QwenVoiceCore
import XCTest

/// The nonisolated copy owner reads one localization from every context:
/// the observable owner on the main thread, the published snapshot elsewhere.
@MainActor
final class MacInterfaceLanguageTests: XCTestCase {
    private let suiteName = "vocello.tests.MacInterfaceLanguage"

    override func setUp() {
        super.setUp()
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        // The test bundle carries the catalog, so English and French are available.
        MacInterfaceLanguage.bootstrap(IOSAppLanguage(
            defaults: defaults,
            bundle: Bundle(for: MacInterfaceLanguageTests.self),
            preferredLanguages: { ["en-CA"] }
        ))
    }

    override func tearDown() {
        UserDefaults(suiteName: suiteName)?.removePersistentDomain(forName: suiteName)
        MacInterfaceLanguage.bootstrap(IOSAppLanguage())
        super.tearDown()
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
}
