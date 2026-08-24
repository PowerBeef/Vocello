import Foundation

public struct NativeTelemetryWorkPlan: Equatable, Sendable {
    public let constructsSampler: Bool
    public let writesSink: Bool
    public let computesChunkQC: Bool
    public let computesDerivedDiagnostics: Bool

    public init(
        mode: NativeTelemetryMode,
        recorderPresent: Bool,
        sampleIntervalAvailable: Bool
    ) {
        let enabled = mode != .off && recorderPresent
        constructsSampler = enabled && sampleIntervalAvailable
        writesSink = enabled
        computesChunkQC = enabled && mode == .verbose
        computesDerivedDiagnostics = enabled
    }
}
import OSLog

public struct NativeTelemetryStageMark: Hashable, Codable, Sendable {
    public let tMS: Int
    public let tNS: UInt64?
    public let sequence: Int?
    public let stage: String
    public let metadata: [String: String]

    public init(
        tMS: Int,
        tNS: UInt64? = nil,
        sequence: Int? = nil,
        stage: String,
        metadata: [String: String] = [:]
    ) {
        self.tMS = tMS
        self.tNS = tNS
        self.sequence = sequence
        self.stage = stage
        self.metadata = metadata
    }

    enum CodingKeys: String, CodingKey {
        case tMS
        case tNS
        case sequence
        case stage
        case metadata
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.tMS = try container.decode(Int.self, forKey: .tMS)
        self.tNS = try container.decodeIfPresent(UInt64.self, forKey: .tNS)
        self.sequence = try container.decodeIfPresent(Int.self, forKey: .sequence)
        self.stage = try container.decode(String.self, forKey: .stage)
        self.metadata = try container.decodeIfPresent([String: String].self, forKey: .metadata) ?? [:]
    }

    static func chronologicallyPrecedes(
        _ lhs: NativeTelemetryStageMark,
        _ rhs: NativeTelemetryStageMark
    ) -> Bool {
        if let lhsNS = lhs.tNS, let rhsNS = rhs.tNS, lhsNS != rhsNS {
            return lhsNS < rhsNS
        }
        if lhs.tMS != rhs.tMS {
            return lhs.tMS < rhs.tMS
        }
        if let lhsSequence = lhs.sequence,
           let rhsSequence = rhs.sequence,
           lhsSequence != rhsSequence {
            return lhsSequence < rhsSequence
        }
        return lhs.stage < rhs.stage
    }
}

public actor NativeTelemetryRecorder {
    /// Exposed (immutable, `Sendable`) so the per-generation `NativeTelemetrySampler`
    /// can be created with the SAME start instant — `NativeTelemetrySampler.decorate`
    /// joins memory samples to stage marks by `tMS`, so a mismatched start clock
    /// would break that join. The clock also supplies high-resolution nanoseconds.
    public nonisolated let clock: NativeTelemetryClock
    private var stageMarks: [NativeTelemetryStageMark] = []
    private var observedStartupStages: Set<String> = []
    private var nextSequence: Int = 0

    public init(clock: NativeTelemetryClock) {
        self.clock = clock
    }

    public func mark(
        stage: String,
        metadata: [String: String] = [:]
    ) {
        guard registerStartupStageIfNeeded(stage) else { return }
        let (ms, ns) = clock.now()
        let sequence = nextSequence
        nextSequence += 1
        stageMarks.append(
            NativeTelemetryStageMark(
                tMS: ms,
                tNS: ns,
                sequence: sequence,
                stage: stage,
                metadata: metadata
            )
        )
    }

    /// Append a one-shot boundary observed by the actor-owned producer on its
    /// existing stream signal. The caller supplies an elapsed offset on this
    /// recorder's clock; no per-token task or actor hop is introduced.
    public func mark(
        stage: String,
        atMilliseconds tMS: Int,
        metadata: [String: String] = [:]
    ) {
        guard registerStartupStageIfNeeded(stage) else { return }
        let sequence = nextSequence
        nextSequence += 1
        stageMarks.append(
            NativeTelemetryStageMark(
                tMS: max(0, tMS),
                sequence: sequence,
                stage: stage,
                metadata: metadata
            )
        )
    }

    public func snapshot() -> [NativeTelemetryStageMark] {
        stageMarks.sorted(by: NativeTelemetryStageMark.chronologicallyPrecedes)
    }

    public func reset() {
        stageMarks.removeAll(keepingCapacity: false)
        observedStartupStages.removeAll(keepingCapacity: false)
        nextSequence = 0
    }

    private func registerStartupStageIfNeeded(_ stage: String) -> Bool {
        guard stage.hasPrefix("startup.") else { return true }
        return observedStartupStages.insert(stage).inserted
    }
}

extension NativeTelemetryRecorder {
    func mark(
        stage: NativeRuntimeStage,
        metadata: [String: String] = [:]
    ) {
        mark(stage: stage.rawValue, metadata: metadata)
    }
}

