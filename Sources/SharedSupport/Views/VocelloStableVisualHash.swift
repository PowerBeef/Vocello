import Foundation

/// Deterministic hashing for visual seeds (FNV-1a 64): the same string
/// renders the same waveform thumbnail and avatar hue on both platforms and
/// across launches. The iOS `IOSStableVisualHash` body, moved unchanged
/// (UIF-02); `IOSStableVisualHash` forwards here and the macOS
/// `MacStableVisualHash` twin is gone.
enum VocelloStableVisualHash {
    static func int(_ value: String) -> Int {
        Int(truncatingIfNeeded: fnv1a64(value))
    }

    static func normalized(_ value: String) -> Double {
        Double(fnv1a64(value) % 10_000) / 10_000.0
    }

    private static func fnv1a64(_ value: String) -> UInt64 {
        var hash: UInt64 = 0xcbf2_9ce4_8422_2325
        for byte in value.utf8 {
            hash ^= UInt64(byte)
            hash &*= 0x0000_0100_0000_01B3
        }
        return hash
    }
}
