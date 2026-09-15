import SwiftUI

/// The iOS Studio player card (`IOSStudioPlayerCard`) at sidebar width: the
/// waveform row on top, then a mode-tinted play/pause control, the take's
/// title and the trailing dismiss. One card serves the live stream and the
/// completed take, so the transition is an in-place morph. Keeps every
/// `sidebarPlayer_*` identifier the lanes assert.
struct MacInlinePlayerCard: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    let inlinePlayerActivity: MacShellActivity?
    var tint: Color = MacTheme.accent

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)

        VStack(alignment: .leading, spacing: 10) {
            MacInlineWaveformRow(tint: tint)
            controlsRow

            if let inlinePlayerActivity {
                MacInlineLiveStatusRow(activity: inlinePlayerActivity, tint: tint)
            }

            if let playbackError = audioPlayer.playbackError {
                Text(playbackError)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("sidebarPlayer_error")
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 12)
        .padding(.bottom, 12)
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
        .accessibilityIdentifier("sidebarPlayer_bar")
    }

    private var controlsRow: some View {
        HStack(spacing: 8) {
            Button {
                AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                    audioPlayer.togglePlayPause()
                }
            } label: {
                Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.onAccent)
                    .frame(width: 36, height: 36)
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
            .accessibilityLabel(MacInterfaceText.menuPlayPause)
            .accessibilityValue(audioPlayer.isPlaying ? "pause" : "play")
            .accessibilityIdentifier("sidebarPlayer_playPause")

            VStack(alignment: .leading, spacing: 2) {
                Text(audioPlayer.currentTitle)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)

                if audioPlayer.isLiveStream {
                    HStack(spacing: 5) {
                        Circle()
                            .fill(tint)
                            .frame(width: 6, height: 6)
                        Text(MacInterfaceText.playerLive)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(MacTheme.Text.secondary)
                            .lineLimit(1)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("sidebarPlayer_liveBadge")
                }
            }
            .padding(.leading, 2)

            Spacer(minLength: 0)

            Button {
                AppLaunchConfiguration.performAnimated(MacTheme.Motion.easeOut) {
                    audioPlayer.dismiss()
                }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .frame(width: 30, height: 30)
                    .background { Circle().fill(Color.white.opacity(0.06)) }
                    .overlay { Circle().stroke(Color.white.opacity(0.10), lineWidth: 0.5) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(MacInterfaceText.playerClose)
            .accessibilityIdentifier("sidebarPlayer_dismiss")
        }
        .appAnimation(MacTheme.Motion.stateChange, value: audioPlayer.isLiveStream)
    }
}

/// The per-tick slice of the card: only this row subscribes to the playback
/// progress object, so the card chrome does not re-render on every tick.
private struct MacInlineWaveformRow: View {
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
                .frame(width: 32, alignment: .leading)
                .accessibilityIdentifier("sidebarPlayer_time")
                .accessibilityValue(
                    "\(playbackProgress.formattedCurrentTime) / \(audioPlayer.durationDisplayText)"
                )

            GeometryReader { geo in
                MacWaveformBars(
                    samples: audioPlayer.waveformSamples,
                    progress: playbackProgress.progress,
                    tint: tint
                )
                .contentShape(Rectangle())
                .onTapGesture { location in
                    guard audioPlayer.canSeek else { return }
                    audioPlayer.seek(to: max(0, min(1, location.x / geo.size.width)))
                }
            }
            .frame(height: 26)
            .opacity(audioPlayer.canSeek ? 1.0 : 0.8)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(MacInterfaceText.playerPosition)
            .accessibilityValue(percentValue)
            .accessibilityIdentifier("sidebarPlayer_waveform")
            // VoiceOver seek: the waveform is click-only, which leaves
            // assistive users with no way to scrub at all.
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
                .frame(width: 32, alignment: .trailing)
                .lineLimit(1)
        }
    }
}

private struct MacInlineLiveStatusRow: View {
    let activity: MacShellActivity
    let tint: Color

    private var progressFraction: Double? {
        activity.fraction.map { min(max($0, 0.0), 1.0) }
    }

    private var percentLabel: String? {
        progressFraction.map { "\(Int(($0 * 100.0).rounded()))%" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "waveform")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(tint)
                    .accessibilityHidden(true)

                Text(activity.label)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)

                Spacer(minLength: 0)

                if let percentLabel {
                    Text(verbatim: percentLabel)
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(MacTheme.Text.tertiary)
                }
            }

            if let progressFraction {
                ProgressView(value: progressFraction, total: 1.0)
                    .tint(tint)
                    .scaleEffect(y: 0.5, anchor: .center)
                    .accessibilityIdentifier("sidebarPlayer_liveProgress")
                    .accessibilityValue(percentLabel ?? MacInterfaceText.shellInProgress)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sidebarPlayer_liveStatus")
        .accessibilityLabel(activity.label)
        .accessibilityValue(percentLabel ?? MacInterfaceText.shellInProgress)
    }
}
