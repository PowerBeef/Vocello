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
/// rule is the lane contract. Compact rows keep primary controls inline and
/// place destructive actions in a menu.
struct MacVoicesScreen: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel

    let enrollRequestID: UUID?
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: (Voice) -> Void
    /// Reported after a voice is actually gone, so the shell can drop anything
    /// still pointing at it. The phone has always done this
    /// (`IOSVoicesView`); the desktop did not, which left a staged Clone
    /// handoff aimed at a `wavPath` that no longer exists.
    let onVoiceDeleted: (String) -> Void

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
    private var voices: [Voice] { savedVoicesViewModel.voices }
    private var isLoading: Bool { savedVoicesViewModel.isLoading }
    private var loadError: String? { savedVoicesViewModel.loadErrorMessage(MacInterfaceText.presentation) }

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
                savedVoicesViewModel.cancelBusyRetry()
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
                    // A plain heading row avoids macOS's section-header chrome.
                    VocelloSectionHeading(
                        MacInterfaceText.voicesYourVoices,
                        titleFontSize: MacType.style(.eyebrow).size,
                        topPadding: VocelloTheme.Spacing.xl,
                        titleLineLimit: 1,
                        expandsWidth: true,
                        horizontalInset: MacShellMetrics.libraryRowHorizontalInset
                    )
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                    ForEach(voices) { voice in
                        MacVoiceRow(
                            voice: voice,
                            caption: rowCaption(for: voice, bankCatalog: bankCatalog),
                            isHighlighted: highlightedVoiceID == voice.id,
                            canUseInVoiceCloning: canUseInVoiceCloning,
                            onUseInVoiceCloning: { onUseInVoiceCloning(voice) },
                            onPlay: { playVoicePreview(voice) },
                            onDelete: { requestDeleteVoice(voice) },
                            onReplaceReference: { requestReplaceReference(voice) }
                        )
                        .id(voice.id)
                        .listRowInsets(EdgeInsets(
                            top: VocelloTheme.Spacing.xs,
                            leading: MacShellMetrics.libraryRowHorizontalInset,
                            bottom: VocelloTheme.Spacing.xs,
                            trailing: MacShellMetrics.libraryRowHorizontalInset
                        ))
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .frame(maxWidth: MacShellMetrics.libraryContentMaxWidth)
                .frame(maxWidth: .infinity)
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
                .flatMap { MacInterfaceText.presetName(id: $0) }
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
                    // MAC-13: a deleted voice's reference leaves the player too,
                    // so it can no longer be played or revealed (⇧⌘R).
                    if audioPlayer.currentFilePath == voice.wavPath {
                        audioPlayer.dismiss()
                    }
                    savedVoicesViewModel.removeVoiceFromVisibleState(id: voice.id)
                    onVoiceDeleted(voice.id)
                }
            } catch {
                await MainActor.run {
                    presentActionAlert(
                        title: MacInterfaceText.voicesDeleteFailed,
                        message: MacInterfaceText.voicesDeleteFailedMessage(
                            MacInterfaceText.presentation.savedVoiceErrorMessage(error)
                        )
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
    let isHighlighted: Bool
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: () -> Void
    let onPlay: () -> Void
    let onDelete: () -> Void
    let onReplaceReference: () -> Void

    @State private var isHovered = false
    private static let avatarDiameter: CGFloat = 32

    private var transcriptStatus: String {
        voice.hasTranscript ? MacInterfaceText.voicesTranscriptBacked : MacInterfaceText.voicesAudioOnlyFallback
    }

    private var qualityHeadline: String? {
        voice.qualityWarnings.first.flatMap { MacInterfaceText.qualityWarningHeadline(token: $0) }
    }

    var body: some View {
        let shape = VocelloShape.input()

        HStack(spacing: VocelloTheme.Spacing.sm) {
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
        }
        .padding(.horizontal, VocelloTheme.Spacing.md)
        .padding(.vertical, VocelloTheme.Spacing.sm)
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

                if qualityHeadline != nil { warningChip }
            }

            HStack(spacing: VocelloTheme.Spacing.tight) {
                Text(transcriptStatus)
                    .layoutPriority(1)
                    .accessibilityIdentifier("voicesRow_\(voiceID)_transcriptStatus")
                Image(systemName: "circle.fill")
                    .font(.system(size: 2))
                    .accessibilityHidden(true)
                Text(caption)
            }
            .macType(.caption)
            .foregroundStyle(MacTheme.Text.secondary)
            .lineLimit(1)
            .help("\(transcriptStatus). \(caption)")

        }
    }

    /// Compact warning control; the full explanation lives in the
    /// popover behind it.
    private var warningChip: some View {
        let token = qualityWarnings.first ?? ""
        let label = MacInterfaceText.qualityWarningShortLabel(token: token)
            ?? MacInterfaceText.voicesReferenceOutsideRangeShort

        return Button {
            showsWarningDetails = true
        } label: {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: MacControl.badge.glyph, weight: .semibold))
                .foregroundStyle(MacTheme.Status.guarded)
                .frame(width: 24, height: 24)
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(MacInterfaceText.voicesQualityWarningAccessibility)
        .accessibilityHint(qualityHeadline ?? label)
        .help(qualityHeadline ?? label)
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

            Text(MacInterfaceText.qualityWarningSummary(tokens: qualityWarnings))
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
                    Text(MacInterfaceText.voicesUse)
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

            Menu {
                Button(MacInterfaceText.voicesDeleteAction, role: .destructive, action: onDelete)
                    .accessibilityIdentifier("voicesRow_delete_\(voiceID)")
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: MacControl.icon.glyph, weight: .semibold))
                    .frame(width: MacControl.icon.height, height: MacControl.icon.height)
                    .contentShape(Circle())
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
            .help(MacInterfaceText.voicesMoreActions)
            .accessibilityLabel(MacInterfaceText.voicesMoreActions)
            .accessibilityIdentifier("voicesRow_more_\(voiceID)")
        }
        .fixedSize(horizontal: true, vertical: false)
    }
}
