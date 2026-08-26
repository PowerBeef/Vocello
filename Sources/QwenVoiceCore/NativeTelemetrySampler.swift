import Darwin
import Foundation
import Metal

/// Thermal-state snapshot captured at the start and end of a generation, plus the
/// worst state observed while the sampler was running.
public struct ThermalStateSnapshot: Hashable, Codable, Sendable {
    public let start: String
    public let end: String
    public let worst: String

    public init(start: ProcessInfo.ThermalState, end: ProcessInfo.ThermalState, worst: ProcessInfo.ThermalState) {
        self.start = Self.string(for: start)
        self.end = Self.string(for: end)
        self.worst = Self.string(for: worst)
    }

    internal static func string(for state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown(\(state.rawValue))"
        }
    }
}

/// Identifies why a telemetry sample was captured. Periodic samples describe the
/// configured cadence; boundary samples are explicit snapshots around lifecycle
/// transitions where a periodic timer could otherwise miss a short-lived peak.
public enum TelemetrySampleKind: String, Hashable, Codable, Sendable {
    case start
    case periodic
    case boundary
    case stop
}

/// Stable process ownership for memory samples. The absolute uptime timestamp
/// lets app/XPC/engine samplers align rows without sharing a relative clock.
public enum TelemetryProcessRole: String, Hashable, Codable, Sendable {
    case app
    case engine
    case engineService = "engine-service"
    case currentProcess = "current-process"
}

/// One lifecycle checkpoint, optionally satisfied by one of several terminal
/// alternatives. Names are code-owned and bounded; they never contain user data.
public struct TelemetryBoundaryRequirement: Hashable, Codable, Sendable {
    public let name: String
    public let alternatives: [String]

    public init(name: String, alternatives: [String]) {
        self.name = String(name.prefix(64))
        self.alternatives = Array(alternatives.prefix(8)).map { String($0.prefix(64)) }
    }

    public static let engineGeneration: [TelemetryBoundaryRequirement] = [
        .init(name: "preparation-start", alternatives: ["before_preparation"]),
        .init(name: "mode-preparation-start", alternatives: ["before_mode_preparation"]),
        .init(name: "mode-preparation-end", alternatives: ["after_mode_preparation"]),
        .init(name: "prewarm-start", alternatives: ["before_prewarm", "prewarm_skipped"]),
        .init(name: "prewarm-end", alternatives: ["after_prewarm", "prewarm_skipped"]),
        .init(name: "model-load-start", alternatives: ["before_model_load"]),
        .init(name: "model-load-end", alternatives: ["after_model_load"]),
        .init(name: "preparation-end", alternatives: ["after_preparation"]),
        .init(name: "session-start", alternatives: ["session_start"]),
        .init(name: "first-output", alternatives: ["first_chunk", "final_audio_materialized"]),
        .init(name: "final-audio-materialized", alternatives: ["final_audio_materialized"]),
        .init(name: "final-wav-start", alternatives: ["before_final_wav"]),
        .init(name: "audio-qc-start", alternatives: ["before_audio_qc"]),
        .init(name: "audio-qc-end", alternatives: ["after_audio_qc"]),
        .init(name: "final-wav-end", alternatives: ["after_final_wav"]),
        .init(
            name: "post-generation-memory-action-start",
            alternatives: ["post_generation", "before_post_generation_trim"]
        ),
        .init(
            name: "post-generation-memory-action-end",
            alternatives: ["post_generation", "post_generation_trim"]
        ),
        .init(
            name: "terminal",
            alternatives: [
                "terminal_success",
                "terminal_failure",
                "terminal_cancelled",
                "preparation_failed",
            ]
        ),
    ]

    public static let appGeneration: [TelemetryBoundaryRequirement] = [
        .init(name: "app-submit", alternatives: ["app_submit"]),
        .init(name: "app-terminal", alternatives: ["app_terminal"]),
    ]
}

public struct TelemetrySample: Hashable, Codable, Sendable {
    public let tMS: Int
    public let tNS: UInt64?
    /// Intended capture time for a periodic sample, relative to the shared
    /// generation clock. nil for lifecycle/boundary snapshots.
    public let scheduledElapsedNS: UInt64?
    /// Actual capture time relative to the shared generation clock.
    public let capturedElapsedNS: UInt64?
    /// Absolute monotonic system-uptime clock. Unlike `capturedElapsedNS`, this
    /// value is comparable across app, XPC, and engine processes on one boot.
    public let capturedUptimeNS: UInt64?
    /// `max(capturedElapsedNS - scheduledElapsedNS, 0)` for periodic samples.
    public let latenessNS: UInt64?
    public let kind: TelemetrySampleKind?
    /// Bounded, code-owned boundary label. Never contains user content.
    public let boundary: String?
    public let processRole: TelemetryProcessRole?
    /// Legacy aggregate flag. Schema v8 defines success as a core task-memory
    /// capture; use the split fields below for exact coverage accounting.
    public let captureSucceeded: Bool?
    public let memoryCaptureSucceeded: Bool?
    public let threadCaptureSucceeded: Bool?
    public let headroomCaptureSucceeded: Bool?
    public let metalCaptureSucceeded: Bool?
    public let totalDeviceRAMMB: Double?
    public let residentMB: Double?
    public let physFootprintMB: Double?
    public let compressedMB: Double?
    public let headroomMB: Double?
    public let gpuAllocatedMB: Double?
    public let gpuRecommendedWorkingSetMB: Double?
    public let impliedProcessLimitMB: Double?
    public let gpuWorkingSetUsageRatio: Double?
    public let threads: Int
    public let thermalState: String?
    public var stage: String?
    public var chunkIndex: Int?

    /// v5 compatibility alias. New v7 rows encode `capturedElapsedNS` instead.
    @available(*, deprecated, renamed: "capturedElapsedNS")
    public var actualElapsedNS: UInt64? { capturedElapsedNS }

    public init(
        tMS: Int,
        tNS: UInt64? = nil,
        scheduledElapsedNS: UInt64? = nil,
        capturedElapsedNS: UInt64? = nil,
        capturedUptimeNS: UInt64? = nil,
        latenessNS: UInt64? = nil,
        kind: TelemetrySampleKind? = nil,
        boundary: String? = nil,
        processRole: TelemetryProcessRole? = nil,
        captureSucceeded: Bool? = nil,
        memoryCaptureSucceeded: Bool? = nil,
        threadCaptureSucceeded: Bool? = nil,
        headroomCaptureSucceeded: Bool? = nil,
        metalCaptureSucceeded: Bool? = nil,
        totalDeviceRAMMB: Double? = nil,
        actualElapsedNS: UInt64? = nil,
        residentMB: Double?,
        physFootprintMB: Double?,
        compressedMB: Double?,
        headroomMB: Double?,
        gpuAllocatedMB: Double?,
        gpuRecommendedWorkingSetMB: Double?,
        impliedProcessLimitMB: Double? = nil,
        gpuWorkingSetUsageRatio: Double? = nil,
        threads: Int,
        thermalState: String? = nil,
        stage: String? = nil,
        chunkIndex: Int? = nil
    ) {
        self.tMS = tMS
        self.tNS = tNS
        self.scheduledElapsedNS = scheduledElapsedNS
        self.capturedElapsedNS = capturedElapsedNS ?? actualElapsedNS ?? tNS
        self.capturedUptimeNS = capturedUptimeNS
        self.latenessNS = latenessNS
        self.kind = kind
        self.boundary = boundary
        self.processRole = processRole
        self.captureSucceeded = captureSucceeded
        self.memoryCaptureSucceeded = memoryCaptureSucceeded ?? captureSucceeded
        self.threadCaptureSucceeded = threadCaptureSucceeded
        self.headroomCaptureSucceeded = headroomCaptureSucceeded
        self.metalCaptureSucceeded = metalCaptureSucceeded
        self.totalDeviceRAMMB = totalDeviceRAMMB
        self.residentMB = residentMB
        self.physFootprintMB = physFootprintMB
        self.compressedMB = compressedMB
        self.headroomMB = headroomMB
        self.gpuAllocatedMB = gpuAllocatedMB
        self.gpuRecommendedWorkingSetMB = gpuRecommendedWorkingSetMB
        self.impliedProcessLimitMB = impliedProcessLimitMB
        self.gpuWorkingSetUsageRatio = gpuWorkingSetUsageRatio
        self.threads = threads
        self.thermalState = thermalState
        self.stage = stage
        self.chunkIndex = chunkIndex
    }

