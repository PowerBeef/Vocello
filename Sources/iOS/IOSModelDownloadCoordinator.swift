import Foundation
import QwenVoiceCore

struct IOSModelDeliverySnapshot: Equatable, Sendable {
    enum Phase: String, Codable, Sendable {
        case queued
        case waitingForConnectivity
        case downloading
        case retrying
        case verifying
        case installing
        case cancelling
        case installed
        case failed
        case deleting
        case deleted
    }

    let modelID: String
    let phase: Phase
    let downloadedBytes: Int64
    let totalBytes: Int64?
    let estimatedBytes: Int64?
    let bytesPerSecond: Int64?
    let estimatedSecondsRemaining: Double?
    let retryCount: Int
    let message: String?
    let operationGeneration: UInt64

    init(
        modelID: String,
        phase: Phase,
        downloadedBytes: Int64,
        totalBytes: Int64?,
        estimatedBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        retryCount: Int = 0,
        message: String?,
        operationGeneration: UInt64
    ) {
        self.modelID = modelID
        self.phase = phase
        self.downloadedBytes = downloadedBytes
        self.totalBytes = totalBytes
        self.estimatedBytes = estimatedBytes
        self.bytesPerSecond = bytesPerSecond
        self.estimatedSecondsRemaining = estimatedSecondsRemaining
        self.retryCount = retryCount
        self.message = message
        self.operationGeneration = operationGeneration
    }
}

/// Schema-v1 compatibility record. It is decoded only by the one-time migration and is never
/// written again. The absolute target path is reduced to its final folder name before v2 storage.
private struct IOSLegacyInFlightDownloadRecord: Codable, Sendable {
    let modelID: String
    let artifactVersion: String
    let backgroundSessionIdentifier: String
    let repo: String
    let revision: String
    let targetFolderPath: String
    let totalBytes: Int64
}

private struct IOSLegacyInFlightDownloadsDocument: Codable, Sendable {
    let schemaVersion: Int
    let downloads: [IOSLegacyInFlightDownloadRecord]
}

/// Owns one bundle-aware background URLSession for the whole iOS app lifetime. One model runs at
/// a time, queued requests are durable, and task adoption occurs inside `HuggingFaceDownloader`
/// before any missing task is created.
@MainActor
final class IOSModelDownloadCoordinator {
    private struct CancellationPersistenceError: LocalizedError {
        static let privacySafeMessage = "Vocello couldn't save the cancellation state. The download and staged files were preserved. Retry Cancel after checking available storage."

        var errorDescription: String? { Self.privacySafeMessage }
    }

    private struct CancellationInstallReconciliationError: LocalizedError {
        static let privacySafeMessage = "Vocello couldn't reconcile a model that completed during cancellation. The installed files were preserved. Restart Vocello before retrying."

        var errorDescription: String? { Self.privacySafeMessage }
    }

    struct InFlightDownload {
        let modelID: String
        let logicalRequestID: String
        let task: Task<Void, Never>
        let targetDir: URL
        let stagingRoot: URL
        let totalBytes: Int64
        let operationGeneration: UInt64
        let targetWasAvailableAtStart: Bool
    }

    typealias SnapshotSink = @MainActor (IOSModelDeliverySnapshot) -> Void

    private static let maxConcurrentModels = 1
    private let modelAssetStore: LocalModelAssetStore
    private let configuration: IOSModelDeliveryConfiguration
    private let fileManager: FileManager
    private let snapshotSink: SnapshotSink
    private let catalogSession: URLSession
    private let ledgerStore: IOSModelDownloadLedgerStore
    private let diagnosticsStore: ModelDownloadDiagnosticsStore
    private var inflight: [String: InFlightDownload] = [:]
    private var pending: [ModelDescriptor] = []
    private var cachedCatalog: IOSModelCatalogDocument?
    private var cachedProductionCatalog: ProductionModelCatalog?
    private var operationGeneration: UInt64 = 0
    private var lastLedgerProgressWrite: [String: TimeInterval] = [:]
    /// Prevents already-enqueued progress callbacks from weakening a durable
    /// cancellation while its URLSession task barrier is still draining.
    private var cancellationBarriers: Set<String> = []

    private lazy var downloader: HuggingFaceDownloader = makeSharedDownloader()

    init(
        modelAssetStore: LocalModelAssetStore,
        configuration: IOSModelDeliveryConfiguration = .default(),
        fileManager: FileManager = .default,
        snapshotSink: @escaping SnapshotSink
    ) {
        self.modelAssetStore = modelAssetStore
        self.configuration = configuration
        self.fileManager = fileManager
        self.snapshotSink = snapshotSink
        self.catalogSession = URLSession(configuration: .ephemeral)
        self.ledgerStore = IOSModelDownloadLedgerStore(
            fileURL: AppPaths.modelDeliveryStateFile,
            fileManager: fileManager
        )
        self.diagnosticsStore = ModelDownloadDiagnosticsStore(
            directory: AppPaths.modelDownloadDiagnosticsDir,
            fileManager: fileManager
        )
    }

