import SwiftUI
import QwenVoiceCore

@MainActor
enum IOSSettingsSupportInfo {
    static var version: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
    }

    static var build: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "—"
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

/// A compact Settings group using the same eyebrow-and-panel language as Voices and History.
/// The tab dock remains the only glass surface on this screen.
struct IOSSettingsSection<Content: View>: View {
    let title: String
    let accessibilityIdentifier: String?
    let content: Content

    init(
        title: String,
        accessibilityIdentifier: String? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.accessibilityIdentifier = accessibilityIdentifier
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title.uppercased())
                .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.88)
                .foregroundStyle(Theme.Text.secondary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier(accessibilityIdentifier ?? "")
                .padding(.horizontal, 4)
                .padding(.bottom, 6)

            VStack(alignment: .leading, spacing: 0) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.04))
            .overlay {
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(Theme.Surface.panelStroke, lineWidth: 0.5)
            }
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        }
    }
}

struct IOSSettingsDivider: View {
    var body: some View {
        Rectangle()
            .fill(Theme.Surface.hairline)
            .frame(height: 0.5)
            .padding(.leading, 62)
    }
}

private struct IOSSettingsIcon: View {
    let symbol: String
    var tint: Color = Theme.Brand.silver

    var body: some View {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(tint.opacity(0.10))
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(tint.opacity(0.18), lineWidth: 0.5)
            }
            .overlay {
                Image(systemName: symbol)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(tint)
            }
            .frame(width: 36, height: 36)
            .accessibilityHidden(true)
    }
}

private struct IOSSettingsLabel: View {
    let symbol: String
    let title: String
    let subtitle: String?
    var tint: Color = Theme.Brand.silver

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            IOSSettingsIcon(symbol: symbol, tint: tint)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .fixedSize(horizontal: false, vertical: true)

                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .layoutPriority(1)
        }
    }
}

/// Vocello's compact switch chrome around a semantic SwiftUI `Toggle`.
/// The visible track is 44x26 while the returned control retains a 44-point hit region.
private struct IOSSettingsCompactToggleStyle: ToggleStyle {
    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(spacing: 12) {
                configuration.label

                Spacer(minLength: 8)

                Capsule(style: .continuous)
                    .fill(configuration.isOn ? tint.opacity(0.88) : Color.white.opacity(0.10))
                    .overlay {
                        Capsule(style: .continuous)
                            .stroke(
                                configuration.isOn ? tint.opacity(0.58) : Color.white.opacity(0.12),
                                lineWidth: 0.5
                            )
                    }
                    .overlay(alignment: configuration.isOn ? .trailing : .leading) {
                        Circle()
                            .fill(Theme.Text.primary)
                            .shadow(color: .black.opacity(0.20), radius: 2, x: 0, y: 1)
                            .padding(2.5)
                    }
                    .frame(width: 44, height: 26)
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
                    .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct IOSSettingsToggleRow: View {
    let symbol: String
    let title: String
    let subtitle: String?
    let accessibilityIdentifier: String
    @Binding var isOn: Bool
    var tint: Color = Theme.Brand.silver

    var body: some View {
        Toggle(isOn: $isOn) {
            IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle, tint: tint)
        }
        .toggleStyle(IOSSettingsCompactToggleStyle(tint: tint))
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(minHeight: 52)
        .accessibilityIdentifier(accessibilityIdentifier)
        .accessibilityLabel(title)
        .accessibilityValue(isOn ? "On" : "Off")
        .accessibilityHint(subtitle ?? "")
    }
}

struct IOSSettingsValueRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let symbol: String
    let title: String
    let subtitle: String?
    let accessibilityIdentifier: String
    let value: String
    var accessibilityHint: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        Group {
            if let action {
                Button(action: action) { content }.buttonStyle(.plain)
            } else {
                content
            }
        }
        .accessibilityIdentifier(accessibilityIdentifier)
        .accessibilityLabel(title)
        .accessibilityValue(value)
        .accessibilityHint(accessibilityHint ?? "")
    }

    private var content: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle)
                    trailingValue
                        .padding(.leading, 46)
                }
            } else {
                HStack(alignment: .center, spacing: 10) {
                    IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle)
                    trailingValue
                        .frame(maxWidth: 152, alignment: .trailing)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var valueText: some View {
        Text(value)
            .font(.caption)
            .foregroundStyle(Theme.Text.secondary)
            .multilineTextAlignment(dynamicTypeSize.isAccessibilitySize ? .leading : .trailing)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var trailingValue: some View {
        HStack(spacing: 8) {
            valueText
                .frame(maxWidth: .infinity, alignment: dynamicTypeSize.isAccessibilitySize ? .leading : .trailing)

            if action != nil {
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.Text.tertiary)
                    .accessibilityHidden(true)
            }
        }
    }
}

