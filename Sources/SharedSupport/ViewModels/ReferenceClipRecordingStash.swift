import Foundation

/// Copies a finished reference-clip recording out of the recorder's temp dir before
/// `ReferenceClipRecorder.stopWithoutSaving()` runs on overlay dismissal.
///
/// MAC-25: the copies do not outlive their use. An enrollment surface removes the
/// ones it made once it closes and no save still reads them
/// (`ReferenceClipStashTracker`), and the macOS app clears both recording folders
/// at launch and quit (`removeLeftoverRecordings()`), which also covers a clip
/// recorded as a one-off Voice Cloning reference: Mac drafts live only as long
/// as the process.
enum ReferenceClipRecordingStash {
    /// `tmp/voice-enroll`: stable copies handed to enrollment and Voice Cloning.
    static var directory: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("voice-enroll", isDirectory: true)
    }

    /// `tmp/voice-clone-references`: the recorder's in-progress captures.
    static var captureDirectory: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("voice-clone-references", isDirectory: true)
    }

    /// Returns a stable temp copy, or `nil` if the copy failed (callers may fall back to `url`).
    static func copyToStableTemp(_ url: URL, in directory: URL = directory) -> URL? {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let dest = directory.appendingPathComponent("\(UUID().uuidString).wav", isDirectory: false)
        do {
            try FileManager.default.copyItem(at: url, to: dest)
            return dest
        } catch {
            return nil
        }
    }

    /// Deletes `path` when it is a stash copy in `directory`; any other file,
    /// such as an imported reference, is never touched.
    static func discard(_ path: String, in directory: URL = directory) {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        guard url.deletingLastPathComponent().standardizedFileURL.path
            == directory.standardizedFileURL.path else { return }
        try? FileManager.default.removeItem(at: url)
    }

    /// Removes both recording folders. Only for a moment when nothing can
    /// reference them: app launch and quit on macOS.
    static func removeLeftoverRecordings(directories: [URL] = [directory, captureDirectory]) {
        for directory in directories {
            try? FileManager.default.removeItem(at: directory)
        }
    }
}

/// The stash copies one enrollment surface made (MAC-25). They are removed when
/// the surface closes, or, while a save is still reading one, when that save
/// ends; the private candidate the save staged holds its own copy.
@MainActor
final class ReferenceClipStashTracker {
    private var paths: [String] = []
    private var activeUses = 0
    private var isClosed = false
    private let discard: (String) -> Void

    init(discard: @escaping (String) -> Void = { ReferenceClipRecordingStash.discard($0) }) {
        self.discard = discard
    }

    func record(_ path: String) {
        paths.append(path)
        removeIfFinished()
    }

    func beginUse() {
        activeUses += 1
    }

    func endUse() {
        activeUses = max(0, activeUses - 1)
        removeIfFinished()
    }

    func close() {
        isClosed = true
        removeIfFinished()
    }

    private func removeIfFinished() {
        guard isClosed, activeUses == 0, !paths.isEmpty else { return }
        let finished = paths
        paths.removeAll()
        finished.forEach(discard)
    }
}
