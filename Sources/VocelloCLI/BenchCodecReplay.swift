import CryptoKit
import Darwin
import Foundation
import QwenVoiceCore

/// A bounded replay branch of the existing diagnostic benchmark command. It
/// consumes a collected startup-reliability take; it never synthesizes text,
/// downloads a model, publishes benchmark history, or changes the source bundle.
enum BenchCodecReplay {
    private struct Take: Decodable {
        let generationID: UUID
        let requestReceipt: GenerationRequestReceipt
        let diagnosticArtifacts: [StartupReliabilityArtifactEvidence]
        let audioQC: AudioQCReport
    }

    private struct ReplayOutput: Encodable {
        let artifact: StartupReliabilityArtifactEvidence
        let audioQC: AudioQCReport
    }

    private struct Report: Encodable {
        let schemaVersion = 1
        let sourceTakeSHA256: String
        let sourceReceipt: GenerationRequestReceipt
        let trace: StartupReliabilityArtifactEvidence
        let replayModelID: String
        let modelRevision: String
        let catalogSHA256: String
        let tokenizerSHA256: String
        let replayInstalledManifestSHA256: String
        let replayInstalledRevision: String
        let modelBinding = "all_installed_file_bytes_match_pinned_catalog"
        // Historical "full" means the shipping non-streaming schedule, not an
        // independent decoder or a single full-sequence callAsFunction pass.
        let fullReplaySemantics = "production_nonstreaming_25_frame_schedule"
        let runID: String
        var status = "started"
        var failureCode: String?
        var elapsedSeconds: Double?
        var incremental: ReplayOutput?
        var productionNonStreaming: ReplayOutput?
    }

