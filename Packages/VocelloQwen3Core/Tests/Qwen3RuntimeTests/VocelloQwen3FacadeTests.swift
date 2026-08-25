@testable import VocelloQwen3Core
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
import MLXAudioTTS
@preconcurrency import MLXLMCommon
import XCTest

final class VocelloQwen3FacadeTests: XCTestCase {
    func testActorRequestCarriesExactCurrentChunkSchedulesAndLegacyDecodeDefaults() throws {
        let cases: [(VocelloQwen3SynthesisInput, Int, Int)] = [
            (.customVoice(speakerID: "fixture", deliveryInstruction: nil), 7, 7),
            (.voiceDesign(description: "fixture"), 7, 14),
            (.voiceClone(referenceID: "fixture"), 7, 14),
        ]
        for (input, expectedFirst, expectedLater) in cases {
            let request = VocelloQwen3SynthesisRequest(
                generationID: UUID(),
                text: "Chunk schedule fixture.",
                language: "en-US",
                input: input,
                sampling: VocelloQwen3SamplingConfiguration(
                    maxNewTokens: 32,
                    temperature: 0.8,
                    topP: 0.9,
                    topK: 50,
                    repetitionPenalty: 1,
                    seed: 1
                ),
                memory: .compatibilityDefault
            )
            XCTAssertEqual(request.chunking.firstCodecFrames, expectedFirst)
            XCTAssertEqual(request.chunking.laterCodecFrames, expectedLater)

            var object = try XCTUnwrap(
                JSONSerialization.jsonObject(with: JSONEncoder().encode(request))
                    as? [String: Any]
            )
            object.removeValue(forKey: "chunking")
            object.removeValue(forKey: "executionStyle")
            let legacyData = try JSONSerialization.data(withJSONObject: object)
            let decoded = try JSONDecoder().decode(
                VocelloQwen3SynthesisRequest.self,
                from: legacyData
            )
            XCTAssertEqual(decoded.chunking, request.chunking)
            XCTAssertEqual(decoded.executionStyle, .streaming)
        }
    }

    func testCompatibilityProducerRejectsChunkControlsItDoesNotImplement() {
        let capabilities = VocelloQwen3CapabilitySet([.streaming, .customVoice])
        let unsupported: [VocelloQwen3StreamChunkConfiguration] = [
            VocelloQwen3StreamChunkConfiguration(
                firstCodecFrames: 7,
                laterCodecFrames: 7,
                pendingFrameLimit: 14
            ),
            VocelloQwen3StreamChunkConfiguration(
                firstCodecFrames: 7,
                laterCodecFrames: 7,
                pendingFrameLimit: 7,
                materializationLeadSteps: 1
            ),
            VocelloQwen3StreamChunkConfiguration(
                firstCodecFrames: 7,
                laterCodecFrames: 7,
                pendingFrameLimit: 7,
                evaluationPolicy: .deferred
            ),
        ]

        for chunking in unsupported {
            let request = VocelloQwen3SynthesisRequest(
                generationID: UUID(),
                text: "Unsupported chunk control fixture.",
                language: "en-US",
                input: .customVoice(speakerID: "fixture", deliveryInstruction: nil),
                sampling: VocelloQwen3SamplingConfiguration(
                    maxNewTokens: 32,
                    temperature: 0.8,
                    topP: 0.9,
                    topK: 50,
                    repetitionPenalty: 1,
                    seed: 1
                ),
                memory: .compatibilityDefault,
                chunking: chunking
            )
            XCTAssertThrowsError(try request.validated(for: capabilities)) { error in
                XCTAssertEqual(
                    error as? VocelloQwen3ContractError,
                    .invalidChunkConfiguration
                )
            }
        }
    }

    func testCapabilityInventoryIsUniqueAndDeterministic() {
        let capabilities = VocelloQwen3CapabilitySet([
            .voiceClone, .streaming, .voiceClone, .audioOnlyClone,
        ])

        XCTAssertEqual(capabilities.values, [.audioOnlyClone, .streaming, .voiceClone])
        XCTAssertTrue(capabilities.supports(.voiceClone))
        XCTAssertFalse(capabilities.supports(.voiceDesign))
    }

    func testSynthesisRequestValidationPreservesTypedMode() throws {
        let request = VocelloQwen3SynthesisRequest(
            generationID: UUID(),
            text: "A deterministic facade request.",
            language: "en-US",
            input: .voiceClone(referenceID: "fixture-clone"),
            sampling: VocelloQwen3SamplingConfiguration(
                maxNewTokens: 256,
                temperature: 0.9,
                topP: 0.95,
                topK: 50,
                repetitionPenalty: 1.05
            ),
            memory: VocelloQwen3MemoryConfiguration(
                clearCacheOnStreamChunk: true,
                tokenMemoryClearCadence: 24,
                talkerKVGeneratedWindow: 384
            )
        )

        let validated = try request.validated(
            for: VocelloQwen3CapabilitySet([.streaming, .voiceClone, .audioOnlyClone])
        )
        XCTAssertEqual(validated.mode, .voiceClone)
    }

    func testUnsupportedModeFailsClosed() {
        let request = VocelloQwen3SynthesisRequest(
            generationID: UUID(),
            text: "Design a voice.",
            language: "en-US",
            input: .voiceDesign(description: "Calm and resonant"),
            sampling: VocelloQwen3SamplingConfiguration(
                maxNewTokens: 64,
                temperature: 0.8,
                topP: 0.9,
                topK: 50,
                repetitionPenalty: 1
            ),
            memory: VocelloQwen3MemoryConfiguration(
                clearCacheOnStreamChunk: true,
                tokenMemoryClearCadence: 16
            )
        )

        XCTAssertThrowsError(
            try request.validated(for: VocelloQwen3CapabilitySet([.customVoice]))
        ) { error in
            XCTAssertEqual(error as? VocelloQwen3ContractError, .unsupportedMode(.voiceDesign))
        }
    }

    func testTerminalOutcomesRoundTripWithoutStringInference() throws {
        let values: [VocelloQwen3TerminalOutcome] = [
            .completed(.endOfSequence),
            .cancelled(.memoryPressure),
            .failed(.incompatibleModel),
        ]
        let data = try JSONEncoder().encode(values)
        XCTAssertEqual(try JSONDecoder().decode([VocelloQwen3TerminalOutcome].self, from: data), values)
    }

    func testTypedDiagnosticAdapterDropsArbitraryCompatibilityDetails() {
        let event = VocelloQwen3Runtime.typedDiagnosticEvent(
            forCompatibilityAction: "tts-load-after-qwen-from-prepared-directory"
        )
        XCTAssertEqual(event.phase, .modelLoad)
        XCTAssertEqual(event.disposition, .completed)
        XCTAssertNil(event.failureCode)
    }

    func testOwnedCachePolicyPreservesDefaultAndFixedDirectoryBehavior() {
        XCTAssertEqual(
            VocelloQwen3CachePolicy.systemDefault.compatibilityValue.cacheDirectory,
            HubCache.default.cacheDirectory
        )
        let fixed = URL(fileURLWithPath: "/tmp/vocello-qwen3-cache-fixture", isDirectory: true)
        XCTAssertEqual(
            VocelloQwen3CachePolicy.directory(fixed).compatibilityValue.cacheDirectory,
            fixed
        )
    }

    func testCompatibilityAdapterCarriesCompleteRequestLocalSamplingPolicy() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let loaded = try makeLoadedFixture(compatibilityModel: compatibilityModel)
        let sampling = VocelloQwen3SamplingConfiguration(
            effectiveSeed: 7,
            talker: VocelloQwen3SamplingStage(
                temperature: 0.73,
                topP: 0.87,
                topK: 49,
                minP: 0.02
            ),
            subtalker: VocelloQwen3SamplingStage(
                temperature: 0.61,
                topP: 0.81,
                topK: 37,
                minP: 0.01
            ),
            repetitionPenalty: 1.17,
            maxNewTokens: 321,
            requestedSeed: 7
        )
        _ = try await loaded.generateCustomVoice(
            text: "Capture every supported sampling field.",
            language: "en-US",
            speaker: "fixture-speaker",
            instruction: nil,
            sampling: sampling,
            memory: VocelloQwen3MemoryConfiguration(
                clearCacheOnStreamChunk: false,
                tokenMemoryClearCadence: 37,
                talkerKVGeneratedWindow: 192
            )
        )

