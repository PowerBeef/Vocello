import Foundation
import QwenVoiceCore
import VocelloCLICore
import VocelloDesktopCore

/// `vocello models` — the contract's models: inventory (install state, on-disk
/// size, missing or stale files), verification, installs (one, or the packages
/// the app would use: `install-recommended`), removal and the app's package
/// choices. Uses the lightweight registry bootstrap (no engine boot).
enum ModelsCommand {
    struct ModelJSON: Encodable, Sendable {
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

    struct Rows: Encodable, Sendable {
        let models: [ModelJSON]
    }

    struct Installed: Encodable, Sendable {
        let modelID: String
        let status: String
        let installedBytes: Int64
    }

    /// `install-recommended`: the package each mode uses, as `models active`
    /// resolves it, and what became of it.
    struct Recommended: Encodable, Sendable {
        let mode: String
        let modelID: String
        /// planned, update_planned, already_installed (with --plan), installed or updated.
        let status: String
        let estimatedDownloadBytes: Int64?
        let installedBytes: Int64?
    }

    struct RecommendedRows: Encodable, Sendable {
        let plan: Bool
        let models: [Recommended]
    }

    struct Removed: Encodable, Sendable {
        let removed: String
        /// The size of the model's folder; shared components another model still
        /// links stay, so the space actually freed can be smaller.
        let freedBytes: Int64
    }

    struct VerifiedModel: Encodable, Sendable {
        let id: String
        let installed: Bool
        /// True when every catalog file has its exact size and SHA-256.
        let verified: Bool
        let fileCount: Int
        let verifiedBytes: Int64
        let missingPaths: [String]
        let mismatchedPaths: [String]
        /// Present but unreadable (permissions or an I/O error).
        let unreadablePaths: [String]
    }

    struct Verified: Encodable, Sendable {
        let models: [VerifiedModel]
    }

    /// `action` is the canonical subcommand the parser resolved.
    @MainActor
    static func run(action: String, _ args: Args) async throws {
        if action == "install-recommended" {
            try await runInstallRecommended(args)
            return
        }
        if action == "remove" {
            try runRemove(args)
            return
        }
        if action == "use" {
            // The app's per-mode package choice (Settings > Models): `models active` shows what it resolves to.
            let mode = args.positionals.first ?? ""
            guard GenerationMode(rawValue: mode) != nil else {
                throw CLIError(.invalidInput, "unknown mode '\(mode)'", hint: "use custom, design or clone")
            }
            SettingsCommand.report(try SettingsCommand.set("variant.\(mode)", to: args.positionals.dropFirst().first ?? ""))
            return
        }
        if action == "prefer-lower-memory" {
            SettingsCommand.report(try SettingsCommand.set("prefer-lower-memory", to: args.positionals.first ?? ""))
            return
        }
        if action == "install" {
            try await runInstall(args)
            return
        }
        if action == "verify" {
            try await runVerify(args)
            return
        }
        if action == "active" {
            try runActive(args)
            return
        }
        let detailed = (action == "status")
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
        if let onlyID, rows.isEmpty {
            throw CLIError(.modelUnknown, "no model '\(onlyID)' in the contract", hint: "see `vocello models list` for the ids")
        }

        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(models: rows))
            return
        }

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

    struct Active: Encodable, Sendable {
        let prefersLowerMemory: Bool
        let memoryClass: String
        let modes: [DesktopModelSelection.Choice]
    }

