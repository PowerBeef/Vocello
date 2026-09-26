import CryptoKit
import Foundation

public enum SpokenTextPlanningError: Error, Equatable, Sendable {
    case emptyOriginalText
    case invalidAlgorithmVersion(Int)
    case invalidSourceRange
    case sourceDigestMismatch
    case invalidLanguageIdentifier
}

/// A half-open UTF-8 byte range. Byte offsets are used instead of `String.Index`
/// so local manifests can be inspected without depending on a process-local
/// Swift string representation.
public struct TextUTF8Range: Codable, Equatable, Hashable, Sendable {
    public let lowerBound: Int
    public let upperBound: Int

    public init(lowerBound: Int, upperBound: Int) {
        self.lowerBound = lowerBound
        self.upperBound = upperBound
    }

    public var count: Int { upperBound - lowerBound }

    public func overlaps(_ other: Self) -> Bool {
        lowerBound < other.upperBound && other.lowerBound < upperBound
    }

    public func contains(_ byteOffset: Int) -> Bool {
        lowerBound <= byteOffset && byteOffset < upperBound
    }
}

/// A source range cannot be interpreted without the digest of the exact text
/// whose UTF-8 bytes it indexes.
public struct DigestBoundTextRange: Codable, Equatable, Hashable, Sendable {
    public let textDigest: String
    public let range: TextUTF8Range

    public init(textDigest: String, range: TextUTF8Range) {
        self.textDigest = textDigest
        self.range = range
    }
}

public enum SpokenTextRiskKind: String, Codable, CaseIterable, Hashable, Sendable {
    case protectedURL = "protected_url"
    case protectedEmail = "protected_email"
    case protectedVersion = "protected_version"
    case protectedAcronym = "protected_acronym"
    case protectedAbbreviation = "protected_abbreviation"
    case ambiguousDate = "ambiguous_date"
    case ambiguousTime = "ambiguous_time"
    case ambiguousCurrency = "ambiguous_currency"
    case ambiguousUnit = "ambiguous_unit"
    case ambiguousNumber = "ambiguous_number"

    fileprivate var protectsSegmentation: Bool {
        switch self {
        case .protectedURL, .protectedEmail, .protectedVersion,
             .protectedAcronym, .protectedAbbreviation,
             .ambiguousDate, .ambiguousTime, .ambiguousCurrency,
             .ambiguousUnit, .ambiguousNumber:
            true
        }
    }
}

public struct SpokenTextRisk: Codable, Equatable, Hashable, Sendable {
    public let kind: SpokenTextRiskKind
    public let sourceRange: DigestBoundTextRange
    public let spokenRange: DigestBoundTextRange?

    public init(
        kind: SpokenTextRiskKind,
        sourceRange: DigestBoundTextRange,
        spokenRange: DigestBoundTextRange?
    ) {
        self.kind = kind
        self.sourceRange = sourceRange
        self.spokenRange = spokenRange
    }
}

/// A caller-supplied code-switch annotation. It is rejected unless it is bound
/// to the exact original text and starts and ends on UTF-8 scalar boundaries.
public struct SpokenTextCodeSwitchInput: Equatable, Hashable, Sendable {
    public let languageIdentifier: String
    public let sourceRange: DigestBoundTextRange

    public init(languageIdentifier: String, sourceRange: DigestBoundTextRange) {
        self.languageIdentifier = languageIdentifier
        self.sourceRange = sourceRange
    }
}

public struct SpokenTextCodeSwitchRange: Codable, Equatable, Hashable, Sendable {
    public let languageIdentifier: String
    public let sourceRange: DigestBoundTextRange
    public let spokenRange: DigestBoundTextRange
}

public struct SpokenTextNormalizationPolicy: Codable, Equatable, Hashable, Sendable {
    // v2 (2026-09-26, CORE-10): one line break per grapheme, so a CRLF pair is a
    // line break rather than a paragraph. Text without CR normalizes as in v1.
    public static let currentAlgorithmVersion = 2

