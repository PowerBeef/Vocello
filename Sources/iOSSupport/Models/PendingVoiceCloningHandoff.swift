import QwenVoiceCore

/// The exact reviewed enrollment identity carried back into Studio Clone.
public struct PendingVoiceCloningHandoff: Equatable, Sendable {
    public let savedVoiceID: String
    public let wavPath: String
    public let transcript: String
    public let transcriptLoadError: String?
    /// Language spoken by the saved reference. This is conditioning metadata
    /// and is deliberately independent from the Clone draft's output language.
    public var referenceLanguage: Qwen3SupportedLanguage = .auto

    public init(
        savedVoiceID: String,
        wavPath: String,
        transcript: String,
        transcriptLoadError: String?,
        referenceLanguage: Qwen3SupportedLanguage = .auto
    ) {
        self.savedVoiceID = savedVoiceID
        self.wavPath = wavPath
        self.transcript = transcript
        self.transcriptLoadError = transcriptLoadError
        self.referenceLanguage = referenceLanguage
    }
}
