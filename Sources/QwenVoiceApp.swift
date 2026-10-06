import AppKit
import SwiftUI

@main
struct QwenVoiceApp: App {
    @NSApplicationDelegateAdaptor(QwenVoiceApplicationDelegate.self)
    private var appDelegate
    /// The shared engine store over the in-process `MLXTTSEngine`; nil only
    /// when the bootstrap failed, in which case the window shows the startup
    /// diagnostics instead of the shell.
    @State private var ttsEngineStore: TTSEngineStore?
    @State private var engineBootstrapDiagnostics: AppLaunchDiagnosticsSnapshot?
    @State private var didInitializeSelectedTTSEngine = false
    @StateObject private var audioPlayer = AudioPlayerViewModel()
    @State private var modelManager: ModelManagerViewModel
    @StateObject private var savedVoicesViewModel = SavedVoicesViewModel()
    @StateObject private var appCommandRouter = AppCommandRouter.shared
    @StateObject private var generationLibraryEvents = GenerationLibraryEvents.shared
    @StateObject private var appStartupCoordinator = AppStartupCoordinator()
    /// The shell model lives as long as the engine store and the player it
    /// drives (A10-04): its Studio coordinators outlive the window, so a window
    /// closed during a take reopens on that take with its Stop, not on idle
    /// coordinators over a busy engine. A line batch or long-form project still
    /// stops with its sheet when the window closes, and keeps its outcome.
    @State private var appModel: MacAppModel

    init() {
        MacInterfaceLanguage.bootstrap(IOSAppLanguage(defaults: AppDefaults.store))
        _appModel = State(initialValue: MacAppModel())
        let modelManager = ModelManagerViewModel()
        _modelManager = State(initialValue: modelManager)
        do {
            let store = try MacEngineBootstrap.makeEngineStore()
            // MAC-20: a model deletion checks the engine before it removes files.
            modelManager.attachEngine(store)
            _ttsEngineStore = State(initialValue: store)
        } catch {
            _engineBootstrapDiagnostics = State(initialValue: Self.engineBootstrapDiagnostics(for: error))
        }
    }

    private static func engineBootstrapDiagnostics(for error: any Error) -> AppLaunchDiagnosticsSnapshot {
        AppLaunchDiagnosticsSnapshot(
            issue: .engineBootstrapFailed,
            manifestPath: TTSContract.manifestURL?.path,
            bundlePath: Bundle.main.bundlePath,
            resourcesPath: Bundle.main.resourceURL?.path,
            underlyingError: error.localizedDescription
        )
    }

    var body: some Scene {
        WindowGroup(id: "mainWindow") {
            mainWindowContent
        }
        .defaultSize(
            width: MacShellMetrics.windowDefaultSize.width,
            height: MacShellMetrics.windowDefaultSize.height
        )
        Settings {
            settingsWindowContent
        }
        .defaultSize(
            width: MacShellMetrics.settingsWindowDefaultSize.width,
            height: MacShellMetrics.settingsWindowDefaultSize.height
        )
        .commands {
            SidebarCommands()
            CommandGroup(replacing: .newItem) { }

            // Playback commands
            CommandMenu(MacInterfaceText.menuPlayback) {
                Button(MacInterfaceText.menuPlayPause) {
                    audioPlayer.togglePlayPause()
                }
                .keyboardShortcut(.space, modifiers: [])
                .disabled(!audioPlayer.hasAudio)

                // MAC-23: ⌘. is the Mac's cancel key. While a take runs it
                // cancels the take (and its live preview); otherwise it stops
                // playback, as before.
                Button(MacInterfaceText.menuStop) {
                    if appCommandRouter.isGenerationActive {
                        appCommandRouter.cancelGeneration(stoppingPreviewOf: audioPlayer)
                    } else {
                        audioPlayer.dismiss()
                    }
                }
                .keyboardShortcut(".", modifiers: .command)
                .disabled(!audioPlayer.hasAudio && !appCommandRouter.isGenerationActive)
            }

            // A14-05: a running line batch or long-form project keeps its
            // Studio screen, which presents its sheet; leaving it would dismiss
            // the sheet and cancel the run, so navigation waits for it.
            CommandMenu(MacInterfaceText.menuNavigate) {
                Group {
                    Button(MacInterfaceText.menuBuiltInVoice) {
                        appCommandRouter.navigate(to: .customVoice)
                    }
                    .keyboardShortcut("1", modifiers: .command)

                    Button(MacInterfaceText.menuVoiceDesign) {
                        appCommandRouter.navigate(to: .voiceDesign)
                    }
                    .keyboardShortcut("2", modifiers: .command)

                    Button(MacInterfaceText.menuVoiceCloning) {
                        appCommandRouter.navigate(to: .voiceCloning)
                    }
                    .keyboardShortcut("3", modifiers: .command)

                    Button(MacInterfaceText.menuHistory) {
                        appCommandRouter.navigate(to: .history)
                    }
                    .keyboardShortcut("4", modifiers: .command)

                    Button(MacInterfaceText.menuSavedVoices) {
                        appCommandRouter.navigate(to: .voices)
                    }
                    .keyboardShortcut("5", modifiers: .command)

                    // Named for what it opens (MAC-23): the Settings destination.
                    Button(MacInterfaceText.settingsTitle) {
                        appCommandRouter.navigate(to: .settings)
                    }
                    .keyboardShortcut("6", modifiers: .command)

                    Divider()

                    Button(MacInterfaceText.menuSearchHistory) {
                        appCommandRouter.searchHistory()
                    }
                    .keyboardShortcut("f", modifiers: .command)
                }
                .disabled(appCommandRouter.isNavigationLocked)
            }

            // File menu additions
            CommandGroup(after: .saveItem) {
                Divider()
                Button(MacInterfaceText.menuOpenOutputFolder) {
                    // MAC-15: the folder new takes are written to, the custom
                    // one when it is usable.
                    NSWorkspace.shared.open(AudioService.effectiveOutputsRoot)
                }
                .keyboardShortcut("o", modifiers: [.command, .shift])

                Button(MacInterfaceText.revealInFinder) {
                    if let path = audioPlayer.currentFilePath {
                        NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
                    }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(audioPlayer.currentFilePath == nil)
            }
        }
    }

    @ViewBuilder
    private var mainWindowContent: some View {
        Group {
            if let launchDiagnostics = appStartupCoordinator.launchDiagnostics ?? engineBootstrapDiagnostics {
                MacStartupDiagnosticsView(
                    snapshot: launchDiagnostics,
                    onRetry: retryLaunchPreflight
                )
                .frame(
                    minWidth: MacShellMetrics.diagnosticsMinSize.width,
                    minHeight: MacShellMetrics.diagnosticsMinSize.height
                )
            } else if let ttsEngineStore {
                ContentView(ttsEngineStore: ttsEngineStore, appModel: appModel)
                    .environmentObject(ttsEngineStore)
                    .environmentObject(audioPlayer)
                    .environmentObject(audioPlayer.playbackProgress)
                    .environment(modelManager)
                    .environmentObject(savedVoicesViewModel)
                    .environmentObject(appCommandRouter)
                    .environmentObject(generationLibraryEvents)
                    .frame(
                        minWidth: MacShellMetrics.windowMinSize.width,
                        minHeight: MacShellMetrics.windowMinSize.height
                    )
            }
        }
        // Dark-only, like iOS (maintainer decision 2026-09-14); the delegate
        // pins the AppKit appearance, this pins the SwiftUI environment.
        .preferredColorScheme(.dark)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            // System Default re-resolves if the system language changed while
            // the user was away.
            MacInterfaceLanguage.refreshSystemLanguage()
        }
        .onAppear {
            appStartupCoordinator.setupAppSupport()
            reconcilePendingHistory()
            startSelectedTTSEngineIfNeeded()
            appStartupCoordinator.refreshLaunchDiagnostics()
            AppLaunchConfiguration.openSettingsWindowIfNeeded()
        }
    }

