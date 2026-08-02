import Foundation

// Single source of truth for the delivery (tone/emotion) presets, shared by the
// macOS app, the iOS app, and the `vocello` CLI (bench/review delivery cells).
// Previously duplicated as Sources/Models/EmotionPreset.swift and
// Sources/iOSSupport/Models/EmotionPreset.swift, which had to be edited in
// lockstep; consolidated here so preset copy changes land once.

// Two calibrated tiers (maintainer decision 2026-08-01): the former "subtle"
// tier measured below the prosody noise floor (its delivery-gate minimum
// effect had to be zero), so it shipped takes indistinguishable from no
// preset. Normal and strong both clear the 0.85 adherence gate with a
// measured magnitude difference. Legacy saved drafts that carried a subtle
// instruction round-trip through `DeliveryInputState(legacyEmotion:)` into
// custom text, preserving their exact behavior.
public enum EmotionIntensity: Int, CaseIterable, Identifiable, Sendable {
    case normal = 1
    case strong = 2

    public var id: Int { rawValue }

    public var label: String {
        switch self {
        case .normal: "Normal"
        case .strong: "Strong"
        }
    }

    public var rpcValue: String {
        switch self {
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

    /// The Neutral preset's real instruction (adopted 2026-08-01, maintainer
    /// decision closing finding F4): Neutral is a preset like any other — a
    /// slightly monotone, emotion-free delivery target — rather than the
    /// absence of an instruction. The measured alternative (sending nothing)
    /// left cross-seed delivery unconstrained (2.70 st pitch wander).
    /// Programmatic requests with no delivery style remain uninstructed;
    /// typed neutral synonyms ("neutral", "normal tone") still drop via
    /// `DeliveryProfile.isNeutralInstruction`.
    public static let neutralPresetInstruction =
        "Speak in an even, level tone, slightly monotone, with steady measured pacing and no noticeable emotion; plain and matter-of-fact throughout."

    // Instruction-writing canon. Written without citations and audited 2026-08-02
    // against primary sources; docs/reference/qwen3-tts-prompting-guide.md §9 holds
    // the adjudication and references. Provenance, so a future reader can tell which
    // of these is load-bearing:
    // - SUPPORTED: combine emotion + pace + pitch + timbre in concrete acoustic
    //   wording. InstructTTSEval scores this checkpoint 77-83 on explicit acoustic
    //   specification against 61-64 on persona/role framing. Volume, speed, and tone
    //   (distinct from emotion) are also scored features that this copy underuses.
    // - UNVERIFIED: negative constraints for high-arousal emotions (no laughing /
    //   shouting / gasping). No upstream source endorses them, and the nearest
    //   published ablation found bare paralinguistic tags *reduced* adherence.
    // - UNVERIFIED: imperative verbs (Speak / Whisper / Narrate) are followed more
    //   reliably. Upstream examples use imperative and descriptive forms alike.
    // - UNVERIFIED: intelligibility clauses for quiet/fragile tiers. The vendor-
    //   documented cousin is a closing recording-quality anchor, a different
    //   mechanism; ours is a mid-string command to the speaker, and its wording is
    //   what makes the English diction append land unevenly across tiers (below).
    // - PARTLY CONTRADICTED: avoid stacked intensifiers. Repetition adding nothing is
    //   defensible; upstream's own examples are "Very happy." and "Say it in a very
    //   angry and disappointed tone". The 500-character cap has no traceable origin.
    //
    // Known confound, FIXED 2026-08-02: happy, surprised, and dramatic suppressed
    // the English diction append on `normal` but not on `strong`, so those three
    // presets differed across tiers by 76 characters of unrelated boilerplate as
    // well as by emotional wording, and the intensity finding below was measured
    // over a matrix that included them. The append now resolves preset-wide in
    // GenerationSemantics, and scripts/check_delivery_instructions.py fails the
    // build if that resolution is removed or a new preset reintroduces the split.
    // Whether the sentence earns its place at all is still open: A/B it with
    // QWENVOICE_ENGLISH_DICTION_REINFORCEMENT=off before rewriting any copy.
    //
    // On the intensity tier, and a fix that did NOT work (measured 2026-08-02):
    //
    // The `strong` tier does not currently earn its place. Over a 19-seed x
    // 20-cell matrix the mean inter-cell separation at strong was 2.435 against
    // 2.442 at normal — a ratio of 0.997, meaning intensity moves cells sideways
    // rather than further apart. A blind listening check agreed: excited.strong
    // versus excited.normal was the one "close" pair a listener rated as merely
    // very similar rather than different.
    //
    // The tiers that amplify best (calm 1.82x, happy 1.45x) re-state their own
    // normal axes with stronger adjectives, while the ones that saturate
    // (dramatic 0.18x, excited 0.63x, angry 0.64x) swap in different axes. Two
    // are outright self-contradictions across tiers: angry asks for "a lower
    // clipped tone" then "heated raised pitch", fearful for "breathy" then "a
    // thin tight tone".
    //
    // Rewriting those five so `strong` pushed the same axes harder was tried and
    // REJECTED. Against four unchanged control presets (drift 0.02-0.35 in tier
    // distance at n=9), the rewrite regressed whisper -0.72, fearful -1.15 and
    // excited -0.61, with dramatic +0.22 and angry +0.09 inside the noise floor;
    // overall spread ratio was unchanged at 0.982. The mechanism is clear in
    // hindsight: making the two instruction *texts* more alike makes the model's
    // *output* more alike, so internal consistency traded away the very
    // differentiation the tier needs. Do not retry that specific fix.
    //
    // The self-contradictions above are still worth removing on their own terms,
    // but removing them must be measured, not assumed — and a candidate needs
    // enough seeds to clear a ~0.35 noise floor, which n=9 does not.
    // Verify with scripts/delivery_matrix_report.py, never by reading text back.
    public static let all: [EmotionPreset] = [
        EmotionPreset(
            id: "neutral",
            label: "Neutral",
            sfSymbol: "face.dashed",
            instructions: [
                .normal: EmotionPreset.neutralPresetInstruction,
                .strong: EmotionPreset.neutralPresetInstruction,
            ]
        ),
        EmotionPreset(
            id: "happy",
            label: "Happy",
            sfSymbol: "face.smiling",
            instructions: [
                .normal: "Speak happily and warmly, with a clearly lifted pitch, a light bouncing rhythm, a bright smiling tone, and quick cheerful pacing; no laughing.",
                .strong: "Speak joyfully and energetically, with a noticeably higher pitch and louder volume, a fast animated pace, a bright ringing tone, and strong rising emphasis on key words; no laughing or shouting.",
            ]
        ),
        EmotionPreset(
            id: "sad",
            label: "Sad",
            sfSymbol: "cloud.rain",
            instructions: [
                .normal: "Speak sadly and softly, with a lowered pitch, a slow weighted pace, and a fragile restrained tone; keep every word clear and audible.",
                .strong: "Speak through deep sorrow, fragile and tearful, with words slow and weighted with grief; keep every word clear and audible.",
            ]
        ),
        EmotionPreset(
            id: "angry",
            label: "Angry",
            sfSymbol: "flame",
            instructions: [
                .normal: "Speak angrily and firmly, with sharp consonants, tight stress, forceful tension, and a lower clipped tone; never shout or scream.",
                .strong: "Speak with fierce open anger, hard biting consonants, a fast forceful attack, heated raised pitch, and strong projected volume; no screaming.",
            ]
        ),
        EmotionPreset(
            id: "fearful",
            label: "Fearful",
            sfSymbol: "exclamationmark.triangle",
            instructions: [
                .normal: "Speak fearfully and anxiously, with a breathy shaky voice, uncertain pacing, and a smaller urgent tone; stay fully audible.",
                .strong: "Speak in trembling panic, voice quavering and urgent, with fast uneven pacing and a thin tight tone; stay fully audible.",
            ]
        ),
        EmotionPreset(
            id: "surprised",
            label: "Surprised",
            sfSymbol: "exclamationmark.2",
            instructions: [
                .normal: "Speak with clear surprise, pitch rising steeply on key words, a quick animated pace with brief catches, and wide swings between low and high; no gasping or extra sounds.",
                .strong: "Speak in sudden astonishment, the voice darting up and down with sharp pitch leaps at each discovery and quick catching bursts of pace; no gasping or extra sounds.",
            ]
        ),
        EmotionPreset(
            id: "excited",
            label: "Excited",
            sfSymbol: "sparkles",
            instructions: [
                .normal: "Speak excitedly, with a fast driving pace, bright ringing tone, higher pitch and louder volume than normal; no laughing or shouting.",
                .strong: "Speak with bursting excitement, a racing pace, big upward pitch leaps, a ringing bright tone, and emphatic peaks on every key word; no laughing or shouting.",
            ]
        ),
        EmotionPreset(
            id: "calm",
            label: "Calm",
            sfSymbol: "leaf",
            instructions: [
                .normal: "Speak calmly and soothingly, with smooth unhurried pacing, low settled pitch, and reassuring warmth; no tension or urgency.",
                .strong: "Speak with serene meditative stillness, very slow and softly grounded, each phrase fully landed; no tension or urgency.",
            ]
        ),
        EmotionPreset(
            id: "whisper",
            label: "Whisper",
            sfSymbol: "ear",
            instructions: [
                .normal: "Whisper throughout, hushed and breathy, every word voiced just above breath, close and confidential; never lift into normal speech.",
                .strong: "Whisper at the very edge of hearing, hushed flat breath with minimal pitch movement, close and secretive; every word still audible, never lifted into normal speech.",
            ]
        ),
        EmotionPreset(
            id: "dramatic",
            label: "Dramatic",
            sfSymbol: "theatermasks",
            instructions: [
                .normal: "Speak like a stage narrator, with sweeping rises and falls in pitch, firm stress landing on key words, deliberate pacing, and clear held pauses between phrases; no shouting.",
                .strong: "Speak with sweeping theatrical grandeur, a wide pitch range swinging from low to high, bold stress on key words, generous well-timed pauses, and a projected resonant tone; no shouting.",
            ]
        ),
    ]
}
