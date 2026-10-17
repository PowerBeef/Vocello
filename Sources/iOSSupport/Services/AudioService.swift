import Foundation

/// Utility functions for audio file management (iOS).
///
/// Mirrors `Sources/Services/AudioService.swift`. iOS reads
/// `UserDefaults.standard` (macOS the debug-aware `AppDefaults.store`) and has
/// no user-chosen output folder: the `outputDirectory` preference is honoured
/// only inside the pullable diagnostics folder the device lanes use (IOS-16).
enum AudioService {
    private static var defaults: UserDefaults {
        UserDefaults.standard
    }

    static var shouldAutoPlay: Bool {
        if defaults.object(forKey: "autoPlay") == nil {
            return true
        }
        return defaults.bool(forKey: "autoPlay")
    }

    /// The private outputs folder, or the lanes' run folder under the pullable
    /// diagnostics root. Any other `outputDirectory` value, such as a folder in
    /// the Files-visible Documents, is ignored (IOS-16).
    private static var configuredOutputsRoot: URL {
        GenerationOutputRootOverride.acceptedRoot(
            configuredPath: defaults.string(forKey: "outputDirectory") ?? "",
            allowedRoot: IOSPullableDiagnosticsMirror.pullableRoot
        ) ?? AppPaths.outputsDir
    }

    /// A new take's path: the output folder and a neutral, timestamped name
    /// that carries none of the script, since the share sheet hands the take
    /// out under this name (SEC-1).
    static func makeOutputPath(subfolder: String) -> String {
        let outputsDir = configuredOutputsRoot.appendingPathComponent(subfolder, isDirectory: true)
        try? FileManager.default.createDirectory(at: outputsDir, withIntermediateDirectories: true)
        return outputsDir.appendingPathComponent(GenerationOutputFileName.make()).path
    }
}

/// Global convenience function used by generate views.
func makeOutputPath(subfolder: String) -> String {
    AudioService.makeOutputPath(subfolder: subfolder)
}
