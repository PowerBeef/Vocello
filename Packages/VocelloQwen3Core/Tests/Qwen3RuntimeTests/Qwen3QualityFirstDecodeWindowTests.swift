import Foundation
import MLX
@testable import MLXAudioTTS
import XCTest

/// PA-13 / DECODE-002: quality-first decode, the in-context clone cut and
/// codec replay derive their sample window from explicit reference and
/// generated frame counts. Code 0 is a legal codec token, so a generated 0
/// (inside the take or at its tail) never shortens the output.
final class Qwen3QualityFirstDecodeWindowTests: XCTestCase {
    // MARK: - Recorded text conditioning (P05-08)

    /// Custom and Design record the mode they were asked for, which they
    /// honor; a clone records the layout it always uses, whatever was asked.
    func testRecordedTextConditioningNamesTheLayoutThePreparationUsed() {
        for requested in [Qwen3TextConditioningMode.streamingTrailingText, .fullTextNonStreaming] {
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: nil),
                requested.rawValue
            )
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: true),
                "icl_full_text_overlay"
            )
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: false),
                "streaming_trailing_text",
                "a quality-first speaker-only clone still streams its trailing text"
            )
        }
    }

    // MARK: - Window math

    func testWindowWithoutReferenceCoversEveryGeneratedFrame() {
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 0, generatedFrameCount: 10,
                decodedSampleCount: 40, upsampleRate: 4
            ),
            0 ..< 40
        )
    }

    func testReferenceCutUsesIntegerFrameStart() {
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 80, upsampleRate: 4
            ),
            28 ..< 80
        )
        // Production stride (24 kHz / 12.5 fps): 97 reference + 211 generated
        // frames decode to 591,360 samples; the cut is exactly 97 × 1,920.
        let production = Qwen3TTSModel.qualityFirstSampleRange(
            referenceFrameCount: 97, generatedFrameCount: 211,
            decodedSampleCount: 591_360, upsampleRate: 1_920
        )
        XCTAssertEqual(production, 186_240 ..< 591_360)
        XCTAssertEqual(production.count, 211 * 1_920)
    }

    func testWindowClampsToDecodedSamples() {
        // Decoder emitted more than the frames cover: keep only the frames.
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 90, upsampleRate: 4
            ),
            28 ..< 80
        )
        // Decoder emitted fewer: never index past the decoded samples.
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 70, upsampleRate: 4
            ),
            28 ..< 70
        )
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 20, upsampleRate: 4
            ),
            20 ..< 20
        )
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: -1, generatedFrameCount: -1,
                decodedSampleCount: -1, upsampleRate: 4
            ),
            0 ..< 0
        )
    }

    /// The window assumes the tokenizer's decode stride equals the decoder's real
    /// upsample product; production checks only the stride (1_920), so pin the
    /// default decoder product to it here.
    func testDefaultDecoderUpsampleProductMatchesTheTokenizerStride() throws {
        let decoder = try JSONDecoder().decode(
            Qwen3TTSTokenizerDecoderConfig.self, from: Data("{}".utf8)
        )
        let product = (decoder.upsampleRates + decoder.upsamplingRatios).reduce(1, *)
        let config = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: Data("{}".utf8))
        XCTAssertEqual(product, 1_920)
        XCTAssertEqual(product, config.decodeUpsampleRate)
    }

    // MARK: - Tiny decoder

    func testTinyDecoderEmitsExactlyFramesTimesUpsample() throws {
        let tokenizer = try makeTinyTokenizer()
        XCTAssertEqual(tokenizer.decodeUpsampleRate, tokenizer.decoder.totalUpsample)
        for frameCount in [1, 24, 25, 26, 63] {
            let codes = fixtureCodes(frameCount: frameCount, zeroFrames: [])
            let chunks = tokenizer.streamingDecode(
                codes, chunkTokens: Qwen3TTSModel.qualityFirstDecoderChunkFrames
            )
            let decoded = concatenated(chunks, axis: -1)[0]
            XCTAssertEqual(
                decoded.dim(0), frameCount * tokenizer.decodeUpsampleRate,
                "\(frameCount) frames"
            )
        }
    }

    func testGeneratedZeroCodesInsideAndAtTailKeepEveryFrame() throws {
        let tokenizer = try makeTinyTokenizer()
        let frameCount = 63
        // First-group code 0 inside the take and on the last two frames.
        let zeroFrames: Set<Int> = [5, 30, 61, 62]
        let codes = fixtureCodes(frameCount: frameCount, zeroFrames: zeroFrames)
        let firstGroupNonZero = frameCount - zeroFrames.count
        XCTAssertLessThan(firstGroupNonZero, frameCount, "fixture must contain generated code 0")

        let audio = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: 0
        )
        XCTAssertEqual(audio.dim(0), frameCount * tokenizer.decodeUpsampleRate)
        // The former `> 0` count would have dropped the tail.
        XCTAssertGreaterThan(audio.dim(0), firstGroupNonZero * tokenizer.decodeUpsampleRate)
    }

    func testReferenceCutKeepsExactlyTheGeneratedWindow() throws {
        let tokenizer = try makeTinyTokenizer()
        let referenceFrames = 7
        let generatedFrames = 41
        let totalFrames = referenceFrames + generatedFrames
        // Code 0 inside the reference, inside the generated take and at its tail.
        let codes = fixtureCodes(frameCount: totalFrames, zeroFrames: [2, 20, totalFrames - 1])
        let rate = tokenizer.decodeUpsampleRate

        let full = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: 0
        ).asArray(Float.self)
        XCTAssertEqual(full.count, totalFrames * rate)

        let generated = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: referenceFrames
        ).asArray(Float.self)
        XCTAssertEqual(generated.count, generatedFrames * rate)
        let expectedTail = Array(full[(referenceFrames * rate)...])
        XCTAssertEqual(generated.count, expectedTail.count)
        XCTAssertTrue(generated.allSatisfy(\.isFinite), "decoded window must be finite")
        let maxAbsolute = zip(generated, expectedTail)
            .map { abs($0 - $1) }
            .max() ?? 0
        XCTAssertLessThanOrEqual(maxAbsolute, 1e-5, "reference cut must start exactly at frame \(referenceFrames)")
    }

    /// A-04 (RF-52): a streamed decode primed with the reference's codes gives
    /// the quality-first window of `[reference + generated]` in any streaming
    /// partition, and a cold streamed decode does not.
    func testAStreamPrimedWithTheReferenceDecodesAsTheQualityFirstWindow() throws {
        let tokenizer = try makeTinyTokenizer()
        let referenceFrames = 31
        let generatedFrames = 40
        let codes = fixtureCodes(frameCount: referenceFrames + generatedFrames, zeroFrames: [])
        let expected = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: referenceFrames
        ).asArray(Float.self)
        // Quantizer-major `[1, groups, frames]`, as the prompt's reference
        // codes and the streamed chunks reach the decoder.
        let referenceCodes = codes[0..., 0 ..< referenceFrames, 0...].transposed(0, 2, 1)
        let generatedCodes = codes[0..., referenceFrames..., 0...].transposed(0, 2, 1)
        func streamed(primed: Bool, piece: Int) throws -> [Float] {
            tokenizer.decoder.resetStreamingState()
            defer { tokenizer.decoder.resetStreamingState() }
            if primed {
                XCTAssertEqual(try Qwen3TTSModel.primeStreamingDecoder(
                    tokenizer.decoder, referenceCodes: referenceCodes), referenceFrames)
            }
            var output: [Float] = []
            for start in stride(from: 0, to: generatedFrames, by: piece) {
                let end = min(generatedFrames, start + piece)
                output += tokenizer.decoder.streamingStep(generatedCodes[0..., 0..., start ..< end]).asArray(Float.self)
            }
            return output
        }
        for piece in [4, 8] {
            let primed = try streamed(primed: true, piece: piece)
            XCTAssertEqual(primed.count, expected.count)
            let difference = zip(primed, expected).map { abs($0 - $1) }.max() ?? .infinity
            XCTAssertLessThanOrEqual(difference, 1e-5, "primed, \(piece)-frame pieces")
        }
        let cold = try streamed(primed: false, piece: 4)
        XCTAssertGreaterThan(zip(cold, expected).map { abs($0 - $1) }.max() ?? 0, 1e-4,
                             "a cold decoder lacks the reference's history")
        // Priming in other piece sizes leaves the same state.
        tokenizer.decoder.resetStreamingState()
        _ = try Qwen3TTSModel.primeStreamingDecoder(tokenizer.decoder, referenceCodes: referenceCodes, pieceFrames: 7)
        let sevens = tokenizer.decoder.streamingStep(generatedCodes).asArray(Float.self)
        tokenizer.decoder.resetStreamingState()
        XCTAssertLessThanOrEqual(zip(sevens, expected).map { abs($0 - $1) }.max() ?? .infinity, 1e-5)
    }

    /// A-26 (RF-52): a primed state kept from the first take and restored for
    /// later ones decodes bit for bit as decoding the reference again, also
    /// past the key/value cache's 256-frame allocation step.
    func testARestoredPrimedStateDecodesExactlyAsPrimingAgain() throws {
        let tokenizer = try makeTinyTokenizer()
        let decoder = tokenizer.decoder
        let generatedFrames = 40
        for referenceFrames in [31, 270] {
            let codes = fixtureCodes(frameCount: referenceFrames + generatedFrames, zeroFrames: [])
            let referenceCodes = codes[0..., 0 ..< referenceFrames, 0...].transposed(0, 2, 1)
            let generatedCodes = codes[0..., referenceFrames..., 0...].transposed(0, 2, 1)
            func take(prime: () throws -> Void) rethrows -> [Float] {
                decoder.resetStreamingState()
                defer { decoder.resetStreamingState() }
                try prime()
                var output: [Float] = []
                for start in stride(from: 0, to: generatedFrames, by: 8) {
                    let end = min(generatedFrames, start + 8)
                    output += decoder.streamingStep(generatedCodes[0..., 0..., start ..< end]).asArray(Float.self)
                }
                return output
            }
            let primedAgain = try take {
                _ = try Qwen3TTSModel.primeStreamingDecoder(decoder, referenceCodes: referenceCodes)
            }
            let primedStates = Qwen3TTSPrimedDecoderStateCache()
            var reused: [Bool] = []
            for takeNumber in 1 ... 3 {
                let output = try take {
                    let priming = try Qwen3TTSModel.primeStreamingDecoderReusingState(
                        decoder, referenceCodes: referenceCodes, primedStates: primedStates
                    )
                    XCTAssertEqual(priming.frames, referenceFrames)
                    reused.append(priming.reused)
                }
                XCTAssertEqual(output, primedAgain, "\(referenceFrames) reference frames, take \(takeNumber)")
            }
            XCTAssertEqual(reused, [false, true, true], "\(referenceFrames) reference frames")
        }
    }

    /// A-26: a snapshot holds every stateful layer's history and the
    /// pre-transformer cache; a reset empties all of them; a snapshot of other
    /// layers is refused and changes nothing.
    func testASnapshotCoversEveryStreamingLayerAndRefusesOtherLayers() throws {
        let tokenizer = try makeTinyTokenizer()
        let decoder = tokenizer.decoder
        let referenceCodes = fixtureCodes(frameCount: 31, zeroFrames: []).transposed(0, 2, 1)
        decoder.resetStreamingState()
        defer { decoder.resetStreamingState() }
        _ = try Qwen3TTSModel.primeStreamingDecoder(decoder, referenceCodes: referenceCodes)
        let carriers = decoder.streamingStateCarriers()
        XCTAssertFalse(carriers.isEmpty)
        let snapshot = try XCTUnwrap(decoder.streamingStateSnapshot())
        XCTAssertEqual(snapshot.layerPaths, Set(carriers.keys))
        for (path, carrier) in carriers {
            let live = carrier.streamingState
            XCTAssertEqual(snapshot.layerStates[path]?.shape, live?.shape, path)
            if let live, let kept = snapshot.layerStates[path] {
                XCTAssertTrue(arrayEqual(kept, live).item(Bool.self), path)
            }
        }
        // A kernel-one convolution keeps no history; every other layer does.
        XCTAssertGreaterThan(snapshot.layerStates.count, 0)
        XCTAssertEqual(snapshot.transformerStates?.count, decoder.preTransformer.layers.count)
        XCTAssertGreaterThan(snapshot.byteCount, 0)

        decoder.resetStreamingState()
        XCTAssertTrue(decoder.streamingStateCarriers().values.allSatisfy { $0.streamingState == nil },
                      "a reset leaves no layer's history behind")
        XCTAssertNil(decoder.transformerCache)

        let otherLayers = Qwen3DecoderStreamingSnapshot(
            layerPaths: snapshot.layerPaths.union(["elsewhere"]),
            layerStates: snapshot.layerStates,
            transformerStates: snapshot.transformerStates
        )
        XCTAssertFalse(decoder.restoreStreamingState(otherLayers))
        let otherCache = Qwen3DecoderStreamingSnapshot(
            layerPaths: snapshot.layerPaths, layerStates: snapshot.layerStates, transformerStates: []
        )
        XCTAssertFalse(decoder.restoreStreamingState(otherCache))
        let keysOnly = Qwen3DecoderStreamingSnapshot(
            layerPaths: snapshot.layerPaths, layerStates: snapshot.layerStates,
            transformerStates: snapshot.transformerStates?.map { Array($0.prefix(1)) }
        )
        XCTAssertFalse(decoder.restoreStreamingState(keysOnly), "a layer without its values is refused, not trapped")
        XCTAssertTrue(decoder.streamingStateCarriers().values.allSatisfy { $0.streamingState == nil })
        XCTAssertNil(decoder.transformerCache)

        XCTAssertTrue(decoder.restoreStreamingState(snapshot))
        XCTAssertEqual(decoder.transformerCache?.first?.offset, 31)
    }

    /// A-26: a kept state serves only its own decoder and reference, the least
    /// recently used one goes past the limit, a released decoder's entries go
    /// with it, and the runtime's cache clearing empties the shared cache.
    func testThePrimedStateCacheServesOnlyItsDecoderAndReference() async throws {
        let first = try makeTinyTokenizer().decoder
        let second = try makeTinyTokenizer().decoder
        let codes = fixtureCodes(frameCount: 12, zeroFrames: []).transposed(0, 2, 1)
        let reference = Qwen3TTSPrimedDecoderStateCache.referenceKey(referenceCodes: codes, pieceFrames: 25)
        let contiguousCopy = MLXArray(codes.asArray(Int32.self), codes.shape)
        XCTAssertEqual(reference, Qwen3TTSPrimedDecoderStateCache.referenceKey(
            referenceCodes: contiguousCopy, pieceFrames: 25))
        XCTAssertNotEqual(reference, Qwen3TTSPrimedDecoderStateCache.referenceKey(
            referenceCodes: codes, pieceFrames: 7))
        XCTAssertNotEqual(reference, Qwen3TTSPrimedDecoderStateCache.referenceKey(
            referenceCodes: fixtureCodes(frameCount: 12, zeroFrames: [3]).transposed(0, 2, 1), pieceFrames: 25))

        first.resetStreamingState()
        _ = try Qwen3TTSModel.primeStreamingDecoder(first, referenceCodes: codes)
        let snapshot = try XCTUnwrap(first.streamingStateSnapshot())
        first.resetStreamingState()

        let cache = Qwen3TTSPrimedDecoderStateCache(limit: 2)
        cache.store(snapshot, forReference: reference, decoder: first)
        XCTAssertNotNil(cache.snapshot(forReference: reference, decoder: first))
        XCTAssertNil(cache.snapshot(forReference: reference, decoder: second), "another decoder")
        XCTAssertNil(cache.snapshot(forReference: "another reference", decoder: first))

        cache.store(snapshot, forReference: "b", decoder: first)
        XCTAssertNotNil(cache.snapshot(forReference: reference, decoder: first))
        cache.store(snapshot, forReference: "c", decoder: first)
        XCTAssertEqual(cache.count, 2)
        XCTAssertNil(cache.snapshot(forReference: "b", decoder: first), "the least recently used goes first")
        XCTAssertNotNil(cache.snapshot(forReference: reference, decoder: first))

        do {
            let released = try makeTinyTokenizer().decoder
            cache.store(snapshot, forReference: reference, decoder: released)
            XCTAssertNotNil(cache.snapshot(forReference: reference, decoder: released))
        }
        XCTAssertEqual(cache.count, 1, "a released decoder's entry goes with it")
        cache.clear()
        XCTAssertEqual(cache.count, 0)

        // The byte budget evicts the least recently used too, and keeps the
        // newest entry even when it alone is past the budget.
        XCTAssertGreaterThan(snapshot.byteCount, 0)
        let bounded = Qwen3TTSPrimedDecoderStateCache(limit: 4, byteBudget: 2 * snapshot.byteCount)
        for name in ["one", "two", "three"] {
            bounded.store(snapshot, forReference: name, decoder: first)
        }
        XCTAssertEqual(bounded.count, 2)
        XCTAssertEqual(bounded.byteCount, 2 * snapshot.byteCount)
        XCTAssertNil(bounded.snapshot(forReference: "one", decoder: first))
        let tiny = Qwen3TTSPrimedDecoderStateCache(limit: 4, byteBudget: 1)
        tiny.store(snapshot, forReference: "one", decoder: first)
        tiny.store(snapshot, forReference: "two", decoder: first)
        XCTAssertEqual(tiny.count, 1)
        XCTAssertNotNil(tiny.snapshot(forReference: "two", decoder: first))

        Qwen3TTSPrimedDecoderStateCache.shared.store(snapshot, forReference: reference, decoder: first)
        XCTAssertEqual(Qwen3TTSPrimedDecoderStateCache.shared.count, 1)
        await Qwen3TTSMemoryCaches.clearAll()
        XCTAssertEqual(Qwen3TTSPrimedDecoderStateCache.shared.count, 0)
    }

    /// A-11 (RF-52): production puts exactly one space before every clone
    /// target; under the key a target whose first letter is Han or kana gets
    /// none, and every other target keeps its one space.
    func testTheCloneTargetSpaceFollowsTheFirstLettersScriptOnlyUnderTheKey() {
        let cases: [(text: String, production: String, spacedScriptsOnly: String)] = [
            ("Ce matin.", " Ce matin.", " Ce matin."),
            ("  Ce matin.", " Ce matin.", " Ce matin."),
            ("人人生而自由。", " 人人生而自由。", "人人生而自由。"),
            (" 人人生而自由。", " 人人生而自由。", "人人生而自由。"),
            ("「なんでもない」", " 「なんでもない」", "「なんでもない」"),
            ("ｶﾀｶﾅ", " ｶﾀｶﾅ", "ｶﾀｶﾅ"),
            ("3个苹果。", " 3个苹果。", "3个苹果。"),
            ("３月です。", " ３月です。", "３月です。"),
            ("\u{3000}こんにちは", " こんにちは", "こんにちは"),
            ("\n\t人人", " 人人", "人人"),
            ("々木さん", " 々木さん", "々木さん"),
            ("\u{20000}字", " \u{20000}字", "\u{20000}字"),
            ("2024 report.", " 2024 report.", " 2024 report."),
            ("\tCe matin.", " Ce matin.", " Ce matin."),
            ("안녕하세요.", " 안녕하세요.", " 안녕하세요."),
            ("Привет.", " Привет.", " Привет."),
            ("123", " 123", " 123"),
            ("", " ", " "),
        ]
        for item in cases {
            XCTAssertEqual(Qwen3ICLTargetText.boundaryMarked(item.text, onlyBeforeSpacedScripts: false),
                           item.production, item.text)
            XCTAssertEqual(Qwen3ICLTargetText.boundaryMarked(item.text, onlyBeforeSpacedScripts: true),
                           item.spacedScriptsOnly, item.text)
        }
    }

    // MARK: - Fixtures

    private func makeTinyTokenizer() throws -> Qwen3TTSSpeechTokenizer {
        let decoderConfig = try Qwen3DecoderPartitionTests.tinyDecoderConfig()
        var config = try JSONDecoder().decode(
            Qwen3TTSTokenizerConfig.self, from: Data("{}".utf8)
        )
        config.decoderConfig = decoderConfig
        config.decodeUpsampleRate = (decoderConfig.upsampleRates + decoderConfig.upsamplingRatios)
            .reduce(1, *)
        return Qwen3TTSSpeechTokenizer(config: config, includeEncoder: false)
    }

    /// Codes `[1, frameCount, 2]` (time-major, two code groups, codebook 16).
    /// Frames listed in `zeroFrames` carry first-group code 0.
    private func fixtureCodes(frameCount: Int, zeroFrames: Set<Int>) -> MLXArray {
        var values: [Int32] = []
        values.reserveCapacity(frameCount * 2)
        for frame in 0 ..< frameCount {
            let first = zeroFrames.contains(frame) ? 0 : (frame * 7) % 15 + 1
            values.append(Int32(first))
            values.append(Int32((frame * 5 + 3) % 16))
        }
        return MLXArray(values).reshaped(1, frameCount, 2)
    }
}
