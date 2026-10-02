"""espeak-ng G2P: the expected phones of a script (decision D5), and its cache.

The engine is libespeak-ng 1.52, called in-process through ctypes. The `espeakng-loader` wheel in
the onnx runtime ships the library with `espeak-ng-data` (GPL-3.0-or-later; the loader is MIT),
so nothing is installed system-wide. A system `espeak-ng` executable is the fallback, run as a
subprocess. IPA comes from `espeak_TextToPhonemes` clause by clause (`espeakPHONEMES_IPA`, no
separators or ties); `qc.phones.segment_ipa` splits it into phones.

Records are cached by text under `build/cache/qc/results/g2p/<g2p_key>.json`, so the repository's
python reads them through `qc.phones.g2p` without espeak-ng. The job (`--job`, the runner
protocol) fills the cache for its takes and its `texts` and writes each take's result, `outputs =
{phones, ipa, words, g2p}`, so `qc.py run` treats G2P like any runner. `qc.py run` also sends the
ASR transcripts as pseudo-takes, for the sound-level transcript comparison.

Japanese: espeak-ng reads kana only (a kanji comes out as the words "Chinese letter"), so a
Japanese text is first read into katakana pronunciation (UniDic `pron`, one space between words)
by MeCab with the UniDic-lite dictionary through fugashi (fugashi MIT, MeCab BSD-3-Clause, UniDic
BSD-3-Clause of its GPL/LGPL/BSD choice), pinned in the onnx runtime. The reader's versions key the
Japanese records. Without the reader, Japanese G2P is unavailable: the job writes no result for
those takes (an environment gap, retried by the next run), and every Japanese phone feature
abstains instead of comparing against "Chinese letter".

Optional phones: each word lists the indices of the phones natural speech may leave out
(`optional`), which the phone alignment then drops at no cost. In French these are a liaison
consonant (a word-final consonant, optionally after a schwa, that espeak-ng gives the word in the
sentence but not when the word is read alone: "les" is /lez/ before "arbres", /le/ alone) and a
final schwa after a consonant in a word spelled -e, -es or -ent with another vowel ("branches",
"ormes"). They are marked only when the script's words and the IPA words pair one to one; every
other language gets none.

Limits: espeak-ng gives Chinese polyphones one reading (the same on both sides of a comparison) and
uses its own Korean rules; ja, zh and ko phone comparisons stay report-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from qc.phones import (ESPEAK_VOICES, G2P_MODEL_ID, LANGUAGE_SWITCH, REPO_ROOT, VOWELS, G2PCacheMiss,
                       G2PUnavailable, normalize_phone, segment_ipa)
from qc.runners import speech_common as common

G2P_CACHE_DIR = REPO_ROOT / "build/cache/qc/results/g2p"
G2P_SCHEMA = "vocello.qc.g2p/1"
# Bump when the G2P output for the same text changes (engine options, cleaning): it keys the cache.
# 2: each word lists its optional phones (French liaison consonants and final schwas).
G2P_VERSION = 2
# The languages whose words get optional phones, and the French spellings of a droppable final schwa.
OPTIONAL_LANGUAGES = frozenset({"french"})
SCHWA_SPELLINGS = ("e", "es", "ent")
# The Japanese reader's pinned packages (config/qc/runtimes/onnx.txt); they key Japanese records.
JAPANESE_READER = "fugashi-1.5.2+unidic-lite-1.0.8"

AUDIO_OUTPUT_SYNCHRONOUS = 0x02
INITIALIZE_DONT_EXIT = 0x8000
CHARS_UTF8 = 1
PHONEMES_IPA = 0x02


class EspeakLibrary:
    """libespeak-ng in-process through ctypes, from the `espeakng-loader` wheel."""

    name = "espeak-ng-library"

    def __init__(self, library_path: str | None = None, data_path: str | None = None) -> None:
        import ctypes

        if library_path is None or data_path is None:
            try:
                import espeakng_loader
            except ImportError as error:
                raise G2PUnavailable("espeakng-loader is not installed") from error
            library_path = library_path or espeakng_loader.get_library_path()
            data_path = data_path or espeakng_loader.get_data_path()
        try:
            library = ctypes.CDLL(str(library_path))
        except OSError as error:
            raise G2PUnavailable("libespeak-ng did not load") from error
        library.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        library.espeak_Initialize.restype = ctypes.c_int
        library.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        library.espeak_SetVoiceByName.restype = ctypes.c_int
        library.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_int, ctypes.c_int]
        library.espeak_TextToPhonemes.restype = ctypes.c_char_p
        library.espeak_Info.argtypes = [ctypes.c_void_p]
        library.espeak_Info.restype = ctypes.c_char_p
        # The path may be espeak-ng-data itself or its parent; DONT_EXIT keeps a bad path an error.
        if library.espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, str(data_path).encode(), INITIALIZE_DONT_EXIT) <= 0:
            raise G2PUnavailable("espeak-ng did not initialize")
        self._ctypes, self._library = ctypes, library
        info = library.espeak_Info(None)
        self.version = info.decode("utf-8", "replace") if info else None

    def phonemize(self, text: str, voice: str) -> str:
        if self._library.espeak_SetVoiceByName(voice.encode()) != 0:
            raise G2PUnavailable(f"espeak-ng has no voice {voice}")
        pointer = self._ctypes.pointer(self._ctypes.c_char_p(text.encode("utf-8")))
        clauses = []
        for _ in range(len(text) + 2):  # one clause per call; the pointer turns NULL at the end
            if not pointer.contents.value:
                break
            output = self._library.espeak_TextToPhonemes(pointer, CHARS_UTF8, PHONEMES_IPA)
            if output:
                clauses.append(output.decode("utf-8", "replace"))
        return " ".join(" ".join(clauses).split())


class EspeakBinary:
    """A system `espeak-ng` executable as a subprocess (the fallback outside the onnx runtime)."""

    name = "espeak-ng-binary"
    version = None

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("espeak-ng")
        if not self.executable:
            raise G2PUnavailable("no espeak-ng executable on PATH")

    def phonemize(self, text: str, voice: str) -> str:
        completed = subprocess.run([self.executable, "-q", "--ipa", "-v", voice, "--stdin"], input=text,
                                   capture_output=True, text=True, check=True, timeout=120)
        return " ".join(completed.stdout.split())


class JapaneseReader:
    """Japanese text as katakana pronunciation for espeak-ng: MeCab with UniDic-lite, via fugashi.

    Each word becomes its UniDic `pron` (the particle は as ワ, long vowels as ー); a word without
    one (Latin letters, digits) keeps its surface. Words are joined by spaces, so espeak-ng keeps
    the word boundaries and reads ー as length. Text is NFKC-normalized first (full-width digits).
    """

    def __init__(self) -> None:
        try:
            from importlib import metadata

            import fugashi
            import unidic_lite
        except ImportError as error:
            raise G2PUnavailable("Japanese G2P needs fugashi and unidic-lite "
                                 "(qc.py runtimes setup --runtime onnx)") from error
        self.name = f"fugashi-{metadata.version('fugashi')}+unidic-lite-{metadata.version('unidic-lite')}"
        if self.name != JAPANESE_READER:
            raise G2PUnavailable(f"the Japanese reader is {self.name}, pinned {JAPANESE_READER}")
        dictionary = unidic_lite.DICDIR
        self._tagger = fugashi.Tagger(f'-r "{os.path.join(dictionary, "mecabrc")}" -d "{dictionary}"')

    def read(self, text: str) -> str:
        words = []
        for word in self._tagger(unicodedata.normalize("NFKC", text)):
            pron = getattr(word.feature, "pron", None)
            reading = (pron if pron and pron != "*" else word.surface).strip()
            if reading:
                words.append(reading)
        return " ".join(words)


def default_reader() -> JapaneseReader:
    return JapaneseReader()


def default_engine() -> EspeakLibrary | EspeakBinary:
    try:
        return EspeakLibrary()
    except G2PUnavailable:
        pass
    try:
        return EspeakBinary()
    except G2PUnavailable as error:
        raise G2PUnavailable("no espeak-ng: run the G2P job (qc.runners.espeak_g2p) in the onnx runtime") from error


def g2p_key(text: str, language: str) -> str:
    """The cache file stem: SHA-256 of the G2P model, version, language and text (and, for
    Japanese, the reader)."""

    fields = {"language": language, "model": G2P_MODEL_ID, "text": text, "version": G2P_VERSION}
    if language == "japanese":
        fields["reader"] = JAPANESE_READER
    payload = common.canonical_json(fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reading(text: str, language: str, reader: Any) -> tuple[str | None, Any]:
    """What espeak-ng reads instead of the text: the reader's kana for Japanese (raises
    G2PUnavailable without a reader), None for every other language."""

    if language != "japanese":
        return None, None
    reader = reader or default_reader()
    return reader.read(text), reader


def _ipa(engine: Any, text: str, language: str) -> str:
    if language not in ESPEAK_VOICES:
        raise ValueError(f"unsupported language: {language!r}")
    return " ".join(LANGUAGE_SWITCH.sub(" ", engine.phonemize(text, ESPEAK_VOICES[language])).split())


def text_words(text: str) -> list[str]:
    """The script's words as espeak-ng reads them: whitespace-separated tokens holding a letter or
    digit, without their leading and trailing punctuation ("arbres," is "arbres")."""

    words = []
    for token in unicodedata.normalize("NFC", text or "").split():
        start, end = 0, len(token)
        while start < end and unicodedata.category(token[start])[0] in "PS":
            start += 1
        while end > start and unicodedata.category(token[end - 1])[0] in "PS":
            end -= 1
        core = token[start:end]
        if any(char.isalnum() for char in core):
            words.append(core)
    return words


def _base(phone: str) -> str:
    return "".join(normalize_phone(phone, keep_rhotics=True))


def _vowel(phone: str) -> bool:
    return phone[:1] in VOWELS


def optional_indices(spelling: str, phones: list[str], alone: list[str] | None) -> list[int]:
    """The phones of one French word (in its sentence) that natural speech may leave out.

    - A liaison: the word read alone (`alone`) is the sentence's word minus a final consonant,
      or minus a schwa and a final consonant ("ormes" /ɔʁm/ alone, /ɔʁməz/ before a vowel);
    - a final schwa after a consonant, in a word spelled -e, -es or -ent that has another vowel
      ("branches" /bʁɑ̃ʃə/; never the only vowel of "le" or "de").
    """

    optional: set[int] = set()
    core = len(phones)
    if alone and len(alone) < len(phones) and [_base(p) for p in phones[:len(alone)]] == [_base(p) for p in alone]:
        extra = phones[len(alone):]
        liaison = (len(extra) == 1 and not _vowel(extra[0])) or (
            len(extra) == 2 and _base(extra[0]) == "ə" and not _vowel(extra[1]))
        if liaison:
            optional.update(range(len(alone), len(phones)))
            core = len(alone)
    lowered = spelling.lower()
    if (core >= 2 and _base(phones[core - 1]) == "ə" and not _vowel(phones[core - 2])
            and lowered.endswith(SCHWA_SPELLINGS) and any(_vowel(phone) for phone in phones[:core - 1])):
        optional.add(core - 1)
    return sorted(optional)


def mark_optional(words: list[dict[str, Any]], text: str, language: str, engine: Any) -> None:
    """Give every word its `optional` phone indices (`optional_indices`, French only); none when the
    script's words and the IPA words do not pair one to one."""

    for word in words:
        word["optional"] = []
    if language not in OPTIONAL_LANGUAGES:
        return
    spellings = text_words(text)
    if len(spellings) != len(words):
        return
    alone: dict[str, list[str]] = {}
    for spelling, word in zip(spellings, words):
        if spelling not in alone:
            alone[spelling] = segment_ipa(_ipa(engine, spelling, language))
        word["optional"] = optional_indices(spelling, word["phones"], alone[spelling])


