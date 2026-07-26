import Foundation
import Observation
import QwenVoiceCore

/// Manages model install state, repairability, download, and delete flows.
@MainActor
@Observable
final class ModelManagerViewModel {

    struct DownloadProgress: Equatable, Sendable {
        enum Phase: String, Equatable, Sendable {
            case queued
            case waitingForConnectivity
            case downloading
            case retrying
            case verifying
            case installing
            case cancelling
        }

        let downloadedBytes: Int64
        let totalBytes: Int64?
        let completedFiles: Int
        let totalFiles: Int?
        let bytesPerSecond: Int64?
        let isStalled: Bool
        let estimatedSecondsRemaining: Double?
        let retryCount: Int
        let statusMessage: String?
        let phase: Phase

        static let initial = DownloadProgress(
            downloadedBytes: 0,
            totalBytes: nil,
            completedFiles: 0,
            totalFiles: nil,
            bytesPerSecond: nil,
            isStalled: false,
            estimatedSecondsRemaining: nil,
            retryCount: 0,
            statusMessage: nil,
            phase: .downloading
        )
    }

    enum ModelStatus: Equatable {
        case checking
        case notDownloaded(message: String?)
        case downloading(progress: DownloadProgress)
        case repairAvailable(sizeBytes: Int, missingRequiredPaths: [String], message: String?)
        case updateAvailable(sizeBytes: Int, stalePaths: [String])
        case downloaded(sizeBytes: Int)
    }

    enum ModelPackageStatusKind: Equatable {
        case checking
        case ready
        case notInstalled
        case needsRepair
        case updateAvailable
        case downloading
    }

    struct ModelPackagePresentation: Equatable {
        let kind: ModelPackageStatusKind
        let label: String
        let detail: String?
    }

    struct ModelSetupSummary: Equatable {
        let installedRecommendedCount: Int
        let totalRecommendedCount: Int

        var text: String {
            if installedRecommendedCount == totalRecommendedCount {
                return "Recommended models ready"
            }
            return "\(installedRecommendedCount) of \(totalRecommendedCount) recommended models installed"
        }
    }

    struct RecommendedSetupProgress: Equatable {
        let completedCount: Int
        let totalCount: Int
        let currentModelID: String?

        var fraction: Double {
            guard totalCount > 0 else { return 0 }
            return Double(completedCount) / Double(totalCount)
        }
    }

    private struct InstallMetadata: Codable, Equatable, Sendable {
        let schemaVersion: Int
        let modelID: String
        let huggingFaceRepo: String
        let huggingFaceRevision: String?
        let completedAtUTC: String
        let resolvedPath: String
        let sizeBytes: Int
        let requiredRelativePaths: [String]
        let downloadedRelativePaths: [String]
        let missingRequiredPaths: [String]

        enum CodingKeys: String, CodingKey {
            case schemaVersion = "schema_version"
            case modelID = "model_id"
            case huggingFaceRepo = "hugging_face_repo"
            case huggingFaceRevision = "hugging_face_revision"
            case completedAtUTC = "completed_at_utc"
            case resolvedPath = "resolved_path"
            case sizeBytes = "size_bytes"
            case requiredRelativePaths = "required_relative_paths"
            case downloadedRelativePaths = "downloaded_relative_paths"
            case missingRequiredPaths = "missing_required_paths"
        }
    }

    private nonisolated static let installMetadataFilename = ".qwenvoice-install-metadata.json"

    /// Bundled production catalog, loaded once for the stale-artifact probe.
    /// A missing/malformed catalog disables update detection only — the
    /// authenticated delivery path still fail-closes any actual download.
    private nonisolated static let productionCatalog: ProductionModelCatalog? = {
        guard let url = Bundle.main.url(
            forResource: "qwenvoice_production_model_catalog",
            withExtension: "json"
        ) else { return nil }
        return try? ProductionModelCatalog(contentsOf: url)
    }()

    private(set) var statuses: [String: ModelStatus] = [:]
    private(set) var modelInfoByID: [String: ModelInfo] = [:]
    private(set) var activeVariantRevision = 0
    private(set) var recommendedSetupProgress: RecommendedSetupProgress?

    private let fileManager: FileManager
    private let modelsDirectory: URL
    /// The user's Mac memory tier, computed once at init and
    /// surfaced for UI surfaces that frame download recommendations.
    let deviceClass: NativeDeviceMemoryClass
    private var downloaders: [String: HuggingFaceDownloader] = [:]
    private var downloadTasks: [String: Task<Void, Never>] = [:]
    private var stateEpochs: [String: Int] = [:]
    private var lastProgressPublishTimes: [String: ContinuousClock.Instant] = [:]
    private var refreshTask: Task<Void, Never>?
    private var recommendedSetupTask: Task<Void, Never>?
    private var lastFailureMessages: [String: String] = [:]
    /// Maximum number of models downloaded at the same time. Each model runs its own
    /// downloader/URLSession (4 concurrent files), so this bounds the total bandwidth
    /// and parallelism across simultaneous downloads.
    private static let maxConcurrentModelDownloads = 2
    /// Model IDs whose download is actively running (has an in-flight URLSession).
    private var inflightModelDownloads = Set<String>()
    /// Models waiting for a download slot, in launch order.
    private var pendingModelDownloads: [TTSModel] = []

