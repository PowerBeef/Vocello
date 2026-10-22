import Foundation
import QwenVoiceCore

/// RF-28: saving a clone voice as the Mac app's voice sheet saves one
/// (`MacSavedVoiceSheet`), for `voices enroll`, `voices replace` and `voices
/// save-take`. The sheet's own configuration seeds the transcript review
/// (`SavedVoiceSheetConfiguration`), the app's name rules apply, a transcript
/// needs a known reference language, the persisted record comes only from
/// `VoiceClipTranscriber.preparedVoiceEnrollmentMetadata`, and the candidate is
/// staged, then committed or discarded. Where the sheet asks the user, the
/// caller has decided in advance: whether to recognize the clip and what to do
/// with quality warnings.
public enum DesktopVoiceEnrollment {
    /// Whether the clip's words are recognized on device when none are given.
    public enum Transcription: String, Sendable, CaseIterable {
        /// Only when Speech is already authorized: never prompts.
        case auto
        /// Asks for Speech authorization if needed (macOS may prompt for the terminal).
        case always
        case never
    }

    /// What a candidate with quality warnings becomes (a hard-blocking warning is always discarded).
    public enum OnWarnings: String, Sendable, CaseIterable {
        case keep, discard, fail
    }

    /// Where the reference comes from.
    public enum Source: Sendable, Equatable {
        /// A clip the caller names.
        case clip
        /// A Clone take from History: its text is what it says; `voice` is the
        /// voice it was spoken in, which names the suggestion.
        case cloneTake(text: String, voice: String?)
        /// A Design take from History: its text is intent, not evidence of what
        /// was spoken, so the take is recognized like any clip.
        case designTake(text: String, voiceDescription: String)
    }

    public struct Request: Sendable {
        public var name: String?
        public var audioPath: String
        public var transcript: String?
        public var audioOnly: Bool
        public var transcription: Transcription
        public var language: Qwen3SupportedLanguage?
        public var onWarnings: OnWarnings
        public var replacingVoiceID: String?
        public var source: Source

        public init(
            name: String?, audioPath: String, transcript: String?, audioOnly: Bool, transcription: Transcription,
            language: Qwen3SupportedLanguage?, onWarnings: OnWarnings, replacingVoiceID: String? = nil,
            source: Source = .clip
        ) {
            self.name = name
            self.audioPath = audioPath
            self.transcript = transcript
            self.audioOnly = audioOnly
            self.transcription = transcription
            self.language = language
            self.onWarnings = onWarnings
            self.replacingVoiceID = replacingVoiceID
            self.source = source
        }
    }

    public enum Outcome: String, Sendable {
        case saved, discarded
    }

    public struct Result: Sendable {
        public let outcome: Outcome
        /// The saved voice; nil when the candidate was discarded.
        public let voice: PreparedVoice?
        public let name: String
        public let qualityWarnings: [String]
        /// `PreparedVoiceTranscriptSource`: where the saved transcript came from.
        public let transcriptSource: String
        public let referenceLanguage: String
        /// The on-device recognition's outcome, when it ran.
        public let automaticTranscription: String?
    }

    public enum Failure: Error, Equatable, Sendable {
        case nameMissing
        case nameNeedsCharacters
        case nameExists(String)
        case voiceNotFound(String)
        /// No transcript and no audio-only confirmation; `reason` says why none came.
        case transcriptNeeded(reason: String)
        /// A transcript needs its reference language, which could not be detected.
        case languageNeeded
        /// The candidate had quality warnings and was discarded.
        case qualityRefused(warnings: [String], hardBlocking: Bool)
    }

    /// The name the app suggests for a Design take's voice.
    public static func suggestedName(forVoiceDescription description: String) -> String {
        SavedVoiceNameSuggestion.designResultName(from: description)
    }