/// Maps the current Swift `Task` priority to a human-readable QoS label for
/// telemetry notes. Swift priorities are an approximation of Dispatch QoS:
/// `.userInitiated` ≈ user-initiated, `.background` ≈ background, etc.
public func currentTaskQOSNotes() -> [String: String] {
    let priority = Task.currentPriority
    let name: String
    switch priority {
    case .high: name = "high"
    case .userInitiated: name = "userInitiated"
    case .medium: name = "medium"
    case .utility: name = "utility"
    case .background: name = "background"
    case .low: name = "low"
    default: name = "priority-\(priority.rawValue)"
    }
    return ["qosClass": name]
}

/// Self-reported process scheduling state for telemetry notes. A process may
/// always inspect its own task policy, so this needs no privileges. Records
/// the darwin task role (the field `taskpolicy -c` clamps), the main thread's
/// QoS class, and the unix nice value. Added by the 2026-07-23 pipeline-pacing
/// diagnosis: identical -O engine code measured RTF 1.81 in an interactive
/// process versus ~0.75 inside the XPC service, and no unprivileged external
/// tool can read another process's role — self-reporting makes class demotion
/// visible in every generation row.
public func currentProcessSchedulingNotes() -> [String: String] {
    var notes: [String: String] = [:]

    var category = task_category_policy()
    var count = mach_msg_type_number_t(
        MemoryLayout<task_category_policy>.size / MemoryLayout<integer_t>.size
    )
    var isDefault: boolean_t = 0
    let result = withUnsafeMutablePointer(to: &category) { pointer in
        pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { rebound in
            task_policy_get(
                mach_task_self_,
                task_policy_flavor_t(TASK_CATEGORY_POLICY),
                rebound,
                &count,
                &isDefault
            )
        }
    }
    if result == KERN_SUCCESS {
        let role: String
        switch category.role {
        case TASK_FOREGROUND_APPLICATION: role = "foreground-application"
        case TASK_BACKGROUND_APPLICATION: role = "background-application"
        case TASK_NONUI_APPLICATION: role = "nonui-application"
        case TASK_DEFAULT_APPLICATION: role = "default-application"
        case TASK_CONTROL_APPLICATION: role = "control-application"
        case TASK_GRAPHICS_SERVER: role = "graphics-server"
        case TASK_UNSPECIFIED: role = "unspecified"
        default: role = "role-\(category.role.rawValue)"
        }
        notes["processTaskRole"] = role
        notes["processTaskRoleIsDefault"] = isDefault == 0 ? "false" : "true"
    } else {
        notes["processTaskRole"] = "unavailable-\(result)"
    }

    let mainQOS: String
    switch qos_class_main() {
    case QOS_CLASS_USER_INTERACTIVE: mainQOS = "userInteractive"
    case QOS_CLASS_USER_INITIATED: mainQOS = "userInitiated"
    case QOS_CLASS_DEFAULT: mainQOS = "default"
    case QOS_CLASS_UTILITY: mainQOS = "utility"
    case QOS_CLASS_BACKGROUND: mainQOS = "background"
    default: mainQOS = "qos-\(qos_class_main().rawValue)"
    }
    notes["processMainThreadQOS"] = mainQOS
    notes["processNice"] = String(getpriority(PRIO_PROCESS, 0))
    return notes
}

/// Description of an `OSSignposter` interval whose wall-clock duration should
/// also be mirrored into the durable JSONL timings map.
public struct NativeTelemetrySignpostInterval: Sendable {
    public let name: StaticString
    public let timingKey: String

    public init(name: StaticString, timingKey: String) {
        self.name = name
        self.timingKey = timingKey
    }
}

extension NativeTelemetrySignpostInterval {
    public static let prepareGeneration = Self(
        name: "Native Prepare Generation",
        timingKey: "native_prepare_generation_ms"
    )
    public static let modelLoad = Self(
        name: "Native Model Load",
        timingKey: "native_model_load_ms"
    )
    public static let cloneConditioning = Self(
        name: "Native Clone Conditioning",
        timingKey: "native_clone_conditioning_ms"
    )
    public static let explicitPrewarm = Self(
        name: "Native Explicit Prewarm",
        timingKey: "native_explicit_prewarm_ms"
    )
    public static let qualityFirstGeneration = Self(
        name: "Native Quality-First Generation",
        timingKey: "native_quality_first_generation_ms"
    )
    public static let generationStream = Self(
        name: "Native Generation Stream",
        timingKey: "native_generation_stream_ms"
    )
    public static let finalWAVFinish = Self(
        name: "Native Final WAV Finish",
        timingKey: "native_final_wav_finish_ms"
    )
}

/// Wraps an `OSSignposter` interval and writes its duration (in milliseconds)
/// into `timings[timingKey]` so the same span seen in Instruments is also
/// present in the durable JSONL row.
public func withMirroredSignpost<T>(
    _ interval: NativeTelemetrySignpostInterval,
    signposter: OSSignposter,
    recorder: NativeTelemetryRecorder?,
    timings: inout [String: Int],
    operation: () async throws -> T
) async rethrows -> T {
    let signpostState = signposter.beginInterval(interval.name)
    let startedAt = ContinuousClock.now
    defer {
        timings[interval.timingKey] = startedAt.elapsedMilliseconds
        signposter.endInterval(interval.name, signpostState)
    }
    return try await operation()
}
