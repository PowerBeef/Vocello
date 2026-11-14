import Foundation
import Observation
import QwenVoiceCore

@MainActor
@Observable
final class IOSModelInstallerViewModel {
    enum OperationState: Equatable {
        case idle
        case available(estimatedBytes: Int64?)
        /// `message` explains a cancellation that could not be recorded (A5-03).
        case queued(message: String?)
        case waitingForConnectivity(downloadedBytes: Int64, totalBytes: Int64?)
        case downloading(
            progress: Double?, downloadedBytes: Int64, totalBytes: Int64?,
            bytesPerSecond: Int64?, estimatedSecondsRemaining: Double?, message: String?
        )
        case retrying(
            progress: Double?, downloadedBytes: Int64, totalBytes: Int64?,
            retryCount: Int, reason: String?
        )
        case verifying
        case installing
        case cancelling
        case installed
        case deleting
        case unavailable(String)
        case failed(String)
    }

    /// RF-59: the alert that asks once before the model update downloads (Guideline 4.2.3(ii)).
    struct ModelUpdatePrompt: Equatable {
        let modelIDs: [String]
        let totalBytes: Int64
        /// The phone lacks space to keep the earlier models meanwhile, so they go first.
        let makesRoomFirst: Bool
    }

    private(set) var states: [String: OperationState] = [:]
    private(set) var modelUpdatePrompt: ModelUpdatePrompt?
    /// RF-59: the recorded update plan, reloaded where it can change (never read in a view body).
    private(set) var updatePlan: ModelUpdatePlan = .empty
    /// RF-59: set once every mode's update is done in this session; the banner shows the space the
    /// earlier models freed until dismissed.
    private(set) var modelUpdateCompletion: Int64?
    @ObservationIgnored private var modelUpdateFreedBytes: Int64 = 0
    @ObservationIgnored private var sessionHadModelUpdate = false
    /// The modes the plan held at launch: the banner counts the finished ones against them.
    @ObservationIgnored private var sessionUpdateModeCount = 0
    /// Modes stopped this session, honored even when the ledger could not record it.
    @ObservationIgnored private var sessionPausedModes = Set<GenerationMode>()
    /// A model whose removal the engine refused because it was busy; the Voice
    /// Models screen explains it in the localized busy alert (A5-01).
    private(set) var blockedDeletionModelID: String?

    private let modelAssetStore: LocalModelAssetStore?
    private let modelManager: ModelManagerViewModel
    /// The in-process engine a model removal coordinates with (A5-01), as on macOS.
    @ObservationIgnored private weak var engine: (any ModelDeletionEngineCoordinating)?
    private let backgroundSessionIdentifier: String
    private let diagnosticsStore: ModelDownloadDiagnosticsStore
    @ObservationIgnored private var coordinator: IOSModelDownloadCoordinator?
    @ObservationIgnored private var lastAcceptedGeneration: [String: UInt64] = [:]
    @ObservationIgnored private var lastDiagnosticSnapshotTrace:
        [String: (uptime: TimeInterval, phase: IOSModelDeliverySnapshot.Phase, bytes: Int64)] = [:]

    init(
        modelAssetStore: LocalModelAssetStore?,
        modelManager: ModelManagerViewModel,
        engine: (any ModelDeletionEngineCoordinating)?
    ) {
        self.modelAssetStore = modelAssetStore
        self.modelManager = modelManager
        self.engine = engine
        let deliveryConfiguration = IOSModelDeliveryConfiguration.default()
        self.backgroundSessionIdentifier = deliveryConfiguration.backgroundSessionIdentifier
        self.diagnosticsStore = ModelDownloadDiagnosticsStore(
            directory: AppPaths.modelDownloadDiagnosticsDir,
            mirrorDirectory: IOSPullableDiagnosticsMirror.pullableRoot?
                .appendingPathComponent("model-downloads", isDirectory: true)
        )

        guard let modelAssetStore else {
            return
        }

        let coordinator = IOSModelDownloadCoordinator(
            modelAssetStore: modelAssetStore,
            configuration: deliveryConfiguration,
            snapshotSink: { [weak self] snapshot in
                self?.apply(snapshot)
            }
        )
        self.coordinator = coordinator

        updatePlan = modelAssetStore.modelUpdatePlan()
        sessionHadModelUpdate = !updatePlan.isEmpty
        sessionUpdateModeCount = updatePlan.modes.count
        Task {
            await refreshModelInventory(modelID: nil, event: "initial-refresh")
            await coordinator.restoreInFlightDownloadsIfNeeded()
            // RF-59: strictly after the restore, so a resumed request is seen as running.
            await startModelUpdateIfNeeded()
        }
    }

