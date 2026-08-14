import AVFoundation
import Observation
import SwiftUI

/// Studio dock hero player — a SINGLE card that serves both the **live streaming
/// preview** (during generation) and the **completed take** (after), so the
/// `.live → .complete` dock transition is an in-place morph (one view identity, one
/// `IOSInlinePlaybackController`) rather than a swap of two separate views.
///
/// Per design_references/Vocello iOS/studio.jsx (InlinePlayer): a waveform progress
/// bar across the top, then a row with a mode-tinted Play/Pause button, voice meta,
/// and phase-specific trailing controls (Cancel while streaming; Save / Download /
/// Dismiss when complete). The same controller mirrors the shared `AudioPlayerViewModel`
/// throughout, so playback position + waveform continue smoothly across the morph.
struct IOSStudioPlayerCard: View {
    enum Phase {
        case live(IOSStudioLivePreviewItem)
        case complete(IOSStudioInlinePlayerItem)

        var isLive: Bool { if case .live = self { return true } else { return false } }
        var waveformSeed: Int {
            switch self {
            case .live(let i): return i.waveformSeed
            case .complete(let i): return i.waveformSeed
            }
        }
        var voiceName: String {
            switch self {
            case .live(let i): return i.voiceName
            case .complete(let i): return i.voiceName
            }
        }
        var modeLabel: String {
            switch self {
            case .live(let i): return i.modeLabel
            case .complete(let i): return i.modeLabel
            }
        }
        var liveEstimate: TimeInterval? {
            if case .live(let i) = self { return i.estimatedAudioDuration } else { return nil }
        }
        var accessibilityIdentifier: String {
            switch self {
            case .live:
                return "studio_livePreview_card"
            case .complete(let item):
                return "studio_inlinePlayer_generation_\(item.generationID.uuidString.lowercased())"
            }
        }
        /// Stable task key: stays `"live"` while streaming, flips to the final path on
        /// completion so the controller re-adopts by URL.
        var taskKey: String {
            switch self {
            case .live: return "live"
            case .complete(let i): return "complete:\(i.audioURL.path)"
            }
        }
    }

    let phase: Phase
    let tint: Color
    var onSave: (() -> Void)?
    var onDismiss: () -> Void
    var onCancel: () -> Void
    var onExpand: (() -> Void)?
    /// When provided (Voice Design), the completed card shows a "Save as voice" button.
    var onSaveAsVoice: (() -> Void)?

    /// Identity for the activation task: phase drives adoption, and the
    /// tab-active flag makes leaving/returning to the tab re-run it (the
    /// stable-identity tab container no longer remounts this card per visit).
    private struct CardActivation: Equatable {
        var phaseKey: String
        var isTabActive: Bool
    }

    @Environment(\.iosTabIsActive) private var isTabActive
    @State private var controller = IOSInlinePlaybackController()
    @State private var pulse = false
    @State private var showDismissConfirm = false
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    private let referenceHeight: CGFloat = 127
    private let saveAsVoiceRowHeight: CGFloat = 52

