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
        if let alternate = EmotionPreset.experimentalInstruction(id: id, intensity: intensity) {
            return alternate
        }
        return instructions[intensity] ?? instructions[.normal] ?? DeliveryProfile.neutralInstruction
    }

    /// DP-3 experiment arm. Returns nil in production.
    ///
    /// `QWENVOICE_DELIVERY_INSTRUCTION_SET=short` swaps every preset for an
    /// official-style short form so the shipped long form can be measured
    /// against it on identical seeds. Registered in
    /// `config/runtime-debug-knobs.json` and inert without the `QWENVOICE_DEBUG`
    /// master gate, so production resolution is unchanged.
    ///
    /// The hypothesis: upstream's own Custom Voice examples are three to nine
    /// words and name the emotion plainly (`Very happy.`, `Say it in a very
    /// angry and disappointed tone`), while the shipped copy is ten to twenty
    /// times longer, avoids naming the emotion in favour of acoustic
    /// specification, and adds negative constraints. That contrast is documented
    /// in `docs/reference/qwen3-tts-prompting-guide.md` §9.1 and has never been
    /// measured. Whichever way it lands, the answer is worth having.
    static func experimentalInstruction(id: String, intensity: EmotionIntensity) -> String? {
        guard shortInstructionSetEnabled else { return nil }
        return shortInstructions[id]?[intensity]
    }

    private static let shortInstructionSetEnabled: Bool = {
        RuntimeDebugGate.value(for: "QWENVOICE_DELIVERY_INSTRUCTION_SET")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() == "short"
    }()

    /// Modelled directly on the documented upstream examples: a bare adjective
    /// phrase, or `Say it in a … tone`, with the strong tier adding the single
    /// intensifier those examples use freely.
    private static let shortInstructions: [String: [EmotionIntensity: String]] = [
        "neutral": [.normal: "Say it in a neutral tone.", .strong: "Say it in a neutral tone."],
        "happy": [.normal: "Happy.", .strong: "Very happy."],
        "sad": [.normal: "Sad.", .strong: "Very sad."],
        "angry": [.normal: "Say it in an angry tone.", .strong: "Say it in a very angry tone."],
        "fearful": [.normal: "Frightened.", .strong: "Very frightened."],
        "surprised": [.normal: "Surprised.", .strong: "Very surprised."],
        "calm": [.normal: "Calm.", .strong: "Very calm."],
        "whisper": [.normal: "Whisper it.", .strong: "Whisper it very quietly."],
    ]

    public static func preset(id: String?) -> EmotionPreset? {
        guard let id else { return nil }
        return all.first(where: { $0.id == id })
    }

    /// Resolve a stored instruction string back to the preset and tier that
    /// produced it, checking the `strong` tier first. Tiers with identical copy
    /// (Neutral) must resolve to `.strong`, the shipped tier: resolving the tie
    /// to `.normal` is the defect that made every macOS preset pick silently
    /// emit the normal-tier copy after the Neutral draft default synced
    /// (found by the 2026-08-04 delivery-control audit, F4 — DP-8's
    /// ship-strong decision never actually took effect on macOS).
    public static func matchInstruction(
        _ text: String
    ) -> (preset: EmotionPreset, intensity: EmotionIntensity)? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        for preset in all {
            for level in EmotionIntensity.allCases.reversed() {
                if preset.instruction(for: level).caseInsensitiveCompare(trimmed) == .orderedSame {
                    return (preset, level)
                }
            }
        }
        return nil
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
    // - SUPPORTED, and now MEASURED: combine emotion + pace + pitch + timbre in
    //   concrete acoustic wording. InstructTTSEval scores this checkpoint 77-83 on
    //   explicit acoustic specification against 61-64 on persona/role framing, and
    //   DP-3 confirmed it directly on 2026-08-02: this long APS-shaped copy beat an
    //   official-style short form (`Very happy.`) 57 surviving features to 33 over
    //   12 paired seeds. Do NOT shorten this copy toward the upstream examples --
    //   that experiment is done and the shorter form lost. Volume, speed, and tone
    //   (distinct from emotion) remain scored features this copy underuses.
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
    //
    // REMOVED 2026-08-03, maintainer decision on DP-10 (18 seeds x 10 shipped
    // cells, one cell per preset since the intensity control was retired):
    // `excited` folded into `happy`, `dramatic` dropped. Both scored *below* a
    // 0.100 chance floor in the 10-way separability test (0.056 each) while the
    // set as a whole reached UAR 0.311, so they were not merely weak controls --
    // they were worse than guessing. Scoring the high-arousal cluster
    // (happy/excited/surprised/dramatic) against only each other gave UAR 0.278
    // against a 0.250 chance floor: 1.11x chance, i.e. the model emits
    // essentially one acoustic output for all four.
    //
    // The tempting fix -- rewrite the copy -- is ruled out by the same run.
    // Mean prosodyEffect is uncorrelated with separability (dramatic 8.2,
    // excited 8.9, happy 9.5, whole set 6.5-9.5), so these instructions were not
    // under-driving; every preset moves prosody hard and they all move it along
    // the same axis. That is the arousal axis saturating, which the research
    // corpus reports as ~91% classifiable against ~55% for valence -- and
    // valence is the only thing separating happy from excited. `dramatic` sat
    // nearest to `neutral` (d=1.07, the smallest distance in the matrix): a
    // large prosodic effect that is not legible as the thing it names.
    //
    // Do NOT reintroduce either preset on the strength of rewritten copy alone.
    // DP-3 (long vs short form), DP-4 (prosodic null), DP-5 (merge form), and
    // DP-6 all varied instruction *wording*; none moved this. Re-earning a slot
    // takes a separability measurement, not a better sentence.
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
    ]
}
