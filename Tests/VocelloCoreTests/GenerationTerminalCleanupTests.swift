import Foundation
import os
@testable import QwenVoiceCore
import VocelloQwen3Core
import XCTest

/// Pins the generation exit path's artifact-cleanup table. The regression
/// this protects: CM-7 (2026-08-04) — a completed non-streaming take had its
/// final WAV deleted by the session-retention defer, so the CLI printed a
/// success line and an output path with no file behind it.
final class GenerationTerminalCleanupTests: XCTestCase {
    func testCompletedNonStreamingTakeKeepsItsFinalOutput() {
        let cleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: true,
            usedStreaming: false
        )
        XCTAssertFalse(cleanup.removeOutput, "CM-7: a completed take must never lose its final WAV")
        XCTAssertTrue(cleanup.removeSession, "non-streaming takes retain no chunk session")
    }

    func testCompletedStreamingTakeKeepsOutputAndSession() {
        let cleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: true,
            usedStreaming: true
        )
        XCTAssertFalse(cleanup.removeOutput)
        XCTAssertFalse(cleanup.removeSession, "the player replays chunks from the session directory")
    }

    func testUnfinishedTakeCannotDeleteCallerDestination() {
        for streaming in [false, true] {
            let cleanup = GenerationOutputAdapter.terminalCleanup(
                didCompleteProduct: false,
                usedStreaming: streaming
            )
            XCTAssertFalse(cleanup.removeOutput, "only the writer owns private staging (streaming=\(streaming))")
            XCTAssertTrue(cleanup.removeSession, "partial session must not leak (streaming=\(streaming))")
        }
    }
}

/// DA-09 / E7-02: the shipped take choreography, `GenerationOutputAdapter.runReservedTake`
/// (the body of `GenerationOutputAdapter.run`), driven over a scripted take. A real
/// reservation needs loaded weights, so the engine side is faked; the order of every
/// reserve, claim, open, finalize, cancel, abort and acknowledge call is the product's.
final class GenerationOutputAdapterChoreographyTests: XCTestCase {
    private static let completedResult = GenerationResult(
        audioPath: "take.wav",
        durationSeconds: 1,
        streamSessionDirectory: nil,
        usedStreaming: false
    )

