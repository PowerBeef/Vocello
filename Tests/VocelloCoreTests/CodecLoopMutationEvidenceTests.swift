import Foundation
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

/// The pure pieces of `vocello bench --codec-loop` (audio QC COD-LOOP, tier T2
/// of the 2026-09-25 audit): the job, the trace binding, the loop mutation (byte
/// for byte the Python builder's, on the shared fixture
/// `scripts/tests/fixtures/audio_qc_codec_loop.json`) and the limited WAV. No
/// model runs here; the decode is the codec replay's full arm.
final class CodecLoopMutationEvidenceTests: XCTestCase {
    private typealias Evidence = CodecLoopMutationEvidence
    private static let digest = String(repeating: "a", count: 64)

    private static var repositoryRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    /// The fixture's frames: frame f, codebook c holds (7f + 13c + (f * c mod 5))
    /// mod its codebook size.
    private static func fixtureFrames(_ count: Int) -> [[Int32]] {
        (0 ..< count).map { frame in
            (0 ..< 16).map { codebook in
                Int32((frame * 7 + codebook * 13 + (frame * codebook) % 5) % (codebook == 0 ? 4_096 : 2_048))
            }
        }
    }

    private static func recipe(
        _ variant: String, _ start: Int, _ span: Int, _ copies: Int, injector: String = Evidence.injector
    ) -> Evidence.Recipe {
        Evidence.Recipe(injector: injector, variant: variant, startFrame: start, spanFrames: span, extraCopies: copies)
    }

    func testLoopMutationMatchesThePythonBuildersSharedFixture() throws {
        let data = try Data(contentsOf: Self.repositoryRoot.appendingPathComponent(
            "scripts/tests/fixtures/audio_qc_codec_loop.json"
        ))
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let frames = Self.fixtureFrames(try XCTUnwrap(fixture["frameCount"] as? Int))
        let source = try Evidence.traceData(frames)
        XCTAssertEqual(Evidence.sha256(source), fixture["sourceTraceSHA256"] as? String)
        XCTAssertEqual(try Evidence.verifiedFrames(source, expectedSHA256: Evidence.sha256(source)), frames)
        let cases = try XCTUnwrap(fixture["cases"] as? [[String: Any]])
        XCTAssertEqual(cases.count, 4)
        for item in cases {
            let recipe = try JSONDecoder().decode(
                Evidence.Recipe.self,
                from: JSONSerialization.data(withJSONObject: try XCTUnwrap(item["recipe"]))
            )
            XCTAssertTrue(recipe.isWellFormed, recipe.variant)
            let mutated = try Evidence.mutated(frames, by: recipe)
            XCTAssertEqual(mutated.count, item["mutatedFrameCount"] as? Int, recipe.variant)
            XCTAssertEqual(
                Evidence.sha256(try Evidence.traceData(mutated)),
                item["mutatedTraceSHA256"] as? String,
                recipe.variant
            )
            guard recipe.variant != "sham" else {
                XCTAssertEqual(mutated, frames)
                continue
            }
            // The copy follows the span, so codebook 0 repeats with the span's period.
            let end = recipe.startFrame + recipe.spanFrames
            XCTAssertEqual(Array(mutated[end ..< end + recipe.spanFrames]), Array(frames[recipe.startFrame ..< end]))
            XCTAssertEqual(Array(mutated[(end + recipe.spanFrames)...]), Array(frames[end...]))
        }
    }

