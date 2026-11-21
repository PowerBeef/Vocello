import AVFoundation
import Combine
import MLX
import SwiftUI
import UIKit
import QwenVoiceCore
import VocelloiOSPolicies

/// Builds the app's dependencies (PA-21, AUD-01, IOS-06).
///
/// The storage-protection pass walks the whole App Group tree, so it runs off the main
/// actor; the registry, engine store and installer are created on the main actor only
/// after it has finished, as the immutable model-file metadata window requires. A
/// failure is shown with Retry instead of ending the session: `IOSStartupRunner` owns
/// the pass, so Retry starts one only after a failure.
@MainActor
final class IOSAppDependenciesContainer: nonisolated ObservableObject {
    struct Dependencies {
        let registry: ContractBackedModelRegistry
        let engine: TTSEngineStore
        let modelManager: ModelManagerViewModel
        let modelInstaller: IOSModelInstallerViewModel
    }

    private let startup: IOSStartupRunner<Dependencies>
    /// Bumped before every startup change. Combine keeps the synthesized
    /// `objectWillChange` in a `@Published` property, so without one the
    /// container's computed state would never reach SwiftUI (AUD-01).
    @Published private var revision = 0

    var registry: ContractBackedModelRegistry? { startup.dependencies?.registry }
    var engine: TTSEngineStore? { startup.dependencies?.engine }
    var modelManager: ModelManagerViewModel? { startup.dependencies?.modelManager }
    var modelInstaller: IOSModelInstallerViewModel? { startup.dependencies?.modelInstaller }
    var startupError: Error? { startup.error }
    var isStarting: Bool { startup.attempt.isStarting }

    init() {
        startup = IOSStartupRunner(operation: Self.makeDependencies)
        startup.willChange = { [weak self] in self?.revision &+= 1 }
        startup.start()
    }

    /// Runs startup again after a failure. Ignored while a pass is running or
    /// once the dependencies exist.
    func retry() {
        startup.start()
    }

    /// AUD-01 device proof: the registered internal-diagnostics knob
    /// `QVOICE_IOS_FORCE_STARTUP_FAILURE_ONCE` fails the first pass of the process
    /// before it touches anything, so a phone run can prove Retry. Distribution
    /// builds compile the knob out (`RuntimeDebugGate`).
    private static var forcedStartupFailurePending: Bool = {
        let raw = RuntimeDebugGate.value(for: "QVOICE_IOS_FORCE_STARTUP_FAILURE_ONCE")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return ["1", "true", "yes", "on"].contains(raw ?? "")
    }()

    private struct ForcedStartupFailure: LocalizedError {
        var errorDescription: String? { "Startup failed on purpose (internal diagnostics)." }
    }

    private static func makeDependencies() async throws -> Dependencies {
        if forcedStartupFailurePending {
            forcedStartupFailurePending = false
            throw ForcedStartupFailure()
        }
        let protection = await Task.detached(priority: .userInitiated) { @concurrent in
            // MAC-25 on the iPhone: reference clips an earlier launch recorded
            // (a crash or jetsam kill stranded them) go before any sheet can
            // record again. One app process owns this temporary directory.
            ReferenceClipRecordingStash.removeLeftoverRecordings(
                anotherCopyIsRunning: false,
                ownerHasEnded: { _ in true }
            )
            return Result<IOSStorageProtectionPolicy.ApplyReport, any Error> {
                try IOSStorageProtectionPolicy.apply(at: AppPaths.appSupportDir)
            }
        }.value
        let report = try protection.get()
        if report.descendantFailureCount > 0, TelemetryGate.resolvedEnabled {
            print("[bootstrap] storage protection left \(report.descendantFailureCount) file(s) for the next launch")
        }
        let registry = try TTSContract.loadRegistry()
        let documentIO = LocalDocumentIO(importedReferenceDirectory: AppPaths.importedReferenceAudioDir)
        let selectedBackend = try QVoiceiOSApp.makeBackend(
            registry: registry,
            documentIO: documentIO
        )
        let installer = selectedBackend.modelInstaller
        IOSModelDeliveryBackgroundEventRelay.handler = { identifier, completionHandler in
            _ = installer.handleBackgroundEventsCompletion(identifier, completionHandler)
        }
        return Dependencies(
            registry: registry,
            engine: selectedBackend.engineStore,
            modelManager: selectedBackend.modelManager,
            modelInstaller: installer
        )
    }
}

extension QVoiceiOSApp {
    static func modelAssetStoreSeed(bundle: Bundle = .main) -> String {
        let bundleIdentifier = bundle.bundleIdentifier ?? "com.patricedery.vocello"
        let marketingVersion = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        let buildVersion = bundle.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String ?? "0"
        return "\(bundleIdentifier)|\(marketingVersion)|\(buildVersion)"
    }

    struct SelectedBackend {
        let engineStore: TTSEngineStore
        let modelManager: ModelManagerViewModel
        let modelInstaller: IOSModelInstallerViewModel
    }