    /// Show "Save as voice" only on a COMPLETED card when the host provides the action (Voice
    /// Design). The live preview keeps the base height so the live→complete morph stays smooth.
    private var showsSaveAsVoice: Bool {
        if case .complete = phase, onSaveAsVoice != nil { return true }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Per-tick currentTime/progress/buffer math lives in this child only, so the
            // parent body (chrome + shadow) doesn't re-render on every display-link tick.
            InlineWaveformProgressRow(
                controller: controller,
                waveformSeed: phase.waveformSeed,
                tint: tint,
                scrubEnabled: !phase.isLive,
                liveEstimate: phase.liveEstimate,
                onExpand: phase.isLive ? nil : onExpand
            )
            controlsRow

            if showsSaveAsVoice {
                saveAsVoiceButton
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 16)
        .frame(maxWidth: .infinity)
        .frame(height: referenceHeight + (showsSaveAsVoice ? saveAsVoiceRowHeight : 0))
        .background {
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.85))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
        }
        // Softer shadow per the design notes: dropped from `0 12 32 / 0.45`
        // to `0 2 10 / 0.22` so the player floats lightly above the canvas.
        .shadow(color: Color.black.opacity(0.22), radius: 5, x: 0, y: 2)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(phase.accessibilityIdentifier)
        .transition(cardTransition)
        // Tab-scoped activation (IUI-5 P4 follow-up): the stable-identity tab
        // container keeps a visited Studio mounted, so tab switches no longer
        // fire `.onDisappear`. Folding the tab-active flag into the task
        // identity restores the old contract exactly: leaving the tab stops
        // this card the way teardown did (own player halted; shared-player
        // mirroring stops without touching the shared player), a phase flip
        // while hidden must NOT adopt or start the display link, and returning
        // re-adopts the current phase the way a remount did.
        .task(id: CardActivation(phaseKey: phase.taskKey, isTabActive: isTabActive)) {
            if isTabActive {
                await activateController()
            } else {
                controller.stop()
            }
        }
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { pulse = true }
        }
        // The repeat-forever pulse would keep animating the hidden subtree;
        // pause it off-tab and restart on return.
        .onChange(of: isTabActive) { _, active in
            if active {
                guard !reduceMotion else { return }
                withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { pulse = true }
            } else {
                var transaction = Transaction()
                transaction.disablesAnimations = true
                withTransaction(transaction) { pulse = false }
            }
        }
        .onDisappear { controller.stop() }
        .confirmationDialog(
            "Dismiss this clip?",
            isPresented: $showDismissConfirm,
            titleVisibility: .visible
        ) {
            Button("Dismiss", role: .destructive) {
                // The take is already saved in History, so this only clears it from Studio.
                // Stop the shared player too, so dismissing doesn't leave audio playing with
                // no visible card.
                audioPlayer.dismiss()
                onDismiss()
            }
            .accessibilityIdentifier("studio_inlinePlayer_dismissConfirm")
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your generation is saved in History — you can replay it anytime.")
        }
    }

    /// Activate the shared-player adoption for the current phase on the SAME controller.
    /// Live → mirror the streaming preview; complete → re-adopt by URL (the shared player's
    /// `currentFilePath` already equals the final URL by the time `.complete` is set, so this
    /// is a seamless hand-off with no position reset).
    private func activateController() async {
        switch phase {
        case .live:
            controller.adoptLive(sharedPlayer: audioPlayer)
        case .complete(let item):
            if item.ownedBySharedPlayer {
                controller.adopt(sharedPlayer: audioPlayer, url: item.audioURL)
            } else {
                await controller.load(url: item.audioURL, autoplay: item.autoplay)
            }
        }
    }

    private var cardTransition: AnyTransition {
        reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity)
    }

    // MARK: - Controls row

    private var controlsRow: some View {
        HStack(spacing: 8) {
            playPauseButton

            VStack(alignment: .leading, spacing: 1) {
                Text(phase.voiceName)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .lineLimit(1)
                statusLine
            }
            .padding(.leading, 4)

            Spacer(minLength: 0)

            trailingControls
        }
        // Card stays put; only the status line + trailing cluster cross-fade between phases.
        .iosAppAnimation(Theme.Motion.stateChange, value: phase.isLive)
    }

    /// Full-width "Save as voice" CTA on a completed Design card — enrolls the generated clip as a
    /// reusable voice (usable in Voice Cloning). Tinted with the card's mode color.
    private var saveAsVoiceButton: some View {
        Button {
            IOSHaptics.selection()
            onSaveAsVoice?()
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "waveform.badge.plus")
                    .font(.system(size: 14, weight: .semibold))
                Text("Save as voice")
                    .font(.subheadline.weight(.semibold))
            }
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity)
            .frame(height: 40)
            .background { Capsule(style: .continuous).fill(tint.opacity(0.16)) }
            .overlay { Capsule(style: .continuous).stroke(tint.opacity(0.32), lineWidth: 0.75) }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("studio_inlinePlayer_saveAsVoice")
    }

    private var playPauseButton: some View {
        Button {
            controller.togglePlayback()
            IOSHaptics.selection()
        } label: {
            Image(systemName: controller.isPlaying ? "pause.fill" : "play.fill")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Theme.Text.onAccent)
                .frame(width: 48, height: 48)
                .background {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [
                                    tint,
                                    tint.mix(with: .black, by: 0.20, in: .perceptual),
                                ],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }
                .overlay {
                    Circle().stroke(Color.white.opacity(0.18), lineWidth: 0.5)
                }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(controller.isPlaying ? "Pause" : "Play")
        .accessibilityIdentifier(phase.isLive ? "studio_livePreview_playPause" : "studio_inlinePlayer_playPause")
    }

    @ViewBuilder
    private var statusLine: some View {
        if phase.isLive {
            HStack(spacing: 5) {
                Circle()
                    .fill(tint)
                    .frame(width: 6, height: 6)
                    .opacity(reduceMotion ? 1.0 : (pulse ? 1.0 : 0.3))
                Text("Streaming preview")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.Text.secondary)
                    .lineLimit(1)
            }
            .transition(.opacity)
        } else {
            Text("Just now · \(phase.modeLabel)")
                .font(.system(size: 11))
                .foregroundStyle(Theme.Text.secondary)
                .lineLimit(1)
                .transition(.opacity)
        }
    }

    @ViewBuilder
    private var trailingControls: some View {
        if phase.isLive {
            Button(action: onCancel) {
                Image(systemName: "stop.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background { Circle().fill(Theme.Surface.glassSurfaceMuted.opacity(0.7)) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Cancel generation")
            .accessibilityIdentifier("studio_livePreview_cancel")
            .transition(.opacity)
        } else {
            HStack(spacing: 8) {
                iconButton(
                    symbol: "bookmark",
                    label: "Save",
                    accessibilityIdentifier: "studio_inlinePlayer_save"
                ) {
                    if let onSave { onSave() } else { shareWAV() }
                }
                iconButton(
                    symbol: "arrow.down.to.line",
                    label: "Download",
                    accessibilityIdentifier: "studio_inlinePlayer_download"
                ) { shareWAV() }
                iconButton(
                    symbol: "xmark",
                    label: "Dismiss",
                    accessibilityIdentifier: "studio_inlinePlayer_dismiss"
                ) { showDismissConfirm = true }
            }
            .transition(.opacity)
        }
    }

    private func iconButton(
        symbol: String,
        label: String,
        accessibilityIdentifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            IOSPlayerIconButtonChrome(symbol: symbol, size: 40, symbolSize: 18)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(accessibilityIdentifier)
    }

    private func shareWAV() {
        guard case .complete(let item) = phase else { return }
        let activity = UIActivityViewController(activityItems: [item.audioURL], applicationActivities: nil)
        UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.keyWindow }
            .first?
            .rootViewController?
            .present(activity, animated: true)
    }
}

