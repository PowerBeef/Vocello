import Foundation
import QwenVoiceCore
import XCTest

private actor CriticalMemoryReliefProbe {
    enum Action: Equatable {
        case cancellation(GenerationCancellationReason)
        case reliefStarted
        case reliefCompleted
        case ownershipReleased
    }

    private var actions: [Action] = []
    private var cancellationStartedWaiters: [CheckedContinuation<Void, Never>] = []
    private var cancellationReleaseWaiters: [CheckedContinuation<Void, Never>] = []
    private var reliefStartedWaiters: [CheckedContinuation<Void, Never>] = []
    private var reliefReleaseWaiters: [CheckedContinuation<Void, Never>] = []
    private var cancellationReleased = false
    private var reliefReleased = false

    func recordCancellation(_ reason: GenerationCancellationReason) {
        actions.append(.cancellation(reason))
        let waiters = cancellationStartedWaiters
        cancellationStartedWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    func waitForCancellationStart() async {
        if actions.contains(where: {
            if case .cancellation = $0 { return true }
            return false
        }) {
            return
        }

        await withCheckedContinuation { continuation in
            cancellationStartedWaiters.append(continuation)
        }
    }

    func waitForCancellationRelease() async {
        guard !cancellationReleased else { return }
        await withCheckedContinuation { continuation in
            cancellationReleaseWaiters.append(continuation)
        }
    }

    func releaseCancellation() {
        cancellationReleased = true
        let waiters = cancellationReleaseWaiters
        cancellationReleaseWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    func recordReliefAndWaitForRelease() async {
        actions.append(.reliefStarted)
        let waiters = reliefStartedWaiters
        reliefStartedWaiters.removeAll()
        waiters.forEach { $0.resume() }

        guard !reliefReleased else {
            actions.append(.reliefCompleted)
            return
        }
        await withCheckedContinuation { continuation in
            reliefReleaseWaiters.append(continuation)
        }
        actions.append(.reliefCompleted)
    }

    func waitForReliefStart() async {
        if actions.contains(.reliefStarted) {
            return
        }
        await withCheckedContinuation { continuation in
            reliefStartedWaiters.append(continuation)
        }
    }

    func releaseRelief() {
        reliefReleased = true
        let waiters = reliefReleaseWaiters
        reliefReleaseWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    func recordOwnershipReleased() {
        actions.append(.ownershipReleased)
    }

    func snapshot() -> [Action] {
        actions
    }
}

private struct CriticalMemoryReliefTestError: Error {}

/// Pure iOS policy tests. This bundle has no application host, performs no
/// network requests, loads no model, and is never routed through Simulator.
final class VocelloiOSLogicTests: XCTestCase {
    private let immutableRevision = String(repeating: "a", count: 40)
    private let digest = String(repeating: "b", count: 64)

    func testCatalogValidationAcceptsPinnedHTTPSArtifact() throws {
        let configuration = IOSModelDeliveryConfiguration(
            catalogURL: try XCTUnwrap(URL(string: "bundle://vocello/ios/catalog/v1/models.json")),
            allowedHosts: ["huggingface.co"],
            backgroundSessionIdentifier: "com.patricedery.vocello.logic-tests"
        )
        let entry = IOSModelCatalogEntry(
            modelID: "model-speed",
            artifactVersion: "v1",
            totalBytes: 42,
            baseURL: try XCTUnwrap(URL(string: "https://huggingface.co/example/model/resolve/\(immutableRevision)/")),
            files: [
                IOSModelCatalogFile(
                    relativePath: "weights/model.safetensors",
                    sizeBytes: 42,
                    sha256: digest,
                    url: nil
                ),
            ]
        )

        XCTAssertNoThrow(try IOSModelDeliverySupport.validate(entry: entry, configuration: configuration))
        XCTAssertEqual(
            try IOSModelDeliverySupport.downloadURL(
                for: entry.files[0],
                entry: entry,
                configuration: configuration
            ).scheme,
            "https"
        )
    }

    func testCatalogValidationRejectsMutableOrUnsafeArtifactRoute() throws {
        let configuration = IOSModelDeliveryConfiguration(
            catalogURL: try XCTUnwrap(URL(string: "bundle://vocello/ios/catalog/v1/models.json")),
            allowedHosts: ["huggingface.co"],
            backgroundSessionIdentifier: "com.patricedery.vocello.logic-tests"
        )
        let entry = IOSModelCatalogEntry(
            modelID: "model-speed",
            artifactVersion: "v1",
            totalBytes: 42,
            baseURL: try XCTUnwrap(URL(string: "http://huggingface.co/example/model/resolve/main/")),
            files: [
                IOSModelCatalogFile(
                    relativePath: "weights/model.safetensors",
                    sizeBytes: 42,
                    sha256: digest,
                    url: nil
                ),
            ]
        )

        XCTAssertThrowsError(try IOSModelDeliverySupport.validate(entry: entry, configuration: configuration))
    }

    func testLedgerRoundTripPreservesTerminalAndByteState() throws {
        let request = IOSModelDownloadLedger.Request(
            logicalRequestID: "request-a",
            modelID: "model-speed",
            artifactVersion: "v1",
            repo: "example/model",
            revision: immutableRevision,
            targetFolder: "model-speed",
            expectedFiles: ["weights/model.safetensors"],
            verifiedFiles: [
                IOSModelDownloadLedger.VerifiedFile(
                    relativePath: "weights/model.safetensors",
                    expectedSize: 42,
                    sha256: digest
                ),
            ],
            retryCount: 1,
            receivedBytes: 42,
            totalBytes: 42,
            status: .installed
        )
        let ledger = try IOSModelDownloadLedger(requests: [request]).validated()
        let decoded = try JSONDecoder().decode(
            IOSModelDownloadLedger.self,
            from: JSONEncoder().encode(ledger)
        )

        XCTAssertEqual(try decoded.validated(), ledger)
        XCTAssertEqual(decoded.requests.first?.status, .installed)
    }

    func testMemoryPolicyClassifiesHeadroomAndTrimDeterministically() {
        let policy = IOSMemoryBudgetPolicy.iPhoneShippingDefault
        let mebibyte = UInt64(1_048_576)
        let healthy = snapshot(headroom: 900 * mebibyte, footprint: 2_000 * mebibyte)
        let guarded = snapshot(headroom: 500 * mebibyte, footprint: 2_000 * mebibyte)
        let critical = snapshot(headroom: 300 * mebibyte, footprint: 2_000 * mebibyte)

        XCTAssertEqual(policy.band(for: healthy), .healthy)
        XCTAssertEqual(policy.band(for: guarded), .guarded)
        XCTAssertEqual(policy.band(for: critical), .critical)
        XCTAssertEqual(policy.trimLevelForPressureEvent(snapshot: guarded, isBackgroundTransition: false), .hardTrim)
        XCTAssertEqual(policy.trimLevelForPressureEvent(snapshot: healthy, isBackgroundTransition: true), .fullUnload)
    }

    func testCancellationReasonIsTypedAndRoundTrips() throws {
        let summary = GenerationCancellationSummary(
            generationID: UUID(uuidString: "00000000-0000-0000-0000-000000000001"),
            reason: .memoryPressure
        )
        let decoded = try JSONDecoder().decode(
            GenerationCancellationSummary.self,
            from: JSONEncoder().encode(summary)
        )

        XCTAssertEqual(decoded, summary)
        XCTAssertEqual(decoded.reason, .memoryPressure)
    }

    @MainActor
    func testCriticalPressureRequestsImmediateActiveCancellation() {
        let coordinator = RuntimeReleaseCoordinator()

        XCTAssertEqual(
            coordinator.requestCacheRelief(
                reason: "memory_warning",
                severity: .critical,
                hasActiveGeneration: true
            ),
            .execute(reason: "memory_warning", cancelActiveGeneration: true)
        )
        XCTAssertNil(coordinator.pendingCacheReliefReason)
    }

    @MainActor
    func testWarningPressureDefersUntilGenerationTerminates() {
        let coordinator = RuntimeReleaseCoordinator()

        XCTAssertEqual(
            coordinator.requestCacheRelief(
                reason: "memory_warning",
                severity: .warning,
                hasActiveGeneration: true
            ),
            .deferred(reason: "memory_warning")
        )
        XCTAssertEqual(
            coordinator.executeDeferredCacheReliefIfReady(hasActiveGeneration: true),
            .none
        )
        XCTAssertEqual(
            coordinator.executeDeferredCacheReliefIfReady(hasActiveGeneration: false),
            .execute(reason: "memory_warning", cancelActiveGeneration: false)
        )
        XCTAssertNil(coordinator.pendingCacheReliefReason)
        XCTAssertEqual(
            coordinator.executeDeferredCacheReliefIfReady(hasActiveGeneration: false),
            .none
        )
    }

    @MainActor
    func testCriticalMemoryReliefWaitsForCancellationBarrierBeforeUnload() async {
        let probe = CriticalMemoryReliefProbe()
        var ownershipHeld = true
        let reliefTask = Task { @MainActor in
            await CriticalMemoryReliefExecutor.execute(
                cancel: { reason in
                    await probe.recordCancellation(reason)
                    await probe.waitForCancellationRelease()
                },
                applyRelief: {
                    await probe.recordReliefAndWaitForRelease()
                },
                releaseOwnership: {
                    ownershipHeld = false
                    await probe.recordOwnershipReleased()
                }
            )
        }

        await probe.waitForCancellationStart()
        let actionsBeforeRelease = await probe.snapshot()
        XCTAssertEqual(actionsBeforeRelease, [.cancellation(.memoryPressure)])

        await probe.releaseCancellation()
        await probe.waitForReliefStart()
        let actionsDuringRelief = await probe.snapshot()
        XCTAssertEqual(
            actionsDuringRelief,
            [.cancellation(.memoryPressure), .reliefStarted]
        )
        XCTAssertTrue(ownershipHeld)

        await probe.releaseRelief()
        let outcome = await reliefTask.value
        XCTAssertEqual(outcome, .completed)
        XCTAssertFalse(ownershipHeld)
        let finalActions = await probe.snapshot()
        XCTAssertEqual(
            finalActions,
            [
                .cancellation(.memoryPressure),
                .reliefStarted,
                .reliefCompleted,
                .ownershipReleased,
            ]
        )
    }

    @MainActor
    func testCriticalMemoryReliefFailureNeverAppliesUnload() async {
        let probe = CriticalMemoryReliefProbe()
        var ownershipHeld = true

        let outcome = await CriticalMemoryReliefExecutor.execute(
            cancel: { reason in
                await probe.recordCancellation(reason)
                throw CriticalMemoryReliefTestError()
            },
            applyRelief: {
                await probe.recordReliefAndWaitForRelease()
            },
            releaseOwnership: {
                ownershipHeld = false
                await probe.recordOwnershipReleased()
            }
        )

        XCTAssertEqual(outcome, .cancellationFailed)
        XCTAssertTrue(ownershipHeld)
        let actions = await probe.snapshot()
        XCTAssertEqual(actions, [.cancellation(.memoryPressure)])
    }

    func testAppSupportOverrideRequiresExplicitDebugGateAndConfinedPath() {
        let override = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-ios-logic", isDirectory: true)
            .standardizedFileURL

        XCTAssertNotEqual(
            AppPaths.resolvedAppSupportDir(environment: [
                AppPaths.appSupportOverrideEnvironmentKey: override.path,
            ]),
            override
        )
        XCTAssertNotEqual(
            AppPaths.resolvedAppSupportDir(environment: [
                "QWENVOICE_DEBUG": "1",
                AppPaths.appSupportOverrideEnvironmentKey: "relative/path",
            ]),
            URL(fileURLWithPath: "relative/path", isDirectory: true).standardizedFileURL
        )
        let fallback = AppPaths.resolvedAppSupportDir(environment: ["QWENVOICE_DEBUG": "1"])
        for unsafeValue in ["../escape", ".", "..", "nested/path", "nested\\path"] {
            XCTAssertEqual(
                AppPaths.resolvedAppSupportDir(environment: [
                    "QWENVOICE_DEBUG": "1",
                    AppPaths.appSupportOverrideEnvironmentKey: unsafeValue,
                ]),
                fallback
            )
        }
        XCTAssertEqual(
            AppPaths.resolvedAppSupportDir(environment: [
                "QWENVOICE_DEBUG": "1",
                AppPaths.appSupportOverrideEnvironmentKey: "model-download-acceptance",
            ]),
            AppPaths.managedAppSupportDir
                .appendingPathComponent("model-download-acceptance", isDirectory: true)
                .standardizedFileURL
        )
        XCTAssertEqual(
            AppPaths.resolvedAppSupportDir(environment: [
                "QWENVOICE_DEBUG": "1",
                AppPaths.appSupportOverrideEnvironmentKey: override.path,
            ]),
            override
        )
    }

    func testStorageProtectionPolicyCoversEveryPersistentIOSDataClass() {
        XCTAssertEqual(
            IOSStorageProtectionPolicy.protectionClass,
            .completeUntilFirstUserAuthentication
        )
        XCTAssertEqual(
            Set(IOSStorageProtectionPolicy.entries.map(\.id)),
            Set([
                "application-support-root",
                "models",
                "downloads",
                "cache",
                "diagnostics",
                "outputs",
                "voices",
                "voice-candidates",
                "voice-transactions",
                "voice-transactions-quarantine",
                "history-outbox",
                "history",
            ])
        )

        let byID = Dictionary(uniqueKeysWithValues: IOSStorageProtectionPolicy.entries.map {
            ($0.id, $0)
        })
        for id in ["models", "downloads", "cache", "diagnostics", "voice-candidates", "voice-transactions"] {
            XCTAssertEqual(byID[id]?.backup, .excluded)
            XCTAssertEqual(byID[id]?.recursive, true)
        }
        for id in ["outputs", "voices", "voice-transactions-quarantine", "history-outbox", "history"] {
            XCTAssertEqual(byID[id]?.backup, .included)
        }
        XCTAssertEqual(byID["voice-transactions-quarantine"]?.recursive, true)
        XCTAssertEqual(byID["voice-transactions-quarantine"]?.isDirectory, true)
        XCTAssertEqual(byID["history"]?.pathPrefix, "history.sqlite")
    }

    /// IOS-06: one file that cannot take the governed attributes is counted and left for the
    /// next launch; it no longer fails startup.
    func testStorageProtectionDescendantFailureIsCountedNotFatal() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "vocello-storage-policy-descendant-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let outputs = root.appendingPathComponent("outputs", isDirectory: true)
        try FileManager.default.createDirectory(at: outputs, withIntermediateDirectories: true)
        try Data("take".utf8).write(to: outputs.appendingPathComponent("take.wav"))
        try Data("take".utf8).write(to: outputs.appendingPathComponent("unwritable.wav"))

        let report = try IOSStorageProtectionPolicy.apply(
            at: root,
            fileManager: StorageProtectionFaultFileManager(failingName: "unwritable.wav")
        )

        XCTAssertEqual(report.descendantFailureCount, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("voices").path))
    }

    /// A governed directory that cannot be protected still fails the pass, which the app shows
    /// with Retry.
    func testStorageProtectionGovernedDirectoryFailureStillThrows() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "vocello-storage-policy-governed-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? FileManager.default.removeItem(at: root) }

        XCTAssertThrowsError(
            try IOSStorageProtectionPolicy.apply(
                at: root,
                fileManager: StorageProtectionFaultFileManager(failingName: "voices")
            )
        )
    }

    /// PA-21 review: a descendant model file that was made writable for its metadata update
    /// and could not be made read-only again fails the pass instead of being counted, so a
    /// digest-verified component is never left writable while startup continues.
    func testStorageProtectionModeRestoreFailureOnADescendantIsFatal() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "vocello-storage-policy-restore-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let models = root.appendingPathComponent("models", isDirectory: true)
        try FileManager.default.createDirectory(at: models, withIntermediateDirectories: true)
        let component = models.appendingPathComponent("model.safetensors", isDirectory: false)
        try Data("immutable-model".utf8).write(to: component)
        try FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: 0o444)],
            ofItemAtPath: component.path
        )
        XCTAssertThrowsError(
            try IOSStorageProtectionPolicy.apply(
                at: root,
                fileManager: StorageProtectionModeRestoreFaultFileManager()
            )
        ) { error in
            XCTAssertTrue(
                error is IOSStorageProtectionPolicy.ModeRestoreFailure,
                "a failed restore is not a countable descendant failure"
            )
        }
        let mode = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: component.path)[.posixPermissions]
                as? NSNumber
        ).intValue
        XCTAssertEqual(mode & 0o777, 0o644, "the widening ran; only the restore failed")
    }

    func testStorageProtectionMetadataUpdateRestoresImmutableModelFile() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "vocello-storage-policy-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let model = root.appendingPathComponent("model.safetensors", isDirectory: false)
        try Data("immutable-model".utf8).write(to: model)
        let installedModel = root.appendingPathComponent("installed-model.safetensors", isDirectory: false)
        try FileManager.default.linkItem(at: model, to: installedModel)
        try FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: 0o444)],
            ofItemAtPath: model.path
        )

        var modeDuringMetadataUpdate: Int?
        try IOSStorageProtectionPolicy.withMetadataWriteAccess(at: model) {
            modeDuringMetadataUpdate = try XCTUnwrap(
                FileManager.default.attributesOfItem(atPath: model.path)[.posixPermissions]
                    as? NSNumber
            ).intValue
        }

        XCTAssertEqual(modeDuringMetadataUpdate.map { $0 & 0o777 }, 0o644)
        let restored = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: model.path)[.posixPermissions]
                as? NSNumber
        ).intValue
        XCTAssertEqual(restored & 0o777, 0o444)
        let linkedMode = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: installedModel.path)[.posixPermissions]
                as? NSNumber
        ).intValue
        XCTAssertEqual(linkedMode & 0o777, 0o444)
    }

    func testStorageProtectionMetadataFailureStillRestoresImmutableModelFile() throws {
        struct ExpectedFailure: Error {}

        let root = FileManager.default.temporaryDirectory.appendingPathComponent(
            "vocello-storage-policy-failure-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let model = root.appendingPathComponent("model.safetensors", isDirectory: false)
        try Data("immutable-model".utf8).write(to: model)
        try FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: 0o444)],
            ofItemAtPath: model.path
        )

        XCTAssertThrowsError(
            try IOSStorageProtectionPolicy.withMetadataWriteAccess(at: model) {
                throw ExpectedFailure()
            }
        )
        let restored = try XCTUnwrap(
            FileManager.default.attributesOfItem(atPath: model.path)[.posixPermissions]
                as? NSNumber
        ).intValue
        XCTAssertEqual(restored & 0o777, 0o444)
    }

    func testModelDeliveryBackgroundSessionSeparatesManagedDebugRoot() {
        let bundleIdentifier = "com.patricedery.vocello"
        let canonical = IOSModelDeliveryConfiguration.backgroundSessionIdentifier(
            bundleIdentifier: bundleIdentifier,
            environment: [:]
        )
        let isolated = IOSModelDeliveryConfiguration.backgroundSessionIdentifier(
            bundleIdentifier: bundleIdentifier,
            environment: [
                "QWENVOICE_DEBUG": "1",
                AppPaths.appSupportOverrideEnvironmentKey: "model-download-acceptance",
            ]
        )

        XCTAssertEqual(
            canonical,
            "com.patricedery.vocello.model-delivery.com.patricedery.vocello"
        )
        XCTAssertEqual(
            isolated,
            "\(canonical).isolated.8c79ad70e4699136f06e8843"
        )
        XCTAssertFalse(isolated.contains("model-download-acceptance"))
    }

    func testModelDeliveryBackgroundSessionRejectsUnconfinedNamespaces() {
        let bundleIdentifier = "com.patricedery.vocello"
        let canonical = IOSModelDeliveryConfiguration.backgroundSessionIdentifier(
            bundleIdentifier: bundleIdentifier,
            environment: [:]
        )
        let absolute = FileManager.default.temporaryDirectory
            .appendingPathComponent("private-model-delivery", isDirectory: true)
            .path
        let rejectedOverrides = [
            "model-download-acceptance", // Missing the debug master gate.
            absolute,
            "../escape",
            "nested/path",
            "nested\\path",
            ".",
            "..",
        ]

        for override in rejectedOverrides {
            var environment = [
                "QWENVOICE_DEBUG": "1",
                AppPaths.appSupportOverrideEnvironmentKey: override,
            ]
            if override == "model-download-acceptance" {
                environment.removeValue(forKey: "QWENVOICE_DEBUG")
            }
            XCTAssertEqual(
                IOSModelDeliveryConfiguration.backgroundSessionIdentifier(
                    bundleIdentifier: bundleIdentifier,
                    environment: environment
                ),
                canonical,
                "Rejected override created a background-session namespace: \(override)"
            )
        }
    }

    @MainActor
    func testBackgroundEventHandlerStoreSeparatesCanonicalAndIsolatedSessions() {
        let canonical = "com.patricedery.vocello.model-delivery.com.patricedery.vocello"
        let isolated = "\(canonical).isolated.8c79ad70e4699136f06e8843"
        let canonicalStore = IOSModelDeliveryBackgroundEventHandlerStore()
        var canonicalCompletions = 0
        var isolatedCompletions = 0

        XCTAssertTrue(
            canonicalStore.store(
                { canonicalCompletions += 1 },
                forDeliveredSessionIdentifier: canonical,
                ownedSessionIdentifier: canonical
            )
        )
        XCTAssertFalse(
            canonicalStore.store(
                { isolatedCompletions += 1 },
                forDeliveredSessionIdentifier: isolated,
                ownedSessionIdentifier: canonical
            )
        )

        XCTAssertEqual(canonicalStore.completeOwnedSession(canonical), 1)
        XCTAssertEqual(canonicalCompletions, 1)
        XCTAssertEqual(isolatedCompletions, 0)
        XCTAssertEqual(canonicalStore.completeOwnedSession(isolated), 0)

        let isolatedStore = IOSModelDeliveryBackgroundEventHandlerStore()
        XCTAssertFalse(
            isolatedStore.store(
                { canonicalCompletions += 1 },
                forDeliveredSessionIdentifier: canonical,
                ownedSessionIdentifier: isolated
            )
        )
        XCTAssertTrue(
            isolatedStore.store(
                { isolatedCompletions += 1 },
                forDeliveredSessionIdentifier: isolated,
                ownedSessionIdentifier: isolated
            )
        )
        XCTAssertEqual(isolatedStore.completeOwnedSession(isolated), 1)
        XCTAssertEqual(canonicalCompletions, 1)
        XCTAssertEqual(isolatedCompletions, 1)
    }

    @MainActor
    func testBackgroundEventHandlerStoreCompletesOwnedNoWorkWithoutConsumingForeignHandler() {
        let owned = "com.patricedery.vocello.model-delivery.owned"
        let foreign = "com.patricedery.vocello.model-delivery.foreign"
        let store = IOSModelDeliveryBackgroundEventHandlerStore()
        var ownedCompletions = 0
        var foreignCompletions = 0

        XCTAssertFalse(
            store.store(
                { foreignCompletions += 1 },
                forDeliveredSessionIdentifier: foreign,
                ownedSessionIdentifier: owned
            )
        )
        XCTAssertTrue(
            store.store(
                { ownedCompletions += 1 },
                forDeliveredSessionIdentifier: owned,
                ownedSessionIdentifier: owned
            )
        )

        XCTAssertEqual(store.completeOwnedSession(owned), 1)
        XCTAssertEqual(store.completeOwnedSession(owned), 0)
        XCTAssertEqual(store.completeOwnedSession(foreign), 0)
        XCTAssertEqual(ownedCompletions, 1)
        XCTAssertEqual(foreignCompletions, 0)
    }

    func testFailureDiagnosticsRecordTypedSummaryWithoutPrivateRoutes() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(directory: root)
        let stagedPath = "/private/var/mobile/fixture/Tell Mara the vault.part"
        store.recordFailure(
            classification: "network/failure",
            error: NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut, userInfo: [
                NSLocalizedDescriptionKey: "request https://example.invalid/private failed in \(stagedPath)",
                NSURLErrorFailingURLErrorKey: URL(string: "https://example.invalid/private")!,
                NSFilePathErrorKey: stagedPath,
            ])
        )

        let file = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).first
        )
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("example.invalid"))
        XCTAssertFalse(text.contains("private/var"))
        XCTAssertFalse(text.contains("Mara"))
        XCTAssertTrue(text.contains("network.request_failed"))
        XCTAssertTrue(text.contains("NSURLErrorDomain#\(NSURLErrorTimedOut)"))
    }

    func testModelProgressPresentationUsesExactDurableByteFraction() {
        let presentation = IOSModelProgressPresentation.transfer(
            durableBytes: 25,
            catalogBytes: 100,
            bytesPerSecond: 5,
            estimatedSecondsRemaining: 15,
            formatBytes: { "\($0) B" }
        )

        XCTAssertEqual(
            presentation.indicator,
            .determinate(fraction: 0.25, accessibilityValue: "25% — 25 of 100 bytes")
        )
        XCTAssertEqual(presentation.detail, "25% · 25 B of 100 B · 5 B/s · about 15s remaining")
    }

    func testModelProgressPresentationNeverCountsBytesBeyondCatalogTotal() {
        let presentation = IOSModelProgressPresentation.transfer(
            durableBytes: 125,
            catalogBytes: 100,
            bytesPerSecond: 20,
            estimatedSecondsRemaining: 1,
            formatBytes: { "\($0) B" }
        )

        XCTAssertEqual(presentation.indicator, .indeterminate)
        XCTAssertEqual(presentation.detail, "Download complete — finishing setup.")
    }

    func testModelProgressFinalizationPhasesAreIndeterminate() {
        XCTAssertEqual(IOSModelProgressPresentation.verification.indicator, .indeterminate)
        XCTAssertEqual(
            IOSModelProgressPresentation.verification.detail,
            "Checking downloaded files."
        )
        XCTAssertEqual(IOSModelProgressPresentation.installation.indicator, .indeterminate)
        XCTAssertEqual(
            IOSModelProgressPresentation.installation.detail,
            "Making the model available offline."
        )
        let retry = IOSModelProgressPresentation.retrying(
            retryCount: 1,
            reason: "Integrity verification"
        )
        XCTAssertEqual(retry.indicator, .indeterminate)
        XCTAssertEqual(
            retry.detail,
            "Preparing retry 1: Integrity verification. Verified files will be reused."
        )
    }

    func testModelProgressIncompleteRailRetainsVisibleTrackAtPixelBoundary() {
        XCTAssertEqual(
            IOSModelProgressPresentation.visibleDeterminateFillWidth(
                fraction: 0.9995,
                width: 300,
                thickness: 6
            ),
            294
        )
        XCTAssertEqual(
            IOSModelProgressPresentation.visibleDeterminateFillWidth(
                fraction: 0.5,
                width: 300,
                thickness: 6
            ),
            150
        )
        XCTAssertEqual(
            IOSModelProgressPresentation.visibleDeterminateFillWidth(
                fraction: 1,
                width: 300,
                thickness: 6
            ),
            300
        )
    }

    private func snapshot(headroom: UInt64, footprint: UInt64) -> IOSMemorySnapshot {
        IOSMemorySnapshot(
            processRole: .app,
            pid: 1,
            capturedAtUptimeSeconds: 1,
            totalDeviceRAMBytes: 8_000 * 1_048_576,
            availableHeadroomBytes: headroom,
            residentBytes: footprint,
            physFootprintBytes: footprint,
            compressedBytes: 0,
            gpuAllocatedBytes: nil,
            gpuRecommendedWorkingSetBytes: nil,
            hasUnifiedMemory: true
        )
    }
}

