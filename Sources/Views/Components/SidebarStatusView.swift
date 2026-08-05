import SwiftUI

struct SidebarFooterPresentation: Equatable {
    let inlinePlayerActivity: ActivityStatus?
    let showsStandaloneStatus: Bool

    static func resolve(sidebarStatus: SidebarStatus, isLiveStream: Bool) -> Self {
        guard isLiveStream,
              case .running(let activity) = sidebarStatus,
              activity.presentation == .inlinePlayer else {
            return Self(inlinePlayerActivity: nil, showsStandaloneStatus: true)
        }

        return Self(inlinePlayerActivity: activity, showsStandaloneStatus: false)
    }
}

struct SidebarStatusView: View {
    let sidebarStatus: SidebarStatus
    let clearError: @MainActor () -> Void

    private var stateKey: String {
        switch sidebarStatus {
        case .idle: return "idle"
        case .standby: return "standby"
        case .starting: return "starting"
        case .running: return "active"
        case .error: return "error"
        case .crashed: return "crashed"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Engine")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)

            statusContent
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("sidebar_backendStatus")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("sidebar_generationStatus")
        .appAnimation(AppTheme.Motion.standard, value: stateKey)
    }

    @ViewBuilder
    private var statusContent: some View {
        switch sidebarStatus {
        case .idle:
            idleView
        case .standby:
            standbyView
        case .starting:
            startingView
        case .running(let activity):
            activeView(activity: activity)
        case .error(let message):
            errorView(message: message)
        case .crashed(let message):
            crashedView(message: message)
        }
    }

    // MARK: - Idle

    private var idleView: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(AppTheme.accent)
                .frame(width: 5, height: 5)
            Text("Ready")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .accessibilityIdentifier("sidebar_backendStatus_idle")
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var standbyView: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Color.secondary.opacity(0.55))
                .frame(width: 5, height: 5)
            Text("Standby")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .accessibilityIdentifier("sidebar_backendStatus_standby")
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Starting

    private var startingView: some View {
        HStack(spacing: 6) {
            // Static glyph, not an indeterminate spinner: engine start
            // includes the GPU-heavy model load, and a continuously
            // animating element over Liquid Glass contends with it for the
            // compositor (generation performance gate, OPTIMIZATION.md §K).
            Image(systemName: "bolt.horizontal")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            Text("Starting engine…")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
        }
        .accessibilityIdentifier("sidebar_backendStatus_starting")
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Active (with progress bar)

    private func activeView(activity: ActivityStatus) -> some View {
        let percent = Int(((activity.fraction ?? 0.0) * 100.0).rounded())

        // Audit Batch 6b: one progress affordance at a time. When we
        // know the fraction, the determinate bar + percent is the
        // signal — the indeterminate spinner alongside it was visual
        // noise. When fraction is nil, the spinner replaces the bar.
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                if activity.fraction == nil {
                    // Static glyph for the same §K reason as startingView:
                    // this row is visible for entire generations, and a
                    // spinner over glass steals compositor time from the
                    // engine's GPU work. The label text carries the state.
                    Image(systemName: "waveform")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(AppTheme.accent)
                }
                Text(activity.label)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            if let fraction = activity.fraction {
                HStack(spacing: 8) {
                    ProgressView(value: min(max(fraction, 0.0), 1.0), total: 1.0)
                        .tint(AppTheme.statusProgressTint)
                        .scaleEffect(y: 0.6)
                    Text("\(percent)%")
                        .font(.caption2.monospacedDigit().weight(.medium))
                        .foregroundStyle(AppTheme.textMuted)
                }
            }
        }
        .accessibilityIdentifier("sidebar_backendStatus_active")
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(statusBackground(color: AppTheme.accent, fillOpacity: 0.035, strokeOpacity: 0.07))
    }

    // MARK: - Error (dismissible)

    private func errorView(message: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                Text("Error")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.primary)
                Spacer()
                Button {
                    clearError()
                } label: {
                    Image(systemName: "xmark")
                        .font(.caption2)
                        .foregroundStyle(AppTheme.textMuted)
                }
                .buttonStyle(.plain)
            }
            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .accessibilityIdentifier("sidebar_backendStatus_error")
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(statusBackground(color: .orange, fillOpacity: 0.05, strokeOpacity: 0.1))
    }

    // MARK: - Crashed

    private func crashedView(message: String) -> some View {
        let detail = message.isEmpty ? "Restart the app to continue" : message
        let title = detail.localizedCaseInsensitiveContains("unavailable")
            ? "Engine unavailable"
            : "Engine stopped"

        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "bolt.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                Text(title)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.primary)
            }
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .accessibilityIdentifier("sidebar_backendStatus_crashed")
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(statusBackground(color: .red, fillOpacity: 0.05, strokeOpacity: 0.1))
    }

    // MARK: - Shared Background

    private func statusBackground(color: Color, fillOpacity: Double, strokeOpacity: Double) -> some View {
        GatedGlass {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.clear)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(
                            color.opacity(strokeOpacity),
                            lineWidth: 1
                        )
                )
                .glassEffect(
                    // The tint used to be full `color` which left the
                    // banner reading as a solid red/amber brick; dropping
                    // to 0.38 lets the glass refract the canvas behind
                    // while still keeping the error identity colour.
                    .regular.tint(color.opacity(0.38)),
                    in: .rect(cornerRadius: 8)
                )
                .glass3DDepth(radius: 8, intensity: 0.55)
        } fallback: {
            statusBackgroundLegacy(color: color, fillOpacity: fillOpacity, strokeOpacity: strokeOpacity)
        }
    }

    private func statusBackgroundLegacy(color: Color, fillOpacity: Double, strokeOpacity: Double) -> some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(color.opacity(fillOpacity))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(color.opacity(strokeOpacity), lineWidth: 1)
            )
    }
}
