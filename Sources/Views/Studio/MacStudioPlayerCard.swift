import SwiftUI

/// The Studio dock card (the iOS `IOSStudioPlayerCard`): one card for the live
/// streaming preview and the completed take, so the live → complete transition
/// morphs in place.
///
/// The two phases are deliberately not the same shape. **Live** is a player:
/// waveform, clock, scrubber, play/pause, and the lanes' `textInput_cancelButton`
/// — it is the surface being watched while a take streams. **Complete** is a
/// result row: the take's identity and what you can do with it (Generate again,
/// Save As, Reveal in Finder, Dismiss), and no transport at all. Playback of a
/// finished take belongs to the sidebar footer card, which is on screen from
/// every destination; showing a second one here gave one sound two play buttons
/// and two clocks, which the maintainer asked to remove on 2026-09-16.
///
/// The shared `AudioPlayerViewModel` owns the audio either way, so both this
/// card and the sidebar's read and drive the same player.
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
    /// The completed take is a result row because the sidebar footer carries
    /// the transport. macOS lets the user collapse that column, which took the
    /// transport with it and left a finished take with no way to play it except
    /// through History — so the card takes it back when the sidebar is gone.
    @Environment(\.vocelloSidebarIsVisible) private var sidebarIsVisible

    let phase: Phase
    let tint: Color
    let onDismiss: () -> Void
    let onCancel: () -> Void
    let onRetry: () -> Void

    @State private var isConfirmingDismiss = false

    var body: some View {
        let shape = VocelloShape.stage()

        VStack(alignment: .leading, spacing: MacTheme.Spacing.snug) {
            // Transport belongs to the sidebar player, which is always on
            // screen; a finished take showing its own waveform, clock and
            // scrubber gave one sound two play buttons and two clocks
            // (maintainer decision 2026-09-16). The live preview keeps its
            // own, because it is the surface being watched while a take
            // streams and it carries Cancel.
            if showsTransport {
                MacStudioWaveformRow(tint: tint, isLive: phase.isLive)
            }
            controlsRow

            if let notice = phase.completedItem?.cadenceNotice {
                cadenceNoticeRow(notice)
            }

            if let playbackError = audioPlayer.playbackError {
                Text(playbackError)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Status.guarded)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, MacTheme.Spacing.lg)
        .padding(.top, MacTheme.Spacing.lg)
        .padding(.bottom, MacTheme.Spacing.lg)
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

    /// The live preview always shows transport; a completed take shows it only
    /// when the sidebar player is not on screen to carry it.
    private var showsTransport: Bool { phase.isLive || !sidebarIsVisible }

    /// See the note beside `sidebarIsVisible`.
    private var playPauseButton: some View {
        Button {
            AppLaunchConfiguration.performAnimated(MacTheme.Motion.stateChange) {
                audioPlayer.togglePlayPause()
            }
        } label: {
            Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                .font(.system(size: MacControl.field.glyph, weight: .semibold))
                .foregroundStyle(MacTheme.Text.onAccent)
                .macControlSquare(.field)
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
        .disabled(!audioPlayer.hasAudio)
        .accessibilityLabel(MacInterfaceText.menuPlayPause)
        .accessibilityValue(audioPlayer.isPlaying ? "pause" : "play")
        .accessibilityIdentifier(
            // Named for the phase, not for why it is on screen: a
            // completed take showing transport because the sidebar is
            // collapsed is still the inline player.
            phase.isLive ? "studio_livePreview_playPause" : "studio_inlinePlayer_playPause"
        )
    }

    private var controlsRow: some View {
        HStack(spacing: MacTheme.Spacing.snug) {
            if showsTransport {
                playPauseButton
            }

            VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                Text(phase.voiceName)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)
                HStack(spacing: MacTheme.Spacing.tight) {
                    Text(phase.modeLabel)
                        .macType(.rowMeta)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                    if phase.isLive {
                        HStack(spacing: MacTheme.Spacing.xs) {
                            Circle().fill(tint).frame(width: 6, height: 6)
                            Text(MacInterfaceText.playerLive)
                                .macType(.badge)
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
                        .macType(.buttonLabel)
                        .foregroundStyle(MacTheme.Text.primary)
                        .padding(.horizontal, MacTheme.Spacing.md)
                        .macControlHeight(.icon)
                        .background { VocelloShape.pill().fill(Color.white.opacity(0.06)) }
                        .overlay { VocelloShape.pill().stroke(Color.white.opacity(0.12), lineWidth: VocelloTheme.Stroke.hairline) }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(MacInterfaceText.studioStopGenerating)
                .accessibilityIdentifier("textInput_cancelButton")
            } else if let item = phase.completedItem {
                MacIconButton(
                    symbol: "arrow.clockwise",
                    label: MacInterfaceText.studioGenerateAgain,
                    accessibilityIdentifier: "studio_inlinePlayer_retry",
                    size: MacControl.icon.height,
                    action: onRetry
                )
                MacIconButton(
                    symbol: "square.and.arrow.down",
                    label: MacInterfaceText.historySaveAs,
                    accessibilityIdentifier: "studio_inlinePlayer_saveAs",
                    size: MacControl.icon.height,
                    action: { _ = MacHistoryFileActions.saveCopy(of: item.audioURL.path) }
                )
                MacIconButton(
                    symbol: "folder",
                    label: MacInterfaceText.revealInFinder,
                    accessibilityIdentifier: "studio_inlinePlayer_reveal",
                    size: MacControl.icon.height,
                    action: { MacHistoryFileActions.revealInFinder(item.audioURL.path) }
                )
                MacIconButton(
                    symbol: "xmark",
                    label: MacInterfaceText.playerClose,
                    accessibilityIdentifier: "studio_inlinePlayer_dismiss",
                    size: MacControl.icon.height,
                    action: { isConfirmingDismiss = true }
                )
            }
        }
        .appAnimation(MacTheme.Motion.stateChange, value: phase.isLive)
    }

    private func cadenceNoticeRow(_ notice: IOSStudioCadenceNotice) -> some View {
        HStack(alignment: .top, spacing: MacTheme.Spacing.sm) {
            Image(systemName: "waveform.path.badge.minus")
                .macType(.rowTitle)
                .foregroundStyle(MacTheme.Status.guarded)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: MacTheme.Spacing.xs) {
                Text(MacInterfaceText.studioUnusualPacing)
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                Text(MacInterfaceText.studioReviewTake)
                    .macType(.rowMeta)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, MacTheme.Spacing.snug)
        .padding(.vertical, MacTheme.Spacing.sm)
        .background {
            VocelloShape.input()
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
    /// Names the scrubber for the card it is in. The row appears in the live
    /// preview, and in a completed take only when a collapsed sidebar has left
    /// it carrying the transport.
    let isLive: Bool

    private var percentValue: String {
        "\(Int((playbackProgress.progress * 100).rounded())) %"
    }

    var body: some View {
        HStack(spacing: MacTheme.Spacing.sm) {
            Text(playbackProgress.formattedCurrentTime)
                .macType(.counter)
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
            .macControlHeight(.icon)
            .opacity(audioPlayer.canSeek ? 1.0 : 0.8)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(MacInterfaceText.playerPosition)
            .accessibilityValue(percentValue)
            .accessibilityIdentifier(isLive ? "studio_livePreview_scrubber" : "studio_inlinePlayer_scrubber")
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
                .frame(width: 34, alignment: .trailing)
                .lineLimit(1)
        }
    }
}
