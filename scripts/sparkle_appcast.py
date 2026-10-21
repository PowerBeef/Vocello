#!/usr/bin/env python3
"""Sign the notarized macOS DMG and its one-item appcast for Sparkle (RF-23).

Standard library only, so release.yml runs it as `python3 -I -S` in its `sparkle-feed` job: a
fresh runner that builds nothing and holds only the DMG the `package` job produced and the
`SPARKLE_ED_PRIVATE_KEY` secret.

`create` takes the feed's values from the app users install: it attaches the DMG read-only
(`hdiutil attach -readonly -nobrowse -noautoopen`), reads CFBundleVersion,
CFBundleShortVersionString, LSMinimumSystemVersion, SUPublicEDKey and SUFeedURL from the one app
at the volume's top level, and detaches. Sparkle's `sign_update` (SHA-pinned in
config/toolchain.json `artifactPins`, called by absolute path with only `PATH=/usr/bin:/bin` in
its environment and an empty working directory) then signs the DMG. The private key reaches it
only on standard input: never an argument, a file, part of a message or the tool's environment,
and the tool's output is withheld when it fails, because `sign_update` echoes a key it cannot
decode. The DMG's signature must verify against the app's SUPublicEDKey with the RFC 8032
Ed25519 check below, so a release key that is not the shipped key's pair fails here instead of
on every user's Mac. The helper then renders the feed (RSS 2.0 with Sparkle's namespace and one
item: the versions, the DMG's HTTPS download URL, its byte length and its signature) and has
`sign_update` sign the feed itself, which the app requires (SURequireSignedFeed). Sparkle 2.9 and
later embed that signature as a trailing comment over the bytes before it:

    <!-- sparkle-signatures:
    edSignature: <base64>
    length: <bytes signed>
    -->

`--disable-signing-warning` keeps the rendered bytes as they are (the warning would have
`sign_update` reserialize the XML). The embedded signature must verify against the same key and
cover exactly the rendered feed before anything is written; otherwise nothing is.

`verify` re-checks a signed feed with no secret: its embedded signature, the item's versions
against the DMG's app, the enclosure URL and length, and the enclosure signature over the DMG's
bytes. The job that uploads the draft runs it on the feed it uploads.

`public-key` prints the public half of a private key held in an environment variable. The
release rehearsal signs with an ephemeral key and verifies against that key's public half
(`--public-key`); a release verifies against the app's.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr


SPARKLE_NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
DEFAULT_KEY_ENV = "SPARKLE_ED_PRIVATE_KEY"
HDIUTIL = "/usr/bin/hdiutil"
# Everything sign_update and hdiutil inherit: no secret, no runner or job variable.
TOOL_ENVIRONMENT = {"PATH": "/usr/bin:/bin"}
# CFBundleVersion, CFBundleShortVersionString and LSMinimumSystemVersion: one to three
# period-separated integers.
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}")
BASE64_TEXT = re.compile(r"[A-Za-z0-9+/]+={0,2}")
APP_NAME = re.compile(r"[^\x00-\x1f\x7f]{1,64}")
# The block sign_update (Sparkle 2.9+) appends to a feed it signs; the app reads the last one.
FEED_SIGNATURE_PREFIX = b"<!-- sparkle-signatures:\n"
FEED_SIGNATURE_BLOCK = re.compile(rb"edSignature: ([A-Za-z0-9+/]+={0,2})\nlength: ([0-9]{1,12})\n-->\n")
SIGN_UPDATE_TIMEOUT_SECONDS = 600
HDIUTIL_TIMEOUT_SECONDS = 300
WITHHELD = "its output is withheld because sign_update echoes a key it cannot decode"


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


def _ed25519_verify_chunks(public_key: bytes, signature: bytes, message: Iterable[bytes]) -> bool:
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
    for chunk in message:
        digest.update(chunk)
    challenge = int.from_bytes(digest.digest(), "little") % _L
    return _point_equal(
        _point_multiply(s, _BASE),
        _point_add(commitment, _point_multiply(challenge, public_point)),
    )


def ed25519_verify(public_key: bytes, signature: bytes, message_path: Path) -> bool:
    """Whether `signature` is a valid Ed25519 signature of the file's bytes under `public_key`."""
    with message_path.open("rb") as stream:
        return _ed25519_verify_chunks(public_key, signature, iter(lambda: stream.read(1 << 20), b""))


