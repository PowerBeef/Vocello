import Foundation

/// The free space a model transfer needs, one rule for both apps' delivery and the RF-59 update's
/// launch checks: twice the bytes still to fetch (staged, then installed), never less than the bytes
/// plus a 256 MB margin.
public enum ModelDeliverySpace {
    public static func minimumFreeBytes(forFetching requiredBytes: Int64) -> Int64 {
        max(requiredBytes * 2, requiredBytes + Int64(256 * 1_024 * 1_024))
    }

    /// The space available for important use on the volume holding `url`, when the system says.
    public static func availableBytes(at url: URL) -> Int64? {
        (try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
            .volumeAvailableCapacityForImportantUsage).map { Int64($0) }
    }
}

/// RF-59: the Mac's decision for the model update after an app update from an earlier Vocello, at
/// launch and on the user's Update. At launch it starts without asking on an unmetered network (the
/// iPhone asks first: `IOSModelUpdateAutoStartPolicy`); a mode the user stopped, one whose last
/// attempt failed (it waits for the user's Update) or one already downloading is left as it is. When
/// the disk lacks the room for the downloads that run at once, or a download already failed for want
/// of space, while earlier models hold some, it offers to remove them first instead of starting a
/// download that would fail.
public enum MacModelUpdateAutoStart {
    public struct Candidate: Equatable, Sendable {
        public let modelID: String
        public let estimatedBytes: Int64
        public let paused: Bool
        public let active: Bool
        /// The class of the last attempt's failure, when it failed.
        public let failure: ModelUpdateFailure?

        public var failed: Bool { failure != nil }

        public init(modelID: String, estimatedBytes: Int64, paused: Bool, active: Bool, failure: ModelUpdateFailure?) {
            self.modelID = modelID
            self.estimatedBytes = estimatedBytes
            self.paused = paused
            self.active = active
            self.failure = failure
        }
    }

    public enum Decision: Equatable, Sendable {
        case none
        case start(modelIDs: [String])
        /// Too little room for the downloads; the earlier models can free some.
        case needsRoom(modelIDs: [String])
    }

    /// `concurrentDownloads`: how many downloads run at once, so the space check covers them all.
    /// The user's Update (`userInitiated`) resumes stopped and failed modes and needs no unmetered
    /// network; a launch starts only the others, on one.
    public static func decide(
        candidates: [Candidate],
        userInitiated: Bool = false,
        networkAllowsAutomaticDownloads: Bool,
        availableBytes: Int64?,
        holdsEarlierModels: Bool,
        concurrentDownloads: Int = 1
    ) -> Decision {
        let idle = candidates.filter { !$0.active }
        let open = userInitiated ? idle : idle.filter { !$0.paused }
        let ready = userInitiated ? open : open.filter { !$0.failed }
        let failedForSpace = open.filter { $0.failure == .space }
        let firstWave = ready.map(\.estimatedBytes).sorted(by: >).prefix(max(1, concurrentDownloads)).reduce(0, +)
        let roomForFirstWave = availableBytes.map {
            $0 >= ModelDeliverySpace.minimumFreeBytes(forFetching: firstWave)
        } ?? true
        if holdsEarlierModels, !failedForSpace.isEmpty || (!ready.isEmpty && !roomForFirstWave) {
            return .needsRoom(modelIDs: open.filter { ready.contains($0) || $0.failure == .space }.map(\.modelID))
        }
        guard !ready.isEmpty, userInitiated || networkAllowsAutomaticDownloads else { return .none }
        // The user's Update starts even short of room: nothing on the disk can make more.
        return roomForFirstWave || userInitiated ? .start(modelIDs: ready.map(\.modelID)) : .none
    }
}

/// RF-59: what the model update banner shows on either app, from the plan and the downloads.
public enum ModelUpdateBannerState: Equatable, Sendable {
    /// The update runs: the modes updated since launch, of those plus the ones still updating.
    case updating(completed: Int, total: Int, fraction: Double)
    /// The update has not started, or its last attempt failed: the banner offers it.
    case needed
    /// The disk lacks the room; the banner offers to remove the earlier models first.
    case needsRoom
    /// Every mode is updated; the earlier models freed this much.
    case done(freedBytes: Int64)

    /// A mode whose model still needs its update.
    public struct Remaining: Equatable, Sendable {
        public let paused: Bool
        public let active: Bool
        /// The running download's share done, when known.
        public let fraction: Double?

