import XCTest
import QwenVoiceCore

@MainActor
final class IOSSettingsModelNavigationTests: XCTestCase {
    private func model(for mode: GenerationMode) throws -> ModelDescriptor {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let registry = try ContractBackedModelRegistry(
            manifestURL: root.appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        ).resolvedForPlatform(.iOS, deviceClass: .iPhonePro)
        return try XCTUnwrap(registry.model(for: mode))
    }

    /// RF-41: Studio's install button routes to Voice Models and leaves the exact selected
    /// model waiting for the download confirmation there; nothing installs from the route.
    func testEveryModeRoutesToAConfirmationForTheExactSelectedDescriptor() throws {
        for mode in [GenerationMode.custom, .design, .clone] {
            let model = try model(for: mode)
            let navigation = IOSSettingsModelNavigation()
            var selectedSettings = false
            navigation.requestInstallation(of: model, selectSettings: {
                XCTAssertEqual(navigation.path, [.modelsAndFiles, .voiceModels])
                XCTAssertNil(navigation.downloadAwaitingConfirmation)
                selectedSettings = true
            })
            XCTAssertTrue(selectedSettings)
            XCTAssertEqual(navigation.downloadAwaitingConfirmation, model)
            XCTAssertEqual(navigation.takeDownloadAwaitingConfirmation(), model)
            XCTAssertNil(navigation.downloadAwaitingConfirmation)
        }
    }

    func testNavigationAndBackDoNotReplayAConfirmation() throws {
        let navigation = IOSSettingsModelNavigation()
        let model = try model(for: .design)
        XCTAssertTrue(navigation.path.isEmpty)
        navigation.path = [.modelsAndFiles]
        navigation.requestInstallation(of: model, selectSettings: {})
        XCTAssertEqual(navigation.path, [.modelsAndFiles, .voiceModels])
        XCTAssertEqual(navigation.takeDownloadAwaitingConfirmation(), model)
        navigation.path.removeLast()
        XCTAssertEqual(navigation.path, [.modelsAndFiles])
        navigation.path.removeLast()
        XCTAssertTrue(navigation.path.isEmpty)
        navigation.path = [.modelsAndFiles, .voiceModels]
        XCTAssertNil(navigation.takeDownloadAwaitingConfirmation())
    }

    /// A request Voice Models never showed must not replay on a later visit to Settings.
    func testLeavingSettingsDropsAConfirmationVoiceModelsNeverShowed() throws {
        let navigation = IOSSettingsModelNavigation()
        let model = try model(for: .clone)
        navigation.requestInstallation(of: model, selectSettings: {})
        navigation.leaveSettings()
        XCTAssertTrue(navigation.path.isEmpty)
        XCTAssertNil(navigation.downloadAwaitingConfirmation)
        XCTAssertNil(navigation.takeDownloadAwaitingConfirmation())
    }
}
