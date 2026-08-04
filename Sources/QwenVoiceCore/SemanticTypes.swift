import Foundation

public enum GenerationMode: String, CaseIterable, Codable, Hashable, Sendable {
    case custom
    case design
    case clone

    public var displayName: String {
        switch self {
        case .custom:
            return "Custom Voice"
        case .design:
            return "Voice Design"
        case .clone:
            return "Voice Cloning"
        }
    }

    public var iconName: String {
        switch self {
        case .custom:
            return "person.wave.2"
        case .design:
            return "text.bubble"
        case .clone:
            return "waveform.badge.plus"
        }
    }
}

public enum Qwen3SupportedLanguage: String, CaseIterable, Codable, Hashable, Sendable {
    case auto
    case chinese
    case english
    case japanese
    case korean
    case german
    case french
    case russian
    case portuguese
    case spanish
    case italian

    public var displayName: String {
        switch self {
        case .auto: return "Auto"
        case .chinese: return "Chinese"
        case .english: return "English"
        case .japanese: return "Japanese"
        case .korean: return "Korean"
        case .german: return "German"
        case .french: return "French"
        case .russian: return "Russian"
        case .portuguese: return "Portuguese"
        case .spanish: return "Spanish"
        case .italian: return "Italian"
        }
    }

    public static var selectableCases: [Qwen3SupportedLanguage] {
        allCases.filter { $0 != .auto }
    }

    public static func normalized(_ raw: String?) -> Qwen3SupportedLanguage {
        let normalized = (raw ?? "")
            .replacingOccurrences(
                of: #"\s+"#,
                with: " ",
                options: .regularExpression
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "_", with: "-")
        switch normalized {
        case "", "auto", "automatic":
            return .auto
        case "zh", "zh-cn", "zh-hans", "cn", "mandarin", "chinese":
            return .chinese
        case "en", "en-us", "en-gb", "english":
            return .english
        case "ja", "jp", "japanese":
            return .japanese
        case "ko", "kr", "korean":
            return .korean
        case "de", "de-de", "german":
            return .german
        case "fr", "fr-fr", "french":
            return .french
        case "ru", "ru-ru", "russian":
            return .russian
        case "pt", "pt-br", "pt-pt", "portuguese":
            return .portuguese
        case "es", "es-es", "spanish":
            return .spanish
        case "it", "it-it", "italian":
            return .italian
        default:
            return .auto
        }
    }

    public static func nativeLanguage(_ raw: String?) -> Qwen3SupportedLanguage {
        let normalized = normalized(raw)
        return normalized == .auto ? .english : normalized
    }
}

public enum EngineActivityLabels {
    public static let preparingVoiceReference = "Preparing voice reference…"

    public static func generating(mode: GenerationMode) -> String {
        "Generating \(mode.displayName)…"
    }
}

public enum EngineImplementationKind: String, Codable, Hashable, Sendable {
    case nativeMLX
}

public enum EngineRoutingPolicy: String, Codable, Hashable, Sendable {
    case nativeDefault
    case nativeOnly
}

public enum EngineWarmState: String, Codable, Hashable, Sendable {
    case cold
    case warm
}

public enum GenerationSupportDecision: Hashable, Codable, Sendable {
    case supported(EngineImplementationKind)
    case unsupported(reason: String)

    public var implementationKind: EngineImplementationKind? {
        switch self {
        case .supported(let kind):
            return kind
        case .unsupported:
            return nil
        }
    }

    public var unsupportedReason: String? {
        switch self {
        case .supported:
            return nil
        case .unsupported(let reason):
            return reason
        }
    }

    public var isSupported: Bool {
        implementationKind != nil
    }
}

public struct SpeakerMetadata: Hashable, Codable, Sendable {
    public let displayName: String
    public let nativeLanguage: String
    public let shortDescription: String
    public let isEnglishNative: Bool

    public init(
        displayName: String,
        nativeLanguage: String,
        shortDescription: String,
        isEnglishNative: Bool
    ) {
        self.displayName = displayName
        self.nativeLanguage = nativeLanguage
        self.shortDescription = shortDescription
        self.isEnglishNative = isEnglishNative
    }
}

public struct SpeakerDescriptor: Identifiable, Hashable, Codable, Sendable {
    public let group: String
    public let id: String
    public let metadata: SpeakerMetadata?

    public init(group: String, id: String, metadata: SpeakerMetadata? = nil) {
        self.group = group
        self.id = id
        self.metadata = metadata
    }

    public var displayName: String {
        metadata?.displayName ?? id.capitalized
    }

    public var nativeLanguage: String? {
        metadata?.nativeLanguage
    }

    public var shortDescription: String? {
        metadata?.shortDescription
    }

    public var isEnglishNative: Bool {
        metadata?.isEnglishNative ?? false
    }

    public var annotatedDisplayName: String {
        guard let nativeLanguage,
              !nativeLanguage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return displayName
        }
        return "\(displayName) - \(nativeLanguage) native"
    }
}

public enum ModelArtifactPlatform: String, Codable, Hashable, Sendable {
    case macOS
    case iOS
}

public enum ModelVariantKind: String, Codable, Hashable, Sendable {
    case compactSpeed = "compact_speed"
    case compactQuality = "compact_quality"
    case speed
    case quality
}

public enum Qwen3TTSModelSize: String, Hashable, Sendable {
    case compact0b6 = "compact0b6"
    case pro1b7 = "pro1b7"
}