    init(
        fileManager: FileManager = .default,
        modelsDirectory: URL = QwenVoiceApp.modelsDir,
        deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass()
    ) {
        self.fileManager = fileManager
        self.modelsDirectory = modelsDirectory
        self.deviceClass = deviceClass

        for model in TTSModel.all {
            let info = localModelInfo(for: model)
            modelInfoByID[model.id] = info
            statuses[model.id] = status(for: info, failureMessage: nil)
        }
    }

    func refresh() async {
        if let refreshTask {
            await refreshTask.value
            return
        }

        let task = Task { @MainActor in
            let interval = AppPerformanceSignposts.begin("Model Status Refresh")
            let wallStart = DispatchTime.now().uptimeNanoseconds
            await performRefresh()
            AppPerformanceSignposts.end(interval)
            if DebugMode.isEnabled {
                let elapsedMs = Int((DispatchTime.now().uptimeNanoseconds - wallStart) / 1_000_000)
                print("[Performance][ModelManagerViewModel] refresh_wall_ms=\(elapsedMs)")
            }
        }

        refreshTask = task
        await task.value
        refreshTask = nil
    }

    func info(for model: TTSModel) -> ModelInfo {
        modelInfoByID[model.id] ?? localModelInfo(for: model)
    }

    func isAvailable(_ model: TTSModel) -> Bool {
        info(for: model).isAvailable
    }

    func isLikelyInstalled(_ model: TTSModel) -> Bool {
        let snapshot = info(for: model)
        return snapshot.downloaded
    }

    func primaryActionTitle(for model: TTSModel) -> String? {
        guard !isAvailable(model) else { return nil }
        return info(for: model).requiresRepair ? "Repair Model" : "Download Model"
    }

    func isActive(_ model: TTSModel) -> Bool {
        activeVariant(for: model.mode)?.id == model.id
    }

    func variant(for mode: GenerationMode, kind: TTSModelVariantKind) -> TTSModel? {
        variants(for: mode).first { $0.variantKind == kind }
    }

    func hasInstalledVariant(for mode: GenerationMode) -> Bool {
        variants(for: mode).contains(where: isAvailable)
    }

    func generationActiveVariant(for mode: GenerationMode) -> TTSModel? {
        if let active = activeVariant(for: mode), isAvailable(active) {
            return active
        }
        return installedFallbackVariant(for: mode)
    }

    func isGenerationVariantSelectable(for mode: GenerationMode, kind: TTSModelVariantKind) -> Bool {
        guard let model = variant(for: mode, kind: kind) else { return false }
        return isAvailable(model)
    }

    @discardableResult
    func reconcileGenerationVariantSelectionIfNeeded(for mode: GenerationMode) -> TTSModel? {
        guard let active = activeVariant(for: mode) else { return nil }
        guard !isAvailable(active) else { return active }
        guard let fallback = installedFallbackVariant(for: mode) else { return active }

        use(fallback)
        return fallback
    }

    /// Returns all active variants for a generation mode in picker order.
    func variants(for mode: GenerationMode) -> [TTSModel] {
        TTSModel.all
            .filter { $0.mode == mode }
            .sorted { lhs, rhs in
                variantSortIndex(lhs.variantKind) < variantSortIndex(rhs.variantKind)
            }
    }

    /// Legacy helper retained for call sites that still need the original
    /// two-package projection. New UI should use `variants(for:)`.
    func pairedVariants(
        for mode: GenerationMode
    ) -> (speed: TTSModel?, quality: TTSModel?) {
        let modelsForMode = TTSModel.all.filter { $0.mode == mode }
        let speed = modelsForMode.first { $0.variantKind == .speed }
        let quality = modelsForMode.first { $0.variantKind == .quality }
        return (speed, quality)
    }

    func activeVariant(for mode: GenerationMode) -> TTSModel? {
        let modeModels = variants(for: mode)
        let recommended = recommendedVariant(for: mode) ?? modeModels.first
        let selectedVariantID = MacModelVariantPreferences.selectedVariantID(
            for: mode,
            defaultVariantID: recommended?.variantID
        )
        return modeModels.first { $0.variantID == selectedVariantID } ?? recommended
    }

    func recommendedVariant(for mode: GenerationMode) -> TTSModel? {
        let modeModels = variants(for: mode)
        for preferredKind in recommendedVariantKinds {
            if let model = modeModels.first(where: { $0.variantKind == preferredKind }) {
                return model
            }
        }
        return modeModels.first { $0.isHardwareRecommended } ?? modeModels.first
    }

    private func installedFallbackVariant(for mode: GenerationMode) -> TTSModel? {
        let candidates = [recommendedVariant(for: mode)].compactMap { $0 } + variants(for: mode)
        var seen = Set<String>()
        return candidates.first { candidate in
            seen.insert(candidate.id).inserted && isAvailable(candidate)
        }
    }

    func isHardwareRecommended(_ model: TTSModel) -> Bool {
        recommendedVariant(for: model.mode)?.id == model.id
    }

    func modelSetupSummary() -> ModelSetupSummary {
        let recommendedModels = GenerationMode.allCases.compactMap(recommendedVariant)
        let readyCount = recommendedModels.filter(isAvailable).count

        return ModelSetupSummary(
            installedRecommendedCount: readyCount,
            totalRecommendedCount: recommendedModels.count
        )
    }

    func recommendedSetupCandidates() -> [TTSModel] {
        GenerationMode.allCases.compactMap { mode in
            guard let recommended = recommendedVariant(for: mode) else { return nil }
            if isAvailable(recommended) {
                return nil
            }
            return recommended
        }
    }

