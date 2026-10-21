import QwenVoiceCore

/// PA-17: how the CLI records voice-cloning consent.
///
/// A command-line tool has no Settings screen, and it must not silently inherit the
/// apps' acknowledgment, so each invocation that clones or saves a voice records the
/// user's consent explicitly with the bare `--confirm-consent` flag. Without it,
/// `CLIRuntime` refuses the operation through the shared core policy before any model
/// work. The flag is accepted and ignored on other runs, so scripts may pass it
/// uniformly.
public enum CLIVoiceCloningConsent {
    /// Parsed as a bare flag (`--confirm-consent`), never as `--confirm-consent <value>`.
    static let flagName = "confirm-consent"

    static let refusalCopy = VoiceCloningConsentPolicy.RefusalCopy(
        generation: "voice cloning needs your consent: pass --confirm-consent to confirm you own or have permission to clone this voice",
        enrollment: "saving a voice needs your consent: pass --confirm-consent to confirm you own or have permission to clone this voice"
    )

    static func policy(confirmed: Bool) -> VoiceCloningConsentPolicy {
        VoiceCloningConsentPolicy(isConsentRecorded: confirmed, refusalCopy: refusalCopy)
    }

    /// The invocation's recorded consent. The flag is bare: the parser refuses a
    /// value (`--confirm-consent=yes`) instead of silently reading it as no consent.
    public static func policy(from args: Args) throws -> VoiceCloningConsentPolicy {
        policy(confirmed: args.flag(flagName))
    }

    /// Fail closed for any caller that does not pass the invocation's flag.
    public static let notConfirmed = policy(confirmed: false)
}