    enum CodingKeys: String, CodingKey {
        case tMS
        case tNS
        case scheduledElapsedNS
        case capturedElapsedNS
        case capturedUptimeNS
        case latenessNS
        case kind
        case boundary
        case processRole
        case captureSucceeded
        case memoryCaptureSucceeded
        case threadCaptureSucceeded
        case headroomCaptureSucceeded
        case metalCaptureSucceeded
        case totalDeviceRAMMB
        // Decode-only compatibility key emitted by schema v5/v6.
        case actualElapsedNS
        case residentMB
        case physFootprintMB
        case compressedMB
        case headroomMB
        case gpuAllocatedMB
        case gpuRecommendedWorkingSetMB
        case impliedProcessLimitMB
        case gpuWorkingSetUsageRatio
        case threads
        case thermalState
        case stage
        case chunkIndex
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.tMS = try container.decode(Int.self, forKey: .tMS)
        self.tNS = try container.decodeIfPresent(UInt64.self, forKey: .tNS)
        self.scheduledElapsedNS = try container.decodeIfPresent(UInt64.self, forKey: .scheduledElapsedNS)
        self.capturedElapsedNS = try container.decodeIfPresent(UInt64.self, forKey: .capturedElapsedNS)
            ?? container.decodeIfPresent(UInt64.self, forKey: .actualElapsedNS)
            ?? tNS
        self.capturedUptimeNS = try container.decodeIfPresent(UInt64.self, forKey: .capturedUptimeNS)
        self.latenessNS = try container.decodeIfPresent(UInt64.self, forKey: .latenessNS)
        self.kind = try container.decodeIfPresent(TelemetrySampleKind.self, forKey: .kind)
        self.boundary = try container.decodeIfPresent(String.self, forKey: .boundary)
        self.processRole = try container.decodeIfPresent(TelemetryProcessRole.self, forKey: .processRole)
        self.captureSucceeded = try container.decodeIfPresent(Bool.self, forKey: .captureSucceeded)
        self.memoryCaptureSucceeded = try container.decodeIfPresent(Bool.self, forKey: .memoryCaptureSucceeded)
            ?? captureSucceeded
        self.threadCaptureSucceeded = try container.decodeIfPresent(Bool.self, forKey: .threadCaptureSucceeded)
        self.headroomCaptureSucceeded = try container.decodeIfPresent(Bool.self, forKey: .headroomCaptureSucceeded)
        self.metalCaptureSucceeded = try container.decodeIfPresent(Bool.self, forKey: .metalCaptureSucceeded)
        self.totalDeviceRAMMB = try container.decodeIfPresent(Double.self, forKey: .totalDeviceRAMMB)
        self.residentMB = try container.decodeIfPresent(Double.self, forKey: .residentMB)
        self.physFootprintMB = try container.decodeIfPresent(Double.self, forKey: .physFootprintMB)
        self.compressedMB = try container.decodeIfPresent(Double.self, forKey: .compressedMB)
        self.headroomMB = try container.decodeIfPresent(Double.self, forKey: .headroomMB)
        self.gpuAllocatedMB = try container.decodeIfPresent(Double.self, forKey: .gpuAllocatedMB)
        self.gpuRecommendedWorkingSetMB = try container.decodeIfPresent(Double.self, forKey: .gpuRecommendedWorkingSetMB)
        self.impliedProcessLimitMB = try container.decodeIfPresent(Double.self, forKey: .impliedProcessLimitMB)
        self.gpuWorkingSetUsageRatio = try container.decodeIfPresent(Double.self, forKey: .gpuWorkingSetUsageRatio)
        self.threads = try container.decode(Int.self, forKey: .threads)
        self.thermalState = try container.decodeIfPresent(String.self, forKey: .thermalState)
        self.stage = try container.decodeIfPresent(String.self, forKey: .stage)
        self.chunkIndex = try container.decodeIfPresent(Int.self, forKey: .chunkIndex)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(tMS, forKey: .tMS)
        try container.encodeIfPresent(tNS, forKey: .tNS)
        try container.encodeIfPresent(scheduledElapsedNS, forKey: .scheduledElapsedNS)
        try container.encodeIfPresent(capturedElapsedNS, forKey: .capturedElapsedNS)
        try container.encodeIfPresent(capturedUptimeNS, forKey: .capturedUptimeNS)
        try container.encodeIfPresent(latenessNS, forKey: .latenessNS)
        try container.encodeIfPresent(kind, forKey: .kind)
        try container.encodeIfPresent(boundary, forKey: .boundary)
        try container.encodeIfPresent(processRole, forKey: .processRole)
        try container.encodeIfPresent(captureSucceeded, forKey: .captureSucceeded)
        try container.encodeIfPresent(memoryCaptureSucceeded, forKey: .memoryCaptureSucceeded)
        try container.encodeIfPresent(threadCaptureSucceeded, forKey: .threadCaptureSucceeded)
        try container.encodeIfPresent(headroomCaptureSucceeded, forKey: .headroomCaptureSucceeded)
        try container.encodeIfPresent(metalCaptureSucceeded, forKey: .metalCaptureSucceeded)
        try container.encodeIfPresent(totalDeviceRAMMB, forKey: .totalDeviceRAMMB)
        try container.encodeIfPresent(residentMB, forKey: .residentMB)
        try container.encodeIfPresent(physFootprintMB, forKey: .physFootprintMB)
        try container.encodeIfPresent(compressedMB, forKey: .compressedMB)
        try container.encodeIfPresent(headroomMB, forKey: .headroomMB)
        try container.encodeIfPresent(gpuAllocatedMB, forKey: .gpuAllocatedMB)
        try container.encodeIfPresent(gpuRecommendedWorkingSetMB, forKey: .gpuRecommendedWorkingSetMB)
        try container.encodeIfPresent(impliedProcessLimitMB, forKey: .impliedProcessLimitMB)
        try container.encodeIfPresent(gpuWorkingSetUsageRatio, forKey: .gpuWorkingSetUsageRatio)
        try container.encode(threads, forKey: .threads)
        try container.encodeIfPresent(thermalState, forKey: .thermalState)
        try container.encodeIfPresent(stage, forKey: .stage)
        try container.encodeIfPresent(chunkIndex, forKey: .chunkIndex)
    }
}

/// Low-cost, process-scoped resource usage accumulated over one sampler lifetime.
/// Values are deltas, never host identifiers or absolute system counters.
public struct ProcessResourceUsageDelta: Hashable, Codable, Sendable {
    public let userCPUTimeMS: Double
    public let systemCPUTimeMS: Double
    public let minorPageFaults: Int64
    public let majorPageFaults: Int64
    public let voluntaryContextSwitches: Int64
    public let involuntaryContextSwitches: Int64
    public let blockInputOperations: Int64
    public let blockOutputOperations: Int64

