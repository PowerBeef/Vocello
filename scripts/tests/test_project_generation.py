"""Generation invalidation is independent of source bytes and native execution."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("project_generation", ROOT / "scripts/project_generation.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
WORKFLOW_SPEC = importlib.util.spec_from_file_location("development_workflow", ROOT / "scripts/development_workflow.py")
assert WORKFLOW_SPEC and WORKFLOW_SPEC.loader
WORKFLOW = importlib.util.module_from_spec(WORKFLOW_SPEC)
WORKFLOW_SPEC.loader.exec_module(WORKFLOW)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vocello generation ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("project.yml", "name: QwenVoice\ntargets:\n  App:\n    sources:\n      - path: Sources\n    resources:\n      - path: Assets\n")
        self.write("Sources/A.swift", "first")
        self.write("Assets/en.lproj/Strings.strings", "first")
        self.write("config/build-output-policy.json", json.dumps({"entries": [
            {"id": "xcode-source-packages", "path": "build/cache/packages"}]}))
        for output in MODULE.OUTPUTS:
            self.write(output, "generated")
        self.stamp = self.root / "stamp"

    def write(self, path, content):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return file

    def test_source_and_resource_content_edits_keep_signature(self):
        before = MODULE.signature(self.root)
        self.write("Sources/A.swift", "second")
        self.write("Assets/en.lproj/Strings.strings", "second")
        self.assertEqual(before, MODULE.signature(self.root))

    def test_add_delete_rename_changes_membership(self):
        before = MODULE.signature(self.root)
        new = self.write("Sources/New.swift", "source")
        self.assertNotEqual(before, MODULE.signature(self.root))
        new.unlink()
        self.assertEqual(before, MODULE.signature(self.root))
        (self.root / "Sources/A.swift").rename(self.root / "Sources/Renamed.swift")
        self.assertNotEqual(before, MODULE.signature(self.root))
        before = MODULE.signature(self.root)
        self.write("Assets/fr.lproj/Strings.strings", "translated")
        self.assertNotEqual(before, MODULE.signature(self.root))

    def test_template_generator_and_spec_edits_invalidate(self):
        for relative in ("project.yml", *MODULE.GENERATORS, "config/xcode-schemes/App.xcscheme.template"):
            with self.subTest(relative=relative):
                before = MODULE.signature(self.root)
                path = self.root / relative
                self.write(relative, (path.read_text() if path.exists() else "") + "\n# change\n")
                self.assertNotEqual(before, MODULE.signature(self.root))

    def test_hidden_and_unrelated_files_do_not_invalidate(self):
        before = MODULE.signature(self.root)
        self.write("Sources/.DS_Store", "ignored")
        self.write("Sources/.scratch/cache", "ignored")
        self.write("docs/new.md", "unrelated")
        self.assertEqual(before, MODULE.signature(self.root))

    def test_included_spec_paths_are_relative_to_the_spec(self):
        self.write("project.yml", "name: QwenVoice\ninclude:\n  - path: specs/shared.yml\n")
        self.write("specs/shared.yml", "targetTemplates:\n  Shared:\n    sources:\n      - path: '../Sources'\n")
        before = MODULE.signature(self.root)
        self.write("Sources/B.swift", "source")
        self.assertNotEqual(before, MODULE.signature(self.root))

    def test_planning_recognizes_included_specs_and_custom_resource_roots(self):
        self.write("project.yml", "include:\n  - specs/shared.yml\n")
        self.write("specs/shared.yml", "targets:\n  App:\n    resources:\n      - path: '../Assets'\n")
        self.assertTrue(MODULE.relevant_paths(["specs/shared.yml"], self.root))
        self.assertTrue(MODULE.relevant_paths(["Assets/new.wav"], self.root))
        self.assertFalse(MODULE.relevant_paths(["docs/new.md"], self.root))

    def test_unsupported_flow_paths_fail_closed(self):
        self.write("project.yml", "targets:\n  App:\n    sources: [Sources]\n")
        with self.assertRaisesRegex(ValueError, "block-list"):
            MODULE.signature(self.root)

    def test_record_freshness_and_missing_outputs(self):
        self.assertTrue(MODULE.status(self.root, self.stamp)["needsRegeneration"])
        MODULE.record(self.root, self.stamp)
        self.assertFalse(MODULE.status(self.root, self.stamp)["needsRegeneration"])
        for output in MODULE.OUTPUTS:
            with self.subTest(output=output):
                (self.root / output).unlink()
                state = MODULE.status(self.root, self.stamp)
                self.assertTrue(state["needsRegeneration"])
                self.assertIn(output, state["missingOutputs"])
                with self.assertRaises(ValueError):
                    MODULE.record(self.root, self.stamp)
                self.write(output, "restored")

    def test_racing_input_change_does_not_publish_a_stamp(self):
        before = MODULE.signature(self.root)
        self.write("Sources/New.swift", "source")
        with self.assertRaises(ValueError):
            MODULE.record(self.root, self.stamp, before)
        self.assertFalse(self.stamp.exists())

    def test_check_planning_uses_the_same_signature_and_content_freshness(self):
        environment = {key: value for key, value in os.environ.items() if key != "QVOICE_XCODE_SOURCE_PACKAGES"}
        with mock.patch.object(WORKFLOW, "ROOT", self.root), \
                mock.patch.object(WORKFLOW, "_load", return_value=MODULE), \
                mock.patch.dict(os.environ, environment, clear=True):
            self.assertIsNone(WORKFLOW.project_generation_status(["docs/new.md"]))
            stamp = MODULE.stamp_path(self.root)
            MODULE.record(self.root, stamp)
            self.write("Sources/A.swift", "content edit")
            self.assertFalse(WORKFLOW.project_generation_status(["Sources/A.swift"])["needsRegeneration"])
            self.write("Sources/B.swift", "new source")
            self.assertTrue(WORKFLOW.project_generation_status(["Sources/B.swift"])["needsRegeneration"])

    def test_cli_reports_check_status_without_writing(self):
        import io
        from contextlib import redirect_stdout
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        with redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(MODULE.main(["status", "--root", str(self.root), "--stamp", str(self.stamp)]), 0)
        self.assertTrue(json.loads(stream.getvalue())["needsRegeneration"])
        self.assertEqual(MODULE.main(["check", "--root", str(self.root), "--stamp", str(self.stamp)]), 1)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)

    def test_shell_cache_regenerates_for_membership_and_missing_outputs_only(self):
        import shutil
        import subprocess
        helper = self.root / "scripts/project_generation.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "scripts/project_generation.py", helper)
        self.write("scripts/generate_cli_scheme.py", "raise SystemExit(0)\n")
        self.write("scripts/generate_ios_logic_scheme.py", "raise SystemExit(0)\n")
        self.write("scripts/regenerate_project.sh", """#!/usr/bin/env bash
