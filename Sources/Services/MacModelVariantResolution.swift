import Foundation

/// Which model package a macOS generation mode uses, resolved from plain values
/// so the order is testable without the app, the model catalog or
/// `UserDefaults`. `ModelManagerViewModel` builds one per lookup.
///
/// Order, most preferred first:
/// 1. the stored explicit per-mode choice, so a user's pick is never overridden;
/// 2. the mode's Speed package when "Prefer lower-memory models" is on;
/// 3. the hardware recommendation for this Mac;
/// 4. the remaining packages in picker order.
///
/// The installed fallback walks the same order and takes the first installed
/// package. Candidates that are not one of the mode's packages are skipped.
/// Turning the preference on clears the stored choices, so every mode resolves
/// to Speed at that moment and later explicit picks win again.
struct MacModelVariantResolution: Equatable, Sendable {
    /// The mode's package variant IDs, in picker order.
    let variantIDs: [String]
    /// The stored explicit per-mode choice, if the user made one.
    let explicitVariantID: String?
    /// The "Prefer lower-memory models" setting.
    let prefersLowerMemory: Bool
    /// The mode's Speed (lower-memory) package, if the catalog has one.
    let lowerMemoryVariantID: String?
    /// The package recommended for this Mac's memory tier.
    let hardwareRecommendedVariantID: String?

    init(
        variantIDs: [String],
        explicitVariantID: String?,
        prefersLowerMemory: Bool,
        lowerMemoryVariantID: String?,
        hardwareRecommendedVariantID: String?
    ) {
        self.variantIDs = variantIDs
        self.explicitVariantID = explicitVariantID
        self.prefersLowerMemory = prefersLowerMemory
        self.lowerMemoryVariantID = lowerMemoryVariantID
        self.hardwareRecommendedVariantID = hardwareRecommendedVariantID
    }

    /// Every package of the mode, most preferred first, without duplicates.
    var preferenceOrder: [String] {
        let preferred = [
            explicitVariantID,
            prefersLowerMemory ? lowerMemoryVariantID : nil,
            hardwareRecommendedVariantID,
        ].compactMap { $0 }
        var ordered: [String] = []
        for candidate in preferred + variantIDs
        where variantIDs.contains(candidate) && !ordered.contains(candidate) {
            ordered.append(candidate)
        }
        return ordered
    }

    /// The package the mode uses when installation is not considered.
    var activeVariantID: String? {
        preferenceOrder.first
    }

    /// The first package in resolution order that is installed.
    func installedFallbackVariantID(isInstalled: (String) -> Bool) -> String? {
        preferenceOrder.first(where: isInstalled)
    }

    /// The installed package that should replace the stored explicit choice,
    /// or nil when nothing should be stored: there is no explicit choice, it is
    /// installed, or it names a retired or unknown package. Only a known but
    /// uninstalled explicit choice is replaced, so an automatic fallback is
    /// never saved as if the user had picked it.
    func fallbackReplacingExplicitChoice(isInstalled: (String) -> Bool) -> String? {
        guard let explicitVariantID,
              variantIDs.contains(explicitVariantID),
              !isInstalled(explicitVariantID) else {
            return nil
        }
        return installedFallbackVariantID(isInstalled: isInstalled)
    }
}
