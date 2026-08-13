import AVFoundation
import SwiftUI
import Synchronization
import QwenVoiceCore

/// Full-screen Player sheet from design_references/Vocello iOS/player.jsx.
/// Renders a mode-tinted waveform + scrubber, a karaoke transcript that
/// follows playback under linear word-timing (per the approved plan), and
/// Share / Dismiss actions (a Save action appears only when the caller
/// supplies a distinct handler).
///
/// Self-contained: uses its own AVAudioPlayer so it doesn't compete with
/// the engine's live-preview state machine. Caller hands in an
/// `IOSPlayerSheetItem` and an optional save handler.
struct IOSPlayerSheet: View {
    let item: IOSPlayerSheetItem
    var onSave: (() -> Void)?
    var onDismiss: () -> Void

    @StateObject private var controller = IOSPlayerSheetController()
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion
    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    var body: some View {
        ZStack {
            playerSheetBackground

            VStack(spacing: 0) {
                grabber
                topBar

                VStack(spacing: 0) {
                    waveform
                        .padding(.top, 14)
                        .padding(.bottom, 18)

                    header
                        .padding(.bottom, 14)

                    transcript
                }
                .padding(.horizontal, 24)
                .frame(maxHeight: .infinity, alignment: .top)

                VStack(spacing: 0) {
                    scrubber
                        .padding(.bottom, 16)
                    controls
                }
                .padding(.horizontal, 24)
                .padding(.top, 12)
                .padding(.bottom, 16)
                .background {
                    LinearGradient(
                        colors: [
                            Color.clear,
                            sheetBaseColor.opacity(0.45),
                            sheetBaseColor.opacity(0.92),
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                }
            }
        }
        .preferredColorScheme(.dark)
        .task {
            await controller.load(item: item)
        }
        .onDisappear {
            controller.stop()
        }
    }

    private var sheetBaseColor: Color {
        Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255)
    }

    @ViewBuilder
    private var playerSheetBackground: some View {
        sheetBaseColor
            .ignoresSafeArea()

        if !reduceTransparency {
            GeometryReader { proxy in
                let radius = max(proxy.size.width * 0.80, proxy.size.height * 0.44)
                RadialGradient(
                    stops: [
                        .init(color: item.modeTint.opacity(0.38), location: 0),
                        .init(color: item.modeTint.opacity(0.16), location: 0.34),
                        .init(color: .clear, location: 0.65),
                    ],
                    center: UnitPoint(x: 0.5, y: 0),
                    startRadius: 0,
                    endRadius: radius
                )
                .scaleEffect(x: 1.55, y: 0.92, anchor: .top)
                .blendMode(.plusLighter)
                .opacity(0.70)
                .allowsHitTesting(false)
            }
            .ignoresSafeArea()
        }
    }

    // MARK: - Top bar

    private var grabber: some View {
        Capsule(style: .continuous)
            .fill(Color.white.opacity(0.20))
            .frame(width: 36, height: 5)
            .padding(.top, 6)
            .padding(.bottom, 6)
    }

    private var topBar: some View {
        HStack {
            Button {
                onDismiss()
            } label: {
                IOSPlayerIconButtonChrome(symbol: "chevron.down", size: 40, symbolSize: 18)
                    // 44 pt HIG hit target around the 40 pt visual (IUI-4 X8;
                    // the History row menu's established pattern).
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close")
            .accessibilityIdentifier("iosPlayer_close")

            Spacer()

            HStack(spacing: 8) {
                IOSModeDot(tint: item.modeTint)
                Text(playerEyebrowLabel.uppercased())
            }
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.88)
            .foregroundStyle(IOSAppTheme.textPrimary)

            Spacer()

            Color.clear
                .frame(width: 44, height: 44)
        }
        .padding(.horizontal, 16)
        .padding(.top, 0)
        .padding(.bottom, 4)
    }

    // MARK: - Header

    /// Centered voice name + "Just now · 0:06" timestamp.
    ///
    /// R3 G.6.1 (2026-05-21): rewritten to match
    /// `design_references/Vocello iOS/player.jsx` `.vc-player-sheet-meta`:
    /// no avatar, voice name as 22pt SF Pro Display semibold on top,
    /// "{timeLabel} · {duration}" in 13pt grey below. The previous
    /// left-aligned avatar+name HStack didn't read as the marquee the
    /// design wants.
    private var header: some View {
        VStack(spacing: 4) {
            Text(item.voiceName)
                .font(.system(size: 22, weight: .bold))
                .tracking(-0.44)
                .foregroundStyle(IOSAppTheme.textPrimary)
                .lineLimit(1)

            Text("\(item.subtitle ?? "Just now") · \(controller.formatted(time: controller.duration))")
                .font(.system(size: 13))
                .foregroundStyle(IOSAppTheme.textSecondary)
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity)
    }

    private var playerEyebrowLabel: String {
        switch item.modeLabel.lowercased() {
        case "custom": return "Custom Voice"
        case "design": return "Voice Design"
        case "clone": return "Voice Cloning"
        default: return item.modeLabel
        }
    }

    // MARK: - Waveform

    /// R3 G.6.2 (2026-05-21): 42 bars at 96pt height per
    /// `app.css .vc-big-wave { height: 96px }` + `player.jsx
    /// <BigWaveform bars={42} />`. Was 38 bars at 72pt — too small to
    /// read as the "art" of the player sheet.
    private var waveform: some View {
        IOSPlayerWaveformSection(
            clock: controller.clock,
            seed: item.waveformSeed,
            tint: item.modeTint,
            duration: controller.duration,
            // Honor Reduce Motion (CLAUDE.md): freeze the perpetual waveform when on.
            isAnimating: controller.isPlaying && !reduceMotion
        )
    }

    // MARK: - Scrubber

    /// R3 G.6.3 (2026-05-21): explicit scrubber track + progress fill +
    /// draggable thumb, matching `app.css` `.vc-player-scrub*`. The
    /// previous version showed only "0:00 / 0:00" labels and made
    /// scrubbing depend on dragging the waveform — undiscoverable.
    private var scrubber: some View {
        IOSPlayerScrubSection(
            clock: controller.clock,
            controller: controller,
            duration: controller.duration,
            tint: item.modeTint
        )
    }

    // MARK: - Transcript

    /// Centered karaoke transcript per
    /// `app.css .vc-player-sheet-transcript { text-align: center }`.
    /// Wrapping card removed so the transcript reads as flowing prose
    /// like the design — the player sheet itself is the surface.
    private var transcript: some View {
        IOSScrollView(bottomFadeHeight: 0) {
            Group {
                if reduceMotion {
                    // Static prose; no highlighting and no clock observation.
                    IOSPlayerKaraokeText(
                        spans: controller.spans,
                        highlight: nil,
                        tint: item.modeTint,
                        alignment: .center
                    )
                } else {
                    IOSPlayerKaraokeLive(
                        karaokeClock: controller.karaokeClock,
                        spans: controller.spans,
                        tint: item.modeTint,
                        alignment: .center
                    )
                }
            }
            .frame(maxWidth: .infinity)
            // VoiceOver: read the transcript as one prose element (the karaoke
            // spans are visual-only highlighting, not separate semantics).
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Transcript")
            .accessibilityValue(item.transcript)
            .accessibilityIdentifier("iosPlayer_transcript")
        }
        .frame(maxHeight: .infinity)
        .padding(.horizontal, 8)
        .padding(.bottom, 12)
    }

    // MARK: - Controls

    private var controls: some View {
        HStack(spacing: 16) {
            // Design pick D1: without a distinct save handler, "Save" and
            // "Download" were two labels for the identical share action. The
            // Save slot renders only when a caller provides a real handler
            // (none does today); a clear placeholder keeps the row balanced.
            if let onSave {
                playerSideButton(
                    title: "Save",
                    symbol: "bookmark",
                    action: onSave
                )
                .accessibilityIdentifier("iosPlayer_save")
            } else {
                // Hidden mirror of the trailing button: identical intrinsic
                // height, so the row cannot go height-flexible (a bare
                // Color.clear accepts any proposed height and would split
                // spare space away from the transcript).
                playerSideButton(
                    title: "Share",
                    symbol: "square.and.arrow.up",
                    action: {}
                )
                .hidden()
            }

            Button {
                guard controller.duration > 0 else { return }
                controller.togglePlayback()
            } label: {
                Image(systemName: controller.isPlaying ? "pause.fill" : "play.fill")
                    .accessibilityLabel(controller.isPlaying ? "Pause" : "Play")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(IOSAppTheme.accentForeground)
                    .frame(width: 72, height: 72)
                    .background {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [
                                        item.modeTint,
                                        item.modeTint.mix(with: .black, by: 0.20, in: .perceptual)
                                    ],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    }
                    .overlay {
                        Circle().stroke(Color.white.opacity(0.18), lineWidth: 0.5)
                    }
                    .shadow(color: item.modeTint.opacity(0.40), radius: 14, x: 0, y: 12)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosPlayer_playPause")
            .disabled(controller.duration <= 0)

            // D1: the action presents the system share sheet, so the label
            // says so ("Download" implied a direct file save). The stable
            // identifier keeps its historical name.
            playerSideButton(
                title: "Share",
                symbol: "square.and.arrow.up",
                action: { controller.shareCurrent() }
            )
            .accessibilityIdentifier("iosPlayer_download")
        }
        .padding(.horizontal, 4)
    }

    private func playerSideButton(
        title: String,
        symbol: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol)
                    .font(.system(size: 19, weight: .semibold))
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.22)
            }
            .foregroundStyle(IOSAppTheme.textSecondary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Player sheet item

struct IOSPlayerSheetItem: Equatable, Identifiable {
    let audioURL: URL
    let transcript: String
    let voiceName: String
    let modeLabel: String
    let modeTint: Color
    let subtitle: String?
    let avatarSeed: String
    let avatarInitials: String
    let waveformSeed: Int

    var id: URL { audioURL }

    static func == (lhs: IOSPlayerSheetItem, rhs: IOSPlayerSheetItem) -> Bool {
        lhs.audioURL == rhs.audioURL && lhs.transcript == rhs.transcript
    }

    /// Helper: build a player-sheet item from a History `Generation` row.
    /// The sheet can still present transcript metadata if an older history
    /// row points at audio that has since disappeared from disk.
    static func from(history: Generation) -> IOSPlayerSheetItem {
        let modeTint: Color
        let modeLabel: String
        switch history.mode.lowercased() {
        case "custom":
            modeTint = IOSBrandTheme.custom
            modeLabel = "Custom"
        case "design":
            modeTint = IOSBrandTheme.design
            modeLabel = "Design"
        case "clone":
            modeTint = IOSBrandTheme.clone
            modeLabel = "Clone"
        default:
            modeTint = IOSBrandTheme.library
            modeLabel = history.mode.capitalized
        }
        let voiceName = history.voice ?? "Voice"
        return IOSPlayerSheetItem(
            audioURL: URL(fileURLWithPath: history.audioPath),
            transcript: history.text,
            voiceName: voiceName,
            modeLabel: modeLabel,
            modeTint: modeTint,
            subtitle: history.formattedDate,
            avatarSeed: voiceName,
            avatarInitials: voiceName,
            waveformSeed: history.id.map { Int(truncatingIfNeeded: $0) } ?? IOSStableVisualHash.int(history.audioPath)
        )
    }

    /// Helper: build a player-sheet item from a saved cloned voice.
    /// Returns `nil` when the prepared WAV is missing on disk.
    static func from(savedVoice voice: Voice) -> IOSPlayerSheetItem? {
        guard FileManager.default.fileExists(atPath: voice.wavPath) else {
            return nil
        }
        let transcript = (try? voice.loadTranscript()) ?? "Hi, I'm \(voice.name). Cloned reference."
        return IOSPlayerSheetItem(
            audioURL: URL(fileURLWithPath: voice.wavPath),
            transcript: transcript,
            voiceName: voice.name,
            modeLabel: "Clone",
            modeTint: IOSBrandTheme.clone,
            subtitle: "Saved voice",
            avatarSeed: voice.id,
            avatarInitials: voice.name,
            waveformSeed: IOSStableVisualHash.int(voice.wavPath)
        )
    }

    /// Helper: build a player-sheet item from a bundled built-in preview
    /// WAV. Missing preview assets intentionally produce no chrome.
    static func fromBuiltInPreview(speaker: SpeakerDescriptor) -> IOSPlayerSheetItem? {
        guard let audioURL = Bundle.main.url(
            forResource: speaker.id,
            withExtension: "wav",
            subdirectory: "voice-previews"
        ) ?? Bundle.main.url(
            forResource: speaker.id,
            withExtension: "wav"
        ) else {
            return nil
        }

        let descriptor = speaker.shortDescription
            ?? speaker.nativeLanguage
            ?? speaker.group.capitalized
        return IOSPlayerSheetItem(
            audioURL: audioURL,
            transcript: "Hi, I'm \(speaker.displayName). \(descriptor).",
            voiceName: speaker.displayName,
            modeLabel: "Custom",
            modeTint: IOSBrandTheme.custom,
            subtitle: "Voice preview",
            avatarSeed: speaker.id,
            avatarInitials: speaker.displayName,
            waveformSeed: IOSStableVisualHash.int(speaker.id)
        )
    }
}

// MARK: - Environment plumbing

/// Environment closure for requesting the global Player sheet presentation.
/// QVoiceiOSRootView injects a closure that sets its `playerSheetItem` state;
/// any descendant view (History rows, Studio inline player) reads it via
/// `@Environment(\.presentIOSPlayerSheet)` and calls it with an item.
struct IOSPlayerSheetPresenterKey: EnvironmentKey {
    static let defaultValue: @MainActor (IOSPlayerSheetItem) -> Void = { _ in }
}

extension EnvironmentValues {
    var presentIOSPlayerSheet: @MainActor (IOSPlayerSheetItem) -> Void {
        get { self[IOSPlayerSheetPresenterKey.self] }
        set { self[IOSPlayerSheetPresenterKey.self] = newValue }
    }
}

// MARK: - Karaoke renderer

/// Index-driven karaoke renderer (IUI-5 P3). The transcript's
/// `AttributedString` is a function of the *highlight state* (active word +
/// played prefix), which changes at word-boundary rate (~2–4 Hz) — never of
/// the raw playback time, which changes per display-link tick. `highlight`
/// is nil for the static Reduce Motion presentation.
struct IOSPlayerKaraokeText: View {
    let spans: [IOSWordSpan]
    let highlight: IOSKaraokeHighlight?
    let tint: Color
    var alignment: TextAlignment = .leading

    var body: some View {
        Text(attributedTranscript)
            .font(.system(size: 17, weight: .medium))
            .tracking(-0.085)
            .lineSpacing(5)
            .multilineTextAlignment(alignment)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var attributedTranscript: AttributedString {
        var attributed = AttributedString()
        for (i, span) in spans.enumerated() {
            var run = AttributedString(span.text)
            if span.isWhitespace {
                run.foregroundColor = IOSAppTheme.textPrimary
            } else if let highlight {
                if i == highlight.activeIndex {
                    run.foregroundColor = tint
                    run.font = .system(size: 17, weight: .semibold)
                } else if i < highlight.playedCount {
                    run.foregroundColor = IOSAppTheme.textPrimary
                } else {
                    run.foregroundColor = IOSAppTheme.textTertiary
                }
            } else {
                run.foregroundColor = IOSAppTheme.textPrimary
            }
            attributed.append(run)
        }
        return attributed
    }
}

/// Observes the boundary-rate karaoke clock so only this leaf re-renders as
/// the highlight advances; the sheet body and scroll container stay still.
private struct IOSPlayerKaraokeLive: View {
    @ObservedObject var karaokeClock: IOSPlayerKaraokeClock
    let spans: [IOSWordSpan]
    let tint: Color
    var alignment: TextAlignment = .leading

    var body: some View {
        IOSPlayerKaraokeText(
            spans: spans,
            highlight: karaokeClock.highlight,
            tint: tint,
            alignment: alignment
        )
    }
}

// MARK: - Per-tick leaf sections (IUI-5 P3)

/// The waveform fill is the one upper-region element that moves every frame;
/// it observes the playback clock directly so ticks stop invalidating the
/// whole sheet body.
private struct IOSPlayerWaveformSection: View {
    @ObservedObject var clock: IOSPlayerPlaybackClock
    let seed: Int
    let tint: Color
    let duration: TimeInterval
    let isAnimating: Bool

    var body: some View {
        IOSWaveformBars(
            seed: seed,
            barCount: 42,
            tint: tint,
            progress: duration > 0 ? min(1, max(0, clock.currentTime / duration)) : 0,
            isAnimating: isAnimating,
            unplayedColor: Color.white.opacity(0.14),
            style: .big
        )
        .frame(height: 96)
    }
}

/// Scrub track + thumb + time labels: the other per-frame region. Holds the
/// controller as a plain (non-observing) reference for actions; duration
/// arrives as a value from the observing parent.
private struct IOSPlayerScrubSection: View {
    @ObservedObject var clock: IOSPlayerPlaybackClock
    let controller: IOSPlayerSheetController
    let duration: TimeInterval
    let tint: Color

    private var progress: Double {
        guard duration > 0 else { return 0 }
        return min(1.0, max(0.0, clock.currentTime / duration))
    }

    var body: some View {
        VStack(spacing: 8) {
            GeometryReader { geo in
                let width = geo.size.width
                let thumbX = max(0, min(width, width * CGFloat(progress)))

                ZStack(alignment: .leading) {
                    // Track
                    Capsule(style: .continuous)
                        .fill(Color.white.opacity(0.10))
                        .frame(height: 4)

                    // Fill
                    Capsule(style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    tint.mix(with: .black, by: 0.20, in: .perceptual),
                                    tint,
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: thumbX, height: 4)

                    // Thumb
                    Circle()
                        .fill(Color.white)
                        .frame(width: 16, height: 16)
                        .overlay {
                            Circle().stroke(tint, lineWidth: 2)
                        }
                        .shadow(color: .black.opacity(0.25), radius: 3, x: 0, y: 2)
                        .offset(x: thumbX - 8)
                }
                .frame(height: 24)
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            let ratio = max(0, min(1, value.location.x / width))
                            controller.scrub(to: ratio)
                        }
                )
                // VoiceOver: a draggable thumb is unreachable; expose it as an
                // adjustable element so swipe-up/down scrubs in 5% steps.
                .accessibilityElement()
                .accessibilityLabel("Playback position")
                .accessibilityValue(controller.formatted(time: clock.currentTime))
                .accessibilityIdentifier("iosPlayer_scrubber")
                .accessibilityAdjustableAction { direction in
                    let step = 0.05
                    switch direction {
                    case .increment: controller.scrub(to: min(1, progress + step))
                    case .decrement: controller.scrub(to: max(0, progress - step))
                    @unknown default: break
                    }
                }
            }
            .frame(height: 24)

            HStack {
                Text(controller.formatted(time: clock.currentTime))
                Spacer()
                Text(controller.formatted(time: duration))
            }
            .font(.system(.caption, design: .monospaced).monospacedDigit())
            .fontWeight(.medium)
            .foregroundStyle(IOSAppTheme.textSecondary)
        }
    }
}

// MARK: - Off-MainActor audio loading (IUI-4 P1)

/// Serializes AVAudioSession activate/deactivate. Ordering alone is not
/// enough — a deactivation can be *enqueued* after a newer presentation's
/// activation (a dismissed-mid-load sheet releases its session only when the
/// stale decode result arrives) — so every activation takes a fresh epoch and
/// a deactivation executes only while its own activation is still the newest.
/// Both interleavings matter: dismiss-before-activation must still release
/// the orphaned session, and dismiss-then-reopen must never silence the new
/// sheet's session (adversarial review of this change, 2026-08-12).
private let iosPlayerAudioSessionQueue = DispatchQueue(
    label: "com.qwenvoice.player-audio-session", qos: .userInitiated)
private let iosPlayerSessionEpoch = Mutex(0)

/// The off-MainActor product of a load. Not Sendable (AVAudioPlayer); crosses
/// back to the MainActor as a `sending` disconnected value.
private struct IOSPlayerLoadedAudio {
    let player: AVAudioPlayer
    let spans: [IOSWordSpan]
    let sessionEpoch: Int
}

/// Session activation is a blocking IPC to mediaserverd (tens to hundreds of
/// ms) and `AVAudioPlayer(contentsOf:)` reads + decodes the file — neither
/// may run inside the sheet's presentation transaction (the metronomic
/// 178 ms present stall the IUI-2 baseline measured).
@concurrent
private func iosPlayerLoadAudio(
    url: URL, transcript: String
) async throws -> sending IOSPlayerLoadedAudio {
    let epoch = try iosPlayerAudioSessionQueue.sync {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default, options: [])
        try session.setActive(true, options: [])
        return iosPlayerSessionEpoch.withLock { epoch in
            epoch += 1
            return epoch
        }
    }
    do {
        let player = try AVAudioPlayer(contentsOf: url)
        player.prepareToPlay()
        let spans = IOSWordTimingPlanner.plan(
            transcript: transcript,
            audioDuration: player.duration
        )
        return IOSPlayerLoadedAudio(player: player, spans: spans, sessionEpoch: epoch)
    } catch {
        // Activation succeeded but the decode failed: release the session
        // unless someone newer has already claimed it.
        iosPlayerDeactivateSession(ifCurrentEpoch: epoch)
        throw error
    }
}

