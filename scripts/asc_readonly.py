#!/usr/bin/env python3
"""Bounded, privacy-safe JSON reads through the App Store Connect CLI."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from typing import Any, Callable, Sequence


class ASCReadError(ValueError):
    """A sanitized App Store Connect read failure."""


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def run_json(
    arguments: Sequence[str],
    profile: str,
    timeout: int,
    *,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    terminate: Callable[[subprocess.Popen[str]], None] = _terminate_process_group,
) -> dict[str, Any]:
    """Run one read-only asc command with complete process-group cleanup."""

    if timeout <= 0:
        raise ASCReadError("App Store Connect timeout must be positive")
    environment = dict(os.environ)
    environment["ASC_TELEMETRY_DISABLED"] = "1"
    process = popen(
        ["asc", "--profile", profile, "--strict-auth", *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        terminate(process)
        process.communicate()
        raise ASCReadError("App Store Connect read timed out") from error
    if process.returncode:
        raise ASCReadError("App Store Connect read failed")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ASCReadError("App Store Connect returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ASCReadError("App Store Connect response root must be an object")
    return payload
