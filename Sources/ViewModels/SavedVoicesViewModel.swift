import Foundation
import Observation
import QwenVoiceCore

@MainActor
@Observable
final class SavedVoicesViewModel {
    private(set) var voices: [Voice] = SavedVoicesSessionCache.voices
    private(set) var isLoading = false
    private(set) var loadError: String?

    @ObservationIgnored private var hasLoadedOnce = !SavedVoicesSessionCache.voices.isEmpty
    @ObservationIgnored private var pendingRefresh = false
    @ObservationIgnored private var loadTask: Task<Void, Never>?
    @ObservationIgnored private weak var lastTTSEngineStore: TTSEngineStore?

    func ensureLoaded(using ttsEngineStore: TTSEngineStore) async {
        guard ttsEngineStore.isReady else { return }
        guard !hasLoadedOnce else { return }
        startLoad(using: ttsEngineStore, clearsVisibleError: true)
    }

    func refresh(using ttsEngineStore: TTSEngineStore) async {
        guard ttsEngineStore.isReady else { return }

        if isLoading {
            pendingRefresh = true
            return
        }

        startLoad(using: ttsEngineStore, clearsVisibleError: voices.isEmpty)
    }

    func insertOrReplace(_ voice: Voice) {
        voices.removeAll { $0.id == voice.id }
        voices.append(voice)
        voices.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        SavedVoicesSessionCache.voices = voices
        hasLoadedOnce = true
        loadError = nil
    }

    func removeVoiceFromVisibleState(id: String) {
        voices.removeAll { $0.id == id }
        SavedVoicesSessionCache.voices = voices
    }

    private func startLoad(using ttsEngineStore: TTSEngineStore, clearsVisibleError: Bool) {
        guard !isLoading else { return }
        lastTTSEngineStore = ttsEngineStore

        let interval = AppPerformanceSignposts.begin("Saved Voices Load")
        let wallStart = DispatchTime.now().uptimeNanoseconds

        isLoading = true
        if clearsVisibleError {
            loadError = nil
        }

        loadTask = Task { [weak self] in
            guard let self else { return }

            defer {
                AppPerformanceSignposts.end(interval)
            }

            do {
                let loadedVoices = try await ttsEngineStore.listPreparedVoices().map(Voice.init(preparedVoice:))
                await MainActor.run {
                    self.voices = loadedVoices
                    SavedVoicesSessionCache.voices = loadedVoices
                    self.loadError = nil
                    self.hasLoadedOnce = true
                    self.finishLoad(wallStart: wallStart)
                }
            } catch {
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    self.loadError = error.localizedDescription
                    self.finishLoad(wallStart: wallStart)
                }
            }
        }
    }

    private func finishLoad(wallStart: UInt64) {
        if DebugMode.isEnabled {
            let elapsedMs = Int((DispatchTime.now().uptimeNanoseconds - wallStart) / 1_000_000)
            print("[Performance][SavedVoicesViewModel] load_wall_ms=\(elapsedMs)")
        }

        isLoading = false
        loadTask = nil

        if pendingRefresh {
            pendingRefresh = false
            if let lastTTSEngineStore {
                Task { [weak self] in
                    guard let self else { return }
                    await self.refresh(using: lastTTSEngineStore)
                }
            }
        }
    }
}

@MainActor private enum SavedVoicesSessionCache {
    static var voices: [Voice] = []
}
