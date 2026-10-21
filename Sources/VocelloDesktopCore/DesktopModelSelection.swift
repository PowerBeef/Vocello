import Foundation
import QwenVoiceCore

/// Which model package each mode uses, resolved the way the Mac app resolves
/// it (`MacModelVariantResolution`): the explicit per-mode choice, then the
/// lower-memory preference, then this Mac's hardware recommendation, then
/// picker order; generation falls back to the first installed package.
public enum DesktopModelSelection {
    public struct Choice: Encodable, Sendable, Equatable {
        public let mode: String
        /// The package the app selects for the mode, installed or not.
        public let activeVariant: String?
        public let activeModelID: String?
        /// Why: explicit, prefer-lower-memory, hardware or picker-order.
        public let source: String
        public let activeInstalled: Bool
        /// The package a take uses now: the active one if installed, else the
        /// first installed package in the same order; nil when none is installed.
        public let generationVariant: String?
        public let generationModelID: String?
        public let explicitVariant: String?
        public let hardwareRecommendedVariant: String?
        public let variants: [String]
    }

    public static func resolve(
        registry: ContractBackedModelRegistry,
        explicitVariantID: (GenerationMode) -> String?,
        prefersLowerMemory: Bool,
        deviceClass: NativeDeviceMemoryClass,
        isInstalled: (String) -> Bool
    ) -> [Choice] {
        GenerationMode.allCases.compactMap { mode in
            guard let base = registry.model(for: mode) else { return nil }
            let variants = base.platformVariants(for: .macOS).sorted { order($0.kind) < order($1.kind) }
            let ids = variants.map(\.id)
            let recommended = hardwareOrder(deviceClass).lazy.compactMap { kind in variants.first { $0.kind == kind } }.first
                ?? variants.first
            let explicit = explicitVariantID(mode)
            let resolution = MacModelVariantResolution(
                variantIDs: ids,
                explicitVariantID: explicit,
                prefersLowerMemory: prefersLowerMemory,
                lowerMemoryVariantID: variants.first { $0.kind == .speed }?.id,
                hardwareRecommendedVariantID: recommended?.id
            )
            func modelID(_ variantID: String?) -> String? {
                variantID.flatMap { id in variants.first { $0.id == id } }.map { base.variantScopedID(for: $0) }
            }
            let active = resolution.activeVariantID
            let source: String
            if let explicit, ids.contains(explicit), active == explicit {
                source = "explicit"
            } else if prefersLowerMemory, active == resolution.lowerMemoryVariantID {
                source = "prefer-lower-memory"
            } else if active == resolution.hardwareRecommendedVariantID {
                source = "hardware"
            } else {
                source = "picker-order"
            }
            let activeInstalled = modelID(active).map(isInstalled) ?? false
            let generation = activeInstalled
                ? active
                : resolution.installedFallbackVariantID { modelID($0).map(isInstalled) ?? false }
            return Choice(
                mode: mode.rawValue, activeVariant: active, activeModelID: modelID(active), source: source,
                activeInstalled: activeInstalled, generationVariant: generation, generationModelID: modelID(generation),
                explicitVariant: explicit, hardwareRecommendedVariant: recommended?.id, variants: ids
            )
        }
    }

    /// The app's picker order (`TTSModelVariantKind.allCases`).
    static func order(_ kind: ModelVariantKind) -> Int {
        switch kind {
        case .compactSpeed: return 0
        case .compactQuality: return 1
        case .speed: return 2
        case .quality: return 3
        }
    }

    /// The app's hardware recommendation: Speed first on the 8 GB tier, Quality first above it.
    static func hardwareOrder(_ deviceClass: NativeDeviceMemoryClass) -> [ModelVariantKind] {
        switch deviceClass {
        case .floor8GBMac, .iPhonePro: return [.speed, .quality]
        case .mid16GBMac, .highMemoryMac: return [.quality, .speed]
        }
    }
}
