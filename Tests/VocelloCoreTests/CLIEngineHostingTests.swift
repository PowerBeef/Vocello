import Foundation
import QwenVoiceCore
import VocelloDesktopCore
import XCTest
@testable import VocelloCLICore

/// RF-27: the CLI's product commands host the engine through the app's store
/// (`DesktopEngineHost`), so the store, not the raw engine, admits each take.
final class CLIEngineHostingTests: XCTestCase {
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")

    @MainActor
    private func hostedRuntime(
        runtimeConsent: Bool, hostConsent: Bool
    ) throws -> (runtime: CLIRuntime, host: DesktopEngineHost, root: URL) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("CLIEngineHosting-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        // The macOS-expanded registry, as `CLIRuntime.bootstrap` builds it.
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let components = try NativeRuntimeFactory.make(
            registry: registry, paths: .rooted(at: root), storeVersionSeed: "rf27-hosting-fixture"
        )
        let host = DesktopEngineHost(
            engine: components.engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: hostConsent),
            deviceClass: .mid16GBMac
        )
        let runtime = CLIRuntime(
            engine: components.engine,
            registry: registry,
            dataDirectory: root,
            voiceCloningConsent: VoiceCloningConsentPolicy(isConsentRecorded: runtimeConsent),
            host: host
        )
        return (runtime, host, root)
    }

    private func clone(in root: URL) -> GenerationRequest {
        GenerationRequest(
            mode: .clone, modelID: "pro_clone_speed", text: "Hello.",
            outputPath: root.appendingPathComponent("take.wav").path, shouldStream: false,
            payload: .clone(reference: CloneReference(
                audioPath: root.appendingPathComponent("reference.wav").path, transcript: nil, preparedVoiceID: nil
            )),
            generationID: UUID()
        )
    }

    /// Review B1 (bf4544fa): the store can refuse a take before the engine starts
    /// it, so no terminal event ever reaches the stream drain; the refusal must
    /// return at once instead of stranding the command.
    @MainActor
    func testAStoreRefusalNeverStrandsTheStreamDrain() async throws {
        let (runtime, _, root) = try hostedRuntime(runtimeConsent: true, hostConsent: true)
        defer { runtime.engine.stop() }
        // The engine refuses batch-shaped requests, so the store refuses this one
        // at its support check, before the engine ever sees it.
        let request = GenerationRequest(
            mode: .custom, modelID: "pro_custom_speed", text: "Hello.",
            outputPath: root.appendingPathComponent("take.wav").path, shouldStream: true,
            batchIndex: 0, batchTotal: 1,
            payload: .custom(speakerID: runtime.defaultSpeakerID, deliveryStyle: nil), generationID: UUID()
        )
        let returned = expectation(description: "the refused streaming take returns")
        let attempt = Task { @MainActor in
            do {
                _ = try await GenerateCommand.generateObservingFirstChunk(runtime, request)
                XCTFail("an unsupported request is refused")
            } catch {
                guard case .unsupportedRequest? = error as? TTSEngineError else {
                    return XCTFail("the store's support check refuses it before the engine: \(error)")
                }
            }
            returned.fulfill()
        }
        // Well inside the drain's 5-second backstop: a refusal stops the drain at once.
        await fulfillment(of: [returned], timeout: 3)
        attempt.cancel()
    }

    /// Review S2 (bf4544fa): takes go through the host's store, which admits each
    /// one under the request's consent.
    @MainActor
    func testHostedTakesAreAdmittedByTheStoreUnderTheRequestsConsent() async throws {
        let (runtime, host, root) = try hostedRuntime(runtimeConsent: true, hostConsent: false)
        defer { runtime.engine.stop() }
        do {
            _ = try await runtime.generate(clone(in: root))
            XCTFail("the store refuses a clone its consent does not cover")
        } catch {
            XCTAssertTrue(error is VoiceCloningConsentRequiredError,
                          "only the host's store can refuse it: the runtime's own consent admits it (\(error))")
        }
        let unconsented = CLIRuntime(
            engine: runtime.engine, registry: runtime.registry, dataDirectory: root,
            voiceCloningConsent: VoiceCloningConsentPolicy(isConsentRecorded: false), host: host
        )
        do {
            _ = try await unconsented.withConsent(VoiceCloningConsentPolicy(isConsentRecorded: true))
                .generate(clone(in: root))
            XCTFail("the uninitialized fixture engine cannot generate")
        } catch {
            XCTAssertFalse(error is VoiceCloningConsentRequiredError,
                           "withConsent reaches the host's store: \(error)")
        }
    }

    /// Review S2 (c6725d84): the headless long-form driver runs the apps' runner
    /// over the host's store and reports one terminal per submitted take, then a
    /// typed failure, leaving nothing behind (the fixture engine cannot generate).
    @MainActor
    func testTheHeadlessRunnerReportsEachTakeAndATypedFailure() async throws {
        let (runtime, host, root) = try hostedRuntime(runtimeConsent: true, hostConsent: true)
        defer { runtime.engine.stop() }
        let plan = try CLILongFormProject.plan(
            "The lighthouse keeper climbed the stairs again, counting each step aloud.", seed: 3
        )
        let folder = root.appendingPathComponent("project", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let log = EventLog()
        let outcome = await host.runLongForm(
            DesktopLongFormRequest(
                mode: .custom, modelID: try runtime.modelID(mode: .custom, quality: false), plan: plan,
                payload: .custom(speakerID: runtime.defaultSpeakerID, deliveryStyle: nil),
                deliveryInstructionCellID: nil, languageHint: nil, directory: folder
            ),
            defaultSpeakerID: runtime.defaultSpeakerID
        ) { event in
            switch event {
            case .segmentStarted(let index, _, _): log.lines.append("started \(index)")
            case .segmentSaved(let index, _, _): log.lines.append("saved \(index)")
            case .segmentFailed(let index, _, let qcRejected): log.lines.append("failed \(index) qc=\(qcRejected)")
            case .segmentCancelled(let index, _): log.lines.append("cancelled \(index)")
            }
        }
        XCTAssertEqual(outcome.status, .failed)
        XCTAssertEqual(log.lines, ["started 0", "failed 0 qc=false"], "one terminal per submitted take")
        XCTAssertEqual(outcome.segments.first?.status, .failed)
        XCTAssertNil(outcome.manifestPath)
        XCTAssertNotNil(outcome.message)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: folder.path), [], "a failed take leaves nothing")
    }
}

