#!/usr/bin/env python3
"""AQ-02 script pool: filters, deterministic seeded selection, splits, validation and the pinned fetch.

No network. The selection tests build small pools (four scripts per language)
from synthetic source files pinned by their own sizes and digests; the fetch
tests serve fixture bytes through a fake opener. One test validates the
committed pool (`config/audio-qc-script-pool.json`) against the committed
sources file, as the contract gate does.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_script_pool as pool_cli  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
RULES = {"perLanguage": 4, "languages": ["english", "french", "chinese"]}
SHARED = "The same small sentence appears in two of the language files today."
LEGACY_TEXT = "The morning train left the quiet station on time while the sunlight rose."
SOURCES_TEXT = {
    "english": [
        "The old dog slept by the warm fire all through the night.",
        "A small boat drifted slowly past the empty harbour at dusk.",
        "",
        "She painted the kitchen door a bright shade of green last week.",
        "The old dog slept by the warm fire, all through the night!",  # a duplicate after normalization
        "Children laughed as the kite climbed higher above the windy beach.",
        "We walked along the river until the lights of the town appeared.",
        "Our neighbours planted apple trees along the edge of the garden.",
        SHARED,  # also in the French file: dropped from both
        "The morning train left the quiet station on time.",  # inside the legacy script
        "The bus had 3 empty seats near the back of the vehicle.",  # digit
        "the letter arrived late on a cold and rainy winter morning.",  # lower-case start
        "The train left.",  # too short
        "THE WHOLE SENTENCE IS WRITTEN IN CAPITAL LETTERS FOR NO REASON.",
        "Visit www.example.com to read the rest of this long story.",
        " A leading space makes this line unusable for the pool.",
        "The cafe served борщ to every guest who came in from the cold.",
        "Yesterday we met Robin at the old market down by the river.",  # a proper name
    ],
    "french": [
        "Le petit chat dort tranquillement sur le rebord de la fenêtre.",
        "Nous avons marché le long de la rivière jusqu'au vieux moulin.",
        "Elle a préparé une soupe chaude pour toute la famille ce soir.",
        "Les enfants jouent dans le parc pendant que le soleil se couche.",
        "Mon voisin répare son vélo dans la cour depuis ce matin.",
        "Il pleuvait si fort que personne ne voulait sortir de la maison.",
        SHARED,
    ],
    "chinese": [
        "我们今天早上在公园里散步，看到了很多美丽的花。",
        "他每天晚上都会读一本书，然后早点睡觉。",
        "妈妈做的饭菜总是很好吃，大家都很喜欢。",
        "这个城市的秋天很凉快，适合出去走走。",
        "我們今天在車站等了很久，火車終於來了。",  # Traditional characters
        "我们今天用app买了很多东西，大家都很开心。",  # Latin letters
        "小猫在窗台上睡觉",  # no terminal punctuation, and too short
        "朋友们周末一起去山上看日出，大家都很兴奋。",
        "图书馆里非常安静，每个人都在认真地学习。",
    ],
}


def write_sources(root: Path, texts: dict[str, list[str]] = SOURCES_TEXT) -> dict:
    """Synthetic source files under root/<commit>/ and a sources document pinning them."""
    directory = root / COMMIT
    license_bytes = b"CC0 1.0 Universal\n"
    (directory / pool_cli.LICENSE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (directory / pool_cli.LICENSE_PATH).write_bytes(license_bytes)
    languages = []
    for language, lines in texts.items():
        locale = pool_cli.COMMON_VOICE_LOCALES[language]
        path = f"server/data/{locale}/sentence-collector.txt"
        data = ("\n".join(lines) + "\n").encode("utf-8")
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_bytes(data)
        languages.append({"language": language, "locale": locale, "path": path, "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
    return {
        "schemaVersion": 1, "kind": pool_cli.SOURCES_KIND, "description": "fixture",
        "repository": "common-voice/common-voice", "commit": COMMIT, "host": pool_cli.DOWNLOAD_HOST,
        "license": {"path": pool_cli.LICENSE_PATH, "spdx": "CC0-1.0", "bytes": len(license_bytes),
                    "sha256": hashlib.sha256(license_bytes).hexdigest()},
        "languages": languages,
    }


LEGACY = {"languages": [{"id": "english", "script": LEGACY_TEXT}]}


def funnel(pool: dict, language: str) -> dict[str, int]:
    summary = next(item for item in pool["languages"] if item["language"] == language)
    return {stage["stage"]: stage["remaining"] for stage in summary["candidateFunnel"]}


def redigest(pool: dict) -> dict:
    pool["poolDigest"] = pool_cli.pool_digest(pool["entries"])
    return pool


class FilterTests(unittest.TestCase):
    CASES = [
        ("english", " Leading whitespace makes this sentence unusable for the pool.", "wellFormed"),
        ("english", "Tabs\tinside a sentence make this line unusable for the pool.", "wellFormed"),
        ("english", "Please visit www.example.com for the rest of the long story.", "noUrlOrEmail"),
        ("english", "Write to anna@example.org if you want to hear the story.", "noUrlOrEmail"),
        ("english", "EVERY WORD OF THIS SENTENCE IS WRITTEN IN CAPITAL LETTERS.", "notAllCaps"),
        ("english", "The bus had 3 empty seats near the back of the long vehicle.", "corpusLint"),
        ("english", "The doctor, Mr Smith, arrived late to the meeting this morning.", "corpusLint"),
        ("english", "The price rose by ten % over the course of the last year.", "corpusLint"),
        ("english", "The cafe served борщ to every guest who came in from the cold.", "scriptMatch"),
        ("english", "The museum shows 中国 paintings to every visitor who comes in.", "scriptMatch"),
        ("russian", "Cтесненное положение перестало в последнее время тяготить его.", "scriptMatch"),
        ("chinese", "我們今天在車站等了很久，火車終於來了。", "scriptMatch"),
        ("chinese", "我们今天用app买了很多东西，大家都很开心。", "scriptMatch"),
        ("japanese", "東京大学図書館閲覧室利用規則改正案可決済。", "scriptMatch"),
        ("korean", "大韓民國의 수도는 서울이며 인구가 아주 많은 도시입니다.", "scriptMatch"),
        ("english", "the letter arrived late on a cold and rainy winter morning.", "sentenceForm"),
        ("english", "The letter arrived late on a cold and rainy winter morning", "sentenceForm"),
        ("english", "The letter arrived late on a cold... and rainy winter morning.", "sentenceForm"),
        ("english", "- The letter arrived late on a cold and rainy winter morning.", "sentenceForm"),
        ("russian", "Наследие Гагарина мы сохраним и в будущем.", "noProperNames"),
        ("french", "Et il a un œil de trop, ajouta Robin Poussepain.", "noProperNames"),
        ("french", "Jean-Pierre est parti très tôt ce matin pour la gare du nord.", "noProperNames"),
        ("spanish", "Fuimos al Museo del Prado para ver la exposición nueva.", "noProperNames"),
        ("english", "The letter arrived late.", "lengthWindow"),
        ("english", " ".join(["The long letter"] + ["arrived"] * 20) + ".", "lengthWindow"),
        ("chinese", "小猫在睡觉。", "lengthWindow"),
    ]

    def test_each_filter_refuses_its_case(self) -> None:
        for language, text, reason in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(pool_cli.text_rejection(text, language), reason)

    def test_valid_texts_pass(self) -> None:
        for language, text in [
            ("english", "The old dog slept by the warm fire all through the night."),
            ("spanish", "¿Dónde está la estación de tren más cercana a este hotel?"),
            ("russian", "Наследие нашей страны мы сохраним и в будущем."),
            ("english", "I think we should leave before the heavy rain starts tonight."),
            # Case cannot mark a name in German, where every noun is capitalized (a declared limitation).
            ("german", "Der alte Hund schlief die ganze Nacht am warmen Feuer."),
            ("chinese", "我们今天早上在公园里散步，看到了很多美丽的花。"),
            ("japanese", "全ての人が他人で関わりがなかった。"),
            ("korean", "그 순간 신철이는 선비를 멀리 바라보았다."),
        ]:
            with self.subTest(text=text):
                self.assertIsNone(pool_cli.text_rejection(text, language))

    def test_a_sentence_may_not_open_with_a_name_its_source_file_uses(self) -> None:
        lines = ["Il parla longtemps avec Poussepain hier soir au village.",
                 "Poussepain est parti très tôt ce matin pour la gare du nord.",
                 "Hier encore, Marie disait que marie était un joli prénom."]
        self.assertEqual(pool_cli.name_lexicon(lines, "french"), frozenset({"Poussepain"}),
                         "a word also written in lower case is no name; a sentence opener alone says nothing")
        opener = lines[1]
        self.assertIsNone(pool_cli.text_rejection(opener, "french"), "validate, without the source file")
        self.assertEqual(pool_cli.text_rejection(opener, "french", pool_cli.name_lexicon(lines, "french")),
                         "noProperNames")
        # English "I" is never a name, and German and the CJK languages have no case-marked names.
        self.assertEqual(pool_cli.name_lexicon(["Yesterday I went home early.", "I went home."], "english"),
                         frozenset())
        self.assertEqual(pool_cli.name_lexicon(["Gestern sah ich den Hund im Garten."], "german"), frozenset())

    def test_units_follow_the_scoring_normalization(self) -> None:
        self.assertEqual(pool_cli.unit_for("english"), "word")
        self.assertEqual(pool_cli.unit_for("chinese"), "character")
        self.assertEqual(pool_cli.unit_for("korean"), "syllable")
        self.assertEqual(len(pool_cli.normalized_units("Don't stop, it's fine.", "english")), 4)
        self.assertEqual(len(pool_cli.normalized_units("我们去公园。", "chinese")), 5)

    def test_legacy_overlap_is_containment_either_way(self) -> None:
        legacy = pool_cli.legacy_texts(LEGACY)
        self.assertTrue(pool_cli.overlaps_legacy("The morning train left the quiet station on time.", "english",
                                                 legacy))
        self.assertTrue(pool_cli.overlaps_legacy(LEGACY_TEXT + " Then it rained.", "english", legacy))
        self.assertFalse(pool_cli.overlaps_legacy("A small boat drifted past the harbour.", "english", legacy))


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = write_sources(self.root)
        self.pool = pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules=RULES)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_build_is_deterministic_and_independent_of_line_order(self) -> None:
        again = pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules=RULES)
        self.assertEqual(pool_cli.encode_pool(again), pool_cli.encode_pool(self.pool))
        with tempfile.TemporaryDirectory() as other:
            reversed_texts = {language: list(reversed(lines)) for language, lines in SOURCES_TEXT.items()}
            sources = write_sources(Path(other), reversed_texts)
            shuffled = pool_cli.build(sources, Path(other) / COMMIT, LEGACY, rules=RULES)
        # Order, ids and splits come from seeded hashes of the normalized text, never from line positions.
        self.assertEqual([(e["id"], e["text"], e["split"]) for e in shuffled["entries"]
                          if e["language"] != "english"],
                         [(e["id"], e["text"], e["split"]) for e in self.pool["entries"]
                          if e["language"] != "english"])

    def test_a_different_seed_selects_differently(self) -> None:
        other = pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules={**RULES, "seed": "another-seed"})
        self.assertNotEqual(other["poolDigest"], self.pool["poolDigest"])

    def test_funnel_counts_each_filter(self) -> None:
        self.assertEqual(funnel(self.pool, "english"), {
            "nonBlankLines": 17, "wellFormed": 16, "noUrlOrEmail": 15, "notAllCaps": 14, "corpusLint": 13,
            "scriptMatch": 12, "sentenceForm": 11, "noProperNames": 10, "lengthWindow": 9, "noLegacyOverlap": 8,
            "uniqueInLanguage": 7, "uniqueAcrossLanguages": 6, "selected": 4,
        })
        self.assertEqual(funnel(self.pool, "french")["uniqueAcrossLanguages"], 6)
        chinese = funnel(self.pool, "chinese")
        self.assertEqual((chinese["nonBlankLines"], chinese["scriptMatch"], chinese["sentenceForm"],
                          chinese["uniqueAcrossLanguages"]), (9, 7, 6, 6))
        texts = {entry["text"] for entry in self.pool["entries"]}
        self.assertNotIn(SHARED, texts)
        self.assertNotIn(LEGACY_TEXT, texts)

    def test_within_language_duplicates_keep_the_first_source_line(self) -> None:
        pool = pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules={**RULES, "perLanguage": 6})
        dog = [entry for entry in pool["entries"] if "old dog" in entry["text"]]
        self.assertEqual([(entry["text"], entry["sourceLine"]) for entry in dog],
                         [(SOURCES_TEXT["english"][0], 1)])

    def test_splits_are_disjoint_halves(self) -> None:
        for language in RULES["languages"]:
            entries = [entry for entry in self.pool["entries"] if entry["language"] == language]
            prefix = "zh" if language == "chinese" else language[:2]
            self.assertEqual([entry["id"] for entry in entries], [f"{prefix}-{index:04d}" for index in range(1, 5)])
            calibration = {entry["text"] for entry in entries if entry["split"] == "calibration"}
            confirmation = {entry["text"] for entry in entries if entry["split"] == "confirmation"}
            self.assertEqual((len(calibration), len(confirmation)), (2, 2))
            self.assertFalse(calibration & confirmation)
        for entry in self.pool["entries"]:
            self.assertEqual(entry["textSHA256"], hashlib.sha256(entry["text"].encode("utf-8")).hexdigest())
            self.assertEqual(SOURCES_TEXT[entry["language"]][entry["sourceLine"] - 1], entry["text"])

    def test_too_few_candidates_refuse(self) -> None:
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "fewer than 7"):
            pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules={**RULES, "perLanguage": 7})

    def test_a_source_that_differs_from_its_pin_refuses(self) -> None:
        path = self.root / COMMIT / self.sources["languages"][0]["path"]
        path.write_bytes(path.read_bytes().replace(b"dog", b"cat"))
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "differs from its pin"):
            pool_cli.build(self.sources, self.root / COMMIT, LEGACY, rules=RULES)

    def test_validate_passes_the_built_pool(self) -> None:
        self.assertEqual(pool_cli.validate(self.pool, self.sources, LEGACY, rules=RULES), [])

    def assertRefused(self, pool: dict, fragment: str) -> None:
        issues = pool_cli.validate(pool, self.sources, LEGACY, rules=RULES)
        self.assertTrue(any(fragment in issue for issue in issues), issues)

    def test_validate_refuses_a_tampered_text(self) -> None:
        pool = copy.deepcopy(self.pool)
        pool["entries"][0]["text"] = pool["entries"][0]["text"].replace("the", "a", 1)
        self.assertRefused(pool, "poolDigest does not match")
        self.assertRefused(redigest(pool), "textSHA256 does not match")

    def test_validate_refuses_a_tampered_digest(self) -> None:
        pool = copy.deepcopy(self.pool)
        pool["poolDigest"] = "0" * 64
        self.assertRefused(pool, "poolDigest does not match")

    def test_validate_refuses_a_swapped_split(self) -> None:
        pool = copy.deepcopy(self.pool)
        english = [entry for entry in pool["entries"] if entry["language"] == "english"]
        first = english[0]
        other = next(entry for entry in english if entry["split"] != first["split"])
        first["split"], other["split"] = other["split"], first["split"]
        self.assertRefused(redigest(pool), "split must be")

    def test_validate_refuses_an_unbalanced_split(self) -> None:
        pool = copy.deepcopy(self.pool)
        for entry in pool["entries"]:
            if entry["language"] == "french":
                entry["split"] = "calibration"
        self.assertRefused(redigest(pool), "splits hold")

    def test_validate_refuses_a_text_that_breaks_a_rule(self) -> None:
        pool = copy.deepcopy(self.pool)
        entry = pool["entries"][0]
        entry["text"] = "The bus had 3 empty seats near the back of the long vehicle."
        entry["textSHA256"] = hashlib.sha256(entry["text"].encode("utf-8")).hexdigest()
        self.assertRefused(redigest(pool), "fails the corpusLint rule")

    def test_validate_refuses_a_cross_language_duplicate(self) -> None:
        pool = copy.deepcopy(self.pool)
        english = next(entry for entry in pool["entries"] if entry["language"] == "english")
        french = next(entry for entry in pool["entries"] if entry["language"] == "french")
        french.update(text=english["text"], textSHA256=english["textSHA256"], length=english["length"])
        self.assertRefused(redigest(pool), "duplicates en-0001")

    def test_validate_refuses_a_changed_rule_or_source(self) -> None:
        pool = copy.deepcopy(self.pool)
        pool["selection"]["lengthWindows"]["windows"]["english"]["max"] = 30
        self.assertRefused(pool, "selection block differs")
        sources = copy.deepcopy(self.sources)
        sources["languages"][0]["sha256"] = "f" * 64
        issues = pool_cli.validate(self.pool, sources, LEGACY, rules=RULES)
        self.assertTrue(any("summary differs" in issue for issue in issues), issues)


class CommittedPoolTests(unittest.TestCase):
    def test_committed_pool_validates(self) -> None:
        pool = pool_cli.load_json(pool_cli.POOL_PATH)
        sources = pool_cli.load_json(pool_cli.SOURCES_PATH)
        legacy = pool_cli.load_json(pool_cli.LEGACY_CORPUS_PATH)
        self.assertEqual(pool_cli.validate(pool, sources, legacy), [])
        self.assertEqual(pool_cli.encode_pool(pool), pool_cli.POOL_PATH.read_bytes())
        self.assertEqual(pool_cli.main(["validate"]), 0)
        self.assertEqual([item["language"] for item in pool["languages"]], list(pool_cli.lm.PRODUCT_LANGUAGES))
        self.assertEqual(len(pool["entries"]), 1200)

    def test_committed_sources_pin_the_ten_locales(self) -> None:
        sources = pool_cli.load_json(pool_cli.SOURCES_PATH)
        self.assertEqual(pool_cli.sources_issues(sources), [])
        self.assertEqual([entry["locale"] for entry in sources["languages"]],
                         ["en", "fr", "de", "es", "it", "pt", "ru", "zh-CN", "ja", "ko"])


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.status = status
        self._payload = payload
        self._position = 0

    def read(self, size: int) -> bytes:
        block = self._payload[self._position:self._position + size]
        self._position += len(block)
        return block

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc) -> None:
        return None


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.origin = Path(self.temporary.name) / "origin"
        self.sources = write_sources(self.origin)
        self.cache = Path(self.temporary.name) / "cache"
        self.requests: list[str] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fetch(self, overrides: dict[str, bytes] | None = None) -> list[dict]:
        return pool_cli.fetch(self.sources, root=self.cache, opener=self.opener(overrides),
                              languages=RULES["languages"])

    def opener(self, overrides: dict[str, bytes] | None = None):
        prefix = f"https://{pool_cli.DOWNLOAD_HOST}/common-voice/common-voice/{COMMIT}/"

        def open_url(request: urllib.request.Request, _timeout: float) -> FakeResponse:
            self.requests.append(request.full_url)
            self.assertTrue(request.full_url.startswith(prefix))
            path = request.full_url.removeprefix(prefix)
            if overrides and path in overrides:
                return FakeResponse(overrides[path])
            return FakeResponse((self.origin / COMMIT / path).read_bytes())
        return open_url

    def test_fetch_writes_verified_files_and_then_reuses_them(self) -> None:
        report = self.fetch()
        self.assertEqual({item["status"] for item in report}, {"fetched"})
        for pin in pool_cli.pinned_files(self.sources):
            self.assertTrue(pool_cli.verified_file(self.cache / COMMIT / pin["path"], pin))
        self.requests.clear()
        report = self.fetch()
        self.assertEqual({item["status"] for item in report}, {"present"})
        self.assertEqual(self.requests, [])

    def test_fetch_refuses_a_digest_mismatch_and_writes_nothing(self) -> None:
        pin = self.sources["languages"][0]
        original = (self.origin / COMMIT / pin["path"]).read_bytes()
        tampered = original.replace(b"dog", b"cat")
        self.assertEqual(len(tampered), len(original))
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "does not match its pinned SHA-256"):
            self.fetch({pin["path"]: tampered})
        self.assertFalse((self.cache / COMMIT / pin["path"]).exists())

    def test_fetch_refuses_a_size_mismatch(self) -> None:
        pin = self.sources["languages"][1]
        longer = (self.origin / COMMIT / pin["path"]).read_bytes() + b"Extra line.\n"
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "pinned"):
            self.fetch({pin["path"]: longer})
        self.assertFalse((self.cache / COMMIT / pin["path"]).exists())

    def test_fetch_refuses_a_present_file_that_differs(self) -> None:
        pin = self.sources["license"]
        target = self.cache / COMMIT / pin["path"]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"not the license\n")
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "differs from its pin"):
            self.fetch()

    def test_only_https_on_the_pinned_host_and_no_redirects(self) -> None:
        self.assertTrue(pool_cli.allowed_url(f"https://{pool_cli.DOWNLOAD_HOST}/a/b"))
        for url in (f"http://{pool_cli.DOWNLOAD_HOST}/a", "https://github.com/a",
                    f"https://{pool_cli.DOWNLOAD_HOST}:8443/a", f"https://user@{pool_cli.DOWNLOAD_HOST}/a",
                    f"https://{pool_cli.DOWNLOAD_HOST}.evil.example/a"):
            self.assertFalse(pool_cli.allowed_url(url), url)
        request = urllib.request.Request(f"https://{pool_cli.DOWNLOAD_HOST}/a")
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "redirected"):
            pool_cli._RefuseRedirects().redirect_request(request, None, 302, "Found", {},
                                                         f"https://{pool_cli.DOWNLOAD_HOST}/b")

    def test_fetch_refuses_an_invalid_sources_file(self) -> None:
        sources = copy.deepcopy(self.sources)
        sources["host"] = "example.com"
        with self.assertRaisesRegex(pool_cli.ScriptPoolError, "host must be"):
            pool_cli.fetch(sources, root=self.cache, opener=self.opener(), languages=RULES["languages"])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
