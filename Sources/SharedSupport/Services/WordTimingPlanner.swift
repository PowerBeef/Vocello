import Foundation

/// Linear word-timing splitter for karaoke transcripts. The engine emits no
/// per-token timestamps, so words are distributed evenly across the audio's
/// duration; whitespace runs are preserved as no-op spans so the rendered
/// string matches the source verbatim. Shared by the iOS Player sheet
/// (`IOSWordTimingPlanner` forwards here) and the macOS inline player card.
enum WordTimingPlanner {
    static func plan(transcript: String, audioDuration: TimeInterval) -> [WordSpan] {
        guard !transcript.isEmpty, audioDuration > 0 else {
            return [WordSpan(text: transcript, isWhitespace: false, start: 0, end: 0)]
        }

        var spans: [WordSpan] = []
        var wordSpanIndices: [Int] = []
        var current = ""
        var currentIsWhitespace: Bool? = nil

        func flush() {
            guard !current.isEmpty, let isWS = currentIsWhitespace else { return }
            spans.append(WordSpan(text: current, isWhitespace: isWS, start: 0, end: 0))
            if !isWS {
                wordSpanIndices.append(spans.count - 1)
            }
            current.removeAll(keepingCapacity: true)
            currentIsWhitespace = nil
        }

        for ch in transcript {
            let isWS = ch.isWhitespace
            if currentIsWhitespace == nil {
                currentIsWhitespace = isWS
            } else if currentIsWhitespace != isWS {
                flush()
                currentIsWhitespace = isWS
            }
            current.append(ch)
        }
        flush()

        guard !wordSpanIndices.isEmpty else {
            for i in spans.indices {
                spans[i].start = 0
                spans[i].end = audioDuration
            }
            return spans
        }

        let slice = audioDuration / Double(wordSpanIndices.count)
        for (i, spanIndex) in wordSpanIndices.enumerated() {
            spans[spanIndex].start = slice * Double(i)
            spans[spanIndex].end = slice * Double(i + 1)
        }
        var lastWordEnd: TimeInterval = 0
        for i in spans.indices {
            if spans[i].isWhitespace {
                spans[i].start = lastWordEnd
                spans[i].end = lastWordEnd
            } else {
                lastWordEnd = spans[i].end
            }
        }
        return spans
    }

    /// Index of the word span that contains `time`, or nil outside every span.
    static func activeIndex(in spans: [WordSpan], at time: TimeInterval) -> Int? {
        for (i, span) in spans.enumerated() where !span.isWhitespace {
            if time >= span.start && time < span.end {
                return i
            }
        }
        return nil
    }
}

struct WordSpan: Equatable, Sendable {
    var text: String
    var isWhitespace: Bool
    var start: TimeInterval
    var end: TimeInterval
}
