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
        do {
            // NSSavePanel confirms an overwrite but leaves the existing file in
            // place. MacFileSaveCopy stages a copy and replaces the destination
            // only once it is complete, and treats the take's own file as the
            // destination as a no-op instead of deleting it.
            _ = try MacFileSaveCopy.copy(from: URL(fileURLWithPath: audioPath), to: url)
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