    private enum IOSBackendBootstrapError: LocalizedError {
        case missingSharedContainer(String)

        var errorDescription: String? {
            switch self {
            case .missingSharedContainer(let appGroupIdentifier):
                return """
                Vocello needs an App Group shared container for on-device storage (models, history, voices).
                The TTS engine runs in-process in this app — there is no separate engine extension.
                Add \(appGroupIdentifier) to the VocelloiOS target entitlements and provisioning profile, then rebuild.
                """
            }
        }
    }

    /// Minimum **entitled per-app memory budget** to load the clone/speaker encoders
    /// in-process. Derived directly from `IOSMemoryBudgetPolicy.iPhoneShippingDefault`
    /// (`minimumCloneCapableProcessLimitBytes()`, `4,779 MiB` / ~`5.01 GB`, RB-05)
    /// so hybrid Clone (~`3,500 MiB` working peak: 3.0's ~`3,332 MiB` + ~`168 MiB`
    /// hybrid attention delta) stays strictly below the policy's proportionally scaled
    /// `.guarded` footprint band and well below `.critical` auto-cancellation. Entitled
    /// 8 GB and 12 GB iPhones with `increased-memory-limit` (Game Mode off) are
    /// typically granted ~`6,144 MiB` (and the conservative `iphone15pro` floor profile
    /// is `5,000 MiB`), so Clone stays enabled on entitled 8 GB+ devices while
    /// self-disabling if a device's dynamic budget drops too low. (Runtime priming is
    /// separately gated on the healthy memory band in
    /// `TTSEngineStore.ensureCloneReferencePrimed`.)
    static let cloneCapableMinimumProcessLimitBytes: UInt64 =
        IOSMemoryBudgetPolicy.iPhoneShippingDefault.minimumCloneCapableProcessLimitBytes()

    /// `.fullCapabilities` (clone enabled) when the measured entitled per-app limit clears
    /// the threshold, else the memory-conscious `.iOSProductionDefault`. Read once at
    /// launch — footprint is tiny then, so `impliedProcessLimitBytes`
    /// (= `phys_footprint` + `os_proc_available_memory()`) ≈ the full granted ceiling.
    static func cloneCapableLoadProfile() -> NativeQwenPreparedLoadProfile {
        let limitBytes = IOSMemorySnapshot.capture(role: .app).impliedProcessLimitBytes ?? 0
        let enabled = limitBytes >= cloneCapableMinimumProcessLimitBytes
        if TelemetryGate.resolvedEnabled {
            print("[bootstrap] clone gate: entitled per-app limit ≈ \(limitBytes / 1_048_576) MB → "
                  + (enabled ? "fullCapabilities (clone ON)" : "withoutCloneEncoders (clone OFF)"))
        }
        return enabled ? .fullCapabilities : .iOSProductionDefault
    }

