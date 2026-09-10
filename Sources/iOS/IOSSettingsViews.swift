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

/// Flat Settings groups; optional headings remain available to existing model/license sections.
/// The tab dock remains the only glass surface on this screen.
struct IOSSettingsSection<Content: View>: View {
    let title: String?
    let accent: Color?
    let accessibilityIdentifier: String?
    let content: Content

    init(
        title: String? = nil,
        accent: Color? = nil,
        accessibilityIdentifier: String? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.accent = accent
        self.accessibilityIdentifier = accessibilityIdentifier
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title {
                Text(title.uppercased())
                .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.88)
                .foregroundStyle(Theme.Text.secondary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier(accessibilityIdentifier ?? "")
                .padding(.horizontal, 4)
                .padding(.bottom, 6)
            }

            VStack(alignment: .leading, spacing: 0) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(accent?.opacity(0.07) ?? Color.white.opacity(0.04))
            .overlay {
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(accent?.opacity(0.25) ?? Theme.Surface.panelStroke, lineWidth: 0.5)
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
            .padding(.leading, 50)
    }
}

private struct IOSSettingsIcon: View {
    let symbol: String
    var tint: Color = Theme.Brand.silver

    var body: some View {
        Image(systemName: symbol)
            // Decorative artwork fits its slot; neighboring text still scales freely.
            .resizable()
            .scaledToFit()
            .fontWeight(.medium)
            .foregroundStyle(tint)
            .frame(width: 20, height: 20)
            .frame(width: 28, height: 28)
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
                        .font(.footnote)
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
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let tint: Color

    func makeBody(configuration: Configuration) -> some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 12))
        return Button {
            configuration.isOn.toggle()
        } label: {
            layout {
                configuration.label

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
        .accessibilityValue(isOn ? IOSSettingsText.on : IOSSettingsText.off)
        .accessibilityHint(subtitle ?? "")
    }
}

struct IOSSettingsValueRow: View {
    let symbol: String
    let title: String
    let subtitle: String?
    let accessibilityIdentifier: String
    let value: String
    var accessibilityHint: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        Group {
            if let action { Button(action: action) { content }.buttonStyle(.plain) }
            else { content }
        }
        .accessibilityIdentifier(accessibilityIdentifier)
        .accessibilityLabel(title)
        .accessibilityValue(value)
        .accessibilityHint(accessibilityHint ?? "")
    }

    private var content: some View {
        IOSSettingsNavigationRow(symbol: symbol, title: title, subtitle: subtitle,
                                 value: value, showsChevron: action != nil)
    }
}

struct IOSSettingsNavigationRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let symbol: String
    let title: String
    let subtitle: String?
    let value: String
    var tint: Color = Theme.Brand.silver
    var showsChevron = true

    var body: some View {
        HStack(spacing: 10) {
            let layout = dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6))
                : AnyLayout(HStackLayout(alignment: .center, spacing: 12))
            layout {
                IOSSettingsLabel(symbol: symbol, title: title, subtitle: subtitle, tint: tint)
                if !value.isEmpty {
                    Text(value)
                        .font(.footnote)
                        .foregroundStyle(Theme.Text.secondary)
                        .multilineTextAlignment(dynamicTypeSize.isAccessibilitySize ? .leading : .trailing)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.leading, dynamicTypeSize.isAccessibilitySize ? 38 : 0)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.Text.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .contentShape(Rectangle())
    }
}

