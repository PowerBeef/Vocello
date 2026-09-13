import Darwin
import Foundation
import Synchronization

// Played-audio capture support (PC-01): the pure pieces the macOS benchmark
// runner needs to record what the app rendered during a take. The Core Audio
// tap itself lives in the macOS-only test target; this file compiles into every
// UI test bundle and into VocelloCoreTests, where it is unit-tested.

/// Single-producer, single-consumer ring of Float32 samples. The real-time
/// IOProc writes, the test thread drains once the take is over. Writes never
/// allocate or lock; an overflow drops the newest samples and counts them.
public final class VocelloPlaybackCaptureRing: @unchecked Sendable {
    public let capacity: Int
    private let storage: UnsafeMutableBufferPointer<Float>
    private let written = Atomic<Int>(0)
    private let consumed = Atomic<Int>(0)
    private let droppedSamples = Atomic<Int>(0)

    public init(capacity: Int) {
        self.capacity = max(1, capacity)
        storage = .allocate(capacity: self.capacity)
        storage.initialize(repeating: 0)
    }

    deinit {
        storage.deallocate()
    }

    /// Real-time safe append; returns the number of samples stored.
    @discardableResult
    public func write(_ source: UnsafePointer<Float>, count: Int) -> Int {
        guard count > 0 else { return 0 }
        let head = written.load(ordering: .relaxed)
        let tail = consumed.load(ordering: .acquiring)
        let free = capacity - (head - tail)
        let stored = min(count, free)
        if stored < count {
            droppedSamples.wrappingAdd(count - stored, ordering: .relaxed)
        }
        guard stored > 0 else { return 0 }
        let offset = head % capacity
        let firstRun = min(stored, capacity - offset)
        (storage.baseAddress! + offset).update(from: source, count: firstRun)
        if stored > firstRun {
            storage.baseAddress!.update(from: source + firstRun, count: stored - firstRun)
        }
        written.store(head + stored, ordering: .releasing)
        return stored
    }

    @discardableResult
    public func write(_ samples: [Float]) -> Int {
        samples.withUnsafeBufferPointer { buffer in
            guard let base = buffer.baseAddress else { return 0 }
            return write(base, count: buffer.count)
        }
    }

    public var availableCount: Int {
        written.load(ordering: .acquiring) - consumed.load(ordering: .relaxed)
    }

    public var droppedCount: Int {
        droppedSamples.load(ordering: .relaxed)
    }

    /// Consumer side: everything written so far, in order.
    public func drain() -> [Float] {
        let tail = consumed.load(ordering: .relaxed)
        let head = written.load(ordering: .acquiring)
        let count = head - tail
        guard count > 0 else { return [] }
        var output = [Float](repeating: 0, count: count)
        output.withUnsafeMutableBufferPointer { destination in
            let offset = tail % capacity
            let firstRun = min(count, capacity - offset)
            destination.baseAddress!.update(from: storage.baseAddress! + offset, count: firstRun)
            if count > firstRun {
                (destination.baseAddress! + firstRun).update(from: storage.baseAddress!, count: count - firstRun)
            }
        }
        consumed.store(head, ordering: .releasing)
        return output
    }
}

/// Mono IEEE float32 RIFF/WAVE writer for the capture files.
public enum VocelloPlaybackCaptureWAV {
    public static func data(samples: [Float], sampleRate: Double) -> Data {
        var pcm = Data(count: samples.count * 4)
        pcm.withUnsafeMutableBytes { raw in
            guard let base = raw.baseAddress else { return }
            for (index, sample) in samples.enumerated() {
                base.storeBytes(of: sample.bitPattern.littleEndian, toByteOffset: index * 4, as: UInt32.self)
            }
        }
        let rate = UInt32(sampleRate.rounded())
        var header = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { header.append(contentsOf: $0) }
        }
        header.append(contentsOf: Array("RIFF".utf8))
        append(UInt32(36 + pcm.count))
        header.append(contentsOf: Array("WAVE".utf8))
        header.append(contentsOf: Array("fmt ".utf8))
        append(UInt32(16))
        append(UInt16(3))          // IEEE float
        append(UInt16(1))          // mono
        append(rate)
        append(rate * 4)
        append(UInt16(4))
        append(UInt16(32))
        header.append(contentsOf: Array("data".utf8))
        append(UInt32(pcm.count))
        return header + pcm
    }

    public static func write(samples: [Float], sampleRate: Double, to url: URL) throws {
        try data(samples: samples, sampleRate: sampleRate).write(to: url, options: .atomic)
    }
}

