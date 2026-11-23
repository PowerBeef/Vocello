import Foundation
import MLX
import MLXAudioCodecs
import MLXLMCommon
import MLXNN
@testable import MLXAudioTTS
import XCTest

/// Phase 9: speech-tokenizer residency semantics — content-exact adoption
/// with the encoder-superset rule, lifecycle clearing, the fail-safe
/// file-identity helper, and the capability-gated load-time diagnostic
/// overrides (residency and talker KV quantization).
final class Qwen3SpeechTokenizerResidencyTests: XCTestCase {
    private let everyOverrideRequested = [
        "QWENVOICE_DEBUG": "1",
        "QVOICE_TALKER_KV_QUANT": "8",
        "QWENVOICE_TOKENIZER_RESIDENCY": "off",
        "QWENVOICE_ENCODER_ROTARY": "split-half",
        "QWENVOICE_DECODER_WINDOW": "on",
        "QWENVOICE_CLONE_DECODER_HISTORY": "cold",
        "QWENVOICE_CODE_PREDICTOR_BITS": "8",
        "QWENVOICE_MIXED_PRECISION": "down",
        "QWENVOICE_ICL_TARGET_SPACE": "every-target",
        "QWENVOICE_REFERENCE_EDGES": "as-given",
    ]

    /// A resident tokenizer is reused only by a load that asked for the same
    /// encoder rotary and decoder window: each key changes the reuse key, and
    /// without either the content identity is the key, as before them.
    func testTheResidencyKeySeparatesEveryDiagnosticBuildOfTheTokenizer() {
        func key(encoder: Bool, rotary: Bool = false, window: Bool = false) -> String {
            Qwen3TTSModel.speechTokenizerResidencyIdentity(
                contentIdentity: "trust:digest",
                includeEncoder: encoder,
                overrides: Qwen3LoadTimeDiagnosticOverrides(
                    talkerKVQuantBits: nil, speechTokenizerResidency: nil,
                    encoderSplitHalfRotary: rotary, decoderSlidingWindow: window)
            )
        }
        for encoder in [true, false] {
            XCTAssertEqual(Qwen3TTSModel.speechTokenizerResidencyIdentity(
                contentIdentity: "trust:digest", includeEncoder: encoder, overrides: .production), "trust:digest")
            XCTAssertEqual(key(encoder: encoder), "trust:digest")
            XCTAssertEqual(key(encoder: encoder, window: true), key(encoder: encoder) + "|decoder-sliding-window")
        }
        XCTAssertEqual(key(encoder: true, rotary: true), "trust:digest|encoder-rope-split-half")
        XCTAssertEqual(key(encoder: false, rotary: true), "trust:digest", "no encoder, so its rotary is moot")
        XCTAssertEqual(key(encoder: true, rotary: true, window: true),
                       "trust:digest|encoder-rope-split-half|decoder-sliding-window")
        let keys = [key(encoder: true), key(encoder: true, rotary: true), key(encoder: true, window: true),
                    key(encoder: true, rotary: true, window: true)]
        XCTAssertEqual(Set(keys).count, keys.count)
    }