/// Skips the data-protection class (it is iOS-only; the macOS host would reject it) and fails
/// every metadata write to items named `failingName`, so a test can place one fault.
private final class StorageProtectionFaultFileManager: FileManager {
    private let failingName: String

    init(failingName: String) {
        self.failingName = failingName
        super.init()
    }

    override func setAttributes(
        _ attributes: [FileAttributeKey: Any],
        ofItemAtPath path: String
    ) throws {
        if URL(fileURLWithPath: path).lastPathComponent == failingName {
            throw CocoaError(.fileWriteNoPermission)
        }
        guard attributes[.protectionKey] == nil else { return }
        try super.setAttributes(attributes, ofItemAtPath: path)
    }
}

/// Skips the data-protection class like `StorageProtectionFaultFileManager` and fails only the
/// second of the two `.posixPermissions` writes around a read-only file's metadata window: the
/// widening (owner write added) succeeds, the restore (owner write removed) fails.
private final class StorageProtectionModeRestoreFaultFileManager: FileManager {
    override func setAttributes(
        _ attributes: [FileAttributeKey: Any],
        ofItemAtPath path: String
    ) throws {
        if let mode = (attributes[.posixPermissions] as? NSNumber)?.intValue, mode & 0o200 == 0 {
            throw CocoaError(.fileWriteNoPermission)
        }
        guard attributes[.protectionKey] == nil else { return }
        try super.setAttributes(attributes, ofItemAtPath: path)
    }
}
