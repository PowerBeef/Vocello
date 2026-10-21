#!/bin/sh
# Vocello CLI installer package: postinstall (shipped as the component's `postinstall`).
#
# Links the command and its zsh completion into the shared /usr/local directories, which
# stay out of the payload. The links are relative, so they hold on any target volume. A
# missing directory is created; an existing one keeps its owner and mode. A link or file
# already at either path is replaced; a real folder there is refused. It never runs the CLI.
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

# make_link <directory> <name> <relative target>
make_link() {
    if [ ! -d "$1" ]; then
        if [ -e "$1" ] || [ -L "$1" ]; then
            echo "Vocello CLI: $1 exists and is not a folder, so $2 was not linked." >&2
            exit 1
        fi
        # umask 022 gives every level this creates mode 0755 (mkdir -m would set only the last).
        /bin/mkdir -p -- "$1"
    fi
    if [ -d "$1/$2" ] && [ ! -L "$1/$2" ]; then
        echo "Vocello CLI: $1/$2 is a folder. Move or remove it, then run the installer again." >&2
        exit 1
    fi
    /bin/ln -sfn -- "$3" "$1/$2"
}

make_link "$root/usr/local/bin" vocello ../lib/vocello/vocello
make_link "$root/usr/local/share/zsh/site-functions" _vocello ../../../lib/vocello/_vocello
exit 0
