import QwenVoiceCore
import QwenVoiceNative
import SwiftUI

struct BatchGenerationSheet: View {
    @Environment(\.generationPerformanceGate) private var performanceGate
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @EnvironmentObject var ttsEngineStore: TTSEngineStore
    @EnvironmentObject var audioPlayer: AudioPlayerViewModel
    @Environment(ModelManagerViewModel.self) var modelManager
    @EnvironmentObject var appCommandRouter: AppCommandRouter
    @Environment(\.dismiss) private var dismiss

    let mode: GenerationMode
    var voice: String?
    var emotion: String?
    var languageHint: String?
    var deliveryProfile: DeliveryProfile? = nil
    var voiceDescription: String?
    var refAudio: String?
    var refText: String?

    @State private var batchText = ""
    @State private var segmentationMode: BatchSegmentationMode = .lineSeparated
    @StateObject private var coordinator = BatchGenerationCoordinator()

    init(
        mode: GenerationMode,
        voice: String? = nil,
        emotion: String? = nil,
        languageHint: String? = nil,
        deliveryProfile: DeliveryProfile? = nil,
        voiceDescription: String? = nil,
        refAudio: String? = nil,
        refText: String? = nil,
        initialText: String = "",
        initialSegmentationMode: BatchSegmentationMode = .lineSeparated
    ) {
        self.mode = mode
        self.voice = voice
        self.emotion = emotion
        self.languageHint = languageHint
        self.deliveryProfile = deliveryProfile
        self.voiceDescription = voiceDescription
        self.refAudio = refAudio
        self.refText = refText
        _batchText = State(initialValue: initialText)
        _segmentationMode = State(initialValue: initialSegmentationMode)
    }

    private var themeColor: Color {
        AppTheme.modeColor(for: mode)
    }

