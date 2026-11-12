// Loading a Qwen3-TTS model: prepared directories, weights, the talker, the speech
// tokenizer and the text tokenizer. Moved out of Qwen3TTS.swift unchanged (RF-46).

import CryptoKit
import Foundation
import Hub
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
import MLXNN
import os
import Tokenizers

private struct LoadedTalkerComponents: @unchecked Sendable {
    let talker: Qwen3TTSTalkerForConditionalGeneration
    let speakerEncoder: Qwen3TTSSpeakerEncoder?
    let talkerWeightLoadMS: Int
    let timingsMS: [String: Int]
    let booleanFlags: [String: Bool]
}

private struct LoadedTokenizerComponent: Sendable {
    let tokenizer: (any Tokenizer)?
    let cacheHit: Bool
    let directConfigLoadUsed: Bool
    let directConfigFallbackUsed: Bool
    let loadMS: Int
}

private struct LoadedSpeechTokenizerComponent: @unchecked Sendable {
    let speechTokenizer: Qwen3TTSSpeechTokenizer?
    let loadMS: Int
    let booleanFlags: [String: Bool]
}

private struct QwenPreparedLoadOptions: Sendable {
    var speechTokenizerContentIdentity: String? = nil
    let trustPreparedCheckpoint: Bool
    let preparedDirectoryAlreadyValidated: Bool
    let loadSpeakerEncoder: Bool?
    let loadSpeechTokenizerEncoder: Bool?
    let skipSpeechTokenizerEval: Bool
    var diagnosticOverrides: Qwen3LoadTimeDiagnosticOverrides = .production
}

private let talkerEvalLayerBatchSize = 4
private let speechTokenizerEvalBatchSize = 8

extension Qwen3TTSModel {
    /// The resident speech tokenizer's reuse key. An encoder built with the
    /// other rotary convention (RF-52) or a decoder built with the attention
    /// window (RF-54) is another object, so it is never handed to a load that
    /// asked for the other one; without either key the content identity is
    /// the key, as it was before them.
    static func speechTokenizerResidencyIdentity(
        contentIdentity: String,
        includeEncoder: Bool,
        overrides: Qwen3LoadTimeDiagnosticOverrides
    ) -> String {
        var key = contentIdentity
        if includeEncoder && overrides.encoderSplitHalfRotary {
            key += "|encoder-rope-split-half"
        }
        if overrides.decoderSlidingWindow {
            key += "|decoder-sliding-window"
        }
        return key
    }
}

extension Qwen3TTSModel {
    // MARK: - fromPretrained

    public static func preparePreparedDirectory(_ modelDir: URL) throws {
        try ensureTokenizerJSON(in: modelDir)
    }

