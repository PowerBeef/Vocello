import Foundation

/// Privacy-safe terminal evidence reconstructed from the engine telemetry row owned by one
/// generation. This keeps diagnostics consumers from independently interpreting failure notes or
/// treating derivative missing fields as separate root causes after generation has already failed.
public struct GenerationTerminalDiagnosticEvidence: Hashable, Codable, Sendable {
    public enum Classification: String, Hashable, Codable, Sendable {
        case postGenerationQC = "post_generation_qc"
        case postGenerationFailure = "post_generation_failure"
        case preAudioStartup = "pre_audio_startup"
        case unmaterializedUnknown = "unmaterialized_unknown"
    }

    public let requestReceipt: GenerationRequestReceipt?
    public let audioQC: AudioQCReport?
    public let failureCode: String?
    public let classification: Classification
    public let diagnosticArtifacts: [StartupReliabilityArtifactEvidence]

    public init(
        requestReceipt: GenerationRequestReceipt?,
        audioQC: AudioQCReport?,
        notes: [String: String],
        stageNames: [String]
    ) {
        self.requestReceipt = requestReceipt
        self.audioQC = audioQC
        self.failureCode = Self.safeIdentifier(notes["nativeRuntimeFailureCode"])
        if audioQC?.verdict == .fail {
            classification = .postGenerationQC
        } else if stageNames.contains(
            GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage
        ) {
            classification = .postGenerationFailure
        } else if stageNames.contains(where: { $0.hasPrefix("startup.") }) {
            classification = .preAudioStartup
        } else {
            classification = .unmaterializedUnknown
        }
        diagnosticArtifacts = Self.parseArtifacts(notes: notes)
    }

    public static func snapshot(
        from records: [GenerationTelemetryRecord]
    ) -> GenerationTerminalDiagnosticEvidence? {
        guard let terminal = records.max(by: { lhs, rhs in
            let lhsAttempt = lhs.requestReceipt?.retryAttempt ?? -1
            let rhsAttempt = rhs.requestReceipt?.retryAttempt ?? -1
            if lhsAttempt != rhsAttempt { return lhsAttempt < rhsAttempt }
            return lhs.recordedAt < rhs.recordedAt
        }) else { return nil }
        return GenerationTerminalDiagnosticEvidence(
            requestReceipt: terminal.requestReceipt,
            audioQC: terminal.audioQC,
            notes: terminal.notes,
            stageNames: terminal.stageMarks.map(\.stage)
        )
    }

    private static func parseArtifacts(
        notes: [String: String]
    ) -> [StartupReliabilityArtifactEvidence] {
        var result: [StartupReliabilityArtifactEvidence] = []
        if let sha256 = validatedDigest(notes["codecTraceSHA256"]),
           let byteCount = nonnegativeInteger(notes["codecTraceByteCount"]),
           let frameCount = nonnegativeInteger(notes["codecTraceFrameCount"]),
           let minimum = nonnegativeInteger(notes["codecTraceCodeGroupsMinimum"]),
           let maximum = nonnegativeInteger(notes["codecTraceCodeGroupsMaximum"]),
           maximum >= minimum,
           let complete = strictBoolean(notes["codecTraceComplete"]),
           let ranges = parseCodecRanges(notes["codecTraceChunkRanges"], frameCount: frameCount) {
            result.append(StartupReliabilityArtifactEvidence(
                kind: .codecTrace,
                sha256: sha256,
                byteCount: byteCount,
                codecFrameCount: frameCount,
                codeGroupRange: .init(minimum: minimum, maximum: maximum),
                codecChunkRanges: ranges,
                complete: complete
            ))
        }
        if let sha256 = validatedDigest(notes["rejectedAudioSHA256"]),
           let byteCount = nonnegativeInteger(notes["rejectedAudioByteCount"]),
           let duration = positiveFiniteDouble(notes["rejectedAudioDurationSeconds"]) {
            result.append(StartupReliabilityArtifactEvidence(
                kind: .rejectedAudio,
                sha256: sha256,
                byteCount: byteCount,
                durationSeconds: duration
            ))
        }
        return result.sorted { $0.kind.rawValue < $1.kind.rawValue }
    }

    private static func parseCodecRanges(
        _ raw: String?,
        frameCount: Int
    ) -> [StartupReliabilityCodecFrameRange]? {
        guard let raw, !raw.isEmpty else { return nil }
        let components = raw.split(separator: ",", omittingEmptySubsequences: false)
        let ranges = components.compactMap { component -> StartupReliabilityCodecFrameRange? in
            let values = component.split(separator: ":", omittingEmptySubsequences: false)
            guard values.count == 2,
                  let start = Int(values[0]),
                  let end = Int(values[1]),
                  start >= 0,
                  end > start,
                  end <= frameCount else { return nil }
            return StartupReliabilityCodecFrameRange(start: start, endExclusive: end)
        }
        return ranges.count == components.count ? ranges : nil
    }

    private static func validatedDigest(_ value: String?) -> String? {
        guard let value = value?.lowercased(),
              value.count == 64,
              value.allSatisfy(\.isHexDigit) else { return nil }
        return value
    }

    private static func safeIdentifier(_ value: String?) -> String? {
        guard let value,
              (1 ... 96).contains(value.count),
              value.unicodeScalars.allSatisfy({ scalar in
                  CharacterSet.alphanumerics.contains(scalar)
                      || scalar == "_"
                      || scalar == "-"
                      || scalar == "."
              }) else { return nil }
        return value
    }

    private static func nonnegativeInteger(_ value: String?) -> Int? {
        guard let value, let result = Int(value), result >= 0 else { return nil }
        return result
    }

    private static func positiveFiniteDouble(_ value: String?) -> Double? {
        guard let value,
              let result = Double(value),
              result.isFinite,
              result > 0 else { return nil }
        return result
    }

    private static func strictBoolean(_ value: String?) -> Bool? {
        switch value {
        case "true": true
        case "false": false
        default: nil
        }
    }
}
