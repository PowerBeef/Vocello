import Foundation
import QwenVoiceCore

/// Joins the per-layer telemetry rows for one generation into a single readable
/// `generations-merged.jsonl` row, keyed by the shared `generationID`.
///
/// macOS-only (app target). Since the engine runs in the app process (plan
/// `macos-ios-convergence-2026-09`) there are two layers: the app row written by
/// `AppGenerationTimeline` and the engine row written by the runtime; the merged
/// record declares exactly those as required, so a 2-layer record is complete and
/// never shares a comparison key with the retired 3-layer (app, engine-service,
/// engine) records.
///
/// Runtime-gated and fully off the main actor. The engine row flushes slightly
/// after the app's `completed` (both write asynchronously), so the merge polls
/// briefly before giving up.
enum GenerationTelemetryMerger {
    private static let mergedFileName = "generations-merged.jsonl"
    // Audit J1: 3 s of polling at .background priority was not enough — under
    // bench load the app/engine-service layer writes (themselves detached
    // background tasks) get starved past the window, the merge gave up, and the
    // flush marker advanced with the app row still unwritten; the bench's next
    // relaunch then terminated the app mid-write. .utility + a 15 s window keeps
    // the marker honest (it fires early as soon as both layers land).
    private static let pollAttempts = 75
    private static let pollIntervalNanos: UInt64 = 200_000_000 // 200 ms × 75 ≈ 15 s

    /// Schedule a merge for the given generation. No-op when telemetry is off.
    static func scheduleMerge(generationID: UUID?) {
        guard TelemetryGate.appProcessIntendedEnabled else { return }
        guard let generationID else { return }
        let key = generationID.uuidString
        let appSupportDirectory = AppPaths.appSupportDir
        Task.detached(priority: .utility) {
            await merge(generationID: key, appSupportDirectory: appSupportDirectory)
        }
    }

    private static func merge(generationID: String, appSupportDirectory: URL) async {
        let diagnostics = appSupportDirectory.appendingPathComponent("diagnostics", isDirectory: true)
        let appURL = diagnostics.appendingPathComponent("app/generations.jsonl", isDirectory: false)
        let engineURL = diagnostics.appendingPathComponent("engine/generations.jsonl", isDirectory: false)

        var app: GenerationTelemetryRecord?
        var engine: GenerationTelemetryRecord?

        for attempt in 0..<pollAttempts {
            app = app ?? latestRecord(for: generationID, in: appURL)
            engine = engine ?? latestRecord(for: generationID, in: engineURL)
            if app != nil, engine != nil { break }
            if attempt < pollAttempts - 1 {
                try? await Task.sleep(nanoseconds: pollIntervalNanos)
            }
        }

        guard app != nil || engine != nil else { return }

        let merged = MergedGenerationTelemetry(
            generationID: generationID,
            recordedAt: ISO8601DateFormatter().string(from: Date()),
            app: app,
            engineService: nil,
            engine: engine,
            requiredLayers: [.app, .engine]
        )
        write(merged, into: diagnostics)
    }

    /// Returns the last row matching `generationID` in a per-layer JSONL file.
    ///
    /// Audit P1-7: a decode failure on a MATCHING row must not be a silent drop
    /// (the Python summarizer is lenient; this Swift path was strict and quiet,
    /// so schema drift produced merged rows that silently lost a layer). Rows
    /// that contain the generationID but fail Codable decoding are logged loudly.
    private static func latestRecord(
        for generationID: String,
        in url: URL
    ) -> GenerationTelemetryRecord? {
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8) else {
            return nil
        }
        let decoder = JSONDecoder()
        var match: GenerationTelemetryRecord?
        for line in text.split(separator: "\n") {
            // Cheap substring pre-filter: only decode candidate lines.
            guard line.contains(generationID), let lineData = line.data(using: .utf8) else {
                continue
            }
            do {
                let record = try decoder.decode(GenerationTelemetryRecord.self, from: lineData)
                if record.generationID == generationID {
                    match = record
                }
            } catch {
                print(
                    "[GenerationTelemetryMerger] Row matching '\(generationID)' in "
                    + "\(url.lastPathComponent) failed to decode and was skipped "
                    + "(schema drift? \(error.localizedDescription))"
                )
            }
        }
        return match
    }

    private static func write(_ merged: MergedGenerationTelemetry, into diagnostics: URL) {
        let url = diagnostics.appendingPathComponent(mergedFileName, isDirectory: false)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        do {
            try FileManager.default.createDirectory(at: diagnostics, withIntermediateDirectories: true)
            var data = try encoder.encode(merged)
            data.append(0x0A)
            if FileManager.default.fileExists(atPath: url.path) {
                let handle = try FileHandle(forWritingTo: url)
                defer { try? handle.close() }
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
            } else {
                try data.write(to: url, options: .atomic)
            }
            // Cap the merged log the same way the per-layer logs are capped
            // (oldest-first front trim) so benchmark logs can't blow out disk.
            GenerationTelemetryJSONLSink.pruneJSONLFromFront(
                at: url,
                maxBytes: GenerationTelemetryJSONLSink.maxLogBytes
            )
        } catch {
            print("[GenerationTelemetryMerger] Could not write merged telemetry for '\(merged.generationID)': \(error.localizedDescription)")
        }
    }
}
