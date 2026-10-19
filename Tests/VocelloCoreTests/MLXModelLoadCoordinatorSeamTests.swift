import CryptoKit
import Foundation
import XCTest
import os
@testable import QwenVoiceCore
import VocelloQwen3Core

/// DW-03 (workflow audit P2-5, engine audit B-30): `MLXModelLoadCoordinator`
/// driven through its injected seams over a synthetic installed Qwen3-TTS
/// folder. The real `LocalModelAssetStore`, runtime-profile validation,
/// prepared-cache validation, overlay rebuild and checkpoint-trust hashing all
/// run; only the loader is fake, and it returns an unloaded runtime actor, so
/// nothing touches MLX or Metal (the allocator is a recording seam). Every
/// assertion reads ground truth: loader calls, files on disk, the allocator
/// log and the values the coordinator returns.
final class MLXModelLoadCoordinatorSeamTests: XCTestCase {
    private static let idA = "fixture-custom-a"
    private static let idB = "fixture-custom-b"
    private static let folderA = "Qwen3-TTS-Fixture-CustomVoice-A"
    private static let folderB = "Qwen3-TTS-Fixture-CustomVoice-B"
    private static let repository = "fixture/Qwen3-TTS-Fixture-CustomVoice"
    /// Exactly 40 characters, as immutable artifact provenance requires.
    private static let revision = String(repeating: "0123456789", count: 4)
    private static let markerFileName = ".qvoice_prepared_cache.json"
    private static let sourceTrustFileName = ".qvoice_qwen_checkpoint_trust.json"
    private static let sentinelName = "fixture-sentinel"
    private static let speechTokenizerWeights = Data("fixture speech tokenizer weights".utf8)

    private static func talkerWeights(for id: String) -> Data {
        Data("fixture talker weights for \(id)".utf8)
    }

    private var sandbox: URL!

    override func setUpWithError() throws {
        sandbox = FileManager.default.temporaryDirectory
            .appendingPathComponent("load-coordinator-seam-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: sandbox, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: sandbox)
    }

    // MARK: - Prepared cache

    /// A first load mirrors the installed folder into the runtime cache,
    /// writes the current marker, hands the loader the overlay and publishes
    /// exactly the model the loader returned.
    func testColdLoadRebuildsTheOverlayAndPublishesTheLoaderModel() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)

