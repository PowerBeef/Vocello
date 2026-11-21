import Foundation
import QwenVoiceCore

/// The device runner's wire records, also compiled in host policy tests.
/// No UI, model execution, or alternate diagnostic producer lives here.
public enum IOSStartupReliabilityRecord {
    public struct BoundaryResult: Codable, Sendable {
        public let boundary: String
        public let tMS: Int

        public init(boundary: String, tMS: Int) {
            self.boundary = boundary
            self.tMS = tMS
        }
    }

    public struct AttemptResult: Codable, Sendable {
        public let retryAttempt: Int
        public let finishReason: String
        public let requestReceipt: GenerationRequestReceipt
        public let startupTimeline: [BoundaryResult]

        public init(
            retryAttempt: Int,
            finishReason: String,
            requestReceipt: GenerationRequestReceipt,
            startupTimeline: [BoundaryResult]
        ) {
            self.retryAttempt = retryAttempt
            self.finishReason = finishReason
            self.requestReceipt = requestReceipt
            self.startupTimeline = startupTimeline
        }
    }

    public struct OutputDigest: Codable, Sendable {
        public let sha256: String
        public let byteCount: Int
        public let durationSeconds: Double

        public init(sha256: String, byteCount: Int, durationSeconds: Double) {
            self.sha256 = sha256
            self.byteCount = byteCount
            self.durationSeconds = durationSeconds
        }
    }

    public struct PreparationEvidence: Codable, Sendable {
        public let stage: String
        public let sequence: Int
        public let capturedAtUptimeSeconds: Double
        public let mlxActiveMB: Double?
        public let mlxCacheMB: Double?
        public let mlxPeakMB: Double?
        public let metalAllocatedMB: Double?
        public let physicalFootprintMB: Double?
        public let availableHeadroomMB: Double?
        public let hasActiveGeneration: Bool
        public let memoryActionInFlight: Bool
        public let modelOperationInFlight: Bool
        public let generationReservationInFlight: Bool
        public let loadedModelID: String?
        public let engineLifecycle: String
        public let violations: [String]

        public init(
            stage: String,
            sequence: Int,
            capturedAtUptimeSeconds: Double,
            mlxActiveMB: Double?,
            mlxCacheMB: Double?,
            mlxPeakMB: Double?,
            metalAllocatedMB: Double?,
            physicalFootprintMB: Double?,
            availableHeadroomMB: Double?,
            hasActiveGeneration: Bool,
            memoryActionInFlight: Bool,
            modelOperationInFlight: Bool,
            generationReservationInFlight: Bool,
            loadedModelID: String?,
            engineLifecycle: String,
            violations: [String]
        ) {
            self.stage = stage
            self.sequence = sequence
            self.capturedAtUptimeSeconds = capturedAtUptimeSeconds
            self.mlxActiveMB = mlxActiveMB
            self.mlxCacheMB = mlxCacheMB
            self.mlxPeakMB = mlxPeakMB
            self.metalAllocatedMB = metalAllocatedMB
            self.physicalFootprintMB = physicalFootprintMB
            self.availableHeadroomMB = availableHeadroomMB
            self.hasActiveGeneration = hasActiveGeneration
            self.memoryActionInFlight = memoryActionInFlight
            self.modelOperationInFlight = modelOperationInFlight
            self.generationReservationInFlight = generationReservationInFlight
            self.loadedModelID = loadedModelID
            self.engineLifecycle = engineLifecycle
            self.violations = violations
        }
    }

    public struct TakeResult: Codable, Sendable {
        public let takeIndex: Int
        public let takeID: String
        public let generationID: String
        public let status: String
        public let preparation: String
        public let prePreparationStoreWarmState: String
        public let preRequestStoreWarmState: String
        public let preparationEvidence: [PreparationEvidence]
        public let requestReceipt: GenerationRequestReceipt?
        public let attempts: [AttemptResult]
        public let startupTimeline: [BoundaryResult]
        public let failureCode: String?
        public let classification: String
        public let output: OutputDigest?
        public let audioQC: AudioQCReport?
        public let diagnosticArtifacts: [StartupReliabilityArtifactEvidence]
        public let codecReplay: CodecReplayComparison?

        public init(
            takeIndex: Int,
            takeID: String,
            generationID: String,
            status: String,
            preparation: String,
            prePreparationStoreWarmState: String,
            preRequestStoreWarmState: String,
            preparationEvidence: [PreparationEvidence],
            requestReceipt: GenerationRequestReceipt?,
            attempts: [AttemptResult],
            startupTimeline: [BoundaryResult],
            failureCode: String?,
            classification: String,
            output: OutputDigest?,
            audioQC: AudioQCReport?,
            diagnosticArtifacts: [StartupReliabilityArtifactEvidence],
            codecReplay: CodecReplayComparison?
        ) {
            self.takeIndex = takeIndex
            self.takeID = takeID
            self.generationID = generationID
            self.status = status
            self.preparation = preparation
            self.prePreparationStoreWarmState = prePreparationStoreWarmState
            self.preRequestStoreWarmState = preRequestStoreWarmState
            self.preparationEvidence = preparationEvidence
            self.requestReceipt = requestReceipt
            self.attempts = attempts
            self.startupTimeline = startupTimeline
            self.failureCode = failureCode
            self.classification = classification
            self.output = output
            self.audioQC = audioQC
            self.diagnosticArtifacts = diagnosticArtifacts
            self.codecReplay = codecReplay
        }

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
        public func encode(to encoder: Encoder) throws {
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

    public struct CodecReplayComparison: Codable, Sendable {
        public let status: String
        public let failureCode: String?
        public let traceSHA256: String
        public let ranges: [StartupReliabilityCodecFrameRange]
        public let incrementalArtifact: StartupReliabilityArtifactEvidence?
        public let incrementalAudioQC: AudioQCReport?
        public let fullArtifact: StartupReliabilityArtifactEvidence?
        public let fullAudioQC: AudioQCReport?

        public init(
            status: String,
            failureCode: String?,
            traceSHA256: String,
            ranges: [StartupReliabilityCodecFrameRange],
            incrementalArtifact: StartupReliabilityArtifactEvidence?,
            incrementalAudioQC: AudioQCReport?,
            fullArtifact: StartupReliabilityArtifactEvidence?,
            fullAudioQC: AudioQCReport?
        ) {
            self.status = status
            self.failureCode = failureCode
            self.traceSHA256 = traceSHA256
            self.ranges = ranges
            self.incrementalArtifact = incrementalArtifact
            self.incrementalAudioQC = incrementalAudioQC
            self.fullArtifact = fullArtifact
            self.fullAudioQC = fullAudioQC
        }
    }
}
