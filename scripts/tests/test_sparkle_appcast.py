"""The Sparkle appcast helper: Ed25519 against RFC 8032, the feed it writes, and the key it never shows.

`create` runs against a recorded stand-in for Sparkle's sign_update that answers with the
RFC 8032 test-vector signature, and that echoes a key it was not given, as the real tool
does, so the tests can prove the helper withholds that output.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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


def b64(hex_value: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_value)).decode()


SEED, PUBLIC, MESSAGE, SIGNATURE = VECTORS[1]
KEY = b64(SEED)
FEED = "https://github.com/PowerBeef/Vocello/releases/latest/download/appcast.xml"
DMG_URL = "https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26.dmg"
RELEASES = "https://github.com/PowerBeef/Vocello/releases"

# Sparkle's sign_update reads one line from stdin for `--ed-key-file -` and, given a key it
# cannot decode, prints that key back. The stand-in does the same for any unexpected key.
SIGN_UPDATE = f"""#!{sys.executable}
import json, os, sys
key = sys.stdin.readline().rstrip("\\n")
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"args": sys.argv[1:], "keyInEnvironment": "SPARKLE_ED_PRIVATE_KEY" in os.environ}}) + "\\n")
if key != os.environ["STUB_EXPECTED_KEY"]:
    print("ERROR! Failed to decode base64 encoded key data from: " + key)
    sys.exit(1)
