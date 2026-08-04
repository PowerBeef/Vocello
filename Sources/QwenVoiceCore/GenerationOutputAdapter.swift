import AVFoundation
import CryptoKit
import Foundation
import MLX
@preconcurrency import VocelloQwen3Core
@preconcurrency import QwenVoiceBackendCore
import OSLog

// MARK: - QwenVoiceCore Runtime Ownership
//
// `GenerationOutputAdapter` is now owned by `QwenVoiceCore` and is
// shared by the active macOS XPC service and the iPhone in-process engine.
// Keep behavior changes here aligned with the platform host adapters.

protocol GenerationOutputAdapting {
    func run(
        chunkSink: @escaping @Sendable (GenerationEvent) async -> Void
    ) async throws -> GenerationResult
}

private enum NativeStreamingSignposts {
    static let signposter = OSSignposter(
        subsystem: "com.qwenvoice.engine",
        category: "generation"
    )

    /// Used to surface model/runtime instability (NaN/Inf samples) caught
    /// by `PCM16StreamLimiter` before it could poison PCM output or derived
    /// numeric metadata. Anything non-zero indicates the upstream MLX
    /// generation produced unstable samples that the limiter scrubbed.
    static let logger = Logger(
        subsystem: "com.qwenvoice.engine",
        category: "generation"
    )
}

struct NativeSignpostCorrelation: Hashable, Sendable {
    let runID: String
    let generationID: String
    let takeIndex: String
    let cell: String

    static let unscoped = NativeSignpostCorrelation(
        runID: "not-bench",
        generationID: "not-generation",
        takeIndex: "not-bench",
        cell: "not-bench"
    )

    var message: String {
        "runID=\(runID) generationID=\(generationID) takeIndex=\(takeIndex) cell=\(cell)"
    }
}

actor NativeTelemetryTerminalGate {
    private var claimed = false

    func claim() -> Bool {
        guard !claimed else { return false }
        claimed = true
        return true
    }
}

enum NativeTelemetryTerminalBoundary {
    static func name(for finishReason: GenerationFinishReason) -> String {
        switch finishReason {
        case .eos:
            "terminal_success"
        case .cancelled:
            "terminal_cancelled"
        case .maxTokens, .failed:
            "terminal_failure"
        }
    }

    static func name(for terminalReason: GenerationTerminalReason) -> String {
        switch terminalReason {
        case .eos, .completed:
            "terminal_success"
        case .cancelled:
            "terminal_cancelled"
        case .maxTokens, .failed, .superseded, .unknown:
            "terminal_failure"
        }
    }

    static func name(for error: Error) -> String {
        name(for: NativeGenerationTerminalClassifier.reason(for: error))
    }
}

final class GenerationOutputAdapter: GenerationOutputAdapting, @unchecked Sendable {
    private let generationID: UUID
    private let requestID: Int
    private let request: GenerationRequest
    private let model: UnsafeSpeechGenerationModel
    private let actorRequest: VocelloQwen3SynthesisRequest
    private let preparedCloneHandle: VocelloQwen3CloneHandle?
    private let cancellationIngress: GenerationCancellationIngress
    private let streamSessionsDirectory: URL
    private let warmState: EngineWarmState
    private let timingOverridesMS: [String: Int]
    private let booleanFlags: [String: Bool]
    private let stringFlags: [String: String]
    private let wasPrimed: Bool
    private let telemetryRecorder: NativeTelemetryRecorder?
    private let telemetrySampler: NativeTelemetrySampler?
    private let telemetryTerminalPolicy: NativeTelemetryTerminalPolicy
    private let loadCapabilityProfile: NativeLoadCapabilityProfile
    private let memoryPolicy: NativeMemoryPolicy
    private let initialMLXMemorySnapshots: [String: NativeMLXMemorySnapshot]
    private let pcmScratchBuffer: PCM16ScratchBuffer?
    /// Sendable holder for the engine process's app-support directory; read at
    /// telemetry-write time so the rescued `TelemetrySummary` lands under
    /// `diagnostics/engine/generations.jsonl`. `nil` for callers that don't supply it.
    private let diagnosticAppSupportBox: DiagnosticAppSupportBox?

    init(
        generationID: UUID,
        requestID: Int,
        request: GenerationRequest,
        model: UnsafeSpeechGenerationModel,
        actorRequest: VocelloQwen3SynthesisRequest,
        cloneHandle: VocelloQwen3CloneHandle?,
        cancellationIngress: GenerationCancellationIngress,
        streamSessionsDirectory: URL,
        warmState: EngineWarmState,
        timingOverridesMS: [String: Int] = [:],
        booleanFlags: [String: Bool] = [:],
        stringFlags: [String: String] = [:],
        wasPrimed: Bool = false,
        telemetryRecorder: NativeTelemetryRecorder? = nil,
        telemetrySampler: NativeTelemetrySampler? = nil,
        telemetryTerminalPolicy: NativeTelemetryTerminalPolicy = .publish,
        loadCapabilityProfile: NativeLoadCapabilityProfile,
        memoryPolicy: NativeMemoryPolicy,
        mlxMemorySnapshots: [String: NativeMLXMemorySnapshot],
        pcmScratchBuffer: PCM16ScratchBuffer? = nil,
        diagnosticAppSupportBox: DiagnosticAppSupportBox? = nil
    ) {
        self.generationID = generationID
        self.requestID = requestID
        self.request = request
        self.model = model
        self.actorRequest = actorRequest
        self.preparedCloneHandle = cloneHandle
        self.cancellationIngress = cancellationIngress
        self.streamSessionsDirectory = streamSessionsDirectory
        self.warmState = warmState
        self.timingOverridesMS = timingOverridesMS
        self.booleanFlags = booleanFlags
        self.stringFlags = stringFlags
        self.wasPrimed = wasPrimed
        self.telemetryRecorder = telemetryRecorder
        self.telemetrySampler = telemetrySampler
        self.telemetryTerminalPolicy = telemetryTerminalPolicy
        self.loadCapabilityProfile = loadCapabilityProfile
        self.memoryPolicy = memoryPolicy
        self.initialMLXMemorySnapshots = mlxMemorySnapshots
        self.pcmScratchBuffer = pcmScratchBuffer
        self.diagnosticAppSupportBox = diagnosticAppSupportBox
    }

    func run(
        chunkSink: @escaping @Sendable (GenerationEvent) async -> Void
    ) async throws -> GenerationResult {
        let telemetryTerminalGate = NativeTelemetryTerminalGate()
        let cloneHandle = preparedCloneHandle
        do {
            return try await withTaskCancellationHandler {
                // Cancellation can win after product preparation but before the
                // actor reservation exists. The typed ingress records that
                // decision before Task cancellation reaches this adapter.
                try cancellationIngress.checkCancellation()
                let chunkCapacity = actorRequest.chunking.pendingFrameLimit * 1_920
                let currentReservation = try await model.engine.reserveGeneration(
                    request: actorRequest,
                    cloneHandle: cloneHandle,
                    audioCapacityFrames: chunkCapacity
                )
                cancellationIngress.install { reason in
                    currentReservation.session.cancellation.request(
                        Self.runtimeCancellationReason(for: reason)
                    )
                }
                var opened = false
                var audio: VocelloQwen3LosslessAudioSequence?
                do {
                    try cancellationIngress.checkCancellation()
                    let claimedAudio = try await currentReservation.session.claimAudioConsumer()
                    audio = claimedAudio
                    try cancellationIngress.checkCancellation()
                    let sessionDirectory = try makeSessionDirectory()
                    let execution = StreamingExecutionContext(
                        requestID: requestID,
                        generationID: generationID,
                        request: request,
                        model: model,
                        sessionDirectory: sessionDirectory,
                        warmState: warmState,
                        timingOverridesMS: timingOverridesMS,
                        booleanFlags: booleanFlags,
                        stringFlags: stringFlags,
                        wasPrimed: wasPrimed,
                        telemetryRecorder: telemetryRecorder,
                        telemetrySampler: telemetrySampler,
                        telemetryTerminalPolicy: telemetryTerminalPolicy,
                        telemetryTerminalGate: telemetryTerminalGate,
                        loadCapabilityProfile: loadCapabilityProfile,
                        memoryPolicy: memoryPolicy,
                        initialMLXMemorySnapshots: initialMLXMemorySnapshots,
                        pcmScratchBuffer: pcmScratchBuffer,
                        diagnosticAppSupportBox: diagnosticAppSupportBox
                    )
                    // The reservation stays inert until its mandatory consumer
                    // and every fallible product-side setup step are complete.
                    try cancellationIngress.checkCancellation()
                    try await model.engine.open(currentReservation.id)
                    opened = true
                    let result = try await execution.run(
                        audio: claimedAudio,
                        session: currentReservation.session,
                        chunkSink: chunkSink
                    )
                    let terminal = await currentReservation.session.waitForModelTermination()
                    guard case .completed(.endOfSequence) = terminal.outcome else {
                        throw Self.productError(for: terminal.outcome)
                    }

                    // Product completion belongs to the operation lease. Do not
                    // release actor ownership until the sole public terminal has
                    // been accepted by the frontend transport.
                    await chunkSink(.completed(result))
                    _ = try await model.engine.acknowledgeProductFinalization(
                        generationID: generationID,
                        leaseID: currentReservation.lease.id,
                        token: currentReservation.session.finalizationToken,
                        disposition: .published
                    )
                    if let cloneHandle {
                        _ = await model.engine.releaseCloneHandle(cloneHandle)
                    }
                    await stopSamplerIfNeeded()
                    return result
                } catch {
                    let ingressReason = cancellationIngress.reason.map {
                        Self.runtimeCancellationReason(for: $0)
                    }
                    let reason = currentReservation.session.cancellation.reason
                        ?? ingressReason
                        ?? .shutdown
                    currentReservation.session.cancellation.request(reason)
                    await audio?.cancel(reason: reason)
                    if opened {
                        try await model.engine.cancelGeneration(
                            currentReservation.id,
                            reason: reason
                        )
                        _ = await currentReservation.session.waitForModelTermination()
                        _ = try await model.engine.acknowledgeProductFinalization(
                            generationID: generationID,
                            leaseID: currentReservation.lease.id,
                            token: currentReservation.session.finalizationToken,
                            disposition: .aborted(.runtime)
                        )
                    } else {
                        try await model.engine.abortReservation(
                            currentReservation.id,
                            reason: reason
                        )
                    }
                    throw error
                }
            } onCancel: {
                // Direct caller cancellation has no richer reason. A reason
                // already recorded by the admission coordinator wins.
                cancellationIngress.request(.user)
            }
        } catch {
            if let cloneHandle {
                _ = await model.engine.releaseCloneHandle(cloneHandle)
            }
            await writeUnhandledSessionFailureTelemetryIfNeeded(
                error,
                terminalGate: telemetryTerminalGate
            )
            await stopSamplerIfNeeded()
            throw error
        }
    }

    private static func runtimeCancellationReason(
        for reason: GenerationCancellationReason
    ) -> VocelloQwen3CancellationReason {
        switch reason {
        case .user: .user
        case .memoryPressure: .memoryPressure
        case .superseded: .superseded
        case .shutdown: .shutdown
        }
    }

    private static func productError(
        for outcome: VocelloQwen3TerminalOutcome
    ) -> Error {
        switch outcome {
        case .cancelled:
            return CancellationError()
        case .completed(.maximumTokens):
            return MLXTTSEngineError.generationFailed(
                "Qwen3-TTS reached maxNewTokens before EOS. The output was discarded."
            )
        case .failed, .completed:
            return MLXTTSEngineError.generationFailed(
                "Qwen3-TTS failed before product finalization."
            )
        }
    }

    /// Covers failures that occur before an execution context exists (most
    /// notably session-directory setup). Execution-owned failures normally
    /// claim the same terminal gate first, making this outer fallback a no-op.
    private func writeUnhandledSessionFailureTelemetryIfNeeded(
        _ error: Error,
        terminalGate: NativeTelemetryTerminalGate
    ) async {
        guard NativeGenerationTerminalClassifier.shouldPublish(
            error: error,
            policy: telemetryTerminalPolicy
        ), TelemetryGate.resolvedEnabled,
           let appSupportDirectory = diagnosticAppSupportBox?.url,
           await terminalGate.claim() else { return }

        let reason = NativeGenerationTerminalClassifier.reason(for: error)
        await telemetrySampler?.captureBoundary(
            NativeTelemetryTerminalBoundary.name(for: reason)
        )
        await telemetryRecorder?.mark(
            metadata: StreamFailureMessageMetadata(message: error.localizedDescription)
        )
        let stageMarks = await telemetryRecorder?.snapshot() ?? []
        let stopped = await telemetrySampler?.stop(stageMarks: stageMarks)
        let summary = stopped?.summary ?? TelemetrySummary.empty(stageMarks: stageMarks)
        let record = GenerationTelemetryRecord(
            generationID: generationID.uuidString,
            layer: .engine,
            recordedAt: ISO8601DateFormatter().string(from: Date()),
            mode: request.modeIdentifier,
            modelID: request.modelID,
            finishReason: reason.rawValue,
            stageMarks: stageMarks,
            summary: summary,
            thermalState: summary.thermalState,
            notes: GenerationTelemetryPrivacy.failureNotes(message: error.localizedDescription)
                .merging(BenchRunContext.telemetryNotes()) { current, _ in current }
        )
        await GenerationTelemetryJSONLSink.shared.write(
            record: record,
            appSupportDirectory: appSupportDirectory,
            subdirectory: "engine"
        )
        if NativeTelemetryMode.current().persistsRawSamples,
           let samples = stopped?.samples,
           !samples.isEmpty {
            await GenerationTelemetryJSONLSink.shared.writeRawSamples(
                samples,
                generationID: generationID.uuidString,
                appSupportDirectory: appSupportDirectory,
                subdirectory: "engine"
            )
        }
    }

