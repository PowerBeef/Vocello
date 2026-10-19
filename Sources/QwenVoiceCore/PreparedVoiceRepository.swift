import Foundation
import Darwin

enum PreparedVoiceRepositoryError: LocalizedError, Equatable {
    case invalidName
    case invalidIdentifier
    case sourceMissing
    case duplicateName(String)
    case candidateMissing
    case voiceMissing(String)
    case malformedCandidate
    case recoveryRequired
    case storeBusy

    var errorDescription: String? {
        switch self {
        case .invalidName:
            return "Invalid saved voice name."
        case .invalidIdentifier:
            return "Invalid saved voice identifier."
        case .sourceMissing:
            return "Reference audio file not found."
        case .duplicateName(let name):
            return "A saved voice named \"\(name)\" already exists. Choose a different name."
        case .candidateMissing:
            return "The saved-voice review expired. Save the reference again."
        case .voiceMissing(let id):
            return "Voice '\(id)' does not exist."
        case .malformedCandidate:
            return "The saved-voice review data is invalid. Save the reference again."
        case .recoveryRequired:
            return "Saved Voice recovery could not finish. Your recovery files have been retained. Retry before changing saved voices."
        case .storeBusy:
            return "Another Vocello process is updating Saved Voices. Try again when it finishes."
        }
    }
}

struct PreparedVoiceStorageRecord: Sendable, Equatable {
    let id: String
    let name: String
    let audioURL: URL
    let hasTranscript: Bool
    let enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
    /// The voice's sidecar exists but could not be read (damaged, or newer than
    /// this build), so it cannot say whether the voice was generated.
    var enrollmentMetadataUnreadable = false
    /// Read only for an unreadable sidecar: the generation mode the voice's
    /// audio embeds as Vocello provenance, nil for a recording or import.
    var audioProvenanceMode: String?
    var cleanupPending = false
}

/// Path-free outcome of one reconciliation pass: counts only, never a journal
/// name, voice name or filesystem path.
struct PreparedVoiceReconciliationSummary: Sendable, Equatable {
    /// Uninterpretable journals moved to `voice-transactions-quarantine/`.
    var quarantinedJournals = 0
    /// Journals from a newer schema, left in place for the build that wrote them.
    var skippedNewerJournals = 0

    var diagnosticCode: String {
        "saved_voices.reconcile.quarantined_\(quarantinedJournals).skipped_newer_\(skippedNewerJournals)"
    }
}