    public static func fromPretrained(
        _ modelRepo: String,
        cache: HubCache = .default,
        revision: String = "main",
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSModel {
        let repoID = Repo.ID(rawValue: modelRepo)!
        let modelDir = try await ModelUtils.resolveOrDownloadModel(
            repoID: repoID,
            requiredExtension: "safetensors",
            revision: revision,
            cache: cache
        )
        return try await fromPreparedDirectory(
            modelDir,
            modelRepo: modelRepo,
            isolation: isolation
        )
    }

    public static func fromPreparedDirectory(
        _ modelDir: URL,
        modelRepo _: String,
        loadBehavior: QwenPreparedLoadBehavior = .fullCapabilities,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)? = nil,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSModel {
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-prepare-prepared-directory",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: QwenPreparedLoadOptions(
                    trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                    preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                    loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                    loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                    skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval
                )
            )
        )
        if !loadBehavior.preparedDirectoryAlreadyValidated {
            try preparePreparedDirectory(modelDir)
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-prepare-prepared-directory",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: QwenPreparedLoadOptions(
                    trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                    preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                    loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                    loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                    skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval
                )
            )
        )
        return try await loadModelContents(
            modelDir: modelDir,
            loadOptions: QwenPreparedLoadOptions(
                speechTokenizerContentIdentity: loadBehavior.speechTokenizerContentIdentity,
                trustPreparedCheckpoint: loadBehavior.trustPreparedCheckpoint,
                preparedDirectoryAlreadyValidated: loadBehavior.preparedDirectoryAlreadyValidated,
                loadSpeakerEncoder: loadBehavior.loadSpeakerEncoder,
                loadSpeechTokenizerEncoder: loadBehavior.loadSpeechTokenizerEncoder,
                skipSpeechTokenizerEval: loadBehavior.skipSpeechTokenizerEval,
                diagnosticOverrides: .resolve(
                    internalDiagnosticsAvailable: loadBehavior.internalDiagnosticsAvailable
                )
            ),
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
    }

    private static func loadModelContents(
        modelDir: URL,
        loadOptions: QwenPreparedLoadOptions,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> Qwen3TTSModel {
        _ = isolation
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-config-read",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions
            )
        )
        let configData = try Data(contentsOf: modelDir.appendingPathComponent("config.json"))
        let config = try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: configData)
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-config-read",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "speakerCount": "\(config.talkerConfig?.spkId?.count ?? 0)",
                ]
            )
        )
        let preparedKey = preparedDirectoryKey(for: modelDir)

        let componentCache = Qwen3TTSPreparedComponentCache.shared
        async let tokenizerComponent = loadTokenizerComponent(
            modelDir: modelDir,
            preparedKey: preparedKey,
            componentCache: componentCache
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-talker",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let talkerComponents = try await loadTalkerComponents(
            modelDir: modelDir,
            config: config,
            loadOptions: loadOptions,
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-talker",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "speakerEncoderLoaded": talkerComponents.speakerEncoder == nil ? "false" : "true",
                ]
            )
        )

        let model = Qwen3TTSModel(
            config: config,
            talker: talkerComponents.talker,
            speakerEncoder: talkerComponents.speakerEncoder,
            talkerKVQuantBits: loadOptions.diagnosticOverrides.talkerKVQuantBits,
            referenceTrailingSilenceSamples: loadOptions.diagnosticOverrides.referenceTrailingSilenceSamples,
            streamedCloneDecoderPriming: loadOptions.diagnosticOverrides.cloneDecoderPriming,
            iclTargetSpaceOnlyBeforeSpacedScripts: loadOptions.diagnosticOverrides.iclTargetSpaceOnlyBeforeSpacedScripts,
            referenceEdgesTrimmed: loadOptions.diagnosticOverrides.referenceEdgesTrimmed
        )
        model.preparedKey = preparedKey

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-tokenizer-await",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let tokenizerResult = await tokenizerComponent
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-tokenizer-await",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "tokenizerCacheHit": tokenizerResult.cacheHit ? "true" : "false",
                    "tokenizerDirectConfigLoadUsed": tokenizerResult.directConfigLoadUsed ? "true" : "false",
                    "tokenizerDirectConfigFallbackUsed": tokenizerResult.directConfigFallbackUsed ? "true" : "false",
                    "tokenizerLoaded": tokenizerResult.tokenizer == nil ? "false" : "true",
                ]
            )
        )
        model.tokenizer = tokenizerResult.tokenizer
        Memory.clearCache()

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-before-speech-tokenizer",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                ]
            )
        )
        let speechTokenizerResult = try await loadSpeechTokenizerComponent(
            modelDir: modelDir,
            preparedKey: preparedKey,
            loadOptions: loadOptions,
            includeEncoder: loadOptions.loadSpeechTokenizerEncoder ?? (config.ttsModelType == "base"),
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-load-after-speech-tokenizer",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "preparedKey": preparedKey,
                    "speechTokenizerCacheHit": "false",
                    "speechTokenizerModelLocal": "true",
                    "speechTokenizerDecoderLoaded": speechTokenizerResult.speechTokenizer == nil ? "false" : "true",
                    "speechTokenizerEncoderLoaded": (speechTokenizerResult.booleanFlags[
                        "speech_tokenizer_encoder_loaded"
                    ] ?? false) ? "true" : "false",
                ]
            )
        )
        model.speechTokenizer = speechTokenizerResult.speechTokenizer
        model.speechTokenizer?.decoder.resetStreamingState()

        var loadTimingsMS = talkerComponents.timingsMS
        loadTimingsMS["talker_weight_load"] = talkerComponents.talkerWeightLoadMS
        loadTimingsMS["tokenizer_load"] = tokenizerResult.loadMS
        loadTimingsMS["speech_tokenizer_load"] = speechTokenizerResult.loadMS
        model.storeLoadTimingsMS(loadTimingsMS)

        var loadBooleanFlags = talkerComponents.booleanFlags
        loadBooleanFlags["trusted_prepared_checkpoint"] = loadOptions.trustPreparedCheckpoint
        loadBooleanFlags["prepared_directory_already_validated"] = loadOptions.preparedDirectoryAlreadyValidated
        loadBooleanFlags["tokenizer_cache_hit"] = tokenizerResult.cacheHit
        loadBooleanFlags["tokenizer_direct_config_load"] = tokenizerResult.directConfigLoadUsed
        loadBooleanFlags["tokenizer_direct_config_fallback"] = tokenizerResult.directConfigFallbackUsed
        // Retain the old key as an explicit false compatibility projection.
        // Mutable decoder state is never shared between loaded model instances.
        loadBooleanFlags["speech_tokenizer_cache_hit"] = false
        loadBooleanFlags["speech_tokenizer_model_local"] = true
        loadBooleanFlags["speech_tokenizer_encoder_loaded"] = speechTokenizerResult.booleanFlags[
            "speech_tokenizer_encoder_loaded"
        ] ?? false
        loadBooleanFlags["speech_tokenizer_eval_skipped"] = loadOptions.skipSpeechTokenizerEval
        loadBooleanFlags["custom_instruction_control_supported"] = model.supportsCustomInstructionControl
        for (key, value) in speechTokenizerResult.booleanFlags {
            loadBooleanFlags[key] = value
        }
        model.storeLoadBooleanFlags(loadBooleanFlags)
        qwen3TTSLog("Loaded Qwen3-TTS model (\(config.ttsModelType))")
        return model
    }

    private static func loadTalkerComponents(
        modelDir: URL,
        config: Qwen3TTSModelConfig,
        loadOptions: QwenPreparedLoadOptions,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> LoadedTalkerComponents {
        _ = isolation
        let talkerConfig = config.talkerConfig ?? {
            let json = "{}".data(using: .utf8)!
            return try! JSONDecoder().decode(Qwen3TTSTalkerConfig.self, from: json)
        }()
        let shouldLoadSpeakerEncoder = loadOptions.loadSpeakerEncoder ?? (config.ttsModelType == "base")
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-weight-load",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "speakerCount": "\(talkerConfig.spkId?.count ?? 0)",
                    "speakerEncoderRequested": shouldLoadSpeakerEncoder ? "true" : "false",
                ]
            )
        )
        // RF-47: read the text embedding's rows from the checkpoint file when
        // it holds them in a known layout, instead of loading the table.
        let textEmbeddingRows = try openTextEmbeddingRows(
            in: modelDir, config: config, talkerConfig: talkerConfig
        )
        let talker = Qwen3TTSTalkerForConditionalGeneration(
            config: talkerConfig, textEmbeddingRows: textEmbeddingRows
        )
        let speakerEncoder = shouldLoadSpeakerEncoder
            ? Qwen3TTSSpeakerEncoder(config: config.speakerEncoderConfig)
            : nil

        let talkerWeightLoadStartedAt = ContinuousClock.now
        var talkerWeights = [String: MLXArray]()
        var talkerTimingsMS: [String: Int] = [:]

        let talkerIOStartedAt = ContinuousClock.now
        var talkerSourceWeights = try loadWeights(
            from: modelDir,
            directSafetensorsFileName: "model.safetensors"
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-weight-load",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "sourceWeightCount": "\(talkerSourceWeights.count)",
                ]
            )
        )
        talkerTimingsMS["talker_safetensors_io"] = talkerIOStartedAt.elapsedMilliseconds

        let talkerSanitizeStartedAt = ContinuousClock.now
        for (key, value) in talkerSourceWeights where key.hasPrefix("talker.") {
            let sanitizedKey = String(key.dropFirst("talker.".count))
            talkerWeights[sanitizedKey] = value
        }

        if talkerWeights.isEmpty {
            talkerWeights = Qwen3TTSTalkerForConditionalGeneration.sanitize(
                weights: talkerSourceWeights
            )
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-sanitize",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerWeightCount": "\(talkerWeights.count)",
                    "speakerWeightCount": shouldLoadSpeakerEncoder ? "\(talkerSourceWeights.count)" : "0",
                ]
            )
        )
        talkerTimingsMS["talker_weight_sanitize"] = talkerSanitizeStartedAt.elapsedMilliseconds
        if textEmbeddingRows != nil {
            // The model has no text-embedding parameter then, and these lazy
            // arrays are dropped without ever being read from the file.
            for suffix in ["weight", "scales", "biases"] {
                talkerWeights.removeValue(forKey: "\(Self.textEmbeddingModuleKey).\(suffix)")
            }
        }
        // RF-55 (diagnostic): the code predictor from the installed sibling of
        // this model at another precision, quantized as that sibling is.
        var codePredictorQuantization: (Int, Int, QuantizationMode)?
        var usedCodePredictorSibling = false
        if let bits = loadOptions.diagnosticOverrides.codePredictorBits,
           let ownBits = config.quantization?.bits, ownBits != bits {
            let sibling = try Self.codePredictorSibling(of: modelDir, config: config, ownBits: ownBits, bits: bits)
            let siblingWeights = try loadWeights(from: sibling.directory, directSafetensorsFileName: "model.safetensors")
            let prefix = "\(Self.codePredictorModuleKey)."
            let ownKeys = Set(talkerWeights.keys.filter { $0.hasPrefix(prefix) })
            let siblingKeys = Set(siblingWeights.keys.compactMap { key -> String? in
                key.hasPrefix("talker.\(prefix)") ? String(key.dropFirst("talker.".count)) : nil
            })
            // Every own code-predictor tensor is replaced, none is added: a
            // sibling converted another way would otherwise mix scales.
            guard !ownKeys.isEmpty, ownKeys == siblingKeys else {
                throw AudioGenerationError.modelNotInitialized("The \(bits)-bit sibling's code predictor differs in layout")
            }
            for key in ownKeys { talkerWeights.removeValue(forKey: key) }
            for key in siblingKeys { talkerWeights[key] = siblingWeights["talker.\(key)"] }
            codePredictorQuantization = sibling.quantization.asTuple
            usedCodePredictorSibling = true
        }
        var talkerPairs = talkerWeights.map { ($0.key, $0.value) }

        let talkerQuantizeStartedAt = ContinuousClock.now
        if config.quantization != nil || config.perLayerQuantization != nil {
            quantize(model: talker) { path, _ in
                Self.talkerQuantization(
                    path: path,
                    hasScales: talkerWeights["\(path).scales"] != nil,
                    config: config,
                    codePredictor: codePredictorQuantization
                )
            }
        }
        talkerTimingsMS["talker_quantize_prepare"] = talkerQuantizeStartedAt.elapsedMilliseconds

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-update",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerPairCount": "\(talkerPairs.count)",
                    "verifyMode": loadOptions.trustPreparedCheckpoint ? "no_unused_keys" : "all",
                ]
            )
        )
        let talkerVerifyMode: Module.VerifyUpdate = loadOptions.trustPreparedCheckpoint && !usedCodePredictorSibling
            ? .noUnusedKeys
            : .all

        let talkerUpdateStartedAt = ContinuousClock.now
        try talker.update(
            parameters: ModuleParameters.unflattened(talkerPairs),
            verify: talkerVerifyMode
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-update",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                    "talkerPairCount": "\(talkerPairs.count)",
                ]
            )
        )
        talkerTimingsMS["talker_parameter_update"] = talkerUpdateStartedAt.elapsedMilliseconds
        talkerPairs.removeAll(keepingCapacity: false)
        talkerWeights.removeAll(keepingCapacity: false)
        Memory.clearCache()

        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-before-eval",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                ]
            )
        )
        let talkerEvalStartedAt = ContinuousClock.now
        talkerTimingsMS.merge(
            evaluateTalkerParametersInBatches(talker),
            uniquingKeysWith: { _, rhs in rhs }
        )
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-talker-after-eval",
            details: diagnosticDetails(
                modelDir: modelDir,
                loadOptions: loadOptions,
                extra: [
                    "ttsModelType": config.ttsModelType,
                ]
            )
        )
        talkerTimingsMS["talker_parameter_eval"] = talkerEvalStartedAt.elapsedMilliseconds

        let talkerBooleanFlags: [String: Bool] = [
            "talker_verify_relaxed": loadOptions.trustPreparedCheckpoint && !usedCodePredictorSibling,
            // RF-55: the code predictor came from the installed 8-bit sibling.
            "talker_code_predictor_from_sibling": usedCodePredictorSibling,
            "talker_eval_chunked": true,
            "talker_text_embedding_from_file": textEmbeddingRows != nil,
            "speaker_encoder_requested": shouldLoadSpeakerEncoder,
        ]

        if let speakerEncoder, shouldLoadSpeakerEncoder {
            var speakerWeights = try speakerEncoderWeightsForLoading(talkerSourceWeights)
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
            var speakerPairs = speakerWeights.map { ($0.key, $0.value) }
            let speakerUpdateStartedAt = ContinuousClock.now
            try speakerEncoder.update(
                parameters: ModuleParameters.unflattened(speakerPairs),
                verify: .all
            )
            talkerTimingsMS["speaker_encoder_update"] = speakerUpdateStartedAt.elapsedMilliseconds
            speakerPairs.removeAll(keepingCapacity: false)
            speakerWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()

            let speakerEvalStartedAt = ContinuousClock.now
            eval(speakerEncoder.parameters())
            talkerTimingsMS["speaker_encoder_eval"] = speakerEvalStartedAt.elapsedMilliseconds
            qwen3TTSLog("Loaded speaker encoder")
            Memory.clearCache()
        } else if shouldLoadSpeakerEncoder {
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
            throw AudioGenerationError.invalidInput(
                "Requested learned component 'speaker_encoder' has no configuration."
            )
        } else {
            talkerSourceWeights.removeAll(keepingCapacity: false)
            Memory.clearCache()
        }

        // RF-46: one product for the projections that share an input. It runs
        // here, once every branch above has released `talkerSourceWeights`:
        // that dictionary holds the layers' original arrays, and while it
        // lives re-pointing a layer at its rows of the fused arrays frees
        // nothing. From here the layers hold the only reference, so each
        // layer's originals are released as it is fused and the transient is
        // one layer's projections.
        let talkerFuseStartedAt = ContinuousClock.now
        talker.fuseProjections()
        Memory.clearCache()
        talkerTimingsMS["talker_projection_fuse"] = talkerFuseStartedAt.elapsedMilliseconds

        return LoadedTalkerComponents(
            talker: talker,
            speakerEncoder: speakerEncoder,
            talkerWeightLoadMS: talkerWeightLoadStartedAt.elapsedMilliseconds,
            timingsMS: talkerTimingsMS,
            booleanFlags: talkerBooleanFlags
        )
    }

    private static func emitPreparedLoadDiagnostic(
        _ diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        action: String,
        details: [String: String]
    ) async {
        guard let diagnosticEventSink else {
            return
        }
        await diagnosticEventSink(action, details)
    }

    private static func diagnosticDetails(
        modelDir: URL,
        loadOptions: QwenPreparedLoadOptions,
        extra: [String: String] = [:]
    ) -> [String: String] {
        var details: [String: String] = [
            "modelDirectory": modelDir.path,
            "trustPreparedCheckpoint": loadOptions.trustPreparedCheckpoint ? "true" : "false",
            "preparedDirectoryAlreadyValidated": loadOptions.preparedDirectoryAlreadyValidated ? "true" : "false",
            "loadSpeakerEncoder": loadOptions.loadSpeakerEncoder.map { $0 ? "true" : "false" } ?? "auto",
            "loadSpeechTokenizerEncoder": loadOptions.loadSpeechTokenizerEncoder.map { $0 ? "true" : "false" } ?? "auto",
            "skipSpeechTokenizerEval": loadOptions.skipSpeechTokenizerEval ? "true" : "false",
        ]
        for (key, value) in extra {
            details[key] = value
        }
        return details
    }

    private static func evaluateTalkerParametersInBatches(
        _ talker: Qwen3TTSTalkerForConditionalGeneration
    ) -> [String: Int] {
        var timingsMS: [String: Int] = [:]

        let talkerCoreStartedAt = ContinuousClock.now
        var talkerCoreArrays: [MLXArray] = []
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.model.codecEmbedding.parameters())
        )
        if let textEmbedding = talker.model.textEmbedding {
            talkerCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: textEmbedding.parameters())
            )
        }
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.model.norm.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.textProjection.parameters())
        )
        talkerCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.codecHead.parameters())
        )
        evalIfNeeded(talkerCoreArrays)
        timingsMS["talker_core_eval"] = talkerCoreStartedAt.elapsedMilliseconds

        let talkerLayerStartedAt = ContinuousClock.now
        evalLayerBatches(talker.model.layers, batchSize: talkerEvalLayerBatchSize)
        timingsMS["talker_decoder_layers_eval"] = talkerLayerStartedAt.elapsedMilliseconds

        let codePredictorCoreStartedAt = ContinuousClock.now
        var codePredictorCoreArrays: [MLXArray] = []
        if let projection = talker.codePredictor.projection {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: projection.parameters())
            )
        }
        for embedding in talker.codePredictor.codecEmbedding {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: embedding.parameters())
            )
        }
        codePredictorCoreArrays.append(
            contentsOf: flattenedParameterArrays(from: talker.codePredictor.model.norm.parameters())
        )
        for lmHead in talker.codePredictor.lmHead {
            codePredictorCoreArrays.append(
                contentsOf: flattenedParameterArrays(from: lmHead.parameters())
            )
        }
        evalIfNeeded(codePredictorCoreArrays)
        timingsMS["talker_code_predictor_core_eval"] = codePredictorCoreStartedAt.elapsedMilliseconds

        let codePredictorLayerStartedAt = ContinuousClock.now
        evalLayerBatches(talker.codePredictor.model.layers, batchSize: talkerEvalLayerBatchSize)
        timingsMS["talker_code_predictor_layers_eval"] = codePredictorLayerStartedAt.elapsedMilliseconds

        return timingsMS
    }

    private static func evalLayerBatches<Layer: Module>(
        _ layers: [Layer],
        batchSize: Int
    ) {
        guard batchSize > 0 else { return }

        for startIndex in stride(from: 0, to: layers.count, by: batchSize) {
            let endIndex = min(startIndex + batchSize, layers.count)
            var arrays: [MLXArray] = []
            for layer in layers[startIndex ..< endIndex] {
                arrays.append(contentsOf: flattenedParameterArrays(from: layer.parameters()))
            }
            evalIfNeeded(arrays)
        }
    }

    private static func flattenedParameterArrays(
        from parameters: ModuleParameters
    ) -> [MLXArray] {
        parameters.flattened().map(\.1)
    }

    private static func evalParameterArraysInBatches(
        _ arrays: [MLXArray],
        batchSize: Int
    ) {
        guard !arrays.isEmpty else { return }
        let resolvedBatchSize = max(batchSize, 1)
        var startIndex = 0
        while startIndex < arrays.count {
            let endIndex = min(startIndex + resolvedBatchSize, arrays.count)
            evalIfNeeded(Array(arrays[startIndex..<endIndex]))
            Memory.clearCache()
            startIndex = endIndex
        }
    }

    private static func evalIfNeeded(_ arrays: [MLXArray]) {
        guard !arrays.isEmpty else { return }
        eval(arrays)
    }

    private static func loadTokenizerComponent(
        modelDir: URL,
        preparedKey: String,
        componentCache: Qwen3TTSPreparedComponentCache
    ) async -> LoadedTokenizerComponent {
        let tokenizerLoadStartedAt = ContinuousClock.now
        var cacheHit = false
        var directConfigLoadUsed = false
        var directConfigFallbackUsed = false
        var tokenizer: (any Tokenizer)?

        do {
            if let cachedTokenizer = componentCache.cachedTokenizer(for: preparedKey) {
                tokenizer = cachedTokenizer.tokenizer
                cacheHit = true
            } else {
                do {
                    tokenizer = try loadTokenizerDirectly(from: modelDir)
                    directConfigLoadUsed = true
                } catch {
                    directConfigFallbackUsed = true
                    tokenizer = try await AutoTokenizer.from(modelFolder: modelDir)
                }

                if let tokenizer {
                    componentCache.storeTokenizer(tokenizer, for: preparedKey)
                }
            }
        } catch {
            qwen3TTSLog("Warning: Could not load tokenizer: \(qwen3TTSLogDescription(error))")
        }

        return LoadedTokenizerComponent(
            tokenizer: tokenizer,
            cacheHit: cacheHit,
            directConfigLoadUsed: directConfigLoadUsed,
            directConfigFallbackUsed: directConfigFallbackUsed,
            loadMS: tokenizerLoadStartedAt.elapsedMilliseconds
        )
    }

    private static func loadTokenizerDirectly(from modelDir: URL) throws -> any Tokenizer {
        let tokenizerDataURL = modelDir.appendingPathComponent("tokenizer.json")
        let tokenizerConfigURL = modelDir.appendingPathComponent("tokenizer_config.json")
        guard FileManager.default.fileExists(atPath: tokenizerDataURL.path),
              FileManager.default.fileExists(atPath: tokenizerConfigURL.path) else {
            throw TokenizerError.missingConfig
        }

        let hub = HubApi.shared
        let tokenizerConfig = try hub.configuration(fileURL: tokenizerConfigURL)
        let tokenizerData = try hub.configuration(fileURL: tokenizerDataURL)
        return try PreTrainedTokenizer(
            tokenizerConfig: tokenizerConfig,
            tokenizerData: tokenizerData,
            strict: true
        )
    }

    private static func loadSpeechTokenizerComponent(
        modelDir: URL,
        preparedKey: String,
        loadOptions: QwenPreparedLoadOptions,
        includeEncoder: Bool,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)?
    ) async throws -> LoadedSpeechTokenizerComponent {
        _ = isolation
        let speechTokenizerPath = modelDir.appendingPathComponent("speech_tokenizer")
        var isDirectory: ObjCBool = false
        let speechTokenizerLoadStartedAt = ContinuousClock.now
        let fileManager = FileManager.default
        var speechTokenizer: Qwen3TTSSpeechTokenizer?
        var reusedResidentSpeechTokenizer = false

        if fileManager.fileExists(atPath: speechTokenizerPath.path, isDirectory: &isDirectory),
           isDirectory.boolValue {
            // Phase 9: adopt the previous model's identical tokenizer object
            // instead of re-materializing 682 MB. Exact content identity only;
            // any identity failure falls through to the ordinary disk load.
            // The host-attested trust identity (weights + config digests) is
            // preferred; the hard-link inode identity is the fallback for
            // loads without a trusted-checkpoint marker.
            let contentIdentity = loadOptions.speechTokenizerContentIdentity
                .map { "trust:\($0)" }
                ?? speechTokenizerComponentIdentity(
                    at: speechTokenizerPath,
                    includeEncoder: includeEncoder
                )
            let residencyIdentity = contentIdentity.map {
                Self.speechTokenizerResidencyIdentity(
                    contentIdentity: $0,
                    includeEncoder: includeEncoder,
                    overrides: loadOptions.diagnosticOverrides
                )
            }
            if let residencyIdentity,
               let residentBox = Qwen3TTSPreparedComponentCache.shared.residentSpeechTokenizer(
                   identityKey: residencyIdentity,
                   includeEncoder: includeEncoder,
                   residencyOverride: loadOptions.diagnosticOverrides.speechTokenizerResidency
               ) {
                // Fresh-load parity: the encoder trims its cache per encode
                // call; the decoder's streaming state resets here and again at
                // every streaming generation start.
                residentBox.speechTokenizer.decoder.resetStreamingState()
                speechTokenizer = residentBox.speechTokenizer
                reusedResidentSpeechTokenizer = true
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-resident-reuse",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
            } else {
            do {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-before-load",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
                speechTokenizer = try await loadSpeechTokenizer(
                    path: speechTokenizerPath,
                    trustPreparedCheckpoint: loadOptions.trustPreparedCheckpoint,
                    includeEncoder: includeEncoder,
                    encoderSplitHalfRotary: loadOptions.diagnosticOverrides.encoderSplitHalfRotary,
                    decoderSlidingWindow: loadOptions.diagnosticOverrides.decoderSlidingWindow,
                    skipSpeechTokenizerEval: loadOptions.skipSpeechTokenizerEval,
                    diagnosticEventSink: diagnosticEventSink,
                    isolation: isolation
                )
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-after-load",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                        ]
                    )
                )
            } catch {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-component-load-failed",
                    details: diagnosticDetails(
                        modelDir: modelDir,
                        loadOptions: loadOptions,
                        extra: [
                            "preparedKey": preparedKey,
                            "includeEncoder": includeEncoder ? "true" : "false",
                            "error": String(reflecting: error),
                        ]
                    )
                )
                throw error
            }
            if let residencyIdentity, let loaded = speechTokenizer {
                Qwen3TTSPreparedComponentCache.shared.storeResidentSpeechTokenizer(
                    loaded,
                    identityKey: residencyIdentity,
                    includesEncoder: includeEncoder,
                    residencyOverride: loadOptions.diagnosticOverrides.speechTokenizerResidency
                )
            }
            }
        } else if fileManager.fileExists(atPath: speechTokenizerPath.path) {
            qwen3TTSLog("speech_tokenizer is not a directory (stale cache), clearing model cache...")
            try? fileManager.removeItem(at: modelDir)
            throw AudioGenerationError.modelNotInitialized(
                "Model cache was corrupted (speech_tokenizer). It has been cleared. Please try loading again."
            )
        } else {
            qwen3TTSLog("Warning: speech_tokenizer directory not found, speech decoding unavailable")
        }

        return LoadedSpeechTokenizerComponent(
            speechTokenizer: speechTokenizer,
            loadMS: speechTokenizerLoadStartedAt.elapsedMilliseconds,
            booleanFlags: [
                "speech_tokenizer_verify_relaxed": loadOptions.trustPreparedCheckpoint,
                "speech_tokenizer_encoder_loaded": includeEncoder,
                "speech_tokenizer_component_reused": reusedResidentSpeechTokenizer,
                "speech_tokenizer_encoder_rope_split_half":
                    includeEncoder && loadOptions.diagnosticOverrides.encoderSplitHalfRotary,
                "speech_tokenizer_decoder_sliding_window": loadOptions.diagnosticOverrides.decoderSlidingWindow,
            ]
        )
    }

    /// Content identity for the on-disk speech tokenizer component, grounded
    /// in the shared-component store's hard links: the resolved weights
    /// file's device/inode/size/mtime plus the tokenizer config digest and
    /// the encoder inclusion. Copies that bypass the store simply never
    /// share an inode and miss the cache; any stat/read failure returns nil
    /// and disables residency for this load (the disk load proceeds).
    static func speechTokenizerComponentIdentity(
        at speechTokenizerPath: URL,
        includeEncoder: Bool
    ) -> String? {
        let weightsURL = speechTokenizerPath
            .appendingPathComponent("model.safetensors")
            .resolvingSymlinksInPath()
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: weightsURL.path),
              let inode = (attributes[.systemFileNumber] as? NSNumber)?.uint64Value,
              let device = (attributes[.systemNumber] as? NSNumber)?.int64Value,
              let size = (attributes[.size] as? NSNumber)?.uint64Value,
              let modified = attributes[.modificationDate] as? Date else {
            return nil
        }
        let configURL = speechTokenizerPath.appendingPathComponent("config.json")
        guard let configData = try? Data(contentsOf: configURL) else {
            return nil
        }
        let configDigest = SHA256.hash(data: configData)
            .map { String(format: "%02x", $0) }
            .joined()
        _ = includeEncoder // capability is matched by the cache's superset rule, not the key
        return "st-v1:\(device):\(inode):\(size):\(modified.timeIntervalSince1970):\(configDigest)"
    }

    private func storeLoadTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedLoadTimingsMS = timings
        diagnosticsLock.unlock()
    }

    private func storeLoadBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedLoadBooleanFlags = flags
        diagnosticsLock.unlock()
    }

    func storePreparationTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedPreparationTimingsMS = timings
        diagnosticsLock.unlock()
    }

    func mergePreparationTimingsMS(_ timings: [String: Int]) {
        diagnosticsLock.lock()
        storedPreparationTimingsMS.merge(timings) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    func storePreparationBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedPreparationBooleanFlags = flags
        diagnosticsLock.unlock()
    }

    func mergePreparationBooleanFlags(_ flags: [String: Bool]) {
        diagnosticsLock.lock()
        storedPreparationBooleanFlags.merge(flags) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    func storePreparationStringFlags(_ flags: [String: String]) {
        diagnosticsLock.lock()
        storedPreparationStringFlags = flags
        diagnosticsLock.unlock()
    }

    func mergePreparationStringFlags(_ flags: [String: String]) {
        diagnosticsLock.lock()
        storedPreparationStringFlags.merge(flags) { _, rhs in rhs }
        diagnosticsLock.unlock()
    }

    /// Once per generation, when its loop exits (never per token).
    func storeGenerationIntrospection(_ summary: Qwen3GenerationIntrospectionSummary?) {
        diagnosticsLock.lock()
        storedGenerationIntrospection = summary
        diagnosticsLock.unlock()
    }

    private static func ensureTokenizerJSON(in modelDir: URL) throws {
        let fm = FileManager.default
        let tokenizerJsonPath = modelDir.appendingPathComponent("tokenizer.json")
        guard !fm.fileExists(atPath: tokenizerJsonPath.path) else {
            return
        }

        let vocabPath = modelDir.appendingPathComponent("vocab.json")
        let mergesPath = modelDir.appendingPathComponent("merges.txt")
        let hasVocab = fm.fileExists(atPath: vocabPath.path)
        let hasMerges = fm.fileExists(atPath: mergesPath.path)

        guard hasVocab, hasMerges else {
            qwen3TTSLog("Warning: Cannot generate tokenizer.json — vocab.json: \(hasVocab), merges.txt: \(hasMerges)")
            return
        }

        do {
            try generateTokenizerJson(
                vocabPath: vocabPath,
                mergesPath: mergesPath,
                tokenizerConfigPath: modelDir.appendingPathComponent("tokenizer_config.json"),
                outputPath: tokenizerJsonPath
            )
            qwen3TTSLog("Generated tokenizer.json from vocab.json + merges.txt")
        } catch {
            qwen3TTSLog("Warning: Failed to generate tokenizer.json: \(qwen3TTSLogDescription(error))")
        }
    }

    private static func preparedDirectoryKey(for modelDir: URL) -> String {
        modelDir.standardizedFileURL.resolvingSymlinksInPath().path
    }

    /// The talker's text embedding as the model's parameter tree names it.
    private static let textEmbeddingModuleKey = "model.text_embedding"

    /// A row reader over the checkpoint's text embedding, or nil when the
    /// table must be loaded as a parameter: the checkpoint is not the single
    /// `model.safetensors` the production artifacts ship, or it holds the
    /// table in a layout the reader does not know.
    private static func openTextEmbeddingRows(
        in modelDir: URL,
        config: Qwen3TTSModelConfig,
        talkerConfig: Qwen3TTSTalkerConfig
    ) throws -> Qwen3TextEmbeddingRows? {
        let weightsFile = modelDir.appendingPathComponent("model.safetensors")
        guard FileManager.default.fileExists(atPath: weightsFile.path) else { return nil }
        let recipe = config.perLayerQuantization?.quantization(layer: textEmbeddingModuleKey)
            ?? config.quantization
        let quantization: Qwen3TextEmbeddingRows.Quantization?
        if let recipe {
            // Only the affine recipe has a row-wise dequantization here.
            guard recipe.mode == .affine else { return nil }
            quantization = .init(groupSize: recipe.groupSize, bits: recipe.bits)
        } else {
            quantization = nil
        }
        return try Qwen3TextEmbeddingRows.open(
            weightsFile: weightsFile,
            tensorPrefix: "talker.\(textEmbeddingModuleKey)",
            rowCount: talkerConfig.textVocabSize,
            dimensions: talkerConfig.textHiddenSize,
            quantization: quantization
        )
    }

    static let codePredictorModuleKey = "code_predictor"

    /// The quantization each talker module loads with: none without scales; the
    /// code predictor's own recipe when it comes from a sibling (RF-55); else
    /// the per-layer recipe, else the global one.
    static func talkerQuantization(
        path: String,
        hasScales: Bool,
        config: Qwen3TTSModelConfig,
        codePredictor: (Int, Int, QuantizationMode)?
    ) -> (Int, Int, QuantizationMode)? {
        guard hasScales else { return nil }
        if let codePredictor, path == codePredictorModuleKey || path.hasPrefix("\(codePredictorModuleKey).") {
            return codePredictor
        }
        if let perLayerQuant = config.perLayerQuantization,
           let layerQuant = perLayerQuant.quantization(layer: path) {
            return layerQuant.asTuple
        }
        return config.quantization?.asTuple
    }

    /// RF-55: the installed sibling of `modelDir` at `bits` (the `-8bit`
    /// directory beside a `-4bit` one), only when it is an installed artifact
    /// (its integrity record present) of the same model type quantized at
    /// exactly `bits`; anything else refuses the load.
    static func codePredictorSibling(
        of modelDir: URL, config: Qwen3TTSModelConfig, ownBits: Int, bits: Int
    ) throws -> (directory: URL, quantization: BaseConfiguration.Quantization) {
        let directory = try codePredictorSiblingDirectory(
            of: installedDirectory(of: modelDir), ownBits: ownBits, bits: bits)
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: directory.appendingPathComponent(".qwenvoice-model-integrity.json").path) else {
            throw AudioGenerationError.modelNotInitialized("The \(bits)-bit sibling is not an installed artifact")
        }
        let siblingConfig = try JSONDecoder().decode(
            Qwen3TTSModelConfig.self, from: Data(contentsOf: directory.appendingPathComponent("config.json")))
        guard siblingConfig.ttsModelType == config.ttsModelType,
              let quantization = siblingConfig.quantization, quantization.bits == bits else {
            throw AudioGenerationError.modelNotInitialized("The \(bits)-bit sibling is another model")
        }
        return (directory, quantization)
    }

    /// Hosts load from a prepared overlay whose weights link into the
    /// installed folder; the sibling sits beside the installed folder, so the
    /// weights' link is followed back to it. A folder loaded in place is its
    /// own installed folder.
    static func installedDirectory(of modelDir: URL) -> URL {
        modelDir.appendingPathComponent("model.safetensors").resolvingSymlinksInPath().deletingLastPathComponent()
    }

    /// The sibling's directory: this one's name with its precision suffix
    /// swapped (`…-4bit` to `…-8bit`), beside it.
    static func codePredictorSiblingDirectory(of modelDir: URL, ownBits: Int, bits: Int) throws -> URL {
        let name = modelDir.lastPathComponent
        let suffix = "-\(ownBits)bit"
        guard name.hasSuffix(suffix) else {
            throw AudioGenerationError.modelNotInitialized("The model directory names no precision")
        }
        return modelDir.deletingLastPathComponent()
            .appendingPathComponent(String(name.dropLast(suffix.count)) + "-\(bits)bit", isDirectory: true)
    }

    private static func loadWeights(
        from directory: URL,
        directSafetensorsFileName: String
    ) throws -> [String: MLXArray] {
        let directWeightsURL = directory.appendingPathComponent(directSafetensorsFileName)
        if FileManager.default.fileExists(atPath: directWeightsURL.path) {
            return try MLX.loadArrays(url: directWeightsURL)
        }

        var mergedWeights = [String: MLXArray]()
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        for file in files where file.pathExtension == "safetensors" {
            let weights = try MLX.loadArrays(url: file)
            mergedWeights.merge(weights) { _, new in new }
        }
        return mergedWeights
    }

    static func speakerEncoderWeightsForLoading(
        _ sourceWeights: [String: MLXArray]
    ) throws -> [String: MLXArray] {
        let weights = Qwen3TTSSpeakerEncoder.sanitize(weights: sourceWeights)
        try Qwen3LearnedComponentWeights.requireNonEmpty(
            weights.count,
            component: "speaker_encoder"
        )
        return weights
    }

    static func loadSpeechTokenizer(
        path: URL,
        trustPreparedCheckpoint: Bool,
        includeEncoder: Bool,
        encoderSplitHalfRotary: Bool = false,
        decoderSlidingWindow: Bool = false,
        skipSpeechTokenizerEval: Bool,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)?,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> Qwen3TTSSpeechTokenizer {
        _ = isolation
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-speech-tokenizer-load-start",
            details: [
                "path": path.path,
                "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                "includeEncoder": includeEncoder ? "true" : "false",
            ]
        )
        // Load config — fall back to defaults if config.json is missing
        let tokenizerConfig: Qwen3TTSTokenizerConfig
        let configPath = path.appendingPathComponent("config.json")
        if let configData = try? Data(contentsOf: configPath) {
            tokenizerConfig = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: configData)
        } else {
            qwen3TTSLog("Warning: speech_tokenizer/config.json not found, using defaults")
            let defaultJson = "{}".data(using: .utf8)!
            tokenizerConfig = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: defaultJson)
        }
        if let validationFailure = tokenizerConfig.qwen3TTS12HzValidationFailure(includeEncoder: includeEncoder) {
            throw AudioGenerationError.invalidInput(
                "Qwen3-TTS speech tokenizer contract mismatch: \(validationFailure)"
            )
        }
        await emitPreparedLoadDiagnostic(
            diagnosticEventSink,
            action: "qwen-speech-tokenizer-after-config",
            details: [
                "path": path.path,
                "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                "includeEncoder": includeEncoder ? "true" : "false",
                "inputSampleRate": "\(tokenizerConfig.inputSampleRate)",
                "outputSampleRate": "\(tokenizerConfig.outputSampleRate)",
                "frameRateHz": "12.5",
                "encoderValidNumQuantizers": "\(tokenizerConfig.encoderValidNumQuantizers)",
                "decoderNumQuantizers": "\(tokenizerConfig.decoderConfig?.numQuantizers ?? 0)",
                "encoderConfiguredNumQuantizers": "\(tokenizerConfig.encoderConfig?.numQuantizers ?? 0)",
                "decoderCodebookSize": "\(tokenizerConfig.decoderConfig?.codebookSize ?? 0)",
                "decoderSemanticCodebookSize": "\(tokenizerConfig.decoderConfig?.semanticCodebookSize ?? 0)",
            ]
        )

        let speechTokenizer = Qwen3TTSSpeechTokenizer(
            config: tokenizerConfig,
            includeEncoder: includeEncoder,
            encoderSplitHalfRotary: encoderSplitHalfRotary,
            decoderSlidingWindow: decoderSlidingWindow
        )

        // Load weights
        var tokenizerWeights = try loadWeights(
            from: path,
            directSafetensorsFileName: "model.safetensors"
        )

        try Qwen3LearnedComponentWeights.requireNonEmpty(
            tokenizerWeights.count,
            component: "speech_tokenizer"
        )

        if !tokenizerWeights.isEmpty {
            if !includeEncoder {
                tokenizerWeights = tokenizerWeights.filter { key, _ in
                    !key.hasPrefix("encoder_model.")
                        && !key.hasPrefix("speech_tokenizer.encoder_model.")
                        && !key.contains(".encoder_model.")
                }
            }
            var sanitized = Qwen3TTSSpeechTokenizer.sanitize(weights: tokenizerWeights)
            tokenizerWeights.removeAll(keepingCapacity: false)
            if !includeEncoder {
                sanitized = sanitized.filter { key, _ in
                    !key.hasPrefix("encoder_model.")
                }
            }
            var pairs = sanitized.map { ($0.key, $0.value) }
            try speechTokenizer.update(
                parameters: ModuleParameters.unflattened(pairs),
                verify: trustPreparedCheckpoint ? .noUnusedKeys : .all
            )
            pairs.removeAll(keepingCapacity: false)
            sanitized.removeAll(keepingCapacity: false)
            Memory.clearCache()
            await emitPreparedLoadDiagnostic(
                diagnosticEventSink,
                action: "qwen-speech-tokenizer-after-update",
                details: [
                    "path": path.path,
                    "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                    "includeEncoder": includeEncoder ? "true" : "false",
                    "parameterPairCount": "\(speechTokenizer.parameters().flattened().count)",
                ]
            )
            if skipSpeechTokenizerEval {
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-eval-skipped",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "0",
                        "reason": "skipSpeechTokenizerEval",
                    ]
                )
            } else {
                let parameterArrays = flattenedParameterArrays(from: speechTokenizer.parameters())
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-before-eval",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "\(parameterArrays.count)",
                        "evalBatchSize": "\(speechTokenizerEvalBatchSize)",
                    ]
                )
                evalParameterArraysInBatches(parameterArrays, batchSize: speechTokenizerEvalBatchSize)
                await emitPreparedLoadDiagnostic(
                    diagnosticEventSink,
                    action: "qwen-speech-tokenizer-after-eval",
                    details: [
                        "path": path.path,
                        "includeEncoder": includeEncoder ? "true" : "false",
                        "parameterArrayCount": "\(parameterArrays.count)",
                    ]
                )
            }
            Memory.clearCache()
        }

        speechTokenizer.decoder.resetStreamingState()
        qwen3TTSLog("Loaded speech tokenizer decoder")
        return speechTokenizer
    }

    // MARK: - Generate tokenizer.json from vocab.json + merges.txt

    /// Qwen3-TTS repos ship with a slow tokenizer (vocab.json + merges.txt) but
    /// swift-transformers requires tokenizer.json (fast tokenizer format). This
    /// generates the fast tokenizer JSON from the available files.
    private static func generateTokenizerJson(
        vocabPath: URL,
        mergesPath: URL,
        tokenizerConfigPath: URL,
        outputPath: URL
    ) throws {
        // Read vocab
        let vocabData = try Data(contentsOf: vocabPath)
        let vocabDict = try JSONSerialization.jsonObject(with: vocabData) as? [String: Int] ?? [:]

        // Read merges (skip header line "#version: ...")
        let mergesText = try String(contentsOf: mergesPath, encoding: .utf8)
        let mergeLines = mergesText.components(separatedBy: .newlines)
            .filter { !$0.isEmpty && !$0.hasPrefix("#") }

        // Read added_tokens from tokenizer_config.json
        var addedTokens = [[String: Any]]()
        if let configData = try? Data(contentsOf: tokenizerConfigPath),
           let configDict = try? JSONSerialization.jsonObject(with: configData) as? [String: Any],
           let addedTokensDecoder = configDict["added_tokens_decoder"] as? [String: [String: Any]] {
            for (idStr, tokenInfo) in addedTokensDecoder {
                guard let tokenId = Int(idStr),
                      let content = tokenInfo["content"] as? String else { continue }
                let entry: [String: Any] = [
                    "id": tokenId,
                    "content": content,
                    "single_word": tokenInfo["single_word"] as? Bool ?? false,
                    "lstrip": tokenInfo["lstrip"] as? Bool ?? false,
                    "rstrip": tokenInfo["rstrip"] as? Bool ?? false,
                    "normalized": tokenInfo["normalized"] as? Bool ?? false,
                    "special": tokenInfo["special"] as? Bool ?? true
                ]
                addedTokens.append(entry)
            }
            addedTokens.sort { ($0["id"] as? Int ?? 0) < ($1["id"] as? Int ?? 0) }
        }

        // Build tokenizer.json
        // Qwen2 uses ByteLevel BPE with a GPT-2-style regex pre-tokenizer
        let tokenizerJson: [String: Any] = [
            "version": "1.0",
            "truncation": NSNull(),
            "padding": NSNull(),
            "added_tokens": addedTokens,
            "normalizer": NSNull(),
            "pre_tokenizer": [
                "type": "Sequence",
                "pretokenizers": [
                    [
                        "type": "Split",
                        "pattern": [
                            "Regex": "(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\\r\\n\\p{L}\\p{N}]?\\p{L}+|\\p{N}{1,3}| ?[^\\s\\p{L}\\p{N}]+[\\r\\n]*|\\s*[\\r\\n]+|\\s+(?!\\S)|\\s+"
                        ],
                        "behavior": "Isolated",
                        "invert": false
                    ] as [String: Any],
                    [
                        "type": "ByteLevel",
                        "add_prefix_space": false,
                        "trim_offsets": true,
                        "use_regex": false
                    ] as [String: Any]
                ] as [[String: Any]]
            ] as [String: Any],
            "post_processor": NSNull(),
            "decoder": [
                "type": "ByteLevel",
                "add_prefix_space": true,
                "trim_offsets": true,
                "use_regex": true
            ] as [String: Any],
            "model": [
                "type": "BPE",
                "dropout": NSNull(),
                "unk_token": NSNull(),
                "continuing_subword_prefix": "",
                "end_of_word_suffix": "",
                "fuse_unk": false,
                "byte_fallback": false,
                "ignore_merges": false,
                "vocab": vocabDict,
                "merges": mergeLines
            ] as [String: Any]
        ]

        let jsonData = try JSONSerialization.data(withJSONObject: tokenizerJson, options: [.sortedKeys])
        try jsonData.write(to: outputPath)
    }
}
