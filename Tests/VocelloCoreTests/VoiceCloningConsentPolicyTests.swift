import Combine
import Foundation
import QwenVoiceCore
import XCTest

/// Thrown by `RecordingEngine` when a call reached the engine; the consent tests
/// tell it apart from `VoiceCloningConsentRequiredError`.
private struct ConsentFixtureEngineReached: Error {}

/// PA-17: voice-cloning consent is enforced below the views. These tests prove the
/// refusal (and the admission once consent is recorded) for the core policy, the
/// store's backend admission layer shared by both apps, and the CLI.
@MainActor
final class VoiceCloningConsentPolicyTests: XCTestCase {
    @MainActor
    private final class RecordedConsent {
        var isRecorded = false
    }

    /// A minimal engine host that records which calls reached it, so the backend's
    /// consent admission can be observed for work that returns nothing.
    @MainActor
    private final class RecordingEngine: TTSEngineRuntimeControlling {
        let modelRegistry: any ModelRegistry
        let loadState: EngineLoadState = .idle
        let clonePreparationState: ClonePreparationState = .idle
        let latestEvent: GenerationEvent? = nil
        let isReady = true
        let visibleErrorMessage: String? = nil
        private(set) var prewarmCount = 0
        private(set) var prefetchCount = 0
        private(set) var primeCount = 0
        private(set) var commitCount = 0
        private(set) var discardCount = 0

        init(modelRegistry: any ModelRegistry) {
            self.modelRegistry = modelRegistry
        }

