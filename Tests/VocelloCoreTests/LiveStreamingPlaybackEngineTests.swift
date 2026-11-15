import AVFoundation
import XCTest

/// The live preview's audio graph without audio hardware (RF-61, audit findings A2, A3 and T9).
/// The node's clock follows what `AVAudioPlayerNode` was measured to do on macOS 27.2: it runs
/// only while the node plays, a pause keeps it, and a stop returns it to zero.
@MainActor
final class FakeLivePreviewGraph: LivePreviewAudioGraph {
    enum Scheduled: Equatable {
        case audio(frames: AVAudioFrameCount)
        case silence(frames: AVAudioFrameCount)
    }

    private(set) var scheduled: [Scheduled] = []
    private(set) var isNodePlaying = false
    private(set) var isRunning = false
    private(set) var retired = false
    var isIntact = true
    private var clock: TimeInterval = 0
    private var configurationHandler: (@MainActor () -> Void)?
    /// The completions of the chunks still queued, in the order they were scheduled.
    private var pendingCompletions: [@Sendable () -> Void] = []

    var nodeSeconds: TimeInterval? { isNodePlaying ? clock : nil }

    func schedule(_ buffer: AVAudioPCMBuffer, onPlayedBack: (@Sendable () -> Void)?) {
        // The engine queues its leading silence without a completion; every chunk has one.
        scheduled.append(
            onPlayedBack == nil ? .silence(frames: buffer.frameLength) : .audio(frames: buffer.frameLength)
        )
        if let onPlayedBack { pendingCompletions.append(onPlayedBack) }
    }

    /// The node plays its oldest queued chunk to the end: the clock advances by its length and
    /// its completion fires, as AVFAudio does off the main actor.
    func playOldestChunk(seconds: TimeInterval) {
        guard isNodePlaying, !pendingCompletions.isEmpty else { return }
        clock += seconds
        pendingCompletions.removeFirst()()
    }

    func startIfNeeded() throws { isRunning = true }

    func playNode() { isNodePlaying = true }

    func pauseNode() { isNodePlaying = false }

    func stopNodeAndReset() {
        isNodePlaying = false
        clock = 0
        scheduled.removeAll()
        pendingCompletions.removeAll()
    }

    func observeConfigurationChange(_ handler: @escaping @MainActor () -> Void) {
        configurationHandler = handler
    }

    func stopObservingConfigurationChange() { configurationHandler = nil }

    func retire() {
        retired = true
        isNodePlaying = false
    }

    /// Render time passes: the node's clock advances only while it plays.
    func advance(_ seconds: TimeInterval) {
        if isNodePlaying { clock += seconds }
    }

    /// The output hardware changed under this graph. A retired graph can still say so, late.
    func reportConfigurationChange() { configurationHandler?() }
}

@MainActor
final class LiveStreamingPlaybackEngineTests: XCTestCase {
    private static let sampleRate = 24_000.0

    private func makeEngine() -> (LiveStreamingPlaybackEngine, () -> [FakeLivePreviewGraph]) {
        var graphs: [FakeLivePreviewGraph] = []
        let engine = LiveStreamingPlaybackEngine { _ in
            let graph = FakeLivePreviewGraph()
            graphs.append(graph)
            return graph
        }
        return (engine, { graphs })
    }

