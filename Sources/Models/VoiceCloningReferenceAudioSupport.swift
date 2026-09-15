import Foundation
import UniformTypeIdentifiers

/// Reference audio the desktop accepts for cloning: the import panel's
/// content types and the drop filter share one list (moved out of the
/// legacy Voice Cloning screen with its port).
enum VoiceCloningReferenceAudioSupport {
    static let allowedFileExtensions: Set<String> = [
        "wav", "mp3", "aiff", "aif", "m4a", "flac", "ogg", "webm",
    ]

    static var supportedFormatDescription: String { MacInterfaceText.cloningSupportedFormats }

    static let webMType = UTType(filenameExtension: "webm")
        ?? UTType(mimeType: "audio/webm")
        ?? UTType(mimeType: "video/webm")

    static let openPanelContentTypes: [UTType] = {
        var seen = Set<String>()
        var types: [UTType] = []

        func append(_ type: UTType) {
            if seen.insert(type.identifier).inserted {
                types.append(type)
            }
        }

        append(.audio)

        for ext in allowedFileExtensions.sorted() where ext != "webm" {
            if let type = UTType(filenameExtension: ext) {
                append(type)
            }
        }

        if let webMType {
            append(webMType)
        }

        return types
    }()
}
