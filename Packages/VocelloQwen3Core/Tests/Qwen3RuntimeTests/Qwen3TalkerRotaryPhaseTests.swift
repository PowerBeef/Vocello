import Foundation
import MLX
@testable import MLXAudioTTS
import XCTest

/// RF-46: the talker's sign-folded rotary step must produce exactly the bits
/// of the reference form `x * cos + rotateHalf(x) * sin`, in every activation
/// dtype the talker runs in.
final class Qwen3TalkerRotaryPhaseTests: XCTestCase {
    private func referenceRotation(_ x: MLXArray, cos: MLXArray, sin: MLXArray) -> MLXArray {
        let half = x.dim(-1) / 2
        let rotated = concatenated([-x[.ellipsis, half...], x[.ellipsis, ..<half]], axis: -1)
        return x * expandedDimensions(cos, axis: 1) + rotated * expandedDimensions(sin, axis: 1)
    }

    /// The reference phase, built the way the talker built it before RF-46.
    private func referencePhase(
        _ embedding: TalkerRotaryEmbedding, positions: MLXArray, dtype: DType
    ) -> (cos: MLXArray, sin: MLXArray) {
        let count = positions.dim(-1)
        let inverse = embedding._invFreq.reshaped(1, 1, -1, 1).asType(.float32)
        let expanded = broadcast(inverse, to: [3, 1, embedding._invFreq.dim(0), 1])
        let pos = expandedDimensions(
            broadcast(positions.reshaped(1, 1, count), to: [3, 1, count]).asType(.float32), axis: 2
        )
        let freqs = swappedAxes(matmul(expanded, pos), 2, 3)
        let combined = embedding.applyInterleavedMrope(freqs, mropeSection: embedding.mropeSection)
        let emb = concatenated([combined, combined], axis: -1)
        return (MLX.cos(emb).asType(dtype), MLX.sin(emb).asType(dtype))
    }

    private func bits(_ array: MLXArray) -> [UInt32] {
        // Compare in float32: every float16 and bfloat16 value is exactly
        // representable, so equal float32 bits mean equal source bits.
        array.asType(.float32).asArray(Float.self).map(\.bitPattern)
    }

    func testSignFoldedRotationMatchesTheReferenceBits() throws {
        let headDim = 128
        let embedding = TalkerRotaryEmbedding(dim: headDim)
        for dtype in [DType.float32, .float16, .bfloat16] {
            for (label, positions) in [
                ("one decode step", MLXArray([Int32(417)])),
                ("a prefill", MLXArray(Int32(0) ..< Int32(9))),
            ] {
                let count = positions.dim(0)
                let key = MLXRandom.key(UInt64(count))
                let q = MLXRandom.normal([1, 16, count, headDim], key: key).asType(dtype)
                let k = MLXRandom.normal([1, 8, count, headDim], key: MLXRandom.split(key: key).0)
                    .asType(dtype)
                let positionIDs = broadcast(positions.reshaped(1, 1, count), to: [3, 1, count])

                let phase = embedding(q, positionIds: positionIDs)
                let (rotatedQ, rotatedK) = phase.rotate(q, k)
                let reference = referencePhase(embedding, positions: positions, dtype: dtype)
                let expectedQ = referenceRotation(q, cos: reference.cos, sin: reference.sin)
                let expectedK = referenceRotation(k, cos: reference.cos, sin: reference.sin)
                eval(rotatedQ, rotatedK, expectedQ, expectedK)

                XCTAssertEqual(rotatedQ.dtype, dtype, "\(label), \(dtype)")
                XCTAssertEqual(rotatedQ.shape, q.shape, "\(label), \(dtype)")
                XCTAssertEqual(bits(rotatedQ), bits(expectedQ), "queries, \(label), \(dtype)")
                XCTAssertEqual(bits(rotatedK), bits(expectedK), "keys, \(label), \(dtype)")
            }
        }
    }
}
