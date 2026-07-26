@testable import QwenVoiceCore
import XCTest

final class DeliveryInstructionAdvisorTests: XCTestCase {
    func testDurationDirectivesAreDetected() {
        let positives = [
            "Speak warmly and finish within 20 seconds.",
            "Calm narrator, complete this in 30 seconds",
            "wrap it up in 15 secs",
            "Read it in 10 seconds, bright and fast",
            "keep it to 30 seconds max",
            "20 seconds or less, whispered",
            "45 seconds total, newsy pacing",
            "a total duration of 30 seconds, cheerful",
            "Voix chaleureuse, en moins de 20 secondes",
            "Lis ce texte en 30 secondes",
            "durée de 15 secondes, ton posé",
            "End by 45 seconds with a soft fade in energy",
        ]
        for instruction in positives {
            XCTAssertTrue(
                DeliveryInstructionAdvisor.hasDurationDirective(instruction),
                "expected a duration directive in: \(instruction)"
            )
            XCTAssertNotNil(DeliveryInstructionAdvisor.firstDurationDirective(in: instruction))
        }
    }

    func testStyleAndPauseInstructionsDoNotTrigger() {
        let negatives = [
            "",
            "   ",
            "A calm narrator, warm and measured.",
            "An energetic news anchor, bright and fast.",
            "Whispered, close-mic and breathy",
            "Take a two-second pause between sentences.",
            "Pause briefly after each list item, about 1 second.",
            "Sound like a 30 year old radio host",
            "Emphasize the second sentence strongly.",
            "Un ton doux et posé, comme une berceuse.",
            "Speak slowly and stretch every vowel.",
            "In seconds, the mood shifts — reflect that turn.",
        ]
        for instruction in negatives {
            XCTAssertFalse(
                DeliveryInstructionAdvisor.hasDurationDirective(instruction),
                "unexpected duration directive in: \(instruction)"
            )
        }
    }

    func testFirstMatchIsReturnedForAdvisoryMessaging() {
        let match = DeliveryInstructionAdvisor.firstDurationDirective(
            in: "Cheerful, finish within 20 seconds, then smile."
        )
        XCTAssertEqual(match?.lowercased(), "within 20 seconds")
        XCTAssertFalse(DeliveryInstructionAdvisor.advisoryMessage.isEmpty)
    }
}