    @concurrent func testACompletedTakePublishesItsTerminalBeforeReleasingTheLease() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)

        let result = try await ChoreographyDriver.run(take, log: log, execute: { @concurrent _ in
            Self.completedResult
        })

        XCTAssertEqual(result, Self.completedResult)
        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution", "open", "execute",
            "waitForModelTermination", "sink.completed", "acknowledge(published)",
            "afterFinalization",
        ])
        XCTAssertNil(take.cancellation.reason)
    }

    @concurrent func testAModelTerminalOtherThanEndOfSequenceAbortsWithoutACompletion() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log, terminal: .completed(.maximumTokens))

        do {
            _ = try await ChoreographyDriver.run(take, log: log, execute: { @concurrent _ in Self.completedResult })
            XCTFail("A take that hit the token cap must not complete")
        } catch is NativeRuntimeError {}

        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution", "open", "execute",
            "waitForModelTermination", "cancelAudio(shutdown)", "cancelGeneration(shutdown)",
            "waitForModelTermination", "acknowledge(aborted(runtime))",
        ])
        XCTAssertEqual(take.cancellation.reason, .shutdown)
    }

    @concurrent func testAFailureAfterOpenCancelsWithTheTypedReasonAndRethrowsIt() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)
        let ingress = GenerationCancellationIngress()

        do {
            _ = try await ChoreographyDriver.run(take, ingress: ingress, log: log, execute: { @concurrent _ in
                // The admission coordinator's typed reason arrives mid-stream,
                // then the output sink fails.
                ingress.request(.superseded)
                throw ScriptedTakeFailure(step: "sink")
            })
            XCTFail("A sink failure must surface")
        } catch let failure as ScriptedTakeFailure {
            XCTAssertEqual(failure, ScriptedTakeFailure(step: "sink"), "the original error wins")
        }

        XCTAssertEqual(take.cancellation.reason, .superseded, "the ingress forwards its typed reason")
        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution", "open", "execute",
            "cancelAudio(superseded)", "cancelGeneration(superseded)",
            "waitForModelTermination", "acknowledge(aborted(runtime))",
        ])
    }

    @concurrent func testAFailureBeforeOpenAbortsTheReservationAndNeverAcknowledges() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)

        do {
            _ = try await ChoreographyDriver.run(
                take,
                log: log,
                prepare: { @concurrent in throw ScriptedTakeFailure(step: "sessionDirectory") },
                execute: { @concurrent _ in Self.completedResult }
            )
            XCTFail("A setup failure must surface")
        } catch let failure as ScriptedTakeFailure {
            XCTAssertEqual(failure, ScriptedTakeFailure(step: "sessionDirectory"))
        }

        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution",
            "cancelAudio(shutdown)", "abortReservation(shutdown)",
        ])
    }

    /// Today a published acknowledgement that throws (the lease failed
    /// revalidation) still follows the `.completed` the sink already took:
    /// the take is cancelled, finalized as aborted and the failure rethrown.
    @concurrent func testAPublishedAcknowledgementThatThrowsAbortsAndRethrows() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log, failing: ["acknowledge(published)"])

        do {
            _ = try await ChoreographyDriver.run(take, log: log, execute: { @concurrent _ in Self.completedResult })
            XCTFail("A refused acknowledgement must surface")
        } catch let failure as ScriptedTakeFailure {
            XCTAssertEqual(failure, ScriptedTakeFailure(step: "acknowledge(published)"))
        }

        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution", "open", "execute",
            "waitForModelTermination", "sink.completed", "acknowledge(published)",
            "cancelAudio(shutdown)", "cancelGeneration(shutdown)",
            "waitForModelTermination", "acknowledge(aborted(runtime))",
        ])
        XCTAssertFalse(log.entries.contains("afterFinalization"))
    }

    /// A cleanup call that throws (the reservation is already invalid) ends
    /// the cleanup there and its error replaces the original one.
    @concurrent func testACancelThatThrowsDuringCleanupSurfacesItsOwnError() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log, failing: ["cancelGeneration"])

        do {
            _ = try await ChoreographyDriver.run(take, log: log, execute: { @concurrent _ in
                throw ScriptedTakeFailure(step: "sink")
            })
            XCTFail("A failed take must surface")
        } catch let failure as ScriptedTakeFailure {
            XCTAssertEqual(failure, ScriptedTakeFailure(step: "cancelGeneration"))
        }

        XCTAssertEqual(log.entries, [
            "reserve", "claim", "prepareExecution", "open", "execute",
            "cancelAudio(shutdown)", "cancelGeneration(shutdown)",
        ])
    }

    @concurrent func testAPreCancelledTakeNeverReserves() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)
        let ingress = GenerationCancellationIngress()
        ingress.request(.memoryPressure)

        do {
            _ = try await ChoreographyDriver.run(take, ingress: ingress, log: log, execute: { @concurrent _ in
                Self.completedResult
            })
            XCTFail("A cancelled take must not run")
        } catch is CancellationError {}

        XCTAssertEqual(log.entries, [])
        XCTAssertNil(take.cancellation.reason)
    }

    @concurrent func testCancellationWonDuringReservationAbortsWithItsTypedReason() async throws {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)
        let ingress = GenerationCancellationIngress()

        do {
            _ = try await ChoreographyDriver.run(
                take,
                ingress: ingress,
                log: log,
                duringReservation: { ingress.request(.memoryPressure) },
                execute: { @concurrent _ in Self.completedResult }
            )
            XCTFail("A cancelled take must not open")
        } catch is CancellationError {}

        XCTAssertEqual(take.cancellation.reason, .memoryPressure, "the installed handler replays the reason")
        XCTAssertEqual(log.entries, ["reserve", "abortReservation(memory_pressure)"])
    }

    @concurrent func testCallerTaskCancellationReportsUser() async throws {
        let (take, log, ingress) = await runUntilCancelled { task, _ in
            task.cancel()
        }

        XCTAssertEqual(ingress.reason, .user)
        XCTAssertEqual(take.cancellation.reason, .user)
        XCTAssertEqual(Array(log.entries.suffix(4)), [
            "cancelAudio(user)", "cancelGeneration(user)",
            "waitForModelTermination", "acknowledge(aborted(runtime))",
        ])
    }

    @concurrent func testATypedReasonRequestedBeforeTheCallerCancelsWins() async throws {
        // PA-15 at the adapter: the barrier records `.shutdown` before the
        // Swift task is cancelled, so the task's `.user` is ignored.
        let (take, log, ingress) = await runUntilCancelled { task, typedIngress in
            typedIngress.request(.shutdown)
            task.cancel()
        }

        XCTAssertEqual(ingress.reason, .shutdown)
        XCTAssertEqual(take.cancellation.reason, .shutdown)
        XCTAssertTrue(log.entries.contains("cancelGeneration(shutdown)"))
        XCTAssertFalse(log.entries.contains("sink.completed"))
    }

    /// Runs a take whose execution waits until its session is cancelled,
    /// applies `cancel` once the take is executing, and returns its state.
    @concurrent private func runUntilCancelled(
        _ cancel: (Task<(any Error)?, Never>, GenerationCancellationIngress) -> Void
    ) async -> (ScriptedReservedTake, ChoreographyLog, GenerationCancellationIngress) {
        let log = ChoreographyLog()
        let take = ScriptedReservedTake(log: log)
        let ingress = GenerationCancellationIngress()
        let executing = ChoreographySignal()
        let task = Task { @concurrent () async -> (any Error)? in
            do {
                _ = try await ChoreographyDriver.run(take, ingress: ingress, log: log, execute: { @concurrent take in
                    await executing.raise()
                    await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                        take.cancellation.installCancelAction { continuation.resume() }
                    }
                    throw CancellationError()
                })
                return nil
            } catch {
                return error
            }
        }
        await executing.wait()
        cancel(task, ingress)
        let error = await task.value
        XCTAssertTrue(error is CancellationError, "unexpected outcome: \(String(describing: error))")
        return (take, log, ingress)
    }
}