    func install(model: ModelDescriptor) async throws {
        guard model.iosDownloadEligible else {
            throw IOSModelDeliveryError.notEligibleForIOS(modelID: model.id)
        }
        if inflight[model.id] != nil || pending.contains(where: { $0.id == model.id }) { return }

        try prepareDirectories()
        let entry = try IOSModelDeliverySupport.matchingCatalogEntry(
            for: model,
            in: try await fetchCatalog(),
            configuration: configuration
        )
        _ = try await productionDeliveryPlan(for: model, matching: entry)
        let totalBytes = entry.totalBytes > 0
            ? entry.totalBytes
            : entry.files.reduce(Int64(0)) { $0 + $1.sizeBytes }
        try IOSModelDeliverySupport.ensureSufficientDiskSpace(
            requiredBytes: totalBytes,
            at: AppPaths.appSupportDir,
            fileManager: fileManager
        )

        var ledger = try ledgerStore.load()
        let replacement = makeLedgerRequest(model: model, entry: entry, totalBytes: totalBytes)
        if let index = ledger.requests.firstIndex(where: { $0.modelID == model.id }) {
            let existing = ledger.requests[index]
            if existing.hasSameArtifactIdentity(as: replacement) {
                ledger.requests[index].status = .queued
                ledger.requests[index].totalBytes = totalBytes
            } else {
                // Artifact update: resume state from the superseded identity is
                // meaningless and can even invalidate the ledger (an already
                // fully received larger artifact leaves receivedBytes above the
                // smaller replacement's totalBytes). Replace the request whole.
                ledger.requests[index] = replacement
            }
        } else {
            ledger.requests.append(replacement)
        }
        try ledgerStore.save(ledger)
        cancellationBarriers.remove(model.id)
        pending.append(model)
        publishSnapshot(for: model, phase: .queued, downloadedBytes: ledgerRequest(model.id, in: ledger)?.receivedBytes ?? 0)
        await startPendingDownloads()
    }

    /// Cancels only after the intent is durable. Returning `false` means the
    /// coordinator deliberately preserved the task/staging rather than claim a
    /// cancellation that a later launch could undo.
    @discardableResult
    func cancel(modelID: String) async -> Bool {
        if let pendingIndex = pending.firstIndex(where: { $0.id == modelID }) {
            cancellationBarriers.insert(modelID)
            guard persistCancellationStatus(modelID: modelID, status: .cancelRequested) else {
                cancellationBarriers.remove(modelID)
                publishCancellationPersistenceFailure(modelID: modelID)
                return false
            }
            pending.remove(at: pendingIndex)
            guard persistCancellationStatus(modelID: modelID, status: .deleted) else {
                publishCancellationPersistenceFailure(modelID: modelID)
                return false
            }
            discardStaging(modelID: modelID)
            publishTerminal(modelID: modelID, phase: .deleted)
            cancellationBarriers.remove(modelID)
            return true
        }
        guard let active = inflight[modelID] else {
            reconcileNoOpCancellation(modelID: modelID)
            return true
        }

        cancellationBarriers.insert(modelID)
        guard persistCancellationStatus(modelID: modelID, status: .cancelRequested) else {
            cancellationBarriers.remove(modelID)
            publishCancellationPersistenceFailure(
                modelID: modelID,
                recoverableGeneration: active.operationGeneration
            )
            return false
        }
        publishSnapshot(
            modelID: modelID,
            phase: .cancelling,
            downloadedBytes: ledgerReceivedBytes(modelID: modelID),
            totalBytes: active.totalBytes,
            message: nil,
            generation: active.operationGeneration
        )

        await downloader.cancel()
        active.task.cancel()
        await active.task.value
        inflight.removeValue(forKey: modelID)
        guard rollbackRacedInstallationIfNeeded(active) else {
            reconcileInstalledAfterCancellationCleanupFailure(active)
            await startPendingDownloads()
            return false
        }
        guard persistCancellationStatus(modelID: modelID, status: .deleted) else {
            publishCancellationPersistenceFailure(modelID: modelID)
            await startPendingDownloads()
            return false
        }
        try? fileManager.removeItem(at: active.stagingRoot)
        publishTerminal(modelID: modelID, phase: .deleted)
        cancellationBarriers.remove(modelID)
        await startPendingDownloads()
        return true
    }

    func delete(model: ModelDescriptor) async throws {
        if inflight[model.id] != nil || pending.contains(where: { $0.id == model.id }) {
            guard await cancel(modelID: model.id) else {
                throw CancellationPersistenceError()
            }
        }
        let generation = beginOperation()
        publishSnapshot(
            modelID: model.id,
            phase: .deleting,
            downloadedBytes: 0,
            totalBytes: nil,
            message: nil,
            generation: generation
        )
        let targetDir = model.installDirectory(in: AppPaths.modelsDir)
        try SharedModelComponentStore(modelsRoot: AppPaths.modelsDir).deleteModel(
            modelFolder: targetDir.lastPathComponent
        )
        discardStaging(modelID: model.id)
        markLedgerTerminal(modelID: model.id, status: .deleted)
        publishTerminal(modelID: model.id, phase: .deleted)
    }

