import AVFoundation
import Synchronization
import QwenVoiceCore

/// The only code in the iOS app that changes `AVAudioSession` (PA-21, AUD-02).
///
/// Players and the recorder claim the session for a use and release the claim
/// when they are done; `IOSAudioSessionLedger` decides the category and
/// activation steps, and this owner applies them on one serial queue. Because
/// activation is a blocking call into the media server and waits behind every
/// queued step, `activate` is called only off the main actor (the player
/// sheet's load and the recorder's start hop there first). `activateAsync`
/// never blocks its caller; players that activate the session implicitly
/// (`AVAudioPlayer`) use it.
final class IOSAudioSessionOwner: Sendable {
    static let shared = IOSAudioSessionOwner()

    private let queue = DispatchQueue(
        label: "com.qwenvoice.audio-session-owner",
        qos: .userInitiated
    )
    /// Touched only on `queue`; the mutex makes that state `Sendable`.
    private let ledger = Mutex(IOSAudioSessionLedger())
    private let nextClaim = Mutex<UInt64>(0)

    private init() {}

    /// Launch: sets the playback configuration without activating the session,
    /// so opening Vocello leaves other apps' audio playing.
    func prepareForLaunch() {
        queue.async { [self] in
            performIgnoringFailures(ledger.withLock { $0.prepareForLaunch() })
        }
    }

    /// Claims the session for `use` and activates it, blocking until the
    /// session is ready. Pass the caller's current claim to renew it. Never
    /// call it on the main actor: it waits behind every queued step.
    func activate(
        _ use: IOSAudioSessionUse,
        renewing claim: IOSAudioSessionClaim? = nil
    ) throws -> IOSAudioSessionClaim {
        let claim = claim ?? makeClaim()
        try queue.sync { [self] in
            try perform(claim: claim, use: use)
        }
        return claim
    }

    /// Claims the session for `use` without blocking. The steps run in order
    /// with every other claim; a failure drops the claim.
    @discardableResult
    func activateAsync(
        _ use: IOSAudioSessionUse,
        renewing claim: IOSAudioSessionClaim? = nil
    ) -> IOSAudioSessionClaim {
        let claim = claim ?? makeClaim()
        queue.async { [self] in
            try? perform(claim: claim, use: use)
        }
        return claim
    }

    /// Releases `claim`. The session deactivates only when no other claim is held.
    func release(_ claim: IOSAudioSessionClaim?) {
        guard let claim else { return }
        queue.async { [self] in
            performIgnoringFailures(ledger.withLock { $0.release(claim) })
        }
    }

    /// Leaving the foreground ends every claim and hands the session back.
    /// Claims made before `enterForeground` change nothing.
    func enterBackground() {
        queue.async { [self] in
            performIgnoringFailures(ledger.withLock { $0.enterBackground() })
        }
    }

    /// The app is active again: new claims activate the session.
    func enterForeground() {
        queue.async { [self] in
            ledger.withLock { $0.enterForeground() }
        }
    }

    // MARK: - Applying steps (on `queue`)

    private func makeClaim() -> IOSAudioSessionClaim {
        nextClaim.withLock { value in
            value += 1
            return IOSAudioSessionClaim(rawValue: value)
        }
    }

    /// A claim made while the app is in the background: the ledger records nothing and
    /// the session is left handed back, so a blocking caller must not proceed.
    struct ClaimRefusedInBackground: Error {}

    private func perform(claim: IOSAudioSessionClaim, use: IOSAudioSessionUse) throws {
        let (steps, refused) = ledger.withLock { ledger in
            (ledger.claim(claim, for: use), ledger.isInBackground)
        }
        if refused { throw ClaimRefusedInBackground() }
        do {
            for step in steps {
                try apply(step)
            }
        } catch {
            log("claim for \(use.rawValue) failed: \(DiagnosticPrivacy.summary(of: error))")
            performIgnoringFailures(ledger.withLock { $0.activationFailed(claim, steps: steps) })
            throw error
        }
    }

    private func performIgnoringFailures(_ steps: [IOSAudioSessionStep]) {
        for step in steps {
            do {
                try apply(step)
            } catch {
                log("\(step) failed: \(DiagnosticPrivacy.summary(of: error))")
            }
        }
    }

    private func apply(_ step: IOSAudioSessionStep) throws {
        let session = AVAudioSession.sharedInstance()
        switch step {
        case .configure(let configuration):
            try session.setCategory(
                configuration.category == .record ? .record : .playback,
                mode: configuration.usesMeasurementMode ? .measurement : .default,
                options: configuration.mixesWithOthers ? [.mixWithOthers] : []
            )
        case .activate:
            try session.setActive(true, options: [])
        case .deactivate:
            try session.setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private func log(_ message: String) {
        if TelemetryGate.resolvedEnabled {
            print("[IOSAudioSessionOwner] \(message)")
        }
    }
}

/// AUD-02: the session's interruptions and route changes reach every player
/// through one observer, installed at launch. `IOSPlaybackExclusivity.handle`
/// decides who pauses.
extension IOSPlaybackExclusivity {
    private static var sessionObservers: [NSObjectProtocol] = []

    static func observeSessionEvents() {
        guard sessionObservers.isEmpty else { return }
        let center = NotificationCenter.default
        let session = AVAudioSession.sharedInstance()
        sessionObservers.append(center.addObserver(
            forName: AVAudioSession.interruptionNotification, object: session, queue: .main
        ) { notification in
            // Raw values cross the hop: a Notification is not Sendable.
            let typeRaw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            guard typeRaw.flatMap(AVAudioSession.InterruptionType.init(rawValue:)) == .began else { return }
            MainActor.assumeIsolated { handle(.interruptionBegan) }
        })
        sessionObservers.append(center.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: session, queue: .main
        ) { notification in
            let reasonRaw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            guard reasonRaw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:)) == .oldDeviceUnavailable
            else { return }
            MainActor.assumeIsolated { handle(.outputDeviceLost) }
        })
    }
}
