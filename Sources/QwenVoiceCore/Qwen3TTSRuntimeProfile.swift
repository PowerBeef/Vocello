import Foundation
import QwenVoiceBackendCore

enum Qwen3TTSRuntimeProfileError: LocalizedError, Sendable {
    case missingFile(String)
    case invalidMetadata(String)
    case unsupportedCapability(String)
    case disallowedVoiceImitation(String)

    var errorDescription: String? {
        switch self {
        case .missingFile(let message),
             .invalidMetadata(let message),
             .unsupportedCapability(let message),
             .disallowedVoiceImitation(let message):
            return message
        }
    }
}

enum Qwen3TTSModelFamily: String, Codable, Hashable, Sendable {
    case customVoice = "custom_voice"
    case voiceDesign = "voice_design"
    case baseClone = "base_clone"

    init?(descriptor: ModelDescriptor, configModelType: String?) {
        let joined = [
            descriptor.folder,
            descriptor.huggingFaceRepo,
            configModelType ?? "",
        ]
        .joined(separator: "|")
        .lowercased()

        if joined.contains("customvoice") || joined.contains("custom_voice") {
            self = .customVoice
        } else if joined.contains("voicedesign") || joined.contains("voice_design") {
            self = .voiceDesign
        } else if joined.contains("base") {
            self = .baseClone
        } else {
            return nil
        }
    }

    var requiredMode: GenerationMode {
        switch self {
        case .customVoice:
            return .custom
        case .voiceDesign:
            return .design
        case .baseClone:
            return .clone
        }
    }
}

private extension Qwen3TTSFamilyType {
    var runtimeFamily: Qwen3TTSModelFamily {
        switch self {
        case .customVoice:
            return .customVoice
        case .voiceDesign:
            return .voiceDesign
        case .baseClone:
            return .baseClone
        }
    }
}

enum Qwen3TTSQuantizationTier: String, Codable, Hashable, Sendable {
    case fourBit = "4bit"
    case eightBit = "8bit"
    case hybrid = "hybrid"
    case unknown
}

struct Qwen3TTSGenerationDefaults: Hashable, Codable, Sendable {
    let maxTokens: Int?
    let topK: Int?
    let topP: Double?
    let doSample: Bool?
    let temperature: Double?
    let repetitionPenalty: Double?

    var source: Qwen3TTSGenerationDefaultSource {
        maxTokens == nil ? .wrapperFallback : .checkpoint
    }
}

struct Qwen3TTSRuntimeProfile: Hashable, Codable, Sendable {
    static let canonicalSampleRate = 24_000
    static let canonicalTokenizerType = "qwen3_tts_tokenizer_12hz"

    static let criticalRequiredComponents: [String] = [
        "config.json",
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "model.safetensors.index.json",
        "preprocessor_config.json",
        "speech_tokenizer/config.json",
        "speech_tokenizer/configuration.json",
        "speech_tokenizer/model.safetensors",
        "speech_tokenizer/preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
    ]

    let modelType: String
    let modelFamily: Qwen3TTSModelFamily
    let quantizationTier: Qwen3TTSQuantizationTier
    let sampleRate: Int
    let tokenizerType: String
    let languageSupport: [String]
    let modeCapability: GenerationMode
    let supportsStreaming: Bool
    let requiredComponents: [String]
    let supportedSpeakers: [String]
    let generationDefaults: Qwen3TTSGenerationDefaults
    let modelSize: Qwen3TTSModelSize?
    let supportsInstructionControl: Bool
    let supportsXVectorOnlyClone: Bool
    let validationSignature: String

