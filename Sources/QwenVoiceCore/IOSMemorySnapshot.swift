import Darwin
import Foundation
import Metal

public enum IOSMemoryPressureBand: String, Codable, Hashable, Sendable {
    case healthy
    case guarded
    case critical

    public var severityRank: Int {
        switch self {
        case .healthy:
            return 0
        case .guarded:
            return 1
        case .critical:
            return 2
        }
    }
}

public enum NativeMemoryTrimLevel: String, Codable, Hashable, Sendable {
    case softTrim
    case hardTrim
    case fullUnload
}

public enum IOSMemoryProcessRole: String, Codable, Hashable, Sendable {
    case app
    case currentProcess
}

public struct IOSMemorySnapshot: Hashable, Codable, Sendable {
    public let processRole: IOSMemoryProcessRole
    public let pid: Int32
    public let capturedAtUptimeSeconds: Double
    public let totalDeviceRAMBytes: UInt64
    public let availableHeadroomBytes: UInt64?
    public let residentBytes: UInt64?
    public let physFootprintBytes: UInt64?
    public let compressedBytes: UInt64?
    public let gpuAllocatedBytes: UInt64?
    public let gpuRecommendedWorkingSetBytes: UInt64?
    public let hasUnifiedMemory: Bool?
    /// The kernel's physical-footprint ledger high-water mark for this process's
    /// lifetime, read in the same `task_vm_info` call as `physFootprintBytes`,
    /// so it is never below any footprint the process has had. Exact, unlike a
    /// periodic sample, but a lifetime maximum: it is a take's own peak only when
    /// it rose during that take. Never a system peak. nil when the kernel did
    /// not fill that revision of the structure.
    public let kernelPhysFootprintPeakBytes: UInt64?
    /// The graphics-tagged footprint ledger (IOAccelerator/Metal memory counted
    /// in the footprint), from the same call. nil when unavailable.
    public let graphicsFootprintBytes: UInt64?
    /// The kernel's `limit_bytes_remaining`: how far this process's footprint
    /// may still grow before its memory limit, read in the same `task_vm_info`
    /// call as `physFootprintBytes`, so the two describe one instant (audit
    /// #68), unlike `availableHeadroomBytes`, which comes from a separate
    /// `os_proc_available_memory` call. iPhone only (macOS processes run
    /// without that limit); clamped like the headroom under a simulated
    /// process limit. nil when unavailable.
    public let processLimitRemainingBytes: UInt64?

    public init(
        processRole: IOSMemoryProcessRole = .currentProcess,
        pid: Int32 = getpid(),
        capturedAtUptimeSeconds: Double = ProcessInfo.processInfo.systemUptime,
        totalDeviceRAMBytes: UInt64,
        availableHeadroomBytes: UInt64?,
        residentBytes: UInt64?,
        physFootprintBytes: UInt64?,
        compressedBytes: UInt64?,
        gpuAllocatedBytes: UInt64?,
        gpuRecommendedWorkingSetBytes: UInt64?,
        hasUnifiedMemory: Bool?,
        kernelPhysFootprintPeakBytes: UInt64? = nil,
        graphicsFootprintBytes: UInt64? = nil,
        processLimitRemainingBytes: UInt64? = nil
    ) {
        self.processRole = processRole
        self.pid = pid
        self.capturedAtUptimeSeconds = capturedAtUptimeSeconds
        self.totalDeviceRAMBytes = totalDeviceRAMBytes
        self.availableHeadroomBytes = availableHeadroomBytes
        self.residentBytes = residentBytes
        self.physFootprintBytes = physFootprintBytes
        self.compressedBytes = compressedBytes
        self.gpuAllocatedBytes = gpuAllocatedBytes
        self.gpuRecommendedWorkingSetBytes = gpuRecommendedWorkingSetBytes
        self.hasUnifiedMemory = hasUnifiedMemory
        self.kernelPhysFootprintPeakBytes = kernelPhysFootprintPeakBytes
        self.graphicsFootprintBytes = graphicsFootprintBytes
        self.processLimitRemainingBytes = processLimitRemainingBytes
    }

    public var processLimitRemainingMB: Double? {
        Self.bytesToMB(processLimitRemainingBytes)
    }

    public var kernelPhysFootprintPeakMB: Double? {
        Self.bytesToMB(kernelPhysFootprintPeakBytes)
    }

