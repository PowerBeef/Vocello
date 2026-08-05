import Foundation
import AVFoundation
import Combine

#if canImport(QwenVoiceCore)
import QwenVoiceCore
#endif

#if canImport(QwenVoiceNative)
import QwenVoiceNative
#endif

#if canImport(QwenVoiceNative)
typealias PlaybackGenerationResult = QwenVoiceNative.GenerationResult
#elseif canImport(QwenVoiceCore)
typealias PlaybackGenerationResult = QwenVoiceCore.GenerationResult
#endif

struct LivePreviewEstimate: Equatable, Sendable {
    let estimatedAudioDuration: TimeInterval

    init?(text: String) {
        let estimate = Self.estimatedAudioDuration(for: text)
        guard estimate > 0 else { return nil }
        estimatedAudioDuration = estimate
    }

    func requiredBufferDuration(
        minimumBufferedDuration: TimeInterval,
        maximumBufferedDuration: TimeInterval = 8,
        fraction: Double = 0.35
    ) -> TimeInterval {
        guard estimatedAudioDuration > 0 else { return 0 }
        let smoothBuffer = max(
            minimumBufferedDuration,
            min(maximumBufferedDuration, estimatedAudioDuration * fraction)
        )
        return min(estimatedAudioDuration, smoothBuffer)
    }

    private static func estimatedAudioDuration(for text: String) -> TimeInterval {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return 0 }

        let words = trimmed
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .count
        let nonWhitespaceCharacters = trimmed.reduce(into: 0) { count, character in
            if !character.isWhitespace {
                count += 1
            }
        }
        let punctuationPauses = trimmed.reduce(into: 0) { count, character in
            if ".!?;:,\n".contains(character) {
                count += 1
            }
        }

        let wordsPerSecond = 2.45
        let charactersPerSecond = 16.0
        let wordEstimate = Double(words) / wordsPerSecond
        let characterEstimate = Double(nonWhitespaceCharacters) / charactersPerSecond
        let pauseEstimate = Double(punctuationPauses) * 0.08
        return max(0.8, max(wordEstimate, characterEstimate) + pauseEstimate)
    }
}

/// Manages playback state for the persistent sidebar player bar.
@MainActor
final class AudioPlayerViewModel: NSObject, ObservableObject, AVAudioPlayerDelegate {

    enum PlaybackPresentationContext: Equatable, Sendable {
        case none
        case generatePreview
        case library
    }

    enum GeneratePreviewVisibilityState: Equatable, Sendable {
        case hidden
        case preparing
        case ready
    }

    // MARK: - High-frequency playback progress (isolated to avoid fan-out)

    /// Lightweight observable that holds timer-driven properties (currentTime, duration).
    /// Only views that need per-frame progress (e.g. SidebarPlayerView) should subscribe.
    @MainActor
    final class PlaybackProgress: ObservableObject {
        @Published var currentTime: TimeInterval = 0
        @Published var duration: TimeInterval = 0

        var progress: Double {
            guard duration > 0 else { return 0 }
            return min(max(currentTime / duration, 0), 1)
        }

        var formattedCurrentTime: String { AudioPlayerViewModel.formatTime(currentTime) }
        var formattedDuration: String { AudioPlayerViewModel.formatTime(duration) }
    }

    let playbackProgress = PlaybackProgress()

    // MARK: - Published State (low-frequency)

    @Published var isPlaying = false
    @Published var currentFilePath: String?
    @Published var currentTitle: String = ""
    @Published var waveformSamples: [Float] = []
    @Published var playbackError: String?
    @Published private(set) var isLiveStream = false
    // Demoted from @Published (iOS frontend perf audit, Wave 3): these have ZERO SwiftUI
    // readers — `livePreviewQueueDepth` is written on every streamed chunk but consumed only
    // internally. Publishing them fired AudioPlayerViewModel.objectWillChange per chunk,
    // invalidating every observer (notably the 3 Studio mode views, which inject this VM via
    // @EnvironmentObject only for imperative cancel/abort, rendering none of its state). Plain
    // stored properties remove that per-chunk broadcast at the source; the high-frequency
    // progress is already isolated in the PlaybackProgress slice. If a streaming-progress UI
    // ever needs these, move them into a nested ObservableObject slice (mirror PlaybackProgress).
    private(set) var livePreviewQueueDepth = 0
    private(set) var livePreviewPhase: LivePreviewPhase = .idle
    @Published private(set) var playbackPresentationContext: PlaybackPresentationContext = .none
    @Published private(set) var generatePreviewVisibilityState: GeneratePreviewVisibilityState = .hidden

    private enum PlaybackMode {
        case none
        case file
        case live
    }

    enum LivePreviewPhase: String, Sendable, Equatable {
        case idle
        case buffering
        case playing
        case draining
        case finalizing
    }

    struct FinalPlaybackHandoff: Equatable, Sendable {
        let preserveCurrentTime: TimeInterval
        let shouldAutoPlay: Bool
    }

    private struct LivePreviewConfiguration {
        let prebufferThreshold: Int
        let minimumBufferedDuration: TimeInterval

        static func current(
            environment: [String: String] = ProcessInfo.processInfo.environment
        ) -> LivePreviewConfiguration {
            let rawThreshold = RuntimeDebugGate.value(
                for: "QWENVOICE_LIVE_PREVIEW_PREBUFFER_CHUNKS",
                environment: environment
            )
            let parsedThreshold = rawThreshold.flatMap(Int.init).map { min(max($0, 1), 8) }
            let rawDuration = RuntimeDebugGate.value(
                for: "QWENVOICE_LIVE_PREVIEW_PREBUFFER_SECONDS",
                environment: environment
            )
            let parsedDuration = rawDuration.flatMap(Double.init).map { min(max($0, 0), 8) }
            return LivePreviewConfiguration(
                prebufferThreshold: parsedThreshold ?? 3,
                minimumBufferedDuration: parsedDuration ?? 3.25
            )
        }
    }

    /// Decides whether the live-preview player has enough buffered
    /// audio to begin (or resume) playback.
    ///
    /// Two policies, picked per-call:
    ///
    /// 1. **Smooth-first estimate** — production generation passes an
    ///    estimated audio duration before streaming begins. The preview
    ///    waits for a conservative queue depth:
    ///    `max(3.25s, min(8s, estimatedDuration * 0.35))`, capped by
    ///    the estimated duration for short clips.
    ///
    /// 2. **Adaptive fallback** — when no estimate exists, each underrun multiplies
    ///    the prebuffer requirement by +75 % up to a 4× cap. Trades
    ///    fast first-audio for periodic mid-playback pauses that
    ///    grow further apart on subsequent resumes.
    private static func shouldStartLivePlayback(
        autoplayEnabled: Bool,
        queuedChunks: Int,
        queuedDuration: TimeInterval,
        prebufferThreshold: Int,
        minimumBufferedDuration: TimeInterval,
        finalFileAvailable: Bool,
        underrunCount: Int = 0,
        estimate: LivePreviewEstimate? = nil
    ) -> Bool {
        guard autoplayEnabled else {
            AppPerformanceSignposts.emit("Should Start Reject Autoplay")
            return false
        }
        guard !finalFileAvailable else { return true }

        if let estimate {
            let requiredBuffer = estimate.requiredBufferDuration(
                minimumBufferedDuration: minimumBufferedDuration
            )
            let pass = queuedDuration >= requiredBuffer
            if !pass {
                AppPerformanceSignposts.emit("Should Start Reject Buffer")
            }
            return pass
        }

        // Policy 2 — fallback adaptive scaling (no estimate).
        // Reached when `setLivePreviewEstimate` was not called or
        // returned nil. Keeps the historical chunk-count + duration
        // thresholds with underrun-driven scaling so a session that
        // does drain dry adapts after the first stall.
        let multiplier = min(1.0 + 0.75 * Double(max(underrunCount, 0)), 4.0)
        let scaledChunks = max(
            prebufferThreshold,
            Int((Double(prebufferThreshold) * multiplier).rounded(.up))
        )
        let scaledDuration = minimumBufferedDuration * multiplier

        let pass = queuedChunks >= scaledChunks && queuedDuration >= scaledDuration
        if !pass {
            AppPerformanceSignposts.emit("Should Start Reject Buffer")
        }
        return pass
    }

