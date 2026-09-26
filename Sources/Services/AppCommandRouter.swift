import Combine
import Foundation

@MainActor
final class AppCommandRouter: ObservableObject {
    static let shared = AppCommandRouter()

    let sidebarSelection = PassthroughSubject<SidebarItem, Never>()
    /// Stop (⌘.) while a take runs (MAC-23): the shell cancels it, stopping
    /// the live preview of the player it carries.
    let generationCancelRequests = PassthroughSubject<AudioPlayerViewModel, Never>()
    /// Search History (⌘F, MAC-23): the shell opens History and focuses its
    /// search field.
    let historySearchRequests = PassthroughSubject<Void, Never>()
    /// Whether a Studio take, line batch or long-form project is running. The
    /// shell keeps it current; the Stop command reads it to choose between
    /// cancelling the take and stopping playback.
    @Published var isGenerationActive = false

    private init() {}

    func navigate(to item: SidebarItem) {
        sidebarSelection.send(item)
    }

    func cancelGeneration(stoppingPreviewOf audioPlayer: AudioPlayerViewModel) {
        generationCancelRequests.send(audioPlayer)
    }

    func searchHistory() {
        historySearchRequests.send()
    }
}
