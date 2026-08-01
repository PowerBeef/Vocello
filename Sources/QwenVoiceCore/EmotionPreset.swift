import Foundation

// Single source of truth for the delivery (tone/emotion) presets, shared by the
// macOS app, the iOS app, and the `vocello` CLI (bench/review delivery cells).
// Previously duplicated as Sources/Models/EmotionPreset.swift and
// Sources/iOSSupport/Models/EmotionPreset.swift, which had to be edited in
// lockstep; consolidated here so preset copy changes land once.

public enum EmotionIntensity: Int, CaseIterable, Identifiable, Sendable {
    case subtle = 0
    case normal = 1
    case strong = 2

    public var id: Int { rawValue }

    public var label: String {
        switch self {
        case .subtle: "Subtle"
        case .normal: "Normal"
        case .strong: "Strong"
        }
    }

    public var rpcValue: String {
        switch self {
        case .subtle: "subtle"
        case .normal: "normal"
        case .strong: "strong"
        }
    }
}

public struct DeliveryProfile: Equatable, Sendable {
    public static let neutralInstruction = "Neutral"

    public let presetID: String?
    public let intensity: EmotionIntensity?
    public let customText: String?
    public let finalInstruction: String

    public init(
        presetID: String?,
        intensity: EmotionIntensity?,
        customText: String?,
        finalInstruction: String
    ) {
        self.presetID = presetID
        self.intensity = intensity
        self.customText = customText
        self.finalInstruction = finalInstruction
    }

    public static let neutral = DeliveryProfile(
        presetID: "neutral",
        intensity: nil,
        customText: nil,
        finalInstruction: neutralInstruction
    )

    public static func isNeutralInstruction(_ instruction: String) -> Bool {
        let normalized = instruction
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return normalized.isEmpty
            || normalized == "normal tone"
            || normalized == "neutral"
            || normalized == "neutral tone"
    }

