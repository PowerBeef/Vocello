import AppKit
import QwenVoiceCore
import SwiftUI

/// The desktop model rows in the iOS row language: the recommended-setup
/// summary, then one row per generation mode carrying its Speed and Quality
/// packages with the badge, the status and the state-dependent action
/// (Download, Cancel, Repair, Update, Manage). Every `settings_*`
/// identifier is the lane contract; the three Speed status labels and
/// badges stay single-line and the Manage button stays inside the window.
struct MacModelSetupSummaryRow: View {
    @Environment(ModelManagerViewModel.self) private var viewModel

    var body: some View {
        let summary = viewModel.modelSetupSummary()
        let setupProgress = viewModel.recommendedSetupProgress
        let isComplete = summary.installedRecommendedCount == summary.totalRecommendedCount

        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 12) {
                HStack(alignment: .top, spacing: 10) {
                    MacSettingsIcon(
                        symbol: isComplete ? "checkmark.circle.fill" : "arrow.down.circle",
                        tint: isComplete ? MacTheme.Status.healthy : MacTheme.settingsTint
                    )
                    Text(summary.text)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(MacTheme.Text.primary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("settings_modelDownloadsSummary")
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if setupProgress != nil {
                    Button(MacInterfaceText.cancel) {
                        viewModel.cancelRecommendedSetup()
                    }
                    .buttonStyle(MacSettingsActionButtonStyle(tint: MacTheme.settingsTint))
                    .accessibilityIdentifier("settings_cancelRecommendedSetup")
                } else if !viewModel.recommendedSetupCandidates().isEmpty {
                    Button(MacInterfaceText.settingsDownloadRecommended) {
                        viewModel.setUpRecommendedModels()
                    }
                    .buttonStyle(MacSettingsActionButtonStyle(tint: MacTheme.accent, prominence: .primary))
                    .accessibilityIdentifier("settings_downloadRecommendedModels")
                }
            }

            if let setupProgress {
                VStack(alignment: .leading, spacing: 4) {
                    MacSettingsProgressBar(
                        fraction: setupProgress.fraction,
                        tint: MacTheme.accent,
                        accessibilityLabel: MacInterfaceText.settingsDownloadRecommended,
                        accessibilityValue: setupProgress.fraction.formatted(.percent.precision(.fractionLength(0)).locale(MacInterfaceLanguage.current.locale)),
                        accessibilityIdentifier: "settings_recommendedSetupProgressBar"
                    )
                    Text(setupProgressText(setupProgress))
                        .font(.footnote)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                        .accessibilityIdentifier("settings_recommendedSetupProgress")
                }
                .padding(.leading, 38)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private func setupProgressText(_ progress: ModelManagerViewModel.RecommendedSetupProgress) -> String {
        if let modelID = progress.currentModelID,
           let model = TTSModel.model(id: modelID) {
            return MacInterfaceText.settingsDownloadingProgress(
                MacInterfaceText.modeName(model.mode), viewModel.activeVariantLabel(for: model),
                String(progress.completedCount), String(progress.totalCount)
            )
        }
        return MacInterfaceText.settingsProgressComplete(String(progress.completedCount), String(progress.totalCount))
    }
}

struct MacModelModeRow: View {
    @Environment(ModelManagerViewModel.self) private var viewModel

    let mode: GenerationMode
    let isFlashed: Bool
    let onDelete: (TTSModel) -> Void

    var body: some View {
        let variants = viewModel.variants(for: mode)

        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                MacSettingsIcon(symbol: MacTheme.modeGlyph(for: mode), tint: MacTheme.Brand.modeColor(mode))

                VStack(alignment: .leading, spacing: 2) {
                    Text(MacInterfaceText.modeName(mode))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(MacTheme.Text.primary)
                        .lineLimit(1)
                    // Mode-constant facts live here once (purpose, size)
                    // instead of repeating on every package line below.
                    Text(modeSubtitle(variants))
                        .font(.footnote)
                        .foregroundStyle(MacTheme.Text.secondary)
                        .lineLimit(1)
                }
            }

            VStack(spacing: 6) {
                ForEach(variants) { model in
                    MacModelPackageLine(model: model, onDelete: { onDelete(model) })
                }
            }
            .padding(.leading, 38)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(isFlashed ? MacTheme.accent.opacity(0.10) : Color.clear)
        .appAnimation(MacTheme.Motion.stateChange, value: isFlashed)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings_mode_\(mode.rawValue)")
    }

    private func modeSubtitle(_ variants: [TTSModel]) -> String {
        var parts = [viewModel.modePurpose(for: mode)]
        if let size = variants.first?.modelSizeLabel {
            parts.append(size)
        }
        return parts.joined(separator: " · ")
    }
}

struct MacModelPackageLine: View {
    @Environment(ModelManagerViewModel.self) private var viewModel

    let model: TTSModel
    let onDelete: () -> Void

    var body: some View {
        let presentation = viewModel.packagePresentation(for: model)
        let status = viewModel.statuses[model.id] ?? .checking
        let shape = VocelloShape.input()

        VStack(alignment: .leading, spacing: 6) {
            // Two lines, like the phone's model row: the package names itself
            // on the first, its state and controls follow on the second. One
            // line could not hold four labels plus a button at a narrow window
            // — under pseudo-localization the badge collapsed to 8 pt — and
            // squeezing any of them truncated a label the lanes read.
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                // "Speed · 4-bit": the tier plus only the per-row fact.
                Text(compactVariantLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                packageBadge
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                    .accessibilityIdentifier("settings_packageBadge_\(model.id)")

                Spacer(minLength: 6)
            }

            HStack(alignment: .center, spacing: 8) {
                HStack(spacing: 5) {
                    statusGlyph(presentation.kind)
                    Text(presentation.label)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(statusColor(presentation.kind))
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                        .accessibilityIdentifier("settings_packageStatus_\(model.id)")
                }

                Spacer(minLength: 8)

                MacModelPackageAction(model: model, status: status, onDelete: onDelete)
            }

            // Dynamic detail only (repair reasons, download specifics).
            if let detail = presentation.detail {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }

            if case .downloading(let progress) = status,
               let total = progress.totalBytes,
               total > 0 {
                let fraction = Double(progress.downloadedBytes) / Double(total)
                MacSettingsProgressBar(
                    fraction: fraction,
                    tint: MacTheme.Brand.modeColor(model.mode),
                    accessibilityLabel: MacInterfaceText.download,
                    accessibilityValue: fraction.formatted(.percent.precision(.fractionLength(0)).locale(MacInterfaceLanguage.current.locale)),
                    accessibilityIdentifier: "settings_downloadProgress_\(model.id)"
                )
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background { shape.fill(Color.white.opacity(0.03)) }
        .overlay { shape.stroke(MacTheme.Surface.hairline, lineWidth: 0.5) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings_package_\(model.id)")
    }

    @ViewBuilder
    private var packageBadge: some View {
        if viewModel.isHardwareRisky(model) {
            Text(MacInterfaceText.settingsHeavy)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(MacTheme.Status.guarded)
                .help(MacInterfaceText.settingsHeavyOnThisMac)
                .accessibilityLabel(MacInterfaceText.settingsHeavyOnThisMac)
        } else if viewModel.isHardwareRecommended(model) {
            // Quiet, not green: static guidance; install state is the row's
            // one semantic color.
            Text(MacInterfaceText.settingsRecommended)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(MacTheme.Text.secondary)
        }
    }

    private var compactVariantLabel: String {
        let kind = model.variantKind?.displayName ?? MacInterfaceText.modeName(model.mode)
        guard let depth = model.variantKind?.depthLabel else {
            return kind
        }
        return "\(kind) · \(depth)"
    }

    @ViewBuilder
    private func statusGlyph(_ kind: ModelManagerViewModel.ModelPackageStatusKind) -> some View {
        switch kind {
        case .checking, .downloading:
            ProgressView()
                .controlSize(.mini)
        case .ready:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(MacTheme.Status.healthy)
                .imageScale(.small)
        case .notInstalled:
            Image(systemName: "arrow.down.circle")
                .foregroundStyle(MacTheme.Text.secondary)
                .imageScale(.small)
        case .needsRepair:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(MacTheme.Status.guarded)
                .imageScale(.small)
        case .updateAvailable:
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .foregroundStyle(MacTheme.accent)
                .imageScale(.small)
        }
    }

    private func statusColor(_ kind: ModelManagerViewModel.ModelPackageStatusKind) -> Color {
        switch kind {
        case .ready: MacTheme.Status.healthy
        case .needsRepair: MacTheme.Status.guarded
        case .updateAvailable: MacTheme.accent
        case .checking, .downloading, .notInstalled: MacTheme.Text.secondary
        }
    }
}

/// Compact package control whose role flips with install state.
private struct MacModelPackageAction: View {
    @Environment(ModelManagerViewModel.self) private var viewModel

    let model: TTSModel
    let status: ModelManagerViewModel.ModelStatus
    let onDelete: () -> Void

    /// Holder for the NSView that backs the Manage button, the anchor for
    /// the AppKit `NSMenu` pop-up.
    @State private var manageHostHolder = NSViewHostHolder()

    private static let slotWidth: CGFloat = 92

    var body: some View {
        switch status {
        case .checking:
            ProgressView()
                .controlSize(.small)
                .accessibilityIdentifier("settings_checking_\(model.id)")

        case .notDownloaded:
            Button(MacInterfaceText.download) {
                Task { await viewModel.download(model) }
            }
            .buttonStyle(packageStyle(tint: modeTint, prominence: .primary))
            .help(downloadHelp)
            .accessibilityIdentifier("settings_download_\(model.id)")

        case .downloading:
            Button(MacInterfaceText.cancel) {
                Task { await viewModel.cancelDownload(model) }
            }
            .buttonStyle(packageStyle(tint: modeTint))
            .help(MacInterfaceText.settingsCancelDownloadHelp)
            .accessibilityIdentifier("settings_cancel_\(model.id)")

        case .repairAvailable:
            Button(MacInterfaceText.settingsRepair) {
                Task { await viewModel.download(model) }
            }
            .buttonStyle(packageStyle(tint: MacTheme.Status.guarded, prominence: .primary))
            .accessibilityIdentifier("settings_repair_\(model.id)")

        case .updateAvailable:
            HStack(spacing: 6) {
                Button(MacInterfaceText.settingsUpdate) {
                    Task { await viewModel.download(model) }
                }
                .buttonStyle(packageStyle(tint: modeTint, prominence: .primary))
                .help(MacInterfaceText.settingsUpdateHelp)
                .accessibilityIdentifier("settings_update_\(model.id)")

                manageButton
            }

        case .downloaded:
            manageButton
        }
    }

    private var manageButton: some View {
        Button(MacInterfaceText.settingsManage) {
            presentManageMenu()
        }
        .buttonStyle(packageStyle(tint: modeTint))
        .background(NSViewHostAccessor(holder: manageHostHolder))
        .help(MacInterfaceText.settingsManageHelp(model.variantKind?.displayName ?? MacInterfaceText.modeName(model.mode)))
        .accessibilityIdentifier("settings_manage_\(model.id)")
    }

    private var modeTint: Color {
        MacTheme.Brand.modeColor(model.mode)
    }

    private func packageStyle(
        tint: Color,
        prominence: MacSettingsActionProminence = .secondary
    ) -> MacSettingsActionButtonStyle {
        MacSettingsActionButtonStyle(tint: tint, prominence: prominence, width: Self.slotWidth)
    }

    private var downloadHelp: String {
        if let size = viewModel.sizeText(for: model) {
            return MacInterfaceText.settingsDownloadSize(size)
        }
        return MacInterfaceText.download
    }

    /// A real AppKit menu popped up from the Manage button's host view:
    /// Reveal in Finder selects the model folder inside its parent, Delete
    /// hands back to the screen's confirmation.
    private func presentManageMenu() {
        guard let host = manageHostHolder.view else { return }

        let menu = NSMenu()
        menu.addItem(ClosureMenuItem(
            title: MacInterfaceText.revealInFinder,
            systemImage: "folder",
            handler: {
                let url = model.installDirectory(in: QwenVoiceApp.modelsDir)
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        ))
        menu.addItem(.separator())
        menu.addItem(ClosureMenuItem(
            title: MacInterfaceText.settingsDeleteModel,
            systemImage: "trash",
            isDestructive: true,
            handler: onDelete
        ))

        menu.popUp(
            positioning: nil,
            at: NSPoint(x: 0, y: host.bounds.height + 2),
            in: host
        )
    }
}

// MARK: - AppKit menu bridge

/// Weak handle on the NSView behind the Manage button; `@State`-friendly
/// because SwiftUI keeps the same instance across renders.
private final class NSViewHostHolder {
    weak var view: NSView?
}

/// Captures the SwiftUI button's host NSView through a transparent
/// background view mounted in the same position, so its bounds anchor the menu.
private struct NSViewHostAccessor: NSViewRepresentable {
    let holder: NSViewHostHolder

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        holder.view = view
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        holder.view = nsView
    }
}

/// `NSMenuItem` that retains a Swift closure and runs it when selected.
private final class ClosureMenuItem: NSMenuItem {
    private let handler: () -> Void

    init(
        title: String,
        systemImage: String? = nil,
        isDestructive: Bool = false,
        handler: @escaping () -> Void
    ) {
        self.handler = handler
        super.init(
            title: title,
            action: #selector(invoke),
            keyEquivalent: ""
        )
        target = self
        if let systemImage {
            image = NSImage(systemSymbolName: systemImage, accessibilityDescription: nil)
        }
        if isDestructive {
            attributedTitle = NSAttributedString(
                string: title,
                attributes: [.foregroundColor: NSColor.systemRed]
            )
        }
    }

    @available(*, unavailable)
    required init(coder: NSCoder) {
        fatalError("init(coder:) is not supported for ClosureMenuItem")
    }

    @objc private func invoke() {
        handler()
    }
}
