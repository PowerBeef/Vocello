#!/usr/bin/env bash
# Renders the README art (docs/readme/*.png) from the HTML in this folder with headless
# Chrome at twice the CSS size. The art reads the website's design tokens and the
# repository's own screenshots and app icon, so rerun it when either changes.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[[ -x "$chrome" ]] || { echo "error: set CHROME to a Chrome or Chromium executable" >&2; exit 1; }
out="$root/docs/readme"
mkdir -p "$out"
render() { # name width height
  "$chrome" --headless --hide-scrollbars --force-device-scale-factor=2 --allow-file-access-from-files \
    --window-size="$2,$3" --virtual-time-budget=4000 --screenshot="$out/$1.png" "file://$here/$1.html" \
    >/dev/null 2>&1
  echo "rendered docs/readme/$1.png"
}
render hero 800 616
render modes 800 276
render performance 800 246
# Phone-width versions, which the README serves below 700 px through <picture>.
render hero-narrow 400 620
render modes-narrow 400 1064
render performance-narrow 400 560
sips -Z 112 "$root/Sources/Assets.xcassets/AppIcon.appiconset/icon_256x256.png" --out "$out/icon.png" >/dev/null
echo "copied docs/readme/icon.png"