    private func stopSamplerIfNeeded() async {
        let marks = await telemetryRecorder?.snapshot() ?? []
        _ = await telemetrySampler?.stop(stageMarks: marks)
    }

    private var previewTitle: String {
        String(request.text.prefix(40))
    }

    private func makeSessionDirectory() throws -> URL {
        try FileManager.default.createDirectory(
            at: streamSessionsDirectory,
            withIntermediateDirectories: true
        )
        let directory = Self.sessionDirectoryURL(
            in: streamSessionsDirectory,
            requestID: requestID
        )
        if FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.removeItem(at: directory)
        }
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }

    nonisolated static func sessionDirectoryURL(in rootDirectory: URL, requestID: Int) -> URL {
        rootDirectory.appendingPathComponent(
            String(format: "session_%04d", requestID),
            isDirectory: true
        )
    }

    nonisolated static func chunkFileName(for chunkIndex: Int) -> String {
        String(format: "chunk_%04d.wav", chunkIndex)
    }

    nonisolated static func chunkURL(in sessionDirectory: URL, chunkIndex: Int) -> URL {
        sessionDirectory.appendingPathComponent(chunkFileName(for: chunkIndex))
    }

    /// What the generation exit path may delete. Three terminal states:
    /// a completed streaming take keeps both the final WAV and the chunk
    /// session directory (the player replays chunks from it); a completed
    /// non-streaming take keeps only the final WAV; anything that did not
    /// complete (throw, cancellation) removes both so partial artifacts
    /// cannot leak. The final output is a product artifact, never session
    /// state — CM-7 was this table wrongly coupling its fate to streaming.
    nonisolated static func terminalCleanup(
        didCompleteProduct: Bool,
        usedStreaming: Bool
    ) -> (removeSession: Bool, removeOutput: Bool) {
        guard didCompleteProduct else {
            return (removeSession: true, removeOutput: true)
        }
        return (removeSession: !usedStreaming, removeOutput: false)
    }

}

private enum PCM16WAVWriter {
    static func makeFormat(sampleRate: Int) throws -> AVAudioFormat {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: Double(sampleRate),
            channels: 1,
            interleaved: false
        ) else {
            throw MLXTTSEngineError.generationFailed("Could not allocate the native PCM output format.")
        }
        return format
    }

    static func pcmSamples(from samples: [Float]) -> [Int16] {
        samples.map { sample in
            // NaN/Inf survive `max/min` comparisons (NaN comparisons always
            // return false), so without an explicit isFinite guard the Int16
            // conversion below would trap or produce undefined output and
            // also taint any derived numeric metadata (RMS, peak, duration)
            // that flows over IPC and breaks JSON-based encoders.
            let finiteSample = sample.isFinite ? sample : 0
            let clamped = max(-1.0, min(1.0, finiteSample))
            return Int16((clamped * Float(Int16.max)).rounded())
        }
    }

    static func makePCMBuffer(
        pcmSamples: [Int16],
        format: AVAudioFormat,
        reusableBuffer: inout AVAudioPCMBuffer?
    ) throws -> AVAudioPCMBuffer {
        let frameCount = AVAudioFrameCount(pcmSamples.count)
        if reusableBuffer?.frameCapacity ?? 0 < frameCount {
            guard let buffer = AVAudioPCMBuffer(
                pcmFormat: format,
                frameCapacity: frameCount
            ) else {
                throw MLXTTSEngineError.generationFailed("Could not allocate the native PCM output buffer.")
            }
            reusableBuffer = buffer
        }

        guard let buffer = reusableBuffer,
              let channelData = buffer.int16ChannelData?[0] else {
            throw MLXTTSEngineError.generationFailed("Could not allocate the native PCM output buffer.")
        }

        buffer.frameLength = frameCount
        pcmSamples.withUnsafeBufferPointer { pointer in
            channelData.update(from: pointer.baseAddress!, count: pcmSamples.count)
        }
        return buffer
    }
}

private enum AtomicFilePublisher {
    static func temporaryURL(for finalURL: URL) -> URL {
        let extensionName = finalURL.pathExtension
        let stem = finalURL.deletingPathExtension().lastPathComponent
        let temporaryName: String
        if extensionName.isEmpty {
            temporaryName = ".\(stem).\(UUID().uuidString).tmp"
        } else {
            // AVAudioFile chooses its container from the filename extension.
            // Keep `.wav` last so an atomic staging file cannot silently become
            // CAF bytes that are later published under a misleading WAV name.
            temporaryName = ".\(stem).\(UUID().uuidString).tmp.\(extensionName)"
        }
        return finalURL
            .deletingLastPathComponent()
            .appendingPathComponent(temporaryName)
    }

    static func publishAtomically(temporaryURL: URL, finalURL: URL) throws {
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: finalURL.path) {
            _ = try fileManager.replaceItemAt(
                finalURL,
                withItemAt: temporaryURL,
                backupItemName: nil,
                options: []
            )
        } else {
            try fileManager.moveItem(at: temporaryURL, to: finalURL)
        }
    }
}

enum AtomicPCM16WAVWriter {
    static func write(
        pcmSamples: [Int16],
        sampleRate: Int,
        outputURL: URL,
        signpostCorrelation: NativeSignpostCorrelation = .unscoped
    ) throws {
        let temporaryURL = AtomicFilePublisher.temporaryURL(for: outputURL)
        try? FileManager.default.removeItem(at: temporaryURL)
        defer {
            try? FileManager.default.removeItem(at: temporaryURL)
        }

        let header: Data = try {
            let headerSignpost = NativeStreamingSignposts.signposter.beginInterval(
                "Native Final WAV Manual Header Build",
                "\(signpostCorrelation.message, privacy: .public)"
            )
            defer {
                NativeStreamingSignposts.signposter.endInterval(
                    "Native Final WAV Manual Header Build",
                    headerSignpost,
                    "\(signpostCorrelation.message, privacy: .public)"
                )
            }
            return try makeHeader(sampleRate: sampleRate, frameCount: pcmSamples.count)
        }()

        try {
            let fileWriteSignpost = NativeStreamingSignposts.signposter.beginInterval(
                "Native Final WAV Manual File Write",
                "\(signpostCorrelation.message, privacy: .public)"
            )
            defer {
                NativeStreamingSignposts.signposter.endInterval(
                    "Native Final WAV Manual File Write",
                    fileWriteSignpost,
                    "\(signpostCorrelation.message, privacy: .public)"
                )
            }
            try write(header: header, pcmSamples: pcmSamples, to: temporaryURL)
        }()

        try {
            let publishSignpost = NativeStreamingSignposts.signposter.beginInterval(
                "Native Final WAV Manual Publish",
                "\(signpostCorrelation.message, privacy: .public)"
            )
            defer {
                NativeStreamingSignposts.signposter.endInterval(
                    "Native Final WAV Manual Publish",
                    publishSignpost,
                    "\(signpostCorrelation.message, privacy: .public)"
                )
            }
            try AtomicFilePublisher.publishAtomically(
                temporaryURL: temporaryURL,
                finalURL: outputURL
            )
        }()
    }

    private static func makeHeader(sampleRate: Int, frameCount: Int) throws -> Data {
        guard sampleRate > 0 else {
            throw MLXTTSEngineError.generationFailed("The native WAV writer received an invalid sample rate.")
        }
        let bytesPerSample = 2
        let dataByteCount = frameCount * bytesPerSample
        guard dataByteCount <= Int(UInt32.max) - 36 else {
            throw MLXTTSEngineError.generationFailed("The native WAV writer output is too large for RIFF/WAVE.")
        }

        var data = Data()
        data.reserveCapacity(44)
        appendASCII("RIFF", to: &data)
        appendUInt32LE(UInt32(36 + dataByteCount), to: &data)
        appendASCII("WAVE", to: &data)
        appendASCII("fmt ", to: &data)
        appendUInt32LE(16, to: &data)
        appendUInt16LE(1, to: &data) // PCM
        appendUInt16LE(1, to: &data) // mono
        appendUInt32LE(UInt32(sampleRate), to: &data)
        appendUInt32LE(UInt32(sampleRate * bytesPerSample), to: &data)
        appendUInt16LE(UInt16(bytesPerSample), to: &data)
        appendUInt16LE(16, to: &data)
        appendASCII("data", to: &data)
        appendUInt32LE(UInt32(dataByteCount), to: &data)
        return data
    }

    private static func write(
        header: Data,
        pcmSamples: [Int16],
        to url: URL
    ) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
            throw MLXTTSEngineError.generationFailed("Could not create the native WAV output file.")
        }
        let handle = try FileHandle(forWritingTo: url)
        do {
            try handle.write(contentsOf: header)
            let pcmData = pcmSamples.withUnsafeBufferPointer { pointer -> Data in
                guard let baseAddress = pointer.baseAddress else { return Data() }
                return Data(
                    bytes: UnsafeRawPointer(baseAddress),
                    count: pointer.count * MemoryLayout<Int16>.stride
                )
            }
            try handle.write(contentsOf: pcmData)
            try handle.synchronize()
            try handle.close()
        } catch {
            try? handle.close()
            throw error
        }
    }

    private static func appendASCII(_ value: String, to data: inout Data) {
        data.append(contentsOf: value.utf8)
    }

    private static func appendUInt16LE(_ value: UInt16, to data: inout Data) {
        data.append(contentsOf: [
            UInt8(value & 0xff),
            UInt8((value >> 8) & 0xff),
        ])
    }

    private static func appendUInt32LE(_ value: UInt32, to data: inout Data) {
        data.append(contentsOf: [
            UInt8(value & 0xff),
            UInt8((value >> 8) & 0xff),
            UInt8((value >> 16) & 0xff),
            UInt8((value >> 24) & 0xff),
        ])
    }
}

/// Per-session PCM16 conversion scratch space + limiter state. Lives as a
/// reference type so callers higher up the stack can choose to pool it
/// across generations (the underlying `[Int16]` capacity is the largest
/// per-generation allocation). Within a single session, `convertLimited`
/// reuses `storage` via `removeAll(keepingCapacity: true)`. `reset()` is
/// what pool callers should invoke between leases — it clears storage AND
/// the limiter so two different audio streams don't inherit each other's
/// gain state.
/// `@unchecked Sendable`: this is a reference type with mutable state, but
/// the contract is that a single session/execution owns it at a time —
/// callers serialize access via the session lifecycle. When pooled across
/// sessions, the pool itself (e.g. the engine) is responsible for
/// returning a buffer to the pool only after the lease has finished.
final class PCM16ScratchBuffer: @unchecked Sendable {
    private var storage: [Int16] = []
    private var limiter = PCM16StreamLimiter()

    init() {}

    var limiterMetrics: PCM16StreamLimiter.Metrics {
        limiter.metrics
    }

    func convertLimited(_ samples: [Float]) -> [Int16] {
        storage.removeAll(keepingCapacity: true)
        storage.reserveCapacity(samples.count)
        limiter.append(samples, into: &storage)
        return storage
    }

    func convertLimited(_ samples: [Float], into destination: inout [Int16]) {
        destination.removeAll(keepingCapacity: true)
        destination.reserveCapacity(samples.count)
        limiter.append(samples, into: &destination)
    }

    func pcm16LittleEndianData(from pcmSamples: [Int16]) -> Data {
        pcmSamples.withUnsafeBufferPointer { pointer in
            guard let baseAddress = pointer.baseAddress else { return Data() }
            return Data(
                bytes: UnsafeRawPointer(baseAddress),
                count: pointer.count * MemoryLayout<Int16>.stride
            )
        }
    }

    /// Clear storage length-to-zero (preserving capacity) and rebuild the
    /// limiter from scratch. Callers pooling this buffer across sessions
    /// must call this before each new lease — otherwise the limiter's
    /// `currentGain` / `previousOutput` from the previous generation
    /// would carry into the next, producing audible discontinuities at
    /// the start of the new audio.
    func reset() {
        storage.removeAll(keepingCapacity: true)
        limiter = PCM16StreamLimiter()
    }
}