        let captured = try XCTUnwrap(compatibilityModel.capturedGenerationParameters)
        XCTAssertEqual(captured.maxTokens, sampling.maxNewTokens)
        XCTAssertEqual(captured.temperature, sampling.temperature, accuracy: 0.0001)
        XCTAssertEqual(captured.topP, sampling.topP, accuracy: 0.0001)
        XCTAssertEqual(captured.repetitionPenalty, sampling.repetitionPenalty)
        XCTAssertEqual(sampling.topK, 49)
        XCTAssertEqual(sampling.seed, 7)

        let capturedPolicy = try XCTUnwrap(compatibilityModel.capturedSamplingPolicy)
        XCTAssertEqual(capturedPolicy.algorithmVersion, 2)
        XCTAssertEqual(capturedPolicy.effectiveSeed, 7)
        XCTAssertEqual(capturedPolicy.talker.topK, 49)
        XCTAssertEqual(capturedPolicy.talker.minP, 0.02, accuracy: 0.0001)
        XCTAssertEqual(capturedPolicy.subtalker.temperature, 0.61, accuracy: 0.0001)
        XCTAssertEqual(capturedPolicy.subtalker.topP, 0.81, accuracy: 0.0001)
        XCTAssertEqual(capturedPolicy.subtalker.topK, 37)
        XCTAssertEqual(capturedPolicy.subtalker.minP, 0.01, accuracy: 0.0001)
        XCTAssertEqual(capturedPolicy.repetitionPenalty, 1.17, accuracy: 0.0001)
        XCTAssertEqual(capturedPolicy.maximumCodecTokens, 321)
        XCTAssertEqual(
            compatibilityModel.capturedMemoryPolicies,
            [Qwen3RequestMemoryPolicy(
                clearCacheOnStreamChunkEmit: false,
                tokenMemoryClearCadence: 37,
                talkerKVGeneratedWindow: 192
            )]
        )
        XCTAssertEqual(compatibilityModel.capturedStreamingIntervals, [])
    }

    func testRequestLocalMemoryPoliciesDoNotBleedAcrossSequentialStreams() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let loaded = try makeLoadedFixture(compatibilityModel: compatibilityModel)
        let sampling = VocelloQwen3SamplingConfiguration(
            effectiveSeed: 99,
            talker: .init(temperature: 0.9, topP: 0.95, topK: 50, minP: 0),
            subtalker: .init(temperature: 0.9, topP: 0.95, topK: 50, minP: 0),
            repetitionPenalty: 1.05,
            maxNewTokens: 64,
            requestedSeed: 99
        )
        let first = VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: false,
            tokenMemoryClearCadence: 17,
            talkerKVGeneratedWindow: 128
        )
        let second = VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: true,
            tokenMemoryClearCadence: 83,
            talkerKVGeneratedWindow: nil
        )

        for memory in [first, second] {
            _ = try await loaded.generateCustomVoice(
                text: "A request-local memory fixture.",
                language: "en-US",
                speaker: "fixture-speaker",
                instruction: nil,
                sampling: sampling,
                memory: memory
            )
        }

        XCTAssertEqual(
            compatibilityModel.capturedMemoryPolicies,
            [
                Qwen3RequestMemoryPolicy(
                    clearCacheOnStreamChunkEmit: false,
                    tokenMemoryClearCadence: 17,
                    talkerKVGeneratedWindow: 128
                ),
                Qwen3RequestMemoryPolicy(
                    clearCacheOnStreamChunkEmit: true,
                    tokenMemoryClearCadence: 83,
                    talkerKVGeneratedWindow: nil
                ),
            ]
        )
    }

    func testTerminalStatePreservesFirstCancellationReason() async {
        let state = VocelloQwen3TerminalState()
        await state.requestCancellation(.memoryPressure)
        await state.requestCancellation(.shutdown)
        let reason = await state.requestedCancellationReason()
        XCTAssertEqual(reason, .memoryPressure)
    }

    func testEngineReservationCannotOpenBeforeMandatoryAudioClaim() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )

        let reservedSnapshot = await engine.snapshot()
        XCTAssertEqual(reservedSnapshot.phase, .reservedGeneration)
        XCTAssertNil(compatibilityModel.capturedGenerationParameters)

        do {
            try await engine.open(reservation.id)
            XCTFail("generation must remain inert until output owns audio")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .audioConsumerNotClaimed)
        }

        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        let terminal = await reservation.session.waitForModelTermination()
        try await drain.value
        XCTAssertEqual(terminal.outcome, .completed(.endOfSequence))

        let awaitingSnapshot = await engine.snapshot()
        XCTAssertEqual(awaitingSnapshot.phase, .awaitingProductFinalization)
        XCTAssertEqual(awaitingSnapshot.activeOperation, reservation.lease)
        do {
            _ = try await engine.reserveGeneration(
                request: makeCustomRequest(generationID: UUID()),
                audioCapacityFrames: 24_000
            )
            XCTFail("model EOS must not release product admission")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .operationInProgress(.generation))
        }

        let acknowledged = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        XCTAssertEqual(acknowledged, .accepted)
        let repeated = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        XCTAssertEqual(repeated, .alreadyAcknowledged)
        let readySnapshot = await engine.snapshot()
        XCTAssertEqual(readySnapshot.phase, .ready)
        XCTAssertNil(readySnapshot.activeOperation)
    }

    func testEngineDirectProducerBackpressuresUntilMandatoryConsumerDrains() async throws {
        let generationID = UUID()
        let stream = AsyncThrowingStream<AudioGeneration, Error> { continuation in
            continuation.yield(.audio(MLXArray([Float(0.1), Float(0.2)])))
            continuation.yield(.audio(MLXArray([Float(0.3), Float(0.4)])))
            continuation.finish()
        }
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(streamOverride: stream)
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: generationID),
            audioCapacityFrames: 2
        )
        let audio = try await reservation.session.claimAudioConsumer()

        try await engine.open(reservation.id)
        let suspensionDeadline = ContinuousClock.now.advanced(by: .seconds(2))
        while ContinuousClock.now < suspensionDeadline {
            if await audio.statistics().producerSuspensionCount > 0 { break }
            await Task.yield()
        }

        let blockedStatistics = await audio.statistics()
        XCTAssertEqual(blockedStatistics.capacityFrames, 2)
        XCTAssertEqual(blockedStatistics.highWaterFrames, 2)
        XCTAssertEqual(blockedStatistics.producerSuspensionCount, 1)
        let generating = await engine.snapshot()
        XCTAssertEqual(generating.phase, .generating)

        var iterator = audio.makeAsyncIterator()
        let first = try await iterator.next()
        let second = try await iterator.next()
        let end = try await iterator.next()
        let terminal = await reservation.session.waitForModelTermination()

        XCTAssertEqual(first?.sequence, 0)
        XCTAssertEqual(first?.samples, [0.1, 0.2])
        XCTAssertEqual(second?.sequence, 1)
        XCTAssertEqual(second?.samples, [0.3, 0.4])
        XCTAssertNil(end)
        XCTAssertEqual(terminal.outcome, .completed(.endOfSequence))
        XCTAssertEqual(terminal.emittedAudioFrameCount, 4)

        _ = try await engine.acknowledgeProductFinalization(
            generationID: generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        let ready = await engine.snapshot()
        XCTAssertEqual(ready.phase, .ready)
    }

    func testEngineMapsTypedProducerFailureWithoutDiagnosticInference() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(generationEndReason: "failed")
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        try await engine.open(reservation.id)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .failed(.runtime))

        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .aborted(.runtime)
        )
    }

    func testEngineMapsTypedMaximumTokenFinishReason() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(
                    generationEndReason: "token_cap"
                )
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        try await engine.open(reservation.id)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .completed(.maximumTokens))
        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
    }

    func testEngineMapsTypedProducerCancellationAndRecordsReason() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(
                    generationEndReason: "cancelled"
                )
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        try await engine.open(reservation.id)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .cancelled(.user))
        XCTAssertEqual(reservation.session.cancellation.reason, .user)
        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .aborted(.runtime)
        )
    }

    func testEngineRejectsNominalSuccessThatProducedNoAudio() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(emitsAudio: false)
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        try await engine.open(reservation.id)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .failed(.runtime))
        XCTAssertEqual(terminal.emittedAudioFrameCount, 0)

        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .aborted(.runtime)
        )
    }

    func testEngineAbortBeforeOpenHasNoGenerationSideEffects() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )

        try await engine.abortReservation(reservation.id, reason: .shutdown)
        XCTAssertNil(compatibilityModel.capturedGenerationParameters)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .cancelled(.shutdown))
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testAbortingReservationRejectsOpenAndDuplicateAbortJoinsFinalization() async throws {
        let ownerGate = SuspendedEngineOperationGate()
        let joinerGate = SuspendedEngineOperationGate()
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel),
            abortLifecycleHook: { event in
                switch event {
                case .owner:
                    await ownerGate.suspend()
                case .joiner:
                    await joinerGate.suspend()
                }
            }
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        let owner = Task {
            try await engine.abortReservation(reservation.id, reason: .shutdown)
        }
        await ownerGate.waitUntilEntered()

        do {
            try await engine.open(reservation.id)
            XCTFail("an abort-owned reservation must never reopen generation")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidReservation)
        }

        let joiner = Task {
            try await engine.abortReservation(reservation.id, reason: .superseded)
        }
        await joinerGate.waitUntilEntered()
        var snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .awaitingProductFinalization)
        XCTAssertEqual(snapshot.activeOperation, reservation.lease)
        XCTAssertNil(compatibilityModel.capturedGenerationParameters)

        await joinerGate.release()
        await ownerGate.release()
        try await owner.value
        try await joiner.value

        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .cancelled(.shutdown))
        snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testReservedGenerationCancellationIsTerminalWithoutSeparateAbort() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )

        try await engine.cancelGeneration(reservation.id, reason: .superseded)

        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .cancelled(.superseded))
        XCTAssertEqual(reservation.session.cancellation.reason, .superseded)
        XCTAssertNil(compatibilityModel.capturedGenerationParameters)
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testCriticalPressureReasonSurvivesOpenFailureAndReservationAbort() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()

        await engine.observeMemoryPressure(.critical)
        do {
            try await engine.open(reservation.id)
            XCTFail("critical pressure must keep an inert reservation closed")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .admissionClosedForMemoryRelief
            )
        }

        try await engine.abortReservation(reservation.id, reason: .shutdown)
        let terminal = await reservation.session.waitForModelTermination()
        XCTAssertEqual(terminal.outcome, .cancelled(.memoryPressure))
        XCTAssertEqual(reservation.session.cancellation.reason, .memoryPressure)
        XCTAssertNil(compatibilityModel.capturedGenerationParameters)

        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertTrue(snapshot.pressure.admissionClosed)
    }

    func testEngineRejectsStaleFinalizationTokenForNewerReservation() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let first = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let staleToken = first.session.finalizationToken
        try await engine.abortReservation(first.id)

        let second = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        do {
            _ = try await second.session.acknowledgeProductFinalization(
                generationID: second.session.generationID,
                leaseID: second.lease.id,
                token: staleToken,
                disposition: .published
            )
            XCTFail("stale finalization identity must not release a newer lease")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .invalidFinalizationIdentity)
        }
        try await engine.abortReservation(second.id)
    }

    func testEngineReliefIsTheOnlyTransitionThatReopensCriticalAdmission() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        await engine.observeMemoryPressure(.critical)
        await engine.observeMemoryPressure(.warning)
        await engine.observeMemoryPressure(.normal)

        var snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.pressure.level, .critical)
        XCTAssertTrue(snapshot.pressure.admissionClosed)

        try await engine.relieveMemory()

        snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertEqual(snapshot.pressure.level, .normal)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testEngineFullUnloadReliefRunsWhileCriticalAdmissionIsClosed() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let original = await engine.snapshot()
        await engine.observeMemoryPressure(.critical)

        try await engine.relieveMemory(.fullUnload)

        let snapshot = await engine.snapshot()
        XCTAssertNil(snapshot.loadedModel)
        XCTAssertEqual(snapshot.modelEpoch, original.modelEpoch + 1)
        XCTAssertEqual(snapshot.phase, .unloaded)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertEqual(snapshot.pressure.level, .normal)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testEngineCarriesGenerationLeaseThroughCriticalFinalizationRelief() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        let result = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )

        XCTAssertEqual(result, .accepted)
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertEqual(snapshot.pressure.level, .normal)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
        let repeated = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        XCTAssertEqual(repeated, .alreadyAcknowledged)
        let repeatedRelief = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published,
            action: .cacheTrim
        )
        XCTAssertEqual(repeatedRelief, .alreadyAcknowledged)
        do {
            _ = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: reservation.session.finalizationToken,
                disposition: .published,
                action: .fullUnload
            )
            XCTFail("a completed cache trim cannot masquerade as full unload")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .finalizationAlreadyReleased
            )
        }
    }

    func testAtomicReliefCannotClaimAPreviouslyReleasedFinalization() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        do {
            _ = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: reservation.session.finalizationToken,
                disposition: .published,
                action: .fullUnload
            )
            XCTFail("a released generation lease cannot authorize later atomic relief")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .finalizationAlreadyReleased
            )
        }

        var snapshot = await engine.snapshot()
        XCTAssertNotNil(snapshot.loadedModel)
        XCTAssertTrue(snapshot.pressure.admissionClosed)
        try await engine.relieveMemory(.fullUnload)
        snapshot = await engine.snapshot()
        XCTAssertNil(snapshot.loadedModel)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testEngineCarriesGenerationLeaseThroughCriticalFullUnload() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let original = await engine.snapshot()
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        let result = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published,
            action: .fullUnload
        )

        XCTAssertEqual(result, .accepted)
        let snapshot = await engine.snapshot()
        XCTAssertNil(snapshot.loadedModel)
        XCTAssertEqual(snapshot.modelEpoch, original.modelEpoch + 1)
        XCTAssertEqual(snapshot.phase, .unloaded)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertEqual(snapshot.pressure.level, .normal)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testDuplicateAtomicReliefIsRejectedUntilOwnerCompletes() async throws {
        let reliefGate = SuspendedEngineOperationGate()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel()),
            memoryReliefHook: { action in
                if action == .fullUnload {
                    await reliefGate.suspend()
                }
            }
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        let owner = Task {
            try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: reservation.session.finalizationToken,
                disposition: .published,
                action: .fullUnload
            )
        }
        await reliefGate.waitUntilEntered()

        do {
            _ = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: reservation.session.finalizationToken,
                disposition: .published,
                action: .fullUnload
            )
            XCTFail("a duplicate relief request must not report early completion")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .operationInProgress(.memoryRelief)
            )
        }

        await reliefGate.release()
        let ownerResult = try await owner.value
        XCTAssertEqual(ownerResult, .accepted)
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .unloaded)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testRejectedAtomicReliefAcknowledgementReleasesItsClaim() async throws {
        let staleEngine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let staleReservation = try await staleEngine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let staleToken = staleReservation.session.finalizationToken
        try await staleEngine.abortReservation(staleReservation.id)

        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        do {
            _ = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: staleToken,
                disposition: .published,
                action: .cacheTrim
            )
            XCTFail("a stale finalization token must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .invalidFinalizationIdentity)
        }

        let result = try await engine.acknowledgeProductFinalizationAndRelieveMemory(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published,
            action: .cacheTrim
        )
        XCTAssertEqual(result, .accepted)
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testRejectedAtomicReliefCannotStrandConcurrentOrdinaryFinalization() async throws {
        let claimGate = SuspendedEngineOperationGate()
        let staleEngine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let staleReservation = try await staleEngine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let staleToken = staleReservation.session.finalizationToken
        try await staleEngine.abortReservation(staleReservation.id)

        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel()),
            finalizationReliefClaimHook: {
                await claimGate.suspend()
            }
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value
        await engine.observeMemoryPressure(.critical)

        let rejectedRelief = Task {
            try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: staleToken,
                disposition: .published,
                action: .cacheTrim
            )
        }
        await claimGate.waitUntilEntered()

        let ordinaryFinalization = Task {
            try await engine.acknowledgeProductFinalization(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: reservation.session.finalizationToken,
                disposition: .published
            )
        }
        let acceptedDisposition = await reservation.session.waitForProductFinalization()
        XCTAssertEqual(acceptedDisposition, .published)
        await claimGate.release()

        do {
            _ = try await rejectedRelief.value
            XCTFail("a stale relief acknowledgement must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .invalidFinalizationIdentity)
        }
        _ = try await ordinaryFinalization.value

        var snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertTrue(snapshot.pressure.admissionClosed)

        try await engine.relieveMemory(.cacheTrim)
        snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
        XCTAssertFalse(snapshot.pressure.admissionClosed)
    }

    func testOrdinaryFinalizerOwnsReleaseAfterRejectedReliefClearsClaim() async throws {
        let rollbackGate = SuspendedEngineOperationGate()
        let staleEngine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )
        let staleReservation = try await staleEngine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let staleToken = staleReservation.session.finalizationToken
        try await staleEngine.abortReservation(staleReservation.id)

        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel()),
            finalizationReliefRollbackHook: {
                await rollbackGate.suspend()
            }
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let audio = try await reservation.session.claimAudioConsumer()
        let drain = Task {
            for try await _ in audio {}
        }
        try await engine.open(reservation.id)
        _ = await reservation.session.waitForModelTermination()
        try await drain.value

        let rejectedRelief = Task {
            try await engine.acknowledgeProductFinalizationAndRelieveMemory(
                generationID: reservation.session.generationID,
                leaseID: reservation.lease.id,
                token: staleToken,
                disposition: .published,
                action: .cacheTrim
            )
        }
        await rollbackGate.waitUntilEntered()

        let ordinaryResult = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
        XCTAssertEqual(ordinaryResult, .accepted)
        await rollbackGate.release()

        do {
            _ = try await rejectedRelief.value
            XCTFail("a stale relief acknowledgement must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3SessionError, .invalidFinalizationIdentity)
        }

        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testEnginePrewarmIsActorOwnedAndReturnsToReady() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: FacadeCompatibilityModel())
        )

        try await engine.prewarm(request: makeCustomRequest(generationID: UUID()))

        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testSuspendedPrewarmRejectsReentrantGenerationReservation() async throws {
        let prewarmGate = SuspendedEngineOperationGate()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(prewarmGate: prewarmGate)
            )
        )
        let prewarmRequest = makeCustomRequest(generationID: UUID())
        let prewarm = Task {
            try await engine.prewarm(request: prewarmRequest)
        }

        await prewarmGate.waitUntilEntered()
        do {
            _ = try await engine.reserveGeneration(
                request: makeCustomRequest(generationID: UUID()),
                audioCapacityFrames: 24_000
            )
            XCTFail("actor reentrancy must not admit work over a suspended prewarm lease")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .operationInProgress(.prewarm)
            )
        }

        await prewarmGate.release()
        try await prewarm.value
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testCancelledSuspendedProducerCannotPublishLateStateOrReleaseNewerLease() async throws {
        let producerGate = SuspendedEngineOperationGate()
        let compatibilityModel = FacadeCompatibilityModel(producerGate: producerGate)
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let first = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await first.session.claimAudioConsumer()
        try await engine.open(first.id)
        await producerGate.waitUntilEntered()

        try await engine.cancelGeneration(first.id, reason: .superseded)
        await producerGate.release()
        let firstTerminal = await first.session.waitForModelTermination()
        XCTAssertEqual(firstTerminal.outcome, .cancelled(.superseded))
        XCTAssertEqual(firstTerminal.generatedTokenCount, 0)
        XCTAssertEqual(firstTerminal.emittedAudioFrameCount, 0)
        let latePrepared = await first.session.prepared.snapshot()
        XCTAssertNil(latePrepared)

        var snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .awaitingProductFinalization)
        XCTAssertEqual(snapshot.activeOperation, first.lease)
        _ = try await engine.acknowledgeProductFinalization(
            generationID: first.session.generationID,
            leaseID: first.lease.id,
            token: first.session.finalizationToken,
            disposition: .aborted(.runtime)
        )

        let second = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        do {
            _ = try await engine.acknowledgeProductFinalization(
                generationID: first.session.generationID,
                leaseID: first.lease.id,
                token: first.session.finalizationToken,
                disposition: .aborted(.runtime)
            )
            XCTFail("a late completion must not release the newer reservation")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .modelHasNotTerminated
            )
        }
        snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .reservedGeneration)
        XCTAssertEqual(snapshot.activeOperation, second.lease)
        try await engine.cancelGeneration(second.id, reason: .shutdown)
    }

    func testPreparedReplayWaitsForProducerPreparationBoundary() async throws {
        let producerGate = SuspendedEngineOperationGate()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(producerGate: producerGate)
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        _ = try await reservation.session.claimAudioConsumer()
        try await engine.open(reservation.id)

        await producerGate.waitUntilEntered()
        let beforeProducerPrepared = await reservation.session.prepared.snapshot()
        XCTAssertNil(beforeProducerPrepared)

        await producerGate.release()
        _ = await reservation.session.waitForModelTermination()
        let afterProducerPrepared = await reservation.session.prepared.snapshot()
        XCTAssertEqual(afterProducerPrepared?.generationID, reservation.session.generationID)
        _ = try await engine.acknowledgeProductFinalization(
            generationID: reservation.session.generationID,
            leaseID: reservation.lease.id,
            token: reservation.session.finalizationToken,
            disposition: .published
        )
    }

    func testClonePromptConstructionCannotOverlapGenerationLease() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: compatibilityModel,
                capabilities: VocelloQwen3CapabilitySet([
                    .streaming,
                    .customVoice,
                    .voiceClone,
                ])
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )

        do {
            _ = try await engine.makeCloneHandle(
                referenceSamples: Array(repeating: 0.1, count: 2_400),
                referenceText: "Fixture reference",
                xVectorOnlyMode: false,
                conditioningDigest: String(repeating: "a", count: 64)
            )
            XCTFail("clone prompt construction must share the actor operation lease")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .operationInProgress(.generation)
            )
        }

        try await engine.abortReservation(reservation.id)
    }

    func testCloneHandleBudgetAndReliefInvalidationAreDeterministic() async throws {
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(),
                capabilities: VocelloQwen3CapabilitySet([
                    .streaming,
                    .voiceClone,
                ])
            )
        )
        let first = try await engine.makeCloneHandle(
            referenceSamples: [0.1, 0.2],
            referenceText: nil,
            xVectorOnlyMode: true,
            conditioningDigest: String(repeating: "a", count: 64)
        )
        let second = try await engine.makeCloneHandle(
            referenceSamples: [0.3, 0.4],
            referenceText: nil,
            xVectorOnlyMode: true,
            conditioningDigest: String(repeating: "b", count: 64)
        )

        do {
            _ = try await engine.reserveGeneration(
                request: makeCloneRequest(generationID: UUID()),
                cloneHandle: first,
                audioCapacityFrames: 24_000
            )
            XCTFail("the conservative one-handle budget must evict the oldest prompt")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidCloneHandle)
        }

        let preserved = try await engine.reserveGeneration(
            request: makeCloneRequest(
                generationID: UUID(),
                conditioningDigest: second.conditioningDigest
            ),
            cloneHandle: second,
            audioCapacityFrames: 24_000
        )
        try await engine.abortReservation(preserved.id)
        try await engine.relieveMemory(.cacheTrim)

        let afterBenignTrim = try await engine.reserveGeneration(
            request: makeCloneRequest(
                generationID: UUID(),
                conditioningDigest: second.conditioningDigest
            ),
            cloneHandle: second,
            audioCapacityFrames: 24_000
        )
        try await engine.abortReservation(afterBenignTrim.id)

        let released = await engine.releaseCloneHandle(second)
        let releasedAgain = await engine.releaseCloneHandle(second)
        XCTAssertTrue(released)
        XCTAssertFalse(releasedAgain)
        do {
            _ = try await engine.reserveGeneration(
                request: makeCloneRequest(generationID: UUID()),
                cloneHandle: second,
                audioCapacityFrames: 24_000
            )
            XCTFail("an explicitly released handle must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidCloneHandle)
        }

        let pressureHandle = try await engine.makeCloneHandle(
            referenceSamples: [0.5, 0.6],
            referenceText: nil,
            xVectorOnlyMode: true,
            conditioningDigest: String(repeating: "c", count: 64)
        )

        await engine.observeMemoryPressure(.critical)
        try await engine.relieveMemory(.cacheTrim)
        do {
            _ = try await engine.reserveGeneration(
                request: makeCloneRequest(generationID: UUID()),
                cloneHandle: pressureHandle,
                audioCapacityFrames: 24_000
            )
            XCTFail("critical relief must invalidate actor-owned clone tensors")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidCloneHandle)
        }
    }

    func testProductOutputAdapterFinalizesBeforeReleasingLease() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let sink = RecordingProductOutputSink()
        let terminals = ProductTerminalRecorder()
        let adapter = VocelloQwen3ProductOutputAdapter(
            terminalPublisher: { terminal in
                await terminals.record(terminal)
            }
        )

        let terminal = try await adapter.run(
            engine: engine,
            reservation: reservation,
            sink: sink
        )

        XCTAssertEqual(terminal.disposition, .published)
        let successFinalizeCount = await sink.finalizeCount
        let successAbortCount = await sink.abortCount
        let successTerminalCount = await terminals.values.count
        XCTAssertEqual(successFinalizeCount, 1)
        XCTAssertEqual(successAbortCount, 0)
        XCTAssertEqual(successTerminalCount, 1)
        XCTAssertEqual(
            compatibilityModel.capturedMemoryPolicies,
            [Qwen3RequestMemoryPolicy(
                clearCacheOnStreamChunkEmit: false,
                tokenMemoryClearCadence: 16,
                talkerKVGeneratedWindow: nil
            )]
        )
        XCTAssertEqual(compatibilityModel.capturedStreamingIntervals.count, 1)
        XCTAssertEqual(
            compatibilityModel.capturedStreamingIntervals[0],
            7.0 / 12.5,
            accuracy: 0.000_001
        )
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testProductOutputAdapterDrainsEveryStreamingModeWithTypedEvidence() async throws {
        let cloneConditioningDigest = String(repeating: "a", count: 64)
        let cases: [(VocelloQwen3SynthesisInput, Double, VocelloQwen3CloneHandleCapability?)] = [
            (.customVoice(speakerID: "fixture", deliveryInstruction: nil), 7.0 / 12.5, nil),
            (.voiceDesign(description: "Calm and resonant"), 7.0 / 12.5, nil),
            (.voiceClone(referenceID: cloneConditioningDigest), 7.0 / 12.5, .decoderOnly),
        ]

        for (input, expectedInterval, cloneCapability) in cases {
            let compatibilityModel = FacadeCompatibilityModel(
                emitsInfo: true,
                emitsChunkTimings: true
            )
            let loadedModel = try makeLoadedFixture(
                compatibilityModel: compatibilityModel,
                capabilities: VocelloQwen3CapabilitySet([
                    .streaming,
                    .customVoice,
                    .voiceDesign,
                    .voiceClone,
                ])
            )
            let engine = VocelloQwen3Engine(adoptingCompatibilityModel: loadedModel)
            let cloneHandle: VocelloQwen3CloneHandle?
            if let cloneCapability {
                let prompt = try loadedModel.makeClonePrompt(
                    referenceSamples: [0.1, 0.2],
                    referenceText: nil,
                    xVectorOnlyMode: true
                )
                cloneHandle = try await engine.adoptValidatedClonePrompt(
                    prompt,
                    capability: cloneCapability,
                    conditioningDigest: cloneConditioningDigest
                )
            } else {
                cloneHandle = nil
            }
            let request = makeRequest(
                generationID: UUID(),
                input: input,
                executionStyle: .streaming
            )
            let reservation = try await engine.reserveGeneration(
                request: request,
                cloneHandle: cloneHandle,
                audioCapacityFrames: 24_000
            )
            let sink = RecordingProductOutputSink()
            let previews = PreviewChunkRecorder()
            let adapter = VocelloQwen3ProductOutputAdapter(
                previewPublisher: { chunk in await previews.record(chunk) }
            )

            let terminal = try await adapter.run(
                engine: engine,
                reservation: reservation,
                sink: sink
            )

            let chunks = await sink.chunks
            let previewChunks = await previews.values
            XCTAssertEqual(chunks.map(\.sequence), [0], "mode=\(input.mode)")
            XCTAssertEqual(chunks.first?.frameCount, 1, "mode=\(input.mode)")
            XCTAssertEqual(chunks.first?.timings?.talkerForwardMS, 1, "mode=\(input.mode)")
            XCTAssertEqual(previewChunks.map(\.sequence), [0], "mode=\(input.mode)")
            XCTAssertEqual(terminal.modelTerminal.generationInfo?.generationTokenCount, 1)
            XCTAssertEqual(
                terminal.modelTerminal.diagnostics?.stringFlags["generation_end_reason"],
                "eos"
            )
            XCTAssertEqual(compatibilityModel.capturedStreamingIntervals.count, 1)
            XCTAssertEqual(
                compatibilityModel.capturedStreamingIntervals[0],
                expectedInterval,
                accuracy: 0.000_001
            )
            let snapshot = await engine.snapshot()
            XCTAssertEqual(snapshot.phase, .ready)
            XCTAssertNil(snapshot.activeOperation)
        }
    }

    func testQualityFirstAllModesUseOneAdapterAndSuppressPreview() async throws {
        let cloneConditioningDigest = String(repeating: "b", count: 64)
        let inputs: [VocelloQwen3SynthesisInput] = [
            .customVoice(speakerID: "fixture", deliveryInstruction: nil),
            .voiceDesign(description: "Calm and resonant"),
            .voiceClone(referenceID: cloneConditioningDigest),
        ]

        for input in inputs {
            let compatibilityModel = FacadeCompatibilityModel(emitsInfo: true)
            let loadedModel = try makeLoadedFixture(
                compatibilityModel: compatibilityModel,
                capabilities: VocelloQwen3CapabilitySet([
                    .streaming,
                    .customVoice,
                    .voiceDesign,
                    .voiceClone,
                ])
            )
            let engine = VocelloQwen3Engine(adoptingCompatibilityModel: loadedModel)
            let cloneHandle: VocelloQwen3CloneHandle?
            if input.mode == .voiceClone {
                let prompt = try loadedModel.makeClonePrompt(
                    referenceSamples: [0.1, 0.2],
                    referenceText: nil,
                    xVectorOnlyMode: true
                )
                cloneHandle = try await engine.adoptValidatedClonePrompt(
                    prompt,
                    capability: .decoderOnly,
                    conditioningDigest: cloneConditioningDigest
                )
            } else {
                cloneHandle = nil
            }
            let reservation = try await engine.reserveGeneration(
                request: makeRequest(
                    generationID: UUID(),
                    input: input,
                    executionStyle: .qualityFirst,
                    captureCodecTrace: true
                ),
                cloneHandle: cloneHandle,
                audioCapacityFrames: 24_000
            )
            let sink = RecordingProductOutputSink()
            let previews = PreviewChunkRecorder()
            let adapter = VocelloQwen3ProductOutputAdapter(
                previewPublisher: { chunk in await previews.record(chunk) }
            )

            let terminal = try await adapter.run(
                engine: engine,
                reservation: reservation,
                sink: sink
            )

            let qualityChunks = await sink.chunks
            let qualityPreviews = await previews.values
            let prepared = await reservation.session.prepared.snapshot()
            XCTAssertEqual(qualityChunks.count, 1, "mode=\(input.mode)")
            XCTAssertEqual(qualityPreviews.count, 0, "mode=\(input.mode)")
            XCTAssertNotNil(
                qualityChunks.first?.startupObservations?
                    .firstModelTokenAndAudioCodeMilliseconds,
                "mode=\(input.mode)"
            )
            XCTAssertEqual(terminal.modelTerminal.emittedAudioFrameCount, 1)
            XCTAssertEqual(terminal.modelTerminal.generationInfo?.generationTokenCount, 1)
            XCTAssertEqual(terminal.modelTerminal.codecTrace?.frames, [[1, 2]])
            XCTAssertNotNil(prepared)
            XCTAssertEqual(compatibilityModel.capturedStreamingIntervals, [])
            let snapshot = await engine.snapshot()
            XCTAssertEqual(snapshot.phase, .ready)
        }
    }

    func testQualityFirstWaveformIsSplitAtFrameCapacityWithoutPreviewLoss() async throws {
        let expectedSamples = (0 ..< 10).map { Float($0) / 10 }
        let compatibilityModel = FacadeCompatibilityModel(
            emitsInfo: true,
            qualityFirstAudio: expectedSamples
        )
        let engine = VocelloQwen3Engine(
            adoptingCompatibilityModel: try makeLoadedFixture(
                compatibilityModel: compatibilityModel
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeRequest(
                generationID: UUID(),
                input: .customVoice(
                    speakerID: "fixture",
                    deliveryInstruction: nil
                ),
                executionStyle: .qualityFirst
            ),
            audioCapacityFrames: 3
        )
        let sink = RecordingProductOutputSink()
        let previews = PreviewChunkRecorder()
        let adapter = VocelloQwen3ProductOutputAdapter(
            previewPublisher: { chunk in await previews.record(chunk) }
        )

        let terminal = try await adapter.run(
            engine: engine,
            reservation: reservation,
            sink: sink
        )

        let chunks = await sink.chunks
        let previewChunks = await previews.values
        XCTAssertEqual(chunks.map(\.sequence), [0, 1, 2, 3])
        XCTAssertEqual(chunks.map(\.frameCount), [3, 3, 3, 1])
        XCTAssertTrue(chunks.allSatisfy { $0.frameCount <= 3 })
        XCTAssertEqual(chunks.flatMap(\.samples), expectedSamples)
        XCTAssertEqual(previewChunks.count, 0)
        XCTAssertEqual(terminal.modelTerminal.emittedAudioFrameCount, expectedSamples.count)
        XCTAssertEqual(terminal.disposition, .published)
    }

    func testCloneReservationBindsRequestReferenceToHandleConditioningDigest() async throws {
        let loadedModel = try makeLoadedFixture(
            compatibilityModel: FacadeCompatibilityModel(),
            capabilities: VocelloQwen3CapabilitySet([.streaming, .voiceClone])
        )
        let engine = VocelloQwen3Engine(adoptingCompatibilityModel: loadedModel)
        let prompt = try loadedModel.makeClonePrompt(
            referenceSamples: [0.1, 0.2],
            referenceText: nil,
            xVectorOnlyMode: true
        )
        let conditioningDigest = String(repeating: "e", count: 64)
        let handle = try await engine.adoptValidatedClonePrompt(
            prompt,
            capability: .decoderOnly,
            conditioningDigest: conditioningDigest
        )

        do {
            _ = try await engine.reserveGeneration(
                request: makeCloneRequest(
                    generationID: UUID(),
                    conditioningDigest: String(repeating: "f", count: 64)
                ),
                cloneHandle: handle,
                audioCapacityFrames: 24_000
            )
            XCTFail("a request must not pair a clone identity with another prompt")
        } catch {
            XCTAssertEqual(
                error as? VocelloQwen3EngineError,
                .cloneConditioningIdentityMismatch
            )
        }

        let reservation = try await engine.reserveGeneration(
            request: makeCloneRequest(
                generationID: UUID(),
                conditioningDigest: conditioningDigest
            ),
            cloneHandle: handle,
            audioCapacityFrames: 24_000
        )
        let released = await engine.releaseCloneHandle(handle)
        XCTAssertTrue(released)
        let terminal = try await VocelloQwen3ProductOutputAdapter().run(
            engine: engine,
            reservation: reservation,
            sink: RecordingProductOutputSink()
        )
        XCTAssertEqual(terminal.disposition, .published)
    }

    func testValidatedClonePromptAdoptionRejectsCapabilityAndIdentityMismatch() async throws {
        let loadedModel = try makeLoadedFixture(
            compatibilityModel: FacadeCompatibilityModel(),
            capabilities: VocelloQwen3CapabilitySet([.streaming, .voiceClone])
        )
        let engine = VocelloQwen3Engine(adoptingCompatibilityModel: loadedModel)
        let prompt = try loadedModel.makeClonePrompt(
            referenceSamples: [0.1, 0.2],
            referenceText: nil,
            xVectorOnlyMode: true
        )

        do {
            _ = try await engine.adoptValidatedClonePrompt(
                prompt,
                capability: .encoderAndDecoder,
                conditioningDigest: String(repeating: "c", count: 64)
            )
            XCTFail("prompt capability mismatch must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidCloneHandle)
        }

        let mismatched = prompt.withArtifactMetadata(VocelloQwen3CloneArtifactMetadata(
            modelID: "another-model",
            xVectorOnlyMode: true
        ))
        do {
            _ = try await engine.adoptValidatedClonePrompt(
                mismatched,
                capability: .decoderOnly,
                conditioningDigest: String(repeating: "d", count: 64)
            )
            XCTFail("artifact identity mismatch must fail closed")
        } catch {
            XCTAssertEqual(error as? VocelloQwen3EngineError, .invalidCloneHandle)
        }
    }

    func testProductOutputAdapterAbortsAndReleasesLeaseAfterSinkFailure() async throws {
        let stream = AsyncThrowingStream<AudioGeneration, Error> { continuation in
            continuation.yield(.audio(MLXArray([Float(0.1), Float(0.2)])))
            continuation.finish()
        }
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(
                compatibilityModel: FacadeCompatibilityModel(streamOverride: stream)
            )
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let sink = RecordingProductOutputSink(failOnConsume: true)
        let terminals = ProductTerminalRecorder()
        let adapter = VocelloQwen3ProductOutputAdapter(
            terminalPublisher: { terminal in
                await terminals.record(terminal)
            }
        )

        do {
            _ = try await adapter.run(engine: engine, reservation: reservation, sink: sink)
            XCTFail("sink failure must fail product output")
        } catch {
            XCTAssertEqual(error as? ProductOutputSinkFixtureError, .consume)
        }

        let failureAbortCount = await sink.abortCount
        let failureTerminals = await terminals.values
        XCTAssertEqual(failureAbortCount, 1)
        XCTAssertEqual(failureTerminals.count, 1)
        XCTAssertEqual(failureTerminals.first?.disposition, .aborted(.runtime))
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    func testPrecancelledOutputAdapterAbortsInertReservationWithoutModelWork() async throws {
        let compatibilityModel = FacadeCompatibilityModel()
        let engine = VocelloQwen3Engine(
            loadedModel: try makeLoadedFixture(compatibilityModel: compatibilityModel)
        )
        let reservation = try await engine.reserveGeneration(
            request: makeCustomRequest(generationID: UUID()),
            audioCapacityFrames: 24_000
        )
        let sink = RecordingProductOutputSink()
        let startGate = AdapterStartGate()
        let adapter = VocelloQwen3ProductOutputAdapter()

        let task = Task {
            await startGate.wait()
            return try await adapter.run(
                engine: engine,
                reservation: reservation,
                sink: sink
            )
        }
        task.cancel()
        await startGate.open()

        do {
            _ = try await task.value
            XCTFail("an already-cancelled adapter must not open model generation")
        } catch {
            XCTAssertTrue(error is CancellationError)
        }

        XCTAssertEqual(compatibilityModel.capturedMemoryPolicies, [])
        let abortCount = await sink.abortCount
        XCTAssertEqual(abortCount, 1)
        let snapshot = await engine.snapshot()
        XCTAssertEqual(snapshot.phase, .ready)
        XCTAssertNil(snapshot.activeOperation)
    }

    private func makeLoadedFixture(
        compatibilityModel: FacadeCompatibilityModel,
        capabilities: VocelloQwen3CapabilitySet = VocelloQwen3CapabilitySet([
            .streaming,
            .customVoice,
        ])
    ) throws -> VocelloQwen3LoadedModel {
        try VocelloQwen3LoadedModel(
            compatibilityModel: compatibilityModel,
            identity: VocelloQwen3ModelIdentity(
                modelID: "fixture-custom",
                repositoryID: "fixture/repository",
                revision: "fixture-revision",
                artifactVersion: "fixture-v1"
            ),
            capabilities: capabilities
        )
    }

    private func makeRequest(
        generationID: UUID,
        input: VocelloQwen3SynthesisInput,
        executionStyle: VocelloQwen3ExecutionStyle = .streaming,
        captureCodecTrace: Bool = false
    ) -> VocelloQwen3SynthesisRequest {
        VocelloQwen3SynthesisRequest(
            generationID: generationID,
            text: "Facade terminal fixture.",
            language: "en-US",
            input: input,
            sampling: VocelloQwen3SamplingConfiguration(
                maxNewTokens: 32,
                temperature: 0.8,
                topP: 0.9,
                topK: VocelloQwen3SamplingConfiguration.compatibilityDefaultTopK,
                repetitionPenalty: 1
            ),
            memory: VocelloQwen3MemoryConfiguration(
                clearCacheOnStreamChunk: false,
                tokenMemoryClearCadence: 16
            ),
            executionStyle: executionStyle,
            captureCodecTrace: captureCodecTrace
        )
    }

    private func makeCustomRequest(generationID: UUID) -> VocelloQwen3SynthesisRequest {
        makeRequest(
            generationID: generationID,
            input: .customVoice(speakerID: "fixture-speaker", deliveryInstruction: nil)
        )
    }

    private func makeCloneRequest(
        generationID: UUID,
        conditioningDigest: String = "fixture-reference"
    ) -> VocelloQwen3SynthesisRequest {
        makeRequest(
            generationID: generationID,
            input: .voiceClone(referenceID: conditioningDigest)
        )
    }
}

private enum ProductOutputSinkFixtureError: Error, Equatable {
    case consume
}

private actor RecordingProductOutputSink: VocelloQwen3ProductOutputSink {
    private let failOnConsume: Bool
    private(set) var chunks: [VocelloQwen3AudioChunkEvent] = []
    private(set) var finalizeCount = 0
    private(set) var abortCount = 0

    init(failOnConsume: Bool = false) {
        self.failOnConsume = failOnConsume
    }

    func consume(
        _ chunk: VocelloQwen3AudioChunkEvent
    ) async throws -> VocelloQwen3PreviewAudioChunk {
        if failOnConsume { throw ProductOutputSinkFixtureError.consume }
        chunks.append(chunk)
        return VocelloQwen3PreviewAudioChunk(
            generationID: chunk.generationID,
            sequence: chunk.sequence,
            pcm16LittleEndian: Data(count: chunk.frameCount * MemoryLayout<Int16>.size),
            frameCount: chunk.frameCount,
            sampleRate: chunk.sampleRate,
            channelCount: chunk.channelCount
        )
    }

    func finalize(
        modelTerminal _: VocelloQwen3TerminalEvent
    ) async -> VocelloQwen3ProductFinalizationDisposition {
        finalizeCount += 1
        return .published
    }

    func abort() async {
        abortCount += 1
    }
}

private actor ProductTerminalRecorder {
    private(set) var values: [VocelloQwen3ProductTerminal] = []

    func record(_ terminal: VocelloQwen3ProductTerminal) {
        values.append(terminal)
    }
}

private actor PreviewChunkRecorder {
    private(set) var values: [VocelloQwen3PreviewAudioChunk] = []

    func record(_ chunk: VocelloQwen3PreviewAudioChunk) {
        values.append(chunk)
    }
}

private actor AdapterStartGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            if isOpen {
                continuation.resume()
            } else {
                waiters.append(continuation)
            }
        }
    }

    func open() {
        guard !isOpen else { return }
        isOpen = true
        let pending = waiters
        waiters.removeAll(keepingCapacity: false)
        pending.forEach { $0.resume() }
    }
}

