import Foundation
import Synchronization

/// Signal handlers contain no Swift work: Dispatch delivers signals on a
/// dedicated queue. The first signal cancels the owned command and waits for
/// its cleanup; a second signal or deadline is explicitly a forced exit, which
/// first stops and reaps every owned child process. Once chosen, the forced
/// path is the only owner of the process exit.
public final class CLIProcessSupervisor: Sendable {
    private struct State: Sendable {
        var command: Task<Int32, Never>?
        var firstSignal: Int32?
        var finished = false
        var forcing = false
    }
    private let state = Mutex(State())
    private let children: CLIChildProcesses
    private let forceExit: @Sendable (Int32) -> Void

    /// The signal that cancelled the running command, for its typed report.
    private static let signalRecord = Mutex<Int32?>(nil)
    /// Stops the running command when stdout's reader goes away.
    private static let brokenOutputHandler = Mutex<(@Sendable () -> Void)?>(nil)

    /// The signal that cancelled the command; nil while none has.
    public static var receivedSignal: Int32? { signalRecord.withLock { $0 } }

    /// stdout's reader went away (EPIPE): the command stops as if signalled
    /// with SIGPIPE, cleaning up what it owns. Nothing more can be reported.
    @Sendable public static func outputBroken() {
        let handler = brokenOutputHandler.withLock { $0 }
        handler?()
    }

    /// A closed stdout cancels the command like a first signal (exit 141), but
    /// never escalates: after a real signal it changes nothing, so that
    /// signal's cleanup and exit status stand. Returns whether it cancelled.
    @discardableResult
    func receiveBrokenOutput() -> Bool {
        let command = state.withLock { state -> Task<Int32, Never>?? in
            guard !state.finished, state.firstSignal == nil else { return nil }
            state.firstSignal = SIGPIPE
            return .some(state.command)
        }
        guard let command else { return false }
        Self.signalRecord.withLock { $0 = SIGPIPE }
        command?.cancel()
        return true
    }

    init(children: CLIChildProcesses = CLIChildProcesses(), forceExit: @escaping @Sendable (Int32) -> Void = { code in
        CLIStandardError.write("Cancellation cleanup did not finish; forced exit. Recovery artifacts may remain.\n")
        exit(code)
    }) {
        self.children = children
        self.forceExit = forceExit
    }

    func attach(_ command: Task<Int32, Never>) {
        let cancelled = state.withLock { state in
            state.command = command
            return state.firstSignal != nil
        }
        if cancelled { command.cancel() }
    }

    func receive(_ signal: Int32) {
        let action = state.withLock { state -> (command: Task<Int32, Never>?, force: Bool, first: Bool) in
            guard !state.finished else { return (nil, false, false) }
            if state.firstSignal != nil {
                state.forcing = true
                return (nil, true, false)
            }
            state.firstSignal = signal
            return (state.command, false, true)
        }
        if action.first { Self.signalRecord.withLock { $0 = signal } }
        if action.force { forced(128 + signal) }
        else { action.command?.cancel() }
    }

    func enforceDeadline() {
        let signal = state.withLock { state -> Int32? in
            guard !state.finished, let signal = state.firstSignal else { return nil }
            state.forcing = true
            return signal
        }
        if let signal { forced(128 + signal) }
    }

    /// The exit status of the finished command, or nil when a forced exit
    /// already owns the process exit and the caller must not exit as well.
    func finish(code: Int32) -> Int32? {
        state.withLock {
            $0.finished = true
            $0.command = nil
            guard !$0.forcing else { return nil }
            return $0.firstSignal.map { 128 + $0 } ?? code
        }
    }

    /// No owned child outlives a forced exit.
    private func forced(_ code: Int32) {
        children.stopAll()
        forceExit(code)
    }

    /// `signals` exists for the in-process fixture; the CLI uses the default.
    @MainActor
    public static func run(
        signals: [Int32] = [SIGINT, SIGTERM],
        _ operation: @escaping @MainActor @Sendable () async -> Int32
    ) async -> Int32 {
        let supervisor = CLIProcessSupervisor(children: .shared)
        let queue = DispatchQueue(label: "vocello.cli.signals")
        // Arm every signal before the command task exists. Each source is
        // registered with the kernel before its disposition becomes SIG_IGN, so
        // an early signal either takes the default action while no command work
        // exists or reaches the supervisor, which holds it until `attach`.
        var sources: [any DispatchSourceSignal] = []
        for number in signals {
            let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
            // Dispatch's legacy callback API does not infer Sendable here.
            // Explicit isolation prevents this MainActor factory from lending
            // actor isolation to a callback executed on the signal queue.
            source.setEventHandler { @Sendable in
                supervisor.receive(number)
                queue.asyncAfter(deadline: .now() + 30) { @Sendable in supervisor.enforceDeadline() }
            }
            await withCheckedContinuation { (registered: CheckedContinuation<Void, Never>) in
                source.setRegistrationHandler { @Sendable in registered.resume() }
                source.resume()
            }
            signal(number, SIG_IGN)
            sources.append(source)
        }
        signalRecord.withLock { $0 = nil }
        brokenOutputHandler.withLock {
            $0 = { @Sendable in
                if supervisor.receiveBrokenOutput() {
                    queue.asyncAfter(deadline: .now() + 30) { @Sendable in supervisor.enforceDeadline() }
                }
            }
        }
        let command = Task { await operation() }
        supervisor.attach(command)
        // A forced exit's reap also unblocks the command while the forced
        // path goes on to call `exit` on the signal queue; returning here
        // would race it with a second `exit` from main.
        guard let code = supervisor.finish(code: await command.value) else {
            await parkForever()
        }
        for source in sources { source.cancel() }
        for number in signals { signal(number, SIG_DFL) }
        brokenOutputHandler.withLock { $0 = nil }
        return code
    }

