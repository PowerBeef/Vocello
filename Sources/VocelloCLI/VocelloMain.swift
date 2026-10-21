import Foundation
import VocelloCLICore

/// `vocello` — headless Vocello TTS over the in-process MLX engine.
/// User-facing generation without the UI + the deterministic benchmark/test driver.
@main
@MainActor
enum VocelloMain {
    static func main() async {
        // A closed stdout must fail its writes (EPIPE), never end the process
        // before the command's owned cleanup runs.
        signal(SIGPIPE, SIG_IGN)
        let code = await CLIProcessSupervisor.run { await execute() }
        if code != 0 { exit(code) }
    }

    private static func execute() async -> Int32 {
        let argv = Array(CommandLine.arguments.dropFirst())
        let invocation: CLIInvocation
        do {
            invocation = try CLIParser.parse(argv)
        } catch {
            // Reported in the format the caller asked for, even unparsed.
            // No command resolved, so the envelope names none.
            CLIPresenter.begin(
                format: CLIParser.requestedFormat(argv), command: "",
                onBrokenOutput: CLIProcessSupervisor.outputBroken
            )
            let failure = CLIFailure.classify(error)
            CLIPresenter.fail(failure)
            return failure.exitCode
        }
        CLIOutput.configure(invocation)
        CLIPresenter.begin(
            format: invocation.format, command: invocation.commandName,
            onBrokenOutput: CLIProcessSupervisor.outputBroken
        )
        do {
            try await dispatch(invocation)
            CLIPresenter.finishSuccessIfUnreported()
            return CLIPresenter.resultWasUnencodable ? VocelloErrorCode.internalError.exitCode : 0
        } catch {
            // A forced exit's reap of a `--play` child also unwinds the
            // command; the forced path reports that exit, not this one.
            if error is CancellationError, CLIChildProcesses.shared.forcedExitBegan { return 130 }
            // A signalled run exits 128 + the signal whatever else failed, and says so.
            let failure = CLIFailure.classify(error, signal: CLIProcessSupervisor.receivedSignal)
                .signalled(by: CLIProcessSupervisor.receivedSignal)
            CLIPresenter.fail(failure)
            return failure.exitCode
        }
    }

    private static func dispatch(_ invocation: CLIInvocation) async throws {
        let args = invocation.args
        if invocation.action == .help {
            if invocation.path == ["bench"], !CLIPresenter.isMachine {
                BenchCommand.printHelp()
                return
            }
            let text = CLIHelpRenderer.render(path: invocation.path)
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(HelpResult(path: invocation.path.joined(separator: "."), text: text))
            } else {
                print(text)
            }
            return
        }
        let path = invocation.path
        let action = path.count > 1 ? path[1] : ""
        switch path.first ?? "" {
        case "generate":
            try await GenerateCommand.run(args)
        case "batch":
            try await BatchCommand.run(args)
        case "voices":
            try await VoicesCommand.run(action: action, args)
        case "speakers":
            try await SpeakersCommand.run(args)
        case "modes":
            try await ModesCommand.run(args)
        case "deliveries":
            try await DeliveriesCommand.run(args)
        case "languages":
            try await LanguagesCommand.run(args)
        case "models":
            try await ModelsCommand.run(action: action, args)
        case "doctor":
            try await DoctorCommand.run(args)
        case "bench":
            try await BenchCommand.run(args)
        case "capabilities":
            try CapabilitiesCommand.run()
        case "completions":
            try CompletionsCommand.run(args)
        case "version":
            if CLIPresenter.isMachine {
                CLIPresenter.succeed(VersionResult(version: vocelloCLIVersion, build: vocelloCLIBuild))
            } else {
                print("vocello \(vocelloCLIVersion)")
            }
        default:
            throw CLIError(.internalError, "no handler for \(invocation.commandName)")
        }
    }

    struct HelpResult: Encodable, Sendable {
        let path: String
        let text: String
    }

    struct VersionResult: Encodable, Sendable {
        let version: String
        let build: String
    }
}

/// `vocello capabilities`: the static description agents read first.
enum CapabilitiesCommand {
    static func run() throws {
        let document = CLICapabilitiesDocument()
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(document)
            return
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted]
        print(String(decoding: try encoder.encode(document), as: UTF8.self))
    }
}

/// `vocello completions zsh|bash|fish`: the completion script for the shell.
enum CompletionsCommand {
    struct Result: Encodable, Sendable {
        let shell: String
        let script: String
    }

    static func run(_ args: Args) throws {
        guard let name = args.positionals.first, let shell = CLICompletionShell(rawValue: name) else {
            throw CLIError(
                .usageError,
                "unknown shell '\(args.positionals.first ?? "")'",
                hint: "use \(CLICompletionShell.allCases.map(\.rawValue).joined(separator: " | "))"
            )
        }
        let script = CLICompletionGenerator.script(for: shell)
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Result(shell: shell.rawValue, script: script))
        } else {
            print(script, terminator: "")
        }
    }
}
