import Foundation

public enum CLICompletionShell: String, Sendable, CaseIterable {
    case zsh, bash, fish
}

/// Shell completion scripts generated from the command model. The zsh script is
/// checked in as `scripts/completions/_vocello` and a test keeps it equal to this
/// output.
public enum CLICompletionGenerator {
    public static func script(for shell: CLICompletionShell, tree: [CLICommandSpec] = VocelloCommandTree.commands) -> String {
        switch shell {
        case .zsh: return zsh(tree)
        case .bash: return bash(tree)
        case .fish: return fish(tree)
        }
    }

    /// A completion key per runnable command: `generate`, `models_install`.
    struct Entry {
        let key: String
        let spec: CLICommandSpec
        let names: [String]
    }

    static func entries(_ tree: [CLICommandSpec]) -> [Entry] {
        var result: [Entry] = []
        for spec in tree {
            result.append(Entry(key: spec.name, spec: spec, names: [spec.name] + spec.aliases))
            for sub in spec.subcommands {
                result.append(Entry(key: "\(spec.name)_\(sub.name)", spec: sub, names: [sub.name] + sub.aliases))
            }
        }
        return result
    }

    /// Every option the tree declares by name, first declaration first.
    static func optionsByName(_ tree: [CLICommandSpec]) -> [(String, CLIOptionSpec)] {
        var seen = Set<String>()
        var result: [(String, CLIOptionSpec)] = []
        for option in CLIGlobalOptionSpecs.all + entries(tree).flatMap(\.spec.options) where seen.insert(option.name).inserted {
            result.append((option.name, option))
        }
        return result
    }

    static func escapeSingleQuoted(_ text: String) -> String {
        text.replacingOccurrences(of: "'", with: "'\\''")
    }

    static func describe(_ name: String, _ summary: String) -> String {
        let short = summary.split(separator: ";").first.map(String.init) ?? summary
        return "'" + escapeSingleQuoted("\(name):\(short.replacingOccurrences(of: ":", with: "\\:"))") + "'"
    }

    // MARK: zsh

    static func zsh(_ tree: [CLICommandSpec]) -> String {
        let globals = CLIGlobalOptionSpecs.all
        let valueOptions = optionsByName(tree).filter { !$0.1.isFlag }.map { "--\($0.0)" }
        var lines = [
            "#compdef vocello",
            "",
            "# Generated from the vocello command model by `vocello completions zsh`; do not edit.",
            "# CLICommandModelGoldenTests keeps this file equal to the generator's output.",
            "_vocello() {",
            "  local word previous key command sub i",
            "  local -a candidates options",
            "  local -a value_options=( \(valueOptions.joined(separator: " ")) )",
            "",
            "  # Find the command and subcommand typed so far, skipping options and their values.",
            "  i=2",
            "  while (( i < CURRENT )); do",
            "    word=${words[i]}",
            "    if [[ $word == -- ]]; then break; fi",
            "    if [[ $word == -* ]]; then",
            "      if [[ $word != *=* ]] && (( ${value_options[(Ie)$word]} )); then (( i++ )); fi",
            "    elif [[ -z $command ]]; then",
            "      command=$word",
            "    elif [[ -z $sub ]]; then",
            "      sub=$word",
            "    fi",
            "    (( i++ ))",
            "  done",
            "",
            "  case $command in",
        ]
        for spec in tree {
            let names = ([spec.name] + spec.aliases).joined(separator: "|")
            lines.append("    \(names)) command=\(spec.name) ;;")
        }
        lines += [
            "    custom|design|clone)",
            "      if (( ${words[(I)--file]} || ${words[(I)--file=*]} )); then command=batch; else command=generate; fi",
            "      sub= ;;",
            "  esac",
            "",
            "  if [[ -z $command ]]; then",
            "    candidates=(",
        ]
        for spec in tree {
            for name in [spec.name] + spec.aliases {
                lines.append("      \(describe(name, spec.summary))")
            }
        }
        for mode in CLIParser.modeShortcuts {
            lines.append("      \(describe(mode, "Synthesize in \(mode) mode"))")
        }
        lines += [
            "    )",
            "    _describe -t commands 'vocello command' candidates",
            "    return",
            "  fi",
            "",
            "  key=$command",
            "  case $command in",
        ]
        for spec in tree where !spec.subcommands.isEmpty {
            lines.append("    \(spec.name))")
            lines.append("      case $sub in")
            for subSpec in spec.subcommands {
                let names = ([subSpec.name] + subSpec.aliases).joined(separator: "|")
                lines.append("        \(names)) key=\(spec.name)_\(subSpec.name) ;;")
            }
            lines.append("        '') ;;")
            lines.append("        *) return ;;")
            lines.append("      esac")
            lines.append("      if [[ -z $sub && ${words[CURRENT]} != -* ]]; then")
            lines.append("        candidates=(")
            for subSpec in spec.subcommands {
                for name in [subSpec.name] + subSpec.aliases {
                    lines.append("          \(describe(name, subSpec.summary))")
                }
            }
            lines.append("        )")
            lines.append("        _describe -t subcommands 'subcommand' candidates")
            lines.append("        return")
            lines.append("      fi")
            if let defaultName = spec.defaultSubcommand {
                lines.append("      [[ -z $sub ]] && key=\(spec.name)_\(defaultName)")
            }
            lines.append("      ;;")
        }
        lines += [
            "  esac",
            "",
            "  # The value of a split --option value pair.",
            "  previous=${words[CURRENT-1]}",
            "  case $previous in",
        ]
        for (name, option) in optionsByName(tree) where !option.isFlag {
            lines.append("    --\(name)) \(zshValue(option.value!, name: name)); return ;;")
        }
        lines += [
            "  esac",
            "",
            "  case $key in",
        ]
        for entry in entries(tree) where entry.spec.subcommands.isEmpty {
            var rows = entry.spec.options.filter { !$0.hidden }.map { describe("--\($0.name)", $0.summary) }
            rows += globals.map { describe("--\($0.name)", $0.summary) }
            lines.append("    \(entry.key))")
            lines.append("      options=(")
            for row in rows { lines.append("        \(row)") }
            lines.append("      ) ;;")
        }
        lines += [
            "    *) return ;;",
            "  esac",
            "",
            "  if [[ ${words[CURRENT]} == -* ]]; then",
            "    _describe -t options 'option' options",
            "    return",
            "  fi",
            "  case $key in",
        ]
        for entry in entries(tree) where entry.spec.subcommands.isEmpty {
            guard let operand = entry.spec.positionals.first else { continue }
            switch operand.value {
            case .choice(let values):
                lines.append("    \(entry.key)) _values '\(operand.name)' \(values.joined(separator: " ")); return ;;")
            case .file:
                lines.append("    \(entry.key)) _files; return ;;")
            default:
                // Operands such as model ids depend on the user's contract.
                lines.append("    \(entry.key)) return ;;")
            }
        }
        lines += [
            "  esac",
            "  _describe -t options 'option' options",
            "}",
            "",
            "_vocello \"$@\"",
            "",
        ]
        return lines.joined(separator: "\n")
    }

