import Foundation
import QwenVoiceCore

/// Value types of the macOS line batch (`MacLineBatchRunner`): the request the
/// sheet assembles from a `MacBatchSheetConfiguration`, the per-line item, the
/// progress the sheet renders and the terminal outcome with the Studio attempt
/// transition it makes. Everything here runs without an engine, so the seed,
/// identity, validation, retry and terminal derivations are testable (the
/// runner file adds the `TTSModel` convenience).
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
    /// (a failed line is offered separately by `retryFailedItems`).
    var retryRemainingItems: [MacLineBatchItem] {
        items.filter { item in
            switch item.status {
            case .pending, .running, .cancelled:
                return true
            case .failed, .saved:
                return false
            }
        }
    }

    var retryFailedItems: [MacLineBatchItem] {
        items.filter { item in
            if case .failed = item.status { return true }
            return false
        }
    }

    var retryRemainingLines: [String] { retryRemainingItems.map(\.line) }

    var retryFailedLines: [String] { retryFailedItems.map(\.line) }

    var savedAudioPaths: [String] {
        items.compactMap(\.audioPath)
    }

    /// Makes the batch's Studio attempt terminal for this outcome: the dock
    /// card mirrors the last saved line, exactly like a single take; a failure
    /// surfaces its message. A cancelled batch closes its attempt too (A14-01):
    /// when the user cancelled, `finish` is a no-op and the engine barrier
    /// closes the attempt; when the engine cancelled the take itself (memory
    /// pressure), nothing else would, and the mode would stay generating.
    @MainActor
    func closeAttempt(
        _ attempt: StudioGenerationAttemptToken,
        on coordinator: StudioGenerationCoordinator,
        lastSaved: IOSStudioInlinePlayerItem?
    ) {
        switch self {
        case .completed:
            if let lastSaved {
                coordinator.complete(lastSaved, attempt: attempt)
            } else {
                coordinator.finish(attempt: attempt)
            }
        case .failed(_, let message):
            coordinator.fail(message, attempt: attempt)
        case .cancelled:
            coordinator.finish(attempt: attempt)
        }
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
    /// The language every line carries: the Studio selection, or under Auto
    /// the whole batch's language, resolved once over all its lines (U03), so
    /// a short line ("Ja.") is never detected on its own and misread.
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
    /// independent draws. The pinned Studio seed when there is one (U11);
    /// otherwise minted per run, so separate batches still differ.
    let batchSeed: UInt64
    /// A retry's own seed for each of its lines (aligned with `lines`), kept
    /// from the batch it retries (`retrySeeds(forLinesAt:failedLines:)`); nil
    /// derives every line's seed from `batchSeed`.
    let lineSeeds: [UInt64]?

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
        batchSeed: UInt64 = UInt64.random(in: UInt64.min ... UInt64.max),
        lineSeeds: [UInt64]? = nil
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
        self.language = Qwen3SupportedLanguage.normalized(
            StudioScriptLanguage.resolved(selection: language.rawValue, script: lines.joined(separator: "\n"))
        )
        self.voiceDescription = voiceDescription
        self.refAudio = refAudio
        self.refText = refText
        self.preparedVoiceID = preparedVoiceID
        self.displayVoiceName = displayVoiceName
        self.variation = variation
        self.batchSeed = batchSeed
        self.lineSeeds = lineSeeds?.count == lines.count ? lineSeeds : nil
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
        // Each line is one take, so a line past the single-take limit (the
        // composer would route it to long-form) is refused before anything
        // runs instead of exhausting its token budget and stopping the batch
        // partway (P01-04).
        if let overLongIndex = lines.firstIndex(where: GenerationTextLimitPolicy.exceedsSingleTake) {
            return MacInterfaceText.batchLineTooLongForOneTake(lineNumber: overLongIndex + 1)
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

    /// The seed of the line at `index`: the batch seed, so the batch keeps one
    /// character (GitHub #30). Sampling is seed-deterministic, so a line the
    /// batch repeats would come out byte-identical on it; each repeat derives
    /// its own seed from the batch seed instead (P11-10), and the batch still
    /// reproduces from its seed.
    func seed(forLineAt index: Int) -> UInt64 {
        guard lines.indices.contains(index) else { return batchSeed }
        if let lineSeeds { return lineSeeds[index] }
        let repeats = lines[..<index].count(where: { $0 == lines[index] })
        return (0..<repeats).reduce(batchSeed) { seed, _ in StudioRetakeSeed.after(seed) }
    }

    /// The seeds of a retry of this batch's lines at `indices`, each line's
    /// own: a retry numbers its lines afresh, so a repeat that never ran
    /// would otherwise take the seed of the copy already saved. Remaining
    /// lines never produced a take, so they keep their seeds. A failed line
    /// failed on its seed and would fail the same way on it again, so its
    /// retry derives a fresh one (U10); retrying again derives again. The
    /// salt keeps a retry's seed off the chain a repeated line draws from.
    func retrySeeds(forLinesAt indices: [Int], failedLines: Bool) -> [UInt64] {
        indices.map { index in
            let lineSeed = self.seed(forLineAt: index)
            return failedLines ? StudioRetakeSeed.after(lineSeed ^ Self.retrySeedSalt) : lineSeed
        }
    }

    private static let retrySeedSalt: UInt64 = 0x5245_5452_5953_4544 // "RETRYSED"

    /// The engine request for one line through `MacStudioGenerationRequestFactory`
    /// (streaming, the line's seed, the Settings variation, a fresh generation
    /// identity). `lineIndex` is the line's position in the batch, which picks
    /// its seed (`seed(forLineAt:)`); without one the line takes the batch
    /// seed. Nil only for a clone line without a reference or a custom line
    /// without a speaker, which the configuration never produces.
    func generationRequest(
        line: String,
        outputPath: String,
        generationID: UUID = UUID(),
        lineIndex: Int? = nil
    ) -> GenerationRequest? {
        let lineSeed = lineIndex.map(seed(forLineAt:)) ?? batchSeed
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
                seed: lineSeed,
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
                seed: lineSeed,
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
                seed: lineSeed,
                variation: variation,
                generationID: generationID
            )
        }
    }
}
