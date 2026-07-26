import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

final class LongFormAssemblyTests: XCTestCase {
    func testOneSegmentPublishesReadableTrimmedAtomicWAVAndFrameMap() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let source = try fixture.makeSegment(index: 1, audibleFrames: 800, edgeSilence: 200)
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: [source],
            outputURL: output,
            configuration: fixture.configuration
        )

        XCTAssertTrue(evidence.outputReadable)
        XCTAssertEqual(evidence.segmentCount, 1)
        XCTAssertEqual(evidence.segments[0].trimmedLeadingFrames, 200)
        XCTAssertEqual(evidence.segments[0].trimmedTrailingFrames, 200)
        XCTAssertEqual(evidence.segments[0].contentOutputRange.count, 800)
        XCTAssertEqual(evidence.segments[0].insertedPauseOutputRange.count, 0)
        XCTAssertEqual(evidence.outputFrameCount, 800)
        XCTAssertEqual(try AVAudioFile(forReading: output).length, 800)
        XCTAssertEqual(evidence.outputDigest.count, 64)
        XCTAssertEqual(try fixture.visibleFiles(named: "joined"), ["joined.wav"])
    }

    func testTenSegmentsUseBoundaryPausesAndContiguousFrameMap() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let segments = try (1...10).map {
            try fixture.makeSegment(index: $0, audibleFrames: 500, edgeSilence: 64)
        }
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: segments,
            outputURL: fixture.directory.appendingPathComponent("joined.wav"),
            configuration: fixture.configuration
        )

        XCTAssertEqual(evidence.segmentCount, 10)
        XCTAssertEqual(
            evidence.workingSetFrameUpperBound,
            fixture.configuration.blockFrames * 3
        )
        for index in evidence.segments.indices {
            let map = evidence.segments[index]
            XCTAssertEqual(map.contentOutputRange.count, 500)
            if index < evidence.segments.count - 1 {
                XCTAssertEqual(map.insertedPauseOutputRange.count, 480)
                XCTAssertEqual(
                    map.insertedPauseOutputRange.upperBound,
                    evidence.segments[index + 1].contentOutputRange.lowerBound
                )
            } else {
                XCTAssertEqual(map.insertedPauseOutputRange.count, 0)
            }
        }
        XCTAssertEqual(evidence.outputFrameCount, 10 * 500 + 9 * 480)
        XCTAssertGreaterThan(evidence.maximumSegmentBoundaryJump, 0)
        XCTAssertLessThan(evidence.maximumSegmentBoundaryJump, 4_000)
    }

    func testStepDiscontinuityRecordsBoundaryJumpAdvisoryWarning() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        // Two loud square-wave segments joined with no pause: an even audible
        // frame count ends the first segment at -amplitude while the next
        // starts at +amplitude, so the join is a full-scale step.
        let sources = try [1, 2].map { index in
            LongFormAssemblySegmentSource(
                segmentID: "segment-\(index)",
                audioURL: try fixture.makeAudioFile(
                    name: "segment-\(index)",
                    audibleFrames: 2_000,
                    edgeSilence: 0,
                    amplitude: 20_000
                ),
                boundary: .safeClause,
                intendedPauseMilliseconds: 0
            )
        }
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: sources,
            outputURL: fixture.directory.appendingPathComponent("joined.wav"),
            configuration: fixture.configuration
        )

        XCTAssertGreaterThan(
            evidence.maximumSegmentBoundaryJump,
            LongFormAssemblyEvidence.advisoryMaximumSegmentBoundaryJump
        )
        XCTAssertTrue(evidence.exceedsAdvisoryBoundaryJump)
        XCTAssertEqual(
            evidence.advisoryWarnings,
            ["boundary_jump:\(evidence.maximumSegmentBoundaryJump)"]
        )

        // The derived typed gate mirrors the warn-first advisory contract and
        // carries the joined output digest plus the measured boundary jump.
        let gate = evidence.longFormContinuityGateResult()
        XCTAssertEqual(gate.gate, .longFormContinuity)
        XCTAssertEqual(gate.outcome, .warning)
        XCTAssertEqual(gate.evidenceDigest, evidence.outputDigest)
        XCTAssertEqual(
            gate.measurements.first { $0.key == .boundaryDiscontinuity }?.value,
            Double(evidence.maximumSegmentBoundaryJump)
        )
    }

    func testSmoothJoinRecordsNoAdvisoryAndOldEvidenceDecodesWithoutTheField() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let segments = try (1...2).map {
            try fixture.makeSegment(index: $0, audibleFrames: 500, edgeSilence: 64)
        }
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: segments,
            outputURL: fixture.directory.appendingPathComponent("joined.wav"),
            configuration: fixture.configuration
        )
        XCTAssertFalse(evidence.exceedsAdvisoryBoundaryJump)
        XCTAssertNil(evidence.advisoryWarnings)
        XCTAssertEqual(evidence.longFormContinuityGateResult().outcome, .pass)

        // Pre-advisory manifests carry no advisoryWarnings key; decoding them
        // must keep working.
        var payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: JSONEncoder().encode(evidence)) as? [String: Any]
        )
        payload.removeValue(forKey: "advisoryWarnings")
        let decoded = try JSONDecoder().decode(
            LongFormAssemblyEvidence.self,
            from: JSONSerialization.data(withJSONObject: payload)
        )
        XCTAssertNil(decoded.advisoryWarnings)
        XCTAssertEqual(decoded.maximumSegmentBoundaryJump, evidence.maximumSegmentBoundaryJump)
    }

    func testDefaultPauseComesFromPlannerBoundarySemantics() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let firstURL = try fixture.makeAudioFile(
            name: "paragraph",
            audibleFrames: 100,
            edgeSilence: 0
        )
        let secondURL = try fixture.makeAudioFile(
            name: "ending",
            audibleFrames: 100,
            edgeSilence: 0
        )
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: [
                LongFormAssemblySegmentSource(
                    segmentID: "paragraph",
                    lineage: LongFormRevisionLineage(
                        revision: 2,
                        parentPlanDigest: "parent-plan-digest",
                        replacesSegmentID: "paragraph-v1"
                    ),
                    audioURL: firstURL,
                    boundary: .paragraph
                ),
                LongFormAssemblySegmentSource(
                    segmentID: "ending",
                    audioURL: secondURL,
                    boundary: .endOfText
                ),
            ],
            outputURL: fixture.directory.appendingPathComponent("joined.wav"),
            configuration: fixture.configuration
        )

        XCTAssertEqual(
            evidence.segments[0].insertedPauseOutputRange.count,
            12_000
        )
        XCTAssertEqual(evidence.segments[0].lineage.revision, 2)
        XCTAssertEqual(evidence.segments[0].lineage.replacesSegmentID, "paragraph-v1")
        XCTAssertEqual(evidence.segments[1].insertedPauseOutputRange.count, 0)
    }

    func testHundredSegmentsRetainFixedWorkingSetProxy() async throws {
        let fixture = try Fixture(blockFrames: 128)
        defer { fixture.cleanup() }
        let segments = try (1...100).map {
            try fixture.makeSegment(index: $0, audibleFrames: 257, edgeSilence: 32)
        }
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: segments,
            outputURL: output,
            configuration: fixture.configuration
        )

        XCTAssertEqual(evidence.segmentCount, 100)
        XCTAssertEqual(evidence.workingSetFrameUpperBound, 384)
        XCTAssertEqual(evidence.outputFrameCount, 100 * 257 + 99 * 480)
        XCTAssertEqual(try AVAudioFile(forReading: output).length, evidence.outputFrameCount)
        XCTAssertTrue(evidence.segments.allSatisfy { $0.contentOutputRange.count == 257 })
    }

    func testGainIsBoundedAndFadesAreRestrictedToVerifiedNonSpeech() async throws {
        let fixture = try Fixture(maximumTrimMillisecondsPerEdge: 1)
        defer { fixture.cleanup() }
        let source = try fixture.makeSegment(
            index: 1,
            audibleFrames: 400,
            edgeSilence: 100,
            amplitude: 500
        )
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: [source],
            outputURL: fixture.directory.appendingPathComponent("joined.wav"),
            configuration: fixture.configuration
        )
        let map = evidence.segments[0]

        XCTAssertEqual(map.appliedGain, fixture.configuration.maximumGain, accuracy: 0.0001)
        XCTAssertGreaterThan(map.verifiedNonSpeechFadeInFrames, 0)
        XCTAssertGreaterThan(map.verifiedNonSpeechFadeOutFrames, 0)
        XCTAssertLessThanOrEqual(map.verifiedNonSpeechFadeInFrames, 240)
        XCTAssertLessThanOrEqual(map.verifiedNonSpeechFadeOutFrames, 240)
    }

    func testCancellationLeavesNoPartialOrStagingOutput() async throws {
        let fixture = try Fixture(blockFrames: 64)
        defer { fixture.cleanup() }
        let segments = try (1...100).map {
            try fixture.makeSegment(index: $0, audibleFrames: 8_000, edgeSilence: 100)
        }
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let configuration = fixture.configuration
        let task = Task.detached { @Sendable in
            try await BoundedLongFormAssembler.assemble(
                segments: segments,
                outputURL: output,
                configuration: configuration
            )
        }
        task.cancel()

        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
            // Expected.
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
        XCTAssertEqual(try fixture.visibleFiles(named: "joined"), [])
    }

    func testSilentSegmentFailsClosedWithoutPublishing() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let url = fixture.directory.appendingPathComponent("silent.wav")
        try AtomicPCM16WAVWriter.write(
            pcmSamples: [Int16](repeating: 0, count: 1_000),
            sampleRate: fixture.configuration.sampleRate,
            outputURL: url
        )
        let output = fixture.directory.appendingPathComponent("joined.wav")
        do {
            _ = try await BoundedLongFormAssembler.assemble(
                segments: [
                    LongFormAssemblySegmentSource(
                        segmentID: "silent",
                        audioURL: url,
                        boundary: .endOfText
                    ),
                ],
                outputURL: output,
                configuration: fixture.configuration
            )
            XCTFail("Expected silent segment rejection")
        } catch {
            XCTAssertEqual(error as? LongFormAssemblyError, .emptyOrSilentSegment(segmentID: "silent"))
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
    }
}

