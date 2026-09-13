import AppKit
import CoreAudio
import Foundation
import Synchronization

// Played-audio capture for the macOS benchmark lane (PC-01).
//
// A Core Audio process tap on the app under test, read through a private
// aggregate device, records exactly what the app renders while muting its
// physical output (`.mutedWhenTapped`). Everything runs inside the XCUITest
// runner; the product ships nothing for it. Any failure marks the evidence
// unavailable and the matrix continues: capture is evidence, never a gate.

/// Host time of the first delivered buffer, boxed so the real-time block can
/// capture it (`Atomic` is not copyable).
final class FirstBufferStamp: @unchecked Sendable {
    let hostTime = Atomic<UInt64>(0)
}

/// One tap → aggregate device → IOProc chain for one process, with a
/// preallocated ring the real-time callback writes into.
@available(macOS 14.2, *)
final class VocelloPlaybackCaptureSession {
    enum Failure: Error, CustomStringConvertible {
        case translatePID(OSStatus)
        case createTap(OSStatus)
        case readFormat(OSStatus)
        case createAggregate(OSStatus)
        case createIOProc(OSStatus)
        case start(OSStatus)

        var description: String {
            switch self {
            case .translatePID(let status): return "translate pid failed (\(status))"
            case .createTap(let status): return "AudioHardwareCreateProcessTap failed (\(status))"
            case .readFormat(let status): return "kAudioTapPropertyFormat failed (\(status))"
            case .createAggregate(let status): return "AudioHardwareCreateAggregateDevice failed (\(status))"
            case .createIOProc(let status): return "AudioDeviceCreateIOProcIDWithBlock failed (\(status))"
            case .start(let status): return "AudioDeviceStart failed (\(status))"
            }
        }
    }

    let pid: pid_t
    let format: AudioStreamBasicDescription
    let ring: VocelloPlaybackCaptureRing
    private let firstHostTime = FirstBufferStamp()
    private var tapID: AudioObjectID = 0
    private var aggregateID: AudioObjectID = 0
    private var ioProcID: AudioDeviceIOProcID?
    private var stopped = false