struct PCM16StreamLimiter: Sendable {
    struct Metrics: Equatable, Sendable {
        var rawPeak: Float = 0
        var limitedPeak: Float = 0
        var samplesAboveCeiling = 0
        var samplesOutsideUnitRange = 0
        var slewLimitedSamples = 0
        var processedSamples = 0
        // Count of non-finite (NaN/Inf) samples observed at the limiter's
        // input. These are replaced with `0` before any gain math runs —
        // otherwise NaN propagates through the `max/min` clamps (NaN
        // comparisons always return false) and turns into undefined Int16
        // output plus non-finite derived metadata that breaks JSON-encoded
        // IPC payloads downstream.
        var nonFiniteSamples = 0
        // Absolute sample index (0-based) of the first non-finite input sample.
        // nil when no non-finite sample was observed. Used for defect localization.
        var firstNonFiniteSample: Int? = nil
        var minimumAppliedGain: Float = 1
        // Audio-QC accumulators (observational — do not affect limiting).
        // Sum of squared input magnitudes → whole-clip RMS (dead/near-silent
        // output detection). Longest *interior* near-silent run in samples (a
        // run bracketed by audio = a mid-utterance dropout; trailing/leading
        // silence is excluded). sampleRate-agnostic here; converted to ms at
        // report build.
        var sumOfSquares: Double = 0
        // Statistics for the limited samples actually written to the WAV.
        var outputSum: Double = 0
        var outputSumOfSquares: Double = 0
        var longestInteriorSilentRunSamples = 0
        // Absolute sample index where the longest interior silent run started.
        // nil when no interior silent run has closed. Used for dropout localization.
        var longestInteriorSilentRunStartSample: Int? = nil
        // Lengths (samples) of interior near-silent runs at/above the record
        // floor, in close order. Converted to ms and counted against the text's
        // pause budget at report build (punctuation-aware dropout calibration —
        // the model emits a prosodic pause at each sentence/clause boundary, so a
        // single long silence is normal; an EXCESS of them, or one egregious gap,
        // is the real tripwire). Bounded; far more entries than the cap means
        // pathological output, already caught by near_silent.
        var interiorSilentRunSamples: [Int] = []
        // Absolute sample index of the first input sample whose magnitude exceeds
        // the digital unit range (|x| > 1). nil when no clip was observed.
        var firstClipSample: Int? = nil

        private static func partsPerMillion(_ value: Float) -> Int {
            Int((Double(value) * 1_000_000).rounded())
        }
    }

    static let ceiling: Float = 0.965
    static let maxSingleSampleStep: Float = 0.42
    static let releaseStepPerSample: Float = 0.002
    /// Below this absolute input magnitude a sample counts as silence for
    /// interior-dropout detection.
    static let silenceFloor: Float = 0.001
    /// Don't record interior runs below this length (noise filter; well under any
    /// ms threshold the report applies, even at low sample rates). Recorded only
    /// when a run closes (audio resumes), so leading/trailing silence is excluded.
    static let interiorRunRecordFloorSamples = 2_400
    /// Cap on recorded interior runs — a long clip has a handful; this guards a
    /// pathological all-silence output from unbounded array growth.
    static let interiorRunRecordCap = 256

    private var currentGain: Float = 1
    private var previousOutput: Float?
    // Cross-`append` silence-run state (a dropout can span chunk boundaries).
    private var sawAudio = false
    private var currentSilentRun = 0
    private var currentSilentRunStartSample: Int?
    private(set) var metrics = Metrics()

    mutating func append(_ samples: [Float], into destination: inout [Int16]) {
        guard !samples.isEmpty else { return }
        destination.reserveCapacity(destination.count + samples.count)

        var localGain = currentGain
        var localPreviousOutput = previousOutput
        var localMetrics = metrics
        var localSawAudio = sawAudio
        var localSilentRun = currentSilentRun
        var localSilentRunStart = currentSilentRunStartSample

        samples.withUnsafeBufferPointer { buffer in
            guard let base = buffer.baseAddress else { return }
            let count = buffer.count
            for index in 0 ..< count {
                let absoluteIndex = localMetrics.processedSamples
                let rawSample = base[index]
                let sample: Float
                if rawSample.isFinite {
                    sample = rawSample
                } else {
                    localMetrics.nonFiniteSamples += 1
                    if localMetrics.firstNonFiniteSample == nil {
                        localMetrics.firstNonFiniteSample = absoluteIndex
                    }
                    sample = 0
                }
                let rawMagnitude = abs(sample)
                localMetrics.rawPeak = max(localMetrics.rawPeak, rawMagnitude)
                localMetrics.processedSamples += 1
                localMetrics.sumOfSquares += Double(rawMagnitude) * Double(rawMagnitude)
                // Interior-dropout tracking: count near-silent runs only after
                // the first audible sample; close a run (recording its length)
                // when audio resumes, so leading/trailing silence is excluded.
                if rawMagnitude < Self.silenceFloor {
                    if localSawAudio {
                        if localSilentRun == 0 {
                            localSilentRunStart = absoluteIndex
                        }
                        localSilentRun += 1
                    }
                } else {
                    if localSilentRun > 0 {
                        if localSilentRun > localMetrics.longestInteriorSilentRunSamples,
                           let start = localSilentRunStart {
                            localMetrics.longestInteriorSilentRunSamples = localSilentRun
                            localMetrics.longestInteriorSilentRunStartSample = start
                        }
                        if localSilentRun >= Self.interiorRunRecordFloorSamples,
                           localMetrics.interiorSilentRunSamples.count < Self.interiorRunRecordCap {
                            localMetrics.interiorSilentRunSamples.append(localSilentRun)
                        }
                        localSilentRun = 0
                        localSilentRunStart = nil
                    }
                    localSawAudio = true
                }
                if rawMagnitude > Self.ceiling {
                    localMetrics.samplesAboveCeiling += 1
                }
                if rawMagnitude > 1 {
                    localMetrics.samplesOutsideUnitRange += 1
                    if localMetrics.firstClipSample == nil {
                        localMetrics.firstClipSample = absoluteIndex
                    }
                }

                let targetGain = rawMagnitude > Self.ceiling
                    ? Self.ceiling / max(rawMagnitude, .leastNonzeroMagnitude)
                    : 1
                if targetGain < localGain {
                    localGain = targetGain
                } else {
                    localGain = min(targetGain, localGain + Self.releaseStepPerSample)
                }
                localMetrics.minimumAppliedGain = min(localMetrics.minimumAppliedGain, localGain)

                var limited = sample * localGain
                if let localPreviousOutput {
                    let delta = limited - localPreviousOutput
                    if delta > Self.maxSingleSampleStep {
                        limited = localPreviousOutput + Self.maxSingleSampleStep
                        localMetrics.slewLimitedSamples += 1
                    } else if delta < -Self.maxSingleSampleStep {
                        limited = localPreviousOutput - Self.maxSingleSampleStep
                        localMetrics.slewLimitedSamples += 1
                    }
                }

                limited = max(-Self.ceiling, min(Self.ceiling, limited))
                localPreviousOutput = limited
                localMetrics.limitedPeak = max(localMetrics.limitedPeak, abs(limited))
                localMetrics.outputSum += Double(limited)
                localMetrics.outputSumOfSquares += Double(limited) * Double(limited)
                destination.append(Int16((limited * Float(Int16.max)).rounded()))
            }
        }

        currentGain = localGain
        previousOutput = localPreviousOutput
        sawAudio = localSawAudio
        currentSilentRun = localSilentRun
        currentSilentRunStartSample = localSilentRunStart
        metrics = localMetrics
    }
}

private final class PCM16ChunkFileWriter {
    private let format: AVAudioFormat
    private var reusableBuffer: AVAudioPCMBuffer?

    init(sampleRate: Int) throws {
        self.format = try PCM16WAVWriter.makeFormat(sampleRate: sampleRate)
    }

    func write(pcmSamples: [Int16], to url: URL) throws {
        let buffer = try PCM16WAVWriter.makePCMBuffer(
            pcmSamples: pcmSamples,
            format: format,
            reusableBuffer: &reusableBuffer
        )
        let temporaryURL = Self.temporaryURL(for: url)
        try? FileManager.default.removeItem(at: temporaryURL)
        defer {
            try? FileManager.default.removeItem(at: temporaryURL)
        }

        // Hold AVAudioFile in a narrow scope so ARC guarantees its deinit
        // fires at the closing brace. AVAudioFile writes the final WAV/RIFF
        // `data`-chunk size field on deinit, not on write(from:), so this
        // deterministic teardown is the first half of correct finalization.
        do {
            let file = try AVAudioFile(
                forWriting: temporaryURL,
                settings: format.settings,
                commonFormat: format.commonFormat,
                interleaved: format.isInterleaved
            )
            try file.write(from: buffer)
        }
        // Force the kernel to commit the completed WAV so cross-process
        // readers (the UI's AVAudioFile(forReading:) in
        // AudioPlayerViewModel.loadPCMBuffer) observe a non-zero-length file.
        // Without this, chunk consumers intermittently saw audioFile.length
        // == 0 and the UI surfaced "Live audio preview could not decode the
        // latest chunk." even though the file eventually finalized correctly.
        if let handle = try? FileHandle(forWritingTo: temporaryURL) {
            try? handle.synchronize()
            try? handle.close()
        }
        try Self.publishAtomically(temporaryURL: temporaryURL, finalURL: url)
    }

    private static func temporaryURL(for finalURL: URL) -> URL {
        AtomicFilePublisher.temporaryURL(for: finalURL)
    }

    private static func publishAtomically(temporaryURL: URL, finalURL: URL) throws {
        try AtomicFilePublisher.publishAtomically(
            temporaryURL: temporaryURL,
            finalURL: finalURL
        )
    }
}

final class IncrementalPCM16WAVFileWriter {
    private var file: AVAudioFile?
    private let format: AVAudioFormat
    private var reusableBuffer: AVAudioPCMBuffer?
    private let finalURL: URL
    private let temporaryURL: URL
    private var published = false
    private var stagingFinalized = false
    private let signpostCorrelation: NativeSignpostCorrelation

    init(
        sampleRate: Int,
        outputURL: URL,
        signpostCorrelation: NativeSignpostCorrelation = .unscoped
    ) throws {
        self.signpostCorrelation = signpostCorrelation
        self.format = try PCM16WAVWriter.makeFormat(sampleRate: sampleRate)
        self.finalURL = outputURL
        self.temporaryURL = AtomicFilePublisher.temporaryURL(for: outputURL)
        try? FileManager.default.removeItem(at: temporaryURL)
        let createSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Final WAV Writer Create",
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
        defer {
            NativeStreamingSignposts.signposter.endInterval(
                "Native Final WAV Writer Create",
                createSignpost,
                "\(self.signpostCorrelation.message, privacy: .public)"
            )
        }
        self.file = try AVAudioFile(
            forWriting: temporaryURL,
            settings: format.settings,
            commonFormat: format.commonFormat,
            interleaved: format.isInterleaved
        )
    }

