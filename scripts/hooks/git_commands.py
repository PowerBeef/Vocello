"""Parse the git invocations in a Bash command for the repository hooks.

The policy guard and the commit lint both judge git commands. A regex over the
raw text misses real spellings (`git -C "a b" commit`, `git -c x=y push -f`,
`bash -lc 'git push origin topic'`, `timeout 60 git push`, `git commit; git -C
other commit`), so this module tokenizes the command once and yields every git
invocation with the directory it runs in, its global options, subcommand and
arguments. A token whose basename is `git` starts an invocation wherever it
appears (after `xargs`, `sudo`, `if ... then`, `{`), and so does a variable in
command position that holds git or precedes a judged subcommand (`G=git; $G push`,
`$GIT stash`), failing closed. Command substitutions and
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
# Config keys that change which command runs, what a push publishes or which hooks run, or make a
# later `git pull` rebase local commits.
UNSAFE_CONFIG = re.compile(
    r"^(alias\.|remote\..*\.(push|mirror|url|pushurl)|remote\.pushdefault|push\.|"
    r"branch\..*\.(merge|rebase|remote|pushremote)|core\.hookspath|url\.|include|pull\.rebase)",
    re.I,
)
# A command word that is a variable (`$G`, `"${GIT}"`, `${GIT:-git}`): git when the command assigned it
# git, when its name says git, or when the next word is a subcommand the policy judges (BKL-63).
VARIABLE_WORD = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?:[:]?[-=?+][^}]*)?\}|([A-Za-z_][A-Za-z0-9_]*))$")
JUDGED_SUBCOMMANDS = {"add", "stage", "stash", "commit", "push", "send-pack", "subtree", "config", "checkout",
                      "switch", "branch", "fetch", "pull", "worktree", "tag", "update-ref", "symbolic-ref", "reset",
                      "rebase", "filter-branch", "filter-repo", "remote"}
# `git-<subcommand>` binaries run that subcommand (`$(git --exec-path)/git-push`, `git-filter-repo`).
DASHED_GIT = re.compile(r"^git-([a-z][a-z-]*)$")
# A wrapper's own arguments (`timeout 60`, `nice -n 5`, `sudo -u me`, `env -i`) keep the next word in
# command position; `env` options that take a value, so a later `-S` is still found.
DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
ENV_VALUE_OPTIONS = {"-u", "--unset", "-C", "--chdir", "-P"}
# `git remote` verbs that change where a remote points, or which remote a name means (BKL-63).
REMOTE_RETARGETS = {"add", "rename", "remove", "rm", "set-url"}
# The backtick substitution stand-in: a computed word, never a literal name.
SUBSTITUTED = "$SUBST"
REDIRECT = re.compile(r"^[0-9]*[<>]")
# `$(which git)`, `"$(command -v git)"`, `` `type -P git` ``: spellings of the git binary itself.
GIT_LOOKUP = re.compile(r"""["']?(?:\$\(\s*(?:which|command\s+-v|type\s+-P)\s+git\s*\)|`\s*(?:which|command\s+-v|type\s+-P)\s+git\s*`)["']?""")
# What a later commit in the same command may record beyond the index the hook sees.
ADD_COMMANDS = {"add", "stage"}
INDEX_REWRITERS = {"apply", "update-index", "stash"}
COMMIT_VALUE_OPTIONS = {"--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash",
                        "--author", "--date", "--template", "--cleanup", "--trailer"}
COMMIT_VALUE_SHORT = "mFCct"
UNSCOPED_PATH = re.compile(r"[*?\[\]{}$`]|^:")
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
    lexer.commenters = ""                            # bash starts a comment only at a word start
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
        if set(token) <= set("<>&|") and ("<" in token or ">" in token):   # `>|` too
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


def _variable_git(token: str, following: str, git_variables: set[str]) -> bool:
    """Whether a command word that is a variable runs git: one this command set to git, one whose
    name says git, or one followed by a subcommand the policy judges. It fails closed: `$X push`
    is judged as a push whatever `$X` holds."""
    match = VARIABLE_WORD.match(token)
    if not match:
        return False
    name = match.group(1) or match.group(2)
    return name in git_variables or "git" in name.lower() or following in JUDGED_SUBCOMMANDS


def git_invocations(command: str, cwd: Path, depth: int = 0) -> list[GitInvocation]:
    """Every git invocation in the command, in order."""
    found: list[GitInvocation] = []
    if depth > 4:
        return found
    text = re.sub(r"\\\n", " ", command)            # line continuations
    text = text.replace("$'", "'")                   # ANSI-C quoting reads as plain quoting here
    text = GIT_LOOKUP.sub("git", text)               # `$(which git) push` is `git push`
    text, heredocs = strip_heredocs(text)
    for prefix, body in heredocs:
        words = _tokens(prefix)
        if words and words[0].rsplit("/", 1)[-1] in SHELLS:
            found.extend(git_invocations(body, cwd, depth + 1))
    for body in _substitutions(text):
        found.extend(git_invocations(body, cwd, depth + 1))
    text = re.sub(r"`[^`]*`", SUBSTITUTED, text)
    text = join_quoted_newlines(text)                # a message that spans lines is one word

    tokens: list[str] = []
    for line in text.splitlines():
        tokens.extend(_tokens(line))
        tokens.append("\n")
    directory: Path | None = cwd
    stack: list[Path | None] = []
    at_start = True
    env_unsafe = exported_unsafe = ""
    env_config = exported_config = ""
    git_variables: set[str] = set()                  # `G=git`, `export GIT=/usr/bin/git`
    in_wrapper = after_option = False                # inside a wrapper's arguments (`timeout 60 ...`)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in SEPARATORS:
            at_start, env_unsafe, env_config = True, exported_unsafe, exported_config
            in_wrapper = after_option = False
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
        if at_start and token in ("export", "declare", "typeset", "local", "readonly"):
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] not in SEPARATORS:
                if GIT_ENV.match(tokens[cursor]):
                    exported_unsafe = tokens[cursor].split("=", 1)[0]
                if GIT_CONFIG_ENV.match(tokens[cursor]):
                    exported_config = tokens[cursor].split("=", 1)[0]
                if ASSIGNMENT.match(tokens[cursor]) and _is_git(tokens[cursor].split("=", 1)[1]):
                    git_variables.add(tokens[cursor].split("=", 1)[0])
                cursor += 1
            env_unsafe, env_config = exported_unsafe, exported_config
            index = cursor
            continue
        if at_start and ASSIGNMENT.match(token):
            # In command position (at a command's start or among a wrapper's arguments, as in
            # `timeout 60 env GIT_DIR=x git push`). The assignment also stands for the rest of the
            # command, failing closed: a later `export GIT_DIR`, `set -a`, or a variable the
            # environment already exports makes it reach every later git (BKL-63). A search
            # pattern such as `grep 'GIT_DIR='` is an argument, not an assignment.
            if GIT_ENV.match(token):
                env_unsafe = token.split("=", 1)[0]
                exported_unsafe = exported_unsafe or env_unsafe
            if GIT_CONFIG_ENV.match(token):
                env_config = token.split("=", 1)[0]
                exported_config = exported_config or env_config
            if _is_git(token.split("=", 1)[1]):
                git_variables.add(token.split("=", 1)[0])
            index += 1
            continue
        name = token.rsplit("/", 1)[-1]
        if name == "env":
            # `env -S "git push ..."` splits its string into a command, as `bash -c` runs one.
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor] not in SEPARATORS:
                option = tokens[cursor]
                split = ""
                if option in ("-S", "--split-string") and cursor + 1 < len(tokens):
                    split = tokens[cursor + 1]
                elif option.startswith("--split-string="):
                    split = option.split("=", 1)[1]
                elif re.fullmatch(r"-[A-Za-z]*S.*", option) and not option.startswith("--"):
                    split = option[option.index("S") + 1:] or (tokens[cursor + 1] if cursor + 1 < len(tokens) else "")
                if split:
                    found.extend(git_invocations(split, directory or cwd, depth + 1))
                    break
                if option in ENV_VALUE_OPTIONS:
                    cursor += 2                       # `env -u HOME -S ...`: the value, then on
                    continue
                if not option.startswith("-") and not ASSIGNMENT.match(option):
                    break
                cursor += 1
        if at_start and (name in TRANSPARENT_PREFIXES or name == "env"):
            in_wrapper, after_option = True, False
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
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        # A `git-<sub>` word runs git only where a command name stands, after a wrapper and its
        # arguments included (`timeout 60 git-filter-repo`, `sudo -u me git-push`,
        # `"$(git --exec-path)/git-push"`); as an argument (`grep -rn git-push .github`,
        # `ls /opt/homebrew/bin/git-filter-repo`) it is only text.
        dashed = DASHED_GIT.match(name) if at_start else None
        if at_start and in_wrapper and not dashed and not _is_git(token) and not VARIABLE_WORD.match(token) and (
                token.startswith("-") or DURATION.match(token) or after_option):
            # A wrapper's option, its value or a duration: the command is still to come. A value
            # that is itself a dashed git word is judged above, failing closed.
            after_option = token.startswith("-") and "=" not in token
            index += 1
            continue
        if dashed:
            # `git-push origin x` is `git push origin x`: no global options come between.
            cursor = index + 1
            args: list[str] = []
            while cursor < len(tokens) and tokens[cursor] not in SEPARATORS | {"(", ")"}:
                args.append(tokens[cursor])
                cursor += 1
            found.append(GitInvocation(directory, dashed.group(1), _without_redirections(args), [],
                                       env_unsafe, env_config))
            at_start = False
            index = cursor
            continue
        if not (_is_git(token) or (at_start and _variable_git(token, following, git_variables))):
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
PUSH_ALLOWED_REMOTES = {"origin"}
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
    repositories: list[str] = []                     # `--repo` values
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "-o" or _long(argument, *PUSH_VALUE_OPTIONS):
            if _long(argument, *PUSH_VALUE_OPTIONS) == "--repo":
                repositories.append(argument.split("=", 1)[1] if "=" in argument
                                    else (args[index + 1] if index + 1 < len(args) else ""))
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
    refspecs = positional if repositories else positional[1:]
    if any(refspec.startswith("+") for refspec in refspecs):
        return "FORCE"
    # Only origin is published: another remote, a URL or a path is another repository (BKL-63).
    for remote in repositories or positional[:1]:
        if remote not in PUSH_ALLOWED_REMOTES:
            return f"`git push {remote}` publishes to a repository other than origin"
    for refspec in refspecs:
        if refspec not in PUSH_ALLOWED_REFSPECS:
            return f"`git push ... {refspec}` publishes a ref other than main"
    return ""


