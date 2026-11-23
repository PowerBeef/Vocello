import Foundation
import QwenVoiceCore

/// App-level adapter over QwenVoiceCore's canonical persisted-WAV QC algorithm,
/// shared by the macOS batch runner and the iOS long-form project. Both use the
/// same versioned thresholds and the same file-backed evidence; there is no
/// per-platform analyzer.
enum AudioQualityGate {
    struct Report: Codable, Equatable {
        let passed: Bool
        let requiredFailures: [String]
        let warnings: [String]
        let metrics: [String: Double]
        let checks: [Check]
    }

    struct Check: Codable, Equatable {
        let name: String
        let passed: Bool
        let severity: Severity
        let message: String?
        let metrics: [String: Double]
    }

    enum Severity: String, Codable {
        case error
        case warning
    }

    static func evaluate(url: URL, expectedPauseCount: Int = 0) -> Report {
        do {
            return report(
                from: try PersistedWAVAudioQCAnalyzer.evaluate(
                    url: url,
                    expectedPauseCount: expectedPauseCount
                )
            )
        } catch {
            let check = Check(
                name: "persisted_wav_readable",
                passed: false,
                severity: .error,
                message: error.localizedDescription,
                metrics: [:]
            )
            return Report(
                passed: false,
                requiredFailures: [check.name],
                warnings: [],
                metrics: [:],
                checks: [check]
            )
        }
    }

    /// Converts an already-computed `AudioQCReport` (such as the pre-watermark
    /// Fast QC report attached to `GenerationResult.audioQC`) into the app-level
    /// gate report without re-reading or re-scoring the published WAV on disk.
    static func report(from audioQC: AudioQCReport) -> Report {
        let failed = audioQC.verdict == .fail
        let warned = audioQC.verdict == .warn
        let metrics: [String: Double] = [
            "algorithm_version": Double(audioQC.algorithmVersion),
            "duration_seconds": audioQC.durationSeconds,
            "peak": audioQC.peak,
            "clipped_samples": Double(audioQC.clippedSamples),
            "hot_samples": Double(audioQC.hotSamples),
            "non_finite_samples": Double(audioQC.nonFiniteSamples),
            "click_events": Double(audioQC.clickEvents),
            "longest_silence_ms": Double(audioQC.longestSilenceMS),
            "rms_dbfs": audioQC.rmsDBFS ?? -160,
            "dc_offset": audioQC.dcOffset ?? 0,
        ]
        let check = Check(
            name: "persisted_wav_qc_v\(audioQC.algorithmVersion)",
            passed: !failed && !warned,
            severity: failed ? .error : .warning,
            message: audioQC.flags.isEmpty ? nil : audioQC.flags.joined(separator: ", "),
            metrics: metrics
        )
        return Report(
            passed: !failed,
            requiredFailures: failed ? [check.name] : [],
            warnings: warned ? [check.message ?? check.name] : [],
            metrics: metrics,
            checks: [check]
        )
    }
}