        func supportDecision(for request: GenerationRequest) -> GenerationSupportDecision {
            .unsupported(reason: "consent fixture")
        }
        func start() {}
        func stop() {}
        func initialize(appSupportDirectory: URL) async throws {}
        func ping() async throws -> Bool { true }
        func loadModel(id: String) async throws {}
        func unloadModel() async throws {}
        func prepareAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
            throw ConsentFixtureEngineReached()
        }
        func ensureModelLoadedIfNeeded(id: String) async {}
        func prewarmModelIfNeeded(for request: GenerationRequest) async { prewarmCount += 1 }
        func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws { primeCount += 1 }
        func cancelClonePreparationIfNeeded() async {}
        func generate(_ request: GenerationRequest) async throws -> GenerationResult {
            throw ConsentFixtureEngineReached()
        }
        func listPreparedVoices() async throws -> [PreparedVoice] { [] }
        func preparePreparedVoiceCandidate(
            name: String,
            audioPath: String,
            transcript: String?,
            replacingVoiceID: String?
        ) async throws -> PreparedVoiceCandidate {
            throw ConsentFixtureEngineReached()
        }
        func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
            commitCount += 1
            throw ConsentFixtureEngineReached()
        }
        func discardPreparedVoiceCandidate(id: UUID) async throws { discardCount += 1 }
        func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
            throw ConsentFixtureEngineReached()
        }
        func deletePreparedVoice(id: String) async throws {}
        func importReferenceAudio(from sourceURL: URL) throws -> ImportedReferenceAudio {
            throw ConsentFixtureEngineReached()
        }
        func exportGeneratedAudio(from sourceURL: URL, to destinationURL: URL) throws -> ExportedDocument {
            throw ConsentFixtureEngineReached()
        }
        func clearGenerationActivity() {}
        func clearVisibleError() {}
        func prefetchInteractiveReadinessIfNeeded(
            for request: GenerationRequest
        ) async -> InteractivePrefetchDiagnostics? {
            prefetchCount += 1
            return nil
        }
        func setVisibleError(_ message: String?) {}
        func setAllowsProactiveWarmOperations(_ allow: Bool) {}
        func recordApplicationMemoryWarning(reason: String) async {}
        func recordMemoryBudgetTransition(
            from previousBand: IOSMemoryPressureBand,
            to currentBand: IOSMemoryPressureBand,
            reason: String
        ) async {}
        func trimMemory(level: NativeMemoryTrimLevel, reason: String) async {}
    }

    private let reference = CloneReference(audioPath: "/nonexistent/pa17-reference.wav", transcript: "Hello.")

    private var contractURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    }

    private func request(
        _ mode: GenerationMode,
        payload: GenerationRequest.Payload? = nil
    ) -> GenerationRequest {
        let resolved: GenerationRequest.Payload
        if let payload {
            resolved = payload
        } else {
            switch mode {
            case .custom: resolved = .custom(speakerID: "aiden", deliveryStyle: nil)
            case .design: resolved = .design(voiceDescription: "A clear narrator.", deliveryStyle: nil)
            case .clone: resolved = .clone(reference: reference)
            }
        }
        return GenerationRequest(
            mode: mode, modelID: "pro_\(mode.rawValue)_speed", text: "Consent fixture.",
            outputPath: "/nonexistent/pa17-output.wav", shouldStream: false,
            payload: resolved, generationID: UUID()
        )
    }

    private func assertRefused(
        _ operation: VoiceCloningOperation,
        _ body: () throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        do {
            try body()
            XCTFail("Expected a \(operation) consent refusal", file: file, line: line)
        } catch let error as VoiceCloningConsentRequiredError {
            XCTAssertEqual(error.operation, operation, file: file, line: line)
            XCTAssertFalse(error.message.isEmpty, file: file, line: line)
            XCTAssertEqual(error.errorDescription, error.message, file: file, line: line)
            XCTAssertEqual(String(describing: error), error.message, file: file, line: line)
        } catch {
            XCTFail("Unexpected error \(error)", file: file, line: line)
        }
    }

    private func assertRefusedAsync(
        _ operation: VoiceCloningOperation,
        _ body: () async throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            try await body()
            XCTFail("Expected a \(operation) consent refusal", file: file, line: line)
        } catch let error as VoiceCloningConsentRequiredError {
            XCTAssertEqual(error.operation, operation, file: file, line: line)
        } catch {
            XCTFail("Unexpected error \(error); the refusal must precede the engine", file: file, line: line)
        }
    }

    // MARK: - Core policy

    func testRecordedConsentKeyMatchesTheSettingsToggle() {
        // Both apps' Settings toggles and Voice Cloning screens write this exact key.
        XCTAssertEqual(VoiceCloningConsentPolicy.recordedConsentDefaultsKey, "vocello.voiceCloningConsent.v1")
    }

    func testOnlyReferenceConditionedWorkRequiresConsent() {
        XCTAssertTrue(VoiceCloningConsentPolicy.requiresConsent(.clone))
        XCTAssertFalse(VoiceCloningConsentPolicy.requiresConsent(.custom))
        XCTAssertFalse(VoiceCloningConsentPolicy.requiresConsent(.design))
        XCTAssertTrue(VoiceCloningConsentPolicy.requiresConsent(request(.clone)))
        XCTAssertFalse(VoiceCloningConsentPolicy.requiresConsent(request(.custom)))
        XCTAssertFalse(VoiceCloningConsentPolicy.requiresConsent(request(.design)))
        // A mismatched request carrying a reference voice cannot slip past as another mode.
        XCTAssertTrue(VoiceCloningConsentPolicy.requiresConsent(
            request(.custom, payload: .clone(reference: reference))
        ))
    }

    func testPolicyRefusesCloneGenerationAndEnrollmentWithoutRecordedConsent() {
        let policy = VoiceCloningConsentPolicy(isConsentRecorded: false)
        assertRefused(.generation) { try policy.admitGeneration(request(.clone)) }
        assertRefused(.generation) { try policy.admitGeneration(request(.design, payload: .clone(reference: reference))) }
        assertRefused(.generation) { try policy.admitGeneration(mode: .clone) }
        assertRefused(.generation) { try policy.admit(.generation) }
        assertRefused(.enrollment) { try policy.admit(.enrollment) }
    }

    func testPolicyAdmitsCloneWorkOnceConsentIsRecorded() {
        let policy = VoiceCloningConsentPolicy(isConsentRecorded: true)
        XCTAssertNoThrow(try policy.admitGeneration(request(.clone)))
        XCTAssertNoThrow(try policy.admitGeneration(mode: .clone))
        XCTAssertNoThrow(try policy.admit(.enrollment))
    }

    func testBuiltInAndDesignGenerationNeverNeedConsent() {
        let policy = VoiceCloningConsentPolicy(isConsentRecorded: false)
        XCTAssertNoThrow(try policy.admitGeneration(request(.custom)))
        XCTAssertNoThrow(try policy.admitGeneration(request(.design)))
        XCTAssertNoThrow(try policy.admitGeneration(mode: .custom))
        XCTAssertNoThrow(try policy.admitGeneration(mode: .design))
    }

    func testRefusalCarriesTheHostCopyForEachOperation() {
        let copy = VoiceCloningConsentPolicy.RefusalCopy(generation: "gen-copy", enrollment: "enroll-copy")
        let policy = VoiceCloningConsentPolicy(isConsentRecorded: false, refusalCopy: copy)
        XCTAssertThrowsError(try policy.admit(.generation)) { error in
            XCTAssertEqual(error as? VoiceCloningConsentRequiredError,
                           VoiceCloningConsentRequiredError(operation: .generation, message: "gen-copy"))
        }
        XCTAssertThrowsError(try policy.admit(.enrollment)) { error in
            XCTAssertEqual(error as? VoiceCloningConsentRequiredError,
                           VoiceCloningConsentRequiredError(operation: .enrollment, message: "enroll-copy"))
        }
    }

    func testPolicyReadsTheRecordedAcknowledgmentAndTreatsAbsenceAsNoConsent() throws {
        let suiteName = "PA17.VoiceCloningConsent.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }

        XCTAssertFalse(VoiceCloningConsentPolicy(defaults: defaults).isConsentRecorded)
        defaults.set(true, forKey: VoiceCloningConsentPolicy.recordedConsentDefaultsKey)
        XCTAssertTrue(VoiceCloningConsentPolicy(defaults: defaults).isConsentRecorded)
        defaults.set(false, forKey: VoiceCloningConsentPolicy.recordedConsentDefaultsKey)
        XCTAssertFalse(VoiceCloningConsentPolicy(defaults: defaults).isConsentRecorded)
    }

    // MARK: - App admission layer (AnyTTSEngineBackend under TTSEngineStore)

    func testEngineBackendRefusesCloneGenerationAndEnrollmentBeforeTheEngine() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let runtime = try NativeRuntimeFactory.make(
            manifestURL: source.appendingPathComponent("Sources/Resources/qwenvoice_contract.json"),
            paths: .rooted(at: root), storeVersionSeed: "pa17-consent-fixture"
        )
        defer { runtime.engine.stop() }
        let consent = RecordedConsent()
        // Uninitialized engine, no model: every refused call must fail on consent,
        // never on engine state, proving the backend decides before the engine runs.
        let backend = AnyTTSEngineBackend(
            engine: runtime.engine,
            supportsSavedVoiceMutation: true,
            supportsModelManagementMutation: true,
            supportedModes: [.custom, .design, .clone],
            voiceCloningConsent: { VoiceCloningConsentPolicy(isConsentRecorded: consent.isRecorded) }
        )

        // Studio clone takes, line batch, long-form segments and regeneration all
        // reach the engine through this one generate path.
        let cloneRequest = request(.clone)
        assertRefused(.generation) { try backend.admitVoiceCloning(for: cloneRequest) }
        await assertRefusedAsync(.generation) { _ = try await backend.generate(cloneRequest) }
        assertRefused(.enrollment) { try backend.admitVoiceEnrollment() }
        await assertRefusedAsync(.enrollment) {
            _ = try await backend.preparePreparedVoiceCandidate(
                name: "PA17", audioPath: self.reference.audioPath, transcript: "Hello.", replacingVoiceID: nil
            )
        }
        await assertRefusedAsync(.enrollment) {
            _ = try await backend.preparePreparedVoiceCandidate(
                name: "PA17", audioPath: self.reference.audioPath, transcript: "Hello.",
                replacingVoiceID: nil, enrollmentMetadata: nil
            )
        }
        await assertRefusedAsync(.enrollment) {
            _ = try await backend.enrollPreparedVoice(
                name: "PA17", audioPath: self.reference.audioPath, transcript: "Hello."
            )
        }
        // Built-in Voice and Voice Design are admitted without consent.
        XCTAssertNoThrow(try backend.admitVoiceCloning(for: request(.custom)))
        XCTAssertNoThrow(try backend.admitVoiceCloning(for: request(.design)))

        // Recording consent in Settings applies to the next call without a rebuild…
        consent.isRecorded = true
        XCTAssertNoThrow(try backend.admitVoiceCloning(for: cloneRequest))
        XCTAssertNoThrow(try backend.admitVoiceEnrollment())

        // …and withdrawing it refuses again.
        consent.isRecorded = false
        assertRefused(.generation) { try backend.admitVoiceCloning(for: cloneRequest) }
        assertRefused(.enrollment) { try backend.admitVoiceEnrollment() }
    }

    func testEngineBackendGatesProactiveClonePrimingAndCandidateCommit() async throws {
        let engine = RecordingEngine(modelRegistry: try ContractBackedModelRegistry(manifestURL: contractURL))
        let consent = RecordedConsent()
        let backend = AnyTTSEngineBackend(
            engine: engine,
            supportsSavedVoiceMutation: true,
            supportsModelManagementMutation: true,
            supportedModes: [.custom, .design, .clone],
            voiceCloningConsent: { VoiceCloningConsentPolicy(isConsentRecorded: consent.isRecorded) }
        )
        let cloneRequest = request(.clone)

        // Without consent, best-effort warm-up of a clone request is skipped (not
        // raised), priming and publishing a staged candidate are refused before the
        // engine, and discarding the private candidate stays allowed.
        await backend.prewarmModelIfNeeded(for: cloneRequest)
        let skippedPrefetch = await backend.prefetchInteractiveReadinessIfNeeded(for: cloneRequest)
        XCTAssertNil(skippedPrefetch)
        XCTAssertEqual(engine.prewarmCount, 0)
        XCTAssertEqual(engine.prefetchCount, 0)
        await assertRefusedAsync(.generation) {
            try await backend.ensureCloneReferencePrimed(modelID: "pro_clone_speed", reference: self.reference)
        }
        XCTAssertEqual(engine.primeCount, 0)
        await assertRefusedAsync(.enrollment) {
            _ = try await backend.commitPreparedVoiceCandidate(id: UUID())
        }
        XCTAssertEqual(engine.commitCount, 0)
        try await backend.discardPreparedVoiceCandidate(id: UUID())
        XCTAssertEqual(engine.discardCount, 1)

        // Built-in Voice and Voice Design warm-up never needs consent.
        await backend.prewarmModelIfNeeded(for: request(.custom))
        _ = await backend.prefetchInteractiveReadinessIfNeeded(for: request(.design))
        XCTAssertEqual(engine.prewarmCount, 1)
        XCTAssertEqual(engine.prefetchCount, 1)

        // Once consent is recorded, the same calls reach the engine.
        consent.isRecorded = true
        await backend.prewarmModelIfNeeded(for: cloneRequest)
        _ = await backend.prefetchInteractiveReadinessIfNeeded(for: cloneRequest)
        try await backend.ensureCloneReferencePrimed(modelID: "pro_clone_speed", reference: reference)
        XCTAssertEqual(engine.prewarmCount, 2)
        XCTAssertEqual(engine.prefetchCount, 2)
        XCTAssertEqual(engine.primeCount, 1)
        do {
            _ = try await backend.commitPreparedVoiceCandidate(id: UUID())
            XCTFail("The recording engine always fails a commit")
        } catch is ConsentFixtureEngineReached {
            // Admitted: the commit reached the engine.
        }
        XCTAssertEqual(engine.commitCount, 1)
    }

    func testMacRefusalCopyNamesTheMacSettingsSection() {
        let copy = MacInterfaceText.voiceCloningConsentRefusalCopy
        XCTAssertEqual(copy.generation, MacInterfaceText.cloningConsentRequiredToGenerate)
        XCTAssertEqual(copy.enrollment, MacInterfaceText.cloningConsentRequiredToSaveVoice)
        XCTAssertNotEqual(copy.generation, copy.enrollment)
        // The shared copy names the iPhone's Settings → Privacy; the Mac's toggle
        // lives under Settings → Voice cloning, so the Mac must not reuse it.
        XCTAssertNotEqual(copy, MacInterfaceText.presentation.voiceCloningConsentRefusalCopy)
    }

    func testAppRefusalCopyComesFromTheLocalizedPresentationRoute() {
        let presentation = VocelloPresentationText()
        let copy = presentation.voiceCloningConsentRefusalCopy
        XCTAssertEqual(copy.generation, presentation.cloningConsentRequired)
        XCTAssertEqual(copy.enrollment, presentation.cloningConsentRequiredToSaveVoice)
        XCTAssertNotEqual(copy.generation, copy.enrollment)
    }

    // MARK: - CLI

    func testCLIRefusesCloneAndEnrollmentWithoutTheConsentFlag() {
        XCTAssertEqual(CLIVoiceCloningConsent.flagName, "confirm-consent")
        for policy in [CLIVoiceCloningConsent.notConfirmed, CLIVoiceCloningConsent.policy(confirmed: false)] {
            assertRefused(.generation) { try policy.admitGeneration(mode: .clone) }
            assertRefused(.generation) { try policy.admitGeneration(request(.clone)) }
            assertRefused(.enrollment) { try policy.admit(.enrollment) }
            XCTAssertNoThrow(try policy.admitGeneration(mode: .custom))
            XCTAssertNoThrow(try policy.admitGeneration(mode: .design))
        }
        // VocelloMain prints `error: \(error)`; the refusal must name the flag.
        XCTAssertThrowsError(try CLIVoiceCloningConsent.notConfirmed.admit(.generation)) { error in
            XCTAssertTrue(String(describing: error).contains("--confirm-consent"))
        }
        XCTAssertThrowsError(try CLIVoiceCloningConsent.notConfirmed.admit(.enrollment)) { error in
            XCTAssertTrue(String(describing: error).contains("--confirm-consent"))
        }
    }

    func testCLIConsentFlagIsBareAndRejectsAValue() throws {
        XCTAssertTrue(try CLIVoiceCloningConsent.policy(from: Args(["--confirm-consent"])).isConsentRecorded)
        XCTAssertTrue(try CLIVoiceCloningConsent.policy(
            from: Args(["--confirm-consent", "--mode", "clone"])
        ).isConsentRecorded)
        XCTAssertFalse(try CLIVoiceCloningConsent.policy(from: Args(["--mode", "clone"])).isConsentRecorded)
        // A value would otherwise parse as `--key value` and silently mean no consent.
        for argv in [["--confirm-consent", "yes"], ["--confirm-consent=yes"], ["--confirm-consent="]] {
            XCTAssertThrowsError(try CLIVoiceCloningConsent.policy(from: Args(argv)), "\(argv)") { error in
                XCTAssertTrue(error is CLIError, "\(argv): \(error)")
                XCTAssertTrue(String(describing: error).contains("takes no value"), "\(argv): \(error)")
            }
        }
    }

    /// `CLIRuntime` around an uninitialized engine: a refused call fails on consent,
    /// an admitted one fails on engine state, proving where the decision is made.
    private func makeCLIRuntime(root: URL, consent: VoiceCloningConsentPolicy) throws -> CLIRuntime {
        let runtime = try NativeRuntimeFactory.make(
            manifestURL: contractURL, paths: .rooted(at: root), storeVersionSeed: "pa17-cli-consent-fixture"
        )
        return CLIRuntime(
            engine: runtime.engine,
            registry: runtime.modelRegistry,
            dataDirectory: root,
            voiceCloningConsent: consent
        )
    }

    private func assertReachesEngine(
        _ body: () async throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            try await body()
            XCTFail("An uninitialized engine cannot complete the call", file: file, line: line)
        } catch let error as VoiceCloningConsentRequiredError {
            XCTFail("Admitted call was refused on consent: \(error)", file: file, line: line)
        } catch {
            // Engine-state failure: the call got past the consent admission.
        }
    }

    func testCLIRuntimeRefusesCloneGenerationAndEnrollmentWithoutTheFlag() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let cli = try makeCLIRuntime(root: root, consent: CLIVoiceCloningConsent.notConfirmed)
        defer { cli.engine.stop() }

        let cloneRequest = request(.clone)
        await assertRefusedAsync(.generation) { _ = try await cli.generate(cloneRequest) }
        await assertRefusedAsync(.enrollment) {
            _ = try await cli.enrollPreparedVoice(
                name: "PA17", audioPath: self.reference.audioPath, transcript: "Hello."
            )
        }
        do {
            _ = try await cli.generate(cloneRequest)
            XCTFail("Expected the CLI consent refusal")
        } catch {
            // VocelloMain prints `error: \(error)`; the refusal names the flag.
            XCTAssertTrue(String(describing: error).contains("--confirm-consent"))
        }
        // Built-in Voice passes the admission without the flag.
        await assertReachesEngine { _ = try await cli.generate(self.request(.custom)) }
    }

    func testCLIRuntimeAdmitsCloneGenerationAndEnrollmentWithTheFlag() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let cli = try makeCLIRuntime(root: root, consent: CLIVoiceCloningConsent.policy(confirmed: true))
        defer { cli.engine.stop() }

        await assertReachesEngine { _ = try await cli.generate(self.request(.clone)) }
        await assertReachesEngine {
            _ = try await cli.enrollPreparedVoice(
                name: "PA17", audioPath: self.reference.audioPath, transcript: "Hello."
            )
        }
    }

    func testCLIAdmitsCloneAndEnrollmentWithTheConsentFlag() {
        let policy = CLIVoiceCloningConsent.policy(confirmed: true)
        XCTAssertNoThrow(try policy.admitGeneration(mode: .clone))
        XCTAssertNoThrow(try policy.admitGeneration(request(.clone)))
        XCTAssertNoThrow(try policy.admit(.enrollment))
    }
}
