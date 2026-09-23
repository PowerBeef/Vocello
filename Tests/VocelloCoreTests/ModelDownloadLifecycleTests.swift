import CryptoKit
import Foundation
@testable import QwenVoiceCore
import Synchronization
import XCTest

final class ModelDownloadLifecycleTests: XCTestCase {
    private var ledgerVerifiedFile: IOSModelDownloadLedger.VerifiedFile {
        .init(
            relativePath: "weights/model.safetensors",
            expectedSize: 42,
            sha256: String(repeating: "b", count: 64)
        )
    }

    private func ledgerRequest(
        logicalRequestID: String,
        artifactVersion: String = "v1",
        status: IOSModelDownloadLedger.Status,
        receivedBytes: Int64,
        verifiedFiles: [IOSModelDownloadLedger.VerifiedFile]
    ) -> IOSModelDownloadLedger.Request {
        .init(
            logicalRequestID: logicalRequestID,
            modelID: "model-a",
            artifactVersion: artifactVersion,
            repo: "org/model",
            revision: String(repeating: "a", count: 40),
            targetFolder: "model-a",
            expectedFiles: ["weights/model.safetensors"],
            verifiedFiles: verifiedFiles,
            retryCount: 0,
            receivedBytes: receivedBytes,
            totalBytes: 42,
            status: status
        )
    }

    private actor EventRecorder {
        private var values: [String] = []

        func append(_ value: String) {
            values.append(value)
        }

        func snapshot() -> [String] {
            values
        }
    }

    private actor SuspensionGate {
        private var isOpen = false
        private var continuation: CheckedContinuation<Void, Never>?

        func wait() async {
            guard !isOpen else { return }
            await withCheckedContinuation { continuation = $0 }
        }

        func open() {
            isOpen = true
            continuation?.resume()
            continuation = nil
        }
    }

