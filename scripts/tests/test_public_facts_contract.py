#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("public_facts_contract", ROOT / "scripts/public_facts_contract.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseIdentityTests(unittest.TestCase):
    STABLE = {"stableMacRelease": {"version": "2.4.0", "tag": "v2.4.0"}}

    def test_project_version_must_match_the_declared_release(self) -> None:
        self.assertEqual(MODULE.validate_release_identity(self.STABLE, 'MARKETING_VERSION: "2.4.0"\n'), [])
        errors = MODULE.validate_release_identity(self.STABLE, 'MARKETING_VERSION: "2.5.0"\n')
        self.assertTrue(any("project version" in e for e in errors), errors)

    def test_candidate_must_be_unpublished_newer_and_tag_matched(self) -> None:
        public = dict(self.STABLE, candidateRelease={"version": "3.0.0", "tag": "v3.0.0", "distributionStatus": "unpublished"})
        self.assertEqual(MODULE.validate_release_identity(public, 'MARKETING_VERSION: "3.0.0"\n'), [])
        stale = dict(self.STABLE, candidateRelease={"version": "2.3.0", "tag": "v2.3.0", "distributionStatus": "unpublished"})
        self.assertTrue(any("candidate" in e for e in MODULE.validate_release_identity(stale, 'MARKETING_VERSION: "2.3.0"\n')))
        published = dict(self.STABLE, candidateRelease={"version": "3.0.0", "tag": "v3.0.0", "distributionStatus": "published"})
        self.assertTrue(any("candidate" in e for e in MODULE.validate_release_identity(published, 'MARKETING_VERSION: "3.0.0"\n')))

    def test_stable_tag_must_match_version(self) -> None:
        errors = MODULE.validate_release_identity({"stableMacRelease": {"version": "2.4.0", "tag": "v2.4.1"}}, 'MARKETING_VERSION: "2.4.0"\n')
        self.assertTrue(any("tag/version" in e for e in errors), errors)


class BenchmarkProfileTests(unittest.TestCase):
    def write_root(self, root: Path) -> None:
        (root / "benchmarks").mkdir()
        (root / "benchmarks/hardware-profiles.json").write_text(json.dumps({"profiles": [
            {"id": "mac-mini-m2-8gb", "platform": "macos", "canonical": False},
            {"id": "mac-mini-m6-16gb", "platform": "macos", "canonical": True},
            {"id": "iphone-17-pro", "platform": "ios", "canonical": True},
        ]}), encoding="utf-8")

    def test_declared_profiles_must_be_the_registry_canonical_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_root(root)
            current = {"canonicalBenchmarkProfiles": {"macos": "mac-mini-m6-16gb", "ios": "iphone-17-pro"}}
            self.assertEqual(MODULE.validate_benchmark_profiles(root, current), [])
            retired = {"canonicalBenchmarkProfiles": {"macos": "mac-mini-m2-8gb", "ios": "iphone-17-pro"}}
            errors = MODULE.validate_benchmark_profiles(root, retired)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("mac-mini-m2-8gb", errors[0])


class CandidateClaimTests(unittest.TestCase):
    PUBLIC = {
        "stableMacRelease": {"version": "2.4.0", "tag": "v2.4.0"},
        "candidateRelease": {"version": "3.0.0", "tag": "v3.0.0", "distributionStatus": "unpublished"},
        "candidateOnlyClaims": {"terms": ["AudioSeal", "eight delivery presets"]},
    }

    def validate(self, readme: str, website: str = "", public: dict | None = None, page: str = "") -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(readme, encoding="utf-8")
            (root / "website/src").mkdir(parents=True)
            (root / "website/src/Section.jsx").write_text(website, encoding="utf-8")
            (root / "website/public/privacy").mkdir(parents=True)
            (root / "website/public/privacy/index.html").write_text(page, encoding="utf-8")
            return MODULE.validate_candidate_claims(root, public or self.PUBLIC)

    def test_candidate_feature_next_to_the_stable_download_fails(self) -> None:
        errors = self.validate("- Generated audio carries an inaudible AudioSeal watermark.\n")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'AudioSeal'", errors[0])

    def test_candidate_feature_labelled_with_the_candidate_version_passes(self) -> None:
        readme = "- **(3.0)** Generated audio carries an inaudible AudioSeal watermark.\n"
        website = "<p>\n  In 3.0, Built-in Voice offers one of eight delivery\n  presets.\n</p>\n"
        self.assertEqual(self.validate(readme, website), [])

    def test_website_copy_is_checked_across_wrapped_lines(self) -> None:
        errors = self.validate("", "<p>\n  Built-in Voice offers one of eight delivery\n  presets.\n</p>\n")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("website/src/Section.jsx", errors[0])

    def test_other_version_numbers_do_not_count_as_the_candidate(self) -> None:
        errors = self.validate("- Vocello 13.0.1 adds an AudioSeal watermark.\n")
        self.assertEqual(len(errors), 1, errors)
        errors = self.validate("- Vocello 3.0.1 adds an AudioSeal watermark.\n")
        self.assertEqual(len(errors), 1, errors)

    def test_a_measurement_is_not_a_version_label(self) -> None:
        for readme in (
            "Peaks stay near 3.0 GB. Generated audio carries an inaudible AudioSeal watermark.\n",
            "Peak memory in 3.0 GB. Generated audio carries an inaudible AudioSeal watermark.\n",
            "Peaks stay low (3.0 GB). Generated audio carries an inaudible AudioSeal watermark.\n",
        ):
            with self.subTest(readme=readme):
                self.assertEqual(len(self.validate(readme)), 1, readme)
        self.assertEqual(self.validate("Vocello 3.0.0 marks audio with AudioSeal.\n"), [])

    def test_public_html_pages_are_checked(self) -> None:
        errors = self.validate("", page="<p>Generated audio carries an AudioSeal watermark.</p>\n")
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("website/public/privacy/index.html", errors[0])
        self.assertEqual(self.validate("", page="<p>In Vocello 3.0, audio carries an AudioSeal watermark.</p>\n"), [])

    def test_claims_require_an_unpublished_candidate(self) -> None:
        public = {key: value for key, value in self.PUBLIC.items() if key != "candidateRelease"}
        errors = self.validate("", public=public)
        self.assertTrue(any("requires an unpublished candidateRelease" in e for e in errors), errors)


class RepositoryTests(unittest.TestCase):
    def test_repository_public_facts_hold(self) -> None:
        self.assertEqual(MODULE.validate(ROOT), [])


if __name__ == "__main__":
    unittest.main()
