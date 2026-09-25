import Foundation
import MLX
import MLXAudioCore
@testable import MLXAudioTTS
import MLXLMCommon
import MLXNN
import Tokenizers
import XCTest
import os

// MLXLMCommon, Tokenizers and MLXAudioTTS each declare a `Tokenizer`; this file
// names the swift-transformers types it conforms to by module.

/// A deterministic text tokenizer for the tiny talker. The chat markers, the two
/// role words and the newline are single tokens, like the shipping Qwen
/// tokenizer, so the production prompt slicing (`<|im_start|>assistant\n` is
/// three tokens, the chat tail five) holds; every other character is one token
/// folded into the tiny text vocabulary. Only `encode(text:)` is consulted by
/// the model; the chat-template surface is not.
private struct TinyTextTokenizer: Tokenizers.Tokenizer {
    static let vocabularySize = 64
    private static let firstCharacterToken = 9
    private static let markers: [(piece: String, id: Int)] = [
        ("<|im_start|>", 1),
        ("<|im_end|>", 2),
        ("\n", 3),
        ("assistant", 4),
        ("user", 5),
    ]

    private static func pieces(_ text: String) -> [String] {
        var result: [String] = []
        var rest = Substring(text)
        while let first = rest.first {
            if let marker = markers.first(where: { rest.hasPrefix($0.piece) }) {
                result.append(marker.piece)
                rest = rest.dropFirst(marker.piece.count)
            } else {
                result.append(String(first))
                rest = rest.dropFirst()
            }
        }
        return result
    }

    private static func id(for piece: String) -> Int {
        if let marker = markers.first(where: { $0.piece == piece }) {
            return marker.id
        }
        let scalar = piece.unicodeScalars.first.map { Int($0.value) } ?? 0
        return firstCharacterToken + scalar % (vocabularySize - firstCharacterToken)
    }

    func tokenize(text: String) -> [String] { Self.pieces(text) }
    func encode(text: String) -> [Int] { Self.pieces(text).map(Self.id(for:)) }
    func encode(text: String, addSpecialTokens: Bool) -> [Int] { encode(text: text) }
    func decode(tokens: [Int], skipSpecialTokens: Bool) -> String { "" }
    func convertTokenToId(_ token: String) -> Int? { Self.id(for: token) }
    func convertIdToToken(_ id: Int) -> String? { nil }

    var bosToken: String? { nil }
    var bosTokenId: Int? { nil }
    var eosToken: String? { nil }
    var eosTokenId: Int? { nil }
    var unknownToken: String? { nil }
    var unknownTokenId: Int? { nil }

    private var noTemplate: Tokenizers.TokenizerError {
        .chatTemplate("The tiny talker fixture has no chat template")
    }

    func applyChatTemplate(messages: [Tokenizers.Message]) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(messages: [Tokenizers.Message], tools: [Tokenizers.ToolSpec]?) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(
        messages: [Tokenizers.Message],
        tools: [Tokenizers.ToolSpec]?,
        additionalContext: [String: any Sendable]?
    ) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(
        messages: [Tokenizers.Message],
        chatTemplate: Tokenizers.ChatTemplateArgument
    ) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(messages: [Tokenizers.Message], chatTemplate: String) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(
        messages: [Tokenizers.Message],
        chatTemplate: Tokenizers.ChatTemplateArgument?,
        addGenerationPrompt: Bool,
        truncation: Bool,
        maxLength: Int?,
        tools: [Tokenizers.ToolSpec]?
    ) throws -> [Int] {
        throw noTemplate
    }

    func applyChatTemplate(
        messages: [Tokenizers.Message],
        chatTemplate: Tokenizers.ChatTemplateArgument?,
        addGenerationPrompt: Bool,
        truncation: Bool,
        maxLength: Int?,
        tools: [Tokenizers.ToolSpec]?,
        additionalContext: [String: any Sendable]?
    ) throws -> [Int] {
        throw noTemplate
    }
}

