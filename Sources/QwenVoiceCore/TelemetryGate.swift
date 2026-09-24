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
public enum TelemetryGate {
    private static let environmentKey = "QWENVOICE_DEBUG"
    private static let telemetryModeKey = "QWENVOICE_NATIVE_TELEMETRY_MODE"

    /// Resolved once per process from the environment.
    public static let isEnabled: Bool = resolve()

    private static let lock = NSLock()
    nonisolated(unsafe) private static var handshakeOverride = false
    nonisolated(unsafe) private static var handshakeMode: NativeTelemetryMode?

    /// Master on/off for durable telemetry persistence in this process.
    /// True if the environment enabled it, or a host latched a mode through
    /// `applyHandshakeMode(_:)`.
    public static var resolvedEnabled: Bool {
        if isEnabled { return true }
        lock.lock()
        defer { lock.unlock() }
        return handshakeOverride
    }

    /// Called by a host (today `vocello bench`) to latch a telemetry **mode** in this
    /// process. `isEnabled` is resolved once from the environment, possibly before the
    /// host parsed its flags, so `verbose` (raw per-sample sidecar) could otherwise miss
    /// the engine — this carries it. One-way latch; `.off` is ignored.
    public static func applyHandshakeMode(_ mode: NativeTelemetryMode) {
        guard mode != .off else { return }
        lock.lock()
        defer { lock.unlock() }
        handshakeOverride = true
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

    private static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        if let debug = environment[environmentKey]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
            ["1", "true", "on", "yes"].contains(debug) {
            return true
        }
        switch environment[telemetryModeKey]?.lowercased() {
        case "light", "lightweight", "verbose", "full", "deep":
            return true
        default:
            return false
        }
    }
}