// MARK: - Waveform progress row

/// The per-tick-varying slice of the inline player, isolated into its own view so the
/// parent card's chrome (background/stroke/shadow) doesn't re-render on every display-link
/// tick. Reads `controller.currentTime`/`progress`/`duration` (tracked via @Observable);
/// the parent reads only `isPlaying`.
struct InlineWaveformProgressRow: View {
    let controller: IOSInlinePlaybackController
    let waveformSeed: Int
    let tint: Color
    /// Scrubbing is disabled during a live preview (seek is a no-op until the final
    /// file exists) — the waveform is a pure progress indicator then.
    var scrubEnabled: Bool = true
    /// When set, the row renders in **streaming-preview mode**: the waveform shows a
    /// generated-so-far buffer fill (`duration / estimate`) with the playhead inside it
    /// and an animated not-yet-generated tail, and the right label shows `~estimate`.
    /// `nil` (default) is the normal completed player (playback progress + final duration).
    /// All per-tick state (`currentTime`/`duration`) is read here so the parent card's
    /// chrome doesn't re-render on every display-link tick.
    var liveEstimate: TimeInterval? = nil
    var onExpand: (() -> Void)?

    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    // Monotonic-handoff guard: the live playhead is `currentTime / estimate`; the completed playhead is
    // `currentTime / actualDuration`. When the real duration is slightly longer than the estimate, the
    // fraction drops a frame at the morph → the bar twitches backward. We hold the bar at its last live
    // position until real playback catches up, then release (so scrubbing still works).
    @State private var lastStreamingFraction: Double = 0
    @State private var holdFloor: Double = 0

