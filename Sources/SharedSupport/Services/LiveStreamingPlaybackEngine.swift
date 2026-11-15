import AVFoundation
import Foundation

/// Terminal ownership transfer for an AVAudioEngine graph. The main actor first stops the player
/// node and severs every app reference; this box then owns the graph exclusively until the
/// utility-priority teardown finishes. AVFAudio does not declare its graph objects Sendable, so the
/// unchecked conformance is limited to this one-way, never-read-again retirement boundary.
private struct RetiredLivePlaybackGraph: @unchecked Sendable {
    let engine: AVAudioEngine

    func stopAndReleaseResources() {
        engine.stop()
        engine.reset()
    }
}

/// What the live preview asks of an audio graph: one player node's queue, clock and transport
/// (RF-61, audit finding T9). `AVLivePreviewAudioGraph` is the shipping one; a test supplies its
/// own, so the order buffers are scheduled in and the playhead arithmetic run without audio
/// hardware.
@MainActor
protocol LivePreviewAudioGraph: AnyObject {
    var isNodePlaying: Bool { get }
    var isRunning: Bool { get }
    /// Whether the node is still attached, so a graph a panic path tore down is rebuilt.
    var isIntact: Bool { get }
    /// The node's own player time, nil while it is not playing. A pause keeps it and the next
    /// play continues from it; only a stop returns it to zero.
    var nodeSeconds: TimeInterval? { get }
    /// Appends to the node's queue. `onPlayedBack` fires off the main actor.
    func schedule(_ buffer: AVAudioPCMBuffer, onPlayedBack: (@Sendable () -> Void)?)
    func startIfNeeded() throws
    func playNode()
    func pauseNode()
    /// Stops the node, which empties its queue and returns its player time to zero, and resets
    /// the engine.
    func stopNodeAndReset()
    func observeConfigurationChange(_ handler: @escaping @MainActor () -> Void)
    func stopObservingConfigurationChange()
    /// The one-way hand-over of the graph to its background teardown.
    func retire()
}

/// The AVFAudio graph: an engine and one player node connected to its main mixer. After `retire`
/// it holds neither, so the background teardown owns the engine alone.
@MainActor
final class AVLivePreviewAudioGraph: LivePreviewAudioGraph {
    private var engine: AVAudioEngine?
    private var playerNode: AVAudioPlayerNode?
    private var configurationObserver: NSObjectProtocol?

    init(format: AVAudioFormat) {
        let engine = AVAudioEngine()
        let playerNode = AVAudioPlayerNode()
        engine.attach(playerNode)
        engine.connect(playerNode, to: engine.mainMixerNode, format: format)
        self.engine = engine
        self.playerNode = playerNode
    }

    /// Runs on the main actor even when the last reference goes elsewhere (an
    /// `isolated deinit` hops there instead of trapping like `assumeIsolated`).
    isolated deinit {
        stopObservingConfigurationChange()
    }

    var isNodePlaying: Bool { playerNode?.isPlaying ?? false }

    var isRunning: Bool { engine?.isRunning ?? false }

    var isIntact: Bool {
        guard let engine, let playerNode else { return false }
        return engine.attachedNodes.contains(playerNode)
    }

    var nodeSeconds: TimeInterval? {
        guard let playerNode,
              let lastRenderTime = playerNode.lastRenderTime,
              let playerTime = playerNode.playerTime(forNodeTime: lastRenderTime),
              playerTime.sampleRate > 0 else { return nil }
        return Double(playerTime.sampleTime) / playerTime.sampleRate
    }

    func schedule(_ buffer: AVAudioPCMBuffer, onPlayedBack: (@Sendable () -> Void)?) {
        guard let onPlayedBack else {
            playerNode?.scheduleBuffer(buffer)
            return
        }
        playerNode?.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { @Sendable _ in
            onPlayedBack()
        }
    }

    func startIfNeeded() throws {
        guard let engine, !engine.isRunning else { return }
        try engine.start()
    }

    func playNode() {
        playerNode?.play()
    }

    func pauseNode() {
        playerNode?.pause()
    }

    func stopNodeAndReset() {
        playerNode?.stop()
        engine?.reset()
    }

    func observeConfigurationChange(_ handler: @escaping @MainActor () -> Void) {
        stopObservingConfigurationChange()
        guard let engine else { return }
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated {
                handler()
            }
        }
    }

    func stopObservingConfigurationChange() {
        if let configurationObserver {
            NotificationCenter.default.removeObserver(configurationObserver)
        }
        configurationObserver = nil
    }

    /// The reference-counted detach is intentional: the node is attached to the engine, and
    /// letting both go triggers ARC teardown of the attached nodes, avoiding stale-graph
    /// assertions on the next attach.
    func retire() {
        stopObservingConfigurationChange()
        playerNode?.stop()
        let retiredGraph = engine.map(RetiredLivePlaybackGraph.init)
        playerNode = nil
        engine = nil
        guard let retiredGraph else { return }
        Task.detached(priority: .utility) { @concurrent in
            retiredGraph.stopAndReleaseResources()
        }
    }
}

/// The live-preview audio graph (W2-D, 2026-08 UI review): AVAudioEngine +
/// player-node lifecycle and the FIFO scheduled-buffer bookkeeping,
/// extracted from the ~1,700-line `AudioPlayerViewModel`. The engine owns
/// mechanics only — session identity, staleness guards, published UI state,
/// timers, and telemetry stay with the owning view model, which calls back
/// through the completion hook it passes to `enqueue`.
@MainActor
final class LiveStreamingPlaybackEngine {
    private var graph: (any LivePreviewAudioGraph)?
    private let makeGraph: @MainActor (AVAudioFormat) -> any LivePreviewAudioGraph
    private(set) var format: AVAudioFormat?
    /// Maps the node's clock to the position the listener has heard.
    private var playhead = LivePreviewPlayhead()

