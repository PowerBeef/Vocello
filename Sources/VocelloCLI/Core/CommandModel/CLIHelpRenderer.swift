import Foundation

/// Help text, rendered from the command model so it never drifts from what the
/// parser accepts.
public enum CLIHelpRenderer {
    public static func render(path: [String], tree: [CLICommandSpec] = VocelloCommandTree.commands) -> String {
        guard let spec = VocelloCommandTree.spec(at: path, in: tree) else { return topLevel(tree) }
        return command(spec, path: path)
    }

    static func topLevel(_ tree: [CLICommandSpec]) -> String {
        var lines = [
            "vocello — local Qwen3-TTS speech synthesis on MLX (the Vocello engine, headless)",
            "",
            "Usage:",
            "  vocello <command> [<subcommand>] [options]",
            "  vocello custom|design|clone [options]     (generate in that mode; batch with --file)",
            "",
            "Commands:",
        ]
        let shown = tree.filter { !$0.internalTool }
        let width = (shown.map(\.name.count).max() ?? 0) + 2
        for spec in shown {
            lines.append("  " + spec.name.padding(toLength: width, withPad: " ", startingAt: 0) + spec.summary)
        }
        lines.append("")
        lines.append("Internal:")
        for spec in tree where spec.internalTool {
            lines.append("  " + spec.name.padding(toLength: width, withPad: " ", startingAt: 0) + spec.summary)
        }
        lines += ["", "Global options:"] + optionRows(CLIGlobalOptionSpecs.all)
        lines += [
            "",
            "Voice cloning (clone takes, `voices enroll`, clone bench cells) requires --confirm-consent:",
            "only clone voices you own or have permission to use.",
            "",
            "Machine output: --json writes one envelope on stdout ({schemaVersion, ok, command, requestID,",
            "result, error, warnings, meta}); --ndjson writes events and ends with a `result` record.",
            "`vocello capabilities --json` describes every command, option, error code and limit.",
            "",
            "Exit status: 0 ok · 1 failure · 2 usage or invalid input · 66 not found · 69 model not",
            "installed · 73 output unavailable · 74 storage · 75 busy or memory pressure (retry later) ·",
            "77 consent or permission · 78 configuration · 130 / 143 interrupted (SIGINT / SIGTERM).",
        ]
        return lines.joined(separator: "\n")
    }

    static func command(_ spec: CLICommandSpec, path: [String]) -> String {
        let name = (["vocello"] + path).joined(separator: " ")
        var lines = ["\(name) — \(spec.summary)"]
        if !spec.aliases.isEmpty {
            lines.append("Aliases: \(spec.aliases.joined(separator: ", "))")
        }
        lines += ["", "Usage:"]
        if spec.usage.isEmpty {
            var synopsis = name
            if !spec.subcommands.isEmpty { synopsis += " <subcommand>" }
            for operand in spec.positionals {
                synopsis += operand.required ? " <\(operand.name)>" : " [<\(operand.name)>]"
            }
            if !spec.options.isEmpty || spec.subcommands.isEmpty { synopsis += " [options]" }
            lines.append("  " + synopsis)
        } else {
            lines += spec.usage.map { "  " + $0 }
        }
        if let discussion = spec.discussion {
            lines += ["", discussion]
        }
        if !spec.subcommands.isEmpty {
            lines += ["", "Subcommands:"]
            let width = (spec.subcommands.map(\.name.count).max() ?? 0) + 2
            for sub in spec.subcommands {
                let isDefault = sub.name == spec.defaultSubcommand ? " (default)" : ""
                lines.append("  " + sub.name.padding(toLength: width, withPad: " ", startingAt: 0) + sub.summary + isDefault)
            }
        }
        if !spec.positionals.isEmpty {
            lines += ["", "Arguments:"]
            let width = (spec.positionals.map { $0.name.count + 2 }.max() ?? 0) + 2
            for operand in spec.positionals {
                lines.append("  " + "<\(operand.name)>".padding(toLength: width, withPad: " ", startingAt: 0) + operand.summary)
            }
        }
        let options = spec.options.filter { !$0.hidden }
        if !options.isEmpty {
            lines += ["", "Options:"] + optionRows(options)
        }
        lines += ["", "Global options: --output-format text|json|ndjson (--json, --ndjson), --quiet, --verbose,",
                  "--no-input, --data-dir <dir>, --manifest <path>, --help"]
        return lines.joined(separator: "\n")
    }

    static func optionRows(_ options: [CLIOptionSpec]) -> [String] {
        let labels = options.map { option -> String in
            guard let placeholder = option.placeholder else { return "--\(option.name)" }
            return option.valueOptional ? "--\(option.name) [<\(placeholder)>]" : "--\(option.name) <\(placeholder)>"
        }
        let width = min((labels.map(\.count).max() ?? 0) + 2, 30)
        return zip(labels, options).map { label, option in
            let padded = label.count >= width ? label + "  " : label.padding(toLength: width, withPad: " ", startingAt: 0)
            return "  " + padded + option.summary
        }
    }
}
