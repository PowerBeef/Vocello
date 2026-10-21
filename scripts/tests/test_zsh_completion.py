#!/usr/bin/env python3
"""The checked-in zsh completion (scripts/completions/_vocello) offers what the command model declares.

The real `_vocello` function runs in zsh with the completion system's helpers stubbed to print
the candidates they are handed. What it offers is compared with the command model the Swift
parser runs on, rendered in config/cli-contract/v1/commands.json (CLICommandModelGoldenTests
keeps both files equal to the Swift tree): every command, alias, subcommand, visible option and
choice value, and nothing else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPLETION = ROOT / "scripts" / "completions" / "_vocello"
MODEL = ROOT / "config" / "cli-contract" / "v1" / "commands.json"
ZSH = shutil.which("zsh") or ""

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


def load_model() -> dict[str, Any]:
    return json.loads(MODEL.read_text(encoding="utf-8"))


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshCompletionTests(unittest.TestCase):
    model: dict[str, Any]
    commands: dict[str, dict[str, Any]]
    globals: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_model()
        cls.commands = {command["path"]: command for command in cls.model["commands"]}
        cls.globals = {f"--{option['name']}" for option in cls.model["globalOptions"]}

    def top_level(self) -> list[dict[str, Any]]:
        return [command for path, command in self.commands.items() if "." not in path]

    def options(self, path: str) -> set[str]:
        return {f"--{option['name']}" for option in self.commands[path]["options"]} | self.globals

    def test_commands_aliases_and_mode_shortcuts_are_offered_first(self) -> None:
        expected = {name for command in self.top_level() for name in [command["name"], *command["aliases"]]}
        expected |= set(self.model["modeShortcuts"])
        self.assertEqual(complete(""), expected)

    def test_each_runnable_command_offers_exactly_its_options(self) -> None:
        for command in self.top_level():
            if command["subcommands"]:
                continue
            for name in [command["name"], *command["aliases"]]:
                with self.subTest(command=name):
                    self.assertEqual(complete(name, "--"), self.options(command["path"]))

    def test_subcommands_and_their_aliases_resolve(self) -> None:
        for command in self.top_level():
            if not command["subcommands"]:
                continue
            path = command["path"]
            subcommands = [self.commands[f"{path}.{name}"] for name in command["subcommands"]]
            expected = {name for sub in subcommands for name in [sub["name"], *sub["aliases"]]}
            self.assertEqual(complete(command["name"], ""), expected, path)
            for sub in subcommands:
                for name in [sub["name"], *sub["aliases"]]:
                    with self.subTest(command=path, subcommand=name):
                        self.assertEqual(complete(command["name"], name, "--"), self.options(sub["path"]))
            default = command["defaultSubcommand"]
            if default:
                self.assertEqual(
                    complete(command["name"], "--"), self.options(f"{path}.{default}"),
                    f"{path} options before a subcommand are the default's",
                )

    def test_mode_shortcuts_offer_generate_or_batch_options(self) -> None:
        for mode in self.model["modeShortcuts"]:
            with self.subTest(mode=mode):
                self.assertEqual(complete(mode, "--"), self.options("generate"))
                self.assertEqual(complete(mode, "--file", "lines.txt", "--"), self.options("batch"))

    def test_choice_values_complete_after_their_option(self) -> None:
        for path, command in self.commands.items():
            for option in command["options"]:
                if not option.get("choices"):
                    continue
                verb = path.split(".")
                with self.subTest(path=path, option=option["name"]):
                    self.assertEqual(complete(*verb, f"--{option['name']}", ""), set(option["choices"]))
        self.assertEqual(complete("completions", ""), {"zsh", "bash", "fish"})
        self.assertEqual(complete("generate", "--text-file", ""), {"<files>"})

    def test_hidden_diagnostics_options_are_never_offered(self) -> None:
        self.assertNotIn("--capture-codec-trace", complete("batch", "--"))
        self.assertNotIn("--run-id", complete("bench", "--"))


if __name__ == "__main__":
    unittest.main()
