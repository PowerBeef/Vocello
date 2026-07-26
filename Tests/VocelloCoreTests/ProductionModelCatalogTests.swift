import CryptoKit
import Foundation
import XCTest
@testable import QwenVoiceCore

final class ProductionModelCatalogTests: XCTestCase {
    func testCheckedInSchemaV2CatalogCoversSixArtifactsAndOnlyThreeIOSSpeedArtifacts() throws {
        let repositoryRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let catalog = try ProductionModelCatalog(
            contentsOf: repositoryRoot.appendingPathComponent(
                "Sources/Resources/qwenvoice_production_model_catalog.json"
            )
        )

        XCTAssertEqual(catalog.schemaVersion, 2)
        XCTAssertEqual(catalog.artifacts.count, 6)
        XCTAssertEqual(catalog.sharedComponents.count, 1)
        XCTAssertEqual(
            catalog.sharedComponents[0].contentIdentity.files.map(\.relativePath),
            [
                "speech_tokenizer/config.json",
                "speech_tokenizer/configuration.json",
                "speech_tokenizer/model.safetensors",
                "speech_tokenizer/preprocessor_config.json",
            ]
        )
        XCTAssertEqual(
            Set(catalog.artifacts.filter { $0.platforms.contains(.iOS) }.map(\.identity)),
            ["pro_custom:speed", "pro_design:speed", "pro_clone:speed"]
        )
        XCTAssertTrue(catalog.artifacts.allSatisfy {
            $0.sharedComponentIDs == [catalog.sharedComponents[0].id]
        })
    }

    func testCompleteCatalogResolvesExactAuthenticatedDownloadFiles() throws {
        let url = try writeCatalog(makeCatalog())
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }

        let catalog = try ProductionModelCatalog(contentsOf: url)
        let artifact = try catalog.artifact(
            modelID: "pro_custom",
            variantID: "quality",
            folder: "Custom-8bit",
            repo: "org/custom-8bit",
            revision: String(repeating: "a", count: 40),
            artifactVersion: "v1",
            estimatedDownloadBytes: 7,
            requiredRelativePaths: ["config.json", "weights/model.safetensors"]
        )

