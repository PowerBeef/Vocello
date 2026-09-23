"""Parse the git invocations in a Bash command for the repository hooks.

The policy guard and the commit lint both judge git commands. A regex over the
raw text misses real spellings (`git -C "a b" commit`, `git -c x=y push -f`,
`bash -lc 'git push origin topic'`, `timeout 60 git push`, `git commit; git -C
other commit`), so this module tokenizes the command once and yields every git
invocation with the directory it runs in, its global options, subcommand and
arguments. A token whose basename is `git` starts an invocation wherever it
appears (after `xargs`, `sudo`, `if ... then`, `{`), command substitutions and
shell heredocs are parsed recursively, and long options match by unambiguous
prefix the way git accepts them.

It never executes anything. It is a guardrail for cooperative agents, not a
sandbox: `python3 -c "os.system(...)"` and similar indirection stay out of
reach. Anything it cannot resolve (a `cd "$VAR"`, `pushd`, `GIT_DIR=...`, an
earlier branch switch) is reported as unresolved so the callers fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shlex

HEREDOC = re.compile(
    r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?([^\n]*)\n(.*?)\n[ \t]*\1[ \t]*(?=\n|$)", re.S
)
SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "|&", "\n", "{", "}", "!", "then", "do", "else", "elif"}
TRANSPARENT_PREFIXES = {"command", "exec", "nohup", "time", "builtin", "noglob", "sudo", "nice",
                        "xargs", "caffeinate", "watch", "timeout", "coproc", "if", "while", "until", "--"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
GIT_ENV = re.compile(r"^(GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_NAMESPACE|GIT_COMMON_DIR)=")
GIT_CONFIG_ENV = re.compile(r"^(GIT_CONFIG[A-Z0-9_]*|GIT_EXEC_PATH)=")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                        "--config-env", "--exec-path", "--list-cmds", "--attr-source"}
UNSAFE_GLOBALS = {"--git-dir", "--work-tree", "--namespace", "--super-prefix"}
# Config keys that change which command runs, what a push publishes or which hooks run.
UNSAFE_CONFIG = re.compile(
    r"^(alias\.|remote\..*\.(push|mirror|url|pushurl)|push\.|branch\..*\.merge|core\.hookspath|url\.|include)",
    re.I,
)
REDIRECT = re.compile(r"^[0-9]*[<>]")
# Commands that can leave a later commit or push on another branch or a detached HEAD.
BRANCH_CHANGERS = {"checkout", "switch", "rebase", "bisect", "symbolic-ref"}


@dataclass
class GitInvocation:
    directory: Path | None          # None: cannot be resolved (cd "$VAR", pushd, ...)
    subcommand: str
    args: list[str]
    configs: list[str] = field(default_factory=list)
    unsafe: str = ""                # why the target cannot be trusted, if any
    config_env: str = ""            # config injected through the environment or --config-env


def strip_heredocs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace heredoc bodies with a marker, keeping the rest of each opening line.

    Returns the stripped text and (opening-line prefix, body) pairs so a caller can
    parse bodies fed to a shell (`sh <<EOF`).
    """
    bodies: list[tuple[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        bodies.append((match.string[line_start:match.start()], match.group(3)))
        return "<<HEREDOC" + match.group(2)

    return HEREDOC.sub(replace, text), bodies


def _substitutions(text: str) -> list[str]:
    """Bodies of `$(...)` (balanced) and backtick substitutions in raw shell text."""
    bodies = re.findall(r"`([^`]*)`", text)
    index = 0
    while True:
        start = text.find("$(", index)
        if start < 0:
            break
        depth, cursor = 1, start + 2
        while cursor < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[cursor], 0)
            cursor += 1
        bodies.append(text[start + 2:cursor - 1])
        index = start + 2
    return bodies


def _resolve(base: Path | None, value: str) -> Path | None:
    if base is None or not value or any(c in value for c in "$`"):
        return None
    if value.startswith("~") and value != "~" and not value.startswith("~/"):
        return None
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _tokens(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return line.split()


def _without_redirections(tokens: list[str]) -> list[str]:
    """Drop `>file`, `2>&1`, `<in` and their targets; shlex splits `2>&1` into 2, >&, 1."""
    result: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if set(token) <= set("<>&") and ("<" in token or ">" in token):
            if result and result[-1].isdigit():
                result.pop()                         # the fd number before the operator
            index += 2                               # the operator and its target
            continue
        if REDIRECT.match(token) and token not in {"<", ">"}:
            index += 1
            continue
        result.append(token)
        index += 1
    return result


def _is_git(token: str) -> bool:
    return token.rsplit("/", 1)[-1] == "git"


def git_invocations(command: str, cwd: Path, depth: int = 0) -> list[GitInvocation]:
    """Every git invocation in the command, in order."""
    found: list[GitInvocation] = []
    if depth > 4:
        return found
    text = re.sub(r"\\\n", " ", command)            # line continuations
    text = text.replace("$'", "'")                   # ANSI-C quoting reads as plain quoting here
    text, heredocs = strip_heredocs(text)
    for prefix, body in heredocs:
        words = _tokens(prefix)
        if words and words[0].rsplit("/", 1)[-1] in SHELLS:
            found.extend(git_invocations(body, cwd, depth + 1))
    for body in _substitutions(text):
        found.extend(git_invocations(body, cwd, depth + 1))
    text = re.sub(r"`[^`]*`", "SUBST", text)

    tokens: list[str] = []
    for line in text.splitlines():
        tokens.extend(_tokens(line))
        tokens.append("\n")
    directory: Path | None = cwd
    stack: list[Path | None] = []
    at_start = True
    env_unsafe = exported_unsafe = ""
    env_config = exported_config = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in SEPARATORS:
            at_start, env_unsafe, env_config = True, exported_unsafe, exported_config
            index += 1
            continue
        if token == "(":
            stack.append(directory)
            at_start = True
            index += 1
            continue
        if token == ")":
            directory = stack.pop() if stack else directory
            index += 1
            continue
        if at_start and token == "export":
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] not in SEPARATORS:
                if GIT_ENV.match(tokens[cursor]):
                    exported_unsafe = tokens[cursor].split("=", 1)[0]
                if GIT_CONFIG_ENV.match(tokens[cursor]):
                    exported_config = tokens[cursor].split("=", 1)[0]
                cursor += 1
            env_unsafe, env_config = exported_unsafe, exported_config
            index = cursor
            continue
        if at_start and ASSIGNMENT.match(token):
            if GIT_ENV.match(token):
                env_unsafe = token.split("=", 1)[0]
            if GIT_CONFIG_ENV.match(token):
                env_config = token.split("=", 1)[0]
            index += 1
            continue
        name = token.rsplit("/", 1)[-1]
        if at_start and (name in TRANSPARENT_PREFIXES or name == "env"):
            index += 1
            continue
        if at_start and name == "cd":
            at_start = False
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] in ("-P", "-L", "-e", "-@"):
                cursor += 1
            if cursor < len(tokens) and tokens[cursor] not in SEPARATORS | {"(", ")"}:
                directory = _resolve(directory, tokens[cursor])
            else:
                directory = _resolve(directory, "~")
            index = cursor + 1
            continue
        if at_start and name in ("pushd", "popd"):
            directory = None
        if name in SHELLS:
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor].startswith("-") and tokens[cursor] not in SEPARATORS:
                option = tokens[cursor]
                cursor += 1
                if not option.startswith("--") and "c" in option[1:]:
                    if cursor < len(tokens):
                        found.extend(git_invocations(tokens[cursor], directory or cwd, depth + 1))
                    break
        if name == "eval":
            cursor = index + 1
            words: list[str] = []
            while cursor < len(tokens) and tokens[cursor] not in SEPARATORS:
                words.append(tokens[cursor])
                cursor += 1
            found.extend(git_invocations(" ".join(words), directory or cwd, depth + 1))
        if not _is_git(token):
            at_start = False
            index += 1
            continue
        at_start = False
        target, configs, unsafe, config_env = directory, [], env_unsafe, env_config
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor].startswith("-") and tokens[cursor] not in SEPARATORS:
            option = tokens[cursor]
            if option.startswith("-c") and len(option) > 2:    # `-cname=value`, attached
                configs.append(option[2:])
                cursor += 1
                continue
            key, _, inline = option.partition("=")
            if key in GLOBAL_VALUE_OPTIONS:
                value = inline if "=" in option else (tokens[cursor + 1] if cursor + 1 < len(tokens) else "")
                cursor += 1 if "=" in option else 2
                if key == "-C":
                    target = _resolve(target, value)
                elif key == "-c":
                    configs.append(value)
                elif key == "--config-env":
                    config_env = config_env or "--config-env"
                elif key in UNSAFE_GLOBALS:
                    unsafe = unsafe or key
                continue
            cursor += 1
        subcommand = tokens[cursor] if cursor < len(tokens) and tokens[cursor] not in SEPARATORS else ""
        cursor += 1
        args: list[str] = []
        while cursor < len(tokens) and tokens[cursor] not in SEPARATORS | {"(", ")"}:
            args.append(tokens[cursor])
            cursor += 1
        found.append(GitInvocation(target, subcommand, _without_redirections(args), configs, unsafe,
                                   config_env))
        index = cursor
    return found