print(os.environ.get("STUB_OUTPUT", os.environ["STUB_SIGNATURE"]))
"""


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

    def test_a_changed_message_signature_or_key_does_not_verify(self) -> None:
        public, signature = bytes.fromhex(PUBLIC), bytes.fromhex(SIGNATURE)
        self.assertFalse(module.ed25519_verify(public, signature, self.message("73")))
        for index in (0, 40, 63):
            tampered = bytearray(signature)
            tampered[index] ^= 0x01
            self.assertFalse(module.ed25519_verify(public, bytes(tampered), self.message(MESSAGE)))
        self.assertFalse(module.ed25519_verify(bytes.fromhex(VECTORS[2][1]), signature, self.message(MESSAGE)))
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


class CreateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "sign_update.jsonl"
        self.sign_update = self.root / "bin/sign_update"
        self.sign_update.parent.mkdir()
        self.sign_update.write_text(SIGN_UPDATE, encoding="utf-8")
        self.sign_update.chmod(0o755)
        self.app = self.root / "dist/Vocello.app"
        self.write_app()
        self.dmg = self.root / "dist/Vocello-macos26.dmg"
        self.dmg.write_bytes(bytes.fromhex(MESSAGE))
        self.output = self.root / "dist/appcast.xml"

    def write_app(self, **changes: object) -> None:
        info: dict[str, object] = {
            "CFBundleName": "Vocello", "CFBundleVersion": "24", "CFBundleShortVersionString": "3.0.0",
            "LSMinimumSystemVersion": "26.0", "SUPublicEDKey": b64(PUBLIC), "SUFeedURL": FEED,
        }
        info.update(changes)
        plist = self.app / "Contents/Info.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({key: value for key, value in info.items() if value is not None}))

    def run_create(self, *extra: str, key: str = KEY, **environment: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ, "SPARKLE_ED_PRIVATE_KEY": key, "STUB_LOG": str(self.log),
            "STUB_EXPECTED_KEY": KEY, "STUB_SIGNATURE": b64(SIGNATURE), **environment,
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--app", str(self.app), "--dmg", str(self.dmg),
             "--url", DMG_URL, "--link", RELEASES, "--pub-date-epoch", "1792000000",
             "--sign-update", str(self.sign_update), "--output", str(self.output), *extra],
            env=env, capture_output=True, text=True, timeout=60, check=False,
        )

    def sign_update_calls(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def assert_refused(self, completed: subprocess.CompletedProcess[str], reason: str, key: str = KEY) -> None:
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn(reason, completed.stderr)
        self.assertNotIn(key, completed.stdout + completed.stderr)
        self.assertFalse(self.output.exists())

    def test_signs_on_stdin_verifies_against_the_app_key_and_writes_the_feed(self) -> None:
        completed = self.run_create()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn(KEY, completed.stdout + completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["verifiedAgainst"], "the app's SUPublicEDKey")
        self.assertEqual((summary["version"], summary["shortVersion"], summary["length"]), ("24", "3.0.0", 1))

        # The key went only to stdin: no argument and no environment variable carried it.
        calls = self.sign_update_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], ["--ed-key-file", "-", "-p", str(self.dmg)])
        self.assertFalse(calls[0]["keyInEnvironment"])

        entry = ElementTree.fromstring(self.output.read_bytes()).find("channel/item")
        assert entry is not None
        self.assertEqual(entry.findtext(f"{SPARKLE}version"), "24")
        self.assertEqual(entry.findtext(f"{SPARKLE}shortVersionString"), "3.0.0")
        self.assertEqual(entry.findtext(f"{SPARKLE}minimumSystemVersion"), "26.0")
        enclosure = entry.find("enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.get("url"), DMG_URL)
        self.assertEqual(enclosure.get("length"), "1")
        self.assertEqual(enclosure.get(f"{SPARKLE}edSignature"), b64(SIGNATURE))

    def test_surrounding_whitespace_in_the_secret_is_ignored(self) -> None:
        completed = self.run_create(key=f"  {KEY}\n\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_a_key_that_is_not_the_apps_pair_fails_closed(self) -> None:
        self.write_app(SUPublicEDKey=b64(VECTORS[2][1]))
        self.assert_refused(self.run_create(), "does not verify against the app's SUPublicEDKey")

    def test_a_malformed_key_is_refused_before_sign_update_runs_and_never_shown(self) -> None:
        for malformed in ("not*base64*key", base64.b64encode(b"x" * 31).decode()):
            with self.subTest(malformed=malformed):
                self.assert_refused(self.run_create(key=malformed), "SPARKLE_ED_PRIVATE_KEY", key=malformed)
        self.assertEqual(self.sign_update_calls(), [])
        self.assert_refused(self.run_create(key=""), "SPARKLE_ED_PRIVATE_KEY is empty or unset")

    def test_sign_update_output_is_withheld_when_it_fails(self) -> None:
        other = base64.b64encode(b"\x01" * 32).decode()
        completed = self.run_create(key=other)
        self.assert_refused(completed, "output is withheld", key=other)
        self.assertEqual(len(self.sign_update_calls()), 1)

    def test_unexpected_sign_update_output_is_refused(self) -> None:
        self.assert_refused(self.run_create(STUB_OUTPUT=f"{b64(SIGNATURE)}\nsecond line"), "something other than one signature")
        self.assert_refused(self.run_create(STUB_OUTPUT="!" * 88), "the signature sign_update printed is not base64")

    def test_the_app_must_read_the_feed_this_writes(self) -> None:
        self.write_app(SUFeedURL=FEED.replace("appcast.xml", "feed.xml"))
        self.assert_refused(self.run_create(), "reads its feed as 'feed.xml'")
        self.write_app(SUFeedURL=None)
        self.assert_refused(self.run_create(), "SUFeedURL is missing")

    def test_the_app_must_ship_a_public_key_and_valid_versions(self) -> None:
        for change, reason in (
            ({"SUPublicEDKey": None}, "SUPublicEDKey is not base64"),
            ({"SUPublicEDKey": base64.b64encode(b"k" * 31).decode()}, "SUPublicEDKey decodes to 31 bytes"),
            ({"CFBundleVersion": "24 beta"}, "CFBundleVersion"),
            ({"LSMinimumSystemVersion": None}, "LSMinimumSystemVersion"),
        ):
            with self.subTest(reason):
                self.write_app(**change)
                self.assert_refused(self.run_create(), reason)
        self.assertEqual(self.sign_update_calls(), [])

    def test_an_http_download_url_is_refused(self) -> None:
        completed = self.run_create()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.output.unlink()
        env = {**os.environ, "SPARKLE_ED_PRIVATE_KEY": KEY, "STUB_LOG": str(self.log),
               "STUB_EXPECTED_KEY": KEY, "STUB_SIGNATURE": b64(SIGNATURE)}
        refused = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--app", str(self.app), "--dmg", str(self.dmg),
             "--url", DMG_URL.replace("https:", "http:"), "--pub-date-epoch", "0",
             "--sign-update", str(self.sign_update), "--output", str(self.output)],
            env=env, capture_output=True, text=True, timeout=60, check=False,
        )
        self.assert_refused(refused, "the enclosure URL must be an https URL")

    def test_a_rehearsal_key_verifies_against_its_own_public_half(self) -> None:
        self.write_app(SUPublicEDKey=b64(VECTORS[2][1]))
        completed = self.run_create("--public-key", b64(PUBLIC))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["verifiedAgainst"], "--public-key")

    def test_public_key_prints_the_public_half_of_either_key_format(self) -> None:
        legacy = base64.b64encode(os.urandom(64) + bytes.fromhex(PUBLIC)).decode()
        for secret in (KEY, legacy):
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "public-key"], env={**os.environ, "SPARKLE_ED_PRIVATE_KEY": secret},
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), b64(PUBLIC))
            self.assertNotIn(secret, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
