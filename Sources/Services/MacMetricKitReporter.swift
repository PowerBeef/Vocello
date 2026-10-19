import Foundation
import MetricKit
import os
import QwenVoiceCore

/// The Mac counterpart of the iPhone's two MetricKit subscribers (DW-03): the
/// bounded memory/exit and UI-responsiveness aggregate of
/// `IOSMetricKitMemoryReporter`, and the crash and hang payloads
/// `IOSCrashObserver` keeps for symbolication. MetricKit is delayed daily field
/// evidence, never a per-take sampler: nothing here is run-correlated, gates a
/// lane or leaves the machine.
///
/// It writes only under the app-support `diagnostics/` folder:
/// - `metrickit-memory-exit-summaries.json`: the same allowlisted, bounded
///   `MetricKitMemoryExitSummaryDocument` the iPhone keeps (no raw payload,
///   call stack, path or identity);
/// - `crashes/metrickit-<time>-<id>.json`: a diagnostic payload that carries a
///   crash or a hang, with its Objective-C exception text and its path-bearing
///   crash metadata passed through `DiagnosticPrivacy.redactedMetricKitPayload`,
///   as on the iPhone.
///
/// The iPhone observer's uncaught-exception hook is not mirrored: on the Mac
/// the system already keeps the crash report.
final class MacMetricKitReporter: NSObject, MXMetricManagerSubscriber, Sendable {
    static let shared = MacMetricKitReporter()

    private let startState = OSAllocatedUnfairLock(initialState: false)
    private let store: MacMetricKitDiagnosticsStore

    private override init() {
        store = MacMetricKitDiagnosticsStore(
            diagnosticsDirectory: AppPaths.appSupportDir
                .appendingPathComponent("diagnostics", isDirectory: true)
        )
        super.init()
    }

    /// Idempotent; called once at launch. A launch under an app-support override (a lane's
    /// temporary root) does not subscribe: MetricKit delivers each payload once, and the
    /// host's own crash or hang report would vanish with that root.
    func start() {
        guard !AppPaths.usesAppSupportOverride else { return }
        let alreadyStarted = startState.withLock { isStarted in
            defer { isStarted = true }
            return isStarted
        }
        guard !alreadyStarted else { return }
        MXMetricManager.shared.add(self)
    }

    func didReceive(_ payloads: [MXMetricPayload]) {
        let records = payloads.map(Self.metricRecord)
        guard !records.isEmpty else { return }
        let store = store
        Task { @concurrent in
            await store.appendSummaries(records)
        }
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        let records = payloads.map(Self.diagnosticRecord)
        // Only a crash or a hang is actionable, as on the iPhone. The payload
        // is redacted here, before it leaves this call.
        let crashPayloads: [Data] = payloads.compactMap { payload in
            let crashes = payload.crashDiagnostics ?? []
            let hangs = payload.hangDiagnostics ?? []
            guard !(crashes.isEmpty && hangs.isEmpty) else { return nil }
            guard let json = DiagnosticPrivacy.redactedMetricKitPayload(payload.jsonRepresentation()) else {
                MacMetricKitLog.logger.error("skipped an unreadable MetricKit payload")
                return nil
            }
            return json
        }
        guard !records.isEmpty || !crashPayloads.isEmpty else { return }
        let store = store
        Task { @concurrent in
            await store.appendSummaries(records)
            await store.writeCrashPayloads(crashPayloads)
        }
    }

    // The reductions below mirror `IOSMetricKitMemoryReporter` field for field,
    // so both platforms publish the same document shape.

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

/// Serializes the reporter's file writes off MetricKit's delivery queue.
private actor MacMetricKitDiagnosticsStore {
    private let summaryURL: URL
    private let crashesDirectory: URL
    private let encoder: JSONEncoder
    private let decoder = JSONDecoder()

    init(diagnosticsDirectory: URL) {
        summaryURL = diagnosticsDirectory.appendingPathComponent(
            MetricKitMemoryExitSummaryDocument.fileName,
            isDirectory: false
        )
        crashesDirectory = diagnosticsDirectory.appendingPathComponent("crashes", isDirectory: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        self.encoder = encoder
    }

    func appendSummaries(_ records: [MetricKitMemoryExitSummaryRecord]) {
        guard !records.isEmpty else { return }
        do {
            let existing: MetricKitMemoryExitSummaryDocument
            if let data = try? Data(contentsOf: summaryURL),
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
                at: summaryURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try encoder.encode(updated).write(to: summaryURL, options: .atomic)
        } catch {
            let summary = DiagnosticPrivacy.summary(of: error).description
            MacMetricKitLog.logger.error("aggregate write failed: \(summary, privacy: .public)")
        }
    }

    func writeCrashPayloads(_ payloads: [Data]) {
        for payload in payloads {
            let name = "metrickit-\(Self.stamp())-\(UUID().uuidString.prefix(8)).json"
            let url = crashesDirectory.appendingPathComponent(name, isDirectory: false)
            do {
                try FileManager.default.createDirectory(at: crashesDirectory, withIntermediateDirectories: true)
                try payload.write(to: url, options: .atomic)
                MacMetricKitLog.logger.info("wrote \(name, privacy: .public)")
            } catch {
                let summary = DiagnosticPrivacy.summary(of: error).description
                MacMetricKitLog.logger.error("crash payload write failed: \(summary, privacy: .public)")
            }
        }
    }

    private static func stamp() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: Date())
    }
}

/// Unified-log channel for this file. Only code-owned file names and typed
/// error summaries are public.
private enum MacMetricKitLog {
    static let logger = Logger(subsystem: "com.qwenvoice.app", category: "metrickit")
}
