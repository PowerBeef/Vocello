import XCTest

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
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("iPad16,1"))
        XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier("arm64"))
    }

    /// RF-42: the capability also admits these iPads at install time; the guard keeps them out.
    func testIPadsTheCapabilityAdmitsAreRejected() {
        // iPad Pro 11-inch (3rd generation), iPad Air (5th generation), iPad mini (A17 Pro),
        // iPad Pro 13-inch (M4).
        for identifier in ["iPad13,4", "iPad13,16", "iPad16,1", "iPad16,5"] {
            XCTAssertFalse(IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier(identifier), identifier)
        }
    }
}