private actor SuspendedEngineOperationGate {
    private var entered = false
    private var released = false
    private var enteredWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func suspend() async {
        if !entered {
            entered = true
            let pending = enteredWaiters
            enteredWaiters.removeAll(keepingCapacity: false)
            pending.forEach { $0.resume() }
        }
        guard !released else { return }
        await withCheckedContinuation { continuation in
            if released {
                continuation.resume()
            } else {
                releaseWaiters.append(continuation)
            }
        }
    }

    func waitUntilEntered() async {
        guard !entered else { return }
        await withCheckedContinuation { continuation in
            if entered {
                continuation.resume()
            } else {
                enteredWaiters.append(continuation)
            }
        }
    }

    func release() {
        guard !released else { return }
        released = true
        let pending = releaseWaiters
        releaseWaiters.removeAll(keepingCapacity: false)
        pending.forEach { $0.resume() }
    }
}

private enum FacadeCompatibilityFixtureError: Error {
    case unsupported
}

private final class FacadeCompatibilityModel: SpeechGenerationModel, Qwen3OptimizedSpeechGenerationModel, Qwen3PreparedQualityGenerationModel, Qwen3SuspendingSpeechGenerationModel, SpeechGenerationModelDiagnosticsProvider, @unchecked Sendable {
    let sampleRate = 24_000
    let defaultGenerationParameters = GenerateParameters()
    private let eventCount: Int
    private let generationEndReason: String
    private let streamOverride: AsyncThrowingStream<AudioGeneration, Error>?
    private let prewarmGate: SuspendedEngineOperationGate?
    private let producerGate: SuspendedEngineOperationGate?
    private let emitsAudio: Bool
    private let emitsInfo: Bool
    private let emitsChunkTimings: Bool
    private let qualityFirstAudio: [Float]
    private let captureLock = NSLock()
    private var _capturedGenerationParameters: GenerateParameters?
    private var _capturedSamplingPolicy: Qwen3RequestSamplingPolicy?
    private var _capturedMemoryPolicies: [Qwen3RequestMemoryPolicy] = []
    private var _capturedStreamingIntervals: [Double] = []

