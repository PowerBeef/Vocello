import Foundation
import QwenVoiceCore
import QwenVoiceEngineSupport
import XCTest

final class PreparedVoiceWireContractTests: XCTestCase {
    func testCandidateCommandsRoundTripAtSchemaVersionTwo() throws {
        XCTAssertEqual(QwenVoiceWireSchema.currentVersion, 2)
        let id = UUID()
        let metadata = PreparedVoiceEnrollmentMetadata(
            referenceLanguage: .french,
            transcriptSource: .manual,
            transcriptionEvidenceDigest: String(repeating: "a", count: 64)
        )
        let commands: [EngineCommand] = [
            .preparePreparedVoiceCandidate(
                name: "Review Voice",
                audioPath: "/private/tmp/reference.wav",
                transcript: "Hello",
                replacingVoiceID: "Old Voice"
            ),
            .preparePreparedVoiceCandidateV2(
                name: "Review Voice",
                audioPath: "/private/tmp/reference.wav",
                transcript: "Bonjour",
                enrollmentMetadata: metadata,
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

    func testLegacyCandidateCommandStillDecodesAfterEnrollmentMetadataExtension() throws {
        let command = EngineCommand.preparePreparedVoiceCandidate(
            name: "Legacy Voice",
            audioPath: "/private/tmp/legacy.wav",
            transcript: nil,
            replacingVoiceID: nil
        )
        let data = try EngineServiceCodec.encode(
            EngineRequestEnvelope(id: UUID(), command: command)
        )

        let decoded = try EngineServiceCodec.decode(EngineRequestEnvelope.self, from: data)
        XCTAssertEqual(decoded.command, command)
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
