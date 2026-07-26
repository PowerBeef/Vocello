import SwiftUI
import QwenVoiceCore

private struct IOSPrefetchContext {
    let request: GenerationRequest
    let screen: String
    let requestKey: String
    let signature: String
    let debounceNanoseconds: UInt64
}

enum IOSPrefetchRequestFactory {
    static func customVoiceRequest(
        model: ModelDescriptor,
        draft: CustomVoiceDraft,
        fallbackText: String
    ) -> GenerationRequest {
        let text = draft.text.isEmpty ? fallbackText : draft.text
        return GenerationRequest(
            mode: .custom,
            modelID: model.id,
            text: text,
            outputPath: "",
            shouldStream: true,
            streamingInterval: GenerationSemantics.appStreamingInterval,
            languageHint: draft.selectedLanguage.rawValue,
            payload: .custom(
                speakerID: draft.selectedSpeaker,
                deliveryStyle: model.supportsInstructionControl
                    ? draft.resolvedDeliveryInstruction
                    : nil
            )
        )
    }

    static func voiceDesignRequest(
        model: ModelDescriptor,
        draft: VoiceDesignDraft,
        fallbackText: String,
        fallbackVoiceDescription: String
    ) -> GenerationRequest {
        let text = draft.text.isEmpty ? fallbackText : draft.text
        let voiceDescription = draft.voiceDescription.isEmpty
            ? fallbackVoiceDescription
            : draft.voiceDescription
        return GenerationRequest(
            mode: .design,
            modelID: model.id,
            text: text,
            outputPath: "",
            shouldStream: true,
            streamingInterval: GenerationSemantics.appStreamingInterval,
            languageHint: draft.selectedLanguage.rawValue,
            payload: .design(
                voiceDescription: voiceDescription,
                deliveryStyle: draft.resolvedDeliveryInstruction
            )
        )
    }
}

private enum IOSProactivePrefetchPolicy {
    // Proactive prefetch is intentionally disabled in the single shippable
    // configuration. Keep this explicit rather than reviving the former dead
    // DEBUG-only environment override.
    static let isEnabled = false
}