    func append(pcmSamples: [Int16]) throws {
        let bufferSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Final WAV Buffer Build",
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
        let buffer = try PCM16WAVWriter.makePCMBuffer(
            pcmSamples: pcmSamples,
            format: format,
            reusableBuffer: &reusableBuffer
        )
        NativeStreamingSignposts.signposter.endInterval(
            "Native Final WAV Buffer Build",
            bufferSignpost,
            "\(self.signpostCorrelation.message, privacy: .public)"
        )

        guard let file else {
            throw MLXTTSEngineError.generationFailed("The native WAV writer was already finalized.")
        }
        let writeSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Final WAV AVAudioFile Write",
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
        try file.write(from: buffer)
        NativeStreamingSignposts.signposter.endInterval(
            "Native Final WAV AVAudioFile Write",
            writeSignpost,
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
    }

    func finish() throws {
        _ = try finishStaging()
        try publish()
    }

    /// Closes and synchronizes the staged WAV without making it visible at the
    /// destination. The converged adapter validates this exact file first.
    @discardableResult
    func finishStaging() throws -> URL {
        if stagingFinalized { return temporaryURL }
        let finalizeSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Final WAV AVAudioFile Finalize",
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
        reusableBuffer = nil
        file = nil
        if let handle = try? FileHandle(forWritingTo: temporaryURL) {
            try? handle.synchronize()
            try? handle.close()
        }
        stagingFinalized = true
        NativeStreamingSignposts.signposter.endInterval(
            "Native Final WAV AVAudioFile Finalize",
            finalizeSignpost,
            "\(self.signpostCorrelation.message, privacy: .public)"
        )
        return temporaryURL
    }

    func publish() throws {
        guard stagingFinalized else {
            throw MLXTTSEngineError.generationFailed(
                "The native WAV writer must finalize staging before publication."
            )
        }
        guard !published else { return }
        try AtomicFilePublisher.publishAtomically(
            temporaryURL: temporaryURL,
            finalURL: finalURL
        )
        published = true
    }

    func discard() {
        reusableBuffer = nil
        file = nil
        stagingFinalized = true
        try? FileManager.default.removeItem(at: temporaryURL)
    }

    deinit {
        if !published {
            try? FileManager.default.removeItem(at: temporaryURL)
        }
    }
}

struct StreamingExecutionContext: Sendable {
    let requestID: Int
    let generationID: UUID
    let request: GenerationRequest
    let model: UnsafeSpeechGenerationModel
    let sessionDirectory: URL
    let warmState: EngineWarmState
    let timingOverridesMS: [String: Int]
    let booleanFlags: [String: Bool]
    let stringFlags: [String: String]
    let wasPrimed: Bool
    let telemetryRecorder: NativeTelemetryRecorder?
    let telemetrySampler: NativeTelemetrySampler?
    let telemetryTerminalPolicy: NativeTelemetryTerminalPolicy
    let telemetryTerminalGate: NativeTelemetryTerminalGate
    let loadCapabilityProfile: NativeLoadCapabilityProfile
    let memoryPolicy: NativeMemoryPolicy
    let initialMLXMemorySnapshots: [String: NativeMLXMemorySnapshot]
    /// Optional pooled scratch buffer shared with the parent session.
    /// When provided, the execution context calls `reset()` and reuses
    /// it instead of allocating a fresh `PCM16ScratchBuffer`. Saves the
    /// per-generation Int16-array allocation (~1-2 MB for a typical
    /// medium-length output) and lets the underlying capacity grow once
    /// to high-water mark and stay there across generations.
    let pcmScratchBuffer: PCM16ScratchBuffer?
    let diagnosticAppSupportBox: DiagnosticAppSupportBox?

    private func scratchBuffer() -> PCM16ScratchBuffer {
        if let pooled = pcmScratchBuffer {
            pooled.reset()
            return pooled
        }
        return PCM16ScratchBuffer()
    }

    var previewTitle: String {
        String(request.text.prefix(40))
    }


    /// Logs a warning when the PCM limiter had to scrub NaN/Inf samples
    /// from the model output. Non-zero counts here are a signal that the
    /// upstream MLX runtime produced unstable values — the limiter
    /// replaced them with `0` so they couldn't corrupt the PCM output
    /// or downstream IPC-encoded numeric metadata, but the underlying
    /// instability is worth surfacing.
    private static func warnIfNonFiniteSamplesObserved(
        metrics: PCM16StreamLimiter.Metrics,
        context: String
    ) {
        let nonFinite = metrics.nonFiniteSamples
        guard nonFinite > 0 else { return }
        let total = metrics.processedSamples
        NativeStreamingSignposts.logger.warning(
            "PCM limiter scrubbed \(nonFinite, privacy: .public) non-finite sample(s) out of \(total, privacy: .public) (\(context, privacy: .public)). Upstream MLX generation produced NaN/Inf values."
        )
    }

    func run(
        audio: VocelloQwen3LosslessAudioSequence,
        session: VocelloQwen3ClassifiedGenerationSession,
        chunkSink: @escaping @Sendable (GenerationEvent) async -> Void
    ) async throws -> GenerationResult {
        let benchNotes = BenchRunContext.telemetryNotes()
        let benchRunID = benchNotes["benchRunID"] ?? "not-bench"
        let benchTakeIndex = benchNotes["benchTakeIndex"] ?? "not-bench"
        let benchCell = benchNotes["benchCell"] ?? "not-bench"
        let signpostCorrelation = NativeSignpostCorrelation(
            runID: benchRunID,
            generationID: generationID.uuidString,
            takeIndex: benchTakeIndex,
            cell: benchCell
        )
        let generationSignpostID = NativeStreamingSignposts.signposter.makeSignpostID()
        let generationSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Generation Stream",
            id: generationSignpostID,
            "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
        )
        let generationStreamStartedAt = ContinuousClock.now
        defer {
            NativeStreamingSignposts.signposter.endInterval(
                "Native Generation Stream",
                generationSignpost,
                "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
            )
        }
        var signpostTimingsMS: [String: Int] = [:]
        let outputURL = URL(fileURLWithPath: request.outputPath)
        let sampleRate = model.sampleRate
        let telemetryMode = NativeTelemetryMode.current()
        let telemetryClock = telemetryRecorder?.clock
        let telemetryWorkPlan = NativeTelemetryWorkPlan(
            mode: telemetryMode,
            recorderPresent: telemetryRecorder != nil,
            sampleIntervalAvailable: telemetrySampler != nil
        )
        // Per-chunk decode timeline + final stats. Only populated when telemetry is
        // on (recorder non-nil), so there is zero per-chunk cost when gated off.
        let telemetryActive = telemetryWorkPlan.computesDerivedDiagnostics
        let chunkQCActive = telemetryWorkPlan.computesChunkQC
        var chunkTimeline: [GenerationChunkTelemetry] = []
        var chunkQCReports: [AudioQCChunkReport] = []
        var latestInfo: VocelloQwen3GenerationInfo?
        var finalizedDiagnostics = VocelloQwen3GenerationDiagnostics()
        await telemetrySampler?.captureBoundary("session_start")
        await telemetryRecorder?.mark(stage: .streamStartup)
        do {
            try FileManager.default.createDirectory(
                at: outputURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
        } catch {
            await writeFailureTelemetry(error: error, usedStreaming: request.shouldStream, counters: [:])
            throw error
        }

        // Cleanup is decided per artifact on the way out. Any error or
        // cancellation between directory creation and successful return
        // removes both the session directory and the partially-written
        // output file so they cannot leak (Tier 1.5). A completed take
        // always keeps its final WAV — retention of the *session directory*
        // is a streaming-only concern and must never delete the product
        // output with it (CM-7: every non-streaming success published a
        // path whose file this defer had just removed).
        var terminalCleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: false,
            usedStreaming: request.shouldStream
        )
        defer {
            if terminalCleanup.removeSession {
                try? FileManager.default.removeItem(at: sessionDirectory)
            }
            if terminalCleanup.removeOutput {
                try? FileManager.default.removeItem(at: outputURL)
            }
        }

        var chunkIndex = 0
        var totalFramesWritten: Int64 = 0
        var nextAudioFrame: UInt64 = 0
        var chunkObservations: [ShippingChunkObservationV9] = []
        var modelTerminalAtNS: UInt64?
        var modelOutcomeV9: ModelTerminalOutcomeV9?
        var audioChannelSummary: AudioChannelSummaryV9?
        var mlxMemorySnapshots = initialMLXMemorySnapshots
        mlxMemorySnapshots["before_stream"] = NativeMemoryPolicyResolver.snapshot()
        let streamingOutputPolicy = NativeStreamingOutputPolicy.current()
        let previewDataPolicy = NativeStreamingPreviewDataPolicy.current()
        let chunkWriter: PCM16ChunkFileWriter?
        do {
            chunkWriter = request.shouldStream
                && streamingOutputPolicy == .pcmPreviewAndFileArtifacts
                ? try PCM16ChunkFileWriter(sampleRate: sampleRate)
                : nil
        } catch {
            await writeFailureTelemetry(error: error, usedStreaming: request.shouldStream, counters: [:])
            throw error
        }
        let scratchBuffer = self.scratchBuffer()
        var pcmSamples = [Int16]()
        let finalWriter: IncrementalPCM16WAVFileWriter
        do {
            finalWriter = try IncrementalPCM16WAVFileWriter(
                sampleRate: sampleRate,
                outputURL: outputURL,
                signpostCorrelation: signpostCorrelation
            )
        } catch {
            await writeFailureTelemetry(error: error, usedStreaming: request.shouldStream, counters: [:])
            throw error
        }
        defer {
            finalWriter.discard()
        }

        do {
            for try await chunk in audio {
                try Task.checkCancellation()
                let chunkSamples = chunk.samples
                guard !chunkSamples.isEmpty else { continue }

                    if chunkQCActive {
                        chunkQCReports.append(
                            Self.makeAudioQCChunkReport(
                                chunkIndex: chunkIndex,
                                frameOffset: Int(totalFramesWritten),
                                samples: chunkSamples,
                                sampleRate: sampleRate
                            )
                        )
                    }

                    if chunkIndex == 0 {
                        NativeStreamingSignposts.signposter.emitEvent(
                            "Native First Audio Chunk",
                            id: generationSignpostID,
                            "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
                        )
                        await telemetryRecorder?.mark(
                            metadata: FirstChunkMetadata(chunkIndex: chunkIndex)
                        )
                        mlxMemorySnapshots["first_chunk"] = NativeMemoryPolicyResolver.snapshot()
                        await telemetrySampler?.captureBoundary("first_chunk")
                    }

                    scratchBuffer.convertLimited(chunkSamples, into: &pcmSamples)
                    let frameOffset = totalFramesWritten
                    let observationIndex = chunkIndex
                    let materializedAtNS = DispatchTime.now().uptimeNanoseconds
                    let previewAudio: StreamingAudioChunk?
                    if !request.shouldStream
                        || previewDataPolicy == .skip
                        || request.suppressStreamingPreview == true {
                        previewAudio = nil
                    } else {
                        previewAudio = StreamingAudioChunk(
                            generationID: generationID,
                            requestID: requestID,
                            sampleRate: sampleRate,
                            frameOffset: frameOffset,
                            frameCount: pcmSamples.count,
                            pcm16LE: scratchBuffer.pcm16LittleEndianData(from: pcmSamples),
                            isFinal: false
                        )
                    }
                    var chunkPath: String?

                    if let chunkWriter {
                        let chunkURL = GenerationOutputAdapter.chunkURL(
                            in: sessionDirectory,
                            chunkIndex: chunkIndex
                        )
                        try autoreleasepool {
                            try chunkWriter.write(
                                pcmSamples: pcmSamples,
                                to: chunkURL
                            )
                        }
                        chunkPath = chunkURL.path
                    }

                    try autoreleasepool {
                        try finalWriter.append(pcmSamples: pcmSamples)
                    }
                    let writtenAtNS = DispatchTime.now().uptimeNanoseconds

                    chunkIndex += 1
                    totalFramesWritten += Int64(pcmSamples.count)
                    let audioStartFrame = nextAudioFrame
                    let audioEndFrame = audioStartFrame + UInt64(pcmSamples.count)
                    nextAudioFrame = audioEndFrame

                    // Bind the stashed decode-substage breakdown to this chunk.
                    if telemetryActive, let timings = chunk.timings {
                        chunkTimeline.append(
                            makeChunkTelemetry(
                                chunkIndex: observationIndex,
                                timings: timings,
                                clock: telemetryClock
                            )
                        )
                    }

                    let chunkDurationSeconds = Double(pcmSamples.count) / Double(sampleRate)
                    let cumulativeDurationSeconds = Double(totalFramesWritten) / Double(sampleRate)

                    let chunkEvent = GenerationEvent.chunk(
                        GenerationChunk(
                            generationID: generationID,
                            requestID: requestID,
                            mode: request.modeIdentifier,
                            title: previewTitle,
                            chunkPath: chunkPath,
                            isFinal: false,
                            chunkDurationSeconds: chunkDurationSeconds,
                            cumulativeDurationSeconds: cumulativeDurationSeconds,
                            streamSessionDirectory: sessionDirectory.path,
                            previewAudio: previewAudio,
                            // Transport sequencing is zero-based: the first
                            // emitted chunk is index 0, matching the XPC gap
                            // detector and accumulator contract.
                            chunkSequence: UInt64(observationIndex)
                        )
                    )

                    var previewPublishedAtNS: UInt64?
                    let previewDisposition: PreviewPublicationDispositionV9
                    if request.shouldStream {
                        await chunkSink(chunkEvent)
                        if previewAudio == nil {
                            previewDisposition = .notRequested
                        } else {
                            previewPublishedAtNS = DispatchTime.now().uptimeNanoseconds
                            previewDisposition = .publishedToProductSink
                        }
                    } else {
                        previewDisposition = .notRequested
                    }
                    if TelemetryGate.resolvedEnabled {
                        let mlxInstants = Self.mlxChunkInstants(
                            timings: chunk.timings,
                            materializedAtNS: materializedAtNS
                        )
                        chunkObservations.append(
                            ShippingChunkObservationV9(
                                index: observationIndex,
                                transportSequence: UInt64(observationIndex),
                                codecStartFrame: chunk.codecStartFrame,
                                codecEndFrameExclusive: chunk.codecEndFrameExclusive,
                                audioStartFrame: audioStartFrame,
                                audioEndFrameExclusive: audioEndFrame,
                                generatedAtNS: mlxInstants?.generatedAtNS,
                                mlxEvaluationEnqueuedAtNS: mlxInstants?.enqueuedAtNS,
                                mlxEnqueueDurationNS: mlxInstants?.enqueueDurationNS,
                                mlxMaterializationDurationNS: mlxInstants?.materializationDurationNS,
                                materializedAtNS: materializedAtNS,
                                writtenAtNS: writtenAtNS,
                                previewPublishedAtNS: previewPublishedAtNS,
                                previewDisposition: previewDisposition
                            )
                        )
                    }
            }
            let terminal = await session.waitForModelTermination()
            modelTerminalAtNS = DispatchTime.now().uptimeNanoseconds
            latestInfo = terminal.generationInfo
            finalizedDiagnostics = terminal.diagnostics ?? finalizedDiagnostics
            switch terminal.outcome {
            case .completed(.endOfSequence):
                modelOutcomeV9 = .eos
            case .completed(.maximumTokens):
                modelOutcomeV9 = .tokenLimit
                throw MLXTTSEngineError.generationFailed(
                    "Qwen3-TTS reached maxNewTokens before EOS. The output was discarded."
                )
            case .cancelled:
                modelOutcomeV9 = .cancelled
                throw CancellationError()
            case .failed:
                modelOutcomeV9 = .failed
                throw MLXTTSEngineError.generationFailed(
                    "Qwen3-TTS failed before producing a complete final audio result."
                )
            }
            if TelemetryGate.resolvedEnabled {
                let channelStats = await audio.statistics()
                audioChannelSummary = AudioChannelSummaryV9(
                    capacityFrames: UInt64(max(0, channelStats.capacityFrames)),
                    highWaterFrames: UInt64(max(0, channelStats.highWaterFrames)),
                    producerSuspensionNS: channelStats.producerSuspensionNanoseconds,
                    producerSuspensionCount: channelStats.producerSuspensionCount,
                    cancellationWakeups: channelStats.cancellationWakeupCount
                )
            }
        } catch {
            GenerationFailureDiagnosticLogger.shared.log(
                surfacedMessage: "Streaming execution failed",
                stage: NativeRuntimeStage.streamFailed.description,
                underlyingError: error,
                request: request,
                appSupportDirectory: diagnosticAppSupportBox?.url
            )
            await writeFailureTelemetry(
                error: error,
                usedStreaming: request.shouldStream,
                counters: ["chunkCount": chunkIndex]
            )
            finalWriter.discard()
            try? FileManager.default.removeItem(at: outputURL)
            try? FileManager.default.removeItem(at: sessionDirectory)
            Memory.clearCache()
            throw error
        }