    private var isStreaming: Bool { liveEstimate != nil }

    /// Estimate floored by what's actually been generated so the buffer fill can't overflow
    /// even when the forecast undershoots.
    private var resolvedEstimate: TimeInterval {
        max(liveEstimate ?? 0, controller.duration, 0.8)
    }

    private var bufferedFraction: Double {
        guard isStreaming, resolvedEstimate > 0 else { return controller.progress }
        return min(1, controller.duration / resolvedEstimate)
    }

    private var playheadFraction: Double {
        guard isStreaming, resolvedEstimate > 0 else { return controller.progress }
        return min(bufferedFraction, controller.currentTime / resolvedEstimate)
    }

    /// Playhead actually drawn: clamped to the last live position across the live→complete morph so the
    /// denominator change (estimate → actual duration) can't step the bar backward. `holdFloor == 0`
    /// (the normal case + after catch-up/scrub) passes `playheadFraction` straight through.
    private var displayedPlayhead: Double {
        guard !isStreaming, holdFloor > 0 else { return playheadFraction }
        return max(playheadFraction, holdFloor)
    }

    var body: some View {
        HStack(spacing: 12) {
            Text(controller.formatted(time: controller.currentTime))
                .font(.system(size: 13, weight: .semibold).monospacedDigit())
                .foregroundStyle(Theme.Text.secondary)
                .frame(width: 36, alignment: .leading)

            GeometryReader { proxy in
                IOSWaveformBars(
                    seed: waveformSeed,
                    barCount: 38,
                    tint: tint,
                    progress: displayedPlayhead,
                    isAnimating: isStreaming && !reduceMotion,
                    unplayedColor: Color.white.opacity(0.18),
                    style: .player,
                    bufferedProgress: isStreaming ? bufferedFraction : nil
                )
                .contentShape(Rectangle())
                .gesture(scrubGesture(width: proxy.size.width), isEnabled: scrubEnabled)
                .onTapGesture { onExpand?() }
                // VoiceOver (IUI-5 X6): the drag scrub is unreachable by
                // switch/VoiceOver users — the sheet scrubber's adjustable
                // pattern, 5% steps; disabled while streaming like the drag.
                .accessibilityElement()
                .accessibilityLabel("Playback position")
                .accessibilityValue(controller.formatted(time: controller.currentTime))
                .accessibilityIdentifier("studio_inlinePlayer_scrubber")
                // Explicit activate: don't rely on SwiftUI synthesizing the
                // default action from the tap gesture on a collapsed element.
                .accessibilityAction { onExpand?() }
                .accessibilityAdjustableAction { direction in
                    guard scrubEnabled else { return }
                    // Step from the position currently shown BEFORE dropping
                    // the morph hold — displayedPlayhead collapses to the
                    // (lower) real playhead once holdFloor clears, and an
                    // up-swipe must never move the bar backward.
                    let current = displayedPlayhead
                    holdFloor = 0
                    let step = 0.05
                    switch direction {
                    case .increment: controller.scrub(to: min(1, current + step))
                    case .decrement: controller.scrub(to: max(0, current - step))
                    @unknown default: break
                    }
                }
            }
            .frame(height: 36)
            .onChange(of: isStreaming) { _, streaming in
                if streaming {
                    // New live preview → drop any stale hold.
                    lastStreamingFraction = 0
                    holdFloor = 0
                } else {
                    // The morph: hold the bar at the last live position so the denominator switch
                    // (estimate → actual duration) can't step it backward.
                    holdFloor = lastStreamingFraction
                }
            }
            .onChange(of: controller.currentTime) { _, _ in
                if isStreaming {
                    lastStreamingFraction = playheadFraction
                } else if holdFloor > 0, playheadFraction >= holdFloor {
                    // Real playback caught up to the held position → release (scrubbing works again).
                    holdFloor = 0
                }
            }

            // Always the real (generated-so-far → final) duration — stable format, never wraps,
            // and doesn't change "by much" across the live→complete morph. The estimate stays
            // internal (it only scales the streaming buffer-fill bands above).
            Text(controller.formatted(time: controller.duration))
                .font(.system(size: 13, weight: .semibold).monospacedDigit())
                .foregroundStyle(Theme.Text.secondary)
                .frame(width: 36, alignment: .trailing)
        }
    }

