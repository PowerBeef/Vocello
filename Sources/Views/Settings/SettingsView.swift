import SwiftUI
import QwenVoiceCore
import AppKit

/// Unified Settings surface, modeled on macOS System Settings.
///
/// Single in-app surface that hosts model downloads + playback +
/// storage. Settings remain grouped by user-facing responsibility:
///
/// 1. Model downloads. Compact status/action rows for the
///    locally managed Speed and Quality packages.
///
/// 2. Playback. Auto-play controls the final-file handoff after generation.
///
/// 3. Storage. Output directory + Application data, two compact
///    rows.
///
/// Mode color identity attaches to each row's leading 8 pt dot
/// rather than the section header.
struct SettingsView: View {
    @Environment(ModelManagerViewModel.self) private var viewModel
    /// Mode-keyed deep-link target. When the sidebar redirects
    /// the user to Settings (because a generation tab's required
    /// variant is missing), the upstream `ContentView` sets this
    /// so the Model downloads section can scroll to and flash that mode's
    /// row. Mode-keyed instead of model-id-keyed because the row
    /// is mode-keyed; the missing variant might not be the
    /// current generation selection.
    @Binding var highlightedMode: GenerationMode?
    private let showsNavigationTitle: Bool

    @AppStorage("autoPlay", store: AppDefaults.store) private var autoPlay = true
    @AppStorage("vocello.voiceCloningConsent.v1", store: AppDefaults.store)
    private var cloneConsentAcknowledged = false
    @AppStorage("outputDirectory", store: AppDefaults.store) private var outputDirectory = ""
    @AppStorage(GenerationVariationPreference.key, store: AppDefaults.store)
    private var generationVariation = GenerationVariationPreference.defaultValue
    /// Bound to `MacModelVariantPreferences.preferSpeedEverywhereKey`.
    /// When ON, every generation mode resolves to the Speed variant
    /// regardless of per-mode preferences or hardware recommendations.
    /// Useful on memory-constrained Macs.
    @AppStorage(MacModelVariantPreferences.preferSpeedEverywhereKey, store: AppDefaults.store)
    private var preferSpeedEverywhere = false

    @State private var flashedMode: GenerationMode?
    @State private var modelToDelete: TTSModel?
    @State private var showDeleteConfirmation = false
    /// Non-nil when the configured output folder is missing/unwritable
    /// (AudioService falls back to the default outputs folder).
    @State private var outputDirectoryIssue: String?

    init(highlightedMode: Binding<GenerationMode?>, showsNavigationTitle: Bool = true) {
        _highlightedMode = highlightedMode
        self.showsNavigationTitle = showsNavigationTitle
    }