    static func reason(for evidence: VoiceClipTranscriber.EnrollmentEvidence) -> String {
        if evidence.authorizationStatus == .siriDisabled { return "Speech recognition needs Siri, which is off" }
        switch evidence.outcome {
        case .permissionDenied, .authorizationTimedOut: return "Speech recognition is not allowed for this terminal"
        case .noCandidateLocales, .recognizerUnavailable: return "no on-device recognizer for the clip's language"
        case .onDeviceRecognitionUnsupported: return "on-device recognition is unsupported here"
        case .recognitionTimedOut: return "recognition timed out"
        case .recognitionFailed: return "recognition failed"
        case .emptyResult, .success: return "recognition heard no words"
        case .lowConfidence: return "recognition was not confident"
        }
    }
}

extension DesktopEngineHost {
    public func listVoices() async throws -> [PreparedVoice] {
        try await store.listPreparedVoices()
    }

    /// Saves (or replaces) a clone voice as the app's voice sheet does.
    public func enrollVoice(_ request: DesktopVoiceEnrollment.Request) async throws -> DesktopVoiceEnrollment.Result {
        typealias Failure = DesktopVoiceEnrollment.Failure
        let path = request.audioPath
        let existing = try await store.listPreparedVoices()
        if let id = request.replacingVoiceID, !existing.contains(where: { $0.id == id }) {
            throw Failure.voiceNotFound(id)
        }

        // The sheet as the app opens it for this source.
        let configuration: SavedVoiceSheetConfiguration
        switch request.source {
        case .clip:
            let replaced = request.replacingVoiceID.flatMap { id in existing.first { $0.id == id } }
            configuration = SavedVoiceSheetConfiguration(
                title: "", subtitle: "", confirmLabel: "", initialName: replaced?.name ?? "", initialAudioPath: "",
                initialTranscript: "", replacingVoiceID: request.replacingVoiceID
            )
        case .cloneTake(let text, let voice):
            // As the app's History suggests it (`MacHistoryScreen.suggestedSavedVoiceName`).
            let trimmed = voice?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let suggestedName = trimmed.isEmpty
                ? URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
                : MacInterfaceText.historySuggestedVoiceName(trimmed)
            configuration = .cloneResult(suggestedName: suggestedName, audioPath: path, transcript: text)
        case .designTake(let text, let voiceDescription):
            configuration = .designResult(voiceDescription: voiceDescription, audioPath: path, transcript: text)
        }

        let name = (request.name ?? configuration.initialName).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw Failure.nameMissing }
        switch SavedVoiceSheetConfiguration.nameIssue(
            for: name, existingVoiceIDs: Set(existing.map(\.id)), replacingVoiceID: request.replacingVoiceID
        ) {
        case .needsCharacters?: throw Failure.nameNeedsCharacters
        case .exists(let storeID)?: throw Failure.nameExists(storeID)
        case nil: break
        }

        var review = ReferenceTranscriptionReviewState(
            initialTranscript: configuration.initialTranscript,
            readySource: configuration.initialTranscriptReadySource,
            transcriptClip: configuration.initialTranscriptClip
        )
        var language = ReferenceLanguageSelection(initialLanguage: configuration.initialReferenceLanguage)
        var transcript = configuration.initialTranscript
        // The clip is chosen: a transcript of another recording no longer describes
        // it. A History take opens the sheet on its own clip, which changes nothing.
        if request.source == .clip, review.referenceClipChanged(to: path) {
            transcript = ""
            language.referenceClipChanged()
        }
        if let explicit = request.language { language.select(explicit) }
        if let typed = request.transcript?.trimmingCharacters(in: .whitespacesAndNewlines), !typed.isEmpty {
            transcript = typed
            review.userEditedTranscript(typed)
            review.bindTranscript(to: path)
            language.applyDetectedLanguage(PromptLanguageDetector.detect(typed))
        }

