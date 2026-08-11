import Foundation
@testable import QwenVoiceCore
import XCTest

final class ModelDownloadLifecycleTests: XCTestCase {
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

    func testProgressNeverRegressesAcrossRelaunchOrRetry() {
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
        store.recordSuccess(expectedBytes: 100)

        let files = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        let objects = try files.compactMap { file -> [String: Any]? in
            let data = try Data(contentsOf: file)
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        }
        let success = try XCTUnwrap(objects.first { $0["kind"] as? String == "success" })
        XCTAssertEqual(success["wireBytes"] as? Int, 120)
        XCTAssertEqual(success["controlBytes"] as? Int, 20)
        XCTAssertEqual(success["expectedBytes"] as? Int, 100)
        XCTAssertEqual(success["duplicateBytes"] as? Int, 20)
        XCTAssertEqual(success["retryCount"] as? Int, 1)
        XCTAssertEqual(success["protocols"] as? [String], ["h3"])
        XCTAssertEqual(success["finalIntegrity"] as? Bool, true)
        XCTAssertNotNil(success["thermalState"] as? String)
    }
}
