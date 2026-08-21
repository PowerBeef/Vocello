import Foundation

public struct IOSModelDownloadLedger: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 2

    public enum Status: String, Codable, Sendable {
        case queued
        case waitingForConnectivity
        case downloading
        case retrying
        case verifying
        case installing
        case cancelRequested
        case installed
        case failed
        case deleted
    }

    public struct VerifiedFile: Codable, Equatable, Sendable {
        public let relativePath: String
        public let expectedSize: Int64
        public let sha256: String?

        public init(relativePath: String, expectedSize: Int64, sha256: String?) {
            self.relativePath = relativePath
            self.expectedSize = expectedSize
            self.sha256 = sha256
        }
    }

    public struct Request: Codable, Equatable, Sendable {
        public let logicalRequestID: String
        public let modelID: String
        public let artifactVersion: String
        public let repo: String
        public let revision: String
        public let targetFolder: String
        public let expectedFiles: [String]
        public var verifiedFiles: [VerifiedFile]
        public var retryCount: Int
        public var receivedBytes: Int64
        public var totalBytes: Int64
        public var status: Status

        /// Whether `other` requests the exact same artifact delivery. A request
        /// whose identity differs (an artifact update) must be replaced whole,
        /// never resumed: carried-over `receivedBytes`/`verifiedFiles` from the
        /// superseded artifact are meaningless and can invalidate the ledger
        /// (a fully received larger artifact leaves `receivedBytes` above a
        /// smaller replacement's `totalBytes`).
        public func hasSameArtifactIdentity(as other: Request) -> Bool {
            artifactVersion == other.artifactVersion
                && repo == other.repo
                && revision == other.revision
                && expectedFiles == other.expectedFiles
        }

        /// Returns the durable request that should back an explicit Install/Retry action.
        ///
        /// Interrupted and failed requests retain their logical identity and verified work so
        /// URLSession restoration can resume them. Terminal tombstones do not: Delete and
        /// cancellation deliberately retain their final counters for diagnosis, and reusing
        /// those counters made a subsequent fresh install appear 100% complete before any new
        /// bytes arrived. An installed ledger whose target has disappeared is likewise a new
        /// request rather than resumable work.
        public func queuedForExplicitInstall(replacing replacement: Request) -> Request {
            guard hasSameArtifactIdentity(as: replacement),
                  ![.cancelRequested, .installed, .deleted].contains(status) else {
                return replacement
            }
            var resumed = self
            resumed.status = .queued
            resumed.totalBytes = replacement.totalBytes
            return resumed
        }

        public init(
            logicalRequestID: String,
            modelID: String,
            artifactVersion: String,
            repo: String,
            revision: String,
            targetFolder: String,
            expectedFiles: [String],
            verifiedFiles: [VerifiedFile],
            retryCount: Int,
            receivedBytes: Int64,
            totalBytes: Int64,
            status: Status
        ) {
            self.logicalRequestID = logicalRequestID
            self.modelID = modelID
            self.artifactVersion = artifactVersion
            self.repo = repo
            self.revision = revision
            self.targetFolder = targetFolder
            self.expectedFiles = expectedFiles
            self.verifiedFiles = verifiedFiles
            self.retryCount = retryCount
            self.receivedBytes = receivedBytes
            self.totalBytes = totalBytes
            self.status = status
        }
    }

    public let schemaVersion: Int
    public var requests: [Request]

    public init(requests: [Request] = []) {
        self.schemaVersion = Self.currentSchemaVersion
        self.requests = requests
    }

    public func validated() throws -> Self {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw IOSModelDownloadLedgerError.unsupportedSchema(schemaVersion)
        }
        var logicalIDs = Set<String>()
        var modelIDs = Set<String>()
        for request in requests {
            let expectedFiles = Set(request.expectedFiles)
            let verifiedPaths = request.verifiedFiles.map(\.relativePath)
            guard isSafeIdentityComponent(request.logicalRequestID),
                  isSafeIdentityComponent(request.modelID),
                  isSafeIdentityComponent(request.artifactVersion),
                  isSafeRepo(request.repo),
                  isImmutableRevision(request.revision),
                  !request.targetFolder.isEmpty,
                  request.targetFolder != ".",
                  request.targetFolder != "..",
                  !request.targetFolder.contains("/"),
                  !request.targetFolder.contains("\\"),
                  request.expectedFiles.count == expectedFiles.count,
                  request.expectedFiles.allSatisfy({ isSafeRelativePath($0) }),
                  request.verifiedFiles.allSatisfy({ isSafeRelativePath($0.relativePath) }),
                  request.verifiedFiles.allSatisfy({ $0.expectedSize > 0 }),
                  request.verifiedFiles.allSatisfy({ isLowercaseSHA256($0.sha256) }),
                  verifiedPaths.count == Set(verifiedPaths).count,
                  Set(verifiedPaths).isSubset(of: expectedFiles),
                  request.receivedBytes >= 0,
                  request.totalBytes > 0,
                  request.receivedBytes <= request.totalBytes,
                  request.retryCount >= 0,
                  logicalIDs.insert(request.logicalRequestID).inserted,
                  modelIDs.insert(request.modelID).inserted else {
                throw IOSModelDownloadLedgerError.invalidDocument
            }
        }
        return self
    }

    private func isSafeRelativePath(_ value: String) -> Bool {
        !value.isEmpty
            && value == value.trimmingCharacters(in: .whitespacesAndNewlines)
            && !value.hasPrefix("/")
            && !value.contains("\\")
            && value.removingPercentEncoding == value
            && value.split(separator: "/", omittingEmptySubsequences: false).allSatisfy {
                !$0.isEmpty && $0 != "." && $0 != ".."
            }
    }

    private func isSafeRepo(_ value: String) -> Bool {
        let components = value.split(separator: "/", omittingEmptySubsequences: false)
        return components.count == 2 && components.allSatisfy {
            !$0.isEmpty && $0 != "." && $0 != ".."
        }
    }

    private func isSafeIdentityComponent(_ value: String) -> Bool {
        !value.isEmpty
            && value == value.trimmingCharacters(in: .whitespacesAndNewlines)
            && !value.contains("/")
            && !value.contains("\\")
            && !value.contains("://")
            && !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
    }

    private func isImmutableRevision(_ value: String) -> Bool {
        value.count == 40 && value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789abcdef").contains($0)
        }
    }

    private func isLowercaseSHA256(_ value: String?) -> Bool {
        guard let value, value.count == 64 else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet(charactersIn: "0123456789abcdef").contains($0)
        }
    }
}

public enum IOSModelDownloadLedgerError: LocalizedError, Equatable, Sendable {
    case unsupportedSchema(Int)
    case invalidDocument

    public var errorDescription: String? {
        switch self {
        case .unsupportedSchema(let version):
            return "Unsupported model-download ledger schema \(version)."
        case .invalidDocument:
            return "The model-download ledger is invalid."
        }
    }
}

public struct IOSModelDownloadLedgerStore {
    public let fileURL: URL
    public let fileManager: FileManager

    public init(fileURL: URL, fileManager: FileManager = .default) {
        self.fileURL = fileURL
        self.fileManager = fileManager
    }

    public func load() throws -> IOSModelDownloadLedger {
        guard fileManager.fileExists(atPath: fileURL.path) else {
            return IOSModelDownloadLedger()
        }
        let data = try Data(contentsOf: fileURL)
        return try JSONDecoder().decode(IOSModelDownloadLedger.self, from: data).validated()
    }

    public func save(_ ledger: IOSModelDownloadLedger) throws {
        let validated = try ledger.validated()
        try fileManager.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(validated).write(to: fileURL, options: [.atomic])
    }
}
