import VocelloQwen3Core
import XCTest
@testable import QwenVoiceCore

final class RuntimeDebugGateTests: XCTestCase {
    func testIndividualOverrideIsInertWithoutMasterGate() {
        let environment = ["QWENVOICE_STREAMING_OUTPUT_POLICY": "files"]

        XCTAssertFalse(RuntimeDebugGate.isEnabled(environment: environment))
        XCTAssertNil(RuntimeDebugGate.value(
            for: "QWENVOICE_STREAMING_OUTPUT_POLICY",
            environment: environment
        ))
        XCTAssertEqual(
            NativeStreamingOutputPolicy.current(environment: environment),
            .pcmPreview
        )
    }

    func testMasterGateEnablesRegisteredOverride() {
        let environment = [
            "QWENVOICE_DEBUG": "true",
            "QWENVOICE_STREAMING_OUTPUT_POLICY": "files",
        ]

        XCTAssertTrue(RuntimeDebugGate.isEnabled(environment: environment))
        XCTAssertEqual(
            RuntimeDebugGate.value(
                for: "QWENVOICE_STREAMING_OUTPUT_POLICY",
                environment: environment
            ),
            "files"
        )
        XCTAssertEqual(
            NativeStreamingOutputPolicy.current(environment: environment),
            .pcmPreviewAndFileArtifacts
        )
    }

    func testMasterGateParsingIsExplicit() {
        XCTAssertFalse(RuntimeDebugGate.isEnabled(environment: ["QWENVOICE_DEBUG": "enabled"]))
        XCTAssertTrue(RuntimeDebugGate.isEnabled(environment: ["QWENVOICE_DEBUG": "YES"]))
    }

    func testDistributedBuildCapabilityCannotBeEnabledByEnvironment() {
        let environment = [
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_MARKING": "off",
        ]

        XCTAssertFalse(RuntimeDebugGate.isEnabled(
            environment: environment,
            internalDiagnosticsAvailable: false
        ))
        XCTAssertNil(RuntimeDebugGate.value(
            for: "QWENVOICE_MARKING",
            environment: environment,
            internalDiagnosticsAvailable: false
        ))
    }

    func testInternalCapabilityStillRequiresExplicitMasterGate() {
        let environment = ["QWENVOICE_MARKING": "off"]

        XCTAssertFalse(RuntimeDebugGate.isEnabled(
            environment: environment,
            internalDiagnosticsAvailable: true
        ))
        XCTAssertNil(RuntimeDebugGate.value(
            for: "QWENVOICE_MARKING",
            environment: environment,
            internalDiagnosticsAvailable: true
        ))
    }

    func testObservabilityValueRemainsAvailableWithoutInternalCapability() {
        XCTAssertEqual(
            RuntimeDebugGate.observabilityValue(
                for: "QVOICE_MAC_BENCH_RUN_ID",
                environment: ["QVOICE_MAC_BENCH_RUN_ID": "run-123"]
            ),
            "run-123"
        )
    }

    func testOverrideProvenanceBindsValuesWithoutRetainingThem() {
        let environment = [
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_MARKING": "off",
            "QVOICE_APP_SUPPORT_DIR": "/private/sensitive/path",
            "UNRELATED": "ignored",
        ]
        let provenance = RuntimeDebugGate.provenance(
            environment: environment,
            internalDiagnosticsAvailable: true
        )

        XCTAssertTrue(provenance.internalDiagnosticsAvailable)
        XCTAssertTrue(provenance.masterGateRequested)
        XCTAssertEqual(provenance.activeOverrideKeys, [
            "QVOICE_APP_SUPPORT_DIR",
            "QWENVOICE_MARKING",
        ])
        XCTAssertEqual(provenance.activeOverrideDigest?.count, 64)
        let encoded = String(data: try! JSONEncoder().encode(provenance), encoding: .utf8)!
        XCTAssertFalse(encoded.contains("sensitive"))
        XCTAssertFalse(encoded.contains("private"))

        var changed = environment
        changed["QWENVOICE_MARKING"] = "on"
        XCTAssertNotEqual(
            provenance.activeOverrideDigest,
            RuntimeDebugGate.provenance(
                environment: changed,
                internalDiagnosticsAvailable: true
            ).activeOverrideDigest
        )
    }

