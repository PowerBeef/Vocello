import Foundation
import QwenVoiceCore

/// Platform-neutral enrollment policy for an imported or recorded clone reference.
///
/// The state owns operation generations so a delayed recognizer result cannot replace a
/// sidecar, an existing reviewed transcript, or a user's edit. Both Apple frontends use this
/// exact policy; platform views only render the resulting status and actions.
struct ReferenceTranscriptionReviewState: Equatable, Sendable {
    /// The engine's own shaping, so the field shows what conditions the take.
    static func conditioningLine(_ raw: String) -> String? {
        CloneConditioningMode.conditioningText(raw)
    }

    /// How much of the clip's speech a recognized transcript spans (G-01). A
    /// transcript that leaves part of the reference unspoken is the reported
    /// cause of transcript-backed clones that never end, so only `whole` is
    /// accepted without the user's review.
    enum TranscriptCoverage: String, Sendable, Equatable {
        /// The first and last recognized words reach both ends of the audible clip.
        case whole
        /// Speech is audible before the first or after the last recognized word.
        case partial
        /// The recognizer reported no timestamps, or the clip could not be measured.
        case unknown
    }

    enum ReadySource: Equatable, Sendable {
        case sidecar
        case automatic
        /// Recognized text that does not reach both ends of the clip's speech,
        /// or whose reach could not be measured (G-01). It is shown for the
        /// user to complete, and it never saves or conditions a take as it is:
        /// an edit, a review or the audio-only choice resolves it.
        case automaticPartial
        case manual
        /// A transcript supplied by a pre-existing workflow, such as saving a generated clip or
        /// replacing an enrolled reference. It is ready for review but has no new ASR evidence.
        case existing
    }

    enum UnavailableReason: Equatable, Sendable {
        case permissionDenied
        case siriDisabled
        case recognizerUnavailable
        case onDeviceRecognitionUnsupported
        case recognitionTimedOut
        case recognitionFailed
        case emptyResult
        case lowConfidence
        case cancelled
    }

    enum Phase: Equatable, Sendable {
        case awaitingAudio
        case ready(ReadySource)
        case transcribing
        case unavailable(UnavailableReason)
        case audioOnlyConfirmed
    }

    struct Status: Equatable, Sendable {
        let message: String
        let symbolName: String
        let showsProgress: Bool
    }

    /// The reference clip the transcript under review describes (U15): the one
    /// it was recognized, read, supplied or typed for.
    enum TranscriptClip: Equatable, Sendable {
        /// No clip yet: an empty field, or one typed before any clip was
        /// chosen, which may describe the clip picked next.
        case unbound
        /// Recognized, read, supplied or typed for this clip (its path).
        case clip(String)
        /// Supplied for a clip this review never shows: the reference that a
        /// Replace reference flow replaces.
        case replacedReference
    }

    private(set) var phase: Phase
    private(set) var operationGeneration: UInt64 = 0
    private(set) var transcriptClip: TranscriptClip

    init(
        initialTranscript: String,
        readySource: ReadySource = .sidecar,
        transcriptClip: TranscriptClip = .unbound
    ) {
        phase = initialTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .awaitingAudio
            : .ready(readySource)
        self.transcriptClip = transcriptClip
    }

    /// The transcript now describes `clip`, or no clip yet when nil: it was
    /// recognized or confirmed for that clip, or the user edited it while
    /// that clip was chosen.
    mutating func bindTranscript(to clip: String?) {
        transcriptClip = clip.map(TranscriptClip.clip) ?? .unbound
    }

    /// The reference clip became `clip` (U15). Only a transcript bound to that
    /// same clip, or typed while no clip was chosen, still describes it; any
    /// other one belongs to a different recording. Returns whether the caller
    /// clears its transcript and starts recognition for the new clip. The
    /// review then awaits it, so Save stays blocked until recognition, an edit
    /// or the audio-only confirmation resolves it, and a recognizer result for
    /// the previous clip can no longer apply.
    mutating func referenceClipChanged(to clip: String) -> Bool {
        switch transcriptClip {
        case .clip(let bound) where bound == clip:
            return false
        case .unbound where phase == .ready(.manual):
            transcriptClip = .clip(clip)
            return false
        case .unbound, .clip, .replacedReference:
            operationGeneration &+= 1
            phase = .awaitingAudio
            transcriptClip = .unbound
            return true
        }
    }

    mutating func awaitAudio() {
        operationGeneration &+= 1
        phase = .awaitingAudio
    }

    mutating func beginAutomaticTranscription() -> UInt64 {
        operationGeneration &+= 1
        phase = .transcribing
        return operationGeneration
    }