def _reset_moves_head(invocation: GitInvocation) -> str:
    """The commit a `git reset` moves the branch to, else '' (a reset of the index or the working
    tree to HEAD, or of named paths, rewrites no history). `--soft`, `--hard`, `--keep` and
    `--merge` take a commit; without one of them a single operand is a commit unless it names an
    existing path, and operands after `--` are paths."""
    mode, operands, paths, index = "", [], False, 0
    args = invocation.args
    while index < len(args):
        argument = args[index]
        index += 1
        if paths:
            return ""                                 # pathspecs: the index only
        if argument == "--":
            paths = True
            continue
        if argument.startswith("--"):
            name = _long(argument, "--soft", "--mixed", "--hard", "--keep", "--merge", "--patch",
                         "--pathspec-from-file")
            if name in ("--patch", "--pathspec-from-file"):
                return ""
            mode = name or mode
            continue
        if argument.startswith("-") and len(argument) > 1:
            if "p" in argument[1:]:
                return ""                             # `-p`: the index, hunk by hunk
            continue
        operands.append(argument)
    if not operands or operands[0] in ("HEAD", "@"):
        return ""
    if mode in ("--soft", "--hard", "--keep", "--merge"):
        return operands[0]
    if len(operands) > 1:
        return ""                                     # `git reset <tree-ish> <paths>`: the index only
    target = operands[0]
    if not paths and (any(char in target for char in "*?[") or (
            invocation.directory is not None and (invocation.directory / target).exists())):
        return ""                                     # an existing path: unstage it
    return target