    public var graphicsFootprintMB: Double? {
        Self.bytesToMB(graphicsFootprintBytes)
    }

    public var residentMB: Double? {
        Self.bytesToMB(residentBytes)
    }

    public var physFootprintMB: Double? {
        Self.bytesToMB(physFootprintBytes)
    }

    public var compressedMB: Double? {
        Self.bytesToMB(compressedBytes)
    }

    public var availableHeadroomMB: Double? {
        Self.bytesToMB(availableHeadroomBytes)
    }

    public var impliedProcessLimitBytes: UInt64? {
        guard let physFootprintBytes, let availableHeadroomBytes else {
            return nil
        }
        return physFootprintBytes + availableHeadroomBytes
    }

    public var impliedProcessLimitMB: Double? {
        Self.bytesToMB(impliedProcessLimitBytes)
    }

    public var gpuAllocatedMB: Double? {
        Self.bytesToMB(gpuAllocatedBytes)
    }

    public var gpuRecommendedWorkingSetMB: Double? {
        Self.bytesToMB(gpuRecommendedWorkingSetBytes)
    }

    public var gpuWorkingSetUsageRatio: Double? {
        guard let gpuAllocatedBytes, let gpuRecommendedWorkingSetBytes,
              gpuRecommendedWorkingSetBytes > 0 else { return nil }
        return Double(gpuAllocatedBytes) / Double(gpuRecommendedWorkingSetBytes)
    }

    /// Dev-only restriction simulation: clamp the *effective* per-process
    /// memory limit so a bigger iPhone behaves like a smaller one (e.g. run
    /// the iPhone 15 Pro's ~5.0 GB entitled budget on a 17 Pro). Resolved
    /// once per process from `QVOICE_IOS_SIMULATED_PROCESS_LIMIT_MB`
    /// (explicit MB) or the `QVOICE_IOS_MEMORY_PROFILE` profile map. The clamp
    /// is applied to the headroom inside `capture()`, so every consumer —
    /// budget bands, aggregate admission, the clone capability gate,
    /// telemetry — sees the smaller device with no per-call-site changes.
    /// It only simulates the MEMORY dimension; GPU compute and thermal
    /// behavior of the smaller device cannot be simulated (see
    /// docs/reference/ios-engine-optimization.md §9).
    public static let simulatedProcessLimitBytes: UInt64? = {
        let environment = ProcessInfo.processInfo.environment
        if let raw = RuntimeDebugGate.value(
            for: "QVOICE_IOS_SIMULATED_PROCESS_LIMIT_MB",
            environment: environment
        ),
           let megabytes = UInt64(raw), megabytes > 0 {
            return megabytes * 1_048_576
        }
        switch RuntimeDebugGate.value(
            for: "QVOICE_IOS_MEMORY_PROFILE",
            environment: environment
        )?.lowercased() {
        case "iphone15pro":
            // Bottom of the community-measured 5.0–5.5 GB entitled band on
            // 8 GB iPhones — conservative: passing here implies passing on
            // whatever the real device grants.
            return 5_000 * 1_048_576
        case "iphone14pro":
            // 6 GB device class (iPhone 14 Pro / 15 / 15 Plus): bottom of the
            // community-measured ~3.6–4.0 GB entitled band with the
            // increased-memory-limit entitlement. Floor-feasibility evidence
            // profile for the 6 GB hardware-floor question — exploratory-only
            // classification, never canonical history.
            return 3_600 * 1_048_576
        default:
            return nil
        }
    }()

    private static let defaultMetalDevice = MTLCreateSystemDefaultDevice()