private func iosPlayerDeactivateSession(ifCurrentEpoch epoch: Int?) {
    guard let epoch else { return }
    iosPlayerAudioSessionQueue.async {
        guard iosPlayerSessionEpoch.withLock({ $0 }) == epoch else { return }
        try? AVAudioSession.sharedInstance().setActive(
            false, options: .notifyOthersOnDeactivation)
    }
}

// MARK: - Controller

/// Per-tick playback time, isolated from the sheet-level controller (IUI-5
/// P3): only the leaf views that genuinely move every frame (waveform fill,
/// scrub thumb, elapsed label) observe this clock, so the 20–60 Hz display
/// link no longer invalidates the whole sheet body per tick.
@MainActor
final class IOSPlayerPlaybackClock: ObservableObject {
    @Published fileprivate(set) var currentTime: TimeInterval = 0
}

/// Karaoke highlight state: the active word plus the played prefix (span end
/// times are non-decreasing — `IOSWordTimingPlanner` distributes linearly and
/// whitespace inherits the previous word's end — so the played set is always
/// a prefix).
struct IOSKaraokeHighlight: Equatable {
    var activeIndex: Int?
    var playedCount: Int
}

/// Publishes only when the visible highlighting changes (word boundaries,
/// ~2–4 Hz), so the transcript rebuilds at the rate its output changes
/// rather than per display-link tick.
@MainActor
final class IOSPlayerKaraokeClock: ObservableObject {
    @Published fileprivate(set) var highlight = IOSKaraokeHighlight(activeIndex: nil, playedCount: 0)

