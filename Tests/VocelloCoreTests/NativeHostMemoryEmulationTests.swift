import XCTest
@testable import QwenVoiceCore

/// The 8 GB floor emulated on a larger Mac (audit #11 option b): the knob moves
/// the tier, its policy, the store's footprint bands and the Metal working set
/// the GPU ratio is judged against, and nothing when it is absent or invalid.
final class NativeHostMemoryEmulationTests: XCTestCase {
    private let gib: UInt64 = 1_073_741_824
    private let mib: UInt64 = 1_048_576
    /// What a Mac mini M6 16 GB reports: 16 GiB of RAM, two thirds of it as the
    /// recommended Metal working set.
    private var m6PhysicalMemory: UInt64 { 16 * gib }
    private var m6MetalWorkingSet: UInt64 { 16 * gib / 3 * 2 }

    private func floorEmulation() throws -> NativeHostMemoryEmulation {
        try XCTUnwrap(NativeHostMemoryEmulation.resolve("8", realPhysicalMemoryBytes: m6PhysicalMemory))
    }

    func testEightGiBEmulatesTheFloorMachineAndItsMetalWorkingSet() throws {
        let emulation = try floorEmulation()
        XCTAssertEqual(emulation.physicalMemoryBytes, 8 * gib)
        XCTAssertEqual(emulation.physicalMemoryMB, 8_192)
        // An 8 GB Apple silicon Mac recommends 5,461 MB of Metal working set.
        XCTAssertEqual(emulation.metalWorkingSetMB, 5_461)
        XCTAssertEqual(
            NativeHostMemoryEmulation.resolve(" 8GB ", realPhysicalMemoryBytes: m6PhysicalMemory),
            emulation
        )
    }

    func testOnlyASmallerMacCanBeEmulated() {
        for raw in [nil, "", "  ", "0", "-8", "eight", "8.5", "16", "32", "4096"] {
            XCTAssertNil(
                NativeHostMemoryEmulation.resolve(raw, realPhysicalMemoryBytes: m6PhysicalMemory),
                "\(raw ?? "nil") must leave the real machine in place"
            )
        }
    }

    func testEffectiveMemoryIsTheRealMachineWithoutAnEmulation() {
        XCTAssertEqual(
            NativeHostMemoryEmulation.effectivePhysicalMemoryBytes(real: m6PhysicalMemory, emulation: nil),
            m6PhysicalMemory
        )
        XCTAssertEqual(
            NativeHostMemoryEmulation.effectiveMetalWorkingSetBytes(real: m6MetalWorkingSet, emulation: nil),
            m6MetalWorkingSet
        )
    }

    func testResolverTreatsTheEmulatedHostAsTheFloorTier() throws {
        let emulation = try floorEmulation()
        let native = NativeMemoryPolicyResolver.deviceClass(
            physicalMemoryBytes: m6PhysicalMemory, isIPhone: false
        )
        XCTAssertEqual(native, .mid16GBMac)

        let emulated = NativeMemoryPolicyResolver.deviceClass(
            physicalMemoryBytes: NativeHostMemoryEmulation.effectivePhysicalMemoryBytes(
                real: m6PhysicalMemory, emulation: emulation
            ),
            isIPhone: false
        )
        XCTAssertEqual(emulated, .floor8GBMac)

        let policy = NativeMemoryPolicyResolver.policy(deviceClass: emulated, mode: .custom, isBatch: false)
        XCTAssertEqual(policy.name, "floor_8gb_mac_custom_single")
        XCTAssertEqual(policy.cacheLimitBytes, 256 * 1_024 * 1_024)
        XCTAssertTrue(policy.clearCacheAfterGeneration)
        XCTAssertEqual(policy.unloadAfterIdleSeconds, 120)
        XCTAssertEqual(NativeMemoryPolicyResolver.cloneCacheCapacity(deviceClass: emulated), 1)
    }

