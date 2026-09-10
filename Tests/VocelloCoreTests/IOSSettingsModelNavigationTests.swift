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

    func testEveryModeRoutesBeforeInstallingTheExactSelectedDescriptor() throws {
        for mode in [GenerationMode.custom, .design, .clone] {
            let model = try model(for: mode)
            let navigation = IOSSettingsModelNavigation()
            var events: [String] = []
            var installed: ModelDescriptor?
            navigation.requestInstallation(of: model, selectSettings: {
                XCTAssertEqual(navigation.path, [.modelsAndFiles, .voiceModels])
                events.append("settings")
            }, install: { selected in
                installed = selected
                events.append("install")
            })
            XCTAssertEqual(installed, model)
            XCTAssertEqual(events, ["settings", "install"])
        }
    }

    func testNavigationAndBackDoNotReplayAnInstallation() throws {
        let navigation = IOSSettingsModelNavigation()
        let model = try model(for: .design)
        var calls = 0
        XCTAssertTrue(navigation.path.isEmpty)
        navigation.path = [.modelsAndFiles]
        navigation.requestInstallation(of: model, selectSettings: {}, install: { _ in calls += 1 })
        XCTAssertEqual(navigation.path, [.modelsAndFiles, .voiceModels])
        navigation.path.removeLast()
        XCTAssertEqual(navigation.path, [.modelsAndFiles])
        navigation.path.removeLast()
        XCTAssertTrue(navigation.path.isEmpty)
        navigation.path = [.modelsAndFiles, .voiceModels]
        XCTAssertEqual(calls, 1)
    }
}