    /// Frames of the silent buffer that leads resumed playback after an underrun.
    static let leadingSilenceFrames: AVAudioFrameCount = 1024

    init(makeGraph: @escaping @MainActor (AVAudioFormat) -> any LivePreviewAudioGraph = {
        AVLivePreviewAudioGraph(format: $0)
    }) {
        self.makeGraph = makeGraph
    }

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

    /// Called on the main actor when the output hardware changes under the
    /// current graph (`AVAudioEngineConfigurationChange`, MAC-18): the engine
    /// has stopped itself and may have dropped what the node had queued. The
    /// owner decides how playback continues.
    var onConfigurationChange: (@MainActor () -> Void)?

    var isConfigured: Bool {
        graph != nil
    }

    var isNodePlaying: Bool {
        graph?.isNodePlaying ?? false
    }

    var isEngineRunning: Bool {
        graph?.isRunning ?? false
    }

    /// The position the listener has heard, nil until the node has a render time.
    ///
    /// The node's player time alone is not that position. It survives `pause()` and continues on
    /// the next `play()`, so nothing is added on a resume: adding the heard position there, as
    /// the owner did until 2026-11-15, counted it twice (audit finding A3). It also keeps running
    /// while the node waits on an empty queue, which `holdForUnderrun` corrects.
    var heardSeconds: TimeInterval? {
        guard let nodeSeconds = graph?.nodeSeconds else { return nil }
        // With nothing queued, everything scheduled has been heard, and the clock of a node
        // that plays an empty queue (Play pressed during an underrun) measures only the wait.
        if scheduledCount == 0 { return playhead.playedSeconds }
        return playhead.heardSeconds(nodeSeconds: nodeSeconds)
    }

    /// Idempotent: if a prior pre-warm or chunk-arrival call already
    /// configured the engine with this exact format, skip the expensive
    /// allocation + attach + connect path. This is what makes the
    /// `prepareStreamingPreview` pre-warm a free win at the first chunk's
    /// arrival site.
    func configure(with format: AVAudioFormat) {
        if let graph, let existingFormat = self.format, existingFormat == format {
            // Belt-and-suspenders: the engine could have been torn down
            // between pre-warm and chunk arrival (e.g. a panic path called
            // `engine.stop()`); confirm it's still running a valid graph
            // before reusing.
            if graph.isIntact {
                return
            }
        }

        if graph != nil {
            discardGraph()
        }

        let graph = makeGraph(format)
        self.graph = graph
        self.format = format
        playhead = LivePreviewPlayhead()
        // Only the live graph's change counts; a retired graph's late
        // notification changes nothing.
        graph.observeConfigurationChange { [weak self, weak graph] in
            guard let self, let graph, self.graph === graph else { return }
            self.onConfigurationChange?()
        }
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
        if scheduledCount == 0, let graph, graph.isNodePlaying {
            // The node is playing an empty queue: Play was pressed during an underrun, before
            // this chunk arrived. Its clock ran while nothing was heard, so the playhead is
            // anchored again to what was played.
            playhead.underrun(nodeSeconds: graph.nodeSeconds, leadingSilenceSeconds: 0)
        }
        scheduledCount += 1
        bufferDurations.append(chunkAudioSeconds)
        queuedAudioSeconds += chunkAudioSeconds
        graph?.schedule(buffer) { @Sendable in
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
            playhead.bufferPlayed(seconds: drained)
        }
    }

    /// Holds a node whose queue ran dry until more audio arrives (an underrun).
    ///
    /// The node is paused and a short zero-filled buffer is queued, so the first real buffer of
    /// the resumed playback does not clip. It is queued here, while the queue is empty, and
    /// therefore plays before the chunks that follow. Until 2026-11-15 it was queued on resume,
    /// behind the audio already waiting, where it put 43 ms of silence in the middle of the take
    /// (audit finding A2). The playhead is anchored to what was actually played: the node's clock
    /// ran on between the last buffer's end and this call, and will run through the silence.
    func holdForUnderrun() {
        guard let graph else { return }
        let nodeSeconds = graph.nodeSeconds
        graph.pauseNode()
        var silenceSeconds: TimeInterval = 0
        if let format, format.sampleRate > 0,
           let silentBuffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: Self.leadingSilenceFrames) {
            // AVAudioPCMBuffer is zero-filled on creation.
            silentBuffer.frameLength = Self.leadingSilenceFrames
            graph.schedule(silentBuffer, onPlayedBack: nil)
            silenceSeconds = Double(Self.leadingSilenceFrames) / format.sampleRate
        }
        playhead.underrun(nodeSeconds: nodeSeconds, leadingSilenceSeconds: silenceSeconds)
    }

    func startEngineIfNeeded() throws {
        try graph?.startIfNeeded()
    }

    func playNode() {
        graph?.playNode()
    }

    /// A user or system pause. The node keeps its queue and its clock, so the next `playNode`
    /// continues where this stopped and schedules nothing.
    func pauseNode() {
        graph?.pauseNode()
    }

    /// Silences the player immediately and resets node state. The engine remains owned by this
    /// object until `discardGraph`, which performs the potentially blocking hardware stop away
    /// from the user-interactive main actor.
    func stopAndReset() {
        graph?.stopNodeAndReset()
        playhead = LivePreviewPlayhead()
    }

    /// Zeroes the FIFO bookkeeping (continuity-failure and session-reset
    /// paths).
    func resetBookkeeping() {
        scheduledCount = 0
        queuedAudioSeconds = 0
        bufferDurations.removeAll(keepingCapacity: true)
        playhead = LivePreviewPlayhead()
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
        let retired = graph
        graph = nil
        retired?.retire()
    }
}
