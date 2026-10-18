@testable import MLXAudioTTS
import Testing
@testable import VocelloQwen3Core

/// Engine audit A-15: a chunk size travels as seconds (`frames / 12.5`) from the contract to
/// the talker loop and back to frames. Truncation lost a frame for 37 of the sizes 1-512.
/// The first Swift Testing suite in the owned package, whose tests run under `swift test`
/// (the Xcode test targets' raw xctest runner never runs Swift Testing; workflow audit P1-6).
@Suite("Streaming interval to codec frames")
struct Qwen3StreamChunkFramesTests {
    @Test("Every chunk size from 1 to 512 frames survives the trip through seconds", arguments: 1...512)
    func framesSurviveTheTripThroughSeconds(frames: Int) {
        // The contract's own conversion, not a copy of its formula.
        let seconds = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: frames, laterCodecFrames: frames, pendingFrameLimit: frames
        ).compatibilityStreamingInterval
        #expect(Qwen3StreamChunkSchedule.codecFrames(forStreamingInterval: seconds) == frames)
    }

    @Test("An interval shorter than one frame still schedules one frame", arguments: [0.0, -1.0, 0.01, 0.039])
    func atLeastOneFrame(seconds: Double) {
        #expect(Qwen3StreamChunkSchedule.codecFrames(forStreamingInterval: seconds) == 1)
    }
}