    /// RF-55: the code predictor's sibling is the same model's installed
    /// artifact at the asked precision, and nothing else.
    func testTheCodePredictorSiblingIsOnlyTheInstalledSameModelAtThatPrecision() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("cp-sibling-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let own = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-4bit")
        let sibling = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-8bit")
        XCTAssertEqual(try Qwen3TTSModel.codePredictorSiblingDirectory(of: own, ownBits: 4, bits: 8).lastPathComponent,
                       sibling.lastPathComponent)
        XCTAssertThrowsError(try Qwen3TTSModel.codePredictorSiblingDirectory(
            of: root.appendingPathComponent("unnamed"), ownBits: 4, bits: 8))
        func write(_ directory: URL, type: String, bits: Int, installed: Bool) throws {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let config = #"{"tts_model_type": "\#(type)", "quantization": {"group_size": 64, "bits": \#(bits)}}"#
            try Data(config.utf8).write(to: directory.appendingPathComponent("config.json"))
            if installed {
                try Data("{}".utf8).write(to: directory.appendingPathComponent(".qwenvoice-model-integrity.json"))
            } else {
                try? FileManager.default.removeItem(at: directory.appendingPathComponent(".qwenvoice-model-integrity.json"))
            }
        }
        let ownConfig = try JSONDecoder().decode(
            Qwen3TTSModelConfig.self, from: Data(#"{"tts_model_type": "base"}"#.utf8))
        XCTAssertThrowsError(try Qwen3TTSModel.codePredictorSibling(of: own, config: ownConfig, ownBits: 4, bits: 8),
                             "no sibling installed")
        try write(sibling, type: "base", bits: 8, installed: false)
        XCTAssertThrowsError(try Qwen3TTSModel.codePredictorSibling(of: own, config: ownConfig, ownBits: 4, bits: 8),
                             "a directory without its integrity record is not an installed artifact")
        try write(sibling, type: "custom_voice", bits: 8, installed: true)
        XCTAssertThrowsError(try Qwen3TTSModel.codePredictorSibling(of: own, config: ownConfig, ownBits: 4, bits: 8),
                             "another model type")
        try write(sibling, type: "base", bits: 4, installed: true)
        XCTAssertThrowsError(try Qwen3TTSModel.codePredictorSibling(of: own, config: ownConfig, ownBits: 4, bits: 8),
                             "another precision")
        try write(sibling, type: "base", bits: 8, installed: true)
        let resolved = try Qwen3TTSModel.codePredictorSibling(of: own, config: ownConfig, ownBits: 4, bits: 8)
        XCTAssertEqual(resolved.directory.lastPathComponent, sibling.lastPathComponent)
        XCTAssertEqual(resolved.quantization.bits, 8)
        XCTAssertEqual(resolved.quantization.groupSize, 64)

        // Hosts load from a prepared overlay whose weights link into the
        // installed folder: the sibling is found beside the installed folder.
        try FileManager.default.createDirectory(at: own, withIntermediateDirectories: true)
        try Data("weights".utf8).write(to: own.appendingPathComponent("model.safetensors"))
        let overlay = root.appendingPathComponent("cache/prepared_models/Qwen3-TTS-12Hz-1.7B-Base-4bit")
        try FileManager.default.createDirectory(at: overlay, withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(
            at: overlay.appendingPathComponent("model.safetensors"),
            withDestinationURL: own.appendingPathComponent("model.safetensors"))
        XCTAssertEqual(Qwen3TTSModel.installedDirectory(of: overlay).standardizedFileURL.resolvingSymlinksInPath().path,
                       own.standardizedFileURL.resolvingSymlinksInPath().path)
        let throughOverlay = try Qwen3TTSModel.codePredictorSibling(of: overlay, config: ownConfig, ownBits: 4, bits: 8)
        XCTAssertEqual(throughOverlay.directory.lastPathComponent, sibling.lastPathComponent)
        XCTAssertEqual(Qwen3TTSModel.installedDirectory(of: own).standardizedFileURL.resolvingSymlinksInPath().path,
                       own.standardizedFileURL.resolvingSymlinksInPath().path, "a folder loaded in place is its own")
    }

    /// RF-55: only the code predictor takes the sibling's recipe; everything
    /// else keeps the model's own per-layer and global recipes.
    func testOnlyTheCodePredictorTakesTheSiblingsQuantization() throws {
        let config = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(#"""
            {"model_type": "qwen3_tts", "tts_model_type": "base", "quantization": {"group_size": 64, "bits": 4, "mode": "affine",
             "model.text_embedding": {"group_size": 64, "bits": 8, "mode": "affine"}}}
            """#.utf8))
        let eight: (Int, Int, QuantizationMode) = (64, 8, .affine)
        func bits(_ path: String, scales: Bool = true, sibling: Bool = true) -> Int? {
            Qwen3TTSModel.talkerQuantization(
                path: path, hasScales: scales, config: config, codePredictor: sibling ? eight : nil)?.1
        }
        XCTAssertEqual(bits("code_predictor.lm_head.3"), 8)
        XCTAssertEqual(bits("code_predictor.model.layers.2.self_attn.q_proj"), 8)
        XCTAssertNil(bits("code_predictor.model.codec_embedding.0", scales: false), "no scales, never quantized")
        XCTAssertEqual(bits("model.text_embedding"), 8, "its own per-layer recipe")
        XCTAssertEqual(bits("codec_head"), 4)
        XCTAssertEqual(bits("model.layers.0.mlp.gate_proj"), 4)
        XCTAssertEqual(bits("code_predictor_shadow.proj"), 4, "only the code predictor itself")

        // A mixed-precision recipe gives the sibling's recipe to the layer
        // tensors it names, never to the code predictor or anything else.
        func mixedBits(_ path: String, _ recipe: Qwen3MixedPrecisionRecipe) -> Int? {
            Qwen3TTSModel.talkerQuantization(
                path: path, hasScales: true, config: config, codePredictor: nil, mixed: (eight, recipe))?.1
        }
        let layer = "model.layers.7."
        let expected: [Qwen3MixedPrecisionRecipe: Set<String>] = [
            .down: ["mlp.down_proj"],
            .attn: ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj"],
            .attnDown: ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj", "mlp.down_proj"],
            .mlp: ["mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"],
            .talker: ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj",
                      "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"],
        ]
        XCTAssertEqual(Set(expected.keys), Set(Qwen3MixedPrecisionRecipe.allCases))
        for (recipe, eightBit) in expected {
            for leaf in expected[.talker]! {
                XCTAssertEqual(mixedBits(layer + leaf, recipe), eightBit.contains(leaf) ? 8 : 4, "\(recipe) \(leaf)")
            }
            XCTAssertEqual(mixedBits("code_predictor.model.layers.2.mlp.down_proj", recipe), 4, "never the code predictor")
            XCTAssertEqual(mixedBits("codec_head", recipe), 4)
            XCTAssertEqual(mixedBits("model.text_embedding", recipe), 8, "its own per-layer recipe")
            // The fused projections need their members at one precision.
            XCTAssertEqual(Set(["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj"].map(eightBit.contains)).count, 1)
            XCTAssertEqual(Set(["mlp.gate_proj", "mlp.up_proj"].map(eightBit.contains)).count, 1)
            // The weights replaced are exactly the selected modules' tensors.
            for leaf in expected[.talker]! {
                for tensor in ["weight", "scales", "biases"] {
                    XCTAssertEqual(Qwen3TTSModel.takesFromSibling(
                        weightKey: "\(layer)\(leaf).\(tensor)", codePredictor: false, recipe: recipe),
                        eightBit.contains(leaf), "\(recipe) \(leaf) \(tensor)")
                }
            }
        }
        // The weights replaced are exactly those modules' tensors.
        XCTAssertTrue(Qwen3TTSModel.takesFromSibling(
            weightKey: "model.layers.7.mlp.down_proj.scales", codePredictor: false, recipe: .down))
        XCTAssertFalse(Qwen3TTSModel.takesFromSibling(
            weightKey: "model.layers.7.mlp.up_proj.weight", codePredictor: false, recipe: .down))
        XCTAssertFalse(Qwen3TTSModel.takesFromSibling(
            weightKey: "code_predictor.lm_head.3.weight", codePredictor: false, recipe: .talker))
        XCTAssertTrue(Qwen3TTSModel.takesFromSibling(
            weightKey: "code_predictor.lm_head.3.weight", codePredictor: true, recipe: nil))
        XCTAssertTrue(Qwen3TTSModel.takesFromSibling(
            weightKey: "model.layers.0.input_layernorm.weight", codePredictor: false, recipe: .talker))
        XCTAssertFalse(Qwen3TTSModel.takesFromSibling(
            weightKey: "model.layers.0.mlp.down_proj.weight", codePredictor: true, recipe: nil))
        XCTAssertEqual(bits("code_predictor.lm_head.3", sibling: false), 4, "without the key, as installed")
    }

    /// A distribution host (app or CLI) attests no internal diagnostics
    /// capability, so the master gate and every override key are inert.
    func testLoadTimeOverridesAreInertWithoutInternalCapabilityEvenWithDebugGate() {
        XCTAssertEqual(
            Qwen3LoadTimeDiagnosticOverrides.resolve(
                internalDiagnosticsAvailable: false,
                environment: everyOverrideRequested
            ),
            .production
        )
        for key in everyOverrideRequested.keys {
            XCTAssertNil(
                VocelloQwen3ImplementationDebugGate.value(
                    for: key,
                    internalDiagnosticsAvailable: false,
                    environment: everyOverrideRequested
                ),
                key
            )
        }
        // Fail closed by default: a consumer that attests nothing gets no
        // capability, and the production residency policy is unchanged.
        XCTAssertFalse(QwenPreparedLoadBehavior().internalDiagnosticsAvailable)
        XCTAssertFalse(QwenPreparedLoadBehavior.fullCapabilities.internalDiagnosticsAvailable)
        XCTAssertFalse(QwenPreparedLoadBehavior.streamingOnly.internalDiagnosticsAvailable)
        XCTAssertEqual(
            Qwen3TTSPreparedComponentCache.speechTokenizerResidencyEnabled(
                override: Qwen3LoadTimeDiagnosticOverrides.production.speechTokenizerResidency
            ),
            Qwen3TTSPreparedComponentCache.speechTokenizerResidencySupported
        )
    }

    func testLoadTimeOverridesRequireBothCapabilityAndDebugGate() {
        var withoutMasterGate = everyOverrideRequested
        withoutMasterGate["QWENVOICE_DEBUG"] = nil
        XCTAssertEqual(
            Qwen3LoadTimeDiagnosticOverrides.resolve(
                internalDiagnosticsAvailable: true,
                environment: withoutMasterGate
            ),
            .production
        )

        let internalRun = Qwen3LoadTimeDiagnosticOverrides.resolve(
            internalDiagnosticsAvailable: true,
            environment: everyOverrideRequested
        )
        XCTAssertEqual(internalRun.talkerKVQuantBits, 8)
        XCTAssertEqual(internalRun.speechTokenizerResidency, false)
        XCTAssertTrue(internalRun.encoderSplitHalfRotary)
        XCTAssertTrue(internalRun.decoderSlidingWindow)
        XCTAssertFalse(Qwen3LoadTimeDiagnosticOverrides.production.decoderSlidingWindow)
        // RF-55: a mixed-precision recipe, only by its exact name.
        XCTAssertEqual(internalRun.mixedPrecisionRecipe, .down)
        XCTAssertNil(Qwen3LoadTimeDiagnosticOverrides.production.mixedPrecisionRecipe)
        for (value, expected) in [(" MLP ", Qwen3MixedPrecisionRecipe.mlp), ("attn-down", .attnDown), ("talker", .talker),
                                  ("on", nil), ("v-down", nil), ("", nil)] as [(String, Qwen3MixedPrecisionRecipe?)] {
            var mixed = everyOverrideRequested
            mixed["QWENVOICE_MIXED_PRECISION"] = value
            XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: mixed)
                .mixedPrecisionRecipe, expected, value)
            XCTAssertNil(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: mixed)
                .mixedPrecisionRecipe, value)
        }
        // RF-55: the code predictor from the 8-bit sibling, only for "8".
        XCTAssertEqual(internalRun.codePredictorBits, 8)
        XCTAssertNil(Qwen3LoadTimeDiagnosticOverrides.production.codePredictorBits)
        for value in ["4", "16", "on", ""] {
            var bits = everyOverrideRequested
            bits["QWENVOICE_CODE_PREDICTOR_BITS"] = value
            XCTAssertNil(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: bits)
                .codePredictorBits, value)
        }
        XCTAssertNil(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: everyOverrideRequested)
            .codePredictorBits)
        // A-04: a streamed clone's decoder is primed with the reference by
        // default (adopted 2026-11-12); only the gated key restores it cold.
        XCTAssertFalse(internalRun.cloneDecoderPriming)
        XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.production.cloneDecoderPriming)
        for (value, expected) in [(" Cold ", false), ("primed", true), ("off", true), ("", true)] {
            var history = everyOverrideRequested
            history["QWENVOICE_CLONE_DECODER_HISTORY"] = value
            XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: history)
                .cloneDecoderPriming, expected, value)
            XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: history)
                .cloneDecoderPriming, value)
        }
        for (value, expected) in [(" On ", true), ("1", false), ("off", false), ("", false)] {
            var windowed = everyOverrideRequested
            windowed["QWENVOICE_DECODER_WINDOW"] = value
            XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: windowed)
                .decoderSlidingWindow, expected, value)
            XCTAssertFalse(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: windowed)
                .decoderSlidingWindow, value)
        }
        // G-07: production trims and fades the reference's edges (adopted
        // 2026-11-12); only "as-given" takes it as given.
        XCTAssertFalse(internalRun.referenceEdgesTrimmed)
        XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.production.referenceEdgesTrimmed)
        for (value, expected) in [(" As-Given ", false), ("trimmed", true), ("on", true), ("", true)] {
            var edges = everyOverrideRequested
            edges["QWENVOICE_REFERENCE_EDGES"] = value
            XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: edges)
                .referenceEdgesTrimmed, expected, value)
            XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: edges)
                .referenceEdgesTrimmed, value)
        }
        // A-11: production joins a Han or kana target with no space (adopted
        // 2026-11-12); only "every-target" puts the space back. The resolver's
        // own defaults are production's.
        XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides(talkerKVQuantBits: nil, speechTokenizerResidency: nil), .production)
        XCTAssertFalse(internalRun.iclTargetSpaceOnlyBeforeSpacedScripts)
        XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.production.iclTargetSpaceOnlyBeforeSpacedScripts)
        for (value, expected) in [(" Every-Target ", false), ("spaced-scripts", true), ("on", true), ("", true)] {
            var spacing = everyOverrideRequested
            spacing["QWENVOICE_ICL_TARGET_SPACE"] = value
            XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: spacing)
                .iclTargetSpaceOnlyBeforeSpacedScripts, expected, value)
            XCTAssertTrue(Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: spacing)
                .iclTargetSpaceOnlyBeforeSpacedScripts, value)
        }
        XCTAssertFalse(Qwen3LoadTimeDiagnosticOverrides.production.encoderSplitHalfRotary)
        for (value, expected) in [(" Split-Half ", true), ("split_half", false), ("on", false), ("", false)] {
            var environment = everyOverrideRequested
            environment["QWENVOICE_ENCODER_ROTARY"] = value
            XCTAssertEqual(
                Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: environment)
                    .encoderSplitHalfRotary,
                expected, value)
        }

        var unsupported = everyOverrideRequested
        unsupported["QVOICE_TALKER_KV_QUANT"] = "3"
        unsupported["QWENVOICE_TOKENIZER_RESIDENCY"] = " ON "
        let normalized = Qwen3LoadTimeDiagnosticOverrides.resolve(
            internalDiagnosticsAvailable: true,
            environment: unsupported
        )
        XCTAssertNil(normalized.talkerKVQuantBits)
        XCTAssertEqual(normalized.speechTokenizerResidency, true)
    }

    /// A-02: the encoder's transformer rotates adjacent pairs unless the
    /// split-half convention is asked for; nothing else in it changes.
    func testTheEncoderRotaryConventionReachesItsTransformer() throws {
        let config = try JSONDecoder().decode(Qwen3TTSTokenizerEncoderConfig.self, from: Data("{}".utf8))
        let shipped = Qwen3TTSSpeechTokenizerEncoder(config: config, validNumQuantizers: 16)
        let reference = Qwen3TTSSpeechTokenizerEncoder(config: config, validNumQuantizers: 16, splitHalfRotary: true)
        XCTAssertTrue(shipped.transformerConfig.ropeTraditional)
        XCTAssertFalse(reference.transformerConfig.ropeTraditional)
        XCTAssertEqual(shipped.transformerConfig.headDim, reference.transformerConfig.headDim)
        XCTAssertEqual(shipped.transformerConfig.maxPeriod, reference.transformerConfig.maxPeriod)
        XCTAssertEqual(shipped.transformerConfig.numLayers, reference.transformerConfig.numLayers)

        // Through the tokenizer, as the loader constructs it, down to the
        // rotary module every attention layer applies.
        let tokenizerConfig = try JSONDecoder().decode(
            Qwen3TTSTokenizerConfig.self, from: Data(#"{"encoder_config": {}}"#.utf8))
        for splitHalf in [false, true] {
            let tokenizer = Qwen3TTSSpeechTokenizer(
                config: tokenizerConfig, includeEncoder: true, encoderSplitHalfRotary: splitHalf)
            let encoder = try XCTUnwrap(tokenizer.encoderModel)
            XCTAssertEqual(encoder.transformerConfig.ropeTraditional, !splitHalf)
            XCTAssertNil(tokenizer.decoder.preTransformer.attentionWindow, "the shipped decoder attends to the whole take")
            let layers = encoder.encoderTransformer.transformer.layers
            XCTAssertFalse(layers.isEmpty)
            let headDim = encoder.transformerConfig.headDim
            let input = MLXArray((0..<(4 * headDim)).map { Float($0 % 17) / 17 }, [1, 1, 4, headDim])
            for layer in layers {
                let rope = try XCTUnwrap(layer.self_attn.rope)
                let applied = rope(input, offset: 3)
                let expected = MLXFast.RoPE(
                    input, dimensions: headDim, traditional: !splitHalf,
                    base: Float(encoder.transformerConfig.maxPeriod), scale: 1, offset: 3)
                let other = MLXFast.RoPE(
                    input, dimensions: headDim, traditional: splitHalf,
                    base: Float(encoder.transformerConfig.maxPeriod), scale: 1, offset: 3)
                XCTAssertTrue(allClose(applied, expected).item(Bool.self), "split-half \(splitHalf)")
                XCTAssertFalse(allClose(applied, other).item(Bool.self), "the two conventions differ")
            }
        }
    }

    func testTheDecoderWindowIsTheConfiguredOneWhenAskedFor() throws {
        let config = try JSONDecoder().decode(
            Qwen3TTSTokenizerConfig.self, from: Data(#"{"decoder_config": {}}"#.utf8))
        XCTAssertEqual(Qwen3TTSSpeechTokenizer(config: config, includeEncoder: false, decoderSlidingWindow: true)
            .decoder.preTransformer.attentionWindow, 72)
        XCTAssertNil(Qwen3TTSSpeechTokenizer(config: config, includeEncoder: false).decoder.preTransformer.attentionWindow)
    }

    func testResidencyOverrideGovernsAdoptionOnlyWhenResolved() throws {
        XCTAssertFalse(Qwen3TTSPreparedComponentCache.speechTokenizerResidencyEnabled(override: false))
        XCTAssertTrue(Qwen3TTSPreparedComponentCache.speechTokenizerResidencyEnabled(override: true))

        let cache = Qwen3TTSPreparedComponentCache()
        let tokenizer = try makeTinyTokenizer()
        cache.storeResidentSpeechTokenizer(
            tokenizer,
            identityKey: "trust:aaa",
            includesEncoder: false,
            residencyOverride: false
        )
        XCTAssertNil(
            cache.residentSpeechTokenizer(
                identityKey: "trust:aaa",
                includeEncoder: false,
                residencyOverride: true
            ),
            "a disabled load never stores a resident"
        )

        cache.storeResidentSpeechTokenizer(
            tokenizer,
            identityKey: "trust:bbb",
            includesEncoder: false,
            residencyOverride: true
        )
        XCTAssertNil(
            cache.residentSpeechTokenizer(
                identityKey: "trust:bbb",
                includeEncoder: false,
                residencyOverride: false
            ),
            "a disabled load never adopts an existing resident"
        )
        XCTAssertNotNil(
            cache.residentSpeechTokenizer(
                identityKey: "trust:bbb",
                includeEncoder: false,
                residencyOverride: true
            ),
            "an enabled load adopts the stored resident"
        )
    }

    private func makeTinyTokenizer(includeEncoder: Bool = false) throws -> Qwen3TTSSpeechTokenizer {
        let json: [String: Any] = [
            "decoder_config": [
                "latent_dim": 16,
                "codebook_dim": 8,
                "codebook_size": 32,
                "decoder_dim": 16,
                "hidden_size": 16,
                "intermediate_size": 32,
                "head_dim": 8,
                "num_attention_heads": 2,
                "num_hidden_layers": 1,
                "num_key_value_heads": 2,
                "num_quantizers": 2,
                "num_semantic_quantizers": 1,
                "semantic_codebook_size": 16,
                "sliding_window": 8,
                "max_position_embeddings": 64,
                "upsample_rates": [2, 2],
                "upsampling_ratios": [2],
                "vector_quantization_hidden_dimension": 16,
            ],
        ]
        let config = try JSONDecoder().decode(
            Qwen3TTSTokenizerConfig.self,
            from: JSONSerialization.data(withJSONObject: json)
        )
        return Qwen3TTSSpeechTokenizer(config: config, includeEncoder: includeEncoder)
    }

    func testResidencyMatchesExactIdentityWithEncoderSupersetRule() throws {
        let cache = Qwen3TTSPreparedComponentCache()
        let decoderOnly = try makeTinyTokenizer()

        cache.storeResidentSpeechTokenizer(
            decoderOnly, identityKey: "trust:aaa", includesEncoder: false
        )
        XCTAssertNotNil(
            cache.residentSpeechTokenizer(identityKey: "trust:aaa", includeEncoder: false)
        )
        // A decoder-only resident can never serve an encoder-needing load.
        XCTAssertNil(
            cache.residentSpeechTokenizer(identityKey: "trust:aaa", includeEncoder: true)
        )
        // Content mismatch never adopts.
        XCTAssertNil(
            cache.residentSpeechTokenizer(identityKey: "trust:bbb", includeEncoder: false)
        )

        // An encoder-carrying resident serves both request shapes.
        let withEncoderMarker = try makeTinyTokenizer()
        cache.storeResidentSpeechTokenizer(
            withEncoderMarker, identityKey: "trust:aaa", includesEncoder: true
        )
        XCTAssertNotNil(
            cache.residentSpeechTokenizer(identityKey: "trust:aaa", includeEncoder: true)
        )
        XCTAssertNotNil(
            cache.residentSpeechTokenizer(identityKey: "trust:aaa", includeEncoder: false)
        )

        // Lifecycle clearing (memory relief / explicit unload) drops the slot.
        cache.clear()
        XCTAssertNil(
            cache.residentSpeechTokenizer(identityKey: "trust:aaa", includeEncoder: false)
        )
    }

    func testFileIdentityFollowsHardLinksAndFailsSafe() throws {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appendingPathComponent("st-identity-\(UUID().uuidString)", isDirectory: true)
        defer { try? fileManager.removeItem(at: root) }
        let first = root.appendingPathComponent("a/speech_tokenizer", isDirectory: true)
        let second = root.appendingPathComponent("b/speech_tokenizer", isDirectory: true)
        try fileManager.createDirectory(at: first, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: second, withIntermediateDirectories: true)

        let weights = Data(repeating: 7, count: 4096)
        let config = Data(#"{"decode_upsample_rate": 1920}"#.utf8)
        try weights.write(to: first.appendingPathComponent("model.safetensors"))
        try config.write(to: first.appendingPathComponent("config.json"))
        // Hard-link the weights (the shared-component store shape) and copy
        // the identical config.
        try fileManager.linkItem(
            at: first.appendingPathComponent("model.safetensors"),
            to: second.appendingPathComponent("model.safetensors")
        )
        try config.write(to: second.appendingPathComponent("config.json"))

        let firstIdentity = try XCTUnwrap(
            Qwen3TTSModel.speechTokenizerComponentIdentity(at: first, includeEncoder: false)
        )
        let secondIdentity = try XCTUnwrap(
            Qwen3TTSModel.speechTokenizerComponentIdentity(at: second, includeEncoder: false)
        )
        XCTAssertEqual(firstIdentity, secondIdentity, "hard-linked components share identity")

        // A config change breaks identity even with shared weights.
        try Data(#"{"decode_upsample_rate": 1919}"#.utf8)
            .write(to: second.appendingPathComponent("config.json"))
        XCTAssertNotEqual(
            firstIdentity,
            Qwen3TTSModel.speechTokenizerComponentIdentity(at: second, includeEncoder: false)
        )

        // Independent copies (distinct inodes) never share identity.
        let third = root.appendingPathComponent("c/speech_tokenizer", isDirectory: true)
        try fileManager.createDirectory(at: third, withIntermediateDirectories: true)
        try weights.write(to: third.appendingPathComponent("model.safetensors"))
        try config.write(to: third.appendingPathComponent("config.json"))
        XCTAssertNotEqual(
            firstIdentity,
            Qwen3TTSModel.speechTokenizerComponentIdentity(at: third, includeEncoder: false)
        )

        // Missing files fail safe.
        XCTAssertNil(
            Qwen3TTSModel.speechTokenizerComponentIdentity(
                at: root.appendingPathComponent("missing"), includeEncoder: false
            )
        )
    }

    /// RF-68 (B1.2): per-layer quantization configs must decode cleanly even
    /// without `"model_type"` (and from `"quantization_config"`), while any
    /// malformed per-layer override, unknown field, or boolean `true` throws
    /// `DecodingError` instead of silently falling back to uniform 4-bit.
    func testPerLayerQuantizationDecodesWithoutModelTypeAndFailsClosedOnMalformedEntries() throws {
        // Valid config without "model_type" preserves per-layer overrides and false skips.
        let validWithoutModelType = #"""
        {
          "tts_model_type": "base",
          "quantization": {
            "group_size": 64,
            "bits": 4,
            "mode": "affine",
            "model.text_embedding": {"group_size": 64, "bits": 8, "mode": "affine"},
            "model.layers.0.self_attn.q_proj": {"group_size": 64, "bits": 8, "mode": "affine"},
            "model.layers.0.self_attn.q_norm": false
          }
        }
        """#
        let decoded = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(validWithoutModelType.utf8))
        XCTAssertEqual(decoded.quantization?.bits, 4)
        XCTAssertEqual(decoded.quantization?.groupSize, 64)
        XCTAssertEqual(decoded.perLayerQuantization?.quantization(layer: "model.text_embedding")?.bits, 8)
        XCTAssertEqual(decoded.perLayerQuantization?.quantization(layer: "model.layers.0.self_attn.q_proj")?.bits, 8)
        XCTAssertEqual(decoded.perLayerQuantization?.quantization(layer: "model.layers.0.mlp.gate_proj")?.bits, 4)
        XCTAssertNil(decoded.perLayerQuantization?.quantization(layer: "model.layers.0.self_attn.q_norm"))

        // Valid config using "quantization_config" key instead of "quantization".
        let validAltKey = #"""
        {
          "tts_model_type": "base",
          "quantization_config": {
            "group_size": 64,
            "bits": 4,
            "model.text_embedding": {"group_size": 64, "bits": 8}
          }
        }
        """#
        let decodedAlt = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(validAltKey.utf8))
        XCTAssertEqual(decodedAlt.perLayerQuantization?.quantization(layer: "model.text_embedding")?.bits, 8)

        // Dual-key HF/MLX config: valid primary `quantization` short-circuits so extra HF
        // keys in `quantization_config` (like `modules_to_not_convert`) do not spuriously fail.
        let validDualKey = #"""
        {
          "quantization": {
            "group_size": 64,
            "bits": 4,
            "model.layers.0.self_attn.q_proj": {"group_size": 64, "bits": 8}
          },
          "quantization_config": {
            "group_size": 64,
            "bits": 4,
            "modules_to_not_convert": ["lm_head"]
          }
        }
        """#
        let decodedDual = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(validDualKey.utf8))
        XCTAssertEqual(decodedDual.perLayerQuantization?.quantization(layer: "model.layers.0.self_attn.q_proj")?.bits, 8)

        // Malformed per-layer entries must throw DecodingError rather than silently dropping overrides.
        let malformedConfigs: [(label: String, json: String)] = [
            (
                "boolean true override",
                #"{"model_type": "qwen3_tts", "quantization": {"group_size": 64, "bits": 4, "model.layers.0.self_attn.q_proj": true}}"#
            ),
            (
                "missing group_size in per-layer entry",
                #"{"model_type": "qwen3_tts", "quantization": {"group_size": 64, "bits": 4, "model.layers.0.self_attn.q_proj": {"bits": 8}}}"#
            ),
            (
                "wrong value type for per-layer entry",
                #"{"model_type": "qwen3_tts", "quantization": {"group_size": 64, "bits": 4, "model.layers.0.self_attn.q_proj": "8bit"}}"#
            ),
            (
                "unexpected metadata key inside quantization",
                #"{"model_type": "qwen3_tts", "quantization": {"group_size": 64, "bits": 4, "unexpected_metadata": 123}}"#
            ),
        ]
        for (label, json) in malformedConfigs {
            XCTAssertThrowsError(
                try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(json.utf8)),
                "\(label) must fail closed instead of silently dropping per-layer quantization"
            ) { error in
                XCTAssertTrue(error is DecodingError, "\(label) threw non-DecodingError: \(error)")
            }
        }
    }

    /// RF-68 (B1.2): prepared-checkpoint verification must enforce shape checks
    /// alongside unused-key checks so a mismatched tensor fails closed at load time.
    func testPreparedCheckpointVerifyModeRejectsShapeMismatch() throws {
        let mode = Qwen3TTSModel.preparedCheckpointVerifyMode(trustPreparedCheckpoint: true)
        XCTAssertTrue(mode.contains(.noUnusedKeys))
        XCTAssertTrue(mode.contains(.shapeMismatch))

        let layer = Linear(4, 4, bias: false)
        let wrongShape = ModuleParameters.unflattened([
            ("weight", MLXArray.zeros([3, 4], type: Float.self)),
        ])
        XCTAssertThrowsError(
            try layer.update(parameters: wrongShape, verify: mode),
            "trusted prepared-checkpoint verify mode must reject mismatched tensor shapes"
        )
    }

    /// A-08 (RF-68): `Qwen3TTSSpeechTokenizerEncoder` must not retain a
    /// persistent transformer KV cache across calls, and repeated encodes of
    /// varying lengths past the 256-frame `KVCacheSimple` step must produce
    /// identical codes without cross-call contamination.
    func testSpeechTokenizerEncoderRetainsNoPersistentKVCacheAcrossVaryingLengths() throws {
        let encoderJSON = #"""
        {
          "frame_rate": 25.0,
          "audio_channels": 1,
          "codebook_dim": 16,
          "codebook_size": 32,
          "compress": 2,
          "dilation_growth_rate": 2,
          "head_dim": 16,
          "hidden_size": 32,
          "intermediate_size": 64,
          "kernel_size": 3,
          "last_kernel_size": 3,
          "layer_scale_initial_scale": 0.01,
          "max_position_embeddings": 1024,
          "num_attention_heads": 2,
          "num_hidden_layers": 2,
          "num_key_value_heads": 2,
          "num_filters": 8,
          "num_quantizers": 4,
          "num_residual_layers": 1,
          "num_semantic_quantizers": 1,
          "residual_kernel_size": 3,
          "sampling_rate": 200,
          "sliding_window": 250,
          "upsampling_ratios": [2, 2],
          "use_causal_conv": true,
          "use_conv_shortcut": false,
          "vector_quantization_hidden_dimension": 16
        }
        """#
        let config = try JSONDecoder().decode(
            Qwen3TTSTokenizerEncoderConfig.self,
            from: Data(encoderJSON.utf8)
        )
        let encoder = Qwen3TTSSpeechTokenizerEncoder(config: config, validNumQuantizers: 4)
        eval(encoder.parameters())

        XCTAssertFalse(
            Mirror(reflecting: encoder).children.contains { $0.label == "encoderCache" },
            "encoder must allocate transformer KV cache locally per encode instead of retaining encoderCache"
        )

        func wave(_ count: Int) -> MLXArray {
            let samples = (0 ..< count).map { index in
                0.25 * sin(Float(index) * 0.07)
            }
            return MLXArray(samples).reshaped([1, 1, count])
        }

        let shortAudio = wave(64)
        let firstShort = encoder.encode(shortAudio)
        eval(firstShort)
        let firstShortCodes = firstShort.asArray(Int32.self)
        XCTAssertFalse(firstShortCodes.isEmpty)

        // Encode clips exceeding KVCacheSimple's 256-frame allocation step.
        autoreleasepool {
            let medium = encoder.encode(wave(1_200))
            eval(medium)
            let long = encoder.encode(wave(2_200))
            eval(long)
        }
        Memory.clearCache()

        let repeatedShort = encoder.encode(shortAudio)
        eval(repeatedShort)
        XCTAssertEqual(
            repeatedShort.asArray(Int32.self),
            firstShortCodes,
            "repeated encode after longer clips must produce identical codes"
        )
    }

    /// RF-68 (B1.6): `codePredictorSiblingDirectory` strips `-hybrid-*` in
    /// addition to `-<ownBits>bit`, `codePredictorSibling` rejects non-uniform
    /// siblings with divergent per-layer overrides, and
    /// `validateMixedPrecisionTarget` fails closed on already-hybrid checkpoints.
    func testHybridSiblingLookupStripsHybridSuffixRejectsNonUniformSiblingAndBlocksMixedPrecision() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("hybrid-sibling-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let hybridAttn = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-hybrid-attn", isDirectory: true)
        let hybridAttnIO = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-hybrid-attn-io", isDirectory: true)
        let sibling8Bit = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-8bit", isDirectory: true)
        let uniform4Bit = root.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-4bit", isDirectory: true)

        XCTAssertEqual(
            try Qwen3TTSModel.codePredictorSiblingDirectory(of: hybridAttn, ownBits: 4, bits: 8).lastPathComponent,
            sibling8Bit.lastPathComponent
        )
        XCTAssertEqual(
            try Qwen3TTSModel.codePredictorSiblingDirectory(of: hybridAttnIO, ownBits: 4, bits: 8).lastPathComponent,
            sibling8Bit.lastPathComponent
        )
        for invalid in ["-hybrid-attn", "Qwen3-TTS-hybrid-", "-4bit", "unnamed"] {
            XCTAssertThrowsError(
                try Qwen3TTSModel.codePredictorSiblingDirectory(
                    of: root.appendingPathComponent(invalid, isDirectory: true),
                    ownBits: 4,
                    bits: 8
                ),
                "\(invalid) must be refused"
            )
        }

        func writeSiblingConfig(_ json: String) throws {
            try FileManager.default.createDirectory(at: sibling8Bit, withIntermediateDirectories: true)
            try Data(json.utf8).write(to: sibling8Bit.appendingPathComponent("config.json"))
            try Data("{}".utf8).write(to: sibling8Bit.appendingPathComponent(".qwenvoice-model-integrity.json"))
        }

        let ownHybridConfig = try JSONDecoder().decode(
            Qwen3TTSModelConfig.self,
            from: Data(#"""
            {
              "tts_model_type": "base",
              "quantization": {
                "group_size": 64,
                "bits": 4,
                "mode": "affine",
                "model.text_embedding": {"group_size": 64, "bits": 8, "mode": "affine"},
                "model.layers.0.self_attn.q_proj": {"group_size": 64, "bits": 8, "mode": "affine"}
              }
            }
            """#.utf8)
        )

        // Uniform 8-bit sibling (bare) resolves beside -hybrid-attn.
        try writeSiblingConfig(#"{"tts_model_type": "base", "quantization": {"group_size": 64, "bits": 8, "mode": "affine"}}"#)
        let resolvedBare = try Qwen3TTSModel.codePredictorSibling(
            of: hybridAttn, config: ownHybridConfig, ownBits: 4, bits: 8
        )
        XCTAssertEqual(resolvedBare.directory.lastPathComponent, sibling8Bit.lastPathComponent)
        XCTAssertEqual(resolvedBare.quantization.bits, 8)

        // Uniform 8-bit sibling with identical-recipe `model.text_embedding` also resolves.
        try writeSiblingConfig(#"""
        {
          "tts_model_type": "base",
          "quantization": {
            "group_size": 64,
            "bits": 8,
            "mode": "affine",
            "model.text_embedding": {"group_size": 64, "bits": 8, "mode": "affine"}
          }
        }
        """#)
        XCTAssertEqual(
            try Qwen3TTSModel.codePredictorSibling(
                of: hybridAttn, config: ownHybridConfig, ownBits: 4, bits: 8
            ).quantization.bits,
            8
        )

        // Non-uniform sibling with per-layer overrides must be rejected.
        let nonUniformSiblings = [
            #"{"tts_model_type": "base", "quantization": {"group_size": 64, "bits": 8, "model.layers.0.self_attn.q_proj": {"group_size": 64, "bits": 4}}}"#,
            #"{"tts_model_type": "base", "quantization": {"group_size": 64, "bits": 8, "code_predictor.lm_head.0": {"group_size": 64, "bits": 4}}}"#,
            #"{"tts_model_type": "base", "quantization": {"group_size": 64, "bits": 8, "model.layers.0.self_attn.q_proj": false}}"#,
            #"{"tts_model_type": "base", "quantization": {"group_size": 64, "bits": 8, "model.text_embedding": {"group_size": 64, "bits": 4}}}"#,
        ]
        for json in nonUniformSiblings {
            try writeSiblingConfig(json)
            XCTAssertThrowsError(
                try Qwen3TTSModel.codePredictorSibling(
                    of: hybridAttn, config: ownHybridConfig, ownBits: 4, bits: 8
                ),
                "sibling with per-layer override must fail closed: \(json)"
            )
        }

        // QWENVOICE_MIXED_PRECISION fails closed on already-hybrid checkpoints (by name or config),
        // while staying allowed on uniform 4-bit checkpoints (including Stage 2.2 8-bit text_embedding).
        let uniform4BitConfig = try JSONDecoder().decode(
            Qwen3TTSModelConfig.self,
            from: Data(#"""
            {
              "tts_model_type": "base",
              "quantization": {
                "group_size": 64,
                "bits": 4,
                "mode": "affine",
                "model.text_embedding": {"group_size": 64, "bits": 8, "mode": "affine"}
              }
            }
            """#.utf8)
        )
        XCTAssertFalse(Qwen3TTSModel.isHybridCheckpoint(modelDir: uniform4Bit, config: uniform4BitConfig))
        XCTAssertNoThrow(
            try Qwen3TTSModel.validateMixedPrecisionTarget(
                modelDir: uniform4Bit, config: uniform4BitConfig, mixedRecipe: .attn
            )
        )
        XCTAssertTrue(Qwen3TTSModel.isHybridCheckpoint(modelDir: hybridAttn, config: uniform4BitConfig))
        XCTAssertTrue(Qwen3TTSModel.isHybridCheckpoint(modelDir: uniform4Bit, config: ownHybridConfig))
        XCTAssertNoThrow(
            try Qwen3TTSModel.validateMixedPrecisionTarget(
                modelDir: hybridAttn, config: ownHybridConfig, mixedRecipe: nil
            ),
            "nil mixedRecipe (e.g. code-predictor-only sibling lookup) remains allowed on hybrid checkpoints"
        )
        XCTAssertThrowsError(
            try Qwen3TTSModel.validateMixedPrecisionTarget(
                modelDir: hybridAttn, config: uniform4BitConfig, mixedRecipe: .attn
            ),
            "QWENVOICE_MIXED_PRECISION must fail closed on a -hybrid-* directory"
        )
        XCTAssertThrowsError(
            try Qwen3TTSModel.validateMixedPrecisionTarget(
                modelDir: uniform4Bit, config: ownHybridConfig, mixedRecipe: .down
            ),
            "QWENVOICE_MIXED_PRECISION must fail closed when config already has talker per-layer overrides"
        )
    }
}
