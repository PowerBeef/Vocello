import SwiftUI

/// A visible, non-modal storage warning on both app roots. It does not change
/// Studio's successful-generation state or take ownership of playback.
struct GenerationHistoryEnqueueWarning: View {
    private let state = GenerationHistoryRecovery.unqueued
    @State private var isRetrying = false
    #if os(iOS)
    @State private var exportGate = IOSExportGate()
    #endif
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    /// The copy follows the app's own interface language, not the system's.
    private var text: VocelloPresentationText {
        #if os(iOS)
        IOSAppLanguage.shared.presentation
        #else
        MacInterfaceText.presentation
        #endif
    }

    var body: some View {
        if !state.records.isEmpty {
            VStack(alignment: .leading, spacing: VocelloTheme.Spacing.sm) {
                Label(text.historyUnqueuedTitle, systemImage: "exclamationmark.triangle")
                    .font(.headline)
                Text(text.historyUnqueuedDetail)
                    .font(.caption)
                    .fixedSize(horizontal: false, vertical: true)
                let layout = dynamicTypeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: VocelloTheme.Spacing.sm))
                    : AnyLayout(HStackLayout(spacing: VocelloTheme.Spacing.md))
                layout {
                    Button(text.retryHistorySave) {
                        isRetrying = true
                        Task {
                            let result = await GenerationHistoryRecovery.reconcile()
                            NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
                            #if os(macOS)
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
                    #if os(iOS)
                    Button {
                        let urls = state.availableAudioURLs
                        // Only actual enqueue failures enter this recovery surface.
                        // Never trap retained user audio behind a purchase on storage failure.
                        exportGate.share(urls: urls, provenance: urls.map { _ in .recoveryRecord })
                    } label: {
                        Label(text.exportAudio, systemImage: "square.and.arrow.up")
                    }
                    .disabled(state.availableAudioURLs.isEmpty)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("historyUnqueued_export")
                    #else
                    ShareLink(items: state.availableAudioURLs) {
                        Label(text.exportAudio, systemImage: "square.and.arrow.up")
                    }
                    .disabled(state.availableAudioURLs.isEmpty)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("historyUnqueued_export")
                    #endif
                }
                .buttonStyle(.bordered)
            }
            .padding(VocelloTheme.Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .modifier(GatedBannerSurface())
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("historyUnqueued_banner")
            // A12-04: the banner appears off any VoiceOver focus; say once, and
            // again only when another take joins it, that History did not save it.
            .onChange(of: state.records.count, initial: true) { previous, count in
                if count >= previous {
                    StudioGenerationAnnouncer.post(text.historyUnqueuedTitle)
                }
            }
            #if os(iOS)
            .iosExportPresentation(exportGate)
            #endif
        }
    }
}

/// The banner's translucency, decided by the same two conditions every other
/// translucent surface in the app routes through. It was the one that did not:
/// a bare `.background(.regularMaterial)` in an architecture where the glass
/// decision is deliberately structural rather than remembered.
///
/// Reduce Transparency is the accessibility half. The generation performance
/// gate is the half a material cannot know about on its own: continuous
/// compositor work costs ~23% engine RTF on the 8 GB tier while a translucent
/// surface is visible (benchmarks/OPTIMIZATION.md §K), and this banner is
/// pinned to the top of the window, so when it is showing it is showing during
/// generation too.
///
/// The ungated branch keeps `.regularMaterial` rather than adopting glass: the
/// fix here is the gate, not a redesign of a warning the user did not ask to
/// see. The gate decides only the background's style, so the banner keeps one
/// view tree (and VoiceOver focus) when a generation starts or ends (A13-52).
private struct GatedBannerSurface: ViewModifier {
    func body(content: Content) -> some View {
        #if os(iOS)
        IOSGlassGate { isGated in styled(content, isGated: isGated) }
        #else
        GatedGlass { isGated in styled(content, isGated: isGated) }
        #endif
    }

    private func styled(_ content: Content, isGated: Bool) -> some View {
        content.background(isGated ? AnyShapeStyle(VocelloTheme.Surface.banner) : AnyShapeStyle(.regularMaterial))
    }
}
