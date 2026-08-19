import Foundation
import QwenVoiceCore
#if canImport(Darwin)
import Darwin
#endif

/// A user-facing CLI error whose message is printed verbatim (no stack noise).
struct CLIError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { self.description = message }
}

/// Minimal flag parser: `--key value` pairs, `--key=value`, bare `--flag`s, and
/// positionals. A bare `--` ends flag parsing (everything after is positional).
/// Note: a value cannot itself begin with `--` (it would parse as a flag) — use
/// the `--key=value` form for such values. Clean enough for a focused tool
/// without pulling in an external arg-parser dependency.
struct Args {
    private var values: [String: String] = [:]
    private var flags: Set<String> = []
    private(set) var positionals: [String] = []

    init(_ argv: [String]) {
        var i = 0
        var flagsEnded = false
        while i < argv.count {
            let token = argv[i]
            if !flagsEnded, token == "--" {
                flagsEnded = true
                i += 1
                continue
            }
            if !flagsEnded, token.hasPrefix("--") {
                let key = String(token.dropFirst(2))
                if let eq = key.firstIndex(of: "=") {
                    values[String(key[..<eq])] = String(key[key.index(after: eq)...])
                    i += 1
                } else if i + 1 < argv.count, !argv[i + 1].hasPrefix("--") {
                    values[key] = argv[i + 1]
                    i += 2
                } else {
                    flags.insert(key)
                    i += 1
                }
            } else {
                positionals.append(token)
                i += 1
            }
        }
    }

    func string(_ key: String) -> String? { values[key] }
    func flag(_ key: String) -> Bool { flags.contains(key) }

    func require(_ key: String, _ hint: String) throws -> String {
        guard let v = values[key], !v.isEmpty else {
            throw CLIError("missing required --\(key) (\(hint))")
        }
        return v
    }
}

enum CLIPaths {
    /// Resolve the runtime data directory the engine roots at (models/, cache/,
    /// outputs/, diagnostics/). Mirrors the app's AppPaths selection without
    /// depending on the app target: explicit --data-dir wins, else
    /// QWENVOICE_APP_SUPPORT_DIR in an explicit QWENVOICE_DEBUG session, else
    /// ~/Library/Application Support/QwenVoice
    /// (or QwenVoice-Debug when QWENVOICE_DEBUG is truthy — matching the app so
    /// the CLI shares the debug-isolated models/diagnostics during benchmarks).
    static func dataDirectory(override: String?) -> URL {
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
enum CLIVerbosity: Int, Comparable {
    case quiet = 0, normal = 1, verbose = 2
    static func < (l: CLIVerbosity, r: CLIVerbosity) -> Bool { l.rawValue < r.rawValue }
}

enum CLIOutput {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var _verbosity: CLIVerbosity = .normal

    static var verbosity: CLIVerbosity {
        get { lock.lock(); defer { lock.unlock() }; return _verbosity }
        set { lock.lock(); defer { lock.unlock() }; _verbosity = newValue }
    }

    /// Configure from parsed args (call once at the start of each command).
    static func configure(_ args: Args) {
        if args.flag("quiet") { verbosity = .quiet }
        else if args.flag("verbose") { verbosity = .verbose }
    }
}

/// Human-facing progress note → stderr (stdout stays machine-readable). The one
/// definition shared by every command. Suppressed under `--quiet`.
func note(_ message: String) {
    guard CLIOutput.verbosity >= .normal else { return }
    FileHandle.standardError.write(Data("• \(message)\n".utf8))
}

/// Extra per-step detail → stderr, only under `--verbose`.
func noteVerbose(_ message: String) {
    guard CLIOutput.verbosity >= .verbose else { return }
    FileHandle.standardError.write(Data("  · \(message)\n".utf8))
}

// MARK: - JSON output + stdin

/// Print a compact, stable-keyed JSON value to stdout (the machine-readable surface).
func emitJSON<T: Encodable>(_ value: T) {
    let enc = JSONEncoder()
    enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    if let data = try? enc.encode(value), let s = String(data: data, encoding: .utf8) {
        print(s)
    }
}

/// Read all of stdin as UTF-8 when it isn't an interactive TTY (i.e. piped/redirected);
/// nil otherwise. Lets `generate`/`batch` accept piped text.
func readStdinText() -> String? {
    if isatty(FileHandle.standardInput.fileDescriptor) != 0 { return nil }
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty else { return nil }
    return String(data: data, encoding: .utf8)
}

/// True when stdin is an interactive terminal (a human is typing) — used to decide
/// whether to show interactive prompts vs. fall back to defaults for scripted/piped runs.
func isInteractiveStdin() -> Bool {
    isatty(FileHandle.standardInput.fileDescriptor) != 0
}

// MARK: - Filesystem helpers (models command)

/// Best-effort total byte size of all regular files under a directory (0 if absent).
func directorySize(_ url: URL) -> Int64 {
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
func humanBytes(_ bytes: Int64) -> String {
    let fmt = ByteCountFormatter()
    fmt.allowedUnits = [.useGB, .useMB, .useKB]
    fmt.countStyle = .file
    return fmt.string(fromByteCount: bytes)
}

/// Marketing version, preferring the built bundle's CFBundleShortVersionString so
/// `version` and the store-version seed track the packaged binary. Unsupported
/// bare `swiftc` builds have no embedded metadata and report an honest unknown.
let vocelloCLIVersion: String =
    (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
        .flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