    var body: some View {
        ScrollViewReader { proxy in
            Form {
                Section("Model downloads") {
                    ModelSetupSummaryRow(viewModel: viewModel)

                    ForEach(GenerationMode.allCases, id: \.self) { mode in
                        ModelDownloadRow(
                            mode: mode,
                            viewModel: viewModel,
                            isFlashed: flashedMode == mode,
                            onDelete: { model in request(delete: model) }
                        )
                        .id(mode.rawValue)
                    }
                }

                Section("Playback") {
                    Toggle("Auto-play generated audio", isOn: $autoPlay)
                        .tint(AppTheme.preferences)
                        .accessibilityIdentifier("preferences_autoPlayToggle")
                }

                Section {
                    Picker("Variation", selection: $generationVariation) {
                        ForEach(Qwen3SamplingVariation.allCases, id: \.rawValue) { variation in
                            Text(variation.displayName).tag(variation.rawValue)
                        }
                    }
                    .pickerStyle(.segmented)
                    // Gold, not system blue: the only other saturated blue
                    // in the app was removed in the accent unification.
                    .tint(AppTheme.accent)
                    .accessibilityIdentifier("settings_generationVariation")
                    Text(
                        "How much takes vary when regenerating the same text. " +
                        "Expressive is the model's official sampling (liveliest); " +
                        "Balanced and Consistent trade some liveliness for steadier, more repeatable takes."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                } header: {
                    Text("Generation")
                }

                Section {
                    Toggle(isOn: $preferSpeedEverywhere) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Prefer lower-memory models")
                                .font(.body)
                            Text(
                                "Pins every generation mode to the Speed package. " +
                                "Speed uses less memory and is safer on lower-RAM Macs, with lower fidelity than Quality. " +
                                "You can still switch per-generation in the mode screens; this toggle just changes the defaults."
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .tint(AppTheme.preferences)
                    .accessibilityIdentifier("settings_preferSpeedEverywhere")
                } header: {
                    Text("Performance")
                }

                Section("Storage") {
                    LabeledContent("Output directory") {
                        HStack(spacing: 6) {
                            if outputDirectoryIssue != nil {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .font(.caption)
                                    .foregroundStyle(.orange)
                                    .help(outputDirectoryIssue ?? "")
                                    .accessibilityIdentifier("preferences_outputDirectoryWarning")
                            }
                            Text(outputDirectorySummary)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .accessibilityIdentifier("preferences_outputDirectory")
                            Button("Choose…") { browseForOutputDirectory() }
                                .controlSize(.small)
                                .accessibilityIdentifier("preferences_browseButton")
                            if !outputDirectory.isEmpty {
                                Button("Reset") { outputDirectory = "" }
                                    .controlSize(.small)
                                    .buttonStyle(.borderless)
                                    .accessibilityIdentifier("preferences_outputResetButton")
                            }
                        }
                    }

                    if let outputDirectoryIssue {
                        Text(outputDirectoryIssue)
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("preferences_outputDirectoryIssue")
                    }

                    // Application data row carries the version
                    // text inline so the dedicated About section is
                    // unnecessary. Settings stays at three sections;
                    // the About box (menu Vocello -> About Vocello)
                    // already covers full version detail in the
                    // standard macOS spot.
                    LabeledContent("Application data") {
                        HStack(spacing: 8) {
                            Text(appVersion)
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(AppTheme.textMuted)
                            Button("Reveal in Finder") {
                                NSWorkspace.shared.open(QwenVoiceApp.appSupportDir)
                            }
                            .controlSize(.small)
                            .accessibilityIdentifier("preferences_openFinderButton")
                        }
                    }
                }

                // Last, not first: this is the persistent record of the
                // one-time acknowledgment (also offered inline in the
                // cloning flow) — a policy row, not the screen's job.
                Section("Voice cloning") {
                    Toggle(isOn: $cloneConsentAcknowledged) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("I own or have permission to clone the voices I use")
                            Text("Only clone voices you own or have explicit permission to use.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            // CP-1 option D: the users' own EU AI Act Article
                            // 50(4) disclosure duty, beside the rights gate.
                            Text("If you publish audio of a cloned real voice, disclose that it is AI-generated. EU law may require this.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .tint(AppTheme.voiceCloning)
                    .accessibilityIdentifier("voiceCloning_consentAcknowledgment")
                }
            }
            .formStyle(.grouped)
            // Match the darker canvas background used by Generate
            // tabs. Without this, Form's grouped style paints its
            // own lighter gray panel that diverges from the rest
            // of the app's chrome.
            .scrollContentBackground(.hidden)
            .frame(maxWidth: LayoutConstants.contentMaxWidth)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .settingsNavigationTitle(showsNavigationTitle)
            .accessibilityIdentifier("screen_settings")
            .task {
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
                await viewModel.refresh()
                focusHighlighted(using: proxy)
            }
            .onChange(of: highlightedMode) { _, _ in
                focusHighlighted(using: proxy)
            }
            .onChange(of: outputDirectory) { _, _ in
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
            }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                // The folder may have been deleted/restored while the user
                // was away — keep the warning truthful.
                outputDirectoryIssue = AudioService.configuredOutputDirectoryIssue()
            }
        }
        .alert("Delete Model?", isPresented: $showDeleteConfirmation) {
            Button("Cancel", role: .cancel) { modelToDelete = nil }
            Button("Delete", role: .destructive) {
                if let model = modelToDelete {
                    Task { await viewModel.delete(model) }
                }
                modelToDelete = nil
            }
        } message: {
            if let model = modelToDelete {
                Text(deleteMessage(for: model))
            }
        }
    }

    private func request(delete model: TTSModel) {
        modelToDelete = model
        showDeleteConfirmation = true
    }

    private func deleteMessage(for model: TTSModel) -> String {
        let variant = viewModel.activeVariantLabel(for: model)
        let status = viewModel.statuses[model.id]
        let sizeText: String = {
            switch status {
            case .downloaded(let sizeBytes), .updateAvailable(let sizeBytes, _):
                guard sizeBytes > 0 else { return "" }
                let size = ByteCountFormatter.string(fromByteCount: Int64(sizeBytes), countStyle: .file)
                return " (\(size))"
            default:
                return ""
            }
        }()
        return "This will delete \(model.mode.displayName) \(variant)\(sizeText) from disk. You can download it again later."
    }

    private var outputDirectorySummary: String {
        if outputDirectory.isEmpty { return "Default" }
        return outputDirectory
    }

    private func browseForOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            outputDirectory = url.path
        }
    }

    private var appVersion: String {
        let dict = Bundle.main.infoDictionary ?? [:]
        let version = dict["CFBundleShortVersionString"] as? String ?? "?"
        let build = dict["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }

    private func focusHighlighted(using proxy: ScrollViewProxy) {
        guard let mode = highlightedMode else { return }
        AppLaunchConfiguration.performAnimated(.spring(response: 0.35, dampingFraction: 0.82)) {
            proxy.scrollTo(mode.rawValue, anchor: .center)
        }
        flashedMode = mode
        self.highlightedMode = nil

        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await MainActor.run {
                if flashedMode == mode { flashedMode = nil }
            }
        }
    }
}

private extension View {
    @ViewBuilder
    func settingsNavigationTitle(_ isVisible: Bool) -> some View {
        if isVisible {
            navigationTitle("Settings")
        } else {
            self
        }
    }
}

// MARK: - Model download rows

private struct ModelSetupSummaryRow: View {
    var viewModel: ModelManagerViewModel

    private var summary: ModelManagerViewModel.ModelSetupSummary {
        viewModel.modelSetupSummary()
    }

    private var setupProgress: ModelManagerViewModel.RecommendedSetupProgress? {
        viewModel.recommendedSetupProgress
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Label(summary.text, systemImage: summaryIconName)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.primary)
                    .labelStyle(.titleAndIcon)
                    .accessibilityIdentifier("settings_modelDownloadsSummary")

                Spacer(minLength: 12)

                if setupProgress != nil {
                    Button("Cancel") {
                        viewModel.cancelRecommendedSetup()
                    }
                    .controlSize(.small)
                    .accessibilityIdentifier("settings_cancelRecommendedSetup")
                } else if !viewModel.recommendedSetupCandidates().isEmpty {
                    Button("Download recommended") {
                        viewModel.setUpRecommendedModels()
                    }
                    .controlSize(.small)
                    .accessibilityIdentifier("settings_downloadRecommendedModels")
                }
            }

            if let setupProgress {
                VStack(alignment: .leading, spacing: 4) {
                    ProgressView(value: setupProgress.fraction)
                        .progressViewStyle(.linear)
                        .tint(AppTheme.statusProgressTint)
                    Text(setupProgressText(setupProgress))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .accessibilityIdentifier("settings_recommendedSetupProgress")
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var summaryIconName: String {
        summary.installedRecommendedCount == summary.totalRecommendedCount
            ? "checkmark.circle.fill"
            : "arrow.down.circle"
    }

    private func setupProgressText(_ progress: ModelManagerViewModel.RecommendedSetupProgress) -> String {
        if let modelID = progress.currentModelID,
           let model = TTSModel.model(id: modelID) {
            return "Downloading \(model.mode.displayName) \(viewModel.activeVariantLabel(for: model)) · \(progress.completedCount) of \(progress.totalCount) complete"
        }
        return "\(progress.completedCount) of \(progress.totalCount) complete"
    }
}

private struct ModelDownloadRow: View {
    let mode: GenerationMode
    var viewModel: ModelManagerViewModel
    let isFlashed: Bool
    let onDelete: (TTSModel) -> Void

    private var variants: [TTSModel] {
        viewModel.variants(for: mode)
    }

    private var modeSubtitle: String {
        var parts = [viewModel.modePurpose(for: mode)]
        if let first = variants.first {
            if let size = first.modelSizeLabel {
                parts.append(size)
            }
            if mode == .custom, first.supportsInstructionControl {
                parts.append("delivery control")
            } else if mode == .clone, first.supportsVoiceClone {
                parts.append("clone capable")
            }
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Image(systemName: AppTheme.modeGlyph(for: mode))
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(AppTheme.modeColor(for: mode))
                    .frame(width: 16)
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 2) {
                    Text(mode.displayName)
                        .font(.callout.weight(.semibold))
                        .lineLimit(1)
                    // Mode-constant facts live here once (size, capability)
                    // instead of repeating on every package line below.
                    Text(modeSubtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)
            }

            VStack(spacing: 4) {
                ForEach(variants) { model in
                    ModelPackageLine(
                        model: model,
                        viewModel: viewModel,
                        onDelete: { onDelete(model) }
                    )
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.leading, 18)
        }
        .padding(.vertical, 4)
        .listRowBackground(isFlashed ? Color.accentColor.opacity(0.10) : nil)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings_mode_\(mode.rawValue)")
    }
}

private struct ModelPackageLine: View {
    let model: TTSModel
    var viewModel: ModelManagerViewModel
    let onDelete: () -> Void

    private var presentation: ModelManagerViewModel.ModelPackagePresentation {
        viewModel.packagePresentation(for: model)
    }

    private var status: ModelManagerViewModel.ModelStatus {
        viewModel.statuses[model.id] ?? .checking
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .center, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    // Short tier label ("Speed · 4-bit"): the model size is
                    // mode-constant and already stated once in the mode
                    // subtitle — the old "(1.7B 4-bit)" form repeated it per
                    // row and truncated.
                    Text(compactVariantLabel)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                    packageBadge
                }
                .layoutPriority(1)

                Spacer(minLength: 6)

                HStack(spacing: 5) {
                    statusGlyph
                    Text(presentation.label)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(statusColor)
                        .lineLimit(1)
                        .accessibilityIdentifier("settings_packageStatus_\(model.id)")
                }
                // W1-E: minWidth keeps the status column aligned while
                // letting longer labels grow instead of truncating at
                // larger text sizes.
                .frame(minWidth: 94, alignment: .leading)

                ActionButton(
                    model: model,
                    viewModel: viewModel,
                    onDelete: onDelete
                )
                // Fixed, not minWidth: the button labels fill their slot
                // (maxWidth: .infinity), so a flexible slot let each row's
                // leftover width decide the button size — Manage/Download
                // rendered different widths and misaligned across rows.
                .frame(width: 92, alignment: .trailing)
            }

            // Dynamic detail only (repair reasons, download specifics) —
            // the static size/capability line repeated mode-constant facts
            // on every row and doubled each row's height.
            if let detail = presentation.detail {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }

            downloadProgress
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 8)
        .background(.quaternary.opacity(0.16), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings_package_\(model.id)")
    }

    @ViewBuilder
    private var packageBadge: some View {
        if viewModel.isHardwareRisky(model) {
            Text("Heavy")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.orange)
                .help("Heavy on this Mac")
                .accessibilityLabel("Heavy on this Mac")
        } else if viewModel.isHardwareRecommended(model) {
            // Quiet, not green: this is static guidance — install state is
            // the row's one semantic color.
            Text("Recommended")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
        }
    }