        let result = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)

        XCTAssertTrue(result.didLoad)
        XCTAssertEqual(probes.loader.calls.map(\.modelID), [Self.idA])
        let call = try XCTUnwrap(probes.loader.calls.first)
        XCTAssertEqual(call.capabilityProfile, .customOnly)
        XCTAssertFalse(call.trustedPreparedCheckpoint, "no load has succeeded on these weights yet")
        XCTAssertEqual(call.preparedDirectory.path, overlayDirectory(Self.folderA).path)
        XCTAssertEqual(call.sourceDirectory?.path, sourceDirectory(Self.folderA).path)
        let resident = await coordinator.loadedModel
        XCTAssertTrue(resident === result.model, "the coordinator publishes the loader's model")
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertEqual(loadedID, Self.idA)

        XCTAssertEqual(result.booleanFlags["prepared_model_cache_hit"], false)
        XCTAssertEqual(result.booleanFlags["prepared_overlay_rebuilt"], true)
        XCTAssertEqual(result.booleanFlags["fixture_loader_flag"], true, "the loader's diagnostics reach the caller")
        XCTAssertEqual(result.timingsMS["fixture_loader_ms"], 7)
        XCTAssertNotNil(result.timingsMS["cache_prepare"])
        XCTAssertNotNil(result.timingsMS["mlx_model_load"])
        XCTAssertEqual(result.modelRuntimeIdentity.resolvedModelID, Self.idA)
        XCTAssertEqual(result.modelRuntimeIdentity.huggingFaceRevision, Self.revision)
        XCTAssertEqual(result.modelRuntimeIdentity.nativeLoadCapabilityProfile, "custom_only")
        XCTAssertEqual(
            result.modelRuntimeIdentity.speechTokenizerDigest,
            sha256Hex(Self.speechTokenizerWeights),
            "the speech-tokenizer digest comes from the installed integrity manifest"
        )
        XCTAssertNotNil(result.modelRuntimeIdentity.runtimeProfileSignature)

        let marker = try XCTUnwrap(jsonObject(at: markerURL(Self.folderA)))
        XCTAssertEqual(marker["schemaVersion"] as? Int, 3)
        XCTAssertEqual(marker["descriptorVersion"] as? String, "fixture-v1")
        let overlay = overlayDirectory(Self.folderA)
        XCTAssertEqual(itemType(overlay.appendingPathComponent("model.safetensors")), .typeSymbolicLink)
        XCTAssertEqual(itemType(overlay.appendingPathComponent("config.json")), .typeRegular)
        XCTAssertEqual(itemType(overlay.appendingPathComponent("tokenizer.json")), .typeSymbolicLink)

        XCTAssertEqual(probes.allocator.entries, [], "a load from empty releases nothing")
        XCTAssertEqual(probes.beforeLoads.entries, ["none"])
        let needsUnload = await coordinator.requiresUnloadAfterRuntimeFailure()
        XCTAssertFalse(needsUnload, "a fresh runtime actor has observed no MLX failure")
    }

    /// A reload on the same coordinator reuses the overlay in place and, now
    /// that a load succeeded, hands the loader a trusted checkpoint.
    func testASecondLoadReusesTheOverlayAndTrustsTheCheckpoint() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)

        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        await coordinator.unloadModel()
        try dropSentinel(in: Self.folderA)
        let second = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)

        XCTAssertTrue(second.didLoad)
        XCTAssertEqual(second.booleanFlags["prepared_model_cache_hit"], true)
        XCTAssertEqual(second.booleanFlags["prepared_overlay_rebuilt"], false)
        XCTAssertTrue(sentinelSurvived(Self.folderA), "reuse leaves the overlay directory in place")
        XCTAssertEqual(probes.loader.calls.map(\.trustedPreparedCheckpoint), [false, true])
        let prepared = probes.diagnostics.details(of: "coordinator-load-after-prepare-local-cache")
        XCTAssertEqual(prepared.map { $0["rebuiltPreparedCache"] }, ["true", "false"])
        XCTAssertEqual(prepared.map { $0["reusedPreparedCache"] }, ["false", "true"])
        XCTAssertEqual(prepared.map { $0["performedTokenizerPreparation"] }, ["true", "false"])
    }

    /// A new coordinator (a relaunch) has no in-memory metadata and validates
    /// the overlay from its marker on disk.
    func testAFreshCoordinatorReusesAValidOverlayFromDisk() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        _ = try await makeCoordinator([descriptor], probes: Probes())
            .loadModel(id: Self.idA, capabilityProfile: .customOnly)
        try dropSentinel(in: Self.folderA)

        let probes = Probes()
        let relaunched = makeCoordinator([descriptor], probes: probes)
        let result = try await relaunched.loadModel(id: Self.idA, capabilityProfile: .customOnly)

        XCTAssertEqual(result.booleanFlags["prepared_model_cache_hit"], true)
        XCTAssertTrue(sentinelSurvived(Self.folderA))
        XCTAssertEqual(
            probes.loader.calls.map(\.trustedPreparedCheckpoint),
            [true],
            "the marker's trust matches the installed weights"
        )
    }

    /// A marker written by another prepared-cache schema is never reused.
    func testAMarkerFromAnotherSchemaVersionForcesARebuild() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        _ = try await makeCoordinator([descriptor], probes: Probes())
            .loadModel(id: Self.idA, capabilityProfile: .customOnly)
        var marker = try XCTUnwrap(jsonObject(at: markerURL(Self.folderA)))
        marker["schemaVersion"] = 2
        try JSONSerialization.data(withJSONObject: marker).write(to: markerURL(Self.folderA))
        try dropSentinel(in: Self.folderA)

        let result = try await makeCoordinator([descriptor], probes: Probes())
            .loadModel(id: Self.idA, capabilityProfile: .customOnly)

        XCTAssertEqual(result.booleanFlags["prepared_overlay_rebuilt"], true)
        XCTAssertFalse(sentinelSurvived(Self.folderA), "the stale overlay was replaced")
        XCTAssertEqual(jsonObject(at: markerURL(Self.folderA))?["schemaVersion"] as? Int, 3)
    }

    /// A descriptor version change (an artifact or store-seed change) is never
    /// served from the overlay the previous descriptor prepared.
    func testADescriptorVersionChangeForcesARebuild() async throws {
        let original = try installModel(id: Self.idA, folder: Self.folderA)
        _ = try await makeCoordinator([original], probes: Probes())
            .loadModel(id: Self.idA, capabilityProfile: .customOnly)
        try dropSentinel(in: Self.folderA)

        let updated = descriptor(id: Self.idA, folder: Self.folderA, version: "fixture-v2")
        let result = try await makeCoordinator([updated], probes: Probes())
            .loadModel(id: Self.idA, capabilityProfile: .customOnly)

        XCTAssertEqual(result.booleanFlags["prepared_overlay_rebuilt"], true)
        XCTAssertFalse(sentinelSurvived(Self.folderA))
        XCTAssertEqual(jsonObject(at: markerURL(Self.folderA))?["descriptorVersion"] as? String, "fixture-v2")
    }

    /// A missing marker, an unreadable marker and a missing prepared artifact
    /// each force a rebuild, even with valid metadata still in memory.
    func testAMissingUnreadableOrIncompleteOverlayIsRebuilt() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)

        let withoutMarker = try await reload(coordinator, afterDamaging: Self.folderA) { overlay in
            try FileManager.default.removeItem(at: overlay.appendingPathComponent(Self.markerFileName))
        }
        XCTAssertEqual(withoutMarker.booleanFlags["prepared_overlay_rebuilt"], true, "missing marker")
        XCTAssertFalse(sentinelSurvived(Self.folderA), "missing marker")

        let unreadableMarker = try await reload(coordinator, afterDamaging: Self.folderA) { overlay in
            try Data("not json".utf8).write(to: overlay.appendingPathComponent(Self.markerFileName))
        }
        XCTAssertEqual(unreadableMarker.booleanFlags["prepared_overlay_rebuilt"], true, "unreadable marker")
        XCTAssertFalse(sentinelSurvived(Self.folderA), "unreadable marker")

        let withoutTokenizer = try await reload(coordinator, afterDamaging: Self.folderA) { overlay in
            try FileManager.default.removeItem(at: overlay.appendingPathComponent("tokenizer.json"))
        }
        XCTAssertEqual(withoutTokenizer.booleanFlags["prepared_overlay_rebuilt"], true, "missing tokenizer.json")
        XCTAssertFalse(sentinelSurvived(Self.folderA), "missing tokenizer.json")
        XCTAssertEqual(
            itemType(overlayDirectory(Self.folderA).appendingPathComponent("tokenizer.json")),
            .typeSymbolicLink,
            "the rebuild restored the prepared artifact"
        )
        XCTAssertEqual(probes.loader.calls.count, 4)
    }

    // MARK: - Trusted-checkpoint marker

    /// The checkpoint trust (source trust file and the marker's trust entry)
    /// is written only once a load has succeeded on those weights.
    func testTheTrustedCheckpointMarkerIsPersistedOnlyAfterASuccessfulLoad() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let weightsDigest = sha256Hex(Self.talkerWeights(for: Self.idA))

        probes.loader.enqueue(.init(outcome: .fail))
        let failure = await loadError(coordinator, id: Self.idA)
        XCTAssertNotNil(failure, "the scripted loader failure reaches the caller")
        XCTAssertFalse(fileExists(sourceTrustURL(Self.folderA)), "no trust after a failed load")
        XCTAssertNotNil(jsonObject(at: markerURL(Self.folderA)), "the rebuild itself wrote the base marker")
        XCTAssertNil(markerTrust(Self.folderA), "no trust entry after a failed load")

        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertEqual(modelDigest(inTrust: markerTrust(Self.folderA)), weightsDigest)
        XCTAssertEqual(modelDigest(inTrust: jsonObject(at: sourceTrustURL(Self.folderA))), weightsDigest)

        await coordinator.unloadModel()
        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertEqual(probes.loader.calls.map(\.trustedPreparedCheckpoint), [false, false, true])
    }

    /// Weights that changed behind a still-valid overlay lose their trust
    /// until a load succeeds on them, and a failed load records nothing.
    func testChangedWeightsBehindAValidOverlayAreNotTrustedUntilALoadSucceeds() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let originalDigest = sha256Hex(Self.talkerWeights(for: Self.idA))
        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        await coordinator.unloadModel()

        let changed = Data("replacement talker weights of another length".utf8)
        try changed.write(to: sourceDirectory(Self.folderA).appendingPathComponent("model.safetensors"))
        probes.loader.enqueue(.init(outcome: .fail))
        let failure = await loadError(coordinator, id: Self.idA)

        XCTAssertNotNil(failure)
        XCTAssertEqual(probes.loader.calls.last?.trustedPreparedCheckpoint, false)
        XCTAssertEqual(modelDigest(inTrust: markerTrust(Self.folderA)), originalDigest)
        XCTAssertEqual(modelDigest(inTrust: jsonObject(at: sourceTrustURL(Self.folderA))), originalDigest)

        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertEqual(probes.loader.calls.last?.trustedPreparedCheckpoint, false)
        XCTAssertEqual(modelDigest(inTrust: markerTrust(Self.folderA)), sha256Hex(changed))
    }

    /// Suspected defect (DW-03 seam finding). The same weight change as the
    /// test above, but the overlay is also invalid (a descriptor change or a
    /// cache sweep), so the coordinator rebuilds it. The rebuild path trusts a
    /// digest it has just recomputed rather than one a load succeeded on.
    func testChangedWeightsAreNotTrustedWhenTheOverlayIsRebuilt() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        _ = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        await coordinator.unloadModel()

        let changed = Data("replacement talker weights of another length".utf8)
        let changedDigest = sha256Hex(changed)
        try changed.write(to: sourceDirectory(Self.folderA).appendingPathComponent("model.safetensors"))
        try FileManager.default.removeItem(at: markerURL(Self.folderA))
        probes.loader.enqueue(.init(outcome: .fail))
        let failure = await loadError(coordinator, id: Self.idA)

        XCTAssertNotNil(failure)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
        // The rebuild path ran: without it this test would pin nothing about the rebuild.
        XCTAssertEqual(
            probes.diagnostics.details(of: "coordinator-load-after-prepare-local-cache").last?["rebuiltPreparedCache"],
            "true"
        )
        let loaderSawTrust = try XCTUnwrap(probes.loader.calls.last).trustedPreparedCheckpoint
        let sourceDigest = modelDigest(inTrust: jsonObject(at: sourceTrustURL(Self.folderA)))
        let markerDigest = modelDigest(inTrust: markerTrust(Self.folderA))
        let defect = "Known defect (DW-03): with the overlay invalid, readPersistedSourceQwenPreparedCheckpointTrust"
            + " re-hashes changed weights and rewrites .qvoice_qwen_checkpoint_trust.json to the new digest, and the"
            + " rebuild marks the checkpoint trusted (relaxed weight-key verification) before any load succeeded"
            + " on it; the trust survives the failed load. The valid-overlay path distrusts the same change."
        await MainActor.run {
            expectKnownDefect(defect) {
                XCTAssertFalse(loaderSawTrust, "changed weights reached the loader as trusted")
            }
            expectKnownDefect(defect) {
                XCTAssertNotEqual(sourceDigest, changedDigest, "the source trust file trusts weights no load succeeded on")
            }
            expectKnownDefect(defect) {
                XCTAssertNotEqual(markerDigest, changedDigest, "the overlay marker trusts weights no load succeeded on")
            }
        }
    }

    // MARK: - Failures

    /// A loader failure publishes nothing and releases MLX's buffer cache; a
    /// failed switch leaves no model rather than the previous one.
    func testALoaderFailurePublishesNothingAndClearsTheAllocatorCache() async throws {
        let descriptorA = try installModel(id: Self.idA, folder: Self.folderA)
        let descriptorB = try installModel(id: Self.idB, folder: Self.folderB)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptorA, descriptorB], probes: probes)

        probes.loader.enqueue(.init(outcome: .fail))
        let failure = await loadError(coordinator, id: Self.idA)
        let runtimeError = try XCTUnwrap(failure as? NativeRuntimeError, "got \(String(describing: failure))")
        XCTAssertEqual(runtimeError.stage, .upstreamModelLoad)
        XCTAssertTrue(runtimeError.underlyingDescription?.contains("FixtureLoaderFailure") == true)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
        let resident = await coordinator.loadedModel
        XCTAssertNil(resident)
        let identity = await coordinator.loadedModelRuntimeIdentity
        XCTAssertNil(identity)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"], "the failure's reset releases the buffer cache")
        let needsUnload = await coordinator.requiresUnloadAfterRuntimeFailure()
        XCTAssertFalse(needsUnload, "no model is loaded after a failed load")

        _ = try await coordinator.loadModel(id: Self.idB, capabilityProfile: .customOnly)
        await coordinator.markPrewarmed(identityKey: "fixture-warm-b")
        probes.loader.enqueue(.init(outcome: .fail))
        let switchFailure = await loadError(coordinator, id: Self.idA)

        XCTAssertNotNil(switchFailure as? NativeRuntimeError)
        let afterSwitch = await coordinator.currentLoadedModelID()
        XCTAssertNil(afterSwitch, "the switch released B before A's loader failed")
        let stillWarm = await coordinator.isPrewarmed(identityKey: "fixture-warm-b")
        XCTAssertFalse(stillWarm)
        XCTAssertEqual(
            probes.allocator.entries,
            ["clearCache", "clearCache", "clearCache"],
            "first failure, then the switch's release of B, then the second failure"
        )
        XCTAssertEqual(probes.beforeLoads.entries, ["none", "none", Self.idB])
        XCTAssertEqual(probes.loader.calls.map(\.modelID), [Self.idA, Self.idB, Self.idA])
    }

    /// Metadata that fails validation stops the load before the loader runs.
    func testAPrepareFailureNeverReachesTheLoader() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        try Data(#"{"model_type":"fixture_other"}"#.utf8)
            .write(to: sourceDirectory(Self.folderA).appendingPathComponent("config.json"))
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)

        let failure = await loadError(coordinator, id: Self.idA)

        let runtimeError = try XCTUnwrap(failure as? NativeRuntimeError, "got \(String(describing: failure))")
        XCTAssertEqual(runtimeError.stage, .preparedCacheRebuild)
        XCTAssertEqual(probes.loader.calls.count, 0)
        XCTAssertFalse(fileExists(overlayDirectory(Self.folderA)), "no overlay is prepared for invalid metadata")
        XCTAssertEqual(probes.allocator.entries, ["clearCache"])
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
    }

    // MARK: - Load epoch

    /// An unload while the load is suspended inside the loader vetoes its
    /// publication: the caller gets a raw `CancellationError`, nothing is
    /// resident and no trust is persisted. The veto does not wedge later loads.
    func testAnUnloadWhileTheLoaderIsSuspendedVetoesPublication() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let gate = SeamGate()
        let entered = expectation(description: "the loader is suspended")
        probes.loader.enqueue(.init(entered: entered, gate: gate))

        let load = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [entered], timeout: 10)
        await coordinator.unloadModel()
        await gate.open()
        let outcome = await load.value

        assertVetoed(outcome)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
        let resident = await coordinator.loadedModel
        XCTAssertNil(resident)
        XCTAssertEqual(probes.loader.calls.count, 1)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"], "only the unload released memory")
        XCTAssertFalse(fileExists(sourceTrustURL(Self.folderA)), "a vetoed load persists no trust")
        let needsUnload = await coordinator.requiresUnloadAfterRuntimeFailure()
        XCTAssertFalse(needsUnload)

        let next = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertTrue(next.didLoad)
        XCTAssertEqual(probes.loader.calls.count, 2)
        let republished = await coordinator.currentLoadedModelID()
        XCTAssertEqual(republished, Self.idA)
    }

    /// An unload that lands after publication but before the load returns
    /// (during the trust-marker diagnostic) vetoes the result as well. The
    /// loader did succeed, so the checkpoint trust is still persisted.
    func testAnUnloadAfterPublicationVetoesTheResult() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let gate = SeamGate()
        let reached = expectation(description: "the load is past publication")
        probes.diagnostics.hold(at: "coordinator-load-before-persist-trusted-marker", until: gate, reached: reached)

        let load = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [reached], timeout: 10)
        let published = await coordinator.currentLoadedModelID()
        XCTAssertEqual(published, Self.idA, "the model is published before the trust-marker step")
        await coordinator.unloadModel()
        await gate.open()
        let outcome = await load.value

        assertVetoed(outcome)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
        XCTAssertEqual(probes.loader.calls.count, 1)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"])
        XCTAssertEqual(
            modelDigest(inTrust: jsonObject(at: sourceTrustURL(Self.folderA))),
            sha256Hex(Self.talkerWeights(for: Self.idA))
        )
    }

    /// An unload before the loader runs also ends the load cancelled with
    /// nothing resident. The epoch is checked only after the loader returns,
    /// so the superseded load still pays for a full load (engine audit B-04).
    func testAnUnloadBeforeTheLoaderRunsVetoesPublicationButNotTheLoad() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let gate = SeamGate()
        let reached = expectation(description: "the load is about to call the loader")
        probes.diagnostics.hold(at: "coordinator-load-before-model-loader", until: gate, reached: reached)

        let load = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [reached], timeout: 10)
        XCTAssertEqual(probes.loader.calls.count, 0)
        await coordinator.unloadModel()
        await gate.open()
        let outcome = await load.value

        assertVetoed(outcome)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertNil(loadedID)
        XCTAssertEqual(probes.loader.calls.count, 1, "B-04: the epoch guards publication, not the loader call")
        XCTAssertEqual(probes.allocator.entries, ["clearCache"])
    }

    // MARK: - Prewarm identity keys

    /// Prewarm keys are tracked per identity, survive a resident reuse and are
    /// cleared by `clearPrewarmState`, by a publication and by an unload.
    func testPrewarmKeysFollowTheResidentModel() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)

        await coordinator.markPrewarmed(identityKey: "fixture-one")
        await coordinator.markPrewarmed(identityKey: "fixture-two")
        let one = await coordinator.isPrewarmed(identityKey: "fixture-one")
        let two = await coordinator.isPrewarmed(identityKey: "fixture-two")
        let other = await coordinator.isPrewarmed(identityKey: "fixture-other")
        XCTAssertTrue(one)
        XCTAssertTrue(two)
        XCTAssertFalse(other)
        await coordinator.clearPrewarmState()
        let clearedKeys = await coordinator.prewarmedIdentityKeys
        XCTAssertEqual(clearedKeys, [])

        await coordinator.markPrewarmed(identityKey: "fixture-before-load")
        let first = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        let beforeLoad = await coordinator.isPrewarmed(identityKey: "fixture-before-load")
        XCTAssertFalse(beforeLoad, "a publication starts with no prewarm state")

        await coordinator.markPrewarmed(identityKey: "fixture-warm-a")
        let again = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertFalse(again.didLoad)
        XCTAssertTrue(again.model === first.model)
        let afterReuse = await coordinator.isPrewarmed(identityKey: "fixture-warm-a")
        XCTAssertTrue(afterReuse, "the resident fast path keeps the prewarm state")
        XCTAssertEqual(probes.loader.calls.count, 1)
        XCTAssertEqual(probes.allocator.entries, [])

        await coordinator.unloadModel()
        let afterUnload = await coordinator.isPrewarmed(identityKey: "fixture-warm-a")
        XCTAssertFalse(afterUnload)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"])
    }

    /// A model switch releases the resident model and its prewarm state before
    /// the new loader runs; a key marked during the new load does not survive
    /// its publication.
    func testAModelSwitchReleasesTheResidentModelAndItsPrewarmStateFirst() async throws {
        let descriptorA = try installModel(id: Self.idA, folder: Self.folderA)
        let descriptorB = try installModel(id: Self.idB, folder: Self.folderB)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptorA, descriptorB], probes: probes)
        let first = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        await coordinator.markPrewarmed(identityKey: "fixture-warm-a")
        let gate = SeamGate()
        let entered = expectation(description: "B's loader is suspended")
        probes.loader.enqueue(.init(entered: entered, gate: gate))

        let load = startLoad(coordinator, id: Self.idB)
        await fulfillment(of: [entered], timeout: 10)
        let duringSwitch = await coordinator.currentLoadedModelID()
        XCTAssertNil(duringSwitch, "A is released before B's loader runs")
        let warmA = await coordinator.isPrewarmed(identityKey: "fixture-warm-a")
        XCTAssertFalse(warmA)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"])
        XCTAssertEqual(probes.beforeLoads.entries, ["none", Self.idA])
        await coordinator.markPrewarmed(identityKey: "fixture-marked-mid-load")
        await gate.open()
        let result = try requireLoaded(await load.value)

        XCTAssertTrue(result.didLoad)
        XCTAssertFalse(result.model === first.model)
        let resident = await coordinator.loadedModel
        XCTAssertTrue(resident === result.model)
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertEqual(loadedID, Self.idB)
        let midLoad = await coordinator.isPrewarmed(identityKey: "fixture-marked-mid-load")
        XCTAssertFalse(midLoad)
    }

    // MARK: - Interleavings at the loader's suspension point

    /// Two concurrent loads of one model are not coalesced: the second caller
    /// finds nothing published and runs the loader too. Both callers get
    /// `didLoad`; the later publication replaces the earlier one without a
    /// reset, and stays resident for the fast path. Production serializes
    /// model operations in `MLXTTSEngine`; this pins the coordinator alone.
    func testConcurrentLoadsOfOneModelBothRunTheLoaderAndTheLastStaysResident() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let firstGate = SeamGate()
        let secondGate = SeamGate()
        let firstEntered = expectation(description: "the first loader is suspended")
        let secondEntered = expectation(description: "the second loader is suspended")
        probes.loader.enqueue(
            .init(entered: firstEntered, gate: firstGate),
            .init(entered: secondEntered, gate: secondGate)
        )

        let first = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [firstEntered], timeout: 10)
        let second = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [secondEntered], timeout: 10)
        XCTAssertEqual(probes.loader.calls.map(\.modelID), [Self.idA, Self.idA])

        await firstGate.open()
        let firstResult = try requireLoaded(await first.value)
        let afterFirst = await coordinator.loadedModel
        XCTAssertTrue(afterFirst === firstResult.model)
        await secondGate.open()
        let secondResult = try requireLoaded(await second.value)

        XCTAssertTrue(firstResult.didLoad)
        XCTAssertTrue(secondResult.didLoad)
        XCTAssertFalse(firstResult.model === secondResult.model)
        let resident = await coordinator.loadedModel
        XCTAssertTrue(resident === secondResult.model, "the last publication stays resident")
        XCTAssertEqual(probes.allocator.entries, [], "the replaced model is dropped without a reset")

        let third = try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
        XCTAssertFalse(third.didLoad)
        XCTAssertTrue(third.model === secondResult.model)
        XCTAssertEqual(probes.loader.calls.count, 2)
    }

    /// Two concurrent loads of different models: neither sees a resident
    /// model to release, and whichever finishes last stays resident, even the
    /// one that started first.
    func testConcurrentLoadsOfTwoModelsLeaveTheLastFinisherResident() async throws {
        let descriptorA = try installModel(id: Self.idA, folder: Self.folderA)
        let descriptorB = try installModel(id: Self.idB, folder: Self.folderB)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptorA, descriptorB], probes: probes)
        let gateA = SeamGate()
        let gateB = SeamGate()
        let enteredA = expectation(description: "A's loader is suspended")
        let enteredB = expectation(description: "B's loader is suspended")
        probes.loader.enqueue(.init(entered: enteredA, gate: gateA), .init(entered: enteredB, gate: gateB))

        let loadA = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [enteredA], timeout: 10)
        let loadB = startLoad(coordinator, id: Self.idB)
        await fulfillment(of: [enteredB], timeout: 10)
        XCTAssertEqual(probes.beforeLoads.entries, ["none", "none"], "neither load saw a resident model")

        await gateB.open()
        let resultB = try requireLoaded(await loadB.value)
        let afterB = await coordinator.currentLoadedModelID()
        XCTAssertEqual(afterB, Self.idB)
        await gateA.open()
        let resultA = try requireLoaded(await loadA.value)

        XCTAssertTrue(resultA.didLoad)
        XCTAssertTrue(resultB.didLoad, "B's caller was told it loaded, though B is no longer resident")
        let afterA = await coordinator.currentLoadedModelID()
        XCTAssertEqual(afterA, Self.idA, "the load that started first finished last and replaced B")
        let resident = await coordinator.loadedModel
        XCTAssertTrue(resident === resultA.model)
        let identity = await coordinator.loadedModelRuntimeIdentity
        XCTAssertEqual(identity?.resolvedModelID, Self.idA)
        XCTAssertEqual(probes.allocator.entries, [], "B was replaced without a reset")
    }

    /// A load an unload superseded never replaces a newer load that
    /// published first, whatever order the two loaders return in.
    func testAStaleLoadFinishingAfterANewerOneNeverReplacesIt() async throws {
        let descriptor = try installModel(id: Self.idA, folder: Self.folderA)
        let probes = Probes()
        let coordinator = makeCoordinator([descriptor], probes: probes)
        let staleGate = SeamGate()
        let freshGate = SeamGate()
        let staleEntered = expectation(description: "the stale loader is suspended")
        let freshEntered = expectation(description: "the fresh loader is suspended")
        probes.loader.enqueue(
            .init(entered: staleEntered, gate: staleGate),
            .init(entered: freshEntered, gate: freshGate)
        )

        let stale = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [staleEntered], timeout: 10)
        await coordinator.unloadModel()
        let fresh = startLoad(coordinator, id: Self.idA)
        await fulfillment(of: [freshEntered], timeout: 10)
        await freshGate.open()
        let freshResult = try requireLoaded(await fresh.value)
        await staleGate.open()
        let staleOutcome = await stale.value

        assertVetoed(staleOutcome)
        XCTAssertTrue(freshResult.didLoad)
        let resident = await coordinator.loadedModel
        XCTAssertTrue(resident === freshResult.model, "the stale load never replaced the newer one")
        let loadedID = await coordinator.currentLoadedModelID()
        XCTAssertEqual(loadedID, Self.idA)
        XCTAssertEqual(probes.loader.calls.count, 2)
        XCTAssertEqual(probes.allocator.entries, ["clearCache"], "only the unload released memory")
    }

    // MARK: - Fixture

    private static let capabilities = Qwen3TTSModelCapabilities(
        modelSize: .pro1b7,
        familyType: .customVoice,
        supportsInstructionControl: true,
        supportsVoiceClone: false,
        supportsXVectorOnlyClone: false,
        requiresSpeakerEncoder: false,
        tokenizerProfile: Qwen3TTSTokenizerProfile(
            name: "qwen3",
            sampleRateHz: 24_000,
            frameRateHz: 12.5,
            decoderQuantizers: 16,
            encoderValidQuantizers: 8,
            encoderConfiguredQuantizers: 8,
            codebookSize: 2_048,
            semanticCodebookSize: 4_096
        ),
        generationDefaults: Qwen3TTSGenerationDefaultsProfile(
            checkpointMaxNewTokens: nil,
            wrapperFallbackMaxNewTokens: 2_048,
            appPolicyMaxNewTokens: 2_048,
            temperature: 0.9,
            topP: 1,
            topK: 50,
            doSample: true,
            repetitionPenalty: 1.05,
            source: .appPolicy
        ),
        artifactAvailability: .publicArtifact
    )

    private var modelsRoot: URL {
        sandbox.appendingPathComponent("models", isDirectory: true)
    }

    private var hubCache: URL {
        sandbox
            .appendingPathComponent("cache", isDirectory: true)
            .appendingPathComponent("native_mlx", isDirectory: true)
    }

    private func sourceDirectory(_ folder: String) -> URL {
        modelsRoot.appendingPathComponent(folder, isDirectory: true)
    }

    private func overlayDirectory(_ folder: String) -> URL {
        PreparedModelOverlay.directory(
            forSourceDirectory: sourceDirectory(folder),
            hubCacheDirectory: hubCache
        )
    }

    private func markerURL(_ folder: String) -> URL {
        overlayDirectory(folder).appendingPathComponent(Self.markerFileName)
    }

    private func sourceTrustURL(_ folder: String) -> URL {
        sourceDirectory(folder).appendingPathComponent(Self.sourceTrustFileName)
    }

    private func markerTrust(_ folder: String) -> [String: Any]? {
        jsonObject(at: markerURL(folder))?["qwenPreparedCheckpointTrust"] as? [String: Any]
    }

    private func dropSentinel(in folder: String) throws {
        try Data("sentinel".utf8)
            .write(to: overlayDirectory(folder).appendingPathComponent(Self.sentinelName))
    }

    private func sentinelSurvived(_ folder: String) -> Bool {
        fileExists(overlayDirectory(folder).appendingPathComponent(Self.sentinelName))
    }

    /// Installs a complete synthetic custom-voice folder: every critical
    /// component, a `tokenizer.json` (so preparation never generates one) and
    /// an integrity manifest. The weights are a few bytes no one evaluates.
    private func installModel(id: String, folder: String) throws -> ModelAssetDescriptor {
        let source = sourceDirectory(folder)
        try FileManager.default.createDirectory(
            at: source.appendingPathComponent("speech_tokenizer", isDirectory: true),
            withIntermediateDirectories: true
        )
        var files: [String: Data] = [:]
        for path in Qwen3TTSRuntimeProfile.criticalRequiredComponents {
            files[path] = Data("{}".utf8)
        }
        files["config.json"] = Data(#"{"model_type":"qwen3_tts"}"#.utf8)
        files["generation_config.json"] = Data(#"{"max_new_tokens":2048,"top_k":50}"#.utf8)
        files["merges.txt"] = Data("#version: fixture\n".utf8)
        files["model.safetensors"] = Self.talkerWeights(for: id)
        files["speech_tokenizer/model.safetensors"] = Self.speechTokenizerWeights
        files["tokenizer.json"] = Data(#"{"model":{"type":"BPE"}}"#.utf8)
        for (path, data) in files {
            try data.write(to: source.appendingPathComponent(path))
        }
        let manifest = ModelAssetIntegrityManifest(
            repo: Self.repository,
            revision: Self.revision,
            targetFolder: folder,
            createdAtUTC: "2026-10-19T00:00:00Z",
            files: files.sorted { $0.key < $1.key }.map { entry in
                ModelAssetIntegrityManifest.FileEntry(
                    path: entry.key,
                    size: Int64(entry.value.count),
                    sha256: sha256Hex(entry.value)
                )
            }
        )
        try JSONEncoder().encode(manifest)
            .write(to: source.appendingPathComponent(ModelAssetIntegrityManifest.filename))
        return descriptor(id: id, folder: folder, version: "fixture-v1")
    }

    private func descriptor(id: String, folder: String, version: String) -> ModelAssetDescriptor {
        let paths = Qwen3TTSRuntimeProfile.criticalRequiredComponents
        let model = ModelDescriptor(
            id: id,
            name: "Fixture \(id)",
            tier: "pro",
            folder: folder,
            mode: .custom,
            huggingFaceRepo: Self.repository,
            huggingFaceRevision: Self.revision,
            artifactVersion: "fixture-artifact-1",
            iosDownloadEligible: false,
            estimatedDownloadBytes: nil,
            outputSubfolder: "CustomVoice",
            requiredRelativePaths: paths,
            qwen3Capabilities: Self.capabilities
        )
        return ModelAssetDescriptor(
            model: model,
            version: version,
            artifacts: paths.map { ModelAssetArtifact(relativePath: $0, scope: .modelSpecific) }
        )
    }

    private func makeCoordinator(
        _ descriptors: [ModelAssetDescriptor],
        probes: Probes
    ) -> MLXModelLoadCoordinator {
        let loader = probes.loader
        let allocator = probes.allocator
        let beforeLoads = probes.beforeLoads
        let diagnostics = probes.diagnostics
        return MLXModelLoadCoordinator(
            modelAssetStore: LocalModelAssetStore(rootDirectory: modelsRoot, descriptors: descriptors),
            hubCacheDirectory: hubCache,
            modelLoader: { descriptor, metadata, capabilityProfile in
                try await loader.load(
                    descriptor: descriptor,
                    metadata: metadata,
                    capabilityProfile: capabilityProfile
                )
            },
            beforeModelLoad: { previousModelID in
                beforeLoads.append(previousModelID ?? "none")
            },
            diagnosticEventSink: { action, details in
                await diagnostics.record(action: action, details: details)
            },
            allocatorControl: NativeMLXAllocatorControl(
                applyPolicy: { _ in allocator.append("applyPolicy") },
                clearCache: { allocator.append("clearCache") }
            )
        )
    }

    /// Unloads, damages the overlay, drops a sentinel into it and reloads.
    private func reload(
        _ coordinator: MLXModelLoadCoordinator,
        afterDamaging folder: String,
        _ damage: (URL) throws -> Void
    ) async throws -> NativeModelLoadResult {
        await coordinator.unloadModel()
        try damage(overlayDirectory(folder))
        try dropSentinel(in: folder)
        return try await coordinator.loadModel(id: Self.idA, capabilityProfile: .customOnly)
    }
}

// MARK: - Seams

/// The probes one coordinator reports through.
private struct Probes {
    let loader = FakeModelLoader()
    let allocator = SeamCallLog()
    let beforeLoads = SeamCallLog()
    let diagnostics = DiagnosticProbe()
}

private final class SeamCallLog: Sendable {
    private let storage = OSAllocatedUnfairLock<[String]>(initialState: [])

    var entries: [String] { storage.withLock { $0 } }

    func append(_ entry: String) {
        storage.withLock { $0.append(entry) }
    }
}

private actor SeamGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func open() {
        isOpen = true
        let pending = waiters
        waiters.removeAll()
        pending.forEach { $0.resume() }
    }
}

/// The injected model loader. Each call records what the coordinator handed
/// it, then follows the next scripted step (succeed by default): it can
/// announce its entry, hold at a gate, and succeed or fail. A success returns
/// an unloaded runtime actor, so no MLX work ever runs.
private final class FakeModelLoader: Sendable {
    struct FixtureLoaderFailure: Error {}

    enum Outcome: Sendable {
        case succeed
        case fail
    }

    struct Step: Sendable {
        var outcome: Outcome = .succeed
        var entered: XCTestExpectation?
        var gate: SeamGate?
    }

    struct Call: Sendable {
        let modelID: String
        let capabilityProfile: NativeLoadCapabilityProfile
        let trustedPreparedCheckpoint: Bool
        let preparedDirectory: URL
        let sourceDirectory: URL?
    }

    private struct State: Sendable {
        var calls: [Call] = []
        var steps: [Step] = []
    }

    private let state = OSAllocatedUnfairLock(initialState: State())

    var calls: [Call] { state.withLock { $0.calls } }

    func enqueue(_ steps: Step...) {
        state.withLock { $0.steps.append(contentsOf: steps) }
    }

    func load(
        descriptor: ModelAssetDescriptor,
        metadata: MLXModelLoadCoordinator.PreparedModelMetadata,
        capabilityProfile: NativeLoadCapabilityProfile
    ) async throws -> UnsafeSpeechGenerationModel {
        let call = Call(
            modelID: descriptor.id,
            capabilityProfile: capabilityProfile,
            trustedPreparedCheckpoint: metadata.trustedPreparedCheckpoint,
            preparedDirectory: metadata.preparedDirectory,
            sourceDirectory: metadata.sourceDirectory
        )
        let step = state.withLock { locked -> Step in
            locked.calls.append(call)
            return locked.steps.isEmpty ? Step() : locked.steps.removeFirst()
        }
        step.entered?.fulfill()
        if let gate = step.gate {
            await gate.wait()
        }
        switch step.outcome {
        case .succeed:
            return makeFixtureModel(id: descriptor.id)
        case .fail:
            throw FixtureLoaderFailure()
        }
    }
}

/// The diagnostic event sink: records every event and can hold the load at
/// one named action until the test opens a gate.
private final class DiagnosticProbe: Sendable {
    struct Event: Sendable {
        let action: String
        let details: [String: String]
    }

    private struct Hold: Sendable {
        let action: String
        let gate: SeamGate
        let reached: XCTestExpectation
    }

    private struct State: Sendable {
        var events: [Event] = []
        var hold: Hold?
    }

    private let state = OSAllocatedUnfairLock(initialState: State())

    func hold(at action: String, until gate: SeamGate, reached: XCTestExpectation) {
        let hold = Hold(action: action, gate: gate, reached: reached)
        state.withLock { $0.hold = hold }
    }

    func details(of action: String) -> [[String: String]] {
        state.withLock { locked in
            locked.events.filter { $0.action == action }.map(\.details)
        }
    }

    func record(action: String, details: [String: String]) async {
        let event = Event(action: action, details: details)
        let matched = state.withLock { locked -> Hold? in
            locked.events.append(event)
            guard let pending = locked.hold, pending.action == event.action else { return nil }
            locked.hold = nil
            return pending
        }
        guard let matched else { return }
        matched.reached.fulfill()
        await matched.gate.wait()
    }
}

private enum LoadOutcome: Sendable {
    case loaded(NativeModelLoadResult)
    case failed(any Error)
}

/// A non-throwing task, so CI's pinned compiler accepts it (a throwing task
/// that returns a value fails its region-isolation check).
private func startLoad(_ coordinator: MLXModelLoadCoordinator, id: String) -> Task<LoadOutcome, Never> {
    Task { () -> LoadOutcome in
        do {
            let result = try await coordinator.loadModel(id: id, capabilityProfile: .customOnly)
            return .loaded(result)
        } catch {
            return .failed(error)
        }
    }
}

private func loadError(_ coordinator: MLXModelLoadCoordinator, id: String) async -> (any Error)? {
    do {
        _ = try await coordinator.loadModel(id: id, capabilityProfile: .customOnly)
        return nil
    } catch {
        return error
    }
}

private func requireLoaded(
    _ outcome: LoadOutcome,
    file: StaticString = #filePath,
    line: UInt = #line
) throws -> NativeModelLoadResult {
    switch outcome {
    case .loaded(let result):
        return result
    case .failed(let error):
        XCTFail("expected a published model, got \(error)", file: file, line: line)
        throw error
    }
}

/// The epoch veto throws a raw `CancellationError`, never a wrapped runtime
/// error, and returns no model.
private func assertVetoed(_ outcome: LoadOutcome, file: StaticString = #filePath, line: UInt = #line) {
    switch outcome {
    case .loaded:
        XCTFail("a superseded load returned a model", file: file, line: line)
    case .failed(let error):
        XCTAssertTrue(error is CancellationError, "expected CancellationError, got \(error)", file: file, line: line)
    }
}

/// Strict: once the defect is fixed the expected failure stops occurring and
/// the test fails, so the expectation is removed with the fix.
private func expectKnownDefect(_ reason: String, _ assertions: () -> Void) {
    XCTExpectFailure(reason, options: XCTExpectedFailure.Options(), failingBlock: assertions)
}

private func makeFixtureModel(id: String) -> UnsafeSpeechGenerationModel {
    let facts = VocelloQwen3LoadedModelFacts(
        identity: VocelloQwen3ModelIdentity(
            modelID: id,
            repositoryID: "fixture/repository",
            revision: "fixture",
            artifactVersion: "fixture"
        ),
        sampleRate: 24_000,
        capabilities: VocelloQwen3CapabilitySet([VocelloQwen3Capability]()),
        loadDiagnostics: VocelloQwen3RuntimeDiagnosticsSnapshot(
            timingsMilliseconds: ["fixture_loader_ms": 7],
            booleanFlags: ["fixture_loader_flag": true]
        )
    )
    return UnsafeSpeechGenerationModel(engine: VocelloQwen3Engine(), facts: facts)
}

private func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { unsafe String(format: "%02x", $0) }.joined()
}

private func jsonObject(at url: URL) -> [String: Any]? {
    guard let data = try? Data(contentsOf: url) else { return nil }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
}

private func modelDigest(inTrust trust: [String: Any]?) -> String? {
    (trust?["modelArtifact"] as? [String: Any])?["contentDigest"] as? String
}

private func fileExists(_ url: URL) -> Bool {
    FileManager.default.fileExists(atPath: url.path)
}

/// The item's own type; symlinks are not followed.
private func itemType(_ url: URL) -> FileAttributeType? {
    (try? FileManager.default.attributesOfItem(atPath: url.path))?[.type] as? FileAttributeType
}
