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
    public static let currentSchemaVersion = 2

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
    /// Routing/provenance vocabulary retained for compatibility
    /// (`english`, `mandarin`, or caller-supplied `verbatim`).
    public let instructionLanguage: String?
    /// Natural language detected from the exact fully assembled instruction.
    public let modelFacingInstructionLanguage: String?
    /// The language value retained by the UI/request before target-text
    /// resolution. `auto` remains distinct from the model-facing language.
    public let storedLanguageSelection: String?
    public let detectedTargetLanguage: String?
    public let referenceTranscriptLanguage: String?
    /// Compatibility field retained for v1 consumers. It is the exact
    /// model-facing output language, never the reference language.
    public let language: String
    public let finalModelLanguage: String?
    public let languageTokenMode: String?
    public let conditioningMode: String?
    public let normalizedTargetTextDigest: String?
    public let normalizedTargetTextCharacters: Int?
    public let referenceTranscriptDigest: String?
    public let referenceTranscriptCharacters: Int?
    public let referenceAudioDigest: String?
    public let modelArtifactVersion: String?
    public let modelIntegrityManifestDigest: String?
    public let speechTokenizerDigest: String?
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
        resolvedInstruction: String? = nil,
        instructionLanguage: DeliveryInstructionLanguage? = nil,
        modelFacingText: String? = nil,
        modelFacingLanguage: String? = nil,
        conditioningMode: String? = nil,
        referenceTranscript: String? = nil,
        referenceAudioDigest: String? = nil,
        modelRuntimeIdentity: ModelRuntimeIdentity? = nil,
        generationID: UUID,
        effectiveSeed: UInt64,
        warmState: EngineWarmState,
        predecessorIdentityDigest: String?,
        retryAttempt: Int,
        operationGeneration: UInt64
    ) {
        let instruction = (resolvedInstruction ?? request.payload.deliveryInstructionText)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let speakerID: String? = {
            guard case .custom(let speaker, _) = request.payload else { return nil }
            return speaker.trimmingCharacters(in: .whitespacesAndNewlines)
        }()
        let instructionDigest = instruction.flatMap { value in
            value.isEmpty ? nil : Self.sha256(value)
        }
        // A raw string that happens to equal current preset copy is still raw.
        // Only the explicit wire-compatible context can grant canonical cell
        // identity or authorize localization.
        let deliveryID = request.deliveryInstructionCellID
        let normalizedTargetText = (modelFacingText ?? request.text)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let language = (modelFacingLanguage ?? GenerationSemantics.qwenLanguageHint(for: request))
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let storedLanguageSelection = Qwen3SupportedLanguage
            .normalized(request.languageHint ?? Qwen3SupportedLanguage.auto.rawValue)
            .rawValue
        let detectedTarget = PromptLanguageDetector.detect(normalizedTargetText)
        let normalizedReferenceTranscript: String? = {
            guard let referenceTranscript else { return nil }
            let trimmed = referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }()
        let detectedReference = normalizedReferenceTranscript.map(PromptLanguageDetector.detect)
        let detectedInstruction: Qwen3SupportedLanguage? = instruction.map(
            PromptLanguageDetector.detect
        )
        let resolvedConditioningMode = conditioningMode ?? Self.conditioningMode(
            for: request,
            referenceTranscript: normalizedReferenceTranscript
        )
        let sessionIdentityDigest = GenerationSemantics.generationSessionIdentity(
            for: request,
            resolvedCustomInstruction: instruction
        ).digest
        let prewarmIdentityDigest = GenerationSemantics.prewarmIdentity(
            for: request,
            resolvedCustomInstruction: instruction
        ).digest
        let promptDigest = Self.sha256(normalizedTargetText)
        let variation = (request.variation ?? .expressive).rawValue
        let requestSerialization = Self.lengthFramed([
            request.modelID,
            request.mode.rawValue,
            promptDigest,
            String(normalizedTargetText.count),
            speakerID ?? "",
            deliveryID ?? "",
            instructionDigest ?? "",
            instructionLanguage?.rawValue ?? "",
            language,
            resolvedConditioningMode,
            normalizedReferenceTranscript.map(Self.sha256) ?? "",
            referenceAudioDigest ?? "",
            modelRuntimeIdentity?.speechTokenizerDigest ?? "",
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
        self.instructionLanguage = instructionLanguage?.rawValue
        self.modelFacingInstructionLanguage = detectedInstruction == .auto
            ? nil
            : detectedInstruction?.rawValue
        self.storedLanguageSelection = storedLanguageSelection
        self.detectedTargetLanguage = detectedTarget == .auto ? nil : detectedTarget.rawValue
        self.referenceTranscriptLanguage = detectedReference == .auto
            ? nil
            : detectedReference?.rawValue
        self.language = language
        self.finalModelLanguage = language
        self.languageTokenMode = language == Qwen3SupportedLanguage.auto.rawValue
            ? "nothink"
            : "think"
        self.conditioningMode = resolvedConditioningMode
        self.normalizedTargetTextDigest = promptDigest
        self.normalizedTargetTextCharacters = normalizedTargetText.count
        self.referenceTranscriptDigest = normalizedReferenceTranscript.map(Self.sha256)
        self.referenceTranscriptCharacters = normalizedReferenceTranscript?.count ?? 0
        self.referenceAudioDigest = Self.validatedDigest(referenceAudioDigest)
        self.modelArtifactVersion = modelRuntimeIdentity?.artifactVersion
        self.modelIntegrityManifestDigest = Self.validatedDigest(
            modelRuntimeIdentity?.integrityManifestDigest
        )
        self.speechTokenizerDigest = Self.validatedDigest(
            modelRuntimeIdentity?.speechTokenizerDigest
        )
        self.seed = effectiveSeed
        self.seedSource = request.seed == nil ? "generated" : "requested"
        self.variation = variation
        self.streaming = request.shouldStream
        self.warmState = warmState
        self.predecessorIdentityDigest = Self.validatedDigest(predecessorIdentityDigest)
        self.retryAttempt = max(0, retryAttempt)
        self.operationGeneration = operationGeneration
    }

    private static func conditioningMode(
        for request: GenerationRequest,
        referenceTranscript: String?
    ) -> String {
        switch request.payload {
        case .custom:
            return "custom_voice"
        case .design:
            return "voice_design"
        case .clone:
            return referenceTranscript == nil ? "clone_audio_only" : "clone_transcript_backed"
        }
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