        if let terminalError = Self.postStreamTerminalError(
            totalFramesWritten: totalFramesWritten,
            isTaskCancelled: Task.isCancelled
        ) {
            await writeFailureTelemetry(
                error: terminalError,
                usedStreaming: request.shouldStream,
                counters: ["chunkCount": chunkIndex]
            )
            finalWriter.discard()
            try? FileManager.default.removeItem(at: outputURL)
            try? FileManager.default.removeItem(at: sessionDirectory)
            Memory.clearCache()
            throw terminalError
        }

        Self.warnIfNonFiniteSamplesObserved(
            metrics: scratchBuffer.limiterMetrics,
            context: "streaming chunks"
        )
        // Token loop + pipelined decoder drain finished; post-stream work (WAV
        // finalize, telemetry marks) is tracked separately from decodeWallSeconds.
        await telemetryRecorder?.mark(stage: .streamGenerationEnded)
        await telemetrySampler?.captureBoundary("final_audio_materialized")

        await telemetrySampler?.captureBoundary("before_final_wav")
        let finalWriteSignpost = NativeStreamingSignposts.signposter.beginInterval(
            "Native Final WAV Finish",
            "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
        )
        let finalWAVFinishStartedAt = ContinuousClock.now
        let finalAudioQC: AudioQCReport
        do {
            // Finalize the hidden staging file first. Fast QC owns the exact
            // persisted bytes and must pass before atomic destination
            // publication; telemetry mode never weakens this product gate.
            let stagingURL = try finalWriter.finishStaging()
            guard Self.isReadableWAV(at: stagingURL) else {
                throw MLXTTSEngineError.generationFailed(
                    "The staged streaming WAV could not be reopened for verification."
                )
            }
            await telemetrySampler?.captureBoundary("before_audio_qc")
            finalAudioQC = try Self.makePersistedWAVAudioQCReport(
                at: stagingURL,
                preWriteMetrics: scratchBuffer.limiterMetrics,
                expectedPauseCount: Self.expectedPauseCount(
                    in: (try? SpokenTextPlanner.plan(originalText: request.text).spokenText)
                        ?? request.text
                ),
                chunkQC: chunkQCActive && !chunkQCReports.isEmpty ? chunkQCReports : nil
            )
            await telemetrySampler?.captureBoundary("after_audio_qc")
            guard finalAudioQC.verdict != .fail else {
                // Triage evidence for an intermittent failure class: name the
                // exact failing rule flags (allowlisted labels, privacy-safe)
                // and, in diagnostics-enabled sessions, retain the rejected
                // staged WAV (newest only) so the audio itself is inspectable.
                if TelemetryGate.resolvedEnabled {
                    Self.preserveFailedQCStagedWAV(stagingURL, sessionDirectory: sessionDirectory)
                }
                throw MLXTTSEngineError.generationFailed(
                    "The finalized streaming WAV failed mandatory Fast audio QC "
                    + "[\(finalAudioQC.flags.joined(separator: ","))]."
                )
            }
            try finalWriter.publish()
            guard Self.isReadableWAV(at: outputURL) else {
                throw MLXTTSEngineError.generationFailed(
                    "The atomically published streaming WAV could not be reopened for reading."
                )
            }
        } catch {
            NativeStreamingSignposts.signposter.endInterval(
                "Native Final WAV Finish",
                finalWriteSignpost,
                "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
            )
            await writeFailureTelemetry(error: error, usedStreaming: request.shouldStream, counters: ["chunkCount": chunkIndex])
            throw error
        }
        NativeStreamingSignposts.signposter.endInterval(
            "Native Final WAV Finish",
            finalWriteSignpost,
            "runID=\(benchRunID, privacy: .public) generationID=\(generationID.uuidString, privacy: .public) takeIndex=\(benchTakeIndex, privacy: .public) cell=\(benchCell, privacy: .public)"
        )
        signpostTimingsMS["native_final_wav_finish_ms"] = finalWAVFinishStartedAt.elapsedMilliseconds
        await telemetrySampler?.captureBoundary("after_final_wav")
        mlxMemorySnapshots["after_final_write"] = NativeMemoryPolicyResolver.snapshot()

        let durationSeconds = Double(totalFramesWritten) / Double(sampleRate)
        await telemetryRecorder?.mark(stage: .streamCompleted)
        mlxMemorySnapshots["after_stream"] = NativeMemoryPolicyResolver.snapshot()
        let postRequestCacheClearApplied = memoryPolicy.clearCacheAfterGeneration
        if postRequestCacheClearApplied {
            await telemetrySampler?.captureBoundary("before_post_generation_trim")
            await telemetryRecorder?.mark(
                metadata: MemoryTrimMetadata(
                    level: .softTrim,
                    reason: "post_generation_cache_clear",
                    source: .postGeneration
                )
            )
            Memory.clearCache()
            mlxMemorySnapshots["after_generation_trim"] = NativeMemoryPolicyResolver.snapshot()
            await telemetrySampler?.captureBoundary("post_generation_trim")
        } else {
            await telemetrySampler?.captureBoundary("post_generation")
        }
        await telemetrySampler?.captureBoundary("terminal_success")
        let stageMarks = await telemetryRecorder?.snapshot() ?? []
        let (summary, rawSamples) = await Self.stopTelemetrySampler(
            telemetrySampler,
            stageMarks: stageMarks
        )

        let resolvedFinishReason: GenerationFinishReason = .eos

        // Re-read the model's diagnostics AFTER the decode loop: the MLX hot-loop
        // totals (talker forward, code predictor, decoder, stream-step eval/EOS,
        // token-loop total, generated-code count) are only finalized post-loop, so
        // the pre-loop `timingOverridesMS` snapshot misses them entirely.
        signpostTimingsMS["native_generation_stream_ms"] = generationStreamStartedAt.elapsedMilliseconds
        var finalTimingsMS = telemetryActive
            ? timingOverridesMS.merging(finalizedDiagnostics.timingsMilliseconds) { _, new in new }.merging(signpostTimingsMS) { _, new in new }
            : timingOverridesMS.merging(signpostTimingsMS) { _, new in new }
        if telemetryActive,
           let info = latestInfo,
           let tokenLoopMS = finalTimingsMS["qwen_token_loop_total"],
           tokenLoopMS > 0 {
            let infoMS = Int((info.generateTime * 1_000).rounded())
            let drainMS = max(0, tokenLoopMS - infoMS)
            if drainMS > 0 {
                finalTimingsMS["qwen_stream_decoder_drain_ms"] = drainMS
            }
        }
        let finalBooleanFlags = booleanFlags.merging(finalizedDiagnostics.booleanFlags) { _, new in new }
        let finalStringFlags = stringFlags.merging(finalizedDiagnostics.stringFlags) { _, new in new }

        let derivedMetrics: [String: Double]? = telemetryActive
            ? Self.computeDerivedMetrics(
                audioSeconds: durationSeconds,
                stageMarks: stageMarks,
                info: latestInfo,
                modelTimingsMS: finalTimingsMS
            )
            : nil

        var successNotes: [String: String] = [
            "finalChunkBarrierObserved": "true",
            "outputReadableWAV": "true",
            "outputAtomicallyPublished": "true",
        ]
        let publishedWAVDigest: String? = TelemetryGate.resolvedEnabled
            ? try? SamplingTakeEvidence.sha256FileDigest(at: outputURL)
            : nil
        if let wavDigest = publishedWAVDigest {
            let plannedSeed = request.seed
                ?? stringFlags["sampling_effective_seed"].flatMap(UInt64.init)
            let observedSeed = stringFlags["sampling_effective_seed"].flatMap(UInt64.init)
            let evidence = SamplingTakeEvidence(
                algorithmVersion: stringFlags["sampling_algorithm_version"].flatMap(Int.init)
                    ?? SamplingTakeEvidence.currentAlgorithmVersion,
                plannedSeed: plannedSeed,
                observedSeed: observedSeed,
                seedSource: request.seed == nil ? .generated : .requested,
                wavDigest: wavDigest
            )
            // Prefer fail-closed promotion packaging; fall back to observational
            // notes when a side is still incomplete (e.g. missing effective seed).
            if let packaged = try? evidence.packagedTelemetryNotes() {
                successNotes.merge(packaged) { _, evidence in evidence }
            } else {
                successNotes.merge(evidence.telemetryNotes) { _, evidence in evidence }
            }
        }
        successNotes.merge(GenerationStreamingTelemetryV9Publication.shippingIdentityNotes) {
            current, _ in current
        }

        // Phase 12: the typed quality registry runs at fast depth on every
        // shipping finalization; the persisted-WAV Fast QC verdict folds into
        // the typed gate and the registry verdict travels in the open
        // telemetry maps (no schema change).
        let hitTokenCap = finalStringFlags.contains { key, value in
            (key == "generation_end_reason" || key.hasSuffix("_generation_end_reason"))
                && value == "token_cap"
        }
        let qualityReport = GenerationQualityReportProducer.fastReport(
            generationID: generationID,
            finishReason: resolvedFinishReason,
            hitTokenCap: hitTokenCap,
            audioQC: finalAudioQC,
            wavDigest: publishedWAVDigest,
            usedStreaming: request.shouldStream,
            chunkCount: chunkIndex,
            audioChannel: audioChannelSummary
        )
        successNotes.merge(
            GenerationQualityReportProducer.telemetryNotes(for: qualityReport)
        ) { _, quality in quality }

        let productTerminalAtNS = DispatchTime.now().uptimeNanoseconds
        await writeEngineTelemetryRecord(
            summary: summary,
            stageMarks: stageMarks,
            usedStreaming: request.shouldStream,
            finishReason: resolvedFinishReason.rawValue,
            counters: ["chunkCount": chunkIndex],
            notes: successNotes,
            timingsMS: finalTimingsMS,
            derivedMetrics: derivedMetrics,
            mlxMemoryByStage: telemetryActive ? mlxMemorySnapshots : nil,
            chunkTimeline: chunkTimeline.isEmpty ? nil : chunkTimeline,
            audioQC: finalAudioQC,
            rawSamples: telemetryMode.persistsRawSamples ? rawSamples : nil,
            streamingChunkObservations: chunkObservations,
            streamingAudioChannel: audioChannelSummary,
            streamingTerminals: GenerationTerminalTimelineV9(
                modelTerminalAtNS: modelTerminalAtNS,
                productTerminalAtNS: productTerminalAtNS,
                modelOutcome: modelOutcomeV9,
                productOutcome: .completed
            )
        )

