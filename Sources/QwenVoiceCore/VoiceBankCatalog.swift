import Foundation

/// Groups saved voices into emotion reference banks by the naming convention
/// the bank builder emits (`scripts/build_emotion_reference_bank.py`,
/// `docs/reference/emotion-reference-banks.md`): a persona's neutral anchor
/// is enrolled under the bare persona name, and each curated emotion
/// reference as "<Persona> (<Emotion>)". Grouping is resolved from names
/// alone — no persistence changes — so banks built by the pipeline, or
/// assembled by hand with the same naming, present identically.
///
/// Rules, deliberately conservative:
/// * a voice counts as a variant only when its suffix matches a live preset
///   (label or capitalized id) AND a voice with the bare base name exists;
/// * anything else — bases without variants, orphan "(X)" names whose base
///   is missing, unknown suffixes — stays a standalone voice untouched;
/// * variants are ordered by the preset roster's order, so every surface
///   lists deliveries identically.
public struct VoiceBankCatalog: Equatable, Sendable {
    public struct Persona: Equatable, Sendable {
        /// The neutral anchor's voice id (the bare persona name).
        public let baseVoiceID: String
        public let name: String
        /// Preset id → variant voice id, only for live-roster suffixes.
        public let variantVoiceIDs: [String: String]

        /// Variant (presetID, voiceID) pairs in preset roster order.
        public var orderedVariants: [(presetID: String, voiceID: String)] {
            EmotionPreset.all.compactMap { preset in
                variantVoiceIDs[preset.id].map { (preset.id, $0) }
            }
        }

        public func contains(voiceID: String) -> Bool {
            voiceID == baseVoiceID || variantVoiceIDs.values.contains(voiceID)
        }

        /// The preset id a member voice carries; nil for the neutral anchor.
        public func presetID(for voiceID: String) -> String? {
            variantVoiceIDs.first(where: { $0.value == voiceID })?.key
        }
    }

    /// Personas with at least one variant, sorted by name.
    public let personas: [Persona]
    /// Every voice id that belongs to some persona (base or variant).
    public let bankMemberVoiceIDs: Set<String>

    public func persona(containing voiceID: String?) -> Persona? {
        guard let voiceID else { return nil }
        return personas.first(where: { $0.contains(voiceID: voiceID) })
    }

    public static func build(voices: [(id: String, name: String)]) -> VoiceBankCatalog {
        let idsByName = Dictionary(voices.map { ($0.name, $0.id) }, uniquingKeysWith: { first, _ in first })
        var suffixToPresetID: [String: String] = [:]
        for preset in EmotionPreset.all {
            suffixToPresetID[preset.label.lowercased()] = preset.id
            suffixToPresetID[preset.id.lowercased()] = preset.id
        }

        var variantsByBase: [String: [String: String]] = [:]
        for voice in voices {
            guard voice.name.hasSuffix(")"),
                  let openParen = voice.name.range(of: " (", options: .backwards) else {
                continue
            }
            let base = String(voice.name[..<openParen.lowerBound])
            let suffix = String(voice.name[openParen.upperBound..<voice.name.index(before: voice.name.endIndex)])
            guard !base.isEmpty,
                  let presetID = suffixToPresetID[suffix.lowercased()],
                  idsByName[base] != nil else {
                continue
            }
            // First variant per (base, preset) wins; duplicates stay standalone
            // by simply not being recorded twice.
            variantsByBase[base, default: [:]].merge([presetID: voice.id]) { existing, _ in existing }
        }

        let personas = variantsByBase
            .compactMap { base, variants -> Persona? in
                guard let baseID = idsByName[base], !variants.isEmpty else { return nil }
                return Persona(baseVoiceID: baseID, name: base, variantVoiceIDs: variants)
            }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }

        var members = Set<String>()
        for persona in personas {
            members.insert(persona.baseVoiceID)
            members.formUnion(persona.variantVoiceIDs.values)
        }
        return VoiceBankCatalog(personas: personas, bankMemberVoiceIDs: members)
    }
}