    private func scrubGesture(width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { value in
                // User took control → drop the morph hold so a scrub (either direction) isn't clamped.
                holdFloor = 0
                let ratio = max(0, min(1, value.location.x / max(1, width)))
                controller.scrub(to: ratio)
            }
    }
}

// MARK: - Playback controller

// @Observable (not ObservableObject) so SwiftUI tracks per-property: the card chrome
// (background/stroke/shadow) reads only `isPlaying` (changes on play/pause), while the
// per-tick `currentTime`/`progress` is read solely by the extracted InlineWaveformProgressRow.
// With the old ObservableObject, object-level objectWillChange re-rendered the whole card
// (incl. shadow) on every display-link tick regardless of view decomposition.
@MainActor
@Observable
final class IOSInlinePlaybackController: NSObject {
    private(set) var isPlaying: Bool = false
    private(set) var currentTime: TimeInterval = 0
    private(set) var duration: TimeInterval = 0

    private var player: AVAudioPlayer?
    private var displayLink: CADisplayLink?
    private var loadedURL: URL?

    // Streaming-adoption mode. For a generation owned by the shared AudioPlayerViewModel
    // (it played the live preview during generation and seamlessly handed off to the final
    // file), this controller MIRRORS + FORWARDS to that shared player instead of starting a
    // second AVAudioPlayer (which would double the audio). The `isAdopting` guard keys on the
    // shared player still playing this exact file; if it moves on (e.g. the user plays a
    // History item), we lazily fall back to our own player so the card can replay independently.
    private weak var sharedPlayer: AudioPlayerViewModel?
    private var adoptedURL: URL?

    // Live-mirror mode: the generation is still streaming, so there is no final
    // file URL to key on yet. We mirror/forward the shared player unconditionally
    // (it owns the live preview). The final card later re-adopts by URL (matched).
    private var isLiveMirroring = false

    private var isAdopting: Bool {
        if isLiveMirroring, sharedPlayer != nil { return true }
        guard player == nil, let shared = sharedPlayer, let url = adoptedURL else { return false }
        return shared.currentFilePath == url.path
    }

    var progress: Double {
        guard duration > 0 else { return 0 }
        return min(1.0, max(0.0, currentTime / duration))
    }

    /// Adopt the shared player for a generation it already owns (no second AVAudioPlayer).
    func adopt(sharedPlayer: AudioPlayerViewModel, url: URL) {
        self.sharedPlayer = sharedPlayer
        self.adoptedURL = url
        self.loadedURL = url
        self.isPlaying = sharedPlayer.isPlaying
        self.currentTime = sharedPlayer.currentTime
        self.duration = sharedPlayer.duration
        startDisplayLink()
    }