    // MARK: - Model update (RF-59)

    /// The models the update still has to install, one per mode in the plan.
    private func modelUpdateCandidates() -> [TTSModel] {
        TTSModel.all.filter { updatePlan.needsUpdate($0.mode) && !modelManager.isAvailable($0) }
    }

    /// The consent covers exactly the artifacts the user agreed to download, never a later set.
    private static func consentKey(_ model: TTSModel) -> String {
        "\(model.id)@\(model.artifactVersion)"
    }

    /// Disk facts the launch decision reads, gathered off the main actor.
    private struct UpdateDiskFacts: Sendable {
        let plan: ModelUpdatePlan
        let availableBytes: Int64?
        let holdsEarlierModels: Bool
    }

    /// At launch: asks once, then resumes on its own (`IOSModelUpdateAutoStartPolicy`).
    func startModelUpdateIfNeeded() async {
        guard let modelAssetStore else { return }
        let facts = await IOSBackgroundTime.hold("vocello.model-update.launch") {
            await Task.detached(priority: .utility) { @concurrent in
            UpdateDiskFacts(
                plan: modelAssetStore.modelUpdatePlan(),
                availableBytes: (try? modelAssetStore.rootDirectory.resourceValues(
                    forKeys: [.volumeAvailableCapacityForImportantUsageKey]
                ).volumeAvailableCapacityForImportantUsage).map { Int64($0) },
                holdsEarlierModels: !RetiredModelReclamation.presentFolders(
                    of: modelAssetStore.descriptors.map(\.model), in: modelAssetStore.rootDirectory
                ).isEmpty
            )
            }.value
        }
        updatePlan = facts.plan
        let models = modelUpdateCandidates()
        let candidates = models.map { model in
            IOSModelUpdateAutoStartPolicy.Candidate(
                modelID: model.id,
                estimatedBytes: model.estimatedDownloadBytes ?? 0,
                mode: model.mode,
                plan: updatePlan,
                pausedThisSession: sessionPausedModes.contains(model.mode),
                transferring: isTransferring(states[model.id]),
                // NET-1: a failed update waits for the user's Retry; a launch never restarts it.
                failedThisSession: { if case .failed = states[model.id] { return true }; return false }()
            )
        }
        guard !candidates.isEmpty else { return }
        let consented = Set(IOSAppDefaults.modelUpdateConsentedArtifacts)
        // Only the models this launch would start must be covered by the consent.
        let ready = zip(models, candidates).filter { !$1.paused && !$1.active && !$1.failed }.map(\.0)
        let network = await NetworkPathCost.current()
        let decision = IOSModelUpdateAutoStartPolicy.decide(
            candidates: candidates,
            consented: ready.allSatisfy { consented.contains(Self.consentKey($0)) },
            lowDataMode: network.isConstrained,
            availableBytes: facts.availableBytes,
            holdsEarlierModels: facts.holdsEarlierModels
        )
        switch decision {
        case .none:
            return
        case .ask(let modelIDs, let totalBytes, let makesRoomFirst):
            modelUpdatePrompt = ModelUpdatePrompt(modelIDs: modelIDs, totalBytes: totalBytes, makesRoomFirst: makesRoomFirst)
        case .start(let modelIDs):
            await runModelUpdate(modelIDs: modelIDs, makingRoomFirst: false)
        }
    }

