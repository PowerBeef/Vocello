import Combine
import Foundation
import QwenVoiceCore
#if canImport(VocelloDesktopCore)
import VocelloDesktopCore
#endif

/// The Mac app among the engine hosts on this Mac (RF-61, audit finding C3).
/// It takes a lease of kind `app` while its engine may hold a model and reads
/// the other hosts' before it deletes a model, generates or warms, as the
/// `vocello` command line already does from its side.
///
/// The lease follows the engine's published state (`EngineHostLeaseKeeper`):
/// taken when a model starts to load, kept while it is loaded, generating or
/// being primed, given back when the engine unloads it and at quit. A lease
/// holds the process id, the host kind and the start time, nothing else.
///
/// The decisions are `EngineHostAppPolicy`'s (compiled into `VocelloDesktopCore`
/// too, where they are tested); this type reads the leases and words the
/// refusals.
@MainActor
final class MacEngineHostCoordinator {
    /// Handle for a provisionally admitted engine start. Scoped async callers
    /// (`beginScopedEngineWork()`) call `end()` in a `defer`; fire-and-forget
    /// starters (`admitEngineWork()` / `admitGeneration()`) call `end()` only
    /// when the start fails synchronously before reaching the engine.
    @MainActor
    final class EngineWorkAdmission {
        private weak var keeper: EngineHostLeaseKeeper?
        private let provisionalHoldID: UUID?
        private let countsAsRequest: Bool
        private var finished = false

        fileprivate init(
            keeper: EngineHostLeaseKeeper,
            provisionalHoldID: UUID?,
            countsAsRequest: Bool
        ) {
            self.keeper = keeper
            self.provisionalHoldID = provisionalHoldID
            self.countsAsRequest = countsAsRequest
        }

        /// Ends a scoped admission or cancels an unused provisional handoff.
        /// Idempotent.
        func end() {
            guard !finished else { return }
            finished = true
            guard let keeper else { return }
            if let provisionalHoldID {
                keeper.endProvisionalHold(provisionalHoldID)
            }
            if countsAsRequest {
                keeper.requestEnded()
            }
        }
    }

    static let shared = MacEngineHostCoordinator()

    private let deviceClass: NativeDeviceMemoryClass
    private let tierIsDiagnostic: Bool
    private let folder: URL
    private let provisionalHoldDuration: Duration
    private let keeper: EngineHostLeaseKeeper
    private var engineStates: AnyCancellable?

    /// The app's coordinator reads this Mac's tier and the shared lease folder; a test
    /// passes its own folder, tier, failure window, and provisional hold duration.
    init(
        folder: URL = EngineHostLease.sharedFolder,
        deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass(),
        tierIsDiagnostic: Bool = NativeDeviceClassGate.resolvedTierIsDiagnostic,
        failureWindow: Duration? = nil,
        provisionalHoldDuration: Duration = .seconds(2)
    ) {
        self.deviceClass = deviceClass
        self.tierIsDiagnostic = tierIsDiagnostic
        self.folder = folder
        self.provisionalHoldDuration = provisionalHoldDuration
        keeper = EngineHostLeaseKeeper(
            kind: "app",
            folder: folder,
            failureWindow: failureWindow ?? EngineHostLeaseKeeper.failureWindow(for: deviceClass)
        )
    }

    /// Whether the app currently holds a live `app` lease on disk.
    var holdsLease: Bool { keeper.holdsLease }

    /// The app's active lease, if any, for excluding self when inspecting
    /// `EngineHostLease.liveHosts(excluding:)`.
    var ownLease: EngineHostLease? { keeper.lease }

    /// Follows `store`'s model from now on. The app has one engine store; a
    /// store built again after a failed start replaces the one followed.
    func attach(_ store: TTSEngineStore) {
        engineStates = store.snapshotUpdates.sink { [weak self] state in
            // RF-69: once `TTSEngineFrontendState` publishes an explicit
            // `unloadEpoch` (wired in B2.1b), pass `unloadEpoch:` here so
            // `unloadModel()`, `trimMemory(.fullUnload)`, and `stop()` cancel
            // any pending failure timer immediately.
            self?.engineChanged(loadState: state.loadState, clonePreparation: state.clonePreparationState.phase)
        }
        engineChanged(loadState: store.loadState, clonePreparation: store.clonePreparationState.phase)
    }

    /// What the engine publishes about its model, as the attached store reports it.
    func engineChanged(
        loadState: EngineLoadState,
        clonePreparation: ClonePreparationPhase,
        unloadEpoch: UInt64? = nil
    ) {
        keeper.engineChanged(
            loadState: loadState,
            clonePreparation: clonePreparation,
            unloadEpoch: unloadEpoch
        )
    }

