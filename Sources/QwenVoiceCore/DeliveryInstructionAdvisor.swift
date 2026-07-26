import Foundation

/// Advisory-only detection of delivery-text directives the engine cannot
/// honor. Qwen3-TTS consumes the delivery instruction as style conditioning;
/// it has no mechanism to target a requested total duration, so directives
/// like "finish within 20 seconds" silently distort pacing instead of being
/// obeyed. Detection informs the input UI; it never blocks generation and
/// never rewrites the user's text.
public enum DeliveryInstructionAdvisor {
    /// English + French total-duration directive shapes. Deliberately narrow:
    /// pause or beat instructions ("a two-second pause between sentences")
    /// are pacing style, partially honored, and must not trigger the
    /// advisory.
    private static let durationDirectivePatterns: [String] = [
        // "within 20 seconds", "in under 15 secs", "in less than 2 minutes",
        // "in no more than 30 seconds"
        #"\b(?:within|in\s+under|in\s+less\s+than|in\s+no\s+more\s+than|in\s+at\s+most)\s+\d+(?:[.,]\d+)?\s*(?:seconds?|secs?|minutes?|mins?)\b"#,
        // "finish in 20 seconds", "wrap up in 30s", "complete this in 1 minute",
        // "end by 45 seconds", "read it in 10 seconds"
        #"\b(?:finish(?:es|ed|ing)?|complete[sd]?|completing|wrap(?:s|ped|ping)?(?:\s+it)?\s*(?:up)?|end(?:s|ed|ing)?|say\s+(?:it|this)|read\s+(?:it|this))\b[^.,;\n]{0,30}?\b(?:in|within|by|under)\s+\d+(?:[.,]\d+)?\s*(?:seconds?|secs?|s|minutes?|mins?|m)\b"#,
        // "20 seconds or less", "30 seconds max", "15 seconds tops",
        // "45 seconds total"
        #"\b\d+(?:[.,]\d+)?\s*(?:seconds?|secs?|minutes?|mins?)\s+(?:or\s+less|or\s+under|max(?:imum)?|tops|total|overall)\b"#,
        // "a total duration of 30 seconds", "length of 20 seconds"
        #"\b(?:duration|length|running\s+time|runtime)\s+of\s+\d+(?:[.,]\d+)?\s*(?:seconds?|secs?|minutes?|mins?)\b"#,
        // FR: "en moins de 20 secondes", "en 30 secondes", "sous 15 secondes"
        #"\b(?:en\s+moins\s+de|en|sous)\s+\d+(?:[.,]\d+)?\s*(?:secondes?|minutes?)\b"#,
        // FR: "durée de 30 secondes"
        #"\b(?:durée|duree)\s+de\s+\d+(?:[.,]\d+)?\s*(?:secondes?|minutes?)\b"#,
    ]

    /// The first duration-style directive found in the instruction, or nil
    /// when none is present. The match is returned for advisory messaging.
    public static func firstDurationDirective(in instruction: String) -> String? {
        let trimmed = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        for pattern in durationDirectivePatterns {
            guard let regex = try? NSRegularExpression(
                pattern: pattern,
                options: [.caseInsensitive]
            ) else { continue }
            let range = NSRange(trimmed.startIndex..., in: trimmed)
            if let match = regex.firstMatch(in: trimmed, range: range),
               let swiftRange = Range(match.range, in: trimmed) {
                return String(trimmed[swiftRange])
            }
        }
        return nil
    }

    public static func hasDurationDirective(_ instruction: String) -> Bool {
        firstDurationDirective(in: instruction) != nil
    }

    /// Shared advisory copy for input surfaces. Pure information; the text is
    /// still sent unchanged if the user generates anyway.
    public static let advisoryMessage =
        "Timing requests aren’t honored — the voice can’t target a duration, so this may distort pacing instead."
}
