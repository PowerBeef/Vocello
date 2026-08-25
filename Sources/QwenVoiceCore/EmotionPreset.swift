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

public struct DeliveryInstructionCell: Equatable, Sendable {
    public let id: String
    public let preset: EmotionPreset
    public let intensity: EmotionIntensity
    public let instruction: String

    public init(preset: EmotionPreset, intensity: EmotionIntensity) {
        self.id = "\(preset.id).\(intensity.rpcValue)"
        self.preset = preset
        self.intensity = intensity
        self.instruction = preset.instruction(for: intensity)
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id && lhs.instruction == rhs.instruction
    }

    /// Resolve the canonical diagnostics/receipt spelling. Unlike user-facing
    /// convenience parsing, this boundary deliberately requires both the
    /// preset and intensity so retained evidence never has an implicit tier.
    public static func resolveStrict(_ rawValue: String) throws -> Self {
        let token = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = token.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 2,
              let preset = EmotionPreset.preset(id: parts[0]) else {
            throw DeliveryInstructionCellError.invalidCell(token)
        }
        guard let intensity = EmotionIntensity.allCases.first(where: {
            $0.rpcValue == parts[1]
        }) else {
            throw DeliveryInstructionCellError.invalidIntensity(parts[1])
        }
        return Self(preset: preset, intensity: intensity)
    }
}

public enum DeliveryInstructionCellError: LocalizedError, Equatable, Sendable {
    case invalidCell(String)
    case invalidIntensity(String)