    public init(
        userCPUTimeMS: Double,
        systemCPUTimeMS: Double,
        minorPageFaults: Int64,
        majorPageFaults: Int64,
        voluntaryContextSwitches: Int64,
        involuntaryContextSwitches: Int64,
        blockInputOperations: Int64,
        blockOutputOperations: Int64
    ) {
        self.userCPUTimeMS = userCPUTimeMS
        self.systemCPUTimeMS = systemCPUTimeMS
        self.minorPageFaults = minorPageFaults
        self.majorPageFaults = majorPageFaults
        self.voluntaryContextSwitches = voluntaryContextSwitches
        self.involuntaryContextSwitches = involuntaryContextSwitches
        self.blockInputOperations = blockInputOperations
        self.blockOutputOperations = blockOutputOperations
    }

    init(start: ProcessResourceUsageSnapshot, end: ProcessResourceUsageSnapshot) {
        self.init(
            userCPUTimeMS: max(0, end.userCPUTimeMS - start.userCPUTimeMS),
            systemCPUTimeMS: max(0, end.systemCPUTimeMS - start.systemCPUTimeMS),
            minorPageFaults: max(0, end.minorPageFaults - start.minorPageFaults),
            majorPageFaults: max(0, end.majorPageFaults - start.majorPageFaults),
            voluntaryContextSwitches: max(0, end.voluntaryContextSwitches - start.voluntaryContextSwitches),
            involuntaryContextSwitches: max(0, end.involuntaryContextSwitches - start.involuntaryContextSwitches),
            blockInputOperations: max(0, end.blockInputOperations - start.blockInputOperations),
            blockOutputOperations: max(0, end.blockOutputOperations - start.blockOutputOperations)
        )
    }
}

struct ProcessResourceUsageSnapshot: Equatable, Sendable {
    let userCPUTimeMS: Double
    let systemCPUTimeMS: Double
    let minorPageFaults: Int64
    let majorPageFaults: Int64
    let voluntaryContextSwitches: Int64
    let involuntaryContextSwitches: Int64
    let blockInputOperations: Int64
    let blockOutputOperations: Int64
}

/// Privacy-safe environment context captured once at generation start. It
/// deliberately excludes host names, device names, paths, and hardware IDs.
public struct RunEnvironmentSnapshot: Hashable, Codable, Sendable {
    public let loadAverage1Minute: Double?
    public let loadAverage5Minutes: Double?
    public let loadAverage15Minutes: Double?
    public let freeStorageBytes: UInt64?
    public let uptimeSeconds: Double
    public let lowPowerModeEnabled: Bool
    public let thermalState: String
    public let runtimeDebugProvenance: RuntimeDebugProvenance?

    public init(
        loadAverage1Minute: Double? = nil,
        loadAverage5Minutes: Double? = nil,
        loadAverage15Minutes: Double? = nil,
        freeStorageBytes: UInt64? = nil,
        uptimeSeconds: Double,
        lowPowerModeEnabled: Bool,
        thermalState: String,
        runtimeDebugProvenance: RuntimeDebugProvenance? = nil
    ) {
        self.loadAverage1Minute = loadAverage1Minute
        self.loadAverage5Minutes = loadAverage5Minutes
        self.loadAverage15Minutes = loadAverage15Minutes
        self.freeStorageBytes = freeStorageBytes
        self.uptimeSeconds = uptimeSeconds
        self.lowPowerModeEnabled = lowPowerModeEnabled
        self.thermalState = thermalState
        self.runtimeDebugProvenance = runtimeDebugProvenance
    }

    static func capture() -> RunEnvironmentSnapshot {
        var loadValues = [Double](repeating: 0, count: 3)
        let loadCount = loadValues.withUnsafeMutableBufferPointer { buffer -> Int in
            guard let baseAddress = buffer.baseAddress else { return 0 }
            return Int(getloadavg(baseAddress, Int32(buffer.count)))
        }
        let freeStorageBytes: UInt64? = {
            guard let attributes = try? FileManager.default.attributesOfFileSystem(
                forPath: NSHomeDirectory()
            ) else { return nil }
            return (attributes[.systemFreeSize] as? NSNumber)?.uint64Value
        }()
        let processInfo = ProcessInfo.processInfo
        return RunEnvironmentSnapshot(
            loadAverage1Minute: loadCount > 0 ? loadValues[0] : nil,
            loadAverage5Minutes: loadCount > 1 ? loadValues[1] : nil,
            loadAverage15Minutes: loadCount > 2 ? loadValues[2] : nil,
            freeStorageBytes: freeStorageBytes,
            uptimeSeconds: processInfo.systemUptime,
            lowPowerModeEnabled: processInfo.isLowPowerModeEnabled,
            thermalState: ThermalStateSnapshot.string(for: processInfo.thermalState),
            runtimeDebugProvenance: RuntimeDebugGate.provenance()
        )
    }
}

/// Same-sample memory budget evidence. Keeping footprint, headroom, process
/// limit, and Metal values together prevents invalid "worst case" arithmetic
/// that combines extrema captured at different moments.
public struct AlignedMemoryBudgetSnapshot: Hashable, Codable, Sendable {
    public let tMS: Int
    public let capturedElapsedNS: UInt64?
    public let capturedUptimeNS: UInt64?
    public let processRole: TelemetryProcessRole?
    public let residentMB: Double?
    public let physFootprintMB: Double?
    public let compressedMB: Double?
    public let headroomMB: Double?
    public let impliedProcessLimitMB: Double?
    public let gpuAllocatedMB: Double?
    public let gpuRecommendedWorkingSetMB: Double?
    public let gpuWorkingSetUsageRatio: Double?
    public let iOSPressureBand: IOSMemoryPressureBand?

    public init(sample: TelemetrySample, iOSPressureBand: IOSMemoryPressureBand? = nil) {
        self.tMS = sample.tMS
        self.capturedElapsedNS = sample.capturedElapsedNS
        self.capturedUptimeNS = sample.capturedUptimeNS
        self.processRole = sample.processRole
        self.residentMB = sample.residentMB
        self.physFootprintMB = sample.physFootprintMB
        self.compressedMB = sample.compressedMB
        self.headroomMB = sample.headroomMB
        self.impliedProcessLimitMB = sample.impliedProcessLimitMB
            ?? Self.sum(sample.physFootprintMB, sample.headroomMB)
        self.gpuAllocatedMB = sample.gpuAllocatedMB
        self.gpuRecommendedWorkingSetMB = sample.gpuRecommendedWorkingSetMB
        self.gpuWorkingSetUsageRatio = sample.gpuWorkingSetUsageRatio
            ?? Self.ratio(sample.gpuAllocatedMB, sample.gpuRecommendedWorkingSetMB)
        self.iOSPressureBand = iOSPressureBand
    }

    private static func sum(_ lhs: Double?, _ rhs: Double?) -> Double? {
        guard let lhs, let rhs else { return nil }
        return lhs + rhs
    }

    private static func ratio(_ numerator: Double?, _ denominator: Double?) -> Double? {
        guard let numerator, let denominator, denominator > 0 else { return nil }
        return numerator / denominator
    }
}

/// Coverage is explicit so a successful thread enumeration can no longer hide
/// failed process-memory capture, and unavailable Metal/headroom readings remain
/// distinguishable from zero use.
public struct TelemetryCaptureCoverage: Hashable, Codable, Sendable {
    public let totalSampleCount: Int
    public let memorySuccessfulSampleCount: Int
    public let memoryCaptureFailureCount: Int
    public let memoryCoverageRatio: Double
    public let threadSuccessfulSampleCount: Int
    public let threadCaptureFailureCount: Int
    public let threadCoverageRatio: Double
    public let headroomSuccessfulSampleCount: Int
    public let headroomCoverageRatio: Double
    public let metalSuccessfulSampleCount: Int
    public let metalCoverageRatio: Double
    public let processResourceCaptureSucceeded: Bool
    public let processResourceCaptureFailureCount: Int

