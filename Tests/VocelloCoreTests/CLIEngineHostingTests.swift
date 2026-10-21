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
        let components = try NativeRuntimeFactory.make(
            manifestURL: Self.contract, paths: .rooted(at: root), storeVersionSeed: "rf27-hosting-fixture"
        )
        let host = DesktopEngineHost(
            engine: components.engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: hostConsent),
            deviceClass: .mid16GBMac
        )
        let runtime = CLIRuntime(
            engine: components.engine,
            registry: try ContractBackedModelRegistry(manifestURL: Self.contract)
                .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true),
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
                XCTAssertFalse(error is CancellationError, "\(error)")
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
}
