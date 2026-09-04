import CryptoKit
import Foundation
import QwenVoiceBackendCore

public enum LongFormPlanningError: Error, Equatable, Sendable {
    case invalidAlgorithmVersion(Int)
    case invalidTokenEstimatorVersion(Int)
    case invalidRuntimeTokenLimit(Int)
    case invalidRevision(Int)
    case protectedSpanExceedsTokenLimit
    case tokenLimitCannotFitGrapheme
    case sourceMappingUnavailable
    case invalidManifestSchema(Int)
    case invalidManifest(String)
}

public enum LongFormBoundaryKind: String, Codable, CaseIterable, Hashable, Sendable {
    case paragraph
    case sentence
    case semicolonOrColon = "semicolon_or_colon"
    case safeClause = "safe_clause"
    case whitespace
    case grapheme
    case endOfText = "end_of_text"

    fileprivate var precedence: Int {
        switch self {
        case .paragraph: 0
        case .sentence: 1
        case .semicolonOrColon: 2
        case .safeClause: 3
        case .whitespace: 4
        case .grapheme: 5
        case .endOfText: -1
        }
    }

    public var intendedPauseMilliseconds: Int {
        switch self {
        case .paragraph: 500
        case .sentence: 300
        case .semicolonOrColon: 180
        case .safeClause: 120
        case .whitespace: 80
        case .grapheme, .endOfText: 0
        }
    }
}

public struct LongFormRevisionLineage: Codable, Equatable, Hashable, Sendable {
    public let revision: Int
    public let parentPlanDigest: String?
    public let replacesSegmentID: String?

    public init(
        revision: Int = 1,
        parentPlanDigest: String? = nil,
        replacesSegmentID: String? = nil
    ) {
        self.revision = revision
        self.parentPlanDigest = parentPlanDigest
        self.replacesSegmentID = replacesSegmentID
    }
}

public struct LongFormPlanningConfiguration: Codable, Equatable, Hashable, Sendable {
    // v2 (2026-08-01): R-tail orphan rebalancing
    // (docs/decisions/long-form-context-planning-v2.md). The version participates in
    // segment/plan identity serialization, so new plans re-derive IDs and sub-seeds;
    // retained projects replay their recorded plans untouched.
    public static let currentPlannerAlgorithmVersion = 2
    public static let currentTokenEstimatorVersion = 1

    public let plannerAlgorithmVersion: Int
    public let tokenEstimatorVersion: Int
    public let runtimeTokenLimit: Int
    public let baseSeed: UInt64
    public let lineage: LongFormRevisionLineage

    public init(
        plannerAlgorithmVersion: Int = Self.currentPlannerAlgorithmVersion,
        tokenEstimatorVersion: Int = Self.currentTokenEstimatorVersion,
        runtimeTokenLimit: Int,
        baseSeed: UInt64,
        lineage: LongFormRevisionLineage = LongFormRevisionLineage()
    ) {
        self.plannerAlgorithmVersion = plannerAlgorithmVersion
        self.tokenEstimatorVersion = tokenEstimatorVersion
        self.runtimeTokenLimit = runtimeTokenLimit
        self.baseSeed = baseSeed
        self.lineage = lineage
    }

    fileprivate func validated() throws -> Self {
        guard plannerAlgorithmVersion == Self.currentPlannerAlgorithmVersion else {
            throw LongFormPlanningError.invalidAlgorithmVersion(plannerAlgorithmVersion)
        }
        guard tokenEstimatorVersion == Self.currentTokenEstimatorVersion else {
            throw LongFormPlanningError.invalidTokenEstimatorVersion(tokenEstimatorVersion)
        }
        guard runtimeTokenLimit > 0 else {
            throw LongFormPlanningError.invalidRuntimeTokenLimit(runtimeTokenLimit)
        }
        guard lineage.revision > 0 else {
            throw LongFormPlanningError.invalidRevision(lineage.revision)
        }
        return self
    }
}

