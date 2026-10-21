#!/bin/sh
# Vocello CLI installer package: preinstall (shipped as the component's `preinstall`).
#
# Installer copies the new payload over the old one but never deletes a file the new
# payload no longer has, so this removes the previously installed CLI first. It removes
# only a real folder that holds the sealed payload's manifest and refuses anything else:
# a symbolic link in its place, or a folder that is not a Vocello CLI installation.
# Installer writes the payload through /usr/local and /usr/local/lib after this returns, so
# each of them that exists must be a real folder that no user but root can change; one that
# is missing is fine, because Installer creates it root's.
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

# Between this script and the payload copy, a user who could change either folder could swap
# the install folder for a link to anywhere.
for folder in "$root/usr/local" "$root/usr/local/lib"; do
    if [ -L "$folder" ] || { [ -e "$folder" ] && [ ! -d "$folder" ]; }; then
        echo "Vocello CLI: $folder is a symbolic link or a file, not a folder." >&2
        echo "Replace it with a real folder owned by root, then run the installer again." >&2
        exit 1
    fi
    if [ -d "$folder" ] && ! trusted "$folder"; then
        echo "Vocello CLI: users other than root can change $folder, so the installer will not write into it." >&2
        echo "Make it root's alone (sudo chown root:wheel \"$folder\" && sudo chmod go-w \"$folder\"), then run the installer again." >&2
        exit 1
    fi
done

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