    /// Mirror the shared player's LIVE streaming preview (generation still in flight,
    /// no final file URL yet). Forwards play/pause to the shared player and mirrors
    /// its position/duration via the display-link tick. Never spawns its own player.
    func adoptLive(sharedPlayer: AudioPlayerViewModel) {
        self.sharedPlayer = sharedPlayer
        self.isLiveMirroring = true
        self.adoptedURL = nil
        self.isPlaying = sharedPlayer.isPlaying
        self.currentTime = sharedPlayer.currentTime
        self.duration = sharedPlayer.duration
        startDisplayLink()
    }

    /// Lazily create our own player from the adopted URL once the shared player has moved on,
    /// so the card can replay/scrub independently. Resumes from the last mirrored position.
    @discardableResult
    private func ensureOwnPlayer() -> Bool {
        if player != nil { return true }
        guard let url = adoptedURL ?? loadedURL else { return false }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true, options: [])
            let p = try AVAudioPlayer(contentsOf: url)
            p.delegate = self
            p.prepareToPlay()
            p.currentTime = min(currentTime, max(0, p.duration - 0.05))
            self.player = p
            self.duration = p.duration
            return true
        } catch {
            return false
        }
    }

    func load(url: URL, autoplay: Bool) async {
        guard loadedURL != url else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [])
            try session.setActive(true, options: [])
            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            player.prepareToPlay()
            self.player = player
            self.loadedURL = url
            self.duration = player.duration
            self.currentTime = 0
            if autoplay { play() }
        } catch {
            self.player = nil
            self.duration = 0
        }
    }

    func play() {
        if isAdopting {
            sharedPlayer?.play()
            isPlaying = true
            startDisplayLink()
            return
        }
        guard ensureOwnPlayer(), let player else { return }
        player.play()
        isPlaying = true
        startDisplayLink()
    }

    func pause() {
        if isAdopting {
            sharedPlayer?.pause()
            isPlaying = false
            stopDisplayLink()
            return
        }
        player?.pause()
        isPlaying = false
        stopDisplayLink()
    }

    func togglePlayback() {
        if isAdopting {
            sharedPlayer?.togglePlayPause()
            let playing = sharedPlayer?.isPlaying ?? false
            isPlaying = playing
            if playing { startDisplayLink() } else { stopDisplayLink() }
            return
        }
        if isPlaying { pause() } else {
            if let player, !player.isPlaying, currentTime >= duration {
                player.currentTime = 0
                currentTime = 0
            }
            play()
        }
    }

    func stop() {
        // When adopting, never stop the shared (global) player on card teardown — just stop
        // mirroring it. Only our own player is stopped.
        if sharedPlayer != nil && player == nil {
            stopDisplayLink()
            return
        }
        player?.stop()
        isPlaying = false
        stopDisplayLink()
    }

    func scrub(to fraction: Double) {
        let clamped = max(0, min(1, fraction))
        if isAdopting {
            sharedPlayer?.seek(to: clamped)
            currentTime = sharedPlayer?.currentTime ?? (duration * clamped)
            return
        }
        guard let player else { return }
        let target = duration * clamped
        player.currentTime = target
        currentTime = target
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
        // ~38 waveform bars and a per-second time label don't need 30fps; ~15fps keeps the
        // progress smooth at half the ticks (iOS frontend perf audit, Wave 3).
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 8, maximum: 30, preferred: 15)
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    private func stopDisplayLink() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func tick(_ link: CADisplayLink) {
        if isAdopting, let shared = sharedPlayer {
            isPlaying = shared.isPlaying
            currentTime = shared.currentTime
            if shared.duration > 0 { duration = shared.duration }
            return
        }
        guard let player else { return }
        currentTime = player.currentTime
        if !player.isPlaying && isPlaying {
            isPlaying = false
            stopDisplayLink()
        }
    }
}

extension IOSInlinePlaybackController: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.isPlaying = false
            self.currentTime = self.duration
            self.stopDisplayLink()
        }
    }
}
