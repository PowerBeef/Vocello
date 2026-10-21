#!/usr/bin/env python3
"""Sign the notarized macOS DMG for Sparkle and write its one-item appcast (RF-23).

`create` runs Sparkle's `sign_update` (SHA-pinned in config/toolchain.json `artifactPins`)
on the stapled DMG. The EdDSA private key comes from an environment variable and reaches the
tool only on its standard input: it is never an argument, a file, part of a message or passed
on in the tool's environment, and the tool's output is withheld when it fails, because
`sign_update` echoes a key it cannot decode. The signature is then verified against the app's
own `SUPublicEDKey` with the RFC 8032 Ed25519 check below, so a release key that does not
match the shipped public key fails here instead of on every user's Mac. Only then is the feed
written: RSS 2.0 with Sparkle's namespace and one item naming the app's CFBundleVersion,
CFBundleShortVersionString and LSMinimumSystemVersion, the DMG's HTTPS download URL, its byte
length and its signature.

`public-key` prints the public half of a private key held in an environment variable. The
release rehearsal signs with an ephemeral key and verifies against that key's public half
(`create --public-key`); a release verifies against the app's.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr


SPARKLE_NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
DEFAULT_KEY_ENV = "SPARKLE_ED_PRIVATE_KEY"
# CFBundleVersion, CFBundleShortVersionString and LSMinimumSystemVersion: one to three
# period-separated integers.
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}")
BASE64_TEXT = re.compile(r"[A-Za-z0-9+/]+={0,2}")
APP_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,64}")
SIGN_UPDATE_TIMEOUT_SECONDS = 600


class AppcastError(ValueError):
    pass


# ── Ed25519 (RFC 8032, section 6 reference arithmetic) ──────────────────────────────────────
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_Point = tuple[int, int, int, int]  # extended homogeneous coordinates (X, Y, Z, T)


def _point_add(first: _Point, second: _Point) -> _Point:
    a = (first[1] - first[0]) * (second[1] - second[0]) % _P
    b = (first[1] + first[0]) * (second[1] + second[0]) % _P
    c = 2 * first[3] * second[3] * _D % _P
    d = 2 * first[2] * second[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, point)
        point = _point_add(point, point)
        scalar >>= 1
    return result


def _point_equal(first: _Point, second: _Point) -> bool:
    return (
        (first[0] * second[2] - second[0] * first[2]) % _P == 0
        and (first[1] * second[2] - second[1] * first[2]) % _P == 0
    )


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_BASE_Y = 4 * pow(5, _P - 2, _P) % _P
_BASE_X = _recover_x(_BASE_Y, 0)
assert _BASE_X is not None
_BASE: _Point = (_BASE_X, _BASE_Y, 1, _BASE_X * _BASE_Y % _P)


def _compress(point: _Point) -> bytes:
    z_inverse = pow(point[2], _P - 2, _P)
    x = point[0] * z_inverse % _P
    y = point[1] * z_inverse % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(encoded: bytes) -> _Point | None:
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def ed25519_public_key(seed: bytes) -> bytes:
    """The public key of a 32-byte Ed25519 private seed."""
    if len(seed) != 32:
        raise AppcastError("an Ed25519 private seed is 32 bytes")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _compress(_point_multiply(scalar, _BASE))


def ed25519_verify(public_key: bytes, signature: bytes, message_path: Path) -> bool:
    """Whether `signature` is a valid Ed25519 signature of the file's bytes under `public_key`."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    public_point = _decompress(public_key)
    commitment = _decompress(signature[:32])
    if public_point is None or commitment is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    digest = hashlib.sha512()
    digest.update(signature[:32])
    digest.update(public_key)
    with message_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    challenge = int.from_bytes(digest.digest(), "little") % _L
    return _point_equal(
        _point_multiply(s, _BASE),
        _point_add(commitment, _point_multiply(challenge, public_point)),
    )