    private var playbackMode: PlaybackMode = .none
    private var player: AVAudioPlayer?
    /// AVAudioEngine graph + FIFO scheduled-buffer bookkeeping (W2-D
    /// extraction; see `LiveStreamingPlaybackEngine`). Session identity,
    /// staleness guards, published state, timers, and telemetry stay here.
    private let livePlayback = LiveStreamingPlaybackEngine()
    // Smooth-first prebuffer state — set before generation starts,
    // picked up by startLiveSession, cleared at session end.
    private var pendingLivePreviewEstimate: LivePreviewEstimate?
    private var livePreviewEstimate: LivePreviewEstimate?
    private var liveExpectedFrameOffset: Int64?
    private var livePreviewDisabledSessionID: String?
    private var liveSessionID: String?
    private var liveSessionDirectory: String?
    private var liveFinalFilePath: String?
    private var liveAutoplayEnabled = false
    private var pendingFirstChunkInterval: AppPerformanceSignposts.Interval?
    private var pendingAutoplaySignpost = false
    private var livePlaybackStarted = false
    private var livePreviewDuration: TimeInterval = 0
    private var livePlaybackTimeOffset: TimeInterval = 0
    private var liveUnderrunCount = 0
    private var completedLiveSessionIDs: Set<String> = []
    private var completedLiveSessionOrder: [String] = []
    private let livePreviewConfiguration: LivePreviewConfiguration
    private var chunkObserver: NSObjectProtocol?
    private var chunkCancellable: AnyCancellable?
    private var timer: Timer?
    #if os(iOS)
    private var interruptionObserver: NSObjectProtocol?
    private var routeChangeObserver: NSObjectProtocol?
    private var shouldResumeAfterInterruption = false
    /// During a headless batch run, streamed chunks are ignored so each item
    /// doesn't start the live-preview player. The engine still streams
    /// internally (flat memory), and dropped PCM chunk events carry no files
    /// to clean up (NativeStreamingOutputPolicy defaults to .pcmPreview).
    private(set) var batchSuppressionActive = false
    #endif

    private func setLivePreviewQueueDepth(_ value: Int) {
        guard livePreviewQueueDepth != value else { return }
        livePreviewQueueDepth = value
    }

    private func setLivePreviewPhase(_ value: LivePreviewPhase) {
        guard livePreviewPhase != value else { return }
        livePreviewPhase = value
    }

    var hasAudio: Bool { currentFilePath != nil || isLiveStream || liveSessionID != nil }
    var canSeek: Bool { playbackMode == .file || liveFinalFilePath != nil }
    var durationDisplayText: String { isLiveStream && liveFinalFilePath == nil ? "Live" : playbackProgress.formattedDuration }
    var activeGeneratePreviewVisibilityState: GeneratePreviewVisibilityState {
        playbackPresentationContext == .generatePreview ? generatePreviewVisibilityState : .hidden
    }

    /// True when the global now-playing rail should be mounted above the studio dock.
    /// Covers Generate-preview preparing/ready states and any Library playback.
    var isShowingNowPlayingRail: Bool {
        if generatePreviewVisibilityState != .hidden { return true }
        return currentFilePath != nil || isLiveStream
    }

    /// Label for the rail's context chip, or nil when no chip should render.
    var nowPlayingContextChipLabel: String? {
        switch playbackPresentationContext {
        case .generatePreview: return "Preview"
        case .library: return "Library"
        case .none: return nil
        }
    }

    /// Non-published pass-through for callers that need the current value without subscribing.
    var currentTime: TimeInterval {
        get { playbackProgress.currentTime }
        set { playbackProgress.currentTime = newValue }
    }

    var duration: TimeInterval {
        get { playbackProgress.duration }
        set { playbackProgress.duration = newValue }
    }

    override init() {
        livePreviewConfiguration = .current()
        super.init()
        bindGenerationEventSource()
        #if os(iOS)
        registerAudioSessionObservers()
        #endif
    }

    deinit {
        MainActor.assumeIsolated {
            #if os(iOS)
            if let interruptionObserver {
                NotificationCenter.default.removeObserver(interruptionObserver)
            }
            if let routeChangeObserver {
                NotificationCenter.default.removeObserver(routeChangeObserver)
            }
            #endif
            timer?.invalidate()
            if let chunkObserver {
                NotificationCenter.default.removeObserver(chunkObserver)
            }
            chunkCancellable?.cancel()
            teardownLivePlayback(clearSession: true)
            stopFilePlayback(clearPlayer: true)
        }
    }

