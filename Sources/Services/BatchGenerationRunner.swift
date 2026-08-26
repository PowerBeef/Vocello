import AVFoundation
import Foundation
import QwenVoiceCore
import QwenVoiceNative

enum BatchSegmentationMode: String, Codable, Equatable {
    case lineSeparated
    case longForm
}

struct BatchProgressSnapshot: Equatable {
    let completedCount: Int
    let totalCount: Int
    let activeItemIndex: Int?
    let backendFraction: Double?
    let statusMessage: String

    init(
        completedCount: Int = 0,
        totalCount: Int = 0,
        activeItemIndex: Int? = nil,
        backendFraction: Double? = nil,
        statusMessage: String = ""
    ) {
        self.completedCount = completedCount
        self.totalCount = totalCount
        self.activeItemIndex = activeItemIndex
        self.backendFraction = backendFraction
        self.statusMessage = statusMessage
    }

    var itemFraction: Double {
        guard totalCount > 0 else { return 0.0 }
        return min(max(Double(completedCount) / Double(totalCount), 0.0), 1.0)
    }

    var displayFraction: Double {
        min(max(backendFraction ?? itemFraction, 0.0), 1.0)
    }

    var itemStatusText: String {
        guard totalCount > 0 else { return "" }
        // The "Item N active" suffix used to be appended here, but
        // `activeItemIndex` lags the engine's real progress (completion is
        // counted only after an item's take persists), which produced
        // contradictory text such as "Generating item 2/2… 0 of 2 clips
        // completed · Item 1 active". `statusMessage` already tells the user
        // which item is in flight, so the count line just reports completion.
        return "\(completedCount) of \(totalCount) clips completed"
    }
}

struct BatchGenerationItemState: Identifiable, Equatable {
    enum Status: Equatable {
        case pending
        case running
        case saved(audioPath: String)
        case failed(message: String)
        case cancelled
    }

    let id = UUID()
    let index: Int
    let line: String
    var status: Status

    var audioPath: String? {
        if case .saved(let audioPath) = status {
            return audioPath
        }
        return nil
    }

    var isSaved: Bool {
        if case .saved = status {
            return true
        }
        return false
    }

    var isRetryable: Bool {
        switch status {
        case .pending, .running, .failed, .cancelled:
            return true
        case .saved:
            return false
        }
    }

    var statusLabel: String {
        switch status {
        case .pending:
            return "Pending"
        case .running:
            return "Running"
        case .saved:
            return "Saved"
        case .failed:
            return "Failed"
        case .cancelled:
            return "Cancelled"
        }
    }

    var statusMessage: String? {
        switch status {
        case .failed(let message):
            return message
        default:
            return nil
        }
    }
}

@MainActor
protocol GenerationPersisting {
    func saveGeneration(_ generation: Generation) async throws -> Generation
    /// Replaces the project's joined-output row (if any) with `generation`,
    /// so regeneration and resume keep exactly one joined record per project.
    func replaceLongFormJoinedGeneration(_ generation: Generation) async throws -> Generation
}

extension DatabaseService: GenerationPersisting {
    func saveGeneration(_ generation: Generation) async throws -> Generation {
        try await GenerationHistoryRecovery.persist(generation)
    }

    func replaceLongFormJoinedGeneration(_ generation: Generation) async throws -> Generation {
        try await GenerationHistoryRecovery.persist(generation, operation: .replaceLongFormJoined)
    }
}

struct BatchGenerationRequest {
    let mode: GenerationMode
    let model: TTSModel
    let lines: [String]
    let segmentationMode: BatchSegmentationMode
    let voice: String?
    let emotion: String?
    let deliveryInstructionCellID: String?
    let languageHint: String?
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    /// One sampling seed shared by every item in the batch (GitHub #30):
    /// segments of one batch keep a steadier character/pacing than fully
    /// independent draws (community-verified for long-form chunking), and
    /// Voice Design batches stop re-rolling a different voice per segment
    /// quite as wildly. Minted per batch run, so separate batches still
    /// differ from each other.
    let batchSeed: UInt64
    /// Long-form v4 plan; present exactly when `segmentationMode == .longForm`.
    /// Segment text, per-segment sub-seed, boundary pause, and identity all
    /// derive from this plan; `lines` mirrors its spoken texts for item
    /// bookkeeping. For long-form, per-segment sub-seeds supersede `batchSeed`.
    var longFormPlan: LongFormPlan?

    init(
        mode: GenerationMode,
        model: TTSModel,
        lines: [String],
        segmentationMode: BatchSegmentationMode = .lineSeparated,
        voice: String?,
        emotion: String?,
        deliveryInstructionCellID: String? = nil,
        languageHint: String? = nil,
        voiceDescription: String?,
        refAudio: String?,
        refText: String?,
        batchSeed: UInt64 = UInt64.random(in: UInt64.min...UInt64.max)
    ) {
        self.mode = mode
        self.model = model
        self.lines = lines
        self.segmentationMode = segmentationMode
        self.voice = voice
        self.emotion = emotion
        self.deliveryInstructionCellID = deliveryInstructionCellID
        self.languageHint = languageHint
        self.voiceDescription = voiceDescription
        self.refAudio = refAudio
        self.refText = refText
        self.batchSeed = batchSeed
    }

