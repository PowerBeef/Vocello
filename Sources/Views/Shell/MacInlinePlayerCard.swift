import SwiftUI

/// Compact now-playing card: title and transport above a slim waveform.
/// The tint follows the audio's origin, independently of the selected screen.
/// One card serves the live stream and the completed take, so the transition is an in-place morph. Keeps every
/// `sidebarPlayer_*` identifier the lanes assert.
struct MacInlinePlayerCard: View {
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    let inlinePlayerActivity: MacShellActivity?
    private var tint: Color {
        audioPlayer.currentGenerationMode.map { MacTheme.tint(for: $0) } ?? MacTheme.voicesTint
    }

    var body: some View {
        let shape = VocelloShape.stage()

        VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
            controlsRow
            if audioPlayer.hasAudio {
                MacInlineWaveformRow(tint: tint)
            }

            if let inlinePlayerActivity {
                MacInlineLiveStatusRow(activity: inlinePlayerActivity, tint: tint)
            }

            if let playbackError = audioPlayer.playbackError {
                Text(playbackError)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("sidebarPlayer_error")
            }
        }
        .padding(.horizontal, MacTheme.Spacing.md)
        .padding(.top, MacTheme.Spacing.md)
        .padding(.bottom, MacTheme.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { shape.fill(Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.85)) }
        .overlay { shape.stroke(Color.white.opacity(0.10), lineWidth: VocelloTheme.Stroke.hairline) }
        .shadow(
            color: VocelloTheme.Elevation.cardColor,
            radius: VocelloTheme.Elevation.cardRadius,
            x: 0,
            y: VocelloTheme.Elevation.cardY
        )
        .transition(
            AppLaunchConfiguration.current.animationsEnabled
                ? .move(edge: .bottom).combined(with: .opacity)
                : .identity
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sidebarPlayer_bar")
    }

    private var controlsRow: some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            Button {
                AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                    audioPlayer.togglePlayPause()
                }
            } label: {
                Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: MacControl.icon.glyph, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.onAccent)
                    .macControlSquare(.icon)
                    .background {
                        Circle().fill(
                            LinearGradient(
                                colors: [tint, tint.mix(with: .black, by: 0.20, in: .perceptual)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                    }
                    .overlay { Circle().stroke(Color.white.opacity(0.18), lineWidth: VocelloTheme.Stroke.hairline) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(audioPlayer.isPlaying ? MacInterfaceText.playerPause : MacInterfaceText.playerPlay)
            .accessibilityIdentifier("sidebarPlayer_playPause")
            .accessibilityValue(audioPlayer.isPlaying ? "pause" : "play")
            .disabled(!audioPlayer.hasAudio)

            VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                Text(audioPlayer.currentTitle)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)

                if audioPlayer.isLiveStream {
                    HStack(spacing: MacTheme.Spacing.tight) {
                        Circle()
                            .fill(tint)
                            .frame(width: 6, height: 6)
                        Text(MacInterfaceText.playerLive)
                            .macType(.badge)
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
                    .font(.system(size: MacControl.icon.glyph, weight: .semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .macControlSquare(.icon)
                    .background { Circle().fill(Color.white.opacity(0.06)) }
                    .overlay { Circle().stroke(Color.white.opacity(0.10), lineWidth: VocelloTheme.Stroke.hairline) }
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

    /// Matches the Studio player card's time column, so the two cards line up
    /// when both are on screen.
    private static let timeColumnWidth: CGFloat = 34

    private var percentValue: String {
        "\(Int((playbackProgress.progress * 100).rounded())) %"
    }

    var body: some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            Text(playbackProgress.formattedCurrentTime)
                .macType(.counter)
                .foregroundStyle(MacTheme.Text.secondary)
                .frame(width: Self.timeColumnWidth, alignment: .leading)
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
            .frame(height: 24)
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
                .macType(.counter)
                .foregroundStyle(MacTheme.Text.secondary)
                .frame(width: Self.timeColumnWidth, alignment: .trailing)
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
        VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
            HStack(spacing: MacTheme.Spacing.tight) {
                Image(systemName: "waveform")
                    .macType(.captionEmphasis)
                    .foregroundStyle(tint)
                    .accessibilityHidden(true)

                Text(activity.label)
                    .macType(.captionEmphasis)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)

                Spacer(minLength: 0)

                if let percentLabel {
                    Text(verbatim: percentLabel)
                        .macType(.counter)
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

// MARK: - Footer

/// Shared transport host: sidebar normally, detail footer when the sidebar is hidden.
struct MacPlaybackFooter: View {
    let isSidebar: Bool
    @Environment(\.vocelloSidebarIsVisible) private var sidebarVisible
    @Environment(MacAppModel.self) private var appModel

    private var studioOwnsTransport: Bool {
        let coordinator: StudioGenerationCoordinator
        switch appModel.selectedItem {
        case .customVoice: coordinator = appModel.customCoordinator
        case .voiceDesign: coordinator = appModel.designCoordinator
        case .voiceCloning: coordinator = appModel.cloneCoordinator
        default: return false
        }
        if coordinator.isGenerating {
            return coordinator.liveItem != nil && audioPlayer.isLiveStream
                && audioPlayer.activeGeneratePreviewVisibilityState == .ready
        }
        guard let output = coordinator.lastCompletedOutput else { return false }
        return audioPlayer.currentFilePath == output.audioURL.path
            || audioPlayer.playbackError(forFile: output.audioURL.path) != nil
    }
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore

    private var status: MacShellStatus {
        MacShellStatusPresentation.resolve(
            snapshot: ttsEngineStore.snapshot,
            prefersInlinePresentation: audioPlayer.isLiveStream
        )
    }

    private var footerPresentation: MacShellFooterPresentation {
        MacShellFooterPresentation.resolve(
            status: status,
            isLiveStream: audioPlayer.isLiveStream
        )
    }

    private var placement: PlaybackTransportPlacement {
        .resolve(hasAudio: audioPlayer.hasAudio || audioPlayer.playbackError != nil,
                 studioOwnsAudio: studioOwnsTransport, sidebarVisible: sidebarVisible)
    }

    @ViewBuilder
    var body: some View {
        if isSidebar || placement == .detail {
            VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
                if placement == (isSidebar ? .sidebar : .detail) {
                    MacInlinePlayerCard(inlinePlayerActivity: footerPresentation.inlinePlayerActivity)
                        .frame(maxWidth: isSidebar ? .infinity : 560)
                        .frame(maxWidth: .infinity)
                }

                if isSidebar && footerPresentation.showsStandaloneStatus && !studioOwnsTransport {
                    MacStatusStrip(
                        status: status,
                        clearError: { ttsEngineStore.clearVisibleError() }
                    )
                }
            }
            .padding(.horizontal, MacShellMetrics.sidebarInset)
            .padding(.top, MacTheme.Spacing.sm)
            .padding(.bottom, MacShellMetrics.sidebarInset)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                LinearGradient(
                    colors: [MacTheme.Surface.canvasBottom.opacity(0), MacTheme.Surface.canvasBottom.opacity(0.9)],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()
            )
        }
    }
}