extension LongFormPlanningConfiguration {
    /// Per-segment planning budget in the conservative TEXT-token estimate's
    /// units. Two ceilings apply and the budget honors the tighter one:
    ///
    /// 1. **Codec safety.** The estimator yields ~chars/3 for English; codec
    ///    tokens are time-based (12/s), so codec ≈ 2.6× the estimate at
    ///    canonical pace and ≈ 3.6× slow. The budget × 3.6 must stay inside
    ///    `Qwen3GenerationConfiguration.officialQualityDefault.maxNewTokens`.
    /// 2. **Delivery stability.** Single-request pacing degrades on very long
    ///    generations: a live 2026-07-23 ~1,100-character segment (~97 s)
    ///    produced a 2,073 ms interior gap plus 24 pauses ≥ 350 ms and was
    ///    correctly hard-failed by QC. The historical long-form path was
    ///    delivery-validated at ≤ 900 characters (~60 s); 300 estimate units
    ///    ≈ 900 English characters keeps planned segments inside that
    ///    envelope.
    ///
    /// 300 × 3.6 ≈ 1,080 codec tokens — the delivery ceiling binds first.
    public static var shippingRuntimeTokenLimit: Int {
        let codecCap = Qwen3GenerationConfiguration.officialQualityDefault.maxNewTokens
        let codecSafeBudget = max(64, codecCap / 4)
        let deliveryValidatedBudget = 300
        return min(codecSafeBudget, deliveryValidatedBudget)
    }
}

public struct LongFormSegmentEvidence: Codable, Equatable, Hashable, Sendable {
    public let index: Int
    public let segmentID: String
    public let segmentDigest: String
    public let originalRange: DigestBoundTextRange
    public let spokenRange: DigestBoundTextRange
    public let boundary: LongFormBoundaryKind
    public let conservativeTokenEstimate: Int
    public let runtimeTokenLimit: Int
    public let intendedPauseMilliseconds: Int
    public let effectiveSubseed: UInt64
    public let lineage: LongFormRevisionLineage
    public let riskKinds: [SpokenTextRiskKind]
    public let codeSwitchRanges: [SpokenTextCodeSwitchRange]
}

/// A segment's model-facing text remains internal to `QwenVoiceCore`. Product
/// integration consumes it in-process; manifests and benchmark history receive
/// only `evidence`.
public struct LongFormSegmentPlan: Sendable {
    let spokenText: String

    public let evidence: LongFormSegmentEvidence

    /// Model-facing segment text for in-process generation requests. Manifests,
    /// telemetry, and benchmark history must record only `evidence`; this text
    /// never enters tracked artifacts.
    public var spokenTextForGeneration: String { spokenText }

    public var index: Int { evidence.index }
    public var segmentID: String { evidence.segmentID }
    public var conservativeTokenEstimate: Int { evidence.conservativeTokenEstimate }
}

public struct LongFormPlanEvidence: Codable, Equatable, Hashable, Sendable {
    public static let currentSchemaVersion = 1

    public let schemaVersion: Int
    public let plannerAlgorithmVersion: Int
    public let tokenEstimatorVersion: Int
    public let originalTextDigest: String
    public let spokenTextDigest: String
    public let planDigest: String
    public let runtimeTokenLimit: Int
    public let segmentCount: Int
    public let lineage: LongFormRevisionLineage
    public let segments: [LongFormSegmentEvidence]

    public func canonicalJSONData() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}

public struct LongFormPlan: Sendable {
    public let configuration: LongFormPlanningConfiguration
    public let segments: [LongFormSegmentPlan]
    public let evidence: LongFormPlanEvidence
}

