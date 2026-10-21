import Foundation

/// The `vocello` command tree: the one declaration the parser, help, shell
/// completions, `capabilities` and `config/cli-contract/v1/commands.json` derive from.
public enum VocelloCommandTree {
    static let modes = ["custom", "design", "clone"]
    static let variants = ["speed", "quality"]
    static let variations = ["expressive", "balanced", "consistent"]

    static let consent = CLIOptionSpec.flag(
        "confirm-consent",
        "confirms you own or have permission to clone this voice (required to clone or save one; ignored otherwise)"
    )

    /// The voice and delivery options `generate` and `batch` share.
    static let voiceOptions: [CLIOptionSpec] = [
        .value("mode", .choice(modes), "mode", "custom (default) | design | clone"),
        .value("variant", .choice(variants), "variant", "speed (default) | quality"),
        .value("speaker", .text, "id", "(custom) Built-in Voice speaker id; default the contract's (see `vocello speakers list`)"),
        .value("voice-brief", .text, "text", "(design) the voice description"),
        .value("voice", .text, "name|id", "(clone) a saved voice"),
        .value("reference", .file, "wav", "(clone) a reference clip instead of a saved voice"),
        .value("transcript", .text, "text", "(clone) the reference clip's words; with --voice, replaces the saved transcript"),
        consent,
        .value("delivery", .text, "text", "delivery instruction (custom and design; refused in clone)"),
        .value("delivery-cell", .text, "preset.intensity", "(custom) a preset cell such as calm.normal (see `vocello deliveries`)"),
        .flag("app-delivery", "with no delivery given, send the apps' default (Neutral) delivery, as a new Studio draft does"),
        .value("seed", .unsignedInteger, "n", "deterministic sampling seed: the same request and seed reproduce the take"),
        .value("variation", .choice(variations), "variation", "expressive (default) | balanced | consistent"),
    ]

    static let generate = CLICommandSpec(
        name: "generate",
        aliases: ["gen"],
        summary: "Synthesize one clip",
        usage: [
            "vocello generate --mode custom|design|clone (--text \"…\" | --text-file <path> | --text -) [options]",
            "vocello custom|design|clone [options]",
        ],
        discussion: """
        Prints the WAV path (text) or the take's result (--json). Without --mode at a terminal, \
        a picker asks for one; elsewhere the mode is custom. Exits 75 when the engine stopped the \
        take under memory pressure, 130 on Ctrl-C.
        """,
        options: [
            .value("text", .text, "text", "the script (\"-\" reads stdin)"),
            .value("text-file", .file, "path", "read the script from a file (\"-\" reads stdin)"),
        ] + voiceOptions + [
            .value("language", .text, "language",
                   "auto, a Qwen3 language name or a code such as en, fr or ja-JP; omitted is Auto"),
            .value("out", .file, "wav", "write the take to this .wav file (replaced only by a successful take)"),
            .flag("stream", "streaming synthesis at the app's cadence (the default)"),
            .flag("no-stream", "accumulate the whole take before decoding"),
            .flag("play", "play the take when done"),
        ]
    )

    static let batch = CLICommandSpec(
        name: "batch",
        summary: "Synthesize many clips with one model load",
        usage: ["vocello batch --file <path|-> --mode custom|design|clone [options]"],
        discussion: """
        One non-empty line per clip; every clip shares the voice, mode and variant. A partial \
        batch keeps its finished outputs, reports every planned row and exits nonzero.
        """,
        options: [
            .value("file", .file, "path", "input lines, one clip per line (\"-\" reads stdin)"),
        ] + voiceOptions + [
            .value("out-dir", .directory, "dir", "output folder (default <data>/outputs/cli/batch)"),
            .flag("long-form", "each line is one long-form project: planned into segments and joined"),
            .flag("capture-codec-trace", "internal diagnostics: keep each take's codec trace", hidden: true),
            .flag("play", "play each result when done"),
        ],
        refusedOptions: [
            "language": "--language is not supported by batch; use generate or omit it. Batch uses per-text Auto language and non-streaming output.",
            "stream": "--stream is not supported by batch; use generate or omit it. Batch uses per-text Auto language and non-streaming output.",
            "out": "--out is not supported by batch; use generate or omit it. Batch uses per-text Auto language and non-streaming output.",
        ]
    )

