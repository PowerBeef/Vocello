import Foundation
import Synchronization
import System

/// The MCP server's stdio (RF-29). stdout carries protocol messages only: they
/// go to a private copy of it, and descriptor 1 is pointed at stderr, so
/// anything else the process prints lands there instead. Messages are written
/// in order on one queue, so a caller (an engine event included) never waits
/// on the client; lines come in on a reader thread.
final class MCPStdio: Sendable {
    private struct State: Sendable {
        var broken = false
        var onBroken: (@Sendable () -> Void)?
    }

    private let output: FileDescriptor
    private let queue = DispatchQueue(label: "vocello.mcp.output")
    private let state = Mutex(State())

    private init(output: FileDescriptor) {
        self.output = output
    }

    /// Reserves stdout for protocol messages.
    static func reserve() throws -> MCPStdio {
        let copy = dup(STDOUT_FILENO)
        guard copy >= 0, fcntl(copy, F_SETFD, FD_CLOEXEC) == 0, dup2(STDERR_FILENO, STDOUT_FILENO) >= 0 else {
            throw CLIError(.ioError, "could not reserve stdout for the protocol")
        }
        return MCPStdio(output: FileDescriptor(rawValue: copy))
    }

    /// Feeds stdin's lines to `continuation` from a reader thread until stdin closes.
    static func readLines(into continuation: AsyncStream<String>.Continuation) {
        let thread = Thread {
            while let line = readLine(strippingNewline: true) {
                continuation.yield(line.hasSuffix("\r") ? String(line.dropLast()) : line)
            }
            continuation.finish()
        }
        thread.name = "vocello.mcp.input"
        thread.start()
    }

    var isBroken: Bool { state.withLock { $0.broken } }

    /// Runs `action` once if the client stops reading stdout.
    func onBroken(_ action: @escaping @Sendable () -> Void) {
        state.withLock { $0.onBroken = action }
    }

    func send(_ message: CLIJSONValue) {
        let line = MCPOutgoing.line(message)
        queue.async { [self] in
            guard !isBroken else { return }
            guard CLIStandardOutput.write(line, to: output) else {
                let action = state.withLock { state -> (@Sendable () -> Void)? in
                    state.broken = true
                    defer { state.onBroken = nil }
                    return state.onBroken
                }
                action?()
                return
            }
        }
    }

    /// Waits until every queued message is written, or `limit` passes (a client
    /// that keeps stdout open without reading never holds the exit).
    func finish(waitingAtMost limit: Duration) {
        let written = DispatchSemaphore(value: 0)
        queue.async { written.signal() }
        let milliseconds = Int(limit / .milliseconds(1))
        _ = written.wait(timeout: .now() + .milliseconds(milliseconds))
    }
}
