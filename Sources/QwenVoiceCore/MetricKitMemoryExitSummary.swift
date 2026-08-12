import Foundation

public enum MetricKitMemoryExitRecordKind: String, Codable, Hashable, Sendable {
    case metricPayload
    case diagnosticPayload
}

public struct MetricKitForegroundExitCounts: Codable, Hashable, Sendable {
    public let normal: Int
    public let watchdog: Int
    public let memoryResourceLimit: Int
    public let badAccess: Int
    public let illegalInstruction: Int
    public let abnormal: Int

    public init(
        normal: Int,
        watchdog: Int,
        memoryResourceLimit: Int,
        badAccess: Int,
        illegalInstruction: Int,
        abnormal: Int
    ) {
        self.normal = normal
        self.watchdog = watchdog
        self.memoryResourceLimit = memoryResourceLimit
        self.badAccess = badAccess
        self.illegalInstruction = illegalInstruction
        self.abnormal = abnormal
    }
}

public struct MetricKitBackgroundExitCounts: Codable, Hashable, Sendable {
    public let normal: Int
    public let watchdog: Int
    public let memoryResourceLimit: Int
    public let memoryPressure: Int
    public let badAccess: Int
    public let illegalInstruction: Int
    public let abnormal: Int
    public let taskTimeout: Int
    public let cpuResourceLimit: Int
    public let suspendedWithLockedFile: Int

    public init(
        normal: Int,
        watchdog: Int,
        memoryResourceLimit: Int,
        memoryPressure: Int,
        badAccess: Int,
        illegalInstruction: Int,
        abnormal: Int,
        taskTimeout: Int,
        cpuResourceLimit: Int,
        suspendedWithLockedFile: Int
    ) {
        self.normal = normal
        self.watchdog = watchdog
        self.memoryResourceLimit = memoryResourceLimit
        self.memoryPressure = memoryPressure
        self.badAccess = badAccess
        self.illegalInstruction = illegalInstruction
        self.abnormal = abnormal
        self.taskTimeout = taskTimeout
        self.cpuResourceLimit = cpuResourceLimit
        self.suspendedWithLockedFile = suspendedWithLockedFile
    }
}

public struct MetricKitDiagnosticCounts: Codable, Hashable, Sendable {
    public let crash: Int
    public let hang: Int
    public let cpuException: Int
    public let diskWriteException: Int

    public init(crash: Int, hang: Int, cpuException: Int, diskWriteException: Int) {
        self.crash = crash
        self.hang = hang
        self.cpuException = cpuException
        self.diskWriteException = diskWriteException
    }
}

/// Typed delayed field evidence for memory-related exits. These are aggregate
/// counters reported by MetricKit and are intentionally not attributed to a
/// generation or expanded into raw diagnostic payloads.
public struct MetricKitMemoryExitCounts: Codable, Hashable, Sendable {
    public let kind: GenerationMemoryEventKind
    public let source: NativeMemoryEventSource
    public let foregroundResourceLimit: Int
    public let backgroundResourceLimit: Int
    public let backgroundMemoryPressure: Int

    public init(
        foregroundResourceLimit: Int,
        backgroundResourceLimit: Int,
        backgroundMemoryPressure: Int
    ) {
        self.kind = .memoryExit
        self.source = .metricKit
        self.foregroundResourceLimit = max(foregroundResourceLimit, 0)
        self.backgroundResourceLimit = max(backgroundResourceLimit, 0)
        self.backgroundMemoryPressure = max(backgroundMemoryPressure, 0)
    }

    public var total: Int {
        foregroundResourceLimit + backgroundResourceLimit + backgroundMemoryPressure
    }
}

/// Allowlisted UI-responsiveness aggregates (ios-ui-2026-08 advisory field
/// evidence): MXAnimationMetric's scroll-hitch time ratio plus a compact
/// reduction of MXAppResponsivenessMetric's hang-time histogram. Daily
/// intervals, never run-correlated, never gating — the same field-diagnostic
/// posture as the memory/exit aggregates in this file.
public struct MetricKitUIResponsivenessAggregates: Codable, Hashable, Sendable {
    /// Scroll hitch time ratio as MetricKit delivers it (ms of hitch per
    /// second of scrolling).
    public let scrollHitchTimeRatioMSPerS: Double?
    /// Total hang events across the hang-time histogram's populated buckets.
    public let hangEventCount: Int?
    /// Bucket-midpoint-weighted total hang seconds (approximate by design —
    /// MetricKit only delivers the histogram).
    public let hangTimeTotalSecondsApprox: Double?
    /// Upper bound of the worst populated hang bucket, in seconds.
    public let hangTimeMaxBucketEndSeconds: Double?

