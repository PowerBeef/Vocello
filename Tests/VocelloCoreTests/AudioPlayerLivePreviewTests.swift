import AVFoundation
import QwenVoiceCore
import XCTest
import VocelloSharedPolicies

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

    /// An output-device change stops the real engine, which drops what the node had queued and
    /// fires no completion. A paused preview that kept its graph would resume past audio nobody
    /// heard and never drain, so it is handed to the take's file at the heard position instead.
    func testAnOutputChangeUnderAPausedPreviewRetiresItsGraphAtTheHeardPosition() async throws {
        _ = await deliverChunksUntilPlaying()
        let graph = try XCTUnwrap(graphs.last)
        graph.advance(1.25)
        player.updatePlaybackProgress()
        player.pause()

        graph.reportConfigurationChange()
        XCTAssertTrue(graph.retired, "the regression: a paused preview kept a graph whose queue was gone")
        XCTAssertFalse(player.isPlaying)
        XCTAssertEqual(player.currentTime, 1.25, accuracy: 1e-6, "the heard position is kept for the file")
        XCTAssertEqual(player.livePreviewPhase, .buffering)
        XCTAssertEqual(player.livePreviewQueueDepth, 0)

        // Play before the take completes plays nothing from the retired graph, and the take's
        // later chunks build no new one: the file continues from the heard position.
        let graphCount = graphs.count
        player.play()
        XCTAssertFalse(player.isPlaying)
        await deliverChunk()
        XCTAssertEqual(graphs.count, graphCount)
        XCTAssertFalse(graph.isNodePlaying)
        XCTAssertEqual(player.currentTime, 1.25, accuracy: 1e-6)
    }

    func testAnOutputChangeUnderAnUnderrunHoldRetiresItsGraphToo() async throws {
        let delivered = await deliverChunksUntilPlaying()
        let graph = try XCTUnwrap(graphs.last)
        graph.advance(1.0)
        player.updatePlaybackProgress()
        for _ in 0..<delivered { graph.playOldestChunk(seconds: 0) }
        await settle { !player.isPlaying }
        XCTAssertFalse(graph.isNodePlaying, "the underrun holds the node")
        let heard = player.currentTime
        XCTAssertEqual(heard, 1.0, accuracy: 1e-6)

        graph.reportConfigurationChange()
        XCTAssertTrue(graph.retired)
        XCTAssertEqual(player.currentTime, heard, accuracy: 1e-6)
        let graphCount = graphs.count
        await deliverChunk()
        XCTAssertEqual(graphs.count, graphCount, "the rest of the take waits for its file")
        XCTAssertFalse(player.isPlaying)
    }

    /// A preview that never played has started no engine, so nothing was dropped: it keeps
    /// its graph and plays from it.
    func testAnOutputChangeBeforeThePreviewPlaysKeepsItsGraph() async throws {
        player.pause()
        await deliverChunk()
        XCTAssertFalse(player.isPlaying, "a held take waits for Play")
        let graph = try XCTUnwrap(graphs.last)
        graph.reportConfigurationChange()
        XCTAssertFalse(graph.retired)
        player.play()
        XCTAssertTrue(player.isPlaying)
        XCTAssertTrue(graph.isNodePlaying)
    }

    /// Regression test: in live mode the playhead timer ticks at 3 Hz (333 ms), while streamed
    /// chunks arrive every ~85-150 ms. Re-arming `startTimer()` on every chunk invalidated the
    /// timer before it ever fired, keeping `currentTime` at 0:00 and `progress` at 0% until
    /// generation completed. Also pins `appendLiveChunk` keeping `.playing` when queued audio
    /// dips below the initial prebuffer threshold while the node is actively playing.
    func testRapidlyArrivingChunksDoNotStarveTheLivePlayheadTimer() async throws {
        let longPrompt = String(repeating: "The morning train left the station on schedule. ", count: 6)
        player.setLivePreviewEstimate(LivePreviewEstimate(text: longPrompt))
        player.prepareStreamingPreview(
            title: "take", shouldAutoPlay: true, generationID: generationID, playbackOperationID: operationID
        )

        let prebuffered = await deliverChunksUntilPlaying()
        XCTAssertTrue(player.isPlaying)
        let graph = try XCTUnwrap(graphs.last)

        // Drain down to a single 1.5 s queued chunk (below the 3.25 s smooth-first prebuffer)
        // while the node continues playing, then deliver a new chunk: phase must stay `.playing`.
        for _ in 0..<max(0, prebuffered - 1) {
            graph.playOldestChunk(seconds: 0.05)
        }
        await settle { player.livePreviewQueueDepth == 1 }
        await deliverChunk()
        XCTAssertEqual(player.livePreviewPhase, .playing)

        // Deliver 10 chunks 80 ms apart (~800 ms, spanning two full 333 ms 3 Hz ticks), advancing
        // the fake graph before each sleep so timer firing order has generous CI/TSan slack.
        for _ in 0..<10 {
            graph.advance(0.08)
            try await Task.sleep(for: .milliseconds(80))
            await deliverChunk()
            XCTAssertEqual(player.livePreviewPhase, .playing)
        }

        XCTAssertGreaterThan(
            player.currentTime, 0.3,
            "the 3 Hz RunLoop timer must fire while chunks arrive every 80 ms"
        )
        XCTAssertGreaterThan(
            player.playbackProgress.progress, 0,
            "the live waveform bar must advance while generation is still in flight"
        )
    }

    private func writeSilentWAV(durationSeconds: TimeInterval) throws -> URL {
        let sampleRate = 8_000.0
        let frameCount = AVAudioFrameCount(durationSeconds * sampleRate)
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 1))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount))
        buffer.frameLength = frameCount
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("live-preview-test-\(UUID().uuidString).wav")
        let file = try AVAudioFile(
            forWriting: url,
            settings: format.settings,
            commonFormat: format.commonFormat,
            interleaved: format.isInterleaved
        )
        try file.write(from: buffer)
        return url
    }

    /// Regression test: live-preview bar progress scales against the text estimate (floored by
    /// generated duration), never steps backward when chunks extend `duration` or when
    /// `completeStreamingPreview` hands over to a longer final file, releases its morph floor
    /// once heard time catches up, and clears immediately on a backward `seek(to:)` during drain.
    func testLiveProgressAdvancesMonotonicallyAcrossChunksAndFinalHandoff() async throws {
        let finalWAV = try writeSilentWAV(durationSeconds: 25.0)
        defer { try? FileManager.default.removeItem(at: finalWAV) }

        player = AudioPlayerViewModel(livePlayback: LiveStreamingPlaybackEngine { [weak self] _ in
            let graph = FakeLivePreviewGraph()
            self?.graphs.append(graph)
            return graph
        })
        player.beginGenerationPlayback(operationID: operationID, mode: .custom)
        // ~16.7-second prompt estimate; chunks arrive much faster than real time.
        let longPrompt = String(repeating: "The morning train left the station on schedule. ", count: 5)
        player.setLivePreviewEstimate(LivePreviewEstimate(text: longPrompt))
        player.prepareStreamingPreview(
            title: "take", shouldAutoPlay: true, generationID: generationID, playbackOperationID: operationID
        )

        _ = await deliverChunksUntilPlaying()
        let graph = try XCTUnwrap(graphs.last)

        var previousProgress = player.playbackProgress.progress
        for _ in 0..<6 {
            graph.advance(0.35)
            player.updatePlaybackProgress()
            let afterTick = player.playbackProgress.progress
            XCTAssertGreaterThan(afterTick, previousProgress, "each heard tick advances the bar")
            previousProgress = afterTick

            // A new 1.5 s chunk arrives faster than real time, extending `duration`.
            await deliverChunk()
            XCTAssertGreaterThanOrEqual(
                player.playbackProgress.progress, previousProgress,
                "a newly arrived chunk must never step the playhead bar backward"
            )
            previousProgress = player.playbackProgress.progress
        }

        // Complete streaming against a 25.0 s final WAV while live buffers are still draining:
        // the morph floor holds the bar until heard time catches up, then releases.
        let result = GenerationResult(
            audioPath: finalWAV.path,
            durationSeconds: 25.0,
            streamSessionDirectory: nil,
            usedStreaming: true
        )
        player.completeStreamingPreview(
            result: result,
            title: "take",
            shouldAutoPlay: true,
            playbackOperationID: operationID
        )
        XCTAssertEqual(player.playbackProgress.progress, previousProgress, accuracy: 1e-9)

        // Advance past the held floor (heard 3.6 s / 25.0 s = 0.144 > ~0.1255): floor releases.
        graph.advance(1.5)
        player.updatePlaybackProgress()
        XCTAssertGreaterThan(player.playbackProgress.progress, previousProgress + 0.01)

        // Re-verify backward seek during the post-completion live-buffer drain window: reset a
        // fresh session whose morph floor is active and seek backward to 5%.
        let secondOperationID = UUID()
        let secondGenerationID = UUID()
        player.beginGenerationPlayback(operationID: secondOperationID, mode: .custom)
        player.claimGenerationStream(secondGenerationID, operationID: secondOperationID)
        player.setLivePreviewEstimate(LivePreviewEstimate(text: longPrompt))
        player.prepareStreamingPreview(
            title: "take-2", shouldAutoPlay: true, generationID: secondGenerationID, playbackOperationID: secondOperationID
        )
        XCTAssertFalse(player.isPlaying)
        nextFrameOffset = 0
        while !player.isPlaying {
            let chunk = GenerationChunk(
                generationID: secondGenerationID,
                requestID: 2,
                mode: "custom",
                title: "take-2",
                chunkPath: nil,
                isFinal: false,
                chunkDurationSeconds: Self.chunkSeconds,
                cumulativeDurationSeconds: nil,
                streamSessionDirectory: nil,
                previewAudio: StreamingAudioChunk(
                    generationID: secondGenerationID,
                    requestID: 2,
                    sampleRate: Self.sampleRate,
                    frameOffset: nextFrameOffset,
                    frameCount: Self.chunkFrames,
                    pcm16LE: Data(count: Self.chunkFrames * MemoryLayout<Int16>.stride),
                    isFinal: false
                )
            )
            nextFrameOffset += Int64(Self.chunkFrames)
            let before = player.livePreviewQueueDepth
            NotificationCenter.default.post(name: .generationChunkReceived, object: nil, userInfo: ["chunk": chunk])
            await settle { player.livePreviewQueueDepth != before }
        }
        let secondGraph = try XCTUnwrap(graphs.last)
        secondGraph.advance(4.0)
        player.updatePlaybackProgress()
        let heldBeforeSeek = player.playbackProgress.progress
        XCTAssertGreaterThan(heldBeforeSeek, 0.2)

        player.completeStreamingPreview(
            result: result,
            title: "take-2",
            shouldAutoPlay: true,
            playbackOperationID: secondOperationID
        )
        XCTAssertEqual(player.playbackProgress.progress, heldBeforeSeek, accuracy: 1e-9)

        // Seeking backward to 5% while live buffers are still queued switches to the final file
        // without re-arming the pre-seek morph floor.
        player.seek(to: 0.05)
        XCTAssertEqual(player.playbackProgress.progress, 0.05, accuracy: 1e-3)

        player.stop()
        XCTAssertEqual(player.currentTime, 0, accuracy: 1e-9)
        XCTAssertEqual(player.playbackProgress.progress, 0, accuracy: 1e-9)
    }
}
