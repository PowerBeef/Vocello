/// The last value synchronized across the AppKit/SwiftUI editor boundary.
/// NSTextStorage can vend a lazily bridged NSString. Materialize it once per
/// edit so draft comparisons do not repeatedly traverse foreign UTF-16 storage.
/// This changes representation only: no normalization, trimming, or rewriting.
struct ScriptTextState {
    private(set) var text: String

    init(_ text: String) {
        self.text = text
        self.text.makeContiguousUTF8()
    }

    mutating func recordNativeEdit(_ value: String) -> String {
        text = value
        text.makeContiguousUTF8()
        return text
    }

    /// A native edit's binding echo must not reset selection, marked text, or
    /// the undo stack. Compare the cached snapshot, not a fresh NSTextView string.
    /// Exact UTF-8 comparison also honors external canonically-equivalent edits.
    mutating func recordExternalEdit(_ value: String) -> Bool {
        var nativeValue = value
        nativeValue.makeContiguousUTF8()
        guard !text.utf8.elementsEqual(nativeValue.utf8) else { return false }
        text = nativeValue
        return true
    }
}
