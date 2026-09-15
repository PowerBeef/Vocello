import SwiftUI

/// The Studio dock hero player (the iOS `IOSStudioPlayerCard`): one card for
/// the live streaming preview and the completed take, so the live → complete
/// transition morphs in place. The shared `AudioPlayerViewModel` owns the
/// audio on the desktop (the sidebar footer card mirrors the same player), so
/// this card reads and drives it directly. While live, its trailing control
/// is the lanes' `textInput_cancelButton`; complete, it offers Save As,
/// Reveal in Finder and Dismiss.
struct MacStudioPlayerCard: View {
    enum Phase: Equatable {
        case live(IOSStudioLivePreviewItem)
        case complete(IOSStudioInlinePlayerItem)

        var isLive: Bool {
            if case .live = self { return true }
            return false
        }

        var voiceName: String {
            switch self {
            case .live(let item): item.voiceName
            case .complete(let item): item.voiceName
            }
        }

        var modeLabel: String {
            switch self {
            case .live(let item): item.modeLabel
            case .complete(let item): item.modeLabel
            }
        }

        var completedItem: IOSStudioInlinePlayerItem? {
            if case .complete(let item) = self { return item }
            return nil
        }

        var accessibilityIdentifier: String {
            switch self {
            case .live:
                "studio_livePreview_card"
            case .complete(let item):
                "studio_inlinePlayer_generation_\(item.generationID.uuidString.lowercased())"
            }
        }
    }

    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel

    let phase: Phase
    let tint: Color
    let onDismiss: () -> Void
    let onCancel: () -> Void
    let onRetry: () -> Void

