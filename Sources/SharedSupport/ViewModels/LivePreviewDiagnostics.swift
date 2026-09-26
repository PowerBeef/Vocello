import Foundation
import QwenVoiceCore

/// Diagnostic logging for the live-preview chunk-decode pipeline.
///
/// Gated behind the `QWENVOICE_LIVE_PREVIEW_DIAGNOSTICS=1` environment
/// variable so production runs pay no cost. When enabled, emits one line
/// per event with:
///   - timestamp
///   - viewModel `ObjectIdentifier` hash (so duplicate subscribers show up
///     as different ids)
///   - event name (e.g. `appendLiveChunk.enter`, `decode_fail.AVAudioFile(forReading:)`)
///   - chunk URL basename
///   - file existence + size at the moment of the event
///
/// Enable by setting `QWENVOICE_LIVE_PREVIEW_DIAGNOSTICS=1`, then grep stdout
/// for `[live-preview-diag]`.
enum LivePreviewDiagnostics {
    private static let environmentKey = "QWENVOICE_LIVE_PREVIEW_DIAGNOSTICS"

    /// Read once per process: the launch environment cannot change, and the
    /// chunk path calls this per event, where rebuilding the environment
    /// dictionary each time was pure overhead (audit #83).
    static let isEnabled: Bool = {
        let value = RuntimeDebugGate.value(for: environmentKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        switch value {
        case "1", "true", "yes", "on": return true
        default: return false
        }
    }()

    /// Record a lifecycle event on a chunk URL (enter / decode_failed /
    /// delete). Writes one formatted line to stdout if diagnostics are on.
    static func logChunkEvent(
        _ event: String,
        viewModel: AnyObject,
        url: URL
    ) {
        guard isEnabled else { return }
        emit(event: event, viewModel: viewModel, url: url, detail: nil)
    }

    /// Record a specific decode-failure return path from `loadPCMBuffer`
    /// with which branch fired and the underlying error's privacy summary,
    /// never its text (AUD-08).
    static func logDecodeFailure(
        _ branch: String,
        viewModel: AnyObject,
        url: URL,
        error: Error?
    ) {
        guard isEnabled else { return }
        let detail: String
        if let error {
            detail = "branch=\(branch) error=\(DiagnosticPrivacy.summary(of: error))"
        } else {
            detail = "branch=\(branch)"
        }
        emit(
            event: "decode_fail",
            viewModel: viewModel,
            url: url,
            detail: detail
        )
    }

    // MARK: - Internals

    private static func emit(
        event: String,
        viewModel: AnyObject,
        url: URL,
        detail: String?
    ) {
        let vmID = UInt(bitPattern: ObjectIdentifier(viewModel).hashValue) & 0xFFFF
        let timestamp = Date().timeIntervalSince1970
        let basename = url.lastPathComponent
        let fm = FileManager.default
        let exists = fm.fileExists(atPath: url.path)
        let size: Int
        if exists,
           let attrs = try? fm.attributesOfItem(atPath: url.path),
           let fileSize = attrs[.size] as? Int {
            size = fileSize
        } else {
            size = -1
        }
        var line = "[live-preview-diag] t=\(String(format: "%.3f", timestamp))"
            + " vm=\(String(format: "%04x", vmID))"
            + " event=\(event)"
            + " chunk=\(basename)"
            + " exists=\(exists)"
            + " size=\(size)"
        if let detail, !detail.isEmpty {
            line += " \(detail)"
        }
        // FileHandle.standardError writes skip line buffering and interleave
        // correctly with xcodebuild's merged test output.
        if let data = (line + "\n").data(using: .utf8) {
            FileHandle.standardError.write(data)
        }
    }
}