    func restoreInFlightDownloadsIfNeeded() async {
        do {
            try prepareDirectories()
            try await migrateV1IfNeeded()
            var ledger = try ledgerStore.load()
            var restored: [ModelDescriptor] = []

            for index in ledger.requests.indices {
                let request = ledger.requests[index]
                guard let descriptor = modelAssetStore.descriptor(id: request.modelID)?.model,
                      descriptor.artifactVersion == request.artifactVersion else {
                    ledger.requests[index].status = .failed
                    continue
                }
                if request.status == .cancelRequested || request.status == .deleted {
                    discardStaging(modelID: request.modelID)
                    ledger.requests[index].status = .deleted
                    continue
                }
                let installed = descriptor.isAvailable(
                    in: AppPaths.modelsDir,
                    fileManager: fileManager
                )
                if installed {
                    ledger.requests[index].status = .installed
                    continue
                }
                if request.status != .installed {
                    ledger.requests[index].status = .queued
                    restored.append(descriptor)
                }
            }
            try ledgerStore.save(ledger)
            pending = restored
            if restored.isEmpty {
                await downloader.cancelAllSessionTasks()
                IOSModelDeliveryBackgroundEventRelay.complete(
                    forOwnedSessionIdentifier: configuration.backgroundSessionIdentifier
                )
            } else {
                await startPendingDownloads()
            }
        } catch {
            diagnosticsStore.recordFailure(classification: "ledger-restore", message: error.localizedDescription)
            await downloader.cancelAllSessionTasks()
            IOSModelDeliveryBackgroundEventRelay.complete(
                forOwnedSessionIdentifier: configuration.backgroundSessionIdentifier
            )
        }
    }

    func resumeBackgroundEventsIfNeeded() async {
        let hasActiveWork: Bool
        do {
            hasActiveWork = try ledgerStore.load().requests.contains(where: {
                ![.installed, .failed, .deleted].contains($0.status)
            })
        } catch {
            diagnosticsStore.recordFailure(
                classification: "background-event-reconciliation",
                message: error.localizedDescription
            )
            return
        }
        guard !hasActiveWork else { return }
        IOSModelDeliveryBackgroundEventRelay.complete(
            forOwnedSessionIdentifier: configuration.backgroundSessionIdentifier
        )
    }

    private func startPendingDownloads() async {
        while inflight.count < Self.maxConcurrentModels, let model = pending.first {
            pending.removeFirst()
            await beginDownload(model)
        }
    }

    private func beginDownload(_ model: ModelDescriptor) async {
        do {
            let catalog = try await fetchCatalog()
            let entry = try IOSModelDeliverySupport.matchingCatalogEntry(
                for: model,
                in: catalog,
                configuration: configuration
            )
            let delivery = try await productionDeliveryPlan(for: model, matching: entry)
            let installedFiles = resolveFiles(entry: entry)
            let downloadPaths = Set(delivery.filesToDownload.map(\.path))
            let files = installedFiles.filter { downloadPaths.contains($0.path) }
            let totalBytes = entry.totalBytes > 0
                ? entry.totalBytes
                : entry.files.reduce(Int64(0)) { $0 + $1.sizeBytes }
            let targetDir = model.installDirectory(in: AppPaths.modelsDir)
            let stagingRoot = stagingRoot(modelID: model.id)
            let generation = beginOperation()

            var ledger = try ledgerStore.load()
            guard let request = ledgerRequest(model.id, in: ledger) else {
                throw IOSModelDownloadLedgerError.invalidDocument
            }
            updateRequest(model.id, in: &ledger) { $0.status = .downloading }
            try ledgerStore.save(ledger)

            let task = Task { @MainActor [weak self] in
                guard let self else { return }
                await self.runDownload(
                    model: model,
                    request: request,
                    files: files,
                    targetDir: targetDir,
                    stagingRoot: stagingRoot,
                    generation: generation,
                    totalBytes: totalBytes,
                    installedFiles: installedFiles,
                    sharedComponentPlan: delivery.sharedComponentPlan
                )
            }
            inflight[model.id] = InFlightDownload(
                modelID: model.id,
                logicalRequestID: request.logicalRequestID,
                task: task,
                targetDir: targetDir,
                stagingRoot: stagingRoot,
                totalBytes: totalBytes,
                operationGeneration: generation,
                targetWasAvailableAtStart: model.isAvailable(
                    in: AppPaths.modelsDir,
                    fileManager: fileManager
                )
            )
        } catch {
            markLedgerTerminal(modelID: model.id, status: .failed)
            publishFailed(modelID: model.id, message: error.localizedDescription)
        }
    }

