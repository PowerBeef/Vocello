import Foundation
import QwenVoiceCore
import XCTest

/// PA-17: voice-cloning consent is enforced below the views. These tests prove the
/// refusal (and the admission once consent is recorded) for the core policy, the
/// store's backend admission layer shared by both apps, and the CLI.
@MainActor
final class VoiceCloningConsentPolicyTests: XCTestCase {
    @MainActor
    private final class RecordedConsent {
        var isRecorded = false
    }

    private let reference = CloneReference(audioPath: "/nonexistent/pa17-reference.wav", transcript: "Hello.")

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

    func testCLIAdmitsCloneAndEnrollmentWithTheConsentFlag() {
        let policy = CLIVoiceCloningConsent.policy(confirmed: true)
        XCTAssertNoThrow(try policy.admitGeneration(mode: .clone))
        XCTAssertNoThrow(try policy.admitGeneration(request(.clone)))
        XCTAssertNoThrow(try policy.admit(.enrollment))
    }
}
