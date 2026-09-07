import CryptoKit
import Foundation
import MLX
@testable import MLXAudioTTS
import XCTest

/// Explicit operator diagnosis only; absent input is SKIP, never model acceptance.
/// The existing external resource supervisor owns process limits and provenance.
/// This test never samples, decodes audio, downloads weights or modifies the model.
final class Qwen3TalkerReplayDiagnosticTests: XCTestCase {
    private struct Input: Decodable {
        let modelDirectory: String
        let modelFiles: [String: String]
        let text: String
        let textSHA256: String
        let instruction: String
        let instructionSHA256: String
        let language: String
        let speaker: String
        let tracePath: String
        let traceSHA256: String
        let outputDirectory: String
        let frameLimit: Int
        let expectedPrefixTokens: Int
        let expectedTextTokens: Int
        let freshPrefixFrames: [Int]
    }

    @MainActor
    func testRetainedCodeTeacherForcing() async throws {
        guard let path = ProcessInfo.processInfo.environment["VOCELLO_TEST_TALKER_REPLAY_INPUT"] else {
            throw XCTSkip("Explicit private replay input required; no model is a CI prerequisite")
        }
        let inputData = try Data(contentsOf: URL(fileURLWithPath: path))
        let input = try JSONDecoder().decode(Input.self, from: inputData)
        try require((1...600).contains(input.frameLimit), "Frame bound")
        try require(input.freshPrefixFrames.count <= 8, "Fresh-prefix bound")
        try require(Set(input.freshPrefixFrames).count == input.freshPrefixFrames.count,
                    "Duplicate fresh-prefix frame")
        try require(input.freshPrefixFrames.allSatisfy { (0..<input.frameLimit).contains($0) },
                    "Fresh-prefix range")
        try require(sha(Data(input.text.utf8)) == input.textSHA256, "Text identity")
        try require(sha(Data(input.instruction.utf8)) == input.instructionSHA256, "Instruction identity")
        let modelURL = URL(fileURLWithPath: input.modelDirectory, isDirectory: true)
        try require(input.modelFiles.keys.contains("config.json") &&
                    input.modelFiles.keys.contains("model.safetensors") &&
                    input.modelFiles.keys.contains("tokenizer.json"), "Model inventory")
        for (file, expected) in input.modelFiles {
            try require(!file.hasPrefix("/") && !file.split(separator: "/").contains(".."), "Model path")
            try require(try fileSHA(modelURL.appendingPathComponent(file)) == expected, "Model identity")
        }
        let trace = try Data(contentsOf: URL(fileURLWithPath: input.tracePath))
        try require(sha(trace) == input.traceSHA256, "Trace identity")
        let frames = try Self.decodeTrace(trace)
        try require(frames.count >= input.frameLimit, "Trace too short")
        let outputURL = URL(fileURLWithPath: input.outputDirectory, isDirectory: true)
        try require(!FileManager.default.fileExists(atPath: outputURL.path), "Refuse overwrite")
        try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: false)
        let provenance: [String: Any] = ["inputSHA256": sha(inputData), "traceSHA256": input.traceSHA256,
            "modelFiles": input.modelFiles, "textSHA256": input.textSHA256,
            "instructionSHA256": input.instructionSHA256, "promotionAuthority": false,
            "method": "teacher-forced-raw-talker-logits-not-sampler-probabilities"]
        try write(provenance, to: outputURL.appendingPathComponent("identity.json"))

