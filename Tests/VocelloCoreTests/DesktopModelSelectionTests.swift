import CryptoKit
import Foundation
import QwenVoiceCore
import Synchronization
import XCTest
import VocelloDesktopCore

/// RF-26: the CLI resolves each mode's package the way the Mac app does: the
/// explicit choice, then the lower-memory preference, then the hardware
/// recommendation; a take falls back to the first installed package.
final class DesktopModelSelectionTests: XCTestCase {
    private func registry(_ deviceClass: NativeDeviceMemoryClass) throws -> ContractBackedModelRegistry {
        let manifest = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        return try ContractBackedModelRegistry(manifestURL: manifest)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
    }

    private func resolve(
        _ deviceClass: NativeDeviceMemoryClass,
        explicit: [GenerationMode: String] = [:],
        prefersLowerMemory: Bool = false,
        installed: Set<String>? = nil
    ) throws -> [String: DesktopModelSelection.Choice] {
        let choices = DesktopModelSelection.resolve(
            registry: try registry(deviceClass),
            explicitVariantID: { explicit[$0] },
            prefersLowerMemory: prefersLowerMemory,
            deviceClass: deviceClass,
            isInstalled: { installed?.contains($0) ?? true }
        )
        return Dictionary(uniqueKeysWithValues: choices.map { ($0.mode, $0) })
    }

    func testTheHardwareRecommendationFollowsTheMemoryTier() throws {
        let floor = try resolve(.floor8GBMac)
        let mid = try resolve(.mid16GBMac)
        for mode in ["custom", "design", "clone"] {
            XCTAssertEqual(floor[mode]?.activeVariant, "speed", mode)
            XCTAssertEqual(floor[mode]?.source, "hardware", mode)
            XCTAssertEqual(mid[mode]?.activeVariant, "quality", mode)
            XCTAssertEqual(mid[mode]?.variants, ["speed", "quality"], "the picker order")
        }
        XCTAssertEqual(mid["custom"]?.activeModelID, "pro_custom_quality")
    }

    func testAnExplicitChoiceThenTheLowerMemoryPreferenceWin() throws {
        let explicit = try resolve(.mid16GBMac, explicit: [.design: "speed"], prefersLowerMemory: false)
        XCTAssertEqual(explicit["design"]?.activeVariant, "speed")
        XCTAssertEqual(explicit["design"]?.source, "explicit")
        XCTAssertEqual(explicit["custom"]?.activeVariant, "quality")

        let lower = try resolve(.mid16GBMac, explicit: [.clone: "quality"], prefersLowerMemory: true)
        XCTAssertEqual(lower["custom"]?.activeVariant, "speed")
        XCTAssertEqual(lower["custom"]?.source, "prefer-lower-memory")
        XCTAssertEqual(lower["clone"]?.activeVariant, "quality", "an explicit choice outranks the preference")

        let unknown = try resolve(.floor8GBMac, explicit: [.custom: "turbo"])
        XCTAssertEqual(unknown["custom"]?.activeVariant, "speed", "an unknown stored choice is ignored")
    }

    func testATakeFallsBackToAnInstalledPackage() throws {
        let choices = try resolve(.mid16GBMac, installed: ["pro_custom_speed"])
        XCTAssertEqual(choices["custom"]?.activeVariant, "quality")
        XCTAssertEqual(choices["custom"]?.activeInstalled, false)
        XCTAssertEqual(choices["custom"]?.generationVariant, "speed")
        XCTAssertEqual(choices["custom"]?.generationModelID, "pro_custom_speed")
        XCTAssertNil(choices["design"]?.generationVariant, "nothing installed for Design")
    }
}

/// RF-26: `models verify` hashes every installed file against the catalog's
/// size and digest, cancellably; `isComplete` judges an install as the app does.
final class DesktopModelInventoryTests: XCTestCase {
    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DesktopModelInventory-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func expected(_ name: String, _ data: Data) -> DesktopModelInventory.ExpectedFile {
        let digest = SHA256.hash(data: data).map { unsafe String(format: "%02x", $0) }.joined()
        return DesktopModelInventory.ExpectedFile(relativePath: name, sizeBytes: Int64(data.count), sha256: digest)
    }

    func testVerifySortsEveryFileIntoItsOutcome() async throws {
        let folder = try makeRoot()
        let good = Data("weights".utf8)
        try good.write(to: folder.appendingPathComponent("good.bin"))
        try Data("weigh".utf8).write(to: folder.appendingPathComponent("truncated.bin"))
        try FileManager.default.linkItem(
            at: folder.appendingPathComponent("good.bin"), to: folder.appendingPathComponent("hardlink.bin")
        )
        try FileManager.default.createSymbolicLink(
            at: folder.appendingPathComponent("symlink.bin"), withDestinationURL: folder.appendingPathComponent("good.bin")
        )
        let checked = Mutex(0)
        let result = try await DesktopModelInventory.verify(
            [expected("good.bin", good), expected("truncated.bin", good), expected("missing.bin", good),
             expected("hardlink.bin", good), expected("symlink.bin", good)],
            in: folder
        ) { count in checked.withLock { $0 = count } }
        XCTAssertEqual(result.missingPaths, ["missing.bin"])
        XCTAssertEqual(result.mismatchedPaths, ["symlink.bin", "truncated.bin"], "a link is not the installed file")
        XCTAssertEqual(result.unreadablePaths, [])
        XCTAssertEqual(result.verifiedBytes, Int64(good.count * 2), "a hard link is the same verified file")
        XCTAssertFalse(result.passed)
        XCTAssertEqual(checked.withLock { $0 }, 5)
    }

