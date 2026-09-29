#!/usr/bin/env python3
"""The CC0 ten-language script pool for audio QC qualification (AQ-02, audit sections 5.3-5.5).

The pool (`config/audio-qc-script-pool.json`) is the script source for natural
Vocello calibration takes (population N3) in detector qualification (AQ-07),
and later for matched human recordings (N1) and their codec resyntheses (N2).
Its texts are Common Voice Sentence Collector submissions, reviewed by people
and dedicated to the public domain under CC0 1.0, read from one pinned commit
of `common-voice/common-voice` (`config/audio-qc-script-pool-sources.json`
pins the commit and every file's size and SHA-256).

Selection is a pure function of the pinned files, the legacy corpus and the
rules below (`RULES_VERSION`), so the pool rebuilds byte for byte:

- **Corpus lint.** Every text passes `script_lint_issues(text, language)`: no
  digits, symbols, brackets or abbreviations.
- **Form.** No leading or trailing whitespace or control characters, no URL
  or email, not all capitals, and one complete sentence form: it starts with a
  letter (Spanish may open with an inverted mark), a capital in a cased
  script, ends with a full stop, question or exclamation mark, and holds no
  ellipsis.
- **No proper names** (rules v2). Recognizers spell names their own way, so a
  name makes a correct take read as a content error (in the first cohort,
  French "ajouta Robin Poussepain"). In the languages whose case marks names
  (English, French, Spanish, Italian, Portuguese, Russian), a word that opens
  no sentence may not start with a capital (English "I" excepted), no word
  may hold a capital after its first letter ("Jean-Pierre", "L'Oréal"), and a
  sentence may not open with a word its own source file writes capitalized
  inside sentences and never in lower case (a name lexicon derived from the
  pinned file). Case cannot mark names in German (every noun is capitalized)
  or in Chinese, Japanese and Korean: their names are not detected, a declared
  limitation. The per-text part is checked by `validate`; the lexicon part
  needs the source file, so `validate --rebuild` checks it.
- **Script.** Every letter is in the language's script: Latin for the six
  Latin-script languages, Cyrillic for Russian, Han for Chinese (Simplified
  only: no character the committed Hant-Hans fold table would change), Han
  and kana for Japanese (at least one kana), Hangul syllables for Korean. So a
  CJK text holds no Latin letter and an alphabetic text no CJK.
- **Length.** A window per language in its scoring unit
  (`language_metrics.normalized_tokens`: normalized words for alphabetic
  languages, normalized characters for Chinese and Japanese, Hangul syllables
  for Korean), sized for TTS takes of about 3-8 s.
- **Uniqueness.** No two texts share a normalized unit sequence, within a
  language (the first source line is kept) or across languages (every copy is
  dropped), and no text overlaps a legacy `config/language-bench-corpus.json`
  script (either normalized sequence contains the other).
- **Seeded selection.** Candidates are ordered by SHA-256 of the seed, the
  language and the normalized text; the first 120 are the pool, with ids in
  that order (`en-0001`). A second seeded hash of the normalized text ranks the
  120, and the lower 60 are `calibration`, the upper 60 `confirmation`.

The pool records the candidate count after every filter per language, so the
funnel is auditable, and a `poolDigest` over the canonical JSON of its entries.

Commands:
  fetch     download the pinned files from raw.githubusercontent.com into
            build/cache/audio-qc-corpora/common-voice-sentences/<commit>/
            (QVOICE_AUDIO_QC_CORPORA_CACHE); refuses any size or digest
            mismatch and any redirect
  build     select the pool from the fetched files and write
            config/audio-qc-script-pool.json
  validate  check the committed pool against its rules and the sources file
            (no network); `--rebuild` also rebuilds it from fetched files and
            requires identical bytes
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import language_metrics as lm  # noqa: E402
from lib.jsonio import atomic_write_bytes, canonical_bytes, pretty_bytes  # noqa: E402

REPO = SCRIPT_DIR.parent
SOURCES_PATH = REPO / "config" / "audio-qc-script-pool-sources.json"
POOL_PATH = REPO / "config" / "audio-qc-script-pool.json"
LEGACY_CORPUS_PATH = REPO / "config" / "language-bench-corpus.json"
CACHE_ENV = "QVOICE_AUDIO_QC_CORPORA_CACHE"
CACHE_SUBDIRECTORY = "common-voice-sentences"

POOL_KIND = "audio-qc-script-pool"
SOURCES_KIND = "audio-qc-script-pool-sources"
SCHEMA_VERSION = 1
POOL_VERSION = 2
RULES_VERSION = "audio-qc-script-pool-rules-v2"
SEED = "vocello-aq02-common-voice-script-pool-v1"
DOWNLOAD_HOST = "raw.githubusercontent.com"
DOWNLOAD_TIMEOUT_SECONDS = 120
MAX_SOURCE_BYTES = 64 * 1024 * 1024
USER_AGENT = "vocello-audio-qc-script-pool/1"

# The Common Voice locale of each product language (`lm.PRODUCT_LANGUAGES`).
COMMON_VOICE_LOCALES: dict[str, str] = {
    "english": "en",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh-CN",
    "japanese": "ja",
    "korean": "ko",
}
SOURCE_PATH_PATTERN = re.compile(r"server/data/([A-Za-z-]+)/sentence-collector\.txt")
LICENSE_PATH = "server/data/LICENSE"
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")

# The letter scripts each language may write, and which must appear.
LANGUAGE_SCRIPTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    **{language: (frozenset({"latin"}), frozenset({"latin"}))
       for language in ("english", "french", "german", "spanish", "italian", "portuguese")},
    "russian": (frozenset({"cyrillic"}), frozenset({"cyrillic"})),
    "chinese": (frozenset({"han"}), frozenset({"han"})),
    "japanese": (frozenset({"han", "kana"}), frozenset({"kana"})),
    "korean": (frozenset({"hangul"}), frozenset({"hangul"})),
}
UNITS = {"chinese": "character", "japanese": "character", "korean": "syllable"}
# Windows in the scoring unit for takes of about 3-8 s at nominal read rates;
# `LENGTH_BASIS` (the pool's `selection.lengthWindows.basis`) records the
# measured distributions of the pinned files that fixed them.
LENGTH_WINDOWS: dict[str, tuple[int, int]] = {
    **{language: (8, 20) for language in ("english", "french", "german", "spanish", "italian", "portuguese")},
    "russian": (7, 16),
    "chinese": (12, 40),
    "japanese": (16, 44),
    "korean": (16, 44),
}
LENGTH_BASIS = (
    "Nominal read rates: about 2.5 normalized words/s for the Latin-script languages (8-20 words is about "
    "3.2-8 s), 2.1 for Russian, whose words are longer (7-16 words, about 3.3-7.6 s), 4.5-5 characters/s "
    "for Mandarin (12-40 characters, about 2.7-8.5 s) and 5.5 characters/s for Japanese or syllables/s for "
    "Korean (16-44, about 2.9-8 s). Measured on the pinned files over the texts that pass every other "
    "per-text rule (median, 75th and 90th percentile): English 8/10/12 words, French 7/10/12, German "
    "7/9/12, Spanish 6/9/11, Italian 7/10/12, Portuguese 8/10/13, Russian 9/12/13; Chinese 22/34/56 "
    "characters, Japanese 24/34/43, Korean 22/28/33 syllables. The alphabetic windows therefore keep the "
    "upper half of short, mostly single-clause sentences. Chinese is the binding language: its file has "
    "541 lines and 213 pass the other rules, so its window is the widest that stays near 3-8 s (136 in "
    "window; 14-36 would keep 119, too few for 120)."
)
PER_LANGUAGE = 120
SPLITS = ("calibration", "confirmation")
TERMINAL_PUNCTUATION = frozenset(".!?。")
LEADING_MARKS = {"spanish": frozenset("¿¡")}
ELLIPSES = ("...", "…")
URL_OR_EMAIL = re.compile(r"(?i)(?:https?:|www\.|\b[\w.+-]+@[\w-]+\.[\w.-]+|\b[\w-]+\.(?:com|org|net|de|fr|ru|io)\b)")
FILTERS = (
    "wellFormed", "noUrlOrEmail", "notAllCaps", "corpusLint", "scriptMatch", "sentenceForm", "noProperNames",
    "lengthWindow", "noLegacyOverlap", "uniqueInLanguage", "uniqueAcrossLanguages",
)
# Languages whose letter case marks proper names; the others' names are not detected (a declared limitation).
NAME_CASE_LANGUAGES = ("english", "french", "spanish", "italian", "portuguese", "russian")
NAMES_UNDETECTED = {
    "german": "every German noun is capitalized, so case does not mark a name",
    "chinese": "the script has no letter case",
    "japanese": "the script has no letter case",
    "korean": "the script has no letter case",
}
# A word: letters, joined by an apostrophe or a hyphen ("l'homme", "Jean-Pierre").
NAME_WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")
ENGLISH_I = frozenset({"i", "i'm", "i've", "i'd", "i'll", "i’m", "i’ve", "i’d", "i’ll"})
POOL_DESCRIPTION = (
    "AQ-02 script pool (rules v2, which refuse proper names where letter case marks them): CC0 Common Voice "
    "Sentence Collector sentences in the product's ten languages, 120 per "
    "language (60 calibration, 60 confirmation, disjoint by script), selected deterministically from one "
    "pinned commit (config/audio-qc-script-pool-sources.json) by scripts/audio_qc_script_pool.py. It is the "
    "script source for natural Vocello calibration takes (N3) in detector qualification (AQ-07) and for the "
    "later matched human recordings (N1) and their codec resyntheses (N2). Texts only: no audio is in the "
    "pool or in Git; Common Voice audio comes from the Mozilla Data Collective under its own terms and is "
    "never committed, and FLEURS is the fallback N1 source. Deferred: the per-language hard-case pool (the "
    "seed-tts test-hard design) and the digits and abbreviations diagnostic pool. "
    "config/language-bench-corpus.json stays the legacy cohort."
)
ATTRIBUTION = (
    "Sentences from the Mozilla Common Voice Sentence Collector (github.com/common-voice/common-voice, "
    "server/data), dedicated to the public domain under CC0 1.0 Universal by their contributors. "
    "Attribution is not required; it is given as a courtesy."
)


class ScriptPoolError(RuntimeError):
    """A pin, a download or a rule failed; nothing unverified is written."""


Opener = Callable[[urllib.request.Request, float], Any]


# --- rules --------------------------------------------------------------------------------------------


def selection_block(rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The pool's selection block: every parameter that decides which texts it holds."""
    block = {
        "rulesVersion": RULES_VERSION,
        "seed": SEED,
        "perLanguage": PER_LANGUAGE,
        "splits": {split: PER_LANGUAGE // len(SPLITS) for split in SPLITS},
        "textNormalization": lm.TEXT_NORMALIZATION,
        "units": {language: unit_for(language) for language in COMMON_VOICE_LOCALES},
        "lengthWindows": {
            "basis": LENGTH_BASIS,
            "windows": {language: {"min": low, "max": high} for language, (low, high) in LENGTH_WINDOWS.items()},
        },
        "filters": list(FILTERS),
        "orderHash": "sha256(seed + NUL + language + NUL + normalizedText)",
        "splitHash": "sha256(seed + NUL + 'split' + NUL + language + NUL + normalizedText); the lower half is calibration",
        "normalizedText": ("language_metrics.normalized_tokens joined by one space for word languages and "
                           "with no separator for character languages"),
        "legacyCorpus": "config/language-bench-corpus.json",
        "properNames": {
            "languages": list(NAME_CASE_LANGUAGES),
            "notDetected": dict(NAMES_UNDETECTED),
            "word": "letters joined by an apostrophe or a hyphen; a word opens a sentence when it is the first or "
                    "follows . ! ? since the previous word",
            "lexicon": "per language, the words of the pinned source file written capitalized where they open no "
                       "sentence and never in lower case anywhere (English I excluded); checked by build and "
                       "validate --rebuild, since validate reads no source file",
        },
        "rules": [
            "well formed: no leading or trailing whitespace and no control or format characters",
            "no URL or email address",
            "not all capitals",
            "corpus lint: language_metrics.script_lint_issues(text, language) is empty (no digits, symbols, "
            "brackets or abbreviations)",
            "script: every letter is in the language's script (Latin; Cyrillic for Russian; Han for Chinese, "
            "Simplified only under config/language-normalization/hant-hans-v1.txt; Han and kana for Japanese, "
            "with at least one kana; Hangul syllables for Korean)",
            "sentence form: starts with a letter (Spanish may open with an inverted mark), a capital in a cased "
            "script, ends with . ! ? or the ideographic full stop, and holds no ellipsis",
            "no proper names, where case marks them (properNames): no capitalized word that opens no sentence "
            "(English I excepted), no capital after a word's first letter, and no sentence-opening word the "
            "language's source file capitalizes inside sentences and never writes in lower case",
            "length: the normalized unit count lies inside the language's window",
            "no overlap with a legacy corpus script: neither normalized text contains the other",
            "unique within the language (the first source line is kept) and across languages (every copy is dropped)",
        ],
    }
    if rules:
        block.update(rules)
        block["splits"] = {split: block["perLanguage"] // len(SPLITS) for split in SPLITS}
    return block


def unit_for(language: str) -> str:
    return UNITS.get(language, "word")


def letter_script(character: str) -> str:
    name = unicodedata.name(character, "")
    if name.startswith("LATIN"):
        return "latin"
    if name.startswith("CYRILLIC"):
        return "cyrillic"
    if name.startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH")) or character == "々":
        return "han"
    if name.startswith(("HIRAGANA", "KATAKANA")):
        return "kana"
    if name.startswith("HANGUL SYLLABLE"):
        return "hangul"
    return "other"


def normalized_units(text: str, language: str) -> list[str]:
    """The scoring units: normalized words, or characters for the character-scored languages."""
    tokens = lm.normalized_tokens(text, language)
    return lm.character_units(tokens) if language in lm.CHARACTER_ERROR_LANGUAGES else tokens


def normalized_text(text: str, language: str) -> str:
    tokens = lm.normalized_tokens(text, language)
    return "".join(tokens) if language in lm.CHARACTER_ERROR_LANGUAGES else " ".join(tokens)


def _script_matches(text: str, language: str) -> bool:
    allowed, required = LANGUAGE_SCRIPTS[language]
    seen: set[str] = set()
    for form in (text, unicodedata.normalize("NFKC", text)):
        for character in form:
            if unicodedata.category(character)[0] == "L":
                script = letter_script(character)
                if script not in allowed:
                    return False
                seen.add(script)
    if not required <= seen:
        return False
    if language == "chinese":
        folded = lm.hant_hans_fold_table()
        return all(form.translate(folded) == form for form in (text, unicodedata.normalize("NFKC", text)))
    return True


def _all_caps(text: str) -> bool:
    cased = [character for character in text if character.isupper() or character.islower()]
    return len(cased) >= 2 and all(character.isupper() for character in cased)


def _sentence_form(text: str, language: str) -> bool:
    folded = unicodedata.normalize("NFKC", text)
    first = folded[0]
    if unicodedata.category(first)[0] != "L" and first not in LEADING_MARKS.get(language, ()):
        return False
    if folded[-1] not in TERMINAL_PUNCTUATION:
        return False
    initial = next(character for character in folded if unicodedata.category(character)[0] == "L")
    if initial.islower():
        return False  # a cased script opens a sentence with a capital

    return not any(ellipsis in folded for ellipsis in ELLIPSES)


def name_words(text: str) -> list[tuple[str, bool]]:
    """(word, opens a sentence) for each word: the first word, or the first after . ! ? opens one."""
    words: list[tuple[str, bool]] = []
    end = 0
    for match in NAME_WORD.finditer(text):
        opens = not words or any(mark in text[end:match.start()] for mark in ".!?")
        words.append((match.group(), opens))
        end = match.end()
    return words


def name_lexicon(lines: Sequence[str], language: str) -> frozenset[str]:
    """The words a language's source file capitalizes inside sentences and never writes in lower case."""
    if language not in NAME_CASE_LANGUAGES:
        return frozenset()
    capitalized: set[str] = set()
    lower: set[str] = set()
    for line in lines:
        for word, opens in name_words(line):
            if language == "english" and word.casefold() in ENGLISH_I:
                continue
            if not opens and word[0].isupper():
                capitalized.add(word)
            if word[0].islower():
                lower.add(word.casefold())
    return frozenset(word for word in capitalized if word.casefold() not in lower)


def names_proper_noun(text: str, language: str, names: frozenset[str] | None = None) -> bool:
    """True when case marks a proper name in `text` (`names`: the source file's lexicon, when known)."""
    if language not in NAME_CASE_LANGUAGES:
        return False
    for word, opens in name_words(text):
        if language == "english" and word.casefold() in ENGLISH_I:
            continue
        if any(character.isupper() for character in word[1:]):
            return True
        if word[0].isupper() and (not opens or (names is not None and word in names)):
            return True
    return False


def text_rejection(text: str, language: str, names: frozenset[str] | None = None) -> str | None:
    """The first per-text filter a text fails (a `FILTERS` name), or None when it passes them all.

    `names` is the language's name lexicon (`name_lexicon`); without it only the
    per-text part of the proper-name rule applies.
    """
    if (not text or text != text.strip()
            or any(unicodedata.category(character) in ("Cc", "Cf", "Zl", "Zp") for character in text)):
        return "wellFormed"
    if URL_OR_EMAIL.search(text):
        return "noUrlOrEmail"
    if _all_caps(text):
        return "notAllCaps"
    if lm.script_lint_issues(text, language):
        return "corpusLint"
    if not _script_matches(text, language):
        return "scriptMatch"
    if not _sentence_form(text, language):
        return "sentenceForm"
    if names_proper_noun(text, language, names):
        return "noProperNames"
    low, high = LENGTH_WINDOWS[language]
    if not low <= len(normalized_units(text, language)) <= high:
        return "lengthWindow"
    return None


def legacy_texts(corpus: Mapping[str, Any]) -> list[str]:
    """The normalized texts of the legacy corpus scripts, in the character form (no separators)."""
    result = []
    for entry in corpus.get("languages", []):
        script, language = entry.get("script"), entry.get("id")
        if isinstance(script, str) and isinstance(language, str):
            result.append("".join(lm.normalized_tokens(script, language)))
    return result


def overlaps_legacy(text: str, language: str, legacy: Sequence[str]) -> bool:
    compact = "".join(lm.normalized_tokens(text, language))
    return any(compact in script or script in compact for script in legacy)


def _hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def order_hash(language: str, normalized: str, seed: str = SEED) -> str:
    return _hash(seed, language, normalized)


def split_hash(language: str, normalized: str, seed: str = SEED) -> str:
    return _hash(seed, "split", language, normalized)


def pool_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_bytes(list(entries))).hexdigest()


# --- sources ------------------------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScriptPoolError(f"{path.name} cannot be read: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise ScriptPoolError(f"{path.name} is not a JSON object")
    return value


def sources_issues(sources: Any, languages: Sequence[str] = lm.PRODUCT_LANGUAGES) -> list[str]:
    """Why the sources file may not pin the pool (empty when it may)."""
    if not isinstance(sources, dict):
        return ["sources: not an object"]
    issues = []
    if sources.get("schemaVersion") != SCHEMA_VERSION or sources.get("kind") != SOURCES_KIND:
        issues.append("sources: schemaVersion or kind is wrong")
    if sources.get("repository") != "common-voice/common-voice":
        issues.append("sources: repository must be common-voice/common-voice")
    if sources.get("host") != DOWNLOAD_HOST:
        issues.append(f"sources: host must be {DOWNLOAD_HOST}")
    if not (isinstance(sources.get("commit"), str) and COMMIT.fullmatch(sources["commit"])):
        issues.append("sources: commit must be a full 40-character SHA-1")
    license_pin = sources.get("license")
    if not isinstance(license_pin, dict) or license_pin.get("path") != LICENSE_PATH \
            or license_pin.get("spdx") != "CC0-1.0" or not _pin_ok(license_pin):
        issues.append(f"sources: license must pin {LICENSE_PATH} as CC0-1.0 with its bytes and sha256")
    entries = sources.get("languages")
    if not isinstance(entries, list):
        return issues + ["sources: languages must be a list"]
    if [entry.get("language") if isinstance(entry, dict) else None for entry in entries] != list(languages):
        issues.append(f"sources: languages must be {', '.join(languages)} in that order")
    for entry in entries:
        if not isinstance(entry, dict):
            issues.append("sources: a language entry is not an object")
            continue
        language = entry.get("language")
        locale = COMMON_VOICE_LOCALES.get(language)
        match = SOURCE_PATH_PATTERN.fullmatch(str(entry.get("path")))
        if locale is None or entry.get("locale") != locale:
            issues.append(f"sources: {language} must read Common Voice locale {locale}")
        if match is None or match.group(1) != entry.get("locale"):
            issues.append(f"sources: {language} path must be server/data/<locale>/sentence-collector.txt")
        if not _pin_ok(entry):
            issues.append(f"sources: {language} must pin bytes and sha256")
    return issues


def _pin_ok(pin: Mapping[str, Any]) -> bool:
    size = pin.get("bytes")
    return (type(size) is int and 0 < size <= MAX_SOURCE_BYTES
            and isinstance(pin.get("sha256"), str) and SHA256.fullmatch(pin["sha256"]) is not None)


def cache_root() -> Path:
    override = os.environ.get(CACHE_ENV)
    return (Path(override) if override else REPO / "build" / "cache" / "audio-qc-corpora") / CACHE_SUBDIRECTORY


def source_directory(sources: Mapping[str, Any], root: Path | None = None) -> Path:
    return (root or cache_root()) / sources["commit"]


def pinned_files(sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [sources["license"], *sources["languages"]]


def raw_url(sources: Mapping[str, Any], path: str) -> str:
    return (f"https://{DOWNLOAD_HOST}/{sources['repository']}/{sources['commit']}/"
            f"{urllib.parse.quote(path)}")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_file(path: Path, pin: Mapping[str, Any]) -> bool:
    return (path.is_file() and not path.is_symlink() and path.stat().st_size == pin["bytes"]
            and _file_digest(path) == pin["sha256"])


# --- fetch --------------------------------------------------------------------------------------------


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """The pinned files are served directly; any redirect is refused, so nothing leaves the host."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        host = urllib.parse.urlsplit(newurl).hostname or "?"
        raise ScriptPoolError(f"a download was redirected (HTTP {code}) to {host}; nothing is fetched from it")


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def allowed_url(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and (parts.hostname or "").lower() == DOWNLOAD_HOST
            and not parts.username and not parts.password and port in (None, 443))


def _open(request: urllib.request.Request, timeout: float) -> Any:
    if not allowed_url(request.full_url):
        raise ScriptPoolError(f"{request.full_url} is not an https URL on {DOWNLOAD_HOST}")
    return _OPENER.open(request, timeout=timeout)


def fetch(sources: Mapping[str, Any], *, root: Path | None = None, opener: Opener = _open,
          languages: Sequence[str] = lm.PRODUCT_LANGUAGES) -> list[dict[str, Any]]:
    """Download every pinned file that is not already present and verified; refuse any mismatch."""
    if issues := sources_issues(sources, languages):
        raise ScriptPoolError("; ".join(issues))
    directory = source_directory(sources, root)
    report = []
    for pin in pinned_files(sources):
        final = directory / pin["path"]
        if final.exists():
            if not verified_file(final, pin):
                raise ScriptPoolError(f"{pin['path']} is present but differs from its pin; remove it and fetch again")
            report.append({"path": pin["path"], "status": "present"})
            continue
        url = raw_url(sources, pin["path"])
        if not allowed_url(url):
            raise ScriptPoolError(f"{pin['path']} does not resolve to an https URL on {DOWNLOAD_HOST}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        try:
            with opener(request, DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = int(getattr(response, "status", None) or response.getcode())
                if status != 200:
                    raise ScriptPoolError(f"HTTP {status} for {pin['path']}")
                blocks: list[bytes] = []
                received = 0
                while received <= pin["bytes"]:  # never more than one byte past the pin
                    block = response.read(min(1 << 20, pin["bytes"] + 1 - received))
                    if not block:
                        break
                    blocks.append(block)
                    received += len(block)
                data = b"".join(blocks)
        except urllib.error.HTTPError as error:
            raise ScriptPoolError(f"HTTP {error.code} for {pin['path']}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, TimeoutError) as error:
            raise ScriptPoolError(f"{pin['path']} could not be downloaded: {type(error).__name__}") from None
        if len(data) != pin["bytes"]:
            raise ScriptPoolError(f"{pin['path']} is {len(data)} bytes, pinned {pin['bytes']}; nothing was written")
        if hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ScriptPoolError(f"{pin['path']} does not match its pinned SHA-256; nothing was written")
        atomic_write_bytes(final, data)
        report.append({"path": pin["path"], "status": "fetched", "bytes": len(data)})
    return report


# --- build --------------------------------------------------------------------------------------------


def read_source_lines(path: Path, pin: Mapping[str, Any]) -> list[str]:
    if not verified_file(path, pin):
        raise ScriptPoolError(f"{pin['path']} is missing or differs from its pin; run `fetch` first")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ScriptPoolError(f"{pin['path']} is not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def build(sources: Mapping[str, Any], directory: Path, legacy_corpus: Mapping[str, Any], *,
          rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Select the pool from verified source files. `rules` overrides selection parameters (tests only)."""
    selection = selection_block(rules)
    languages = [entry["language"] for entry in sources["languages"]]
    if issues := sources_issues(sources, languages):
        raise ScriptPoolError("; ".join(issues))
    per_language, seed = selection["perLanguage"], selection["seed"]
    legacy = legacy_texts(legacy_corpus)
    candidates: dict[str, dict[str, tuple[int, str]]] = {}
    funnels: dict[str, dict[str, int]] = {}
    for entry in sources["languages"]:
        language = entry["language"]
        lines = read_source_lines(directory / entry["path"], entry)
        numbered = [(number, line) for number, line in enumerate(lines, start=1) if line.strip()]
        names = name_lexicon([line for _number, line in numbered], language)
        funnel = {"nonBlankLines": len(numbered)}
        survivors = []
        rejected: dict[str, int] = {name: 0 for name in FILTERS}
        for number, line in numbered:
            reason = text_rejection(line, language, names)
            if reason is None and overlaps_legacy(line, language, legacy):
                reason = "noLegacyOverlap"
            if reason is None:
                survivors.append((number, line))
            else:
                rejected[reason] += 1
        unique: dict[str, tuple[int, str]] = {}
        for number, line in survivors:
            unique.setdefault(normalized_text(line, language), (number, line))
        rejected["uniqueInLanguage"] = len(survivors) - len(unique)
        remaining = funnel["nonBlankLines"]
        for name in FILTERS[:-1]:
            remaining -= rejected[name]
            funnel[name] = remaining
        candidates[language] = unique
        funnels[language] = funnel
    seen: dict[str, int] = {}
    for unique in candidates.values():
        for key in unique:
            seen[key] = seen.get(key, 0) + 1
    entries: list[dict[str, Any]] = []
    summaries = []
    for entry in sources["languages"]:
        language = entry["language"]
        unique = {key: value for key, value in candidates[language].items() if seen[key] == 1}
        funnels[language]["uniqueAcrossLanguages"] = len(unique)
        if len(unique) < per_language:
            raise ScriptPoolError(f"{language} keeps {len(unique)} candidates, fewer than {per_language}")
        ordered = sorted(unique, key=lambda key: (order_hash(language, key, seed), unique[key][0]))[:per_language]
        by_split = sorted(ordered, key=lambda key: split_hash(language, key, seed))
        calibration = set(by_split[: per_language // 2])
        prefix = lm.LANGUAGE_LOCALE_CODES[language]
        for index, key in enumerate(ordered, start=1):
            number, text = unique[key]
            entries.append({
                "id": f"{prefix}-{index:04d}",
                "language": language,
                "text": text,
                "sourceLine": number,
                "textSHA256": lm.text_sha256(text),
                "split": SPLITS[0] if key in calibration else SPLITS[1],
                "unit": unit_for(language),
                "length": len(normalized_units(text, language)),
            })
        funnels[language]["selected"] = per_language
        summaries.append({
            "language": language,
            "commonVoiceLocale": entry["locale"],
            "sourcePath": entry["path"],
            "sourceSHA256": entry["sha256"],
            "unit": unit_for(language),
            "lengthWindow": selection["lengthWindows"]["windows"][language],
            "candidateFunnel": funnel_list(funnels[language]),
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": POOL_KIND,
        "version": POOL_VERSION,
        "description": POOL_DESCRIPTION,
        "license": {
            "spdx": "CC0-1.0",
            "name": "CC0 1.0 Universal",
            "path": sources["license"]["path"],
            "sha256": sources["license"]["sha256"],
            "attribution": ATTRIBUTION,
        },
        "source": {
            "repository": sources["repository"],
            "commit": sources["commit"],
            "sourcesFile": "config/audio-qc-script-pool-sources.json",
        },
        "selection": selection,
        "languages": summaries,
        "entries": entries,
        "poolDigest": pool_digest(entries),
    }


def encode_pool(pool: Mapping[str, Any]) -> bytes:
    """Indented JSON with sorted keys, except that `entries` comes last with one entry per line."""
    head = pretty_bytes({key: value for key, value in pool.items() if key != "entries"},
                        ascii=False, allow_nan=False).decode("utf-8")
    if not head.endswith("\n}\n"):
        raise ScriptPoolError("the pool header did not encode as an object")
    rows = ",\n".join(
        "    " + json.dumps(entry, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(", ", ": "))
        for entry in pool["entries"]
    )
    return (head[:-3] + ',\n  "entries": [\n' + rows + "\n  ]\n}\n").encode("utf-8")


# --- validate -----------------------------------------------------------------------------------------


def validate(pool: Any, sources: Any, legacy_corpus: Mapping[str, Any], *,
             rules: Mapping[str, Any] | None = None) -> list[str]:
    """Why the pool may not be used (empty when it may). Needs no network and no fetched file."""
    if not isinstance(pool, dict):
        return ["pool: not a JSON object"]
    issues: list[str] = []
    selection = selection_block(rules)
    languages = list(selection.get("languages") or lm.PRODUCT_LANGUAGES)
    issues += sources_issues(sources, languages)
    if issues:
        return issues
    per_language, seed = selection["perLanguage"], selection["seed"]
    if (pool.get("schemaVersion"), pool.get("kind"), pool.get("version")) != (SCHEMA_VERSION, POOL_KIND, POOL_VERSION):
        issues.append("pool: schemaVersion, kind or version is wrong")
    if pool.get("description") != POOL_DESCRIPTION:
        issues.append("pool: description differs from the script's")
    expected_license = {"spdx": "CC0-1.0", "name": "CC0 1.0 Universal", "path": sources["license"]["path"],
                        "sha256": sources["license"]["sha256"], "attribution": ATTRIBUTION}
    if pool.get("license") != expected_license:
        issues.append("pool: license block differs from the sources file")
    if pool.get("source") != {"repository": sources["repository"], "commit": sources["commit"],
                              "sourcesFile": "config/audio-qc-script-pool-sources.json"}:
        issues.append("pool: source block differs from the sources file")
    if pool.get("selection") != selection:
        issues.append("pool: selection block differs from the script's rules (rebuild under a new rules version)")
    entries = pool.get("entries")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        return issues + ["pool: entries must be a list of objects"]
    if pool.get("poolDigest") != pool_digest(entries):
        issues.append("pool: poolDigest does not match the entries")
    summaries = pool.get("languages")
    if not isinstance(summaries, list) or [s.get("language") if isinstance(s, dict) else None
                                           for s in summaries] != languages:
        return issues + [f"pool: languages must be {', '.join(languages)} in that order"]
    order = {language: index for index, language in enumerate(languages)}
    ranks = [order.get(entry.get("language"), -1) for entry in entries]
    if -1 in ranks or ranks != sorted(ranks):
        issues.append("pool: entries must be product-language entries grouped in the languages' order")
    legacy = legacy_texts(legacy_corpus)
    keys: dict[str, str] = {}
    fields = {"id", "language", "text", "sourceLine", "textSHA256", "split", "unit", "length"}
    for summary, pin in zip(summaries, sources["languages"]):
        language = summary["language"]
        expected_summary = {"language": language, "commonVoiceLocale": pin["locale"], "sourcePath": pin["path"],
                            "sourceSHA256": pin["sha256"], "unit": unit_for(language),
                            "lengthWindow": selection["lengthWindows"]["windows"].get(language)}
        if (set(summary) != {*expected_summary, "candidateFunnel"}
                or {key: summary.get(key) for key in expected_summary} != expected_summary):
            issues.append(f"{language}: summary differs from the sources file or the rules")
        issues += _funnel_issues(language, summary.get("candidateFunnel"), per_language)
        mine = [entry for entry in entries if entry.get("language") == language]
        if len(mine) != per_language:
            issues.append(f"{language}: {len(mine)} entries, expected {per_language}")
            continue
        prefix = lm.LANGUAGE_LOCALE_CODES[language]
        if [entry.get("id") for entry in mine] != [f"{prefix}-{index:04d}" for index in range(1, per_language + 1)]:
            issues.append(f"{language}: ids must run {prefix}-0001 to {prefix}-{per_language:04d} in order")
        normalized = []
        for entry in mine:
            label = f"{entry.get('id')}"
            if set(entry) != fields:
                issues.append(f"{label}: fields must be {', '.join(sorted(fields))}")
                continue
            text = entry["text"]
            if not isinstance(text, str) or type(entry["sourceLine"]) is not int or entry["sourceLine"] < 1:
                issues.append(f"{label}: text or sourceLine is malformed")
                continue
            if entry["textSHA256"] != lm.text_sha256(text):
                issues.append(f"{label}: textSHA256 does not match the text")
            if (reason := text_rejection(text, language)) is not None:
                issues.append(f"{label}: fails the {reason} rule")
            if overlaps_legacy(text, language, legacy):
                issues.append(f"{label}: overlaps a legacy corpus script")
            if entry["unit"] != unit_for(language) or entry["length"] != len(normalized_units(text, language)):
                issues.append(f"{label}: unit or length is wrong")
            key = normalized_text(text, language)
            if key in keys:
                issues.append(f"{label}: duplicates {keys[key]} after normalization")
            keys[key] = label
            normalized.append((entry, key))
        if len(normalized) != per_language:
            continue
        hashes = [order_hash(language, key, seed) for _entry, key in normalized]
        if hashes != sorted(hashes):
            issues.append(f"{language}: entries are not in seeded-hash order")
        by_split = sorted(normalized, key=lambda item: split_hash(language, item[1], seed))
        half = per_language // 2
        for rank, (entry, _key) in enumerate(by_split):
            expected = SPLITS[0] if rank < half else SPLITS[1]
            if entry["split"] != expected:
                issues.append(f"{entry['id']}: split must be {expected} by its seeded hash")
        counts = {split: sum(1 for entry, _key in normalized if entry["split"] == split) for split in SPLITS}
        if counts != {split: half for split in SPLITS}:
            issues.append(f"{language}: splits hold {counts}, expected {half} each")
    if len(entries) != per_language * len(languages):
        issues.append(f"pool: {len(entries)} entries, expected {per_language * len(languages)}")
    return issues


FUNNEL_STAGES = ("nonBlankLines", *FILTERS, "selected")


def funnel_list(funnel: Mapping[str, int]) -> list[dict[str, Any]]:
    """The funnel as ordered stages: the candidates remaining after each filter."""
    return [{"stage": stage, "remaining": funnel[stage]} for stage in FUNNEL_STAGES]


def _funnel_issues(language: str, funnel: Any, per_language: int) -> list[str]:
    shape = f"{language}: candidateFunnel must list the stages {', '.join(FUNNEL_STAGES)} with integer counts"
    if not isinstance(funnel, list) or not all(isinstance(stage, dict) and set(stage) == {"stage", "remaining"}
                                               and type(stage["remaining"]) is int for stage in funnel):
        return [shape]
    if [stage["stage"] for stage in funnel] != list(FUNNEL_STAGES):
        return [shape]
    counts = [stage["remaining"] for stage in funnel[:-1]]
    if any(later > earlier for earlier, later in zip(counts, counts[1:])) or counts[-1] < per_language:
        return [f"{language}: candidateFunnel must not grow and must keep at least {per_language}"]
    if funnel[-1]["remaining"] != per_language:
        return [f"{language}: candidateFunnel must end with {per_language} selected"]
    return []


# --- CLI ----------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("fetch", "download the pinned source files"), ("build", "write the pool"),
                       ("validate", "check the committed pool (no network)")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--sources", type=Path, default=SOURCES_PATH)
        if name in ("build", "validate"):
            command.add_argument("--pool", type=Path, default=POOL_PATH)
            command.add_argument("--legacy-corpus", type=Path, default=LEGACY_CORPUS_PATH)
        if name == "validate":
            command.add_argument("--rebuild", action="store_true",
                                 help="also rebuild from the fetched files and require identical bytes")
    args = parser.parse_args(argv)
    try:
        sources = load_json(args.sources)
        if args.command == "fetch":
            report = fetch(sources)
            print(json.dumps({"status": "PASS", "files": report}, sort_keys=True))
            return 0
        legacy = load_json(args.legacy_corpus)
        if args.command == "build":
            pool = build(sources, source_directory(sources), legacy)
            atomic_write_bytes(args.pool, encode_pool(pool))
            print(json.dumps({"status": "PASS", "poolDigest": pool["poolDigest"],
                              "funnel": {s["language"]: s["candidateFunnel"] for s in pool["languages"]}},
                             ensure_ascii=False))
            return 0
        pool = load_json(args.pool)
        issues = validate(pool, sources, legacy)
        if not issues and encode_pool(pool) != args.pool.read_bytes():
            issues.append("pool: the file is not in the canonical encoding; rewrite it with `build`")
        if not issues and args.rebuild:
            rebuilt = encode_pool(build(sources, source_directory(sources), legacy))
            if rebuilt != args.pool.read_bytes():
                issues.append("pool: a rebuild from the pinned files differs from the committed pool")
    except ScriptPoolError as error:
        issues = [str(error)]
    if issues:
        print("Audio QC script pool: FAIL", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "entries": len(pool["entries"]), "poolDigest": pool["poolDigest"],
                      "rebuilt": bool(args.rebuild)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