    private func identity(
        request: String = "request-a",
        model: String = "model-a",
        artifact: String = "v1",
        path: String = "weights/model.safetensors"
    ) -> ModelDownloadTaskIdentity {
        ModelDownloadTaskIdentity(
            logicalRequestID: request,
            modelID: model,
            artifactVersion: artifact,
            relativePath: path,
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64)
        )
    }

    func testTaskIdentityRoundTripsWithoutURLOrFilesystemPath() throws {
        let original = identity()
        let encoded = try XCTUnwrap(original.encodedTaskDescription)
        let decoded = try XCTUnwrap(ModelDownloadTaskIdentity.decode(taskDescription: encoded))

        XCTAssertEqual(decoded, original)
        XCTAssertFalse(encoded.contains("https"))
        XCTAssertFalse(encoded.contains("/Users/"))
    }

    func testArtifactURLPolicyRejectsUnsafeInitialHostsAndRedirects() throws {
        let policy = ModelArtifactURLPolicy(
            allowedInitialHosts: ["huggingface.co"],
            allowedRedirectHostSuffixes: ["huggingface.co", "hf.co"]
        )
        let source = try XCTUnwrap(URL(string: "https://huggingface.co/org/model/resolve/"))
        XCTAssertTrue(policy.allowsInitialRequest(source))
        XCTAssertTrue(policy.allowsRedirect(
            from: source,
            to: try XCTUnwrap(URL(string: "https://cdn-lfs.huggingface.co/object"))
        ))
        XCTAssertTrue(policy.allowsRedirect(
            from: source,
            to: try XCTUnwrap(URL(string: "https://cas-bridge.xethub.hf.co/object"))
        ))
        for value in [
            "http://huggingface.co/object",
            "https://attacker.invalid/object",
            "https://127.0.0.1/object",
            "https://localhost/object",
            "https://user:secret@huggingface.co/object",
        ] {
            XCTAssertFalse(policy.allowsRedirect(
                from: source,
                to: try XCTUnwrap(URL(string: value))
            ), value)
        }
        XCTAssertFalse(policy.allowsRedirect(
            from: try XCTUnwrap(URL(string: "https://attacker.invalid/source")),
            to: try XCTUnwrap(URL(string: "https://huggingface.co/object"))
        ))
    }

    func testTaskIdentityRejectsMissingDigestUnsafePathAndUnsafeIdentity() {
        let missingDigest = ModelDownloadTaskIdentity(
            logicalRequestID: "request",
            modelID: "model",
            artifactVersion: "v1",
            relativePath: "weights/model.safetensors",
            expectedSize: 42,
            expectedSHA256: nil
        )
        let unsafePath = ModelDownloadTaskIdentity(
            logicalRequestID: "request",
            modelID: "model",
            artifactVersion: "v1",
            relativePath: "../model.safetensors",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64)
        )
        let unsafeModel = ModelDownloadTaskIdentity(
            logicalRequestID: "request",
            modelID: "https://attacker.invalid/model",
            artifactVersion: "v1",
            relativePath: "weights/model.safetensors",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64)
        )

        for identity in [missingDigest, unsafePath, unsafeModel] {
            XCTAssertFalse(identity.isValidProductionIdentity)
            XCTAssertNil(identity.encodedTaskDescription)
            let plan = ModelDownloadTaskReconciler.plan(
                expected: [self.identity()],
                existing: [ModelDownloadExistingTask(taskID: 1, identity: identity)]
            )
            XCTAssertEqual(plan.cancelledTaskIDs, [1])
        }
    }

    func testExistingTaskIsAdoptedWithNoDuplicateCreation() {
        let expected = identity()
        let plan = ModelDownloadTaskReconciler.plan(
            expected: [expected],
            existing: [ModelDownloadExistingTask(taskID: 7, identity: expected)]
        )

        XCTAssertEqual(plan.adoptedTaskByReconciliationKey, [expected.relativePath: 7])
        XCTAssertTrue(plan.cancelledTaskIDs.isEmpty)
        XCTAssertTrue(plan.missingReconciliationKeys.isEmpty)
    }

    func testUnknownStaleAndDuplicateTasksAreCancelled() {
        let expected = identity()
        let stale = identity(artifact: "v0")
        let plan = ModelDownloadTaskReconciler.plan(
            expected: [expected],
            existing: [
                ModelDownloadExistingTask(taskID: 4, identity: nil),
                ModelDownloadExistingTask(taskID: 3, identity: stale),
                ModelDownloadExistingTask(taskID: 2, identity: expected),
                ModelDownloadExistingTask(taskID: 8, identity: expected),
            ]
        )

        XCTAssertEqual(plan.adoptedTaskByReconciliationKey, [expected.relativePath: 2])
        XCTAssertEqual(plan.cancelledTaskIDs, [3, 4, 8])
        XCTAssertTrue(plan.missingReconciliationKeys.isEmpty)
    }

    func testMissingTaskIsCreatedOnlyForMissingIdentity() {
        let first = identity(path: "a.safetensors")
        let second = identity(path: "b.safetensors")
        let plan = ModelDownloadTaskReconciler.plan(
            expected: [first, second],
            existing: [ModelDownloadExistingTask(taskID: 1, identity: first)]
        )
        XCTAssertEqual(plan.missingReconciliationKeys, ["b.safetensors"])
    }

    func testProgressPreservesValidRelaunchFloorButDropsInvalidatedRetryBytes() {
        XCTAssertEqual(
            ModelDownloadProgressReconciler.visibleBytes(current: 20, persisted: 40, total: 100),
            40
        )
        XCTAssertEqual(
            ModelDownloadProgressReconciler.visibleBytes(current: 70, persisted: 40, total: 100),
            70
        )
        XCTAssertEqual(
            ModelDownloadProgressReconciler.visibleBytes(current: 120, persisted: 40, total: 100),
            100
        )
        XCTAssertEqual(
            ModelDownloadProgressReconciler.visibleBytes(
                current: 25,
                persisted: 100,
                total: 100,
                persistedBytesAreValid: false
            ),
            25
        )
    }

    func testExplicitInstallStartsFreshAfterTerminalTombstone() {
        let replacement = ledgerRequest(
            logicalRequestID: "new-request",
            status: .queued,
            receivedBytes: 0,
            verifiedFiles: []
        )

        for status in [
            IOSModelDownloadLedger.Status.cancelRequested,
            .installed,
            .deleted,
        ] {
            let terminal = ledgerRequest(
                logicalRequestID: "old-request",
                status: status,
                receivedBytes: 42,
                verifiedFiles: [ledgerVerifiedFile]
            )
            XCTAssertEqual(
                terminal.queuedForExplicitInstall(replacing: replacement),
                replacement,
                "\(status) must not carry terminal bytes into a fresh install"
            )
        }
    }

    func testExplicitRetryPreservesSameArtifactResumeEvidence() {
        let failed = ledgerRequest(
            logicalRequestID: "retained-request",
            status: .failed,
            receivedBytes: 21,
            verifiedFiles: [ledgerVerifiedFile]
        )
        let replacement = ledgerRequest(
            logicalRequestID: "new-request",
            status: .queued,
            receivedBytes: 0,
            verifiedFiles: []
        )

        let resumed = failed.queuedForExplicitInstall(replacing: replacement)
        XCTAssertEqual(resumed.logicalRequestID, "retained-request")
        XCTAssertEqual(resumed.status, .queued)
        XCTAssertEqual(resumed.receivedBytes, 21)
        XCTAssertEqual(resumed.verifiedFiles, [ledgerVerifiedFile])
    }

    func testExplicitRetryRejectsResumeEvidenceFromAnotherArtifact() {
        let failed = ledgerRequest(
            logicalRequestID: "retained-request",
            artifactVersion: "v1",
            status: .failed,
            receivedBytes: 21,
            verifiedFiles: [ledgerVerifiedFile]
        )
        let replacement = ledgerRequest(
            logicalRequestID: "new-request",
            artifactVersion: "v2",
            status: .queued,
            receivedBytes: 0,
            verifiedFiles: []
        )

        XCTAssertEqual(failed.queuedForExplicitInstall(replacing: replacement), replacement)
    }

    func testDelegateProgressGateBoundsIngressAndAlwaysForwardsTerminalBytes() {
        var gate = ModelDownloadDelegateProgressGate()

        XCTAssertTrue(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 1,
            totalBytesExpected: 100,
            uptime: 10
        ))
        XCTAssertFalse(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 50,
            totalBytesExpected: 100,
            uptime: 10.1
        ))
        XCTAssertFalse(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 1,
            totalBytesExpected: 100,
            uptime: 10.5
        ))
        XCTAssertTrue(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 60,
            totalBytesExpected: 100,
            uptime: 10.5
        ))
        XCTAssertTrue(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 100,
            totalBytesExpected: 100,
            uptime: 10.51
        ))

        gate.finish(taskID: 7)
        XCTAssertTrue(gate.shouldForward(
            taskID: 7,
            totalBytesWritten: 1,
            totalBytesExpected: 100,
            uptime: 11
        ))
    }

    func testDelegateTerminalSequencerAwaitsDurableStageBeforeCompletion() async {
        let sequencer = ModelDownloadDelegateTerminalSequencer()
        let suspension = SuspensionGate()
        let events = EventRecorder()

        sequencer.stage(taskID: 9) {
            await suspension.wait()
            await events.append("staged")
        }
        let completion = sequencer.complete(taskID: 9) {
            await events.append("completed")
        }

        await suspension.open()
        await completion.value

        let recordedEvents = await events.snapshot()
        XCTAssertEqual(recordedEvents, ["staged", "completed"])
        XCTAssertEqual(sequencer.pendingStageCount, 0)
    }

    func testDownloadedFileValidationStatsAtomicReplacementAuthoritatively() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let partial = root.appendingPathComponent("model.safetensors.partial")
        let durableTemporary = root.appendingPathComponent("background-download.tmp")
        try Data().write(to: partial)
        // Prime the URL metadata path with the old zero-byte file before replacing it,
        // matching the physical-device background download sequence.
        XCTAssertEqual(try partial.resourceValues(forKeys: [.fileSizeKey]).fileSize, 0)

        let payload = Data(repeating: 0xA5, count: 8_193)
        try payload.write(to: durableTemporary)
        try FileManager.default.removeItem(at: partial)
        try FileManager.default.moveItem(at: durableTemporary, to: partial)

        XCTAssertEqual(
            try HuggingFaceDownloader.authoritativeFileSize(at: partial),
            Int64(payload.count)
        )
        XCTAssertNoThrow(try HuggingFaceDownloader.validateDownloadedFile(
            at: partial,
            expectedSize: Int64(payload.count),
            sha256: nil
        ))
        XCTAssertThrowsError(try HuggingFaceDownloader.validateDownloadedFile(
            at: partial,
            expectedSize: Int64(payload.count + 1),
            sha256: nil
        ))
    }

    func testRetryPolicySeparatesTransientPermanentTLSDiskAndIntegrity() {
        let transient = NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)
        let tls = NSError(domain: NSURLErrorDomain, code: NSURLErrorServerCertificateUntrusted)
        let disk = NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotWriteToFile)

        guard case .retry = ModelDownloadRetryPolicy.disposition(
            error: transient,
            retryNumber: 1,
            integrityRetryAlreadyUsed: false
        ) else { return XCTFail("connection loss must retry") }
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(error: tls, retryNumber: 1, integrityRetryAlreadyUsed: false),
            .fail
        )
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(error: disk, retryNumber: 1, integrityRetryAlreadyUsed: false),
            .fail
        )

        let integrity = HuggingFaceDownloader.DownloadError.integrityCheckFailed(
            path: "weights",
            reason: "fixture"
        )
        guard case .retryClean = ModelDownloadRetryPolicy.disposition(
            error: integrity,
            retryNumber: 1,
            integrityRetryAlreadyUsed: false
        ) else { return XCTFail("first integrity mismatch must retry clean") }
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(
                error: integrity,
                retryNumber: 2,
                integrityRetryAlreadyUsed: true
            ),
            .fail
        )
    }

    func testHTTPRetryAfterIsCappedAndPermanent4xxFails() {
        let throttled = HuggingFaceDownloader.DownloadError.httpError(
            statusCode: 429,
            path: "weights",
            retryAfterSeconds: 900
        )
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(
                error: throttled,
                retryNumber: 1,
                integrityRetryAlreadyUsed: false
            ),
            .retry(afterSeconds: 300)
        )
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(
                error: HuggingFaceDownloader.DownloadError.httpError(statusCode: 404, path: "weights"),
                retryNumber: 1,
                integrityRetryAlreadyUsed: false
            ),
            .fail
        )
        for status in [408, 500, 503] {
            let error = HuggingFaceDownloader.DownloadError.httpError(
                statusCode: status,
                path: "weights"
            )
            guard case .retry = ModelDownloadRetryPolicy.disposition(
                error: error,
                retryNumber: 3,
                integrityRetryAlreadyUsed: false
            ) else { return XCTFail("HTTP \(status) must retry through attempt three") }
            XCTAssertEqual(
                ModelDownloadRetryPolicy.disposition(
                    error: error,
                    retryNumber: 4,
                    integrityRetryAlreadyUsed: false
                ),
                .fail
            )
        }
        XCTAssertEqual(
            ModelDownloadRetryPolicy.disposition(
                error: CancellationError(),
                retryNumber: 1,
                integrityRetryAlreadyUsed: false
            ),
            .cancelled
        )
    }

    func testBackgroundCompletionWaitsForDurablePostprocessingAndDeliversOnce() {
        var eventsFirst = ModelDownloadBackgroundCompletionGate()
        XCTAssertFalse(eventsFirst.markEventsFinished())
        XCTAssertTrue(eventsFirst.markPostprocessingFinished())
        XCTAssertFalse(eventsFirst.markPostprocessingFinished())
        XCTAssertFalse(eventsFirst.markEventsFinished())

        eventsFirst.resetForRequest()
        XCTAssertFalse(eventsFirst.completionDelivered)
        XCTAssertFalse(eventsFirst.markPostprocessingFinished())
        XCTAssertTrue(eventsFirst.markEventsFinished())
    }

    func testVerifiedReceiptInvalidatesOnProcessOrMetadataChange() {
        let receipt = VerifiedArtifactReceipt(
            relativePath: "weights/model.safetensors",
            artifactVersion: "v1",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64),
            fileSize: 42,
            modificationTimeNanoseconds: 100,
            fileIdentifier: 7,
            verificationProcessGeneration: "process-a"
        )
        XCTAssertTrue(receipt.matches(
            relativePath: "weights/model.safetensors",
            artifactVersion: "v1",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64),
            fileSize: 42,
            modificationTimeNanoseconds: 100,
            fileIdentifier: 7,
            processGeneration: "process-a"
        ))
        XCTAssertFalse(receipt.matches(
            relativePath: "weights/model.safetensors",
            artifactVersion: "v1",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64),
            fileSize: 42,
            modificationTimeNanoseconds: 101,
            fileIdentifier: 7,
            processGeneration: "process-a"
        ))
        XCTAssertFalse(receipt.matches(
            relativePath: "weights/model.safetensors",
            artifactVersion: "v1",
            expectedSize: 42,
            expectedSHA256: String(repeating: "a", count: 64),
            fileSize: 42,
            modificationTimeNanoseconds: 100,
            fileIdentifier: 7,
            processGeneration: "process-b"
        ))
    }

    func testRangeValidationAcceptsExactAndRejectsIgnoredOrMalformedResponses() {
        XCTAssertTrue(HuggingFaceDownloader.contentRange("bytes 100-199/1000", startsAt: 100))
        XCTAssertTrue(HuggingFaceDownloader.contentRange("bytes 100-199/1000", matchesStart: 100, end: 199))
        XCTAssertFalse(HuggingFaceDownloader.contentRange(nil, startsAt: 100))
        XCTAssertFalse(HuggingFaceDownloader.contentRange("bytes 0-999/1000", startsAt: 100))
        XCTAssertFalse(HuggingFaceDownloader.contentRange("bytes 100-*/1000", startsAt: 100))
        XCTAssertFalse(HuggingFaceDownloader.contentRange("bytes 100-200/1000", matchesStart: 100, end: 199))
    }

    func testLedgerRoundTripAndAtomicReplacement() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = IOSModelDownloadLedgerStore(fileURL: root.appendingPathComponent("ledger.json"))
        let request = IOSModelDownloadLedger.Request(
            logicalRequestID: "logical",
            modelID: "model",
            artifactVersion: "v1",
            repo: "org/repo",
            revision: String(repeating: "a", count: 40),
            targetFolder: "model-folder",
            expectedFiles: ["weights/model.safetensors"],
            verifiedFiles: [],
            retryCount: 0,
            receivedBytes: 12,
            totalBytes: 42,
            status: .downloading
        )
        try store.save(IOSModelDownloadLedger(requests: [request]))
        XCTAssertEqual(try store.load().requests, [request])

        var updated = request
        updated.receivedBytes = 20
        try store.save(IOSModelDownloadLedger(requests: [updated]))
        XCTAssertEqual(try store.load().requests.first?.receivedBytes, 20)
    }

    func testArtifactUpdateMustReplaceSupersededLedgerRequestWholesale() throws {
        // Regression: a fully received request for a superseded (larger)
        // artifact cannot be resumed into a smaller replacement. Patching only
        // status/totalBytes leaves receivedBytes above the new total, which
        // fail-closes every subsequent ledger save ("ledger is invalid") and
        // bricks the visible Update/Retry loop.
        let installed = IOSModelDownloadLedger.Request(
            logicalRequestID: "old-logical",
            modelID: "pro_custom",
            artifactVersion: "2026.04.05.2",
            repo: "mlx-community/old-repo",
            revision: String(repeating: "a", count: 40),
            targetFolder: "pro_custom",
            expectedFiles: ["model.safetensors"],
            verifiedFiles: [
                .init(
                    relativePath: "model.safetensors",
                    expectedSize: 2_300_000_000,
                    sha256: String(repeating: "b", count: 64)
                ),
            ],
            retryCount: 0,
            receivedBytes: 2_300_000_000,
            totalBytes: 2_300_000_000,
            status: .installed
        )
        let replacement = IOSModelDownloadLedger.Request(
            logicalRequestID: "new-logical",
            modelID: "pro_custom",
            artifactVersion: "2026.07.26.1",
            repo: "PowerBeef02/new-repo",
            revision: String(repeating: "c", count: 40),
            targetFolder: "pro_custom",
            expectedFiles: ["model.safetensors"],
            verifiedFiles: [],
            retryCount: 0,
            receivedBytes: 0,
            totalBytes: 2_020_000_000,
            status: .queued
        )

        XCTAssertFalse(installed.hasSameArtifactIdentity(as: replacement))
        XCTAssertTrue(installed.hasSameArtifactIdentity(as: installed))

        // The trap: reusing the superseded entry with only status/totalBytes
        // patched produces an invalid document.
        var patched = installed
        patched.status = .queued
        patched.totalBytes = replacement.totalBytes
        XCTAssertThrowsError(
            try IOSModelDownloadLedger(requests: [patched]).validated()
        ) { error in
            XCTAssertEqual(error as? IOSModelDownloadLedgerError, .invalidDocument)
        }

        // The fix: wholesale replacement validates and round-trips.
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = IOSModelDownloadLedgerStore(fileURL: root.appendingPathComponent("ledger.json"))
        try store.save(IOSModelDownloadLedger(requests: [replacement]))
        XCTAssertEqual(try store.load().requests, [replacement])
    }

    func testCorruptAndUnsupportedLedgerFailClosed() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let url = root.appendingPathComponent("ledger.json")
        let store = IOSModelDownloadLedgerStore(fileURL: url)

        try Data("not-json".utf8).write(to: url)
        XCTAssertThrowsError(try store.load())

        try Data(#"{"schemaVersion":99,"requests":[]}"#.utf8).write(to: url)
        XCTAssertThrowsError(try store.load()) { error in
            XCTAssertEqual(error as? IOSModelDownloadLedgerError, .unsupportedSchema(99))
        }
    }

    func testLedgerRejectsAbsoluteTraversalAndDuplicateModelRequests() {
        func request(id: String, path: String) -> IOSModelDownloadLedger.Request {
            IOSModelDownloadLedger.Request(
                logicalRequestID: id,
                modelID: "model",
                artifactVersion: "v1",
                repo: "org/repo",
                revision: String(repeating: "a", count: 40),
                targetFolder: "model-folder",
                expectedFiles: [path],
                verifiedFiles: [],
                retryCount: 0,
                receivedBytes: 0,
                totalBytes: 42,
                status: .queued
            )
        }

        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [request(id: "a", path: "/tmp/file")]).validated())
        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [request(id: "a", path: "../file")]).validated())
        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [request(id: "a", path: "%2e%2e/file")]).validated())
        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [
            request(id: "a", path: "one"),
            request(id: "b", path: "two"),
        ]).validated())
    }

    func testLedgerRejectsMutableRevisionAndUnverifiedReceiptIdentity() {
        func request(revision: String, verifiedSHA: String?) -> IOSModelDownloadLedger.Request {
            IOSModelDownloadLedger.Request(
                logicalRequestID: "logical",
                modelID: "model",
                artifactVersion: "v1",
                repo: "org/repo",
                revision: revision,
                targetFolder: "model-folder",
                expectedFiles: ["weights/model.safetensors"],
                verifiedFiles: [IOSModelDownloadLedger.VerifiedFile(
                    relativePath: "weights/model.safetensors",
                    expectedSize: 42,
                    sha256: verifiedSHA
                )],
                retryCount: 0,
                receivedBytes: 42,
                totalBytes: 42,
                status: .verifying
            )
        }

        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [
            request(revision: "main", verifiedSHA: String(repeating: "a", count: 64))
        ]).validated())
        XCTAssertThrowsError(try IOSModelDownloadLedger(requests: [
            request(revision: String(repeating: "a", count: 40), verifiedSHA: nil)
        ]).validated())
    }

    func testDiagnosticsAreBoundedAndRedactURLsAndAbsolutePaths() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(directory: root)
        let cap = ModelDownloadDiagnosticsStore.maxRetainedRecords
        for index in 0..<(cap + 10) {
            store.recordFailure(
                classification: "network-\(index)",
                message: "failed at https://example.invalid/private from /Users/example/private/file"
            )
        }
        let files = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        XCTAssertLessThanOrEqual(files.count, cap)
        let payload = try files.map { try String(contentsOf: $0, encoding: .utf8) }.joined()
        XCTAssertFalse(payload.contains("example.invalid"))
        XCTAssertFalse(payload.contains("/Users/example"))
    }

    func testModelManagementTraceIsCorrelatedOrderedAndRedacted() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(
            directory: root,
            diagnosticTraceRunID: "ios-run-1"
        )
        store.recordEvent(
            layer: "url-session",
            event: "task-completed",
            modelID: "pro_custom",
            logicalRequestID: "request-1",
            operationGeneration: 7,
            artifactVersion: "speed-v1",
            durableBytes: 42,
            totalBytes: 100,
            errorMessage: "failed at https://example.invalid/private in /private/var/mobile/fixture"
        )
        store.recordEvent(
            layer: "ledger",
            event: "write",
            modelID: "pro_custom",
            logicalRequestID: "request-1",
            operationGeneration: 7,
            artifactVersion: "speed-v1",
            durableBytes: 100,
            totalBytes: 100,
            ledgerStatus: "verifying"
        )

        let traceRoot = root.appendingPathComponent("trace", isDirectory: true)
            .appendingPathComponent("ios-run-1", isDirectory: true)
        let journal = try XCTUnwrap(FileManager.default.contentsOfDirectory(
            at: traceRoot,
            includingPropertiesForKeys: nil
        ).first { $0.pathExtension == "jsonl" })
        let rows = try String(contentsOf: journal, encoding: .utf8)
            .split(separator: "\n")
            .map {
                try JSONDecoder().decode(
                ModelDownloadDiagnosticsStore.DeliveryEvent.self,
                    from: Data($0.utf8)
                )
            }
        XCTAssertEqual(rows.map(\.runID), ["ios-run-1", "ios-run-1"])
        XCTAssertEqual(rows.map(\.sequence), [1, 2])
        XCTAssertEqual(Set(rows.map(\.processInstanceID)).count, 1)
        XCTAssertEqual(rows.last?.ledgerStatus, "verifying")
        XCTAssertFalse(rows.first?.errorMessage?.contains("example.invalid") ?? true)
        XCTAssertFalse(rows.first?.errorMessage?.contains("/private/var") ?? true)

        let attemptRoot = root.appendingPathComponent("attempts", isDirectory: true)
            .appendingPathComponent("ios-run-1", isDirectory: true)
        store.recordFailure(classification: "network", message: "bounded")
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(
            at: attemptRoot,
            includingPropertiesForKeys: nil
        ).contains { $0.pathExtension == "jsonl" })
    }

    func testModelManagementTraceRetentionCoversOneWorstCaseTransferAndStaysBounded() {
        let oneHourLedgerWrites = 60 * 60 * 2
        let oneHourHeartbeats = 60 * 60 / 5
        XCTAssertGreaterThanOrEqual(
            ModelDownloadDiagnosticsStore.maxRetainedTraceEvents,
            oneHourLedgerWrites + oneHourHeartbeats
        )
        XCTAssertGreaterThan(ModelDownloadDiagnosticsStore.maxRetainedTraceBytes, 0)
        XCTAssertLessThanOrEqual(
            ModelDownloadDiagnosticsStore.maxRetainedTraceBytes,
            40 * 1_024 * 1_024
        )
    }

    func testDiagnosticsSummarizePhaseTimingWireBytesAndFinalIntegrity() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(directory: root)

        func progress(_ phase: HuggingFaceDownloader.DownloadPhase) -> HuggingFaceDownloader.RepositoryProgress {
            HuggingFaceDownloader.RepositoryProgress(
                downloadedBytes: phase == .downloading ? 20 : 100,
                totalBytes: 100,
                completedFiles: phase == .downloading ? 0 : 1,
                totalFiles: 1,
                bytesPerSecond: phase == .downloading ? 10 : nil,
                isStalled: false,
                estimatedSecondsRemaining: phase == .downloading ? 8 : nil,
                retryCount: 1,
                statusMessage: nil,
                phase: phase
            )
        }

        store.record(progress: progress(.downloading))
        store.record(metrics: HuggingFaceDownloader.TransferMetrics(
            relativePath: "weights/model.safetensors",
            protocolName: "h3",
            redirectCount: 1,
            reusedConnection: true,
            cellular: false,
            constrained: false,
            expensive: false,
            transferredBytes: 120,
            durationSeconds: 2
        ))
        store.record(metrics: HuggingFaceDownloader.TransferMetrics(
            relativePath: nil,
            protocolName: "h3",
            redirectCount: 0,
            reusedConnection: true,
            cellular: false,
            constrained: false,
            expensive: false,
            transferredBytes: 20,
            durationSeconds: 0.1
        ))
        store.record(progress: progress(.verifying))
        store.record(progress: progress(.installing))
        store.recordSuccess(expectedBytes: 150, reusedBytes: 30)

        let files = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        let objects = try files.compactMap { file -> [String: Any]? in
            let data = try Data(contentsOf: file)
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        }
        let success = try XCTUnwrap(objects.first { $0["kind"] as? String == "success" })
        XCTAssertEqual(success["wireBytes"] as? Int, 120)
        XCTAssertEqual(success["controlBytes"] as? Int, 20)
        XCTAssertEqual(success["expectedBytes"] as? Int, 150)
        XCTAssertEqual(success["reusedBytes"] as? Int, 30)
        XCTAssertEqual(success["duplicateBytes"] as? Int, 0)
        XCTAssertEqual(success["retryCount"] as? Int, 1)
        XCTAssertEqual(success["protocols"] as? [String], ["h3"])
        XCTAssertEqual(success["finalIntegrity"] as? Bool, true)
        XCTAssertNotNil(success["thermalState"] as? String)
    }

    // MARK: - Typed retry reasons and per-range retry diagnostics

    private func diagnosticObjects(in root: URL) throws -> [[String: Any]] {
        try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
            .compactMap { file -> [String: Any]? in
                try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
            }
    }

    func testDiagnosticsPersistTypedRetryReasonAndRangeRetryEvents() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(directory: root)

        func progress(
            _ phase: HuggingFaceDownloader.DownloadPhase,
            reason: HuggingFaceDownloader.RetryReason? = nil
        ) -> HuggingFaceDownloader.RepositoryProgress {
            HuggingFaceDownloader.RepositoryProgress(
                downloadedBytes: 20,
                totalBytes: 100,
                completedFiles: 0,
                totalFiles: 1,
                bytesPerSecond: nil,
                isStalled: false,
                estimatedSecondsRemaining: nil,
                retryCount: phase == .retrying ? 1 : 0,
                statusMessage: nil,
                phase: phase,
                retryReason: reason
            )
        }

        store.record(progress: progress(.downloading))
        store.record(rangeRetry: HuggingFaceDownloader.RangeRetryEvent(
            relativePath: "weights/model.safetensors",
            rangeStart: 134_217_728,
            rangeLength: 134_217_728,
            attempt: 1,
            reason: .shortRange,
            delaySeconds: 1
        ))
        store.record(rangeRetry: HuggingFaceDownloader.RangeRetryEvent(
            relativePath: "/private/var/mobile/fixture/model.safetensors",
            rangeStart: 0,
            rangeLength: 33_554_432,
            attempt: 2,
            reason: .http5xx,
            delaySeconds: 2
        ))
        store.record(progress: progress(.retrying, reason: .shortRange))
        store.record(progress: progress(.downloading))
        store.recordSuccess(expectedBytes: 100)

        let objects = try diagnosticObjects(in: root)
        let phases = objects.filter { $0["kind"] as? String == "phase" }
        let retrying = try XCTUnwrap(phases.first { $0["phase"] as? String == "retrying" })
        XCTAssertEqual(retrying["retryReason"] as? String, "short-range")
        XCTAssertEqual(retrying["retryCount"] as? Int, 1)
        XCTAssertTrue(
            phases.filter { $0["phase"] as? String == "downloading" }
                .allSatisfy { $0["retryReason"] == nil },
            "only a retrying phase carries a retry reason"
        )

        let rangeRetries = objects
            .filter { $0["kind"] as? String == "range-retry" }
            .sorted { ($0["attempt"] as? Int ?? 0) < ($1["attempt"] as? Int ?? 0) }
        XCTAssertEqual(rangeRetries.count, 2)
        XCTAssertEqual(rangeRetries.first?["relativePath"] as? String, "weights/model.safetensors")
        XCTAssertEqual(rangeRetries.first?["attempt"] as? Int, 1)
        XCTAssertEqual(rangeRetries.first?["retryReason"] as? String, "short-range")
        XCTAssertEqual(rangeRetries.first?["rangeStart"] as? Int, 134_217_728)
        XCTAssertEqual(rangeRetries.first?["rangeLength"] as? Int, 134_217_728)
        XCTAssertEqual(rangeRetries.first?["retryDelaySeconds"] as? Double, 1)
        XCTAssertNil(rangeRetries.last?["relativePath"], "an absolute path is never persisted")
        XCTAssertEqual(rangeRetries.last?["retryReason"] as? String, "http-5xx")

        let success = try XCTUnwrap(objects.first { $0["kind"] as? String == "success" })
        XCTAssertEqual(success["retryCount"] as? Int, 1)
        XCTAssertEqual(success["rangeRetryCount"] as? Int, 2)

        let payload = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
            .map { try String(contentsOf: $0, encoding: .utf8) }
            .joined()
        XCTAssertFalse(payload.contains("/private/var"))
    }

    func testRangeRetryRecordsAreCappedPerRunButFullyCounted() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ModelDownloadDiagnosticsStore(directory: root)
        let cap = ModelDownloadDiagnosticsStore.maxRangeRetryRecordsPerRun
        XCTAssertLessThan(cap, ModelDownloadDiagnosticsStore.maxRetainedRecords / 4)
        for index in 0..<(cap + 6) {
            store.record(rangeRetry: HuggingFaceDownloader.RangeRetryEvent(
                relativePath: "weights/model.safetensors",
                rangeStart: Int64(index) * 1_024,
                rangeLength: 1_024,
                attempt: 1,
                reason: .network,
                delaySeconds: 1
            ))
        }
        store.recordSuccess(expectedBytes: 100)

        let objects = try diagnosticObjects(in: root)
        XCTAssertEqual(objects.filter { $0["kind"] as? String == "range-retry" }.count, cap)
        let success = try XCTUnwrap(objects.first { $0["kind"] as? String == "success" })
        XCTAssertEqual(success["rangeRetryCount"] as? Int, cap + 6)
    }

    // MARK: - Range-level retry through a stubbed foreground session
    //
    // These drive the real chunked path (`downloadFiles` -> chunk workers -> assembly ->
    // sidecar -> verification -> install) over a foreground URLSession whose only
    // protocol is an in-process stub, so they are network-free. One worker keeps the
    // range order deterministic.

    fileprivate static let stubRelativePath = "weights/model.safetensors"

    private struct StubbedDelivery {
        let host: String
        let root: URL
        let payload: Data
        let ranges: [HuggingFaceDownloader.ChunkRange]
        let downloader: HuggingFaceDownloader
        let retries: RangeRetryStubSink<HuggingFaceDownloader.RangeRetryEvent>
        let progress: RangeRetryStubSink<HuggingFaceDownloader.RepositoryProgress>

        var targetDir: URL { root.appendingPathComponent("models/stub-model", isDirectory: true) }

        func header(_ index: Int) -> String {
            "bytes=\(ranges[index].start)-\(ranges[index].end)"
        }

        func run() async throws {
            let digest = SHA256.hash(data: payload).map { String(format: "%02x", $0) }.joined()
            let file = HuggingFaceDownloader.RepoFile(
                path: ModelDownloadLifecycleTests.stubRelativePath,
                size: Int64(payload.count),
                sha256: digest,
                absoluteURL: URL(string: "https://\(host)/\(ModelDownloadLifecycleTests.stubRelativePath)")
            )
            try await downloader.downloadFiles(
                [file],
                repo: "stub/model",
                revision: String(repeating: "a", count: 40),
                to: targetDir,
                stagingRoot: root.appendingPathComponent("staging", isDirectory: true)
            )
        }

        func installedPayload() throws -> Data {
            try Data(contentsOf: targetDir.appendingPathComponent(
                ModelDownloadLifecycleTests.stubRelativePath
            ))
        }

        var requests: [String] { RangeStubURLProtocol.requests(host: host) }

        func requestCount(_ header: String) -> Int {
            requests.filter { $0 == header }.count
        }
    }

    private func makeStubbedDelivery(
        faults: [Int: [RangeStubURLProtocol.Fault]] = [:],
        ignoreRange: Bool = false,
        maxRangeRetries: Int = 3
    ) throws -> StubbedDelivery {
        let host = "\(UUID().uuidString.lowercased()).range-stub.invalid"
        let payload = Data((0..<8_192).map { UInt8(truncatingIfNeeded: $0 &* 31 &+ 7) })
        var configuration = HuggingFaceDownloader.Configuration()
        configuration.maxConcurrentFiles = 1
        configuration.chunkLargeFiles = true
        configuration.chunkedDownloadThreshold = 1_024
        configuration.chunkTargetSize = 1_024
        configuration.chunkWorkerCount = 1
        configuration.maxRangeRetries = maxRangeRetries
        let ranges = HuggingFaceDownloader.chunkRanges(
            total: Int64(payload.count),
            chunkSize: configuration.chunkTargetSize,
            tailWorkerCount: configuration.chunkWorkerCount
        )
        var faultsByHeader: [String: [RangeStubURLProtocol.Fault]] = [:]
        for (index, queue) in faults {
            faultsByHeader["bytes=\(ranges[index].start)-\(ranges[index].end)"] = queue
        }
        RangeStubURLProtocol.install(
            host: host,
            payload: payload,
            faults: faultsByHeader,
            ignoreRange: ignoreRange
        )

        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("range-retry-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.protocolClasses = [RangeStubURLProtocol.self]
        let retries = RangeRetryStubSink<HuggingFaceDownloader.RangeRetryEvent>()
        let progress = RangeRetryStubSink<HuggingFaceDownloader.RepositoryProgress>()
        let downloader = HuggingFaceDownloader(
            progressHandler: { progress.append($0) },
            sessionConfiguration: sessionConfiguration,
            engineConfiguration: configuration,
            durableTemporaryDirectory: root.appendingPathComponent("delegate", isDirectory: true),
            rangeRetryHandler: { retries.append($0) }
        )
        return StubbedDelivery(
            host: host,
            root: root,
            payload: payload,
            ranges: ranges,
            downloader: downloader,
            retries: retries,
            progress: progress
        )
    }

    private func tearDownStubbedDelivery(_ delivery: StubbedDelivery) {
        RangeStubURLProtocol.uninstall(host: delivery.host)
        try? FileManager.default.removeItem(at: delivery.root)
    }

    func testShortRangeBodyRetriesOnlyThatRangeAndKeepsEveryOtherRange() async throws {
        let delivery = try makeStubbedDelivery(faults: [2: [.shortBody(900)]])
        defer { tearDownStubbedDelivery(delivery) }

        try await delivery.run()

        XCTAssertEqual(try delivery.installedPayload(), delivery.payload)
        XCTAssertEqual(delivery.requestCount(delivery.header(2)), 2, "only the short range is re-requested")
        for index in delivery.ranges.indices where index != 2 {
            XCTAssertEqual(delivery.requestCount(delivery.header(index)), 1, "range \(index) is untouched")
        }
        XCTAssertFalse(delivery.requests.contains(""), "no whole-file fetch")
        let retries = delivery.retries.values
        XCTAssertEqual(retries.count, 1)
        XCTAssertEqual(retries.first?.reason, .shortRange)
        XCTAssertEqual(retries.first?.attempt, 1)
        XCTAssertEqual(retries.first?.rangeStart, delivery.ranges[2].start)
        XCTAssertEqual(retries.first?.rangeLength, 1_024)
        XCTAssertEqual(retries.first?.relativePath, Self.stubRelativePath)
        XCTAssertFalse(
            delivery.progress.values.contains { $0.phase == .retrying },
            "a recovered range never reaches the file-level retry"
        )
    }

    func testTransientNetworkErrorOnOneRangeRetriesThatRange() async throws {
        let delivery = try makeStubbedDelivery(
            faults: [1: [.transportError(NSURLErrorNetworkConnectionLost)]]
        )
        defer { tearDownStubbedDelivery(delivery) }

        try await delivery.run()

        XCTAssertEqual(try delivery.installedPayload(), delivery.payload)
        XCTAssertEqual(delivery.requestCount(delivery.header(1)), 2)
        for index in delivery.ranges.indices where index != 1 {
            XCTAssertEqual(delivery.requestCount(delivery.header(index)), 1)
        }
        XCTAssertFalse(delivery.requests.contains(""))
        XCTAssertEqual(delivery.retries.values.map(\.reason), [.network])
        XCTAssertFalse(delivery.progress.values.contains { $0.phase == .retrying })
    }

    func testIgnoredRangeStillFallsBackToOneCleanSingleStream() async throws {
        let delivery = try makeStubbedDelivery(ignoreRange: true)
        defer { tearDownStubbedDelivery(delivery) }

        try await delivery.run()

        XCTAssertEqual(try delivery.installedPayload(), delivery.payload)
        // The first range got HTTP 200: no range retry; the file-level retry clears the
        // partial and re-fetches once as a single stream with no Range header.
        XCTAssertEqual(delivery.requests, [delivery.header(0), ""])
        XCTAssertTrue(delivery.retries.values.isEmpty)
        let retrying = delivery.progress.values.filter { $0.phase == .retrying }
        XCTAssertFalse(retrying.isEmpty)
        XCTAssertTrue(retrying.allSatisfy { $0.retryReason == .rangeResponse })
    }

    func testExhaustedRangeRetriesEscalateWithoutClearingTheSidecar() async throws {
        let last = HuggingFaceDownloader.chunkRanges(
            total: 8_192,
            chunkSize: 1_024,
            tailWorkerCount: 1
        ).count - 1
        let delivery = try makeStubbedDelivery(
            faults: [last: [.shortBody(10), .shortBody(10)]],
            maxRangeRetries: 1
        )
        defer { tearDownStubbedDelivery(delivery) }

        try await delivery.run()

        XCTAssertEqual(try delivery.installedPayload(), delivery.payload)
        // The initial request and its one range retry come back short; the file-level
        // retry then resumes from the sidecar and fetches only the missing range.
        XCTAssertEqual(delivery.requestCount(delivery.header(last)), 3)
        for index in delivery.ranges.indices where index != last {
            XCTAssertEqual(
                delivery.requestCount(delivery.header(index)),
                1,
                "completed range \(index) survives the file-level retry"
            )
        }
        XCTAssertFalse(delivery.requests.contains(""), "no single-stream fallback")
        XCTAssertEqual(delivery.retries.values.map(\.attempt), [1])
        let retrying = delivery.progress.values.filter { $0.phase == .retrying }
        XCTAssertFalse(retrying.isEmpty)
        XCTAssertTrue(retrying.allSatisfy { $0.retryReason == .shortRange && $0.retryCount == 1 })
    }

    func testCancellationDuringRangeRetryBackoffNeverRetries() async throws {
        let delivery = try makeStubbedDelivery(
            faults: [0: [.status(503, retryAfter: "30")]]
        )
        defer { tearDownStubbedDelivery(delivery) }

        let started = ContinuousClock.now
        let transfer = Task { try await delivery.run() }
        let deadline = ContinuousClock.now.advanced(by: .seconds(10))
        while delivery.retries.values.isEmpty, ContinuousClock.now < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(delivery.retries.values.map(\.reason), [.http5xx])
        XCTAssertEqual(delivery.retries.values.first?.delaySeconds, 30, "Retry-After is honored")

        await delivery.downloader.cancel()
        do {
            try await transfer.value
            XCTFail("a cancelled delivery must not complete")
        } catch let error as HuggingFaceDownloader.DownloadError {
            guard case .cancelled = error else { return XCTFail("unexpected error: \(error)") }
        }
        XCTAssertLessThan(
            ContinuousClock.now - started,
            .seconds(15),
            "cancellation interrupts the Retry-After backoff"
        )
        XCTAssertEqual(delivery.requests, [delivery.header(0)], "the cancelled range is never re-requested")
    }
}

