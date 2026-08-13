import SwiftUI
import QwenVoiceCore

private enum IOSStudioCanvasLayout {
    static let tabDockReservation: CGFloat = 97
    static let compactDockAreaHeight: CGFloat = 64
    static let completeDockAreaHeight: CGFloat = 135
    /// Extra dock height when the completed card carries the "Save as voice" button (Voice Design),
    /// matching the card's added button row so the dock expands instead of overlapping the chips.
    static let saveAsVoiceExtraHeight: CGFloat = 52
    static let dockBottomPadding: CGFloat = 8
}

/// Unified Studio surface from design_references/Vocello iOS/studio.jsx.
/// Lays out (top → bottom): composer pad, setup-chip row, dock area with
/// idle / generating / complete states. The composer + meta + counter
/// match the design exactly; the dock area carries the Generate CTA,
/// the generating waveform, or the inline player depending on
/// `genState`.
///
/// Per-mode views provide the setup-chip row content via the
/// `setupChips` view builder and own the actual generation logic
/// through the closures. The canvas is stateless from a generation
/// point of view; it just renders the current `genState`.
struct IOSStudioCanvas<SetupChips: View>: View {
    let mode: GenerationMode
    @Binding var script: String
    let placeholder: String
    let modeMetaLabel: String
    let charLimit: Int
    let tint: Color
    let genState: IOSStudioGenState
    let errorMessage: String?
    let canGenerate: Bool
    let modelInstalled: Bool
    let modelDisplayName: String
    let setupChips: SetupChips
    let onGenerate: () -> Void
    let onCancel: () -> Void
    let onInstallModel: () -> Void
    let onPlayerDismiss: () -> Void
    let onPlayerExpand: (() -> Void)?
    /// When provided (Voice Design), the completed player card shows a "Save as voice" button.
    let onSaveAsVoice: (() -> Void)?
    // Batch generation was removed from iOS (2026-07-02): the affordance was dead UI —
    // `onBatch` was nil at every call site because the native in-process engine doesn't
    // support batch (Jetsam risk). macOS batch is unaffected. If it returns, it must be
    // a sequential streaming implementation validated on device.

    init(
        mode: GenerationMode,
        script: Binding<String>,
        placeholder: String,
        modeMetaLabel: String,
        charLimit: Int = 800,
        tint: Color,
        genState: IOSStudioGenState,
        errorMessage: String? = nil,
        canGenerate: Bool,
        modelInstalled: Bool,
        modelDisplayName: String,
        @ViewBuilder setupChips: () -> SetupChips,
        onGenerate: @escaping () -> Void,
        onCancel: @escaping () -> Void,
        onInstallModel: @escaping () -> Void,
        onPlayerDismiss: @escaping () -> Void,
        onPlayerExpand: (() -> Void)? = nil,
        onSaveAsVoice: (() -> Void)? = nil
    ) {
        self.mode = mode
        self._script = script
        self.placeholder = placeholder
        self.modeMetaLabel = modeMetaLabel
        self.charLimit = charLimit
        self.tint = tint
        self.genState = genState
        self.errorMessage = errorMessage
        self.canGenerate = canGenerate
        self.modelInstalled = modelInstalled
        self.modelDisplayName = modelDisplayName
        self.setupChips = setupChips()
        self.onGenerate = onGenerate
        self.onCancel = onCancel
        self.onInstallModel = onInstallModel
        self.onPlayerDismiss = onPlayerDismiss
        self.onPlayerExpand = onPlayerExpand
        self.onSaveAsVoice = onSaveAsVoice
    }

