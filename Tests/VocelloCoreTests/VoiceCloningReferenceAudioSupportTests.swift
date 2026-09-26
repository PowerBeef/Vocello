import UniformTypeIdentifiers
import XCTest

/// MAC-09: the Mac offers only reference formats its decoder reads.
final class VoiceCloningReferenceAudioSupportTests: XCTestCase {
    func testWebMIsNeverOffered() {
        XCTAssertFalse(VoiceCloningReferenceAudioSupport.allowedFileExtensions.contains("webm"))
        XCTAssertFalse(
            VoiceCloningReferenceAudioSupport.allowedFileExtensions(systemReadableExtensions: ["webm", "ogg"]).contains("webm")
        )
    }

    func testOggIsOfferedOnlyWhenTheSystemReadsIt() {
        let base = VoiceCloningReferenceAudioSupport.baseFileExtensions
        XCTAssertEqual(VoiceCloningReferenceAudioSupport.allowedFileExtensions(systemReadableExtensions: ["wav", "mp3"]), base)
        XCTAssertEqual(
            VoiceCloningReferenceAudioSupport.allowedFileExtensions(systemReadableExtensions: ["wav", "ogg"]),
            base.union(["ogg"])
        )
    }

    func testTheSystemQueryAnswersForThisHost() {
        let readable = VoiceCloningReferenceAudioSupport.systemReadableAudioExtensions()
        XCTAssertTrue(readable.contains("wav"))
        XCTAssertFalse(readable.contains("webm"))
        XCTAssertEqual(
            VoiceCloningReferenceAudioSupport.allowedFileExtensions.contains("ogg"),
            readable.contains("ogg")
        )
    }

    func testThePanelListsTheAllowedTypesAndNotEveryAudioType() {
        let identifiers = Set(VoiceCloningReferenceAudioSupport.openPanelContentTypes.map(\.identifier))
        XCTAssertFalse(identifiers.contains(UTType.audio.identifier))
        XCTAssertTrue(identifiers.contains(UTType.wav.identifier))
        XCTAssertTrue(identifiers.contains(UTType.mp3.identifier))
        XCTAssertFalse(identifiers.contains("org.webmproject.webm"))
        XCTAssertEqual(identifiers.count, VoiceCloningReferenceAudioSupport.openPanelContentTypes.count)
    }
}