    public init(
        totalSampleCount: Int,
        memorySuccessfulSampleCount: Int,
        threadSuccessfulSampleCount: Int,
        headroomSuccessfulSampleCount: Int,
        metalSuccessfulSampleCount: Int,
        processResourceCaptureSucceeded: Bool
    ) {
        let denominator = max(totalSampleCount, 1)
        self.totalSampleCount = totalSampleCount
        self.memorySuccessfulSampleCount = memorySuccessfulSampleCount
        self.memoryCaptureFailureCount = max(totalSampleCount - memorySuccessfulSampleCount, 0)
        self.memoryCoverageRatio = totalSampleCount > 0
            ? Double(memorySuccessfulSampleCount) / Double(denominator)
            : 0
        self.threadSuccessfulSampleCount = threadSuccessfulSampleCount
        self.threadCaptureFailureCount = max(totalSampleCount - threadSuccessfulSampleCount, 0)
        self.threadCoverageRatio = totalSampleCount > 0
            ? Double(threadSuccessfulSampleCount) / Double(denominator)
            : 0
        self.headroomSuccessfulSampleCount = headroomSuccessfulSampleCount
        self.headroomCoverageRatio = totalSampleCount > 0
            ? Double(headroomSuccessfulSampleCount) / Double(denominator)
            : 0
        self.metalSuccessfulSampleCount = metalSuccessfulSampleCount
        self.metalCoverageRatio = totalSampleCount > 0
            ? Double(metalSuccessfulSampleCount) / Double(denominator)
            : 0
        self.processResourceCaptureSucceeded = processResourceCaptureSucceeded
        self.processResourceCaptureFailureCount = processResourceCaptureSucceeded ? 0 : 1
    }
}

public struct TelemetryBoundaryCoverage: Hashable, Codable, Sendable {
    public let requiredBoundaryNames: [String]
    public let satisfiedBoundaryNames: [String]
    public let missingBoundaryNames: [String]
    public let coverageRatio: Double

    public init(requirements: [TelemetryBoundaryRequirement], observedBoundaries: Set<String>) {
        self.requiredBoundaryNames = requirements.map(\.name)
        self.satisfiedBoundaryNames = requirements.compactMap { requirement in
            requirement.alternatives.contains(where: observedBoundaries.contains)
                ? requirement.name
                : nil
        }
        let satisfied = Set(satisfiedBoundaryNames)
        self.missingBoundaryNames = requiredBoundaryNames.filter { !satisfied.contains($0) }
        self.coverageRatio = requirements.isEmpty
            ? 1
            : Double(satisfiedBoundaryNames.count) / Double(requirements.count)
    }
}

public struct TelemetrySummary: Hashable, Codable, Sendable {
    public let processRole: TelemetryProcessRole?
    public let residentStartMB: Double?
    public let residentEndMB: Double?
    public let residentPeakMB: Double?
    public let residentDeltaMB: Double?
    public let physFootprintStartMB: Double?
    public let physFootprintEndMB: Double?
    public let physFootprintPeakMB: Double?
    public let physFootprintDeltaMB: Double?
    public let compressedStartMB: Double?
    public let compressedEndMB: Double?
    public let compressedPeakMB: Double?
    public let compressedDeltaMB: Double?
    public let headroomStartMB: Double?
    public let headroomEndMB: Double?
    public let headroomMinMB: Double?
    public let headroomDeltaMB: Double?
    public let gpuAllocatedStartMB: Double?
    public let gpuAllocatedEndMB: Double?
    public let gpuAllocatedPeakMB: Double?
    public let gpuAllocatedDeltaMB: Double?
    public let gpuRecommendedWorkingSetMB: Double?
    public let gpuWorkingSetUsageRatioStart: Double?
    public let gpuWorkingSetUsageRatioEnd: Double?
    public let gpuWorkingSetUsageRatioPeak: Double?
    public let totalDeviceRAMMB: Double?
    public let memoryAtStart: AlignedMemoryBudgetSnapshot?
    public let memoryAtEnd: AlignedMemoryBudgetSnapshot?
    public let memoryAtPeakPhysFootprint: AlignedMemoryBudgetSnapshot?
    public let memoryAtMinimumHeadroom: AlignedMemoryBudgetSnapshot?
    public let timeToPeakMS: Int?
    public let sampleCount: Int
    public let stageMarks: [NativeTelemetryStageMark]
    public let thermalState: ThermalStateSnapshot?
    /// v7 cadence/capture metadata. nil on legacy summaries.
    public let targetIntervalNS: UInt64?
    public let effectiveIntervalNS: UInt64?
    public let maximumIntervalNS: UInt64?
    public let maximumDriftNS: UInt64?
    public let maximumLatenessNS: UInt64?
    public let periodicSampleCount: Int?
    public let boundarySampleCount: Int?
    public let captureFailureCount: Int?
    /// Number of periodic cadence deadlines intentionally skipped because the
    /// sampler was already more than one interval late. This keeps the cadence
    /// anchored to the generation clock without issuing burst catch-up samples.
    public let missedPeriodicDeadlineCount: Int?
    public let processResourceUsage: ProcessResourceUsageDelta?
    public let resourceCaptureSucceeded: Bool?
    public let resourceCaptureFailureCount: Int?
    public let runEnvironment: RunEnvironmentSnapshot?
    public let captureCoverage: TelemetryCaptureCoverage?
    public let boundaryCoverage: TelemetryBoundaryCoverage?

