import Foundation
import QwenVoiceCore

/// History seeding for the `ui_test.sh ios perf` lane — the iOS counterpart
/// of the macOS `UIPerfHistorySeeder` (mirrored like `DatabaseService`, since
/// the iOS app compiles its own persistence copies).
///
/// Enabled only when `QWENVOICE_UIPERF_SEED_HISTORY=<N>` is present under the
/// `QWENVOICE_DEBUG` master gate (registered knob; the same launch-time
/// input-substitution class as the virtual microphone). Seeds are inserted
/// through the production `Generation` model and `DatabaseService`, so the
/// rows stay schema-correct across future migrations — a runner-side SQLite
/// writer would fork the schema and silently rot.
///
/// Idempotent top-up: rows are identified by the `uiperf-seed-NNNN` text
/// prefix; existing rows are kept, missing ones are added up to N. All rows
/// share one 30 s silent WAV under `outputs/uiperf/` (long enough that the
/// player-scrub scenario has a real scrubbable timeline), and `createdAt` is
/// spread backwards over days so History's date sections and sorts are
/// genuinely exercised.
enum IOSUIPerfHistorySeeder {
    static let countEnvironmentKey = "QWENVOICE_UIPERF_SEED_HISTORY"
    static let textPrefix = "uiperf-seed-"
    private static let fillerSentence =
        "A steady rehearsal line for interface measurement, spoken plainly and without ceremony."
    private static let maximumRows = 2000
    private static let seedDurationSeconds = 30.0

    static func seedIfConfigured() {
        guard let raw = RuntimeDebugGate.value(for: countEnvironmentKey),
              let requested = Int(raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              requested > 0 else {
            return
        }
        let target = min(requested, maximumRows)
        DispatchQueue.global(qos: .userInitiated).sync {
            seed(upTo: target)
        }
    }

    private static func seed(upTo target: Int) {
        guard let wavPath = try? writeSilentWAV() else { return }
        let service = DatabaseService.shared
        let existing = (try? service.fetchAllGenerations()) ?? []
        let present = Set(
            existing.compactMap { generation -> Int? in
                guard generation.text.hasPrefix(textPrefix) else { return nil }
                let tail = generation.text.dropFirst(textPrefix.count).prefix(4)
                return Int(tail)
            })
        let modes = ["custom", "design", "clone"]
        for index in 0..<target where !present.contains(index) {
            var generation = Generation(
                text: String(format: "%@%04d · %@", textPrefix, index, fillerSentence),
                mode: modes[index % modes.count],
                modelTier: "pro",
                voice: index % 3 == 0 ? "aiden" : nil,
                emotion: nil,
                speed: nil,
                audioPath: wavPath,
                duration: seedDurationSeconds,
                createdAt: Date().addingTimeInterval(Double(-index) * 3_600 * 7)
            )
            try? service.saveGeneration(&generation)
        }
    }

    /// A minimal valid 24 kHz mono PCM16 WAV of 30 s silence, written once.
    private static func writeSilentWAV() throws -> String {
        let directory = AppPaths.outputsDir
            .appendingPathComponent("uiperf", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("seed.wav")
        if FileManager.default.fileExists(atPath: url.path) {
            return url.path
        }
        let sampleRate: UInt32 = 24_000
        let frames = UInt32(Double(sampleRate) * seedDurationSeconds)
        let dataBytes = frames * 2
        var header = Data()
        func append(_ string: String) { header.append(string.data(using: .ascii)!) }
        func append32(_ value: UInt32) { withUnsafeBytes(of: value.littleEndian) { header.append(contentsOf: $0) } }
        func append16(_ value: UInt16) { withUnsafeBytes(of: value.littleEndian) { header.append(contentsOf: $0) } }
        append("RIFF"); append32(36 + dataBytes); append("WAVE")
        append("fmt "); append32(16); append16(1); append16(1)
        append32(sampleRate); append32(sampleRate * 2); append16(2); append16(16)
        append("data"); append32(dataBytes)
        header.append(Data(count: Int(dataBytes)))
        try header.write(to: url, options: .atomic)
        return url.path
    }
}
