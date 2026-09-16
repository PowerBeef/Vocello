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
    /// The Studio column. The phone's canvas is 390 pt; at 640 the three
    /// chips and the Generate button keep the phone's proportions and the
    /// 22 pt script keeps a comfortable line length.
    static let contentMaxWidth: CGFloat = 640
    /// The iOS canvas gutter. The composer uses it, the chip row and the dock
    /// use it, so the script, the chips and the Generate button share one
    /// left edge — the spine the whole screen hangs from.
    static let horizontalInset: CGFloat = 20
    /// Floor for the dock box (the iOS `compactDockAreaHeight`), so the
    /// silhouette does not jump between the idle CTA and the generating bar.
    static let dockMinHeight: CGFloat = 64
    /// Six lines of the 22 pt face plus the editor's vertical insets. The
    /// desktop composer is a bounded area that grows with its text instead of
    /// the phone's flexible pad, because a Mac window has no thumb zone to
    /// justify pinning the controls to the bottom of a void.
    static let composerMinHeight: CGFloat = 176
    /// Share of the canvas the composer may take before it scrolls internally.
    static let composerMaxFraction: CGFloat = 0.55
    /// The dock's square Batch button: the CTA's height, the stage radius.
    static let batchButtonSize: CGFloat = 56
}

/// Readiness of the current mode, rendered as one caption beside the mode
/// label — where the phone puts it for Voice Cloning, and the only place it
/// appears at all. The accessibility value is "Ready" or "Waiting" (capital R
/// is what the lanes match).
struct MacStudioReadinessState: Equatable {
    let isReady: Bool
    let title: String
    let detail: String
    let accessibilityIdentifier: String

    init(isReady: Bool, title: String, detail: String, accessibilityIdentifier: String) {
        self.isReady = isReady
        self.title = title
        self.detail = detail
        self.accessibilityIdentifier = accessibilityIdentifier
    }
}

/// The unified Studio surface (the iOS `IOSStudioCanvas`, arranged for a
/// desktop): the composer on top, sized to its text between a six-line floor
/// and a ceiling; the meta line; the setup-chip row; the dock with the
/// Generate CTA and the Batch button, the generating bar, the error bar or the
/// player card depending on `genState`; then whatever space is left. Per-mode
/// screens provide the chips and own the generation logic through the
/// closures; the canvas is stateless from a generation point of view. Every
/// `textInput_*` identifier is the lane contract.
struct MacStudioCanvas<SetupChips: View, Footer: View>: View {
    let mode: GenerationMode
    /// Identifier prefix of the mode's container ids (`customVoice_script`).
    let accessibilityPrefix: String
    @Binding var script: String
    let placeholder: String
    let modeMetaLabel: String
    let readiness: MacStudioReadinessState
    let tint: Color
    let genState: MacStudioGenState
    let errorMessage: String?
    let canGenerate: Bool
    let canRunBatch: Bool
    let modelInstalled: Bool
    let setupChips: SetupChips
    /// Rows under the chip row (custom tone field, hints, warnings). Empty on
    /// a ready Built-in Voice screen, which is why that screen renders exactly
    /// the phone's composition.
    let footer: Footer
    let onGenerate: () -> Void
    let onBatch: () -> Void
    let onCancel: () -> Void
    let onInstallModel: () -> Void
    let onPlayerDismiss: () -> Void

    @State private var isScriptFocused = false
    /// Height of the laid-out script, reported by the editor bridge.
    @State private var scriptContentHeight: CGFloat = 0

    init(
        mode: GenerationMode,
        accessibilityPrefix: String,
        script: Binding<String>,
        placeholder: String,
        modeMetaLabel: String,
        readiness: MacStudioReadinessState,
        tint: Color,
        genState: MacStudioGenState,
        errorMessage: String? = nil,
        canGenerate: Bool,
        canRunBatch: Bool,
        modelInstalled: Bool,
        @ViewBuilder setupChips: () -> SetupChips,
        @ViewBuilder footer: () -> Footer,
        onGenerate: @escaping () -> Void,
        onBatch: @escaping () -> Void,
        onCancel: @escaping () -> Void,
        onInstallModel: @escaping () -> Void,
        onPlayerDismiss: @escaping () -> Void
    ) {
        self.mode = mode
        self.accessibilityPrefix = accessibilityPrefix
        _script = script
        self.placeholder = placeholder
        self.modeMetaLabel = modeMetaLabel
        self.readiness = readiness
        self.tint = tint
        self.genState = genState
        self.errorMessage = errorMessage
        self.canGenerate = canGenerate
        self.canRunBatch = canRunBatch
        self.modelInstalled = modelInstalled
        self.setupChips = setupChips()
        self.footer = footer()
        self.onGenerate = onGenerate
        self.onBatch = onBatch
        self.onCancel = onCancel
        self.onInstallModel = onInstallModel
        self.onPlayerDismiss = onPlayerDismiss
    }

