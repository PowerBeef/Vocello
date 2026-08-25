import Foundation

public struct IOSUnloadQuiescenceSample: Hashable, Codable, Sendable {
    public let sequence: Int
    public let capturedAtUptimeSeconds: Double
    public let mlx: NativeMLXMemorySnapshot
    public let process: IOSMemorySnapshot
    public let hasActiveGeneration: Bool
    public let criticalMemoryActionInFlight: Bool
    public let modelOperationInFlight: Bool
    public let generationReservationInFlight: Bool
    public let loadedModelID: String?
    public let engineLifecycle: String

    public init(
        sequence: Int,
        capturedAtUptimeSeconds: Double,
        mlx: NativeMLXMemorySnapshot,
        process: IOSMemorySnapshot,
        hasActiveGeneration: Bool,
        criticalMemoryActionInFlight: Bool,
        modelOperationInFlight: Bool,
        generationReservationInFlight: Bool,
        loadedModelID: String?,
        engineLifecycle: String
    ) {
        self.sequence = sequence
        self.capturedAtUptimeSeconds = capturedAtUptimeSeconds
        self.mlx = mlx
        self.process = process
        self.hasActiveGeneration = hasActiveGeneration
        self.criticalMemoryActionInFlight = criticalMemoryActionInFlight
        self.modelOperationInFlight = modelOperationInFlight
        self.generationReservationInFlight = generationReservationInFlight
        self.loadedModelID = loadedModelID
        self.engineLifecycle = engineLifecycle
    }
}

public enum IOSUnloadQuiescenceViolation: String, Hashable, Codable, Sendable {
    case activeGeneration = "active_generation"
    case memoryActionInFlight = "memory_action_in_flight"
    case modelOperationInFlight = "model_operation_in_flight"
    case generationReservationInFlight = "generation_reservation_in_flight"
    case modelStillLoaded = "model_still_loaded"
    case lifecycleNotIdle = "lifecycle_not_idle"
    case mlxCacheNotCleared = "mlx_cache_not_cleared"
    case mlxActiveUnstable = "mlx_active_unstable"
    case metalAllocationUnstable = "metal_allocation_unstable"
    case insufficientHeadroom = "insufficient_headroom"
    case guardedFootprintExceeded = "guarded_footprint_exceeded"
    case missingMemoryMeasurement = "missing_memory_measurement"
}

public enum IOSUnloadQuiescenceEvaluator {
    public static let stabilityToleranceMB = 32.0
    public static let maximumClearedCacheMB = 32.0
    public static let minimumHealthyHeadroomMB = 768.0
    public static let maximumGuardedFootprintMB = 4_500.0
    public static let requiredConsecutiveSamples = 3

    public static func violations(
        current: IOSUnloadQuiescenceSample,
        previous: IOSUnloadQuiescenceSample?
    ) -> Set<IOSUnloadQuiescenceViolation> {
        var result: Set<IOSUnloadQuiescenceViolation> = []
        if current.hasActiveGeneration { result.insert(.activeGeneration) }
        if current.criticalMemoryActionInFlight { result.insert(.memoryActionInFlight) }
        if current.modelOperationInFlight { result.insert(.modelOperationInFlight) }
        if current.generationReservationInFlight { result.insert(.generationReservationInFlight) }
        if current.loadedModelID != nil { result.insert(.modelStillLoaded) }
        if current.engineLifecycle != "idle" && current.engineLifecycle != "connected" {
            result.insert(.lifecycleNotIdle)
        }
        guard let active = current.mlx.activeMB,
              let cache = current.mlx.cacheMB,
              let metal = current.process.gpuAllocatedMB,
              let headroom = current.process.availableHeadroomMB,
              let footprint = current.process.physFootprintMB else {
            result.insert(.missingMemoryMeasurement)
            return result
        }
        if cache > maximumClearedCacheMB { result.insert(.mlxCacheNotCleared) }
        if headroom < minimumHealthyHeadroomMB { result.insert(.insufficientHeadroom) }
        if footprint >= maximumGuardedFootprintMB { result.insert(.guardedFootprintExceeded) }
        if let previous {
            guard let previousActive = previous.mlx.activeMB,
                  let previousMetal = previous.process.gpuAllocatedMB else {
                result.insert(.missingMemoryMeasurement)
                return result
            }
            if abs(active - previousActive) > stabilityToleranceMB {
                result.insert(.mlxActiveUnstable)
            }
            if abs(metal - previousMetal) > stabilityToleranceMB {
                result.insert(.metalAllocationUnstable)
            }
        } else {
            result.insert(.mlxActiveUnstable)
            result.insert(.metalAllocationUnstable)
        }
        return result
    }

    public static func isQuiescent(_ samples: [IOSUnloadQuiescenceSample]) -> Bool {
        guard samples.count >= requiredConsecutiveSamples + 1 else { return false }
        let firstIndex = samples.count - requiredConsecutiveSamples
        for index in firstIndex ..< samples.count {
            guard violations(
                current: samples[index],
                previous: samples[index - 1]
            ).isEmpty else { return false }
        }
        return true
    }
}
