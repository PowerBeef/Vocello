#!/usr/bin/env python3
"""The shared JSON toolkit reproduces every historical encoding its callers depend on."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import jsonio  # noqa: E402


class CanonicalBytesTests(unittest.TestCase):
    def test_defaults_are_compact_ascii_without_newline_or_nan(self) -> None:
        value = {"b": 1, "a": "é"}
        self.assertEqual(jsonio.canonical_bytes(value), b'{"a":"\\u00e9","b":1}')
        with self.assertRaises(ValueError):
            jsonio.canonical_bytes({"x": float("nan")})

    def test_options_reproduce_the_historical_variants(self) -> None:
        value = {"a": "é"}
        self.assertEqual(jsonio.canonical_bytes(value, ascii=False), '{"a":"é"}'.encode())
        self.assertEqual(jsonio.canonical_bytes(value, newline=True, allow_nan=True), b'{"a":"\\u00e9"}\n')
        self.assertEqual(jsonio.pretty_bytes(value), b'{\n  "a": "\\u00e9"\n}\n')
        self.assertEqual(jsonio.sha256_json(value), hashlib.sha256(b'{"a":"\\u00e9"}').hexdigest())


class FileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_atomic_json_writes_pretty_bytes_and_leaves_no_temporary(self) -> None:
        target = self.root / "nested" / "value.json"
        jsonio.atomic_json(target, {"z": 1, "a": [1, 2]})
        self.assertEqual(target.read_bytes(), b'{\n  "a": [\n    1,\n    2\n  ],\n  "z": 1\n}\n')
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["value.json"])
        jsonio.atomic_json(target, {"a": "é"}, ascii=False, fsync_dir=True)
        self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "a": "é"\n}\n')
        with self.assertRaises(FileNotFoundError):
            jsonio.atomic_json(self.root / "absent" / "x.json", {}, mkdir=False)

    def test_load_json_errors_are_typed_and_bounded(self) -> None:
        class Custom(ValueError):
            pass

        path = self.root / "value.json"
        path.write_text('{"a": 1}')
        self.assertEqual(jsonio.load_json(path), {"a": 1})
        path.write_text("[1]")
        self.assertEqual(jsonio.load_json(path, require_object=False), [1])
        with self.assertRaisesRegex(Custom, "must contain a JSON object"):
            jsonio.load_json(path, error=Custom)
        path.write_text('{"a": 1, "a": 2}')
        self.assertEqual(jsonio.load_json(path), {"a": 2})
        with self.assertRaisesRegex(jsonio.JSONReadError, "duplicate JSON key: a"):
            jsonio.load_json(path, reject_duplicate_keys=True)
        path.write_text("not json")
        with self.assertRaisesRegex(Custom, r"cannot read JSON value\.json: JSONDecodeError") as context:
            jsonio.load_json(path, error=Custom, redact="type")
        self.assertNotIn(str(self.root), str(context.exception))
        with self.assertRaisesRegex(Custom, r"cannot read JSON value\.json: Expecting"):
            jsonio.load_json(path, error=Custom, redact="name")
        with self.assertRaisesRegex(Custom, "cannot read JSON .*absent"):
            jsonio.load_json(self.root / "absent.json", error=Custom)

    def test_sha256_file_streams_and_can_wrap_errors(self) -> None:
        path = self.root / "blob.bin"
        payload = b"x" * (3 * 1024 * 1024 + 7)
        path.write_bytes(payload)
        self.assertEqual(jsonio.sha256_file(path), hashlib.sha256(payload).hexdigest())
        with self.assertRaises(OSError):
            jsonio.sha256_file(self.root / "absent")

        class Custom(ValueError):
            pass

        with self.assertRaisesRegex(Custom, "cannot hash"):
            jsonio.sha256_file(self.root / "absent", error=Custom)

    def test_utc_now_shape(self) -> None:
        stamp = jsonio.utc_now()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertRegex(jsonio.utc_now(whole_seconds=False), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        json.loads(json.dumps(stamp))


ROOT = Path(__file__).resolve().parents[2]
# BKL-64: the scripts that kept their own reader. Each keeps its error type and how much of the
# path its messages show: (script, loader, error class or None for ValueError, shown, lists pass).
CALLERS = (
    ("scripts/audio_qc_script_pool.py", "load_json", "ScriptPoolError", "type", False),
    ("scripts/check_ios_model_management.py", "load_json", None, "path", True),
    ("scripts/check_language_hints.py", "load_json", None, "path", False),
    ("scripts/qwen3_core_contract.py", "load_json", None, "path", True),
    ("scripts/release_source_authority.py", "_load_json", None, "path", True),
    ("scripts/runtime_security_contract.py", "load_json", None, "name", False),
    ("scripts/support_contact_contract.py", "_load_json", None, "name", False),
)


def script_module(relative: str):
    name = f"jsonio_caller_{Path(relative).stem}"
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module                     # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


class CallerTests(unittest.TestCase):
    def test_the_scripts_that_read_json_do_it_through_the_toolkit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private host directory"
            root.mkdir()
            (root / "value.json").write_text('{"a": 1}', encoding="utf-8")
            (root / "list.json").write_text("[1]", encoding="utf-8")
            (root / "bad.json").write_text("not json", encoding="utf-8")
            (root / "undecodable.json").write_bytes(b"\xff\xfe{")
            for relative, name, error_name, shown, lists in CALLERS:
                with self.subTest(script=relative):
                    module = script_module(relative)
                    loader = getattr(module, name)
                    error = getattr(module, error_name) if error_name else ValueError
                    self.assertEqual(loader(root / "value.json"), {"a": 1})
                    if lists:
                        self.assertEqual(loader(root / "list.json"), [1])
                    else:
                        with self.assertRaisesRegex(error, "list.json must contain a JSON object"):
                            loader(root / "list.json")
                    for path, detail in (("bad.json", "JSONDecodeError" if shown == "type" else "Expecting"),
                                         ("undecodable.json", "UnicodeDecodeError" if shown == "type" else "codec")):
                        with self.assertRaisesRegex(error, f"cannot read JSON .*{path}: .*{detail}") as context:
                            loader(root / path)
                        self.assertEqual(str(root) in str(context.exception), shown == "path")
                    # An OSError's own text names the path unless only its type is shown.
                    detail = "FileNotFoundError" if shown == "type" else "No such file"
                    with self.assertRaisesRegex(error, f"cannot read JSON .*absent.json: .*{detail}") as context:
                        loader(root / "absent.json")
                    self.assertEqual(str(root) in str(context.exception), shown != "type")


if __name__ == "__main__":
    unittest.main()
