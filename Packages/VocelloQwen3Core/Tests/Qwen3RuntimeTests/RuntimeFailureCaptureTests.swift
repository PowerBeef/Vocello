import MLX
@testable import MLXAudioTTS
@testable import VocelloQwen3Core
import XCTest

/// The facade's MLX error capture: an MLX error inside an owned-runtime entry
/// point becomes a typed `VocelloQwen3RuntimeFailure` instead of reaching
/// mlx-swift's `fatalError`. No model weights or downloads.
final class RuntimeFailureCaptureTests: XCTestCase {
    func testAllocationMessagesClassifyAsAllocation() {
        let allocationMessages = [
            "[metal::malloc] Attempting to allocate 68719476736 bytes which is greater than "
                + "the maximum allowed buffer size of 17179869184 bytes.",
            "[metal::malloc] Resource limit (499000) exceeded.",
            "[malloc] Unable to allocate 1073741824 bytes.",
        ]
        for message in allocationMessages {
            XCTAssertEqual(
                VocelloQwen3RuntimeFailure.classifying(mlxMessage: message),
                .allocation,
                message
            )
        }
        XCTAssertEqual(VocelloQwen3RuntimeFailure.allocation.failureCode, .memoryPressure)
    }

    func testOtherMessagesClassifyAsMLXFailure() {
        let message = "[broadcast_shapes] Shapes (2,5) and (3,5) cannot be broadcast."
        XCTAssertEqual(VocelloQwen3RuntimeFailure.classifying(mlxMessage: message), .mlx)
        XCTAssertEqual(VocelloQwen3RuntimeFailure.mlx.failureCode, .runtime)
    }

    func testCaughtMLXErrorMapsToTypedFailure() {
        XCTAssertEqual(
            VocelloQwen3RuntimeFailure(mlxError: MLXError.caught("[malloc] Unable to allocate 64 bytes.")),
            .allocation
        )
        XCTAssertEqual(
            VocelloQwen3RuntimeFailure(mlxError: MLXError.caught("[load] Invalid header.")),
            .mlx
        )
        XCTAssertNil(VocelloQwen3RuntimeFailure(mlxError: CancellationError()))
    }

    func testObservedCancellationWinsOverARecordedMLXFailure() async {
        let scope = VocelloQwen3MLXErrorScope()
        let task = Task { () -> Error? in
            do {
                _ = try await scope.captureAsync { @Sendable () async throws -> Int in
                    withUnsafeCurrentTask { $0?.cancel() }
                    scope.record(mlxMessage: "[malloc] Unable to allocate 64 bytes.")
                    // The operation noticed nothing and returned normally.
                    return 1
                }
                return nil
            } catch {
                return error
            }
        }
        let error = await task.value
        XCTAssertTrue(error is CancellationError, "\(String(describing: error))")
    }

    func testScopeKeepsTheFirstRecordedFailure() throws {
        let scope = VocelloQwen3MLXErrorScope()
        XCTAssertNil(scope.failure)
        XCTAssertNoThrow(try scope.check())

        scope.record(mlxMessage: "[malloc] Unable to allocate 64 bytes.")
        scope.record(mlxMessage: "[broadcast_shapes] Shapes cannot be broadcast.")

        XCTAssertEqual(scope.failure, .allocation)
        XCTAssertThrowsError(try scope.check()) { error in
            XCTAssertEqual(error as? VocelloQwen3RuntimeFailure, .allocation)
        }
    }

    func testRealMLXErrorThrowsTypedFailureInsteadOfFatalError() {
        let scope = VocelloQwen3MLXErrorScope()
        XCTAssertThrowsError(
            try scope.capture { () -> MLXArray in
                let a = MLXArray(0 ..< 10, [2, 5])
                let b = MLXArray(0 ..< 15, [3, 5])
                // Incompatible shapes: MLX raises through its error handler.
                return a + b
            }
        ) { error in
            XCTAssertEqual(error as? VocelloQwen3RuntimeFailure, .mlx)
        }
    }