    func testForceColdIsInertWhenTelemetryIsEnabledWithoutMasterGate() {
        let environment = [
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "verbose",
            "QWENVOICE_BENCH_FORCE_COLD": "1",
        ]

        XCTAssertFalse(BenchForceColdPolicy.isRequested(
            environment: environment,
            telemetryEnabled: true
        ))
    }

    func testForceColdIsEnabledOnlyWhenTelemetryAndMasterGateAreEnabled() {
        let environment = [
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "verbose",
            "QWENVOICE_BENCH_FORCE_COLD": "true",
        ]

        XCTAssertTrue(BenchForceColdPolicy.isRequested(
            environment: environment,
            telemetryEnabled: true
        ))
        XCTAssertFalse(BenchForceColdPolicy.isRequested(
            environment: environment,
            telemetryEnabled: false
        ))
    }

    /// Audit #27: `vocello bench --telemetry off` leaves the explicit off mode in
    /// its environment and sets `QWENVOICE_DEBUG=1` for its registered runtime
    /// overrides. Telemetry must still resolve off, so the off arm builds no
    /// recorder and writes no engine row, and force-cold stays inert.
    func testBenchTelemetryOffEnvironmentResolvesTelemetryOff() {
        let environment = [
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "off",
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_STREAMING_PREVIEW_DATA": "off",
            "QWENVOICE_BENCH_FORCE_COLD": "1",
        ]

        let telemetryEnabled = TelemetryGate.resolve(environment: environment)
        XCTAssertFalse(telemetryEnabled)
        let mode = NativeTelemetryMode.current(environment: environment)
        XCTAssertEqual(mode, .off)
        XCTAssertFalse(NativeTelemetryWorkPlan.buildsRecorder(
            telemetryEnabled: telemetryEnabled,
            mode: mode
        ))
        XCTAssertFalse(NativeTelemetryWorkPlan(
            mode: mode,
            recorderPresent: false,
            sampleIntervalAvailable: false
        ).writesSink)
        XCTAssertFalse(BenchForceColdPolicy.isRequested(
            environment: environment,
            telemetryEnabled: telemetryEnabled
        ))
        // The split does not loosen production diagnostics: the bench override
        // still needs the internal-diagnostics capability and the master switch.
        XCTAssertEqual(
            RuntimeDebugGate.value(
                for: "QWENVOICE_STREAMING_PREVIEW_DATA",
                environment: environment,
                internalDiagnosticsAvailable: true
            ),
            "off"
        )
        XCTAssertNil(RuntimeDebugGate.value(
            for: "QWENVOICE_STREAMING_PREVIEW_DATA",
            environment: environment,
            internalDiagnosticsAvailable: false
        ))
    }

    /// The bench also latches `.off` in-process, which wins even when the
    /// environment decision was resolved on by `QWENVOICE_DEBUG` first.
    func testLatchedOffModeWinsOverAnEnvironmentThatResolvedOn() {
        XCTAssertFalse(TelemetryGate.resolve(
            environmentEnabled: true,
            latchedEnabled: false,
            latchedMode: .off
        ))
        XCTAssertTrue(TelemetryGate.resolve(
            environmentEnabled: true,
            latchedEnabled: false,
            latchedMode: nil
        ))
        XCTAssertTrue(TelemetryGate.resolve(
            environmentEnabled: false,
            latchedEnabled: true,
            latchedMode: .verbose
        ))
        XCTAssertFalse(TelemetryGate.resolve(
            environmentEnabled: false,
            latchedEnabled: false,
            latchedMode: nil
        ))
        XCTAssertFalse(NativeTelemetryWorkPlan.buildsRecorder(telemetryEnabled: true, mode: .off))
        XCTAssertTrue(NativeTelemetryWorkPlan.buildsRecorder(telemetryEnabled: true, mode: .lightweight))
        XCTAssertFalse(NativeTelemetryWorkPlan.buildsRecorder(telemetryEnabled: false, mode: .verbose))
    }