    static let voices = CLICommandSpec(
        name: "voices",
        aliases: ["voice"],
        summary: "Manage saved clone voices",
        subcommands: [
            CLICommandSpec(name: "list", aliases: ["ls"], summary: "List saved voices", options: [consent]),
            CLICommandSpec(
                name: "enroll", aliases: ["add"], summary: "Save a clone voice from a reference clip",
                usage: ["vocello voices enroll --name <name> --audio <wav> [--transcript \"…\"] --confirm-consent"],
                options: [
                    .value("name", .text, "name", "the voice's name"),
                    .value("audio", .file, "wav", "the reference clip"),
                    .value("transcript", .text, "text", "the clip's words"),
                    consent,
                ]
            ),
            CLICommandSpec(
                name: "delete", aliases: ["rm"], summary: "Delete a saved voice",
                options: [.value("id", .text, "id", "the saved voice id (see `vocello voices list`)"), consent]
            ),
        ],
        defaultSubcommand: "list"
    )

    static let speakers = CLICommandSpec(
        name: "speakers",
        aliases: ["speaker"],
        summary: "List Built-in Voice speakers",
        subcommands: [CLICommandSpec(name: "list", aliases: ["ls"], summary: "List Built-in Voice speakers")],
        defaultSubcommand: "list"
    )

    static let modesCommand = CLICommandSpec(
        name: "modes",
        summary: "List the generation modes",
        subcommands: [CLICommandSpec(name: "list", aliases: ["ls"], summary: "List the generation modes and what each needs")],
        defaultSubcommand: "list"
    )

    static let languages = CLICommandSpec(
        name: "languages",
        aliases: ["language"],
        summary: "List the generation languages and their codes",
        subcommands: [CLICommandSpec(name: "list", aliases: ["ls"], summary: "List the languages --language accepts")],
        defaultSubcommand: "list"
    )

    static let deliveries = CLICommandSpec(
        name: "deliveries",
        aliases: ["delivery"],
        summary: "List delivery presets and their instructions",
        subcommands: [
            CLICommandSpec(
                name: "list", aliases: ["ls"], summary: "List delivery preset cells and the instruction each sends",
                options: [.flag("shipped-only", "one row per product preset, Neutral included, at its shipped tier")]
            ),
        ],
        defaultSubcommand: "list"
    )

    static let models = CLICommandSpec(
        name: "models",
        aliases: ["model"],
        summary: "Inventory and install models",
        subcommands: [
            CLICommandSpec(
                name: "list", aliases: ["ls"], summary: "List the contract's models and their install state",
                positionals: [CLIPositionalSpec("id", "show only this model")]
            ),
            CLICommandSpec(
                name: "status", summary: "List models with missing or stale files",
                positionals: [CLIPositionalSpec("id", "show only this model")]
            ),
            CLICommandSpec(
                name: "verify", summary: "Check every installed file's size and SHA-256 against the catalog",
                discussion: "Reads every byte of each installed model (several GB); exits 1 (integrity_failed) when a file differs.",
                positionals: [CLIPositionalSpec("id", "verify only this model")]
            ),
            CLICommandSpec(
                name: "install", summary: "Download and verify a model into the shared store",
                positionals: [CLIPositionalSpec("id", "the model id to install (see `vocello models list`)", required: true)]
            ),
        ],
        defaultSubcommand: "list"
    )

