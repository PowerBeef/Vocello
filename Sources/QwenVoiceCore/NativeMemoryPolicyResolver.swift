import Foundation
import MLX
import os
@preconcurrency import VocelloQwen3Core

public enum NativeMemoryPolicyResolver {
    private static let oneGB = 1_024 * 1_024 * 1_024

    /// The tier for a machine with `physicalMemoryBytes` of RAM. The default is
    /// the machine policy reads: the real RAM, or the smaller Mac that
    /// `QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB` emulates (audit #11).
    public static func deviceClass(
        physicalMemoryBytes: UInt64 = NativeHostMemoryEmulation.effectivePhysicalMemoryBytes(),
        isIPhone: Bool = {
            #if os(iOS)
            return true
            #else
            return false
            #endif
        }()
    ) -> NativeDeviceMemoryClass {
        // Diagnostic override (opt-in env, read in-process through
        // `RuntimeDebugGate`): force a tier so the constrained-tier code paths
        // run and memory pressure is measurable on any hardware. nil ⇒ real tier.
        if let forced = NativeDeviceClassGate.resolvedForcedClass {
            return forced
        }
        if isIPhone {
            return .iPhonePro
        }
        if physicalMemoryBytes <= UInt64(10 * oneGB) {
            return .floor8GBMac
        }
        if physicalMemoryBytes <= UInt64(24 * oneGB) {
            return .mid16GBMac
        }
        return .highMemoryMac
    }

    public static func policy(
        deviceClass: NativeDeviceMemoryClass = deviceClass(),
        mode: GenerationMode,
        isBatch: Bool
    ) -> NativeMemoryPolicy {
        switch deviceClass {
        case .floor8GBMac:
            return NativeMemoryPolicy(
                name: "floor_8gb_mac_\(mode.rawValue)_\(isBatch ? "batch" : "single")",
                deviceClass: deviceClass,
                cacheLimitBytes: 256 * 1_024 * 1_024,
                clearCacheAfterGeneration: !isBatch,
                clearMLXCacheOnStreamChunkEmit: true,
                mlxTokenMemoryClearCadence: 50,
                unloadAfterIdleSeconds: 120
            )
        case .mid16GBMac:
            return NativeMemoryPolicy(
                name: "mid_16gb_mac_\(mode.rawValue)_\(isBatch ? "batch" : "single")",
                deviceClass: deviceClass,
                cacheLimitBytes: 512 * 1_024 * 1_024,
                clearCacheAfterGeneration: false,
                clearMLXCacheOnStreamChunkEmit: true,
                mlxTokenMemoryClearCadence: 50,
                unloadAfterIdleSeconds: 600
            )
        case .highMemoryMac:
            // Unload after idle on this tier too (AUD-10, maintainer decision
            // 2026-09-24): warming follows intent (entering Studio or
            // generating), so a finite window keeps browsing from pinning the
            // weights. The window is the longest of the Mac tiers (floor 2 min,
            // mid 10 min) because the trade favours latency here: 2-3 GB of
            // idle weights is a small share of 32 GB or more, while an unload
            // makes the next take pay a cold start (model load plus prewarm).
            // Kernel pressure trims this tier as it does the others.
            return NativeMemoryPolicy(
                name: "high_memory_mac_\(mode.rawValue)_\(isBatch ? "batch" : "single")",
                deviceClass: deviceClass,
                cacheLimitBytes: 1_024 * 1_024 * 1_024,
                clearCacheAfterGeneration: false,
                clearMLXCacheOnStreamChunkEmit: false,
                mlxTokenMemoryClearCadence: 200,
                unloadAfterIdleSeconds: 1_800
            )
        case .iPhonePro:
            let cacheLimitBytes = debugMegabytesOverride(
                "QVOICE_IOS_MLX_CACHE_LIMIT_MB"
            ) ?? 128 * 1_024 * 1_024
            let memoryLimitBytes = debugMegabytesOverride(
                "QVOICE_IOS_MLX_MEMORY_LIMIT_MB"
            )
            return NativeMemoryPolicy(
                name: "iphone_pro_\(mode.rawValue)_\(isBatch ? "batch" : "single")",
                deviceClass: deviceClass,
                cacheLimitBytes: cacheLimitBytes,
                memoryLimitBytes: memoryLimitBytes,
                clearCacheAfterGeneration: true,
                clearMLXCacheOnStreamChunkEmit: true,
                mlxTokenMemoryClearCadence: 50,
                unloadAfterIdleSeconds: 30
            )
        }
    }

