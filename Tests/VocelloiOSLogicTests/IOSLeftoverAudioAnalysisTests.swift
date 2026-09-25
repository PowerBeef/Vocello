import Foundation
import XCTest

/// PA-30: the iPhone's one-time removal offers only audio no History state
/// uses, never a link or a folder, and nothing when a reference or the folder
/// itself cannot be read fully.
final class IOSLeftoverAudioAnalysisTests: XCTestCase {
    private let sessionStart = Date(timeIntervalSince1970: 1_800_000_000)
    private var temporaryRoots: [URL] = []
    private var lockedDirectories: [URL] = []

    override func tearDownWithError() throws {
        for directory in lockedDirectories {
            try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
        }
        lockedDirectories.removeAll()
        for root in temporaryRoots {
            try? FileManager.default.removeItem(at: root)
        }
        temporaryRoots.removeAll()
    }

    func testOffersOnlyUnreferencedRegularAudioWrittenBeforeTheSession() {
        let before = sessionStart.addingTimeInterval(-3_600)
        let folder = "/container-b/Vocello/outputs/CustomVoice"
        let listing = IOSLeftoverAudioAnalysis.Listing(entries: [
            entry("\(folder)/orphan.wav", size: 100, modifiedAt: before),
            entry("\(folder)/ORPHAN-UPPER.WAV", size: 50, modifiedAt: before),
            entry("\(folder)/row.wav", size: 7, modifiedAt: before),
            entry("\(folder)/moved-container.wav", size: 7, modifiedAt: before),
            entry("\(folder)/queued.wav", size: 7, modifiedAt: before),
            entry("\(folder)/link.wav", kind: .symbolicLink, size: 7, modifiedAt: before),
            entry("\(folder)/folder.wav", kind: .directory, size: 7, modifiedAt: before),
            entry("\(folder)/special.wav", kind: .other, size: 7, modifiedAt: before),
            entry("\(folder)/long_form_manifest_1234.json", size: 7, modifiedAt: before),
            entry("\(folder)/in-flight.wav", size: 7, modifiedAt: sessionStart),
        ], isComplete: true)
        let referenced: Set<String> = [
            "\(folder)/row.wav",
            // A row recorded under an earlier container location still keeps
            // the file of the same name.
            "/container-a/Vocello/outputs/CustomVoice/moved-container.wav",
            "\(folder)/queued.wav",
        ]

        let leftovers = IOSLeftoverAudioAnalysis.leftovers(
            in: listing,
            referencedAudioPaths: referenced,
            writtenBefore: sessionStart
        )

        XCTAssertEqual(leftovers?.files.map(\.path), [
            "\(folder)/ORPHAN-UPPER.WAV",
            "\(folder)/orphan.wav",
        ])
        XCTAssertEqual(leftovers?.count, 2)
        XCTAssertEqual(leftovers?.byteCount, 150)
    }

    func testOffersNothingWhenAReferenceOrTheListingCannotBeRead() {
        let listing = IOSLeftoverAudioAnalysis.Listing(
            entries: [entry("/outputs/CustomVoice/orphan.wav", size: 1, modifiedAt: .distantPast)],
            isComplete: true
        )
        XCTAssertEqual(
            IOSLeftoverAudioAnalysis.leftovers(in: listing, referencedAudioPaths: [], writtenBefore: sessionStart)?.count,
            1,
            "Control: readable state offers the orphan"
        )
        // An outbox, removal list or History that cannot be read fully yields
        // no reference set at all: nothing is offered.
        XCTAssertNil(IOSLeftoverAudioAnalysis.leftovers(
            in: listing,
            referencedAudioPaths: nil,
            writtenBefore: sessionStart
        ))
        var incomplete = listing
        incomplete.isComplete = false
        XCTAssertNil(IOSLeftoverAudioAnalysis.leftovers(
            in: incomplete,
            referencedAudioPaths: [],
            writtenBefore: sessionStart
        ))
    }

