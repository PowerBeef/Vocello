import Foundation

enum MacBatchSegmentationMode: String, Equatable {
    case lineSeparated
    case longForm
}

enum LongTextGenerationRouter {
    static let directGenerationCharacterLimit = GenerationTextLimitPolicy.singleTakeScriptLimit

    /// The shared single-take predicate (U01): a script whose single-take
    /// length (CJK characters count three) passes 900 is a long-form project,
    /// exactly when the iOS Studio routes it there.
    static func shouldRouteToLongFormBatch(_ text: String) -> Bool {
        GenerationTextLimitPolicy.exceedsSingleTake(text)
    }

    /// Explicit line-by-line takes precedence; otherwise both platforms use
    /// the shared single-take predicate. Nil means an ordinary single take.
    static func batchMode(for text: String, lineByLine: Bool) -> MacBatchSegmentationMode? {
        if lineByLine { return .lineSeparated }
        return shouldRouteToLongFormBatch(text) ? .longForm : nil
    }
}
