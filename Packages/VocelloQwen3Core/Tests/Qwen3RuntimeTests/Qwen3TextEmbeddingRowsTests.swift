import Foundation
import MLX
import MLXAudioCore
@testable import MLXAudioTTS
import MLXNN
import XCTest

/// RF-47: the text embedding read by row from the checkpoint file must give
/// exactly the bits of the embedding layer loaded from the same file, and a
/// talker built over the reader must hold no text-embedding parameter.
final class Qwen3TextEmbeddingRowsTests: XCTestCase {
    private static let prefix = "talker.model.text_embedding"
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("qwen3-text-rows-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func bits(_ array: MLXArray) -> [UInt32] {
        array.asType(.float32).asArray(Float.self).map(\.bitPattern)
    }

    /// Writes a packed table beside unrelated tensors, as a checkpoint has
    /// them, and returns the layer the loader would build from it.
    private func writeQuantizedTable(
        rows: Int, dimensions: Int, bits: Int, floatType: DType
    ) throws -> (file: URL, layer: QuantizedEmbedding) {
        let weight = MLXRandom.normal([rows, dimensions], key: MLXRandom.key(UInt64(rows + bits))) * 0.1
        let (packed, scales, biases) = MLX.quantized(weight, groupSize: 64, bits: bits)
        let layer = QuantizedEmbedding(
            weight: packed,
            scales: scales.asType(floatType),
            biases: biases?.asType(floatType),
            groupSize: 64,
            bits: bits
        )
        eval(layer.parameters())
        let file = directory.appendingPathComponent("model-\(bits)-\(floatType).safetensors")
        try MLX.save(
            arrays: [
                "talker.model.codec_embedding.weight": MLXRandom.normal([7, 5]),
                "\(Self.prefix).weight": layer.weight,
                "\(Self.prefix).scales": layer.scales,
                "\(Self.prefix).biases": try XCTUnwrap(layer.biases),
                "talker.model.norm.weight": MLXArray.ones([dimensions]),
            ],
            url: file
        )
        return (file, layer)
    }

    func testPackedRowsFromTheFileMatchTheEmbeddingLayerBitForBit() throws {
        for (tableBits, floatType) in [(8, DType.bfloat16), (4, .float16), (8, .float32)] {
            let (file, layer) = try writeQuantizedTable(
                rows: 300, dimensions: 256, bits: tableBits, floatType: floatType
            )
            let rows = try XCTUnwrap(Qwen3TextEmbeddingRows.open(
                weightsFile: file, tensorPrefix: Self.prefix, rowCount: 300, dimensions: 256,
                quantization: .init(groupSize: 64, bits: tableBits)
            ))
            // First row, last row, a repeat, and a two-dimensional id array.
            let ids = MLXArray([Int32(0), 299, 17, 17, 128, 1]).reshaped(2, 3)
            let fromFile = try rows.embed(ids)
            let fromLayer = layer(ids)
            eval(fromFile, fromLayer)
            XCTAssertEqual(fromFile.shape, [2, 3, 256])
            XCTAssertEqual(fromFile.shape, fromLayer.shape)
            XCTAssertEqual(fromFile.dtype, fromLayer.dtype, "\(tableBits)-bit, \(floatType)")
            XCTAssertEqual(bits(fromFile), bits(fromLayer), "\(tableBits)-bit, \(floatType)")
        }
    }

    func testAFloatTableIsReadByRowToo() throws {
        let table = (MLXRandom.normal([50, 32], key: MLXRandom.key(5)) * 0.1).asType(.float16)
        eval(table)
        let file = directory.appendingPathComponent("float.safetensors")
        try MLX.save(arrays: ["\(Self.prefix).weight": table], url: file)
        let rows = try XCTUnwrap(Qwen3TextEmbeddingRows.open(
            weightsFile: file, tensorPrefix: Self.prefix, rowCount: 50, dimensions: 32,
            quantization: nil
        ))
        let ids = MLXArray([Int32(49), 0, 12]).reshaped(1, 3)
        let fromFile = try rows.embed(ids)
        let expected = table[ids.flattened()].reshaped(1, 3, 32)
        eval(fromFile, expected)
        XCTAssertEqual(fromFile.dtype, .float16)
        XCTAssertEqual(bits(fromFile), bits(expected))
    }