        terminalCleanup = GenerationOutputAdapter.terminalCleanup(
            didCompleteProduct: true,
            usedStreaming: request.shouldStream
        )
        return GenerationResult(
            audioPath: outputURL.path,
            durationSeconds: durationSeconds,
            streamSessionDirectory: request.shouldStream ? sessionDirectory.path : nil,
            usedStreaming: request.shouldStream,
            finishReason: resolvedFinishReason,
            diagnosticTimingsMS: finalTimingsMS,
            diagnosticBooleanFlags: finalBooleanFlags,
            diagnosticStringFlags: finalStringFlags,
            telemetrySummary: summary
        )
    }

    /// Async streams may finish normally after their producer task is
    /// cancelled. Check the task's cooperative cancellation state before
    /// interpreting an empty stream as an engine failure so memory-pressure
    /// cancellation retains its typed terminal reason and never surfaces a
    /// false "no audio chunks" error in the frontend.
    static func postStreamTerminalError(
        totalFramesWritten: Int64,
        isTaskCancelled: Bool
    ) -> Error? {
        if isTaskCancelled {
            return CancellationError()
        }
        guard totalFramesWritten > 0 else {
            return MLXTTSEngineError.generationFailed(
                "The native engine did not emit any audio chunks."
            )
        }
        return nil
    }

    private static func adaptiveStreamingInterval(
        for request: GenerationRequest,
        memoryPolicy: NativeMemoryPolicy
    ) -> Double {
        if request.batchTotal != nil {
            return 0.8
        }
        switch memoryPolicy.deviceClass {
        case .floor8GBMac, .iPhonePro:
            return 0.6
        case .mid16GBMac, .highMemoryMac:
            return 0.4
        }
    }

    private static func isReadableWAV(at url: URL) -> Bool {
        guard let file = try? AVAudioFile(forReading: url) else { return false }
        return file.fileFormat.sampleRate > 0 && file.length > 0
    }

    /// Close the per-generation session and persist one failure row for setup,
    /// empty-output, token-cap, or finalization failures that occur outside the
    /// producer-loop catch. The sampler itself is idempotent, so an outer cleanup
    /// may safely call stop again without changing this evidence.
    /// Newest-only retention of a QC-rejected staged WAV beside the session
    /// tree (policy-owned cache; routine cleanup prunes it). Diagnostics-gated
    /// by the caller.
    private static func preserveFailedQCStagedWAV(_ stagingURL: URL, sessionDirectory: URL) {
        let holdingDirectory = sessionDirectory
            .deletingLastPathComponent()
            .appendingPathComponent("failed-audio-qc", isDirectory: true)
        let fileManager = FileManager.default
        try? fileManager.createDirectory(at: holdingDirectory, withIntermediateDirectories: true)
        let destination = holdingDirectory.appendingPathComponent("failed-qc-latest.wav", isDirectory: false)
        try? fileManager.removeItem(at: destination)
        try? fileManager.copyItem(at: stagingURL, to: destination)
    }

    private func writeFailureTelemetry(
        error: Error,
        usedStreaming: Bool,
        counters: [String: Int]
    ) async {
        let reason = NativeGenerationTerminalClassifier.reason(for: error)
        await telemetrySampler?.captureBoundary(
            NativeTelemetryTerminalBoundary.name(for: reason)
        )
        await telemetryRecorder?.mark(
            metadata: StreamFailureMessageMetadata(message: error.localizedDescription)
        )
        let stageMarks = await telemetryRecorder?.snapshot() ?? []
        let (summary, rawSamples) = await Self.stopTelemetrySampler(
            telemetrySampler,
            stageMarks: stageMarks
        )
        guard NativeGenerationTerminalClassifier.shouldPublish(
            error: error,
            policy: telemetryTerminalPolicy
        ) else { return }
        await writeEngineTelemetryRecord(
            summary: summary,
            stageMarks: stageMarks,
            usedStreaming: usedStreaming,
            finishReason: reason.rawValue,
            counters: counters,
            notes: TelemetryGate.resolvedEnabled
                ? GenerationTelemetryPrivacy.failureNotes(message: error.localizedDescription)
                : [:],
            rawSamples: NativeTelemetryMode.current().persistsRawSamples ? rawSamples : nil
        )
    }

