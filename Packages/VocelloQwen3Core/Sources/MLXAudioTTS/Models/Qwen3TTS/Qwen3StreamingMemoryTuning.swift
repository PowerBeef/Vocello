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
    /// RF-52, A-02 (`QWENVOICE_ENCODER_ROTARY=split-half`): the speech
    /// tokenizer's encoder rotates the halves, as the reference encoder does.
    /// The host folds the same key into the clone prompt's speaker-feature
    /// version, so a prompt encoded one way is never adopted the other way.
    let encoderSplitHalfRotary: Bool
    /// RF-52, A-12: the clone reference is encoded as it is, as upstream does
    /// (production since 2026-11-11); `QWENVOICE_REFERENCE_PADDING=half-second`
    /// restores the half second of zeros Vocello appended before. The host
    /// folds the same key into the clone prompt's speaker-feature version.
    let referenceTrailingSilenceSamples: Int
    /// RF-54 (`QWENVOICE_DECODER_WINDOW=on`): the speech tokenizer's decoder
    /// applies its configured attention window (72 frames), as upstream does.
    let decoderSlidingWindow: Bool

    init(
        talkerKVQuantBits: Int?,
        speechTokenizerResidency: Bool?,
        encoderSplitHalfRotary: Bool = false,
        referenceTrailingSilenceSamples: Int = Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
        decoderSlidingWindow: Bool = false
    ) {
        self.talkerKVQuantBits = talkerKVQuantBits
        self.speechTokenizerResidency = speechTokenizerResidency
        self.encoderSplitHalfRotary = encoderSplitHalfRotary
        self.referenceTrailingSilenceSamples = referenceTrailingSilenceSamples
        self.decoderSlidingWindow = decoderSlidingWindow
    }

    static let production = Qwen3LoadTimeDiagnosticOverrides(
        talkerKVQuantBits: nil,
        speechTokenizerResidency: nil,
        encoderSplitHalfRotary: false,
        referenceTrailingSilenceSamples: Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
        decoderSlidingWindow: false
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
            speechTokenizerResidency: speechTokenizerResidency,
            encoderSplitHalfRotary: gatedValue("QWENVOICE_ENCODER_ROTARY") == "split-half",
            referenceTrailingSilenceSamples: gatedValue("QWENVOICE_REFERENCE_PADDING") == "half-second"
                ? Qwen3TTSReferenceAudio.legacyTrailingSilenceSamples
                : Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
            decoderSlidingWindow: gatedValue("QWENVOICE_DECODER_WINDOW") == "on"
        )
    }
}