    func testAnUnknownLayoutFallsBackAndABadFileThrows() throws {
        let (file, _) = try writeQuantizedTable(rows: 300, dimensions: 256, bits: 8, floatType: .bfloat16)
        func open(
            prefix: String = Self.prefix, rowCount: Int = 300, dimensions: Int = 256,
            quantization: Qwen3TextEmbeddingRows.Quantization? = .init(groupSize: 64, bits: 8)
        ) throws -> Qwen3TextEmbeddingRows? {
            try Qwen3TextEmbeddingRows.open(
                weightsFile: file, tensorPrefix: prefix, rowCount: rowCount, dimensions: dimensions,
                quantization: quantization
            )
        }
        XCTAssertNotNil(try open())
        XCTAssertNil(try open(prefix: "talker.model.missing"), "no such tensor")
        XCTAssertNil(try open(rowCount: 299), "another vocabulary size")
        XCTAssertNil(try open(dimensions: 128), "another embedding width")
        XCTAssertNil(try open(quantization: nil), "packed weights without a recipe")
        XCTAssertNil(try open(quantization: .init(groupSize: 64, bits: 4)), "another bit width")
        XCTAssertNil(try open(quantization: .init(groupSize: 32, bits: 8)), "another group size")

    }

    /// Every way a file can be unusable is a typed `modelNotInitialized` at
    /// load, with a fixed message: a file that is not a checkpoint, a header
    /// that is not JSON, a missing file, a checkpoint cut short inside the
    /// table, and a header whose sizes overflow.
    func testAnUnusableFileFailsTheLoadWithATypedError() throws {
        func assertNotInitialized(_ file: URL, _ label: String, line: UInt = #line) {
            XCTAssertThrowsError(try Qwen3TextEmbeddingRows.open(
                weightsFile: file, tensorPrefix: Self.prefix, rowCount: 300, dimensions: 256,
                quantization: .init(groupSize: 64, bits: 8)
            ), label, line: line) { error in
                guard case AudioGenerationError.modelNotInitialized(let message) = error else {
                    return XCTFail("\(label): expected modelNotInitialized, got \(error)", line: line)
                }
                XCTAssertFalse(message.contains(directory.path), "\(label): the message names a path", line: line)
            }
        }
        func header(_ json: String) -> Data {
            let body = Data(json.utf8)
            var data = Data((0 ..< 8).map { UInt8((UInt64(body.count) >> (8 * UInt64($0))) & 0xFF) })
            data.append(body)
            return data
        }

        let notSafetensors = directory.appendingPathComponent("bad.safetensors")
        try Data("not a checkpoint".utf8).write(to: notSafetensors)
        assertNotInitialized(notSafetensors, "not a checkpoint")

        let notJSON = directory.appendingPathComponent("not-json.safetensors")
        try header("this is not json").write(to: notJSON)
        assertNotInitialized(notJSON, "a header that is not JSON")

        assertNotInitialized(directory.appendingPathComponent("missing.safetensors"), "a missing file")

        let (file, _) = try writeQuantizedTable(rows: 300, dimensions: 256, bits: 8, floatType: .bfloat16)
        let whole = try Data(contentsOf: file)
        let cut = directory.appendingPathComponent("truncated.safetensors")
        try whole.prefix(whole.count / 2).write(to: cut)
        assertNotInitialized(cut, "a checkpoint cut short inside the table")

        // Sizes that overflow are an unknown layout, not a trap.
        let overflowing = directory.appendingPathComponent("overflow.safetensors")
        try header("""
        {"\(Self.prefix).weight": {"dtype": "F32", "shape": [3037000500, 3037000500], "data_offsets": [0, 16]}}
        """).write(to: overflowing)
        XCTAssertNil(try Qwen3TextEmbeddingRows.open(
            weightsFile: overflowing, tensorPrefix: Self.prefix, rowCount: 3_037_000_500,
            dimensions: 3_037_000_500, quantization: nil
        ))
    }