    public let algorithmVersion: Int
    public let languageIdentifier: String?

    public init(
        algorithmVersion: Int = Self.currentAlgorithmVersion,
        languageIdentifier: String? = nil
    ) {
        self.algorithmVersion = algorithmVersion
        self.languageIdentifier = languageIdentifier
    }
}

public struct SpokenTextRiskCount: Codable, Equatable, Hashable, Sendable {
    public let kind: SpokenTextRiskKind
    public let count: Int
}

/// Privacy-safe projection suitable for telemetry and tracked evidence. Neither
/// the original nor the spoken text is Codable through this type.
public struct SpokenTextPlanEvidence: Codable, Equatable, Hashable, Sendable {
    public let schemaVersion: Int
    public let algorithmVersion: Int
    public let originalTextDigest: String
    public let spokenTextDigest: String
    public let originalTextUTF8ByteCount: Int
    public let spokenTextUTF8ByteCount: Int
    public let transformationCount: Int
    public let riskCounts: [SpokenTextRiskCount]
    public let codeSwitchRangeCount: Int

    public func canonicalJSONData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    public func canonicalDigest() throws -> String {
        SpokenTextCanonical.digest(try canonicalJSONData())
    }
}

/// App-private text plan. Raw text remains internal to `QwenVoiceCore`; public
/// evidence is available only through `evidence`.
public struct SpokenTextPlan: Sendable {
    public static let evidenceSchemaVersion = 1

    let originalText: String
    let mappingRuns: [MappingRun]

    public let spokenText: String
    public let originalTextDigest: String
    public let spokenTextDigest: String
    public let policy: SpokenTextNormalizationPolicy
    public let risks: [SpokenTextRisk]
    public let codeSwitchRanges: [SpokenTextCodeSwitchRange]
    public let transformationCount: Int

    public var evidence: SpokenTextPlanEvidence {
        let grouped = Dictionary(grouping: risks, by: \.kind)
        let counts = grouped
            .map { SpokenTextRiskCount(kind: $0.key, count: $0.value.count) }
            .sorted { $0.kind.rawValue < $1.kind.rawValue }
        return SpokenTextPlanEvidence(
            schemaVersion: Self.evidenceSchemaVersion,
            algorithmVersion: policy.algorithmVersion,
            originalTextDigest: originalTextDigest,
            spokenTextDigest: spokenTextDigest,
            originalTextUTF8ByteCount: originalText.utf8.count,
            spokenTextUTF8ByteCount: spokenText.utf8.count,
            transformationCount: transformationCount,
            riskCounts: counts,
            codeSwitchRangeCount: codeSwitchRanges.count
        )
    }

    var protectedSpokenRanges: [TextUTF8Range] {
        risks.compactMap { risk in
            guard risk.kind.protectsSegmentation else { return nil }
            return risk.spokenRange?.range
        }
    }

    func sourceRange(forSpokenRange spokenRange: TextUTF8Range) -> DigestBoundTextRange? {
        let overlapping = mappingRuns.filter { $0.spoken.overlaps(spokenRange) }
        guard let lower = overlapping.map(\.source.lowerBound).min(),
              let upper = overlapping.map(\.source.upperBound).max() else {
            return nil
        }
        return DigestBoundTextRange(
            textDigest: originalTextDigest,
            range: TextUTF8Range(lowerBound: lower, upperBound: upper)
        )
    }

    func sourceSubstring(in range: DigestBoundTextRange) throws -> String {
        guard range.textDigest == originalTextDigest else {
            throw SpokenTextPlanningError.sourceDigestMismatch
        }
        return try Self.substring(originalText, range: range.range)
    }

