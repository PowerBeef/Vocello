import QwenVoiceCore
import SwiftUI

/// One History row in the iOS card language: a mode-tinted thumbnail tile
/// that plays the take, the script preview with its metadata line, and the
/// desktop action cluster (save to Saved Voices, Save As, delete). Every
/// `historyRow_*` identifier is the lane contract; the child identifiers keep
/// the `_play_`, `_saveVoice_`, `_saveAs_` and `_delete_` shapes the row
/// counter excludes.
struct MacHistoryItemCard: View {
    /// Where the row's text column starts: the play tile plus the card's own
    /// horizontal padding on either side of it. The hairline under the row and
    /// the long-form segments toggle beneath it both align to this.
    static let contentLeadingInset: CGFloat = MacControl.row.height + VocelloTheme.Spacing.md * 2

    let generation: Generation
    let rowID: String
    let textPreview: String
    let formattedDate: String
    let audioFileExists: Bool
    let waveformSeed: Int
    let allowsDeletion: Bool
    let onPlay: () -> Void
    let onSaveToSavedVoices: (() -> Void)?
    let onSaveAs: () -> Void
    let onDelete: () -> Void

    @State private var isHovered = false

    private var generationMode: GenerationMode? {
        GenerationMode(rawValue: generation.mode.lowercased())
    }

    private var modeText: String {
        generationMode.map(MacInterfaceText.modeName) ?? generation.mode.capitalized
    }

    private var modeTint: Color {
        generationMode.map(MacTheme.Brand.modeColor) ?? MacTheme.historyTint
    }

    private var durationText: String? {
        guard let duration = generation.duration, duration > 0 else { return nil }
        return String(format: "%.1fs", duration)
    }

    private var metadataParts: [String] {
        var parts: [String] = []
        if let voice = generation.voice?.trimmingCharacters(in: .whitespacesAndNewlines), !voice.isEmpty {
            parts.append(voice)
        }
        parts.append(modeText)
        parts.append(formattedDate)
        if let durationText {
            parts.append(durationText)
        }
        return parts
    }

    var body: some View {
        HStack(alignment: .center, spacing: VocelloTheme.Spacing.md) {
            playTile

            VStack(alignment: .leading, spacing: VocelloTheme.Spacing.xs) {
                Text(textPreview)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                HStack(spacing: VocelloTheme.Spacing.tight) {
                    VocelloModeDot(tint: modeTint)
                    // The mode stays a textual cue beside the dot, never
                    // color-only, even when the voice name is present.
                    Text(verbatim: metadataParts.joined(separator: " · "))
                        .macType(.rowMeta)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(metadataParts.joined(separator: ", "))
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            actions
        }
        .padding(.vertical, VocelloTheme.Spacing.snug)
        .padding(.horizontal, VocelloTheme.Spacing.md)
        .background {
            VocelloShape.row()
                .fill(Color.white.opacity(isHovered ? 0.035 : 0))
        }
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(MacTheme.Surface.hairline)
                .frame(height: VocelloTheme.Stroke.hairline)
                .padding(.leading, Self.contentLeadingInset)
                .padding(.trailing, VocelloTheme.Spacing.md)
        }
        .contentShape(VocelloShape.row())
        .onHover { hovering in
            isHovered = hovering
        }
        .appAnimation(MacTheme.Motion.stateChange, value: isHovered)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("historyRow_\(rowID)")
    }

    private var playTile: some View {
        Button(action: onPlay) {
            ZStack {
                VocelloShape.row()
                    .fill(modeTint.opacity(0.14))
                    .background {
                        VocelloShape.row()
                            .fill(Color.white.opacity(0.02))
                    }
                if audioFileExists {
                    VocelloStaticWaveformThumbnail(seed: waveformSeed, barCount: 14, tint: modeTint)
                        // Content, not a control: it keeps the optical inset
                        // it had when the tile was 48 pt.
                        .frame(width: 28, height: 18)
                        .opacity(isHovered ? 0.35 : 1)
                    if isHovered {
                        Image(systemName: "play.fill")
                            .font(.system(size: MacControl.row.glyph, weight: .semibold))
                            .foregroundStyle(modeTint)
                    }
                } else {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: MacControl.row.glyph, weight: .semibold))
                        .foregroundStyle(MacTheme.Status.guarded)
                }
            }
            .macControlSquare(.row)
            .contentShape(VocelloShape.row())
        }
        .buttonStyle(.plain)
        .disabled(!audioFileExists)
        .help(audioFileExists ? MacInterfaceText.historyPlayTake : MacInterfaceText.historyAudioUnavailable)
        .accessibilityLabel(audioFileExists ? MacInterfaceText.historyPlayTake : MacInterfaceText.historyAudioUnavailable)
        .accessibilityIdentifier("historyRow_play_\(rowID)")
    }

    private var actions: some View {
        HStack(spacing: VocelloTheme.Spacing.tight) {
            if let onSaveToSavedVoices {
                MacIconButton(
                    symbol: "person.crop.circle.badge.plus",
                    label: MacInterfaceText.historySaveToSavedVoices,
                    accessibilityIdentifier: "historyRow_saveVoice_\(rowID)",
                    isEnabled: audioFileExists,
                    action: onSaveToSavedVoices
                )
            }
            MacIconButton(
                symbol: "square.and.arrow.down",
                label: MacInterfaceText.historySaveAs,
                accessibilityIdentifier: "historyRow_saveAs_\(rowID)",
                isEnabled: audioFileExists,
                action: onSaveAs
            )
            MacIconButton(
                symbol: "trash",
                label: MacInterfaceText.historyDeleteTake,
                accessibilityIdentifier: "historyRow_delete_\(rowID)",
                isEnabled: allowsDeletion,
                help: allowsDeletion ? MacInterfaceText.historyDeleteTake : MacInterfaceText.historyReloadBeforeDelete,
                action: onDelete
            )
        }
    }
}