    static func zshValue(_ kind: CLIValueKind, name: String) -> String {
        switch kind {
        case .choice(let values): return "_values '\(name)' \(values.joined(separator: " "))"
        case .list(let values): return "_values -s , '\(name)' \(values.joined(separator: " "))"
        case .file: return "_files"
        case .directory: return "_files -/"
        case .text, .integer, .unsignedInteger: return ":"
        }
    }

    // MARK: bash

    static func bash(_ tree: [CLICommandSpec]) -> String {
        let valueOptions = optionsByName(tree).filter { !$0.1.isFlag }.map { "--\($0.0)" }
        let globals = CLIGlobalOptionSpecs.all.map { "--\($0.name)" }.joined(separator: " ")
        var lines = [
            "# bash completion for vocello. Generated by `vocello completions bash`; do not edit.",
            "_vocello() {",
            "  local cur prev word command sub key i",
            "  cur=${COMP_WORDS[COMP_CWORD]}",
            "  prev=${COMP_WORDS[COMP_CWORD-1]}",
            "  local value_options=\" \(valueOptions.joined(separator: " ")) \"",
            "  for (( i = 1; i < COMP_CWORD; i++ )); do",
            "    word=${COMP_WORDS[i]}",
            "    [[ $word == -- ]] && break",
            "    if [[ $word == -* ]]; then",
            "      [[ $word != *=* && $value_options == *\" $word \"* ]] && (( i++ ))",
            "    elif [[ -z $command ]]; then command=$word",
            "    elif [[ -z $sub ]]; then sub=$word",
            "    fi",
            "  done",
            "  case $command in",
        ]
        for spec in tree {
            lines.append("    \(([spec.name] + spec.aliases).joined(separator: "|"))) command=\(spec.name) ;;")
        }
        lines += [
            "    custom|design|clone) command=generate; [[ \" ${COMP_WORDS[*]} \" == *\" --file\"* ]] && command=batch; sub= ;;",
            "  esac",
            "  if [[ -z $command ]]; then",
            "    COMPREPLY=( $(compgen -W \"\((tree.flatMap { [$0.name] + $0.aliases } + CLIParser.modeShortcuts).joined(separator: " "))\" -- \"$cur\") )",
            "    return",
            "  fi",
            "  case $prev in",
        ]
        for (name, option) in optionsByName(tree) where !option.isFlag {
            switch option.value! {
            case .choice(let values), .list(let values):
                lines.append("    --\(name)) COMPREPLY=( $(compgen -W \"\(values.joined(separator: " "))\" -- \"$cur\") ); return ;;")
            case .file:
                lines.append("    --\(name)) COMPREPLY=( $(compgen -f -- \"$cur\") ); return ;;")
            case .directory:
                lines.append("    --\(name)) COMPREPLY=( $(compgen -d -- \"$cur\") ); return ;;")
            default:
                lines.append("    --\(name)) return ;;")
            }
        }
        lines += ["  esac", "  key=$command", "  case $command in"]
        for spec in tree where !spec.subcommands.isEmpty {
            let subNames = spec.subcommands.flatMap { [$0.name] + $0.aliases }.joined(separator: " ")
            lines.append("    \(spec.name))")
            lines.append("      if [[ -z $sub && $cur != -* ]]; then COMPREPLY=( $(compgen -W \"\(subNames)\" -- \"$cur\") ); return; fi")
            lines.append("      case $sub in")
            for sub in spec.subcommands {
                lines.append("        \(([sub.name] + sub.aliases).joined(separator: "|"))) key=\(spec.name)_\(sub.name) ;;")
            }
            if let defaultName = spec.defaultSubcommand {
                lines.append("        '') key=\(spec.name)_\(defaultName) ;;")
            }
            lines.append("      esac ;;")
        }
        lines += ["  esac", "  local options=\"\(globals)\"", "  case $key in"]
        for entry in entries(tree) where entry.spec.subcommands.isEmpty {
            let names = entry.spec.options.filter { !$0.hidden }.map { "--\($0.name)" }.joined(separator: " ")
            lines.append("    \(entry.key)) options=\"\(names) $options\" ;;")
        }
        lines += [
            "  esac",
            "  COMPREPLY=( $(compgen -W \"$options\" -- \"$cur\") )",
            "}",
            "complete -o default -F _vocello vocello",
            "",
        ]
        return lines.joined(separator: "\n")
    }

