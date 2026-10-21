import Foundation
import QwenVoiceCore
import Synchronization
#if canImport(Darwin)
import Darwin
#endif

public enum CLIPaths {
    /// Resolve the runtime data directory the engine roots at (models/, cache/,
    /// outputs/, diagnostics/). Mirrors the app's AppPaths selection without
    /// depending on the app target: explicit --data-dir wins, else
    /// QWENVOICE_APP_SUPPORT_DIR in an explicit QWENVOICE_DEBUG session, else
    /// ~/Library/Application Support/QwenVoice
    /// (or QwenVoice-Debug when QWENVOICE_DEBUG is truthy — matching the app so
    /// the CLI shares the debug-isolated models/diagnostics during benchmarks).
    public static func dataDirectory(override: String?) -> URL {
        if let override, !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath, isDirectory: true)
        }
        let env = ProcessInfo.processInfo.environment
        let debug = RuntimeDebugGate.isEnabled(environment: env)
        if debug,
           let explicit = RuntimeDebugGate.value(
               for: "QWENVOICE_APP_SUPPORT_DIR",
               environment: env
           )?.trimmingCharacters(in: .whitespacesAndNewlines),
           !explicit.isEmpty,
           (explicit as NSString).isAbsolutePath {
            return URL(fileURLWithPath: explicit, isDirectory: true)
                .standardizedFileURL
                .resolvingSymlinksInPath()
        }
        let folder = debug ? "QwenVoice-Debug" : "QwenVoice"
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: (NSHomeDirectory() as NSString)
                .appendingPathComponent("Library/Application Support"), isDirectory: true)
        return base.appendingPathComponent(folder, isDirectory: true)
    }
}

// MARK: - Output verbosity

/// CLI output verbosity, set once at command start from `--quiet` / `--verbose`.
/// stdout (machine-readable surface) is never affected — only the human notes on
/// stderr are gated.
public enum CLIVerbosity: Int, Comparable, Sendable {
    case quiet = 0, normal = 1, verbose = 2
    public static func < (l: CLIVerbosity, r: CLIVerbosity) -> Bool { l.rawValue < r.rawValue }
}

public enum CLIOutput {
    private struct Settings: Sendable {
        var verbosity = CLIVerbosity.normal
        var noInput = false
        var format = CLIOutputFormat.text
    }

    private static let settings = Mutex(Settings())

    static var verbosity: CLIVerbosity {
        get { settings.withLock { $0.verbosity } }
        set { settings.withLock { $0.verbosity = newValue } }
    }

    /// Configure once from the parsed invocation. The machine formats keep
    /// stderr quiet unless `--verbose` asks for notes.
    public static func configure(_ invocation: CLIInvocation) {
        settings.withLock {
            $0.verbosity = invocation.verbosity ?? (invocation.format.isMachine ? .quiet : .normal)
            $0.noInput = invocation.noInput
            $0.format = invocation.format
        }
    }

    /// Prompts need a person: text output, a terminal and no `--no-input`.
    static var promptsAllowed: Bool {
        settings.withLock { !$0.noInput && !$0.format.isMachine } && isInteractiveStdin()
    }

    /// Unnamed piped stdin is read only in text mode without `--no-input`; the
    /// machine formats read stdin only when a flag names it (`-`), so an agent
    /// whose stdin never closes cannot hang a command.
    static var implicitStdinAllowed: Bool {
        settings.withLock { !$0.noInput && !$0.format.isMachine }
    }
}

/// Human-facing progress note → stderr (stdout stays machine-readable). The one
/// definition shared by every command. Suppressed under `--quiet`.
public func note(_ message: String) {
    guard CLIOutput.verbosity >= .normal else { return }
    CLIStandardError.write("• \(message)\n")
}

/// Extra per-step detail → stderr, only under `--verbose`.
public func noteVerbose(_ message: String) {
    guard CLIOutput.verbosity >= .verbose else { return }
    CLIStandardError.write("  · \(message)\n")
}

// MARK: - JSON output + stdin

/// Print a compact, stable-keyed bare JSON value to stdout: `bench`'s own output,
/// which is not part of the machine contract. Every other command reports through
/// `CLIPresenter`.
public func emitJSON<T: Encodable>(_ value: T) {
    let enc = JSONEncoder()
    enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    if let data = try? enc.encode(value), let s = String(data: data, encoding: .utf8) {
        print(s)
    }
}

/// Read all of stdin as UTF-8 when it isn't an interactive TTY (i.e. piped/redirected);
/// nil otherwise. For an explicit `-`; unnamed stdin goes through `readImplicitStdinText`.
public func readStdinText() -> String? {
    if isatty(FileHandle.standardInput.fileDescriptor) != 0 { return nil }
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty else { return nil }
    return String(data: data, encoding: .utf8)
}

/// Piped stdin that no flag named: read only where `CLIOutput.implicitStdinAllowed`.
public func readImplicitStdinText() -> String? {
    CLIOutput.implicitStdinAllowed ? readStdinText() : nil
}

/// True when stdin is an interactive terminal (a human is typing) — used to decide
/// whether to show interactive prompts vs. fall back to defaults for scripted/piped runs.
func isInteractiveStdin() -> Bool {
    isatty(FileHandle.standardInput.fileDescriptor) != 0
}

// MARK: - Filesystem helpers (models command)

/// Best-effort total byte size of all regular files under a directory (0 if absent).
public func directorySize(_ url: URL) -> Int64 {
    let fm = FileManager.default
    guard let en = fm.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey]) else { return 0 }
    var total: Int64 = 0
    for case let f as URL in en {
        let v = try? f.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        if v?.isRegularFile == true { total += Int64(v?.fileSize ?? 0) }
    }
    return total
}

/// Human-readable byte size (e.g. "1.7 GB").
public func humanBytes(_ bytes: Int64) -> String {
    let fmt = ByteCountFormatter()
    fmt.allowedUnits = [.useGB, .useMB, .useKB]
    fmt.countStyle = .file
    return fmt.string(fromByteCount: bytes)
}

/// Marketing version, preferring the built bundle's CFBundleShortVersionString so
/// `version` and the store-version seed track the packaged binary. Unsupported
/// bare `swiftc` builds have no embedded metadata and report an honest unknown.
public let vocelloCLIVersion: String =
    (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
        .flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
