import AppKit
import SwiftUI

/// Reference-clip capture sheet in the iOS recording-overlay language: a
/// tracked phase label, the large monospaced timer, the live level meter
/// driven by the real input, the coaching line, then review in place before
/// committing. Records a 24 kHz mono WAV through the shared
/// `ReferenceClipRecorder` and gates "Use This Clip" to the 10–20 s window
/// of the Voice Cloning reference contract. Presented as a window sheet from
/// the enrollment sheet and Voice Cloning; the `recordClip_*` identifiers are
/// the lane contract. The completed WAV is copied out of the recorder's temp
/// dir before dismissal and handed to `onComplete`.
struct MacRecordVoiceSheet: View {
    @ScaledMetric(relativeTo: .largeTitle) private var timerFontSize: CGFloat = 52
    var onComplete: (URL) -> Void

    @Environment(\.dismiss) private var dismiss

    @StateObject private var recorder = ReferenceClipRecorder()
    @StateObject private var reviewPlayer = ClipReviewPlayer()

    private let tint = MacTheme.Brand.modeClone

    private enum Stage {
        case idle, recording, captured
    }

    private var stage: Stage {
        if recorder.isRecording { return .recording }
        if recorder.lastSavedURL != nil { return .captured }
        return .idle
    }

    private var canUse: Bool {
        stage == .captured && recorder.elapsed >= ReferenceClipRecorder.minDuration
    }

    private var timerColor: Color {
        if recorder.elapsed >= ReferenceClipRecorder.minDuration
            && recorder.elapsed <= ReferenceClipRecorder.maxDuration {
            return tint
        }
        if recorder.elapsed > ReferenceClipRecorder.maxDuration {
            return MacTheme.Status.guarded
        }
        return MacTheme.Text.tertiary
    }

    private var phaseLabel: String {
        switch stage {
        case .recording: MacInterfaceText.recordPhaseRecording
        case .captured: MacInterfaceText.recordPhaseCaptured
        case .idle: MacInterfaceText.recordPhaseIdle
        }
    }

    private var hasInputDevice: Bool {
        ReferenceClipRecorder.hasAvailableInputDevice
    }

    private var statusLabel: String {
        switch stage {
        case .idle:
            if !hasInputDevice {
                return MacInterfaceText.recordNoMicrophone
            }
            if recorder.permissionDenied {
                return MacInterfaceText.recordMicrophoneDenied
            }
            if recorder.recordingFailed {
                return MacInterfaceText.recordFailedToStart
            }
            return MacInterfaceText.recordIdleHint
        case .recording:
            if recorder.elapsed < ReferenceClipRecorder.minDuration {
                return MacInterfaceText.recordKeepGoing
            }
            if recorder.elapsed <= ReferenceClipRecorder.maxDuration {
                return MacInterfaceText.recordSoundsGood
            }
            return MacInterfaceText.recordOverLimit
        case .captured:
            return canUse
                ? MacInterfaceText.recordReviewClip
                : MacInterfaceText.recordClipTooShort
        }
    }

