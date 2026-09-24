@preconcurrency import AVFoundation
import CoreMedia
import CryptoKit
import Foundation

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

    public var errorDescription: String? {
        switch self {
        case .missingInputFile(let path):
            return "Audio file not found: \(path)"
        case .unsupportedInput(let message):
            return message
        case .inputFileTooLarge(let path, let maxBytes, let actualBytes):
            return "Audio file is too large to prepare safely: \(path) is \(actualBytes) bytes; the limit is \(maxBytes) bytes."
        case .inputDurationTooLong(let maxSeconds, let actualSeconds):
            return "Audio file is too long to prepare safely: \(String(format: "%.1f", actualSeconds)) seconds; the limit is \(String(format: "%.1f", maxSeconds)) seconds."
        case .decodeTimedOut(let seconds):
            return "Audio preparation timed out after \(String(format: "%.1f", seconds)) seconds."
        case .cancelled:
            return "Audio preparation was cancelled."
        case .missingOutputDirectory:
            return "Audio preparation needs an output directory when the source is not already canonical."
        case .failedToCreateOutputDirectory(let path):
            return "Couldn't create audio output directory at \(path)."
        case .failedToReadAudio(let path):
            return "Couldn't read audio file at \(path)."
        case .failedToCreateOutput(let path):
            return "Couldn't create normalized audio output at \(path)."
        case .conversionFailed(let message):
            return message
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
    func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult
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

    func run<T: Sendable>(_ operation: @Sendable () async throws -> T) async throws -> T {
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
    var beforeWriterCreation: (@Sendable () async throws -> Void)?
    var beforeConversionLoop: (@Sendable () async throws -> Void)?

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
    public static let canonicalSampleRate: Double = 24_000
    public static let canonicalChannelCount: AVAudioChannelCount = 1
    public static let canonicalBitDepth = 16

    public let preparedAudioDirectory: URL?
    public let limits: AudioPreparationLimits
    let testingHooks: AudioPreparationTestingHooks

    public init(
        preparedAudioDirectory: URL? = nil,
        limits: AudioPreparationLimits = .defaults
    ) {
        self.preparedAudioDirectory = preparedAudioDirectory
        self.limits = limits
        self.testingHooks = .none
    }

    init(
        preparedAudioDirectory: URL? = nil,
        limits: AudioPreparationLimits = .defaults,
        testingHooks: AudioPreparationTestingHooks
    ) {
        self.preparedAudioDirectory = preparedAudioDirectory
        self.limits = limits
        self.testingHooks = testingHooks
    }

    public static func == (
        lhs: NativeAudioPreparationService,
        rhs: NativeAudioPreparationService
    ) -> Bool {
        lhs.preparedAudioDirectory == rhs.preparedAudioDirectory
            && lhs.limits == rhs.limits
    }

    public func hash(into hasher: inout Hasher) {
        hasher.combine(preparedAudioDirectory)
        hasher.combine(limits)
    }

    public func normalizeAudio(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
        do {
            return try await NativeAudioPreparationWorkQueue.shared.run {
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

    private func normalizeAudioAsynchronously(_ request: AudioPreparationRequest) async throws -> AudioNormalizationResult {
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
        let result = temporaryURL.withUnsafeFileSystemRepresentation { temporaryPath in
            outputURL.withUnsafeFileSystemRepresentation { outputPath -> Int32 in
                guard let temporaryPath, let outputPath else { return -1 }
                return rename(temporaryPath, outputPath)
            }
        }
        guard result == 0 else {
            throw AudioPreparationError.failedToCreateOutput(outputURL.path)
        }
    }

    private static func convertAudio(
        inputURL: URL,
        outputURL: URL,
        limits: AudioPreparationLimits,
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

        let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
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
            while let sampleBuffer = readerOutput.copyNextSampleBuffer() {
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
                guard let channelData = outputBuffer.int16ChannelData else {
                    throw AudioPreparationError.conversionFailed("Decoded audio data could not be mapped into PCM channels.")
                }

                let status = CMBlockBufferCopyDataBytes(
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

    private static func firstAudioTrack(
        from asset: AVURLAsset,
        timeoutSeconds: Double
    ) async throws -> AVAssetTrack {
        guard timeoutSeconds > 0 else {
            throw AudioPreparationError.decodeTimedOut(seconds: timeoutSeconds)
        }
        return try await withThrowingTaskGroup(of: AVAssetTrack.self) { group in
            group.addTask {
                let resolvedTrack = try await asset.loadTracks(withMediaType: .audio).first
                guard let resolvedTrack else {
                    throw AudioPreparationError.unsupportedInput(
                        "No readable audio track was found in the selected file."
                    )
                }
                return resolvedTrack
            }
            group.addTask {
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
        return digest.prefix(8).map { String(format: "%02x", $0) }.joined()
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
