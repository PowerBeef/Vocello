import Foundation
import QuartzCore
import QwenVoiceCore
import UIKit

/// UI-performance frame probe for the `ui_test.sh ios perf` lane.
///
/// Enabled only when `QWENVOICE_UIPERF_FRAME_PROBE=<scenarioName>` is present
/// under the `QWENVOICE_DEBUG` master gate (registered knob; the iOS
/// counterpart of the macOS `UIPerfFrameProbe`). While enabled it drives a
/// `CADisplayLink` pinned to the app's 60 Hz cap
/// (`preferredFrameRateRange(60, 60, 60)`, the `IOSStudioInlinePlayerCard`
/// precedent) and appends one JSON line per 500 ms block to
/// `Library/Caches/Vocello/diagnostics/ui-perf/frames-<launchEpochMS>-<scenario>.jsonl`
/// — the devicectl-pullable app-container tree, the same one
/// `IOSDeviceDiagnosticsRecorder` mirrors into.
///
/// Honesty note: a display link on the main run loop measures *main-run-loop
/// frame cadence* — a proxy for UI-thread hitching, not render-server frame
/// presents. Expected intervals come from the link's own per-tick target,
/// never a hard-coded 16.67 ms: on ProMotion hardware `duration` reports the
/// panel's native refresh period, not the pinned rate this probe requested,
/// so `targetTimestamp - timestamp` is the only honest expectation. The
/// checker (`scripts/check_ios_ui_perf.py`) fail-closes when the observed
/// median block cadence leaves the 55–65 Hz band, so a run where the system
/// ignored the pin (Low Power Mode, thermal caps) can never publish quietly.
///
/// The probe owns a *private* `MainThreadStallWatchdog` instance so the
/// refcounted shared session used by generation telemetry is never perturbed.
@MainActor
final class IOSUIPerfFrameProbe: NSObject {
    static let scenarioEnvironmentKey = "QWENVOICE_UIPERF_FRAME_PROBE"
    private static let blockDurationMS = 500.0
    private static let retentionMaxFiles = 64
    private static let retentionMaxBytes = 16 * 1024 * 1024

    private static var active: IOSUIPerfFrameProbe?

    static func startIfConfigured() {
        guard active == nil,
              let scenario = RuntimeDebugGate.value(for: scenarioEnvironmentKey)?
                  .trimmingCharacters(in: .whitespacesAndNewlines),
              !scenario.isEmpty else {
            return
        }
        let probe = IOSUIPerfFrameProbe(scenario: scenario)
        active = probe
        probe.start()
    }

    private let scenario: String
    private let launchEpochMS: Int64
    private let watchdog = MainThreadStallWatchdog()
    private var displayLink: CADisplayLink?
    private var writer: FileHandle?
    private let writerQueue = DispatchQueue(label: "com.qwenvoice.ios-uiperf-writer", qos: .utility)
    private var finished = false

    private var previousTimestamp: CFTimeInterval?
    private var blockStartEpochMS: Int64 = 0
    private var framesDelivered = 0
    private var sumExcessMS = 0.0
    private var maxGapMS = 0.0
    private var refreshIntervalMS = 0.0
    /// Gap histogram in multiples of the refresh interval:
    /// ≤1.25×, ≤1.75×, ≤2.75×, ≤4.75×, ≤8×, ≤16×, >16×.
    private var gapHistogram = [0, 0, 0, 0, 0, 0, 0]

    private init(scenario: String) {
        self.scenario = scenario
        self.launchEpochMS = Int64(Date().timeIntervalSince1970 * 1000)
        super.init()
    }

