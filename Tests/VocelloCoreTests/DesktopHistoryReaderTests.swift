import CryptoKit
import Foundation
import GRDB
import QwenVoiceCore
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
        let reader = DesktopHistoryReader(root: root)
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
        let reader = DesktopHistoryReader(root: root)
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
        let reader = DesktopHistoryReader(root: root)
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
        let reader = DesktopHistoryReader(root: root)
        XCTAssertFalse(reader.longFormRecoveryPending, "an empty journal is not pending")
        try Data("{}".utf8).write(to: journal.appendingPathComponent("entry.json"))
        let page = try reader.page()
        XCTAssertTrue(page.longFormRecoveryPending)
        XCTAssertEqual(page.items.map(\.text), ["Single"])
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
            "QwenVoice.MacModelVariantPreference.clone": "quality", "QwenVoice.MacModelVariantPreference.design": "turbo",
        ]
        let settings = DesktopAppSettings(domain: DesktopAppSettings.releaseDomain) { values[$0] }
        let entries = Dictionary(uniqueKeysWithValues: settings.all().map { ($0.name, $0) })
        XCTAssertEqual(Set(entries.keys), Set(DesktopAppSettings.names))
        XCTAssertEqual(entries["autoplay"]?.value, "false")
        XCTAssertEqual(entries["autoplay"]?.isDefault, false)
        XCTAssertEqual(entries["variation"]?.value, "consistent")
        XCTAssertEqual(entries["output-folder"]?.value, "default", "a blank folder is the default")
        XCTAssertEqual(entries["variant.clone"]?.value, "quality")
        XCTAssertEqual(entries["variant.design"]?.value, "automatic", "an unknown variant reads as automatic")
        XCTAssertEqual(entries["prefer-lower-memory"]?.value, "false")
        XCTAssertEqual(entries["interface-language"]?.settable, false)
        XCTAssertNil(settings.entry("consent"), "consent is never a CLI setting")
        XCTAssertEqual(DesktopAppSettings(debug: false).domain, "com.qwenvoice.app")
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
