import Foundation

/// RF-59: what the iPhone does at launch with the models an earlier Vocello installed. The App
/// Store requires asking before a model download, with its size (RF-41, Guideline 4.2.3(ii)), so
/// the first launch asks once for every model together; after that consent, a later launch resumes
/// the update without asking. A model the user stopped, one whose download failed (it waits for
/// the user's Retry, NET-1) or one already transferring is left as it is, and nothing starts under
/// Low Data Mode. Pure, so both iOS test bundles drive it.
enum IOSModelUpdateAutoStartPolicy {
    struct Candidate: Equatable, Sendable {
        let modelID: String
        let estimatedBytes: Int64
        /// The user stopped this model's update.
        let paused: Bool
        /// Queued, waiting for a network, transferring, verifying or installing.
        let active: Bool
        /// The last attempt failed and waits for Retry.
        let failed: Bool
    }

    enum Decision: Equatable, Sendable {
        case none
        /// Ask once, naming the total size. `makesRoomFirst`: the phone lacks the space to keep the
        /// earlier models while the first new one downloads, so they are removed first.
        case ask(modelIDs: [String], totalBytes: Int64, makesRoomFirst: Bool)
        case start(modelIDs: [String])
    }

    static func decide(
        candidates: [Candidate],
        consented: Bool,
        lowDataMode: Bool,
        availableBytes: Int64?,
        holdsEarlierModels: Bool
    ) -> Decision {
        let ready = candidates.filter { !$0.paused && !$0.active && !$0.failed }
        guard !ready.isEmpty, !lowDataMode else { return .none }
        guard !consented else { return .start(modelIDs: ready.map(\.modelID)) }
        let largest = ready.map(\.estimatedBytes).max() ?? 0
        let roomForFirst = availableBytes.map { $0 >= IOSModelDeliverySupport.minimumFreeBytes(forFetching: largest) } ?? true
        return .ask(
            modelIDs: ready.map(\.modelID),
            totalBytes: ready.reduce(0) { $0 + $1.estimatedBytes },
            makesRoomFirst: holdsEarlierModels && !roomForFirst
        )
    }
}