    func validationError(isModelAvailable: Bool, recoveryDetail: String) -> String? {
        guard isModelAvailable else {
            return recoveryDetail
        }

        if mode == .design && (voiceDescription ?? "").isEmpty {
            return "Enter a voice description before starting batch generation."
        }

        if mode == .clone && refAudio == nil {
            return "Select a reference audio file before starting batch generation."
        }

        return nil
    }

    func makeHistoryRecord(
        for line: String,
        result: QwenVoiceNative.GenerationResult,
        longFormRole: String? = nil
    ) -> Generation {
        let voiceName: String?
        switch mode {
        case .custom:
            voiceName = voice
        case .design:
            voiceName = voiceDescription
        case .clone:
            if let voice {
                voiceName = voice
            } else if let refAudio {
                voiceName = URL(fileURLWithPath: refAudio).deletingPathExtension().lastPathComponent
            } else {
                voiceName = nil
            }
        }

        let projectID = segmentationMode == .longForm ? longFormPlan?.evidence.planDigest : nil
        return Generation(
            text: line,
            mode: model.mode.rawValue,
            modelTier: model.tier,
            voice: voiceName,
            emotion: emotion,
            speed: nil,
            audioPath: result.audioPath,
            duration: result.durationSeconds,
            createdAt: Date(),
            longFormProjectID: projectID,
            longFormRole: projectID == nil ? nil : (longFormRole ?? "segment")
        )
    }

    /// Pause budget for the assembled output: the whole script's punctuation
    /// plus the assembler's own inserted boundary pauses.
    var joinedOutputPauseBudget: Int {
        lines.reduce(0) { $0 + PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: $1) }
            + max(0, lines.count - 1)
    }

    /// History record for the assembled long-form output. Text is the joined
    /// spoken script; duration derives from the assembler's exact frame count.
    func makeJoinedHistoryRecord(
        assembly: LongFormAssemblyEvidence,
        outputURL: URL
    ) -> Generation? {
        guard segmentationMode == .longForm, let plan = longFormPlan else { return nil }
        var record = makeHistoryRecord(
            for: lines.joined(separator: " "),
            result: QwenVoiceNative.GenerationResult(
                audioPath: outputURL.path,
                durationSeconds: Double(assembly.outputFrameCount) / Double(assembly.sampleRate),
                streamSessionDirectory: nil,
                usedStreaming: true
            ),
            longFormRole: "joined"
        )
        record.longFormProjectID = plan.evidence.planDigest
        return record
    }

    /// Every batch item — line-separated and long-form — streams for flat
    /// memory, mandatory engine Fast QC, and standard streaming telemetry;
    /// live preview publication stays enabled (playback gated by the user's
    /// auto-play preference). `suppressStreamingPreview` remains available for
    /// contexts that need silent generation.
    private var streamsSegments: Bool { true }

    private func segmentSeed(batchIndex: Int?, seedOverride: UInt64?) -> UInt64 {
        if let seedOverride { return seedOverride }
        guard let longFormPlan, let batchIndex,
              batchIndex >= 1, batchIndex <= longFormPlan.segments.count else {
            return batchSeed
        }
        return longFormPlan.segments[batchIndex - 1].evidence.effectiveSubseed
    }

    func makeGenerationRequest(
        for line: String,
        outputPath: String,
        batchIndex rawBatchIndex: Int?,
        batchTotal rawBatchTotal: Int?,
        seedOverride: UInt64? = nil
    ) -> QwenVoiceNative.GenerationRequest {
        // Every item is an ordinary sequential streaming take; the engine's
        // support decision reserves batch markers for the retired native batch
        // route, and item order lives in the visible list (and, for long-form,
        // the plan + manifest).
        let batchIndex: Int? = nil
        let batchTotal: Int? = nil
        _ = rawBatchTotal
        switch mode {
        case .custom:
            return QwenVoiceNative.GenerationRequest(
                modelID: model.id,
                text: line,
                outputPath: outputPath,
                shouldStream: streamsSegments,
                batchIndex: batchIndex,
                batchTotal: batchTotal,
                languageHint: languageHint,
                payload: .custom(
                    speakerID: voice ?? TTSModel.defaultSpeaker,
                    deliveryStyle: model.supportsInstructionControl
                        ? (emotion ?? EmotionPreset.neutralPresetInstruction)
                        : nil
                ),
                seed: segmentSeed(batchIndex: rawBatchIndex, seedOverride: seedOverride),
                variation: GenerationVariationPreference.requestValue(),
                deliveryInstructionCellID: deliveryInstructionCellID
            )
        case .design:
            return QwenVoiceNative.GenerationRequest(
                modelID: model.id,
                text: line,
                outputPath: outputPath,
                shouldStream: streamsSegments,
                batchIndex: batchIndex,
                batchTotal: batchTotal,
                languageHint: languageHint,
                payload: .design(
                    voiceDescription: voiceDescription ?? "",
                    deliveryStyle: emotion ?? EmotionPreset.neutralPresetInstruction
                ),
                seed: segmentSeed(batchIndex: rawBatchIndex, seedOverride: seedOverride),
                variation: GenerationVariationPreference.requestValue()
            )
        case .clone:
            return QwenVoiceNative.GenerationRequest(
                modelID: model.id,
                text: line,
                outputPath: outputPath,
                shouldStream: streamsSegments,
                batchIndex: batchIndex,
                batchTotal: batchTotal,
                languageHint: languageHint,
                payload: .clone(
                    reference: CloneReference(
                        audioPath: refAudio ?? "",
                        transcript: refText
                    )
                ),
                seed: segmentSeed(batchIndex: rawBatchIndex, seedOverride: seedOverride),
                variation: GenerationVariationPreference.requestValue()
            )
        }
    }


    func outputText(for line: String, index: Int) -> String {
        switch segmentationMode {
        case .lineSeparated:
            return line
        case .longForm:
            return String(format: "segment_%04d_%@", index + 1, String(line.prefix(40)))
        }
    }

    /// Duration probe for v4 execution evidence; reads only the audio header.
    static func audioDurationSeconds(for path: String) async -> Double? {
        await Task.detached(priority: .utility) {
            guard let audioFile = try? AVAudioFile(forReading: URL(fileURLWithPath: path)),
                  audioFile.processingFormat.sampleRate > 0 else { return nil }
            return Double(audioFile.length) / audioFile.processingFormat.sampleRate
        }.value
    }
}

