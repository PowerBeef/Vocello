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

    /// Whatever this runner's AudioToolbox reads, the offered list keeps its
    /// invariants; the host's own capability is not asserted.
    func testTheOfferedListFollowsThisHostsProbe() {
        let readable = VoiceCloningReferenceAudioSupport.systemReadableAudioExtensions()
        let offered = VoiceCloningReferenceAudioSupport.allowedFileExtensions
        XCTAssertFalse(offered.contains("webm"), "WebM is never offered, whatever the probe reports")
        XCTAssertTrue(offered.isSuperset(of: VoiceCloningReferenceAudioSupport.baseFileExtensions))
        XCTAssertEqual(offered.contains("ogg"), readable.contains("ogg"), "Ogg is offered exactly when the probe reads it")
        XCTAssertEqual(offered, VoiceCloningReferenceAudioSupport.allowedFileExtensions(systemReadableExtensions: readable))
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
