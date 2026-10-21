import Foundation
import QwenVoiceCore

/// The Mac app's line batch plan (`MacLineBatchRequest`), for the CLI's
/// `generate --line-by-line`: one take per non-blank line with something to
/// speak, one batch seed shared by every line (a repeated line derives its own,
/// P11-10), one language for the whole script under Auto (U03), the Neutral
/// delivery when none is given (Design, and Custom on a package with instruction
/// control), and every line streamed at the app cadence.
public struct DesktopLineBatch: Sendable {
    /// The most lines the app runs as one batch.
    public static let maxLines = MacLineBatchRequest.maxLines

    /// The script's lines as the app splits it: trimmed, blank and unspeakable
    /// lines (separators such as `***`) skipped.
    public static func lines(from text: String) -> [String] {
        MacLineBatchRequest.lines(from: text)
    }

    private let plan: MacLineBatchRequest

    /// `batchSeed` nil draws one, as the app does without a pinned seed.
    public init(
        mode: GenerationMode, model: ModelDescriptor, lines: [String], payload: GenerationRequest.Payload,
        deliveryInstructionCellID: String?, language: Qwen3SupportedLanguage?, variation: Qwen3SamplingVariation?,
        batchSeed: UInt64?
    ) {
        var voice: String?
        var emotion: String?
        var voiceDescription: String?
        var reference: CloneReference?
        switch payload {
        case .custom(let speakerID, let deliveryStyle):
            voice = speakerID
            emotion = deliveryStyle
        case .design(let description, let deliveryStyle):
            voiceDescription = description
            emotion = deliveryStyle
        case .clone(let cloneReference):
            reference = cloneReference
        }
        plan = MacLineBatchRequest(
            mode: mode, modelID: model.id, modelTier: model.tier, outputSubfolder: model.outputSubfolder,
            supportsInstructionControl: model.supportsInstructionControl, lines: lines, voice: voice,
            emotion: emotion, deliveryInstructionCellID: deliveryInstructionCellID, language: language ?? .auto,
            voiceDescription: voiceDescription, refAudio: reference?.audioPath, refText: reference?.transcript,
            preparedVoiceID: reference?.preparedVoiceID, displayVoiceName: voice ?? mode.rawValue,
            variation: variation, batchSeed: batchSeed ?? UInt64.random(in: UInt64.min ... UInt64.max)
        )
    }

    public var lines: [String] { plan.lines }
    /// The language every line carries: the selection, or Auto resolved over the script.
    public var language: Qwen3SupportedLanguage { plan.language }
    public var batchSeed: UInt64 { plan.batchSeed }

    public func seed(forLineAt index: Int) -> UInt64 {
        plan.seed(forLineAt: index)
    }

    /// The engine request for the line at `index`, as the app builds it.
    public func request(forLineAt index: Int, outputPath: String, generationID: UUID) -> GenerationRequest? {
        guard plan.lines.indices.contains(index) else { return nil }
        return plan.generationRequest(
            line: plan.lines[index], outputPath: outputPath, generationID: generationID, lineIndex: index
        )
    }
}