public enum LongFormPlanner {
    public static func plan(
        spokenTextPlan: SpokenTextPlan,
        configuration: LongFormPlanningConfiguration
    ) throws -> LongFormPlan {
        let configuration = try configuration.validated()
        let text = spokenTextPlan.spokenText
        let protectedRanges = spokenTextPlan.protectedSpokenRanges
        var drafts: [SegmentDraft] = []
        var start = text.startIndex

        while start < text.endIndex {
            start = text.indexAfterWhitespace(from: start)
            guard start < text.endIndex else { break }

            let scan = try scanWindow(
                text: text,
                start: start,
                tokenLimit: configuration.runtimeTokenLimit,
                protectedRanges: protectedRanges
            )
            var selection: BoundaryCandidate
            if scan.maximumEnd == text.endIndex {
                selection = BoundaryCandidate(index: text.endIndex, kind: .endOfText)
            } else if let selected = preferredBoundary(from: scan.candidates) {
                selection = selected
            } else if protectedRanges.contains(where: {
                let startOffset = text.utf8Offset(of: start)
                let endOffset = text.utf8Offset(of: scan.maximumEnd)
                return $0.contains(startOffset) && endOffset < $0.upperBound
            }) {
                throw LongFormPlanningError.protectedSpanExceedsTokenLimit
            } else {
                selection = BoundaryCandidate(index: scan.maximumEnd, kind: .grapheme)
            }

            // Planner v2 context repair (docs/decisions/long-form-context-planning-v2.md):
            // R-tail keeps the final segment from becoming a pacing-visible orphan by
            // rebalancing the last boundary. Pure text decision; boundary kinds never
            // degrade and paragraph pauses are never crossed.
            if selection.kind != .endOfText,
               let rebalanced = rebalancedAgainstOrphanTail(
                   text: text,
                   start: start,
                   selection: selection,
                   candidates: scan.candidates,
                   tokenLimit: configuration.runtimeTokenLimit
               ) {
                selection = rebalanced
            }

            let trimmedEnd = text.indexBeforeWhitespace(endingAt: selection.index, after: start)
            guard trimmedEnd > start else {
                throw LongFormPlanningError.tokenLimitCannotFitGrapheme
            }
            let spokenRange = TextUTF8Range(
                lowerBound: text.utf8Offset(of: start),
                upperBound: text.utf8Offset(of: trimmedEnd)
            )
            let spokenBoundRange = DigestBoundTextRange(
                textDigest: spokenTextPlan.spokenTextDigest,
                range: spokenRange
            )
            guard let originalRange = spokenTextPlan.sourceRange(forSpokenRange: spokenRange) else {
                throw LongFormPlanningError.sourceMappingUnavailable
            }
            let segmentText = String(text[start..<trimmedEnd])
            let tokenEstimate = ConservativeTokenEstimator.estimate(segmentText)
            guard tokenEstimate <= configuration.runtimeTokenLimit else {
                throw LongFormPlanningError.invalidRuntimeTokenLimit(
                    configuration.runtimeTokenLimit
                )
            }
            let risks = spokenTextPlan.risks.filter {
                $0.spokenRange?.range.overlaps(spokenRange) == true
            }
            let codeSwitches = spokenTextPlan.codeSwitchRanges.filter {
                $0.spokenRange.range.overlaps(spokenRange)
            }
            drafts.append(
                SegmentDraft(
                    spokenText: segmentText,
                    originalRange: originalRange,
                    spokenRange: spokenBoundRange,
                    boundary: selection.kind,
                    conservativeTokenEstimate: tokenEstimate,
                    riskKinds: Array(Set(risks.map(\.kind))).sorted { $0.rawValue < $1.rawValue },
                    codeSwitchRanges: codeSwitches
                )
            )

            start = text.indexAfterWhitespace(from: selection.index)
        }

        let segmentIdentities = drafts.enumerated().map { index, draft in
            segmentIdentity(
                index: index + 1,
                draft: draft,
                spokenPlan: spokenTextPlan,
                configuration: configuration
            )
        }
        let planDigest = SpokenTextCanonical.digest(
            Data(
                SpokenTextCanonical.serialize(
                    namespace: "long-form-plan-v1",
                    components: [
                        String(configuration.plannerAlgorithmVersion),
                        String(configuration.tokenEstimatorVersion),
                        spokenTextPlan.originalTextDigest,
                        spokenTextPlan.spokenTextDigest,
                        String(configuration.runtimeTokenLimit),
                        String(configuration.baseSeed),
                        String(configuration.lineage.revision),
                        configuration.lineage.parentPlanDigest ?? "",
                        configuration.lineage.replacesSegmentID ?? "",
                    ] + segmentIdentities.map(\.segmentID)
                ).utf8
            )
        )

        let segments = zip(drafts.indices, drafts).map { index, draft in
            let identity = segmentIdentities[index]
            let subseed = deriveSubseed(baseSeed: configuration.baseSeed, segmentID: identity.segmentID)
            let evidence = LongFormSegmentEvidence(
                index: index + 1,
                segmentID: identity.segmentID,
                segmentDigest: identity.segmentDigest,
                originalRange: draft.originalRange,
                spokenRange: draft.spokenRange,
                boundary: draft.boundary,
                conservativeTokenEstimate: draft.conservativeTokenEstimate,
                runtimeTokenLimit: configuration.runtimeTokenLimit,
                intendedPauseMilliseconds: draft.boundary.intendedPauseMilliseconds,
                effectiveSubseed: subseed,
                lineage: configuration.lineage,
                riskKinds: draft.riskKinds,
                codeSwitchRanges: draft.codeSwitchRanges
            )
            return LongFormSegmentPlan(spokenText: draft.spokenText, evidence: evidence)
        }
        let evidence = LongFormPlanEvidence(
            schemaVersion: LongFormPlanEvidence.currentSchemaVersion,
            plannerAlgorithmVersion: configuration.plannerAlgorithmVersion,
            tokenEstimatorVersion: configuration.tokenEstimatorVersion,
            originalTextDigest: spokenTextPlan.originalTextDigest,
            spokenTextDigest: spokenTextPlan.spokenTextDigest,
            planDigest: planDigest,
            runtimeTokenLimit: configuration.runtimeTokenLimit,
            segmentCount: segments.count,
            lineage: configuration.lineage,
            segments: segments.map(\.evidence)
        )
        return LongFormPlan(configuration: configuration, segments: segments, evidence: evidence)
    }

