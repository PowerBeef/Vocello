import Foundation

/// Compact local-only diagnostics for model delivery. The allowlisted schema cannot contain
/// request URLs, filesystem paths, device identity, model prompts, or user content.
public final class ModelDownloadDiagnosticsStore: @unchecked Sendable {
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

    public init(
        directory: URL,
        mirrorDirectory: URL? = nil,
        fileManager: FileManager = .default
    ) {
        self.directory = directory
        self.mirrorDirectory = mirrorDirectory
        self.fileManager = fileManager
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
            if index >= 60 || retainedBytes + size > 5 * 1_024 * 1_024 {
                try? fileManager.removeItem(at: file)
            } else {
                retainedBytes += size
            }
        }
    }

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