set -eu
printf 'regenerated\\n' >> "$ROOT_DIR/generation-count.txt"
mkdir -p "$ROOT_DIR/QwenVoice.xcodeproj/xcshareddata/xcschemes"
touch "$ROOT_DIR/QwenVoice.xcodeproj/project.pbxproj"
touch "$ROOT_DIR/QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloCLI.xcscheme"
touch "$ROOT_DIR/QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloiOSLogic.xcscheme"
python3 "$ROOT_DIR/scripts/project_generation.py" record
""")
        environment = {**os.environ, "ROOT_DIR": str(self.root), "QVOICE_BUILD_ROOT": str(self.root / "build"),
                       "QVOICE_XCODE_SOURCE_PACKAGES": str(self.root / "packages")}
        command = ["bash", "-c", 'source "$1"; ensure_project_regenerated', "cache-test", str(ROOT / "scripts/lib/build_cache.sh")]
        def ensure():
            result = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def count():
            return len((self.root / "generation-count.txt").read_text().splitlines())
        ensure()
        self.assertEqual(count(), 1)
        self.write("Sources/A.swift", "content edit")
        ensure()
        self.assertEqual(count(), 1)
        new = self.write("Sources/New.swift", "new")
        ensure()
        self.assertEqual(count(), 2)
        new.rename(self.root / "Sources/Renamed.swift")
        ensure()
        self.assertEqual(count(), 3)
        (self.root / MODULE.OUTPUTS[0]).unlink()
        ensure()
        self.assertEqual(count(), 4)
