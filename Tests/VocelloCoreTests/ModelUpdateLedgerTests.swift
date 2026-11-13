import Foundation
@testable import QwenVoiceCore
import XCTest

/// RF-59: the model update plan's ledger, which outlives the retired folders it is found from.
final class ModelUpdateLedgerTests: XCTestCase {
    private var root: URL!
    private var models: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("update-ledger-\(UUID().uuidString)", isDirectory: true)
        models = root.appendingPathComponent("models", isDirectory: true)
        try FileManager.default.createDirectory(at: models, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: models.path)
        try? FileManager.default.removeItem(at: root)
    }

    private static func model(_ mode: GenerationMode, retiring folders: [String]) -> ModelDescriptor {
        ModelDescriptor(
            id: "pro_\(mode.rawValue)", name: mode.rawValue, tier: "speed", folder: "\(mode.rawValue)-hybrid",
            mode: mode, huggingFaceRepo: "org/\(mode.rawValue)", artifactVersion: "1", iosDownloadEligible: true,
            estimatedDownloadBytes: nil, outputSubfolder: "out", requiredRelativePaths: ["model.safetensors"],
            retiredFolders: folders
        )
    }

    private let all = [
        model(.custom, retiring: ["custom-4bit", "custom-8bit"]),
        model(.design, retiring: ["design-4bit"]),
        model(.clone, retiring: ["clone-4bit"]),
    ]

    /// An earlier build's completed install: the folder and an integrity manifest naming it.
    private func installEarlier(_ folder: String, manifestTarget: String? = nil) throws {
        let url = models.appendingPathComponent(folder, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        try Data("old".utf8).write(to: url.appendingPathComponent("model.safetensors"))
        let manifest = ModelAssetIntegrityManifest(
            repo: "org/old", revision: "rev", targetFolder: manifestTarget ?? folder,
            createdAtUTC: "2026-09-14T00:00:00Z",
            files: [.init(path: "model.safetensors", size: 3, sha256: String(repeating: "ab", count: 32))]
        )
        try JSONEncoder().encode(manifest).write(to: url.appendingPathComponent(ModelAssetIntegrityManifest.filename))
    }

    private func reconcile(
        installed: Set<GenerationMode> = [], change: ModelUpdateLedger.Change = .none
    ) throws -> ModelUpdatePlan {
        try ModelUpdateLedger.reconcile(
            models: all, in: models, isInstalled: { installed.contains($0.mode) }, change: change
        )
    }

    func testOnlyACompletedEarlierInstallCounts() throws {
        try installEarlier("custom-4bit")
        try installEarlier("design-4bit", manifestTarget: "somewhere-else")
        try FileManager.default.createDirectory(
            at: models.appendingPathComponent("clone-4bit"), withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: models.appendingPathComponent(".qwenvoice-downloads/custom-8bit"), withIntermediateDirectories: true
        )
        XCTAssertTrue(ModelUpdateLedger.holdsEarlierInstall("custom-4bit", in: models))
        XCTAssertFalse(ModelUpdateLedger.holdsEarlierInstall("design-4bit", in: models), "a manifest for another folder")
        XCTAssertFalse(ModelUpdateLedger.holdsEarlierInstall("clone-4bit", in: models), "no manifest")
        XCTAssertFalse(ModelUpdateLedger.holdsEarlierInstall("custom-8bit", in: models), "staging only")
        try Data().write(to: models.appendingPathComponent("plain-file"))
        XCTAssertFalse(ModelUpdateLedger.holdsEarlierInstall("plain-file", in: models))
        XCTAssertEqual(try reconcile().modes, [.custom])
    }

    func testThePlanOutlivesItsEvidenceUntilEachModeIsInstalled() throws {
        try installEarlier("custom-4bit")
        try installEarlier("custom-8bit")
        try installEarlier("clone-4bit")
        let plan = try reconcile()
        XCTAssertEqual(plan.modes, [.custom, .clone])
        XCTAssertEqual(plan.entries[.custom]?.retiredFolders, ["custom-4bit", "custom-8bit"])
        XCTAssertEqual(ModelUpdateLedger.read(in: models), plan)

        for folder in ["custom-4bit", "custom-8bit", "clone-4bit"] {
            try FileManager.default.removeItem(at: models.appendingPathComponent(folder))
        }
        XCTAssertEqual(try reconcile().modes, [.custom, .clone], "the reclaim removed the evidence, not the plan")
        XCTAssertEqual(try reconcile(installed: [.custom]).modes, [.clone])
        XCTAssertTrue(try reconcile(installed: [.custom, .clone]).isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: models.appendingPathComponent(ModelUpdateLedger.filename).path))
        XCTAssertTrue(try reconcile().isEmpty, "nothing left to find")
    }

    /// The launch and refresh passes that change nothing stay reads: the file is not rewritten.
    func testAPassThatChangesNothingWritesNothing() throws {
        try installEarlier("custom-4bit")
        _ = try reconcile()
        let ledger = models.appendingPathComponent(ModelUpdateLedger.filename)
        let before = try FileManager.default.attributesOfItem(atPath: ledger.path)
        _ = try reconcile()
        _ = try reconcile(installed: [.design])
        let after = try FileManager.default.attributesOfItem(atPath: ledger.path)
        XCTAssertEqual(before[.systemFileNumber] as? Int, after[.systemFileNumber] as? Int, "same file, never replaced")
        _ = try reconcile(change: .pause(.custom))
        let paused = try FileManager.default.attributesOfItem(atPath: ledger.path)
        XCTAssertNotEqual(before[.systemFileNumber] as? Int, paused[.systemFileNumber] as? Int, "a change replaces it")
    }

    func testPauseAndResume() throws {
        try installEarlier("custom-4bit")
        try installEarlier("clone-4bit")
        XCTAssertEqual(try reconcile(change: .pause(.custom)).activeModes, [.clone])
        let reread = try reconcile()
        XCTAssertTrue(reread.isPaused(.custom), "a pause survives the next pass")
        XCTAssertEqual(reread.modes, [.custom, .clone])
        XCTAssertEqual(try reconcile(change: .resume(.custom)).activeModes, [.custom, .clone])
        _ = try reconcile(change: .pause(.clone))
        XCTAssertEqual(try reconcile(change: .resumeAll).activeModes, [.custom, .clone])
    }

    /// A build before the integrity manifests left only the weights; they still count.
    func testAnInstallFromBeforeIntegrityManifestsCounts() throws {
        let folder = models.appendingPathComponent("clone-4bit", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try Data().write(to: folder.appendingPathComponent("model.safetensors"))
        XCTAssertFalse(ModelUpdateLedger.holdsEarlierInstall("clone-4bit", in: models), "empty weights")
        try Data("w".utf8).write(to: folder.appendingPathComponent("model.safetensors"))
        XCTAssertTrue(ModelUpdateLedger.holdsEarlierInstall("clone-4bit", in: models))
    }

    func testConcurrentWritersLoseNothing() throws {
        for folder in ["custom-4bit", "design-4bit", "clone-4bit"] { try installEarlier(folder) }
        let directory = models!
        let descriptors = all
        let modes = GenerationMode.allCases
        DispatchQueue.concurrentPerform(iterations: 60) { index in
            _ = try? ModelUpdateLedger.reconcile(
                models: descriptors, in: directory, isInstalled: { _ in false },
                change: .pause(modes[index % modes.count])
            )
        }
        let plan = ModelUpdateLedger.read(in: models)
        XCTAssertEqual(plan.modes, [.custom, .design, .clone])
        XCTAssertTrue(plan.modes.allSatisfy(plan.isPaused), "every writer's pause landed")
    }

    func testAnUnreadableOrNewerLedgerIsSetAsideAndRebuilt() throws {
        try installEarlier("design-4bit")
        let ledger = models.appendingPathComponent(ModelUpdateLedger.filename)
        let aside = models.appendingPathComponent(ModelUpdateLedger.setAsideFilename)
        try Data("{ not json".utf8).write(to: ledger)
        XCTAssertTrue(ModelUpdateLedger.read(in: models).isEmpty)
        XCTAssertEqual(try reconcile().modes, [.design], "rebuilt from the folders on disk")
        XCTAssertTrue(FileManager.default.fileExists(atPath: aside.path))

    }

    /// An older build sharing the Mac's folder never erases a newer build's plan: it records and
    /// deletes nothing.
    func testANewerBuildsLedgerIsLeftAloneAndNothingIsDeleted() throws {
        try installEarlier("design-4bit")
        let ledger = models.appendingPathComponent(ModelUpdateLedger.filename)
        let newer = Data(#"{"schemaVersion": 99, "entries": [{"mode": "clone", "future": true}]}"#.utf8)
        try newer.write(to: ledger)
        XCTAssertTrue(ModelUpdateLedger.read(in: models).isEmpty)
        XCTAssertThrowsError(try reconcile()) { error in
            XCTAssertEqual(error as? ModelUpdateLedger.LedgerError, .newerLedger(99))
        }
        let result = RetiredModelReclamation.reclaim(models: all, in: models) { _ in true }
        XCTAssertEqual(result.removed, [])
        XCTAssertTrue(FileManager.default.fileExists(atPath: models.appendingPathComponent("design-4bit").path))
        XCTAssertEqual(try Data(contentsOf: ledger), newer, "untouched")
    }

    func testAPlanThatCannotBeRecordedRemovesNothing() throws {
        try installEarlier("custom-4bit")
        // The folder stays writable (the deletion itself would succeed); only the ledger's lock fails.
        try FileManager.default.createDirectory(
            at: models.appendingPathComponent(ModelUpdateLedger.lockFilename), withIntermediateDirectories: true
        )
        let result = RetiredModelReclamation.reclaim(models: all, in: models, force: true) { _ in true }
        XCTAssertEqual(result.removed, [])
        XCTAssertEqual(Array(result.failed.keys), ["custom-4bit"])
        XCTAssertTrue(result.failed["custom-4bit"]?.contains("update plan could not be recorded") == true)
        XCTAssertTrue(FileManager.default.fileExists(atPath: models.appendingPathComponent("custom-4bit").path))
    }

    /// Every host's entry records the plan before it deletes: the Mac's and the CLI's registry, and
    /// the iPhone's store (at launch, and before an update on a nearly full phone).
    func testEveryHostEntryRecordsThePlanBeforeDeleting() throws {
        let contract = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let registry = try ContractBackedModelRegistry(manifestURL: contract)
            .expandedForPlatform(.macOS, deviceClass: nil, includeBaseAliases: false)
        let designOld = "Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit"
        try installEarlier(designOld)
        let mac = registry.reclaimRetiredFolders(in: models) { $0.mode == .custom }
        XCTAssertEqual(mac.removed, [designOld])
        XCTAssertEqual(ModelUpdateLedger.read(in: models).modes, [.design])
        try FileManager.default.removeItem(at: models.appendingPathComponent(ModelUpdateLedger.filename))

        try installEarlier("design-4bit")
        let descriptors = all.map {
            ModelAssetDescriptor(model: $0, version: "test",
                                 artifacts: [ModelAssetArtifact(relativePath: "model.safetensors", scope: .modelSpecific)])
        }
        let store = LocalModelAssetStore(rootDirectory: models, descriptors: descriptors)
        XCTAssertEqual(store.reclaimRetiredFolders(), .nothing, "nothing verified at launch")
        let forced = store.removeRetiredFoldersBeforeUpdate()
        XCTAssertEqual(forced.removed, ["design-4bit"], "the user agreed to make room first")
        XCTAssertEqual(store.modelUpdatePlan().modes, [.design])

        // A mode whose current model is available leaves the plan.
        let current = models.appendingPathComponent("design-hybrid", isDirectory: true)
        try FileManager.default.createDirectory(at: current, withIntermediateDirectories: true)
        try Data("new".utf8).write(to: current.appendingPathComponent("model.safetensors"))
        XCTAssertTrue(try store.reconcileModelUpdatePlan().isEmpty)
    }

    func testThePlanIsRecordedBeforeTheFoldersGo() throws {
        try installEarlier("custom-4bit")
        try installEarlier("design-4bit")
        let result = RetiredModelReclamation.reclaim(models: all, in: models) { $0.mode == .custom }
        XCTAssertEqual(result.removed, ["custom-4bit", "design-4bit"])
        XCTAssertGreaterThan(result.freedBytes, 0)
        let plan = ModelUpdateLedger.read(in: models)
        XCTAssertEqual(plan.modes, [.design], "Custom Voice's new model is installed; Voice Design's still needs its update")
        XCTAssertEqual(plan.entries[.design]?.retiredFolders, ["design-4bit"])
        XCTAssertEqual(RetiredModelReclamation.reclaim(models: all, in: models) { _ in true }, .nothing)
    }
}
