import Foundation
import UniformTypeIdentifiers

/// One import contract for every iOS saved-reference entry point. Validation returns the exact
/// URL supplied by the system so the document layer can consume its security-scoped grant.
enum IOSReferenceAudioImportPolicy {
    static let allowedContentTypes: [UTType] = [.wav, .mp3, .aiff, .mpeg4Audio]
    static let supportedExtensions: Set<String> = ["wav", "mp3", "aiff", "m4a"]

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
}
