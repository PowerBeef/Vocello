import Foundation

/// Hears another Vocello process (the `vocello` CLI) change a store the app
/// shares (`SharedStoreChange`, RF-28) and hands the change to the app, which
/// reloads that store. Started once, for the app's life.
@MainActor
final class MacSharedStoreChangeObserver {
    private var observers: [any NSObjectProtocol] = []

    func start(_ onChange: @escaping @MainActor (SharedStoreChange) -> Void) {
        guard observers.isEmpty else { return }
        let center = DistributedNotificationCenter.default()
        observers = SharedStoreChange.allCases.map { change in
            center.addObserver(forName: change.name, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { onChange(change) }
            }
        }
    }

    func stop() {
        let center = DistributedNotificationCenter.default()
        observers.forEach(center.removeObserver)
        observers = []
    }
}
