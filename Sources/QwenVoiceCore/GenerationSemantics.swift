import CryptoKit
import Foundation

public enum GenerationSemantics {
    /// A caller may replace an output, but never the Clone conditioning asset.
    /// Resolve symlinks and hard links as well as lexical aliases before work.
    static func validateOutputOwnership(for request: GenerationRequest) throws {
        guard case .clone(let reference) = request.payload else { return }
        let output = URL(fileURLWithPath: request.outputPath).resolvingSymlinksInPath().standardizedFileURL
        let input = URL(fileURLWithPath: reference.audioPath).resolvingSymlinksInPath().standardizedFileURL
        let outputAttributes = try? FileManager.default.attributesOfItem(atPath: output.path)
        let inputAttributes = try? FileManager.default.attributesOfItem(atPath: input.path)
        let sameInode = outputAttributes?[.systemFileNumber] as? NSNumber != nil
            && outputAttributes?[.systemFileNumber] as? NSNumber == inputAttributes?[.systemFileNumber] as? NSNumber
            && outputAttributes?[.systemNumber] as? NSNumber == inputAttributes?[.systemNumber] as? NSNumber
        guard output != input, !sameInode else {
            throw MLXTTSEngineError.unsupportedRequest("The output must not replace the Clone reference audio. Choose a different output file.")
        }
    }

    public enum DesignWarmBucket: String, Hashable, Sendable {
        case short
        case long
    }

    public enum Qwen3PromptMode: String, Codable, Hashable, Sendable {
        case customVoice = "custom_voice"
        case voiceDesign = "voice_design"
        case voiceClone = "voice_clone"
    }

    public struct Qwen3PromptAssembly: Hashable, Codable, Sendable {
        public let mode: Qwen3PromptMode
        public let text: String
        public let language: String
        public let instruct: String?
        public let refText: String?
        public let speakerID: String?
        public let usesInstructionControl: Bool
        public let cloneUsesTranscript: Bool
        public let instructionLanguage: DeliveryInstructionLanguage?
    }

    public struct ResolvedDeliveryInstruction: Hashable, Sendable {
        public let instruction: String?
        public let language: DeliveryInstructionLanguage?
    }

    public enum DeliveryInstructionIdentityError: LocalizedError, Equatable, Sendable {
        case nonCustomMode(String)
        case canonicalInstructionMismatch(String)

        public var errorDescription: String? {
            switch self {
            case .nonCustomMode(let cellID):
                return "Delivery cell '\(cellID)' is valid only for CustomVoice requests."
            case .canonicalInstructionMismatch(let cellID):
                return "Delivery cell '\(cellID)' does not match its canonical instruction."
            }
        }
    }

    public static func validateDeliveryInstructionIdentity(
        for request: GenerationRequest
    ) throws {
        guard let cellID = request.deliveryInstructionCellID else { return }
        guard case .custom(_, let suppliedInstruction) = request.payload else {
            throw DeliveryInstructionIdentityError.nonCustomMode(cellID)
        }
        let cell = try DeliveryInstructionCell.resolveStrict(cellID)
        let supplied = suppliedInstruction?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard supplied == cell.instruction else {
            throw DeliveryInstructionIdentityError.canonicalInstructionMismatch(cellID)
        }
    }

    /// Collision-safe value identity for a resolved Voice Design warm state.
    ///
    /// Equality and hashing operate on typed fields rather than a delimiter-
    /// composed string. `canonicalSerialization` is UTF-8 length framed for
    /// deterministic diagnostics; cache boundaries use its opaque digest.
    public struct DesignConditioningIdentity: Hashable, Sendable {
        public let modelID: String
        public let language: String
        public let instruction: String
        public let bucket: DesignWarmBucket

        public var canonicalSerialization: String {
            GenerationSemantics.canonicalIdentitySerialization(
                namespace: "design-conditioning",
                components: [modelID, language, instruction, bucket.rawValue]
            )
        }

        public var digest: String {
            GenerationSemantics.canonicalIdentityDigest(canonicalSerialization)
        }

        public var cacheKey: String { "qv-design-v1-\(digest)" }

        /// Compatibility output for callers that display or compare the
        /// pre-v1 key. Runtime cache ownership must use this value type.
        public var legacyKey: String {
            [
                modelID,
                GenerationMode.design.rawValue,
                language,
                instruction,
                bucket.rawValue,
            ].joined(separator: "|")
        }
    }

    /// Collision-safe clone identity. The optional fingerprint remains a
    /// separate field internally instead of being appended to a path with
    /// `#`, so paths containing separators cannot alias another reference.
    public struct CloneReferenceIdentity: Hashable, Sendable {
        public let modelID: String
        public let conditioningMode: CloneConditioningMode
        public let referenceAudio: String
        public let referenceFingerprint: String?

        public init(modelID: String, refAudio: String, refText: String?) {
            self.init(
                modelID: modelID,
                referenceAudio: refAudio,
                referenceFingerprint: nil,
                conditioningMode: CloneConditioningMode(transcript: refText)
            )
        }

