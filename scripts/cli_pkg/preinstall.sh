#!/bin/sh
# Vocello CLI installer package: preinstall (shipped as the component's `preinstall`).
#
# Installer copies the new payload over the old one but never deletes a file the new
# payload no longer has, so this removes the previously installed CLI first. It removes
# only a real folder that holds the sealed payload's manifest and refuses anything else:
# a symbolic link in its place, or a folder that is not a Vocello CLI installation.
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
dir="$root/usr/local/lib/vocello"

if [ -L "$dir" ]; then
    echo "Vocello CLI: $dir is a symbolic link, not the installed CLI." >&2
    echo "Remove the link (sudo rm \"$dir\"), then run the installer again." >&2
    exit 1
fi
if [ -d "$dir" ]; then
    if [ -f "$dir/package-manifest.json" ] && [ ! -L "$dir/package-manifest.json" ]; then
        /bin/rm -rf -- "$dir"
        exit 0
    fi
    echo "Vocello CLI: $dir exists but is not a Vocello CLI installation." >&2
    echo "Move or remove it yourself (sudo rm -rf \"$dir\"), then run the installer again." >&2
    exit 1
fi
if [ -e "$dir" ]; then
    echo "Vocello CLI: $dir exists and is not a folder." >&2
    echo "Move or remove it yourself (sudo rm \"$dir\"), then run the installer again." >&2
    exit 1
fi
exit 0