    private func runDownload(
        model: ModelDescriptor,
        request: IOSModelDownloadLedger.Request,
        files: [HuggingFaceDownloader.RepoFile],
        targetDir: URL,
        stagingRoot: URL,
        generation: UInt64,
        totalBytes: Int64,
        installedFiles: [HuggingFaceDownloader.RepoFile],
        sharedComponentPlan: SharedComponentMigrationPlan?
    ) async {
        do {
            try await downloader.downloadFiles(
                files,
                repo: request.repo,
                revision: request.revision,
                to: targetDir,
                requestIdentity: ModelDownloadRequestIdentity(
                    logicalRequestID: request.logicalRequestID,
                    modelID: request.modelID,
                    artifactVersion: request.artifactVersion
                ),
                stagingRoot: stagingRoot,
                installedFiles: installedFiles,
                sharedComponentPlan: sharedComponentPlan
            )
            guard inflight[model.id]?.operationGeneration == generation,
                  !cancellationBarriers.contains(model.id) else { return }
            inflight.removeValue(forKey: model.id)
            markLedgerTerminal(modelID: model.id, status: .installed, receivedBytes: totalBytes)
            diagnosticsStore.recordSuccess(expectedBytes: totalBytes)
            publishSnapshot(
                modelID: model.id,
                phase: .installed,
                downloadedBytes: totalBytes,
                totalBytes: totalBytes,
                message: nil,
                generation: generation
            )
        } catch is CancellationError {
            return
        } catch let error as HuggingFaceDownloader.DownloadError {
            if case .cancelled = error { return }
            guard inflight[model.id]?.operationGeneration == generation,
                  !cancellationBarriers.contains(model.id) else { return }
            inflight.removeValue(forKey: model.id)
            markLedgerTerminal(modelID: model.id, status: .failed)
            diagnosticsStore.recordFailure(classification: "transfer", message: error.localizedDescription)
            publishFailed(modelID: model.id, message: error.localizedDescription)
        } catch {
            guard inflight[model.id]?.operationGeneration == generation,
                  !cancellationBarriers.contains(model.id) else { return }
            inflight.removeValue(forKey: model.id)
            markLedgerTerminal(modelID: model.id, status: .failed)
            diagnosticsStore.recordFailure(classification: "filesystem", message: error.localizedDescription)
            publishFailed(modelID: model.id, message: error.localizedDescription)
        }
        await startPendingDownloads()
    }

    private func makeSharedDownloader() -> HuggingFaceDownloader {
        var engineConfig = HuggingFaceDownloader.Configuration()
        engineConfig.maxConcurrentFiles = 6
        engineConfig.chunkLargeFiles = false

        let sessionConfig = URLSessionConfiguration.background(
            withIdentifier: configuration.backgroundSessionIdentifier
        )
        sessionConfig.isDiscretionary = false
        sessionConfig.waitsForConnectivity = true
        sessionConfig.sessionSendsLaunchEvents = true
        sessionConfig.httpMaximumConnectionsPerHost = 6
        let backgroundSessionIdentifier = configuration.backgroundSessionIdentifier

        return HuggingFaceDownloader(
            progressHandler: { [weak self] progress in
                Task { @MainActor [weak self] in self?.handleProgress(progress) }
            },
            sessionConfiguration: sessionConfig,
            engineConfiguration: engineConfig,
            durableTemporaryDirectory: AppPaths.modelDownloadDelegateFilesDir,
            // The diagnostics store is internally serialized. Record synchronously so the
            // terminal success summary cannot overtake URLSession's final task metrics.
            transferMetricsHandler: { [diagnosticsStore] metrics in
                diagnosticsStore.record(metrics: metrics)
            },
            verifiedArtifactHandler: { [weak self] receipt in
                await MainActor.run { [weak self] in self?.recordVerifiedFile(receipt) }
            },
            backgroundSessionCompletionHandler: { identifier in
                Task { @MainActor in
                    guard identifier == backgroundSessionIdentifier else { return }
                    IOSModelDeliveryBackgroundEventRelay.complete(
                        forOwnedSessionIdentifier: backgroundSessionIdentifier
                    )
                }
            },
            artifactURLPolicy: ModelArtifactURLPolicy(
                allowedInitialHosts: configuration.allowedHosts,
                allowedRedirectHostSuffixes: configuration.allowedRedirectHostSuffixes
            )
        )
    }

    private func handleProgress(_ progress: HuggingFaceDownloader.RepositoryProgress) {
        diagnosticsStore.record(progress: progress)
        guard let active = inflight.values.first,
              let descriptor = modelAssetStore.descriptor(id: active.modelID)?.model,
              !cancellationBarriers.contains(active.modelID) else { return }
        let phase: IOSModelDeliverySnapshot.Phase
        let ledgerStatus: IOSModelDownloadLedger.Status
        switch progress.phase {
        case .queued:
            phase = .queued; ledgerStatus = .queued
        case .waitingForConnectivity:
            phase = .waitingForConnectivity; ledgerStatus = .waitingForConnectivity
        case .downloading:
            phase = .downloading; ledgerStatus = .downloading
        case .retrying:
            phase = .retrying; ledgerStatus = .retrying
        case .verifying:
            phase = .verifying; ledgerStatus = .verifying
        case .installing:
            phase = .installing; ledgerStatus = .installing
        case .cancelling:
            phase = .cancelling; ledgerStatus = .cancelRequested
        }
        let visibleBytes = ModelDownloadProgressReconciler.visibleBytes(
            current: progress.downloadedBytes,
            persisted: ledgerReceivedBytes(modelID: active.modelID),
            total: active.totalBytes
        )
        guard persistProgressIfNeeded(
            modelID: active.modelID,
            status: ledgerStatus,
            bytes: visibleBytes,
            retryCount: progress.retryCount
        ) else { return }
        publishSnapshot(
            modelID: active.modelID,
            phase: phase,
            downloadedBytes: visibleBytes,
            totalBytes: progress.totalBytes > 0 ? progress.totalBytes : active.totalBytes,
            bytesPerSecond: progress.phase == .downloading ? progress.bytesPerSecond : nil,
            estimatedSecondsRemaining: progress.estimatedSecondsRemaining,
            retryCount: progress.retryCount,
            message: progress.isStalled ? "No progress for 20 seconds" : progress.statusMessage,
            generation: active.operationGeneration,
            estimatedBytes: descriptor.estimatedDownloadBytes
        )
    }

