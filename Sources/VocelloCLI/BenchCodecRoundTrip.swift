import Darwin
import Foundation
import QwenVoiceCore

/// A bounded codec round-trip branch of the diagnostic benchmark command (audit
/// P9, audio QC population N2). It resynthesizes digest-bound mono PCM16 24 kHz
/// recordings through the installed Voice Cloning Speed model's speech
/// tokenizer; it never synthesizes text, downloads a model, publishes benchmark
/// history or changes the source bundle.
enum BenchCodecRoundTrip {
    private struct ItemReport: Encodable {
        let id: String
        let inputSHA256: String
        var status = "pending"
        var failureCode: String?
        var inputSampleCount: Int?
        var outputPath: String?
        var outputSHA256: String?
        var outputByteCount: Int?
        var outputSampleCount: Int?
        var clampedSampleCount: Int?
        var frameCount: Int?
        var codebookCount: Int?
        var codesPath: String?
        var codesSHA256: String?
    }

    private struct Report: Encodable {
        let schemaVersion = 1
        let kind = "audio-qc-n2-roundtrip-result"
        let runID: String
        let jobSHA256: String
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
        let encoderInput = "clone_reference_encoder_input_trailing_silence_500ms"
        let decodeSemantics = "production_nonstreaming_25_frame_schedule"
        let trim = "input_sample_count"
        let outputFormat = "pcm16_mono_24000hz_without_output_limiter"
        let codesFormat = "codec_trace_v1"
        let sampleRate = CodecRoundTripEvidence.sampleRate
        var status = "started"
        var failureCode: String?
        var modelLoadCount = 0
        var elapsedSeconds: Double?
        var items: [ItemReport]
    }

    private struct Summary: Encodable {
        let runID: String
        let status: String
        let itemCount: Int
        let completeCount: Int
        let modelLoadCount: Int
        let result = "codec-roundtrip-result.json"
    }

