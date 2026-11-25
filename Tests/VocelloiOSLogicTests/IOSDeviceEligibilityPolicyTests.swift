import XCTest
import VocelloiOSPolicies

final class IOSDeviceEligibilityPolicyTests: XCTestCase {
    func testRequiredCapabilitiesMatchTheAppStoreHardwareFloor() {
        XCTAssertEqual(
            IOSDeviceEligibilityPolicy.requiredCapabilities,
            ["arm64", "iphone-performance-gaming-tier"]
        )
        XCTAssertEqual(IOSDeviceEligibilityPolicy.minimumHardwareModel, "iPhone 15 Pro")
    }

    func testSupportedIdentifiersBeginAtIPhone15Pro() {
        XCTAssertTrue(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone16,1"))
        XCTAssertTrue(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone16,2"))
        XCTAssertTrue(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone17,1"))
        XCTAssertTrue(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone18,1"))
    }

    func testOlderAndMalformedIdentifiersAreRejected() {
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone15,5"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone16,3"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone16,4"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPhone17"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPad"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("arm64"))
    }

    /// RF-42 / RF-73 (2026-11-25): the 8 GB+ M-series and A17 Pro iPads that satisfy
    /// `iphone-performance-gaming-tier` run in portrait iPhone compatibility mode, while
    /// lower-memory iPads stay rejected.
    func testEligibleHighMemoryIPadsAreAdmittedAndLowerMemoryIPadsRejected() {
        let supportedIPads = [
            "iPad13,4", "iPad13,11", // M1 iPad Pro 11" / 12.9"
            "iPad13,16", "iPad13,17", // M1 iPad Air 5th gen
            "iPad14,3", "iPad14,6", // M2 iPad Pro
            "iPad14,8", "iPad14,11", // M2 iPad Air
            "iPad15,3", "iPad15,6", // M3 iPad Air
            "iPad16,1", "iPad16,2", // iPad mini (A17 Pro)
            "iPad16,5", "iPad16,6", // M4 iPad Pro
            "iPad17,1", // M5 iPad Pro
        ]
        for identifier in supportedIPads {
            XCTAssertTrue(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier(identifier), identifier)
        }

        let unsupportedIPads = [
            "iPad12,1", // iPad 9th gen (A13, 3 GB)
            "iPad13,1", "iPad13,2", "iPad13,3", // iPad Air 4th gen & gap-adjacent
            "iPad13,12", "iPad13,15", // gap-adjacent minors
            "iPad13,18", "iPad13,19", // iPad 10th gen (A14, 4 GB)
            "iPad14,1", "iPad14,2", "iPad14,7", // iPad mini 6th gen & gap-adjacent
            "iPad15,2", "iPad15,7", "iPad15,8", // gap-adjacent & iPad 11th gen (A16, 6 GB)
            "iPad16,-1", "iPad16,0", "iPad16,1,2", // malformed / non-positive components
            "iPhone17,-1", "iPhone17,0",
        ]
        for identifier in unsupportedIPads {
            XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier(identifier), identifier)
        }
    }
}
