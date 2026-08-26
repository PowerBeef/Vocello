import Foundation
import VocelloQwen3Core

/// Publication-time audio marking (EU AI Act Article 50(2), roadmap CP-2).
///
/// Every published generation WAV carries two machine-readable marks that flip
/// on together (one byte-identity discontinuity for the fixed-seed evidence
/// methodology): the AudioSeal watermark embedded into the PCM and the
/// `LIST/INFO` provenance chunk appended after `data`. Marking runs on the
/// finalized staging file — after generation has ended, before Fast QC reads
/// the exact persisted bytes, before atomic publication — so QC always judges
/// what the user receives. The generator loads and drops inside the pass
/// (CPU-scoped in the facade), keeping the take lifecycle's peak footprint
/// unchanged; the memory-qualification lane enforces that equality
/// fail-closed.
public struct AudioMarkingConfiguration: Sendable {
    /// Catalog-delivered required artifact file, uniform across all six
    /// Speed/Quality artifacts (same digest everywhere, validated by
    /// `model_catalog_contract.py`).
    public static let weightsRelativePath = "marking/audioseal_wm16_generator_fp16.safetensors"

    public let weightsURL: URL
    public let modelID: String
    public let mode: String

    public init(weightsURL: URL, modelID: String, mode: String) {
        self.weightsURL = weightsURL
        self.modelID = modelID
        self.mode = mode
    }

    /// Resolves the marking weights inside an installed model directory.
    public static func resolve(
        modelDirectory: URL,
        modelID: String,
        mode: String
    ) -> AudioMarkingConfiguration {
        AudioMarkingConfiguration(
            weightsURL: modelDirectory.appendingPathComponent(
                weightsRelativePath,
                isDirectory: false
            ),
            modelID: modelID,
            mode: mode
        )
    }
}

/// Registered internal override (`config/runtime-debug-knobs.json`): marking
/// is default-on for every published WAV. `QWENVOICE_MARKING=off` disables
/// both marks only when the binary carries `VOCELLO_INTERNAL_DIAGNOSTICS` and
/// `QWENVOICE_DEBUG` enables overrides for that process. Distributed binaries
/// omit that capability, so there is no production path to an unmarked file.
public enum AudioMarkingPolicy {
    public static func resolvedEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        let raw = RuntimeDebugGate.value(for: "QWENVOICE_MARKING", environment: environment)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return !(raw == "off" || raw == "false" || raw == "0" || raw == "no")
    }
}

public enum AudioPublicationMarker {
    /// Test seam: deterministic suites inject a transform instead of loading
    /// real AudioSeal weights; the live transform is integration-proven by
    /// the package parity tests plus the QC-neutrality and peak-equality
    /// evidence lanes.
    public typealias PCMTransform = @Sendable ([Float]) throws -> [Float]

    /// Marks a finalized staging WAV in place: embeds the watermark into the
    /// PCM (same byte count, header untouched) and appends the provenance
    /// chunk. Returns `false` without touching the file when the registered
    /// debug override disables marking.
    @discardableResult
    public static func markStagedWAV(
        at url: URL,
        configuration: AudioMarkingConfiguration,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        transform: PCMTransform? = nil
    ) throws -> Bool {
        guard AudioMarkingPolicy.resolvedEnabled(environment: environment) else {
            return false
        }

        let layout = try WAVDataLayout(contentsOf: url)
        let pcm = try layout.readSamples(from: url)
        let marked: [Float]
        if let transform {
            marked = try transform(pcm)
        } else {
            marked = try VocelloQwen3AudioMarking.markedPCM(
                pcm,
                weightsURL: configuration.weightsURL
            )
        }
        guard marked.count == pcm.count else {
            throw MLXTTSEngineError.generationFailed(
                "Audio marking changed the sample count; the staged WAV was left unmodified."
            )
        }
        try layout.writeSamples(marked, to: url)

        try WAVProvenanceChunk.append(
            toWAVAt: url,
            software: WAVProvenanceChunk.generatorSoftware(),
            comment: WAVProvenanceChunk.comment(
                modelID: configuration.modelID,
                mode: configuration.mode,
                createdAt: Date(),
                watermarkPayload: VocelloQwen3AudioMarking.payload
            )
        )
        return true
    }