def ed25519_verify_bytes(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """Whether `signature` is a valid Ed25519 signature of `message` under `public_key`."""
    return _ed25519_verify_chunks(public_key, signature, (message,))


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
    """The unsigned appcast for one item, after checking every field it publishes."""
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


def split_signed_feed(data: bytes) -> tuple[bytes, str]:
    """The bytes a feed's embedded signature covers, and that signature, as sign_update writes them.

    Like Sparkle's SPUExtractAppcastContent the last signature block wins, but nothing may follow
    it and its declared length must be the length of the bytes before it.
    """
    index = data.rfind(FEED_SIGNATURE_PREFIX)
    if index < 0:
        raise AppcastError("the appcast carries no embedded Sparkle signature (<!-- sparkle-signatures: -->)")
    content = data[:index]
    match = FEED_SIGNATURE_BLOCK.fullmatch(data[index + len(FEED_SIGNATURE_PREFIX):])
    if match is None:
        raise AppcastError("the appcast's signature block is not the one sign_update writes, or text follows it")
    if int(match.group(2)) != len(content):
        raise AppcastError(f"the appcast's signature covers {int(match.group(2))} bytes but {len(content)} precede it")
    return content, match.group(1).decode("ascii")


def verify_feed_signature(data: bytes, public_key: bytes, verified_against: str) -> tuple[bytes, str]:
    """The signed feed's content and signature, once the signature verifies against `public_key`."""
    content, signature = split_signed_feed(data)
    signature_bytes = _decode_base64(signature, "the appcast's embedded edSignature", (64,))
    if not ed25519_verify_bytes(public_key, signature_bytes, content):
        raise AppcastError(f"the appcast's embedded signature does not verify against {verified_against}")
    return content, signature


# ── the app inside the DMG ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AppInfo:
    name: str
    version: str
    short_version: str
    minimum_system_version: str
    public_key: bytes
    feed_url: str


def app_info(plist: bytes, source: str) -> AppInfo:
    """The values the feed publishes, from an app's Info.plist bytes."""
    try:
        info = plistlib.loads(plist)
    except (plistlib.InvalidFileException, ValueError) as error:
        raise AppcastError(f"cannot read {source}: {error}") from error
    if not isinstance(info, dict):
        raise AppcastError(f"{source} is not a dictionary")
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


def _executable(value: str, option: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise AppcastError(f"{option} must be an absolute path, not {value!r}")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise AppcastError(f"{option} is not an executable file: {value}")
    return path


def _run_tool(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, env=dict(TOOL_ENVIRONMENT), cwd=cwd,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise AppcastError(f"{Path(command[0]).name} could not run ({type(error).__name__})") from None


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no message"


def _mount_points(attach_output: str) -> set[str]:
    try:
        result = plistlib.loads(attach_output.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError):
        return set()
    entities = result.get("system-entities") if isinstance(result, dict) else None
    if not isinstance(entities, list):
        return set()
    return {os.path.realpath(entity["mount-point"]) for entity in entities
            if isinstance(entity, dict) and isinstance(entity.get("mount-point"), str)}


def _detach(hdiutil: Path, mount: Path, cwd: Path) -> bool:
    for command in ([str(hdiutil), "detach", str(mount)], [str(hdiutil), "detach", "-force", str(mount)]):
        try:
            if _run_tool(command, cwd, HDIUTIL_TIMEOUT_SECONDS).returncode == 0:
                return True
        except AppcastError:
            continue
    return False


def read_dmg_app(dmg: Path, hdiutil: Path) -> AppInfo:
    """The feed's values from the one app at the top of the DMG, attached read-only and detached."""
    with tempfile.TemporaryDirectory(prefix="sparkle-dmg-", ignore_cleanup_errors=True) as scratch:
        workdir = Path(scratch)
        mount = workdir / "volume"
        attach = _run_tool(
            [str(hdiutil), "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(mount),
             "-plist", str(dmg)],
            workdir, HDIUTIL_TIMEOUT_SECONDS,
        )
        if attach.returncode != 0:
            raise AppcastError(f"hdiutil could not attach {dmg.name} read-only (exit {attach.returncode}): "
                               f"{_last_line(attach.stderr)}")
        try:
            if os.path.realpath(mount) not in _mount_points(attach.stdout):
                raise AppcastError(f"hdiutil did not report {dmg.name} mounted where it was asked to")
            apps = sorted(entry for entry in mount.iterdir()
                          if entry.name.endswith(".app") and not entry.name.startswith("."))
            if len(apps) != 1:
                raise AppcastError(f"{dmg.name} must hold exactly one app at its top level, not {len(apps)}")
            plist = apps[0] / "Contents/Info.plist"
            if apps[0].is_symlink() or plist.is_symlink() or not plist.is_file():
                raise AppcastError(f"{apps[0].name} in {dmg.name} has no regular Contents/Info.plist")
            info = app_info(plist.read_bytes(), f"{apps[0].name}/Contents/Info.plist in {dmg.name}")
        finally:
            detached = _detach(hdiutil, mount, workdir)
        if not detached:
            raise AppcastError(f"hdiutil could not detach {dmg.name}")
    return info


# ── signing ─────────────────────────────────────────────────────────────────────────────────
def read_private_key(key_env: str) -> tuple[str, bytes]:
    """The base64 private key in `key_env` (whitespace removed) and its bytes; never echoes it."""
    key = "".join(os.environ.get(key_env, "").split())
    if not key:
        raise AppcastError(f"{key_env} is empty or unset")
    # 32 bytes: a private seed (Sparkle 2); 96: the older private-and-public key pair.
    return key, _decode_base64(key, key_env, (32, 96))


def _sign_update(sign_update: Path, key: str, arguments: list[str], cwd: Path) -> str:
    """sign_update's standard output, with the key on its standard input and nowhere else."""
    try:
        completed = subprocess.run(
            [str(sign_update), "--ed-key-file", "-", *arguments],
            input=key + "\n", capture_output=True, text=True, env=dict(TOOL_ENVIRONMENT), cwd=cwd,
            timeout=SIGN_UPDATE_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AppcastError(f"sign_update could not run ({type(error).__name__})") from None
    if completed.returncode != 0:
        raise AppcastError(f"sign_update exited {completed.returncode}; {WITHHELD}")
    if key in completed.stdout or key in completed.stderr:
        raise AppcastError(f"sign_update printed something other than its result; {WITHHELD}")
    return completed.stdout


def sign_archive(sign_update: Path, key: str, dmg: Path, cwd: Path) -> str:
    """The base64 EdDSA signature `sign_update -p` prints for the DMG."""
    lines = [line.strip() for line in _sign_update(sign_update, key, ["-p", str(dmg)], cwd).splitlines()
             if line.strip()]
    if len(lines) != 1:
        raise AppcastError(f"sign_update printed something other than one signature; {WITHHELD}")
    return lines[0]


def sign_feed(sign_update: Path, key: str, feed: Path, cwd: Path) -> bytes:
    """The feed after `sign_update` embedded its signature (it prints nothing with -p)."""
    if _sign_update(sign_update, key, ["-p", "--disable-signing-warning", str(feed)], cwd).strip():
        raise AppcastError(f"sign_update printed output while signing the feed; {WITHHELD}")
    return feed.read_bytes()


def check_feed(data: bytes, info: AppInfo, dmg: Path, url: str, public_key: bytes,
               verified_against: str) -> dict[str, Any]:
    """Everything an installed copy checks in the signed feed, against the DMG and its app."""
    content, feed_signature = verify_feed_signature(data, public_key, verified_against)
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise AppcastError(f"the signed appcast is not well-formed XML: {error}") from None
    items = root.findall("channel/item")
    if root.tag != "rss" or len(items) != 1:
        raise AppcastError("the appcast must be an RSS feed with exactly one item")
    item = items[0]
    for element, expected in (("version", info.version), ("shortVersionString", info.short_version),
                              ("minimumSystemVersion", info.minimum_system_version)):
        found = item.findtext(f"{{{SPARKLE_NAMESPACE}}}{element}")
        if found != expected:
            raise AppcastError(f"the appcast's sparkle:{element} is {found!r}, but the DMG's app has {expected!r}")
    enclosures = item.findall("enclosure")
    if len(enclosures) != 1:
        raise AppcastError("the appcast's item must have exactly one enclosure")
    enclosure = enclosures[0]
    if enclosure.get("url") != url:
        raise AppcastError(f"the appcast's enclosure URL is {enclosure.get('url')!r}, not {url!r}")
    length = dmg.stat().st_size
    if enclosure.get("length") != str(length):
        raise AppcastError(f"the appcast's enclosure length is {enclosure.get('length')!r}, but the DMG is {length} bytes")
    signature = enclosure.get(f"{{{SPARKLE_NAMESPACE}}}edSignature")
    if not ed25519_verify(public_key, _decode_base64(signature, "the enclosure's sparkle:edSignature", (64,)), dmg):
        raise AppcastError(f"the enclosure's signature does not verify the DMG against {verified_against}")
    return {
        "version": info.version,
        "shortVersion": info.short_version,
        "minimumSystemVersion": info.minimum_system_version,
        "url": url,
        "length": length,
        "edSignature": signature,
        "feedSignature": feed_signature,
        "verifiedAgainst": verified_against,
    }


def _verification_key(info: AppInfo, public_key_override: str | None) -> tuple[bytes, str]:
    if public_key_override is not None:
        return _decode_base64(public_key_override, "--public-key", (32,)), "--public-key"
    return info.public_key, "the app's SUPublicEDKey"


def _feed_name(info: AppInfo, name: str) -> None:
    feed_name = urlsplit(info.feed_url).path.rsplit("/", 1)[-1]
    if feed_name != name:
        raise AppcastError(f"the app reads its feed as {feed_name!r} (SUFeedURL) but this is {name!r}")


def _existing_dmg(dmg: Path) -> Path:
    resolved = dmg.resolve()
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise AppcastError(f"the DMG is missing or empty: {dmg}")
    return resolved


def _write_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create(
    dmg: Path,
    url: str,
    output: Path,
    pub_date_epoch: int,
    sign_update: str,
    key_env: str = DEFAULT_KEY_ENV,
    link: str | None = None,
    public_key_override: str | None = None,
    hdiutil: str = HDIUTIL,
) -> dict[str, Any]:
    sign_update_path = _executable(sign_update, "--sign-update")
    hdiutil_path = _executable(hdiutil, "--hdiutil")
    if not output.name.endswith(".xml"):
        raise AppcastError(f"the appcast must be an .xml file (sign_update signs only .xml feeds): {output.name}")
    _https_url(url, "the enclosure URL")
    if link is not None:
        _https_url(link, "the release link")
    dmg = _existing_dmg(dmg)
    info = read_dmg_app(dmg, hdiutil_path)
    _feed_name(info, output.name)
    public_key, verified_against = _verification_key(info, public_key_override)
    key, _ = read_private_key(key_env)
    length = dmg.stat().st_size
    with tempfile.TemporaryDirectory(prefix="sparkle-sign-") as scratch:
        workdir = Path(scratch) / "cwd"  # sign_update's working directory, empty
        workdir.mkdir()
        signature = sign_archive(sign_update_path, key, dmg, workdir)
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
        feed = Path(scratch) / "feed" / output.name
        feed.parent.mkdir()
        feed.write_bytes(document)
        signed = sign_feed(sign_update_path, key, feed, workdir)
    content, _ = verify_feed_signature(signed, public_key, verified_against)
    if content != document:
        raise AppcastError("sign_update changed the feed it signed; only its signature block may follow the feed")
    summary = check_feed(signed, info, dmg, url, public_key, verified_against)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(output, signed)
    return {"appcast": str(output), **summary}


def verify(
    dmg: Path,
    appcast: Path,
    url: str,
    public_key_override: str | None = None,
    hdiutil: str = HDIUTIL,
) -> dict[str, Any]:
    hdiutil_path = _executable(hdiutil, "--hdiutil")
    dmg = _existing_dmg(dmg)
    try:
        data = appcast.read_bytes()
    except OSError as error:
        raise AppcastError(f"cannot read the appcast: {error}") from None
    info = read_dmg_app(dmg, hdiutil_path)
    _feed_name(info, appcast.name)
    public_key, verified_against = _verification_key(info, public_key_override)
    return {"appcast": str(appcast), **check_feed(data, info, dmg, url, public_key, verified_against)}


def public_key_from_env(key_env: str) -> str:
    _, secret = read_private_key(key_env)
    public = ed25519_public_key(secret) if len(secret) == 32 else secret[64:]
    return base64.b64encode(public).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create", help="sign the DMG and the feed, verify both, write the appcast")
    create_parser.add_argument("--dmg", type=Path, required=True, help="the notarized, stapled DMG")
    create_parser.add_argument("--url", required=True, help="the https URL the DMG is downloaded from")
    create_parser.add_argument("--link", help="an https page for the release history (item link and Version History)")
    create_parser.add_argument("--pub-date-epoch", type=int, required=True, help="publication time, Unix seconds")
    create_parser.add_argument("--output", type=Path, required=True, help="where to write the signed appcast")
    create_parser.add_argument("--sign-update", required=True, help="absolute path of the pinned sign_update")
    create_parser.add_argument("--key-env", default=DEFAULT_KEY_ENV,
                               help=f"environment variable holding the base64 private key (default {DEFAULT_KEY_ENV})")
    verify_parser = commands.add_parser("verify", help="check a signed appcast against the DMG, without a secret")
    verify_parser.add_argument("--dmg", type=Path, required=True, help="the DMG the appcast offers")
    verify_parser.add_argument("--appcast", type=Path, required=True, help="the signed appcast")
    verify_parser.add_argument("--url", required=True, help="the https URL the enclosure must name")
    for subparser in (create_parser, verify_parser):
        subparser.add_argument("--public-key",
                               help="verify against this base64 public key instead of the app's SUPublicEDKey "
                                    "(release rehearsal with an ephemeral key)")
        subparser.add_argument("--hdiutil", default=HDIUTIL, help=f"absolute path of hdiutil (default {HDIUTIL})")
    key_parser = commands.add_parser("public-key", help="print the public half of the private key in --key-env")
    key_parser.add_argument("--key-env", default=DEFAULT_KEY_ENV)
    args = parser.parse_args(argv)
    try:
        if args.command == "public-key":
            print(public_key_from_env(args.key_env))
            return 0
        if args.command == "verify":
            summary = verify(args.dmg, args.appcast, args.url, args.public_key, args.hdiutil)
        else:
            summary = create(
                args.dmg, args.url, args.output, args.pub_date_epoch, args.sign_update,
                key_env=args.key_env, link=args.link, public_key_override=args.public_key, hdiutil=args.hdiutil,
            )
    except (AppcastError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