    private func resolveFiles(entry: IOSModelCatalogEntry) -> [HuggingFaceDownloader.RepoFile] {
        entry.files.map { file in
            HuggingFaceDownloader.RepoFile(
                path: file.relativePath,
                size: file.sizeBytes,
                sha256: file.sha256,
                absoluteURL: try? IOSModelDeliverySupport.downloadURL(
                    for: file,
                    entry: entry,
                    configuration: configuration
                )
            )
        }
    }

    private func fetchCatalog() async throws -> IOSModelCatalogDocument {
        if let cachedCatalog { return cachedCatalog }
        let document: IOSModelCatalogDocument
        if configuration.catalogURL.isBundledModelCatalog {
            guard let url = Bundle.main.url(
                forResource: IOSModelDeliveryConfiguration.bundledCatalogResourceName,
                withExtension: IOSModelDeliveryConfiguration.bundledCatalogResourceExtension
            ) else {
                throw IOSModelDeliveryError.invalidCatalog("Bundled iPhone model catalog is missing.")
            }
            document = try JSONDecoder().decode(IOSModelCatalogDocument.self, from: Data(contentsOf: url))
        } else {
            let (data, response) = try await catalogSession.data(from: configuration.catalogURL)
            guard let response = response as? HTTPURLResponse,
                  (200..<300).contains(response.statusCode) else {
                throw IOSModelDeliveryError.invalidCatalog("Catalog endpoint returned an unexpected response.")
            }
            document = try JSONDecoder().decode(IOSModelCatalogDocument.self, from: data)
        }
        cachedCatalog = document
        return document
    }

    private func productionDeliveryPlan(
        for model: ModelDescriptor,
        matching entry: IOSModelCatalogEntry
    ) async throws -> ProductionModelCatalog.ArtifactDeliveryPlan {
        let catalog: ProductionModelCatalog
        if let cachedProductionCatalog {
            catalog = cachedProductionCatalog
        } else {
            guard let url = Bundle.main.url(
                forResource: "qwenvoice_production_model_catalog",
                withExtension: "json"
            ) else {
                throw ProductionModelCatalog.Error.unreadable(
                    "Bundled production model catalog is missing."
                )
            }
            catalog = try ProductionModelCatalog(contentsOf: url)
            cachedProductionCatalog = catalog
        }
        let artifact = try catalog.artifactMatchingDescriptor(
            platform: .iOS,
            folder: model.folder,
            repo: model.huggingFaceRepo,
            revision: model.huggingFaceRevision,
            artifactVersion: model.artifactVersion,
            estimatedDownloadBytes: model.estimatedDownloadBytes,
            requiredRelativePaths: model.requiredRelativePaths
        )
        let productionFiles = Dictionary(uniqueKeysWithValues: artifact.files.map {
            ($0.relativePath, ($0.sizeBytes, $0.sha256))
        })
        guard artifact.totalBytes == entry.totalBytes,
              productionFiles.count == entry.files.count,
              entry.files.allSatisfy({ file in
                  guard let expected = productionFiles[file.relativePath] else { return false }
                  return expected.0 == file.sizeBytes && expected.1 == file.sha256
              }) else {
            throw ProductionModelCatalog.Error.descriptorMismatch(
                identity: artifact.identity,
                reason: "iPhone delivery catalog differs from the authenticated production catalog"
            )
        }
        let modelsRoot = AppPaths.modelsDir
        return try await Task.detached(priority: .utility) {
            try catalog.deliveryPlan(for: artifact, modelsRoot: modelsRoot)
        }.value
    }

    private func makeLedgerRequest(
        model: ModelDescriptor,
        entry: IOSModelCatalogEntry,
        totalBytes: Int64
    ) -> IOSModelDownloadLedger.Request {
        IOSModelDownloadLedger.Request(
            logicalRequestID: UUID().uuidString,
            modelID: model.id,
            artifactVersion: model.artifactVersion,
            repo: model.huggingFaceRepo,
            revision: model.huggingFaceRevision ?? "main",
            targetFolder: model.installDirectory(in: AppPaths.modelsDir).lastPathComponent,
            expectedFiles: entry.files.map(\.relativePath).sorted(),
            verifiedFiles: [],
            retryCount: 0,
            receivedBytes: 0,
            totalBytes: totalBytes,
            status: .queued
        )
    }

