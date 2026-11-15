import Foundation
import QwenVoiceCore

/// The file copy behind Save As. Choosing the take's own file as the
/// destination is a no-op rather than a delete-then-copy of the only copy, and
/// a failed copy never removes an existing destination: `StagedFileCopy` lands
/// the bytes in a hidden staging file next to the destination, replaces it only
/// once they are complete, and removes its staging file on every failure.
enum MacFileSaveCopy {
    enum Outcome: Equatable {
        case copied
        case sameFile
    }

    static func copy(from source: URL, to destination: URL, fileManager: FileManager = .default) throws -> Outcome {
        if isSameFile(source, destination) { return .sameFile }
        try StagedFileCopy.copy(from: source, to: destination, fileManager: fileManager)
        return .copied
    }

    /// Same path after resolving symlinks and `..`, or, when the destination
    /// exists, the same file system object (hard links, case-only renames).
    static func isSameFile(_ first: URL, _ second: URL) -> Bool {
        let firstPath = first.standardizedFileURL.resolvingSymlinksInPath().path
        let secondPath = second.standardizedFileURL.resolvingSymlinksInPath().path
        if firstPath == secondPath { return true }
        guard
            let firstID = try? first.resourceValues(forKeys: [.fileResourceIdentifierKey]).fileResourceIdentifier,
            let secondID = try? second.resourceValues(forKeys: [.fileResourceIdentifierKey]).fileResourceIdentifier
        else { return false }
        return firstID.isEqual(secondID)
    }
}

/// The copies of the recovery export: each pending take's audio into the
/// folder the user chose, under its neutral export name (SEC-1). A name the
/// folder already holds is never overwritten; that copy gets a short random
/// suffix instead.
enum MacRecoveryAudioExport {
    /// Copies every source and returns how many could not be copied.
    static func copy(_ sources: [URL], into destination: URL, fileManager: FileManager = .default) -> Int {
        var failures = 0
        for source in sources {
            let exportName = GenerationOutputFileName.exportName(forTakeNamed: source.lastPathComponent) as NSString
            var target = destination.appendingPathComponent(exportName as String)
            if fileManager.fileExists(atPath: target.path) {
                target = destination.appendingPathComponent(
                    "\(exportName.deletingPathExtension)-\(UUID().uuidString.prefix(8)).\(exportName.pathExtension)"
                )
            }
            do {
                try fileManager.copyItem(at: source, to: target)
            } catch {
                failures += 1
            }
        }
        return failures
    }
}

/// The one file copy the Mac app runs for the user at a time (Save As, the
/// recovery export) and how the last one failed. The copy runs off the main
/// actor and can outlast the screen that asked for it, so this state belongs
/// to the app (`MacAppModel.fileCopy`), never to a view: the failure is shown
/// wherever the user is by then, and a second copy cannot start while one
/// runs, which is what made a repeated recovery export write every file twice.
struct MacFileCopyActivity: Equatable, Sendable {
    enum Failure: Hashable, Identifiable, Sendable {
        /// Save As could not write the copy; the text is the error's own.
        case saveAs(String)
        /// The recovery export could not copy this many files.
        case recoveryExport(failedCount: Int)

        /// The alert that shows a failure is presented by value.
        var id: Self { self }

        /// The recovery export's outcome: a failure only when a file was not copied.
        static func afterRecoveryExport(failures: Int) -> Failure? {
            failures > 0 ? .recoveryExport(failedCount: failures) : nil
        }
    }

    /// A copy, or the panel that precedes it, is in flight.
    private(set) var isCopying = false
    /// The failure the user has not acknowledged yet.
    private(set) var failure: Failure?

    /// Claims the one copy. `false` while another is in flight: the caller
    /// then starts nothing.
    mutating func begin() -> Bool {
        guard !isCopying else { return false }
        isCopying = true
        return true
    }

    /// The claimed copy ended. `failure` is nil when it succeeded or the user
    /// cancelled its panel; a failure not yet acknowledged then stays.
    mutating func finish(_ failure: Failure?) {
        isCopying = false
        if let failure { self.failure = failure }
    }

    /// The user dismissed the failure alert.
    mutating func acknowledgeFailure() {
        failure = nil
    }
}
