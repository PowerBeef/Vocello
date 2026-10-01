"""espeak-ng G2P: the expected phones of a script (decision D5), and its cache.

The engine is libespeak-ng 1.52, called in-process through ctypes. The `espeakng-loader` wheel in
the onnx runtime ships the library with `espeak-ng-data` (GPL-3.0-or-later; the loader is MIT),
so nothing is installed system-wide. A system `espeak-ng` executable is the fallback, run as a
subprocess. IPA comes from `espeak_TextToPhonemes` clause by clause (`espeakPHONEMES_IPA`, no
separators or ties); `qc.phones.segment_ipa` splits it into phones.

Records are cached by text under `build/cache/qc/results/g2p/<g2p_key>.json`, so the repository's
python reads them through `qc.phones.g2p` without espeak-ng. The job (`--job`, the runner
protocol) fills the cache for its takes and writes each take's result, `outputs = {phones, ipa,
words, g2p}`, so `qc.py run` treats G2P like any runner.

Limits: espeak-ng reads Japanese kana only (kanji get no reading), gives Chinese polyphones one
reading and uses its own Korean rules; ja, zh and ko phone comparisons stay report-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from qc.phones import ESPEAK_VOICES, G2P_MODEL_ID, LANGUAGE_SWITCH, REPO_ROOT, G2PCacheMiss, G2PUnavailable, segment_ipa
from qc.runners import speech_common as common

G2P_CACHE_DIR = REPO_ROOT / "build/cache/qc/results/g2p"
G2P_SCHEMA = "vocello.qc.g2p/1"
# Bump when the G2P output for the same text changes (engine options, cleaning): it keys the cache.
G2P_VERSION = 1

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
    """The cache file stem: SHA-256 of the G2P model, version, language and text."""

    payload = common.canonical_json({"language": language, "model": G2P_MODEL_ID, "text": text,
                                     "version": G2P_VERSION})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ipa(engine: Any, text: str, language: str) -> str:
    if language not in ESPEAK_VOICES:
        raise ValueError(f"unsupported language: {language!r}")
    return " ".join(LANGUAGE_SWITCH.sub(" ", engine.phonemize(text, ESPEAK_VOICES[language])).split())


def g2p_record(text: str, language: str, *, cache_dir: Path | str | None = None, engine: Any = None,
               compute: bool = True) -> dict[str, Any]:
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
    engine = engine or default_engine()
    ipa = _ipa(engine, text, language)
    words = [{"ipa": word, "phones": segment_ipa(word)} for word in ipa.split(" ") if word]
    words = [word for word in words if word["phones"]]
    record = {"schema": G2P_SCHEMA, "model": G2P_MODEL_ID, "g2pVersion": G2P_VERSION, "engine": engine.name,
              "engineVersion": getattr(engine, "version", None), "voice": ESPEAK_VOICES[language],
              "language": language, "text": text, "ipa": ipa, "words": words,
              "phones": [phone for word in words for phone in word["phones"]]}
    common.write_json_atomic(path, record)
    return record


def g2p(text: str, language: str, *, cache_dir: Path | str | None = None, compute: bool = True,
        engine: Any = None) -> list[str]:
    return list(g2p_record(text, language, cache_dir=cache_dir, compute=compute, engine=engine)["phones"])


def g2p_espeak(text: str, language: str, *, engine: Any = None) -> list[str]:
    return segment_ipa(_ipa(engine or default_engine(), text, language))


def run_g2p_job(job: Mapping[str, Any], *, engine: Any = None) -> int:
    """Fill the G2P cache for a job's takes (and optional `texts`), then write each take's result.

    `outputDir` is the G2P cache. A take without text gets the `text-missing` error; exit 0 when
    every text and take succeeded, 1 otherwise, 2 when no engine is available.
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
    failures = 0
    for count, (language, text) in enumerate(pending, start=1):
        try:
            g2p_record(text, language, cache_dir=output_dir, engine=engine)
        except (G2PUnavailable, ValueError, OSError, subprocess.SubprocessError) as error:
            failures += 1
            print(f"qc g2p: text {count} failed ({type(error).__name__})", file=sys.stderr)
        print(f"progress {count}/{len(pending)}", flush=True)
    for take in takes:
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