# ── appcast ─────────────────────────────────────────────────────────────────────────────────
def _decode_base64(value: Any, field: str, expected: tuple[int, ...]) -> bytes:
    if not isinstance(value, str) or not BASE64_TEXT.fullmatch(value):
        raise AppcastError(f"{field} is not base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except binascii.Error:
        raise AppcastError(f"{field} is not base64 text") from None
    if len(decoded) not in expected:
        sizes = " or ".join(str(size) for size in expected)
        raise AppcastError(f"{field} decodes to {len(decoded)} bytes, not {sizes}")
    return decoded


def _https_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AppcastError(f"{field} is missing")
    if any(character.isspace() or ord(character) < 0x20 or character in "\"'<>\\`" for character in value):
        raise AppcastError(f"{field} contains whitespace, a quote or a control character: {value!r}")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise AppcastError(f"{field} must be an https URL without credentials: {value!r}")
    return value


def _version(value: Any, field: str) -> str:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise AppcastError(f"{field} must be one to three period-separated integers, not {value!r}")
    return value


@dataclass(frozen=True)
class AppcastItem:
    app_name: str
    version: str
    short_version: str
    minimum_system_version: str
    url: str
    length: int
    signature: str
    pub_date_epoch: int
    link: str | None = None


def render(item: AppcastItem) -> bytes:
    """The appcast for one item, after checking every field it publishes."""
    if not isinstance(item.app_name, str) or not APP_NAME.fullmatch(item.app_name):
        raise AppcastError("the app name must be 1-64 printable characters")
    version = _version(item.version, "sparkle:version (CFBundleVersion)")
    short_version = _version(item.short_version, "sparkle:shortVersionString (CFBundleShortVersionString)")
    minimum = _version(item.minimum_system_version, "sparkle:minimumSystemVersion (LSMinimumSystemVersion)")
    url = _https_url(item.url, "the enclosure URL")
    link = _https_url(item.link, "the release link") if item.link is not None else None
    if type(item.length) is not int or item.length <= 0:
        raise AppcastError("the enclosure length must be a positive byte count")
    _decode_base64(item.signature, "the EdDSA signature", (64,))
    if type(item.pub_date_epoch) is not int or item.pub_date_epoch < 0:
        raise AppcastError("the publication time must be a non-negative Unix time")
    published = format_datetime(datetime.fromtimestamp(item.pub_date_epoch, tz=timezone.utc), usegmt=True)

    name = escape(item.app_name)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<rss version="2.0" xmlns:sparkle="{SPARKLE_NAMESPACE}">',
        "  <channel>",
        f"    <title>{name}</title>",
    ]
    if link is not None:
        lines.append(f"    <link>{escape(link)}</link>")
    lines += [
        f"    <description>{name} updates</description>",
        "    <language>en</language>",
        "    <item>",
        f"      <title>{name} {escape(short_version)}</title>",
    ]
    if link is not None:
        lines.append(f"      <link>{escape(link)}</link>")
    lines += [
        f"      <pubDate>{published}</pubDate>",
        f"      <sparkle:version>{version}</sparkle:version>",
        f"      <sparkle:shortVersionString>{short_version}</sparkle:shortVersionString>",
        f"      <sparkle:minimumSystemVersion>{minimum}</sparkle:minimumSystemVersion>",
    ]
    if link is not None:
        lines.append(f"      <sparkle:fullReleaseNotesLink>{escape(link)}</sparkle:fullReleaseNotesLink>")
    lines += [
        f"      <enclosure url={quoteattr(url)} length=\"{item.length}\""
        f" type=\"application/octet-stream\" sparkle:edSignature={quoteattr(item.signature)}/>",
        "    </item>",
        "  </channel>",
        "</rss>",
        "",
    ]
    document = "\n".join(lines).encode("utf-8")
    try:
        ElementTree.fromstring(document)
    except ElementTree.ParseError as error:  # a bug here, never an input problem
        raise AppcastError(f"rendered appcast is not well-formed XML: {error}") from error
    return document


# ── inputs ──────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AppInfo:
    name: str
    version: str
    short_version: str
    minimum_system_version: str
    public_key: bytes
    feed_url: str


