// Generation profiles and policies of the Qwen3-TTS runtime: prewarm depth, token
// budget, speed profile, streaming mode, text conditioning and step evaluation.
// Moved out of Qwen3TTS.swift unchanged (RF-46).

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

enum Qwen3CustomVoicePrewarmDepth: String, Sendable {
    case full
    case skipDecoderBucket = "skip-decoder-bucket"
    case skipStreamStep = "skip-stream-step"

    static func resolve(rawValue: String?) -> Qwen3CustomVoicePrewarmDepth {
        guard let rawValue = rawValue?
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased(),
              !rawValue.isEmpty else {
            return .full
        }

        return Qwen3CustomVoicePrewarmDepth(rawValue: rawValue) ?? .full
    }

    var precompileDecoderBuckets: Bool {
        self != .skipDecoderBucket
    }

    var warmsStreamStep: Bool {
        self != .skipStreamStep
    }

    var booleanFlags: [String: Bool] {
        [
            "custom_prewarm_depth_full": self == .full,
            "custom_prewarm_depth_skip_decoder_bucket": self == .skipDecoderBucket,
            "custom_prewarm_depth_skip_stream_step": self == .skipStreamStep,
        ]
    }
}

enum Qwen3CustomVoiceGenerationProfile: String, Sendable {
    case baseline
    case balancedShort = "balanced-short"
    case conservativeShort = "conservative-short"
    case fastShort = "fast-short"

    static func resolve(
        explicitProfile: String? = nil
    ) -> Qwen3CustomVoiceGenerationProfile {
        if let explicitProfile = explicitProfile?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitProfile.isEmpty {
            return Qwen3CustomVoiceGenerationProfile(rawValue: explicitProfile) ?? .baseline
        }

        return .baseline
    }

    var maxTokenMultiplier: Int {
        switch self {
        case .baseline:
            return 6
        case .balancedShort, .fastShort:
            return 4
        case .conservativeShort:
            return 5
        }
    }

    var minimumGeneratedCodes: Int {
        switch self {
        case .baseline:
            return 75
        case .balancedShort, .conservativeShort:
            return 60
        case .fastShort:
            return 50
        }
    }

    var postFirstStreamChunkMultiplier: Int {
        switch self {
        case .baseline:
            return 1
        case .balancedShort, .conservativeShort:
            return 2
        case .fastShort:
            return 3
        }
    }

    func effectiveMaxTokens(defaultMaxTokens: Int, targetTokenCount: Int) -> Int {
        return min(
            defaultMaxTokens,
            max(minimumGeneratedCodes, targetTokenCount * maxTokenMultiplier)
        )
    }

    func postFirstStreamingChunkSize(baseChunkSize: Int) -> Int {
        max(baseChunkSize, baseChunkSize * postFirstStreamChunkMultiplier)
    }

    var booleanFlags: [String: Bool] {
        [
            "custom_profile_baseline": self == .baseline,
            "custom_profile_balanced_short": self == .balancedShort,
            "custom_profile_conservative_short": self == .conservativeShort,
            "custom_profile_fast_short": self == .fastShort,
        ]
    }
}

struct Qwen3TokenBudgetPolicy: Sendable {
    let name: String
    let maxTokenMultiplier: Int
    let minimumGeneratedCodes: Int
    let usesDefaultMaxTokens: Bool

    init(
        name: String,
        maxTokenMultiplier: Int,
        minimumGeneratedCodes: Int,
        usesDefaultMaxTokens: Bool = false
    ) {
        self.name = name
        self.maxTokenMultiplier = maxTokenMultiplier
        self.minimumGeneratedCodes = minimumGeneratedCodes
        self.usesDefaultMaxTokens = usesDefaultMaxTokens
    }

    static let officialQuality = Qwen3TokenBudgetPolicy(
        name: "official-quality-max-new-tokens",
        maxTokenMultiplier: 0,
        minimumGeneratedCodes: 0,
        usesDefaultMaxTokens: true
    )

    func effectiveMaxTokens(defaultMaxTokens: Int, targetTokenCount: Int) -> Int {
        if usesDefaultMaxTokens {
            return defaultMaxTokens
        }
        return min(
            defaultMaxTokens,
            max(minimumGeneratedCodes, targetTokenCount * maxTokenMultiplier)
        )
    }
}

enum Qwen3GenerationSpeedProfile: String, Sendable {
    case current
    case legacy123Memory = "legacy123-memory"
    case adaptiveFailureOnly = "adaptive-failure-only"
    case balancedAllModes = "balanced-all-modes"

    static func resolve(
        explicitProfile: String? = nil
    ) -> Qwen3GenerationSpeedProfile {
        if let explicitProfile = explicitProfile?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitProfile.isEmpty {
            return Qwen3GenerationSpeedProfile(rawValue: explicitProfile) ?? .current
        }

        return .current
    }