extension Qwen3TTSModelSize: Codable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let rawValue = try container.decode(String.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        switch rawValue {
        case "compact0b6", "0b6", "0.6b", "600m":
            self = .compact0b6
        case "pro1b7", "1b7", "1.7b":
            self = .pro1b7
        default:
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported Qwen3-TTS model size '\(rawValue)'."
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

public enum Qwen3TTSFamilyType: String, Codable, Hashable, Sendable {
    case customVoice = "custom_voice"
    case voiceDesign = "voice_design"
    case baseClone = "base_clone"
}

public enum Qwen3TTSArtifactAvailability: String, Codable, Hashable, Sendable {
    case publicArtifact = "public_artifact"
    case researchOnly = "research_only"
    case unsupported
}

public struct Qwen3TTSTokenizerProfile: Hashable, Codable, Sendable {
    public let name: String
    public let sampleRateHz: Int
    public let frameRateHz: Double
    public let decoderQuantizers: Int
    public let encoderValidQuantizers: Int
    public let encoderConfiguredQuantizers: Int?
    public let codebookSize: Int
    public let semanticCodebookSize: Int

    public init(
        name: String,
        sampleRateHz: Int,
        frameRateHz: Double,
        decoderQuantizers: Int,
        encoderValidQuantizers: Int,
        encoderConfiguredQuantizers: Int?,
        codebookSize: Int,
        semanticCodebookSize: Int
    ) {
        self.name = name
        self.sampleRateHz = sampleRateHz
        self.frameRateHz = frameRateHz
        self.decoderQuantizers = decoderQuantizers
        self.encoderValidQuantizers = encoderValidQuantizers
        self.encoderConfiguredQuantizers = encoderConfiguredQuantizers
        self.codebookSize = codebookSize
        self.semanticCodebookSize = semanticCodebookSize
    }
}

public enum Qwen3TTSGenerationDefaultSource: String, Codable, Hashable, Sendable {
    case checkpoint = "checkpoint"
    case wrapperFallback = "wrapper_fallback"
    case appPolicy = "app_policy"
}

public struct Qwen3TTSGenerationDefaultsProfile: Hashable, Codable, Sendable {
    public let checkpointMaxNewTokens: Int?
    public let wrapperFallbackMaxNewTokens: Int
    public let appPolicyMaxNewTokens: Int
    public let temperature: Double
    public let topP: Double
    public let topK: Int
    public let doSample: Bool
    public let repetitionPenalty: Double
    public let source: Qwen3TTSGenerationDefaultSource

    public init(
        checkpointMaxNewTokens: Int?,
        wrapperFallbackMaxNewTokens: Int,
        appPolicyMaxNewTokens: Int,
        temperature: Double,
        topP: Double,
        topK: Int,
        doSample: Bool,
        repetitionPenalty: Double,
        source: Qwen3TTSGenerationDefaultSource
    ) {
        self.checkpointMaxNewTokens = checkpointMaxNewTokens
        self.wrapperFallbackMaxNewTokens = wrapperFallbackMaxNewTokens
        self.appPolicyMaxNewTokens = appPolicyMaxNewTokens
        self.temperature = temperature
        self.topP = topP
        self.topK = topK
        self.doSample = doSample
        self.repetitionPenalty = repetitionPenalty
        self.source = source
    }
}

public struct Qwen3TTSModelCapabilities: Hashable, Codable, Sendable {
    public let modelSize: Qwen3TTSModelSize
    public let familyType: Qwen3TTSFamilyType
    public let supportsInstructionControl: Bool
    public let supportsVoiceClone: Bool
    public let supportsXVectorOnlyClone: Bool
    public let requiresSpeakerEncoder: Bool
    public let tokenizerProfile: Qwen3TTSTokenizerProfile
    public let generationDefaults: Qwen3TTSGenerationDefaultsProfile
    public let artifactAvailability: Qwen3TTSArtifactAvailability

    public init(
        modelSize: Qwen3TTSModelSize,
        familyType: Qwen3TTSFamilyType,
        supportsInstructionControl: Bool,
        supportsVoiceClone: Bool,
        supportsXVectorOnlyClone: Bool,
        requiresSpeakerEncoder: Bool,
        tokenizerProfile: Qwen3TTSTokenizerProfile,
        generationDefaults: Qwen3TTSGenerationDefaultsProfile,
        artifactAvailability: Qwen3TTSArtifactAvailability
    ) {
        self.modelSize = modelSize
        self.familyType = familyType
        self.supportsInstructionControl = supportsInstructionControl
        self.supportsVoiceClone = supportsVoiceClone
        self.supportsXVectorOnlyClone = supportsXVectorOnlyClone
        self.requiresSpeakerEncoder = requiresSpeakerEncoder
        self.tokenizerProfile = tokenizerProfile
        self.generationDefaults = generationDefaults
        self.artifactAvailability = artifactAvailability
    }
}

public struct ModelVariantDescriptor: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public let name: String
    public let kind: ModelVariantKind
    public let platforms: Set<ModelArtifactPlatform>
    public let folder: String
    public let huggingFaceRepo: String
    public let huggingFaceRevision: String?
    public let artifactVersion: String
    public let iosDownloadEligible: Bool
    public let estimatedDownloadBytes: Int64?
    public let requiredRelativePaths: [String]
    public let qwen3Capabilities: Qwen3TTSModelCapabilities?

    public init(
        id: String,
        name: String,
        kind: ModelVariantKind,
        platforms: Set<ModelArtifactPlatform>,
        folder: String,
        huggingFaceRepo: String,
        huggingFaceRevision: String? = nil,
        artifactVersion: String,
        iosDownloadEligible: Bool,
        estimatedDownloadBytes: Int64?,
        requiredRelativePaths: [String],
        qwen3Capabilities: Qwen3TTSModelCapabilities? = nil
    ) {
        self.id = id
        self.name = name
        self.kind = kind
        self.platforms = platforms
        self.folder = folder
        self.huggingFaceRepo = huggingFaceRepo
        self.huggingFaceRevision = huggingFaceRevision
        self.artifactVersion = artifactVersion
        self.iosDownloadEligible = iosDownloadEligible
        self.estimatedDownloadBytes = estimatedDownloadBytes
        self.requiredRelativePaths = requiredRelativePaths
        self.qwen3Capabilities = qwen3Capabilities
    }
}

public struct ModelDescriptor: Identifiable, Hashable, Sendable, Codable {
    public let id: String
    public let name: String
    public let tier: String
    public let folder: String
    public let mode: GenerationMode
    public let huggingFaceRepo: String
    public let huggingFaceRevision: String?
    public let artifactVersion: String
    public let iosDownloadEligible: Bool
    public let estimatedDownloadBytes: Int64?
    public let outputSubfolder: String
    public let requiredRelativePaths: [String]
    public let variants: [ModelVariantDescriptor]
    public let qwen3Capabilities: Qwen3TTSModelCapabilities?

    public init(
        id: String,
        name: String,
        tier: String,
        folder: String,
        mode: GenerationMode,
        huggingFaceRepo: String,
        huggingFaceRevision: String? = nil,
        artifactVersion: String,
        iosDownloadEligible: Bool,
        estimatedDownloadBytes: Int64?,
        outputSubfolder: String,
        requiredRelativePaths: [String],
        variants: [ModelVariantDescriptor] = [],
        qwen3Capabilities: Qwen3TTSModelCapabilities? = nil
    ) {
        self.id = id
        self.name = name
        self.tier = tier
        self.folder = folder
        self.mode = mode
        self.huggingFaceRepo = huggingFaceRepo
        self.huggingFaceRevision = huggingFaceRevision
        self.artifactVersion = artifactVersion
        self.iosDownloadEligible = iosDownloadEligible
        self.estimatedDownloadBytes = estimatedDownloadBytes
        self.outputSubfolder = outputSubfolder
        self.requiredRelativePaths = requiredRelativePaths
        self.variants = variants
        self.qwen3Capabilities = qwen3Capabilities
    }

    public func installDirectory(in modelsDirectory: URL) -> URL {
        modelsDirectory.appendingPathComponent(folder, isDirectory: true)
    }

    public func isAvailable(in modelsDirectory: URL, fileManager: FileManager = .default) -> Bool {
        let installDirectory = installDirectory(in: modelsDirectory)
        return requiredRelativePaths.allSatisfy { relativePath in
            fileManager.fileExists(atPath: installDirectory.appendingPathComponent(relativePath).path)
        }
    }

    public var supportsInstructionControl: Bool {
        qwen3Capabilities?.supportsInstructionControl ?? false
    }

    public var supportsVoiceClone: Bool {
        qwen3Capabilities?.supportsVoiceClone ?? (mode == .clone)
    }

    public func platformVariants(for platform: ModelArtifactPlatform) -> [ModelVariantDescriptor] {
        variants.filter { $0.platforms.contains(platform) }
    }

    public func variantScopedID(for variant: ModelVariantDescriptor) -> String {
        "\(id)_\(variant.id)"
    }

    public func preferredVariant(for platform: ModelArtifactPlatform) -> ModelVariantDescriptor? {
        preferredVariant(for: platform, deviceClass: nil)
    }

    public func preferredVariant(
        for platform: ModelArtifactPlatform,
        deviceClass: NativeDeviceMemoryClass?
    ) -> ModelVariantDescriptor? {
        let platformVariants = variants.filter { $0.platforms.contains(platform) }
        guard !platformVariants.isEmpty else { return nil }

        switch platform {
        case .iOS:
            return platformVariants.first(where: { $0.kind == .speed })
                ?? platformVariants.first
        case .macOS:
            if deviceClass == .floor8GBMac {
                return platformVariants.first(where: { $0.kind == .speed })
                    ?? platformVariants.first
            }
            return platformVariants.first(where: { $0.kind == .quality }) ?? platformVariants.first
        }
    }

    public func resolvedForPlatform(_ platform: ModelArtifactPlatform) -> ModelDescriptor {
        resolvedForPlatform(platform, deviceClass: nil)
    }

    public func resolvedForPlatform(
        _ platform: ModelArtifactPlatform,
        deviceClass: NativeDeviceMemoryClass?
    ) -> ModelDescriptor {
        guard let variant = preferredVariant(for: platform, deviceClass: deviceClass) else {
            return self
        }

        return resolved(with: variant, id: id)
    }

    public func resolved(with variant: ModelVariantDescriptor, id resolvedID: String? = nil) -> ModelDescriptor {
        return ModelDescriptor(
            id: resolvedID ?? id,
            name: name,
            tier: tier,
            folder: variant.folder,
            mode: mode,
            huggingFaceRepo: variant.huggingFaceRepo,
            huggingFaceRevision: variant.huggingFaceRevision,
            artifactVersion: variant.artifactVersion,
            iosDownloadEligible: variant.iosDownloadEligible,
            estimatedDownloadBytes: variant.estimatedDownloadBytes,
            outputSubfolder: outputSubfolder,
            requiredRelativePaths: variant.requiredRelativePaths,
            variants: variants,
            qwen3Capabilities: variant.qwen3Capabilities ?? qwen3Capabilities
        )
    }
}

public enum CloneConditioningMode: Hashable, Codable, Sendable {
    case transcriptBacked(String)
    case xVectorOnly

    private enum CodingKeys: String, CodingKey {
        case kind
        case transcript
    }

    private enum Kind: String, Codable {
        case transcriptBacked = "transcript_backed"
        case xVectorOnly = "x_vector_only"
    }

    public init(transcript: String?) {
        let normalized = transcript?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let normalized, !normalized.isEmpty {
            self = .transcriptBacked(normalized)
        } else {
            self = .xVectorOnly
        }
    }

    public var transcript: String? {
        switch self {
        case .transcriptBacked(let transcript):
            let normalized = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
            return normalized.isEmpty ? nil : normalized
        case .xVectorOnly:
            return nil
        }
    }

    public var identifier: String {
        switch normalized {
        case .transcriptBacked:
            return Kind.transcriptBacked.rawValue
        case .xVectorOnly:
            return Kind.xVectorOnly.rawValue
        }
    }

    public var usesTranscript: Bool {
        transcript != nil
    }

    public var isXVectorOnly: Bool {
        !usesTranscript
    }

    public var normalized: CloneConditioningMode {
        switch self {
        case .transcriptBacked(let transcript):
            return CloneConditioningMode(transcript: transcript)
        case .xVectorOnly:
            return .xVectorOnly
        }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        switch try container.decode(Kind.self, forKey: .kind) {
        case .transcriptBacked:
            let transcript = try container.decode(String.self, forKey: .transcript)
            let normalized = CloneConditioningMode(transcript: transcript)
            guard normalized.usesTranscript else {
                throw DecodingError.dataCorruptedError(
                    forKey: .transcript,
                    in: container,
                    debugDescription: "Transcript-backed clone conditioning requires non-empty text."
                )
            }
            self = normalized
        case .xVectorOnly:
            self = .xVectorOnly
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch normalized {
        case .transcriptBacked(let transcript):
            try container.encode(Kind.transcriptBacked, forKey: .kind)
            try container.encode(transcript, forKey: .transcript)
        case .xVectorOnly:
            try container.encode(Kind.xVectorOnly, forKey: .kind)
        }
    }
}

public struct CloneReference: Hashable, Codable, Sendable {
    public let audioPath: String
    public let conditioningMode: CloneConditioningMode
    public let preparedVoiceID: String?

    public init(audioPath: String, transcript: String? = nil, preparedVoiceID: String? = nil) {
        self.audioPath = audioPath
        self.conditioningMode = CloneConditioningMode(transcript: transcript)
        self.preparedVoiceID = preparedVoiceID
    }

    public init(
        audioPath: String,
        conditioningMode: CloneConditioningMode,
        preparedVoiceID: String? = nil
    ) {
        self.audioPath = audioPath
        self.conditioningMode = conditioningMode.normalized
        self.preparedVoiceID = preparedVoiceID
    }

    public var transcript: String? {
        conditioningMode.transcript
    }

    public var audioURL: URL {
        URL(fileURLWithPath: audioPath)
    }

    private enum CodingKeys: String, CodingKey {
        case audioPath
        case transcript
        case conditioningMode
        case preparedVoiceID
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        audioPath = try container.decode(String.self, forKey: .audioPath)
        preparedVoiceID = try container.decodeIfPresent(String.self, forKey: .preparedVoiceID)

        if let decodedMode = try container.decodeIfPresent(
            CloneConditioningMode.self,
            forKey: .conditioningMode
        ) {
            let normalizedMode = decodedMode.normalized
            if container.contains(.transcript) {
                let legacyTranscript = try container.decodeIfPresent(String.self, forKey: .transcript)
                guard CloneConditioningMode(transcript: legacyTranscript) == normalizedMode else {
                    throw DecodingError.dataCorruptedError(
                        forKey: .conditioningMode,
                        in: container,
                        debugDescription: "Clone conditioning mode disagrees with the legacy transcript field."
                    )
                }
            }
            conditioningMode = normalizedMode
        } else {
            conditioningMode = CloneConditioningMode(
                transcript: try container.decodeIfPresent(String.self, forKey: .transcript)
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(audioPath, forKey: .audioPath)
        try container.encode(conditioningMode.normalized, forKey: .conditioningMode)
        try container.encodeIfPresent(transcript, forKey: .transcript)
        try container.encodeIfPresent(preparedVoiceID, forKey: .preparedVoiceID)
    }
}

public struct PreparedVoice: Identifiable, Hashable, Codable, Sendable {
    public let id: String
    public let name: String
    public let audioPath: String
    public let hasTranscript: Bool
    /// Quality observations about the underlying reference audio. Tokens
    /// match the existing `clone_reference_warnings` schema in
    /// `NativeCloneSupport.referenceQualityWarnings(for:)` —
    /// e.g. `reference_duration_short`, `reference_duration_long`,
    /// `reference_quality_unreadable`. Empty when the reference is
    /// within the recommended window (currently 10–20 s).
    /// UI surfaces these as soft warnings during enrollment + as inline
    /// badges in the saved-voices list.
    public let qualityWarnings: [String]

    public init(
        id: String,
        name: String,
        audioPath: String,
        hasTranscript: Bool,
        qualityWarnings: [String] = []
    ) {
        self.id = id
        self.name = name
        self.audioPath = audioPath
        self.hasTranscript = hasTranscript
        self.qualityWarnings = qualityWarnings
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.id = try container.decode(String.self, forKey: .id)
        self.name = try container.decode(String.self, forKey: .name)
        self.audioPath = try container.decode(String.self, forKey: .audioPath)
        self.hasTranscript = try container.decode(Bool.self, forKey: .hasTranscript)
        // Backward-compat: older encoded forms (pre-May 2026) lacked
        // `qualityWarnings`; missing key decodes as empty.
        self.qualityWarnings = try container
            .decodeIfPresent([String].self, forKey: .qualityWarnings) ?? []
    }

    public var audioURL: URL {
        URL(fileURLWithPath: audioPath)
    }

    /// Cached headline for the first warning token. Avoids re-running
    /// the `PreparedVoiceQualityWarning.headline(for:)` lookup every
    /// time the saved-voices list re-renders. Nil when no warnings
    /// (the common case).
    public var qualityHeadline: String? {
        qualityWarnings.first.flatMap(PreparedVoiceQualityWarning.headline(for:))
    }
}

/// Human-readable summaries of `PreparedVoice.qualityWarnings` tokens.
/// Used by enrollment dialogs and library badges across macOS + iOS.
/// Unknown tokens fall through to `nil` so callers can choose whether to
/// display a generic warning line or drop it.
public enum PreparedVoiceQualityWarning {
    /// Tokens whose presence in a voice's `qualityWarnings` array means
    /// the voice cannot be kept — the enrollment UI must remove the
    /// "Keep voice" affordance and force the user to discard or re-pick.
    /// Currently only the >60 s excessive-duration token blocks (matches
    /// Alibaba Cloud Model Studio's 60 s hard cap on the hosted Qwen-TTS
    /// API). Soft-warn tokens are reported but do not block keeping.
    public static let hardBlockingTokens: Set<String> = ["reference_duration_excessive"]

    /// True if any token in the array hits a hard-block tier (currently
    /// just `reference_duration_excessive`). Use this in the enrollment
    /// alert to skip the "Keep voice" button and message the user that
    /// the reference must be replaced.
    public static func isHardBlocking(_ tokens: [String]) -> Bool {
        !Set(tokens).isDisjoint(with: hardBlockingTokens)
    }

    /// Sentence-length explanation. Used in the enrollment alert body
    /// and any place the row has room for full prose.
    public static func headline(for token: String) -> String? {
        switch token {
        case "reference_duration_short":
            return "Reference is shorter than recommended (under 10 seconds)."
        case "reference_duration_long":
            return "Reference is longer than recommended (over 30 seconds)."
        case "reference_duration_excessive":
            return "Reference exceeds the 60 second maximum supported for cloning."
        case "reference_quality_unreadable":
            return "Reference audio could not be read."
        default:
            return nil
        }
    }

    /// Compact 2-3 word label used inside the saved-voice row's
    /// warning chip, where the full sentence wraps awkwardly. Pairs
    /// with `exclamationmark.triangle.fill` + a chevron; the popover
    /// behind the chip carries the full headline + `summary(for:)` body.
    public static func shortLabel(for token: String) -> String? {
        switch token {
        case "reference_duration_short":
            return "Reference too short"
        case "reference_duration_long":
            return "Reference too long"
        case "reference_duration_excessive":
            return "Reference exceeds 60 s"
        case "reference_quality_unreadable":
            return "Reference unreadable"
        default:
            return nil
        }
    }

    /// Multi-line summary suitable for a warning dialog body.
    ///
    /// The 10–20 s recommended window is a product heuristic sourced
    /// from Alibaba Cloud Model Studio's hosted Qwen-TTS API guidance.
    /// Qwen3-TTS itself does not publish a documented degradation
    /// threshold for long references, so the soft-warn wording stays
    /// neutral rather than promising a specific quality cliff. The 60 s
    /// hard cap also mirrors that hosted-API limit — and is enforced
    /// in the enrollment UI by `isHardBlocking(_:)`.
    public static func summary(for tokens: [String]) -> String {
        let lines = tokens.compactMap { headline(for: $0) }
        if lines.isEmpty {
            return "Voice cloning works best with 10–20 seconds of clean speech."
        }
        let trailer = isHardBlocking(tokens)
            ? "Pick a clip that is 60 seconds or shorter to use it for cloning."
            : "Clones from references outside this range still work, but may sound less consistent."
        return "Voice cloning works best with 10–20 seconds of clean speech.\n\n" +
            lines.map { "• \($0)" }.joined(separator: "\n") +
            "\n\n" + trailer
    }
}

public struct AudioPreparationRequest: Hashable, Codable, Sendable {
    public let inputPath: String
    public let outputPath: String?

    public init(inputPath: String, outputPath: String? = nil) {
        self.inputPath = inputPath
        self.outputPath = outputPath
    }
}

public struct NativeMLXMemorySnapshot: Hashable, Codable, Sendable {
    public let activeMB: Double?
    public let cacheMB: Double?
    public let peakMB: Double?

    public init(activeMB: Double?, cacheMB: Double?, peakMB: Double?) {
        self.activeMB = activeMB
        self.cacheMB = cacheMB
        self.peakMB = peakMB
    }
}


public enum NativeLoadCapabilityProfile: String, Hashable, Codable, Sendable {
    case customOnly = "custom_only"
    case designOnly = "design_only"
    case cloneOnly = "clone_only"
    case fullCapabilities = "full_capabilities"

    public init(for request: GenerationRequest) {
        switch request.payload {
        case .custom:
            self = .customOnly
        case .design:
            self = .designOnly
        case .clone:
            self = .cloneOnly
        }
    }

    public func canServe(_ requested: NativeLoadCapabilityProfile) -> Bool {
        self == requested || self == .fullCapabilities
    }
}

public enum NativeDeviceMemoryClass: String, Hashable, Codable, Sendable {
    case floor8GBMac = "floor_8gb_mac"
    case mid16GBMac = "mid_16gb_mac"
    case highMemoryMac = "high_memory_mac"
    case iPhonePro = "iphone_pro"
}

public struct NativeMemoryPolicy: Hashable, Codable, Sendable {
    public let name: String
    public let deviceClass: NativeDeviceMemoryClass
    public let cacheLimitBytes: Int
    public let memoryLimitBytes: Int?
    public let clearCacheAfterGeneration: Bool
    public let clearMLXCacheOnStreamChunkEmit: Bool
    public let mlxTokenMemoryClearCadence: Int
    public let unloadAfterIdleSeconds: Double?

    public init(
        name: String,
        deviceClass: NativeDeviceMemoryClass,
        cacheLimitBytes: Int,
        memoryLimitBytes: Int? = nil,
        clearCacheAfterGeneration: Bool,
        clearMLXCacheOnStreamChunkEmit: Bool = true,
        mlxTokenMemoryClearCadence: Int = 50,
        unloadAfterIdleSeconds: Double?
    ) {
        self.name = name
        self.deviceClass = deviceClass
        self.cacheLimitBytes = cacheLimitBytes
        self.memoryLimitBytes = memoryLimitBytes
        self.clearCacheAfterGeneration = clearCacheAfterGeneration
        self.clearMLXCacheOnStreamChunkEmit = clearMLXCacheOnStreamChunkEmit
        self.mlxTokenMemoryClearCadence = mlxTokenMemoryClearCadence
        self.unloadAfterIdleSeconds = unloadAfterIdleSeconds
    }
}

public enum NativeTelemetryMode: String, Hashable, Codable, Sendable {
    case off
    case lightweight
    /// Same cadence as lightweight, but additionally persists the raw per-sample
    /// memory/timing series to a sidecar for deep memory-curve analysis. Opt-in
    /// only (`QWENVOICE_NATIVE_TELEMETRY_MODE=verbose`) — never the default.
    case verbose

    /// Device-tiered memory-sampling cadence. Finer on roomy Macs where the
    /// sampler's per-tick cost is negligible; coarser on restricted hardware
    /// (8 GB Macs, iPhone) so the background sampler never competes with
    /// generation for CPU/Metal. `off` disables sampling entirely.
    public func sampleIntervalMS(for deviceClass: NativeDeviceMemoryClass) -> Int? {
        switch self {
        case .off:
            return nil
        case .lightweight, .verbose:
            switch deviceClass {
            case .highMemoryMac:
                return 100
            case .mid16GBMac:
                return 250
            case .floor8GBMac, .iPhonePro:
                return 500
            }
        }
    }

    /// Back-compat fixed cadence used only when the device class is unknown.
    public var sampleIntervalMS: Int? {
        switch self {
        case .off:
            return nil
        case .lightweight, .verbose:
            return 250
        }
    }

    /// Whether the raw `[TelemetrySample]` series should be persisted to a sidecar.
    public var persistsRawSamples: Bool { self == .verbose }

    public static func current(environment: [String: String] = ProcessInfo.processInfo.environment) -> NativeTelemetryMode {
        switch environment["QWENVOICE_NATIVE_TELEMETRY_MODE"]?.lowercased() {
        case "off", "disabled":
            return .off
        case "verbose", "full", "deep":
            return .verbose
        case "light", "lightweight":
            return .lightweight
        default:
            // No explicit env mode. In an engine process the app's mode arrives over
            // the IPC handshake (env can't cross the process boundary) — honor it so
            // `verbose` actually reaches the engine. Otherwise follow the master gate.
            if let handshakeMode = TelemetryGate.handshakeResolvedMode {
                return handshakeMode
            }
            return TelemetryGate.resolvedEnabled ? .lightweight : .off
        }
    }
}

public enum NativeStreamingOutputPolicy: String, Hashable, Codable, Sendable {
    case pcmPreview = "pcm_preview"
    case pcmPreviewAndFileArtifacts = "pcm_preview_and_file_artifacts"

    public static func current(environment: [String: String] = ProcessInfo.processInfo.environment) -> NativeStreamingOutputPolicy {
        switch RuntimeDebugGate.value(
            for: "QWENVOICE_STREAMING_OUTPUT_POLICY",
            environment: environment
        )?.lowercased() {
        case "file", "files", "pcm_and_files", "pcm_preview_and_file_artifacts":
            return .pcmPreviewAndFileArtifacts
        default:
            return .pcmPreview
        }
    }
}

/// Opt-out switch for the per-chunk PCM preview Data materialization.
/// Audio files on disk are unaffected; only the in-flight preview data
/// carried by `GenerationEvent.chunk` is controlled here. **Defaults to
/// `.emit` on every platform** — iOS streaming-playback consumes this PCM
/// to play audio live during generation, and the iOS engine runs
/// in-process so the bytes never cross XPC/JSON (the old `.skip` default
/// was a dead-extension-era artifact). Set `QWENVOICE_STREAMING_PREVIEW_DATA=off`
/// to suppress it (e.g. to isolate memory in a benchmark).
public enum NativeStreamingPreviewDataPolicy: String, Hashable, Codable, Sendable {
    case emit
    case skip

    public static func current(environment: [String: String] = ProcessInfo.processInfo.environment) -> NativeStreamingPreviewDataPolicy {
        switch RuntimeDebugGate.value(
            for: "QWENVOICE_STREAMING_PREVIEW_DATA",
            environment: environment
        )?.lowercased() {
        case "on", "emit", "true", "1", "yes":
            return .emit
        case "off", "skip", "false", "0", "no":
            return .skip
        default:
            return .emit
        }
    }
}

public struct StreamingAudioChunk: Hashable, Codable, Sendable {
    public let generationID: UUID?
    public let requestID: Int?
    public let sampleRate: Int
    public let frameOffset: Int64
    public let frameCount: Int
    public let pcm16LE: Data
    public let isFinal: Bool

    public init(
        generationID: UUID? = nil,
        requestID: Int? = nil,
        sampleRate: Int,
        frameOffset: Int64,
        frameCount: Int,
        pcm16LE: Data,
        isFinal: Bool
    ) {
        self.generationID = generationID
        self.requestID = requestID
        self.sampleRate = sampleRate
        self.frameOffset = frameOffset
        self.frameCount = frameCount
        self.pcm16LE = pcm16LE
        self.isFinal = isFinal
    }
}

public struct GenerationSessionKey: Hashable, Codable, Sendable {
    public let modelID: String
    public let variantID: String?
    public let mode: GenerationMode
    public let language: String
    public let speakerOrVoiceDescriptionHash: String?
    public let cloneReferenceHash: String?

    public init(
        modelID: String,
        variantID: String? = nil,
        mode: GenerationMode,
        language: String,
        speakerOrVoiceDescriptionHash: String? = nil,
        cloneReferenceHash: String? = nil
    ) {
        self.modelID = modelID
        self.variantID = variantID
        self.mode = mode
        self.language = language
        self.speakerOrVoiceDescriptionHash = speakerOrVoiceDescriptionHash
        self.cloneReferenceHash = cloneReferenceHash
    }
}

public enum GenerationFinishReason: String, Hashable, Codable, Sendable {
    case eos
    case maxTokens = "max_tokens"
    case cancelled
    case failed
}

/// Why an in-flight generation was asked to stop. This is deliberately
/// separate from failure classification: cancellation is a successful,
/// terminal lifecycle outcome, not an error string that callers must parse.
public enum GenerationCancellationReason: String, Hashable, Codable, Sendable {
    case user
    case memoryPressure = "memory_pressure"
    case superseded
    case shutdown
}

public struct GenerationCancellationSummary: Hashable, Codable, Sendable {
    public let generationID: UUID?
    public let reason: GenerationCancellationReason

    public init(
        generationID: UUID?,
        reason: GenerationCancellationReason
    ) {
        self.generationID = generationID
        self.reason = reason
    }
}

public struct GenerationResult: Hashable, Codable, Sendable {
    public let audioPath: String
    public let durationSeconds: Double
    public let streamSessionDirectory: String?
    public let usedStreaming: Bool
    public let finishReason: GenerationFinishReason?
    public let diagnosticTimingsMS: [String: Int]
    public let diagnosticBooleanFlags: [String: Bool]
    public let diagnosticStringFlags: [String: String]
    /// Headline memory/timing summary rescued from the in-engine telemetry sampler.
    /// Optional + `decodeIfPresent` keeps the IPC wire and persisted history readable
    /// across versions; `nil` when telemetry was off for the run.
    public let telemetrySummary: TelemetrySummary?

    public init(
        audioPath: String,
        durationSeconds: Double,
        streamSessionDirectory: String?,
        usedStreaming: Bool,
        finishReason: GenerationFinishReason? = nil,
        diagnosticTimingsMS: [String: Int] = [:],
        diagnosticBooleanFlags: [String: Bool] = [:],
        diagnosticStringFlags: [String: String] = [:],
        telemetrySummary: TelemetrySummary? = nil
    ) {
        self.audioPath = audioPath
        self.durationSeconds = durationSeconds
        self.streamSessionDirectory = streamSessionDirectory
        self.usedStreaming = usedStreaming
        self.finishReason = finishReason
        self.diagnosticTimingsMS = diagnosticTimingsMS
        self.diagnosticBooleanFlags = diagnosticBooleanFlags
        self.diagnosticStringFlags = diagnosticStringFlags
        self.telemetrySummary = telemetrySummary
    }

    /// The effective sampling seed the engine actually used for this take
    /// (requested or generated), as reported through the diagnostics wire.
    /// This is what a "pin this take's seed" control persists: replaying it
    /// with the same parameters reproduces the take (DP-15).
    public var observedSamplingSeed: UInt64? {
        diagnosticStringFlags["sampling_effective_seed"].flatMap(UInt64.init)
    }

    private enum CodingKeys: String, CodingKey {
        case audioPath
        case durationSeconds
        case streamSessionDirectory
        case usedStreaming
        case finishReason
        case diagnosticTimingsMS
        case diagnosticBooleanFlags
        case diagnosticStringFlags
        case telemetrySummary
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        audioPath = try container.decode(String.self, forKey: .audioPath)
        durationSeconds = try container.decode(Double.self, forKey: .durationSeconds)
        streamSessionDirectory = try container.decodeIfPresent(String.self, forKey: .streamSessionDirectory)
        usedStreaming = try container.decode(Bool.self, forKey: .usedStreaming)
        finishReason = try container.decodeIfPresent(GenerationFinishReason.self, forKey: .finishReason)
        diagnosticTimingsMS = try container.decodeIfPresent([String: Int].self, forKey: .diagnosticTimingsMS) ?? [:]
        diagnosticBooleanFlags = try container.decodeIfPresent([String: Bool].self, forKey: .diagnosticBooleanFlags) ?? [:]
        diagnosticStringFlags = try container.decodeIfPresent([String: String].self, forKey: .diagnosticStringFlags) ?? [:]
        telemetrySummary = try container.decodeIfPresent(TelemetrySummary.self, forKey: .telemetrySummary)
    }

    public var audioURL: URL {
        URL(fileURLWithPath: audioPath)
    }

    public var streamSessionDirectoryURL: URL? {
        guard let streamSessionDirectory else { return nil }
        return URL(fileURLWithPath: streamSessionDirectory)
    }

}

public enum EngineActivityPresentation: String, Hashable, Codable, Sendable {
    case standaloneCard
    case inlinePlayer
}

public struct EngineActivity: Hashable, Codable, Sendable {
    public let label: String
    public let fraction: Double?
    public let presentation: EngineActivityPresentation

    public init(label: String, fraction: Double?, presentation: EngineActivityPresentation) {
        self.label = label
        self.fraction = fraction
        self.presentation = presentation
    }
}

public enum EngineLoadState: Hashable, Codable, Sendable {
    case idle
    case starting
    case loaded(modelID: String)
    case running(modelID: String?, label: String?, fraction: Double?)
    case failed(message: String)

    public var isReady: Bool {
        switch self {
        case .idle, .loaded, .running, .failed:
            return true
        case .starting:
            return false
        }
    }

    public var currentModelID: String? {
        switch self {
        case .loaded(let modelID):
            return modelID
        case .running(let modelID, _, _):
            return modelID
        case .idle, .starting, .failed:
            return nil
        }
    }
}

public enum ClonePreparationPhase: String, Hashable, Codable, Sendable {
    case idle
    case preparing
    case primed
    case failed
}

public struct ClonePreparationState: Hashable, Codable, Sendable {
    public let phase: ClonePreparationPhase
    public let identityKey: String?
    public let message: String?

    public init(
        phase: ClonePreparationPhase,
        identityKey: String? = nil,
        message: String? = nil
    ) {
        self.phase = phase
        self.identityKey = identityKey
        self.message = message
    }

    public static let idle = ClonePreparationState(phase: .idle)

    public static func preparing(key: String?) -> ClonePreparationState {
        ClonePreparationState(phase: .preparing, identityKey: key)
    }

    public static func primed(key: String?) -> ClonePreparationState {
        ClonePreparationState(phase: .primed, identityKey: key)
    }

    public static func failed(key: String?, message: String?) -> ClonePreparationState {
        ClonePreparationState(phase: .failed, identityKey: key, message: message)
    }

    public var key: String? {
        identityKey
    }

    public var errorMessage: String? {
        phase == .failed ? message : nil
    }

    public var isPreparingOrPrimed: Bool {
        phase == .preparing || phase == .primed
    }

    public var isPrimed: Bool {
        phase == .primed
    }
}

public enum CloneReferenceContextResolution: Hashable, Sendable {
    case waitingForHydration
    case preparing
    case primed
    case usableWithoutPriming
    case degraded(String)
}

public enum CloneReferenceContextResolver {
    public static let defaultDegradedMessage =
        "Reference prep didn't finish. Generation is still available, but the first generation may be slower."

    public static func resolve(
        hasReference: Bool,
        selectedSavedVoiceID: String?,
        hydratedSavedVoiceID: String?,
        transcriptLoadError: String?,
        expectedPreparationKey: String?,
        preparationState: ClonePreparationState
    ) -> CloneReferenceContextResolution? {
        guard hasReference else { return nil }

        if let selectedSavedVoiceID,
           hydratedSavedVoiceID != selectedSavedVoiceID,
           transcriptLoadError == nil {
            return .waitingForHydration
        }

        guard let expectedPreparationKey else {
            return .usableWithoutPriming
        }

        guard preparationState.key == expectedPreparationKey else {
            return .usableWithoutPriming
        }

        switch preparationState.phase {
        case .idle:
            return .usableWithoutPriming
        case .preparing:
            return .preparing
        case .primed:
            return .primed
        case .failed:
            return .degraded(preparationState.errorMessage ?? defaultDegradedMessage)
        }
    }
}

/// User-facing sampling variation for a generation (GitHub #47). Maps to
/// talker temperature/top-p in the engine: `expressive` is the official
/// checkpoint default (most take-to-take variety); the other two trade
/// liveliness for consistency across regenerations. Note from the 2026-06-11
/// listening A/Bs: official defaults sounded best — this is a consistency
/// control, not a quality ladder, and `expressive` stays the default.
public enum Qwen3SamplingVariation: String, Codable, Hashable, Sendable, CaseIterable {
    case expressive
    case balanced
    case consistent

    public var displayName: String {
        switch self {
        case .expressive: return "Expressive"
        case .balanced: return "Balanced"
        case .consistent: return "Consistent"
        }
    }
}

public struct GenerationRequest: Hashable, Codable, Sendable {
    public enum Payload: Hashable, Codable, Sendable {
        case custom(speakerID: String, deliveryStyle: String?)
        case design(voiceDescription: String, deliveryStyle: String?)
        case clone(reference: CloneReference)
    }

    public let mode: GenerationMode
    public let modelID: String
    public let text: String
    public let outputPath: String
    public let shouldStream: Bool
    public let streamingInterval: Double?
    public let batchIndex: Int?
    public let batchTotal: Int?
    public let streamingTitle: String?
    public let languageHint: String?
    public let payload: Payload
    /// App-minted correlation key. Threaded down so the engine reuses it
    /// (`NativeEngineRuntime`) and app/middle/engine telemetry rows join.
    /// Optional + synthesized `Codable` keeps the IPC wire back-compatible.
    public let generationID: UUID?
    /// Deterministic-sampling seed. When set, the engine creates a request-local
    /// MLX random state before decoding, so the same request + sampling-policy
    /// version + seed reproduces the same take ("regenerate exactly";
    /// stabilizes batches). Unseeded requests receive a recorded effective seed.
    /// Optional + synthesized `Codable` keeps the IPC wire back-compatible.
    /// (GitHub #47/#30)
    public let seed: UInt64?
    /// Sampling variation (talker temperature/top-p shaping). nil/expressive
    /// = official defaults. Wire-back-compatible like `seed`.
    public let variation: Qwen3SamplingVariation?
    /// Long-form v4 segments stream for flat memory but must not publish live
    /// preview audio to the frontend. `true` keeps streaming execution while
    /// suppressing preview-chunk publication. Optional + synthesized `Codable`
    /// keeps the IPC wire back-compatible.
    public let suppressStreamingPreview: Bool?

    public init(
        mode: GenerationMode,
        modelID: String,
        text: String,
        outputPath: String,
        shouldStream: Bool,
        streamingInterval: Double? = nil,
        batchIndex: Int? = nil,
        batchTotal: Int? = nil,
        streamingTitle: String? = nil,
        languageHint: String? = nil,
        payload: Payload,
        generationID: UUID? = nil,
        seed: UInt64? = nil,
        variation: Qwen3SamplingVariation? = nil,
        suppressStreamingPreview: Bool? = nil
    ) {
        self.mode = mode
        self.modelID = modelID
        self.text = text
        self.outputPath = outputPath
        self.shouldStream = shouldStream
        self.streamingInterval = streamingInterval
        self.batchIndex = batchIndex
        self.batchTotal = batchTotal
        self.streamingTitle = streamingTitle
        self.languageHint = languageHint
        self.payload = payload
        self.generationID = generationID
        self.seed = seed
        self.variation = variation
        self.suppressStreamingPreview = suppressStreamingPreview
    }

    public init(
        modelID: String,
        text: String,
        outputPath: String,
        shouldStream: Bool = false,
        streamingInterval: Double? = nil,
        batchIndex: Int? = nil,
        batchTotal: Int? = nil,
        streamingTitle: String? = nil,
        languageHint: String? = nil,
        payload: Payload,
        generationID: UUID? = nil,
        seed: UInt64? = nil,
        variation: Qwen3SamplingVariation? = nil,
        suppressStreamingPreview: Bool? = nil
    ) {
        let resolvedMode: GenerationMode
        switch payload {
        case .custom:
            resolvedMode = .custom
        case .design:
            resolvedMode = .design
        case .clone:
            resolvedMode = .clone
        }

        self.init(
            mode: resolvedMode,
            modelID: modelID,
            text: text,
            outputPath: outputPath,
            shouldStream: shouldStream,
            streamingInterval: streamingInterval,
            batchIndex: batchIndex,
            batchTotal: batchTotal,
            streamingTitle: streamingTitle,
            languageHint: languageHint,
            payload: payload,
            generationID: generationID,
            seed: seed,
            variation: variation,
            suppressStreamingPreview: suppressStreamingPreview
        )
    }

    public var modeIdentifier: String {
        mode.rawValue
    }

    public var engineActivityLabel: String {
        EngineActivityLabels.generating(mode: mode)
    }

    public func withGenerationID(_ generationID: UUID) -> GenerationRequest {
        GenerationRequest(
            mode: mode,
            modelID: modelID,
            text: text,
            outputPath: outputPath,
            shouldStream: shouldStream,
            streamingInterval: streamingInterval,
            batchIndex: batchIndex,
            batchTotal: batchTotal,
            streamingTitle: streamingTitle,
            languageHint: languageHint,
            payload: payload,
            generationID: generationID,
            seed: seed,
            variation: variation
        )
    }
}

public struct GenerationProgress: Hashable, Codable, Sendable {
    public let percent: Int
    public let message: String

    public init(percent: Int, message: String) {
        self.percent = percent
        self.message = message
    }
}

public struct GenerationChunk: Hashable, Codable, Sendable {
    public let generationID: UUID?
    public let requestID: Int?
    public let mode: String
    public let title: String
    public let chunkPath: String?
    public let isFinal: Bool
    public let chunkDurationSeconds: Double?
    public let cumulativeDurationSeconds: Double?
    public let streamSessionDirectory: String?
    public let previewAudio: StreamingAudioChunk?
    /// Monotonic per-generation chunk index for transport gap detection.
    public let chunkSequence: UInt64?

    public init(
        generationID: UUID? = nil,
        requestID: Int? = nil,
        mode: String,
        title: String,
        chunkPath: String?,
        isFinal: Bool,
        chunkDurationSeconds: Double?,
        cumulativeDurationSeconds: Double?,
        streamSessionDirectory: String?,
        previewAudio: StreamingAudioChunk? = nil,
        chunkSequence: UInt64? = nil
    ) {
        self.generationID = generationID
        self.requestID = requestID
        self.mode = mode
        self.title = title
        self.chunkPath = chunkPath
        self.isFinal = isFinal
        self.chunkDurationSeconds = chunkDurationSeconds
        self.cumulativeDurationSeconds = cumulativeDurationSeconds
        self.streamSessionDirectory = streamSessionDirectory
        self.previewAudio = previewAudio
        self.chunkSequence = chunkSequence
    }

    public func withoutPreviewAudioPayload() -> GenerationChunk {
        GenerationChunk(
            generationID: generationID,
            requestID: requestID,
            mode: mode,
            title: title,
            chunkPath: chunkPath,
            isFinal: isFinal,
            chunkDurationSeconds: chunkDurationSeconds,
            cumulativeDurationSeconds: cumulativeDurationSeconds,
            streamSessionDirectory: streamSessionDirectory,
            previewAudio: nil,
            chunkSequence: chunkSequence
        )
    }

    public var deliveryIdentity: GenerationChunkDeliveryIdentity {
        GenerationChunkDeliveryIdentity(
            generationID: generationID,
            requestID: requestID,
            mode: mode,
            title: title,
            chunkPath: chunkPath,
            isFinal: isFinal,
            chunkDurationSeconds: chunkDurationSeconds,
            cumulativeDurationSeconds: cumulativeDurationSeconds,
            streamSessionDirectory: streamSessionDirectory,
            previewAudioGenerationID: previewAudio?.generationID,
            previewAudioRequestID: previewAudio?.requestID,
            previewAudioSampleRate: previewAudio?.sampleRate,
            previewAudioFrameOffset: previewAudio?.frameOffset,
            previewAudioFrameCount: previewAudio?.frameCount,
            previewAudioIsFinal: previewAudio?.isFinal
        )
    }
}

public struct GenerationChunkDeliveryIdentity: Hashable, Sendable {
    public let generationID: UUID?
    public let requestID: Int?
    public let mode: String
    public let title: String
    public let chunkPath: String?
    public let isFinal: Bool
    public let chunkDurationSeconds: Double?
    public let cumulativeDurationSeconds: Double?
    public let streamSessionDirectory: String?
    public let previewAudioGenerationID: UUID?
    public let previewAudioRequestID: Int?
    public let previewAudioSampleRate: Int?
    public let previewAudioFrameOffset: Int64?
    public let previewAudioFrameCount: Int?
    public let previewAudioIsFinal: Bool?
}

public enum GenerationEvent: Hashable, Codable, Sendable {
    public enum Kind: String, Hashable, Codable, Sendable {
        case streamChunk
        case progress
        case completed
        case cancelled
        case failed
    }

    case progress(GenerationProgress)
    case chunk(GenerationChunk)
    case completed(GenerationResult)
    case cancelled(GenerationCancellationSummary)
    case failed(String)

    public init(
        kind: Kind,
        generationID: UUID? = nil,
        requestID: Int,
        mode: String,
        title: String,
        chunkPath: String? = nil,
        isFinal: Bool,
        chunkDurationSeconds: Double? = nil,
        cumulativeDurationSeconds: Double? = nil,
        streamSessionDirectory: String? = nil,
        previewAudio: StreamingAudioChunk? = nil
    ) {
        precondition(kind == .streamChunk, "This initializer only supports chunk events.")
        self = .chunk(
            GenerationChunk(
                generationID: generationID,
                requestID: requestID,
                mode: mode,
                title: title,
                chunkPath: chunkPath,
                isFinal: isFinal,
                chunkDurationSeconds: chunkDurationSeconds,
                cumulativeDurationSeconds: cumulativeDurationSeconds,
                streamSessionDirectory: streamSessionDirectory,
                previewAudio: previewAudio
            )
        )
    }

    public var kind: Kind {
        switch self {
        case .progress:
            return .progress
        case .chunk:
            return .streamChunk
        case .completed:
            return .completed
        case .cancelled:
            return .cancelled
        case .failed:
            return .failed
        }
    }

    public var requestID: Int? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.requestID
    }

    public var generationID: UUID? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.generationID
    }

    public var mode: String? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.mode
    }

    public var title: String? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.title
    }

    public var chunkPath: String? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.chunkPath
    }

    public var previewAudio: StreamingAudioChunk? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.previewAudio
    }

    public var isFinal: Bool? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.isFinal
    }

    public var chunkDurationSeconds: Double? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.chunkDurationSeconds
    }

    public var cumulativeDurationSeconds: Double? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.cumulativeDurationSeconds
    }

    public var streamSessionDirectory: String? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.streamSessionDirectory
    }

    public func withoutPreviewAudioPayload() -> GenerationEvent {
        switch self {
        case .chunk(let chunk):
            return .chunk(chunk.withoutPreviewAudioPayload())
        case .progress, .completed, .cancelled, .failed:
            return self
        }
    }

    public var chunkDeliveryIdentity: GenerationChunkDeliveryIdentity? {
        guard case .chunk(let chunk) = self else { return nil }
        return chunk.deliveryIdentity
    }
}

public struct TTSEngineSnapshot: Hashable, Codable, Sendable {
    public let isReady: Bool
    public let loadState: EngineLoadState
    public let clonePreparationState: ClonePreparationState
    public let visibleErrorMessage: String?

    public init(
        isReady: Bool,
        loadState: EngineLoadState,
        clonePreparationState: ClonePreparationState,
        visibleErrorMessage: String?
    ) {
        self.isReady = isReady
        self.loadState = loadState
        self.clonePreparationState = clonePreparationState
        self.visibleErrorMessage = visibleErrorMessage
    }
}