struct IOSGenerateContainerView: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var audioPlayer: AudioPlayerViewModel
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var modelManager: ModelManagerViewModel
    private let selectorRailHeight: CGFloat = 44

    @Binding var selectedTab: IOSAppTab
    let isTabActive: Bool
    @Binding var selectedSection: IOSGenerationSection
    @Binding var customVoiceDraft: CustomVoiceDraft
    @Binding var voiceDesignDraft: VoiceDesignDraft
    @Binding var voiceCloningDraft: VoiceCloningDraft
    @Binding var pendingVoiceCloningHandoff: PendingVoiceCloningHandoff?

    private var hasAnyInstalledModel: Bool {
        modelManager.statuses.values.contains { status in
            if case .installed = status { return true }
            if case .updateAvailable = status { return true }
            return false
        }
    }

    var body: some View {
        IOSStudioShellScreen(
            selectedTab: $selectedTab,
            activeTab: .studio,
            tint: selectedSection.primaryActionTint
        ) {
            // Studio's CTA / generating waveform / inline player live INSIDE
            // each per-mode view via IOSStudioCanvas, per
            // design_references/Vocello iOS/studio.jsx (vc-dock-area).
            //
            // R2 (2026-05-21): the body was previously wrapped in a
            // ScrollView, which sized content to its natural height and
            // killed the canvas's Spacer-based layout (composer
            // sticking to top, chips + dock pinned to bottom). Per the
            // design Studio doesn't scroll — composer fills, chips and
            // dock sit against the safe-area bottom inset above the
            // tab dock. Plain VStack reinstates that flow.
            VStack(alignment: .leading, spacing: 0) {
                IOSGenerationModeSelector(selectedSection: $selectedSection)
                    .frame(height: selectorRailHeight)
                    .padding(.horizontal, 16)
                    .padding(.top, 6)
                    .padding(.bottom, 10)

                IOSGenerateModeViewport(selection: selectedSection) {
                    IOSCustomVoiceView(
                        isActive: selectedSection == .custom,
                        selectedTab: $selectedTab,
                        draft: $customVoiceDraft
                    )
                } design: {
                    IOSVoiceDesignView(
                        isActive: selectedSection == .design,
                        selectedTab: $selectedTab,
                        draft: $voiceDesignDraft
                    )
                } clone: {
                    IOSVoiceCloningView(
                        isActive: selectedSection == .clone,
                        selectedTab: $selectedTab,
                        draft: $voiceCloningDraft,
                        pendingSavedVoiceHandoff: $pendingVoiceCloningHandoff
                    )
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .background {
            IOSGeneratePrefetchCoordinator(
                isTabActive: isTabActive,
                selectedSection: selectedSection,
                customVoiceDraft: customVoiceDraft,
                voiceDesignDraft: voiceDesignDraft
            )
        }
    }
}

private struct IOSGeneratePrefetchCoordinator: View {
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @EnvironmentObject private var modelManager: ModelManagerViewModel

    let isTabActive: Bool
    let selectedSection: IOSGenerationSection
    let customVoiceDraft: CustomVoiceDraft
    let voiceDesignDraft: VoiceDesignDraft

    @State private var didRefreshAvailability = false
    @State private var prefetchTask: Task<Void, Never>?
    @State private var lastCompletedPrefetchSignature: String?
    @State private var latestPrefetchToken = ""

    var body: some View {
        Color.clear
            .frame(width: 0, height: 0)
            .task {
                await modelManager.refresh()
                didRefreshAvailability = true
                guard IOSProactivePrefetchPolicy.isEnabled else { return }
                guard let context = currentPrefetchContext() else { return }
                await performPrefetch(context, token: UUID().uuidString)
            }
            .onChange(of: isTabActive) { _, _ in
                scheduleSelectedGenerationPrefetch(force: true)
            }
            .onChange(of: selectedSection) { _, _ in
                scheduleSelectedGenerationPrefetch(force: true)
            }
            .onChange(of: modelManager.statuses) { _, _ in
                guard didRefreshAvailability else { return }
                scheduleSelectedGenerationPrefetch(force: true)
            }
            .onChange(of: customVoiceDraft.selectedSpeaker) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: customVoiceDraft.selectedLanguage) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: customVoiceDraft.resolvedDeliveryInstruction) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: voiceDesignDraft.voiceDescription) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: voiceDesignDraft.selectedLanguage) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: voiceDesignDraft.resolvedDeliveryInstruction) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
            .onChange(of: voiceDesignDraft.text) { _, _ in
                scheduleSelectedGenerationPrefetch()
            }
    }

    private func scheduleSelectedGenerationPrefetch(force: Bool = false) {
        prefetchTask?.cancel()
        guard IOSProactivePrefetchPolicy.isEnabled else { return }
        guard let context = currentPrefetchContext() else { return }
        if !force, lastCompletedPrefetchSignature == context.signature {
            return
        }

        prefetchTask = Task { @MainActor in
            if context.debounceNanoseconds > 0 {
                try? await Task.sleep(nanoseconds: context.debounceNanoseconds)
            }
            guard !Task.isCancelled else { return }
            await performPrefetch(context, token: UUID().uuidString)
        }
    }

    private func performPrefetch(_ context: IOSPrefetchContext, token: String) async {
        latestPrefetchToken = token

        let diagnostics = await ttsEngine.prefetchInteractiveReadinessIfNeeded(for: context.request)
        guard latestPrefetchToken == token else { return }

        if diagnostics != nil {
            lastCompletedPrefetchSignature = context.signature
        }
    }

    private func currentPrefetchContext() -> IOSPrefetchContext? {
        guard isTabActive else { return nil }
        guard let model = TTSModel.model(for: selectedSection.mode),
              modelManager.isAvailable(model),
              ttsEngine.supportsMode(selectedSection.mode) else {
            return nil
        }

        switch selectedSection {
        case .custom:
            let request = IOSPrefetchRequestFactory.customVoiceRequest(
                model: model,
                draft: customVoiceDraft,
                fallbackText: MLXTTSEngine.lightweightWarmupTextForUI
            )
            let normalizedEmotion = GenerationSemantics.normalizedConditioningCacheKeyText(
                customVoiceDraft.resolvedDeliveryInstruction
            )
            return IOSPrefetchContext(
                request: request,
                screen: "screen_customVoice",
                requestKey: GenerationSemantics.prewarmIdentityKey(
                    modelID: request.modelID,
                    mode: request.mode,
                    voice: customVoiceDraft.selectedSpeaker,
                    instruct: customVoiceDraft.resolvedDeliveryInstruction
                ),
                signature: [
                    "custom",
                    model.id,
                    GenerationSemantics.qwenLanguageHint(for: request),
                    customVoiceDraft.selectedSpeaker,
                    normalizedEmotion,
                ].joined(separator: "|"),
                debounceNanoseconds: 150_000_000
            )
        case .design:
            let fallbackVoiceDescription = "Clear, natural narration voice"
            let request = IOSPrefetchRequestFactory.voiceDesignRequest(
                model: model,
                draft: voiceDesignDraft,
                fallbackText: GenerationSemantics.canonicalDesignWarmShortText,
                fallbackVoiceDescription: fallbackVoiceDescription
            )
            let voiceDescription: String
            if case .design(let resolvedVoiceDescription, _) = request.payload {
                voiceDescription = resolvedVoiceDescription
            } else {
                voiceDescription = fallbackVoiceDescription
            }
            let requestKey = GenerationSemantics.designConditioningWarmKey(for: request) ?? ""
            let bucket = GenerationSemantics.designWarmBucket(for: request.text)
            let instructionIdentity = GenerationSemantics.normalizedDesignConditioningIdentity(
                language: GenerationSemantics.qwenLanguageHint(for: request),
                voiceDescription: voiceDescription,
                emotion: voiceDesignDraft.resolvedDeliveryInstruction
            )
            return IOSPrefetchContext(
                request: request,
                screen: "screen_voiceDesign",
                requestKey: requestKey,
                signature: [
                    "design",
                    model.id,
                    instructionIdentity,
                    bucket.rawValue,
                ].joined(separator: "|"),
                debounceNanoseconds: 350_000_000
            )
        case .clone:
            return nil
        }
    }
}

