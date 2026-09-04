import SwiftUI

/// A visible, non-modal storage warning on both app roots. It does not change
/// Studio's successful-generation state or take ownership of playback.
struct GenerationHistoryEnqueueWarning: View {
    private let state = GenerationHistoryRecovery.unqueued
    @State private var isRetrying = false
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        if !state.records.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Label(VocelloPresentationText.historyUnqueuedTitle, systemImage: "exclamationmark.triangle")
                    .font(.headline)
                Text(VocelloPresentationText.historyUnqueuedDetail)
                    .font(.caption)
                    .fixedSize(horizontal: false, vertical: true)
                let layout = dynamicTypeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
                    : AnyLayout(HStackLayout(spacing: 12))
                layout {
                    Button(VocelloPresentationText.retryHistorySave) {
                        isRetrying = true
                        Task {
                            let result = await GenerationHistoryRecovery.reconcile()
                            NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
                            #if canImport(QwenVoiceNative)
                            for generation in result.committed {
                                GenerationLibraryEvents.shared.announceGenerationAppended(generation)
                            }
                            #else
                            NotificationCenter.default.post(name: .generationSaved, object: nil)
                            #endif
                            isRetrying = false
                        }
                    }
                    .disabled(isRetrying)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("historyUnqueued_retry")
                    ShareLink(items: state.availableAudioURLs) {
                        Label(VocelloPresentationText.exportAudio, systemImage: "square.and.arrow.up")
                    }
                    .disabled(state.availableAudioURLs.isEmpty)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("historyUnqueued_export")
                }
                .buttonStyle(.bordered)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("historyUnqueued_banner")
        }
    }
}
