import AVFoundation
import MLX
import SwiftUI
import UIKit
import QwenVoiceCore

@MainActor
final class IOSAppDependenciesContainer: ObservableObject {
    let registry: ContractBackedModelRegistry?
    let documentIO: LocalDocumentIO?
    let engine: TTSEngineStore?
    let modelManager: ModelManagerViewModel?
    let modelInstaller: IOSModelInstallerViewModel?
    let startupError: Error?

    init() {
        do {
            try IOSStorageProtectionPolicy.apply(at: AppPaths.appSupportDir)
            let registry = try TTSContract.loadRegistry()
            let documentIO = LocalDocumentIO(importedReferenceDirectory: AppPaths.importedReferenceAudioDir)
            let selectedBackend = try QVoiceiOSApp.makeBackend(
                registry: registry,
                documentIO: documentIO
            )
            let installer = selectedBackend.modelInstaller
            self.registry = registry
            self.documentIO = documentIO
            self.engine = selectedBackend.engineStore
            self.modelManager = selectedBackend.modelManager
            self.modelInstaller = installer
            IOSModelDeliveryBackgroundEventRelay.handler = { identifier, completionHandler in
                _ = installer.handleBackgroundEventsCompletion(identifier, completionHandler)
            }
            self.startupError = nil
        } catch {
            self.registry = nil
            self.documentIO = nil
            self.engine = nil
            self.modelManager = nil
            self.modelInstaller = nil
            self.startupError = error
        }
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
    /// in-process. Clone (`.fullCapabilities`) keeps those encoders resident for the whole
    /// session (~0.6 GB) on top of the ~2.3 GB model + a ~0.4 GB priming spike (~3.3 GB
    /// peak). The `increased-memory-limit` entitlement raises the per-app Jetsam budget
    /// (NOT total RAM): ~50% of RAM default → ~75% entitled (community-measured; Apple
    /// publishes no exact figure). So 8 GB iPhones (15/16/17, all Pro) get ~5–5.5 GB and
    /// 12 GB (17 Pro / Air) ~8–8.5 GB — clone fits on *every entitled* device. 4.5 GB
    /// clears the 3.3 GB peak + ~1.2 GB working headroom and aligns with the policy's
    /// 4.5 GB guarded / 5.2 GB critical footprint thresholds; it self-disables if a
    /// device's real budget is too low. (Runtime priming is separately gated on the
    /// healthy memory band in `TTSEngineStore.ensureCloneReferencePrimed`.)
    static let cloneCapableMinimumProcessLimitBytes: UInt64 = 4_500_000_000

    /// `.fullCapabilities` (clone enabled) when the measured entitled per-app limit clears
    /// the threshold, else the memory-conscious `.iOSProductionDefault`. Read once at
    /// launch — footprint is tiny then, so `impliedProcessLimitBytes`
    /// (= `phys_footprint` + `os_proc_available_memory()`) ≈ the full granted ceiling.
    static func cloneCapableLoadProfile() -> NativeQwenPreparedLoadProfile {
        let limitBytes = IOSMemorySnapshot.capture(role: .app).impliedProcessLimitBytes ?? 0
        let enabled = limitBytes >= cloneCapableMinimumProcessLimitBytes
        print("[bootstrap] clone gate: entitled per-app limit ≈ \(limitBytes / 1_048_576) MB → "
              + (enabled ? "fullCapabilities (clone ON)" : "withoutCloneEncoders (clone OFF)"))
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

        guard AppPaths.isUsingSharedContainer else {
            throw IOSBackendBootstrapError.missingSharedContainer(
                AppPaths.sharedAppGroupIdentifier
            )
        }

        let modelAssetStore = LocalModelAssetStore(
            modelRegistry: registry,
            rootDirectory: AppPaths.modelsDir,
            storeVersionSeed: modelAssetStoreSeed()
        )

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
        let engineStore = TTSEngineStore(
            backend: AnyTTSEngineBackend(
                engine: engine,
                supportsSavedVoiceMutation: true,
                supportsModelManagementMutation: true,
                supportedModes: [.custom, .design, .clone]
            )
        )
        let modelInstaller = IOSModelInstallerViewModel(
            modelAssetStore: modelAssetStore,
            modelManager: modelManager
        )
        modelInstaller.onModelInstalled = nil
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

    static var unsupportedReason: String {
        let identifier = machineIdentifier()
        return "Vocello for iPhone currently requires \(IOSDeviceEligibilityPolicy.minimumHardwareDescription).\nCurrent device: \(identifier)"
    }

    private static func machineIdentifier() -> String {
        var systemInfo = utsname()
        uname(&systemInfo)
        return withUnsafePointer(to: &systemInfo.machine) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: 1) {
                String(cString: $0)
            }
        }
    }
}

struct IOSUnsupportedDeviceView: View {
    let reason: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "iphone.slash")
                .font(.system(size: 40, weight: .semibold))
                .foregroundStyle(.orange)
            Text("Unsupported Device")
                .font(.title2.weight(.semibold))
            Text(reason)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal)
        }
        .padding(32)
    }
}