    private var deliverySummary: [String] {
        var summary: [String] = []
        if let emotion, !emotion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            summary.append("Tone: \(emotion)")
        }
        return summary
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let outcome = coordinator.outcome {
                completionView(outcome: outcome)
            } else {
                editorView
            }
        }
        .padding(24)
        .frame(minWidth: 520, minHeight: 440)
        .profileBackground(AppTheme.canvasBackground)
        .onDisappear {
            // The Cancel button is the normal path; this catches programmatic
            // dismissal/window close so a headless batch can't keep the
            // engine's generation slot occupied invisibly.
            coordinator.cancelIfDismissedWhileProcessing()
        }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            guard coordinator.outcome == nil else { return false }
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

    // MARK: - Editor View

    @ViewBuilder
    private var editorView: some View {
        Text("Batch Generation")
            .font(.title.weight(.bold))

        Text("Enter one line per generation, or drag a `.txt` file onto this sheet.")
            .font(.callout)
            .foregroundStyle(.secondary)

        Picker("Segmentation", selection: $segmentationMode) {
            Text("Line-by-line").tag(BatchSegmentationMode.lineSeparated)
            Text("Long form").tag(BatchSegmentationMode.longForm)
        }
        .pickerStyle(.segmented)
        .disabled(coordinator.isProcessing)
        .accessibilityIdentifier("batch_segmentationMode")

        if !deliverySummary.isEmpty {
            GroupBox("Current delivery") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(deliverySummary, id: \.self) { line in
                        Text(line)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityIdentifier("batch_deliverySummary")
        }

        ScriptTextEditor(
            text: $batchText,
            placeholder: "Enter one line per generation...",
            font: .systemFont(ofSize: NSFont.systemFontSize),
            isFocused: .constant(false),
            accessibilityIdentifier: "batch_textEditor"
        )
        .padding(8)
        .frame(minHeight: 220)
        #if QW_UI_LIQUID
        .background {
            if #available(macOS 26, *), !reduceTransparency, !performanceGate {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(.clear)
                    .glassEffect(.regular.tint(AppTheme.smokedGlassTint), in: .rect(cornerRadius: 10))
            } else {
                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color(nsColor: .textBackgroundColor))
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(AppTheme.cardStroke.opacity(0.45), lineWidth: 1)
                }
            }
        }
        #else
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(nsColor: .textBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(AppTheme.cardStroke.opacity(0.45), lineWidth: 1)
        )
        #endif
        .disabled(coordinator.isProcessing)

        if coordinator.isProcessing {
            VStack(alignment: .leading, spacing: 8) {
                ProgressView(value: coordinator.progressSnapshot.displayFraction, total: 1.0)
                    .tint(AppTheme.statusProgressTint)
                Text(progressStatusMessage)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                if !coordinator.progressSnapshot.itemStatusText.isEmpty {
                    Text(coordinator.progressSnapshot.itemStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }

        if !coordinator.itemStates.isEmpty {
            batchItemStatusList(
                coordinator.itemStates,
                title: coordinator.isProcessing ? "Current batch" : "Prepared items"
            )
        }

        if let errorMessage = coordinator.errorMessage {
            Text(errorMessage)
                .foregroundStyle(.red)
                .font(.callout)
        }

        HStack {
            Button("Cancel") {
                coordinator.cancelBatch(
                    dismiss: { dismiss() }
                )
            }
            .buttonStyle(.bordered)
            .disabled(coordinator.isCancelling)
            .keyboardShortcut(.cancelAction)
            .accessibilityIdentifier("batch_cancelButton")

            Spacer()

            Button(coordinator.isCancelling ? "Cancelling..." : (coordinator.isProcessing ? "Processing..." : "Generate All")) {
                startBatch()
            }
            .buttonStyle(.borderedProminent)
            .tint(themeColor)
            .disabled(batchText.isEmpty || coordinator.isProcessing)
            .keyboardShortcut(.defaultAction)
            .accessibilityIdentifier("batch_generateAllButton")
        }
    }

    // MARK: - Completion View

    @ViewBuilder
    private func completionView(outcome: BatchGenerationOutcome) -> some View {
        Spacer()

        VStack(spacing: 16) {
            Image(systemName: completionIconName(for: outcome))
                .font(.system(size: 48))
                .foregroundStyle(completionIconColor(for: outcome))

            Text(completionTitle(for: outcome))
                .font(.title2.weight(.bold))

            Text(completionMessage(for: outcome))
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)

        batchItemStatusList(outcome.items, title: "Batch results")

        Spacer()

        HStack {
            Button("Done") {
                dismiss()
            }
            .buttonStyle(.bordered)
            .keyboardShortcut(.cancelAction)
            .accessibilityIdentifier("batch_doneButton")

            if segmentationMode == .longForm {
                if coordinator.canOperateOnLongFormOutcome,
                   outcome.items.contains(where: { !$0.isSaved }) {
                    Button("Resume Missing Segments") {
                        coordinator.resumeLongForm(engineStore: ttsEngineStore)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("batch_resumeLongFormButton")
                }
            } else {
                if shouldShowRetryRemaining(for: outcome) {
                    Button("Retry Remaining") {
                        retryBatch(with: outcome.retryRemainingLines)
                    }
                    .buttonStyle(.bordered)
                }

                if shouldShowRetryFailed(for: outcome) {
                    Button("Retry Failed") {
                        retryBatch(with: outcome.retryFailedLines)
                    }
                    .buttonStyle(.bordered)
                }
            }

            Spacer()

            if !outcome.savedAudioPaths.isEmpty {
                Button("Reveal Outputs") {
                    revealOutputs(for: outcome.savedAudioPaths)
                }
                .buttonStyle(.bordered)
            }

            Button(outcome.savedAudioPaths.isEmpty ? "Close" : "View History") {
                if outcome.savedAudioPaths.isEmpty {
                    dismiss()
                    return
                }
                dismiss()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    appCommandRouter.navigate(to: .history)
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(themeColor)
            .keyboardShortcut(.defaultAction)
            .disabled(outcome.savedAudioPaths.isEmpty && !shouldShowRetryRemaining(for: outcome) && !shouldShowRetryFailed(for: outcome))
        }
    }

    // MARK: - Helpers

    private var progressStatusMessage: String {
        if coordinator.isCancelling {
            return "Cancelling..."
        }
        let message = coordinator.progressSnapshot.statusMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        return message.isEmpty ? "Preparing batch..." : message
    }

    private func completionMessage(for outcome: BatchGenerationOutcome) -> String {
        switch outcome {
        case .completed(let items):
            let count = items.filter(\.isSaved).count
            return count == 1
                ? "1 clip generated successfully."
                : "\(count) clips generated successfully."
        case .cancelled(let items, let restartFailedMessage):
            let count = items.filter(\.isSaved).count
            let total = items.count
            if count == 0 {
                if let restartFailedMessage, !restartFailedMessage.isEmpty {
                    return "Generation was cancelled before any clips were created. \(restartFailedMessage)"
                }
                return "Generation was cancelled before any clips were created."
            }
            let base = "\(count) of \(total) clips generated before cancellation."
            if let restartFailedMessage, !restartFailedMessage.isEmpty {
                return "\(base) \(restartFailedMessage)"
            }
            return base
        case .failed(let items, let message):
            let completedCount = items.filter(\.isSaved).count
            if completedCount == 0 {
                return "Batch generation stopped before any clips were saved. \(message)"
            }
            return "\(completedCount) of \(items.count) clips were saved before the batch stopped. \(message)"
        }
    }

    private func completionTitle(for outcome: BatchGenerationOutcome) -> String {
        switch outcome {
        case .completed:
            return "Batch Complete"
        case .cancelled:
            return "Batch Cancelled"
        case .failed:
            return "Batch Stopped"
        }
    }

    private func completionIconName(for outcome: BatchGenerationOutcome) -> String {
        switch outcome {
        case .completed:
            return "checkmark.circle.fill"
        case .cancelled:
            return "exclamationmark.circle.fill"
        case .failed:
            return "xmark.octagon.fill"
        }
    }

    private func completionIconColor(for outcome: BatchGenerationOutcome) -> Color {
        switch outcome {
        case .completed:
            return AppTheme.accent
        case .cancelled:
            return .orange
        case .failed:
            return .red
        }
    }

    @ViewBuilder
    private func batchItemStatusList(_ items: [BatchGenerationItemState], title: String) -> some View {
        if !items.isEmpty {
            GroupBox(title) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(items) { item in
                            HStack(spacing: 8) {
                                BatchGenerationItemRow(item: item)
                                if segmentationMode == .longForm,
                                   coordinator.canOperateOnLongFormOutcome,
                                   item.isSaved {
                                    Spacer(minLength: 4)
                                    Button("Regenerate") {
                                        coordinator.regenerateLongFormSegment(
                                            item.index,
                                            engineStore: ttsEngineStore
                                        )
                                    }
                                    .buttonStyle(.borderless)
                                    .font(.caption)
                                    .accessibilityIdentifier("batch_regenerateSegment_\(item.index)")
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
                }
                .frame(minHeight: 120, maxHeight: 220)
            }
            .accessibilityIdentifier("batch_itemStatusList")
        }
    }

    private func retryBatch(with lines: [String]) {
        guard !lines.isEmpty else { return }
        batchText = lines.joined(separator: "\n")
        segmentationMode = .lineSeparated
        startBatch()
    }

    private func shouldShowRetryRemaining(for outcome: BatchGenerationOutcome) -> Bool {
        !outcome.retryRemainingLines.isEmpty
    }

    private func shouldShowRetryFailed(for outcome: BatchGenerationOutcome) -> Bool {
        !outcome.retryFailedLines.isEmpty
    }

    private func revealOutputs(for audioPaths: [String]) {
        let urls = audioPaths.map { URL(fileURLWithPath: $0) }
        NSWorkspace.shared.activateFileViewerSelecting(urls)
    }

    private func startBatch() {
        coordinator.startBatch(
            batchText: batchText,
            segmentationMode: segmentationMode,
            requestBuilder: { lines in
                guard let model = TTSModel.model(for: mode) else { return nil }
                return BatchGenerationRequest(
                    mode: mode,
                    model: model,
                    lines: lines,
                    segmentationMode: segmentationMode,
                    voice: voice,
                    emotion: emotion,
                    languageHint: languageHint,
                    voiceDescription: voiceDescription,
                    refAudio: refAudio,
                    refText: refText
                )
            },
            isModelAvailable: { model in
                modelManager.isAvailable(model)
            },
            recoveryDetail: { model in
                modelManager.recoveryDetail(for: model)
            },
            engineStore: ttsEngineStore
        )
    }
}

private struct BatchGenerationItemRow: View {
    let item: BatchGenerationItemState

    private var statusColor: Color {
        switch item.status {
        case .pending:
            return .secondary
        case .running:
            return AppTheme.statusProgressTint
        case .saved:
            return .green
        case .failed:
            return .red
        case .cancelled:
            return .orange
        }
    }

    private var statusIcon: String {
        switch item.status {
        case .pending:
            return "circle.dashed"
        case .running:
            return "waveform.circle.fill"
        case .saved:
            return "checkmark.circle.fill"
        case .failed:
            return "xmark.circle.fill"
        case .cancelled:
            return "pause.circle.fill"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Label(item.statusLabel, systemImage: statusIcon)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(statusColor)

                Text("Line \(item.index + 1)")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()
            }

            Text(item.line)
                .font(.callout)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let statusMessage = item.statusMessage {
                Text(statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let audioPath = item.audioPath {
                Text(URL(fileURLWithPath: audioPath).lastPathComponent)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(AppTheme.cardFill)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(statusColor.opacity(0.18), lineWidth: 1)
        )
    }
}