HISTORY_READS = {"--help", "-h"}
REBASE_EXITS = {"--abort", "--quit", "--show-current-patch"}


def _history_violation(invocation: GitInvocation) -> str:
    """Why a git invocation rewrites local history (BKL-63), else ''. The lead records new commits
    and integrates with `git cherry-pick` or `git merge --ff-only`; a rewrite is the maintainer's."""
    sub, args = invocation.subcommand, invocation.args
    if args and args[0] in HISTORY_READS:
        return ""
    if sub == "commit":
        name = _commit_rewrite(args)
        if name == "--amend":
            return "`git commit --amend` rewrites the last commit"
        if name:
            return f"`git commit {name}` records a commit only an autosquash rebase applies"
    elif sub == "rebase":
        if not (args and all(_long(a, *REBASE_EXITS) in REBASE_EXITS for a in args)):
            return "`git rebase` rewrites commits"
    elif sub in ("filter-branch", "filter-repo"):
        return f"`git {sub}` rewrites history"
    elif sub == "reset":
        target = _reset_moves_head(invocation)
        if target:
            return f"`git reset ... {target}` moves the branch to another commit"
    elif sub == "pull":
        for argument in args:
            if _short_has(argument, "r") or (_long(argument, "--rebase") == "--rebase"
                                    and argument.partition("=")[2].lower() not in ("false", "no", "0")):
                return "`git pull --rebase` rewrites local commits onto the remote's"
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
    sections = verb in ("rename-section", "remove-section") or any(
        _long(a, "--rename-section", "--remove-section") for a in args)
    if sections and re.match(r"^(remote|branch|url)(\.|$)", key, re.I):
        return f"`git config` renames or removes the `{key}` section, which names where git publishes"
    return ""