    public static func capture(
        role: IOSMemoryProcessRole = .currentProcess,
        device: MTLDevice? = nil
    ) -> IOSMemorySnapshot {
        let device = device ?? defaultMetalDevice
        let metrics = taskMemoryMetrics()
        var headroom = availableProcessMemory()
        #if os(iOS)
        var limitRemaining = metrics.limitBytesRemaining
        #else
        var limitRemaining: UInt64? = nil
        #endif
        if let simLimit = simulatedProcessLimitBytes,
           let footprint = metrics.physFootprintBytes {
            if let realHeadroom = headroom {
                let effectiveLimit = min(footprint + realHeadroom, simLimit)
                headroom = effectiveLimit > footprint ? effectiveLimit - footprint : 0
            }
            if let realRemaining = limitRemaining {
                let effectiveLimit = min(footprint + realRemaining, simLimit)
                limitRemaining = effectiveLimit > footprint ? effectiveLimit - footprint : 0
            }
        }
        // A Mac emulating the 8 GB floor (`QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB`,
        // audit #11) reports the emulated RAM and Metal working set, so the
        // store's bands and the GPU working-set ratio judge the floor's budget.
        return IOSMemorySnapshot(
            processRole: role,
            pid: getpid(),
            capturedAtUptimeSeconds: ProcessInfo.processInfo.systemUptime,
            totalDeviceRAMBytes: NativeHostMemoryEmulation.effectivePhysicalMemoryBytes(),
            availableHeadroomBytes: headroom,
            residentBytes: metrics.residentBytes,
            physFootprintBytes: metrics.physFootprintBytes,
            compressedBytes: metrics.compressedBytes,
            gpuAllocatedBytes: device.map { UInt64($0.currentAllocatedSize) },
            gpuRecommendedWorkingSetBytes: device.map {
                NativeHostMemoryEmulation.effectiveMetalWorkingSetBytes(real: $0.recommendedMaxWorkingSetSize)
            },
            hasUnifiedMemory: device?.hasUnifiedMemory,
            kernelPhysFootprintPeakBytes: metrics.kernelPhysFootprintPeakBytes,
            graphicsFootprintBytes: metrics.graphicsFootprintBytes,
            processLimitRemainingBytes: limitRemaining
        )
    }

    private struct TaskMemoryMetrics {
        var residentBytes: UInt64?
        var physFootprintBytes: UInt64?
        var compressedBytes: UInt64?
        var kernelPhysFootprintPeakBytes: UInt64?
        var graphicsFootprintBytes: UInt64?
        var limitBytesRemaining: UInt64?
    }

    private static func taskMemoryMetrics() -> TaskMemoryMetrics {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(
            MemoryLayout<task_vm_info_data_t>.stride / MemoryLayout<integer_t>.stride
        )
        let result = withUnsafeMutablePointer(to: &info) { pointer -> kern_return_t in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { integerPointer in
                task_info(
                    mach_task_self_,
                    task_flavor_t(TASK_VM_INFO),
                    integerPointer,
                    &count
                )
            }
        }

        guard result == KERN_SUCCESS else {
            return TaskMemoryMetrics()
        }

        // The kernel fills only the structure revision it supports and reports
        // how much it filled in `count`; a later ledger is read only when the
        // filled words cover it.
        let filledBytes = Int(count) * MemoryLayout<integer_t>.stride
        return TaskMemoryMetrics(
            residentBytes: info.resident_size,
            physFootprintBytes: info.phys_footprint,
            compressedBytes: info.compressed,
            kernelPhysFootprintPeakBytes: ledgerBytes(
                info.ledger_phys_footprint_peak,
                fieldOffset: MemoryLayout<task_vm_info_data_t>.offset(
                    of: \task_vm_info_data_t.ledger_phys_footprint_peak
                ),
                filledBytes: filledBytes
            ),
            graphicsFootprintBytes: ledgerBytes(
                info.ledger_tag_graphics_footprint,
                fieldOffset: MemoryLayout<task_vm_info_data_t>.offset(
                    of: \task_vm_info_data_t.ledger_tag_graphics_footprint
                ),
                filledBytes: filledBytes
            ),
            limitBytesRemaining: filledValue(
                info.limit_bytes_remaining,
                fieldOffset: MemoryLayout<task_vm_info_data_t>.offset(
                    of: \task_vm_info_data_t.limit_bytes_remaining
                ),
                filledBytes: filledBytes
            )
        )
    }

    /// An unsigned field, only when the kernel filled it.
    static func filledValue(_ value: UInt64, fieldOffset: Int?, filledBytes: Int) -> UInt64? {
        guard let fieldOffset,
              fieldOffset + MemoryLayout<UInt64>.size <= filledBytes else { return nil }
        return value
    }

    /// A signed ledger value, only when the kernel filled its field and it is
    /// not negative.
    static func ledgerBytes(_ value: Int64, fieldOffset: Int?, filledBytes: Int) -> UInt64? {
        guard let fieldOffset,
              fieldOffset + MemoryLayout<Int64>.size <= filledBytes,
              value >= 0 else { return nil }
        return UInt64(value)
    }

