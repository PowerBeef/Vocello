import Foundation

/// Shared benchmark matrix corpus + iteration spec for `vocello bench` and the macOS UI bench.
/// Keep identical to `benchmarks/baseline-*-length-sweep.md` and
/// `scripts/summarize_generation_telemetry.py` len-bucket thresholds.
public enum BenchMatrixSpec {
    public static let corpus: [(len: String, text: String)] = [
        ("short", "The train left the station at dawn."),
        ("medium", "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast."),
        ("long", "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast. Outside the fogged windows, pale fields gave way to grey water, and the rhythm of the rails settled into a steady, hypnotic hum. By the time the sun finally broke through, most of the passengers had drifted into an unhurried silence."),
    ]

    public static let defaultDesignBrief =
        "A warm, calm middle-aged male narrator with a clear, measured pace."
    public static let defaultCloneVoice = "A_warm_elderly_woman"

    public static let defaultModes = ["custom", "design", "clone"]
    public static let defaultLengths = ["short", "medium", "long"]
    public static let defaultWarmReps = 3

    /// Bucket prompt char count into short/medium/long (mirrors summarizer).
    public static func lenBucket(_ chars: Int) -> String {
        chars == 0 ? "n/a" : chars < 70 ? "short" : chars > 220 ? "long" : "medium"
    }

    public static func text(for len: String) -> String? {
        corpus.first { $0.len == len }?.text
    }

    public static func validateCorpus() throws {
        for entry in corpus where lenBucket(entry.text.count) != entry.len {
            throw BenchMatrixValidationError.drift(
                len: entry.len,
                bucket: lenBucket(entry.text.count),
                chars: entry.text.count
            )
        }
    }

    /// One generation cell in the release matrix (Speed variant; no delivery cells).
    public struct Take: Sendable, Equatable {
        public let mode: String
        public let length: String
        public let warmState: String
        public let rep: Int
        public let text: String

        public init(mode: String, length: String, warmState: String, rep: Int, text: String) {
            self.mode = mode
            self.length = length
            self.warmState = warmState
            self.rep = rep
            self.text = text
        }
    }

    /// Deterministic take order matching `BenchCommand.run` (Custom/Design cold medium only).
    public static func matrix(
        modes: [String] = defaultModes,
        lengths: [String] = defaultLengths,
        warm: Int = defaultWarmReps
    ) -> [Take] {
        let warmReps = max(1, warm)
        let coldLen = lengths.contains("medium") ? "medium" : lengths.first
        var takes: [Take] = []

        for mode in modes {
            if mode != "clone", let coldLen, let coldText = text(for: coldLen) {
                takes.append(Take(mode: mode, length: coldLen, warmState: "cold", rep: 0, text: coldText))
            }
            for len in lengths {
                guard let body = text(for: len) else { continue }
                for rep in 0..<warmReps {
                    takes.append(Take(mode: mode, length: len, warmState: "warm", rep: rep, text: body))
                }
            }
        }
        return takes
    }

    /// Expected take count for the Speed release matrix (29 with defaults).
    public static func expectedTakeCount(
        modes: [String] = defaultModes,
        lengths: [String] = defaultLengths,
        warm: Int = defaultWarmReps
    ) -> Int {
        matrix(modes: modes, lengths: lengths, warm: warm).count
    }

    /// Generations one `vocello bench` invocation plans, each of which writes one
    /// verbose sidecar: per mode × variant, the Custom/Design cold take, `warm`
    /// takes per length and one take per delivery cell (Custom/Design only), plus
    /// one TTFC probe per mode × variant. Mirrors `BenchCommand.run`'s loops; the
    /// full default matrix (three modes, two variants, three lengths, warm 3) is 58.
    /// A delivery sweep run with `--no-cold` (audit #104) plans no cold take.
    public static func plannedGenerationCount(
        modes: [String],
        variantCount: Int,
        lengths: [String],
        warm: Int,
        deliveryCellCount: Int,
        ttfcProbe: Bool,
        coldTakes: Bool = true
    ) -> Int {
        let hasColdLength = coldTakes && !lengths.isEmpty
        let perVariant = modes.reduce(0) { count, mode in
            let instructable = mode != "clone"
            return count
                + (instructable && hasColdLength ? 1 : 0)
                + lengths.count * max(0, warm)
                + (instructable ? max(0, deliveryCellCount) : 0)
        }
        let probes = ttfcProbe ? modes.count : 0
        return (perVariant + probes) * max(0, variantCount)
    }
}

public enum BenchMatrixValidationError: Error, CustomStringConvertible {
    case drift(len: String, bucket: String, chars: Int)

    public var description: String {
        switch self {
        case let .drift(len, bucket, chars):
            "corpus drift: '\(len)' text buckets as '\(bucket)' (\(chars) chars)"
        }
    }
}