    /// The alert's Update, with the prompt the alert presented (SwiftUI may clear the binding
    /// before the action runs). The consent names these artifacts, for later launches.
    func confirmModelUpdate(_ prompt: ModelUpdatePrompt) {
        modelUpdatePrompt = nil
        let models = TTSModel.all.filter { prompt.modelIDs.contains($0.id) }
        IOSAppDefaults.modelUpdateConsentedArtifacts = Array(
            Set(IOSAppDefaults.modelUpdateConsentedArtifacts).union(models.map(Self.consentKey))
        ).sorted()
        Task { await runModelUpdate(modelIDs: prompt.modelIDs, makingRoomFirst: prompt.makesRoomFirst) }
    }

    /// The alert's Later: those modes stop, so no later launch asks again; their rows and Studio
    /// keep offering the update.
    func postponeModelUpdate(_ prompt: ModelUpdatePrompt?) {
        modelUpdatePrompt = nil
        guard let prompt else { return }
        Task {
            for model in TTSModel.all where prompt.modelIDs.contains(model.id) {
                await changeModelUpdatePlan(.pause(model.mode))
            }
        }
    }

    func dismissModelUpdateCompletion() {
        modelUpdateCompletion = nil
    }

    private func runModelUpdate(modelIDs: [String], makingRoomFirst: Bool) async {
        guard let modelAssetStore else { return }
        if makingRoomFirst {
            let result = await IOSBackgroundTime.hold("vocello.model-update.make-room") {
                await Task.detached(priority: .userInitiated) { @concurrent in
                    modelAssetStore.removeRetiredFoldersBeforeUpdate()
                }.value
            }
            modelUpdateFreedBytes += result.freedBytes
        }
        for model in TTSModel.all where modelIDs.contains(model.id) {
            if let change = updatePlan.changeBeforeUpdating(model.mode) {
                await changeModelUpdatePlan(change)
            }
            install(model)
        }
    }

    /// Writes `change` off the main actor. A pause that cannot be recorded is still honored for
    /// this session, and the failure is recorded.
    private func changeModelUpdatePlan(_ change: ModelUpdateLedger.Change) async {
        guard let modelAssetStore else { return }
        let outcome: Result<ModelUpdatePlan, any Error> = await IOSBackgroundTime.hold("vocello.model-update.plan") {
            await Task.detached(priority: .userInitiated) { @concurrent in
                Result { try modelAssetStore.reconcileModelUpdatePlan(change: change) }
            }.value
        }
        switch outcome {
        case .success(let plan):
            updatePlan = plan
        case .failure(let error):
            diagnosticsStore.recordFailure(classification: "model-update-plan", error: error)
        }
        switch change {
        case .pause(let mode): sessionPausedModes.insert(mode)
        case .resume(let mode): sessionPausedModes.remove(mode)
        case .resumeAll: sessionPausedModes.removeAll()
        case .none, .recordFailure: break
        }
    }

    /// After a verified install: every retired folder goes once one new model is in place; the
    /// update pins go once no update download is left; the done note follows the last mode.
    private func reclaimAfterInstall() async {
        await IOSBackgroundTime.hold("vocello.model-update.reclaim") { await reclaimAfterInstallHoldingTime() }
    }

    private func reclaimAfterInstallHoldingTime() async {
        guard let modelAssetStore else { return }
        let updateStillDownloading = TTSModel.all.contains {
            updatePlan.needsUpdate($0.mode) && isTransferring(states[$0.id])
        }
        let result = await Task.detached(priority: .utility) { @concurrent in
            let result = modelAssetStore.reclaimRetiredFolders()
            if !updateStillDownloading { modelAssetStore.releaseModelUpdatePins() }
            return result
        }.value
        modelUpdateFreedBytes += result.freedBytes
        await modelManager.refresh()
        updatePlan = await Task.detached(priority: .utility) { @concurrent in
            modelAssetStore.modelUpdatePlan()
        }.value
        if sessionHadModelUpdate, updatePlan.isEmpty, modelUpdateCompletion == nil {
            sessionHadModelUpdate = false
            modelUpdateCompletion = modelUpdateFreedBytes
            // Nothing is left to update: a later set of models asks again.
            IOSAppDefaults.modelUpdateConsentedArtifacts = []
        }
    }