    private func start() {
        guard let caches = FileManager.default.urls(
            for: .cachesDirectory, in: .userDomainMask
        ).first else { return }
        let directory = caches
            .appendingPathComponent("Vocello", isDirectory: true)
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("ui-perf", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        Self.pruneRetention(in: directory)
        let fileURL = directory.appendingPathComponent(
            "frames-\(launchEpochMS)-\(scenario).jsonl")
        FileManager.default.createFile(atPath: fileURL.path, contents: nil)
        writer = try? FileHandle(forWritingTo: fileURL)
        watchdog.begin()
        blockStartEpochMS = Int64(Date().timeIntervalSince1970 * 1000)

        NotificationCenter.default.addObserver(
            self, selector: #selector(willTerminate(_:)),
            name: UIApplication.willTerminateNotification, object: nil)
        // XCUIApplication.terminate() usually delivers willTerminate, but the
        // background transition is the reliable last-write point on iOS.
        NotificationCenter.default.addObserver(
            self, selector: #selector(didEnterBackground(_:)),
            name: UIApplication.didEnterBackgroundNotification, object: nil)

        let link = CADisplayLink(target: self, selector: #selector(tick(_:)))
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 60, preferred: 60)
        // `.common` mode is load-bearing: during scroll and sheet tracking the
        // main run loop leaves `.default`, and those are exactly the windows
        // this probe exists to measure.
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    @objc private func tick(_ link: CADisplayLink) {
        let timestamp = link.timestamp
        let expected = link.targetTimestamp - link.timestamp
        if refreshIntervalMS == 0, expected > 0 {
            refreshIntervalMS = expected * 1000
        }
        defer { previousTimestamp = timestamp }
        guard let previous = previousTimestamp else { return }
        let deltaMS = (timestamp - previous) * 1000
        let expectedMS = expected * 1000
        framesDelivered += 1
        sumExcessMS += max(0, deltaMS - expectedMS)
        maxGapMS = max(maxGapMS, deltaMS)
        if expectedMS > 0 {
            let multiple = deltaMS / expectedMS
            let bucket: Int
            switch multiple {
            case ..<1.25: bucket = 0
            case ..<1.75: bucket = 1
            case ..<2.75: bucket = 2
            case ..<4.75: bucket = 3
            case ..<8.0: bucket = 4
            case ..<16.0: bucket = 5
            default: bucket = 6
            }
            gapHistogram[bucket] += 1
        }
        let nowEpochMS = Int64(Date().timeIntervalSince1970 * 1000)
        if Double(nowEpochMS - blockStartEpochMS) >= Self.blockDurationMS {
            flushBlock(endEpochMS: nowEpochMS)
        }
    }

    private func flushBlock(endEpochMS: Int64) {
        let cpu = Self.cpuTimesMS()
        var row: [String: Any] = [
            "kind": "block",
            "scenario": scenario,
            "startEpochMS": blockStartEpochMS,
            "endEpochMS": endEpochMS,
            "framesDelivered": framesDelivered,
            "refreshIntervalMS": (refreshIntervalMS * 1000).rounded() / 1000,
            "sumExcessMS": (sumExcessMS * 1000).rounded() / 1000,
            "maxGapMS": (maxGapMS * 1000).rounded() / 1000,
            "gapHistogram": gapHistogram,
            "cpuUserMS": cpu.user,
            "cpuSystemMS": cpu.system,
            "footprintMB": Self.physicalFootprintMB(),
            "thermalState": thermalStateName(),
        ]
        if refreshIntervalMS > 0 {
            let windowMS = Double(endEpochMS - blockStartEpochMS)
            row["expectedFrames"] = Int((windowMS / refreshIntervalMS).rounded())
        }
        append(row)
        blockStartEpochMS = endEpochMS
        framesDelivered = 0
        sumExcessMS = 0
        maxGapMS = 0
        gapHistogram = [0, 0, 0, 0, 0, 0, 0]
    }

    @objc private func willTerminate(_ notification: Notification) {
        finish()
    }

    @objc private func didEnterBackground(_ notification: Notification) {
        finish()
    }

    private func finish() {
        guard !finished else { return }
        finished = true
        let endEpochMS = Int64(Date().timeIntervalSince1970 * 1000)
        if framesDelivered > 0 {
            flushBlock(endEpochMS: endEpochMS)
        }
        var summary: [String: Any] = [
            "kind": "summary",
            "scenario": scenario,
            "launchEpochMS": launchEpochMS,
            "endEpochMS": endEpochMS,
        ]
        if let report = watchdog.end() {
            for (key, value) in report.asCounters {
                summary[key] = value
            }
        }
        append(summary)
        writerQueue.sync { }
        try? writer?.close()
        displayLink?.invalidate()
        displayLink = nil
    }

    private func append(_ row: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]),
              let writer else {
            return
        }
        var line = data
        line.append(0x0A)
        writerQueue.async {
            try? writer.write(contentsOf: line)
        }
    }

    private func thermalStateName() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    private static func cpuTimesMS() -> (user: Int, system: Int) {
        var usage = rusage()
        getrusage(RUSAGE_SELF, &usage)
        let user = usage.ru_utime.tv_sec * 1000 + Int(usage.ru_utime.tv_usec) / 1000
        let system = usage.ru_stime.tv_sec * 1000 + Int(usage.ru_stime.tv_usec) / 1000
        return (user, system)
    }

    private static func physicalFootprintMB() -> Double {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(
            MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { raw in
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), raw, &count)
            }
        }
        guard result == KERN_SUCCESS else { return 0 }
        return Double(info.phys_footprint) / (1024 * 1024)
    }

    private static func pruneRetention(in directory: URL) {
        let manager = FileManager.default
        guard let entries = try? manager.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey]
        ) else { return }
        let sorted = entries
            .filter { $0.lastPathComponent.hasPrefix("frames-") }
            .sorted { lhs, rhs in
                let l = (try? lhs.resourceValues(forKeys: [.contentModificationDateKey])
                    .contentModificationDate) ?? .distantPast
                let r = (try? rhs.resourceValues(forKeys: [.contentModificationDateKey])
                    .contentModificationDate) ?? .distantPast
                return l > r
            }
        var kept = 0
        var totalBytes = 0
        for url in sorted {
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            kept += 1
            totalBytes += size
            if kept > retentionMaxFiles || totalBytes > retentionMaxBytes {
                try? manager.removeItem(at: url)
            }
        }
    }
}
