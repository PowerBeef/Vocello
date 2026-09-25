import Foundation

/// Diagnostic override for the resolved `NativeDeviceMemoryClass`.
///
/// `NativeMemoryPolicyResolver.deviceClass()` normally reads real
/// `ProcessInfo.physicalMemory`, so a high-memory dev Mac always resolves to
/// `highMemoryMac` — where the constrained-tier policy (tight caches,
/// per-chunk clears, a short and pressure-adaptive idle unload) is never
/// exercised.
/// This gate lets a benchmark **force** a tier so those code paths run (and
/// pressure becomes measurable) without special hardware.
///
/// Plain runtime — **never `#if DEBUG`**, which is dead code in this
/// single-Release-config repo. Every host (macOS app, iOS app, `vocello` CLI)
/// runs the engine in-process, so the process reads
/// `QWENVOICE_FORCE_MEMORY_CLASS` itself through `RuntimeDebugGate`.
///
/// Off by default: unset env ⇒ `resolvedForcedClass == nil` ⇒
/// `deviceClass()` returns the real, physical-memory-derived tier (no behavior
/// change).
public enum NativeDeviceClassGate {
    private static let environmentKey = "QWENVOICE_FORCE_MEMORY_CLASS"

    /// The forced class for this process, parsed from the environment once per
    /// process. `nil` when unset or unrecognized ⇒ use the real tier.
    public static let resolvedForcedClass: NativeDeviceMemoryClass? = {
        parse(RuntimeDebugGate.value(for: environmentKey))
    }()

    /// Accepts the `NativeDeviceMemoryClass` rawValues
    /// (`floor_8gb_mac` / `mid_16gb_mac` / `high_memory_mac` / `iphone_pro`) plus a
    /// few friendly aliases. Case/whitespace-insensitive. Returns `nil` for empty
    /// or unrecognized input.
    static func parse(_ raw: String?) -> NativeDeviceMemoryClass? {
        guard let trimmed = raw?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
            !trimmed.isEmpty else {
            return nil
        }
        if let exact = NativeDeviceMemoryClass(rawValue: trimmed) {
            return exact
        }
        switch trimmed {
        case "8gb", "floor", "floor8gbmac":
            return .floor8GBMac
        case "16gb", "mid", "mid16gbmac":
            return .mid16GBMac
        case "high", "highmemorymac":
            return .highMemoryMac
        case "iphone", "iphonepro":
            return .iPhonePro
        default:
            return nil
        }
    }

    /// Whether the resolved tier is a diagnostic one rather than the host's
    /// native, physical-memory-derived tier: a forced class or an emulated
    /// smaller Mac. Rows stamp it as `notes.deviceClassForced`, so such evidence
    /// publishes only as exploratory and never seeds or meets a baseline.
    public static var resolvedTierIsDiagnostic: Bool {
        resolvedForcedClass != nil || NativeHostMemoryEmulation.current != nil
    }
}

/// Diagnostic emulation of a smaller Mac (audit #11 option b, maintainer
/// decision 2026-09-25): `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8` makes the
/// host read as an 8 GB machine wherever policy reads the machine's memory:
/// `NativeMemoryPolicyResolver.deviceClass()` (so the floor tier and its
/// policy), the store's footprint bands (`MacMemoryBudgetPolicy`) and the
/// snapshot's total RAM and Metal working set (two thirds of the emulated RAM,
/// 5,461 MB for 8 GB, the working set an 8 GB Mac reports), so the GPU
/// working-set ratio is judged against the floor's budget.
///
/// It emulates policy and footprint only. The kernel still has the real RAM:
/// no memory pressure, compression or real Metal budget of an 8 GB Mac is
/// reproduced, so emulated evidence never stands for the floor's timing or
/// pressure behavior. Only a smaller Mac can be emulated; a value at or above
/// the real RAM, a non-Mac host or an unparseable value leaves it off. Like
/// every production-affecting override it needs the internal-diagnostics
/// build plus `QWENVOICE_DEBUG` (`RuntimeDebugGate`).
public struct NativeHostMemoryEmulation: Hashable, Sendable {
    public static let environmentKey = "QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB"
    private static let bytesPerGiB: UInt64 = 1_073_741_824
    private static let bytesPerMiB: UInt64 = 1_048_576

    /// The emulated machine's physical memory.
    public let physicalMemoryBytes: UInt64
    /// The Metal recommended working set of the emulated machine: two thirds
    /// of its RAM, as macOS reports on 8 and 16 GB Apple silicon Macs.
    public let metalWorkingSetBytes: UInt64

    init(physicalMemoryBytes: UInt64) {
        self.physicalMemoryBytes = physicalMemoryBytes
        self.metalWorkingSetBytes = physicalMemoryBytes / 3 * 2
    }

    public var physicalMemoryMB: UInt64 { physicalMemoryBytes / Self.bytesPerMiB }
    public var metalWorkingSetMB: UInt64 { metalWorkingSetBytes / Self.bytesPerMiB }

    /// The emulation for this process, resolved once. nil (the default) keeps
    /// the real machine everywhere.
    public static let current: NativeHostMemoryEmulation? = {
        #if os(macOS)
        return resolve(
            RuntimeDebugGate.value(for: environmentKey),
            realPhysicalMemoryBytes: ProcessInfo.processInfo.physicalMemory
        )
        #else
        return nil
        #endif
    }()

    /// Accepts a whole number of GiB, optionally suffixed `gb`
    /// (case/whitespace-insensitive). Returns nil for empty or invalid input and
    /// for a machine that is not smaller than the real one.
    static func resolve(_ raw: String?, realPhysicalMemoryBytes: UInt64) -> NativeHostMemoryEmulation? {
        guard let trimmed = raw?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
            !trimmed.isEmpty else {
            return nil
        }
        let digits = trimmed.hasSuffix("gb") ? String(trimmed.dropLast(2)) : trimmed
        guard let gigabytes = UInt64(digits), gigabytes > 0, gigabytes < 4_096 else {
            return nil
        }
        let bytes = gigabytes * bytesPerGiB
        guard bytes < realPhysicalMemoryBytes else { return nil }
        return NativeHostMemoryEmulation(physicalMemoryBytes: bytes)
    }

    /// The physical memory policy reads: the emulated machine's when an
    /// emulation is active, otherwise `real`.
    public static func effectivePhysicalMemoryBytes(
        real: UInt64 = ProcessInfo.processInfo.physicalMemory,
        emulation: NativeHostMemoryEmulation? = current
    ) -> UInt64 {
        guard let emulation else { return real }
        return min(real, emulation.physicalMemoryBytes)
    }

    /// The Metal recommended working set policy reads: the emulated machine's
    /// when an emulation is active, otherwise `real`.
    public static func effectiveMetalWorkingSetBytes(
        real: UInt64,
        emulation: NativeHostMemoryEmulation? = current
    ) -> UInt64 {
        guard let emulation else { return real }
        return min(real, emulation.metalWorkingSetBytes)
    }
}
