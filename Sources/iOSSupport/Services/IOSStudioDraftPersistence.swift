import Foundation

/// The Studio drafts as they are kept across launches (PA-21, IOS-09).
///
/// iOS routinely terminates a backgrounded app that holds several GB, and the
/// drafts (a script of up to 30,000 characters per mode) used to live only in
/// memory. `AppModel` saves this snapshot whenever the scene leaves the
/// foreground and restores it at launch. Plain values keep the stored format
/// independent of the in-memory draft types.
struct IOSStudioDraftSnapshot: Codable, Equatable, Sendable {
    static let currentVersion = 1

    struct Delivery: Codable, Equatable, Sendable {
        var mode: String
        var presetID: String
        var intensity: Int
        var customText: String
    }

    struct Custom: Codable, Equatable, Sendable {
        var speakerID: String
        var language: String
        var pinnedSeed: UInt64?
        var delivery: Delivery
        var text: String
    }

    struct Design: Codable, Equatable, Sendable {
        var voiceDescription: String
        var language: String
        var pinnedSeed: UInt64?
        var delivery: Delivery
        var text: String
    }

    struct Clone: Codable, Equatable, Sendable {
        /// Only a saved voice is restored as the reference; its path and
        /// transcript are checked against the library when the Studio hydrates.
        var savedVoiceID: String?
        var referenceAudioPath: String?
        var referenceTranscript: String
        var language: String
        var pinnedSeed: UInt64?
        var text: String
    }

    var version: Int
    var custom: Custom
    var design: Design
    var clone: Clone

    init(custom: Custom, design: Design, clone: Clone) {
        self.version = Self.currentVersion
        self.custom = custom
        self.design = design
        var clone = clone
        if clone.savedVoiceID == nil {
            // A reference that is not a saved voice (an imported or recorded
            // clip still being enrolled) lives in regenerable storage; it is
            // never restored.
            clone.referenceAudioPath = nil
            clone.referenceTranscript = ""
        }
        self.clone = clone
    }
}

enum IOSStudioDraftPersistence {
    /// Stored in the app's own preferences, which keep the default data
    /// protection class and back up like History.
    static let defaultsKey = "vocello.ios.studioDrafts.v1"

    static func encode(_ snapshot: IOSStudioDraftSnapshot) -> Data? {
        try? JSONEncoder().encode(snapshot)
    }

    /// `nil` for a missing, unreadable or other-version snapshot: the Studio
    /// then starts with empty drafts, as it did before drafts were kept.
    static func decode(_ data: Data?) -> IOSStudioDraftSnapshot? {
        guard let data,
              let snapshot = try? JSONDecoder().decode(IOSStudioDraftSnapshot.self, from: data),
              snapshot.version == IOSStudioDraftSnapshot.currentVersion else {
            return nil
        }
        return snapshot
    }

    static func load(from defaults: UserDefaults) -> IOSStudioDraftSnapshot? {
        decode(defaults.data(forKey: defaultsKey))
    }

    static func save(_ snapshot: IOSStudioDraftSnapshot, to defaults: UserDefaults) {
        guard let data = encode(snapshot) else { return }
        defaults.set(data, forKey: defaultsKey)
    }
}