/// RF-27: the headless long-form driver over the apps' runner and the host's
/// store, driven by the runner tests' fixture engine (a tone per take, or
/// silence, or a take held until released).
final class DesktopLongFormDriverTests: XCTestCase {
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")

    @MainActor
    private struct Fixture {
        let engine: LongFormFixtureEngine
        let host: DesktopEngineHost
        let request: DesktopLongFormRequest
        let folder: URL
    }

    @MainActor
    private func fixture() throws -> Fixture {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DesktopLongFormDriver-\(UUID().uuidString)", isDirectory: true)
            .resolvingSymlinksInPath()
        let folder = root.appendingPathComponent("project", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
        let model = try XCTUnwrap(registry.models.first { $0.mode == .custom })
        let engine = LongFormFixtureEngine(modelRegistry: registry)
        let host = DesktopEngineHost(
            engine: engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: true), deviceClass: .mid16GBMac
        )
        let plan = try LongFormPlanner.plan(
            spokenTextPlan: try SpokenTextPlanner.plan(
                originalText: "Gulls circled the pier. Rain fell on the harbor. Lamps lit the long quay."
            ),
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 12, baseSeed: 19)
        )
        XCTAssertEqual(plan.segments.count, 3, "one segment per sentence")
        return Fixture(
            engine: engine, host: host,
            request: DesktopLongFormRequest(
                mode: .custom, modelID: model.id, plan: plan, payload: .custom(speakerID: "aiden", deliveryStyle: nil),
                deliveryInstructionCellID: nil, languageHint: "english", directory: folder
            ),
            folder: folder
        )
    }

    @MainActor
    private func run(_ fixture: Fixture, log: EventLog) async -> DesktopLongFormOutcome {
        await fixture.host.runLongForm(fixture.request, defaultSpeakerID: "aiden") { log.record($0) }
    }

    @MainActor
    func testACompletedProjectKeepsItsTakesAndWritesItsManifest() async throws {
        let fixture = try fixture()
        let log = EventLog()
        let outcome = await run(fixture, log: log)
        XCTAssertEqual(outcome.status, .completed)
        XCTAssertEqual(log.lines, ["started 0", "saved 0", "started 1", "saved 1", "started 2", "saved 2"])
        XCTAssertEqual(outcome.segments.map(\.status), [.saved, .saved, .saved])
        XCTAssertEqual(outcome.segments.map(\.seed), fixture.request.plan.segments.map(\.evidence.effectiveSubseed))
        XCTAssertEqual(outcome.segments.compactMap(\.qcPassed), [true, true, true])
        let manifest = try XCTUnwrap(outcome.manifestPath)
        XCTAssertTrue(FileManager.default.fileExists(atPath: manifest))
        XCTAssertTrue(FileManager.default.fileExists(atPath: try XCTUnwrap(outcome.joinedPath)))
        XCTAssertEqual(URL(fileURLWithPath: manifest).deletingLastPathComponent().path, fixture.folder.path)
        XCTAssertTrue(outcome.segments.allSatisfy { $0.audioPath?.hasPrefix(fixture.folder.path + "/segment_") == true })
        XCTAssertNotNil(outcome.assembly)
        XCTAssertEqual(fixture.engine.takeRequests.map(\.longFormSegment), [true, true, true])
    }

    @MainActor
    func testARejectedSegmentFailsTypedAndIsNotKept() async throws {
        let fixture = try fixture()
        fixture.engine.scriptedTakes = [1: .silence]
        let log = EventLog()
        let outcome = await run(fixture, log: log)
        XCTAssertEqual(outcome.status, .failed)
        XCTAssertEqual(outcome.failure, .segmentQCRejected(index: 1))
        XCTAssertEqual(log.lines, ["started 0", "saved 0", "started 1", "failed 1 qc=true"])
        XCTAssertNil(outcome.segments[1].audioPath, "the rejected take is removed")
        XCTAssertNil(outcome.manifestPath)
    }

    /// Review B1 (c6725d84): a signal while a take runs stops the project; the
    /// take gets its terminal and nothing is accepted.
    @MainActor
    func testASignalStopsTheProjectBeforeAnythingIsAccepted() async throws {
        let fixture = try fixture()
        fixture.engine.heldTakes = [1]
        let log = EventLog()
        let host = fixture.host
        let request = fixture.request
        let project = Task { @MainActor in
            await host.runLongForm(request, defaultSpeakerID: "aiden") { log.record($0) }
        }
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(10))
        while fixture.engine.takeRequests.count < 2, clock.now < deadline { await Task.yield() }
        XCTAssertEqual(fixture.engine.takeRequests.count, 2, "the second take is held")
        project.cancel()
        fixture.engine.releaseGeneration()
        let outcome = await project.value
        XCTAssertEqual(outcome.status, .cancelled)
        XCTAssertEqual(log.lines, ["started 0", "saved 0", "started 1", "cancelled 1"])
        XCTAssertEqual(outcome.segments.map(\.status), [.saved, .cancelled, .cancelled])
        XCTAssertNil(outcome.manifestPath)
        XCTAssertFalse(
            try FileManager.default.contentsOfDirectory(atPath: fixture.folder.path).contains { $0.hasPrefix("long_form_") },
            "no joined output and no manifest"
        )
    }
}