/// Drives `GenerationOutputAdapter.runReservedTake` over a scripted take.
private enum ChoreographyDriver {
    @concurrent static func run(
        _ take: ScriptedReservedTake,
        ingress: GenerationCancellationIngress = GenerationCancellationIngress(),
        log: ChoreographyLog,
        duringReservation: () -> Void = {},
        prepare: @concurrent () async throws -> Void = { @concurrent in},
        execute: @concurrent (ScriptedReservedTake) async throws -> GenerationResult
    ) async throws -> GenerationResult {
        try await GenerationOutputAdapter.runReservedTake(
            cancellationIngress: ingress,
            telemetryRecorder: nil,
            reserve: { @concurrent () async throws -> ScriptedReservedTake in
                log.append("reserve")
                duringReservation()
                return take
            },
            prepareExecution: { @concurrent () async throws -> String in
                log.append("prepareExecution")
                try await prepare()
                return "execution"
            },
            execute: { @concurrent (
                execution: String,
                reserved: ScriptedReservedTake,
                audio: Int,
                _: Int?
            ) async throws -> GenerationResult in
                XCTAssertEqual(execution, "execution")
                XCTAssertEqual(audio, ScriptedReservedTake.audioToken)
                log.append("execute")
                return try await execute(reserved)
            },
            chunkSink: { @concurrent event in log.append(Self.label(event)) },
            afterFinalization: { @concurrent in log.append("afterFinalization") }
        )
    }

    private static func label(_ event: GenerationEvent) -> String {
        switch event {
        case .progress: "sink.progress"
        case .chunk: "sink.chunk"
        case .completed: "sink.completed"
        case .cancelled: "sink.cancelled"
        case .failed: "sink.failed"
        }
    }
}

private struct ScriptedTakeFailure: Error, Equatable {
    let step: String
}

private final class ChoreographyLog: Sendable {
    private let storage = OSAllocatedUnfairLock<[String]>(initialState: [])

    var entries: [String] { storage.withLock { $0 } }

    func append(_ entry: String) {
        storage.withLock { $0.append(entry) }
    }
}

private actor ChoreographySignal {
    private var raised = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func raise() {
        raised = true
        let pending = waiters
        waiters.removeAll()
        pending.forEach { $0.resume() }
    }

    func wait() async {
        guard !raised else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }
}

/// The engine side of one reservation, recording each call in order.
private struct ScriptedReservedTake: GenerationReservedTake {
    static let audioToken = 7

    let log: ChoreographyLog
    var terminal: VocelloQwen3TerminalOutcome = .completed(.endOfSequence)
    /// Logged steps that throw `ScriptedTakeFailure` after they are logged.
    var failing: Set<String> = []
    let cancellation = VocelloQwen3CancellationController()

    private func record(_ step: String) throws {
        log.append(step)
        if failing.contains(step) { throw ScriptedTakeFailure(step: step) }
    }

    @concurrent func claimAudioConsumer() async throws -> Int {
        log.append("claim")
        return Self.audioToken
    }

    @concurrent func cancelAudio(_ audio: Int, reason: VocelloQwen3CancellationReason) async {
        log.append("cancelAudio(\(reason.rawValue))")
    }

    @concurrent func open() async throws {
        log.append("open")
    }

    @concurrent func waitForModelTermination() async -> VocelloQwen3TerminalEvent {
        log.append("waitForModelTermination")
        return VocelloQwen3TerminalEvent(
            generationID: UUID(),
            outcome: terminal,
            generatedTokenCount: 3,
            emittedAudioFrameCount: 1_920,
            elapsedMilliseconds: 1
        )
    }

    @concurrent func cancelGeneration(reason: VocelloQwen3CancellationReason) async throws {
        log.append("cancelGeneration(\(reason.rawValue))")
        if failing.contains("cancelGeneration") { throw ScriptedTakeFailure(step: "cancelGeneration") }
    }

    @concurrent func abortReservation(reason: VocelloQwen3CancellationReason) async throws {
        log.append("abortReservation(\(reason.rawValue))")
    }

    @concurrent func acknowledgeProductFinalization(
        _ disposition: VocelloQwen3ProductFinalizationDisposition
    ) async throws {
        switch disposition {
        case .published:
            try record("acknowledge(published)")
        case .aborted(let code):
            try record("acknowledge(aborted(\(code.rawValue)))")
        }
    }
}
