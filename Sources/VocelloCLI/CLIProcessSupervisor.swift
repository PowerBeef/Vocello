import Foundation
import Synchronization

/// Signal handlers contain no Swift work: Dispatch delivers signals on a
/// dedicated queue. The first signal cancels the owned command and waits for
/// its cleanup; a second signal or deadline is explicitly a forced exit.
final class CLIProcessSupervisor: Sendable {
    private struct State: Sendable {
        var command: Task<Int32, Never>?
        var firstSignal: Int32?
        var finished = false
    }
    private let state = Mutex(State())
    private let forceExit: @Sendable (Int32) -> Void

    init(forceExit: @escaping @Sendable (Int32) -> Void = { code in
        FileHandle.standardError.write(Data("Cancellation cleanup did not finish; forced exit. Recovery artifacts may remain.\n".utf8))
        exit(code)
    }) { self.forceExit = forceExit }

    func attach(_ command: Task<Int32, Never>) {
        let cancelled = state.withLock { state in
            state.command = command
            return state.firstSignal != nil
        }
        if cancelled { command.cancel() }
    }

    func receive(_ signal: Int32) {
        let action = state.withLock { state -> (Task<Int32, Never>?, Bool) in
            guard !state.finished else { return (nil, false) }
            if state.firstSignal != nil { return (nil, true) }
            state.firstSignal = signal
            return (state.command, false)
        }
        if action.1 { forceExit(128 + signal) }
        else { action.0?.cancel() }
    }

    func enforceDeadline() {
        let signal = state.withLock { !$0.finished ? $0.firstSignal : nil }
        if let signal { forceExit(128 + signal) }
    }

    func finish(code: Int32) -> Int32 {
        state.withLock {
            $0.finished = true
            $0.command = nil
            return $0.firstSignal.map { 128 + $0 } ?? code
        }
    }

    @MainActor
    static func run(_ operation: @escaping @MainActor @Sendable () async -> Int32) async -> Int32 {
        let supervisor = CLIProcessSupervisor()
        let queue = DispatchQueue(label: "vocello.cli.signals")
        let command = Task { await operation() }
        supervisor.attach(command)
        let sources = [SIGINT, SIGTERM].map { number in
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
            // Dispatch's legacy callback API does not infer Sendable here.
            // Explicit isolation prevents this MainActor factory from lending
            // actor isolation to a callback executed on the signal queue.
            source.setEventHandler { @Sendable in
                supervisor.receive(number)
                queue.asyncAfter(deadline: .now() + 30) { @Sendable in supervisor.enforceDeadline() }
            }
            source.resume()
            return source
        }
        let code = supervisor.finish(code: await command.value)
        for source in sources { source.cancel() }
        signal(SIGINT, SIG_DFL)
        signal(SIGTERM, SIG_DFL)
        return code
    }
}
