#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
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


class RepositoryTests(unittest.TestCase):
    def test_repository_public_facts_hold(self) -> None:
        self.assertEqual(MODULE.validate(ROOT), [])


if __name__ == "__main__":
    unittest.main()