    private static func availableProcessMemory() -> UInt64? {
        var headroom: UInt64 = 0
        guard QVoiceGetOSProcAvailableMemory(&headroom) else {
            return nil
        }
        return headroom
    }

    private static func bytesToMB(_ bytes: UInt64?) -> Double? {
        guard let bytes else { return nil }
        return Double(bytes) / 1_048_576
    }
}

public struct IOSMemoryContext: Hashable, Codable, Sendable {
    public let appSnapshot: IOSMemorySnapshot
    public let pressureBand: IOSMemoryPressureBand
    public let aggregatePressureBand: IOSMemoryPressureBand
    public let worstProcessRole: IOSMemoryProcessRole?
    public let reason: String
    public let source: String

    public init(
        appSnapshot: IOSMemorySnapshot,
        pressureBand: IOSMemoryPressureBand,
        aggregatePressureBand: IOSMemoryPressureBand = .healthy,
        worstProcessRole: IOSMemoryProcessRole?,
        reason: String,
        source: String
    ) {
        self.appSnapshot = appSnapshot
        self.pressureBand = pressureBand
        self.aggregatePressureBand = aggregatePressureBand
        self.worstProcessRole = worstProcessRole
        self.reason = reason
        self.source = source
    }

    // The engine runs in-process, so a context measures the single app process.
    // The `combined*`/`aggregate*` members below therefore reflect that one process
    // (names retained for telemetry-schema continuity); the footprint-based aggregate
    // band stays a live admission criterion distinct from the headroom-based band.
    public var snapshots: [IOSMemorySnapshot] {
        [appSnapshot]
    }

    public var minimumHeadroomBytes: UInt64? {
        snapshots.compactMap(\.availableHeadroomBytes).min()
    }

    public var peakPhysFootprintBytes: UInt64? {
        snapshots.compactMap(\.physFootprintBytes).max()
    }

    public var peakResidentBytes: UInt64? {
        snapshots.compactMap(\.residentBytes).max()
    }

    public var peakGPUAllocatedBytes: UInt64? {
        snapshots.compactMap(\.gpuAllocatedBytes).max()
    }

    public var combinedResidentBytes: UInt64? {
        sumKnown(\.residentBytes)
    }

    public var combinedPhysFootprintBytes: UInt64? {
        sumKnown(\.physFootprintBytes)
    }

    public var combinedCompressedBytes: UInt64? {
        sumKnown(\.compressedBytes)
    }

    public var combinedGPUAllocatedBytes: UInt64? {
        sumKnown(\.gpuAllocatedBytes)
    }

    private func sumKnown(_ keyPath: KeyPath<IOSMemorySnapshot, UInt64?>) -> UInt64? {
        let values = snapshots.compactMap { $0[keyPath: keyPath] }
        guard !values.isEmpty else { return nil }
        return values.reduce(0, +)
    }
}

public struct IOSMemoryBudgetPolicy: Hashable, Codable, Sendable {
    public let healthyHeadroomBytes: UInt64
    public let guardedHeadroomBytes: UInt64
    public let criticalGPUWorkingSetUsageRatio: Double
    public let aggregateGuardedFootprintBytes: UInt64?
    public let aggregateCriticalFootprintBytes: UInt64?

    public init(
        healthyHeadroomBytes: UInt64,
        guardedHeadroomBytes: UInt64,
        criticalGPUWorkingSetUsageRatio: Double,
        aggregateGuardedFootprintBytes: UInt64? = nil,
        aggregateCriticalFootprintBytes: UInt64? = nil
    ) {
        self.healthyHeadroomBytes = healthyHeadroomBytes
        self.guardedHeadroomBytes = guardedHeadroomBytes
        self.criticalGPUWorkingSetUsageRatio = criticalGPUWorkingSetUsageRatio
        self.aggregateGuardedFootprintBytes = aggregateGuardedFootprintBytes
        self.aggregateCriticalFootprintBytes = aggregateCriticalFootprintBytes
    }

    /// The shipping iPhone bands, in MiB. `config/ios-memory-budget-policy.json`
    /// declares the same numbers for the Python publication gate
    /// (`scripts/benchmark_memory.py`), and a test pins the two together, so the
    /// app and the evidence gate cannot drift apart again (audit V-4).
    public enum ShippingBandMiB {
        public static let healthyHeadroom: UInt64 = 768
        public static let guardedHeadroom: UInt64 = 384
        public static let guardedFootprint: UInt64 = 4_500
        public static let criticalFootprint: UInt64 = 5_200
        public static let criticalGPUWorkingSetUsageRatio = 0.80
    }