def read_app(app: Path) -> AppInfo:
    """The values the feed publishes, from the staged app bundle the DMG was made from."""
    plist_path = app / "Contents/Info.plist"
    try:
        info = plistlib.loads(plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as error:
        raise AppcastError(f"cannot read {plist_path}: {error}") from error
    if not isinstance(info, dict):
        raise AppcastError(f"{plist_path} is not a dictionary")
    name = info.get("CFBundleName")
    if not isinstance(name, str) or not APP_NAME.fullmatch(name):
        raise AppcastError("the app's CFBundleName is missing or not printable")
    feed_url = _https_url(info.get("SUFeedURL"), "the app's SUFeedURL")
    return AppInfo(
        name=name,
        version=_version(info.get("CFBundleVersion"), "the app's CFBundleVersion"),
        short_version=_version(info.get("CFBundleShortVersionString"), "the app's CFBundleShortVersionString"),
        minimum_system_version=_version(info.get("LSMinimumSystemVersion"), "the app's LSMinimumSystemVersion"),
        public_key=_decode_base64(info.get("SUPublicEDKey"), "the app's SUPublicEDKey", (32,)),
        feed_url=feed_url,
    )


def read_private_key(key_env: str) -> tuple[str, bytes]:
    """The base64 private key in `key_env` (whitespace removed) and its bytes; never echoes it."""
    key = "".join(os.environ.get(key_env, "").split())
    if not key:
        raise AppcastError(f"{key_env} is empty or unset")
    # 32 bytes: a private seed (Sparkle 2); 96: the older private-and-public key pair.
    return key, _decode_base64(key, key_env, (32, 96))


def sign_with_sign_update(sign_update: str, key: str, key_env: str, dmg: Path) -> str:
    """The base64 EdDSA signature `sign_update` makes of `dmg` with the key on its stdin."""
    executable = sign_update if os.sep in sign_update else shutil.which(sign_update)
    if not executable or not Path(executable).is_file():
        raise AppcastError(f"sign_update is not installed: {sign_update} (scripts/install_pinned_tools.sh sparkle)")
    environment = {name: value for name, value in os.environ.items() if name != key_env}
    try:
        completed = subprocess.run(
            [executable, "--ed-key-file", "-", "-p", str(dmg)],
            input=key + "\n", capture_output=True, text=True, env=environment,
            timeout=SIGN_UPDATE_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AppcastError(f"sign_update could not run ({type(error).__name__})") from None
    withheld = "its output is withheld because sign_update echoes a key it cannot decode"
    if completed.returncode != 0:
        raise AppcastError(f"sign_update exited {completed.returncode}; {withheld}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or key in completed.stdout or key in completed.stderr:
        raise AppcastError(f"sign_update printed something other than one signature; {withheld}")
    return lines[0]


def _write_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create(
    app: Path,
    dmg: Path,
    url: str,
    output: Path,
    pub_date_epoch: int,
    sign_update: str,
    key_env: str = DEFAULT_KEY_ENV,
    link: str | None = None,
    public_key_override: str | None = None,
) -> dict[str, Any]:
    info = read_app(app)
    feed_name = urlsplit(info.feed_url).path.rsplit("/", 1)[-1]
    if feed_name != output.name:
        raise AppcastError(
            f"the app reads its feed as {feed_name!r} (SUFeedURL) but this writes {output.name!r}"
        )
    if not dmg.is_file() or dmg.stat().st_size <= 0:
        raise AppcastError(f"the DMG is missing or empty: {dmg}")
    if public_key_override is not None:
        public_key = _decode_base64(public_key_override, "--public-key", (32,))
        verified_against = "--public-key"
    else:
        public_key = info.public_key
        verified_against = "the app's SUPublicEDKey"
    key, _ = read_private_key(key_env)
    length = dmg.stat().st_size
    signature = sign_with_sign_update(sign_update, key, key_env, dmg)
    signature_bytes = _decode_base64(signature, "the signature sign_update printed", (64,))
    if dmg.stat().st_size != length:
        raise AppcastError("the DMG changed while it was being signed")
    if not ed25519_verify(public_key, signature_bytes, dmg):
        raise AppcastError(
            f"the DMG signature does not verify against {verified_against}: "
            f"the private key in {key_env} is not the pair of the key the app ships"
        )
    document = render(AppcastItem(
        app_name=info.name,
        version=info.version,
        short_version=info.short_version,
        minimum_system_version=info.minimum_system_version,
        url=url,
        length=length,
        signature=signature,
        pub_date_epoch=pub_date_epoch,
        link=link,
    ))
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(output, document)
    return {
        "appcast": str(output),
        "version": info.version,
        "shortVersion": info.short_version,
        "minimumSystemVersion": info.minimum_system_version,
        "url": url,
        "length": length,
        "edSignature": signature,
        "verifiedAgainst": verified_against,
    }


def public_key_from_env(key_env: str) -> str:
    _, secret = read_private_key(key_env)
    public = ed25519_public_key(secret) if len(secret) == 32 else secret[64:]
    return base64.b64encode(public).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create", help="sign the DMG, verify the signature and write the appcast")
    create_parser.add_argument("--app", type=Path, required=True, help="the app bundle packaged in the DMG")
    create_parser.add_argument("--dmg", type=Path, required=True, help="the notarized, stapled DMG")
    create_parser.add_argument("--url", required=True, help="the https URL the DMG is downloaded from")
    create_parser.add_argument("--link", help="an https page for the release history (item link and Version History)")
    create_parser.add_argument("--pub-date-epoch", type=int, required=True, help="publication time, Unix seconds")
    create_parser.add_argument("--output", type=Path, required=True, help="where to write the appcast")
    create_parser.add_argument("--sign-update", default="sign_update", help="Sparkle's sign_update (default: on PATH)")
    create_parser.add_argument("--key-env", default=DEFAULT_KEY_ENV,
                               help=f"environment variable holding the base64 private key (default {DEFAULT_KEY_ENV})")
    create_parser.add_argument("--public-key",
                               help="verify against this base64 public key instead of the app's SUPublicEDKey "
                                    "(release rehearsal with an ephemeral key)")
    key_parser = commands.add_parser("public-key", help="print the public half of the private key in --key-env")
    key_parser.add_argument("--key-env", default=DEFAULT_KEY_ENV)
    args = parser.parse_args(argv)
    try:
        if args.command == "public-key":
            print(public_key_from_env(args.key_env))
            return 0
        summary = create(
            args.app, args.dmg, args.url, args.output, args.pub_date_epoch, args.sign_update,
            key_env=args.key_env, link=args.link, public_key_override=args.public_key,
        )
    except AppcastError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
