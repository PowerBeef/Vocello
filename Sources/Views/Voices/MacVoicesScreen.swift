import AppKit
import QwenVoiceCore
import SwiftUI

private struct MacVoicesAlertState: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

/// Saved Voices in the iOS card language (`IOSVoicesView`): avatar rows with
/// the name, the transcript status badge and a caption, the preview button
/// and the desktop actions (use in Voice Cloning, delete), the quality
/// warning chip with its Replace reference popover, and the enrollment and
/// record sheets. Every `voicesRow_*` identifier and its single-line layout
/// rule (the row lays out from the List width and the action cluster width,
/// never its own rendered width) is the lane contract.
struct MacVoicesScreen: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel

    let enrollRequestID: UUID?
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: (Voice) -> Void

    @State private var savedVoiceSheetConfiguration: SavedVoiceSheetConfiguration?
    @State private var actionAlert: MacVoicesAlertState?
    @State private var voiceToDelete: Voice?
    @State private var showDeleteConfirmation = false
    @State private var pendingRevealVoiceID: String?
    @State private var highlightedVoiceID: String?
    @State private var highlightResetTask: Task<Void, Never>?
    /// Set when the user starts a "Replace reference" flow from a flagged
    /// saved voice; the repository replaces the old assets in the same commit
    /// that publishes the new reference. Nil for normal add flows.
    @State private var voiceBeingReplaced: Voice?
    /// One width signal for every row: the List is clipped to its proposal, so
    /// an overflowing row can never inflate it.
    @State private var listWidth: CGFloat = 0

    private var voices: [Voice] { savedVoicesViewModel.voices }
    private var isLoading: Bool { savedVoicesViewModel.isLoading }
    private var loadError: String? { savedVoicesViewModel.loadError }

    private var loadTaskID: String {
        "\(ttsEngineStore.isReady)"
    }

    /// Bank membership by naming convention; every voice stays listed, the
    /// caption just tells which rows are one persona. Cached: the catalog is
    /// a pure function of the (id, name) list.
    private var bankCatalog: VoiceBankCatalog {
        MacVoiceBankCatalogCache.catalog(for: voices.map { (id: $0.id, name: $0.name) })
    }

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("screen_voices")
            .task(id: loadTaskID) {
                guard ttsEngineStore.isReady else { return }
                await savedVoicesViewModel.refresh(using: ttsEngineStore)
            }
            .onChange(of: enrollRequestID) { _, newValue in
                guard newValue != nil else { return }
                presentAddSavedVoiceSheet()
            }
            .onDisappear {
                highlightResetTask?.cancel()
                highlightResetTask = nil
            }
            .sheet(item: $savedVoiceSheetConfiguration) { configuration in
                MacSavedVoiceSheet(configuration: configuration) { voice in
                    handleSavedVoiceSheetCompletion(voice)
                }
                .environmentObject(ttsEngineStore)
            }
            .alert(MacInterfaceText.voicesDeleteTitle, isPresented: $showDeleteConfirmation) {
                Button(MacInterfaceText.cancel, role: .cancel) {
                    voiceToDelete = nil
                }
                Button(MacInterfaceText.delete, role: .destructive) {
                    confirmDeleteVoice()
                }
            } message: {
                if let voice = voiceToDelete {
                    Text(MacInterfaceText.voicesDeleteDetail(voice.name))
                }
            }
            .alert(item: $actionAlert) { alert in
                Alert(
                    title: Text(alert.title),
                    message: Text(alert.message),
                    dismissButton: .default(Text(MacInterfaceText.ok))
                )
            }
    }

    @ViewBuilder
    private var content: some View {
        if !ttsEngineStore.isReady {
            voicesStateContainer(identifier: "voices_emptyState") {
                VocelloEmptyStateCard(
                    title: MacInterfaceText.voicesEngineStarting,
                    message: MacInterfaceText.voicesWaitingForEngine,
                    symbolName: "arrow.triangle.2.circlepath.circle",
                    tint: MacTheme.voicesTint,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
            }
        } else if let loadError, voices.isEmpty, !isLoading {
            voicesStateContainer(identifier: "voices_errorState") {
                VocelloEmptyStateCard(
                    title: MacInterfaceText.voicesLoadFailedTitle,
                    message: loadError,
                    symbolName: "exclamationmark.triangle",
                    tint: MacTheme.Status.guarded,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
                Button(MacInterfaceText.tryAgain) {
                    retryLoadVoices()
                }
                .buttonStyle(.bordered)
                .tint(MacTheme.voicesTint)
                .accessibilityIdentifier("voices_retryButton")
            }
        } else if isLoading && voices.isEmpty {
            voicesStateContainer(identifier: "voices_loadingState") {
                ProgressView(MacInterfaceText.voicesLoading)
                    .tint(MacTheme.voicesTint)
            }
        } else if voices.isEmpty {
            voicesStateContainer(identifier: "voices_emptyState") {
                VocelloEmptyStateCard(
                    title: MacInterfaceText.voicesNoVoicesTitle,
                    message: MacInterfaceText.voicesEmpty,
                    symbolName: "person.2.fill",
                    tint: MacTheme.voicesTint,
                    maxWidth: MacShellMetrics.emptyStateCardMaxWidth,
                    symbolIsDecorative: true
                )
            }
        } else {
            let bankCatalog = self.bankCatalog
            ScrollViewReader { proxy in
                List {
                    Section {
                        ForEach(voices) { voice in
                            MacVoiceRow(
                                voice: voice,
                                caption: rowCaption(for: voice, bankCatalog: bankCatalog),
                                availableWidth: listWidth,
                                isHighlighted: highlightedVoiceID == voice.id,
                                canUseInVoiceCloning: canUseInVoiceCloning,
                                onUseInVoiceCloning: { onUseInVoiceCloning(voice) },
                                onPlay: { playVoicePreview(voice) },
                                onDelete: { requestDeleteVoice(voice) },
                                onReplaceReference: { requestReplaceReference(voice) }
                            )
                            .id(voice.id)
                            .listRowInsets(EdgeInsets(
                                top: 3,
                                leading: VocelloTheme.Spacing.lg,
                                bottom: 3,
                                trailing: VocelloTheme.Spacing.lg
                            ))
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                        }
                    } header: {
                        VocelloSectionHeading(
                            MacInterfaceText.voicesYourVoices,
                            titleFontSize: MacType.style(.eyebrow).size,
                            topPadding: VocelloTheme.Spacing.xl,
                            titleLineLimit: 1,
                            expandsWidth: true
                        )
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .frame(maxWidth: MacShellMetrics.libraryContentMaxWidth)
                .frame(maxWidth: .infinity)
                .onGeometryChange(for: CGFloat.self) { proxy in
                    proxy.size.width
                } action: { width in
                    listWidth = width
                }
                .onChange(of: voices) { _, newVoices in
                    guard let pendingRevealVoiceID else { return }
                    guard newVoices.contains(where: { $0.id == pendingRevealVoiceID }) else { return }
                    revealVoice(pendingRevealVoiceID, using: proxy)
                }
            }
        }
    }

    private func rowCaption(for voice: Voice, bankCatalog: VoiceBankCatalog) -> String {
        if let persona = bankCatalog.persona(containing: voice.id) {
            let delivery = persona.presetID(for: voice.id)
                .flatMap { EmotionPreset.preset(id: $0)?.label }
                ?? MacInterfaceText.deliveryNeutral
            return MacInterfaceText.voicesVoiceBank(delivery)
        }
        return voice.hasTranscript
            ? MacInterfaceText.voicesDetailTranscript
            : MacInterfaceText.voicesDetailAudioOnly
    }
}

@MainActor
private extension MacVoicesScreen {
    @ViewBuilder
    func voicesStateContainer<Content: View>(
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.md) {
            content()
        }
        .padding(VocelloTheme.Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    func presentAddSavedVoiceSheet() {
        voiceBeingReplaced = nil
        savedVoiceSheetConfiguration = .manualAdd
    }

    /// Opens the enrollment sheet pre-filled for replacing the given voice's
    /// reference clip. The transcript loads best-effort from the sidecar; a
    /// missing one just means the user retypes it.
    func requestReplaceReference(_ voice: Voice) {
        let transcript = (try? voice.loadTranscript()).flatMap { $0 } ?? ""
        voiceBeingReplaced = voice
        savedVoiceSheetConfiguration = .replaceReference(
            name: voice.name,
            transcript: transcript,
            referenceLanguage: voice.enrollmentMetadata?.referenceLanguage ?? .auto
        )
    }

    func handleSavedVoiceSheetCompletion(_ voice: Voice) {
        let replacedVoice = voiceBeingReplaced
        voiceBeingReplaced = nil

        pendingRevealVoiceID = voice.id
        savedVoicesViewModel.insertOrReplace(voice)

        // Replacement is one repository transaction. If the normalized ID
        // changed, remove only the old row from the visible cache; its files
        // were already tombstoned before the new voice was published.
        if let replacedVoice, replacedVoice.id != voice.id {
            savedVoicesViewModel.removeVoiceFromVisibleState(id: replacedVoice.id)
        }
        Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) }
    }

    func retryLoadVoices() {
        Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) }
    }

    func playVoicePreview(_ voice: Voice) {
        audioPlayer.playFile(voice.wavPath, title: voice.name)
    }

    func requestDeleteVoice(_ voice: Voice) {
        voiceToDelete = voice
        showDeleteConfirmation = true
    }

    func confirmDeleteVoice() {
        if let voice = voiceToDelete {
            deleteVoice(voice)
        }
        voiceToDelete = nil
    }

    func revealVoice(_ voiceID: String, using proxy: ScrollViewProxy) {
        pendingRevealVoiceID = nil
        highlightedVoiceID = voiceID

        AppLaunchConfiguration.performAnimated(MacTheme.Motion.easeOut) {
            proxy.scrollTo(voiceID, anchor: .center)
        }

        highlightResetTask?.cancel()
        highlightResetTask = Task {
            try? await Task.sleep(nanoseconds: 1_800_000_000)
            await MainActor.run {
                if highlightedVoiceID == voiceID {
                    highlightedVoiceID = nil
                }
            }
        }
    }

    func deleteVoice(_ voice: Voice) {
        if audioPlayer.currentFilePath == voice.wavPath {
            audioPlayer.stop()
        }
        Task {
            do {
                try await ttsEngineStore.deletePreparedVoice(id: voice.id)
                await MainActor.run {
                    savedVoicesViewModel.removeVoiceFromVisibleState(id: voice.id)
                }
            } catch {
                await MainActor.run {
                    presentActionAlert(
                        title: MacInterfaceText.voicesDeleteFailed,
                        message: MacInterfaceText.voicesDeleteFailedMessage(error.localizedDescription)
                    )
                }
            }
            await savedVoicesViewModel.refresh(using: ttsEngineStore)
        }
    }

    func presentActionAlert(title: String, message: String) {
        actionAlert = MacVoicesAlertState(title: title, message: message)
    }
}

