import Foundation
import QwenVoiceCore

/// Memory budget bands for the shared store on a Mac. The headroom thresholds
/// are inert here (`os_proc_available_memory` is iOS-only, so the snapshot's
/// headroom falls back to total RAM minus footprint and stays far above them);
/// the live criteria are the process footprint against physical RAM and the
/// Metal working-set ratio. `highMemoryMac` keeps only the GPU criterion; its
/// resident weights are released by the resolver's idle unload, and the
/// engine's kernel-pressure responder trims caches (AUD-10).
///
/// The physical memory is the machine policy reads: on a Mac emulating the
/// 8 GB floor (`QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB`, audit #11) the footprint
/// bands are the floor's, and the snapshot's Metal working set is the floor's
/// too, so the GPU criterion judges the floor's budget. Compiled into
/// `VocelloCoreTests` by path so the bands are unit-tested.
enum MacMemoryBudgetPolicy {
    static func policy(
        for deviceClass: NativeDeviceMemoryClass,
        physicalMemory: UInt64 = NativeHostMemoryEmulation.effectivePhysicalMemoryBytes()
    ) -> IOSMemoryBudgetPolicy {
        let healthyHeadroom: UInt64 = 768 * 1_048_576
        let guardedHeadroom: UInt64 = 384 * 1_048_576
        switch deviceClass {
        case .highMemoryMac:
            return IOSMemoryBudgetPolicy(
                healthyHeadroomBytes: healthyHeadroom,
                guardedHeadroomBytes: guardedHeadroom,
                criticalGPUWorkingSetUsageRatio: 0.90
            )
        default:
            return IOSMemoryBudgetPolicy(
                healthyHeadroomBytes: healthyHeadroom,
                guardedHeadroomBytes: guardedHeadroom,
                criticalGPUWorkingSetUsageRatio: 0.85,
                aggregateGuardedFootprintBytes: physicalMemory / 100 * 55,
                aggregateCriticalFootprintBytes: physicalMemory / 100 * 72
            )
        }
    }
}