    /// RF-59: the banner's progress while the update runs: the modes updated since launch, of
    /// those plus the ones still updating (a mode the user stopped is not counted).
    var modelUpdateProgress: (completed: Int, total: Int)? {
        let state = ModelUpdateBannerState.derive(
            remaining: modelUpdateCandidates().map { model in
                ModelUpdateBannerState.Remaining(
                    paused: updatePlan.isPaused(model.mode) || sessionPausedModes.contains(model.mode),
                    active: isTransferring(states[model.id]), fraction: nil
                )
            },
            sessionModeCount: sessionUpdateModeCount, completionFreedBytes: nil, needsRoom: false
        )
        guard case .updating(let completed, let total, _) = state else { return nil }
        return (completed, total)
    }

    private func isTransferring(_ state: OperationState?) -> Bool {
        switch state {
        case .queued, .waitingForConnectivity, .downloading, .retrying, .verifying, .installing:
            return true
        default:
            return false
        }
    }


    func state(for model: TTSModel) -> OperationState {
        if let state = states[model.id] {
            return state
        }

        if let unavailableMessage = IOSNativeDeviceFeatureGate.unavailableMessage(for: model) {
            return .unavailable(unavailableMessage)
        }

        switch modelManager.statuses[model.id] {
        case .installed, .updateAvailable:
            return .idle
        case .updateRequired:
            // The row's Update starts a new download: the same eligibility as Install.
            guard let descriptor = modelAssetStore?.descriptor(id: model.id)?.model,
                  IOSNativeDeviceFeatureGate.allowsModelDownloads(for: descriptor) else {
                return .unavailable(IOSInterfaceText.modelUnavailable)
            }
            return .idle
        case .checking:
            return .idle
        case .notInstalled, .none:
            guard let descriptor = modelAssetStore?.descriptor(id: model.id)?.model else {
                return .failed(IOSInterfaceText.missingDescriptor)
            }
            guard IOSNativeDeviceFeatureGate.allowsModelDownloads(for: descriptor) else {
                return .unavailable("iPhone download support for this model is not enabled in this build.")
            }
            return .available(estimatedBytes: descriptor.estimatedDownloadBytes)
        case .incomplete(let message, _):
            guard let descriptor = modelAssetStore?.descriptor(id: model.id)?.model else {
                return .failed(message)
            }
            if IOSNativeDeviceFeatureGate.allowsModelDownloads(for: descriptor) {
                // Not a delivery failure: the row's own incomplete branch offers
                // Repair and Remove, so a broken install can always be deleted.
                return .idle
            }
            return .unavailable(IOSInterfaceText.modelUnavailable)
        case .error(let message):
            guard let descriptor = modelAssetStore?.descriptor(id: model.id)?.model else {
                return .failed(message)
            }
            if IOSNativeDeviceFeatureGate.allowsModelDownloads(for: descriptor) {
                return .failed(message)
            }
            return .unavailable(message)
        }
    }

    func install(_ model: TTSModel) {
        if let unavailableMessage = IOSNativeDeviceFeatureGate.unavailableMessage(for: model) {
            states[model.id] = .unavailable(unavailableMessage)
            return
        }
        guard let coordinator else {
            states[model.id] = .failed(IOSInterfaceText.deliveryUnavailable)
            return
        }

        Task {
            do {
                if let change = updatePlan.changeBeforeUpdating(model.mode) {
                    await changeModelUpdatePlan(change)
                }
                try await coordinator.install(model: model)
            } catch {
                let generation = (lastAcceptedGeneration[model.id] ?? 0) + 1
                lastAcceptedGeneration[model.id] = generation
                apply(
                    IOSModelDeliverySnapshot(
                        modelID: model.id,
                        phase: .failed,
                        downloadedBytes: 0,
                        totalBytes: model.estimatedDownloadBytes,
                        estimatedBytes: model.estimatedDownloadBytes,
                        message: error.localizedDescription,
                        operationGeneration: generation
                    )
                )
            }
        }
    }

    func cancel(_ model: TTSModel) {
        guard let coordinator else { return }
        Task {
            // RF-59: a stopped update stays stopped across launches until the user updates again.
            if updatePlan.needsUpdate(model.mode) {
                await changeModelUpdatePlan(.pause(model.mode))
            }
            await coordinator.cancel(modelID: model.id)
            await refreshModelInventory(modelID: model.id, event: "cancel-refresh")
        }
    }

