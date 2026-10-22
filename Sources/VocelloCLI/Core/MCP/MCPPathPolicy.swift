import Foundation

/// Where an MCP tool may read clips from and write audio to (RF-29). It reads
/// inside the data folder's `outputs` (History takes included) and writes inside
/// `outputs/cli` (never into the folders the app keeps takes in), and does both
/// inside the folders the server was started with (`--allow-dir`). An agent
/// names absolute paths only; symbolic links resolve before the check, so a link
/// inside an allowed folder cannot lead outside it, and a `..` component is
/// refused rather than resolved. A path outside is refused before anything about
/// it is looked at, so a refusal never says whether the file exists.
struct MCPPathPolicy: Sendable, Equatable {
    enum Access: Sendable {
        /// The file must exist.
        case read
        /// The file may not exist yet; its folder is created by the command.
        case write
    }

    /// The folders a tool may read inside and write inside, resolved.
    let readRoots: [String]
    let writeRoots: [String]

    /// `allowedFolders` must exist; `<data>/outputs` need not yet.
    init(dataDirectory: URL, allowedFolders: [URL]) throws {
        func resolved(_ url: URL) -> String { Self.resolve(url.path) ?? url.standardizedFileURL.path }
        let outputs = dataDirectory.appendingPathComponent("outputs", isDirectory: true)
        var allowed: [String] = []
        for folder in allowedFolders {
            guard (try? folder.resolvingSymlinksInPath().resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true else {
                throw CLIError(.configError, "--allow-dir names \(folder.path), which is not a folder")
            }
            allowed.append(resolved(folder))
        }
        readRoots = [resolved(outputs)] + allowed
        writeRoots = [resolved(outputs.appendingPathComponent("cli", isDirectory: true))] + allowed
    }

    /// The folders `--allow-dir` names, separated by ':' as in PATH.
    static func folders(_ value: String?) -> [URL] {
        (value ?? "").split(separator: ":", omittingEmptySubsequences: true).map {
            URL(fileURLWithPath: (String($0) as NSString).expandingTildeInPath, isDirectory: true)
        }
    }

    /// The resolved path `raw` names, when it is allowed for `access`.
    func check(_ raw: String, access: Access, argument: String) throws -> String {
        let roots = access == .read ? readRoots : writeRoots
        let expanded = (raw as NSString).expandingTildeInPath
        guard expanded.hasPrefix("/") else {
            throw refusal(argument, "\(argument) must be an absolute path", roots: roots)
        }
        guard !expanded.split(separator: "/").contains("..") else {
            throw refusal(argument, "\(argument) must not contain '..'", roots: roots)
        }
        func inside(_ path: String) -> Bool {
            roots.contains { path == $0 || path.hasPrefix($0.hasSuffix("/") ? $0 : $0 + "/") }
        }
        let outside = "\(argument) is outside the folders this server may \(access == .read ? "read" : "write")"
        guard let resolved = Self.resolve(expanded) else {
            // Named as a link to nothing only inside an allowed folder, so a
            // refusal says nothing about what lies outside.
            let lexical = URL(fileURLWithPath: expanded).standardizedFileURL.path
            let lexicallyInside = inside(lexical) || inside("/private" + lexical)
                || (lexical.hasPrefix("/private/") && inside(String(lexical.dropFirst("/private".count))))
            throw refusal(
                argument, lexicallyInside ? "\(argument) passes through a symbolic link to nothing" : outside, roots: roots
            )
        }
        guard inside(resolved) else {
            throw refusal(argument, outside, roots: roots)
        }
        if access == .read, !FileManager.default.fileExists(atPath: resolved) {
            throw CLIError(.inputFileNotFound, "\(argument): no file at \(expanded)")
        }
        return resolved
    }

    private func refusal(_ argument: String, _ message: String, roots: [String]) -> CLIError {
        CLIError(
            .pathNotAllowed, message,
            hint: "use an absolute path inside \(roots.joined(separator: " or ")); start the server with --allow-dir to add a folder",
            detail: ["argument": .string(argument)]
        )
    }

    /// The path with every symbolic link resolved: the deepest part that exists
    /// is resolved, and the rest (which does not exist yet, so holds no link)
    /// is appended to it. Nil when that deepest part is a link to nothing, which
    /// a write would otherwise follow.
    static func resolve(_ path: String) -> String? {
        var existing = URL(fileURLWithPath: path).standardizedFileURL
        var rest: [String] = []
        // Attributes describe a link itself, not what it points to.
        while (try? FileManager.default.attributesOfItem(atPath: existing.path)) == nil, existing.path != "/" {
            rest.insert(existing.lastPathComponent, at: 0)
            existing = existing.deletingLastPathComponent()
        }
        guard FileManager.default.fileExists(atPath: existing.path) else { return nil }
        var resolved = existing.resolvingSymlinksInPath()
        for component in rest { resolved.appendPathComponent(component) }
        return resolved.path
    }
}