struct IOSSettingsPickerRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Binding var selection: String

    private var currentDisplayName: String {
        IOSSettingsText.variationName(Qwen3SamplingVariation(rawValue: selection) ?? .expressive)
    }

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(alignment: .center, spacing: 12))
        layout {
            label
            picker.padding(.leading, dynamicTypeSize.isAccessibilitySize ? 38 : 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
    }

    private var label: some View {
        IOSSettingsLabel(
            symbol: "dial.medium",
            title: IOSSettingsText.variation,
            subtitle: IOSSettingsText.variationDetail
        )
    }

    private var picker: some View {
        Picker(IOSSettingsText.variation, selection: $selection) {
            ForEach(Qwen3SamplingVariation.allCases, id: \.self) { variation in
                Text(IOSSettingsText.variationName(variation))
                    .accessibilityIdentifier("iosSettings_variationOption_\(variation.rawValue)")
                    .tag(variation.rawValue)
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .font(.subheadline.weight(.semibold))
        .tint(Theme.Text.secondary)
        .frame(minWidth: 44, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityIdentifier("iosSettings_variationRow")
        .accessibilityLabel(IOSSettingsText.variation)
        .accessibilityValue(currentDisplayName)
        .accessibilityHint(IOSSettingsText.variationHint)
    }
}

struct IOSSettingsVersionRow: View {
    var body: some View {
        Text(IOSSettingsText.versionIdentity(IOSSettingsSupportInfo.version, build: IOSSettingsSupportInfo.build))
            .font(.footnote)
            .foregroundStyle(Theme.Text.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("iosSettings_versionLabel")
            .accessibilityLabel(IOSSettingsText.version)
            .accessibilityValue("\(IOSSettingsSupportInfo.version) (\(IOSSettingsSupportInfo.build))")
    }
}

private enum IOSSettingsActionButtonProminence {
    case primary
    case secondary
    case destructive
}

private struct IOSSettingsActionButtonStyle: ButtonStyle {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    let tint: Color
    let prominence: IOSSettingsActionButtonProminence

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption.weight(.semibold))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, 10)
            .frame(minWidth: 44, minHeight: 44)
            .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : 112)
            .background(backgroundColor(configuration: configuration))
            .clipShape(Capsule(style: .continuous))
            .overlay {
                Capsule(style: .continuous)
                    .stroke(strokeColor(configuration: configuration), lineWidth: 0.5)
            }
            .opacity(configuration.isPressed ? 0.82 : 1)
    }

    private var foregroundColor: Color {
        switch prominence {
        case .primary: Theme.Text.onAccent
        case .secondary: tint
        case .destructive: Theme.Status.critical
        }
    }

    private func backgroundColor(configuration: Configuration) -> Color {
        switch prominence {
        case .primary:
            tint.opacity(configuration.isPressed ? 0.72 : 0.92)
        case .secondary, .destructive:
            Theme.Surface.inline
        }
    }

    private func strokeColor(configuration: Configuration) -> Color {
        let opacity = configuration.isPressed ? 0.68 : 0.42
        return switch prominence {
        case .primary: Color.white.opacity(configuration.isPressed ? 0.12 : 0.18)
        case .secondary: tint.opacity(opacity)
        case .destructive: Theme.Status.critical.opacity(opacity)
        }
    }
}

/// A fixed-geometry transfer indicator whose rendered fill and accessibility value share the
/// same exact fraction. The opaque recessed track keeps every mode tint above the diagnostic
/// lane's 3:1 non-text contrast floor and gives screenshot analysis a stable six-point frame.
private struct IOSModelTransferProgressBar: View {
    let fraction: Double
    let tint: Color
    let accessibilityLabel: String
    let accessibilityValue: String
    let accessibilityIdentifier: String