enum BatchGenerationOutcome: Equatable {
    case completed(items: [BatchGenerationItemState])
    case cancelled(items: [BatchGenerationItemState], restartFailedMessage: String?)
    case failed(items: [BatchGenerationItemState], message: String)

    var items: [BatchGenerationItemState] {
        switch self {
        case .completed(let items):
            return items
        case .cancelled(let items, _):
            return items
        case .failed(let items, _):
            return items
        }
    }

    var completedCount: Int {
        items.filter(\.isSaved).count
    }

    var totalCount: Int {
        items.count
    }

    var retryRemainingLines: [String] {
        items.compactMap { item in
            switch item.status {
            case .pending, .running, .cancelled:
                return item.line
            case .failed, .saved:
                return nil
            }
        }
    }

    var retryFailedLines: [String] {
        items.compactMap { item in
            if case .failed = item.status {
                return item.line
            }
            return nil
        }
    }

    var savedAudioPaths: [String] {
        items.compactMap(\.audioPath)
    }

    func withRestartFailure(_ message: String?) -> BatchGenerationOutcome {
        guard case .cancelled(let items, _) = self else { return self }
        return .cancelled(items: items, restartFailedMessage: message)
    }
}

@MainActor
final class BatchGenerationCoordinator: ObservableObject {
    @Published private(set) var isProcessing = false
    @Published private(set) var isCancelling = false
    @Published private(set) var progressSnapshot = BatchProgressSnapshot()
    @Published private(set) var itemStates: [BatchGenerationItemState] = []
    @Published var errorMessage: String?
    @Published private(set) var outcome: BatchGenerationOutcome?

    private var runner: BatchGenerationRunner?
    private var runTask: Task<Void, Never>?
    private var cancelTask: Task<Void, Never>?
    private var cancelRestartFailedMessage: String?
    /// Retained for long-form resume and single-segment regeneration; the plan
    /// inside is the identity authority for both.
    private var lastLongFormRequest: BatchGenerationRequest?
    private var longFormReplacements: [LongFormSegmentReplacementEvidence] = []

