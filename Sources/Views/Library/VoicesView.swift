import AppKit
import QwenVoiceNative
import SwiftUI
import UniformTypeIdentifiers

private struct VoicesAlertState: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

struct VoicesView: View {
    @EnvironmentObject private var ttsEngineStore: TTSEngineStore
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @Environment(SavedVoicesViewModel.self) private var savedVoicesViewModel

    let enrollRequestID: UUID?
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: (Voice) -> Void

    @State private var savedVoiceSheetConfiguration: SavedVoiceSheetConfiguration?
    @State private var actionAlert: VoicesAlertState?
    @State private var voiceToDelete: Voice?
    @State private var showDeleteConfirmation = false
    @State private var pendingRevealVoiceID: String?
    @State private var highlightedVoiceID: String?
    @State private var highlightResetTask: Task<Void, Never>?
    /// Set when the user starts a "Replace reference" flow from a
    /// flagged saved voice. The repository replaces the old assets in the
    /// same commit that publishes the new reference (see
    /// `handleSavedVoiceSheetCompletion`). Nil for normal add flows.
    @State private var voiceBeingReplaced: Voice?
    /// One width signal for every row: the List is clipped to its proposal, so
    /// an overflowing row can never inflate it (W1-F kept one signal, but a
    /// row's own rendered width fed back into its layout choice).
    @State private var listWidth: CGFloat = 0

    private var voices: [Voice] {
        savedVoicesViewModel.voices
    }

    private var isLoading: Bool {
        savedVoicesViewModel.isLoading
    }

    private var loadError: String? {
        savedVoicesViewModel.loadError
    }

    private var loadTaskID: String {
        "\(ttsEngineStore.isReady)"
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
                SavedVoiceSheet(configuration: configuration) { voice in
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
            voicesStateContainer(
                identifier: "voices_emptyState"
            ) {
                ContentUnavailableView(
                    "Starting speech engine...",
                    systemImage: "arrow.triangle.2.circlepath.circle",
                    description: Text(MacInterfaceText.voicesWaitingForEngine)
                )
            }
        } else if let loadError, voices.isEmpty, !isLoading {
            voicesStateContainer(identifier: "voices_errorState") {
                VStack(alignment: .leading, spacing: 12) {
                    ContentUnavailableView(
                        "Couldn't load saved voices",
                        systemImage: "exclamationmark.triangle",
                        description: Text(loadError)
                    )

                    Button(MacInterfaceText.tryAgain) {
                        retryLoadVoices()
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("voices_retryButton")
                }
            }
        } else if isLoading && voices.isEmpty {
            voicesStateContainer(identifier: "voices_loadingState") {
                VStack(spacing: 12) {
                    ProgressView()
                    Text(MacInterfaceText.voicesLoading)
                        .font(.body)
                        .foregroundStyle(.secondary)
                }
            }
        } else if voices.isEmpty {
            voicesStateContainer(identifier: "voices_emptyState") {
                ContentUnavailableView(
                    "No saved voices",
                    systemImage: "person.2.wave.2",
                    description: Text(MacInterfaceText.voicesEmpty)
                )
            }
        } else {
            ScrollViewReader { proxy in
                List {
                    ForEach(voices) { voice in
                        VoiceRow(
                            voice: voice,
                            availableWidth: listWidth,
                            isHighlighted: highlightedVoiceID == voice.id,
                            canUseInVoiceCloning: canUseInVoiceCloning,
                            onUseInVoiceCloning: {
                                onUseInVoiceCloning(voice)
                            },
                            onPlay: {
                                playVoicePreview(voice)
                            },
                            onDelete: {
                                requestDeleteVoice(voice)
                            },
                            onReplaceReference: {
                                requestReplaceReference(voice)
                            }
                        )
                        .id(voice.id)
                    }
                }
                .listStyle(.inset)
                .scrollContentBackground(.hidden)
                .frame(maxWidth: LayoutConstants.contentMaxWidth)
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
}

@MainActor
private extension VoicesView {
    @ViewBuilder
    func voicesStateContainer<Content: View>(
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack {
            content()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(identifier)
    }

    func presentAddSavedVoiceSheet() {
        voiceBeingReplaced = nil
        savedVoiceSheetConfiguration = .manualAdd
    }

    /// Opens the SavedVoiceSheet pre-filled for replacing the given
    /// voice's reference clip. The transcript is loaded best-effort
    /// from the sidecar `.txt` file; a missing/unreadable transcript
    /// just means the user has to retype it.
    func requestReplaceReference(_ voice: Voice) {
        // `Voice.loadTranscript()` is `() throws -> String?`; `try?`
        // collapses any throw into `nil`, then `flatMap` drops the
        // missing-file `nil` case so we end up with `String?`.
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
            Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) }
        } else {
            Task { await savedVoicesViewModel.refresh(using: ttsEngineStore) }
        }
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

        AppLaunchConfiguration.performAnimated(.easeInOut(duration: 0.2)) {
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
        actionAlert = VoicesAlertState(title: title, message: message)
    }
}

private struct VoiceRow: View {
    let voice: Voice
    /// The List's width (container-owned, never the row's own rendered size).
    let availableWidth: CGFloat
    let isHighlighted: Bool
    let canUseInVoiceCloning: Bool
    let onUseInVoiceCloning: () -> Void
    let onPlay: () -> Void
    let onDelete: () -> Void
    let onReplaceReference: () -> Void

    private var highlightFill: Color {
        isHighlighted ? AppTheme.accent.opacity(0.12) : .clear
    }

    private var highlightStroke: Color {
        isHighlighted ? AppTheme.accent.opacity(0.22) : .clear
    }

    private var transcriptStatus: String {
        voice.hasTranscript ? MacInterfaceText.voicesTranscriptBacked : MacInterfaceText.voicesAudioOnlyFallback
    }

    private var detailCopy: String {
        voice.hasTranscript
            ? MacInterfaceText.voicesDetailTranscript
            : MacInterfaceText.voicesDetailAudioOnly
    }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "person.2.wave.2")
                .font(.title3.weight(.semibold))
                .foregroundStyle(AppTheme.accent)
                .frame(width: 24, alignment: .center)
                .padding(.top, 4)

            rowContent
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 6)
        .background {
            GatedGlass {
                if isHighlighted {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(.clear)
                        .glassEffect(.regular.tint(AppTheme.accent), in: .rect(cornerRadius: 12))
                } else {
                    highlightBackground
                }
            } fallback: {
                highlightBackground
            }
        }
    }