/// RF-28: saving a clone voice as the app's voice sheet does, over the real
/// engine and its saved-voice store in a temporary data folder.
final class DesktopVoiceEnrollmentTests: XCTestCase {
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    private static let words = "The lighthouse keeper climbed the stairs again, counting each step aloud."

    @MainActor
    private func host() async throws -> (host: DesktopEngineHost, engine: MLXTTSEngine, root: URL) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DesktopVoiceEnrollment-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let components = try NativeRuntimeFactory.make(
            registry: registry, paths: .rooted(at: root), storeVersionSeed: "rf28-enrollment-fixture"
        )
        let host = DesktopEngineHost(
            engine: components.engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: true), deviceClass: .mid16GBMac
        )
        try await host.initialize(appSupportDirectory: root)
        return (host, components.engine, root)
    }

    /// A 220 Hz tone, `seconds` long.
    private func clip(_ seconds: Int, in root: URL) throws -> String {
        let url = root.appendingPathComponent("reference-\(seconds)s.wav")
        let samples: [Int16] = (0 ..< seconds * 24_000).map { frame in
            Int16((sin(2 * Double.pi * 220 * Double(frame) / 24_000) * 8_000).rounded())
        }
        // A 16-bit mono PCM WAV at 24 kHz.
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            for shift in stride(from: 0, to: T.bitWidth, by: 8) { data.append(UInt8(truncatingIfNeeded: value >> shift)) }
        }
        data.append(contentsOf: Array("RIFF".utf8)); append(UInt32(36 + samples.count * 2))
        data.append(contentsOf: Array("WAVEfmt ".utf8)); append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
        append(UInt32(24_000)); append(UInt32(48_000)); append(UInt16(2)); append(UInt16(16))
        data.append(contentsOf: Array("data".utf8)); append(UInt32(samples.count * 2))
        samples.forEach { append($0) }
        try data.write(to: url)
        return url.path
    }

    private func request(
        _ path: String, name: String? = nil, transcript: String? = nil, audioOnly: Bool = false,
        onWarnings: DesktopVoiceEnrollment.OnWarnings = .fail, replacing: String? = nil,
        source: DesktopVoiceEnrollment.Source = .clip
    ) -> DesktopVoiceEnrollment.Request {
        DesktopVoiceEnrollment.Request(
            name: name, audioPath: path, transcript: transcript, audioOnly: audioOnly, transcription: .never,
            language: nil, onWarnings: onWarnings, replacingVoiceID: replacing, source: source
        )
    }

    @MainActor
    private func failure(
        _ host: DesktopEngineHost, _ request: DesktopVoiceEnrollment.Request
    ) async -> DesktopVoiceEnrollment.Failure? {
        do {
            _ = try await host.enrollVoice(request)
            return nil
        } catch {
            return error as? DesktopVoiceEnrollment.Failure
        }
    }

    @MainActor
    func testAClipIsSavedReplacedAndDeletedAsTheAppDoes() async throws {
        let (host, engine, root) = try await host()
        defer { engine.stop() }
        let clip = try clip(10, in: root)

        let needsTranscript = await failure(host, request(clip, name: "Keeper"))
        XCTAssertEqual(needsTranscript, .transcriptNeeded(reason: "transcription is off"))
        let saved = try await host.enrollVoice(request(clip, name: "Keeper", transcript: Self.words))
        XCTAssertEqual(saved.outcome, .saved)
        XCTAssertEqual(saved.transcriptSource, "manual")
        XCTAssertEqual(saved.referenceLanguage, "english", "detected from the transcript")
        let voice = try XCTUnwrap(saved.voice)
        XCTAssertTrue(voice.hasTranscript)
        XCTAssertEqual(voice.enrollmentMetadata?.transcriptSource, .manual)

        let duplicate = await failure(host, request(clip, name: "keeper", transcript: Self.words))
        XCTAssertEqual(duplicate, .nameExists("keeper"), "the store's own case-insensitive naming, as the app names it")
        let unknown = await failure(host, request(clip, transcript: Self.words, replacing: "Nobody"))
        XCTAssertEqual(unknown, .voiceNotFound("Nobody"))
        let numbers = await failure(host, request(clip, name: "Digits", transcript: "1234 5678"))
        XCTAssertEqual(numbers, .languageNeeded, "a transcript needs a known language")

        let replaced = try await host.enrollVoice(request(clip, audioOnly: true, replacing: voice.id))
        XCTAssertEqual(replaced.name, voice.name, "a replaced voice keeps its name")
        XCTAssertEqual(replaced.transcriptSource, "audio_only")
        let afterReplace = try await host.listVoices()
        XCTAssertEqual(afterReplace.map(\.id), [voice.id])
        XCTAssertEqual(afterReplace.first?.hasTranscript, false)

        try await host.deleteVoice(id: voice.id, sleep: { _ in XCTFail("no retry without a busy store") })
        let afterDelete = try await host.listVoices()
        XCTAssertEqual(afterDelete, [])
    }

    @MainActor
    func testQualityWarningsFollowThePolicy() async throws {
        let (host, engine, root) = try await host()
        defer { engine.stop() }
        let short = try clip(3, in: root)
        let refused = await failure(host, request(short, name: "Short", transcript: Self.words))
        XCTAssertEqual(refused, .qualityRefused(warnings: ["reference_duration_short"], hardBlocking: false))
        let discarded = try await host.enrollVoice(request(short, name: "Short", transcript: Self.words, onWarnings: .discard))
        XCTAssertEqual(discarded.outcome, .discarded)
        XCTAssertNil(discarded.voice)
        let left = try await host.listVoices()
        XCTAssertEqual(left, [], "a refused or discarded candidate leaves nothing")
        let kept = try await host.enrollVoice(request(short, name: "Short", transcript: Self.words, onWarnings: .keep))
        XCTAssertEqual(kept.voice?.qualityWarnings, ["reference_duration_short"])
    }

    /// History takes become voices as the app's History offers them: a Clone
    /// take's text is its transcript; a Design take's is intent, so it needs one.
    @MainActor
    func testHistoryTakesBecomeVoicesAsTheAppSavesThem() async throws {
        let (host, engine, root) = try await host()
        defer { engine.stop() }
        let clip = try clip(10, in: root)

        let cloned = try await host.enrollVoice(request(clip, source: .cloneTake(text: Self.words, voice: "Nora")))
        XCTAssertEqual(cloned.name, "Nora Sample", "named as the app's History suggests it")
        let unnamed = try await host.enrollVoice(request(clip, source: .cloneTake(text: Self.words, voice: nil)))
        XCTAssertEqual(unnamed.name, "reference-10s", "without a voice: the take's file name")
        XCTAssertEqual(cloned.transcriptSource, "unknown", "a supplied transcript with no new recognition")
        XCTAssertEqual(cloned.voice?.hasTranscript, true)

        let brief = "A warm, slow narrator with a gentle rasp"
        let design = DesktopVoiceEnrollment.Source.designTake(text: Self.words, voiceDescription: brief)
        let needsWords = await failure(host, request(clip, source: design))
        XCTAssertEqual(needsWords, .transcriptNeeded(reason: "transcription is off"), "the script is intent, not evidence")
        let designed = try await host.enrollVoice(request(clip, transcript: Self.words, source: design))
        XCTAssertEqual(designed.name, "A_warm_slow_narrator_with_a_gentle")
        XCTAssertEqual(designed.name, DesktopVoiceEnrollment.suggestedName(forVoiceDescription: brief))
        XCTAssertEqual(designed.voice?.enrollmentMetadata?.generatedSourceMode, GenerationMode.design.rawValue)
        let audioOnly = try await host.enrollVoice(request(clip, name: "Designed Audio", audioOnly: true, source: design))
        XCTAssertEqual(audioOnly.referenceLanguage, "english", "the take's script language stays, as in the app")
    }

    /// Review 4 (a3ebb9e2): a signal while the candidate is staged discards it.
    @MainActor
    func testASignalDiscardsTheCandidate() async throws {
        let (host, engine, root) = try await host()
        defer { engine.stop() }
        let clip = try clip(10, in: root)
        let request = request(clip, name: "Stopped", transcript: Self.words, onWarnings: .keep)
        // A non-throwing task (CI's compiler refuses a throwing one that returns a value).
        let enrollment = Task { @MainActor () -> (any Error)? in
            do {
                _ = try await host.enrollVoice(request)
                return nil
            } catch {
                return error
            }
        }
        enrollment.cancel()
        let error = await enrollment.value
        XCTAssertTrue(error is CancellationError, "\(String(describing: error))")
        let voices = try await host.listVoices()
        XCTAssertEqual(voices, [], "nothing is committed after a signal")
        let again = try await host.enrollVoice(request)
        XCTAssertEqual(again.outcome, .saved, "the candidate was discarded, not stranded under the name")
    }
}

