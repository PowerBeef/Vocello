import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

final class LongFormAssemblyTests: XCTestCase {
    @concurrent func testOneSegmentPublishesReadableTrimmedAtomicWAVAndFrameMap() async throws {
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

    @concurrent func testTenSegmentsUseBoundaryPausesAndContiguousFrameMap() async throws {
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

    @concurrent func testStepDiscontinuityRecordsBoundaryJumpAdvisoryWarning() async throws {
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

    /// CORE-12: a quiet segment with a near-ceiling peak is boosted only up to
    /// the limiter's ceiling, never clipped at full scale; a quiet segment
    /// without such a peak still gets the full loudness gain.
    @concurrent func testLoudnessGainNeverPushesAPeakPastTheCeiling() async throws {
        let fixture = try Fixture()
        defer { fixture.cleanup() }
        let peak: Int16 = 31_000
        var peaky = (0..<2_000).map { frame -> Int16 in frame.isMultiple(of: 2) ? 1_000 : -1_000 }
        for index in stride(from: 100, to: 2_000, by: 400) {
            peaky[index] = peak
            peaky[index + 1] = -peak
        }
        let peakyURL = fixture.directory.appendingPathComponent("peaky.wav")
        try AtomicPCM16WAVWriter.write(
            pcmSamples: peaky,
            sampleRate: fixture.configuration.sampleRate,
            outputURL: peakyURL
        )
        let quietURL = try fixture.makeAudioFile(
            name: "quiet",
            audibleFrames: 2_000,
            edgeSilence: 0,
            amplitude: 1_000
        )
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: [
                LongFormAssemblySegmentSource(
                    segmentID: "peaky",
                    audioURL: peakyURL,
                    boundary: .sentence,
                    intendedPauseMilliseconds: 0
                ),
                LongFormAssemblySegmentSource(
                    segmentID: "quiet",
                    audioURL: quietURL,
                    boundary: .endOfText,
                    intendedPauseMilliseconds: 0
                ),
            ],
            outputURL: output,
            configuration: fixture.configuration
        )

        let ceiling = Double(PCM16StreamLimiter.ceiling) * Double(Int16.max)
        let peakyGain = evidence.segments[0].appliedGain
        XCTAssertGreaterThan(peakyGain, 1, "the quiet body still gets a boost")
        XCTAssertLessThan(peakyGain, fixture.configuration.maximumGain)
        XCTAssertLessThanOrEqual(Double(peak) * peakyGain, ceiling + 0.5)
        XCTAssertEqual(evidence.segments[1].appliedGain, fixture.configuration.maximumGain)

        let file = try AVAudioFile(forReading: output, commonFormat: .pcmFormatInt16, interleaved: false)
        let buffer = try XCTUnwrap(
            AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length))
        )
        try file.read(into: buffer)
        let samples = unsafe try XCTUnwrap(buffer.int16ChannelData?[0])
        let maximum = (0..<Int(buffer.frameLength)).map { unsafe abs(Int(samples[$0])) }.max() ?? 0
        XCTAssertLessThanOrEqual(Double(maximum), ceiling + 0.5)
        XCTAssertLessThan(maximum, Int(Int16.max), "no sample reaches the 16-bit clamp")
    }