def _upstream_violation(args: list[str]) -> str:
    """`git branch -u <upstream>` / `--set-upstream-to`: an upstream on another remote makes a later
    bare `git push` or `git pull` use that remote (BKL-63); origin's branches are fine."""
    for index, argument in enumerate(args):
        value = ""
        if argument == "-u" or _long(argument, "--set-upstream-to") == "--set-upstream-to":
            value = (argument.split("=", 1)[1] if "=" in argument
                     else (args[index + 1] if index + 1 < len(args) else ""))
        elif argument.startswith("-u") and len(argument) > 2 and not argument.startswith("--"):
            value = argument[2:]
        else:
            continue
        if not value.startswith("origin/"):
            spelled = argument if ("=" in argument or argument != "-u") else f"{argument} {value}"
            return f"`git branch {spelled}` sets an upstream on a remote other than origin"
    return ""


def _remote_violation(args: list[str]) -> str:
    """`git remote add`, `set-url`, `rename`, `remove`: each changes where a remote name points, so
    an approved `git push origin main` could publish elsewhere (BKL-63). Listing and `get-url` read."""
    verbs = [a for a in args if not a.startswith("-")]
    if verbs and verbs[0] in REMOTE_RETARGETS:
        return f"`git remote {verbs[0]}` changes where a remote points; only origin is published"
    return ""


def _branch_violation(args: list[str]) -> str:
    upstream = _upstream_violation(args)
    if upstream:
        return upstream
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


# Quoted spellings of the directory a command runs in or of the checkout's root.
TREE_ROOT_WORDS = ("$PWD", "${PWD}", "$(pwd)", "$CLAUDE_PROJECT_DIR", "${CLAUDE_PROJECT_DIR}",
                   "$VOCELLO_PROJECT_ROOT", "${VOCELLO_PROJECT_ROOT}", "$(git rev-parse --show-toplevel)")
ADD_VALUE_OPTIONS = ("--chmod", "--pathspec-from-file")
STASH_READS = {"list", "show"}


def _whole_tree_pathspec(path: str, directory: Path | None) -> bool:
    """Whether a pathspec names the directory the command runs in, one above it or the whole
    tree (`.`, `./`, `..`, `:/`, `:(top)`, `*`, `"$PWD"`, an exclusion such as `:!docs`) rather
    than a file or a directory below. A computed path (`"$file"`) cannot be judged and is not one."""
    spec = path
    if spec.startswith(":("):
        magic, _, spec = spec[2:].partition(")")
        if any(word.strip() == "exclude" for word in magic.split(",")):
            return True                               # everything but the named paths
    elif spec.startswith(":"):
        spec = spec[1:]
        while spec[:1] in ("/", "!", "^"):
            if spec[0] != "/":
                return True                           # `:!path`, `:^path`: everything but it
            spec = spec[1:]
        spec = spec[1:] if spec.startswith(":") else spec     # the optional end of the short magic
    for word in TREE_ROOT_WORDS:
        if spec == word or spec.startswith(word + "/"):
            spec = "." + spec[len(word):]
            break
    if "$" in spec or "`" in spec:
        return False
    parts = [part for part in spec.split("/") if part not in ("", ".")]
    if not spec.startswith(("/", "~")) and all(part in ("*", "**", "..") for part in parts):
        return True                                   # the directory itself, a parent, or every entry
    if directory is None:
        return False
    here = directory.resolve()
    resolved = _resolve(here, spec)
    return resolved is not None and (resolved == here or resolved in here.parents)