/// RF-27: publishing a project's joined output (review of fc1c4e05, item 4).
final class LongFormPublishTests: XCTestCase {
    private func project() throws -> (outcome: CLILongFormProject.Outcome, root: URL) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("LongFormPublish-\(UUID().uuidString)", isDirectory: true)
        let folder = root.appendingPathComponent("story_segments", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let joined = folder.appendingPathComponent("long_form_joined.wav")
        let manifest = folder.appendingPathComponent("long_form_manifest.json")
        try Data([1, 2]).write(to: joined)
        try Data("{}".utf8).write(to: manifest)
        var outcome = CLILongFormProject.Outcome(baseSeed: 1, planDigest: "d")
        outcome.audioPath = joined.path
        outcome.manifestPath = manifest.path
        return (outcome, root)
    }

    func testAPassedProjectReplacesTheOutputWhole() throws {
        let (outcome, root) = try project()
        let output = root.appendingPathComponent("story.wav")
        try Data([9]).write(to: output)
        try CLILongFormProject.publishJoined(outcome, to: output, signalled: false)
        XCTAssertEqual(try Data(contentsOf: output), Data([1, 2]))
        XCTAssertTrue(FileManager.default.fileExists(atPath: try XCTUnwrap(outcome.manifestPath)), "the manifest stays")
    }

    func testASignalPublishesNothingAndAFailedMoveKeepsTheProject() throws {
        let (outcome, root) = try project()
        let output = root.appendingPathComponent("story.wav")
        try Data([9]).write(to: output)
        XCTAssertThrowsError(try CLILongFormProject.publishJoined(outcome, to: output, signalled: true)) {
            XCTAssertTrue($0 is CancellationError)
        }
        XCTAssertEqual(try Data(contentsOf: output), Data([9]), "an existing output is left as it was")
        XCTAssertFalse(FileManager.default.fileExists(atPath: try XCTUnwrap(outcome.audioPath)))
        XCTAssertFalse(FileManager.default.fileExists(atPath: try XCTUnwrap(outcome.manifestPath)),
                       "the manifest names the discarded output by its digest")

        let (second, secondRoot) = try project()
        let unwritable = secondRoot.appendingPathComponent("missing/story.wav")
        XCTAssertThrowsError(try CLILongFormProject.publishJoined(second, to: unwritable, signalled: false)) {
            XCTAssertEqual(($0 as? CLIError)?.code, .outputUnavailable)
        }
        // RF-61 (audit finding C12): the project passed, so a destination that cannot be written
        // costs neither its joined output nor the manifest that names it.
        XCTAssertTrue(FileManager.default.fileExists(atPath: try XCTUnwrap(second.audioPath)))
        XCTAssertTrue(FileManager.default.fileExists(atPath: try XCTUnwrap(second.manifestPath)))
    }
}

