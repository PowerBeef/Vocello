import Foundation
import QwenVoiceCore

@MainActor
final class IOSModelInstallerViewModel: ObservableObject {
    enum OperationState: Equatable {
        case idle
        case available(estimatedBytes: Int64?)
        case queued
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

    @Published private(set) var states: [String: OperationState] = [:]

    private let modelAssetStore: LocalModelAssetStore?
    private let modelManager: ModelManagerViewModel
    private let backgroundSessionIdentifier: String
    private let diagnosticsStore: ModelDownloadDiagnosticsStore
    private var coordinator: IOSModelDownloadCoordinator?
    private var lastAcceptedGeneration: [String: UInt64] = [:]
    private var lastDiagnosticSnapshotTrace:
        [String: (uptime: TimeInterval, phase: IOSModelDeliverySnapshot.Phase, bytes: Int64)] = [:]

    /// Called after a model install completes so the engine can preload it in the background.
    var onModelInstalled: ((_ modelID: String) -> Void)?

    init(
        modelAssetStore: LocalModelAssetStore?,
        modelManager: ModelManagerViewModel
    ) {
        self.modelAssetStore = modelAssetStore
        self.modelManager = modelManager
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

        Task {
            await refreshModelInventory(modelID: nil, event: "initial-refresh")
            await coordinator.restoreInFlightDownloadsIfNeeded()
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
        case .checking:
            return .idle
        case .notInstalled, .none:
            guard let descriptor = modelAssetStore?.descriptor(id: model.id)?.model else {
                return .failed("Missing model descriptor.")
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
                return .failed(message)
            }
            return .unavailable("This model is not available on iPhone yet, and the local files are incomplete.")
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
            states[model.id] = .failed("Model delivery is unavailable in this runtime.")
            return
        }

        Task {
            do {
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
            await coordinator.cancel(modelID: model.id)
            await refreshModelInventory(modelID: model.id, event: "cancel-refresh")
        }
    }

    func delete(_ model: TTSModel) {
        if IOSNativeDeviceFeatureGate.unavailableMessage(for: model) != nil {
            return
        }
        guard let coordinator else {
            states[model.id] = .failed("Model delivery is unavailable in this runtime.")
            return
        }

        Task {
            do {
                try await coordinator.delete(model: model)
                await refreshModelInventory(modelID: model.id, event: "delete-refresh")
                states.removeValue(forKey: model.id)
            } catch {
                let generation = (lastAcceptedGeneration[model.id] ?? 0) + 1
                lastAcceptedGeneration[model.id] = generation
                apply(
                    IOSModelDeliverySnapshot(
                        modelID: model.id,
                        phase: .failed,
                        downloadedBytes: 0,
                        totalBytes: nil,
                        estimatedBytes: model.estimatedDownloadBytes,
                        message: error.localizedDescription,
                        operationGeneration: generation
                    )
                )
            }
        }
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
            states[snapshot.modelID] = .queued
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
                onModelInstalled?(modelID)
            }
        case .deleting:
            states[snapshot.modelID] = .deleting
        case .failed:
            states[snapshot.modelID] = .failed(snapshot.message ?? "Model delivery failed.")
            Task {
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
        await modelManager.refresh()
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