    func tokenBudgetPolicy(
        mode: Qwen3StreamingGenerationMode,
        customVoiceProfile: Qwen3CustomVoiceGenerationProfile
    ) -> Qwen3TokenBudgetPolicy {
        switch self {
        case .current:
            return .officialQuality
        case .legacy123Memory, .adaptiveFailureOnly:
            if mode == .custom {
                return Qwen3TokenBudgetPolicy(
                    name: "custom-\(customVoiceProfile.rawValue)",
                    maxTokenMultiplier: customVoiceProfile.maxTokenMultiplier,
                    minimumGeneratedCodes: customVoiceProfile.minimumGeneratedCodes
                )
            }
            return Qwen3TokenBudgetPolicy(
                name: "baseline",
                maxTokenMultiplier: 6,
                minimumGeneratedCodes: 75
            )
        case .balancedAllModes:
            if mode == .custom {
                return Qwen3TokenBudgetPolicy(
                    name: "balanced-all-modes-custom",
                    maxTokenMultiplier: Qwen3CustomVoiceGenerationProfile.balancedShort.maxTokenMultiplier,
                    minimumGeneratedCodes: Qwen3CustomVoiceGenerationProfile.balancedShort.minimumGeneratedCodes
                )
            }
            return Qwen3TokenBudgetPolicy(
                name: "balanced-all-modes-\(mode.rawValue)",
                maxTokenMultiplier: 5,
                minimumGeneratedCodes: 60
            )
        }
    }

    var booleanFlags: [String: Bool] {
        [
            "generation_speed_profile_current": self == .current,
            "generation_speed_profile_legacy123_memory": self == .legacy123Memory,
            "generation_speed_profile_adaptive_failure_only": self == .adaptiveFailureOnly,
            "generation_speed_profile_balanced_all_modes": self == .balancedAllModes,
        ]
    }
}

enum Qwen3StreamingGenerationMode: String, Sendable {
    case custom
    case design
    case clone
    case generic

    var timingPrefix: String? {
        switch self {
        case .custom:
            return "custom"
        case .design:
            return "design"
        case .clone:
            return "clone"
        case .generic:
            return nil
        }
    }

    func postFirstStreamChunkMultiplier(customVoiceProfile: Qwen3CustomVoiceGenerationProfile) -> Int {
        switch self {
        case .custom:
            return customVoiceProfile.postFirstStreamChunkMultiplier
        case .design, .clone:
            return 2
        case .generic:
            return 1
        }
    }

    func postFirstStreamingChunkSize(
        baseChunkSize: Int,
        customVoiceProfile: Qwen3CustomVoiceGenerationProfile
    ) -> Int {
        max(
            baseChunkSize,
            baseChunkSize * postFirstStreamChunkMultiplier(customVoiceProfile: customVoiceProfile)
        )
    }
}

enum Qwen3TextConditioningMode: String, Sendable {
    case streamingTrailingText = "streaming_trailing_text"
    case fullTextNonStreaming = "full_text_non_streaming"

    /// The layout a request actually prepared, as `text_conditioning_mode`
    /// records it (P05-08). Custom and Design honor the requested mode; a
    /// clone ignores it: ICL always lays the full target text over the
    /// reference codes, and a speaker-only clone always streams its trailing
    /// text. `cloneInContextLearning` is nil for a request that is no clone.
    static func recordedLabel(
        requested: Qwen3TextConditioningMode,
        cloneInContextLearning: Bool?
    ) -> String {
        switch cloneInContextLearning {
        case true?: "icl_full_text_overlay"
        case false?: Self.streamingTrailingText.rawValue
        case nil: requested.rawValue
        }
    }
}

enum Qwen3StreamStepEvalPolicy: String, Sendable {
    case full
    case pipelined
    case eosOnly = "eos-only"
    case deferred

    /// Stage 1 P2a: `.pipelined` is the production default. It submits the
    /// step graph with `asyncEval` and performs the previous chunk's
    /// materialization and channel sends before the token/EOS reads, so host
    /// and channel work overlap the in-flight GPU step. Unlike the null
    /// `.eosOnly`/`.deferred` variants (SAMPLER-001: moving the same sync to
    /// a later read with nothing in between), real work fills the gap.
    /// `.full` remains the synchronous diagnostic for exact per-stage
    /// attribution.
    static func resolve(
        explicitPolicy: String? = nil
    ) -> Qwen3StreamStepEvalPolicy {
        if let explicitPolicy = explicitPolicy?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
           !explicitPolicy.isEmpty {
            return Qwen3StreamStepEvalPolicy(rawValue: explicitPolicy) ?? .pipelined
        }

        return .pipelined
    }

    var booleanFlags: [String: Bool] {
        [
            "stream_step_eval_policy_full": self == .full,
            "stream_step_eval_policy_pipelined": self == .pipelined,
            "stream_step_eval_policy_eos_only": self == .eosOnly,
            "stream_step_eval_policy_deferred": self == .deferred,
        ]
    }

}