# --- policy ----------------------------------------------------------------

PUSH_ALLOWED_REFSPECS = {"main", "main:main", "refs/heads/main", "refs/heads/main:refs/heads/main"}
PUSH_BLOCKED_OPTIONS = ("--all", "--branches", "--mirror", "--tags", "--follow-tags", "--delete",
                        "--set-upstream", "--prune")
PUSH_BLOCKED_SHORT = {"-d", "-u"}
PUSH_VALUE_OPTIONS = ("--push-option", "--repo", "--receive-pack", "--exec")
BRANCH_VALUE_OPTIONS = {"--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
                        "--sort", "--format", "-u", "--set-upstream-to"}
CONFIG_WRITE_FLAGS = ("--add", "--unset", "--unset-all", "--replace-all", "--rename-section",
                      "--remove-section", "--edit")
CONFIG_VALUE_OPTIONS = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}


def _long(argument: str, *names: str) -> str:
    """The full option name when `argument` is `name` or an unambiguous git-style prefix of it."""
    key = argument.split("=", 1)[0]
    if not key.startswith("--") or len(key) < 3:
        return ""
    for name in names:
        if name.startswith(key):
            return name
    return ""


def _short_has(argument: str, letters: str) -> bool:
    return bool(re.fullmatch(r"-[A-Za-z]+", argument)) and any(letter in argument[1:] for letter in letters)


