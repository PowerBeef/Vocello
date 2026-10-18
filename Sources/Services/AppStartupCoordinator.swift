import Foundation
import Observation

@MainActor
@Observable
final class AppStartupCoordinator {
    private(set) var launchDiagnostics: AppLaunchDiagnosticsSnapshot?

    func setupAppSupport() {
        let fm = FileManager.default
        let outputSubdirectories = Set(TTSModel.all.map(\.outputSubfolder))

        let dirs = [
            QwenVoiceApp.appSupportDir.path,
            QwenVoiceApp.appSupportDir.appendingPathComponent("models").path,
            QwenVoiceApp.appSupportDir.appendingPathComponent("outputs").path,
            QwenVoiceApp.appSupportDir.appendingPathComponent("voices").path,
            QwenVoiceApp.appSupportDir.appendingPathComponent("cache").path,
            QwenVoiceApp.appSupportDir.appendingPathComponent("cache/stream_sessions").path,
        ] + outputSubdirectories.sorted().map {
            QwenVoiceApp.appSupportDir.appendingPathComponent("outputs/\($0)").path
        }

        for dir in dirs {
            try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
        }

        AppPaths.excludeFromBackup(QwenVoiceApp.appSupportDir.appendingPathComponent("models", isDirectory: true))
        AppPaths.excludeFromBackup(QwenVoiceApp.appSupportDir.appendingPathComponent("cache", isDirectory: true))
    }

    func refreshLaunchDiagnostics() {
        launchDiagnostics = AppLaunchPreflight.run()
    }

    func clearLaunchDiagnostics() {
        launchDiagnostics = nil
    }
}
