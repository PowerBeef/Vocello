#!/usr/bin/env python3
"""Paired machine screens for the quality remediation (RF-50).

Nobody listens to Vocello's output, so a change that alters samples is decided
by a screen: the same takes generated under two arms that differ in one thing,
scored by the same models, and compared take by take under a rule recorded
before the takes exist. The calibration lane (`macos_test.sh qc-takes`) is not
that screen: it passes when scoring fails, no lane of it measures both who is
speaking and what was said, it drops refused takes from its averages, and two
arms share one data directory (the audit of 2026-11-11). This tool is built
around those defects:

- every arm runs in its own data directory, so no prompt or cache made by one
  arm can serve another;
- every planned take has an outcome, and a take that was refused or failed
  counts against its arm instead of leaving the average;
- identity is the PCM digest (a WAV's bytes carry its creation time);
- scoring is the QC v2 runners for the two ASR families and the speaker model,
  and a take without all three results fails the scoring step;
- the edit rate is a true one (substitutions, deletions and insertions over the
  reference length), per family;
- an arm records what it was: its environment overrides, the executable's
  digest and the commit.

    plan     write the take plan of a screen (deterministic; `--seed-set` gives
             the same takes other seeds, for the noise floor)
    run      generate one arm of a plan
    score    score an arm
    compare  compare two arms: `--expect identical` for a determinism check,
             `--expect noise` to report the floor, `--rule NAME` to decide

Run it with the repository's Python after `scripts/build.sh cli-optimized`.
Arms, audio and transcripts stay under `build/artifacts`; nothing here is
benchmark-history evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import unicodedata
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telemetry_overhead import DEBUG_ROOT, ROOT, managed_output_path, pcm_digest  # noqa: E402

SCHEMA_VERSION = 1
CONFIG = ROOT / "config/quality-screens.json"
SCRIPT_POOL = ROOT / "config/audio-qc-script-pool.json"
CORPORA = ROOT / "build/cache/audio-qc-corpora"
QC_RESULTS = ROOT / "build/cache/qc/results"
ASR_MODELS = ("asr.qwen3-asr-1.7b", "asr.whisper-large-v3")
SPEAKER_MODEL = "speaker.redimnet2-plus"
# Compared by character: no spaces between words, or spacing that varies.
CHARACTER_LANGUAGES = {"chinese", "japanese", "korean"}
# Written without spaces: their sentences join with no separator.
UNSPACED_LANGUAGES = {"chinese", "japanese"}
# The late part of a take starts here: the speech tokenizer decoder attends
# over 72 frames at 12.5 Hz (5.76 s), so a speaker window that starts at 6 s
# lies wholly past what a frame near the start can see (RF-54).
LATE_FROM_SECONDS = 6.0
PASS_THROUGH_PREFIXES = ("MLX_", "QWENVOICE_", "QVOICE_")
BOOTSTRAP_RESAMPLES = 2_000


class ScreenError(Exception):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_screen(name: str, config: dict | None = None) -> dict:
    loaded: dict = config if config is not None else read_json(CONFIG)
    screen = (loaded.get("screens") or {}).get(name)
    if not screen:
        raise ScreenError(f"no screen named '{name}' in {CONFIG.name}")
    return dict(screen, name=name)


# ---------------------------------------------------------------- plan


def rank(key: str) -> str:
    return sha256_text(key)


def take_seed(screen: dict, seed_set: int, take_id: str) -> int:
    key = f"quality-screen|{screen['name']}|v{screen['version']}|seed-set {seed_set}|{take_id}"
    return int(sha256_text(key)[:16], 16) & ((1 << 63) - 1)


def corpus_clips(source: str) -> tuple[Path, list[dict]]:
    manifests = sorted((CORPORA / source).glob("*/extracted/manifest.json"))
    if len(manifests) != 1:
        raise ScreenError(f"the '{source}' corpus is not extracted once under build/cache/audio-qc-corpora")
    return manifests[0].parent, read_json(manifests[0])["clips"]


TRANSCRIPT_FORMS = ("as-given", "unpunctuated")
# Marks a recognizer writes as part of a token even with punctuation off.
KEPT_SIGNS = frozenset("%\u2030&@#/*\\")


def _han_or_kana(character: str) -> bool:
    if not character:
        return False
    code = ord(character)
    return (0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F
            or 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
            or 0x20000 <= code <= 0x323AF or 0x3005 <= code <= 0x3007)


def unpunctuated(text: str) -> str:
    """A transcript's words as Apple's on-device recognizer gives them with
    punctuation off (G-15): every punctuation mark removed except an apostrophe
    or hyphen inside a word, a mark between two digits (3.5, 1,000) and the
    signs a number or address carries (% & @ # /); letters, digits, symbols and
    case kept. A mark between two Han or kana characters leaves nothing, any
    other a space, and whitespace is collapsed."""
    out: list[str] = []
    for index, character in enumerate(text):
        if not unicodedata.category(character).startswith("P") or character in KEPT_SIGNS:
            out.append(character)
            continue
        before = text[index - 1] if index > 0 else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if character in "'\u2019-\u2010" and before.isalnum() and after.isalnum():
            out.append(character)
        elif before.isdigit() and after.isdigit():
            out.append(character)
        elif not (_han_or_kana(before) and _han_or_kana(after)):
            out.append(" ")
    return " ".join("".join(out).split())


def enrolled_transcript(transcript: str, form: str) -> str:
    """The transcript a voice is enrolled with under an arm's transcript form."""
    if form not in TRANSCRIPT_FORMS:
        raise ScreenError(f"transcript form '{form}' is not one of {', '.join(TRANSCRIPT_FORMS)}")
    return unpunctuated(transcript) if form == "unpunctuated" else transcript


def population(screen: dict) -> str:
    """The name references and scripts are drawn under: a screen that varies
    another screen's references (`population`) draws the same ones."""
    return screen.get("population") or screen["name"]


# ---------------------------------------------------------------- channel layouts

CHANNEL_LAYOUTS = ("duplicate", "left-only")
STEREO_REFERENCES = "quality-screen-references"


def stereo_frames(mono: bytes, layout: str) -> bytes:
    """Two-channel 16-bit frames from one channel: the same signal on both
    (a mono recording saved as stereo, the common case), or the signal on the
    left with silence on the right (a microphone on one input). Sample
    values are copied, never recomputed."""
    if layout not in CHANNEL_LAYOUTS:
        raise ScreenError(f"unknown channel layout '{layout}'")
    if len(mono) % 2:
        raise ScreenError("a 16-bit clip has an odd byte count")
    silence = b"\x00\x00"
    out = bytearray()
    for index in range(0, len(mono), 2):
        sample = mono[index:index + 2]
        out += sample + (sample if layout == "duplicate" else silence)
    return bytes(out)


def layout_for(screen: dict, index: int) -> str | None:
    """The channel layout of a screen's index-th reference of a language
    (1-based): alternating, so each language has both."""
    if screen.get("referenceChannels") != "alternate-duplicate-left-only":
        return None
    return CHANNEL_LAYOUTS[(index - 1) % 2]


def two_channel_reference(source: Path, layout: str) -> tuple[Path, str]:
    """The reference as a two-channel WAV, stored by its content digest under
    the managed artifacts, so every plan that asks for it shares one file."""
    with wave.open(str(source), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ScreenError(f"{source.name}: a two-channel layout needs a mono 16-bit source")
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    stereo = stereo_frames(frames, layout)
    directory = managed_output_path("QVOICE_ARTIFACTS_MACOS") / STEREO_REFERENCES
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".partial-{os.getpid()}.wav"
    try:
        with wave.open(str(temporary), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(stereo)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    digest = sha256_file(temporary)
    target = directory / f"{digest}.wav"
    os.replace(temporary, target)
    return target, digest


def select_references(screen: dict, language: str, clips_by_source: dict[str, tuple[Path, list[dict]]]) -> list[dict]:
    """One clip per speaker, speakers and clips in hash order; clips at or
    above the preferred length first, so short ones fill in only where a
    corpus has nothing longer."""
    minimum, preferred, maximum = screen["referenceSeconds"]
    candidates = []
    for source in screen["languages"][language]:
        root, clips = clips_by_source[source]
        for clip in clips:
            if clip.get("language") != language or not (clip.get("text") or "").strip() or not clip.get("speaker"):
                continue
            if clip.get("clippedSamples") or not minimum <= clip["durationSeconds"] <= maximum:
                continue
            candidates.append(dict(clip, source=source, path=str(root / clip["wavPath"])))
    by_speaker: dict[str, list[dict]] = {}
    for clip in candidates:
        by_speaker.setdefault(f"{clip['source']}/{clip['speaker']}", []).append(clip)
    chosen = []
    for speaker, clips in by_speaker.items():
        clips.sort(key=lambda clip: (clip["durationSeconds"] < preferred, rank(f"{population(screen)}|clip|{clip['clipID']}")))
        chosen.append((clips[0]["durationSeconds"] < preferred, rank(f"{population(screen)}|speaker|{speaker}"), clips[0]))
    chosen.sort(key=lambda item: item[:2])
    references = [item[2] for item in chosen[: screen["referencesPerLanguage"]]]
    if len(references) < screen["referencesPerLanguage"]:
        raise ScreenError(f"{language}: only {len(references)} eligible reference speakers")
    return references


def select_scripts(screen: dict, pool: list[dict], language: str, reference_key: str, count: int) -> list[dict]:
    """`count` scripts in hash order. A screen with `sentencesPerTake` N joins
    N pool sentences into each script, in that order, so its takes run long
    enough for what only acts late in a take; one sentence is the default."""
    per_take = screen.get("sentencesPerTake", 1)
    entries = [entry for entry in pool if entry["language"] == language and entry["split"] == screen["scriptSplit"]]
    entries.sort(key=lambda entry: rank(f"{population(screen)}|script|{reference_key}|{entry['id']}"))
    if len(entries) < count * per_take:
        raise ScreenError(f"{language}: the script pool holds fewer than {count * per_take} scripts")
    if per_take == 1:
        return entries[:count]
    return [joined_script(entries[index * per_take:(index + 1) * per_take], language) for index in range(count)]


def joined_script(entries: list[dict], language: str) -> dict:
    separator = "" if language in UNSPACED_LANGUAGES else " "
    return {"id": "+".join(entry["id"] for entry in entries), "language": language,
            "text": separator.join(entry["text"] for entry in entries)}


def build_plan(screen: dict, seed_set: int, languages: list[str] | None = None,
               variations: list[str] | None = None) -> dict:
    if screen.get("kind") == "long-form":
        return build_long_form_plan(screen, seed_set, languages, variations)
    if variations:
        raise ScreenError("--variations applies to a long-form screen")
    if screen.get("kind") == "custom":
        return build_custom_plan(screen, seed_set, languages)
    if screen.get("kind") != "clone":
        raise ScreenError(f"screen kind '{screen.get('kind')}' is not implemented")
    pool = read_json(SCRIPT_POOL)["entries"]
    selected = languages or list(screen["languages"])
    unknown = [language for language in selected if language not in screen["languages"]]
    if unknown:
        raise ScreenError(f"not in the screen: {', '.join(unknown)}")
    sources = {source for language in selected for source in screen["languages"][language]}
    clips_by_source = {source: corpus_clips(source) for source in sorted(sources)}
    voices, takes = [], []
    for language in selected:
        for index, clip in enumerate(select_references(screen, language, clips_by_source), start=1):
            voice = f"screen-{language}-{index:02d}"
            transcript = " ".join(unicodedata.normalize("NFC", clip["text"]).split())
            entry = {"voice": voice, "language": language, "clipID": clip["clipID"], "source": clip["source"],
                     "audio": clip["path"], "audioSHA256": clip["wavSHA256"],
                     "seconds": clip["durationSeconds"], "sampleRate": clip["sampleRate"], "transcript": transcript}
            layout = layout_for(screen, index)
            if layout:
                path, digest = two_channel_reference(Path(clip["path"]), layout)
                entry.update(audio=str(path), audioSHA256=digest, channelLayout=layout,
                             monoAudio=clip["path"], monoAudioSHA256=clip["wavSHA256"])
            voices.append(entry)
            other = screen["crossLanguage"].get(language, screen["crossLanguage"]["default"])
            scripts = [(language, script) for script in
                       select_scripts(screen, pool, language, clip["clipID"], screen["scriptsPerReference"])]
            scripts += [(other, script) for script in
                        select_scripts(screen, pool, other, clip["clipID"], screen["crossLanguageScripts"])]
            for script_language, script in scripts:
                take_id = f"{voice}--{script['id']}"
                takes.append({"takeID": take_id, "voice": voice, "referenceLanguage": language,
                              "language": script_language, "crossLanguage": script_language != language,
                              "scriptID": script["id"], "text": script["text"], "seed": take_seed(screen, seed_set, take_id)})
    plan = {"schemaVersion": SCHEMA_VERSION, "screen": screen["name"], "screenVersion": screen["version"],
            "mode": screen["mode"], "variant": screen["variant"], "seedSet": seed_set, "voices": voices, "takes": takes}
    plan["planSHA256"] = sha256_text(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    return plan


def build_long_form_plan(screen: dict, seed_set: int, strata: list[str] | None = None,
                         variations: list[str] | None = None) -> dict:
    """Long-form projects (RF-50): per stratum, `projectsPerStratum` scripts of
    `sentencesPerProject` pool sentences, each run once per variation with the
    same script (Expressive only since RF-58). A project, not a take, is the
    unit the interval resamples (its `voice`)."""
    pool = read_json(SCRIPT_POOL)["entries"]
    selected = strata or list(screen["strata"])
    unknown = [name for name in selected if name not in screen["strata"]]
    if unknown:
        raise ScreenError(f"not in the screen: {', '.join(unknown)}")
    per, count = screen["sentencesPerProject"], screen["projectsPerStratum"]
    if screen.get("longForm", "always") not in LONG_FORM_ROUTES:
        raise ScreenError(f"longForm must be one of {', '.join(LONG_FORM_ROUTES)}")
    retired = [name for name in screen["variations"] if name != "expressive"]
    if retired:
        # The CLI samples every take as Expressive since RF-58, so such a take
        # would carry a label it was not generated under.
        raise ScreenError(f"retired variation (RF-58): {', '.join(retired)}")
    unknown_variations = [name for name in variations or [] if name not in screen["variations"]]
    if unknown_variations:
        raise ScreenError(f"not a variation of the screen: {', '.join(unknown_variations)}")
    takes = []
    for name in selected:
        stratum = screen["strata"][name]
        language, mode = stratum["language"], stratum["mode"]
        voices = stratum["speakers"] if mode == "custom" else stratum["voiceBriefs"]
        # "all" draws from both halves of the pool: a project needs more
        # sentences than one half holds.
        entries = [entry for entry in pool if entry["language"] == language
                   and screen["scriptSplit"] in ("all", entry["split"])]
        entries.sort(key=lambda entry: rank(f"{screen['name']}|{name}|script|{entry['id']}"))
        if len(entries) < per * count:
            raise ScreenError(f"{name}: the script pool holds fewer than {per * count} {language} scripts")
        for index in range(count):
            script = joined_script(entries[index * per:(index + 1) * per], language)
            project = f"{name}-{index + 1:02d}"
            voice = voices[index % len(voices)]
            for variation in screen["variations"]:
                if variations and variation not in variations:
                    continue
                take_id = f"{project}--{variation}"
                take = {"takeID": take_id, "voice": project, "stratum": name, "mode": mode, "language": language,
                        "variation": variation, "scriptID": script["id"], "text": script["text"],
                        "seed": take_seed(screen, seed_set, take_id)}
                take["speaker" if mode == "custom" else "voiceBrief"] = voice
                takes.append(take)
    plan = {"schemaVersion": SCHEMA_VERSION, "screen": screen["name"], "screenVersion": screen["version"],
            "kind": "long-form", "variant": screen["variant"], "seedSet": seed_set, "voices": [], "takes": takes}
    if "longForm" in screen:
        # Written only when a screen sets it, so earlier plans keep their digests.
        plan["longForm"] = screen["longForm"]
    plan["planSHA256"] = sha256_text(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    return plan


# How a long-form screen's takes are routed: `always` plans each script into
# segments as the apps route long text; `never` asks for one take of the whole
# script, a single Built-in Voice or Voice Design take (the `single` screen).
LONG_FORM_ROUTES = ("always", "never")


def short_sentence_candidates(lines: list[str], language: str, maximum_words: int) -> list[tuple[str, str]]:
    """Sentences that pass every rule of the script pool but its length window
    and hold one to `maximum_words` words: short, well-formed scripts of the
    kind a person types to try a voice (D6). (line id, text), one per
    normalized text, in line order."""
    import audio_qc_script_pool as pool  # imported late: only a custom plan reads sentences
    numbered = [(number, line) for number, line in enumerate(lines, start=1) if line.strip()]
    names = pool.name_lexicon([line for _number, line in numbered], language)
    unique: dict[str, tuple[str, str]] = {}
    for number, line in numbered:
        if pool.text_rejection(line, language, names) != "lengthWindow":
            continue
        if not 1 <= len(pool.normalized_units(line, language)) <= maximum_words:
            continue
        unique.setdefault(pool.normalized_text(line, language), (f"cv-{language}-{number}", line))
    return list(unique.values())


def short_sentences(language: str, maximum_words: int) -> list[tuple[str, str]]:
    """`short_sentence_candidates` over the pinned Common Voice file the
    script pool is drawn from (config/audio-qc-script-pool-sources.json)."""
    import audio_qc_script_pool as pool
    sources = read_json(pool.SOURCES_PATH)
    pins = {entry["language"]: entry for entry in sources["languages"]}
    if language not in pins:
        raise ScreenError(f"{language}: no pinned sentence file")
    try:
        lines = pool.read_source_lines(pool.source_directory(sources) / pins[language]["path"], pins[language])
    except pool.ScriptPoolError as error:
        raise ScreenError(str(error)) from None
    return short_sentence_candidates(lines, language, maximum_words)


def build_custom_plan(screen: dict, seed_set: int, languages: list[str] | None = None) -> dict:
    """Single Built-in Voice takes of short scripts (D6): per language,
    `scriptsPerLanguage` short sentences (`short_sentences`, at most
    `maximumWords` words), each spoken once by the next of `speakers` and sent
    with the request language `requestLanguage`. A script is its own cluster
    (`voice`)."""
    order = list(screen["languages"])
    selected = languages or order
    unknown = [language for language in selected if language not in order]
    if unknown:
        raise ScreenError(f"not in the screen: {', '.join(unknown)}")
    count, speakers = screen["scriptsPerLanguage"], screen["speakers"]
    takes = []
    for language in selected:
        candidates = short_sentences(language, screen["maximumWords"])
        candidates.sort(key=lambda candidate: rank(f"{screen['name']}|{language}|script|{candidate[0]}"))
        if len(candidates) < count:
            raise ScreenError(f"{language}: fewer than {count} short sentences")
        offset = order.index(language)
        for index, (script_id, text) in enumerate(candidates[:count]):
            take_id = f"{language}-{index + 1:02d}"
            takes.append({"takeID": take_id, "voice": take_id, "mode": "custom", "language": language,
                          "requestLanguage": screen["requestLanguage"],
                          "speaker": speakers[(index + offset) % len(speakers)], "scriptID": script_id,
                          "text": text, "seed": take_seed(screen, seed_set, take_id)})
    plan = {"schemaVersion": SCHEMA_VERSION, "screen": screen["name"], "screenVersion": screen["version"],
            "kind": "custom", "mode": "custom", "variant": screen["variant"], "seedSet": seed_set, "voices": [],
            "takes": takes}
    plan["planSHA256"] = sha256_text(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    return plan


def long_form_command(vocello: Path, plan: dict, take: dict, wav: Path, common: list[str]) -> list[str]:
    voice = ["--speaker", take["speaker"]] if take["mode"] == "custom" else ["--voice-brief", take["voiceBrief"]]
    return [str(vocello), "generate", "--mode", take["mode"], "--variant", plan["variant"], *voice,
            "--text", take["text"], "--language", take["language"], "--seed", str(take["seed"]),
            "--variation", take["variation"], "--long-form", plan.get("longForm", "always"), "--out", str(wav), *common]


def segment_summary(result: dict) -> dict:
    """What a project's segments say: how many, how each ended, and how many
    passed with Fast QC warnings (a refused segment fails the project)."""
    segments = result.get("longFormSegments") or []
    reasons: dict[str, int] = {}
    for segment in segments:
        reason = segment.get("finishReason") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
    return {"count": len(segments), "finishReasons": dict(sorted(reasons.items())),
            "warned": sum(bool(segment.get("qcWarnings")) for segment in segments),
            "warnings": sorted({warning for segment in segments for warning in segment.get("qcWarnings") or []}),
            "longestSeconds": max((segment.get("durationSeconds") or 0 for segment in segments), default=0)}


# ---------------------------------------------------------------- run


def parse_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        name, separator, setting = value.partition("=")
        if not separator or not name.startswith(PASS_THROUGH_PREFIXES):
            raise ScreenError(f"--env takes KEY=VALUE with a {', '.join(PASS_THROUGH_PREFIXES)} key: {value!r}")
        overrides[name] = setting
    return overrides


def plan_for_variant(plan: dict, variant: str | None) -> tuple[dict, str | None]:
    """The plan an arm runs: the screen's own, or the same takes on another
    installed variant of the model (`run --variant`), which the arm records.
    The plan's digest is unchanged: the takes are the same."""
    if variant is None or variant == plan["variant"]:
        return plan, None
    return dict(plan, variant=variant), variant


def git_value(*arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def invoke(command: list[str], environment: dict[str, str]) -> tuple[int, dict]:
    """Runs one `vocello --json` command; its one JSON document is the answer
    whether it succeeded or not."""
    completed = subprocess.run(command, env=environment, text=True, capture_output=True, check=False)
    for stream in (completed.stdout, completed.stderr):
        for line in reversed(stream.strip().splitlines()):
            if line.startswith("{"):
                try:
                    return completed.returncode, json.loads(line)
                except json.JSONDecodeError:
                    continue
    return completed.returncode, {}


def outcome_of(code: int, document: dict) -> tuple[str, str | None]:
    """generated, refused (Fast QC or the generation limit: the engine made a
    take it would not publish) or failed (anything else)."""
    if code == 0 and document.get("ok"):
        return "generated", None
    error = document.get("error") or {}
    reason = (error.get("detail") or {}).get("reason") or error.get("code") or f"exit {code}"
    return ("refused" if error.get("code") == "qc_rejected" else "failed"), reason


def run_arm(args: argparse.Namespace) -> Path:
    plan_path = Path(args.plan)
    plan = read_json(plan_path)
    arm_dir = plan_path.parent / "arms" / args.arm
    if arm_dir.exists():
        raise ScreenError(f"arm '{args.arm}' already exists; an arm is never regenerated in place")
    vocello = Path(args.vocello) if args.vocello else managed_output_path("QVOICE_BUILD_ROOT") / "vocello"
    if not vocello.exists():
        raise ScreenError(f"{vocello} is missing; run scripts/build.sh cli-optimized")
    overrides = parse_overrides(args.env or [])
    plan, variant = plan_for_variant(plan, getattr(args, "variant", None))
    transcript_form = getattr(args, "transcript_form", None) or "as-given"
    enrolled_transcript("", transcript_form)
    if transcript_form != "as-given" and plan.get("kind") in ("long-form", "custom"):
        raise ScreenError("--transcript-form applies to a screen with references")
    data_dir = arm_dir / "data"
    data_dir.mkdir(parents=True)
    (arm_dir / "wav").mkdir()
    models = Path(args.models_root).resolve() if getattr(args, "models_root", None) else DEBUG_ROOT / "models"
    if not models.exists():
        raise ScreenError(f"the model root {models.name} is missing; run scripts/macos_test.sh models ensure")
    (data_dir / "models").symlink_to(models.resolve(), target_is_directory=True)
    environment = dict(os.environ, **overrides)
    environment["QWENVOICE_DEBUG"] = "1"
    arm = {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "planSHA256": plan["planSHA256"],
           "environment": overrides, "executableSHA256": sha256_file(vocello.resolve()),
           "commit": git_value("rev-parse", "HEAD"), "dirtyPaths": len(git_value("status", "--porcelain").splitlines())}
    if variant:
        arm["variant"] = variant
    if transcript_form != "as-given":
        arm["transcriptForm"] = transcript_form
    manifest = Path(args.manifest).resolve() if getattr(args, "manifest", None) else None
    if manifest:
        # A development contract (a built hybrid, RF-55): its digest names the models the arm ran.
        arm.update(manifest=manifest.name, manifestSHA256=sha256_file(manifest), modelsRoot=str(models))
    write_json(arm_dir / "arm.json", arm)
    common = ["--data-dir", str(data_dir), "--json", "--quiet", "--no-input",
              *(["--manifest", str(manifest)] if manifest else [])]
    if plan.get("kind") == "long-form":
        return run_long_form_arm(args, plan, arm, arm_dir, vocello, environment, common)
    if plan.get("kind") == "custom":
        return run_custom_arm(args, plan, arm, arm_dir, vocello, environment, common)

    # A reference that is not the file the plan was made from would fail or
    # change its voice's takes, and the arm would carry the blame.
    for voice in plan["voices"]:
        if not Path(voice["audio"]).is_file() or sha256_file(Path(voice["audio"])) != voice["audioSHA256"]:
            raise ScreenError(f"{voice['voice']}: the reference is missing or not the one the plan names; plan again")
    enrolled: dict[str, str | None] = {}
    for voice in plan["voices"]:
        code, document = invoke([
            str(vocello), "voices", "enroll", "--name", voice["voice"], "--audio", voice["audio"],
            "--transcript", enrolled_transcript(voice["transcript"], transcript_form), "--language", voice["language"],
            "--on-warnings", "keep", "--confirm-consent", *common], environment)
        enrolled[voice["voice"]] = None if code == 0 and document.get("ok") else (
            (document.get("error") or {}).get("code") or f"exit {code}")

    rows = []
    for index, take in enumerate(plan["takes"], start=1):
        row = {"takeID": take["takeID"], "seed": take["seed"]}
        if enrolled[take["voice"]] is not None:
            row.update(outcome="failed", reason=f"voice not enrolled ({enrolled[take['voice']]})")
        else:
            wav = arm_dir / "wav" / f"{take['takeID']}.wav"
            code, document = invoke([
                str(vocello), "generate", "--mode", plan["mode"], "--variant", plan["variant"],
                "--voice", take["voice"], "--confirm-consent", "--text", take["text"], "--seed", str(take["seed"]),
                "--long-form", "never", "--out", str(wav), *common], environment)
            outcome, reason = outcome_of(code, document)
            row.update(outcome=outcome, reason=reason)
            if outcome == "generated":
                if not wav.is_file():
                    row.update(outcome="failed", reason="no output file")
                else:
                    result = document["result"]
                    quality = result.get("audioQC") or {}
                    row.update(wav=str(wav.relative_to(arm_dir)), pcmSHA256=pcm_digest(wav),
                               generationID=result.get("generationID"),
                               durationSeconds=result.get("durationSeconds"), finishReason=result.get("finishReason"),
                               wallSeconds=result.get("wallSeconds"),
                               fastQC={key: quality.get(key) for key in (
                                   "verdict", "flags", "trailingSilenceMS", "longestSilenceMS", "stepBurstPeakCount",
                                   "clickEventCount", "clippedSamples", "rmsDBFS", "instabilityVerdict")})
        rows.append(row)
        if index % 20 == 0 or index == len(plan["takes"]):
            write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
            print(f"{args.arm}: {index}/{len(plan['takes'])} takes", flush=True)
    evidence = arm_evidence(data_dir / "diagnostics/engine/generations.jsonl", rows)
    write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
    counts = {name: sum(row["outcome"] == name for row in rows) for name in ("generated", "refused", "failed")}
    unread = unread_overrides(overrides, evidence["activeOverrideKeys"])
    write_json(arm_dir / "arm.json", dict(
        arm, complete=not unread, outcomes=counts, activeOverrideKeys=evidence["activeOverrideKeys"],
        overridesNotRead=unread, voicesNotEnrolled=sum(value is not None for value in enrolled.values())))
    print(json.dumps({"arm": args.arm, "outcomes": counts, "activeOverrideKeys": evidence["activeOverrideKeys"]}))
    if unread:
        raise ScreenError(f"the engine never read {', '.join(unread)}: this arm ran as the control and is not usable")
    return arm_dir


def run_long_form_arm(args: argparse.Namespace, plan: dict, arm: dict, arm_dir: Path, vocello: Path,
                      environment: dict[str, str], common: list[str]) -> Path:
    rows = []
    for index, take in enumerate(plan["takes"], start=1):
        wav = arm_dir / "wav" / f"{take['takeID']}.wav"
        code, document = invoke(long_form_command(vocello, plan, take, wav, common), environment)
        outcome, reason = outcome_of(code, document)
        row = {"takeID": take["takeID"], "seed": take["seed"], "outcome": outcome, "reason": reason}
        if outcome == "generated":
            if not wav.is_file():
                row.update(outcome="failed", reason="no output file")
            else:
                result = document["result"]
                row.update(wav=str(wav.relative_to(arm_dir)), pcmSHA256=pcm_digest(wav),
                           generationID=result.get("generationID"), durationSeconds=result.get("durationSeconds"),
                           finishReason=result.get("finishReason"), wallSeconds=result.get("wallSeconds"),
                           segments=segment_summary(result))
        rows.append(row)
        if index % 10 == 0 or index == len(plan["takes"]):
            write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
    counts = {kind: sum(row["outcome"] == kind for row in rows) for kind in ("generated", "refused", "failed")}
    # A long-form project's engine rows are its segments; any of them names
    # the keys the engine read.
    active: set[str] = set()
    telemetry = arm_dir / "data/diagnostics/engine/generations.jsonl"
    if telemetry.is_file():
        for line in telemetry.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            provenance = ((record.get("summary") or {}).get("runEnvironment") or {}).get("runtimeDebugProvenance") or {}
            active.update(provenance.get("activeOverrideKeys") or [])
    unread = unread_overrides(arm["environment"], sorted(active))
    write_json(arm_dir / "arm.json", dict(arm, complete=not unread, outcomes=counts, activeOverrideKeys=sorted(active),
                                          overridesNotRead=unread))
    print(json.dumps({"arm": args.arm, "outcomes": counts, "activeOverrideKeys": sorted(active)}))
    if unread:
        raise ScreenError(f"the engine never read {', '.join(unread)}: this arm ran as the control and is not usable")
    return arm_dir


def run_custom_arm(args: argparse.Namespace, plan: dict, arm: dict, arm_dir: Path, vocello: Path,
                   environment: dict[str, str], common: list[str]) -> Path:
    """One Built-in Voice take per planned script, each in its own process,
    sent with the plan's request language."""
    rows = []
    for index, take in enumerate(plan["takes"], start=1):
        wav = arm_dir / "wav" / f"{take['takeID']}.wav"
        code, document = invoke([
            str(vocello), "generate", "--mode", "custom", "--variant", plan["variant"], "--speaker", take["speaker"],
            "--text", take["text"], "--language", take["requestLanguage"], "--seed", str(take["seed"]),
            "--long-form", "never", "--out", str(wav), *common], environment)
        outcome, reason = outcome_of(code, document)
        row = {"takeID": take["takeID"], "seed": take["seed"], "outcome": outcome, "reason": reason}
        if outcome == "generated":
            if not wav.is_file():
                row.update(outcome="failed", reason="no output file")
            else:
                result = document["result"]
                quality = result.get("audioQC") or {}
                row.update(wav=str(wav.relative_to(arm_dir)), pcmSHA256=pcm_digest(wav),
                           generationID=result.get("generationID"), durationSeconds=result.get("durationSeconds"),
                           finishReason=result.get("finishReason"), wallSeconds=result.get("wallSeconds"),
                           fastQC={key: quality.get(key) for key in (
                               "verdict", "flags", "trailingSilenceMS", "longestSilenceMS", "rmsDBFS",
                               "instabilityVerdict")})
        rows.append(row)
        if index % 20 == 0 or index == len(plan["takes"]):
            write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
    evidence = arm_evidence(arm_dir / "data/diagnostics/engine/generations.jsonl", rows)
    write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
    counts = {kind: sum(row["outcome"] == kind for row in rows) for kind in ("generated", "refused", "failed")}
    unread = unread_overrides(arm["environment"], evidence["activeOverrideKeys"])
    write_json(arm_dir / "arm.json", dict(arm, complete=not unread, outcomes=counts,
                                          activeOverrideKeys=evidence["activeOverrideKeys"], overridesNotRead=unread))
    print(json.dumps({"arm": args.arm, "outcomes": counts, "activeOverrideKeys": evidence["activeOverrideKeys"]}))
    if unread:
        raise ScreenError(f"the engine never read {', '.join(unread)}: this arm ran as the control and is not usable")
    return arm_dir


def refresh_evidence(args: argparse.Namespace) -> int:
    """Reads an arm's evidence again from the telemetry it kept. The takes are
    not touched: this only repeats what `run` does after its last take."""
    arm_dir = Path(args.run) / "arms" / args.arm
    arm = read_json(arm_dir / "arm.json")
    rows = read_json(arm_dir / "takes.json")["takes"]
    if "outcomes" not in arm or len(rows) != len(read_json(Path(args.run) / "plan.json")["takes"]):
        raise ScreenError(f"arm '{args.arm}' did not finish generating")
    evidence = arm_evidence(arm_dir / "data/diagnostics/engine/generations.jsonl", rows)
    unread = unread_overrides(arm["environment"], evidence["activeOverrideKeys"])
    write_json(arm_dir / "takes.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "takes": rows})
    write_json(arm_dir / "arm.json", dict(arm, complete=not unread, overridesNotRead=unread,
                                          activeOverrideKeys=evidence["activeOverrideKeys"]))
    print(json.dumps({"arm": args.arm, "complete": not unread, "activeOverrideKeys": evidence["activeOverrideKeys"],
                      "takesWithReferenceDigest": sum(bool(row.get("referenceAudioDigest")) for row in rows)}))
    return 2 if unread else 0


def arm_evidence(telemetry: Path, rows: list[dict]) -> dict:
    """What the engine's own rows say the arm was: the override keys it read,
    and for each take the digest of the reference audio it was conditioned on.
    An arm is believed from this, not from the environment it was given."""
    # The CLI prints a generation's identifier in lowercase; the engine's row
    # carries it in uppercase.
    by_generation = {row["generationID"].lower(): row for row in rows if row.get("generationID")}
    active: set[str] = set()
    if telemetry.is_file():
        for line in telemetry.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = by_generation.get(str(record.get("generationID") or "").lower())
            if row is None:
                continue
            provenance = ((record.get("summary") or {}).get("runEnvironment") or {}).get("runtimeDebugProvenance") or {}
            active.update(provenance.get("activeOverrideKeys") or [])
            receipt = record.get("requestReceipt") or {}
            row["referenceAudioDigest"] = receipt.get("normalizedReferenceAudioDigest")
            # The language the engine sent and the one it detected in the
            # script (absent when detection could not decide).
            if receipt.get("finalModelLanguage") is not None:
                row["finalModelLanguage"] = receipt["finalModelLanguage"]
                row["detectedTargetLanguage"] = receipt.get("detectedTargetLanguage")
            codes = generated_code_count(record)
            if codes is not None:
                row["generatedCodeCount"] = codes
    return {"activeOverrideKeys": sorted(active)}


def generated_code_count(record: dict) -> int | None:
    """The talker's codec frames for a take, from the engine row's own timing
    map (`qwen_generated_code_count`), wherever the row nests it."""
    stack = [record]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if isinstance(value.get("qwen_generated_code_count"), int):
                return value["qwen_generated_code_count"]
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return None


def unread_overrides(overrides: dict[str, str], active: list[str]) -> list[str]:
    """The app's own keys that no take reported as read. MLX reads its keys
    itself and the registry cannot see them, so they are not checked."""
    return sorted(name for name in overrides if not name.startswith("MLX_") and name not in active)


# ---------------------------------------------------------------- score


def normalized_units(text: str, language: str) -> list[str]:
    """NFKC, lowercase, punctuation and symbols to spaces; words, or characters
    for the languages compared by character."""
    folded = unicodedata.normalize("NFKC", text).lower()
    cleaned = "".join(" " if unicodedata.category(char)[0] in "PSZC" else char for char in folded)
    if language in CHARACTER_LANGUAGES:
        return [char for char in cleaned if not char.isspace()]
    return cleaned.split()


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, heard in enumerate(hypothesis, start=1):
            current.append(min(previous[column] + 1, current[column - 1] + 1,
                               previous[column - 1] + (expected != heard)))
        previous = current
    return previous[-1]


def error_rate(reference_text: str, hypothesis_text: str, language: str) -> float | None:
    reference = normalized_units(reference_text, language)
    if not reference:
        return None
    return edit_distance(reference, normalized_units(hypothesis_text, language)) / len(reference)


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def qc_store():
    from qc import store  # scripts/qc; imported late so `plan` and `compare` need no QC tree state
    return store


def score_arm(args: argparse.Namespace) -> Path:
    run_dir = Path(args.run)
    plan = read_json(run_dir / "plan.json")
    arm_dir = run_dir / "arms" / args.arm
    arm = read_json(arm_dir / "arm.json")
    if not arm.get("complete"):
        raise ScreenError(f"arm '{args.arm}' did not finish generating")
    takes = {row["takeID"]: row for row in read_json(arm_dir / "takes.json")["takes"]}
    planned = {take["takeID"]: take for take in plan["takes"]}
    voices = {voice["voice"]: voice for voice in plan["voices"]}
    # A Built-in Voice take of a few words is too short for a speaker
    # embedding and has no reference: only its words are scored.
    speaker_scored = plan.get("kind") != "custom"
    store = qc_store()
    manifest_takes = []
    for take_id, row in takes.items():
        if row["outcome"] != "generated":
            continue
        take, audio = planned[take_id], arm_dir / row["wav"]
        voice = voices.get(take["voice"])
        entry = {
            "takeID": take_id, "token": store.take_token(f"{plan['planSHA256'][:12]}-{args.arm}", take_id),
            "audio": str(audio), "audioSHA256": store.audio_sha256(audio), "language": take["language"],
            "text": take["text"], "mode": take.get("mode") or plan["mode"], "voice": take["voice"],
            "cell": plan["screen"], "finishReason": row.get("finishReason"), "seed": row["seed"],
            "family": take["scriptID"]}
        if voice:
            entry.update(reference=voice["audio"], referenceSHA256=store.audio_sha256(Path(voice["audio"])),
                         referenceText=voice["transcript"])
        manifest_takes.append(entry)
    manifest_path = arm_dir / "qc-takes.json"
    write_json(manifest_path, {"schema": store.TAKES_SCHEMA, "source": f"quality-screen-{args.arm}", "takes": manifest_takes})
    if not args.cache_only:
        python = subprocess.run([sys.executable, str(ROOT / "scripts/select_python.py")],
                                text=True, capture_output=True, check=True).stdout.strip()
        completed = subprocess.run(
            [python, str(ROOT / "scripts/qc.py"), "run", "--takes", str(manifest_path), "--lane", "quality-screen",
             "--models", ",".join((*ASR_MODELS, SPEAKER_MODEL) if speaker_scored else ASR_MODELS)],
            cwd=ROOT, check=False)
        if completed.returncode != 0:
            raise ScreenError(f"QC scoring failed (exit {completed.returncode}); nothing was scored for this arm")

    def result(model: str, take: dict, variant: bool) -> dict:
        # The store keys a variant model's result by script, language and
        # reference, the reference absent for Custom and Design.
        key = store.variant_key(take["text"], take["language"], take.get("referenceSHA256")) if variant else None
        path = QC_RESULTS / model / f"{store.result_stem(take['audioSHA256'], key)}.json"
        if not path.is_file():
            raise ScreenError(f"{take['takeID']}: no {model} result; a take is never scored in part")
        return read_json(path)

    scores = {}
    for take in manifest_takes:
        speaker = result(SPEAKER_MODEL, take, True) if speaker_scored else {"outputs": {}}
        asr = {model: result(model, take, False) for model in ASR_MODELS}
        failed = [model for model, value in [(SPEAKER_MODEL, speaker), *asr.items()]
                  if "outputs" not in value and not is_measured_outcome(value)]
        if failed:
            raise ScreenError(f"{take['takeID']}: the {', '.join(failed)} runner reported an error")
        rates = {model: error_rate(take["text"], (value.get("outputs") or {}).get("text") or "", take["language"])
                 for model, value in asr.items()}
        score = {"speakerSimilarity": None, "errorRate": rates}
        if "outputs" in speaker and speaker["outputs"].get("reference"):
            score["speakerSimilarity"] = cosine(speaker["outputs"]["whole"], speaker["outputs"]["reference"])
            score.update(window_similarities(speaker["outputs"]))
        elif "outputs" in speaker:
            spread = window_spread(speaker["outputs"])
            if spread is not None:
                score["speakerWindowSpread"] = spread
        else:
            # Too short for a speaker embedding: a take that cannot hold its
            # script, counted as a gross failure rather than dropped.
            score["tooShortToScore"] = True
        scores[take["takeID"]] = score
    write_json(arm_dir / "scores.json", {"schemaVersion": SCHEMA_VERSION, "arm": args.arm, "scores": scores})
    print(json.dumps({"arm": args.arm, "scored": len(scores)}))
    return arm_dir / "scores.json"


def window_similarities(outputs: dict) -> dict[str, float]:
    """The take's worst speaker window and the mean of its late windows (those
    starting at LATE_FROM_SECONDS or later), each as similarity to the
    reference; a take with no late window has no late value."""
    reference = outputs.get("reference")
    windows = [window for window in outputs.get("windows") or [] if window.get("embedding")]
    if not reference or not windows:
        return {}
    values = {"speakerSimilarityWorstWindow": min(cosine(window["embedding"], reference) for window in windows)}
    late = [cosine(window["embedding"], reference) for window in windows if window["start"] >= LATE_FROM_SECONDS]
    if late:
        values["speakerSimilarityLate"] = sum(late) / len(late)
    return values


def window_spread(outputs: dict) -> float | None:
    """How far the take's speaker windows drift from the take as a whole: the
    range of their cosine distances to its whole embedding. Higher is less
    consistent; None for a take of one window."""
    whole = outputs.get("whole")
    windows = [window for window in outputs.get("windows") or [] if window.get("embedding")]
    if not whole or len(windows) < 2:
        return None
    distances = [1.0 - cosine(window["embedding"], whole) for window in windows]
    return max(distances) - min(distances)


def is_measured_outcome(result: dict) -> bool:
    """A runner's refusal that says something about the take itself: audio
    too short to embed. Any other runner error is a scoring failure."""
    return result.get("error") == "audio-too-short"


# ---------------------------------------------------------------- compare

# Higher is worse for every metric here except the speaker similarities.
SIMILARITY_METRICS = ("speakerSimilarity", "speakerSimilarityLate", "speakerSimilarityWorstWindow")
METRICS = (*SIMILARITY_METRICS, "errorRateBetterFamily", "errorRate:" + ASR_MODELS[0],
           "errorRate:" + ASR_MODELS[1], "trailingSilenceMS", "durationSeconds",
           "speakerWindowSpread", "segmentsWarned")
# A take whose better ASR family misses half of the script says something else.
GROSS_ERROR_RATE = 0.5
# Every edit rate is read bounded at one edit per script unit.
MAXIMUM_EDIT_RATE = 1.0


def take_metrics(row: dict, score: dict | None) -> dict[str, float]:
    values: dict[str, float] = {}
    if row.get("durationSeconds") is not None:
        values["durationSeconds"] = row["durationSeconds"]
    silence = (row.get("fastQC") or {}).get("trailingSilenceMS")
    if silence is not None:
        values["trailingSilenceMS"] = silence
    if row.get("segments"):
        values["segmentsWarned"] = row["segments"]["warned"]
    if score:
        for metric in (*SIMILARITY_METRICS, "speakerWindowSpread"):
            if score.get(metric) is not None:
                values[metric] = score[metric]
        # Bounded at 1 (since 2026-11-11): a recognizer that runs away on a
        # take inserts without limit, and one such take could carry a mean.
        rates = {model: min(rate, MAXIMUM_EDIT_RATE) for model, rate in score["errorRate"].items() if rate is not None}
        for model, rate in rates.items():
            values[f"errorRate:{model}"] = rate
        if rates:
            values["errorRateBetterFamily"] = min(rates.values())
    return values


def same_takes_other_seeds(plan: dict, other: dict) -> bool:
    """Two plans of one screen that differ only in their seed set."""
    def shape(value: dict) -> list:
        return [{key: take[key] for key in take if key != "seed"} for take in value["takes"]]
    return (plan["screen"], plan["screenVersion"], plan["voices"], shape(plan)) == (
        other["screen"], other["screenVersion"], other["voices"], shape(other))


def arm_view(run_dir: Path, name: str, plan: dict) -> dict:
    arm_dir = run_dir / "arms" / name
    arm = read_json(arm_dir / "arm.json")
    if arm.get("planSHA256") != plan["planSHA256"] or not arm.get("complete"):
        raise ScreenError(f"arm '{name}' is incomplete or belongs to another plan")
    rows = {row["takeID"]: row for row in read_json(arm_dir / "takes.json")["takes"]}
    scores_path = arm_dir / "scores.json"
    scores = read_json(scores_path)["scores"] if scores_path.is_file() else {}
    return {"arm": arm, "rows": rows, "scores": scores}


def bootstrap_interval(clusters: dict[str, list[float]], generator: random.Random) -> tuple[float, float]:
    """A 95% interval of the mean, resampling whole references: a reference's
    takes share its voice, so they are not independent observations."""
    names = sorted(clusters)
    means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        values = [value for name in generator.choices(names, k=len(names)) for value in clusters[name]]
        means.append(sum(values) / len(values))
    means.sort()
    return means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]


def summarize(plan: dict, a: dict, b: dict, takes: list[dict] | None = None) -> dict:
    takes = plan["takes"] if takes is None else takes
    generator = random.Random(20_261_111)
    outcomes = {name: {kind: sum(view["rows"][take["takeID"]]["outcome"] == kind for take in takes)
                       for kind in ("generated", "refused", "failed")} for name, view in (("a", a), ("b", b))}
    paired = [take for take in takes
              if a["rows"][take["takeID"]]["outcome"] == "generated" and b["rows"][take["takeID"]]["outcome"] == "generated"]
    identical = sum(a["rows"][take["takeID"]]["pcmSHA256"] == b["rows"][take["takeID"]]["pcmSHA256"] for take in paired)
    # Equal lengths: the same number of codec frames, so a change meant only
    # for the decoder left the talker alone.
    same_duration = sum(a["rows"][take["takeID"]].get("durationSeconds") is not None
                        and a["rows"][take["takeID"]].get("durationSeconds") == b["rows"][take["takeID"]].get("durationSeconds")
                        for take in paired)
    # The talker's own count of codec frames: unlike a take's length, which a
    # clone's onset trim can move, it changes only when the talker did.
    same_codes = sum(a["rows"][take["takeID"]].get("generatedCodeCount") is not None
                     and a["rows"][take["takeID"]].get("generatedCodeCount")
                     == b["rows"][take["takeID"]].get("generatedCodeCount")
                     for take in paired)
    metrics = {}
    for metric in METRICS:
        clusters: dict[str, list[float]] = {}
        a_values, b_values = [], []
        for take in paired:
            left = take_metrics(a["rows"][take["takeID"]], a["scores"].get(take["takeID"])).get(metric)
            right = take_metrics(b["rows"][take["takeID"]], b["scores"].get(take["takeID"])).get(metric)
            if left is None or right is None:
                continue
            a_values.append(left)
            b_values.append(right)
            clusters.setdefault(take["voice"], []).append(right - left)
        if not clusters:
            continue
        differences = [value for values in clusters.values() for value in values]
        low, high = bootstrap_interval(clusters, generator)
        metrics[metric] = {"pairs": len(differences), "meanA": sum(a_values) / len(a_values),
                           "meanB": sum(b_values) / len(b_values), "meanDifference": sum(differences) / len(differences),
                           "interval95": [low, high], "largestAbsoluteDifference": max(abs(value) for value in differences)}

    def gross(view: dict) -> int:
        count = 0
        for take in takes:
            row = view["rows"][take["takeID"]]
            score = view["scores"].get(take["takeID"])
            rate = take_metrics(row, score).get("errorRateBetterFamily")
            runaway = bool(((row.get("segments") or {}).get("finishReasons") or {}).get("maximum_tokens"))
            count += (row["outcome"] != "generated"
                      or bool(score and score.get("tooShortToScore"))
                      or (rate is not None and rate >= GROSS_ERROR_RATE)
                      or runaway)
        return count

    def warned(view: dict) -> int:
        return sum(bool((view["rows"][take["takeID"]].get("fastQC") or {}).get("flags")) for take in takes)

    references = [(a["rows"][take["takeID"]].get("referenceAudioDigest"), b["rows"][take["takeID"]].get("referenceAudioDigest"))
                  for take in paired]
    return {"planned": len(takes), "outcomes": outcomes, "paired": len(paired), "identicalPCM": identical,
            "sameDuration": same_duration, "sameCodeCount": same_codes,
            "referenceAudioDiffers": sum(1 for left, right in references if left and right and left != right),
            "grossFailures": {"a": gross(a), "b": gross(b)}, "fastQCWarned": {"a": warned(a), "b": warned(b)},
            "scored": bool(a["scores"]) and bool(b["scores"]), "metrics": metrics}


POPULATIONS = ("undetected-language",)


def undetected_language(row: dict) -> bool:
    """The engine's receipt says it could not tell the script's language (it
    names the language it sent but none it detected)."""
    return "finalModelLanguage" in row and row.get("detectedTargetLanguage") is None


def population_takes(plan: dict, a: dict, b: dict, name: str) -> list[dict]:
    """The takes a rule decides on. `undetected-language`: those whose script
    either arm's receipt found no language in (D6); every other take is
    outside the change and should be identical in both arms."""
    if name not in POPULATIONS:
        raise ScreenError(f"population '{name}' is not one of {', '.join(POPULATIONS)}")
    return [take for take in plan["takes"]
            if undetected_language(a["rows"][take["takeID"]]) or undetected_language(b["rows"][take["takeID"]])]


def floor_violations(rule: dict, floor: dict | None) -> list[str]:
    """A rule may require the screen's own noise floor to sit well inside its
    margins: a floor report (compare --expect noise of the same population
    under two seed sets) whose bound on a guard exceeds the given share of
    that guard's margin makes the screen unable to decide."""
    share = rule.get("maximumFloorShareOfMargin")
    if share is None:
        return []
    if floor is None:
        return ["the rule needs this screen's noise floor (--floor)"]
    reasons = []
    for metric, guard in rule["guards"].items():
        measured = (floor.get("metrics") or {}).get(metric)
        if not measured:
            reasons.append(f"the noise floor did not measure {metric}")
            continue
        bound = max(abs(value) for value in measured["interval95"])
        if bound > share * guard["margin"]:
            reasons.append(f"the noise floor of {metric} ({bound:.4g}) exceeds {share} of its margin")
    return reasons


def decide(summary: dict, rule: dict, floor: dict | None = None) -> dict:
    """ADOPT when arm B fails no more takes than arm A (within the allowance)
    and is not worse on any guarded metric beyond its margin; REJECT when it is
    worse beyond a margin with the interval excluding zero harm; otherwise
    INCONCLUSIVE."""
    reasons, harms = [], []
    extra = summary["grossFailures"]["b"] - summary["grossFailures"]["a"]
    if extra > rule["maximumExtraGrossFailures"]:
        harms.append(f"{extra} more gross failures than arm A")
    for metric, guard in rule["guards"].items():
        measured = summary["metrics"].get(metric)
        if not measured:
            reasons.append(f"{metric} was not measured")
            continue
        low, high = measured["interval95"]
        # Signed so that positive is harm.
        worst = -low if guard["higherIsBetter"] else high
        best = -high if guard["higherIsBetter"] else low
        if best > guard["margin"]:
            harms.append(f"{metric} is worse by more than {guard['margin']}")
        elif worst > guard["margin"]:
            reasons.append(f"{metric}: the interval reaches past the margin of {guard['margin']}")
    if rule.get("requiresSameCodeCount") and summary.get("sameCodeCount") != summary.get("paired"):
        reasons.append(f"{summary.get('paired', 0) - summary.get('sameCodeCount', 0)} paired takes changed their "
                       "talker's code count, so the change reached the talker")
    if rule.get("requiresSameDuration") and summary.get("sameDuration") != summary.get("paired"):
        reasons.append(f"{summary.get('paired', 0) - summary.get('sameDuration', 0)} paired takes changed length, "
                       "so the change reached the talker")
    reasons += floor_violations(rule, floor)
    verdict = "REJECT" if harms else ("INCONCLUSIVE" if reasons else "ADOPT")
    return {"verdict": verdict, "harms": harms, "open": reasons}


def compare_arms(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    plan = read_json(run_dir / "plan.json")
    a = arm_view(run_dir, args.a, plan)
    if args.b_run:
        # The noise floor: the same takes under other seeds, so the difference
        # is what sampling alone does to each metric.
        other_dir = Path(args.b_run)
        other_plan = read_json(other_dir / "plan.json")
        if args.expect != "noise" or not same_takes_other_seeds(plan, other_plan):
            raise ScreenError("--b-run compares the same takes under another seed set, with --expect noise only")
        b = arm_view(other_dir, args.b, other_plan)
    else:
        b = arm_view(run_dir, args.b, plan)
    summary = summarize(plan, a, b)
    # Report-only strata: a decision reads the whole population.
    layouts = {voice["voice"]: voice.get("channelLayout") for voice in plan["voices"]}
    if any(layouts.values()):
        summary["strata"] = {
            layout: summarize(plan, a, b, [take for take in plan["takes"] if layouts[take["voice"]] == layout])
            for layout in sorted({value for value in layouts.values() if value})}
    if plan.get("kind") == "long-form":
        groups = sorted({take["stratum"] for take in plan["takes"]}) + sorted({take["variation"] for take in plan["takes"]})
        summary["strata"] = {group: summarize(plan, a, b, [take for take in plan["takes"]
                                                           if group in (take["stratum"], take["variation"])])
                             for group in groups}
    same_arm = (a["arm"]["environment"] == b["arm"]["environment"]
                and a["arm"]["executableSHA256"] == b["arm"]["executableSHA256"]
                and a["arm"].get("variant") == b["arm"].get("variant")
                and a["arm"].get("manifestSHA256") == b["arm"].get("manifestSHA256")
                and a["arm"].get("transcriptForm", "as-given") == b["arm"].get("transcriptForm", "as-given"))
    report = {"schemaVersion": SCHEMA_VERSION, "screen": plan["screen"], "planSHA256": plan["planSHA256"],
              "a": {"arm": args.a, **{key: a["arm"][key] for key in ("environment", "executableSHA256", "commit")},
                    "variant": a["arm"].get("variant") or plan["variant"],
                    "transcriptForm": a["arm"].get("transcriptForm", "as-given")},
              "b": {"arm": args.b, **{key: b["arm"][key] for key in ("environment", "executableSHA256", "commit")},
                    "variant": b["arm"].get("variant") or plan["variant"],
                    "transcriptForm": b["arm"].get("transcriptForm", "as-given")},
              "summary": summary}
    code = 0
    if args.expect == "identical":
        passed = (summary["identicalPCM"] == summary["paired"] == summary["planned"]
                  or (summary["identicalPCM"] == summary["paired"]
                      and summary["outcomes"]["a"] == summary["outcomes"]["b"]))
        report["verdict"] = "IDENTICAL" if passed else "DIFFERENT"
        code = 0 if passed else 1
    elif args.expect == "noise":
        report["verdict"] = "NOISE-FLOOR"
    else:
        screen = load_screen(plan["screen"])
        rule = (screen.get("rules") or {}).get(args.rule)
        if not rule or not rule.get("recorded"):
            raise ScreenError(f"rule '{args.rule}' is not recorded in {CONFIG.name}; a rule is written before its takes")
        if not summary["scored"]:
            raise ScreenError("both arms must be scored before a rule decides")
        if rule.get("population"):
            # The rule decides on its population; the whole plan is reported,
            # and the takes outside the population show whether the change
            # reached only it.
            members = population_takes(plan, a, b, rule["population"])
            inside = {take["takeID"] for take in members}
            outside = summarize(plan, a, b, [take for take in plan["takes"] if take["takeID"] not in inside])
            report["wholePlan"] = summary
            summary = summarize(plan, a, b, members)
            report["summary"] = summary
            report["population"] = {"name": rule["population"], "takes": len(members),
                                    "outsidePaired": outside["paired"], "outsideIdenticalPCM": outside["identicalPCM"]}
        if not same_arm and summary["paired"] and summary["identicalPCM"] == summary["paired"]:
            # Two arms that were meant to differ made the same samples: the
            # knob was not read, or it changes nothing on this population.
            report.update(verdict="INERT", decision={"verdict": "INERT", "harms": [], "open": []})
            code = 1
        else:
            floor = None
            if args.floor:
                floor_report = read_json(Path(args.floor))
                if floor_report.get("verdict") != "NOISE-FLOOR" or floor_report.get("screen") != plan["screen"]:
                    raise ScreenError("--floor takes this screen's noise-floor report (compare --expect noise)")
                floor = floor_report["summary"]
                report["floor"] = {"report": Path(args.floor).name, "a": floor_report["a"]["arm"], "b": floor_report["b"]["arm"]}
            decision = decide(summary, rule, floor)
            report.update(verdict=decision["verdict"], decision=decision, rule={"name": args.rule, **rule})
            code = 0 if decision["verdict"] == "ADOPT" else 1
    out = run_dir / f"compare-{args.a}-vs-{args.b}.json"
    write_json(out, report)
    print(json.dumps({"verdict": report["verdict"], "report": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else out.name,
                      **{key: summary[key] for key in ("planned", "outcomes", "paired", "identicalPCM", "sameDuration",
                                                       "sameCodeCount", "grossFailures")}},
                     indent=1))
    return code


# ---------------------------------------------------------------- commands


def command_plan(args: argparse.Namespace) -> int:
    screen = load_screen(args.screen)
    languages = [value for value in (args.languages or "").split(",") if value] or None
    variations = [value for value in (args.variations or "").split(",") if value] or None
    plan = build_plan(screen, args.seed_set, languages, variations)
    run_dir = Path(args.out) if args.out else (
        managed_output_path("QVOICE_ARTIFACTS_MACOS") / "quality-screen" / f"{args.screen}-{plan['planSHA256'][:12]}")
    if (run_dir / "plan.json").exists():
        if read_json(run_dir / "plan.json")["planSHA256"] != plan["planSHA256"]:
            raise ScreenError("another plan is already in that directory")
    else:
        write_json(run_dir / "plan.json", plan)
    print(json.dumps({"run": str(run_dir), "planSHA256": plan["planSHA256"], "voices": len(plan["voices"]),
                      "takes": len(plan["takes"]), "seedSet": plan["seedSet"]}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paired machine screens for the quality remediation.")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="write the take plan of a screen")
    plan.add_argument("--screen", required=True)
    plan.add_argument("--seed-set", type=int, default=1)
    plan.add_argument("--languages", help="a subset of the screen's languages (a long-form screen's strata), comma-separated")
    plan.add_argument("--variations", help="a long-form screen: a subset of its variations, comma-separated")
    plan.add_argument("--out", help="run directory (default: under build/artifacts)")
    plan.set_defaults(run_command=command_plan)
    run = commands.add_parser("run", help="generate one arm")
    run.add_argument("--plan", required=True)
    run.add_argument("--arm", required=True)
    run.add_argument("--env", action="append", help="KEY=VALUE for this arm's processes; repeatable")
    run.add_argument("--vocello", help="a preserved build (default: build/vocello)")
    run.add_argument("--transcript-form", choices=TRANSCRIPT_FORMS, default="as-given",
                     help="enroll each reference with its transcript as given or unpunctuated, as recognition gives it (G-15)")
    run.add_argument("--models-root", help="a model directory other than the debug root (a built hybrid's)")
    run.add_argument("--manifest", help="a development qwenvoice_contract.json for every command (a built hybrid's)")
    run.add_argument("--variant", choices=("speed", "quality"),
                     help="run the plan's takes on this installed variant instead of the screen's own")
    run.set_defaults(run_command=lambda args: (run_arm(args), 0)[1])
    score = commands.add_parser("score", help="score an arm with the QC v2 runners")
    score.add_argument("--run", required=True)
    score.add_argument("--arm", required=True)
    score.add_argument("--cache-only", action="store_true", help="read results already in the QC cache")
    score.set_defaults(run_command=lambda args: (score_arm(args), 0)[1])
    evidence = commands.add_parser("evidence", help="read an arm's evidence again from its telemetry")
    evidence.add_argument("--run", required=True)
    evidence.add_argument("--arm", required=True)
    evidence.set_defaults(run_command=refresh_evidence)
    compare = commands.add_parser("compare", help="compare two arms of one plan")
    compare.add_argument("--run", required=True)
    compare.add_argument("--a", required=True)
    compare.add_argument("--b", required=True)
    compare.add_argument("--b-run", help="arm B's run directory when it is the same plan under another seed set")
    compare.add_argument("--floor", help="with --rule: this screen's noise-floor report, when the rule requires one")
    mode = compare.add_mutually_exclusive_group(required=True)
    mode.add_argument("--expect", choices=("identical", "noise"))
    mode.add_argument("--rule")
    compare.set_defaults(run_command=compare_arms)
    args = parser.parse_args(argv)
    try:
        return args.run_command(args)
    except ScreenError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
