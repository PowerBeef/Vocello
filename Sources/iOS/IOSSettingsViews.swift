import SwiftUI
import UIKit
import UniformTypeIdentifiers
import QwenVoiceCore

@MainActor
private enum IOSSettingsSupportInfo {
    static var appVersionLabel: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "—"
        let build = info?["CFBundleVersion"] as? String ?? "—"
        return "\(short) (\(build))"
    }
}

@MainActor
enum IOSSettingsFormatters {
    static let byteCount: ByteCountFormatter = {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter
    }()

    static func fileSize(_ bytes: Int64) -> String {
        byteCount.string(fromByteCount: bytes)
    }
}

// The Settings screen body lives in `SettingsScreen`
// (Sources/iOS/Settings/SettingsScreen.swift) since Phase 6 of the
// AppModel migration retired the `IOSSettingsContainerView` /
// `IOSSettingsView` indirection. This file keeps the reusable
// reference-styled section/row primitives and the model row.

struct IOSSettingsReferenceSection<Content: View>: View {
    let title: String
    let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title.uppercased())
                .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.88)
                .foregroundStyle(Theme.Text.secondary)
                .padding(.horizontal, 20)
                .padding(.top, 14)
                .padding(.bottom, 6)

            VStack(alignment: .leading, spacing: 0) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color.white.opacity(0.04))
            }
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
            }
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .padding(.horizontal, 16)
            .padding(.bottom, 6)
        }
    }
}

private struct IOSSettingsUtilityIcon: View {
    let symbol: String

    var body: some View {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Color.white.opacity(0.06))
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .overlay {
                Image(systemName: symbol)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
            }
            .frame(width: 36, height: 36)
    }
}

struct IOSSettingsReferenceDivider: View {
    var body: some View {
        Rectangle()
            .fill(Color.white.opacity(0.06))
            .frame(height: 0.5)
            .padding(.leading, 64)
    }
}

private struct IOSSettingsReferenceSwitch: View {
    let isOn: Bool
    let tint: Color

