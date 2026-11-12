@unsafe @preconcurrency import AVFoundation
import CoreAudioTypes
import CoreMedia
import CryptoKit
import Foundation
import os

// MARK: - QwenVoiceCore Runtime Ownership
//
// Audio normalization is owned by `QwenVoiceCore` and shared by every host
// that runs the engine in-process (macOS app, iOS app, `vocello` CLI).
// `AudioPreparationRequest` is defined in `SemanticTypes.swift`; this file owns
// the concrete native normalization service used by both platforms.

public enum AudioPreparationError: LocalizedError, Equatable {
    case missingInputFile(String)
    case unsupportedInput(String)
    case inputFileTooLarge(path: String, maxBytes: Int64, actualBytes: Int64)
    case inputDurationTooLong(maxSeconds: Double, actualSeconds: Double)
    case decodeTimedOut(seconds: Double)
    case cancelled
    case missingOutputDirectory
    case failedToCreateOutputDirectory(String)
    case failedToReadAudio(String)
    case failedToCreateOutput(String)
    case conversionFailed(String)

    /// Path-free: the file's location never enters the description, which reaches
    /// the CLI and any host without interface copy for the typed reason (AUD-08).
    public var errorDescription: String? {
        switch self {
        case .missingInputFile:
            return "Audio file not found."
        case .unsupportedInput(let message):
            return message
        case .inputFileTooLarge(_, let maxBytes, let actualBytes):
            return "Audio file is too large to prepare safely: it is \(actualBytes) bytes; the limit is \(maxBytes) bytes."
        case .inputDurationTooLong(let maxSeconds, let actualSeconds):
            return unsafe "Audio file is too long to prepare safely: \(String(format: "%.1f", actualSeconds)) seconds; the limit is \(String(format: "%.1f", maxSeconds)) seconds."
        case .decodeTimedOut(let seconds):
            return unsafe "Audio preparation timed out after \(String(format: "%.1f", seconds)) seconds."
        case .cancelled:
            return "Audio preparation was cancelled."
        case .missingOutputDirectory:
            return "Audio preparation needs an output directory when the source is not already canonical."
        case .failedToCreateOutputDirectory:
            return "Couldn't create the audio output directory."
        case .failedToReadAudio:
            return "Couldn't read the audio file."
        case .failedToCreateOutput:
            return "Couldn't create the normalized audio output."
        case .conversionFailed(let message):
            // May carry a system error's text, which quotes file names.
            return DiagnosticPrivacy.redactedText(message)
        }
    }
}

public struct AudioNormalizationResult: Hashable, Codable, Sendable {
    public let sourcePath: String
    public let normalizedPath: String
    public let sampleRate: Double
    public let channelCount: Int
    public let frameCount: Int64
    public let durationSeconds: Double
    public let byteSize: Int64
    public let wasAlreadyCanonical: Bool
    public let fingerprint: String

    public init(
        sourcePath: String,
        normalizedPath: String,
        sampleRate: Double,
        channelCount: Int,
        frameCount: Int64,
        durationSeconds: Double,
        byteSize: Int64,
        wasAlreadyCanonical: Bool,
        fingerprint: String
    ) {
        self.sourcePath = sourcePath
        self.normalizedPath = normalizedPath
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        self.frameCount = frameCount
        self.durationSeconds = durationSeconds
        self.byteSize = byteSize
        self.wasAlreadyCanonical = wasAlreadyCanonical
        self.fingerprint = fingerprint
    }

    public var sourceURL: URL {
        URL(fileURLWithPath: sourcePath)
    }

    public var normalizedURL: URL {
        URL(fileURLWithPath: normalizedPath)
    }
}

public protocol AudioPreparationService: Sendable {
    @concurrent func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult
}

public struct AudioPreparationLimits: Hashable, Sendable {
    public static let defaults = AudioPreparationLimits(
        maxInputFileSizeBytes: 250 * 1_024 * 1_024,
        maxDecodedDurationSeconds: 120,
        trackLoadTimeoutSeconds: 60,
        normalizationTimeoutSeconds: 60
    )

    public let maxInputFileSizeBytes: Int64
    public let maxDecodedDurationSeconds: Double
    public let trackLoadTimeoutSeconds: Double
    public let normalizationTimeoutSeconds: Double

    public init(
        maxInputFileSizeBytes: Int64,
        maxDecodedDurationSeconds: Double,
        trackLoadTimeoutSeconds: Double,
        normalizationTimeoutSeconds: Double = 60
    ) {
        self.maxInputFileSizeBytes = maxInputFileSizeBytes
        self.maxDecodedDurationSeconds = maxDecodedDurationSeconds
        self.trackLoadTimeoutSeconds = trackLoadTimeoutSeconds
        self.normalizationTimeoutSeconds = normalizationTimeoutSeconds
    }
}

