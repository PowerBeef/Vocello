import Foundation
import QwenVoiceCore

enum TTSModelVariantKind: String, CaseIterable, Codable, Hashable, Sendable {
    case compactSpeed = "compact_speed"
    case compactQuality = "compact_quality"
    case speed
    case quality

    var displayName: String {
        switch self {
        case .compactSpeed: return "Lite"
        case .compactQuality: return "Lite+"
        case .speed: return "Speed"
        case .quality: return "Quality"
        }
    }

    var bitDepthLabel: String {
        switch self {
        case .compactSpeed: return "0.6B 4-bit"
        case .compactQuality: return "0.6B 8-bit"
        case .speed: return "1.7B 4-bit"
        case .quality: return "1.7B 8-bit"
        }
    }

    var variantLabel: String {
        "\(displayName) variant"
    }
}

/// Represents a TTS model that can be downloaded and used for generation.
struct TTSModel: Identifiable, Hashable, Sendable, Codable {
    let id: String          // e.g. "pro_custom"
    let name: String        // e.g. "Built-in Voice"
    let tier: String        // e.g. "pro"
    let folder: String      // e.g. "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
    let mode: GenerationMode
    let huggingFaceRepo: String
    let huggingFaceRevision: String?
    let artifactVersion: String
    let outputSubfolder: String
    let requiredRelativePaths: [String]
    let baseModelID: String
    let variantID: String?
    let variantKind: TTSModelVariantKind?
    let estimatedDownloadBytes: Int64?
    let isHardwareRecommended: Bool
    let qwen3Capabilities: Qwen3TTSModelCapabilities?

    init(
        id: String,
        name: String,
        tier: String,
        folder: String,
        mode: GenerationMode,
        huggingFaceRepo: String,
        huggingFaceRevision: String? = nil,
        artifactVersion: String = "",
        outputSubfolder: String,
        requiredRelativePaths: [String],
        baseModelID: String? = nil,
        variantID: String? = nil,
        variantKind: TTSModelVariantKind? = nil,
        estimatedDownloadBytes: Int64? = nil,
        isHardwareRecommended: Bool = false,
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
        self.outputSubfolder = outputSubfolder
        self.requiredRelativePaths = requiredRelativePaths
        self.baseModelID = baseModelID ?? id
        self.variantID = variantID
        self.variantKind = variantKind
        self.estimatedDownloadBytes = estimatedDownloadBytes
        self.isHardwareRecommended = isHardwareRecommended
        self.qwen3Capabilities = qwen3Capabilities
    }

    var supportsInstructionControl: Bool {
        qwen3Capabilities?.supportsInstructionControl ?? false
    }

    var supportsVoiceClone: Bool {
        qwen3Capabilities?.supportsVoiceClone ?? (mode == .clone)
    }

    var modelSizeLabel: String? {
        switch qwen3Capabilities?.modelSize {
        case .compact0b6:
            return "0.6B"
        case .pro1b7:
            return "1.7B"
        case nil:
            return nil
        }
    }
}

enum MacModelVariantPreferences {
    private static let keyPrefix = "QwenVoice.MacModelVariantPreference."
    /// Global override: when set to true, every per-mode variant lookup
    /// resolves to the active Speed variant regardless of the per-mode
    /// stored choice or the hardware-recommended default. The legacy key
    /// name is retained for existing preferences.
    static let preferSpeedEverywhereKey = "QwenVoice.PreferSpeedEverywhere"

    static func key(for mode: GenerationMode) -> String {
        keyPrefix + mode.rawValue
    }

    static func selectedVariantID(
        for mode: GenerationMode,
        defaultVariantID: String?,
        defaults: UserDefaults = AppDefaults.store
    ) -> String? {
        let stored = defaults.string(forKey: key(for: mode))?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let stored, !stored.isEmpty else {
            return defaultVariantID
        }
        return stored
    }

    static func setSelectedVariantID(
        _ variantID: String,
        for mode: GenerationMode,
        defaults: UserDefaults = AppDefaults.store
    ) {
        defaults.set(variantID, forKey: key(for: mode))
    }

    static func clearSelectedVariantID(
        for mode: GenerationMode,
        defaults: UserDefaults = AppDefaults.store
    ) {
        defaults.removeObject(forKey: key(for: mode))
    }

    static func preferSpeedEverywhere(defaults: UserDefaults = AppDefaults.store) -> Bool {
        defaults.bool(forKey: preferSpeedEverywhereKey)
    }

    static func setPreferSpeedEverywhere(
        _ value: Bool,
        defaults: UserDefaults = AppDefaults.store
    ) {
        defaults.set(value, forKey: preferSpeedEverywhereKey)
    }
}

enum GenerationMode: String, CaseIterable, Codable, Hashable, Sendable {
    case custom
    case design
    case clone

    var displayName: String {
        switch self {
        // User-facing rename 2026-08-15 (maintainer call): the mode named after
        // upstream's CustomVoice checkpoint reads as "Built-in Voice" — it
        // speaks with the built-in speakers, and "Custom" confused end users.
        // Every internal identity stays `custom` (mode rawValue, model ID
        // pro_custom, bench cells, telemetry, accessibility identifiers).
        case .custom: return "Built-in Voice"
        case .design: return "Voice Design"
        case .clone: return "Voice Cloning"
        }
    }

    var iconName: String {
        switch self {
        case .custom: return "person.wave.2"
        case .design: return "text.bubble"
        case .clone: return "waveform.badge.plus"
        }
    }
}

// MARK: - Model Registry

extension TTSModel {
    static var all: [TTSModel] { TTSContract.models }

    /// Find the model for a given generation mode
    static func model(for mode: GenerationMode) -> TTSModel? {
        TTSContract.model(for: mode)
    }

    static func model(id: String) -> TTSModel? {
        TTSContract.model(id: id)
    }

    func installDirectory(in modelsDirectory: URL) -> URL {
        modelsDirectory.appendingPathComponent(folder, isDirectory: true)
    }

    func isAvailable(in modelsDirectory: URL, fileManager: FileManager = .default) -> Bool {
        let installDirectory = installDirectory(in: modelsDirectory)
        return requiredRelativePaths.allSatisfy { relativePath in
            let fileURL = installDirectory.appendingPathComponent(relativePath)
            return fileManager.fileExists(atPath: fileURL.path)
        }
    }

    static var speakerGroups: [String: [String]] { TTSContract.groupedSpeakers }

    static var defaultSpeaker: String { TTSContract.defaultSpeaker }

    static var speakers: [String] { TTSContract.allSpeakers }

    static var allSpeakers: [String] { TTSContract.allSpeakers }

    static var allSpeakerDescriptors: [SpeakerDescriptor] {
        TTSContract.allSpeakerDescriptors
    }

    static func speakerDescriptor(id: String) -> SpeakerDescriptor? {
        TTSContract.speakerDescriptor(id: id)
    }

    static func speakerPickerLabel(for id: String) -> String {
        speakerDescriptor(id: id)?.annotatedDisplayName ?? id.capitalized
    }

    static func qwenLanguage(forSpeaker id: String) -> Qwen3SupportedLanguage {
        Qwen3SupportedLanguage.nativeLanguage(speakerDescriptor(id: id)?.nativeLanguage)
    }
}