private final class Fixture {
    let directory: URL
    let configuration: LongFormAssemblyConfiguration

    init(
        blockFrames: Int = 256,
        maximumTrimMillisecondsPerEdge: Int = 500
    ) throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-long-form-assembly-\(UUID().uuidString)", isDirectory: true)
        configuration = LongFormAssemblyConfiguration(
            blockFrames: blockFrames,
            maximumTrimMillisecondsPerEdge: maximumTrimMillisecondsPerEdge
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    func makeSegment(
        index: Int,
        audibleFrames: Int,
        edgeSilence: Int,
        amplitude: Int16 = 3_000
    ) throws -> LongFormAssemblySegmentSource {
        let url = try makeAudioFile(
            name: "segment-\(index)",
            audibleFrames: audibleFrames,
            edgeSilence: edgeSilence,
            amplitude: amplitude
        )
        return LongFormAssemblySegmentSource(
            segmentID: "segment-\(index)",
            audioURL: url,
            boundary: index.isMultiple(of: 5) ? .paragraph : .safeClause,
            intendedPauseMilliseconds: 20
        )
    }

    func makeAudioFile(
        name: String,
        audibleFrames: Int,
        edgeSilence: Int,
        amplitude: Int16 = 3_000
    ) throws -> URL {
        let url = directory.appendingPathComponent("\(name).wav")
        let tone = (0..<audibleFrames).map { frame -> Int16 in
            frame.isMultiple(of: 2) ? amplitude : -amplitude
        }
        try AtomicPCM16WAVWriter.write(
            pcmSamples: [Int16](repeating: 0, count: edgeSilence)
                + tone
                + [Int16](repeating: 0, count: edgeSilence),
            sampleRate: configuration.sampleRate,
            outputURL: url
        )
        return url
    }

    func visibleFiles(named prefix: String) throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: directory.path)
            .filter { $0.contains(prefix) }
            .sorted()
    }

    func cleanup() {
        try? FileManager.default.removeItem(at: directory)
    }
}