        init(
            modelID: String,
            referenceAudio: String,
            referenceFingerprint: String?,
            conditioningMode: CloneConditioningMode
        ) {
            self.modelID = modelID
            self.referenceAudio = referenceAudio.trimmingCharacters(in: .whitespacesAndNewlines)
            let normalizedFingerprint = referenceFingerprint?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            self.referenceFingerprint = normalizedFingerprint?.isEmpty == false
                ? normalizedFingerprint
                : nil
            self.conditioningMode = conditioningMode.normalized
        }

        public var canonicalSerialization: String {
            GenerationSemantics.canonicalIdentitySerialization(
                namespace: "clone-reference",
                components: [
                    modelID,
                    conditioningMode.identifier,
                    referenceAudio,
                    referenceFingerprint ?? "",
                    conditioningMode.transcript ?? "",
                ]
            )
        }

        public var digest: String {
            GenerationSemantics.canonicalIdentityDigest(canonicalSerialization)
        }

        public var cacheKey: String { "qv-clone-v1-\(digest)" }

        /// Compatibility output used by existing UI identity/state APIs and
        /// the persistent clone-artifact directory derivation.
        public var legacyKey: String {
            let legacyAudio = referenceFingerprint.map { "\(referenceAudio)#\($0)" }
                ?? referenceAudio
            return [
                modelID,
                GenerationMode.clone.rawValue,
                conditioningMode.identifier,
                legacyAudio,
                conditioningMode.transcript ?? "",
            ].joined(separator: "|")
        }
    }

    /// Immutable installed-model identity that contributes learned weights to
    /// a reusable clone prompt. This deliberately carries only privacy-safe
    /// contract identifiers and the installed integrity-manifest digest; local
    /// model paths never participate in prompt identity.
    struct ClonePromptModelArtifactIdentity: Hashable, Sendable {
        let repository: String
        let revision: String
        let artifactVersion: String
        let integrityManifestDigest: String

        init?(
            repository: String?,
            revision: String?,
            artifactVersion: String?,
            integrityManifestDigest: String?
        ) {
            let normalizedRepository = repository?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let normalizedRevision = revision?
                .trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
            let normalizedArtifactVersion = artifactVersion?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let normalizedDigest = integrityManifestDigest?
                .trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
            let lowercaseHex = CharacterSet(charactersIn: "0123456789abcdef")
            guard !normalizedRepository.isEmpty,
                  normalizedRevision.count == 40,
                  normalizedRevision.unicodeScalars.allSatisfy(lowercaseHex.contains),
                  !normalizedArtifactVersion.isEmpty,
                  normalizedDigest.count == 64,
                  normalizedDigest.unicodeScalars.allSatisfy(lowercaseHex.contains) else {
                return nil
            }
            self.repository = normalizedRepository
            self.revision = normalizedRevision
            self.artifactVersion = normalizedArtifactVersion
            self.integrityManifestDigest = normalizedDigest
        }

        init?(modelRuntimeIdentity: ModelRuntimeIdentity) {
            self.init(
                repository: modelRuntimeIdentity.modelRepository,
                revision: modelRuntimeIdentity.huggingFaceRevision,
                artifactVersion: modelRuntimeIdentity.artifactVersion,
                integrityManifestDigest: modelRuntimeIdentity.integrityManifestDigest
            )
        }

        var canonicalSerialization: String {
            GenerationSemantics.canonicalIdentitySerialization(
                namespace: "clone-prompt-model-artifact",
                components: [
                    repository,
                    revision,
                    artifactVersion,
                    integrityManifestDigest,
                ]
            )
        }
    }

    /// Complete semantic identity for a reusable clone prompt.
    ///
    /// A clone reference alone is not sufficient: the learned speaker
    /// embedding also depends on the model runtime contract and the speaker
    /// feature frontend that produced it. Persisted artifacts store
    /// `runtimeContractSignature` in their existing runtime-profile metadata
    /// field, while the actor-owned prompt LRU uses this whole value directly.
    struct ClonePromptIdentity: Hashable, Sendable {
        let referenceIdentity: CloneReferenceIdentity
        let language: String
        let modelArtifactIdentity: ClonePromptModelArtifactIdentity
        let qwenRuntimeProfileSignature: String?
        let speakerFeatureVersion: String

        init(
            referenceIdentity: CloneReferenceIdentity,
            language: String?,
            modelArtifactIdentity: ClonePromptModelArtifactIdentity,
            qwenRuntimeProfileSignature: String?,
            speakerFeatureVersion: String
        ) {
            self.referenceIdentity = referenceIdentity
            self.modelArtifactIdentity = modelArtifactIdentity
            let normalizedLanguage = (language ?? "auto")
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased()
            self.language = normalizedLanguage.isEmpty ? "auto" : normalizedLanguage
            let normalizedRuntimeSignature = qwenRuntimeProfileSignature?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            self.qwenRuntimeProfileSignature = normalizedRuntimeSignature?.isEmpty == false
                ? normalizedRuntimeSignature
                : nil
            self.speakerFeatureVersion = speakerFeatureVersion
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }

        var runtimeContractSerialization: String {
            GenerationSemantics.canonicalIdentitySerialization(
                namespace: "clone-prompt-runtime-contract",
                components: [
                    modelArtifactIdentity.canonicalSerialization,
                    qwenRuntimeProfileSignature ?? "",
                    speakerFeatureVersion,
                ]
            )
        }