    init(
        eventCount: Int = 1,
        generationEndReason: String = "eos",
        streamOverride: AsyncThrowingStream<AudioGeneration, Error>? = nil,
        prewarmGate: SuspendedEngineOperationGate? = nil,
        producerGate: SuspendedEngineOperationGate? = nil,
        emitsAudio: Bool = true,
        emitsInfo: Bool = false,
        emitsChunkTimings: Bool = false,
        qualityFirstAudio: [Float] = [0.1]
    ) {
        self.eventCount = eventCount
        self.generationEndReason = generationEndReason
        self.streamOverride = streamOverride
        self.prewarmGate = prewarmGate
        self.producerGate = producerGate
        self.emitsAudio = emitsAudio
        self.emitsInfo = emitsInfo
        self.emitsChunkTimings = emitsChunkTimings
        self.qualityFirstAudio = qualityFirstAudio
    }

    var capturedGenerationParameters: GenerateParameters? {
        captureLock.lock()
        defer { captureLock.unlock() }
        return _capturedGenerationParameters
    }

    var capturedSamplingPolicy: Qwen3RequestSamplingPolicy? {
        captureLock.lock()
        defer { captureLock.unlock() }
        return _capturedSamplingPolicy
    }

    var capturedMemoryPolicies: [Qwen3RequestMemoryPolicy] {
        captureLock.lock()
        defer { captureLock.unlock() }
        return _capturedMemoryPolicies
    }