    func testFootprintBandsFollowTheEmulatedMemory() throws {
        let emulation = try floorEmulation()
        let physicalMemory = NativeHostMemoryEmulation.effectivePhysicalMemoryBytes(
            real: m6PhysicalMemory, emulation: emulation
        )
        let floor = MacMemoryBudgetPolicy.policy(for: .floor8GBMac, physicalMemory: physicalMemory)
        XCTAssertEqual(floor.aggregateGuardedFootprintBytes, 8 * gib / 100 * 55)
        XCTAssertEqual(floor.aggregateCriticalFootprintBytes, 8 * gib / 100 * 72)

        // A 4.6 GiB footprint is healthy on the real 16 GB Mac and guarded on
        // the emulated floor; 6 GiB is critical there.
        let native = MacMemoryBudgetPolicy.policy(for: .mid16GBMac, physicalMemory: m6PhysicalMemory)
        let guardedFootprint = 4 * gib + 600 * mib
        XCTAssertEqual(
            native.context(
                appSnapshot: snapshot(footprint: guardedFootprint, totalRAM: m6PhysicalMemory, workingSet: m6MetalWorkingSet),
                reason: "test", source: "test"
            ).pressureBand,
            .healthy
        )
        let floorWorkingSet = NativeHostMemoryEmulation.effectiveMetalWorkingSetBytes(
            real: m6MetalWorkingSet, emulation: emulation
        )
        XCTAssertEqual(
            floor.context(
                appSnapshot: snapshot(footprint: guardedFootprint, totalRAM: physicalMemory, workingSet: floorWorkingSet),
                reason: "test", source: "test"
            ).pressureBand,
            .guarded
        )
        XCTAssertEqual(
            floor.context(
                appSnapshot: snapshot(footprint: 6 * gib, totalRAM: physicalMemory, workingSet: floorWorkingSet),
                reason: "test", source: "test"
            ).pressureBand,
            .critical
        )
    }

    func testGPUWorkingSetRatioIsJudgedAgainstTheFloorBudget() throws {
        let emulation = try floorEmulation()
        let floorWorkingSet = NativeHostMemoryEmulation.effectiveMetalWorkingSetBytes(
            real: m6MetalWorkingSet, emulation: emulation
        )
        XCTAssertEqual(floorWorkingSet / mib, 5_461)
        // 4.7 GB of Metal allocations: under half the M6's working set, but
        // above the 0.85 critical ratio of the floor's.
        let allocated = 4_700 * mib
        let policy = MacMemoryBudgetPolicy.policy(for: .floor8GBMac, physicalMemory: 8 * gib)
        let onM6 = snapshot(footprint: 3 * gib, totalRAM: m6PhysicalMemory, workingSet: m6MetalWorkingSet, gpu: allocated)
        let onFloor = snapshot(footprint: 3 * gib, totalRAM: 8 * gib, workingSet: floorWorkingSet, gpu: allocated)
        XCTAssertLessThan(try XCTUnwrap(onM6.gpuWorkingSetUsageRatio), 0.5)
        XCTAssertGreaterThan(try XCTUnwrap(onFloor.gpuWorkingSetUsageRatio), 0.85)
        XCTAssertEqual(policy.band(for: onM6), .healthy)
        XCTAssertEqual(policy.band(for: onFloor), .critical)
    }

    private func snapshot(
        footprint: UInt64, totalRAM: UInt64, workingSet: UInt64, gpu: UInt64 = 0
    ) -> IOSMemorySnapshot {
        IOSMemorySnapshot(
            totalDeviceRAMBytes: totalRAM,
            availableHeadroomBytes: nil,
            residentBytes: footprint,
            physFootprintBytes: footprint,
            compressedBytes: 0,
            gpuAllocatedBytes: gpu,
            gpuRecommendedWorkingSetBytes: workingSet,
            hasUnifiedMemory: true
        )
    }
}
