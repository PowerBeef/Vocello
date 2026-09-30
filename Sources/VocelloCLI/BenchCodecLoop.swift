import Darwin
import Foundation
import QwenVoiceCore

/// A bounded codec-loop replay branch of the diagnostic benchmark command
/// (audio QC COD-LOOP, tier T2 of the 2026-09-25 audit, section 5.2). Each job
/// item names a generated take's recorded codec trace by digest and one loop
/// recipe; the mutated trace decodes through the same replay as `--codec-replay`
/// (its full arm: the production non-streaming 25-frame schedule and window)
/// on the installed CustomVoice Speed model, whose speech tokenizer every
/// artifact shares. It never synthesizes text, downloads a model, publishes
/// benchmark history or changes the source traces.
enum BenchCodecLoop {
    private struct ItemReport: Encodable {
        let id: String
        let traceSHA256: String
        let recipe: CodecLoopMutationEvidence.Recipe
        var status = "pending"
        var failureCode: String?
        var sourceFrameCount: Int?
        var mutatedFrameCount: Int?
        var codesPath: String?
        var codesSHA256: String?
        var wavPath: String?
        var wavSHA256: String?
        var wavByteCount: Int?
        var sampleCount: Int?
        var samplesAboveCeiling: Int?
        var marked: Bool?
    }

    private struct Report: Encodable {
        let schemaVersion = 1
        let kind = CodecLoopMutationEvidence.resultKind
        let runID: String
        let jobSHA256: String
        let jobTokenizerSHA256: String?
        let modelID: String
        let catalogModelID: String
        let catalogVariantID: String
        let modelRepository: String
        let modelRevision: String
        let modelArtifactVersion: String
        let catalogSHA256: String
        let tokenizerSHA256: String
        let installedManifestSHA256: String
        let installedRevision: String
        let modelBinding = "all_installed_file_bytes_match_pinned_catalog"
        // The replay's full arm: `fullAudio`, not an independent decoder.
        let decodeSemantics = "production_nonstreaming_25_frame_schedule"
        let sampleWindow = "quality_first_generated_frames"
        let outputStage = "pcm16_production_output_limiter_then_publication_marking"
        let sampleRate = CodecLoopMutationEvidence.sampleRate
        let markingEnabled: Bool
        var status = "started"
        var failureCode: String?
        var elapsedSeconds: Double?
        var items: [ItemReport]
    }

    private struct Summary: Encodable {
        let runID: String
        let status: String
        let itemCount: Int
        let completeCount: Int
        let result = "codec-loop-result.json"
    }

