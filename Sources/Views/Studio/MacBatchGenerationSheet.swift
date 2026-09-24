import AppKit
import QwenVoiceCore
import SwiftUI

/// The batch sheet of the three Studio screens: line-by-line batches run on
/// `MacLineBatchRunner` (one ordinary take per line on the shared single-take
/// executor) and long-form projects on the shared `IOSLongFormCoordinator`
/// with the desktop platform hooks; both live on `MacAppModel` and run under
/// the mode's `StudioGenerationCoordinator`, so the canvas behind the sheet
/// locks and shows the live card exactly as during a single take. The sheet
/// only projects their state. Resume and per-segment regeneration follow the
/// iOS semantics (resume after a stopped project, regenerate after a
/// completed one) and survive closing the sheet. Every `batch_*` identifier is
/// the lane contract.
struct MacBatchGenerationSheet: View {
    let configuration: MacBatchSheetConfiguration

    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var appCommandRouter: AppCommandRouter
    @Environment(ModelManagerViewModel.self) private var modelManager
    @Environment(MacAppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    @State private var batchText: String
    @State private var segmentationMode: MacBatchSegmentationMode
    @State private var isEditorFocused = false
    @State private var validationMessage: String?
    /// A retained long-form outcome stays behind the editor while the sheet
    /// holds a script the user brought (routed from the composer, typed or
    /// dropped); starting, resuming or regenerating from this sheet shows it.
    @State private var hidesRetainedLongFormOutcome: Bool
    @State private var hasStartedFromThisSheet = false
    @State private var longFormCancelRequested = false
    @ScaledMetric(relativeTo: .largeTitle) private var completionIconSize: CGFloat = 48

    init(configuration: MacBatchSheetConfiguration) {
        self.configuration = configuration
        _batchText = State(initialValue: configuration.initialText)
        _segmentationMode = State(initialValue: configuration.initialSegmentationMode)
        _hidesRetainedLongFormOutcome = State(initialValue: !configuration.initialText.isEmpty)
    }

    // MARK: - Owners

    private var mode: GenerationMode { configuration.mode }
    private var lineBatch: MacLineBatchRunner { appModel.lineBatch }
    private var longForm: IOSLongFormCoordinator { appModel.longForm }
    private var coordinator: StudioGenerationCoordinator { appModel.coordinator(for: mode) }
    private var model: TTSModel? { modelManager.generationActiveVariant(for: mode) }
    private var tint: Color { VocelloTheme.Brand.modeColor(mode) }
    private var presentation: VocelloPresentationText {
        VocelloPresentationText(localization: MacInterfaceLanguage.current)
    }

    // MARK: - Projection

    private var isLongForm: Bool { segmentationMode == .longForm }
    private var longFormOwnsMode: Bool { longForm.lastMode == mode }
    private var lineBatchOwnsMode: Bool { lineBatch.lastMode == mode }

    private var isProcessing: Bool {
        isLongForm ? (longForm.isProcessing && longFormOwnsMode) : (lineBatch.isProcessing && lineBatchOwnsMode)
    }

    private var isCancelling: Bool {
        isLongForm ? (isProcessing && longFormCancelRequested) : lineBatch.isCancelling
    }

    private var rows: [MacBatchRow] {
        if isLongForm {
            return longFormOwnsMode ? longForm.segments.map { MacBatchRow(segment: $0, presentation: presentation) } : []
        }
        return lineBatchOwnsMode ? lineBatch.items.map(MacBatchRow.init(item:)) : []
    }

    private var presentedOutcome: MacBatchOutcomePresentation? {
        if isLongForm {
            // A running project (including a regeneration over a retained
            // outcome) always shows the editor's progress, never an outcome.
            guard longFormOwnsMode, !longForm.isProcessing, !hidesRetainedLongFormOutcome,
                  let outcome = longForm.outcome else { return nil }
            return MacBatchOutcomePresentation(longForm: outcome, presentation: presentation)
        }
        guard lineBatchOwnsMode, let outcome = lineBatch.outcome else { return nil }
        return MacBatchOutcomePresentation(line: outcome)
    }

    private var completedCount: Int {
        isLongForm ? longForm.progress.completedCount : lineBatch.progress.completedCount
    }

    private var totalCount: Int {
        isLongForm ? longForm.progress.totalCount : lineBatch.progress.totalCount
    }

    private var progressFraction: Double {
        isLongForm ? longForm.progress.fraction : lineBatch.progress.fraction
    }

    private var progressStatusMessage: String {
        if isCancelling { return MacInterfaceText.batchCancelling }
        let message = (isLongForm ? longForm.progress.statusMessage : lineBatch.progress.statusMessage)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return message.isEmpty ? MacInterfaceText.batchPreparing : message
    }

    private var errorLine: String? {
        if let validationMessage { return validationMessage }
        guard hasStartedFromThisSheet else { return nil }
        return coordinator.errorMessage
    }

    private var canResumeLongForm: Bool {
        isLongForm && longFormOwnsMode && longForm.canResume
    }

    private var canRegenerateSegments: Bool {
        isLongForm && longFormOwnsMode && longForm.canRegenerateSegments
    }

    private var canStart: Bool {
        !batchText.isEmpty && !isProcessing && !lineBatch.isProcessing && !longForm.isProcessing
    }

    private var displayVoiceName: String {
        switch mode {
        case .custom:
            let speaker = configuration.voice ?? ""
            return TTSModel.speakerDescriptor(id: speaker)?.displayName ?? speaker.capitalized
        case .design:
            let brief = (configuration.voiceDescription ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return brief.isEmpty ? MacInterfaceText.designVoiceBriefLabel : SavedVoiceNameSuggestion.designResultName(from: brief)
        case .clone:
            if let voice = configuration.voice { return voice }
            if let refAudio = configuration.refAudio {
                return URL(fileURLWithPath: refAudio).deletingPathExtension().lastPathComponent
            }
            return MacInterfaceText.modeName(.clone)
        }
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.lg) {
            if let outcome = presentedOutcome {
                completionView(outcome)
            } else {
                editorView
            }
        }
        .padding(MacTheme.Spacing.xxl)
        .frame(minWidth: 520, minHeight: 440)
        .background(MacTheme.canvasGradient.ignoresSafeArea())
        .onAppear {
            if !lineBatch.isProcessing {
                lineBatch.reset()
            }
        }
        .onDisappear {
            // The Cancel button is the normal path; this catches programmatic
            // dismissal and window close so a headless batch cannot keep the
            // engine's generation slot occupied invisibly.
            if lineBatch.isProcessing, lineBatchOwnsMode {
                lineBatch.cancelIfDismissedWhileProcessing(
                    ttsEngine: ttsEngineStore, audioPlayer: audioPlayer, studioCoordinator: coordinator
                )
            }
            if longForm.isProcessing, longFormOwnsMode {
                longForm.cancel(ttsEngine: ttsEngineStore, audioPlayer: audioPlayer, studioCoordinator: coordinator)
            }
        }
        .onChange(of: batchText) { _, _ in
            hidesRetainedLongFormOutcome = true
        }
        .onChange(of: longForm.isProcessing) { _, isProcessing in
            if !isProcessing { longFormCancelRequested = false }
        }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            guard presentedOutcome == nil, !isProcessing else { return false }
            guard let provider = providers.first else { return false }
            provider.loadItem(forTypeIdentifier: "public.file-url", options: nil) { data, _ in
                guard let data = data as? Data,
                      let url = URL(dataRepresentation: data, relativeTo: nil),
                      url.pathExtension == "txt",
                      let text = try? String(contentsOf: url, encoding: .utf8)
                else { return }
                Task { @MainActor in
                    batchText = text
                }
            }
            return true
        }
    }