    public var trimmedInstruction: String {
        finalInstruction.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public var trimmedCustomText: String? {
        customText?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public var isNeutral: Bool {
        DeliveryProfile.isNeutralInstruction(trimmedInstruction)
    }

    public var isMeaningful: Bool {
        !isNeutral
    }

    public static func preset(_ preset: EmotionPreset, intensity: EmotionIntensity) -> DeliveryProfile {
        DeliveryProfile(
            presetID: preset.id,
            intensity: preset.id == "neutral" ? nil : intensity,
            customText: nil,
            finalInstruction: preset.instruction(for: intensity)
        )
    }

    public static func custom(_ text: String) -> DeliveryProfile {
        DeliveryProfile(
            presetID: nil,
            intensity: .normal,
            customText: text,
            finalInstruction: text
        )
    }
}

public struct EmotionPreset: Identifiable, Sendable {
    public let id: String
    public let label: String
    public let sfSymbol: String
    public let instructions: [EmotionIntensity: String]

    public init(
        id: String,
        label: String,
        sfSymbol: String,
        instructions: [EmotionIntensity: String]
    ) {
        self.id = id
        self.label = label
        self.sfSymbol = sfSymbol
        self.instructions = instructions
    }

    public func instruction(for intensity: EmotionIntensity) -> String {
        instructions[intensity] ?? instructions[.normal] ?? DeliveryProfile.neutralInstruction
    }

    public static func preset(id: String?) -> EmotionPreset? {
        guard let id else { return nil }
        return all.first(where: { $0.id == id })
    }

    // Instruction-writing canon (Qwen3-TTS official guidance + measured adherence):
    // - Imperative verbs (Speak / Whisper / Narrate) are followed more reliably.
    // - Combine emotion + pace + pitch + timbre in concrete acoustic wording.
    // - Add negative constraints for high-arousal emotions (no laughing / shouting /
    //   gasping) to avoid literal artifacts.
    // - Keep intelligibility clauses for quiet/fragile tiers.
    // - Avoid stacked intensifiers; stay under the 500-character cap.
    public static let all: [EmotionPreset] = [
        EmotionPreset(
            id: "neutral",
            label: "Neutral",
            sfSymbol: "face.dashed",
            instructions: [
                .subtle: DeliveryProfile.neutralInstruction,
                .normal: DeliveryProfile.neutralInstruction,
                .strong: DeliveryProfile.neutralInstruction,
            ]
        ),
        EmotionPreset(
            id: "happy",
            label: "Happy",
            sfSymbol: "face.smiling",
            instructions: [
                .subtle: "Speak with a hint of warmth, a faint smile in the voice, a gently lifted pitch, and a relaxed easy pace; no laughing.",
                .normal: "Speak happily and warmly, with a clearly lifted pitch, a light bouncing rhythm, a bright smiling tone, and quick cheerful pacing; no laughing.",
                .strong: "Speak joyfully and energetically, with a noticeably higher pitch and louder volume, a fast animated pace, a bright ringing tone, and strong rising emphasis on key words; no laughing or shouting.",
            ]
        ),
        EmotionPreset(
            id: "sad",
            label: "Sad",
            sfSymbol: "cloud.rain",
            instructions: [
                .subtle: "Speak with quiet reflective sadness, a lowered pitch, a slightly slower pace, and a subdued restrained tone.",
                .normal: "Speak sadly and softly, with a lowered pitch, a slow weighted pace, and a fragile restrained tone; keep every word clear and audible.",
                .strong: "Speak through deep sorrow, fragile and tearful, with words slow and weighted with grief; keep every word clear and audible.",
            ]
        ),
        EmotionPreset(
            id: "angry",
            label: "Angry",
            sfSymbol: "flame",
            instructions: [
                .subtle: "Speak with quiet irritation, controlled and clipped, holding back the bigger feeling.",
                .normal: "Speak angrily and firmly, with sharp consonants, tight stress, forceful tension, and a lower clipped tone; never shout or scream.",
                .strong: "Speak with fierce open anger, hard biting consonants, a fast forceful attack, heated raised pitch, and strong projected volume; no screaming.",
            ]
        ),
        EmotionPreset(
            id: "fearful",
            label: "Fearful",
            sfSymbol: "exclamationmark.triangle",
            instructions: [
                .subtle: "Speak with quiet unease, cautious and hesitant, voice a little smaller than usual.",
                .normal: "Speak fearfully and anxiously, with a breathy shaky voice, uncertain pacing, and a smaller urgent tone; stay fully audible.",
                .strong: "Speak in trembling panic, voice quavering and urgent, with fast uneven pacing and a thin tight tone; stay fully audible.",
            ]
        ),
        EmotionPreset(
            id: "surprised",
            label: "Surprised",
            sfSymbol: "exclamationmark.2",
            instructions: [
                .subtle: "Speak with mild surprise, a light lift in pitch and a slightly quickened pace, as if just noticing something unexpected.",
                .normal: "Speak with clear surprise, pitch rising steeply on key words, a quick animated pace with brief catches, and wide swings between low and high; no gasping or extra sounds.",
                .strong: "Speak in sudden astonishment, the voice darting up and down with sharp pitch leaps at each discovery and quick catching bursts of pace; no gasping or extra sounds.",
            ]
        ),
        EmotionPreset(
            id: "excited",
            label: "Excited",
            sfSymbol: "sparkles",
            instructions: [
                .subtle: "Speak with a touch of enthusiasm, slightly energized and engaged, with a gentle lift in pitch.",
                .normal: "Speak excitedly, with a fast driving pace, bright ringing tone, higher pitch and louder volume than normal; no laughing or shouting.",
                .strong: "Speak with bursting excitement, a racing pace, big upward pitch leaps, a ringing bright tone, and emphatic peaks on every key word; no laughing or shouting.",
            ]
        ),
        EmotionPreset(
            id: "calm",
            label: "Calm",
            sfSymbol: "leaf",
            instructions: [
                .subtle: "Speak easily and unhurriedly, relaxed and warm throughout.",
                .normal: "Speak calmly and soothingly, with smooth unhurried pacing, low settled pitch, and reassuring warmth; no tension or urgency.",
                .strong: "Speak with serene meditative stillness, very slow and softly grounded, each phrase fully landed; no tension or urgency.",
            ]
        ),
        EmotionPreset(
            id: "whisper",
            label: "Whisper",
            sfSymbol: "ear",
            instructions: [
                .subtle: "Whisper gently, close-mic and quiet, with soft breath and easy pacing.",
                .normal: "Whisper throughout, hushed and breathy, every word voiced just above breath, close and confidential; never lift into normal speech.",
                .strong: "Whisper at the very edge of hearing, hushed flat breath with minimal pitch movement, close and secretive; every word still audible, never lifted into normal speech.",
            ]
        ),
        EmotionPreset(
            id: "dramatic",
            label: "Dramatic",
            sfSymbol: "theatermasks",
            instructions: [
                .subtle: "Speak with measured theatrical weight, leaning into key beats without overdoing it.",
                .normal: "Speak like a stage narrator, with sweeping rises and falls in pitch, firm stress landing on key words, deliberate pacing, and clear held pauses between phrases; no shouting.",
                .strong: "Speak with sweeping theatrical grandeur, a wide pitch range swinging from low to high, bold stress on key words, generous well-timed pauses, and a projected resonant tone; no shouting.",
            ]
        ),
    ]
}
