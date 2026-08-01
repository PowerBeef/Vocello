import SwiftUI
import QwenVoiceCore

/// Top-level iOS root view. Replaces the legacy `QVoiceiOSRootView`
/// switch-on-tab tree. Reads everything from the injected `AppModel`
/// and owns the global sheet plumbing:
///
/// - Onboarding `fullScreenCover` gated on `AppModel.isOnboardingPresented`.
/// - Player sheet `sheet(item:)` keyed on `AppModel.playerSheetItem`.
/// - Tab routing via `AppModel.tab`.
/// - Custom `TabDock` at the bottom (no native `TabView`; the design
///   uses a mode-tinted glass dock that doesn't fit `Tab` API).
///
/// Each tab routes to its dedicated screen (StudioScreen, VoicesScreen,
/// HistoryScreen, SettingsScreen); those screens own their bodies
/// directly — the legacy per-tab container indirection is gone
/// (AppModel migration Phases 2–6, see `AppModel`'s type comment).
struct RootView: View {
    @Environment(AppModel.self) private var appModel
    @EnvironmentObject private var ttsEngine: TTSEngineStore
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.accessibilityReduceTransparency) private var systemReduceTransparency
    @AppStorage(IOSAppDefaults.reduceMotionEnabledKey) private var appReduceMotion = false
    @AppStorage(IOSAppDefaults.reduceTransparencyEnabledKey) private var appReduceTransparency = false

    var body: some View {
        @Bindable var appModel = appModel

        // R0 (2026-05-21): RootView now owns the entire app chrome the way
        // `design_references/Vocello iOS/ios-frame.jsx` does in the React
        // prototype:
        //
        //   ZStack:
        //     tab backdrop wash      ← radial gradient, active tab tint
        //     activeScreen           ← per-tab body, transparent
        //   safeAreaInset(.bottom):
        //     TabDock                ← single source of truth for the dock
        //
        // The legacy `IOSStudioShellScreen` no longer paints a canopy or its
        // own dock; it just hosts the per-screen body and the engine /
        // now-playing toast safe-area insets.
        // Perf (iOS frontend audit, Wave 2): the mode backdrop is painted by each
        // screen's IOSStudioShellScreen, which sits INSIDE the NavigationStack and whose
        // IOSModeBackdrop has an opaque `canvasTop` base — so it fully occludes any
        // backdrop painted here. RootView previously also painted one (tinted by
        // activeBackdropTint): a full-screen RadialGradient + .plusLighter blend pass that
        // was never visible. Dropping it removes one offscreen-composited backdrop layer
        // per redraw across all tabs, pixel-identical (verified by sim shot parity).
        ZStack {
            activeScreen
        }
        .iosAppAnimation(Theme.Motion.easeOut, value: appModel.tab)
        .iosAppAnimation(Theme.Motion.modePillSlide, value: appModel.studioMode)
        .environment(\.iosReduceMotionEnabled, effectiveReduceMotion)
        .environment(\.iosReduceTransparencyEnabled, effectiveReduceTransparency)
        // Fixed-refresh (non-ProMotion) devices render glass with the shipped
        // solid-fill fallback while a generation is active; see
        // IOSGenerationPerformanceGateKey.
        .environment(
            \.iosGenerationPerformanceGate,
            IOSDisplayCapability.isFixedRefreshDisplay
                && (ttsEngine.hasActiveGeneration || ttsEngine.hasSustainedPerformanceActivity)
        )
        // The dock is the only persistent bottom chrome. Playback is
        // presented inline in Studio or through IOSPlayerSheet.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            IOSEngineLifecycleToast()
                .padding(.bottom, 6)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            TabDock()
        }
        // Pin all bottom chrome (dock + toast) AND the active screen so the
        // on-screen keyboard OVERLAYS them instead of riding the whole layout up.
        // This is safe app-wide: every text editor that must sit above the keyboard
        // lives in an isolated `.sheet` / `.fullScreenCover` (the design-brief, batch,
        // and recorder editors) — those are separate presentations unaffected by
        // this modifier. The bottom-panel overlays reachable from here are pickers
        // (delivery/voice/language/install — no keyboard), and the only inline
        // editor below this is the Studio composer, which we intend to overlay.
        .ignoresSafeArea(.keyboard, edges: .bottom)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .tint(Theme.Brand.gold)
        .iosFocusModalBackdrop(
            isActive: isFocusBackdropActive,
            allowsBlur: !effectiveReduceTransparency
        )
        .overlay {
            bottomPanelOverlay
            deleteModelSheetOverlay
        }
        // App-switcher privacy: when the app is not active, cover the content so the
        // script/transcript being composed isn't captured in the multitasking snapshot.
        .overlay {
            if scenePhase != .active {
                IOSAppSwitcherPrivacyCover()
                    .transition(.opacity)
                    .zIndex(100)
            }
        }
        .iosAppAnimation(Theme.Motion.easeOut, value: scenePhase)
        .iosAppAnimation(Theme.Motion.sheetSlideUp, value: isFocusBackdropActive)
        .environment(\.presentIOSPlayerSheet) { item in
            appModel.playerSheetItem = item
        }
        .fullScreenCover(isPresented: $appModel.isOnboardingPresented) {
            IOSOnboardingFlow(isPresented: $appModel.isOnboardingPresented)
        }
        .fullScreenCover(isPresented: $appModel.isCloneReferenceRecorderPresented) {
            IOSRecordVoiceSheet(
                onEnrolled: { voice, transcript, language in
                    appModel.isCloneReferenceRecorderPresented = false
                    appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
                        savedVoiceID: voice.id,
                        wavPath: voice.wavPath,
                        transcript: transcript,
                        transcriptLoadError: nil,
                        language: language
                    )
                    appModel.studioMode = .clone
                },
                onDismiss: {
                    appModel.cancelCloneReferenceRecording()
                }
            )
        }
        .sheet(item: $appModel.playerSheetItem) { item in
            IOSPlayerSheet(
                item: item,
                onDismiss: { appModel.playerSheetItem = nil }
            )
            .presentationDetents([.fraction(0.88)])
            .presentationDragIndicator(.hidden)
            .presentationCornerRadius(28)
            .presentationBackground(Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255).opacity(0.96))
        }
    }

    // MARK: - Tab routing

    @ViewBuilder
    private var activeScreen: some View {
        @Bindable var appModel = appModel

        switch appModel.tab {
        case .studio:
            NavigationStack {
                StudioScreen()
            }
            .toolbar(.hidden, for: .navigationBar)

        case .voices:
            NavigationStack {
                VoicesScreen()
            }
            .toolbar(.hidden, for: .navigationBar)

        case .history:
            NavigationStack {
                HistoryScreen()
            }
            .toolbar(.hidden, for: .navigationBar)

        case .settings:
            NavigationStack {
                SettingsScreen()
            }
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    @ViewBuilder
    private var deleteModelSheetOverlay: some View {
        if let item = appModel.deleteModelSheetItem {
            GeometryReader { proxy in
                ZStack(alignment: .bottom) {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture {
                            dismissDeleteModelSheet()
                        }

                    IOSDeleteModelSheet(
                        modelName: item.modelName,
                        sizeLabel: item.sizeLabel,
                        presentation: .edgeToEdge(bottomSafeAreaInset: proxy.safeAreaInsets.bottom),
                        onConfirm: {
                            item.onConfirm()
                            dismissDeleteModelSheet()
                        },
                        onCancel: {
                            dismissDeleteModelSheet()
                        }
                    )
                    .frame(maxWidth: .infinity)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                .ignoresSafeArea()
            }
            .zIndex(20)
        }
    }

    @ViewBuilder
    private var bottomPanelOverlay: some View {
        if let item = appModel.bottomPanelItem {
            GeometryReader { proxy in
                ZStack(alignment: .bottom) {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture {
                            dismissBottomPanel()
                        }

                    item.content(proxy.safeAreaInsets.bottom, proxy.size.height, dismissBottomPanel)
                        .frame(maxWidth: .infinity)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                .ignoresSafeArea()
            }
            // Measure the FULL screen (not the safe-area-reduced content region inside
            // RootView's TabDock/toast safeAreaInset chain), so the expanded picker height
            // (IOSBottomSheetChrome.expandedHeight) is computed off the real screen and the
            // top peek is what we actually specify.
            .ignoresSafeArea()
            .zIndex(19)
        }
    }

    private var isFocusBackdropActive: Bool {
        appModel.isFocusBackdropPresented
            || appModel.bottomPanelItem != nil
            || appModel.deleteModelSheetItem != nil
    }

    private func dismissDeleteModelSheet() {
        appModel.dismissDeleteModelSheet()
    }

    private func dismissBottomPanel() {
        appModel.dismissBottomPanel()
    }

    private var effectiveReduceMotion: Bool {
        systemReduceMotion || appReduceMotion
    }

    private var effectiveReduceTransparency: Bool {
        systemReduceTransparency || appReduceTransparency
    }
}


/// Opaque branded cover shown when the app is backgrounded/inactive so the
/// multitasking snapshot doesn't reveal the user's in-progress script or
/// transcript. Mirrors the launch screen so the transition reads as intentional.
private struct IOSAppSwitcherPrivacyCover: View {
    var body: some View {
        ZStack {
            Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255)
                .ignoresSafeArea()
            Image("VocelloLaunchLogo")
                .renderingMode(.original)
                .resizable()
                .scaledToFit()
                .frame(width: 200)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private extension View {
    func iosFocusModalBackdrop(isActive: Bool, allowsBlur: Bool) -> some View {
        blur(radius: isActive && allowsBlur ? 2.4 : 0)
            .overlay {
                if isActive {
                    Color.black
                        .opacity(allowsBlur ? 0.10 : 0.34)
                        .ignoresSafeArea()
                        .allowsHitTesting(false)
                        .transition(.opacity)
                }
            }
    }
}