    private struct SegmentDraft {
        let spokenText: String
        let originalRange: DigestBoundTextRange
        let spokenRange: DigestBoundTextRange
        let boundary: LongFormBoundaryKind
        let conservativeTokenEstimate: Int
        let riskKinds: [SpokenTextRiskKind]
        let codeSwitchRanges: [SpokenTextCodeSwitchRange]
    }

    private struct SegmentIdentity {
        let segmentID: String
        let segmentDigest: String
    }

    private struct BoundaryCandidate {
        let index: String.Index
        let kind: LongFormBoundaryKind
    }

    private struct ScanResult {
        let maximumEnd: String.Index
        let candidates: [BoundaryCandidate]
    }

    private static func scanWindow(
        text: String,
        start: String.Index,
        tokenLimit: Int,
        protectedRanges: [TextUTF8Range]
    ) throws -> ScanResult {
        var estimator = ConservativeTokenEstimator.State()
        var cursor = start
        var maximumEnd = start
        var candidates: [BoundaryCandidate] = []

        while cursor < text.endIndex {
            let next = text.index(after: cursor)
            let grapheme = String(text[cursor..<next])
            let nextEstimate = estimator.estimateAfterAppending(grapheme)
            if nextEstimate > tokenLimit {
                break
            }
            estimator.append(grapheme)
            maximumEnd = next

            let startOffset = text.utf8Offset(of: cursor)
            let endOffset = text.utf8Offset(of: next)
            let boundaryInsideProtected = protectedRanges.contains {
                $0.lowerBound < endOffset && endOffset < $0.upperBound
            }
            let currentInsideProtected = protectedRanges.contains {
                $0.lowerBound < startOffset && startOffset < $0.upperBound
            }

            if grapheme.unicodeScalars.allSatisfy({ CharacterSet.whitespacesAndNewlines.contains($0) }) {
                if grapheme.unicodeScalars.contains(where: { CharacterSet.newlines.contains($0) }),
                   next < text.endIndex {
                    let following = String(text[next..<text.index(after: next)])
                    if following.unicodeScalars.contains(where: { CharacterSet.newlines.contains($0) }),
                       cursor > start {
                        candidates.append(BoundaryCandidate(index: cursor, kind: .paragraph))
                    }
                }
                if cursor > start {
                    candidates.append(BoundaryCandidate(index: cursor, kind: .whitespace))
                }
            } else if !boundaryInsideProtected && !currentInsideProtected {
                if ".!?。！？".contains(grapheme) {
                    candidates.append(BoundaryCandidate(index: next, kind: .sentence))
                } else if ";:；：".contains(grapheme) {
                    candidates.append(BoundaryCandidate(index: next, kind: .semicolonOrColon))
                } else if ",，、—–".contains(grapheme) {
                    candidates.append(BoundaryCandidate(index: next, kind: .safeClause))
                }
            }
            if !boundaryInsideProtected {
                candidates.append(BoundaryCandidate(index: next, kind: .grapheme))
            }
            cursor = next
        }

        guard maximumEnd > start else {
            throw LongFormPlanningError.tokenLimitCannotFitGrapheme
        }
        return ScanResult(maximumEnd: maximumEnd, candidates: candidates)
    }

