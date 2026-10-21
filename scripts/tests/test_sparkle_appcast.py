"""The Sparkle appcast helper: Ed25519 against RFC 8032, the feed it signs, and the key it never shows.

`create` and `verify` run as `python3 -I -S` (as release.yml runs them) against two recorded
stand-ins. The `sign_update` stand-in signs for real with a test-only RFC 8032 signer, embeds
the feed signature the way Sparkle 2.10.0 does (checked against the real tool by hand) and,
given a key it was not expecting, echoes it as the real tool does, so the tests can prove the
helper withholds that output. The `hdiutil` stand-in "attaches" a fixture volume at the mount
point it is given and removes it on detach. Both log their arguments, environment and working
directory.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import inspect
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SCRIPT = Path(__file__).resolve().parents[1] / "sparkle_appcast.py"
SPEC = importlib.util.spec_from_file_location("sparkle_appcast", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"

# RFC 8032 section 7.1, tests 1-3: (private seed, public key, message, signature).
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


def b64(value: str | bytes) -> str:
    return base64.b64encode(bytes.fromhex(value) if isinstance(value, str) else value).decode()


SEED, PUBLIC, MESSAGE, SIGNATURE = VECTORS[1]
KEY = b64(SEED)
OTHER_PUBLIC = VECTORS[2][1]
FEED = "https://github.com/PowerBeef/Vocello/releases/latest/download/appcast.xml"
DMG_URL = "https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26.dmg"
RELEASES = "https://github.com/PowerBeef/Vocello/releases"

def ed25519_sign(curve: Any, seed: bytes, message: bytes) -> bytes:
    """RFC 8032 section 5.1.6 signing, test-only: the helper only verifies. The stand-in
    sign_update runs this same source over the helper's curve arithmetic."""
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    public = curve._compress(curve._point_multiply(scalar, curve._BASE))
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % curve._L
    commitment = curve._compress(curve._point_multiply(nonce, curve._BASE))
    challenge = int.from_bytes(hashlib.sha512(commitment + public + message).digest(), "little") % curve._L
    return commitment + ((nonce + challenge * scalar) % curve._L).to_bytes(32, "little")


SIGNER = inspect.getsource(ed25519_sign).replace("curve: Any", "curve").replace(": bytes", "").replace(" -> bytes", "")


def sign(seed_hex: str, message: bytes) -> bytes:
    return ed25519_sign(module, bytes.fromhex(seed_hex), message)


# Sparkle's sign_update reads one line from stdin for `--ed-key-file -` and, given a key it cannot
# decode, prints that key back. A `.xml` path is a feed: the signature over its bytes is appended
# as the `sparkle-signatures` block and nothing is printed under -p. `feed` in the configuration
# misbehaves on purpose: `rewrite` reformats the XML before signing (what the signing warning
# would cause), `wrong-signature`, `wrong-length`, `trailing`, `unsigned` and `print`.
SIGN_UPDATE = '''#!{python}
import base64, hashlib, importlib.util, json, os, sys
{signer}
with open({config!r}, encoding="utf-8") as stream:
    config = json.load(stream)
spec = importlib.util.spec_from_file_location("curve", {script!r})
curve = importlib.util.module_from_spec(spec)
sys.modules["curve"] = curve
spec.loader.exec_module(curve)
key = sys.stdin.readline().rstrip("\\n")
with open(config["log"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "sign_update", "args": sys.argv[1:], "environment": sorted(os.environ),
                           "path": os.environ.get("PATH"), "cwd": os.getcwd(),
                           "cwdEntries": sorted(os.listdir("."))}}) + "\\n")
if key != config["expectedKey"]:
    print("ERROR! Failed to decode base64 encoded key data from: " + key)
    sys.exit(1)
seed = base64.b64decode(key)
path = sys.argv[-1]
with open(path, "rb") as stream:
    data = stream.read()
if not path.endswith(".xml"):
    print(config.get("archiveOutput") or base64.b64encode(ed25519_sign(curve, seed, data)).decode())
    sys.exit(0)
mode = config.get("feed", "sign")
if mode == "unsigned":
    sys.exit(0)
content = data.replace(b"\\n", b"") if mode == "rewrite" else data
signature = ed25519_sign(curve, seed, content + (b"x" if mode == "wrong-signature" else b""))
length = len(content) + (1 if mode == "wrong-length" else 0)
block = "<!-- sparkle-signatures:\\nedSignature: %s\\nlength: %d\\n-->\\n" % (base64.b64encode(signature).decode(), length)
if mode == "trailing":
    block += "<!-- more -->\\n"
with open(path, "wb") as stream:
    stream.write(content + block.encode())
if mode == "print":
    print("<!-- Updated signature inside appcast.xml -->")
'''

