import Foundation
import QwenVoiceCore

/// Value types of the macOS line batch (`MacLineBatchRunner`): the request the
/// sheet assembles from a `MacBatchSheetConfiguration`, the per-line item, the
/// progress the sheet renders and the terminal outcome. Everything here is
/// pure so the seed, identity, validation and retry derivations are testable
/// without an engine (the runner file adds the `TTSModel` convenience).
struct MacLineBatchItem: Identifiable, Equatable {
    enum Status: Equatable {
        case pending
        case running
        case saved(audioPath: String)
        case failed(message: String)
        case cancelled
    }

    let id = UUID()
    let index: Int
    let line: String
    var status: Status
    var generationID: UUID?

    var audioPath: String? {
        if case .saved(let audioPath) = status { return audioPath }
        return nil
    }

    var isSaved: Bool {
        if case .saved = status { return true }
        return false
    }
}

struct MacLineBatchProgress: Equatable {
    var completedCount = 0
    var totalCount = 0
    var activeIndex: Int?
    var statusMessage = ""

    var fraction: Double {
        guard totalCount > 0 else { return 0 }
        return min(max(Double(completedCount) / Double(totalCount), 0), 1)
    }
}

enum MacLineBatchOutcome: Equatable {
    case completed(items: [MacLineBatchItem])
    case cancelled(items: [MacLineBatchItem], restartFailedMessage: String?)
    case failed(items: [MacLineBatchItem], message: String)

    var items: [MacLineBatchItem] {
        switch self {
        case .completed(let items), .cancelled(let items, _), .failed(let items, _):
            return items
        }
    }

    /// Lines that never produced a saved clip: pending, running or cancelled
    /// (a failed line is offered separately by `retryFailedLines`).
    var retryRemainingLines: [String] {
        items.compactMap { item in
            switch item.status {
            case .pending, .running, .cancelled:
                return item.line
            case .failed, .saved:
                return nil
            }
        }
    }

    var retryFailedLines: [String] {
        items.compactMap { item in
            if case .failed = item.status { return item.line }
            return nil
        }
    }

    var savedAudioPaths: [String] {
        items.compactMap(\.audioPath)
    }
}

struct MacLineBatchRequest {
    static let maxLines = 100

    let mode: GenerationMode
    let modelID: String
    let modelTier: String
    let outputSubfolder: String
    let supportsInstructionControl: Bool
    let lines: [String]
    let voice: String?
    let emotion: String?
    let deliveryInstructionCellID: String?
    let language: Qwen3SupportedLanguage
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    let preparedVoiceID: String?
    /// The Studio dock and inline card name for the voice (speaker display
    /// name, brief-derived name or saved voice / reference file name).
    let displayVoiceName: String
    let variation: Qwen3SamplingVariation?
    /// One sampling seed shared by every line of the batch (GitHub #30): the
    /// lines of one batch keep a steadier character and pacing than fully
    /// independent draws. Minted per run, so separate batches still differ.
    let batchSeed: UInt64

    init(
        mode: GenerationMode,
        modelID: String,
        modelTier: String,
        outputSubfolder: String,
        supportsInstructionControl: Bool,
        lines: [String],
        voice: String?,
        emotion: String?,
        deliveryInstructionCellID: String?,
        language: Qwen3SupportedLanguage,
        voiceDescription: String?,
        refAudio: String?,
        refText: String?,
        preparedVoiceID: String?,
        displayVoiceName: String,
        variation: Qwen3SamplingVariation?,
        batchSeed: UInt64 = UInt64.random(in: UInt64.min ... UInt64.max)
    ) {
        self.mode = mode
        self.modelID = modelID
        self.modelTier = modelTier
        self.outputSubfolder = outputSubfolder
        self.supportsInstructionControl = supportsInstructionControl
        self.lines = lines
        self.voice = voice
        self.emotion = emotion
        self.deliveryInstructionCellID = deliveryInstructionCellID
        self.language = language
        self.voiceDescription = voiceDescription
        self.refAudio = refAudio
        self.refText = refText
        self.preparedVoiceID = preparedVoiceID
        self.displayVoiceName = displayVoiceName
        self.variation = variation
        self.batchSeed = batchSeed
    }

    /// One line per non-blank row of the editor, trimmed of surrounding spaces.
    static func lines(from text: String) -> [String] {
        text.components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    func validationError(isModelAvailable: Bool, recoveryDetail: String) -> String? {
        guard isModelAvailable else { return recoveryDetail }
        if mode == .design && (voiceDescription ?? "").isEmpty {
            return MacInterfaceText.batchNeedsVoiceDescription
        }
        if mode == .clone && refAudio == nil {
            return MacInterfaceText.batchNeedsReference
        }
        return nil
    }

    /// History voice naming: custom → speaker, design → brief, clone → saved
    /// voice name or the reference file stem.
    var historyVoice: String? {
        switch mode {
        case .custom:
            return voice
        case .design:
            return voiceDescription
        case .clone:
            if let voice { return voice }
            if let refAudio {
                return URL(fileURLWithPath: refAudio).deletingPathExtension().lastPathComponent
            }
            return nil
        }
    }

    /// History delivery: custom only when the package supports instructions,
    /// design always, clone never.
    var historyEmotion: String? {
        switch mode {
        case .custom:
            return supportsInstructionControl ? emotion : nil
        case .design:
            return emotion
        case .clone:
            return nil
        }
    }

    var modeLabel: String { MacInterfaceText.modeName(mode) }

    /// The engine request for one line through `MacStudioGenerationRequestFactory`
    /// (streaming, the batch seed, the Settings variation, a fresh generation
    /// identity). Nil only for a clone line without a reference or a custom
    /// line without a speaker, which the configuration never produces.
    func generationRequest(line: String, outputPath: String, generationID: UUID = UUID()) -> GenerationRequest? {
        switch mode {
        case .custom:
            guard let voice else { return nil }
            return MacStudioGenerationRequestFactory.customVoice(
                modelID: modelID,
                text: line,
                outputPath: outputPath,
                language: language,
                speakerID: voice,
                deliveryStyle: supportsInstructionControl ? (emotion ?? EmotionPreset.neutralPresetInstruction) : nil,
                deliveryInstructionCellID: deliveryInstructionCellID,
                seed: batchSeed,
                variation: variation,
                generationID: generationID
            )
        case .design:
            return MacStudioGenerationRequestFactory.voiceDesign(
                modelID: modelID,
                text: line,
                outputPath: outputPath,
                language: language,
                voiceDescription: voiceDescription ?? "",
                deliveryStyle: emotion ?? EmotionPreset.neutralPresetInstruction,
                seed: batchSeed,
                variation: variation,
                generationID: generationID
            )
        case .clone:
            return MacStudioGenerationRequestFactory.voiceClone(
                modelID: modelID,
                text: line,
                outputPath: outputPath,
                language: language,
                referenceAudioPath: refAudio,
                referenceTranscript: refText,
                preparedVoiceID: preparedVoiceID,
                seed: batchSeed,
                variation: variation,
                generationID: generationID
            )
        }
    }
}
