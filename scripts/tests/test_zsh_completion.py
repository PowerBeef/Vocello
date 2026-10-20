#!/usr/bin/env python3
"""The checked-in zsh completion (scripts/completions/_vocello) offers what the CLI documents.

The real `_vocello` function runs in zsh with the completion system's helpers stubbed to print
the candidates they are handed. Its flags are compared with each command's help text in
Sources/VocelloCLI: a documented flag the completion lacks fails, and so does a completed flag
that the help never mentions.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPLETION = ROOT / "scripts" / "completions" / "_vocello"
CLI_SOURCES = ROOT / "Sources" / "VocelloCLI"
ZSH = shutil.which("zsh") or ""
FLAG = re.compile(r"--[a-z][a-z0-9-]*")

# Stand-ins for zsh's completion helpers; the words to complete arrive as arguments, the
# cursor on the last one.
DRIVER = r"""
_describe() { local name=${@[-1]}; print -rl -- ${${(P)name}%%:*} }
_values() { [[ $1 == -s ]] && shift 2; shift; print -rl -- "$@" }
_files() { print -r -- '<files>' }
words=("$@"); CURRENT=$#words; set --
source "$VOCELLO_COMPLETION"
"""


def complete(*words: str) -> set[str]:
    """What `vocello <words>` offers with the cursor on the last word."""
    result = subprocess.run(
        [ZSH, "-f", "-c", DRIVER, "zsh", "vocello", *words],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "VOCELLO_COMPLETION": str(COMPLETION)},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return set(result.stdout.split())


def help_text(file_name: str, function: str = "printHelp") -> str:
    source = (CLI_SOURCES / file_name).read_text(encoding="utf-8")
    start = source.index('"""', source.index(f"static func {function}()")) + 3
    return source[start : source.index('"""', start)]


def option_rows(text: str) -> set[str]:
    """Flags that open an Options row, such as `--quiet|--verbose  …` or `--label <id>  …`."""
    flags: set[str] = set()
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or not tokens[0].startswith("--"):
            continue
        for token in tokens:
            if token.startswith("--"):
                flags.update(FLAG.findall(token))
            elif not token.startswith(("<", "[")):
                break
    return flags


def usage_lines(text: str, *command: str) -> list[list[str]]:
    """The words of each line in the Usage block that runs `vocello <command>`."""
    block = text.split("Usage:", 1)[1].strip("\n").split("\n\n", 1)[0]
    prefix = ["vocello", *command]
    return [line.split() for line in block.splitlines() if line.split()[: len(prefix)] == prefix]


def dispatch_table() -> list[list[str]]:
    """The words of each `case` in CLICommandRoute, which picks the command `vocello` runs."""
    source = (CLI_SOURCES / "Support.swift").read_text(encoding="utf-8")
    start = source.index("public init(_ argv: [String])", source.index("enum CLICommandRoute"))
    table = source[start : source.index("default:", start)]
    return [
        re.findall(r'"([^"]+)"', line)
        for line in table.splitlines()
        if line.strip().startswith("case ")
    ]


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        usage = help_text("VocelloMain.swift", "printUsage")
        cls.global_flags = {
            flag
            for line in usage.splitlines()
            if line.strip().startswith("Global:")
            for flag in FLAG.findall(line)
        }
        if not cls.global_flags:
            raise AssertionError("the usage text lost its Global: line")

    def assert_offers(self, words: tuple[str, ...], text: str, documented: set[str]) -> set[str]:
        offered = {candidate for candidate in complete(*words, "--") if candidate.startswith("--")}
        line = " ".join(("vocello", *words, "--"))
        self.assertFalse(documented - offered, f"{line}<TAB> lacks documented flags")
        unknown = offered - set(FLAG.findall(text)) - self.global_flags - {"--help"}
        self.assertFalse(unknown, f"{line}<TAB> offers flags its help never mentions")
        return offered

    def test_commands_are_the_dispatch_table(self) -> None:
        expected = {word for case in dispatch_table() for word in case}
        self.assertEqual(complete(""), expected)

    def test_aliases_complete_like_their_command(self) -> None:
        for command, *aliases in dispatch_table():
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertEqual(complete(alias, "--"), complete(command, "--"))

    def test_each_command_offers_its_documented_flags(self) -> None:
        for command, file_name in (
            ("generate", "GenerateCommand.swift"),
            ("batch", "BatchCommand.swift"),
            ("bench", "BenchCommand.swift"),
            ("modes", "ModesCommand.swift"),
            ("deliveries", "DeliveriesCommand.swift"),
        ):
            with self.subTest(command=command):
                text = help_text(file_name)
                self.assert_offers((command,), text, option_rows(text))

    def test_mode_shortcuts_offer_generate_flags_or_batch_flags_with_a_file(self) -> None:
        generate, batch = help_text("GenerateCommand.swift"), help_text("BatchCommand.swift")
        modes = next(case for case in dispatch_table() if "clone" in case)
        for mode in modes:
            with self.subTest(mode=mode):
                self.assert_offers((mode,), generate + batch, option_rows(generate))
                self.assert_offers((mode, "--file", "lines.txt"), batch, option_rows(batch))
        self.assertEqual(complete("generate", "--mode", ""), set(modes))

    def test_action_commands_offer_each_usage_line(self) -> None:
        for command, file_name in (
            ("voices", "VoicesCommand.swift"),
            ("models", "ModelsCommand.swift"),
            ("speakers", "SpeakersCommand.swift"),
        ):
            with self.subTest(command=command):
                text = help_text(file_name)
                actions = {words[2] for words in usage_lines(text, command)}
                self.assertTrue(actions)
                self.assertLessEqual(actions, complete(command, ""))
                offered: set[str] = set()
                for action in actions:
                    documented = {
                        flag
                        for words in usage_lines(text, command, action)
                        for flag in FLAG.findall(" ".join(words))
                    }
                    offered |= self.assert_offers((command, action), text, documented)
                self.assertLessEqual(option_rows(text), offered)


if __name__ == "__main__":
    unittest.main()