    // MARK: fish

    static func fish(_ tree: [CLICommandSpec]) -> String {
        func escape(_ text: String) -> String { text.replacingOccurrences(of: "'", with: "\\'") }
        var lines = [
            "# fish completion for vocello. Generated by `vocello completions fish`; do not edit.",
            "complete -c vocello -f",
        ]
        for spec in tree {
            for name in [spec.name] + spec.aliases {
                lines.append("complete -c vocello -n '__fish_use_subcommand' -a \(name) -d '\(escape(spec.summary))'")
            }
        }
        for mode in CLIParser.modeShortcuts {
            lines.append("complete -c vocello -n '__fish_use_subcommand' -a \(mode) -d 'Synthesize in \(mode) mode'")
        }
        for option in CLIGlobalOptionSpecs.all {
            lines.append(fishOption(option, condition: nil, escape: escape))
        }
        for spec in tree {
            let names = ([spec.name] + spec.aliases + (spec.name == "generate" || spec.name == "batch" ? CLIParser.modeShortcuts : []))
                .joined(separator: " ")
            let inCommand = "__fish_seen_subcommand_from \(names)"
            if spec.subcommands.isEmpty {
                for option in spec.options where !option.hidden {
                    lines.append(fishOption(option, condition: inCommand, escape: escape))
                }
                if let operand = spec.positionals.first, case .choice(let values) = operand.value {
                    lines.append("complete -c vocello -n '\(inCommand)' -a '\(values.joined(separator: " "))'")
                }
                continue
            }
            let subNames = spec.subcommands.flatMap { [$0.name] + $0.aliases }.joined(separator: " ")
            lines.append("complete -c vocello -n '\(inCommand); and not __fish_seen_subcommand_from \(subNames)' -a '\(subNames)'")
            for sub in spec.subcommands {
                let inSub = "\(inCommand); and __fish_seen_subcommand_from \(([sub.name] + sub.aliases).joined(separator: " "))"
                for option in sub.options where !option.hidden {
                    lines.append(fishOption(option, condition: inSub, escape: escape))
                }
            }
        }
        lines.append("")
        return lines.joined(separator: "\n")
    }

    static func fishOption(_ option: CLIOptionSpec, condition: String?, escape: (String) -> String) -> String {
        var line = "complete -c vocello"
        if let condition { line += " -n '\(condition)'" }
        line += " -l \(option.name)"
        switch option.value {
        case nil: break
        case .choice(let values)?, .list(let values)?: line += " -x -a '\(values.joined(separator: " "))'"
        case .file?: line += " -r -F"
        case .directory?: line += " -r -a '(__fish_complete_directories)'"
        default: line += " -x"
        }
        line += " -d '\(escape(option.summary))'"
        return line
    }
}