def _push_violation(args: list[str]) -> str:
    positional: list[str] = []
    repo = False
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "-o" or _long(argument, *PUSH_VALUE_OPTIONS):
            repo = repo or _long(argument, "--repo") == "--repo"
            index += 1 if "=" in argument else 2
            continue
        if _long(argument, "--force", "--force-with-lease", "--force-if-includes") or _short_has(argument, "f"):
            return "FORCE"
        blocked = _long(argument, *PUSH_BLOCKED_OPTIONS)
        if blocked or argument in PUSH_BLOCKED_SHORT or _short_has(argument, "du"):
            return f"`git push {argument}` publishes more than main"
        if not argument.startswith("-"):
            positional.append(argument)
        index += 1
    refspecs = positional if repo else positional[1:]
    for refspec in refspecs:
        if refspec.startswith("+"):
            return "FORCE"
        if refspec not in PUSH_ALLOWED_REFSPECS:
            return f"`git push ... {refspec}` publishes a ref other than main"
    return ""


def _config_violation(args: list[str]) -> str:
    positional: list[str] = []
    skip = False
    for argument in args:
        if skip:
            skip = False
        elif argument in CONFIG_VALUE_OPTIONS:
            skip = True
        elif not argument.startswith("-"):
            positional.append(argument)
    if not positional:
        return ""
    verb = positional[0]
    if verb in ("set", "unset", "rename-section", "remove-section"):
        key, writes = (positional[1] if len(positional) > 1 else ""), True
    elif verb in ("get", "list", "edit"):
        return ""
    else:
        key = verb
        writes = len(positional) > 1 or any(_long(a, *CONFIG_WRITE_FLAGS) for a in args)
    if writes and UNSAFE_CONFIG.match(key):
        return f"`git config {key}` changes what git runs or publishes"
    return ""


