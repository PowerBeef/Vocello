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

        // P08-07: an unspaced Chinese or Japanese run is one "word" and reads
        // far slower than 16 characters per second, so CJK characters are
        // timed apart, per character (per syllable block in Korean), and the
        // rest of the text keeps the word and character rates below.
        let script = CJKScriptCount(text: trimmed)
        let rest = script.textWithoutCJK
        let words = rest
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .count
        let nonWhitespaceCharacters = rest.reduce(into: 0) { count, character in
            if !character.isWhitespace {
                count += 1
            }
        }
        let punctuationPauses = trimmed.reduce(into: 0) { count, character in
            if ".!?;:,\n。！？；：，、".contains(character) {
                count += 1
            }
        }

        let wordsPerSecond = 2.45
        let charactersPerSecond = 16.0
        let wordEstimate = Double(words) / wordsPerSecond
        let characterEstimate = Double(nonWhitespaceCharacters) / charactersPerSecond
        let pauseEstimate = Double(punctuationPauses) * 0.08
        return max(0.8, script.estimatedSeconds + max(wordEstimate, characterEstimate) + pauseEstimate)
    }
}

/// Han, kana and Hangul in a script, with the speaking rates of the committed
/// benchmark takes that `AudioSpeakingRateQC` cites: a median 0.26 s per
/// character in Chinese and 0.22 s in Japanese (Han read among kana counts as
/// Japanese). Korean has no committed take yet and borrows the Japanese rate,
/// as the speaking-rate QC does. The Unicode blocks match that QC's.
private struct CJKScriptCount {
    let han: Int
    let kana: Int
    let hangul: Int
    /// The text with every counted character replaced by a space.
    let textWithoutCJK: String

    init(text: String) {
        let space: Unicode.Scalar = " "
        var han = 0
        var kana = 0
        var hangul = 0
        var rest = String.UnicodeScalarView()
        for scalar in text.unicodeScalars {
            switch scalar.value {
            case 0x3040...0x30FF, 0x31F0...0x31FF, 0xFF66...0xFF9F:
                kana += 1
                rest.append(space)
            case 0x3400...0x4DBF, 0x4E00...0x9FFF, 0xF900...0xFAFF:
                han += 1
                rest.append(space)
            case 0x1100...0x11FF, 0x3130...0x318F, 0xAC00...0xD7AF:
                hangul += 1
                rest.append(space)
            default:
                rest.append(scalar)
            }
        }
        self.han = han
        self.kana = kana
        self.hangul = hangul
        textWithoutCJK = String(rest)
    }

    var estimatedSeconds: TimeInterval {
        let chineseSecondsPerCharacter = 0.26
        let japaneseSecondsPerCharacter = 0.22
        let hanSeconds = kana > 0 ? japaneseSecondsPerCharacter : chineseSecondsPerCharacter
        return Double(han) * hanSeconds + Double(kana + hangul) * japaneseSecondsPerCharacter
    }
}