    /// The evidence gate on the measured process budget (audit #68). A take's
    /// peak budget utilization is its footprint over its own process limit
    /// (footprint plus what remains before that limit, the budget the device
    /// grants this process): `critical` fails publication and `guarded` warns.
    /// `config/ios-memory-budget-policy.json` declares the same fractions for
    /// scripts/benchmark_memory.py, and a test pins them. They replace the
    /// absolute footprint bands and the Metal working-set ratio for evidence:
    /// every iPhone reports an 8 GiB Metal working set against a 6 GiB process
    /// limit, and the 5 GB floor device's limit sits below the 5,200 MiB band.
    /// The app's own admission and trim bands are unchanged.
    public enum EvidenceBudgetUtilization {
        public static let critical = 0.92
        public static let guarded = 0.80
    }

    /// A sample's share of its process budget, nil without both readings.
    public static func budgetUtilization(footprintMB: Double?, remainingMB: Double?) -> Double? {
        guard let footprintMB, let remainingMB, footprintMB + remainingMB > 0 else { return nil }
        return footprintMB / (footprintMB + remainingMB)
    }

    public static let iPhoneShippingDefault = IOSMemoryBudgetPolicy(
        healthyHeadroomBytes: ShippingBandMiB.healthyHeadroom * 1_048_576,
        guardedHeadroomBytes: ShippingBandMiB.guardedHeadroom * 1_048_576,
        criticalGPUWorkingSetUsageRatio: ShippingBandMiB.criticalGPUWorkingSetUsageRatio,
        aggregateGuardedFootprintBytes: ShippingBandMiB.guardedFootprint * 1_048_576,
        aggregateCriticalFootprintBytes: ShippingBandMiB.criticalFootprint * 1_048_576
    )

    /// Worst evidence band over a whole generation, persisted on engine
    /// telemetry rows (audit P1-6): the peak budget utilization against
    /// `EvidenceBudgetUtilization` and the minimum headroom against this
    /// policy's headroom bands (audit #68). Neither the absolute footprint nor
    /// the Metal working-set ratio judges evidence any more.
    public func worstBand(
        headroomMinMB: Double?,
        peakBudgetUtilization: Double?
    ) -> IOSMemoryPressureBand? {
        guard headroomMinMB != nil || peakBudgetUtilization != nil else {
            return nil
        }
        var band = IOSMemoryPressureBand.healthy
        if let peakBudgetUtilization {
            if peakBudgetUtilization >= Self.EvidenceBudgetUtilization.critical {
                band = .critical
            } else if peakBudgetUtilization >= Self.EvidenceBudgetUtilization.guarded {
                band = .guarded
            }
        }
        if let headroomMinMB {
            let headroomBytes = UInt64(max(headroomMinMB, 0) * 1_048_576)
            if headroomBytes < guardedHeadroomBytes {
                band = maxBand(band, .critical)
            } else if headroomBytes < healthyHeadroomBytes {
                band = maxBand(band, .guarded)
            }
        }
        return band
    }

    public func band(for snapshot: IOSMemorySnapshot) -> IOSMemoryPressureBand {
        if let gpuAllocated = snapshot.gpuAllocatedBytes,
           let gpuRecommendedWorkingSet = snapshot.gpuRecommendedWorkingSetBytes,
           gpuRecommendedWorkingSet > 0,
           Double(gpuAllocated) / Double(gpuRecommendedWorkingSet) >= criticalGPUWorkingSetUsageRatio {
            return .critical
        }

        guard let headroom = snapshot.availableHeadroomBytes ?? fallbackHeadroom(from: snapshot) else {
            return .healthy
        }

        if headroom < guardedHeadroomBytes {
            return .critical
        }
        if headroom < healthyHeadroomBytes {
            return .guarded
        }
        return .healthy
    }