/// Per-take capture sidecar; every timestamp is the runner's own clock, in
/// epoch milliseconds, so first-audible arithmetic never crosses processes.
public struct VocelloPlaybackCaptureSidecar: Codable, Equatable, Sendable {
    public var benchRunID: String
    public var takeIndex: Int
    public var cell: String
    public var warmState: String
    public var pid: Int
    public var sampleRate: Double
    public var channels: Int
    public var frames: Int
    public var droppedSamples: Int
    public var submitClickEpochMS: Double?
    public var captureStartEpochMS: Double?
    public var firstBufferEpochMS: Double?
    public var playbackEndedEpochMS: Double?
    public var stopEpochMS: Double?
    /// captured | silent | unavailable | aborted (the analysis may refine captured).
    public var status: String
    public var reason: String?

    public init(
        benchRunID: String, takeIndex: Int, cell: String, warmState: String, pid: Int,
        sampleRate: Double = 0, channels: Int = 0, frames: Int = 0, droppedSamples: Int = 0,
        submitClickEpochMS: Double? = nil, captureStartEpochMS: Double? = nil,
        firstBufferEpochMS: Double? = nil, playbackEndedEpochMS: Double? = nil,
        stopEpochMS: Double? = nil, status: String = "aborted", reason: String? = nil
    ) {
        self.benchRunID = benchRunID
        self.takeIndex = takeIndex
        self.cell = cell
        self.warmState = warmState
        self.pid = pid
        self.sampleRate = sampleRate
        self.channels = channels
        self.frames = frames
        self.droppedSamples = droppedSamples
        self.submitClickEpochMS = submitClickEpochMS
        self.captureStartEpochMS = captureStartEpochMS
        self.firstBufferEpochMS = firstBufferEpochMS
        self.playbackEndedEpochMS = playbackEndedEpochMS
        self.stopEpochMS = stopEpochMS
        self.status = status
        self.reason = reason
    }

    /// `take-NN-<cell>` with the cell's `/` and `#` made filesystem-safe; the
    /// Python side joins on the sidecar's fields, not on the name.
    public static func baseName(takeIndex: Int, cell: String) -> String {
        let safe = cell.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "#", with: "-")
        return String(format: "take-%02d-%@", takeIndex, safe)
    }

    public func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    public static func decode(_ data: Data) throws -> VocelloPlaybackCaptureSidecar {
        try JSONDecoder().decode(VocelloPlaybackCaptureSidecar.self, from: data)
    }
}

/// Maps Core Audio host times (mach absolute time) onto the runner's epoch
/// clock using one reference pair taken at construction.
public struct VocelloPlaybackCaptureClock: Sendable {
    public let referenceEpochMS: Double
    public let referenceHostTime: UInt64
    public let nanosecondsPerHostTick: Double

    public init(
        referenceEpochMS: Double = Date().timeIntervalSince1970 * 1000,
        referenceHostTime: UInt64 = mach_absolute_time()
    ) {
        self.referenceEpochMS = referenceEpochMS
        self.referenceHostTime = referenceHostTime
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        nanosecondsPerHostTick = info.denom == 0 ? 1 : Double(info.numer) / Double(info.denom)
    }

    public static var nowEpochMS: Double {
        Date().timeIntervalSince1970 * 1000
    }

    public func epochMS(forHostTime hostTime: UInt64) -> Double {
        let delta = Double(Int64(bitPattern: hostTime &- referenceHostTime)) * nanosecondsPerHostTick
        return referenceEpochMS + delta / 1_000_000
    }
}