/// Serializes every mutation of the saved-voice store.
///
/// Permanent voices retain the historical flat `voices/` representation.
/// Review candidates live in a private sibling tree and are published only by
/// `commit`. Audio is moved last, because its presence is the visibility
/// boundary used by `list`.
actor PreparedVoiceRepository {
    static let candidateSchemaVersion = 2
    static let supportedCandidateSchemaVersions: Set<Int> = [1, 2]
    static let candidateLifetime: TimeInterval = 24 * 60 * 60
    /// The process whose interactive review holds a candidate (F-01): a session
    /// every repository of that process shares, so an engine that restarts
    /// keeps its reviews, and the identifier and start time that tell whether
    /// the process has ended.
    struct ReviewOwner: Codable, Equatable, Sendable {
        let session: UUID
        let processIdentifier: Int32
        /// Microseconds since 1970; zero when the kernel did not report it.
        let startTime: UInt64
    }

    static let processReviewOwner: ReviewOwner = {
        let processIdentifier = getpid()
        return ReviewOwner(
            session: UUID(),
            processIdentifier: processIdentifier,
            startTime: startTime(ofProcess: processIdentifier) ?? 0
        )
    }()
    private static let transactionSchemaVersion = 2
    private static let transactionManifestFileName = "transaction.json"

    private struct CandidateManifest: Codable, Sendable {
        let schemaVersion: Int
        let id: UUID
        let name: String
        let audioFileName: String
        let transcriptFileName: String?
        let qualityWarnings: [String]
        let enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
        let replacingVoiceID: String?
        let createdAt: Date
        /// The process whose interactive review holds this candidate (F-01);
        /// nil for a one-shot enrollment such as the CLI's, and for earlier
        /// builds, which never wrote it.
        var reviewOwner: ReviewOwner? = nil
    }

    private enum CommitPhase: String, Codable { case prepared, backedUp, rolledBack }
    private struct CommitTransactionManifest: Codable, Sendable {
        let schemaVersion: Int
        let candidateID: UUID
        let newVoiceName: String
        let newAudioFileName: String
        let newTranscriptFileName: String?
        let newMetadataFileName: String?
        var phase: CommitPhase? = nil
        var audioDigest: String? = nil
    }

    private struct DeleteTransactionManifest: Codable, Sendable {
        let schemaVersion: Int
        let voiceID: String
    }

    private let voicesDirectory: URL
    private let candidatesDirectory: URL
    private let transactionsDirectory: URL
    private let quarantineDirectory: URL
    private let normalizedCloneReferenceDirectory: URL
    private let supportedAudioExtensions: Set<String>
    private let fileManager: FileManager
    private let now: @Sendable () -> Date
    private let reviewOwner: ReviewOwner
    /// Candidates of closed review surfaces whose discard could not finish yet,
    /// usually because another process held the store. The next operation that
    /// holds it removes them with the expired ones, so such a candidate does
    /// not keep its name until it expires (F-01).
    private var releasedCandidateIDs: Set<UUID> = []
    enum FaultPoint: Sendable { case beforeCandidatePublication, beforeAudioPublication, beforeRestoreAsset, beforeCandidateCleanup, beforeTransactionCleanup, beforeClonePromptPublication }
    private let fault: @Sendable (FaultPoint) throws -> Void

    init(
        appSupportDirectory: URL,
        supportedAudioExtensions: Set<String>,
        fileManager: FileManager = .default,
        now: @escaping @Sendable () -> Date = Date.init,
        reviewOwner: ReviewOwner = PreparedVoiceRepository.processReviewOwner,
        fault: @escaping @Sendable (FaultPoint) throws -> Void = { _ in }
    ) {
        voicesDirectory = appSupportDirectory.appendingPathComponent("voices", isDirectory: true)
        candidatesDirectory = appSupportDirectory.appendingPathComponent("voice-candidates", isDirectory: true)
        transactionsDirectory = appSupportDirectory.appendingPathComponent("voice-transactions", isDirectory: true)
        quarantineDirectory = appSupportDirectory.appendingPathComponent("voice-transactions-quarantine", isDirectory: true)
        normalizedCloneReferenceDirectory = MLXTTSEngine.normalizedCloneReferenceDirectory(in: appSupportDirectory)
        self.supportedAudioExtensions = supportedAudioExtensions
        self.fileManager = fileManager
        self.now = now
        self.reviewOwner = reviewOwner
        self.fault = fault
    }

    @discardableResult
    func reconcile() throws -> PreparedVoiceReconciliationSummary {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        return try reconcileLocked()
    }

    @discardableResult
    private func reconcileLocked() throws -> PreparedVoiceReconciliationSummary {
        var summary = PreparedVoiceReconciliationSummary()
        try createRoots()
        // Transactions can still own expired/partially-cleaned candidates.
        // Recover them before applying ordinary candidate retention.
        for url in try reconcilableEntries(at: transactionsDirectory) {
            if try directoryContents(at: url).isEmpty {
                try fileManager.removeItem(at: url)
                continue
            }
            do {
                if url.lastPathComponent.hasPrefix("delete-") {
                    try reconcileDeleteTransaction(at: url)
                } else if url.lastPathComponent.hasPrefix("commit-") {
                    try reconcileCommitTransaction(at: url)
                } else {
                    // An unknown kind from a newer build is left alone like
                    // any other newer journal; otherwise it is uninterpretable.
                    _ = try decodeTransactionManifest(TransactionSchemaProbe.self, in: url)
                    throw UninterpretableTransaction()
                }
            } catch is NewerTransaction {
                // The app and the CLI share this store, and an older build can
                // run after a newer one. Only the build that wrote a newer
                // journal may interpret it.
                summary.skippedNewerJournals += 1
            } catch is UninterpretableTransaction {
                // Unknown or malformed journals are not safe to interpret.
                // Keep them, and every asset they hold, for diagnosis instead
                // of guessing whether to restore or delete, and without
                // blocking every later reconciliation of the store.
                try quarantineTransaction(at: url)
                summary.quarantinedJournals += 1
            }
        }
        for url in try reconcilableEntries(at: candidatesDirectory, admittingHiddenPrefix: ".partial-") {
            if url.lastPathComponent.hasPrefix(".partial-") {
                try fileManager.removeItem(at: url)
                continue
            }
            guard let manifest = try? loadManifest(from: url) else {
                try fileManager.removeItem(at: url)
                continue
            }
            if releasedCandidateIDs.contains(manifest.id)
                || now().timeIntervalSince(manifest.createdAt) >= Self.candidateLifetime {
                try fileManager.removeItem(at: url)
            }
        }
        // Every released candidate still present is gone now.
        releasedCandidateIDs.removeAll()
        return summary
    }

    func list() throws -> [PreparedVoiceStorageRecord] {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        try reconcileLocked()
        return try directoryContents(at: voicesDirectory)
            .filter { supportedAudioExtensions.contains($0.pathExtension.lowercased()) }
            .map { audioURL in
                let id = audioURL.deletingPathExtension().lastPathComponent
                let sidecar = loadEnrollmentMetadata(for: id)
                return PreparedVoiceStorageRecord(
                    id: id,
                    name: id,
                    audioURL: audioURL,
                    hasTranscript: fileManager.fileExists(
                        atPath: voicesDirectory.appendingPathComponent("\(id).txt").path
                    ),
                    enrollmentMetadata: sidecar.metadata,
                    enrollmentMetadataUnreadable: sidecar.unreadable,
                    audioProvenanceMode: sidecar.unreadable
                        ? WAVProvenanceChunk.generationMode(fromWAVAt: audioURL) : nil
                )
            }
            .sorted {
                $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
            }
    }

    func prepare(
        name rawName: String,
        audioURL sourceURL: URL,
        transcript: String?,
        qualityWarnings: [String],
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata? = nil,
        replacingVoiceID: String?,
        heldForReview: Bool = false
    ) throws -> PreparedVoiceCandidate {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        let summary = try reconcileLocked()
        if heldForReview, summary.skippedNewerJournals == 0 {
            try discardEndedReviewsCandidatesLocked()
        }
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw PreparedVoiceRepositoryError.sourceMissing
        }

        let name = NativeSavedVoiceNaming.normalizedName(rawName)
        guard !name.isEmpty else {
            throw PreparedVoiceRepositoryError.invalidName
        }
        if let replacingVoiceID {
            try validateIdentifier(replacingVoiceID)
        }
        try requireNameAvailable(name, replacingVoiceID: replacingVoiceID, excludingCandidateID: nil)

        let sourceExtension = sourceURL.pathExtension.lowercased()
        let destinationExtension = supportedAudioExtensions.contains(sourceExtension) ? sourceExtension : "wav"
        let normalizedTranscript = NativePreparedCloneConditioningCache.normalizedTranscript(transcript)
        let candidateID = UUID()
        let directoryName = candidateID.uuidString.lowercased()
        let partialDirectory = candidatesDirectory.appendingPathComponent(".partial-\(directoryName)", isDirectory: true)
        let candidateDirectory = candidatesDirectory.appendingPathComponent(directoryName, isDirectory: true)
        let audioFileName = "reference.\(destinationExtension)"
        let transcriptFileName = normalizedTranscript == nil ? nil : "transcript.txt"

        do {
            try fileManager.createDirectory(at: partialDirectory, withIntermediateDirectories: false)
            try fileManager.copyItem(
                at: sourceURL,
                to: partialDirectory.appendingPathComponent(audioFileName)
            )
            if let normalizedTranscript, let transcriptFileName {
                try normalizedTranscript.write(
                    to: partialDirectory.appendingPathComponent(transcriptFileName),
                    atomically: true,
                    encoding: .utf8
                )
            }
            let manifest = CandidateManifest(
                schemaVersion: Self.candidateSchemaVersion,
                id: candidateID,
                name: name,
                audioFileName: audioFileName,
                transcriptFileName: transcriptFileName,
                qualityWarnings: qualityWarnings,
                enrollmentMetadata: enrollmentMetadata,
                replacingVoiceID: replacingVoiceID,
                createdAt: now(),
                reviewOwner: heldForReview ? reviewOwner : nil
            )
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            try encoder.encode(manifest).write(
                to: partialDirectory.appendingPathComponent("manifest.json"),
                options: [.atomic]
            )
            try fault(.beforeCandidatePublication)
            try fileManager.moveItem(at: partialDirectory, to: candidateDirectory)
        } catch {
            if fileManager.fileExists(atPath: partialDirectory.path) {
                try? fileManager.removeItem(at: partialDirectory)
            }
            throw error
        }

        return PreparedVoiceCandidate(
            id: candidateID,
            name: name,
            hasTranscript: normalizedTranscript != nil,
            qualityWarnings: qualityWarnings,
            enrollmentMetadata: enrollmentMetadata
        )
    }

    func commit(id: UUID) throws -> PreparedVoiceStorageRecord {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        try reconcileLocked()
        let candidateDirectory = candidateDirectory(for: id)
        guard fileManager.fileExists(atPath: candidateDirectory.path) else {
            throw PreparedVoiceRepositoryError.candidateMissing
        }
        let manifest = try loadManifest(from: candidateDirectory)
        guard manifest.id == id else {
            throw PreparedVoiceRepositoryError.malformedCandidate
        }
        try requireNameAvailable(
            manifest.name,
            replacingVoiceID: manifest.replacingVoiceID,
            excludingCandidateID: id
        )

        let stagedAudioURL = candidateDirectory.appendingPathComponent(manifest.audioFileName)
        guard fileManager.fileExists(atPath: stagedAudioURL.path),
              supportedAudioExtensions.contains(stagedAudioURL.pathExtension.lowercased()) else {
            throw PreparedVoiceRepositoryError.malformedCandidate
        }

        let destinationAudioURL = voicesDirectory.appendingPathComponent(
            "\(manifest.name).\(stagedAudioURL.pathExtension.lowercased())"
        )
        let destinationTranscriptURL = voicesDirectory.appendingPathComponent("\(manifest.name).txt")
        let destinationMetadataURL = voicesDirectory.appendingPathComponent("\(manifest.name).voice.json")
        let transactionDirectory = transactionsDirectory.appendingPathComponent(
            "commit-\(UUID().uuidString.lowercased())",
            isDirectory: true
        )
        var transaction = CommitTransactionManifest(
            schemaVersion: Self.transactionSchemaVersion,
            candidateID: id,
            newVoiceName: manifest.name,
            newAudioFileName: destinationAudioURL.lastPathComponent,
            newTranscriptFileName: manifest.transcriptFileName == nil ? nil : destinationTranscriptURL.lastPathComponent,
            newMetadataFileName: manifest.enrollmentMetadata == nil ? nil : destinationMetadataURL.lastPathComponent,
            phase: .prepared,
            audioDigest: try SamplingTakeEvidence.sha256FileDigest(at: stagedAudioURL)
        )
        do {
            try fileManager.createDirectory(at: transactionDirectory, withIntermediateDirectories: false)
            try writeTransactionManifest(transaction, to: transactionDirectory)
        } catch {
            if fileManager.fileExists(atPath: transactionDirectory.path) {
                try? fileManager.removeItem(at: transactionDirectory)
            }
            throw error
        }

        do {
            if let replacingVoiceID = manifest.replacingVoiceID {
                try moveVoiceAssets(id: replacingVoiceID, into: transactionDirectory)
            }
            transaction.phase = .backedUp
            try writeTransactionManifest(transaction, to: transactionDirectory)

            if let transcriptFileName = manifest.transcriptFileName {
                let stagedTranscriptURL = candidateDirectory.appendingPathComponent(transcriptFileName)
                guard fileManager.fileExists(atPath: stagedTranscriptURL.path) else {
                    throw PreparedVoiceRepositoryError.malformedCandidate
                }
                if fileManager.fileExists(atPath: destinationTranscriptURL.path) {
                    try fileManager.removeItem(at: destinationTranscriptURL)
                }
                try fileManager.copyItem(at: stagedTranscriptURL, to: destinationTranscriptURL)
            }

            if let enrollmentMetadata = manifest.enrollmentMetadata {
                try JSONEncoder().encode(enrollmentMetadata).write(
                    to: destinationMetadataURL,
                    options: [.atomic]
                )
            }

            // Publication boundary: listing discovers the voice only after
            // this final move succeeds.
            try fault(.beforeAudioPublication)
            try fileManager.moveItem(at: stagedAudioURL, to: destinationAudioURL)
        } catch {
            do {
                try reconcileCommitTransaction(at: transactionDirectory)
            } catch {
                // Never discard the only recoverable backup after a second
                // filesystem error. Retry observes the same durable witness.
                throw PreparedVoiceRepositoryError.recoveryRequired
            }
            throw error
        }
        // Publication succeeded. Cleanup is forward-only, never rollback.
        var cleanupPending = false
        do {
            try finishCommittedCandidate(candidateDirectory, transactionDirectory: transactionDirectory)
        } catch { cleanupPending = true }
        return PreparedVoiceStorageRecord(
            id: manifest.name,
            name: manifest.name,
            audioURL: destinationAudioURL,
            hasTranscript: manifest.transcriptFileName != nil,
            enrollmentMetadata: manifest.enrollmentMetadata,
            cleanupPending: cleanupPending
        )
    }

    /// `abandoned`: the surface that held the candidate has closed, so nothing
    /// is left to show a failure to. Such a discard is remembered before the
    /// store is taken, and one that cannot take it now is finished by the next
    /// operation that can (F-01). An explicit Discard that fails leaves its
    /// candidate under review, so Keep still publishes it.
    func discard(id: UUID, abandoned: Bool = false) throws {
        if abandoned { releasedCandidateIDs.insert(id) }
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        try reconcileLocked()
        let directory = candidateDirectory(for: id)
        guard fileManager.fileExists(atPath: directory.path) else { return }
        try fileManager.removeItem(at: directory)
    }

    func delete(id: String) throws {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        try reconcileLocked()
        try validateIdentifier(id)
        let audioURLs = supportedAudioExtensions
            .map { voicesDirectory.appendingPathComponent("\(id).\($0)") }
            .filter { fileManager.fileExists(atPath: $0.path) }
        guard !audioURLs.isEmpty else {
            throw PreparedVoiceRepositoryError.voiceMissing(id)
        }

        let transactionDirectory = transactionsDirectory.appendingPathComponent(
            "delete-\(UUID().uuidString.lowercased())",
            isDirectory: true
        )
        do {
            try fileManager.createDirectory(at: transactionDirectory, withIntermediateDirectories: false)
            try JSONEncoder().encode(
                DeleteTransactionManifest(
                    schemaVersion: Self.transactionSchemaVersion,
                    voiceID: id
                )
            ).write(
                to: transactionDirectory.appendingPathComponent(Self.transactionManifestFileName),
                options: [.atomic]
            )
            try moveVoiceAssets(id: id, into: transactionDirectory)
        } catch {
            // A durable delete journal means user-confirmed forward recovery.
            // Do not restore a partially removed tombstone, then destroy it.
            throw PreparedVoiceRepositoryError.recoveryRequired
        }
        // All assets are tombstoned: a cleanup failure cannot resurrect them.
        removeDerivedCloneReferences(ofVoiceAudioIn: transactionDirectory)
        try? removeTransaction(transactionDirectory)
    }

    /// Publishes a completely staged prompt only while its source still belongs
    /// to this voice. The same cross-process lock covers delete/replacement and
    /// the final move; no lock survives an actor suspension or model work.
    @discardableResult
    func publishClonePromptArtifact(
        from staging: URL,
        to destination: URL,
        voiceID: String,
        sourceURL: URL,
        sourceFingerprint: String,
        checksStoredTranscript: Bool,
        expectedStoredTranscript: String?
    ) throws -> Bool {
        let lock = try acquireStoreLock()
        defer { releaseStoreLock(lock) }
        try reconcileLocked()
        try validateIdentifier(voiceID)
        let promptRoot = voicesDirectory.appendingPathComponent("\(voiceID).clone_prompt", isDirectory: true)
        guard sourceURL.standardizedFileURL.deletingLastPathComponent() == voicesDirectory.standardizedFileURL,
              sourceURL.deletingPathExtension().lastPathComponent == voiceID,
              supportedAudioExtensions.contains(sourceURL.pathExtension.lowercased()),
              staging.standardizedFileURL.deletingLastPathComponent() == voicesDirectory.standardizedFileURL,
              staging.lastPathComponent.hasPrefix(".clone-prompt-staging-"),
              destination.standardizedFileURL.deletingLastPathComponent().deletingLastPathComponent()
                == promptRoot.standardizedFileURL else {
            throw PreparedVoiceRepositoryError.invalidIdentifier
        }
        try fault(.beforeClonePromptPublication)
        guard fileManager.fileExists(atPath: sourceURL.path),
              try sourceURL.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true,
              try NativePreparedCloneConditioningCache.stableCloneReferenceFingerprint(for: sourceURL)
                == sourceFingerprint else { return false }
        if checksStoredTranscript {
            let transcriptURL = voicesDirectory.appendingPathComponent("\(voiceID).txt")
            let stored = fileManager.fileExists(atPath: transcriptURL.path)
                ? try String(contentsOf: transcriptURL, encoding: .utf8) : nil
            guard NativePreparedCloneConditioningCache.normalizedTranscript(stored)
                == expectedStoredTranscript else { return false }
        }
        try fileManager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: destination.path) {
            _ = try fileManager.replaceItemAt(destination, withItemAt: staging)
        } else {
            try fileManager.moveItem(at: staging, to: destination)
        }
        return true
    }

    /// Cross-process exclusion, not just actor isolation. Never block a Swift
    /// executor waiting for another app/CLI process and never unlink this inode.
    private func acquireStoreLock() throws -> Int32 {
        let root = voicesDirectory.deletingLastPathComponent()
        try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
        let fd = unsafe Darwin.open(root.appendingPathComponent(".voice-store.lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw PreparedVoiceRepositoryError.recoveryRequired }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            let failure = errno
            Darwin.close(fd)
            throw failure == EWOULDBLOCK || failure == EAGAIN
                ? PreparedVoiceRepositoryError.storeBusy : PreparedVoiceRepositoryError.recoveryRequired
        }
        return fd
    }

    private func releaseStoreLock(_ fd: Int32) {
        flock(fd, LOCK_UN)
        Darwin.close(fd)
    }

    /// A journal this build cannot interpret: an unknown prefix, a missing or
    /// undecodable manifest, or values that fail validation. Thrown only before
    /// the journal's assets are touched, so moving it aside is always safe.
    private struct UninterpretableTransaction: Error {}

    /// A journal whose manifest declares a schema newer than this build's.
    private struct NewerTransaction: Error {}

    private struct TransactionSchemaProbe: Decodable {
        let schemaVersion: Int
    }

    /// Moves an uninterpretable journal to `voice-transactions-quarantine/`.
    /// Never deletes: the journal may hold the only copy of a replaced voice.
    private func quarantineTransaction(at transactionDirectory: URL) throws {
        if !fileManager.fileExists(atPath: quarantineDirectory.path) {
            try fileManager.createDirectory(at: quarantineDirectory, withIntermediateDirectories: true)
            applyQuarantineStoragePolicy(to: quarantineDirectory)
        }
        let name = transactionDirectory.lastPathComponent
        var destination = quarantineDirectory.appendingPathComponent(name, isDirectory: true)
        if fileManager.fileExists(atPath: destination.path) {
            destination = quarantineDirectory.appendingPathComponent(
                "\(name)-\(UUID().uuidString.lowercased())",
                isDirectory: true
            )
        }
        try fileManager.moveItem(at: transactionDirectory, to: destination)
        applyQuarantineStoragePolicy(to: destination)
        if let descendants = fileManager.enumerator(at: destination, includingPropertiesForKeys: nil) {
            for case let url as URL in descendants {
                applyQuarantineStoragePolicy(to: url)
            }
        }
    }

    /// Mirrors the iOS storage-protection entry `voice-transactions-quarantine`
    /// (`IOSStorageProtectionPolicy`, `config/ios-storage-protection-policy.json`):
    /// backup-eligible, because a quarantined journal may hold the only copy of
    /// a replaced voice, and a move out of backup-excluded `voice-transactions/`
    /// would otherwise keep its exclusion until the next launch's bootstrap.
    /// Best effort: bootstrap reapplies the policy recursively on every launch.
    private func applyQuarantineStoragePolicy(to url: URL) {
        #if os(iOS)
        try? fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
        #endif
        var values = URLResourceValues()
        values.isExcludedFromBackup = false
        var mutableURL = url
        try? mutableURL.setResourceValues(values)
    }

    /// Store roots can collect Finder metadata (`.DS_Store`), sync droppings or
    /// stray files. Reconciliation interprets only visible real directories
    /// (never symbolic links) and leaves everything else where it is.
    private func reconcilableEntries(at root: URL, admittingHiddenPrefix: String? = nil) throws -> [URL] {
        try fileManager.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: []
        ).filter { url in
            let name = url.lastPathComponent
            if name.hasPrefix("."), !(admittingHiddenPrefix.map { name.hasPrefix($0) } ?? false) {
                return false
            }
            guard let values = try? url.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey]) else {
                return false
            }
            return values.isDirectory == true && values.isSymbolicLink != true
        }
    }

    private func removeTransaction(_ directory: URL) throws {
        try fault(.beforeTransactionCleanup)
        // Preserve the witness until every backed-up asset has been removed.
        for url in try directoryContents(at: directory) where url.lastPathComponent != Self.transactionManifestFileName {
            try fileManager.removeItem(at: url)
        }
        let manifest = directory.appendingPathComponent(Self.transactionManifestFileName)
        if fileManager.fileExists(atPath: manifest.path) { try fileManager.removeItem(at: manifest) }
        try fileManager.removeItem(at: directory)
    }

    private func finishCommittedCandidate(_ candidate: URL, transactionDirectory: URL) throws {
        try fault(.beforeCandidateCleanup)
        if fileManager.fileExists(atPath: candidate.path) { try fileManager.removeItem(at: candidate) }
        // A replaced voice's audio sits in the backup until the cleanup below.
        removeDerivedCloneReferences(ofVoiceAudioIn: transactionDirectory)
        try removeTransaction(transactionDirectory)
    }

    /// A8-01: cloning a voice whose audio is not canonical WAV leaves a 24 kHz
    /// copy and a mirrored transcript in `cache/normalized_clone_refs/`, named
    /// from the voice file as `<stem>_<SHA-256>.wav` and `.txt`. Once a delete
    /// or a replacement has tombstoned a voice's audio, those go with it, so no
    /// copy of a removed voice stays behind. Best effort and fail closed: only
    /// those exact regular files are removed, and they stay whenever a live
    /// voice derives the same name (two voice names can share a sanitized stem
    /// and the same audio) or a live voice's audio cannot be read.
    private func removeDerivedCloneReferences(ofVoiceAudioIn tombstone: URL) {
        let extensions = supportedAudioExtensions
        let isAudio = { (url: URL) in extensions.contains(url.pathExtension.lowercased()) }
        guard let tombstonedAudio = try? directoryContents(at: tombstone).filter(isAudio),
              !tombstonedAudio.isEmpty,
              let liveAudio = try? directoryContents(at: voicesDirectory).filter(isAudio) else {
            return
        }
        for audioURL in tombstonedAudio {
            guard let fingerprint = try? NativePreparedCloneConditioningCache
                .stableCloneReferenceFingerprint(for: audioURL) else { continue }
            let name = NativePreparedCloneConditioningCache.stableNormalizedCloneReferenceFileName(
                for: audioURL,
                referenceFingerprint: fingerprint
            )
            let stillDerived = liveAudio.contains { liveURL in
                guard NativePreparedCloneConditioningCache.stableNormalizedCloneReferenceFileName(
                    for: liveURL,
                    referenceFingerprint: fingerprint
                ) == name else { return false }
                let liveFingerprint = try? NativePreparedCloneConditioningCache
                    .stableCloneReferenceFingerprint(for: liveURL)
                return liveFingerprint == nil || liveFingerprint == fingerprint
            }
            guard !stillDerived else { continue }
            let normalizedURL = normalizedCloneReferenceDirectory.appendingPathComponent(name)
            for url in [normalizedURL, normalizedURL.deletingPathExtension().appendingPathExtension("txt")] {
                // Never a directory, or a link left in a file's place
                // (the attributes describe the link, not its target).
                let type = (try? fileManager.attributesOfItem(atPath: url.path))?[.type] as? FileAttributeType
                guard type == .typeRegular else { continue }
                try? fileManager.removeItem(at: url)
            }
        }
    }

    /// F-01: a review candidate lives only as long as the process whose review
    /// holds it. Once that process has ended (the app was quit, or the system
    /// ended it, mid-review), its candidate would keep its name until it
    /// expires, so an interactive review save removes it. Another copy of the
    /// app still running keeps its reviews (the Mac runs several copies on one
    /// store), as does every one-shot candidate: the CLI stages and commits in
    /// one call and never sweeps. A journal a newer build left may own a
    /// candidate, so the caller skips the sweep while one remains.
    private func discardEndedReviewsCandidatesLocked() throws {
        var ended: [UUID: Bool] = [:]
        for url in try reconcilableEntries(at: candidatesDirectory) {
            guard let manifest = try? loadManifest(from: url),
                  let owner = manifest.reviewOwner,
                  owner.session != reviewOwner.session else { continue }
            let hasEnded = ended[owner.session] ?? Self.reviewOwnerHasEnded(owner, current: reviewOwner)
            ended[owner.session] = hasEnded
            if hasEnded { try fileManager.removeItem(at: url) }
        }
    }

    /// Whether the process behind another review session has ended: this
    /// process now holds its identifier, no process does, or a later one
    /// reuses it (a different start time). A process this one may not signal
    /// is no copy of this app on its store: on the iPhone any other app, on the
    /// Mac another user's process. When nothing can be told, the review stays.
    static func reviewOwnerHasEnded(_ owner: ReviewOwner, current: ReviewOwner) -> Bool {
        guard owner.processIdentifier > 0 else { return false }
        if owner.processIdentifier == current.processIdentifier { return true }
        guard kill(owner.processIdentifier, 0) == 0 else { return errno == ESRCH || errno == EPERM }
        guard owner.startTime != 0, let running = startTime(ofProcess: owner.processIdentifier) else { return false }
        return running != owner.startTime
    }

    /// `sysctl(KERN_PROC_PID)`, as MAC-25's recording owner reads it: the start
    /// time of the process holding `processIdentifier` in microseconds since
    /// 1970, or nil when none does or the kernel cannot say.
    private static func startTime(ofProcess processIdentifier: Int32) -> UInt64? {
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, processIdentifier]
        var info = unsafe kinfo_proc()
        var size = unsafe MemoryLayout<kinfo_proc>.stride
        let status = mib.withMutableBufferPointer { mib in
            unsafe sysctl(mib.baseAddress, u_int(mib.count), &info, &size, nil, 0)
        }
        guard status == 0, unsafe size >= MemoryLayout<kinfo_proc>.stride,
              unsafe info.kp_proc.p_pid == processIdentifier else { return nil }
        let started = unsafe info.kp_proc.p_un.__p_starttime
        let microseconds = UInt64(clamping: started.tv_sec) * 1_000_000 + UInt64(clamping: started.tv_usec)
        return microseconds == 0 ? nil : microseconds
    }

    private func createRoots() throws {
        try fileManager.createDirectory(at: voicesDirectory, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: candidatesDirectory, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: transactionsDirectory, withIntermediateDirectories: true)
    }

    private func requireNameAvailable(
        _ name: String,
        replacingVoiceID: String?,
        excludingCandidateID: UUID?
    ) throws {
        let committedConflict = supportedAudioExtensions.contains { ext in
            fileManager.fileExists(atPath: voicesDirectory.appendingPathComponent("\(name).\(ext)").path)
        } || fileManager.fileExists(atPath: voicesDirectory.appendingPathComponent("\(name).txt").path)
            || fileManager.fileExists(atPath: voicesDirectory.appendingPathComponent("\(name).voice.json").path)
        if committedConflict && replacingVoiceID != name {
            throw PreparedVoiceRepositoryError.duplicateName(name)
        }

        for directory in try directoryContents(at: candidatesDirectory)
            where !directory.lastPathComponent.hasPrefix(".partial-") {
            guard let manifest = try? loadManifest(from: directory) else { continue }
            if manifest.id != excludingCandidateID,
               manifest.name.caseInsensitiveCompare(name) == .orderedSame {
                throw PreparedVoiceRepositoryError.duplicateName(name)
            }
        }
    }

    private func moveVoiceAssets(id: String, into transactionDirectory: URL) throws {
        try validateIdentifier(id)
        let urls = supportedAudioExtensions.map { voicesDirectory.appendingPathComponent("\(id).\($0)") }
            + [
                voicesDirectory.appendingPathComponent("\(id).txt"),
                voicesDirectory.appendingPathComponent("\(id).voice.json"),
                voicesDirectory.appendingPathComponent("\(id).clone_prompt", isDirectory: true),
            ]
        for sourceURL in urls where fileManager.fileExists(atPath: sourceURL.path) {
            try fileManager.moveItem(
                at: sourceURL,
                to: transactionDirectory.appendingPathComponent(sourceURL.lastPathComponent)
            )
        }
    }

    private func restoreVoiceAssets(from transactionDirectory: URL) throws {
        guard fileManager.fileExists(atPath: transactionDirectory.path) else { return }
        for sourceURL in try directoryContents(at: transactionDirectory)
            where sourceURL.lastPathComponent != Self.transactionManifestFileName {
            try fault(.beforeRestoreAsset)
            let destinationURL = voicesDirectory.appendingPathComponent(sourceURL.lastPathComponent)
            if fileManager.fileExists(atPath: destinationURL.path) {
                try fileManager.removeItem(at: destinationURL)
            }
            // Keep backups through the entire restore. A second failure must
            // leave retryable evidence even for assets already restored.
            try fileManager.copyItem(at: sourceURL, to: destinationURL)
        }
    }

    private func writeTransactionManifest(
        _ manifest: CommitTransactionManifest,
        to transactionDirectory: URL
    ) throws {
        try JSONEncoder().encode(manifest).write(
            to: transactionDirectory.appendingPathComponent(Self.transactionManifestFileName),
            options: [.atomic]
        )
    }

    /// Reads a transaction manifest. A missing manifest in a non-empty journal
    /// or one that does not decode is uninterpretable; a manifest declaring a
    /// newer schema is `NewerTransaction`; any other read failure (permissions,
    /// I/O) is transient and propagates unchanged.
    private func decodeTransactionManifest<Manifest: Decodable>(
        _ type: Manifest.Type,
        in transactionDirectory: URL
    ) throws -> Manifest {
        let data: Data
        do {
            data = try Data(contentsOf: transactionDirectory.appendingPathComponent(Self.transactionManifestFileName))
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
            throw UninterpretableTransaction()
        }
        guard let probe = try? JSONDecoder().decode(TransactionSchemaProbe.self, from: data) else {
            throw UninterpretableTransaction()
        }
        guard probe.schemaVersion <= Self.transactionSchemaVersion else {
            throw NewerTransaction()
        }
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw UninterpretableTransaction()
        }
    }

    private func loadCommitTransaction(at transactionDirectory: URL) throws -> CommitTransactionManifest {
        let manifest = try decodeTransactionManifest(CommitTransactionManifest.self, in: transactionDirectory)
        guard [1, Self.transactionSchemaVersion].contains(manifest.schemaVersion),
              NativeSavedVoiceNaming.normalizedName(manifest.newVoiceName) == manifest.newVoiceName,
              !manifest.newVoiceName.isEmpty,
              URL(fileURLWithPath: manifest.newAudioFileName).lastPathComponent == manifest.newAudioFileName,
              manifest.newTranscriptFileName.map({
                  URL(fileURLWithPath: $0).lastPathComponent == $0
              }) ?? true,
              manifest.newMetadataFileName.map({
                  URL(fileURLWithPath: $0).lastPathComponent == $0
              }) ?? true else {
            throw UninterpretableTransaction()
        }
        if manifest.schemaVersion == 2, manifest.phase != .rolledBack {
            guard let digest = manifest.audioDigest, digest.count == 64, manifest.phase != nil else {
                throw UninterpretableTransaction()
            }
        }
        return manifest
    }

    private func reconcileCommitTransaction(at transactionDirectory: URL) throws {
        var manifest = try loadCommitTransaction(at: transactionDirectory)

        let candidateDirectory = candidateDirectory(for: manifest.candidateID)
        let publishedAudioURL = voicesDirectory.appendingPathComponent(manifest.newAudioFileName)
        // An unreadable candidate is not evidence that publication consumed it.
        let candidateContents: [URL]
        do { candidateContents = try directoryContents(at: candidateDirectory) }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
            candidateContents = [] // A completed candidate cleanup is legitimate.
        }
        let stagedAudioExists = candidateContents.contains {
            supportedAudioExtensions.contains($0.pathExtension.lowercased())
        }
        let committed: Bool
        if manifest.phase == .rolledBack {
            try removeTransaction(transactionDirectory)
            return
        }
        if manifest.schemaVersion == 2 {
            // `loadCommitTransaction` validated the digest of every version 2
            // journal that has not already rolled back.
            let digest = manifest.audioDigest ?? ""
            if manifest.phase == .backedUp && !stagedAudioExists {
                // The publication source was consumed. An unreadable, missing,
                // or changed destination is ambiguous, never rollback authority.
                guard (try? SamplingTakeEvidence.sha256FileDigest(at: publishedAudioURL)) == digest else {
                    throw PreparedVoiceRepositoryError.recoveryRequired
                }
                committed = true
            } else { committed = false }
        } else {
            committed = fileManager.fileExists(atPath: publishedAudioURL.path) && !stagedAudioExists
        }
        if committed {
            // Audio is the publication boundary. A crash after that move
            // completed the commit, so discard the stale candidate and old
            // replacement backup rather than rolling the visible voice back.
            try finishCommittedCandidate(candidateDirectory, transactionDirectory: transactionDirectory)
            return
        }

        if manifest.schemaVersion == 2 {
            // Prepared means backup may be partial; untouched old destinations
            // must not be mistaken for newly published sidecars.
            if manifest.phase == .backedUp {
                for name in [manifest.newTranscriptFileName, manifest.newMetadataFileName].compactMap({ $0 }) {
                    let url = voicesDirectory.appendingPathComponent(name)
                    if fileManager.fileExists(atPath: url.path) { try fileManager.removeItem(at: url) }
                }
            }
            try restoreVoiceAssets(from: transactionDirectory)
            manifest.phase = .rolledBack
            try writeTransactionManifest(manifest, to: transactionDirectory)
            try removeTransaction(transactionDirectory)
            return
        }

        if let newTranscriptFileName = manifest.newTranscriptFileName {
            let publishedTranscriptURL = voicesDirectory.appendingPathComponent(newTranscriptFileName)
            if fileManager.fileExists(atPath: publishedTranscriptURL.path) {
                if fileManager.fileExists(atPath: candidateDirectory.path) {
                    let candidate = try loadManifest(from: candidateDirectory)
                    guard candidate.id == manifest.candidateID,
                          let stagedTranscriptFileName = candidate.transcriptFileName else {
                        throw PreparedVoiceRepositoryError.malformedCandidate
                    }
                    let stagedTranscriptURL = candidateDirectory.appendingPathComponent(stagedTranscriptFileName)
                    if fileManager.fileExists(atPath: stagedTranscriptURL.path) {
                        try fileManager.removeItem(at: stagedTranscriptURL)
                    }
                    try fileManager.moveItem(at: publishedTranscriptURL, to: stagedTranscriptURL)
                } else {
                    try fileManager.removeItem(at: publishedTranscriptURL)
                }
            }
        }
        if let newMetadataFileName = manifest.newMetadataFileName {
            let publishedMetadataURL = voicesDirectory.appendingPathComponent(newMetadataFileName)
            if fileManager.fileExists(atPath: publishedMetadataURL.path) {
                try fileManager.removeItem(at: publishedMetadataURL)
            }
        }

        // No published audio means the commit never crossed its visibility
        // boundary. Restore any replaced voice and leave the candidate ready
        // for a safe retry.
        try restoreVoiceAssets(from: transactionDirectory)
        manifest.phase = .rolledBack
        try writeTransactionManifest(manifest, to: transactionDirectory)
        try removeTransaction(transactionDirectory)
    }

    private func reconcileDeleteTransaction(at transactionDirectory: URL) throws {
        let manifest = try decodeTransactionManifest(DeleteTransactionManifest.self, in: transactionDirectory)
        guard [1, Self.transactionSchemaVersion].contains(manifest.schemaVersion),
              (try? validateIdentifier(manifest.voiceID)) != nil else {
            throw UninterpretableTransaction()
        }

        // User confirmation is the delete boundary. If the process stopped
        // after journaling but before every move, finish moving any remaining
        // audio/transcript/prompt assets into the tombstone, then remove it.
        try moveVoiceAssets(id: manifest.voiceID, into: transactionDirectory)
        removeDerivedCloneReferences(ofVoiceAudioIn: transactionDirectory)
        try removeTransaction(transactionDirectory)
    }

    private func loadManifest(from directory: URL) throws -> CandidateManifest {
        let data = try Data(contentsOf: directory.appendingPathComponent("manifest.json"))
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(CandidateManifest.self, from: data)
        guard Self.supportedCandidateSchemaVersions.contains(manifest.schemaVersion),
              directory.lastPathComponent == manifest.id.uuidString.lowercased(),
              NativeSavedVoiceNaming.normalizedName(manifest.name) == manifest.name,
              !manifest.name.isEmpty,
              URL(fileURLWithPath: manifest.audioFileName).lastPathComponent == manifest.audioFileName,
              manifest.transcriptFileName.map({ URL(fileURLWithPath: $0).lastPathComponent == $0 }) ?? true else {
            throw PreparedVoiceRepositoryError.malformedCandidate
        }
        return manifest
    }

    /// No sidecar is an older or recorded voice. A sidecar that exists but cannot
    /// be read (damaged, or written by a newer schema) is reported as unreadable,
    /// never as absent, so outward export can ask the audio instead (RF-13).
    private func loadEnrollmentMetadata(
        for id: String
    ) -> (metadata: PreparedVoiceEnrollmentMetadata?, unreadable: Bool) {
        let url = voicesDirectory.appendingPathComponent("\(id).voice.json")
        guard fileManager.fileExists(atPath: url.path) else { return (nil, false) }
        guard let data = try? Data(contentsOf: url),
              let metadata = try? JSONDecoder().decode(
                  PreparedVoiceEnrollmentMetadata.self,
                  from: data
              ),
              (1...PreparedVoiceEnrollmentMetadata.currentSchemaVersion).contains(metadata.schemaVersion) else {
            return (nil, true)
        }
        return (metadata, false)
    }

    private func validateIdentifier(_ id: String) throws {
        guard !id.isEmpty,
              NativeSavedVoiceNaming.normalizedName(id) == id,
              URL(fileURLWithPath: id).lastPathComponent == id else {
            throw PreparedVoiceRepositoryError.invalidIdentifier
        }
    }

    private func candidateDirectory(for id: UUID) -> URL {
        candidatesDirectory.appendingPathComponent(id.uuidString.lowercased(), isDirectory: true)
    }

    private func directoryContents(at url: URL) throws -> [URL] {
        try fileManager.contentsOfDirectory(
            at: url,
            includingPropertiesForKeys: nil,
            options: []
        )
    }
}