    var capturedStreamingIntervals: [Double] {
        captureLock.lock()
        defer { captureLock.unlock() }
        return _capturedStreamingIntervals
    }

    let loadTimingsMS: [String: Int] = [:]
    let loadBooleanFlags: [String: Bool] = [:]
    let latestPreparationTimingsMS: [String: Int] = [:]
    let latestPreparationBooleanFlags: [String: Bool] = [:]
    var latestPreparationStringFlags: [String: String] {
        ["generation_end_reason": generationEndReason]
    }
    func resetPreparationDiagnostics() {}

    func prepareForGeneration(
        text _: String,
        voice _: String?,
        refAudio _: MLXArray?,
        refText _: String?,
        language _: String?,
        generationParameters _: GenerateParameters
    ) async throws {}

    func generate(
        text _: String,
        voice _: String?,
        refAudio _: MLXArray?,
        refText _: String?,
        language _: String?,
        generationParameters _: GenerateParameters
    ) async throws -> MLXArray { MLXArray([Float(0)]) }

    func generateStream(
        text _: String,
        voice _: String?,
        refAudio _: MLXArray?,
        refText _: String?,
        language _: String?,
        generationParameters _: GenerateParameters
    ) -> AsyncThrowingStream<AudioGeneration, Error> { fixtureStream() }