    /// Starts capturing immediately. `ringSeconds` bounds memory (mono float).
    init(pid: pid_t, ringSeconds: Double = 180) throws {
        self.pid = pid
        let processObject = try Self.processObject(for: pid)
        let description = CATapDescription(monoMixdownOfProcesses: [processObject])
        description.uuid = UUID()
        description.muteBehavior = .mutedWhenTapped
        description.isPrivate = true
        description.name = "Vocello benchmark capture"

        var tap: AudioObjectID = 0
        let tapStatus = AudioHardwareCreateProcessTap(description, &tap)
        guard tapStatus == noErr, tap != 0 else { throw Failure.createTap(tapStatus) }
        tapID = tap

        var formatAddress = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var streamFormat = AudioStreamBasicDescription()
        var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        let formatStatus = AudioObjectGetPropertyData(tap, &formatAddress, 0, nil, &formatSize, &streamFormat)
        guard formatStatus == noErr, streamFormat.mSampleRate > 0 else {
            AudioHardwareDestroyProcessTap(tap)
            throw Failure.readFormat(formatStatus)
        }
        format = streamFormat
        ring = VocelloPlaybackCaptureRing(capacity: Int(streamFormat.mSampleRate * ringSeconds))

        let aggregateDescription: [String: Any] = [
            kAudioAggregateDeviceNameKey: "Vocello benchmark capture",
            kAudioAggregateDeviceUIDKey: "com.qwenvoice.app.uitests.capture.\(UUID().uuidString)",
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapUIDKey: description.uuid.uuidString,
                kAudioSubTapDriftCompensationKey: true,
            ]],
        ]
        var aggregate: AudioObjectID = 0
        let aggregateStatus = AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregate)
        guard aggregateStatus == noErr, aggregate != 0 else {
            AudioHardwareDestroyProcessTap(tap)
            throw Failure.createAggregate(aggregateStatus)
        }
        aggregateID = aggregate

        let ring = self.ring
        let firstHostTime = self.firstHostTime
        // (a class, so the real-time block can capture it; `Atomic` itself cannot be copied)
        let channels = Int(max(1, streamFormat.mChannelsPerFrame))
        let interleaved = (streamFormat.mFormatFlags & kAudioFormatFlagIsNonInterleaved) == 0
        var procID: AudioDeviceIOProcID?
        let procStatus = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregate, nil) { _, inputData, inputTime, _, _ in
            // Real-time thread: copy the first channel into the ring, stamp the
            // first buffer's host time; no allocation, lock or actor hop here.
            _ = firstHostTime.hostTime.compareExchange(
                expected: 0, desired: inputTime.pointee.mHostTime, ordering: .relaxed
            )
            let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inputData))
            guard let first = buffers.first, let data = first.mData else { return }
            let floats = data.assumingMemoryBound(to: Float.self)
            let frames = Int(first.mDataByteSize) / (MemoryLayout<Float>.size * (interleaved ? channels : 1))
            if interleaved && channels > 1 {
                // Mono mixdown was requested; if the HAL still hands an interleaved
                // stereo buffer, take the left channel sample by sample.
                for frame in 0 ..< frames {
                    var sample = floats[frame * channels]
                    ring.write(&sample, count: 1)
                }
            } else {
                ring.write(floats, count: frames)
            }
        }
        guard procStatus == noErr, let procID else {
            AudioHardwareDestroyAggregateDevice(aggregate)
            AudioHardwareDestroyProcessTap(tap)
            throw Failure.createIOProc(procStatus)
        }
        ioProcID = procID
        let startStatus = AudioDeviceStart(aggregate, procID)
        guard startStatus == noErr else {
            AudioDeviceDestroyIOProcID(aggregate, procID)
            AudioHardwareDestroyAggregateDevice(aggregate)
            AudioHardwareDestroyProcessTap(tap)
            throw Failure.start(startStatus)
        }
    }

    deinit {
        stopIfNeeded()
    }

    /// Host time of the first delivered buffer, or nil when nothing arrived yet.
    var firstBufferHostTime: UInt64? {
        let value = firstHostTime.hostTime.load(ordering: .relaxed)
        return value == 0 ? nil : value
    }

    /// Stops the device and tears the chain down (destroying the tap restores
    /// the process's audible output), then returns every captured sample.
    @discardableResult
    func stop() -> [Float] {
        stopIfNeeded()
        return ring.drain()
    }

    private func stopIfNeeded() {
        guard !stopped else { return }
        stopped = true
        if let ioProcID {
            AudioDeviceStop(aggregateID, ioProcID)
            AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
        }
        if aggregateID != 0 {
            AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        if tapID != 0 {
            AudioHardwareDestroyProcessTap(tapID)
        }
        ioProcID = nil
        aggregateID = 0
        tapID = 0
    }

    static func processObject(for pid: pid_t) throws -> AudioObjectID {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyTranslatePIDToProcessObject,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var processID = pid
        var objectID: AudioObjectID = 0
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        let status = withUnsafePointer(to: &processID) { pointer in
            AudioObjectGetPropertyData(
                AudioObjectID(kAudioObjectSystemObject), &address,
                UInt32(MemoryLayout<pid_t>.size), pointer, &size, &objectID
            )
        }
        guard status == noErr, objectID != 0 else { throw Failure.translatePID(status) }
        return objectID
    }
}

/// Drives one capture per benchmark take and writes the per-take WAV and
/// sidecar under the lane's `playback-capture` directory. Never fails a test.
@MainActor
final class VocelloPlaybackCaptureCoordinator {
    static let environmentKey = "QVOICE_MAC_BENCH_CAPTURE_DIR"
    static let appBundleIdentifier = "com.qwenvoice.app"

    let directory: URL
    let runID: String
    private(set) var unavailableReason: String?
    private var session: VocelloPlaybackCaptureSession?
    private var sidecar: VocelloPlaybackCaptureSidecar?
    private var clock = VocelloPlaybackCaptureClock()
    /// Samples drained from the ring while a take is still open (the quiet-tail
    /// condition reads them); `endTake` appends whatever remains.
    private var collected: [Float] = []