    @discardableResult
    mutating func acceptAutomaticTranscript(
        _ text: String,
        generation: UInt64,
        currentTranscript: String,
        coverage: TranscriptCoverage
    ) -> Bool {
        guard generation == operationGeneration, phase == .transcribing else { return false }
        guard currentTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            phase = .ready(.manual)
            operationGeneration &+= 1
            return false
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            phase = .unavailable(.emptyResult)
            return false
        }
        phase = .ready(coverage == .whole ? .automatic : .automaticPartial)
        return true
    }

    mutating func finishWithoutTranscript(
        reason: UnavailableReason,
        generation: UInt64,
        currentTranscript: String
    ) {
        guard generation == operationGeneration, phase == .transcribing else { return }
        if currentTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            phase = .unavailable(reason)
        } else {
            phase = .ready(.manual)
        }
    }

    mutating func userEditedTranscript(_ text: String) {
        operationGeneration &+= 1
        phase = text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .unavailable(.emptyResult)
            : .ready(.manual)
    }

    mutating func confirmAudioOnly() {
        operationGeneration &+= 1
        phase = .audioOnlyConfirmed
    }

    mutating func invalidate() {
        operationGeneration &+= 1
        if phase == .transcribing {
            phase = .unavailable(.cancelled)
        }
    }

    func isCurrent(generation: UInt64) -> Bool {
        generation == operationGeneration
    }

    func allowsSave(transcript: String) -> Bool {
        let hasTranscript = !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        switch phase {
        case .ready(.automaticPartial):
            return false
        case .ready:
            return hasTranscript
        case .audioOnlyConfirmed:
            return !hasTranscript
        case .awaitingAudio, .transcribing, .unavailable:
            return false
        }
    }

    var offersAudioOnlyConfirmation: Bool {
        switch phase {
        case .unavailable, .ready(.automaticPartial): return true
        case .awaitingAudio, .ready, .transcribing, .audioOnlyConfirmed: return false
        }
    }

    var preparedVoiceTranscriptSource: PreparedVoiceTranscriptSource {
        switch phase {
        case .ready(.sidecar): return .sidecar
        case .ready(.automatic): return .automatic
        case .ready(.manual): return .manual
        case .audioOnlyConfirmed: return .audioOnly
        case .awaitingAudio, .ready(.existing), .ready(.automaticPartial), .transcribing, .unavailable:
            return .unknown
        }
    }

    var status: Status {
        switch phase {
        case .awaitingAudio:
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.awaitingAudio),
                symbolName: "waveform.badge.plus",
                showsProgress: false
            )
        case .ready(.sidecar):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.sidecarReady),
                symbolName: "doc.text.fill",
                showsProgress: false
            )
        case .ready(.existing):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.manualReady),
                symbolName: "checkmark.circle.fill",
                showsProgress: false
            )
        case .transcribing:
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.transcribing),
                symbolName: "waveform",
                showsProgress: true
            )
        case .ready(.automatic):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.automaticReady),
                symbolName: "checkmark.circle.fill",
                showsProgress: false
            )
        case .ready(.automaticPartial):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.automaticPartial),
                symbolName: "exclamationmark.triangle.fill",
                showsProgress: false
            )
        case .ready(.manual):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.manualReady),
                symbolName: "checkmark.circle.fill",
                showsProgress: false
            )
        case .unavailable(.permissionDenied):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.permissionDenied),
                symbolName: "exclamationmark.triangle.fill",
                showsProgress: false
            )
        case .unavailable(.siriDisabled):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.unavailable),
                symbolName: "exclamationmark.triangle.fill",
                showsProgress: false
            )
        case .unavailable(.recognizerUnavailable),
             .unavailable(.onDeviceRecognitionUnsupported),
             .unavailable(.recognitionTimedOut),
             .unavailable(.recognitionFailed),
             .unavailable(.emptyResult),
             .unavailable(.lowConfidence):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.empty),
                symbolName: "exclamationmark.triangle.fill",
                showsProgress: false
            )
        case .unavailable(.cancelled):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.cancelled),
                symbolName: "exclamationmark.triangle.fill",
                showsProgress: false
            )
        case .audioOnlyConfirmed:
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.audioOnlyConfirmed),
                symbolName: "waveform.circle.fill",
                showsProgress: false
            )
        }
    }
}

/// Enrollment language follows the current clip until the user chooses a
/// language explicitly. A detected or inherited language belongs to its old
/// clip and must not silently label a replacement recording.
struct ReferenceLanguageSelection: Equatable, Sendable {
    private(set) var language: Qwen3SupportedLanguage
    private(set) var isAutomatic = true

    init(initialLanguage: Qwen3SupportedLanguage = .auto) {
        language = initialLanguage
    }

    mutating func select(_ language: Qwen3SupportedLanguage) {
        self.language = language
        isAutomatic = language == .auto
    }

    mutating func applyDetectedLanguage(_ language: Qwen3SupportedLanguage) {
        guard isAutomatic else { return }
        self.language = language
    }

    mutating func referenceClipChanged() {
        guard isAutomatic else { return }
        language = .auto
    }
}
