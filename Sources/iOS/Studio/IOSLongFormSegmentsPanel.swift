import QwenVoiceCore
import SwiftUI

/// Per-segment regeneration for the retained completed long-form project:
/// a standard setup chip beside the resume chip's slot opens a confirmation
/// dialog listing the project's segments. Choosing one regenerates that
/// segment with a fresh recorded seed and reassembles the joined output,
/// mirroring the macOS replacement flow. In-session only, exactly like
/// resume — the retained plan is the identity authority. The chip is a plain
/// `IOSStudioSetupChip` button rather than a SwiftUI `Menu` because a Menu's
/// accessibility identifier does not reliably reach the on-device tree.
struct IOSLongFormSegmentsMenuChip: View {
    let mode: GenerationMode
    let tint: Color
    let appModel: AppModel
    let ttsEngine: TTSEngineStore
    let audioPlayer: AudioPlayerViewModel
    let studioCoordinator: StudioGenerationCoordinator

    @State private var isChoosingSegment = false

    private var isVisible: Bool {
        appModel.longForm.canRegenerateSegments && appModel.longForm.lastMode == mode
    }

    var body: some View {
        if isVisible {
            IOSStudioSetupChip(
                eyebrow: "Long-form",
                value: "Regenerate segment",
                abbreviation: "RS",
                leadingSymbol: "square.stack.3d.up",
                tint: tint,
                accessibilityID: "iosLongForm_segmentsChip",
                action: { isChoosingSegment = true }
            )
            .disabled(appModel.longForm.isProcessing || ttsEngine.hasActiveGeneration)
            .confirmationDialog(
                "Regenerate a segment",
                isPresented: $isChoosingSegment,
                titleVisibility: .visible
            ) {
                ForEach(appModel.longForm.segments) { segment in
                    Button("Segment \(segment.index + 1): \(String(segment.line.prefix(28)))") {
                        appModel.longForm.regenerateSegment(
                            index: segment.index,
                            ttsEngine: ttsEngine,
                            audioPlayer: audioPlayer,
                            studioCoordinator: studioCoordinator
                        )
                    }
                    .accessibilityIdentifier("iosLongForm_regenerateSegment_\(segment.index)")
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
