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
                deliveryInstructionCellID: nil, languageHint: nil, variation: nil, directory: folder
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
                deliveryInstructionCellID: nil, languageHint: "english", variation: nil, directory: folder
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

    func testASignalOrAFailedMovePublishesNothing() throws {
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
        XCTAssertFalse(FileManager.default.fileExists(atPath: try XCTUnwrap(second.manifestPath)))
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
