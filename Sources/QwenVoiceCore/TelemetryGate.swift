import Foundation

/// Process-portable runtime gate for durable generation telemetry.
///
/// `TelemetryGate` is the Core-visible equivalent every process can read, so
/// telemetry persistence is gated at runtime
/// (never compiled out, no `#if DEBUG`): dev and shipped binaries run identical paths.
///
/// Resolution sources:
/// - `QWENVOICE_DEBUG` env var (`1` / `true` / `on` / `yes`) — mirrors `DebugMode`'s env
///   key, so `scripts/build.sh run` lights up every process it launches.
/// - `QWENVOICE_NATIVE_TELEMETRY_MODE` set to `light` / `lightweight` (back-compat).
/// - An in-process override (`applyHandshakeMode(_:)`): `vocello bench` latches its
///   `--telemetry` mode so `verbose` reaches the engine even if `isEnabled` was already
///   resolved. The name predates the retired XPC `initialize` handshake. Every host now
///   runs the engine in-process, so the latch is set and read in the same process.
///
/// An explicit off wins. `QWENVOICE_DEBUG` is also the master switch for
/// production-affecting diagnostics (`RuntimeDebugGate`), which a telemetry-off
/// benchmark still needs for its registered overrides; it must not turn the
/// telemetry that run disabled back on. So `QWENVOICE_NATIVE_TELEMETRY_MODE=off`
/// (or `disabled`) and a latched `.off` both resolve telemetry off whatever
/// `QWENVOICE_DEBUG` says. `RuntimeDebugGate` itself is unchanged: overrides
/// still need the internal-diagnostics build and the master switch.
public enum TelemetryGate {
    private static let environmentKey = "QWENVOICE_DEBUG"
    private static let telemetryModeKey = "QWENVOICE_NATIVE_TELEMETRY_MODE"

    /// Resolved once per process from the environment.
    public static let isEnabled: Bool = resolve()

    private static let lock = NSLock()
    nonisolated(unsafe) private static var handshakeOverride = false
    nonisolated(unsafe) private static var handshakeMode: NativeTelemetryMode?

    /// Master on/off for durable telemetry persistence in this process.
    /// True if the environment enabled it, or a host latched a non-off mode
    /// through `applyHandshakeMode(_:)`; false whenever a host latched `.off`.
    public static var resolvedEnabled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return resolve(
            environmentEnabled: isEnabled,
            latchedEnabled: handshakeOverride,
            latchedMode: handshakeMode
        )
    }

    /// Pure precedence seam for deterministic tests: a latched `.off` wins,
    /// then the environment decision, then a latched non-off mode.
    static func resolve(
        environmentEnabled: Bool,
        latchedEnabled: Bool,
        latchedMode: NativeTelemetryMode?
    ) -> Bool {
        if latchedMode == .off { return false }
        return environmentEnabled || latchedEnabled
    }

    /// Called by a host (today `vocello bench`) to latch a telemetry **mode** in this
    /// process. `isEnabled` is resolved once from the environment, possibly before the
    /// host parsed its flags, so `verbose` (raw per-sample sidecar) could otherwise miss
    /// the engine — this carries it. `.off` latches telemetry off for the rest of the
    /// process, even when `QWENVOICE_DEBUG` resolved it on first.
    public static func applyHandshakeMode(_ mode: NativeTelemetryMode) {
        lock.lock()
        defer { lock.unlock() }
        handshakeOverride = mode != .off
        handshakeMode = mode
    }

    /// The latched mode, or nil when no host latched one.
    public static var handshakeResolvedMode: NativeTelemetryMode? {
        lock.lock()
        defer { lock.unlock() }
        return handshakeMode
    }

    /// The telemetry **mode** for this process — `NativeTelemetryMode.current()` (the
    /// env mode, else a latched mode) when it is not `.off`, else `.lightweight` when
    /// the explicit process gate is on, else `.off`.
    public static var appProcessIntendedMode: NativeTelemetryMode {
        let envMode = NativeTelemetryMode.current()
        if envMode != .off { return envMode }
        return appProcessIntendedEnabled ? .lightweight : .off
    }

    /// The telemetry decision from this process's environment, ignoring any
    /// latched mode.
    public static var appProcessIntendedEnabled: Bool {
        isEnabled
    }

    static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        let mode = environment[telemetryModeKey]?.lowercased()
        // Same spellings `NativeTelemetryMode.current(environment:)` reads as off.
        if mode == "off" || mode == "disabled" {
            return false
        }
        if let debug = environment[environmentKey]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
            ["1", "true", "on", "yes"].contains(debug) {
            return true
        }
        switch mode {
        case "light", "lightweight", "verbose", "full", "deep":
            return true
        default:
            return false
        }
    }
}