    private func prepareDirectories() throws {
        for directory in [
            AppPaths.modelsDir,
            AppPaths.modelDownloadRootDir,
            AppPaths.modelDownloadStagingDir,
            AppPaths.modelDownloadDelegateFilesDir,
            AppPaths.modelDownloadDiagnosticsDir,
        ] {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            try? IOSModelDeliverySupport.excludeFromBackup(directory)
        }
    }

    private func stagingRoot(modelID: String) -> URL {
        AppPaths.modelDownloadStagingDir.appendingPathComponent(modelID, isDirectory: true)
    }

    private func discardStaging(modelID: String) {
        try? fileManager.removeItem(at: stagingRoot(modelID: modelID))
    }

    @discardableResult
    private func persistProgressIfNeeded(
        modelID: String,
        status: IOSModelDownloadLedger.Status,
        bytes: Int64,
        retryCount: Int
    ) -> Bool {
        guard !cancellationBarriers.contains(modelID) else { return false }
        do {
            var ledger = try ledgerStore.load()
            guard let index = ledger.requests.firstIndex(where: { $0.modelID == modelID }) else {
                return false
            }
            let durableStatus = ledger.requests[index].status
            guard durableStatus != .cancelRequested, durableStatus != .deleted else {
                cancellationBarriers.insert(modelID)
                return false
            }

            let now = ProcessInfo.processInfo.systemUptime
            let last = lastLedgerProgressWrite[modelID] ?? 0
            guard now - last >= 0.5 || status != .downloading else { return true }
            ledger.requests[index].status = status
            ledger.requests[index].receivedBytes = max(ledger.requests[index].receivedBytes, bytes)
            ledger.requests[index].retryCount = max(ledger.requests[index].retryCount, retryCount)
            try ledgerStore.save(ledger)
            lastLedgerProgressWrite[modelID] = now
            return true
        } catch {
            diagnosticsStore.recordFailure(classification: "ledger-write", message: error.localizedDescription)
            return false
        }
    }

    private func recordVerifiedFile(_ receipt: VerifiedArtifactReceipt) {
        guard let modelID = inflight.values.first?.modelID else { return }
        updateLedger(modelID: modelID) { request in
            request.verifiedFiles.removeAll { $0.relativePath == receipt.relativePath }
            request.verifiedFiles.append(.init(
                relativePath: receipt.relativePath,
                expectedSize: receipt.expectedSize,
                sha256: receipt.expectedSHA256
            ))
            request.verifiedFiles.sort { $0.relativePath < $1.relativePath }
        }
    }

    private func updateLedger(
        modelID: String,
        mutate: (inout IOSModelDownloadLedger.Request) -> Void
    ) {
        do {
            try persistLedgerUpdate(modelID: modelID, mutate: mutate)
        } catch {
            diagnosticsStore.recordFailure(classification: "ledger-write", message: error.localizedDescription)
        }
    }

    /// Critical cancellation transitions use this throwing path. Best-effort
    /// ledger updates are acceptable for progress diagnostics, but never for a
    /// state that authorizes task cancellation or destructive staging cleanup.
    private func persistLedgerUpdate(
        modelID: String,
        mutate: (inout IOSModelDownloadLedger.Request) -> Void
    ) throws {
        var ledger = try ledgerStore.load()
        guard ledger.requests.contains(where: { $0.modelID == modelID }) else {
            throw IOSModelDownloadLedgerError.invalidDocument
        }
        updateRequest(modelID, in: &ledger, mutate: mutate)
        try ledgerStore.save(ledger)
    }

    private func persistCancellationStatus(
        modelID: String,
        status: IOSModelDownloadLedger.Status
    ) -> Bool {
        do {
            try persistLedgerUpdate(modelID: modelID) { $0.status = status }
            return true
        } catch {
            diagnosticsStore.recordFailure(
                classification: "cancellation-ledger-write",
                message: error.localizedDescription
            )
            return false
        }
    }

    private func publishCancellationPersistenceFailure(
        modelID: String,
        recoverableGeneration: UInt64? = nil
    ) {
        publishSnapshot(
            modelID: modelID,
            phase: .failed,
            downloadedBytes: ledgerReceivedBytes(modelID: modelID),
            totalBytes: inflight[modelID]?.totalBytes
                ?? modelAssetStore.descriptor(id: modelID)?.model.estimatedDownloadBytes,
            message: CancellationPersistenceError.privacySafeMessage,
            generation: recoverableGeneration ?? beginOperation()
        )
    }

    /// The transfer may cross its synchronous atomic-install boundary just as
    /// cancellation arrives. Never tombstone that request while leaving a
    /// newly installed target behind.
    private func rollbackRacedInstallationIfNeeded(_ active: InFlightDownload) -> Bool {
        guard !active.targetWasAvailableAtStart,
              let model = modelAssetStore.descriptor(id: active.modelID)?.model,
              model.isAvailable(in: AppPaths.modelsDir, fileManager: fileManager) else {
            return true
        }
        do {
            try SharedModelComponentStore(modelsRoot: AppPaths.modelsDir).deleteModel(
                modelFolder: active.targetDir.lastPathComponent
            )
            return true
        } catch {
            diagnosticsStore.recordFailure(
                classification: "cancellation-install-rollback",
                message: error.localizedDescription
            )
            return false
        }
    }