    func startBatch(
        batchText: String,
        segmentationMode: BatchSegmentationMode = .lineSeparated,
        requestBuilder: ([String]) -> BatchGenerationRequest?,
        isModelAvailable: (TTSModel) -> Bool,
        recoveryDetail: (TTSModel) -> String,
        engineStore: TTSEngineStore,
        store: any GenerationPersisting = DatabaseService.shared
    ) {
        let lines: [String]
        var longFormPlan: LongFormPlan?
        switch segmentationMode {
        case .lineSeparated:
            lines = batchText.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
        case .longForm:
            do {
                let spokenPlan = try SpokenTextPlanner.plan(originalText: batchText)
                let plan = try LongFormPlanner.plan(
                    spokenTextPlan: spokenPlan,
                    configuration: LongFormPlanningConfiguration(
                        runtimeTokenLimit: LongFormPlanningConfiguration.shippingRuntimeTokenLimit,
                        baseSeed: UInt64.random(in: UInt64.min ... UInt64.max)
                    )
                )
                longFormPlan = plan
                lines = plan.segments.map(\.spokenTextForGeneration)
            } catch {
                errorMessage = "Long-form planning failed: \(error.localizedDescription)"
                return
            }
        }

        guard !lines.isEmpty else { return }
        let maxBatchSegments = 100
        if lines.count > maxBatchSegments {
            errorMessage = "Batch is too large: \(lines.count) segments exceeds the maximum of \(maxBatchSegments). Please split the text and try again."
            return
        }
        guard var request = requestBuilder(lines) else {
            errorMessage = "Model configuration not found"
            return
        }
        request.longFormPlan = longFormPlan
        lastLongFormRequest = segmentationMode == .longForm ? request : nil
        longFormReplacements = []

        if let validationError = request.validationError(
            isModelAvailable: isModelAvailable(request.model),
            recoveryDetail: recoveryDetail(request.model)
        ) {
            errorMessage = validationError
            return
        }

        let runner = BatchGenerationRunner(
            engineStore: engineStore,
            store: store
        )

        self.runner = runner
        runTask?.cancel()
        cancelTask = nil
        cancelRestartFailedMessage = nil
        isProcessing = true
        isCancelling = false
        errorMessage = nil
        outcome = nil
        itemStates = lines.enumerated().map { index, line in
            BatchGenerationItemState(index: index, line: line, status: .pending)
        }
        progressSnapshot = BatchProgressSnapshot(
            completedCount: 0,
            totalCount: lines.count,
            activeItemIndex: lines.isEmpty ? nil : 0,
            statusMessage: "Preparing batch..."
        )

        runTask = Task { [weak self] in
            guard let self else { return }

            var outcome = await runner.run(
                request: request,
                makeOutputPath: { makeOutputPath(subfolder: $0, text: $1) },
                onProgress: { [weak self] snapshot in
                    self?.progressSnapshot = snapshot
                },
                onItemsUpdated: { [weak self] items in
                    self?.itemStates = items
                }
            )

            if case .cancelled = outcome, let cancelTask = self.cancelTask {
                await cancelTask.value
                if let cancelRestartFailedMessage {
                    outcome = outcome.withRestartFailure(cancelRestartFailedMessage)
                }
            }

            self.isProcessing = false
            self.isCancelling = false
            self.runner = nil
            self.runTask = nil
            self.outcome = outcome

            if case .failed(_, let message) = outcome {
                self.errorMessage = message
            } else if case .cancelled(_, let restartFailedMessage) = outcome {
                self.errorMessage = restartFailedMessage
            }
        }
    }

    /// A finished long-form run with retained plan identity can resume missing
    /// segments or regenerate an individual one.
    var canOperateOnLongFormOutcome: Bool {
        !isProcessing && lastLongFormRequest != nil && outcome != nil
    }

    /// Re-runs the retained long-form plan, reusing every already-saved take
    /// and generating only missing or failed segments.
    func resumeLongForm(engineStore: TTSEngineStore, store: any GenerationPersisting = DatabaseService.shared) {
        guard canOperateOnLongFormOutcome,
              let request = lastLongFormRequest,
              let priorItems = outcome?.items else { return }
        let replacements = longFormReplacements
        let runner = BatchGenerationRunner(engineStore: engineStore, store: store)
        self.runner = runner
        runTask?.cancel()
        cancelTask = nil
        cancelRestartFailedMessage = nil
        isProcessing = true
        isCancelling = false
        errorMessage = nil
        outcome = nil
        runTask = Task { [weak self] in
            guard let self else { return }
            let outcome = await runner.run(
                request: request,
                reusingItems: priorItems,
                replacements: replacements,
                makeOutputPath: { makeOutputPath(subfolder: $0, text: $1) },
                onProgress: { [weak self] snapshot in
                    self?.progressSnapshot = snapshot
                },
                onItemsUpdated: { [weak self] items in
                    self?.itemStates = items
                }
            )
            self.finish(with: outcome)
        }
    }

    /// Regenerates one segment of the finished long-form run as a new accepted
    /// take, then reassembles and rewrites the manifest.
    func regenerateLongFormSegment(
        _ index: Int,
        engineStore: TTSEngineStore,
        store: any GenerationPersisting = DatabaseService.shared
    ) {
        guard canOperateOnLongFormOutcome,
              let request = lastLongFormRequest,
              let priorItems = outcome?.items else { return }
        let replacements = longFormReplacements
        let runner = BatchGenerationRunner(engineStore: engineStore, store: store)
        self.runner = runner
        runTask?.cancel()
        cancelTask = nil
        cancelRestartFailedMessage = nil
        isProcessing = true
        isCancelling = false
        errorMessage = nil
        outcome = nil
        runTask = Task { [weak self] in
            guard let self else { return }
            let result = await runner.regenerateSegment(
                request: request,
                priorItems: priorItems,
                segmentIndex: index,
                priorReplacements: replacements,
                makeOutputPath: { makeOutputPath(subfolder: $0, text: $1) },
                onProgress: { [weak self] snapshot in
                    self?.progressSnapshot = snapshot
                },
                onItemsUpdated: { [weak self] items in
                    self?.itemStates = items
                }
            )
            self.longFormReplacements = result.replacements
            self.finish(with: result.outcome)
        }
    }