    func packagePresentation(for model: TTSModel) -> ModelPackagePresentation {
        let status = statuses[model.id] ?? .checking

        switch status {
        case .checking:
            return ModelPackagePresentation(
                kind: .checking,
                label: "Checking",
                detail: "Looking for local model files."
            )
        case .notDownloaded(let message):
            return ModelPackagePresentation(
                kind: .notInstalled,
                label: "Not installed",
                detail: message
            )
        case .downloading(let progress):
            return ModelPackagePresentation(
                kind: .downloading,
                label: progress.phase.displayLabel,
                detail: downloadDetail(for: progress)
            )
        case .repairAvailable(_, let missingRequiredPaths, let message):
            return ModelPackagePresentation(
                kind: .needsRepair,
                label: "Needs repair",
                detail: message ?? repairDetail(missingRequiredPaths: missingRequiredPaths)
            )
        case .updateAvailable:
            return ModelPackagePresentation(
                kind: .updateAvailable,
                label: "Update available",
                detail: "A newer model package is pinned. Update to download it."
            )
        case .downloaded:
            return ModelPackagePresentation(
                kind: .ready,
                label: "Ready",
                detail: nil
            )
        }
    }

    func activeVariantLabel(for model: TTSModel) -> String {
        let kind = model.variantKind?.displayName ?? model.name
        let bits = model.variantKind?.bitDepthLabel
        guard let bits, !bits.isEmpty else { return kind }
        return "\(kind) (\(bits))"
    }

    func generationVariantDisplayName(for model: TTSModel) -> String {
        "\(model.name) \(activeVariantLabel(for: model))"
    }

    func generationVariantStatusLabel(for model: TTSModel) -> String {
        let presentation = packagePresentation(for: model)
        switch presentation.kind {
        case .checking:
            return "Checking"
        case .ready:
            return "Ready"
        case .notInstalled:
            return "Download"
        case .needsRepair:
            return "Repair"
        case .updateAvailable:
            return "Update"
        case .downloading:
            return presentation.label
        }
    }

    func modePurpose(for mode: GenerationMode) -> String {
        switch mode {
        case .custom:
            return "Built-in speakers"
        case .design:
            return "Describe a new voice"
        case .clone:
            return "Use a reference clip"
        }
    }

    /// `true` when running this variant on the current Mac is
    /// likely to overrun memory and either fail or thrash badly.
    /// Today the risky combination is the Quality (8-bit)
    /// variant on `.floor8GBMac`. The cached `deviceClass` is
    /// computed once at init from `ProcessInfo.physicalMemory`,
    /// so this lookup stays cheap. If we add a
    /// `recommendedMemoryGB` field to the manifest later, this
    /// is the single seam to extend.
    func isHardwareRisky(_ model: TTSModel) -> Bool {
        guard deviceClass == .floor8GBMac else { return false }
        return model.variantKind == .quality
    }

    private var recommendedVariantKinds: [TTSModelVariantKind] {
        switch deviceClass {
        case .floor8GBMac, .iPhonePro:
            return [.speed, .quality]
        case .mid16GBMac, .highMemoryMac:
            return [.quality, .speed]
        }
    }

    private func variantSortIndex(_ kind: TTSModelVariantKind?) -> Int {
        guard let kind,
              let index = TTSModelVariantKind.allCases.firstIndex(of: kind) else {
            return Int.max
        }
        return index
    }

    /// Localized "1.6 GB" / "3.2 GB" string for model download
    /// controls.
    /// size column. Source of truth depends on install state:
    ///   * `.downloaded` / `.repairAvailable` use the resolved
    ///     `info.sizeBytes` (real on-disk size).
    ///   * `.notDownloaded` falls back to
    ///     `model.estimatedDownloadBytes` from the manifest.
    ///   * `.downloading` is handled by the row's progress
    ///     subview, not this column; returns `nil`.
    ///   * `.checking` returns `nil` (we don't yet know).
    /// Returns `nil` when no source has a value, so the UI can
    /// elide the column instead of rendering an em-dash.
    func sizeText(for model: TTSModel) -> String? {
        switch statuses[model.id] {
        case .downloaded(let sizeBytes),
             .repairAvailable(let sizeBytes, _, _),
             .updateAvailable(let sizeBytes, _):
            guard sizeBytes > 0 else { return nil }
            return Self.formattedFileSize(Int64(sizeBytes))
        case .notDownloaded:
            guard let estimated = model.estimatedDownloadBytes, estimated > 0 else {
                return nil
            }
            return Self.formattedFileSize(estimated)
        case .downloading, .checking, .none:
            return nil
        }
    }

    func setUpRecommendedModels() {
        guard recommendedSetupTask == nil else { return }
        let candidates = recommendedSetupCandidates()
        guard !candidates.isEmpty else { return }

        recommendedSetupProgress = RecommendedSetupProgress(
            completedCount: 0,
            totalCount: candidates.count,
            currentModelID: candidates.first?.id
        )

        recommendedSetupTask = Task { @MainActor [weak self] in
            guard let self else { return }

            // Launch every candidate up front; `startPendingDownloads` caps how many
            // run concurrently. `download(_:)` returns immediately, so this no longer
            // serializes models one at a time.
            for model in candidates {
                guard !Task.isCancelled else { break }
                if !isAvailable(model) {
                    await download(model)
                }
            }

            // Observe completions until every candidate is installed or no longer
            // downloading (installed, failed, or cancelled).
            while !Task.isCancelled {
                let completedCount = candidates.filter { isAvailable($0) }.count
                let activeCount = candidates.filter {
                    !isAvailable($0) && isDownloadActive($0.id)
                }.count
                recommendedSetupProgress = RecommendedSetupProgress(
                    completedCount: completedCount,
                    totalCount: candidates.count,
                    currentModelID: candidates.first { !isAvailable($0) }?.id
                )
                if completedCount >= candidates.count || activeCount == 0 {
                    break
                }
                try? await Task.sleep(for: .milliseconds(400))
            }

            recommendedSetupTask = nil
            recommendedSetupProgress = nil
        }
    }

