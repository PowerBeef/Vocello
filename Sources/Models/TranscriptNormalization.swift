import Foundation

/// The reference transcript as conditioning.
///
/// Pure and separate so the behaviour can be tested: the field it comes from is
/// a multi-line `TextField` — it has to be, because on one line it truncated
/// mid-word even at the widest window — which means Return inserts a newline
/// instead of committing, and line breaks reach the conditioning string. A
/// transcript of spoken audio has no line structure worth keeping, and a stray
/// newline is a token the model never heard.
enum TranscriptNormalization {
    /// Every run of whitespace collapsed to one space; nil when nothing is left.
    static func conditioningLine(_ raw: String) -> String? {
        let collapsed = raw.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return collapsed.isEmpty ? nil : collapsed
    }
}
