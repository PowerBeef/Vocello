import AppKit
import QwenVoiceCore
import SwiftUI

/// Generation state the dock renders (the iOS `IOSStudioGenState` without
/// the iOS player-sheet phase).
enum MacStudioGenState: Equatable {
    case idle
    case generating
    /// Live streaming preview is audible while generation is still in flight:
    /// the dock shows the player card, which becomes the `.complete` card in
    /// place when generation finishes.
    case live(IOSStudioLivePreviewItem)
    case complete(IOSStudioInlinePlayerItem)

    var playerPhase: MacStudioPlayerCard.Phase? {
        switch self {
        case .live(let item): .live(item)
        case .complete(let item): .complete(item)
        case .idle, .generating: nil
        }
    }

    /// A take is actively generating; `.complete` is excluded so the user can
    /// retune the chips for the next take while reviewing this one.
    var isGenerationActive: Bool {
        switch self {
        case .generating, .live: true
        case .idle, .complete: false
        }
    }

    var isLivePlayerVisible: Bool {
        if case .live = self { return true }
        return false
    }
}

enum MacStudioMetrics {
    static let contentMaxWidth: CGFloat = 780
    static let horizontalInset: CGFloat = 24
}

/// The unified Studio surface (the iOS `IOSStudioCanvas`): the composer pad
/// on top (flexible height), the setup-chip row, then the dock area that
/// carries the Generate CTA, the generating bar, the error bar or the player
/// card depending on `genState`. Per-mode screens provide the chips and own
/// the generation logic through the closures; the canvas is stateless from a
/// generation point of view. Every `textInput_*` identifier is the lane
/// contract.
struct MacStudioCanvas<SetupChips: View, Footer: View>: View {
    let mode: GenerationMode
    /// Identifier prefix of the mode's container ids (`customVoice_script`).
    let accessibilityPrefix: String
    @Binding var script: String
    let placeholder: String
    let modeMetaLabel: String
    let tint: Color
    let genState: MacStudioGenState
    let errorMessage: String?
    let canGenerate: Bool
    let modelInstalled: Bool
    let setupChips: SetupChips
    /// Rows under the chip row (custom tone field, hints, readiness).
    let footer: Footer
    let onGenerate: () -> Void
    let onCancel: () -> Void
    let onInstallModel: () -> Void
    let onPlayerDismiss: () -> Void

    @State private var isScriptFocused = false

    init(
        mode: GenerationMode,
        accessibilityPrefix: String,
        script: Binding<String>,
        placeholder: String,
        modeMetaLabel: String,
        tint: Color,
        genState: MacStudioGenState,
        errorMessage: String? = nil,
        canGenerate: Bool,
        modelInstalled: Bool,
        @ViewBuilder setupChips: () -> SetupChips,
        @ViewBuilder footer: () -> Footer,
        onGenerate: @escaping () -> Void,
        onCancel: @escaping () -> Void,
        onInstallModel: @escaping () -> Void,
        onPlayerDismiss: @escaping () -> Void
    ) {
        self.mode = mode
        self.accessibilityPrefix = accessibilityPrefix
        _script = script
        self.placeholder = placeholder
        self.modeMetaLabel = modeMetaLabel
        self.tint = tint
        self.genState = genState
        self.errorMessage = errorMessage
        self.canGenerate = canGenerate
        self.modelInstalled = modelInstalled
        self.setupChips = setupChips()
        self.footer = footer()
        self.onGenerate = onGenerate
        self.onCancel = onCancel
        self.onInstallModel = onInstallModel
        self.onPlayerDismiss = onPlayerDismiss
    }

