import QwenVoiceCore
import SwiftUI

/// One History row in the iOS card language: a mode-tinted thumbnail tile
/// that plays the take, the script preview with its metadata line, and the
/// desktop action cluster (save to Saved Voices, Save As, delete). Every
/// `historyRow_*` identifier is the lane contract; the child identifiers keep
/// the `_play_`, `_saveVoice_`, `_saveAs_` and `_delete_` shapes the row
/// counter excludes.
struct MacHistoryItemCard: View {
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
        HStack(alignment: .center, spacing: 12) {
            playTile

            VStack(alignment: .leading, spacing: 3) {
                Text(textPreview)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                HStack(spacing: 6) {
                    MacModeDot(tint: modeTint)
                    // The mode stays a textual cue beside the dot, never
                    // color-only, even when the voice name is present.
                    Text(verbatim: metadataParts.joined(separator: " · "))
                        .font(.system(size: 12))
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(metadataParts.joined(separator: ", "))
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            actions
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(isHovered ? 0.035 : 0))
        }
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(MacTheme.Surface.hairline)
                .frame(height: 0.5)
                .padding(.leading, 72)
                .padding(.trailing, 12)
        }
        .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
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
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(modeTint.opacity(0.14))
                    .background {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(Color.white.opacity(0.02))
                    }
                if audioFileExists {
                    MacStaticWaveformThumbnail(seed: waveformSeed, barCount: 14, tint: modeTint)
                        .frame(width: 34, height: 22)
                        .opacity(isHovered ? 0.35 : 1)
                    if isHovered {
                        Image(systemName: "play.fill")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(modeTint)
                    }
                } else {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(MacTheme.Status.guarded)
                }
            }
            .frame(width: 48, height: 48)
            .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(!audioFileExists)
        .help(audioFileExists ? MacInterfaceText.historyPlayTake : MacInterfaceText.historyAudioUnavailable)
        .accessibilityLabel(audioFileExists ? MacInterfaceText.historyPlayTake : MacInterfaceText.historyAudioUnavailable)
        .accessibilityIdentifier("historyRow_play_\(rowID)")
    }

    private var actions: some View {
        HStack(spacing: 6) {
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