    func cancelRecommendedSetup() {
        recommendedSetupTask?.cancel()
        // Several candidates can be in flight at once; cancel (discard) them all.
        let candidates = recommendedSetupCandidates()
        Task { [weak self] in
            for model in candidates {
                await self?.cancelDownload(model)
            }
        }
        recommendedSetupTask = nil
        recommendedSetupProgress = nil
    }

    private func downloadDetail(for progress: DownloadProgress) -> String? {
        if progress.isStalled {
            return "No progress for 20 seconds."
        }
        var details: [String] = []
        if let totalBytes = progress.totalBytes, totalBytes > 0 {
            let downloaded = Self.formattedFileSize(progress.downloadedBytes)
            let total = Self.formattedFileSize(totalBytes)
            details.append("\(downloaded) of \(total)")
        } else if let totalFiles = progress.totalFiles, totalFiles > 0 {
            details.append("\(progress.completedFiles) of \(totalFiles) files")
        }
        if let bytesPerSecond = progress.bytesPerSecond, bytesPerSecond > 0,
           progress.phase == .downloading {
            details.append("\(Self.formattedFileSize(bytesPerSecond))/s")
        }
        if let eta = progress.estimatedSecondsRemaining, eta.isFinite,
           progress.phase == .downloading {
            details.append("about \(max(1, Int(eta.rounded())))s remaining")
        }
        if progress.phase == .retrying, progress.retryCount > 0 {
            details.append("retry \(progress.retryCount); verified files will be reused")
        }
        if let statusMessage = progress.statusMessage, !statusMessage.isEmpty {
            details.append(statusMessage)
        }
        return details.isEmpty ? nil : details.joined(separator: " · ")
    }

    private func repairDetail(missingRequiredPaths: [String]) -> String {
        if missingRequiredPaths.isEmpty {
            return "The local model folder is incomplete."
        }
        if missingRequiredPaths.count == 1 {
            return "One required file is missing."
        }
        return "\(missingRequiredPaths.count) required files are missing."
    }

    private nonisolated static func formattedFileSize(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useGB, .useMB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }

    func use(_ model: TTSModel) {
        guard let variantID = model.variantID else { return }
        MacModelVariantPreferences.setSelectedVariantID(variantID, for: model.mode)
        activeVariantRevision += 1
    }

    func recoveryDetail(for model: TTSModel) -> String {
        let snapshot = info(for: model)
        let displayName = generationVariantDisplayName(for: model)
        if snapshot.requiresRepair {
            if !snapshot.missingRequiredPaths.isEmpty {
                return "Some required files are missing. Repair \(displayName) to finish installing it."
            }
            return "The local model files are incomplete. Repair \(displayName) to keep using \(model.mode.displayName)."
        }
        return "Install \(displayName) to enable \(model.mode.displayName)."
    }

    /// Request a model download. Returns immediately; the download runs on the bounded
    /// queue so multiple models download concurrently (up to
    /// `maxConcurrentModelDownloads`). A model already queued or downloading is a no-op.
    func download(_ model: TTSModel) async {
        let modelID = model.id
        guard !isDownloadActive(modelID) else { return }

        lastFailureMessages.removeValue(forKey: modelID)
        statuses[modelID] = .downloading(progress: .initial)
        pendingModelDownloads.append(model)
        startPendingDownloads()
    }

    /// `true` when `modelID` is queued or actively downloading.
    private func isDownloadActive(_ modelID: String) -> Bool {
        inflightModelDownloads.contains(modelID)
            || pendingModelDownloads.contains { $0.id == modelID }
    }

    /// Launch queued downloads until the concurrency cap is reached.
    private func startPendingDownloads() {
        while inflightModelDownloads.count < Self.maxConcurrentModelDownloads,
              let next = pendingModelDownloads.first {
            pendingModelDownloads.removeFirst()
            beginModelDownload(next)
        }
    }