# hdiutil attach copies the fixture volume to -mountpoint and prints its mount point as a plist;
# detach removes it. `attachExit`, `detachExit` (plain detach only) and `forceDetachExit` fail
# on purpose; `reportedMount` reports another mount point.
HDIUTIL = '''#!{python}
import json, os, plistlib, shutil, sys
with open({config!r}, encoding="utf-8") as stream:
    config = json.load(stream)
args = sys.argv[1:]
with open(config["log"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "hdiutil", "args": args, "environment": sorted(os.environ)}}) + "\\n")
if args[0] == "attach":
    if config.get("attachExit"):
        sys.stderr.write("hdiutil: attach failed - image not recognized\\n")
        sys.exit(config["attachExit"])
    mount = args[args.index("-mountpoint") + 1]
    shutil.copytree(config["volume"], mount, symlinks=True)
    reported = config.get("reportedMount", mount)
    sys.stdout.write(plistlib.dumps({{"system-entities": [{{"content-hint": "Apple_HFS", "mount-point": reported}}]}}).decode())
elif args[0] == "detach":
    if "-force" in args and config.get("forceDetachExit"):
        sys.exit(config["forceDetachExit"])
    if "-force" not in args and config.get("detachExit"):
        sys.exit(config["detachExit"])
    shutil.rmtree(args[-1])
else:
    sys.exit(64)
'''


def item(**changes: object) -> object:
    fields: dict[str, object] = {
        "app_name": "Vocello", "version": "24", "short_version": "3.0.0", "minimum_system_version": "26.0",
        "url": DMG_URL, "length": 1, "signature": b64(SIGNATURE), "pub_date_epoch": 1_792_000_000,
        "link": RELEASES,
    }
    fields.update(changes)
    return module.AppcastItem(**fields)  # type: ignore[arg-type]


class Ed25519Tests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def message(self, hex_value: str) -> Path:
        path = self.root / "message"
        path.write_bytes(bytes.fromhex(hex_value))
        return path

    def test_rfc_8032_vectors_verify_and_derive_their_public_keys(self) -> None:
        for seed, public, message, signature in VECTORS:
            with self.subTest(public=public[:8]):
                self.assertEqual(module.ed25519_public_key(bytes.fromhex(seed)).hex(), public)
                self.assertTrue(module.ed25519_verify(bytes.fromhex(public), bytes.fromhex(signature), self.message(message)))
                self.assertTrue(module.ed25519_verify_bytes(bytes.fromhex(public), bytes.fromhex(signature),
                                                            bytes.fromhex(message)))

    def test_the_test_signer_reproduces_the_rfc_8032_signatures(self) -> None:
        for seed, _, message, signature in VECTORS:
            self.assertEqual(sign(seed, bytes.fromhex(message)).hex(), signature)

    def test_a_changed_message_signature_or_key_does_not_verify(self) -> None:
        public, signature = bytes.fromhex(PUBLIC), bytes.fromhex(SIGNATURE)
        self.assertFalse(module.ed25519_verify(public, signature, self.message("73")))
        self.assertFalse(module.ed25519_verify_bytes(public, signature, b"\x73"))
        for index in (0, 40, 63):
            tampered = bytearray(signature)
            tampered[index] ^= 0x01
            self.assertFalse(module.ed25519_verify(public, bytes(tampered), self.message(MESSAGE)))
        self.assertFalse(module.ed25519_verify(bytes.fromhex(OTHER_PUBLIC), signature, self.message(MESSAGE)))
        self.assertFalse(module.ed25519_verify(public, signature[:63], self.message(MESSAGE)))