    static func load(
        from modelDirectory: URL,
        descriptor: ModelAssetDescriptor,
        fileManager: FileManager = .default
    ) throws -> Qwen3TTSRuntimeProfile {
        let configURL = modelDirectory.appendingPathComponent("config.json")
        let generationConfigURL = modelDirectory.appendingPathComponent("generation_config.json")

        guard fileManager.fileExists(atPath: configURL.path) else {
            throw Qwen3TTSRuntimeProfileError.missingFile("Missing Qwen3-TTS config.json at '\(configURL.path)'.")
        }
        guard fileManager.fileExists(atPath: generationConfigURL.path) else {
            throw Qwen3TTSRuntimeProfileError.missingFile("Missing Qwen3-TTS generation_config.json at '\(generationConfigURL.path)'.")
        }

        let config = try readJSONObject(configURL)
        let generationConfig = try readJSONObject(generationConfigURL)
        let profile = try fromConfig(
            config,
            generationConfig: generationConfig,
            descriptor: descriptor
        )
        try profile.validate(
            descriptor: descriptor.model,
            modelDirectory: modelDirectory,
            fileManager: fileManager
        )
        return profile
    }

    static func fromConfig(
        _ config: [String: Any],
        generationConfig: [String: Any],
        descriptor: ModelAssetDescriptor
    ) throws -> Qwen3TTSRuntimeProfile {
        let modelType = normalizedModelType(string(config["model_type"]) ?? "qwen3_tts")
        guard modelType == "qwen3_tts" else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "QwenVoice supports only Qwen3-TTS model metadata (expected model_type qwen3_tts, found \(modelType))."
            )
        }

        guard let modelFamily = Qwen3TTSModelFamily(
            descriptor: descriptor.model,
            configModelType: string(config["tts_model_type"])
        ) else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Could not infer Qwen3-TTS family from model '\(descriptor.model.id)' folder/repo/config."
            )
        }

        let tokenizerType = normalizedModelType(
            string(config["tokenizer_type"]) ?? Self.canonicalTokenizerType
        )
        let sampleRate = int(config["sample_rate"])
            ?? int(nested(config, "tokenizer_config")?["output_sample_rate"])
            ?? Self.canonicalSampleRate
        let languages = normalizedLanguageSupport(from: nested(config, "talker_config")?["codec_language_id"])
        let speakers = normalizedSpeakerIDs(from: nested(config, "talker_config")?["spk_id"])
        let quantization = quantizationTier(
            descriptor: descriptor.model,
            config: config
        )
        let modelSize = qwenModelSize(string(config["tts_model_size"]))
        let generationDefaults = Qwen3TTSGenerationDefaults(
            maxTokens: int(generationConfig["max_new_tokens"])
                ?? int(generationConfig["max_tokens"]),
            topK: int(generationConfig["top_k"]),
            topP: double(generationConfig["top_p"]),
            doSample: bool(generationConfig["do_sample"]),
            temperature: double(generationConfig["temperature"]),
            repetitionPenalty: double(generationConfig["repetition_penalty"])
        )
        let requiredComponents = Self.criticalRequiredComponents
        let derivedSupportsInstructionControl =
            modelFamily == .voiceDesign
            || (modelFamily == .customVoice && modelSize != .compact0b6)
        let supportsXVectorOnlyClone = descriptor.model.qwen3Capabilities?
            .supportsXVectorOnlyClone ?? false
        let signatureParts = [
            modelType,
            modelFamily.rawValue,
            quantization.rawValue,
            String(sampleRate),
            tokenizerType,
            languages.joined(separator: ","),
            speakers.joined(separator: ","),
            modelSize?.rawValue ?? "unknown",
            derivedSupportsInstructionControl ? "instruction" : "no_instruction",
            supportsXVectorOnlyClone ? "x_vector_only_clone" : "no_x_vector_only_clone",
        ]

        return Qwen3TTSRuntimeProfile(
            modelType: modelType,
            modelFamily: modelFamily,
            quantizationTier: quantization,
            sampleRate: sampleRate,
            tokenizerType: tokenizerType,
            languageSupport: languages,
            modeCapability: modelFamily.requiredMode,
            supportsStreaming: true,
            requiredComponents: requiredComponents,
            supportedSpeakers: speakers,
            generationDefaults: generationDefaults,
            modelSize: modelSize,
            supportsInstructionControl: derivedSupportsInstructionControl,
            supportsXVectorOnlyClone: supportsXVectorOnlyClone,
            validationSignature: signatureParts.joined(separator: "|")
        )
    }

    func validateCapability(_ requestedCapability: NativeLoadCapabilityProfile) throws {
        let expectedMode = switch requestedCapability {
        case .customOnly:
            GenerationMode.custom
        case .designOnly:
            GenerationMode.design
        case .cloneOnly:
            GenerationMode.clone
        case .fullCapabilities:
            modeCapability
        }

        guard expectedMode == modeCapability else {
            throw Qwen3TTSRuntimeProfileError.unsupportedCapability(
                "Qwen3-TTS \(modelFamily.rawValue) model cannot serve \(requestedCapability.rawValue)."
            )
        }
    }

    func validateSpeaker(_ speaker: String) throws {
        let normalized = Self.normalizedCacheText(speaker)
        guard !normalized.isEmpty else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata("Built-in Voice requires a non-empty Qwen3 speaker.")
        }
        guard supportedSpeakers.isEmpty || supportedSpeakers.contains(normalized) else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Unsupported Qwen3 speaker '\(speaker)'. Supported speakers: \(supportedSpeakers.joined(separator: ", "))."
            )
        }
    }

    func validatePromptText(_ value: String, label: String) throws {
        let normalized = Self.normalizedCacheText(value)
        guard !normalized.isEmpty else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata("\(label) must not be empty.")
        }
        guard !Self.containsDisallowedVoiceImitationInstruction(normalized) else {
            throw Qwen3TTSRuntimeProfileError.disallowedVoiceImitation(
                "\(label) cannot request celebrity imitation or voice impersonation."
            )
        }
    }

    func diagnosticStringFlags() -> [String: String] {
        [
            "qwen3_model_family": modelFamily.rawValue,
            "qwen3_quantization_tier": quantizationTier.rawValue,
            "qwen3_tokenizer_type": tokenizerType,
            "qwen3_mode_capability": modeCapability.rawValue,
            "qwen3_model_size": modelSize?.rawValue ?? "unknown",
            "qwen3_supports_instruction_control": supportsInstructionControl ? "true" : "false",
            "qwen3_supports_x_vector_only_clone": supportsXVectorOnlyClone ? "true" : "false",
            "qwen3_runtime_profile_signature": validationSignature,
            "qwen3_sample_rate": String(sampleRate),
            "qwen3_supported_speaker_count": String(supportedSpeakers.count),
            "qwen3_generation_config_source": generationDefaults.source.rawValue,
            "qwen3_generation_defaults_source": Qwen3TTSGenerationDefaultSource.appPolicy.rawValue,
            "qwen3_checkpoint_max_new_tokens": String(generationDefaults.maxTokens ?? Qwen3GenerationConfiguration.checkpointDefaultMaxNewTokens),
            "qwen3_wrapper_fallback_max_new_tokens": String(Qwen3GenerationConfiguration.wrapperFallbackMaxNewTokens),
            "qwen3_app_policy_max_new_tokens": String(Qwen3GenerationConfiguration.officialQualityDefault.maxNewTokens),
            "qwen3_top_k": String(generationDefaults.topK ?? Qwen3GenerationConfiguration.officialQualityDefault.topK),
            "qwen3_do_sample": String(generationDefaults.doSample ?? Qwen3GenerationConfiguration.officialQualityDefault.doSample),
        ]
    }

    private func validate(
        descriptor: ModelDescriptor,
        modelDirectory: URL,
        fileManager: FileManager
    ) throws {
        guard descriptor.folder.localizedCaseInsensitiveContains("Qwen3-TTS"),
              descriptor.huggingFaceRepo.localizedCaseInsensitiveContains("Qwen3-TTS") else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Model '\(descriptor.id)' must use Qwen3-TTS folder and repository metadata."
            )
        }
        guard descriptor.mode == modeCapability else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Model '\(descriptor.id)' is declared for \(descriptor.mode.rawValue) but its Qwen3-TTS family supports \(modeCapability.rawValue)."
            )
        }
        if let capabilities = descriptor.qwen3Capabilities {
            guard capabilities.familyType.runtimeFamily == modelFamily else {
                throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                    "Model '\(descriptor.id)' declares Qwen3 family \(capabilities.familyType.rawValue) but config resolves \(modelFamily.rawValue)."
                )
            }
            guard capabilities.supportsInstructionControl == supportsInstructionControl else {
                throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                    "Model '\(descriptor.id)' declares supportsInstructionControl=\(capabilities.supportsInstructionControl) but runtime metadata derives \(supportsInstructionControl)."
                )
            }
            guard capabilities.supportsVoiceClone == (modelFamily == .baseClone) else {
                throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                    "Model '\(descriptor.id)' declares supportsVoiceClone=\(capabilities.supportsVoiceClone) but runtime family \(modelFamily.rawValue) expects \((modelFamily == .baseClone))."
                )
            }
            guard capabilities.supportsXVectorOnlyClone == (modelFamily == .baseClone) else {
                throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                    "Model '\(descriptor.id)' declares supportsXVectorOnlyClone=\(capabilities.supportsXVectorOnlyClone) but runtime family \(modelFamily.rawValue) expects \((modelFamily == .baseClone))."
                )
            }
            guard capabilities.requiresSpeakerEncoder == (modelFamily == .baseClone) else {
                throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                    "Model '\(descriptor.id)' declares requiresSpeakerEncoder=\(capabilities.requiresSpeakerEncoder) but runtime family \(modelFamily.rawValue) expects \((modelFamily == .baseClone))."
                )
            }
            if let modelSize {
                guard capabilities.modelSize == modelSize else {
                    throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                        "Model '\(descriptor.id)' declares Qwen3 size \(capabilities.modelSize.rawValue) but config resolves \(modelSize.rawValue)."
                    )
                }
            }
        }
        guard sampleRate == Self.canonicalSampleRate else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "QwenVoice expects Qwen3-TTS 24 kHz output; model '\(descriptor.id)' declares \(sampleRate) Hz."
            )
        }
        guard tokenizerType == Self.canonicalTokenizerType else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "QwenVoice expects \(Self.canonicalTokenizerType); model '\(descriptor.id)' declares \(tokenizerType)."
            )
        }

        let descriptorRequiredPaths = Set(descriptor.requiredRelativePaths)
        let missingDescriptorRequirements = requiredComponents.filter {
            !descriptorRequiredPaths.contains($0)
        }
        guard missingDescriptorRequirements.isEmpty else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Model '\(descriptor.id)' is missing Qwen3-TTS required contract paths: \(missingDescriptorRequirements.joined(separator: ", "))."
            )
        }

        let missingFiles = requiredComponents.filter {
            !fileManager.fileExists(atPath: modelDirectory.appendingPathComponent($0).path)
        }
        guard missingFiles.isEmpty else {
            throw Qwen3TTSRuntimeProfileError.missingFile(
                "Installed Qwen3-TTS model '\(descriptor.id)' is missing files: \(missingFiles.joined(separator: ", "))."
            )
        }
    }

    static func normalizedLanguage(_ raw: String?) -> String {
        Qwen3SupportedLanguage.normalized(raw).rawValue
    }

    static func normalizedCacheText(_ raw: String) -> String {
        raw
            .replacingOccurrences(
                of: #"\s+"#,
                with: " ",
                options: .regularExpression
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    /// Explicit impersonation / celebrity-imitation intent guard across all 10
    /// supported languages (P02-10, RF-73 / D2). Refuses impersonation intent
    /// phrases without maintaining a celebrity-name blocklist, and allows
    /// ordinary character/archetype descriptions introduced by an indefinite
    /// article (e.g. "in the voice of an old sea captain", "dans la voix d'un
    /// vieux capitaine").
    static func containsDisallowedVoiceImitationInstruction(_ normalizedText: String) -> Bool {
        let markers = [
            // English
            "celebrity",
            "impersonat",
            "imitate the voice",
            "clone the voice",
            "mimic the voice",
            // French
            "célébrité",
            "celebrite",
            "usurper",
            "imiter la voix",
            "imite la voix",
            "cloner la voix",
            "clone la voix",
            "se faire passer pour",
            // Spanish
            "celebridad",
            "suplantar",
            "imitar la voz",
            "imita la voz",
            "clonar la voz",
            "clona la voz",
            "hacerse pasar por",
            // German
            "prominente stimme",
            "prominente person",
            "einen prominenten",
            "einer prominenten",
            "promi-stimme",
            "promistimme",
            "stimme imitieren",
            "stimme nachahmen",
            "stimme klonen",
            "ausgeben als",
            // Italian
            "celebrità",
            "celebrita",
            "impersonare",
            "imitare la voce",
            "imita la voce",
            "clonare la voce",
            "clona la voce",
            "spacciarsi per",
            // Portuguese
            "celebridade",
            "fingir ser",
            "imitar a voz",
            "imita a voz",
            "clonar a voz",
            "clona a voz",
            "se passar por",
            // Chinese (Simplified & Traditional)
            "名人",
            "明星",
            "冒充",
            "假冒",
            "模仿他人",
            "模仿别人",
            "模仿別人",
            "模仿某人",
            "模仿本人",
            "克隆他人",
            "克隆别人",
            "克隆別人",
            "克隆某人",
            "克隆本人",
            // Japanese
            "有名人",
            "芸能人",
            "なりすまし",
            "なりすます",
            "ものまね",
            "モノマネ",
            "声真似",
            "声まね",
            "声を真似",
            "声をまね",
            "声をクローン",
            "声をコピー",
            // Korean
            "유명인",
            "연예인",
            "사칭",
            "성대모사",
            "목소리 흉내",
            "목소리를 흉내",
            "목소리 모방",
            "목소리를 모방",
            "목소리 복제",
            "목소리를 복제",
            // Russian
            "знаменитост",
            "выдавать себя за",
            "имитировать голос",
            "имитируй голос",
            "подражать голосу",
            "клонировать голос",
            "клонируй голос",
        ]
        if markers.contains(where: { normalizedText.contains($0) }) { return true }
        // P02-10 & RF-73/D2: a named-likeness phrase names someone unless an
        // indefinite article follows it. "In the voice of an old sea captain"
        // and "sound just like a bedtime story" describe a character or mood
        // and are allowed; "in the voice of morgan freeman" and "sounds exactly
        // like my boss" are not.
        let likenessPatterns = [
            // English
            #"\b(?:sound(?:s|ing)? (?:exactly|just) like|in the voice of) (?!(?:a|an) )"#,
            // French (exempts un/une/des and elided d'un/d'une while catching named d'Emmanuel)
            #"\b(?:(?:dans|avec) la voix (?:de (?!(?:un|une|des) )|d['’](?!(?:un|une) ))|exactement comme (?!(?:un|une|des) ))"#,
            // Spanish
            #"\b(?:con la voz de|en la voz de|suena (?:exactamente|igual) (?:a|que)) (?!(?:un|una|unos|unas) )"#,
            // German
            #"\b(?:mit der stimme von|in der stimme von|klingt genau wie) (?!(?:ein|eine|einem|einer|einen) )"#,
            // Italian (exempts un/una/uno + space and elided un'/un’ attached directly to a vowel)
            #"\b(?:con la voce di|nella voce di|suona esattamente come) (?!(?:(?:un|una|uno) |un['’]))"#,
            // Portuguese
            #"\b(?:com a voz de|na voz de|soa exatamente como) (?!(?:um|uma|uns|umas) )"#,
            // Russian (explicit personal/known-person target; Russian lacks indefinite articles)
            #"(?:^|\s)точно как голос (?:моего|моей|нашего|реального|известного)\b"#,
        ]
        return likenessPatterns.contains { pattern in
            normalizedText.range(of: pattern, options: .regularExpression) != nil
        }
    }

    private static func readJSONObject(_ url: URL) throws -> [String: Any] {
        let data = try Data(contentsOf: url)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw Qwen3TTSRuntimeProfileError.invalidMetadata(
                "Expected JSON object at '\(url.path)'."
            )
        }
        return object
    }

    private static func normalizedModelType(_ value: String) -> String {
        value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
    }

    private static func normalizedLanguageSupport(from raw: Any?) -> [String] {
        guard let map = raw as? [String: Any] else {
            return ["auto", "english", "chinese"]
        }
        let languages = Set(map.keys.map(normalizedLanguage))
        return languages.sorted()
    }

    private static func normalizedSpeakerIDs(from raw: Any?) -> [String] {
        guard let map = raw as? [String: Any] else {
            return []
        }
        return map.keys.map(normalizedCacheText).filter { !$0.isEmpty }.sorted()
    }

    private static func hasPerLayerQuantizationOverrides(_ config: [String: Any]) -> Bool {
        // Uniform 4-bit checkpoints keep 8-bit `model.text_embedding` (Stage 2.2)
        // without being hybrid models; align with `Qwen3TTSLoading.isHybridCheckpoint`.
        let nonHybridKeys: Set<String> = [
            "bits", "group_size", "mode", "quant_method", "linear_class", "quantization_mode",
            "model.text_embedding",
        ]
        for containerKey in ["quantization", "quantization_config"] {
            guard let quant = nested(config, containerKey) else { continue }
            let defaultBits = int(quant["bits"])
            for (key, value) in quant where !nonHybridKeys.contains(key) {
                if let boolValue = value as? Bool, !boolValue {
                    return true
                }
                if let layerMap = value as? [String: Any] {
                    if let layerBits = int(layerMap["bits"]),
                       let defaultBits,
                       layerBits != defaultBits {
                        return true
                    }
                    if defaultBits == nil {
                        return true
                    }
                }
            }
        }
        return false
    }

    static func quantizationTier(
        descriptor: ModelDescriptor,
        config: [String: Any]
    ) -> Qwen3TTSQuantizationTier {
        if hasPerLayerQuantizationOverrides(config) {
            return .hybrid
        }
        let identity = "\(descriptor.folder)|\(descriptor.huggingFaceRepo)".lowercased()
        if identity.contains("-hybrid-") {
            return .hybrid
        }
        if identity.contains("4bit") {
            return .fourBit
        }
        if identity.contains("8bit") {
            return .eightBit
        }
        if let bits = int(nested(config, "quantization")?["bits"])
            ?? int(nested(config, "quantization_config")?["bits"]) {
            if bits == 4 {
                return .fourBit
            }
            if bits == 8 {
                return .eightBit
            }
        }
        return .unknown
    }

    private static func qwenModelSize(_ value: String?) -> Qwen3TTSModelSize? {
        switch normalizedModelType(value ?? "") {
        case "0b6", "0.6b", "600m":
            return .compact0b6
        case "1b7", "1.7b":
            return .pro1b7
        default:
            return nil
        }
    }

    private static func nested(_ object: [String: Any], _ key: String) -> [String: Any]? {
        object[key] as? [String: Any]
    }

    private static func string(_ value: Any?) -> String? {
        value as? String
    }

    private static func int(_ value: Any?) -> Int? {
        if let intValue = value as? Int {
            return intValue
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String {
            return Int(string)
        }
        return nil
    }

    private static func double(_ value: Any?) -> Double? {
        if let doubleValue = value as? Double {
            return doubleValue
        }
        if let number = value as? NSNumber {
            return number.doubleValue
        }
        if let string = value as? String {
            return Double(string)
        }
        return nil
    }

    private static func bool(_ value: Any?) -> Bool? {
        if let boolValue = value as? Bool {
            return boolValue
        }
        if let number = value as? NSNumber {
            return number.boolValue
        }
        if let string = value as? String {
            switch string.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            case "true", "yes", "1":
                return true
            case "false", "no", "0":
                return false
            default:
                return nil
            }
        }
        return nil
    }
}