def _add_violation(invocation: GitInvocation) -> str:
    """Why a `git add` stages more than named paths, wherever the flag or the pathspec stands."""
    args = invocation.args
    index, only_paths = 0, False
    while index < len(args):
        argument = args[index]
        index += 1
        if only_paths or not argument.startswith("-") or argument == "-":
            if argument == "$" or "$(" in argument or SUBSTITUTED in argument:
                return "`git add $(...)` stages the paths a substitution computes, not named files"
            if _whole_tree_pathspec(argument, invocation.directory):
                return f"`git add {argument}` stages a whole tree, not named files"
        elif argument == "--":
            only_paths = True
        elif argument.startswith("--"):
            broad = _long(argument, "--all", "--no-ignore-removal", "--update")
            if broad:
                return f"`git add {broad}` stages every {'tracked ' if broad == '--update' else ''}change"
            if _long(argument, *ADD_VALUE_OPTIONS) and "=" not in argument:
                index += 1                            # the option's value, not a pathspec
        elif re.fullmatch(r"-[A-Za-z]+", argument):   # no short option of `git add` takes a value
            if "A" in argument:
                return "`git add -A` stages every change"
            if "u" in argument:
                return "`git add -u` stages every tracked change"
    return ""


def _commit_takes_all(args: list[str]) -> bool:
    """`git commit -a`/`--all`, alone or in a cluster (`-am`, `-qa`); an option's value is not a flag."""
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if argument == "--":
            break
        if argument.startswith("--"):
            if argument == "--all":
                return True
            if _long(argument, *COMMIT_VALUE_OPTIONS) and "=" not in argument:
                index += 1
        elif argument.startswith("-") and len(argument) > 1:
            for position, letter in enumerate(argument[1:], 1):
                if letter == "a":
                    return True
                if letter in "Su":
                    break                             # `-S<keyid>`, `-u<mode>`: the rest is a value
                if letter in COMMIT_VALUE_SHORT:
                    if position == len(argument) - 1:
                        index += 1                    # the value is the next word
                    break
    return False


def _commit_rewrite(args: list[str]) -> str:
    """`--amend`, `--fixup` or `--squash` when a `git commit` carries one (by any unambiguous
    prefix), else ''. Option values, a message included, are not options."""
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if argument == "--":
            break
        if argument.startswith("--"):
            name = _long(argument, "--amend", "--fixup", "--squash")
            if name:
                return name
            if _long(argument, *COMMIT_VALUE_OPTIONS) and "=" not in argument:
                index += 1
        elif argument.startswith("-") and len(argument) > 1:
            for position, letter in enumerate(argument[1:], 1):
                if letter in "Su":
                    break                             # `-S<keyid>`, `-u<mode>`: the rest is a value
                if letter in COMMIT_VALUE_SHORT:
                    if position == len(argument) - 1:
                        index += 1                    # the value is the next word
                    break
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
    # Staging and stashing (CLAUDE.md: stage explicit paths, never stash or broadly stage). The
    # permission rules deny the literal prefixes; these catch every other spelling (`git add -- .`,
    # `git add -v -A`, `git commit -m x -a`, `git -C . stash`).
    if sub in ADD_COMMANDS:
        reason = _add_violation(invocation)
        if reason:
            return "staging", reason
    elif sub == "stash":
        if not args or args[0] not in STASH_READS:
            return "staging", (f"`git stash{' ' + args[0] if args else ''}` changes the stash, which every "
                               "worktree and session shares; only `git stash list` and `git stash show` read it")
    elif sub == "commit" and _commit_takes_all(args):
        return "staging", "`git commit -a` records every tracked change, not the files staged by name"
    reason = _history_violation(invocation)
    if reason:
        return "history", reason
    if sub in ("push", "send-pack") and invocation.unsafe:
        # `GIT_DIR`, `--git-dir` or `--work-tree` (at a command's start or after a wrapper such as
        # `timeout 60 env`): the push publishes another repository's refs (BKL-63).
        return "push", f"`{invocation.unsafe}` points the push at another repository"
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
    elif sub == "remote":
        reason = _remote_violation(args)
        if reason:
            return "push", reason
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
            return "worktree", "`git worktree move` bypasses Claude Code worktree management"
        if action == "remove" and any(_long(a, "--force") or _short_has(a, "f") for a in args[2:]):
            return "worktree", ("put --force right after `git worktree remove` so discarding agent "
                                "work asks first")
    elif sub == "tag":
        listing = not args or any(a in ("-l", "-n", "-v") or _long(a, "--list", "--contains", "--no-contains",
                                                                       "--merged", "--no-merged", "--points-at",
                                                                       "--verify")
                                  for a in args)
        if not listing:
            return "ref", ("`git tag` writes tags; release tags are maintainer-run, and iPhone TestFlight "
                           "candidates go through scripts/ios_candidate_tag.py")
    elif sub == "update-ref":
        return "ref", "`git update-ref` rewrites refs directly"
    elif sub == "symbolic-ref" and len([a for a in args if not a.startswith("-")]) >= 2:
        return "ref", "`git symbolic-ref <name> <ref>` moves HEAD to another branch"
    return "", ""