    /// The Cmd+, scene hosts the same screen the sidebar shows, so muscle
    /// memory keeps working; the screen reads only the model manager, and the
    /// deep-link highlight is a no-op in this window.
    private var settingsWindowContent: some View {
        MacSettingsScreen(highlightedMode: .constant(nil))
            .frame(
                minWidth: MacShellMetrics.settingsWindowMinSize.width,
                minHeight: MacShellMetrics.settingsWindowMinSize.height
            )
            .environment(modelManager)
            .preferredColorScheme(.dark)
    }

    static var voicesDir: URL { AppPaths.voicesDir }

    static var appSupportDir: URL {
        AppPaths.appSupportDir
    }

    static var modelsDir: URL { AppPaths.modelsDir }
    static var outputsDir: URL { AppPaths.outputsDir }

    private func reconcilePendingHistory() {
        Task { @concurrent in
            let result = await GenerationHistoryRecovery.reconcile()
            guard !result.committed.isEmpty || result.snapshot.needsAttention else { return }
            await MainActor.run {
                for generation in result.committed {
                    GenerationLibraryEvents.shared.announceGenerationAppended(generation)
                }
                NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
            }
        }
    }

    private func startSelectedTTSEngineIfNeeded() {
        // While a failed start is on screen, only its Retry starts the engine again
        // (the window's onAppear fires each time the content switches).
        guard let ttsEngineStore, !didInitializeSelectedTTSEngine, engineBootstrapDiagnostics == nil else { return }
        didInitializeSelectedTTSEngine = true

        Task {
            do {
                try await ttsEngineStore.initialize(appSupportDirectory: Self.appSupportDir)
            } catch {
                // The engine publishes no failure state for a failed start, so the
                // app would sit on "Starting engine…" for good. Show the launch
                // diagnostics instead; Retry starts the engine again.
                didInitializeSelectedTTSEngine = false
                engineBootstrapDiagnostics = Self.engineBootstrapDiagnostics(for: error)
            }
        }
    }

    /// Retry re-runs the preflight and, when the engine could not be built,
    /// the engine bootstrap itself (MAC-04): before, a failed bootstrap stayed
    /// on screen however often Retry was pressed.
    private func retryLaunchPreflight() {
        appStartupCoordinator.refreshLaunchDiagnostics()
        guard ttsEngineStore == nil else {
            // The store exists, so what failed was its start.
            if engineBootstrapDiagnostics != nil {
                engineBootstrapDiagnostics = nil
                appStartupCoordinator.setupAppSupport()
                startSelectedTTSEngineIfNeeded()
            }
            return
        }
        do {
            let store = try MacEngineBootstrap.makeEngineStore()
            modelManager.attachEngine(store)
            ttsEngineStore = store
            engineBootstrapDiagnostics = nil
            startSelectedTTSEngineIfNeeded()
        } catch {
            engineBootstrapDiagnostics = Self.engineBootstrapDiagnostics(for: error)
        }
    }
}
