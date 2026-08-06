import Foundation

/// Machine-readable AI-generation provenance for published WAV files
/// (EU AI Act Article 50(2); docs/reference/eu-ai-act-article50-assessment.md,
/// roadmap CP-2). Appends a standard RIFF `LIST/INFO` chunk after the `data`
/// chunk — legal RIFF, universally parseable — and patches the RIFF size so
/// the file stays well-formed. Works identically on both writer paths
/// (in-memory header builder and the streaming `AVAudioFile` output) because
/// it operates on the finalized file.
///
/// Not yet applied by the publication path: the metadata chunk and the
/// AudioSeal watermark flip on together (one byte-identity discontinuity for
/// the fixed-seed evidence methodology) when the marking component ships.
public enum WAVProvenanceChunk {
    /// The machine-readable generation statement embedded as `ICMT`.
    public static func comment(
        modelID: String,
        mode: String,
        createdAt: Date,
        watermarkPayload: UInt16?
    ) -> String {
        let stamp = ISO8601DateFormatter().string(from: createdAt)
        var fields = [
            "AI-generated audio",
            "generator=Vocello",
            "engine=Qwen3-TTS",
            "model=\(modelID)",
            "mode=\(mode)",
            "created=\(stamp)",
        ]
        if let payload = watermarkPayload {
            fields.append(String(format: "marking=AudioSeal:0x%04X", payload))
        }
        return fields.joined(separator: "; ")
    }

    /// Appends `LIST/INFO` (ISFT software tag + ICMT provenance comment) to a
    /// finalized RIFF/WAVE file and patches the RIFF chunk size.
    public static func append(
        toWAVAt url: URL,
        software: String,
        comment: String
    ) throws {
        let handle = try FileHandle(forUpdating: url)
        defer { try? handle.close() }

        // Validate the RIFF/WAVE preamble before touching anything.
        try handle.seek(toOffset: 0)
        guard let preamble = try handle.read(upToCount: 12), preamble.count == 12,
              preamble[0 ..< 4].elementsEqual("RIFF".utf8),
              preamble[8 ..< 12].elementsEqual("WAVE".utf8) else {
            throw MLXTTSEngineError.generationFailed("Provenance chunk target is not a RIFF/WAVE file.")
        }

        var chunk = Data()
        func appendField(_ fourCC: String, _ text: String) {
            var payload = Data(text.utf8)
            payload.append(0) // INFO strings are NUL-terminated
            if payload.count % 2 == 1 { payload.append(0) } // word alignment
            chunk.append(contentsOf: fourCC.utf8)
            appendUInt32LE(UInt32(payload.count), to: &chunk)
            chunk.append(payload)
        }
        appendField("ISFT", software)
        appendField("ICMT", comment)

        var list = Data()
        list.append(contentsOf: "LIST".utf8)
        appendUInt32LE(UInt32(chunk.count + 4), to: &list)
        list.append(contentsOf: "INFO".utf8)
        list.append(chunk)

        let end = try handle.seekToEnd()
        guard end >= 44, end + UInt64(list.count) <= UInt64(UInt32.max) else {
            throw MLXTTSEngineError.generationFailed("Provenance chunk would overflow the RIFF size field.")
        }
        try handle.write(contentsOf: list)

        // RIFF size = file length - 8.
        let riffSize = UInt32(end + UInt64(list.count) - 8)
        var sizeField = Data()
        appendUInt32LE(riffSize, to: &sizeField)
        try handle.seek(toOffset: 4)
        try handle.write(contentsOf: sizeField)
        try handle.synchronize()
    }

    /// Reads back the `INFO` fields of a WAV file (validation and tests).
    public static func readInfoFields(fromWAVAt url: URL) throws -> [String: String] {
        let data = try Data(contentsOf: url)
        var fields = [String: String]()
        var offset = 12
        while offset + 8 <= data.count {
            let fourCC = String(decoding: data[offset ..< offset + 4], as: UTF8.self)
            let size = Int(readUInt32LE(data, at: offset + 4))
            let body = offset + 8
            if fourCC == "LIST", body + 4 <= data.count,
               data[body ..< body + 4].elementsEqual("INFO".utf8) {
                var inner = body + 4
                let listEnd = min(body + size, data.count)
                while inner + 8 <= listEnd {
                    let key = String(decoding: data[inner ..< inner + 4], as: UTF8.self)
                    let length = Int(readUInt32LE(data, at: inner + 4))
                    let start = inner + 8
                    let end = min(start + length, listEnd)
                    let raw = data[start ..< end]
                    fields[key] = String(decoding: raw.prefix(while: { $0 != 0 }), as: UTF8.self)
                    inner = start + length + (length % 2)
                }
            }
            offset = body + size + (size % 2)
        }
        return fields
    }

    private static func appendUInt32LE(_ value: UInt32, to data: inout Data) {
        withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
    }

    private static func readUInt32LE(_ data: Data, at offset: Int) -> UInt32 {
        UInt32(data[offset]) | UInt32(data[offset + 1]) << 8
            | UInt32(data[offset + 2]) << 16 | UInt32(data[offset + 3]) << 24
    }
}