    var body: some View {
        // Pinned to the viewport (as the legacy page scaffold did): every
        // child then receives a finite proposal, and the canvas's own minimum
        // size is zero, so the window never grows to fit the composer.
        GeometryReader { proxy in
            canvasColumn
                .frame(width: proxy.size.width, height: proxy.size.height, alignment: .top)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(shortcutBridge)
    }

    private var canvasColumn: some View {
        VStack(alignment: .leading, spacing: 0) {
            composerPad
                .frame(maxHeight: .infinity)
                .layoutPriority(1)

            VStack(alignment: .leading, spacing: 10) {
                // Lock voice, delivery and language while a take is in flight
                // (the request already captured them); re-enabled on complete.
                HStack(alignment: .center, spacing: 8) {
                    setupChips
                }
                .disabled(genState.isGenerationActive)
                .opacity(genState.isGenerationActive ? 0.5 : 1)
                .appAnimation(MacTheme.Motion.stateChange, value: genState.isGenerationActive)

                footer
            }
            .padding(.horizontal, MacStudioMetrics.horizontalInset)
            .padding(.bottom, 12)
            .layoutPriority(2)

            dockArea
                .padding(.horizontal, MacStudioMetrics.horizontalInset)
                .padding(.bottom, 16)
                .layoutPriority(3)
        }
        .frame(maxWidth: MacStudioMetrics.contentMaxWidth)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .appAnimation(MacTheme.Motion.stateChange, value: genState)
    }

    // MARK: - Composer pad

    private var composerPad: some View {
        VStack(alignment: .leading, spacing: 0) {
            MacScriptTextEditor(
                text: $script,
                placeholder: placeholder,
                font: .systemFont(ofSize: 20, weight: .medium),
                isFocused: $isScriptFocused
            )
            .frame(maxWidth: .infinity, minHeight: 96, maxHeight: .infinity, alignment: .topLeading)

            HStack(alignment: .center, spacing: 12) {
                Text(modeMetaLabel)
                    .font(.caption.weight(.medium))
                    .tracking(0.24)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .accessibilityIdentifier("textInput_modeMetaLabel")

                Spacer(minLength: 8)

                if !script.isEmpty {
                    Button(MacInterfaceText.studioClearScript) {
                        script = ""
                    }
                    .buttonStyle(.plain)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .accessibilityIdentifier("textInput_clearButton")
                }

                characterCount
            }
            .padding(.top, 6)
            .padding(.bottom, 10)
        }
        .padding(.horizontal, MacStudioMetrics.horizontalInset)
        .padding(.top, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("\(accessibilityPrefix)_script")
    }

    /// Pairs the count with a glyph once the script crosses the 500-character
    /// "long" threshold, so the signal is never color alone.
    private var characterCount: some View {
        let count = script.count
        let isLong = count > 500
        let baseLabel = MacInterfaceText.textInputCharacterCount(String(count))
        return HStack(spacing: 6) {
            if isLong {
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .accessibilityHidden(true)
            }
            Text(baseLabel)
                .font(.footnote.monospacedDigit())
                .foregroundStyle(isLong ? MacTheme.Status.guarded : MacTheme.Text.secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(isLong ? "\(baseLabel), long script" : baseLabel)
        .accessibilityIdentifier("textInput_charCount")
    }

    // MARK: - Dock area

    /// The player card is a top-level `if let` (not a `switch` branch) so it
    /// keeps one view identity across live → complete. Unlike the phone, the
    /// desktop keeps the Generate control under a completed card and beside an
    /// error: the next take is one click away and the lanes read
    /// `textInput_generateButton` after every completion.
    @ViewBuilder
    private var dockArea: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let phase = genState.playerPhase {
                MacStudioPlayerCard(
                    phase: phase,
                    tint: tint,
                    onDismiss: onPlayerDismiss,
                    onCancel: onCancel,
                    onRetry: onGenerate
                )
                .id("studioPlayerCard")
            }

            switch genState {
            case .generating, .live:
                if !genState.isLivePlayerVisible {
                    generatingBar
                }
            case .idle, .complete:
                if let errorMessage {
                    errorRow(errorMessage)
                }
                if modelInstalled {
                    generateCTA
                } else {
                    installCTA
                }
            }
        }
    }

    private var installCTA: some View {
        MacPrimaryCTAButton(
            title: MacInterfaceText.shellModelMissingHint,
            symbol: "arrow.down.circle.fill",
            tint: tint,
            action: onInstallModel
        )
        .accessibilityIdentifier("textInput_installModelButton")
    }

    private func errorRow(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(MacTheme.Status.guarded)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(MacInterfaceText.studioGenerationFailed)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)
                .fill(MacTheme.Status.guarded.opacity(0.10))
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(MacInterfaceText.studioGenerationFailed)
        .accessibilityValue(message)
        .accessibilityIdentifier("textInput_generationError")
    }

    private var generateCTA: some View {
        MacPrimaryCTAButton(
            title: MacInterfaceText.textInputGenerate,
            symbol: "sparkles",
            tint: tint,
            isEnabled: canGenerate,
            action: onGenerate
        )
        .accessibilityIdentifier("textInput_generateButton")
    }

    private var generatingBar: some View {
        HStack(spacing: 12) {
            MacStaticWaveformThumbnail(seed: 42, barCount: 28, tint: tint)
                .frame(width: 98, height: 28)
                .accessibilityHidden(true)

            ProgressView()
                .controlSize(.small)

            VStack(alignment: .leading, spacing: 2) {
                Text(MacInterfaceText.statusGenerating)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(generatingSubline)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Text.secondary)
            }

            Spacer(minLength: 0)

            Button(action: onCancel) {
                Label(MacInterfaceText.cancel, systemImage: "stop.fill")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .padding(.horizontal, 12)
                    .frame(height: 30)
                    .background { Capsule(style: .continuous).fill(Color.white.opacity(0.06)) }
                    .overlay { Capsule(style: .continuous).stroke(Color.white.opacity(0.12), lineWidth: 0.5) }
                    .contentShape(Capsule(style: .continuous))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(MacInterfaceText.studioStopGenerating)
            .accessibilityIdentifier("textInput_cancelButton")
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity)
        .frame(height: 56)
        .background { Capsule(style: .continuous).fill(Color.white.opacity(0.04)) }
        .overlay { Capsule(style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 0.5) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("textInput_generatingBar")
    }

    private var generatingSubline: String {
        switch mode {
        case .custom: MacInterfaceText.studioRenderingAudio
        case .design: MacInterfaceText.studioDesigningVoice
        case .clone: MacInterfaceText.studioCloningVoice
        }
    }

    /// ⌘↩ generates while the composer has focus (the legacy shortcut).
    private var shortcutBridge: some View {
        Button(action: onGenerate) { Text(verbatim: "") }
            .keyboardShortcut(.return, modifiers: .command)
            .opacity(0.001)
            .disabled(!canGenerate || genState.isGenerationActive)
            .accessibilityHidden(true)
    }
}

/// Readiness line under the chips (the legacy `WorkflowReadinessNote`):
/// title and detail with a static glyph; the accessibility value is
/// "Ready" or "Waiting" (capital R is what the lanes match).
struct MacStudioReadinessNote: View {
    let isReady: Bool
    let title: String
    let detail: String
    let tint: Color
    var isBusy = false
    let accessibilityIdentifier: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: isBusy ? "waveform" : (isReady ? "checkmark.seal.fill" : "clock"))
                .font(.subheadline)
                .foregroundStyle(isReady || isBusy ? tint : MacTheme.Text.secondary)
                .frame(width: 16, height: 16)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(title)
        .accessibilityValue(isReady ? "Ready" : "Waiting")
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}