/// Lock-protected collector for downloader callbacks in the stubbed range-retry tests.
private final class RangeRetryStubSink<Value: Sendable>: Sendable {
    private let storage = Mutex<[Value]>([])

    func append(_ value: Value) {
        storage.withLock { $0.append(value) }
    }

    var values: [Value] {
        storage.withLock { $0 }
    }
}

/// In-process HTTP stub for `*.range-stub.invalid` hosts: serves one in-memory payload,
/// honors `Range: bytes=start-end` (and `bytes=start-`) with 206 + Content-Range, and
/// consumes a per-host, per-Range-header queue of injected faults. It records every
/// request's Range header ("" for none) so tests can prove which ranges were fetched.
private final class RangeStubURLProtocol: URLProtocol {
    enum Fault: Sendable {
        /// 206 with the full Content-Range but only this many body bytes.
        case shortBody(Int)
        case transportError(Int)
        case status(Int, retryAfter: String?)
    }

    private struct Scenario: Sendable {
        var payload: Data
        var faults: [String: [Fault]]
        var ignoreRange: Bool
        var requests: [String] = []
    }

    private struct Plan: Sendable {
        let payload: Data
        let fault: Fault?
        let ignoreRange: Bool
    }

    private static let scenarios = Mutex<[String: Scenario]>([:])