    public static func apply(_ policy: NativeMemoryPolicy) {
        // MLX exposes process-wide allocator limits. Resolve these once at the
        // host boundary before model preparation; request-varying Qwen cache
        // behavior is carried separately by `memoryConfiguration(for:)`.
        Memory.cacheLimit = policy.cacheLimitBytes
        if let memoryLimitBytes = policy.memoryLimitBytes {
            Memory.memoryLimit = memoryLimitBytes
        }
    }

    public static func memoryConfiguration(
        for policy: NativeMemoryPolicy,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> VocelloQwen3MemoryConfiguration {
        VocelloQwen3MemoryConfiguration(
            clearCacheOnStreamChunk: policy.clearMLXCacheOnStreamChunkEmit,
            tokenMemoryClearCadence: policy.mlxTokenMemoryClearCadence,
            talkerKVGeneratedWindow: resolvedTalkerKVGeneratedWindow(environment: environment)
        )
    }

    /// Free-form notes describing the active MLX/Metal memory policy so each
    /// telemetry row self-identifies the substrate it ran under.
    public static func currentPolicyNotes(for policy: NativeMemoryPolicy) -> [String: String] {
        let environment = ProcessInfo.processInfo.environment
        var notes: [String: String] = [
            "mlxCacheLimitMB": String(policy.cacheLimitBytes / (1_024 * 1_024)),
            "mlxTokenMemoryClearCadence": String(policy.mlxTokenMemoryClearCadence),
            "mlxClearCacheAfterGeneration": String(policy.clearCacheAfterGeneration),
            "mlxClearCacheOnStreamChunkEmit": String(policy.clearMLXCacheOnStreamChunkEmit),
            "talkerKVWindow": RuntimeDebugGate.value(
                for: "QVOICE_TALKER_KV_WINDOW",
                environment: environment
            ) ?? "default"
        ]
        if let memoryLimitBytes = policy.memoryLimitBytes {
            notes["mlxMemoryLimitMB"] = String(memoryLimitBytes / (1_024 * 1_024))
        }
        return notes
    }

    /// Generated-audio-token window for the sliding-window talker KV cache, from
    /// `QVOICE_TALKER_KV_WINDOW` (a positive integer enables it; absent/invalid =
    /// disabled → unbounded KVCacheSimple). Used for Mac-CLI testing + the window
    /// sweep before the per-tier defaults land.
    public static func resolvedTalkerKVGeneratedWindow(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Int? {
        guard let raw = RuntimeDebugGate.value(
            for: "QVOICE_TALKER_KV_WINDOW",
            environment: environment
        )?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            let window = Int(raw), window > 0
        else {
            return nil
        }
        return window
    }

    public static func minimumStreamingInterval(
        for policy: NativeMemoryPolicy,
        request: GenerationRequest
    ) -> Double {
        if request.batchTotal != nil {
            return 0.8
        }

        switch policy.deviceClass {
        case .floor8GBMac, .iPhonePro:
            return 0.6
        case .mid16GBMac, .highMemoryMac:
            return 0.4
        }
    }

    public static func effectiveStreamingInterval(
        requested: Double?,
        request: GenerationRequest,
        policy: NativeMemoryPolicy
    ) -> Double {
        let adaptiveInterval = minimumStreamingInterval(for: policy, request: request)
        guard let requested else {
            return adaptiveInterval
        }
        guard policy.deviceClass == .floor8GBMac || policy.deviceClass == .iPhonePro || request.batchTotal != nil else {
            return requested
        }
        return max(requested, adaptiveInterval)
    }

    public static func cloneCacheCapacity(deviceClass: NativeDeviceMemoryClass = deviceClass()) -> Int {
        switch deviceClass {
        case .floor8GBMac, .iPhonePro:
            // Down from 2 to 1 on the lowest-RAM tier. Holding two
            // primed clone references in memory simultaneously costs
            // ~200-400 MB of peak RSS during the second reference's
            // prime, which on an 8 GB Mac can be the difference
            // between a smooth generation and an OOM-bound stall.
            // The on-disk clone-normalization cache (introduced in
            // a sibling commit) covers the case where a user toggles
            // between two references repeatedly — they pay the prime
            // again on switch but the audio normalization step
            // (the bulkier one) reuses cached parquet.
            return 1
        case .mid16GBMac:
            return 8
        case .highMemoryMac:
            return 16
        }
    }

    public static func snapshot() -> NativeMLXMemorySnapshot {
        let snapshot = Memory.snapshot()
        return NativeMLXMemorySnapshot(
            activeMB: bytesToMB(snapshot.activeMemory),
            cacheMB: bytesToMB(snapshot.cacheMemory),
            peakMB: bytesToMB(snapshot.peakMemory)
        )
    }

    /// Exact per-stage MLX peaks (audit #3 part 2), opt-in with
    /// `QWENVOICE_MLX_STAGE_PEAKS=1`, a production-affecting diagnostic: it
    /// needs the internal-diagnostics build and `QWENVOICE_DEBUG`, and the
    /// row's runtime-debug provenance names it, because it changes what MLX's
    /// raw peak counter reads mid-request (`AudioGenerationInfo.peakMemoryUsage`
    /// becomes the peak since the last stage). MLX keeps one process-wide peak counter,
    /// reset at each request's start, so a stage snapshot's `peakMB` is the
    /// request's peak so far and a stage that set no new high has no peak of
    /// its own. With the knob, each stage snapshot (`stageSnapshot()`) reads
    /// the peak since the previous stage and resets the counter: the stage's
    /// exact peak (`stagePeakMB`) is the largest of that peak, the active
    /// memory at the previous reset and the active memory now, and `peakMB`
    /// stays the request's running maximum. Off by default: a reset in the
    /// middle of a request races the generation task's allocations for a few
    /// microseconds, and the gate compares the per-request peak exactly (seeded
    /// runs repeat it to the megabyte), so default evidence keeps MLX's own
    /// uninterrupted counter.
    public static let stagePeaksEnabled: Bool =
        RuntimeDebugGate.value(for: "QWENVOICE_MLX_STAGE_PEAKS") == "1"

    private struct StagePeakState: Sendable {
        var cumulativePeakBytes = 0
        var activeAtResetBytes = 0
    }

    private static let stagePeakState = OSAllocatedUnfairLock(initialState: StagePeakState())

    public static func resetPeakMemory() {
        stagePeakState.withLock { state in
            Memory.peakMemory = 0
            state = StagePeakState(cumulativePeakBytes: 0, activeAtResetBytes: Memory.activeMemory)
        }
    }

    /// The snapshot a generation stage records in `mlxMemoryByStage`: the
    /// plain `snapshot()` unless `stagePeaksEnabled`.
    public static func stageSnapshot() -> NativeMLXMemorySnapshot {
        guard stagePeaksEnabled else { return snapshot() }
        return stagePeakState.withLock { state in
            let current = Memory.snapshot()
            let stagePeak = Self.stagePeak(
                peakSinceReset: current.peakMemory,
                activeAtReset: state.activeAtResetBytes,
                activeNow: current.activeMemory
            )
            state.cumulativePeakBytes = max(state.cumulativePeakBytes, stagePeak)
            Memory.peakMemory = 0
            state.activeAtResetBytes = Memory.activeMemory
            return NativeMLXMemorySnapshot(
                activeMB: bytesToMB(current.activeMemory),
                cacheMB: bytesToMB(current.cacheMemory),
                peakMB: bytesToMB(state.cumulativePeakBytes),
                stagePeakMB: bytesToMB(stagePeak)
            )
        }
    }

    /// A stage's exact MLX peak: the counter's peak since the last reset can
    /// read below memory that was already active at that reset (the setter
    /// resets it to 0), so the active memory at the reset and now bound it.
    static func stagePeak(peakSinceReset: Int, activeAtReset: Int, activeNow: Int) -> Int {
        max(peakSinceReset, activeAtReset, activeNow)
    }

    private static func bytesToMB(_ bytes: Int) -> Double {
        Double(bytes) / Double(1_024 * 1_024)
    }

    // Runtime experimentation override (off unless the env var is set). Now available on
    // the Release device build too (project rule: debug capabilities are runtime-gated, not
    // compiled out) so MLX cache / memory-limit tuning can be exercised on hardware.
    private static func debugMegabytesOverride(
        _ key: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Int? {
        guard let rawValue = RuntimeDebugGate.value(for: key, environment: environment)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              let megabytes = Int(rawValue),
              megabytes > 0 else {
            return nil
        }
        return megabytes * 1_024 * 1_024
    }

}

/// The process-wide MLX allocator side effects of the engine's memory lifecycle:
/// applying a tier's cache policy before a load and clearing the buffer cache on
/// a trim. Production always uses `.live`; lifecycle tests pass `.inert` so the
/// core test bundle, which the ThreadSanitizer lane runs, never touches MLX.
struct NativeMLXAllocatorControl: Sendable {
    let applyPolicy: @Sendable (NativeMemoryPolicy) -> Void
    let clearCache: @Sendable () -> Void

    static let live = NativeMLXAllocatorControl(
        applyPolicy: { NativeMemoryPolicyResolver.apply($0) },
        clearCache: { Memory.clearCache() }
    )

    static let inert = NativeMLXAllocatorControl(applyPolicy: { _ in }, clearCache: {})
}