    static func makeBackend(
        registry: ContractBackedModelRegistry,
        documentIO: LocalDocumentIO
    ) throws -> SelectedBackend {
        // MARK: Engine selection
        // An IN-PROCESS `MLXTTSEngine` (via `NativeRuntimeFactory`, the same path
        // the macOS `vocello` CLI uses). It used to drive the out-of-process
        // `VocelloEngineExtension`, but that ExtensionKit non-UI extension is capped
        // at a tiny per-process memory limit the increased-memory entitlement does
        // NOT raise — iOS jetsam-killed it (per-process-limit) while loading the
        // model. The app process *does* get the entitlement's raised limit, so
        // generation runs in-process here, wrapped in `TTSEngineStore`. The iOS
        // Simulator is intentionally unsupported (the project is on-device only).

        guard AppPaths.hasUsableStorageRoot(
            environment: ProcessInfo.processInfo.environment,
            sharedContainerAvailable: AppPaths.isUsingSharedContainer
        ) else {
            throw IOSBackendBootstrapError.missingSharedContainer(
                AppPaths.sharedAppGroupIdentifier
            )
        }

        let modelAssetStore = LocalModelAssetStore(
            modelRegistry: registry,
            rootDirectory: AppPaths.modelsDir,
            storeVersionSeed: modelAssetStoreSeed()
        )
        // RF-59 internal-diagnostics isolated-root fixture seeding (no-op in
        // distribution builds and whenever QVOICE_APP_SUPPORT_DIR is not an isolated child).
        let seedResult = IOSModelUpdateAutoStartPolicy.seedRetiredModelsIfConfigured(
            modelsDirectory: AppPaths.modelsDir,
            allowedRetiredFolders: Set(registry.models.flatMap(\.retiredFolders))
        )
        if seedResult.shouldClearConsent {
            IOSAppDefaults.modelUpdateConsentedArtifacts = []
        }
        // RF-59: records which modes an earlier Vocello installed (a few small files, never model
        // weights) before the first statuses, so those modes read "Update Required"; then, off the
        // launch path, every retired Speed folder goes once any new model verifies.
        _ = try? modelAssetStore.reconcileModelUpdatePlan()
        // Holds background time: the reclaim takes file locks, also on a background relaunch for
        // a download session's events.
        Task {
            await IOSBackgroundTime.hold("vocello.model-update.launch-reclaim") {
                _ = await Task.detached(priority: .utility) { @concurrent in
                    modelAssetStore.reclaimRetiredFolders()
                }.value
            }
        }

        let modelManager = ModelManagerViewModel(
            modelRegistry: registry,
            modelAssetStore: modelAssetStore
        )
        // In-process engine in the APP process (mirrors the macOS CLI's
        // NativeRuntimeFactory path). The load profile is RAM-gated (see
        // `cloneCapableLoadProfile`): high-RAM iPhones load `.fullCapabilities` (clone
        // encoders, so Voice Cloning works in-process); everyone else keeps the
        // memory-conscious `.iOSProductionDefault` (= withoutCloneEncoders).
        // `.skipDedicatedCustomPrewarm` avoids a prewarm memory spike. Models resolve
        // from the same shared-container `models/` dir the user already downloaded into.
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: AppPaths.appSupportDir),
            storeVersionSeed: modelAssetStoreSeed(),
            customPrewarmPolicy: .skipDedicatedCustomPrewarm,
            qwenPreparedLoadProfile: cloneCapableLoadProfile()
        )
        let engine = runtime.engine
        // PA-20: errors the engine surfaces read catalog copy in the interface language.
        engine.visibleErrorDescription = { IOSAppLanguage.shared.presentation.generationFailureMessage($0) }
        let engineStore = TTSEngineStore(
            backend: AnyTTSEngineBackend(
                engine: engine,
                supportsSavedVoiceMutation: true,
                supportsModelManagementMutation: true,
                supportedModes: [.custom, .design, .clone],
                // PA-17: the visible Settings acknowledgment (`@AppStorage` in
                // `.standard`) is the recorded consent the core enforces.
                voiceCloningConsent: {
                    VoiceCloningConsentPolicy(
                        defaults: .standard,
                        refusalCopy: IOSAppLanguage.shared.presentation.voiceCloningConsentRefusalCopy
                    )
                }
            )
        )
        // A5-01: removing a model coordinates with the engine, as on macOS. An
        // install never preloads its model: warms follow Studio intent (AUD-10).
        let modelInstaller = IOSModelInstallerViewModel(
            modelAssetStore: modelAssetStore,
            modelManager: modelManager,
            engine: engineStore
        )
        return SelectedBackend(
            engineStore: engineStore,
            modelManager: modelManager,
            modelInstaller: modelInstaller
        )
    }
}

enum IOSDeviceSupport {
    static var isSupportedHardware: Bool {
        IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier(machineIdentifier())
    }

    /// Shown on hardware the guard refuses, including the iPads that can install the app (RF-42).
    @MainActor static var unsupportedReason: String {
        IOSInterfaceText.unsupportedDeviceDetail(IOSDeviceEligibilityPolicy.minimumHardwareModel)
    }

    private static func machineIdentifier() -> String {
        var systemInfo = utsname()
        unsafe uname(&systemInfo)
        return withValuePointer(to: &systemInfo.machine) { pointer in
            unsafe pointer.withMemoryRebound(to: CChar.self, capacity: 1) {
                unsafe String(cString: $0)
            }
        }
    }
}

/// Shown while startup runs: the launch mark, so the transition from the launch
/// screen reads as one step.
struct IOSStartupProgressView: View {
    var body: some View {
        ZStack {
            Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255)
                .ignoresSafeArea()
            VStack(spacing: 24) {
                Image("VocelloLaunchLogo")
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 200)
                    .accessibilityHidden(true)
                ProgressView()
            }
        }
    }
}

/// Startup failed (AUD-01): say so and offer Retry instead of a dead end.
struct IOSStartupFailureView: View {
    let error: Error
    let isRetrying: Bool
    let onRetry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .resizable()
                .scaledToFit()
                .frame(width: 64, height: 64)
                .foregroundColor(.orange)
                .accessibilityHidden(true)
            Text(IOSInterfaceText.initializationFailed)
                .font(.title2.bold())
            Text(Self.message(for: error))
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal)
            Button(IOSInterfaceText.retry, action: onRetry)
                .iosAdaptiveUtilityButtonStyle(tint: Theme.Brand.gold)
                .disabled(isRetrying)
                .accessibilityIdentifier("startup_retryButton")
        }
        .padding()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("startup_errorState")
    }

    /// A restore failure carries no path (privacy) and no user-facing text of its own.
    private static func message(for error: Error) -> String {
        error is IOSStorageProtectionPolicy.ModeRestoreFailure
            ? IOSInterfaceText.storageProtectionRestoreFailed
            : error.localizedDescription
    }
}

struct IOSUnsupportedDeviceView: View {
    let reason: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "iphone.slash")
                .font(.system(size: 40, weight: .semibold))
                .foregroundStyle(.orange)
            Text(IOSInterfaceText.unsupportedDevice)
                .font(.title2.weight(.semibold))
            Text(reason)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal)
        }
        .padding(32)
    }
}