    private static func preferredBoundary(
        from candidates: [BoundaryCandidate]
    ) -> BoundaryCandidate? {
        for kind in LongFormBoundaryKind.allCases
            .filter({ $0 != .endOfText })
            .sorted(by: { $0.precedence < $1.precedence }) {
            if let candidate = candidates.last(where: { $0.kind == kind }) {
                return candidate
            }
        }
        return nil
    }

    private static func segmentIdentity(
        index: Int,
        draft: SegmentDraft,
        spokenPlan: SpokenTextPlan,
        configuration: LongFormPlanningConfiguration
    ) -> SegmentIdentity {
        let serialization = SpokenTextCanonical.serialize(
            namespace: "long-form-segment-v1",
            components: [
                String(configuration.plannerAlgorithmVersion),
                String(configuration.tokenEstimatorVersion),
                spokenPlan.originalTextDigest,
                spokenPlan.spokenTextDigest,
                String(index),
                String(draft.originalRange.range.lowerBound),
                String(draft.originalRange.range.upperBound),
                String(draft.spokenRange.range.lowerBound),
                String(draft.spokenRange.range.upperBound),
                draft.boundary.rawValue,
            ]
        )
        let digest = SpokenTextCanonical.digest(Data(serialization.utf8))
        return SegmentIdentity(segmentID: "lfseg_\(digest.prefix(24))", segmentDigest: digest)
    }

    // MARK: - Planner v2 context repairs

    /// R-tail threshold: a final segment under this fraction of the token limit is an
    /// orphan worth rebalancing.
    private static let minimumTailFraction = 0.25

    /// R-tail: when everything after `selection` would form a single under-fraction
    /// orphan segment, move the boundary to the same-or-better-precedence candidate
    /// that best balances the final two segments. Grapheme candidates are never used
    /// for re-selection, and the original selection stands when no candidate improves
    /// the balance while keeping both halves under the limit.
    private static func rebalancedAgainstOrphanTail(
        text: String,
        start: String.Index,
        selection: BoundaryCandidate,
        candidates: [BoundaryCandidate],
        tokenLimit: Int
    ) -> BoundaryCandidate? {
        let tailStart = text.indexAfterWhitespace(from: selection.index)
        guard tailStart < text.endIndex else { return nil }
        let tailEstimate = ConservativeTokenEstimator.estimate(String(text[tailStart...]))
        guard tailEstimate <= tokenLimit,
              Double(tailEstimate) < minimumTailFraction * Double(tokenLimit)
        else { return nil }

        let headEstimate = ConservativeTokenEstimator.estimate(String(text[start..<selection.index]))
        var bestImbalance = abs(headEstimate - tailEstimate)
        var best: BoundaryCandidate?
        for candidate in candidates
        where candidate.kind != .grapheme
            && candidate.kind.precedence <= selection.kind.precedence
            && candidate.index > start
            && candidate.index < selection.index {
            let head = ConservativeTokenEstimator.estimate(String(text[start..<candidate.index]))
            let newTailStart = text.indexAfterWhitespace(from: candidate.index)
            guard newTailStart < text.endIndex else { continue }
            let tail = ConservativeTokenEstimator.estimate(String(text[newTailStart...]))
            guard head <= tokenLimit, tail <= tokenLimit else { continue }
            let imbalance = abs(head - tail)
            if imbalance < bestImbalance {
                bestImbalance = imbalance
                best = candidate
            }
        }
        return best
    }

