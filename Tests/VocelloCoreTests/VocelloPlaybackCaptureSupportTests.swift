import Foundation
import XCTest

/// Pure logic behind the macOS benchmark lane's played-audio capture (PC-01).
final class VocelloPlaybackCaptureSupportTests: XCTestCase {
    func testRingKeepsOrderAcrossWrapAndCountsOverflow() {
        let ring = VocelloPlaybackCaptureRing(capacity: 8)
        XCTAssertEqual(ring.write([1, 2, 3, 4, 5]), 5)
        XCTAssertEqual(ring.drain(), [1, 2, 3, 4, 5])
        // The next write wraps around the end of the storage.
        XCTAssertEqual(ring.write([6, 7, 8, 9, 10, 11]), 6)
        XCTAssertEqual(ring.availableCount, 6)
        XCTAssertEqual(ring.drain(), [6, 7, 8, 9, 10, 11])
        XCTAssertEqual(ring.drain(), [])
        // Overflow keeps the oldest samples and counts the rest as dropped.
        XCTAssertEqual(ring.write(Array(repeating: 1, count: 10)), 8)
        XCTAssertEqual(ring.droppedCount, 2)
        XCTAssertEqual(ring.write([2]), 0)
        XCTAssertEqual(ring.droppedCount, 3)
        XCTAssertEqual(ring.drain().count, 8)
        XCTAssertEqual(ring.write([2]), 1)
    }

    func testFloatWAVHeaderDescribesMonoIEEEAtTheGivenRate() throws {
        let samples: [Float] = [0, 0.5, -0.5, 1]
        let data = VocelloPlaybackCaptureWAV.data(samples: samples, sampleRate: 48_000)
        XCTAssertEqual(data.count, 44 + samples.count * 4)
        XCTAssertEqual(String(decoding: data[0..<4], as: UTF8.self), "RIFF")
        XCTAssertEqual(String(decoding: data[8..<12], as: UTF8.self), "WAVE")
        XCTAssertEqual(String(decoding: data[12..<16], as: UTF8.self), "fmt ")
        func u16(_ offset: Int) -> UInt16 { data.subdata(in: offset..<offset + 2).withUnsafeBytes { $0.loadUnaligned(as: UInt16.self) } }
        func u32(_ offset: Int) -> UInt32 { data.subdata(in: offset..<offset + 4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) } }
        XCTAssertEqual(u32(16), 16)
        XCTAssertEqual(u16(20), 3, "IEEE float format tag")
        XCTAssertEqual(u16(22), 1, "mono")
        XCTAssertEqual(u32(24), 48_000)
        XCTAssertEqual(u32(28), 48_000 * 4)
        XCTAssertEqual(u16(32), 4)
        XCTAssertEqual(u16(34), 32)
        XCTAssertEqual(String(decoding: data[36..<40], as: UTF8.self), "data")
        XCTAssertEqual(u32(40), UInt32(samples.count * 4))
        let back = data.subdata(in: 44..<data.count).withUnsafeBytes { raw in
            (0..<samples.count).map { Float(bitPattern: UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: $0 * 4, as: UInt32.self))) }
        }
        XCTAssertEqual(back, samples)
    }

    func testSidecarRoundTripsAndNamesTakesSafely() throws {
        var sidecar = VocelloPlaybackCaptureSidecar(
            benchRunID: "macos-xcui-benchmark-20260913-000000-deadbeef", takeIndex: 4,
            cell: "clone/short/warm#0", warmState: "warm", pid: 4242
        )
        sidecar.sampleRate = 48_000
        sidecar.channels = 1
        sidecar.frames = 96_000
        sidecar.submitClickEpochMS = 1_000
        sidecar.captureStartEpochMS = 990
        sidecar.stopEpochMS = 5_000
        sidecar.status = "captured"
        let decoded = try VocelloPlaybackCaptureSidecar.decode(try sidecar.encoded())
        XCTAssertEqual(decoded, sidecar)
        XCTAssertEqual(VocelloPlaybackCaptureSidecar.baseName(takeIndex: 4, cell: "clone/short/warm#0"), "take-04-clone_short_warm-0")
        let json = String(decoding: try sidecar.encoded(), as: UTF8.self)
        XCTAssertTrue(json.contains("\"takeIndex\" : 4"))
        XCTAssertTrue(json.contains("\"cell\" : \"clone/short/warm#0\""))
    }

    func testClockMapsHostTimeForwardAndBackward() {
        let reference: UInt64 = 1_000_000_000_000
        let clock = VocelloPlaybackCaptureClock(referenceEpochMS: 10_000, referenceHostTime: reference)
        let tick = clock.nanosecondsPerHostTick
        let later = reference + UInt64(1_000_000_000 / tick)      // one second later
        XCTAssertEqual(clock.epochMS(forHostTime: later), 11_000, accuracy: 1)
        let earlier = reference - UInt64(500_000_000 / tick)      // half a second earlier
        XCTAssertEqual(clock.epochMS(forHostTime: earlier), 9_500, accuracy: 1)
        XCTAssertEqual(clock.epochMS(forHostTime: clock.referenceHostTime), 10_000, accuracy: 0.001)
    }
}