    /// Signals an explicit model unload (`unloadModel()`, `trimMemory(.fullUnload)`,
    /// or `stop()`), cancelling any pending post-failure release window immediately.
    func modelUnloaded() {
        keeper.modelUnloaded()
    }

    /// Gives the lease up at quit. A process that ends without this leaves a
    /// lease nobody holds, which the next reader removes.
    func releaseLease() {
        keeper.releaseNow()
    }

    /// The live hosts other than this app's own lease.
    private var otherHosts: [EngineHostLease.Host] {
        EngineHostLease.liveHosts(in: folder, excluding: keeper.lease)
    }

    /// Whether a take or a warm waits: on an 8 GB Mac, while another Vocello
    /// engine holds a lease (`EngineHostAdmission`'s rule). Call sites starting
    /// engine work should prefer `admitEngineWork()`, `admitGeneration()`, or
    /// `beginScopedEngineWork()` to close the 8 GB acquire-then-check race.
    var refusesEngineWork: Bool {
        EngineHostAppPolicy.refusesEngineWork(
            otherHosts: otherHosts, deviceClass: deviceClass,
            holdsOwnLease: keeper.holdsLease,
            tierIsDiagnostic: tierIsDiagnostic
        )
    }

    /// The refusal a take, a line batch or a long-form project shows in place
    /// of starting, or nil when it may start.
    var generationRefusalMessage: String? {
        refusesEngineWork ? MacInterfaceText.engineHostBusy : nil
    }

    /// Acquire-then-check admission (mirroring `CLIRuntime.admitEngineHost`) for
    /// a scoped async operation such as clone priming. Acquires a provisional
    /// `app` lease first, checks `liveHosts(excluding: provisional)`, releases it
    /// immediately if refused on an 8 GB Mac, or holds it until the caller invokes
    /// `end()` on the returned handle (and beyond if a model became present).
    func beginScopedEngineWork() -> EngineWorkAdmission? {
        guard let decision = acquireAndCheckProvisionalLease() else { return nil }
        keeper.requestBegan()
        keeper.adopt(decision.lease)
        return EngineWorkAdmission(keeper: keeper, provisionalHoldID: nil, countsAsRequest: true)
    }

    /// Acquire-then-check admission for fire-and-forget starts (single takes,
    /// batches, long-form projects, and proactive warms). On admission, hands
    /// the provisional lease to `keeper` until the engine publishes `.present`,
    /// the caller cancels an unused start via `end()`, or `provisionalHoldDuration`
    /// elapses. Returns `nil` when refused on an 8 GB Mac.
    @discardableResult
    func admitEngineWork() -> EngineWorkAdmission? {
        guard let decision = acquireAndCheckProvisionalLease() else { return nil }
        if decision.lease == nil, !keeper.holdsLease {
            return EngineWorkAdmission(keeper: keeper, provisionalHoldID: nil, countsAsRequest: false)
        }
        let holdID = keeper.beginProvisionalHold(adopting: decision.lease, timeout: provisionalHoldDuration)
        return EngineWorkAdmission(keeper: keeper, provisionalHoldID: holdID, countsAsRequest: false)
    }

    /// Acquire-then-check admission for generation starts that surface
    /// `MacInterfaceText.engineHostBusy` on refusal.
    func admitGeneration() -> (admission: EngineWorkAdmission?, refusalMessage: String?) {
        if let admission = admitEngineWork() {
            return (admission, nil)
        }
        return (nil, MacInterfaceText.engineHostBusy)
    }

    /// Whether a model's files stay: another host holds a lease and may have
    /// that model loaded.
    var refusesModelDeletion: Bool {
        EngineHostAppPolicy.refusesModelDeletion(otherHosts: otherHosts)
    }

    private struct ProvisionalDecision {
        let lease: EngineHostLease?
    }

    private func acquireAndCheckProvisionalLease() -> ProvisionalDecision? {
        if keeper.holdsLease || tierIsDiagnostic {
            return ProvisionalDecision(lease: nil)
        }
        let provisional = try? EngineHostLease.acquire(in: folder, kind: "app")
        let others = EngineHostLease.liveHosts(in: folder, excluding: provisional)
        if EngineHostAppPolicy.refusesEngineWork(
            otherHosts: others,
            deviceClass: deviceClass,
            holdsOwnLease: false,
            tierIsDiagnostic: tierIsDiagnostic
        ) {
            provisional?.release()
            return nil
        }
        return ProvisionalDecision(lease: provisional)
    }
}
