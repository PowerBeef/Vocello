// Tokenizer, prepared-component, conditioning-prefix and decoder-bucket caches of the
// Qwen3-TTS runtime. Moved out of Qwen3TTS.swift unchanged (RF-46).

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

final class CachedTokenizerBox: @unchecked Sendable {
    let tokenizer: Tokenizer

    init(tokenizer: Tokenizer) {
        self.tokenizer = tokenizer
    }
}

/// Phase 9 (runtime component reuse): the loaded 682 MB speech tokenizer is
/// byte-identical across every catalog artifact, so a mode switch may adopt
/// the previous model's tokenizer object instead of re-reading and
/// re-materializing it. Content identity is grounded in the shared-component
/// store's hard links (device/inode/size/mtime of the resolved weights file
/// plus the tokenizer config digest); any stat or hash failure disables
/// caching fail-safe. Ownership follows the registered lock-protected cache
/// invariant: exactly one logical user at a time — the loaded model — with
/// the cache holding the handoff reference between sequential loads.
/// `Qwen3TTSMemoryCaches.clearAll` (memory relief and explicit unload) clears
/// the slot, so pressure never retains it; only an in-process model switch
/// preserves it.
final class CachedSpeechTokenizerBox: @unchecked Sendable {
    let identityKey: String
    let includesEncoder: Bool
    let speechTokenizer: Qwen3TTSSpeechTokenizer

    init(identityKey: String, includesEncoder: Bool, speechTokenizer: Qwen3TTSSpeechTokenizer) {
        self.identityKey = identityKey
        self.includesEncoder = includesEncoder
        self.speechTokenizer = speechTokenizer
    }
}

/// Thread-safe cache for the immutable text tokenizer only. Speech tokenizers
/// contain mutable decoder streaming state and remain owned by one loaded model;
/// sharing them across engines would bypass each engine's operation lease.
final class Qwen3TTSPreparedComponentCache: Sendable {
    private struct State {
        var tokenizersByPreparedKey: [String: CachedTokenizerBox] = [:]
        var tokenizerLRU: [String] = []
        var residentSpeechTokenizer: CachedSpeechTokenizerBox?
    }

    static let shared = Qwen3TTSPreparedComponentCache()

#if os(iOS)
    private let tokenizerLimit = 1
    /// Adaptive iOS residency (2026-08-01): the f16 codec promotion (§R) cut
    /// the resident decoder to ~218 MB, making residency a candidate on the
    /// 8 GB device class (the Mac's model-switch win is 503 → 0 ms). The
    /// device-class heuristic qualified 2026-08-02 on the paired iPhone 17
    /// Pro with this exact build in its default state:
    /// ios-memory-qualification-20260802-011251 — memoryQualified true, QC
    /// clean, and engagement proven by load-event counts (one speech-tokenizer
    /// load for the Custom→Design→Clone switch sequence instead of three;
    /// retained cost absorbed within run noise). Pressure ownership is
    /// unchanged: critical trim and full unload invalidate the resident cache
    /// regardless.
    static let iosAdaptiveResidencyQualified = true
    /// 8 GB device class; 6 GB devices stay non-resident pending the
    /// hardware-floor feasibility evidence (iphone14pro clamp profile).
    static let iosResidencyMinimumPhysicalMemoryBytes: UInt64 = 7 * 1_073_741_824
    static let speechTokenizerResidencySupported: Bool =
        iosAdaptiveResidencyQualified
            && ProcessInfo.processInfo.physicalMemory >= iosResidencyMinimumPhysicalMemoryBytes
#else
    private let tokenizerLimit = 3
    static let speechTokenizerResidencySupported = true
#endif

    /// `override` is the load's gated diagnostic switch
    /// (`Qwen3LoadTimeDiagnosticOverrides.speechTokenizerResidency`): `nil`
    /// keeps the device-class policy, `false` disables residency anywhere,
    /// `true` force-enables it.
    static func speechTokenizerResidencyEnabled(override: Bool?) -> Bool {
        override ?? speechTokenizerResidencySupported
    }

    private let state = OSAllocatedUnfairLock(initialState: State())

    func cachedTokenizer(for preparedKey: String) -> CachedTokenizerBox? {
        state.withLock { value in
            guard let box = value.tokenizersByPreparedKey[preparedKey] else {
                return nil
            }
            Self.touch(preparedKey, in: &value.tokenizerLRU)
            return box
        }
    }

    func storeTokenizer(_ tokenizer: Tokenizer, for preparedKey: String) {
        let box = CachedTokenizerBox(tokenizer: tokenizer)
        state.withLock { value in
            value.tokenizersByPreparedKey[preparedKey] = box
            Self.touch(preparedKey, in: &value.tokenizerLRU)
            Self.trim(
                keys: &value.tokenizerLRU,
                values: &value.tokenizersByPreparedKey,
                limit: tokenizerLimit
            )
        }
    }

    /// Exact content identity, superset capability: a resident that carries
    /// the encoder may serve a decoder-only load (custom/design switching
    /// away from a clone model), but a decoder-only resident can never serve
    /// an encoder-needing load — that one falls through to the disk load.
    func residentSpeechTokenizer(
        identityKey: String,
        includeEncoder: Bool,
        residencyOverride: Bool? = nil
    ) -> CachedSpeechTokenizerBox? {
        guard Self.speechTokenizerResidencyEnabled(override: residencyOverride) else {
            return nil
        }
        return state.withLock { value in
            guard let box = value.residentSpeechTokenizer,
                  box.identityKey == identityKey,
                  !includeEncoder || box.includesEncoder else {
                return nil
            }
            return box
        }
    }