    @State private var isConfirmingDismiss = false

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 22, style: .continuous)

        VStack(alignment: .leading, spacing: 10) {
            MacStudioWaveformRow(tint: tint)
            controlsRow

            if let notice = phase.completedItem?.cadenceNotice {
                cadenceNoticeRow(notice)
            }

            if let playbackError = audioPlayer.playbackError {
                Text(playbackError)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { shape.fill(Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.85)) }
        .overlay { shape.stroke(Color.white.opacity(0.10), lineWidth: 0.5) }
        .shadow(color: Color.black.opacity(0.22), radius: 5, x: 0, y: 2)
        .transition(
            AppLaunchConfiguration.current.animationsEnabled
                ? .move(edge: .bottom).combined(with: .opacity)
                : .identity
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(phase.accessibilityIdentifier)
        .confirmationDialog(
            MacInterfaceText.studioDismissTake,
            isPresented: $isConfirmingDismiss,
            titleVisibility: .visible
        ) {
            Button(MacInterfaceText.playerClose, role: .destructive) {
                // Stop the shared player too, so dismissing never leaves audio
                // playing with no visible card.
                audioPlayer.dismiss()
                onDismiss()
            }
            .accessibilityIdentifier("studio_inlinePlayer_dismissConfirm")
            Button(MacInterfaceText.cancel, role: .cancel) {}
        } message: {
            Text(MacInterfaceText.studioDismissTakeDetail)
        }
    }

    private var controlsRow: some View {
        HStack(spacing: 10) {
            Button {
                AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                    audioPlayer.togglePlayPause()
                }
            } label: {
                Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.onAccent)
                    .frame(width: 38, height: 38)
                    .background {
                        Circle().fill(
                            LinearGradient(
                                colors: [tint, tint.mix(with: .black, by: 0.20, in: .perceptual)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                    }
                    .overlay { Circle().stroke(Color.white.opacity(0.18), lineWidth: 0.5) }
            }
            .buttonStyle(.plain)
            .disabled(!audioPlayer.hasAudio)
            .accessibilityLabel(MacInterfaceText.menuPlayPause)
            .accessibilityValue(audioPlayer.isPlaying ? "pause" : "play")
            .accessibilityIdentifier(phase.isLive ? "studio_livePreview_playPause" : "studio_inlinePlayer_playPause")

            VStack(alignment: .leading, spacing: 2) {
                Text(phase.voiceName)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text(phase.modeLabel)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                    if phase.isLive {
                        HStack(spacing: 4) {
                            Circle().fill(tint).frame(width: 6, height: 6)
                            Text(MacInterfaceText.playerLive)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(MacTheme.Text.secondary)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("studio_livePreview_badge")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if phase.isLive {
                Button {
                    onCancel()
                } label: {
                    Label(MacInterfaceText.cancel, systemImage: "stop.fill")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(MacTheme.Text.primary)
                        .padding(.horizontal, 12)
                        .frame(height: 30)
                        .background { Capsule(style: .continuous).fill(Color.white.opacity(0.06)) }
                        .overlay { Capsule(style: .continuous).stroke(Color.white.opacity(0.12), lineWidth: 0.5) }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(MacInterfaceText.studioStopGenerating)
                .accessibilityIdentifier("textInput_cancelButton")
            } else if let item = phase.completedItem {
                MacIconButton(
                    symbol: "arrow.clockwise",
                    label: MacInterfaceText.studioGenerateAgain,
                    accessibilityIdentifier: "studio_inlinePlayer_retry",
                    size: 30,
                    action: onRetry
                )
                MacIconButton(
                    symbol: "square.and.arrow.down",
                    label: MacInterfaceText.historySaveAs,
                    accessibilityIdentifier: "studio_inlinePlayer_saveAs",
                    size: 30,
                    action: { _ = MacHistoryFileActions.saveCopy(of: item.audioURL.path) }
                )
                MacIconButton(
                    symbol: "folder",
                    label: MacInterfaceText.revealInFinder,
                    accessibilityIdentifier: "studio_inlinePlayer_reveal",
                    size: 30,
                    action: { MacHistoryFileActions.revealInFinder(item.audioURL.path) }
                )
                MacIconButton(
                    symbol: "xmark",
                    label: MacInterfaceText.playerClose,
                    accessibilityIdentifier: "studio_inlinePlayer_dismiss",
                    size: 30,
                    action: { isConfirmingDismiss = true }
                )
            }
        }
        .appAnimation(MacTheme.Motion.stateChange, value: phase.isLive)
    }

    private func cadenceNoticeRow(_ notice: IOSStudioCadenceNotice) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "waveform.path.badge.minus")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(MacTheme.Status.guarded)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text(MacInterfaceText.studioUnusualPacing)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                Text(MacInterfaceText.studioReviewTake)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(MacTheme.Status.guarded.opacity(0.10))
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("studio_inlinePlayer_cadenceNotice")
    }
}

/// The per-tick slice of the card: only this row subscribes to the playback
/// progress object, so the card chrome does not re-render on every tick.
private struct MacStudioWaveformRow: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var playbackProgress: AudioPlayerViewModel.PlaybackProgress
    let tint: Color

    private var percentValue: String {
        "\(Int((playbackProgress.progress * 100).rounded())) %"
    }

    var body: some View {
        HStack(spacing: 8) {
            Text(playbackProgress.formattedCurrentTime)
                .font(.system(size: 11, weight: .semibold).monospacedDigit())
                .foregroundStyle(MacTheme.Text.secondary)
                .frame(width: 34, alignment: .leading)

            GeometryReader { geo in
                MacWaveformBars(
                    samples: audioPlayer.waveformSamples,
                    progress: playbackProgress.progress,
                    tint: tint,
                    barCount: 56
                )
                .contentShape(Rectangle())
                .onTapGesture { location in
                    guard audioPlayer.canSeek else { return }
                    audioPlayer.seek(to: max(0, min(1, location.x / geo.size.width)))
                }
            }
            .frame(height: 30)
            .opacity(audioPlayer.canSeek ? 1.0 : 0.8)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(MacInterfaceText.playerPosition)
            .accessibilityValue(percentValue)
            .accessibilityIdentifier("studio_inlinePlayer_scrubber")
            .accessibilityAdjustableAction { direction in
                guard audioPlayer.canSeek else { return }
                let step = 0.05
                let target = direction == .increment
                    ? min(1.0, playbackProgress.progress + step)
                    : max(0.0, playbackProgress.progress - step)
                audioPlayer.seek(to: target)
            }

            Text(audioPlayer.durationDisplayText)
                .font(.system(size: 11, weight: .semibold).monospacedDigit())
                .foregroundStyle(MacTheme.Text.secondary)
                .frame(width: 34, alignment: .trailing)
                .lineLimit(1)
        }
    }
}
