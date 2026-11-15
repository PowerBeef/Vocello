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

    /// The MCP server's settings (RF-29): stdin carries the protocol, so no
    /// command reads it or prompts, and notes stay off stderr unless `--verbose`.
    public static func configureForServer(verbose: Bool) {
        settings.withLock {
            $0.noInput = true
            $0.verbosity = verbose ? .verbose : .quiet
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

// MARK: - Model ids

/// A model id as every command takes it. The contract writes ids in lowercase,
/// so an id typed in any letter case names the same model.
public enum CLIModelID {
    public static func canonical(_ raw: String) -> String { raw.lowercased() }
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

/// A download's free-space check, made before any byte is fetched, so a volume
/// that cannot hold it is refused as `storage_full` instead of failing partway.
public enum CLIStoragePreflight {
    /// Room kept free beyond the bytes themselves.
    public static let marginBytes: Int64 = 256 * 1_024 * 1_024

    /// Refuses a download of `bytesToFetch` the volume cannot hold. A download
    /// lands in staging beside the model store and moves into place by a
    /// rename, so it needs its own bytes plus the margin. An unknown capacity
    /// (`availableBytes` nil) refuses nothing.
    public static func ensureRoom(forFetching bytesToFetch: Int64, availableBytes: Int64?) throws {
        guard bytesToFetch > 0, let availableBytes else { return }
        let needed = bytesToFetch + marginBytes
        guard availableBytes < needed else { return }
        throw CLIError(
            .storageFull,
            "not enough free space: the download needs \(humanBytes(needed)) free and the volume has \(humanBytes(availableBytes))",
            hint: CLIFailure.storageFullHint,
            detail: ["requiredBytes": .string(String(needed)), "availableBytes": .string(String(availableBytes))]
        )
    }

    /// The bytes a download into `targetDirectory` still has to fetch: each planned file's size,
    /// less what an earlier attempt's kept staging already holds of that file
    /// (`.qwenvoice-downloads/<folder>` beside the model folders,
    /// `docs/reference/model-delivery.md`), which a resumed download reuses. Only planned files
    /// count, by the space they really occupy: staging also holds hard links to shared components
    /// the plan does not download, and a chunked partial is sparse, so its length overstates it.
    public static func bytesStillToFetch(
        plan: [HuggingFaceDownloader.RepoFile], targetDirectory: URL
    ) -> Int64 {
        let staging = targetDirectory.deletingLastPathComponent()
            .appendingPathComponent(".qwenvoice-downloads", isDirectory: true)
            .appendingPathComponent(targetDirectory.lastPathComponent, isDirectory: true)
        let complete = staging.appendingPathComponent("files", isDirectory: true)
        let partial = staging.appendingPathComponent("partials", isDirectory: true)
        return plan.reduce(0) { remaining, file in
            let held = max(
                occupiedBytes(of: complete.appendingPathComponent(file.path)),
                occupiedBytes(of: partial.appendingPathComponent(file.path).appendingPathExtension("partial"))
            )
            return remaining + max(0, file.size - min(held, file.size))
        }
    }

    /// The bytes a regular file occupies on disk, never more than its length; 0 when there is none.
    private static func occupiedBytes(of url: URL) -> Int64 {
        guard let values = try? url.resourceValues(
            forKeys: [.isRegularFileKey, .fileSizeKey, .totalFileAllocatedSizeKey]
        ), values.isRegularFile == true, let length = values.fileSize else { return 0 }
        return Int64(min(values.totalFileAllocatedSize ?? length, length))
    }

    /// The space available on the volume that holds `url`, read at the nearest
    /// folder that exists (a first install's model folder does not yet).
    public static func availableBytes(near url: URL) -> Int64? {
        var probe = url.standardizedFileURL
        while !FileManager.default.fileExists(atPath: probe.path), probe.path != "/" {
            probe = probe.deletingLastPathComponent()
        }
        return ModelDeliverySpace.availableBytes(at: probe)
    }
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