    func generateStream(
        text _: String,
        voice _: String?,
        refAudio _: MLXArray?,
        refText _: String?,
        language _: String?,
        generationParameters: GenerateParameters,
        streamingInterval _: Double
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        capture(generationParameters)
        return fixtureStream()
    }

    func prepareCustomVoice(
        text _: String,
        language _: String,
        speaker _: String,
        instruct _: String?,
        generationParameters _: GenerateParameters,
        memoryPolicy _: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws {
        _ = isolation
        if let prewarmGate {
            await prewarmGate.suspend()
        }
    }

    func generateCustomVoiceStream(
        text _: String,
        language _: String,
        speaker _: String,
        instruct _: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile _: String?,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        return fixtureStream()
    }

    func generateCustomVoice(
        text _: String,
        language _: String,
        speaker _: String,
        instruct _: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        return fixtureCompletion()
    }

    func generateCustomVoiceQualityFirst(
        text _: String,
        language _: String,
        speaker _: String,
        instruct _: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        try await onPrepared()
        try await codecTraceSink?([1, 2])
        return fixtureCompletion()
    }

    func produceCustomVoice(
        text _: String,
        language _: String,
        speaker _: String,
        instruct _: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile _: String?,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool,
        enableCodecTrace _: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        if let producerGate {
            await producerGate.suspend()
        }
        try await sink(.prepared)
        try await emitFixtureEvents(to: sink)
        switch generationEndReason {
        case "eos": return .eos
        case "token_cap", "max_tokens": return .maxTokens
        case "cancelled": return .cancelled
        default: return .failed
        }
    }

    func prepareVoiceDesign(
        text _: String,
        language _: String,
        voiceDescription _: String,
        generationParameters _: GenerateParameters,
        memoryPolicy _: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws {
        _ = isolation
    }

    func generateVoiceDesignStream(
        text _: String,
        language _: String,
        voiceDescription _: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        return fixtureStream()
    }

    func generateVoiceDesign(
        text _: String,
        language _: String,
        voiceDescription _: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        return fixtureCompletion()
    }

    func generateVoiceDesignQualityFirst(
        text _: String,
        language _: String,
        voiceDescription _: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        try await onPrepared()
        try await codecTraceSink?([1, 2])
        return fixtureCompletion()
    }

    func produceVoiceDesign(
        text _: String,
        language _: String,
        voiceDescription _: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool,
        enableCodecTrace _: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        try await sink(.prepared)
        try await emitFixtureEvents(to: sink)
        return fixtureFinishReason()
    }

    func createVoiceClonePrompt(
        refAudio _: MLXArray,
        refText: String?,
        xVectorOnlyMode: Bool
    ) throws -> Qwen3TTSVoiceClonePrompt {
        Qwen3TTSVoiceClonePrompt(
            refCodes: nil,
            speakerEmbedding: MLXArray([Float(0.25)]).reshaped(1, 1),
            refText: refText,
            xVectorOnlyMode: xVectorOnlyMode,
            iclMode: !xVectorOnlyMode
        )
    }

    func prepareVoiceClone(
        text _: String,
        language _: String,
        voiceClonePrompt _: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        memoryPolicy _: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)?
    ) async throws {
        _ = isolation
    }

    func generateVoiceCloneStream(
        text _: String,
        language _: String,
        voiceClonePrompt _: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        return fixtureStream()
    }

    func generateVoiceClone(
        text _: String,
        language _: String,
        voiceClonePrompt _: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        return fixtureCompletion()
    }

    func generateVoiceCloneQualityFirst(
        text _: String,
        language _: String,
        voiceClonePrompt _: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy
        )
        try await onPrepared()
        try await codecTraceSink?([1, 2])
        return fixtureCompletion()
    }