    private static func deriveSubseed(baseSeed: UInt64, segmentID: String) -> UInt64 {
        let serialization = SpokenTextCanonical.serialize(
            namespace: "long-form-subseed-v1",
            components: [String(baseSeed), segmentID]
        )
        return SHA256.hash(data: Data(serialization.utf8)).prefix(8).reduce(UInt64(0)) {
            ($0 << 8) | UInt64($1)
        }
    }
}

private enum ConservativeTokenEstimator {
    struct State {
        private(set) var estimate = 0
        private var asciiWordRunLength = 0

        mutating func estimateAfterAppending(_ grapheme: String) -> Int {
            var copy = self
            copy.append(grapheme)
            return copy.estimate
        }

        mutating func append(_ grapheme: String) {
            if grapheme.unicodeScalars.allSatisfy({ CharacterSet.whitespacesAndNewlines.contains($0) }) {
                asciiWordRunLength = 0
                return
            }
            if grapheme.unicodeScalars.count == 1,
               let scalar = grapheme.unicodeScalars.first,
               scalar.isASCII,
               CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "'_-")).contains(scalar) {
                let oldContribution = (asciiWordRunLength + 2) / 3
                asciiWordRunLength += 1
                let newContribution = (asciiWordRunLength + 2) / 3
                estimate += newContribution - oldContribution
                return
            }
            asciiWordRunLength = 0
            estimate += max(1, (grapheme.utf8.count + 2) / 3)
        }
    }

    static func estimate(_ text: String) -> Int {
        var state = State()
        for grapheme in text {
            state.append(String(grapheme))
        }
        return state.estimate
    }
}

/// Privacy-safe schema-v4 planning contract. Product execution will add local
/// output and quality state without putting raw text or paths into this core
/// projection.
/// Per-segment execution outcome recorded by the product coordinator. Values
/// are privacy-safe: no text, paths, or user data — only identities, verdict
/// booleans, allowlisted QC labels, and audio timing.
public struct LongFormSegmentExecutionEvidence: Codable, Equatable, Hashable, Sendable {
    public let index: Int
    public let segmentID: String
    public let generated: Bool
    public let audioDurationSeconds: Double?
    public let qcPassed: Bool?
    public let qcRequiredFailures: [String]
    public let qcWarnings: [String]
    /// Optional additions preserve decoding of already-published v4 manifests.
    public let generationID: UUID?
    public let effectiveSeed: UInt64?

    public init(
        index: Int,
        segmentID: String,
        generated: Bool,
        audioDurationSeconds: Double? = nil,
        qcPassed: Bool? = nil,
        qcRequiredFailures: [String] = [],
        qcWarnings: [String] = [],
        generationID: UUID? = nil,
        effectiveSeed: UInt64? = nil
    ) {
        self.index = index
        self.segmentID = segmentID
        self.generated = generated
        self.audioDurationSeconds = audioDurationSeconds
        self.qcPassed = qcPassed
        self.qcRequiredFailures = qcRequiredFailures
        self.qcWarnings = qcWarnings
        self.generationID = generationID
        self.effectiveSeed = effectiveSeed
    }
}

/// Execution summary for one long-form run against its plan.
public struct LongFormExecutionEvidence: Codable, Equatable, Hashable, Sendable {
    public let generatedAtUTC: String
    public let streamingExecution: Bool
    public let segments: [LongFormSegmentExecutionEvidence]

    public init(
        generatedAtUTC: String,
        streamingExecution: Bool,
        segments: [LongFormSegmentExecutionEvidence]
    ) {
        self.generatedAtUTC = generatedAtUTC
        self.streamingExecution = streamingExecution
        self.segments = segments
    }
}

