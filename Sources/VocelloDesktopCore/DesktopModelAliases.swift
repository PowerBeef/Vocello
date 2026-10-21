import QwenVoiceCore
import Synchronization

/// The apps' name for a model descriptor, for the app files compiled here by
/// path (the app's own `TTSModel` files read the bundled contract, which the
/// CLI resolves itself).
typealias TTSModel = ModelDescriptor

extension ModelDescriptor {
    /// The long-form runner's fallback speaker: the registry's default, which
    /// `DesktopLongFormProject` configures (it always names the speaker anyway).
    static var defaultSpeaker: String { DesktopSpeakerDefault.id.withLock { $0 } }
}

enum DesktopSpeakerDefault {
    static let id = Mutex("")
}