    public var errorDescription: String? {
        switch self {
        case .invalidCell(let value):
            let known = EmotionPreset.all.map(\.id).joined(separator: ", ")
            return "Unknown delivery cell '\(value)'. Use <preset>.<intensity>; presets: \(known)."
        case .invalidIntensity(let value):
            return "Unknown delivery intensity '\(value)'. Use normal or strong."
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
    /// official-style short form. `candidate-v2` selects the multi-speaker
    /// remediation arm. Both are measurement-only alternatives to the shipped
    /// copy and can be compared on identical seeds. Registered in
    /// `config/runtime-debug-knobs.json` and inert without the `QWENVOICE_DEBUG`
    /// master gate, so production resolution is unchanged.
    ///
    /// The hypothesis: upstream's own Custom Voice examples are three to nine
    /// words and name the emotion plainly (`Very happy.`, `Say it in a very
    /// angry and disappointed tone`), while the shipped copy is ten to twenty
    /// times longer, avoids naming the emotion in favour of acoustic
    /// specification, and adds negative constraints. That contrast is documented
    /// in `docs/reference/qwen3-tts-prompting-guide.md` §9.1; DP-3 measured and
    /// retained the long register. The candidate-v2 arm therefore stays long and
    /// tests clearer target naming and fewer conflicting clauses instead.
    static func experimentalInstruction(id: String, intensity: EmotionIntensity) -> String? {
        switch experimentalInstructionSet {
        case "short":
            return shortInstructions[id]?[intensity]
        case "candidate-v2":
            return candidateV2Instructions[id]?[intensity]
        default:
            return nil
        }
    }

    private static let experimentalInstructionSet: String? = {
        RuntimeDebugGate.value(for: "QWENVOICE_DELIVERY_INSTRUCTION_SET")?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
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

    /// Multi-speaker candidate arm written after the 2026-08-22 9-voice ×
    /// 8-preset × 5-seed screen. It keeps the long explicit register that beat
    /// the upstream-style short prompts in DP-3, removes unsupported negative
    /// clauses where possible, names each target unmistakably, and avoids
    /// wording that asks the model to manufacture long silences. This is not
    /// production copy until a same-seed matrix shows a speaker-generalized
    /// improvement without a QC or separability regression.
    ///
    /// RESULT 2026-08-22: rejected as a production set after an exact same-seed
    /// 9-speaker × 8-preset × 5-seed comparison. Acoustic adherence was unchanged
    /// (182/360 in both arms) and held-speaker UAR regressed 0.342 → 0.306.
    /// `surprised.strong` is the only cell that improved both profile adherence
    /// (+4/45) and held-speaker recall (+0.200), but its paired exact p=0.289 and
    /// exploratory selection require a fresh pre-registered holdout before any
    /// copy change. The arm remains debug-only so the null is reproducible.
    private static let candidateV2Instructions: [String: [EmotionIntensity: String]] = [
        "neutral": [
            .normal: "Sound completely neutral and matter-of-fact, with an even level pitch, steady measured pace, and no noticeable emotion.",
            .strong: "Sound completely neutral and matter-of-fact, with an even level pitch, steady measured pace, and no noticeable emotion.",
        ],
        "happy": [
            .normal: "Sound unmistakably happy and delighted: smile through the words, with a brighter higher pitch, lively upward melody, and quick buoyant pacing.",
            .strong: "Sound intensely joyful and delighted: smile broadly through the words, with a bright high pitch, lively upward melody, and fast buoyant pacing.",
        ],
        "sad": [
            .normal: "Sound unmistakably sad and grief-stricken, with a low subdued pitch, reduced energy, flattened melody, and slow weighted pacing; keep the sentence flowing and clear.",
            .strong: "Sound deeply sorrowful and grief-stricken, with a very low subdued pitch, restrained energy, flattened melody, and slow weighted pacing; keep the sentence flowing and clear.",
        ],
        "angry": [
            .normal: "Sound unmistakably angry and frustrated, with a tense forceful voice, hard consonants, clipped emphasis, and quick emphatic pacing; stay controlled rather than shouting.",
            .strong: "Sound fiercely angry and frustrated, with an intensely tense forceful voice, biting consonants, hard clipped emphasis, and fast emphatic pacing; stay controlled rather than shouting.",
        ],
        "fearful": [
            .normal: "Sound unmistakably frightened and anxious, with a high tight shaky voice, trembling pitch, uneven urgent pacing, and brief hesitant catches; keep every word audible.",
            .strong: "Sound terrified and panicked, with a very high tight shaky voice, strongly trembling pitch, uneven urgent pacing, and brief startled catches; keep every word audible.",
        ],
        "surprised": [
            .normal: "Sound unmistakably surprised and astonished, with a sudden pitch lift, key words jumping sharply upward, wide pitch movement, and quick startled pacing.",
            .strong: "Sound intensely astonished, with a sudden high pitch lift, key words leaping sharply upward, very wide pitch movement, and quick startled pacing.",
        ],
        "calm": [
            .normal: "Sound deeply calm and reassuring, with a low settled pitch, soft steady energy, smooth unhurried pacing, and gentle even phrasing.",
            .strong: "Sound serenely calm and reassuring, with a very low settled pitch, quiet steady energy, very smooth unhurried pacing, and gentle even phrasing.",
        ],
        "whisper": [
            .normal: "Whisper every word in an airy breathy voice with very little voicing, close and confidential; keep the sentence flowing and intelligible without returning to normal speech.",
            .strong: "Whisper every word at the edge of breath with minimal voicing, very airy and close; keep the sentence flowing and intelligible without returning to normal speech.",
        ],
    ]

    public static func preset(id: String?) -> EmotionPreset? {
        guard let id else { return nil }
        return all.first(where: { $0.id == id })
    }

    /// Resolve a stored instruction string back to the preset and tier that
    /// produced it, checking the `strong` tier first. Tiers with identical copy
    /// (Neutral) must resolve to `.strong` — Neutral's shipped tier: resolving
    /// the tie to `.normal` is the defect that made every macOS preset pick
    /// silently emit the normal-tier copy after the Neutral draft default
    /// synced (found by the 2026-08-04 delivery-control audit, F4 — DP-8's
    /// ship-strong decision never actually took effect on macOS). Distinct-copy
    /// tiers resolve to exactly what was stored, which is what keeps legacy
    /// drafts stable across shipped-tier changes (`shippedIntensity`).
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

    /// The measured roster split (DP-12 calibration session, 2026-08-04;
    /// docs/reference/delivery-control-audit-2026-08.md finding record in
    /// docs/development-progress.md finding 14). Listeners identify these
    /// four presets above chance (calm 0.55, whisper 0.55, neutral 0.36,
    /// sad 0.36), so the UI presents them as distinct deliveries. The
    /// remaining four moved prosody hard but were not identified as
    /// themselves (angry 0/11 — never once named Angry; happy heard as
    /// Surprised; fearful heard as Sad; surprised mostly Unsure), so they
    /// present as directional hints that shape energy and pace without
    /// promising the named emotion. Membership changes require a new
    /// listening measurement, not taste.
    public static let distinctDeliveryIDs: Set<String> = ["neutral", "calm", "whisper", "sad"]

    /// Honest framing for the hint half of the roster, shared by both
    /// platforms so the wording cannot drift.
    public static let directionalHintAdvisory =
        "Directional hints shape energy and pace reliably, but the named emotion may not come through on every take. Regenerate to explore, or clone from an emotion reference voice for a dependable delivery."

    public var isDirectionalHint: Bool {
        !EmotionPreset.distinctDeliveryIDs.contains(id)
    }

    /// Presets whose shipped copy is the `normal` tier (maintainer call
    /// 2026-08-15, executing DP-22's pre-registered branch (a): per-preset
    /// tier selection under DP-8's ship-the-measured-better-copy rule).
    /// The user-facing intensity control stays retired; this set is the one
    /// place the shipped tier deviates from the DP-8 strong anchor.
    ///
    /// Evidence: the normal tier is the only channel ever measured to carry
    /// the happy/angry distinction — DP-22's confirmatory acoustic probe
    /// (UAR 0.765 vs the 0.5 floor, perm p=0.007, 4-bit arm) replicating
    /// DP-12's blind 2AFC (0.75 at normal, chance at strong). happy.normal
    /// is the only FDR-clear happy cell in any arm (happy.strong fails FDR
    /// everywhere and was heard as Surprised); instruct angry.strong was
    /// never identified in listening (0/11) despite roster-level acoustic
    /// clearance, and DP-6's angry.strong feature-power edge measures copy
    /// adherence, not the valence separation this selection optimizes.
    /// DP-23's cross-tier candidate (angry.strong + happy.normal) failed
    /// its confirmatory probe, so the pair ships the confirmed
    /// both-at-normal configuration. Everything else keeps the strong
    /// anchor: the distinct set clears FDR in both DP-18 arms at strong and
    /// DP-12's 2AFC found control pairs MORE discriminable at strong.
    /// Membership changes require a new measurement, not taste.
    public static let normalTierShippedIDs: Set<String> = ["happy", "angry"]

    /// The tier a fresh preset selection ships. Legacy drafts keep resolving
    /// to exactly the tier string they stored (`matchInstruction` /
    /// `DeliveryInputState(legacyEmotion:)` contracts are unchanged).
    public var shippedIntensity: EmotionIntensity {
        EmotionPreset.normalTierShippedIDs.contains(id) ? .normal : .strong
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
    // (dramatic 0.18x, excited 0.63x, angry 0.64x) swap in different axes. Before
    // the maintainer-directed 2026-08-24 remediation, two were outright
    // self-contradictions across tiers: angry asked for "a lower clipped tone"
    // then "heated raised pitch", while fearful asked for "breathy" then "a
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
    // Those self-contradictions were removed on 2026-08-24 as part of a
    // maintainer-directed valence, dominance, and temporal-contour remediation.
    // This is an attributed production-copy decision, not a measured improvement
    // claim; DP-30 through DP-32 retain the source-bound and blinded confirmation.
    // A candidate still needs enough seeds to clear the measured noise floor.
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
                .normal: "Speak with genuine warm delight and a relaxed smile in the voice. Use bright open resonance, smooth, clear, buoyant phrasing, a moderately lifted pitch, and a naturally lively pace; sustain pleasant warmth rather than sounding startled.",
                .strong: "Speak with radiant joy and unmistakable positive warmth. Use a broad smiling resonance, smooth, clear, buoyant phrasing, a noticeably higher pitch, and energetic but flowing pacing; sustain delighted warmth rather than sounding startled.",
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
                .normal: "Speak with controlled resentment and unmistakable irritation. Use a dry tense resonance, clipped consonants, compressed phrasing, and sharp deliberate stress; sound hostile and confrontational rather than energetic or triumphant.",
                .strong: "Speak with fierce controlled anger and seething resentment. Use a harsher tense resonance, biting consonants, compressed forceful phrasing, and hard deliberate stress; sound openly hostile and confrontational rather than excited or triumphant.",
            ]
        ),
        EmotionPreset(
            id: "fearful",
            label: "Fearful",
            sfSymbol: "exclamationmark.triangle",
            instructions: [
                .normal: "Speak as though danger is close and confidence is slipping. Use a tight unsteady voice, hesitant starts, unstable pitch, and tentative rising endings; sound afraid rather than sorrowful.",
                .strong: "Speak in vulnerable panic, as though danger is immediate and control is failing. Use a tight trembling voice, hesitant starts, uneven urgent phrasing, unstable pitch, and tentative rising endings; sound frightened rather than mournful.",
            ]
        ),
        EmotionPreset(
            id: "surprised",
            label: "Surprised",
            sfSymbol: "exclamationmark.2",
            instructions: [
                .normal: "React as though one unexpected fact has just landed. Use a brief startled onset and one sudden pitch jump on the first important word, then settle quickly into clear natural phrasing; sound astonished rather than continuously excited.",
                .strong: "React with intense astonishment to a completely unexpected revelation. Use a sharp startled onset and one abrupt high pitch leap on the first important word, then settle quickly into clear natural phrasing instead of staying excited throughout.",
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
