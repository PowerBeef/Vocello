import Foundation
import HuggingFace
import MLXAudioCore

public enum TTSModelError: Error, LocalizedError, CustomStringConvertible {
    case invalidRepositoryID(String)
    case unsupportedModelType(String?)

    public var errorDescription: String? {
        description
    }

    public var description: String {
        switch self {
        case .invalidRepositoryID(let modelRepo):
            return "Invalid repository ID: \(modelRepo)"
        case .unsupportedModelType(let modelType):
            return "Unsupported model type: \(String(describing: modelType))"
        }
    }
}

public struct QwenPreparedLoadBehavior: Sendable, Equatable {
    public let trustPreparedCheckpoint: Bool
    public let preparedDirectoryAlreadyValidated: Bool
    public let loadSpeakerEncoder: Bool?
    public let loadSpeechTokenizerEncoder: Bool?
    public let skipSpeechTokenizerEval: Bool
    /// Host-attested content identity for the speech-tokenizer component
    /// (weights digest + config digest from the trusted-checkpoint marker).
    /// Enables phase 9 in-memory reuse across model switches; nil disables
    /// residency for this load.
    public let speechTokenizerContentIdentity: String?

    public init(
        trustPreparedCheckpoint: Bool = false,
        preparedDirectoryAlreadyValidated: Bool = false,
        loadSpeakerEncoder: Bool? = nil,
        loadSpeechTokenizerEncoder: Bool? = nil,
        skipSpeechTokenizerEval: Bool = false,
        speechTokenizerContentIdentity: String? = nil
    ) {
        self.trustPreparedCheckpoint = trustPreparedCheckpoint
        self.preparedDirectoryAlreadyValidated = preparedDirectoryAlreadyValidated
        self.loadSpeakerEncoder = loadSpeakerEncoder
        self.loadSpeechTokenizerEncoder = loadSpeechTokenizerEncoder
        self.skipSpeechTokenizerEval = skipSpeechTokenizerEval
        self.speechTokenizerContentIdentity = speechTokenizerContentIdentity
    }

    public static let fullCapabilities = QwenPreparedLoadBehavior()
    public static let streamingOnly = QwenPreparedLoadBehavior(
        loadSpeakerEncoder: false,
        loadSpeechTokenizerEncoder: false,
        skipSpeechTokenizerEval: true
    )
}

public enum TTS {
    public static func preparePreparedDirectory(
        _ preparedDirectory: URL,
        modelRepo: String,
        modelType: String?
    ) throws {
        let resolvedType = normalizedModelType(modelType) ?? inferModelType(from: modelRepo)
        guard resolvedType == "qwen3_tts" else {
            throw TTSModelError.unsupportedModelType(modelType ?? resolvedType)
        }
        try Qwen3TTSModel.preparePreparedDirectory(preparedDirectory)
    }

    public static func loadModel(
        modelRepo: String,
        textProcessor _: TextProcessor? = nil,
        hfToken: String? = nil,
        cache: HubCache = .default,
        revision: String = "main",
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> SpeechGenerationModel {
        guard let repoID = Repo.ID(rawValue: modelRepo) else {
            throw TTSModelError.invalidRepositoryID(modelRepo)
        }

        let modelType = try await ModelUtils.resolveModelType(
            repoID: repoID,
            revision: revision,
            hfToken: hfToken,
            cache: cache
        )
        return try await loadModel(
            modelRepo: modelRepo,
            modelType: modelType,
            cache: cache,
            revision: revision,
            isolation: isolation
        )
    }

    public static func loadModel(
        fromPreparedDirectory preparedDirectory: URL,
        modelRepo: String,
        modelType: String?,
        trustPreparedCheckpoint: Bool = false,
        qwenPreparedLoadBehavior: QwenPreparedLoadBehavior? = nil,
        diagnosticEventSink: (@Sendable (String, [String: String]) async -> Void)? = nil,
        textProcessor _: TextProcessor? = nil,
        cache: HubCache = .default,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> SpeechGenerationModel {
        let resolvedType = normalizedModelType(modelType) ?? inferModelType(from: modelRepo)
        guard let resolvedType, resolvedType == "qwen3_tts" else {
            throw TTSModelError.unsupportedModelType(modelType ?? resolvedType)
        }

        if let diagnosticEventSink {
            await diagnosticEventSink(
                "tts-load-before-qwen-from-prepared-directory",
                [
                    "modelRepo": modelRepo,
                    "modelType": resolvedType,
                    "preparedDirectory": preparedDirectory.path,
                    "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                    "preparedDirectoryAlreadyValidated": (
                        qwenPreparedLoadBehavior?.preparedDirectoryAlreadyValidated ?? false
                    ) ? "true" : "false",
                ]
            )
        }
        let model = try await Qwen3TTSModel.fromPreparedDirectory(
            preparedDirectory,
            modelRepo: modelRepo,
            loadBehavior: qwenPreparedLoadBehavior ?? QwenPreparedLoadBehavior(
                trustPreparedCheckpoint: trustPreparedCheckpoint
            ),
            diagnosticEventSink: diagnosticEventSink,
            isolation: isolation
        )
        if let diagnosticEventSink {
            await diagnosticEventSink(
                "tts-load-after-qwen-from-prepared-directory",
                [
                    "modelRepo": modelRepo,
                    "modelType": resolvedType,
                    "preparedDirectory": preparedDirectory.path,
                    "trustPreparedCheckpoint": trustPreparedCheckpoint ? "true" : "false",
                    "preparedDirectoryAlreadyValidated": (
                        qwenPreparedLoadBehavior?.preparedDirectoryAlreadyValidated ?? false
                    ) ? "true" : "false",
                ]
            )
        }
        return model
    }

    public static func loadModel(
        modelRepo: String,
        modelType: String?,
        textProcessor _: TextProcessor? = nil,
        cache: HubCache = .default,
        revision: String = "main",
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> SpeechGenerationModel {
        let resolvedType = normalizedModelType(modelType) ?? inferModelType(from: modelRepo)
        guard let resolvedType, resolvedType == "qwen3_tts" else {
            throw TTSModelError.unsupportedModelType(modelType ?? resolvedType)
        }
        return try await Qwen3TTSModel.fromPretrained(
            modelRepo,
            cache: cache,
            revision: revision,
            isolation: isolation
        )
    }

    private static func normalizedModelType(_ modelType: String?) -> String? {
        guard let modelType else { return nil }
        let trimmed = modelType.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return trimmed.lowercased().replacingOccurrences(of: "-", with: "_")
    }

    static func resolveModelType(modelRepo: String, modelType: String? = nil) -> String? {
        normalizedModelType(modelType) ?? inferModelType(from: modelRepo)
    }

    private static func inferModelType(from modelRepo: String) -> String? {
        let lower = modelRepo.lowercased()
        if lower.contains("qwen3_tts") || lower.contains("qwen3-tts") {
            return "qwen3_tts"
        }
        return nil
    }
}

@available(*, deprecated, renamed: "TTSModelError")
public typealias TTSModelUtilsError = TTSModelError

@available(*, deprecated, renamed: "TTS")
public typealias TTSModelUtils = TTS
