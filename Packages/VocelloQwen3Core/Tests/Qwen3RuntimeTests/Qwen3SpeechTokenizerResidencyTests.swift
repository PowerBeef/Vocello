import Foundation
@testable import MLXAudioTTS
import XCTest

/// Phase 9: speech-tokenizer residency semantics — content-exact adoption
/// with the encoder-superset rule, lifecycle clearing, and the fail-safe
/// file-identity helper.
final class Qwen3SpeechTokenizerResidencyTests: XCTestCase {
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
}
