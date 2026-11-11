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

    /// The audio the preview queues before it starts.
    ///
    /// Without a measured `pace` this is the smooth-first buffer:
    /// `max(minimum, min(maximum, estimate * fraction))`, capped by the
    /// estimate. With one, a take that is arriving faster than it plays needs
    /// less (RF-48): once the pace, less a safety margin, is at or above
    /// `LivePreviewPace.comfortablePace` the buffer only has to cover the
    /// spacing of the chunks, and between real time and that pace the two
    /// buffers are blended. A take at or below real time keeps the
    /// smooth-first buffer, so a slow device waits no longer than before.
    func requiredBufferDuration(
        minimumBufferedDuration: TimeInterval,
        maximumBufferedDuration: TimeInterval = 8,
        fraction: Double = 0.35,
        pace: Double? = nil
    ) -> TimeInterval {
        guard estimatedAudioDuration > 0 else { return 0 }
        let smoothBuffer = max(
            minimumBufferedDuration,
            min(maximumBufferedDuration, estimatedAudioDuration * fraction)
        )
        let conservative = min(estimatedAudioDuration, smoothBuffer)
        guard let pace, pace.isFinite else { return conservative }
        let safePace = pace * LivePreviewPace.safetyFactor
        guard safePace > 1 else { return conservative }
        let jitterBuffer = min(conservative, LivePreviewPace.jitterBufferDuration)
        let headroom = min(1, (safePace - 1) / (LivePreviewPace.comfortablePace - 1))
        return conservative + (jitterBuffer - conservative) * headroom
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

/// How fast a take's audio is arriving at the player, measured from the take's
/// own chunks (RF-48): audio seconds received per second of wall time since
/// its first chunk. The first chunk's own audio is left out, because the time
/// before it (prompt and prefill) is not part of the steady rate.
///
/// The preview uses it to stop waiting for a buffer it does not need. On a
/// Mac or an iPhone that generates two to four times faster than playback,
/// the fixed 3.25-second buffer delayed the first sound by most of a second
/// for no gain; a device at or below real time keeps that buffer.
struct LivePreviewPace: Equatable, Sendable {
    /// Chunks after the first before the pace is trusted.
    static let minimumChunks = 2
    /// Wall time after the first chunk before the pace is trusted.
    static let minimumSpan: TimeInterval = 0.25
    /// The measured pace is discounted by this much: generation slows as a
    /// device warms, and an early measurement is the fastest it will be.
    static let safetyFactor = 0.8
    /// At this discounted pace and above, only the jitter buffer is kept.
    static let comfortablePace = 1.5
    /// The least queued audio a fast take starts from. The pace is trusted
    /// only after two chunks follow the first, so three chunks (1.2 s or more
    /// at the engine's chunk sizes) are queued by then and this floor rarely
    /// binds; it is what a resumed or re-evaluated start is held to.
    static let jitterBufferDuration: TimeInterval = 0.8

    private var firstChunkAt: TimeInterval?
    private var latestChunkAt: TimeInterval = 0
    private var audioAfterFirstChunk: TimeInterval = 0
    private var chunksAfterFirst = 0
    private var unmeasurable = false

    /// Records one chunk received from the engine at `now` (monotonic
    /// seconds). A time that runs backwards makes the take unmeasurable.
    mutating func record(chunkAudioSeconds: TimeInterval, at now: TimeInterval) {
        guard !unmeasurable else { return }
        guard let firstChunkAt else {
            self.firstChunkAt = now
            latestChunkAt = now
            return
        }
        guard now >= latestChunkAt, now >= firstChunkAt, chunkAudioSeconds >= 0 else {
            unmeasurable = true
            return
        }
        latestChunkAt = now
        audioAfterFirstChunk += chunkAudioSeconds
        chunksAfterFirst += 1
    }

    /// A take promoted from the queue behind another take has no pace, with
    /// or without stored chunks: the chunks it replays did not reach the
    /// player as they were generated, so their arrival times say nothing
    /// about how fast it is generated.
    mutating func markUnmeasurable() {
        unmeasurable = true
    }

    /// Audio seconds received per wall second since the first chunk; nil
    /// until enough chunks and time have passed to trust it.
    var audioSecondsPerSecond: Double? {
        guard !unmeasurable, let firstChunkAt, chunksAfterFirst >= Self.minimumChunks else { return nil }
        let span = latestChunkAt - firstChunkAt
        guard span >= Self.minimumSpan else { return nil }
        return audioAfterFirstChunk / span
    }
}