/// PA-19: a tiny seeded random-weight talker driven through the production
/// generate loop (`Qwen3TTSModel.generateVoiceDesign`: conditioning prefix,
/// talker prefill and KV-cached steps, first-codebook sampling with special-token
/// suppression and EOS gating, the compiled code-predictor passes, codec-embedding
/// assembly, the token cap and the final quality-first decode). No downloaded
/// weights: the talker, code predictor and speech decoder are random modules
/// built from tiny configs, like the decoder and code-predictor fixtures.
final class Qwen3TalkerGenerateLoopTests: XCTestCase {
    private static let codeGroups = 3
    private static let codebookSize = 16
    private static let codecEOS = 1_030

    /// Talker vocabulary = the 1 024 reserved special codec ids the loop
    /// suppresses, plus a 16-entry codebook. Special ids sit inside the reserved
    /// range; EOS is the one special token the sampler may emit.
    private static func tinyModelConfig() throws -> Qwen3TTSModelConfig {
        let json = """
        {
          "model_type": "qwen3_tts",
          "tts_model_type": "voice_design",
          "tts_model_size": "tiny",
          "im_start_token_id": 1,
          "im_end_token_id": 2,
          "tts_pad_token_id": 6,
          "tts_bos_token_id": 7,
          "tts_eos_token_id": 8,
          "sample_rate": 24000,
          "talker_config": {
            "vocab_size": 1040,
            "hidden_size": 16,
            "intermediate_size": 32,
            "num_hidden_layers": 2,
            "num_attention_heads": 2,
            "num_key_value_heads": 1,
            "head_dim": 8,
            "hidden_act": "silu",
            "max_position_embeddings": 512,
            "rms_norm_eps": 1e-6,
            "rope_theta": 10000,
            "attention_bias": false,
            "num_code_groups": 3,
            "text_hidden_size": 16,
            "text_vocab_size": 64,
            "codec_eos_token_id": 1030,
            "codec_think_id": 1031,
            "codec_nothink_id": 1032,
            "codec_think_bos_id": 1033,
            "codec_think_eos_id": 1034,
            "codec_pad_id": 1035,
            "codec_bos_id": 1036,
            "code_predictor_config": {
              "vocab_size": 16,
              "hidden_size": 16,
              "intermediate_size": 32,
              "num_hidden_layers": 1,
              "num_attention_heads": 2,
              "num_key_value_heads": 1,
              "head_dim": 8,
              "hidden_act": "silu",
              "max_position_embeddings": 64,
              "rms_norm_eps": 1e-6,
              "rope_theta": 10000,
              "attention_bias": false,
              "attention_dropout": 0,
              "num_code_groups": 3
            }
          }
        }
        """
        return try JSONDecoder().decode(Qwen3TTSModelConfig.self, from: Data(json.utf8))
    }