    func testATokenOutsideTheVocabularyIsRefused() throws {
        let (file, _) = try writeQuantizedTable(rows: 300, dimensions: 256, bits: 8, floatType: .bfloat16)
        let rows = try XCTUnwrap(Qwen3TextEmbeddingRows.open(
            weightsFile: file, tensorPrefix: Self.prefix, rowCount: 300, dimensions: 256,
            quantization: .init(groupSize: 64, bits: 8)
        ))
        for bad in [Int32(300), -1] {
            XCTAssertThrowsError(try rows.embed(MLXArray([bad]).reshaped(1, 1))) { error in
                guard case AudioGenerationError.invalidInput = error else {
                    return XCTFail("expected invalidInput, got \(error)")
                }
            }
        }
    }

    func testTheRowsStayReadableAfterTheFileIsRemoved() throws {
        let (file, layer) = try writeQuantizedTable(rows: 300, dimensions: 256, bits: 8, floatType: .bfloat16)
        let rows = try XCTUnwrap(Qwen3TextEmbeddingRows.open(
            weightsFile: file, tensorPrefix: Self.prefix, rowCount: 300, dimensions: 256,
            quantization: .init(groupSize: 64, bits: 8)
        ))
        try FileManager.default.removeItem(at: file)
        let ids = MLXArray([Int32(5), 250]).reshaped(1, 2)
        let fromFile = try rows.embed(ids)
        let fromLayer = layer(ids)
        eval(fromFile, fromLayer)
        XCTAssertEqual(bits(fromFile), bits(fromLayer))
    }

    /// A talker built over the reader has no text-embedding parameter, so the
    /// table is neither a checkpoint key it expects nor memory it holds, and
    /// `embedText` reads through the reader.
    func testATalkerOverTheReaderHoldsNoTextEmbeddingParameter() throws {
        let json = """
        {
          "vocab_size": 40, "hidden_size": 16, "intermediate_size": 32, "num_hidden_layers": 1,
          "num_attention_heads": 2, "num_key_value_heads": 1, "head_dim": 8, "hidden_act": "silu",
          "max_position_embeddings": 64, "rms_norm_eps": 1e-6, "rope_theta": 10000,
          "attention_bias": false, "num_code_groups": 3, "text_hidden_size": 256,
          "text_vocab_size": 300
        }
        """
        let config = try JSONDecoder().decode(Qwen3TTSTalkerConfig.self, from: Data(json.utf8))
        let (file, layer) = try writeQuantizedTable(rows: 300, dimensions: 256, bits: 8, floatType: .bfloat16)
        let rows = try XCTUnwrap(Qwen3TextEmbeddingRows.open(
            weightsFile: file, tensorPrefix: Self.prefix, rowCount: 300, dimensions: 256,
            quantization: .init(groupSize: 64, bits: 8)
        ))

        let withTable = Qwen3TTSTalkerForConditionalGeneration(config: config)
        let overReader = Qwen3TTSTalkerForConditionalGeneration(config: config, textEmbeddingRows: rows)
        let tableKeys = withTable.parameters().flattened().map(\.0).filter { $0.contains("text_embedding") }
        let readerKeys = overReader.parameters().flattened().map(\.0).filter { $0.contains("text_embedding") }
        XCTAssertEqual(tableKeys, ["model.text_embedding.weight"])
        XCTAssertEqual(readerKeys, [])
        XCTAssertNil(overReader.model.textEmbedding)

        let ids = MLXArray([Int32(9), 0, 299]).reshaped(1, 3)
        let embedded = try overReader.embedText(ids)
        let expected = layer(ids)
        eval(embedded, expected)
        XCTAssertEqual(bits(embedded), bits(expected))
        XCTAssertEqual(try withTable.embedText(ids).shape, [1, 3, 256])
    }
}
