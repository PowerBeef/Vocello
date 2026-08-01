import QwenVoiceCore
import SwiftUI

/// Per-segment regeneration for the retained completed long-form project:
/// one pill-sized menu in the studio setup row (beside the resume chip's
/// slot), listing the project's segments. Choosing one regenerates that
/// segment with a fresh recorded seed and reassembles the joined output,
/// mirroring the macOS replacement flow. In-session only, exactly like
/// resume — the retained plan is the identity authority.
struct IOSLongFormSegmentsMenuChip: View {
    let mode: GenerationMode
    let tint: Color
    let appModel: AppModel
    let ttsEngine: TTSEngineStore
    let audioPlayer: AudioPlayerViewModel
    let studioCoordinator: StudioGenerationCoordinator

    private var isVisible: Bool {
        appModel.longForm.canRegenerateSegments && appModel.longForm.lastMode == mode
    }

    var body: some View {
        if isVisible {
            Menu {
                ForEach(appModel.longForm.segments) { segment in
                    Button {
                        appModel.longForm.regenerateSegment(
                            index: segment.index,
                            ttsEngine: ttsEngine,
                            audioPlayer: audioPlayer,
                            studioCoordinator: studioCoordinator
                        )
                    } label: {
                        Label(
                            "Segment \(segment.index + 1): \(String(segment.line.prefix(28)))",
                            systemImage: "arrow.clockwise"
                        )
                    }
                    .accessibilityIdentifier("iosLongForm_regenerateSegment_\(segment.index)")
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "square.stack.3d.up")
                        .font(.caption2.weight(.semibold))
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Long-form")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                        Text("Regenerate segment")
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .frame(maxWidth: .infinity)
                .background(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(tint.opacity(0.12))
                )
                .foregroundStyle(tint)
            }
            .disabled(appModel.longForm.isProcessing || ttsEngine.hasActiveGeneration)
            .accessibilityIdentifier("iosLongForm_segmentsChip")
        }
    }
}
