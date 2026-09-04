#!/usr/bin/env python3
"""Stage/seal and smoke-check the CLI payload used by the existing macOS release lane.

Model generation runs only through the opt-in qualify command. No model installation,
publication, or shell-profile modification. The manifest is an integrity inventory,
not independent signing or quality-promotion authority.
"""
from __future__ import annotations

import argparse
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
import tempfile
import time
from typing import Callable

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
    if process.returncode != 0:
        raise ValueError("CLI qualification generation failed")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError("CLI qualification generation returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("CLI qualification generation returned a non-object")
    return payload


def _stop_qualification_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


def _run_qualification_cancellation(
    argv: list[str], cwd: Path, environment: dict[str, str], timeout: int = 900
) -> dict:
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
        pending = b""
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
                if pipe is process.stdout:
                    output.extend(chunk)
                    if len(output) > 65536:
                        raise ValueError("CLI cancellation probe returned unexpected output")
                    continue
                pending = (pending + chunk)[-65536:]
                if b"generating (" in pending:
                    generation_started = True
                    os.killpg(process.pid, signal.SIGINT)
                    break
            if generation_started:
                break
        if not generation_started:
            raise ValueError("CLI cancellation probe did not reach generation")
        stdout, _stderr = process.communicate(timeout=max(1.0, deadline - time.monotonic()))
    except BaseException:
        _stop_qualification_process(process)
        raise
    if (process.returncode != 130 or output.strip() or stdout.strip()
            or b"Cancelled; command cleanup completed." not in _stderr
            or b"forced exit" in _stderr):
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
) -> dict:
    """Run opt-in serial real-generation checks against a copied CLI payload.

    This is operator QA for an already-produced package. It is deliberately not
    called by deterministic packaging, CI, signing, notarization, or publication.
    """

    payload = verify(directory, expected)
    if model_store.is_symlink() or not model_store.is_dir():
        raise ValueError("CLI qualification model store must be a real directory")
    if clone_reference.is_symlink() or not clone_reference.is_file():
        raise ValueError("CLI qualification clone reference must be a real file")
    if clone_reference.stat().st_size <= 44 or clone_reference.stat().st_size > 100 * 1024**2:
        raise ValueError("CLI qualification clone reference is outside bounds")
    clone_arguments = ["--reference", str(clone_reference.resolve())]
    if clone_transcript is not None:
        if clone_transcript.is_symlink() or not clone_transcript.is_file() or clone_transcript.stat().st_size > 65536:
            raise ValueError("CLI qualification transcript must be a bounded real file")
        transcript = clone_transcript.read_text(encoding="utf-8").strip()
        if not transcript:
            raise ValueError("CLI qualification transcript is empty")
        clone_arguments += ["--transcript", transcript]

    binary = str((directory / "vocello").resolve())
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
        "schemaVersion": 1, "status": "running", "release": payload["release"],
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

        state["stage"] = "cancellation"
        if report:
            atomic_json(report, state)
        cancellation_output = outputs / "cancelled.wav"
        long_text = " ".join(["The cancellation probe remains intentionally unfinished."] * 80)
        cancellation = cancellation_runner([
            binary, "generate", "--mode", "custom", "--variant", "speed",
            "--speaker", "aiden", "--language", "english", "--seed", "30000004",
            "--variation", "consistent", "--text", long_text,
            "--out", str(cancellation_output), "--data-dir", str(runtime), "--json",
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
        ], work, environment, expected=1)

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
        "failureExitChecks": {"unknownCommand": 2, "invalidMode": 1},
        "serialExecution": True,
        "publicationAuthority": "none",
    }
    if report:
        atomic_json(report, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "seal", "verify", "smoke", "qualify"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--products", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--build")
    parser.add_argument("--commit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--model-store", type=Path)
    parser.add_argument("--clone-reference", type=Path)
    parser.add_argument("--clone-transcript-file", type=Path)
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
            if args.command == "qualify":
                if not args.model_store or not args.clone_reference or not args.report:
                    raise ValueError("qualification requires model store, clone reference, and report")
                result = qualify(
                    args.directory, release,
                    args.model_store, args.clone_reference,
                    clone_transcript=args.clone_transcript_file,
                    report=args.report,
                )
            else:
                action = {"seal": seal, "verify": verify, "smoke": smoke}[args.command]
                result = action(args.directory, release)
            if args.report and args.command != "qualify":
                if args.command != "smoke" or not args.artifact or not args.artifact.is_file():
                    raise ValueError("report requires a smoke check and its DMG artifact")
                else:
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