/// Single-entry memo for `VoiceBankCatalog.build`: the catalog is a pure
/// function of the saved-voice (id, name) list and rows share one build.
@MainActor
enum MacVoiceBankCatalogCache {
    private static var cachedKey: [String] = []
    private static var cached: VoiceBankCatalog?

    static func catalog(for voices: [(id: String, name: String)]) -> VoiceBankCatalog {
        let key = voices.flatMap { [$0.id, $0.name] }
        if let cached, key == cachedKey {
            return cached
        }
        let built = VoiceBankCatalog.build(voices: voices)
        cachedKey = key
        cached = built
        return built
    }
}

// MARK: - Row

private struct MacVoiceRow: View {
    let voice: Voice
    let caption: String
    /// The List's width (container-owned, never the row's own rendered size).
    let availableWidth: CGFloat
    let isHighlighted: Bool
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: () -> Void
    let onPlay: () -> Void
    let onDelete: () -> Void
    let onReplaceReference: () -> Void

    /// One width signal plus `AnyLayout`: the two inputs are stable by
    /// construction (the List's width comes from the container, the action
    /// cluster is horizontally fixed-size), so an overflowing title can never
    /// feed back into the layout choice (pseudo-localized readiness journey,
    /// 2026-09-13).
    @State private var actionsWidth: CGFloat = 0
    @State private var isHovered = false