    /// nil when the lane did not arm a capture directory.
    init?(environment: [String: String] = ProcessInfo.processInfo.environment, runID: String) {
        guard let raw = environment[Self.environmentKey], !raw.isEmpty else { return nil }
        directory = URL(fileURLWithPath: raw, isDirectory: true)
        self.runID = runID
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            unavailableReason = "capture directory not writable: \(error.localizedDescription)"
        }
        if #unavailable(macOS 14.2) {
            unavailableReason = "process taps need macOS 14.2"
        }
        writeRunManifest()
    }

    /// Starts tapping the app under test for the take. Any failure records the
    /// reason and leaves the take without capture evidence.
    func beginTake(index: Int, cell: String, warmState: String) {
        endTake(playbackEnded: false, status: "aborted", reason: "a new take began before the previous capture stopped")
        var record = VocelloPlaybackCaptureSidecar(
            benchRunID: runID, takeIndex: index, cell: cell, warmState: warmState, pid: 0
        )
        clock = VocelloPlaybackCaptureClock()
        collected = []
        guard unavailableReason == nil else {
            record.status = "unavailable"
            record.reason = unavailableReason
            sidecar = record
            return
        }
        guard let pid = Self.appProcessIdentifier() else {
            record.status = "unavailable"
            record.reason = "app process not found"
            sidecar = record
            return
        }
        record.pid = Int(pid)
        guard #available(macOS 14.2, *) else {
            record.status = "unavailable"
            sidecar = record
            return
        }
        do {
            let live = try VocelloPlaybackCaptureSession(pid: pid)
            record.sampleRate = live.format.mSampleRate
            record.channels = Int(live.format.mChannelsPerFrame)
            record.captureStartEpochMS = VocelloPlaybackCaptureClock.nowEpochMS
            record.status = "captured"
            session = live
        } catch {
            record.status = "unavailable"
            record.reason = String(describing: error)
        }
        sidecar = record
    }

    /// Call immediately before the Generate click.
    func markSubmit() {
        sidecar?.submitClickEpochMS = VocelloPlaybackCaptureClock.nowEpochMS
    }

    /// True when no tap is live for the current take (nothing to wait for).
    var isIdle: Bool {
        session == nil
    }

    /// Condition for the post-playback wait: the last `seconds` of captured
    /// audio stayed below `threshold`. Drains the ring as it looks, so the
    /// playback tail after the player reports "play" is still recorded.
    func capturedAudioIsQuiet(forLast seconds: Double, threshold: Float = 0.002) -> Bool {
        guard let live = session else { return true }
        collected.append(contentsOf: live.ring.drain())
        let window = Int(live.format.mSampleRate * seconds)
        guard window > 0, collected.count >= window else { return false }
        return collected.suffix(window).allSatisfy { abs($0) < threshold }
    }

    /// Stops the tap and writes the take's files. `playbackEnded` records
    /// whether the runner observed the player stop before the tail.
    func endTake(playbackEnded: Bool, status: String? = nil, reason: String? = nil) {
        guard var record = sidecar else { return }
        sidecar = nil
        if playbackEnded {
            record.playbackEndedEpochMS = VocelloPlaybackCaptureClock.nowEpochMS
        }
        var samples: [Float] = []
        if let live = session {
            samples = collected + live.stop()
            collected = []
            record.frames = samples.count
            record.droppedSamples = live.ring.droppedCount
            if let host = live.firstBufferHostTime {
                record.firstBufferEpochMS = clock.epochMS(forHostTime: host)
            }
            session = nil
        }
        record.stopEpochMS = VocelloPlaybackCaptureClock.nowEpochMS
        if let status {
            record.status = status
        }
        if let reason {
            record.reason = reason
        }
        let base = VocelloPlaybackCaptureSidecar.baseName(takeIndex: record.takeIndex, cell: record.cell)
        do {
            if !samples.isEmpty, record.status == "captured" {
                try VocelloPlaybackCaptureWAV.write(
                    samples: samples, sampleRate: record.sampleRate,
                    to: directory.appendingPathComponent("\(base).wav")
                )
            } else if record.status == "captured" {
                record.status = "silent"
                record.reason = "the tap delivered no buffers"
            }
            try record.encoded().write(to: directory.appendingPathComponent("\(base).json"), options: .atomic)
        } catch {
            // The lane keeps running; the analysis reports the take as unavailable.
        }
    }

    /// Teardown safety: stop any live tap so the app's audible output returns.
    func abort() {
        endTake(playbackEnded: false, status: "aborted", reason: "runner teardown")
    }

    private func writeRunManifest() {
        let payload: [String: Any] = [
            "schemaVersion": 1,
            "runID": runID,
            "hostOS": ProcessInfo.processInfo.operatingSystemVersionString,
            "muteBehavior": "mutedWhenTapped",
            "unavailableReason": unavailableReason as Any,
            "createdAt": ISO8601DateFormatter().string(from: Date()),
        ]
        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys, .prettyPrinted]) {
            try? data.write(to: directory.appendingPathComponent("capture-run.json"), options: .atomic)
        }
    }

    private static func appProcessIdentifier() -> pid_t? {
        NSRunningApplication.runningApplications(withBundleIdentifier: appBundleIdentifier)
            .filter { !$0.isTerminated }
            .max { $0.launchDate ?? .distantPast < $1.launchDate ?? .distantPast }?
            .processIdentifier
    }
}