    func testDebugSwitchStillEnablesTelemetryWithoutAnExplicitOffMode() {
        XCTAssertTrue(TelemetryGate.resolve(environment: ["QWENVOICE_DEBUG": "1"]))
        XCTAssertTrue(TelemetryGate.resolve(environment: [
            "QWENVOICE_DEBUG": "1",
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "verbose",
        ]))
        XCTAssertTrue(TelemetryGate.resolve(environment: [
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "lightweight",
        ]))
        XCTAssertFalse(TelemetryGate.resolve(environment: [:]))
        XCTAssertFalse(TelemetryGate.resolve(environment: [
            "QWENVOICE_DEBUG": "yes",
            "QWENVOICE_NATIVE_TELEMETRY_MODE": "Disabled",
        ]))
    }

    func testWithoutCloneEncodersExplicitProfileIsNeverOverriddenToFullCapabilities() async throws {
        XCTAssertEqual(
            MLXTTSEngine.resolvedPreparedLoadProfile(
                requestedCapabilityProfile: .cloneOnly,
                explicitProfile: .withoutCloneEncoders
            ),
            .withoutCloneEncoders
        )
        XCTAssertEqual(
            MLXTTSEngine.resolvedPreparedLoadProfile(
                requestedCapabilityProfile: .fullCapabilities,
                explicitProfile: .withoutCloneEncoders
            ),
            .withoutCloneEncoders
        )
        XCTAssertEqual(
            MLXTTSEngine.resolvedPreparedLoadProfile(
                requestedCapabilityProfile: .cloneOnly,
                explicitProfile: .fullCapabilities
            ),
            .fullCapabilities
        )
        XCTAssertEqual(
            MLXTTSEngine.resolvedPreparedLoadProfile(
                requestedCapabilityProfile: .customOnly,
                explicitProfile: .fullCapabilities
            ),
            .withoutCloneEncoders
        )
        XCTAssertEqual(
            MLXTTSEngine.resolvedPreparedLoadProfile(
                requestedCapabilityProfile: .designOnly,
                explicitProfile: .fullCapabilities
            ),
            .withoutCloneEncoders
        )

        let loadBehavior = MLXTTSEngine.qwenPreparedLoadBehavior(
            for: .withoutCloneEncoders,
            trustPreparedCheckpoint: true,
            preparedDirectoryAlreadyValidated: true
        )
        XCTAssertEqual(loadBehavior.loadSpeakerEncoder, false)
        XCTAssertEqual(loadBehavior.loadSpeechTokenizerEncoder, false)

        // End-to-end runtime check: a `.withoutCloneEncoders` engine refuses `.clone`
        // generation while still admitting `.custom` and `.design`.
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-p1-5-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let manifestURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let runtime = try await MainActor.run {
            try NativeRuntimeFactory.make(
                manifestURL: manifestURL,
                paths: .rooted(at: root),
                storeVersionSeed: "p1-5-fallback",
                qwenPreparedLoadProfile: .withoutCloneEncoders
            )
        }
        defer { Task { @MainActor in runtime.engine.stop() } }

        let cloneRequest = GenerationRequest(
            mode: .clone,
            modelID: "pro_clone_speed",
            text: "Fallback test.",
            outputPath: root.appendingPathComponent("clone.wav").path,
            shouldStream: false,
            payload: .clone(reference: CloneReference(audioPath: "/nonexistent/ref.wav", transcript: "Hi"))
        )
        let customRequest = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Fallback test.",
            outputPath: root.appendingPathComponent("custom.wav").path,
            shouldStream: false,
            payload: .custom(speakerID: "aiden", deliveryStyle: nil)
        )
        let designRequest = GenerationRequest(
            mode: .design,
            modelID: "pro_design_speed",
            text: "Fallback test.",
            outputPath: root.appendingPathComponent("design.wav").path,
            shouldStream: false,
            payload: .design(voiceDescription: "Warm narrator", deliveryStyle: nil)
        )

        await MainActor.run {
            if case .unsupported = runtime.engine.supportDecision(for: cloneRequest) {
                // Expected refusal on `.withoutCloneEncoders`.
            } else {
                XCTFail("Expected .withoutCloneEncoders engine to refuse .clone requests")
            }
            XCTAssertEqual(runtime.engine.supportDecision(for: customRequest), .supported(.nativeMLX))
            XCTAssertEqual(runtime.engine.supportDecision(for: designRequest), .supported(.nativeMLX))
        }
    }
}