        var evidence: VoiceClipTranscriber.EnrollmentEvidence?
        if request.audioOnly {
            transcript = ""
            review.confirmAudioOnly()
            review.bindTranscript(to: path)
        } else if transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            switch request.transcription {
            case .never:
                throw Failure.transcriptNeeded(reason: "transcription is off")
            case .auto:
                switch VoiceClipTranscriber.availability() {
                case .available: break
                case .notDetermined: throw Failure.transcriptNeeded(reason: "Speech recognition has not been allowed for this terminal")
                case .siriDisabled: throw Failure.transcriptNeeded(reason: "Speech recognition needs Siri, which is off")
                case .denied: throw Failure.transcriptNeeded(reason: "Speech recognition is not allowed for this terminal")
                }
            case .always:
                break
            }
            let generation = review.beginAutomaticTranscription()
            guard let result = await VoiceClipTranscriber.stableEnrollmentResult(url: URL(fileURLWithPath: path)) else {
                throw Failure.transcriptNeeded(reason: "the clip could not be read for recognition, or changed while it ran")
            }
            evidence = result.evidence
            guard let text = result.text,
                  review.acceptAutomaticTranscript(text, generation: generation, currentTranscript: "") else {
                throw Failure.transcriptNeeded(reason: DesktopVoiceEnrollment.reason(for: result.evidence))
            }
            transcript = text
            review.bindTranscript(to: path)
            language.applyDetectedLanguage(result.language)
        }
        guard review.allowsSave(transcript: transcript) else {
            throw Failure.transcriptNeeded(reason: "the transcript is not ready")
        }
        let hasTranscript = !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasTranscript, language.language == .auto { throw Failure.languageNeeded }

        let generatedSourceMode: String? = if case .designTake = request.source { GenerationMode.design.rawValue } else { nil }
        let metadata = try VoiceClipTranscriber.preparedVoiceEnrollmentMetadata(
            referenceLanguage: language.language, reviewState: review, evidence: evidence,
            generatedSourceMode: generatedSourceMode
        )
        let candidate = try await store.preparePreparedVoiceCandidate(
            name: name, audioPath: path, transcript: hasTranscript ? transcript : nil,
            replacingVoiceID: request.replacingVoiceID, enrollmentMetadata: metadata
        )
        func result(_ outcome: DesktopVoiceEnrollment.Outcome, _ voice: PreparedVoice?) -> DesktopVoiceEnrollment.Result {
            DesktopVoiceEnrollment.Result(
                outcome: outcome, voice: voice, name: name, qualityWarnings: candidate.qualityWarnings,
                transcriptSource: review.preparedVoiceTranscriptSource.rawValue,
                referenceLanguage: language.language.rawValue,
                automaticTranscription: evidence?.outcome.rawValue
            )
        }
        // A signal while the candidate was staged wins: it is discarded, never
        // committed (as the app discards one whose sheet closed, MAC-12).
        if Task.isCancelled {
            await store.discardAbandonedPreparedVoiceCandidate(id: candidate.id)
            throw CancellationError()
        }
        let warnings = candidate.qualityWarnings
        if !warnings.isEmpty {
            let hardBlocking = PreparedVoiceQualityWarning.isHardBlocking(warnings)
            if hardBlocking || request.onWarnings != .keep {
                do {
                    try await store.discardPreparedVoiceCandidate(id: candidate.id)
                } catch {
                    await store.discardAbandonedPreparedVoiceCandidate(id: candidate.id)
                }
                if !hardBlocking, request.onWarnings == .discard { return result(.discarded, nil) }
                throw Failure.qualityRefused(warnings: warnings, hardBlocking: hardBlocking)
            }
        }
        do {
            return result(.saved, try await store.commitPreparedVoiceCandidate(id: candidate.id))
        } catch {
            await store.discardAbandonedPreparedVoiceCandidate(id: candidate.id)
            throw error
        }
    }

    /// Deletes a saved voice, retrying while another Vocello process holds the
    /// saved-voice store, on the schedule the app's Saved Voices screen uses to
    /// retry a load (F-25).
    public func deleteVoice(id: String, sleep: (Duration) async throws -> Void = { try await Task.sleep(for: $0) })
        async throws {
        var retry = SavedVoicesBusyRetryPolicy()
        while true {
            do {
                try await store.deletePreparedVoice(id: id)
                return
            } catch {
                guard GenerationFailurePresentationReason(error) == .savedVoiceStoreBusy, let delay = retry.nextDelay() else {
                    throw error
                }
                try await sleep(delay)
            }
        }
    }
}
