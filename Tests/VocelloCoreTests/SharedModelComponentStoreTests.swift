import CryptoKit
import Foundation
@testable import QwenVoiceCore
import XCTest

final class SharedModelComponentStoreTests: XCTestCase {
    private enum ProbeError: Error { case failed }

    func testContentAndCompatibilityIdentitiesAreDeterministicAndIndependent() throws {
        let first = try identity(path: "codec/config.json", bytes: Data("config".utf8))
        let second = try identity(path: "codec/weights.safetensors", bytes: Data("weights".utf8))
        let contentA = try SharedComponentContentIdentity(files: [first, second])
        let contentB = try SharedComponentContentIdentity(files: [second, first])
        XCTAssertEqual(contentA, contentB)

        let decoder = try compatibility(content: contentA, capability: .decoderOnly)
        let encoder = try compatibility(content: contentA, capability: .encoderAndDecoder)
        XCTAssertNotEqual(decoder.digest, contentA.digest)
        XCTAssertNotEqual(decoder.digest, encoder.digest)
        XCTAssertTrue(encoder.satisfies(decoder))
        XCTAssertFalse(decoder.satisfies(encoder))

        let profileChange = try SharedComponentCompatibilityIdentity(
            contentDigest: contentA.digest,
            componentSchemaVersion: 1,
            loaderABI: "qwen3-loader-v1",
            runtimeProfileSignature: "profile-b",
            encoderCapability: .decoderOnly
        )
        XCTAssertFalse(profileChange.satisfies(decoder))
    }

    func testIdentityValidationRejectsTraversalDuplicateAndTamperedDigest() throws {
        XCTAssertThrowsError(try SharedComponentFileIdentity(
            relativePath: "../weights.bin",
            byteCount: 1,
            sha256: String(repeating: "a", count: 64)
        ))
        let file = try identity(path: "weights.bin", bytes: Data("a".utf8))
        XCTAssertThrowsError(try SharedComponentContentIdentity(files: [file, file]))

        let content = try SharedComponentContentIdentity(files: [file])
        let encoded = try JSONEncoder().encode(content)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        object["digest"] = String(repeating: "f", count: 64)
        let tampered = try JSONSerialization.data(withJSONObject: object)
        XCTAssertThrowsError(try JSONDecoder().decode(SharedComponentContentIdentity.self, from: tampered))
    }

    func testPublishDeepVerifiesAndRepairsCorruptContentAddressedBlob() throws {
        let root = try temporaryDirectory("publish")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let source = root.appendingPathComponent("source", isDirectory: true)
        try write(Data("immutable-component".utf8), to: source.appendingPathComponent("codec/weights.bin"))
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "codec/weights.bin",
            fileURL: source.appendingPathComponent("codec/weights.bin")
        )
        let content = try SharedComponentContentIdentity(files: [file])
        let store = SharedModelComponentStore(modelsRoot: models)

