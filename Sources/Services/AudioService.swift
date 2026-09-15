import Foundation

/// Utility functions for audio file management (macOS).
///
/// Mirrored by `Sources/iOSSupport/Services/AudioService.swift`. The only
/// divergence is the preferences store: macOS reads the debug-aware
/// `AppDefaults.store` (which isolates dev runs); iOS reads `UserDefaults.standard`.
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

    /// Generate an output file path with timestamp and text snippet.
    static func makeOutputPath(subfolder: String, text: String) -> String {
        var root = configuredOutputsRoot
        if configuredOutputDirectoryIssue() != nil {
            root = AppPaths.outputsDir
        }
        var outputsDir = root.appendingPathComponent(subfolder, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: outputsDir, withIntermediateDirectories: true)
        } catch {
            // The custom directory vanished or became unwritable between the
            // probe and the write — never lose a generation over it.
            outputsDir = AppPaths.outputsDir.appendingPathComponent(subfolder, isDirectory: true)
            try? FileManager.default.createDirectory(at: outputsDir, withIntermediateDirectories: true)
        }

        let timestamp = Self.timestampFormatter.string(from: Date())
        let cleanText = text
            .replacingOccurrences(of: "[^\\w\\s-]", with: "", options: .regularExpression)
            .prefix(20)
            .trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: " ", with: "_")
        let filename = "\(timestamp)_\(cleanText.isEmpty ? "audio" : cleanText).wav"
        return outputsDir.appendingPathComponent(filename).path
    }

    private static let timestampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd_HH-mm-ss-SSS"
        return f
    }()
}

/// Global convenience function used by generate views.
func makeOutputPath(subfolder: String, text: String) -> String {
    AudioService.makeOutputPath(subfolder: subfolder, text: text)
}