    @concurrent func testSmoothJoinRecordsNoAdvisoryAndOldEvidenceDecodesWithoutTheField() async throws {
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

    @concurrent func testDefaultPauseComesFromPlannerBoundarySemantics() async throws {
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

    @concurrent func testHundredSegmentsRetainFixedWorkingSetProxy() async throws {
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

    @concurrent func testGainIsBoundedAndFadesAreRestrictedToVerifiedNonSpeech() async throws {
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

    @concurrent func testCancellationLeavesNoPartialOrStagingOutput() async throws {
        let fixture = try Fixture(blockFrames: 64)
        defer { fixture.cleanup() }
        let segments = try (1...100).map {
            try fixture.makeSegment(index: $0, audibleFrames: 8_000, edgeSilence: 100)
        }
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let configuration = fixture.configuration
        let task = Task.detached { @concurrent @Sendable in
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

    @concurrent func testSilentSegmentFailsClosedWithoutPublishing() async throws {
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

    // MARK: - The watermark's frame grid (RF-44)

    func testTheShippingConfigurationKeepsSegmentsOnTheMarkFrame() {
        XCTAssertEqual(LongFormAssemblyConfiguration().markFrameSamples, 320)
        XCTAssertEqual(LongFormAssemblyConfiguration.currentAlgorithmVersion, 3)
    }

    func testAlignedStartTrimsLessByUnderOneFrameAndPadsOnlyWhenItMust() {
        // At the start of the output the trim rounds down to whole frames.
        var aligned = BoundedLongFormAssembler.gridAlignedStart(candidate: 2_277, position: 0, frame: 320)
        XCTAssertEqual(aligned.contentStart, 2_240)
        XCTAssertEqual(aligned.paddingFrames, 0)
        // Elsewhere the kept start is congruent to the output position.
        aligned = BoundedLongFormAssembler.gridAlignedStart(candidate: 1_986, position: 1_060_192, frame: 320)
        XCTAssertEqual(aligned.contentStart, 1_952)
        XCTAssertEqual((1_060_192 - aligned.contentStart) % 320, 0)
        XCTAssertEqual(aligned.paddingFrames, 0)
        // Too little leading non-speech: the trim is unchanged and silence makes up the rest.
        aligned = BoundedLongFormAssembler.gridAlignedStart(candidate: 10, position: 1_000, frame: 320)
        XCTAssertEqual(aligned.contentStart, 10)
        XCTAssertEqual(aligned.paddingFrames, 290)
        XCTAssertEqual((1_000 + Int64(aligned.paddingFrames) - aligned.contentStart) % 320, 0)
        // A frame of one sample is no constraint.
        aligned = BoundedLongFormAssembler.gridAlignedStart(candidate: 777, position: 12_345, frame: 1)
        XCTAssertEqual(aligned.contentStart, 777)
        XCTAssertEqual(aligned.paddingFrames, 0)
        for candidate in Int64(0)...700 {
            for position in stride(from: Int64(0), through: 2_000, by: 37) {
                let result = BoundedLongFormAssembler.gridAlignedStart(
                    candidate: candidate, position: position, frame: 320
                )
                XCTAssertLessThanOrEqual(result.contentStart, candidate)
                XCTAssertGreaterThanOrEqual(result.contentStart, 0)
                XCTAssertGreaterThan(result.contentStart, candidate - 320)
                XCTAssertTrue((0..<320).contains(result.paddingFrames))
                XCTAssertEqual(
                    (position + Int64(result.paddingFrames) - result.contentStart) % 320, 0,
                    "candidate \(candidate) at \(position)"
                )
            }
        }
    }

    @concurrent func testEverySegmentLandsOnTheMarkFrameWithItsPauseUnchanged() async throws {
        let fixture = try Fixture(markFrameSamples: 320)
        defer { fixture.cleanup() }
        // Leading silences like the ones real takes carry, none a multiple of the frame.
        let silences = [2_277, 1_986, 1_961, 2_196, 701]
        let segments = try silences.enumerated().map { index, silence in
            try fixture.makeSegment(index: index + 1, audibleFrames: 5_000 + 33 * index, edgeSilence: silence)
        }
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: segments,
            outputURL: output,
            configuration: fixture.configuration
        )

        XCTAssertEqual(evidence.algorithmVersion, 3)
        for (index, map) in evidence.segments.enumerated() {
            // A sample marked at source frame f sits at output frame f + shift.
            let shift = map.contentOutputRange.lowerBound - map.trimmedLeadingFrames
            XCTAssertEqual(shift % 320, 0, "segment \(index + 1) is off the mark's grid")
            XCTAssertLessThanOrEqual(map.trimmedLeadingFrames, Int64(silences[index]))
            XCTAssertGreaterThan(map.trimmedLeadingFrames, Int64(silences[index]) - 320)
            // The trailing edge is trimmed as before, and no audible frame is lost.
            XCTAssertEqual(map.trimmedTrailingFrames, Int64(silences[index]))
            if index < evidence.segments.count - 1 {
                XCTAssertEqual(map.insertedPauseOutputRange.count, 480, "the pause keeps its length")
            }
        }
        XCTAssertEqual(try AVAudioFile(forReading: output).length, evidence.outputFrameCount)

        // Ground truth from the published samples, not from the evidence: each segment's first
        // audible sample was marked at source frame `silences[index]`, and must sit a whole
        // number of frames from there, at full level (the fade covers non-speech only).
        let published = try fixture.samples(of: output)
        let threshold = Int(fixture.configuration.silenceThreshold)
        for (index, map) in evidence.segments.enumerated() {
            let lower = Int(map.contentOutputRange.lowerBound)
            let upper = Int(map.contentOutputRange.upperBound)
            let firstAudible = try XCTUnwrap(
                (lower..<upper).first { abs(Int(published[$0])) > threshold },
                "segment \(index + 1) has no audible sample in its range"
            )
            XCTAssertEqual((firstAudible - silences[index]) % 320, 0, "segment \(index + 1)")
            XCTAssertEqual(
                Int(published[firstAudible]), Int((3_000 * map.appliedGain).rounded()),
                "segment \(index + 1) starts attenuated"
            )
            XCTAssertEqual(
                (lower..<firstAudible).filter { abs(Int(published[$0])) > threshold }.count, 0
            )
        }
    }

    @concurrent func testASegmentWithAlmostNoLeadingSilenceIsPaddedOntoTheMarkFrame() async throws {
        let fixture = try Fixture(markFrameSamples: 320)
        defer { fixture.cleanup() }
        let first = try fixture.makeSegment(index: 1, audibleFrames: 5_000, edgeSilence: 701)
        let second = try fixture.makeSegment(index: 2, audibleFrames: 5_000, edgeSilence: 7)
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: [first, second],
            outputURL: output,
            configuration: fixture.configuration
        )
        let published = try fixture.samples(of: output)
        let secondStart = Int(evidence.segments[1].contentOutputRange.lowerBound)
        // The second segment's first sample is audible (its 7 silent frames were trimmed), and it
        // was marked at source frame 7.
        XCTAssertGreaterThan(abs(Int(published[secondStart])), Int(fixture.configuration.silenceThreshold))
        XCTAssertEqual((secondStart - 7) % 320, 0)
        let pauseRange = evidence.segments[0].insertedPauseOutputRange
        XCTAssertTrue(
            published[Int(pauseRange.lowerBound)..<Int(pauseRange.upperBound)].allSatisfy { $0 == 0 }
        )

        let map = evidence.segments[1]
        XCTAssertEqual(map.trimmedLeadingFrames, 7, "no audible frame is trimmed to reach the grid")
        XCTAssertEqual((map.contentOutputRange.lowerBound - map.trimmedLeadingFrames) % 320, 0)
        let pause = evidence.segments[0].insertedPauseOutputRange.count
        XCTAssertGreaterThan(pause, 480)
        XCTAssertLessThan(pause, 480 + 320)
        XCTAssertEqual(
            evidence.segments[0].insertedPauseOutputRange.upperBound,
            map.contentOutputRange.lowerBound
        )
    }

    @concurrent func testAZeroPauseBoundaryIsPaddedOnlyWhenTheNextSegmentCannotReachTheFrame() async throws {
        let fixture = try Fixture(markFrameSamples: 320)
        defer { fixture.cleanup() }
        // A grapheme boundary plans no pause. The second segment has room to reach the grid by
        // trimming less; the third does not, and takes under one frame of silence instead.
        let segments = [
            try fixture.makeSegment(
                index: 1, audibleFrames: 5_000, edgeSilence: 701, boundary: .grapheme,
                intendedPauseMilliseconds: 0
            ),
            try fixture.makeSegment(
                index: 2, audibleFrames: 5_000, edgeSilence: 900, boundary: .grapheme,
                intendedPauseMilliseconds: 0
            ),
            try fixture.makeSegment(index: 3, audibleFrames: 5_000, edgeSilence: 7),
        ]
        let output = fixture.directory.appendingPathComponent("joined.wav")
        let evidence = try await BoundedLongFormAssembler.assemble(
            segments: segments,
            outputURL: output,
            configuration: fixture.configuration
        )

        XCTAssertEqual(evidence.segments[0].insertedPauseOutputRange.count, 0, "no silence is added")
        let padding = evidence.segments[1].insertedPauseOutputRange.count
        XCTAssertTrue((1..<320).contains(padding), "padding \(padding)")
        for (index, map) in evidence.segments.enumerated() {
            XCTAssertEqual(
                (map.contentOutputRange.lowerBound - map.trimmedLeadingFrames) % 320, 0,
                "segment \(index + 1)"
            )
        }
        // The boundary jump is measured against what really precedes the third segment: silence.
        let published = try fixture.samples(of: output)
        let thirdStart = Int(evidence.segments[2].contentOutputRange.lowerBound)
        XCTAssertEqual(published[thirdStart - 1], 0)
        XCTAssertGreaterThanOrEqual(evidence.maximumSegmentBoundaryJump, abs(Int(published[thirdStart])))
        XCTAssertEqual(published.count, Int(evidence.outputFrameCount))
    }

    @concurrent func testAFailureInTheNextSegmentAfterOneIsWrittenPublishesNothing() async throws {
        let fixture = try Fixture(markFrameSamples: 320)
        defer { fixture.cleanup() }
        let first = try fixture.makeSegment(index: 1, audibleFrames: 5_000, edgeSilence: 701)
        let silentURL = fixture.directory.appendingPathComponent("silent.wav")
        try AtomicPCM16WAVWriter.write(
            pcmSamples: [Int16](repeating: 0, count: 1_000),
            sampleRate: fixture.configuration.sampleRate,
            outputURL: silentURL
        )
        let output = fixture.directory.appendingPathComponent("joined.wav")
        do {
            _ = try await BoundedLongFormAssembler.assemble(
                segments: [
                    first,
                    LongFormAssemblySegmentSource(segmentID: "silent", audioURL: silentURL, boundary: .endOfText),
                ],
                outputURL: output,
                configuration: fixture.configuration
            )
            XCTFail("the silent second segment must fail the join")
        } catch {
            XCTAssertEqual(error as? LongFormAssemblyError, .emptyOrSilentSegment(segmentID: "silent"))
        }
        // The first segment was already written to staging when the look-ahead failed.
        XCTAssertEqual(try fixture.visibleFiles(named: "joined"), [])
    }

    @concurrent func testAMarkFrameBelowOneSampleIsRefused() async throws {
        let fixture = try Fixture(markFrameSamples: 0)
        defer { fixture.cleanup() }
        let source = try fixture.makeSegment(index: 1, audibleFrames: 800, edgeSilence: 200)
        do {
            _ = try await BoundedLongFormAssembler.assemble(
                segments: [source],
                outputURL: fixture.directory.appendingPathComponent("joined.wav"),
                configuration: fixture.configuration
            )
            XCTFail("a zero frame must be refused")
        } catch let error as LongFormAssemblyError {
            XCTAssertEqual(error, .invalidConfiguration("markFrameSamples"))
        }
    }
}

private final class Fixture {
    let directory: URL
    let configuration: LongFormAssemblyConfiguration

    /// `markFrameSamples` defaults to 1 here, which places no grid constraint:
    /// the tests that count trimmed and inserted frames stay exact. The grid
    /// tests pass the shipping frame.
    init(
        blockFrames: Int = 256,
        maximumTrimMillisecondsPerEdge: Int = 500,
        markFrameSamples: Int = 1
    ) throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-long-form-assembly-\(UUID().uuidString)", isDirectory: true)
        configuration = LongFormAssemblyConfiguration(
            blockFrames: blockFrames,
            maximumTrimMillisecondsPerEdge: maximumTrimMillisecondsPerEdge,
            markFrameSamples: markFrameSamples
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    func makeSegment(
        index: Int,
        audibleFrames: Int,
        edgeSilence: Int,
        amplitude: Int16 = 3_000,
        boundary: LongFormBoundaryKind? = nil,
        intendedPauseMilliseconds: Int = 20
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
            boundary: boundary ?? (index.isMultiple(of: 5) ? .paragraph : .safeClause),
            intendedPauseMilliseconds: intendedPauseMilliseconds
        )
    }

    /// The published file's samples, read back from disk.
    func samples(of url: URL) throws -> [Int16] {
        let file = try AVAudioFile(forReading: url, commonFormat: .pcmFormatInt16, interleaved: false)
        let buffer = try XCTUnwrap(
            AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length))
        )
        try file.read(into: buffer)
        let channel = unsafe try XCTUnwrap(buffer.int16ChannelData?[0])
        return (0..<Int(buffer.frameLength)).map { unsafe channel[$0] }
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