    static func install(host: String, payload: Data, faults: [String: [Fault]], ignoreRange: Bool) {
        scenarios.withLock {
            $0[host] = Scenario(payload: payload, faults: faults, ignoreRange: ignoreRange)
        }
    }

    static func uninstall(host: String) {
        _ = scenarios.withLock { $0.removeValue(forKey: host) }
    }

    static func requests(host: String) -> [String] {
        scenarios.withLock { $0[host]?.requests ?? [] }
    }

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host?.hasSuffix(".range-stub.invalid") ?? false
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let host = request.url?.host else { return }
        let rangeHeader = request.value(forHTTPHeaderField: "Range") ?? ""
        let plan: Plan? = Self.scenarios.withLock { all in
            guard var scenario = all[host] else { return nil }
            scenario.requests.append(rangeHeader)
            var fault: Fault?
            if var queue = scenario.faults[rangeHeader], !queue.isEmpty {
                fault = queue.removeFirst()
                scenario.faults[rangeHeader] = queue
            }
            all[host] = scenario
            return Plan(payload: scenario.payload, fault: fault, ignoreRange: scenario.ignoreRange)
        }
        guard let plan else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotFindHost))
            return
        }
        switch plan.fault {
        case .transportError(let code):
            client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: code))
            return
        case .status(let statusCode, let retryAfter):
            var headers: [String: String] = [:]
            if let retryAfter { headers["Retry-After"] = retryAfter }
            respond(statusCode: statusCode, headers: headers, body: Data("unavailable".utf8))
            return
        case .shortBody, nil:
            break
        }
        let total = Int64(plan.payload.count)
        guard !plan.ignoreRange, let bounds = Self.bounds(of: rangeHeader, total: total) else {
            respond(statusCode: 200, headers: [:], body: plan.payload)
            return
        }
        var body = plan.payload.subdata(in: Int(bounds.start)..<Int(bounds.end + 1))
        if case .shortBody(let count) = plan.fault {
            body = body.prefix(count)
        }
        respond(
            statusCode: 206,
            headers: ["Content-Range": "bytes \(bounds.start)-\(bounds.end)/\(total)"],
            body: body
        )
    }

    override func stopLoading() {}

    private func respond(statusCode: Int, headers: [String: String], body: Data) {
        guard let url = request.url,
              let response = HTTPURLResponse(
                url: url,
                statusCode: statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: headers
              ) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    private static func bounds(of header: String, total: Int64) -> (start: Int64, end: Int64)? {
        guard header.hasPrefix("bytes=") else { return nil }
        let parts = header.dropFirst("bytes=".count)
            .split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 2, let start = Int64(parts[0]), start < total else { return nil }
        let end = parts[1].isEmpty ? total - 1 : min(Int64(parts[1]) ?? (total - 1), total - 1)
        guard start <= end else { return nil }
        return (start, end)
    }
}
