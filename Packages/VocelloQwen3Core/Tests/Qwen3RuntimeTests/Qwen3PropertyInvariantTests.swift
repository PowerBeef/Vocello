import MLXAudioCore
@testable import MLXAudioTTS
import Testing
@testable import VocelloQwen3Core

/// Parameterized Swift Testing invariants for the owned Qwen3 runtime (DW-03 P2-4).
/// Pure Swift logic only (no MLX Metal kernel dispatch), so tests run in parallel
/// under `swiftpm-testing-helper` without depending on an executable-adjacent metallib.
@Suite("Qwen3 runtime parameterized invariants")
struct Qwen3PropertyInvariantTests {
    @Test(
        "EOS suppression window blocks only for its exact hold length after the first EOS",
        arguments: [1, 2, 3, 5, 8], [1, 2, 4]
    )
    func eosSuppressionWindowExactHoldBounds(holdFrames: Int, productionMinimum: Int) {
        var window = Qwen3EOSSuppressionWindow(frames: holdFrames)
        let openAt = productionMinimum + 4

        #expect(!window.allowsEOS(generatedCodeCount: productionMinimum - 1, productionMinimum: productionMinimum))
        #expect(window.allowsEOS(generatedCodeCount: productionMinimum, productionMinimum: productionMinimum))
        #expect(window.watchesForFirstEOS(allowsEOS: true))

        window.open(atGeneratedCodeCount: openAt)
        #expect(window.startFrame == openAt)
        #expect(!window.watchesForFirstEOS(allowsEOS: true))

        for step in openAt ..< (openAt + holdFrames) {
            #expect(!window.allowsEOS(generatedCodeCount: step, productionMinimum: productionMinimum))
        }
        #expect(window.allowsEOS(generatedCodeCount: openAt + holdFrames, productionMinimum: productionMinimum))

        // Re-opening later never shifts the original hold anchor.
        window.open(atGeneratedCodeCount: openAt + holdFrames + 10)
        #expect(window.startFrame == openAt)
    }

    @Test(
        "Zero-frame EOS suppression holds nothing and never relaxes productionMinimum",
        arguments: [1, 2, 5, 10]
    )
    func zeroFrameEOSSuppressionRespectsProductionMinimum(productionMinimum: Int) {
        let window = Qwen3EOSSuppressionWindow(frames: 0)
        #expect(!window.allowsEOS(generatedCodeCount: productionMinimum - 1, productionMinimum: productionMinimum))
        #expect(window.allowsEOS(generatedCodeCount: productionMinimum, productionMinimum: productionMinimum))
        #expect(!window.watchesForFirstEOS(allowsEOS: true))
    }

