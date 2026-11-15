import Foundation
import QwenVoiceCore

/// RF-59, A9: what the Mac's "Remove Earlier Models and Update" does once the
/// removal ended. It sits beside the launch decision it follows
/// (`MacModelUpdateAutoStart.decide`, whose `needsRoom` makes the offer) and
/// is UI-free, so `ModelManagerViewModel` only applies it.
extension MacModelUpdateAutoStart {
    enum AfterMakingRoom: Equatable, Sendable {
        /// At least one earlier model went, so there is more room than
        /// before: the update starts.
        case startUpdate
        /// Nothing went: the update plan could not be recorded, or no folder
        /// could be deleted. The disk is as short as it was, so no download
        /// starts, the offer stays and the banner says the earlier models
        /// could not be removed (`ModelManagerViewModel.modelUpdateRoomNotMade`).
        case roomNotMade
    }

    /// Folders that could not be removed do not decide it: one folder gone
    /// is room made, and the folders that stayed are tried again later.
    static func afterMakingRoom(_ removal: RetiredModelReclamation) -> AfterMakingRoom {
        removal.removed.isEmpty ? .roomNotMade : .startUpdate
    }
}
