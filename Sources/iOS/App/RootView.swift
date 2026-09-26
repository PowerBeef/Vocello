import SwiftUI
import UIKit
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
    /// Non-observing reference (IUI-5 P2): the root shell must not subscribe
    /// to the whole store — per-publish invalidation here re-diffs every
    /// mounted NavigationStack. Descendants that need engine state observe it
    /// themselves via the injected `environmentObject`.
    let ttsEngine: TTSEngineStore

    @Environment(AppModel.self) private var appModel
    @StateObject private var performanceGate: IOSGenerationPerformanceGateModel
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.accessibilityReduceTransparency) private var systemReduceTransparency
    @AppStorage(IOSAppDefaults.reduceMotionEnabledKey) private var appReduceMotion = false
    @AppStorage(IOSAppDefaults.reduceTransparencyEnabledKey) private var appReduceTransparency = false
    @State private var importedVoicePresentation: ImportedVoicePresentation?
    @State private var importErrorMessage: String?
    @State private var dockHeight = IOSStudioShellMetrics.dockFadeHeight

    init(ttsEngine: TTSEngineStore) {
        self.ttsEngine = ttsEngine
        _performanceGate = StateObject(
            wrappedValue: IOSGenerationPerformanceGateModel(store: ttsEngine)
        )
    }

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
        .safeAreaInset(edge: .top, spacing: 0) { GenerationHistoryEnqueueWarning() }
        // The dock is the only persistent bottom chrome. Playback is
        // presented inline in Studio or through IOSPlayerSheet.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            IOSEngineLifecycleToast(ttsEngine: ttsEngine)
                .padding(.bottom, 6)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            TabDock()
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                    dockHeight = height
                }
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
        // App-switcher privacy is a window above every presentation
        // (`IOSAppSwitcherPrivacyCoverWindows`, IOS-22), not an overlay here:
        // sheets and full-screen covers draw above this view.
        .iosAppAnimation(Theme.Motion.sheetSlideUp, value: isFocusBackdropActive)
        .environment(\.presentIOSPlayerSheet) { item in
            appModel.playerSheetItem = item
        }
        .fullScreenCover(isPresented: $appModel.isOnboardingPresented) {
            IOSOnboardingFlow(isPresented: $appModel.isOnboardingPresented)
        }
        .fullScreenCover(isPresented: $appModel.isCloneReferenceRecorderPresented) {
            IOSRecordVoiceSheet(
                onEnrolled: { voice, transcript, referenceLanguage in
                    appModel.isCloneReferenceRecorderPresented = false
                    appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
                        savedVoiceID: voice.id,
                        wavPath: voice.wavPath,
                        transcript: transcript,
                        transcriptLoadError: nil,
                        referenceLanguage: referenceLanguage
                    )
                    appModel.studioMode = .clone
                },
                onDismiss: {
                    appModel.cancelCloneReferenceRecording()
                }
            )
        }
        .fullScreenCover(item: $importedVoicePresentation) { presentation in
            IOSRecordVoiceSheet(
                importedReference: presentation.reference,
                onEnrolled: { voice, transcript, referenceLanguage in
                    importedVoicePresentation = nil
                    appModel.pendingVoiceCloningHandoff = PendingVoiceCloningHandoff(
                        savedVoiceID: voice.id,
                        wavPath: voice.wavPath,
                        transcript: transcript,
                        transcriptLoadError: nil,
                        referenceLanguage: referenceLanguage
                    )
                    appModel.studioMode = .clone
                    appModel.tab = .studio
                },
                onDismiss: {
                    importedVoicePresentation = nil
                }
            )
        }
        .fileImporter(
            isPresented: $appModel.isCloneReferenceImporterPresented,
            allowedContentTypes: IOSReferenceAudioImportPolicy.allowedContentTypes,
            allowsMultipleSelection: false
        ) { result in
            handleCloneReferenceImport(result)
        }
        .fileDialogDefaultDirectory(
            FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        )
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
        .onOpenURL(perform: openExternalAudio)
        .alert(
            IOSInterfaceText.importFailed,
            isPresented: Binding(
                get: { importErrorMessage != nil },
                set: { if !$0 { importErrorMessage = nil } }
            )
        ) {
            Button("OK", role: .cancel) { importErrorMessage = nil }
        } message: {
            Text(importErrorMessage ?? IOSInterfaceText.importFailedDetail)
        }
        // Outermost on purpose (IUI-5 X3): environment set here reaches the
        // tab screens AND every presentation attached above — sheets, covers,
        // the bottom-panel overlays, the toast, and the dock. These modifiers
        // previously sat inside the chain, so all of that chrome read the
        // DEFAULT reduce-motion/transparency/performance-gate values.
        .environment(\.iosReduceMotionEnabled, effectiveReduceMotion)
        .environment(\.iosDockHeight, dockHeight)
        .environment(\.iosReduceTransparencyEnabled, effectiveReduceTransparency)
        // Fixed-refresh (non-ProMotion) devices render glass with the shipped
        // solid-fill fallback while a generation is active; see
        // IOSGenerationPerformanceGateKey.
        .environment(
            \.iosGenerationPerformanceGate,
            IOSDisplayCapability.isFixedRefreshDisplay && performanceGate.isActive
        )
    }

    // MARK: - Tab routing

    /// Switch-branch tab routing (P4 keep-alive reverted, IUI-5 wave close).
    /// The stable-identity ZStack container (visited tabs kept mounted at
    /// `opacity(0)`) measured a wholesale frame-health regression on device —
    /// +52% hitch on the tab-navigation scenario it targeted, +140% on
    /// voices-scroll, and roughly double on generation-active — and taxed
    /// even single-tab scenarios, so the wrapper itself (not just hidden
    /// siblings) carried the cost. Reverted to the measured-healthy remount
    /// container; per-tab state preservation is re-scoped as model-hoisted
    /// state (survives remount without a persistent view hierarchy). The
    /// `\.iosTabIsActive` environment stays at its default (`true`), which
    /// under remount semantics makes the screens' activation wiring behave
    /// exactly like plain `.task`/`.onDisappear`.
    @ViewBuilder
    private var activeScreen: some View {
        @Bindable var appModel = appModel
        @Bindable var modelNavigation = appModel.settingsModelNavigation

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
            NavigationStack(path: $modelNavigation.path) {
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

    private func openExternalAudio(_ sourceURL: URL) {
        // Keep the URL supplied by the system intact so LocalDocumentIO can consume the
        // security-scoped grant before copying audio and any adjacent transcript sidecar.
        // The copy runs off the main actor and refuses an oversized file (CORE-16).
        Task {
            do {
                let imported = try await IOSReferenceAudioImportPolicy.importReference(
                    from: sourceURL,
                    into: AppPaths.importedReferenceAudioDir
                )
                importErrorMessage = nil
                appModel.playerSheetItem = nil
                appModel.cancelCloneReferenceRecording()
                appModel.cancelCloneReferenceImport()
                appModel.dismissBottomPanel()
                appModel.dismissDeleteModelSheet()
                appModel.tab = .voices
                importedVoicePresentation = ImportedVoicePresentation(reference: imported)
            } catch {
                importErrorMessage = importFailureMessage(error)
            }
        }
    }

    private func handleCloneReferenceImport(_ result: Result<[URL], Error>) {
        appModel.cancelCloneReferenceImport()
        let sourceURL: URL
        do {
            // Preserve the picker URL exactly so the document layer can consume its
            // security-scoped grant before materializing the audio and optional sidecar.
            guard let selected = try IOSReferenceAudioImportPolicy.selectedSourceURL(from: result) else {
                return
            }
            sourceURL = selected
        } catch {
            importErrorMessage = importFailureMessage(error)
            return
        }
        Task {
            do {
                let imported = try await IOSReferenceAudioImportPolicy.importReference(
                    from: sourceURL,
                    into: AppPaths.importedReferenceAudioDir
                )
                importErrorMessage = nil
                importedVoicePresentation = ImportedVoicePresentation(reference: imported)
            } catch {
                importErrorMessage = importFailureMessage(error)
            }
        }
    }

    /// Interface-language copy for a failed import; the alert's generic detail otherwise.
    private func importFailureMessage(_ error: Error) -> String {
        IOSReferenceAudioImportPolicy.failureMessage(
            for: error,
            presentation: IOSAppLanguage.shared.presentation
        ) ?? IOSInterfaceText.importFailedDetail
    }

    private var effectiveReduceMotion: Bool {
        systemReduceMotion || appReduceMotion
    }

    private var effectiveReduceTransparency: Bool {
        systemReduceTransparency || appReduceTransparency
    }
}

private struct ImportedVoicePresentation: Identifiable {
    let id = UUID()
    let reference: ImportedReferenceAudio
}


/// Opaque branded cover shown when the app is backgrounded/inactive so the
/// multitasking snapshot doesn't reveal the user's in-progress script or
/// transcript. Mirrors the launch screen so the transition reads as intentional.
private struct IOSAppSwitcherPrivacyCover: View {
    static let background = Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255)

    var body: some View {
        ZStack {
            Self.background
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

/// IOS-22: the app-switcher privacy cover lives in a window of its own above
/// every presentation. An overlay on the root view sat below the sheets and
/// full-screen covers where scripts and transcripts are edited, so the
/// multitasking snapshot still showed them.
///
/// The cover is shown synchronously when a scene resigns active (or enters the
/// background) and hidden when it is active again. It is never made key, so the
/// focused field and its keyboard survive the round trip, and it draws nothing
/// while the scene is active.
@MainActor
final class IOSAppSwitcherPrivacyCoverWindows: NSObject {
    static let shared = IOSAppSwitcherPrivacyCoverWindows()

    private var windows: [ObjectIdentifier: UIWindow] = [:]
    private var isInstalled = false

    /// Starts following scene activation. Call once at launch, before the
    /// first scene can resign active.
    func install() {
        guard !isInstalled else { return }
        isInstalled = true
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(sceneWillLeaveActive(_:)),
                           name: UIScene.willDeactivateNotification, object: nil)
        center.addObserver(self, selector: #selector(sceneWillLeaveActive(_:)),
                           name: UIScene.didEnterBackgroundNotification, object: nil)
        center.addObserver(self, selector: #selector(sceneDidActivate(_:)),
                           name: UIScene.didActivateNotification, object: nil)
        center.addObserver(self, selector: #selector(sceneDidDisconnect(_:)),
                           name: UIScene.didDisconnectNotification, object: nil)
    }

    @objc private func sceneWillLeaveActive(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene else { return }
        coverWindow(for: scene).isHidden = false
    }

    @objc private func sceneDidActivate(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene else { return }
        windows[ObjectIdentifier(scene)]?.isHidden = true
    }

    @objc private func sceneDidDisconnect(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene else { return }
        windows.removeValue(forKey: ObjectIdentifier(scene))?.isHidden = true
    }

    private func coverWindow(for scene: UIWindowScene) -> UIWindow {
        if let window = windows[ObjectIdentifier(scene)] {
            return window
        }
        let window = UIWindow(windowScene: scene)
        // Sheets, full-screen covers and in-app alerts are all presented inside
        // the app's normal-level window, so any higher level covers them.
        window.windowLevel = .statusBar + 1
        let host = UIHostingController(rootView: IOSAppSwitcherPrivacyCover())
        host.view.backgroundColor = UIColor(IOSAppSwitcherPrivacyCover.background)
        window.rootViewController = host
        window.overrideUserInterfaceStyle = .dark
        windows[ObjectIdentifier(scene)] = window
        return window
    }
}

/// Whether the enclosing tab is the active (visible) one. Introduced for the
/// IUI-5 P4 keep-alive container; with that container reverted (measured
/// frame-health regression — see `activeScreen`), no view writes this key, so
/// it always reads its default (`true`) and the screens' activation wiring
/// (`.task(id:)`, activation-task identities) degenerates to plain
/// remount/teardown semantics. Kept because a future model-hoisted
/// state-preservation design reuses the same contract.
struct IOSTabActiveKey: EnvironmentKey {
    static let defaultValue = true
}

extension EnvironmentValues {
    var iosTabIsActive: Bool {
        get { self[IOSTabActiveKey.self] }
        set { self[IOSTabActiveKey.self] = newValue }
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