    func testListingNeverFollowsALinkOrEntersAFolder() throws {
        let root = try makeRoot()
        let folder = root.appendingPathComponent("CustomVoice", isDirectory: true)
        let outside = root.appendingPathComponent("outside", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outside, withIntermediateDirectories: true)
        let orphan = try writeAudio(folder.appendingPathComponent("orphan.wav"), bytes: 12)
        let outsideAudio = try writeAudio(outside.appendingPathComponent("outside.wav"), bytes: 5)
        try FileManager.default.createSymbolicLink(
            at: folder.appendingPathComponent("link.wav"),
            withDestinationURL: outsideAudio
        )
        let subfolder = folder.appendingPathComponent("device-diagnostics", isDirectory: true)
        try FileManager.default.createDirectory(at: subfolder, withIntermediateDirectories: true)
        _ = try writeAudio(subfolder.appendingPathComponent("run.wav"), bytes: 5)
        // A take folder replaced by a link is never read through.
        let linkedFolder = root.appendingPathComponent("VoiceDesign", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: linkedFolder, withDestinationURL: outside)
        let missingFolder = root.appendingPathComponent("Clones", isDirectory: true)

        let listing = IOSLeftoverAudioAnalysis.listing(ofDirectories: [folder, linkedFolder, missingFolder])

        XCTAssertTrue(listing.isComplete, "A missing folder has no entries; a linked one is skipped")
        let kinds = Dictionary(uniqueKeysWithValues: listing.entries.map {
            (($0.path as NSString).lastPathComponent, $0.kind)
        })
        XCTAssertEqual(kinds, [
            "orphan.wav": .regularFile,
            "link.wav": .symbolicLink,
            "device-diagnostics": .directory,
        ])
        let leftovers = IOSLeftoverAudioAnalysis.leftovers(
            in: listing,
            referencedAudioPaths: [],
            writtenBefore: .distantFuture
        )
        XCTAssertEqual(leftovers?.files.map(\.path), [orphan.path])
        XCTAssertEqual(leftovers?.byteCount, 12)
    }

    func testFolderThatCannotBeReadMakesTheListingIncomplete() throws {
        let root = try makeRoot()
        let folder = root.appendingPathComponent("CustomVoice", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        _ = try writeAudio(folder.appendingPathComponent("orphan.wav"), bytes: 3)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: folder.path)
        lockedDirectories.append(folder)
        guard (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) == nil else {
            throw XCTSkip("This account can read a folder without permissions")
        }

        let listing = IOSLeftoverAudioAnalysis.listing(ofDirectories: [folder])

        XCTAssertFalse(listing.isComplete)
        XCTAssertNil(IOSLeftoverAudioAnalysis.leftovers(
            in: listing,
            referencedAudioPaths: [],
            writtenBefore: .distantFuture
        ))
    }

    func testRemovalKeepsWhatChangedOrGainedAReferenceSinceTheConfirmation() {
        let before = sessionStart.addingTimeInterval(-60)
        let kept = entry("/outputs/CustomVoice/a.wav", size: 10, modifiedAt: before)
        let rewritten = entry("/outputs/CustomVoice/b.wav", size: 20, modifiedAt: before)
        let nowReferenced = entry("/outputs/CustomVoice/c.wav", size: 30, modifiedAt: before)
        let confirmed = IOSLeftoverAudioAnalysis.Leftovers(files: [kept, rewritten, nowReferenced])
        let current = IOSLeftoverAudioAnalysis.Leftovers(files: [
            kept,
            entry("/outputs/CustomVoice/b.wav", size: 21, modifiedAt: before),
            entry("/outputs/CustomVoice/d.wav", size: 40, modifiedAt: before),
        ])

        let plan = IOSLeftoverAudioAnalysis.removalPlan(confirmed: confirmed, current: current)

        XCTAssertEqual(plan, [kept], "Never more than was confirmed, and only what is still unused")
    }

    func testRemovalReportsOnlyFailures() {
        let plan = [
            entry("/outputs/CustomVoice/removed.wav", size: 10, modifiedAt: .distantPast),
            entry("/outputs/CustomVoice/absent.wav", size: 20, modifiedAt: .distantPast),
            entry("/outputs/CustomVoice/failed.wav", size: 30, modifiedAt: .distantPast),
        ]
        var attempted: [String] = []

        let outcome = IOSLeftoverAudioAnalysis.remove(plan) { path in
            attempted.append((path as NSString).lastPathComponent)
            switch (path as NSString).lastPathComponent {
            case "removed.wav": return .removed
            case "absent.wav": return .absent
            default: return .failed
            }
        }

        XCTAssertEqual(attempted, ["removed.wav", "absent.wav", "failed.wav"])
        XCTAssertEqual(outcome, IOSLeftoverAudioAnalysis.RemovalOutcome(
            removedCount: 1,
            removedByteCount: 10,
            failedCount: 1
        ))
    }

    private func entry(
        _ path: String,
        kind: IOSLeftoverAudioAnalysis.Kind = .regularFile,
        size: Int64,
        modifiedAt: Date
    ) -> IOSLeftoverAudioAnalysis.Entry {
        IOSLeftoverAudioAnalysis.Entry(path: path, kind: kind, byteCount: size, modifiedAt: modifiedAt)
    }

    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("IOSLeftoverAudioAnalysisTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        temporaryRoots.append(root)
        return root
    }

    private func writeAudio(_ url: URL, bytes: Int) throws -> URL {
        try Data(repeating: 0x52, count: bytes).write(to: url)
        return url
    }
}
