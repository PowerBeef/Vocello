import Foundation
@testable import QwenVoiceCore
import XCTest

final class PreparedVoiceRepositoryTests: XCTestCase {
    private enum Injected: Error { case filesystem }

    func testNativeStoreWorker() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let path = environment["VOCELLO_TEST_STORE_ROOT"], let phase = environment["VOCELLO_TEST_STORE_PHASE"] else { return }
        let shared = URL(fileURLWithPath: path)
        let source = shared.appendingPathComponent("source.wav")
        try Data([1, 2, 3]).write(to: source)
        let normal = PreparedVoiceRepository(appSupportDirectory: shared, supportedAudioExtensions: ["wav"])
        if phase != "prepare" {
            let old = try await normal.prepare(name: "Same", audioURL: source, transcript: "old", qualityWarnings: [], replacingVoiceID: nil)
            _ = try await normal.commit(id: old.id)
        }
        let worker = PreparedVoiceRepository(appSupportDirectory: shared, supportedAudioExtensions: ["wav"], fault: { point in
            let matches: Bool
            switch point {
            case .beforeCandidatePublication: matches = phase == "prepare"
            case .beforeAudioPublication: matches = phase == "replace"
            case .beforeTransactionCleanup: matches = phase == "delete"
            default: matches = false
            }
            guard matches else { return }
            try Data("locked".utf8).write(to: shared.appendingPathComponent("locked"), options: .atomic)
            let deadline = Date().addingTimeInterval(15)
            while !FileManager.default.fileExists(atPath: shared.appendingPathComponent("release").path) {
                guard Date() < deadline else { throw Injected.filesystem }
                Thread.sleep(forTimeInterval: 0.02) // Test-only bounded condition poll inside the held operation.
            }
        })
        switch phase {
        case "prepare":
            _ = try await worker.prepare(name: "New", audioURL: source, transcript: "new", qualityWarnings: [], replacingVoiceID: nil)
        case "replace":
            let candidate = try await normal.prepare(name: "Same", audioURL: source, transcript: "new", qualityWarnings: [], replacingVoiceID: "Same")
            _ = try await worker.commit(id: candidate.id)
        case "delete":
            _ = try await worker.delete(id: "Same")
        default: XCTFail("Unknown fixture phase")
        }
    }

    func testTwoNativeProcessesExcludePreparationReplacementAndDeletion() async throws {
        for phase in ["prepare", "replace", "delete"] {
            let shared = root.appendingPathComponent(phase)
            try FileManager.default.createDirectory(at: shared, withIntermediateDirectories: true)
            let child = Process()
            child.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
            child.arguments = ["xctest", "-XCTest", "VocelloCoreTests.PreparedVoiceRepositoryTests/testNativeStoreWorker", Bundle(for: Self.self).bundleURL.path]
            var environment = ProcessInfo.processInfo.environment
            environment["VOCELLO_TEST_STORE_ROOT"] = shared.path
            environment["VOCELLO_TEST_STORE_PHASE"] = phase
            child.environment = environment
            child.standardOutput = FileHandle.nullDevice
            child.standardError = FileHandle.nullDevice
            try child.run()
            defer { if child.isRunning { kill(child.processIdentifier, SIGKILL); child.waitUntilExit() } }
            let deadline = ContinuousClock.now + .seconds(15)
            while !FileManager.default.fileExists(atPath: shared.appendingPathComponent("locked").path), child.isRunning, ContinuousClock.now < deadline {
                try await Task.sleep(for: .milliseconds(20))
            }
            XCTAssertTrue(FileManager.default.fileExists(atPath: shared.appendingPathComponent("locked").path))
            let competing = PreparedVoiceRepository(appSupportDirectory: shared, supportedAudioExtensions: ["wav"])
            do { _ = try await competing.list(); XCTFail("Live operation must exclude startup reconciliation") }
            catch { XCTAssertEqual(error as? PreparedVoiceRepositoryError, .storeBusy) }
            do { try await competing.reconcile(); XCTFail("Live transaction must not be recovered") }
            catch { XCTAssertEqual(error as? PreparedVoiceRepositoryError, .storeBusy) }
            try Data().write(to: shared.appendingPathComponent("release"), options: .atomic)
            while child.isRunning, ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(20)) }
            XCTAssertFalse(child.isRunning)
            guard !child.isRunning else { continue }
            XCTAssertEqual(child.terminationStatus, 0)
            let voices = try await competing.list()
            XCTAssertEqual(voices.map(\.id), phase == "replace" ? ["Same"] : [])
            if phase == "replace" {
                XCTAssertEqual(try Data(contentsOf: voices[0].audioURL), Data([1, 2, 3]))
                XCTAssertEqual(try String(contentsOf: shared.appendingPathComponent("voices/Same.txt"), encoding: .utf8), "new")
            }
        }
    }

    func testFailedRollbackRetainsBackupAndRecoveryIsIdempotent() async throws {
        let repository = makeRepository()
        let source = try writeSource(named: "old.wav", bytes: [1, 2, 3])
        let original = try await repository.prepare(name: "Same", audioURL: source, transcript: "old",
            qualityWarnings: [], replacingVoiceID: nil)
        _ = try await repository.commit(id: original.id)
        let next = try writeSource(named: "new.wav", bytes: [4, 5, 6])
        let candidate = try await repository.prepare(name: "Same", audioURL: next, transcript: "new",
            qualityWarnings: [], replacingVoiceID: "Same")
        let failing = PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: extensions, fault: { point in
            switch point {
            case .beforeAudioPublication, .beforeRestoreAsset: throw Injected.filesystem
            default: break
            }
        })
        do {
            _ = try await failing.commit(id: candidate.id)
            XCTFail("injected failure must surface")
        } catch { XCTAssertEqual(error as? PreparedVoiceRepositoryError, .recoveryRequired) }
        let transactions = try FileManager.default.contentsOfDirectory(at: root.appendingPathComponent("voice-transactions"), includingPropertiesForKeys: nil)
        let journal = try XCTUnwrap(transactions.first)
        XCTAssertEqual(try Data(contentsOf: journal.appendingPathComponent("Same.wav")), Data([1, 2, 3]))
        try await repository.reconcile()
        try await repository.reconcile()
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("voices/Same.wav")), Data([1, 2, 3]))
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("voices/Same.txt"), encoding: .utf8), "old")
        _ = try await repository.commit(id: candidate.id)
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("voices/Same.wav")), Data([4, 5, 6]))
    }

    func testCommittedCleanupFailureNeverRollsBackNewVoice() async throws {
        let repository = makeRepository()
        let source = try writeSource(named: "old.wav", bytes: [1])
        let original = try await repository.prepare(name: "Same", audioURL: source, transcript: "old", qualityWarnings: [], replacingVoiceID: nil)
        _ = try await repository.commit(id: original.id)
        let next = try writeSource(named: "new.wav", bytes: [2])
        let candidate = try await repository.prepare(name: "Same", audioURL: next, transcript: "new", qualityWarnings: [], replacingVoiceID: "Same")
        let failing = PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: extensions, fault: { point in
            if case .beforeTransactionCleanup = point { throw Injected.filesystem }
        })
        let committed = try await failing.commit(id: candidate.id)
        XCTAssertTrue(committed.cleanupPending)
        XCTAssertEqual(try Data(contentsOf: committed.audioURL), Data([2]))
        try await repository.reconcile()
        try await repository.reconcile()
        XCTAssertEqual(try Data(contentsOf: committed.audioURL), Data([2]))
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("voices/Same.txt"), encoding: .utf8), "new")
    }

    func testRollbackCleanupFailureDoesNotDeleteRestoredSidecarsOnRetry() async throws {
        let repository = makeRepository()
        let source = try writeSource(named: "old.wav", bytes: [1])
        let original = try await repository.prepare(name: "Same", audioURL: source, transcript: "old", qualityWarnings: [], replacingVoiceID: nil)
        _ = try await repository.commit(id: original.id)
        let candidate = try await repository.prepare(name: "Same", audioURL: source, transcript: "new", qualityWarnings: [], replacingVoiceID: "Same")
        let failing = PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: extensions, fault: { point in
            switch point {
            case .beforeAudioPublication, .beforeTransactionCleanup: throw Injected.filesystem
            default: break
            }
        })
        await XCTAssertThrowsErrorAsync { _ = try await failing.commit(id: candidate.id) }
        try await repository.reconcile()
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("voices/Same.txt"), encoding: .utf8), "old")
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("voices/Same.wav")), Data([1]))
    }

    func testChangedPublishedAudioRetainsBothVersionsInsteadOfGuessingRollback() async throws {
        let repository = makeRepository()
        let source = try writeSource(named: "old.wav", bytes: [1])
        let original = try await repository.prepare(name: "Same", audioURL: source, transcript: "old", qualityWarnings: [], replacingVoiceID: nil)
        _ = try await repository.commit(id: original.id)
        let newer = try writeSource(named: "new.wav", bytes: [2])
        let candidate = try await repository.prepare(name: "Same", audioURL: newer, transcript: "new", qualityWarnings: [], replacingVoiceID: "Same")
        let failing = PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: extensions, fault: { point in
            if case .beforeCandidateCleanup = point { throw Injected.filesystem }
        })
        let committed = try await failing.commit(id: candidate.id)
        XCTAssertTrue(committed.cleanupPending)
        try Data([3]).write(to: committed.audioURL)
        for _ in 0..<2 {
            do { try await repository.reconcile(); XCTFail("Changed publication must remain unresolved") }
            catch { XCTAssertEqual(error as? PreparedVoiceRepositoryError, .recoveryRequired) }
        }
        let transaction = try XCTUnwrap(FileManager.default.contentsOfDirectory(at: root.appendingPathComponent("voice-transactions"), includingPropertiesForKeys: nil).first)
        XCTAssertEqual(try Data(contentsOf: transaction.appendingPathComponent("Same.wav")), Data([1]))
        XCTAssertEqual(try Data(contentsOf: committed.audioURL), Data([3]))
        XCTAssertTrue(FileManager.default.fileExists(atPath: transaction.appendingPathComponent("transaction.json").path))
        // Once exact published bytes are restored, forward recovery is safe.
        try Data([2]).write(to: committed.audioURL)
        try await repository.reconcile()
        XCTAssertEqual(try Data(contentsOf: committed.audioURL), Data([2]))
    }

    func testDeleteCleanupFailureRetainsWitnessAndFinishesWithoutResurrection() async throws {
        let repository = makeRepository()
        let source = try writeSource(named: "source.wav")
        let candidate = try await repository.prepare(name: "Delete", audioURL: source, transcript: "delete", qualityWarnings: [], replacingVoiceID: nil)
        _ = try await repository.commit(id: candidate.id)
        let failing = PreparedVoiceRepository(appSupportDirectory: root, supportedAudioExtensions: extensions, fault: { point in
            if case .beforeTransactionCleanup = point { throw Injected.filesystem }
        })
        try await failing.delete(id: "Delete")
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Delete.wav").path))
        try await repository.reconcile()
        try await repository.reconcile()
        let listed = try await repository.list()
        XCTAssertTrue(listed.isEmpty)
    }

    #if os(macOS)
    func testAnotherProcessLockRefusesAllOperationsWithoutReconciliation() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let partial = root.appendingPathComponent("voice-candidates/.partial-active")
        try FileManager.default.createDirectory(at: partial, withIntermediateDirectories: true)
        let process = Process()
        let output = Pipe()
        let input = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = ["-c", "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read(1)", root.appendingPathComponent(".voice-store.lock").path]
        process.standardOutput = output
        process.standardInput = input
        try process.run()
        defer { try? input.fileHandleForWriting.close(); process.waitUntilExit() }
        XCTAssertEqual(String(data: output.fileHandleForReading.availableData, encoding: .utf8), "locked\n")
        for action in 0..<6 {
            do {
                switch action {
                case 0: try await repository.reconcile()
                case 1: _ = try await repository.list()
                case 2: _ = try await repository.prepare(name: "test", audioURL: root, transcript: nil, qualityWarnings: [], replacingVoiceID: nil)
                case 3: _ = try await repository.commit(id: UUID())
                case 4: try await repository.discard(id: UUID())
                default: try await repository.delete(id: "test")
                }
                XCTFail("must reject while the other process holds the lock")
            } catch { XCTAssertEqual(error as? PreparedVoiceRepositoryError, .storeBusy) }
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: partial.path), "must not sweep another process's active staging")
    }
    #endif

    private var root: URL!
    private let extensions: Set<String> = ["wav", "mp3", "aiff", "m4a"]

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "prepared-voice-repository-tests-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let root, FileManager.default.fileExists(atPath: root.path) {
            try FileManager.default.removeItem(at: root)
        }
    }

    func testPreparedCandidateIsInvisibleUntilCommit() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.m4a")

        let candidate = try await repository.prepare(
            name: "Review Voice",
            audioURL: source,
            transcript: "  visible only after keep  ",
            qualityWarnings: ["reference_duration_short"],
            replacingVoiceID: nil
        )

        XCTAssertEqual(candidate.name, "Review Voice")
        XCTAssertTrue(candidate.hasTranscript)
        let voicesBeforeCommit = try await repository.list()
        XCTAssertEqual(voicesBeforeCommit, [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Review Voice.m4a").path))

        let committed = try await repository.commit(id: candidate.id)
        XCTAssertEqual(committed.id, "Review Voice")
        XCTAssertEqual(committed.audioURL.pathExtension, "m4a")
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("voices/Review Voice.txt"), encoding: .utf8), "visible only after keep")
        let committedIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(committedIDs, ["Review Voice"])
    }

    func testReviewedReferenceMetadataPublishesTransactionallyAndSurvivesRelaunch() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "metadata-source.wav")
        let metadata = PreparedVoiceEnrollmentMetadata(
            referenceLanguage: .french,
            transcriptSource: .manual,
            automaticTranscriptionOutcome: "lowConfidence",
            transcriptionEvidenceDigest: String(repeating: "a", count: 64)
        )
        let candidate = try await repository.prepare(
            name: "Reviewed French",
            audioURL: source,
            transcript: "Texte corrigé manuellement.",
            qualityWarnings: [],
            enrollmentMetadata: metadata,
            replacingVoiceID: nil
        )

        XCTAssertEqual(candidate.enrollmentMetadata, metadata)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent("voices/Reviewed French.voice.json").path
        ))
        _ = try await repository.commit(id: candidate.id)

        let relaunched = makeRepository()
        try await relaunched.reconcile()
        let listed = try await relaunched.list()
        let voice = try XCTUnwrap(listed.first)
        XCTAssertEqual(voice.enrollmentMetadata, metadata)
        try await relaunched.delete(id: voice.id)
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent("voices/Reviewed French.voice.json").path
        ))
    }

    func testDiscardIsIdempotentAndAllowsSameNameRetry() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let first = try await repository.prepare(
            name: "Retry Voice",
            audioURL: source,
            transcript: nil,
            qualityWarnings: ["reference_duration_excessive"],
            replacingVoiceID: nil
        )

        try await repository.discard(id: first.id)
        try await repository.discard(id: first.id)
        let voicesAfterDiscard = try await repository.list()
        XCTAssertEqual(voicesAfterDiscard, [])

        _ = try await repository.prepare(
            name: "Retry Voice",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
    }

    func testPendingAndCommittedNamesAreReserved() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let candidate = try await repository.prepare(
            name: "Unique",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )

        await XCTAssertThrowsErrorAsync {
            _ = try await repository.prepare(
                name: "Unique",
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
        }
        _ = try await repository.commit(id: candidate.id)
        await XCTAssertThrowsErrorAsync {
            _ = try await repository.prepare(
                name: "Unique",
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
        }
    }

    func testReplacementPublishesNewVoiceAndRemovesOldAssets() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let firstSource = try writeSource(named: "first.wav", bytes: [1, 2, 3])
        let first = try await repository.prepare(
            name: "Bank Base",
            audioURL: firstSource,
            transcript: "old",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: first.id)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Bank Base.clone_prompt"),
            withIntermediateDirectories: true
        )

        let replacementSource = try writeSource(named: "second.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Renamed Base",
            audioURL: replacementSource,
            transcript: "new",
            qualityWarnings: [],
            replacingVoiceID: "Bank Base"
        )
        _ = try await repository.commit(id: replacement.id)

        let replacementIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(replacementIDs, ["Renamed Base"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Bank Base.wav").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Bank Base.clone_prompt").path))
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("voices/Renamed Base.mp3")), Data([9, 8, 7]))
    }

    func testDeleteRemovesOnlySelectedVoiceAndPromptArtifacts() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        for name in ["Persona", "Persona (Happy)"] {
            let candidate = try await repository.prepare(
                name: name,
                audioURL: source,
                transcript: nil,
                qualityWarnings: [],
                replacingVoiceID: nil
            )
            _ = try await repository.commit(id: candidate.id)
        }
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Persona.clone_prompt"),
            withIntermediateDirectories: true
        )

        try await repository.delete(id: "Persona")

        let remainingIDs = (try await repository.list()).map(\.id)
        XCTAssertEqual(remainingIDs, ["Persona (Happy)"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Persona.clone_prompt").path))
    }

    func testReconcileExpiresCandidatesAndRemovesPartialAndDeleteTombstones() async throws {
        let createdAt = Date(timeIntervalSince1970: 1_700_000_000)
        let repository = PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions,
            now: { createdAt }
        )
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        _ = try await repository.prepare(
            name: "Expired",
            audioURL: source,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voice-candidates/.partial-orphan"),
            withIntermediateDirectories: true
        )
        let deleteTombstone = root.appendingPathComponent("voice-transactions/delete-orphan")
        try FileManager.default.createDirectory(
            at: deleteTombstone,
            withIntermediateDirectories: true
        )
        try JSONSerialization.data(withJSONObject: [
            "schemaVersion": 1,
            "voiceID": "Already Removed",
        ], options: [.sortedKeys]).write(
            to: deleteTombstone.appendingPathComponent("transaction.json"),
            options: [.atomic]
        )

        let relaunched = PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions,
            now: { createdAt.addingTimeInterval(PreparedVoiceRepository.candidateLifetime + 1) }
        )
        try await relaunched.reconcile()

        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("voice-candidates").path).isEmpty)
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("voice-transactions").path).isEmpty)
    }

    func testMalformedCandidateManifestIsRemovedDuringReconcile() async throws {
        let directory = root.appendingPathComponent("voice-candidates/not-a-uuid", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data(#"{"schemaVersion":1,"audioFileName":"../escape.wav"}"#.utf8)
            .write(to: directory.appendingPathComponent("manifest.json"))

        let repository = makeRepository()
        try await repository.reconcile()

        XCTAssertFalse(FileManager.default.fileExists(atPath: directory.path))
    }

    func testReconcileRollsBackInterruptedReplacementBeforeAudioPublication() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let originalSource = try writeSource(named: "original.wav", bytes: [1, 2, 3])
        let original = try await repository.prepare(
            name: "Original",
            audioURL: originalSource,
            transcript: "old transcript",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: original.id)

        let replacementSource = try writeSource(named: "replacement.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Replacement",
            audioURL: replacementSource,
            transcript: "new transcript",
            qualityWarnings: [],
            replacingVoiceID: "Original"
        )
        let candidateDirectory = root.appendingPathComponent(
            "voice-candidates/\(replacement.id.uuidString.lowercased())",
            isDirectory: true
        )
        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/commit-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.wav"),
            to: transactionDirectory.appendingPathComponent("Original.wav")
        )
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.txt"),
            to: transactionDirectory.appendingPathComponent("Original.txt")
        )
        try FileManager.default.moveItem(
            at: candidateDirectory.appendingPathComponent("transcript.txt"),
            to: root.appendingPathComponent("voices/Replacement.txt")
        )
        try writeTransactionManifest(
            candidateID: replacement.id,
            newAudioFileName: "Replacement.mp3",
            newTranscriptFileName: "Replacement.txt",
            to: transactionDirectory
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let recoveredIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(recoveredIDs, ["Original"])
        XCTAssertEqual(
            try String(contentsOf: candidateDirectory.appendingPathComponent("transcript.txt"), encoding: .utf8),
            "new transcript"
        )
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))

        _ = try await relaunched.commit(id: replacement.id)
        let replacementIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(replacementIDs, ["Replacement"])
    }

    func testReconcileCompletesInterruptedReplacementAfterAudioPublication() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let originalSource = try writeSource(named: "original.wav", bytes: [1, 2, 3])
        let original = try await repository.prepare(
            name: "Original",
            audioURL: originalSource,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: original.id)

        let replacementSource = try writeSource(named: "replacement.mp3", bytes: [9, 8, 7])
        let replacement = try await repository.prepare(
            name: "Replacement",
            audioURL: replacementSource,
            transcript: nil,
            qualityWarnings: [],
            replacingVoiceID: "Original"
        )
        let candidateDirectory = root.appendingPathComponent(
            "voice-candidates/\(replacement.id.uuidString.lowercased())",
            isDirectory: true
        )
        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/commit-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Original.wav"),
            to: transactionDirectory.appendingPathComponent("Original.wav")
        )
        try FileManager.default.moveItem(
            at: candidateDirectory.appendingPathComponent("reference.mp3"),
            to: root.appendingPathComponent("voices/Replacement.mp3")
        )
        try writeTransactionManifest(
            candidateID: replacement.id,
            newAudioFileName: "Replacement.mp3",
            newTranscriptFileName: nil,
            to: transactionDirectory
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let committedIDs = (try await relaunched.list()).map(\.id)
        XCTAssertEqual(committedIDs, ["Replacement"])
        XCTAssertFalse(FileManager.default.fileExists(atPath: candidateDirectory.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Original.wav").path))
    }

    func testReconcileCompletesJournaledDeleteFromAnyMovePoint() async throws {
        let repository = makeRepository()
        try await repository.reconcile()
        let source = try writeSource(named: "source.wav")
        let candidate = try await repository.prepare(
            name: "Delete Me",
            audioURL: source,
            transcript: "delete transcript",
            qualityWarnings: [],
            replacingVoiceID: nil
        )
        _ = try await repository.commit(id: candidate.id)
        try FileManager.default.createDirectory(
            at: root.appendingPathComponent("voices/Delete Me.clone_prompt"),
            withIntermediateDirectories: true
        )

        let transactionDirectory = root.appendingPathComponent(
            "voice-transactions/delete-interrupted",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: transactionDirectory, withIntermediateDirectories: true)
        try JSONSerialization.data(withJSONObject: [
            "schemaVersion": 1,
            "voiceID": "Delete Me",
        ], options: [.sortedKeys]).write(
            to: transactionDirectory.appendingPathComponent("transaction.json"),
            options: [.atomic]
        )
        // Simulate a stop after only the transcript crossed into the tombstone.
        try FileManager.default.moveItem(
            at: root.appendingPathComponent("voices/Delete Me.txt"),
            to: transactionDirectory.appendingPathComponent("Delete Me.txt")
        )

        let relaunched = makeRepository()
        try await relaunched.reconcile()

        let remaining = try await relaunched.list()
        XCTAssertEqual(remaining, [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Delete Me.wav").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices/Delete Me.clone_prompt").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: transactionDirectory.path))
    }

    private func makeRepository() -> PreparedVoiceRepository {
        PreparedVoiceRepository(
            appSupportDirectory: root,
            supportedAudioExtensions: extensions
        )
    }

    private func writeSource(
        named name: String,
        bytes: [UInt8] = [0, 1, 2, 3]
    ) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data(bytes).write(to: url)
        return url
    }

    private func writeTransactionManifest(
        candidateID: UUID,
        newAudioFileName: String,
        newTranscriptFileName: String?,
        to directory: URL
    ) throws {
        let manifest: [String: Any] = [
            "schemaVersion": 1,
            "candidateID": candidateID.uuidString,
            "newVoiceName": "Replacement",
            "newAudioFileName": newAudioFileName,
            "newTranscriptFileName": newTranscriptFileName.map { $0 as Any } ?? NSNull(),
        ]
        try JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys])
            .write(to: directory.appendingPathComponent("transaction.json"), options: [.atomic])
    }
}

private func XCTAssertThrowsErrorAsync(
    _ expression: () async throws -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected an error", file: file, line: line)
    } catch {
        // Expected.
    }
}
