import Foundation

/// Compact local-only diagnostics for model delivery. The allowlisted schema cannot contain
/// request URLs, filesystem paths, device identity, model prompts, or user content.
public final class ModelDownloadDiagnosticsStore: @unchecked Sendable {
    /// Schema-versioned, privacy-safe event used by the model-management diagnostic lane. The
    /// schema deliberately has no URL or filesystem-path field.
    public struct DeliveryEvent: Codable, Equatable, Sendable {
        public let schemaVersion: Int
        public let runID: String
        public let processInstanceID: String
        public let sequence: UInt64
        public let capturedAtUTC: String
        public let uptimeSeconds: Double
        public let layer: String
        public let event: String
        public let modelID: String?
        public let logicalRequestID: String?
        public let operationGeneration: UInt64?
        public let artifactVersion: String?
        public let phase: String?
        public let durableBytes: Int64?
        public let totalBytes: Int64?
        public let expectedFileCount: Int?
        public let verifiedFileCount: Int?
        public let taskCount: Int?
        public let taskID: Int?
        public let stagingFileCount: Int?
        public let stagingBytes: Int64?
        public let targetAvailable: Bool?
        public let ledgerStatus: String?
        public let outcome: String?
        public let errorClassification: String?
        public let errorMessage: String?
    }

    private struct Record: Codable, Sendable {
        let schemaVersion: Int
        let capturedAtUTC: String
        let kind: String
        let relativePath: String?
        let protocolName: String?
        let redirectCount: Int?
        let reusedConnection: Bool?
        let cellular: Bool?
        let constrained: Bool?
        let expensive: Bool?
        let transferredBytes: Int64?
        let durationSeconds: Double?
        let classification: String?
        let message: String?
        let phase: String?
        let downloadedBytes: Int64?
        let totalBytes: Int64?
        let bytesPerSecond: Int64?
        let etaSeconds: Double?
        let retryCount: Int?
        let networkSeconds: Double?
        let verificationSeconds: Double?
        let installationSeconds: Double?
        let expectedBytes: Int64?
        let wireBytes: Int64?
        let controlBytes: Int64?
        let duplicateBytes: Int64?
        let protocols: [String]?
        let thermalState: String?
        let finalIntegrity: Bool?

        init(
            capturedAtUTC: String,
            kind: String,
            relativePath: String? = nil,
            protocolName: String? = nil,
            redirectCount: Int? = nil,
            reusedConnection: Bool? = nil,
            cellular: Bool? = nil,
            constrained: Bool? = nil,
            expensive: Bool? = nil,
            transferredBytes: Int64? = nil,
            durationSeconds: Double? = nil,
            classification: String? = nil,
            message: String? = nil,
            phase: String? = nil,
            downloadedBytes: Int64? = nil,
            totalBytes: Int64? = nil,
            bytesPerSecond: Int64? = nil,
            etaSeconds: Double? = nil,
            retryCount: Int? = nil,
            networkSeconds: Double? = nil,
            verificationSeconds: Double? = nil,
            installationSeconds: Double? = nil,
            expectedBytes: Int64? = nil,
            wireBytes: Int64? = nil,
            controlBytes: Int64? = nil,
            duplicateBytes: Int64? = nil,
            protocols: [String]? = nil,
            thermalState: String? = nil,
            finalIntegrity: Bool? = nil
        ) {
            self.schemaVersion = 1
            self.capturedAtUTC = capturedAtUTC
            self.kind = kind
            self.relativePath = relativePath
            self.protocolName = protocolName
            self.redirectCount = redirectCount
            self.reusedConnection = reusedConnection
            self.cellular = cellular
            self.constrained = constrained
            self.expensive = expensive
            self.transferredBytes = transferredBytes
            self.durationSeconds = durationSeconds
            self.classification = classification
            self.message = message
            self.phase = phase
            self.downloadedBytes = downloadedBytes
            self.totalBytes = totalBytes
            self.bytesPerSecond = bytesPerSecond
            self.etaSeconds = etaSeconds
            self.retryCount = retryCount
            self.networkSeconds = networkSeconds
            self.verificationSeconds = verificationSeconds
            self.installationSeconds = installationSeconds
            self.expectedBytes = expectedBytes
            self.wireBytes = wireBytes
            self.controlBytes = controlBytes
            self.duplicateBytes = duplicateBytes
            self.protocols = protocols
            self.thermalState = thermalState
            self.finalIntegrity = finalIntegrity
        }
    }