    private func finish(with outcome: BatchGenerationOutcome) {
        isProcessing = false
        isCancelling = false
        runner = nil
        runTask = nil
        self.outcome = outcome
        if case .failed(_, let message) = outcome {
            errorMessage = message
        } else if case .cancelled(_, let restartFailedMessage) = outcome {
            errorMessage = restartFailedMessage
        }
    }

    /// Sheet-dismissal safety net: if the sheet disappears while a batch is
    /// still processing (programmatic dismissal, window close — anything but
    /// the Cancel button), cancel the run so it can't keep generating and
    /// holding the engine's generation slot with no visible UI.
    func cancelIfDismissedWhileProcessing() {
        guard isProcessing else { return }
        cancelBatch(dismiss: {})
    }

    func cancelBatch(
        dismiss: @escaping () -> Void
    ) {
        guard isProcessing else {
            dismiss()
            return
        }

        guard !isCancelling else { return }
        guard let runner else {
            isProcessing = false
            dismiss()
            return
        }

        isCancelling = true
        errorMessage = nil
        cancelRestartFailedMessage = nil
        progressSnapshot = BatchProgressSnapshot(
            completedCount: progressSnapshot.completedCount,
            totalCount: progressSnapshot.totalCount,
            activeItemIndex: progressSnapshot.activeItemIndex,
            backendFraction: progressSnapshot.backendFraction,
            statusMessage: "Cancelling..."
        )
        cancelTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await runner.requestCancellation()
            } catch {
                self.cancelRestartFailedMessage = "Batch generation was interrupted, but the backend could not be restarted: \(error.localizedDescription)"
            }
        }
    }
}

@MainActor
final class BatchGenerationRunner {
    private let engineStore: TTSEngineStore
    private let store: any GenerationPersisting
    private let generationEvents: GenerationLibraryEvents
    private let audioQualityEvaluator: (URL, Int) async -> AudioQualityGate.Report
    private let cancellationState = BatchGenerationCancellationState()

    init(
        engineStore: TTSEngineStore,
        store: any GenerationPersisting,
        generationEvents: GenerationLibraryEvents = .shared,
        audioQualityEvaluator: @escaping (URL, Int) async -> AudioQualityGate.Report = { url, expectedPauseCount in
            await Task.detached(priority: .utility) {
                AudioQualityGate.evaluate(url: url, expectedPauseCount: expectedPauseCount)
            }.value
        }
    ) {
        self.engineStore = engineStore
        self.store = store
        self.generationEvents = generationEvents
        self.audioQualityEvaluator = audioQualityEvaluator
    }

