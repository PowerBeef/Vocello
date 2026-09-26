import AudioToolbox
import Foundation
import UniformTypeIdentifiers

/// Reference audio the desktop accepts for cloning: the import panels'
/// content types and the drop filter share one list (moved out of the
/// legacy Voice Cloning screen with its port).
///
/// MAC-09: the list is what the reference is actually decoded with.
/// Preparation opens the file with `AVAudioFile` (AudioToolbox), which has no
/// WebM reader, so WebM is not offered. Ogg (Opus, Vorbis or FLAC) is offered
/// only when this Mac's AudioToolbox reads it, and the panels list these types
/// alone, not every audio type.
enum VoiceCloningReferenceAudioSupport {
    static let baseFileExtensions: Set<String> = ["wav", "mp3", "aiff", "aif", "m4a", "flac"]
    static let oggFileExtension = "ogg"

    static let allowedFileExtensions: Set<String> = allowedFileExtensions(
        systemReadableExtensions: systemReadableAudioExtensions()
    )

    /// The base formats, plus Ogg when `systemReadableExtensions` includes it.
    static func allowedFileExtensions(systemReadableExtensions: Set<String>) -> Set<String> {
        systemReadableExtensions.contains(oggFileExtension)
            ? baseFileExtensions.union([oggFileExtension])
            : baseFileExtensions
    }

    static var supportsOgg: Bool { allowedFileExtensions.contains(oggFileExtension) }

    static var supportedFormatDescription: String {
        supportsOgg ? MacInterfaceText.cloningSupportedFormats : MacInterfaceText.cloningSupportedFormatsWithoutOgg
    }

    static let openPanelContentTypes: [UTType] = {
        var seen = Set<String>()
        var types: [UTType] = []
        for ext in allowedFileExtensions.sorted() {
            if let type = UTType(filenameExtension: ext), seen.insert(type.identifier).inserted {
                types.append(type)
            }
        }
        return types
    }()

    /// Lowercased file extensions AudioToolbox can open for reading on this
    /// system (`kAudioFileGlobalInfo_AllExtensions`); empty when the query fails.
    static func systemReadableAudioExtensions() -> Set<String> {
        var extensions: Unmanaged<CFArray>?
        var size = UInt32(MemoryLayout<Unmanaged<CFArray>?>.size)
        let status = AudioFileGetGlobalInfo(
            kAudioFileGlobalInfo_AllExtensions,
            0,
            nil,
            &size,
            &extensions
        )
        guard status == noErr, let array = extensions?.takeRetainedValue() as? [String] else { return [] }
        return Set(array.map { $0.lowercased() })
    }
}