    /// "Speed · 4-bit" — the tier plus only the per-row fact (bit depth).
    private var compactVariantLabel: String {
        let kind = model.variantKind?.displayName ?? model.name
        guard let bits = model.variantKind?.bitDepthLabel,
              let depth = bits.split(separator: " ").last else {
            return kind
        }
        return "\(kind) · \(depth)"
    }

    @ViewBuilder
    private var statusGlyph: some View {
        switch presentation.kind {
        case .checking, .downloading:
            ProgressView()
                .controlSize(.mini)
        case .ready:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.green)
                .imageScale(.small)
        case .notInstalled:
            Image(systemName: "arrow.down.circle")
                .foregroundStyle(.secondary)
                .imageScale(.small)
        case .needsRepair:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
                .imageScale(.small)
        case .updateAvailable:
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .foregroundStyle(Color.blue)
                .imageScale(.small)
        }
    }

    private var statusColor: Color {
        switch presentation.kind {
        case .ready:
            return .green
        case .needsRepair:
            return .orange
        case .updateAvailable:
            return .blue
        default:
            return .secondary
        }
    }

    @ViewBuilder
    private var downloadProgress: some View {
        if case .downloading(let progress) = status,
           let total = progress.totalBytes,
           total > 0 {
            ProgressView(value: Double(progress.downloadedBytes), total: Double(total))
                .progressViewStyle(.linear)
                .tint(AppTheme.statusProgressTint)
                .accessibilityIdentifier("settings_downloadProgress_\(model.id)")
        }
    }
}

