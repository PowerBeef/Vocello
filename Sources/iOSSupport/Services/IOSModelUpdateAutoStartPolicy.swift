import Foundation
import QwenVoiceCore

/// RF-59: what the iPhone does at launch with the models an earlier Vocello installed. The App
/// Store requires asking before a model download, with its size (RF-41, Guideline 4.2.3(ii)), so
/// the first launch asks once for every model together; after that consent, a later launch resumes
/// the update without asking. A model the user stopped, one whose download failed (it waits for
/// the user's Retry, NET-1) or one already transferring is left as it is, and nothing starts under
/// Low Data Mode; one that failed for want of space while earlier models hold some is offered again,
/// with their removal first. Pure, so both iOS test bundles drive it.
enum IOSModelUpdateAutoStartPolicy {
    static let simulatedAvailableBytesKey = "QVOICE_IOS_SIMULATED_AVAILABLE_BYTES"
    static let seedRetiredModelsKey = "QVOICE_IOS_SEED_RETIRED_MODELS"

    struct SeedResult: Equatable, Sendable {
        let didResetLedger: Bool
        let seededFolders: [String]

        var shouldClearConsent: Bool {
            didResetLedger || !seededFolders.isEmpty
        }

        static let none = SeedResult(didResetLedger: false, seededFolders: [])
    }

    /// Resolves launch free space, honouring the registered internal-diagnostics
    /// override (`QVOICE_IOS_SIMULATED_AVAILABLE_BYTES`) when valid so RF-59
    /// low-space Make Room tests never need to drain real device storage.
    static func resolvedAvailableBytes(
        systemAvailableBytes: Int64?,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        internalDiagnosticsAvailable: Bool = RuntimeDebugGate.internalDiagnosticsAvailable
    ) -> Int64? {
        guard internalDiagnosticsAvailable,
              let raw = RuntimeDebugGate.value(for: simulatedAvailableBytesKey, environment: environment)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            let override = Int64(raw),
            override >= 0 else {
            return systemAvailableBytes
        }
        return override
    }

    /// Seeds tiny earlier-Vocello retired model folders into an explicitly
    /// isolated `QVOICE_APP_SUPPORT_DIR` (validated by `AppPaths.isolatedModelDeliverySupportRoot`)
    /// when `QVOICE_IOS_SEED_RETIRED_MODELS` is active under `RuntimeDebugGate`.
    /// Never writes to the canonical root, accepts only contract-listed folder names,
    /// validates requested folders before resetting the isolated ledger, and is
    /// idempotent once `.qwenvoice-model-update.json` already exists.
    @discardableResult
    static func seedRetiredModelsIfConfigured(
        modelsDirectory: URL,
        allowedRetiredFolders: Set<String>,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        fileManager: FileManager = .default,
        internalDiagnosticsAvailable: Bool = RuntimeDebugGate.internalDiagnosticsAvailable
    ) -> SeedResult {
        guard internalDiagnosticsAvailable,
              AppPaths.isolatedModelDeliverySupportRoot(environment: environment) != nil,
              let raw = RuntimeDebugGate.value(for: seedRetiredModelsKey, environment: environment) else {
            return .none
        }
        let trimmedRaw = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let shouldResetLedger = trimmedRaw.hasPrefix("reset:")
        let folderList = shouldResetLedger ? String(trimmedRaw.dropFirst("reset:".count)) : trimmedRaw
        let requested = folderList
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && allowedRetiredFolders.contains($0) && !$0.contains("/") && $0 != "." && $0 != ".." }
        guard !requested.isEmpty else { return .none }

        let ledgerURL = modelsDirectory.appendingPathComponent(".qwenvoice-model-update.json", isDirectory: false)
        var didResetLedger = false
        if shouldResetLedger {
            if fileManager.fileExists(atPath: ledgerURL.path) {
                do {
                    try fileManager.removeItem(at: ledgerURL)
                } catch {
                    return .none
                }
            }
            didResetLedger = true
        } else if fileManager.fileExists(atPath: ledgerURL.path) {
            return .none
        }