    /// If rollback cannot remove a target that completed during cancellation,
    /// make the installed state durable before exposing it. A failed ledger
    /// write must never produce a false terminal-success snapshot.
    private func reconcileInstalledAfterCancellationCleanupFailure(_ active: InFlightDownload) {
        do {
            try persistLedgerUpdate(modelID: active.modelID) { request in
                request.status = .installed
                request.receivedBytes = max(request.receivedBytes, active.totalBytes)
                request.totalBytes = max(request.totalBytes, active.totalBytes)
            }
            cancellationBarriers.remove(active.modelID)
            publishSnapshot(
                modelID: active.modelID,
                phase: .installed,
                downloadedBytes: active.totalBytes,
                totalBytes: active.totalBytes,
                message: nil,
                generation: beginOperation()
            )
        } catch {
            diagnosticsStore.recordFailure(
                classification: "cancellation-install-reconcile",
                message: error.localizedDescription
            )
            publishSnapshot(
                modelID: active.modelID,
                phase: .failed,
                downloadedBytes: active.totalBytes,
                totalBytes: active.totalBytes,
                message: CancellationInstallReconciliationError.privacySafeMessage,
                generation: beginOperation()
            )
        }
    }

    /// A completion can win the race with a user's Cancel tap. Re-publish the
    /// durable/current outcome instead of leaving an optimistic UI state behind.
    private func reconcileNoOpCancellation(modelID: String) {
        let durableStatus = try? ledgerStore.load().requests
            .first(where: { $0.modelID == modelID })?.status
        if durableStatus == .cancelRequested || durableStatus == .deleted {
            publishTerminal(modelID: modelID, phase: .deleted)
            return
        }
        if let model = modelAssetStore.descriptor(id: modelID)?.model,
           model.isAvailable(in: AppPaths.modelsDir, fileManager: fileManager) {
            publishSnapshot(
                modelID: modelID,
                phase: .installed,
                downloadedBytes: model.estimatedDownloadBytes ?? 0,
                totalBytes: model.estimatedDownloadBytes,
                message: nil,
                generation: beginOperation()
            )
            return
        }
        publishFailed(
            modelID: modelID,
            message: "No active model download was found. Retry to start a new download."
        )
    }

    private func updateRequest(
        _ modelID: String,
        in ledger: inout IOSModelDownloadLedger,
        mutate: (inout IOSModelDownloadLedger.Request) -> Void
    ) {
        guard let index = ledger.requests.firstIndex(where: { $0.modelID == modelID }) else { return }
        mutate(&ledger.requests[index])
    }

    private func ledgerRequest(
        _ modelID: String,
        in ledger: IOSModelDownloadLedger
    ) -> IOSModelDownloadLedger.Request? {
        ledger.requests.first(where: { $0.modelID == modelID })
    }

    private func ledgerReceivedBytes(modelID: String) -> Int64 {
        (try? ledgerStore.load().requests.first(where: { $0.modelID == modelID })?.receivedBytes) ?? 0
    }

    private func markLedgerTerminal(
        modelID: String,
        status: IOSModelDownloadLedger.Status,
        receivedBytes: Int64? = nil
    ) {
        updateLedger(modelID: modelID) {
            $0.status = status
            if let receivedBytes { $0.receivedBytes = receivedBytes }
        }
    }

    private func beginOperation() -> UInt64 {
        operationGeneration += 1
        return operationGeneration
    }

    private func publishSnapshot(
        for model: ModelDescriptor,
        phase: IOSModelDeliverySnapshot.Phase,
        downloadedBytes: Int64
    ) {
        publishSnapshot(
            modelID: model.id,
            phase: phase,
            downloadedBytes: downloadedBytes,
            totalBytes: model.estimatedDownloadBytes,
            message: nil,
            generation: beginOperation(),
            estimatedBytes: model.estimatedDownloadBytes
        )
    }

    private func publishSnapshot(
        modelID: String,
        phase: IOSModelDeliverySnapshot.Phase,
        downloadedBytes: Int64,
        totalBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        retryCount: Int = 0,
        message: String?,
        generation: UInt64,
        estimatedBytes: Int64? = nil
    ) {
        snapshotSink(.init(
            modelID: modelID,
            phase: phase,
            downloadedBytes: downloadedBytes,
            totalBytes: totalBytes,
            estimatedBytes: estimatedBytes ?? modelAssetStore.descriptor(id: modelID)?.model.estimatedDownloadBytes,
            bytesPerSecond: bytesPerSecond,
            estimatedSecondsRemaining: estimatedSecondsRemaining,
            retryCount: retryCount,
            message: message,
            operationGeneration: generation
        ))
    }

    private func publishTerminal(modelID: String, phase: IOSModelDeliverySnapshot.Phase) {
        publishSnapshot(
            modelID: modelID,
            phase: phase,
            downloadedBytes: 0,
            totalBytes: nil,
            message: nil,
            generation: beginOperation()
        )
    }