    var body: some View {
        GeometryReader { proxy in
            let clamped = min(max(fraction, 0), 1)
            let filledWidth = CGFloat(IOSModelProgressPresentation.visibleDeterminateFillWidth(
                fraction: clamped,
                width: Double(proxy.size.width),
                thickness: Double(proxy.size.height)
            ))
            ZStack(alignment: .leading) {
                Capsule(style: .continuous)
                    .fill(Theme.Surface.inline)
                Capsule(style: .continuous)
                    .fill(tint)
                    .frame(width: filledWidth)
            }
        }
        .frame(height: 6)
        // Model delivery is evidence-bearing state, not decorative motion. A parent transition
        // can otherwise animate the fill from its minimum capsule while accessibility already
        // exposes the new exact-byte fraction, producing a visibly false progress sample.
        .transaction { transaction in
            transaction.animation = nil
            transaction.disablesAnimations = true
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityValue(accessibilityValue)
        .accessibilityIdentifier(accessibilityIdentifier)
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
        VStack(alignment: .leading, spacing: 6) {
            header

            if showsStatusDetail {
                statusDetailView.padding(.leading, dynamicTypeSize.isAccessibilitySize ? 0 : 46)
            }

            if hasVisibleActions, !usesInlineControls {
                controls
                    .padding(.leading, dynamicTypeSize.isAccessibilitySize ? 0 : 46)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("iosModelRow_\(model.id)")
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            IOSSettingsIcon(symbol: modelIconName, tint: Theme.Brand.modeColor(model.mode))

            VStack(alignment: .leading, spacing: 2) {
                Text(IOSSettingsText.modeName(model.mode))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(metadataText)
                    .font(.caption)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                statusLabel
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if usesInlineControls {
                actionControls
                    .fixedSize(horizontal: true, vertical: false)
            }
        }
    }

    private var statusLabel: some View {
        Label(statusText, systemImage: statusSymbol)
            .font(.caption.weight(.semibold))
            .foregroundStyle(statusTint)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityLabel(IOSSettingsText.modelStatus(IOSSettingsText.modeName(model.mode)))
            .accessibilityValue(statusText)
            .accessibilityIdentifier("iosModelStatus_\(model.id)")
    }

    private var controls: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 8))

        return layout {
            actionControls
        }
    }

    @ViewBuilder
    private var actionControls: some View {
        switch operationState {
        case .idle:
            switch status {
            case .installed:
                removalAction
            case .updateAvailable:
                actionButton(
                    IOSSettingsText.update,
                    symbol: "arrow.triangle.2.circlepath",
                    id: "iosModelUpdate_\(model.id)",
                    action: requestInstall
                )
                removalAction
            case .checking:
                EmptyView()
            case .notInstalled:
                actionButton(
                    IOSSettingsText.install,
                    symbol: "arrow.down.circle.fill",
                    id: "iosModelDownload_\(model.id)",
                    action: requestInstall
                )
            case .incomplete:
                actionButton(
                    IOSSettingsText.repair,
                    symbol: "wrench.and.screwdriver.fill",
                    id: "iosModelRepair_\(model.id)",
                    action: requestInstall
                )
                removalAction
            case .error:
                actionButton(
                    IOSSettingsText.retry,
                    symbol: "arrow.clockwise",
                    id: "iosModelRetry_\(model.id)",
                    action: requestInstall
                )
            }
        case .installed:
            removalAction
        case .available:
            actionButton(
                IOSSettingsText.install,
                symbol: "arrow.down.circle.fill",
                id: "iosModelDownload_\(model.id)",
                action: requestInstall
            )
        case .queued, .waitingForConnectivity, .downloading, .retrying:
            actionButton(
                IOSSettingsText.cancel,
                symbol: "xmark",
                id: "iosModelCancel_\(model.id)",
                prominence: .secondary,
                accessibilityTitle: IOSSettingsText.cancelDownload,
                action: requestCancelOptions
            )
        case .verifying, .installing, .cancelling, .deleting:
            EmptyView()
        case .unavailable:
            if case .incomplete = status { removalAction }
        case .failed:
            actionButton(
                IOSSettingsText.retry,
                symbol: "arrow.clockwise",
                id: "iosModelRetry_\(model.id)",
                action: requestInstall
            )
        }
    }

    /// Keep the legacy `iosModelMenu_*` container identifier on the visible action so existing
    /// automation can still recognize an installed model after the overflow menu is retired.
    private var removalAction: some View {
        HStack(spacing: 0) {
            actionButton(
                IOSSettingsText.remove,
                symbol: "trash",
                id: "iosModelDelete_\(model.id)",
                prominence: .destructive,
                action: requestDelete
            )
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("iosModelMenu_\(model.id)")
    }

    private func actionButton(
        _ title: String,
        symbol: String,
        id: String,
        prominence: IOSSettingsActionButtonProminence = .primary,
        accessibilityTitle: String? = nil,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .fixedSize(horizontal: !dynamicTypeSize.isAccessibilitySize, vertical: true)
        }
        .buttonStyle(IOSSettingsActionButtonStyle(
            tint: Theme.Brand.modeColor(model.mode),
            prominence: prominence
        ))
        .accessibilityLabel(IOSSettingsText.modelAction(accessibilityTitle ?? title, IOSSettingsText.modeName(model.mode)))
        .accessibilityIdentifier(id)
    }

