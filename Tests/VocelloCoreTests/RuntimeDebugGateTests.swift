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
}
