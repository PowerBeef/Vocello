#!/bin/sh
# Removes the Vocello CLI that the installer package put under /usr/local: the two links
# its postinstall made, the /usr/local/lib/vocello folder and the package receipt.
# It never touches the data store the CLI shares with the Mac app
# (~/Library/Application Support/QwenVoice): voices, models and History stay.
# It removes only inside folders that no user but root can change, entered with cd -P and
# checked by their physical path, so a link planted above them cannot redirect a removal.
#
# Run it as: sudo sh /usr/local/lib/vocello/uninstall.sh
# It ships inside the sealed CLI folder (scripts/cli_package.py stage), not as a package script.
set -eu
umask 022

lib=/usr/local/lib/vocello
receipt=com.qwenvoice.cli

refused=0
if [ "$(/usr/bin/id -u)" != 0 ]; then
    echo "uninstall.sh: run it as an administrator: sudo sh $lib/uninstall.sh" >&2
    refused=1
fi
here=$(CDPATH='' cd -P -- "$(/usr/bin/dirname -- "$0")" 2>/dev/null && pwd -P) || here=
if [ "$here" != "$lib" ] || [ -L "$lib" ] || [ ! -f "$lib/package-manifest.json" ]; then
    echo "uninstall.sh: refusing: this is not the installed copy in $lib." >&2
    refused=1
fi
if [ "$refused" != 0 ]; then
    exit 1
fi
if ! /usr/sbin/pkgutil --pkg-info "$receipt" >/dev/null 2>&1; then
    echo "uninstall.sh: refusing: this Mac has no installer receipt for $receipt." >&2
    exit 1
fi

# trusted <folder>: owned by root and writable by no one else.
trusted() {
    info=$(/usr/bin/stat -f '%u %Lp' -- "$1" 2>/dev/null) || return 1
    case "$info" in
        "0 "*) ;;
        *) return 1 ;;
    esac
    mode=${info#* }
    case "$mode" in
        "" | *[!0-7]*) return 1 ;;
    esac
    [ $((0$mode & 022)) -eq 0 ]
}

# enter <folder>: cd into it when it is a trusted folder whose physical path is exactly that one.
enter() {
    CDPATH='' cd -P -- "$1" 2>/dev/null && [ "$(pwd -P)" = "$1" ] && trusted .
}

if ! enter /usr/local/lib; then
    echo "uninstall.sh: refusing: users other than root can change /usr/local/lib, or it is not a real folder." >&2
    echo "Make it root's alone (sudo chown root:wheel /usr/local/lib && sudo chmod go-w /usr/local/lib), then run it again." >&2
    exit 1
fi

# remove_link <folder> <name> <relative folder it points into>
remove_link() {
    if [ ! -e "$1" ] && [ ! -L "$1" ]; then
        return 0
    fi
    if ! enter "$1"; then
        echo "uninstall.sh: kept $1/$2: $1 is not a real folder that only root can change." >&2
        return 0
    fi
    if [ -L "./$2" ]; then
        case "$(/usr/bin/readlink -- "./$2")" in
            "$3"/* | "$lib"/*) /bin/rm -f -- "./$2" ;;
            *) echo "uninstall.sh: kept $1/$2: it does not point into $lib." >&2 ;;
        esac
    fi
}

remove_link /usr/local/bin vocello ../lib/vocello
remove_link /usr/local/share/zsh/site-functions _vocello ../../../lib/vocello
if ! enter /usr/local/lib; then
    echo "uninstall.sh: /usr/local/lib changed while removing the CLI; $lib was kept." >&2
    exit 1
fi
/bin/rm -rf -- ./vocello
/usr/sbin/pkgutil --forget "$receipt" >/dev/null
echo "Vocello CLI removed. Voices, models and History in ~/Library/Application Support/QwenVoice were kept."
