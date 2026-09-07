import Foundation
import QwenVoiceCore

/// The device runner's wire records, also compiled in host policy tests.
/// No UI, model execution, or alternate diagnostic producer lives here.
enum IOSStartupReliabilityRecord {
    struct BoundaryResult: Codable {
        let boundary: String
        let tMS: Int
    }

    struct AttemptResult: Codable {
        let retryAttempt: Int
        let finishReason: String
        let requestReceipt: GenerationRequestReceipt
        let startupTimeline: [BoundaryResult]
    }

    struct OutputDigest: Codable {
        let sha256: String
        let byteCount: Int
        let durationSeconds: Double
    }

    struct PreparationEvidence: Codable {
        let stage: String
        let sequence: Int
        let capturedAtUptimeSeconds: Double
        let mlxActiveMB: Double?
        let mlxCacheMB: Double?
        let mlxPeakMB: Double?
        let metalAllocatedMB: Double?
        let physicalFootprintMB: Double?
        let availableHeadroomMB: Double?
        let hasActiveGeneration: Bool
        let memoryActionInFlight: Bool
        let modelOperationInFlight: Bool
        let generationReservationInFlight: Bool
        let loadedModelID: String?
        let engineLifecycle: String
        let violations: [String]
    }

    struct TakeResult: Codable {
        let takeIndex: Int
        let takeID: String
        let generationID: String
        let status: String
        let preparation: String
        let prePreparationStoreWarmState: String
        let preRequestStoreWarmState: String
        let preparationEvidence: [PreparationEvidence]
        let requestReceipt: GenerationRequestReceipt?
        let attempts: [AttemptResult]
        let startupTimeline: [BoundaryResult]
        let failureCode: String?
        let classification: String
        let output: OutputDigest?
        let audioQC: AudioQCReport?
        let diagnosticArtifacts: [StartupReliabilityArtifactEvidence]
        let codecReplay: CodecReplayComparison?

        private enum CodingKeys: String, CodingKey {
            case takeIndex
            case takeID
            case generationID
            case status
            case preparation
            case prePreparationStoreWarmState
            case preRequestStoreWarmState
            case preparationEvidence
            case requestReceipt
            case attempts
            case startupTimeline
            case failureCode
            case classification
            case output
            case audioQC
            case diagnosticArtifacts
            case codecReplay
        }

        // v2 requires this nullable key even when generation stopped before QC.
        // Synthesized decoding still reads historical records that omitted it.
        func encode(to encoder: Encoder) throws {
            var values = encoder.container(keyedBy: CodingKeys.self)
            try values.encode(takeIndex, forKey: .takeIndex)
            try values.encode(takeID, forKey: .takeID)
            try values.encode(generationID, forKey: .generationID)
            try values.encode(status, forKey: .status)
            try values.encode(preparation, forKey: .preparation)
            try values.encode(prePreparationStoreWarmState, forKey: .prePreparationStoreWarmState)
            try values.encode(preRequestStoreWarmState, forKey: .preRequestStoreWarmState)
            try values.encode(preparationEvidence, forKey: .preparationEvidence)
            try values.encodeIfPresent(requestReceipt, forKey: .requestReceipt)
            try values.encode(attempts, forKey: .attempts)
            try values.encode(startupTimeline, forKey: .startupTimeline)
            try values.encodeIfPresent(failureCode, forKey: .failureCode)
            try values.encode(classification, forKey: .classification)
            try values.encodeIfPresent(output, forKey: .output)
            try values.encode(audioQC, forKey: .audioQC)
            try values.encode(diagnosticArtifacts, forKey: .diagnosticArtifacts)
            try values.encodeIfPresent(codecReplay, forKey: .codecReplay)
        }
    }

    struct CodecReplayComparison: Codable {
        let status: String
        let failureCode: String?
        let traceSHA256: String
        let ranges: [StartupReliabilityCodecFrameRange]
        let incrementalArtifact: StartupReliabilityArtifactEvidence?
        let incrementalAudioQC: AudioQCReport?
        let fullArtifact: StartupReliabilityArtifactEvidence?
        let fullAudioQC: AudioQCReport?
    }
}
