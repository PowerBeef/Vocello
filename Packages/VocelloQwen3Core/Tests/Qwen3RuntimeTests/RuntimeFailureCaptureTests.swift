import MLX
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
            "[METAL] Command buffer execution failed: Insufficient Memory "
                + "(00000008:kIOGPUCommandBufferCallbackErrorOutOfMemory)",
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
}
