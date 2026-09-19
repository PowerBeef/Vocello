import Foundation

enum MacBatchSegmentationMode: String, Equatable {
    case lineSeparated
    case longForm
}

enum LongTextGenerationRouter {
    static let directGenerationCharacterLimit = GenerationTextLimitPolicy.singleTakeScriptLimit

    static func shouldRouteToLongFormBatch(_ text: String) -> Bool {
        text.count > directGenerationCharacterLimit
    }

    /// Explicit line-by-line takes precedence; otherwise both platforms use
    /// the shared character threshold. Nil means an ordinary single take.
    static func batchMode(for text: String, lineByLine: Bool) -> MacBatchSegmentationMode? {
        if lineByLine { return .lineSeparated }
        return shouldRouteToLongFormBatch(text) ? .longForm : nil
    }
}
