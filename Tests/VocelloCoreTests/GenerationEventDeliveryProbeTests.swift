import XCTest
@testable import QwenVoiceCore

final class GenerationEventDeliveryProbeTests: XCTestCase {
    func testBoundedGenerationStreamBackpressuresWithoutEvictingAudioOrTerminal() async {
        let router = GenerationScopedEventRouter()
        let generationID = UUID()
        let stream = router.stream(for: generationID, capacity: 1)
        router.beginGeneration(generationID)

        let producer = Task.detached {
            await router.yield(.progress(GenerationProgress(percent: 10, message: "one")), for: generationID)
            await router.yield(.progress(GenerationProgress(percent: 20, message: "two")), for: generationID)
            await router.yield(.failed("fixture"), for: generationID)
        }

        var received: [GenerationEvent] = []
        for await event in stream {
            received.append(event)
        }
        await producer.value
        let snapshot = router.snapshot(for: generationID)
        XCTAssertEqual(received, [
            .progress(GenerationProgress(percent: 10, message: "one")),
            .progress(GenerationProgress(percent: 20, message: "two")),
            .failed("fixture"),
        ])
        XCTAssertEqual(snapshot.yielded, 3)
        XCTAssertEqual(snapshot.accepted, 3)
        XCTAssertEqual(snapshot.droppedProgress, 0)
        XCTAssertEqual(snapshot.droppedTerminals, 0)
        XCTAssertEqual(snapshot.terminalYielded, 1)
        XCTAssertEqual(snapshot.terminalEnqueued, 1)
        XCTAssertTrue(snapshot.terminalDeliveryComplete)
        XCTAssertTrue(snapshot.accountingIsExact)
    }

    func testPriorGenerationCannotOccupyNextGenerationBuffer() async {
        let router = GenerationScopedEventRouter()
        let oldID = UUID()
        let newID = UUID()
        let oldStream = router.stream(for: oldID, capacity: 1)
        let newStream = router.stream(for: newID, capacity: 1)
        router.beginGeneration(oldID)
        router.beginGeneration(newID)

        await router.yield(.progress(GenerationProgress(percent: 1, message: "old")), for: oldID)
        await router.yield(.failed("new-terminal"), for: newID)

        var newEvents: [GenerationEvent] = []
        for await event in newStream { newEvents.append(event) }
        XCTAssertEqual(newEvents, [.failed("new-terminal")])
        XCTAssertEqual(router.snapshot(for: newID).droppedTotal, 0)
        XCTAssertEqual(router.snapshot(for: newID).terminalEnqueued, 1)
        XCTAssertEqual(router.snapshot(for: oldID).yielded, 1)
        withExtendedLifetime(oldStream) {}
    }

    func testConsumerTerminationBeforeTerminalIsReportedExactly() async {
        let router = GenerationScopedEventRouter()
        let generationID = UUID()
        let stream = router.stream(for: generationID, capacity: 4)
        router.beginGeneration(generationID)
        let consumer = Task {
            for await _ in stream {}
        }
        consumer.cancel()
        await consumer.value

        await router.yield(.failed("terminal-after-consumer"), for: generationID)

        let snapshot = router.snapshot(for: generationID)
        XCTAssertTrue(snapshot.consumerTerminatedBeforeTerminal)
        XCTAssertEqual(snapshot.yielded, 1)
        XCTAssertEqual(snapshot.unobserved, 1)
        XCTAssertEqual(snapshot.terminalYielded, 1)
        XCTAssertEqual(snapshot.terminalEnqueued, 0)
        XCTAssertFalse(snapshot.terminalDeliveryComplete)
        XCTAssertTrue(snapshot.accountingIsExact)
    }

    func testStressRetainsEveryChunkAndTerminalUnderBackpressure() async {
        let router = GenerationScopedEventRouter()
        let generationID = UUID()
        let capacity = 1_001
        let stream = router.stream(for: generationID, capacity: capacity)
        router.beginGeneration(generationID)

        for index in 0..<1_000 {
            await router.yield(Self.chunk(index: index, generationID: generationID), for: generationID)
        }
        await router.yield(.completed(Self.result), for: generationID)

        var received: [GenerationEvent] = []
        for await event in stream { received.append(event) }
        let snapshot = router.snapshot(for: generationID)
        XCTAssertEqual(received.count, 1_001)
        XCTAssertEqual(received.last, .completed(Self.result))
        XCTAssertEqual(snapshot.yielded, 1_001)
        XCTAssertEqual(snapshot.accepted, 1_001)
        XCTAssertEqual(snapshot.droppedChunks, 0)
        XCTAssertEqual(snapshot.droppedTerminals, 0)
        XCTAssertEqual(snapshot.terminalEnqueued, 1)
        XCTAssertTrue(snapshot.accountingIsExact)
    }

    /// L13-06: a cancelled take yields `.cancelled` from its own cancelled task.
    /// With the consumer a full queue behind, that terminal must still reach it
    /// after the queued chunks; dropped, the consumer would wait forever and the
    /// store's `generate` would never return.
    func testATerminalFromACancelledProducerIsNeverDroppedBehindAFullQueue() async {
        let router = GenerationScopedEventRouter()
        let generationID = UUID()
        let stream = router.stream(for: generationID, capacity: 2)
        router.beginGeneration(generationID)
        await router.yield(Self.chunk(index: 0, generationID: generationID), for: generationID)
        await router.yield(Self.chunk(index: 1, generationID: generationID), for: generationID)

        let terminal = GenerationEvent.cancelled(
            GenerationCancellationSummary(generationID: generationID, reason: .memoryPressure)
        )
        let producer = Task.detached {
            withUnsafeCurrentTask { $0?.cancel() }
            await router.yield(terminal, for: generationID)
        }
        await producer.value

        let drained = Task { () -> [GenerationEvent] in
            var received: [GenerationEvent] = []
            for await event in stream { received.append(event) }
            return received
        }
        // Without the fix the drain parks forever; the watchdog turns that into a failure.
        let watchdog = Task {
            try? await Task.sleep(for: .seconds(10))
            drained.cancel()
        }
        let received = await drained.value
        watchdog.cancel()

        XCTAssertEqual(received, [
            Self.chunk(index: 0, generationID: generationID),
            Self.chunk(index: 1, generationID: generationID),
            terminal,
        ])
        let snapshot = router.snapshot(for: generationID)
        XCTAssertEqual(snapshot.yielded, 3)
        XCTAssertEqual(snapshot.accepted, 3)
        XCTAssertEqual(snapshot.terminatedYields, 0)
        XCTAssertEqual(snapshot.terminalEnqueued, 1)
        XCTAssertTrue(snapshot.terminalDeliveryComplete)
        XCTAssertTrue(snapshot.accountingIsExact)
    }

    private static func chunk(index: Int, generationID: UUID) -> GenerationEvent {
        .chunk(
            GenerationChunk(
                generationID: generationID,
                requestID: index,
                mode: "custom",
                title: "chunk",
                chunkPath: nil,
                isFinal: false,
                chunkDurationSeconds: nil,
                cumulativeDurationSeconds: nil,
                streamSessionDirectory: nil,
                chunkSequence: UInt64(index)
            )
        )
    }

    private static let result = GenerationResult(
        audioPath: "fixture.wav",
        durationSeconds: 1,
        streamSessionDirectory: nil,
        usedStreaming: true
    )
}