    public init(
        scrollHitchTimeRatioMSPerS: Double? = nil,
        hangEventCount: Int? = nil,
        hangTimeTotalSecondsApprox: Double? = nil,
        hangTimeMaxBucketEndSeconds: Double? = nil
    ) {
        self.scrollHitchTimeRatioMSPerS = scrollHitchTimeRatioMSPerS.map { max($0, 0) }
        self.hangEventCount = hangEventCount.map { max($0, 0) }
        self.hangTimeTotalSecondsApprox = hangTimeTotalSecondsApprox.map { max($0, 0) }
        self.hangTimeMaxBucketEndSeconds = hangTimeMaxBucketEndSeconds.map { max($0, 0) }
    }

    public var isEmpty: Bool {
        scrollHitchTimeRatioMSPerS == nil && hangEventCount == nil
            && hangTimeTotalSecondsApprox == nil && hangTimeMaxBucketEndSeconds == nil
    }
}

/// Allowlisted MetricKit aggregate. No raw payload JSON, call stack, process
/// path, device identity, or user content is retained.
public struct MetricKitMemoryExitSummaryRecord: Codable, Hashable, Sendable {
    public let kind: MetricKitMemoryExitRecordKind
    public let intervalStart: String
    public let intervalEnd: String
    public let peakMemoryMB: Double?
    public let foregroundExitCounts: MetricKitForegroundExitCounts?
    public let backgroundExitCounts: MetricKitBackgroundExitCounts?
    public let memoryExitCounts: MetricKitMemoryExitCounts?
    public let diagnosticCounts: MetricKitDiagnosticCounts?
    public let uiResponsiveness: MetricKitUIResponsivenessAggregates?

    public init(
        kind: MetricKitMemoryExitRecordKind,
        intervalStart: String,
        intervalEnd: String,
        peakMemoryMB: Double? = nil,
        foregroundExitCounts: MetricKitForegroundExitCounts? = nil,
        backgroundExitCounts: MetricKitBackgroundExitCounts? = nil,
        memoryExitCounts: MetricKitMemoryExitCounts? = nil,
        diagnosticCounts: MetricKitDiagnosticCounts? = nil,
        uiResponsiveness: MetricKitUIResponsivenessAggregates? = nil
    ) {
        self.kind = kind
        self.intervalStart = String(intervalStart.prefix(40))
        self.intervalEnd = String(intervalEnd.prefix(40))
        self.peakMemoryMB = peakMemoryMB.map { max($0, 0) }
        self.foregroundExitCounts = foregroundExitCounts
        self.backgroundExitCounts = backgroundExitCounts
        self.uiResponsiveness = uiResponsiveness.flatMap { $0.isEmpty ? nil : $0 }
        self.memoryExitCounts = memoryExitCounts ?? {
            guard foregroundExitCounts != nil || backgroundExitCounts != nil else { return nil }
            return MetricKitMemoryExitCounts(
                foregroundResourceLimit: foregroundExitCounts?.memoryResourceLimit ?? 0,
                backgroundResourceLimit: backgroundExitCounts?.memoryResourceLimit ?? 0,
                backgroundMemoryPressure: backgroundExitCounts?.memoryPressure ?? 0
            )
        }()
        self.diagnosticCounts = diagnosticCounts
    }

    fileprivate var identity: String {
        "\(kind.rawValue)|\(intervalStart)|\(intervalEnd)"
    }
}

public struct MetricKitMemoryExitSummaryDocument: Codable, Hashable, Sendable {
    public static let currentSchemaVersion = 1
    public static let fileName = "metrickit-memory-exit-summaries.json"
    public static let maximumRecordCount = 64

    public let schemaVersion: Int
    public let updatedAt: String
    public let records: [MetricKitMemoryExitSummaryRecord]

    public init(
        schemaVersion: Int = Self.currentSchemaVersion,
        updatedAt: String,
        records: [MetricKitMemoryExitSummaryRecord]
    ) {
        self.schemaVersion = schemaVersion
        self.updatedAt = String(updatedAt.prefix(40))
        self.records = records
    }

    /// Idempotently replace redelivered intervals, sort chronologically, and
    /// retain only the newest bounded window.
    public func appending(
        _ additions: [MetricKitMemoryExitSummaryRecord],
        updatedAt: String,
        maximumRecordCount: Int = Self.maximumRecordCount
    ) -> MetricKitMemoryExitSummaryDocument {
        var byIdentity: [String: MetricKitMemoryExitSummaryRecord] = [:]
        for record in records {
            byIdentity[record.identity] = record
        }
        for record in additions {
            byIdentity[record.identity] = record
        }
        let sorted = byIdentity.values.sorted { lhs, rhs in
            if lhs.intervalEnd != rhs.intervalEnd { return lhs.intervalEnd < rhs.intervalEnd }
            if lhs.intervalStart != rhs.intervalStart { return lhs.intervalStart < rhs.intervalStart }
            return lhs.kind.rawValue < rhs.kind.rawValue
        }
        let limit = max(maximumRecordCount, 0)
        let bounded = limit == 0 ? [] : Array(sorted.suffix(limit))
        return MetricKitMemoryExitSummaryDocument(updatedAt: updatedAt, records: bounded)
    }
}
