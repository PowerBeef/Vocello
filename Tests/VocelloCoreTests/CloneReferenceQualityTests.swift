import AVFoundation
import Foundation
@testable import QwenVoiceCore
import XCTest

/// RF-51 (G-08 to G-11): one check of a clone reference serves enrollment, the
/// saved-voice list, a one-off reference and the engine, reads the clip as the
/// user gave it, and refuses what cannot condition a take.
final class CloneReferenceQualityTests: XCTestCase {
    private typealias Quality = CloneReferenceQuality

    // MARK: - The rule

    func testDurationTiersAndTheirBoundaries() {
        func tokens(_ seconds: Double) -> [String] {
            Quality.warnings(durationSeconds: seconds, sourceSampleRate: 24_000, signal: nil)
        }
        XCTAssertEqual(tokens(9.99), [Quality.shortDurationToken])
        XCTAssertEqual(tokens(10), [])
        XCTAssertEqual(tokens(30), [])
        XCTAssertEqual(tokens(30.01), [Quality.longDurationToken])
        XCTAssertEqual(tokens(60), [Quality.longDurationToken])
        XCTAssertEqual(tokens(60.01), [Quality.excessiveDurationToken])
    }

    func testASourceBelowSixteenKilohertzIsNamedAndAnUnknownRateIsNot() {
        func tokens(_ rate: Double?) -> [String] {
            Quality.warnings(durationSeconds: 15, sourceSampleRate: rate, signal: nil)
        }
        XCTAssertEqual(tokens(8_000), [Quality.sourceRateLowToken])
        XCTAssertEqual(tokens(11_025), [Quality.sourceRateLowToken])
        XCTAssertEqual(tokens(16_000), [])
        XCTAssertEqual(tokens(48_000), [])
        XCTAssertEqual(tokens(nil), [])
    }

    func testSilenceBlocksAndIsNeverAlsoCalledClipped() {
        let silent = Quality.Signal(peak: 0.0004, rms: 0.0004, clippedRuns: 400, analyzedSeconds: 15)
        XCTAssertEqual(
            Quality.warnings(durationSeconds: 15, sourceSampleRate: 24_000, signal: silent),
            [Quality.nearSilenceToken])
        let quiet = Quality.Signal(peak: 0.02, rms: 0.003, clippedRuns: 0, analyzedSeconds: 15)
        XCTAssertEqual(Quality.warnings(durationSeconds: 15, sourceSampleRate: 24_000, signal: quiet), [])
    }

    func testClippingNeedsFlatTopsAtARateNotALoudPeak() {
        func tokens(runs: Int, seconds: Double, peak: Float = 1) -> [String] {
            Quality.warnings(
                durationSeconds: 15, sourceSampleRate: 24_000,
                signal: Quality.Signal(peak: peak, rms: 0.1, clippedRuns: runs, analyzedSeconds: seconds))
        }
        // A full-scale peak alone is a well-mastered clip, not a clipped one.
        XCTAssertEqual(tokens(runs: 0, seconds: 15), [])
        // The highest clean clip of the calibration set: 0.43 flat tops a second.
        XCTAssertEqual(tokens(runs: 6, seconds: 15), [])
        XCTAssertEqual(tokens(runs: 8, seconds: 15), [Quality.possibleClippingToken])
        // Overdriven and then turned down still reads as clipped.
        XCTAssertEqual(tokens(runs: 300, seconds: 15, peak: 0.3), [Quality.possibleClippingToken])
        // Two flat tops in a short clip are a rate above the threshold, not evidence.
        XCTAssertEqual(tokens(runs: 2, seconds: 2), [])
    }

    func testBlockingTokensComeFirstSoTheChipNamesWhatStopsTheClip() {
        let silent = Quality.Signal(peak: 0, rms: 0, clippedRuns: 0, analyzedSeconds: 4)
        XCTAssertEqual(
            Quality.warnings(durationSeconds: 4, sourceSampleRate: 8_000, signal: silent),
            [Quality.nearSilenceToken, Quality.shortDurationToken, Quality.sourceRateLowToken])
        let clipped = Quality.Signal(peak: 1, rms: 0.3, clippedRuns: 900, analyzedSeconds: 30)
        XCTAssertEqual(
            Quality.warnings(durationSeconds: 75, sourceSampleRate: 44_100, signal: clipped),
            [Quality.excessiveDurationToken, Quality.possibleClippingToken])
    }

