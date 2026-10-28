#!/usr/bin/env python3
"""RF-38: package Vocello and its UI-test runner for BrowserStack App Automate, upload them and
read the results back, for the self-contained farm smoke test
(Tests/VocelloiOSUITests/VocelloiOSFarmSmokeUITests.swift).

`package` runs after scripts/farm_smoke.sh has built and staged the products. `upload` and
`results` are maintainer-run from a terminal: they use the maintainer's BrowserStack account, from
BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY or a hidden prompt, and `upload` spends its
minutes after an explicit confirmation. The account reaches curl only on its standard input and only
for https://api-cloud.browserstack.com; it is never printed, passed as an argument, left in curl's
environment or written down. The farm re-signs the app without `increased-memory-limit`, so every
result is clone-off exploratory smoke evidence only."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

API_HOSTNAME = "api-cloud.browserstack.com"
API_HOST = f"https://{API_HOSTNAME}"
API = f"{API_HOST}/app-automate/xcuitest/v2"
APP = "Vocello.app"
RUNNER = "VocelloiOSUITests-Runner.app"
TEST_BINARY = Path("PlugIns/VocelloiOSUITests.xctest/VocelloiOSUITests")
FARM_TEST_CLASS = b"VocelloiOSFarmSmokeUITests"
IPA = "Vocello.ipa"
SUITE = "VocelloiOSUITests-Runner.zip"
MANIFEST = "package.json"
LATEST_UPLOAD = "upload.json"
# BrowserStack's public App Automate list (2026-10-27): the only real iPhone 15 Pro class devices
# on an iOS that can install Vocello. The 15 Pro Max shares the 15 Pro's chip and memory.
DEFAULT_DEVICES = ("iPhone 15 Pro-27", "iPhone 15 Pro Max-26")
ONLY_TESTING = (
    "VocelloiOSUITests/VocelloiOSFarmSmokeUITests/testFarmSmokeJourney",
    "VocelloiOSUITests/VocelloiOSFarmSmokeUITests/testFarmTakeMemoryPeak",
)
RESULT_MARKERS = ("VOCELLO_FARM_SMOKE ", "VOCELLO_FARM_MEMORY ", "measured [")
CAVEAT = "BrowserStack re-signs the app without increased-memory-limit: clone-off exploratory smoke only"
CREDENTIAL = re.compile(r"^[A-Za-z0-9_.@+-]+$")
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
MSDOS_DIRECTORY = 0x10
STILL_RUNNING = 3

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class FarmError(RuntimeError):
    pass


def run_command(argv: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
    # curl gets the account on stdin only, never through an inherited BROWSERSTACK_* variable.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BROWSERSTACK_")}
    return subprocess.run(argv, input=input, capture_output=True, text=True, errors="replace",
                          env=environment, check=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_info(name: str, mode: int = 0o40755) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name.rstrip("/") + "/", date_time=ZIP_EPOCH)
    info.external_attr = ((mode & 0xFFFF) << 16) | MSDOS_DIRECTORY
    return info


def _zip_tree(archive: zipfile.ZipFile, source: Path, root: str) -> None:
    """Adds `source` under `root`, keeping modes and symlinks so the code signature survives."""

    def add(path: Path, name: str) -> None:
        mode = path.lstat().st_mode
        if path.is_symlink():
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, os.readlink(path))
        elif path.is_dir():
            archive.writestr(_directory_info(name, mode), b"")
        else:
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as src, archive.open(info, "w", force_zip64=True) as dst:
                shutil.copyfileobj(src, dst, 1 << 20)

    add(source, root)
    for directory, subdirectories, files in os.walk(source, followlinks=False):
        subdirectories.sort()
        base = Path(directory)
        for entry in subdirectories + sorted(files):
            path = base / entry
            add(path, f"{root}/{path.relative_to(source).as_posix()}")


def package(products: Path, root: Path, *, commit: str, dirty: bool, xcode: str, fingerprint: str,
            now: Callable[[], float] = time.time) -> Path:
    """Writes Vocello.ipa, the runner zip and package.json into a new directory under `root`.
    `products` holds the staged, signed Vocello.app and runner."""
    app, runner = products / APP, products / RUNNER
    if not app.is_dir() or not runner.is_dir():
        raise FarmError(f"the staged products are missing {APP} or {RUNNER}")
    test_binary = runner / TEST_BINARY
    if not test_binary.is_file() or FARM_TEST_CLASS not in test_binary.read_bytes():
        raise FarmError("the UI-test runner does not contain VocelloiOSFarmSmokeUITests")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise FarmError("the source commit must be a full git SHA")
    try:
        info = plistlib.loads((app / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise FarmError(f"cannot read {APP}'s Info.plist: {error}") from error

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now()))
    destination = root / f"{stamp}-{commit[:8]}"
    partial = root / f".partial-{destination.name}"
    if destination.exists():
        raise FarmError(f"{destination.name} already exists; package again in a second")
    root.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir()
    try:
        with zipfile.ZipFile(partial / IPA, "w") as ipa:
            ipa.writestr(_directory_info("Payload"), b"")
            _zip_tree(ipa, app, f"Payload/{APP}")
        with zipfile.ZipFile(partial / SUITE, "w") as suite:
            _zip_tree(suite, runner, RUNNER)
        manifest = {
            "schemaVersion": 1,
            "item": "RF-38",
            "createdAtUTC": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now())),
            "sourceCommit": commit,
            "dirtyTree": dirty,
            "buildInputsFingerprint": fingerprint,
            "xcode": xcode,
            "appVersion": info.get("CFBundleShortVersionString"),
            "appBuild": info.get("CFBundleVersion"),
            "appExecutableSha256": sha256(app / str(info.get("CFBundleExecutable", "Vocello"))),
            "files": {IPA: sha256(partial / IPA), SUITE: sha256(partial / SUITE)},
            "onlyTesting": list(ONLY_TESTING),
            "defaultDevices": list(DEFAULT_DEVICES),
            "caveat": CAVEAT,
        }
        (partial / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
        partial.rename(destination)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return destination


def credentials(environment: Mapping[str, str], ask: Callable[[str], str] = input,
                ask_secret: Callable[[str], str] = getpass.getpass) -> tuple[str, str]:
    user = environment.get("BROWSERSTACK_USERNAME") or ask("BrowserStack username: ").strip()
    key = environment.get("BROWSERSTACK_ACCESS_KEY") or ask_secret("BrowserStack access key (hidden): ").strip()
    if not CREDENTIAL.fullmatch(user) or not CREDENTIAL.fullmatch(key):
        raise FarmError("the BrowserStack username and access key must be set and use only letters, "
                        "digits and . _ @ + -")
    return user, key


def api_url(url: str) -> str:
    """The URL to call with the account: BrowserStack's API host over HTTPS, nothing else."""
    absolute = API_HOST + url if url.startswith("/") else url
    parts = urlsplit(absolute)
    if (parts.scheme != "https" or parts.hostname != API_HOSTNAME or parts.username is not None
            or parts.password is not None or parts.port not in (None, 443)):
        raise FarmError(f"refusing to send the BrowserStack account to {url[:120]!r}")
    return absolute


