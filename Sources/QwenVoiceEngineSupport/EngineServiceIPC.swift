import Foundation
import QwenVoiceCore

public let QwenVoiceEngineServiceBundleIdentifier = "com.qwenvoice.app.engine-service"

public typealias RemoteErrorCode = QwenVoiceCore.RemoteErrorCode
public typealias RemoteErrorPayload = QwenVoiceCore.RemoteErrorPayload
public typealias EngineCapabilities = QwenVoiceCore.EngineCapabilities
public typealias EngineLifecycleState = QwenVoiceCore.EngineLifecycleState
public typealias InteractivePrefetchDiagnostics = QwenVoiceCore.InteractivePrefetchDiagnostics
public typealias EngineServiceCodec = QwenVoiceCore.QwenVoiceWireCodec

public struct EngineRequestEnvelope: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = QwenVoiceWireSchema.currentVersion
    public let schemaVersion: Int
    public let id: UUID
    public let command: EngineCommand

    public init(
        id: UUID,
        command: EngineCommand,
        schemaVersion: Int = Self.currentSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.id = id
        self.command = command
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case id
        case command
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let version = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
            ?? QwenVoiceWireSchema.legacyMissingVersion
        try QwenVoiceWireSchema.validate(version: version, codingPath: decoder.codingPath)
        self.schemaVersion = version
        self.id = try container.decode(UUID.self, forKey: .id)
        self.command = try container.decode(EngineCommand.self, forKey: .command)
    }
}

public enum EngineCommand: Codable, Equatable, Sendable {
    case initialize(appSupportDirectoryPath: String, telemetryMode: String, forcedMemoryClass: String)
    case ping
    case loadModel(id: String)
    case unloadModel
    case ensureModelLoadedIfNeeded(id: String)
    case prewarmModelIfNeeded(request: GenerationRequest)
    case prefetchInteractiveReadinessIfNeeded(
        request: GenerationRequest,
        customPrewarmDepth: String?
    )
    case ensureCloneReferencePrimed(modelID: String, reference: CloneReference)
    case cancelClonePreparationIfNeeded
    case generate(request: GenerationRequest)
    case cancelActiveGeneration
    case listPreparedVoices
    case preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    )
    /// Versioned extension of candidate preparation. The original command remains
    /// decodable so an interrupted upgrade cannot strand a pending review flow.
    case preparePreparedVoiceCandidateV2(
        name: String,
        audioPath: String,
        transcript: String?,
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata?,
        replacingVoiceID: String?
    )
    case commitPreparedVoiceCandidate(id: UUID)
    case discardPreparedVoiceCandidate(id: UUID)
    case enrollPreparedVoice(name: String, audioPath: String, transcript: String?)
    case deletePreparedVoice(id: String)
    case clearGenerationActivity
    case clearVisibleError
    /// Ask the service to exit once idle so the OS reclaims ALL engine
    /// memory (MLX heap fragmentation + Metal shader caches — things model
    /// unload never returns). The service refuses while a generation is
    /// active; the client treats the subsequent connection drop as expected
    /// (no error UI, no auto-reconnect) and lazily relaunches on next use.
    case shutdownWhenIdle
}

public struct EngineReplyEnvelope: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = QwenVoiceWireSchema.currentVersion
    public let schemaVersion: Int
    public let id: UUID
    public let reply: EngineReply

    public init(
        id: UUID,
        reply: EngineReply,
        schemaVersion: Int = Self.currentSchemaVersion
    ) {
        self.schemaVersion = schemaVersion
        self.id = id
        self.reply = reply
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case id
        case reply
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let version = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
            ?? QwenVoiceWireSchema.legacyMissingVersion
        try QwenVoiceWireSchema.validate(version: version, codingPath: decoder.codingPath)
        self.schemaVersion = version
        self.id = try container.decode(UUID.self, forKey: .id)
        self.reply = try container.decode(EngineReply.self, forKey: .reply)
    }
}

public enum EngineReply: Codable, Equatable, Sendable {
    case void
    case bool(Bool)
    case capabilities(EngineCapabilities)
    case generationResult(GenerationResult)
    case preparedVoiceCandidate(PreparedVoiceCandidate)
    case preparedVoice(PreparedVoice)
    case preparedVoices([PreparedVoice])
    case interactivePrefetchDiagnostics(InteractivePrefetchDiagnostics)
    case snapshot(TTSEngineSnapshot)
    case failure(RemoteErrorPayload)
}

public enum EngineEventEnvelope: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = QwenVoiceWireSchema.currentVersion

    case snapshot(TTSEngineSnapshot)
    case generationChunk(GenerationEvent)

    public var schemaVersion: Int {
        Self.currentSchemaVersion
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case snapshot
        case generationChunk
    }

    private enum LegacyEngineEventEnvelope: Codable {
        case snapshot(TTSEngineSnapshot)
        case generationChunk(GenerationEvent)

        var modern: EngineEventEnvelope {
            switch self {
            case .snapshot(let snapshot):
                return .snapshot(snapshot)
            case .generationChunk(let event):
                return .generationChunk(event)
            }
        }
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let version = try container.decodeIfPresent(Int.self, forKey: .schemaVersion)
            ?? QwenVoiceWireSchema.legacyMissingVersion
        try QwenVoiceWireSchema.validate(version: version, codingPath: decoder.codingPath)

        do {
            if container.contains(.snapshot) {
                self = .snapshot(try container.decode(TTSEngineSnapshot.self, forKey: .snapshot))
                return
            }
            if container.contains(.generationChunk) {
                self = .generationChunk(try container.decode(GenerationEvent.self, forKey: .generationChunk))
                return
            }
        } catch {
            if !container.contains(.schemaVersion) {
                self = try LegacyEngineEventEnvelope(from: decoder).modern
                return
            }
            throw error
        }

        if !container.contains(.schemaVersion) {
            self = try LegacyEngineEventEnvelope(from: decoder).modern
            return
        }
        throw DecodingError.dataCorrupted(
            DecodingError.Context(
                codingPath: decoder.codingPath,
                debugDescription: "Missing EngineEventEnvelope payload."
            )
        )
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(Self.currentSchemaVersion, forKey: .schemaVersion)
        switch self {
        case .snapshot(let snapshot):
            try container.encode(snapshot, forKey: .snapshot)
        case .generationChunk(let event):
            try container.encode(event, forKey: .generationChunk)
        }
    }
}

@objc public protocol QwenVoiceEngineClientEventXPCProtocol {
    func handleEvent(_ payload: Data)
}

@objc public protocol QwenVoiceEngineServiceXPCProtocol {
    func perform(_ payload: Data, withReply reply: @escaping (Data) -> Void)
}
