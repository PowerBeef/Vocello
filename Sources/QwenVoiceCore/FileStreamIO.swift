import CryptoKit
import Foundation

/// Chunked file I/O for model, download and evidence paths, built only on the
/// throwing `FileHandle` APIs (`read(upToCount:)`, `write(contentsOf:)`,
/// `seekToEnd()`). The legacy `readData(ofLength:)` / `write(_:)` pair raises an
/// Objective-C exception on a full disk or an I/O error, which Swift cannot catch
/// and which terminates the process; here the same failures surface as ordinary
/// Swift errors (Cocoa/POSIX domain) for the caller to handle. Callers keep their
/// own retry policy: these errors are not network errors, so the download retry
/// policy treats them as terminal.
enum FileStreamIO {
    /// Read and write granularity, matching the 1 MiB chunks the call sites used
    /// before this helper existed.
    static let defaultChunkSize = 1_048_576

    /// Streams the file at `url` through SHA-256 and returns the lowercase hex digest.
    static func sha256Hex(of url: URL, chunkSize: Int = defaultChunkSize) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        return try sha256Hex(reading: handle, chunkSize: chunkSize)
    }

    /// Streams `handle` from its current offset to end of file through SHA-256 and
    /// returns the lowercase hex digest.
    static func sha256Hex(reading handle: FileHandle, chunkSize: Int = defaultChunkSize) throws -> String {
        var hasher = SHA256()
        try forEachChunk(of: handle, chunkSize: chunkSize) { hasher.update(data: $0) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    /// Reads `handle` from its current offset to end of file in chunks of at most
    /// `chunkSize` bytes, passing each non-empty chunk to `body`. Each chunk is read
    /// inside its own autorelease pool so a multi-gigabyte file never accumulates
    /// bridged buffers. Returns the number of bytes read.
    @discardableResult
    static func forEachChunk(
        of handle: FileHandle,
        chunkSize: Int = defaultChunkSize,
        _ body: (Data) throws -> Void
    ) throws -> Int64 {
        let count = max(1, chunkSize)
        var total: Int64 = 0
        while try autoreleasepool(invoking: { () throws -> Bool in
            guard let data = try handle.read(upToCount: count), !data.isEmpty else { return false }
            try body(data)
            total += Int64(data.count)
            return true
        }) {}
        return total
    }

    /// Copies `source` from its current offset to end of file into `destination` at
    /// its current offset. Returns the number of bytes copied.
    @discardableResult
    static func copy(
        from source: FileHandle,
        to destination: FileHandle,
        chunkSize: Int = defaultChunkSize
    ) throws -> Int64 {
        try forEachChunk(of: source, chunkSize: chunkSize) { try destination.write(contentsOf: $0) }
    }

    /// Copies the whole file at `sourceURL` into `destination` at its current offset.
    /// Returns the number of bytes copied.
    @discardableResult
    static func copy(
        contentsOf sourceURL: URL,
        to destination: FileHandle,
        chunkSize: Int = defaultChunkSize
    ) throws -> Int64 {
        let source = try FileHandle(forReadingFrom: sourceURL)
        defer { try? source.close() }
        return try copy(from: source, to: destination, chunkSize: chunkSize)
    }

    /// Appends the whole file at `sourceURL` to the end of `destination`.
    /// Returns the number of bytes appended.
    @discardableResult
    static func append(
        contentsOf sourceURL: URL,
        to destination: FileHandle,
        chunkSize: Int = defaultChunkSize
    ) throws -> Int64 {
        try destination.seekToEnd()
        return try copy(contentsOf: sourceURL, to: destination, chunkSize: chunkSize)
    }
}
