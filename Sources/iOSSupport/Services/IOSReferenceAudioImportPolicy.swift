import Foundation
import QwenVoiceCore
import UniformTypeIdentifiers

/// One import contract for every iOS saved-reference entry point. Validation returns the exact
/// URL supplied by the system so the document layer can consume its security-scoped grant.
///
/// The document types in `Info.plist` list the same four formats (IOS-23), so Files offers
/// Vocello only for audio this policy accepts.
enum IOSReferenceAudioImportPolicy {
    static let allowedContentTypes: [UTType] = [.wav, .mp3, .aiff, .mpeg4Audio]
    /// `.aif` is the AIFF type's other extension; enrollment stores it as WAV.
    static let supportedExtensions: Set<String> = ["wav", "mp3", "aiff", "aif", "m4a"]

    enum ValidationError: LocalizedError, Equatable {
        case unsupportedType

        var errorDescription: String? {
            "Vocello can import WAV, MP3, AIFF, and M4A reference audio."
        }
    }

    static func validatedSourceURL(_ sourceURL: URL) throws -> URL {
        guard supportedExtensions.contains(sourceURL.pathExtension.lowercased()) else {
            throw ValidationError.unsupportedType
        }
        return sourceURL
    }

    /// Converts the Files-picker result into the one URL the enrollment route may consume.
    /// Cancellation and an empty selection are explicit no-ops; every other error remains typed.
    static func selectedSourceURL(from result: Result<[URL], Error>) throws -> URL? {
        switch result {
        case .success(let urls):
            guard let sourceURL = urls.first else { return nil }
            return try validatedSourceURL(sourceURL)
        case .failure(let error):
            if (error as? CocoaError)?.code == .userCancelled {
                return nil
            }
            throw error
        }
    }

    /// CORE-16 / IOS-23: validates the system-supplied URL and copies it (with any readable
    /// transcript sidecar) into `directory` off the main actor. `LocalDocumentIO` refuses a
    /// file larger than audio preparation accepts before copying a byte.
    @concurrent
    static func importReference(
        from sourceURL: URL,
        into directory: URL
    ) async throws -> ImportedReferenceAudio {
        let validatedURL = try validatedSourceURL(sourceURL)
        return try LocalDocumentIO(importedReferenceDirectory: directory)
            .importReferenceAudio(from: validatedURL)
    }

    /// The interface-language message for a failed import; `nil` when no specific copy applies
    /// and the caller shows its generic "choose another file" detail. File paths and English
    /// system text never reach the alert.
    static func failureMessage(for error: Error, presentation: VocelloPresentationText) -> String? {
        if error is ValidationError {
            return presentation.importReferenceAudioDetail
        }
        if case .referenceTooLarge? = error as? DocumentIOError {
            return presentation.generationFailureMessage(.referenceAudioTooLong)
        }
        return nil
    }
}
