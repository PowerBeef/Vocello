import Foundation

/// The file name of a generated take on both platforms: a timestamp and the
/// app's name, `20260926_14-03-07-512_Vocello.wav`.
///
/// SEC-1 (BKL-09): the name carries none of the script. A take leaves the app
/// under its own name (the iPhone share sheet, AirDrop and Files, the Mac's
/// output folder, Save As and the recovery export), so the script snippet that
/// earlier builds put in it showed the text wherever the file went. Those
/// takes keep their `<timestamp>_<snippet>.wav` names on disk; on the Mac,
/// `exportName(forTakeNamed:)` names their saved and exported copies, while the
/// iPhone share sheet still hands an earlier build's take out under its old
/// name (BKL-09). Takes are written one at a time, so the millisecond timestamp
/// keeps names unique; a long-form segment also adds a UUID
/// (`LongFormHistoryAcceptance`).
///
/// MAC-16 / IOS-16: the timestamp is formatted with the POSIX locale and the
/// Gregorian calendar, so a Buddhist or Japanese calendar, or a locale with its
/// own digits, never changes the year or the characters of a file name.
enum GenerationOutputFileName {
    /// The word after the timestamp. It names the app, never the take's content.
    static let neutralLabel = "Vocello"
    /// The `yyyyMMdd_HH-mm-ss-SSS` timestamp that begins every take's name,
    /// then `_`. The macOS playback-capture analysis matches it too
    /// (`OUTPUT_NAME_RE` in `scripts/lib/playback_capture.py`).
    private static let timestampPrefixPattern = #"^[0-9]{8}_[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{3}_"#

    static func make(date: Date = Date(), timeZone: TimeZone = .current) -> String {
        "\(timestamp(for: date, timeZone: timeZone))_\(neutralLabel).wav"
    }

    /// `yyyyMMdd_HH-mm-ss-SSS` in `timeZone`, with ASCII digits whatever the
    /// user's locale and calendar.
    static func timestamp(for date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        // The POSIX locale fixes the digits and the format; the calendar is set
        // after it because assigning a locale resets the formatter's calendar.
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyyMMdd_HH-mm-ss-SSS"
        return formatter.string(from: date)
    }

    /// SEC-1: the name a copy of the take named `name` gets where the user
    /// saves or exports it. A take name keeps its timestamp and extension and
    /// drops everything between them, an earlier build's script snippet and a
    /// long-form segment's UUID alike, so `20260926_14-03-07-512_Hello_world.wav`
    /// becomes `20260926_14-03-07-512_Vocello.wav`. A name that does not begin
    /// with a take timestamp (a joined long-form project, a recovery journal)
    /// carries no script and is returned as it is.
    static func exportName(forTakeNamed name: String) -> String {
        guard let prefix = name.range(of: timestampPrefixPattern, options: .regularExpression) else {
            return name
        }
        let stamp = name[prefix].dropLast()
        let pathExtension = (name as NSString).pathExtension
        return pathExtension.isEmpty
            ? "\(stamp)_\(neutralLabel)"
            : "\(stamp)_\(neutralLabel).\(pathExtension)"
    }
}

/// IOS-16: the iPhone has no user-chosen output folder. The `outputDirectory`
/// preference only exists for the physical-device lanes, which point it at the
/// app's pullable diagnostics folder in `Library/Caches`; a value anywhere else
/// (Documents is visible in Files, so a take written there would bypass the
/// export gate) is ignored and takes stay in the private outputs folder.
enum GenerationOutputRootOverride {
    /// The folder `configuredPath` names when it lies strictly inside
    /// `allowedRoot` once `~`, `.` and `..` are resolved; nil for an empty or
    /// relative value, a folder outside `allowedRoot`, or no `allowedRoot`.
    /// The comparison is lexical: the folders need not exist yet.
    static func acceptedRoot(configuredPath: String, allowedRoot: URL?) -> URL? {
        let trimmed = configuredPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let allowedRoot else { return nil }
        let expanded = (trimmed as NSString).expandingTildeInPath
        guard expanded.hasPrefix("/") else { return nil }
        let candidate = URL(fileURLWithPath: expanded, isDirectory: true).standardizedFileURL
        let candidateComponents = comparableComponents(of: candidate)
        let rootComponents = comparableComponents(of: allowedRoot)
        guard candidateComponents.count > rootComponents.count,
              Array(candidateComponents.prefix(rootComponents.count)) == rootComponents else {
            return nil
        }
        return candidate
    }

    /// Standardized components, with the `/private` alias of `/var` and `/tmp`
    /// folded so a container path matches however it was spelled.
    private static func comparableComponents(of url: URL) -> [String] {
        var components = url.standardizedFileURL.pathComponents
        if components.count > 2, components[0] == "/", components[1] == "private",
           components[2] == "var" || components[2] == "tmp" {
            components.remove(at: 1)
        }
        return components
    }
}
