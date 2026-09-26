import Foundation

/// `vocello` — headless Vocello TTS over the in-process MLX engine.
/// User-facing generation without the UI + the deterministic benchmark/test driver.
@main
@MainActor
enum VocelloMain {
    static func main() async {
        let code = await CLIProcessSupervisor.run { await execute() }
        if code != 0 { exit(code) }
    }

    private static func execute() async -> Int32 {
        let route = CLICommandRoute(Array(CommandLine.arguments.dropFirst()))

        do {
            switch route {
            case .generate(let argv):
                try await GenerateCommand.run(argv)
            case .batch(let argv):
                try await BatchCommand.run(argv)
            case .modes(let argv):
                try await ModesCommand.run(argv)
            case .deliveries(let argv):
                try await DeliveriesCommand.run(argv)
            case .voices(let argv):
                try await VoicesCommand.run(argv)
            case .speakers(let argv):
                try await SpeakersCommand.run(argv)
            case .models(let argv):
                try await ModelsCommand.run(argv)
            case .bench(let argv):
                try await BenchCommand.run(argv)
            case .help:
                printUsage()
            case .version:
                print("vocello \(vocelloCLIVersion)")
            case .unknown(let command):
                FileHandle.standardError.write(Data("unknown command: \(command)\n\n".utf8))
                printUsage()
                exit(2)
            case .missingCommand:
                printUsage()
                exit(2)
            }
        } catch is CancellationError {
            // A forced exit's reap of a `--play` child also unwinds the
            // command; the forced path reports that exit, not this one.
            if !CLIChildProcesses.shared.forcedExitBegan {
                FileHandle.standardError.write(Data("Cancelled; command cleanup completed.\n".utf8))
            }
            return 130
        } catch {
            // A typed error prints its own path-free description (SEC-11); the
            // raw value would print every associated value, staged paths and an
            // underlying error's userInfo included.
            let message = (error as? LocalizedError)?.errorDescription ?? "\(error)"
            FileHandle.standardError.write(Data("error: \(message)\n".utf8))
            return 1
        }
        return 0
    }

    static func printUsage() {
        print("""
        vocello — headless Vocello TTS (Qwen3-TTS via MLX)

        Commands:
          generate            synthesize a clip            (vocello generate --help)
          custom|design|clone synthesize in that mode (shortcut for generate --mode)
          batch               synthesize many clips, one model load (vocello batch --help)
          voices              manage saved clone voices    (vocello voices help)
          speakers            list Built-in Voice speakers (vocello speakers help)
          modes               list the generation modes    (vocello modes --help)
          deliveries          list delivery presets + instruction text (vocello deliveries --help)
          models              inventory installed models   (vocello models help)
          bench               drive the perf/quality matrix (vocello bench --help)
          help                show this message
          version             print version

        Global: --json (machine-readable stdout), --quiet / --verbose (stderr notes).
        Voice cloning (clone generation, `voices enroll`, clone bench cells) requires
        --confirm-consent: only clone voices you own or have permission to use.
        """)
    }
}
