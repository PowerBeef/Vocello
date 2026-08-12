import AVFoundation
import SwiftUI
import Synchronization
import QwenVoiceCore

/// Full-screen Player sheet from design_references/Vocello iOS/player.jsx.
/// Renders a mode-tinted waveform + scrubber, a karaoke transcript that
/// follows playback under linear word-timing (per the approved plan), and
/// Save / Download / Dismiss actions.
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
        IOSWaveformBars(
            seed: item.waveformSeed,
            barCount: 42,
            tint: item.modeTint,
            progress: controller.progress,
            // Honor Reduce Motion (CLAUDE.md): freeze the perpetual waveform when on.
            isAnimating: controller.isPlaying && !reduceMotion,
            unplayedColor: Color.white.opacity(0.14),
            style: .big
        )
        .frame(height: 96)
    }

    // MARK: - Scrubber

    /// R3 G.6.3 (2026-05-21): explicit scrubber track + progress fill +
    /// draggable thumb, matching `app.css` `.vc-player-scrub*`. The
    /// previous version showed only "0:00 / 0:00" labels and made
    /// scrubbing depend on dragging the waveform — undiscoverable.
    private var scrubber: some View {
        VStack(spacing: 8) {
            GeometryReader { geo in
                let width = geo.size.width
                let progress = CGFloat(controller.progress)
                let thumbX = max(0, min(width, width * progress))

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
                                    item.modeTint.mix(with: .black, by: 0.20, in: .perceptual),
                                    item.modeTint,
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
                            Circle().stroke(item.modeTint, lineWidth: 2)
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
                .accessibilityValue(controller.formatted(time: controller.currentTime))
                .accessibilityIdentifier("iosPlayer_scrubber")
                .accessibilityAdjustableAction { direction in
                    let step = 0.05
                    switch direction {
                    case .increment: controller.scrub(to: min(1, controller.progress + step))
                    case .decrement: controller.scrub(to: max(0, controller.progress - step))
                    @unknown default: break
                    }
                }
            }
            .frame(height: 24)

            HStack {
                Text(controller.formatted(time: controller.currentTime))
                Spacer()
                Text(controller.formatted(time: controller.duration))
            }
            .font(.system(.caption, design: .monospaced).monospacedDigit())
            .fontWeight(.medium)
            .foregroundStyle(IOSAppTheme.textSecondary)
        }
    }

    // MARK: - Transcript

    /// Centered karaoke transcript per
    /// `app.css .vc-player-sheet-transcript { text-align: center }`.
    /// Wrapping card removed so the transcript reads as flowing prose
    /// like the design — the player sheet itself is the surface.
    private var transcript: some View {
        IOSScrollView(bottomFadeHeight: 0) {
            IOSPlayerKaraokeText(
                spans: controller.spans,
                currentTime: controller.currentTime,
                tint: item.modeTint,
                isPlaying: controller.isPlaying,
                reduceMotion: reduceMotion,
                alignment: .center
            )
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
            playerSideButton(
                title: "Save",
                symbol: "bookmark",
                action: {
                    if let onSave {
                        onSave()
                    } else {
                        controller.shareCurrent()
                    }
                }
            )
            .accessibilityIdentifier("iosPlayer_save")

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

            playerSideButton(
                title: "Download",
                symbol: "arrow.down.to.line",
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

struct IOSPlayerKaraokeText: View {
    let spans: [IOSWordSpan]
    let currentTime: TimeInterval
    let tint: Color
    let isPlaying: Bool
    let reduceMotion: Bool
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
        let activeIndex = reduceMotion ? nil : IOSWordTimingPlanner.activeIndex(in: spans, at: currentTime)
        for (i, span) in spans.enumerated() {
            var run = AttributedString(span.text)
            if span.isWhitespace {
                run.foregroundColor = IOSAppTheme.textPrimary
            } else if reduceMotion {
                run.foregroundColor = IOSAppTheme.textPrimary
            } else if i == activeIndex {
                run.foregroundColor = tint
                run.font = .system(size: 17, weight: .semibold)
            } else if span.end <= currentTime {
                run.foregroundColor = IOSAppTheme.textPrimary
            } else {
                run.foregroundColor = IOSAppTheme.textTertiary
            }
            attributed.append(run)
        }
        return attributed
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

@MainActor
final class IOSPlayerSheetController: NSObject, ObservableObject {
    @Published private(set) var isPlaying: Bool = false
    @Published private(set) var currentTime: TimeInterval = 0
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var spans: [IOSWordSpan] = []

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