    var body: some View {
        // Pinned to the viewport: every child receives a finite proposal and
        // the canvas's own minimum size is zero, so the window never grows to
        // fit the composer; the composer scrolls instead.
        GeometryReader { proxy in
            canvasColumn(canvasHeight: proxy.size.height)
                .frame(width: proxy.size.width, height: proxy.size.height, alignment: .top)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(shortcutBridge)
    }

    private func canvasColumn(canvasHeight: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            composerPad(editorHeight: editorHeight(canvasHeight: canvasHeight))

            VStack(alignment: .leading, spacing: 10) {
                // Lock voice, delivery and language while a take is in flight
                // (the request already captured them); re-enabled on complete.
                MacChipFlow(spacing: 8) {
                    setupChips
                }
                .disabled(genState.isGenerationActive)
                .opacity(genState.isGenerationActive ? 0.5 : 1)
                .appAnimation(MacTheme.Motion.stateChange, value: genState.isGenerationActive)

                footer
            }
            .padding(.horizontal, MacStudioMetrics.horizontalInset)
            .padding(.bottom, 10)
            // Accessibility containers: the screen root carries `screen_<mode>`
            // and SwiftUI hands that identifier to every descendant element
            // that is not inside a container, which would erase the chip,
            // readiness and dock identifiers the lanes read.
            .accessibilityElement(children: .contain)

            dockArea
                .frame(minHeight: MacStudioMetrics.dockMinHeight, alignment: .top)
                .padding(.horizontal, MacStudioMetrics.horizontalInset)
                .padding(.bottom, 16)
                .accessibilityElement(children: .contain)

            // Desktop eyes expect a form to end and space to follow; the
            // phone's void sat between the script and the controls.
            Spacer(minLength: 0)
        }
        .frame(maxWidth: MacStudioMetrics.contentMaxWidth)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .appAnimation(MacTheme.Motion.stateChange, value: genState)
    }

    /// The editor grows with its text between the six-line floor and a share
    /// of the canvas; past the ceiling it scrolls inside its own scroll view.
    private func editorHeight(canvasHeight: CGFloat) -> CGFloat {
        let ceiling = max(MacStudioMetrics.composerMinHeight, (canvasHeight * MacStudioMetrics.composerMaxFraction).rounded(.down))
        return min(max(scriptContentHeight, MacStudioMetrics.composerMinHeight), ceiling)
    }

    // MARK: - Composer pad