    public let directory: URL
    /// Optional second root receiving an identical copy of every record. iOS
    /// passes its devicectl-pullable caches mirror here because the App Group
    /// primary cannot be pulled for triage (see `IOSPullableDiagnosticsMirror`).
    public let mirrorDirectory: URL?
    private let fileManager: FileManager
    private let lock = NSLock()
    private var runStartedAt: Date?
    private var verificationStartedAt: Date?
    private var installationStartedAt: Date?
    private var lastPhase: String?
    private var maximumRetryCount = 0
    private var accumulatedWireBytes: Int64 = 0
    private var accumulatedControlBytes: Int64 = 0
    private var observedProtocols: Set<String> = []
    private var terminalRecorded = false
    private let processInstanceID = UUID().uuidString.lowercased()
    private var traceRunID: String?
    private var traceSequence: UInt64 = 0

    public convenience init(
        directory: URL,
        mirrorDirectory: URL? = nil,
        fileManager: FileManager = .default
    ) {
        self.init(
            directory: directory,
            mirrorDirectory: mirrorDirectory,
            fileManager: fileManager,
            diagnosticTraceRunID: RuntimeDebugGate.value(
                for: "QVOICE_IOS_MODEL_MANAGEMENT_RUN_ID"
            )
        )
    }

    init(
        directory: URL,
        mirrorDirectory: URL? = nil,
        fileManager: FileManager = .default,
        diagnosticTraceRunID: String?
    ) {
        self.directory = directory
        self.mirrorDirectory = mirrorDirectory
        self.fileManager = fileManager
        self.traceRunID = Self.safeIdentifier(diagnosticTraceRunID)
    }

    /// Records one correlated lifecycle event only when the registered, debug-gated run ID is
    /// present. Diagnostics are best-effort and can never fail model delivery.
    public func recordEvent(
        layer: String,
        event: String,
        modelID: String? = nil,
        logicalRequestID: String? = nil,
        operationGeneration: UInt64? = nil,
        artifactVersion: String? = nil,
        phase: String? = nil,
        durableBytes: Int64? = nil,
        totalBytes: Int64? = nil,
        expectedFileCount: Int? = nil,
        verifiedFileCount: Int? = nil,
        taskCount: Int? = nil,
        taskID: Int? = nil,
        stagingFileCount: Int? = nil,
        stagingBytes: Int64? = nil,
        targetAvailable: Bool? = nil,
        ledgerStatus: String? = nil,
        outcome: String? = nil,
        errorClassification: String? = nil,
        errorMessage: String? = nil
    ) {
        lock.lock()
        guard let runID = traceRunID else {
            lock.unlock()
            return
        }
        traceSequence &+= 1
        let sequence = traceSequence
        lock.unlock()

        let record = DeliveryEvent(
            schemaVersion: 1,
            runID: runID,
            processInstanceID: processInstanceID,
            sequence: sequence,
            capturedAtUTC: ISO8601DateFormatter().string(from: Date()),
            uptimeSeconds: ProcessInfo.processInfo.systemUptime,
            layer: Self.safeIdentifier(layer) ?? "unknown",
            event: Self.safeIdentifier(event) ?? "unknown",
            modelID: Self.safeIdentifier(modelID),
            logicalRequestID: Self.safeIdentifier(logicalRequestID),
            operationGeneration: operationGeneration,
            artifactVersion: Self.safeIdentifier(artifactVersion),
            phase: Self.safeIdentifier(phase),
            durableBytes: durableBytes.map { max(0, $0) },
            totalBytes: totalBytes.map { max(0, $0) },
            expectedFileCount: expectedFileCount.map { max(0, $0) },
            verifiedFileCount: verifiedFileCount.map { max(0, $0) },
            taskCount: taskCount.map { max(0, $0) },
            taskID: taskID.map { max(0, $0) },
            stagingFileCount: stagingFileCount.map { max(0, $0) },
            stagingBytes: stagingBytes.map { max(0, $0) },
            targetAvailable: targetAvailable,
            ledgerStatus: Self.safeIdentifier(ledgerStatus),
            outcome: Self.safeIdentifier(outcome),
            errorClassification: Self.safeIdentifier(errorClassification),
            errorMessage: errorMessage.map(sanitizeMessage)
        )
        persistTrace(record)
    }