    #if os(iOS)
    /// Pause for audio-session interruptions (calls/Siri) and route changes
    /// (headphones/Bluetooth unplugged). Without these, an interrupted player
    /// sits in a stale `isPlaying` state and an unplug keeps audio blasting
    /// from the speaker — both are App Store quality + HIG concerns.
    private func registerAudioSessionObservers() {
        let center = NotificationCenter.default
        interruptionObserver = center.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            // Extract Sendable raw values before the actor hop (Notification is not Sendable).
            let typeRaw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let optionsRaw = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt
            MainActor.assumeIsolated { self?.handleAudioSessionInterruption(typeRaw: typeRaw, optionsRaw: optionsRaw) }
        }
        routeChangeObserver = center.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            let reasonRaw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            MainActor.assumeIsolated { self?.handleAudioRouteChange(reasonRaw: reasonRaw) }
        }
    }

    private func handleAudioSessionInterruption(typeRaw: UInt?, optionsRaw: UInt?) {
        guard let typeRaw, let type = AVAudioSession.InterruptionType(rawValue: typeRaw) else { return }
        switch type {
        case .began:
            // Only file playback is safely resumable; a live streaming preview
            // is transient and should not auto-resume mid-generation.
            shouldResumeAfterInterruption = isPlaying && playbackMode == .file
            if isPlaying { pause() }
        case .ended:
            guard shouldResumeAfterInterruption, playbackMode == .file else { return }
            shouldResumeAfterInterruption = false
            if let optionsRaw,
               AVAudioSession.InterruptionOptions(rawValue: optionsRaw).contains(.shouldResume) {
                play()
            }
        @unknown default:
            break
        }
    }

    private func handleAudioRouteChange(reasonRaw: UInt?) {
        guard let reasonRaw,
              AVAudioSession.RouteChangeReason(rawValue: reasonRaw) == .oldDeviceUnavailable else { return }
        if isPlaying { pause() }
    }

    /// Toggle batch suppression. Enabling it tears down any active live preview
    /// so a batch run generates headlessly without audible per-item playback.
    func setBatchSuppression(_ active: Bool) {
        batchSuppressionActive = active
        if active { abortLivePreviewIfNeeded() }
    }
    #endif

    // MARK: - Playback

    func load(
        filePath: String,
        title: String = "",
        presentationContext: PlaybackPresentationContext = .library
    ) {
        pendingAutoplaySignpost = false
        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)

        do {
            try applyFilePlayback(
                filePath: filePath,
                title: title,
                preserveCurrentTime: 0,
                autoPlay: false,
                transitionFromLive: false,
                presentationContext: presentationContext
            )
        } catch {
            clearLoadedAudio()
            resetPresentationState()
            playbackError = error.localizedDescription
        }
    }

    func play() {
        switch playbackMode {
        case .live:
            attemptLivePlay()
        case .file:
            attemptFilePlay()
        case .none:
            break
        }
    }

    func pause() {
        switch playbackMode {
        case .live:
            livePlayback.pauseNode()
            isPlaying = false
            stopTimer()
        case .file:
            player?.pause()
            isPlaying = false
            stopTimer()
        case .none:
            break
        }
    }

    func togglePlayPause() {
        if isPlaying { pause() } else { play() }
    }

    func stop() {
        switch playbackMode {
        case .live:
            stopLivePlayback(resetCurrentTime: true)
        case .file:
            stopFilePlayback(clearPlayer: false)
            currentTime = 0
        case .none:
            break
        }
    }

    func dismiss() {
        pendingAutoplaySignpost = false
        stop()
        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)
        clearLoadedAudio()
        playbackError = nil
        playbackMode = .none
        isLiveStream = false
        setLivePreviewQueueDepth(0)
        setLivePreviewPhase(.idle)
        resetPresentationState()
    }

    func seek(to fraction: Double) {
        guard canSeek else { return }

        let clampedFraction = max(0, min(1, fraction))
        let targetTime = clampedFraction * duration

        if playbackMode == .live, liveFinalFilePath != nil {
            switchToFinalFilePlayback(
                preserveCurrentTime: targetTime,
                autoPlay: isPlaying
            )
            return
        }

        guard let player else { return }
        player.currentTime = targetTime
        currentTime = targetTime
    }

    func playFile(
        _ path: String,
        title: String = "",
        isAutoplay: Bool = false,
        presentationContext: PlaybackPresentationContext = .library
    ) {
        load(filePath: path, title: title, presentationContext: presentationContext)
        if isAutoplay {
            pendingAutoplaySignpost = true
        }
        guard player != nil else { return }
        play()
    }

    /// Sets a prompt-derived forecast so `shouldStartLivePlayback` can
    /// size the live-preview buffer before the first chunk arrives.
    /// Pass nil to fall back to adaptive chunk-count buffering for future
    /// sessions; an active live session keeps the estimate it already
    /// captured.
    func setLivePreviewEstimate(_ estimate: LivePreviewEstimate?) {
        pendingLivePreviewEstimate = estimate
    }

    func prepareStreamingPreview(title: String, shouldAutoPlay: Bool) {
        let sessionEstimate = pendingLivePreviewEstimate
            ?? livePreviewEstimate
            ?? LivePreviewEstimate(text: title)

        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)
        clearPendingFirstChunkInterval()

        playbackMode = .live
        liveSessionID = "pending-\(UUID().uuidString)"
        liveSessionDirectory = nil
        liveFinalFilePath = nil
        liveAutoplayEnabled = shouldAutoPlay
        pendingAutoplaySignpost = shouldAutoPlay
        pendingFirstChunkInterval = AppPerformanceSignposts.begin("Preview To First Chunk")
        livePlayback.resetBookkeeping()
        livePlayback.clearFormat()
        livePlaybackStarted = false
        livePreviewDuration = 0
        livePlaybackTimeOffset = 0
        liveUnderrunCount = 0
        livePreviewEstimate = sessionEstimate
        pendingLivePreviewEstimate = nil
        liveExpectedFrameOffset = 0
        livePreviewDisabledSessionID = nil
        currentTitle = title
        currentFilePath = nil
        duration = 0
        currentTime = 0
        waveformSamples = []
        playbackError = nil
        isPlaying = false
        isLiveStream = true
        setLivePreviewQueueDepth(0)
        setLivePreviewPhase(.buffering)
        playbackPresentationContext = .generatePreview
        generatePreviewVisibilityState = .preparing
        // Pre-warm the AVAudioEngine + player node + audio graph with
        // the engine's expected output format (24 kHz Int16 mono per
        // the Qwen3-TTS streaming contract). This avoids paying the
        // allocation/connect cost on the first live chunk.
        // `configure` is idempotent against an identical format so the
        // chunk-arrival site is a cheap no-op when the format matches; if
        // it ever mismatches (different model or contract change) the
        // chunk site falls back to reconfiguring.
        if let prewarmFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 24_000,
            channels: 1,
            interleaved: false
        ) {
            livePlayback.configure(with: prewarmFormat)
        }
    }

    func completeStreamingPreview(result: PlaybackGenerationResult, title: String, shouldAutoPlay: Bool) {
        guard result.usedStreaming else {
            if shouldAutoPlay {
                playFile(
                    result.audioPath,
                    title: title,
                    isAutoplay: true,
                    presentationContext: .generatePreview
                )
            }
            return
        }

        currentTitle = title
        currentFilePath = result.audioPath
        liveFinalFilePath = result.audioPath
        // Audit Finding #2 — DO NOT add `liveSessionID` to
        // `completedLiveSessionIDs` here. Two independent XPC paths
        // race on MainActor: the awaited generation result (this
        // function's caller) and the chunk broker
        // (`Task { @MainActor in subject.send }` inside
        // `GenerationChunkBroker.publish`). If the result-channel
        // continuation runs first and we record the session ID
        // immediately, any chunk still queued on the broker is
        // rejected by the guard at the top of
        // `handleGenerationChunk` and silently dropped. Defer the
        // record to the actual drain points below
        // (`finishLivePlaybackAfterDrainingBuffers` for the
        // live-still-playing path, the `if` block below for the
        // immediate-handoff path, and `teardownLivePlayback` for
        // dismissed sessions). All three call
        // `recordCompletedLiveSessionID` which is idempotent
        // (`Set.insert(_:).inserted`), so multiple invocations
        // from different paths are safe.
        if let streamSessionDirectory = result.streamSessionDirectory {
            liveSessionDirectory = streamSessionDirectory
        }
        duration = max(duration, result.durationSeconds)

        // Only transition immediately if live playback never started or all
        // buffers have already drained. Otherwise the existing buffer-drain
        // mechanism (handleLiveBufferPlaybackCompletion -> finishLivePlaybackAfterDrainingBuffers)
        // keeps playback moving from the heard preview position into the final file.
        if !livePlaybackStarted || livePlayback.scheduledCount == 0 {
            // Immediate-handoff branch: live preview is over (never
            // started or already drained). Any chunk arriving from
            // the broker now is genuinely stale. Record the session
            // as completed so the `handleGenerationChunk` guard
            // drops it.
            recordCompletedLiveSessionID(liveSessionID)
            let handoff = Self.finalPlaybackHandoff(
                heardLivePreview: livePlaybackStarted,
                currentTime: currentTime,
                previewDuration: livePreviewDuration,
                duration: duration,
                autoPlayEnabled: shouldAutoPlay
            )
            switchToFinalFilePlayback(
                preserveCurrentTime: handoff.preserveCurrentTime,
                autoPlay: handoff.shouldAutoPlay
            )
        }
        // Else: live preview still draining. Late chunks that
        // arrive between now and the drain are appended naturally
        // by `appendLiveChunk` (the session ID is NOT in
        // `completedLiveSessionIDs` yet, so the guard lets them
        // through). When the queue drains and
        // `finishLivePlaybackAfterDrainingBuffers` fires, the
        // session ID is recorded there.
    }

    func abortLivePreviewIfNeeded() {
        pendingLivePreviewEstimate = nil
        guard playbackMode == .live || liveSessionID != nil else { return }
        dismiss()
    }

    // MARK: - Notifications

    private struct ChunkInfo: Sendable {
        let generationID: UUID?
        let requestID: Int
        let title: String
        let chunkPath: String?
        let previewAudio: StreamingAudioChunk?
        let sessionDirectory: String?
        let cumulativeDuration: Double?
    }

    private func bindGenerationEventSource() {
#if canImport(QwenVoiceNative)
        // The broker is `@MainActor` and its `publish(_:)` always
        // sends from a `Task { @MainActor in ... }`, so the sink
        // already runs on the MainActor. Dropping the previous
        // `.receive(on: DispatchQueue.main)` saves a second scheduling
        // hop on every chunk.
        chunkCancellable = GenerationChunkBroker.shared.publisher
            .sink { [weak self] event in
                guard let self,
                      let requestID = event.requestID,
                      let title = event.title,
                      event.chunkPath != nil || event.previewAudio != nil else { return }
                let chunk = ChunkInfo(
                    generationID: event.generationID,
                    requestID: requestID,
                    title: title,
                    chunkPath: event.chunkPath,
                    previewAudio: event.previewAudio,
                    sessionDirectory: event.streamSessionDirectory,
                    cumulativeDuration: event.cumulativeDurationSeconds
                )
                self.handleGenerationChunk(chunk)
            }
#else
        chunkObserver = NotificationCenter.default.addObserver(
            forName: .generationChunkReceived,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let userInfo = notification.userInfo else { return }
            let chunk: ChunkInfo?
            if let generationChunk = userInfo["chunk"] as? GenerationChunk,
               let requestID = generationChunk.requestID {
                chunk = ChunkInfo(
                    generationID: generationChunk.generationID,
                    requestID: requestID,
                    title: generationChunk.title,
                    chunkPath: generationChunk.chunkPath,
                    previewAudio: generationChunk.previewAudio,
                    sessionDirectory: generationChunk.streamSessionDirectory,
                    cumulativeDuration: generationChunk.cumulativeDurationSeconds
                )
            } else if let requestID = userInfo["requestID"] as? Int,
                      let title = userInfo["title"] as? String,
                      let chunkPath = userInfo["chunkPath"] as? String {
                chunk = ChunkInfo(
                    generationID: userInfo["generationID"] as? UUID,
                    requestID: requestID,
                    title: title,
                    chunkPath: chunkPath,
                    previewAudio: nil,
                    sessionDirectory: userInfo["streamSessionDirectory"] as? String,
                    cumulativeDuration: userInfo["cumulativeDurationSeconds"] as? Double
                )
            } else {
                chunk = nil
            }
            guard let chunk else { return }
            // The observer is registered with `queue: .main`, so this closure runs on
            // the main thread = the MainActor's executor. `assumeIsolated` invokes the
            // handler synchronously and drops the per-chunk `Task { @MainActor }`
            // scheduling hop (mirrors the broker fast-path above) — one less wakeup per
            // chunk during the time-sensitive streaming phase.
            MainActor.assumeIsolated {
                self?.handleGenerationChunk(chunk)
            }
        }
#endif
    }

    private func handleGenerationChunk(_ chunk: ChunkInfo) {
        #if os(iOS)
        // Batch runs headlessly: drop streamed chunks so items don't live-play.
        if batchSuppressionActive { return }
        #endif
        let sessionID = chunk.generationID?.uuidString ?? String(chunk.requestID)
        AppPerformanceSignposts.emit("Chunk Received")
        AppGenerationTimeline.shared.recordFirstChunk(id: sessionID)
        guard !completedLiveSessionIDs.contains(sessionID) else {
            AppPerformanceSignposts.emit("Chunk Dropped Completed")
            return
        }

        let sessionDirectory = chunk.sessionDirectory
        let cumulativeDuration = chunk.cumulativeDuration

        if liveSessionID != sessionID {
            startLiveSession(
                id: sessionID,
                title: chunk.title,
                sessionDirectory: sessionDirectory,
                autoPlay: AudioService.shouldAutoPlay
            )
        }
        guard livePreviewDisabledSessionID != sessionID else {
            AppPerformanceSignposts.emit("Chunk Dropped Preview Disabled")
            return
        }

        if let previewAudio = chunk.previewAudio {
            appendLiveChunk(
                previewAudio,
                cumulativeDuration: cumulativeDuration
            )
        } else if let chunkPath = chunk.chunkPath {
            appendLiveChunk(
                from: URL(fileURLWithPath: chunkPath),
                cumulativeDuration: cumulativeDuration
            )
        }
    }

    // MARK: - Live Playback

    private func recordCompletedLiveSessionID(_ sessionID: String?) {
        guard let sessionID, !sessionID.hasPrefix("pending-") else { return }
        guard completedLiveSessionIDs.insert(sessionID).inserted else { return }
        AppPerformanceSignposts.emit("Session Completed Recorded")
        completedLiveSessionOrder.append(sessionID)

        let maximumRetainedSessionIDs = 16
        while completedLiveSessionOrder.count > maximumRetainedSessionIDs {
            let expiredID = completedLiveSessionOrder.removeFirst()
            completedLiveSessionIDs.remove(expiredID)
        }
    }

    private func startLiveSession(id: String, title: String, sessionDirectory: String?, autoPlay: Bool) {
        let sessionEstimate = pendingLivePreviewEstimate
            ?? livePreviewEstimate
            ?? LivePreviewEstimate(text: title)

        AppPerformanceSignposts.emit("Live Session Start")
        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)

        playbackMode = .live
        liveSessionID = id
        liveSessionDirectory = sessionDirectory
        liveFinalFilePath = nil
        liveAutoplayEnabled = autoPlay
        // When `startLiveSession` fires from `handleGenerationChunk` (the
        // auto-init path used by every streaming generation today), nothing
        // upstream sets `pendingAutoplaySignpost`. Without it, the
        // "Autoplay Start" signpost never fires when live playback begins
        // — even though playback is actually happening. The bench harness
        // (and any forensic latency analysis) can't see the perceived-speed
        // gain. Set it here so the signpost mirrors the live engine's
        // play() call when autoplay is enabled for this session.
        pendingAutoplaySignpost = autoPlay
        livePlayback.resetBookkeeping()
        livePlayback.clearFormat()
        livePlaybackStarted = false
        livePreviewDuration = 0
        livePlaybackTimeOffset = 0
        liveUnderrunCount = 0
        // Smooth-first prebuffer estimate handoff: pending values
        // captured pre-generation become the active session's
        // estimate, then are cleared so a future session that arrives
        // without a fresh estimate falls back to adaptive scaling.
        livePreviewEstimate = sessionEstimate
        pendingLivePreviewEstimate = nil
        liveExpectedFrameOffset = 0
        livePreviewDisabledSessionID = nil
        currentTitle = title
        currentFilePath = nil
        duration = 0
        currentTime = 0
        waveformSamples = []
        playbackError = nil
        isPlaying = false
        isLiveStream = true
        setLivePreviewQueueDepth(0)
        setLivePreviewPhase(.buffering)
        playbackPresentationContext = .generatePreview
        generatePreviewVisibilityState = .preparing
    }

    private func appendLiveChunk(from url: URL, cumulativeDuration: TimeInterval?) {
        LivePreviewDiagnostics.logChunkEvent(
            "appendLiveChunk.enter",
            viewModel: self,
            url: url
        )
        guard let (buffer, fileFormat) = loadPCMBuffer(from: url) else {
            LivePreviewDiagnostics.logChunkEvent(
                "appendLiveChunk.decode_failed",
                viewModel: self,
                url: url
            )
            playbackError = "Live audio preview could not decode the latest chunk."
            return
        }

        if !livePlayback.isConfigured {
            livePlayback.configure(with: fileFormat)
        }

        AppPerformanceSignposts.emit("Chunk Decoded")
        let chunkAudioSeconds = TimeInterval(buffer.frameLength) / fileFormat.sampleRate
        enqueueLiveBuffer(buffer, chunkAudioSeconds: chunkAudioSeconds)
        AppGenerationTimeline.shared.recordPlaybackChunk(
            id: liveSessionID,
            queuedAudioSeconds: livePlayback.queuedAudioSeconds
        )

        livePreviewDuration = cumulativeDuration
            ?? (livePreviewDuration + chunkAudioSeconds)
        duration = max(duration, livePreviewDuration)
        markGeneratePreviewReadyIfNeeded()
        if let pendingFirstChunkInterval {
            AppPerformanceSignposts.end(pendingFirstChunkInterval)
            AppPerformanceSignposts.emit("First Chunk Received")
            self.pendingFirstChunkInterval = nil
        }

        if Self.shouldStartLivePlayback(
            autoplayEnabled: liveAutoplayEnabled,
            queuedChunks: livePlayback.scheduledCount,
            queuedDuration: livePlayback.queuedAudioSeconds,
            prebufferThreshold: livePreviewConfiguration.prebufferThreshold,
            minimumBufferedDuration: livePreviewConfiguration.minimumBufferedDuration,
            finalFileAvailable: liveFinalFilePath != nil,
            underrunCount: liveUnderrunCount,
            estimate: livePreviewEstimate
        ) {
            attemptLivePlay()
        } else {
            setLivePreviewPhase(.buffering)
        }

        LivePreviewDiagnostics.logChunkEvent(
            "appendLiveChunk.delete",
            viewModel: self,
            url: url
        )
        try? FileManager.default.removeItem(at: url)
        cleanupLiveSessionDirectoryIfEmpty()
    }

    private func validatePreviewAudioChunk(_ previewAudio: StreamingAudioChunk) -> Bool {
        guard previewAudio.sampleRate > 0,
              previewAudio.frameOffset >= 0,
              previewAudio.frameCount > 0,
              previewAudio.frameCount <= Int.max / MemoryLayout<Int16>.stride else {
            stopLivePreviewForChunkContinuityFailure()
            return false
        }

        let expectedByteCount = previewAudio.frameCount * MemoryLayout<Int16>.stride
        guard previewAudio.pcm16LE.count == expectedByteCount else {
            stopLivePreviewForChunkContinuityFailure()
            return false
        }

        if let expectedFrameOffset = liveExpectedFrameOffset,
           previewAudio.frameOffset != expectedFrameOffset {
            stopLivePreviewForChunkContinuityFailure()
            return false
        }

        liveExpectedFrameOffset = previewAudio.frameOffset + Int64(previewAudio.frameCount)
        return true
    }

    private func stopLivePreviewForChunkContinuityFailure() {
        AppPerformanceSignposts.emit("Live Preview Chunk Gap")
        AppGenerationTimeline.shared.recordPlaybackContinuityFailure(id: liveSessionID)
        livePreviewDisabledSessionID = liveSessionID
        stopLivePlayback(resetCurrentTime: true)
        livePlayback.resetBookkeeping()
        livePlaybackStarted = false
        livePreviewDuration = 0
        livePlaybackTimeOffset = 0
        liveUnderrunCount = 0
        liveExpectedFrameOffset = nil
        setLivePreviewQueueDepth(0)
        setLivePreviewPhase(.buffering)
    }

    private func appendLiveChunk(_ previewAudio: StreamingAudioChunk, cumulativeDuration: TimeInterval?) {
        guard validatePreviewAudioChunk(previewAudio) else { return }
        guard let (buffer, format) = makePCMBuffer(from: previewAudio) else {
            stopLivePreviewForChunkContinuityFailure()
            playbackError = "Live audio preview could not decode the latest chunk."
            return
        }

        if !livePlayback.isConfigured {
            livePlayback.configure(with: format)
        }

        AppPerformanceSignposts.emit("Chunk Decoded")
        let chunkAudioSeconds = TimeInterval(buffer.frameLength) / format.sampleRate
        enqueueLiveBuffer(buffer, chunkAudioSeconds: chunkAudioSeconds)
        AppGenerationTimeline.shared.recordPlaybackChunk(
            id: liveSessionID,
            queuedAudioSeconds: livePlayback.queuedAudioSeconds
        )

        livePreviewDuration = cumulativeDuration
            ?? (livePreviewDuration + chunkAudioSeconds)
        duration = max(duration, livePreviewDuration)
        markGeneratePreviewReadyIfNeeded()
        if let pendingFirstChunkInterval {
            AppPerformanceSignposts.end(pendingFirstChunkInterval)
            AppPerformanceSignposts.emit("First Chunk Received")
            self.pendingFirstChunkInterval = nil
        }

        if Self.shouldStartLivePlayback(
            autoplayEnabled: liveAutoplayEnabled,
            queuedChunks: livePlayback.scheduledCount,
            queuedDuration: livePlayback.queuedAudioSeconds,
            prebufferThreshold: livePreviewConfiguration.prebufferThreshold,
            minimumBufferedDuration: livePreviewConfiguration.minimumBufferedDuration,
            finalFileAvailable: liveFinalFilePath != nil,
            underrunCount: liveUnderrunCount,
            estimate: livePreviewEstimate
        ) {
            attemptLivePlay()
        } else {
            setLivePreviewPhase(.buffering)
        }
    }

    /// Shared enqueue path for both chunk formats: FIFO bookkeeping lives
    /// in the engine; the completion hop applies this view model's session
    /// staleness guards in `handleLiveBufferPlaybackCompletion`.
    private func enqueueLiveBuffer(_ buffer: AVAudioPCMBuffer, chunkAudioSeconds: TimeInterval) {
        livePlayback.enqueue(
            buffer,
            chunkAudioSeconds: chunkAudioSeconds,
            sessionID: liveSessionID
        ) { [weak self] sessionID in
            self?.handleLiveBufferPlaybackCompletion(sessionID: sessionID)
        }
        setLivePreviewQueueDepth(livePlayback.scheduledCount)
    }

    private func attemptLivePlay() {
        if liveFinalFilePath != nil, !isPlaying {
            let handoff = Self.finalPlaybackHandoff(
                heardLivePreview: livePlaybackStarted,
                currentTime: currentTime,
                previewDuration: livePreviewDuration,
                duration: duration,
                autoPlayEnabled: liveAutoplayEnabled
            )
            switchToFinalFilePlayback(
                preserveCurrentTime: handoff.preserveCurrentTime,
                autoPlay: handoff.shouldAutoPlay
            )
            return
        }

        guard livePlayback.isConfigured else { return }

        do {
            try livePlayback.startEngineIfNeeded()
            if !livePlayback.isNodePlaying {
                if livePlaybackStarted {
                    livePlaybackTimeOffset = currentTime
                    livePlayback.scheduleLeadingSilence()
                }
                livePlayback.playNode()
                AppGenerationTimeline.shared.recordPlaybackScheduled(
                    id: liveSessionID,
                    source: .liveStream,
                    queuedChunks: livePlayback.scheduledCount,
                    queuedAudioSeconds: livePlayback.queuedAudioSeconds
                )
                livePlaybackStarted = true
                AppPerformanceSignposts.emit("Live Engine Play")
            }
            isPlaying = true
            setLivePreviewPhase(.playing)
            playbackError = nil
            startTimer()
            consumeAutoplaySignpostIfNeeded()
        } catch {
            playbackError = "Playback could not start."
        }
    }

    private func handleLiveBufferPlaybackCompletion(sessionID: String? = nil) {
        guard playbackMode == .live else { return }
        // Phase 5 fix: reject stale completions from a previous session.
        // AVAudioEngine's completion callback hops to MainActor via Task,
        // which can be delayed long enough that a new session has already
        // started. Without this guard, those stale decrements clobber the
        // new session's buffer bookkeeping (liveScheduledCount /
        // liveQueuedAudioSeconds / liveBufferDurations), causing
        // shouldStartLivePlayback's Policy 2 to never trigger.
        // sessionID == nil means "legacy caller" (none today) — allow.
        if let scheduledID = sessionID, scheduledID != liveSessionID {
            AppPerformanceSignposts.emit("Stale Completion Dropped")
            return
        }
        if livePreviewDisabledSessionID == liveSessionID {
            return
        }
        livePlayback.drainCompletedBuffer()
        AppGenerationTimeline.shared.recordPlaybackQueueDepth(
            id: liveSessionID,
            queuedAudioSeconds: livePlayback.queuedAudioSeconds
        )
        setLivePreviewQueueDepth(livePlayback.scheduledCount)
        if livePlayback.scheduledCount > 0 {
            setLivePreviewPhase(isPlaying ? .playing : .draining)
        }
        if livePlayback.scheduledCount == 0, liveFinalFilePath != nil {
            setLivePreviewPhase(.finalizing)
            finishLivePlaybackAfterDrainingBuffers()
        } else if livePlayback.scheduledCount == 0 {
            liveUnderrunCount += 1
            AppPerformanceSignposts.emit("Live Preview Underrun")
            AppGenerationTimeline.shared.recordPlaybackUnderrun(id: liveSessionID)
            livePlayback.pauseNode()
            isPlaying = false
            stopTimer()
            setLivePreviewPhase(.buffering)
        }
    }

    private func finishLivePlaybackAfterDrainingBuffers() {
        // Audit Finding #2 — record the session as completed at
        // drain time, not when the result was delivered to
        // `completeStreamingPreview`. By now, all scheduled
        // buffers have played out (`.dataPlayedBack` callback for
        // the last buffer fired immediately before this function
        // was called); any chunk arriving now is truly stale.
        recordCompletedLiveSessionID(liveSessionID)

        let heardTime = max(currentTime, livePreviewDuration)
        stopLivePlayback(resetCurrentTime: false)
        currentTime = heardTime

        if liveFinalFilePath != nil {
            let handoff = Self.finalPlaybackHandoff(
                heardLivePreview: livePlaybackStarted,
                currentTime: currentTime,
                previewDuration: livePreviewDuration,
                duration: duration,
                autoPlayEnabled: liveAutoplayEnabled
            )
            switchToFinalFilePlayback(
                preserveCurrentTime: handoff.preserveCurrentTime,
                autoPlay: handoff.shouldAutoPlay
            )
        }
    }

    private func switchToFinalFilePlayback(preserveCurrentTime: TimeInterval, autoPlay: Bool) {
        guard let finalFilePath = liveFinalFilePath else { return }
        // Short generations can finish before the live prebuffer threshold is
        // reached. In that case autoplay starts from the finalized WAV instead
        // of AVAudioPlayerNode, but it is still the genuine frontend playback
        // scheduling boundary. Capture the live-session identity before
        // `applyFilePlayback` clears the streaming fields; the finalized-file
        // path records its own active buffer semantics at the successful
        // `AVAudioPlayer.play()` call.
        let telemetrySessionID = liveSessionID
        AppPerformanceSignposts.emit("Switch To File Playback")
        setLivePreviewPhase(.finalizing)

        do {
            try applyFilePlayback(
                filePath: finalFilePath,
                title: currentTitle,
                preserveCurrentTime: preserveCurrentTime,
                autoPlay: autoPlay,
                transitionFromLive: true,
                presentationContext: playbackPresentationContext,
                playbackTelemetrySessionID: telemetrySessionID
            )
        } catch {
            playbackError = error.localizedDescription
        }
    }

    private func teardownLivePlayback(clearSession: Bool) {
        // Audit Finding #2 — defensive record. If teardown is
        // reached without a completion-handoff path having fired
        // (user-driven dismiss, error-path teardown, etc.), the
        // session ID still belongs in `completedLiveSessionIDs` so
        // a later straggler chunk doesn't accidentally restart a
        // new live session via `startLiveSession`'s
        // `liveSessionID != sessionID` branch. Idempotent.
        recordCompletedLiveSessionID(liveSessionID)

        stopLivePlayback(resetCurrentTime: true)
        livePlayback.resetBookkeeping()
        livePlaybackStarted = false
        livePreviewDuration = 0
        livePlaybackTimeOffset = 0
        liveUnderrunCount = 0
        livePlayback.clearFormat()
        livePreviewEstimate = nil
        liveExpectedFrameOffset = nil
        setLivePreviewQueueDepth(0)
        clearPendingFirstChunkInterval()

        if clearSession {
            cleanupLiveSessionDirectory()
            liveSessionID = nil
            liveSessionDirectory = nil
            liveFinalFilePath = nil
            liveAutoplayEnabled = false
            pendingLivePreviewEstimate = nil
            livePreviewDisabledSessionID = nil
            isLiveStream = false
            setLivePreviewPhase(.idle)
            // Discard the audio graph so the next session rebuilds fresh
            // (Phase 4 fix rationale lives with
            // `LiveStreamingPlaybackEngine.discardGraph`).
            livePlayback.discardGraph()
        }
    }

    private func stopLivePlayback(resetCurrentTime: Bool) {
        livePlayback.stopAndReset()
        isPlaying = false
        stopTimer()
        if resetCurrentTime {
            currentTime = 0
        }
    }

    private func cleanupLiveSessionDirectoryIfEmpty() {
        guard liveFinalFilePath != nil else { return }
        guard let liveSessionDirectory else { return }
        let directoryURL = URL(fileURLWithPath: liveSessionDirectory, isDirectory: true)
        let contents = (try? FileManager.default.contentsOfDirectory(atPath: directoryURL.path)) ?? []
        if contents.isEmpty {
            try? FileManager.default.removeItem(at: directoryURL)
        }
    }

    private func cleanupLiveSessionDirectory() {
        guard let liveSessionDirectory else { return }
        try? FileManager.default.removeItem(at: URL(fileURLWithPath: liveSessionDirectory, isDirectory: true))
    }

    private func loadPCMBuffer(from url: URL) -> (AVAudioPCMBuffer, AVAudioFormat)? {
        let audioFile: AVAudioFile
        do {
            audioFile = try AVAudioFile(forReading: url)
        } catch {
            LivePreviewDiagnostics.logDecodeFailure(
                "AVAudioFile(forReading:)",
                viewModel: self,
                url: url,
                error: error
            )
            return nil
        }
        let format = audioFile.processingFormat
        let frameCapacity = AVAudioFrameCount(audioFile.length)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCapacity) else {
            LivePreviewDiagnostics.logDecodeFailure(
                "AVAudioPCMBuffer(frameCapacity: \(frameCapacity))",
                viewModel: self,
                url: url,
                error: nil
            )
            return nil
        }

        do {
            try audioFile.read(into: buffer)
            return (buffer, format)
        } catch {
            LivePreviewDiagnostics.logDecodeFailure(
                "audioFile.read(into:)",
                viewModel: self,
                url: url,
                error: error
            )
            return nil
        }
    }

    private func makePCMBuffer(from previewAudio: StreamingAudioChunk) -> (AVAudioPCMBuffer, AVAudioFormat)? {
        guard previewAudio.frameCount > 0,
              previewAudio.pcm16LE.count == previewAudio.frameCount * MemoryLayout<Int16>.stride,
              let format = AVAudioFormat(
                  commonFormat: .pcmFormatInt16,
                  sampleRate: Double(previewAudio.sampleRate),
                  channels: 1,
                  interleaved: false
              ),
              let buffer = AVAudioPCMBuffer(
                  pcmFormat: format,
                  frameCapacity: AVAudioFrameCount(previewAudio.frameCount)
              ),
              let channelData = buffer.int16ChannelData?[0] else {
            return nil
        }

        buffer.frameLength = AVAudioFrameCount(previewAudio.frameCount)
        previewAudio.pcm16LE.withUnsafeBytes { rawBuffer in
            guard let baseAddress = rawBuffer.bindMemory(to: Int16.self).baseAddress else { return }
            channelData.update(from: baseAddress, count: previewAudio.frameCount)
        }
        return (buffer, format)
    }

    private func applyFilePlayback(
        filePath: String,
        title: String,
        preserveCurrentTime: TimeInterval,
        autoPlay: Bool,
        transitionFromLive: Bool,
        presentationContext: PlaybackPresentationContext,
        playbackTelemetrySessionID: String? = nil
    ) throws {
        let url = URL(fileURLWithPath: filePath)
        guard FileManager.default.fileExists(atPath: filePath) else {
            throw NSError(domain: "AudioPlayerViewModel", code: 404, userInfo: [
                NSLocalizedDescriptionKey: "Audio file not found."
            ])
        }

        let audioPlayer = try AVAudioPlayer(contentsOf: url)
        audioPlayer.delegate = self
        audioPlayer.prepareToPlay()

        if transitionFromLive {
            stopLivePlayback(resetCurrentTime: false)
            livePlayback.resetBookkeeping()
            livePlaybackStarted = false
            livePreviewDuration = 0
            livePlaybackTimeOffset = 0
            liveUnderrunCount = 0
            livePlayback.clearFormat()
            livePreviewEstimate = nil
            liveExpectedFrameOffset = nil
            livePreviewDisabledSessionID = nil
            cleanupLiveSessionDirectory()
            liveSessionID = nil
            liveSessionDirectory = nil
            liveFinalFilePath = nil
            liveAutoplayEnabled = false
        } else {
            teardownLivePlayback(clearSession: true)
        }

        stopFilePlayback(clearPlayer: true)

        player = audioPlayer
        playbackMode = .file
        currentFilePath = filePath
        currentTitle = title.isEmpty ? url.lastPathComponent : title
        duration = audioPlayer.duration
        let clampedTime = min(max(preserveCurrentTime, 0), audioPlayer.duration)
        audioPlayer.currentTime = clampedTime
        currentTime = clampedTime
        playbackError = nil
        isLiveStream = false
        setLivePreviewQueueDepth(0)
        setLivePreviewPhase(.idle)
        playbackPresentationContext = presentationContext
        generatePreviewVisibilityState = presentationContext == .generatePreview ? .ready : .hidden
        extractWaveform(from: url, replace: true)

        if autoPlay {
            attemptFilePlay(playbackTelemetrySessionID: playbackTelemetrySessionID)
        }
    }

    // MARK: - File Playback

    private func stopFilePlayback(clearPlayer: Bool) {
        player?.stop()
        if clearPlayer {
            player = nil
        }
        isPlaying = false
        stopTimer()
    }

    private func attemptFilePlay(playbackTelemetrySessionID: String? = nil) {
        guard var player else { return }

        if player.currentTime >= player.duration, player.duration > 0 {
            player.currentTime = 0
        }

        if player.play() {
            recordFinalFilePlaybackScheduled(
                sessionID: playbackTelemetrySessionID,
                player: player
            )
            playbackError = nil
            isPlaying = true
            currentTime = player.currentTime
            startTimer()
            consumeAutoplaySignpostIfNeeded()
            return
        }

        guard let path = currentFilePath else {
            playbackError = "Playback could not start."
            return
        }

        let url = URL(fileURLWithPath: path)
        guard let rebuilt = try? AVAudioPlayer(contentsOf: url) else {
            playbackError = "Playback could not start."
            return
        }
        rebuilt.delegate = self
        rebuilt.prepareToPlay()
        self.player = rebuilt
        player = rebuilt

        if player.play() {
            recordFinalFilePlaybackScheduled(
                sessionID: playbackTelemetrySessionID,
                player: player
            )
            playbackError = nil
            isPlaying = true
            currentTime = player.currentTime
            startTimer()
            consumeAutoplaySignpostIfNeeded()
        } else {
            playbackError = "Playback could not start."
        }
    }

    private func recordFinalFilePlaybackScheduled(
        sessionID: String?,
        player: AVAudioPlayer
    ) {
        guard let sessionID else { return }
        // The finalized WAV is the active playback buffer on this path, not
        // the live AVAudioPlayerNode queue that was just discarded. Model it
        // as one fully available file with its remaining audio.
        AppGenerationTimeline.shared.recordPlaybackScheduled(
            id: sessionID,
            source: .finalFile,
            queuedChunks: 1,
            queuedAudioSeconds: max(player.duration - player.currentTime, 0)
        )
    }

    private func clearPendingFirstChunkInterval() {
        guard let pendingFirstChunkInterval else { return }
        AppPerformanceSignposts.end(pendingFirstChunkInterval)
        self.pendingFirstChunkInterval = nil
    }

    private func consumeAutoplaySignpostIfNeeded() {
        guard pendingAutoplaySignpost else { return }
        pendingAutoplaySignpost = false
        AppPerformanceSignposts.emit("Autoplay Start")
    }

    private func clearLoadedAudio() {
        currentFilePath = nil
        currentTitle = ""
        duration = 0
        currentTime = 0
        waveformSamples = []
    }

    private func markGeneratePreviewReadyIfNeeded() {
        guard playbackPresentationContext == .generatePreview else { return }
        guard generatePreviewVisibilityState != .ready else { return }
        generatePreviewVisibilityState = .ready
    }

    private func resetPresentationState() {
        playbackPresentationContext = .none
        generatePreviewVisibilityState = .hidden
    }

    static func finalPlaybackHandoff(
        heardLivePreview: Bool,
        currentTime: TimeInterval,
        previewDuration: TimeInterval = 0,
        duration: TimeInterval,
        autoPlayEnabled: Bool
    ) -> FinalPlaybackHandoff {
        guard heardLivePreview else {
            return FinalPlaybackHandoff(
                preserveCurrentTime: 0,
                shouldAutoPlay: autoPlayEnabled
            )
        }

        guard autoPlayEnabled else {
            return FinalPlaybackHandoff(
                preserveCurrentTime: 0,
                shouldAutoPlay: false
            )
        }

        let safeDuration = max(duration, 0)
        let heardTime = max(currentTime, previewDuration)
        let safeCurrentTime = min(max(heardTime, 0), safeDuration)
        let replayThreshold: TimeInterval = 0.12
        guard safeDuration > replayThreshold,
              safeCurrentTime < safeDuration - replayThreshold else {
            return FinalPlaybackHandoff(
                preserveCurrentTime: 0,
                shouldAutoPlay: false
            )
        }

        return FinalPlaybackHandoff(
            preserveCurrentTime: safeCurrentTime,
            shouldAutoPlay: true
        )
    }

    // MARK: - Timer

    /// Generation performance gate (benchmarks/OPTIMIZATION.md §K): while the
    /// live-preview stream plays, the engine competes with window compositing
    /// for the shared GPU, and a 10 Hz playhead redraw over Liquid Glass
    /// measurably inflates the engine's GPU queueing delay on the 8 GB tier.
    /// 3 Hz keeps visible motion during generation; file playback keeps the
    /// smooth 10 Hz playhead.
    private var desiredTimerInterval: TimeInterval {
        playbackMode == .live ? (1.0 / 3.0) : 0.1
    }

    private var activeTimerInterval: TimeInterval = 0.1

    private func startTimer() {
        stopTimer()
        let interval = desiredTimerInterval
        activeTimerInterval = interval
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                if self.activeTimerInterval != self.desiredTimerInterval {
                    // Live→file handoff (or vice versa) without a playback
                    // restart: re-arm at the cadence the current mode wants.
                    self.startTimer()
                }
                self.updatePlaybackProgress()
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func updatePlaybackProgress() {
        switch playbackMode {
        case .file:
            guard let player else { return }
            currentTime = duration > 0 ? min(player.currentTime, duration) : player.currentTime
            if !player.isPlaying {
                isPlaying = false
                stopTimer()
            }
        case .live:
            guard livePlayback.isConfigured else { return }
            if let renderedTime = livePlayback.renderedNodeSeconds {
                let adjustedTime = renderedTime + livePlaybackTimeOffset
                currentTime = duration > 0 ? min(adjustedTime, duration) : adjustedTime
            }

            if !livePlayback.isNodePlaying, liveFinalFilePath != nil {
                isPlaying = false
                stopTimer()
                let handoff = Self.finalPlaybackHandoff(
                    heardLivePreview: livePlaybackStarted,
                    currentTime: currentTime,
                    previewDuration: livePreviewDuration,
                    duration: duration,
                    autoPlayEnabled: liveAutoplayEnabled
                )
                switchToFinalFilePlayback(
                    preserveCurrentTime: handoff.preserveCurrentTime,
                    autoPlay: handoff.shouldAutoPlay
                )
            }
        case .none:
            stopTimer()
        }
    }

    // MARK: - Waveform

    private func extractWaveform(from url: URL, replace: Bool) {
        Task.detached {
            let extracted = WaveformService.extractSamples(from: url, targetCount: replace ? 120 : 32)
            await MainActor.run { [weak self] in
                guard let self else { return }
                if replace || self.waveformSamples.isEmpty {
                    self.waveformSamples = extracted
                } else {
                    self.waveformSamples = Self.mergeWaveformSamples(
                        existing: self.waveformSamples,
                        incoming: extracted,
                        targetCount: 120
                    )
                }
            }
        }
    }

    private static func mergeWaveformSamples(existing: [Float], incoming: [Float], targetCount: Int) -> [Float] {
        let combined = existing + incoming
        guard combined.count > targetCount else { return combined }

        var reduced: [Float] = []
        reduced.reserveCapacity(targetCount)
        let step = Double(combined.count) / Double(targetCount)
        for index in 0..<targetCount {
            let lowerBound = Int(Double(index) * step)
            let upperBound = min(Int(Double(index + 1) * step), combined.count)
            let slice = combined[lowerBound..<max(lowerBound + 1, upperBound)]
            let average = slice.reduce(0, +) / Float(slice.count)
            reduced.append(average)
        }
        return reduced
    }

    // MARK: - Formatting

    static func formatTime(_ time: TimeInterval) -> String {
        let minutes = Int(time) / 60
        let seconds = Int(time) % 60
        return String(format: "%d:%02d", minutes, seconds)
    }

    // MARK: - AVAudioPlayerDelegate

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let snapshotTime = player.currentTime
        let playerID = ObjectIdentifier(player)
        Task { @MainActor [weak self] in
            guard let self, self.player.map(ObjectIdentifier.init) == playerID else { return }
            self.isPlaying = false
            self.currentTime = flag ? self.duration : snapshotTime
            self.stopTimer()
            if !flag {
                self.playbackError = "Playback stopped unexpectedly."
            }
        }
    }
}