    private var hasVisibleActions: Bool {
        switch operationState {
        case .idle:
            if case .checking = status { return false }
            return true
        case .installed, .available, .queued, .waitingForConnectivity, .downloading, .retrying, .failed:
            return true
        case .verifying, .installing, .cancelling, .deleting:
            return false
        case .unavailable:
            if case .incomplete = status { return true }
            return false
        }
    }

    private var visibleActionCount: Int {
        switch operationState {
        case .idle:
            switch status {
            case .checking: return 0
            case .updateAvailable, .incomplete: return 2
            case .installed, .notInstalled, .error: return 1
            }
        case .installed, .available, .queued, .waitingForConnectivity,
             .downloading, .retrying, .failed:
            return 1
        case .unavailable:
            if case .incomplete = status { return 1 }
            return 0
        case .verifying, .installing, .cancelling, .deleting:
            return 0
        }
    }

    /// Ordinary text sizes keep the single state-appropriate action beside the model summary.
    /// Accessibility sizes and the two-action repair/update states retain a vertical reflow.
    private var usesInlineControls: Bool {
        !dynamicTypeSize.isAccessibilitySize && visibleActionCount == 1
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
            modelName: IOSSettingsText.modeName(model.mode),
            sizeLabel: deleteSheetSizeLabel,
            onConfirm: { onDelete() }
        ))
    }

    private var deleteSheetSizeLabel: String {
        switch status {
        case .installed(let sizeBytes), .updateAvailable(let sizeBytes, _), .incomplete(_, let sizeBytes):
            return IOSSettingsFormatters.fileSize(Int64(sizeBytes))
        default:
            return model.estimatedDownloadBytes.map(IOSSettingsFormatters.fileSize) ?? IOSSettingsText.severalGB
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
        return parts.isEmpty ? IOSSettingsText.onDeviceModel : parts.joined(separator: " · ")
    }

    private var statusText: String {
        switch operationState {
        case .idle:
            switch status {
            case .checking: return IOSSettingsText.checking
            case .notInstalled: return IOSSettingsText.notInstalled
            case .installed: return IOSAppLanguage.shared.presentation.status(.ready)
            case .updateAvailable: return IOSSettingsText.updateAvailable
            case .incomplete: return IOSSettingsText.repairNeeded
            case .error: return IOSSettingsText.retryNeeded
            }
        case .installed: return IOSAppLanguage.shared.presentation.status(.ready)
        case .available: return IOSSettingsText.notInstalled
        case .queued: return IOSSettingsText.queued
        case .waitingForConnectivity: return IOSSettingsText.waitingForNetwork
        case .downloading: return transferIsComplete ? IOSSettingsText.finishing : IOSSettingsText.downloading
        case .retrying: return transferIsComplete ? IOSSettingsText.finishing : IOSSettingsText.retrying
        case .verifying: return IOSSettingsText.verifying
        case .installing: return IOSSettingsText.installing
        case .cancelling: return IOSSettingsText.cancelling
        case .deleting: return IOSSettingsText.removing
        case .unavailable: return IOSSettingsText.repairNeeded
        case .failed: return IOSSettingsText.retryNeeded
        }
    }

    private var statusSymbol: String {
        switch operationState {
        case .queued: return "clock"
        case .waitingForConnectivity: return "wifi.exclamationmark"
        case .downloading: return "arrow.down.circle"
        case .retrying: return "arrow.clockwise"
        case .verifying: return "checkmark.shield"
        case .installing: return "shippingbox"
        case .cancelling: return "xmark.circle"
        case .deleting: return "trash"
        case .failed: return "exclamationmark.arrow.triangle.2.circlepath"
        case .installed: return "checkmark.circle"
        case .available: return "arrow.down.circle"
        case .unavailable: return "wrench.and.screwdriver"
        case .idle:
            switch status {
            case .checking: return "magnifyingglass"
            case .notInstalled: return "arrow.down.circle"
            case .installed: return "checkmark.circle"
            case .updateAvailable: return "arrow.triangle.2.circlepath.circle"
            case .incomplete: return "wrench.and.screwdriver"
            case .error: return "exclamationmark.arrow.triangle.2.circlepath"
            }
        }
    }

    private var statusTint: Color {
        switch operationState {
        case .installed:
            return Theme.Status.healthy
        case .queued, .waitingForConnectivity, .downloading, .retrying,
             .verifying, .installing, .cancelling, .deleting:
            return Theme.Brand.modeColor(model.mode)
        case .failed, .unavailable:
            return Theme.Status.critical
        case .available:
            return Theme.Brand.silver
        case .idle:
            switch status {
            case .installed: return Theme.Status.healthy
            case .updateAvailable: return Theme.Status.guarded
            case .incomplete, .error: return Theme.Status.critical
            case .checking, .notInstalled: return Theme.Brand.silver
            }
        }
    }

    private var showsStatusDetail: Bool {
        switch operationState {
        case .waitingForConnectivity, .downloading, .retrying, .verifying, .installing, .failed:
            return true
        default:
            if case .incomplete = status { return true }
            if case .error = status { return true }
            return false
        }
    }

    @ViewBuilder
    private var statusDetailView: some View {
        switch operationState {
        case .downloading(_, let downloaded, let total, let speed, let eta, let message):
            modelProgressPresentation(.transfer(
                durableBytes: downloaded,
                catalogBytes: total,
                bytesPerSecond: speed,
                estimatedSecondsRemaining: eta,
                suffix: message,
                text: IOSAppLanguage.shared.presentation,
                formatBytes: IOSSettingsFormatters.fileSize
            ))
        case .waitingForConnectivity(let downloaded, let total):
            modelProgressPresentation(.transfer(
                durableBytes: downloaded,
                catalogBytes: total,
                suffix: IOSSettingsText.waitingForNetwork,
                text: IOSAppLanguage.shared.presentation,
                formatBytes: IOSSettingsFormatters.fileSize
            ))
        case .retrying(_, _, _, let retryCount, let reason):
            modelProgressPresentation(.retrying(
                retryCount: retryCount,
                reason: reason,
                text: IOSAppLanguage.shared.presentation
            ))
        case .verifying:
            modelProgressPresentation(.init(indicator: .indeterminate,
                detail: IOSAppLanguage.shared.presentation.status(.checkingDownloadedFiles) + "."))
        case .installing:
            modelProgressPresentation(.init(indicator: .indeterminate,
                detail: IOSAppLanguage.shared.presentation.status(.makingModelAvailableOffline) + "."))
        case .failed(let message):
            detailText(message, color: .red)
        default:
            switch status {
            case .incomplete(let message, _), .error(let message): detailText(message, color: .red)
            default: EmptyView()
            }
        }
    }

    @ViewBuilder
    private func modelProgressPresentation(_ presentation: IOSModelProgressPresentation) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            switch presentation.indicator {
            case .determinate(let fraction, let accessibilityValue):
                IOSModelTransferProgressBar(
                    fraction: fraction,
                    tint: Theme.Brand.modeColor(model.mode),
                    accessibilityLabel: IOSSettingsText.modelProgress(IOSSettingsText.modeName(model.mode)),
                    accessibilityValue: accessibilityValue,
                    accessibilityIdentifier: "iosModelProgress_\(model.id)"
                )
            case .indeterminate:
                ProgressView()
                    .tint(Theme.Brand.modeColor(model.mode))
                    .accessibilityLabel(IOSSettingsText.modelSetup(IOSSettingsText.modeName(model.mode)))
                    .accessibilityIdentifier("iosModelPhaseActivity_\(model.id)")
            }
            detailText(presentation.detail)
                .accessibilityIdentifier("iosModelProgressDetail_\(model.id)")
        }
    }

    private var transferIsComplete: Bool {
        switch operationState {
        case .downloading(_, let downloaded, let total, _, _, _),
             .retrying(_, let downloaded, let total, _, _):
            guard let total, total > 0 else { return false }
            return downloaded >= total
        default:
            return false
        }
    }

    private func detailText(_ text: String, color: Color = Theme.Text.secondary) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }

}