    // MARK: - Meters

    func testAFlatTopSplitAcrossChunksIsOneRun() {
        var counter = Quality.FlatTopCounter(channelPeaks: [1], runLength: 3)
        counter.count(channel: 0, samples: [0.1, 1, 1])
        counter.count(channel: 0, samples: [1, 1, 0.1, 1, 1])
        counter.count(channel: 0, samples: [0.2, -1, -1, -1])
        // The first run spans two chunks; the pair is too short; the last one counts.
        XCTAssertEqual(counter.runs, 2)
    }

    func testAFlatTopIsADurationSoTheRuleMeansTheSameAtEveryRate() {
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 8_000), 3)
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 16_000), 3)
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 24_000), 3)
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 44_100), 6)
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 48_000), 6)
        XCTAssertEqual(Quality.clippedRunLength(sampleRate: 96_000), 12)
        var counter = Quality.FlatTopCounter(channelPeaks: [1], runLength: 6)
        counter.count(channel: 0, samples: [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1])
        XCTAssertEqual(counter.runs, 1)
    }

    func testASilentChannelHasNoPeakToFlattenAgainst() {
        var counter = Quality.FlatTopCounter(channelPeaks: [0, 0.5], runLength: 3)
        counter.count(channel: 0, samples: Array(repeating: 0, count: 64))
        counter.count(channel: 1, samples: [0.5, 0.5, 0.5, 0.1])
        counter.count(channel: 7, samples: [1, 1, 1])
        XCTAssertEqual(counter.runs, 1)
    }

    func testTheLevelIsOverEveryChannelAndThePeakIsPerChannel() {
        var meter = Quality.LevelMeter(channelCount: 2)
        meter.measure(channel: 0, samples: [0.5, -0.5])
        meter.measure(channel: 1, samples: [0, 0])
        XCTAssertEqual(meter.peaks, [0.5, 0])
        XCTAssertEqual(meter.peak, 0.5)
        XCTAssertEqual(meter.rms, Float((0.5 * 0.5 * 2 / 4).squareRoot()), accuracy: 1e-6)
    }

    // MARK: - Files

    func testACleanClipAtTheModelRateHasNoWarning() throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("clean.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 12, sampleRate: 24_000), sampleRate: 24_000, to: url)
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [])
        let signal = try Quality.signal(at: url)
        XCTAssertEqual(signal.analyzedSeconds, 12, accuracy: 0.01)
        XCTAssertFalse(signal.isLikelyClipped)
    }

    func testTelephoneAudioIsSeenInTheSourceEvenThoughPreparationResamplesIt() async throws {
        let root = try temporaryDirectory()
        let source = root.appendingPathComponent("phone.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 12, sampleRate: 8_000), sampleRate: 8_000, to: source)
        XCTAssertEqual(Quality.warnings(forReferenceAt: source), [Quality.sourceRateLowToken])
        XCTAssertEqual(Quality.warnings(forReferenceAt: source, depth: .header), [Quality.sourceRateLowToken])

        // The prepared 24 kHz file no longer shows it (the check that never fired);
        // the engine measures the source and still does.
        let prepared = try await NativeAudioPreparationService().normalizeAudio(
            AudioPreparationRequest(inputURL: source, outputURL: root.appendingPathComponent("prepared.wav")))
        XCTAssertEqual(Quality.warnings(forReferenceAt: prepared.normalizedURL), [])
        let cache = NativePreparedCloneConditioningCache(capacity: 2)
        let resolved = try await cache.resolve(
            modelID: "clone", reference: CloneReference(audioPath: source.path), sampleRate: 24_000,
            audioPreparationService: NativeAudioPreparationService(),
            normalizedCloneReferenceDirectory: root.appendingPathComponent("normalized"))
        XCTAssertEqual(resolved.referenceQualityWarnings, [Quality.sourceRateLowToken])
    }

    func testAnOverdrivenClipIsNamedAndTheSameClipTurnedDownStillIs() throws {
        let root = try temporaryDirectory()
        let clean = Self.voiceLike(seconds: 12, sampleRate: 24_000)
        // The fixture peaks near 0.25: twelve times that is far past full scale.
        let overdriven = clean.map { max(-1, min(1, $0 * 12)) }
        let loud = root.appendingPathComponent("loud.wav")
        try Self.writeWAV(overdriven, sampleRate: 24_000, to: loud)
        XCTAssertEqual(Quality.warnings(forReferenceAt: loud), [Quality.possibleClippingToken])
        let turnedDown = root.appendingPathComponent("turned-down.wav")
        try Self.writeWAV(overdriven.map { $0 * 0.3 }, sampleRate: 24_000, to: turnedDown)
        XCTAssertEqual(Quality.warnings(forReferenceAt: turnedDown), [Quality.possibleClippingToken])
        // A clean clip raised to full scale is loud, not clipped.
        let peak = clean.map(abs).max() ?? 1
        let normalized = root.appendingPathComponent("normalized.wav")
        try Self.writeWAV(clean.map { $0 / peak * 0.999 }, sampleRate: 24_000, to: normalized)
        XCTAssertEqual(Quality.warnings(forReferenceAt: normalized), [])
    }

    func testASilentClipBlocksOnlyWhenItsSignalIsRead() throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("silent.wav")
        try Self.writeWAV(Array(repeating: 0, count: 24_000 * 12), sampleRate: 24_000, to: url)
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [Quality.nearSilenceToken])
        XCTAssertEqual(Quality.warnings(forReferenceAt: url, depth: .header), [])
    }

    func testAFileThatIsNotAudioIsUnreadable() throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("notes.wav")
        try Data("not audio".utf8).write(to: url)
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [Quality.unreadableToken])
        XCTAssertEqual(Quality.warnings(forReferenceAt: url, depth: .header), [Quality.unreadableToken])
        XCTAssertEqual(
            Quality.warnings(forReferenceAt: root.appendingPathComponent("missing.wav")),
            [Quality.unreadableToken])
    }

    func testAFlatTopAcrossTheReadersChunkEdgeIsOneRunAndStereoIsReadPerChannel() throws {
        let root = try temporaryDirectory()
        // Left: quiet, with one flat top that straddles frame 32,768, the
        // reader's chunk size, and two more elsewhere. Right: silence.
        var left = [Float](repeating: 0.05, count: 24_000 * 3)
        for range in [32_766..<32_771, 40_000..<40_004, 50_000..<50_003] {
            for index in range { left[index] = 0.8 }
        }
        let url = root.appendingPathComponent("stereo.wav")
        try Self.writeWAV(channels: [left, [Float](repeating: 0, count: left.count)], sampleRate: 24_000, to: url)
        let signal = try Quality.signal(at: url)
        XCTAssertEqual(signal.clippedRuns, 3)
        XCTAssertEqual(signal.peak, 0.8, accuracy: 0.001)
        XCTAssertEqual(signal.analyzedSeconds, 3, accuracy: 0.01)
        // Three flat tops in three seconds is the rate of a clipped clip.
        XCTAssertTrue(signal.isLikelyClipped)
    }

    func testACompressedSourceIsMeasuredToItsEndAndACleanOneHasNoWarning() throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("clean.m4a")
        let samples = Self.voiceLike(seconds: 12, sampleRate: 44_100)
        try Self.write(channels: [samples], to: AVAudioFile(forWriting: url, settings: [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100.0,
            AVNumberOfChannelsKey: 1,
        ]))
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [])
        let signal = try Quality.signal(at: url)
        XCTAssertEqual(signal.analyzedSeconds, 12, accuracy: 0.25)
        XCTAssertGreaterThan(signal.rms, 0.01)
    }

    func testOnlyTheOpeningThirtySecondsAreAnalyzed() throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("long.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 45, sampleRate: 16_000), sampleRate: 16_000, to: url)
        XCTAssertEqual(try Quality.signal(at: url).analyzedSeconds, 30, accuracy: 0.01)
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [Quality.longDurationToken])
    }

    // MARK: - Enrollment and the list

    func testEnrollmentRunsTheFullCheckAndTheListReadsOnlyTheHeader() throws {
        let root = try temporaryDirectory()
        let silent = root.appendingPathComponent("silent.wav")
        try Self.writeWAV(Array(repeating: 0, count: 24_000 * 12), sampleRate: 24_000, to: silent)
        XCTAssertEqual(
            MLXTTSEngine.enrollmentReferenceQualityWarnings(forOriginalAt: silent.path),
            [Quality.nearSilenceToken])
        XCTAssertEqual(MLXTTSEngine.savedReferenceQualityWarnings(forAudioAt: silent.path), [])

        let phone = root.appendingPathComponent("phone.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 5, sampleRate: 8_000), sampleRate: 8_000, to: phone)
        let expected = [Quality.shortDurationToken, Quality.sourceRateLowToken]
        XCTAssertEqual(MLXTTSEngine.enrollmentReferenceQualityWarnings(forOriginalAt: phone.path), expected)
        XCTAssertEqual(MLXTTSEngine.savedReferenceQualityWarnings(forAudioAt: phone.path), expected)
    }

    /// The source is measured once per file state (path, size, modification
    /// time): a take after the first, a long-form segment or a batch line
    /// reads no audio for it again.
    func testTheEnginesCheckOfASourceIsKeptUntilTheFileChanges() async throws {
        let root = try temporaryDirectory()
        let url = root.appendingPathComponent("clip.wav")
        let frames = 24_000 * 12
        try Self.writeWAV(Self.voiceLike(seconds: 12, sampleRate: 24_000), sampleRate: 24_000, to: url)
        // A whole-second stamp, so setting it again reads back the same value.
        let stamp = Date(timeIntervalSince1970: 1_700_000_000)
        try FileManager.default.setAttributes([.modificationDate: stamp], ofItemAtPath: url.path)
        let cache = NativePreparedCloneConditioningCache(capacity: 2)
        let clean = await cache.sourceQualityWarnings(for: url)
        XCTAssertEqual(clean, [])

        // Same path, same size, same modification time, other samples: the
        // kept answer is returned, which only a kept answer can be.
        try FileManager.default.removeItem(at: url)
        try Self.writeWAV(Array(repeating: 0, count: frames), sampleRate: 24_000, to: url)
        try FileManager.default.setAttributes([.modificationDate: stamp], ofItemAtPath: url.path)
        let kept = await cache.sourceQualityWarnings(for: url)
        XCTAssertEqual(kept, [])
        XCTAssertEqual(Quality.warnings(forReferenceAt: url), [Quality.nearSilenceToken], "the file itself is silent now")

        // A file whose state changed is measured again.
        try FileManager.default.setAttributes(
            [.modificationDate: stamp.addingTimeInterval(5)], ofItemAtPath: url.path)
        let measuredAgain = await cache.sourceQualityWarnings(for: url)
        XCTAssertEqual(measuredAgain, [Quality.nearSilenceToken])
    }

    func testTheRefusalBeforeAModelLoadLeavesAnUnopenableClipToThePipeline() async throws {
        let root = try temporaryDirectory()
        let cache = NativePreparedCloneConditioningCache(capacity: 2)
        let silent = root.appendingPathComponent("silent.wav")
        try Self.writeWAV(Array(repeating: 0, count: 24_000 * 12), sampleRate: 24_000, to: silent)
        do {
            try await cache.requireUsableOneOffReferenceBeforeLoad(CloneReference(audioPath: silent.path))
            XCTFail("a silent one-off clip is refused before any model is loaded")
        } catch let rejection as CloneReferenceQuality.Rejection {
            XCTAssertEqual(rejection.tokens, [Quality.nearSilenceToken])
        }
        // A saved voice was accepted at enrollment.
        try await cache.requireUsableOneOffReferenceBeforeLoad(
            CloneReference(audioPath: silent.path, preparedVoiceID: "Voice"))
        // A missing or unsupported file keeps the pipeline's own, more exact error.
        try await cache.requireUsableOneOffReferenceBeforeLoad(
            CloneReference(audioPath: root.appendingPathComponent("missing.wav").path))
    }

    // MARK: - What blocks, and the wording

    func testUnreadableAndSilentReferencesBlockLikeTheDurationCap() {
        typealias Warning = PreparedVoiceQualityWarning
        XCTAssertEqual(Warning.hardBlockingTokens, [
            Quality.excessiveDurationToken, Quality.unreadableToken, Quality.nearSilenceToken,
        ])
        for advisory in [Quality.shortDurationToken, Quality.longDurationToken,
                         Quality.sourceRateLowToken, Quality.possibleClippingToken] {
            XCTAssertFalse(Warning.isHardBlocking([advisory]), advisory)
        }
        XCTAssertTrue(Warning.isHardBlocking([Quality.shortDurationToken, Quality.unreadableToken]))
        XCTAssertEqual(
            Warning.blockingTokens(in: [Quality.nearSilenceToken, Quality.shortDurationToken]),
            [Quality.nearSilenceToken])
    }

    func testEveryTokenHasWordingAndTheClosingLineFitsTheFinding() {
        typealias Warning = PreparedVoiceQualityWarning
        let all = [
            Quality.shortDurationToken, Quality.longDurationToken, Quality.excessiveDurationToken,
            Quality.unreadableToken, Quality.nearSilenceToken, Quality.sourceRateLowToken,
            Quality.possibleClippingToken,
        ]
        for token in all {
            XCTAssertNotNil(Warning.headline(for: token), token)
            XCTAssertNotNil(Warning.shortLabel(for: token), token)
        }
        XCTAssertEqual(Warning.summaryClosing(for: [Quality.excessiveDurationToken]), .shortenToMaximum)
        XCTAssertEqual(Warning.summaryClosing(for: [Quality.nearSilenceToken]), .chooseAnotherClip)
        XCTAssertEqual(
            Warning.summaryClosing(for: [Quality.excessiveDurationToken, Quality.nearSilenceToken]),
            .chooseAnotherClip)
        XCTAssertEqual(
            Warning.summaryClosing(for: [Quality.shortDurationToken, Quality.possibleClippingToken]),
            .outsideRecommendedLength)
        XCTAssertNil(Warning.summaryClosing(for: [Quality.sourceRateLowToken]))
        XCTAssertNil(Warning.summaryClosing(for: []))
        // Advice about the signal ends on its own headline, which states the effect.
        XCTAssertTrue(Warning.summary(for: [Quality.possibleClippingToken]).hasSuffix("distorted."))
        XCTAssertTrue(Warning.summary(for: [Quality.unreadableToken]).hasSuffix("Choose another clip to use for cloning."))

        XCTAssertTrue(Warning.concernsLengthOnly([]))
        XCTAssertTrue(Warning.concernsLengthOnly([Quality.shortDurationToken]))
        XCTAssertTrue(Warning.concernsLengthOnly([Quality.excessiveDurationToken]))
        XCTAssertFalse(Warning.concernsLengthOnly([Quality.shortDurationToken, Quality.sourceRateLowToken]))
    }

    // MARK: - The engine's refusal of a one-off reference

    @concurrent func testTheEngineRefusesAOneOffReferenceThatBlocksAndKeepsASavedVoiceWorking() async throws {
        let root = try temporaryDirectory()
        let source = root.appendingPathComponent("Long.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 61, sampleRate: 16_000), sampleRate: 16_000, to: source)
        let cache = NativePreparedCloneConditioningCache(capacity: 4)
        @concurrent func resolve(_ reference: CloneReference) async throws -> ResolvedCloneConditioning {
            try await cache.resolve(
                modelID: "clone", reference: reference, sampleRate: 24_000,
                audioPreparationService: NativeAudioPreparationService(),
                normalizedCloneReferenceDirectory: root.appendingPathComponent("normalized"))
        }
        do {
            _ = try await resolve(CloneReference(audioPath: source.path))
            XCTFail("a one-off reference over the cap must be refused")
        } catch let rejection as CloneReferenceQuality.Rejection {
            XCTAssertEqual(rejection.tokens, [CloneReferenceQuality.excessiveDurationToken])
            XCTAssertEqual(
                rejection.errorDescription,
                "Reference exceeds the 60 second maximum supported for cloning.")
        }
        // The same clip as a saved voice was accepted when it was enrolled.
        let saved = try await resolve(CloneReference(audioPath: source.path, preparedVoiceID: "Long"))
        XCTAssertEqual(saved.referenceQualityWarnings, [CloneReferenceQuality.excessiveDurationToken])

        let silent = root.appendingPathComponent("Silent.wav")
        try Self.writeWAV(Array(repeating: 0, count: 24_000 * 12), sampleRate: 24_000, to: silent)
        do {
            _ = try await resolve(CloneReference(audioPath: silent.path))
            XCTFail("a silent one-off reference must be refused")
        } catch let rejection as CloneReferenceQuality.Rejection {
            XCTAssertEqual(rejection.tokens, [CloneReferenceQuality.nearSilenceToken])
        }

        // Advice never refuses: a short telephone clip still conditions a take.
        let phone = root.appendingPathComponent("Phone.wav")
        try Self.writeWAV(Self.voiceLike(seconds: 4, sampleRate: 8_000), sampleRate: 8_000, to: phone)
        let advised = try await resolve(CloneReference(audioPath: phone.path))
        XCTAssertEqual(
            advised.referenceQualityWarnings,
            [CloneReferenceQuality.shortDurationToken, CloneReferenceQuality.sourceRateLowToken])
    }

    /// The apps show catalog copy for the reason and the CLI reports its code,
    /// whether the refusal arrives raw (before the model load) or wrapped by
    /// the runtime at clone preparation.
    func testARefusalResolvesToAReasonPeopleCanActOnRawOrWrapped() {
        typealias Reason = GenerationFailurePresentationReason
        let cases: [([String], String, Reason)] = [
            ([Quality.nearSilenceToken], "audio.reference_silent", .referenceAudioSilent),
            ([Quality.excessiveDurationToken], "audio.input_too_long", .referenceAudioTooLong),
            ([Quality.excessiveDurationToken, Quality.nearSilenceToken], "audio.reference_silent", .referenceAudioSilent),
            ([Quality.unreadableToken], "audio.processing_failed", .referenceAudioUnreadable),
        ]
        for (tokens, code, reason) in cases {
            let rejection = CloneReferenceQuality.Rejection(tokens: tokens)
            XCTAssertEqual(GenerationFailureDiagnosticLogger.errorMetadata(for: rejection).code, code)
            XCTAssertEqual(Reason(rejection), reason)
            let wrapped = NativeRuntimeError.wrapping(
                rejection, stage: .clonePreparation, message: "The native runtime could not prepare the clone reference")
            XCTAssertEqual(Reason(wrapped), reason, "\(tokens)")
            // The prime's quiet settle is for the refusal made before a load
            // only; one wrapped at clone preparation came after it.
            XCTAssertTrue(MLXTTSEngine.isCloneReferenceRejection(rejection))
            XCTAssertFalse(MLXTTSEngine.isCloneReferenceRejection(wrapped))
        }
        XCTAssertFalse(MLXTTSEngine.isCloneReferenceRejection(CancellationError()))
        XCTAssertEqual(
            CloneReferenceQuality.Rejection(tokens: ["unknown_token"]).errorDescription,
            "The reference clip cannot be used for cloning.")
        XCTAssertEqual(
            VocelloPresentationText().generationFailureMessage(Reason.referenceAudioSilent),
            "This reference audio is silent. Choose another clip.")
    }

    // MARK: - Fixtures

    private func temporaryDirectory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    /// Three partials under a slow swell: like speech, it reaches its peak
    /// rarely, where a steady tone would touch it every cycle.
    private static func voiceLike(seconds: Double, sampleRate: Double) -> [Float] {
        (0..<Int(seconds * sampleRate)).map { index in
            let time = Double(index) / sampleRate
            let swell = 0.55 + 0.45 * sin(2 * .pi * 0.37 * time)
            let tone = 0.6 * sin(2 * .pi * 173 * time)
                + 0.3 * sin(2 * .pi * 431 * time + 0.7)
                + 0.1 * sin(2 * .pi * 1_217 * time + 1.9)
            return Float(0.25 * swell * tone)
        }
    }

    private static func writeWAV(_ samples: [Float], sampleRate: Double, to url: URL) throws {
        try writeWAV(channels: [samples], sampleRate: sampleRate, to: url)
    }

    private static func writeWAV(channels: [[Float]], sampleRate: Double, to url: URL) throws {
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: channels.count,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        try write(channels: channels, to: AVAudioFile(forWriting: url, settings: settings))
    }

    private static func write(channels: [[Float]], to file: AVAudioFile) throws {
        let frames = AVAudioFrameCount(channels[0].count)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              let data = unsafe buffer.floatChannelData else {
            throw CocoaError(.fileWriteUnknown)
        }
        buffer.frameLength = frames
        for (channel, samples) in channels.enumerated() {
            for (index, sample) in samples.enumerated() {
                unsafe data[channel][index] = sample
            }
        }
        try file.write(from: buffer)
    }
}
