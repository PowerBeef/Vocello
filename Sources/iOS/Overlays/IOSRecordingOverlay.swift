import AVFoundation
import SwiftUI

/// Full-screen reference-clip capture surface from the iOS design reference
/// prototype (design_references/Vocello iOS/chrome.jsx RecordingOverlay).
/// Records a 24 kHz mono PCM WAV using AVAudioRecorder, shows a live
/// amplitude meter, and gates the "Use this clip" CTA to the 10-20s window
/// required by the Voice Cloning reference contract.
///
/// Consumers present this as a `.fullScreenCover` and receive the completed
/// WAV file URL via `onComplete`. The view does its own permission request;
/// callers don't need to pre-check microphone access.
struct IOSRecordingOverlay: View {
    var onComplete: (URL) -> Void
    var onCancel: () -> Void

    @StateObject private var recorder = ReferenceClipRecorder()
    /// When true, the clip was handed to `onComplete` — skip `stopWithoutSaving` on
    /// `.onDisappear` so the temp WAV survives until the caller stashes/imports it.
    @State private var didHandOffClip = false

    @Environment(\.iosReduceMotionEnabled) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            IOSModeBackdrop(tint: Theme.Brand.modeClone, intensity: .warm)
            Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255)
                .opacity(0.70)
                .ignoresSafeArea()

            VStack(spacing: 0) {
                topBar
                captureStage
                Spacer()
                controls
            }
            .padding(.horizontal, 24)
            .padding(.top, 56)
            .padding(.bottom, 60)
        }
        .preferredColorScheme(.dark)
        .interactiveDismissDisabled(true)
        .task {
            await recorder.requestPermissionIfNeeded()
        }
        .onChange(of: scenePhase) { _, newPhase in
            // Clear the denied state without a relaunch if the user granted
            // mic access in iOS Settings and returned (mirrors macOS).
            if newPhase == .active {
                recorder.refreshPermissionState()
            }
        }
        .onDisappear {
            guard !didHandOffClip else { return }
            recorder.stopWithoutSaving()
        }
        .alert("Microphone access denied", isPresented: $recorder.showsPermissionAlert) {
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            Button("Cancel", role: .cancel) {
                onCancel()
            }
        } message: {
            Text("Vocello needs the microphone to record reference clips. Enable it in Settings to continue.")
        }
    }

    private func handOffClip(at url: URL) {
        didHandOffClip = true
        onComplete(url)
    }

    // MARK: - Top bar

    private var topBar: some View {
        HStack {
            Spacer()

            Button {
                recorder.stopWithoutSaving()
                onCancel()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 40, height: 40)
                    .background {
                        Circle()
                            .fill(Color.white.opacity(0.06))
                    }
                    .overlay {
                        Circle()
                            .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosRecord_close")
            .accessibilityLabel("Close")
        }
    }

    // MARK: - Capture stage

    private var progressColor: Color {
        if recorder.elapsed >= ReferenceClipRecorder.minDuration && recorder.elapsed <= ReferenceClipRecorder.maxDuration {
            return Theme.Brand.modeClone
        }
        if recorder.elapsed > ReferenceClipRecorder.maxDuration {
            return Color.orange
        }
        return Theme.Text.tertiary
    }

    private var captureStage: some View {
        VStack(spacing: 28) {
            VStack(spacing: 28) {
                Text(phaseLabel.uppercased())
                    .iosScaledFont(size: 13, weight: .semibold, relativeTo: .footnote)
                    .tracking(1.56)
                    .foregroundStyle(Theme.Text.secondary)

                Text(timeString)
                    .iosScaledFont(size: 56, weight: .bold, design: .monospaced, relativeTo: .largeTitle)
                    .tracking(-1.12)
                    .foregroundStyle(progressColor)
                    .monospacedDigit()
                    // At the largest accessibility sizes the scaled jumbo
                    // numeral approaches full screen width; shrink-to-fit
                    // beats wrapping a running timer onto two lines.
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)

                Text("Read 10-20 s of clean, natural speech. Quiet room. One voice.")
                    .iosScaledFont(size: 14, weight: .medium, relativeTo: .footnote)
                    .foregroundStyle(Theme.Text.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 280)
            }

            // LIVE level meter driven by the real mic amplitude — bars rise when you speak
            // and fall when silent, so you can see your voice is heard + recorded.
            IOSLiveLevelMeter(
                levels: recorder.levels,
                tint: Theme.Brand.modeClone,
                isActive: recorder.isRecording
            )
            .frame(height: 96)
            .opacity(recorder.isRecording ? 1 : (recorder.elapsed > 0 ? 0.8 : 0.4))

            Text(statusLabel)
                .iosScaledFont(size: 14, weight: .medium, relativeTo: .footnote)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 280)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var phaseLabel: String {
        if recorder.isRecording { return "Recording" }
        if recorder.elapsed > 0 { return "Captured" }
        return "Reference clip"
    }

    private var statusLabel: String {
        if recorder.wasInterrupted && !recorder.isRecording && recorder.elapsed > 0 {
            return "Recording was interrupted. The clip up to that point was kept."
        }
        if !recorder.isRecording && recorder.elapsed == 0 {
            return "Tap Record to begin."
        }
        if recorder.elapsed < ReferenceClipRecorder.minDuration {
            return "Keep recording. 10 second minimum."
        }
        if recorder.elapsed <= ReferenceClipRecorder.maxDuration {
            return "Sounds good. Tap stop when ready."
        }
        return "Over 20 seconds. Stop now."
    }

    private var timeString: String {
        let total = max(0, Int(recorder.elapsed.rounded(.down)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    // MARK: - Controls

    private var controls: some View {
        HStack(spacing: 12) {
            if recorder.isRecording {
                IOSPrimaryCTAButton(
                    title: "Stop",
                    symbol: "stop.fill",
                    tint: Theme.Brand.modeClone,
                    isEnabled: true,
                    action: {
                        if let url = recorder.stopAndSave() {
                            handOffClip(at: url)
                        }
                    }
                )
                .accessibilityIdentifier("iosRecord_stop")
            } else if recorder.elapsed > 0 {
                Button("Retake") {
                    recorder.reset()
                }
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.Text.secondary)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background {
                    Capsule(style: .continuous)
                        .fill(Theme.Surface.glassSurfaceMuted)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("iosRecord_retake")

                let canUse = recorder.elapsed >= ReferenceClipRecorder.minDuration
                IOSPrimaryCTAButton(
                    title: canUse ? "Use this clip" : "Need 10 s",
                    symbol: canUse ? "checkmark" : nil,
                    tint: Theme.Brand.modeClone,
                    isEnabled: canUse,
                    action: {
                        if let url = recorder.lastSavedURL {
                            handOffClip(at: url)
                        }
                    }
                )
                .accessibilityIdentifier("iosRecord_use")
            } else {
                IOSPrimaryCTAButton(
                    title: "Record",
                    symbol: "mic.fill",
                    tint: Theme.Brand.modeClone,
                    isEnabled: !recorder.permissionDenied,
                    action: {
                        Task { await recorder.start() }
                    }
                )
                .accessibilityIdentifier("iosRecord_start")
            }
        }
    }
}

// MARK: - Live level meter

/// A clean scrolling level meter for the recorder: each bar is a recent mic-amplitude sample
/// (newest on the right), centered so it reads as a waveform. It's driven by the REAL input
/// (`recorder.levels`), so it visibly rises when the user speaks and falls when silent —
/// honest feedback that the voice is being heard + recorded. Data-driven (no decorative
/// animation), so it stays truthful under Reduce Motion.
struct IOSLiveLevelMeter: View {
    let levels: [Double]
    let tint: Color
    var isActive: Bool = true

    private let barCount = 48
    private let spacing: CGFloat = 3

    var body: some View {
        GeometryReader { geo in
            let barWidth = max(2.5, (geo.size.width - spacing * CGFloat(barCount - 1)) / CGFloat(barCount))
            HStack(alignment: .center, spacing: spacing) {
                ForEach(0..<barCount, id: \.self) { i in
                    let level = sample(at: i)
                    let height = max(3, geo.size.height * CGFloat(0.04 + 0.96 * level))
                    Capsule(style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [tint, tint.opacity(0.55)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .frame(width: barWidth, height: height)
                        .opacity(opacity(at: i))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .center)
        }
    }

    /// Bar index 0 = left/oldest … `barCount-1` = right/newest; left-pad with silence until
    /// the buffer fills so the live edge scrolls in from the right.
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
