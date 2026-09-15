import Foundation
import QwenVoiceCore

/// The generation-lifecycle payloads `StudioGenerationCoordinator` publishes
/// to the Studio dock on both platforms. Moved out of `IOSStudioCanvas.swift`
/// so the macOS app compiles them by path; the iOS-only presentation
/// (`playerSheetItem`, the cadence copy, `IOSStudioGenState.playerPhase`)
/// stays in that file as extensions.

/// Lightweight payload for the live-preview dock card (no audio URL — the final
/// file doesn't exist yet). Carries only what the live card chrome needs; the
/// shared `AudioPlayerViewModel` owns the actual streaming playback.
struct IOSStudioLivePreviewItem: Equatable {
    let voiceName: String
    let modeLabel: String
    let mode: GenerationMode
    let transcript: String
    /// Identical to the eventual `.complete` item's seed (prompt-derived) so the
    /// decorative waveform shape does not change across the live→final swap.
    let waveformSeed: Int
    /// Prompt-derived forecast of the final audio length (from `LivePreviewEstimate`),
    /// computed once at generation start. Drives the streaming waveform's buffer fill
    /// (`generated-so-far / estimate`) so the card looks full while audio is still arriving.
    let estimatedAudioDuration: TimeInterval
}

struct IOSStudioInlinePlayerItem: Equatable {
    let generationID: UUID
    let audioURL: URL
    let voiceName: String
    let modeLabel: String
    let mode: GenerationMode
    let transcript: String
    let waveformSeed: Int
    let autoplay: Bool
    let cadenceNotice: IOSStudioCadenceNotice?
    /// True when the shared AudioPlayerViewModel already owns this generation's playback
    /// (live preview during generation → seamless hand-off). The inline card then mirrors/
    /// forwards that shared player instead of starting its own AVAudioPlayer (no double audio).
    var ownedBySharedPlayer: Bool = false

    init(
        generationID: UUID,
        audioURL: URL,
        voiceName: String,
        modeLabel: String,
        mode: GenerationMode,
        transcript: String,
        waveformSeed: Int,
        autoplay: Bool,
        cadenceNotice: IOSStudioCadenceNotice? = nil,
        ownedBySharedPlayer: Bool = false
    ) {
        self.generationID = generationID
        self.audioURL = audioURL
        self.voiceName = voiceName
        self.modeLabel = modeLabel
        self.mode = mode
        self.transcript = transcript
        self.waveformSeed = waveformSeed
        self.autoplay = autoplay
        self.cadenceNotice = cadenceNotice
        self.ownedBySharedPlayer = ownedBySharedPlayer
    }

    static func == (lhs: IOSStudioInlinePlayerItem, rhs: IOSStudioInlinePlayerItem) -> Bool {
        lhs.audioURL == rhs.audioURL
    }
}

struct IOSStudioCadenceNotice: Equatable {
    init?(audioQC: AudioQCReport?) {
        guard audioQC?.cadence?.classification == .unusual else { return nil }
    }
}
