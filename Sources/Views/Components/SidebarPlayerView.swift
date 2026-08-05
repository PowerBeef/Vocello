import SwiftUI

/// Compact vertical audio player designed for the sidebar's narrow width.
struct SidebarPlayerView: View {
    @EnvironmentObject var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject var playbackProgress: AudioPlayerViewModel.PlaybackProgress
    let inlinePlayerActivity: ActivityStatus?

    var body: some View {
        if audioPlayer.hasAudio {
            VStack(alignment: .leading, spacing: 7) {
                Text("Player")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)

                HStack {
                    Text(audioPlayer.currentTitle)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                        .foregroundStyle(.primary)

                    if audioPlayer.isLiveStream {
                        Text("Live")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(AppTheme.accent)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            #if QW_UI_LIQUID
                            .glassBadge(tint: AppTheme.accent)
                            #else
                            .background(
                                Capsule()
                                    .fill(AppTheme.accent.opacity(0.14))
                            )
                            #endif
                            .accessibilityIdentifier("sidebarPlayer_liveBadge")
                    }

                    Spacer()

                    Button {
                        AppLaunchConfiguration.performAnimated(.easeInOut(duration: 0.25)) {
                            audioPlayer.dismiss()
                        }
                    } label: {
                        Image(systemName: "xmark")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("sidebarPlayer_dismiss")
                }

                GeometryReader { geo in
                    WaveformView(samples: audioPlayer.waveformSamples, progress: playbackProgress.progress)
                        .contentShape(Rectangle())
                        .onTapGesture { location in
                            guard audioPlayer.canSeek else { return }
                            let fraction = max(0, min(1, location.x / geo.size.width))
                            audioPlayer.seek(to: fraction)
                        }
                }
                .frame(height: 24)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Waveform")
                .opacity(audioPlayer.canSeek ? 1.0 : 0.75)
                .accessibilityIdentifier("sidebarPlayer_waveform")
                .accessibilityValue(audioPlayer.canSeek ? "seek enabled" : "seek disabled")

                HStack(spacing: 6) {
                    Button {
                        AppLaunchConfiguration.performAnimated(.spring(response: 0.3, dampingFraction: 0.7)) {
                            audioPlayer.togglePlayPause()
                        }
                    } label: {
                        Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(AppTheme.accent)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("sidebarPlayer_playPause")
                    .accessibilityValue(audioPlayer.isPlaying ? "pause" : "play")

                    Text("\(playbackProgress.formattedCurrentTime) / \(audioPlayer.durationDisplayText)")
                        .font(.caption.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("sidebarPlayer_time")

                    Spacer(minLength: 0)

                    // Audit Batch 6a: dropped the redundant "Playback" /
                    // "Preview" trailing role label. Play/pause + time
                    // already imply playback; the "Live" capsule next to
                    // the title still distinguishes streaming.
                }

                if let inlinePlayerActivity {
                    InlineLivePreviewStatusView(activity: inlinePlayerActivity)
                }

                if let playbackError = audioPlayer.playbackError {
                    Text(playbackError)
                        .font(.caption2)
                        .foregroundStyle(.orange)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("sidebarPlayer_error")
                }
            }
            .transition(
                AppLaunchConfiguration.current.animationsEnabled
                ? .move(edge: .bottom).combined(with: .opacity)
                : .identity
            )
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("sidebarPlayer_bar")
        }
    }
}

private struct InlineLivePreviewStatusView: View {
    let activity: ActivityStatus

    private var progressFraction: Double? {
        guard let fraction = activity.fraction else { return nil }
        return min(max(fraction, 0.0), 1.0)
    }

    private var percentLabel: String? {
        guard let progressFraction else { return nil }
        let percent = Int((progressFraction * 100.0).rounded())
        return "\(percent)%"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "waveform")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(AppTheme.accent)

                Text(activity.label)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                Spacer(minLength: 0)

                if let percentLabel {
                    Text(percentLabel)
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(AppTheme.textMuted)
                }
            }

            if let progressFraction {
                ProgressView(value: progressFraction, total: 1.0)
                    .tint(AppTheme.inlinePreviewProgressTint)
                    .scaleEffect(y: 0.5, anchor: .center)
                    .accessibilityIdentifier("sidebarPlayer_liveProgress")
                    .accessibilityValue(percentLabel ?? "in progress")
            }
        }
        .padding(.top, 2)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sidebarPlayer_liveStatus")
        .accessibilityLabel(activity.label)
        .accessibilityValue(percentLabel ?? "in progress")
    }
}