struct IOSGenerationModeSelector: View {
    @Binding var selectedSection: IOSGenerationSection
    @EnvironmentObject private var ttsEngine: TTSEngineStore

    var body: some View {
        IOSCapsuleSelector(
            items: IOSGenerationSection.allCases,
            selection: $selectedSection,
            title: \.compactTitle,
            selectedTint: \.primaryActionTint,
            isSelectionDisabled: ttsEngine.hasActiveGeneration,
            controlAccessibilityIdentifier: "generateSectionPicker",
            itemAccessibilityIdentifier: { "generateSection_\($0.rawValue)" }
        )
    }
}

/// Shared 3-way capsule selector used by `IOSGenerationModeSelector`
/// (Studio mode) and previously by Library / History filter rows.
///
/// R3 (2026-05-21): matches `design_references/Vocello iOS/app.css`
/// `.vc-mode-segmented` plus `chrome.jsx`'s active-mode inline style:
///
///   rail:  rgba(255,255,255,0.04) fill + 0.5pt rgba(255,255,255,0.08)
///          stroke. Neutral, not mode-tinted.
///   pill:  active tint @ 22 % fill + active tint @ 36 % stroke,
///          white inset top highlight, and 1pt black drop shadow.
struct IOSCapsuleSelector<Item: Identifiable & Hashable>: View {
    let items: [Item]
    @Binding var selection: Item
    let title: KeyPath<Item, String>
    let selectedTint: (Item) -> Color
    var isSelectionDisabled = false
    let controlAccessibilityIdentifier: String
    let itemAccessibilityIdentifier: (Item) -> String
    @Namespace private var selectionPillNamespace

    var body: some View {
        HStack(spacing: 4) {
            ForEach(items) { item in
                Button {
                    guard !isSelectionDisabled else { return }
                    guard item != selection else { return }
                    selection = item
                } label: {
                    Text(item[keyPath: title])
                        .font(.system(size: 15, weight: .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .foregroundStyle(
                            item == selection
                                ? IOSAppTheme.textPrimary
                                : IOSAppTheme.textSecondary
                        )
                        .frame(minHeight: 36)
                        .padding(.horizontal, 20)
                        .background {
                            if item == selection {
                                IOSCapsuleSelectorPill(tint: selectedTint(item))
                                    .matchedGeometryEffect(id: "selectionPill", in: selectionPillNamespace)
                            }
                        }
                }
                .buttonStyle(.plain)
                .disabled(isSelectionDisabled && item != selection)
                .opacity(isSelectionDisabled && item != selection ? 0.42 : 1)
                .iosAppAnimation(IOSSelectionMotion.selectorLabel, value: selection)
                .accessibilityIdentifier(itemAccessibilityIdentifier(item))
                .accessibilityAddTraits(item == selection ? .isSelected : [])
            }
        }
        .iosAppAnimation(IOSDesignMotion.modePillSlide, value: selection)
        .padding(4)
        .background {
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        }
        .frame(height: 44)
        .fixedSize(horizontal: true, vertical: false)
        .frame(maxWidth: .infinity, alignment: .center)
        .sensoryFeedback(.selection, trigger: selection)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(controlAccessibilityIdentifier)
    }
}

/// The moving capsule pill behind the selected segment.
/// Tinted per `chrome.jsx`'s `color-mix(in oklch, activeColor 22%)`
/// override on `.vc-mode-pill`.
private struct IOSCapsuleSelectorPill: View {
    let tint: Color

    var body: some View {
        let shape = Capsule(style: .continuous)
        shape
            .fill(tint.opacity(0.22))
            .overlay {
                shape.stroke(tint.opacity(0.36), lineWidth: 0.5)
            }
            .overlay(alignment: .top) {
                // inset 0 1px 0 rgba(255,255,255,0.10) — top-edge highlight
                shape
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    .mask(
                        LinearGradient(
                            colors: [.white, .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
            .shadow(color: .black.opacity(0.15), radius: 1, x: 0, y: 1)
    }
}

extension IOSGenerationSection {
    var primaryActionSystemImage: String {
        switch self {
        case .custom:
            return "waveform.and.mic"
        case .design:
            return "paintbrush.pointed"
        case .clone:
            return "waveform.path.ecg"
        }
    }

    var primaryActionTint: Color {
        IOSBrandTheme.modeColor(for: mode)
    }
}