    public func context(
        appSnapshot: IOSMemorySnapshot,
        reason: String,
        source: String
    ) -> IOSMemoryContext {
        let aggregateBand = aggregateBand(appSnapshot: appSnapshot)
        let appBand = band(for: appSnapshot)
        return IOSMemoryContext(
            appSnapshot: appSnapshot,
            pressureBand: maxBand(appBand, aggregateBand),
            aggregatePressureBand: aggregateBand,
            worstProcessRole: appSnapshot.processRole,
            reason: reason,
            source: source
        )
    }

    public func aggregateBand(for context: IOSMemoryContext) -> IOSMemoryPressureBand {
        aggregateBand(appSnapshot: context.appSnapshot)
    }

    // Footprint-based admission criterion, distinct from the headroom-based `band(for:)`.
    // Measures the single in-process app; the thresholds remain a live pressure gate.
    private func aggregateBand(appSnapshot: IOSMemorySnapshot) -> IOSMemoryPressureBand {
        guard let footprint = appSnapshot.physFootprintBytes else { return .healthy }
        if let aggregateCriticalFootprintBytes,
           footprint >= aggregateCriticalFootprintBytes {
            return .critical
        }
        if let aggregateGuardedFootprintBytes,
           footprint >= aggregateGuardedFootprintBytes {
            return .guarded
        }
        return .healthy
    }

    private func fallbackHeadroom(from snapshot: IOSMemorySnapshot) -> UInt64? {
        let usedBytes = snapshot.physFootprintBytes ?? snapshot.residentBytes
        guard let usedBytes, snapshot.totalDeviceRAMBytes > usedBytes else {
            return nil
        }
        return snapshot.totalDeviceRAMBytes - usedBytes
    }

    public func allowsProactiveWarmOperations(for band: IOSMemoryPressureBand) -> Bool {
        band == .healthy
    }

    public func allowsModelAdmission(for band: IOSMemoryPressureBand) -> Bool {
        band != .critical
    }

    public func engineExecutionBand(
        for context: IOSMemoryContext,
        includesAggregatePressure: Bool = true
    ) -> IOSMemoryPressureBand {
        var executionBand = band(for: context.appSnapshot)
        if includesAggregatePressure {
            executionBand = maxBand(executionBand, aggregateBand(for: context))
        }
        return executionBand
    }

    public func allowsModelAdmission(for context: IOSMemoryContext) -> Bool {
        allowsModelAdmission(
            for: engineExecutionBand(for: context, includesAggregatePressure: false)
        )
    }

    public func postGenerationTrimLevel(for band: IOSMemoryPressureBand) -> NativeMemoryTrimLevel? {
        switch band {
        case .healthy:
            return nil
        case .guarded:
            return .hardTrim
        case .critical:
            return .fullUnload
        }
    }

    public func trimLevelForPressureEvent(
        snapshot: IOSMemorySnapshot,
        isBackgroundTransition: Bool
    ) -> NativeMemoryTrimLevel {
        if isBackgroundTransition {
            return .fullUnload
        }

        switch band(for: snapshot) {
        case .healthy:
            return .softTrim
        case .guarded:
            return .hardTrim
        case .critical:
            return .fullUnload
        }
    }

    public func trimLevelForPressureEvent(
        context: IOSMemoryContext,
        isBackgroundTransition: Bool
    ) -> NativeMemoryTrimLevel {
        if isBackgroundTransition {
            return .fullUnload
        }

        switch context.pressureBand {
        case .healthy:
            return .softTrim
        case .guarded:
            return .hardTrim
        case .critical:
            return .fullUnload
        }
    }

    /// User-visible copy when `guardModelAdmission` blocks model load.
    public func modelAdmissionBlockMessage(
        for context: IOSMemoryContext,
        perProcessAdmissionBand: IOSMemoryPressureBand,
        allowsAggregateGuardedAdmission: Bool
    ) -> String {
        if context.aggregatePressureBand == .critical {
            return "Close other apps — Vocello is critically low on combined memory with the voice engine."
        }
        if context.aggregatePressureBand == .guarded, !allowsAggregateGuardedAdmission {
            return "Close apps using memory in the background. Vocello needs more combined memory for the app and voice engine before loading this model."
        }
        return "Vocello needs more available memory before loading this model. Close background apps and try again."
    }

    private func maxBand(
        _ lhs: IOSMemoryPressureBand,
        _ rhs: IOSMemoryPressureBand
    ) -> IOSMemoryPressureBand {
        lhs.severityRank >= rhs.severityRank ? lhs : rhs
    }
}