/// RF-27: engines on this Mac say so with a lease, and a second engine is
/// refused only where two cannot fit.
final class EngineHostLeaseTests: XCTestCase {
    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("EngineHostLease-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    func testALeaseIsLiveWhileHeldAndStaleOnceNobodyHoldsIt() throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let lease = try EngineHostLease.acquire(in: folder, kind: "cli")
        XCTAssertEqual(lease.host.pid, getpid())
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [lease.host], "a held lease is live to any reader")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder, excluding: lease), [])
        let mode = try FileManager.default.attributesOfItem(atPath: folder.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(mode?.intValue, 0o700)
        lease.release()
        lease.release()
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [], "a released lease is gone")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: folder.path), [])

        // A lease whose process died is a file nobody holds: stale, and removed.
        let stale = folder.appendingPathComponent("99999-stale.lease")
        try JSONEncoder().encode(EngineHostLease.Host(pid: 99999, kind: "cli", startedAt: "2026-10-21T00:00:00Z"))
            .write(to: stale)
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [])
        XCTAssertFalse(FileManager.default.fileExists(atPath: stale.path))
        XCTAssertTrue(EngineHostLease.sharedFolder.path.hasSuffix("com.qwenvoice.vocello/engine-hosts"),
                      "one folder per user, whatever the data folder")
    }

    /// Review items 4 and 5 (fc1c4e05): admission refuses, waits, warns and
    /// stops on a signal, with its lease given back while it waits.
    @MainActor
    func testAdmissionRefusesWaitsAndWarns() async throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let other = try EngineHostLease.acquire(in: folder, kind: "cli")
        do {
            _ = try await CLIRuntime.admitEngineHost(
                deviceClass: .floor8GBMac, concurrency: CLIEngineConcurrency(), appRunning: { false },
                sleep: { _ in XCTFail("no wait without --wait-for-engine") }, folder: folder
            )
            XCTFail("an 8 GB Mac refuses a second engine")
        } catch {
            XCTAssertEqual((error as? CLIError)?.code, .engineBusy)
        }
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder, excluding: other), [], "a refused process keeps no lease")

        var waits = 0
        let waited = try await CLIRuntime.admitEngineHost(
            deviceClass: .floor8GBMac, concurrency: CLIEngineConcurrency(allow: false, wait: true), appRunning: { false },
            sleep: { _ in
                waits += 1
                XCTAssertEqual(EngineHostLease.liveHosts(in: folder, excluding: other), [], "no lease while waiting")
                other.release()
            },
            folder: folder
        )
        XCTAssertEqual(waits, 1)
        XCTAssertNotNil(waited, "admitted once the other engine exited")
        waited?.release()

        do {
            _ = try await CLIRuntime.admitEngineHost(
                deviceClass: .floor8GBMac, concurrency: CLIEngineConcurrency(allow: false, wait: true), appRunning: { true },
                sleep: { _ in throw CancellationError() }, folder: folder
            )
            XCTFail("a signal ends the wait")
        } catch {
            XCTAssertTrue(error is CancellationError, "the running app counts, and a signal ends the wait")
        }
        let warned = try await CLIRuntime.admitEngineHost(
            deviceClass: .mid16GBMac, concurrency: CLIEngineConcurrency(), appRunning: { true },
            sleep: { _ in XCTFail("no wait on a larger Mac") }, folder: folder
        )
        XCTAssertNotNil(warned, "a larger Mac runs beside the app, warned")
        warned?.release()

        let args = try CLIParser.args(["--text", "Hi.", "--wait-for-engine", "--allow-concurrent-engine"], for: "generate")
        XCTAssertEqual(CLIEngineConcurrency(args), CLIEngineConcurrency(allow: true, wait: true))
    }

    func testASecondEngineIsRefusedOnlyWhereTwoCannotFit() {
        let other = EngineHostLease.Host(pid: 42, kind: "cli", startedAt: "2026-10-21T00:00:00Z")
        func decide(_ hosts: [EngineHostLease.Host], app: Bool = false, _ device: NativeDeviceMemoryClass,
                    allow: Bool = false) -> EngineHostAdmission {
            EngineHostAdmission.decide(otherHosts: hosts, appRunning: app, deviceClass: device, allowConcurrent: allow)
        }
        XCTAssertEqual(decide([], .floor8GBMac), .proceed)
        guard case .refuse(let message) = decide([other], .floor8GBMac) else { return XCTFail("8 GB refuses") }
        XCTAssertTrue(message.contains("pid 42"), message)
        guard case .refuse = decide([], app: true, .floor8GBMac) else { return XCTFail("the running app counts") }
        guard case .warn = decide([other], .floor8GBMac, allow: true) else { return XCTFail("insisting runs, warned") }
        guard case .warn = decide([other], .mid16GBMac) else { return XCTFail("16 GB warns") }
    }
}