    fileprivate func update(spans: [IOSWordSpan], time: TimeInterval) {
        let active = IOSWordTimingPlanner.activeIndex(in: spans, at: time)
        var played = 0
        for span in spans {
            guard span.end <= time else { break }
            played += 1
        }
        let next = IOSKaraokeHighlight(activeIndex: active, playedCount: played)
        if next != highlight {
            highlight = next
        }
    }
}

@MainActor
final class IOSPlayerSheetController: NSObject, ObservableObject {
    @Published private(set) var isPlaying: Bool = false
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var spans: [IOSWordSpan] = [] {
        didSet { karaokeClock.update(spans: spans, time: currentTime) }
    }

    /// Deliberately NOT `@Published` (IUI-5 P3): per-tick publication through
    /// this sheet-level object was the whole-body invalidation the baseline
    /// measured at 106.5 ms/s during scrub. Per-frame consumers observe
    /// `clock`; boundary-rate consumers observe `karaokeClock`.
    private(set) var currentTime: TimeInterval = 0 {
        didSet {
            clock.currentTime = currentTime
            karaokeClock.update(spans: spans, time: currentTime)
        }
    }

    let clock = IOSPlayerPlaybackClock()
    let karaokeClock = IOSPlayerKaraokeClock()

    private var player: AVAudioPlayer?
    private var displayLink: CADisplayLink?
    private var loadedItem: IOSPlayerSheetItem?
    private var loadGeneration = 0
    private var sessionEpoch: Int?

