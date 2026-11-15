import Combine
import Foundation
import QwenVoiceCore

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
    static let shared = MacEngineHostCoordinator()

    private let deviceClass: NativeDeviceMemoryClass
    private let keeper: EngineHostLeaseKeeper
    private var engineStates: AnyCancellable?

    private init() {
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        self.deviceClass = deviceClass
        keeper = EngineHostLeaseKeeper(
            kind: "app", failureWindow: EngineHostLeaseKeeper.failureWindow(for: deviceClass)
        )
    }

    /// Follows `store`'s model from now on. The app has one engine store; a
    /// store built again after a failed start replaces the one followed.
    func attach(_ store: TTSEngineStore) {
        engineStates = store.snapshotUpdates.sink { [keeper] state in
            keeper.engineChanged(loadState: state.loadState, clonePreparation: state.clonePreparationState.phase)
        }
        keeper.engineChanged(loadState: store.loadState, clonePreparation: store.clonePreparationState.phase)
    }

    /// Gives the lease up at quit. A process that ends without this leaves a
    /// lease nobody holds, which the next reader removes.
    func releaseLease() {
        keeper.releaseNow()
    }

    /// The live hosts other than this app's own lease.
    private var otherHosts: [EngineHostLease.Host] {
        EngineHostLease.liveHosts(excluding: keeper.lease)
    }

    /// Whether a take or a warm waits: on an 8 GB Mac, while another Vocello
    /// engine holds a lease (`EngineHostAdmission`'s rule).
    var refusesEngineWork: Bool {
        EngineHostAppPolicy.refusesEngineWork(otherHosts: otherHosts, deviceClass: deviceClass)
    }

    /// The refusal a take, a line batch or a long-form project shows in place
    /// of starting, or nil when it may start.
    var generationRefusalMessage: String? {
        refusesEngineWork ? MacInterfaceText.engineHostBusy : nil
    }

    /// Refuses a take before it reaches the engine.
    func admitGeneration() throws {
        if refusesEngineWork { throw MacEngineHostRefusal.anotherEngineRunning }
    }

    /// Whether a model's files stay: another host holds a lease and may have
    /// that model loaded.
    var refusesModelDeletion: Bool {
        EngineHostAppPolicy.refusesModelDeletion(otherHosts: otherHosts)
    }
}

/// A take the app did not start because another Vocello engine holds this
/// 8 GB Mac. Its description is interface copy, shown as the take's failure.
enum MacEngineHostRefusal: LocalizedError {
    case anotherEngineRunning

    var errorDescription: String? {
        MacInterfaceText.engineHostBusy
    }
}