/// One accepted per-segment replacement take. Revision 1 is the plan's own
/// take; replacements start at revision 2 and record the seed that produced
/// the accepted audio so any take remains reproducible.
public struct LongFormSegmentReplacementEvidence: Codable, Equatable, Hashable, Sendable {
    public let segmentID: String
    public let revision: Int
    public let effectiveSeed: UInt64
    public let generatedAtUTC: String
    public let qcPassed: Bool
    public let qcWarnings: [String]

    public init(
        segmentID: String,
        revision: Int,
        effectiveSeed: UInt64,
        generatedAtUTC: String,
        qcPassed: Bool,
        qcWarnings: [String] = []
    ) {
        self.segmentID = segmentID
        self.revision = revision
        self.effectiveSeed = effectiveSeed
        self.generatedAtUTC = generatedAtUTC
        self.qcPassed = qcPassed
        self.qcWarnings = qcWarnings
    }
}

public struct LongFormManifestV4: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 4

    public let schemaVersion: Int
    public let manifestKind: String
    public let plan: LongFormPlanEvidence
    /// Present once the coordinator has run (or attempted) the plan.
    public let execution: LongFormExecutionEvidence?
    /// Present once every segment passed and the bounded assembler joined the
    /// output; absent for planning-only or failed runs.
    public let assembly: LongFormAssemblyEvidence?
    /// Accepted replacement history, oldest first; absent when no segment has
    /// been regenerated.
    public let replacements: [LongFormSegmentReplacementEvidence]?

    public init(
        plan: LongFormPlanEvidence,
        execution: LongFormExecutionEvidence? = nil,
        assembly: LongFormAssemblyEvidence? = nil,
        replacements: [LongFormSegmentReplacementEvidence]? = nil
    ) {
        schemaVersion = Self.currentSchemaVersion
        manifestKind = "long_form_generation"
        self.plan = plan
        self.execution = execution
        self.assembly = assembly
        self.replacements = replacements?.isEmpty == true ? nil : replacements
    }

    public func validated() throws -> Self {
        guard schemaVersion == Self.currentSchemaVersion else {
            throw LongFormPlanningError.invalidManifestSchema(schemaVersion)
        }
        guard manifestKind == "long_form_generation",
              plan.schemaVersion == LongFormPlanEvidence.currentSchemaVersion,
              plan.segmentCount == plan.segments.count else {
            throw LongFormPlanningError.invalidManifest("v4 planning contract")
        }
        var planIDs: [String] = []
        planIDs.reserveCapacity(plan.segments.count)
        for (offset, segment) in plan.segments.enumerated() {
            guard segment.index == offset + 1,
                  segment.runtimeTokenLimit == plan.runtimeTokenLimit,
                  segment.conservativeTokenEstimate <= plan.runtimeTokenLimit else {
                throw LongFormPlanningError.invalidManifest("v4 planning contract")
            }
            planIDs.append(segment.segmentID)
        }
        guard Set(planIDs).count == planIDs.count else {
            throw LongFormPlanningError.invalidManifest("v4 planning contract")
        }
        if let execution {
            guard execution.segments.count == plan.segmentCount else {
                throw LongFormPlanningError.invalidManifest("v4 execution contract")
            }
            for (offset, segment) in execution.segments.enumerated() {
                guard segment.index == offset + 1,
                      segment.segmentID == planIDs[offset] else {
                    throw LongFormPlanningError.invalidManifest("v4 execution contract")
                }
            }
        }
        if let assembly {
            guard execution != nil,
                  assembly.segmentCount == plan.segmentCount,
                  assembly.segments.count == planIDs.count else {
                throw LongFormPlanningError.invalidManifest("v4 assembly contract")
            }
            for (offset, segment) in assembly.segments.enumerated() {
                guard segment.segmentID == planIDs[offset] else {
                    throw LongFormPlanningError.invalidManifest("v4 assembly contract")
                }
            }
        }
        if let replacements {
            let planIDSet = Set(planIDs)
            var nextRevisionBySegment: [String: Int] = [:]
            for replacement in replacements {
                let expected = nextRevisionBySegment[replacement.segmentID] ?? 2
                guard planIDSet.contains(replacement.segmentID),
                      replacement.revision == expected else {
                    throw LongFormPlanningError.invalidManifest("v4 replacement contract")
                }
                nextRevisionBySegment[replacement.segmentID] = expected + 1
            }
        }
        return self
    }

    public func canonicalJSONData() throws -> Data {
        _ = try validated()
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}

