import AppKit
import SwiftUI

/// Mac-native reference-clip capture sheet — the macOS counterpart of the iOS
/// `IOSRecordingOverlay`. Records a 24 kHz mono PCM WAV via the shared
/// `ReferenceClipRecorder`, shows a live amplitude meter, and gates "Use This
/// Clip" to the 10–20 s window required by the Voice Cloning reference
/// contract. After capture the clip can be reviewed in place (`ClipReviewPlayer`)
/// before committing.
///
/// Presented as a `.sheet` from `SavedVoiceSheet` ("Record…" next to
/// "Browse…") and `VoiceCloningView`. The completed WAV is copied out of the
/// recorder's temp dir before dismissal (the recorder deletes its own file on
/// teardown) and handed to `onComplete`.
struct RecordReferenceClipSheet: View {
    var onComplete: (URL) -> Void

    @Environment(\.dismiss) private var dismiss

    @StateObject private var recorder = ReferenceClipRecorder()
    @StateObject private var reviewPlayer = ClipReviewPlayer()

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
            return AppTheme.voiceCloning
        }
        if recorder.elapsed > ReferenceClipRecorder.maxDuration {
            return .orange
        }
        return .secondary
    }

    private var phaseLabel: String {
        switch stage {
        case .recording: return "Recording"
        case .captured: return "Captured"
        case .idle: return "Reference clip"
        }
    }

    private var hasInputDevice: Bool {
        ReferenceClipRecorder.hasAvailableInputDevice
    }

    private var statusLabel: String {
        switch stage {
        case .idle:
            if !hasInputDevice {
                return "No microphone detected. Connect a microphone or audio-input device to record."
            }
            if recorder.permissionDenied {
                return "Microphone access is denied. Enable it in System Settings to record."
            }
            if recorder.recordingFailed {
                return "Recording couldn't start. Check your microphone in System Settings → Sound, then try again."
            }
            return "Click Record, then read 10–20 s of clean, natural speech. Quiet room. One voice."
        case .recording:
            if recorder.elapsed < ReferenceClipRecorder.minDuration {
                return "Keep recording. 10 second minimum."
            }
            if recorder.elapsed <= ReferenceClipRecorder.maxDuration {
                return "Sounds good. Click Stop when ready."
            }
            return "Over 20 seconds. Stop now."
        case .captured:
            return canUse
                ? "Review the clip, then use it or retake."
                : "Clip is under 10 seconds. Retake a longer one."
        }
    }

    private var timeString: String {
        let total = max(0, Int(recorder.elapsed.rounded(.down)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Record Reference Clip")
                .font(.title2.weight(.bold))

            VStack(spacing: 14) {
                Text(phaseLabel.uppercased())
                    .font(.caption.weight(.semibold))
                    .tracking(1.4)
                    .foregroundStyle(.secondary)

                Text(timeString)
                    .font(.system(size: 44, weight: .bold, design: .monospaced))
                    .monospacedDigit()
                    .foregroundStyle(timerColor)
                    .accessibilityIdentifier("recordClip_timer")

                LiveLevelMeterBars(
                    levels: recorder.levels,
                    tint: AppTheme.voiceCloning,
                    isActive: recorder.isRecording
                )
                .frame(height: 64)
                .opacity(recorder.isRecording ? 1 : (recorder.elapsed > 0 ? 0.8 : 0.4))
                .accessibilityIdentifier("recordClip_levelMeter")

                Text(statusLabel)
                    .font(.callout)
                    .foregroundStyle(.secondary)
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
            .appAnimation(AppTheme.Motion.state, value: recorder.isRecording)

            HStack(spacing: 10) {
                Button("Cancel") {
                    recorder.stopWithoutSaving()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
                .accessibilityIdentifier("recordClip_cancel")

                Spacer()

                switch stage {
                case .idle:
                    Button {
                        Task { await recorder.start() }
                    } label: {
                        Label("Record", systemImage: "mic.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(AppTheme.voiceCloning)
                    .disabled(recorder.permissionDenied || !hasInputDevice)
                    .accessibilityIdentifier("recordClip_record")
                case .recording:
                    Button {
                        _ = recorder.stopAndSave()
                    } label: {
                        Label("Stop", systemImage: "stop.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(AppTheme.voiceCloning)
                    .accessibilityIdentifier("recordClip_stop")
                case .captured:
                    Button("Retake") {
                        reviewPlayer.stop()
                        recorder.reset()
                    }
                    .accessibilityIdentifier("recordClip_retake")

                    Button {
                        useClip()
                    } label: {
                        Label(canUse ? "Use This Clip" : "Need 10 s", systemImage: "checkmark")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(AppTheme.voiceCloning)
                    .disabled(!canUse)
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("recordClip_use")
                }
            }
        }
        .padding(20)
        .frame(width: 480)
        .task {
            await recorder.requestPermissionIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // The user may have just granted the microphone in System
            // Settings — clear the denied state without a relaunch.
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
        .alert("Microphone access denied", isPresented: $recorder.showsPermissionAlert) {
            Button("Open System Settings") {
                if let url = URL(
                    string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
                ) {
                    NSWorkspace.shared.open(url)
                }
            }
            Button("Cancel", role: .cancel) {
                dismiss()
            }
        } message: {
            Text("Vocello needs the microphone to record reference clips. Enable it in System Settings to continue.")
        }
    }

    // MARK: - Review

    private var reviewRow: some View {
        HStack(spacing: 10) {
            Button {
                reviewPlayer.toggle()
            } label: {
                Image(systemName: reviewPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.bordered)
            .clipShape(Circle())
            .accessibilityLabel(reviewPlayer.isPlaying ? "Pause review" : "Play review")
            .accessibilityIdentifier("recordClip_reviewToggle")

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule(style: .continuous)
                        .fill(AppTheme.fieldFill)
                    Capsule(style: .continuous)
                        .fill(AppTheme.voiceCloning.opacity(0.75))
                        .frame(width: max(4, geo.size.width * reviewPlayer.progress))
                }
            }
            .frame(height: 6)

            Text(durationString)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 24)
    }

    private var durationString: String {
        let total = max(0, Int(reviewPlayer.duration.rounded()))
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    // MARK: - Completion

    /// Copy the finished recording out of the recorder's temp dir so the
    /// recorder's `.onDisappear` cleanup can't delete it before enrollment,
    /// then hand the stable URL to the caller.
    private func useClip() {
        guard let url = recorder.lastSavedURL else { return }
        reviewPlayer.stop()
        let stable = ReferenceClipRecordingStash.copyToStableTemp(url) ?? url
        onComplete(stable)
        dismiss()
    }
}

// MARK: - Live level meter

/// Scrolling mic-level meter (newest sample on the right), driven by the REAL
/// input (`recorder.levels`) so it visibly rises when the user speaks — honest
/// feedback that the voice is heard + recorded. Data-driven (no decorative
/// animation), so it stays truthful under Reduce Motion.
private struct LiveLevelMeterBars: View {
    let levels: [Double]
    let tint: Color
    var isActive: Bool = true

    private let barCount = 48
    private let spacing: CGFloat = 3

    var body: some View {
        // Canvas instead of a 48-Capsule ForEach: the meter redraws at
        // 12.5 Hz while recording, so one draw call beats 48 view updates
        // (matters on the 8 GB tier when generation runs concurrently).
        Canvas { context, size in
            let barWidth = max(2.5, (size.width - spacing * CGFloat(barCount - 1)) / CGFloat(barCount))
            for i in 0..<barCount {
                let level = sample(at: i)
                let height = max(3, size.height * CGFloat(0.04 + 0.96 * level))
                let x = CGFloat(i) * (barWidth + spacing)
                let y = (size.height - height) / 2
                let rect = CGRect(x: x, y: y, width: barWidth, height: height)
                let gradient = Gradient(colors: [
                    tint.opacity(opacity(at: i)),
                    tint.opacity(0.55 * opacity(at: i)),
                ])
                context.fill(
                    Path(roundedRect: rect, cornerRadius: barWidth / 2),
                    with: .linearGradient(
                        gradient,
                        startPoint: CGPoint(x: rect.midX, y: rect.minY),
                        endPoint: CGPoint(x: rect.midX, y: rect.maxY)
                    )
                )
            }
        }
    }

    /// Bar index 0 = left/oldest … `barCount-1` = right/newest; left-pad with
    /// silence until the buffer fills so the live edge scrolls in from the right.
    private func sample(at index: Int) -> Double {
        let offsetFromNewest = (barCount - 1) - index
        let srcIndex = levels.count - 1 - offsetFromNewest
        guard srcIndex >= 0, srcIndex < levels.count else { return 0 }
        return min(1, max(0, levels[srcIndex]))
    }

    /// Gentle left-fade so the live leading edge (the current voice) reads brightest.
    private func opacity(at index: Int) -> Double {
        guard isActive else { return 0.3 }
        let t = Double(index) / Double(max(1, barCount - 1))
        return 0.4 + 0.6 * t
    }
}