    public init(
        residentStartMB: Double?,
        residentEndMB: Double?,
        residentPeakMB: Double?,
        physFootprintPeakMB: Double?,
        compressedPeakMB: Double?,
        headroomStartMB: Double?,
        headroomEndMB: Double?,
        headroomMinMB: Double?,
        gpuAllocatedPeakMB: Double?,
        gpuRecommendedWorkingSetMB: Double?,
        gpuWorkingSetUsageRatioPeak: Double?,
        timeToPeakMS: Int?,
        sampleCount: Int,
        stageMarks: [NativeTelemetryStageMark],
        thermalState: ThermalStateSnapshot?,
        targetIntervalNS: UInt64? = nil,
        effectiveIntervalNS: UInt64? = nil,
        maximumIntervalNS: UInt64? = nil,
        maximumDriftNS: UInt64? = nil,
        maximumLatenessNS: UInt64? = nil,
        periodicSampleCount: Int? = nil,
        boundarySampleCount: Int? = nil,
        captureFailureCount: Int? = nil,
        missedPeriodicDeadlineCount: Int? = nil,
        processResourceUsage: ProcessResourceUsageDelta? = nil,
        resourceCaptureSucceeded: Bool? = nil,
        resourceCaptureFailureCount: Int? = nil,
        runEnvironment: RunEnvironmentSnapshot? = nil,
        processRole: TelemetryProcessRole? = nil,
        residentDeltaMB: Double? = nil,
        physFootprintStartMB: Double? = nil,
        physFootprintEndMB: Double? = nil,
        physFootprintDeltaMB: Double? = nil,
        compressedStartMB: Double? = nil,
        compressedEndMB: Double? = nil,
        compressedDeltaMB: Double? = nil,
        headroomDeltaMB: Double? = nil,
        gpuAllocatedStartMB: Double? = nil,
        gpuAllocatedEndMB: Double? = nil,
        gpuAllocatedDeltaMB: Double? = nil,
        gpuWorkingSetUsageRatioStart: Double? = nil,
        gpuWorkingSetUsageRatioEnd: Double? = nil,
        totalDeviceRAMMB: Double? = nil,
        memoryAtStart: AlignedMemoryBudgetSnapshot? = nil,
        memoryAtEnd: AlignedMemoryBudgetSnapshot? = nil,
        memoryAtPeakPhysFootprint: AlignedMemoryBudgetSnapshot? = nil,
        memoryAtMinimumHeadroom: AlignedMemoryBudgetSnapshot? = nil,
        captureCoverage: TelemetryCaptureCoverage? = nil,
        boundaryCoverage: TelemetryBoundaryCoverage? = nil
    ) {
        self.processRole = processRole
        self.residentStartMB = residentStartMB
        self.residentEndMB = residentEndMB
        self.residentPeakMB = residentPeakMB
        self.residentDeltaMB = residentDeltaMB
        self.physFootprintStartMB = physFootprintStartMB
        self.physFootprintEndMB = physFootprintEndMB
        self.physFootprintPeakMB = physFootprintPeakMB
        self.physFootprintDeltaMB = physFootprintDeltaMB
        self.compressedStartMB = compressedStartMB
        self.compressedEndMB = compressedEndMB
        self.compressedPeakMB = compressedPeakMB
        self.compressedDeltaMB = compressedDeltaMB
        self.headroomStartMB = headroomStartMB
        self.headroomEndMB = headroomEndMB
        self.headroomMinMB = headroomMinMB
        self.headroomDeltaMB = headroomDeltaMB
        self.gpuAllocatedStartMB = gpuAllocatedStartMB
        self.gpuAllocatedEndMB = gpuAllocatedEndMB
        self.gpuAllocatedPeakMB = gpuAllocatedPeakMB
        self.gpuAllocatedDeltaMB = gpuAllocatedDeltaMB
        self.gpuRecommendedWorkingSetMB = gpuRecommendedWorkingSetMB
        self.gpuWorkingSetUsageRatioStart = gpuWorkingSetUsageRatioStart
        self.gpuWorkingSetUsageRatioEnd = gpuWorkingSetUsageRatioEnd
        self.gpuWorkingSetUsageRatioPeak = gpuWorkingSetUsageRatioPeak
        self.totalDeviceRAMMB = totalDeviceRAMMB
        self.memoryAtStart = memoryAtStart
        self.memoryAtEnd = memoryAtEnd
        self.memoryAtPeakPhysFootprint = memoryAtPeakPhysFootprint
        self.memoryAtMinimumHeadroom = memoryAtMinimumHeadroom
        self.timeToPeakMS = timeToPeakMS
        self.sampleCount = sampleCount
        self.stageMarks = stageMarks
        self.thermalState = thermalState
        self.targetIntervalNS = targetIntervalNS
        self.effectiveIntervalNS = effectiveIntervalNS
        self.maximumIntervalNS = maximumIntervalNS
        self.maximumDriftNS = maximumDriftNS
        self.maximumLatenessNS = maximumLatenessNS
        self.periodicSampleCount = periodicSampleCount
        self.boundarySampleCount = boundarySampleCount
        self.captureFailureCount = captureFailureCount
        self.missedPeriodicDeadlineCount = missedPeriodicDeadlineCount
        self.processResourceUsage = processResourceUsage
        self.resourceCaptureSucceeded = resourceCaptureSucceeded
        self.resourceCaptureFailureCount = resourceCaptureFailureCount
        self.runEnvironment = runEnvironment
        self.captureCoverage = captureCoverage
        self.boundaryCoverage = boundaryCoverage
    }

    public static func empty(stageMarks: [NativeTelemetryStageMark]) -> TelemetrySummary {
        TelemetrySummary(
            residentStartMB: nil,
            residentEndMB: nil,
            residentPeakMB: nil,
            physFootprintPeakMB: nil,
            compressedPeakMB: nil,
            headroomStartMB: nil,
            headroomEndMB: nil,
            headroomMinMB: nil,
            gpuAllocatedPeakMB: nil,
            gpuRecommendedWorkingSetMB: nil,
            gpuWorkingSetUsageRatioPeak: nil,
            timeToPeakMS: nil,
            sampleCount: 0,
            stageMarks: stageMarks,
            thermalState: nil
        )
    }
}