    static let bench = CLICommandSpec(
        name: "bench",
        aliases: ["benchmark"],
        summary: "Drive the performance and quality matrix (internal)",
        usage: ["vocello bench [--modes custom,design,clone] [--variants speed,quality] [--lengths short,medium,long] [--warm 3] [options]"],
        options: [
            .value("modes", .list(modes), "list", "strict comma list of modes (default all)"),
            .value("variants", .list(variants), "list", "strict comma list of variants (default both)"),
            .value("lengths", .list(["short", "medium", "long"]), "list", "strict comma list of lengths (default all)"),
            .value("warm", .integer, "n", "warm repetitions per cell and length (default 3)"),
            .flag("no-cold", "with --delivery, skip the Custom/Design cold take"),
            .value("voice", .text, "name", "(clone) saved voice name"),
            consent,
            .value("speaker", .text, "id", "(custom) exact Built-in Voice speaker id"),
            .value("voice-brief", .text, "text", "(design) voice brief"),
            .value("delivery", .text, "list", "add instruct-bearing cells; alone runs the default set", optional: true),
            .value("prosody-profile", .file, "path", "a calibrated prosody profile for the delivery analysis"),
            .flag("continue-delivery-failures", "with --delivery and --no-summary, keep typed failures and continue"),
            .value("label", .text, "id", "opaque 1-96 character run label"),
            .value("force-class", .choice(["8gb", "16gb", "high", "iphone"]), "tier", "run a constrained memory tier"),
            .value("telemetry", .choice(["off", "lightweight", "verbose"]), "level", "telemetry level (default verbose)"),
            .value("memory-qualification", .choice(["retained-memory-v1"]), "protocol", "require the retained-memory protocol"),
            .value("seed", .unsignedInteger, "n", "deterministic sampling seed applied to every take"),
            .flag("no-stream", "accumulate each result before decoding"),
            .flag("ttfc", "add an engine first-chunk-latency probe per cell"),
            .flag("keep", "append to existing diagnostics (default: clear first)"),
            .flag("force", "allow clearing even the real (non-debug) app data folder"),
            .flag("no-summary", "skip the aggregator and registry"),
            .value("run-id", .text, "id", "the run identity (default generated)", hidden: true),
            .value("codec-replay", .file, "take.json", "internal diagnostics: replay collected codes"),
            .value("take-sha256", .text, "digest", "the original take digest (--codec-replay)"),
            .value("codec-trace", .file, "trace.bin", "the collected binary trace (--codec-replay)"),
            .value("output-dir", .directory, "dir", "new untracked diagnostic output folder"),
            .value("script-file", .file, "path", "the original model-facing script (--codec-replay)"),
            .value("reference-wav", .file, "wav", "the canonical reference clip (--codec-replay)"),
            .value("codec-roundtrip", .file, "job.json", "internal diagnostics: resynthesize reference clips"),
            .value("codec-loop", .file, "job.json", "internal diagnostics: decode repeated codec spans"),
        ],
        internalTool: true,
        machineContract: false
    )

    static let help = CLICommandSpec(
        name: "help",
        summary: "Show help for a command",
        usage: ["vocello help [<command> [<subcommand>]]"],
        positionals: [CLIPositionalSpec("command", "the command to describe")]
    )

    static let version = CLICommandSpec(name: "version", summary: "Print the version")

    static let doctor = CLICommandSpec(
        name: "doctor",
        summary: "Check the data folder, contract, catalog, models, memory and disk (no engine boot)"
    )

    static let capabilities = CLICommandSpec(
        name: "capabilities",
        summary: "Describe commands, options, codes and limits for agents",
        usage: ["vocello capabilities --json"]
    )

    static let completions = CLICommandSpec(
        name: "completions",
        summary: "Print a shell completion script",
        usage: ["vocello completions zsh|bash|fish"],
        positionals: [CLIPositionalSpec("shell", "zsh, bash or fish", required: true, value: .choice(CLICompletionShell.allCases.map(\.rawValue)))]
    )

    public static let commands: [CLICommandSpec] = [
        generate, batch, voices, speakers, modesCommand, languages, deliveries, models, doctor, capabilities, completions,
        bench, help, version,
    ]

    /// The spec at `path`, such as `["models", "install"]`.
    public static func spec(at path: [String], in tree: [CLICommandSpec] = commands) -> CLICommandSpec? {
        guard let first = path.first, let top = tree.first(where: { $0.name == first }) else { return nil }
        return path.dropFirst().reduce(Optional(top)) { spec, name in spec?.subcommand(named: name) }
    }
}
