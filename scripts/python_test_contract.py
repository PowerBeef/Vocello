#!/usr/bin/env python3
"""Fail-closed inventory contract for repository Python tests.

The executable test lane uses unittest discovery for both supported roots. This
contract keeps that discovery honest by rejecting a tracked-looking test module
that declares no discoverable unittest test, or function-style tests without an
explicit ``load_tests`` adapter.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEST_ROOTS = (
    (Path("scripts"), False),
    (Path("scripts/tests"), False),
)


@dataclass(frozen=True)
class ModuleInventory:
    path: Path
    declared_tests: int
    class_tests: int
    function_tests: int
    has_load_tests: bool


def _is_test_function(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
        "test"
    )


def inventory_module(path: Path) -> ModuleInventory:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise ValueError(f"{path}: cannot parse test module: {error}") from error

    function_tests = sum(1 for node in tree.body if _is_test_function(node))
    class_tests = sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if _is_test_function(member)
    )
    has_load_tests = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "load_tests"
        for node in tree.body
    )
    return ModuleInventory(
        path=path,
        declared_tests=class_tests + function_tests,
        class_tests=class_tests,
        function_tests=function_tests,
        has_load_tests=has_load_tests,
    )


def iter_test_modules(project_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for relative_root, recursive in TEST_ROOTS:
        root = project_root / relative_root
        if not root.is_dir():
            continue
        candidates = root.rglob("test_*.py") if recursive else root.glob("test_*.py")
        for path in sorted(candidates):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def validate(project_root: Path) -> list[ModuleInventory]:
    inventories = [inventory_module(path) for path in iter_test_modules(project_root)]
    errors: list[str] = []
    if not inventories:
        errors.append("no Python test modules found under scripts/ or scripts/tests/")

    for inventory in inventories:
        relative = inventory.path.relative_to(project_root)
        if inventory.declared_tests == 0:
            errors.append(f"{relative}: unexpected zero-test module")
        if inventory.function_tests and not inventory.has_load_tests:
            errors.append(
                f"{relative}: {inventory.function_tests} function-style test(s) are invisible to "
                "unittest discovery; add a load_tests adapter or convert them to unittest.TestCase"
            )
        if inventory.has_load_tests and not inventory.function_tests:
            errors.append(f"{relative}: load_tests exists without function-style tests")

    if errors:
        raise ValueError("\n".join(errors))
    return inventories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (used by contract fixtures)",
    )
    args = parser.parse_args()

    try:
        inventories = validate(args.root.resolve())
    except ValueError as error:
        print(f"Python test contract: FAIL\n{error}")
        return 1

    declared = sum(item.declared_tests for item in inventories)
    print(f"Python test contract: PASS ({len(inventories)} modules, {declared} declared tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