    var body: some View {
        Capsule(style: .continuous)
            .fill(Color.white.opacity(0.06))
            .overlay {
                if isOn {
                    Capsule(style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    tint,
                                    tint.mix(with: .black, by: 0.18, in: .perceptual),
                                ],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(isOn ? tint.opacity(0.60) : Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .overlay {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [
                                Color(red: 0.98, green: 0.97, blue: 0.94),
                                Color(red: 0.86, green: 0.84, blue: 0.79),
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .shadow(color: .black.opacity(isOn ? 0.22 : 0.18), radius: 2, x: 0, y: 1)
                    .frame(width: 21, height: 21)
                    .frame(maxWidth: .infinity, alignment: isOn ? .trailing : .leading)
                    .padding(2)
            }
            .shadow(color: isOn ? tint.opacity(0.18) : .clear, radius: 8, x: 0, y: 2)
            .frame(width: 44, height: 26)
    }
}

struct IOSSettingsReferenceToggleRow: View {
    let symbol: String
    let title: String
    let accessibilityIdentifier: String
    @Binding var isOn: Bool
    let tint: Color

    var body: some View {
        Button {
            isOn.toggle()
            IOSHaptics.selection()
        } label: {
            HStack(spacing: 12) {
                IOSSettingsUtilityIcon(symbol: symbol)

                Text(title)
                    .iosScaledFont(size: 16)
                    .foregroundStyle(Theme.Text.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                IOSSettingsReferenceSwitch(isOn: isOn, tint: tint)
            }
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityIdentifier(accessibilityIdentifier)
        .accessibilityLabel(title)
        .accessibilityValue(isOn ? "On" : "Off")
    }
}

struct IOSSettingsReferenceValueRow: View {
    let symbol: String
    let title: String
    let accessibilityIdentifier: String
    let value: String
    let showsChevron: Bool
    /// When set, the whole row becomes tappable (e.g. the "Saved outputs" destination picker).
    var action: (() -> Void)? = nil

    var body: some View {
        if let action {
            Button(action: action) { rowContent }
                .buttonStyle(.plain)
        } else {
            rowContent
        }
    }

    private var rowContent: some View {
        HStack(spacing: 12) {
            IOSSettingsUtilityIcon(symbol: symbol)

            Text(title)
                .iosScaledFont(size: 16)
                .foregroundStyle(Theme.Text.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(value)
                .iosScaledFont(size: 14)
                .foregroundStyle(Theme.Text.secondary)
                .lineLimit(1)

            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.Text.tertiary)
                    .padding(.leading, 4)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

/// Variation control (GitHub #47) — Expressive / Balanced / Consistent. A Menu
/// styled to match the reference value rows. Persisted via @AppStorage on the
/// shared IOSGenerationVariationPreference key; stamped onto every generation.
struct IOSSettingsVariationRow: View {
    @Binding var selection: String

    private var currentDisplayName: String {
        (Qwen3SamplingVariation(rawValue: selection) ?? .expressive).displayName
    }

    var body: some View {
        Menu {
            ForEach(Qwen3SamplingVariation.allCases, id: \.self) { variation in
                Button {
                    selection = variation.rawValue
                    IOSHaptics.selection()
                } label: {
                    if selection == variation.rawValue {
                        Label(variation.displayName, systemImage: "checkmark")
                    } else {
                        Text(variation.displayName)
                    }
                }
            }
        } label: {
            HStack(spacing: 12) {
                IOSSettingsUtilityIcon(symbol: "dial.medium")

                Text("Variation")
                    .iosScaledFont(size: 16)
                    .foregroundStyle(Theme.Text.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Text(currentDisplayName)
                    .iosScaledFont(size: 14)
                    .foregroundStyle(Theme.Text.secondary)
                    .lineLimit(1)

                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.Text.tertiary)
                    .padding(.leading, 4)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("iosSettings_variationRow")
        .accessibilityLabel("Variation")
        .accessibilityValue(currentDisplayName)
        .accessibilityHint("How much takes vary when you regenerate the same text")
    }
}

struct IOSSettingsBrandFooter: View {
    var body: some View {
        VStack(spacing: 2) {
            Image("VocelloLaunchLogo")
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .antialiased(true)
                .scaledToFit()
                .frame(width: 180)
                .shadow(color: Theme.Brand.gold.opacity(0.18), radius: 14, x: 0, y: 10)
                .accessibilityHidden(true)

            Text("VERSION \(IOSSettingsSupportInfo.appVersionLabel)".uppercased())
                .iosScaledFont(size: 11, weight: .medium, relativeTo: .caption2)
                .accessibilityIdentifier("iosSettings_versionLabel")
                .tracking(0.66)
                .foregroundStyle(Theme.Text.tertiary)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
        .padding(.top, 6)
        .padding(.bottom, 2)
        .opacity(0.78)
    }
}

private struct IOSSettingsLinkRow: View {
    let title: String
    let subtitle: String
    let urlString: String
    let accessibilityIdentifier: String

    @Environment(\.openURL) private var openURL

    var body: some View {
        Button {
            guard let url = URL(string: urlString) else { return }
            openURL(url)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.Text.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(subtitle)
                        .font(.footnote)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 10)
                Image(systemName: "arrow.up.forward")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.Text.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier)
    }
}

private struct IOSSettingsSystemPreferencesRow: View {
    @Environment(\.openURL) private var openURL

    var body: some View {
        Button {
            guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
            openURL(url)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Open iOS Settings")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.Text.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Adjust permissions and system preferences for Vocello.")
                        .font(.footnote)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 10)
                Image(systemName: "arrow.up.forward")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.Text.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("iosSettingsOpenSystemSettings")
    }
}

private struct IOSSettingsPlaybackRow: View {
    @Binding var isOn: Bool

    var body: some View {
        Toggle(isOn: $isOn) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Auto-play generated audio")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Play each finished take automatically.")
                    .font(.footnote)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .toggleStyle(.switch)
        .tint(Theme.Brand.silver)
        .padding(.vertical, 2)
    }
}

private struct IOSSettingsProminentActionButtonStyle: ButtonStyle {
    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        let shape = Capsule(style: .continuous)

        configuration.label
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 16)
            .frame(height: 36)
            .background { shape.fill(Color.clear) }
            .overlay {
                shape
                    .stroke(tint.opacity(configuration.isPressed ? 0.62 : 0.48), lineWidth: 0.5)
            }
            .opacity(configuration.isPressed ? 0.96 : 1.0)
            .iosAppAnimation(Theme.Motion.press, value: configuration.isPressed)
    }
}

private extension View {
    func iosSettingsProminentActionButtonStyle(tint: Color) -> some View {
        buttonStyle(IOSSettingsProminentActionButtonStyle(tint: tint))
    }
}

struct IOSModelRow: View {
    @Environment(AppModel.self) private var appModel

    let model: TTSModel
    let status: ModelManagerViewModel.ModelStatus
    let operationState: IOSModelInstallerViewModel.OperationState
    let onInstall: () -> Void
    let onRequestCancelOptions: () -> Void
    let onDirectCancel: () -> Void
    let onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                header
                Spacer(minLength: 12)
                controls
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)

            if showsStatusDetail {
                statusDetailView
                    .padding(.horizontal, 14)
                    .padding(.bottom, 10)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("iosModelRow_\(model.id)")
    }

    private func requestInstall() {
        IOSHaptics.selection()
        onInstall()
    }

    private func requestCancelOptions() {
        IOSHaptics.selection()
        onRequestCancelOptions()
    }

    private func requestDirectCancel() {
        IOSHaptics.selection()
        onDirectCancel()
    }

    private func requestDelete() {
        appModel.presentDeleteModelSheet(IOSDeleteModelSheetPresentation(
            modelName: model.name,
            sizeLabel: deleteSheetSizeLabel,
            onConfirm: {
                onDelete()
            }
        ))
    }

    private var estimatedDownloadSizeLabel: String {
        if let estimated = model.estimatedDownloadBytes {
            return IOSSettingsFormatters.fileSize(estimated)
        }
        if case let .installed(sizeBytes) = status {
            return IOSSettingsFormatters.fileSize(Int64(sizeBytes))
        }
        return "—"
    }

    private var deleteSheetSizeLabel: String {
        if case let .installed(sizeBytes) = status {
            return IOSSettingsFormatters.fileSize(Int64(sizeBytes))
        }
        if let estimated = model.estimatedDownloadBytes {
            return IOSSettingsFormatters.fileSize(estimated)
        }
        return "several GB"
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Theme.Brand.modeColor(model.mode).opacity(0.16))
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Theme.Brand.modeColor(model.mode).opacity(0.38), lineWidth: 0.5)
                Image(systemName: modelIconName)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(Theme.Brand.modeColor(model.mode))
            }
            .frame(width: 36, height: 36)

            VStack(alignment: .leading, spacing: 2) {
                Text(model.mode.displayName)
                    .iosScaledFont(size: 15, weight: .semibold, relativeTo: .subheadline)
                    .tracking(-0.075)
                    .foregroundStyle(Theme.Text.primary)

                modelSubtitle
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var modelSubtitle: some View {
        HStack(spacing: 6) {
            Text(variantDisplayText)

            if let estimatedSizeText {
                Text("·")
                Text(estimatedSizeText)
                    .monospacedDigit()
            }

            if let statusSummaryText {
                Text("·")
                Text(statusSummaryText)
                    .fontWeight(statusSummaryText == "Active" ? .semibold : .regular)
                    .foregroundStyle(statusSummaryText == "Active"
                                     ? Theme.Brand.modeColor(model.mode)
                                     : Theme.Text.secondary)
                    .accessibilityLabel("\(model.mode.displayName) model status")
                    .accessibilityValue(statusSummaryText)
                    .accessibilityIdentifier("iosModelStatus_\(model.id)")
            }
        }
        .iosScaledFont(size: 12, relativeTo: .caption)
        .foregroundStyle(Theme.Text.secondary)
        .lineLimit(1)
    }

    // Match the Studio per-mode voice-selector chip glyphs (IOSGenerationModeViews) so the download
    // list reads the same as the mode UI — more representative than the old generic mic/wand glyphs.
    private var modelIconName: String {
        switch model.mode {
        case .custom: return "person.wave.2.fill"   // Custom "Voice" chip
        case .design: return "text.bubble.fill"     // Design "Voice brief" chip
        case .clone: return "waveform"              // Clone "Reference" chip (unchanged)
        }
    }

    @ViewBuilder
    private var controls: some View {
        switch operationState {
        case .idle:
            switch status {
            case .installed:
                installedControls
            case .updateAvailable:
                HStack(spacing: 8) {
                    installButton(
                        title: "Update",
                        action: onInstall,
                        accessibilityIdentifier: "iosModelUpdate_\(model.id)"
                    )
                    installedControls
                }
            case .checking:
                ProgressView()
            case .notInstalled:
                installButton(title: "Install", accessibilityIdentifier: "iosModelDownload_\(model.id)")
            case .incomplete, .error:
                installButton(title: "Repair", action: onInstall, accessibilityIdentifier: "iosModelRepair_\(model.id)")
            }
        case .installed:
            installedControls
        case .available:
            installButton(title: "Install", accessibilityIdentifier: "iosModelDownload_\(model.id)")
        case .queued, .waitingForConnectivity, .downloading, .retrying:
            installButton(title: "Cancel", action: requestCancelOptions, accessibilityIdentifier: "iosModelCancel_\(model.id)")
        case .verifying, .installing, .cancelling, .deleting:
            ProgressView()
        case .unavailable:
            if case .incomplete = status {
                installedControls
            }
        case .failed:
            installButton(title: "Retry", action: onInstall, accessibilityIdentifier: "iosModelRetry_\(model.id)")
        }
    }

    private var installedControls: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(Color(red: 0.19, green: 0.82, blue: 0.35))

            Button(role: .destructive, action: requestDelete) {
                Image(systemName: "trash")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.Text.secondary)
                    .frame(width: 36, height: 36)
                    .background {
                        Circle()
                            .fill(Color.white.opacity(0.04))
                    }
                    .overlay {
                        Circle()
                            .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("iosModelDelete_\(model.id)")
        }
    }

    private func installButton(
        title: String,
        action: (() -> Void)? = nil,
        accessibilityIdentifier: String
    ) -> some View {
        Button(title, action: action ?? requestInstall)
            .iosSettingsProminentActionButtonStyle(tint: Theme.Brand.modeColor(model.mode))
            .accessibilityIdentifier(accessibilityIdentifier)
    }

    @ViewBuilder
    private var statusDetailView: some View {
        switch operationState {
        case .downloading(
            let progress, let downloadedBytes, let totalBytes,
            let bytesPerSecond, let estimatedSecondsRemaining, let message
        ):
            VStack(alignment: .leading, spacing: 6) {
                ProgressView(value: progress ?? 0)
                    .tint(Theme.Brand.modeColor(model.mode))
                    .accessibilityIdentifier("iosModelProgress_\(model.id)")
                Text(progressText(
                    downloadedBytes: downloadedBytes,
                    totalBytes: totalBytes,
                    bytesPerSecond: bytesPerSecond,
                    estimatedSecondsRemaining: estimatedSecondsRemaining,
                    suffix: message
                ))
                    .iosScaledFont(size: 12, relativeTo: .caption)
                    .foregroundStyle(Theme.Text.secondary)
            }
        case .waitingForConnectivity(let downloadedBytes, let totalBytes):
            VStack(alignment: .leading, spacing: 6) {
                Text("Waiting for connectivity")
                    .iosScaledFont(size: 12, relativeTo: .caption)
                    .foregroundStyle(Theme.Text.secondary)
                Text(progressText(downloadedBytes: downloadedBytes, totalBytes: totalBytes))
                    .iosScaledFont(size: 12, relativeTo: .caption)
                    .foregroundStyle(Theme.Text.secondary)
            }
        case .retrying(let progress, let downloadedBytes, let totalBytes, let retryCount, let reason):
            VStack(alignment: .leading, spacing: 6) {
                ProgressView(value: progress ?? 0)
                    .tint(Theme.Brand.modeColor(model.mode))
                    .accessibilityIdentifier("iosModelProgress_\(model.id)")
                Text(progressText(
                    downloadedBytes: downloadedBytes,
                    totalBytes: totalBytes,
                    suffix: "Retry \(retryCount)\(reason.map { ": \($0)" } ?? "") · verified files will be reused"
                ))
                    .iosScaledFont(size: 12, relativeTo: .caption)
                    .foregroundStyle(Theme.Text.secondary)
            }
        case .failed(let message):
            Text(message)
                .iosScaledFont(size: 12, relativeTo: .caption)
                .foregroundStyle(.red)
                .fixedSize(horizontal: false, vertical: true)
        case .available, .queued, .verifying, .installing, .cancelling, .installed, .deleting, .unavailable, .idle:
            EmptyView()
        }
    }

    private var variantDisplayText: String {
        var parts: [String] = []
        switch model.qwen3Capabilities?.modelSize {
        case .compact0b6:
            parts.append("0.6B")
        case .pro1b7:
            parts.append("1.7B")
        case nil:
            break
        }
        if model.folder.localizedCaseInsensitiveContains("4bit") {
            parts.append("4-bit")
        } else if model.folder.localizedCaseInsensitiveContains("8bit") {
            parts.append("8-bit")
        }
        if model.mode == .custom, model.supportsInstructionControl == false {
            parts.append("speaker only")
        }
        if model.mode == .clone, model.supportsVoiceClone {
            parts.append("clone")
        }
        return parts.isEmpty ? "On-device" : parts.joined(separator: " · ")
    }

    private var estimatedSizeText: String? {
        let label = estimatedDownloadSizeLabel
        return label == "—" ? nil : label
    }

    private var showsStatusDetail: Bool {
        switch operationState {
        case .waitingForConnectivity, .downloading, .retrying:
            return true
        case .failed:
            return true
        default:
            return false
        }
    }

    private var statusSummaryText: String? {
        switch operationState {
        case .idle:
            switch status {
            case .checking:
                return "Checking…"
            case .notInstalled:
                return nil
            case .installed:
                return "Active"
            case .updateAvailable:
                return "Update available"
            case .incomplete:
                return "Repair needed"
            case .error:
                return "Retry needed"
            }
        case .installed:
            return "Active"
        case .available:
            return nil
        case .queued:
            return "Queued…"
        case .waitingForConnectivity:
            return "Waiting for network…"
        case .downloading:
            return "Downloading…"
        case .retrying:
            return "Retrying…"
        case .verifying:
            return "Verifying…"
        case .installing:
            return "Installing…"
        case .cancelling:
            return "Cancelling…"
        case .deleting:
            return "Removing…"
        case .unavailable:
            return "Unavailable"
        case .failed:
            return "Retry needed"
        }
    }

    private func progressText(
        downloadedBytes: Int64,
        totalBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        suffix: String? = nil
    ) -> String {
        let current = IOSSettingsFormatters.fileSize(downloadedBytes)
        var parts: [String]
        if let totalBytes {
            parts = ["\(current) / \(IOSSettingsFormatters.fileSize(totalBytes))"]
        } else {
            parts = ["\(current) downloaded"]
        }
        if let bytesPerSecond, bytesPerSecond > 0 {
            parts.append("\(IOSSettingsFormatters.fileSize(bytesPerSecond))/s")
        }
        if let estimatedSecondsRemaining, estimatedSecondsRemaining.isFinite {
            parts.append("about \(max(1, Int(estimatedSecondsRemaining.rounded())))s remaining")
        }
        if let suffix, !suffix.isEmpty { parts.append(suffix) }
        return parts.joined(separator: " · ")
    }
}
