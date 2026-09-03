import Foundation
import QwenVoiceCore

/// Platform-neutral enrollment policy for an imported or recorded clone reference.
///
/// The state owns operation generations so a delayed recognizer result cannot replace a
/// sidecar, an existing reviewed transcript, or a user's edit. Both Apple frontends use this
/// exact policy; platform views only render the resulting status and actions.
struct ReferenceTranscriptionReviewState: Equatable, Sendable {
    enum ReadySource: Equatable, Sendable {
        case sidecar
        case automatic
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

    private(set) var phase: Phase
    private(set) var operationGeneration: UInt64 = 0

    init(
        initialTranscript: String,
        readySource: ReadySource = .sidecar
    ) {
        phase = initialTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .awaitingAudio
            : .ready(readySource)
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
        currentTranscript: String
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
        phase = .ready(.automatic)
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
        case .ready:
            return hasTranscript
        case .audioOnlyConfirmed:
            return !hasTranscript
        case .awaitingAudio, .transcribing, .unavailable:
            return false
        }
    }

    var offersAudioOnlyConfirmation: Bool {
        if case .unavailable = phase { return true }
        return false
    }

    var preparedVoiceTranscriptSource: PreparedVoiceTranscriptSource {
        switch phase {
        case .ready(.sidecar): return .sidecar
        case .ready(.automatic): return .automatic
        case .ready(.manual): return .manual
        case .audioOnlyConfirmed: return .audioOnly
        case .awaitingAudio, .ready(.existing), .transcribing, .unavailable: return .unknown
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
