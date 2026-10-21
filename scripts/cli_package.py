#!/usr/bin/env python3
"""Stage/seal and smoke-check the CLI payload used by the existing macOS release lane.

The same sealed folder ships twice: as the DMG folder and, through `pkg`, as an
installer package that puts it at /usr/local/lib/vocello; `pkg-verify` checks an
expanded package against the sealed manifest. Signing the package is release.sh's job.
Model generation runs only through the opt-in qualify command. No model installation,
publication, or shell-profile modification. The manifest is an integrity inventory,
not independent signing or quality-promotion authority.
"""
from __future__ import annotations

import argparse
import codecs
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import wave
from typing import Callable, Iterator, NoReturn
import xml.etree.ElementTree as ElementTree
from xml.parsers import expat

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import vocello_cli_json  # noqa: E402
from lib import jsonio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ("mlx-swift_Cmlx.bundle", "swift-transformers_Hub.bundle",
           "swift-crypto_Crypto.bundle", "GRDB_GRDB.bundle")
CATALOGS = ("qwenvoice_contract.json", "qwenvoice_production_model_catalog.json")
COMPLETION = "_vocello"
UNINSTALLER = "uninstall.sh"
FILES = ("vocello", *CATALOGS, "third_party_attributions.json", "LICENSE",
         "THIRD-PARTY-NOTICES.txt", "README.txt", COMPLETION, UNINSTALLER)
MANIFEST = "package-manifest.json"
# Repository sources of the files the package carries beside the built products.
COMPLETION_SOURCE = "scripts/completions/_vocello"
PKG_SCRIPT_SOURCES = {"preinstall": "scripts/cli_pkg/preinstall.sh",
                      "postinstall": "scripts/cli_pkg/postinstall.sh"}
UNINSTALLER_SOURCE = "scripts/cli_pkg/uninstall.sh"
PKG_IDENTIFIER = "com.qwenvoice.cli"
INSTALL_LOCATION = "/usr/local/lib/vocello"
COMPONENT = "vocello-cli.pkg"
PKG_TITLE = "Vocello CLI"
# The shared /usr/local directories stay out of the payload; postinstall links into them.
PKG_LINKS = {"usr/local/bin/vocello": "../lib/vocello/vocello",
             "usr/local/share/zsh/site-functions/_vocello": "../../../lib/vocello/_vocello"}
PKG_SIGNATURES = ("developer-id-installer", "unsigned")
PKG_NOTARIZATIONS = ("stapled", "not-performed")
# What `pkg-verify` proves, in report order; the install checks join only with --root-free-install.
PKG_CHECKS = (
    "distribution-script-free", "distribution-arm64-only", "distribution-minimum-os",
    "distribution-boot-volume-only", "distribution-single-hidden-package", "installer-resources",
    "package-identity", "non-relocatable-bundles", "package-scripts-match-source",
    "payload-content-integrity", "payload-manifest-digest", "payload-helpers-match-source",
    "bom-matches-payload", "bom-root-ownership", "bom-modes", "bom-no-setid",
    "signature-state", "notarization-state",
)
PKG_INSTALL_CHECKS = (
    "root-free-install", "relative-links", "smoke-through-link", "upgrade-removes-stale-payload",
    "refuses-symlinked-install-folder", "refuses-foreign-install-folder",
)
PKG_TOOL_TIMEOUT = 600
MACHO = {bytes.fromhex(value) for value in ("cffaedfe", "cefaedfe", "feedface",
                                          "feedfacf", "cafebabe", "bebafeca", "cafebabf")}


digest = jsonio.sha256_file


def atomic_json(path: Path, value: dict) -> None:
    jsonio.atomic_json(path, value, allow_nan=False, mkdir=False)


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


README = (
    'Vocello CLI for Apple Silicon / macOS 26+\n\n'
    'The same files ship two ways.\n\n'
    'Installer package (Vocello-macos26-cli.pkg)\n'
    '  Open the package and follow Installer; it asks for an administrator password. It puts\n'
    '  this folder at /usr/local/lib/vocello, links /usr/local/bin/vocello to it and adds\n'
    '  zsh completion in /usr/local/share/zsh/site-functions. Your shell profile is not changed.\n'
    '  From a new Terminal window:\n'
    '    vocello --version\n'
    '    vocello generate --help\n'
    '  Agents and other tools that do not read your PATH use the absolute path, for example:\n'
    '    /usr/local/bin/vocello mcp\n'
    '  To upgrade, install a newer package; it replaces the previous files.\n'
    '  To remove it:\n'
    '    sudo sh /usr/local/lib/vocello/uninstall.sh\n\n'
    'Folder copy (Vocello-macos26-cli.dmg)\n'
    '  Copy this entire "Vocello CLI" folder to a location you control. Keep vocello and\n'
    '  all adjacent resources together. No installer, administrator access, or shell change is needed.\n'
    '  From Terminal, use the quoted absolute path to the executable, for example:\n'
    '    "/your/chosen/Vocello CLI/vocello" --version\n'
    '    "/your/chosen/Vocello CLI/vocello" modes --json\n'
    '    "/your/chosen/Vocello CLI/vocello" generate --help\n'
    '  To remove it, delete the folder. Its uninstall.sh is only for the installer package.\n\n'
    'No models, Python, or repository checkout are included or required. Install a model\n'
    'explicitly through Vocello or `vocello models install <id>` before generation.\n'
    'The default data store (~/Library/Application Support/QwenVoice) is shared with the\n'
    'desktop app; removing the CLI either way never removes it. Use --data-dir <folder>\n'
    'to select a separate store. Downloads require network; inference is local.\n'
    'Ctrl-C cancels a command. Exit status: 0 success, 1 error, 2 usage, 75 the engine\n'
    'stopped a take under memory pressure (retry later), 130 interrupted.\n'
    'See LICENSE, THIRD-PARTY-NOTICES.txt and third_party_attributions.json for notices.\n'
    'The signed package or DMG and the release SHA256SUMS bind this folder; package-manifest.json\n'
    'is a content inventory, not independent release or audio-quality approval.\n')


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
        # Plain data in both routes: zsh reads the completion, `sudo sh` runs the uninstaller,
        # so `vocello` stays the payload's only executable.
        for name, source in ((COMPLETION, COMPLETION_SOURCE), (UNINSTALLER, UNINSTALLER_SOURCE)):
            shutil.copyfile(root / source, target / name)
            (target / name).chmod(0o644)
        (target / "README.txt").write_text(README, encoding="utf-8")
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


def command(argv: list[str], cwd: Path, environment: dict, expected: int = 0, timeout: int = 60) -> str:
    result = subprocess.run(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout, check=False)
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


