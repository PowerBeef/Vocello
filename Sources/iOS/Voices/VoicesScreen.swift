import SwiftUI
import QwenVoiceCore

/// Top-level Voices tab entry point. Reads/writes `AppModel` state
/// directly so the screen doesn't need binding plumbing from
/// RootView.
///
/// Mirrors `design_references/Vocello iOS/screens.jsx` Voices section:
/// the unified built-in + saved voices list with search + filter chips
/// + a dashed "Save a new voice" CTA. The actual list rendering lives
/// in `IOSVoicesView` (already aligned with the design); this screen
/// is the AppModel-aware shell around it.
///
/// Routing semantics:
/// - Tap a built-in speaker → preset `customVoiceDraft.selectedSpeaker`,
///   switch to Custom mode, jump to Studio tab.
/// - Tap a saved voice → stage `PendingVoiceCloningHandoff`, switch to
///   Clone mode, jump to Studio.
struct VoicesScreen: View {
    @Environment(AppModel.self) private var appModel

    @State private var newVoiceFlow: NewVoiceFlow?

    var body: some View {
        @Bindable var appModel = appModel

        IOSVoicesView(
            selectedTab: $appModel.tab,
            onSelectBuiltInSpeaker: { speaker in
                appModel.customVoiceDraft.selectedSpeaker = speaker.id
                appModel.customVoiceDraft.selectedLanguage = TTSModel.qwenLanguage(forSpeaker: speaker.id)
                appModel.studioMode = .custom
                appModel.tab = .studio
            },
            onSelectSavedVoice: { voice in
                appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
                    savedVoiceID: voice.id,
                    wavPath: voice.wavPath,
                    transcript: (try? voice.loadTranscript()) ?? "",
                    transcriptLoadError: nil
                )
                appModel.studioMode = .clone
                appModel.tab = .studio
            },
            onRecordNewVoice: { newVoiceFlow = .recording },
            onImportNewVoice: { imported in newVoiceFlow = .imported(imported) }
        )
        .fullScreenCover(item: $newVoiceFlow) { flow in
            IOSRecordVoiceSheet(
                importedReference: flow.importedReference,
                onEnrolled: { voice, transcript, language in
                    newVoiceFlow = nil
                    // Same staging as tapping a saved voice → Clone mode, pre-loaded; carry the
                    // detected reference language so the Clone Language picker is pre-set.
                    appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
                        savedVoiceID: voice.id,
                        wavPath: voice.wavPath,
                        transcript: transcript,
                        transcriptLoadError: nil,
                        language: language
                    )
                    appModel.studioMode = .clone
                    appModel.tab = .studio
                },
                onDismiss: { newVoiceFlow = nil }
            )
        }
    }
}

private enum NewVoiceFlow: Identifiable {
    case recording
    case imported(ImportedReferenceAudio)

    var id: String {
        switch self {
        case .recording:
            return "recording"
        case .imported(let reference):
            return "imported-\(reference.fingerprint)"
        }
    }

    var importedReference: ImportedReferenceAudio? {
        guard case .imported(let reference) = self else { return nil }
        return reference
    }
}