    /// A5-01: never removes files the engine is using, as on macOS
    /// (`ModelDeletionSequence`). A take, a long-form project, or a load, warm or
    /// prime keeps the files and raises the busy alert; unless another model is
    /// loaded the engine is unloaded first, and a refused unload keeps the files.
    func delete(_ model: TTSModel) {
        if IOSNativeDeviceFeatureGate.unavailableMessage(for: model) != nil {
            return
        }
        guard let coordinator else {
            states[model.id] = .failed(IOSInterfaceText.deliveryUnavailable)
            return
        }

        Task {
            var removalError: (any Error)?
            let outcome = await ModelDeletionSequence.run(
                modelID: model.id,
                engine: engine,
                stopDownloads: { await coordinator.stopDownloadBeforeDeletion(modelID: model.id) },
                removeFiles: {
                    do {
                        return try coordinator.removeInstalledFiles(of: model)
                    } catch {
                        removalError = error
                        return false
                    }
                },
                unloadFailed: { error in
                    diagnosticsStore.recordFailure(classification: "delete-unload", error: error)
                }
            )
            switch outcome {
            case .deleted:
                await refreshModelInventory(modelID: model.id, event: "delete-refresh")
                states.removeValue(forKey: model.id)
            case .blockedByActiveGeneration, .failed(.engineRelease):
                // The files are intact; the busy alert says why.
                diagnosticsStore.recordEvent(
                    layer: "view-model",
                    event: "delete-blocked",
                    modelID: model.id,
                    outcome: "engine-busy"
                )
                blockedDeletionModelID = model.id
            case .failed(.downloadStop):
                // The model's download could not be cancelled durably, so its
                // files stay; the coordinator already published the row's state.
                break
            case .failed(.fileRemoval):
                // Without an error the files were kept for a download that started
                // meanwhile, which the row shows.
                guard let removalError else { return }
                let generation = (lastAcceptedGeneration[model.id] ?? 0) + 1
                lastAcceptedGeneration[model.id] = generation
                apply(
                    IOSModelDeliverySnapshot(
                        modelID: model.id,
                        phase: .failed,
                        downloadedBytes: 0,
                        totalBytes: nil,
                        estimatedBytes: model.estimatedDownloadBytes,
                        message: removalError.localizedDescription,
                        operationGeneration: generation
                    )
                )
            }
        }
    }

    func dismissBlockedDeletion() {
        blockedDeletionModelID = nil
    }

    @discardableResult
    func handleBackgroundEventsCompletion(
        _ identifier: String,
        _ completionHandler: @escaping () -> Void
    ) -> Bool {
        guard IOSModelDeliveryBackgroundEventRelay.store(
            completionHandler,
            forSessionIdentifier: identifier,
            ownedSessionIdentifier: backgroundSessionIdentifier
        ) else {
            return false
        }
        guard let coordinator else {
            IOSModelDeliveryBackgroundEventRelay.complete(
                forOwnedSessionIdentifier: backgroundSessionIdentifier
            )
            return true
        }
        Task {
            await coordinator.resumeBackgroundEventsIfNeeded()
        }
        return true
    }

