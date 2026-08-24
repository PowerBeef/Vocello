import CryptoKit
import Foundation

public enum GenerationStartupBoundary: String, CaseIterable, Codable, Hashable, Sendable {
    case requestValidated = "request_validated"
    case memoryAdmitted = "memory_admitted"
    case modelLoadStarted = "model_load_started"
    case modelLoaded = "model_loaded"
    case prewarmStarted = "prewarm_started"
    case prewarmCompleted = "prewarm_completed"
    case generationReserved = "generation_reserved"
    case audioConsumerClaimed = "audio_consumer_claimed"
    case sessionDirectoryCreated = "session_directory_created"
    case engineOpened = "engine_opened"
    case firstModelToken = "first_model_token"
    case firstAudioCodeGroup = "first_audio_code_group"
    case firstDecodedAudioFrame = "first_decoded_audio_frame"
    case firstPublishedStreamChunk = "first_published_stream_chunk"

    public var telemetryStage: String { "startup.\(rawValue)" }
}

public struct GenerationRequestReceipt: Hashable, Codable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let generationID: String
    public let generationIdentityDigest: String
    public let requestIdentityDigest: String
    public let sessionIdentityDigest: String
    public let prewarmIdentityDigest: String
    public let modelID: String
    public let speakerID: String?
    public let deliveryID: String?
    public let instructionDigest: String?
    public let instructionCharacters: Int
    public let language: String
    public let seed: UInt64
    public let seedSource: String
    public let variation: String
    public let streaming: Bool
    public let warmState: EngineWarmState
    public let predecessorIdentityDigest: String?
    public let retryAttempt: Int
    public let operationGeneration: UInt64

    public init(
        request: GenerationRequest,
        generationID: UUID,
        effectiveSeed: UInt64,
        warmState: EngineWarmState,
        predecessorIdentityDigest: String?,
        retryAttempt: Int,
        operationGeneration: UInt64
    ) {
        let instruction = request.payload.deliveryInstructionText?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let speakerID: String? = {
            guard case .custom(let speaker, _) = request.payload else { return nil }
            return speaker.trimmingCharacters(in: .whitespacesAndNewlines)
        }()
        let instructionDigest = instruction.flatMap { value in
            value.isEmpty ? nil : Self.sha256(value)
        }
        let deliveryID = instruction.flatMap { value -> String? in
            guard let match = EmotionPreset.matchInstruction(value) else { return nil }
            return "\(match.preset.id).\(match.intensity.rpcValue)"
        }
        let language = GenerationSemantics.qwenLanguageHint(for: request)
        let sessionIdentityDigest = GenerationSemantics.generationSessionIdentity(for: request).digest
        let prewarmIdentityDigest = GenerationSemantics.prewarmIdentity(for: request).digest
        let promptDigest = Self.sha256(request.text)
        let variation = (request.variation ?? .expressive).rawValue
        let requestSerialization = Self.lengthFramed([
            request.modelID,
            request.mode.rawValue,
            promptDigest,
            String(request.text.count),
            speakerID ?? "",
            deliveryID ?? "",
            instructionDigest ?? "",
            language,
            String(effectiveSeed),
            variation,
            request.shouldStream ? "streaming" : "quality-first",
        ])

        self.schemaVersion = Self.currentSchemaVersion
        self.generationID = generationID.uuidString
        self.generationIdentityDigest = Self.sha256(generationID.uuidString.lowercased())
        self.requestIdentityDigest = Self.sha256(requestSerialization)
        self.sessionIdentityDigest = sessionIdentityDigest
        self.prewarmIdentityDigest = prewarmIdentityDigest
        self.modelID = request.modelID
        self.speakerID = speakerID
        self.deliveryID = deliveryID
        self.instructionDigest = instructionDigest
        self.instructionCharacters = instruction?.count ?? 0
        self.language = language
        self.seed = effectiveSeed
        self.seedSource = request.seed == nil ? "generated" : "requested"
        self.variation = variation
        self.streaming = request.shouldStream
        self.warmState = warmState
        self.predecessorIdentityDigest = Self.validatedDigest(predecessorIdentityDigest)
        self.retryAttempt = max(0, retryAttempt)
        self.operationGeneration = operationGeneration
    }

    private static func validatedDigest(_ value: String?) -> String? {
        guard let value = value?.lowercased(),
              value.count == 64,
              value.allSatisfy({ $0.isHexDigit }) else { return nil }
        return value
    }

    private static func lengthFramed(_ components: [String]) -> String {
        components.map { "\($0.utf8.count):\($0)" }.joined()
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
