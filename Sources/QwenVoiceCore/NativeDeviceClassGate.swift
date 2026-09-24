import Foundation

/// Diagnostic override for the resolved `NativeDeviceMemoryClass`.
///
/// `NativeMemoryPolicyResolver.deviceClass()` normally reads real
/// `ProcessInfo.physicalMemory`, so a high-memory dev Mac always resolves to
/// `highMemoryMac` — where the memory-pressure monitor never starts and the
/// constrained-tier policy (tight caches, idle unload) is never exercised.
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
}