    /// Persists the rescued sampler `TelemetrySummary` + stage timeline as the
    /// engine-layer row of the unified telemetry artifact. Runtime-gated and a
    /// no-op when the gate is off or the app-support directory is unknown — so it
    /// is safe to call on every terminal path (success, failure, non-EOS finish).
    private func writeEngineTelemetryRecord(
        summary: TelemetrySummary,
        stageMarks: [NativeTelemetryStageMark],
        usedStreaming: Bool,
        finishReason: String?,
        counters: [String: Int],
        notes: [String: String],
        timingsMS: [String: Int]? = nil,
        derivedMetrics: [String: Double]? = nil,
        mlxMemoryByStage: [String: NativeMLXMemorySnapshot]? = nil,
        chunkTimeline: [GenerationChunkTelemetry]? = nil,
        audioQC: AudioQCReport? = nil,
        rawSamples: [TelemetrySample]? = nil,
        streamingChunkObservations: [ShippingChunkObservationV9] = [],
        streamingAudioChannel: AudioChannelSummaryV9? = nil,
        streamingTerminals: GenerationTerminalTimelineV9? = nil
    ) async {
        guard TelemetryGate.resolvedEnabled else { return }
        guard let appSupportDirectory = diagnosticAppSupportBox?.url else { return }
        guard await telemetryTerminalGate.claim() else { return }
        // Stamp the resolved device-memory tier so each row self-identifies which
        // policy it ran under — confirms a forced-tier benchmark took effect.
        // Reuses the free-form notes field; a caller-supplied key wins on collision.
        // Phase 10: the same deterministic plan the engine spoke from; nil only
        // for scripts the planner rejects (which never reach a success row).
        let spokenTextPlan = try? SpokenTextPlanner.plan(originalText: request.text)
        var tierNotes = [
            "deviceClass": NativeMemoryPolicyResolver.deviceClass().rawValue,
            // Whether the tier was forced (QWENVOICE_FORCE_MEMORY_CLASS) vs the
            // native, physical-memory-derived tier — so the summarizer doesn't
            // mislabel a real floor_8gb_mac (8 GB Mac) as "forced".
            "deviceClassForced": NativeDeviceClassGate.resolvedForcedClass != nil ? "true" : "false",
            // Input script length (characters) so the benchmark summarizer can
            // break results out by prompt length (short / medium / long) — RTF,
            // decode time, and KV-cache memory all scale with it.
            "promptChars": String(request.text.count),
            // Privacy-safe corpus identity for history/trend equivalence. The
            // script itself is never persisted in telemetry or tracked records.
            "promptDigest": SHA256.hash(data: Data(request.text.utf8))
                .map { String(format: "%02x", $0) }.joined(),
            // Resolved Qwen3 language for this generation (explicit hint or
            // text-detected) — verifies Auto-language resolution (incl. the
            // Latin-script NLLanguageRecognizer path) and gives delivery
            // benchmarks the language variable. Clone rows may differ when a
            // resolved transcript later refines the detection.
            "languageHint": GenerationSemantics.qwenLanguageHint(
                for: request,
                textOverride: spokenTextPlan?.spokenText
            ),
        ]
        tierNotes.merge(Self.samplingTelemetryNotes(for: request)) { current, _ in current }
        // Phase 10: when the spoken script differs from the typed script, the
        // row records the transformation count and the spoken-text digest so
        // the evidence names exactly what was synthesized. Deterministic
        // recomputation of the same plan the engine used; invariant scripts
        // (including the entire bench corpus) add nothing.
        if let spokenTextPlan, spokenTextPlan.transformationCount > 0 {
            tierNotes["spokenTextTransformations"] = String(spokenTextPlan.transformationCount)
            tierNotes["spokenTextDigest"] = spokenTextPlan.spokenTextDigest
        }
        if let algorithmVersion = stringFlags["sampling_algorithm_version"] {
            tierNotes["samplingAlgorithmVersion"] = algorithmVersion
        }
        if let effectiveSeed = stringFlags["sampling_effective_seed"] {
            // `samplingSeed` now means the resolved effective seed. This keeps
            // the existing telemetry field while ensuring unseeded requests
            // are reproducible from their evidence.
            tierNotes["samplingSeed"] = effectiveSeed
            tierNotes["samplingSeedSource"] = request.seed == nil ? "generated" : "requested"
        }
        if let talkerTopK = stringFlags["sampling_talker_top_k"] {
            tierNotes["samplingTalkerTopK"] = talkerTopK
        }
        if let subtalkerTopK = stringFlags["sampling_subtalker_top_k"] {
            tierNotes["samplingSubtalkerTopK"] = subtalkerTopK
        }
        if let simLimit = IOSMemorySnapshot.simulatedProcessLimitBytes {
            // Restriction-simulation rows must self-identify — a simulated
            // iPhone-15-Pro run must never read as a real-device proof.
            tierNotes["simulatedProcessLimitMB"] = String(simLimit / 1_048_576)
            if let profile = RuntimeDebugGate.value(for: "QVOICE_IOS_MEMORY_PROFILE") {
                tierNotes["memoryProfile"] = profile
            }
        }
        // Bench delivery cells (vocello bench --delivery) stamp the preset id so
        // the summarizer can segregate instruct-bearing takes from the plain matrix.
        // Read via getenv (not ProcessInfo) because the in-process CLI updates it per
        // take; only the id is recorded, never user text.
        if let delivery = RuntimeDebugGate.value(for: "QWENVOICE_BENCH_DELIVERY") {
            if !delivery.isEmpty { tierNotes["delivery"] = delivery }
        }
        // MLX/Metal memory policy notes so each row self-identifies the substrate
        // it ran under (cache limit, memory limit, clear cadence, KV window).
        let policyNotes = NativeMemoryPolicyResolver.currentPolicyNotes(for: memoryPolicy)
        tierNotes.merge(policyNotes) { _, policy in policy }

        // Nested telemetry-v9 transition identity. These values are the
        // privacy-safe shadow-plan digests already compared with independently
        // resolved shipping inputs; missing values remain explicitly
        // unavailable in the v9 bridge rather than being synthesized here.
        let v9IdentityNotes: [(source: String, digest: String, version: String, versionValue: String)] = [
            ("generation_plan_shadow_complete_digest", "streamingV9PlanDigest", "streamingV9PlanVersion", "1"),
            ("generation_plan_shadow_sampling_digest", "streamingV9SamplingDigest", "streamingV9SamplingVersion", stringFlags["sampling_algorithm_version"] ?? "1"),
            ("generation_plan_shadow_chunking_digest", "streamingV9ChunkDigest", "streamingV9ChunkVersion", "1"),
            ("generation_plan_shadow_memory_digest", "streamingV9MemoryDigest", "streamingV9MemoryVersion", "1"),
            ("generation_plan_shadow_output_digest", "streamingV9OutputPolicyDigest", "streamingV9OutputPolicyVersion", "1"),
            ("generation_plan_shadow_quality_digest", "streamingV9QualityPolicyDigest", "streamingV9QualityPolicyVersion", "1"),
        ]
        for identity in v9IdentityNotes {
            guard let digest = stringFlags[identity.source] else { continue }
            tierNotes[identity.digest] = digest
            tierNotes[identity.version] = identity.versionValue
        }

        // On iOS, derive the worst pressure band from the sampler summary using the
        // shipping process-budget thresholds so Jetsam-adjacent runs are visible on
        // the row. macOS retains the raw metrics without inheriting iPhone limits.
        if let worstBand = GenerationMemoryMetrics.worstPressureBand(for: summary) {
            tierNotes["memoryPressureBandWorst"] = worstBand.rawValue
        }

        // Row-level KV-cache footprint (audit P1-2): the per-chunk diagnostics carry
        // an estimated footprint; surface the peak as a headline derived metric so
        // regression tooling doesn't need to walk the chunk timeline.
        var derivedWithKV = derivedMetrics
        if let kvPeakMB = chunkTimeline?
            .compactMap({ $0.kvCacheDiagnostics?.estimatedFootprintMB })
            .max() {
            derivedWithKV = (derivedWithKV ?? [:]).merging(
                ["kvCacheEstimatedPeakMB": kvPeakMB]
            ) { current, _ in current }
        }

        // Adherence ground-truth for bench analysis (dev-gated diagnostics only —
        // this whole writer is behind TelemetryGate; never ships). These notes let
        // post-processing scripts pair instruct/design takes with their expected
        // voice description + delivery instruction; acoustic audioQC can't see adherence.
        switch request.payload {
        case .design(let voiceDescription, let deliveryStyle):
            let desc = voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines)
            if !desc.isEmpty { tierNotes["voiceDescriptionChars"] = String(desc.count) }
            if let d = deliveryStyle?.trimmingCharacters(in: .whitespacesAndNewlines), !d.isEmpty {
                tierNotes["deliveryInstructionChars"] = String(d.count)
            }
        case .custom(_, let deliveryStyle):
            if let d = deliveryStyle?.trimmingCharacters(in: .whitespacesAndNewlines), !d.isEmpty {
                tierNotes["deliveryInstructionChars"] = String(d.count)
            }
        case .clone:
            break
        }
        var notesWithTier = tierNotes
            .merging(notes) { _, caller in caller }
            .merging(currentTaskQOSNotes()) { current, _ in current }
            .merging(currentProcessSchedulingNotes()) { current, _ in current }
            .merging(BenchRunContext.telemetryNotes(intendedWarmState: warmState.rawValue)) { current, _ in current }
        let fixtureDigest: String? = {
            switch request.payload {
            case .custom:
                return nil
            case .design(let voiceDescription, _):
                return SHA256.hash(data: Data(voiceDescription.utf8))
                    .map { String(format: "%02x", $0) }.joined()
            case .clone(let reference):
                guard let data = try? Data(contentsOf: URL(fileURLWithPath: reference.audioPath), options: .mappedIfSafe) else {
                    return nil
                }
                return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            }
        }()
        let nestedStreamingV9 = GenerationStreamingTelemetryV9Bridge.make(
            generationID: generationID.uuidString,
            layer: .engine,
            notes: notesWithTier,
            frontend: nil,
            transport: nil,
            terminals: streamingTerminals,
            chunkObservations: streamingChunkObservations,
            audioChannel: streamingAudioChannel
        )
        if let nestedStreamingV9 {
            let sidecarDirectory = appSupportDirectory
                .appendingPathComponent("diagnostics", isDirectory: true)
                .appendingPathComponent("engine", isDirectory: true)
                .appendingPathComponent("streaming-telemetry-v9", isDirectory: true)
            if let published = try? GenerationStreamingTelemetryV9Publication.publishCompleteSidecarIfReady(
                transition: nestedStreamingV9,
                directory: sidecarDirectory
            ) {
                notesWithTier["streamingTelemetryV9SidecarDigest"] = published.digest
                notesWithTier["streamingTelemetryV9PublicationReady"] = "true"
            } else if GenerationStreamingTelemetryV9Publication.isPublicationReady(nestedStreamingV9) {
                notesWithTier["streamingTelemetryV9PublicationReady"] = "true"
            }
        }
        let record = GenerationTelemetryRecord(
            generationID: generationID.uuidString,
            layer: .engine,
            recordedAt: ISO8601DateFormatter().string(from: Date()),
            mode: request.modeIdentifier,
            modelID: request.modelID,
            warmState: warmState,
            usedStreaming: usedStreaming,
            finishReason: finishReason,
            stageMarks: stageMarks,
            summary: summary,
            thermalState: summary.thermalState,
            timingsMS: timingsMS ?? timingOverridesMS,
            counters: counters,
            notes: notesWithTier,
            derivedMetrics: derivedWithKV,
            mlxMemoryByStage: mlxMemoryByStage,
            chunkTimeline: chunkTimeline,
            audioQC: audioQC,
            modelRuntimeIdentity: ModelRuntimeIdentity(
                resolvedModelID: request.modelID,
                modelVariant: stringFlags["model_identity_variant"],
                modelRepository: stringFlags["model_identity_repository"],
                huggingFaceRevision: stringFlags["model_identity_revision"],
                artifactVersion: stringFlags["model_identity_artifact_version"],
                quantization: stringFlags["model_identity_quantization"],
                integrityManifestDigest: stringFlags["model_identity_integrity_manifest_digest"],
                runtimeProfileSignature: stringFlags["qwen3_runtime_profile_signature"],
                nativeLoadCapabilityProfile: loadCapabilityProfile.rawValue,
                fixtureDigest: fixtureDigest
            ),
            streamingTelemetryV9: nestedStreamingV9
        )
        await GenerationTelemetryJSONLSink.shared.write(
            record: record,
            appSupportDirectory: appSupportDirectory,
            subdirectory: "engine"
        )
        // Opt-in verbose: persist the raw per-sample memory/timing series to a
        // per-generation sidecar for deep memory-curve analysis. Off by default.
        if let rawSamples, !rawSamples.isEmpty {
            await GenerationTelemetryJSONLSink.shared.writeRawSamples(
                rawSamples,
                generationID: generationID.uuidString,
                appSupportDirectory: appSupportDirectory,
                subdirectory: "engine"
            )
        }
    }

    /// Privacy-safe request-origin sampling notes. The writer later replaces
    /// `samplingSeed` with the resolved effective seed from the immutable
    /// runtime policy, including for originally unseeded requests, and may add
    /// the persisted WAV digest plus planned/observed seed agreement fields.
    static func samplingTelemetryNotes(for request: GenerationRequest) -> [String: String] {
        var notes = [
            "samplingVariation": (request.variation ?? .expressive).rawValue,
        ]
        if let seed = request.seed {
            notes["samplingPlannedSeed"] = String(seed)
            notes["samplingSeed"] = String(seed)
        }
        return notes
    }

    /// Re-open the atomically published WAV and derive the written-output half
    /// of the QC report from those exact persisted frames. Pre-limiter
    /// instability counters are retained from generation, while energy, DC and
    /// dropout evidence is replaced by the file that downstream consumers read.
    static func makePersistedWAVAudioQCReport(
        at url: URL,
        preWriteMetrics: PCM16StreamLimiter.Metrics? = nil,
        expectedPauseCount: Int,
        chunkQC: [AudioQCChunkReport]? = nil
    ) throws -> AudioQCReport {
        let file = try AVAudioFile(forReading: url)
        let frameCount = Int(file.length)
        guard frameCount > 0, file.processingFormat.sampleRate > 0 else {
            throw MLXTTSEngineError.generationFailed(
                "The finalized WAV contains no readable audio frames."
            )
        }
        // Keep persisted-output verification bounded for long clips. The
        // limiter owns cross-block continuity and silence-run state, so the
        // exact QC result is independent of this block size.
        let blockFrameCount = min(frameCount, 16_384)
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: file.processingFormat,
            frameCapacity: AVAudioFrameCount(blockFrameCount)
        ) else {
            throw MLXTTSEngineError.generationFailed(
                "The finalized WAV could not allocate a verification buffer."
            )
        }
        var persistedLimiter = PCM16StreamLimiter()
        var discardedPCM: [Int16] = []
        discardedPCM.reserveCapacity(blockFrameCount)
        var observedFrameCount = 0
        while observedFrameCount < frameCount {
            buffer.frameLength = 0
            let requested = min(blockFrameCount, frameCount - observedFrameCount)
            try file.read(into: buffer, frameCount: AVAudioFrameCount(requested))
            let count = Int(buffer.frameLength)
            guard count > 0 else { break }
            let persistedSamples: [Float]
            if let floats = buffer.floatChannelData {
                persistedSamples = Array(UnsafeBufferPointer(start: floats[0], count: count))
            } else if let integers = buffer.int16ChannelData {
                persistedSamples = UnsafeBufferPointer(start: integers[0], count: count).map {
                    Float($0) / Float(Int16.max)
                }
            } else {
                throw MLXTTSEngineError.generationFailed(
                    "The finalized WAV uses an unsupported verification format."
                )
            }
            discardedPCM.removeAll(keepingCapacity: true)
            persistedLimiter.append(persistedSamples, into: &discardedPCM)
            observedFrameCount += count
        }
        guard observedFrameCount == frameCount else {
            throw MLXTTSEngineError.generationFailed(
                "The finalized WAV ended before every audio frame could be verified."
            )
        }
        let persisted = persistedLimiter.metrics
        var combined = preWriteMetrics ?? persisted
        combined.processedSamples = persisted.processedSamples
        combined.outputSum = persisted.outputSum
        combined.outputSumOfSquares = persisted.outputSumOfSquares
        combined.longestInteriorSilentRunSamples = persisted.longestInteriorSilentRunSamples
        combined.longestInteriorSilentRunStartSample = persisted.longestInteriorSilentRunStartSample
        combined.interiorSilentRunSamples = persisted.interiorSilentRunSamples

        return makeAudioQCReport(
            metrics: combined,
            sampleRate: Int(file.processingFormat.sampleRate.rounded()),
            durationSeconds: Double(observedFrameCount) / file.processingFormat.sampleRate,
            expectedPauseCount: expectedPauseCount,
            chunkQC: chunkQC
        )
    }

    /// Build the reference-free `AudioQCReport` from the limiter's per-sample
    /// metrics. Thresholds are conservative + tunable here — they exist to catch
    /// GROSS defects (regression tripwire), not to claim subjective naturalness.
    /// Autonomous promotion combines this evidence with the applicable fixed-seed
    /// ASR, prosody, and delivery gates. Fractions are relative to processed samples.
    static func makeAudioQCReport(
        metrics: PCM16StreamLimiter.Metrics,
        sampleRate: Int,
        durationSeconds: Double,
        expectedPauseCount: Int,
        chunkQC: [AudioQCChunkReport]? = nil
    ) -> AudioQCReport {
        let n = metrics.processedSamples
        let rms = n > 0 ? (metrics.outputSumOfSquares / Double(n)).squareRoot() : 0
        let rmsDBFS: Double? = rms > 0 ? 20 * log10(rms) : nil
        let dcOffset: Double? = n > 0 ? metrics.outputSum / Double(n) : nil
        let longestSilenceMS = sampleRate > 0
            ? Int(Double(metrics.longestInteriorSilentRunSamples) * 1000 / Double(sampleRate))
            : 0
        let longestSilenceStartMS: Int? = {
            guard let startSample = metrics.longestInteriorSilentRunStartSample, sampleRate > 0 else { return nil }
            return Int(Double(startSample) * 1000 / Double(sampleRate))
        }()
        // Every interior silence run (≥ record floor), in ms — for the
        // punctuation-aware dropout check below.
        let interiorSilencesMS: [Int] = sampleRate > 0
            ? metrics.interiorSilentRunSamples.map { Int(Double($0) * 1000 / Double(sampleRate)) }
            : []
        let clipped = metrics.samplesOutsideUnitRange
        let hot = metrics.samplesAboveCeiling
        let clicks = metrics.slewLimitedSamples
        let denom = max(n, 1)
        let clippedFrac = Double(clipped) / Double(denom)
        let clickFrac = Double(clicks) / Double(denom)
        let hotFrac = Double(hot) / Double(denom)

        // Conservative thresholds (documented; tune as the corpus dictates).
        let silentFailDBFS = -60.0, lowLevelWarnDBFS = -45.0
        let clipFailFrac = 0.001, clickFailFrac = 0.005
        let clickWarnFrac = 0.0005, hotWarnFrac = 0.02
        let dcOffsetWarn = 0.05, dcOffsetFail = 0.20
        // Dropout (punctuation-aware). The model emits a prosodic pause at each
        // sentence/clause boundary; on long, slow content these legitimately reach
        // ~800 ms — verified that EVERY long-content interior silence maps to a
        // punctuation mark, so the old fixed 400 ms fail line cried wolf on natural
        // delivery. Instead: count "long pauses" against the text's pause budget
        // (punctuation boundaries) and flag only an EXCESS beyond it, or a single
        // EGREGIOUS gap no natural pause reaches. A mid-phrase gap that merely
        // replaces a punctuation pause cannot be classified by amplitude alone;
        // fixed-seed exact-WAV, ASR-consensus, and prosody evidence own that gate.
        // Long-content calibration (2026-07-23): ~60 s narration segments show
        // sentence/comma pauses up to ~1.45 s (retained failed-qc evidence,
        // gap positions correlated with text boundaries). The short-form
        // thresholds below were calibrated on the ≤341-char canonical corpus
        // (natural max ~810 ms) and misclassified narration pacing as
        // dropouts when extrapolated to minute-scale takes.
        let longContent = durationSeconds >= 45
        let longPauseMS = longContent ? 600 : 350
        let egregiousMS = longContent ? 2_000 : 1_200
        let suspiciousSingleMS = longContent ? 1_500 : 900
        let longPauseCount = interiorSilencesMS.filter { $0 >= longPauseMS }.count
        let excessLongPauses = max(0, longPauseCount - max(0, expectedPauseCount))

        var flags: [String] = []
        var instabilityVerdict: AudioQCReport.Verdict = .pass
        var writtenOutputVerdict: AudioQCReport.Verdict = .pass
        func raise(_ to: AudioQCReport.Verdict, _ verdict: inout AudioQCReport.Verdict) {
            if to == .fail { verdict = .fail }
            else if to == .warn, verdict != .fail { verdict = .warn }
        }
        func worst(
            _ lhs: AudioQCReport.Verdict,
            _ rhs: AudioQCReport.Verdict
        ) -> AudioQCReport.Verdict {
            if lhs == .fail || rhs == .fail { return .fail }
            if lhs == .warn || rhs == .warn { return .warn }
            return .pass
        }

        if metrics.nonFiniteSamples > 0 {
            flags.append("nonfinite"); raise(.fail, &instabilityVerdict)
        }
        if n == 0 { flags.append("empty"); raise(.fail, &writtenOutputVerdict) }
        if let db = rmsDBFS {
            if db < silentFailDBFS { flags.append("near_silent"); raise(.fail, &writtenOutputVerdict) }
            else if db < lowLevelWarnDBFS { flags.append("low_level"); raise(.warn, &writtenOutputVerdict) }
        } else if n > 0 { flags.append("silent"); raise(.fail, &writtenOutputVerdict) }
        if longestSilenceMS >= egregiousMS {
            flags.append("dropout:\(longestSilenceMS)ms"); raise(.fail, &writtenOutputVerdict)
        } else if excessLongPauses >= 2 {
            flags.append("dropout:excess\(excessLongPauses)(\(longPauseCount)/\(expectedPauseCount))"); raise(.fail, &writtenOutputVerdict)
        } else if excessLongPauses == 1 {
            flags.append("dropout:excess1(\(longPauseCount)/\(expectedPauseCount))"); raise(.warn, &writtenOutputVerdict)
        } else if longestSilenceMS >= suspiciousSingleMS {
            flags.append("dropout:\(longestSilenceMS)ms"); raise(.warn, &writtenOutputVerdict)
        }
        if clippedFrac > clipFailFrac { flags.append("clipping"); raise(.fail, &instabilityVerdict) }
        else if clipped > 0 { flags.append("clipping"); raise(.warn, &instabilityVerdict) }
        if clickFrac > clickFailFrac { flags.append("clicks"); raise(.fail, &instabilityVerdict) }
        else if clickFrac > clickWarnFrac { flags.append("clicks"); raise(.warn, &instabilityVerdict) }
        if hotFrac > hotWarnFrac { flags.append("hot"); raise(.warn, &instabilityVerdict) }
        if let dcOffset {
            if abs(dcOffset) > dcOffsetFail {
                flags.append("dc_offset"); raise(.fail, &writtenOutputVerdict)
            } else if abs(dcOffset) > dcOffsetWarn {
                flags.append("dc_offset"); raise(.warn, &writtenOutputVerdict)
            }
        }
        let verdict = worst(instabilityVerdict, writtenOutputVerdict)

        return AudioQCReport(
            instabilityVerdict: instabilityVerdict,
            writtenOutputVerdict: writtenOutputVerdict,
            verdict: verdict,
            flags: flags,
            rmsDBFS: rmsDBFS,
            dcOffset: dcOffset,
            peak: Double(metrics.rawPeak),
            clippedSamples: clipped,
            hotSamples: hot,
            nonFiniteSamples: metrics.nonFiniteSamples,
            clickEvents: clicks,
            longestSilenceMS: longestSilenceMS,
            durationSeconds: durationSeconds,
            firstNonFiniteSample: metrics.firstNonFiniteSample,
            firstClipSample: metrics.firstClipSample,
            longestSilenceStartMS: longestSilenceStartMS,
            chunkQC: chunkQC
        )
    }

    /// Build a per-chunk audio-QC snapshot from raw float samples. Uses a private
    /// limiter instance so the global session limiter's state is untouched. Sample
    /// indices in the report are absolute from the start of the generation.
    private static func makeAudioQCChunkReport(
        chunkIndex: Int,
        frameOffset: Int,
        samples: [Float],
        sampleRate: Int
    ) -> AudioQCChunkReport {
        var limiter = PCM16StreamLimiter()
        var destination: [Int16] = []
        limiter.append(samples, into: &destination)
        let metrics = limiter.metrics
        let durationSeconds = sampleRate > 0 ? Double(samples.count) / Double(sampleRate) : 0
        let report = Self.makeAudioQCReport(
            metrics: metrics,
            sampleRate: sampleRate,
            durationSeconds: durationSeconds,
            expectedPauseCount: 0
        )
        let frameOffsetMS = sampleRate > 0
            ? Int(Double(frameOffset) * 1000 / Double(sampleRate))
            : 0
        return AudioQCChunkReport(
            chunkIndex: chunkIndex,
            frameOffset: frameOffset,
            frameCount: samples.count,
            verdict: report.verdict,
            flags: report.flags,
            rmsDBFS: report.rmsDBFS,
            peak: report.peak,
            clippedSamples: report.clippedSamples,
            hotSamples: report.hotSamples,
            nonFiniteSamples: report.nonFiniteSamples,
            clickEvents: report.clickEvents,
            longestSilenceMS: report.longestSilenceMS,
            durationSeconds: durationSeconds,
            firstNonFiniteSample: report.firstNonFiniteSample.map { $0 + frameOffset },
            firstClipSample: report.firstClipSample.map { $0 + frameOffset },
            longestSilenceStartMS: report.longestSilenceStartMS.map { $0 + frameOffsetMS }
        )
    }

    /// The text's *interior* pause budget for the punctuation-aware dropout check:
    /// the number of sentence/clause boundaries (maximal runs of pause punctuation,
    /// so "..." or ", " count once), excluding a trailing terminal — that final
    /// mark ends the clip and produces no interior silence. The model emits a
    /// prosodic pause at each interior boundary, so this is the count of long
    /// interior silences that is *expected* and benign. Short text with no interior
    /// punctuation gets a budget of 0, so any long interior pause there is flagged.
    static func expectedPauseCount(in text: String) -> Int {
        let pausePunctuation: Set<Character> = [
            ".", ",", ";", ":", "!", "?", "…", "—",
            "。", "、", "，", "；", "：", "！", "？",
        ]
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        var count = 0
        var inRun = false
        for character in trimmed {
            if pausePunctuation.contains(character) {
                if !inRun { count += 1; inRun = true }
            } else {
                inRun = false
            }
        }
        // Drop the trailing terminal boundary (no interior silence follows it).
        if let last = trimmed.last, pausePunctuation.contains(last), count > 0 {
            count -= 1
        }
        return count
    }

    /// Maps the owned Qwen3 per-chunk timings into the Codable
    /// `GenerationChunkTelemetry`, stamping the chunk index and the wall-clock
    /// arrival (ms and ns since the shared telemetry start clock).
    private func makeChunkTelemetry(
        chunkIndex: Int,
        timings: VocelloQwen3ChunkTimings,
        clock: NativeTelemetryClock?
    ) -> GenerationChunkTelemetry {
        let (arrivalMS, arrivalNS) = clock?.now() ?? (0, 0)
        return GenerationChunkTelemetry(
            chunkIndex: chunkIndex,
            arrivalMS: max(0, arrivalMS),
            arrivalNS: arrivalNS,
            talkerForwardMS: timings.talkerForwardMS,
            codePredictorMS: timings.codePredictorMS,
            audioDecoderMS: timings.audioDecoderMS,
            streamStepEvalMS: timings.streamStepEvalMS,
            streamStepEvalEnqueueMS: timings.streamStepEvalEnqueueMS,
            streamStepEvalWaitMS: timings.streamStepEvalWaitMS,
            streamStepEOSReadMS: timings.streamStepEOSReadMS,
            audioChunkEvalMS: timings.audioChunkEvalMS,
            kvCacheDiagnostics: timings.kvCacheDiagnostics,
            mimiDecoderBreakdownMS: timings.mimiDecoderBreakdownMS
        )
    }

    /// Derive exact MLX enqueue/materialization instants from measured substage
    /// milliseconds anchored at the observed materialization uptime. Durations
    /// of zero are allowed when the producer measured zero — never invented.
    private static func mlxChunkInstants(
        timings: VocelloQwen3ChunkTimings?,
        materializedAtNS: UInt64
    ) -> (generatedAtNS: UInt64, enqueuedAtNS: UInt64, enqueueDurationNS: UInt64, materializationDurationNS: UInt64)? {
        guard let timings else { return nil }
        let enqueueDurationNS = UInt64(max(0, timings.streamStepEvalEnqueueMS) * 1_000_000.0)
        let waitDurationNS = UInt64(max(0, timings.streamStepEvalWaitMS) * 1_000_000.0)
        let evalDurationNS = UInt64(max(0, timings.streamStepEvalMS) * 1_000_000.0)
        let materializationDurationNS = waitDurationNS > 0
            ? waitDurationNS
            : (evalDurationNS > enqueueDurationNS ? evalDurationNS - enqueueDurationNS : 0)
        let enqueuedAtNS = materializedAtNS >= materializationDurationNS
            ? materializedAtNS - materializationDurationNS
            : materializedAtNS
        let generatedAtNS = enqueuedAtNS >= enqueueDurationNS
            ? enqueuedAtNS - enqueueDurationNS
            : enqueuedAtNS
        return (
            generatedAtNS,
            enqueuedAtNS,
            enqueueDurationNS,
            materializedAtNS >= enqueuedAtNS ? materializedAtNS - enqueuedAtNS : 0
        )
    }

    /// Headline backend throughput KPIs derived from data already gathered:
    /// audio duration, decode wall time (preferring the model's `.info` event,
    /// falling back to the stream stage-mark span), the realtime ratio, and
    /// tokens/sec. Computed once at generation end — no hot-path cost.
    private static func computeDerivedMetrics(
        audioSeconds: Double,
        stageMarks: [NativeTelemetryStageMark],
        info: VocelloQwen3GenerationInfo?,
        modelTimingsMS: [String: Int]
    ) -> [String: Double] {
        var metrics: [String: Double] = ["audioSeconds": audioSeconds]

        // Decode wall time: prefer the model's finalized token-loop total (includes
        // pipelined decoder drain after the `.info` event), else `.info.generateTime`,
        // else the streamStartup→streamGenerationEnded span (excludes WAV finalize).
        let decodeWallSeconds: Double
        if let tokenLoopMS = modelTimingsMS["qwen_token_loop_total"], tokenLoopMS > 0 {
            decodeWallSeconds = Double(tokenLoopMS) / 1_000
        } else if let info, info.generateTime > 0 {
            decodeWallSeconds = info.generateTime
        } else {
            let startMS = stageMarks.first { $0.stage == NativeRuntimeStage.streamStartup.rawValue }?.tMS
            let endMS = stageMarks.first {
                $0.stage == NativeRuntimeStage.streamGenerationEnded.rawValue
                    || $0.stage == NativeRuntimeStage.streamCompleted.rawValue
            }?.tMS
            if let startMS, let endMS, endMS > startMS {
                decodeWallSeconds = Double(endMS - startMS) / 1_000
            } else {
                decodeWallSeconds = 0
            }
        }
        if decodeWallSeconds > 0 {
            metrics["decodeWallSeconds"] = decodeWallSeconds
            metrics["audioSecondsPerWallSecond"] = audioSeconds / decodeWallSeconds
        }

        if let info {
            metrics["generatedTokenCount"] = Double(info.generationTokenCount)
            metrics["tokensPerSecond"] = info.tokensPerSecond
        } else if let codeCount = modelTimingsMS["qwen_generated_code_count"] {
            metrics["generatedTokenCount"] = Double(codeCount)
            if decodeWallSeconds > 0 {
                metrics["tokensPerSecond"] = Double(codeCount) / decodeWallSeconds
            }
        }
        return metrics
    }

    private static func stopTelemetrySampler(
        _ telemetrySampler: NativeTelemetrySampler?,
        stageMarks: [NativeTelemetryStageMark]
    ) async -> (summary: TelemetrySummary, samples: [TelemetrySample]) {
        guard let telemetrySampler else {
            return (TelemetrySummary.empty(stageMarks: stageMarks), [])
        }
        return await telemetrySampler.stop(stageMarks: stageMarks)
    }
}

/// Canonical persisted-output QC entry point for app-level batch validation and
/// deterministic tests. Generation passes its pre-limiter metrics internally so
/// the same report also retains upstream instability evidence.
public enum PersistedWAVAudioQCAnalyzer {
    public static func evaluate(
        url: URL,
        expectedPauseCount: Int = 0
    ) throws -> AudioQCReport {
        try StreamingExecutionContext.makePersistedWAVAudioQCReport(
            at: url,
            expectedPauseCount: expectedPauseCount
        )
    }

    /// Punctuation-derived pause budget for `expectedPauseCount:` — the same
    /// counter the engine's mandatory Fast QC applies to its request text.
    /// Callers validating persisted audio against known source text must pass
    /// this; a zero budget makes every natural sentence pause count as an
    /// excess dropout.
    public static func expectedPauseCount(in text: String) -> Int {
        StreamingExecutionContext.expectedPauseCount(in: text)
    }
}
