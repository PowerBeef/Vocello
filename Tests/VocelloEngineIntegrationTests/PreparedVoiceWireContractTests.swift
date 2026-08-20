import Foundation
import QwenVoiceCore
import QwenVoiceEngineSupport
import XCTest

final class PreparedVoiceWireContractTests: XCTestCase {
    func testCandidateCommandsRoundTripAtSchemaVersionTwo() throws {
        XCTAssertEqual(QwenVoiceWireSchema.currentVersion, 2)
        let id = UUID()
        let commands: [EngineCommand] = [
            .preparePreparedVoiceCandidate(
                name: "Review Voice",
                audioPath: "/private/tmp/reference.wav",
                transcript: "Hello",
                replacingVoiceID: "Old Voice"
            ),
            .commitPreparedVoiceCandidate(id: id),
            .discardPreparedVoiceCandidate(id: id),
        ]

        for command in commands {
            let envelope = EngineRequestEnvelope(id: UUID(), command: command)
            let data = try EngineServiceCodec.encode(envelope)
            let decoded = try EngineServiceCodec.decode(EngineRequestEnvelope.self, from: data)
            XCTAssertEqual(decoded.schemaVersion, 2)
            XCTAssertEqual(decoded.command, command)
        }
    }

    func testCandidateReplyRoundTripsWithoutExposingStagedPath() throws {
        let candidate = PreparedVoiceCandidate(
            id: UUID(),
            name: "Review Voice",
            hasTranscript: true,
            qualityWarnings: ["reference_duration_short"]
        )
        let envelope = EngineReplyEnvelope(
            id: UUID(),
            reply: .preparedVoiceCandidate(candidate)
        )

        let data = try EngineServiceCodec.encode(envelope)
        let decoded = try EngineServiceCodec.decode(EngineReplyEnvelope.self, from: data)

        XCTAssertEqual(decoded.reply, .preparedVoiceCandidate(candidate))
        XCTAssertFalse(String(decoding: data, as: UTF8.self).contains("voice-candidates"))
    }

    func testPreviousWireSchemaFailsClosed() throws {
        let envelope = EngineRequestEnvelope(
            id: UUID(),
            command: .ping,
            schemaVersion: 1
        )
        let data = try EngineServiceCodec.encode(envelope)

        XCTAssertThrowsError(
            try EngineServiceCodec.decode(EngineRequestEnvelope.self, from: data)
        )
    }
}