/// RF-61 (audit finding C3): a warm engine's lease follows its model, so an
/// idle server neither blocks another engine nor hides a model it has loaded.
final class WarmEngineLeaseTests: XCTestCase {
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")

    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("WarmEngineLease-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    /// Waits for `condition`: the store publishes an engine state on a later
    /// main-actor turn, and a failure's window is a real sleep.
    @MainActor
    private func settles(_ condition: @MainActor () -> Bool) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(10))
        while !condition(), clock.now < deadline {
            try? await Task.sleep(for: .milliseconds(2))
        }
        return condition()
    }

    @MainActor
    private struct Fixture {
        let warm: CLIWarmEngine
        /// The engine behind the warm host's store: its published state is the test's to set.
        let engine: StoreFixtureEngine
        let runtime: CLIRuntime
        let root: URL

        /// A request that loads a model, as `generate` bootstraps under the server.
        func admit() async throws {
            _ = try await warm.runtime(
                dataDirectory: root, manifestOverride: nil, consent: CLIVoiceCloningConsent.notConfirmed,
                hosted: true, takesEngineLease: true
            )
        }
    }

    /// A warm engine on an 8 GB Mac whose host runs the store's fixture engine,
    /// with its leases in `folder`.
    @MainActor
    private func fixture(leasesIn folder: URL) throws -> Fixture {
        let root = try makeRoot()
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let components = try NativeRuntimeFactory.make(
            registry: registry, paths: .rooted(at: root), storeVersionSeed: "rf61-warm-lease-fixture"
        )
        let engine = StoreFixtureEngine(modelRegistry: registry)
        let consent = VoiceCloningConsentPolicy(isConsentRecorded: false)
        let runtime = CLIRuntime(
            engine: components.engine, registry: registry, dataDirectory: root, voiceCloningConsent: consent,
            host: DesktopEngineHost(engine: engine, consent: consent, deviceClass: .mid16GBMac)
        )
        let warm = CLIWarmEngine(
            dataDirectory: root, manifestOverride: nil, concurrency: CLIEngineConcurrency(),
            seams: CLIWarmEngine.Seams(
                deviceClass: { .floor8GBMac }, appRunning: { false }, leaseFolder: folder,
                failureWindow: .milliseconds(30), boot: { runtime }
            )
        )
        return Fixture(warm: warm, engine: engine, runtime: runtime, root: root)
    }

    @MainActor
    func testTheLeaseIsGivenBackOnIdleUnloadAndTakenAgainForTheNextLoad() async throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let fixture = try fixture(leasesIn: folder)
        defer { fixture.runtime.engine.stop() }
        let warm = fixture.warm
        XCTAssertFalse(warm.holdsLease, "no lease before the first load")

        warm.engineRequestBegan()
        try await fixture.admit()
        XCTAssertTrue(warm.holdsLease, "admitted before its load")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder).map(\.kind), ["cli"])
        fixture.engine.loadState = .loaded(modelID: "pro_custom_speed")
        let loaded = await settles { warm.modelPresence == .present }
        XCTAssertTrue(loaded, "the host's store publishes the load")
        warm.engineRequestEnded()
        XCTAssertTrue(warm.holdsLease, "a loaded model keeps the lease between requests")

        // The engine's idle unload publishes `.idle`.
        fixture.engine.loadState = .idle
        let released = await settles { !warm.holdsLease }
        XCTAssertTrue(released, "the idle unload gives the lease back")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [], "an idle server blocks no other engine")

        warm.engineRequestBegan()
        try await fixture.admit()
        XCTAssertTrue(warm.holdsLease, "the next load is admitted again")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder).count, 1)
        warm.engineRequestEnded()
        XCTAssertFalse(warm.holdsLease, "a request that loaded nothing gives its lease back when it ends")
    }

    @MainActor
    func testARefusedReadmissionFailsThatRequestAndTheEngineStaysUp() async throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let fixture = try fixture(leasesIn: folder)
        defer { fixture.runtime.engine.stop() }
        let warm = fixture.warm
        warm.engineRequestBegan()
        try await fixture.admit()
        warm.engineRequestEnded()
        XCTAssertFalse(warm.holdsLease)

        // Another engine took this 8 GB Mac while the server sat idle.
        let other = try EngineHostLease.acquire(in: folder, kind: "cli")
        warm.engineRequestBegan()
        do {
            try await fixture.admit()
            XCTFail("an 8 GB Mac holds one engine at a time")
        } catch {
            XCTAssertEqual((error as? CLIError)?.code, .engineBusy, "the error a fresh vocello generate gets")
        }
        warm.engineRequestEnded()
        XCTAssertFalse(warm.holdsLease)
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder, excluding: other), [], "a refused request keeps no lease")
        XCTAssertTrue(warm.isBooted, "the engine stays up for the next request")

        other.release()
        warm.engineRequestBegan()
        try await fixture.admit()
        XCTAssertTrue(warm.holdsLease, "admitted once the other engine has gone")
        warm.engineRequestEnded()
    }

    @MainActor
    func testAKeeperHoldsItsLeaseWhileAModelMayBeLoaded() async throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let keeper = EngineHostLeaseKeeper(kind: "app", folder: folder, failureWindow: .milliseconds(30))
        XCTAssertFalse(keeper.holdsLease)

        // A model that shows up with no lease held gets one, and keeps the same
        // one across its load, a take and a clone prime.
        keeper.engineChanged(loadState: .starting, clonePreparation: .idle)
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder).map(\.kind), ["app"])
        let first = keeper.lease?.host
        keeper.engineChanged(loadState: .loaded(modelID: "m"), clonePreparation: .idle)
        keeper.engineChanged(loadState: .running(modelID: "m", label: nil, fraction: nil), clonePreparation: .idle)
        keeper.engineChanged(loadState: .idle, clonePreparation: .preparing)
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [first].compactMap { $0 })
        keeper.engineChanged(loadState: .idle, clonePreparation: .idle)
        XCTAssertFalse(keeper.holdsLease, "the unload gives the lease back")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [])

        // Weights a failure left resident keep the lease for the idle window,
        // also once the failure is dismissed.
        keeper.engineChanged(loadState: .loaded(modelID: "m"), clonePreparation: .idle)
        keeper.engineChanged(loadState: .failed(message: "failed"), clonePreparation: .idle)
        keeper.engineChanged(loadState: .idle, clonePreparation: .idle)
        XCTAssertTrue(keeper.holdsLease, "the weights may still be resident")
        let released = await settles { !keeper.holdsLease }
        XCTAssertTrue(released, "the idle window has unloaded them")

        // Quitting gives the lease up whatever is loaded.
        keeper.engineChanged(loadState: .loaded(modelID: "m"), clonePreparation: .idle)
        XCTAssertTrue(keeper.holdsLease)
        keeper.releaseNow()
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [])
    }

    @MainActor
    func testAnAdmittedLeaseStaysUntilItsRequestEnds() throws {
        let folder = try makeRoot().appendingPathComponent("engine-hosts")
        let keeper = EngineHostLeaseKeeper(kind: "cli", folder: folder, failureWindow: .milliseconds(30))
        let admitted = try EngineHostLease.acquire(in: folder, kind: "cli")
        keeper.requestBegan()
        keeper.adopt(admitted)
        // Nothing the engine publishes on the way to the load takes it back.
        keeper.engineChanged(loadState: .idle, clonePreparation: .idle)
        XCTAssertTrue(keeper.holdsLease)
        // A second admission while one is held is given back, not kept beside it.
        keeper.adopt(try EngineHostLease.acquire(in: folder, kind: "cli"))
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [admitted.host])
        keeper.requestEnded()
        XCTAssertFalse(keeper.holdsLease, "a request that loaded nothing gives its lease back")
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [])

        XCTAssertEqual(EngineHostModelPresence.of(loadState: .failed(message: "x"), clonePreparation: .idle),
                       .absentAfterIdleWindow)
        XCTAssertEqual(EngineHostLeaseKeeper.failureWindow(for: .floor8GBMac), .seconds(125.0),
                       "the 8 GB tier's two-minute idle window, with room for the unload")
    }
}

