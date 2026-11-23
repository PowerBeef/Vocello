import Foundation

/// RF-55 / RF-70: which of the talker's modules a mixed-precision load takes
/// from the 8-bit sibling. Every recipe keeps q, k and v at one precision, and
/// gate and up at one, so the fused projections (RF-46) stay fused: a recipe
/// that split them would pay for three products where one runs today.
///
/// The layer-only recipes (`down`, `attn`, `attn-down`, `mlp`, `talker`) never
/// touch the code predictor. The Pack C recipes (`attn-io`, `attn-io-edge`)
/// keep the code predictor's transformer layers and embeddings at 4 bits while
/// promoting only its lightweight projection/head I/O boundaries
/// (`code_predictor.small_to_mtp_projection`, `code_predictor.lm_head.*`) along
/// with the talker's I/O projections (`text_projection.linear_fc1/2`,
/// `codec_head`) and (for `attn-io-edge`) edge layers `{0, 1, 26, 27}` MLPs.
enum Qwen3MixedPrecisionRecipe: String, Sendable, Equatable, CaseIterable {
    /// The MLP down projection.
    case down
    /// The four attention projections.
    case attn
    /// All four attention projections and the MLP down projection.
    case attnDown = "attn-down"
    /// The three MLP projections.
    case mlp
    /// Every tensor of the talker's layers.
    case talker
    /// Pack C Bundle A (`+24.12 MB` over `attn`): the four attention projections
    /// across all layers plus talker/code-predictor I/O projections
    /// (`text_projection.linear_fc1/2`, `codec_head`,
    /// `code_predictor.small_to_mtp_projection`, `code_predictor.lm_head.*`).
    case attnIO = "attn-io"
    /// Pack C Bundle B (`+99.61 MB` over `attn`): `attn-io` plus the three MLP
    /// projections of talker edge layers `0`, `1`, `26`, and `27`.
    case attnIOEdge = "attn-io-edge"

    private static let attentionLeaves: Set<String> = ["q_proj", "k_proj", "v_proj", "o_proj"]
    private static let mlpLeaves: Set<String> = ["gate_proj", "up_proj", "down_proj"]
    private static let edgeLayerIndices: Set<Int> = [0, 1, 26, 27]
    private static let ioProjectionModules: Set<String> = [
        "text_projection.linear_fc1",
        "text_projection.linear_fc2",
        "codec_head",
        "code_predictor.small_to_mtp_projection",
    ]
    private static let codePredictorLMHeadPrefix = "code_predictor.lm_head."

    private static func isIOProjection(_ path: String) -> Bool {
        if ioProjectionModules.contains(path) {
            return true
        }
        guard path.hasPrefix(codePredictorLMHeadPrefix) else { return false }
        let suffix = path.dropFirst(codePredictorLMHeadPrefix.count)
        return !suffix.isEmpty && suffix.allSatisfy { $0.isASCII && $0.isNumber }
    }

    private static func isEdgeLayerMLP(_ path: String) -> Bool {
        let parts = path.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 5,
              parts[0] == "model",
              parts[1] == "layers",
              let layerIndex = Int(parts[2]),
              edgeLayerIndices.contains(layerIndex),
              parts[3] == "mlp"
        else { return false }
        return mlpLeaves.contains(String(parts[4]))
    }

