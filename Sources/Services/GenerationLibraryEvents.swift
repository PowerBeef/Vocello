import Combine
import Foundation

@MainActor
final class GenerationLibraryEvents {
    static let shared = GenerationLibraryEvents()

    /// Fires after a Generation has been persisted and is ready for
    /// inclusion in the History view. Carries the persisted Generation
    /// so the UI can append it in-place without re-fetching all rows
    /// from SQLite. Backward-compat: `generationSaved` (Void) still
    /// fires for any subscribers that don't need the payload.
    let generationAppended = PassthroughSubject<Generation, Never>()

    /// Legacy publisher for subscribers that only need a "something
    /// changed" signal. New subscribers should prefer
    /// `generationAppended` so they can avoid full reloads.
    let generationSaved = PassthroughSubject<Void, Never>()

    private init() {}

    /// Convenience: announce a freshly-persisted Generation, firing
    /// both publishers for callers that haven't migrated yet.
    func announceGenerationAppended(_ generation: Generation) {
        generationAppended.send(generation)
        generationSaved.send(())
    }

    /// Legacy entrypoint for callers that only know the save happened
    /// but don't have the Generation handy.
    func announceGenerationSaved() {
        generationSaved.send(())
    }
}
