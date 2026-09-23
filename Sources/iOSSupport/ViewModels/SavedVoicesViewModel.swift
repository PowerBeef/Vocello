import Foundation
import QwenVoiceCore

/// Why the Saved Voices list is not current. The busy state stays typed so each
/// surface presents it in its interface language instead of as a failure (F-25).
enum SavedVoicesLoadIssue: Equatable {
    /// Another Vocello process (the CLI shares the store with the Mac app) holds
    /// the Saved Voice store lock. Loading retries automatically a few times.
    case storeBusy
    case failed(String)

    init(_ error: Error) {
        if (error as? TTSEngineError) == .savedVoiceStoreBusy {
            self = .storeBusy
        } else {
            self = .failed(error.localizedDescription)
        }
    }
}

@MainActor
final class SavedVoicesViewModel: ObservableObject {
    @Published private(set) var voices: [Voice] = SavedVoicesSessionCache.voices
    @Published private(set) var isLoading = false
    @Published private(set) var loadIssue: SavedVoicesLoadIssue?

    private var hasLoadedOnce = !SavedVoicesSessionCache.voices.isEmpty
    private var pendingRefresh = false
    private var loadTask: Task<Void, Never>?
    private var lastRefreshAction: (() async -> Void)?
    private var busyRetryPolicy = SavedVoicesBusyRetryPolicy()
    private var storeBusyRetryTask: Task<Void, Never>?

    /// Stops a pending busy-store retry and restores a fresh schedule. The
    /// Voices screens call this when they disappear; reappearing loads again.
    func cancelBusyRetry() {
        storeBusyRetryTask?.cancel()
        storeBusyRetryTask = nil
        busyRetryPolicy.reset()
    }

    /// `loadIssue` in the caller's interface language.
    func loadErrorMessage(_ presentation: VocelloPresentationText) -> String? {
        switch loadIssue {
        case nil: nil
        case .storeBusy: presentation.savedVoicesStoreBusy
        case .failed(let message): message
        }
    }

    func ensureLoaded(using ttsEngine: some TTSEngine) async {
        guard ttsEngine.isReady else { return }
        guard !hasLoadedOnce else { return }
        startLoad(using: ttsEngine, clearsVisibleError: true)
    }

    func refresh(using ttsEngine: some TTSEngine) async {
        guard ttsEngine.isReady else { return }

        if isLoading {
            pendingRefresh = true
            return
        }

        startLoad(using: ttsEngine, clearsVisibleError: voices.isEmpty)
    }

    func insertOrReplace(_ voice: Voice) {
        voices.removeAll { $0.id == voice.id }
        voices.append(voice)
        voices.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        SavedVoicesSessionCache.voices = voices
        hasLoadedOnce = true
        loadIssue = nil
    }

    func removeVoiceFromVisibleState(id: String) {
        voices.removeAll { $0.id == id }
        SavedVoicesSessionCache.voices = voices
    }

    private func startLoad(using ttsEngine: some TTSEngine, clearsVisibleError: Bool) {
        guard !isLoading else { return }
        lastRefreshAction = { [weak self] in
            guard let self else { return }
            await self.refresh(using: ttsEngine)
        }

        let interval = AppPerformanceSignposts.begin("Saved Voices Load")
        let wallStart = DispatchTime.now().uptimeNanoseconds

        isLoading = true
        if clearsVisibleError {
            loadIssue = nil
        }

        loadTask = Task { [weak self] in
            guard let self else { return }

            defer {
                AppPerformanceSignposts.end(interval)
            }

            do {
                let loadedVoices = try await ttsEngine.listPreparedVoices()
                await MainActor.run {
                    self.voices = loadedVoices
                    SavedVoicesSessionCache.voices = loadedVoices
                    self.loadIssue = nil
                    self.hasLoadedOnce = true
                    self.busyRetryPolicy.reset()
                    self.finishLoad(wallStart: wallStart)
                }
            } catch {
                guard !Task.isCancelled else { return }
                let issue = SavedVoicesLoadIssue(error)
                await MainActor.run {
                    self.loadIssue = issue
                    self.finishLoad(wallStart: wallStart)
                    if issue == .storeBusy {
                        self.scheduleStoreBusyRetry()
                    }
                }
            }
        }
    }

    private func scheduleStoreBusyRetry() {
        guard storeBusyRetryTask == nil, let delay = busyRetryPolicy.nextDelay() else { return }
        storeBusyRetryTask = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard let self, !Task.isCancelled else { return }
            self.storeBusyRetryTask = nil
            await self.lastRefreshAction?()
        }
    }

    private func finishLoad(wallStart: UInt64) {
        if TelemetryGate.resolvedEnabled {
            let elapsedMs = Int((DispatchTime.now().uptimeNanoseconds - wallStart) / 1_000_000)
            print("[Performance][SavedVoicesViewModel] load_wall_ms=\(elapsedMs)")
        }

        isLoading = false
        loadTask = nil

        if pendingRefresh {
            pendingRefresh = false
            if let lastRefreshAction {
                Task {
                    await lastRefreshAction()
                }
            }
        }
    }
}

@MainActor private enum SavedVoicesSessionCache {
    static var voices: [Voice] = []
}