    func testRecipesAreShapedAndBounded() throws {
        XCTAssertTrue(Self.recipe("sham", 0, 0, 0).isWellFormed)
        XCTAssertTrue(Self.recipe("severe", 3, 32, 1).isWellFormed)
        let malformed = [
            Self.recipe("sham", 0, 4, 1), Self.recipe("severe", 0, 0, 1), Self.recipe("severe", 0, 32, 0),
            Self.recipe("severe", -1, 32, 1), Self.recipe("severe", 0, Evidence.maximumSpanFrames + 1, 1),
            Self.recipe("severe", 0, 32, Evidence.maximumExtraCopies + 1), Self.recipe("extreme", 0, 32, 1),
            Self.recipe("severe", 0, 32, 1, injector: "COD-SKIP@1"),
        ]
        for recipe in malformed {
            XCTAssertFalse(recipe.isWellFormed, "\(recipe)")
        }
        let frames = Self.fixtureFrames(10)
        XCTAssertThrowsError(try Evidence.mutated(frames, by: Self.recipe("mild", 8, 4, 1))) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidRecipe)
        }
        XCTAssertThrowsError(try Evidence.mutated(frames, by: Self.recipe("sham", 0, 4, 1))) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidRecipe)
        }
        XCTAssertEqual(try Evidence.mutated(frames, by: Self.recipe("mild", 6, 4, 2)).count, 18)
    }

    func testJobDecodesBoundedSafeUniqueItemsWithWellFormedRecipes() throws {
        func item(_ id: String, _ path: String = "traces/a.bin",
                  sha256: String = CodecLoopMutationEvidenceTests.digest,
                  recipe: CodecLoopMutationEvidence.Recipe = CodecLoopMutationEvidenceTests.recipe("severe", 4, 32, 1))
            -> [String: Any] {
            ["id": id, "tracePath": path, "traceSHA256": sha256,
             "recipe": ["injector": recipe.injector, "variant": recipe.variant, "startFrame": recipe.startFrame,
                        "spanFrames": recipe.spanFrames, "extraCopies": recipe.extraCopies]]
        }
        func job(_ items: [[String: Any]], kind: String = Evidence.jobKind, schemaVersion: Int = 1,
                 sampleRate: Int = 24_000, tokenizer: String? = nil) throws -> Data {
            var value: [String: Any] = ["schemaVersion": schemaVersion, "kind": kind, "sampleRate": sampleRate,
                                        "items": items]
            if let tokenizer { value["tokenizerSHA256"] = tokenizer }
            return try JSONSerialization.data(withJSONObject: value)
        }
        let decoded = try Evidence.decodeJob(job([item("cl-1")], tokenizer: Self.digest))
        XCTAssertEqual(decoded.items.map(\.id), ["cl-1"])
        XCTAssertEqual(decoded.items.first?.recipe, Self.recipe("severe", 4, 32, 1))
        XCTAssertEqual(decoded.tokenizerSHA256, Self.digest)
        XCTAssertNil(try Evidence.decodeJob(job([item("cl-1")])).tokenizerSHA256)

        let refused: [(Data, Evidence.EvidenceError)] = [
            (try job([item("a")], kind: "audio-qc-n2-roundtrip-job"), .invalidJob),
            (try job([item("a")], schemaVersion: 2), .invalidJob),
            (try job([item("a")], sampleRate: 16_000), .invalidJob),
            (try job([item("a")], tokenizer: "abc"), .invalidJob),
            (try job([]), .invalidJob),
            (Data("not json".utf8), .invalidJob),
            (try job([item(".hidden")]), .invalidItem),
            (try job([item("a", "/abs/a.bin")]), .invalidItem),
            (try job([item("a", "../a.bin")]), .invalidItem),
            (try job([item("a", sha256: "abc")]), .invalidItem),
            (try job([item("a", recipe: Self.recipe("severe", 4, 0, 1))]), .invalidRecipe),
            (try job([item("Loop"), item("loop")]), .duplicateItem),
            (Data(count: Evidence.maximumJobBytes + 1), .inputOutOfBounds),
        ]
        for (data, expected) in refused {
            XCTAssertThrowsError(try Evidence.decodeJob(data)) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, expected)
            }
        }
    }

    func testTraceBindingRefusesAnotherDigestAnIncompleteTraceOrForeignCodes() throws {
        let frames = Self.fixtureFrames(5)
        let data = try Evidence.traceData(frames)
        XCTAssertThrowsError(try Evidence.verifiedFrames(data, expectedSHA256: Self.digest)) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .digestMismatch)
        }
        var foreign = frames
        foreign[2][0] = 4_096
        let refused = [
            StartupReliabilityDiagnosticEvidence.encode(VocelloQwen3CodecTrace(frames: frames, droppedFrameCount: 1)),
            StartupReliabilityDiagnosticEvidence.encode(VocelloQwen3CodecTrace(frames: foreign, droppedFrameCount: 0)),
            StartupReliabilityDiagnosticEvidence.encode(
                VocelloQwen3CodecTrace(frames: frames.map { Array($0.prefix(8)) }, droppedFrameCount: 0)
            ),
            Data("VQCT".utf8),
        ]
        for trace in refused {
            XCTAssertThrowsError(try Evidence.verifiedFrames(trace, expectedSHA256: Evidence.sha256(trace))) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidTrace)
            }
        }
        XCTAssertThrowsError(try Evidence.traceData([])) {
            XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidTrace)
        }
    }

    func testDecodeRangesCoverTheTraceInTheProductionChunk() {
        XCTAssertEqual(
            Evidence.decodeRanges(frameCount: 60).map { [$0.start, $0.endExclusive] },
            [[0, 25], [25, 50], [50, 60]]
        )
        XCTAssertEqual(Evidence.decodeRanges(frameCount: 25).map { [$0.start, $0.endExclusive] }, [[0, 25]])
        XCTAssertTrue(Evidence.decodeRanges(frameCount: 0).isEmpty)
    }

    func testLimitedWAVIsOnePCM16SamplePerDecodedSample() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("codec-loop-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("loop.wav")
        let samples: [Float] = (0 ..< 2_400).map { Float(sin(Double($0) * 0.05) * 0.5) }
        let written = try Evidence.writeLimitedWAV(samples: samples, sampleRate: 24_000, to: url)
        let data = try Data(contentsOf: url)
        XCTAssertEqual(written.sha256, Evidence.sha256(data))
        XCTAssertEqual(written.byteCount, data.count)
        XCTAssertEqual(written.sampleCount, samples.count)
        XCTAssertEqual(try CodecRoundTripEvidence.monoPCM16Samples(wav: data).count, samples.count)
        for (bad, rate) in [(samples, 16_000), ([Float.nan], 24_000), ([], 24_000)] as [([Float], Int)] {
            XCTAssertThrowsError(try Evidence.writeLimitedWAV(samples: bad, sampleRate: rate, to: url)) {
                XCTAssertEqual($0 as? Evidence.EvidenceError, .invalidOutput)
            }
        }
    }
}