def _launcher(directory: Path, launcher: Path | None) -> str:
    """The path commands run through: the payload's executable, or an installed link to it."""
    executable = (directory / "vocello").resolve()
    if launcher is None:
        return str(executable)
    if not launcher.is_absolute() or not launcher.is_symlink() or launcher.resolve() != executable:
        raise ValueError("CLI launcher must be an absolute link to the payload executable")
    return str(launcher)


def smoke(directory: Path, expected: dict, *, launcher: Path | None = None) -> dict:
    payload = verify(directory, expected)
    # lipo and otool read the real file; every command runs through the launcher.
    executable = str((directory / "vocello").resolve())
    binary = _launcher(directory, launcher)
    with tempfile.TemporaryDirectory(prefix="vocello-cli-smoke-") as temporary:
        work = Path(temporary) / "unrelated working folder"
        work.mkdir()
        # Drop caller overrides, DYLD injection and checkout-derived resource paths.
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", **{key: os.environ[key] for key in ("HOME",) if key in os.environ},
                       "TMPDIR": temporary, "LANG": "en_US.UTF-8"}
        if command(["/usr/bin/lipo", "-archs", executable], work, environment).strip() != "arm64":
            raise ValueError("CLI package must contain only arm64")
        linked = command(["/usr/bin/otool", "-L", executable], work, environment).splitlines()[1:]
        if not linked or any(not line.strip().startswith(("/System/Library/", "/usr/lib/")) for line in linked):
            raise ValueError("CLI has an unbundled/non-system dynamic dependency")
        info = embedded_info(command(["/usr/bin/otool", "-X", "-s", "__TEXT", "__info_plist", executable], work, environment))
        if info.get("CFBundleShortVersionString") != expected["marketingVersion"] or info.get("CFBundleVersion") != expected["buildNumber"]:
            raise ValueError("CLI embedded build/version mismatch")
        for alias in (["--version"], ["version"], ["-v"]):
            if command([binary, *alias], work, environment).strip() != "vocello " + expected["marketingVersion"]:
                raise ValueError("CLI embedded version mismatch")
        modes = vocello_cli_json.rows(
            vocello_cli_json.read_result(command([binary, "modes", "--json"], work, environment)), "modes")
        if {row["mode"] for row in modes} != {"custom", "design", "clone"} or len(modes) != 3:
            raise ValueError("CLI mode discovery mismatch")
        speakers = vocello_cli_json.rows(vocello_cli_json.read_result(
            command([binary, "speakers", "list", "--json", "--data-dir", str(work / "data")], work, environment)
        ), "speakers")
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


def _qualification_environment(temporary: str) -> dict[str, str]:
    """Build a release-like environment without development runtime overrides."""

    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        **{key: os.environ[key] for key in ("HOME",) if key in os.environ},
        "TMPDIR": temporary,
        "LANG": "en_US.UTF-8",
    }


