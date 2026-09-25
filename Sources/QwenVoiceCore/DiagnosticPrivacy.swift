import Foundation

/// The privacy-safe projection every persisted or exported runtime diagnostic
/// uses for a failure (AUD-08).
///
/// Error text never reaches a diagnostic file: a Cocoa file error's
/// `localizedDescription` quotes the file name (and `String(describing:)` adds
/// the absolute `NSFilePath`), generated output names begin with the script,
/// and a wrapped error can quote whatever its caller passed. `summary(of:)`
/// keeps only code-owned identity instead. `redactedText(_:)` is the fallback
/// for text a diagnostic has to keep, such as an exception reason or a detail
/// value a runtime emits.
public enum DiagnosticPrivacy {
    public static let redactedPathMarker = "<redacted-path>"
    public static let redactedURLMarker = "<redacted-url>"
    public static let redactedEmailMarker = "<redacted-email>"
    public static let redactedTextMarker = "<redacted>"

    /// Typed classification of `error`: the allowlisted failure code from
    /// `GenerationFailureDiagnosticLogger.errorMetadata(for:)`, the error's type
    /// and enum case, its `NSError` domain and code, the domains and codes of
    /// the errors it wraps, the runtime stage and an HTTP status. It keeps no
    /// description, failure reason or user info value: the only text it reads is
    /// a payload-less enum case's name, kept when it is a plain identifier, and
    /// the only user info entry it follows is `NSUnderlyingErrorKey`, whose
    /// errors contribute their domain and code alone.
    public static func summary(of error: any Error) -> DiagnosticErrorSummary {
        let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: error)
        let nsError = error as NSError
        var httpStatus: Int?
        if let downloadError = error as? HuggingFaceDownloader.DownloadError,
           case .httpError(let statusCode, _, _) = downloadError {
            httpStatus = statusCode
        }
        let underlying = underlyingLinks(of: error)
        return DiagnosticErrorSummary(
            code: metadata.code,
            classification: metadata.classification.rawValue,
            type: codeIdentifier(String(reflecting: type(of: error))),
            caseName: enumCaseName(of: error),
            domain: codeIdentifier(nsError.domain),
            domainCode: nsError.code,
            stage: (error as? NativeRuntimeError)?.stage.rawValue,
            httpStatus: httpStatus,
            underlying: underlying.isEmpty ? nil : underlying
        )
    }

    /// Best-effort redaction for text a diagnostic must keep: URLs, email
    /// addresses, quoted spans (the form Cocoa and most localized errors use for
    /// file and item names) and absolute or home-relative paths, which are
    /// removed through the end of their clause because paths contain spaces.
    /// The result is bounded to `limit` characters. Prefer `summary(of:)`: this
    /// cannot recognize a prompt or transcript that is not quoted.
    public static func redactedText(_ text: String, limit: Int = 240) -> String {
        var value = text
        for (pattern, template) in redactionRules {
            value = value.replacingOccurrences(
                of: pattern,
                with: template,
                options: .regularExpression
            )
        }
        return String(value.prefix(max(0, limit)))
    }

    /// Redacts every value of a diagnostic detail map and drops the value of a
    /// key that names user content outright.
    public static func redactedDetails(
        _ details: [String: String],
        valueLimit: Int = 512
    ) -> [String: String] {
        details.reduce(into: [:]) { result, entry in
            if contentKeys.contains(entry.key.lowercased()) {
                result[entry.key] = redactedTextMarker
            } else {
                result[entry.key] = redactedText(entry.value, limit: valueLimit)
            }
        }
    }

    /// A MetricKit diagnostic payload (`MXDiagnosticPayload.jsonRepresentation()`)
    /// with each uncaught Objective-C exception reason's message, format string
    /// and arguments passed through `redactedText`, the same treatment as the
    /// crash observer's own exception record. Call stacks and metadata stay for
    /// symbolication. A payload without an exception reason is returned as is;
    /// one that is not JSON returns nil, so a caller never persists it unread.
    public static func redactedMetricKitPayload(_ json: Data) -> Data? {
        guard let object = try? JSONSerialization.jsonObject(with: json) else { return nil }
        var changed = false
        let redacted = redactingExceptionReasons(in: object, changed: &changed)
        guard changed else { return json }
        return try? JSONSerialization.data(withJSONObject: redacted, options: [.prettyPrinted, .sortedKeys])
    }

    /// `MXCrashDiagnosticObjectiveCExceptionReason` text fields; its
    /// `exceptionName`, `className` and `exceptionType` are runtime-owned.
    private static let exceptionReasonTextKeys: Set<String> = ["composedMessage", "formatString"]

    private static func redactingExceptionReasons(in value: Any, changed: inout Bool) -> Any {
        if var dictionary = value as? [String: Any] {
            let isExceptionReason = dictionary["composedMessage"] != nil
            for (key, element) in dictionary {
                if isExceptionReason, exceptionReasonTextKeys.contains(key), let text = element as? String {
                    dictionary[key] = redactedText(text, limit: 512)
                    changed = true
                } else if isExceptionReason, key == "arguments", let arguments = element as? [Any] {
                    var redactedArguments: [Any] = []
                    for argument in arguments {
                        if let text = argument as? String {
                            redactedArguments.append(redactedText(text, limit: 512))
                        } else {
                            redactedArguments.append(argument)
                        }
                    }
                    dictionary[key] = redactedArguments
                    changed = true
                } else {
                    dictionary[key] = redactingExceptionReasons(in: element, changed: &changed)
                }
            }
            return dictionary
        }
        if let array = value as? [Any] {
            var redactedArray: [Any] = []
            for element in array {
                redactedArray.append(redactingExceptionReasons(in: element, changed: &changed))
            }
            return redactedArray
        }
        return value
    }

    private static let contentKeys: Set<String> = [
        "text", "prompt", "script", "transcript", "instruction",
        "voicedescription", "deliverystyle", "referencetranscript",
    ]

    /// Ordered: URLs and email addresses first, then quoted spans, then paths,
    /// so a path inside quotes is removed with its quotes. A path runs to a
    /// double quote, `;`, `|`, an angle bracket or the end of the line: folder
    /// and file names may hold spaces, apostrophes, commas and parentheses.
    private static let redactionRules: [(String, String)] = [
        (#"(?i)\bfile:/[^\n"“”„«»‹›「」『』;|<>]*"#, redactedURLMarker),
        (#"[A-Za-z][A-Za-z0-9+.-]*://[^\s"'“”‘’«»<>]*"#, redactedURLMarker),
        (#"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"#, redactedEmailMarker),
        (#"“[^”\n]*”"#, "“\(redactedTextMarker)”"),
        (#"„[^“”\n]*[“”]"#, "„\(redactedTextMarker)“"),
        (#"«[^»\n]*»"#, "«\(redactedTextMarker)»"),
        (#"‹[^›\n]*›"#, "‹\(redactedTextMarker)›"),
        (#"「[^」\n]*」"#, "「\(redactedTextMarker)」"),
        (#"『[^』\n]*』"#, "『\(redactedTextMarker)』"),
        (#"‘[^’\n]*’"#, "‘\(redactedTextMarker)’"),
        (#""[^"\n]*""#, "\"\(redactedTextMarker)\""),
        (#"(^|[\s(\[{=:,])'[^'\n]*'"#, "$1'\(redactedTextMarker)'"),
        (#"(^|[\s(\[{)\]}=:,;|<>"'“„«‹「『‘])~?/(?=[^\s/])[^\n"“”„«»‹›「」『』;|<>]*"#, "$1\(redactedPathMarker)"),
    ]

    /// A type name or error domain is code-owned; anything shaped like a path,
    /// URL or address is not and is dropped whole.
    private static func codeIdentifier(_ value: String) -> String {
        if value.isEmpty
            || value.contains("/") || value.contains("\\")
            || value.contains("~") || value.contains("@") {
            return "unrecognized"
        }
        let allowed = CharacterSet.alphanumerics
            .union(CharacterSet(charactersIn: "_.-:<>,()$[] "))
        let scalars = value.unicodeScalars.filter { allowed.contains($0) }
        let identifier = String(String.UnicodeScalarView(scalars)).prefix(160)
        return identifier.isEmpty ? "unrecognized" : String(identifier)
    }

    /// The case of a Swift error enum, without its associated values.
    private static func enumCaseName(of error: any Error) -> String? {
        let mirror = Mirror(reflecting: error)
        guard mirror.displayStyle == .enum else { return nil }
        let candidate = mirror.children.first?.label ?? String(describing: error)
        guard candidate.range(
            of: #"^[A-Za-z_][A-Za-z0-9_]{0,63}$"#,
            options: .regularExpression
        ) != nil else { return nil }
        return candidate
    }

    private static func underlyingLinks(of error: any Error) -> [DiagnosticErrorSummary.Link] {
        var links: [DiagnosticErrorSummary.Link] = []
        var next = directUnderlyingError(of: error)
        while let current = next, links.count < 4 {
            let nsError = current as NSError
            links.append(.init(domain: codeIdentifier(nsError.domain), code: nsError.code))
            next = directUnderlyingError(of: current)
        }
        return links
    }

    /// `NSUnderlyingErrorKey`, or the error a typed enum case carries as an
    /// associated value (the downloader's `fileDownloadFailed`).
    private static func directUnderlyingError(of error: any Error) -> (any Error)? {
        if let underlying = (error as NSError).userInfo[NSUnderlyingErrorKey] as? any Error {
            return underlying
        }
        let mirror = Mirror(reflecting: error)
        guard mirror.displayStyle == .enum,
              let payload = mirror.children.first?.value else { return nil }
        if let nested = payload as? any Error { return nested }
        for element in Mirror(reflecting: payload).children {
            if let nested = element.value as? any Error { return nested }
        }
        return nil
    }
}

/// Code-owned identity of a failure, safe to persist in any diagnostic file.
public struct DiagnosticErrorSummary: Codable, Equatable, Sendable, CustomStringConvertible {
    public struct Link: Codable, Equatable, Sendable {
        public let domain: String
        public let code: Int
    }

    public let code: String
    public let classification: String
    public let type: String
    public let caseName: String?
    public let domain: String
    public let domainCode: Int
    public let stage: String?
    public let httpStatus: Int?
    public let underlying: [Link]?

    public var description: String {
        var parts = [
            code,
            "type=\(type)\(caseName.map { ".\($0)" } ?? "")",
            "domain=\(domain)#\(domainCode)",
        ]
        if let stage { parts.append("stage=\(stage)") }
        if let httpStatus { parts.append("http=\(httpStatus)") }
        if let underlying, !underlying.isEmpty {
            parts.append("underlying=" + underlying.map { "\($0.domain)#\($0.code)" }.joined(separator: ">"))
        }
        return parts.joined(separator: " ")
    }
}
