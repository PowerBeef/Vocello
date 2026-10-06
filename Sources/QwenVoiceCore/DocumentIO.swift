import CryptoKit
import Foundation

public enum DocumentIOError: LocalizedError, Equatable {
    case missingSource(String)
    case failedToCreateDirectory(String)
    case failedToCopy(String)
    /// CORE-16: a reference larger than audio preparation accepts is refused
    /// before it is copied, instead of being copied only to fail later.
    case referenceTooLarge(maxBytes: Int64, actualBytes: Int64)

    /// Path-free: the file's location never enters the description (AUD-08).
    public var errorDescription: String? {
        switch self {
        case .missingSource:
            return "Document file not found."
        case .failedToCreateDirectory:
            return "Couldn't create the document directory."
        case .failedToCopy:
            return "Couldn't copy the document."
        case .referenceTooLarge(let maxBytes, let actualBytes):
            return "The reference audio is \(actualBytes) bytes; the limit is \(maxBytes) bytes."
        }
    }
}

public struct ImportedReferenceAudio: Hashable, Codable, Sendable {
    public let originalPath: String
    public let materializedPath: String
    public let transcriptSidecarPath: String?
    public let fingerprint: String

    public init(
        originalPath: String,
        materializedPath: String,
        transcriptSidecarPath: String?,
        fingerprint: String
    ) {
        self.originalPath = originalPath
        self.materializedPath = materializedPath
        self.transcriptSidecarPath = transcriptSidecarPath
        self.fingerprint = fingerprint
    }

    public var originalURL: URL {
        URL(fileURLWithPath: originalPath)
    }

    public var materializedURL: URL {
        URL(fileURLWithPath: materializedPath)
    }

    public var transcriptSidecarURL: URL? {
        guard let transcriptSidecarPath else { return nil }
        return URL(fileURLWithPath: transcriptSidecarPath)
    }
}

public struct ExportedDocument: Hashable, Codable, Sendable {
    public let sourcePath: String
    public let destinationPath: String

    public init(sourcePath: String, destinationPath: String) {
        self.sourcePath = sourcePath
        self.destinationPath = destinationPath
    }

    public var sourceURL: URL {
        URL(fileURLWithPath: sourcePath)
    }

    public var destinationURL: URL {
        URL(fileURLWithPath: destinationPath)
    }
}

/// A copy that never removes an existing destination before the new bytes are
/// complete: they land in a hidden staging file beside the destination, which
/// then replaces it (or takes its name when there is none). A failed copy
/// leaves any destination exactly as it was and removes only its own staging
/// file (A3-01, A3-02).
public enum StagedFileCopy {
    public static func copy(from source: URL, to destination: URL, fileManager: FileManager = .default) throws {
        let staging = destination.deletingLastPathComponent().appendingPathComponent(
            ".\(destination.lastPathComponent).vocello-copy-\(UUID().uuidString)",
            isDirectory: false
        )
        do {
            try fileManager.copyItem(at: source, to: staging)
            if fileManager.fileExists(atPath: destination.path) {
                _ = try fileManager.replaceItemAt(destination, withItemAt: staging)
            } else {
                try fileManager.moveItem(at: staging, to: destination)
            }
        } catch {
            try? fileManager.removeItem(at: staging)
            throw error
        }
    }
}

public protocol DocumentIO: Sendable {
    func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio
    func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument
}

public struct LocalDocumentIO: DocumentIO, Hashable, Sendable {
    public let importedReferenceDirectory: URL
    /// The largest reference this imports (CORE-16). It defaults to what audio
    /// preparation accepts, so no file is copied that could never be prepared.
    public let maximumReferenceBytes: Int64

    public init(
        importedReferenceDirectory: URL,
        maximumReferenceBytes: Int64 = AudioPreparationLimits.defaults.maxInputFileSizeBytes
    ) {
        self.importedReferenceDirectory = importedReferenceDirectory
        self.maximumReferenceBytes = maximumReferenceBytes
    }