    /// Whether the talker module at `path` (e.g. `model.layers.3.self_attn.v_proj`,
    /// `codec_head`, `code_predictor.lm_head.0`) comes from the sibling.
    func selects(_ path: String) -> Bool {
        switch self {
        case .attnIO:
            return Self.isIOProjection(path) || Self.attn.selects(path)
        case .attnIOEdge:
            return Self.attnIO.selects(path) || Self.isEdgeLayerMLP(path)
        case .down, .attn, .attnDown, .mlp, .talker:
            guard path.hasPrefix("model.layers.") else { return false }
            let leaf = path.split(separator: ".").last.map(String.init) ?? ""
            switch self {
            case .down: return leaf == "down_proj"
            case .attn: return Self.attentionLeaves.contains(leaf)
            case .attnDown: return Self.attentionLeaves.contains(leaf) || leaf == "down_proj"
            case .mlp: return Self.mlpLeaves.contains(leaf)
            case .talker: return true
            case .attnIO, .attnIOEdge: return false
            }
        }
    }
}

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
    /// RF-52, A-12: the clone reference is encoded with no padding, as
    /// upstream does (production since 2026-11-11); `QWENVOICE_REFERENCE_PADDING=half-second`
    /// restores the half second of zeros Vocello appended before. The host
    /// folds the same key into the clone prompt's speaker-feature version.
    let referenceTrailingSilenceSamples: Int
    /// RF-54 (`QWENVOICE_DECODER_WINDOW=on`): the speech tokenizer's decoder
    /// applies its configured attention window (72 frames), as upstream does.
    let decoderSlidingWindow: Bool
    /// RF-52, A-04: a streamed transcript-backed clone decodes the reference's
    /// codes first and keeps none of their samples, as the quality-first path
    /// and upstream's ICL decode do (production since 2026-11-12, adopted by
    /// the clone screen's rule `clone-decoder-history-primed-confirm`).
    /// `QWENVOICE_CLONE_DECODER_HISTORY=cold` restores the cold decoder.
    let cloneDecoderPriming: Bool
    /// RF-55 (`QWENVOICE_CODE_PREDICTOR_BITS=8`): the talker's code predictor
    /// is taken from the installed sibling of this model at that precision
    /// (the 8-bit artifact of the same mode, which carries its integrity
    /// record), the rest of the talker staying as installed. nil loads the
    /// model as it is.
    let codePredictorBits: Int?
    /// RF-55 (`QWENVOICE_MIXED_PRECISION=<recipe>`): the talker tensors the
    /// recipe names are taken from the installed 8-bit sibling of this model,
    /// the rest staying as installed, so a mixed-precision model can be
    /// measured before any artifact is built. nil loads the model as it is.
    let mixedPrecisionRecipe: Qwen3MixedPrecisionRecipe?
    /// RF-52, A-11: a clone target whose first letter is Han or kana follows
    /// the reference transcript with no separator, as upstream joins them;
    /// every other target keeps its one leading space. On in production since
    /// 2026-11-12 (the clone-cjk screen's rule icl-target-space-unspaced-scripts);
    /// the gated `QWENVOICE_ICL_TARGET_SPACE=every-target` puts one space before
    /// every target again.
    let iclTargetSpaceOnlyBeforeSpacedScripts: Bool
    /// RF-52, G-07: a transcript-backed clone reference's silent edges are
    /// trimmed and it is faded in and out before the speaker embedding and the
    /// codec encode read it (`Qwen3TTSReferenceAudio.edgesTrimmedAndFaded`). On
    /// in production since 2026-11-12 (the clone screen's rule
    /// reference-edges-trimmed); the gated `QWENVOICE_REFERENCE_EDGES=as-given`
    /// takes the reference as given, as upstream does. Audio-only prompts always
    /// take it as given. The host folds the same key into
    /// the clone prompt's speaker-feature version.
    let referenceEdgesTrimmed: Bool

    init(
        talkerKVQuantBits: Int?,
        speechTokenizerResidency: Bool?,
        encoderSplitHalfRotary: Bool = false,
        referenceTrailingSilenceSamples: Int = Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
        decoderSlidingWindow: Bool = false,
        cloneDecoderPriming: Bool = true,
        codePredictorBits: Int? = nil,
        mixedPrecisionRecipe: Qwen3MixedPrecisionRecipe? = nil,
        iclTargetSpaceOnlyBeforeSpacedScripts: Bool = true,
        referenceEdgesTrimmed: Bool = true
    ) {
        self.talkerKVQuantBits = talkerKVQuantBits
        self.speechTokenizerResidency = speechTokenizerResidency
        self.encoderSplitHalfRotary = encoderSplitHalfRotary
        self.referenceTrailingSilenceSamples = referenceTrailingSilenceSamples
        self.decoderSlidingWindow = decoderSlidingWindow
        self.cloneDecoderPriming = cloneDecoderPriming
        self.codePredictorBits = codePredictorBits
        self.mixedPrecisionRecipe = mixedPrecisionRecipe
        self.iclTargetSpaceOnlyBeforeSpacedScripts = iclTargetSpaceOnlyBeforeSpacedScripts
        self.referenceEdgesTrimmed = referenceEdgesTrimmed
    }

    static let production = Qwen3LoadTimeDiagnosticOverrides(
        talkerKVQuantBits: nil,
        speechTokenizerResidency: nil,
        encoderSplitHalfRotary: false,
        referenceTrailingSilenceSamples: Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
        decoderSlidingWindow: false,
        cloneDecoderPriming: true,
        codePredictorBits: nil,
        mixedPrecisionRecipe: nil,
        iclTargetSpaceOnlyBeforeSpacedScripts: true,
        referenceEdgesTrimmed: true
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
            decoderSlidingWindow: gatedValue("QWENVOICE_DECODER_WINDOW") == "on",
            cloneDecoderPriming: gatedValue("QWENVOICE_CLONE_DECODER_HISTORY") != "cold",
            codePredictorBits: gatedValue("QWENVOICE_CODE_PREDICTOR_BITS") == "8" ? 8 : nil,
            mixedPrecisionRecipe: gatedValue("QWENVOICE_MIXED_PRECISION").flatMap(Qwen3MixedPrecisionRecipe.init(rawValue:)),
            iclTargetSpaceOnlyBeforeSpacedScripts: gatedValue("QWENVOICE_ICL_TARGET_SPACE") != "every-target",
            referenceEdgesTrimmed: gatedValue("QWENVOICE_REFERENCE_EDGES") != "as-given"
        )
    }
}