// MARK: - Action button

/// Compact package control whose role flips with install state.
private struct ActionButton: View {
    let model: TTSModel
    var viewModel: ModelManagerViewModel
    let onDelete: () -> Void

    /// Holder for the NSView that backs the Manage button's
    /// background, used as the anchor for the AppKit `NSMenu`'s
    /// popUp positioning.
    @State private var manageHostHolder = NSViewHostHolder()

    private var status: ModelManagerViewModel.ModelStatus {
        viewModel.statuses[model.id] ?? .checking
    }

    var body: some View {
        switch status {
        case .checking:
            ProgressView()
                .controlSize(.small)
                .accessibilityIdentifier("settings_checking_\(model.id)")

        case .notDownloaded:
            HoverableActionButton(title: downloadButtonTitle) {
                Task { await viewModel.download(model) }
            }
            .help(downloadHelp)
            .accessibilityIdentifier("settings_download_\(model.id)")

        case .downloading:
            HoverableActionButton(title: "Cancel") {
                Task { await viewModel.cancelDownload(model) }
            }
            .help("Cancel the download (discards partial data)")
            .accessibilityIdentifier("settings_cancel_\(model.id)")

        case .repairAvailable:
            HoverableActionButton(title: "Repair", tint: .orange) {
                Task { await viewModel.download(model) }
            }
            .accessibilityIdentifier("settings_repair_\(model.id)")

        case .updateAvailable:
            HStack(spacing: 6) {
                HoverableActionButton(title: "Update", tint: .blue) {
                    Task { await viewModel.download(model) }
                }
                .help("Download the updated model package")
                .accessibilityIdentifier("settings_update_\(model.id)")
                Button {
                    presentManageMenu()
                } label: {
                    Text("Manage")
                }
                .background(NSViewHostAccessor(holder: manageHostHolder))
                .help("Manage \(model.variantKind?.displayName ?? model.name) variant")
                .controlSize(.small)
                .accessibilityIdentifier("settings_manage_\(model.id)")
            }

        case .downloaded:
            Button {
                presentManageMenu()
            } label: {
                Text("Manage")
                .frame(maxWidth: .infinity)
            }
            .background(NSViewHostAccessor(holder: manageHostHolder))
            .help("Manage \(model.variantKind?.displayName ?? model.name) variant")
            .controlSize(.small)
            .accessibilityIdentifier("settings_manage_\(model.id)")
        }
    }

