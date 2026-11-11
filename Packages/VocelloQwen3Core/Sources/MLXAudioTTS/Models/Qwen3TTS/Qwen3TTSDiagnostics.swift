// Diagnostic records and throughput arithmetic of the Qwen3-TTS runtime.
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

/// Bounded, audio/path-free records emitted only by explicit codec replay.
/// MLX counters are allocator measurements, not physical footprint or RSS.
struct CodecReplayMemoryObservation: Encodable {
    enum Arm: String, Codable { case incremental, full }
    enum Stage: String, Codable { case started, materialized, afterCachePolicy, finished }
    let event = "codec_replay_memory"
    let arm: Arm
    let stage: Stage
    let completedFrames: Int
    let timestampUnixMS: Int64
    let activeBytes: Int
    let cacheBytes: Int
    let peakBytes: Int
    let cacheLimitBytes: Int

    static func shouldSample(index: Int, count: Int) -> Bool {
        // At most 17 sampled chunks, independent of trace duration/partition.
        index % max(1, (count + 15) / 16) == 0 || index == count - 1
    }

    static func capture(arm: Arm, stage: Stage, completedFrames: Int) -> Self {
        let snapshot = Memory.snapshot()
        return Self(arm: arm, stage: stage, completedFrames: completedFrames,
                    timestampUnixMS: Int64(Date().timeIntervalSince1970 * 1_000),
                    activeBytes: snapshot.activeMemory, cacheBytes: snapshot.cacheMemory,
                    peakBytes: snapshot.peakMemory, cacheLimitBytes: Memory.cacheLimit)
    }

    func writeToStandardError() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try FileHandle.standardError.write(contentsOf: encoder.encode(self) + Data([0x0A]))
    }
}

/// TEL-001: estimate K+V talker cache bytes for the effective sequence length.
func estimatedKVCacheFootprintMB(layers: Int, heads: Int, seq: Int, headDim: Int, dtypeBytes: Int) -> Double {
    let bytes = 2 * layers * heads * seq * headDim * dtypeBytes
    return Double(bytes) / Double(1_024 * 1_024)
}

/// The `.info` throughput of one generation span. The span is measured on
/// ContinuousClock: native.md forbids `Date()` for any throughput figure, and
/// `tokensPerSecond` is published (audit #60).
enum Qwen3GenerationThroughput {
    static func info(
        generationTokenCount: Int,
        span: Duration,
        peakMemoryUsage: Double
    ) -> AudioGenerationInfo {
        let generateTime = span.totalSeconds
        return AudioGenerationInfo(
            promptTokenCount: 0, // Not tracked for VoiceDesign
            generationTokenCount: generationTokenCount,
            prefillTime: 0, // Included in generateTime
            generateTime: generateTime,
            tokensPerSecond: Double(generationTokenCount) / generateTime,
            peakMemoryUsage: peakMemoryUsage
        )
    }
}
