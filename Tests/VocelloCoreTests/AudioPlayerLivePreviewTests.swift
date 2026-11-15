import AVFoundation
import QwenVoiceCore
import XCTest

/// The player's live preview driven as the app drives it, on a fake audio graph (RF-61, audit
/// findings A2, A3 and T9): streamed chunks arrive as notifications, the node "plays" them, the
/// queue runs dry and more audio arrives. These fail if the view model stops holding an underrun
/// through the engine, schedules anything on resume, or adds to the engine's playhead.
@MainActor
final class AudioPlayerLivePreviewTests: XCTestCase {
    private static let sampleRate = 24_000
    private static let chunkSeconds = 1.5
    private static var chunkFrames: Int { Int(chunkSeconds * Double(sampleRate)) }

    private var graphs: [FakeLivePreviewGraph] = []
    private var player: AudioPlayerViewModel!
    private let operationID = UUID()
    private let generationID = UUID()
    private var nextFrameOffset: Int64 = 0

    override func setUp() async throws {
        graphs = []
        nextFrameOffset = 0
        player = AudioPlayerViewModel(livePlayback: LiveStreamingPlaybackEngine { [weak self] _ in
            let graph = FakeLivePreviewGraph()
            self?.graphs.append(graph)
            return graph
        })
        player.beginGenerationPlayback(operationID: operationID, mode: .custom)
        player.prepareStreamingPreview(
            title: "take", shouldAutoPlay: true, generationID: generationID, playbackOperationID: operationID
        )
    }

    override func tearDown() async throws {
        player = nil
        graphs = []
    }

    /// One streamed chunk of silence, delivered the way the engine store delivers it. The
    /// player observes on the main queue, so the chunk lands once that queue has run.
    private func deliverChunk() async {
        let queuedBefore = player.livePreviewQueueDepth
        let chunk = GenerationChunk(
            generationID: generationID,
            requestID: 1,
            mode: "custom",
            title: "take",
            chunkPath: nil,
            isFinal: false,
            chunkDurationSeconds: Self.chunkSeconds,
            cumulativeDurationSeconds: nil,
            streamSessionDirectory: nil,
            previewAudio: StreamingAudioChunk(
                generationID: generationID,
                requestID: 1,
                sampleRate: Self.sampleRate,
                frameOffset: nextFrameOffset,
                frameCount: Self.chunkFrames,
                pcm16LE: Data(count: Self.chunkFrames * MemoryLayout<Int16>.stride),
                isFinal: false
            )
        )
        nextFrameOffset += Int64(Self.chunkFrames)
        NotificationCenter.default.post(name: .generationChunkReceived, object: nil, userInfo: ["chunk": chunk])
        await settle { player.livePreviewQueueDepth != queuedBefore }
    }

    /// Lets the completions' hops back to the main actor run.
    private func settle(until condition: () -> Bool) async {
        for _ in 0..<400 where !condition() {
            await Task.yield()
        }
    }

    private func deliverChunksUntilPlaying(limit: Int = 12) async -> Int {
        var delivered = 0
        while !player.isPlaying, delivered < limit {
            await deliverChunk()
            delivered += 1
        }
        return delivered
    }

    func testAnUnderrunHoldsThroughTheEngineAndTheResumedTakeKeepsItsPlayhead() async throws {
        let firstBatch = await deliverChunksUntilPlaying()
        XCTAssertTrue(player.isPlaying, "the prebuffer fills and the preview starts on its own")
        // The chunk's own format replaced the graph the preview was pre-warmed with.
        let graph = try XCTUnwrap(graphs.last)
        XCTAssertTrue(graph.isNodePlaying)
        let audio = FakeLivePreviewGraph.Scheduled.audio(frames: AVAudioFrameCount(Self.chunkFrames))
        XCTAssertEqual(graph.scheduled, Array(repeating: audio, count: firstBatch))

        // The node plays everything it has; generation has fallen behind.
        for _ in 0..<firstBatch { graph.playOldestChunk(seconds: Self.chunkSeconds) }
        await settle { !player.isPlaying }
        XCTAssertFalse(player.isPlaying)
        XCTAssertFalse(graph.isNodePlaying, "the underrun holds the node")
        XCTAssertEqual(player.livePreviewPhase, .buffering)
        let silence = FakeLivePreviewGraph.Scheduled.silence(frames: LiveStreamingPlaybackEngine.leadingSilenceFrames)
        XCTAssertEqual(graph.scheduled.last, silence, "the leading silence is queued while the queue is empty")
        let heardAtUnderrun = Double(firstBatch) * Self.chunkSeconds

        // More audio arrives and the preview resumes by itself.
        let secondBatch = await deliverChunksUntilPlaying()
        XCTAssertTrue(player.isPlaying)
        XCTAssertEqual(
            graph.scheduled,
            Array(repeating: audio, count: firstBatch) + [silence] + Array(repeating: audio, count: secondBatch),
            "nothing but the new chunks is scheduled on resume, and the silence leads them"
        )

        // The node plays its silence and half a second of the new audio.
        graph.advance(Double(LiveStreamingPlaybackEngine.leadingSilenceFrames) / Double(Self.sampleRate) + 0.5)
        player.updatePlaybackProgress()
        XCTAssertEqual(
            player.currentTime, heardAtUnderrun + 0.5, accuracy: 1e-6,
            "the regression: the playhead doubled after an underrun"
        )
    }

    func testAUserPauseAndPlayKeepThePlayheadAndScheduleNothing() async throws {
        let delivered = await deliverChunksUntilPlaying()
        let graph = try XCTUnwrap(graphs.last)
        graph.advance(1.25)
        player.updatePlaybackProgress()
        XCTAssertEqual(player.currentTime, 1.25, accuracy: 1e-6)

        player.pause()
        XCTAssertFalse(player.isPlaying)
        XCTAssertFalse(graph.isNodePlaying)
        graph.advance(5)
        player.updatePlaybackProgress()
        XCTAssertEqual(player.currentTime, 1.25, accuracy: 1e-6, "a paused take keeps its position")

        player.play()
        XCTAssertTrue(player.isPlaying)
        XCTAssertTrue(graph.isNodePlaying)
        player.updatePlaybackProgress()
        XCTAssertEqual(player.currentTime, 1.25, accuracy: 1e-6, "the regression: 2.5 s after one pause")
        graph.advance(0.25)
        player.updatePlaybackProgress()
        XCTAssertEqual(player.currentTime, 1.5, accuracy: 1e-6)
        XCTAssertEqual(
            graph.scheduled,
            Array(repeating: .audio(frames: AVAudioFrameCount(Self.chunkFrames)), count: delivered),
            "a resume with audio queued schedules no silence"
        )
    }
}
