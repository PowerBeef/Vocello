import SwiftUI
import Combine
import QwenVoiceCore

struct IOSEngineLifecycleToast: View {
    /// Plain (non-observing) reference: the toast's only genuine invalidation
    /// source is the scoped `onReceive` below. An `@EnvironmentObject` here
    /// additionally subscribed this persistent bottom-chrome view to every
    /// store publish — generation progress ticks included — even while it
    /// showed nothing (IUI-4 P10).
    let ttsEngine: TTSEngineStore

    @State private var visibleState: EngineLifecycleState?
    @State private var errorMessage: String?
    @State private var dismissTask: Task<Void, Never>?

    var body: some View {
        Group {
            if let state = visibleState, let descriptor = Self.descriptor(for: state) {
                toastBody(descriptor: descriptor)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .iosAppAnimation(Theme.Motion.miniPlayerSlide, value: visibleState)
        .onReceive(ttsEngine.$engineLifecycleState.removeDuplicates()) { newState in
            handle(newState: newState)
        }
        .onDisappear {
            dismissTask?.cancel()
            dismissTask = nil
        }
    }

    @ViewBuilder
    private func toastBody(descriptor: ToastDescriptor) -> some View {
        // An error toast carries the engine's specific message when available, and
        // is the only one the user can act on (tap to dismiss). Transient states
        // (interrupted/recovering/restarted) stay informational + non-interactive.
        // The message is captured at event time (handle(newState:)) so the body
        // has no render-time store reads.
        let message = descriptor.isError
            ? (errorMessage ?? descriptor.message)
            : descriptor.message
        HStack(spacing: 10) {
            Image(systemName: descriptor.symbol)
                .font(.callout.weight(.semibold))
                .foregroundStyle(descriptor.tint)
            Text(message)
                .font(IOSTypeStyle.subhead.font)
                .foregroundStyle(Theme.Text.primary)
                .lineLimit(3)
            Spacer(minLength: 0)
            if descriptor.isError {
                Image(systemName: "xmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(Theme.Text.tertiary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity)
        .iosSubtleGlassSurface(
            in: RoundedRectangle(cornerRadius: 14, style: .continuous),
            tint: descriptor.tint
        )
        .padding(.horizontal, 16)
        .contentShape(Rectangle())
        .allowsHitTesting(descriptor.isError)
        .onTapGesture {
            if descriptor.isError { dismissError() }
        }
        .accessibilityIdentifier("engineLifecycleToast_\(descriptor.identifier)")
        .accessibilityAddTraits(descriptor.isError ? .isButton : [])
        .accessibilityHint(descriptor.isError ? "Double tap to dismiss" : "")
    }

    private func dismissError() {
        dismissTask?.cancel()
        ttsEngine.clearVisibleError()
        visibleState = nil
        errorMessage = nil
    }

    private func handle(newState: EngineLifecycleState) {
        if newState == .invalidated, !ttsEngine.hasActiveGeneration {
            dismissTask?.cancel()
            visibleState = nil
            return
        }
        guard Self.descriptor(for: newState) != nil else {
            // States with no toast clear any in-flight banner immediately.
            dismissTask?.cancel()
            visibleState = nil
            return
        }
        errorMessage = ttsEngine.visibleErrorMessage
        visibleState = newState
        dismissTask?.cancel()
        // Error toasts persist until the engine state changes or the user taps to
        // dismiss — a real failure must not vanish before it can be read/acted on.
        // Transient states keep the 4s auto-dismiss.
        guard Self.descriptor(for: newState)?.isError != true else {
            dismissTask = nil
            return
        }
        dismissTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            guard !Task.isCancelled else { return }
            if visibleState == newState {
                visibleState = nil
            }
        }
    }

    private struct ToastDescriptor {
        let identifier: String
        let message: String
        let symbol: String
        let tint: Color
        var isError: Bool = false
    }

    private static func descriptor(for state: EngineLifecycleState) -> ToastDescriptor? {
        switch state {
        case .interrupted:
            return ToastDescriptor(
                identifier: "interrupted",
                message: "Engine paused. Generation will resume shortly.",
                symbol: "pause.circle",
                tint: .yellow
            )
        case .recovering:
            return ToastDescriptor(
                identifier: "recovering",
                message: "Engine recovering…",
                symbol: "arrow.triangle.2.circlepath",
                tint: .yellow
            )
        case .invalidated:
            return ToastDescriptor(
                identifier: "invalidated",
                message: "Engine restarted.",
                symbol: "arrow.clockwise.circle",
                tint: Theme.Brand.gold
            )
        case .failed:
            return ToastDescriptor(
                identifier: "failed",
                // D3: the destination must exist — the Settings section is
                // titled "Voice models" (there is no "Model Downloads").
                message: "Engine error. Try again, or open Settings → Voice models.",
                symbol: "exclamationmark.triangle",
                tint: .red,
                isError: true
            )
        case .idle, .launching, .connected:
            return nil
        }
    }
}