    private var timeString: String {
        let total = max(0, Int(recorder.elapsed.rounded(.down)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline) {
                Text(MacInterfaceText.recordTitle)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(MacTheme.Text.primary)
                Spacer()
                MacIconButton(
                    symbol: "xmark",
                    label: MacInterfaceText.cancel,
                    accessibilityIdentifier: "recordClip_cancel",
                    size: 30,
                    symbolSize: 12
                ) {
                    recorder.stopWithoutSaving()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
            }

            VStack(spacing: 18) {
                Text(phaseLabel.uppercased())
                    .font(.system(size: 12, weight: .semibold))
                    .tracking(1.4)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)

                Text(timeString)
                    .font(.system(size: timerFontSize, weight: .bold, design: .monospaced))
                    .monospacedDigit()
                    .foregroundStyle(timerColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
                    .accessibilityIdentifier("recordClip_timer")

                MacLiveLevelMeter(
                    levels: recorder.levels,
                    tint: tint,
                    isActive: recorder.isRecording
                )
                .frame(height: 72)
                .opacity(recorder.isRecording ? 1 : (recorder.elapsed > 0 ? 0.8 : 0.4))
                .accessibilityIdentifier("recordClip_levelMeter")

                Text(statusLabel)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(MacTheme.Text.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 340)
                    .accessibilityIdentifier("recordClip_status")

                if stage == .captured {
                    reviewRow
                        .transition(.opacity)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .appAnimation(MacTheme.Motion.stateChange, value: recorder.isRecording)

            HStack(spacing: 10) {
                Spacer()

                switch stage {
                case .idle:
                    MacPrimaryCTAButton(
                        title: MacInterfaceText.recordRecord,
                        symbol: "mic.fill",
                        tint: tint,
                        isEnabled: !recorder.permissionDenied && hasInputDevice
                    ) {
                        Task { await recorder.start() }
                    }
                    .accessibilityIdentifier("recordClip_record")
                case .recording:
                    MacPrimaryCTAButton(
                        title: MacInterfaceText.recordStop,
                        symbol: "stop.fill",
                        tint: tint
                    ) {
                        _ = recorder.stopAndSave()
                    }
                    .accessibilityIdentifier("recordClip_stop")
                case .captured:
                    Button(MacInterfaceText.recordRetake) {
                        reviewPlayer.stop()
                        recorder.reset()
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("recordClip_retake")

                    MacPrimaryCTAButton(
                        title: canUse ? MacInterfaceText.recordUseClip : MacInterfaceText.recordNeedTenSeconds,
                        symbol: canUse ? "checkmark" : nil,
                        tint: tint,
                        isEnabled: canUse
                    ) {
                        useClip()
                    }
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("recordClip_use")
                }
            }
        }
        .padding(20)
        // Min instead of fixed: at large accessibility text sizes a fixed
        // width squeezed the coaching copy instead of growing.
        .frame(minWidth: 480, maxWidth: 560)
        .background(MacTheme.canvasGradient)
        .task {
            await recorder.requestPermissionIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted the microphone in System
            // Settings; clear the denied state without a relaunch.
            recorder.refreshPermissionState()
        }
        .onDisappear {
            reviewPlayer.stop()
            recorder.stopWithoutSaving()
        }
        .onChange(of: recorder.lastSavedURL) { _, url in
            if let url {
                reviewPlayer.load(url: url)
            } else {
                reviewPlayer.stop()
            }
        }
        .alert(MacInterfaceText.recordMicrophoneDeniedTitle, isPresented: $recorder.showsPermissionAlert) {
            Button(MacInterfaceText.recordOpenSystemSettings) {
                if let url = URL(
                    string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
                ) {
                    NSWorkspace.shared.open(url)
                }
            }
            Button(MacInterfaceText.cancel, role: .cancel) {
                dismiss()
            }
        } message: {
            Text(MacInterfaceText.recordMicrophoneDeniedDetail)
        }
    }

    // MARK: - Review

    private var reviewRow: some View {
        HStack(spacing: 12) {
            Button {
                reviewPlayer.toggle()
            } label: {
                ZStack {
                    Circle().fill(tint.opacity(0.2))
                    Image(systemName: reviewPlayer.isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(tint)
                }
                .frame(width: 36, height: 36)
                .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(reviewPlayer.isPlaying ? MacInterfaceText.recordPauseReview : MacInterfaceText.recordPlayReview)
            .accessibilityIdentifier("recordClip_reviewToggle")

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule(style: .continuous)
                        .fill(Color.white.opacity(0.10))
                    Capsule(style: .continuous)
                        .fill(tint.opacity(0.75))
                        .frame(width: max(4, geo.size.width * reviewPlayer.progress))
                }
            }
            .frame(height: 6)

            Text(durationString)
                .font(.caption.monospacedDigit())
                .foregroundStyle(MacTheme.Text.secondary)
        }
        .padding(.horizontal, 24)
    }

    private var durationString: String {
        let total = max(0, Int(reviewPlayer.duration.rounded()))
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: - Completion

    /// Copy the finished recording out of the recorder's temp dir so the
    /// recorder's teardown cannot delete it before enrollment, then hand the
    /// stable URL to the caller.
    private func useClip() {
        guard let url = recorder.lastSavedURL else { return }
        reviewPlayer.stop()
        let stable = ReferenceClipRecordingStash.copyToStableTemp(url) ?? url
        onComplete(stable)
        dismiss()
    }
}
