import CryptoKit
import Foundation
import os

/// The UI benchmark's sampling-seed policy (audit #29).
///
/// A Studio take normally samples with a fresh random seed, so a benchmark
/// cell's take length (and the occasional run-on) changes from run to run. With
/// the registered `QWENVOICE_BENCH_SEED_POLICY=cell-hash-v1` knob, which
/// `RuntimeDebugGate` honours only in an internal-diagnostics build under
/// `QWENVOICE_DEBUG`, every generation instead samples with a seed derived from
/// the benchmark cell it measures (`seed(forCell:)`: the cell ID carries the
/// mode, length, warm state and repetition), so two runs of one build produce
/// the same take per cell. Shipped builds never read the knob.
///
/// The cell comes from the process's launch schedule when the lane gives one
/// (`QWENVOICE_BENCH_SEED_CELLS`, comma-separated, consumed one per generation:
/// the iPhone benchmark runs each mode's takes in one process), else from the
/// benchmark's current-take identity (`BenchRunContext`: the macOS runner
/// rewrites it before each take). Rows stamp `samplingSeedPolicy`, and the
/// lane checkers recompute each take's seed from its cell, so a take that ran
/// under another seed fails validation. Only while this gated knob is on does
/// the benchmark's take identity (`QVOICE_MAC_BENCH_CELL` and the current-take
/// file, otherwise observability-only) select output: the seed.
public enum BenchSeedPolicy {
    public static let policyEnvironmentKey = "QWENVOICE_BENCH_SEED_POLICY"
    public static let cellScheduleEnvironmentKey = "QWENVOICE_BENCH_SEED_CELLS"
    /// seed = the first eight bytes, big-endian, of
    /// SHA-256("vocello-ui-bench-seed-v1" NUL <cell ID>).
    public static let cellHashV1 = "cell-hash-v1"
    private static let cellHashDomain = "vocello-ui-bench-seed-v1"

    private static let scheduleCursor = OSAllocatedUnfairLock(initialState: 0)

    /// The seed `cell-hash-v1` assigns to one benchmark cell ID, for example
    /// `custom/short/warm#1`. `scripts/lib/bench_seed.py` computes the same value.
    public static func seed(forCell cell: String) -> UInt64 {
        var message = Data(cellHashDomain.utf8)
        message.append(0)
        message.append(contentsOf: cell.utf8)
        return SHA256.hash(data: message).prefix(8).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
    }

    /// The active policy name, or nil when the knob is absent, unknown or not
    /// honoured by this build.
    public static var activePolicy: String? {
        // A distributed build never reads the knob, so it never copies the
        // process environment for it on the generation path either.
        guard RuntimeDebugGate.internalDiagnosticsAvailable else { return nil }
        return policy(environment: ProcessInfo.processInfo.environment)
    }

    static func policy(
        environment: [String: String],
        internalDiagnosticsAvailable: Bool = RuntimeDebugGate.internalDiagnosticsAvailable
    ) -> String? {
        let raw = RuntimeDebugGate.value(
            for: policyEnvironmentKey,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        )?.trimmingCharacters(in: .whitespacesAndNewlines)
        return raw == cellHashV1 ? raw : nil
    }

    /// The launch schedule of cells, in generation order, or nil without one.
    static func scheduledCells(
        environment: [String: String],
        internalDiagnosticsAvailable: Bool = RuntimeDebugGate.internalDiagnosticsAvailable
    ) -> [String]? {
        guard let raw = RuntimeDebugGate.value(
            for: cellScheduleEnvironmentKey,
            environment: environment,
            internalDiagnosticsAvailable: internalDiagnosticsAvailable
        ) else { return nil }
        let cells = raw.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return cells.isEmpty ? nil : cells
    }

    /// The request with the active policy's seed, or unchanged when no policy
    /// is active or no cell resolves (the checker then refuses the take). The
    /// policy seed replaces any requested seed: a benchmark take measures its
    /// cell, never a draft's pinned seed.
    public static func applying(to request: GenerationRequest) -> GenerationRequest {
        guard RuntimeDebugGate.internalDiagnosticsAvailable else { return request }
        let environment = ProcessInfo.processInfo.environment
        guard policy(environment: environment) != nil else { return request }
        let cell: String?
        if let schedule = scheduledCells(environment: environment) {
            let position = scheduleCursor.withLock { cursor -> Int in
                let current = cursor
                cursor += 1
                return current
            }
            cell = position < schedule.count ? schedule[position] : nil
        } else {
            cell = BenchRunContext.telemetryNotes()["benchCell"]
        }
        guard let cell, !cell.isEmpty else { return request }
        return request.withSeed(seed(forCell: cell))
    }
}