        let first = try store.publish(content: content, from: source)
        XCTAssertEqual(first.publishedDigests, [file.sha256])
        XCTAssertTrue(first.reusedDigests.isEmpty)
        let blob = try store.blobURL(for: file.sha256)
        XCTAssertEqual(try Data(contentsOf: blob), Data("immutable-component".utf8))
        XCTAssertFalse(try blob.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink ?? true)

        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: blob.path)
        try Data("corrupt-component".utf8).write(to: blob)
        let repaired = try store.publish(content: content, from: source)
        XCTAssertEqual(repaired.publishedDigests, [file.sha256])
        XCTAssertEqual(try Data(contentsOf: blob), Data("immutable-component".utf8))

        let reused = try store.publish(content: content, from: source)
        XCTAssertEqual(reused.reusedDigests, [file.sha256])
        XCTAssertTrue(reused.publishedDigests.isEmpty)
    }

    func testPublishRejectsSymbolicLinkSource() throws {
        let root = try temporaryDirectory("symlink")
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        try write(Data("component".utf8), to: source.appendingPathComponent("real.bin"))
        try FileManager.default.createSymbolicLink(
            at: source.appendingPathComponent("linked.bin"),
            withDestinationURL: source.appendingPathComponent("real.bin")
        )
        let expected = try identity(path: "linked.bin", bytes: Data("component".utf8))
        let content = try SharedComponentContentIdentity(files: [expected])
        let store = SharedModelComponentStore(modelsRoot: root.appendingPathComponent("models"))

        XCTAssertThrowsError(try store.publish(content: content, from: source)) { error in
            XCTAssertEqual(
                error as? SharedModelComponentStoreError,
                .nonRegularFile(relativePath: "linked.bin")
            )
        }
    }

    func testPublishRejectsSymbolicLinkInIntermediatePath() throws {
        let root = try temporaryDirectory("symlink-ancestor")
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let outside = root.appendingPathComponent("outside", isDirectory: true)
        try write(Data("component".utf8), to: outside.appendingPathComponent("weights.bin"))
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(
            at: source.appendingPathComponent("codec", isDirectory: true),
            withDestinationURL: outside
        )
        let expected = try identity(
            path: "codec/weights.bin",
            bytes: Data("component".utf8)
        )
        let store = SharedModelComponentStore(
            modelsRoot: root.appendingPathComponent("models", isDirectory: true)
        )

        XCTAssertThrowsError(try store.publish(
            content: SharedComponentContentIdentity(files: [expected]),
            from: source
        )) { error in
            XCTAssertEqual(
                error as? SharedModelComponentStoreError,
                .invalidRelativePath
            )
        }
    }

    func testMigrationUsesRegularHardLinksAndManifestDerivedLiveness() throws {
        let root = try temporaryDirectory("migration")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let componentBytes = Data("same-component-across-models".utf8)
        let component = try identity(path: "codec/shared.bin", bytes: componentBytes)
        let content = try SharedComponentContentIdentity(files: [component])
        let compatibility = try compatibility(content: content, capability: .encoderAndDecoder)
        let store = SharedModelComponentStore(modelsRoot: models)

        for (folder, modelIdentity) in [("model-a", "custom-speed"), ("model-b", "design-speed")] {
            let model = models.appendingPathComponent(folder, isDirectory: true)
            try write(componentBytes, to: model.appendingPathComponent(component.relativePath))
            try write(Data("unique-\(folder)".utf8), to: model.appendingPathComponent("model/weights.bin"))
            let manifest = try SharedComponentInstalledModelManifest(
                modelIdentity: modelIdentity,
                contentIdentity: content,
                compatibilityIdentity: compatibility
            )
            let plan = try SharedComponentMigrationPlan(modelFolder: folder, manifest: manifest)
            let result = try store.migrate(plan) { installed in
                guard FileManager.default.fileExists(
                    atPath: installed.appendingPathComponent("model/weights.bin").path
                ) else { throw ProbeError.failed }
            }
            XCTAssertEqual(result.linkedFileCount, 1)
        }

        let blob = try store.blobURL(for: component.sha256)
        let modelA = models.appendingPathComponent("model-a/codec/shared.bin")
        let modelB = models.appendingPathComponent("model-b/codec/shared.bin")
        XCTAssertTrue(try sameFile(blob, modelA))
        XCTAssertTrue(try sameFile(blob, modelB))
        XCTAssertFalse(try modelA.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink ?? true)
        XCTAssertEqual(try Data(contentsOf: models.appendingPathComponent("model-a/model/weights.bin")), Data("unique-model-a".utf8))
        XCTAssertEqual(
            try store.liveness(),
            SharedComponentLiveness(
                modelIdentities: ["custom-speed", "design-speed"],
                liveBlobDigests: [component.sha256]
            )
        )

        // The store publishes read-only inodes, so ordinary mutation fails.
        // If the owner deliberately changes inode permissions, every hard
        // link is affected; audits must fail closed until authenticated bytes
        // are republished and every model is relinked by repair.
        XCTAssertThrowsError(try FileHandle(forWritingTo: modelA))
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o644],
            ofItemAtPath: modelA.path
        )
        let corruptHandle = try FileHandle(forWritingTo: modelA)
        try corruptHandle.truncate(atOffset: 0)
        try corruptHandle.write(contentsOf: Data("corrupt".utf8))
        try corruptHandle.close()
        XCTAssertEqual(try store.audit(modelFolder: "model-a").state, .corruptStore)
        XCTAssertEqual(try store.audit(modelFolder: "model-b").state, .corruptStore)

        let recovery = root.appendingPathComponent("authenticated-recovery", isDirectory: true)
        try write(componentBytes, to: recovery.appendingPathComponent(component.relativePath))
        _ = try store.publish(content: content, from: recovery)
        for folder in ["model-a", "model-b"] {
            _ = try store.repair(modelFolder: folder) { installed in
                guard FileManager.default.fileExists(
                    atPath: installed.appendingPathComponent("model/weights.bin").path
                ) else { throw ProbeError.failed }
            }
            XCTAssertEqual(try store.audit(modelFolder: folder).state, .healthy)
        }
        let repairedBlob = try store.blobURL(for: component.sha256)
        XCTAssertTrue(try sameFile(repairedBlob, modelA))
        XCTAssertTrue(try sameFile(repairedBlob, modelB))
        XCTAssertEqual(try Data(contentsOf: modelA), componentBytes)

        try store.deleteModel(modelFolder: "model-a")
        let firstPrune = try store.pruneUnreferencedComponents()
        XCTAssertTrue(firstPrune.removedDigests.isEmpty)
        XCTAssertEqual(firstPrune.preservedDigests, [component.sha256])
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))

        try store.deleteModel(modelFolder: "model-b")
        let finalPrune = try store.pruneUnreferencedComponents()
        XCTAssertEqual(finalPrune.removedDigests, [component.sha256])
        XCTAssertFalse(FileManager.default.fileExists(atPath: blob.path))
    }

    func testValidationFailureAtomicallyRestoresOriginalModel() throws {
        let root = try temporaryDirectory("rollback")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let model = models.appendingPathComponent("model-a", isDirectory: true)
        let componentBytes = Data("rollback-component".utf8)
        try write(componentBytes, to: model.appendingPathComponent("codec/shared.bin"))
        try write(Data("original-unique".utf8), to: model.appendingPathComponent("unique.bin"))
        let component = try identity(path: "codec/shared.bin", bytes: componentBytes)
        let content = try SharedComponentContentIdentity(files: [component])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "model-a",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .decoderOnly)
        )
        let store = SharedModelComponentStore(modelsRoot: models)

        XCTAssertThrowsError(try store.migrate(
            SharedComponentMigrationPlan(modelFolder: "model-a", manifest: manifest)
        ) { _ in
            throw ProbeError.failed
        }) { error in
            XCTAssertEqual(error as? SharedModelComponentStoreError, .validationFailed)
        }

        XCTAssertEqual(try Data(contentsOf: model.appendingPathComponent("codec/shared.bin")), componentBytes)
        XCTAssertEqual(try Data(contentsOf: model.appendingPathComponent("unique.bin")), Data("original-unique".utf8))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: model.appendingPathComponent(SharedComponentInstalledModelManifest.filename).path
        ))
        XCTAssertEqual(try store.audit(modelFolder: "model-a").state, .unmanaged)
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: models.path)
            .filter { $0.contains("component-migration") }
        XCTAssertTrue(leftovers.isEmpty)
    }

    func testRepairRestoresMissingAndCopiedComponentLinks() throws {
        let fixture = try migratedFixture(label: "repair")
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let visible = fixture.model.appendingPathComponent(fixture.file.relativePath)
        try FileManager.default.removeItem(at: visible)
        try write(Data("standalone-copy".utf8), to: visible)

        let before = try fixture.store.audit(modelFolder: fixture.model.lastPathComponent)
        XCTAssertEqual(before.state, .repairable)
        XCTAssertEqual(before.copiedRelativePaths, [fixture.file.relativePath])

        _ = try fixture.store.repair(modelFolder: fixture.model.lastPathComponent) { installed in
            guard FileManager.default.fileExists(atPath: installed.appendingPathComponent("unique.bin").path) else {
                throw ProbeError.failed
            }
        }
        let blob = try fixture.store.blobURL(for: fixture.file.sha256)
        XCTAssertTrue(try sameFile(blob, visible))
        XCTAssertEqual(try fixture.store.audit(modelFolder: fixture.model.lastPathComponent).state, .healthy)

        try FileManager.default.removeItem(at: visible)
        XCTAssertEqual(try fixture.store.audit(modelFolder: fixture.model.lastPathComponent).state, .repairable)
        _ = try fixture.store.repair(modelFolder: fixture.model.lastPathComponent) { _ in }
        XCTAssertTrue(try sameFile(blob, visible))
    }

    func testCorruptStoreBlobFailsRepairClosed() throws {
        let fixture = try migratedFixture(label: "corrupt")
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let blob = try fixture.store.blobURL(for: fixture.file.sha256)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: blob.path)
        try Data("bad".utf8).write(to: blob)

        let audit = try fixture.store.audit(modelFolder: fixture.model.lastPathComponent)
        XCTAssertEqual(audit.state, .corruptStore)
        XCTAssertEqual(audit.corruptBlobDigests, [fixture.file.sha256])
        XCTAssertThrowsError(try fixture.store.repair(modelFolder: fixture.model.lastPathComponent) { _ in })
    }

    func testCorruptInstalledManifestPreventsPruning() throws {
        let fixture = try migratedFixture(label: "manifest")
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let manifest = fixture.model.appendingPathComponent(SharedComponentInstalledModelManifest.filename)
        try Data("not-json".utf8).write(to: manifest, options: .atomic)
        let blob = try fixture.store.blobURL(for: fixture.file.sha256)

        XCTAssertThrowsError(try fixture.store.pruneUnreferencedComponents())
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))
    }

    func testStagedInstallReusesVerifiedBlobPublishesHardLinksAndPreservesBlobOnDelete() throws {
        let root = try temporaryDirectory("staged-install")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let source = root.appendingPathComponent("source", isDirectory: true)
        let stage = root.appendingPathComponent("stage", isDirectory: true)
        let componentBytes = Data("verified-component".utf8)
        try write(componentBytes, to: source.appendingPathComponent("speech_tokenizer/model.bin"))
        try write(Data("unique-model".utf8), to: stage.appendingPathComponent("model.bin"))
        let component = try SharedComponentFileIdentity.verify(
            relativePath: "speech_tokenizer/model.bin",
            fileURL: source.appendingPathComponent("speech_tokenizer/model.bin")
        )
        let content = try SharedComponentContentIdentity(files: [component])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "pro_custom:speed",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .encoderAndDecoder)
        )
        let plan = try SharedComponentMigrationPlan(modelFolder: "model-a", manifest: manifest)
        let store = SharedModelComponentStore(modelsRoot: models)
        _ = try store.publish(content: content, from: source)

        let result = try store.installStagedModel(plan, stagedModelURL: stage) { candidate in
            guard FileManager.default.fileExists(atPath: candidate.appendingPathComponent("model.bin").path),
                  FileManager.default.fileExists(
                      atPath: candidate.appendingPathComponent(component.relativePath).path
                  ) else { throw ProbeError.failed }
        }
        XCTAssertEqual(result.linkedFileCount, 1)
        let target = models.appendingPathComponent("model-a", isDirectory: true)
        let visible = target.appendingPathComponent(component.relativePath)
        let blob = try store.blobURL(for: component.sha256)
        XCTAssertTrue(try sameFile(blob, visible))
        let values = try visible.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        XCTAssertTrue(values.isRegularFile ?? false)
        XCTAssertFalse(values.isSymbolicLink ?? true)
        XCTAssertEqual(try store.audit(modelFolder: "model-a").state, .healthy)

        try store.deleteModel(modelFolder: "model-a")
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))
    }

    func testStagedInstallValidationFailureLeavesExistingTargetAndStageUntouched() throws {
        let root = try temporaryDirectory("staged-rollback")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let source = root.appendingPathComponent("source", isDirectory: true)
        let stage = root.appendingPathComponent("stage", isDirectory: true)
        let target = models.appendingPathComponent("model-a", isDirectory: true)
        let componentBytes = Data("component".utf8)
        try write(componentBytes, to: source.appendingPathComponent("codec/shared.bin"))
        try write(Data("candidate".utf8), to: stage.appendingPathComponent("unique.bin"))
        try write(Data("original".utf8), to: target.appendingPathComponent("unique.bin"))
        let component = try SharedComponentFileIdentity.verify(
            relativePath: "codec/shared.bin",
            fileURL: source.appendingPathComponent("codec/shared.bin")
        )
        let content = try SharedComponentContentIdentity(files: [component])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "model-a",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .decoderOnly)
        )
        let plan = try SharedComponentMigrationPlan(modelFolder: "model-a", manifest: manifest)
        let store = SharedModelComponentStore(modelsRoot: models)
        _ = try store.publish(content: content, from: source)

        XCTAssertThrowsError(try store.installStagedModel(plan, stagedModelURL: stage) { _ in
            throw ProbeError.failed
        })
        XCTAssertEqual(
            try Data(contentsOf: target.appendingPathComponent("unique.bin")),
            Data("original".utf8)
        )
        XCTAssertEqual(
            try Data(contentsOf: stage.appendingPathComponent("unique.bin")),
            Data("candidate".utf8)
        )
    }

    func testStagedInstallRejectsAnySymbolicLink() throws {
        let root = try temporaryDirectory("staged-symlink")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let stage = root.appendingPathComponent("stage", isDirectory: true)
        let bytes = Data("component".utf8)
        try write(bytes, to: stage.appendingPathComponent("codec/shared.bin"))
        try write(Data("unique".utf8), to: stage.appendingPathComponent("real.bin"))
        try FileManager.default.createSymbolicLink(
            at: stage.appendingPathComponent("linked.bin"),
            withDestinationURL: stage.appendingPathComponent("real.bin")
        )
        let component = try SharedComponentFileIdentity.verify(
            relativePath: "codec/shared.bin",
            fileURL: stage.appendingPathComponent("codec/shared.bin")
        )
        let content = try SharedComponentContentIdentity(files: [component])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "model-a",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .decoderOnly)
        )
        let store = SharedModelComponentStore(modelsRoot: models)

        XCTAssertThrowsError(try store.installStagedModel(
            SharedComponentMigrationPlan(modelFolder: "model-a", manifest: manifest),
            stagedModelURL: stage
        ) { _ in })
        XCTAssertFalse(FileManager.default.fileExists(atPath: models.appendingPathComponent("model-a").path))
    }

    func testInstalledIntegrityManifestReadsLegacySchemaAndRoundTripsSharedIdentity() throws {
        let legacy = Data(#"""
        {
          "schema_version": 1,
          "repo": "org/model",
          "revision": "revision",
          "target_folder": "model-a",
          "created_at_utc": "2026-07-17T00:00:00Z",
          "files": [{"path":"model.bin","size":3,"sha256":null}]
        }
        """#.utf8)
        let decodedLegacy = try JSONDecoder().decode(ModelAssetIntegrityManifest.self, from: legacy)
        XCTAssertEqual(decodedLegacy.schemaVersion, 1)
        XCTAssertNil(decodedLegacy.sharedComponentContentIdentity)
        XCTAssertNil(decodedLegacy.sharedComponentCompatibilityIdentity)

        let file = try identity(path: "codec/shared.bin", bytes: Data("shared".utf8))
        let content = try SharedComponentContentIdentity(files: [file])
        let compatibility = try compatibility(content: content, capability: .decoderOnly)
        let current = ModelAssetIntegrityManifest(
            repo: "org/model",
            revision: "revision",
            targetFolder: "model-a",
            createdAtUTC: "2026-07-17T00:00:00Z",
            files: [.init(path: "codec/shared.bin", size: file.byteCount, sha256: file.sha256)],
            sharedComponentContentIdentity: content,
            sharedComponentCompatibilityIdentity: compatibility
        )
        XCTAssertEqual(
            try JSONDecoder().decode(
                ModelAssetIntegrityManifest.self,
                from: JSONEncoder().encode(current)
            ),
            current
        )
    }

    func testConcurrentPublishersConvergeOnOneVerifiedBlob() async throws {
        let root = try temporaryDirectory("concurrent")
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let bytes = Data(repeating: 0x5a, count: 32_768)
        try write(bytes, to: source.appendingPathComponent("codec/shared.bin"))
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "codec/shared.bin",
            fileURL: source.appendingPathComponent("codec/shared.bin")
        )
        let content = try SharedComponentContentIdentity(files: [file])
        let models = root.appendingPathComponent("models", isDirectory: true)

        let results = try await withThrowingTaskGroup(of: SharedComponentPublicationResult.self) { group in
            for _ in 0..<8 {
                group.addTask {
                    try SharedModelComponentStore(modelsRoot: models).publish(content: content, from: source)
                }
            }
            var results: [SharedComponentPublicationResult] = []
            for try await result in group { results.append(result) }
            return results
        }

        XCTAssertEqual(results.count, 8)
        XCTAssertEqual(results.flatMap(\.publishedDigests).count, 1)
        XCTAssertEqual(results.flatMap(\.reusedDigests).count, 7)
        let blob = try SharedModelComponentStore(modelsRoot: models).blobURL(for: file.sha256)
        XCTAssertEqual(try Data(contentsOf: blob), bytes)
    }

    func testActorCoordinatorUsesSameStoreContract() async throws {
        let root = try temporaryDirectory("actor")
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let bytes = Data("actor-safe".utf8)
        try write(bytes, to: source.appendingPathComponent("component.bin"))
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "component.bin",
            fileURL: source.appendingPathComponent("component.bin")
        )
        let content = try SharedComponentContentIdentity(files: [file])
        let coordinator = SharedModelComponentStoreCoordinator(
            modelsRoot: root.appendingPathComponent("models", isDirectory: true)
        )

        let result = try await coordinator.publish(content: content, from: source)
        XCTAssertEqual(result.publishedDigests, [file.sha256])
        let liveness = try await coordinator.liveness()
        XCTAssertEqual(liveness.liveBlobDigests, [])
    }

    /// PA-22 / CORE-07: deleting a model reclaims the shared blobs no installed manifest still
    /// lists, and sweeps `trash/` and `staging/` entries interrupted operations left behind.
    func testDeleteReclaimsUnreferencedComponentsAndSweepsLeftovers() throws {
        let fixture = try migratedFixture(label: "reclaim")
        defer { try? FileManager.default.removeItem(at: fixture.root) }
        let store = fixture.store
        let blob = try store.blobURL(for: fixture.file.sha256)
        let interruptedDelete = store.storeRoot.appendingPathComponent("trash/model-interrupted", isDirectory: true)
        let interruptedPublish = store.storeRoot.appendingPathComponent("staging/interrupted", isDirectory: true)
        try write(Data("tombstoned".utf8), to: interruptedDelete.appendingPathComponent("weights.bin"))
        try write(Data("partial".utf8), to: interruptedPublish.appendingPathComponent("blob.bin"))

        try store.deleteModel(modelFolder: fixture.model.lastPathComponent, componentGracePeriod: 0)

        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.model.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: blob.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: interruptedDelete.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: interruptedPublish.path))
        XCTAssertEqual(
            try FileManager.default.contentsOfDirectory(
                atPath: store.storeRoot.appendingPathComponent("trash", isDirectory: true).path
            ),
            []
        )
    }

    /// Automatic reclamation never takes a component an install in flight may still need: a blob
    /// another hard link holds (the install replica) or one published within the grace period.
    /// It also never creates a store that does not exist yet.
    func testAutomaticReclaimProtectsInFlightAndFreshComponents() throws {
        let root = try temporaryDirectory("reclaim-protection")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let source = root.appendingPathComponent("source", isDirectory: true)
        try write(Data("published-not-installed".utf8), to: source.appendingPathComponent("component.bin"))
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "component.bin",
            fileURL: source.appendingPathComponent("component.bin")
        )
        let store = SharedModelComponentStore(modelsRoot: models)
        XCTAssertEqual(
            try store.reclaimUnreferencedComponents(gracePeriod: 0),
            SharedComponentPruneResult(removedDigests: [], preservedDigests: [])
        )
        XCTAssertFalse(FileManager.default.fileExists(atPath: store.storeRoot.path))

        _ = try store.publish(content: SharedComponentContentIdentity(files: [file]), from: source)
        let blob = try store.blobURL(for: file.sha256)
        XCTAssertEqual(try store.reclaimUnreferencedComponents().preservedDigests, [file.sha256])
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))

        let replica = models.appendingPathComponent(".model-a.component-install.fixture", isDirectory: true)
        try FileManager.default.createDirectory(at: replica, withIntermediateDirectories: true)
        try FileManager.default.linkItem(at: blob, to: replica.appendingPathComponent("component.bin"))
        XCTAssertEqual(try store.reclaimUnreferencedComponents(gracePeriod: 0).preservedDigests, [file.sha256])
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))

        try FileManager.default.removeItem(at: replica)
        XCTAssertEqual(try store.reclaimUnreferencedComponents(gracePeriod: 0).removedDigests, [file.sha256])
        XCTAssertFalse(FileManager.default.fileExists(atPath: blob.path))
    }

    /// PA-22 / CORE-08: a model loaded by an earlier build carries the engine's overlay of
    /// absolute symlinks inside its folder. Migration and repair used to fail on it and fall back
    /// to a full re-download; they now drop the rebuildable overlay and succeed.
    func testMigrationAndRepairSucceedWithLegacyPreparedOverlayPresent() throws {
        let root = try temporaryDirectory("legacy-overlay")
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        let model = models.appendingPathComponent("model-legacy", isDirectory: true)
        let bytes = Data("shared-legacy".utf8)
        try write(bytes, to: model.appendingPathComponent("codec/shared.bin"))
        try write(Data("unique".utf8), to: model.appendingPathComponent("unique.bin"))
        try addLegacyOverlay(to: model)
        let file = try identity(path: "codec/shared.bin", bytes: bytes)
        let content = try SharedComponentContentIdentity(files: [file])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "identity-legacy",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .decoderOnly)
        )
        let store = SharedModelComponentStore(modelsRoot: models)
        let validate: @Sendable (URL) throws -> Void = { installed in
            guard FileManager.default.fileExists(atPath: installed.appendingPathComponent("unique.bin").path) else {
                throw ProbeError.failed
            }
        }

        _ = try store.migrate(
            SharedComponentMigrationPlan(modelFolder: model.lastPathComponent, manifest: manifest),
            validateInstalledModel: validate
        )
        XCTAssertEqual(try store.audit(modelFolder: model.lastPathComponent).state, .healthy)
        XCTAssertEqual(try Data(contentsOf: model.appendingPathComponent("unique.bin")), Data("unique".utf8))
        XCTAssertFalse(hasLegacyOverlayEntries(in: model))

        try addLegacyOverlay(to: model)
        try FileManager.default.removeItem(at: model.appendingPathComponent(file.relativePath))
        XCTAssertEqual(try store.audit(modelFolder: model.lastPathComponent).state, .repairable)
        _ = try store.repair(modelFolder: model.lastPathComponent, validateInstalledModel: validate)
        XCTAssertEqual(try store.audit(modelFolder: model.lastPathComponent).state, .healthy)
        XCTAssertFalse(hasLegacyOverlayEntries(in: model))

        // Idempotent: nothing left to remove is not an error.
        PreparedModelOverlay.removeLegacyOverlay(in: model)
        XCTAssertEqual(try store.audit(modelFolder: model.lastPathComponent).state, .healthy)
    }

    func testPreparedModelOverlayLivesUnderTheRuntimeCache() {
        let source = URL(fileURLWithPath: "/fixture/models/Qwen3-TTS-Fixture", isDirectory: true)
        let hubCache = URL(fileURLWithPath: "/fixture/cache/native_mlx", isDirectory: true)
        let overlay = PreparedModelOverlay.directory(forSourceDirectory: source, hubCacheDirectory: hubCache)
        XCTAssertEqual(overlay.path, "/fixture/cache/native_mlx/prepared_models/Qwen3-TTS-Fixture")
        XCTAssertFalse(overlay.path.hasPrefix(source.path + "/"))
    }

    /// The overlay layout builds before PA-22 wrote: absolute symlinks to the model's files,
    /// plus an interrupted rebuild next to it.
    private func addLegacyOverlay(to model: URL) throws {
        for directoryName in [
            PreparedModelOverlay.legacyDirectoryName,
            "\(PreparedModelOverlay.legacyDirectoryName).tmp.fixture",
        ] {
            let overlay = model.appendingPathComponent(directoryName, isDirectory: true)
            try FileManager.default.createDirectory(
                at: overlay.appendingPathComponent("codec", isDirectory: true),
                withIntermediateDirectories: true
            )
            try FileManager.default.createSymbolicLink(
                atPath: overlay.appendingPathComponent("unique.bin").path,
                withDestinationPath: model.appendingPathComponent("unique.bin").path
            )
            try FileManager.default.createSymbolicLink(
                atPath: overlay.appendingPathComponent("codec/shared.bin").path,
                withDestinationPath: model.appendingPathComponent("codec/shared.bin").path
            )
        }
    }

    private func hasLegacyOverlayEntries(in model: URL) -> Bool {
        let entries = (try? FileManager.default.contentsOfDirectory(atPath: model.path)) ?? []
        return entries.contains { $0.hasPrefix(PreparedModelOverlay.legacyDirectoryName) }
    }

    private struct MigratedFixture {
        let root: URL
        let model: URL
        let store: SharedModelComponentStore
        let file: SharedComponentFileIdentity
    }

    private func migratedFixture(label: String) throws -> MigratedFixture {
        let root = try temporaryDirectory(label)
        let models = root.appendingPathComponent("models", isDirectory: true)
        let model = models.appendingPathComponent("model-\(label)", isDirectory: true)
        let bytes = Data("shared-\(label)".utf8)
        try write(bytes, to: model.appendingPathComponent("codec/shared.bin"))
        try write(Data("unique".utf8), to: model.appendingPathComponent("unique.bin"))
        let file = try identity(path: "codec/shared.bin", bytes: bytes)
        let content = try SharedComponentContentIdentity(files: [file])
        let manifest = try SharedComponentInstalledModelManifest(
            modelIdentity: "identity-\(label)",
            contentIdentity: content,
            compatibilityIdentity: compatibility(content: content, capability: .decoderOnly)
        )
        let store = SharedModelComponentStore(modelsRoot: models)
        _ = try store.migrate(
            SharedComponentMigrationPlan(modelFolder: model.lastPathComponent, manifest: manifest)
        ) { installed in
            guard FileManager.default.fileExists(atPath: installed.appendingPathComponent("unique.bin").path) else {
                throw ProbeError.failed
            }
        }
        return MigratedFixture(root: root, model: model, store: store, file: file)
    }

    private func compatibility(
        content: SharedComponentContentIdentity,
        capability: SharedComponentEncoderCapability
    ) throws -> SharedComponentCompatibilityIdentity {
        try SharedComponentCompatibilityIdentity(
            contentDigest: content.digest,
            componentSchemaVersion: 1,
            loaderABI: "qwen3-loader-v1",
            runtimeProfileSignature: "qwen3-runtime-v1",
            encoderCapability: capability
        )
    }

    private func identity(path: String, bytes: Data) throws -> SharedComponentFileIdentity {
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        return try SharedComponentFileIdentity(
            relativePath: path,
            byteCount: Int64(bytes.count),
            sha256: digest
        )
    }

    private func temporaryDirectory(_ label: String) throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-component-store-\(label)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func write(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: url, options: .atomic)
    }

    private func sameFile(_ first: URL, _ second: URL) throws -> Bool {
        let lhs = try FileManager.default.attributesOfItem(atPath: first.path)
        let rhs = try FileManager.default.attributesOfItem(atPath: second.path)
        return (lhs[.systemNumber] as? NSNumber)?.uint64Value == (rhs[.systemNumber] as? NSNumber)?.uint64Value
            && (lhs[.systemFileNumber] as? NSNumber)?.uint64Value == (rhs[.systemFileNumber] as? NSNumber)?.uint64Value
    }
}
