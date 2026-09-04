#!/usr/bin/env python3
"""Stage/seal and smoke-check the CLI payload used by the existing macOS release lane.

No model installation, generation, publication, or shell-profile modification. The manifest
is an integrity inventory, not independent signing or quality-promotion authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ("mlx-swift_Cmlx.bundle", "swift-transformers_Hub.bundle",
           "swift-crypto_Crypto.bundle", "GRDB_GRDB.bundle")
CATALOGS = ("qwenvoice_contract.json", "qwenvoice_production_model_catalog.json")
FILES = ("vocello", *CATALOGS, "third_party_attributions.json", "LICENSE",
         "THIRD-PARTY-NOTICES.txt", "README.txt")
MANIFEST = "package-manifest.json"
MACHO = {bytes.fromhex(value) for value in ("cffaedfe", "cefaedfe", "feedface",
                                          "feedfacf", "cafebabe", "bebafeca", "cafebabf")}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".cli-json-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identity(version: str, build: str, commit: str) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError("invalid CLI marketing version")
    if not re.fullmatch(r"\d+", build) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid CLI build/source identity")
    return {"marketingVersion": version, "buildNumber": build, "commitSHA": commit}


def inventory(directory: Path) -> list[dict]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("CLI payload must be a real directory")
    entries = []
    total = 0
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("CLI payload contains a link or special file")
        if path.parts[len(directory.parts)] not in {*FILES, *BUNDLES, MANIFEST}:
            raise ValueError("unexpected CLI payload entry")
        if stat.S_ISDIR(info.st_mode):
            if relative.split("/")[0] not in BUNDLES:
                raise ValueError("unexpected CLI payload directory")
            continue
        if relative == MANIFEST:
            continue
        empty_adhoc_signature = relative in {bundle + "/Contents/_CodeSignature/CodeSignature" for bundle in BUNDLES}
        if (info.st_size == 0 and not empty_adhoc_signature) or info.st_size > 1024**3 or info.st_mode & 0o6000:
            raise ValueError("unsafe CLI payload file")
        total += info.st_size
        if total > 2 * 1024**3 or len(entries) >= 5000:
            raise ValueError("CLI payload inventory exceeds bounds")
        with path.open("rb") as stream:
            magic = stream.read(4)
        if relative != "vocello" and (magic in MACHO or info.st_mode & 0o111):
            raise ValueError("unexpected executable code in CLI resources")
        entries.append({"name": relative, "bytes": info.st_size, "sha256": digest(path),
                        "executable": bool(info.st_mode & 0o111)})
    names = {entry["name"] for entry in entries}
    if not set(FILES) <= names or not os.access(directory / "vocello", os.X_OK):
        raise ValueError("CLI payload is missing required files or executable permission")
    for bundle in BUNDLES:
        if not any(name.startswith(bundle + "/") for name in names):
            raise ValueError("CLI resource bundle is missing or empty")
    if not any(name.startswith(BUNDLES[0] + "/") and name.endswith("/default.metallib") for name in names):
        raise ValueError("CLI MLX shader library is missing")
    return entries


def notices(document: dict) -> str:
    licenses = {item["id"]: item["text"] for item in document["licenses"]}
    parts = ["Vocello CLI — third-party licenses and notices",
             "Generated from the application's governed attribution manifest.\n"
             "No model weights are included. Model redistribution/rights decisions remain separate."]
    for item in document["components"]:
        parts += [item["displayName"], item.get("copyrightNotice") or "",
                  item.get("notice") or "", item.get("licenseTextOverride") or licenses[item["licenseID"]]]
    return "\n\n".join(parts) + "\n"


def stage(products: Path, output: Path, root: Path = ROOT) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("refusing to overwrite an existing CLI payload")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cli-stage-", dir=output.parent) as temporary:
        target = Path(temporary) / "payload"
        target.mkdir()
        shutil.copy2(products / "vocello", target / "vocello")
        for bundle in BUNDLES:
            shutil.copytree(products / bundle, target / bundle, symlinks=True)
        # Xcode's tool product does not consistently copy resource-phase JSON. Packaging
        # owns these explicit source-bound data copies; shipped discovery needs no checkout.
        # If Xcode did produce a catalog, reject drift rather than silently replacing it.
        for name in CATALOGS:
            built = products / name
            source = root / "Sources/Resources" / name
            if built.exists() and digest(built) != digest(source):
                raise ValueError("built CLI catalog differs from current source")
            shutil.copy2(source, target / name)
        shutil.copy2(root / "LICENSE", target / "LICENSE")
        attribution = root / "Sources/Resources/third_party_attributions.json"
        shutil.copy2(attribution, target / attribution.name)
        (target / "THIRD-PARTY-NOTICES.txt").write_text(notices(json.loads(attribution.read_text())), encoding="utf-8")
        (target / "README.txt").write_text(
            'Vocello CLI for Apple Silicon / macOS 26+\n\n'
            'Copy this entire "Vocello CLI" folder to a location you control. Keep vocello and\n'
            'all adjacent resources together. No installer, administrator access, or shell change is needed.\n'
            'From Terminal, use the quoted absolute path to the executable, for example:\n'
            '  "/your/chosen/Vocello CLI/vocello" --version\n'
            '  "/your/chosen/Vocello CLI/vocello" modes --json\n'
            '  "/your/chosen/Vocello CLI/vocello" generate --help\n\n'
            'No models, Python, or repository checkout are included or required. Install a model\n'
            'explicitly through Vocello or `vocello models install <id>` before generation.\n'
            'The default data store is shared with the desktop app. Use --data-dir <folder>\n'
            'to select a separate store. Downloads require network; inference is local.\n'
            'Ctrl-C cancels a command. Exit status: 0 success, 1 error, 2 usage, 130 interrupted.\n'
            'See LICENSE, THIRD-PARTY-NOTICES.txt and third_party_attributions.json for notices.\n'
            'The signed DMG and release SHA256SUMS bind this package; package-manifest.json\n'
            'is a content inventory, not independent release or audio-quality approval.\n', encoding="utf-8")
        inventory(target)
        os.replace(target, output)


def seal(directory: Path, release: dict) -> dict:
    payload = {"schemaVersion": 1, "release": release, "files": inventory(directory)}
    atomic_json(directory / MANIFEST, payload)
    return payload


def verify(directory: Path, expected: dict | None = None) -> dict:
    path = directory / MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024**2:
        raise ValueError("missing or oversized CLI manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    release = payload["release"]
    checked = identity(release["marketingVersion"], release["buildNumber"], release["commitSHA"])
    if expected is not None and checked != expected:
        raise ValueError("CLI package source/version identity mismatch")
    if payload != {"schemaVersion": 1, "release": checked, "files": inventory(directory)}:
        raise ValueError("CLI package manifest/content mismatch")
    if (directory / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8") != notices(
            json.loads((directory / "third_party_attributions.json").read_text(encoding="utf-8"))):
        raise ValueError("CLI notices differ from the attribution authority")
    return payload


def command(argv: list[str], cwd: Path, environment: dict, expected: int = 0) -> str:
    result = subprocess.run(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != expected:
        # Raw output may contain operator paths; do not include it in a report/error.
        raise ValueError("CLI package subprocess returned an unexpected exit status")
    return result.stdout


def embedded_info(hex_dump: str) -> dict:
    # `otool -X -s` emits native-endian 32-bit words on the qualified arm64 host.
    words = [word for line in hex_dump.splitlines() for word in line.split()[1:]]
    if not words or len(words) > 16384 or any(not re.fullmatch(r"[0-9a-fA-F]{8}", word) for word in words):
        raise ValueError("invalid CLI embedded Info.plist dump")
    return plistlib.loads(b"".join(int(word, 16).to_bytes(4, "little") for word in words).rstrip(b"\0"))


def smoke(directory: Path, expected: dict) -> dict:
    payload = verify(directory, expected)
    binary = str((directory / "vocello").resolve())
    with tempfile.TemporaryDirectory(prefix="vocello-cli-smoke-") as temporary:
        work = Path(temporary) / "unrelated working folder"
        work.mkdir()
        # Drop caller overrides, DYLD injection and checkout-derived resource paths.
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", **{key: os.environ[key] for key in ("HOME",) if key in os.environ},
                       "TMPDIR": temporary, "LANG": "en_US.UTF-8"}
        if command(["/usr/bin/lipo", "-archs", binary], work, environment).strip() != "arm64":
            raise ValueError("CLI package must contain only arm64")
        linked = command(["/usr/bin/otool", "-L", binary], work, environment).splitlines()[1:]
        if not linked or any(not line.strip().startswith(("/System/Library/", "/usr/lib/")) for line in linked):
            raise ValueError("CLI has an unbundled/non-system dynamic dependency")
        info = embedded_info(command(["/usr/bin/otool", "-X", "-s", "__TEXT", "__info_plist", binary], work, environment))
        if info.get("CFBundleShortVersionString") != expected["marketingVersion"] or info.get("CFBundleVersion") != expected["buildNumber"]:
            raise ValueError("CLI embedded build/version mismatch")
        for alias in (["--version"], ["version"], ["-v"]):
            if command([binary, *alias], work, environment).strip() != "vocello " + expected["marketingVersion"]:
                raise ValueError("CLI embedded version mismatch")
        modes = json.loads(command([binary, "modes", "--json"], work, environment))
        if {row["mode"] for row in modes} != {"custom", "design", "clone"} or len(modes) != 3:
            raise ValueError("CLI mode discovery mismatch")
        speakers = json.loads(command([binary, "speakers", "list", "--json", "--data-dir", str(work / "data")], work, environment))
        catalog = json.loads((directory / CATALOGS[0]).read_text())
        expected_speakers = {speaker for group in catalog["speakers"].values() for speaker in group}
        if {row["id"] for row in speakers} != expected_speakers or len(speakers) != len(expected_speakers):
            raise ValueError("CLI bundled speaker discovery mismatch")
        command([binary, "unknown-package-smoke-command"], work, environment, expected=2)
    return {"schemaVersion": 1, "status": "passed", "release": payload["release"],
            "manifestSHA256": digest(directory / MANIFEST), "fileCount": len(payload["files"]),
            "checks": ["content-integrity", "arm64", "system-linkage", "embedded-version", "embedded-build",
                       "json-modes", "bundled-speakers", "usage-exit-status", "checkout-independent-cwd"],
            "generationQualification": "not-performed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "seal", "verify", "smoke"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--products", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--build")
    parser.add_argument("--commit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "stage":
            if args.products is None:
                raise ValueError("stage requires products")
            stage(args.products, args.directory)
        else:
            if not all((args.version, args.build, args.commit)):
                raise ValueError("exact version/build/commit are required")
            release = identity(args.version, args.build, args.commit)
            action = {"seal": seal, "verify": verify, "smoke": smoke}[args.command]
            result = action(args.directory, release)
            if args.report:
                if args.command != "smoke" or not args.artifact or not args.artifact.is_file():
                    raise ValueError("report requires a smoke check and its DMG artifact")
                result["artifact"] = {"name": args.artifact.name, "bytes": args.artifact.stat().st_size,
                                      "sha256": digest(args.artifact)}
                atomic_json(args.report, result)
        print("CLI package " + args.command + ": PASS")
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print("CLI package " + args.command + ": FAIL (invalid payload, identity, resources, or subprocess)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
