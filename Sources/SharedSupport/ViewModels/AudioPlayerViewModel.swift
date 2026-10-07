import AVFoundation
import Combine
import Foundation

import QwenVoiceCore

typealias PlaybackGenerationResult = QwenVoiceCore.GenerationResult

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
    @Published private(set) var playbackTargetFilePath: String?
    @Published private(set) var currentGenerationMode: GenerationMode?
    private var generationPlaybackOwnership = GenerationPlaybackOwnership()
    private var generationPlaybackMode: GenerationMode?

    func beginGenerationPlayback(operationID: UUID, mode: GenerationMode) {
        // S1: an earlier operation's waiting takes never take over the player.
        if generationPlaybackOwnership.operationID != operationID {
            discardQueuedLiveSessions()
        }
        generationPlaybackOwnership.begin(operationID)
        generationPlaybackMode = mode
    }

    func ownsGenerationPlayback(_ operationID: UUID) -> Bool {
        generationPlaybackOwnership.owns(operationID)
    }

    @discardableResult
    func claimGenerationStream(_ generationID: UUID, operationID: UUID) -> Bool {
        generationPlaybackOwnership.claimStream(generationID, operationID: operationID)
    }

    func playbackError(forFile path: String) -> String? {
        playbackTargetFilePath == path ? playbackError : nil
    }

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

    typealias FinalPlaybackHandoff = LivePreviewFinalHandoff

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

    /// Whether the live preview has enough buffered audio to begin (or
    /// resume) on its own; the decision lives in `LivePreviewStartPolicy`.
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
        switch LivePreviewStartPolicy.decide(
            autoplayEnabled: autoplayEnabled,
            queuedChunks: queuedChunks,
            queuedDuration: queuedDuration,
            prebufferThreshold: prebufferThreshold,
            minimumBufferedDuration: minimumBufferedDuration,
            finalFileAvailable: finalFileAvailable,
            underrunCount: underrunCount,
            estimate: estimate
        ) {
        case .start:
            return true
        case .rejectAutoplay:
            AppPerformanceSignposts.emit("Should Start Reject Autoplay")
            return false
        case .rejectBuffer:
            AppPerformanceSignposts.emit("Should Start Reject Buffer")
            return false
        }
    }

    /// U07: what the player keeps for a take of the same operation that waits
    /// for the take before it (`LivePreviewTakeQueue` keeps them in order).
    private enum QueuedChunk {
        case pcm(StreamingAudioChunk, cumulativeDuration: TimeInterval?)
        case file(URL, cumulativeDuration: TimeInterval?)
    }

    private struct QueuedCompletion {
        let result: PlaybackGenerationResult
        let title: String
        let shouldAutoPlay: Bool
        let playbackOperationID: UUID?
    }

    private struct QueuedTakeDetails {
        let title: String
        let autoplayPreference: Bool
        /// S1: the mode the take was generated in, not the mode of whatever
        /// operation owns playback when it starts.
        let generationMode: GenerationMode?
    }

    private typealias TakeQueue = LivePreviewTakeQueue<QueuedChunk, QueuedCompletion, QueuedTakeDetails>

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
    /// Auto-play, user and system holds and explicit Play for the current
    /// session and its generation operation (U04, U06).
    private var liveAutoplay = LivePreviewAutoplayState()
    private var liveAutoplayEnabled: Bool { liveAutoplay.allowsAutomaticPlayback }
    /// Takes of the current operation waiting for the take that plays (U07).
    private var takeQueue = TakeQueue()
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
    #if os(macOS)
    private var recordingObserver: NSObjectProtocol?
    #endif
    private var timer: Timer?
    #if os(iOS)
    private var interruptionObserver: NSObjectProtocol?
    private var routeChangeObserver: NSObjectProtocol?
    private var shouldResumeAfterInterruption = false
    /// Held from the first playback until the app leaves the foreground (PA-21),
    /// so a closing preview never deactivates the session under this player.
    private var sessionClaim: IOSAudioSessionClaim?
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
        #if os(macOS)
        livePlayback.onConfigurationChange = { [weak self] in
            self?.handleLiveOutputConfigurationChange()
        }
        registerRecordingObserver()
        #endif
        #if os(iOS)
        registerAudioSessionObservers()
        IOSPlaybackExclusivity.register(self) { [weak self] in
            self?.pauseForOtherPlayback()
        }
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
            #if os(macOS)
            if let recordingObserver {
                NotificationCenter.default.removeObserver(recordingObserver)
            }
            #endif
            teardownLivePlayback(clearSession: true)
            stopFilePlayback(clearPlayer: true)
        }
    }

    #if os(macOS)
    /// MAC-14: a reference recording is about to start, so whatever this player
    /// is playing would be captured into the clip. Pause it; like another
    /// player starting on iOS, a live preview (paused, or still buffering) does
    /// not start on its next chunk, and Play resumes it.
    private func registerRecordingObserver() {
        recordingObserver = NotificationCenter.default.addObserver(
            forName: ReferenceClipRecorder.willStartRecordingNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.pauseForRecording() }
        }
    }

    private func pauseForRecording() {
        holdAutomaticPlayback()
        if isPlaying {
            pause()
        }
    }

    /// MAC-18: an output-device change stops the live-preview engine and can
    /// drop what it had queued, so the preview cannot resume in place without
    /// skipping or repeating audio. The heard position is kept, the rest of
    /// the preview is not scheduled, and the take continues from the published
    /// file at that position: at once when it exists, otherwise when the take
    /// completes (the handoff `completeStreamingPreview` already makes).
    /// Only an audible preview is handed over: a paused or buffering one
    /// restarts its engine on the next Play or chunk. File playback
    /// (`AVAudioPlayer`) follows the new device by itself.
    private func handleLiveOutputConfigurationChange() {
        guard playbackMode == .live, isPlaying else { return }
        AppPerformanceSignposts.emit("Live Preview Output Changed")
        retireLiveGraphKeepingHeardPosition()
    }
    #endif

    /// Drops the live graph and whatever it had queued but keeps the session
    /// and the heard position, so the take continues from its final file at
    /// that position: at once when the file exists, otherwise when the take
    /// completes. A take waiting behind this one starts instead when this
    /// one's stream has already ended (U07).
    private func retireLiveGraphKeepingHeardPosition() {
        guard playbackMode == .live, let liveSessionID,
              livePreviewDisabledSessionID != liveSessionID else { return }
        let heardTime = currentTime
        livePreviewDisabledSessionID = liveSessionID
        stopLivePlayback(resetCurrentTime: false)
        livePlayback.resetBookkeeping()
        livePlayback.discardGraph()
        livePreviewDuration = heardTime
        currentTime = heardTime
        setLivePreviewQueueDepth(0)
        guard liveFinalFilePath != nil else {
            if promoteQueuedLiveSession() { return }
            setLivePreviewPhase(.buffering)
            return
        }
        recordCompletedLiveSessionID(liveSessionID)
        let handoff = Self.finalPlaybackHandoff(
            heardLivePreview: livePlaybackStarted,
            currentTime: heardTime,
            previewDuration: heardTime,
            duration: duration,
            autoPlayEnabled: liveAutoplayEnabled
        )
        handOffToFinalFile(handoff)
    }

    /// U04/U06: a user or system pause, another player or a recording. A live
    /// session, playing or still buffering, waits for an explicit Play; a take
    /// submitted without a session yet starts held.
    private func holdAutomaticPlayback() {
        if playbackMode == .live || isPlaying {
            liveAutoplay.hold()
        }
        holdSubmittedTake()
    }

    /// S4: a take submitted while this one plays (it has no session yet, and
    /// a lone take's hold ends with its session) starts held too.
    private func holdSubmittedTake() {
        if pendingLivePreviewEstimate != nil {
            liveAutoplay.holdUpcomingSession()
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
            // is transient and should not auto-resume mid-generation: playing
            // or still buffering, it waits for Play (U04).
            shouldResumeAfterInterruption = isPlaying && playbackMode == .file
            if playbackMode == .live { liveAutoplay.hold() }
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

    /// Claims playback through the one session owner (PA-21) without blocking
    /// the first chunk, and pauses every other player.
    private func claimSharedPlaybackSession() {
        sessionClaim = IOSAudioSessionOwner.shared.activateAsync(.sharedPlayback, renewing: sessionClaim)
        IOSPlaybackExclusivity.didStartPlayback(self)
    }

    /// Another player (a preview, the player sheet, clip review or the recorder)
    /// started. A paused live preview must not resume on its next chunk, so
    /// autoplay ends for this take, audible, buffering, underrun or not yet
    /// started alike (U06); Play resumes it.
    private func pauseForOtherPlayback() {
        holdAutomaticPlayback()
        guard isPlaying else { return }
        shouldResumeAfterInterruption = false
        pause()
    }

    /// The output the preview was playing on went away (headphones unplugged):
    /// a live preview, playing or still buffering, waits for Play rather than
    /// starting on the speaker with its next chunk (U04).
    private func handleAudioRouteChange(reasonRaw: UInt?) {
        guard let reasonRaw,
              AVAudioSession.RouteChangeReason(rawValue: reasonRaw) == .oldDeviceUnavailable else { return }
        if playbackMode == .live { liveAutoplay.hold() }
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
        presentationContext: PlaybackPresentationContext = .library,
        generationMode: GenerationMode? = nil,
        playbackOperationID: UUID? = nil
    ) {
        if let playbackOperationID {
            guard ownsGenerationPlayback(playbackOperationID) else { return }
        } else {
            generationPlaybackOwnership.revoke()
        }
        playbackTargetFilePath = filePath
        currentGenerationMode = generationMode
        pendingAutoplaySignpost = false
        discardQueuedLiveSessions()
        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)
        // Other audio: no hold or explicit Play carries over, except that a
        // file the operation itself hands over stays the operation's.
        liveAutoplay.reset(operationID: playbackOperationID)

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
            currentTitle = title.isEmpty ? URL(fileURLWithPath: filePath).lastPathComponent : title
            playbackError = error.localizedDescription
        }
    }

    func play() {
        // The only way out of a user or system hold (U04): later underruns,
        // the final-file handoff and the operation's next takes play again.
        liveAutoplay.play()
        switch playbackMode {
        case .live:
            if liveFinalFilePath != nil {
                // An explicit Play must resume the heard position, even when
                // the entire finalized preview is still queued. The automatic
                // drain policy intentionally avoids replay, so cannot own this
                // user action (or gate it on the Auto-play preference).
                let decision = AudioPlaybackResumePolicy.explicitPlay(
                    currentTime: currentTime, duration: duration
                )
                switchToFinalFilePlayback(
                    preserveCurrentTime: decision.position,
                    autoPlay: decision.shouldPlay
                )
            } else {
                attemptLivePlay()
            }
        case .file:
            attemptFilePlay()
        case .none:
            break
        }
    }

    /// A user or system pause holds the take (U04): no streamed chunk, underrun
    /// recovery or final-file handoff restarts it, only `play()`. An underrun
    /// pauses the node directly and keeps automatic resume.
    func pause() {
        switch playbackMode {
        case .live:
            liveAutoplay.hold()
            holdSubmittedTake()
            livePlayback.pauseNode()
            isPlaying = false
            stopTimer()
        case .file:
            // The operation's next take waits for Play too.
            liveAutoplay.hold()
            holdSubmittedTake()
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
        generationPlaybackOwnership.revoke()
        clearPlayback()
    }

    private func clearPlayback() {
        playbackTargetFilePath = nil
        currentGenerationMode = nil
        pendingAutoplaySignpost = false
        discardQueuedLiveSessions()
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
        presentationContext: PlaybackPresentationContext = .library,
        generationMode: GenerationMode? = nil,
        playbackOperationID: UUID? = nil
    ) {
        if let playbackOperationID, !ownsGenerationPlayback(playbackOperationID) { return }
        load(filePath: path, title: title, presentationContext: presentationContext,
             generationMode: generationMode, playbackOperationID: playbackOperationID)
        if isAutoplay {
            pendingAutoplaySignpost = true
        }
        guard player != nil else { return }
        // N7: an automatic play is not the listener's Play.
        if isAutoplay {
            attemptFilePlay()
        } else {
            play()
        }
    }

    /// Sets a prompt-derived forecast so `shouldStartLivePlayback` can
    /// size the live-preview buffer before the first chunk arrives.
    /// Pass nil to fall back to adaptive chunk-count buffering for future
    /// sessions; an active live session keeps the estimate it already
    /// captured.
    func setLivePreviewEstimate(_ estimate: LivePreviewEstimate?) {
        pendingLivePreviewEstimate = estimate
        // A newly submitted take: an earlier take's upcoming hold is spent.
        if estimate != nil {
            liveAutoplay.clearUpcomingHold()
        }
    }

    func prepareStreamingPreview(
        title: String, shouldAutoPlay: Bool,
        generationID: UUID? = nil, playbackOperationID: UUID? = nil
    ) {
        let streamSessionID = generationID?.uuidString
        #if os(macOS)
        guard let generationID, let playbackOperationID,
              claimGenerationStream(generationID, operationID: playbackOperationID) else { return }
        currentGenerationMode = generationPlaybackMode
        #endif
        // U07: the operation's previous take plays to its end; this one waits.
        if queueBehindCurrentTake(
            sessionID: streamSessionID,
            operationID: playbackOperationID,
            title: title,
            sessionDirectory: nil,
            autoplayPreference: shouldAutoPlay
        ) {
            return
        }
        playbackTargetFilePath = nil
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
        liveAutoplay.beginSession(operationID: playbackOperationID, autoplayPreference: shouldAutoPlay)
        pendingAutoplaySignpost = liveAutoplayEnabled
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

    func completeStreamingPreview(
        result: PlaybackGenerationResult, title: String, shouldAutoPlay: Bool,
        playbackOperationID: UUID? = nil
    ) {
        #if os(macOS)
        guard let playbackOperationID, ownsGenerationPlayback(playbackOperationID) else { return }
        #endif
        // U07: a take still waiting for the take before it keeps its result
        // for its turn (`LivePreviewTakeQueue.attach`).
        if result.usedStreaming,
           takeQueue.attach(
               QueuedCompletion(
                   result: result,
                   title: title,
                   shouldAutoPlay: shouldAutoPlay,
                   playbackOperationID: playbackOperationID
               ),
               details: QueuedTakeDetails(
                   title: title,
                   autoplayPreference: shouldAutoPlay,
                   generationMode: generationPlaybackMode
               )
           ) {
            return
        }
        applyCompletedResult(
            result,
            title: title,
            shouldAutoPlay: shouldAutoPlay,
            playbackOperationID: playbackOperationID,
            generationMode: generationPlaybackMode
        )
    }

    private func applyCompletedResult(
        _ result: PlaybackGenerationResult, title: String, shouldAutoPlay: Bool,
        playbackOperationID: UUID?, generationMode: GenerationMode?
    ) {
        #if os(macOS)
        let authorizedPlaybackOperationID: UUID? = playbackOperationID
        currentGenerationMode = generationMode
        #else
        // iOS retains its existing playback handoff; operation ownership is Mac-only.
        let authorizedPlaybackOperationID: UUID? = nil
        #endif
        // U06: with no live session left, a hold of the operation or of the
        // submitted take (another player, a recording) still wins over the
        // caller's Auto-play preference. The upcoming hold is spent here.
        let finalAutoplay = liveAutoplay.allowsAutomaticFinalPlayback(
            operationID: playbackOperationID,
            autoplayPreference: shouldAutoPlay
        )
        liveAutoplay.clearUpcomingHold()
        playbackTargetFilePath = result.audioPath
        guard result.usedStreaming else {
            if finalAutoplay {
                playFile(
                    result.audioPath,
                    title: title,
                    isAutoplay: true,
                    presentationContext: .generatePreview,
                    generationMode: generationMode,
                    playbackOperationID: authorizedPlaybackOperationID
                )
            }
            return
        }

        currentTitle = title
        currentFilePath = result.audioPath
        liveFinalFilePath = result.audioPath
        // Audit Finding #2 — DO NOT add `liveSessionID` to
        // `completedLiveSessionIDs` here. Two independent paths race
        // on MainActor: the awaited generation result (this function's
        // caller) and the chunk notifications posted by the store's
        // forwarding task. If the result-channel continuation runs
        // first and we record the session ID immediately, any chunk
        // still queued behind it is
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
        switch LivePreviewCompletionPolicy.decide(
            previewStarted: livePlaybackStarted,
            queuedBuffers: livePlayback.scheduledCount,
            isPlaying: isPlaying,
            allowsAutomaticPlayback: liveAutoplayEnabled,
            previewDisabled: livePreviewDisabledSessionID == liveSessionID
        ) {
        case .handOffNow:
            // Immediate-handoff branch: live preview is over (never
            // started or already drained). Any chunk arriving from
            // the broker now is genuinely stale. Record the session
            // as completed so the `handleGenerationChunk` guard
            // drops it.
            recordCompletedLiveSessionID(liveSessionID)
            // U06 (P10-02): the session's own state decides, so a hold
            // (Pause, another player, a recording) is not undone by the
            // caller's Auto-play preference.
            let handoff = Self.finalPlaybackHandoff(
                heardLivePreview: livePlaybackStarted,
                currentTime: currentTime,
                previewDuration: livePreviewDuration,
                duration: duration,
                autoPlayEnabled: playbackMode == .live && liveSessionID != nil
                    ? liveAutoplayEnabled
                    : finalAutoplay
            )
            handOffToFinalFile(handoff)
        case .playOutQueuedTail:
            // U05: after an underrun the stream has ended, so a tail shorter
            // than the prebuffer will never fill it. Play it out now; the
            // drain hands off to the file.
            startLiveNode()
        case .awaitDrain:
            // Live preview still draining (or held). Late chunks that
            // arrive between now and the drain are appended naturally
            // by `appendLiveChunk` (the session ID is NOT in
            // `completedLiveSessionIDs` yet, so the guard lets them
            // through). When the queue drains and
            // `finishLivePlaybackAfterDrainingBuffers` fires, the
            // session ID is recorded there.
            break
        }
    }

    func abortLivePreviewIfNeeded() {
        pendingLivePreviewEstimate = nil
        liveAutoplay.clearUpcomingHold()
        // N8: the live session and the waiting takes go; a final file that
        // already plays (an earlier line's) keeps playing.
        discardQueuedLiveSessions()
        guard playbackMode == .live || liveSessionID != nil else { return }
        dismiss()
    }

    #if os(iOS)
    /// P03-02: critical memory drops the live preview's graph, what it had
    /// queued and any take waiting behind it, but keeps the session and the
    /// heard position. A take that still completes then continues from its
    /// final file there instead of replaying from the start; a cancelled or
    /// failed take clears the player through `abortLivePreviewIfNeeded`.
    func relieveLivePreviewForMemoryPressure() {
        discardQueuedLiveSessions()
        retireLiveGraphKeepingHeardPosition()
    }
    #endif

    /// Internal long-form cleanup preserves the operation's final-file handoff.
    /// A user dismissal or another audio selection still wins over this cleanup.
    func finishGenerationPreview(playbackOperationID: UUID) {
        #if os(macOS)
        guard ownsGenerationPlayback(playbackOperationID) else { return }
        generationPlaybackOwnership.finishStream(operationID: playbackOperationID)
        #endif
        pendingLivePreviewEstimate = nil
        guard !takeQueue.isEmpty || playbackMode == .live || liveSessionID != nil else { return }
        clearPlayback()
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
    }

    private func handleGenerationChunk(_ chunk: ChunkInfo) {
        #if os(macOS)
        guard generationPlaybackOwnership.acceptsChunk(chunk.generationID) else { return }
        #endif
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

        // U07: a take waiting for the take that plays keeps its chunks.
        if routeToQueuedTake(chunk, sessionID: sessionID) { return }

        if liveSessionID != sessionID {
            let operationID = chunkOperationID
            if queueBehindCurrentTake(
                sessionID: sessionID,
                operationID: operationID,
                title: chunk.title,
                sessionDirectory: sessionDirectory,
                autoplayPreference: AudioService.shouldAutoPlay,
                firstChunk: chunk
            ) {
                return
            }
            startLiveSession(
                id: sessionID,
                title: chunk.title,
                sessionDirectory: sessionDirectory,
                autoPlay: AudioService.shouldAutoPlay,
                operationID: operationID
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

    /// Starts a live session. A take promoted from the queue (U07) brings the
    /// estimate it captured when it was queued and leaves the pending estimate
    /// to the take that was submitted after it.
    private func startLiveSession(
        id: String,
        title: String,
        sessionDirectory: String?,
        autoPlay: Bool,
        operationID: UUID?,
        queuedEstimate: LivePreviewEstimate? = nil,
        queuedGenerationMode: GenerationMode? = nil,
        isQueuedTake: Bool = false
    ) {
        playbackTargetFilePath = nil
        currentGenerationMode = isQueuedTake ? queuedGenerationMode : generationPlaybackMode
        let sessionEstimate = isQueuedTake
            ? (queuedEstimate ?? LivePreviewEstimate(text: title))
            : (pendingLivePreviewEstimate ?? livePreviewEstimate ?? LivePreviewEstimate(text: title))

        AppPerformanceSignposts.emit("Live Session Start")
        // Teardown clears the pending estimate, which belongs to a later take
        // when this one comes from the queue.
        let laterTakeEstimate = isQueuedTake ? pendingLivePreviewEstimate : nil
        teardownLivePlayback(clearSession: true)
        stopFilePlayback(clearPlayer: true)
        pendingLivePreviewEstimate = laterTakeEstimate

        playbackMode = .live
        liveSessionID = id
        liveSessionDirectory = sessionDirectory
        liveFinalFilePath = nil
        liveAutoplay.beginSession(operationID: operationID, autoplayPreference: autoPlay)
        // When `startLiveSession` fires from `handleGenerationChunk` (the
        // auto-init path used by every streaming generation today), nothing
        // upstream sets `pendingAutoplaySignpost`. Without it, the
        // "Autoplay Start" signpost never fires when live playback begins
        // — even though playback is actually happening. The bench harness
        // (and any forensic latency analysis) can't see the perceived-speed
        // gain. Set it here so the signpost mirrors the live engine's
        // play() call when autoplay is enabled for this session.
        pendingAutoplaySignpost = liveAutoplayEnabled
        livePlayback.resetBookkeeping()
        livePlayback.clearFormat()
        livePlaybackStarted = false
        livePreviewDuration = 0
        livePlaybackTimeOffset = 0
        liveUnderrunCount = 0
        // Smooth-first prebuffer estimate handoff: pending values
        // captured pre-generation become the active session's
        // estimate, then are cleared (above, by the teardown) so a future
        // session that arrives without a fresh estimate falls back to
        // adaptive scaling.
        livePreviewEstimate = sessionEstimate
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

    // MARK: - Take succession (U07)

    /// The generation operation a newly streaming take belongs to. On the Mac
    /// every accepted chunk belongs to the operation that owns playback; on
    /// iOS only a prepared session (a long-form segment) names one.
    private var chunkOperationID: UUID? {
        #if os(macOS)
        return generationPlaybackOwnership.operationID
        #else
        guard let liveSessionID, liveSessionID.hasPrefix("pending-") else { return nil }
        return liveAutoplay.operationID
        #endif
    }

    /// What the current take would still play.
    private var previousTakeState: LivePreviewSuccessionPolicy.PreviousTake {
        if isPlaying { return .playing }
        if liveAutoplay.isHeld { return hasAudioToResume ? .held : .silent }
        if playbackMode == .live, liveAutoplayEnabled, livePlayback.scheduledCount > 0,
           livePreviewDisabledSessionID != liveSessionID {
            return .unplayedTail
        }
        return .silent
    }

    /// What Play would resume for a held take: queued live audio, its final
    /// file, or the rest of a loaded file.
    private var hasAudioToResume: Bool {
        switch playbackMode {
        case .live:
            return (livePreviewDisabledSessionID != liveSessionID && livePlayback.scheduledCount > 0)
                || liveFinalFilePath != nil
        case .file:
            return player != nil && currentTime < duration
        case .none:
            return false
        }
    }

    /// Audio the current take still has to play: its live queue or the rest
    /// of its file. The waiting takes add `takeQueue.backlogSeconds`.
    private var currentTakeBacklogSeconds: TimeInterval {
        switch playbackMode {
        case .live: return livePlayback.queuedAudioSeconds
        case .file: return max(0, duration - currentTime)
        case .none: return 0
        }
    }

    /// Decides whether a new take of the operation waits for the take before
    /// it, and queues it when it does (returning true, so the caller stops).
    /// Otherwise the waiting takes are dropped and the caller starts the new
    /// take at once, as before.
    private func queueBehindCurrentTake(
        sessionID: String?,
        operationID: UUID?,
        title: String,
        sessionDirectory: String?,
        autoplayPreference: Bool,
        firstChunk: ChunkInfo? = nil
    ) -> Bool {
        switch LivePreviewSuccessionPolicy.decide(
            incomingOperationID: operationID,
            previousOperationID: liveAutoplay.operationID,
            previous: previousTakeState
        ) {
        case .startNow:
            discardQueuedLiveSessions()
            return false
        case .releaseTailThenQueue:
            // A successor means the current stream has ended: play the tail
            // its prebuffer or an underrun was holding back.
            startLiveNode()
            guard isPlaying else {
                discardQueuedLiveSessions()
                return false
            }
        case .queue:
            break
        }
        takeQueue.admit(
            sessionID: sessionID,
            operationID: operationID,
            details: QueuedTakeDetails(
                title: title,
                autoplayPreference: autoplayPreference,
                generationMode: generationPlaybackMode
            ),
            sessionDirectory: sessionDirectory,
            pendingEstimate: &pendingLivePreviewEstimate,
            fallbackEstimate: LivePreviewEstimate(text: title),
            currentBacklogSeconds: currentTakeBacklogSeconds
        )
        AppPerformanceSignposts.emit("Live Session Queued")
        if let firstChunk, let sessionID {
            _ = routeToQueuedTake(firstChunk, sessionID: sessionID)
        }
        return true
    }

    /// Routes a chunk to its waiting take (`LivePreviewTakeQueue.route`);
    /// false when no waiting take owns it.
    private func routeToQueuedTake(_ chunk: ChunkInfo, sessionID: String) -> Bool {
        guard !takeQueue.isEmpty else { return false }
        let entry = Self.queuedChunk(from: chunk)
        switch takeQueue.route(
            entry?.chunk,
            sessionID: sessionID,
            isCurrentSession: liveSessionID == sessionID,
            sessionDirectory: chunk.sessionDirectory,
            chunkSeconds: entry?.seconds ?? 0,
            cumulativeDuration: chunk.cumulativeDuration,
            currentBacklogSeconds: currentTakeBacklogSeconds
        ) {
        case .notQueued:
            return false
        case .stored(let firstAudio):
            if firstAudio {
                // N5: the take is playable from its first queued audio; its
                // wait for the take before it is not frontend latency.
                AppGenerationTimeline.shared.recordPlaybackScheduled(
                    id: sessionID,
                    source: .liveStream,
                    queuedChunks: 1,
                    queuedAudioSeconds: entry?.seconds ?? 0
                )
            }
            return true
        case .dropped:
            if case .file(let url, cumulativeDuration: _)? = entry?.chunk {
                try? FileManager.default.removeItem(at: url)
            }
            AppPerformanceSignposts.emit("Queued Chunk Past Bound")
            return true
        }
    }

    private static func queuedChunk(
        from chunk: ChunkInfo
    ) -> (chunk: QueuedChunk, seconds: TimeInterval)? {
        if let previewAudio = chunk.previewAudio {
            let seconds = previewAudio.sampleRate > 0
                ? Double(previewAudio.frameCount) / Double(previewAudio.sampleRate)
                : 0
            let queued = QueuedChunk.pcm(previewAudio, cumulativeDuration: chunk.cumulativeDuration)
            return (chunk: queued, seconds: seconds)
        }
        if let chunkPath = chunk.chunkPath {
            let queued = QueuedChunk.file(
                URL(fileURLWithPath: chunkPath),
                cumulativeDuration: chunk.cumulativeDuration
            )
            return (chunk: queued, seconds: 0)
        }
        return nil
    }

    /// S1: on the Mac a waiting take starts, or applies its result, only
    /// while its operation still owns playback. iOS has no ownership.
    private func takeStillOwnsPlayback(_ operationID: UUID?) -> Bool {
        #if os(macOS)
        guard let operationID else { return false }
        return ownsGenerationPlayback(operationID)
        #else
        return true
        #endif
    }

    /// The take that played has ended: start the oldest waiting take. Its
    /// buffered chunks schedule at once, so it plays as soon as they fill its
    /// prebuffer, its result arrives or its stream is known to have ended,
    /// and drains into its final file.
    @discardableResult
    private func promoteQueuedLiveSession() -> Bool {
        dropQueuedTakes { !self.takeStillOwnsPlayback($0.operationID) }
        guard let next = takeQueue.popFirst() else { return false }
        AppPerformanceSignposts.emit("Queued Live Session Started")
        startLiveSession(
            id: next.sessionID ?? "pending-\(UUID().uuidString)",
            title: next.details.title,
            sessionDirectory: next.sessionDirectory,
            autoPlay: next.details.autoplayPreference,
            operationID: next.operationID,
            queuedEstimate: next.estimate,
            queuedGenerationMode: next.details.generationMode,
            isQueuedTake: true
        )
        for chunk in next.chunks {
            guard livePreviewDisabledSessionID != liveSessionID else {
                if case .file(let url, cumulativeDuration: _) = chunk {
                    try? FileManager.default.removeItem(at: url)
                }
                continue
            }
            switch chunk {
            case .pcm(let previewAudio, cumulativeDuration: let cumulativeDuration):
                appendLiveChunk(previewAudio, cumulativeDuration: cumulativeDuration)
            case .file(let url, cumulativeDuration: let cumulativeDuration):
                appendLiveChunk(from: url, cumulativeDuration: cumulativeDuration)
            }
        }
        if let completion = next.completion {
            applyCompletedResult(
                completion.result,
                title: completion.title,
                shouldAutoPlay: completion.shouldAutoPlay,
                playbackOperationID: completion.playbackOperationID,
                generationMode: next.details.generationMode
            )
            return true
        }
        // S2: a long-form segment has no result of its own; a take waiting
        // behind it means its stream has ended, so a short one plays now.
        switch LivePreviewPromotionPolicy.decide(
            streamEnded: !takeQueue.isEmpty,
            queuedBuffers: livePreviewDisabledSessionID == liveSessionID ? 0 : livePlayback.scheduledCount,
            isPlaying: isPlaying,
            allowsAutomaticPlayback: liveAutoplayEnabled
        ) {
        case .play:
            startLiveNode()
        case .skipToNext:
            promoteQueuedLiveSession()
        case .wait:
            break
        }
        return true
    }

    /// Drops every waiting take; their late chunks are dropped too.
    private func discardQueuedLiveSessions() {
        dropQueuedTakes { _ in true }
    }

    private func dropQueuedTakes(where shouldDrop: (TakeQueue.Take) -> Bool) {
        guard !takeQueue.isEmpty else { return }
        for take in takeQueue.removeAll(where: shouldDrop) {
            recordCompletedLiveSessionID(take.sessionID)
            for chunk in take.chunks {
                if case .file(let url, cumulativeDuration: _) = chunk {
                    try? FileManager.default.removeItem(at: url)
                }
            }
            if let sessionDirectory = take.sessionDirectory {
                try? FileManager.default.removeItem(at: URL(fileURLWithPath: sessionDirectory, isDirectory: true))
            }
        }
    }

    /// Hands a live take over to its final file. When the file would not play
    /// on (the take was heard to its end, or may not play on its own), the
    /// operation's next waiting take starts instead; a file that plays on
    /// hands over to that take when it ends. A held take loads its file where
    /// it stopped and waits for Play; the waiting takes follow its end (S5).
    private func handOffToFinalFile(_ handoff: FinalPlaybackHandoff) {
        let keepsTake = handoff.shouldAutoPlay || takeQueue.isEmpty || liveAutoplay.isHeld
        if keepsTake {
            switchToFinalFilePlayback(
                preserveCurrentTime: handoff.preserveCurrentTime,
                autoPlay: handoff.shouldAutoPlay
            )
            if isPlaying || takeQueue.isEmpty || liveAutoplay.isHeld { return }
        }
        promoteQueuedLiveSession()
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
            handOffToFinalFile(handoff)
            return
        }
        startLiveNode()
    }

    /// Plays the live node from what it has queued, whatever the prebuffer
    /// says: an explicit Play, a filled prebuffer, or a stream that ended.
    private func startLiveNode() {
        guard livePlayback.isConfigured else { return }

        #if os(iOS)
        if !isPlaying {
            claimSharedPlaybackSession()
        }
        #endif
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
            // U07: a waiting take means this stream has ended, so this is the
            // take's end, not an underrun; the next take starts.
            if promoteQueuedLiveSession() { return }
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
            handOffToFinalFile(handoff)
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
            liveAutoplay.endSession()
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
            liveAutoplay.endSession()
        } else {
            teardownLivePlayback(clearSession: true)
        }

        stopFilePlayback(clearPlayer: true)

        player = audioPlayer
        playbackMode = .file
        currentFilePath = filePath
        playbackTargetFilePath = filePath
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
        extractWaveform(from: url, loadedPath: filePath)

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
        #if os(iOS)
        claimSharedPlaybackSession()
        #endif

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
        LivePreviewFinalHandoff.resolve(
            heardLivePreview: heardLivePreview,
            currentTime: currentTime,
            previewDuration: previewDuration,
            duration: duration,
            autoPlayEnabled: autoPlayEnabled
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
                handOffToFinalFile(handoff)
            }
        case .none:
            stopTimer()
        }
    }

    // MARK: - Waveform

    /// Reads the loaded file's waveform off the main actor. MAC-17: the bars
    /// land only while that file is still the loaded one, so a slow read of a
    /// take the user already left never replaces the current take's waveform.
    private func extractWaveform(from url: URL, loadedPath: String) {
        Task.detached {
            let extracted = WaveformService.extractSamples(from: url, targetCount: 120)
            await MainActor.run { [weak self] in
                guard let self, self.currentFilePath == loadedPath else { return }
                self.waveformSamples = extracted
            }
        }
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
            // U07: the operation's next take was waiting for this file.
            self.promoteQueuedLiveSession()
        }
    }
}

/// The long-form runner and its coordinator drive the shared player through
/// this narrow protocol (PA-19), so `VocelloCoreTests` can run them without it.
extension AudioPlayerViewModel: IOSLongFormAudioPlayback {}
