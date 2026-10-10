#!/usr/bin/env python3
"""Select an existing repository Python without installing or changing host settings.

This bootstrap is compatible with the macOS system Python 3.9. Workflow execution
requires Python 3.10 or newer. VOCELLO_PYTHON is an explicit executable override.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("pytest", "pytest-xdist", "numpy")
PROBE = """import importlib.metadata as m, json, sys
versions = {}
for name in ('pytest', 'pytest-xdist', 'numpy'):
    try: versions[name] = m.version(name)
    except m.PackageNotFoundError: versions[name] = None
print(json.dumps({'version': list(sys.version_info[:2]), 'packages': versions}))
"""


def inspect_python(executable):
    try:
        result = subprocess.run([executable, "-c", PROBE], capture_output=True, text=True,
                                timeout=5, check=False)
        report = json.loads(result.stdout) if result.returncode == 0 else {}
        version = report.get("version") if isinstance(report, dict) else None
        if (isinstance(version, list) and len(version) == 2
                and all(isinstance(part, int) and not isinstance(part, bool) for part in version)
                and tuple(version) >= (3, 10) and isinstance(report.get("packages"), dict)):
            return report
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def installed_candidates():
    ambient = shutil.which("python3")
    if ambient:
        yield ambient
    if sys.platform == "darwin":
        # Homebrew keeps its unversioned executable outside the ordinary bin dir.
        for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
            yield from (str(path) for path in sorted(prefix.glob("opt/python@*/libexec/bin/python3"), reverse=True))


def select_python(root=ROOT):
    explicit = os.environ.get("VOCELLO_PYTHON")
    if explicit is not None:
        executable = shutil.which(explicit) if explicit else None
        if not executable or not inspect_python(executable):
            raise ValueError("VOCELLO_PYTHON must name an executable Python 3.10 or newer; no fallback was used")
        return executable
    manifest = json.loads((root / "config/toolchain.json").read_text(encoding="utf-8"))
    pins = {name: manifest["native"][name]["version"] for name in PACKAGES}
    compatible = []
    for executable in dict.fromkeys(installed_candidates()):
        report = inspect_python(executable)
        if report:
            compatible.append(executable)
            if all(report["packages"].get(name) == pin for name, pin in pins.items()):
                return executable
    if compatible:
        return compatible[0]  # Read-only tools still work without test dependencies.
    raise ValueError("No executable Python 3.10 or newer found; set VOCELLO_PYTHON to an installed interpreter")


if __name__ == "__main__":
    try:
        print(select_python())
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
