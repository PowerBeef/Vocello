import AVFoundation
import Foundation

/// The live-preview audio graph (W2-D, 2026-08 UI review): AVAudioEngine +
/// player-node lifecycle and the FIFO scheduled-buffer bookkeeping,
/// extracted from the ~1,700-line `AudioPlayerViewModel`. The engine owns
/// mechanics only — session identity, staleness guards, published UI state,
/// timers, and telemetry stay with the owning view model, which calls back
/// through the completion hook it passes to `enqueue`.
@MainActor
final class LiveStreamingPlaybackEngine {
    private var engine: AVAudioEngine?
    private var playerNode: AVAudioPlayerNode?
    private(set) var format: AVAudioFormat?

    /// Number of scheduled-but-not-yet-played buffers.
    private(set) var scheduledCount = 0
    /// Real audio-second queue depth used by `shouldStartLivePlayback`.
    /// Bumped on every `enqueue` and decremented in `drainCompletedBuffer`
    /// (FIFO via `bufferDurations`). Distinct from the view model's
    /// `livePreviewDuration`, which is monotonically-cumulative total
    /// received audio used for UI / `final_handoff` audio-length reporting.
    /// Audit Finding #3 (May 2026): the prior code path reused
    /// `livePreviewDuration` for queue health, which after an underrun read
    /// multi-second-stale, and the `shouldStartLivePlayback` predicate
    /// would resume playback with a buffer claim of 6+ s while the
    /// AVAudioEngine queue actually held one fresh chunk (~0.6 s).
    /// Repeated resume/cutoff cycles followed.
    private(set) var queuedAudioSeconds: TimeInterval = 0
    private var bufferDurations: [TimeInterval] = []

    var isConfigured: Bool {
        engine != nil && playerNode != nil
    }

    var isNodePlaying: Bool {
        playerNode?.isPlaying ?? false
    }

    var isEngineRunning: Bool {
        engine?.isRunning ?? false
    }

    /// Seconds of audio the node has rendered in its current play session
    /// (nil until the node has a render time).
    var renderedNodeSeconds: TimeInterval? {
        guard let playerNode,
              let lastRenderTime = playerNode.lastRenderTime,
              let playerTime = playerNode.playerTime(forNodeTime: lastRenderTime),
              playerTime.sampleRate > 0 else { return nil }
        return Double(playerTime.sampleTime) / playerTime.sampleRate
    }

    /// Idempotent: if a prior pre-warm or chunk-arrival call already
    /// configured the engine with this exact format, skip the expensive
    /// allocation + attach + connect path. This is what makes the
    /// `prepareStreamingPreview` pre-warm a free win at the first chunk's
    /// arrival site.
    func configure(with format: AVAudioFormat) {
        if let existingEngine = engine,
           let existingNode = playerNode,
           let existingFormat = self.format,
           existingFormat == format {
            // Belt-and-suspenders: the engine could have been torn down
            // between pre-warm and chunk arrival (e.g. a panic path called
            // `engine.stop()`); confirm it's still running a valid graph
            // before reusing.
            if existingEngine.attachedNodes.contains(existingNode) {
                return
            }
        }

        let engine = AVAudioEngine()
        let playerNode = AVAudioPlayerNode()
        engine.attach(playerNode)
        engine.connect(playerNode, to: engine.mainMixerNode, format: format)
        self.engine = engine
        self.playerNode = playerNode
        self.format = format
    }

    /// Schedules a decoded chunk and updates the FIFO bookkeeping. The
    /// session ID is captured at scheduling time: the completion callback
    /// is hopped to MainActor via a `Task`, which can be delayed — by the
    /// time it runs, the owner's session may have moved on
    /// (warm-after-cold). The owner receives the captured ID and applies
    /// its own staleness guards before calling `drainCompletedBuffer`.
    func enqueue(
        _ buffer: AVAudioPCMBuffer,
        chunkAudioSeconds: TimeInterval,
        sessionID: String?,
        onDataPlayedBack: @escaping @MainActor (String?) -> Void
    ) {
        scheduledCount += 1
        bufferDurations.append(chunkAudioSeconds)
        queuedAudioSeconds += chunkAudioSeconds
        playerNode?.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { @Sendable _ in
            // AVFAudio invokes completion handlers on its own queue, so keep
            // the callback nonisolated and hop back to MainActor explicitly.
            Task { @MainActor in
                onDataPlayedBack(sessionID)
            }
        }
    }

    /// Decrements the scheduled count and the audio-second queue depth in
    /// lock-step. AVAudioEngine plays scheduled buffers FIFO, so the head
    /// of `bufferDurations` is the buffer that just completed
    /// (`.dataPlayedBack`). Callers apply session-staleness guards FIRST —
    /// a stale completion must never reach this bookkeeping.
    func drainCompletedBuffer() {
        scheduledCount = max(0, scheduledCount - 1)
        if !bufferDurations.isEmpty {
            let drained = bufferDurations.removeFirst()
            queuedAudioSeconds = max(0, queuedAudioSeconds - drained)
        }
    }

    /// A short zero-filled buffer scheduled ahead of resumed playback so
    /// the node's first real buffer doesn't clip.
    func scheduleLeadingSilence() {
        guard let format, let playerNode else { return }
        let silenceFrames: AVAudioFrameCount = 1024
        guard let silentBuffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: silenceFrames) else { return }
        silentBuffer.frameLength = silenceFrames
        // AVAudioPCMBuffer is zero-filled on creation
        playerNode.scheduleBuffer(silentBuffer)
    }

    func startEngineIfNeeded() throws {
        guard let engine, !engine.isRunning else { return }
        try engine.start()
    }

    func playNode() {
        playerNode?.play()
    }

    func pauseNode() {
        playerNode?.pause()
    }

    /// Stops node + engine and resets the engine's processing graph
    /// (mechanics of the view model's `stopLivePlayback`).
    func stopAndReset() {
        playerNode?.stop()
        engine?.stop()
        engine?.reset()
    }

    /// Zeroes the FIFO bookkeeping (continuity-failure and session-reset
    /// paths).
    func resetBookkeeping() {
        scheduledCount = 0
        queuedAudioSeconds = 0
        bufferDurations.removeAll(keepingCapacity: true)
    }

    /// Forgets the configured format without discarding the graph — the
    /// next `configure` rebuilds against whatever format arrives.
    func clearFormat() {
        format = nil
    }

    /// Phase 4 fix: nil out the audio graph so the next session's first
    /// chunk triggers `configure` to rebuild a fresh engine + player node.
    /// Without this, `engine.reset()` (in `stopAndReset`) leaves the engine
    /// in a state where `engine.start()` throws on the next session — the
    /// owner's catch silently sets a playback error and the user falls
    /// through to file playback once generation ends, losing the
    /// perceived-speed win.
    ///
    /// The reference-counted detach is intentional: `playerNode` is
    /// attached to `engine`. Letting both go to nil triggers ARC teardown
    /// of the attached nodes, avoiding stale-graph assertions on the next
    /// attach.
    func discardGraph() {
        playerNode = nil
        engine = nil
    }
}
