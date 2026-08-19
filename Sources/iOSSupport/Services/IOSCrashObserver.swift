import Foundation
import MetricKit
import os

/// On-device crash/diagnostic backstop.
///
/// Subscribes to MetricKit diagnostic payloads (crash + hang) and writes them to the
/// pullable diagnostics dir (`Library/Caches/Vocello/diagnostics/crashes/`) so
/// `scripts/ios_device.sh crashes` can pull them and `xcsym` / `axiom-tools`
/// can symbolicate against the build's preserved dSYM. Also installs an
/// `NSSetUncaughtExceptionHandler` as a fast path for Obj-C exceptions (MetricKit
/// covers signal faults and delivers them on the next launch). Best-effort; MetricKit
/// does the real capture and `.ips`-style JSON delivery.
///
/// No entitlement required. Started once from `QVoiceiOSApp.init()`. Writes only to
/// the `devicectl`-pullable app-container dir (the App-Group container is NOT pullable
/// — the same constraint `IOSDeviceDiagnosticsRunner` works around for its sentinel).
final class IOSCrashObserver: NSObject, @unchecked Sendable {
    static let shared = IOSCrashObserver()
    private let log = OSLog(subsystem: "com.patricedery.vocello", category: "crash")

    private override init() { super.init() }

    /// Idempotent start. Safe to call from `QVoiceiOSApp.init()` (MainActor).
    func start() {
        MXMetricManager.shared.add(self)
        // C function pointer — must not capture context; reach the singleton statically.
        NSSetUncaughtExceptionHandler { exception in
            IOSCrashObserver.shared.recordUncaught(exception)
        }
        os_log("started MetricKit crash/hang subscriber", log: log, type: .info)
    }

    /// The app's OWN container Caches dir (`Library/Caches/Vocello/diagnostics/crashes`)
    /// — the `devicectl`-pullable export location.
    static func pullableCrashesDir() -> URL? {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
            .appendingPathComponent("Vocello", isDirectory: true)
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("crashes", isDirectory: true)
    }

    private func writeJSON(_ data: Data, named name: String) {
        guard let dir = Self.pullableCrashesDir() else { return }
        let url = dir.appendingPathComponent(name, isDirectory: false)
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            os_log("wrote %{public}@", log: log, type: .info, url.lastPathComponent)
        } catch {
            os_log("write failed: %{public}@", log: log, type: .error, error.localizedDescription)
        }
    }

    private func recordUncaught(_ exception: NSException) {
        // Runs in normal (non-signal) context → Foundation/FileManager are safe here.
        let record: [String: Any] = [
            "kind": "uncaughtException",
            "name": exception.name.rawValue,
            "reason": exception.reason ?? "",
            "callStack": exception.callStackSymbols,
            "appVersion": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "",
            "buildVersion": Bundle.main.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String ?? "",
            "timestamp": ISO8601DateFormatter().string(from: Date()),
        ]
        let data = (try? JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])) ?? Data()
        writeJSON(data, named: "exception-\(stamp()).json")
    }

    private func stamp() -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date())
    }
}

extension IOSCrashObserver: MXMetricManagerSubscriber {
    func didReceive(_ payloads: [MXMetricPayload]) {
        // Daily performance metrics — not crash data. Intentionally ignored.
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for payload in payloads {
            // Only persist when there's something actionable. `jsonRepresentation()` is the
            // canonical MetricKit JSON (`.ips`-style) that `xcsym` can symbolicate.
            let crashes = payload.crashDiagnostics ?? []
            let hangs = payload.hangDiagnostics ?? []
            guard !(crashes.isEmpty && hangs.isEmpty) else { continue }
            writeJSON(payload.jsonRepresentation(), named: "metrickit-\(stamp()).json")
        }
    }
}
