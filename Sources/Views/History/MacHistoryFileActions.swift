import AppKit
import Foundation
import UniformTypeIdentifiers

/// Desktop file actions of the History screen: Save As, Reveal in Finder,
/// the outputs folder and the recovery export. Panels run modal on the main
/// actor; the results are plain values the screen turns into alerts.
@MainActor
enum MacHistoryFileActions {
    /// Copies the take's WAV where the user chooses. Returns the failure
    /// description, or nil when the copy succeeded or the user cancelled.
    static func saveCopy(of audioPath: String) -> String? {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = URL(fileURLWithPath: audioPath).lastPathComponent
        panel.allowedContentTypes = [.wav]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        let sourceURL = URL(fileURLWithPath: audioPath)
        let fileManager = FileManager.default
        do {
            // NSSavePanel only stages the destination URL after the user
            // confirms the overwrite prompt; it does not remove the existing
            // file, and `copyItem` then throws on overwrite. Remove the
            // destination first. `replaceItemAt` is not an option: it would
            // move the History file out of place.
            if fileManager.fileExists(atPath: url.path) {
                try fileManager.removeItem(at: url)
            }
            try fileManager.copyItem(at: sourceURL, to: url)
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    /// Copies the pending recovery audio into a folder the user chooses.
    /// Returns the number of files that could not be copied, or nil when the
    /// user cancelled.
    static func exportPendingAudio(_ urls: [URL]) -> Int? {
        guard !urls.isEmpty else { return nil }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = MacInterfaceText.historyExportPrompt
        guard panel.runModal() == .OK, let destination = panel.url else { return nil }

        var failures = 0
        for source in urls {
            var target = destination.appendingPathComponent(source.lastPathComponent)
            if FileManager.default.fileExists(atPath: target.path) {
                target = destination.appendingPathComponent(
                    "\(source.deletingPathExtension().lastPathComponent)-\(UUID().uuidString.prefix(8)).\(source.pathExtension)"
                )
            }
            do {
                try FileManager.default.copyItem(at: source, to: target)
            } catch {
                failures += 1
            }
        }
        return failures
    }

    static func revealInFinder(_ path: String) {
        NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
    }

    static func openOutputsFolder() {
        NSWorkspace.shared.open(AppPaths.outputsDir)
    }
}
