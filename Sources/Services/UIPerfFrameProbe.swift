import AppKit
import Foundation
import QuartzCore
import QwenVoiceCore

/// UI-performance frame probe for the `ui_test.sh macos perf` lane.
///
/// Enabled only when `QWENVOICE_UIPERF_FRAME_PROBE=<scenarioName>` is present
/// under the `QWENVOICE_DEBUG` master gate (registered knob). While enabled it
/// drives an `NSWindow` display link on the first key window and appends one
/// JSON line per 500 ms block to
/// `<appSupport>/diagnostics/ui-perf/frames-<launchEpochMS>-<scenario>.jsonl`.
///
/// Honesty note: a display link on the main run loop measures *main-run-loop
/// frame cadence* — a proxy for UI-thread hitching, not compositor-level frame
/// presents. It is the dominant signal for SwiftUI triage; compositor ground
/// truth remains an Instruments Hitches/Core Animation trace.
///
/// The probe owns a *private* `MainThreadStallWatchdog` instance so the
/// refcounted shared session used by `AppGenerationTimeline` is never
/// perturbed: a shared ref held across a generation would blank the
/// generation row's stall counters.
@MainActor
final class UIPerfFrameProbe: NSObject {
    static let scenarioEnvironmentKey = "QWENVOICE_UIPERF_FRAME_PROBE"
    private static let blockDurationMS = 500.0
    private static let retentionMaxFiles = 64
    private static let retentionMaxBytes = 16 * 1024 * 1024

    private static var active: UIPerfFrameProbe?

    static func startIfConfigured() {
        guard active == nil,
              let scenario = RuntimeDebugGate.value(for: scenarioEnvironmentKey)?
                  .trimmingCharacters(in: .whitespacesAndNewlines),
              !scenario.isEmpty else {
            return
        }
        let probe = UIPerfFrameProbe(scenario: scenario)
        active = probe
        probe.start()
    }

    private let scenario: String
    private let launchEpochMS: Int64
    private let watchdog = MainThreadStallWatchdog()
    private var displayLink: CADisplayLink?
    private var writer: FileHandle?
    private let writerQueue = DispatchQueue(label: "com.qwenvoice.uiperf-writer", qos: .utility)

    private var previousTimestamp: CFTimeInterval?
    private var blockStartEpochMS: Int64 = 0
    private var framesDelivered = 0
    private var sumExcessMS = 0.0
    private var maxGapMS = 0.0
    private var refreshIntervalMS = 0.0
    /// Gap histogram in multiples of the refresh interval:
    /// ≤1.25×, ≤1.75×, ≤2.75×, ≤4.75×, ≤8×, ≤16×, >16×.
    private var gapHistogram = [0, 0, 0, 0, 0, 0, 0]
    private var baselineCPU = UIPerfFrameProbe.cpuTimesMS()

    private init(scenario: String) {
        self.scenario = scenario
        self.launchEpochMS = Int64(Date().timeIntervalSince1970 * 1000)
        super.init()
    }

    private func start() {
        let directory = AppPaths.appSupportDir
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
            self, selector: #selector(windowBecameKey(_:)),
            name: NSWindow.didBecomeKeyNotification, object: nil)
        NotificationCenter.default.addObserver(
            self, selector: #selector(willTerminate(_:)),
            name: NSApplication.willTerminateNotification, object: nil)
        if let window = NSApp.keyWindow ?? NSApp.windows.first {
            attach(to: window)
        }
    }

    @objc private func windowBecameKey(_ notification: Notification) {
        guard displayLink == nil, let window = notification.object as? NSWindow else { return }
        attach(to: window)
    }

    private func attach(to window: NSWindow) {
        guard displayLink == nil else { return }
        let link = window.displayLink(target: self, selector: #selector(tick(_:)))
        // `.common` mode is load-bearing: during scroll, menu tracking, and
        // window resize the main run loop leaves `.default`, and those are
        // exactly the windows this probe exists to measure.
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    @objc private func tick(_ link: CADisplayLink) {
        let timestamp = link.timestamp
        let expected = link.duration
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
        _ = baselineCPU
    }

    @objc private func willTerminate(_ notification: Notification) {
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