public actor NativeTelemetrySampler {
    private typealias StopResult = (summary: TelemetrySummary, samples: [TelemetrySample])

    private let clock: NativeTelemetryClock
    private let sampleIntervalMS: Int
    private let processRole: TelemetryProcessRole
    private let boundaryRequirements: [TelemetryBoundaryRequirement]
    private let buffer = TelemetrySampleBuffer()
    private var samplingTask: Task<Void, Never>?
    private var resourceUsageStart: ProcessResourceUsageSnapshot?
    private var runEnvironmentStart: RunEnvironmentSnapshot?
    private var stoppedResult: StopResult?
    /// Resolved once per generation instead of per sample. `IOSMemorySnapshot.capture`
    /// defaults `device:` to `MTLCreateSystemDefaultDevice()`, which would otherwise
    /// allocate a fresh Metal device object on every tick — wasteful on restricted
    /// hardware where the sampler runs alongside generation.
    private let metalDevice: MTLDevice? = MTLCreateSystemDefaultDevice()

    public init(
        clock: NativeTelemetryClock,
        sampleIntervalMS: Int,
        processRole: TelemetryProcessRole = .currentProcess,
        boundaryRequirements: [TelemetryBoundaryRequirement] = []
    ) {
        self.clock = clock
        self.sampleIntervalMS = sampleIntervalMS
        self.processRole = processRole
        self.boundaryRequirements = boundaryRequirements
    }

    public func start() async {
        guard samplingTask == nil, stoppedResult == nil else { return }
        resourceUsageStart = Self.captureProcessResourceUsage()
        runEnvironmentStart = RunEnvironmentSnapshot.capture()
        let startSample = Self.captureSample(
            clock: clock,
            device: metalDevice,
            processRole: processRole,
            kind: .start
        )
        await buffer.append(sample: startSample)
        let intervalNanos = UInt64(max(sampleIntervalMS, 1)) * 1_000_000
        let buffer = self.buffer
        let clock = self.clock
        let device = self.metalDevice
        let processRole = self.processRole
        samplingTask = Task.detached(priority: .utility) {
            var scheduledElapsedNS = Self.addingClamped(
                startSample.capturedElapsedNS ?? startSample.tNS ?? 0,
                intervalNanos
            )
            while !Task.isCancelled {
                let (_, beforeSleepNS) = clock.now()
                if scheduledElapsedNS > beforeSleepNS {
                    try? await Task.sleep(nanoseconds: scheduledElapsedNS - beforeSleepNS)
                }
                guard !Task.isCancelled else { break }
                let sample = Self.captureSample(
                    clock: clock,
                    device: device,
                    processRole: processRole,
                    kind: .periodic,
                    scheduledElapsedNS: scheduledElapsedNS
                )
                await buffer.append(sample: sample)
                let capturedElapsedNS = sample.capturedElapsedNS ?? sample.tNS ?? scheduledElapsedNS
                let schedule = Self.nextPeriodicSchedule(
                    after: scheduledElapsedNS,
                    capturedElapsedNS: capturedElapsedNS,
                    intervalNanos: intervalNanos
                )
                if schedule.missedDeadlines > 0 {
                    await buffer.addMissedDeadlines(schedule.missedDeadlines)
                }
                scheduledElapsedNS = schedule.nextScheduledElapsedNS
            }
        }
    }

    /// Capture a lifecycle boundary without changing the periodic cadence.
    /// Boundary names must be code-owned constants; the sampler bounds their size
    /// so accidental dynamic content cannot expand raw telemetry indefinitely.
    public func captureBoundary(_ name: String) async {
        guard samplingTask != nil else { return }
        let boundedName = String(name.prefix(64))
        await buffer.append(
            sample: Self.captureSample(
                clock: clock,
                device: metalDevice,
                processRole: processRole,
                kind: .boundary,
                boundary: boundedName
            )
        )
    }

    public func stop(stageMarks: [NativeTelemetryStageMark]) async -> (summary: TelemetrySummary, samples: [TelemetrySample]) {
        if let stoppedResult { return stoppedResult }
        samplingTask?.cancel()
        _ = await samplingTask?.value
        samplingTask = nil
        // A short generation can stop just after a cadence deadline while the
        // detached task is still waiting to resume. Capture that already-due
        // deadline once before the terminal sample. Older unobserved deadlines
        // remain explicitly missed, so this closes only the cancellation race
        // and cannot disguise sustained sampler starvation.
        let beforeStop = await buffer.snapshot()
        if let startElapsedNS = beforeStop.samples.first(where: { $0.kind == .start })?
                .capturedElapsedNS {
            let stopElapsedNS = clock.now().ns
            let adjustment = Self.periodicStopAdjustment(
                startElapsedNS: startElapsedNS,
                stopElapsedNS: stopElapsedNS,
                intervalNanos: UInt64(max(sampleIntervalMS, 1)) * 1_000_000,
                periodicSampleCount: beforeStop.samples.count(where: { $0.kind == .periodic }),
                missedDeadlineCount: beforeStop.missedDeadlines
            )
            if adjustment.additionalMissedDeadlines > 0 {
                await buffer.addMissedDeadlines(adjustment.additionalMissedDeadlines)
            }
            if let scheduledElapsedNS = adjustment.scheduledElapsedNS {
                await buffer.append(
                    sample: Self.captureSample(
                        clock: clock,
                        device: metalDevice,
                        processRole: processRole,
                        kind: .periodic,
                        scheduledElapsedNS: scheduledElapsedNS
                    )
                )
            }
        }
        await buffer.append(
            sample: Self.captureSample(
                clock: clock,
                device: metalDevice,
                processRole: processRole,
                kind: .stop
            )
        )
        let bufferSnapshot = await buffer.snapshot()
        let rawSamples = bufferSnapshot.samples
        let samples = Self.decorate(samples: rawSamples, stageMarks: stageMarks)
        let resourceUsage = resourceUsageStart.flatMap { start in
            Self.captureProcessResourceUsage().map { end in
                ProcessResourceUsageDelta(start: start, end: end)
            }
        }
        let summary = Self.summarize(
            samples: samples,
            stageMarks: stageMarks,
            targetIntervalNS: UInt64(max(sampleIntervalMS, 1)) * 1_000_000,
            missedPeriodicDeadlineCount: bufferSnapshot.missedDeadlines,
            processResourceUsage: resourceUsage,
            runEnvironment: runEnvironmentStart,
            boundaryRequirements: boundaryRequirements
        )
        let result = (summary: summary, samples: samples)
        stoppedResult = result
        return result
    }

    static func decorate(
        samples: [TelemetrySample],
        stageMarks: [NativeTelemetryStageMark]
    ) -> [TelemetrySample] {
        let sortedMarks = stageMarks.sorted(by: NativeTelemetryStageMark.chronologicallyPrecedes)
        let sortedSamples = samples.enumerated().sorted { lhs, rhs in
            let lhsNS = lhs.element.capturedElapsedNS ?? lhs.element.tNS
            let rhsNS = rhs.element.capturedElapsedNS ?? rhs.element.tNS
            if let lhsNS, let rhsNS, lhsNS != rhsNS { return lhsNS < rhsNS }
            if lhs.element.tMS != rhs.element.tMS { return lhs.element.tMS < rhs.element.tMS }
            return lhs.offset < rhs.offset
        }.map(\.element)

        var nextMarkIndex = 0
        var currentStage: String?
        var currentChunkIndex: Int?
        return sortedSamples.map { sample in
            var sample = sample
            while nextMarkIndex < sortedMarks.count,
                  Self.mark(mark: sortedMarks[nextMarkIndex], occursNoLaterThan: sample) {
                let mark = sortedMarks[nextMarkIndex]
                currentStage = mark.stage
                currentChunkIndex = mark.metadata["chunk_index"].flatMap(Int.init)
                nextMarkIndex += 1
            }
            sample.stage = currentStage
            sample.chunkIndex = currentChunkIndex
            return sample
        }
    }

    static func summarize(
        samples: [TelemetrySample],
        stageMarks: [NativeTelemetryStageMark],
        targetIntervalNS: UInt64?,
        missedPeriodicDeadlineCount: Int = 0,
        processResourceUsage: ProcessResourceUsageDelta? = nil,
        runEnvironment: RunEnvironmentSnapshot? = nil,
        boundaryRequirements: [TelemetryBoundaryRequirement] = []
    ) -> TelemetrySummary {
        let memorySamples = samples.filter(Self.memoryCaptureSucceeded)
        let memoryStartSample = memorySamples.first
        let memoryEndSample = memorySamples.last
        let residentStartMB = memoryStartSample?.residentMB
        let residentEndMB = memoryEndSample?.residentMB
        let residentPeakSample = memorySamples.max { lhs, rhs in
            (lhs.residentMB ?? 0) < (rhs.residentMB ?? 0)
        }
        // timeToPeak tracks the physFootprint peak — the figure Jetsam judges —
        // falling back to the RSS peak only when phys_footprint is unavailable.
        let physFootprintPeakSample = memorySamples.max { lhs, rhs in
            (lhs.physFootprintMB ?? 0) < (rhs.physFootprintMB ?? 0)
        }
        let peakSample = (physFootprintPeakSample?.physFootprintMB != nil)
            ? physFootprintPeakSample
            : residentPeakSample
        let physFootprintStartMB = memoryStartSample?.physFootprintMB
        let physFootprintEndMB = memoryEndSample?.physFootprintMB
        let physFootprintPeakMB = memorySamples.compactMap(\.physFootprintMB).max()
        let compressedStartMB = memoryStartSample?.compressedMB
        let compressedEndMB = memoryEndSample?.compressedMB
        let compressedPeakMB = memorySamples.compactMap(\.compressedMB).max()
        let headroomSamples = samples.filter { $0.headroomMB != nil }
        let headroomStartMB = headroomSamples.first?.headroomMB
        let headroomEndMB = headroomSamples.last?.headroomMB
        let headroomMinMB = samples.compactMap(\.headroomMB).min()
        let minimumHeadroomSample = samples
            .filter { $0.headroomMB != nil }
            .min { ($0.headroomMB ?? .greatestFiniteMagnitude) < ($1.headroomMB ?? .greatestFiniteMagnitude) }
        let metalSamples = samples.filter { $0.gpuAllocatedMB != nil }
        let gpuAllocatedStartMB = metalSamples.first?.gpuAllocatedMB
        let gpuAllocatedEndMB = metalSamples.last?.gpuAllocatedMB
        let gpuAllocatedPeakMB = samples.compactMap(\.gpuAllocatedMB).max()
        let gpuRecommendedWorkingSetMB = samples.compactMap(\.gpuRecommendedWorkingSetMB).max()
        let gpuWorkingSetUsageRatioPeak = samples.compactMap { sample -> Double? in
            guard let allocated = sample.gpuAllocatedMB,
                  let recommended = sample.gpuRecommendedWorkingSetMB,
                  recommended > 0 else { return nil }
            return allocated / recommended
        }.max()
        let gpuWorkingSetUsageRatioStart = Self.metalRatio(for: metalSamples.first)
        let gpuWorkingSetUsageRatioEnd = Self.metalRatio(for: metalSamples.last)

        let memorySuccessfulSampleCount = samples.count(where: Self.memoryCaptureSucceeded)
        let threadSuccessfulSampleCount = samples.count(where: Self.threadCaptureSucceeded)
        let headroomSuccessfulSampleCount = samples.count(where: { $0.headroomMB != nil })
        let metalSuccessfulSampleCount = samples.count(where: { $0.gpuAllocatedMB != nil })
        let captureCoverage = TelemetryCaptureCoverage(
            totalSampleCount: samples.count,
            memorySuccessfulSampleCount: memorySuccessfulSampleCount,
            threadSuccessfulSampleCount: threadSuccessfulSampleCount,
            headroomSuccessfulSampleCount: headroomSuccessfulSampleCount,
            metalSuccessfulSampleCount: metalSuccessfulSampleCount,
            processResourceCaptureSucceeded: processResourceUsage != nil
        )
        let observedBoundaries = Set(samples.compactMap(\.boundary))
        let boundaryCoverage = TelemetryBoundaryCoverage(
            requirements: boundaryRequirements,
            observedBoundaries: observedBoundaries
        )

        let cadenceSamples = samples.filter { $0.kind == .start || $0.kind == .periodic }
        let capturedIntervals = zip(cadenceSamples, cadenceSamples.dropFirst()).compactMap { previous, current -> UInt64? in
            guard let previousNS = previous.capturedElapsedNS ?? previous.tNS,
                  let currentNS = current.capturedElapsedNS ?? current.tNS,
                  currentNS >= previousNS else { return nil }
            return currentNS - previousNS
        }
        // Drift is phase error against the anchored scheduled deadline, not
        // interval jitter. `effectiveIntervalNS`/`maximumIntervalNS` retain the
        // separate observed-interval view.
        let maximumDriftNS = samples.compactMap(\.latenessNS).max()

        let thermalSnapshot: ThermalStateSnapshot? = {
            guard let first = samples.first?.thermalState,
                  let last = samples.last?.thermalState else { return nil }
            let worst = samples.compactMap(\.thermalState).max { lhs, rhs in
                thermalRank(lhs) < thermalRank(rhs)
            } ?? first
            return ThermalStateSnapshot(start: state(from: first), end: state(from: last), worst: state(from: worst))
        }()

        return TelemetrySummary(
            residentStartMB: residentStartMB,
            residentEndMB: residentEndMB,
            residentPeakMB: residentPeakSample?.residentMB,
            physFootprintPeakMB: physFootprintPeakMB,
            compressedPeakMB: compressedPeakMB,
            headroomStartMB: headroomStartMB,
            headroomEndMB: headroomEndMB,
            headroomMinMB: headroomMinMB,
            gpuAllocatedPeakMB: gpuAllocatedPeakMB,
            gpuRecommendedWorkingSetMB: gpuRecommendedWorkingSetMB,
            gpuWorkingSetUsageRatioPeak: gpuWorkingSetUsageRatioPeak,
            timeToPeakMS: peakSample?.tMS,
            sampleCount: samples.count,
            stageMarks: stageMarks,
            thermalState: thermalSnapshot,
            targetIntervalNS: targetIntervalNS,
            effectiveIntervalNS: Self.median(capturedIntervals),
            maximumIntervalNS: capturedIntervals.max(),
            maximumDriftNS: maximumDriftNS,
            maximumLatenessNS: samples.compactMap(\.latenessNS).max(),
            periodicSampleCount: samples.count(where: { $0.kind == .periodic }),
            boundarySampleCount: samples.count(where: { $0.kind == .boundary }),
            captureFailureCount: captureCoverage.memoryCaptureFailureCount,
            missedPeriodicDeadlineCount: missedPeriodicDeadlineCount,
            processResourceUsage: processResourceUsage,
            resourceCaptureSucceeded: captureCoverage.processResourceCaptureSucceeded,
            resourceCaptureFailureCount: captureCoverage.processResourceCaptureFailureCount,
            runEnvironment: runEnvironment,
            processRole: samples.compactMap(\.processRole).first,
            residentDeltaMB: Self.delta(start: residentStartMB, end: residentEndMB),
            physFootprintStartMB: physFootprintStartMB,
            physFootprintEndMB: physFootprintEndMB,
            physFootprintDeltaMB: Self.delta(start: physFootprintStartMB, end: physFootprintEndMB),
            compressedStartMB: compressedStartMB,
            compressedEndMB: compressedEndMB,
            compressedDeltaMB: Self.delta(start: compressedStartMB, end: compressedEndMB),
            headroomDeltaMB: Self.delta(start: headroomStartMB, end: headroomEndMB),
            gpuAllocatedStartMB: gpuAllocatedStartMB,
            gpuAllocatedEndMB: gpuAllocatedEndMB,
            gpuAllocatedDeltaMB: Self.delta(start: gpuAllocatedStartMB, end: gpuAllocatedEndMB),
            gpuWorkingSetUsageRatioStart: gpuWorkingSetUsageRatioStart,
            gpuWorkingSetUsageRatioEnd: gpuWorkingSetUsageRatioEnd,
            totalDeviceRAMMB: samples.compactMap(\.totalDeviceRAMMB).first,
            memoryAtStart: memoryStartSample.map(Self.alignedMemorySnapshot),
            memoryAtEnd: memoryEndSample.map(Self.alignedMemorySnapshot),
            memoryAtPeakPhysFootprint: physFootprintPeakSample.map(Self.alignedMemorySnapshot),
            memoryAtMinimumHeadroom: minimumHeadroomSample.map(Self.alignedMemorySnapshot),
            captureCoverage: captureCoverage,
            boundaryCoverage: boundaryCoverage
        )
    }

    private static func delta(start: Double?, end: Double?) -> Double? {
        guard let start, let end else { return nil }
        return end - start
    }

    private static func memoryCaptureSucceeded(_ sample: TelemetrySample) -> Bool {
        sample.memoryCaptureSucceeded
            ?? sample.captureSucceeded
            ?? (sample.residentMB != nil || sample.physFootprintMB != nil || sample.compressedMB != nil)
    }

    private static func threadCaptureSucceeded(_ sample: TelemetrySample) -> Bool {
        sample.threadCaptureSucceeded ?? (sample.threads > 0)
    }

    private static func metalRatio(for sample: TelemetrySample?) -> Double? {
        guard let sample else { return nil }
        if let ratio = sample.gpuWorkingSetUsageRatio { return ratio }
        guard let allocated = sample.gpuAllocatedMB,
              let recommended = sample.gpuRecommendedWorkingSetMB,
              recommended > 0 else { return nil }
        return allocated / recommended
    }

    private static func alignedMemorySnapshot(_ sample: TelemetrySample) -> AlignedMemoryBudgetSnapshot {
        #if os(iOS)
        let pressureBand = IOSMemoryBudgetPolicy.iPhoneShippingDefault.worstBand(
            headroomMinMB: sample.headroomMB,
            physFootprintPeakMB: sample.physFootprintMB,
            gpuWorkingSetUsageRatioPeak: metalRatio(for: sample)
        )
        #else
        let pressureBand: IOSMemoryPressureBand? = nil
        #endif
        return AlignedMemoryBudgetSnapshot(sample: sample, iOSPressureBand: pressureBand)
    }

    private static func median(_ values: [UInt64]) -> UInt64? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        let middle = sorted.count / 2
        guard sorted.count.isMultiple(of: 2) else { return sorted[middle] }
        let lower = sorted[middle - 1]
        let upper = sorted[middle]
        return lower + ((upper - lower) / 2)
    }

    private static func mark(
        mark: NativeTelemetryStageMark,
        occursNoLaterThan sample: TelemetrySample
    ) -> Bool {
        if let markNS = mark.tNS,
           let sampleNS = sample.capturedElapsedNS ?? sample.tNS {
            return markNS <= sampleNS
        }
        return mark.tMS <= sample.tMS
    }

    private static func thermalRank(_ state: String) -> Int {
        switch state {
        case "nominal": return 0
        case "fair": return 1
        case "serious": return 2
        case "critical": return 3
        default: return -1
        }
    }

    private static func state(from string: String) -> ProcessInfo.ThermalState {
        switch string {
        case "fair": return .fair
        case "serious": return .serious
        case "critical": return .critical
        default: return .nominal
        }
    }

    private static func captureSample(
        clock: NativeTelemetryClock,
        device: MTLDevice?,
        processRole: TelemetryProcessRole,
        kind: TelemetrySampleKind,
        scheduledElapsedNS: UInt64? = nil,
        boundary: String? = nil
    ) -> TelemetrySample {
        let capturedUptimeNS = DispatchTime.now().uptimeNanoseconds
        let (ms, ns) = clock.now()
        let snapshot = IOSMemorySnapshot.capture(device: device)
        let threadCapture = threadCount()
        let memoryCaptureSucceeded = snapshot.residentBytes != nil
            || snapshot.physFootprintBytes != nil
            || snapshot.compressedBytes != nil
        return TelemetrySample(
            tMS: ms,
            tNS: ns,
            scheduledElapsedNS: scheduledElapsedNS,
            capturedElapsedNS: ns,
            capturedUptimeNS: capturedUptimeNS,
            latenessNS: scheduledElapsedNS.map { ns >= $0 ? ns - $0 : 0 },
            kind: kind,
            boundary: boundary,
            processRole: processRole,
            captureSucceeded: memoryCaptureSucceeded,
            memoryCaptureSucceeded: memoryCaptureSucceeded,
            threadCaptureSucceeded: threadCapture.succeeded,
            headroomCaptureSucceeded: snapshot.availableHeadroomBytes != nil,
            metalCaptureSucceeded: snapshot.gpuAllocatedBytes != nil,
            totalDeviceRAMMB: Double(snapshot.totalDeviceRAMBytes) / 1_048_576,
            residentMB: snapshot.residentMB,
            physFootprintMB: snapshot.physFootprintMB,
            compressedMB: snapshot.compressedMB,
            headroomMB: snapshot.availableHeadroomMB,
            gpuAllocatedMB: snapshot.gpuAllocatedMB,
            gpuRecommendedWorkingSetMB: snapshot.gpuRecommendedWorkingSetMB,
            impliedProcessLimitMB: snapshot.impliedProcessLimitMB,
            gpuWorkingSetUsageRatio: snapshot.gpuWorkingSetUsageRatio,
            threads: threadCapture.count,
            thermalState: ThermalStateSnapshot.string(for: ProcessInfo.processInfo.thermalState)
        )
    }

    private static func addingClamped(_ lhs: UInt64, _ rhs: UInt64) -> UInt64 {
        let (result, overflow) = lhs.addingReportingOverflow(rhs)
        return overflow ? UInt64.max : result
    }

    /// Advance from an anchored deadline to the first deadline strictly after
    /// capture. Deadlines already passed are counted rather than sampled in a
    /// burst, which preserves both low overhead and honest phase-drift evidence.
    static func nextPeriodicSchedule(
        after scheduledElapsedNS: UInt64,
        capturedElapsedNS: UInt64,
        intervalNanos: UInt64
    ) -> (nextScheduledElapsedNS: UInt64, missedDeadlines: Int) {
        let interval = max(intervalNanos, 1)
        let firstNext = addingClamped(scheduledElapsedNS, interval)
        guard capturedElapsedNS >= firstNext, firstNext != UInt64.max else {
            return (firstNext, 0)
        }
        let elapsedPastNext = capturedElapsedNS - firstNext
        let skipped = (elapsedPastNext / interval) + 1
        let boundedSkipped = min(skipped, UInt64(Int.max))
        let advance = interval.multipliedReportingOverflow(by: skipped)
        let next = advance.overflow
            ? UInt64.max
            : addingClamped(firstNext, advance.partialValue)
        return (next, Int(boundedSkipped))
    }

    /// Resolve cadence opportunities that became due immediately before stop.
    /// At most the newest deadline is sampled; every older gap remains a missed
    /// deadline and therefore lowers strict coverage.
    static func periodicStopAdjustment(
        startElapsedNS: UInt64,
        stopElapsedNS: UInt64,
        intervalNanos: UInt64,
        periodicSampleCount: Int,
        missedDeadlineCount: Int
    ) -> (scheduledElapsedNS: UInt64?, additionalMissedDeadlines: Int) {
        let interval = max(intervalNanos, 1)
        guard stopElapsedNS >= startElapsedNS else { return (nil, 0) }
        let dueCount = (stopElapsedNS - startElapsedNS) / interval
        let accounted = UInt64(max(periodicSampleCount, 0))
            + UInt64(max(missedDeadlineCount, 0))
        guard dueCount > accounted else { return (nil, 0) }

        let unaccounted = dueCount - accounted
        let product = interval.multipliedReportingOverflow(by: dueCount)
        let scheduled = product.overflow
            ? UInt64.max
            : addingClamped(startElapsedNS, product.partialValue)
        return (
            scheduled,
            Int(min(unaccounted - 1, UInt64(Int.max)))
        )
    }

    private static func captureProcessResourceUsage() -> ProcessResourceUsageSnapshot? {
        var usage = rusage()
        guard getrusage(RUSAGE_SELF, &usage) == 0 else { return nil }
        func milliseconds(_ value: timeval) -> Double {
            (Double(value.tv_sec) * 1_000) + (Double(value.tv_usec) / 1_000)
        }
        return ProcessResourceUsageSnapshot(
            userCPUTimeMS: milliseconds(usage.ru_utime),
            systemCPUTimeMS: milliseconds(usage.ru_stime),
            minorPageFaults: Int64(usage.ru_minflt),
            majorPageFaults: Int64(usage.ru_majflt),
            voluntaryContextSwitches: Int64(usage.ru_nvcsw),
            involuntaryContextSwitches: Int64(usage.ru_nivcsw),
            blockInputOperations: Int64(usage.ru_inblock),
            blockOutputOperations: Int64(usage.ru_oublock)
        )
    }

    private static func threadCount() -> (count: Int, succeeded: Bool) {
        var threadList: thread_act_array_t?
        var threadCount: mach_msg_type_number_t = 0
        let result = task_threads(mach_task_self_, &threadList, &threadCount)
        defer {
            if let threadList {
                vm_deallocate(
                    mach_task_self_,
                    vm_address_t(UInt(bitPattern: threadList)),
                    vm_size_t(Int(threadCount) * MemoryLayout<thread_t>.stride)
                )
            }
        }
        guard result == KERN_SUCCESS else {
            return (0, false)
        }
        return (Int(threadCount), true)
    }
}

private actor TelemetrySampleBuffer {
    private var samples: [TelemetrySample] = []
    private var missedDeadlines = 0

    func append(sample: TelemetrySample) {
        samples.append(sample)
    }

    func addMissedDeadlines(_ count: Int) {
        missedDeadlines += max(count, 0)
    }

    func snapshot() -> (samples: [TelemetrySample], missedDeadlines: Int) {
        (samples, missedDeadlines)
    }
}
