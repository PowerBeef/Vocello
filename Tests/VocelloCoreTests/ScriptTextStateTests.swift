import AppKit
import XCTest

final class ScriptTextStateTests: XCTestCase {
    func testNativeStorageIsMaterializedWithoutChangingAnyUTF8Bytes() {
        let fixtures = [
            "", "  Script\nwith whitespace.\t", "Café", "Cafe\u{301}",
            "中文、日本語、한국어", "مرحبا بالعالم", "👨‍👩‍👧‍👦 🇨🇦",
            String(repeating: "Cafe\u{301} — bonjour 👋!\n", count: 500),
        ]
        for fixture in fixtures {
            let storage = NSTextStorage(string: fixture)
            var state = ScriptTextState("")
            let published = state.recordNativeEdit(storage.string)
            XCTAssertTrue(published.isContiguousUTF8)
            XCTAssertEqual(Array(published.utf8), Array(fixture.utf8))
            XCTAssertFalse(state.recordExternalEdit(published), "Binding echo must not rewrite the editor")
            // Later AppKit mutations cannot change an already published request snapshot.
            storage.mutableString.append(" changed")
            XCTAssertEqual(Array(published.utf8), Array(fixture.utf8))
            XCTAssertEqual(Array(state.text.utf8), Array(fixture.utf8))
        }
    }

    func testExternalInitializationReplacementAndClear() {
        var state = ScriptTextState(NSTextStorage(string: "Initial é").string)
        XCTAssertTrue(state.text.isContiguousUTF8)
        XCTAssertFalse(state.recordExternalEdit("Initial é"))
        XCTAssertTrue(state.recordExternalEdit("Changed é"))
        XCTAssertEqual(state.text, "Changed é")
        XCTAssertTrue(state.recordExternalEdit(""))
        XCTAssertEqual(state.text, "")
        XCTAssertFalse(state.recordExternalEdit(""))
    }

    func testCanonicallyEquivalentExternalEditPreservesExactRequestBytes() {
        let composed = "Café"
        let decomposed = "Cafe\u{301}"
        XCTAssertEqual(composed, decomposed) // Swift's semantic equality is not byte identity.
        var state = ScriptTextState(composed)
        XCTAssertTrue(state.recordExternalEdit(decomposed))
        XCTAssertEqual(Array(state.text.utf8), Array(decomposed.utf8))
        XCTAssertFalse(state.recordExternalEdit(decomposed))
    }

    func testNativeEditUndoRedoAndMarkedTextEchoDoNotRequestEditorReplacement() {
        var state = ScriptTextState("")
        let edits = ["に", "日本", "日本語", "日本", "日本語", "日本語\nBonjour"]
        var snapshots: [String] = []
        for edit in edits {
            let published = state.recordNativeEdit(NSTextStorage(string: edit).string)
            snapshots.append(published)
            XCTAssertFalse(state.recordExternalEdit(published))
        }
        XCTAssertEqual(snapshots, edits)
        XCTAssertTrue(state.recordExternalEdit("New selected script"))
        XCTAssertEqual(state.text, "New selected script")
        XCTAssertEqual(snapshots, edits)
    }
}