    // MARK: - Editor

    @ViewBuilder
    private var editorView: some View {
        Text(MacInterfaceText.batchTitle)
            .macType(.sheetTitle)
            .foregroundStyle(MacTheme.Text.primary)

        Text(MacInterfaceText.batchInstructions)
            .macType(.body)
            .foregroundStyle(MacTheme.Text.secondary)

        Text(isLongForm ? MacInterfaceText.batchLongFormMode : MacInterfaceText.batchLineByLine)
            .macType(.captionEmphasis)
            .foregroundStyle(tint)
            .accessibilityIdentifier("batch_segmentationMode")

        if let emotion = configuration.emotion?.trimmingCharacters(in: .whitespacesAndNewlines), !emotion.isEmpty {
            GroupBox(MacInterfaceText.batchCurrentDelivery) {
                Text(MacInterfaceText.batchToneSummary(emotion))
                    .foregroundStyle(MacTheme.Text.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityIdentifier("batch_deliverySummary")
        }

        MacScriptTextEditor(
            text: $batchText,
            placeholder: MacInterfaceText.batchPlaceholder,
            font: .systemFont(ofSize: NSFont.systemFontSize),
            isFocused: $isEditorFocused,
            accessibilityIdentifier: "batch_textEditor"
        )
        .padding(MacTheme.Spacing.sm)
        .frame(minHeight: 220)
        .background {
            VocelloShape.input()
                .fill(MacTheme.Surface.field)
        }
        .overlay {
            VocelloShape.input()
                .stroke(isEditorFocused ? tint.opacity(0.6) : MacTheme.Surface.fieldStroke, lineWidth: isEditorFocused ? 1 : 0.5)
        }
        .appAnimation(MacTheme.Motion.stateChange, value: isEditorFocused)
        .disabled(isProcessing)

        if isProcessing {
            VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
                ProgressView(value: progressFraction, total: 1.0)
                    .tint(MacTheme.accent)
                Text(progressStatusMessage)
                    .macType(.rowMeta)
                    .foregroundStyle(MacTheme.Text.secondary)
                if totalCount > 0 {
                    Text(MacInterfaceText.batchClipsCompleted(String(completedCount), String(totalCount)))
                        .macType(.caption)
                        .foregroundStyle(MacTheme.Text.secondary)
                }
            }
        }

        if !rows.isEmpty {
            itemStatusList(rows, title: isProcessing ? MacInterfaceText.batchCurrentBatch : MacInterfaceText.batchPreparedItems)
        }

        if let errorLine {
            Text(errorLine)
                .foregroundStyle(MacTheme.Status.critical)
                .macType(.rowMeta)
        }

        HStack {
            Button(MacInterfaceText.cancel) {
                if isProcessing {
                    cancelCurrent()
                } else {
                    dismiss()
                }
            }
            .buttonStyle(.bordered)
            .disabled(isCancelling)
            .keyboardShortcut(.cancelAction)
            .accessibilityIdentifier("batch_cancelButton")

            Spacer()

            Button(isCancelling ? MacInterfaceText.batchCancelling : (isProcessing ? MacInterfaceText.batchProcessing : MacInterfaceText.batchGenerateAll)) {
                startBatch()
            }
            .buttonStyle(.borderedProminent)
            .tint(tint)
            .disabled(!canStart)
            .keyboardShortcut(.defaultAction)
            .accessibilityIdentifier("batch_generateAllButton")
        }
    }

    // MARK: - Completion

    @ViewBuilder
    private func completionView(_ outcome: MacBatchOutcomePresentation) -> some View {
        Spacer()

        VStack(spacing: MacTheme.Spacing.lg) {
            Image(systemName: outcome.iconName)
                .font(.system(size: completionIconSize))
                .foregroundStyle(outcome.iconColor)

            Text(outcome.title)
                .macType(.sheetTitle)
                .foregroundStyle(MacTheme.Text.primary)

            Text(outcome.message)
                .macType(.body)
                .foregroundStyle(MacTheme.Text.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)

        itemStatusList(outcome.rows, title: MacInterfaceText.batchResults)

        // A failed outcome's message already carries the failure text.
        if outcome.kind != .failed, let errorLine {
            Text(errorLine)
                .foregroundStyle(MacTheme.Status.critical)
                .macType(.rowMeta)
        }

        Spacer()

        HStack {
            Button(MacInterfaceText.done) {
                dismiss()
            }
            .buttonStyle(.bordered)
            .keyboardShortcut(.cancelAction)
            .accessibilityIdentifier("batch_doneButton")

            Button(MacInterfaceText.batchNewBatch) {
                startNewBatch()
            }
            .buttonStyle(.bordered)

            if isLongForm {
                if canResumeLongForm {
                    Button(MacInterfaceText.batchResumeMissing) {
                        resumeLongForm()
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("batch_resumeLongFormButton")
                }
            } else {
                if !outcome.retryRemainingLines.isEmpty {
                    Button(MacInterfaceText.batchRetryRemaining) {
                        retryBatch(with: outcome.retryRemainingLines)
                    }
                    .buttonStyle(.bordered)
                }

                if !outcome.retryFailedLines.isEmpty {
                    Button(MacInterfaceText.batchRetryFailed) {
                        retryBatch(with: outcome.retryFailedLines)
                    }
                    .buttonStyle(.bordered)
                }
            }

            Spacer()

            if !outcome.savedAudioPaths.isEmpty {
                Button(MacInterfaceText.batchRevealOutputs) {
                    revealOutputs(outcome.savedAudioPaths)
                }
                .buttonStyle(.bordered)
            }

            Button(outcome.savedAudioPaths.isEmpty ? MacInterfaceText.close : MacInterfaceText.batchViewHistory) {
                let showsHistory = !outcome.savedAudioPaths.isEmpty
                dismiss()
                guard showsHistory else { return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    appCommandRouter.navigate(to: .history)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(tint)
            .keyboardShortcut(.defaultAction)
        }
    }

    // MARK: - Rows

    @ViewBuilder
    private func itemStatusList(_ rows: [MacBatchRow], title: String) -> some View {
        if !rows.isEmpty {
            GroupBox(title) {
                ScrollView {
                    VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
                        ForEach(rows) { row in
                            HStack(spacing: MacTheme.Spacing.sm) {
                                MacBatchItemRow(row: row)
                                if canRegenerateSegments, row.isSaved {
                                    Spacer(minLength: 4)
                                    Button(MacInterfaceText.batchRegenerate) {
                                        regenerateSegment(row.index)
                                    }
                                    .buttonStyle(.borderless)
                                    .macType(.caption)
                                    .accessibilityIdentifier("batch_regenerateSegment_\(row.index)")
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, MacTheme.Spacing.xs)
                }
                .frame(minHeight: 120, maxHeight: 220)
            }
            .accessibilityIdentifier("batch_itemStatusList")
        }
    }

    // MARK: - Actions

    private func makeLineBatchRequest(model: TTSModel, lines: [String]) -> MacLineBatchRequest {
        MacLineBatchRequest(
            mode: mode,
            model: model,
            lines: lines,
            voice: configuration.voice,
            emotion: configuration.emotion,
            deliveryInstructionCellID: configuration.deliveryInstructionCellID,
            language: configuration.language,
            voiceDescription: configuration.voiceDescription,
            refAudio: configuration.refAudio,
            refText: configuration.refText,
            preparedVoiceID: configuration.preparedVoiceID,
            displayVoiceName: displayVoiceName
        )
    }

    private func startBatch() {
        guard canStart else { return }
        validationMessage = nil
        guard !ttsEngineStore.hasActiveGeneration else {
            validationMessage = MacInterfaceText.batchBusy
            return
        }
        guard let model else {
            validationMessage = MacInterfaceText.batchModelConfigurationMissing
            return
        }
        switch segmentationMode {
        case .lineSeparated:
            startLineBatch(model: model)
        case .longForm:
            startLongFormProject(model: model)
        }
    }

    private func startLineBatch(model: TTSModel) {
        let lines = MacLineBatchRunner.lines(from: batchText)
        guard !lines.isEmpty else { return }
        guard lines.count <= MacLineBatchRunner.maxLines else {
            validationMessage = MacInterfaceText.batchTooLarge(String(lines.count), String(MacLineBatchRunner.maxLines))
            return
        }
        let request = makeLineBatchRequest(model: model, lines: lines)
        if let error = request.validationError(
            isModelAvailable: modelManager.isAvailable(model),
            recoveryDetail: modelManager.recoveryDetail(for: model)
        ) {
            validationMessage = error
            return
        }
        let started = lineBatch.start(
            request: request,
            ttsEngine: ttsEngineStore,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        if started {
            hasStartedFromThisSheet = true
        } else {
            validationMessage = MacInterfaceText.batchBusy
        }
    }

    private func startLongFormProject(model: TTSModel) {
        let plan: LongFormPlan
        do {
            plan = try IOSLongFormCoordinator.plan(originalText: batchText)
        } catch {
            validationMessage = MacInterfaceText.batchPlanningFailed(error.localizedDescription)
            return
        }
        guard !plan.segments.isEmpty else { return }
        guard plan.segments.count <= IOSLongFormCoordinator.maxSegments else {
            validationMessage = MacInterfaceText.batchTooLarge(String(plan.segments.count), String(IOSLongFormCoordinator.maxSegments))
            return
        }
        let lines = plan.segments.map(\.spokenTextForGeneration)
        if let error = makeLineBatchRequest(model: model, lines: lines).validationError(
            isModelAvailable: modelManager.isAvailable(model),
            recoveryDetail: modelManager.recoveryDetail(for: model)
        ) {
            validationMessage = error
            return
        }
        longForm.start(
            request: IOSLongFormProjectRequest(
                mode: mode,
                model: model,
                plan: plan,
                voice: configuration.voice,
                emotion: configuration.emotion,
                deliveryInstructionCellID: configuration.deliveryInstructionCellID,
                languageHint: configuration.language.rawValue,
                voiceDescription: configuration.voiceDescription,
                refAudio: configuration.refAudio,
                refText: configuration.refText,
                preparedVoiceID: configuration.preparedVoiceID
            ),
            ttsEngine: ttsEngineStore,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        noteLongFormOperationStarted()
    }

    private func resumeLongForm() {
        validationMessage = nil
        longForm.resume(ttsEngine: ttsEngineStore, audioPlayer: audioPlayer, studioCoordinator: coordinator)
        noteLongFormOperationStarted()
    }

    private func regenerateSegment(_ index: Int) {
        validationMessage = nil
        longForm.regenerateSegment(
            index: index,
            ttsEngine: ttsEngineStore,
            audioPlayer: audioPlayer,
            studioCoordinator: coordinator
        )
        noteLongFormOperationStarted()
    }

    /// The coordinator starts synchronously or refuses (busy engine, pending
    /// attempt); the sheet's flags follow what actually happened.
    private func noteLongFormOperationStarted() {
        if longForm.isProcessing, longFormOwnsMode {
            hasStartedFromThisSheet = true
            hidesRetainedLongFormOutcome = false
        } else {
            validationMessage = MacInterfaceText.batchBusy
        }
    }

    /// Back to the editor for another batch; the retained long-form project
    /// keeps its resume and regenerate affordances on the coordinator.
    private func startNewBatch() {
        validationMessage = nil
        if isLongForm {
            hidesRetainedLongFormOutcome = true
        } else {
            lineBatch.reset()
        }
    }

    private func cancelCurrent() {
        if isLongForm {
            if longForm.cancel(ttsEngine: ttsEngineStore, audioPlayer: audioPlayer, studioCoordinator: coordinator) {
                longFormCancelRequested = true
            }
        } else {
            lineBatch.cancel(ttsEngine: ttsEngineStore, audioPlayer: audioPlayer, studioCoordinator: coordinator)
        }
    }

    private func retryBatch(with lines: [String]) {
        guard !lines.isEmpty else { return }
        batchText = lines.joined(separator: "\n")
        segmentationMode = .lineSeparated
        startBatch()
    }

    private func revealOutputs(_ audioPaths: [String]) {
        NSWorkspace.shared.activateFileViewerSelecting(audioPaths.map { URL(fileURLWithPath: $0) })
    }
}

// MARK: - Row model

private struct MacBatchRow: Identifiable, Equatable {
    let id: UUID
    let index: Int
    let line: String
    let status: MacLineBatchItem.Status
    let statusLabel: String

    init(item: MacLineBatchItem) {
        id = item.id
        index = item.index
        line = item.line
        status = item.status
        statusLabel = Self.label(for: item.status, savedLabel: MacInterfaceText.batchStatusSaved)
    }

    init(segment: IOSLongFormSegmentState, presentation: VocelloPresentationText) {
        id = segment.id
        index = segment.index
        line = segment.line
        status = Self.status(of: segment)
        statusLabel = Self.label(for: status, savedLabel: presentation.longFormSegmentGenerated)
    }

    var isSaved: Bool {
        if case .saved = status { return true }
        return false
    }

    var audioPath: String? {
        if case .saved(let audioPath) = status { return audioPath }
        return nil
    }

    var failureMessage: String? {
        if case .failed(let message) = status { return message }
        return nil
    }

    private static func status(of segment: IOSLongFormSegmentState) -> MacLineBatchItem.Status {
        switch segment.status {
        case .pending: return .pending
        case .running: return .running
        case .saved(let audioPath): return .saved(audioPath: audioPath)
        case .failed(let message): return .failed(message: message)
        case .cancelled: return .cancelled
        }
    }

    private static func label(for status: MacLineBatchItem.Status, savedLabel: String) -> String {
        switch status {
        case .pending: return MacInterfaceText.batchStatusPending
        case .running: return MacInterfaceText.batchStatusRunning
        case .saved: return savedLabel
        case .failed: return MacInterfaceText.batchStatusFailed
        case .cancelled: return MacInterfaceText.batchStatusCancelled
        }
    }
}

private struct MacBatchItemRow: View {
    let row: MacBatchRow

    private var statusColor: Color {
        switch row.status {
        case .pending: return MacTheme.Text.secondary
        case .running: return MacTheme.accent
        case .saved: return MacTheme.Status.healthy
        case .failed: return MacTheme.Status.critical
        case .cancelled: return MacTheme.Status.guarded
        }
    }

    private var statusIcon: String {
        switch row.status {
        case .pending: return "circle.dashed"
        case .running: return "waveform.circle.fill"
        case .saved: return "checkmark.circle.fill"
        case .failed: return "xmark.circle.fill"
        case .cancelled: return "pause.circle.fill"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: MacTheme.Spacing.tight) {
            HStack(alignment: .firstTextBaseline, spacing: MacTheme.Spacing.snug) {
                Label(row.statusLabel, systemImage: statusIcon)
                    .macType(.captionEmphasis)
                    .foregroundStyle(statusColor)

                Text(MacInterfaceText.batchLine(String(row.index + 1)))
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)

                Spacer()
            }

            Text(row.line)
                .macType(.rowTitle)
                .foregroundStyle(MacTheme.Text.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let failureMessage = row.failureMessage {
                Text(failureMessage)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let audioPath = row.audioPath {
                Text(URL(fileURLWithPath: audioPath).lastPathComponent)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(MacTheme.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            VocelloShape.card()
                .fill(MacTheme.Surface.card)
        )
        .overlay(
            VocelloShape.card()
                .stroke(statusColor.opacity(0.18), lineWidth: VocelloTheme.Stroke.standard)
        )
    }
}

// MARK: - Outcome presentation

/// One completion view over both runners' outcomes: title, message, icon,
/// rows and the follow-up actions (retry lines only exist for line batches;
/// long-form resume and regeneration come from the coordinator's state).
private struct MacBatchOutcomePresentation {
    enum Kind { case completed, cancelled, failed }

    let kind: Kind
    let title: String
    let message: String
    let rows: [MacBatchRow]
    let savedAudioPaths: [String]
    let retryRemainingLines: [String]
    let retryFailedLines: [String]

    init(line outcome: MacLineBatchOutcome) {
        rows = outcome.items.map(MacBatchRow.init(item:))
        savedAudioPaths = outcome.savedAudioPaths
        retryRemainingLines = outcome.retryRemainingLines
        retryFailedLines = outcome.retryFailedLines
        let savedCount = outcome.items.count(where: \.isSaved)
        let total = outcome.items.count
        switch outcome {
        case .completed:
            kind = .completed
            message = Self.completedMessage(savedCount: savedCount)
        case .cancelled(_, let restartFailedMessage):
            kind = .cancelled
            message = Self.cancelledMessage(savedCount: savedCount, total: total, restartFailedMessage: restartFailedMessage)
        case .failed(_, let failure):
            kind = .failed
            message = Self.failedMessage(savedCount: savedCount, total: total, failure: failure)
        }
        title = Self.title(for: kind)
    }

    init(longForm outcome: IOSLongFormOutcome, presentation: VocelloPresentationText) {
        let segments = outcome.segments
        rows = segments.map { MacBatchRow(segment: $0, presentation: presentation) }
        retryRemainingLines = []
        retryFailedLines = []
        let savedCount = segments.count(where: \.isSaved)
        let total = segments.count
        switch outcome {
        case .completed(_, let joinedAudioPath, _):
            kind = .completed
            savedAudioPaths = segments.compactMap(\.audioPath) + [joinedAudioPath]
            message = Self.completedMessage(savedCount: savedCount)
        case .cancelled:
            kind = .cancelled
            savedAudioPaths = segments.compactMap(\.audioPath)
            message = Self.cancelledMessage(savedCount: savedCount, total: total, restartFailedMessage: nil)
        case .failed(_, let failure):
            kind = .failed
            savedAudioPaths = segments.compactMap(\.audioPath)
            message = Self.failedMessage(savedCount: savedCount, total: total, failure: failure)
        }
        title = Self.title(for: kind)
    }

    var iconName: String {
        switch kind {
        case .completed: return "checkmark.circle.fill"
        case .cancelled: return "exclamationmark.circle.fill"
        case .failed: return "xmark.octagon.fill"
        }
    }

    var iconColor: Color {
        switch kind {
        case .completed: return MacTheme.accent
        case .cancelled: return MacTheme.Status.guarded
        case .failed: return MacTheme.Status.critical
        }
    }

    private static func title(for kind: Kind) -> String {
        switch kind {
        case .completed: return MacInterfaceText.batchComplete
        case .cancelled: return MacInterfaceText.batchCancelledTitle
        case .failed: return MacInterfaceText.batchStoppedTitle
        }
    }

    private static func completedMessage(savedCount: Int) -> String {
        savedCount == 1
            ? MacInterfaceText.batchOneClipGenerated
            : MacInterfaceText.batchClipsGenerated(savedCount)
    }

    private static func cancelledMessage(savedCount: Int, total: Int, restartFailedMessage: String?) -> String {
        let base = savedCount == 0
            ? MacInterfaceText.batchCancelledNone
            : MacInterfaceText.batchCancelledPartial(String(savedCount), String(total))
        if let restartFailedMessage, !restartFailedMessage.isEmpty {
            return "\(base) \(restartFailedMessage)"
        }
        return base
    }

    private static func failedMessage(savedCount: Int, total: Int, failure: String) -> String {
        savedCount == 0
            ? MacInterfaceText.batchStoppedNone(failure)
            : MacInterfaceText.batchStoppedPartial(String(savedCount), String(total), failure)
    }
}
