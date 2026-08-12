import Foundation
import MetricKit
import QwenVoiceCore

/// Registers early and keeps the legacy iOS 26 MetricKit subscriber alive for
/// the process lifetime. MetricKit is delayed field evidence, not a per-take
/// sampler; only bounded allowlisted aggregates are forwarded to local storage.
final class IOSMetricKitMemoryReporter: NSObject, MXMetricManagerSubscriber, @unchecked Sendable {
    static let shared = IOSMetricKitMemoryReporter()

    private let stateLock = NSLock()
    private var isStarted = false

    private override init() {
        super.init()
    }

    func start() {
        stateLock.lock()
        guard !isStarted else {
            stateLock.unlock()
            return
        }
        isStarted = true
        stateLock.unlock()
        MXMetricManager.shared.add(self)
    }

    deinit {
        MXMetricManager.shared.remove(self)
    }

    func didReceive(_ payloads: [MXMetricPayload]) {
        let records = payloads.map(Self.metricRecord)
        guard !records.isEmpty else { return }
        Task {
            await IOSMetricKitMemorySummaryStore.shared.append(records)
        }
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        let records = payloads.map(Self.diagnosticRecord)
        guard !records.isEmpty else { return }
        Task {
            await IOSMetricKitMemorySummaryStore.shared.append(records)
        }
    }

    private static func metricRecord(_ payload: MXMetricPayload) -> MetricKitMemoryExitSummaryRecord {
        let exits = payload.applicationExitMetrics
        let foreground = exits.map { metric in
            let data = metric.foregroundExitData
            return MetricKitForegroundExitCounts(
                normal: Int(clamping: data.cumulativeNormalAppExitCount),
                watchdog: Int(clamping: data.cumulativeAppWatchdogExitCount),
                memoryResourceLimit: Int(clamping: data.cumulativeMemoryResourceLimitExitCount),
                badAccess: Int(clamping: data.cumulativeBadAccessExitCount),
                illegalInstruction: Int(clamping: data.cumulativeIllegalInstructionExitCount),
                abnormal: Int(clamping: data.cumulativeAbnormalExitCount)
            )
        }
        let background = exits.map { metric in
            let data = metric.backgroundExitData
            return MetricKitBackgroundExitCounts(
                normal: Int(clamping: data.cumulativeNormalAppExitCount),
                watchdog: Int(clamping: data.cumulativeAppWatchdogExitCount),
                memoryResourceLimit: Int(clamping: data.cumulativeMemoryResourceLimitExitCount),
                memoryPressure: Int(clamping: data.cumulativeMemoryPressureExitCount),
                badAccess: Int(clamping: data.cumulativeBadAccessExitCount),
                illegalInstruction: Int(clamping: data.cumulativeIllegalInstructionExitCount),
                abnormal: Int(clamping: data.cumulativeAbnormalExitCount),
                taskTimeout: Int(clamping: data.cumulativeBackgroundTaskAssertionTimeoutExitCount),
                cpuResourceLimit: Int(clamping: data.cumulativeCPUResourceLimitExitCount),
                suspendedWithLockedFile: Int(clamping: data.cumulativeSuspendedWithLockedFileExitCount)
            )
        }
        return MetricKitMemoryExitSummaryRecord(
            kind: .metricPayload,
            intervalStart: timestamp(payload.timeStampBegin),
            intervalEnd: timestamp(payload.timeStampEnd),
            peakMemoryMB: payload.memoryMetrics?.peakMemoryUsage
                .converted(to: UnitInformationStorage.megabytes).value,
            foregroundExitCounts: foreground,
            backgroundExitCounts: background,
            uiResponsiveness: uiResponsivenessAggregates(payload)
        )
    }