/// RF-61 (audit finding C3): the Mac app takes a lease and reads the other
/// hosts' before it deletes a model, generates or warms.
final class EngineHostAppPolicyTests: XCTestCase {
    private let cli = EngineHostLease.Host(pid: 42, kind: "cli", startedAt: "2026-11-15T00:00:00Z")

    private func makeFolder() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("EngineHostAppPolicy-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root.appendingPathComponent("engine-hosts")
    }

    func testAModelsFilesStayWhileAnotherHostHoldsALease() {
        XCTAssertFalse(EngineHostAppPolicy.refusesModelDeletion(otherHosts: []))
        XCTAssertTrue(EngineHostAppPolicy.refusesModelDeletion(otherHosts: [cli]),
                      "a lease names no model, so the host may have any of them loaded")
        let unreadable = EngineHostLease.Host(pid: 0, kind: "unknown", startedAt: "")
        XCTAssertTrue(EngineHostAppPolicy.refusesModelDeletion(otherHosts: [unreadable]),
                      "a held lease that cannot be read still counts")
    }

    func testTheAppAppliesTheCommandLinesRuleOnAn8GBMac() {
        XCTAssertFalse(EngineHostAppPolicy.refusesEngineWork(otherHosts: [], deviceClass: .floor8GBMac))
        XCTAssertTrue(EngineHostAppPolicy.refusesEngineWork(otherHosts: [cli], deviceClass: .floor8GBMac))
        XCTAssertFalse(EngineHostAppPolicy.refusesEngineWork(otherHosts: [cli], deviceClass: .mid16GBMac),
                       "a larger Mac runs beside the other engine")
        // The incumbent keeps working: an app whose own model is loaded is not refused its next
        // take by a lease that may be a command line's that is only asking (review of step 37).
        XCTAssertFalse(EngineHostAppPolicy.refusesEngineWork(
            otherHosts: [cli], deviceClass: .floor8GBMac, holdsOwnLease: true
        ))
        // A forced or emulated tier describes a Mac that has the memory: a lane on the emulated
        // 8 GB floor is not failed by a command line running beside it.
        XCTAssertFalse(EngineHostAppPolicy.refusesEngineWork(
            otherHosts: [cli], deviceClass: .floor8GBMac, tierIsDiagnostic: true
        ))
        // One rule: the app refuses exactly where the command line's admission does.
        let tiers: [NativeDeviceMemoryClass] = [.floor8GBMac, .mid16GBMac, .highMemoryMac]
        for tier in tiers {
            var commandLineRefuses = false
            if case .refuse = EngineHostAdmission.decide(
                otherHosts: [cli], appRunning: false, deviceClass: tier, allowConcurrent: false
            ) {
                commandLineRefuses = true
            }
            XCTAssertEqual(
                EngineHostAppPolicy.refusesEngineWork(otherHosts: [cli], deviceClass: tier), commandLineRefuses,
                tier.rawValue
            )
        }
    }

    /// The app's lease is of kind `app`, lives while its model does, refuses a
    /// command line on an 8 GB Mac and never refuses the app itself.
    @MainActor
    func testTheAppsLeaseIsReadByTheCommandLineAndNotByTheAppItself() async throws {
        let folder = try makeFolder()
        let keeper = EngineHostLeaseKeeper(kind: "app", folder: folder, failureWindow: .seconds(1))
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [], "an app with nothing loaded holds no lease")
        keeper.engineChanged(loadState: .starting, clonePreparation: .idle)
        let own = try XCTUnwrap(keeper.lease)
        XCTAssertEqual(own.host.kind, "app")
        XCTAssertEqual(own.host.pid, getpid())
        func others() -> [EngineHostLease.Host] { EngineHostLease.liveHosts(in: folder, excluding: own) }
        XCTAssertFalse(EngineHostAppPolicy.refusesEngineWork(otherHosts: others(), deviceClass: .floor8GBMac))
        XCTAssertFalse(EngineHostAppPolicy.refusesModelDeletion(otherHosts: others()))

