#!/bin/sh
# Vocello CLI installer package: postinstall (shipped as the component's `postinstall`).
#
# Links the command and its zsh completion into the shared /usr/local directories, which
# stay out of the payload. The links are relative, so they hold on any target volume. It
# works only inside a folder that no user but root can change, entered with cd -P and checked
# by its physical path, so a link planted above it cannot send a link elsewhere. A missing
# folder is created only below such a folder; an existing one keeps its owner and mode. Only
# a link into the installed folder is replaced: a file, a folder or another link at either
# path stays as it is, and so does a folder it cannot trust. Either way it warns, naming the
# installed command, and the install still succeeds. It never runs the CLI.
# Installer passes the target volume as $3 ("/" for the startup disk); every path comes
# from it. Built and verified by scripts/cli_package.py (pkg, pkg-verify).
set -eu
umask 022

case "${3-}" in
    /*) ;;
    *)
        echo "Vocello CLI: the installer did not name a target volume." >&2
        exit 1
        ;;
esac
root="${3%/}"
lib="$root/usr/local/lib/vocello"

if [ -L "$lib" ] || [ ! -f "$lib/vocello" ] || [ ! -x "$lib/vocello" ]; then
    echo "Vocello CLI: the installed command is missing from $lib." >&2
    exit 1
fi
# The volume's physical path, with no trailing slash ("" for the startup disk).
volume=$(CDPATH='' cd -P -- "$root/" && pwd -P) || {
    echo "Vocello CLI: the target volume $root cannot be entered." >&2
    exit 1
}
[ "$volume" != / ] || volume=
# Installer runs this as root. A run by anyone else (the root-free check in pkg-verify)
# also trusts folders of its own, which that user could change anyway.
self=$(/usr/bin/id -u)

# trusted <folder>: owned by root (or by whoever runs this) and writable by no one else.
trusted() {
    info=$(/usr/bin/stat -f '%u %Lp' -- "$1" 2>/dev/null) || return 1
    case "$info" in
        "0 "* | "$self "*) ;;
        *) return 1 ;;
    esac
    mode=${info#* }
    case "$mode" in
        "" | *[!0-7]*) return 1 ;;
    esac
    [ $((0$mode & 022)) -eq 0 ]
}

# enter <folder below the volume, or "">: cd into it when it is a trusted folder whose
# physical path is exactly that one.
enter() {
    path="$volume${1:+/$1}"
    CDPATH='' cd -P -- "${path:-/}" 2>/dev/null && [ "$(pwd -P)" = "${path:-/}" ] && trusted .
}

# folder <folder below the volume>: enter it, first creating its missing levels from inside
# the nearest level that exists, which must be trusted too.
folder() {
    have=$1
    missing=
    while [ -n "$have" ] && [ ! -e "$volume/$have" ] && [ ! -L "$volume/$have" ]; do
        missing="${have##*/}${missing:+/$missing}"
        case "$have" in
            */*) have=${have%/*} ;;
            *) have= ;;
        esac
    done
    if [ -n "$missing" ]; then
        enter "$have" || return 1
        /bin/mkdir -p -- "$missing" || return 1
    fi
    enter "$1"
}

# link <folder below the volume> <name> <the installed folder, relative to that folder>
link() {
    if ! folder "$1"; then
        echo "Vocello CLI: $root/$1 is not a real folder that only root can change, so $2 was not linked there." >&2
        echo "The command is installed at $lib/vocello." >&2
        return 0
    fi
    if [ -e "./$2" ] || [ -L "./$2" ]; then
        if [ -L "./$2" ]; then
            target=$(/usr/bin/readlink -- "./$2") || target=
        else
            target=
        fi
        case "$target" in
            "$3"/* | /usr/local/lib/vocello/*) ;;
            *)
                echo "Vocello CLI: $root/$1/$2 is not a link into the installed CLI, so it was left as it is." >&2
                echo "The command is installed at $lib/vocello." >&2
                return 0
                ;;
        esac
    fi
    /bin/ln -sfn -- "$3/$2" "./$2"
}

link usr/local/bin vocello ../lib/vocello
link usr/local/share/zsh/site-functions _vocello ../../../lib/vocello
exit 0
