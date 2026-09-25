import Foundation

/// Prompt-derived forecast of a take's audio length. The shared player sizes
/// its live-preview buffer from it and the Studio live cards show it. It lives
/// apart from `AudioPlayerViewModel` so code compiled without the player (the
/// long-form runner under `VocelloCoreTests`) can use it too (PA-19).
struct LivePreviewEstimate: Equatable, Sendable {
    let estimatedAudioDuration: TimeInterval

    init?(text: String) {
        let estimate = Self.estimatedAudioDuration(for: text)
        guard estimate > 0 else { return nil }
        estimatedAudioDuration = estimate
    }

    func requiredBufferDuration(
        minimumBufferedDuration: TimeInterval,
        maximumBufferedDuration: TimeInterval = 8,
        fraction: Double = 0.35
    ) -> TimeInterval {
        guard estimatedAudioDuration > 0 else { return 0 }
        let smoothBuffer = max(
            minimumBufferedDuration,
            min(maximumBufferedDuration, estimatedAudioDuration * fraction)
        )
        return min(estimatedAudioDuration, smoothBuffer)
    }

    private static func estimatedAudioDuration(for text: String) -> TimeInterval {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return 0 }

        let words = trimmed
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .count
        let nonWhitespaceCharacters = trimmed.reduce(into: 0) { count, character in
            if !character.isWhitespace {
                count += 1
            }
        }
        let punctuationPauses = trimmed.reduce(into: 0) { count, character in
            if ".!?;:,\n".contains(character) {
                count += 1
            }
        }

        let wordsPerSecond = 2.45
        let charactersPerSecond = 16.0
        let wordEstimate = Double(words) / wordsPerSecond
        let characterEstimate = Double(nonWhitespaceCharacters) / charactersPerSecond
        let pauseEstimate = Double(punctuationPauses) * 0.08
        return max(0.8, max(wordEstimate, characterEstimate) + pauseEstimate)
    }
}