        let fakeDigest = String(repeating: "ab", count: 32)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        var seeded: [String] = []
        for folder in requested {
            let directory = modelsDirectory.appendingPathComponent(folder, isDirectory: true)
            let manifestURL = directory.appendingPathComponent(ModelAssetIntegrityManifest.filename, isDirectory: false)
            guard !fileManager.fileExists(atPath: manifestURL.path) else { continue }
            do {
                let manifest = ModelAssetIntegrityManifest(
                    repo: "mlx-community/\(folder)",
                    revision: "earlier",
                    targetFolder: folder,
                    createdAtUTC: "2026-09-14T00:00:00Z",
                    files: [
                        ModelAssetIntegrityManifest.FileEntry(
                            path: "model.safetensors",
                            size: 7,
                            sha256: fakeDigest
                        ),
                    ]
                )
                let manifestData = try encoder.encode(manifest)
                try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
                try Data("earlier".utf8).write(
                    to: directory.appendingPathComponent("model.safetensors", isDirectory: false),
                    options: .atomic
                )
                try manifestData.write(to: manifestURL, options: .atomic)
                seeded.append(folder)
            } catch {
                try? fileManager.removeItem(at: directory)
                continue
            }
        }
        return SeedResult(didResetLedger: didResetLedger, seededFolders: seeded)
    }

    struct Candidate: Equatable, Sendable {
        let modelID: String
        let estimatedBytes: Int64
        /// The user stopped this model's update.
        let paused: Bool
        /// Queued, waiting for a network, transferring, verifying or installing.
        let active: Bool
        /// The last attempt failed and waits for Retry.
        let failed: Bool
        /// It failed for want of space: a Retry would fail again while the earlier models stay.
        let failedForSpace: Bool

        init(
            modelID: String, estimatedBytes: Int64, paused: Bool, active: Bool, failed: Bool,
            failedForSpace: Bool = false
        ) {
            self.modelID = modelID
            self.estimatedBytes = estimatedBytes
            self.paused = paused
            self.active = active
            self.failed = failed || failedForSpace
            self.failedForSpace = failedForSpace
        }

        /// A launch's view of a model whose mode the update plan holds: stopped in the ledger or
        /// this session, transferring, or failed in the ledger (kept from an earlier launch until
        /// the user's Retry clears it) or this session.
        init(
            modelID: String, estimatedBytes: Int64, mode: GenerationMode, plan: ModelUpdatePlan,
            pausedThisSession: Bool, transferring: Bool, failedThisSession: Bool
        ) {
            self.init(
                modelID: modelID, estimatedBytes: estimatedBytes,
                paused: plan.isPaused(mode) || pausedThisSession,
                active: transferring,
                failed: plan.hasFailed(mode) || failedThisSession,
                failedForSpace: plan.failure(mode) == .space
            )
        }
    }

    enum Decision: Equatable, Sendable {
        case none
        /// Ask once, naming the total size. `makesRoomFirst`: the phone lacks the space to keep the
        /// earlier models while the first new one downloads, so they are removed first.
        case ask(modelIDs: [String], totalBytes: Int64, makesRoomFirst: Bool)
        case start(modelIDs: [String])
    }

    static func decide(
        candidates: [Candidate],
        consented: Bool,
        lowDataMode: Bool,
        availableBytes: Int64?,
        holdsEarlierModels: Bool
    ) -> Decision {
        let ready = candidates.filter { !$0.paused && !$0.active && !$0.failed }
        // A download that failed for want of space while earlier models hold some: the phone asks
        // again, this time to remove them first (a new decision, so asked even after consent).
        let failedForSpace = candidates.filter { !$0.paused && !$0.active && $0.failedForSpace }
        if holdsEarlierModels, !failedForSpace.isEmpty, !lowDataMode {
            let asked = ready + failedForSpace
            return .ask(
                modelIDs: asked.map(\.modelID), totalBytes: asked.reduce(0) { $0 + $1.estimatedBytes }, makesRoomFirst: true
            )
        }
        guard !ready.isEmpty, !lowDataMode else { return .none }
        guard !consented else { return .start(modelIDs: ready.map(\.modelID)) }
        let largest = ready.map(\.estimatedBytes).max() ?? 0
        let roomForFirst = availableBytes.map { $0 >= IOSModelDeliverySupport.minimumFreeBytes(forFetching: largest) } ?? true
        return .ask(
            modelIDs: ready.map(\.modelID),
            totalBytes: ready.reduce(0) { $0 + $1.estimatedBytes },
            makesRoomFirst: holdsEarlierModels && !roomForFirst
        )
    }
}
