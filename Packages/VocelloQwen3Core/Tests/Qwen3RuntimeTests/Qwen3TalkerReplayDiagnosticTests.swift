import CryptoKit
import Foundation
import MLX
@testable import MLXAudioTTS
import MLXLMCommon
import XCTest

/// Explicit operator diagnosis only; absent input is SKIP, never model acceptance.
/// The existing external resource supervisor owns process limits and provenance.
/// Default input teacher-forces retained codes; productionCapture explicitly opts
/// into bounded synthesis. Neither route downloads weights or qualifies audio.
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
        let allocatorPolicyPath: String
        let allocatorPolicySHA256: String
        let productionCapture: ProductionCapture?
        let predictorFrames: [Int]?
    }

    private struct ProductionCapture: Decodable {
        let seed: UInt64
        let temperature: Float
        let topP: Float
        let topK: Int
        let minP: Float
        let subtalkerTemperature: Float
        let subtalkerTopP: Float
        let subtalkerTopK: Int
        let subtalkerMinP: Float
        let repetitionPenalty: Float
        let maximumCodecTokens: Int
        let streamingInterval: Double
        let observe: Bool
        let inspectFrames: [Int]
    }

    @MainActor
    func testRetainedCodeTeacherForcing() async throws {
        guard let path = ProcessInfo.processInfo.environment["VOCELLO_TEST_TALKER_REPLAY_INPUT"] else {
            throw XCTSkip("Explicit private replay input required; no model is a CI prerequisite")
        }
        let inputData = try Data(contentsOf: URL(fileURLWithPath: path))
        let input = try JSONDecoder().decode(Input.self, from: inputData)
        let policyData = try Data(contentsOf: URL(fileURLWithPath: input.allocatorPolicyPath))
        try require(sha(policyData) == input.allocatorPolicySHA256, "Allocator policy identity")
        let policy = try JSONDecoder().decode(DiagnosticAllocatorPolicy.self, from: policyData)
        try policy.validate()
        let allocator = try DiagnosticAllocatorScope(policy)
        defer { allocator.restore() }
        try require((1...600).contains(input.frameLimit), "Frame bound")
        try require(input.freshPrefixFrames.count <= 8, "Fresh-prefix bound")
        try require(Set(input.freshPrefixFrames).count == input.freshPrefixFrames.count,
                    "Duplicate fresh-prefix frame")
        try require(input.freshPrefixFrames.allSatisfy { (0..<input.frameLimit).contains($0) },
                    "Fresh-prefix range")
        try require((input.predictorFrames?.count ?? 0) <= 4 &&
            (input.predictorFrames ?? []).allSatisfy { (0..<input.frameLimit).contains($0) }, "Predictor frame bound")
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
            "allocatorPolicySHA256": input.allocatorPolicySHA256,
            "allocatorCacheLimitBytesBeforeLoad": Memory.cacheLimit,
            "instructionSHA256": input.instructionSHA256, "promotionAuthority": false,
            "method": input.productionCapture == nil ? "teacher-forced-raw-talker-logits-not-sampler-probabilities"
                : "bounded-production-producer-observer-parity-required"]
        try write(provenance, to: outputURL.appendingPathComponent("identity.json"))

        // Keep model/graph ownership in the callee: its frame is released before
        // the outer allocator scope clears cache and restores process settings.
        try await inspectModel(input: input, frames: frames, policy: policy, outputURL: outputURL)
    }

    @MainActor
    private func inspectModel(input: Input, frames: [[Int32]], policy: DiagnosticAllocatorPolicy,
                              outputURL: URL) async throws {
        let modelURL = URL(fileURLWithPath: input.modelDirectory, isDirectory: true)
        let model = try await Qwen3TTSModel.fromPreparedDirectory(modelURL, modelRepo: "local-diagnostic",
            loadBehavior: QwenPreparedLoadBehavior(trustPreparedCheckpoint: true,
                preparedDirectoryAlreadyValidated: true, loadSpeakerEncoder: false,
                loadSpeechTokenizerEncoder: false, skipSpeechTokenizerEval: true))
        let prepared = try model.prepareCustomVoiceInputs(text: input.text, language: input.language,
            speaker: input.speaker, instruct: input.instruction)
        try require(prepared.targetTokenCount == input.expectedTextTokens, "Text token identity")
        try require(prepared.inputEmbeds.dim(1) == input.expectedPrefixTokens, "Prefix identity")
        if let capture = input.productionCapture {
            try await captureProduction(model, input: input, capture: capture, policy: policy, output: outputURL)
            return
        }
        let config = try XCTUnwrap(model.config.talkerConfig)
        var predictorPlan: CodePredictorCompiledPlan?
        let cache = model.talker.makeCache()
        var current = prepared.inputEmbeds
        var history = [prepared.inputEmbeds]
        var observations: [[String: Any]] = []
        for frame in 0..<input.frameLimit {
            try Task.checkCancellation()
            let (logits, hidden) = model.talker(current, cache: cache)
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
            if input.predictorFrames?.contains(frame) == true {
                let predictor = model.talker.codePredictor
                let codeHidden = hidden[0..., (-1)..., 0...]
                let code0 = model.talker.getInputEmbeddings()(MLXArray([codes[0]]).reshaped(1, 1))
                if predictorPlan == nil { predictorPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: codeHidden.dtype) }
                let eagerCache = predictor.makeCache()
                let constants = CodePredictorStepConstants()
                var eager: [MLXArray] = [], compiled: [MLXArray] = []
                for pass in 0..<15 {
                    let token = MLXArray([codes[pass]]).reshaped(1, 1)
                    let embed = pass == 0 ? concatenated([codeHidden, code0], axis: 1)
                        : predictor.codecEmbedding[pass - 1](token)
                    eager.append(predictor(embed, cache: eagerCache, generationStep: pass, stepConstants: constants).0)
                    compiled.append(predictorPlan!.run(pass: pass,
                        codeHidden: pass == 0 ? codeHidden : nil,
                        code0Embed: pass == 0 ? code0 : nil, token: pass == 0 ? nil : token))
                }
                eval(eager + compiled)
                let rows: [[String: Any]] = (0..<15).map { pass in
                    let a = eager[pass].asType(.float32).asArray(Float.self)
                    let b = compiled[pass].asType(.float32).asArray(Float.self)
                    return ["pass": pass, "dtype": String(describing: compiled[pass].dtype),
                        "finite": a.allSatisfy(\.isFinite) && b.allSatisfy(\.isFinite),
                        "maximumAbsoluteLogitDifference": zip(a,b).map { abs($0-$1) }.max()!,
                        "eagerTop": a.indices.max(by: { a[$0] < a[$1] })!,
                        "compiledTop": b.indices.max(by: { b[$0] < b[$1] })!,
                        "eagerLogits": a, "compiledLogits": b]
                }
                try write(["frame": frame, "method": "forced-codes-all15-passes-no-sampling",
                           "rows": rows], to: outputURL.appendingPathComponent("predictor-\(frame).json"))
            }
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

    @MainActor
    private func captureProduction(_ model: Qwen3TTSModel, input: Input, capture: ProductionCapture,
        policy: DiagnosticAllocatorPolicy, output: URL) async throws {
        try require(capture.maximumCodecTokens == 2048 && capture.inspectFrames.count <= 16 &&
            capture.inspectFrames.allSatisfy { (0..<input.frameLimit).contains($0) }, "Capture bounds")
        let buffer = SamplingCaptureBuffer(output: output, limit: input.frameLimit,
            inspectFrames: Set(capture.inspectFrames), observe: capture.observe,
            eos: try XCTUnwrap(model.config.talkerConfig).codecEosTokenId)
        if capture.observe {
            model.samplerObserver = { raw, processed, key, token in
                MainActor.assumeIsolated { buffer.pending.append((raw, processed, key, token)) }
            }
        }
        defer { model.samplerObserver = nil; buffer.pending.removeAll() }
        let sampling = Qwen3RequestSamplingPolicy(effectiveSeed: capture.seed,
            talker: Qwen3SamplingStage(temperature: capture.temperature, topP: capture.topP, topK: capture.topK, minP: capture.minP),
            subtalker: Qwen3SamplingStage(temperature: capture.subtalkerTemperature, topP: capture.subtalkerTopP,
                topK: capture.subtalkerTopK, minP: capture.subtalkerMinP),
            repetitionPenalty: capture.repetitionPenalty, maximumCodecTokens: capture.maximumCodecTokens)
        var terminal = "unexpected"
        do {
            let finish = try await model.produceCustomVoice(text: input.text, language: input.language,
                speaker: input.speaker, instruct: input.instruction, generationParameters: model.defaultGenerationParameters,
                samplingPolicy: sampling, memoryPolicy: Qwen3RequestMemoryPolicy(
                    clearCacheOnStreamChunkEmit: policy.clearCacheOnStreamChunkEmit,
                    tokenMemoryClearCadence: policy.tokenMemoryClearCadence, talkerKVGeneratedWindow: nil),
                streamingInterval: capture.streamingInterval, customVoiceProfile: nil, streamStepEvalPolicy: nil,
                generationSpeedProfile: nil, memoryClearCadence: nil, enableChunkTimings: false,
                enableCodecTrace: true, sink: { event in try await buffer.receive(event) })
            terminal = String(describing: finish)
        } catch SamplingCaptureBuffer.Stop.frameBound {
            terminal = "diagnostic_frame_bound_not_eos"
        }
        try write(["terminal": terminal, "framesCaptured": buffer.frames, "observed": capture.observe,
                   "audioSamplesDrained": buffer.audioSamples, "promotionAuthority": false],
                  to: output.appendingPathComponent("capture-summary.json"))
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

    @MainActor
    func testCaptureUsesLastPositionAndRejectsIncompleteFrame() throws {
        // Prompt prefill and predictor pass zero return multiple positions.
        // Flattening the whole tensor would report a different distribution.
        let raw = MLXArray([Float](arrayLiteral: 100, 0, 0, 0, 0, 1, 2, 3)).reshaped(1, 2, 4)
        XCTAssertEqual(try SamplingCaptureBuffer.lastPosition(raw, vocabulary: 4), [0, 1, 2, 3])
        XCTAssertEqual(try SamplingCaptureBuffer.lastPosition(raw[0..., 1..., 0...], vocabulary: 4), [0, 1, 2, 3])
        XCTAssertThrowsError(try SamplingCaptureBuffer.lastPosition(raw, vocabulary: 3))
        let buffer = SamplingCaptureBuffer(output: FileManager.default.temporaryDirectory,
            limit: 1, inspectFrames: [], observe: true, eos: 3)
        XCTAssertThrowsError(try buffer.receive(.token(0))) { error in
            guard case SamplingCaptureBuffer.Stop.invalidObservation = error else {
                return XCTFail("Must classify capture failure, not allocator failure")
            }
        }
    }

    func testAllocatorEstablishmentAndRestorationOnEveryTerminalPath() throws {
        let originalCache = Memory.cacheLimit
        let originalMemory = Memory.memoryLimit
        let policy = DiagnosticAllocatorPolicy(schemaVersion: 1, resolver: "NativeMemoryPolicyResolver",
            name: "synthetic-fixture-not-host-policy", cacheLimitBytes: 1024 * 1024,
            memoryLimitBytes: nil, tokenMemoryClearCadence: 50, clearCacheOnStreamChunkEmit: true)
        func operation(_ failure: Error?) throws {
            let scope = try DiagnosticAllocatorScope(policy)
            defer { scope.restore(); scope.restore() }
            XCTAssertEqual(Memory.cacheLimit, policy.cacheLimitBytes, "Must precede first load")
            XCTAssertEqual(Memory.memoryLimit, originalMemory, "No invented hard ceiling")
            if let failure { throw failure }
        }
        try operation(nil)
        XCTAssertEqual(Memory.cacheLimit, originalCache)
        for failure: Error in [CancellationError(), ProbeError.invalid("Observation failure")] {
            XCTAssertThrowsError(try operation(failure))
            XCTAssertEqual(Memory.cacheLimit, originalCache)
            XCTAssertEqual(Memory.memoryLimit, originalMemory)
        }
        let invalid = DiagnosticAllocatorPolicy(schemaVersion: 2, resolver: "copied-defaults",
            name: "invalid", cacheLimitBytes: 0, memoryLimitBytes: nil,
            tokenMemoryClearCadence: 0, clearCacheOnStreamChunkEmit: true)
        XCTAssertThrowsError(try DiagnosticAllocatorScope(invalid))
        XCTAssertEqual(Memory.cacheLimit, originalCache)
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

@MainActor
private final class SamplingCaptureBuffer {
    enum Stop: Error { case frameBound, invalidObservation }
    let output: URL
    let limit: Int
    let inspectFrames: Set<Int>
    let observe: Bool
    let eos: Int
    var frames = 0
    var audioSamples = 0
    var pending: [(MLXArray, MLXArray, MLXArray?, MLXArray)] = []
    init(output: URL, limit: Int, inspectFrames: Set<Int>, observe: Bool, eos: Int) {
        self.output = output; self.limit = limit; self.inspectFrames = inspectFrames; self.observe = observe; self.eos = eos
    }
    func receive(_ event: Qwen3MaterializedGenerationEvent) throws {
        switch event {
        case .token:
            if observe {
                guard pending.count == 16 else { throw Stop.invalidObservation }
                // Called only after the producer's normal frame eval boundary.
                var rows: [[String: Any]] = []
                for (pass, value) in pending.enumerated() {
                    let (raw, processed, key, token) = value
                    var row: [String: Any] = ["pass": pass, "selected": token.item(Int32.self),
                        "dtype": String(describing: processed.dtype),
                        "rawShape": raw.shape, "rawPosition": "last",
                        "key": key?.asArray(UInt32.self) ?? []]
                    if pass == 0 || inspectFrames.contains(frames) {
                        let values = processed.asType(.float32).asArray(Float.self)
                        let rawValues = try Self.lastPosition(raw, vocabulary: values.count)
                        row["eligibleTokenCount"] = values.filter(\.isFinite).count
                        row["hasNaN"] = values.contains(where: \.isNaN)
                        if pass == 0 {
                            row["processedStatistics"] = statistics(values, selected: Int(token.item(Int32.self)))
                            row["rawStatistics"] = statistics(rawValues, selected: Int(token.item(Int32.self)))
                        }
                        if inspectFrames.contains(frames) {
                            row["rawLogits"] = rawValues
                            row["processedLogits"] = values.map { $0.isFinite ? $0 as Any : NSNull() }
                        }
                    }
                    rows.append(row)
                }
                try save(["schemaVersion": 2, "frame": frames, "rows": rows], name: "sampling-\(frames).json")
                pending.removeAll(keepingCapacity: true)
            }
        case .codecFrame(let codes):
            try save(["frame": frames, "codes": codes], name: "codes-\(frames).json")
            frames += 1
            if frames % 25 == 0 { print("SAMPLING_CAPTURE frames=\(frames)"); fflush(stdout) }
            if frames >= limit { throw Stop.frameBound }
        case .audio(let samples): audioSamples += samples.count
        default: break
        }
    }
    static func lastPosition(_ raw: MLXArray, vocabulary: Int) throws -> [Float] {
        guard raw.ndim == 3, raw.dim(0) == 1, raw.dim(1) > 0, raw.dim(2) == vocabulary else {
            throw Stop.invalidObservation
        }
        return raw[0, -1, 0...].asType(.float32).asArray(Float.self)
    }
    private func save(_ object: [String: Any], name: String) throws {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]).write(
            to: output.appendingPathComponent(name), options: .atomic)
    }
    private func statistics(_ values: [Float], selected: Int) -> [String: Any] {
        let maxValue = values.max()!
        let weights = values.map { exp(Double($0 - maxValue)) }
        let sum = weights.reduce(0, +)
        return ["selectedProbability": weights[selected] / sum,
                "eosProbability": weights[eos] / sum,
                "selectedRank": 1 + values.filter { $0 > values[selected] }.count,
                "maximumProbability": weights.max()! / sum,
                "entropyBits": -weights.filter { $0 > 0 }.map { let p = $0 / sum; return p * log2(p) }.reduce(0, +)]
    }
}

/// Values are exported by the host resolver and digest-bound by the operator.
/// No tier defaults are defined in this test bundle.
struct DiagnosticAllocatorPolicy: Decodable {
    let schemaVersion: Int
    let resolver: String
    let name: String
    let cacheLimitBytes: Int
    let memoryLimitBytes: Int?
    let tokenMemoryClearCadence: Int
    let clearCacheOnStreamChunkEmit: Bool

    func validate() throws {
        guard schemaVersion == 1, resolver == "NativeMemoryPolicyResolver", !name.isEmpty,
              cacheLimitBytes > 0, tokenMemoryClearCadence > 0,
              memoryLimitBytes.map({ $0 >= cacheLimitBytes }) ?? true else {
            throw DiagnosticAllocatorScope.Failure.invalidPolicy
        }
    }
}

final class DiagnosticAllocatorScope {
    enum Failure: Error { case invalidPolicy, establishmentFailed }
    private let previousCache = Memory.cacheLimit
    private let previousMemory = Memory.memoryLimit
    private var restored = false

    init(_ policy: DiagnosticAllocatorPolicy) throws {
        try policy.validate()
        Memory.cacheLimit = policy.cacheLimitBytes
        if let limit = policy.memoryLimitBytes { Memory.memoryLimit = limit }
        guard Memory.cacheLimit == policy.cacheLimitBytes,
              policy.memoryLimitBytes.map({ Memory.memoryLimit == $0 }) ?? true else {
            restore()
            throw Failure.establishmentFailed
        }
    }

    func restore() {
        guard !restored else { return }
        Memory.clearCache()
        Memory.cacheLimit = previousCache
        Memory.memoryLimit = previousMemory
        restored = true
    }
}
