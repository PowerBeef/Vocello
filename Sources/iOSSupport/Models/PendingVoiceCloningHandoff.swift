import QwenVoiceCore

/// The exact reviewed enrollment identity carried back into Studio Clone.
struct PendingVoiceCloningHandoff: Equatable {
    let savedVoiceID: String
    let wavPath: String
    let transcript: String
    let transcriptLoadError: String?
    /// Detected reference language (record→enroll flow); `.auto` for an existing saved voice.
    var language: Qwen3SupportedLanguage = .auto
}
