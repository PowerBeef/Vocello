import Combine
import Foundation
import Observation

@MainActor
@Observable
final class AppCommandRouter {
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
    var isGenerationActive = false
    /// Whether a line batch or long-form project is running (A14-05). Its
    /// sheet belongs to its Studio screen, so the Navigate commands wait.
    var isNavigationLocked = false

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
