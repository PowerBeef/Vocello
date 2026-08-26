import Foundation
import QwenVoiceCore

/// `vocello models` — read-only inventory of the contract's models: install state,
/// on-disk size, and (for `status`) any missing required files. No download
/// machinery — honors the no-bundled-weights framing. Uses the lightweight
/// registry bootstrap (no engine boot).
enum ModelsCommand {
    struct ModelJSON: Encodable {
        let id: String
        let mode: String
        let name: String
        let installed: Bool
        let missingPaths: [String]
        let installedBytes: Int64
        let estimatedDownloadBytes: Int64?
        let updateAvailable: Bool
        let stalePaths: [String]
    }

    /// Installed-but-stale probe against the production catalog: files whose on-disk byte
    /// count no longer matches the current pinned identity. Best-effort — an unresolvable
    /// catalog entry reports no staleness rather than failing the read-only inventory.
    private static func stalePaths(
        for descriptor: ModelDescriptor,
        catalog: ProductionModelCatalog?,
        modelsDirectory: URL
    ) -> [String] {
        guard let catalog,
              let artifact = try? catalog.artifactMatchingMacOSDescriptor(
                  folder: descriptor.folder,
                  repo: descriptor.huggingFaceRepo,
                  revision: descriptor.huggingFaceRevision,
                  artifactVersion: descriptor.artifactVersion,
                  estimatedDownloadBytes: descriptor.estimatedDownloadBytes,
                  requiredRelativePaths: descriptor.requiredRelativePaths
              ) else {
            return []
        }
        return catalog.installedFileSizeMismatches(for: artifact, modelsRoot: modelsDirectory)
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        var argv = argv
        let action = argv.first?.lowercased() ?? "list"
        if action == "help" || action == "--help" { printHelp(); return }
        if action == "install" {
            argv.removeFirst()
            try await runInstall(argv)
            return
        }
        let detailed = (action == "status")
        if !argv.isEmpty, action == "list" || action == "ls" || action == "status" { argv.removeFirst() }
        guard action == "list" || action == "ls" || action == "status" || action.hasPrefix("--") else {
            throw CLIError("unknown models action '\(action)' (use list | status [<id>])")
        }

        let args = Args(argv)
        CLIOutput.configure(args)
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })

        let onlyID = args.positionals.first  // optional `status <id>` / `list <id>` filter
        let catalog = try? ProductionModelCatalog(contentsOf: CLIRuntime.locateProductionCatalogURL())

        var rows: [ModelJSON] = []
        for m in ctx.registry.models {
            if let onlyID, m.id != onlyID { continue }
            let installed: Bool
            let missing: [String]
            switch ctx.registry.availability(forModelID: m.id, in: ctx.modelsDirectory) {
            case .available: installed = true; missing = []
            case .unavailable(_, let paths): installed = false; missing = paths
            case .unknown: installed = false; missing = []
            }
            let stale = installed
                ? stalePaths(for: m, catalog: catalog, modelsDirectory: ctx.modelsDirectory)
                : []
            rows.append(ModelJSON(
                id: m.id, mode: m.mode.rawValue, name: m.name,
                installed: installed, missingPaths: missing,
                installedBytes: directorySize(m.installDirectory(in: ctx.modelsDirectory)),
                estimatedDownloadBytes: m.estimatedDownloadBytes,
                updateAvailable: !stale.isEmpty,
                stalePaths: stale))
        }
        if let onlyID, rows.isEmpty { throw CLIError("no model '\(onlyID)' in the contract") }

        if args.flag("json") { emitJSON(rows); return }

        guard !rows.isEmpty else { print("(no models in contract)"); return }
        for r in rows {
            let mark = r.updateAvailable ? "↑" : (r.installed ? "✓" : (r.missingPaths.isEmpty ? "?" : "✗"))
            var size = r.installed
                ? humanBytes(r.installedBytes)
                : (r.estimatedDownloadBytes.map { "~\(humanBytes($0)) to download" } ?? "not installed")
            if r.updateAvailable {
                size += " · update available (models install \(r.id))"
            }
            print("\(mark) \(r.id)\t[\(r.mode)]\t\(size)")
            if detailed {
                for p in r.missingPaths { print("    missing: \(p)") }
                for p in r.stalePaths { print("    stale: \(p)") }
            }
        }
    }

    /// `vocello models install <id>` — download a model via the shared `HuggingFaceDownloader`
    /// engine (the same one the macOS app uses) into the shared models directory. A
    /// CLI-installed model is immediately usable by the app, and vice-versa.
    @MainActor
    static func runInstall(_ argv: [String]) async throws {
        let args = Args(argv)
        CLIOutput.configure(args)

        guard let modelID = args.positionals.first?.lowercased() else {
            throw CLIError("install requires a model id (e.g. pro_custom_speed). Run `vocello models list` for ids.")
        }

        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })

        guard let descriptor = ctx.registry.model(id: modelID) else {
            throw CLIError("unknown model id '\(modelID)' (run `vocello models list` for valid ids)")
        }

        let targetDir = descriptor.installDirectory(in: ctx.modelsDirectory)
        let catalog = try ProductionModelCatalog(
            contentsOf: CLIRuntime.locateProductionCatalogURL()
        )
        let artifact = try catalog.artifactMatchingMacOSDescriptor(
            folder: descriptor.folder,
            repo: descriptor.huggingFaceRepo,
            revision: descriptor.huggingFaceRevision,
            artifactVersion: descriptor.artifactVersion,
            estimatedDownloadBytes: descriptor.estimatedDownloadBytes,
            requiredRelativePaths: descriptor.requiredRelativePaths
        )

        var repairingStaleInstall = false
        if case .available = ctx.registry.availability(forModelID: modelID, in: ctx.modelsDirectory) {
            let stale = catalog.installedFileSizeMismatches(for: artifact, modelsRoot: ctx.modelsDirectory)
            if stale.isEmpty {
                note("Already installed: \(modelID)")
                return
            }
            repairingStaleInstall = true
            note("Updating \(modelID): \(stale.count) file(s) no longer match the pinned catalog identity")
        }
        let modelsDirectory = ctx.modelsDirectory
        let delivery = try await Task.detached(priority: .utility) {
            try catalog.deliveryPlan(for: artifact, modelsRoot: modelsDirectory)
        }.value
        note("Installing \(modelID) from \(artifact.repo) (revision \(artifact.revision.prefix(7))\u{2026})")
        if delivery.reusedVerifiedComponent {
            noteVerbose("  reusing verified shared speech tokenizer (\(humanBytes(delivery.reusedComponentBytes)))")
        }

        let diagnostics = ModelDownloadDiagnosticsStore(
            directory: ctx.modelsDirectory
                .deletingLastPathComponent()
                .appendingPathComponent("diagnostics/model-downloads", isDirectory: true)
        )
        // A/B download-engine profile (registered debug knob; inert without
        // QWENVOICE_DEBUG). The shipping default IS the chunked profile since the
        // 2026-08-08 controlled comparison (87% median improvement). `legacy`
        // reproduces the pre-chunking profile for regression comparisons; `chunked`
        // names the default explicitly; `chunked-multisession` gives each chunk
        // worker its own URLSession so ranges cannot coalesce onto one HTTP/2/3
        // connection (measured equivalent to the shared session on this CDN; kept
        // as a diagnostic lever).
        var engineConfiguration = HuggingFaceDownloader.Configuration()
        switch RuntimeDebugGate.value(for: "QVOICE_DOWNLOAD_ENGINE_PROFILE")?
            .trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "legacy":
            engineConfiguration.chunkLargeFiles = false
            engineConfiguration.maxConnectionsPerHost = 4
            note("download engine profile: legacy")
        case "chunked":
            note("download engine profile: chunked (default)")
        case "chunked-multisession":
            engineConfiguration.chunkSessionStrategy = .perWorker
            note("download engine profile: chunked-multisession")
        default:
            break
        }
        let downloader = HuggingFaceDownloader(
            progressHandler: { progress in
                diagnostics.record(progress: progress)
                let pct = progress.totalBytes > 0
                    ? Int(Double(progress.downloadedBytes) / Double(progress.totalBytes) * 100)
                    : 0
                let speed = progress.bytesPerSecond.map { "\(humanBytes($0))/s" } ?? "—"
                let eta = progress.estimatedSecondsRemaining.map { " · ETA \(max(1, Int($0.rounded())))s" } ?? ""
                noteVerbose("  \(progress.phase.rawValue) · \(pct)% · \(humanBytes(progress.downloadedBytes))/\(humanBytes(progress.totalBytes)) · \(speed)\(eta)")
            },
            engineConfiguration: engineConfiguration,
            transferMetricsHandler: { diagnostics.record(metrics: $0) },
            artifactURLPolicy: catalog.downloadURLPolicy
        )

        do {
            let transferAccounting = try await downloader.downloadFiles(
                delivery.filesToDownload,
                repo: artifact.repo,
                revision: artifact.revision,
                to: targetDir,
                requestIdentity: ModelDownloadRequestIdentity(
                    logicalRequestID: UUID().uuidString,
                    modelID: modelID,
                    artifactVersion: artifact.artifactVersion
                ),
                installedFiles: delivery.installedFiles,
                sharedComponentPlan: delivery.sharedComponentPlan
            )
            diagnostics.recordSuccess(
                expectedBytes: descriptor.estimatedDownloadBytes ?? directorySize(targetDir),
                reusedBytes: transferAccounting.reusedVerifiedBytes
            )
        } catch {
            diagnostics.recordFailure(classification: "download", message: error.localizedDescription)
            throw error
        }

        print("✓ \(repairingStaleInstall ? "Updated" : "Installed") \(modelID) (\(humanBytes(directorySize(targetDir))))")
    }

    static func printHelp() {
        print("""
        vocello models — inventory and install models

        Usage:
          vocello models list [--json]
          vocello models status [<id>] [--json]               # adds missing-file detail
          vocello models install <id> [--verbose]             # download into the shared models dir

        <id> may be a variant-scoped id (pro_custom_speed / pro_custom_quality / …) or a
        base alias (pro_custom → preferred variant). Same engine + dir as the macOS app,
        so a CLI-installed model is immediately usable in the app.

        Options:
          --json       emit JSON instead of a table (list/status)
          --verbose    show per-update download progress (install)
          --data-dir   runtime dir (default ~/Library/Application Support/QwenVoice[-Debug])
          --manifest   override path to qwenvoice_contract.json
        """)
    }
}
