import Foundation
import QwenVoiceCore

/// PA-30: the iPhone's one-time, confirmed removal of audio that earlier
/// History clears left in the app's private `outputs/` (maintainer decision
/// 2026-09-24; the Mac outputs folder stays untouched and the Mac never
/// compiles this file). Settings → Models & Files offers it; the decisions
/// are `IOSLeftoverAudioAnalysis`, and a file is removed only through the
/// History guarded removal, never through a link or into a folder.
///
/// It fails closed: while a long-form acceptance awaits recovery, a clear has
/// not finished, or History, its outbox or its removal list cannot be read
/// fully, nothing is offered and nothing is removed.
enum IOSLeftoverAudioCleanup {
    /// Set once the one-time review is done: the user removed the audio
    /// without a failure or chose Keep Files, or none was found. A persisted
    /// flag is the simplest correct way to never ask again, since a decline
    /// leaves the files in place. Nothing this offer exists for comes back:
    /// iPhone clears always delete their audio since PA-21, and audio a
    /// delete could not remove waits on the durable removal list instead.
    static let reviewedDefaultsKey = "vocello.ios.leftoverAudioReviewed"

    /// When this app session started; `QVoiceiOSApp.init` reads it first.
    /// Audio written since is never offered, so a take still in flight, not
    /// yet in History or the outbox, is never mistaken for a leftover.
    static let sessionStart = Date()

    static var isReviewed: Bool {
        UserDefaults.standard.bool(forKey: reviewedDefaultsKey)
    }

    static func markReviewed() {
        UserDefaults.standard.set(true, forKey: reviewedDefaultsKey)
    }

    /// The audio to offer, or nil: already reviewed, nothing left, or History
    /// state that cannot be read fully.
    static func pendingOffer() async -> IOSLeftoverAudioAnalysis.Leftovers? {
        guard !isReviewed else { return nil }
        guard let leftovers = await withCurrentLeftovers({ $0 }) else { return nil }
        guard !leftovers.files.isEmpty else {
            markReviewed()
            return nil
        }
        return leftovers
    }

    /// Removes the confirmed audio that is still unused and unchanged now,
    /// decided against History as it is at that moment. Nil when History state
    /// could not be read fully: then nothing was removed. The review is done
    /// once nothing failed.
    static func remove(
        _ confirmed: IOSLeftoverAudioAnalysis.Leftovers
    ) async -> IOSLeftoverAudioAnalysis.RemovalOutcome? {
        let outcome = await withCurrentLeftovers { current in
            IOSLeftoverAudioAnalysis.remove(
                IOSLeftoverAudioAnalysis.removalPlan(confirmed: confirmed, current: current)
            ) { path in
                switch GenerationHistoryAudioFile.removeRegularFile(atPath: path) {
                case .removed: return .removed
                case .absentOrNotRegular: return .absent
                case .failed: return .failed
                }
            }
        }
        if let outcome, outcome.failedCount == 0 {
            markReviewed()
        }
        return outcome
    }

    /// The folders History takes are written to, one per Studio mode, long-form
    /// projects included (`makeOutputPath`). Diagnostics runs write to their own
    /// subfolders, which the listing never enters.
    private static func takeDirectories() -> [URL] {
        Set(TTSModel.all.map(\.outputSubfolder)).sorted().map {
            AppPaths.outputsDir.appendingPathComponent($0, isDirectory: true)
        }
    }

    private static func withCurrentLeftovers<T: Sendable>(
        _ body: @escaping @Sendable (IOSLeftoverAudioAnalysis.Leftovers) -> T
    ) async -> T? {
        // A long-form acceptance awaiting recovery names audio no row holds yet.
        guard !GenerationHistoryRecovery.longFormStore.hasPendingRecovery else { return nil }
        // Audio whose History record could not even be queued this session.
        let unqueued = await MainActor.run { Set(GenerationHistoryRecovery.unqueued.records.keys) }
        // No bundled model contract, no known folders: nothing can be judged.
        let directories = takeDirectories()
        guard !directories.isEmpty else { return nil }
        let cutoff = Self.sessionStart
        let result = await GenerationHistoryRecovery.coordinator.withReferencedAudioPaths { referenced -> T? in
            guard !GenerationHistoryRecovery.longFormStore.hasPendingRecovery,
                  let leftovers = IOSLeftoverAudioAnalysis.leftovers(
                      in: IOSLeftoverAudioAnalysis.listing(ofDirectories: directories),
                      referencedAudioPaths: referenced.union(unqueued),
                      writtenBefore: cutoff
                  ) else { return nil }
            return body(leftovers)
        }
        return result ?? nil
    }
}