    func spokenSubstring(in range: DigestBoundTextRange) throws -> String {
        guard range.textDigest == spokenTextDigest else {
            throw SpokenTextPlanningError.sourceDigestMismatch
        }
        return try Self.substring(spokenText, range: range.range)
    }

    private static func substring(_ text: String, range: TextUTF8Range) throws -> String {
        guard let bounds = text.indices(forUTF8Range: range) else {
            throw SpokenTextPlanningError.invalidSourceRange
        }
        return String(text[bounds])
    }
}

struct MappingRun: Equatable, Hashable, Sendable {
    let source: TextUTF8Range
    let spoken: TextUTF8Range
}

public enum SpokenTextPlanner {
    public static func originalTextDigest(for text: String) -> String {
        SpokenTextCanonical.digest(Data(text.utf8))
    }

    public static func plan(
        originalText: String,
        codeSwitches: [SpokenTextCodeSwitchInput] = [],
        policy: SpokenTextNormalizationPolicy = SpokenTextNormalizationPolicy()
    ) throws -> SpokenTextPlan {
        guard !originalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SpokenTextPlanningError.emptyOriginalText
        }
        guard policy.algorithmVersion == SpokenTextNormalizationPolicy.currentAlgorithmVersion else {
            throw SpokenTextPlanningError.invalidAlgorithmVersion(policy.algorithmVersion)
        }

        let originalDigest = originalTextDigest(for: originalText)
        let detected = try detectedRisks(in: originalText)
        let protectedRanges = detected
            .filter { $0.kind.protectsSegmentation }
            .map(\.range)
        let normalized = normalize(originalText, protectedRanges: protectedRanges)
        let spokenDigest = SpokenTextCanonical.digest(Data(normalized.text.utf8))

        let risks = detected.map { match in
            let source = DigestBoundTextRange(textDigest: originalDigest, range: match.range)
            let spoken = mappedSpokenRange(
                for: match.range,
                mappings: normalized.mappings,
                spokenDigest: spokenDigest
            )
            return SpokenTextRisk(kind: match.kind, sourceRange: source, spokenRange: spoken)
        }

        let resolvedCodeSwitches = try codeSwitches.map { input in
            guard !input.languageIdentifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  input.languageIdentifier.utf8.count <= 64 else {
                throw SpokenTextPlanningError.invalidLanguageIdentifier
            }
            guard input.sourceRange.textDigest == originalDigest else {
                throw SpokenTextPlanningError.sourceDigestMismatch
            }
            guard originalText.indices(forUTF8Range: input.sourceRange.range) != nil else {
                throw SpokenTextPlanningError.invalidSourceRange
            }
            guard let spokenRange = mappedSpokenRange(
                for: input.sourceRange.range,
                mappings: normalized.mappings,
                spokenDigest: spokenDigest
            ) else {
                throw SpokenTextPlanningError.invalidSourceRange
            }
            return SpokenTextCodeSwitchRange(
                languageIdentifier: input.languageIdentifier,
                sourceRange: input.sourceRange,
                spokenRange: spokenRange
            )
        }

