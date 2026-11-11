import Foundation
import MLX
@testable import MLXAudioTTS
import MLXNN
import XCTest

/// RF-46: one fused quantized product must give each projection exactly the
/// bits its own product gave for a one-row step, admit no other shape, and
/// leave the layers usable on their own rows of the fused arrays.
final class Qwen3FusedProjectionTests: XCTestCase {
    private func quantizedLayer(_ input: Int, _ output: Int, seed: UInt64) -> QuantizedLinear {
        let weight = MLXRandom.normal([output, input], key: MLXRandom.key(seed)) * 0.05
        let layer = QuantizedLinear(weight: weight, bias: nil, groupSize: 64, bits: 4)
        eval(layer.parameters())
        return layer
    }

    private func bits(_ array: MLXArray) -> [UInt32] {
        array.asType(.float32).asArray(Float.self).map(\.bitPattern)
    }

    func testFusedRowsMatchTheSeparateProductsBitForBit() throws {
        // The talker's shape class: an input width the fast one-row kernel
        // accepts, and three projections of unequal widths.
        let input = 1_024
        let layers = [
            quantizedLayer(input, 512, seed: 1),
            quantizedLayer(input, 256, seed: 2),
            quantizedLayer(input, 256, seed: 3),
        ]
        for dtype in [DType.float32, .float16, .bfloat16] {
            // A prefill is checked on the re-pointed layers only: the fused
            // product is not offered for it.
            for (label, rows) in [("one decode step", 1), ("a prefill", 7)] {
                let x = MLXRandom.normal([1, rows, input], key: MLXRandom.key(UInt64(rows)))
                    .asType(dtype)
                let separate = layers.map { $0(x) }
                eval(separate)
                let expected = separate.map(bits)

                let fresh = [
                    quantizedLayer(input, 512, seed: 1),
                    quantizedLayer(input, 256, seed: 2),
                    quantizedLayer(input, 256, seed: 3),
                ]
                let fused = try XCTUnwrap(FusedQuantizedProjection.fuse(fresh))
                XCTAssertEqual(fused.outputRanges, [0 ..< 512, 512 ..< 768, 768 ..< 1_024])
                XCTAssertEqual(fused.projects(x), rows == 1, "\(label)")
                if fused.projects(x) {
                    let outputs = fused(x)
                    eval(outputs)
                    for index in outputs.indices {
                        XCTAssertEqual(outputs[index].shape, separate[index].shape)
                        XCTAssertEqual(outputs[index].dtype, separate[index].dtype)
                        XCTAssertEqual(
                            bits(outputs[index]), expected[index],
                            "projection \(index), \(label), \(dtype)"
                        )
                    }
                }
                // Each layer now reads its rows of the fused arrays.
                let repointed = fresh.map { $0(x) }
                eval(repointed)
                for index in repointed.indices {
                    XCTAssertEqual(
                        bits(repointed[index]), expected[index],
                        "re-pointed layer \(index), \(label), \(dtype)"
                    )
                }
            }
        }
    }

    /// Fusing must leave one copy of the weights: each layer is re-pointed at
    /// its rows of the fused arrays and its own arrays are released. Without
    /// the re-pointing the fused arrays would be a second copy.
    func testFusingLeavesOneCopyOfTheWeights() throws {
        let input = 2_048
        Memory.clearCache()
        let baseline = Memory.activeMemory
        let layers = [
            quantizedLayer(input, 2_048, seed: 7),
            quantizedLayer(input, 1_024, seed: 8),
            quantizedLayer(input, 1_024, seed: 9),
        ]
        Memory.clearCache()
        let loaded = Memory.activeMemory - baseline
        XCTAssertGreaterThan(loaded, 4_000_000, "the layers' packed weights are resident")

        let fused = try XCTUnwrap(FusedQuantizedProjection.fuse(layers))
        Memory.clearCache()
        let afterFusing = Memory.activeMemory - baseline
        XCTAssertLessThan(
            Double(afterFusing), Double(loaded) * 1.25,
            "fusing must not keep a second copy of the weights"
        )
        // 8-bit layers fuse the same way.
        let eightBit = (0 ..< 2).map { index in
            let weight = MLXRandom.normal([512, input], key: MLXRandom.key(UInt64(20 + index))) * 0.05
            let layer = QuantizedLinear(weight: weight, bias: nil, groupSize: 64, bits: 8)
            eval(layer.parameters())
            return layer
        }
        let x = MLXRandom.normal([1, 1, input], key: MLXRandom.key(31)).asType(.bfloat16)
        let separate = eightBit.map { $0(x) }
        eval(separate)
        let expected = separate.map(bits)
        let fusedEightBit = try XCTUnwrap(FusedQuantizedProjection.fuse(eightBit))
        let outputs = fusedEightBit(x)
        eval(outputs)
        XCTAssertEqual(outputs.map(bits), expected)
        _ = fused
    }

    func testOnlyBiasFreeQuantizedLayersOfOneRecipeAreFused() {
        let input = 512
        XCTAssertNil(FusedQuantizedProjection.fuse([
            Linear(input, 64, bias: false), Linear(input, 64, bias: false),
        ]), "float layers keep their separate products")

        let biased = QuantizedLinear(
            weight: MLXRandom.normal([64, input]), bias: MLXArray.zeros([64]), groupSize: 64, bits: 4
        )
        XCTAssertNil(
            FusedQuantizedProjection.fuse([quantizedLayer(input, 64, seed: 4), biased]),
            "a biased layer is not fused"
        )

        let eightBit = QuantizedLinear(
            weight: MLXRandom.normal([64, input]), bias: nil, groupSize: 64, bits: 8
        )
        XCTAssertNil(
            FusedQuantizedProjection.fuse([quantizedLayer(input, 64, seed: 5), eightBit]),
            "layers of two recipes are not fused"
        )
        XCTAssertNil(
            FusedQuantizedProjection.fuse([quantizedLayer(input, 64, seed: 6)]),
            "one layer has nothing to fuse with"
        )
        XCTAssertNil(
            FusedQuantizedProjection.fuse([
                quantizedLayer(input, 64, seed: 10), quantizedLayer(input, 12, seed: 11),
            ]),
            "a width that is not a multiple of eight could change the one-row kernel"
        )
    }
}
