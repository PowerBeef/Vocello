import CryptoKit
import Foundation
import GRDB
import QwenVoiceCore
import Synchronization
import XCTest
import VocelloDesktopCore

/// RF-26: the CLI reads the History the app writes, through a read-only
/// connection that never migrates or writes it and refuses a newer schema;
/// the app's settings through the app's preferences domain; the briefs and
/// delivery banks the app shows.
final class DesktopHistoryReaderTests: XCTestCase {
    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DesktopHistoryReader-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func row(
        _ text: String, mode: String = "custom", at seconds: TimeInterval, audioPath: String,
        duration: Double = 1.5, projectID: String? = nil, role: String? = nil, seed: Int64? = nil
    ) -> Generation {
        Generation(
            id: nil, text: text, mode: mode, modelTier: "speed", voice: "Aiden", emotion: nil, speed: nil,
            audioPath: audioPath, duration: duration, createdAt: Date(timeIntervalSince1970: 1_700_000_000 + seconds),
            longFormProjectID: projectID, longFormRole: role, seed: seed
        )
    }

    /// The app's own service writes the fixture store.
    private func seed(_ root: URL, _ rows: [Generation]) throws {
        let service = DatabaseService(rootDirectory: root)
        for var generation in rows {
            try service.saveGeneration(&generation)
        }
    }

    private func digest(_ url: URL) throws -> String {
        SHA256.hash(data: try Data(contentsOf: url)).map { unsafe String(format: "%02x", $0) }.joined()
    }