    private func apply(_ snapshot: IOSModelDeliverySnapshot) {
        let previousGeneration = lastAcceptedGeneration[snapshot.modelID] ?? 0
        guard snapshot.operationGeneration >= previousGeneration else {
            diagnosticsStore.recordEvent(
                layer: "view-model",
                event: "stale-snapshot-rejected",
                modelID: snapshot.modelID,
                operationGeneration: snapshot.operationGeneration,
                phase: snapshot.phase.rawValue,
                durableBytes: snapshot.downloadedBytes,
                totalBytes: snapshot.totalBytes,
                outcome: "rejected"
            )
            return
        }
        lastAcceptedGeneration[snapshot.modelID] = snapshot.operationGeneration

        switch snapshot.phase {
        case .queued:
            states[snapshot.modelID] = .queued(message: snapshot.message)
        case .waitingForConnectivity:
            states[snapshot.modelID] = .waitingForConnectivity(
                downloadedBytes: snapshot.downloadedBytes,
                totalBytes: snapshot.totalBytes
            )
        case .downloading:
            let progress: Double?
            if let totalBytes = snapshot.totalBytes, totalBytes > 0 {
                progress = min(max(Double(snapshot.downloadedBytes) / Double(totalBytes), 0), 1)
            } else {
                progress = nil
            }
            states[snapshot.modelID] = .downloading(
                progress: progress,
                downloadedBytes: snapshot.downloadedBytes,
                totalBytes: snapshot.totalBytes,
                bytesPerSecond: snapshot.bytesPerSecond,
                estimatedSecondsRemaining: snapshot.estimatedSecondsRemaining,
                message: snapshot.message
            )
        case .retrying:
            let progress: Double?
            if let totalBytes = snapshot.totalBytes, totalBytes > 0 {
                progress = min(max(Double(snapshot.downloadedBytes) / Double(totalBytes), 0), 1)
            } else {
                progress = nil
            }
            states[snapshot.modelID] = .retrying(
                progress: progress,
                downloadedBytes: snapshot.downloadedBytes,
                totalBytes: snapshot.totalBytes,
                retryCount: snapshot.retryCount,
                reason: snapshot.message
            )
        case .verifying:
            states[snapshot.modelID] = .verifying
        case .installing:
            states[snapshot.modelID] = .installing
        case .cancelling:
            states[snapshot.modelID] = .cancelling
        case .installed:
            states[snapshot.modelID] = .installed
            let modelID = snapshot.modelID
            Task {
                await refreshModelInventory(modelID: modelID, event: "installed-refresh")
                await reclaimAfterInstall()
            }
        case .deleting:
            states[snapshot.modelID] = .deleting
        case .failed:
            states[snapshot.modelID] = .failed(snapshot.message ?? IOSInterfaceText.deliveryFailed)
            let failedModel = TTSModel.all.first { $0.id == snapshot.modelID }
            let failure = ModelUpdateFailure.classify(description: snapshot.message ?? "")
            Task {
                // RF-59: a failed update waits for the user's Retry; no launch restarts it.
                if let failedModel, let change = updatePlan.changeAfterFailure(failedModel.mode, failure) {
                    await changeModelUpdatePlan(change)
                }
                await refreshModelInventory(modelID: snapshot.modelID, event: "failed-refresh")
            }
        case .deleted:
            states.removeValue(forKey: snapshot.modelID)
            lastAcceptedGeneration.removeValue(forKey: snapshot.modelID)
            Task {
                await refreshModelInventory(modelID: snapshot.modelID, event: "deleted-refresh")
            }
        }
        let now = ProcessInfo.processInfo.systemUptime
        let previousTrace = lastDiagnosticSnapshotTrace[snapshot.modelID]
        if previousTrace == nil
            || previousTrace?.phase != snapshot.phase
            || snapshot.phase == .installed || snapshot.phase == .failed || snapshot.phase == .deleted
            || now - (previousTrace?.uptime ?? 0) >= 5 {
            lastDiagnosticSnapshotTrace[snapshot.modelID] = (
                now,
                snapshot.phase,
                snapshot.downloadedBytes
            )
            diagnosticsStore.recordEvent(
                layer: "view-model",
                event: "snapshot-applied",
                modelID: snapshot.modelID,
                operationGeneration: snapshot.operationGeneration,
                phase: snapshot.phase.rawValue,
                durableBytes: snapshot.downloadedBytes,
                totalBytes: snapshot.totalBytes,
                outcome: "applied"
            )
        }
    }

    private func refreshModelInventory(modelID: String?, event: String) async {
        // The refresh reconciles the update plan under its file lock, possibly while in the background.
        await IOSBackgroundTime.hold("vocello.model-inventory.refresh") { await modelManager.refresh() }
        let targetAvailable = modelID.flatMap { id in
            TTSModel.all.first(where: { $0.id == id }).map(modelManager.isAvailable)
        }
        diagnosticsStore.recordEvent(
            layer: "model-manager",
            event: event,
            modelID: modelID,
            targetAvailable: targetAvailable,
            outcome: "completed"
        )
    }
}