    private var downloadButtonTitle: String {
        "Download"
    }

    private var downloadHelp: String {
        if let size = viewModel.sizeText(for: model) {
            return "Download \(size)"
        }
        return "Download"
    }

    /// Build a real AppKit NSMenu and pop it up from the Manage
    /// button's host NSView. The closure-based items use a small
    /// retained `ClosureMenuItem` wrapper so we don't need a
    /// separate `@objc` controller.
    private func presentManageMenu() {
        guard let host = manageHostHolder.view else { return }

        let menu = NSMenu()
        menu.addItem(ClosureMenuItem(
            title: "Reveal in Finder",
            systemImage: "folder",
            handler: {
                let url = model.installDirectory(in: QwenVoiceApp.modelsDir)
                // `activateFileViewerSelecting(_:)` highlights the
                // model folder inside its parent (the macOS native
                // "Reveal in Finder" idiom), as opposed to
                // `open(_:)` which would open the folder's contents.
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        ))
        menu.addItem(.separator())
        menu.addItem(ClosureMenuItem(
            title: "Delete Model",
            systemImage: "trash",
            isDestructive: true,
            handler: onDelete
        ))

        // Popping up at the bottom-leading corner of the host
        // makes the menu appear directly under the button.
        menu.popUp(
            positioning: nil,
            at: NSPoint(x: 0, y: host.bounds.height + 2),
            in: host
        )
    }
}

// MARK: - AppKit menu bridge

/// Holds a weak reference to the NSView that backs the SwiftUI
/// Manage button so we can position an AppKit `NSMenu` against
/// it. `@State`-friendly because it's a class — SwiftUI keeps the
/// same instance across renders.
private final class NSViewHostHolder {
    weak var view: NSView?
}

/// Captures the SwiftUI Button's host NSView via a transparent
/// background view. SwiftUI mounts the NSView in the same
/// position as the Button itself, so its `bounds` are usable as
/// the menu anchor.
private struct NSViewHostAccessor: NSViewRepresentable {
    let holder: NSViewHostHolder

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { [weak view] in
            holder.view = view
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        holder.view = nsView
    }
}

/// `NSMenuItem` subclass that retains a Swift closure and runs
/// it when the item is selected. Cleaner than a separate `@objc`
/// controller object — each item owns its own handler.
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

// MARK: - Hoverable bordered button

/// Bordered button with a subtle hover highlight. macOS bordered
/// buttons in SwiftUI don't have a built-in hover state — only
/// press feedback — so the rest action surface reads as static
/// between clicks. `brightness(0.07)` on hover lifts every visible
/// pixel of the button (bezel, text, tint) without any
/// shape-matching gymnastics. Returns to resting brightness with a
/// short ease-out when the cursor leaves.
private struct HoverableActionButton: View {
    let title: String
    var tint: Color? = nil
    let action: () -> Void

    @State private var isHovering = false

    var body: some View {
        Button {
            action()
        } label: {
            Text(title)
                .frame(maxWidth: .infinity)
        }
        .controlSize(.small)
        .tint(tint)
        .brightness(isHovering ? 0.12 : 0)
        .scaleEffect(isHovering ? 1.02 : 1.0)
        .onHover { hovering in
            AppLaunchConfiguration.performAnimated(.easeOut(duration: 0.14)) {
                isHovering = hovering
            }
        }
    }
}