        public init(paused: Bool, active: Bool, fraction: Double?) {
            self.paused = paused
            self.active = active
            self.fraction = fraction
        }
    }

    /// Nothing while every remaining mode was stopped by the user: the rows and Studio still offer
    /// the update, but the banner no longer asks. `sessionModeCount` is the plan's size at launch.
    public static func derive(
        remaining: [Remaining],
        sessionModeCount: Int,
        completionFreedBytes: Int64?,
        needsRoom: Bool
    ) -> ModelUpdateBannerState? {
        if let freed = completionFreedBytes { return .done(freedBytes: freed) }
        guard !remaining.isEmpty else { return nil }
        let running = remaining.filter(\.active)
        guard !running.isEmpty else {
            // Every remaining mode stopped (Not Now): the banner no longer asks, room or not.
            guard remaining.contains(where: { !$0.paused }) else { return nil }
            return needsRoom ? .needsRoom : .needed
        }
        let completed = max(0, sessionModeCount - remaining.count)
        let total = completed + remaining.filter { $0.active || !$0.paused }.count
        let inFlight = running.reduce(0.0) { $0 + min(1, max(0, $1.fraction ?? 0)) }
        return .updating(
            completed: completed, total: total,
            fraction: total == 0 ? 0 : min(1, (Double(completed) + inFlight) / Double(total))
        )
    }
}

/// RF-59: when the pins `removeRetiredFoldersBeforeUpdate` made may go. They serve the removal
/// itself and the update downloads after it, a setup still waiting to start them included; a
/// release during the removal would let it prune the blobs the new models reuse.
public enum ModelUpdatePins {
    public static func mayRelease(makingRoom: Bool, setupPending: Bool, updateDownloadActive: Bool) -> Bool {
        !makingRoom && !setupPending && !updateDownloadActive
    }
}

extension ContractBackedModelRegistry {
    /// RF-59, a disk too full for the update whose user agreed to remove the earlier models first:
    /// pins the shared components they hold (the new models reuse them), records the plan, then
    /// removes every retired folder now. Synchronous and possibly slow: call it off the main actor.
    public func removeRetiredFoldersBeforeUpdate(
        in modelsDirectory: URL,
        isInstalled: (ModelDescriptor) -> Bool
    ) -> RetiredModelReclamation {
        let store = SharedModelComponentStore(modelsRoot: modelsDirectory)
        store.pinSharedComponents(ofModelFolders: RetiredModelReclamation.presentFolders(of: models, in: modelsDirectory))
        let result = withoutActuallyEscaping(isInstalled) { isInstalled in
            RetiredModelReclamation.reclaim(
                models: models, in: modelsDirectory, force: true, isInstalled: isInstalled, isVerified: { _ in false }
            )
        }
        // Nothing went (the plan could not be recorded): the earlier models still hold the blobs.
        if result.removed.isEmpty { store.releaseUpdatePins() }
        return result
    }

    /// Drops the pins `removeRetiredFoldersBeforeUpdate` made, once no update download needs them.
    public func releaseModelUpdatePins(in modelsDirectory: URL) {
        SharedModelComponentStore(modelsRoot: modelsDirectory).releaseUpdatePins()
    }
}

/// RF-59: clone prompts are cached per model under `<voice>.clone_prompt/<model id>/`; a model the
/// contract no longer names (the 3.0 Quality package, `pro_clone_quality`) leaves a cache nothing
/// reads again.
public enum RetiredClonePromptCaches {
    /// Removes every cache folder named for a model id (`pro_…`) that `currentModelIDs` lacks, and
    /// returns them as `<voice>.clone_prompt/<model id>`, sorted. Anything else is left alone.
    @discardableResult
    public static func remove(in voicesDirectory: URL, currentModelIDs: Set<String>) -> [String] {
        let fileManager = FileManager.default
        func isDirectory(_ url: URL) -> Bool {
            (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true
        }
        guard let voices = try? fileManager.contentsOfDirectory(at: voicesDirectory, includingPropertiesForKeys: nil) else {
            return []
        }
        var removed: [String] = []
        for root in voices where root.pathExtension == "clone_prompt" && isDirectory(root) {
            let caches = (try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
            for cache in caches {
                let modelID = cache.lastPathComponent
                guard modelID.hasPrefix("pro_"), !currentModelIDs.contains(modelID), isDirectory(cache),
                      (try? fileManager.removeItem(at: cache)) != nil else { continue }
                removed.append("\(root.lastPathComponent)/\(modelID)")
            }
        }
        return removed.sorted()
    }
}
