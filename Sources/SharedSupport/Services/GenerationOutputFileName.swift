import Foundation

/// The file name of a generated take on both platforms: a timestamp and a
/// short snippet of the script, `20260926_14-03-07-512_Hello_world.wav`.
///
/// MAC-16 / IOS-16: the timestamp is formatted with the POSIX locale and the
/// Gregorian calendar, so a Buddhist or Japanese calendar, or a locale with its
/// own digits, never changes the year or the characters of a file name, and the
/// snippet keeps no newline, tab or other whitespace run, only single `_`s.
enum GenerationOutputFileName {
    static let fallbackSnippet = "audio"
    static let snippetLength = 20

    static func make(text: String, date: Date = Date(), timeZone: TimeZone = .current) -> String {
        "\(timestamp(for: date, timeZone: timeZone))_\(snippet(from: text)).wav"
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

    /// Letters, digits, `_` and `-` of the script's opening, whitespace runs
    /// (newlines and tabs included) collapsed to one `_`, at most
    /// `snippetLength` characters, never starting or ending with `_`.
    static func snippet(from text: String) -> String {
        let kept = text.replacingOccurrences(of: #"[^\w\s-]"#, with: "", options: .regularExpression)
        let words = kept.split(whereSeparator: { $0.isWhitespace })
        let joined = words.joined(separator: "_")
        let clipped = String(joined.prefix(snippetLength))
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
        return clipped.isEmpty ? fallbackSnippet : clipped
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