        return SpokenTextPlan(
            originalText: originalText,
            mappingRuns: normalized.mappings,
            spokenText: normalized.text,
            originalTextDigest: originalDigest,
            spokenTextDigest: spokenDigest,
            policy: policy,
            risks: risks,
            codeSwitchRanges: resolvedCodeSwitches,
            transformationCount: normalized.transformationCount
        )
    }

    private struct RiskMatch {
        let kind: SpokenTextRiskKind
        let range: TextUTF8Range
    }

    private struct NormalizedText {
        let text: String
        let mappings: [MappingRun]
        let transformationCount: Int
    }

    private static func detectedRisks(in text: String) throws -> [RiskMatch] {
        let protectedPatterns: [(SpokenTextRiskKind, String)] = [
            (.protectedURL, #"(?i)\bhttps?://[^\s<>\"']*[A-Za-z0-9/#=_~%+-]"#),
            (.protectedEmail, #"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"#),
            (.protectedVersion, #"\b(?:[vV]\d+(?:\.\d+){1,4}|\d+(?:\.\d+){2,4})(?:[-+][A-Za-z0-9.-]+)?\b"#),
            (.protectedAcronym, #"(?:(?<![A-Za-z])(?:[A-Z]\.){2,}|\b[A-Z]{2,}\b)"#),
            (.protectedAbbreviation, #"(?i)\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\."#),
        ]
        let ambiguousPatterns: [(SpokenTextRiskKind, String)] = [
            (.ambiguousDate, #"\b\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b"#),
            (.ambiguousTime, #"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?\b"#),
            (.ambiguousCurrency, #"(?:[$€£¥]\s?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s?(?:USD|CAD|EUR|GBP|JPY|CNY)\b)"#),
            (.ambiguousUnit, #"\b\d+(?:[.,]\d+)?\s?(?:kg|g|km|cm|mm|m|mph|km/h|°C|°F|Hz|kHz|MB|GB)\b"#),
            (.ambiguousNumber, #"\b\d+(?:[.,]\d+)+\b"#),
        ]

        var matches: [RiskMatch] = []
        for (kind, pattern) in protectedPatterns {
            for range in try regexRanges(pattern: pattern, in: text) where
                !matches.contains(where: { $0.range.overlaps(range) }) {
                matches.append(RiskMatch(kind: kind, range: range))
            }
        }
        for (kind, pattern) in ambiguousPatterns {
            for range in try regexRanges(pattern: pattern, in: text) where
                !matches.contains(where: { $0.range.overlaps(range) }) {
                matches.append(RiskMatch(kind: kind, range: range))
            }
        }
        return matches.sorted {
            if $0.range.lowerBound == $1.range.lowerBound {
                return $0.range.upperBound < $1.range.upperBound
            }
            return $0.range.lowerBound < $1.range.lowerBound
        }
    }

    private static func regexRanges(pattern: String, in text: String) throws -> [TextUTF8Range] {
        let regex = try NSRegularExpression(pattern: pattern)
        let fullRange = NSRange(text.startIndex..<text.endIndex, in: text)
        return regex.matches(in: text, range: fullRange).compactMap { result in
            guard let range = Range(result.range, in: text) else { return nil }
            return TextUTF8Range(
                lowerBound: text.utf8.distance(from: text.utf8.startIndex, to: range.lowerBound),
                upperBound: text.utf8.distance(from: text.utf8.startIndex, to: range.upperBound)
            )
        }
    }

    private static func normalize(
        _ original: String,
        protectedRanges: [TextUTF8Range]
    ) -> NormalizedText {
        var builder = NormalizationBuilder()
        var cursor = original.startIndex
        var pendingWhitespace: TextUTF8Range?
        var pendingWhitespaceText = ""
        var pendingNewlineCount = 0

        func isProtected(_ range: TextUTF8Range) -> Bool {
            protectedRanges.contains(where: { $0.overlaps(range) })
        }

        while cursor < original.endIndex {
            let next = original.index(after: cursor)
            let sourceRange = TextUTF8Range(
                lowerBound: original.utf8.distance(from: original.utf8.startIndex, to: cursor),
                upperBound: original.utf8.distance(from: original.utf8.startIndex, to: next)
            )
            let raw = String(original[cursor..<next])
            let isWhitespace = raw.unicodeScalars.allSatisfy {
                CharacterSet.whitespacesAndNewlines.contains($0)
            }

            if isWhitespace {
                pendingWhitespace = pendingWhitespace.map {
                    TextUTF8Range(lowerBound: $0.lowerBound, upperBound: sourceRange.upperBound)
                } ?? sourceRange
                pendingWhitespaceText.append(raw)
                // One line break per grapheme: a Windows CRLF pair is a single
                // grapheme of two newline scalars, and counting scalars turned
                // every CRLF line break into a paragraph break (CORE-10).
                if raw.unicodeScalars.contains(where: { CharacterSet.newlines.contains($0) }) {
                    pendingNewlineCount += 1
                }
                cursor = next
                continue
            }

            if let whitespace = pendingWhitespace, !builder.text.isEmpty {
                let separator = pendingNewlineCount >= 2 ? "\n\n" : " "
                builder.append(
                    separator,
                    source: whitespace,
                    transformed: separator != pendingWhitespaceText
                )
            }
            pendingWhitespace = nil
            pendingWhitespaceText = ""
            pendingNewlineCount = 0

            let replacement = normalizedCharacter(raw, protected: isProtected(sourceRange))
            builder.append(replacement, source: sourceRange, transformed: replacement != raw)
            cursor = next
        }

        return NormalizedText(
            text: builder.text.precomposedStringWithCanonicalMapping,
            mappings: builder.mappings,
            transformationCount: builder.transformationCount
        )
    }

    private static func normalizedCharacter(_ raw: String, protected: Bool) -> String {
        if protected {
            return raw.precomposedStringWithCanonicalMapping
        }
        if raw.unicodeScalars.count == 1,
           let scalar = raw.unicodeScalars.first,
           (0xFF10...0xFF19).contains(scalar.value),
           let ascii = UnicodeScalar(0x30 + scalar.value - 0xFF10) {
            return String(ascii)
        }
        switch raw {
        case "\u{2018}", "\u{2019}", "\u{02BC}": return "'"
        case "\u{201C}", "\u{201D}": return "\""
        case "\u{FF0E}": return "."
        case "\u{FF0F}": return "/"
        case "\u{FF0D}": return "-"
        default: return raw.precomposedStringWithCanonicalMapping
        }
    }

    private static func mappedSpokenRange(
        for sourceRange: TextUTF8Range,
        mappings: [MappingRun],
        spokenDigest: String
    ) -> DigestBoundTextRange? {
        let overlapping = mappings.filter { $0.source.overlaps(sourceRange) }
        guard let lower = overlapping.map(\.spoken.lowerBound).min(),
              let upper = overlapping.map(\.spoken.upperBound).max() else {
            return nil
        }
        return DigestBoundTextRange(
            textDigest: spokenDigest,
            range: TextUTF8Range(lowerBound: lower, upperBound: upper)
        )
    }
}

private struct NormalizationBuilder {
    var text = ""
    var mappings: [MappingRun] = []
    var transformationCount = 0

    mutating func append(_ value: String, source: TextUTF8Range, transformed: Bool) {
        guard !value.isEmpty else { return }
        let lower = text.utf8.count
        text.append(value)
        let upper = text.utf8.count
        mappings.append(
            MappingRun(
                source: source,
                spoken: TextUTF8Range(lowerBound: lower, upperBound: upper)
            )
        )
        if transformed { transformationCount += 1 }
    }
}

extension String {
    fileprivate func indices(forUTF8Range range: TextUTF8Range) -> Range<String.Index>? {
        guard range.lowerBound >= 0,
              range.upperBound >= range.lowerBound,
              range.upperBound <= utf8.count else {
            return nil
        }
        guard let lowerUTF8 = utf8.index(
            utf8.startIndex,
            offsetBy: range.lowerBound,
            limitedBy: utf8.endIndex
        ),
        let upperUTF8 = utf8.index(
            utf8.startIndex,
            offsetBy: range.upperBound,
            limitedBy: utf8.endIndex
        ),
        let lower = String.Index(lowerUTF8, within: self),
        let upper = String.Index(upperUTF8, within: self) else {
            return nil
        }
        return lower..<upper
    }
}

enum SpokenTextCanonical {
    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func serialize(namespace: String, components: [String]) -> String {
        ([namespace] + components).map { "\($0.utf8.count):\($0)" }.joined(separator: "|")
    }
}