    var progress: Double {
        guard duration > 0 else { return 0 }
        return min(1.0, max(0.0, currentTime / duration))
    }

    func load(item: IOSPlayerSheetItem) async {
        guard loadedItem != item else {
            // Re-presented for the same item — autoplay from current state.
            play()
            return
        }
        loadGeneration += 1
        let generation = loadGeneration
        // The heavy half runs off the MainActor: session activation is a
        // blocking IPC to mediaserverd (tens to hundreds of ms) and
        // AVAudioPlayer(contentsOf:) reads + decodes the file. Keeping both
        // out of the presentation transaction is the IUI-4 P1 fix for the
        // metronomic 178 ms sheet-present stall the baseline measured.
        let audioURL = item.audioURL
        let transcript = item.transcript
        do {
            let loaded = try await iosPlayerLoadAudio(url: audioURL, transcript: transcript)
            guard generation == loadGeneration else {
                // Dismissed (or superseded) while loading: never adopt the
                // stale player, and release the session it activated — unless
                // a newer presentation has already re-activated it.
                iosPlayerDeactivateSession(ifCurrentEpoch: loaded.sessionEpoch)
                return
            }
            loadedItem = item
            sessionEpoch = loaded.sessionEpoch
            loaded.player.delegate = self
            self.player = loaded.player
            self.duration = loaded.player.duration
            self.currentTime = 0
            self.spans = loaded.spans
            play()
        } catch {
            guard generation == loadGeneration else { return }
            loadedItem = item
            self.player = nil
            self.duration = 0
            self.spans = IOSWordTimingPlanner.plan(transcript: transcript, audioDuration: 0)
        }
    }