    private func composerPad(editorHeight: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            MacScriptTextEditor(
                text: $script,
                placeholder: placeholder,
                font: .systemFont(ofSize: 22, weight: .medium),
                isFocused: $isScriptFocused,
                tracking: -0.22,
                contentHeight: $scriptContentHeight
            )
            .frame(maxWidth: .infinity)
            .frame(height: editorHeight)
            .appAnimation(MacTheme.Motion.stateChange, value: editorHeight)

            // The meta line sits right under the script, above the chips:
            // mode, readiness, Clear, count.
            HStack(alignment: .center, spacing: 12) {
                HStack(spacing: 5) {
                    Text(modeMetaLabel)
                        .font(.caption.weight(.medium))
                        .tracking(0.24)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .accessibilityIdentifier("textInput_modeMetaLabel")

                    readinessCaption
                }
                .layoutPriority(1)

                Spacer(minLength: 8)

                if !script.isEmpty {
                    Button(MacInterfaceText.studioClearScript) {
                        script = ""
                    }
                    .buttonStyle(.plain)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .fixedSize()
                    .accessibilityIdentifier("textInput_clearButton")
                }

                characterCount
                    .fixedSize()
            }
            .padding(.top, 4)
            .padding(.bottom, 10)
        }
        .padding(.horizontal, MacStudioMetrics.horizontalInset)
        .padding(.top, 12)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("\(accessibilityPrefix)_script")
    }

    /// Readiness as one caption after a separator dot, the shape the phone
    /// uses for Voice Cloning. The glyph appears only when the mode is not
    /// ready, so state is never carried by color alone.
    private var readinessCaption: some View {
        HStack(spacing: 4) {
            Text(verbatim: "·")
                .font(.caption.weight(.medium))
                .foregroundStyle(MacTheme.Text.tertiary)
                .accessibilityHidden(true)

            if !readiness.isReady {
                Image(systemName: "clock")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.tertiary)
                    .accessibilityHidden(true)
            }

            Text(readiness.title)
                .font(.caption.weight(.medium))
                .tracking(0.24)
                .foregroundStyle(readiness.isReady ? MacTheme.Text.secondary : MacTheme.Text.tertiary)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(readiness.title)
        .accessibilityValue(readiness.isReady ? "Ready" : "Waiting")
        .accessibilityHint(readiness.detail)
        .accessibilityIdentifier(readiness.accessibilityIdentifier)
    }

    /// The phone's counter: written against the shared script ceiling, so the
    /// number means the same thing on both platforms. The spoken value keeps
    /// the "N characters" phrasing.
    private var characterCount: some View {
        let state = GenerationTextLimitPolicy.state(for: script, mode: mode)
        let spoken = MacInterfaceText.textInputCharacterCount(String(state.count))
        return Text(verbatim: "\(state.count) / \(state.displayLimit)")
            .font(.caption.weight(.medium).monospacedDigit())
            .foregroundStyle(state.isOverLimit ? MacTheme.Status.guarded : MacTheme.Text.secondary)
            .accessibilityLabel(spoken)
            .accessibilityValue(spoken)
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
                    errorBar(errorMessage)
                }
                actionRow
            }
        }
    }

    /// Generate takes the width; Batch, the desktop's own action, is a square
    /// of the same height at its right end rather than a setup chip (it does
    /// not describe the take, and as a chip it wrapped the row).
    private var actionRow: some View {
        HStack(spacing: 8) {
            if modelInstalled {
                generateCTA
            } else {
                installCTA
            }
            MacStudioBatchButton(tint: tint, isEnabled: canRunBatch && modelInstalled, action: onBatch)
        }
    }

    private var installCTA: some View {
        MacPrimaryCTAButton(
            title: MacInterfaceText.shellModelMissingHint,
            symbol: "arrow.down.circle.fill",
            tint: tint,
            size: .dock,
            action: onInstallModel
        )
        .accessibilityIdentifier("textInput_installModelButton")
    }

    /// The phone's error bar: one capsule the height of the CTA that retries
    /// when clicked, rather than a block of text above a separate button.
    private func errorBar(_ message: String) -> some View {
        Button(action: onGenerate) {
            HStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(MacTheme.Status.guarded)
                    .frame(width: 34, height: 34)
                    .background { Circle().fill(MacTheme.Status.guarded.opacity(0.14)) }
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 2) {
                    Text(MacInterfaceText.studioGenerationFailed)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)
                    Text(message)
                        .font(.caption2)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }

                Spacer(minLength: 8)

                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity)
            .frame(height: 56)
            .background { Capsule(style: .continuous).fill(Color.white.opacity(0.04)) }
            .overlay { Capsule(style: .continuous).stroke(MacTheme.Status.guarded.opacity(0.30), lineWidth: 0.7) }
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
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
            size: .dock,
            shortcutHint: "⌘↩",
            action: onGenerate
        )
        .accessibilityIdentifier("textInput_generateButton")
    }

    private var generatingBar: some View {
        HStack(spacing: 10) {
            VocelloStaticWaveformThumbnail(seed: 42, barCount: 28, tint: tint)
                .frame(height: 32)
                .accessibilityHidden(true)

            VStack(alignment: .trailing, spacing: 2) {
                Text(MacInterfaceText.statusGenerating)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(generatingSubline)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
            }

            Button(action: onCancel) {
                Image(systemName: "stop.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background { Circle().fill(MacTheme.Surface.glassSurfaceMuted.opacity(0.7)) }
                    .contentShape(Circle())
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

/// The desktop's Batch entry as the square at the right end of the Generate
/// row: the CTA's height, the chip's chrome, `textInput_batchButton`.
struct MacStudioBatchButton: View {
    let tint: Color
    let isEnabled: Bool
    let action: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        let shape = VocelloShape.stage()
        Button(action: action) {
            Image(systemName: "list.bullet.rectangle")
                .font(.system(size: 18, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(MacTheme.Text.primary)
                .frame(width: MacStudioMetrics.batchButtonSize, height: MacStudioMetrics.batchButtonSize)
                .background { shape.fill(fillStyle) }
                .overlay { shape.stroke(Color.white.opacity(0.12), lineWidth: 0.8) }
                .overlay { shape.inset(by: 0.65).stroke(Color.white.opacity(0.04), lineWidth: 0.55) }
                .shadow(color: reduceTransparency ? .clear : tint.opacity(0.28), radius: 8, y: 1)
                .contentShape(shape)
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.45)
        .vocelloFocusRing(tint, radius: MacTheme.Radius.stage)
        .help(MacInterfaceText.textInputBatch)
        .accessibilityLabel(MacInterfaceText.textInputBatch)
        .accessibilityIdentifier("textInput_batchButton")
    }

    private var fillStyle: AnyShapeStyle {
        if reduceTransparency {
            return AnyShapeStyle(tint.opacity(0.22))
        }
        return AnyShapeStyle(
            LinearGradient(
                colors: [tint.opacity(0.30), tint.opacity(0.14)],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }
}