        XCTAssertEqual(artifact.totalBytes, 7)
        XCTAssertEqual(artifact.downloadFiles.map(\.path), ["config.json", "weights/model.safetensors"])
        XCTAssertEqual(
            artifact.downloadFiles.last?.absoluteURL?.absoluteString,
            "https://huggingface.co/org/custom-8bit/resolve/\(String(repeating: "a", count: 40))/weights/model.safetensors"
        )
        XCTAssertTrue(
            catalog.downloadURLPolicy.allowsRedirect(
                from: URL(string: "https://huggingface.co/file")!,
                to: URL(string: "https://cas-bridge.xethub.hf.co/object")!
            )
        )
        XCTAssertTrue(catalog.downloadURLPolicy.allowsInitialRequest(artifact.baseURL))
        XCTAssertFalse(
            catalog.downloadURLPolicy.allowsInitialRequest(URL(string: "https://attacker.invalid/object")!)
        )
    }

    func testIncompleteCatalogFailsClosed() throws {
        var document = makeCatalog()
        document["activationState"] = "staged"
        document["missingArtifactIdentities"] = ["pro_custom:quality"]
        let url = try writeCatalog(document)
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }

        XCTAssertThrowsError(try ProductionModelCatalog(contentsOf: url)) { error in
            XCTAssertEqual(
                error as? ProductionModelCatalog.Error,
                .incomplete(["pro_custom:quality"])
            )
        }
    }

    func testMissingDigestAndUntrustedBaseURLFailClosed() throws {
        for mutation in ["digest", "host"] {
            var document = makeCatalog()
            var artifacts = document["artifacts"] as! [[String: Any]]
            if mutation == "digest" {
                var files = artifacts[0]["files"] as! [[String: Any]]
                files[0]["sha256"] = ""
                artifacts[0]["files"] = files
            } else {
                artifacts[0]["baseURL"] = "https://attacker.invalid/org/custom-8bit/resolve/\(String(repeating: "a", count: 40))"
            }
            document["artifacts"] = artifacts
            let url = try writeCatalog(document)
            defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            XCTAssertThrowsError(try ProductionModelCatalog(contentsOf: url), mutation)
        }
    }

    func testDescriptorDriftFailsBeforeDownload() throws {
        let url = try writeCatalog(makeCatalog())
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let catalog = try ProductionModelCatalog(contentsOf: url)

        XCTAssertThrowsError(try catalog.artifactMatchingMacOSDescriptor(
            folder: "Custom-8bit",
            repo: "org/custom-8bit",
            revision: String(repeating: "b", count: 40),
            artifactVersion: "v1",
            estimatedDownloadBytes: 7,
            requiredRelativePaths: ["config.json", "weights/model.safetensors"]
        )) { error in
            guard case ProductionModelCatalog.Error.descriptorMismatch = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    func testDeliverySkipsSharedBytesOnlyAfterStoreDeepVerification() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let componentURL = source.appendingPathComponent("speech_tokenizer/model.safetensors")
        try FileManager.default.createDirectory(
            at: componentURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 0x4a, count: 64).write(to: componentURL)
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "speech_tokenizer/model.safetensors",
            fileURL: componentURL
        )
        let content = try SharedComponentContentIdentity(files: [file])
        let compatibility = try SharedComponentCompatibilityIdentity(
            contentDigest: content.digest,
            componentSchemaVersion: 1,
            loaderABI: "fixture-loader-v1",
            runtimeProfileSignature: "fixture-runtime-v1",
            encoderCapability: .encoderAndDecoder
        )
        let catalogURL = try writeCatalog(makeV2Catalog(
            content: content,
            compatibility: compatibility
        ))
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        let artifact = catalog.artifacts[0]
        let models = root.appendingPathComponent("models", isDirectory: true)

        let cold = try catalog.deliveryPlan(for: artifact, modelsRoot: models)
        XCTAssertEqual(cold.filesToDownload.map(\.path), artifact.files.map(\.relativePath))
        XCTAssertFalse(cold.reusedVerifiedComponent)

        _ = try SharedModelComponentStore(modelsRoot: models).publish(
            content: content,
            from: source
        )
        let warm = try catalog.deliveryPlan(for: artifact, modelsRoot: models)
        XCTAssertEqual(warm.filesToDownload.map(\.path), ["config.json"])
        XCTAssertEqual(warm.reusedComponentBytes, file.byteCount)

        let blob = try SharedModelComponentStore(modelsRoot: models).blobURL(for: file.sha256)
        try FileManager.default.removeItem(at: blob)
        try Data(repeating: 0x00, count: Int(file.byteCount)).write(to: blob)
        let corrupt = try catalog.deliveryPlan(for: artifact, modelsRoot: models)
        XCTAssertEqual(corrupt.filesToDownload.map(\.path), artifact.files.map(\.relativePath))
        XCTAssertFalse(corrupt.reusedVerifiedComponent)
    }

    func testInstalledFileSizeMismatchProbeReportsOnlyPresentFilesWithWrongSize() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let componentURL = source.appendingPathComponent("speech_tokenizer/model.safetensors")
        try FileManager.default.createDirectory(
            at: componentURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 0x4a, count: 64).write(to: componentURL)
        let file = try SharedComponentFileIdentity.verify(
            relativePath: "speech_tokenizer/model.safetensors",
            fileURL: componentURL
        )
        let content = try SharedComponentContentIdentity(files: [file])
        let compatibility = try SharedComponentCompatibilityIdentity(
            contentDigest: content.digest,
            componentSchemaVersion: 1,
            loaderABI: "fixture-loader-v1",
            runtimeProfileSignature: "fixture-runtime-v1",
            encoderCapability: .encoderAndDecoder
        )
        let catalog = try ProductionModelCatalog(contentsOf: writeCatalog(makeV2Catalog(
            content: content,
            compatibility: compatibility
        )))
        let artifact = catalog.artifacts[0]
        let models = root.appendingPathComponent("models", isDirectory: true)
        let folder = models.appendingPathComponent(artifact.folder, isDirectory: true)

        // Nothing installed: the probe reports no staleness (presence is availability's job).
        XCTAssertEqual(catalog.installedFileSizeMismatches(for: artifact, modelsRoot: models), [])

        let installedComponent = folder.appendingPathComponent("speech_tokenizer/model.safetensors")
        try FileManager.default.createDirectory(
            at: installedComponent.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 0x4a, count: 64).write(to: installedComponent)
        let configURL = folder.appendingPathComponent("config.json")
        try Data(repeating: 0x2f, count: 3).write(to: configURL)
        XCTAssertEqual(catalog.installedFileSizeMismatches(for: artifact, modelsRoot: models), [])

        // A present file whose byte count drifted from the pinned identity is reported;
        // a missing file is not.
        try Data(repeating: 0x2f, count: 5).write(to: configURL)
        try FileManager.default.removeItem(at: installedComponent)
        XCTAssertEqual(
            catalog.installedFileSizeMismatches(for: artifact, modelsRoot: models),
            ["config.json"]
        )
    }

    func testDeliveryPlanMigratesAuthenticatedLegacyInstallWithoutNetwork() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let legacy = root.appendingPathComponent("legacy", isDirectory: true)
        let componentURL = legacy.appendingPathComponent("speech_tokenizer/model.safetensors")
        try FileManager.default.createDirectory(
            at: componentURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 0x4a, count: 64).write(to: componentURL)
        let component = try SharedComponentFileIdentity.verify(
            relativePath: "speech_tokenizer/model.safetensors",
            fileURL: componentURL
        )
        let content = try SharedComponentContentIdentity(files: [component])
        let compatibility = try SharedComponentCompatibilityIdentity(
            contentDigest: content.digest,
            componentSchemaVersion: 1,
            loaderABI: "fixture-loader-v1",
            runtimeProfileSignature: "fixture-runtime-v1",
            encoderCapability: .encoderAndDecoder
        )
        let configuration = Data("cfg".utf8)
        let configurationFile = try SharedComponentFileIdentity(
            relativePath: "config.json",
            byteCount: Int64(configuration.count),
            sha256: SHA256.hash(data: configuration).map { String(format: "%02x", $0) }.joined()
        )
        let catalogURL = try writeCatalog(makeV2Catalog(
            content: content,
            compatibility: compatibility,
            configurationFile: configurationFile
        ))
        defer { try? FileManager.default.removeItem(at: catalogURL.deletingLastPathComponent()) }
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        let artifact = try XCTUnwrap(catalog.artifacts.first)
        let models = root.appendingPathComponent("models", isDirectory: true)
        let installed = models.appendingPathComponent(artifact.folder, isDirectory: true)
        try FileManager.default.createDirectory(
            at: installed.appendingPathComponent("speech_tokenizer", isDirectory: true),
            withIntermediateDirectories: true
        )
        try configuration.write(to: installed.appendingPathComponent("config.json"))
        try FileManager.default.copyItem(at: componentURL, to: installed.appendingPathComponent(component.relativePath))

        let delivery = try catalog.deliveryPlan(for: artifact, modelsRoot: models)

        XCTAssertEqual(delivery.filesToDownload.map(\.path), ["config.json"])
        let store = SharedModelComponentStore(modelsRoot: models)
        let blob = try store.blobURL(for: component.sha256)
        XCTAssertTrue(FileManager.default.fileExists(atPath: blob.path))
        XCTAssertEqual(try store.audit(modelFolder: artifact.folder).state, .healthy)
        XCTAssertTrue(try sameFile(blob, installed.appendingPathComponent(component.relativePath)))
    }

    func testDeliveryPlanRejectsTamperedLegacyInstallBeforePublishingAnyComponent() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("source", isDirectory: true)
        let componentURL = source.appendingPathComponent("speech_tokenizer/model.safetensors")
        try FileManager.default.createDirectory(
            at: componentURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data(repeating: 0x4a, count: 64).write(to: componentURL)
        let component = try SharedComponentFileIdentity.verify(
            relativePath: "speech_tokenizer/model.safetensors",
            fileURL: componentURL
        )
        let content = try SharedComponentContentIdentity(files: [component])
        let compatibility = try SharedComponentCompatibilityIdentity(
            contentDigest: content.digest,
            componentSchemaVersion: 1,
            loaderABI: "fixture-loader-v1",
            runtimeProfileSignature: "fixture-runtime-v1",
            encoderCapability: .encoderAndDecoder
        )
        let configuration = Data("cfg".utf8)
        let configurationFile = try SharedComponentFileIdentity(
            relativePath: "config.json",
            byteCount: Int64(configuration.count),
            sha256: SHA256.hash(data: configuration).map { String(format: "%02x", $0) }.joined()
        )
        let catalogURL = try writeCatalog(makeV2Catalog(
            content: content,
            compatibility: compatibility,
            configurationFile: configurationFile
        ))
        defer { try? FileManager.default.removeItem(at: catalogURL.deletingLastPathComponent()) }
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        let artifact = try XCTUnwrap(catalog.artifacts.first)
        let models = root.appendingPathComponent("models", isDirectory: true)
        let installed = models.appendingPathComponent(artifact.folder, isDirectory: true)
        try FileManager.default.createDirectory(
            at: installed.appendingPathComponent("speech_tokenizer", isDirectory: true),
            withIntermediateDirectories: true
        )
        try Data("bad".utf8).write(to: installed.appendingPathComponent("config.json"))
        try FileManager.default.copyItem(at: componentURL, to: installed.appendingPathComponent(component.relativePath))

        let delivery = try catalog.deliveryPlan(for: artifact, modelsRoot: models)
        XCTAssertEqual(delivery.filesToDownload.map(\.path), artifact.files.map(\.relativePath))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: SharedModelComponentStore(modelsRoot: models).storeRoot.path
        ))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: installed.appendingPathComponent(SharedComponentInstalledModelManifest.filename).path
        ))
    }

    private func makeCatalog() -> [String: Any] {
        let revision = String(repeating: "a", count: 40)
        return [
            "schemaVersion": 1,
            "catalogSchema": "config/model-catalog-schema-v1.json",
            "activationState": "complete",
            "allowedArtifactHosts": ["huggingface.co"],
            "allowedRedirectHostSuffixes": ["huggingface.co", "hf.co"],
            "sourceDigests": ["contract": String(repeating: "1", count: 64)],
            "missingArtifactIdentities": [],
            "artifacts": [[
                "modelID": "pro_custom",
                "variantID": "quality",
                "platforms": ["macOS"],
                "folder": "Custom-8bit",
                "repo": "org/custom-8bit",
                "revision": revision,
                "artifactVersion": "v1",
                "baseURL": "https://huggingface.co/org/custom-8bit/resolve/\(revision)",
                "totalBytes": 7,
                "files": [
                    [
                        "relativePath": "config.json",
                        "sizeBytes": 3,
                        "sha256": String(repeating: "2", count: 64),
                    ],
                    [
                        "relativePath": "weights/model.safetensors",
                        "sizeBytes": 4,
                        "sha256": String(repeating: "3", count: 64),
                    ],
                ],
            ]],
        ]
    }

    private func makeV2Catalog(
        content: SharedComponentContentIdentity,
        compatibility: SharedComponentCompatibilityIdentity,
        configurationFile: SharedComponentFileIdentity? = nil
    ) throws -> [String: Any] {
        let revision = String(repeating: "a", count: 40)
        let componentFile = content.files[0]
        let resolvedConfigurationFile: SharedComponentFileIdentity
        if let provided = configurationFile {
            resolvedConfigurationFile = provided
        } else {
            resolvedConfigurationFile = try SharedComponentFileIdentity(
                relativePath: "config.json",
                byteCount: 3,
                sha256: String(repeating: "3", count: 64)
            )
        }
        return [
            "schemaVersion": 2,
            "catalogSchema": "config/model-catalog-schema-v2.json",
            "activationState": "complete",
            "allowedArtifactHosts": ["huggingface.co"],
            "allowedRedirectHostSuffixes": ["huggingface.co", "hf.co"],
            "sourceDigests": ["contract": String(repeating: "1", count: 64)],
            "missingArtifactIdentities": [],
            "sharedComponents": [[
                "id": "speech-tokenizer-v1",
                "relativeRoot": "speech_tokenizer",
                "contentIdentity": try jsonObject(content),
                "compatibilityIdentity": try jsonObject(compatibility),
                "sourceArtifactIdentities": ["pro_custom:quality"],
            ]],
            "artifacts": [[
                "modelID": "pro_custom",
                "variantID": "quality",
                "platforms": ["macOS"],
                "folder": "Custom-8bit",
                "repo": "org/custom-8bit",
                "revision": revision,
                "artifactVersion": "v1",
                "baseURL": "https://huggingface.co/org/custom-8bit/resolve/\(revision)",
                "totalBytes": componentFile.byteCount + resolvedConfigurationFile.byteCount,
                "sharedComponentIDs": ["speech-tokenizer-v1"],
                "files": [
                    [
                        "relativePath": "config.json",
                        "sizeBytes": resolvedConfigurationFile.byteCount,
                        "sha256": resolvedConfigurationFile.sha256,
                    ],
                    [
                        "relativePath": componentFile.relativePath,
                        "sizeBytes": componentFile.byteCount,
                        "sha256": componentFile.sha256,
                    ],
                ],
            ]],
        ]
    }

    private func jsonObject<T: Encodable>(_ value: T) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
    }

    private func writeCatalog(_ document: [String: Any]) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("catalog.json")
        try JSONSerialization.data(withJSONObject: document, options: [.sortedKeys]).write(to: url)
        return url
    }

    private func sameFile(_ first: URL, _ second: URL) throws -> Bool {
        let lhs = try FileManager.default.attributesOfItem(atPath: first.path)
        let rhs = try FileManager.default.attributesOfItem(atPath: second.path)
        return (lhs[.systemNumber] as? NSNumber)?.uint64Value == (rhs[.systemNumber] as? NSNumber)?.uint64Value
            && (lhs[.systemFileNumber] as? NSNumber)?.uint64Value == (rhs[.systemFileNumber] as? NSNumber)?.uint64Value
    }
}