    func play() {
        guard let player else { return }
        player.play()
        isPlaying = true
        startDisplayLink()
        IOSHaptics.selection()
    }

    func pause() {
        player?.pause()
        isPlaying = false
        stopDisplayLink()
        // Design pick D6: play and pause are the same class of transport action;
        // the haptic fires on both (it previously marked only play/autoplay).
        IOSHaptics.selection()
    }

    func togglePlayback() {
        if isPlaying { pause() } else { play() }
    }

    func stop() {
        loadGeneration += 1
        player?.stop()
        isPlaying = false
        stopDisplayLink()
        // Deactivation blocks like activation does; run it off the dismiss
        // transaction. Epoch-guarded: releases only the activation this
        // controller adopted (nil while a load is still in flight — the
        // stale-load guard releases that one with its own epoch).
        iosPlayerDeactivateSession(ifCurrentEpoch: sessionEpoch)
        sessionEpoch = nil
    }

    func skip(by seconds: TimeInterval) {
        guard let player else { return }
        let target = max(0, min(duration, player.currentTime + seconds))
        player.currentTime = target
        currentTime = target
    }

    func scrub(to fraction: Double) {
        guard let player else { return }
        let target = duration * max(0, min(1, fraction))
        player.currentTime = target
        currentTime = target
    }

    func shareCurrent() {
        guard let url = loadedItem?.audioURL else { return }
        let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.keyWindow }
            .first?
            .rootViewController?
            .present(activity, animated: true)
    }

    func formatted(time: TimeInterval) -> String {
        guard time.isFinite else { return "0:00" }
        let total = max(0, Int(time.rounded()))
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }

    private func startDisplayLink() {
        stopDisplayLink()
        let link = CADisplayLink(target: self, selector: #selector(tick(_:)))
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 20, maximum: 60, preferred: 30)
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    private func stopDisplayLink() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func tick(_ link: CADisplayLink) {
        guard let player else { return }
        currentTime = player.currentTime
        if !player.isPlaying && isPlaying {
            isPlaying = false
            stopDisplayLink()
        }
    }
}

extension IOSPlayerSheetController: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.isPlaying = false
            self.stopDisplayLink()
            self.currentTime = self.duration
        }
    }
}