    func testVerifyStopsWhenCancelled() async throws {
        let folder = try makeRoot()
        let data = Data("x".utf8)
        try data.write(to: folder.appendingPathComponent("a.bin"))
        let file = expected("a.bin", data)
        let task = Task { () async throws -> DesktopModelInventory.Verification in
            unsafe withUnsafeCurrentTask { unsafe $0?.cancel() }
            return try await DesktopModelInventory.verify([file], in: folder)
        }
        do {
            _ = try await task.value
            XCTFail("a cancelled verification must not finish")
        } catch is CancellationError {}
    }

    func testAnInstallIsCompleteOnlyWithEveryRequiredFile() throws {
        let manifest = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let registry = try ContractBackedModelRegistry(manifestURL: manifest)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let descriptor = try XCTUnwrap(registry.model(id: "pro_custom_speed"))
        let models = try makeRoot()
        XCTAssertFalse(DesktopModelInventory.isComplete(descriptor, modelsDirectory: models))
        let folder = descriptor.installDirectory(in: models)
        for path in descriptor.requiredRelativePaths.dropLast() {
            let url = folder.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data().write(to: url)
        }
        XCTAssertFalse(DesktopModelInventory.isComplete(descriptor, modelsDirectory: models), "one required file is missing")
        let last = try XCTUnwrap(descriptor.requiredRelativePaths.last)
        try FileManager.default.createDirectory(
            at: folder.appendingPathComponent(last).deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try Data().write(to: folder.appendingPathComponent(last))
        XCTAssertTrue(
            DesktopModelInventory.isComplete(descriptor, modelsDirectory: models),
            "every file present and no integrity manifest to contradict them, as the app decides"
        )
    }
}

/// RF-27: CLI takes run through the app's engine store. Each request is
/// admitted under its own recorded consent, switched on the one shared host.
/// RF-28: `models remove` removes as the app's model manager does, and never
/// while another engine may have the model loaded.
final class DesktopModelRemovalTests: XCTestCase {
    func testAModelIsRemovedOnlyWhileNoOtherEngineRuns() throws {
        let repository = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let registry = try ContractBackedModelRegistry(
            manifestURL: repository.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        ).expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let descriptor = try XCTUnwrap(registry.model(id: "pro_custom_speed"))
        let models = FileManager.default.temporaryDirectory.appendingPathComponent("models-\(UUID().uuidString)")
        addTeardownBlock { try? FileManager.default.removeItem(at: models) }
        let folder = descriptor.installDirectory(in: models)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try Data(repeating: 0, count: 4096).write(to: folder.appendingPathComponent("model.safetensors"))
        let other = try XCTUnwrap(registry.model(id: "pro_custom_quality"))
        try FileManager.default.createDirectory(at: other.installDirectory(in: models), withIntermediateDirectories: true)

        XCTAssertThrowsError(try DesktopModelRemoval.remove(descriptor, modelsDirectory: models, otherEngineRunning: true)) {
            XCTAssertEqual($0 as? DesktopModelRemoval.Refusal, .engineRunning)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.path), "nothing is removed while another engine runs")

        try DesktopModelRemoval.remove(descriptor, modelsDirectory: models, otherEngineRunning: false)
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: other.installDirectory(in: models).path), "only that model")
        XCTAssertThrowsError(try DesktopModelRemoval.remove(descriptor, modelsDirectory: models, otherEngineRunning: false)) {
            XCTAssertEqual($0 as? DesktopModelRemoval.Refusal, .notInstalled)
        }
    }
}

@MainActor
final class DesktopEngineHostTests: XCTestCase {
    func testTheHostAdmitsEachRequestUnderItsOwnConsent() async throws {
        let repository = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("DesktopEngineHost-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let runtime = try NativeRuntimeFactory.make(
            manifestURL: repository.appendingPathComponent("Sources/Resources/qwenvoice_contract.json"),
            paths: .rooted(at: root), storeVersionSeed: "rf27-host-fixture"
        )
        defer { runtime.engine.stop() }
        let host = DesktopEngineHost(
            engine: runtime.engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: false), deviceClass: .mid16GBMac
        )
        let clone = GenerationRequest(
            mode: .clone, modelID: "pro_clone_speed", text: "Hello.",
            outputPath: root.appendingPathComponent("take.wav").path, shouldStream: false,
            payload: .clone(reference: CloneReference(
                audioPath: root.appendingPathComponent("reference.wav").path, transcript: nil, preparedVoiceID: nil
            )),
            generationID: UUID()
        )
        do {
            _ = try await host.generate(clone)
            XCTFail("a clone without recorded consent must be refused")
        } catch {
            XCTAssertTrue(error is VoiceCloningConsentRequiredError, "\(error)")
        }
        host.setConsent(VoiceCloningConsentPolicy(isConsentRecorded: true))
        do {
            _ = try await host.generate(clone)
            XCTFail("the uninitialized fixture engine cannot generate")
        } catch {
            XCTAssertFalse(error is VoiceCloningConsentRequiredError, "consent now admits it; the engine refuses: \(error)")
        }
    }
}