    private var highlightBackground: some View {
        RoundedRectangle(cornerRadius: 12, style: .continuous)
            .fill(highlightFill)
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(highlightStroke, lineWidth: isHighlighted ? 1 : 0)
            )
    }

    /// W1-F: one width signal + `AnyLayout` replaces the `ViewThatFits`
    /// that built and measured BOTH full row layouts for every visible row
    /// on every layout pass. Child identity is preserved across the flip.
    ///
    /// The two inputs are stable by construction: the List's width comes from
    /// the container, and the action cluster is horizontally fixed-size, so its
    /// width does not depend on which layout wraps it. Measuring the row's own
    /// rendered width (the previous rule, wide when >= 430) fed back into the
    /// choice: once the action cluster overflowed under long titles, the wide
    /// HStack reported an inflated width and the row locked into a near-zero
    /// metadata column (pseudo-localized readiness journey, 2026-09-13).
    /// Width 0 (pre-first-layout) renders wide, matching the default window.
    @State private var actionsWidth: CGFloat = 0

    /// Name plus status chip at body/caption sizes.
    private static let minimumMetadataWidth: CGFloat = 220
    /// Leading icon, its gap, the layout gap, horizontal padding and List insets.
    private static let rowChrome: CGFloat = 24 + 14 + 14 + 12 + 40

    private var usesWideLayout: Bool {
        guard availableWidth > 0, actionsWidth > 0 else { return true }
        return availableWidth - Self.rowChrome - actionsWidth >= Self.minimumMetadataWidth
    }

    private var rowContent: some View {
        let layout = usesWideLayout
            ? AnyLayout(HStackLayout(alignment: .center, spacing: 14))
            : AnyLayout(VStackLayout(alignment: .leading, spacing: 12))
        return layout {
            VoiceRowMetadata(
                voiceName: voice.name,
                voiceID: voice.id,
                transcriptStatus: transcriptStatus,
                detailCopy: detailCopy,
                qualityHeadline: voice.qualityHeadline,
                qualityWarnings: voice.qualityWarnings,
                onReplaceReference: onReplaceReference
            )
            .frame(maxWidth: .infinity, alignment: .leading)

            VoiceRowActions(
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
    }
}

private struct VoiceRowMetadata: View {
    let voiceName: String
    let voiceID: String
    let transcriptStatus: String
    let detailCopy: String
    let qualityHeadline: String?
    let qualityWarnings: [String]
    let onReplaceReference: () -> Void

    @State private var showsWarningDetails = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                // Display-only humanization: sanitized voice names carry
                // underscores (stable IDs, CLI, and test identifiers keep
                // the raw form).
                Text(voiceName.replacingOccurrences(of: "_", with: " "))
                    .font(.body.weight(.semibold))
                    .lineLimit(1)
                    .accessibilityIdentifier("voicesRow_\(voiceID)")

                Text(transcriptStatus)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .fixedSize(horizontal: true, vertical: false)
                    .accessibilityIdentifier("voicesRow_\(voiceID)_transcriptStatus")
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    #if QW_UI_LIQUID
                    .glassBadge()
                    #else
                    .background(
                        Capsule(style: .continuous)
                            .fill(Color.secondary.opacity(0.12))
                    )
                    #endif

                // Title-row triangle removed: the warning chip below
                // carries the warning visual; doubling it on the title
                // row was the redundancy that made the row look busy.
            }

            if qualityHeadline != nil {
                warningChip
            } else {
                Text(detailCopy)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
    }

    /// Compact tappable status pill that replaces the wrapping orange
    /// sentence + inline "Why?" link. Single visual element, single
    /// tap target — the full explanation lives in the popover behind
    /// it (unchanged).
    private var warningChip: some View {
        let token = qualityWarnings.first ?? ""
        let label = MacInterfaceText.qualityWarningShortLabel(token: token)
            ?? MacInterfaceText.voicesReferenceOutsideRangeShort

        return Button {
            showsWarningDetails = true
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption)
                Text(label)
                    .font(.caption.weight(.medium))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .opacity(0.7)
            }
            .fixedSize(horizontal: true, vertical: false)
            .foregroundStyle(.orange)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                Capsule(style: .continuous)
                    .fill(Color.orange.opacity(0.12))
            )
            .overlay(
                Capsule(style: .continuous)
                    .stroke(Color.orange.opacity(0.24), lineWidth: 1.0)
            )
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
        VStack(alignment: .leading, spacing: 12) {
            Label(MacInterfaceText.voicesReferenceOutsideRange, systemImage: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundStyle(.orange)

            Text(PreparedVoiceQualityWarning.summary(for: qualityWarnings))
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                Button(MacInterfaceText.voicesReplaceReference) {
                    showsWarningDetails = false
                    onReplaceReference()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .accessibilityIdentifier("voicesRow_\(voiceID)_replaceReference")

                Spacer(minLength: 8)

                Button(MacInterfaceText.close) {
                    showsWarningDetails = false
                }
                .keyboardShortcut(.cancelAction)
            }
        }
        .padding(16)
        .frame(width: 360)
    }
}

private struct VoiceRowActions: View {
    let voiceID: String
    let canUseInVoiceCloning: Bool
    let onPlay: () -> Void
    let onUseInVoiceCloning: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button(MacInterfaceText.voicesOpenInCloning, action: onUseInVoiceCloning)
                .buttonStyle(.bordered)
                .controlSize(.small)
                .fixedSize(horizontal: true, vertical: false)
                .help(
                    canUseInVoiceCloning
                        ? "Open Voice Cloning with this saved voice selected."
                        : "Open Voice Cloning with this saved voice selected. Install the Voice Cloning model in Models to generate from it."
                )
                .accessibilityIdentifier("voicesRow_use_\(voiceID)")

            Button(MacInterfaceText.voicesPreview, action: onPlay)
                .buttonStyle(.bordered)
                .controlSize(.small)
                .fixedSize(horizontal: true, vertical: false)
                .accessibilityIdentifier("voicesRow_play_\(voiceID)")

            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .accessibilityIdentifier("voicesRow_delete_\(voiceID)")
        }
        .fixedSize(horizontal: true, vertical: false)
    }
}
