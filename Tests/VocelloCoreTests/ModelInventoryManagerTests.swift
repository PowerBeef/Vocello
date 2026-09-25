import Foundation
import QwenVoiceCore
import XCTest

/// PA-19: the iPhone model manager (`ModelManagerViewModel`, the inventory the
/// Studio and Settings read) over a scripted status provider, and its local
/// provider over a real `LocalModelAssetStore` on a private directory.
@MainActor
final class ModelInventoryManagerTests: XCTestCase {
    @MainActor
    private final class ScriptedStatusProvider: ModelStatusProviding {
        var initial: [String: ModelInventoryStatus] = [:]
        var refreshed: [String: ModelInventoryStatus] = [:]
        var likelyInstalled: Set<String> = []
        var suspendsRefresh = false
        private(set) var initialModelIDs: [String] = []
        private(set) var refreshCount = 0
        private var pendingRefresh: CheckedContinuation<Void, Never>?

        func initialStatuses(for models: [TTSModel]) -> [String: ModelInventoryStatus] {
            initialModelIDs = models.map(\.id)
            return initial
        }

        func refreshStatuses(for models: [TTSModel]) async -> [String: ModelInventoryStatus] {
            refreshCount += 1
            if suspendsRefresh {
                await withCheckedContinuation { pendingRefresh = $0 }
            }
            return refreshed
        }

        func releaseRefresh() {
            pendingRefresh?.resume()
            pendingRefresh = nil
        }

        func isLikelyInstalled(_ model: TTSModel) -> Bool {
            likelyInstalled.contains(model.id)
        }
    }