    /// `vocello models active`: which package each mode uses, as the app picks it.
    @MainActor
    static func runActive(_ args: Args) throws {
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })
        let settings = DesktopAppSettings()
        let deviceClass = NativeMemoryPolicyResolver.deviceClass()
        let choices = DesktopModelSelection.resolve(
            registry: ctx.registry,
            explicitVariantID: { settings.explicitVariantID(for: $0) },
            prefersLowerMemory: settings.prefersLowerMemory,
            deviceClass: deviceClass,
            isInstalled: { id in
                ctx.registry.model(id: id).map { DesktopModelInventory.isComplete($0, modelsDirectory: ctx.modelsDirectory) } ?? false
            }
        )
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Active(
                prefersLowerMemory: settings.prefersLowerMemory, memoryClass: deviceClass.rawValue, modes: choices
            ))
            return
        }
        for choice in choices {
            let installed = choice.activeInstalled ? "" : "  (not installed; takes use \(choice.generationVariant ?? "none"))"
            print("\(choice.mode)\t\(choice.activeVariant ?? "-")\t\(choice.source)\(installed)")
        }
    }

    /// `vocello models verify [<id>]`: every installed model's files against the
    /// authenticated catalog's exact sizes and SHA-256 digests. Read-only; a model
    /// that is not installed is reported, not verified. Any difference exits 1
    /// (`integrity_failed`) with every row kept.
    @MainActor
    static func runVerify(_ args: Args) async throws {
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })
        let catalog = try ProductionModelCatalog(contentsOf: CLIRuntime.locateProductionCatalogURL())
        let onlyID = args.positionals.first
        let models = ctx.registry.models.filter { onlyID == nil || $0.id == onlyID }
        if let onlyID, models.isEmpty {
            throw CLIError(.modelUnknown, "no model '\(onlyID)' in the contract", hint: "see `vocello models list` for the ids")
        }
        var rows: [VerifiedModel] = []
        // A base alias shares its folder with a variant: each folder is hashed once.
        var verifiedFolders: [String: DesktopModelInventory.Verification] = [:]
        for descriptor in models {
            try Task.checkCancellation()
            let artifact = try catalog.artifactMatchingMacOSDescriptor(
                folder: descriptor.folder, repo: descriptor.huggingFaceRepo, revision: descriptor.huggingFaceRevision,
                artifactVersion: descriptor.artifactVersion, estimatedDownloadBytes: descriptor.estimatedDownloadBytes,
                requiredRelativePaths: descriptor.requiredRelativePaths
            )
            guard case .available = ctx.registry.availability(forModelID: descriptor.id, in: ctx.modelsDirectory) else {
                rows.append(VerifiedModel(
                    id: descriptor.id, installed: false, verified: false, fileCount: artifact.files.count,
                    verifiedBytes: 0, missingPaths: [], mismatchedPaths: [], unreadablePaths: []
                ))
                continue
            }
            let outcome: DesktopModelInventory.Verification
            if let earlier = verifiedFolders[artifact.folder] {
                outcome = earlier
            } else {
                note("verifying \(descriptor.id) (\(artifact.files.count) files)…")
                let modelID = descriptor.id
                let fileCount = artifact.files.count
                outcome = try await DesktopModelInventory.verify(
                    artifact.files.map {
                        DesktopModelInventory.ExpectedFile(relativePath: $0.relativePath, sizeBytes: $0.sizeBytes, sha256: $0.sha256)
                    },
                    in: ctx.modelsDirectory.appendingPathComponent(artifact.folder, isDirectory: true)
                ) { checked in
                    CLIPresenter.event(.progress, data: [
                        "modelID": .string(modelID), "filesChecked": .integer(checked), "fileCount": .integer(fileCount),
                    ])
                }
                verifiedFolders[artifact.folder] = outcome
            }
            rows.append(VerifiedModel(
                id: descriptor.id, installed: true, verified: outcome.passed, fileCount: artifact.files.count,
                verifiedBytes: outcome.verifiedBytes, missingPaths: outcome.missingPaths,
                mismatchedPaths: outcome.mismatchedPaths, unreadablePaths: outcome.unreadablePaths
            ))
        }
        let failed = rows.filter { $0.installed && !$0.verified }
        if CLIPresenter.isMachine {
            if failed.isEmpty {
                CLIPresenter.succeed(Verified(models: rows))
            } else {
                CLIPresenter.recordPartialResult(Verified(models: rows))
            }
        } else {
            for row in rows {
                let mark = !row.installed ? "–" : row.verified ? "✓" : "✗"
                let detail = !row.installed ? "not installed"
                    : row.verified ? "\(row.fileCount) files, \(humanBytes(row.verifiedBytes)) verified"
                    : "\(row.missingPaths.count) missing, \(row.mismatchedPaths.count) differ, \(row.unreadablePaths.count) unreadable"
                print("\(mark) \(row.id)\t\(detail)")
                for path in row.missingPaths { print("    missing: \(path)") }
                for path in row.mismatchedPaths { print("    differs: \(path)") }
                for path in row.unreadablePaths { print("    unreadable: \(path)") }
            }
        }
        if !failed.isEmpty {
            let unreadableOnly = failed.allSatisfy { $0.missingPaths.isEmpty && $0.mismatchedPaths.isEmpty }
            throw CLIError(
                unreadableOnly ? .ioError : .integrityFailed,
                "\(failed.count) installed model(s) differ from the authenticated catalog: \(failed.map(\.id).joined(separator: ", "))",
                hint: unreadableOnly
                    ? "check the model folder's permissions"
                    : "remove the model in the app (Settings > Models) and reinstall it with `vocello models install <id>`"
            )
        }
    }

    /// `vocello models install <id>` — download a model via the shared `HuggingFaceDownloader`
    /// engine (the same one the macOS app uses) into the shared models directory. A
    /// CLI-installed model is immediately usable by the app, and vice-versa.
    @MainActor
    static func runInstall(_ args: Args) async throws {
        guard let modelID = args.positionals.first?.lowercased() else {
            throw CLIError(.usageError, "install requires a model id (e.g. pro_custom_speed). Run `vocello models list` for ids.")
        }

        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })
        let installed = try await install(modelID, ctx: ctx)
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(installed)
        } else if installed.status != "already_installed" {
            print("✓ \(installed.status == "updated" ? "Updated" : "Installed") \(modelID) (\(humanBytes(installed.installedBytes)))")
        }
    }

    /// Installs (or repairs) one model; reports nothing on stdout. Tells a running
    /// app once its files changed.
    @MainActor
    static func install(_ modelID: String, ctx: CLIRegistryContext) async throws -> Installed {
        guard let descriptor = ctx.registry.model(id: modelID) else {
            throw CLIError(.modelUnknown, "unknown model id '\(modelID)' (run `vocello models list` for valid ids)")
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
                return Installed(modelID: modelID, status: "already_installed", installedBytes: directorySize(targetDir))
            }
            repairingStaleInstall = true
            note("Updating \(modelID): \(stale.count) file(s) no longer match the pinned catalog identity")
        }
        let modelsDirectory = ctx.modelsDirectory
        let delivery = try await Task.detached(priority: .utility) { @concurrent in
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
                CLIPresenter.event(.downloadProgress, data: [
                    "modelID": .string(modelID), "phase": .string(progress.phase.rawValue),
                    "downloadedBytes": .string(String(progress.downloadedBytes)),
                    "totalBytes": .string(String(progress.totalBytes)),
                ])
            },
            engineConfiguration: engineConfiguration,
            transferMetricsHandler: { diagnostics.record(metrics: $0) },
            rangeRetryHandler: { diagnostics.record(rangeRetry: $0) },
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
        } catch is CancellationError {
            // A signal is not a download failure.
            throw CancellationError()
        } catch {
            diagnostics.recordFailure(classification: "download", error: error)
            throw error
        }

        DesktopChangeNotice.models.post()
        return Installed(
            modelID: modelID, status: repairingStaleInstall ? "updated" : "installed", installedBytes: directorySize(targetDir)
        )
    }

    /// `vocello models install-recommended [--plan]`: installs the package each
    /// mode uses, as the app resolves it (`models active`: the explicit choice,
    /// the lower-memory preference, then this Mac's recommendation). `--plan`
    /// lists them, with their download sizes, and downloads nothing.
    @MainActor
    static func runInstallRecommended(_ args: Args) async throws {
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })
        let settings = DesktopAppSettings()
        let isInstalled: (String) -> Bool = { id in
            ctx.registry.model(id: id).map { DesktopModelInventory.isComplete($0, modelsDirectory: ctx.modelsDirectory) } ?? false
        }
        let choices = DesktopModelSelection.resolve(
            registry: ctx.registry, explicitVariantID: { settings.explicitVariantID(for: $0) },
            prefersLowerMemory: settings.prefersLowerMemory, deviceClass: NativeMemoryPolicyResolver.deviceClass(),
            isInstalled: isInstalled
        )
        let planOnly = args.flag("plan")
        let catalog = try? ProductionModelCatalog(contentsOf: CLIRuntime.locateProductionCatalogURL())
        var rows: [Recommended] = []
        for choice in choices {
            guard let modelID = choice.activeModelID else { continue }
            let estimate = ctx.registry.model(id: modelID)?.estimatedDownloadBytes
            if planOnly {
                // As `install` decides: an installed model whose files no longer match the catalog is updated.
                let status = !isInstalled(modelID) ? "planned"
                    : (ctx.registry.model(id: modelID).map { stalePaths(for: $0, catalog: catalog, modelsDirectory: ctx.modelsDirectory) }
                        ?? []).isEmpty ? "already_installed" : "update_planned"
                rows.append(Recommended(
                    mode: choice.mode, modelID: modelID, status: status, estimatedDownloadBytes: estimate, installedBytes: nil
                ))
                continue
            }
            let installed: Installed
            do {
                installed = try await install(modelID, ctx: ctx)
            } catch {
                // The installs that finished stay reported.
                CLIPresenter.recordPartialResult(RecommendedRows(plan: false, models: rows))
                throw error
            }
            rows.append(Recommended(
                mode: choice.mode, modelID: modelID, status: installed.status, estimatedDownloadBytes: estimate,
                installedBytes: installed.installedBytes
            ))
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(RecommendedRows(plan: planOnly, models: rows))
            return
        }
        for row in rows {
            let size = row.status == "planned" ? row.estimatedDownloadBytes.map { " (\(humanBytes($0)))" } ?? "" : ""
            print("\(row.mode)\t\(row.modelID)\t\(row.status)\(size)")
        }
    }

    /// `vocello models remove <id>`: removes one installed model, its staging
    /// and the shared components no other model uses, as the app's model
    /// manager does. Refused while the Vocello app or another vocello engine
    /// runs, since either may have the model loaded.
    @MainActor
    static func runRemove(_ args: Args) throws {
        let modelID = args.positionals.first?.lowercased() ?? ""
        let ctx = try CLIRuntime.bootstrapRegistryOnly(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) })
        guard let descriptor = ctx.registry.model(id: modelID) else {
            throw CLIError(.modelUnknown, "unknown model id '\(modelID)'", hint: "see `vocello models list`")
        }
        let freed = directorySize(descriptor.installDirectory(in: ctx.modelsDirectory))
        do {
            try DesktopModelRemoval.remove(
                descriptor, modelsDirectory: ctx.modelsDirectory,
                otherEngineRunning: DesktopAppPresence.isAppRunning() || !EngineHostLease.liveHosts().isEmpty
            )
        } catch DesktopModelRemoval.Refusal.notInstalled {
            throw CLIError(.modelNotInstalled, "\(modelID) is not installed")
        } catch DesktopModelRemoval.Refusal.engineRunning {
            throw CLIError(
                .engineBusy, "a Vocello engine is running (the app or another vocello) and may have \(modelID) loaded",
                hint: "quit the Vocello app and wait for other vocello commands, then retry"
            )
        } catch {
            throw CLIError(.ioError, "could not remove \(modelID): \(error.localizedDescription)")
        }
        DesktopChangeNotice.models.post()
        // A package choice that named it follows, as the app's model manager makes it follow.
        if (try? DesktopModelRemoval.reconcileChoice(
            afterRemoving: descriptor, registry: ctx.registry, modelsDirectory: ctx.modelsDirectory,
            settings: DesktopAppSettings()
        )) == true {
            DesktopChangeNotice.settings.post()
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Removed(removed: modelID, freedBytes: freed))
        } else {
            print("removed \(modelID) (\(humanBytes(freed)))")
        }
    }
}