    /// Start one model's download after it has claimed a concurrency slot.
    private func beginModelDownload(_ model: TTSModel) {
        let modelID = model.id
        let downloadPlan: (
            catalog: ProductionModelCatalog,
            artifact: ProductionModelCatalog.Artifact
        )
        do {
            downloadPlan = try TTSContract.productionDownloadPlan(for: model)
        } catch {
            lastFailureMessages[modelID] = error.localizedDescription
            statuses[modelID] = status(
                for: localModelInfo(for: model),
                failureMessage: error.localizedDescription
            )
            startPendingDownloads()
            return
        }
        let epoch = beginEpoch(for: modelID)
        inflightModelDownloads.insert(modelID)

        let targetDir = model.installDirectory(in: modelsDirectory)
        let modelsDirectory = self.modelsDirectory

        // A replacement must not register tasks until the previous downloader's cancellation
        // callbacks have finished. Preserve staging for retry, but serialize session ownership.
        let staleDownloader = downloaders.removeValue(forKey: modelID)
        let staleTask = downloadTasks.removeValue(forKey: modelID)
        staleTask?.cancel()

        try? fileManager.createDirectory(at: modelsDirectory, withIntermediateDirectories: true)
        removeInstallMetadata(for: model)

        let diagnostics = ModelDownloadDiagnosticsStore(
            directory: modelsDirectory
                .deletingLastPathComponent()
                .appendingPathComponent("diagnostics/model-downloads", isDirectory: true)
        )
        let downloader = HuggingFaceDownloader(
            progressHandler: { [weak self] progress in
                diagnostics.record(progress: progress)
                Task { @MainActor [weak self] in
                    self?.publishDownloadProgressIfCurrent(
                        epoch: epoch,
                        modelID: modelID,
                        progress: progress
                    )
                }
            },
            transferMetricsHandler: { diagnostics.record(metrics: $0) },
            artifactURLPolicy: downloadPlan.catalog.downloadURLPolicy
        )
        downloaders[modelID] = downloader

        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            if let staleDownloader {
                await staleDownloader.cancel()
                await staleTask?.value
            }
            let delivery: ProductionModelCatalog.ArtifactDeliveryPlan
            do {
                let catalog = downloadPlan.catalog
                let artifact = downloadPlan.artifact
                delivery = try await Task.detached(priority: .utility) {
                    try catalog.deliveryPlan(for: artifact, modelsRoot: modelsDirectory)
                }.value
            } catch {
                guard self.isCurrentEpoch(epoch, for: modelID) else { return }
                self.lastFailureMessages[modelID] = error.localizedDescription
                await self.handleMutationCompletion(for: modelID)
                return
            }
            await self.runModelDownload(
                model: model,
                epoch: epoch,
                downloader: downloader,
                targetDir: targetDir,
                diagnostics: diagnostics,
                artifact: downloadPlan.artifact,
                delivery: delivery
            )
        }
        downloadTasks[modelID] = task
    }

    /// Runs one model's repo download to completion and reconciles status. The
    /// concurrency slot is released in `handleMutationCompletion` when this returns.
    private func runModelDownload(
        model: TTSModel,
        epoch: Int,
        downloader: HuggingFaceDownloader,
        targetDir: URL,
        diagnostics: ModelDownloadDiagnosticsStore,
        artifact: ProductionModelCatalog.Artifact,
        delivery: ProductionModelCatalog.ArtifactDeliveryPlan
    ) async {
        do {
            try await downloader.downloadFiles(
                delivery.filesToDownload,
                repo: artifact.repo,
                revision: artifact.revision,
                to: targetDir,
                requestIdentity: ModelDownloadRequestIdentity(
                    logicalRequestID: UUID().uuidString,
                    modelID: model.id,
                    artifactVersion: artifact.artifactVersion
                ),
                installedFiles: delivery.installedFiles,
                sharedComponentPlan: delivery.sharedComponentPlan
            )
            guard isCurrentEpoch(epoch, for: model.id) else { return }
            let postDownloadSnapshot = localModelInfo(for: model)
            if !postDownloadSnapshot.complete {
                lastFailureMessages[model.id] = "Download finished, but required model files are still missing."
            } else {
                persistInstallMetadata(for: model, snapshot: postDownloadSnapshot)
                diagnostics.recordSuccess(
                    expectedBytes: model.estimatedDownloadBytes ?? Int64(postDownloadSnapshot.sizeBytes)
                )
            }
        } catch is CancellationError {
            guard isCurrentEpoch(epoch, for: model.id) else { return }
        } catch let dlError as HuggingFaceDownloader.DownloadError {
            guard isCurrentEpoch(epoch, for: model.id) else { return }
            switch dlError {
            case .cancelled:
                lastFailureMessages.removeValue(forKey: model.id)
            default:
                ModelDownloadDiagnosticsStore(
                    directory: modelsDirectory
                        .deletingLastPathComponent()
                        .appendingPathComponent("diagnostics/model-downloads", isDirectory: true)
                ).recordFailure(classification: "download", message: dlError.localizedDescription)
                lastFailureMessages[model.id] = dlError.localizedDescription
            }
        } catch {
            guard isCurrentEpoch(epoch, for: model.id) else { return }
            ModelDownloadDiagnosticsStore(
                directory: modelsDirectory
                    .deletingLastPathComponent()
                    .appendingPathComponent("diagnostics/model-downloads", isDirectory: true)
            ).recordFailure(classification: "download", message: error.localizedDescription)
            lastFailureMessages[model.id] = error.localizedDescription
        }
        await handleMutationCompletion(for: model.id)
    }

    /// Stop the in-flight download for `modelID` and clear its tracking, without changing
    /// the model's status. Shared by cancel + delete. Awaits the downloader's cancellation
    /// so callers can safely delete staging afterwards.
    private func stopAndClear(for modelID: String) async {
        _ = beginEpoch(for: modelID)
        pendingModelDownloads.removeAll { $0.id == modelID }
        let downloader = downloaders.removeValue(forKey: modelID)
        downloadTasks[modelID]?.cancel()
        downloadTasks.removeValue(forKey: modelID)
        inflightModelDownloads.remove(modelID)
        lastProgressPublishTimes.removeValue(forKey: modelID)
        if let downloader {
            await downloader.cancel()
        }
    }

    /// Cancel an in-flight download and discard its staged partial so the next download
    /// starts fresh from zero (a true cancel — no paused state, no silent resume).
    func cancelDownload(_ model: TTSModel) async {
        await stopAndClear(for: model.id)
        HuggingFaceDownloader.discardStaging(forTargetDirectory: model.installDirectory(in: modelsDirectory))
        await handleMutationCompletion(for: model.id)
    }

    func delete(_ model: TTSModel) async {
        await stopAndClear(for: model.id)

        let modelDir = model.installDirectory(in: modelsDirectory)
        do {
            try SharedModelComponentStore(modelsRoot: modelsDirectory).deleteModel(
                modelFolder: modelDir.lastPathComponent
            )
        } catch {
            lastFailureMessages[model.id] = error.localizedDescription
            await handleMutationCompletion(for: model.id)
            return
        }
        // Also drop any orphaned staging tree (partials/resume data/staged files) so a
        // deleted model doesn't leave multi-GB under `.qwenvoice-downloads/`.
        HuggingFaceDownloader.discardStaging(forTargetDirectory: modelDir)
        lastFailureMessages.removeValue(forKey: model.id)
        removeInstallMetadata(for: model)

        // Audit Finding B (May 2026 dual-variant cleanup): if the
        // user just deleted their currently-active variant, the
        // variant preference is now stale. Without this fixup, the
        // generate flow would compute `activeModel = <deleted variant>`,
        // `isModelAvailable = false`, and silently disable the
        // Generate button — the user has no obvious way to recover
        // short of clicking Use on the surviving variant.
        //
        // Recovery policy:
        //   1. If another variant of the same mode is still on
        //      disk, reassign the preference to it (smoothest UX —
        //      Generate stays enabled).
        //   2. Otherwise clear the preference so the
        //      hardware-recommended variant becomes Active again
        //      (its row will show as not-yet-installed but the
        //      readiness banner now points the user at a sensible
        //      next step).
        reconcileActiveVariantAfterDeletion(of: model)

        Task {
            await handleMutationCompletion(for: model.id)
        }
    }

    private func reconcileActiveVariantAfterDeletion(of model: TTSModel) {
        guard let deletedVariantID = model.variantID else { return }

        let preferenceVariantID = MacModelVariantPreferences.selectedVariantID(
            for: model.mode,
            defaultVariantID: nil
        )
        guard preferenceVariantID == deletedVariantID else { return }

        // Find a sibling variant of the same mode that is still
        // installed (folder exists AND required files complete).
        let siblingInstalled = TTSModel.all.first { candidate in
            candidate.mode == model.mode
                && candidate.id != model.id
                && candidate.variantID != nil
                && candidate.isAvailable(in: modelsDirectory, fileManager: fileManager)
        }

        if let siblingInstalled, let siblingVariantID = siblingInstalled.variantID {
            MacModelVariantPreferences.setSelectedVariantID(siblingVariantID, for: model.mode)
        } else {
            MacModelVariantPreferences.clearSelectedVariantID(for: model.mode)
        }
        activeVariantRevision += 1
    }

    private func performRefresh() async {
        let modelsDirectory = modelsDirectory
        let snapshots = await Task.detached(priority: .utility) {
            Self.fetchSnapshots(in: modelsDirectory)
        }.value
        applySnapshots(snapshots)
    }

    private nonisolated static func fetchSnapshots(in modelsDirectory: URL) -> [ModelInfo] {
        TTSModel.all.map { model in
            localModelInfo(for: model, modelsDirectory: modelsDirectory)
        }
    }

    private func applySnapshots(_ snapshots: [ModelInfo]) {
        let snapshotByID = Dictionary(uniqueKeysWithValues: snapshots.map { ($0.id, $0) })
        modelInfoByID = snapshotByID

        for model in TTSModel.all {
            let id = model.id
            // A download in flight owns its row status — don't let a disk snapshot refresh
            // overwrite it.
            if case .downloading = statuses[id] { continue }

            let snapshot = snapshotByID[id] ?? localModelInfo(for: model)
            let failureMessage = lastFailureMessages[id]
            if snapshot.complete {
                lastFailureMessages.removeValue(forKey: id)
                persistInstallMetadata(for: model, snapshot: snapshot)
            }
            statuses[id] = status(for: snapshot, failureMessage: failureMessage)
        }
    }

    private func status(for info: ModelInfo, failureMessage: String?) -> ModelStatus {
        if info.updateAvailable {
            return .updateAvailable(sizeBytes: info.sizeBytes, stalePaths: info.staleCatalogPaths)
        }
        if info.complete {
            return .downloaded(sizeBytes: info.sizeBytes)
        }
        if info.requiresRepair {
            return .repairAvailable(
                sizeBytes: info.sizeBytes,
                missingRequiredPaths: info.missingRequiredPaths,
                message: failureMessage ?? info.deepIntegrityMessage
            )
        }
        return .notDownloaded(message: failureMessage)
    }

    private func handleMutationCompletion(for modelID: String) async {
        downloaders.removeValue(forKey: modelID)
        downloadTasks.removeValue(forKey: modelID)
        lastProgressPublishTimes.removeValue(forKey: modelID)
        inflightModelDownloads.remove(modelID)
        if let model = TTSModel.model(id: modelID) {
            applyLocalSnapshot(for: model)
        } else {
            statuses[modelID] = .checking
        }
        // A slot just freed up — launch the next queued download, if any.
        startPendingDownloads()
        scheduleRefreshIfPossible()
    }

    private func localModelInfo(for model: TTSModel) -> ModelInfo {
        Self.localModelInfo(for: model, modelsDirectory: modelsDirectory)
    }

    private nonisolated static func localModelInfo(
        for model: TTSModel,
        modelsDirectory: URL
    ) -> ModelInfo {
        let fileManager = FileManager.default
        let modelDirectory = model.installDirectory(in: modelsDirectory)
        let rootExists = fileManager.fileExists(atPath: modelDirectory.path)
        let missingRequiredPaths = rootExists
            ? model.requiredRelativePaths.filter {
                !fileManager.fileExists(atPath: modelDirectory.appendingPathComponent($0).path)
            }
            : []
        let presenceComplete = rootExists && missingRequiredPaths.isEmpty
        let deepIntegrity: ModelAssetDeepIntegrity?
        if presenceComplete {
            let coreMode = QwenVoiceCore.GenerationMode(rawValue: model.mode.rawValue)!
            let modelDescriptor = ModelDescriptor(
                id: model.id,
                name: model.name,
                tier: model.tier,
                folder: model.folder,
                mode: coreMode,
                huggingFaceRepo: model.huggingFaceRepo,
                huggingFaceRevision: model.huggingFaceRevision,
                artifactVersion: model.artifactVersion,
                iosDownloadEligible: false,
                estimatedDownloadBytes: model.estimatedDownloadBytes,
                outputSubfolder: model.outputSubfolder,
                requiredRelativePaths: model.requiredRelativePaths,
                qwen3Capabilities: model.qwen3Capabilities
            )
            let descriptor = ModelAssetDescriptor(
                model: modelDescriptor,
                version: "status",
                artifacts: model.requiredRelativePaths.map {
                    ModelAssetArtifact(relativePath: $0, scope: .modelSpecific)
                }
            )
            let store = LocalModelAssetStore(
                rootDirectory: modelsDirectory,
                descriptors: [descriptor],
                storeVersionSeed: "status"
            )
            deepIntegrity = store.deepIntegrity(for: descriptor)
        } else {
            deepIntegrity = nil
        }
        let deepFailedRelativePaths: [String]
        let deepStatus: String?
        let deepMessage: String?
        switch deepIntegrity {
        case .failed(let message, let failedRelativePaths):
            deepStatus = "failed"
            deepMessage = message
            deepFailedRelativePaths = failedRelativePaths
        case .verified:
            deepStatus = "verified"
            deepMessage = nil
            deepFailedRelativePaths = []
        case .unavailable(let reason):
            deepStatus = reason
            deepMessage = nil
            deepFailedRelativePaths = []
        case nil:
            deepStatus = nil
            deepMessage = nil
            deepFailedRelativePaths = []
        }
        let complete = presenceComplete && deepFailedRelativePaths.isEmpty
        let effectiveMissingRequiredPaths = (missingRequiredPaths + deepFailedRelativePaths).sorted()
        // Update detection: a complete install may still predate the current
        // catalog pin. Byte-count probe only — repair re-verifies every digest
        // through the ordinary authenticated delivery plan.
        var staleCatalogPaths: [String] = []
        if complete,
           let catalog = Self.productionCatalog,
           let artifact = try? catalog.artifactMatchingMacOSDescriptor(
               folder: model.folder,
               repo: model.huggingFaceRepo,
               revision: model.huggingFaceRevision,
               artifactVersion: model.artifactVersion,
               estimatedDownloadBytes: model.estimatedDownloadBytes,
               requiredRelativePaths: model.requiredRelativePaths
           ) {
            staleCatalogPaths = catalog.installedFileSizeMismatches(
                for: artifact,
                modelsRoot: modelsDirectory,
                fileManager: fileManager
            )
        }
        let metadata = rootExists ? readInstallMetadata(for: model, in: modelDirectory) : nil
        let sizeBytes: Int
        if presenceComplete,
           let metadata,
           metadataMatchesCurrentModel(metadata, model: model, resolvedPath: modelDirectory.path) {
            sizeBytes = metadata.sizeBytes
        } else {
            sizeBytes = rootExists ? Self.directorySize(url: modelDirectory) : 0
        }

        return ModelInfo(
            id: model.id,
            name: model.name,
            folder: model.folder,
            mode: model.mode,
            tier: model.tier,
            outputSubfolder: model.outputSubfolder,
            huggingFaceRepo: model.huggingFaceRepo,
            requiredRelativePaths: model.requiredRelativePaths,
            resolvedPath: rootExists ? modelDirectory.path : nil,
            downloaded: rootExists,
            complete: complete,
            repairable: rootExists && !complete,
            missingRequiredPaths: effectiveMissingRequiredPaths,
            staleCatalogPaths: staleCatalogPaths,
            sizeBytes: sizeBytes,
            deepIntegrityStatus: deepStatus,
            deepIntegrityMessage: deepMessage,
            mlxAudioVersion: nil,
            supportsStreaming: true,
            supportsPreparedClone: model.mode == .clone,
            supportsCloneStreaming: model.mode == .clone,
            supportsBatch: true
        )
    }

    private func applyLocalSnapshot(for model: TTSModel) {
        let snapshot = localModelInfo(for: model)
        modelInfoByID[model.id] = snapshot
        if snapshot.complete {
            lastFailureMessages.removeValue(forKey: model.id)
            persistInstallMetadata(for: model, snapshot: snapshot)
        } else if !snapshot.downloaded {
            removeInstallMetadata(for: model)
        }
        statuses[model.id] = status(
            for: snapshot,
            failureMessage: lastFailureMessages[model.id]
        )
    }

    private func scheduleRefreshIfPossible() {
        Task { @MainActor [weak self] in
            guard let self else { return }
            await self.refresh()
        }
    }

    private func installMetadataURL(for model: TTSModel) -> URL {
        Self.installMetadataURL(for: model, modelsDirectory: modelsDirectory)
    }

    private nonisolated static func installMetadataURL(
        for model: TTSModel,
        modelsDirectory: URL
    ) -> URL {
        model.installDirectory(in: modelsDirectory)
            .appendingPathComponent(Self.installMetadataFilename, isDirectory: false)
    }

    private func persistInstallMetadata(for model: TTSModel, snapshot: ModelInfo) {
        guard snapshot.complete, let resolvedPath = snapshot.resolvedPath else { return }

        let metadata = InstallMetadata(
            schemaVersion: 1,
            modelID: model.id,
            huggingFaceRepo: model.huggingFaceRepo,
            huggingFaceRevision: model.huggingFaceRevision,
            completedAtUTC: ISO8601DateFormatter().string(from: Date()),
            resolvedPath: resolvedPath,
            sizeBytes: snapshot.sizeBytes,
            requiredRelativePaths: model.requiredRelativePaths,
            downloadedRelativePaths: model.requiredRelativePaths,
            missingRequiredPaths: snapshot.missingRequiredPaths
        )

        guard let data = try? JSONEncoder().encode(metadata) else { return }
        try? data.write(to: installMetadataURL(for: model), options: .atomic)
    }

    private func removeInstallMetadata(for model: TTSModel) {
        try? fileManager.removeItem(at: installMetadataURL(for: model))
    }

    private nonisolated static func readInstallMetadata(
        for model: TTSModel,
        in modelDirectory: URL
    ) -> InstallMetadata? {
        let url = modelDirectory.appendingPathComponent(installMetadataFilename, isDirectory: false)
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(InstallMetadata.self, from: data)
    }

    private nonisolated static func metadataMatchesCurrentModel(
        _ metadata: InstallMetadata,
        model: TTSModel,
        resolvedPath: String
    ) -> Bool {
        metadata.schemaVersion == 1
            && metadata.modelID == model.id
            && metadata.huggingFaceRepo == model.huggingFaceRepo
            && metadata.huggingFaceRevision == model.huggingFaceRevision
            && metadata.resolvedPath == resolvedPath
            && metadata.requiredRelativePaths == model.requiredRelativePaths
            && metadata.missingRequiredPaths.isEmpty
    }

    private func downloadedRelativePaths(in directory: URL) -> [String] {
        guard let enumerator = fileManager.enumerator(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }

        var paths: [String] = []
        for case let fileURL as URL in enumerator {
            guard let isRegularFile = try? fileURL.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile,
                  isRegularFile == true else {
                continue
            }
            let relativePath = fileURL.path.replacingOccurrences(of: directory.path + "/", with: "")
            paths.append(relativePath)
        }
        return paths.sorted()
    }

    private func beginEpoch(for modelID: String) -> Int {
        let nextEpoch = (stateEpochs[modelID] ?? 0) + 1
        stateEpochs[modelID] = nextEpoch
        return nextEpoch
    }

    private func isCurrentEpoch(_ epoch: Int, for modelID: String) -> Bool {
        stateEpochs[modelID] == epoch
    }

    private nonisolated static func directorySize(url: URL) -> Int {
        let fm = FileManager.default
        guard let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey]) else { return 0 }
        var total = 0
        for case let fileURL as URL in enumerator {
            if fileURL.lastPathComponent == installMetadataFilename {
                continue
            }
            if let size = try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                total += size
            }
        }
        return total
    }

    private func publishDownloadProgressIfCurrent(
        epoch: Int,
        modelID: String,
        progress: HuggingFaceDownloader.RepositoryProgress
    ) {
        guard isCurrentEpoch(epoch, for: modelID) else { return }
        guard case .downloading = statuses[modelID] else { return }

        let now = ContinuousClock.now
        if let lastPublish = lastProgressPublishTimes[modelID],
           now - lastPublish < .milliseconds(100) {
            return
        }
        lastProgressPublishTimes[modelID] = now

        statuses[modelID] = .downloading(
            progress: DownloadProgress(
                downloadedBytes: progress.downloadedBytes,
                totalBytes: progress.totalBytes > 0 ? progress.totalBytes : nil,
                completedFiles: progress.completedFiles,
                totalFiles: progress.totalFiles > 0 ? progress.totalFiles : nil,
                bytesPerSecond: progress.bytesPerSecond,
                isStalled: progress.isStalled,
                estimatedSecondsRemaining: progress.estimatedSecondsRemaining,
                retryCount: progress.retryCount,
                statusMessage: progress.statusMessage,
                phase: DownloadProgress.Phase(progress.phase)
            )
        )
    }
}

private extension ModelManagerViewModel.DownloadProgress.Phase {
    var displayLabel: String {
        switch self {
        case .queued:
            return "Queued"
        case .waitingForConnectivity:
            return "Waiting for network"
        case .downloading:
            return "Downloading"
        case .retrying:
            return "Retrying"
        case .verifying:
            return "Verifying"
        case .installing:
            return "Installing"
        case .cancelling:
            return "Cancelling"
        }
    }

    init(_ phase: HuggingFaceDownloader.DownloadPhase) {
        switch phase {
        case .queued:
            self = .queued
        case .waitingForConnectivity:
            self = .waitingForConnectivity
        case .downloading:
            self = .downloading
        case .retrying:
            self = .retrying
        case .verifying:
            self = .verifying
        case .installing:
            self = .installing
        case .cancelling:
            self = .cancelling
        }
    }
}
