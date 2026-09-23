import Foundation
import QwenVoiceCore

/// In-process engine host for the macOS app (maintainer decision 2026-09-14,
/// plan `macos-ios-convergence-2026-09`): the same shape as
/// `IOSAppBootstrap.makeBackend` and the CLI's `CLIRuntime.bootstrap` — the
/// bundled contract becomes a platform-expanded registry, `NativeRuntimeFactory`
/// builds `MLXTTSEngine` in this process, and the shared `TTSEngineStore` wraps
/// it. There is no separate engine process any more: crash isolation is gone
/// with it, and memory relief comes from the engine's own kernel-pressure
/// responder, the store's footprint bands (`MacMemoryBudgetPolicy`) and the
/// per-tier idle unload in `NativeMemoryPolicyResolver`.
@MainActor
enum MacEngineBootstrap {
    enum BootstrapError: LocalizedError {
        case manifestMissing

        var errorDescription: String? {
            switch self {
            case .manifestMissing:
                return "qwenvoice_contract.json is not in the application bundle."
            }
        }
    }

    static func makeEngineStore() throws -> TTSEngineStore {
        guard let manifestURL = TTSContract.manifestURL else {
            throw BootstrapError.manifestMissing
        }
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
        // Same tiered prewarm policy the retired XPC host used: defer the
        // dedicated custom prewarm on the 8 GB floor tier (the work folds into
        // the first generation); machines with headroom keep `.eager`.
        let customPrewarmPolicy: NativeCustomPrewarmPolicy =
            deviceClass == .floor8GBMac ? .skipDedicatedCustomPrewarm : .eager
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: AppPaths.appSupportDir),
            storeVersionSeed: storeVersionSeed(),
            customPrewarmPolicy: customPrewarmPolicy
        )
        return TTSEngineStore(
            backend: AnyTTSEngineBackend(
                engine: runtime.engine,
                supportsSavedVoiceMutation: true,
                supportsModelManagementMutation: true,
                supportedModes: [.custom, .design, .clone],
                // PA-17: the visible Settings acknowledgment (`@AppStorage` in
                // `AppDefaults.store`) is the recorded consent the core enforces;
                // the refusal names the Mac's Settings → Voice cloning section.
                voiceCloningConsent: {
                    VoiceCloningConsentPolicy(
                        defaults: AppDefaults.store,
                        refusalCopy: MacInterfaceText.voiceCloningConsentRefusalCopy
                    )
                }
            ),
            memoryBudgetPolicy: MacMemoryBudgetPolicy.policy(for: deviceClass)
        )
    }

    /// Identity of the model asset store's verification cache. Changing it
    /// re-verifies installed artifacts once (digests, never a re-download).
    static func storeVersionSeed(bundle: Bundle = .main) -> String {
        let bundleIdentifier = bundle.bundleIdentifier ?? "com.qwenvoice.app"
        let marketingVersion = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        let buildVersion = bundle.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String ?? "0"
        return "\(bundleIdentifier)|\(marketingVersion)|\(buildVersion)"
    }
}

/// Memory budget bands for the shared store on a Mac. The headroom thresholds
/// are inert here (`os_proc_available_memory` is iOS-only, so the snapshot's
/// headroom falls back to total RAM minus footprint and stays far above them);
/// the live criteria are the process footprint against physical RAM and the
/// Metal working-set ratio. `highMemoryMac` keeps only the GPU criterion, like
/// its resolver policy keeps no idle unload.
enum MacMemoryBudgetPolicy {
    static func policy(
        for deviceClass: NativeDeviceMemoryClass,
        physicalMemory: UInt64 = ProcessInfo.processInfo.physicalMemory
    ) -> IOSMemoryBudgetPolicy {
        let healthyHeadroom: UInt64 = 768 * 1_048_576
        let guardedHeadroom: UInt64 = 384 * 1_048_576
        switch deviceClass {
        case .highMemoryMac:
            return IOSMemoryBudgetPolicy(
                healthyHeadroomBytes: healthyHeadroom,
                guardedHeadroomBytes: guardedHeadroom,
                criticalGPUWorkingSetUsageRatio: 0.90
            )
        default:
            return IOSMemoryBudgetPolicy(
                healthyHeadroomBytes: healthyHeadroom,
                guardedHeadroomBytes: guardedHeadroom,
                criticalGPUWorkingSetUsageRatio: 0.85,
                aggregateGuardedFootprintBytes: physicalMemory / 100 * 55,
                aggregateCriticalFootprintBytes: physicalMemory / 100 * 72
            )
        }
    }
}
