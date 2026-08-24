import Foundation
import QwenVoiceCore

/// Copies App-Group `diagnostics/<layer>/generations.jsonl` into the app's own
/// container at `Library/Caches/Vocello/diagnostics/<layer>/generations.jsonl`.
///
/// devicectl can pull appDataContainer but NOT the App Group, so on-device
/// bench/gate lanes read telemetry from the Caches mirror (see
/// `scripts/ios_device.sh pull` and `IOSDeviceDiagnosticsRunner`).
enum IOSPullableDiagnosticsMirror {
    /// App-Group diagnostics dir where the in-process engine writes JSONL rows.
    private static var appGroupDiagnosticsRoot: URL {
        AppPaths.appSupportDir.appendingPathComponent("diagnostics", isDirectory: true)
    }

    /// devicectl-pullable export root (`Library/Caches/Vocello/diagnostics`).
    static var pullableRoot: URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("Vocello", isDirectory: true)
            .appendingPathComponent("diagnostics", isDirectory: true)
    }

    /// Mirror engine/app JSONL telemetry after each debug generation so the
    /// XCUITest benchmark validator can pull and gate without a diagnostics sentinel.
    static func syncEngineTelemetryIfEnabled() {
        guard TelemetryGate.resolvedEnabled else { return }
        guard let pullableRoot else { return }
        syncEngineTelemetry(from: appGroupDiagnosticsRoot, into: pullableRoot)
    }

    /// Export only the rows and verbose sidecar owned by one completed UI
    /// generation. This avoids copying the App Group's historical diagnostics
    /// corpus after every XCUITest take; the shell validator still filters the
    /// pullable log by the benchmark run id.
    static func syncGenerationTelemetryIfEnabled(generationID: UUID) {
        guard TelemetryGate.resolvedEnabled else { return }
        guard let pullableRoot else { return }
        let generationID = generationID.uuidString
        syncGenerationTelemetry(
            generationID: generationID,
            from: appGroupDiagnosticsRoot,
            into: pullableRoot
        )

        // Run-scoped UI diagnostics are pulled independently from the app's
        // historical telemetry mirror. Export the same generation-filtered
        // rows into that run directory so request-receipt parity can be proven
        // without copying unrelated prior runs. Keep the global destination
        // above for existing benchmark and acceptance consumers.
        if let runID = safeRunID(
            from: ProcessInfo.processInfo.environment["QVOICE_IOS_DEVICE_RUN_ID"]
        ) {
            syncGenerationTelemetry(
                generationID: generationID,
                from: appGroupDiagnosticsRoot,
                into: pullableRoot.appendingPathComponent(runID, isDirectory: true)
            )
        }
    }

    static func syncGenerationTelemetry(
        generationID: String,
        from sourceRoot: URL,
        into pullableRoot: URL
    ) {
        let fileManager = FileManager.default
        for layer in ["engine", "engine-service", "app"] {
            let source = sourceRoot.appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("generations.jsonl", isDirectory: false)
            guard let text = try? String(contentsOf: source, encoding: .utf8) else { continue }
            let matchingLines = text.split(separator: "\n").filter { line in
                guard line.contains(generationID),
                      let data = line.data(using: .utf8),
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else { return false }
                return object["generationID"] as? String == generationID
            }
            guard !matchingLines.isEmpty else { continue }

            let destination = pullableRoot.appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("generations.jsonl", isDirectory: false)
            do {
                try fileManager.createDirectory(
                    at: destination.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                let existing = (try? String(contentsOf: destination, encoding: .utf8)) ?? ""
                let newLines = matchingLines.filter { !existing.contains($0) }
                guard !newLines.isEmpty else { continue }
                let payload = newLines.map(String.init).joined(separator: "\n") + "\n"
                if fileManager.fileExists(atPath: destination.path) {
                    let handle = try FileHandle(forWritingTo: destination)
                    defer { try? handle.close() }
                    try handle.seekToEnd()
                    try handle.write(contentsOf: Data(payload.utf8))
                } else {
                    try Data(payload.utf8).write(to: destination, options: .atomic)
                }
            } catch {
                print("[IOSPullableDiagnosticsMirror] could not export \(layer) row: \(error.localizedDescription)")
            }
        }

        let sampleName = "samples-\(generationID).jsonl"
        let sampleSource = sourceRoot.appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent(sampleName, isDirectory: false)
        guard fileManager.fileExists(atPath: sampleSource.path) else { return }
        let sampleDestination = pullableRoot.appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent(sampleName, isDirectory: false)
        do {
            try fileManager.createDirectory(
                at: sampleDestination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try? fileManager.removeItem(at: sampleDestination)
            try fileManager.copyItem(at: sampleSource, to: sampleDestination)
        } catch {
            print("[IOSPullableDiagnosticsMirror] could not export verbose samples: \(error.localizedDescription)")
        }
    }

    static func syncEngineTelemetry(from sourceRoot: URL, into pullableRoot: URL) {
        let fileManager = FileManager.default
        for layer in ["engine", "engine-service", "app"] {
            let from = sourceRoot.appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("generations.jsonl", isDirectory: false)
            guard fileManager.fileExists(atPath: from.path) else { continue }
            let to = pullableRoot.appendingPathComponent(layer, isDirectory: true)
                .appendingPathComponent("generations.jsonl", isDirectory: false)
            do {
                try fileManager.createDirectory(
                    at: to.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                if fileManager.fileExists(atPath: to.path) {
                    try fileManager.removeItem(at: to)
                }
                try fileManager.copyItem(at: from, to: to)
            } catch {
                print("[IOSPullableDiagnosticsMirror] could not mirror \(layer) telemetry: \(error.localizedDescription)")
            }
        }
    }

    private static func safeRunID(from rawValue: String?) -> String? {
        guard let value = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines),
              (1...96).contains(value.count),
              value.unicodeScalars.allSatisfy({ scalar in
                  CharacterSet.alphanumerics.contains(scalar)
                      || scalar == "."
                      || scalar == "_"
                      || scalar == "-"
              }) else {
            return nil
        }
        return value
    }
}
