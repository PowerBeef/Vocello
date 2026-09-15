import SwiftUI
import AppKit
import QwenVoiceNative

@main
struct QwenVoiceApp: App {
    @NSApplicationDelegateAdaptor(QwenVoiceApplicationDelegate.self)
    private var appDelegate
    @State private var ttsEngineStore: TTSEngineStore
    @State private var didInitializeSelectedTTSEngine = false
    @StateObject private var audioPlayer = AudioPlayerViewModel()
    @State private var modelManager = ModelManagerViewModel()
    @State private var savedVoicesViewModel = SavedVoicesViewModel()
    @StateObject private var appCommandRouter = AppCommandRouter.shared
    @StateObject private var generationLibraryEvents = GenerationLibraryEvents.shared
    @StateObject private var appStartupCoordinator = AppStartupCoordinator()
    private let appEngineSelection: AppEngineSelection

    init() {
        let appEngineSelection = AppEngineSelection.current()
        self.appEngineSelection = appEngineSelection
        let engine = appEngineSelection.makeEngine()
        _ttsEngineStore = State(
            initialValue: TTSEngineStore(
                engine: engine
            )
        )
    }

    var body: some Scene {
        WindowGroup(id: "mainWindow") {
            mainWindowContent
        }
        .defaultSize(width: 880, height: 640)
        Settings {
            // The Cmd+, scene hosts the same SettingsView the
            // sidebar shows, so muscle memory keeps working. Deep
            // link highlighting is a no-op in this surface (the
            // sidebar has no notion of "the user just clicked a
            // disabled mode" inside the standalone settings
            // window).
            SettingsView(highlightedMode: .constant(nil))
                .environment(modelManager)
        }
        .commands {
            CommandGroup(replacing: .newItem) { }

            // Playback commands
            CommandMenu(MacInterfaceText.menuPlayback) {
                Button(MacInterfaceText.menuPlayPause) {
                    audioPlayer.togglePlayPause()
                }
                .keyboardShortcut(.space, modifiers: [])
                .disabled(!audioPlayer.hasAudio)

                Button(MacInterfaceText.menuStop) {
                    audioPlayer.dismiss()
                }
                .keyboardShortcut(".", modifiers: .command)
                .disabled(!audioPlayer.hasAudio)
            }

            CommandMenu(MacInterfaceText.menuNavigate) {
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

                Button(MacInterfaceText.menuModels) {
                    appCommandRouter.navigate(to: .settings)
                }
                .keyboardShortcut("6", modifiers: .command)
            }

            // File menu additions
            CommandGroup(after: .saveItem) {
                Divider()
                Button(MacInterfaceText.menuOpenOutputFolder) {
                    NSWorkspace.shared.open(Self.outputsDir)
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
            if let launchDiagnostics = appStartupCoordinator.launchDiagnostics {
                StartupDiagnosticsView(
                    snapshot: launchDiagnostics,
                    onRetry: retryLaunchPreflight
                )
                .frame(minWidth: 520, minHeight: 420)
            } else {
                ContentView(ttsEngineStore: ttsEngineStore)
                    .safeAreaInset(edge: .top, spacing: 0) { GenerationHistoryEnqueueWarning() }
                    .environment(ttsEngineStore)
                    .environmentObject(audioPlayer)
                    .environmentObject(audioPlayer.playbackProgress)
                    .environment(modelManager)
                    .environment(savedVoicesViewModel)
                    .environmentObject(appCommandRouter)
                    .environmentObject(generationLibraryEvents)
                    .frame(minWidth: 720, minHeight: 560)
            }
        }
        .onAppear {
            appStartupCoordinator.setupAppSupport()
            reconcilePendingHistory()
            startSelectedTTSEngineIfNeeded()
            appStartupCoordinator.refreshLaunchDiagnostics()
            AppLaunchConfiguration.openSettingsWindowIfNeeded()
        }
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
        guard appEngineSelection.requiresManualInitialization() else { return }
        guard !didInitializeSelectedTTSEngine else { return }
        didInitializeSelectedTTSEngine = true

        Task {
            do {
                try await ttsEngineStore.initialize(appSupportDirectory: Self.appSupportDir)
            } catch {
                // Native engine initialization publishes its own failure snapshot.
            }
        }
    }

    private func retryLaunchPreflight() {
        appStartupCoordinator.refreshLaunchDiagnostics()
    }
}
