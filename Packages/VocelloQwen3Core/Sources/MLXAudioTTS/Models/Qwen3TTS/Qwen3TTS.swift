import CryptoKit
import Foundation
import Hub
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
import MLXNN
import os
import Tokenizers

// mlx-swift-lm 3.x declares its own `Tokenizer`/`TokenizerError` in MLXLMCommon; this runtime
// keeps using the swift-transformers implementations, so module-scope aliases pin bare names to
// the Tokenizers module and keep every reference unambiguous.
typealias Tokenizer = Tokenizers.Tokenizer
typealias TokenizerError = Tokenizers.TokenizerError

/// TEL-001: stage signposts correlate the Qwen hot path with typed chunk timings.
private enum Qwen3Signposts {
    static let subsystem = "com.qwenvoice.engine.qwen3"
    static let category = "generation"

    /// The log every decode-loop, chunk and tail interval is emitted on,
    /// through the allocation-free `os_signpost(.begin/.end, log:name:)` entry
    /// point with the exclusive signpost ID: `OSSignposter.beginInterval`
    /// allocates an interval-state object on every call, about 37 times per
    /// token (V-2, BT-06). Made once per generation, outside the token loop;
    /// the interval names are the ones `scripts/lib/trace_intervals.py`
    /// matches.
    static func makeStepLog() -> OSLog {
        OSLog(subsystem: subsystem, category: category)
    }
}

func qwen3TTSLog(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

/// SEC-7 (BKL-09): an error's domain and code only. A file-system error's
/// description names the model folder, a private path, and the package sits
/// below `DiagnosticPrivacy`, so its standard-error lines never carry it.
func qwen3TTSLogDescription(_ error: any Error) -> String {
    let error = error as NSError
    return "\(error.domain) \(error.code)"
}

/// F-03 (engine audit 2026-10-16): evaluates `array` and throws the error MLX
/// raised while evaluating it. Under an outer MLX error scope a failed
/// evaluation returns normally and leaves the buffer unfilled, and `asArray`
/// then traps on a nil base address; probing first turns that into a thrown
/// `MLXError` the facade maps to its typed failure. An already-evaluated
/// array costs one no-op `eval`. Synchronous, so async callers also get
/// `withError`'s synchronous overload.
func evalForReadback(_ array: MLXArray) throws {
    try withError { eval(array) }
}

actor Qwen3TTSGenerationGate {
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, Error>
    }

    private var isHeld = false
    private var waiters: [Waiter] = []
    private let afterTransferHook: (@Sendable () async -> Void)?

    init(afterTransferHook: (@Sendable () async -> Void)? = nil) {
        self.afterTransferHook = afterTransferHook
    }

    func acquire() async throws {
        let id = UUID()
        try Task.checkCancellation()

        if !isHeld {
            isHeld = true
            return
        }

        var gateAcquired = false
        do {
            try await withTaskCancellationHandler {
                try await waitForTurn(id: id)
                // waitForTurn only returns if the continuation was resumed normally
                // by release(), so the gate has been transferred to us.
                gateAcquired = true
                await afterTransferHook?()
            } onCancel: {
                Task { await self.cancelWaiter(id: id) }
            }
            // Keep the post-transfer cancellation check inside the scope whose
            // catch releases ownership. A cancellation between continuation
            // resume and acquire() return must never strand the gate held.
            try Task.checkCancellation()
        } catch {
            // Only release the gate if it was actually transferred to us. If we
            // were cancelled while still queued, cancelWaiter removed us and the
            // gate is still owned by the current generation.
            if gateAcquired {
                release()
            }
            throw error
        }

    }

    func release() {
        guard !waiters.isEmpty else {
            isHeld = false
            return
        }

        let waiter = waiters.removeFirst()
        waiter.continuation.resume()
    }

    var queuedWaiterCount: Int { waiters.count }

    nonisolated func withPermit<T: Sendable>(
        _ operation: @Sendable () async throws -> T
    ) async throws -> T {
        try await acquire()
        do {
            try Task.checkCancellation()
            let result = try await operation()
            await release()
            return result
        } catch {
            await release()
            throw error
        }
    }

    private func waitForTurn(id: UUID) async throws {
        try Task.checkCancellation()
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            guard !Task.isCancelled else {
                continuation.resume(throwing: CancellationError())
                return
            }
            waiters.append(Waiter(id: id, continuation: continuation))
        }
    }

    private func cancelWaiter(id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        let waiter = waiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }
}

enum Qwen3LearnedComponentWeights {
    static func requireNonEmpty(
        _ count: Int,
        component: String
    ) throws {
        guard count > 0 else {
            throw AudioGenerationError.invalidInput(
                "Requested learned component '\(component)' has no verified weights."
            )
        }
    }
}

struct Qwen3StreamChunkSchedule: Sendable {
    /// The codec runs at 12.5 frames per second.
    static let codecFrameRateHz = 12.5

    /// The codec frames a streaming interval stands for, at least one. It inverts
    /// `VocelloQwen3StreamChunkConfiguration.compatibilityStreamingInterval`
    /// (`Double(frames) / 12.5`), so it rounds: truncation lost a frame for 37 of the
    /// chunk sizes 1-512 (engine audit A-15). It is not the conversion for a raw tier
    /// interval: the product maps those to frames by truncating
    /// (`StreamChunkPolicy.currentShippingDefault`), and 0.6 s is 7 frames there, 8 here.
    static func codecFrames(forStreamingInterval interval: Double) -> Int {
        max(1, Int((interval * codecFrameRateHz).rounded()))
    }

    let firstChunkSize: Int
    let laterChunkSize: Int
    private(set) var pendingCount = 0
    private(set) var emittedChunkCount = 0
    private(set) var peakPendingCount = 0

    init(firstChunkSize: Int, laterChunkSize: Int) {
        self.firstChunkSize = max(1, firstChunkSize)
        self.laterChunkSize = max(1, laterChunkSize)
    }

    var requiredChunkSize: Int {
        emittedChunkCount == 0 ? firstChunkSize : laterChunkSize
    }

    mutating func append() -> Bool {
        pendingCount += 1
        peakPendingCount = max(peakPendingCount, pendingCount)
        return pendingCount >= requiredChunkSize
    }

    mutating func didEmit() {
        precondition(pendingCount <= requiredChunkSize, "pending stream retention exceeded its bounded schedule")
        pendingCount = 0
        emittedChunkCount += 1
    }
}

// MARK: - Qwen3TTS Model

public final class Qwen3TTSModel: Module, SpeechGenerationModel, Qwen3OptimizedSpeechGenerationModel, Qwen3PreparedQualityGenerationModel, Qwen3SuspendingSpeechGenerationModel, Qwen3CodecTraceReplayModel, Qwen3CodecRoundTripModel, Qwen3CustomVoicePrewarmDepthControlling, SpeechGenerationModelDiagnosticsProvider, @unchecked Sendable {
    private static let productionMinimumGeneratedCodeTokensBeforeEOS = 2

    let config: Qwen3TTSModelConfig
    let talker: Qwen3TTSTalkerForConditionalGeneration
    /// Gated load-time diagnostic (`QVOICE_TALKER_KV_QUANT`); nil in production.
    let talkerKVQuantBits: Int?
    /// Silence appended to a clone reference before the codec encodes it:
    /// none in production since 2026-11-11, as upstream; half a second under
    /// the gated `QWENVOICE_REFERENCE_PADDING=half-second` (A-12, RF-52).
    let referenceTrailingSilenceSamples: Int
    /// A streamed transcript-backed clone primes the decoder with the
    /// reference's codes before its own (A-04, RF-52): on in production since
    /// 2026-11-12, off under the gated `QWENVOICE_CLONE_DECODER_HISTORY=cold`.
    let streamedCloneDecoderPriming: Bool
    /// A clone target in Han or kana follows the reference transcript with no
    /// separator under the gated `QWENVOICE_ICL_TARGET_SPACE=spaced-scripts`
    /// (A-11, RF-52); production puts one space before every target.
    let iclTargetSpaceOnlyBeforeSpacedScripts: Bool
    /// A transcript-backed clone reference's silent edges are trimmed and it is
    /// faded in and out under the gated `QWENVOICE_REFERENCE_EDGES=trimmed`
    /// (G-07, RF-52); audio-only prompts and production take it as given.
    let referenceEdgesTrimmed: Bool
    var speakerEncoder: Qwen3TTSSpeakerEncoder?
    var speechTokenizer: Qwen3TTSSpeechTokenizer?
    var tokenizer: Tokenizer?
    var preparedKey: String?
    let diagnosticsLock = NSLock()
    var storedLoadTimingsMS: [String: Int] = [:]
    var storedLoadBooleanFlags: [String: Bool] = [:]
    var storedPreparationTimingsMS: [String: Int] = [:]
    var storedPreparationBooleanFlags: [String: Bool] = [:]
    var storedPreparationStringFlags: [String: String] = [:]
    var storedGenerationIntrospection: Qwen3GenerationIntrospectionSummary?
    private let generationGate = Qwen3TTSGenerationGate()