    private func format() throws -> AVAudioFormat {
        try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: Self.sampleRate, channels: 1))
    }

    private func enqueue(seconds: TimeInterval, on engine: LiveStreamingPlaybackEngine) throws {
        let frames = AVAudioFrameCount(seconds * Self.sampleRate)
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format(), frameCapacity: frames))
        buffer.frameLength = frames
        engine.enqueue(buffer, chunkAudioSeconds: seconds, sessionID: "take") { _ in }
    }

    func testAUserPauseKeepsTheQueueAndThePlayhead() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        let graph = try XCTUnwrap(graphs().first)
        for _ in 0..<3 { try enqueue(seconds: 1, on: engine) }
        try engine.startEngineIfNeeded()
        engine.playNode()
        graph.advance(1.5)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 1.5, accuracy: 1e-9)

        engine.pauseNode()
        graph.advance(4)
        XCTAssertNil(engine.heardSeconds, "a paused node has no clock to read; the owner keeps its last position")

        engine.playNode()
        // The regression: the owner added the heard position on resume, and the playhead read 3.0.
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 1.5, accuracy: 1e-9)
        graph.advance(0.5)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 2.0, accuracy: 1e-9)
        XCTAssertEqual(
            graph.scheduled,
            Array(repeating: .audio(frames: 24_000), count: 3),
            "a resume with audio queued schedules nothing"
        )
        XCTAssertEqual(engine.scheduledCount, 3)
    }

    func testAnUnderrunQueuesItsSilenceAheadOfTheAudioThatFollows() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        let graph = try XCTUnwrap(graphs().first)
        for _ in 0..<2 { try enqueue(seconds: 1, on: engine) }
        try engine.startEngineIfNeeded()
        engine.playNode()
        graph.advance(2)
        engine.drainCompletedBuffer()
        engine.drainCompletedBuffer()
        XCTAssertEqual(engine.scheduledCount, 0)
        // The completion reaches the main actor a little after the audio ended, and the node's
        // clock ran on meanwhile.
        graph.advance(0.08)

        engine.holdForUnderrun()
        XCTAssertFalse(engine.isNodePlaying)
        let silence = FakeLivePreviewGraph.Scheduled.silence(frames: LiveStreamingPlaybackEngine.leadingSilenceFrames)
        XCTAssertEqual(graph.scheduled.last, silence)

        try enqueue(seconds: 1, on: engine)
        XCTAssertEqual(
            graph.scheduled.suffix(2),
            [silence, .audio(frames: 24_000)],
            "the silence leads the audio that follows the underrun, never trails audio already queued"
        )

        engine.playNode()
        let silenceSeconds = Double(LiveStreamingPlaybackEngine.leadingSilenceFrames) / Self.sampleRate
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 2.0, accuracy: 1e-9, "never below what was played")
        graph.advance(silenceSeconds)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 2.0, accuracy: 1e-9)
        graph.advance(0.5)
        XCTAssertEqual(
            try XCTUnwrap(engine.heardSeconds), 2.5, accuracy: 1e-9,
            "neither the idle clock time nor the silence counts as heard audio"
        )
    }

    func testAStopReturnsThePlayheadToZero() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        let graph = try XCTUnwrap(graphs().first)
        try enqueue(seconds: 1, on: engine)
        engine.playNode()
        graph.advance(1)
        engine.drainCompletedBuffer()
        engine.holdForUnderrun()

        // A stop alone forgets the anchor: the node's clock restarts at zero.
        engine.stopAndReset()
        XCTAssertEqual(engine.scheduledCount, 0, "the hold's silence was never counted as a queued chunk")
        try enqueue(seconds: 1, on: engine)
        engine.playNode()
        graph.advance(0.25)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 0.25, accuracy: 1e-9)
    }

    func testResettingTheBookkeepingForgetsWhatWasPlayed() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        let graph = try XCTUnwrap(graphs().first)
        for _ in 0..<2 { try enqueue(seconds: 1, on: engine) }
        engine.playNode()
        graph.advance(1)
        engine.drainCompletedBuffer()
        engine.holdForUnderrun()
        XCTAssertEqual(engine.scheduledCount, 1)

        engine.resetBookkeeping()
        XCTAssertEqual(engine.scheduledCount, 0)
        XCTAssertEqual(engine.queuedAudioSeconds, 0)
        try enqueue(seconds: 1, on: engine)
        engine.playNode()
        XCTAssertEqual(
            try XCTUnwrap(engine.heardSeconds), 1, accuracy: 1e-9,
            "without an anchor the playhead is the node's clock again, here still at one second"
        )
    }

    func testPlayPressedDuringAnUnderrunDoesNotCountTheWaitAsHeard() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        let graph = try XCTUnwrap(graphs().first)
        for _ in 0..<2 { try enqueue(seconds: 1, on: engine) }
        engine.playNode()
        graph.advance(2)
        engine.drainCompletedBuffer()
        engine.drainCompletedBuffer()
        graph.advance(0.08)
        engine.holdForUnderrun()

        // The listener presses Play before the next chunk: the node plays its silence, then
        // an empty queue, and its clock runs for three seconds.
        engine.playNode()
        graph.advance(3)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 2.0, accuracy: 1e-9, "nothing new was heard yet")
        try enqueue(seconds: 1, on: engine)
        XCTAssertEqual(try XCTUnwrap(engine.heardSeconds), 2.0, accuracy: 1e-9)
        graph.advance(0.25)
        XCTAssertEqual(
            try XCTUnwrap(engine.heardSeconds), 2.25, accuracy: 1e-9,
            "the regression: 5.21 s, which resumed the final file past audio nobody had heard"
        )
    }

    func testOnlyTheLiveGraphReportsAnOutputChange() throws {
        let (engine, graphs) = makeEngine()
        var changes = 0
        engine.onConfigurationChange = { changes += 1 }
        engine.configure(with: try format())
        let first = try XCTUnwrap(graphs().first)
        engine.configure(with: try format())
        XCTAssertEqual(graphs().count, 1, "an intact graph of the same format is reused")

        first.reportConfigurationChange()
        XCTAssertEqual(changes, 1)

        engine.discardGraph()
        XCTAssertTrue(first.retired)
        XCTAssertFalse(engine.isConfigured)
        engine.configure(with: try format())
        XCTAssertEqual(graphs().count, 2)
        first.reportConfigurationChange()
        XCTAssertEqual(changes, 1, "a retired graph's late notification changes nothing")
        try XCTUnwrap(graphs().last).reportConfigurationChange()
        XCTAssertEqual(changes, 2)
    }

    func testAGraphThatLostItsNodeIsRebuilt() throws {
        let (engine, graphs) = makeEngine()
        engine.configure(with: try format())
        try XCTUnwrap(graphs().first).isIntact = false
        engine.configure(with: try format())
        XCTAssertEqual(graphs().count, 2)
        XCTAssertTrue(try XCTUnwrap(graphs().first).retired)
    }
}
