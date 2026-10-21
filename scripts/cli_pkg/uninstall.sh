#!/bin/sh
# Removes the Vocello CLI that the installer package put under /usr/local: the two links
# its postinstall made, the /usr/local/lib/vocello folder and the package receipt.
# It never touches the data store the CLI shares with the Mac app
# (~/Library/Application Support/QwenVoice): voices, models and History stay.
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

# remove_link <link> <relative folder it points into>
remove_link() {
    if [ -L "$1" ]; then
        case "$(/usr/bin/readlink -- "$1")" in
            "$2"/* | "$lib"/*) /bin/rm -f -- "$1" ;;
            *) echo "uninstall.sh: kept $1: it does not point into $lib." >&2 ;;
        esac
    fi
}

remove_link /usr/local/bin/vocello ../lib/vocello
remove_link /usr/local/share/zsh/site-functions/_vocello ../../../lib/vocello
/bin/rm -rf -- "$lib"
/usr/sbin/pkgutil --forget "$receipt" >/dev/null
echo "Vocello CLI removed. Voices, models and History in ~/Library/Application Support/QwenVoice were kept."
