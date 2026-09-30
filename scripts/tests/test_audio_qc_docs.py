#!/usr/bin/env python3
"""AQ-09: the generated audio QC reference tree, from fixture registries and a fixture record.

The fixture repository (`fixtures/audio_qc_docs/repo`) holds two judges with
their canary, Fast QC, a retired judge, a Stage 0 detector with no plan and a
content detector with a committed plan, ledger entry and qualified warn record
that gates the language bench. `fixtures/audio_qc_docs/golden` is the tree
`regen` renders from it; after an intended rendering change, rewrite it with
`AUDIO_QC_DOCS_UPDATE_GOLDEN=1 python3 -m pytest scripts/tests/test_audio_qc_docs.py`
and review the diff.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_docs as docs  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audio_qc_docs"
REPO_FIXTURE = FIXTURE / "repo"
GOLDEN = FIXTURE / "golden"
TREE = Path(str(docs.DOCS))
CONTENT, CLICKS = "content.consensus-error@1", "signal.clicks@1"
RECORD_DIRECTORY = Path("benchmarks/audio-qc-calibration") / CONTENT


def run(root: Path, *arguments: str) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = docs.main(["--repo-root", str(root), "regen", *arguments])
    return code, out.getvalue(), err.getvalue()


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        shutil.copytree(REPO_FIXTURE, self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def page(self, relative: str) -> Path:
        return self.root / TREE / relative

    def read(self, relative: str) -> str:
        return self.page(relative).read_text(encoding="utf-8")

    def edit_json(self, relative: str, change) -> None:
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def regen(self) -> None:
        code, _, err = run(self.root)
        self.assertEqual(code, 0, err)


class GoldenTests(FixtureCase):
    def test_the_fixture_renders_the_golden_tree(self) -> None:
        self.regen()
        rendered = {path.relative_to(self.root / TREE).as_posix(): path.read_text(encoding="utf-8")
                    for path in sorted((self.root / TREE).rglob("*.md"))}
        if os.environ.get("AUDIO_QC_DOCS_UPDATE_GOLDEN") == "1":
            shutil.rmtree(GOLDEN, ignore_errors=True)
            for relative, text in rendered.items():
                (GOLDEN / relative).parent.mkdir(parents=True, exist_ok=True)
                (GOLDEN / relative).write_text(text, encoding="utf-8")
        golden = {path.relative_to(GOLDEN).as_posix(): path.read_text(encoding="utf-8")
                  for path in sorted(GOLDEN.rglob("*.md"))}
        self.assertEqual(sorted(rendered), sorted(golden))
        for relative, text in golden.items():
            with self.subTest(page=relative):
                self.assertEqual(rendered[relative], text)

    def test_one_page_per_registry_judge_and_detector(self) -> None:
        self.regen()
        judges = json.loads((self.root / "config/audio-qc-judges.json").read_text(encoding="utf-8"))["judges"]
        detectors = json.loads((self.root / "config/audio-qc-detectors.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(path.name for path in self.page("judges").glob("*.md")),
                         sorted(docs.page_name(identifier) for identifier in judges))
        self.assertEqual(sorted(path.name for path in self.page("detectors").glob("*.md")),
                         sorted(docs.page_name(entry["id"]) for entry in detectors["detectors"]))
        # Page and registry agree on identity: each page names its own entry.
        for identifier in judges:
            self.assertIn(f"Registry entry `{identifier}`", self.read(f"judges/{docs.page_name(identifier)}"))

    def test_a_qualified_record_is_reported_with_its_rates(self) -> None:
        self.regen()
        page = self.read("detectors/content.consensus-error-v1.md")
        self.assertIn("**Status.** Qualified (warn); confirmed (qualified).", page)
        self.assertIn("| german | 0.1175 | 4/121 (0.033), upper 0.087 | 0.2 | yes |", page)
        self.assertIn("| T1-pcm-construction | CNT-DEL/severe | 141/150 (0.940), lower 0.898 | 0.7 | yes |", page)
        self.assertIn("language-bench at warn", page)
        self.assertNotIn(docs.NOT_QUALIFIED, page)
        self.assertNotIn("UNQUALIFIED", self.read("judges/asr.whisper-large-v3-v1.md"))
        report = self.read("meta-evaluation-report.md")
        self.assertIn("| B (content) | confirmed (qualified) | qualified (warn) | 7/359 (0.019), upper 0.036 |", report)


class FailPlanTests(FixtureCase):
    def test_a_fail_plan_and_a_fail_record_are_rendered_beside_the_warn_ones(self) -> None:
        from lib.qc_qualification import thresholds

        directory = self.root / "config/audio-qc-preregistrations"
        warn = json.loads((directory / f"{CONTENT}.json").read_text(encoding="utf-8"))
        warn["bindings"].update(operatingPoint="fail", n3CohortDigest="7" * 64)
        warn["alpha"] = 0.005
        plan = thresholds.PreRegistration.from_dict(warn)
        thresholds.PreRegistrationStore(directory, naming="detector").commit(plan)
        self.assertTrue((directory / f"{CONTENT}.fail.json").is_file())
        record = next((self.root / RECORD_DIRECTORY).glob("record-*.json")).relative_to(self.root).as_posix()

        def fail(value: dict) -> None:
            value.update(operatingPoint="fail", level="fail")
            value["cohorts"]["n3"] = {"kind": "audio-qc-calibration-takes", "manifestDigest": "7" * 64,
                                      "scoresSHA256": "8" * 64}
            value["rates"]["n3"] = {"events": 1, "units": 600, "rate": 0.001667, "lower": 0.0, "upper": 0.0079,
                                    "confidence": 0.95, "method": "clopper-pearson-one-sided", "limit": 0.05,
                                    "minimumUnits": None, "meets": True}
        self.edit_json(record, fail)
        self.regen()
        page = self.read("detectors/content.consensus-error-v1.md")
        self.assertIn(f"**Plan (fail).** [{docs.PREREGISTRATIONS}/{CONTENT}.fail.json]", page)
        self.assertIn("N3 bound manifest `7777777777777777`", page)
        self.assertIn("**Status.** Qualified (fail); confirmed (qualified); fail planned.", page)
        self.assertIn("N3 bound (A2): flag rate 1/600 (0.002), upper 0.008 (limit 0.05, meets yes)", page)
        self.assertIn("confirmed (qualified); fail planned", self.read("README.md"))


class NoRecordTests(FixtureCase):
    def test_without_a_record_every_page_says_not_qualified(self) -> None:
        shutil.rmtree(self.root / RECORD_DIRECTORY)
        for ledger in (self.root / "config/audio-qc-preregistrations").glob("confirmation-*.json"):
            ledger.unlink()
        self.regen()
        page = self.read("detectors/content.consensus-error-v1.md")
        self.assertIn("**Status.** Not qualified; planned, not confirmed.", page)
        self.assertIn("**Confirmation.** Not run: no ledger entry.", page)
        self.assertIn(docs.NOT_QUALIFIED, page)
        self.assertIn("**UNQUALIFIED.**", self.read("judges/asr.whisper-large-v3-v1.md"))
        report = self.read("meta-evaluation-report.md")
        self.assertIn("No detector has a committed calibration record yet.", report)
        self.assertIn("| B (content) | planned, not confirmed | not qualified | - |", report)
        self.assertIn("| A (signal) | no plan | not qualified | - |", report)

    def test_an_invalid_record_is_shown_but_never_qualifies(self) -> None:
        record = next((self.root / RECORD_DIRECTORY).glob("record-*.json"))
        self.edit_json(record.relative_to(self.root).as_posix(), lambda value: value.update(verdict="maybe"))
        self.regen()
        page = self.read("detectors/content.consensus-error-v1.md")
        self.assertIn("not usable (verdict is qualified or refused", page)
        self.assertIn(docs.NOT_QUALIFIED, page)

    def test_a_record_of_an_earlier_definition_never_qualifies(self) -> None:
        def reword(registry: dict) -> None:
            next(entry for entry in registry["detectors"] if entry["id"] == CONTENT)["measures"] += " Reworded."
        self.edit_json("config/audio-qc-detectors.json", reword)
        self.regen()
        self.assertIn("it confirmed an earlier definition (A7)", self.read("detectors/content.consensus-error-v1.md"))


class CheckAndSpliceTests(FixtureCase):
    def test_check_is_fresh_after_regen_and_names_a_drifted_block(self) -> None:
        self.regen()
        code, out, _ = run(self.root, "--check")
        self.assertEqual(code, 0)
        self.assertIn("pages fresh", out)
        page = self.page("detectors/signal.clicks-v1.md")
        page.write_text(page.read_text(encoding="utf-8").replace("above", "below"), encoding="utf-8")
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(f"{docs.STALE_MESSAGE}: {TREE}/detectors/signal.clicks-v1.md", err)
        before = page.read_text(encoding="utf-8")
        self.regen()
        self.assertNotEqual(page.read_text(encoding="utf-8"), before)
        self.assertEqual(run(self.root, "--check")[0], 0)

    def test_check_writes_nothing_and_a_missing_page_is_stale(self) -> None:
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(docs.STALE_MESSAGE, err)
        self.assertFalse((self.root / TREE).exists())

    def test_a_registry_change_stales_the_generated_block(self) -> None:
        self.regen()
        self.edit_json("config/audio-qc-judges.json",
                       lambda value: value["judges"]["fastqc@8"].update(role="A new description."))
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(f"{TREE}/judges/fastqc-v8.md", err)

    def test_the_corpora_page_follows_its_registry(self) -> None:
        self.regen()
        self.edit_json("config/audio-qc-corpora.json",
                       lambda value: value["sources"]["hub-mirror"]["caveats"].append("A new caveat."))
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(f"{TREE}/corpora.md", err)
        self.regen()
        text = self.read("corpora.md")
        self.assertIn("- Caveat: A new caveat.", text)
        self.assertLess(text.index("| `speaker` |"), text.index("| `emotion` |"))
        self.assertIn("emo-archive, hub-mirror (shared)", text)

    def test_hand_written_text_outside_the_blocks_is_kept(self) -> None:
        self.regen()
        page = self.page("judges/fastqc-v8.md")
        notes = "\n## Notes\n\nA hand-written note that no regen touches.\n"
        text = "---\nstatus: active\n---\n" + page.read_text(encoding="utf-8") + notes
        page.write_text(text, encoding="utf-8")
        self.edit_json("config/audio-qc-judges.json",
                       lambda value: value["judges"]["fastqc@8"].update(role="A new description."))
        self.regen()
        updated = page.read_text(encoding="utf-8")
        self.assertTrue(updated.startswith("---\nstatus: active\n---\n# `fastqc@8`"))
        self.assertTrue(updated.endswith(notes))
        self.assertIn("**Measures.** A new description.", updated)

    def test_a_missing_block_is_appended_and_an_unknown_one_removed(self) -> None:
        self.regen()
        page = self.page("detectors/signal.clicks-v1.md")
        text = page.read_text(encoding="utf-8")
        start = text.index(docs.BEGIN.format(name="qualification"))
        stray = docs.block_text("retired-block", "old generated text")
        page.write_text(text[:start] + stray, encoding="utf-8")
        self.regen()
        updated = page.read_text(encoding="utf-8")
        self.assertNotIn("retired-block", updated)
        self.assertIn(docs.BEGIN.format(name="qualification"), updated)
        self.assertEqual(run(self.root, "--check")[0], 0)

    def test_an_unterminated_or_repeated_block_is_an_error(self) -> None:
        self.regen()
        page = self.page("judges/fastqc-v8.md")
        text = page.read_text(encoding="utf-8")
        page.write_text(text.replace(docs.END.format(name="facts"), ""), encoding="utf-8")
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn("marker has no partner", err)
        self.assertNotIn(docs.STALE_MESSAGE, err)
        block = docs.block_text("accuracy", "twice")
        page.write_text(text + block, encoding="utf-8")
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn("appears more than once", err)

    def test_a_page_without_a_registry_entry_is_an_error_not_stale(self) -> None:
        self.regen()
        orphan = self.page("judges/asr.retired-elsewhere-v1.md")
        orphan.write_text("# `asr.retired-elsewhere@1`\n\nProse that belongs to a successor.\n", encoding="utf-8")
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(f"{TREE}/judges/asr.retired-elsewhere-v1.md has no registry entry", err)
        self.assertNotIn(docs.STALE_MESSAGE, err)
        self.assertEqual(run(self.root)[0], 1)
        self.assertTrue(orphan.is_file())

    def test_a_new_detector_of_any_class_gets_its_page(self) -> None:
        self.regen()

        def add(registry: dict) -> None:
            entry = json.loads(json.dumps(next(item for item in registry["detectors"] if item["id"] == CLICKS)))
            entry.update(id="identity.onset-drift@1", **{"class": "E"}, measures="A class E fixture.",
                         novelField={"declared": "later"})
            registry["detectors"].append(entry)
        self.edit_json("config/audio-qc-detectors.json", add)
        code, _, err = run(self.root, "--check")
        self.assertEqual(code, 1)
        self.assertIn(f"{TREE}/detectors/identity.onset-drift-v1.md", err)
        self.regen()
        page = self.read("detectors/identity.onset-drift-v1.md")
        self.assertIn("| E (identity) |", page)
        self.assertIn('- `novelField`: declared="later"', page)
        self.assertIn(docs.NOT_QUALIFIED, page)
        self.assertIn("[`identity.onset-drift@1`](detectors/identity.onset-drift-v1.md)", self.read("README.md"))


if __name__ == "__main__":
    unittest.main()