    public func record(metrics: HuggingFaceDownloader.TransferMetrics) {
        let relativePath = sanitizeRelativePath(metrics.relativePath)
        lock.lock()
        if relativePath == nil {
            // Catalog and other control-plane requests are useful network evidence, but are not
            // model payload and therefore must not inflate duplicate artifact bytes.
            accumulatedControlBytes += max(0, metrics.transferredBytes)
        } else {
            accumulatedWireBytes += max(0, metrics.transferredBytes)
        }
        if let protocolName = sanitizeToken(metrics.protocolName), !protocolName.isEmpty {
            observedProtocols.insert(protocolName)
        }
        lock.unlock()
        persist(Record(
            capturedAtUTC: ISO8601DateFormatter().string(from: Date()),
            kind: "task-metrics",
            relativePath: relativePath,
            protocolName: sanitizeToken(metrics.protocolName),
            redirectCount: metrics.redirectCount,
            reusedConnection: metrics.reusedConnection,
            cellular: metrics.cellular,
            constrained: metrics.constrained,
            expensive: metrics.expensive,
            transferredBytes: metrics.transferredBytes,
            durationSeconds: metrics.durationSeconds
        ))
    }

    /// Persist only phase transitions, while retaining exact byte updates in the UI callback.
    /// The resulting compact records make network, verification, and installation timing
    /// independently auditable without retaining raw requests or model payloads.
    public func record(progress: HuggingFaceDownloader.RepositoryProgress) {
        let now = Date()
        let phase = progress.phase.rawValue
        lock.lock()
        if terminalRecorded {
            resetRunStateLocked()
        }
        if runStartedAt == nil { runStartedAt = now }
        maximumRetryCount = max(maximumRetryCount, progress.retryCount)
        guard lastPhase != phase else {
            lock.unlock()
            return
        }
        lastPhase = phase
        if progress.phase == .verifying { verificationStartedAt = now }
        if progress.phase == .installing { installationStartedAt = now }
        lock.unlock()

        persist(Record(
            capturedAtUTC: ISO8601DateFormatter().string(from: now),
            kind: "phase",
            phase: phase,
            downloadedBytes: progress.downloadedBytes,
            totalBytes: progress.totalBytes,
            bytesPerSecond: progress.bytesPerSecond,
            etaSeconds: progress.estimatedSecondsRemaining,
            retryCount: progress.retryCount
        ))
    }

    public func recordSuccess(expectedBytes: Int64) {
        let now = Date()
        lock.lock()
        let networkSeconds = verificationStartedAt.flatMap { start in
            runStartedAt.map { max(0, start.timeIntervalSince($0)) }
        }
        let verificationSeconds = installationStartedAt.flatMap { end in
            verificationStartedAt.map { max(0, end.timeIntervalSince($0)) }
        }
        let installationSeconds = installationStartedAt.map { max(0, now.timeIntervalSince($0)) }
        let wireBytes = accumulatedWireBytes
        let controlBytes = accumulatedControlBytes
        let retryCount = maximumRetryCount
        let protocols = observedProtocols.sorted()
        terminalRecorded = true
        lock.unlock()

        persist(Record(
            capturedAtUTC: ISO8601DateFormatter().string(from: now),
            kind: "success",
            retryCount: retryCount,
            networkSeconds: networkSeconds,
            verificationSeconds: verificationSeconds,
            installationSeconds: installationSeconds,
            expectedBytes: expectedBytes,
            wireBytes: wireBytes,
            controlBytes: controlBytes,
            duplicateBytes: max(0, wireBytes - max(0, expectedBytes)),
            protocols: protocols,
            thermalState: thermalStateToken(),
            finalIntegrity: true
        ))
    }

    public func recordFailure(classification: String, message: String) {
        persist(Record(
            capturedAtUTC: ISO8601DateFormatter().string(from: Date()),
            kind: "failure",
            classification: sanitizeToken(classification),
            message: sanitizeMessage(message)
        ))
    }