    @Test(
        "Blank speaker identifiers fail closed as AudioGenerationError.invalidInput",
        arguments: ["", " ", "   \t\n "]
    )
    func blankSpeakersThrowInvalidInput(speaker: String) {
        let table = ["aiden": [3_001], "ryan": [3_002], "serena": [3_003]]
        #expect {
            _ = try Qwen3TTSModel.speakerTokenIDs(for: speaker, in: table)
        } throws: { error in
            guard case AudioGenerationError.invalidInput = error else { return false }
            return true
        }
    }

    @Test(
        "Unknown speaker identifiers fail closed as AudioGenerationError.modelNotInitialized",
        arguments: ["unknown_speaker", "aiden_extra", "nobody"]
    )
    func unknownSpeakersThrowModelNotInitialized(speaker: String) {
        let table = ["aiden": [3_001], "ryan": [3_002], "serena": [3_003]]
        #expect {
            _ = try Qwen3TTSModel.speakerTokenIDs(for: speaker, in: table)
        } throws: { error in
            guard case AudioGenerationError.modelNotInitialized = error else { return false }
            return true
        }
    }

    @Test(
        "Speaker lookup normalizes surrounding whitespace and ASCII case",
        arguments: zip(
            ["aiden", " Aiden ", "\tAIDEN\n", "  RyAn  ", "SERENA"],
            [[3_001], [3_001], [3_001], [3_002], [3_003]]
        )
    )
    func speakerLookupNormalizesCaseAndWhitespace(query: String, expected: [Int]) throws {
        let table = ["aiden": [3_001], "ryan": [3_002], "serena": [3_003]]
        #expect(try Qwen3TTSModel.speakerTokenIDs(for: query, in: table) == expected)
    }

    @Test(
        "Memory configuration validation accepts positive cadence and positive or nil KV window",
        arguments: [1, 24, 50, 128], [nil, 1, 64, 256]
    )
    func memoryConfigurationAcceptsValidParameters(cadence: Int, kvWindow: Int?) throws {
        let config = VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: kvWindow != nil,
            tokenMemoryClearCadence: cadence,
            talkerKVGeneratedWindow: kvWindow
        )
        let validated = try config.validated()
        #expect(validated == config)
    }

    @Test(
        "Memory configuration validation rejects non-positive cadence with invalidMemoryClearCadence",
        arguments: [-10, -1, 0]
    )
    func memoryConfigurationRejectsNonPositiveCadence(cadence: Int) {
        let config = VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: true,
            tokenMemoryClearCadence: cadence,
            talkerKVGeneratedWindow: 64
        )
        #expect(throws: VocelloQwen3ContractError.invalidMemoryClearCadence) {
            _ = try config.validated()
        }
    }

    @Test(
        "Memory configuration validation rejects non-positive KV window with invalidTalkerKVWindow",
        arguments: [-64, -1, 0]
    )
    func memoryConfigurationRejectsNonPositiveKVWindow(kvWindow: Int) {
        let config = VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: true,
            tokenMemoryClearCadence: 50,
            talkerKVGeneratedWindow: kvWindow
        )
        #expect(throws: VocelloQwen3ContractError.invalidTalkerKVWindow) {
            _ = try config.validated()
        }
    }

    @Test(
        "Stream chunk validation accepts canonical mode schedules and rejects mismatched schedules",
        arguments: [VocelloQwen3SynthesisMode.customVoice, .voiceDesign, .voiceClone], [1, 7, 16, 64]
    )
    func streamChunkValidationEnforcesModeContract(mode: VocelloQwen3SynthesisMode, firstFrames: Int) throws {
        let expectedLater = mode == .customVoice ? firstFrames : firstFrames * 2
        let valid = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: firstFrames,
            laterCodecFrames: expectedLater,
            pendingFrameLimit: expectedLater
        )
        #expect(try valid.validated(for: mode) == valid)

        // Strict monotonicity & exact round-trip against the next frame size.
        let larger = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: firstFrames + 1,
            laterCodecFrames: mode == .customVoice ? firstFrames + 1 : (firstFrames + 1) * 2,
            pendingFrameLimit: mode == .customVoice ? firstFrames + 1 : (firstFrames + 1) * 2
        )
        #expect(valid.compatibilityStreamingInterval < larger.compatibilityStreamingInterval)
        #expect(Qwen3StreamChunkSchedule.codecFrames(forStreamingInterval: valid.compatibilityStreamingInterval) == firstFrames)

        // Mismatched laterCodecFrames or pendingFrameLimit fails closed.
        let wrongLater = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: firstFrames,
            laterCodecFrames: expectedLater + 1,
            pendingFrameLimit: expectedLater + 1
        )
        #expect(throws: VocelloQwen3ContractError.invalidChunkConfiguration) {
            _ = try wrongLater.validated(for: mode)
        }
        let wrongPending = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: firstFrames,
            laterCodecFrames: expectedLater,
            pendingFrameLimit: expectedLater + 1
        )
        #expect(throws: VocelloQwen3ContractError.invalidChunkConfiguration) {
            _ = try wrongPending.validated(for: mode)
        }
        let nonPositive = VocelloQwen3StreamChunkConfiguration(
            firstCodecFrames: 0,
            laterCodecFrames: 0,
            pendingFrameLimit: 0
        )
        #expect(throws: VocelloQwen3ContractError.invalidChunkConfiguration) {
            _ = try nonPositive.validated(for: mode)
        }
    }
}