    @MainActor
    static func run(_ args: Args) async throws {
        guard RuntimeDebugGate.isEnabled() else {
            throw CLIError("Codec round trip requires an internal-diagnostics build and QWENVOICE_DEBUG=1.")
        }
        let jobURL = URL(fileURLWithPath: try args.require("codec-roundtrip", "round-trip job JSON"))
        let output = URL(fileURLWithPath: try args.require("output-dir", "new untracked output directory"))
        // Bounds before allocation.
        guard (try jobURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max)
                <= CodecRoundTripEvidence.maximumJobBytes else {
            throw CLIError("The round-trip job exceeds the bounded size.")
        }
        let jobData = try Data(contentsOf: jobURL)
        let items: [CodecRoundTripEvidence.Item]
        do {
            items = try CodecRoundTripEvidence.decodeJob(jobData)
        } catch {
            throw CLIError("The round-trip job is invalid (\(failureCode(for: error))).")
        }
        let jobDirectory = jobURL.deletingLastPathComponent()
        // Every input is bound and parsed before a model loads or a file is written.
        for item in items {
            do {
                _ = try CodecRoundTripEvidence.verifiedInputSamples(
                    try CodecRoundTripEvidence.readBoundedInput(
                        at: CodecRoundTripEvidence.inputURL(for: item, jobDirectory: jobDirectory)
                    ),
                    expectedSHA256: item.wavSHA256
                )
            } catch {
                throw CLIError("Round-trip input \(item.id) is invalid (\(failureCode(for: error))).")
            }
        }

        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let context = try CLIRuntime.bootstrapRegistryOnly(dataDirectory: dataDirectory, manifestOverride: nil)
        let catalogURL = try CLIRuntime.locateProductionCatalogURL()
        let catalog = try ProductionModelCatalog(contentsOf: catalogURL)
        // The Base (Voice Cloning) Speed model is the one that loads the encoder;
        // every catalog artifact shares its speech tokenizer.
        let candidates = context.registry.models.filter { $0.mode == .clone && $0.id.hasSuffix("_speed") }
        guard candidates.count == 1, let model = candidates.first else {
            throw CLIError("No unambiguous Voice Cloning Speed model is registered.")
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
        // Bind the round trip to actual catalog bytes, as the codec replay does.
        try SharedModelComponentStore(modelsRoot: context.modelsDirectory).validateInstalledModelFiles(
            modelFolder: model.folder,
            expectedFiles: try artifact.files.map {
                try SharedComponentFileIdentity(relativePath: $0.relativePath, byteCount: $0.sizeBytes, sha256: $0.sha256)
            }
        )
        // mkdir is exclusive: failed or completed evidence can never be overwritten.
        guard mkdir(output.path, 0o700) == 0 else {
            throw CLIError("Round-trip output must be a new directory with an existing parent.")
        }
        let runID = "codec-roundtrip-" + UUID().uuidString.lowercased()
        var report = Report(
            runID: runID, jobSHA256: CodecRoundTripEvidence.sha256(jobData),
            modelID: model.id, catalogModelID: artifact.modelID, catalogVariantID: artifact.variantID,
            modelRepository: artifact.repo, modelRevision: artifact.revision,
            modelArtifactVersion: artifact.artifactVersion,
            catalogSHA256: try SamplingTakeEvidence.sha256FileDigest(at: catalogURL),
            tokenizerSHA256: tokenizerSHA256,
            installedManifestSHA256: try SamplingTakeEvidence.sha256FileDigest(at: manifestURL),
            installedRevision: installedManifest.revision,
            items: items.map { ItemReport(id: $0.id, inputSHA256: $0.wavSHA256) }
        )
        let reportURL = output.appendingPathComponent("codec-roundtrip-result.json")
        try write(report, to: reportURL)
        let start = Date()
        var runtime: CLIRuntime?
        var current: Int?
        do {
            let loaded = try await CLIRuntime.bootstrap(dataDirectory: dataDirectory, manifestOverride: nil)
            runtime = loaded
            for (index, item) in items.enumerated() {
                current = index
                try Task.checkCancellation()
                let samples = try CodecRoundTripEvidence.verifiedInputSamples(
                    try CodecRoundTripEvidence.readBoundedInput(
                        at: CodecRoundTripEvidence.inputURL(for: item, jobDirectory: jobDirectory)
                    ),
                    expectedSHA256: item.wavSHA256
                )
                let result = try await loaded.engine.codecRoundTrip(modelID: model.id, samples: samples)
                try Task.checkCancellation()
                if result.didLoadModel { report.modelLoadCount += 1 }
                guard report.modelLoadCount == 1 else {
                    throw CLIError("The round trip must run on exactly one model load.")
                }
                guard result.sampleRate == CodecRoundTripEvidence.sampleRate,
                      result.audio.count == samples.count else {
                    throw CodecRoundTripEvidence.EvidenceError.invalidOutput
                }
                let codes = try CodecRoundTripEvidence.codesData(result.codes)
                let codesPath = "\(item.id).codes.bin"
                try codes.write(to: output.appendingPathComponent(codesPath), options: .withoutOverwriting)
                let wavPath = "\(item.id).wav"
                let written = try CodecRoundTripEvidence.writeOutputWAV(
                    samples: result.audio, sampleRate: result.sampleRate,
                    to: output.appendingPathComponent(wavPath)
                )
                report.items[index].status = "complete"
                report.items[index].inputSampleCount = samples.count
                report.items[index].outputPath = wavPath
                report.items[index].outputSHA256 = written.sha256
                report.items[index].outputByteCount = written.byteCount
                report.items[index].outputSampleCount = written.sampleCount
                report.items[index].clampedSampleCount = written.clampedSampleCount
                report.items[index].frameCount = result.codes.count
                report.items[index].codebookCount = result.codes.first?.count
                report.items[index].codesPath = codesPath
                report.items[index].codesSHA256 = CodecRoundTripEvidence.sha256(codes)
                current = nil
                try write(report, to: reportURL)
            }
            try await loaded.engine.unloadModel()
            runtime = nil
            report.status = "complete"
            report.elapsedSeconds = Date().timeIntervalSince(start)
            try write(report, to: reportURL)
            emitJSON(Summary(
                runID: runID, status: report.status, itemCount: items.count,
                completeCount: report.items.filter { $0.status == "complete" }.count,
                modelLoadCount: report.modelLoadCount
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

    /// A fixed code, never error text: evidence failures by case, the rest
    /// as one round-trip failure.
    private static func failureCode(for error: any Error) -> String {
        if let evidence = error as? CodecRoundTripEvidence.EvidenceError {
            return "evidence_\(evidence)"
        }
        return error is CancellationError ? "cancelled" : "codec_roundtrip_failed"
    }

    private static func write(_ report: Report, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(report).write(to: url, options: .atomic)
    }
}