    /// Never resumes: the forced exit ends the process. A sleep loop rather than a
    /// Never-typed continuation, which the pinned CI compiler (Xcode 26.6) rejects as
    /// "will never be executed" under warnings-as-errors.
    @concurrent private static func parkForever() async -> Never {
        while true {
            try? await Task.sleep(for: .seconds(3600))
        }
    }
}

// MARK: - Owned child processes

/// A child process the CLI launched and must not leave behind (today only
/// `--play`'s afplay). The waits report only a child that has exited and been
/// reaped; the forced path's bounded wait may give up first.
public protocol CLIChildProcess: Sendable {
    /// Graceful stop (SIGTERM), sent when the owning command is cancelled.
    func terminate()
    /// Forced stop (SIGKILL), sent only on the forced-exit path.
    func forceKill()
    @concurrent func waitUntilExit() async
    /// Bounded wait for the forced-exit path, which cannot suspend.
    func waitUntilExit(timeout: DispatchTime) -> Bool
}

/// Starts a child. Tests inject a fake, so no real player runs.
public typealias CLIProcessLauncher = @Sendable (_ executable: URL, _ arguments: [String]) throws -> any CLIChildProcess

/// Children owned by the running command. Cancelling the owning task stops its
/// child and waits for the reap before reporting cancellation; a forced exit
/// kills and reaps every live child and refuses later launches.
public final class CLIChildProcesses: Sendable {
    public static let shared = CLIChildProcesses()

    private struct State: Sendable {
        var live: [UUID: any CLIChildProcess] = [:]
        var closed = false
    }
    private let state = Mutex(State())

    var liveCount: Int { state.withLock { $0.live.count } }

    /// `stopAll` has run: a forced exit owns the process exit and its report.
    public var forcedExitBegan: Bool { state.withLock { $0.closed } }

    /// Runs one child to exit. Throws `CancellationError`, only after the
    /// child is reaped, when the owning task was cancelled.
    @concurrent func run(_ executable: URL, arguments: [String], launch: CLIProcessLauncher) async throws {
        try Task.checkCancellation()
        let id = UUID()
        // Launch under the lock: a concurrent forced exit either sees this
        // child or refuses it, never misses it.
        let child = try state.withLock { state throws -> any CLIChildProcess in
            guard !state.closed else { throw CancellationError() }
            let child = try launch(executable, arguments)
            state.live[id] = child
            return child
        }
        defer { state.withLock { _ = $0.live.removeValue(forKey: id) } }
        await withTaskCancellationHandler { @concurrent in
            await child.waitUntilExit()
        } onCancel: {
            child.terminate()
        }
        try Task.checkCancellation()
    }

    /// Forced exit: the graceful SIGTERM already went out with the first
    /// signal, so escalate to SIGKILL and wait, bounded, for each reap.
    func stopAll(timeout: DispatchTimeInterval = .seconds(2)) {
        let live = state.withLock { state -> [any CLIChildProcess] in
            state.closed = true
            return Array(state.live.values)
        }
        for child in live { child.forceKill() }
        let deadline = DispatchTime.now() + timeout
        for child in live { _ = child.waitUntilExit(timeout: deadline) }
    }
}

/// `Process`-backed child. Exit is observed through Foundation's reaping
/// termination handler, never a blocking `waitUntilExit()` on the main actor.
public final class CLIFoundationChildProcess: CLIChildProcess {
    private let process: Process
    private let exited: DispatchGroup

    public static let launch: CLIProcessLauncher = { executable, arguments in
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        let exited = DispatchGroup()
        exited.enter()
        process.terminationHandler = { @Sendable _ in exited.leave() }
        do {
            try process.run()
        } catch {
            // No termination handler runs for a child that never started;
            // balance the group, which traps if released while entered.
            process.terminationHandler = nil
            exited.leave()
            throw error
        }
        return CLIFoundationChildProcess(process: process, exited: exited)
    }

    private init(process: Process, exited: DispatchGroup) {
        self.process = process
        self.exited = exited
    }

    public func terminate() {
        if process.isRunning { process.terminate() }
    }

    public func forceKill() {
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
    }

    @concurrent public func waitUntilExit() async {
        await withCheckedContinuation { (reaped: CheckedContinuation<Void, Never>) in
            exited.notify(queue: .global(qos: .utility)) { @Sendable in reaped.resume() }
        }
    }

    public func waitUntilExit(timeout: DispatchTime) -> Bool {
        exited.wait(timeout: timeout) == .success
    }
}

/// `--play`: afplay each published file in order through an owned child. A
/// player that cannot start is a note, not an error: the output is already
/// published. A signal stops the current child and skips the rest.
public enum CLIPlayback {
    static let player = URL(fileURLWithPath: "/usr/bin/afplay")

    @concurrent public static func play(
        _ paths: [String],
        children: CLIChildProcesses = .shared,
        launch: CLIProcessLauncher = CLIFoundationChildProcess.launch
    ) async throws {
        for path in paths {
            do {
                try await children.run(player, arguments: [path], launch: launch)
            } catch let cancellation as CancellationError {
                throw cancellation
            } catch {
                note("playback unavailable: \(error.localizedDescription)")
                return
            }
        }
    }
}