    private func publishFailed(modelID: String, message: String) {
        publishSnapshot(
            modelID: modelID,
            phase: .failed,
            downloadedBytes: ledgerReceivedBytes(modelID: modelID),
            totalBytes: modelAssetStore.descriptor(id: modelID)?.model.estimatedDownloadBytes,
            message: message,
            generation: beginOperation()
        )
    }

    private func migrateV1IfNeeded() async throws {
        let legacyURL = AppPaths.iosInFlightDownloadsFile
        guard fileManager.fileExists(atPath: legacyURL.path) else { return }
        let data = try Data(contentsOf: legacyURL)
        let legacy = try JSONDecoder().decode(IOSLegacyInFlightDownloadsDocument.self, from: data)
        guard legacy.schemaVersion == 1 else {
            throw IOSModelDownloadLedgerError.unsupportedSchema(legacy.schemaVersion)
        }

        var ledger = try ledgerStore.load()
        for record in legacy.downloads {
            let legacyConfig = URLSessionConfiguration.background(
                withIdentifier: record.backgroundSessionIdentifier
            )
            let legacySession = URLSession(configuration: legacyConfig)
            let tasks = await withCheckedContinuation { continuation in
                legacySession.getAllTasks { continuation.resume(returning: $0) }
            }
            await withTaskGroup(of: Void.self) { group in
                for case let task as URLSessionDownloadTask in tasks {
                    group.addTask {
                        await withCheckedContinuation { continuation in
                            task.cancel { _ in continuation.resume() }
                        }
                    }
                }
            }
            guard await waitUntilSessionIsEmpty(legacySession) else {
                legacySession.invalidateAndCancel()
                throw IOSModelDownloadLedgerError.invalidDocument
            }
            legacySession.finishTasksAndInvalidate()

            guard let descriptor = modelAssetStore.descriptor(id: record.modelID)?.model,
                  descriptor.artifactVersion == record.artifactVersion,
                  let entry = try? IOSModelDeliverySupport.matchingCatalogEntry(
                    for: descriptor,
                    in: try await fetchCatalog(),
                    configuration: configuration
                  ) else { continue }
            try migrateLegacyStagingIfPresent(record: record)
            if !ledger.requests.contains(where: { $0.modelID == record.modelID }) {
                ledger.requests.append(makeLedgerRequest(
                    model: descriptor,
                    entry: entry,
                    totalBytes: record.totalBytes
                ))
            }
        }
        try ledgerStore.save(ledger)
        try fileManager.removeItem(at: legacyURL)
    }

    private func waitUntilSessionIsEmpty(_ session: URLSession) async -> Bool {
        for _ in 0..<100 {
            let tasks = await withCheckedContinuation { continuation in
                session.getAllTasks { continuation.resume(returning: $0) }
            }
            if tasks.isEmpty { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return false
    }

    /// Move recoverable v1 partials into the single v2 staging hierarchy. Conflicting files are
    /// retained under `legacy-conflicts` for a clean revalidation instead of being discarded or
    /// trusted without hashing.
    private func migrateLegacyStagingIfPresent(record: IOSLegacyInFlightDownloadRecord) throws {
        let targetName = URL(fileURLWithPath: record.targetFolderPath).lastPathComponent
        guard !targetName.isEmpty else { return }
        let legacyRoot = AppPaths.modelsDir
            .appendingPathComponent(".qwenvoice-downloads", isDirectory: true)
            .appendingPathComponent(targetName, isDirectory: true)
        guard fileManager.fileExists(atPath: legacyRoot.path) else { return }

        let destinationRoot = AppPaths.modelDownloadStagingDir
            .appendingPathComponent(record.modelID, isDirectory: true)
        try fileManager.createDirectory(at: destinationRoot, withIntermediateDirectories: true)
        guard let enumerator = fileManager.enumerator(
            at: legacyRoot,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else { return }

        let legacyComponents = legacyRoot.standardizedFileURL.pathComponents
        for case let source as URL in enumerator {
            let values = try source.resourceValues(forKeys: [.isRegularFileKey])
            guard values.isRegularFile == true else { continue }
            let relativeComponents = source.standardizedFileURL.pathComponents
                .dropFirst(legacyComponents.count)
            guard !relativeComponents.isEmpty,
                  !relativeComponents.contains("..") else { continue }
            let relativePath = relativeComponents.joined(separator: "/")
            var destination = destinationRoot.appendingPathComponent(relativePath)
            if fileManager.fileExists(atPath: destination.path) {
                let sourceSize = (try? source.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? -1
                let destinationSize = (try? destination.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? -2
                if sourceSize == destinationSize {
                    try fileManager.removeItem(at: source)
                    continue
                }
                destination = destinationRoot
                    .appendingPathComponent("legacy-conflicts", isDirectory: true)
                    .appendingPathComponent("\(UUID().uuidString)-\(source.lastPathComponent)")
            }
            try fileManager.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try fileManager.moveItem(at: source, to: destination)
        }
        try? fileManager.removeItem(at: legacyRoot)
    }
}
