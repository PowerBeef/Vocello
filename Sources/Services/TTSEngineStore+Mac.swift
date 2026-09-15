import Combine
import Foundation
import QwenVoiceCore

/// macOS conveniences over the shared store. The legacy screens and the warmup
/// coordinator read one `TTSEngineSnapshot` value; the root shell subscribes to
/// `snapshotChanges` with `onReceive` so it never observes the whole
/// `ObservableObject` in a view body (W1-D/W2-A).
extension TTSEngineStore {
    var snapshot: TTSEngineSnapshot {
        TTSEngineSnapshot(
            isReady: isReady,
            loadState: loadState,
            clonePreparationState: clonePreparationState,
            visibleErrorMessage: visibleErrorMessage
        )
    }

    var snapshotChanges: AnyPublisher<TTSEngineSnapshot, Never> {
        snapshotUpdates
            .map { state in
                TTSEngineSnapshot(
                    isReady: state.isReady,
                    loadState: state.loadState,
                    clonePreparationState: state.clonePreparationState,
                    visibleErrorMessage: state.visibleErrorMessage
                )
            }
            .eraseToAnyPublisher()
    }
}