def _branch_violation(args: list[str]) -> str:
    deleting = any(a in ("-d", "-D") or _long(a, "--delete") for a in args)
    listing = any(a == "-l" or _long(a, "--list") for a in args)
    for index, argument in enumerate(args):
        if argument.startswith("-"):
            if argument == "-f" or _long(argument, "--force") or (
                    re.fullmatch(r"-[A-Za-z]+", argument) and len(argument) > 2 and "f" in argument):
                return ("`git branch --force` deletes unmerged or moves branches; use `git branch -D` "
                        "(asks first)" if deleting else "`git branch -f` moves a branch")
            if argument in ("-m", "-M", "-c", "-C") or _long(argument, "--move", "--copy"):
                return "`git branch -m/-c` renames or copies a branch"
            continue
        previous = args[index - 1] if index else ""
        if previous in BRANCH_VALUE_OPTIONS:
            continue                                  # the option's own value
        if not deleting and not listing:
            return "`git branch <name>` creates a hand-made branch"
    return ""


def policy_violation(invocation: GitInvocation) -> tuple[str, str]:
    """(category, reason) for a git invocation the repository forbids, else ("", "")."""
    sub, args = invocation.subcommand, invocation.args
    for value in invocation.configs:
        if UNSAFE_CONFIG.match(value):
            return "config", f"`git -c {value.split('=', 1)[0]}` changes what git runs or publishes"
    if invocation.config_env:
        return "config", f"`{invocation.config_env}` injects git configuration"
    if "$" in sub or "`" in sub:
        return "push", "the git subcommand is computed at run time"
    if sub in ("push", "send-pack") or (sub == "subtree" and "push" in args):
        reason = _push_violation(args if sub == "push" else ["origin", *args])
        if sub == "push" and any("$" in a or "`" in a for a in args if not a.startswith("-")):
            reason = reason or "a push refspec is computed at run time"
        if reason == "FORCE":
            return "force", "force pushes are never allowed"
        if reason or sub != "push":
            return "push", reason or f"`git {sub}` pushes outside the reviewed path"
    elif sub == "config":
        reason = _config_violation(args)
        if reason:
            return "config", reason
    elif sub == "checkout" and any(a in ("-b", "-B", "-t") or _short_has(a, "bBt")
                                   or _long(a, "--orphan", "--track") for a in args if a != "--"):
        return "branch", "`git checkout -b/-B/--orphan/--track` creates a hand-made branch"
    elif sub == "switch" and any(_short_has(a, "cCt") or _long(a, "--create", "--force-create", "--orphan",
                                                                  "--track") for a in args):
        return "branch", "`git switch -c/-C/--orphan/--track` creates a hand-made branch"
    elif sub == "branch":
        reason = _branch_violation(args)
        if reason:
            return "branch", reason
    elif sub == "fetch":
        for refspec in (a for a in args if ":" in a and not a.startswith("-")):
            destination = refspec.lstrip("+").split(":", 1)[1]
            if destination and not destination.startswith("refs/remotes/"):
                return "ref", f"`git fetch ... {refspec}` writes a local branch"
    elif sub == "worktree" and args:
        action = args[0]
        if action == "add":
            return "worktree", "`git worktree add` makes a hand-made worktree"
        if action == "move":
            return "worktree", "`git worktree move` takes a worktree out of .claude/worktrees"
        if action == "remove" and any(_long(a, "--force") or _short_has(a, "f") for a in args[2:]):
            return "worktree", ("put --force right after `git worktree remove` so discarding agent "
                                "work asks first")
    elif sub == "tag":
        listing = not args or any(a in ("-l", "-n", "-v") or _long(a, "--list", "--contains", "--no-contains",
                                                                       "--merged", "--no-merged", "--points-at",
                                                                       "--verify")
                                  for a in args)
        if not listing:
            return "ref", "`git tag` writes tags; release tags are maintainer-run"
    elif sub == "update-ref":
        return "ref", "`git update-ref` rewrites refs directly"
    elif sub == "symbolic-ref" and len([a for a in args if not a.startswith("-")]) >= 2:
        return "ref", "`git symbolic-ref <name> <ref>` moves HEAD to another branch"
    return "", ""


def changes_branch(invocation: GitInvocation) -> bool:
    """Whether a later commit or push in the same command may land on another branch."""
    if invocation.subcommand not in BRANCH_CHANGERS:
        return False
    if invocation.subcommand == "checkout" and (not invocation.args or invocation.args[0] == "--"):
        return False                                   # `git checkout -- <paths>` restores files
    if invocation.subcommand == "symbolic-ref":
        return len([a for a in invocation.args if not a.startswith("-")]) >= 2
    return True