        var runtimeContractSignature: String {
            "qv-clone-prompt-runtime-v2-\(GenerationSemantics.canonicalIdentityDigest(runtimeContractSerialization))"
        }

        var canonicalSerialization: String {
            GenerationSemantics.canonicalIdentitySerialization(
                namespace: "clone-prompt",
                components: [
                    referenceIdentity.canonicalSerialization,
                    language,
                    runtimeContractSignature,
                ]
            )
        }

        var digest: String {
            GenerationSemantics.canonicalIdentityDigest(canonicalSerialization)
        }

        var cacheKey: String { "qv-clone-prompt-v1-\(digest)" }
    }

    /// Typed identity for the three semantically distinct prewarm scopes.
    public enum PrewarmIdentity: Hashable, Sendable {
        case model(modelID: String, mode: GenerationMode)
        case customRequest(
            modelID: String,
            language: String,
            speakerID: String,
            instruction: String
        )
        case clone(CloneReferenceIdentity)

        public var canonicalSerialization: String {
            switch self {
            case .model(let modelID, let mode):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "model-prewarm",
                    components: [modelID, mode.rawValue]
                )
            case .customRequest(let modelID, let language, let speakerID, let instruction):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "custom-request-prewarm",
                    components: [modelID, language, speakerID, instruction]
                )
            case .clone(let identity):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "clone-prewarm",
                    components: [identity.canonicalSerialization]
                )
            }
        }

        public var digest: String {
            GenerationSemantics.canonicalIdentityDigest(canonicalSerialization)
        }

        public var cacheKey: String { "qv-prewarm-v1-\(digest)" }

        /// Compatibility output for existing public string APIs.
        public var legacyKey: String {
            switch self {
            case .model(let modelID, let mode):
                [modelID, mode.rawValue].joined(separator: "|")
            case .customRequest(let modelID, let language, let speakerID, let instruction):
                [modelID, GenerationMode.custom.rawValue, language, speakerID, instruction]
                    .joined(separator: "|")
            case .clone(let identity):
                identity.legacyKey
            }
        }
    }

    /// Collision-safe identity for a batch generation session.
    ///
    /// The former implementation concatenated payload fields with `|` before
    /// applying a 64-bit FNV hash. Inputs containing that delimiter could alias
    /// a different semantic request. This value keeps the fields typed and uses
    /// the same UTF-8 length framing + SHA-256 boundary as the other runtime
    /// identities.
    public enum GenerationSessionIdentity: Hashable, Sendable {
        case custom(
            modelID: String,
            language: String,
            speakerID: String,
            deliveryStyle: String?
        )
        case design(
            modelID: String,
            language: String,
            voiceDescription: String,
            deliveryStyle: String?
        )
        case clone(
            modelID: String,
            language: String,
            audioPath: String,
            conditioningMode: CloneConditioningMode,
            preparedVoiceID: String?
        )

        public var canonicalSerialization: String {
            switch self {
            case .custom(let modelID, let language, let speakerID, let deliveryStyle):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "generation-session-custom-v1",
                    components: [
                        modelID,
                        language,
                        speakerID,
                        deliveryStyle == nil ? "none" : "some",
                        deliveryStyle ?? "",
                    ]
                )
            case .design(let modelID, let language, let voiceDescription, let deliveryStyle):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "generation-session-design-v1",
                    components: [
                        modelID,
                        language,
                        voiceDescription,
                        deliveryStyle == nil ? "none" : "some",
                        deliveryStyle ?? "",
                    ]
                )
            case .clone(
                let modelID,
                let language,
                let audioPath,
                let conditioningMode,
                let preparedVoiceID
            ):
                GenerationSemantics.canonicalIdentitySerialization(
                    namespace: "generation-session-clone-v1",
                    components: [
                        modelID,
                        language,
                        audioPath,
                        conditioningMode.identifier,
                        conditioningMode.transcript ?? "",
                        preparedVoiceID == nil ? "none" : "some",
                        preparedVoiceID ?? "",
                    ]
                )
            }
        }

        public var digest: String {
            GenerationSemantics.canonicalIdentityDigest(canonicalSerialization)
        }

        public var sessionKey: GenerationSessionKey {
            switch self {
            case .custom(let modelID, let language, _, _):
                GenerationSessionKey(
                    modelID: modelID,
                    mode: .custom,
                    language: language,
                    speakerOrVoiceDescriptionHash: digest
                )
            case .design(let modelID, let language, _, _):
                GenerationSessionKey(
                    modelID: modelID,
                    mode: .design,
                    language: language,
                    speakerOrVoiceDescriptionHash: digest
                )
            case .clone(let modelID, let language, _, _, _):
                GenerationSessionKey(
                    modelID: modelID,
                    mode: .clone,
                    language: language,
                    cloneReferenceHash: digest
                )
            }
        }
    }

    public static func generationSessionIdentity(
        for request: GenerationRequest,
        resolvedCustomInstruction: String? = nil
    ) -> GenerationSessionIdentity {
        let language = qwenLanguageHint(for: request)
        switch request.payload {
        case .custom(let speakerID, let deliveryStyle):
            return .custom(
                modelID: request.modelID,
                language: language,
                speakerID: speakerID,
                deliveryStyle: resolvedCustomInstruction ?? deliveryStyle
            )
        case .design(let voiceDescription, let deliveryStyle):
            return .design(
                modelID: request.modelID,
                language: language,
                voiceDescription: voiceDescription,
                deliveryStyle: deliveryStyle
            )
        case .clone(let reference):
            return .clone(
                modelID: request.modelID,
                language: language,
                audioPath: reference.audioPath,
                conditioningMode: reference.conditioningMode,
                preparedVoiceID: reference.preparedVoiceID
            )
        }
    }

    public static let appStreamingInterval = 0.32
    public static let canonicalCustomWarmText = "Hi."
    public static let canonicalCustomWarmSpeaker = "aiden"
    public static let canonicalCustomWarmLanguage = "english"
    public static let canonicalDesignWarmLanguage = "english"
    public static let englishDictionReinforcement =
        "Native English pronunciation with clear English diction and natural stress."
    public static let canonicalDesignWarmShortText = "Hello world."
    public static let canonicalDesignWarmLongText =
        """
        Artificial intelligence has rapidly transformed from a niche academic pursuit into one of the most consequential technologies of the modern era. Large language models, capable of generating coherent text across a wide range of domains, have captured the imagination of researchers and the general public alike. Meanwhile, text-to-speech systems have reached a point where synthesized voices are often indistinguishable from natural human speech, opening new possibilities for accessibility, creative media production, and personalized assistants.
        """

    public static func isNeutralDeliveryInstruction(_ emotion: String) -> Bool {
        let normalized = normalizedConditioningCacheKeyText(emotion)
        return normalized.isEmpty
            || normalized == "normal tone"
            || normalized == "neutral"
            || normalized == "neutral tone"
    }

    public static func hasMeaningfulDeliveryInstruction(_ emotion: String) -> Bool {
        !isNeutralDeliveryInstruction(emotion)
    }

    public static func supportsIdlePrewarm(mode: GenerationMode) -> Bool {
        mode == .custom
    }

    public static func designInstruction(voiceDescription: String, emotion: String) -> String {
        let trimmedDescription = voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedEmotion = emotion.trimmingCharacters(in: .whitespacesAndNewlines)
        guard hasMeaningfulDeliveryInstruction(trimmedEmotion) else {
            return trimmedDescription.trimmingTerminalSentencePunctuation()
        }

        guard !trimmedDescription.isEmpty else {
            return trimmedEmotion.trimmingTerminalSentencePunctuation()
        }
        let description = trimmedDescription.trimmingTerminalSentencePunctuation()
        let delivery = trimmedEmotion.trimmingTerminalSentencePunctuation()

        // DP-5 experiment arms. Production is `.labeled` and unchanged.
        //
        // Upstream carries voice identity and delivery in a single `instruct`
        // string and documents no way to combine them, so the labeled framing is
        // a repository invention (prompting guide §6.1). The labels may help the
        // model segment two intents, or may simply be two out-of-distribution
        // tokens at a high-attention position. `anchored` tests the vendor
        // guidance that a closing recording-quality clause stops texture words
        // being read as degradation.
        switch designMergeForm {
        case .plain:
            return "\(description). \(delivery)."
        case .anchored:
            return "\(description). \(delivery). Perfect broadcast quality audio."
        case .labeled:
            return "Voice character: \(description). Delivery: \(delivery)."
        }
    }

    enum DesignMergeForm: String {
        case labeled, plain, anchored
    }

    /// `QWENVOICE_DESIGN_MERGE_FORM=plain|anchored` selects a DP-5 arm. Registered
    /// in `config/runtime-debug-knobs.json` and inert without the `QWENVOICE_DEBUG`
    /// master gate, so production always resolves `.labeled`.
    static let designMergeForm: DesignMergeForm = {
        let raw = RuntimeDebugGate.value(for: "QWENVOICE_DESIGN_MERGE_FORM")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return raw.flatMap(DesignMergeForm.init(rawValue:)) ?? .labeled
    }()

    public static func normalizedConditioningCacheKeyText(_ text: String) -> String {
        Qwen3TTSRuntimeProfile.normalizedCacheText(text)
    }

    public static func normalizedDesignConditioningIdentity(
        language: String,
        voiceDescription: String,
        emotion: String?
    ) -> String {
        let components = normalizedDesignConditioningComponents(
            language: language,
            voiceDescription: voiceDescription,
            emotion: emotion
        )
        return "\(components.language)|\(components.instruction)"
    }

    public static func customInstruction(deliveryStyle: String?) -> String? {
        guard let deliveryStyle else { return nil }
        let trimmedDelivery = deliveryStyle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard hasMeaningfulDeliveryInstruction(trimmedDelivery) else {
            return nil
        }
        return trimmedDelivery
    }

    public static func customInstruction(
        for request: GenerationRequest,
        capabilities: Qwen3TTSModelCapabilities
    ) -> String? {
        qwen3PromptAssembly(for: request, capabilities: capabilities).instruct
    }

    public static func voiceDesignInstruction(
        for request: GenerationRequest,
        capabilities: Qwen3TTSModelCapabilities
    ) -> String? {
        qwen3PromptAssembly(for: request, capabilities: capabilities).instruct
    }

    public static func qwen3PromptAssembly(
        for request: GenerationRequest,
        capabilities: Qwen3TTSModelCapabilities,
        resolvedCloneTranscript: String? = nil,
        spokenText: String? = nil,
        speakerNativeLanguage: String? = nil
    ) -> Qwen3PromptAssembly {
        // Phase 10: when the engine speaks a normalized script, the prompt and
        // the language detection must see the same spoken text, never a mix.
        let effectiveText = spokenText ?? request.text
        let language = qwenLanguageHint(
            for: request,
            resolvedCloneTranscript: resolvedCloneTranscript,
            textOverride: spokenText
        )
        switch request.payload {
        case .custom(let speakerID, _):
            let canUseInstruction = capabilities.supportsInstructionControl
            let resolvedDelivery = canUseInstruction
                ? resolvedDeliveryInstruction(
                    for: request,
                    speakerNativeLanguage: speakerNativeLanguage,
                    outputLanguage: language
                )
                : ResolvedDeliveryInstruction(instruction: nil, language: nil)
            let instruction = canUseInstruction
                ? englishDictionReinforcedInstruction(
                    baseInstruction: resolvedDelivery.instruction,
                    language: language
                )
                : nil
            return Qwen3PromptAssembly(
                mode: .customVoice,
                text: effectiveText,
                language: language,
                instruct: instruction,
                refText: nil,
                speakerID: speakerID.trimmingCharacters(in: .whitespacesAndNewlines),
                usesInstructionControl: instruction != nil,
                cloneUsesTranscript: false,
                instructionLanguage: resolvedDelivery.language
            )
        case .design(let voiceDescription, let deliveryStyle):
            let baseInstruction = capabilities.supportsInstructionControl
                ? designInstruction(
                    voiceDescription: voiceDescription,
                    emotion: deliveryStyle ?? ""
                )
                : voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            let instruction = englishDictionReinforcedInstruction(
                baseInstruction: baseInstruction,
                language: language
            )
            return Qwen3PromptAssembly(
                mode: .voiceDesign,
                text: effectiveText,
                language: language,
                instruct: instruction,
                refText: nil,
                speakerID: nil,
                usesInstructionControl: instruction != nil,
                cloneUsesTranscript: false,
                instructionLanguage: instruction == nil ? nil : .verbatim
            )
        case .clone(let reference):
            let rawRefText = (resolvedCloneTranscript ?? reference.transcript)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmedRefText = (rawRefText?.isEmpty == false) ? rawRefText : nil
            return Qwen3PromptAssembly(
                mode: .voiceClone,
                text: effectiveText,
                language: language,
                instruct: nil,
                refText: trimmedRefText,
                speakerID: nil,
                usesInstructionControl: false,
                cloneUsesTranscript: trimmedRefText != nil,
                instructionLanguage: nil
            )
        }
    }

    public static func resolvedDeliveryInstruction(
        for request: GenerationRequest,
        speakerNativeLanguage: String?,
        outputLanguage: String? = nil
    ) -> ResolvedDeliveryInstruction {
        guard case .custom(_, let deliveryStyle) = request.payload else {
            return ResolvedDeliveryInstruction(instruction: nil, language: nil)
        }
        let verbatim = customInstruction(deliveryStyle: deliveryStyle)
        guard let cellID = request.deliveryInstructionCellID,
              let cell = try? DeliveryInstructionCell.resolveStrict(cellID),
              verbatim == cell.instruction else {
            return ResolvedDeliveryInstruction(
                instruction: verbatim,
                language: verbatim == nil ? nil : .verbatim
            )
        }

        let resolvedOutputLanguage = outputLanguage ?? qwenLanguageHint(for: request)
        let outputIsChinese = Qwen3SupportedLanguage.normalized(resolvedOutputLanguage) == .chinese
        let speakerIsChinese = Qwen3SupportedLanguage.nativeLanguage(speakerNativeLanguage) == .chinese
        let candidateEnglish = cell.preset.instructionVariant(
            for: cell.intensity,
            language: .english
        )
        if cell.id == "angry.normal",
           cell.instruction == candidateEnglish?.instruction,
           outputIsChinese,
           speakerIsChinese,
           let variant = cell.preset.instructionVariant(
               for: cell.intensity,
               language: .mandarin
           ) {
            return ResolvedDeliveryInstruction(
                instruction: variant.instruction,
                language: .mandarin
            )
        }
        return ResolvedDeliveryInstruction(instruction: verbatim, language: .english)
    }

    /// Dev A/B gate: `QWENVOICE_ENGLISH_DICTION_REINFORCEMENT=off` skips the
    /// English diction-reinforcement append entirely, so fixed-seed delivery and
    /// prosody evidence can test whether the extra clause dilutes instruction
    /// adherence; an optional listening note may supplement that evidence.
    /// Resolved once; production default is unchanged (reinforcement on).
    private static let englishDictionReinforcementDisabled: Bool = {
        let raw = RuntimeDebugGate.value(for: "QWENVOICE_ENGLISH_DICTION_REINFORCEMENT")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return raw == "off" || raw == "0" || raw == "false" || raw == "no"
    }()

    /// Words whose presence means the base instruction already asks for clarity,
    /// so appending the reinforcement would be redundant and would crowd out the
    /// dominant emotion signal.
    private static let dictionTokens = [
        "clear", "clearly", "diction", "articulation",
        "pronunciation", "clarity", "intelligible", "understandable",
    ]

    private static func containsDictionToken(_ instruction: String) -> Bool {
        let lowercased = instruction.lowercased()
        return dictionTokens.contains { lowercased.contains($0) }
    }

    /// Every shipped preset instruction belonging to a preset that trips the
    /// diction-token rule on *any* intensity tier.
    ///
    /// The append decision must not vary between a preset's tiers. It says
    /// nothing about intensity, so a tier-varying 76-character difference is pure
    /// confound: normal-versus-strong then differs by boilerplate as well as by
    /// emotional wording. Measured 2026-08-02 — happy, surprised, and dramatic
    /// each suppressed on `normal` and appended on `strong`, and the recorded
    /// intensity-tier finding was measured over a matrix that included them.
    /// Resolving preset-wide (suppress if any tier asks for clarity) keeps the
    /// rule's intent and removes the asymmetry without touching emotional copy.
    /// `scripts/check_delivery_instructions.py` fails the build if it returns.
    private static let presetInstructionsSuppressingDictionReinforcement: Set<String> = {
        var suppressed: Set<String> = []
        for preset in EmotionPreset.all {
            let tierInstructions = EmotionIntensity.allCases.map { preset.instruction(for: $0) }
            guard tierInstructions.contains(where: containsDictionToken) else { continue }
            suppressed.formUnion(tierInstructions.map {
                $0.trimmingCharacters(in: .whitespacesAndNewlines)
            })
        }
        return suppressed
    }()

    public static func englishDictionReinforcedInstruction(
        baseInstruction: String?,
        language: String
    ) -> String? {
        guard !englishDictionReinforcementDisabled else {
            return baseInstruction
        }
        guard Qwen3TTSRuntimeProfile.normalizedLanguage(language) == "english" else {
            return baseInstruction
        }

        let reinforcement = englishDictionReinforcement
        guard let baseInstruction else {
            return reinforcement
        }

        let trimmedBase = baseInstruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedBase.isEmpty else {
            return reinforcement
        }
        if normalizedConditioningCacheKeyText(trimmedBase)
            .contains(normalizedConditioningCacheKeyText(reinforcement)) {
            return trimmedBase
        }
        // Preset instructions resolve preset-wide so the two intensity tiers of
        // one preset never differ by boilerplate alone (see the set above).
        if presetInstructionsSuppressingDictionReinforcement.contains(trimmedBase) {
            return trimmedBase
        }
        // Free-form instructions resolve per string: skip the append when the
        // caller already asked for clarity, so the model is not handed
        // "…with clear articulation… Native English pronunciation with clear
        // English diction and natural stress."
        if containsDictionToken(trimmedBase) {
            return trimmedBase
        }
        return "\(trimmedBase) \(reinforcement)"
    }

    public static func qwenLanguageHint(
        for request: GenerationRequest,
        resolvedCloneTranscript: String? = nil,
        textOverride: String? = nil
    ) -> String {
        let effectiveText = textOverride ?? request.text
        if let languageHint = request.languageHint {
            let normalized = Qwen3SupportedLanguage.normalized(languageHint)
            if normalized != .auto {
                return normalized.rawValue
            }
        }
        switch request.payload {
        case .custom:
            return detectedQwenLanguage(in: effectiveText)?.rawValue ?? canonicalCustomWarmLanguage
        case .design:
            return detectedQwenLanguage(in: effectiveText)?.rawValue ?? Qwen3SupportedLanguage.auto.rawValue
        case .clone:
            // Qwen's `language` field describes the text being synthesized,
            // not the language of the reference transcript. The latter is
            // conditioning metadata and must never redirect an Auto request
            // away from its target text (for example, a French reference
            // cloning an English script).
            return detectedQwenLanguage(in: effectiveText)?.rawValue ?? Qwen3SupportedLanguage.auto.rawValue
        }
    }

    public static func validateQwenPromptContract(for request: GenerationRequest) throws {
        switch request.payload {
        case .custom(_, let deliveryStyle):
            if let deliveryStyle,
               hasMeaningfulDeliveryInstruction(deliveryStyle),
               Qwen3TTSRuntimeProfile.containsDisallowedVoiceImitationInstruction(
                   normalizedConditioningCacheKeyText(deliveryStyle)
               ) {
                throw MLXTTSEngineError.unsupportedRequest(
                    "Built-in Voice delivery instructions cannot request celebrity imitation or voice impersonation."
                )
            }
        case .design(let voiceDescription, let deliveryStyle):
            let instruction = designInstruction(
                voiceDescription: voiceDescription,
                emotion: deliveryStyle ?? ""
            )
            if Qwen3TTSRuntimeProfile.containsDisallowedVoiceImitationInstruction(
                normalizedConditioningCacheKeyText(instruction)
            ) {
                throw MLXTTSEngineError.unsupportedRequest(
                    "Voice Design descriptions cannot request celebrity imitation or voice impersonation."
                )
            }
        case .clone:
            break
        }
    }

    public static func canonicalCustomWarmInstruction() -> String? {
        nil
    }

    public static func canonicalDesignWarmInstruction() -> String {
        designInstruction(
            voiceDescription: "A clear, steady narrator with a natural conversational tone.",
            emotion: ""
        )
    }

    public static func canonicalDesignWarmText(for bucket: DesignWarmBucket) -> String {
        switch bucket {
        case .short:
            canonicalDesignWarmShortText
        case .long:
            canonicalDesignWarmLongText
        }
    }

    public static func designWarmBucket(for text: String) -> DesignWarmBucket {
        let normalizedText = normalizedConditioningCacheKeyText(text)
        guard !normalizedText.isEmpty else { return .short }

        let normalizedLongText = normalizedConditioningCacheKeyText(canonicalDesignWarmLongText)
        let longBucketThreshold = max(160, normalizedLongText.count / 2)
        return normalizedText.count >= longBucketThreshold ? .long : .short
    }

    public static func designConditioningWarmKey(
        modelID: String,
        language: String,
        voiceDescription: String,
        emotion: String?,
        text: String
    ) -> String {
        designConditioningIdentity(
            modelID: modelID,
            language: language,
            voiceDescription: voiceDescription,
            emotion: emotion,
            text: text
        ).legacyKey
    }

    public static func designConditioningWarmKey(
        for request: GenerationRequest
    ) -> String? {
        designConditioningIdentity(for: request)?.legacyKey
    }

    public static func designConditioningIdentity(
        modelID: String,
        language: String,
        voiceDescription: String,
        emotion: String?,
        text: String
    ) -> DesignConditioningIdentity {
        let components = normalizedDesignConditioningComponents(
            language: language,
            voiceDescription: voiceDescription,
            emotion: emotion
        )
        return DesignConditioningIdentity(
            modelID: modelID,
            language: components.language,
            instruction: components.instruction,
            bucket: designWarmBucket(for: text)
        )
    }

    public static func designConditioningIdentity(
        for request: GenerationRequest
    ) -> DesignConditioningIdentity? {
        guard case .design(let voiceDescription, let emotion) = request.payload else {
            return nil
        }
        let trimmedVoiceDescription = voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedVoiceDescription.isEmpty else { return nil }
        let language = qwenLanguageHint(for: request)
        return designConditioningIdentity(
            modelID: request.modelID,
            language: language,
            voiceDescription: voiceDescription,
            emotion: emotion,
            text: request.text
        )
    }

    public static func prewarmIdentityKey(
        modelID: String,
        mode: GenerationMode,
        voice: String? = nil,
        instruct: String? = nil,
        refAudio: String? = nil,
        refText: String? = nil
    ) -> String {
        prewarmIdentity(
            modelID: modelID,
            mode: mode,
            voice: voice,
            instruct: instruct,
            refAudio: refAudio,
            refText: refText
        ).legacyKey
    }

    public static func prewarmIdentity(
        modelID: String,
        mode: GenerationMode,
        voice: String? = nil,
        instruct: String? = nil,
        refAudio: String? = nil,
        refText: String? = nil
    ) -> PrewarmIdentity {
        let trimmedVoice = voice?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let trimmedRefAudio = refAudio?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let trimmedRefText = refText?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let trimmedInstruction = instruct?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let normalizedInstruction = hasMeaningfulDeliveryInstruction(trimmedInstruction) ? trimmedInstruction : ""

        switch mode {
        case .custom:
            _ = trimmedVoice
            _ = normalizedInstruction
            // Keep custom interactive readiness stable at the model level so
            // UI draft churn does not invalidate the hot model state.
            return .model(modelID: modelID, mode: mode)
        case .design:
            return .model(modelID: modelID, mode: mode)
        case .clone:
            return .clone(
                CloneReferenceIdentity(
                    modelID: modelID,
                    refAudio: trimmedRefAudio,
                    refText: trimmedRefText
                )
            )
        }
    }

    public static func cloneReferenceIdentityKey(
        modelID: String,
        refAudio: String,
        refText: String?
    ) -> String {
        cloneReferenceIdentity(
            modelID: modelID,
            refAudio: refAudio,
            refText: refText
        ).legacyKey
    }

    public static func cloneReferenceIdentity(
        modelID: String,
        refAudio: String,
        refText: String?
    ) -> CloneReferenceIdentity {
        CloneReferenceIdentity(
            modelID: modelID,
            refAudio: refAudio,
            refText: refText
        )
    }

    static func internalCloneReferenceIdentity(
        modelID: String,
        normalizedReferencePath: String,
        referenceFingerprint: String,
        conditioningMode: CloneConditioningMode
    ) -> CloneReferenceIdentity {
        CloneReferenceIdentity(
            modelID: modelID,
            referenceAudio: normalizedReferencePath,
            referenceFingerprint: referenceFingerprint,
            conditioningMode: conditioningMode
        )
    }

    /// Request-form prewarm identity key. For `.custom`, the key INCLUDES
    /// the speaker and (normalized) delivery instruction, so that voice/
    /// delivery changes invalidate the prewarm cache. The parameterized
    /// `prewarmIdentityKey(modelID:mode:...)` above intentionally omits
    /// those for the "stable model-level readiness" code paths — both
    /// forms coexist by design with intentionally different semantics.
    /// Live callers: NativeEngineRuntime, XPCNativeEngineClient,
    /// GenerationSemanticsTests.
    public static func prewarmIdentityKey(for request: GenerationRequest) -> String {
        prewarmIdentity(for: request).legacyKey
    }

    public static func prewarmIdentity(
        for request: GenerationRequest,
        resolvedCustomInstruction: String? = nil
    ) -> PrewarmIdentity {
        switch request.payload {
        case .custom(let speakerID, let deliveryStyle):
            let effectiveInstruction = resolvedCustomInstruction ?? deliveryStyle
            let normalizedInstruction = hasMeaningfulDeliveryInstruction(effectiveInstruction ?? "")
                ? effectiveInstruction?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                : ""
            return .customRequest(
                modelID: request.modelID,
                language: qwenLanguageHint(for: request),
                speakerID: speakerID.trimmingCharacters(in: .whitespacesAndNewlines),
                instruction: normalizedInstruction
            )
        case .design:
            return .model(modelID: request.modelID, mode: .design)
        case .clone(let reference):
            return .clone(
                cloneReferenceIdentity(
                    modelID: request.modelID,
                    refAudio: reference.audioPath,
                    refText: reference.transcript
                )
            )
        }
    }

    /// Public clone-preparation cache key. Mirrors the engine-support
    /// signature so production callers can switch to this copy without
    /// changing arguments. Format:
    /// "<modelID>|clone|<conditioningMode>|<audioPath>|<transcript>".
    public static func clonePreparationKey(modelID: String, reference: CloneReference) -> String {
        cloneReferenceIdentityKey(
            modelID: modelID,
            refAudio: reference.audioPath,
            refText: reference.transcript
        )
    }

    private static func normalizedDesignConditioningComponents(
        language: String,
        voiceDescription: String,
        emotion: String?
    ) -> (language: String, instruction: String) {
        let normalizedLanguage = language
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let resolvedInstruction = englishDictionReinforcedInstruction(
            baseInstruction: designInstruction(
                voiceDescription: voiceDescription,
                emotion: emotion ?? ""
            ),
            language: normalizedLanguage
        ) ?? ""
        return (
            normalizedLanguage,
            normalizedConditioningCacheKeyText(resolvedInstruction)
        )
    }

    private static func canonicalIdentitySerialization(
        namespace: String,
        components: [String]
    ) -> String {
        ([namespace] + components).map { component in
            "\(component.utf8.count):\(component)"
        }.joined()
    }

    private static func canonicalIdentityDigest(_ serialization: String) -> String {
        SHA256.hash(data: Data(serialization.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private static func detectedQwenLanguage(in text: String) -> Qwen3SupportedLanguage? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        if trimmed.unicodeScalars.contains(where: \.isJapaneseScalar) {
            return .japanese
        }
        if trimmed.unicodeScalars.contains(where: \.isHangulScalar) {
            return .korean
        }
        if trimmed.unicodeScalars.contains(where: \.isCyrillicScalar) {
            return .russian
        }
        if trimmed.unicodeScalars.contains(where: \.isCJKScalar) {
            return .chinese
        }
        // Latin scripts are indistinguishable by Unicode range — resolve
        // French/German/Spanish/Portuguese/Italian/English via the shared
        // NLLanguageRecognizer detector (confidence-gated; .auto when
        // ambiguous). Without this, Built-in Voice fell back to the english
        // language token for ANY Latin-script text under Auto — misdirecting
        // e.g. French text AND wrongly appending the English diction
        // reinforcement to its delivery instruction. (Official guidance:
        // an explicit language outperforms Auto.)
        let recognized = PromptLanguageDetector.detect(trimmed)
        return recognized == .auto ? nil : recognized
    }
}

private extension String {
    func trimmingTerminalSentencePunctuation() -> String {
        trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: ".!?。！？"))
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private extension UnicodeScalar {
    var isCJKScalar: Bool {
        switch value {
        case 0x3400 ... 0x4DBF, 0x4E00 ... 0x9FFF, 0xF900 ... 0xFAFF:
            return true
        default:
            return false
        }
    }

    var isJapaneseScalar: Bool {
        switch value {
        case 0x3040 ... 0x309F, 0x30A0 ... 0x30FF:
            return true
        default:
            return false
        }
    }

    var isHangulScalar: Bool {
        switch value {
        case 0x1100 ... 0x11FF, 0x3130 ... 0x318F, 0xAC00 ... 0xD7AF:
            return true
        default:
            return false
        }
    }

    var isArabicScalar: Bool {
        switch value {
        case 0x0600 ... 0x06FF, 0x0750 ... 0x077F, 0x08A0 ... 0x08FF:
            return true
        default:
            return false
        }
    }

    var isDevanagariScalar: Bool {
        switch value {
        case 0x0900 ... 0x097F:
            return true
        default:
            return false
        }
    }

    var isCyrillicScalar: Bool {
        switch value {
        case 0x0400 ... 0x04FF, 0x0500 ... 0x052F:
            return true
        default:
            return false
        }
    }

    var isLatinLetterScalar: Bool {
        switch value {
        case 0x0041 ... 0x005A, 0x0061 ... 0x007A:
            return true
        default:
            return false
        }
    }
}
