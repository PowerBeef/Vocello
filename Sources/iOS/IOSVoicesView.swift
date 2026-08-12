import SwiftUI
import UniformTypeIdentifiers
import QwenVoiceCore

/// Unified Voices tab from design_references/Vocello iOS/screens.jsx
/// (Voices section). Combines built-in speakers from the TTSContract with
/// saved (cloned) voices from SavedVoicesViewModel under one search +
/// filter chrome. Tapping a built-in speaker routes to Studio Custom mode
/// preselected; tapping a saved voice routes to Studio Clone mode with
/// the existing PendingVoiceCloningHandoff plumbing.
///
/// Wired in QVoiceiOSRootView's `.voices` case. Rows include the reference
/// play affordance: bundled previews and saved-voice playback present
/// the full player sheet so no persistent rail appears in app chrome.
struct IOSVoicesView: View {
    @Binding var selectedTab: IOSAppTab
    let onSelectBuiltInSpeaker: (SpeakerDescriptor) -> Void
    let onSelectSavedVoice: (Voice) -> Void
    /// Surface the record → name → enroll flow (the call-site presents it + handles the handoff).
    let onRecordNewVoice: () -> Void

    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var savedVoicesViewModel: SavedVoicesViewModel
    @Environment(\.presentIOSPlayerSheet) private var presentPlayerSheet

    @State private var search: String = ""
    @State private var filter: VoiceFilter = .all

    // The built-in speaker list is a static constant — sort it once, not on
    // every body evaluation (iOS readiness audit, fix #25).
    private static let builtInSorted: [SpeakerDescriptor] = TTSContract.allSpeakerDescriptors
        .sorted { lhs, rhs in
            lhs.displayName.localizedCaseInsensitiveCompare(rhs.displayName) == .orderedAscending
        }

    private var builtIn: [SpeakerDescriptor] { Self.builtInSorted }

    private var saved: [Voice] {
        savedVoicesViewModel.voices.sorted { lhs, rhs in
            lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
        }
    }

    /// Bank membership by naming convention; every voice stays listed (each
    /// member has its own preview-worthy reference clip) — the caption just
    /// tells the truth about which rows are one persona.
    private var bankCatalog: VoiceBankCatalog {
        VoiceBankCatalog.build(voices: saved.map { (id: $0.id, name: $0.name) })
    }

    private func savedRowCaption(_ voice: Voice) -> String {
        guard let persona = bankCatalog.persona(containing: voice.id) else {
            return "Cloned reference"
        }
        let delivery = persona.presetID(for: voice.id)
            .flatMap { EmotionPreset.preset(id: $0)?.label } ?? "Neutral"
        return "Voice bank · \(delivery)"
    }

    private var filteredBuiltIn: [SpeakerDescriptor] {
        guard filter != .saved else { return [] }
        return builtIn.filter(matchesSearch)
    }

    private var filteredSaved: [Voice] {
        guard filter != .builtIn else { return [] }
        return saved.filter(matchesSearch)
    }

    var body: some View {
        IOSStudioShellScreen(
            selectedTab: $selectedTab,
            activeTab: .voices,
            tint: IOSAppTab.voices.dockAccent(studioMode: .custom)
        ) {
            IOSScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    IOSSearchField(text: $search, placeholder: "Search voices")
                        .accessibilityIdentifier("voicesSearchField")
                        .padding(.horizontal, 20)
                        .padding(.bottom, 10)

                    IOSFilterChipRow(
                        options: VoiceFilter.allCases,
                        selection: $filter,
                        tint: IOSBrandTheme.library,
                        label: \.label,
                        accessibilityIdentifier: { "voicesFilter_\($0.rawValue)" }
                    )

                    if filter != .builtIn {
                        voicesSectionHeading("Your saved voices")

                        VStack(spacing: 0) {
                            LazyVStack(spacing: 0) {
                            ForEach(filteredSaved, id: \.id) { voice in
                                savedRow(voice)
                            }
                            }
                            saveACallCard
                        }
                    }

                    if filter != .saved {
                        voicesSectionHeading("Built-in speakers")

                        LazyVStack(spacing: 0) {
                            ForEach(filteredBuiltIn, id: \.id) { speaker in
                                builtInRow(speaker)
                            }
                        }
                    }

                    if filteredBuiltIn.isEmpty && filteredSaved.isEmpty {
                        IOSEmptyStateCard(
                            title: "Nothing matches",
                            message: "Try a different search term or switch the filter back to All.",
                            symbolName: "magnifyingglass",
                            tint: IOSBrandTheme.library
                        )
                        .padding(.horizontal, 20)
                        .padding(.top, 12)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .padding(.bottom, 12)
            }
            // Engine initialization finishes asynchronously after the screen can
            // first appear. Key the task to readiness so an early no-op is retried
            // instead of leaving Saved Voices empty for the rest of the session.
            .task(id: ttsEngine.isReady) {
                await savedVoicesViewModel.ensureLoaded(using: ttsEngine)
            }
        }
        .accessibilityIdentifier("screen_voices")
    }

    private func voicesSectionHeading(_ title: String) -> some View {
        Text(title.uppercased())
            .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
            .tracking(0.88)
            .foregroundStyle(IOSAppTheme.textSecondary)
            .padding(.horizontal, 20)
            .padding(.top, 14)
            .padding(.bottom, 6)
    }

