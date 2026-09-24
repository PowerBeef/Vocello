import AVFoundation
import QwenVoiceCore
import SwiftUI

/// Lightweight AVAudioPlayer wrapper that plays per-voice sample WAVs
/// bundled at `Sources/Resources/voice-previews/{id}.wav`. Used by the
/// voice picker sheet to preview ~2.5 s of each voice without leaving
/// the picker.
///
/// One instance lives in `IOSVoicePickerSheet` as `@StateObject` so
/// preview state survives filter + search re-renders but resets when
/// the sheet dismisses.
@MainActor
final class IOSVoicePreviewPlayer: NSObject, ObservableObject {
    /// The voice id currently previewing, or `nil` when no audio is
    /// playing. Drives the play↔pause icon swap in the row's preview
    /// button.
    @Published private(set) var currentlyPlayingID: String?

    private var player: AVAudioPlayer?
    /// Mixable hold on the audio session while a sample plays (PA-21). The
    /// owner restores the default category when it is released, so mixing
    /// never leaks into later playback.
    private var sessionClaim: IOSAudioSessionClaim?

    override init() {
        super.init()
        IOSPlaybackExclusivity.register(self) { [weak self] in
            self?.stop()
        }
    }

    /// Toggles preview for the given voice id. If the same voice is
    /// already previewing, stops it; otherwise stops any in-flight
    /// preview and starts the new one.
    func toggle(voiceID: String) {
        if currentlyPlayingID == voiceID {
            stop()
        } else {
            play(voiceID: voiceID)
        }
    }

    /// Resolves the voice id to a bundled WAV under `voice-previews/`
    /// and plays it. Returns silently when the WAV is missing — the
    /// asset set may be incomplete during development.
    func play(voiceID: String) {
        stop()

        guard let url = Bundle.main.url(
            forResource: voiceID,
            withExtension: "wav",
            subdirectory: "voice-previews"
        ) ?? Bundle.main.url(
            forResource: voiceID,
            withExtension: "wav"
        ) else {
            // No bundled sample for this voice. Fail-safe; the picker
            // simply doesn't preview. Runtime diagnostics flag missing
            // assets during sample generation.
            if TelemetryGate.resolvedEnabled {
                print("[IOSVoicePreviewPlayer] No sample WAV for voice id '\(voiceID)' under voice-previews/")
            }
            return
        }

        do {
            sessionClaim = try IOSAudioSessionOwner.shared.activate(.mixablePreview)
            IOSPlaybackExclusivity.didStartPlayback(self)

            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            player.prepareToPlay()
            self.player = player
            self.currentlyPlayingID = voiceID
            player.play()
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[IOSVoicePreviewPlayer] Failed to play '\(voiceID)': \(error)")
            }
            stop()
        }
    }

    func stop() {
        player?.stop()
        player = nil
        currentlyPlayingID = nil
        IOSAudioSessionOwner.shared.release(sessionClaim)
        sessionClaim = nil
    }
}

extension IOSVoicePreviewPlayer: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let finished = ObjectIdentifier(player)
        Task { @MainActor [weak self] in
            guard let self, let current = self.player,
                  ObjectIdentifier(current) == finished else { return }
            self.stop()
        }
    }
}