def _run_qualification_generation(
    argv: list[str], cwd: Path, environment: dict[str, str], timeout: int = 900
) -> dict:
    process = subprocess.Popen(
        argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except BaseException:
        _stop_qualification_process(process)
        raise
    if len(argv) > 1 and argv[1] == "batch" and stdout:
        # Raw command output stays beside the ignored QA audio, including partial
        # failure rows. Never copy paths/text from this file into the safe report.
        (cwd / "batch-result.json").write_text(stdout, encoding="utf-8")
    if process.returncode != 0:
        raise ValueError("CLI qualification generation failed")
    try:
        payload = vocello_cli_json.read_result(stdout, exit_code=process.returncode)
    except (ValueError, vocello_cli_json.VocelloCLIError) as error:
        raise ValueError("CLI qualification generation returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("CLI qualification generation returned a non-object")
    return payload


def _stop_qualification_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Gone already; macOS answers EPERM for a group whose leader exited unreaped.
        pass
    process.communicate()


def _run_qualification_cancellation(
    argv: list[str], cwd: Path, environment: dict[str, str], timeout: int = 900
) -> dict:
    """SIGINT a take once its `generation_started` event is on stdout (`--ndjson`), then
    require exit 130 and a final envelope reporting the cancellation, with no forced exit."""
    process = subprocess.Popen(
        argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    generation_started = False
    try:
        assert process.stderr is not None and process.stdout is not None
        pipes = [process.stderr, process.stdout]
        output = bytearray()
        while time.monotonic() < deadline:
            if not pipes:
                break
            ready, _, _ = select.select(pipes, [], [], max(0, min(1.0, deadline - time.monotonic())))
            for pipe in ready:
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    pipes.remove(pipe)
                    continue
                if pipe is not process.stdout:
                    continue
                output.extend(chunk)
                if len(output) > 1 << 20:
                    raise ValueError("CLI cancellation probe returned unexpected output")
                if b'"type":"generation_started"' in output:
                    generation_started = True
                    os.killpg(process.pid, signal.SIGINT)
                    break
            if generation_started:
                break
        if not generation_started:
            raise ValueError("CLI cancellation probe did not reach generation")
        stdout, stderr = process.communicate(timeout=max(1.0, deadline - time.monotonic()))
    except BaseException:
        _stop_qualification_process(process)
        raise
    try:
        _events, envelope = vocello_cli_json.read_ndjson((bytes(output) + stdout).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        envelope = None
    if not isinstance(envelope, dict):
        envelope = {}
    error = envelope.get("error")
    if (process.returncode != 130 or b"forced exit" in stderr or not isinstance(error, dict)
            or envelope.get("ok") is not False or error.get("code") != "cancelled"
            or error.get("exitCode") != 130 or (error.get("detail") or {}).get("signal") != "SIGINT"):
        raise ValueError("CLI cancellation probe did not terminate cleanly")
    return {"generationStartObserved": True, "exitStatus": 130, "cleanupAcknowledged": True}


@contextmanager
def _qualification_workspace(report: Path | None, state: dict):
    """Retain operator QA audio and partial results on success, failure or interruption."""
    if report is None:
        with tempfile.TemporaryDirectory(prefix="vocello-cli-qualification-") as temporary:
            yield temporary
        return
    if report.exists() or report.is_symlink():
        raise ValueError("refusing to overwrite a CLI qualification report")
    report.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.mkdtemp(prefix="cli-qualification-", dir=report.parent.resolve())
    state["artifactDirectory"] = Path(temporary).name
    atomic_json(report, state)
    try:
        yield temporary
    except BaseException as error:
        state["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        state["failureType"] = type(error).__name__
        atomic_json(report, state)
        raise


def qualify_batch(binary: str, work: Path, runtime: Path, outputs: Path,
                  environment: dict[str, str], generation_runner: Callable) -> dict:
    """Two real items in ONE CLI process; keep the legacy success JSON unchanged."""
    lines = ["The first clip checks the packaged batch command.",
             "The second clip must complete in the same batch."]
    source = work / "batch-input.txt"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    destination = outputs / "batch"
    destination.mkdir()
    result = generation_runner([
        binary, "batch", "--mode", "custom", "--variant", "speed",
        "--speaker", "aiden", "--seed", "30000005", "--variation", "consistent",
        "--file", str(source), "--out-dir", str(destination),
        "--data-dir", str(runtime), "--json",
    ], work, environment, 900)
    if (result.get("mode") != "custom" or result.get("variant") != "speed"
            or result.get("modelID") != "pro_custom_speed"
            or type(result.get("count")) is not int or result["count"] != len(lines)
            or "schemaVersion" in result or not isinstance(result.get("items"), list)
            or len(result["items"]) != len(lines)):
        raise ValueError("CLI batch qualification lacks two successful rows")
    rows = []
    paths: set[Path] = set()
    for index, (item, text) in enumerate(zip(result["items"], lines, strict=True)):
        if (not isinstance(item, dict) or type(item.get("index")) is not int
                or item["index"] != index or item.get("text") != text
                or item.get("finishReason") != "eos"
                or type(item.get("durationSeconds")) not in (int, float)
                or not math.isfinite(item["durationSeconds"]) or item["durationSeconds"] <= 0
                or not isinstance(item.get("audioPath"), str)):
            raise ValueError("CLI batch qualification row identity is invalid")
        path = Path(item["audioPath"])
        if (path.is_symlink() or not path.is_file() or path.parent.resolve() != destination.resolve()
                or path.resolve() in paths or path.suffix != ".wav"):
            raise ValueError("CLI batch qualification output identity is invalid")
        paths.add(path.resolve())
        try:
            with wave.open(str(path), "rb") as audio:
                rate, frames = audio.getframerate(), audio.getnframes()
                if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or rate <= 0 or frames <= 0:
                    raise ValueError("invalid PCM shape")
                actual = 0
                audible = False
                while block := audio.readframes(4096):
                    actual += len(block)
                    audible |= any(block)
                if actual != frames * 2 or not audible or abs(frames / rate - item["durationSeconds"]) > 0.01:
                    raise ValueError("invalid PCM length, silence, or duration")
        except (wave.Error, EOFError, ValueError) as error:
            raise ValueError("CLI batch qualification PCM integrity failed") from error
        rows.append({"index": index, "durationSeconds": item["durationSeconds"],
                     "audioSHA256": digest(path), "audioBytes": path.stat().st_size,
                     "finishReason": "eos"})
    entries = list(destination.iterdir())
    if (len(entries) != len(paths) or any(path.is_symlink() for path in entries)
            or {path.resolve() for path in entries} != paths):
        raise ValueError("CLI batch qualification left unexpected output or staging")
    return {"status": "passed", "count": len(rows), "rows": rows,
            "requestedSeed": "30000005", "requestedStreaming": False,
            "oneCommandInvocation": True, "pcmIntegrity": "passed",
            "qualityEvidence": "engine-accepted; per-item QC not exposed by legacy batch JSON"}


def qualify(
    directory: Path,
    expected: dict,
    model_store: Path,
    clone_reference: Path,
    *,
    clone_transcript: Path | None = None,
    report: Path | None = None,
    generation_runner: Callable[[list[str], Path, dict[str, str], int], dict] = _run_qualification_generation,
    cancellation_runner: Callable[[list[str], Path, dict[str, str], int], dict] = _run_qualification_cancellation,
    launcher: Path | None = None,
) -> dict:
    """Run opt-in serial real-generation checks against a copied CLI payload.

    This is operator QA for an already-produced package. It is deliberately not
    called by deterministic packaging, CI, signing, notarization, or publication.
    `launcher` runs every command through an installed link (/usr/local/bin/vocello).
    """

    payload = verify(directory, expected)
    if model_store.is_symlink() or not model_store.is_dir():
        raise ValueError("CLI qualification model store must be a real directory")
    if clone_reference.is_symlink() or not clone_reference.is_file():
        raise ValueError("CLI qualification clone reference must be a real file")
    if clone_reference.stat().st_size <= 44 or clone_reference.stat().st_size > 100 * 1024**2:
        raise ValueError("CLI qualification clone reference is outside bounds")
    # PA-17: the CLI refuses clone generation without the invocation's recorded consent;
    # the operator supplies a test-owned reference they may clone.
    clone_arguments = ["--reference", str(clone_reference.resolve()), "--confirm-consent"]
    if clone_transcript is not None:
        if clone_transcript.is_symlink() or not clone_transcript.is_file() or clone_transcript.stat().st_size > 65536:
            raise ValueError("CLI qualification transcript must be a bounded real file")
        transcript = clone_transcript.read_text(encoding="utf-8").strip()
        if not transcript:
            raise ValueError("CLI qualification transcript is empty")
        clone_arguments += ["--transcript", transcript]

    binary = _launcher(directory, launcher)
    fixed_runs = (
        {
            "mode": "custom", "language": "english", "seed": "30000001",
            "modelID": "pro_custom_speed",
            "extra": ["--speaker", "aiden", "--delivery-cell", "neutral.normal"],
            "text": "This packaged voice is running entirely on this Mac.",
        },
        {
            "mode": "design", "language": "french", "seed": "30000002",
            "modelID": "pro_design_speed",
            "extra": ["--voice-brief", "Une voix française chaleureuse, claire et posée."],
            "text": "Cette vérification confirme que la voix française fonctionne localement.",
        },
        {
            "mode": "clone", "language": "english", "seed": "30000003",
            "modelID": "pro_clone_speed",
            "extra": clone_arguments,
            "text": "This clone qualification uses a test-owned reference clip.",
        },
    )

    runs: list[dict] = []
    state = {
        "schemaVersion": 2, "status": "running", "release": payload["release"],
        "manifestSHA256": digest(directory / MANIFEST), "runs": runs,
        "serialExecution": True, "publicationAuthority": "none",
    }
    with _qualification_workspace(report, state) as temporary:
        work = Path(temporary) / "unrelated working folder"
        runtime = Path(temporary) / "isolated runtime"
        outputs = Path(temporary) / "qualification outputs"
        work.mkdir()
        runtime.mkdir()
        outputs.mkdir()
        (runtime / "models").symlink_to(model_store.resolve(), target_is_directory=True)
        environment = _qualification_environment(temporary)
        for specification in fixed_runs:
            state["stage"] = specification["mode"]
            if report:
                atomic_json(report, state)
            output = outputs / f"{specification['mode']}.wav"
            argv = [
                binary, "generate", "--mode", specification["mode"],
                "--variant", "speed", "--language", specification["language"],
                "--seed", specification["seed"], "--variation", "consistent",
                "--text", specification["text"], "--out", str(output),
                "--data-dir", str(runtime), "--json", *specification["extra"],
            ]
            result = generation_runner(argv, work, environment, 900)
            reported = Path(str(result.get("audioPath", ""))).resolve()
            header = b""
            if output.is_file():
                with output.open("rb") as stream:
                    header = stream.read(12)
            if (
                reported != output.resolve()
                or not output.is_file()
                or output.stat().st_size <= 44
                or header[:4] != b"RIFF"
                or header[8:12] != b"WAVE"
            ):
                raise ValueError("CLI qualification output identity is invalid")
            qc = result.get("audioQC")
            if not isinstance(qc, dict) or qc.get("verdict") != "pass":
                raise ValueError("CLI qualification output lacks a passing QC verdict")
            if (
                result.get("mode") != specification["mode"]
                or result.get("variant") != "speed"
                or result.get("finalModelLanguage") != specification["language"]
                or result.get("modelID") != specification["modelID"]
                or type(result.get("durationSeconds")) not in (int, float)
                or not math.isfinite(result["durationSeconds"])
                or result["durationSeconds"] <= 0
                or result.get("finishReason") != "eos"
            ):
                raise ValueError("CLI qualification request/result identity mismatch")
            runs.append({
                "mode": specification["mode"],
                "modelID": result.get("modelID"),
                "language": result.get("finalModelLanguage"),
                "requestedSeed": specification["seed"],
                "requestedStreaming": True,
                "durationSeconds": result["durationSeconds"],
                "finishReason": result.get("finishReason"),
                "audioQCVerdict": qc["verdict"],
                "audioSHA256": digest(output),
                "audioBytes": output.stat().st_size,
            })
            if report:
                atomic_json(report, state)

        state["stage"] = "batch"
        if report:
            atomic_json(report, state)
        state["batch"] = qualify_batch(binary, work, runtime, outputs, environment, generation_runner)
        state["stage"] = "cancellation"
        if report:
            atomic_json(report, state)
        cancellation_output = outputs / "cancelled.wav"
        # Long enough to be interrupted mid-take, within the single-take limit the CLI enforces.
        long_text = " ".join(["The cancellation probe remains intentionally unfinished."] * 15)
        cancellation = cancellation_runner([
            binary, "generate", "--mode", "custom", "--variant", "speed",
            "--speaker", "aiden", "--language", "english", "--seed", "30000004",
            "--variation", "consistent", "--text", long_text,
            "--out", str(cancellation_output), "--data-dir", str(runtime), "--ndjson",
        ], work, environment, 900)
        # Qualification observes cleanup; it must never perform it for the CLI.
        if (cancellation_output.exists() or cancellation_output.is_symlink()
                or list(outputs.glob(".cancelled.*.tmp.wav"))
                or cancellation.get("exitStatus") != 130
                or cancellation.get("cleanupAcknowledged") is not True):
            state["cancellation"] = cancellation
            raise ValueError("CLI cancellation left output/staging or lacks cleanup acknowledgement")
        cancellation["outputAbsent"] = True
        cancellation["hostCleanupPerformed"] = False
        state["cancellation"] = cancellation
        state["stage"] = "failure-exits"
        if report:
            atomic_json(report, state)

        # Stable failure exits are part of the public CLI contract and must not
        # depend on a model launch or a repository checkout.
        command([binary, "unknown-package-qualification-command"], work, environment, expected=2)
        command([
            binary, "generate", "--mode", "invalid", "--text", "Invalid mode fixture.",
        ], work, environment, expected=2)

    encoded = json.dumps(runs, sort_keys=True, separators=(",", ":")).encode()
    result = {
        **state,
        "status": "passed",
        "stage": "complete",
        "release": payload["release"],
        "manifestSHA256": digest(directory / MANIFEST),
        "modelStore": "operator-provided-existing",
        "cloneReference": {
            "sha256": digest(clone_reference),
            "bytes": clone_reference.stat().st_size,
            "transcriptSHA256": digest(clone_transcript) if clone_transcript else None,
        },
        "runs": runs,
        "runsDigest": hashlib.sha256(encoded).hexdigest(),
        "cancellation": cancellation,
        "failureExitChecks": {"unknownCommand": 2, "invalidMode": 2},
        "serialExecution": True,
        "publicationAuthority": "none",
    }
    if report:
        atomic_json(report, result)
    return result


# Installer package ---------------------------------------------------------------------

# Every element a Distribution may hold, as written here or as productbuild rewrites it, with
# the attributes each may carry. Installer evaluates some attributes as JavaScript (`active` on
# a pkg-ref, `selected` or `enabled` on a choice, `script` on a check), so none of those is here.
DISTRIBUTION_ATTRIBUTES: dict[str, frozenset[str]] = {
    "installer-gui-script": frozenset({"minSpecVersion", "authoringTool", "authoringToolVersion",
                                       "authoringToolBuild"}),
    "title": frozenset(),
    "readme": frozenset({"file"}),
    "license": frozenset({"file"}),
    "options": frozenset({"customize", "require-scripts", "hostArchitectures"}),
    "domains": frozenset({"enable_anywhere", "enable_currentUserHome", "enable_localSystem"}),
    "volume-check": frozenset(),
    "allowed-os-versions": frozenset(),
    "os-version": frozenset({"min", "before"}),  # check_distribution then allows exactly `min`
    "choices-outline": frozenset(),
    "line": frozenset({"choice"}),
    "choice": frozenset({"id", "visible", "title", "description"}),
    "pkg-ref": frozenset({"id", "version", "onConclusion", "installKBytes", "updateKBytes", "auth",
                          "packageIdentifier"}),
    "bundle-version": frozenset(),
    "bundle": frozenset({"id", "path", "CFBundleShortVersionString", "CFBundleVersion", "SourceVersion"}),
}
MACOS_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


def parse_minimum_os(load_commands: str) -> str:
    """The macOS minimum in `otool -l` output: exactly one LC_BUILD_VERSION, for macOS."""
    found: list[dict[str, str]] = []
    lines = load_commands.splitlines()
    for index, line in enumerate(lines):
        if line.split() != ["cmd", "LC_BUILD_VERSION"]:
            continue
        fields: dict[str, str] = {}
        for row in lines[index + 1:]:
            parts = row.split()
            if not parts or parts[0] in {"Load", "cmd"}:
                break
            if len(parts) == 2:
                fields.setdefault(parts[0], parts[1])
        found.append(fields)
    if (len(found) != 1 or found[0].get("platform") not in {"1", "MACOS", "macos"}
            or not MACOS_VERSION.fullmatch(found[0].get("minos", ""))):
        raise ValueError("CLI executable lacks exactly one macOS minimum version")
    return found[0]["minos"]


def binary_minimum_os(binary: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="vocello-cli-minos-") as temporary:
        return parse_minimum_os(command(["/usr/bin/otool", "-l", str(binary)], Path(temporary),
                                        _qualification_environment(temporary)))


def _bundles(payload: Path) -> list[str]:
    return sorted(path.relative_to(payload).as_posix() for path in payload.rglob("*.bundle")
                  if path.is_dir() and not path.is_symlink())


def _bundle_identifiers(payload: Path) -> dict[str, str]:
    identifiers = {}
    for name in _bundles(payload):
        info = payload / name / "Contents/Info.plist"
        if info.is_symlink() or not info.is_file() or info.stat().st_size > 1024**2:
            raise ValueError("CLI resource bundle lacks a bounded Info.plist")
        identifier = plistlib.loads(info.read_bytes()).get("CFBundleIdentifier")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("CLI resource bundle lacks an identifier")
        identifiers[name] = identifier
    return identifiers


def component_plist(payload: Path) -> bytes:
    """pkgbuild's component list: every bundle stays where it is and replaces only itself.

    The Mac app ships bundles with the same identifiers; a relocatable bundle would let
    Installer find one of those and "upgrade" it in place instead of installing here.
    """
    bundles = _bundles(payload)
    if not set(BUNDLES) <= set(bundles):
        raise ValueError("CLI resource bundle is missing")
    return plistlib.dumps([{"RootRelativeBundlePath": name, "BundleIsRelocatable": False,
                            "BundleIsVersionChecked": False, "BundleHasStrictIdentifier": True,
                            "BundleOverwriteAction": "upgrade"} for name in bundles], sort_keys=True)


def distribution_xml(version: str, minimum_os: str) -> bytes:
    """The product's Distribution: no JavaScript, arm64 only, the startup disk, one hidden package."""
    script = ElementTree.Element("installer-gui-script", {"minSpecVersion": "2"})
    ElementTree.SubElement(script, "title").text = PKG_TITLE
    ElementTree.SubElement(script, "readme", {"file": "README.txt"})
    ElementTree.SubElement(script, "license", {"file": "LICENSE.txt"})
    ElementTree.SubElement(script, "options", {"customize": "never", "require-scripts": "false",
                                               "hostArchitectures": "arm64"})
    ElementTree.SubElement(script, "domains", {"enable_anywhere": "false", "enable_currentUserHome": "false",
                                               "enable_localSystem": "true"})
    versions = ElementTree.SubElement(ElementTree.SubElement(script, "volume-check"), "allowed-os-versions")
    ElementTree.SubElement(versions, "os-version", {"min": minimum_os})
    ElementTree.SubElement(ElementTree.SubElement(script, "choices-outline"), "line", {"choice": PKG_IDENTIFIER})
    choice = ElementTree.SubElement(script, "choice", {"id": PKG_IDENTIFIER, "visible": "false", "title": PKG_TITLE})
    ElementTree.SubElement(choice, "pkg-ref", {"id": PKG_IDENTIFIER})
    reference = ElementTree.SubElement(script, "pkg-ref", {"id": PKG_IDENTIFIER, "version": version,
                                                          "onConclusion": "none"})
    reference.text = COMPONENT
    ElementTree.indent(script)
    return ElementTree.tostring(script, encoding="utf-8", xml_declaration=True) + b"\n"


def _refuse_document_type(*_: object) -> NoReturn:
    raise ValueError("CLI installer XML is oversized or declares entities")


def parse_xml(text: str) -> ElementTree.Element:
    """Parse a document with an expat parser that refuses any document type or entity declaration."""
    builder = ElementTree.TreeBuilder()
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse_document_type
    parser.EntityDeclHandler = _refuse_document_type
    parser.UnparsedEntityDeclHandler = _refuse_document_type
    parser.ExternalEntityRefHandler = _refuse_document_type
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.buffer_text = True
    try:
        # A str is parsed as UTF-8 whatever encoding its declaration names.
        parser.Parse(text, True)
    except expat.ExpatError as error:
        raise ValueError("CLI installer XML is malformed") from error
    return builder.close()


def _xml(data: bytes, tag: str) -> ElementTree.Element:
    if len(data) > 1024**2:
        raise ValueError("CLI installer XML is oversized or declares entities")
    # Plain UTF-8, as pkgbuild and productbuild write it: no byte-order mark, no NUL, no other
    # encoding, so the text checked below is the text the parser reads.
    if data.startswith(codecs.BOM_UTF8) or b"\0" in data:
        raise ValueError("CLI installer XML is not plain UTF-8")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("CLI installer XML is not plain UTF-8") from error
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("CLI installer XML is oversized or declares entities")
    element = parse_xml(text)
    if element.tag != tag:
        raise ValueError("CLI installer XML has an unexpected root element")
    return element


def check_distribution(data: bytes, version: str) -> str:
    """Check a Distribution as written or as productbuild rewrote it; return its minimum macOS."""
    script = _xml(data, "installer-gui-script")
    nodes = list(script.iter())
    if any(node.tag == "script" or "script" in node.attrib or node.tag not in DISTRIBUTION_ATTRIBUTES
           or not set(node.attrib) <= DISTRIBUTION_ATTRIBUTES[node.tag] for node in nodes):
        raise ValueError("CLI installer Distribution must be script-free")
    options = script.findall("options")
    if len(options) != 1 or options[0].get("hostArchitectures") != "arm64":
        raise ValueError("CLI installer Distribution must allow only arm64 hosts")
    domains = script.findall("domains")
    if len(domains) != 1 or domains[0].attrib != {"enable_anywhere": "false", "enable_currentUserHome": "false",
                                                  "enable_localSystem": "true"}:
        raise ValueError("CLI installer Distribution must install only on the startup disk")
    checks = script.findall("volume-check")
    allowed = list(checks[0]) if len(checks) == 1 else []
    versions = list(allowed[0]) if len(allowed) == 1 and allowed[0].tag == "allowed-os-versions" else []
    if (len(versions) != 1 or versions[0].tag != "os-version" or set(versions[0].attrib) != {"min"}
            or not MACOS_VERSION.fullmatch(versions[0].get("min", ""))):
        raise ValueError("CLI installer Distribution lacks exactly one minimum macOS")
    outline = script.findall("choices-outline")
    lines = list(outline[0]) if len(outline) == 1 else []
    choices = script.findall("choice")
    if (options[0].attrib != {"customize": "never", "require-scripts": "false", "hostArchitectures": "arm64"}
            or len(lines) != 1 or len(choices) != 1 or lines[0].tag != "line" or list(lines[0])
            or lines[0].attrib != {"choice": choices[0].get("id")} or choices[0].get("visible") != "false"
            or not set(choices[0].attrib) <= {"id", "visible", "title", "description"}
            or [(child.tag, child.attrib) for child in choices[0]] != [("pkg-ref", {"id": PKG_IDENTIFIER})]):
        raise ValueError("CLI installer Distribution must offer exactly one hidden, fixed choice")
    references = script.findall("pkg-ref")
    carriers = [node for node in references if (node.text or "").strip()]
    if (any(node.get("id") != PKG_IDENTIFIER for node in script.iter("pkg-ref")) or len(carriers) != 1
            or (carriers[0].text or "").strip() not in {COMPONENT, "#" + COMPONENT}
            or carriers[0].get("version") != version or carriers[0].get("onConclusion") != "none"
            or any(node is not carriers[0] and ("version" in node.attrib
                                                or any(child.tag != "bundle-version" for child in node))
                   for node in references)):
        raise ValueError("CLI installer Distribution must reference one package at the release version")
    titles = script.findall("title")
    if (len(titles) != 1 or titles[0].text != PKG_TITLE
            or [node.attrib for node in script.findall("readme")] != [{"file": "README.txt"}]
            or [node.attrib for node in script.findall("license")] != [{"file": "LICENSE.txt"}]):
        raise ValueError("CLI installer Distribution lacks its title, readme or license")
    return versions[0].attrib["min"]


def check_package_info(data: bytes, version: str, bundles: dict[str, str]) -> None:
    """The component's identity, its non-relocatable bundles and its two scripts."""
    info = _xml(data, "pkg-info")
    if (info.get("identifier") != PKG_IDENTIFIER or info.get("version") != version
            or info.get("install-location") != INSTALL_LOCATION or info.get("auth") != "root"):
        raise ValueError("CLI installer package identity mismatch")
    # pkgbuild always writes <relocate/>; a bundle inside it is what Installer would relocate.
    if info.get("relocatable", "false") != "false" or any(len(node) for node in info.iter("relocate")):
        raise ValueError("CLI installer package relocates bundles")
    declared = {node.get("path"): node.get("id") for node in info.findall("bundle")}
    if len(info.findall("bundle")) != len(bundles) or declared != {"./" + path: name for path, name in bundles.items()}:
        raise ValueError("CLI installer package bundles differ from the payload")
    identifiers = set(bundles.values())
    for tag in ("strict-identifier", "upgrade-bundle"):
        nodes = info.findall(tag)
        if (len(nodes) != 1 or any(child.tag != "bundle" for child in nodes[0])
                or {child.get("id") for child in nodes[0]} != identifiers):
            raise ValueError("CLI installer package bundle policy mismatch")
    if any(len(node) for tag in ("bundle-version", "update-bundle", "atomic-update-bundle")
           for node in info.findall(tag)):
        raise ValueError("CLI installer package bundle policy mismatch")
    scripts = info.findall("scripts")
    if len(scripts) != 1 or sorted((child.tag, child.get("file")) for child in scripts[0]) != [
            ("postinstall", "./postinstall"), ("preinstall", "./preinstall")]:
        raise ValueError("CLI installer package must run exactly its preinstall and postinstall")


def bom_entries(bom: Path, cwd: Path, environment: dict[str, str]) -> dict[str, tuple[int, int, int]]:
    """`lsbom -p fugm`: path, owner, group and mode of everything the package installs."""
    entries: dict[str, tuple[int, int, int]] = {}
    for line in command(["/usr/bin/lsbom", "-p", "fugm", str(bom)], cwd, environment).splitlines():
        fields = line.split("\t")
        if (len(fields) != 4 or not fields[0] or fields[0] in entries
                or not all(re.fullmatch(r"\d{1,10}", value) for value in fields[1:3])
                or not re.fullmatch(r"[0-7]{1,7}", fields[3])):
            raise ValueError("CLI installer Bom listing is malformed")
        entries[fields[0]] = (int(fields[1]), int(fields[2]), int(fields[3], 8))
        if len(entries) > 6000:
            raise ValueError("CLI installer Bom exceeds bounds")
    return entries


def check_bom(entries: dict[str, tuple[int, int, int]], payload: Path) -> None:
    expected = {".": True, **{"./" + path.relative_to(payload).as_posix(): path.is_dir()
                             for path in payload.rglob("*")}}
    if set(entries) != set(expected):
        raise ValueError("CLI installer Bom differs from the payload")
    if any(uid != 0 or gid != 0 for uid, gid, _ in entries.values()):
        raise ValueError("CLI installer Bom must install everything as root:wheel")
    if any(mode & 0o7000 for _, _, mode in entries.values()):
        raise ValueError("CLI installer Bom must not set setuid, setgid or sticky bits")
    for path, (_, _, mode) in entries.items():
        wanted = 0o40755 if expected[path] else 0o100755 if path == "./vocello" else 0o100644
        if mode != wanted:
            raise ValueError("CLI installer Bom modes must be 0755 folders, 0644 files and one 0755 vocello")


def check_signature(artifact: Path, signature: str, notarization: str, cwd: Path,
                    environment: dict[str, str]) -> None:
    """Confirm the claimed signature and stapled ticket; never record the signing team."""
    if signature == "unsigned":
        listing = command(["/usr/sbin/pkgutil", "--check-signature", str(artifact)], cwd, environment, expected=1)
        if "Status: no signature" not in [line.strip() for line in listing.splitlines()]:
            raise ValueError("CLI installer package claimed unsigned but carries a signature")
    else:
        listing = command(["/usr/sbin/pkgutil", "--check-signature", str(artifact)], cwd, environment)
        lines = [line.strip() for line in listing.splitlines()]
        if ("Status: signed by a developer certificate issued by Apple for distribution" not in lines
                or not any(line.startswith("1. Developer ID Installer: ") for line in lines)):
            raise ValueError("CLI installer package lacks a Developer ID Installer signature")
    if notarization == "stapled":
        command(["/usr/bin/xcrun", "stapler", "validate", str(artifact)], cwd, environment)


def _copy_payload(source: Path, target: Path) -> None:
    """Copy a sealed folder with install modes: folders 0755, files 0644, vocello 0755."""
    target.mkdir()
    target.chmod(0o755)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = target / relative
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            destination.mkdir()
            destination.chmod(0o755)
        elif stat.S_ISREG(info.st_mode):
            shutil.copyfile(path, destination)
            destination.chmod(0o755 if relative.as_posix() == "vocello" else 0o644)
        else:
            raise ValueError("CLI payload contains a link or special file")


@contextmanager
def _pkg_workspace(work: Path | None, output: Path) -> Iterator[Path]:
    if work is not None:
        work.mkdir(parents=True)
        work.chmod(0o755)
        yield work.resolve()
        return
    with tempfile.TemporaryDirectory(prefix=".cli-pkg-work-", dir=output.parent) as temporary:
        yield Path(temporary).resolve()


def pkg(directory: Path, release: dict, output: Path, *, work: Path | None = None,
        minimum_os: str = "26.0", root: Path = ROOT) -> dict:
    """Build the unsigned product archive that installs the sealed folder at INSTALL_LOCATION.

    The payload is the sealed folder byte for byte; /usr/local/bin and the zsh directory
    stay out of it (postinstall links into them). release.sh signs the result.
    """
    if output.exists() or output.is_symlink():
        raise ValueError("refusing to overwrite an existing CLI installer package")
    if output.suffix != ".pkg" or not MACOS_VERSION.fullmatch(minimum_os):
        raise ValueError("CLI installer package needs a .pkg output and a minimum macOS version")
    if work is not None and (work.exists() or work.is_symlink()):
        raise ValueError("refusing to reuse an existing CLI installer work folder")
    payload = verify(directory, release)
    if binary_minimum_os(directory / "vocello") != minimum_os:
        raise ValueError("CLI executable minimum macOS differs from the package's")
    version = release["marketingVersion"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with _pkg_workspace(work, output) as base:
        staged = base / "root"
        _copy_payload(directory, staged)
        verify(staged, release)
        (base / "component.plist").write_bytes(component_plist(staged))
        scripts = base / "scripts"
        scripts.mkdir()
        for name, source in PKG_SCRIPT_SOURCES.items():
            shutil.copyfile(root / source, scripts / name)
            (scripts / name).chmod(0o755)
        resources = base / "resources"
        resources.mkdir()
        shutil.copyfile(staged / "README.txt", resources / "README.txt")
        shutil.copyfile(staged / "LICENSE", resources / "LICENSE.txt")
        (base / "Distribution.xml").write_bytes(distribution_xml(version, minimum_os))
        temporary = base / "tmp"
        temporary.mkdir()
        environment = _qualification_environment(str(temporary))
        command(["/usr/bin/pkgbuild", "--root", str(staged), "--install-location", INSTALL_LOCATION,
                 "--identifier", PKG_IDENTIFIER, "--version", version, "--ownership", "recommended",
                 "--scripts", str(scripts), "--component-plist", str(base / "component.plist"),
                 str(base / COMPONENT)], base, environment, timeout=PKG_TOOL_TIMEOUT)
        with tempfile.TemporaryDirectory(prefix=".cli-pkg-", dir=output.parent) as partial:
            product = Path(partial) / output.name
            command(["/usr/bin/productbuild", "--distribution", str(base / "Distribution.xml"),
                     "--resources", str(resources), "--package-path", str(base), str(product)],
                    base, environment, timeout=PKG_TOOL_TIMEOUT)
            if product.is_symlink() or not product.is_file():
                raise ValueError("productbuild did not write the CLI installer package")
            os.replace(product, output)
    return {"schemaVersion": 1, "release": payload["release"], "manifestSHA256": digest(directory / MANIFEST),
            "package": {"identifier": PKG_IDENTIFIER, "version": version,
                        "installLocation": INSTALL_LOCATION, "minimumOS": minimum_os},
            "artifact": {"name": output.name, "bytes": output.stat().st_size, "sha256": digest(output)}}


def _read_small(path: Path, limit: int = 1024**2) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("CLI installer package file is missing, linked or oversized")
    return path.read_bytes()


def _exact_children(directory: Path, files: set[str], folders: set[str] | None = None, *,
                    extra_files: bool = False) -> None:
    """`directory` holds exactly these real files and folders (plus plain files, if allowed)."""
    folders = folders or set()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("CLI installer package folder is missing or linked")
    children = {path.name: path for path in directory.iterdir()}
    if not files | folders <= set(children) or (not extra_files and set(children) != files | folders) or any(
            path.is_symlink() or not (path.is_dir() if name in folders else path.is_file())
            for name, path in children.items()):
        raise ValueError("CLI installer package layout is unexpected")


def _root_free_install(payload: Path, scripts: Path, artifact: Path, release: dict) -> None:
    """Install, upgrade and refuse under a temporary root, the way Installer runs the scripts."""
    with tempfile.TemporaryDirectory(prefix="vocello-cli-pkg-install-") as temporary:
        base = Path(temporary).resolve()
        environment = _qualification_environment(str(base))
        work = base / "unrelated working folder"
        work.mkdir()
        volume = base / "root with spaces"
        volume.mkdir()
        lib = volume / INSTALL_LOCATION.lstrip("/")

        def run(name: str, target: Path, expected: int = 0) -> None:
            # Installer's arguments: package, install location, target volume, startup disk.
            command([str(scripts / name), str(artifact), str(target / INSTALL_LOCATION.lstrip("/")),
                     str(target), "/"], work, environment, expected)

        def install() -> None:
            run("preinstall", volume)
            lib.parent.mkdir(parents=True, exist_ok=True)
            command(["/usr/bin/ditto", str(payload), str(lib)], work, environment, timeout=PKG_TOOL_TIMEOUT)
            run("postinstall", volume)

        def check_installed() -> None:
            verify(lib, release)
            for link, target in PKG_LINKS.items():
                path = volume / link
                if (not path.is_symlink() or os.readlink(path) != target
                        or path.resolve() != (lib / Path(target).name).resolve()):
                    raise ValueError("CLI installer links are not relative links into the installed folder")

        install()
        check_installed()
        smoke(lib, release, launcher=volume / "usr/local/bin/vocello")
        stale = lib / "stale-file-from-an-older-version.txt"
        stale.write_text("stale\n", encoding="utf-8")
        install()
        if stale.exists() or stale.is_symlink():
            raise ValueError("CLI installer upgrade kept a stale payload file")
        check_installed()

        decoy = base / "decoy folder with a manifest"
        decoy.mkdir()
        (decoy / MANIFEST).write_text("{}\n", encoding="utf-8")
        linked = base / "volume with a linked folder"
        (linked / "usr/local/lib").mkdir(parents=True)
        (linked / INSTALL_LOCATION.lstrip("/")).symlink_to(decoy, target_is_directory=True)
        run("preinstall", linked, expected=1)
        if not (decoy / MANIFEST).is_file() or not (linked / INSTALL_LOCATION.lstrip("/")).is_symlink():
            raise ValueError("CLI installer followed a linked install folder")
        foreign = base / "volume with a foreign folder"
        (foreign / INSTALL_LOCATION.lstrip("/")).mkdir(parents=True)
        kept = foreign / INSTALL_LOCATION.lstrip("/") / "notes.txt"
        kept.write_text("not the CLI\n", encoding="utf-8")
        run("preinstall", foreign, expected=1)
        if not kept.is_file():
            raise ValueError("CLI installer removed a folder it did not install")


def pkg_verify(expanded: Path, artifact: Path, release: dict, manifest_sha256: str, *, signature: str,
               notarization: str, report: Path, root_free_install: bool = False, root: Path = ROOT) -> dict:
    """Check a `pkgutil --expand-full` tree of the product archive and write its report."""
    if report.exists() or report.is_symlink():
        raise ValueError("refusing to overwrite a CLI installer verification report")
    if (signature not in PKG_SIGNATURES or notarization not in PKG_NOTARIZATIONS
            or (notarization == "stapled" and signature != "developer-id-installer")):
        raise ValueError("CLI installer signature/notarization claim is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("invalid CLI manifest digest")
    if artifact.is_symlink() or not artifact.is_file() or not artifact.name.endswith("-cli.pkg"):
        raise ValueError("CLI installer artifact must be a real -cli.pkg file")
    # A stapled ticket may surface as a plain file beside the product's own entries; the
    # Distribution checked below references nothing but README, LICENSE and the component.
    _exact_children(expanded, {"Distribution"}, {"Resources", COMPONENT}, extra_files=notarization == "stapled")
    component = expanded / COMPONENT
    _exact_children(component, {"Bom", "PackageInfo"}, {"Payload", "Scripts"})
    _exact_children(expanded / "Resources", {"README.txt", "LICENSE.txt"})
    _exact_children(component / "Scripts", set(PKG_SCRIPT_SOURCES))
    version = release["marketingVersion"]

    minimum_os = check_distribution(_read_small(expanded / "Distribution"), version)
    payload_folder = component / "Payload"
    payload = verify(payload_folder, release)
    if digest(payload_folder / MANIFEST) != manifest_sha256:
        raise ValueError("CLI installer payload manifest differs from the sealed folder's")
    if binary_minimum_os(payload_folder / "vocello") != minimum_os:
        raise ValueError("CLI installer minimum macOS differs from the executable's")
    if (_read_small(expanded / "Resources/README.txt") != (payload_folder / "README.txt").read_bytes()
            or _read_small(expanded / "Resources/LICENSE.txt") != (payload_folder / "LICENSE").read_bytes()):
        raise ValueError("CLI installer readme or license differs from the payload")
    check_package_info(_read_small(component / "PackageInfo"), version, _bundle_identifiers(payload_folder))
    for name, source in PKG_SCRIPT_SOURCES.items():
        script = component / "Scripts" / name
        if _read_small(script) != (root / source).read_bytes() or not os.access(script, os.X_OK):
            raise ValueError("CLI installer scripts differ from the repository source")
    for name, source in ((UNINSTALLER, UNINSTALLER_SOURCE), (COMPLETION, COMPLETION_SOURCE)):
        if (payload_folder / name).read_bytes() != (root / source).read_bytes():
            raise ValueError("CLI payload helpers differ from the repository source")
    with tempfile.TemporaryDirectory(prefix="vocello-cli-pkg-verify-") as temporary:
        environment = _qualification_environment(temporary)
        check_bom(bom_entries(component / "Bom", Path(temporary), environment), payload_folder)
        check_signature(artifact, signature, notarization, Path(temporary), environment)
    checks: list[str] = list(PKG_CHECKS)
    if root_free_install:
        _root_free_install(payload_folder, component / "Scripts", artifact, release)
        checks.extend(PKG_INSTALL_CHECKS)
    result = {
        "schemaVersion": 1, "status": "passed", "release": payload["release"],
        "manifestSHA256": manifest_sha256, "fileCount": len(payload["files"]),
        "package": {"identifier": PKG_IDENTIFIER, "version": version, "installLocation": INSTALL_LOCATION,
                    "hostArchitectures": ["arm64"], "minimumOS": minimum_os, "relocatableBundles": 0,
                    "scriptDigests": {name: digest(component / "Scripts" / name) for name in PKG_SCRIPT_SOURCES}},
        "signature": signature, "notarization": notarization, "installTest": "not-performed",
        "checks": checks, "generationQualification": "not-performed",
        "artifact": {"name": artifact.name, "bytes": artifact.stat().st_size, "sha256": digest(artifact)},
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(report, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "seal", "verify", "smoke", "qualify", "pkg", "pkg-verify"))
    parser.add_argument("--directory", type=Path, help="the sealed CLI folder (every command but pkg-verify)")
    parser.add_argument("--products", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--build")
    parser.add_argument("--commit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--model-store", type=Path)
    parser.add_argument("--clone-reference", type=Path)
    parser.add_argument("--clone-transcript-file", type=Path)
    parser.add_argument("--launcher", type=Path,
                        help="smoke/qualify: run every command through this absolute link to the folder's vocello")
    parser.add_argument("--output", type=Path, help="pkg: the product archive to write (never overwritten)")
    parser.add_argument("--work", type=Path, help="pkg: a new folder to build in, kept afterwards")
    parser.add_argument("--minimum-os", default="26.0", help="pkg: must equal the executable's LC_BUILD_VERSION minos")
    parser.add_argument("--expanded", type=Path, help="pkg-verify: the `pkgutil --expand-full` tree of --artifact")
    parser.add_argument("--manifest-sha256", help="pkg-verify: SHA-256 of the sealed folder's package-manifest.json")
    parser.add_argument("--signature", choices=PKG_SIGNATURES)
    parser.add_argument("--notarization", choices=PKG_NOTARIZATIONS)
    parser.add_argument("--root-free-install", action="store_true",
                        help="pkg-verify: also install, upgrade and smoke under a temporary root")
    args = parser.parse_args()
    if args.command != "pkg-verify" and args.directory is None:
        parser.error("the following arguments are required: --directory")
    try:
        if args.command == "stage":
            if args.products is None:
                raise ValueError("stage requires products")
            stage(args.products, args.directory)
        else:
            if not all((args.version, args.build, args.commit)):
                raise ValueError("exact version/build/commit are required")
            release = identity(args.version, args.build, args.commit)
            if args.command == "qualify":
                if not args.model_store or not args.clone_reference or not args.report:
                    raise ValueError("qualification requires model store, clone reference, and report")
                result = qualify(
                    args.directory, release,
                    args.model_store, args.clone_reference,
                    clone_transcript=args.clone_transcript_file,
                    report=args.report,
                    launcher=args.launcher,
                )
            elif args.command == "pkg":
                if args.output is None:
                    raise ValueError("pkg requires an output")
                pkg(args.directory, release, args.output, work=args.work, minimum_os=args.minimum_os)
            elif args.command == "pkg-verify":
                if not all((args.expanded, args.artifact, args.manifest_sha256, args.signature,
                            args.notarization, args.report)):
                    raise ValueError("pkg-verify requires expanded, artifact, manifest digest, claims and report")
                pkg_verify(args.expanded, args.artifact, release, args.manifest_sha256,
                           signature=args.signature, notarization=args.notarization, report=args.report,
                           root_free_install=args.root_free_install)
            else:
                if args.command == "smoke":
                    result = smoke(args.directory, release, launcher=args.launcher)
                else:
                    result = {"seal": seal, "verify": verify}[args.command](args.directory, release)
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