    // MARK: - Save-a-voice CTA

    private var saveACallCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Save a new voice")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(IOSAppTheme.textPrimary)
                .padding(.horizontal, 14)
                .padding(.top, 14)
                .padding(.bottom, 8)

            newVoiceActionRow(
                title: "Record voice",
                detail: "Capture a 10-20 second reference clip on this iPhone.",
                symbol: "mic.fill",
                accessibilityIdentifier: "voices_saveNewVoice"
            ) {
                IOSHaptics.selection()
                onRecordNewVoice()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.white.opacity(0.12), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                .background {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(Color.white.opacity(0.02))
                }
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
    }

    private func newVoiceActionRow(
        title: String,
        detail: String,
        symbol: String,
        accessibilityIdentifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(IOSBrandTheme.clone.opacity(0.16))
                    Image(systemName: symbol)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(IOSBrandTheme.clone)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(IOSAppTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 6)

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(IOSAppTheme.textTertiary)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier)
        .accessibilityLabel(title)
        .accessibilityHint(detail)
    }

    // MARK: - Rows

    private func builtInRow(_ speaker: SpeakerDescriptor) -> some View {
        HStack(spacing: 12) {
            Button {
                IOSHaptics.selection()
                onSelectBuiltInSpeaker(speaker)
            } label: {
                HStack(spacing: 12) {
                    IOSVoiceAvatar(
                        seed: speaker.id,
                        initials: speaker.displayName,
                        diameter: 44
                    )

                    VStack(alignment: .leading, spacing: 1) {
                        Text(speaker.displayName)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(IOSAppTheme.textPrimary)
                        if let detail = builtInSubtitle(for: speaker) {
                            Text(detail)
                                .font(.caption)
                                .foregroundStyle(IOSAppTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .buttonStyle(.plain)

            Spacer(minLength: 8)

            if let tag = IOSVoicePickerLanguage.tag(for: speaker.nativeLanguage) {
                Text(tag)
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.4)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .padding(.horizontal, 8)
                    .frame(height: 20)
                    .background {
                        Capsule(style: .continuous)
                            .fill(Color.white.opacity(0.08))
                    }
            }

            voicePreviewButton(
                isPlaying: false,
                action: {
                    guard let item = IOSPlayerSheetItem.fromBuiltInPreview(speaker: speaker) else {
                        return
                    }
                    presentPreview(item)
                }
            )
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 6)
        .accessibilityIdentifier("voicesRow_\(speaker.id)")
    }

    private func savedRow(_ voice: Voice) -> some View {
        HStack(spacing: 12) {
            Button {
                IOSHaptics.selection()
                onSelectSavedVoice(voice)
            } label: {
                HStack(spacing: 12) {
                    IOSVoiceAvatar(
                        seed: voice.id,
                        initials: voice.name,
                        diameter: 44
                    )

                    VStack(alignment: .leading, spacing: 1) {
                        Text(voice.name)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(IOSAppTheme.textPrimary)
                        Text(savedRowCaption(voice))
                            .font(.caption)
                            .foregroundStyle(IOSAppTheme.textSecondary)
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("voicesRow_saved_\(voice.id)")

            Spacer(minLength: 8)

            voicePreviewButton(
                isPlaying: false,
                action: {
                    guard let item = IOSPlayerSheetItem.from(savedVoice: voice) else {
                        return
                    }
                    presentPreview(item)
                }
            )
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 6)
    }

    private func voicePreviewButton(isPlaying: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            IOSPlayerIconButtonChrome(
                symbol: isPlaying ? "pause.fill" : "play.fill",
                isActive: isPlaying,
                size: 40,
                symbolSize: 16
            )
            // 44 pt HIG hit target around the 40 pt visual (IUI-4 X8).
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isPlaying ? "Stop preview" : "Preview voice")
    }

    // MARK: - Helpers

    private func builtInSubtitle(for speaker: SpeakerDescriptor) -> String? {
        if let detail = speaker.shortDescription, !detail.isEmpty { return detail }
        if let lang = speaker.nativeLanguage, !lang.isEmpty {
            return speaker.isEnglishNative ? "\(lang) - English native" : lang
        }
        return speaker.group.capitalized
    }

    private func matchesSearch(_ speaker: SpeakerDescriptor) -> Bool {
        guard !search.isEmpty else { return true }
        let q = search.lowercased()
        if speaker.displayName.lowercased().contains(q) { return true }
        if (speaker.shortDescription ?? "").lowercased().contains(q) { return true }
        if (speaker.nativeLanguage ?? "").lowercased().contains(q) { return true }
        return false
    }

    private func matchesSearch(_ voice: Voice) -> Bool {
        guard !search.isEmpty else { return true }
        return voice.name.lowercased().contains(search.lowercased())
    }

    @MainActor
    private func presentPreview(_ item: IOSPlayerSheetItem) {
        IOSHaptics.selection()
        presentPlayerSheet(item)
    }
}

// MARK: - Filter

private enum VoiceFilter: String, Identifiable, CaseIterable, Hashable {
    case all
    case builtIn
    case saved

    var id: String { rawValue }

    var label: String {
        switch self {
        case .all: return "All"
        case .builtIn: return "Built-in"
        case .saved: return "Saved"
        }
    }
}
