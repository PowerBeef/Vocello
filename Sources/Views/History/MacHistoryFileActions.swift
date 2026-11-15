import AppKit
import Foundation
import UniformTypeIdentifiers

/// Desktop file actions of the History screen: Save As, Reveal in Finder,
/// the outputs folder and the recovery export. Panels run modal on the main
/// actor; the copies run off it, because a long take written to an external
/// volume takes seconds and froze the window (A7). The results are plain
/// values the screen turns into alerts on the main actor.
@MainActor
enum MacHistoryFileActions {
    /// Copies the take's WAV where the user chooses. Returns the failure
    /// description, or nil when the copy succeeded or the user cancelled.
    /// The suggested name is neutral, even for a take an earlier build named
    /// after its script (SEC-1).
    static func saveCopy(of audioPath: String) async -> String? {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = GenerationOutputFileName.exportName(
            forTakeNamed: URL(fileURLWithPath: audioPath).lastPathComponent
        )
        panel.allowedContentTypes = [.wav]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        let source = URL(fileURLWithPath: audioPath)
        return await Task.detached(priority: .userInitiated) { @concurrent in
            copyFailure(from: source, to: url)
        }.value
    }

    /// NSSavePanel confirms an overwrite but leaves the existing file in
    /// place. MacFileSaveCopy stages a copy and replaces the destination only
    /// once it is complete, and treats the take's own file as the destination
    /// as a no-op instead of deleting it.
    private nonisolated static func copyFailure(from source: URL, to destination: URL) -> String? {
        do {
            _ = try MacFileSaveCopy.copy(from: source, to: destination)
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    /// Copies the pending recovery audio into a folder the user chooses, each
    /// copy under its neutral export name (SEC-1). Returns the number of files
    /// that could not be copied, or nil when the user cancelled.
    static func exportPendingAudio(_ urls: [URL]) async -> Int? {
        guard !urls.isEmpty else { return nil }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = MacInterfaceText.historyExportPrompt
        guard panel.runModal() == .OK, let destination = panel.url else { return nil }
        return await Task.detached(priority: .userInitiated) { @concurrent in
            copyPendingAudio(urls, into: destination)
        }.value
    }

    /// The recovery export's copies; returns how many failed.
    private nonisolated static func copyPendingAudio(_ urls: [URL], into destination: URL) -> Int {
        var failures = 0
        for source in urls {
            let exportName = GenerationOutputFileName.exportName(forTakeNamed: source.lastPathComponent) as NSString
            var target = destination.appendingPathComponent(exportName as String)
            if FileManager.default.fileExists(atPath: target.path) {
                target = destination.appendingPathComponent(
                    "\(exportName.deletingPathExtension)-\(UUID().uuidString.prefix(8)).\(exportName.pathExtension)"
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

    /// The recovery banner's Reveal: selects the recoverable takes' audio when
    /// any is on disk, otherwise opens the folder new takes are written to,
    /// the custom output folder while it is usable (MAC-15).
    static func revealRecoveryAudio(_ urls: [URL]) {
        let existing = urls.filter { FileManager.default.fileExists(atPath: $0.path) }
        if existing.isEmpty {
            NSWorkspace.shared.open(AudioService.effectiveOutputsRoot)
        } else {
            NSWorkspace.shared.activateFileViewerSelecting(existing)
        }
    }
}