struct IOSSettingsNavigationRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let symbol: String
    let title: String
    let subtitle: String?
    let value: String

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle)
                    HStack(spacing: 8) {
                        Text(value).frame(maxWidth: .infinity, alignment: .leading)
                        chevron
                    }
                    .padding(.leading, 46)
                }
            } else {
                HStack(spacing: 10) {
                    IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle)
                    Text(value)
                        .font(.caption)
                        .multilineTextAlignment(.trailing)
                    chevron
                }
            }
        }
        .foregroundStyle(Theme.Text.secondary)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var chevron: some View {
        Image(systemName: "chevron.right")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(Theme.Text.tertiary)
            .accessibilityHidden(true)
    }
}

struct IOSSettingsPickerRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Binding var selection: String

    private var currentDisplayName: String {
        (Qwen3SamplingVariation(rawValue: selection) ?? .expressive).displayName
    }

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    label
                    picker.frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 46)
                }
            } else {
                HStack(spacing: 10) {
                    label
                    picker
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
    }

    private var label: some View {
        IOSSettingsLabel(
            symbol: "dial.medium",
            title: "Take variation",
            subtitle: "Choose how much finished takes vary."
        )
    }

    private var picker: some View {
        Picker("Take variation", selection: $selection) {
            ForEach(Qwen3SamplingVariation.allCases, id: \.self) { variation in
                Text(variation.displayName).tag(variation.rawValue)
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .font(.caption.weight(.semibold))
        .tint(Theme.Text.secondary)
        .frame(minWidth: 44, minHeight: 44, alignment: dynamicTypeSize.isAccessibilitySize ? .leading : .trailing)
        .contentShape(Rectangle())
        .accessibilityIdentifier("iosSettings_variationRow")
        .accessibilityLabel("Take variation")
        .accessibilityValue(currentDisplayName)
        .accessibilityHint("Choose Expressive, Balanced, or Consistent")
    }
}

struct IOSSettingsVersionRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    IOSSettingsLabel(symbol: "info.circle", title: "Version", subtitle: nil)
                    versionText.padding(.leading, 46)
                }
            } else {
                HStack(spacing: 10) {
                    IOSSettingsLabel(symbol: "info.circle", title: "Version", subtitle: nil)
                    versionText
                        .frame(maxWidth: 152, alignment: .trailing)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("iosSettings_versionLabel")
        .accessibilityLabel("Version \(IOSSettingsSupportInfo.version), build \(IOSSettingsSupportInfo.build)")
    }

    private var versionText: some View {
        Text("\(IOSSettingsSupportInfo.version) (\(IOSSettingsSupportInfo.build))")
            .font(.caption.monospacedDigit())
            .foregroundStyle(Theme.Text.secondary)
            .multilineTextAlignment(dynamicTypeSize.isAccessibilitySize ? .leading : .trailing)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct IOSSettingsActionButtonStyle: ButtonStyle {
    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 12)
            .frame(minWidth: 44, minHeight: 44)
            .background(Theme.Surface.inline)
            .clipShape(Capsule(style: .continuous))
            .overlay {
                Capsule(style: .continuous)
                    .stroke(tint.opacity(configuration.isPressed ? 0.65 : 0.40), lineWidth: 0.5)
            }
            .opacity(configuration.isPressed ? 0.82 : 1)
    }
}

