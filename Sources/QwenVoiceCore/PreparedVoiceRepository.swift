import Foundation

enum PreparedVoiceRepositoryError: LocalizedError, Equatable {
    case invalidName
    case invalidIdentifier
    case sourceMissing
    case duplicateName(String)
    case candidateMissing
    case voiceMissing(String)
    case malformedCandidate

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
        }
    }
}

struct PreparedVoiceStorageRecord: Sendable, Equatable {
    let id: String
    let name: String
    let audioURL: URL
    let hasTranscript: Bool
    let enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
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
    private static let transactionSchemaVersion = 1
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
    }

    private struct CommitTransactionManifest: Codable, Sendable {
        let schemaVersion: Int
        let candidateID: UUID
        let newVoiceName: String
        let newAudioFileName: String
        let newTranscriptFileName: String?
        let newMetadataFileName: String?
    }

    private struct DeleteTransactionManifest: Codable, Sendable {
        let schemaVersion: Int
        let voiceID: String
    }

    private let voicesDirectory: URL
    private let candidatesDirectory: URL
    private let transactionsDirectory: URL
    private let supportedAudioExtensions: Set<String>
    private let fileManager: FileManager
    private let now: @Sendable () -> Date

    init(
        appSupportDirectory: URL,
        supportedAudioExtensions: Set<String>,
        fileManager: FileManager = .default,
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        voicesDirectory = appSupportDirectory.appendingPathComponent("voices", isDirectory: true)
        candidatesDirectory = appSupportDirectory.appendingPathComponent("voice-candidates", isDirectory: true)
        transactionsDirectory = appSupportDirectory.appendingPathComponent("voice-transactions", isDirectory: true)
        self.supportedAudioExtensions = supportedAudioExtensions
        self.fileManager = fileManager
        self.now = now
    }

    func reconcile() throws {
        try createRoots()

        for url in try directoryContents(at: candidatesDirectory) {
            if url.lastPathComponent.hasPrefix(".partial-") {
                try fileManager.removeItem(at: url)
                continue
            }
            guard let manifest = try? loadManifest(from: url) else {
                try fileManager.removeItem(at: url)
                continue
            }
            if now().timeIntervalSince(manifest.createdAt) >= Self.candidateLifetime {
                try fileManager.removeItem(at: url)
            }
        }

        for url in try directoryContents(at: transactionsDirectory) {
            if url.lastPathComponent.hasPrefix("delete-") {
                try reconcileDeleteTransaction(at: url)
            } else if url.lastPathComponent.hasPrefix("commit-") {
                try reconcileCommitTransaction(at: url)
            } else {
                // Unknown transaction state is not safe to interpret. Keep it
                // for diagnosis instead of guessing whether its assets should
                // be restored or deleted.
                throw PreparedVoiceRepositoryError.malformedCandidate
            }
        }
    }

    func list() throws -> [PreparedVoiceStorageRecord] {
        try createRoots()
        return try directoryContents(at: voicesDirectory)
            .filter { supportedAudioExtensions.contains($0.pathExtension.lowercased()) }
            .map { audioURL in
                let id = audioURL.deletingPathExtension().lastPathComponent
                return PreparedVoiceStorageRecord(
                    id: id,
                    name: id,
                    audioURL: audioURL,
                    hasTranscript: fileManager.fileExists(
                        atPath: voicesDirectory.appendingPathComponent("\(id).txt").path
                    ),
                    enrollmentMetadata: loadEnrollmentMetadata(for: id)
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
        replacingVoiceID: String?
    ) throws -> PreparedVoiceCandidate {
        try createRoots()
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
                createdAt: now()
            )
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            try encoder.encode(manifest).write(
                to: partialDirectory.appendingPathComponent("manifest.json"),
                options: [.atomic]
            )
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
        try createRoots()
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
        do {
            try fileManager.createDirectory(at: transactionDirectory, withIntermediateDirectories: false)
            try writeTransactionManifest(
                CommitTransactionManifest(
                    schemaVersion: Self.transactionSchemaVersion,
                    candidateID: id,
                    newVoiceName: manifest.name,
                    newAudioFileName: destinationAudioURL.lastPathComponent,
                    newTranscriptFileName: manifest.transcriptFileName == nil
                        ? nil
                        : destinationTranscriptURL.lastPathComponent,
                    newMetadataFileName: manifest.enrollmentMetadata == nil
                        ? nil
                        : destinationMetadataURL.lastPathComponent
                ),
                to: transactionDirectory
            )
        } catch {
            if fileManager.fileExists(atPath: transactionDirectory.path) {
                try? fileManager.removeItem(at: transactionDirectory)
            }
            throw error
        }

        var publishedTranscript = false
        var publishedMetadata = false
        var publishedAudio = false
        do {
            if let replacingVoiceID = manifest.replacingVoiceID {
                try moveVoiceAssets(id: replacingVoiceID, into: transactionDirectory)
            }

            if let transcriptFileName = manifest.transcriptFileName {
                let stagedTranscriptURL = candidateDirectory.appendingPathComponent(transcriptFileName)
                guard fileManager.fileExists(atPath: stagedTranscriptURL.path) else {
                    throw PreparedVoiceRepositoryError.malformedCandidate
                }
                if fileManager.fileExists(atPath: destinationTranscriptURL.path) {
                    try fileManager.removeItem(at: destinationTranscriptURL)
                }
                try fileManager.moveItem(at: stagedTranscriptURL, to: destinationTranscriptURL)
                publishedTranscript = true
            }

            if let enrollmentMetadata = manifest.enrollmentMetadata {
                try JSONEncoder().encode(enrollmentMetadata).write(
                    to: destinationMetadataURL,
                    options: [.atomic]
                )
                publishedMetadata = true
            }

            // Publication boundary: listing discovers the voice only after
            // this final move succeeds.
            try fileManager.moveItem(at: stagedAudioURL, to: destinationAudioURL)
            publishedAudio = true
            try fileManager.removeItem(at: candidateDirectory)
            try fileManager.removeItem(at: transactionDirectory)
        } catch {
            if publishedAudio, fileManager.fileExists(atPath: destinationAudioURL.path) {
                try? fileManager.moveItem(at: destinationAudioURL, to: stagedAudioURL)
            }
            if publishedTranscript, fileManager.fileExists(atPath: destinationTranscriptURL.path) {
                let transcriptFileName = manifest.transcriptFileName ?? "transcript.txt"
                try? fileManager.moveItem(
                    at: destinationTranscriptURL,
                    to: candidateDirectory.appendingPathComponent(transcriptFileName)
                )
            }
            if publishedMetadata, fileManager.fileExists(atPath: destinationMetadataURL.path) {
                try? fileManager.removeItem(at: destinationMetadataURL)
            }
            try? restoreVoiceAssets(from: transactionDirectory)
            if fileManager.fileExists(atPath: transactionDirectory.path) {
                try? fileManager.removeItem(at: transactionDirectory)
            }
            throw error
        }

        return PreparedVoiceStorageRecord(
            id: manifest.name,
            name: manifest.name,
            audioURL: destinationAudioURL,
            hasTranscript: manifest.transcriptFileName != nil,
            enrollmentMetadata: manifest.enrollmentMetadata
        )
    }

    func discard(id: UUID) throws {
        let directory = candidateDirectory(for: id)
        guard fileManager.fileExists(atPath: directory.path) else { return }
        try fileManager.removeItem(at: directory)
    }

    func delete(id: String) throws {
        try createRoots()
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
            try fileManager.removeItem(at: transactionDirectory)
        } catch {
            try? restoreVoiceAssets(from: transactionDirectory)
            if fileManager.fileExists(atPath: transactionDirectory.path) {
                try? fileManager.removeItem(at: transactionDirectory)
            }
            throw error
        }
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
            let destinationURL = voicesDirectory.appendingPathComponent(sourceURL.lastPathComponent)
            if fileManager.fileExists(atPath: destinationURL.path) {
                try fileManager.removeItem(at: destinationURL)
            }
            try fileManager.moveItem(at: sourceURL, to: destinationURL)
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

    private func reconcileCommitTransaction(at transactionDirectory: URL) throws {
        let manifestURL = transactionDirectory.appendingPathComponent(Self.transactionManifestFileName)
        let manifest = try JSONDecoder().decode(
            CommitTransactionManifest.self,
            from: Data(contentsOf: manifestURL)
        )
        guard manifest.schemaVersion == Self.transactionSchemaVersion,
              NativeSavedVoiceNaming.normalizedName(manifest.newVoiceName) == manifest.newVoiceName,
              !manifest.newVoiceName.isEmpty,
              URL(fileURLWithPath: manifest.newAudioFileName).lastPathComponent == manifest.newAudioFileName,
              manifest.newTranscriptFileName.map({
                  URL(fileURLWithPath: $0).lastPathComponent == $0
              }) ?? true,
              manifest.newMetadataFileName.map({
                  URL(fileURLWithPath: $0).lastPathComponent == $0
              }) ?? true else {
            throw PreparedVoiceRepositoryError.malformedCandidate
        }

        let candidateDirectory = candidateDirectory(for: manifest.candidateID)
        let publishedAudioURL = voicesDirectory.appendingPathComponent(manifest.newAudioFileName)
        if fileManager.fileExists(atPath: publishedAudioURL.path) {
            // Audio is the publication boundary. A crash after that move
            // completed the commit, so discard the stale candidate and old
            // replacement backup rather than rolling the visible voice back.
            if fileManager.fileExists(atPath: candidateDirectory.path) {
                try fileManager.removeItem(at: candidateDirectory)
            }
            try fileManager.removeItem(at: transactionDirectory)
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
        try fileManager.removeItem(at: transactionDirectory)
    }

    private func reconcileDeleteTransaction(at transactionDirectory: URL) throws {
        let manifest = try JSONDecoder().decode(
            DeleteTransactionManifest.self,
            from: Data(
                contentsOf: transactionDirectory.appendingPathComponent(Self.transactionManifestFileName)
            )
        )
        guard manifest.schemaVersion == Self.transactionSchemaVersion else {
            throw PreparedVoiceRepositoryError.malformedCandidate
        }
        try validateIdentifier(manifest.voiceID)

        // User confirmation is the delete boundary. If the process stopped
        // after journaling but before every move, finish moving any remaining
        // audio/transcript/prompt assets into the tombstone, then remove it.
        try moveVoiceAssets(id: manifest.voiceID, into: transactionDirectory)
        try fileManager.removeItem(at: transactionDirectory)
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

    private func loadEnrollmentMetadata(for id: String) -> PreparedVoiceEnrollmentMetadata? {
        let url = voicesDirectory.appendingPathComponent("\(id).voice.json")
        guard let data = try? Data(contentsOf: url),
              let metadata = try? JSONDecoder().decode(
                  PreparedVoiceEnrollmentMetadata.self,
                  from: data
              ),
              metadata.schemaVersion == PreparedVoiceEnrollmentMetadata.currentSchemaVersion else {
            return nil
        }
        return metadata
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
