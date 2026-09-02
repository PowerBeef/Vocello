import XCTest

final class IOSDeviceEligibilityPolicyTests: XCTestCase {
    func testRequiredCapabilitiesMatchTheAppStoreHardwareFloor() {
        XCTAssertEqual(
            IOSDeviceEligibilityPolicy.requiredCapabilities,
            ["arm64", "iphone-performance-gaming-tier"]
        )
        XCTAssertEqual(
            IOSDeviceEligibilityPolicy.minimumHardwareDescription,
            "iPhone 15 Pro or newer"
        )
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
}