    func testAMissingStoreReadsAsEmptyAndCreatesNothing() throws {
        let root = try makeRoot()
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })
        let page = try reader.page()
        XCTAssertEqual(page.items, [])
        XCTAssertEqual(page.totalCount, 0)
        XCTAssertNil(try reader.detail(id: 1))
        XCTAssertFalse(FileManager.default.fileExists(atPath: reader.databaseURL.path), "a reader never creates the store")
    }

    func testPagesMatchTheAppsListingAndNeverChangeTheStore() throws {
        let root = try makeRoot()
        let audio = root.appendingPathComponent("present.wav")
        try Data("RIFF".utf8).write(to: audio)
        try seed(root, [
            row("First take about the harbour", at: 1, audioPath: audio.path, duration: 4, seed: -1),
            row("A designed voice reads", mode: "design", at: 2, audioPath: root.appendingPathComponent("gone.wav").path, duration: 2),
            row("Project joined", at: 3, audioPath: root.appendingPathComponent("joined.wav").path, duration: 9,
                projectID: "p1", role: "joined"),
            row("Segment one", at: 4, audioPath: root.appendingPathComponent("s1.wav").path, projectID: "p1", role: "segment"),
            row("Segment two", at: 5, audioPath: root.appendingPathComponent("s2.wav").path, projectID: "p1", role: "segment"),
        ])
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })
        let before = try digest(reader.databaseURL)

        let page = try reader.page()
        XCTAssertEqual(page.totalCount, 5)
        XCTAssertEqual(page.items.map(\.text), [
            "Project joined", "A designed voice reads", "First take about the harbour", "Segment one", "Segment two",
        ], "newest first; a project's segments follow it, oldest first")
        XCTAssertFalse(page.hasMore)
        let first = try XCTUnwrap(page.items.first { $0.text.hasPrefix("First") })
        XCTAssertEqual(first.seed, "18446744073709551615", "a seed is its unsigned value as a decimal string")
        XCTAssertTrue(first.audioExists)
        XCTAssertFalse(try XCTUnwrap(page.items.first { $0.mode == "design" }).audioExists)
        XCTAssertTrue(first.createdAt.hasSuffix("Z"))

        XCTAssertEqual(try reader.page(mode: "design").items.map(\.mode), ["design"])
        XCTAssertEqual(try reader.page(query: "HARBOUR").items.map(\.text), ["First take about the harbour"],
                       "the Mac search: case-insensitive, text and voice")
        XCTAssertEqual(try reader.page(query: "segment").items.count, 2, "a search lists segments flat")
        let shortest = try reader.page(order: .shortest, limit: 1)
        XCTAssertEqual(shortest.items.first?.durationSeconds, 2, "segments page under their project, not alone")
        XCTAssertTrue(shortest.hasMore)

        let id = try XCTUnwrap(Int64(first.id))
        XCTAssertEqual(try reader.detail(id: id)?.item, first)
        XCTAssertNil(try reader.detail(id: 999_999))
        XCTAssertEqual(try digest(reader.databaseURL), before, "reading never writes the store")
    }

    func testAStoreFromANewerVocelloIsRefused() throws {
        let root = try makeRoot()
        try seed(root, [row("Take", at: 1, audioPath: root.appendingPathComponent("a.wav").path)])
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })
        let queue = try DatabaseQueue(path: reader.databaseURL.path)
        try queue.write { db in
            try db.execute(sql: "INSERT INTO grdb_migrations (identifier) VALUES ('v99_from_the_future')")
        }
        XCTAssertThrowsError(try reader.page()) { error in
            XCTAssertEqual(error as? DesktopHistoryError, .schemaNewer)
        }
    }

    func testAPendingLongFormRecoveryWithholdsProjectRows() throws {
        let root = try makeRoot()
        try seed(root, [
            row("Single", at: 1, audioPath: root.appendingPathComponent("a.wav").path),
            row("Joined", at: 2, audioPath: root.appendingPathComponent("j.wav").path, projectID: "p", role: "joined"),
        ])
        let journal = root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        try FileManager.default.createDirectory(at: journal, withIntermediateDirectories: true)
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })
        XCTAssertFalse(reader.longFormRecoveryPending, "an empty journal is not pending")
        try Data("{}".utf8).write(to: journal.appendingPathComponent("entry.json"))
        let page = try reader.page()
        XCTAssertTrue(page.longFormRecoveryPending)
        XCTAssertEqual(page.items.map(\.text), ["Single"])
    }

    func testReadsAreRefusedWhileTheAppUsesTheStore() throws {
        let root = try makeRoot()
        try seed(root, [row("Take", at: 1, audioPath: root.appendingPathComponent("a.wav").path)])
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in true })
        XCTAssertThrowsError(try reader.page()) { XCTAssertEqual($0 as? DesktopHistoryError, .appRunning) }
        XCTAssertThrowsError(try reader.detail(id: 1)) { XCTAssertEqual($0 as? DesktopHistoryError, .appRunning) }
        XCTAssertFalse(DesktopAppPresence.isAppDataRoot(root), "a scratch root is never the app's")
        let support = try XCTUnwrap(FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first)
        XCTAssertTrue(DesktopAppPresence.isAppDataRoot(support.appendingPathComponent("QwenVoice", isDirectory: true)))
        XCTAssertTrue(DesktopAppPresence.isAppDataRoot(support.appendingPathComponent("QwenVoice-Debug/", isDirectory: true)))
    }

    func testAnOlderStoreIsRefusedAndAHotJournalNeverShowsATornWrite() throws {
        let root = try makeRoot()
        try seed(root, [row("Take", at: 1, audioPath: root.appendingPathComponent("a.wav").path)])
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })

        // A hot journal: a write that spilled pages to disk, copied mid-transaction.
        let copy = try makeRoot()
        let queue = try DatabaseQueue(path: reader.databaseURL.path)
        try queue.inDatabase { db in
            try db.execute(sql: "PRAGMA cache_size = 1")
            try db.execute(sql: "BEGIN IMMEDIATE")
            for index in 0 ..< 400 {
                try db.execute(
                    sql: "UPDATE generations SET text = ? WHERE id = 1",
                    arguments: [String(repeating: "x", count: 4096) + String(index)]
                )
                try db.execute(sql: "INSERT INTO generations (text, mode, modelTier, audioPath, createdAt) VALUES (?, 'custom', 'speed', ?, ?)",
                               arguments: [String(repeating: "y", count: 2048), "/x/\(index).wav", Date()])
            }
            for name in ["history.sqlite", "history.sqlite-journal"] {
                try FileManager.default.copyItem(at: root.appendingPathComponent(name), to: copy.appendingPathComponent(name))
            }
            try db.execute(sql: "ROLLBACK")
        }
        // SQLite recovers the hot journal before the read: only the committed state is seen, never a torn write.
        let recovered = try DesktopHistoryReader(root: copy, appIsUsingRoot: { _ in false }).page()
        XCTAssertEqual(recovered.items.map(\.text), ["Take"])
        XCTAssertEqual(recovered.totalCount, 1)

        try queue.write { db in
            try db.execute(sql: "DELETE FROM grdb_migrations WHERE identifier = (SELECT MAX(identifier) FROM grdb_migrations)")
        }
        XCTAssertThrowsError(try reader.page()) { XCTAssertEqual($0 as? DesktopHistoryError, .schemaOlder) }
    }

    func testRecoveryIsPendingAsTheAppDecides() throws {
        let root = try makeRoot()
        let reader = DesktopHistoryReader(root: root, appIsUsingRoot: { _ in false })
        let journal = root.appendingPathComponent("history-outbox/long-form", isDirectory: true)
        try FileManager.default.createDirectory(at: journal, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: journal.appendingPathComponent("abc.1234.unreadable"))
        XCTAssertFalse(reader.longFormRecoveryPending, "a discarded journal is not pending")
        try Data("{}".utf8).write(to: journal.appendingPathComponent("abc.json"))
        XCTAssertTrue(reader.longFormRecoveryPending)
        try FileManager.default.removeItem(at: journal)
        try Data().write(to: journal)
        XCTAssertTrue(reader.longFormRecoveryPending, "a journal folder that cannot be read fails closed")
    }

    func testExportRefusesWhatSaveAsWouldNot() throws {
        let root = try makeRoot()
        let source = root.appendingPathComponent("take.wav")
        try Data("RIFF".utf8).write(to: source)
        let existing = root.appendingPathComponent("existing.wav")
        try Data("old".utf8).write(to: existing)
        let folder = root.appendingPathComponent("folder.wav", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let other = root.appendingPathComponent("other-take.wav")
        try Data("other".utf8).write(to: other)
        func check(_ destination: URL, replace: Bool = false) -> DesktopHistoryExport.Refusal? {
            do {
                try DesktopHistoryExport.check(destination: destination, source: source, replace: replace) { $0 == other }
                return nil
            } catch {
                return error as? DesktopHistoryExport.Refusal
            }
        }
        XCTAssertNil(check(root.appendingPathComponent("new.wav")))
        XCTAssertEqual(check(root.appendingPathComponent("new.aiff")), .notWAV)
        XCTAssertEqual(check(root.appendingPathComponent("missing/new.wav")), .missingFolder)
        XCTAssertEqual(check(existing), .exists)
        XCTAssertNil(check(existing, replace: true))
        XCTAssertEqual(check(folder, replace: true), .isFolder)
        XCTAssertEqual(check(other, replace: true), .anotherTake, "never another History take")
        XCTAssertNil(check(source), "the take's own file is a no-op")
    }

    func testExportCopiesTheTakeAndTreatsItsOwnFileAsDone() throws {
        let root = try makeRoot()
        let source = root.appendingPathComponent("take.wav")
        try Data("RIFF take".utf8).write(to: source)
        let destination = root.appendingPathComponent("copy.wav")
        XCTAssertEqual(try DesktopHistoryExport.copy(from: source, to: destination), .copied)
        XCTAssertEqual(try Data(contentsOf: destination), Data("RIFF take".utf8))
        XCTAssertEqual(try DesktopHistoryExport.copy(from: source, to: source), .sameFile)
        XCTAssertEqual(try Data(contentsOf: source), Data("RIFF take".utf8), "the only copy survives")
    }

    func testSettingsReadTheAppsKeysWithItsDefaults() {
        let values: [String: any Sendable] = [
            "autoPlay": false, "generationVariation": "consistent", "outputDirectory": "  ",
            "QwenVoice.MacModelVariantPreference.clone": " quality ", "QwenVoice.MacModelVariantPreference.design": "turbo",
            "QwenVoice.PreferSpeedEverywhere": "YES",
        ]
        let release: [String: any Sendable] = ["vocello.ios.interfaceLanguage": "fr"]
        let settings = DesktopAppSettings(
            domain: DesktopAppSettings.debugDomain, read: { values[$0] }, readRelease: { release[$0] }
        )
        let entries = Dictionary(uniqueKeysWithValues: settings.all().map { ($0.name, $0) })
        XCTAssertEqual(Set(entries.keys), Set(DesktopAppSettings.names))
        XCTAssertEqual(entries["autoplay"]?.value, "false")
        XCTAssertEqual(entries["autoplay"]?.isDefault, false)
        XCTAssertEqual(entries["variation"]?.value, "consistent")
        XCTAssertEqual(entries["output-folder"]?.value, "default", "a blank folder is the default")
        XCTAssertEqual(entries["variant.clone"]?.value, "quality")
        XCTAssertEqual(entries["variant.design"]?.value, "automatic", "an unknown variant reads as automatic")
        XCTAssertEqual(entries["interface-language"]?.settable, false)
        XCTAssertEqual(entries["interface-language"]?.value, "fr", "the app keeps it in the release domain")
        XCTAssertEqual(entries["prefer-lower-memory"]?.value, "true", "a string Boolean reads as UserDefaults reads it")
        XCTAssertTrue(settings.prefersLowerMemory)
        XCTAssertEqual(settings.variation, .consistent)
        XCTAssertEqual(settings.explicitVariantID(for: .clone), "quality")
        XCTAssertEqual(settings.explicitVariantID(for: .design), "turbo", "any stored id counts; the resolution skips it")
        XCTAssertNil(settings.explicitVariantID(for: .custom))
        XCTAssertNil(settings.entry("consent"), "consent is never a CLI setting")
        XCTAssertEqual(DesktopAppSettings(debug: false).domain, "com.qwenvoice.app")
    }

    /// RF-28: the CLI sets what the app's Settings set, stored as the app stores it.
    func testSettingsAreSetAsTheAppStoresThem() throws {
        let store = Mutex<[String: any Sendable]>(["generationVariation": "balanced"])
        let settings = DesktopAppSettings(
            domain: DesktopAppSettings.debugDomain,
            read: { key -> Any? in store.withLock { stored -> (any Sendable)? in stored[key] } },
            write: { key, value in
                store.withLock { stored in
                    switch value {
                    case let flag as Bool: stored[key] = flag
                    case let text as String: stored[key] = text
                    default: stored[key] = nil
                    }
                }
                return true
            }
        )
        func stored(_ key: String) -> (any Sendable)? { store.withLock { $0[key] } }
        func code(_ name: String, _ value: String) -> DesktopAppSettings.SetError? {
            do {
                _ = try settings.set(name, to: value)
                return nil
            } catch {
                return error as? DesktopAppSettings.SetError
            }
        }

        XCTAssertEqual(try settings.set("autoplay", to: "off").value, "false")
        XCTAssertEqual(stored("autoPlay") as? Bool, false, "a Boolean, as UserDefaults stores it")
        XCTAssertEqual(try settings.set("prefer-lower-memory", to: "YES").value, "true")
        XCTAssertEqual(stored("QwenVoice.PreferSpeedEverywhere") as? Bool, true)
        XCTAssertEqual(try settings.set("variation", to: " Consistent ").value, "consistent")
        XCTAssertEqual(stored("generationVariation") as? String, "consistent")
        XCTAssertEqual(try settings.set("variant.design", to: "hq").value, "quality")
        XCTAssertEqual(stored("QwenVoice.MacModelVariantPreference.design") as? String, "quality")
        let automatic = try settings.set("variant.design", to: "automatic")
        XCTAssertEqual(automatic.value, "automatic")
        XCTAssertTrue(automatic.isDefault)
        XCTAssertNil(stored("QwenVoice.MacModelVariantPreference.design"), "automatic removes the choice")

        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("settings-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        XCTAssertEqual(try settings.set("output-folder", to: folder.path + "/").value, folder.standardizedFileURL.path)
        XCTAssertEqual(try settings.set("output-folder", to: "default").value, "default")
        XCTAssertNil(stored("outputDirectory"))

        XCTAssertEqual(code("output-folder", folder.appendingPathComponent("missing").path),
                       .invalidValue(name: "output-folder", value: folder.appendingPathComponent("missing").path,
                                     accepted: "an existing folder | default"))
        XCTAssertEqual(code("autoplay", "maybe"), .invalidValue(name: "autoplay", value: "maybe", accepted: "true | false"))
        XCTAssertEqual(code("interface-language", "fr"), .notSettable("interface-language"))
        XCTAssertEqual(code("consent", "true"), .unknownSetting("consent"), "consent is never a CLI setting")

        let readOnly = DesktopAppSettings(domain: DesktopAppSettings.debugDomain, read: { _ in nil })
        XCTAssertThrowsError(try readOnly.set("autoplay", to: "true")) {
            XCTAssertEqual($0 as? DesktopAppSettings.SetError, .writeFailed("autoplay"))
        }
        XCTAssertEqual(Set(DesktopChangeNotice.allCases.map(\.rawValue)).count, 4)
        XCTAssertTrue(DesktopChangeNotice.allCases.allSatisfy { $0.rawValue.hasPrefix("com.qwenvoice.shared.") })
    }

    /// RF-28: the app hears the CLI change a shared store, by the names both use.
    @MainActor
    func testTheAppHearsTheCLIChangeAStore() async {
        XCTAssertEqual(
            DesktopChangeNotice.allCases.map(\.rawValue), SharedStoreChange.allCases.map(\.rawValue),
            "one set of names for the poster and the observer"
        )
        final class Heard {
            var changes: [SharedStoreChange] = []
        }
        let heard = Heard()
        let delivered = expectation(description: "the app hears the saved voices change")
        let observer = MacSharedStoreChangeObserver()
        observer.start { change in
            heard.changes.append(change)
            if change == .savedVoices { delivered.fulfill() }
        }
        observer.start { _ in XCTFail("started once, for the app's life") }
        DesktopChangeNotice.savedVoices.post()
        await fulfillment(of: [delivered], timeout: 10)
        XCTAssertEqual(heard.changes, [.savedVoices])
    }

    @MainActor
    func testTheInterfaceLanguageKeyIsTheOneBothAppsWrite() {
        let appKey = IOSAppLanguage.preferenceKey
        XCTAssertEqual(DesktopAppSettings.interfaceLanguageKey, appKey)
    }

    func testBriefsAndDeliveryBanksFollowTheApp() {
        XCTAssertEqual(DesktopBriefCatalog.briefs().count, 8)
        XCTAssertEqual(DesktopBriefCatalog.briefs(in: .french).count, 8)
        XCTAssertNotEqual(DesktopBriefCatalog.briefs(in: .french).first?.text, DesktopBriefCatalog.briefs().first?.text)
        XCTAssertEqual(DesktopBriefCatalog.briefs().map(\.index), Array(0 ..< 8))
        XCTAssertEqual(DesktopBriefCatalog.descriptionLimit, 500)

        let banks = DesktopVoiceBanks.banks(voices: [
            (id: "Nora", name: "Nora"), (id: "Nora (Happy)", name: "Nora (Happy)"),
            (id: "Solo", name: "Solo"), (id: "Ghost (Sad)", name: "Ghost (Sad)"),
        ])
        XCTAssertEqual(banks.map(\.name), ["Nora"], "a bank needs its base voice and a preset variant")
        XCTAssertEqual(banks.first?.members.map(\.voiceID), ["Nora (Happy)"])
    }
}