    /// A portrait, not a control: it keeps its own diameter while the row's
    /// controls snap to the six steps.
    private static let avatarDiameter: CGFloat = 44

    /// Name plus status badge at body/caption sizes.
    private static let minimumMetadataWidth: CGFloat = 220
    /// Avatar, its gap, the layout gap, card padding and List insets.
    private static let rowChrome: CGFloat = avatarDiameter
        + VocelloTheme.Spacing.md
        + VocelloTheme.Spacing.lg
        + VocelloTheme.Spacing.md * 2
        + VocelloTheme.Spacing.lg * 2

    private var usesWideLayout: Bool {
        guard availableWidth > 0, actionsWidth > 0 else { return true }
        return availableWidth - Self.rowChrome - actionsWidth >= Self.minimumMetadataWidth
    }

    private var transcriptStatus: String {
        voice.hasTranscript ? MacInterfaceText.voicesTranscriptBacked : MacInterfaceText.voicesAudioOnlyFallback
    }

    private var qualityHeadline: String? {
        voice.qualityWarnings.first.flatMap(PreparedVoiceQualityWarning.headline(for:))
    }

    var body: some View {
        let shape = VocelloShape.card()
        let layout = usesWideLayout
            ? AnyLayout(HStackLayout(alignment: .center, spacing: VocelloTheme.Spacing.lg))
            : AnyLayout(VStackLayout(alignment: .leading, spacing: VocelloTheme.Spacing.md))

        layout {
            HStack(alignment: .center, spacing: VocelloTheme.Spacing.md) {
                VocelloVoiceAvatar(
                    seed: voice.id,
                    initials: voice.name,
                    diameter: Self.avatarDiameter,
                    isDecorative: true
                )

                MacVoiceRowMetadata(
                    voiceName: voice.name,
                    voiceID: voice.id,
                    transcriptStatus: transcriptStatus,
                    caption: caption,
                    qualityHeadline: qualityHeadline,
                    qualityWarnings: voice.qualityWarnings,
                    onReplaceReference: onReplaceReference
                )
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            MacVoiceRowActions(
                voiceID: voice.id,
                canUseInVoiceCloning: canUseInVoiceCloning,
                onPlay: onPlay,
                onUseInVoiceCloning: onUseInVoiceCloning,
                onDelete: onDelete
            )
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { width in
                actionsWidth = width
            }
        }
        .padding(.horizontal, VocelloTheme.Spacing.md)
        .padding(.vertical, VocelloTheme.Spacing.snug)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            shape.fill(Color.white.opacity(isHovered ? 0.06 : 0.04))
        }
        .overlay {
            shape.stroke(
                isHighlighted ? MacTheme.voicesTint.opacity(0.55) : Color.white.opacity(0.08),
                lineWidth: isHighlighted ? VocelloTheme.Stroke.standard : VocelloTheme.Stroke.hairline
            )
        }
        .macGatedGlass(
            tint: MacTheme.glassTint(isHighlighted ? MacTheme.voicesTint : nil, intensity: isHighlighted ? 1.4 : 0.6),
            in: shape
        )
        .onHover { hovering in
            isHovered = hovering
        }
        .appAnimation(MacTheme.Motion.stateChange, value: isHovered)
        .appAnimation(MacTheme.Motion.easeOut, value: isHighlighted)
    }
}

