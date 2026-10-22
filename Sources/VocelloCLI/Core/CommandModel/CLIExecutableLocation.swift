import Foundation

/// Where this executable really lives (RF-08). MLX finds its metallib, and
/// every SwiftPM resource bundle is found, beside the executable as it was
/// loaded; started through a link (the installer's /usr/local/bin/vocello, a
/// development build/vocello, an MCP client's configured path) that is the
/// link's folder, where none of them are, and the first take fails. So a
/// process started through a link first execs itself from the real path,
/// keeping its arguments, environment, process id and standard streams.
public enum CLIExecutableLocation {
    /// Execs the real binary when this one was started through a link; returns
    /// only when it was not (or the exec failed, which runs on as before).
    public static func execFromRealPathIfLinked() {
        guard let loaded = Bundle.main.executablePath, let real = realPath(ofLoaded: loaded) else { return }
        _ = unsafe execv(real, CommandLine.unsafeArgv)
    }

    /// The path to exec when `loaded` passes through a link, else nil. The
    /// system's /private firmlinks (/tmp, /var) are not links that move the
    /// executable away from its bundles, so they never cause an exec.
    static func realPath(
        ofLoaded loaded: String,
        resolve: (String) -> String = { URL(fileURLWithPath: $0).resolvingSymlinksInPath().path },
        isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }
    ) -> String? {
        func withoutPrivate(_ path: String) -> String {
            path.hasPrefix("/private/") ? String(path.dropFirst("/private".count)) : path
        }
        let resolved = resolve(loaded)
        guard withoutPrivate(resolved) != withoutPrivate(loaded), isExecutable(resolved) else { return nil }
        return resolved
    }
}