    // Plain @State (NOT @FocusState): this drives `IOSFlexibleTextEditor`'s
    // UIKit first-responder binding directly, set by the text view's
    // begin/end-editing delegate callbacks. A @FocusState here would never
    // hold its value (it isn't attached to any SwiftUI view via `.focused(...)`),
    // so it reverted to false after a tap and the editor's updateUIView then
    // immediately called resignFirstResponder — the keyboard never stayed up.
    // The sibling composers in IOSGenerationModeViews use the same @State pattern.
    @State private var isScriptFocused = false
    // Honor Reduce Motion for the generating waveform (CLAUDE.md animation rule);
    // injected at RootView. When on, the dock waveform renders frozen.
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    var body: some View {
        // B.3 closed (2026-05-21): composer is now `flex: 1` per the
        // design's `.vc-composer-pad`. The R5 / Phase 2 attempts kept
        // failing because SwiftUI's stock `TextEditor` doesn't
        // negotiate with `.frame(maxHeight: .infinity)` cleanly. The
        // fix that finally worked: a thin UIViewRepresentable<UITextView>
        // (`IOSFlexibleTextEditor` in `Sources/iOS/Studio/`) whose
        // `intrinsicContentSize.height` is `UIView.noIntrinsicMetric`.
        // With that out of the way, composerPad asks for the canvas's
        // leftover height via `.layoutPriority(1)` + maxHeight infinity;
        // chips + dock keep their natural sizes and pin against the
        // bottom safe-area inset chain owned by RootView (Phase 2).
        VStack(alignment: .leading, spacing: 0) {
            composerPad
                .frame(maxHeight: .infinity)
                .layoutPriority(1)
            setupRow
                // Lock voice/delivery/language changes while a take is generating
                // (the in-flight request already captured its config; mutating mid-
                // generation is confusing). Re-enabled at .complete for the next take.
                .disabled(isGenerationActive)
                .opacity(isGenerationActive ? 0.5 : 1)
                .iosAppAnimation(IOSDesignMotion.stateChange, value: isGenerationActive)
                .layoutPriority(2)
            dockArea
                .padding(.horizontal, 16)
                .padding(.bottom, IOSStudioCanvasLayout.dockBottomPadding)
                .frame(height: dockAreaHeight, alignment: .bottom)
                .layoutPriority(3)
        }
        // Bottom clearance: NavigationStack inside RootView doesn't
        // propagate the bottom chrome's safeAreaInset reservation to
        // the canvas cleanly. The React reference reserves 97 pt for
        // the tab dock; Studio's CTA / inline player then bottom-align
        // immediately above that reservation.
        .padding(.bottom, IOSStudioCanvasLayout.tabDockReservation)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        // Keep the composer layout fixed: the keyboard OVERLAYS the bottom
        // (chips + Generate + tab dock stay put, covered) instead of reflowing
        // the whole canvas up into a cramped strip. The composer is the top,
        // flex element so the text you're typing stays visible above the keyboard.
        .ignoresSafeArea(.keyboard, edges: .bottom)
        .iosAppAnimation(IOSDesignMotion.stateChange, value: genState)
    }

    /// A take is actively generating (request in flight or live-streaming).
    /// `.complete` is excluded — reviewing a finished take, the user may retune
    /// the chips for the next generation.
    private var isGenerationActive: Bool {
        switch genState {
        case .generating, .live: return true
        case .idle, .complete: return false
        }
    }

    private var dockAreaHeight: CGFloat {
        switch genState {
        case .complete:
            // Grow to fit the "Save as voice" button (Voice Design) so the dock expands + pushes the
            // chips up, instead of the taller card overflowing upward over them.
            return IOSStudioCanvasLayout.completeDockAreaHeight
                + (onSaveAsVoice != nil ? IOSStudioCanvasLayout.saveAsVoiceExtraHeight : 0)
        case .live:
            // Base height (no save button while streaming) so the live→complete morph stays smooth.
            return IOSStudioCanvasLayout.completeDockAreaHeight
        default:
            return IOSStudioCanvasLayout.compactDockAreaHeight
        }
    }

    // MARK: - Composer pad