private struct MacVoiceRowMetadata: View {
    let voiceName: String
    let voiceID: String
    let transcriptStatus: String
    let caption: String
    let qualityHeadline: String?
    let qualityWarnings: [String]
    let onReplaceReference: () -> Void

    @State private var showsWarningDetails = false

    var body: some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.tight) {
            HStack(alignment: .firstTextBaseline, spacing: VocelloTheme.Spacing.sm) {
                // Display-only humanization: sanitized voice names carry
                // underscores (stable IDs, CLI and test identifiers keep the
                // raw form).
                Text(voiceName.replacingOccurrences(of: "_", with: " "))
                    .macType(.rowTitle)
                    .foregroundStyle(MacTheme.Text.primary)
                    .lineLimit(1)
                    .accessibilityIdentifier("voicesRow_\(voiceID)")

                VocelloStatusBadge(
                    text: transcriptStatus,
                    tone: .muted,
                    horizontalPadding: MacControl.badge.horizontalPadding,
                    verticalPadding: VocelloTheme.Spacing.xs,
                    lineLimit: 1
                )
                    .fixedSize(horizontal: true, vertical: false)
                    .accessibilityIdentifier("voicesRow_\(voiceID)_transcriptStatus")
            }

            if qualityHeadline != nil {
                warningChip
            } else {
                Text(caption)
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)
            }
        }
    }

    /// Compact tappable status pill; the full explanation lives in the
    /// popover behind it.
    private var warningChip: some View {
        let token = qualityWarnings.first ?? ""
        let label = MacInterfaceText.qualityWarningShortLabel(token: token)
            ?? MacInterfaceText.voicesReferenceOutsideRangeShort

        return Button {
            showsWarningDetails = true
        } label: {
            HStack(spacing: VocelloTheme.Spacing.tight) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: MacControl.badge.glyph, weight: .semibold))
                Text(label)
                    .macType(.badge)
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: MacControl.badge.glyph, weight: .semibold))
                    .opacity(0.7)
            }
            .fixedSize(horizontal: true, vertical: false)
            .foregroundStyle(MacTheme.Status.guarded)
            .padding(.horizontal, VocelloTheme.Spacing.snug)
            .padding(.vertical, VocelloTheme.Spacing.xs)
            .background(VocelloShape.pill().fill(MacTheme.Status.guarded.opacity(0.12)))
            .overlay(VocelloShape.pill().stroke(MacTheme.Status.guarded.opacity(0.30), lineWidth: VocelloTheme.Stroke.hairline))
            .contentShape(VocelloShape.pill())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(MacInterfaceText.voicesQualityWarningAccessibility)
        .accessibilityHint(qualityHeadline ?? label)
        .accessibilityIdentifier("voicesRow_\(voiceID)_qualityWarning")
        .popover(isPresented: $showsWarningDetails, arrowEdge: .top) {
            warningDetailsPopover
        }
    }

    private var warningDetailsPopover: some View {
        VStack(alignment: .leading, spacing: VocelloTheme.Spacing.md) {
            Label(MacInterfaceText.voicesReferenceOutsideRange, systemImage: "exclamationmark.triangle.fill")
                .macType(.screenTitle)
                .foregroundStyle(MacTheme.Status.guarded)

            Text(PreparedVoiceQualityWarning.summary(for: qualityWarnings))
                .macType(.body)
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                Button(MacInterfaceText.voicesReplaceReference) {
                    showsWarningDetails = false
                    onReplaceReference()
                }
                .buttonStyle(.borderedProminent)
                .tint(MacTheme.Brand.modeClone)
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier("voicesRow_\(voiceID)_replaceReference")

                Spacer(minLength: VocelloTheme.Spacing.sm)

                Button(MacInterfaceText.close) {
                    showsWarningDetails = false
                }
                .keyboardShortcut(.cancelAction)
            }
        }
        .padding(VocelloTheme.Spacing.lg)
        .frame(width: 360)
    }
}