class RenderTests(unittest.TestCase):
    def test_the_feed_carries_every_field_sparkle_reads(self) -> None:
        document = module.render(item(length=4_242))
        channel = ElementTree.fromstring(document).find("channel")
        assert channel is not None
        items = channel.findall("item")
        self.assertEqual(len(items), 1)
        entry = items[0]
        self.assertEqual(entry.findtext(f"{SPARKLE}version"), "24")
        self.assertEqual(entry.findtext(f"{SPARKLE}shortVersionString"), "3.0.0")
        self.assertEqual(entry.findtext(f"{SPARKLE}minimumSystemVersion"), "26.0")
        self.assertEqual(entry.findtext(f"{SPARKLE}fullReleaseNotesLink"), RELEASES)
        self.assertEqual(entry.findtext("pubDate"), "Wed, 14 Oct 2026 17:46:40 GMT")
        enclosure = entry.find("enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.attrib, {
            "url": DMG_URL, "length": "4242", "type": "application/octet-stream",
            f"{SPARKLE}edSignature": b64(SIGNATURE),
        })

    def test_text_and_attributes_are_escaped(self) -> None:
        url = DMG_URL + "?a=1&b=2"
        document = module.render(item(app_name='Voice & <Co> "Q"', url=url))
        root = ElementTree.fromstring(document)
        self.assertEqual(root.findtext("channel/title"), 'Voice & <Co> "Q"')
        self.assertEqual(root.findtext("channel/item/title"), 'Voice & <Co> "Q" 3.0.0')
        enclosure = root.find("channel/item/enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.get("url"), url)

    def test_the_link_is_optional(self) -> None:
        root = ElementTree.fromstring(module.render(item(link=None)))
        self.assertIsNone(root.find("channel/item/link"))
        self.assertIsNone(root.find(f"channel/item/{SPARKLE}fullReleaseNotesLink"))

    def test_unpublishable_fields_are_refused(self) -> None:
        refused = {
            "an http download": {"url": "http://github.com/x/y.dmg"},
            "a URL with a space": {"url": DMG_URL.replace("Vocello-macos26", "Vocello macos26")},
            "a URL with a quote": {"url": DMG_URL + '"'},
            "a URL with credentials": {"url": "https://user:pw@github.com/x.dmg"},
            "an http link": {"link": "http://github.com/x"},
            "an empty signature": {"signature": ""},
            "a short signature": {"signature": base64.b64encode(b"x" * 63).decode()},
            "a signature that is not base64": {"signature": "!" * 88},
            "an empty DMG": {"length": 0},
            "a length that is not an integer": {"length": True},
            "a build that is not numeric": {"version": "24b"},
            "an empty short version": {"short_version": ""},
            "a minimum system that is not a version": {"minimum_system_version": "Tahoe"},
            "a negative date": {"pub_date_epoch": -1},
            "a name with a control character": {"app_name": "Vo\ncello"},
        }
        for reason, change in refused.items():
            with self.subTest(reason), self.assertRaises(module.AppcastError):
                module.render(item(**change))


class SignedFeedTests(unittest.TestCase):
    def signed(self, content: bytes, *, length: int | None = None, seed: str = SEED) -> bytes:
        signature = b64(sign(seed, content))
        return content + (f"<!-- sparkle-signatures:\nedSignature: {signature}\n"
                          f"length: {len(content) if length is None else length}\n-->\n").encode()

    def test_a_signed_feed_splits_into_its_content_and_signature(self) -> None:
        content = module.render(item())
        verified, signature = module.verify_feed_signature(self.signed(content), bytes.fromhex(PUBLIC), "key")
        self.assertEqual(verified, content)
        self.assertEqual(base64.b64decode(signature), sign(SEED, content))

    def test_the_last_block_is_the_signature_and_must_end_the_file(self) -> None:
        content = module.render(item())
        older = self.signed(content)
        self.assertEqual(module.split_signed_feed(self.signed(older))[0], older)
        for data, reason in (
            (content, "no embedded Sparkle signature"),
            (self.signed(content) + b"\n", "not the one sign_update writes"),
            (self.signed(content, length=len(content) - 1), "covers"),
            (self.signed(content).replace(b"edSignature: ", b"edSignature:  "), "not the one sign_update writes"),
        ):
            with self.subTest(reason), self.assertRaisesRegex(module.AppcastError, reason):
                module.split_signed_feed(data)

    def test_a_feed_signed_by_another_key_or_changed_after_signing_does_not_verify(self) -> None:
        content = module.render(item())
        for data in (self.signed(content, seed=VECTORS[2][0]),
                     self.signed(content).replace(b"3.0.0", b"3.0.1", 1)):
            with self.assertRaisesRegex(module.AppcastError, "embedded signature does not verify"):
                module.verify_feed_signature(data, bytes.fromhex(PUBLIC), "key")


class CommandTests(unittest.TestCase):
    """`create` and `verify` as release.yml runs them, over the two stand-ins."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.log = self.root / "tools.jsonl"
        self.config_path = self.root / "tools.json"
        self.volume = self.root / "volume"
        self.config: dict[str, Any] = {"log": str(self.log), "expectedKey": KEY, "volume": str(self.volume)}
        self.write_config()
        self.sign_update = self.tool("sign_update", SIGN_UPDATE)
        self.hdiutil = self.tool("hdiutil", HDIUTIL)
        self.app = self.volume / "Vocello.app"
        self.write_app()
        (self.volume / "Applications").symlink_to("/Applications")
        self.dmg = self.root / "dist/Vocello-macos26.dmg"
        self.dmg.parent.mkdir()
        self.dmg.write_bytes(os.urandom(4096))
        self.output = self.root / "dist/appcast.xml"

    def tool(self, name: str, template: str) -> Path:
        path = self.root / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(template.format(python=sys.executable, config=str(self.config_path), script=str(SCRIPT),
                                        signer=SIGNER), encoding="utf-8")
        path.chmod(0o755)
        return path

    def write_config(self, **changes: object) -> None:
        self.config.update(changes)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def write_app(self, **changes: object) -> None:
        info: dict[str, object] = {
            "CFBundleName": "Vocello", "CFBundleVersion": "24", "CFBundleShortVersionString": "3.0.0",
            "LSMinimumSystemVersion": "26.0", "SUPublicEDKey": b64(PUBLIC), "SUFeedURL": FEED,
        }
        info.update(changes)
        plist = self.app / "Contents/Info.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({key: value for key, value in info.items() if value is not None}))

    def run_helper(self, *arguments: str, key: str | None = KEY) -> subprocess.CompletedProcess[str]:
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root),
                       "TMPDIR": str(self.root), "UNRELATED_JOB_VARIABLE": "kept-from-the-tools"}
        if key is not None:
            environment["SPARKLE_ED_PRIVATE_KEY"] = key
        return subprocess.run(
            [sys.executable, "-I", "-S", str(SCRIPT), *arguments, "--hdiutil", str(self.hdiutil)],
            env=environment, capture_output=True, text=True, timeout=120, check=False,
        )

    def create(self, *extra: str, key: str | None = KEY, url: str = DMG_URL) -> subprocess.CompletedProcess[str]:
        return self.run_helper(
            "create", "--dmg", str(self.dmg), "--url", url, "--link", RELEASES, "--pub-date-epoch", "1792000000",
            "--sign-update", str(self.sign_update), "--output", str(self.output), *extra, key=key,
        )

    def verify(self, *extra: str, url: str = DMG_URL) -> subprocess.CompletedProcess[str]:
        return self.run_helper("verify", "--dmg", str(self.dmg), "--appcast", str(self.output), "--url", url,
                               *extra, key=None)

    def calls(self, tool: str) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [entry for entry in entries if entry["tool"] == tool]

    def mounts_left(self) -> list[Path]:
        return [path for path in self.root.glob("sparkle-dmg-*/volume")]

    def assert_refused(self, completed: subprocess.CompletedProcess[str], reason: str, key: str = KEY) -> None:
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn(reason, completed.stderr)
        self.assertNotIn(key, completed.stdout + completed.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.mounts_left(), [])

    def test_signs_the_dmg_and_the_feed_with_the_key_only_on_stdin(self) -> None:
        completed = self.create()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn(KEY, completed.stdout + completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["verifiedAgainst"], "the app's SUPublicEDKey")
        self.assertEqual((summary["version"], summary["shortVersion"], summary["length"]), ("24", "3.0.0", 4096))

        # Two sign_update calls: the DMG, then the feed in place, each with nothing inherited.
        calls = self.calls("sign_update")
        self.assertEqual([call["args"][:-1] for call in calls], [
            ["--ed-key-file", "-", "-p"],
            ["--ed-key-file", "-", "-p", "--disable-signing-warning"],
        ])
        self.assertEqual(calls[0]["args"][-1], str(self.dmg))
        self.assertTrue(calls[1]["args"][-1].endswith("/appcast.xml"))
        for call in calls:
            self.assertEqual(call["path"], "/usr/bin:/bin")
            self.assertNotIn("SPARKLE_ED_PRIVATE_KEY", call["environment"])
            self.assertNotIn("UNRELATED_JOB_VARIABLE", call["environment"])
            self.assertEqual(call["cwdEntries"], [])
        self.assertEqual(calls[0]["cwd"], calls[1]["cwd"])

        # The feed values came from the DMG's app, attached read-only and detached.
        attach, *detach = self.calls("hdiutil")
        self.assertEqual(attach["args"][:4], ["attach", "-readonly", "-nobrowse", "-noautoopen"])
        self.assertEqual(attach["args"][-1], str(self.dmg))
        self.assertEqual([call["args"][0] for call in detach], ["detach"])
        self.assertNotIn("SPARKLE_ED_PRIVATE_KEY", attach["environment"])
        self.assertEqual(self.mounts_left(), [])

        data = self.output.read_bytes()
        content, feed_signature = module.verify_feed_signature(data, bytes.fromhex(PUBLIC), "key")
        self.assertEqual(feed_signature, summary["feedSignature"])
        entry = ElementTree.fromstring(content).find("channel/item")
        assert entry is not None
        self.assertEqual(entry.findtext(f"{SPARKLE}version"), "24")
        self.assertEqual(entry.findtext(f"{SPARKLE}shortVersionString"), "3.0.0")
        self.assertEqual(entry.findtext(f"{SPARKLE}minimumSystemVersion"), "26.0")
        enclosure = entry.find("enclosure")
        assert enclosure is not None
        self.assertEqual((enclosure.get("url"), enclosure.get("length")), (DMG_URL, "4096"))
        self.assertEqual(base64.b64decode(enclosure.get(f"{SPARKLE}edSignature") or ""),
                         sign(SEED, self.dmg.read_bytes()))

        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["feedSignature"], feed_signature)

    def test_surrounding_whitespace_in_the_secret_is_ignored(self) -> None:
        completed = self.create(key=f"  {KEY}\n\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_a_key_that_is_not_the_apps_pair_fails_before_the_feed_is_signed(self) -> None:
        self.write_app(SUPublicEDKey=b64(OTHER_PUBLIC))
        self.assert_refused(self.create(), "does not verify against the app's SUPublicEDKey")
        self.assertEqual(len(self.calls("sign_update")), 1)

    def test_a_malformed_key_is_refused_before_sign_update_runs_and_never_shown(self) -> None:
        for malformed in ("not*base64*key", base64.b64encode(b"x" * 31).decode()):
            with self.subTest(malformed=malformed):
                self.assert_refused(self.create(key=malformed), "SPARKLE_ED_PRIVATE_KEY", key=malformed)
        self.assertEqual(self.calls("sign_update"), [])
        self.assert_refused(self.create(key=""), "SPARKLE_ED_PRIVATE_KEY is empty or unset")
        self.assert_refused(self.create(key=None), "SPARKLE_ED_PRIVATE_KEY is empty or unset")

    def test_sign_update_output_is_withheld_when_it_fails(self) -> None:
        other = base64.b64encode(b"\x01" * 32).decode()
        self.assert_refused(self.create(key=other), "output is withheld", key=other)
        self.assertEqual(len(self.calls("sign_update")), 1)

    def test_unexpected_sign_update_output_is_refused(self) -> None:
        self.write_config(archiveOutput=f"{b64(SIGNATURE)}\nsecond line")
        self.assert_refused(self.create(), "something other than one signature")
        self.write_config(archiveOutput="!" * 88)
        self.assert_refused(self.create(), "the signature sign_update printed is not base64")

    def test_a_feed_signature_that_does_not_hold_writes_nothing(self) -> None:
        for mode, reason in (
            ("unsigned", "no embedded Sparkle signature"),
            ("wrong-signature", "embedded signature does not verify against the app's SUPublicEDKey"),
            ("wrong-length", "the appcast's signature covers"),
            ("trailing", "not the one sign_update writes"),
            ("rewrite", "sign_update changed the feed it signed"),
            ("print", "printed output while signing the feed"),
        ):
            with self.subTest(mode=mode):
                self.write_config(feed=mode)
                self.assert_refused(self.create(), reason)

    def test_the_app_must_read_the_feed_this_writes(self) -> None:
        self.write_app(SUFeedURL=FEED.replace("appcast.xml", "feed.xml"))
        self.assert_refused(self.create(), "reads its feed as 'feed.xml'")
        self.write_app(SUFeedURL=None)
        self.assert_refused(self.create(), "SUFeedURL is missing")
        self.assertEqual(self.calls("sign_update"), [])

    def test_the_app_must_ship_a_public_key_and_valid_versions(self) -> None:
        for change, reason in (
            ({"SUPublicEDKey": None}, "SUPublicEDKey is not base64"),
            ({"SUPublicEDKey": base64.b64encode(b"k" * 31).decode()}, "SUPublicEDKey decodes to 31 bytes"),
            ({"CFBundleVersion": "24 beta"}, "CFBundleVersion"),
            ({"LSMinimumSystemVersion": None}, "LSMinimumSystemVersion"),
        ):
            with self.subTest(reason):
                self.write_app(**change)
                self.assert_refused(self.create(), reason)
        self.assertEqual(self.calls("sign_update"), [])

    def test_the_dmg_must_hold_exactly_one_regular_app(self) -> None:
        second = self.volume / "Other.app"
        shutil.copytree(self.app, second)
        self.assert_refused(self.create(), "exactly one app at its top level, not 2")
        shutil.rmtree(second)
        shutil.rmtree(self.app)
        self.assert_refused(self.create(), "exactly one app at its top level, not 0")
        self.app.mkdir()
        (self.app / "Contents").mkdir()
        (self.app / "Contents/Info.plist").symlink_to("/etc/hosts")
        self.assert_refused(self.create(), "has no regular Contents/Info.plist")
        self.assertEqual(self.calls("sign_update"), [])

    def test_attach_and_detach_failures(self) -> None:
        self.write_config(attachExit=1)
        self.assert_refused(self.create(), "could not attach Vocello-macos26.dmg read-only (exit 1): hdiutil: attach failed")
        self.write_config(attachExit=0, reportedMount="/Volumes/Vocello")
        self.assert_refused(self.create(), "did not report Vocello-macos26.dmg mounted where it was asked to")
        self.config.pop("reportedMount")
        # A busy volume is detached with -force; only when that fails too does the run fail.
        self.write_config(detachExit=16)
        completed = self.create()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        attach, plain, forced = self.calls("hdiutil")[-3:]
        mount = attach["args"][attach["args"].index("-mountpoint") + 1]
        self.assertEqual((plain["args"], forced["args"]), (["detach", mount], ["detach", "-force", mount]))
        self.output.unlink()
        self.write_config(forceDetachExit=16)
        completed = self.create()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("could not detach Vocello-macos26.dmg", completed.stderr)
        self.assertFalse(self.output.exists())

    def test_tools_and_output_are_checked_before_anything_runs(self) -> None:
        completed = self.run_helper(
            "create", "--dmg", str(self.dmg), "--url", DMG_URL, "--pub-date-epoch", "0",
            "--sign-update", "sign_update", "--output", str(self.output))
        self.assert_refused(completed, "--sign-update must be an absolute path")
        self.output = self.root / "dist/appcast.rss"
        self.assert_refused(self.create(), "must be an .xml file")
        self.output = self.root / "dist/appcast.xml"
        self.assert_refused(self.create(url=DMG_URL.replace("https:", "http:")), "the enclosure URL must be an https URL")
        self.dmg.write_bytes(b"")
        self.assert_refused(self.create(), "the DMG is missing or empty")
        self.assertEqual(self.calls("sign_update"), [])
        self.assertEqual(self.calls("hdiutil"), [])

    def test_a_rehearsal_key_verifies_against_its_own_public_half(self) -> None:
        self.write_app(SUPublicEDKey=b64(OTHER_PUBLIC))
        completed = self.create("--public-key", b64(PUBLIC))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["verifiedAgainst"], "--public-key")
        self.assertEqual(self.verify("--public-key", b64(PUBLIC)).returncode, 0)
        self.assertIn("does not verify against the app's SUPublicEDKey", self.verify().stderr)

    def test_verify_refuses_a_feed_that_does_not_match_the_dmg(self) -> None:
        self.assertEqual(self.create().returncode, 0)
        signed = self.output.read_bytes()
        self.assertIn("is 'https://github.com", self.verify(url=DMG_URL.replace("v3.0.0", "v3.0.1")).stderr)

        self.write_app(CFBundleVersion="25")
        self.assertIn("sparkle:version is '24', but the DMG's app has '25'", self.verify().stderr)
        self.write_app()

        self.output.write_bytes(signed.replace(b"3.0.0", b"3.0.1", 1))
        self.assertIn("embedded signature does not verify", self.verify().stderr)
        self.output.write_bytes(signed)

        original = self.dmg.read_bytes()
        self.dmg.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        self.assertIn("enclosure's signature does not verify the DMG", self.verify().stderr)
        self.dmg.write_bytes(original + b"\0")
        self.assertIn("but the DMG is 4097 bytes", self.verify().stderr)
        self.dmg.write_bytes(original)
        self.assertEqual(self.verify().returncode, 0)
        self.assertEqual(self.mounts_left(), [])

    def test_public_key_prints_the_public_half_of_either_key_format(self) -> None:
        legacy = base64.b64encode(os.urandom(64) + bytes.fromhex(PUBLIC)).decode()
        for secret in (KEY, legacy):
            completed = subprocess.run(
                [sys.executable, "-I", "-S", str(SCRIPT), "public-key"],
                env={"PATH": "/usr/bin:/bin", "SPARKLE_ED_PRIVATE_KEY": secret},
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), b64(PUBLIC))
            self.assertNotIn(secret, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