    /// Compact allowlisted reduction of MXAnimationMetric /
    /// MXAppResponsivenessMetric (ios-ui-2026-08 advisory field evidence;
    /// daily aggregates, never run-correlated, never gating).
    private static func uiResponsivenessAggregates(
        _ payload: MXMetricPayload
    ) -> MetricKitUIResponsivenessAggregates? {
        var hangEventCount: Int?
        var hangTotalSecondsApprox: Double?
        var hangMaxBucketEndSeconds: Double?
        if let histogram = payload.applicationResponsivenessMetrics?.histogrammedApplicationHangTime {
            var count = 0
            var totalSeconds = 0.0
            var maxEndSeconds = 0.0
            let enumerator = histogram.bucketEnumerator
            while let bucket = enumerator.nextObject() as? MXHistogramBucket<UnitDuration> {
                let bucketCount = bucket.bucketCount
                guard bucketCount > 0 else { continue }
                let start = bucket.bucketStart.converted(to: .seconds).value
                let end = bucket.bucketEnd.converted(to: .seconds).value
                count += bucketCount
                totalSeconds += Double(bucketCount) * (start + end) / 2
                maxEndSeconds = max(maxEndSeconds, end)
            }
            hangEventCount = count
            hangTotalSecondsApprox = totalSeconds
            hangMaxBucketEndSeconds = count > 0 ? maxEndSeconds : nil
        }
        let aggregates = MetricKitUIResponsivenessAggregates(
            scrollHitchTimeRatioMSPerS: payload.animationMetrics?.scrollHitchTimeRatio.value,
            hangEventCount: hangEventCount,
            hangTimeTotalSecondsApprox: hangTotalSecondsApprox,
            hangTimeMaxBucketEndSeconds: hangMaxBucketEndSeconds
        )
        return aggregates.isEmpty ? nil : aggregates
    }

    private static func diagnosticRecord(_ payload: MXDiagnosticPayload) -> MetricKitMemoryExitSummaryRecord {
        MetricKitMemoryExitSummaryRecord(
            kind: .diagnosticPayload,
            intervalStart: timestamp(payload.timeStampBegin),
            intervalEnd: timestamp(payload.timeStampEnd),
            diagnosticCounts: MetricKitDiagnosticCounts(
                crash: payload.crashDiagnostics?.count ?? 0,
                hang: payload.hangDiagnostics?.count ?? 0,
                cpuException: payload.cpuExceptionDiagnostics?.count ?? 0,
                diskWriteException: payload.diskWriteExceptionDiagnostics?.count ?? 0
            )
        )
    }

    private static func timestamp(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}

private actor IOSMetricKitMemorySummaryStore {
    static let shared = IOSMetricKitMemorySummaryStore()

    private let outputURL: URL?
    private let encoder: JSONEncoder
    private let decoder = JSONDecoder()

    private init() {
        self.outputURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("Vocello", isDirectory: true)
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(MetricKitMemoryExitSummaryDocument.fileName, isDirectory: false)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        self.encoder = encoder
    }

    func append(_ records: [MetricKitMemoryExitSummaryRecord]) {
        guard let outputURL, !records.isEmpty else { return }
        do {
            let existing: MetricKitMemoryExitSummaryDocument
            if let data = try? Data(contentsOf: outputURL),
               let decoded = try? decoder.decode(MetricKitMemoryExitSummaryDocument.self, from: data),
               decoded.schemaVersion == MetricKitMemoryExitSummaryDocument.currentSchemaVersion {
                existing = decoded
            } else {
                existing = MetricKitMemoryExitSummaryDocument(updatedAt: "", records: [])
            }
            let updated = existing.appending(
                records,
                updatedAt: ISO8601DateFormatter().string(from: Date())
            )
            try FileManager.default.createDirectory(
                at: outputURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try encoder.encode(updated).write(to: outputURL, options: .atomic)
        } catch {
            if TelemetryGate.resolvedEnabled {
                // Intentionally omit paths and raw errors from diagnostics output.
                print("[IOSMetricKitMemoryReporter] Aggregate write failed.")
            }
        }
    }
}
