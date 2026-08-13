import AVFoundation
import MLX
import SwiftUI
import UIKit
import QwenVoiceCore

/// iOS app entry point.
///
/// **On-device-capable.** Heavy generation runs **in-process in the app** via
/// `NativeRuntimeFactory` (see `IOSAppBootstrap.makeBackend`) — the app process gets
/// the `com.apple.developer.kernel.increased-memory-limit` entitlement's raised limit,
/// whereas the (since-removed) `VocelloEngineExtension` did not and was jetsam-killed
/// loading the model. The headless `IOSDeviceDiagnosticsRunner` drives explicit
/// non-UI device diagnostics, including generation and Speech-asset bootstrap;
/// it ships inert unless a repository command supplies its purpose-specific environment.
@main
struct QVoiceiOSApp: App {
    @StateObject private var deps: IOSAppDependenciesContainer
    @UIApplicationDelegateAdaptor private var appDelegate: IOSAppDelegate
    @StateObject private var audioPlayer = AudioPlayerViewModel()
    @StateObject private var savedVoicesViewModel = SavedVoicesViewModel()
    @StateObject private var runtimeReleaseCoordinator = RuntimeReleaseCoordinator()
    @State private var didInitializeEngine = false
    private let memoryBudgetPolicy = IOSMemoryBudgetPolicy.iPhoneShippingDefault
    @Environment(\.scenePhase) private var scenePhase

