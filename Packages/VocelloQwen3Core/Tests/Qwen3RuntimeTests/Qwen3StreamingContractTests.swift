@testable import MLXAudioTTS
import XCTest

/// Bounded streaming retention and chunk scheduling. Cancellation and the
/// final-audio barrier are pinned on the real producers and consumers, not on
/// a local stream: the lossless channel in `ClassifiedGenerationSessionTests`,
/// the talker loop in `Qwen3TalkerGenerateLoopTests`, the engine in
/// `VocelloQwen3FacadeTests` and the product adapter in
/// `GenerationOutputAdapterChoreographyTests` (DA-09, E7-01).
final class Qwen3StreamingContractTests: XCTestCase {
    func testPendingRetentionIsBoundedAndFirstLaterSchedulingIsExact() {
        var schedule = Qwen3StreamChunkSchedule(firstChunkSize: 3, laterChunkSize: 7)
        var emissionSteps: [Int] = []
        for step in 1...24 {
            if schedule.append() {
                emissionSteps.append(step)
                schedule.didEmit()
            }
        }
        XCTAssertEqual(emissionSteps, [3, 10, 17, 24])
        XCTAssertEqual(schedule.peakPendingCount, 7)
        XCTAssertEqual(schedule.pendingCount, 0)
    }
}