struct IOSModelRow: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let model: TTSModel
    let status: ModelManagerViewModel.ModelStatus
    let operationState: IOSModelInstallerViewModel.OperationState
    let onInstall: () -> Void
    let onRequestCancelOptions: () -> Void
    let onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    header
                    controls.frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                HStack(alignment: .top, spacing: 10) {
                    header
                    controls
                }
            }

            if showsStatusDetail {
                statusDetailView.padding(.leading, dynamicTypeSize.isAccessibilitySize ? 0 : 46)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("iosModelRow_\(model.id)")
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            IOSSettingsIcon(symbol: modelIconName, tint: Theme.Brand.modeColor(model.mode))

            VStack(alignment: .leading, spacing: 4) {
                Text(model.mode.displayName)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(metadataText)
                    .font(.caption)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Label(statusText, systemImage: statusSymbol)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel("\(model.mode.displayName) model status")
                    .accessibilityValue(statusText)
                    .accessibilityIdentifier("iosModelStatus_\(model.id)")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var controls: some View {
        switch operationState {
        case .idle:
            switch status {
            case .installed:
                removalMenu
            case .updateAvailable:
                HStack(spacing: 8) {
                    actionButton("Update", id: "iosModelUpdate_\(model.id)", action: requestInstall)
                    removalMenu
                }
            case .checking:
                ProgressView().frame(minWidth: 44, minHeight: 44)
            case .notInstalled:
                actionButton("Install", id: "iosModelDownload_\(model.id)", action: requestInstall)
            case .incomplete:
                actionButton("Repair", id: "iosModelRepair_\(model.id)", action: requestInstall)
            case .error:
                actionButton("Retry", id: "iosModelRetry_\(model.id)", action: requestInstall)
            }
        case .installed:
            removalMenu
        case .available:
            actionButton("Install", id: "iosModelDownload_\(model.id)", action: requestInstall)
        case .queued, .waitingForConnectivity, .downloading, .retrying:
            actionButton("Cancel", id: "iosModelCancel_\(model.id)", action: requestCancelOptions)
        case .verifying, .installing, .cancelling, .deleting:
            ProgressView().frame(minWidth: 44, minHeight: 44)
        case .unavailable:
            if case .incomplete = status { removalMenu }
        case .failed:
            actionButton("Retry", id: "iosModelRetry_\(model.id)", action: requestInstall)
        }
    }

    private var removalMenu: some View {
        Menu {
            Button(role: .destructive, action: requestDelete) {
                Label("Remove Model", systemImage: "trash")
            }
            .accessibilityIdentifier("iosModelDelete_\(model.id)")
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.Text.secondary)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("More options for \(model.mode.displayName)")
        .accessibilityHint("Contains Remove Model")
        .accessibilityIdentifier("iosModelMenu_\(model.id)")
    }

    private func actionButton(_ title: String, id: String, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(IOSSettingsActionButtonStyle(tint: Theme.Brand.modeColor(model.mode)))
            .accessibilityIdentifier(id)
    }

    private func requestInstall() {
        IOSHaptics.selection()
        onInstall()
    }

    private func requestCancelOptions() {
        IOSHaptics.selection()
        onRequestCancelOptions()
    }

    private func requestDelete() {
        appModel.presentDeleteModelSheet(IOSDeleteModelSheetPresentation(
            modelName: model.name,
            sizeLabel: deleteSheetSizeLabel,
            onConfirm: { onDelete() }
        ))
    }

    private var deleteSheetSizeLabel: String {
        switch status {
        case .installed(let sizeBytes), .updateAvailable(let sizeBytes, _), .incomplete(_, let sizeBytes):
            return IOSSettingsFormatters.fileSize(Int64(sizeBytes))
        default:
            return model.estimatedDownloadBytes.map(IOSSettingsFormatters.fileSize) ?? "several GB"
        }
    }

    private var modelIconName: String {
        switch model.mode {
        case .custom: return "person.wave.2.fill"
        case .design: return "text.bubble.fill"
        case .clone: return "waveform"
        }
    }

    private var metadataText: String {
        var parts: [String] = []
        switch model.qwen3Capabilities?.modelSize {
        case .compact0b6: parts.append("0.6B")
        case .pro1b7: parts.append("1.7B")
        case nil: break
        }
        if model.folder.localizedCaseInsensitiveContains("4bit") {
            parts.append("4-bit")
        } else if model.folder.localizedCaseInsensitiveContains("8bit") {
            parts.append("8-bit")
        }
        if let bytes = model.estimatedDownloadBytes {
            parts.append(IOSSettingsFormatters.fileSize(bytes))
        }
        return parts.isEmpty ? "On-device model" : parts.joined(separator: " · ")
    }

    private var statusText: String {
        switch operationState {
        case .idle:
            switch status {
            case .checking: return "Checking…"
            case .notInstalled: return "Not Installed"
            case .installed: return "Ready"
            case .updateAvailable: return "Update Available"
            case .incomplete: return "Repair Needed"
            case .error: return "Retry Needed"
            }
        case .installed: return "Ready"
        case .available: return "Not Installed"
        case .queued: return "Downloading · Queued"
        case .waitingForConnectivity: return "Downloading · Waiting for Network"
        case .downloading: return "Downloading"
        case .retrying: return "Downloading · Retrying"
        case .verifying: return "Downloading · Verifying"
        case .installing: return "Downloading · Installing"
        case .cancelling: return "Downloading · Cancelling"
        case .deleting: return "Removing"
        case .unavailable: return "Repair Needed"
        case .failed: return "Retry Needed"
        }
    }

    private var statusSymbol: String {
        switch statusText {
        case "Ready": return "checkmark.circle"
        case "Not Installed": return "arrow.down.circle"
        case "Update Available": return "arrow.triangle.2.circlepath.circle"
        case "Repair Needed": return "wrench.and.screwdriver"
        case "Retry Needed": return "exclamationmark.arrow.triangle.2.circlepath"
        default: return "clock"
        }
    }

    private var showsStatusDetail: Bool {
        switch operationState {
        case .waitingForConnectivity, .downloading, .retrying, .failed: return true
        default:
            if case .incomplete = status { return true }
            if case .error = status { return true }
            return false
        }
    }

    @ViewBuilder
    private var statusDetailView: some View {
        switch operationState {
        case .downloading(let progress, let downloaded, let total, let speed, let eta, let message):
            VStack(alignment: .leading, spacing: 6) {
                ProgressView(value: progress ?? 0)
                    .tint(Theme.Brand.modeColor(model.mode))
                    .accessibilityIdentifier("iosModelProgress_\(model.id)")
                detailText(progressText(downloaded: downloaded, total: total, speed: speed, eta: eta, suffix: message))
            }
        case .waitingForConnectivity(let downloaded, let total):
            detailText(progressText(downloaded: downloaded, total: total, suffix: "Waiting for connectivity"))
        case .retrying(let progress, let downloaded, let total, let retryCount, let reason):
            VStack(alignment: .leading, spacing: 6) {
                ProgressView(value: progress ?? 0)
                    .tint(Theme.Brand.modeColor(model.mode))
                    .accessibilityIdentifier("iosModelProgress_\(model.id)")
                detailText(progressText(
                    downloaded: downloaded,
                    total: total,
                    suffix: "Retry \(retryCount)\(reason.map { ": \($0)" } ?? "") · verified files will be reused"
                ))
            }
        case .failed(let message):
            detailText(message, color: .red)
        default:
            switch status {
            case .incomplete(let message, _), .error(let message): detailText(message, color: .red)
            default: EmptyView()
            }
        }
    }

    private func detailText(_ text: String, color: Color = Theme.Text.secondary) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func progressText(
        downloaded: Int64,
        total: Int64?,
        speed: Int64? = nil,
        eta: Double? = nil,
        suffix: String? = nil
    ) -> String {
        var details: [String] = []
        if let total {
            details.append("\(IOSSettingsFormatters.fileSize(downloaded)) / \(IOSSettingsFormatters.fileSize(total))")
        } else {
            details.append("\(IOSSettingsFormatters.fileSize(downloaded)) downloaded")
        }
        if let speed, speed > 0 { details.append("\(IOSSettingsFormatters.fileSize(speed))/s") }
        if let eta, eta.isFinite { details.append("about \(max(1, Int(eta.rounded())))s remaining") }
        if let suffix, !suffix.isEmpty { details.append(suffix) }
        return details.joined(separator: " · ")
    }
}