    init() {
        _deps = StateObject(wrappedValue: IOSAppDependenciesContainer())
        configureAudioSession()
        configureNativeRuntimeMemoryCacheIfNeeded()
        IOSCrashObserver.shared.start()
        IOSMetricKitMemoryReporter.shared.start()
        // UI-perf lane hooks (both inert without QWENVOICE_DEBUG + their
        // registered knobs): seed History before any navigation can reach it,
        // then start the frame probe so its display link spans the launch.
        IOSUIPerfHistorySeeder.seedIfConfigured()
        IOSUIPerfFrameProbe.startIfConfigured()
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if let error = deps.startupError {
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 64, height: 64)
                            .foregroundColor(.orange)
                        Text("App Initialization Failed")
                            .font(.title2.bold())
                        Text(error.localizedDescription)
                            .multilineTextAlignment(.center)
                            .foregroundColor(.secondary)
                            .padding(.horizontal)
                    }
                    .padding()
                } else if let modelRegistry = deps.registry, let engine = deps.engine, let manager = deps.modelManager, let installer = deps.modelInstaller {
                    if IOSDeviceSupport.isSupportedHardware {
                        QVoiceiOSRootView(modelRegistry: modelRegistry, ttsEngine: engine)
                            .environmentObject(engine)
                            .environmentObject(audioPlayer)
                            .environmentObject(audioPlayer.playbackProgress)
                            .environmentObject(manager)
                            .environmentObject(savedVoicesViewModel)
                            .environmentObject(installer)
                            .onAppear {
                                setupAppSupport()
                                Task {
                                    await engine.refreshMemoryContext(reason: "appear", source: "app")
                                }
                                startEngineIfNeeded()
                            }
                            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didReceiveMemoryWarningNotification)) { _ in
                                Task { @MainActor in
                                    await engine.recordApplicationMemoryWarning(reason: "memory_warning")
                                    handleMemoryPressure(reason: "memory_warning", severity: .critical)
                                }
                            }
                            .onReceive(NotificationCenter.default.publisher(for: ProcessInfo.thermalStateDidChangeNotification)) { _ in
                                let thermalState = ProcessInfo.processInfo.thermalState
                                if thermalState == .serious || thermalState == .critical {
                                    let reason = "thermal_\(thermalState.rawValue)"
                                    handleMemoryPressure(reason: reason, severity: .warning)
                                }
                            }
                            .onReceive(engine.$hasActiveGeneration) { hasActiveGeneration in
                                guard !hasActiveGeneration else { return }
                                executeDeferredMemoryPressureReliefIfNeeded()
                                executeDeferredRuntimeReleaseIfNeeded()
                            }
                            .onReceive(NotificationCenter.default.publisher(for: .ttsEngineMemoryContextDidChange)) { _ in
                                if engine.currentMemoryContext().pressureBand == .critical {
                                    audioPlayer.abortLivePreviewIfNeeded()
                                }
                            }
                            .onReceive(engine.$engineLifecycleState.removeDuplicates()) { lifecycleState in
                                switch lifecycleState {
                                case .interrupted, .invalidated:
                                    audioPlayer.abortLivePreviewIfNeeded()
                                case .connected:
                                    executeDeferredMemoryPressureReliefIfNeeded()
                                    executeDeferredRuntimeReleaseIfNeeded()
                                case .idle, .launching, .recovering, .failed:
                                    break
                                }
                            }
                    } else {
                        IOSUnsupportedDeviceView(reason: IOSDeviceSupport.unsupportedReason)
                    }
                }
            }
            .preferredColorScheme(.dark)
        }
        .onChange(of: scenePhase) { _, newValue in
            handleScenePhaseChange(newValue)
        }
    }

    private func startEngineIfNeeded() {
        guard !didInitializeEngine, let engine = deps.engine else { return }
        didInitializeEngine = true
        engine.start()
        Task {
            do {
                try await engine.initialize(appSupportDirectory: AppPaths.appSupportDir)
                await engine.refreshMemoryContext(reason: "engine_initialized", source: "app")
                if TelemetryGate.resolvedEnabled {
                    print("[QVoiceiOSApp] Engine initialized.")
                }
                // Headless, non-UI on-device diagnostics runner. No-op unless a
                // purpose-specific environment key is set by scripts/ios_device.sh.
                IOSDeviceDiagnosticsRunner.runIfRequested(engine: engine)
            } catch {
                didInitializeEngine = false
                if TelemetryGate.resolvedEnabled {
                    print("[QVoiceiOSApp] Engine initialization failed: \(error.localizedDescription)")
                }
                engine.setVisibleError("Engine initialization failed: \(error.localizedDescription)")
            }
        }
    }

    private func handleScenePhaseChange(_ scenePhase: ScenePhase) {
        switch scenePhase {
        case .active:
            setPlaybackSessionActive(true)
            if let engine = deps.engine {
                Task {
                    await engine.refreshMemoryContext(reason: "scene_active", source: "app")
                }
            }
            executeDeferredMemoryPressureReliefIfNeeded()
            executeDeferredRuntimeReleaseIfNeeded()
        case .background:
            // Hand the audio session back to the system so other apps can resume
            // (we declare no background-audio mode, so playback can't continue
            // backgrounded anyway). Foregrounding re-activates it.
            setPlaybackSessionActive(false)
            releaseRuntime(reason: "background")
        case .inactive:
            break
        @unknown default:
            break
        }
    }

    private func setPlaybackSessionActive(_ active: Bool) {
        let session = AVAudioSession.sharedInstance()
        do {
            if active {
                try session.setCategory(.playback, mode: .default)
                try session.setActive(true)
            } else {
                try session.setActive(false, options: .notifyOthersOnDeactivation)
            }
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[QVoiceiOSApp] Audio session \(active ? "activate" : "deactivate") failed: \(error.localizedDescription)")
            }
        }
    }

    private func releaseRuntime(reason: String) {
        let action = runtimeReleaseCoordinator.requestRelease(
            reason: reason,
            hasActiveGeneration: deps.engine?.hasActiveGeneration ?? false
        )

        switch action {
        case .none:
            break
        case .deferred:
            break
        case .execute(let executeReason, let wasDeferred):
            performRuntimeRelease(reason: executeReason, wasDeferred: wasDeferred)
        }
    }

    private func executeDeferredRuntimeReleaseIfNeeded() {
        let action = runtimeReleaseCoordinator.executeDeferredReleaseIfReady(
            hasActiveGeneration: deps.engine?.hasActiveGeneration ?? false
        )

        guard case .execute(let reason, let wasDeferred) = action else {
            return
        }

        performRuntimeRelease(reason: reason, wasDeferred: wasDeferred)
    }

    private func handleMemoryPressure(
        reason: String,
        severity: MemoryPressureSeverity = .warning
    ) {
        let action = runtimeReleaseCoordinator.requestCacheRelief(
            reason: reason,
            severity: severity,
            hasActiveGeneration: deps.engine?.hasActiveGeneration ?? false
        )

        switch action {
        case .none:
            break
        case .deferred:
            break
        case .execute(let executeReason, let cancelActiveGeneration):
            let forcedTrimLevel: NativeMemoryTrimLevel? = severity == .critical
                ? .fullUnload
                : nil
            if cancelActiveGeneration {
                performMemoryPressureReliefAfterCancellingGeneration(
                    reason: executeReason
                )
            } else {
                performMemoryPressureRelief(
                    reason: executeReason,
                    forcedTrimLevel: forcedTrimLevel
                )
            }
        }
    }

    private func executeDeferredMemoryPressureReliefIfNeeded() {
        let action = runtimeReleaseCoordinator.executeDeferredCacheReliefIfReady(
            hasActiveGeneration: deps.engine?.hasActiveGeneration ?? false
        )

        guard case .execute(let reason, _) = action else {
            return
        }

        performMemoryPressureRelief(reason: reason)
    }

    private func performMemoryPressureReliefAfterCancellingGeneration(
        reason: String
    ) {
        guard let engine = deps.engine else {
            performMemoryPressureRelief(reason: reason, forcedTrimLevel: .fullUnload)
            return
        }

        Task { @MainActor in
            let outcome = await engine.performCriticalMemoryPressureRelief(reason: reason)
            switch outcome {
            case .completed, .alreadyInFlight:
                audioPlayer.abortLivePreviewIfNeeded()
            case .cancellationFailed:
                // Stopping audible preview is safe, but engine state and MLX
                // ownership remain intact when the terminal barrier failed.
                // A later pressure observation may retry cancellation.
                audioPlayer.abortLivePreviewIfNeeded()
                engine.clearVisibleError()
            }
        }
    }

    private func performMemoryPressureRelief(
        reason: String,
        forcedTrimLevel: NativeMemoryTrimLevel? = nil
    ) {
        guard let engine = deps.engine else {
            clearNativeRuntimeCacheIfAvailable()
            return
        }

        Task { @MainActor in
            await applyMemoryPressureRelief(
                engine: engine,
                reason: reason,
                forcedTrimLevel: forcedTrimLevel
            )
        }
    }

    private func applyMemoryPressureRelief(
        engine: TTSEngineStore,
        reason: String,
        forcedTrimLevel: NativeMemoryTrimLevel? = nil
    ) async {
        let context = await engine.refreshMemoryContext(reason: reason, source: "app_pressure")
        let trimLevel = forcedTrimLevel ?? memoryBudgetPolicy.trimLevelForPressureEvent(
            context: context,
            isBackgroundTransition: false
        )
        await engine.trimMemory(level: trimLevel, reason: reason)
        if trimLevel == .fullUnload {
            audioPlayer.abortLivePreviewIfNeeded()
            engine.clearGenerationActivity()
        }
        if TelemetryGate.resolvedEnabled {
            print("[QVoiceiOSApp] Applied \(trimLevel.rawValue) due to \(reason)")
        }
    }

    private func configureNativeRuntimeMemoryCacheIfNeeded() {
        NativeMemoryPolicyResolver.apply(
            NativeMemoryPolicyResolver.policy(
                deviceClass: .iPhonePro,
                mode: .custom,
                isBatch: false
            )
        )
    }

    private func clearNativeRuntimeCacheIfAvailable() {
        Memory.clearCache()
    }

    private func performRuntimeRelease(reason: String, wasDeferred: Bool) {
        guard let engine = deps.engine else { return }
        Task { @MainActor in
            defer {
                let followUpAction = runtimeReleaseCoordinator.completeRelease(
                    hasActiveGeneration: engine.hasActiveGeneration
                )
                if case .execute(let nextReason, let nextWasDeferred) = followUpAction {
                    performRuntimeRelease(reason: nextReason, wasDeferred: nextWasDeferred)
                }
            }

            await engine.cancelClonePreparationIfNeeded()
            if engine.hasActiveGeneration {
                do {
                    try await engine.cancelActiveGeneration()
                } catch {
                    engine.clearVisibleError()
                }
            }
            do {
                try await engine.unloadModel()
            } catch {
                engine.clearVisibleError()
            }
            audioPlayer.abortLivePreviewIfNeeded()
            engine.clearGenerationActivity()
            if TelemetryGate.resolvedEnabled {
                print("[QVoiceiOSApp] Released runtime due to \(reason)")
            }
        }
    }

    private func setupAppSupport() {
        let fileManager = FileManager.default
        let outputSubdirectories = Set(TTSModel.all.map(\.outputSubfolder))
        let directories = [
            AppPaths.appSupportDir,
            AppPaths.modelsDir,
            AppPaths.modelDownloadRootDir,
            AppPaths.modelDownloadStagingDir,
            AppPaths.outputsDir,
            AppPaths.voicesDir,
            AppPaths.appSupportDir.appendingPathComponent("cache", isDirectory: true),
            AppPaths.importedReferenceAudioDir,
            AppPaths.preparedAudioDir,
            AppPaths.normalizedCloneReferenceDir,
            AppPaths.streamSessionsDir,
            AppPaths.nativeMLXCacheDir,
        ] + outputSubdirectories.sorted().map {
            AppPaths.outputsDir.appendingPathComponent($0, isDirectory: true)
        }

        for directory in directories {
            try? fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        }

        try? IOSModelDeliverySupport.excludeFromBackup(AppPaths.modelsDir)
        try? IOSModelDeliverySupport.excludeFromBackup(AppPaths.modelDownloadRootDir)
        try? IOSModelDeliverySupport.excludeFromBackup(AppPaths.modelDownloadStagingDir)
        // Regenerable intermediates (prepared/normalized audio, stream sessions, MLX
        // cache, imported-reference staging) must not bloat the user's iCloud backup.
        // User content — outputs/, voices/, history.sqlite — stays backed up.
        try? IOSModelDeliverySupport.excludeFromBackup(
            AppPaths.appSupportDir.appendingPathComponent("cache", isDirectory: true)
        )
    }

    private func configureAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default)
            try session.setActive(true)
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[QVoiceiOSApp] Failed to configure audio session: \(error.localizedDescription)")
            }
        }
    }
}
