import Foundation

/// The two voice-cloning operations that need the user's recorded consent.
public enum VoiceCloningOperation: String, CaseIterable, Hashable, Sendable {
    /// Any generation conditioned on a reference voice: Studio Voice Cloning takes,
    /// line batch, long-form segments and their regeneration, and the CLI.
    case generation
    /// Turning reference audio into a saved voice (candidate preparation or direct
    /// enrollment), whatever produced the audio.
    case enrollment
}

/// Typed refusal raised when a voice-cloning operation runs without recorded consent.
/// It carries presentation copy chosen by the host (the apps' localized catalog copy,
/// or the CLI's flag guidance), so it can be shown as-is.
public struct VoiceCloningConsentRequiredError: LocalizedError, CustomStringConvertible, Hashable, Sendable {
    public let operation: VoiceCloningOperation
    public let message: String

    public init(operation: VoiceCloningOperation, message: String) {
        self.operation = operation
        self.message = message
    }

    public var errorDescription: String? { message }
    public var description: String { message }
}

/// PA-17: voice-cloning consent is enforced below the views.
///
/// One immutable admission decision built from the consent the host recorded: the
/// visible Settings acknowledgment in the apps (`recordedConsentDefaultsKey`), or the
/// explicit per-invocation `--confirm-consent` flag in the CLI. The apps apply it in
/// `AnyTTSEngineBackend` (under `TTSEngineStore`) and the CLI in `CLIRuntime`, so the
/// refusal no longer depends on a screen remembering to check.
public struct VoiceCloningConsentPolicy: Hashable, Sendable {
    /// The `UserDefaults` key both apps' Settings toggle writes (macOS through
    /// `AppDefaults.store`, iOS through `.standard`).
    public static let recordedConsentDefaultsKey = "vocello.voiceCloningConsent.v1"

    /// Refusal copy per operation. The apps pass localized catalog copy; the default is
    /// the English fallback used where no interface language exists.
    public struct RefusalCopy: Hashable, Sendable {
        public let generation: String
        public let enrollment: String

        public init(generation: String, enrollment: String) {
            self.generation = generation
            self.enrollment = enrollment
        }

        public func message(for operation: VoiceCloningOperation) -> String {
            switch operation {
            case .generation: generation
            case .enrollment: enrollment
            }
        }

        public static let english = RefusalCopy(
            generation: "Voice cloning needs your consent: confirm you own or have permission to clone the voices you use before generating.",
            enrollment: "Saving a voice needs your voice-cloning consent: confirm you own or have permission to clone the voices you use first."
        )
    }

    public let isConsentRecorded: Bool
    public let refusalCopy: RefusalCopy

    public init(isConsentRecorded: Bool, refusalCopy: RefusalCopy = .english) {
        self.isConsentRecorded = isConsentRecorded
        self.refusalCopy = refusalCopy
    }

    /// Reads the recorded acknowledgment. A missing value is no consent.
    public init(defaults: UserDefaults, refusalCopy: RefusalCopy = .english) {
        self.init(
            isConsentRecorded: defaults.bool(forKey: Self.recordedConsentDefaultsKey),
            refusalCopy: refusalCopy
        )
    }

    /// True when the mode generates from a reference voice.
    public static func requiresConsent(_ mode: GenerationMode) -> Bool {
        mode == .clone
    }

    /// True when the request is conditioned on a reference voice, judged by both its
    /// mode and its payload so a mismatched request cannot slip through.
    public static func requiresConsent(_ request: GenerationRequest) -> Bool {
        if requiresConsent(request.mode) { return true }
        if case .clone = request.payload { return true }
        return false
    }

    /// Admits the operation only when consent is recorded.
    public func admit(_ operation: VoiceCloningOperation) throws(VoiceCloningConsentRequiredError) {
        guard isConsentRecorded else {
            throw VoiceCloningConsentRequiredError(
                operation: operation,
                message: refusalCopy.message(for: operation)
            )
        }
    }

    /// Admits a generation request: Built-in Voice and Voice Design pass unconditionally,
    /// anything conditioned on a reference voice needs recorded consent.
    public func admitGeneration(_ request: GenerationRequest) throws(VoiceCloningConsentRequiredError) {
        guard Self.requiresConsent(request) else { return }
        try admit(.generation)
    }

    /// Admits a generation mode before a request exists (CLI preflight).
    public func admitGeneration(mode: GenerationMode) throws(VoiceCloningConsentRequiredError) {
        guard Self.requiresConsent(mode) else { return }
        try admit(.generation)
    }
}
