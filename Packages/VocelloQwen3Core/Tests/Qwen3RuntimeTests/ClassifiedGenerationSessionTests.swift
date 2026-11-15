@testable import VocelloQwen3Core
import XCTest

final class ClassifiedGenerationSessionTests: XCTestCase {
    func testLosslessAudioChannelSuspendsByFrameCapacityAndPreservesOrder() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 4)
        let first = chunk(sequence: 0, samples: [0, 1, 2, 3])
        let second = chunk(sequence: 1, samples: [4, 5, 6, 7])
        try await channel.producer.send(first)

        let attempted = expectation(description: "second send attempted")
        let producer = Task {
            attempted.fulfill()
            try await channel.producer.send(second)
        }
        await fulfillment(of: [attempted], timeout: 1)

        var iterator = channel.consumer.makeAsyncIterator()
        let observedFirst = try await iterator.next()
        XCTAssertEqual(observedFirst, first)
        try await producer.value
        await channel.producer.finish()
        let observedSecond = try await iterator.next()
        let observedEnd = try await iterator.next()
        XCTAssertEqual(observedSecond, second)
        XCTAssertNil(observedEnd)

        let statistics = await channel.consumer.statistics()
        XCTAssertEqual(statistics.capacityFrames, 4)
        XCTAssertEqual(statistics.highWaterFrames, 4)
        XCTAssertEqual(statistics.producerSuspensionCount, 1)
        XCTAssertGreaterThan(statistics.producerSuspensionNanoseconds, 0)
    }

    func testLosslessAudioChannelRejectsSecondConsumer() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 8)
        try await channel.producer.send(chunk(sequence: 0, samples: [0, 1]))

        var first = channel.consumer.makeAsyncIterator()
        var second = channel.consumer.makeAsyncIterator()
        let firstValue = try await first.next()
        XCTAssertNotNil(firstValue)
        await channel.producer.finish()

        do {
            _ = try await second.next()
            XCTFail("a second audio consumer must fail")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .audioConsumerAlreadyClaimed)
        }
    }

    func testCancellationWakesProducerBlockedByBackpressure() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 2)
        try await channel.producer.send(chunk(sequence: 0, samples: [0, 1]))
        let blockedChunk = chunk(sequence: 1, samples: [2, 3])
        let attempted = expectation(description: "blocked send attempted")
        let producer = Task { () -> (any Error)? in
            attempted.fulfill()
            do {
                try await channel.producer.send(blockedChunk)
                return nil
            } catch {
                return error
            }
        }
        await fulfillment(of: [attempted], timeout: 1)

        await channel.consumer.cancel(reason: .memoryPressure)
        let error = await producer.value
        XCTAssertEqual(
            error as? VocelloQwen3SessionError,
            .audioChannelCancelled(.memoryPressure)
        )
        let statistics = await channel.consumer.statistics()
        XCTAssertEqual(statistics.cancellationWakeupCount, 1)
    }

    func testTaskCancellationReleasesProducerBlockedByBackpressure() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 2)
        try await channel.producer.send(chunk(sequence: 0, samples: [0, 1]))
        let blockedChunk = chunk(sequence: 1, samples: [2, 3])
        let attempted = expectation(description: "blocked send attempted")
        let producer = Task { () -> (any Error)? in
            attempted.fulfill()
            do {
                try await channel.producer.send(blockedChunk)
                return nil
            } catch {
                return error
            }
        }
        await fulfillment(of: [attempted], timeout: 1)

        for _ in 0 ..< 32 {
            if await channel.consumer.statistics().producerSuspensionCount == 1 {
                break
            }
            await Task.yield()
        }
        let statisticsBeforeCancellation = await channel.consumer.statistics()
        XCTAssertEqual(statisticsBeforeCancellation.producerSuspensionCount, 1)

        producer.cancel()
        let error = await producer.value
        XCTAssertTrue(error is CancellationError)

        var audio = channel.consumer.makeAsyncIterator()
        let remainingChunk = try await audio.next()
        XCTAssertEqual(remainingChunk?.sequence, 0)
        await channel.producer.finish()
        let end = try await audio.next()
        XCTAssertNil(end)
    }

    func testReceiverTaskCancellationTerminatesChannelAndRejectsLaterSends() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 2)
        let receiverStarted = expectation(description: "receiver attempted next")
        let receiver = Task { () -> (any Error)? in
            var audio = channel.consumer.makeAsyncIterator()
            receiverStarted.fulfill()
            do {
                _ = try await audio.next()
                return nil
            } catch {
                return error
            }
        }
        await fulfillment(of: [receiverStarted], timeout: 1)

        receiver.cancel()
        let receiverError = await receiver.value
        XCTAssertTrue(receiverError is CancellationError)

        do {
            try await channel.producer.send(chunk(sequence: 0, samples: [0, 1]))
            XCTFail("a cancelled mandatory receiver must close the lossless channel")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }
    }

    func testConsumerFailureWakesProducerBlockedByBackpressure() async throws {
        let channel = VocelloQwen3LosslessAudioChannel.make(capacityFrames: 2)
        try await channel.producer.send(chunk(sequence: 0, samples: [0, 1]))
        let blockedChunk = chunk(sequence: 1, samples: [2, 3])
        let producer = Task { () -> (any Error)? in
            do {
                try await channel.producer.send(blockedChunk)
                return nil
            } catch {
                return error
            }
        }

        for _ in 0 ..< 64 {
            if await channel.consumer.statistics().producerSuspensionCount == 1 {
                break
            }
            await Task.yield()
        }
        let statisticsBeforeFailure = await channel.consumer.statistics()
        XCTAssertEqual(statisticsBeforeFailure.producerSuspensionCount, 1)

        await channel.consumer.fail(ConsumerDrainFixtureError.failed)
        let producerError = await producer.value
        XCTAssertEqual(producerError as? ConsumerDrainFixtureError, .failed)
    }

    func testMaximumLengthChannelRemainsBoundedAndOrdered() async throws {
        let chunkCount = 4_096
        let capacityFrames = 32
        let channel = VocelloQwen3LosslessAudioChannel.make(
            capacityFrames: capacityFrames
        )
        let generationID = UUID(uuidString: "00000000-0000-0000-0000-000000000777")!
        let producer = Task {
            for sequence in 0 ..< chunkCount {
                try await channel.producer.send(VocelloQwen3AudioChunkEvent(
                    generationID: generationID,
                    sequence: sequence,
                    samples: [Float(sequence)],
                    sampleRate: 24_000
                ))
            }
            await channel.producer.finish()
        }

        var iterator = channel.consumer.makeAsyncIterator()
        var expectedSequence = 0
        while let observed = try await iterator.next() {
            XCTAssertEqual(observed.sequence, expectedSequence)
            expectedSequence += 1
        }
        try await producer.value

        XCTAssertEqual(expectedSequence, chunkCount)
        let statistics = await channel.consumer.statistics()
        XCTAssertLessThanOrEqual(statistics.highWaterFrames, capacityFrames)
    }

    func testReplayLatestIsIndependentAndCoalescesProgress() async {
        let session = makeSession()
        let prepared = VocelloQwen3PreparedEvent(
            generationID: session.generationID,
            model: modelIdentity,
            mode: .customVoice,
            elapsedMilliseconds: 10
        )
        await session.publishPrepared(prepared)

        let preparedSnapshot = await session.prepared.snapshot()
        XCTAssertEqual(preparedSnapshot, prepared)
        let stream = session.prepared.updates()
        var iterator = stream.makeAsyncIterator()
        let replayed = await iterator.next()
        XCTAssertEqual(replayed, prepared)

        for value in 1 ... 16 {
            await session.publishProgress(VocelloQwen3ProgressEvent(
                generationID: session.generationID,
                generatedTokenCount: value,
                emittedAudioFrameCount: value * 100,
                elapsedMilliseconds: value
            ))
        }
        let latestProgress = await session.progress.snapshot()
        XCTAssertEqual(latestProgress?.generatedTokenCount, 16)
    }

    /// The engine publishes progress once per chunk-level signal. A per-token
    /// signal only raises the counts the next publication carries, so the
    /// per-frame loop pays no extra actor hop for a slot the product never
    /// reads.
    func testOnlyChunkLevelSignalsPublishProgress() {
        XCTAssertFalse(VocelloQwen3GenerationSignal.token(7).publishesProgress)
        XCTAssertFalse(VocelloQwen3GenerationSignal.codecFrame([1, 2, 3]).publishesProgress)
        XCTAssertTrue(VocelloQwen3GenerationSignal.prepared.publishesProgress)
        XCTAssertTrue(VocelloQwen3GenerationSignal.audio([0, 0.1]).publishesProgress)
    }

    func testModelTerminalDoesNotRequireProgressOrDiagnosticSubscribers() async throws {
        let session = makeSession()
        let prepared = VocelloQwen3PreparedEvent(
            generationID: session.generationID,
            model: modelIdentity,
            mode: .customVoice,
            elapsedMilliseconds: 8
        )
        await session.publishPrepared(prepared)
        let terminal = VocelloQwen3TerminalEvent(
            generationID: session.generationID,
            outcome: .completed(.endOfSequence),
            generatedTokenCount: 12,
            emittedAudioFrameCount: 48,
            elapsedMilliseconds: 20
        )

        await session.resolveModelTerminal(terminal)
        let observedTerminal = await session.waitForModelTermination()
        XCTAssertEqual(observedTerminal, terminal)
        let audioConsumer = try await session.claimAudioConsumer()
        var audio = audioConsumer.makeAsyncIterator()
        let audioEnd = try? await audio.next()
        XCTAssertNil(audioEnd)

        let latePreparedUpdates = session.prepared.updates()
        var latePreparedIterator = latePreparedUpdates.makeAsyncIterator()
        let latePreparedValue = await latePreparedIterator.next()
        let latePreparedEnd = await latePreparedIterator.next()
        XCTAssertEqual(latePreparedValue, prepared)
        XCTAssertNil(latePreparedEnd)
    }

    func testFinalizationAcknowledgementIsIdempotentButStaleSafe() async throws {
        let session = makeSession()
        let first = try await session.acknowledgeProductFinalization(
            generationID: session.generationID,
            leaseID: session.leaseID,
            token: session.finalizationToken,
            disposition: .published
        )
        let repeated = try await session.acknowledgeProductFinalization(
            generationID: session.generationID,
            leaseID: session.leaseID,
            token: session.finalizationToken,
            disposition: .published
        )
        XCTAssertEqual(first, .accepted)
        XCTAssertEqual(repeated, .alreadyAcknowledged)
        let finalization = await session.waitForProductFinalization()
        XCTAssertEqual(finalization, .published)

        do {
            _ = try await session.acknowledgeProductFinalization(
                generationID: session.generationID,
                leaseID: session.leaseID,
                token: session.finalizationToken,
                disposition: .aborted(.runtime)
            )
            XCTFail("conflicting acknowledgement must fail")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3SessionError,
                .conflictingFinalizationAcknowledgement
            )
        }

        let newer = VocelloQwen3ClassifiedGenerationSession(
            generationID: session.generationID,
            leaseID: UUID(),
            audioCapacityFrames: 16,
            diagnosticCapacity: 4
        )
        do {
            _ = try await newer.acknowledgeProductFinalization(
                generationID: newer.generationID,
                leaseID: newer.leaseID,
                token: session.finalizationToken,
                disposition: .published
            )
            XCTFail("an older generation token must not release a newer lease")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .invalidFinalizationIdentity)
        }
    }

    func testDiagnosticsAreBoundedAndReportEviction() async {
        let session = makeSession(diagnosticCapacity: 2)
        for value in 1 ... 3 {
            await session.recordDiagnostic(VocelloQwen3DiagnosticEvent(
                generationID: session.generationID,
                phase: .synthesis,
                disposition: .observed,
                generatedTokenCount: value
            ))
        }

        let snapshot = await session.diagnostics.snapshot()
        XCTAssertEqual(snapshot.events.map(\.generatedTokenCount), [2, 3])
        XCTAssertEqual(snapshot.droppedEventCount, 1)
    }

    func testCancellationControllerPreservesFirstReasonAndCancelsLateTask() {
        let controller = VocelloQwen3CancellationController()
        XCTAssertTrue(controller.request(.memoryPressure))
        XCTAssertFalse(controller.request(.shutdown))
        XCTAssertEqual(controller.reason, .memoryPressure)

        let cancelled = expectation(description: "late task cancellation action")
        controller.installCancelAction { cancelled.fulfill() }
        wait(for: [cancelled], timeout: 1)
    }

    private var modelIdentity: VocelloQwen3ModelIdentity {
        VocelloQwen3ModelIdentity(
            modelID: "fixture",
            repositoryID: "fixture/repository",
            revision: "fixture-revision",
            artifactVersion: "fixture-v1"
        )
    }

    private func makeSession(
        diagnosticCapacity: Int = 4
    ) -> VocelloQwen3ClassifiedGenerationSession {
        VocelloQwen3ClassifiedGenerationSession(
            generationID: UUID(),
            leaseID: UUID(),
            audioCapacityFrames: 16,
            diagnosticCapacity: diagnosticCapacity
        )
    }

    private func chunk(
        sequence: Int,
        samples: [Float]
    ) -> VocelloQwen3AudioChunkEvent {
        VocelloQwen3AudioChunkEvent(
            generationID: UUID(uuidString: "00000000-0000-0000-0000-000000000777")!,
            sequence: sequence,
            samples: samples,
            sampleRate: 24_000
        )
    }
}

private enum ConsumerDrainFixtureError: Error, Equatable, Sendable {
    case failed
}
