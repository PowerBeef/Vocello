import Foundation
import QwenVoiceCore

/// Gate for **proactive** engine warm-ups on every Mac tier — the macOS port
/// of the iOS admission discipline (`allowsProactiveWarmOperations`).
///
/// While the kernel reports memory pressure, pre-loading a 2.3 GB model "for
/// readiness" makes the very pressure that's stalling the UI worse. This
/// policy defers those warms until pressure clears (plus a short cool-down
/// after a hard trim on the floor tier). The high-memory tier is gated too
/// (AUD-10): memory-pressure relief applies there as on the other tiers.
/// **User-initiated work is never gated** — generations and explicit model
/// loads always proceed and surface their own errors.
///
/// Signal choice: the kernel pressure level via the app-process
/// `NativeMemoryPressureMonitor` (the signal Apple says to react to), NOT
/// the iOS `IOSMemoryBudgetPolicy` bands — those encode iPhone Jetsam
/// semantics (`os_proc_available_memory`) that don't translate to a Mac
/// with a compressor and swap.
///
/// Rollout: `QWENVOICE_MAC_WARM_GATE=off|records|enforce` (default
/// `records` while validating; flip the default to `enforce` after one
/// validation cycle). `records` computes + logs the verdict but lets warms
/// proceed.
@MainActor
final class MacWarmupAdmissionPolicy {
    enum Verdict: Equatable {
        case allow
        case deferred(reason: String)
    }

    enum Mode: String {
        case off
        case records
        case enforce

        static func fromEnvironment(
            _ environment: [String: String] = ProcessInfo.processInfo.environment
        ) -> Mode {
            // Default flipped records → enforce 2026-06-09 after the live
            // pressured validation (simulated hardTrim → both the live-level
            // and cool-down deferral paths observed on the floor tier).
            Mode(rawValue: RuntimeDebugGate.value(
                for: "QWENVOICE_MAC_WARM_GATE",
                environment: environment
            ) ?? "") ?? .enforce
        }
    }

    let mode: Mode
    private let deviceClass: NativeDeviceMemoryClass
    private let monitor: NativeMemoryPressureMonitor
    /// floor8GBMac hysteresis: stay deferred for a cool-down after a hard
    /// trim even once the kernel reports normal again.
    private let hardTrimCooldown: Duration = .seconds(30)
    private var lastHardTrimAt: ContinuousClock.Instant?
    private var eventTask: Task<Void, Never>?

    init(
        mode: Mode = .fromEnvironment(),
        deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass()
    ) {
        self.mode = mode
        self.deviceClass = deviceClass
        self.monitor = NativeMemoryPressureMonitor(
            label: "com.qwenvoice.app.memory-pressure"
        )

        guard mode != .off else { return }
        monitor.start()
        eventTask = Task { [weak self, monitor] in
            for await level in monitor.events {
                guard let self else { return }
                if level == .hardTrim {
                    self.lastHardTrimAt = ContinuousClock.now
                }
            }
        }
    }

    deinit {
        eventTask?.cancel()
        // Cancelling the consumer Task alone leaves the kernel DispatchSource
        // firing and the AsyncStream open — stop the monitor itself too.
        monitor.stop()
    }

    /// The raw decision, independent of mode.
    private func rawVerdict() -> Verdict {
        if let level = monitor.currentLevel {
            return .deferred(reason: "memory pressure (\(level))")
        }
        if deviceClass == .floor8GBMac,
           let lastHardTrimAt,
           lastHardTrimAt.duration(to: .now) < hardTrimCooldown {
            return .deferred(reason: "post-hardTrim cool-down")
        }
        return .allow
    }

    /// Verdict for a proactive warm about to dispatch. Always logs the
    /// observation; in `records` mode the returned verdict is `.allow` even
    /// when the raw decision deferred (the log row carries the truth).
    func admit(contextDescription: String) -> Verdict {
        guard mode != .off else { return .allow }
        let raw = rawVerdict()
        if case .deferred(let reason) = raw {
            Self.recordEvent(
                name: mode == .enforce ? "mac_warm_blocked" : "mac_warm_admission_observed",
                reason: reason,
                deviceClass: deviceClass,
                context: contextDescription
            )
            return mode == .enforce ? raw : .allow
        }
        return .allow
    }

    /// Append one JSONL event to diagnostics/app/native-events.jsonl —
    /// same artifact the engine's chunk-gap events land in.
    private static func recordEvent(
        name: String,
        reason: String,
        deviceClass: NativeDeviceMemoryClass,
        context: String
    ) {
        guard TelemetryGate.appProcessIntendedEnabled else { return }
        let appSupportDirectory = AppPaths.appSupportDir
        Task.detached(priority: .background) {
            let event: [String: Any] = [
                "event": name,
                "reason": reason,
                "deviceClass": String(describing: deviceClass),
                "context": context,
                "recordedAt": ISO8601DateFormatter().string(from: Date()),
            ]
            guard let data = try? JSONSerialization.data(withJSONObject: event),
                  var line = String(data: data, encoding: .utf8) else { return }
            line += "\n"
            let dir = appSupportDirectory.appendingPathComponent("diagnostics/app", isDirectory: true)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let url = dir.appendingPathComponent("native-events.jsonl")
            if let handle = try? FileHandle(forWritingTo: url) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: Data(line.utf8))
            } else {
                try? line.data(using: .utf8)?.write(to: url)
            }
        }
    }
}