        let model = try await Qwen3TTSModel.fromPreparedDirectory(modelURL, modelRepo: "local-diagnostic",
            loadBehavior: QwenPreparedLoadBehavior(trustPreparedCheckpoint: true,
                preparedDirectoryAlreadyValidated: true, loadSpeakerEncoder: false,
                loadSpeechTokenizerEncoder: false, skipSpeechTokenizerEval: true))
        let prepared = try model.prepareCustomVoiceInputs(text: input.text, language: input.language,
            speaker: input.speaker, instruct: input.instruction)
        try require(prepared.targetTokenCount == input.expectedTextTokens, "Text token identity")
        try require(prepared.inputEmbeds.dim(1) == input.expectedPrefixTokens, "Prefix identity")
        let config = try XCTUnwrap(model.config.talkerConfig)
        let cache = model.talker.makeCache()
        var current = prepared.inputEmbeds
        var history = [prepared.inputEmbeds]
        var observations: [[String: Any]] = []
        for frame in 0..<input.frameLimit {
            try Task.checkCancellation()
            let (logits, _) = model.talker(current, cache: cache)
            let raw = logits[0, -1, 0...].asType(.float32)
            eval(raw)
            let values = raw.asArray(Float.self)
            try require(values.allSatisfy(\.isFinite), "Non-finite Talker logits")
            let inspect = frame % 25 == 0 || input.freshPrefixFrames.contains(frame) ||
                ((350...550).contains(frame) && frame % 5 == 0)
            if inspect {
                var row = Self.statistics(values, selected: Int(frames[frame][0]), eos: config.codecEosTokenId)
                row["frame"] = frame
                row["cacheOffset"] = cache.first?.offset ?? -1
                row["textTokensRemaining"] = max(0, prepared.trailingTextHidden.dim(1) - frame)
                if input.freshPrefixFrames.contains(frame) {
                    // Same original history, fresh cache; no new sequence or random draw.
                    let complete = concatenated(history, axis: 1)
                    let (freshLogits, _) = model.talker(complete, cache: model.talker.makeCache())
                    let fresh = freshLogits[0, -1, 0...].asType(.float32)
                    eval(fresh)
                    let freshValues = fresh.asArray(Float.self)
                    try require(freshValues.allSatisfy(\.isFinite), "Non-finite fresh-prefix logits")
                    row["freshPrefix"] = Self.statistics(freshValues,
                        selected: Int(frames[frame][0]), eos: config.codecEosTokenId)
                    row["maximumAbsoluteLogitDifference"] = zip(values, freshValues)
                        .map { abs(Double($0) - Double($1)) }.max() ?? 0
                    row["freshPrefixLength"] = complete.dim(1)
                }
                observations.append(row)
                try write(["status": "in_progress", "rows": observations],
                          to: outputURL.appendingPathComponent("observations.json"))
            }
            let codes = frames[frame]
            var embedding = model.talker.getInputEmbeddings()(MLXArray([codes[0]]).reshaped(1, 1))
            for group in 1..<codes.count {
                embedding = embedding + model.talker.codePredictor.codecEmbedding[group - 1](
                    MLXArray([codes[group]]).reshaped(1, 1))
            }
            let text = frame < prepared.trailingTextHidden.dim(1)
                ? prepared.trailingTextHidden[0..., frame..<(frame + 1), 0...]
                : prepared.ttsPadEmbed
            current = text + embedding
            eval(current)
            history.append(current)
            if frame % 25 == 0 {
                Memory.clearCache()
                print("TALKER_REPLAY completed_frames=\(frame + 1)")
                fflush(stdout)
            }
        }
        try require(try fileSHA(URL(fileURLWithPath: input.tracePath)) == input.traceSHA256, "Trace drift")
        try write(["status": "diagnostic_complete_not_audio_acceptance", "rows": observations,
                   "framesInspected": input.frameLimit, "initialPrefixTokens": prepared.inputEmbeds.dim(1),
                   "trailingTextTokens": prepared.trailingTextHidden.dim(1)],
                  to: outputURL.appendingPathComponent("observations.json"))
    }

    func testTraceValidationAndRawProbabilityStatistics() throws {
        XCTAssertThrowsError(try Self.decodeTrace(Data()))
        XCTAssertThrowsError(try Self.decodeTrace(Data(repeating: 0, count: 82)))
        let stats = Self.statistics([0, 0, 0, 0], selected: 0, eos: 3)
        XCTAssertEqual(stats["rawEOSProbability"] as? Double, 0.25)
        XCTAssertEqual(stats["rawSelectedProbability"] as? Double, 0.25)
        XCTAssertEqual(stats["rawEntropyBits"] as? Double, 2)
        let shifted = Self.statistics([1_000, 1_000, 1_000, 1_000], selected: 0, eos: 3)
        XCTAssertEqual(shifted["rawEOSProbability"] as? Double, 0.25)
        let peaked = Self.statistics([10, 0, -10, -20], selected: 0, eos: 3)
        XCTAssertGreaterThan(try XCTUnwrap(peaked["rawSelectedProbability"] as? Double), 0.999)
        XCTAssertLessThan(try XCTUnwrap(peaked["rawEOSProbability"] as? Double), 1e-12)
        XCTAssertEqual(peaked["rawSelectedRank"] as? Int, 1)
        XCTAssertEqual(peaked["rawEOSRank"] as? Int, 4)
    }

    func testTraceAcceptsExactFramesAndRejectsDamagedEvidence() throws {
        var valid = Data("VQCT".utf8)
        for value: UInt32 in [1, 1, 0] {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { valid.append(contentsOf: $0) }
        }
        valid.append(contentsOf: [16, 0])
        for value in 0..<16 {
            var little = Int32(value).littleEndian
            withUnsafeBytes(of: &little) { valid.append(contentsOf: $0) }
        }
        XCTAssertEqual(try Self.decodeTrace(valid), [(0..<16).map(Int32.init)])
        XCTAssertThrowsError(try Self.decodeTrace(valid.dropLast()))
        for (offset, byte) in [(4, UInt8(2)), (8, 0), (12, 1), (16, 15), (21, 255)] {
            var damaged = valid
            damaged[offset] = byte
            XCTAssertThrowsError(try Self.decodeTrace(damaged))
        }
    }

    private static func statistics(_ values: [Float], selected: Int, eos: Int) -> [String: Any] {
        let maximum = Double(values.max()!)
        let exps = values.map { exp(Double($0) - maximum) }
        let total = exps.reduce(0, +)
        let probabilities = exps.map { $0 / total }
        return ["rawEOSProbability": probabilities[eos], "rawSelectedProbability": probabilities[selected],
                "rawEOSRank": 1 + values.filter { $0 > values[eos] }.count,
                "rawSelectedRank": 1 + values.filter { $0 > values[selected] }.count,
                "rawMaximumProbability": probabilities.max()!,
                "rawEntropyBits": -probabilities.filter { $0 > 0 }.reduce(0) { $0 + $1 * log2($1) }]
    }

    private static func decodeTrace(_ data: Data) throws -> [[Int32]] {
        func u32(_ offset: Int) -> UInt32 {
            data.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(fromByteOffset: offset, as: UInt32.self)) }
        }
        guard data.count >= 16, data.prefix(4) == Data("VQCT".utf8), u32(4) == 1,
              u32(12) == 0, (1...8192).contains(Int(u32(8))),
              data.count == 16 + Int(u32(8)) * 66 else { throw ProbeError.invalid("Trace format") }
        return try (0..<Int(u32(8))).map { frame in
            let offset = 16 + frame * 66
            guard data[offset] == 16, data[offset + 1] == 0 else { throw ProbeError.invalid("Code groups") }
            let codes = (0..<16).map { Int32(bitPattern: u32(offset + 2 + $0 * 4)) }
            guard codes.enumerated().allSatisfy({ $0.element >= 0 && $0.element < ($0.offset == 0 ? 4096 : 2048) })
            else { throw ProbeError.invalid("Code range") }
            return codes
        }
    }

    private enum ProbeError: Error { case invalid(String) }
    private func require(_ condition: Bool, _ reason: String) throws {
        if !condition { throw ProbeError.invalid(reason) }
    }
    private func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private func fileSHA(_ url: URL) throws -> String {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        var hasher = SHA256()
        while let block = try file.read(upToCount: 1024 * 1024), !block.isEmpty { hasher.update(data: block) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
    private func write(_ value: [String: Any], to url: URL) throws {
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(to: url, options: .atomic)
    }
}