private struct MacVoiceRowActions: View {
    let voiceID: String
    let canUseInVoiceCloning: Bool
    let onPlay: () -> Void
    let onUseInVoiceCloning: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: VocelloTheme.Spacing.sm) {
            MacIconButton(
                symbol: "play.fill",
                label: MacInterfaceText.voicesPreview,
                accessibilityIdentifier: "voicesRow_play_\(voiceID)",
                action: onPlay
            )

            Button(action: onUseInVoiceCloning) {
                HStack(spacing: VocelloTheme.Spacing.tight) {
                    Image(systemName: MacTheme.modeGlyph(for: .clone))
                        .font(.system(size: MacControl.icon.glyph, weight: .semibold))
                    Text(MacInterfaceText.voicesOpenInCloning)
                        .macType(.buttonLabel)
                        .lineLimit(1)
                }
                .foregroundStyle(MacTheme.Brand.modeClone)
                .padding(.horizontal, VocelloTheme.Spacing.md)
                .macControlHeight(.icon)
                .background { VocelloShape.pill().fill(MacTheme.Brand.modeClone.opacity(0.14)) }
                .overlay { VocelloShape.pill().stroke(MacTheme.Brand.modeClone.opacity(0.32), lineWidth: VocelloTheme.Stroke.hairline) }
                .contentShape(VocelloShape.pill())
            }
            .buttonStyle(.plain)
            .fixedSize(horizontal: true, vertical: false)
            .help(canUseInVoiceCloning ? MacInterfaceText.voicesUseHelp : MacInterfaceText.voicesUseHelpInstall)
            .accessibilityIdentifier("voicesRow_use_\(voiceID)")

            MacIconButton(
                symbol: "trash",
                label: MacInterfaceText.voicesDeleteAction,
                accessibilityIdentifier: "voicesRow_delete_\(voiceID)",
                action: onDelete
            )
        }
        .fixedSize(horizontal: true, vertical: false)
    }
}