    func storeResidentSpeechTokenizer(
        _ speechTokenizer: Qwen3TTSSpeechTokenizer,
        identityKey: String,
        includesEncoder: Bool,
        residencyOverride: Bool? = nil
    ) {
        guard Self.speechTokenizerResidencyEnabled(override: residencyOverride) else { return }
        let box = CachedSpeechTokenizerBox(
            identityKey: identityKey,
            includesEncoder: includesEncoder,
            speechTokenizer: speechTokenizer
        )
        state.withLock { value in
            value.residentSpeechTokenizer = box
        }
    }

    func clear() {
        state.withLock { value in
            value.tokenizersByPreparedKey.removeAll()
            value.tokenizerLRU.removeAll()
            value.residentSpeechTokenizer = nil
        }
    }

    private static func touch(_ key: String, in keys: inout [String]) {
        keys.removeAll { $0 == key }
        keys.append(key)
    }

    private static func trim<Value>(
        keys: inout [String],
        values: inout [String: Value],
        limit: Int
    ) {
        while keys.count > limit, let evicted = keys.first {
            keys.removeFirst()
            values.removeValue(forKey: evicted)
        }
    }
}

struct CachedConditioningPrefix: @unchecked Sendable {
    let inputPrefixEmbeds: MLXArray
    let codecLastEmbed: MLXArray
    let ttsEosEmbed: MLXArray
    let ttsPadEmbed: MLXArray
}

private final class CachedConditioningPrefixBox: @unchecked Sendable {
    let prefix: CachedConditioningPrefix

    init(prefix: CachedConditioningPrefix) {
        self.prefix = prefix
    }
}

/// The model-relative part of a conditioning-prefix cache key (P02-08, P05-07).
/// A cached prefix holds the instruct tokens embedded on the miss that built it,
/// and those are the instruction exactly as given, trimmed at its ends only. The
/// key therefore carries that exact text: two instructions that differ only in
/// case, line breaks or inner spacing are two prompts and never share an entry,
/// so an edit to a brief always reaches the model and a request and seed give
/// the same take whatever the cache held. Language and speaker fold case and
/// trim because the prefix resolves both that way (`resolvedLanguageIdentifier`,
/// `speakerTokenEmbeddings`).
enum Qwen3ConditioningPrefixCacheKey {
    static func customVoice(language: String, speaker: String, instruction: String?) -> String {
        "custom|\(folded(language))|\(folded(speaker))|\(embeddedInstruction(instruction))"
    }

    static func voiceDesign(language: String, voiceDescription: String) -> String {
        "design|\(folded(language))|\(embeddedInstruction(voiceDescription))"
    }

    /// The instruct text the prefix embeds: trimmed as `buildConditioningPrefix`
    /// trims it, otherwise untouched; empty when there is none.
    static func embeddedInstruction(_ instruction: String?) -> String {
        instruction?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private static func folded(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

final class Qwen3TTSConditioningPrefixCache: @unchecked Sendable {
    static let shared = Qwen3TTSConditioningPrefixCache()

#if os(iOS)
    private let limit = 2
#else
    private let limit = 16
#endif
    private let lock = NSLock()
    private var prefixesByKey: [String: CachedConditioningPrefixBox] = [:]
    private var lruKeys: [String] = []

    func cachedPrefix(for cacheKey: String) -> CachedConditioningPrefix? {
        lock.lock()
        defer { lock.unlock() }
        guard let box = prefixesByKey[cacheKey] else {
            return nil
        }
        touch(cacheKey)
        return box.prefix
    }

    func storePrefix(_ prefix: CachedConditioningPrefix, for cacheKey: String) {
        lock.lock()
        prefixesByKey[cacheKey] = CachedConditioningPrefixBox(prefix: prefix)
        touch(cacheKey)
        trimIfNeeded()
        lock.unlock()
    }

    func clear() {
        lock.lock()
        prefixesByKey.removeAll()
        lruKeys.removeAll()
        lock.unlock()
        Memory.clearCache()
    }

    private func touch(_ cacheKey: String) {
        lruKeys.removeAll { $0 == cacheKey }
        lruKeys.append(cacheKey)
    }

    private func trimIfNeeded() {
        while lruKeys.count > limit, let evicted = lruKeys.first {
            lruKeys.removeFirst()
            prefixesByKey.removeValue(forKey: evicted)
        }
    }
}

final class Qwen3TTSStreamingDecoderBucketCache: @unchecked Sendable {
    static let shared = Qwen3TTSStreamingDecoderBucketCache()

#if os(iOS)
    private let limit = 2
#else
    private let limit = 8
#endif
    private let lock = NSLock()
    private var warmedKeys: Set<String> = []
    private var lruKeys: [String] = []

    func contains(_ key: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        let contains = warmedKeys.contains(key)
        if contains {
            touch(key)
        }
        return contains
    }

    func insert(_ key: String) {
        lock.lock()
        warmedKeys.insert(key)
        touch(key)
        trimIfNeeded()
        lock.unlock()
    }

    func clear() {
        lock.lock()
        warmedKeys.removeAll()
        lruKeys.removeAll()
        lock.unlock()
        Memory.clearCache()
    }

    private func touch(_ key: String) {
        lruKeys.removeAll { $0 == key }
        lruKeys.append(key)
    }

    private func trimIfNeeded() {
        while lruKeys.count > limit, let evicted = lruKeys.first {
            lruKeys.removeFirst()
            warmedKeys.remove(evicted)
        }
    }
}

public enum Qwen3TTSMemoryCaches {
    public static func clearAll(
        isolation: isolated (any Actor)? = #isolation
    ) async {
        _ = isolation
        Qwen3TTSPreparedComponentCache.shared.clear()
        Qwen3TTSConditioningPrefixCache.shared.clear()
        Qwen3TTSStreamingDecoderBucketCache.shared.clear()
        Memory.clearCache()
    }
}