    func run(
        request: BatchGenerationRequest,
        reusingItems: [BatchGenerationItemState]? = nil,
        replacements: [LongFormSegmentReplacementEvidence] = [],
        makeOutputPath: (String, String) -> String,
        onProgress: @escaping @MainActor (BatchProgressSnapshot) -> Void,
        onItemsUpdated: @escaping @MainActor ([BatchGenerationItemState]) -> Void
    ) async -> BatchGenerationOutcome {
        // Hold the generation performance gate across the whole run — segments,
        // QC, History saves, and assembly — instead of flickering per segment.
        engineStore.beginSustainedPerformanceActivity()
        defer { engineStore.endSustainedPerformanceActivity() }
        var items = request.lines.enumerated().map { index, line -> BatchGenerationItemState in
            // Long-form resume: keep already-saved takes from the prior run of
            // the same plan; everything else regenerates.
            if request.segmentationMode == .longForm,
               let prior = reusingItems, index < prior.count,
               prior[index].isSaved, prior[index].line == line {
                return prior[index]
            }
            return BatchGenerationItemState(index: index, line: line, status: .pending)
        }
        var completedCount = 0
        let total = request.lines.count

        func publishItems() {
            onItemsUpdated(items)
        }

        func markItemsCancelled(startingAt index: Int) {
            guard index < items.count else { return }
            for itemIndex in index..<items.count where !items[itemIndex].isSaved {
                items[itemIndex].status = .cancelled
            }
        }

        func publishProgress(activeItemIndex: Int?, message: String, backendFraction: Double? = nil) {
            onProgress(
                BatchProgressSnapshot(
                    completedCount: completedCount,
                    totalCount: total,
                    activeItemIndex: activeItemIndex,
                    backendFraction: backendFraction,
                    statusMessage: message
                )
            )
        }

        publishItems()

        var longFormQualityReports: [AudioQualityGate.Report?] = []
        for (index, line) in request.lines.enumerated() {
            if await cancellationState.wasRequested() {
                markItemsCancelled(startingAt: index)
                publishItems()
                engineStore.clearGenerationActivity()
                return .cancelled(items: items, restartFailedMessage: nil)
            }

            if request.segmentationMode == .longForm,
               items[index].isSaved,
               let reusedPath = items[index].audioPath {
                // Resume: re-verify the retained take instead of regenerating.
                let qualityReport = await audioQualityEvaluator(
                    URL(fileURLWithPath: reusedPath),
                    PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
                )
                longFormQualityReports.append(qualityReport)
                if !qualityReport.passed {
                    items[index].status = .failed(message: qualityReport.failureSummary)
                    await persistLongFormV4Manifest(
                        request: request,
                        items: items,
                        qualityReports: longFormQualityReports,
                        assembly: nil,
                        replacements: replacements
                    )
                    publishItems()
                    return .failed(
                        items: items,
                        message: "A previously generated long-form segment no longer passes audio quality checks."
                    )
                }
                completedCount += 1
                publishProgress(activeItemIndex: index, message: "Reusing item \(index + 1)/\(total)...")
                publishItems()
                continue
            }

            items[index].status = .running
            publishItems()
            publishProgress(activeItemIndex: index, message: "Generating item \(index + 1)/\(total)...")

            let outputPath = makeOutputPath(request.model.outputSubfolder, line)
            do {
                let result = try await generateResult(
                    for: request,
                    line: line,
                    outputPath: outputPath,
                    batchIndex: index + 1,
                    batchTotal: total
                )

                if request.segmentationMode == .longForm {
                    let qualityReport = await audioQualityEvaluator(
                        URL(fileURLWithPath: result.audioPath),
                        PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
                    )
                    longFormQualityReports.append(qualityReport)
                    if !qualityReport.passed {
                        items[index].status = .failed(message: qualityReport.failureSummary)
                        await persistLongFormV4Manifest(
                            request: request,
                            items: items,
                            qualityReports: longFormQualityReports,
                            assembly: nil,
                            replacements: replacements
                        )
                        publishItems()
                        return .failed(
                            items: items,
                            message: "Long-form batch failed audio quality checks. Review the failed segment details before retrying."
                        )
                    }
                }

                publishProgress(activeItemIndex: index, message: "Saving item \(index + 1)/\(total)...")

                let generation = request.makeHistoryRecord(for: line, result: result)
                let savedGeneration = try await store.saveGeneration(generation)
                // See above: payload-carrying announce so HistoryView
                // appends the new row live.
                generationEvents.announceGenerationAppended(savedGeneration)
                completedCount += 1
                items[index].status = .saved(audioPath: result.audioPath)
                publishItems()
            } catch {
                let cancellationRequested = await cancellationState.wasRequested()
                if error is CancellationError || cancellationRequested {
                    markItemsCancelled(startingAt: index)
                    publishItems()
                    engineStore.clearGenerationActivity()
                    return .cancelled(items: items, restartFailedMessage: nil)
                }

                items[index].status = .failed(message: error.localizedDescription)
                publishItems()
                return .failed(items: items, message: error.localizedDescription)
            }
        }

        if await cancellationState.wasRequested() {
            if let firstUnfinished = items.firstIndex(where: { !$0.isSaved }) {
                markItemsCancelled(startingAt: firstUnfinished)
            }
            publishItems()
            engineStore.clearGenerationActivity()
            return .cancelled(items: items, restartFailedMessage: nil)
        }

        if request.segmentationMode == .longForm {
            publishProgress(activeItemIndex: nil, message: "Joining segments...")
            do {
                let joined = try await assembleLongFormOutput(request: request, items: items)
                let joinedReport = await audioQualityEvaluator(
                    joined.outputURL,
                    request.joinedOutputPauseBudget
                )
                await persistLongFormV4Manifest(
                    request: request,
                    items: items,
                    qualityReports: longFormQualityReports,
                    assembly: joined.evidence,
                    replacements: replacements
                )
                if !joinedReport.passed {
                    return .failed(
                        items: items,
                        message: "Long-form joined output failed audio quality checks: \(joinedReport.failureSummary)"
                    )
                }
                if let joinedRecord = request.makeJoinedHistoryRecord(
                    assembly: joined.evidence,
                    outputURL: joined.outputURL
                ) {
                    let savedJoined = try await store.replaceLongFormJoinedGeneration(joinedRecord)
                    generationEvents.announceGenerationAppended(savedJoined)
                }
            } catch {
                await persistLongFormV4Manifest(
                    request: request,
                    items: items,
                    qualityReports: longFormQualityReports,
                    assembly: nil,
                    replacements: replacements
                )
                return .failed(
                    items: items,
                    message: "Long-form assembly failed: \(error.localizedDescription)"
                )
            }
        }

        publishProgress(activeItemIndex: nil, message: "Done")
        return .completed(items: items)
    }

    func requestCancellation() async throws {
        await cancellationState.request()
        try await engineStore.cancelActiveGeneration()
    }

