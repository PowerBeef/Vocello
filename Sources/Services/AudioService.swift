import Foundation

/// Utility functions for audio file management (macOS).
///
/// Mirrored by `Sources/iOSSupport/Services/AudioService.swift`, which reads
/// `UserDefaults.standard` and has no user-chosen output folder (IOS-16); macOS
/// reads the debug-aware `AppDefaults.store` (which isolates dev runs). Both
/// name takes through `GenerationOutputFileName`.
enum AudioService {
    private static var defaults: UserDefaults {
        AppDefaults.store
    }

    static var shouldAutoPlay: Bool {
        if defaults.object(forKey: "autoPlay") == nil {
            return true
        }
        return defaults.bool(forKey: "autoPlay")
    }

    private static var configuredOutputsRoot: URL {
        let configuredPath = (defaults.string(forKey: "outputDirectory") ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if configuredPath.isEmpty {
            return AppPaths.outputsDir
        }

        let expandedPath = (configuredPath as NSString).expandingTildeInPath
        return URL(fileURLWithPath: expandedPath, isDirectory: true)
    }

    /// Non-nil when the user-configured output directory can't currently be
    /// used (deleted, unmounted, or unwritable). New audio silently falls back
    /// to the default outputs folder; Settings surfaces this message so the
    /// fallback isn't a mystery.
    static func configuredOutputDirectoryIssue() -> String? {
        let configuredPath = (defaults.string(forKey: "outputDirectory") ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !configuredPath.isEmpty else { return nil }

        let expandedPath = (configuredPath as NSString).expandingTildeInPath
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: expandedPath, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            return MacInterfaceText.audioFolderMissing
        }
        guard FileManager.default.isWritableFile(atPath: expandedPath) else {
            return MacInterfaceText.audioFolderNotWritable
        }
        return nil
    }

    /// The folder new takes are written to: the custom output folder while it
    /// is usable, the default outputs folder otherwise. "Open Output Folder"
    /// and History's recovery Reveal open this one (MAC-15).
    static var effectiveOutputsRoot: URL {
        configuredOutputDirectoryIssue() == nil ? configuredOutputsRoot : AppPaths.outputsDir
    }

    /// Generate an output file path with timestamp and text snippet.
    static func makeOutputPath(subfolder: String, text: String) -> String {
        var outputsDir = effectiveOutputsRoot.appendingPathComponent(subfolder, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: outputsDir, withIntermediateDirectories: true)
        } catch {
            // The custom directory vanished or became unwritable between the
            // probe and the write — never lose a generation over it.
            outputsDir = AppPaths.outputsDir.appendingPathComponent(subfolder, isDirectory: true)
            try? FileManager.default.createDirectory(at: outputsDir, withIntermediateDirectories: true)
        }
        return outputsDir.appendingPathComponent(GenerationOutputFileName.make(text: text)).path
    }
}

/// Global convenience function used by generate views.
func makeOutputPath(subfolder: String, text: String) -> String {
    AudioService.makeOutputPath(subfolder: subfolder, text: text)
}