    public var sampleRate: Int { config.sampleRate }
    public var loadTimingsMS: [String: Int] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedLoadTimingsMS
    }

    public var loadBooleanFlags: [String: Bool] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedLoadBooleanFlags
    }

    public var latestPreparationTimingsMS: [String: Int] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationTimingsMS
    }

    public var latestPreparationBooleanFlags: [String: Bool] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationBooleanFlags
    }

    public var latestPreparationStringFlags: [String: String] {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedPreparationStringFlags
    }

    public var latestGenerationIntrospection: Qwen3GenerationIntrospectionSummary? {
        diagnosticsLock.lock()
        defer { diagnosticsLock.unlock() }
        return storedGenerationIntrospection
    }

    public func resetPreparationDiagnostics() {
        diagnosticsLock.lock()
        storedPreparationTimingsMS = [:]
        storedPreparationBooleanFlags = [:]
        storedPreparationStringFlags = [:]
        storedGenerationIntrospection = nil
        diagnosticsLock.unlock()
    }

    public var defaultGenerationParameters: GenerateParameters {
        GenerateParameters(
            maxTokens: 2048,
            temperature: 0.9,
            topP: 1.0,
            repetitionPenalty: 1.05
        )
    }

    var supportsCustomInstructionControl: Bool {
        !(config.ttsModelSize == "0b6" && config.ttsModelType == "custom_voice")
    }

    private func trimmedInstruction(_ instruct: String?) -> String? {
        guard let instruct else { return nil }
        let trimmed = Qwen3ChatTemplateText.preparedForTemplate(instruct)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func customVoiceInstruction(_ instruct: String?) -> String? {
        guard supportsCustomInstructionControl else { return nil }
        return trimmedInstruction(instruct)
    }

    private func conditioningCacheKey(for mode: String) -> String? {
        guard let preparedKey else { return nil }
        return "\(preparedKey)|\(mode)"
    }

    private func decoderBucketCacheKey() -> String? {
        guard let preparedKey else { return nil }
        return "\(preparedKey)|decoder_buckets|4,1,2,3"
    }

    private func decoderBucketCacheHit() -> Bool {
        guard let cacheKey = decoderBucketCacheKey() else { return false }
        return Qwen3TTSStreamingDecoderBucketCache.shared.contains(cacheKey)
    }

    func resolvedLanguageIdentifier(language: String, speaker: String? = nil) -> Int? {
        guard let talkerConfig = config.talkerConfig else { return nil }

        let normalizedLanguage = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let normalizedSpeaker = speaker?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        if (normalizedLanguage == "auto" || normalizedLanguage == "chinese"),
           let normalizedSpeaker,
           let dialect = talkerConfig.spkIsDialect?[normalizedSpeaker],
           let dialectLanguageID = talkerConfig.codecLanguageId?[dialect] {
            return dialectLanguageID
        }

        guard normalizedLanguage != "auto" else {
            return nil
        }
        return talkerConfig.codecLanguageId?[normalizedLanguage]
    }

    private func speakerTokenEmbeddings(for speaker: String?) throws -> MLXArray? {
        guard let talkerConfig = config.talkerConfig else { return nil }
        guard let speaker else { return nil }

        let speakerIDs = try Self.speakerTokenIDs(for: speaker, in: talkerConfig.spkId)
        let tokenIDs = MLXArray(speakerIDs.map(Int32.init)).reshaped(1, -1)
        return talker.getInputEmbeddings()(tokenIDs)
    }

    /// The codec token ids of a CustomVoice speaker. P05-05: an empty or blank
    /// speaker is refused like an unknown one; returning no token used to build
    /// the prefix without a speaker slot, an unconditioned voice that still
    /// reported success.
    static func speakerTokenIDs(for speaker: String, in table: [String: [Int]]?) throws -> [Int] {
        let normalizedSpeaker = speaker.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalizedSpeaker.isEmpty else {
            throw AudioGenerationError.invalidInput("Qwen3 Custom Voice requires a speaker")
        }
        guard let speakerIDs = table?[normalizedSpeaker], !speakerIDs.isEmpty else {
            throw AudioGenerationError.modelNotInitialized(
                "Unsupported Qwen3 speaker '\(speaker)'"
            )
        }
        return speakerIDs
    }

    private func prefixCacheKeyForCustomVoice(language: String, speaker: String, instruct: String?) -> String? {
        conditioningCacheKey(
            for: Qwen3ConditioningPrefixCacheKey.customVoice(
                language: language,
                speaker: speaker,
                instruction: instruct
            )
        )
    }

    private func prefixCacheKeyForVoiceDesign(language: String, voiceDescription: String) -> String? {
        conditioningCacheKey(
            for: Qwen3ConditioningPrefixCacheKey.voiceDesign(
                language: language,
                voiceDescription: voiceDescription
            )
        )
    }

    private func buildConditioningPrefix(
        language: String,
        speaker: String?,
        instruct: String?,
        cacheKey: String?
    ) throws -> (CachedConditioningPrefix, Bool, Int, Int) {
        let prefixCache = Qwen3TTSConditioningPrefixCache.shared
        if let cacheKey,
           let cachedPrefix = prefixCache.cachedPrefix(for: cacheKey) {
            return (cachedPrefix, true, 0, 0)
        }

        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let prefixTokenizeStartedAt = ContinuousClock.now

        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(try talker.embedText(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        let languageId = resolvedLanguageIdentifier(language: language, speaker: speaker)
        let codecPrefill: [Int32] = if let languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(languageId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        if let speakerEmbeds = try speakerTokenEmbeddings(for: speaker) {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerEmbeds, codecPrefixSuffix], axis: 1)
        } else {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, codecPrefixSuffix], axis: 1)
        }

        let assistantPrefix = "<|im_start|>assistant\n"
        let assistantPrefixIDs = MLXArray(tokenizer.encode(text: assistantPrefix).map(Int32.init)).reshaped(1, -1)
        let instructIDs: MLXArray?
        if let instruct = trimmedInstruction(instruct) {
            let instructText = "<|im_start|>user\n\(instruct)<|im_end|>\n"
            instructIDs = MLXArray(tokenizer.encode(text: instructText).map(Int32.init)).reshaped(1, -1)
        } else {
            instructIDs = nil
        }
        let prefixTokenizeMS = prefixTokenizeStartedAt.elapsedMilliseconds

        let prefixEmbedBuildStartedAt = ContinuousClock.now
        let roleEmbed = talker.textProjection(try talker.embedText(assistantPrefixIDs))

        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecPrefixEmbed[0..., ..<(-1), 0...]

        let instructEmbed: MLXArray?
        if let instructIDs {
            instructEmbed = talker.textProjection(try talker.embedText(instructIDs))
        } else {
            instructEmbed = nil
        }

        let inputPrefixEmbeds = if let instructEmbed {
            concatenated([instructEmbed, roleEmbed, combinedEmbed], axis: 1)
        } else {
            concatenated([roleEmbed, combinedEmbed], axis: 1)
        }
        let codecLastEmbed = codecPrefixEmbed[0..., (-1)..., 0...]
        let prefix = CachedConditioningPrefix(
            inputPrefixEmbeds: inputPrefixEmbeds,
            codecLastEmbed: codecLastEmbed,
            ttsEosEmbed: ttsEosEmbed,
            ttsPadEmbed: ttsPadEmbed
        )
        if let cacheKey {
            prefixCache.storePrefix(prefix, for: cacheKey)
        }
        return (prefix, false, prefixTokenizeMS, prefixEmbedBuildStartedAt.elapsedMilliseconds)
    }

    func prepareInputs(
        text: String,
        prefix: CachedConditioningPrefix
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        textPrepareMS: Int,
        targetTokenCount: Int
    ) {
        guard let tokenizer else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer not loaded")
        }

        let textPrepareStartedAt = ContinuousClock.now
        let text = Qwen3ChatTemplateText.preparedForTemplate(text)
        let targetTokenCount = tokenizer.encode(text: text).count
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map(Int32.init)).reshaped(1, -1)
        let textEmbed = talker.textProjection(try talker.embedText(inputIds))
        try Self.validateChatTemplateTokenCount(textEmbed.dim(1))

        let firstTextEmbed = textEmbed[0..., 3 ..< 4, 0...] + prefix.codecLastEmbed
        let trailingTextHidden = concatenated(
            [textEmbed[0..., 4 ..< (textEmbed.dim(1) - 5), 0...], prefix.ttsEosEmbed],
            axis: 1
        )
        let inputEmbeds = concatenated([prefix.inputPrefixEmbeds, firstTextEmbed], axis: 1)
        return (
            inputEmbeds,
            trailingTextHidden,
            prefix.ttsPadEmbed,
            textPrepareStartedAt.elapsedMilliseconds,
            targetTokenCount
        )
    }

    private func prepareFullTextNonStreamingInputs(
        text: String,
        prefix: CachedConditioningPrefix
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        textPrepareMS: Int,
        targetTokenCount: Int
    ) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let textPrepareStartedAt = ContinuousClock.now
        let text = Qwen3ChatTemplateText.preparedForTemplate(text)
        let targetTokenCount = tokenizer.encode(text: text).count
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map(Int32.init)).reshaped(1, -1)
        let textEmbed = talker.textProjection(try talker.embedText(inputIds))
        try Self.validateChatTemplateTokenCount(textEmbed.dim(1))

        let targetTextEmbed = concatenated(
            [textEmbed[0..., 3 ..< (textEmbed.dim(1) - 5), 0...], prefix.ttsEosEmbed],
            axis: 1
        )
        let codecPadIDs = MLXArray(
            Array(
                repeating: Int32(talkerConfig.codecPadId),
                count: targetTextEmbed.dim(1)
            )
        ).reshaped(1, -1)
        let fullTextOverlay = targetTextEmbed + talker.getInputEmbeddings()(codecPadIDs)
        let codecBosOverlay = prefix.ttsPadEmbed + prefix.codecLastEmbed
        let inputEmbeds = concatenated(
            [prefix.inputPrefixEmbeds, fullTextOverlay, codecBosOverlay],
            axis: 1
        )

        return (
            inputEmbeds,
            prefix.ttsPadEmbed,
            prefix.ttsPadEmbed,
            textPrepareStartedAt.elapsedMilliseconds,
            targetTokenCount
        )
    }

    // Internal so opt-in runtime diagnostics inspect the production conditioning
    // path without duplicating prompt assembly. Not part of the public facade.
    func prepareCustomVoiceInputs(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        timingsMS: [String: Int],
        targetTokenCount: Int
    ) {
        let resolvedInstruct = customVoiceInstruction(instruct)
        let prefixPrepareStartedAt = ContinuousClock.now
        let cacheKey = prefixCacheKeyForCustomVoice(
            language: language,
            speaker: speaker,
            instruct: resolvedInstruct
        )
        let (prefix, cacheHit, prefixTokenizeMS, prefixEmbedBuildMS) = try buildConditioningPrefix(
            language: language,
            speaker: speaker,
            instruct: resolvedInstruct,
            cacheKey: cacheKey
        )
        let prepared: (
            inputEmbeds: MLXArray,
            trailingTextHidden: MLXArray,
            ttsPadEmbed: MLXArray,
            textPrepareMS: Int,
            targetTokenCount: Int
        )
        switch textConditioningMode {
        case .streamingTrailingText:
            prepared = try prepareInputs(text: text, prefix: prefix)
        case .fullTextNonStreaming:
            prepared = try prepareFullTextNonStreamingInputs(text: text, prefix: prefix)
        }
        let customTimingsMS = [
            "custom_prefix_prepare": prefixPrepareStartedAt.elapsedMilliseconds,
            "custom_prefix_tokenize_ms": prefixTokenizeMS,
            "custom_prefix_embed_build_ms": prefixEmbedBuildMS,
            "custom_text_prepare_ms": prepared.textPrepareMS,
        ]
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            customTimingsMS,
            prepared.targetTokenCount
        )
    }

    private func prepareVoiceDesignInputs(
        text: String,
        language: String,
        voiceDescription: String,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        timingsMS: [String: Int],
        targetTokenCount: Int
    ) {
        let prefixPrepareStartedAt = ContinuousClock.now
        let cacheKey = prefixCacheKeyForVoiceDesign(
            language: language,
            voiceDescription: voiceDescription
        )
        let (prefix, cacheHit, prefixTokenizeMS, prefixEmbedBuildMS) = try buildConditioningPrefix(
            language: language,
            speaker: nil,
            instruct: voiceDescription,
            cacheKey: cacheKey
        )
        let prepared: (
            inputEmbeds: MLXArray,
            trailingTextHidden: MLXArray,
            ttsPadEmbed: MLXArray,
            textPrepareMS: Int,
            targetTokenCount: Int
        )
        switch textConditioningMode {
        case .streamingTrailingText:
            prepared = try prepareInputs(text: text, prefix: prefix)
        case .fullTextNonStreaming:
            prepared = try prepareFullTextNonStreamingInputs(text: text, prefix: prefix)
        }
        let designTimingsMS = [
            "design_prefix_prepare": prefixPrepareStartedAt.elapsedMilliseconds,
            "design_prefix_tokenize_ms": prefixTokenizeMS,
            "design_prefix_embed_build_ms": prefixEmbedBuildMS,
            "design_text_prepare_ms": prepared.textPrepareMS,
        ]
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            designTimingsMS,
            prepared.targetTokenCount
        )
    }

    /// CONV-21 (engine audit F-04/F-05): mlx-swift 0.32 compiles the
    /// sampler's kernels at first use (the inverse-CDF categorical, top-k's
    /// partition, top-p's sort and cumulative sum, the suppression and
    /// penalty scatters), and the greedy argMax prewarm never reaches them, so
    /// the first take after an update paid about 1.5 s on an M6. Draws once
    /// from the talker's and the code predictor's logits through the
    /// production sampler, with and without top-p, on a private random state
    /// that no take reads; the draws are evaluated with the prewarm and then
    /// discarded, so no output changes.
    static func productionSamplerWarmDraws(
        talkerLogits: MLXArray,
        codeLogits: MLXArray?,
        eosTokenId: Int,
        suppressTokens: [Int]
    ) -> [MLXArray] {
        withRandomState(MLXRandom.RandomState(seed: 0)) {
            var draws: [MLXArray] = []
            for topP: Float in [1.0, 0.95] {
                draws.append(sampleToken(
                    talkerLogits,
                    temperature: 0.9,
                    topP: topP,
                    topK: 50,
                    repetitionPenalty: 1.05,
                    // One penalized id and then several, as a take's second step
                    // and later steps hold: MLX picks different binary kernels.
                    generatedTokenIDs: topP < 1 ? [0, 1] : [0],
                    suppressTokens: suppressTokens,
                    eosTokenId: eosTokenId,
                    reinsertsEOSAfterFiltering: !Qwen3ReferenceParity.production.filtersEOS
                ))
                if let codeLogits {
                    draws.append(sampleToken(codeLogits, temperature: 0.9, topP: topP, topK: 50))
                }
            }
            return draws
        }
    }

    private func warmPreparedInputs(
        _ inputEmbedsInit: MLXArray,
        trailingTextHidden: MLXArray? = nil,
        ttsPadEmbed: MLXArray? = nil,
        inputPreparationMS: Int,
        booleanFlags: [String: Bool] = [:],
        additionalTimingsMS: [String: Int] = [:],
        preparationEvalTimingKey: String? = nil,
        streamStepEvalTimingKey: String? = nil,
        streamStepWarmBooleanFlag: String? = nil,
        precompileDecoderBuckets: Bool = true,
        memoryPolicy: Qwen3RequestMemoryPolicy = .compatibilityDefault,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        _ = isolation
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        // DA-04 E4-02 backstop: every caller's input preparation already needs
        // the talker config, so this only guards a future caller that does not.
        guard let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Talker config not loaded")
        }
        defer {
            Memory.clearCache()
        }

        let cache: [any KVCache]
        if let talkerKVWindow = memoryPolicy.talkerKVGeneratedWindow {
            // Sliding-window talker KV (constrained tiers): keep = the conditioning
            // prefill length (control + full text, always at the front of the
            // sequence), so only old generated audio-codec tokens rotate out.
            cache = talker.makeRotatingCache(
                keep: inputEmbedsInit.dim(1), window: talkerKVWindow
            )
        } else {
            cache = talker.makeCache(kvQuantBits: talkerKVQuantBits)
        }
        let codeCache = talker.codePredictor.makeCache()
        let (logits, hidden) = talker(inputEmbedsInit, cache: cache)
        let nextToken = argMax(
            logits[0..., (-1)..., 0...].squeezed(axis: 1),
            axis: -1,
            keepDims: true
        )
        let eosTokenArray = MLXArray([Int32(talkerConfig.codecEosTokenId)]).reshaped(1, 1)
        let isEOS = nextToken .== eosTokenArray

        let codeHidden = hidden[0..., (-1)..., 0...]
        var codeTokens = [nextToken]
        var lastCodeLogits: MLXArray?

        for layerCache in codeCache {
            _ = layerCache.trim(layerCache.offset)
        }

        if talkerConfig.numCodeGroups > 1 {
            for codeIdx in 0 ..< talkerConfig.numCodeGroups - 1 {
                let codeInput: MLXArray
                if codeIdx == 0 {
                    let code0Embed = talker.getInputEmbeddings()(nextToken)
                    codeInput = concatenated([codeHidden, code0Embed], axis: 1)
                } else {
                    codeInput = talker.codePredictor.codecEmbedding[codeIdx - 1](codeTokens.last!)
                }

                let (codeLogits, _, _) = talker.codePredictor(
                    codeInput,
                    cache: codeCache,
                    generationStep: codeIdx
                )
                let nextCode = argMax(
                    codeLogits[0..., (-1)..., 0...].squeezed(axis: 1),
                    axis: -1,
                    keepDims: true
                )
                codeTokens.append(nextCode)
                lastCodeLogits = codeLogits
            }
        }
        let samplerWarmDraws = Self.productionSamplerWarmDraws(
            talkerLogits: logits,
            codeLogits: lastCodeLogits,
            eosTokenId: talkerConfig.codecEosTokenId,
            suppressTokens: Array(max(0, talkerConfig.vocabSize - 1024) ..< talkerConfig.vocabSize)
                .filter { $0 != talkerConfig.codecEosTokenId }
        )

        let allCodes = concatenated(codeTokens, axis: 1)
        let codesChunk = stacked([allCodes], axis: 1)
        let codesForDecoder = codesChunk.transposed(0, 2, 1)
        let decoderStartedAt = ContinuousClock.now
        let decoded = speechTokenizer.decoder.streamingStep(codesForDecoder).squeezed(axis: 1)
        let firstDecoderStepMS = decoderStartedAt.elapsedMilliseconds
        var preparationBooleanFlags = booleanFlags
        let decoderBucketWarmStartedAt = ContinuousClock.now
        let decoderBucketCacheHit: Bool
        let decoderBucketWarmMS: Int
        if precompileDecoderBuckets {
            decoderBucketCacheHit = try precompileStreamingDecoderBuckets(with: codesForDecoder)
            decoderBucketWarmMS = decoderBucketCacheHit ? 0 : decoderBucketWarmStartedAt.elapsedMilliseconds
        } else {
            decoderBucketCacheHit = self.decoderBucketCacheHit()
            decoderBucketWarmMS = 0
            preparationBooleanFlags["decoder_bucket_precompile_skipped"] = true
        }
        preparationBooleanFlags["decoder_bucket_cache_hit"] = decoderBucketCacheHit
        speechTokenizer.decoder.resetStreamingState()
        let preparationEvalStartedAt = ContinuousClock.now
        eval([logits, hidden, allCodes, codesForDecoder, decoded] + samplerWarmDraws)
        var timingsMS = [
            "prepare_inputs": inputPreparationMS,
            "first_decoder_step": firstDecoderStepMS,
            "decoder_bucket_warm": decoderBucketWarmMS,
        ].merging(additionalTimingsMS) { _, rhs in rhs }
        if let preparationEvalTimingKey {
            timingsMS[preparationEvalTimingKey] = preparationEvalStartedAt.elapsedMilliseconds
        }
        if let streamStepEvalTimingKey,
           let trailingTextHidden,
           let ttsPadEmbed
        {
            let nextTextEmbed: MLXArray
            if trailingTextHidden.dim(1) > 0 {
                nextTextEmbed = trailingTextHidden[0..., 0 ..< 1, 0...]
            } else {
                nextTextEmbed = ttsPadEmbed
            }

            var codecEmbed = talker.getInputEmbeddings()(nextToken)
            for (index, code) in codeTokens.dropFirst().enumerated() {
                codecEmbed = codecEmbed + talker.codePredictor.codecEmbedding[index](code)
            }

            let nextInputEmbeds = nextTextEmbed + codecEmbed
            let streamStepWarmStartedAt = ContinuousClock.now
            eval(nextInputEmbeds, isEOS)
            timingsMS[streamStepEvalTimingKey] = streamStepWarmStartedAt.elapsedMilliseconds
            if let streamStepWarmBooleanFlag {
                preparationBooleanFlags[streamStepWarmBooleanFlag] = true
            }
        }
        storePreparationTimingsMS(timingsMS)
        mergePreparationBooleanFlags(preparationBooleanFlags)
    }

    @discardableResult
    private func precompileStreamingDecoderBuckets(with codesForDecoder: MLXArray) throws -> Bool {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }

        if let cacheKey = decoderBucketCacheKey(),
           Qwen3TTSStreamingDecoderBucketCache.shared.contains(cacheKey) {
            speechTokenizer.decoder.resetStreamingState()
            return true
        }

        for bucketSize in [4, 1, 2, 3] {
            speechTokenizer.decoder.resetStreamingState()
            let bucketCodes = concatenated(
                Array(repeating: codesForDecoder, count: bucketSize),
                axis: 2
            )
            let decoded = speechTokenizer.decoder.streamingStep(bucketCodes)
            eval(bucketCodes, decoded)
        }
        speechTokenizer.decoder.resetStreamingState()
        if let cacheKey = decoderBucketCacheKey() {
            Qwen3TTSStreamingDecoderBucketCache.shared.insert(cacheKey)
        }
        return false
    }

    public func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await prepareCustomVoice(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct,
            generationParameters: generationParameters,
            memoryPolicy: memoryPolicy,
            customPrewarmDepth: nil,
            isolation: isolation
        )
    }

    public func prepareCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        customPrewarmDepth: String?,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        let (inputEmbedsInit, trailingTextHidden, ttsPadEmbed, prefixCacheHit, customPrefixPrepareMS, _) = try prepareCustomVoiceInputs(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct
        )
        let prewarmDepth = Qwen3CustomVoicePrewarmDepth.resolve(rawValue: customPrewarmDepth)
        try await warmPreparedInputs(
            inputEmbedsInit,
            trailingTextHidden: trailingTextHidden,
            ttsPadEmbed: ttsPadEmbed,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "prefix_cache_hit": prefixCacheHit,
                "custom_prefix_cache_hit": prefixCacheHit,
                "custom_speaker_conditioning_used": true,
            ].merging(prewarmDepth.booleanFlags) { _, rhs in rhs },
            additionalTimingsMS: customPrefixPrepareMS,
            preparationEvalTimingKey: "custom_prewarm_eval_ms",
            streamStepEvalTimingKey: prewarmDepth.warmsStreamStep ? "custom_stream_step_warm_ms" : nil,
            streamStepWarmBooleanFlag: "custom_stream_step_prewarmed",
            precompileDecoderBuckets: prewarmDepth.precompileDecoderBuckets,
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    public func prepareVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        let (inputEmbedsInit, trailingTextHidden, ttsPadEmbed, prefixCacheHit, designPrefixPrepareMS, _) = try prepareVoiceDesignInputs(
            text: text,
            language: language,
            voiceDescription: voiceDescription
        )
        try await warmPreparedInputs(
            inputEmbedsInit,
            trailingTextHidden: trailingTextHidden,
            ttsPadEmbed: ttsPadEmbed,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "prefix_cache_hit": prefixCacheHit,
                "design_prefix_cache_hit": prefixCacheHit,
            ],
            additionalTimingsMS: designPrefixPrepareMS,
            preparationEvalTimingKey: "design_prewarm_eval_ms",
            streamStepEvalTimingKey: "design_stream_step_warm_ms",
            streamStepWarmBooleanFlag: "design_stream_step_prewarmed",
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    /// A transcript-backed clone reference as conditioning reads it, for the
    /// speaker embedding and the codec encode alike: as given in production,
    /// as upstream takes it; trimmed at its silent edges and faded in and out
    /// under the gated `QWENVOICE_REFERENCE_EDGES=trimmed` (G-07, RF-52).
    /// Audio-only (x-vector) prompts never pass through it.
    func conditioningReference(_ refAudio: MLXArray) throws -> MLXArray {
        guard referenceEdgesTrimmed else {
            return refAudio
        }
        return try Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(refAudio)
    }

    public func createVoiceClonePrompt(
        refAudio: MLXArray,
        refText: String?,
        xVectorOnlyMode: Bool
    ) throws -> Qwen3TTSVoiceClonePrompt {
        guard config.ttsModelType == "base" else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt creation requires the base model."
            )
        }

        let normalizedRefText = refText?.trimmingCharacters(in: .whitespacesAndNewlines)
        let iclMode = !xVectorOnlyMode
        if iclMode, normalizedRefText?.isEmpty ?? true {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 clone prompt creation requires a transcript when x_vector_only_mode is false."
            )
        }

        // G-07 reaches transcript-backed prompts only: the clone screen that
        // decides it measures those, so an audio-only prompt keeps its
        // reference as given whatever the key says.
        let reference = iclMode ? try conditioningReference(refAudio) : refAudio
        let speakerEmbedding = try extractSpeakerEmbedding(reference)
        if xVectorOnlyMode, speakerEmbedding == nil {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 x-vector clone prompt creation requires an initialized speaker encoder."
            )
        }
        let refCodes: MLXArray?
        if iclMode {
            guard let speechTokenizer, speechTokenizer.hasEncoder else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt creation requires an initialized speech tokenizer encoder."
                )
            }
            let refAudioForEncoder = try Qwen3TTSReferenceAudio.encoderInput(
                reference, trailingSilenceSamples: referenceTrailingSilenceSamples)
            let encoded = try speechTokenizer.encode(refAudioForEncoder)
            // F-07: evaluate the reference encode here, inside the caller's MLX
            // error scope and lease, instead of letting the lazy graph run later
            // in artifact persistence or the first take.
            eval(encoded)
            refCodes = encoded
        } else {
            refCodes = nil
        }

        return Qwen3TTSVoiceClonePrompt(
            refCodes: refCodes,
            speakerEmbedding: speakerEmbedding,
            refText: normalizedRefText,
            xVectorOnlyMode: xVectorOnlyMode,
            iclMode: iclMode
        )
    }

    public func prepareVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        isolation: isolated (any Actor)? = #isolation
    ) async throws {
        try await withGenerationGate(isolation: isolation) {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let startedAt = ContinuousClock.now
        // The clone prewarm does not prime the decoder (A-26): a proactive
        // prime stops only when its token is revoked, which a priming loop
        // would not see, so priming here could keep submitting GPU work after
        // the app deactivates (BG-01). The first streamed take of a reference
        // primes it, and later takes restore that state.
        let inputEmbedsInit = try prepareVoiceCloneInputs(
            text: text,
            voiceClonePrompt: voiceClonePrompt,
            language: language
        ).inputEmbeds
        try await warmPreparedInputs(
            inputEmbedsInit,
            inputPreparationMS: startedAt.elapsedMilliseconds,
            booleanFlags: [
                "clone_prompt_used": true,
            ],
            memoryPolicy: memoryPolicy,
            isolation: isolation
        )
        }
    }

    public func prepareForGeneration(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws {
        try await withGenerationGate {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        let instruct = voice
        let lang = language ?? "auto"
        let inputPreparationStartedAt = ContinuousClock.now

        let inputEmbedsInit: MLXArray
        let preparationBooleanFlags: [String: Bool]
        let additionalPreparationTimingsMS: [String: Int]
        if let refAudio,
           let refText,
           speechTokenizer.hasEncoder
        {
            let reference = try conditioningReference(refAudio)
            let speakerEmbedding = try extractSpeakerEmbedding(reference)
            inputEmbedsInit = try prepareICLGenerationInputs(
                text: text,
                refAudio: reference,
                refText: refText,
                speakerEmbedding: speakerEmbedding,
                language: lang
            ).inputEmbeds
            preparationBooleanFlags = [:]
            additionalPreparationTimingsMS = [:]
        } else {
            let prepared = try prepareVoiceDesignInputs(
                text: text,
                language: lang,
                voiceDescription: instruct ?? ""
            )
            inputEmbedsInit = prepared.inputEmbeds
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "design_prefix_cache_hit": prepared.prefixCacheHit,
            ]
            additionalPreparationTimingsMS = prepared.timingsMS
        }

        try await warmPreparedInputs(
            inputEmbedsInit,
            inputPreparationMS: inputPreparationStartedAt.elapsedMilliseconds,
            booleanFlags: preparationBooleanFlags,
            additionalTimingsMS: additionalPreparationTimingsMS,
            preparationEvalTimingKey: preparationBooleanFlags["design_prefix_cache_hit"] == true || !additionalPreparationTimingsMS.isEmpty
                ? "design_prewarm_eval_ms"
                : nil
        )
        }
    }

    convenience init(config: Qwen3TTSModelConfig) {
        let talkerConfig = config.talkerConfig ?? {
            let json = "{}".data(using: .utf8)!
            return try! JSONDecoder().decode(Qwen3TTSTalkerConfig.self, from: json)
        }()
        self.init(
            config: config,
            talker: Qwen3TTSTalkerForConditionalGeneration(config: talkerConfig),
            speakerEncoder: config.ttsModelType == "base"
                ? Qwen3TTSSpeakerEncoder(config: config.speakerEncoderConfig)
                : nil
        )
    }

    init(
        config: Qwen3TTSModelConfig,
        talker: Qwen3TTSTalkerForConditionalGeneration,
        speakerEncoder: Qwen3TTSSpeakerEncoder?,
        talkerKVQuantBits: Int? = nil,
        referenceTrailingSilenceSamples: Int = Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples,
        streamedCloneDecoderPriming: Bool = true,
        iclTargetSpaceOnlyBeforeSpacedScripts: Bool = false,
        referenceEdgesTrimmed: Bool = false
    ) {
        self.config = config
        self.talker = talker
        self.talkerKVQuantBits = talkerKVQuantBits
        self.referenceTrailingSilenceSamples = referenceTrailingSilenceSamples
        self.streamedCloneDecoderPriming = streamedCloneDecoderPriming
        self.iclTargetSpaceOnlyBeforeSpacedScripts = iclTargetSpaceOnlyBeforeSpacedScripts
        self.referenceEdgesTrimmed = referenceEdgesTrimmed
        self.speakerEncoder = speakerEncoder
    }

    private func withGenerationGate<T: Sendable>(
        isolation: isolated (any Actor)? = #isolation,
        _ operation: () async throws -> T
    ) async throws -> T {
        _ = isolation
        try await generationGate.acquire()
        do {
            try Task.checkCancellation()
            let result = try await operation()
            await generationGate.release()
            return result
        } catch {
            await generationGate.release()
            throw error
        }
    }

    // MARK: - SpeechGenerationModel protocol

    public func generate(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) async throws -> MLXArray {
        try await withGenerationGate {
        guard speechTokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
        }

        // VoiceDesign: voice parameter is the instruct (voice description)
        let instruct = voice

        let samplingPolicy = Qwen3RequestSamplingPolicy.official(
            generationParameters,
            effectiveSeed: UInt64.random(in: UInt64.min ... UInt64.max)
        )
        let audio = try await samplingPolicy.runWithRandomState {
            try await generateVoiceDesign(
                text: text,
                instruct: instruct,
                language: language ?? "auto",
                refAudio: refAudio,
                refText: refText,
                samplingPolicy: samplingPolicy,
                memoryPolicy: .compatibilityDefault
            )
        }
        return audio
        }
    }

    public func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        generateStream(
            text: text,
            voice: voice,
            refAudio: refAudio,
            refText: refText,
            language: language,
            generationParameters: generationParameters,
            streamingInterval: 2.0
        )
    }

    public func generateStream(
        text: String,
        voice: String?,
        refAudio: MLXArray?,
        refText: String?,
        language: String?,
        generationParameters: GenerateParameters,
        streamingInterval: Double,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                guard speechTokenizer != nil else {
                    throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
                }
                guard tokenizer != nil else {
                    throw AudioGenerationError.modelNotInitialized("Text tokenizer not loaded")
                }

                // VoiceDesign: voice parameter is the instruct (voice description)
                let instruct = voice
                let lang = language ?? "auto"
                let samplingPolicy = Qwen3RequestSamplingPolicy.official(
                    generationParameters,
                    effectiveSeed: UInt64.random(in: UInt64.min ... UInt64.max)
                )
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: instruct,
                        language: lang,
                        refAudio: refAudio,
                        refText: refText,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: .compatibilityDefault,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: nil,
                        generationSpeedProfile: nil,
                        onToken: { tokenId in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token(tokenId))
                        },
                        onInfo: { info in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info(info))
                        },
                        onAudioChunk: { chunk in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio(materializing: chunk))
                        },
                        onAudioChunkTimings: enableChunkTimings ? { timings in
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings(timings))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateCustomVoiceQualityFirst(
            text: text,
            language: language,
            speaker: speaker,
            instruct: instruct,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateCustomVoiceQualityFirst(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: instruct,
                language: language,
                speaker: speaker,
                refAudio: nil,
                refText: nil,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    public func generateVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateVoiceDesignQualityFirst(
            text: text,
            language: language,
            voiceDescription: voiceDescription,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateVoiceDesignQualityFirst(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: voiceDescription,
                language: language,
                refAudio: nil,
                refText: nil,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    public func generateVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy
    ) async throws -> AudioGenerationCompletion {
        try await generateVoiceCloneQualityFirst(
            text: text,
            language: language,
            voiceClonePrompt: voiceClonePrompt,
            generationParameters: generationParameters,
            samplingPolicy: samplingPolicy,
            memoryPolicy: memoryPolicy,
            onPrepared: {},
            codecTraceSink: nil,
            isolation: #isolation
        )
    }

    public func generateVoiceCloneQualityFirst(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        onPrepared: @escaping @Sendable () async throws -> Void,
        codecTraceSink: Qwen3CodecTraceSink?,
        isolation: isolated (any Actor)?
    ) async throws -> AudioGenerationCompletion {
        try await withGenerationGate(isolation: isolation) {
        let generationInfo = OSAllocatedUnfairLock<AudioGenerationInfo?>(initialState: nil)
        let audio = try await samplingPolicy.runWithRandomState(isolation: isolation) {
            try await generateVoiceDesign(
                text: text,
                instruct: nil,
                language: language,
                speaker: nil,
                refAudio: nil,
                refText: nil,
                voiceClonePrompt: voiceClonePrompt,
                samplingPolicy: samplingPolicy,
                memoryPolicy: memoryPolicy,
                textConditioningMode: .fullTextNonStreaming,
                customVoiceProfile: nil,
                streamStepEvalPolicy: nil,
                generationSpeedProfile: nil,
                onInfo: { info in generationInfo.withLock { $0 = info } },
                codecTraceSink: codecTraceSink,
                onPrepared: onPrepared,
                isolation: isolation
            )
        }
        return AudioGenerationCompletion(
            audio: audio,
            info: generationInfo.withLock { $0 },
            finishReason: latestAudioGenerationFinishReason()
        )
        }
    }

    private func latestAudioGenerationFinishReason() -> AudioGenerationFinishReason {
        switch latestPreparationStringFlags["generation_end_reason"] {
        case "eos":
            return .eos
        case "token_cap":
            return .maxTokens
        case "failed":
            return .failed
        default:
            return .failed
        }
    }

    public func generateCustomVoiceStream(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile: String?,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: instruct,
                        language: language,
                        speaker: speaker,
                        refAudio: nil,
                        refText: nil,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        customVoiceProfile: customVoiceProfile,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio(materializing: $0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateVoiceDesignStream(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: voiceDescription,
                        language: language,
                        refAudio: nil,
                        refText: nil,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio(materializing: $0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    public func generateVoiceCloneStream(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool = false
    ) -> AsyncThrowingStream<AudioGeneration, Error> {
        let (stream, continuation) = AsyncThrowingStream<AudioGeneration, Error>.makeStream()
        let producerTask = Task { @Sendable [weak self] in
            guard let self else { return }
            do {
                try await withGenerationGate {
                try Task.checkCancellation()
                _ = try await samplingPolicy.runWithRandomState {
                    try await generateVoiceDesign(
                        text: text,
                        instruct: nil,
                        language: language,
                        speaker: nil,
                        refAudio: nil,
                        refText: nil,
                        voiceClonePrompt: voiceClonePrompt,
                        samplingPolicy: samplingPolicy,
                        memoryPolicy: memoryPolicy,
                        streamingInterval: streamingInterval,
                        streamStepEvalPolicy: streamStepEvalPolicy,
                        generationSpeedProfile: generationSpeedProfile,
                        onToken: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.token($0))
                        },
                        onInfo: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.info($0))
                        },
                        onAudioChunk: {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.audio(materializing: $0))
                        },
                        onAudioChunkTimings: enableChunkTimings ? {
                            guard !Task.isCancelled else { return }
                            continuation.yield(.chunkTimings($0))
                        } : nil
                    )
                }
                }
                continuation.finish()
            } catch {
                continuation.finish(throwing: error)
            }
        }
        continuation.onTermination = { @Sendable _ in
            producerTask.cancel()
        }
        return stream
    }

    // MARK: - Suspending materialized generation

    /// Runs Custom Voice generation in the caller's task. Audio is evaluated
    /// and copied to `[Float]` before the sink is awaited, so backpressure from
    /// the facade's frame-bounded channel suspends this actual token/decode
    /// producer without transferring an `MLXArray` to another task.
    public func produceCustomVoice(
        text: String,
        language: String,
        speaker: String,
        instruct: String?,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        customVoiceProfile: String?,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: instruct,
                    language: language,
                    speaker: speaker,
                    refAudio: nil,
                    refText: nil,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    customVoiceProfile: customVoiceProfile,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    public func produceVoiceDesign(
        text: String,
        language: String,
        voiceDescription: String,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: voiceDescription,
                    language: language,
                    refAudio: nil,
                    refText: nil,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    public func produceVoiceClone(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        generationParameters _: GenerateParameters,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double,
        streamStepEvalPolicy: String?,
        generationSpeedProfile: String?,
        enableChunkTimings: Bool,
        enableCodecTrace: Bool,
        sink: @escaping Qwen3MaterializedGenerationSink,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> AudioGenerationFinishReason {
        try await withGenerationGate(isolation: isolation) {
            try Task.checkCancellation()
            let finishReason = try await samplingPolicy.runWithRandomState(isolation: isolation) {
                _ = try await generateVoiceDesign(
                    text: text,
                    instruct: nil,
                    language: language,
                    speaker: nil,
                    refAudio: nil,
                    refText: nil,
                    voiceClonePrompt: voiceClonePrompt,
                    samplingPolicy: samplingPolicy,
                    memoryPolicy: memoryPolicy,
                    streamingInterval: streamingInterval,
                    streamStepEvalPolicy: streamStepEvalPolicy,
                    generationSpeedProfile: generationSpeedProfile,
                    materializedEventSink: sink,
                    emitMaterializedChunkTimings: enableChunkTimings,
                    emitMaterializedCodecTrace: enableCodecTrace,
                    isolation: isolation
                )
                return latestAudioGenerationFinishReason()
            }
            try Task.checkCancellation()
            return finishReason
        }
    }

    // MARK: - Decode chunk helper

    /// Full-text conditioning still decodes through Mimi incrementally. Keep
    /// the decoder partition small enough for constrained unified-memory
    /// devices; decoder partition invariance is covered by
    /// `Qwen3DecoderPartitionTests`.
    static let qualityFirstDecoderChunkFrames = 25

    /// Sample window of a quality-first decode, derived from explicit frame
    /// counts. Every codec frame decodes to exactly `upsampleRate` samples, so
    /// the generated take is `[reference, reference + generated) × upsampleRate`,
    /// clamped to what the decoder actually emitted. Code 0 is a legal codec
    /// token, so the window never counts non-zero codes (PA-13, DECODE-002).
    static func qualityFirstSampleRange(
        referenceFrameCount: Int,
        generatedFrameCount: Int,
        decodedSampleCount: Int,
        upsampleRate: Int
    ) -> Range<Int> {
        let available = max(0, decodedSampleCount)
        let rate = max(0, upsampleRate)
        let referenceFrames = max(0, referenceFrameCount)
        let generatedFrames = max(0, generatedFrameCount)
        let start = min(available, referenceFrames * rate)
        let end = min(available, max(start, (referenceFrames + generatedFrames) * rate))
        return start ..< end
    }

    /// A-04 (RF-52): decodes a clone reference's codes `[1, quantizers,
    /// frames]` through the streaming decoder and keeps none of their samples,
    /// leaving the decoder with the history a quality-first take's generated
    /// frames decode with. It decodes in the quality-first path's pieces, so a
    /// long reference never decodes in one burst; any partition leaves the
    /// same state (`Qwen3DecoderPartitionTests`). Returns the frames primed.
    static func primeStreamingDecoder(
        _ decoder: Qwen3TTSSpeechTokenizerDecoder,
        referenceCodes: MLXArray,
        pieceFrames: Int = Qwen3TTSModel.qualityFirstDecoderChunkFrames
    ) throws -> Int {
        let frames = referenceCodes.dim(2)
        for start in stride(from: 0, to: frames, by: max(1, pieceFrames)) {
            try Task.checkCancellation()
            let end = min(frames, start + max(1, pieceFrames))
            eval(decoder.streamingStep(referenceCodes[0..., 0..., start ..< end]))
        }
        return frames
    }

    /// A-26 (RF-52): primes as `primeStreamingDecoder` does, decoding each
    /// reference once per decoder. The first priming keeps a copy of the state
    /// it leaves in `primedStates`; a later one restores that copy, which
    /// leaves the decoder exactly as decoding the reference again would
    /// (`Qwen3QualityFirstDecodeWindowTests`). The decoder must be freshly
    /// reset. Returns the frames primed and whether a kept copy served them.
    static func primeStreamingDecoderReusingState(
        _ decoder: Qwen3TTSSpeechTokenizerDecoder,
        referenceCodes: MLXArray,
        primedStates: Qwen3TTSPrimedDecoderStateCache = .shared,
        pieceFrames: Int = Qwen3TTSModel.qualityFirstDecoderChunkFrames
    ) throws -> (frames: Int, reused: Bool) {
        let frames = referenceCodes.dim(2)
        guard frames > 0 else {
            return (0, false)
        }
        let reference = Qwen3TTSPrimedDecoderStateCache.referenceKey(
            referenceCodes: referenceCodes,
            pieceFrames: pieceFrames
        )
        if let snapshot = primedStates.snapshot(forReference: reference, decoder: decoder),
           decoder.restoreStreamingState(snapshot) {
            return (frames, true)
        }
        let primed = try primeStreamingDecoder(decoder, referenceCodes: referenceCodes, pieceFrames: pieceFrames)
        if let snapshot = decoder.streamingStateSnapshot() {
            primedStates.store(snapshot, forReference: reference, decoder: decoder)
        }
        return (primed, false)
    }

    /// Decode `[reference + generated]` codec frames on the bounded
    /// quality-first partition and return only the generated window.
    /// - Parameters:
    ///   - codes: Codec codes `[1, referenceFrameCount + generatedFrames, numCodeGroups]`
    ///   - referenceFrameCount: Leading in-context reference frames to cut (0 without ICL)
    ///   - chunkTokens: Tokens per decode chunk (controls decode granularity)
    /// - Returns: Evaluated generated waveform (1D)
    static func decodeQualityFirstWindow(
        _ speechTokenizer: Qwen3TTSSpeechTokenizer,
        codes: MLXArray,
        referenceFrameCount: Int,
        chunkTokens: Int = Qwen3TTSModel.qualityFirstDecoderChunkFrames
    ) -> MLXArray {
        var audioChunks = [MLXArray]()
        for chunk in speechTokenizer.streamingDecode(codes, chunkTokens: chunkTokens) {
            audioChunks.append(chunk)
        }
        var audio = concatenated(audioChunks, axis: -1)[0]

        let window = qualityFirstSampleRange(
            referenceFrameCount: referenceFrameCount,
            generatedFrameCount: codes.dim(1) - referenceFrameCount,
            decodedSampleCount: audio.dim(0),
            upsampleRate: speechTokenizer.decodeUpsampleRate
        )
        if window != 0 ..< audio.dim(0) {
            audio = audio[window]
        }

        eval(audio)
        return audio
    }

    private func decodeChunk(
        _ codes: MLXArray,
        referenceFrameCount: Int,
        chunkTokens: Int = Qwen3TTSModel.qualityFirstDecoderChunkFrames
    ) -> MLXArray {
        guard let speechTokenizer else { return MLXArray.zeros([1]) }
        return Self.decodeQualityFirstWindow(
            speechTokenizer,
            codes: codes,
            referenceFrameCount: referenceFrameCount,
            chunkTokens: chunkTokens
        )
    }

    public func replayCodecTrace(
        frames: [[Int32]],
        incrementalRanges: [Qwen3CodecFrameRange],
        memoryPolicy: Qwen3RequestMemoryPolicy = .compatibilityDefault
    ) throws -> Qwen3CodecReplayResult {
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        guard !frames.isEmpty, frames.count <= 8_192,
              let groupCount = frames.first?.count,
              groupCount > 0, groupCount <= 64,
              frames.allSatisfy({ $0.count == groupCount }) else {
            throw AudioGenerationError.invalidInput("Invalid bounded codec trace")
        }
        guard !incrementalRanges.isEmpty,
              incrementalRanges.first?.start == 0,
              incrementalRanges.last?.endExclusive == frames.count else {
            throw AudioGenerationError.invalidInput("Codec replay ranges are incomplete")
        }
        var expectedStart = 0
        for range in incrementalRanges {
            guard range.start == expectedStart,
                  range.endExclusive > range.start,
                  range.endExclusive <= frames.count else {
                throw AudioGenerationError.invalidInput("Codec replay ranges are not contiguous")
            }
            expectedStart = range.endExclusive
        }

        let flatCodes = frames.flatMap { $0 }
        let codes = MLXArray(flatCodes).reshaped([1, frames.count, groupCount])

        let incrementalAudio = try Self.replayDecoderArm(
            speechTokenizer.decoder, codes: codes, ranges: incrementalRanges,
            arm: .incremental, memoryPolicy: memoryPolicy
        )
        let fullRanges = stride(from: 0, to: frames.count, by: Self.qualityFirstDecoderChunkFrames).map {
            Qwen3CodecFrameRange(start: $0, endExclusive: min(frames.count, $0 + Self.qualityFirstDecoderChunkFrames))
        }
        var fullAudio = try Self.replayDecoderArm(
            speechTokenizer.decoder, codes: codes, ranges: fullRanges,
            arm: .full, memoryPolicy: memoryPolicy
        )
        // Same sample window as production quality-first decode (a trace
        // carries generated frames only, so there is no reference cut).
        let fullWindow = Self.qualityFirstSampleRange(
            referenceFrameCount: 0,
            generatedFrameCount: frames.count,
            decodedSampleCount: fullAudio.count,
            upsampleRate: speechTokenizer.decodeUpsampleRate
        )
        if fullWindow != fullAudio.indices {
            fullAudio = Array(fullAudio[fullWindow])
        }

        return Qwen3CodecReplayResult(
            incrementalAudio: incrementalAudio,
            fullAudio: fullAudio,
            sampleRate: sampleRate
        )
    }

    public var hasSpeechTokenizerEncoder: Bool {
        speechTokenizer?.hasEncoder ?? false
    }

    /// Diagnostic codec round trip (audio QC population N2). The encoder sees
    /// the clone path's codec input for a reference as given (`encoderInput`,
    /// with the model's trailing silence); it never trims edges, so it does
    /// not reproduce the codes of a take made under
    /// `QWENVOICE_REFERENCE_EDGES=trimmed` (G-07)
    /// and keeps every codebook it produces; the codes then decode through
    /// `replayDecoderArm` on the production non-streaming 25-frame schedule and
    /// sample window, the schedule the replay's `fullAudio` uses. The codes are
    /// materialized first and decoded from that CPU copy, so the audio is the
    /// replay decode of the returned codes. The caller trims the audio.
    public func codecRoundTrip(
        samples: [Float],
        memoryPolicy: Qwen3RequestMemoryPolicy = .compatibilityDefault
    ) throws -> Qwen3CodecRoundTripResult {
        guard let speechTokenizer, speechTokenizer.hasEncoder else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer encoder not loaded")
        }
        guard !samples.isEmpty else {
            throw AudioGenerationError.invalidInput("Empty codec round-trip input")
        }
        try Task.checkCancellation()
        let (flatCodes, frameCount, groupCount): ([Int32], Int, Int) = try autoreleasepool {
            let encoderInput = try Qwen3TTSReferenceAudio.encoderInput(
                MLXArray(samples), trailingSilenceSamples: referenceTrailingSilenceSamples)
            // [1, codebooks, frames] -> [1, frames, codebooks], the codec trace layout.
            let encoded = try speechTokenizer.encode(encoderInput).transposed(0, 2, 1)
            try evalForReadback(encoded)
            return (encoded.asArray(Int32.self), encoded.dim(1), encoded.dim(2))
        }
        if memoryPolicy.clearCacheOnStreamChunkEmit { Memory.clearCache() }
        guard frameCount > 0, frameCount <= 8_192, groupCount > 0, groupCount <= 64,
              flatCodes.count == frameCount * groupCount else {
            throw AudioGenerationError.invalidInput("Codec round-trip codes are out of bounds")
        }
        try Task.checkCancellation()
        let codes = MLXArray(flatCodes).reshaped([1, frameCount, groupCount])
        let ranges = stride(from: 0, to: frameCount, by: Self.qualityFirstDecoderChunkFrames).map {
            Qwen3CodecFrameRange(start: $0, endExclusive: min(frameCount, $0 + Self.qualityFirstDecoderChunkFrames))
        }
        var audio = try Self.replayDecoderArm(
            speechTokenizer.decoder, codes: codes, ranges: ranges,
            arm: .full, memoryPolicy: memoryPolicy, observe: { _ in }
        )
        let window = Self.qualityFirstSampleRange(
            referenceFrameCount: 0,
            generatedFrameCount: frameCount,
            decodedSampleCount: audio.count,
            upsampleRate: speechTokenizer.decodeUpsampleRate
        )
        if window != audio.indices {
            audio = Array(audio[window])
        }
        let frames = stride(from: 0, to: flatCodes.count, by: groupCount).map {
            Array(flatCodes[$0 ..< $0 + groupCount])
        }
        return Qwen3CodecRoundTripResult(codes: frames, audio: audio, sampleRate: sampleRate)
    }

    /// Diagnostic replay keeps only CPU samples after each materialization;
    /// neither arm retains a list of GPU outputs. Decoder context and the
    /// original/25-frame partitions remain intact until the arm terminates.
    static func replayDecoderArm(
        _ decoder: Qwen3TTSSpeechTokenizerDecoder,
        codes: MLXArray,
        ranges: [Qwen3CodecFrameRange],
        arm: CodecReplayMemoryObservation.Arm,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        observe: (CodecReplayMemoryObservation) throws -> Void = { try $0.writeToStandardError() }
    ) throws -> [Float] {
        decoder.resetStreamingState()
        defer {
            decoder.resetStreamingState()
            if memoryPolicy.clearCacheOnStreamChunkEmit { Memory.clearCache() }
        }
        try Task.checkCancellation()
        try observe(.capture(arm: arm, stage: .started, completedFrames: 0))
        var samples: [Float] = []
        for (index, range) in ranges.enumerated() {
            try Task.checkCancellation()
            // Release temporary arrays before clearing recyclable allocations.
            // The decoder's live KV/convolution state is deliberately retained.
            let chunk: [Float] = try autoreleasepool {
                let input = codes[0..., range.start ..< range.endExclusive, 0...].transposed(0, 2, 1)
                let decoded = decoder.streamingStep(input)[0, 0]
                try evalForReadback(decoded)
                return decoded.asArray(Float.self)
            }
            samples.append(contentsOf: chunk)
            let sampled = CodecReplayMemoryObservation.shouldSample(index: index, count: ranges.count)
            if sampled {
                try observe(.capture(arm: arm, stage: .materialized, completedFrames: range.endExclusive))
            }
            if memoryPolicy.clearCacheOnStreamChunkEmit { Memory.clearCache() }
            if sampled {
                try observe(.capture(arm: arm, stage: .afterCachePolicy, completedFrames: range.endExclusive))
            }
            try Task.checkCancellation()
        }
        decoder.resetStreamingState()
        if memoryPolicy.clearCacheOnStreamChunkEmit { Memory.clearCache() }
        try observe(.capture(arm: arm, stage: .finished, completedFrames: ranges.last?.endExclusive ?? 0))
        try Task.checkCancellation()
        return samples
    }

    // MARK: - VoiceDesign generation

    fileprivate func generateVoiceDesign(
        text: String,
        instruct: String?,
        language: String,
        speaker: String? = nil,
        refAudio: MLXArray?,
        refText: String?,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt? = nil,
        samplingPolicy: Qwen3RequestSamplingPolicy,
        memoryPolicy: Qwen3RequestMemoryPolicy,
        streamingInterval: Double = 2.0,
        textConditioningMode: Qwen3TextConditioningMode = .streamingTrailingText,
        customVoiceProfile explicitCustomVoiceProfile: String? = nil,
        streamStepEvalPolicy explicitStreamStepEvalPolicy: String? = nil,
        generationSpeedProfile explicitGenerationSpeedProfile: String? = nil,
        onToken: ((Int) -> Void)? = nil,
        onInfo: ((AudioGenerationInfo) -> Void)? = nil,
        onAudioChunk: ((MLXArray) -> Void)? = nil,
        onAudioChunkTimings: ((ChunkSubstageTimings) -> Void)? = nil,
        materializedEventSink: Qwen3MaterializedGenerationSink? = nil,
        emitMaterializedChunkTimings: Bool = false,
        emitMaterializedCodecTrace: Bool = false,
        codecTraceSink: Qwen3CodecTraceSink? = nil,
        onPrepared: (@Sendable () async throws -> Void)? = nil,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> MLXArray {
        _ = isolation
        guard let speechTokenizer, tokenizer != nil else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer or text tokenizer not loaded")
        }

        let temperature = samplingPolicy.talker.temperature
        let topK = samplingPolicy.talker.topK
        let topP = samplingPolicy.talker.topP
        let repetitionPenalty = samplingPolicy.repetitionPenalty
        let minP = samplingPolicy.talker.minP
        let maxTokens = samplingPolicy.maximumCodecTokens
        let subtalkerSampling = samplingPolicy.subtalker
        // Audio QC GEN-NOEOS (diagnostics only): nil on every production request.
        var eosSuppression = samplingPolicy.eosSuppressionFrames.map(Qwen3EOSSuppressionWindow.init(frames:))
        // RF-14 reference parity: `.production` (D1-D3 on) on every single
        // take; a long-form segment turns D1 off, and the other departures are
        // diagnostics only.
        let referenceParity = samplingPolicy.referenceParity
        // D1: streamed Custom and Design takes use the reference's full-text
        // layout unless the request keeps trailing text; clones ignore the
        // requested mode (see `recordedLabel`).
        let effectiveTextConditioningMode: Qwen3TextConditioningMode =
            referenceParity.fullTextConditioning ? .fullTextNonStreaming : textConditioningMode

        // DA-04 E4-02: a checkpoint loaded without `talker_config` builds its
        // talker from defaults, so fail here, typed, rather than trap.
        guard let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Talker config not loaded")
        }
        let isPureVoiceDesign = speaker == nil && refAudio == nil && voiceClonePrompt == nil
        let isDedicatedCustomVoice = speaker != nil && refAudio == nil && voiceClonePrompt == nil
        let isVoiceCloneGeneration = voiceClonePrompt != nil || refAudio != nil
        let streamingGenerationMode: Qwen3StreamingGenerationMode = {
            if isDedicatedCustomVoice {
                return .custom
            } else if isPureVoiceDesign {
                return .design
            } else if isVoiceCloneGeneration {
                return .clone
            }
            return .generic
        }()

        // Prepare inputs
        let inputEmbedsInit: MLXArray
        let trailingTextHidden: MLXArray
        let ttsPadEmbed: MLXArray
        let refCodes: MLXArray?
        let preparationBooleanFlags: [String: Bool]
        let preparationTimingsMS: [String: Int]
        let preparedTargetTokenCount: Int

        if let voiceClonePrompt {
            let prepared = try prepareVoiceCloneInputs(
                text: text,
                voiceClonePrompt: voiceClonePrompt,
                language: language
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = prepared.refCodes
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "clone_prompt_used": true,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = [:]
        } else if let refAudio,
           let refText,
           speechTokenizer.hasEncoder {
            let reference = try conditioningReference(refAudio)
            let speakerEmbedding = try extractSpeakerEmbedding(reference)
            let prepared = try prepareICLGenerationInputs(
                text: text,
                refAudio: reference,
                refText: refText,
                speakerEmbedding: speakerEmbedding,
                language: language
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = prepared.refCodes
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [:]
            preparationTimingsMS = [:]
        } else if let speaker {
            let prepared = try prepareCustomVoiceInputs(
                text: text,
                language: language,
                speaker: speaker,
                instruct: instruct,
                textConditioningMode: effectiveTextConditioningMode
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = nil
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "custom_prefix_cache_hit": prepared.prefixCacheHit,
                "custom_speaker_conditioning_used": true,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = prepared.timingsMS
        } else {
            let prepared = try prepareVoiceDesignInputs(
                text: text,
                language: language,
                voiceDescription: instruct ?? "",
                textConditioningMode: effectiveTextConditioningMode
            )
            inputEmbedsInit = prepared.inputEmbeds
            trailingTextHidden = prepared.trailingTextHidden
            ttsPadEmbed = prepared.ttsPadEmbed
            refCodes = nil
            preparedTargetTokenCount = prepared.targetTokenCount
            preparationBooleanFlags = [
                "prefix_cache_hit": prepared.prefixCacheHit,
                "design_prefix_cache_hit": prepared.prefixCacheHit,
                "decoder_bucket_cache_hit": decoderBucketCacheHit(),
            ]
            preparationTimingsMS = prepared.timingsMS
        }
        storePreparationBooleanFlags(preparationBooleanFlags)
        mergePreparationTimingsMS(preparationTimingsMS)
        let cloneInContextLearning: Bool? = if let voiceClonePrompt {
            voiceClonePrompt.iclMode
        } else if refAudio != nil, refText != nil, speechTokenizer.hasEncoder {
            true
        } else {
            nil
        }
        storePreparationStringFlags([
            "text_conditioning_mode": Qwen3TextConditioningMode.recordedLabel(
                requested: effectiveTextConditioningMode,
                cloneInContextLearning: cloneInContextLearning
            ),
        ])
        mergePreparationStringFlags(referenceParity.evidence)

        // Cap max tokens based on text length
        let customVoiceProfile = isDedicatedCustomVoice
            ? Qwen3CustomVoiceGenerationProfile.resolve(explicitProfile: explicitCustomVoiceProfile)
            : .baseline
        let generationSpeedProfile = Qwen3GenerationSpeedProfile.resolve(
            explicitProfile: explicitGenerationSpeedProfile
        )
        let tokenBudgetPolicy = generationSpeedProfile.tokenBudgetPolicy(
            mode: streamingGenerationMode,
            customVoiceProfile: customVoiceProfile
        )
        let effectiveMaxTokens = tokenBudgetPolicy.effectiveMaxTokens(
            defaultMaxTokens: maxTokens,
            targetTokenCount: preparedTargetTokenCount
        )
        let memoryClearCadence = memoryPolicy.tokenMemoryClearCadence
        let streamStepEvalPolicy = Qwen3StreamStepEvalPolicy.resolve(
            explicitPolicy: explicitStreamStepEvalPolicy
        )
        mergePreparationBooleanFlags(streamStepEvalPolicy.booleanFlags)
        mergePreparationBooleanFlags(generationSpeedProfile.booleanFlags)
        mergePreparationStringFlags([
            "generation_speed_profile": generationSpeedProfile.rawValue,
            "stream_step_eval_policy": streamStepEvalPolicy.rawValue,
            "token_budget_policy": tokenBudgetPolicy.name,
        ])
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            mergePreparationTimingsMS([
                "\(timingPrefix)_target_token_count": preparedTargetTokenCount,
                "\(timingPrefix)_effective_max_tokens": effectiveMaxTokens,
                "\(timingPrefix)_generation_profile_multiplier": tokenBudgetPolicy.maxTokenMultiplier,
                "\(timingPrefix)_generation_profile_min_tokens": tokenBudgetPolicy.minimumGeneratedCodes,
                "memory_clear_cadence": memoryClearCadence,
            ])
        } else {
            mergePreparationTimingsMS([
                "memory_clear_cadence": memoryClearCadence,
            ])
        }
        if isDedicatedCustomVoice {
            mergePreparationTimingsMS([
                "custom_post_first_stream_chunk_multiplier": customVoiceProfile.postFirstStreamChunkMultiplier,
            ])
            mergePreparationBooleanFlags(customVoiceProfile.booleanFlags)
            mergePreparationStringFlags([
                "custom_voice_profile": customVoiceProfile.rawValue,
            ])
        }

        if let materializedEventSink {
            try Task.checkCancellation()
            try await materializedEventSink(.prepared)
            try Task.checkCancellation()
        }
        if let onPrepared {
            try Task.checkCancellation()
            try await onPrepared()
            try Task.checkCancellation()
        }

        // Initialize cache and timing. The span feeds tokensPerSecond, so it is
        // monotonic (ContinuousClock), never wall-clock Date().
        let startTime = ContinuousClock.now
        let cache: [any KVCache]
        if let talkerKVWindow = memoryPolicy.talkerKVGeneratedWindow {
            // Sliding-window talker KV (constrained tiers): keep = the conditioning
            // prefill length (control + full text, always at the front of the
            // sequence), so only old generated audio-codec tokens rotate out.
            cache = talker.makeRotatingCache(
                keep: inputEmbedsInit.dim(1), window: talkerKVWindow
            )
        } else {
            cache = talker.makeCache(kvQuantBits: talkerKVQuantBits)
        }
        let isStreaming = onAudioChunk != nil || materializedEventSink != nil
        // Quality-first generation must not retain one lazy MLX graph per
        // sampled codec frame. On iOS a 280-character request accumulated the
        // graphs until final decode and crossed the process limit. Store only
        // materialized codec IDs; full-text conditioning remains unchanged.
        var generatedCodecFrames = [[Int32]]()
        if !isStreaming {
            generatedCodecFrames.reserveCapacity(effectiveMaxTokens)
        }
        var pendingStreamCodes = [MLXArray]()
        var generatedCodeCount = 0
        let eosTokenId = talkerConfig.codecEosTokenId

        // Suppress special tokens
        let suppressTokens = (talkerConfig.vocabSize - 1024 ..< talkerConfig.vocabSize)
            .filter { $0 != eosTokenId }

        // Streaming decode state
        let streamingChunkSize = Qwen3StreamChunkSchedule.codecFrames(forStreamingInterval: streamingInterval)
        let postFirstStreamingChunkSize = streamingGenerationMode.postFirstStreamingChunkSize(
            baseChunkSize: streamingChunkSize,
            customVoiceProfile: customVoiceProfile
        )
        var streamChunkSchedule = Qwen3StreamChunkSchedule(
            firstChunkSize: streamingChunkSize,
            laterChunkSize: postFirstStreamingChunkSize
        )
        /// Cumulative codec frames already emitted as streaming PCM chunks.
        var emittedCodecFrameCount: UInt64 = 0
        if isStreaming {
            pendingStreamCodes.reserveCapacity(max(streamingChunkSize, postFirstStreamingChunkSize))
        }
        // Hot-loop span totals accumulate at the clock's resolution and are
        // rounded to whole milliseconds once, at export (audit #61/#95):
        // rounding every step first sent each sub-millisecond span to zero
        // before it was summed. Each span's signpost interval opens and
        // closes around the same code as its clock reads, so a trace's
        // per-name interval sums line up with these totals.
        var tokenLoopTotal = Duration.zero
        var talkerForwardTotal = Duration.zero
        var sampleFirstCodebookTotal = Duration.zero
        var codePredictorTotal = Duration.zero
        var codePredictorStepTotal = Duration.zero
        var samplePredictedCodebookTotal = Duration.zero
        var codecEmbeddingAssemblyTotal = Duration.zero
        var streamingDecoderTotal = Duration.zero
        var streamingDecoderCallCount = 0
        var mimiDecoderBreakdownTotal = MimiDecoderStepTimings()
        // Snapshot of the cumulative span totals at the
        // moment of the previous chunk's emit, so the per-chunk
        // sub-stage delta passed to `onAudioChunkTimings` reflects ONLY
        // the work done since the previous chunk (or since generation
        // start for the first chunk).
        var lastChunkTalkerForward = Duration.zero
        var lastChunkCodePredictor = Duration.zero
        var lastChunkStreamingDecoder = Duration.zero
        var lastChunkMimiDecoderBreakdown = MimiDecoderStepTimings()
        // TEL-001: mode-agnostic counters feed one per-chunk delta path.
        var streamStepEvalTotal = Duration.zero
        var streamStepEvalEnqueueTotal = Duration.zero
        var streamStepEvalWaitTotal = Duration.zero
        // V-2: the first blocking read of each step (the sampled token). Under
        // `.pipelined` this is where the host waits for the step's GPU work.
        var streamStepTokenReadTotal = Duration.zero
        var streamStepEOSReadTotal = Duration.zero
        var audioChunkEvalTotal = Duration.zero
        var lastChunkStreamStepEval = Duration.zero
        var lastChunkStreamStepEvalEnqueue = Duration.zero
        var lastChunkStreamStepEvalWait = Duration.zero
        var lastChunkStreamStepEOSRead = Duration.zero
        var lastChunkAudioChunkEval = Duration.zero
        // TEL-001: track peak KV-cache footprint across the generation.
        var peakKVCacheSeqLength = 0
        var peakKVCacheFootprintMB = 0.0
        var kvCacheTypeAtPeak = talker.model.latestCreatedCacheType
        var designStreamStepEvalTotal = Duration.zero
        var designStreamStepEOSReadTotal = Duration.zero
        var designAudioChunkEvalTotal = Duration.zero
        var designGenerationStepsBeforeFirstChunk: Int?
        var designFirstChunkDecoderTokens: Int?
        var customStreamStepEvalTotal = Duration.zero
        var customStreamStepEOSReadTotal = Duration.zero
        var customAudioChunkEvalTotal = Duration.zero
        var customGenerationStepsBeforeFirstChunk: Int?
        var customFirstChunkDecoderTokens: Int?
        var cloneStreamStepEvalTotal = Duration.zero
        var cloneStreamStepEOSReadTotal = Duration.zero
        var cloneAudioChunkEvalTotal = Duration.zero
        var cloneGenerationStepsBeforeFirstChunk: Int?
        var cloneFirstChunkDecoderTokens: Int?
        var generationEndReason = "token_cap"
        var cacheClearCount = 0
        func tokenLoopAttributedTotal() -> Duration {
            talkerForwardTotal
                + sampleFirstCodebookTotal
                + codePredictorTotal
                + codecEmbeddingAssemblyTotal
                + streamStepEvalTotal
                + streamStepTokenReadTotal
                + streamStepEOSReadTotal
                + streamingDecoderTotal
                + audioChunkEvalTotal
        }
        // The named spans inside the token loop, read when the loop exits: the
        // final flush, tail decode and tail eval run after the loop and must
        // not hide in-loop time that no span covers.
        var tokenLoopAttributedAtExit: Duration?
        // Audit #61 fix 2: the awaited sink hand-offs inside the token loop
        // (the `.token`, `.codecFrame`, `.chunkTimings` and `.audio` sends,
        // the pipelined flush's sends and the codec-trace sink). Hand-offs
        // after the loop exits (the final flush, `.info`, the tail chunk) are
        // not counted. Their own keys; they stay out of
        // `tokenLoopAttributedTotal()`, so `qwen_token_loop_unattributed`
        // keeps its meaning and still contains this time.
        var tokenLoopSinkHandoffTotal = Duration.zero
        var tokenLoopSinkHandoffCount = 0
        func recordSinkHandoff(since startedAt: ContinuousClock.Instant) {
            guard tokenLoopAttributedAtExit == nil else { return }
            tokenLoopSinkHandoffTotal += startedAt.elapsed
            tokenLoopSinkHandoffCount += 1
        }
        func qwenTokenLoopUnattributedMS() -> Int {
            let attributed = tokenLoopAttributedAtExit ?? tokenLoopAttributedTotal()
            return max(Duration.zero, tokenLoopTotal - attributed).roundedMilliseconds
        }

        func qwenHotLoopTimingsMS() -> [String: Int] {
            var timings: [String: Int] = [
                "qwen_token_loop_total": tokenLoopTotal.roundedMilliseconds,
                "qwen_talker_forward_total": talkerForwardTotal.roundedMilliseconds,
                "qwen_sample_first_codebook_total": sampleFirstCodebookTotal.roundedMilliseconds,
                "qwen_code_predictor_total": codePredictorTotal.roundedMilliseconds,
                "qwen_code_predictor_step_total": codePredictorStepTotal.roundedMilliseconds,
                "qwen_sample_predicted_codebook_total": samplePredictedCodebookTotal.roundedMilliseconds,
                "qwen_codec_embedding_assembly_total": codecEmbeddingAssemblyTotal.roundedMilliseconds,
                "qwen_stream_step_eval_total": streamStepEvalTotal.roundedMilliseconds,
                "qwen_stream_step_eval_enqueue_total": streamStepEvalEnqueueTotal.roundedMilliseconds,
                "qwen_stream_step_eval_wait_total": streamStepEvalWaitTotal.roundedMilliseconds,
                "qwen_stream_step_token_read_total": streamStepTokenReadTotal.roundedMilliseconds,
                "qwen_stream_step_eos_read_total": streamStepEOSReadTotal.roundedMilliseconds,
                "qwen_token_loop_unattributed": qwenTokenLoopUnattributedMS(),
                "qwen_token_loop_sink_handoff_total": tokenLoopSinkHandoffTotal.roundedMilliseconds,
                "qwen_token_loop_sink_handoff_count": tokenLoopSinkHandoffCount,
                "qwen_stream_decoder_total": streamingDecoderTotal.roundedMilliseconds,
                "qwen_audio_chunk_eval_total": audioChunkEvalTotal.roundedMilliseconds,
                "qwen_stream_decoder_calls": streamingDecoderCallCount,
                "qwen_generated_code_count": generatedCodeCount,
                "qwen_talker_kv_cache_offset": cache.first?.offset ?? 0,
                "cache_clear_count": cacheClearCount,
                "memory_clear_cadence": memoryClearCadence,
            ]
            // Only emit peak KV-cache keys when the peak tracker was actually
            // updated (i.e., telemetry was active). Prevents false-zero readings.
            if peakKVCacheSeqLength > 0 {
                timings["qwen_talker_kv_cache_peak_seq"] = peakKVCacheSeqLength
                timings["qwen_talker_kv_cache_peak_mb"] = Int(peakKVCacheFootprintMB)
            }
            return timings
        }

        // Phase 2a: build a per-chunk KV-cache diagnostic snapshot and keep
        // running peak totals for the final hot-loop summary.
        //
        // NOTE: the footprint is a dense bfloat16 estimate. Quantized KV caches
        // (e.g. 4-bit) and rotating-window caches are NOT reflected in the byte
        // count, so treat this as a coarse trend/regression signal, not exact
        // allocated bytes.
        func makeChunkKVCacheDiagnostics() -> KVCacheDiagnostics? {
            let effectiveSeqLength = cache.first?.offset ?? 0
            let layerCount = talkerConfig.numHiddenLayers
            let headCount = talkerConfig.numAttentionHeads
            let kvHeadCount = talkerConfig.numKeyValueHeads
            let headDim = talkerConfig.headDim
            let dtypeBytes = 2
            let footprintMB = estimatedKVCacheFootprintMB(
                layers: layerCount,
                heads: kvHeadCount,
                seq: effectiveSeqLength,
                headDim: headDim,
                dtypeBytes: dtypeBytes
            )
            if footprintMB > peakKVCacheFootprintMB {
                peakKVCacheFootprintMB = footprintMB
                peakKVCacheSeqLength = effectiveSeqLength
                kvCacheTypeAtPeak = talker.model.latestCreatedCacheType
            }
            return KVCacheDiagnostics(
                cacheType: talker.model.latestCreatedCacheType,
                effectiveSeqLength: effectiveSeqLength,
                layerCount: layerCount,
                headCount: headCount,
                kvHeadCount: kvHeadCount,
                headDim: headDim,
                dtypeBytes: dtypeBytes,
                estimatedFootprintMB: footprintMB
            )
        }

        func clearGenerationCache() {
            Memory.clearCache()
            cacheClearCount += 1
        }
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            let postFirstMultiplier = streamingGenerationMode.postFirstStreamChunkMultiplier(
                customVoiceProfile: customVoiceProfile
            )
            mergePreparationTimingsMS([
                "\(timingPrefix)_initial_stream_chunk_size": streamingChunkSize,
                "\(timingPrefix)_post_first_stream_chunk_size": postFirstStreamingChunkSize,
                "\(timingPrefix)_post_first_stream_chunk_multiplier": postFirstMultiplier,
            ])
            mergePreparationBooleanFlags([
                "\(timingPrefix)_stream_chunk_growth_enabled": postFirstStreamingChunkSize > streamingChunkSize,
            ])
        }

        var trailingIdx = 0
        var inputEmbeds = inputEmbedsInit
        let eosTokenArray = MLXArray([Int32(eosTokenId)]).reshaped(1, 1)
        // Per-generation CP execution state: the compiled per-pass plan and
        // its baked pass-0 mask replace the eager per-frame graph rebuild
        // (Stage 1 P3); the plan owns its K/V buffers, so no KVCacheSimple is
        // allocated for the streaming CP.
        let codePredictorStepConstants = CodePredictorStepConstants()
        // Every per-step, per-chunk and tail interval goes through this log's
        // allocation-free entry point: no per-token allocation, lock or string
        // formatting.
        let stepSignpostLog = Qwen3Signposts.makeStepLog()
        // AQ-04 engine introspection: fixed-state bookkeeping fed values the
        // step already holds, summarized once when the loop exits (including a
        // cancelled or failed one). The talker vocabulary is the codec codebook
        // followed by the 1 024 special ids, EOS among them.
        var generationIntrospector = Qwen3GenerationIntrospector()
        let introspectionCodecVocabularySize = talkerConfig.vocabSize - 1024
        // The step scalars need EOS outside the codebook and inside the
        // vocabulary; a configuration without that records token cycles and
        // seams only. The diagnostic `.deferred` policy evaluates nothing with
        // the step, so the scalars would add their own syncs there: skipped.
        // The scalar graph is compiled once per generation, so each step adds
        // a few fused kernels to its own evaluation, not a dozen ops.
        let introspectionStepScalars: (@Sendable ([MLXArray]) -> [MLXArray])? =
            introspectionCodecVocabularySize > 0
                && eosTokenId >= introspectionCodecVocabularySize
                && eosTokenId < talkerConfig.vocabSize
                && streamStepEvalPolicy != .deferred
            ? Self.compiledIntrospectionScalars(
                codecVocabularySize: introspectionCodecVocabularySize,
                eosTokenId: eosTokenId
            )
            : nil
        storeGenerationIntrospection(nil)
        defer {
            storeGenerationIntrospection(generationIntrospector.summary())
        }

        if isStreaming {
            speechTokenizer.decoder.resetStreamingState()
        }
        defer {
            if isStreaming {
                speechTokenizer.decoder.resetStreamingState()
            }
        }
        // A-04 (RF-52): the decoder hears the reference before the take, so
        // the take's first frames decode with the history the quality-first
        // path and upstream's ICL decode give them. The reference's samples
        // are discarded; only the decoder's state is kept, and A-26 restores
        // it from the reference's earlier priming when one is kept.
        if isStreaming, streamedCloneDecoderPriming, let refCodes {
            let primingStartedAt = ContinuousClock.now
            let priming = try Self.primeStreamingDecoderReusingState(speechTokenizer.decoder, referenceCodes: refCodes)
            // The pieces' buffers would otherwise stay cached through prefill.
            if !priming.reused, memoryPolicy.clearCacheOnStreamChunkEmit { clearGenerationCache() }
            mergePreparationTimingsMS([
                "qwen_clone_decoder_priming_ms": primingStartedAt.elapsed.roundedMilliseconds,
                "qwen_clone_decoder_primed_frames": priming.frames,
            ])
            mergePreparationBooleanFlags([
                "clone_decoder_primed": true,
                "clone_decoder_priming_reused": priming.reused,
            ])
        }

        let suppressTokensWithEOS = suppressTokens + [eosTokenId]
        let samplerScratch = Qwen3SamplerScratch(vocabSize: talkerConfig.vocabSize)
        samplerScratch.prepareSuppressPairs(
            base: suppressTokens,
            withEOS: suppressTokensWithEOS,
            dtype: .float32
        )
        // Separate scratch for the code-predictor sampler (different vocab; no
        // suppress pairs prepared, so suppression stays disabled there exactly
        // as before — this only caches the arange/zeros/-inf rows that were
        // re-allocated 14× per frame). Sized lazily from the first CP logits.
        var codePredictorScratch: Qwen3SamplerScratch?

        // Stage 1 P2a (`.pipelined` policy, materialized-sink path only): a
        // stream chunk's compute is submitted with asyncEval at assembly and
        // its materialization + channel sends run at the top of the NEXT token
        // step, after that step's graph is submitted — so the host/channel
        // work overlaps in-flight GPU compute. The flush point precedes the
        // next `.token` read, so the event order on the channel is exactly the
        // pre-pipelining order, and materialization still happens in this task
        // before the awaited send (lossless-channel contract unchanged).
        struct PendingMaterializedStreamChunk {
            let audioChunk: MLXArray
            let timings: ChunkSubstageTimings?
        }
        var pendingMaterializedChunk: PendingMaterializedStreamChunk?
        func flushPendingMaterializedChunk() async throws {
            guard let pending = pendingMaterializedChunk else { return }
            pendingMaterializedChunk = nil
            guard let materializedEventSink else { return }
            let flushEvalStartedAt = ContinuousClock.now
            // Once per chunk under `.pipelined`, on the same allocation-free
            // entry point as every loop interval.
            os_signpost(.begin, log: stepSignpostLog, name: "Audio Chunk Flush")
            eval(pending.audioChunk)
            os_signpost(.end, log: stepSignpostLog, name: "Audio Chunk Flush")
            // Flush wait lands in the running audio-chunk-eval totals (its
            // chunk's own delta closed at assembly; this shifts attribution by
            // at most one chunk in the diagnostic breakdown). Its own interval
            // name keeps it apart from the assembly-time `Audio Chunk Eval`.
            let flushElapsed = flushEvalStartedAt.elapsed
            audioChunkEvalTotal += flushElapsed
            if isPureVoiceDesign {
                designAudioChunkEvalTotal += flushElapsed
            } else if isDedicatedCustomVoice {
                customAudioChunkEvalTotal += flushElapsed
            } else if isVoiceCloneGeneration {
                cloneAudioChunkEvalTotal += flushElapsed
            }
            try Task.checkCancellation()
            try evalForReadback(pending.audioChunk)
            let materializedSamples = pending.audioChunk.asArray(Float.self)
            if let timings = pending.timings {
                let handoffStartedAt = ContinuousClock.now
                try await materializedEventSink(.chunkTimings(timings))
                recordSinkHandoff(since: handoffStartedAt)
                try Task.checkCancellation()
            }
            let handoffStartedAt = ContinuousClock.now
            try await materializedEventSink(.audio(materializedSamples))
            recordSinkHandoff(since: handoffStartedAt)
            try Task.checkCancellation()
        }

        lastTakeFrameFunctionFrames = 0
        for _ in 0 ..< effectiveMaxTokens {
            try Task.checkCancellation()
            let tokenLoopStartedAt = ContinuousClock.now
            defer {
                tokenLoopTotal += tokenLoopStartedAt.elapsed
            }

            // Forward pass through talker
            let talkerForwardStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Talker Forward")
            let (logits, hidden) = talker(inputEmbeds, cache: cache)
            os_signpost(.end, log: stepSignpostLog, name: "Talker Forward")
            talkerForwardTotal += talkerForwardStartedAt.elapsed

            let allowsEOS = eosSuppression?.allowsEOS(
                generatedCodeCount: generatedCodeCount,
                productionMinimum: Self.productionMinimumGeneratedCodeTokensBeforeEOS
            ) ?? (generatedCodeCount >= Self.productionMinimumGeneratedCodeTokensBeforeEOS)

            // Sample first codebook token
            let sampleFirstCodebookStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Sample First Codebook")
            var nextToken = Self.sampleToken(
                logits,
                temperature: temperature,
                topP: topP,
                topK: topK,
                repetitionPenalty: repetitionPenalty,
                eosTokenId: allowsEOS ? eosTokenId : nil,
                minP: minP,
                scratch: samplerScratch,
                allowsEOS: allowsEOS,
                castsLogitsToFloat32: referenceParity.float32Sampling,
                reinsertsEOSAfterFiltering: !referenceParity.filtersEOS,
                observe: samplerObserver
            )
            // GEN-NOEOS (internal diagnostics only; `eosSuppression` is nil on
            // every production request): read this step's token before the
            // code predictor, and when the talker first samples EOS, redraw the
            // step from the same logits with EOS unavailable and open the hold.
            if eosSuppression?.watchesForFirstEOS(allowsEOS: allowsEOS) == true,
               (nextToken .== eosTokenArray).item(Bool.self) {
                eosSuppression?.open(atGeneratedCodeCount: generatedCodeCount)
                nextToken = Self.sampleToken(
                    logits,
                    temperature: temperature,
                    topP: topP,
                    topK: topK,
                    repetitionPenalty: repetitionPenalty,
                    eosTokenId: nil,
                    minP: minP,
                    scratch: samplerScratch,
                    allowsEOS: false,
                    castsLogitsToFloat32: referenceParity.float32Sampling,
                    observe: samplerObserver
                )
            }
            os_signpost(.end, log: stepSignpostLog, name: "Sample First Codebook")
            sampleFirstCodebookTotal += sampleFirstCodebookStartedAt.elapsed

            // Defer sync to the eval boundary with inputEmbeds.
            let isEOS = nextToken .== eosTokenArray
            // AQ-04: the entropy and EOS probability of this step's talker
            // distribution, two scalars built from the logits already computed
            // and evaluated with the step below (no extra synchronization).
            let stepIntrospection: (entropy: MLXArray, eosProbability: MLXArray)? =
                introspectionStepScalars.flatMap { scalars in
                    // The last position only, so the prefill step ([1, L, V])
                    // and later steps ([1, 1, V]) share one compiled trace.
                    let values = scalars([logits[0..., (-1)..., 0...]])
                    // Under an MLX error handler a failed compile or apply
                    // returns no outputs; the step then reaches its typed
                    // failure at the next error check instead of trapping.
                    guard values.count == 2 else { return nil }
                    return (entropy: values[0], eosProbability: values[1])
                }
            // Measured do-NOT (2026-07-26): submitting the talker+sampling
            // subgraph here with asyncEval to overlap the CP-loop graph build
            // regressed warm RTF (custom/long −3.9%) — the extra command
            // buffer + fusion break cost more launches than the overlap
            // saved. Record `stage1-p2aii-early-submit`
            // (macos-engine-20260726-060659-99b59f93).

            // Generate remaining codebook tokens with code predictor. Stage 1
            // P3: the streaming path replays per-pass compiled functions (the
            // per-frame position sequence is identical, so pass-indexed
            // traces are exact); the compiled plan owns its K/V buffers, so
            // the eager codeCache is neither written nor trimmed here.
            var codeTokens = [nextToken]
            let codeHidden = hidden[0..., (-1)..., 0...]
            // RF-46: when the subtalker stage is the plain temperature and
            // top-k sampler, the frame's passes sample inside one compiled
            // function (`runFrame` below). A sampler observer needs the
            // logits, so it keeps the per-pass plan and the eager sampler.
            let codePredictorPlan = codePredictorStepConstants.compiledPlan(
                for: talker.codePredictor,
                dtype: codeHidden.dtype,
                sampling: samplerObserver == nil
                    ? CompiledPassSampling.eligible(
                        stage: subtalkerSampling,
                        castsLogitsToFloat32: referenceParity.float32Sampling,
                        vocabSize: talker.codePredictor.config.vocabSize
                    )
                    : nil
            )

            let codePredictorStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Code Predictor Loop")
            // RF-46: with a stage the passes can sample, the whole frame is
            // one compiled function: fifteen passes and the sum of the
            // frame's code embeddings. The keys are drawn here from the
            // request's random state, one per pass in pass order, where the
            // eager sampler drew them.
            var frameEmbeddingSum: MLXArray?
            if codePredictorPlan.sampling != nil {
                let passCount = talkerConfig.numCodeGroups - 1
                let keys = (0 ..< passCount).map { _ in resolve(key: MLXArray?.none) }
                let frame = codePredictorPlan.runFrame(
                    codeHidden: codeHidden,
                    code0Embed: talker.getInputEmbeddings()(nextToken),
                    keys: keys
                )
                codeTokens.append(contentsOf: frame.codes)
                frameEmbeddingSum = frame.embeddingSum
                lastTakeFrameFunctionFrames = codePredictorPlan.frameFunctionCallCount
                // The per-pass intervals are still emitted, empty: the profile
                // lane counts fifteen of each per step (`trace_intervals.py`),
                // and their host time is the loop interval's.
                for _ in 0 ..< passCount {
                    os_signpost(.begin, log: stepSignpostLog, name: "Code Predictor Step")
                    os_signpost(.end, log: stepSignpostLog, name: "Code Predictor Step")
                    os_signpost(.begin, log: stepSignpostLog, name: "Sample Predicted Codebook")
                    os_signpost(.end, log: stepSignpostLog, name: "Sample Predicted Codebook")
                }
            }
            for codeIdx in 0 ..< talkerConfig.numCodeGroups - 1 where frameEmbeddingSum == nil {
                let codePredictorStepStartedAt = ContinuousClock.now
                os_signpost(.begin, log: stepSignpostLog, name: "Code Predictor Step")
                let codeLogits: MLXArray
                if codeIdx == 0 {
                    let code0Embed = talker.getInputEmbeddings()(nextToken)
                    codeLogits = codePredictorPlan.run(
                        pass: 0, codeHidden: codeHidden, code0Embed: code0Embed, token: nil
                    )
                } else {
                    codeLogits = codePredictorPlan.run(
                        pass: codeIdx, codeHidden: nil, code0Embed: nil, token: codeTokens.last!
                    )
                }
                os_signpost(.end, log: stepSignpostLog, name: "Code Predictor Step")
                codePredictorStepTotal += codePredictorStepStartedAt.elapsed

                let samplePredictedCodebookStartedAt = ContinuousClock.now
                os_signpost(.begin, log: stepSignpostLog, name: "Sample Predicted Codebook")
                if codePredictorScratch == nil {
                    codePredictorScratch = Qwen3SamplerScratch(vocabSize: codeLogits.dim(-1))
                }
                // Subtalker (code-predictor) sampling is explicitly request
                // owned and never inherits the talker's repetition penalty. The
                // host gives it the reference values whatever the variation
                // (RF-18 C1); only the generic `official` helper copies the talker.
                let nextCode = Self.sampleToken(
                    codeLogits,
                    temperature: subtalkerSampling.temperature,
                    topP: subtalkerSampling.topP,
                    topK: subtalkerSampling.topK,
                    minP: subtalkerSampling.minP,
                    scratch: codePredictorScratch,
                    castsLogitsToFloat32: referenceParity.float32Sampling,
                    observe: samplerObserver
                )
                os_signpost(.end, log: stepSignpostLog, name: "Sample Predicted Codebook")
                samplePredictedCodebookTotal += samplePredictedCodebookStartedAt.elapsed
                codeTokens.append(nextCode)
            }
            os_signpost(.end, log: stepSignpostLog, name: "Code Predictor Loop")
            codePredictorTotal += codePredictorStartedAt.elapsed

            let allCodes = concatenated(codeTokens, axis: 1) // [1, num_code_groups]
            // Prepare next input
            let textEmbed: MLXArray
            if trailingIdx < trailingTextHidden.dim(1) {
                textEmbed = trailingTextHidden[0..., trailingIdx ..< (trailingIdx + 1), 0...]
                trailingIdx += 1
            } else {
                textEmbed = ttsPadEmbed
            }

            // Sum all code embeddings for next step
            let codecEmbeddingStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Codec Embedding Assembly")
            var codecEmbed: MLXArray
            if let frameEmbeddingSum {
                // The frame function summed the embeddings it had computed.
                codecEmbed = frameEmbeddingSum
            } else {
                codecEmbed = talker.getInputEmbeddings()(nextToken)
                for (i, code) in codeTokens.dropFirst().enumerated() {
                    codecEmbed = codecEmbed + talker.codePredictor.codecEmbedding[i](code)
                }
            }

            inputEmbeds = textEmbed + codecEmbed
            os_signpost(.end, log: stepSignpostLog, name: "Codec Embedding Assembly")
            codecEmbeddingAssemblyTotal += codecEmbeddingStartedAt.elapsed
            let streamStepEvalStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Step Eval Flush")
            switch (streamStepEvalPolicy, stepIntrospection) {
            case (.full, let introspection?):
                eval(inputEmbeds, isEOS, introspection.entropy, introspection.eosProbability)
            case (.full, nil):
                eval(inputEmbeds, isEOS)
            case (.pipelined, let introspection?):
                asyncEval(inputEmbeds, isEOS, introspection.entropy, introspection.eosProbability)
            case (.pipelined, nil):
                asyncEval(inputEmbeds, isEOS)
            case (.eosOnly, let introspection?):
                eval(isEOS, introspection.entropy, introspection.eosProbability)
            case (.eosOnly, nil):
                eval(isEOS)
            case (.deferred, _):
                break
            }
            os_signpost(.end, log: stepSignpostLog, name: "Step Eval Flush")
            let streamStepEvalElapsed = streamStepEvalStartedAt.elapsed
            streamStepEvalTotal += streamStepEvalElapsed
            // The eval call is the enqueue. Only `.pipelined` has a separate,
            // observable wait: the step's first blocking read below (audit
            // #49/#62). A synchronous eval (`.full`, `.eosOnly`) fuses enqueue
            // and wait inside this call, so its split stays all-enqueue and
            // its wait is not observed.
            streamStepEvalEnqueueTotal += streamStepEvalElapsed
            if isPureVoiceDesign {
                designStreamStepEvalTotal += streamStepEvalElapsed
            } else if isDedicatedCustomVoice {
                customStreamStepEvalTotal += streamStepEvalElapsed
            } else if isVoiceCloneGeneration {
                cloneStreamStepEvalTotal += streamStepEvalElapsed
            }

            // The previous chunk's materialization and sends run while this
            // step's submitted graph computes; they precede this step's
            // `.token` send, so channel event order is unchanged.
            try await flushPendingMaterializedChunk()

            // V-2: the sampled-token read is the step's first blocking read.
            // Under `.pipelined` it waits for the GPU work `asyncEval`
            // submitted above; untimed, that wait fell into
            // `qwen_token_loop_unattributed`. Two clock reads and one
            // exclusive `os_signpost` interval per step: no allocation and no
            // lock on the hot path.
            let tokenReadStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "Token Read")
            let tokenId = Int(nextToken[0, 0].item(Int32.self))
            os_signpost(.end, log: stepSignpostLog, name: "Token Read")
            let tokenReadElapsed = tokenReadStartedAt.elapsed
            streamStepTokenReadTotal += tokenReadElapsed
            if streamStepEvalPolicy == .pipelined {
                streamStepEvalWaitTotal += tokenReadElapsed
            }
            if let materializedEventSink {
                try Task.checkCancellation()
                let handoffStartedAt = ContinuousClock.now
                try await materializedEventSink(.token(tokenId))
                recordSinkHandoff(since: handoffStartedAt)
                try Task.checkCancellation()
            } else {
                onToken?(tokenId)
            }
            let eosReadStartedAt = ContinuousClock.now
            os_signpost(.begin, log: stepSignpostLog, name: "EOS Read")
            let reachedEOS = isEOS.item(Bool.self)
            os_signpost(.end, log: stepSignpostLog, name: "EOS Read")
            let eosReadElapsed = eosReadStartedAt.elapsed
            streamStepEOSReadTotal += eosReadElapsed
            if isPureVoiceDesign {
                designStreamStepEOSReadTotal += eosReadElapsed
            } else if isDedicatedCustomVoice {
                customStreamStepEOSReadTotal += eosReadElapsed
            } else if isVoiceCloneGeneration {
                cloneStreamStepEOSReadTotal += eosReadElapsed
            }
            // Both scalars were evaluated with the step, so these are reads.
            if let stepIntrospection {
                generationIntrospector.observeStep(
                    entropy: stepIntrospection.entropy.item(Float.self),
                    eosProbability: stepIntrospection.eosProbability.item(Float.self),
                    stopped: reachedEOS
                )
            }
            if reachedEOS {
                generationEndReason = "eos"
                break
            }
            let materializedCodeFrame: [Int32]?
            if emitMaterializedCodecTrace || codecTraceSink != nil || !isStreaming {
                try evalForReadback(allCodes)
                materializedCodeFrame = allCodes.asArray(Int32.self)
            } else {
                materializedCodeFrame = nil
            }
            if emitMaterializedCodecTrace,
               let materializedEventSink,
               let materializedCodeFrame {
                try Task.checkCancellation()
                let handoffStartedAt = ContinuousClock.now
                try await materializedEventSink(.codecFrame(materializedCodeFrame))
                recordSinkHandoff(since: handoffStartedAt)
                try Task.checkCancellation()
            } else if let codecTraceSink, let materializedCodeFrame {
                try Task.checkCancellation()
                let handoffStartedAt = ContinuousClock.now
                try await codecTraceSink(materializedCodeFrame)
                recordSinkHandoff(since: handoffStartedAt)
                try Task.checkCancellation()
            }
            samplerScratch.appendRepetitionTokenID(tokenId)
            generationIntrospector.observeCodecToken(tokenId)
            generatedCodeCount += 1
            if isStreaming {
                pendingStreamCodes.append(allCodes)
                _ = streamChunkSchedule.append()
            } else if let materializedCodeFrame {
                generatedCodecFrames.append(materializedCodeFrame)
            }

            // Streaming: decode and yield audio chunks during generation
            if isStreaming {
                let requiredStreamChunkSize = streamChunkSchedule.requiredChunkSize
                if pendingStreamCodes.count >= requiredStreamChunkSize {
                    try Task.checkCancellation()
                    let codesChunk = stacked(pendingStreamCodes, axis: 1)
                    let codesForDecoder = codesChunk.transposed(0, 2, 1)
                    if isPureVoiceDesign, designGenerationStepsBeforeFirstChunk == nil {
                        designGenerationStepsBeforeFirstChunk = generatedCodeCount
                        designFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    } else if isDedicatedCustomVoice, customGenerationStepsBeforeFirstChunk == nil {
                        customGenerationStepsBeforeFirstChunk = generatedCodeCount
                        customFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    } else if isVoiceCloneGeneration, cloneGenerationStepsBeforeFirstChunk == nil {
                        cloneGenerationStepsBeforeFirstChunk = generatedCodeCount
                        cloneFirstChunkDecoderTokens = codesForDecoder.dim(2)
                    }
                    let streamDecoderStartedAt = ContinuousClock.now
                    os_signpost(.begin, log: stepSignpostLog, name: "Audio Decoder")
                    // Measured do-NOT (2026-07-26): building this decode graph
                    // on a dedicated stream (Stream.withNewDefaultStream)
                    // regressed warm RTF on every cell (−0.4% to −4.3%) — the
                    // per-chunk stream + cross-stream event sync cost more
                    // than overlapping a ~5 ms decode buys on this
                    // launch-bound loop. Record `stage1-p5b-codec-stream`
                    // (macos-engine-20260726-070148-150cc5e8).
                    let decoded: MLXArray
                    if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                        let decodedWithTimings = speechTokenizer.decoder.streamingStepWithTimings(codesForDecoder)
                        decoded = decodedWithTimings.audio.squeezed(axis: 1)
                        mimiDecoderBreakdownTotal = mimiDecoderBreakdownTotal.adding(decodedWithTimings.timings)
                    } else {
                        decoded = speechTokenizer.decoder.streamingStep(codesForDecoder)
                    }
                    os_signpost(.end, log: stepSignpostLog, name: "Audio Decoder")
                    streamingDecoderTotal += streamDecoderStartedAt.elapsed
                    streamingDecoderCallCount += 1
                    let audioChunk = decoded[0]
                    let audioChunkEvalStartedAt = ContinuousClock.now
                    os_signpost(.begin, log: stepSignpostLog, name: "Audio Chunk Eval")
                    // STREAM-001: non-final chunks evaluate asynchronously so decoding can
                    // overlap the next token loop on the compatibility path. The suspending
                    // actor path materializes in this task before it awaits its sink, so an
                    // MLX value never crosses a task or actor boundary.
                    asyncEval(audioChunk)
                    os_signpost(.end, log: stepSignpostLog, name: "Audio Chunk Eval")
                    let audioChunkEvalElapsed = audioChunkEvalStartedAt.elapsed
                    audioChunkEvalTotal += audioChunkEvalElapsed
                    if isPureVoiceDesign {
                        designAudioChunkEvalTotal += audioChunkEvalElapsed
                    } else if isDedicatedCustomVoice {
                        customAudioChunkEvalTotal += audioChunkEvalElapsed
                    } else if isVoiceCloneGeneration {
                        cloneAudioChunkEvalTotal += audioChunkEvalElapsed
                    }

                    let chunkCodecStart = emittedCodecFrameCount
                    let chunkCodecEnd = chunkCodecStart + UInt64(pendingStreamCodes.count)
                    pendingStreamCodes.removeAll(keepingCapacity: true)
                    streamChunkSchedule.didEmit()
                    emittedCodecFrameCount = chunkCodecEnd
                    generationIntrospector.recordSeam(codecFrame: Int(chunkCodecEnd))
                    // `.pipelined`: leave the chunk lazily submitted and flush
                    // it at the top of the next token step. The flush point
                    // runs before every assembly, so at most one chunk is ever
                    // pending.
                    let deferChunkMaterialization =
                        streamStepEvalPolicy == .pipelined && materializedEventSink != nil
                    assert(pendingMaterializedChunk == nil)
                    let materializedSamples: [Float]?
                    if materializedEventSink != nil, !deferChunkMaterialization {
                        try evalForReadback(audioChunk)
                        try Task.checkCancellation()
                        materializedSamples = audioChunk.asArray(Float.self)
                    } else {
                        materializedSamples = nil
                    }
                    var deferredChunkTimings: ChunkSubstageTimings?
                    if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                        let kvDiagnostics = makeChunkKVCacheDiagnostics()
                        let chunkMimiBreakdown = mimiDecoderBreakdownTotal.subtracting(lastChunkMimiDecoderBreakdown)
                        let timings = ChunkSubstageTimings(
                            talkerForwardMS: (talkerForwardTotal - lastChunkTalkerForward).fractionalMilliseconds,
                            codePredictorMS: (codePredictorTotal - lastChunkCodePredictor).fractionalMilliseconds,
                            audioDecoderMS: (streamingDecoderTotal - lastChunkStreamingDecoder).fractionalMilliseconds,
                            streamStepEvalMS: (streamStepEvalTotal - lastChunkStreamStepEval).fractionalMilliseconds,
                            streamStepEvalEnqueueMS: (streamStepEvalEnqueueTotal - lastChunkStreamStepEvalEnqueue).fractionalMilliseconds,
                            streamStepEvalWaitMS: (streamStepEvalWaitTotal - lastChunkStreamStepEvalWait).fractionalMilliseconds,
                            streamStepEOSReadMS: (streamStepEOSReadTotal - lastChunkStreamStepEOSRead).fractionalMilliseconds,
                            audioChunkEvalMS: (audioChunkEvalTotal - lastChunkAudioChunkEval).fractionalMilliseconds,
                            kvCacheDiagnostics: kvDiagnostics,
                            mimiDecoderBreakdownMS: chunkMimiBreakdown,
                            codecStartFrame: chunkCodecStart,
                            codecEndFrameExclusive: chunkCodecEnd
                        )
                        lastChunkTalkerForward = talkerForwardTotal
                        lastChunkCodePredictor = codePredictorTotal
                        lastChunkStreamingDecoder = streamingDecoderTotal
                        lastChunkStreamStepEval = streamStepEvalTotal
                        lastChunkStreamStepEvalEnqueue = streamStepEvalEnqueueTotal
                        lastChunkStreamStepEvalWait = streamStepEvalWaitTotal
                        lastChunkStreamStepEOSRead = streamStepEOSReadTotal
                        lastChunkAudioChunkEval = audioChunkEvalTotal
                        lastChunkMimiDecoderBreakdown = mimiDecoderBreakdownTotal
                        if deferChunkMaterialization {
                            deferredChunkTimings = timings
                        } else if let materializedEventSink {
                            try Task.checkCancellation()
                            let handoffStartedAt = ContinuousClock.now
                            try await materializedEventSink(.chunkTimings(timings))
                            recordSinkHandoff(since: handoffStartedAt)
                            try Task.checkCancellation()
                        } else {
                            onAudioChunkTimings?(timings)
                        }
                    }
                    try Task.checkCancellation()
                    if deferChunkMaterialization {
                        pendingMaterializedChunk = PendingMaterializedStreamChunk(
                            audioChunk: audioChunk,
                            timings: deferredChunkTimings
                        )
                    } else if let materializedEventSink, let materializedSamples {
                        let handoffStartedAt = ContinuousClock.now
                        try await materializedEventSink(.audio(materializedSamples))
                        recordSinkHandoff(since: handoffStartedAt)
                        try Task.checkCancellation()
                    } else {
                        onAudioChunk?(audioChunk)
                    }
                    if memoryPolicy.clearCacheOnStreamChunkEmit {
                        clearGenerationCache()
                    }
                }
            }

            if memoryClearCadence > 0,
               generatedCodeCount > 0,
               generatedCodeCount.isMultiple(of: memoryClearCadence) {
                clearGenerationCache()
            }

        }

        // GEN-NOEOS evidence on the engine row: the frames held and where the hold opened.
        if let eosSuppression {
            mergePreparationTimingsMS(eosSuppression.evidence)
        }

        tokenLoopAttributedAtExit = tokenLoopAttributedTotal()
        // Audit #60: the work after the token loop (the final flush, `.info`,
        // and the tail chunk's decode, eval and sends, or quality-first's full
        // decode) is timed as its own span, `qwen_tail_decode_total`, so no
        // loop key has to stand in for it.
        let tailStartedAt = ContinuousClock.now

        // A chunk stashed in the final token step (EOS or token cap) flushes
        // here, before the info event and the tail chunk — the same relative
        // audio/info order as the synchronous path.
        try await flushPendingMaterializedChunk()

        guard generatedCodeCount > 0 else {
            generationEndReason = "failed"
            mergePreparationBooleanFlags([
                "generation_ended_by_eos": false,
                "generation_hit_token_cap": false,
            ])
            mergePreparationStringFlags([
                "generation_end_reason": generationEndReason,
            ])
            if let timingPrefix = streamingGenerationMode.timingPrefix {
                mergePreparationBooleanFlags([
                    "\(timingPrefix)_generation_ended_by_eos": false,
                    "\(timingPrefix)_generation_hit_token_cap": false,
                ])
                mergePreparationStringFlags([
                    "\(timingPrefix)_generation_end_reason": generationEndReason,
                ])
            }
            return MLXArray.zeros([1])
        }

        // Emit generation info
        let info = Qwen3GenerationThroughput.info(
            generationTokenCount: generatedCodeCount,
            span: startTime.duration(to: .now),
            peakMemoryUsage: Double(Memory.peakMemory) / 1e9
        )
        if let materializedEventSink {
            try Task.checkCancellation()
            try await materializedEventSink(.info(info))
            try Task.checkCancellation()
        } else {
            onInfo?(info)
        }
        mergePreparationBooleanFlags([
            "generation_ended_by_eos": generationEndReason == "eos",
            "generation_hit_token_cap": generationEndReason == "token_cap",
        ])
        mergePreparationStringFlags([
            "generation_end_reason": generationEndReason,
        ])
        if let timingPrefix = streamingGenerationMode.timingPrefix {
            mergePreparationBooleanFlags([
                "\(timingPrefix)_generation_ended_by_eos": generationEndReason == "eos",
                "\(timingPrefix)_generation_hit_token_cap": generationEndReason == "token_cap",
            ])
            mergePreparationStringFlags([
                "\(timingPrefix)_generation_end_reason": generationEndReason,
            ])
        }

        // Streaming path: yield remaining tokens and return early
        if isStreaming {
            if !pendingStreamCodes.isEmpty {
                try Task.checkCancellation()
                let codesChunk = stacked(pendingStreamCodes, axis: 1)
                let codesForDecoder = codesChunk.transposed(0, 2, 1)
                let streamDecoderStartedAt = ContinuousClock.now
                // The tail decode and eval carry the same interval names as
                // the in-loop chunks, so a trace's `Audio Decoder` count
                // equals `qwen_stream_decoder_calls`.
                os_signpost(.begin, log: stepSignpostLog, name: "Audio Decoder")
                let decoded: MLXArray
                if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                    let decodedWithTimings = speechTokenizer.decoder.streamingStepWithTimings(codesForDecoder)
                    decoded = decodedWithTimings.audio.squeezed(axis: 1)
                    mimiDecoderBreakdownTotal = mimiDecoderBreakdownTotal.adding(decodedWithTimings.timings)
                } else {
                    decoded = speechTokenizer.decoder.streamingStep(codesForDecoder)
                }
                os_signpost(.end, log: stepSignpostLog, name: "Audio Decoder")
                streamingDecoderTotal += streamDecoderStartedAt.elapsed
                streamingDecoderCallCount += 1
                let audioChunk = decoded[0]
                if isPureVoiceDesign, designGenerationStepsBeforeFirstChunk == nil {
                    designGenerationStepsBeforeFirstChunk = generatedCodeCount
                    designFirstChunkDecoderTokens = codesForDecoder.dim(2)
                } else if isDedicatedCustomVoice, customGenerationStepsBeforeFirstChunk == nil {
                    customGenerationStepsBeforeFirstChunk = generatedCodeCount
                    customFirstChunkDecoderTokens = codesForDecoder.dim(2)
                } else if isVoiceCloneGeneration, cloneGenerationStepsBeforeFirstChunk == nil {
                    cloneGenerationStepsBeforeFirstChunk = generatedCodeCount
                    cloneFirstChunkDecoderTokens = codesForDecoder.dim(2)
                }
                let audioChunkEvalStartedAt = ContinuousClock.now
                os_signpost(.begin, log: stepSignpostLog, name: "Audio Chunk Eval")
                // STREAM-001: the final chunk is a synchronous completion barrier. Returning
                // before materialization can race playback handoff and truncate the preview.
                eval(audioChunk)
                os_signpost(.end, log: stepSignpostLog, name: "Audio Chunk Eval")
                let audioChunkEvalElapsed = audioChunkEvalStartedAt.elapsed
                audioChunkEvalTotal += audioChunkEvalElapsed
                if isPureVoiceDesign {
                    designAudioChunkEvalTotal += audioChunkEvalElapsed
                } else if isDedicatedCustomVoice {
                    customAudioChunkEvalTotal += audioChunkEvalElapsed
                } else if isVoiceCloneGeneration {
                    cloneAudioChunkEvalTotal += audioChunkEvalElapsed
                }
                let materializedSamples: [Float]?
                if materializedEventSink != nil {
                    try Task.checkCancellation()
                    try evalForReadback(audioChunk)
                    materializedSamples = audioChunk.asArray(Float.self)
                } else {
                    materializedSamples = nil
                }
                let chunkCodecStart = emittedCodecFrameCount
                let chunkCodecEnd = chunkCodecStart + UInt64(pendingStreamCodes.count)
                emittedCodecFrameCount = chunkCodecEnd
                if onAudioChunkTimings != nil || emitMaterializedChunkTimings {
                    let kvDiagnostics = makeChunkKVCacheDiagnostics()
                    let chunkMimiBreakdown = mimiDecoderBreakdownTotal.subtracting(lastChunkMimiDecoderBreakdown)
                    let timings = ChunkSubstageTimings(
                        talkerForwardMS: (talkerForwardTotal - lastChunkTalkerForward).fractionalMilliseconds,
                        codePredictorMS: (codePredictorTotal - lastChunkCodePredictor).fractionalMilliseconds,
                        audioDecoderMS: (streamingDecoderTotal - lastChunkStreamingDecoder).fractionalMilliseconds,
                        streamStepEvalMS: (streamStepEvalTotal - lastChunkStreamStepEval).fractionalMilliseconds,
                        streamStepEvalEnqueueMS: (streamStepEvalEnqueueTotal - lastChunkStreamStepEvalEnqueue).fractionalMilliseconds,
                        streamStepEvalWaitMS: (streamStepEvalWaitTotal - lastChunkStreamStepEvalWait).fractionalMilliseconds,
                        streamStepEOSReadMS: (streamStepEOSReadTotal - lastChunkStreamStepEOSRead).fractionalMilliseconds,
                        audioChunkEvalMS: (audioChunkEvalTotal - lastChunkAudioChunkEval).fractionalMilliseconds,
                        kvCacheDiagnostics: kvDiagnostics,
                        mimiDecoderBreakdownMS: chunkMimiBreakdown,
                        codecStartFrame: chunkCodecStart,
                        codecEndFrameExclusive: chunkCodecEnd
                    )
                    lastChunkTalkerForward = talkerForwardTotal
                    lastChunkCodePredictor = codePredictorTotal
                    lastChunkStreamingDecoder = streamingDecoderTotal
                    lastChunkStreamStepEval = streamStepEvalTotal
                    lastChunkStreamStepEvalEnqueue = streamStepEvalEnqueueTotal
                    lastChunkStreamStepEvalWait = streamStepEvalWaitTotal
                    lastChunkStreamStepEOSRead = streamStepEOSReadTotal
                    lastChunkAudioChunkEval = audioChunkEvalTotal
                    lastChunkMimiDecoderBreakdown = mimiDecoderBreakdownTotal
                    if let materializedEventSink {
                        try Task.checkCancellation()
                        try await materializedEventSink(.chunkTimings(timings))
                        try Task.checkCancellation()
                    } else {
                        onAudioChunkTimings?(timings)
                    }
                }
                try Task.checkCancellation()
                if let materializedEventSink, let materializedSamples {
                    try await materializedEventSink(.audio(materializedSamples))
                    try Task.checkCancellation()
                } else {
                    onAudioChunk?(audioChunk)
                }
                streamChunkSchedule.didEmit()
                // Capture final KV-cache footprint before clearing; when the
                // chunk-timing callback is not registered this is the only
                // update the peak trackers get.
                if onAudioChunkTimings != nil {
                    _ = makeChunkKVCacheDiagnostics()
                }
                clearGenerationCache()
            }
            mergePreparationStringFlags([
                "qwen_talker_kv_cache_type": kvCacheTypeAtPeak,
            ])
            var mergedTimingsMS = qwenHotLoopTimingsMS()
                .merging(preparationTimingsMS) { _, rhs in rhs }
            mergedTimingsMS["qwen_tail_decode_total"] = tailStartedAt.elapsed.roundedMilliseconds
            if isPureVoiceDesign {
                mergedTimingsMS["design_stream_step_eval_total_ms"] = designStreamStepEvalTotal.roundedMilliseconds
                mergedTimingsMS["design_stream_step_eos_read_total_ms"] = designStreamStepEOSReadTotal.roundedMilliseconds
                mergedTimingsMS["design_audio_chunk_eval_total_ms"] = designAudioChunkEvalTotal.roundedMilliseconds
                if let designGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["design_generation_steps_before_first_chunk"] = designGenerationStepsBeforeFirstChunk
                }
                if let designFirstChunkDecoderTokens {
                    mergedTimingsMS["design_first_chunk_decoder_tokens"] = designFirstChunkDecoderTokens
                }
            } else if isDedicatedCustomVoice {
                mergedTimingsMS["custom_stream_step_eval_total_ms"] = customStreamStepEvalTotal.roundedMilliseconds
                mergedTimingsMS["custom_stream_step_eos_read_total_ms"] = customStreamStepEOSReadTotal.roundedMilliseconds
                mergedTimingsMS["custom_audio_chunk_eval_total_ms"] = customAudioChunkEvalTotal.roundedMilliseconds
                if let customGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["custom_generation_steps_before_first_chunk"] = customGenerationStepsBeforeFirstChunk
                }
                if let customFirstChunkDecoderTokens {
                    mergedTimingsMS["custom_first_chunk_decoder_tokens"] = customFirstChunkDecoderTokens
                }
                mergedTimingsMS["custom_generation_ended_by_eos"] = generationEndReason == "eos" ? 1 : 0
                mergedTimingsMS["custom_generation_hit_token_cap"] = generationEndReason == "token_cap" ? 1 : 0
                mergePreparationBooleanFlags([
                    "custom_generation_ended_by_eos": generationEndReason == "eos",
                    "custom_generation_hit_token_cap": generationEndReason == "token_cap",
                ])
                mergePreparationStringFlags([
                    "custom_generation_end_reason": generationEndReason,
                ])
            } else if isVoiceCloneGeneration {
                mergedTimingsMS["clone_stream_step_eval_total_ms"] = cloneStreamStepEvalTotal.roundedMilliseconds
                mergedTimingsMS["clone_stream_step_eos_read_total_ms"] = cloneStreamStepEOSReadTotal.roundedMilliseconds
                mergedTimingsMS["clone_audio_chunk_eval_total_ms"] = cloneAudioChunkEvalTotal.roundedMilliseconds
                if let cloneGenerationStepsBeforeFirstChunk {
                    mergedTimingsMS["clone_generation_steps_before_first_chunk"] = cloneGenerationStepsBeforeFirstChunk
                }
                if let cloneFirstChunkDecoderTokens {
                    mergedTimingsMS["clone_first_chunk_decoder_tokens"] = cloneFirstChunkDecoderTokens
                }
            }
            mergePreparationTimingsMS(mergedTimingsMS)
            // Streaming chunks already yielded; return empty (caller uses chunks)
            return MLXArray.zeros([1])
        }

        // Non-streaming path: full decode (existing behavior)
        guard let codeGroupCount = generatedCodecFrames.first?.count,
              codeGroupCount > 0,
              generatedCodecFrames.allSatisfy({ $0.count == codeGroupCount }) else {
            throw AudioGenerationError.audioDecodingFailed(
                "Quality-first generation produced invalid codec frames"
            )
        }
        let codes = MLXArray(generatedCodecFrames.flatMap { $0 })
            .reshaped([1, generatedCodecFrames.count, codeGroupCount])

        var decodeCodes = codes
        var referenceFrameCount = 0
        if let refCodes {
            let refCodesT = refCodes.transposed(0, 2, 1)
            decodeCodes = concatenated([refCodesT, codes], axis: 1)
            referenceFrameCount = refCodes.dim(2)
        }

        // The in-context reference cut and the generated tail both come from
        // explicit frame counts (qualityFirstSampleRange), never from the
        // decoded length or from counting non-zero codes.
        let audio = decodeChunk(decodeCodes, referenceFrameCount: referenceFrameCount)

        let finalDecodeEvalStartedAt = ContinuousClock.now
        eval(audio)
        // Capture final KV-cache footprint for non-streaming runs (no chunk
        // boundaries fired, so the peak trackers haven't been updated) BEFORE
        // clearing the generation cache, which resets the KV-cache offset.
        if onAudioChunkTimings != nil {
            _ = makeChunkKVCacheDiagnostics()
        }
        mergePreparationStringFlags([
            "qwen_talker_kv_cache_type": kvCacheTypeAtPeak,
        ])
        clearGenerationCache()
        var mergedTimingsMS = qwenHotLoopTimingsMS()
            .merging(preparationTimingsMS) { _, rhs in rhs }
        mergedTimingsMS["qwen_tail_decode_total"] = tailStartedAt.elapsed.roundedMilliseconds
        if isPureVoiceDesign {
            mergedTimingsMS["design_stream_step_eval_total_ms"] = designStreamStepEvalTotal.roundedMilliseconds
            mergedTimingsMS["design_stream_step_eos_read_total_ms"] = designStreamStepEOSReadTotal.roundedMilliseconds
            mergedTimingsMS["design_final_decode_eval_ms"] = finalDecodeEvalStartedAt.elapsedMilliseconds
        } else if isDedicatedCustomVoice {
            mergedTimingsMS["custom_stream_step_eval_total_ms"] = customStreamStepEvalTotal.roundedMilliseconds
            mergedTimingsMS["custom_stream_step_eos_read_total_ms"] = customStreamStepEOSReadTotal.roundedMilliseconds
            mergedTimingsMS["custom_audio_chunk_eval_total_ms"] = customAudioChunkEvalTotal.roundedMilliseconds
            mergedTimingsMS["custom_generation_ended_by_eos"] = generationEndReason == "eos" ? 1 : 0
            mergedTimingsMS["custom_generation_hit_token_cap"] = generationEndReason == "token_cap" ? 1 : 0
            mergePreparationBooleanFlags([
                "custom_generation_ended_by_eos": generationEndReason == "eos",
                "custom_generation_hit_token_cap": generationEndReason == "token_cap",
            ])
            mergePreparationStringFlags([
                "custom_generation_end_reason": generationEndReason,
            ])
        } else if isVoiceCloneGeneration {
            mergedTimingsMS["clone_stream_step_eval_total_ms"] = cloneStreamStepEvalTotal.roundedMilliseconds
            mergedTimingsMS["clone_stream_step_eos_read_total_ms"] = cloneStreamStepEOSReadTotal.roundedMilliseconds
            mergedTimingsMS["clone_audio_chunk_eval_total_ms"] = cloneAudioChunkEvalTotal.roundedMilliseconds
        }
        mergePreparationTimingsMS(mergedTimingsMS)
        return audio
    }

    // MARK: - Token sampling

    /// Internal diagnostic seam. Product hosts cannot set this. The observer
    /// must retain at most one frame and materialize only after its normal eval
    /// boundary; observed/unobserved code parity is a separate required check.
    var samplerObserver: ((MLXArray, MLXArray, MLXArray?, MLXArray) -> Void)?

    /// Frames of the latest take that ran the code predictor as one compiled
    /// function (RF-46); zero for a take on the per-pass plan. Internal, for
    /// tests: it says which path a take took.
    private(set) var lastTakeFrameFunctionFrames = 0

}

extension ContinuousClock.Instant {
    var elapsedMilliseconds: Int {
        duration(to: .now).roundedMilliseconds
    }

    /// The unrounded span to now, for hot-loop totals that round once at export.
    var elapsed: Duration {
        duration(to: .now)
    }
}

extension Duration {
    /// Whole milliseconds, rounded once. Hot-loop totals sum unrounded spans
    /// and round here at export (audit #61/#95).
    var roundedMilliseconds: Int {
        Int(fractionalMilliseconds.rounded())
    }

    /// Unrounded milliseconds, for per-chunk deltas.
    var fractionalMilliseconds: Double {
        let components = components
        let secondsMS = Double(components.seconds) * 1_000
        let attosecondsMS = Double(components.attoseconds) / 1_000_000_000_000_000
        return secondsMS + attosecondsMS
    }

    /// Unrounded seconds, for throughput spans measured on ContinuousClock.
    var totalSeconds: Double {
        let components = components
        return Double(components.seconds)
            + Double(components.attoseconds) / 1_000_000_000_000_000_000
    }
}