    @MainActor
    static func run(_ args: Args) async throws {
        guard RuntimeDebugGate.isEnabled(), TelemetryGate.resolvedEnabled else {
            throw CLIError("Codec replay requires an internal-diagnostics build and QWENVOICE_DEBUG=1.")
        }
        let takeURL = URL(fileURLWithPath: try args.require("codec-replay", "collected take JSON"))
        let expectedDigest = try args.require("take-sha256", "original take digest")
        let traceURL = URL(fileURLWithPath: try args.require("codec-trace", "collected binary trace"))
        let output = URL(fileURLWithPath: try args.require("output-dir", "new untracked output directory"))
        // Bounds before allocation. The original terminal take format is reused.
        guard (try takeURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 4 * 1_024 * 1_024,
              (try traceURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 3 * 1_024 * 1_024 else {
            throw CLIError("Replay input exceeds the bounded evidence size.")
        }
        let takeData = try Data(contentsOf: takeURL)
        guard digest(takeData) == expectedDigest else { throw CLIError("Source take digest mismatch.") }
        let take = try JSONDecoder().decode(Take.self, from: takeData)
        let receipt = take.requestReceipt
        guard receipt.schemaVersion == 2,
              receipt.generationID == take.generationID.uuidString,
              receipt.conditioningMode == "custom_voice",
              let speakerID = receipt.speakerID,
              let expectedTokenizer = receipt.speechTokenizerDigest,
              receipt.modelIntegrityManifestDigest != nil,
              take.diagnosticArtifacts.filter({ $0.kind == .codecTrace }).count == 1,
              let evidence = take.diagnosticArtifacts.first(where: { $0.kind == .codecTrace }),
              let pauseCount = take.audioQC.cadence?.expectedPauseCount, pauseCount >= 0 else {
            throw CLIError("Replay requires a correlated CustomVoice v2 take and complete codec/QC identity.")
        }
        let trace = try StartupReliabilityDiagnosticEvidence.verifiedReplayTrace(
            data: Data(contentsOf: traceURL), evidence: evidence
        )
        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let context = try CLIRuntime.bootstrapRegistryOnly(dataDirectory: dataDirectory, manifestOverride: nil)
        let catalogURL = try CLIRuntime.locateProductionCatalogURL()
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        // The iOS base ID and macOS scoped ID must resolve to the SAME artifact.
        let candidates = context.registry.models.filter {
            $0.mode == .custom && $0.id.hasSuffix("_speed")
                && $0.artifactVersion == receipt.modelArtifactVersion
        }
        guard candidates.count == 1, let model = candidates.first else {
            throw CLIError("No unambiguous installed model matches the source receipt.")
        }
        let artifact = try catalog.artifactMatchingMacOSDescriptor(
            folder: model.folder, repo: model.huggingFaceRepo, revision: model.huggingFaceRevision,
            artifactVersion: model.artifactVersion, estimatedDownloadBytes: model.estimatedDownloadBytes,
            requiredRelativePaths: model.requiredRelativePaths
        )
        let modelRoot = model.installDirectory(in: context.modelsDirectory)
        let manifestURL = modelRoot.appendingPathComponent(ModelAssetIntegrityManifest.filename)
        let installedManifest = try JSONDecoder().decode(
            ModelAssetIntegrityManifest.self, from: Data(contentsOf: manifestURL)
        )
        guard (receipt.modelID == model.id || receipt.modelID == artifact.modelID),
              context.registry.allSpeakers.contains(where: { $0.id == speakerID }),
              installedManifest.repo == artifact.repo,
              installedManifest.revision.count == 40,
              installedManifest.revision.allSatisfy({ "0123456789abcdef".contains($0) }),
              artifact.files.first(where: { $0.relativePath == "speech_tokenizer/model.safetensors" })?.sha256 == expectedTokenizer else {
            throw CLIError("Installed model or tokenizer identity differs from the source take.")
        }
        // Installation manifests contain creation time and can retain an older
        // repository revision with identical files. Bind cross-host replay to
        // actual catalog bytes, not equality of installation-specific JSON.
        try SharedModelComponentStore(modelsRoot: context.modelsDirectory).validateInstalledModelFiles(
            modelFolder: model.folder,
            expectedFiles: try artifact.files.map {
                try SharedComponentFileIdentity(relativePath: $0.relativePath, byteCount: $0.sizeBytes, sha256: $0.sha256)
            }
        )
        // mkdir is exclusive: failed or completed evidence can never be overwritten.
        guard mkdir(output.path, 0o700) == 0 else { throw CLIError("Replay output must be a new directory with an existing parent.") }
        let runID = "codec-replay-" + UUID().uuidString.lowercased()
        var report = Report(
            sourceTakeSHA256: expectedDigest, sourceReceipt: receipt, trace: evidence,
            replayModelID: model.id, modelRevision: artifact.revision,
            catalogSHA256: try SamplingTakeEvidence.sha256FileDigest(at: catalogURL),
            tokenizerSHA256: expectedTokenizer,
            replayInstalledManifestSHA256: try SamplingTakeEvidence.sha256FileDigest(at: manifestURL),
            replayInstalledRevision: installedManifest.revision, runID: runID
        )
        let reportURL = output.appendingPathComponent("codec-replay-result.json")
        try write(report, to: reportURL)
        let start = Date()
        var runtime: CLIRuntime?
        do {
            let loaded = try await CLIRuntime.bootstrap(dataDirectory: dataDirectory, manifestOverride: nil)
            runtime = loaded
            let request = GenerationRequest(
                mode: .custom, modelID: model.id, text: "", outputPath: "",
                shouldStream: receipt.streaming, languageHint: receipt.language,
                payload: .custom(speakerID: speakerID, deliveryStyle: nil),
                generationID: take.generationID, seed: receipt.seed, captureCodecTrace: true
            )
            let replay = try await loaded.engine.replayStartupReliabilityCodecTrace(
                request: request, frames: trace.frames, incrementalRanges: evidence.codecChunkRanges ?? []
            )
            try Task.checkCancellation()
            let incremental = try StartupReliabilityDiagnosticEvidence.persistReplayAudio(
                samples: replay.incrementalAudio, sampleRate: replay.sampleRate, kind: .incrementalReplayAudio,
                appSupportDirectory: output, runID: runID, generationID: take.generationID, expectedPauseCount: pauseCount
            )
            report.incremental = ReplayOutput(artifact: incremental.0, audioQC: incremental.1)
            try write(report, to: reportURL)
            let full = try StartupReliabilityDiagnosticEvidence.persistReplayAudio(
                samples: replay.fullAudio, sampleRate: replay.sampleRate, kind: .fullReplayAudio,
                appSupportDirectory: output, runID: runID, generationID: take.generationID, expectedPauseCount: pauseCount
            )
            report.productionNonStreaming = ReplayOutput(artifact: full.0, audioQC: full.1)
            try await loaded.engine.unloadModel()
            runtime = nil
            report.status = "replay_complete" // NOT a generation or audio-quality PASS.
            report.elapsedSeconds = Date().timeIntervalSince(start)
            try write(report, to: reportURL)
            emitJSON(report)
        } catch {
            if let runtime { try? await runtime.engine.unloadModel() }
            report.status = error is CancellationError ? "cancelled" : "failed"
            report.failureCode = error is CancellationError ? "cancelled" : "codec_replay_failed"
            report.elapsedSeconds = Date().timeIntervalSince(start)
            try write(report, to: reportURL)
            throw error
        }
    }

    private static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func write(_ report: Report, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(report).write(to: url, options: .atomic)
    }
}