    public func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
        // iOS `fileImporter` (and macOS NSOpenPanel under a sandboxed
        // configuration) deliver security-scoped URLs that require an
        // explicit `startAccessingSecurityScopedResource()` before any
        // read. macOS today runs with the app sandbox disabled
        // (`com.apple.security.app-sandbox = false`) so this call is a
        // no-op there, but iOS is always sandboxed and the import
        // would otherwise fail silently for files from iCloud Drive,
        // Files providers, or any other app's container. Pair with a
        // `defer` to release the grant on every exit path. Wrapping
        // around the sidecar lookup keeps the `.txt` companion read
        // inside the same scope.
        let accessed = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw DocumentIOError.missingSource(sourceURL.path)
        }
        if maximumReferenceBytes > 0,
           let size = (try? sourceURL.resourceValues(forKeys: [.fileSizeKey]))?.fileSize,
           Int64(size) > maximumReferenceBytes {
            throw DocumentIOError.referenceTooLarge(maxBytes: maximumReferenceBytes, actualBytes: Int64(size))
        }

        do {
            try fileManager.createDirectory(at: importedReferenceDirectory, withIntermediateDirectories: true)
        } catch {
            throw DocumentIOError.failedToCreateDirectory(importedReferenceDirectory.path)
        }

        let fingerprint = Self.fileFingerprint(for: sourceURL)
        let destinationURL = importedReferenceDirectory.appendingPathComponent(
            "\(Self.sanitizedStem(for: sourceURL))_\(fingerprint).\(sourceURL.pathExtension.lowercased())"
        )
        try Self.copyReplacingIfNeeded(sourceURL, to: destinationURL)

        // CORE-17: the transcript sidecar is best effort. A Files picker grants
        // access to the chosen audio alone, so a sibling `.txt` may be visible
        // but unreadable; the audio still imports, and enrollment transcribes it.
        // A sidecar this import could not copy never leaves a stale one behind.
        let sourceSidecarURL = sourceURL.deletingPathExtension().appendingPathExtension("txt")
        let destinationSidecarURL = destinationURL.deletingPathExtension().appendingPathExtension("txt")
        let copiedSidecar = fileManager.fileExists(atPath: sourceSidecarURL.path)
            && (try? Self.copyReplacingIfNeeded(sourceSidecarURL, to: destinationSidecarURL)) != nil
        if !copiedSidecar, fileManager.fileExists(atPath: destinationSidecarURL.path) {
            try? fileManager.removeItem(at: destinationSidecarURL)
        }

        return ImportedReferenceAudio(
            originalPath: sourceURL.path,
            materializedPath: destinationURL.path,
            transcriptSidecarPath: copiedSidecar ? destinationSidecarURL.path : nil,
            fingerprint: fingerprint
        )
    }

    public func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw DocumentIOError.missingSource(sourceURL.path)
        }

        let parentDirectory = destinationURL.deletingLastPathComponent()
        do {
            try fileManager.createDirectory(at: parentDirectory, withIntermediateDirectories: true)
        } catch {
            throw DocumentIOError.failedToCreateDirectory(parentDirectory.path)
        }

        do {
            try StagedFileCopy.copy(from: sourceURL, to: destinationURL, fileManager: fileManager)
        } catch {
            throw DocumentIOError.failedToCopy(destinationURL.path)
        }

        return ExportedDocument(sourcePath: sourceURL.path, destinationPath: destinationURL.path)
    }

    /// A re-import of the same file maps to the same materialized name, which a
    /// review may still be reading: it is replaced in one step, never removed
    /// first, and a failed copy keeps the earlier materialization (A3-02).
    private static func copyReplacingIfNeeded(_ sourceURL: URL, to destinationURL: URL) throws {
        if sourceURL.standardizedFileURL == destinationURL.standardizedFileURL {
            return
        }

        do {
            try StagedFileCopy.copy(from: sourceURL, to: destinationURL)
        } catch {
            throw DocumentIOError.failedToCopy(destinationURL.path)
        }
    }

    private static func fileFingerprint(for url: URL) -> String {
        let fileManager = FileManager.default
        let resolvedPath = url.resolvingSymlinksInPath().path
        let attributes = (try? fileManager.attributesOfItem(atPath: resolvedPath)) ?? [:]
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        let mtime = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let data = Data("\(resolvedPath)|\(size)|\(mtime)".utf8)
        let digest = SHA256.hash(data: data)
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
    }

    private static func sanitizedStem(for url: URL) -> String {
        let raw = url.deletingPathExtension().lastPathComponent
        let sanitized = raw
            .replacingOccurrences(of: #"[^\w\s-]"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
        return sanitized.isEmpty ? "reference" : sanitized
    }
}