    /// Regenerates one long-form segment as a new accepted take (revision >= 2)
    /// with a fresh seed, re-verifies it, reassembles the joined output, and
    /// rewrites the manifest with the appended replacement history. A take
    /// that fails QC leaves the prior accepted take and history untouched.
    func regenerateSegment(
        request: BatchGenerationRequest,
        priorItems: [BatchGenerationItemState],
        segmentIndex: Int,
        priorReplacements: [LongFormSegmentReplacementEvidence],
        makeOutputPath: (String, String) -> String,
        onProgress: @escaping @MainActor (BatchProgressSnapshot) -> Void,
        onItemsUpdated: @escaping @MainActor ([BatchGenerationItemState]) -> Void
    ) async -> (outcome: BatchGenerationOutcome, replacements: [LongFormSegmentReplacementEvidence]) {
        engineStore.beginSustainedPerformanceActivity()
        defer { engineStore.endSustainedPerformanceActivity() }
        guard request.segmentationMode == .longForm,
              let plan = request.longFormPlan,
              segmentIndex >= 0,
              segmentIndex < request.lines.count,
              segmentIndex < plan.segments.count else {
            return (
                .failed(items: priorItems, message: "The segment to regenerate is not part of this long-form project."),
                priorReplacements
            )
        }

        var items = priorItems
        let line = request.lines[segmentIndex]
        let segmentID = plan.segments[segmentIndex].segmentID
        let revision = 2 + priorReplacements.count(where: { $0.segmentID == segmentID })
        let replacementSeed = UInt64.random(in: UInt64.min ... UInt64.max)
        let total = request.lines.count

        items[segmentIndex].status = .running
        onItemsUpdated(items)
        onProgress(
            BatchProgressSnapshot(
                completedCount: items.count(where: \.isSaved),
                totalCount: total,
                activeItemIndex: segmentIndex,
                statusMessage: "Regenerating segment \(segmentIndex + 1)/\(total)..."
            )
        )

        let outputPath = makeOutputPath(request.model.outputSubfolder, request.outputText(for: line, index: segmentIndex))
        do {
            let result = try await engineStore.generate(
                request.makeGenerationRequest(
                    for: line,
                    outputPath: outputPath,
                    batchIndex: segmentIndex + 1,
                    batchTotal: total,
                    seedOverride: replacementSeed
                )
            )
            let qualityReport = await audioQualityEvaluator(
                URL(fileURLWithPath: result.audioPath),
                PersistedWAVAudioQCAnalyzer.expectedPauseCount(in: line)
            )
            guard qualityReport.passed else {
                items[segmentIndex] = priorItems[segmentIndex]
                onItemsUpdated(items)
                return (
                    .failed(
                        items: items,
                        message: "The regenerated take failed audio quality checks; the previous take is unchanged. \(qualityReport.failureSummary)"
                    ),
                    priorReplacements
                )
            }

            let generation = request.makeHistoryRecord(for: line, result: result)
            let savedGeneration = try await store.saveGeneration(generation)
            generationEvents.announceGenerationAppended(savedGeneration)
            items[segmentIndex].status = .saved(audioPath: result.audioPath)
            onItemsUpdated(items)

            var replacements = priorReplacements
            replacements.append(
                LongFormSegmentReplacementEvidence(
                    segmentID: segmentID,
                    revision: revision,
                    effectiveSeed: replacementSeed,
                    generatedAtUTC: ISO8601DateFormatter().string(from: Date()),
                    qcPassed: true,
                    qcWarnings: qualityReport.warnings
                )
            )

            onProgress(
                BatchProgressSnapshot(
                    completedCount: items.count(where: \.isSaved),
                    totalCount: total,
                    activeItemIndex: nil,
                    statusMessage: "Joining segments..."
                )
            )
            let qualityReports: [AudioQualityGate.Report?] = items.indices.map { index in
                index == segmentIndex ? qualityReport : nil
            }
            let joined = try await assembleLongFormOutput(request: request, items: items)
            let joinedReport = await audioQualityEvaluator(
                joined.outputURL,
                request.joinedOutputPauseBudget
            )
            await persistLongFormV4Manifest(
                request: request,
                items: items,
                qualityReports: qualityReports,
                assembly: joined.evidence,
                replacements: replacements
            )
            guard joinedReport.passed else {
                return (
                    .failed(
                        items: items,
                        message: "Long-form joined output failed audio quality checks after regeneration: \(joinedReport.failureSummary)"
                    ),
                    replacements
                )
            }
            if let joinedRecord = request.makeJoinedHistoryRecord(
                assembly: joined.evidence,
                outputURL: joined.outputURL
            ) {
                let savedJoined = try await store.replaceLongFormJoinedGeneration(joinedRecord)
                generationEvents.announceGenerationAppended(savedJoined)
            }
            onProgress(
                BatchProgressSnapshot(
                    completedCount: items.count(where: \.isSaved),
                    totalCount: total,
                    activeItemIndex: nil,
                    statusMessage: "Done"
                )
            )
            return (.completed(items: items), replacements)
        } catch {
            items[segmentIndex] = priorItems[segmentIndex]
            onItemsUpdated(items)
            if error is CancellationError {
                return (.cancelled(items: items, restartFailedMessage: nil), priorReplacements)
            }
            return (
                .failed(items: items, message: "Segment regeneration failed: \(error.localizedDescription)"),
                priorReplacements
            )
        }
    }