def join_quoted_newlines(text: str) -> str:
    """Newlines inside quotes become spaces, so a quoted word that spans lines stays one word
    for the per-line tokenizer. A comment is copied as it is: its apostrophes open no quote."""
    out: list[str] = []
    quote = ""
    index = 0
    word_start = True
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(text):
                out.append(text[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = ""
            out.append(" " if char == "\n" else char)
            index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            out.append(text[index:index + 2])
            index += 2
            word_start = False
            continue
        if char == "#" and word_start:
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            out.append(text[index:end])
            index = end
            continue
        if char in "'\"":
            quote = char
        out.append(char)
        word_start = char in " \t\n;&|("
        index += 1
    return "".join(out)


def _scoped(mode: str, paths: list[str]) -> tuple[str, list[str]]:
    """Literal pathspecs keep their scope; a glob, a variable or pathspec magic widens it."""
    if any(UNSCOPED_PATH.search(path) for path in paths):
        return "all", []
    return mode, paths


def add_selection(invocation: GitInvocation) -> tuple[str, list[str]]:
    """What a `git add` moves into the index: `("paths", [...])` for literal pathspecs,
    `("tracked", [...])` for `-u`, `-p`, `-i`, `-e`, or `("all", [])`."""
    mode, paths, only_paths = "paths", [], False
    args = invocation.args
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if only_paths:
            paths.append(argument)
        elif argument == "--":
            only_paths = True
        elif argument.startswith("--"):
            name = argument.split("=", 1)[0]
            if name in ("--all", "--no-ignore-removal", "--pathspec-from-file"):
                mode = "all"
            elif name in ("--update", "--patch", "--interactive", "--edit") and mode != "all":
                mode = "tracked"
            if name in ("--pathspec-from-file", "--chmod") and "=" not in argument:
                index += 1
        elif argument.startswith("-") and len(argument) > 1:
            if "A" in argument:
                mode = "all"
            elif any(letter in argument for letter in "upie") and mode != "all":
                mode = "tracked"
        else:
            paths.append(argument)
    return ("all", []) if mode == "all" else _scoped(mode, paths)


def commit_selection(invocation: GitInvocation) -> tuple[str, list[str]]:
    """What a `git commit` records beyond the index it starts from: `("index", [])` for nothing,
    `("tracked", [...])` for `-a` or interactive selection, `("paths", [...])` for pathspecs
    (`--only` and `--include` take them), or `("all", [])` when the selection cannot be read."""
    mode, paths = "index", []
    args = invocation.args
    index = 0
    while index < len(args):
        argument = args[index]
        index += 1
        if argument == "--":
            paths.extend(args[index:])
            break
        if set(argument) <= set("<>&|"):
            index += 1                                   # a redirection operator and its target
            continue
        if argument.startswith("--"):
            name = argument.split("=", 1)[0]
            if name in ("--all", "--interactive", "--patch"):
                mode = "tracked"
            elif name in ("--pathspec-from-file", "--pathspec-file-nul"):
                return "all", []
            if name in COMMIT_VALUE_OPTIONS and "=" not in argument:
                index += 1
            continue
        if argument.startswith("-") and len(argument) > 1:
            for position, letter in enumerate(argument[1:], 1):
                if letter in "ap":
                    mode = "tracked"
                elif letter in "Su":
                    break                                # `-S<keyid>`, `-u<mode>`: the rest is a value
                elif letter in COMMIT_VALUE_SHORT:
                    if position == len(argument) - 1:
                        index += 1                       # the value is the next word
                    break
            continue
        paths.append(argument)
    if paths and mode == "index":
        mode = "paths"
    return _scoped(mode, paths)


def changes_branch(invocation: GitInvocation) -> bool:
    """Whether a later commit or push in the same command may land on another branch."""
    if invocation.subcommand not in BRANCH_CHANGERS:
        return False
    if invocation.subcommand == "checkout" and (not invocation.args or invocation.args[0] == "--"):
        return False                                   # `git checkout -- <paths>` restores files
    if invocation.subcommand == "symbolic-ref":
        return len([a for a in invocation.args if not a.startswith("-")]) >= 2
    return True
