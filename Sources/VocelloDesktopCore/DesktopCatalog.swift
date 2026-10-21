import Foundation
import QwenVoiceCore

/// The Voice Design starting briefs the app offers, in the speech language the
/// app would show them for. They have no stable ids: the app lists them by
/// position, and so does the CLI.
public enum DesktopBriefCatalog {
    public struct Brief: Encodable, Sendable, Equatable {
        public let index: Int
        public let text: String
    }

    /// The longest description Voice Design accepts.
    public static var descriptionLimit: Int { VoiceDesignBriefCatalog.descriptionLimit }

    public static func briefs(in language: Qwen3SupportedLanguage = .english) -> [Brief] {
        VoiceDesignBriefCatalog.startingPoints(in: language).enumerated().map { Brief(index: $0.offset, text: $0.element) }
    }
}

/// Saved voices grouped into delivery banks the way Clone's delivery picker
/// groups them: a base voice and its `<Name> (<Preset>)` variants.
public enum DesktopVoiceBanks {
    public struct Bank: Encodable, Sendable, Equatable {
        public struct Member: Encodable, Sendable, Equatable {
            public let preset: String
            public let voiceID: String
        }

        public let name: String
        public let baseVoiceID: String
        public let members: [Member]
    }

    public static func banks(voices: [(id: String, name: String)]) -> [Bank] {
        VoiceBankCatalog.build(voices: voices).personas.map { persona in
            Bank(
                name: persona.name, baseVoiceID: persona.baseVoiceID,
                members: persona.orderedVariants.map { Bank.Member(preset: $0.presetID, voiceID: $0.voiceID) }
            )
        }
    }
}