def g2p_record(text: str, language: str, *, cache_dir: Path | str | None = None, engine: Any = None,
               compute: bool = True, reader: Any = None) -> dict[str, Any]:
    """The cached G2P record for (text, language), computing and caching it when allowed."""

    if language not in ESPEAK_VOICES:
        raise ValueError(f"unsupported language: {language!r}")
    path = Path(cache_dir or G2P_CACHE_DIR) / f"{g2p_key(text, language)}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("text") == text and record.get("language") == language:
            return record
    except (OSError, ValueError):
        pass
    if not compute:
        raise G2PCacheMiss(language)
    reading, reader = _reading(text, language, reader)
    engine = engine or default_engine()
    ipa = _ipa(engine, text if reading is None else reading, language)
    words = [{"ipa": word, "phones": segment_ipa(word)} for word in ipa.split(" ") if word]
    words = [word for word in words if word["phones"]]
    mark_optional(words, text if reading is None else reading, language, engine)
    record = {"schema": G2P_SCHEMA, "model": G2P_MODEL_ID, "g2pVersion": G2P_VERSION, "engine": engine.name,
              "engineVersion": getattr(engine, "version", None), "voice": ESPEAK_VOICES[language],
              "language": language, "text": text, "ipa": ipa, "words": words,
              "phones": [phone for word in words for phone in word["phones"]]}
    if reading is not None:
        record.update(reader=reader.name, reading=reading)
    common.write_json_atomic(path, record)
    return record