    /// Appends only the provenance chunk (long-form assembly: the joined PCM
    /// is already watermarked because every segment was marked at its own
    /// publication, so re-embedding would stack deltas for no detection
    /// gain).
    public static func appendProvenanceChunk(
        toStagedWAVAt url: URL,
        configuration: AudioMarkingConfiguration,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws {
        guard AudioMarkingPolicy.resolvedEnabled(environment: environment) else { return }
        try WAVProvenanceChunk.append(
            toWAVAt: url,
            software: WAVProvenanceChunk.generatorSoftware(),
            comment: WAVProvenanceChunk.comment(
                modelID: configuration.modelID,
                mode: configuration.mode,
                createdAt: Date(),
                watermarkPayload: VocelloQwen3AudioMarking.payload
            )
        )
    }
}

/// Chunk-walked location of a PCM16 mono `data` payload inside a RIFF/WAVE
/// file. Both product writers emit the canonical 44-byte layout; the walk
/// keeps the marker correct if a writer ever adds a chunk before `data`.
struct WAVDataLayout {
    let dataOffset: UInt64
    let sampleCount: Int

    init(contentsOf url: URL) throws {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        guard let preamble = try handle.read(upToCount: 12), preamble.count == 12,
              preamble[0 ..< 4].elementsEqual("RIFF".utf8),
              preamble[8 ..< 12].elementsEqual("WAVE".utf8) else {
            throw MLXTTSEngineError.generationFailed("Marking target is not a RIFF/WAVE file.")
        }
        var offset: UInt64 = 12
        var fmtIsPCM16Mono = false
        var found: (offset: UInt64, byteCount: Int)?
        while found == nil {
            try handle.seek(toOffset: offset)
            guard let header = try handle.read(upToCount: 8), header.count == 8 else { break }
            let fourCC = header[0 ..< 4]
            let size = Int(UInt32(header[4]) | UInt32(header[5]) << 8
                | UInt32(header[6]) << 16 | UInt32(header[7]) << 24)
            if fourCC.elementsEqual("fmt ".utf8) {
                guard let fmt = try handle.read(upToCount: min(size, 16)), fmt.count >= 16 else {
                    throw MLXTTSEngineError.generationFailed("Marking target has a truncated fmt chunk.")
                }
                let format = UInt16(fmt[0]) | UInt16(fmt[1]) << 8
                let channels = UInt16(fmt[2]) | UInt16(fmt[3]) << 8
                let bits = UInt16(fmt[14]) | UInt16(fmt[15]) << 8
                fmtIsPCM16Mono = format == 1 && channels == 1 && bits == 16
            } else if fourCC.elementsEqual("data".utf8) {
                found = (offset + 8, size)
            }
            offset += 8 + UInt64(size) + UInt64(size % 2)
        }
        guard fmtIsPCM16Mono else {
            throw MLXTTSEngineError.generationFailed("Marking supports PCM16 mono WAV output only.")
        }
        guard let data = found, data.byteCount % 2 == 0 else {
            throw MLXTTSEngineError.generationFailed("Marking target has no even-length data chunk.")
        }
        dataOffset = data.offset
        sampleCount = data.byteCount / 2
    }

    func readSamples(from url: URL) throws -> [Float] {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        try handle.seek(toOffset: dataOffset)
        guard let raw = try handle.read(upToCount: sampleCount * 2),
              raw.count == sampleCount * 2 else {
            throw MLXTTSEngineError.generationFailed("Marking target data chunk could not be read.")
        }
        var samples = [Float](repeating: 0, count: sampleCount)
        raw.withUnsafeBytes { bytes in
            let int16 = bytes.bindMemory(to: Int16.self)
            for index in 0 ..< sampleCount {
                samples[index] = Float(Int16(littleEndian: int16[index])) / 32768.0
            }
        }
        return samples
    }

    func writeSamples(_ samples: [Float], to url: URL) throws {
        precondition(samples.count == sampleCount)
        var raw = Data(capacity: sampleCount * 2)
        for value in samples {
            let clamped = max(-1.0, min(1.0, value))
            let quantized = Int16(max(-32768.0, min(32767.0, (clamped * 32767.0).rounded())))
            withUnsafeBytes(of: quantized.littleEndian) { raw.append(contentsOf: $0) }
        }
        let handle = try FileHandle(forUpdating: url)
        defer { try? handle.close() }
        try handle.seek(toOffset: dataOffset)
        try handle.write(contentsOf: raw)
        try handle.synchronize()
    }
}