    private func persist(_ record: Record) {
        lock.lock()
        defer { lock.unlock() }
        let fileName = "attempt-\(UUID().uuidString).json"
        for root in [directory, mirrorDirectory].compactMap({ $0 }) {
            do {
                try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.sortedKeys]
                let data = try encoder.encode(record)
                try data.write(
                    to: root.appendingPathComponent(fileName),
                    options: [.atomic]
                )
                try prune(in: root)
            } catch {
                // Diagnostics must never interfere with model delivery.
            }
        }
    }

    private func persistTrace(_ record: DeliveryEvent) {
        lock.lock()
        defer { lock.unlock() }
        let sequenceToken = String(format: "%020llu", record.sequence)
        let fileName = "event-\(record.processInstanceID)-\(sequenceToken).json"
        for root in [directory, mirrorDirectory].compactMap({ $0 }) {
            let traceRoot = root.appendingPathComponent("trace", isDirectory: true)
            do {
                try fileManager.createDirectory(at: traceRoot, withIntermediateDirectories: true)
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.sortedKeys]
                try encoder.encode(record).write(
                    to: traceRoot.appendingPathComponent(fileName),
                    options: [.atomic]
                )
                try pruneTrace(in: traceRoot)
            } catch {
                // Diagnostics must never interfere with model delivery.
            }
        }
    }

    private func pruneTrace(in directory: URL) throws {
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey]
        let files = try fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ).filter { $0.pathExtension == "json" }.sorted {
            let lhs = (try? $0.resourceValues(forKeys: keys).contentModificationDate) ?? .distantPast
            let rhs = (try? $1.resourceValues(forKeys: keys).contentModificationDate) ?? .distantPast
            return lhs > rhs
        }
        var retainedBytes: Int64 = 0
        for (index, file) in files.enumerated() {
            let size = Int64((try? file.resourceValues(forKeys: keys).fileSize) ?? 0)
            if index >= Self.maxRetainedTraceEvents
                || retainedBytes + size > Self.maxRetainedTraceBytes {
                try? fileManager.removeItem(at: file)
            } else {
                retainedBytes += size
            }
        }
    }

    private func prune(in directory: URL) throws {
        let keys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey]
        let files = try fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles]
        ).filter { $0.pathExtension == "json" }.sorted {
            let lhs = (try? $0.resourceValues(forKeys: keys).contentModificationDate) ?? .distantPast
            let rhs = (try? $1.resourceValues(forKeys: keys).contentModificationDate) ?? .distantPast
            return lhs > rhs
        }

        var retainedBytes: Int64 = 0
        for (index, file) in files.enumerated() {
            let size = Int64((try? file.resourceValues(forKeys: keys).fileSize) ?? 0)
            if index >= Self.maxRetainedRecords || retainedBytes + size > 5 * 1_024 * 1_024 {
                try? fileManager.removeItem(at: file)
            } else {
                retainedBytes += size
            }
        }
    }

    /// Sized for a full chunked three-artifact lifecycle: 128 MiB ranges over the Speed
    /// artifacts emit one task-metrics record per chunk (~35 for the full-wire artifact
    /// alone), plus per-file records, phase samples, and the three success summaries —
    /// about 120 records. The prior cap of 60 silently pruned the first artifact's
    /// metrics before the model-download lane could validate its byte-exact wire
    /// accounting. The paired validator bound lives in scripts/ui_test.sh and must move
    /// with this constant.
    static let maxRetainedRecords = 200
    /// One worst-case one-hour diagnostic transfer persists the durable ledger twice per second,
    /// plus five-second heartbeats and bounded task events. Retain that complete causality chain
    /// without allowing repeated failed runs to grow without limit.
    static let maxRetainedTraceEvents = 15_000
    static let maxRetainedTraceBytes: Int64 = 40 * 1_024 * 1_024

    private func sanitizeRelativePath(_ value: String?) -> String? {
        guard let value,
              !value.isEmpty,
              !value.hasPrefix("/"),
              !value.contains(":"),
              !value.split(separator: "/").contains("..") else { return nil }
        return String(value.prefix(300))
    }

    private func sanitizeToken(_ value: String?) -> String? {
        guard let value else { return nil }
        let allowed = value.unicodeScalars.filter {
            CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._-")).contains($0)
        }
        return String(String.UnicodeScalarView(allowed).prefix(100))
    }

    private static func safeIdentifier(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 160 else { return nil }
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._-"))
        guard trimmed.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return nil }
        return trimmed
    }

    private func sanitizeMessage(_ value: String) -> String {
        let withoutURLs = value.replacingOccurrences(
            of: #"[A-Za-z][A-Za-z0-9+.-]*://\S+"#,
            with: "<redacted-url>",
            options: .regularExpression
        )
        let withoutPaths = withoutURLs.replacingOccurrences(
            of: #"/(?:Users|private|var|tmp)/\S+"#,
            with: "<redacted-path>",
            options: .regularExpression
        )
        return String(withoutPaths.prefix(500))
    }

    private func resetRunStateLocked() {
        runStartedAt = nil
        verificationStartedAt = nil
        installationStartedAt = nil
        lastPhase = nil
        maximumRetryCount = 0
        accumulatedWireBytes = 0
        accumulatedControlBytes = 0
        observedProtocols.removeAll()
        terminalRecorded = false
    }

    private func thermalStateToken() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }
}
