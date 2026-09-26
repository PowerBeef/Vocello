"""Lane markers for the Python suite.

Modules are marked by name, never moved: `research` covers the audio, delivery,
prosody and device-analysis tooling that only changes when that research does.
Every module runs on Linux: host probes (the benchmark publisher's `swift -e`
and `devicectl`) are mocked in the tests, so no module needs the macOS host.
Push CI runs `-m "not research"` on Linux and adds `-m research` when a research
path changed. Nightly runs everything.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_LOCK_ROOT_KEY = pytest.StashKey[str]()

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:  # modules loaded by path import `lib.*`
    sys.path.insert(0, str(SCRIPTS))

ROOT = Path(__file__).resolve().parents[2]
QUARANTINE = ROOT / "config/test-quarantine.json"


def _research_prefixes() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("classify_changes", ROOT / "scripts/ci/classify_changes.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RESEARCH_PREFIXES


ANALYSIS_LOCK_ROOT_VARIABLE = "QVOICE_DELIVERY_ANALYSIS_LOCK_ROOT"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "research: audio, delivery, prosody and device-analysis tooling")
    # No test touches the host's real analysis lock or admission ledger: every
    # test process (each xdist worker too) gets its own root, the test-only
    # override of `hostAnalysisLock` in config/build-output-policy.json.
    root = tempfile.mkdtemp(prefix="vocello-analysis-lock-")
    config.stash[_LOCK_ROOT_KEY] = root
    os.environ[ANALYSIS_LOCK_ROOT_VARIABLE] = root


def pytest_unconfigure(config: pytest.Config) -> None:
    root = config.stash.get(_LOCK_ROOT_KEY, None)
    if root:
        shutil.rmtree(root, ignore_errors=True)


def _quarantined() -> set[str]:
    if os.environ.get("VOCELLO_QUARANTINE") != "1" or not QUARANTINE.is_file():
        return set()
    entries = json.loads(QUARANTINE.read_text(encoding="utf-8")).get("entries", [])
    return {entry.get("id", "") for entry in entries}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    prefixes = _research_prefixes()
    quarantined = _quarantined()
    for item in items:
        if item.nodeid in quarantined:
            item.add_marker(pytest.mark.skip(reason="quarantined in config/test-quarantine.json"))
        module_name = item.path.stem
        subject = module_name.removeprefix("test_")
        if any(subject.startswith(prefix) for prefix in prefixes):
            item.add_marker(pytest.mark.research)
