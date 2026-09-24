import AVFoundation
import Foundation

/// Tiny audio player for reviewing a just-recorded (or just-generated) reference clip inside the
/// "Save this voice" sheet: play/pause + a 0…1 progress for the waveform playhead + the clip's
/// duration. Deliberately small — the Studio `AudioPlayerViewModel` is too coupled to the
/// generation flow, and `IOSVoicePreviewPlayer` has no progress.
@MainActor
final class ClipReviewPlayer: NSObject, ObservableObject {
    @Published private(set) var isPlaying = false
    @Published private(set) var progress: Double = 0   // 0…1
    @Published private(set) var duration: TimeInterval = 0

    private var player: AVAudioPlayer?
    private var url: URL?
    private var timer: Timer?
    #if os(iOS)
    private var interruptionObserver: NSObjectProtocol?
    /// Hold on the audio session while reviewing (PA-21).
    private var sessionClaim: IOSAudioSessionClaim?

    override init() {
        super.init()
        IOSPlaybackExclusivity.register(self) { [weak self] in
            guard let self, self.isPlaying else { return }
            self.pause()
        }
    }
    #endif

    deinit {
        // AVAudioPlayer holds its delegate unsafe-unowned; clear it and stop the
        // timer so a late callback / repeating tick can't touch a freed object.
        MainActor.assumeIsolated {
            #if os(iOS)
            if let interruptionObserver {
                NotificationCenter.default.removeObserver(interruptionObserver)
            }
            IOSAudioSessionOwner.shared.release(sessionClaim)
            #endif
            player?.delegate = nil
            player?.stop()
            timer?.invalidate()
        }
    }

    /// Prepare the player + read the duration without starting playback.
    func load(url: URL) {
        guard self.url != url else { return }
        stop()
        self.url = url
        if let prepared = try? AVAudioPlayer(contentsOf: url) {
            prepared.delegate = self
            prepared.prepareToPlay()
            player = prepared
            duration = prepared.duration
        }
    }

    func toggle() {
        isPlaying ? pause() : play()
    }

    private func play() {
        guard let player else { return }
        #if os(iOS)
        // Claim playback through the one session owner (PA-21) so the clip comes out of the
        // speaker after a recording, and pause any other player. (macOS has no AVAudioSession;
        // output routing is direct.)
        sessionClaim = try? IOSAudioSessionOwner.shared.activate(.playback, renewing: sessionClaim)
        IOSPlaybackExclusivity.didStartPlayback(self)
        #endif
        player.play()
        isPlaying = true
        startTimer()
        #if os(iOS)
        registerInterruptionObserver()
        #endif
    }

    func pause() {
        player?.pause()
        isPlaying = false
        stopTimer()
    }

    func stop() {
        // AVAudioPlayer holds its delegate unsafe-unowned — clear it before
        // releasing so a late finish callback can't touch a freed pointer.
        player?.delegate = nil
        player?.stop()
        player = nil
        url = nil
        isPlaying = false
        progress = 0
        duration = 0
        stopTimer()
        #if os(iOS)
        removeInterruptionObserver()
        IOSAudioSessionOwner.shared.release(sessionClaim)
        sessionClaim = nil
        #endif
    }

    #if os(iOS)
    private func registerInterruptionObserver() {
        guard interruptionObserver == nil else { return }
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            let typeRaw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            MainActor.assumeIsolated {
                guard let self, let typeRaw,
                      AVAudioSession.InterruptionType(rawValue: typeRaw) == .began else { return }
                self.pause()
            }
        }
    }

    private func removeInterruptionObserver() {
        if let interruptionObserver {
            NotificationCenter.default.removeObserver(interruptionObserver)
            self.interruptionObserver = nil
        }
    }
    #endif

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.tick() }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func tick() {
        guard let player, player.duration > 0 else { return }
        progress = min(1, player.currentTime / player.duration)
    }
}

extension ClipReviewPlayer: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.isPlaying = false
            self.progress = 0
            self.stopTimer()
            self.player?.currentTime = 0
        }
    }
}