/// Read-only summary of an existing schema-v3 product manifest. It deliberately
/// does not fabricate plan, segment, seed, or range identities that v3 never
/// recorded.
public struct LegacyLongFormManifestV3Summary: Equatable, Sendable {
    public let schemaVersion: Int
    public let modelID: String
    public let mode: String
    public let segmentationMode: String
    public let generatedAtUTC: String
    public let totalSegments: Int
    public let generatedSegments: Int
    public let failedSegments: Int
    public let totalAudioDurationSeconds: Double
    public let encodedSegmentCount: Int
}

public enum LongFormManifestDocument: Equatable, Sendable {
    case version4(LongFormManifestV4)
    case legacyVersion3(LegacyLongFormManifestV3Summary)

    public static func decode(_ data: Data) throws -> Self {
        let decoder = JSONDecoder()
        let probe = try decoder.decode(SchemaProbe.self, from: data)
        switch probe.schemaVersion {
        case LongFormManifestV4.currentSchemaVersion:
            return .version4(try decoder.decode(LongFormManifestV4.self, from: data).validated())
        case 3:
            return .legacyVersion3(try decoder.decode(LegacyV3Bridge.self, from: data).summary)
        default:
            throw LongFormPlanningError.invalidManifestSchema(probe.schemaVersion)
        }
    }

    private struct SchemaProbe: Decodable {
        let schemaVersion: Int
    }

    private struct LegacyV3Bridge: Decodable {
        struct PerformanceSummary: Decodable {
            let totalSegments: Int
            let generatedSegments: Int
            let failedSegments: Int
            let totalAudioDurationSeconds: Double
        }

        struct IgnoredSegment: Decodable {
            init(from decoder: Decoder) throws {
                _ = decoder.codingPath
            }
        }

        let schemaVersion: Int
        let modelID: String
        let mode: String
        let segmentationMode: String
        let generatedAtUTC: String
        let performanceSummary: PerformanceSummary
        let segments: [IgnoredSegment]

        var summary: LegacyLongFormManifestV3Summary {
            LegacyLongFormManifestV3Summary(
                schemaVersion: schemaVersion,
                modelID: modelID,
                mode: mode,
                segmentationMode: segmentationMode,
                generatedAtUTC: generatedAtUTC,
                totalSegments: performanceSummary.totalSegments,
                generatedSegments: performanceSummary.generatedSegments,
                failedSegments: performanceSummary.failedSegments,
                totalAudioDurationSeconds: performanceSummary.totalAudioDurationSeconds,
                encodedSegmentCount: segments.count
            )
        }
    }
}

private extension String {
    func utf8Offset(of index: String.Index) -> Int {
        utf8.distance(from: utf8.startIndex, to: index)
    }

    func indexAfterWhitespace(from initial: String.Index) -> String.Index {
        var cursor = initial
        while cursor < endIndex {
            let next = index(after: cursor)
            let grapheme = self[cursor..<next]
            guard grapheme.unicodeScalars.allSatisfy({
                CharacterSet.whitespacesAndNewlines.contains($0)
            }) else { break }
            cursor = next
        }
        return cursor
    }

    func indexBeforeWhitespace(
        endingAt initial: String.Index,
        after lowerBound: String.Index
    ) -> String.Index {
        var cursor = initial
        while cursor > lowerBound {
            let previous = index(before: cursor)
            let grapheme = self[previous..<cursor]
            guard grapheme.unicodeScalars.allSatisfy({
                CharacterSet.whitespacesAndNewlines.contains($0)
            }) else { break }
            cursor = previous
        }
        return cursor
    }
}