def _curl(run: Runner, account: tuple[str, str], url: str, *args: str, max_time: int = 120) -> str:
    # -q first: the user's ~/.curlrc could otherwise add tracing or redirects that expose the account.
    argv = ["curl", "-q", "--config", "-", "--proto", "=https", "--silent", "--show-error",
            "--fail-with-body", "--connect-timeout", "30", "--max-time", str(max_time), *args, api_url(url)]
    result = run(argv, input=f'user = "{account[0]}:{account[1]}"\n')
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()[:400]
        raise FarmError(f"BrowserStack request failed (curl exit {result.returncode}): {detail}")
    return result.stdout


def _curl_json(run: Runner, account: tuple[str, str], url: str, *args: str, max_time: int = 120) -> dict[str, Any]:
    body = _curl(run, account, url, *args, max_time=max_time)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise FarmError(f"BrowserStack answered with something other than JSON: {body[:200]}") from error
    if not isinstance(parsed, dict):
        raise FarmError("BrowserStack answered with an unexpected JSON shape")
    return parsed


def _load(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise FarmError(f"missing {path.name} in {path.parent}") from error
    except json.JSONDecodeError as error:
        raise FarmError(f"{path} is not valid JSON") from error
    if not isinstance(loaded, dict):
        raise FarmError(f"{path.name} is not a JSON object")
    return loaded


def check_package(directory: Path, *, force: bool) -> dict[str, Any]:
    """The package's manifest, once its files still match it and it has not been uploaded."""
    manifest = _load(directory / MANIFEST)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise FarmError("package.json has no file digests; package again")
    for name in (IPA, SUITE):
        if not (directory / name).is_file() or sha256(directory / name) != files.get(name):
            raise FarmError(f"{name} no longer matches package.json; package again")
    if (directory / LATEST_UPLOAD).exists() and not force:
        raise FarmError("this package was already uploaded (upload.json); pass --force to start another farm build")
    return manifest


def upload(directory: Path, account: Callable[[], tuple[str, str]], *, devices: list[str],
           confirm: Callable[[str], bool], run: Runner = run_command, force: bool = False,
           now: Callable[[], float] = time.time) -> dict[str, Any] | None:
    """Uploads the package and starts one farm build on `devices` once the maintainer confirms.
    Records the build in uploads/<build id>.json and upload.json; None when declined."""
    manifest = check_package(directory, force=force)
    dirty = " from a tree with uncommitted changes" if manifest.get("dirtyTree") else ""
    if not confirm(f"Upload {directory.name} (commit {str(manifest.get('sourceCommit'))[:8]}{dirty}) and "
                   f"start one farm build on {', '.join(devices)}? It spends BrowserStack minutes."):
        return None
    login = account()
    app = _curl_json(run, login, f"{API}/app", "-X", "POST", "-F", f"file=@{directory / IPA}", max_time=900)
    suite = _curl_json(run, login, f"{API}/test-suite", "-X", "POST", "-F", f"file=@{directory / SUITE}",
                       max_time=900)
    if not app.get("app_url") or not suite.get("test_suite_url"):
        raise FarmError("BrowserStack did not return the uploaded app or test suite")
    request = {
        "app": app["app_url"],
        "testSuite": suite["test_suite_url"],
        "devices": devices,
        "only-testing": list(ONLY_TESTING),
        "deviceLogs": True,
        "enableResultBundle": True,
        # One runner invocation keeps the model the journey downloaded for the memory test.
        "singleRunnerInvocation": "true",
        "project": "Vocello",
        "customBuildName": f"RF-38 farm smoke {directory.name}",
    }
    build = _curl_json(run, login, f"{API}/build", "-X", "POST", "-H", "Content-Type: application/json",
                       "--data-raw", json.dumps(request))
    build_id = str(build.get("build_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", build_id):
        raise FarmError(f"BrowserStack did not start a build: {json.dumps(build)[:300]}")
    record = {
        "schemaVersion": 1,
        "uploadedAtUTC": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now())),
        "sourceCommit": manifest.get("sourceCommit"),
        "appUrl": app["app_url"],
        "testSuiteUrl": suite["test_suite_url"],
        "buildId": build_id,
        "devices": devices,
        "onlyTesting": list(ONLY_TESTING),
    }
    text = json.dumps(record, indent=2) + "\n"
    (directory / "uploads").mkdir(exist_ok=True)
    (directory / "uploads" / f"{build_id}.json").write_text(text)
    (directory / LATEST_UPLOAD).write_text(text)
    return record


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", text).strip("-") or "unnamed"