def g2p(text: str, language: str, *, cache_dir: Path | str | None = None, compute: bool = True,
        engine: Any = None, reader: Any = None) -> list[str]:
    return list(g2p_record(text, language, cache_dir=cache_dir, compute=compute, engine=engine,
                           reader=reader)["phones"])


def g2p_espeak(text: str, language: str, *, engine: Any = None, reader: Any = None) -> list[str]:
    if language not in ESPEAK_VOICES:
        raise ValueError(f"unsupported language: {language!r}")
    reading, _ = _reading(text, language, reader)
    return segment_ipa(_ipa(engine or default_engine(), text if reading is None else reading, language))


def run_g2p_job(job: Mapping[str, Any], *, engine: Any = None, reader: Any = None) -> int:
    """Fill the G2P cache for a job's takes (and optional `texts`), then write each take's result.

    `outputDir` is the G2P cache. A take without text gets the `text-missing` error. A Japanese
    take without the reader gets no result at all, so the next run retries it. Exit 0 when every
    text and take succeeded, 1 otherwise, 2 when no engine is available.
    """

    output_dir = Path(job["outputDir"])
    takes = list(job.get("takes") or [])
    texts = [(item.get("language"), item.get("text")) for item in job.get("texts") or []]
    texts += [(take.get("language"), take.get("text")) for take in takes]
    pending = list(dict.fromkeys((language, text) for language, text in texts if text))
    if engine is None:
        try:
            engine = default_engine()
        except G2PUnavailable as error:
            print(f"qc g2p: {error}", file=sys.stderr)
            return 2
    unreadable: str | None = None
    if reader is None and any(language == "japanese" for language, _ in pending):
        try:
            reader = default_reader()
        except G2PUnavailable as error:
            unreadable = str(error)
            print(f"qc g2p: Japanese abstains: {error}", file=sys.stderr)
    failures = 0
    unavailable: set[tuple[str, str]] = set()
    for count, (language, text) in enumerate(pending, start=1):
        try:
            if language == "japanese" and unreadable:
                raise G2PUnavailable(unreadable)
            g2p_record(text, language, cache_dir=output_dir, engine=engine, reader=reader)
        except G2PUnavailable as error:
            failures += 1
            unavailable.add((language, text))
            if not (language == "japanese" and unreadable):
                print(f"qc g2p: text {count} unavailable ({error})", file=sys.stderr)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            failures += 1
            print(f"qc g2p: text {count} failed ({type(error).__name__})", file=sys.stderr)
        print(f"progress {count}/{len(pending)}", flush=True)
    for take in takes:
        if (take.get("language"), take.get("text")) in unavailable:
            continue  # an environment gap, not the take's result: nothing is cached
        variant = common.take_variant(take, depends=False)
        try:
            if not take.get("text"):
                raise common.TakeError("text-missing")
            entry = g2p_record(take["text"], take.get("language"), cache_dir=output_dir, compute=False)
            outputs = {"phones": entry["phones"], "ipa": entry["ipa"], "words": entry["words"],
                       "g2p": f"{g2p_key(take['text'], take['language'])}.json"}
            record = common.result_record(job, take, variant=variant, duration=None, outputs=outputs)
        except common.TakeError as error:
            failures += 1
            record = common.result_record(job, take, variant=variant, duration=None, error=error.code)
        except (G2PCacheMiss, ValueError):
            failures += 1
            record = common.result_record(job, take, variant=variant, duration=None, error="g2p-failed")
        common.write_json_atomic(output_dir / f"{common.result_stem(take['audioSHA256'], variant)}.json", record)
    return 0 if failures == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QC v2 G2P job: espeak-ng phones for a job's texts")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job", dest="job", help="runner-protocol job file")
    group.add_argument("--g2p-job", dest="job", help="alias of --job")
    args = parser.parse_args(argv)
    try:
        job = json.loads(Path(args.job).read_text(encoding="utf-8"))
        if "outputDir" not in job:
            raise ValueError("job is missing outputDir")
    except (OSError, ValueError) as error:
        print(f"qc g2p: unreadable job ({type(error).__name__})", file=sys.stderr)
        return 2
    common.offline()
    return run_g2p_job(job)


if __name__ == "__main__":
    sys.exit(main())
