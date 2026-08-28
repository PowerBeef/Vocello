import Foundation

/// Pure enrollment policy for an imported or recorded clone reference. The state owns operation
/// generations so a delayed recognizer result cannot replace a sidecar or a user's edit.
struct IOSReferenceTranscriptionReviewState: Equatable, Sendable {
    enum ReadySource: Equatable, Sendable {
        case sidecar
        case automatic
        case manual
    }

    enum UnavailableReason: Equatable, Sendable {
        case permissionDenied
        case siriDisabled
        case recognitionUnavailableOrEmpty
        case cancelled
    }

    enum Phase: Equatable, Sendable {
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

    init(sidecarTranscript: String) {
        phase = sidecarTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .transcribing
            : .ready(.sidecar)
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
            phase = .unavailable(.recognitionUnavailableOrEmpty)
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
            ? .unavailable(.recognitionUnavailableOrEmpty)
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
        case .transcribing, .unavailable:
            return false
        }
    }

    var offersAudioOnlyConfirmation: Bool {
        if case .unavailable = phase { return true }
        return false
    }

    var status: Status {
        switch phase {
        case .ready(.sidecar):
            return Status(
                message: VocelloPresentationText.enrollmentTranscriptionStatus(.sidecarReady),
                symbolName: "doc.text.fill",
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
        case .unavailable(.recognitionUnavailableOrEmpty):
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