private actor NativeAudioPreparationWorkQueue {
    static let shared = NativeAudioPreparationWorkQueue()
    private var isRunning = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func run<T: Sendable>(_ operation: @Sendable @concurrent () async throws -> T) async throws -> T {
        await acquire()
        do {
            let result = try await operation()
            release()
            return result
        } catch {
            release()
            throw error
        }
    }

    private func acquire() async {
        if !isRunning {
            isRunning = true
            return
        }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    private func release() {
        if waiters.isEmpty {
            isRunning = false
        } else {
            waiters.removeFirst().resume()
        }
    }
}

struct AudioPreparationTestingHooks: Sendable {
    var beforeWriterCreation: (@Sendable @concurrent () async throws -> Void)?
    var beforeConversionLoop: (@Sendable @concurrent () async throws -> Void)?

    static let none = AudioPreparationTestingHooks()
}

private struct AudioPreparationDeadline: Sendable {
    let timeoutSeconds: Double
    let timeoutDuration: Duration
    let startedAt: ContinuousClock.Instant

    init(timeoutSeconds: Double) {
        self.timeoutSeconds = timeoutSeconds
        self.timeoutDuration = .nanoseconds(Int64((max(timeoutSeconds, 0) * 1_000_000_000).rounded(.up)))
        self.startedAt = .now
    }

    func check() throws {
        if Task.isCancelled {
            throw AudioPreparationError.cancelled
        }
        if timeoutSeconds <= 0 {
            throw AudioPreparationError.decodeTimedOut(seconds: timeoutSeconds)
        }
        // The timeout is cooperative: AVFoundation may still block inside a
        // synchronous decode call, but every boundary we control checks a
        // monotonic deadline before continuing.
        if startedAt.duration(to: .now) > timeoutDuration {
            throw AudioPreparationError.decodeTimedOut(seconds: timeoutSeconds)
        }
    }
}

public struct NativeAudioPreparationService: AudioPreparationService, Hashable, Sendable {
    /// Version of what preparation does to a clone reference before it is
    /// encoded (decode, downmix, resample to the canonical format). Raise it
    /// with any change that alters the prepared samples: the clone path folds
    /// it into the reference's fingerprint
    /// (`NativePreparedCloneConditioningCache.preparationFingerprint`), so
    /// prepared files, caches and persisted prompts made under the earlier
    /// version stop being reused (G-13). Until this existed, a fix to
    /// preparation never reached a reference that had been prepared before.
    ///
    /// - 1: the asset reader resamples (`Resampling.assetReader`).
    /// - 2: one converter call resamples (`Resampling.singleCall`).
    /// - 3: as 2, with two channels averaged (`Resampling.singleCallAveraged`).
    ///
    /// `PreparedVoiceRepository.removeDerivedCloneReferences` removes a
    /// deleted voice's prepared copies under every version up to the newest.
    public static var cloneReferencePreparationVersion: Int { Resampling.current.preparationVersion }
    public static let newestCloneReferencePreparationVersion = 3

    /// How a reference that is not already 24 kHz is brought to it.
    public enum Resampling: String, Hashable, Sendable {
        /// The asset reader decodes and resamples in one step. Its output is
        /// not reproducible: the same 16 kHz file gives two different sample
        /// sequences, one sample apart in length, in three of five clips over
        /// twelve runs (measured 2026-11-11, outside Vocello). A voice
        /// enrolled twice from one file can therefore differ.
        case assetReader
        /// The audio file reader decodes the clip at its own rate; the whole
        /// clip is then resampled by one `AVAudioConverter` call. Both steps
        /// give the same samples every time and the clip's exact length. The
        /// asset reader does neither even when it only decodes (measured
        /// 2026-11-11): one AAC file decoded to three different sample
        /// sequences over twelve runs, and a FLAC file came out 1,332 frames
        /// longer than it is. It decodes here only what the audio file
        /// reader cannot open. Two channels are mixed as the asset reader
        /// mixes them, the sum over the square root of two.
        case singleCall
        /// As `singleCall`, with two channels averaged, as upstream Qwen3-TTS
        /// (`librosa.load(mono=True)`, then `np.mean` over channels) and the
        /// Python port (`ffmpeg -ac 1`) mix them. The sum over the square
        /// root of two makes a voice recorded on both channels 3 dB hotter
        /// than its source and clips it where it peaked above -3 dBFS.
        case singleCallAveraged

        var preparationVersion: Int {
            switch self {
            case .assetReader: 1
            case .singleCall: 2
            case .singleCallAveraged: 3
            }
        }

        /// The audio file reader decodes and one converter call resamples.
        var usesSingleCall: Bool { self != .assetReader }

        /// How the single-call paths make one channel of two. The asset
        /// reader's own path mixes inside the reader.
        var mixdown: Mixdown { self == .singleCallAveraged ? .average : .sumOverRootTwo }

        static let environmentKey = "QWENVOICE_REFERENCE_PREPARATION"

        /// What every build does without the diagnostic key, since 2026-11-11:
        /// `singleCall` (adopted by the clone screen's rule
        /// `reference-preparation-v2`), then `singleCallAveraged` (adopted by
        /// the clone-stereo screen's rule `reference-mixdown-average`; RF-52).
        /// Changing it changes every prepared reference that is not already
        /// 24 kHz mono 16-bit WAV, and rebuilds every saved voice's prompt once.
        static let production: Resampling = .singleCallAveraged

        /// The path this process uses. Read once: the preparation version is
        /// part of every reference's identity, so it cannot change mid-run.
        public static let current = resolved(
            environment: ProcessInfo.processInfo.environment,
            internalDiagnosticsAvailable: RuntimeDebugGate.internalDiagnosticsAvailable
        )

        /// `QWENVOICE_REFERENCE_PREPARATION=asset-reader` (version 1) or
        /// `single-call` (version 2) restores an earlier path and
        /// `single-call-average` names the shipped one, honoured only in an
        /// internal-diagnostics build with the master gate on. Any other
        /// value is the production path: a screen arm
        /// proves which path it ran from each take's prepared-reference
        /// digest, not from the key having been set.
        static func resolved(
            environment: [String: String],
            internalDiagnosticsAvailable: Bool
        ) -> Resampling {
            let requested = RuntimeDebugGate.value(
                for: environmentKey,
                environment: environment,
                internalDiagnosticsAvailable: internalDiagnosticsAvailable
            )
            return requested.flatMap(Resampling.init(diagnosticValue:)) ?? production
        }

        init?(diagnosticValue: String) {
            switch diagnosticValue {
            case "single-call": self = .singleCall
            case "single-call-average": self = .singleCallAveraged
            case "asset-reader": self = .assetReader
            default: return nil
            }
        }
    }

    /// One channel from several.
    public enum Mixdown: Hashable, Sendable {
        /// Two channels summed and scaled by 1/sqrt(2), the asset reader's law.
        case sumOverRootTwo
        /// The mean of the channels, upstream's law.
        case average
    }

    public static let canonicalSampleRate: Double = 24_000
    public static let canonicalChannelCount: AVAudioChannelCount = 1
    public static let canonicalBitDepth = 16

    public let preparedAudioDirectory: URL?
    public let limits: AudioPreparationLimits
    public let resampling: Resampling
    let testingHooks: AudioPreparationTestingHooks

    public init(
        preparedAudioDirectory: URL? = nil,
        limits: AudioPreparationLimits = .defaults
    ) {
        self.init(preparedAudioDirectory: preparedAudioDirectory, limits: limits, resampling: .current)
    }

    /// The path is the process's, because the clone reference's fingerprint
    /// reads the process's preparation version: a service on another path
    /// would write that path's samples under this path's names. Only tests,
    /// which prepare into their own directories, choose one.
    init(
        preparedAudioDirectory: URL? = nil,
        limits: AudioPreparationLimits = .defaults,
        resampling: Resampling = .current,
        testingHooks: AudioPreparationTestingHooks = .none
    ) {
        self.preparedAudioDirectory = preparedAudioDirectory
        self.limits = limits
        self.resampling = resampling
        self.testingHooks = testingHooks
    }

    public static func == (
        lhs: NativeAudioPreparationService,
        rhs: NativeAudioPreparationService
    ) -> Bool {
        lhs.preparedAudioDirectory == rhs.preparedAudioDirectory
            && lhs.limits == rhs.limits
            && lhs.resampling == rhs.resampling
    }

    public func hash(into hasher: inout Hasher) {
        hasher.combine(preparedAudioDirectory)
        hasher.combine(resampling)
        hasher.combine(limits)
    }

    @concurrent public func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        do {
            return try await NativeAudioPreparationWorkQueue.shared.run { @concurrent in
                try Task.checkCancellation()
                return try await normalizeAudioAsynchronously(request)
            }
        } catch is CancellationError {
            throw AudioPreparationError.cancelled
        }
    }

    public static func isCanonicalWAV(at sourceURL: URL) -> Bool {
        guard FileManager.default.fileExists(atPath: sourceURL.path) else {
            return false
        }

        do {
            return isCanonical(
                file: try AVAudioFile(forReading: sourceURL),
                sourceURL: sourceURL
            )
        } catch {
            return false
        }
    }

    public static func canReuseExistingNormalizedOutput(at outputURL: URL, fingerprint: String) -> Bool {
        guard FileManager.default.fileExists(atPath: outputURL.path) else {
            return false
        }
        let normalizedStem = outputURL.deletingPathExtension().lastPathComponent
        guard normalizedStem.contains(fingerprint) else {
            return false
        }
        // A canonical header alone is not a reusable output: a conversion an
        // earlier build interrupted (it wrote in place) can leave a header with
        // no frames under the content-derived name, which would be reused forever.
        guard let file = try? AVAudioFile(forReading: outputURL),
              file.length > 0 else {
            return false
        }
        return isCanonical(file: file, sourceURL: outputURL)
    }

    @concurrent private func normalizeAudioAsynchronously(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        let deadline = AudioPreparationDeadline(timeoutSeconds: limits.normalizationTimeoutSeconds)
        let fileManager = FileManager.default
        let sourceURL = request.inputURL
        try deadline.check()
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw AudioPreparationError.missingInputFile(sourceURL.path)
        }
        let sourceByteSize = try Self.fileSize(at: sourceURL)
        if limits.maxInputFileSizeBytes > 0,
           sourceByteSize > limits.maxInputFileSizeBytes {
            throw AudioPreparationError.inputFileTooLarge(
                path: sourceURL.path,
                maxBytes: limits.maxInputFileSizeBytes,
                actualBytes: sourceByteSize
            )
        }
        try deadline.check()

        let fingerprint = Self.fileFingerprint(for: sourceURL)
        let inputFile: AVAudioFile
        do {
            inputFile = try AVAudioFile(forReading: sourceURL)
        } catch {
            throw AudioPreparationError.failedToReadAudio(sourceURL.path)
        }
        try deadline.check()
        guard inputFile.length > 0 else {
            throw AudioPreparationError.unsupportedInput(
                "The selected audio file does not contain readable audio frames."
            )
        }
        let inputDurationSeconds = inputFile.fileFormat.sampleRate > 0
            ? Double(inputFile.length) / inputFile.fileFormat.sampleRate
            : 0
        if limits.maxDecodedDurationSeconds > 0,
           inputDurationSeconds > limits.maxDecodedDurationSeconds {
            throw AudioPreparationError.inputDurationTooLong(
                maxSeconds: limits.maxDecodedDurationSeconds,
                actualSeconds: inputDurationSeconds
            )
        }

        let alreadyCanonical = Self.isCanonical(file: inputFile, sourceURL: sourceURL)
        let outputURL = try normalizedOutputURL(
            sourceURL: sourceURL,
            outputURL: request.outputURL,
            fingerprint: fingerprint,
            sourceAlreadyCanonical: alreadyCanonical
        )

        if alreadyCanonical && outputURL == sourceURL {
            return try Self.makeResult(
                sourceURL: sourceURL,
                normalizedURL: sourceURL,
                fingerprint: fingerprint,
                wasAlreadyCanonical: true
            )
        }

        if outputURL != sourceURL,
           Self.canReuseExistingNormalizedOutput(
                at: outputURL,
                fingerprint: request.outputReuseFingerprint ?? fingerprint
            ) {
            return try Self.makeResult(
                sourceURL: sourceURL,
                normalizedURL: outputURL,
                fingerprint: fingerprint,
                wasAlreadyCanonical: false
            )
        }
        try deadline.check()

        let parentDirectory = outputURL.deletingLastPathComponent()
        do {
            try fileManager.createDirectory(at: parentDirectory, withIntermediateDirectories: true)
        } catch {
            throw AudioPreparationError.failedToCreateOutputDirectory(parentDirectory.path)
        }

        // Convert into a hidden sibling and rename it onto `outputURL` only
        // after the conversion completed and the writer closed, so the
        // content-named output is never observed partially written: a crash or
        // cancellation mid-conversion leaves at most the hidden temporary file.
        let temporaryURL = Self.temporaryConversionURL(for: outputURL)
        let writtenFrameCount: Int64
        do {
            writtenFrameCount = try await Self.convertAudio(
                inputURL: sourceURL,
                outputURL: temporaryURL,
                limits: limits,
                resampling: resampling,
                deadline: deadline,
                testingHooks: testingHooks
            )
            try Self.replaceItem(at: outputURL, withConvertedAudioAt: temporaryURL)
        } catch is CancellationError {
            try? fileManager.removeItem(at: temporaryURL)
            throw AudioPreparationError.cancelled
        } catch let error as AudioPreparationError {
            try? fileManager.removeItem(at: temporaryURL)
            throw error
        } catch {
            try? fileManager.removeItem(at: temporaryURL)
            throw AudioPreparationError.conversionFailed(error.localizedDescription)
        }

        return try Self.makeCanonicalResult(
            sourceURL: sourceURL,
            normalizedURL: outputURL,
            fingerprint: fingerprint,
            wasAlreadyCanonical: false,
            frameCount: writtenFrameCount
        )
    }

    private func normalizedOutputURL(
        sourceURL: URL,
        outputURL: URL?,
        fingerprint: String,
        sourceAlreadyCanonical: Bool
    ) throws -> URL {
        if let outputURL {
            return outputURL
        }

        if sourceAlreadyCanonical {
            return sourceURL
        }

        guard let preparedAudioDirectory else {
            throw AudioPreparationError.missingOutputDirectory
        }

        let stem = Self.sanitizedStem(for: sourceURL)
        return preparedAudioDirectory.appendingPathComponent("\(stem)_\(fingerprint).wav")
    }

    /// Hidden sibling of `outputURL` in the same directory (so the final rename
    /// stays on one volume), keeping the `.wav` extension the writer's file
    /// type is inferred from.
    static func temporaryConversionURL(for outputURL: URL) -> URL {
        let stem = outputURL.deletingPathExtension().lastPathComponent
        return outputURL.deletingLastPathComponent().appendingPathComponent(
            ".\(stem).converting-\(UUID().uuidString).wav",
            isDirectory: false
        )
    }

    /// Atomically replaces `outputURL` (present or not) with the completed
    /// conversion at `temporaryURL`.
    private static func replaceItem(at outputURL: URL, withConvertedAudioAt temporaryURL: URL) throws {
        let result = unsafe temporaryURL.withUnsafeFileSystemRepresentation { temporaryPath in
            unsafe outputURL.withUnsafeFileSystemRepresentation { outputPath -> Int32 in
                guard let temporaryPath = unsafe temporaryPath, let outputPath = unsafe outputPath else { return -1 }
                return unsafe rename(temporaryPath, outputPath)
            }
        }
        guard result == 0 else {
            throw AudioPreparationError.failedToCreateOutput(outputURL.path)
        }
    }

    @concurrent private static func convertAudio(
        inputURL: URL,
        outputURL: URL,
        limits: AudioPreparationLimits,
        resampling: Resampling,
        deadline: AudioPreparationDeadline,
        testingHooks: AudioPreparationTestingHooks
    ) async throws -> Int64 {
        try deadline.check()
        let outputSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: canonicalSampleRate,
            AVNumberOfChannelsKey: canonicalChannelCount,
            AVLinearPCMBitDepthKey: canonicalBitDepth,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]

        if resampling.usesSingleCall,
           let decoded = try decodedMonoSamples(
               fromAudioFileAt: inputURL,
               mixdown: resampling.mixdown,
               maxDecodedDurationSeconds: limits.maxDecodedDurationSeconds,
               deadline: deadline
           ) {
            try await testingHooks.beforeWriterCreation?()
            try deadline.check()
            let writer: AVAudioFile
            do {
                writer = try AVAudioFile(
                    forWriting: outputURL,
                    settings: outputSettings,
                    commonFormat: .pcmFormatInt16,
                    interleaved: false
                )
            } catch {
                // As below: a writer that failed past the deadline timed out.
                try deadline.check()
                throw AudioPreparationError.failedToCreateOutput(outputURL.path)
            }
            try await testingHooks.beforeConversionLoop?()
            try deadline.check()
            let prepared = try resampledToCanonicalRate(
                decoded.samples,
                sourceSampleRate: decoded.sampleRate,
                deadline: deadline
            )
            try deadline.check()
            let written = try writeCanonical(prepared, to: writer, deadline: deadline)
            try deadline.check()
            guard written > 0 else {
                throw AudioPreparationError.unsupportedInput(
                    "The selected audio file does not contain readable audio frames."
                )
            }
            writer.close()
            return written
        }

        let asset = AVURLAsset(url: inputURL)
        let track: AVAssetTrack
        do {
            try deadline.check()
            track = try await firstAudioTrack(
                from: asset,
                timeoutSeconds: limits.trackLoadTimeoutSeconds
            )
            try deadline.check()
        } catch is CancellationError {
            throw AudioPreparationError.cancelled
        } catch let error as AudioPreparationError {
            throw error
        } catch {
            throw AudioPreparationError.conversionFailed("Couldn't load the native audio track.")
        }

        let reader: AVAssetReader
        try deadline.check()
        do {
            reader = try AVAssetReader(asset: asset)
        } catch let error as AudioPreparationError {
            throw error
        } catch {
            throw AudioPreparationError.conversionFailed("Couldn't create the native audio reader.")
        }

        // The single-call paths ask the reader for the track's own rate and channels
        // as float samples, so it decodes and does nothing else.
        let decodedSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let readerOutput = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: resampling.usesSingleCall ? decodedSettings : outputSettings
        )
        readerOutput.alwaysCopiesSampleData = false
        guard reader.canAdd(readerOutput) else {
            throw AudioPreparationError.unsupportedInput("The selected audio track could not be decoded natively.")
        }
        reader.add(readerOutput)

        try deadline.check()
        guard reader.startReading() else {
            throw AudioPreparationError.conversionFailed(reader.error?.localizedDescription ?? "Native audio decoding could not start.")
        }

        let writer: AVAudioFile
        try await testingHooks.beforeWriterCreation?()
        try deadline.check()
        do {
            writer = try AVAudioFile(
                forWriting: outputURL,
                settings: outputSettings,
                commonFormat: .pcmFormatInt16,
                interleaved: false
            )
        } catch let error as AudioPreparationError {
            throw error
        } catch {
            // The AVAudioFile initializer can block long enough for the
            // normalization deadline to expire mid-call. When that
            // happens the AVFoundation-level failure is the symptom, not
            // the cause; re-check the deadline so the timeout surfaces
            // as `.decodeTimedOut` instead of being remapped to
            // `.failedToCreateOutput`. The parallel `AVAssetReader`
            // catch above has the same structural risk; apply the same
            // idiom there if a flake surfaces.
            try deadline.check()
            throw AudioPreparationError.failedToCreateOutput(outputURL.path)
        }

        var totalWrittenFrames: Int64 = 0
        let maxOutputFrames = limits.maxDecodedDurationSeconds > 0
            ? Int64((limits.maxDecodedDurationSeconds * canonicalSampleRate).rounded(.up))
            : Int64.max
        do {
            try await testingHooks.beforeConversionLoop?()
            try deadline.check()
            if resampling.usesSingleCall {
                let decoded = try decodedMonoSamples(
                    from: readerOutput,
                    mixdown: resampling.mixdown,
                    maxDecodedDurationSeconds: limits.maxDecodedDurationSeconds,
                    deadline: deadline
                )
                try deadline.check()
                let prepared = try resampledToCanonicalRate(
                    decoded.samples,
                    sourceSampleRate: decoded.sampleRate,
                    deadline: deadline
                )
                try deadline.check()
                totalWrittenFrames = try writeCanonical(prepared, to: writer, deadline: deadline)
                try deadline.check()
            }
            while resampling == .assetReader, let sampleBuffer = readerOutput.copyNextSampleBuffer() {
                try deadline.check()
                let frameCount = CMSampleBufferGetNumSamples(sampleBuffer)
                guard frameCount > 0 else { continue }

                guard let outputBuffer = AVAudioPCMBuffer(
                    pcmFormat: writer.processingFormat,
                    frameCapacity: AVAudioFrameCount(frameCount)
                ) else {
                    throw AudioPreparationError.conversionFailed("Couldn't allocate the decoded audio buffer.")
                }
                outputBuffer.frameLength = AVAudioFrameCount(frameCount)

                guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else {
                    throw AudioPreparationError.conversionFailed("Decoded audio data was unavailable.")
                }

                let dataLength = CMBlockBufferGetDataLength(blockBuffer)
                guard let channelData = unsafe outputBuffer.int16ChannelData else {
                    throw AudioPreparationError.conversionFailed("Decoded audio data could not be mapped into PCM channels.")
                }

                let status = unsafe CMBlockBufferCopyDataBytes(
                    blockBuffer,
                    atOffset: 0,
                    dataLength: dataLength,
                    destination: UnsafeMutableRawPointer(channelData[0])
                )
                guard status == noErr else {
                    throw AudioPreparationError.conversionFailed("Decoded audio bytes could not be copied into the canonical buffer.")
                }

                try deadline.check()
                do {
                    try writer.write(from: outputBuffer)
                } catch {
                    throw AudioPreparationError.conversionFailed("Audio write failed: \(error.localizedDescription)")
                }

                totalWrittenFrames += Int64(frameCount)
                if totalWrittenFrames > maxOutputFrames {
                    throw AudioPreparationError.inputDurationTooLong(
                        maxSeconds: limits.maxDecodedDurationSeconds,
                        actualSeconds: Double(totalWrittenFrames) / canonicalSampleRate
                    )
                }
            }
        } catch {
            if reader.status == .reading {
                reader.cancelReading()
            }
            throw error
        }

        switch reader.status {
        case .completed:
            break
        case .reading:
            break
        case .failed:
            throw AudioPreparationError.conversionFailed(reader.error?.localizedDescription ?? "Native audio decoding failed.")
        case .cancelled:
            // A cancelled reader is a cancellation, typed at its origin so the
            // generation terminal classifier never has to read this text.
            throw AudioPreparationError.cancelled
        case .unknown:
            throw AudioPreparationError.conversionFailed("Native audio decoding ended in an unknown state.")
        @unknown default:
            throw AudioPreparationError.conversionFailed("Native audio decoding ended in an unsupported state.")
        }

        guard totalWrittenFrames > 0 else {
            throw AudioPreparationError.unsupportedInput(
                "The selected audio file does not contain readable audio frames."
            )
        }
        // Finalize the header before the caller renames the file into place.
        writer.close()

        return totalWrittenFrames
    }

    // MARK: - Single-call resampling

    /// The whole file through the audio file reader, mixed down to one
    /// channel at the file's own rate. Nil when that reader cannot open the
    /// file, which then goes to the asset reader's decode below.
    private static func decodedMonoSamples(
        fromAudioFileAt url: URL,
        mixdown: Mixdown,
        maxDecodedDurationSeconds: Double,
        deadline: AudioPreparationDeadline
    ) throws -> (samples: [Float], sampleRate: Double)? {
        guard let file = try? AVAudioFile(forReading: url) else { return nil }
        let format = file.processingFormat
        let sampleRate = format.sampleRate
        let channels = Int(format.channelCount)
        guard sampleRate > 0, channels > 0, format.commonFormat == .pcmFormatFloat32, !format.isInterleaved else {
            return nil
        }
        func requireWithinLimit(frames: Int) throws {
            let seconds = Double(frames) / sampleRate
            if maxDecodedDurationSeconds > 0, seconds > maxDecodedDurationSeconds {
                throw AudioPreparationError.inputDurationTooLong(
                    maxSeconds: maxDecodedDurationSeconds,
                    actualSeconds: seconds
                )
            }
        }
        // Refused from the header, before anything is decoded.
        try requireWithinLimit(frames: Int(file.length))
        let chunkFrames: AVAudioFrameCount = 32_768
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: chunkFrames) else {
            throw AudioPreparationError.conversionFailed("Couldn't allocate the decoded audio buffer.")
        }
        var mono: [Float] = []
        mono.reserveCapacity(Int(file.length) + Int(chunkFrames))
        while true {
            try deadline.check()
            buffer.frameLength = 0
            do {
                try file.read(into: buffer, frameCount: chunkFrames)
            } catch {
                // A compressed file's length is an estimate, so its decoder
                // can end a little before it; an error before any frame is
                // a file this reader cannot decode.
                guard !mono.isEmpty else { return nil }
                break
            }
            let frames = Int(buffer.frameLength)
            guard frames > 0, let channelData = unsafe buffer.floatChannelData else { break }
            if channels == 1 {
                unsafe mono.append(contentsOf: UnsafeBufferPointer(start: channelData[0], count: frames))
            } else {
                var interleaved = [Float](repeating: 0, count: frames * channels)
                for channel in 0..<channels {
                    let samples = unsafe channelData[channel]
                    for frame in 0..<frames {
                        interleaved[frame * channels + channel] = unsafe samples[frame]
                    }
                }
                mono.append(contentsOf: downmixed(interleaved, channels: channels, mixdown: mixdown))
            }
            try requireWithinLimit(frames: mono.count)
        }
        return (mono, sampleRate)
    }

    /// Everything the asset reader decodes, mixed down to one channel at the
    /// track's own rate: the fallback for a file the audio file reader cannot
    /// open. Its decode of a compressed track is not reproducible.
    private static func decodedMonoSamples(
        from readerOutput: AVAssetReaderTrackOutput,
        mixdown: Mixdown,
        maxDecodedDurationSeconds: Double,
        deadline: AudioPreparationDeadline
    ) throws -> (samples: [Float], sampleRate: Double) {
        var mono: [Float] = []
        var sampleRate: Double = 0
        while let sampleBuffer = readerOutput.copyNextSampleBuffer() {
            try deadline.check()
            let frameCount = CMSampleBufferGetNumSamples(sampleBuffer)
            guard frameCount > 0 else { continue }
            guard let stream = CMSampleBufferGetFormatDescription(sampleBuffer)?.audioStreamBasicDescription,
                  isInterleavedFloat32(stream),
                  sampleRate == 0 || sampleRate == stream.mSampleRate,
                  let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else {
                throw AudioPreparationError.conversionFailed("Decoded audio was not in the format that was asked for.")
            }
            sampleRate = stream.mSampleRate
            let channels = Int(stream.mChannelsPerFrame)
            let byteCount = frameCount * channels * MemoryLayout<Float>.size
            guard CMBlockBufferGetDataLength(blockBuffer) == byteCount else {
                throw AudioPreparationError.conversionFailed("Decoded audio did not match its declared format.")
            }
            var interleaved = [Float](repeating: 0, count: frameCount * channels)
            let status = interleaved.withMutableBufferPointer { destination in
                unsafe CMBlockBufferCopyDataBytes(
                    blockBuffer,
                    atOffset: 0,
                    dataLength: byteCount,
                    destination: UnsafeMutableRawPointer(destination.baseAddress!)
                )
            }
            guard status == noErr else {
                throw AudioPreparationError.conversionFailed("Decoded audio bytes could not be copied.")
            }
            mono.append(contentsOf: downmixed(interleaved, channels: channels, mixdown: mixdown))
            let decodedSeconds = Double(mono.count) / sampleRate
            if maxDecodedDurationSeconds > 0, decodedSeconds > maxDecodedDurationSeconds {
                throw AudioPreparationError.inputDurationTooLong(
                    maxSeconds: maxDecodedDurationSeconds,
                    actualSeconds: decodedSeconds
                )
            }
        }
        return (mono, sampleRate)
    }

    /// What `decodedSettings` asks the reader for; anything else would be
    /// read as the wrong numbers.
    static func isInterleavedFloat32(_ stream: AudioStreamBasicDescription) -> Bool {
        stream.mFormatID == kAudioFormatLinearPCM
            && stream.mFormatFlags & kAudioFormatFlagIsFloat != 0
            && stream.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0
            && stream.mFormatFlags & kAudioFormatFlagIsBigEndian == 0
            && stream.mBitsPerChannel == 32
            && stream.mSampleRate > 0
            && stream.mChannelsPerFrame > 0
    }

    /// One channel from the reader's interleaved frames. `sumOverRootTwo`
    /// sums two channels and scales by 1/sqrt(2), which is what the asset
    /// reader does when it is asked for one channel (measured: a tone on both
    /// channels comes out 3 dB hotter, a tone on one channel 3 dB quieter).
    /// `average` takes their mean, as upstream does. More than two channels,
    /// which a voice reference almost never has, are averaged either way.
    static func downmixed(_ interleaved: [Float], channels: Int, mixdown: Mixdown) -> [Float] {
        guard channels > 1 else { return interleaved }
        let scale: Float = channels == 2 && mixdown == .sumOverRootTwo
            ? Float(0.5.squareRoot())
            : 1 / Float(channels)
        return stride(from: 0, to: interleaved.count - channels + 1, by: channels).map { start in
            var sum: Float = 0
            for channel in 0..<channels {
                sum += interleaved[start + channel]
            }
            return sum * scale
        }
    }

    /// The whole clip through one converter, fed once: the same input gives
    /// the same output on every run, and the output has the clip's length at
    /// the new rate (the reader's own resampling drops about a millisecond).
    static func resampledToCanonicalRate(_ samples: [Float], sourceSampleRate: Double) throws -> [Float] {
        try resampledToCanonicalRate(samples, sourceSampleRate: sourceSampleRate, deadline: nil)
    }

    private static func resampledToCanonicalRate(
        _ samples: [Float],
        sourceSampleRate: Double,
        deadline: AudioPreparationDeadline?
    ) throws -> [Float] {
        guard !samples.isEmpty, sourceSampleRate != canonicalSampleRate else { return samples }
        guard let sourceFormat = AVAudioFormat(
                  commonFormat: .pcmFormatFloat32, sampleRate: sourceSampleRate, channels: 1, interleaved: false),
              let targetFormat = AVAudioFormat(
                  commonFormat: .pcmFormatFloat32, sampleRate: canonicalSampleRate, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: sourceFormat, to: targetFormat),
              let input = AVAudioPCMBuffer(pcmFormat: sourceFormat, frameCapacity: AVAudioFrameCount(samples.count)),
              let inputChannel = unsafe input.floatChannelData?[0] else {
            throw AudioPreparationError.conversionFailed("Couldn't create the sample-rate converter.")
        }
        samples.withBufferPointer { source in
            if let base = source.baseAddress {
                unsafe inputChannel.update(from: base, count: source.count)
            }
        }
        input.frameLength = AVAudioFrameCount(samples.count)
        converter.sampleRateConverterAlgorithm = AVSampleRateConverterAlgorithm_Mastering
        converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue

        let expected = Int((Double(samples.count) * canonicalSampleRate / sourceSampleRate).rounded(.up))
        var resampled: [Float] = []
        resampled.reserveCapacity(expected + 64)
        // The converter asks for input more than once: it gets the one buffer,
        // then the end of the stream. The closure holds the buffer, so it
        // stays alive until the conversion is over.
        let delivered = OSAllocatedUnfairLock(initialState: false)
        while true {
            try deadline?.check()
            guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: 32_768) else {
                throw AudioPreparationError.conversionFailed("Couldn't allocate the resampled audio buffer.")
            }
            var conversionError: NSError?
            let status = unsafe converter.convert(to: output, error: &conversionError) { _, inputStatus in
                let isFirstRequest = delivered.withLock { wasDelivered in
                    defer { wasDelivered = true }
                    return !wasDelivered
                }
                unsafe inputStatus.pointee = isFirstRequest ? .haveData : .endOfStream
                return isFirstRequest ? input : nil
            }
            if status == .error {
                throw AudioPreparationError.conversionFailed(
                    conversionError?.localizedDescription ?? "Sample-rate conversion failed.")
            }
            let produced = Int(output.frameLength)
            if produced > 0, let channel = unsafe output.floatChannelData?[0] {
                unsafe resampled.append(contentsOf: UnsafeBufferPointer(start: channel, count: produced))
            }
            // The tail arrives with `.endOfStream`; a call that produced
            // nothing has nothing more to give, whatever it reports.
            if status == .endOfStream || produced == 0 {
                break
            }
        }
        return resampled
    }

    /// One float sample as the canonical file stores it: scaled by 32,768,
    /// the scale the reader decodes 16-bit audio with, so a clip that is
    /// already at the model's rate comes through bit for bit; rounded to
    /// nearest and clamped.
    static func canonicalSample(_ value: Float) -> Int16 {
        let scaled = (value * 32_768).rounded()
        return Int16(max(-32_768, min(32_767, scaled.isFinite ? scaled : 0)))
    }

    /// Float samples to the canonical 16-bit file. Returns the frames written.
    private static func writeCanonical(
        _ samples: [Float],
        to writer: AVAudioFile,
        deadline: AudioPreparationDeadline
    ) throws -> Int64 {
        let chunkFrames = 65_536
        var written = 0
        while written < samples.count {
            try deadline.check()
            let count = min(chunkFrames, samples.count - written)
            guard let buffer = AVAudioPCMBuffer(
                      pcmFormat: writer.processingFormat, frameCapacity: AVAudioFrameCount(count)),
                  let channel = unsafe buffer.int16ChannelData?[0] else {
                throw AudioPreparationError.conversionFailed("Couldn't allocate the canonical audio buffer.")
            }
            for index in 0..<count {
                unsafe channel[index] = canonicalSample(samples[written + index])
            }
            buffer.frameLength = AVAudioFrameCount(count)
            do {
                try writer.write(from: buffer)
            } catch {
                throw AudioPreparationError.conversionFailed("Audio write failed: \(error.localizedDescription)")
            }
            written += count
        }
        return Int64(written)
    }

    @concurrent private static func firstAudioTrack(
        from asset: AVURLAsset,
        timeoutSeconds: Double
    ) async throws -> AVAssetTrack {
        guard timeoutSeconds > 0 else {
            throw AudioPreparationError.decodeTimedOut(seconds: timeoutSeconds)
        }
        return try await withThrowingTaskGroup(of: AVAssetTrack.self) { @concurrent group in
            group.addTask { @concurrent in
                let resolvedTrack = try await asset.loadTracks(withMediaType: .audio).first
                guard let resolvedTrack else {
                    throw AudioPreparationError.unsupportedInput(
                        "No readable audio track was found in the selected file."
                    )
                }
                return resolvedTrack
            }
            group.addTask { @concurrent in
                try await Task.sleep(nanoseconds: UInt64(timeoutSeconds * 1_000_000_000))
                throw AudioPreparationError.decodeTimedOut(seconds: timeoutSeconds)
            }

            guard let first = try await group.next() else {
                throw AudioPreparationError.unsupportedInput(
                    "No readable audio track was found in the selected file."
                )
            }
            group.cancelAll()
            return first
        }
    }

    private static func makeResult(
        sourceURL: URL,
        normalizedURL: URL,
        fingerprint: String,
        wasAlreadyCanonical: Bool
    ) throws -> AudioNormalizationResult {
        let normalizedFile: AVAudioFile
        do {
            normalizedFile = try AVAudioFile(forReading: normalizedURL)
        } catch {
            throw AudioPreparationError.failedToReadAudio(normalizedURL.path)
        }

        let frameCount = Int64(normalizedFile.length)
        let sampleRate = normalizedFile.fileFormat.sampleRate
        let channels = Int(normalizedFile.fileFormat.channelCount)
        let durationSeconds = sampleRate > 0 ? Double(frameCount) / sampleRate : 0
        let byteSize = Int64((try? normalizedURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)

        return AudioNormalizationResult(
            sourcePath: sourceURL.path,
            normalizedPath: normalizedURL.path,
            sampleRate: sampleRate,
            channelCount: channels,
            frameCount: frameCount,
            durationSeconds: durationSeconds,
            byteSize: byteSize,
            wasAlreadyCanonical: wasAlreadyCanonical,
            fingerprint: fingerprint
        )
    }

    private static func makeCanonicalResult(
        sourceURL: URL,
        normalizedURL: URL,
        fingerprint: String,
        wasAlreadyCanonical: Bool,
        frameCount: Int64
    ) throws -> AudioNormalizationResult {
        let byteSize = Int64((try? normalizedURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        let durationSeconds = canonicalSampleRate > 0 ? Double(frameCount) / canonicalSampleRate : 0

        return AudioNormalizationResult(
            sourcePath: sourceURL.path,
            normalizedPath: normalizedURL.path,
            sampleRate: canonicalSampleRate,
            channelCount: Int(canonicalChannelCount),
            frameCount: frameCount,
            durationSeconds: durationSeconds,
            byteSize: byteSize,
            wasAlreadyCanonical: wasAlreadyCanonical,
            fingerprint: fingerprint
        )
    }

    private static func isCanonical(file: AVAudioFile, sourceURL: URL) -> Bool {
        let settings = file.fileFormat.settings
        let bitDepth = settings[AVLinearPCMBitDepthKey] as? Int
        let formatID = settings[AVFormatIDKey] as? UInt32
        let isFloat = settings[AVLinearPCMIsFloatKey] as? Bool

        return sourceURL.pathExtension.lowercased() == "wav"
            && file.fileFormat.sampleRate == canonicalSampleRate
            && file.fileFormat.channelCount == canonicalChannelCount
            && formatID == kAudioFormatLinearPCM
            && bitDepth == canonicalBitDepth
            && isFloat == false
    }

    /// Path/size/mtime fingerprint of a source file, carried in every
    /// `AudioNormalizationResult` (and from there in clone-artifact metadata).
    static func fileFingerprint(for url: URL) -> String {
        let resolvedPath = url.resolvingSymlinksInPath().path
        let attributes = (try? FileManager.default.attributesOfItem(atPath: resolvedPath)) ?? [:]
        let size = (attributes[.size] as? NSNumber)?.int64Value ?? 0
        let mtime = (attributes[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let data = Data("\(resolvedPath)|\(size)|\(mtime)".utf8)
        let digest = SHA256.hash(data: data)
        return digest.prefix(8).map { unsafe String(format: "%02x", $0) }.joined()
    }

    private static func fileSize(at url: URL) throws -> Int64 {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        return Int64(values.fileSize ?? 0)
    }

    private static func sanitizedStem(for url: URL) -> String {
        let raw = url.deletingPathExtension().lastPathComponent
        let sanitized = raw
            .replacingOccurrences(of: #"[^\w\s-]"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
        return sanitized.isEmpty ? "reference" : sanitized
    }
}

public extension AudioPreparationRequest {
    init(inputURL: URL, outputURL: URL? = nil, outputReuseFingerprint: String? = nil) {
        self.init(
            inputPath: inputURL.path,
            outputPath: outputURL?.path,
            outputReuseFingerprint: outputReuseFingerprint
        )
    }

    var inputURL: URL {
        URL(fileURLWithPath: inputPath)
    }

    var outputURL: URL? {
        guard let outputPath else { return nil }
        return URL(fileURLWithPath: outputPath)
    }
}