    /// The tiny random Mimi decoder of `Qwen3DecoderPartitionTests` with three
    /// quantizers (one semantic, two acoustic) to match the talker's code groups.
    private static func tinySpeechTokenizer() throws -> Qwen3TTSSpeechTokenizer {
        var decoderConfig = try Qwen3DecoderPartitionTests.tinyDecoderConfig()
        decoderConfig.numQuantizers = codeGroups
        var config = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: Data("{}".utf8))
        config.decoderConfig = decoderConfig
        config.decodeUpsampleRate = (decoderConfig.upsampleRates + decoderConfig.upsamplingRatios).reduce(1, *)
        return Qwen3TTSSpeechTokenizer(config: config, includeEncoder: false)
    }

    /// Random weights from a fixed global seed, so every run builds the same model.
    private static func makeModel(withTextTokenizer: Bool = true) throws -> Qwen3TTSModel {
        MLXRandom.seed(0x7A1C_E5)
        let model = Qwen3TTSModel(config: try tinyModelConfig())
        model.speechTokenizer = try tinySpeechTokenizer()
        eval(model)
        if withTextTokenizer {
            model.tokenizer = TinyTextTokenizer()
        }
        return model
    }

    private static func samplingPolicy(seed: UInt64, maximumCodecTokens: Int = 16) -> Qwen3RequestSamplingPolicy {
        let stage = Qwen3SamplingStage(temperature: 0.9, topP: 1, topK: 50, minP: 0)
        return Qwen3RequestSamplingPolicy(
            effectiveSeed: seed,
            talker: stage,
            subtalker: stage,
            repetitionPenalty: 1.05,
            maximumCodecTokens: maximumCodecTokens
        )
    }

    private struct Take {
        let frames: [[Int32]]
        let samples: [Float]
        let finishReason: AudioGenerationFinishReason
    }

    private func generate(
        _ model: Qwen3TTSModel,
        seed: UInt64,
        maximumCodecTokens: Int = 16
    ) async throws -> Take {
        let frames = OSAllocatedUnfairLock<[[Int32]]>(initialState: [])
        let completion = try await model.generateVoiceDesignQualityFirst(
            text: "Hello there, tiny talker.",
            language: "auto",
            voiceDescription: "A calm narrator.",
            generationParameters: model.defaultGenerationParameters,
            samplingPolicy: Self.samplingPolicy(seed: seed, maximumCodecTokens: maximumCodecTokens),
            memoryPolicy: .compatibilityDefault,
            onPrepared: {},
            codecTraceSink: { frame in frames.withLock { $0.append(frame) } },
            isolation: nil
        )
        let samples = completion.audio.asArray(Float.self)
        return Take(frames: frames.withLock { $0 }, samples: samples, finishReason: completion.finishReason)
    }

    // MARK: - Talker

    func testIncrementalKVCachedTalkerStepsMatchAFullSequencePass() throws {
        MLXRandom.seed(0x7A1C_E6)
        let talkerConfig = try XCTUnwrap(try Self.tinyModelConfig().talkerConfig)
        let talker = Qwen3TTSTalkerForConditionalGeneration(config: talkerConfig)
        eval(talker)
        let total = 9
        let prefill = 6
        let embeds = MLXRandom.normal([1, total, 16], key: MLXRandom.key(0x7A1C_E7)) * 0.5

        // One causal pass over the whole sequence is the reference.
        let (fullLogits, _) = talker(embeds)
        // The loop's path: prefill the prefix into the KV cache, then one step per position.
        let cache = talker.makeCache()
        let (prefillLogits, _) = talker(embeds[0..., 0 ..< prefill, 0...], cache: cache)
        var incremental = [prefillLogits[0..., (prefill - 1)..., 0...]]
        for position in prefill ..< total {
            let (stepLogits, _) = talker(embeds[0..., position ..< (position + 1), 0...], cache: cache)
            incremental.append(stepLogits)
        }
        let stepped = concatenated(incremental, axis: 1)
        let reference = fullLogits[0..., (prefill - 1)..., 0...]
        eval(stepped, reference)

        XCTAssertEqual(cache.first?.offset, total)
        XCTAssertEqual(stepped.shape, reference.shape)
        XCTAssertEqual(stepped.shape, [1, total - prefill + 1, 1_040])
        let steppedValues = stepped.asArray(Float.self)
        let referenceValues = reference.asArray(Float.self)
        XCTAssertTrue(steppedValues.allSatisfy(\.isFinite))
        let maxDifference = zip(steppedValues, referenceValues).map { abs($0 - $1) }.max() ?? .infinity
        XCTAssertLessThanOrEqual(maxDifference, 1e-4, "KV-cached steps diverged from the full pass")
    }

    // MARK: - Generate loop

    func testSeededGenerateLoopIsReproducibleAndEmitsOnlyCodebookFrames() async throws {
        let model = try Self.makeModel()
        let maximumCodecTokens = 16

        let first = try await generate(model, seed: 0x5EED_0001, maximumCodecTokens: maximumCodecTokens)
        let replay = try await generate(model, seed: 0x5EED_0001, maximumCodecTokens: maximumCodecTokens)

        XCTAssertEqual(first.frames, replay.frames, "The same request seed must replay the same codes")
        XCTAssertEqual(first.samples, replay.samples, "The same codes must decode to the same audio")
        XCTAssertEqual(first.finishReason, replay.finishReason)

        // EOS is suppressed for the first two frames and never emitted as a frame.
        XCTAssertGreaterThanOrEqual(first.frames.count, 2)
        XCTAssertLessThanOrEqual(first.frames.count, maximumCodecTokens)
        for (index, frame) in first.frames.enumerated() {
            XCTAssertEqual(frame.count, Self.codeGroups, "frame \(index)")
            XCTAssertTrue(
                frame.allSatisfy { (0 ..< Int32(Self.codebookSize)).contains($0) },
                "frame \(index) left the codebook: \(frame)"
            )
        }
        switch first.finishReason {
        case .maxTokens:
            XCTAssertEqual(first.frames.count, maximumCodecTokens, "The token cap bounds the loop")
        case .eos:
            XCTAssertLessThan(first.frames.count, maximumCodecTokens)
        default:
            XCTFail("Unexpected finish reason \(first.finishReason)")
        }

        // Quality-first decode: exactly one upsampled window per generated frame.
        let upsample = try XCTUnwrap(model.speechTokenizer?.decodeUpsampleRate)
        XCTAssertEqual(first.samples.count, first.frames.count * upsample)
        XCTAssertTrue(first.samples.allSatisfy { $0.isFinite && abs($0) <= 1 })
    }

    func testDifferentRequestSeedsSampleDifferentCodecTraces() async throws {
        let model = try Self.makeModel()
        let first = try await generate(model, seed: 0x5EED_0001)
        let second = try await generate(model, seed: 0x5EED_0002)
        XCTAssertNotEqual(first.frames, second.frames, "The request seed drives both sampling stages")
    }

    func testTokenCapStopsTheLoop() async throws {
        let model = try Self.makeModel()
        let take = try await generate(model, seed: 0x5EED_0003, maximumCodecTokens: 3)
        XCTAssertGreaterThanOrEqual(take.frames.count, 2)
        XCTAssertLessThanOrEqual(take.frames.count, 3)
        if take.frames.count == 3 {
            XCTAssertEqual(take.finishReason, .maxTokens)
        }
    }

    func testMissingTextTokenizerFailsBeforeTheLoop() async throws {
        let model = try Self.makeModel(withTextTokenizer: false)
        do {
            _ = try await generate(model, seed: 0x5EED_0004)
            XCTFail("A model without its text tokenizer must refuse to generate")
        } catch let error as AudioGenerationError {
            guard case .modelNotInitialized = error else {
                return XCTFail("Unexpected error \(error)")
            }
        }
    }

    func testCancelledRequestStopsWithCancellation() async throws {
        let model = try Self.makeModel()
        let task = Task {
            try await model.generateVoiceDesign(
                text: "Hello there, tiny talker.",
                language: "auto",
                voiceDescription: "A calm narrator.",
                generationParameters: model.defaultGenerationParameters,
                samplingPolicy: Self.samplingPolicy(seed: 0x5EED_0005, maximumCodecTokens: 64),
                memoryPolicy: .compatibilityDefault
            )
        }
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("A cancelled request must not complete")
        } catch is CancellationError {
            // Cancellation is typed, never a generation failure.
        }

        // The generation gate was released: the next request runs.
        let take = try await generate(model, seed: 0x5EED_0006, maximumCodecTokens: 3)
        XCTAssertGreaterThanOrEqual(take.frames.count, 2)
    }
}
