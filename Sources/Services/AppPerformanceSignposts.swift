import OSLog

enum AppPerformanceSignposts {
    struct Interval {
        let name: StaticString
        let state: OSSignpostIntervalState
    }

    private static let signposter = OSSignposter(
        subsystem: "com.qwenvoice.app",
        category: "performance"
    )
    private static let log = OSLog(
        subsystem: "com.qwenvoice.app",
        category: "performance"
    )

    static func begin(_ name: StaticString) -> Interval {
        Interval(name: name, state: signposter.beginInterval(name))
    }

    static func end(_ interval: Interval) {
        signposter.endInterval(interval.name, interval.state)
    }

    static func emit(_ name: StaticString) {
        signposter.emitEvent(name)
    }

    static func emit(_ name: StaticString, message: String) {
        unsafe os_signpost(.event, log: log, name: name, "%{public}@", message)
    }
}
