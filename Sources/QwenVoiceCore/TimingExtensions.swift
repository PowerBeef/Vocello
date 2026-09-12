import Foundation
import Darwin

extension ContinuousClock.Instant {
    var elapsedMilliseconds: Int {
        duration(to: .now).roundedMilliseconds
    }

    /// Seconds elapsed on the monotonic clock. Wall time for throughput figures
    /// (RTF) must come from here, never from `Date()`, which can jump.
    public var elapsedSeconds: Double {
        duration(to: .now).seconds
    }
}

extension Duration {
    /// Fractional seconds.
    public var seconds: Double {
        let components = components
        return Double(components.seconds) + Double(components.attoseconds) / 1_000_000_000_000_000
    }

    var roundedMilliseconds: Int {
        let components = components
        let secondsMS = Double(components.seconds) * 1_000
        let attosecondsMS = Double(components.attoseconds) / 1_000_000_000_000_000
        return Int((secondsMS + attosecondsMS).rounded())
    }
}

/// High-resolution clock that pairs the portable `ProcessInfo.systemUptime`
/// millisecond timeline with `mach_absolute_time` nanoseconds. Both values share
/// the same start instant so stage marks and memory samples can join by `tMS`
/// while nanosecond-span keys capture sub-millisecond latency.
public struct NativeTelemetryClock: Sendable {
    public let startUptimeSeconds: TimeInterval
    public let startMachAbs: UInt64
    private let nanosecondsPerMachUnit: Double

    public init(
        startUptimeSeconds: TimeInterval = ProcessInfo.processInfo.systemUptime,
        startMachAbs: UInt64 = mach_absolute_time()
    ) {
        self.startUptimeSeconds = startUptimeSeconds
        self.startMachAbs = startMachAbs
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        self.nanosecondsPerMachUnit = Double(info.numer) / Double(info.denom)
    }

    public func now() -> (ms: Int, ns: UInt64) {
        let ms = Int(
            (ProcessInfo.processInfo.systemUptime - startUptimeSeconds) * 1_000
        )
        let ns = UInt64(
            Double(mach_absolute_time() - startMachAbs) * nanosecondsPerMachUnit
        )
        return (ms, ns)
    }
}
