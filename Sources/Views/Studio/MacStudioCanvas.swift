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
    /// The iOS canvas gutter, which is the app's screen gutter token. The
    /// composer uses it, the chip row and the dock use it, so the script, the
    /// chips and the Generate button share one left edge — the spine the
    /// whole screen hangs from.
    static let horizontalInset: CGFloat = MacTheme.Spacing.xl
    /// Floor for the dock box (the iOS `compactDockAreaHeight`), so the
    /// silhouette does not jump between the idle CTA and the generating bar:
    /// the primary control plus one step of air under it.
    static let dockMinHeight: CGFloat = MacControl.primary.height + MacTheme.Spacing.sm
    /// Six lines of the 22 pt face plus the editor's vertical insets: the
    /// floor below which the script never shrinks, even in the shortest
    /// window. Above it the script takes every point the chips and the dock do
    /// not, because it is the one region this product exists to host and it
    /// was the one region that could not grow.
    static let composerMinHeight: CGFloat = 176
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
        canvasColumn
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(shortcutBridge)
    }

    private var canvasColumn: some View {
        VStack(alignment: .leading, spacing: 0) {
            composerPad

            VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
                // Lock voice, delivery and language while a take is in flight
                // (the request already captured them); re-enabled on complete.
                // `setupChips` must be a flat list of chips. A nested layout
                // here breaks quietly: a Layout measures its subviews at
                // unspecified width, so an inner flow reports the rows it would
                // take unconstrained and the outer one reserves that height,
                // while the inner one wraps to more rows at the real width and
                // draws over whatever follows.
                MacChipFlow(spacing: MacTheme.Spacing.sm) {
                    setupChips
                }
                .disabled(genState.isGenerationActive)
                .opacity(genState.isGenerationActive ? VocelloTheme.Opacity.dimmed : 1)
                .appAnimation(MacTheme.Motion.stateChange, value: genState.isGenerationActive)

                footer
            }
            .padding(.horizontal, MacStudioMetrics.horizontalInset)
            .padding(.bottom, MacTheme.Spacing.snug)
            // Accessibility containers: the screen root carries `screen_<mode>`
            // and SwiftUI hands that identifier to every descendant element
            // that is not inside a container, which would erase the chip,
            // readiness and dock identifiers the lanes read.
            .accessibilityElement(children: .contain)

            dockArea
                .frame(minHeight: MacStudioMetrics.dockMinHeight, alignment: .top)
                .padding(.horizontal, MacStudioMetrics.horizontalInset)
                .padding(.bottom, MacTheme.Spacing.lg)
                .accessibilityElement(children: .contain)

        }
        .frame(maxWidth: MacStudioMetrics.contentMaxWidth)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .appAnimation(MacTheme.Motion.stateChange, value: genState)
    }

    // MARK: - Composer pad

    /// No card, no border, and the emptiness under a short script is the
    /// point: `IOSStudioCanvas.composerPad` says "No card background, no
    /// border. The composer fills available vertical space", and this is that
    /// composer adapted to a window. A design review asked for a container
    /// here, on the grounds that the primary input has none while Voice
    /// Design's secondary brief field does. Declined: the reference world
    /// deliberately has none, and the brief outranks the reviewer.
    private var composerPad: some View {
        VStack(alignment: .leading, spacing: 0) {
            MacScriptTextEditor(
                text: $script,
                placeholder: placeholder,
                font: .systemFont(ofSize: MacType.style(.script).size, weight: .medium),
                isFocused: $isScriptFocused,
                tracking: MacType.style(.script).tracking
            )
            .frame(maxWidth: .infinity)
            .frame(minHeight: MacStudioMetrics.composerMinHeight, maxHeight: .infinity)

            // The meta line sits right under the script, above the chips:
            // mode, readiness, Clear, count.
            HStack(alignment: .center, spacing: MacTheme.Spacing.md) {
                HStack(spacing: MacTheme.Spacing.tight) {
                    Text(modeMetaLabel)
                        .macType(.captionEmphasis)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .accessibilityIdentifier("textInput_modeMetaLabel")

                    readinessCaption
                }
                .layoutPriority(1)

                Spacer(minLength: MacTheme.Spacing.sm)

                if !script.isEmpty {
                    Button(MacInterfaceText.studioClearScript) {
                        script = ""
                    }
                    .buttonStyle(.plain)
                    .macType(.buttonLabel)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .fixedSize()
                    .accessibilityIdentifier("textInput_clearButton")
                }

                characterCount
                    .fixedSize()
            }
            .padding(.top, MacTheme.Spacing.xs)
            .padding(.bottom, MacTheme.Spacing.snug)
        }
        .padding(.horizontal, MacStudioMetrics.horizontalInset)
        .padding(.top, MacTheme.Spacing.md)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("\(accessibilityPrefix)_script")
    }

    /// Readiness as one caption after a separator dot, the shape the phone
    /// uses for Voice Cloning. The glyph appears only when the mode is not
    /// ready, so state is never carried by color alone.
    private var readinessCaption: some View {
        HStack(spacing: MacTheme.Spacing.xs) {
            Text(verbatim: "·")
                .macType(.captionEmphasis)
                .foregroundStyle(MacTheme.Text.tertiary)
                .accessibilityHidden(true)

            if !readiness.isReady {
                Image(systemName: "clock")
                    .macType(.captionEmphasis)
                    .foregroundStyle(MacTheme.Text.tertiary)
                    .accessibilityHidden(true)
            }

            Text(readiness.title)
                .macType(.captionEmphasis)
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
            .macType(.counter)
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
        VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
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
        HStack(spacing: MacTheme.Spacing.sm) {
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
            HStack(spacing: MacTheme.Spacing.md) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: MacControl.field.glyph, weight: .semibold))
                    .foregroundStyle(MacTheme.Status.guarded)
                    .macControlSquare(.field)
                    .background { Circle().fill(MacTheme.Status.guarded.opacity(0.14)) }
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                    Text(MacInterfaceText.studioGenerationFailed)
                        .macType(.rowTitle)
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)
                    Text(message)
                        .macType(.rowMeta)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }

                Spacer(minLength: MacTheme.Spacing.sm)

                Image(systemName: "arrow.clockwise")
                    .font(.system(size: MacControl.field.glyph, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, MacTheme.Spacing.lg)
            .frame(maxWidth: .infinity)
            .macControlHeight(.primary)
            .background { VocelloShape.pill().fill(Color.white.opacity(0.04)) }
            .overlay { VocelloShape.pill().stroke(MacTheme.Status.guarded.opacity(0.30), lineWidth: VocelloTheme.Stroke.hairline) }
            .contentShape(VocelloShape.pill())
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
        HStack(spacing: MacTheme.Spacing.snug) {
            VocelloStaticWaveformThumbnail(seed: 42, barCount: 28, tint: tint)
                .frame(height: 32)
                .accessibilityHidden(true)

            VStack(alignment: .trailing, spacing: MacTheme.Spacing.xs) {
                Text(MacInterfaceText.statusGenerating)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                Text(generatingSubline)
                    .macType(.rowMeta)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
            }

            Button(action: onCancel) {
                Image(systemName: "stop.fill")
                    .font(.system(size: MacControl.row.glyph, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .macControlSquare(.row)
                    .background { Circle().fill(MacTheme.Surface.glassSurfaceMuted.opacity(0.7)) }
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(MacInterfaceText.studioStopGenerating)
            .accessibilityIdentifier("textInput_cancelButton")
        }
        .padding(.horizontal, MacTheme.Spacing.lg)
        .frame(maxWidth: .infinity)
        .macControlHeight(.primary)
        .background { VocelloShape.pill().fill(Color.white.opacity(0.04)) }
        .overlay { VocelloShape.pill().stroke(Color.white.opacity(0.10), lineWidth: VocelloTheme.Stroke.hairline) }
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
                .font(.system(size: MacControl.primary.glyph, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(MacTheme.Text.primary)
                .macControlSquare(.primary)
                .background { shape.fill(fillStyle) }
                .overlay { shape.stroke(Color.white.opacity(0.12), lineWidth: VocelloTheme.Stroke.hairline) }
                .overlay { shape.inset(by: 0.65).stroke(Color.white.opacity(0.04), lineWidth: VocelloTheme.Stroke.hairline) }
                .shadow(
                    color: reduceTransparency ? .clear : VocelloTheme.Elevation.glowColor(tint),
                    radius: VocelloTheme.Elevation.glowRadius,
                    y: VocelloTheme.Elevation.glowY
                )
                .contentShape(shape)
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : VocelloTheme.Opacity.disabled)
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
