import Foundation

/// Debug-only load-time behavior, resolved once per model load through
/// `VocelloQwen3ImplementationDebugGate` and carried as an immutable value.
/// Request-varying memory behavior belongs exclusively to
/// `Qwen3RequestMemoryPolicy`; generation never mutates this value.
/// `.production` (no overrides) is what every load gets unless its host
/// attests the internal diagnostics capability and `QWENVOICE_DEBUG` is set.
struct Qwen3LoadTimeDiagnosticOverrides: Sendable, Equatable {
    /// Opt-in talker KV-cache quantization (P4 A/B; dev knob, default off):
    /// `QVOICE_TALKER_KV_QUANT=8|4` → QuantizedKVCache(groupSize: 64, bits: n).
    /// Quality-sensitive (clone fidelity) — ships per-tier only after fixed-seed
    /// exact-WAV QC plus the applicable ASR/prosody gates. Never combined with the rotating-window cache (its
    /// toQuantized is unimplemented upstream); the window policy wins if both
    /// are set.
    let talkerKVQuantBits: Int?
    /// Phase 9 residency A/B switch (`QWENVOICE_TOKENIZER_RESIDENCY`):
    /// `false` disables residency anywhere, `true` force-enables it (the iOS
    /// qualification lane's entry point while the adaptive heuristic is dark),
    /// `nil` keeps the device-class policy.
    let speechTokenizerResidency: Bool?

    static let production = Qwen3LoadTimeDiagnosticOverrides(
        talkerKVQuantBits: nil,
        speechTokenizerResidency: nil
    )

    static func resolve(
        internalDiagnosticsAvailable: Bool,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Qwen3LoadTimeDiagnosticOverrides {
        func gatedValue(_ key: String) -> String? {
            VocelloQwen3ImplementationDebugGate.value(
                for: key,
                internalDiagnosticsAvailable: internalDiagnosticsAvailable,
                environment: environment
            )?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        }

        let talkerKVQuantBits = gatedValue("QVOICE_TALKER_KV_QUANT")
            .flatMap { Int($0) }
            .flatMap { $0 == 4 || $0 == 8 ? $0 : nil }
        let speechTokenizerResidency: Bool?
        switch gatedValue("QWENVOICE_TOKENIZER_RESIDENCY") {
        case "off"?, "false"?, "0"?, "no"?:
            speechTokenizerResidency = false
        case "on"?, "true"?, "1"?, "yes"?:
            speechTokenizerResidency = true
        default:
            speechTokenizerResidency = nil
        }
        return Qwen3LoadTimeDiagnosticOverrides(
            talkerKVQuantBits: talkerKVQuantBits,
            speechTokenizerResidency: speechTokenizerResidency
        )
    }
}
