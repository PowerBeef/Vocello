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

        var failureSummary: String {
            if requiredFailures.isEmpty {
                return "Audio quality check passed."
            }
            return "Audio quality check failed: \(requiredFailures.joined(separator: ", "))"
        }
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

    private static func report(from qc: AudioQCReport) -> Report {
        let failed = qc.verdict == .fail
        let warned = qc.verdict == .warn
        let metrics: [String: Double] = [
            "algorithm_version": Double(qc.algorithmVersion),
            "duration_seconds": qc.durationSeconds,
            "peak": qc.peak,
            "clipped_samples": Double(qc.clippedSamples),
            "hot_samples": Double(qc.hotSamples),
            "non_finite_samples": Double(qc.nonFiniteSamples),
            "click_events": Double(qc.clickEvents),
            "longest_silence_ms": Double(qc.longestSilenceMS),
            "rms_dbfs": qc.rmsDBFS ?? -160,
            "dc_offset": qc.dcOffset ?? 0,
        ]
        let check = Check(
            name: "persisted_wav_qc_v\(qc.algorithmVersion)",
            passed: !failed && !warned,
            severity: failed ? .error : .warning,
            message: qc.flags.isEmpty ? nil : qc.flags.joined(separator: ", "),
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
