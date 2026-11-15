import AppKit
import Foundation
import SwiftUI
import UniformTypeIdentifiers

/// Desktop file actions of the History screen: Save As, Reveal in Finder,
/// the outputs folder and the recovery export. Panels run modal on the main
/// actor; the copies run off it, because a long take written to an external
/// volume takes seconds and froze the window (A7). Save As and the recovery
/// export are started through `MacAppModel` (`saveCopy(of:)`,
/// `exportPendingAudio(_:)`), which allows one copy at a time and keeps the
/// result for the shell's alert, so a screen left meanwhile loses nothing.
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
            MacRecoveryAudioExport.copy(urls, into: destination)
        }.value
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

/// The shell's alert for a Save As or a recovery export that failed. The
/// failure is the app model's (`MacAppModel.fileCopy`), so it is shown on
/// whichever destination the user is on when the copy ends, with the titles
/// and messages History and the Studio card showed for it before.
struct MacFileCopyFailureAlert: ViewModifier {
    let appModel: MacAppModel

    func body(content: Content) -> some View {
        // Read here, in the body, so a change presents or dismisses the alert.
        let failure = appModel.fileCopy.failure
        content.alert(
            item: Binding(
                get: { failure },
                set: { if $0 == nil { appModel.acknowledgeFileCopyFailure() } }
            )
        ) { shown in
            Alert(
                title: Text(Self.title(for: shown)),
                message: Text(Self.message(for: shown)),
                dismissButton: .default(Text(MacInterfaceText.ok))
            )
        }
    }

    static func title(for failure: MacFileCopyActivity.Failure) -> String {
        switch failure {
        case .saveAs: MacInterfaceText.historyExportError
        case .recoveryExport: MacInterfaceText.historyExportWarning
        }
    }

    static func message(for failure: MacFileCopyActivity.Failure) -> String {
        switch failure {
        case .saveAs(let description): MacInterfaceText.historyExportErrorMessage(description)
        case .recoveryExport(let failedCount): VocelloPresentationText.recoveryExportFailure(failedCount)
        }
    }
}
