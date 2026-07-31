"""Synthetic-fixture tests for the release-notes quality gate."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import check_release_notes  # noqa: E402


def _passing_body() -> str:
    filler = "Real substance about the release, written for humans. " * 12
    return "\n".join(
        [
            "# Vocello 9.9.9",
            "",
            "Released **2099-01-01**. " + filler,
            "",
            "## What's new",
            "- Something users care about, in plain language. " + filler,
            "",
            "## Requirements",
            "- macOS 26.0 or later. " + filler,
            "",
            "## Install",
            "1. Download [the DMG](https://example.com/dmg) and drag it in.",
            "",
            "## TestFlight — What to Test (build 99)",
            "- Try the new thing and report anything odd. " + filler,
            "",
        ]
    )


class ValidateNotesTests(unittest.TestCase):
    def test_passing_body_has_no_failures(self) -> None:
        self.assertEqual(check_release_notes.validate_notes(_passing_body()), [])

    def test_each_required_section_is_enforced(self) -> None:
        for heading in ("## What's new", "## Requirements", "## Install", "## TestFlight"):
            body = _passing_body().replace(heading, "## Removed")
            failures = check_release_notes.validate_notes(body)
            self.assertTrue(
                any("missing required section" in f for f in failures),
                f"removing {heading!r} must fail: {failures}",
            )

    def test_headline_heading_satisfies_substance_section(self) -> None:
        body = _passing_body().replace("## What's new", "## Headline themes")
        self.assertEqual(check_release_notes.validate_notes(body), [])

    def test_placeholders_fail_closed(self) -> None:
        for token in ("PENDING-SMOKE-RUN-ID", "TBD", "TODO", "FIXME"):
            failures = check_release_notes.validate_notes(_passing_body() + f"\n{token}\n")
            self.assertTrue(
                any("placeholder" in f for f in failures),
                f"{token} must fail: {failures}",
            )

    def test_relative_links_fail_and_absolute_links_pass(self) -> None:
        bad = _passing_body() + "\nSee [older notes](v2.2.0.md#requirements).\n"
        failures = check_release_notes.validate_notes(bad)
        self.assertTrue(any("relative markdown links" in f for f in failures))
        good = (
            _passing_body()
            + "\nSee [older notes](https://example.com/v2.2.0), "
            + "[anchor](#install), [mail](mailto:x@example.com).\n"
        )
        self.assertEqual(check_release_notes.validate_notes(good), [])

    def test_thin_body_fails_minimum_size(self) -> None:
        thin = "## What's new\n## Requirements\n## Install\n## TestFlight\nok\n"
        failures = check_release_notes.validate_notes(thin)
        self.assertTrue(any("bytes" in f for f in failures))


class CliTests(unittest.TestCase):
    def test_cli_pass_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes = pathlib.Path(tmp) / "v9.9.9.md"
            notes.write_text(_passing_body(), encoding="utf-8")
            self.assertEqual(
                check_release_notes.main(["v9.9.9", "--file", str(notes)]), 0
            )
            self.assertEqual(
                check_release_notes.main(
                    ["v9.9.9", "--file", str(pathlib.Path(tmp) / "absent.md")]
                ),
                1,
            )

    def test_cli_rejects_invalid_tag(self) -> None:
        self.assertEqual(check_release_notes.main(["not-a-tag"]), 1)

    def test_live_notes_pass_for_current_version(self) -> None:
        # The tracked notes for the released version must satisfy the gate the
        # release workflow now enforces, so a regression is caught locally.
        root = pathlib.Path(__file__).resolve().parents[2]
        released = sorted(
            (root / "docs" / "releases").glob("v2.3.*.md"), reverse=True
        )
        self.assertTrue(released, "expected at least one v2.3.x notes file")
        failures = check_release_notes.validate_notes(
            released[0].read_text(encoding="utf-8")
        )
        self.assertEqual(failures, [], f"{released[0].name}: {failures}")


if __name__ == "__main__":
    unittest.main()
