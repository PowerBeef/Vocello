import QwenVoiceCore

/// The exact reviewed enrollment identity carried back into Studio Clone.
struct PendingVoiceCloningHandoff: Equatable {
    let savedVoiceID: String
    let wavPath: String
    let transcript: String
    let transcriptLoadError: String?
    /// Language spoken by the saved reference. This is conditioning metadata
    /// and is deliberately independent from the Clone draft's output language.
    var referenceLanguage: Qwen3SupportedLanguage = .auto
}