    func produceVoiceClone(
        text _: String,
        language _: String,
        voiceClonePrompt _: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy _: String?,
        generationSpeedProfile _: String?,
        memoryClearCadence _: Int?,
        enableChunkTimings _: Bool,
        enableCodecTrace _: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationFinishReason {
        _ = isolation
        capture(
            generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            streamingInterval: streamingInterval
        )
        try await sink(.prepared)
        try await emitFixtureEvents(to: sink)
        return fixtureFinishReason()
    }

    private func fixtureStream() -> AsyncThrowingStream<AudioGeneration, Error> {
        if let streamOverride { return streamOverride }
        return AsyncThrowingStream { continuation in
            for token in 1 ... eventCount { continuation.yield(.token(token)) }
            if emitsInfo {
                continuation.yield(.info(fixtureInfo()))
            }
            if emitsAudio {
                if emitsChunkTimings {
                    continuation.yield(.chunkTimings(ChunkSubstageTimings(
                        talkerForwardMS: 1,
                        codePredictorMS: 2,
                        audioDecoderMS: 3
                    )))
                }
                continuation.yield(.audio(MLXArray([Float(0.1)])))
            }
            continuation.finish()
        }
    }

    private func failingFixtureStream() -> AsyncThrowingStream<AudioGeneration, Error> {
        AsyncThrowingStream { continuation in
            continuation.finish(throwing: FacadeCompatibilityFixtureError.unsupported)
        }
    }

    private func emitFixtureEvents(
        to sink: @escaping Qwen3MaterializedGenerationSink
    ) async throws {
        for try await event in fixtureStream() {
            switch event {
            case .token(let token):
                try await sink(.token(token))
            case .info(let info):
                try await sink(.info(info))
            case .audio(let audio):
                try await sink(.audio(audio.asArray(Float.self)))
            case .chunkTimings(let timings):
                try await sink(.chunkTimings(timings))
            }
        }
    }

    private func fixtureCompletion() -> AudioGenerationCompletion {
        AudioGenerationCompletion(
            audio: MLXArray(qualityFirstAudio),
            info: emitsInfo ? fixtureInfo() : nil,
            finishReason: fixtureFinishReason()
        )
    }

    private func fixtureInfo() -> AudioGenerationInfo {
        AudioGenerationInfo(
            promptTokenCount: 2,
            generationTokenCount: eventCount,
            prefillTime: 0.01,
            generateTime: 0.02,
            tokensPerSecond: 50,
            peakMemoryUsage: 0.25
        )
    }

    private func fixtureFinishReason() -> AudioGenerationFinishReason {
        switch generationEndReason {
        case "eos": return .eos
        case "token_cap", "max_tokens": return .maxTokens
        case "cancelled": return .cancelled
        default: return .failed
        }
    }


    private func capture(
        _ generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy? = nil,
        memoryPolicy: Qwen3RequestMemoryPolicy? = nil,
        streamingInterval: Double? = nil
    ) {
        captureLock.lock()
        _capturedGenerationParameters = generationParameters
        if let samplingPolicy {
            _capturedSamplingPolicy = samplingPolicy
        }
        if let memoryPolicy {
            _capturedMemoryPolicies.append(memoryPolicy)
        }
        if let streamingInterval {
            _capturedStreamingIntervals.append(streamingInterval)
        }
        captureLock.unlock()
    }
}