        do {
            _ = try await CLIRuntime.admitEngineHost(
                deviceClass: .floor8GBMac, concurrency: CLIEngineConcurrency(), appRunning: { false },
                sleep: { _ in XCTFail("no wait without --wait-for-engine") }, folder: folder
            )
            XCTFail("the app's loaded model refuses a command line on an 8 GB Mac")
        } catch {
            XCTAssertEqual((error as? CLIError)?.code, .engineBusy)
        }

        let commandLine = try EngineHostLease.acquire(in: folder, kind: "cli")
        XCTAssertTrue(EngineHostAppPolicy.refusesEngineWork(otherHosts: others(), deviceClass: .floor8GBMac))
        XCTAssertTrue(EngineHostAppPolicy.refusesModelDeletion(otherHosts: others()))
        commandLine.release()
        XCTAssertFalse(EngineHostAppPolicy.refusesModelDeletion(otherHosts: others()))

        keeper.engineChanged(loadState: .idle, clonePreparation: .idle)
        XCTAssertEqual(EngineHostLease.liveHosts(in: folder), [], "the unload gives the app's lease back")
    }

    @MainActor
    func testAWarmWaitsWhileAnotherEngineHoldsTheMac() {
        let anotherEngine = Flag()
        let policy = MacWarmupAdmissionPolicy(
            mode: .off, deviceClass: .floor8GBMac, anotherEngineBlocksWarm: { anotherEngine.isSet }
        )
        XCTAssertEqual(policy.admit(contextDescription: "custom/test"), .allow)
        anotherEngine.isSet = true
        XCTAssertEqual(
            policy.admit(contextDescription: "custom/test"),
            .deferred(reason: MacWarmupAdmissionPolicy.anotherEngineReason),
            "deferred whatever the pressure gate's mode"
        )
        anotherEngine.isSet = false
        XCTAssertEqual(policy.admit(contextDescription: "custom/test"), .allow)
    }
}

@MainActor
private final class Flag {
    var isSet = false
}

/// RF-61 (audit finding C4): the command line finds the running app from a
/// session the workspace cannot see into (ssh, cron, launchd).
final class DesktopAppPresenceTests: XCTestCase {
    func testOnlyTheAppsOwnExecutableInsideItsBundleIsTheApp() {
        XCTAssertTrue(DesktopAppPresence.isAppExecutable("/Applications/Vocello.app/Contents/MacOS/Vocello"))
        XCTAssertTrue(DesktopAppPresence.isAppExecutable("/Volumes/Build/Release/Vocello.app/Contents/MacOS/Vocello"),
                      "whatever folder holds the bundle")
        let others = [
            "/usr/local/lib/vocello/vocello",
            "/usr/local/bin/Vocello",
            "/Applications/Vocello.app/Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate",
            "/Applications/Vocello.app/Contents/MacOS/Vocello Helper",
            "/Volumes/Build/Release/VocelloMacUITests-Runner.app/Contents/MacOS/VocelloMacUITests-Runner",
            "/Applications/MyVocello.app/Contents/MacOS/Vocello",
            "/Applications/Vocello.app/Contents/MacOS/vocello",
            "",
        ]
        for path in others {
            XCTAssertFalse(DesktopAppPresence.isAppExecutable(path), path)
        }
    }

    func testTheLeaseIsReadFirstThenTheWorkspaceThenTheProcessTable() {
        let app = EngineHostLease.Host(pid: 7, kind: "app", startedAt: "2026-11-15T00:00:00Z")
        let commandLine = EngineHostLease.Host(pid: 8, kind: "cli", startedAt: "2026-11-15T00:00:00Z")
        var asked: [String] = []
        func detects(leases: [EngineHostLease.Host], workspace: Bool, paths: [String]) -> Bool {
            asked = []
            return DesktopAppPresence.detectsRunningApp(
                leaseHosts: {
                    asked.append("leases")
                    return leases
                },
                workspaceSeesApp: {
                    asked.append("workspace")
                    return workspace
                },
                executablePaths: {
                    asked.append("processes")
                    return paths
                }
            )
        }
        XCTAssertTrue(detects(leases: [commandLine, app], workspace: false, paths: []))
        XCTAssertEqual(asked, ["leases"], "the app's own lease settles it")

        XCTAssertTrue(detects(leases: [commandLine], workspace: true, paths: []))
        XCTAssertEqual(asked, ["leases", "workspace"], "a command line's lease is not the app")

        // From ssh the workspace may see nothing: the process table answers.
        XCTAssertTrue(detects(
            leases: [], workspace: false,
            paths: ["/sbin/launchd", "/Applications/Vocello.app/Contents/MacOS/Vocello"]
        ))
        XCTAssertEqual(asked, ["leases", "workspace", "processes"])

        XCTAssertFalse(detects(
            leases: [commandLine], workspace: false, paths: ["/sbin/launchd", "/usr/local/lib/vocello/vocello"]
        ), "a process named vocello is the command line, not the app")
    }

    func testTheProcessTableNamesThisProcess() throws {
        let own = try XCTUnwrap(Bundle.main.executableURL?.lastPathComponent)
        let paths = DesktopAppPresence.runningExecutablePaths()
        XCTAssertTrue(paths.contains { URL(fileURLWithPath: $0).lastPathComponent == own },
                      "the kernel lists the test host among \(paths.count) processes")
        XCTAssertTrue(paths.allSatisfy { $0.hasPrefix("/") }, "each entry is a whole path")
    }
}

@MainActor
private final class EventLog {
    var lines: [String] = []

    func record(_ event: DesktopLongFormEvent) {
        switch event {
        case .segmentStarted(let index, _, _): lines.append("started \(index)")
        case .segmentSaved(let index, _, _): lines.append("saved \(index)")
        case .segmentFailed(let index, _, let qcRejected): lines.append("failed \(index) qc=\(qcRejected)")
        case .segmentCancelled(let index, _): lines.append("cancelled \(index)")
        }
    }
}