    private func generateResult(
        for request: BatchGenerationRequest,
        line: String,
        outputPath: String,
        batchIndex: Int,
        batchTotal: Int
    ) async throws -> QwenVoiceNative.GenerationResult {
        try await engineStore.generate(
            request.makeGenerationRequest(
                for: line,
                outputPath: outputPath,
                batchIndex: batchIndex,
                batchTotal: batchTotal
            )
        )
    }

    private enum LongFormRunError: LocalizedError {
        case missingPlan
        case missingSegmentAudio(index: Int)

        var errorDescription: String? {
            switch self {
            case .missingPlan:
                return "The long-form run is missing its segmentation plan."
            case .missingSegmentAudio(let index):
                return "Segment \(index + 1) has no generated audio to join."
            }
        }
    }

    private func assembleLongFormOutput(
        request: BatchGenerationRequest,
        items: [BatchGenerationItemState]
    ) async throws -> (evidence: LongFormAssemblyEvidence, outputURL: URL) {
        guard let plan = request.longFormPlan else { throw LongFormRunError.missingPlan }
        var sources: [LongFormAssemblySegmentSource] = []
        for (index, segment) in plan.segments.enumerated() {
            guard index < items.count, let path = items[index].audioPath else {
                throw LongFormRunError.missingSegmentAudio(index: index)
            }
            sources.append(
                LongFormAssemblySegmentSource(
                    segmentID: segment.segmentID,
                    lineage: segment.evidence.lineage,
                    audioURL: URL(fileURLWithPath: path),
                    boundary: segment.evidence.boundary,
                    intendedPauseMilliseconds: segment.evidence.intendedPauseMilliseconds
                )
            )
        }
        guard let firstPath = items.compactMap(\.audioPath).first else {
            throw LongFormRunError.missingSegmentAudio(index: 0)
        }
        let digestPrefix = String(plan.evidence.planDigest.prefix(8))
        let outputURL = URL(fileURLWithPath: firstPath)
            .deletingLastPathComponent()
            .appendingPathComponent("long_form_joined_\(digestPrefix).wav", isDirectory: false)
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: sources,
            outputURL: outputURL,
            provenanceModelID: request.model.id,
            provenanceMode: request.model.mode.rawValue
        )
        return (evidence, outputURL)
    }

    private func persistLongFormV4Manifest(
        request: BatchGenerationRequest,
        items: [BatchGenerationItemState],
        qualityReports: [AudioQualityGate.Report?],
        assembly: LongFormAssemblyEvidence?,
        replacements: [LongFormSegmentReplacementEvidence] = []
    ) async {
        guard let plan = request.longFormPlan else { return }
        let audioPaths: [String?] = plan.evidence.segments.indices.map { index in
            index < items.count ? items[index].audioPath : nil
        }
        // One detached probe for every duration; the evidence loop below is
        // fully synchronous on the main actor.
        let durations: [Double?] = await Task.detached(priority: .utility) {
            audioPaths.map { path -> Double? in
                guard let path,
                      let audioFile = try? AVAudioFile(forReading: URL(fileURLWithPath: path)),
                      audioFile.processingFormat.sampleRate > 0 else { return nil }
                return Double(audioFile.length) / audioFile.processingFormat.sampleRate
            }
        }.value
        var segmentEvidence: [LongFormSegmentExecutionEvidence] = []
        for (index, segment) in plan.evidence.segments.enumerated() {
            let report = index < qualityReports.count ? qualityReports[index] : nil
            segmentEvidence.append(
                LongFormSegmentExecutionEvidence(
                    index: segment.index,
                    segmentID: segment.segmentID,
                    generated: audioPaths[index] != nil,
                    audioDurationSeconds: durations[index],
                    qcPassed: report?.passed,
                    qcRequiredFailures: report?.requiredFailures ?? [],
                    qcWarnings: report?.warnings ?? []
                )
            )
        }
        let manifest = LongFormManifestV4(
            plan: plan.evidence,
            execution: LongFormExecutionEvidence(
                generatedAtUTC: Date().formatted(.iso8601),
                streamingExecution: true,
                segments: segmentEvidence
            ),
            assembly: assembly,
            replacements: replacements
        )
        guard let firstAudioPath = items.compactMap({ $0.audioPath }).first else { return }
        let directory = URL(fileURLWithPath: firstAudioPath).deletingLastPathComponent()
        let digestPrefix = String(plan.evidence.planDigest.prefix(8))
        let manifestURL = directory.appendingPathComponent(
            "long_form_manifest_\(digestPrefix).json",
            isDirectory: false
        )
        guard let data = try? manifest.canonicalJSONData() else { return }
        try? data.write(to: manifestURL, options: .atomic)
    }

}

actor BatchGenerationCancellationState {
    private var isRequested = false

    func request() {
        isRequested = true
    }

    func wasRequested() -> Bool {
        isRequested
    }
}
