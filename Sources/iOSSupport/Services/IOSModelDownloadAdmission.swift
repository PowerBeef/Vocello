import Foundation

/// Admission for iPhone model downloads (RF-19, E-01): at most `maxConcurrentModels` transfers
/// start, and one model is never prepared or started twice.
///
/// `IOSModelDownloadCoordinator.install` and `beginDownload` await the catalog and the delivery
/// plan, which hashes the 682 MB shared component on a detached task, before a model is queued
/// or recorded as running. Without a claim taken before those awaits, two quick Install taps on
/// one model prepared and queued it twice, and taps on two models started both transfers on the
/// one shared downloader, whose second run dropped the first run's continuations unresumed and
/// wedged both models. A preparing or starting model is claimed here; a queued or running one
/// is the coordinator's own state, which it passes in.
///
/// Pure: the coordinator applies the decisions, and `IOSModelDownloadAdmissionTests` pins them.
struct IOSModelDownloadAdmission: Equatable, Sendable {
    let maxConcurrentModels: Int
    /// Models whose Install is preparing a request (catalog, delivery plan, free space, ledger)
    /// that has not joined the queue yet.
    private(set) var preparingModelIDs: Set<String> = []
    /// Models taken off the queue whose transfer is not recorded as running yet.
    private(set) var startingModelIDs: Set<String> = []

    init(maxConcurrentModels: Int) {
        self.maxConcurrentModels = max(1, maxConcurrentModels)
    }

    /// Install's duplicate guard, taken before its first await. `false` means the model already
    /// has a download, queued or running (`hasDownload`) or being prepared or started, so the
    /// request is ignored.
    mutating func claimPreparation(of modelID: String, hasDownload: Bool) -> Bool {
        guard !hasDownload, !isClaimed(modelID) else { return false }
        preparingModelIDs.insert(modelID)
        return true
    }

    /// Ends a preparation claim: the request joined the queue, or preparing it failed.
    mutating func releasePreparation(of modelID: String) {
        preparingModelIDs.remove(modelID)
    }

    /// Claims the start slot for the model at the head of the queue, before the first await of
    /// its start. Starting and running transfers both count against `maxConcurrentModels`, so
    /// another start stays queued. `false` means there is no free slot.
    mutating func claimStart(of modelID: String, runningCount: Int) -> Bool {
        guard runningCount + startingModelIDs.count < maxConcurrentModels,
              !startingModelIDs.contains(modelID) else { return false }
        startingModelIDs.insert(modelID)
        return true
    }

    /// Ends a start claim: the transfer is recorded as running, or its start failed.
    mutating func releaseStart(of modelID: String) {
        startingModelIDs.remove(modelID)
    }

    /// Whether the model is being prepared or started.
    func isClaimed(_ modelID: String) -> Bool {
        preparingModelIDs.contains(modelID) || startingModelIDs.contains(modelID)
    }
}