    @MainActor
    static func run(_ args: Args) async throws {
        // The replay is telemetry-gated evidence, so an explicit
        // QWENVOICE_NATIVE_TELEMETRY_MODE=off refuses it even with QWENVOICE_DEBUG=1.
        guard RuntimeDebugGate.isEnabled(), TelemetryGate.resolvedEnabled else {
            throw CLIError(
                "Codec-loop replay requires an internal-diagnostics build, QWENVOICE_DEBUG=1 "
                    + "and telemetry that is not explicitly off."
            )
        }
        let jobURL = URL(fileURLWithPath: try args.require("codec-loop", "codec-loop job JSON"))
        let output = URL(fileURLWithPath: try args.require("output-dir", "new untracked output directory"))
        // Bounds before allocation.
        guard (try jobURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max)
                <= CodecLoopMutationEvidence.maximumJobBytes else {
            throw CLIError("The codec-loop job exceeds the bounded size.")
        }
        let jobData = try Data(contentsOf: jobURL)
        let job: CodecLoopMutationEvidence.Job
        do {
            job = try CodecLoopMutationEvidence.decodeJob(jobData)
        } catch {
            throw CLIError("The codec-loop job is invalid (\(failureCode(for: error))).")
        }
        let jobDirectory = jobURL.deletingLastPathComponent()
        // Every trace is bound, parsed and its recipe applied before a model
        // loads or a file is written.
        for item in job.items {
            do {
                _ = try frames(for: item, jobDirectory: jobDirectory)
            } catch {
                throw CLIError("Codec-loop item \(item.id) is invalid (\(failureCode(for: error))).")
            }
        }

        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let context = try CLIRuntime.bootstrapRegistryOnly(dataDirectory: dataDirectory, manifestOverride: nil)
        let catalogURL = try CLIRuntime.locateProductionCatalogURL()
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        // The replay's model: every catalog artifact shares its speech tokenizer.
        let candidates = context.registry.models.filter { $0.mode == .custom && $0.id.hasSuffix("_speed") }
        guard candidates.count == 1, let model = candidates.first else {
            throw CLIError("No unambiguous CustomVoice Speed model is registered.")
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
        guard installedManifest.repo == artifact.repo,
              installedManifest.revision.count == 40,
              installedManifest.revision.allSatisfy({ "0123456789abcdef".contains($0) }),
              let tokenizerSHA256 = artifact.files.first(where: {
                  $0.relativePath == "speech_tokenizer/model.safetensors"
              })?.sha256 else {
            throw CLIError("Installed model or tokenizer identity differs from the pinned catalog.")
        }
        if let expected = job.tokenizerSHA256, expected != tokenizerSHA256 {
            throw CLIError("The source takes were generated with another speech tokenizer than the replay model's.")
        }
        // Bind the replay to actual catalog bytes, as the codec replay does.
        try SharedModelComponentStore(modelsRoot: context.modelsDirectory).validateInstalledModelFiles(
            modelFolder: model.folder,
            expectedFiles: try artifact.files.map {
                try SharedComponentFileIdentity(relativePath: $0.relativePath, byteCount: $0.sizeBytes, sha256: $0.sha256)
            }
        )
        // mkdir is exclusive: failed or completed evidence can never be overwritten.
        guard mkdir(output.path, 0o700) == 0 else {
            throw CLIError("Codec-loop output must be a new directory with an existing parent.")
        }
        let runID = "codec-loop-" + UUID().uuidString.lowercased()
        let markingEnabled = AudioMarkingPolicy.resolvedEnabled()
        var report = Report(
            runID: runID, jobSHA256: CodecLoopMutationEvidence.sha256(jobData),
            jobTokenizerSHA256: job.tokenizerSHA256,
            modelID: model.id, catalogModelID: artifact.modelID, catalogVariantID: artifact.variantID,
            modelRepository: artifact.repo, modelRevision: artifact.revision,
            modelArtifactVersion: artifact.artifactVersion,
            catalogSHA256: try SamplingTakeEvidence.sha256FileDigest(at: catalogURL),
            tokenizerSHA256: tokenizerSHA256,
            installedManifestSHA256: try SamplingTakeEvidence.sha256FileDigest(at: manifestURL),
            installedRevision: installedManifest.revision,
            markingEnabled: markingEnabled,
            items: job.items.map { ItemReport(id: $0.id, traceSHA256: $0.traceSHA256, recipe: $0.recipe) }
        )
        let reportURL = output.appendingPathComponent("codec-loop-result.json")
        try write(report, to: reportURL)
        let start = Date()
        var runtime: CLIRuntime?
        var current: Int?
        do {
            let loaded = try await CLIRuntime.bootstrap(dataDirectory: dataDirectory, manifestOverride: nil)
            runtime = loaded
            for (index, item) in job.items.enumerated() {
                current = index
                try Task.checkCancellation()
                let (source, mutated) = try frames(for: item, jobDirectory: jobDirectory)
                let codes = try CodecLoopMutationEvidence.traceData(mutated)
                let codesPath = "\(item.id).codes.bin"
                try codes.write(to: output.appendingPathComponent(codesPath), options: .withoutOverwriting)
                let request = GenerationRequest(
                    mode: .custom, modelID: model.id, text: "", outputPath: "",
                    shouldStream: false,
                    payload: .custom(speakerID: loaded.defaultSpeakerID, deliveryStyle: nil),
                    generationID: UUID(), captureCodecTrace: true
                )
                let replay = try await loaded.engine.replayStartupReliabilityCodecTrace(
                    request: request, frames: mutated,
                    incrementalRanges: CodecLoopMutationEvidence.decodeRanges(frameCount: mutated.count)
                )
                try Task.checkCancellation()
                let wavPath = "\(item.id).wav"
                let written = try CodecLoopMutationEvidence.writeLimitedWAV(
                    samples: replay.fullAudio, sampleRate: replay.sampleRate,
                    to: output.appendingPathComponent(wavPath)
                )
                report.items[index].status = "decoded"
                report.items[index].sourceFrameCount = source.count
                report.items[index].mutatedFrameCount = mutated.count
                report.items[index].codesPath = codesPath
                report.items[index].codesSHA256 = CodecLoopMutationEvidence.sha256(codes)
                report.items[index].wavPath = wavPath
                report.items[index].sampleCount = written.sampleCount
                report.items[index].samplesAboveCeiling = written.samplesAboveCeiling
                current = nil
                try write(report, to: reportURL)
            }
            try await loaded.engine.unloadModel()
            runtime = nil
            // Publication marking after the decoder is released, as a published
            // take is marked after its generation ends; its provenance chunk
            // makes the final bytes, so each digest is taken last.
            let marking = AudioMarkingConfiguration.resolve(
                modelDirectory: modelRoot, modelID: model.id, mode: GenerationMode.custom.rawValue
            )
            for (index, item) in report.items.enumerated() {
                current = index
                try Task.checkCancellation()
                guard let wavPath = item.wavPath else { throw CodecLoopMutationEvidence.EvidenceError.invalidOutput }
                let url = output.appendingPathComponent(wavPath)
                var marked = false
                if markingEnabled {
                    marked = try AudioPublicationMarker.markStagedWAV(at: url, configuration: marking)
                }
                let data = try Data(contentsOf: url)
                report.items[index].marked = marked
                report.items[index].wavSHA256 = CodecLoopMutationEvidence.sha256(data)
                report.items[index].wavByteCount = data.count
                report.items[index].status = "complete"
                current = nil
            }
            report.status = "complete"
            report.elapsedSeconds = Date().timeIntervalSince(start)
            try write(report, to: reportURL)
            emitJSON(Summary(
                runID: runID, status: report.status, itemCount: job.items.count,
                completeCount: report.items.filter { $0.status == "complete" }.count
            ))
        } catch {
            if let runtime { try? await runtime.engine.unloadModel() }
            let code = error is CancellationError ? "cancelled" : failureCode(for: error)
            if let current {
                report.items[current].status = "failed"
                report.items[current].failureCode = code
            }
            report.status = error is CancellationError ? "cancelled" : "failed"
            report.failureCode = code
            report.elapsedSeconds = Date().timeIntervalSince(start)
            try write(report, to: reportURL)
            throw error
        }
    }

    /// The item's verified source frames and the frames its recipe makes.
    private static func frames(
        for item: CodecLoopMutationEvidence.Item,
        jobDirectory: URL
    ) throws -> (source: [[Int32]], mutated: [[Int32]]) {
        let data = try CodecLoopMutationEvidence.readBoundedTrace(
            at: CodecLoopMutationEvidence.traceURL(for: item, jobDirectory: jobDirectory)
        )
        let source = try CodecLoopMutationEvidence.verifiedFrames(data, expectedSHA256: item.traceSHA256)
        return (source, try CodecLoopMutationEvidence.mutated(source, by: item.recipe))
    }

    /// A fixed code, never error text: evidence failures by case, the rest as
    /// one replay failure.
    private static func failureCode(for error: any Error) -> String {
        if let evidence = error as? CodecLoopMutationEvidence.EvidenceError {
            return "evidence_\(evidence)"
        }
        return error is CancellationError ? "cancelled" : "codec_loop_failed"
    }

    private static func write(_ report: Report, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(report).write(to: url, options: .atomic)
    }
}