    private var contractURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    }

    private func makeRegistry() throws -> ContractBackedModelRegistry {
        try ContractBackedModelRegistry(manifestURL: contractURL)
    }

    private func waitUntil(
        _ description: String,
        file: StaticString = #filePath,
        line: UInt = #line,
        _ condition: () -> Bool
    ) async {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(2))
        while !condition() {
            guard clock.now < deadline else {
                XCTFail("Timed out waiting for \(description)", file: file, line: line)
                return
            }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    func testInitialInventoryComesFromTheProviderForTheInventoriedModels() throws {
        let registry = try makeRegistry()
        let models = registry.models
        XCTAssertGreaterThanOrEqual(models.count, 3, "One model per Studio mode")
        let provider = ScriptedStatusProvider()
        provider.initial = [models[0].id: .installed(sizeBytes: 10), models[1].id: .checking]

        let manager = ModelManagerViewModel(modelRegistry: registry, statusProvider: provider, models: models)
        XCTAssertEqual(manager.statuses, provider.initial)
        XCTAssertEqual(provider.initialModelIDs, models.map(\.id))
        XCTAssertEqual(provider.refreshCount, 0, "Construction never scans the disk")
    }

    func testAvailabilityFollowsStatusAndUsesTheCheapProbeOnlyWhileChecking() throws {
        let registry = try makeRegistry()
        let models = Array(registry.models.prefix(3))
        let provider = ScriptedStatusProvider()
        let manager = ModelManagerViewModel(modelRegistry: registry, statusProvider: provider, models: models)
        let model = models[0]

        let expectations: [(ModelInventoryStatus?, Bool)] = [
            (.installed(sizeBytes: 1), true),
            (.updateAvailable(sizeBytes: 1, stalePaths: ["model.safetensors"]), true),
            (.notInstalled, false),
            (.incomplete(message: "missing", sizeBytes: 1), false),
            (.error(message: "failed"), false),
            (nil, false),
        ]
        provider.likelyInstalled = [model.id]
        for (status, available) in expectations {
            manager.statuses[model.id] = status
            XCTAssertEqual(manager.isAvailable(model), available, "\(String(describing: status))")
        }

        manager.statuses[model.id] = .checking
        XCTAssertTrue(manager.isAvailable(model), "Checking falls back to the likely-installed probe")
        provider.likelyInstalled = []
        XCTAssertFalse(manager.isAvailable(model))
        XCTAssertFalse(manager.isLikelyInstalled(model))
    }

    func testConcurrentRefreshesJoinOnePassThatReplacesTheInventory() async throws {
        let registry = try makeRegistry()
        let models = registry.models
        let provider = ScriptedStatusProvider()
        provider.initial = [models[0].id: .checking]
        provider.refreshed = [models[0].id: .notInstalled, models[1].id: .installed(sizeBytes: 5)]
        provider.suspendsRefresh = true
        let manager = ModelManagerViewModel(modelRegistry: registry, statusProvider: provider, models: models)

        let first = Task { await manager.refresh() }
        await waitUntil("the first refresh pass") { provider.refreshCount == 1 }
        let second = Task { await manager.refresh() }
        for _ in 0..<5 { await Task.yield() }
        XCTAssertEqual(provider.refreshCount, 1, "A refresh during a pass joins it")
        XCTAssertEqual(manager.statuses, provider.initial)

        provider.releaseRefresh()
        await first.value
        await second.value
        XCTAssertEqual(provider.refreshCount, 1)
        XCTAssertEqual(manager.statuses, provider.refreshed)

        provider.suspendsRefresh = false
        await manager.refresh()
        XCTAssertEqual(provider.refreshCount, 2, "A later refresh runs a new pass")
    }

    func testAssetStatesMapToInventoryStatuses() {
        func integrity(missing: [String], size: Int64) -> AssetIntegrity {
            AssetIntegrity(
                status: missing.isEmpty ? .verified : .incomplete,
                localRootPath: "/nonexistent/models/pro_custom",
                missingRelativePaths: missing,
                presentRelativePaths: ["config.json"],
                sizeBytes: size
            )
        }

        XCTAssertEqual(LocalModelStatusProvider.status(from: .notInstalled), .notInstalled)
        XCTAssertEqual(
            LocalModelStatusProvider.status(from: .available(integrity(missing: [], size: 1_234))),
            .installed(sizeBytes: 1_234)
        )
        XCTAssertEqual(
            LocalModelStatusProvider.status(from: .incomplete(integrity(missing: ["a", "b"], size: 99))),
            .incomplete(message: "Installation incomplete: missing 2 required files.", sizeBytes: 99)
        )
        XCTAssertEqual(
            LocalModelStatusProvider.status(from: .incomplete(integrity(missing: ["a"], size: 9))),
            .incomplete(message: "Installation incomplete: missing 1 required file.", sizeBytes: 9)
        )
        XCTAssertEqual(
            LocalModelStatusProvider.status(from: .downloading(downloadedBytes: 1, totalBytes: 2)),
            .checking
        )
        XCTAssertEqual(LocalModelStatusProvider.status(from: .deleting), .checking)
        XCTAssertEqual(LocalModelStatusProvider.status(from: .failed(message: "disk")), .error(message: "disk"))
    }

    func testLocalProviderInventoriesARealModelDirectory() async throws {
        let registry = try makeRegistry()
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ModelInventory-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let assetStore = LocalModelAssetStore(
            modelRegistry: registry,
            rootDirectory: root,
            storeVersionSeed: "pa19-inventory-fixture"
        )
        let models = registry.models
        let installed = models[0]
        let partial = models[1]
        let descriptor = try XCTUnwrap(assetStore.descriptor(id: installed.id))
        for artifact in descriptor.artifacts {
            let url = assetStore.localURL(for: descriptor, artifact: artifact)
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data("pa19".utf8).write(to: url)
        }
        let partialDescriptor = try XCTUnwrap(assetStore.descriptor(id: partial.id))
        let firstArtifact = try XCTUnwrap(partialDescriptor.artifacts.first)
        XCTAssertGreaterThan(partialDescriptor.artifacts.count, 1)
        let partialURL = assetStore.localURL(for: partialDescriptor, artifact: firstArtifact)
        try FileManager.default.createDirectory(
            at: partialURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try Data("pa19".utf8).write(to: partialURL)

        let manager = ModelManagerViewModel(
            modelRegistry: registry,
            statusProvider: LocalModelStatusProvider(modelAssetStore: assetStore),
            models: models
        )
        // The launch inventory defers the complete-install check to the refresh.
        XCTAssertEqual(manager.statuses[installed.id], .checking)
        XCTAssertTrue(manager.isAvailable(installed), "A complete install is usable while checking")
        XCTAssertFalse(manager.isAvailable(partial))

        await manager.refresh()
        guard case .installed(let size) = manager.statuses[installed.id] else {
            return XCTFail("Expected an installed model, got \(String(describing: manager.statuses[installed.id]))")
        }
        XCTAssertGreaterThan(size, 0)
        guard case .incomplete = manager.statuses[partial.id] else {
            return XCTFail("Expected an incomplete model, got \(String(describing: manager.statuses[partial.id]))")
        }
        for model in models.dropFirst(2) {
            XCTAssertEqual(manager.statuses[model.id], .notInstalled)
            XCTAssertFalse(manager.isAvailable(model))
        }
    }
}