def results(directory: Path, account: tuple[str, str], *, build_id: str | None = None,
            run: Runner = run_command, bundle: bool = False, emit: Callable[[str], None] = print) -> int:
    """Prints the farm build's status, each test's result and its marker lines, and saves the logs
    under results/<build id>/. 0 when every test passed, 3 while the build runs, 1 otherwise."""
    build_id = build_id or str(_load(directory / LATEST_UPLOAD).get("buildId", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", build_id):
        raise FarmError("no farm build to read; upload first or pass --build")
    build = _curl_json(run, account, f"{API}/builds/{build_id}")
    status = str(build.get("status", "unknown"))
    emit(f"build {build_id}: {status} ({CAVEAT})")
    output = directory / "results" / build_id
    case_statuses: list[str] = []
    for device in build.get("devices", []):
        label = f"{device.get('device', '?')} iOS {device.get('os_version', '?')}"
        for session in device.get("sessions", []):
            session_id = str(session.get("id", ""))
            if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
                raise FarmError(f"{label}: BrowserStack returned a session without a usable id")
            emit(f"{label}: session {session.get('status', 'unknown')}")
            details = _curl_json(run, account, f"{API}/builds/{build_id}/sessions/{session_id}")
            folder = output / _slug(label)
            for group in details.get("testcases", {}).get("data", []):
                for case in group.get("testcases", []):
                    name = f"{group.get('class', '?')}/{case.get('name', '?')}"
                    case_statuses.append(str(case.get("status", "unknown")))
                    emit(f"  {name}: {case_statuses[-1]}")
                    url = case.get("instrumentation_log")
                    if not url:
                        continue
                    log = _curl(run, account, str(url))
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"{_slug(name)}.log").write_text(log)
                    for line in log.splitlines():
                        if any(marker in line for marker in RESULT_MARKERS):
                            emit(f"    {line.strip()}")
            if bundle:
                folder.mkdir(parents=True, exist_ok=True)
                _curl(run, account, f"{API}/builds/{build_id}/sessions/{session_id}/resultbundle",
                      "-o", str(folder / "resultbundle.zip"), max_time=900)
    if status in {"queued", "running"}:
        emit("still running: run results again later")
        return STILL_RUNNING
    return 0 if case_statuses and all(case == "passed" for case in case_statuses) else 1


def _ask_yes(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RF-38 BrowserStack farm smoke: package, upload, results")
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("package")
    pack.add_argument("--products", type=Path, required=True)
    pack.add_argument("--root", type=Path, required=True)
    pack.add_argument("--commit", required=True)
    pack.add_argument("--dirty", choices=["true", "false"], required=True)
    pack.add_argument("--xcode", required=True)
    pack.add_argument("--fingerprint", required=True)
    send = commands.add_parser("upload")
    send.add_argument("package", type=Path)
    send.add_argument("--device", action="append", dest="devices")
    send.add_argument("--force", action="store_true")
    read = commands.add_parser("results")
    read.add_argument("package", type=Path)
    read.add_argument("--build", help="a farm build of this package other than the latest")
    read.add_argument("--bundle", action="store_true", help="also download each session's xcresult bundle")
    args = parser.parse_args(argv)
    try:
        if args.command == "package":
            directory = package(args.products, args.root, commit=args.commit, dirty=args.dirty == "true",
                                xcode=args.xcode, fingerprint=args.fingerprint)
            print(directory)
            return 0
        if not sys.stdin.isatty():
            raise FarmError(f"{args.command} is maintainer-run from a terminal: it uses the maintainer's "
                            "BrowserStack account")
        if args.command == "upload":
            record = upload(args.package, lambda: credentials(os.environ),
                            devices=args.devices or list(DEFAULT_DEVICES), confirm=_ask_yes, force=args.force)
            if record is None:
                print("nothing uploaded")
                return 1
            print(f"farm build {record['buildId']} started on {', '.join(record['devices'])}; "
                  "read it with: scripts/farm_smoke.sh results")
            return 0
        return results(args.package, credentials(os.environ), build_id=args.build, bundle=args.bundle)
    except FarmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
