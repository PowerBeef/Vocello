"""Lane markers for the Python suite.

Modules are marked by name, never moved: `research` covers the audio, delivery,
prosody and device-analysis tooling that only changes when that research does;
`darwin_only` covers modules that need the macOS host (they skip elsewhere).
Push CI runs `-m "not research and not darwin_only"` on Linux, adds `-m research`
when a research path changed, and runs `-m darwin_only` inside the macOS gate.
Nightly runs everything.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DARWIN_ONLY_MODULES = {"test_benchmark_history"}
QUARANTINE = ROOT / "config/test-quarantine.json"


def _research_prefixes() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("classify_changes", ROOT / "scripts/ci/classify_changes.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RESEARCH_PREFIXES


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "research: audio, delivery, prosody and device-analysis tooling")
    config.addinivalue_line("markers", "darwin_only: needs the macOS host; skipped elsewhere")


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
        if module_name in DARWIN_ONLY_MODULES:
            item.add_marker(pytest.mark.darwin_only)