    func testAsyncScopeCapturesMLXErrorsFromChildTasks() async {
        let scope = VocelloQwen3MLXErrorScope()
        do {
            _ = try await scope.captureAsync { @Sendable () async throws -> Int in
                // The handler is task-local, so an unstructured task started
                // inside the scope (like the Qwen3 producer) reports into it.
                let producer = Task { () -> Int in
                    let a = MLXArray(0 ..< 10, [2, 5])
                    let b = MLXArray(0 ..< 15, [3, 5])
                    _ = a + b
                    return 1
                }
                return await producer.value
            }
            XCTFail("an MLX error inside the scope must throw")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3RuntimeFailure, .mlx)
        }
    }

    func testCancellationWinsOverARecordedMLXFailure() async {
        let scope = VocelloQwen3MLXErrorScope()
        do {
            _ = try await scope.captureAsync { @Sendable () async throws -> Int in
                scope.record(mlxMessage: "[malloc] Unable to allocate 64 bytes.")
                throw CancellationError()
            }
            XCTFail("the operation threw")
        } catch {
            XCTAssertTrue(error is CancellationError, "\(error)")
        }
    }

    func testThrownErrorIsReplacedByTheRecordedMLXFailure() {
        struct DownstreamGarbage: Error {}
        let scope = VocelloQwen3MLXErrorScope()
        XCTAssertThrowsError(
            try scope.capture { () throws -> Int in
                scope.record(mlxMessage: "[metal::malloc] Resource limit (499000) exceeded.")
                throw DownstreamGarbage()
            }
        ) { error in
            XCTAssertEqual(error as? VocelloQwen3RuntimeFailure, .allocation)
        }
    }

    /// F-03 (engine audit 2026-10-16): inside a scope a failed evaluation
    /// returns normally and leaves its buffer unfilled, so `asArray` would trap
    /// on a nil base address. The readback probe throws first, the scope maps
    /// the error to the typed failure, and the probe's own handler owns it.
    func testReadbackProbeThrowsAForcedAllocationFailureInsteadOfTrapping() throws {
        let scope = VocelloQwen3MLXErrorScope()
        XCTAssertThrowsError(
            try scope.capture { () -> [Float] in
                let oversized = Self.oversizedArray()
                try evalForReadback(oversized)
                return oversized.asArray(Float.self)
            }
        ) { error in
            XCTAssertEqual(error as? VocelloQwen3RuntimeFailure, .allocation)
        }
        XCTAssertNil(scope.failure, "the probe, not the outer scope, caught the error")

        // The facade's completion probes the final waveform the same way.
        XCTAssertThrowsError(
            try VocelloQwen3GenerationCompletion(
                AudioGenerationCompletion(audio: Self.oversizedArray(), info: nil, finishReason: .eos)
            )
        ) { error in
            XCTAssertEqual(VocelloQwen3RuntimeFailure(mlxError: error), .allocation)
        }

        // A healthy array passes the probe unchanged.
        let healthy = MLXArray([1, 2, 3] as [Float]) * 2
        try evalForReadback(healthy)
        XCTAssertEqual(healthy.asArray(Float.self), [2, 4, 6])
        let completion = try VocelloQwen3GenerationCompletion(
            AudioGenerationCompletion(audio: healthy, info: nil, finishReason: .eos)
        )
        XCTAssertEqual(completion.audio, [2, 4, 6])
    }

    /// BG-01 review: an unleased artifact operation marks the loaded model for
    /// unload only for an evaluation error its scope recorded or an allocation
    /// failure; a file error from mlx-swift's own I/O leaves the model intact.
    func testUnleasedArtifactFailuresMarkTheModelOnlyForEvaluationOrAllocation() {
        XCTAssertTrue(VocelloQwen3Engine.unleasedFailureMarksModelForUnload(
            recorded: .mlx, error: VocelloQwen3RuntimeFailure.mlx
        ))
        XCTAssertTrue(VocelloQwen3Engine.unleasedFailureMarksModelForUnload(
            recorded: nil, error: VocelloQwen3RuntimeFailure.allocation
        ))
        XCTAssertFalse(VocelloQwen3Engine.unleasedFailureMarksModelForUnload(
            recorded: nil, error: VocelloQwen3RuntimeFailure.mlx
        ))
        XCTAssertFalse(VocelloQwen3Engine.unleasedFailureMarksModelForUnload(
            recorded: nil, error: CancellationError()
        ))
    }

    /// 2^36 float32 elements (256 GiB): larger than any device's maximum
    /// buffer length, so MLX refuses the allocation before making it.
    private static func oversizedArray() -> MLXArray {
        MLXArray.zeros([1 << 18, 1 << 18], type: Float.self)
    }
}