    // R2 (2026-05-21): composer rewritten to match
    // `design_references/Vocello iOS/app.css` `.vc-composer-pad` +
    // `.vc-script`:
    //
    //   .vc-composer-pad { flex: 1; padding: 4px 20px 0; min-height: 0 }
    //   .vc-script       { background: transparent; border: none;
    //                      font: 500 22px/30px var(--font-display);
    //                      letter-spacing: -0.01em; padding: 8px 0 }
    //   .vc-script-meta  { font: 500 12px/14px; color: var(--fg-2);
    //                      letter-spacing: 0.02em }
    //
    // No card background, no border. The composer fills available
    // vertical space (canvas body removed its trailing Spacer for
    // exactly this reason). The meta row sits flush below the editor
    // with the mode label on the left and the counter on the right.
    private var composerPad: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .topLeading) {
                if script.isEmpty {
                    Text(placeholder)
                        .font(.system(size: 22, weight: .medium))
                        .tracking(-0.22)            // letter-spacing -0.01em ≈ -0.22pt at 22pt
                        .foregroundStyle(IOSAppTheme.textTertiary)
                        .padding(.top, 8)
                        .allowsHitTesting(false)
                }
                IOSFlexibleTextEditor(
                    text: $script,
                    font: UIFont.systemFont(ofSize: 22, weight: .medium),
                    textColor: IOSAppTheme.textPrimaryUIColor,
                    tintColor: UIColor(tint),
                    isFocused: Binding(
                        get: { isScriptFocused },
                        set: { isScriptFocused = $0 }
                    )
                )
                .accessibilityIdentifier("textInput_textEditor")
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .onChange(of: script) { _, newValue in
                let cap = charLimit + 200
                if newValue.count > cap {
                    script = String(newValue.prefix(cap))
                }
            }

            HStack {
                Text(modeMetaLabel)
                    .iosScaledFont(size: 12, weight: .medium, relativeTo: .caption)
                    .tracking(0.24)               // letter-spacing 0.02em ≈ 0.24pt at 12pt
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .accessibilityIdentifier("textInput_modeMetaLabel")
                Spacer()
                if !script.isEmpty {
                    Button {
                        script = ""
                        isScriptFocused = false
                    } label: {
                        Text("Clear")
                            .iosScaledFont(size: 12, weight: .semibold, relativeTo: .caption)
                            .frame(minWidth: 44, minHeight: 44)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .accessibilityLabel("Clear script")
                    .accessibilityIdentifier(IOSAccessibilityIdentifier.TextInput.clearButton)
                }
                Text("\(script.count) / \(charLimit)")
                    .iosScaledFont(size: 12, weight: .medium, monospacedDigit: true, relativeTo: .caption)
                    .foregroundStyle(script.count > charLimit ? Color.orange : IOSAppTheme.textSecondary)
                    .accessibilityIdentifier("textInput_lengthCount")
            }
            .padding(.top, 4)
            .padding(.bottom, 10)
        }
        .padding(.horizontal, 20)
        .padding(.top, 4)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Setup row

    private var setupRow: some View {
        // Equal-width selector pills that fill the row. The same horizontal
        // padding (16) as the dock area means the 2-or-3 pills together span
        // exactly the Generate button's width below.
        HStack(alignment: .center, spacing: 8) {
            setupChips
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 10)
    }

    // MARK: - Dock area

    @ViewBuilder
    private var dockArea: some View {
        // The player card is a TOP-LEVEL `if let` (not a `switch` branch) so it keeps one
        // stable view identity while `playerPhase` stays non-nil — i.e. the `.live → .complete`
        // change morphs the card's content in place instead of running the card's transition
        // (slide out / slide in). The transition fires only on the true entrance
        // (generating → card) and exit (card → idle).
        if let phase = genState.playerPhase {
            IOSStudioPlayerCard(
                phase: phase,
                tint: tint,
                onDismiss: onPlayerDismiss,
                onCancel: onCancel,
                onExpand: onPlayerExpand,
                onSaveAsVoice: onSaveAsVoice
            )
            .id("studioPlayerCard")
        } else {
            switch genState {
            case .idle where errorMessage != nil:
                errorBar
            case .idle where !modelInstalled:
                installCTA
            case .idle:
                generateCTA
            default:
                generatingBar   // .generating (player states handled above)
            }
        }
    }

    private var installCTA: some View {
        IOSPrimaryCTAButton(
            title: "Install \(modelDisplayName)",
            symbol: "arrow.down.circle.fill",
            tint: tint,
            isEnabled: true,
            action: onInstallModel
        )
        .accessibilityIdentifier("textInput_installModelButton")
    }

    private var errorBar: some View {
        Button {
            IOSHaptics.impact(.medium)
            onGenerate()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(tint)
                    .frame(width: 34, height: 34)
                    .background {
                        Circle().fill(tint.opacity(0.14))
                    }

                VStack(alignment: .leading, spacing: 2) {
                    Text("Generation failed")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    Text(errorMessage ?? "Try again.")
                        .font(.system(size: 11))
                        .foregroundStyle(IOSAppTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 0)

                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary.opacity(canGenerate ? 1 : 0.45))
            }
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity)
            .frame(height: 56)
            .background {
                Capsule(style: .continuous)
                    .fill(Color.white.opacity(0.04))
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(tint.opacity(0.30), lineWidth: 0.7)
            }
        }
        .buttonStyle(.plain)
        .disabled(!canGenerate)
        .accessibilityIdentifier("textInput_generationError")
    }

    private var generateCTA: some View {
        IOSPrimaryCTAButton(
            title: "Generate",
            symbol: "sparkles",
            tint: tint,
            isEnabled: canGenerate,
            action: {
                IOSHaptics.impact(.medium)
                onGenerate()
            }
        )
        .accessibilityIdentifier("textInput_generateButton")
    }

    private var generatingBar: some View {
        HStack(spacing: 10) {
            IOSWaveformBars(
                seed: 42,
                barCount: 28,
                tint: tint,
                progress: 1.0,
                isAnimating: true
            )
            .frame(height: 32)

            VStack(alignment: .trailing, spacing: 2) {
                Text("Generating")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary)
                Text(generatingSubline)
                    .font(.system(size: 11))
                    .foregroundStyle(IOSAppTheme.textSecondary)
            }

            Button {
                onCancel()
            } label: {
                Image(systemName: "stop.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textPrimary)
                    .frame(width: 44, height: 44)
                    .background {
                        Circle().fill(IOSAppTheme.glassSurfaceFillMuted.opacity(0.7))
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Stop generating")
            .accessibilityIdentifier("textInput_cancelButton")
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity)
        .frame(height: 56)
        .background {
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
        }
    }

    private var generatingSubline: String {
        switch mode {
        case .custom: return "Rendering audio…"
        case .design: return "Designing voice…"
        case .clone: return "Cloning voice…"
        }
    }
}

// MARK: - Generation state

enum IOSStudioGenState: Equatable {
    case idle
    case generating
    /// Live streaming preview is audible while generation is still in flight —
    /// the dock shows a player card (progressing waveform + play/pause + cancel)
    /// that seamlessly becomes the `.complete` card when generation finishes.
    case live(IOSStudioLivePreviewItem)
    case complete(IOSStudioInlinePlayerItem)

    /// Maps the two player-bearing states to the unified card's phase. `nil` for
    /// idle/generating. Used by the dock to render ONE `IOSStudioPlayerCard` for both
    /// `.live` and `.complete` (stable view identity ⇒ the transition morphs in place).
    var playerPhase: IOSStudioPlayerCard.Phase? {
        switch self {
        case .live(let item): return .live(item)
        case .complete(let item): return .complete(item)
        case .idle, .generating: return nil
        }
    }
}

/// Lightweight payload for the live-preview dock card (no audio URL — the final
/// file doesn't exist yet). Carries only what the live card chrome needs; the
/// shared `AudioPlayerViewModel` owns the actual streaming playback.
struct IOSStudioLivePreviewItem: Equatable {
    let voiceName: String
    let modeLabel: String
    let mode: GenerationMode
    let transcript: String
    /// Identical to the eventual `.complete` item's seed (prompt-derived) so the
    /// decorative waveform shape does not change across the live→final swap.
    let waveformSeed: Int
    /// Prompt-derived forecast of the final audio length (from `LivePreviewEstimate`),
    /// computed once at generation start. Drives the streaming waveform's buffer fill
    /// (`generated-so-far / estimate`) so the card looks full while audio is still arriving.
    let estimatedAudioDuration: TimeInterval
}

struct IOSStudioInlinePlayerItem: Equatable {
    let generationID: UUID
    let audioURL: URL
    let voiceName: String
    let modeLabel: String
    let mode: GenerationMode
    let transcript: String
    let waveformSeed: Int
    let autoplay: Bool
    /// True when the shared AudioPlayerViewModel already owns this generation's playback
    /// (live preview during generation → seamless hand-off). The inline card then mirrors/
    /// forwards that shared player instead of starting its own AVAudioPlayer (no double audio).
    var ownedBySharedPlayer: Bool = false

    static func == (lhs: IOSStudioInlinePlayerItem, rhs: IOSStudioInlinePlayerItem) -> Bool {
        lhs.audioURL == rhs.audioURL
    }

    var playerSheetItem: IOSPlayerSheetItem {
        IOSPlayerSheetItem(
            audioURL: audioURL,
            transcript: transcript,
            voiceName: voiceName,
            modeLabel: modeLabel,
            modeTint: IOSBrandTheme.modeColor(for: mode),
            subtitle: "Just now",
            avatarSeed: voiceName,
            avatarInitials: voiceName,
            waveformSeed: waveformSeed
        )
    }
}
