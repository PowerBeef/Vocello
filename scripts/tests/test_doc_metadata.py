#!/usr/bin/env python3
"""Unit tests for scripts/doc_metadata.py.

The regression that motivated the whole design has its own test: a document
saying "10 x 3" must be caught even though the commit that broke it *did* edit
the document, which is exactly why a git co-change check alone is not enough.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doc_metadata import (  # noqa: E402
    body_digest,
    render_index,
    scan_text,
    split_frontmatter,
)

FACTS = {
    "deliveryPresetCount": {"value": 10, "source": "x"},
    "deliveryIntensityTiers": {"value": 2, "source": "x"},
    "qwenSpeakerCount": {"value": 9, "source": "x"},
    "stableMacReleaseVersion": {"value": "2.4.0", "source": "x"},
    "canonicalMacBenchmarkChip": {"value": "Apple M2", "source": "x"},
}


def matched(text):
    return {f["matched"] for f in scan_text(text, FACTS)}


class FactScanTests(unittest.TestCase):
    def test_the_regression_that_motivated_this(self):
        # docs/reference/qwen3-tts-guide.md line 489, 2026-08-01 to 2026-08-02.
        self.assertEqual(matched("| EmotionPreset.swift | 10 × 3 presets |"), {"10 × 3"})

    def test_both_multiplication_spellings(self):
        self.assertTrue(matched("10 x 3 presets"))
        self.assertTrue(matched("10 × 4 presets"))

    def test_the_correct_product_passes(self):
        self.assertEqual(matched("10 × 2 presets"), set())
        self.assertEqual(matched("10 x 2 presets"), set())

    def test_multiplication_chains_are_arithmetic_not_tier_claims(self):
        # docs/reference/mimi-codec-guide.md line 160, 2026-08-05: the SEANet
        # upsample product "2 × 2 × 10 × 5 × 4 × 3" false-matched on "10 × 5".
        self.assertEqual(matched("2 × 2 × 10 × 5 × 4 × 3 = 2,400"), set())
        self.assertEqual(matched("a 10 × 5 × 4 chain tail"), set())
        # A standalone wrong product still fails.
        self.assertEqual(matched("the 10 × 5 delivery matrix"), {"10 × 5"})

    def test_spelled_and_numeric_forms_of_the_true_count_both_pass(self):
        # Only excluding the word form let "2 intensities" fail as a false
        # positive on the real corpus.
        self.assertEqual(matched("two intensity tiers"), set())
        self.assertEqual(matched("2 intensities"), set())

    def test_a_wrong_spelled_count_is_caught(self):
        self.assertTrue(matched("three intensity tiers"))
        self.assertTrue(matched("four intensities"))

    def test_selection_prose_is_not_a_count_claim(self):
        # "one intensity tier and not the other" describes which tier, not how
        # many exist; requiring a plural noun is what separates them.
        self.assertEqual(matched("applied to one intensity tier and not the other"), set())

    def test_a_match_never_spans_a_line_break(self):
        self.assertEqual(matched("three presets trip it on one\nintensity tier"), set())

    def test_preset_and_speaker_counts(self):
        self.assertTrue(matched("8 emotion presets"))
        self.assertTrue(matched("12 built-in speakers"))
        self.assertEqual(matched("10 delivery presets"), set())
        self.assertEqual(matched("9 built-in speakers"), set())

    def test_findings_carry_a_line_number(self):
        findings = scan_text("ok\nok\n10 × 3 presets\n", FACTS)
        self.assertEqual(findings[0]["line"], 3)


class ReleaseFactTests(unittest.TestCase):
    """CLAUDE.md and README.md are fact-scanned; these are the claims that drift."""

    def test_a_stale_current_release_claim_is_caught(self):
        self.assertTrue(matched("macOS **2.3.0** is the current release"))
        self.assertTrue(matched("2.3.0 is the current macOS release"))

    def test_the_true_current_release_passes(self):
        self.assertEqual(matched("macOS **2.4.0** is the current release"), set())

    def test_version_numbers_outside_a_currency_claim_are_ignored(self):
        # Release notes and history legitimately name old versions; only the
        # claim about which release is current may not drift.
        for text in ("v2.3.0 was cut 2026-07-31",
                     "the v2.3.0 auto-generated stub was fixed post-publication",
                     "upgrading from 1.2.3 requires a fresh install"):
            self.assertEqual(matched(text), set(), text)

    def test_the_wrong_canonical_mac_is_caught(self):
        # Standing risk: public performance copy citing M1 instead of the
        # canonical M2 machine.
        self.assertTrue(matched("measured on a Mac mini M1 8 GB"))
        self.assertTrue(matched("Mac mini (M1, 8 GB)"))

    def test_the_canonical_mac_passes(self):
        for text in ("Mac mini M2 8 GB", "Mac mini (M2, 8 GB)", "canonical Mac mini M2"):
            self.assertEqual(matched(text), set(), text)

    def test_other_apple_silicon_mentions_are_not_claims_about_the_canonical_mac(self):
        for text in ("M1 Max throughput", "an M1 Pro laptop", "Apple M3 results"):
            self.assertEqual(matched(text), set(), text)


class FrontmatterTests(unittest.TestCase):
    def test_a_document_without_frontmatter_is_recognised(self):
        meta, body = split_frontmatter("# Title\n\ntext\n")
        self.assertIsNone(meta)
        self.assertEqual(body, "# Title\n\ntext\n")

    def test_scalars_and_lists_parse(self):
        meta, body = split_frontmatter(
            "---\nstatus: active\nowner: backend-mlx\n"
            "sourceOfTruth:\n  - a.swift\n  - b.json\n---\n# Title\n"
        )
        self.assertEqual(meta["status"], "active")
        self.assertEqual(meta["sourceOfTruth"], ["a.swift", "b.json"])
        self.assertEqual(body, "# Title\n")

    def test_an_unterminated_block_is_an_error(self):
        with self.assertRaises(ValueError):
            split_frontmatter("---\nstatus: active\n# Title\n")

    def test_quotes_are_stripped(self):
        meta, _ = split_frontmatter('---\nsummary: "a, b"\n---\nx\n')
        self.assertEqual(meta["summary"], "a, b")


class DigestTests(unittest.TestCase):
    def test_the_digest_covers_the_body_only(self):
        # Metadata on a pinned document must be correctable without breaking the
        # seal on its content.
        one = "---\nstatus: historical\nsummary: a\n---\nBODY\n"
        two = "---\nstatus: historical\nsummary: CHANGED\n---\nBODY\n"
        self.assertEqual(body_digest(split_frontmatter(one)[1]),
                         body_digest(split_frontmatter(two)[1]))

    def test_a_body_edit_changes_the_digest(self):
        self.assertNotEqual(body_digest("BODY\n"), body_digest("BODY edited\n"))


class IndexTests(unittest.TestCase):
    def test_the_index_reports_annotated_and_unannotated_counts(self):
        import pathlib
        payload = render_index(pathlib.Path(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ))
        self.assertGreaterEqual(payload["annotatedDocuments"], 3)
        self.assertGreater(payload["unannotatedDocuments"], 0)
        statuses = {d["status"] for d in payload["documents"]}
        self.assertTrue({"active", "historical", "superseded"} <= statuses,
                        "the prototype must exercise every mode")
        for document in payload["documents"]:
            self.assertTrue(document["summary"], f"{document['path']} needs a summary")
            if document["status"] in ("historical", "superseded"):
                self.assertIn("contentDigest", document)


if __name__ == "__main__":
    unittest.main()
