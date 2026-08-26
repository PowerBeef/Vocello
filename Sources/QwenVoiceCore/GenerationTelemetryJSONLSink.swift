import Foundation

/// Shared, runtime-gated, append-only writer for per-generation telemetry rows.
///
/// Complements the runtime-gated native event stream with one durable summary per
/// generation. This sink is gated on `TelemetryGate.resolvedEnabled` (resolved at
/// runtime, never compiled out) so dev and shipped binaries run identical code. Each
/// layer appends one JSON line to `<appSupport>/diagnostics/<layer>/generations.jsonl`.
///
/// Hardening notes (Phase 2b):
/// - All file writes are wrapped in `NSFileCoordinator` so the app process and the
///   engine-service / XPC helper don't corrupt shared JSONL files when they append
///   concurrently.
/// - Errors are written to `stderr` instead of `stdout`, so they don't pollute the
///   CLI output stream (e.g., benchmark JSON capture).
/// - The append path still creates files atomically when they don't exist.
public actor GenerationTelemetryJSONLSink {
    public static let shared = GenerationTelemetryJSONLSink()

    private let encoder: JSONEncoder

    /// Storage budget for the append-only diagnostics so benchmark logs are
    /// permitted but can't blow out disk. Auto-prune is oldest-first.
    /// - Per JSONL log (`generations.jsonl` × layer, `generations-merged.jsonl`):
    ///   trimmed from the front when it exceeds `maxLogBytes`. `QWENVOICE_DIAGNOSTICS_MAX_MB`
    ///   scales this (per-log MB); unset ⇒ 8 MB.
    /// - Verbose sidecars (`samples-<id>.jsonl`): newest `maxSidecarFiles` kept, total
    ///   capped at `maxSidecarTotalBytes`.
    public static let maxLogBytes: Int = {
        let mb = RuntimeDebugGate.observabilityValue(for: "QWENVOICE_DIAGNOSTICS_MAX_MB")
            .flatMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
            .map { max(1, $0) } ?? 8
        return mb * 1_024 * 1_024
    }()
    public static let maxSidecarFiles = 48
    public static let maxSidecarTotalBytes = 64 * 1_024 * 1_024

    public init() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        self.encoder = encoder
    }

    /// Append one record under `diagnostics/<subdirectory>/<fileName>`.
    /// No-op when the telemetry gate is off or the directory is unknown.
    public func write(
        record: GenerationTelemetryRecord,
        appSupportDirectory: URL?,
        subdirectory: String,
        fileName: String = "generations.jsonl"
    ) {
        guard TelemetryGate.resolvedEnabled else { return }
        guard let appSupportDirectory else { return }

        let directory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(subdirectory, isDirectory: true)
        let url = directory.appendingPathComponent(fileName, isDirectory: false)

        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            var data = try encoder.encode(record)
            data.append(0x0A)
            try Self.append(data, to: url)
            Self.pruneJSONLFromFront(at: url, maxBytes: Self.maxLogBytes)
        } catch {
            Self.logError("Could not write telemetry for '\(record.generationID)': \(error.localizedDescription)")
        }
    }

    /// Opt-in verbose path: persist the raw per-sample memory/timing series to a
    /// per-generation sidecar `samples-<generationID>.jsonl` (one `TelemetrySample`
    /// per line). Separate file so the main `generations.jsonl` stays compact and
    /// the high-volume series is only paid for when explicitly requested.
    public func writeRawSamples(
        _ samples: [TelemetrySample],
        generationID: String,
        appSupportDirectory: URL?,
        subdirectory: String
    ) {
        guard TelemetryGate.resolvedEnabled else { return }
        guard let appSupportDirectory, !samples.isEmpty else { return }

        let directory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(subdirectory, isDirectory: true)
        let safeID = generationID.replacingOccurrences(of: "/", with: "_")
        let url = directory.appendingPathComponent("samples-\(safeID).jsonl", isDirectory: false)

        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var blob = Data()
            for sample in samples {
                var line = try encoder.encode(sample)
                line.append(0x0A)
                blob.append(line)
            }
            try Self.coordinatedWrite(blob, to: url, options: .atomic)
            Self.pruneSidecars(
                in: directory,
                maxFiles: Self.maxSidecarFiles,
                maxTotalBytes: Self.maxSidecarTotalBytes
            )
        } catch {
            Self.logError("Could not write raw samples for '\(generationID)': \(error.localizedDescription)")
        }
    }

    /// Append `data` to an existing JSONL file, or atomically create it.
    /// Uses `NSFileCoordinator` so concurrent writers across processes don't
    /// interleave bytes.
    private static func append(_ data: Data, to url: URL) throws {
        var writeError: Error?
        let coordinator = NSFileCoordinator(filePresenter: nil)
        var coordinatorError: NSError?
        coordinator.coordinate(
            writingItemAt: url,
            options: .forMerging,
            error: &coordinatorError
        ) { safeURL in
            do {
                if FileManager.default.fileExists(atPath: safeURL.path) {
                    let handle = try FileHandle(forWritingTo: safeURL)
                    defer { try? handle.close() }
                    try handle.seekToEnd()
                    try handle.write(contentsOf: data)
                } else {
                    try data.write(to: safeURL, options: .atomic)
                }
            } catch {
                writeError = error
            }
        }
        if let writeError { throw writeError }
        if let coordinatorError { throw coordinatorError }
    }

    /// Trim an append-only JSONL from the **front** (oldest rows) when it exceeds
    /// `maxBytes`, keeping the newest whole lines within ~`maxBytes/2`. Trimming to
    /// half is intentional: it amortizes the rewrite cost so a busy log isn't
    /// rewritten on every append. Gated by a cheap size check — a no-op (just a
    /// `stat`) on the common path. Best-effort: any failure is logged but leaves
    /// the file intact.
    /// `public` so the macOS `GenerationTelemetryMerger` caps its merged file too.
    public static func pruneJSONLFromFront(at url: URL, maxBytes: Int) {
        guard maxBytes > 0 else { return }
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = (attrs[.size] as? NSNumber)?.intValue,
              size > maxBytes else {
            return
        }

        var pruneError: Error?
        let coordinator = NSFileCoordinator(filePresenter: nil)
        var coordinatorError: NSError?
        coordinator.coordinate(
            readingItemAt: url,
            options: [],
            writingItemAt: url,
            options: .forMerging,
            error: &coordinatorError
        ) { readURL, writeURL in
            do {
                guard let data = try? Data(contentsOf: readURL) else { return }
                let newline: UInt8 = 0x0A
                let target = maxBytes / 2
                // Scan backward for line boundaries; `keepFrom` walks to the oldest line
                // start whose tail (`keepFrom..<end`) still fits `target`.
                var keepFrom = data.count
                var index = data.count - 1
                while index >= 0 {
                    if data[index] == newline, index + 1 < keepFrom {
                        if data.count - (index + 1) > target { break }
                        keepFrom = index + 1
                    }
                    index -= 1
                }
                // If the whole file (incl. the leading line, which has no preceding
                // newline) fits `target`, there's nothing to drop.
                if data.count <= target { keepFrom = 0 }
                guard keepFrom > 0, keepFrom < data.count else { return }
                let trimmed = data.suffix(from: keepFrom)
                try trimmed.write(to: writeURL, options: .atomic)
            } catch {
                pruneError = error
            }
        }
        if let pruneError {
            logError("Could not prune '\(url.lastPathComponent)': \(pruneError.localizedDescription)")
        }
        if let coordinatorError {
            logError("Could not coordinate prune of '\(url.lastPathComponent)': \(coordinatorError.localizedDescription)")
        }
    }

    /// Delete oldest `samples-*.jsonl` sidecars until within both budgets.
    private static func pruneSidecars(in directory: URL, maxFiles: Int, maxTotalBytes: Int) {
        let fm = FileManager.default
        guard let entries = try? fm.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey]
        ) else { return }
        var sidecars = entries.filter {
            $0.lastPathComponent.hasPrefix("samples-") && $0.pathExtension == "jsonl"
        }
        guard !sidecars.isEmpty else { return }
        func modDate(_ u: URL) -> Date {
            (try? u.resourceValues(forKeys: [.contentModificationDateKey]))?
                .contentModificationDate ?? .distantPast
        }
        func byteSize(_ u: URL) -> Int {
            (try? u.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0
        }
        // Newest first.
        sidecars.sort { modDate($0) > modDate($1) }
        var runningBytes = 0
        for (offset, sidecar) in sidecars.enumerated() {
            runningBytes += byteSize(sidecar)
            if offset >= maxFiles || runningBytes > maxTotalBytes {
                try? fm.removeItem(at: sidecar)
            }
        }
    }

    /// Atomically write/replace a file under `NSFileCoordinator`.
    private static func coordinatedWrite(
        _ data: Data,
        to url: URL,
        options: Data.WritingOptions
    ) throws {
        var writeError: Error?
        let coordinator = NSFileCoordinator(filePresenter: nil)
        var coordinatorError: NSError?
        coordinator.coordinate(
            writingItemAt: url,
            options: .forReplacing,
            error: &coordinatorError
        ) { safeURL in
            do {
                try data.write(to: safeURL, options: options)
            } catch {
                writeError = error
            }
        }
        if let writeError { throw writeError }
        if let coordinatorError { throw coordinatorError }
    }

    private static func logError(_ message: String) {
        let line = "[GenerationTelemetryJSONLSink] \(message)\n"
        if let data = line.data(using: .utf8) {
            try? FileHandle.standardError.write(contentsOf: data)
        }
    }
}
