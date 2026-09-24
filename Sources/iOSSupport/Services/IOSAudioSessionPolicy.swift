import Foundation

/// Why a caller needs the iOS audio session (PA-21, AUD-02).
///
/// Every category or activation change in the iOS app goes through
/// `IOSAudioSessionOwner`, which applies the steps this ledger decides. The
/// session is configured for playback at launch but only becomes active when
/// playback or recording actually starts, so opening or returning to the app
/// never interrupts another app's audio.
enum IOSAudioSessionUse: String, Equatable, Sendable {
    /// The shared Studio player (final file or live preview). Held until the
    /// app leaves the foreground, so a paused take resumes without another
    /// activation and closing a preview never silences it.
    case sharedPlayback
    /// A player with its own `AVAudioPlayer`: the player sheet, the inline
    /// card replaying on its own, or a recorded clip under review.
    case playback
    /// A bundled speaker sample in the voice picker; it mixes with other apps.
    case mixablePreview
    /// Reference-clip capture.
    case recording
}

/// The category, options and mode the session is set to.
struct IOSAudioSessionConfiguration: Equatable, Sendable {
    enum Category: String, Equatable, Sendable {
        case playback
        case record
    }

    let category: Category
    let mixesWithOthers: Bool
    /// `.measurement` mode (no automatic gain or voice processing) for capture.
    let usesMeasurementMode: Bool

    static let playback = IOSAudioSessionConfiguration(
        category: .playback, mixesWithOthers: false, usesMeasurementMode: false
    )
    static let mixablePlayback = IOSAudioSessionConfiguration(
        category: .playback, mixesWithOthers: true, usesMeasurementMode: false
    )
    static let recording = IOSAudioSessionConfiguration(
        category: .record, mixesWithOthers: false, usesMeasurementMode: true
    )

    /// Between claims the session keeps `.playback` without being active: a
    /// player that activates implicitly is not silenced by the Ring/Silent
    /// switch, and nothing interrupts other apps until playback starts.
    static let base = playback

    init(category: Category, mixesWithOthers: Bool, usesMeasurementMode: Bool) {
        self.category = category
        self.mixesWithOthers = mixesWithOthers
        self.usesMeasurementMode = usesMeasurementMode
    }

    init(for use: IOSAudioSessionUse) {
        switch use {
        case .sharedPlayback, .playback: self = .playback
        case .mixablePreview: self = .mixablePlayback
        case .recording: self = .recording
        }
    }
}

/// One physical change the owner applies, in order.
enum IOSAudioSessionStep: Equatable, Sendable {
    case configure(IOSAudioSessionConfiguration)
    case activate
    /// Always with `.notifyOthersOnDeactivation`, so other apps can resume.
    case deactivate
}

/// A caller's hold on the session. Releasing an unknown or already released
/// claim changes nothing, so a late release can never silence a newer holder.
struct IOSAudioSessionClaim: Hashable, Sendable {
    let rawValue: UInt64
}

/// Decides the audio-session steps for claims and releases (PA-21, AUD-02).
///
/// - Recording outranks playback while it is held; otherwise the newest claim
///   decides the configuration.
/// - The session deactivates only when the last claim is released, and the
///   base configuration is restored after any other configuration.
/// - Leaving the foreground drops every claim and deactivates the session;
///   until the app is active again a claim changes nothing, so a late live
///   chunk or an interruption ending in the background cannot reactivate it.
struct IOSAudioSessionLedger: Equatable, Sendable {
    private struct Holder: Equatable, Sendable {
        let claim: IOSAudioSessionClaim
        var use: IOSAudioSessionUse
    }

    private var holders: [Holder] = []
    private(set) var appliedConfiguration: IOSAudioSessionConfiguration?
    private(set) var isActive = false
    /// Set by `enterBackground`, cleared by `enterForeground`.
    private(set) var isInBackground = false

    init() {}

    var heldClaims: [IOSAudioSessionClaim] { holders.map(\.claim) }

    func holds(_ claim: IOSAudioSessionClaim) -> Bool {
        holders.contains { $0.claim == claim }
    }

    /// The configuration the current holders need.
    var requiredConfiguration: IOSAudioSessionConfiguration {
        if holders.contains(where: { $0.use == .recording }) {
            return .recording
        }
        guard let newest = holders.last else { return .base }
        return IOSAudioSessionConfiguration(for: newest.use)
    }

    /// Launch: set the base configuration without activating the session.
    mutating func prepareForLaunch() -> [IOSAudioSessionStep] {
        guard holders.isEmpty, appliedConfiguration != .base else { return [] }
        appliedConfiguration = .base
        return [.configure(.base)]
    }

    /// Records `claim` for `use` (a held claim becomes the newest again) and
    /// returns the steps that make the session ready for it. In the background
    /// the claim is not recorded and nothing changes: the session stays handed
    /// back until the app is active again.
    mutating func claim(
        _ claim: IOSAudioSessionClaim,
        for use: IOSAudioSessionUse
    ) -> [IOSAudioSessionStep] {
        guard !isInBackground else { return [] }
        holders.removeAll { $0.claim == claim }
        holders.append(Holder(claim: claim, use: use))
        var steps: [IOSAudioSessionStep] = []
        let required = requiredConfiguration
        if appliedConfiguration != required {
            appliedConfiguration = required
            steps.append(.configure(required))
        }
        if !isActive {
            isActive = true
            steps.append(.activate)
        }
        return steps
    }

    /// Releases `claim`. Unknown claims change nothing.
    mutating func release(_ claim: IOSAudioSessionClaim) -> [IOSAudioSessionStep] {
        guard holds(claim) else { return [] }
        holders.removeAll { $0.claim == claim }
        guard holders.isEmpty else {
            let required = requiredConfiguration
            guard appliedConfiguration != required else { return [] }
            appliedConfiguration = required
            return [.configure(required)]
        }
        return releaseSession()
    }

    /// Applying `steps`, the steps returned for `claim`, failed. The claim is
    /// dropped so it cannot keep the session configured for it. The session is
    /// inactive only when those steps were to activate it: a failed
    /// configuration while another holder keeps the session active leaves it
    /// active, so the last release still deactivates it.
    mutating func activationFailed(
        _ claim: IOSAudioSessionClaim,
        steps: [IOSAudioSessionStep]
    ) -> [IOSAudioSessionStep] {
        if steps.contains(.activate) {
            isActive = false
        }
        guard holds(claim) else { return [] }
        holders.removeAll { $0.claim == claim }
        let required = requiredConfiguration
        guard appliedConfiguration != required else { return [] }
        appliedConfiguration = required
        return [.configure(required)]
    }

    /// Leaving the foreground: no background-audio mode is declared, so every
    /// claim ends and the session is handed back to other apps. Deactivation is
    /// unconditional because a player may have activated the session implicitly.
    mutating func enterBackground() -> [IOSAudioSessionStep] {
        isInBackground = true
        holders.removeAll()
        return releaseSession(force: true)
    }

    /// The app is active again, so claims take effect. The session stays
    /// inactive until the next playback or recording claims it.
    mutating func enterForeground() {
        isInBackground = false
    }

    private mutating func releaseSession(force: Bool = false) -> [IOSAudioSessionStep] {
        var steps: [IOSAudioSessionStep] = []
        if isActive || force {
            steps.append(.deactivate)
        }
        isActive = false
        if appliedConfiguration != .base {
            appliedConfiguration = .base
            steps.append(.configure(.base))
        }
        return steps
    }
}
