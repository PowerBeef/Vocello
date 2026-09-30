#!/usr/bin/env python3
"""The AQ-07 injected-defect set over natural takes, and its report-only scorer (M2).

Commands:
  inject  --takes <manifest> --output <dir> [--catalog-seed N] [--classes A,C,F] [--jobs N]
          [--alignments <alignments.json>] [--sample-per-cell N] [--sample-seed S] [--embed-text]
          Apply every applicable T1 injector of the selected classes (by default
          A signal, C boundary and the signal-level F prosody ones; A, B, C, D and
          F on N2) to every generated natural take (population N3) of an
          `audio-qc-calibration-takes` manifest, at mild, moderate and severe plus
          the family's sham. Writes <dir>/wav/<clip>.wav and
          <dir>/injection-set.json.
  verify  --set <injection-set.json> --takes <manifest> [--alignments <alignments.json>] [--jobs N]
          Replay every recipe from the source WAVs and require byte-identical
          output digests (and untouched output WAVs).
  score   --takes <manifest> [--set <injection-set.json>] --output <dir> [--jobs N]
          Run Fast QC v8 (the Python mirror in scripts/lib/audio_qc.py), the
          Stage 0 observations and the PCM shape measures
          (lib/qc_qualification/pcm_measures.py: flat tops, digital silence,
          the last active span) over every clean take (N3, or N1/N2 for a
          cohort), sham (S) and positive (P1); write measurements.json (ids and
          digests only), report.json and report.md. Without --set it scores the clean
          takes alone. A clip also carries its generation's Stage 0 evidence
          (`generation_evidence`): the engine introspection summary a take (or
          a T2/T3 entry, or a byte-copied donor) records, and a long-form
          take's `longForm` block, whose seams reach the Stage 0 seam z-score
          and whose boundary jump is measured on the clip's own PCM.
  alignments --takes <cohort manifest> --bundle <panel bundle> --output <alignments.json>
          [--cache-root <dir>]
          Export the forced aligner's word intervals for the cohort's takes from
          the orchestrator's L1 cache (see "Word intervals" below).
  raw-outputs --takes <cohort manifest or injection set> --bundle <panel bundle> --judge ID
          --output <raw-outputs.json> [--cache-root <dir>]
          Export one panel judge's raw output per take from the same L1 cache
          (`export_raw_outputs`: pYIN's frame track, a speaker judge's window
          embeddings), for the `raw-output` detectors
          (`audio_qc_detector_calibration.py scores --raw-outputs`).

`inject` and `verify` also take an `audio-qc-n1-cohort` manifest
(`scripts/audio_qc_n1_corpus.py`): its eligible FLEURS recordings (population
N1) are the sources, resampled from 16 kHz to the engine rate before any
injector runs, and every recipe records that resampling (`sourceResampling`,
`lib/qc_qualification/recordings.py`). Ineligible recordings are counted, never
injected. An `audio-qc-n2-cohort` manifest (`scripts/audio_qc_n2_resynthesis.py`)
is read the same way: every take is an eligible, generated 24 kHz PCM16
resynthesis whose `family` is its N1 recording. `score` labels a cohort's clean
takes N1 or N2: they carry published text (T4), so their flag rate bounds FAR
directly, without N3's f / (1 - pi_max) framing.

Sampling (`--sample-per-cell N --sample-seed S`). Injecting every variant into
every recording of a human cohort would write tens of gigabytes. For each
injector, N source families are drawn, stratified by language as evenly as the
eligible pool allows, by a seeded SHA-256 rank, so a rerun picks the same
families; the injector's sham and every severity use those same families, so
each (injector, severity) cell and its sham hold the same N families. The pool
of a word-level injector is the takes whose alignment is usable. The draw is
recorded in the set (`sampling`) and re-derived by `verify`. N2 defaults to 150
per cell; N1 and N3 default to every source (0 means every source).

Schedule (`SCHEDULE_VERSION`, recorded as the set's `schedule`). Version 2
draws, beside each injector's sham and severity sweep, the catalog's extra
variants at a severity a registered successor detector targets
(`SCHEDULE_EXTRAS`: SIG-CLIP soft-knee and over-range at moderate, BND-RUNON's
reversed tail at moderate), on the same sampled families, so the cell holds
every construction of the defect; the ones it leaves out say why
(`SCHEDULE_EXCLUDED`). A set without a `schedule` drew version 1, the sweep
alone, and `verify` replays any set by the plan rows it recorded, so earlier
sets stay verifiable. A plan binds the version it expects.

Word intervals. The panel's forced aligner (`align.qwen3-forcedaligner-0.6b@1`)
stored its raw output (units and intervals) in the orchestrator's L1 cache;
the bundle keeps only reduced metrics. `alignments` rebuilds each take's L1 key
as the orchestrator did (the evidence's audio and canonical digests, the
aligner's output identity from the evidence, its registry pins and the request
`panel_jobs.panel_request` builds), loads the digest-verified entry and writes
takeID -> intervals in seconds, each unit's text as a SHA-256 only. With
`--alignments`, the recording adapter gives every take with a usable alignment
word and pause intervals (`recordings.word_alignment`), and the word-level
injectors run through their catalog variants: CNT-DEL, CNT-REP, CNT-INS,
PRS-OCT, PRS-BRK and BND-TRUNC's word cuts (which then replace its take-* cut
at a fraction of the take). Korean is outside the aligner's scope, so its takes
keep no word interval.

Language swaps (class D, `LNG-SWAP`, `lib/qc_qualification/language_swap.py`):
on an N2 cohort, a source's FLoRes sentence read in another language (severe)
or by another recording in its own language (sham), presented with the
source's language and text; the clip is a byte copy of the donor's audio file.
Its `family` is the donor recording's.

Text. Entries built from an N1 or N2 cohort carry their source take's `text`
(for a language swap, the expected L1 text) bound by `textSHA256`, so
`audio_qc_orchestrator.py manifest --from-calibration-takes` can take the set;
N3 sets keep it in the takes manifest unless `--embed-text` is given. Sets are
untracked build artifacts, like the manifests that already carry the text.

Recorded takes carry no word intervals (they exist only from the aligner on N1
and N2), no declared pause, no script and no render voice
(`lib/qc_qualification/recordings.py`), so every variant that needs one raises
`InjectorNotApplicable` and is counted with its reason; injectors with a
word-free recording variant (`take-*`) use it instead. Identity swaps from the
N3 manifest's donor pairs are deferred: the donor take is another rendering with
its own timing, so it is not the time-aligned re-render the swap construction
splices, and aligning the two would need word intervals N3 never has.

Speaker donors (classes E and J, `lib/qc_qualification/speaker_donors.py`): on a
cohort whose takes name their `speaker` and `gender`, the take-* variants of
IDN-SWAP, IDN-ONSET and SEAM-VOICE splice a donor recording's words into the
source (another speaker of its language and gender for a positive, another
utterance of the source speaker for the sham), and IDN-IMPOSTOR presents another
speaker's recording (or, as its sham, the source speaker's other utterance) as the
source speaker, with the source take as the reference clip. Donors come from
the same manifest (so the same split), a splice's only from takes whose
alignment is usable; the choice is seeded by `--sample-seed`, recorded in each
entry and re-derived by `verify`. A take without a speaker label, or without a
donor of both relations, is not applicable, with that reason. An entry keeps the
reference clip its take declares (`reference`, which the orchestrator hands to
the speaker judges), its path made relative to the set; an impostor's reference
is its source take.

Seams (class J). A long-form take may declare its segment boundaries as
`seamSamples` (sample offsets at the engine rate on its own timeline); a take of
the take plan's long-form cell carries them as its `longForm` block's
`seamFrames`, which serve the same way (`take_seams`). SEAM-DISC
and SEAM-VOICE act at one of them; every entry carries the seams of its own
output (`seamSamples`) where the edit keeps them, and `score` passes them to the
Stage 0 seam z-score. An entry whose output keeps one seam per seam of its
take's `longForm` block (where they were, or moved by the construction)
records the block of its own output (its length, its seams and the boundary
jump its PCM16 steps at them, `output_long_form`), which `verify` checks, so
the detectors read the seams and the jump the clip has.

Voice donors (class J, `speaker_donors.VoicePool`). A generated long-form take
names no corpus speaker, but the voice it was generated with is its speaker
label (lead decision 2026-09-30): a Built-in speaker, a Voice Design brief, a
clone reference speaker, with the gender the committed take policy records
(`speakerGenders`, a brief's declared `gender`) or a clone reference's corpus
label. On an N3 manifest with long-form takes the plan schedules SEAM-VOICE's
`take-voice-*` variants: the segment after the seeded seam is replaced by
another long-form take of the same manifest (so the same split) and language,
of another voice whose gender is not known to differ, from the start of one of
its segments, or for the sham by another take of the same voice. The choice is
the speaker donors' seeded rule; each entry records its donor (take, family,
voice label, relation, WAV and PCM digests, seams), and `verify` re-derives and
replays it.

Catalog version. A set records the injector catalog version it was built with,
and `verify` replays only a set of the current version (3). A set of another
version is refused whole, with its version named: verify it with the code of
its version (a pre-registered plan binds the version its set was built with).

Report-only. N3 is unlabeled, so a flag rate f bounds the false-alarm rate only
as f / (1 - pi_max), and T1 on N3 qualifies nothing: a fail bound needs N2 and
a pre-registered plan (A2, A5). Everything is written under the caller's output
directory, an untracked build artifact; no model, device or native build runs.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, OrderedDict
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import numpy as np

import audio_qc_n1_corpus
import audio_qc_n2_resynthesis
import audio_qc_qualification as m1
from lib import audio_qc, audio_qc_observations
from lib.playback_capture import resample as polyphase_resample
from lib.qc_qualification import (
    injectors, language_swap, pcm_measures, policy as policy_module, recordings, resampling, speaker_donors,
)
from lib.qc_qualification.pcm import canonical_json, json_digest, pcm_digest, to_pcm16
from lib.qc_qualification.stats import DEFAULT_CONFIDENCE, Rate, bonferroni_confidence

TAKES_KIND = "audio-qc-calibration-takes"
# FLEURS human recordings (population N1), in the same take shape.
N1_KIND = audio_qc_n1_corpus.MANIFEST_KIND
# Their codec resyntheses (population N2): eligible, generated 24 kHz takes.
N2_KIND = audio_qc_n2_resynthesis.MANIFEST_KIND
TAKES_KINDS = (TAKES_KIND, N1_KIND, N2_KIND)
COHORT_KINDS = (N1_KIND, N2_KIND)
POPULATIONS = {TAKES_KIND: "N3", N1_KIND: "N1", N2_KIND: "N2"}
DEFAULT_N2_CLASSES = ("A", "B", "C", "D", "F")
# Source families per (injector, severity) cell, by population; 0 is every source.
DEFAULT_SAMPLE_PER_CELL = {"N3": 0, "N1": 0, "N2": 150}
DEFAULT_SAMPLE_SEED = 1
SAMPLE_SCHEMA = "vocello.audioqc.injection-sampling/1"
ALIGNMENTS_KIND = "audio-qc-alignments"
ALIGNER_JUDGE = "align.qwen3-forcedaligner-0.6b@1"
ALIGNMENT_STATUSES = ("complete", "no-evidence", "audio-differs", "text-differs", "not-run", "out-of-scope",
                      "unavailable", "not-in-cache", "cache-entry-invalid")
# With word intervals, these injectors run their catalog variants instead of their word-free take-* ones.
WORD_CATALOG_INJECTORS = ("BND-TRUNC",)
TEXT_POLICY_N3 = ("entries carry the source take's fields except its text, bound by textSHA256; the text stays in "
                  "the takes manifest")
TEXT_POLICY_EMBEDDED = ("entries carry their text (the source take's; for a language swap the expected L1 text), "
                        "bound by textSHA256, for the orchestrator's content and language metrics; the set is an "
                        "untracked build artifact, like the takes manifest")
# The take lane's statuses (scripts/audio_qc_calibration_takes.py): only generated takes have audio.
TAKE_STATUSES = ("generated", "rejected", "failed", "missing")
SET_KIND = "audio-qc-injection-set"
MEASUREMENTS_KIND = "audio-qc-calibration-measurements"
REPORT_SCHEMA = "vocello.audioqc.calibration-report/1"
GENERATOR = "audio-qc-calibration-set/1"
SEED_SCHEMA = "vocello.audioqc.calibration-seed/1"
SEVERITY_SWEEP = ("sham", "mild", "moderate", "severe")
# The schedule a set draws, recorded in its head (`schedule`); a set without one drew version 1, the sham and
# severity sweep alone, and `verify` replays every set by the plan rows it recorded. Version 2 (2026-09-30) also
# draws the catalog's extra variants at a severity a registered successor targets, so its cell holds every
# construction of the defect it claims, on the same sampled families. A plan binds the version
# (`injectionSchedule`, audio_qc_detector_calibration.py).
SCHEDULE_VERSION = 2
SCHEDULE_EXTRAS = {
    # signal.clipping@2 reads sign-symmetric flat tops, whatever the knee: hard, soft-knee and over-range.
    "SIG-CLIP": ("soft-knee-moderate", "over-range-moderate"),
    # boundary.run-on@2 reads speech-level audio after the script's aligned end, whatever it says.
    "BND-RUNON": ("reversed-moderate",),
}
# Extra variants of a targeted severity the schedule leaves out, each with the reason it is no target.
SCHEDULE_EXCLUDED = {
    "SIG-DROP": {"attenuated-ramped": "signal.dropout@2 scores exact digital silence; a span attenuated by 60 dB "
                                      "is no target (digital-silence-only)"},
    "SIG-SIL": {"leading-moderate": "signal.terminal-silence@2 scores the trailing digital silence; a leading one "
                                    "is no target"},
}
SCHEDULE_RULE = ("each in-scope injector at sham, mild, moderate and severe (its take-* recording variant where it "
                 "declares one), plus the extra catalog variants of SCHEDULE_EXTRAS (rows marked extra), all on the "
                 "injector's one sampled family set")
DEFAULT_CLASSES = ("A", "C", "F")
DEFAULT_CATALOG_SEED = 7
PI_MAX = (0.05, 0.10, 0.20)
DEFAULT_CACHE_ROOT = Path(os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE",
                                         Path(__file__).resolve().parents[1] / "build/cache/delivery-analysis"))
TAKE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The v8 report's numeric fields that measurements.json keeps (no text, no path).
FASTQC_FIELDS = (
    "rmsDBFS", "dcOffset", "peak", "clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents",
    "longestSilenceMS", "trailingSilenceMS", "stepBurstPeakCount", "stepBurstPeakStartMS", "durationSeconds",
    "expectedPauseCount", "speakingRateTextUnits", "secondsPerTextUnit", "clickEventCount",
    "lowEnergyClickEventCount", "clickEventsPerSecond",
)
OBSERVATION_MEASURES = tuple(source for source, _ in audio_qc.QC_SIGNAL_METRIC_MAP)
DONOR_SWAP_STATUS = {
    "injector": injectors.CATALOG["IDN-SWAP"].key,
    "status": "deferred",
    "reason": "a donor pair's second take is another rendering with its own timing, not the time-aligned "
              "re-render the swap splices; aligning them needs word intervals, which N3 never has, and the "
              "recorded donor splice needs speaker labels, which natural takes do not carry",
}
COHORT_SWAP_STATUS = {
    "injector": injectors.CATALOG["IDN-SWAP"].key,
    "status": "not-applicable",
    "reason": "an identity swap splices a time-aligned re-render of the same script by a second voice, which a "
              "human recording cannot give, or a speaker-labelled donor recording, and no take of this cohort "
              "names its speaker and gender",
}
LABELLED_SWAP_STATUS = {
    "injector": injectors.CATALOG["IDN-SWAP"].key,
    "status": "donor-splice",
    "reason": "speaker-labelled takes: the take-* variants splice a donor recording of the same cohort at aligned "
              "word boundaries (speakerDonors)",
}
# Why a language swap cannot be built from a manifest of this kind (None: it can).
LANGUAGE_SWAP_ISSUES = {
    TAKES_KIND: "natural takes read the CC0 script pool, not FLoRes parallel sentences",
    N1_KIND: "N1 recordings are 16 kHz and a swap presents the donor's audio as it is; build swaps on the N2 cohort",
    N2_KIND: None,
}
# Why an impostor cannot be built from a manifest of this kind (None: it can, given speaker labels).
IMPOSTOR_ISSUES = {
    TAKES_KIND: "natural takes carry no speaker label (speaker and gender)",
    N1_KIND: "N1 recordings are 16 kHz and an impostor presents the donor's audio as it is; build impostors on the "
             "N2 cohort",
    N2_KIND: None,
}
NO_LABELLED_TAKES = "no take of this manifest names its speaker and gender"
# The take policy whose speakerGenders (and any brief's declared gender) give a generated take's voice its gender.
TAKE_POLICY = Path(__file__).resolve().parent.parent / "config" / "audio-qc-calibration-takes.json"
# How an entry's longForm block describes its output (a set that records this rule has verify check each block).
LONG_FORM_ENTRY_RULE = ("an entry whose output keeps one seam per seam of its source take's longForm block (where "
                        "they were, or moved by the construction) records the block of its output: its frame count, "
                        "its seams and the largest PCM16 step at them; any other entry keeps its source's block")


class CalibrationError(ValueError):
    """An input is malformed or does not match what it claims."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def file_sha256(path: Path) -> str:
    return recordings.file_sha256(path)


def _plain(value: Any) -> Any:
    """JSON-safe: NumPy scalars to Python, non-finite floats to None."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

def _relative_path(base: Path, value: Any, what: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise CalibrationError(f"{what} must be a relative path inside its manifest's directory")
    return base / value


def load_takes(path: Path) -> tuple[dict, str]:
    """The takes manifest and the SHA-256 of its bytes, validated."""
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationError(f"{path.name} is not JSON: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("kind") not in TAKES_KINDS or manifest.get("schemaVersion") != 1:
        raise CalibrationError(f"{path.name} is not an {' or '.join(TAKES_KINDS)} schema 1 manifest")
    n1 = manifest["kind"] == N1_KIND
    n2 = manifest["kind"] == N2_KIND
    if n1 and (issues := audio_qc_n1_corpus.manifest_digest_issues(manifest)):
        raise CalibrationError(f"{path.name}: {issues[0]}")
    if n2 and (issues := audio_qc_n2_resynthesis.manifest_digest_issues(manifest)):
        raise CalibrationError(f"{path.name}: {issues[0]}")
    takes = manifest.get("takes")
    if not isinstance(takes, list):
        raise CalibrationError(f"{path.name} lists no takes")
    seen: set[str] = set()
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or not TAKE_ID.fullmatch(take_id) or take_id in seen:
            raise CalibrationError("every take has a unique takeID of letters, digits, '.', '_' and '-'")
        seen.add(take_id)
        if n2:
            # An N2 manifest lists only completed round trips: each take is an eligible, generated 24 kHz file.
            if take.get("population") != "N2" or take.get("eligible") is not True or "recording" in take:
                raise CalibrationError(f"{take_id}: an N2 take is an eligible population N2 resynthesis")
            take.setdefault("status", "generated")
        if take.get("status") not in TAKE_STATUSES:
            raise CalibrationError(f"{take_id}: status is one of {', '.join(TAKE_STATUSES)}")
        if not isinstance(take.get("family"), str) or not take["family"]:
            raise CalibrationError(f"{take_id}: it names its source family")
        if take["status"] == "rejected":
            flags = (take.get("rejection") or {}).get("audioQCFlags")
            if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
                raise CalibrationError(f"{take_id}: a rejected take names the Fast QC flags that refused it")
        if take["status"] != "generated":
            continue
        if not SHA256.fullmatch(str(take.get("wavSHA256", ""))):
            raise CalibrationError(f"{take_id}: a generated take pins its WAV's SHA-256")
        if not isinstance(take.get("language"), str) or not isinstance(take.get("text"), str):
            raise CalibrationError(f"{take_id}: a generated take names its language and text")
        _relative_path(path.parent, take.get("wavPath"), f"{take_id}: wavPath")
        for seams in (take.get("seamSamples"), take_seams(take)):
            if seams is not None and (not isinstance(seams, list) or not all(type(seam) is int and seam > 0
                                                                             for seam in seams)
                                      or any(later <= earlier for earlier, later in zip(seams, seams[1:]))):
                raise CalibrationError(f"{take_id}: seamSamples (or a longForm block's seamFrames) are increasing "
                                       "positive sample offsets")
        if n1:
            recording = take.get("recording")
            if take.get("population") != "N1" or not isinstance(take.get("eligible"), bool) \
                    or not isinstance(recording, dict) or type(recording.get("sampleRate")) is not int \
                    or recording["sampleRate"] not in recordings.SOURCE_RATES:
                raise CalibrationError(f"{take_id}: an N1 recording names its population, eligibility and "
                                       "source sample rate")
    return manifest, hashlib.sha256(raw).hexdigest()


def take_seams(take: dict) -> list:
    """A long-form take's seam offsets (samples at the engine rate on its own timeline): the `seamSamples` it
    declares, else the `seamFrames` of its `longForm` block, where the take plan's long-form cell records the
    assembly (`audio_qc_calibration_takes.long_form_block`); none for a single-segment take."""
    if take.get("seamSamples") is not None:
        return take["seamSamples"]
    block = take.get("longForm")
    if isinstance(block, dict) and block.get("sampleRate") == recordings.ENGINE_SAMPLE_RATE:
        return block.get("seamFrames") or []
    return []


def source_rate(take: dict) -> int:
    """The sample rate of a take's WAV: an N1 recording declares its own; an engine take is 24 kHz."""
    recording = take.get("recording")
    if isinstance(recording, dict) and "sampleRate" in recording:
        return int(recording["sampleRate"])
    return recordings.ENGINE_SAMPLE_RATE


def rejected_takes(manifest: dict) -> list[dict]:
    """Takes the engine's mandatory Fast QC refused: no audio, but the fielded
    detector's fail on a natural take, so the N3 rates count them."""
    return [take for take in manifest["takes"] if take["status"] == "rejected"]


def rejection_levels(flags: Iterable[str]) -> dict[str, str]:
    """The v8 level of each flag family a rejection names.

    The engine records the flags without their levels. A rejection is a fail,
    and a family that can raise only one level raised that one; a family that
    can raise warn or fail raised fail when it is the only such family and no
    fail-only family fired (then it alone caused the fail), else it counts as
    warn, so a fail-level rate never overcounts.
    """
    families = [audio_qc.flag_family(flag) for flag in flags]
    families = [family for family in dict.fromkeys(families) if family in audio_qc.FASTQC_V8_FLAGS]
    levels = {family: audio_qc.FASTQC_V8_FLAGS[family][0] for family in families
              if len(audio_qc.FASTQC_V8_FLAGS[family]) == 1}
    either = [family for family in families if len(audio_qc.FASTQC_V8_FLAGS[family]) > 1]
    sole_cause = len(either) == 1 and "fail" not in levels.values()
    for family in either:
        levels[family] = "fail" if sole_cause else "warn"
    return dict(sorted(levels.items()))


def generated_takes(manifest: dict) -> list[dict]:
    """Takes with audio that may be sources: an N1 recording its manifest marks ineligible is not one."""
    return [take for take in manifest["takes"] if take["status"] == "generated" and take.get("eligible", True)]


def ineligible_takes(manifest: dict) -> list[dict]:
    return [take for take in manifest["takes"] if take["status"] == "generated" and not take.get("eligible", True)]


def take_wav(manifest_path: Path, take: dict) -> Path:
    return _relative_path(manifest_path.parent, take["wavPath"], f"{take['takeID']}: wavPath")


def donor_pairs(manifest: dict) -> int:
    """Scripts rendered by two or more voices: the donor pairs an identity swap would use."""
    voices: dict[str, set[str]] = {}
    for take in generated_takes(manifest):
        voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
        voices.setdefault(str(take.get("scriptID")), set()).add(f"{voice.get('kind')}:{voice.get('id')}")
    return sum(1 for names in voices.values() if len(names) >= 2)


def derive_seed(source_wav_sha256: str, injector_key: str, catalog_seed: int) -> int:
    """The per-(take, injector) seed: 48 bits of SHA-256 over the source digest, injector and catalog seed.

    The variant is deliberately not an input: `injectors.inject` keys its stream
    by (seed, injector, source), so a sham draws the same positions as its
    positives only when they share the seed.
    """
    material = "|".join((SEED_SCHEMA, source_wav_sha256, injector_key, str(catalog_seed))).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:6], "big")


def stratum(take: dict) -> str:
    if take.get("population") in ("N1", "N2"):
        return f"{take['population']}/{take.get('language')}"
    return f"N3/{take.get('language')}/{take.get('mode')}"


def population_of(manifest: dict) -> str:
    return POPULATIONS[manifest["kind"]]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def voice_label(take: dict) -> dict:
    """Builtin voices by id; any other voice by a digest of its id (it may be a person's name)."""
    voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
    kind = str(voice.get("kind"))
    identity = str(voice.get("id"))
    if kind == "builtin":
        return {"kind": kind, "id": identity}
    return {"kind": kind, "idSHA256": hashlib.sha256(identity.encode("utf-8")).hexdigest()}


def voice_genders(path: Path | None = None) -> dict[str, dict[str, str]]:
    """The genders the take policy (`TAKE_POLICY` by default) records: each Built-in speaker's (`speakerGenders`)
    and each Voice Design brief's that declares one (`designBriefs.<id>.gender`; none does in policy version 2)."""
    policy = json.loads((path or TAKE_POLICY).read_text(encoding="utf-8"))
    speakers = policy.get("speakerGenders") if isinstance(policy.get("speakerGenders"), dict) else {}
    briefs = policy.get("designBriefs") if isinstance(policy.get("designBriefs"), dict) else {}
    return {"speakers": {str(speaker): gender for speaker, gender in sorted(speakers.items())
                         if gender in speaker_donors.VOICE_GENDERS},
            "briefs": {str(brief_id): brief["gender"] for brief_id, brief in sorted(briefs.items())
                       if isinstance(brief, dict) and brief.get("gender") in speaker_donors.VOICE_GENDERS}}


def voice_labels(takes: Iterable[dict], genders: dict[str, dict[str, str]]) -> dict[str, dict | None]:
    """takeID -> the take's voice as its speaker label (`speaker_donors.voice_label`), or None."""
    return {take["takeID"]: speaker_donors.voice_label(take, speaker_genders=genders["speakers"],
                                                       brief_genders=genders["briefs"]) for take in takes}


def voice_table(labels: dict[str, dict | None]) -> list[dict]:
    """The distinct voices a manifest's takes were labelled with, each with the gender it was drawn with."""
    distinct = {canonical_json(label["label"]): label["label"] for label in labels.values() if label is not None}
    return [distinct[key] for key in sorted(distinct)]


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #

def build_plan(classes: Iterable[str], *, words: bool = False, language_swap_issue: str | None = None,
               language_swap_rows: bool = False, seams: bool = False, impostor_issue: str | None = None,
               impostor_rows: bool = False, voice_donors: bool = False) -> list[dict]:
    """Every catalog injector at sham, mild, moderate and severe, then its `SCHEDULE_EXTRAS` variants (rows
    marked `extra`): scheduled, replaced, not applicable or out of scope.

    `words`: the sources carry the aligner's word intervals, so a catalog
    variant that needs only words (and pauses) is scheduled, and the injectors
    of `WORD_CATALOG_INJECTORS` run their catalog variants instead of their
    take-* ones. `seams`: some sources declare long-form seams. `voice_donors`:
    the sources are generated long-form takes whose voice is their speaker
    label, so an injector with `take-voice-*` variants (SEAM-VOICE) runs those
    instead of its take-* ones. `language_swap_rows`
    adds the LNG-SWAP rows (class D), refused with `language_swap_issue` when
    the manifest cannot build them; `impostor_rows` adds the IDN-IMPOSTOR rows
    (class E) the same way.
    """
    scope = sorted(set(classes))
    available = ({"words", "pauses"} if words else set()) | ({"seams"} if seams else set())
    rows = []
    for injector in injectors.CATALOG.values():
        in_scope = bool(set(injector.classes) & set(scope))
        recording = {variant.name: variant for variant in injector.recording_variants}
        for severity in SEVERITY_SWEEP:
            catalog = injector.variant(severity)
            catalog_needs = list(injectors.needs(injector.injector_id, catalog.parameters))
            chosen = (recording.get(f"take-voice-{severity}") if voice_donors else None) \
                or recording.get(f"take-{severity}")
            row = {"injector": injector.key, "injectorID": injector.injector_id, "classes": list(injector.classes),
                   "severity": severity, "catalogVariant": catalog.name, "catalogNeeds": catalog_needs}
            word_catalog = words and injector.injector_id in WORD_CATALOG_INJECTORS
            if not in_scope:
                row.update(status="out-of-scope", variant=None,
                           reason=f"classes {'/'.join(injector.classes)} are outside this set ({'/'.join(scope)})")
            elif chosen is not None and not word_catalog:
                row.update(status="scheduled", variant=chosen.name, parameters=dict(chosen.parameters),
                           replaces=catalog.name if catalog_needs else None)
            else:
                # A catalog variant that needs what no recording has is still attempted on every
                # take, so the refusals it raises are counted with their reason.
                row.update(status="not-applicable" if set(catalog_needs) - available else "scheduled",
                           variant=catalog.name, parameters=dict(catalog.parameters))
                if word_catalog and chosen is not None:
                    row["replacesRecordingVariant"] = chosen.name
            rows.append(row)
        for name in SCHEDULE_EXTRAS.get(injector.injector_id, ()):
            extra = injector.variant(name)
            extra_needs = list(injectors.needs(injector.injector_id, extra.parameters))
            row = {"injector": injector.key, "injectorID": injector.injector_id, "classes": list(injector.classes),
                   "severity": extra.severity, "catalogVariant": extra.name, "catalogNeeds": extra_needs,
                   "extra": True}
            if not in_scope:
                row.update(status="out-of-scope", variant=None,
                           reason=f"classes {'/'.join(injector.classes)} are outside this set ({'/'.join(scope)})")
            else:
                row.update(status="not-applicable" if set(extra_needs) - available else "scheduled",
                           variant=extra.name, parameters=dict(extra.parameters))
            rows.append(row)
    if language_swap_rows or "D" in scope:
        description = language_swap.describe()
        for variant, parameters in language_swap.VARIANTS.items():
            row = {"injector": language_swap.KEY, "injectorID": language_swap.INJECTOR_ID,
                   "classes": list(language_swap.CLASSES), "severity": variant, "catalogVariant": None,
                   "catalogNeeds": ["parallel recordings"], "mechanism": description["mechanism"]}
            if "D" not in scope:
                row.update(status="out-of-scope", variant=None,
                           reason=f"classes D are outside this set ({'/'.join(scope)})")
            elif language_swap_issue is not None:
                row.update(status="not-applicable", variant=None, reason=language_swap_issue)
            else:
                row.update(status="scheduled", variant=variant, parameters=dict(parameters))
            rows.append(row)
    if impostor_rows or "E" in scope:
        for variant, parameters in speaker_donors.IMPOSTOR_VARIANTS.items():
            row = {"injector": speaker_donors.IMPOSTOR_KEY, "injectorID": speaker_donors.IMPOSTOR_ID,
                   "classes": list(speaker_donors.CLASSES), "severity": variant, "catalogVariant": None,
                   "catalogNeeds": ["speaker donors"], "mechanism": speaker_donors.MECHANISM}
            if "E" not in scope:
                row.update(status="out-of-scope", variant=None,
                           reason=f"classes E are outside this set ({'/'.join(scope)})")
            elif impostor_issue is not None:
                row.update(status="not-applicable", variant=None, reason=impostor_issue)
            else:
                row.update(status="scheduled", variant=variant, parameters=dict(parameters))
            rows.append(row)
    return rows


def schedule(plan: list[dict]) -> list[tuple[str, str]]:
    """The T1 catalog variants to attempt on each source (language swaps and impostors are built apart)."""
    return [(row["injectorID"], row["variant"]) for row in plan
            if row["status"] != "out-of-scope" and row["injectorID"] in injectors.CATALOG]


def swaps_scheduled(plan: list[dict]) -> list[str]:
    return [row["variant"] for row in plan
            if row["injectorID"] == language_swap.INJECTOR_ID and row["status"] == "scheduled"]


def impostors_scheduled(plan: list[dict]) -> list[str]:
    return [row["variant"] for row in plan
            if row["injectorID"] == speaker_donors.IMPOSTOR_ID and row["status"] == "scheduled"]


def donor_relations(plan: list[dict], injector_id: str) -> tuple[str, ...]:
    """The donor relations the scheduled variants of a T1 splice injector need (none: it splices no donor):
    speaker relations (`speaker_donors.RELATIONS`) or voice relations (`VOICE_RELATIONS`), never both."""
    wanted = {injectors.CATALOG[injector_id].variant(variant).parameters.get("donor")
              for row_id, variant in schedule(plan) if row_id == injector_id}
    relations = tuple(relation for relation in (*speaker_donors.RELATIONS, *speaker_donors.VOICE_RELATIONS)
                      if relation in wanted)
    if set(relations) & set(speaker_donors.RELATIONS) and set(relations) & set(speaker_donors.VOICE_RELATIONS):
        raise CalibrationError(f"{injector_id}: a plan draws speaker donors or voice donors for an injector, not both")
    return relations


def voice_relations(relations: Iterable[str]) -> bool:
    """The relations are a voice donor's (`speaker_donors.VoicePool`), not a speaker donor's."""
    return bool(set(relations) & set(speaker_donors.VOICE_RELATIONS))


def splice_pool(takes: list[dict], relations: tuple[str, ...], usable_words: set[str] | None,
                labels: dict[str, dict | None] | None) -> Any:
    """The donors of a splice injector's relations: speaker-labelled takes with usable words (`usable_words`,
    None when the set has no alignments), or for voice relations the long-form takes labelled by their voice."""
    if voice_relations(relations):
        if labels is None:
            raise CalibrationError("voice donors need the takes' voice labels")
        return speaker_donors.VoicePool(takes, labels, eligible={take["takeID"] for take in takes if take_seams(take)})
    return speaker_donors.DonorPool(takes, eligible=usable_words)


def injector_classes(injector_id: str) -> tuple[str, ...]:
    if injector_id == language_swap.INJECTOR_ID:
        return language_swap.CLASSES
    if injector_id == speaker_donors.IMPOSTOR_ID:
        return speaker_donors.CLASSES
    return injectors.CATALOG[injector_id].classes


# --------------------------------------------------------------------------- #
# Word intervals (the aligner's L1 output)
# --------------------------------------------------------------------------- #

def interval_pairs(record: dict) -> list[tuple[float, float]]:
    return [(float(item["start"]), float(item["end"])) for item in record.get("intervals") or []]


def load_alignments(path: Path, manifest_sha256: str) -> tuple[dict, str]:
    """An alignments export bound to this takes manifest, and the SHA-256 of its bytes."""
    raw = path.read_bytes()
    try:
        alignments = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationError(f"{path.name} is not JSON: {error}") from error
    if not isinstance(alignments, dict) or alignments.get("kind") != ALIGNMENTS_KIND \
            or alignments.get("schemaVersion") != 1 or not isinstance(alignments.get("takes"), dict):
        raise CalibrationError(f"{path.name} is not an {ALIGNMENTS_KIND} schema 1 file")
    if (alignments.get("takesManifest") or {}).get("sha256") != manifest_sha256:
        raise CalibrationError(f"{path.name} was exported for another takes manifest")
    if json_digest(alignments["takes"]) != alignments.get("takesSHA256"):
        raise CalibrationError(f"{path.name}: its takes differ from its takesSHA256")
    for take_id, record in alignments["takes"].items():
        if not isinstance(record, dict) or record.get("status") not in ALIGNMENT_STATUSES:
            raise CalibrationError(f"{path.name}: {take_id} names no alignment status")
    return alignments, hashlib.sha256(raw).hexdigest()


def alignment_context(record: dict | None) -> dict:
    """What `_source_fixture` needs of a take's alignment: the record, or why there is none."""
    if record is None:
        return {"record": None, "status": "no alignment was exported for the take"}
    if record["status"] != "complete":
        return {"record": None, "status": f"aligner: {record['status']}"}
    return {"record": record, "status": "complete"}


def preview_alignment(take: dict, record: dict | None) -> recordings.WordAlignment | None:
    """The take's word alignment at its declared duration (the sampler's view; inject re-derives it)."""
    if record is None or record.get("status") != "complete":
        return None
    frames = int(round(float(take.get("durationSeconds") or 0.0) * recordings.ENGINE_SAMPLE_RATE))
    return recordings.word_alignment(interval_pairs(record), frames=frames)


PANEL_CACHE_GAPS = ("not-in-cache", "cache-entry-invalid")


def panel_cache(cache_root: Path) -> Any:
    """The panel run's own L1 cache; a root without analysis layers refuses.

    A pruned confirmation root, or a path that is not the panel's, would
    otherwise read every complete measurement as not-in-cache and export
    nothing without an error.
    """
    if not (Path(cache_root) / "layers").is_dir():
        raise CalibrationError(f"the cache root {Path(cache_root).name} holds no analysis layers: it was pruned or "
                               "is not the panel run's own --cache-root")
    from delivery_analysis_cache import DeliveryAnalysisCache

    return DeliveryAnalysisCache(cache_root)


def refuse_cache_gaps(records: dict[str, dict], what: str) -> None:
    """A measurement the bundle calls complete must have its L1 entry: never export around a gap."""
    gaps = Counter(record["status"] for record in records.values() if record["status"] in PANEL_CACHE_GAPS)
    if gaps:
        raise CalibrationError(f"{what}: {sum(gaps.values())} complete measurement(s) have no usable L1 entry "
                               f"({', '.join(f'{status} {count}' for status, count in sorted(gaps.items()))}); "
                               "pass the panel run's own --cache-root, or rerun the panel on a fresh root")


@contextlib.contextmanager
def shared_analysis_lock() -> Iterator[None]:
    """Hold the host analysis lock shared while an export reads a panel cache.

    Orchestrator runs hold it shared too; a generator, an exclusive analyzer or
    a confirmation-cache prune (build_cleanup.py) holds it exclusive, so a
    prune cannot remove a root mid-export and an export never starts under one.
    """
    from delivery_resource_supervisor import HOST_LOCK_NAME, host_analysis_lock_root

    root = host_analysis_lock_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / HOST_LOCK_NAME).open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CalibrationError("a generator, an exclusive analyzer or a cache prune holds the host analysis "
                                   "lock; export when it is free") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def export_alignments(takes_path: Path, bundle: Path, output: Path, *, cache_root: Path,
                      judge_id: str = ALIGNER_JUDGE, registry_path: Path | None = None) -> dict:
    """The aligner's intervals per take, from the L1 entries the orchestrator stored for a panel bundle.

    The L1 key is rebuilt as the orchestrator computed it per row
    (`layered_cache.l1_identity`): the take's original WAV and canonical
    derivative digests (the evidence records both), the judge's identity with
    its output identity as the evidence records it and its model fields from
    the registry pins (`panel_jobs.panel_identity`), and the request
    `panel_jobs.panel_request` builds from the take's language and text. The
    entry is loaded through `DeliveryAnalysisCache.load`, which verifies its
    record, identity and payload digests. Unit texts leave as SHA-256 digests.
    """
    from dataclasses import replace as replace_identity
    from types import SimpleNamespace

    from delivery_analysis_cache import AnalysisCacheError, DeliveryAnalysisCache
    from lib.jsonio import sha256_json
    from lib.qc_pipeline.evidence import BUNDLE_SCHEMA
    from lib.qc_pipeline.layered_cache import L1_LAYER, l1_identity
    from lib.qc_pipeline.panel_jobs import judge_scope, panel_identity, panel_request, profile

    manifest, manifest_sha256 = load_takes(takes_path)
    registry_path = registry_path or Path(__file__).resolve().parents[1] / "config" / "audio-qc-judges.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    judge = (registry.get("judges") or {}).get(judge_id)
    spec = profile(judge_id)
    if not isinstance(judge, dict) or spec.category != "alignment":
        raise CalibrationError(f"{judge_id} is not a registered forced aligner")
    scope = judge_scope(judge)
    # The model fields of the judge's L1 identity; each take's output identity comes from its evidence.
    model = panel_identity(judge_id, registry, {"threads": None})
    try:
        bundle_record = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationError(f"the bundle's bundle.json is unreadable ({type(error).__name__})") from error
    body = {key: value for key, value in bundle_record.items() if key != "bundleDigest"}
    if bundle_record.get("schema") != BUNDLE_SCHEMA \
            or bundle_record.get("bundleDigest") != sha256_json(body, ascii=False, allow_nan=False):
        raise CalibrationError(f"the bundle is not a {BUNDLE_SCHEMA} whose digest matches its content")
    evidence: dict[str, dict] = {}
    base = bundle.resolve()
    for entry in bundle_record.get("takes") or []:
        relative = entry.get("evidence") if isinstance(entry, dict) else None
        target = (bundle / str(relative)).resolve()
        if not isinstance(relative, str) or base not in target.parents or not target.is_file() \
                or file_sha256(target) != entry.get("evidenceSHA256"):
            raise CalibrationError(f"take {entry.get('takeID') if isinstance(entry, dict) else '?'}: its evidence "
                                   "file is missing, outside the bundle or changed")
        record = json.loads(target.read_text(encoding="utf-8"))
        evidence[str((record.get("take") or {}).get("takeID"))] = record
    cache = panel_cache(cache_root)
    takes: dict[str, dict] = {}
    identities: set[str] = set()
    for take in generated_takes(manifest):
        take_id, text = take["takeID"], take["text"]
        record = evidence.get(take_id)
        base_record = {"language": take["language"], "audioSHA256": take["wavSHA256"]}
        if record is None:
            takes[take_id] = {**base_record, "status": "no-evidence"}
            continue
        seen = record.get("take") or {}
        if seen.get("audioSHA256") != take["wavSHA256"]:
            takes[take_id] = {**base_record, "status": "audio-differs"}
            continue
        if seen.get("textSHA256") != text_sha256(text):
            takes[take_id] = {**base_record, "status": "text-differs"}
            continue
        measurement = next((item for item in record.get("measurements") or [] if item.get("judge") == judge_id), None)
        request = panel_request(spec, scope, {"language": take["language"], "referenceText": text,
                                              "scriptSHA256": text_sha256(text)})
        if measurement is None:
            takes[take_id] = {**base_record, "status": "out-of-scope" if request is None else "not-run"}
            continue
        if measurement.get("status") != "complete" or request is None:
            status = measurement.get("status") if measurement.get("status") in ALIGNMENT_STATUSES else "unavailable"
            takes[take_id] = {**base_record, "status": "out-of-scope" if request is None else status,
                              "reasons": [str(reason) for reason in measurement.get("reasons") or []]}
            continue
        identity = replace_identity(model, output_identity=measurement["outputIdentity"])
        canonical = SimpleNamespace(original_wav_sha256=seen["audioSHA256"],
                                    canonical_derivative_sha256=seen["canonicalPCMSHA256"])
        key = l1_identity(canonical, identity, request)
        try:
            payload = cache.load(key)
        except AnalysisCacheError:
            takes[take_id] = {**base_record, "status": "cache-entry-invalid"}
            continue
        if payload is None:
            takes[take_id] = {**base_record, "status": "not-in-cache", "l1Key": key.key}
            continue
        units = [str(unit) for unit in payload.get("units") or []]
        identities.add(identity.output_identity)
        takes[take_id] = {
            **base_record, "status": "complete", "canonicalPCMSHA256": seen["canonicalPCMSHA256"],
            "outputIdentity": identity.output_identity, "l1Key": key.key,
            "units": len(units), "unitsSHA256": json_digest(units),
            "intervals": [{"start": float(item["start"]), "end": float(item["end"]),
                           "unitSHA256": text_sha256(str(item.get("unit", "")))}
                          for item in payload.get("intervals") or []],
        }
    refuse_cache_gaps(takes, "alignments")
    statuses = Counter(record["status"] for record in takes.values())
    issues = Counter()
    for take in generated_takes(manifest):
        preview = preview_alignment(take, takes.get(take["takeID"]))
        if preview is not None:
            issues[preview.issue or "usable"] += 1
    export = {
        "schemaVersion": 1, "kind": ALIGNMENTS_KIND, "generator": GENERATOR,
        "privacy": "intervals in seconds and each unit's text as a SHA-256 only: no text, transcript or path",
        "takesManifest": {"sha256": manifest_sha256, "kind": manifest["kind"], "runID": manifest.get("runID")},
        "bundle": {"bundleDigest": bundle_record.get("bundleDigest"), "runID": bundle_record.get("runID"),
                   "manifestSHA256": bundle_record.get("manifestSHA256")},
        "aligner": {"judge": judge_id, "layer": f"{L1_LAYER}:{judge_id}", "modelID": model.model_id,
                    "modelRevision": model.model_revision, "weightsSHA256": model.weights_sha256,
                    "outputIdentities": sorted(identities),
                    "timeline": "seconds on the take's own timeline: the aligner read the take's 16 kHz canonical "
                                "derivative, which the zero-phase resampler keeps sample-aligned"},
        "wordRule": {"rule": recordings.ALIGNMENT_RULE, "pauseGapSeconds": recordings.PAUSE_GAP_SECONDS,
                     "minimumWords": recordings.MINIMUM_WORDS,
                     "maximumSqueezedFraction": recordings.MAXIMUM_SQUEEZED_FRACTION,
                     "overrunToleranceSeconds": recordings.ALIGNER_FRAME_SECONDS},
        "counts": {"takes": len(takes), "byStatus": dict(sorted(statuses.items())),
                   "wordAlignment": dict(sorted(issues.items()))},
        "takes": takes, "takesSHA256": json_digest(takes),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(export, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, output)
    return export


# --------------------------------------------------------------------------- #
# Raw outputs
# --------------------------------------------------------------------------- #

RAW_OUTPUTS_KIND = "audio-qc-raw-outputs"
# Per judge engine, the raw-output fields the detectors' reducers read (detectors.RAW_MEASURES).
RAW_OUTPUT_FIELDS = {"pyin-librosa": ("hopSeconds", "f0Hz", "voiced"), "wespeaker-onnx": ("dimension", "windows")}
RAW_OUTPUT_STATUSES = ("complete", "no-evidence", "audio-differs", "not-run", "out-of-scope", "unavailable",
                       "skipped", "not-in-cache", "cache-entry-invalid")


def _raw_output_takes(path: Path) -> tuple[dict, str, list[dict]]:
    """A cohort manifest's generated takes or an injection set's entries, with the manifest and its SHA-256."""
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationError(f"{path.name} is not JSON: {error}") from error
    if isinstance(document, dict) and document.get("kind") == SET_KIND:
        injection_set = load_set(path)
        if json_digest(injection_set["entries"]) != injection_set.get("entriesSHA256"):
            raise CalibrationError(f"{path.name}'s entries differ from its entriesSHA256")
        entries = [entry for entry in injection_set["entries"] if isinstance(entry, dict)]
        if any(not TAKE_ID.fullmatch(str(entry.get("takeID"))) or not SHA256.fullmatch(str(entry.get("wavSHA256")))
               or not isinstance(entry.get("language"), str) for entry in entries):
            raise CalibrationError(f"{path.name}: every entry names its takeID, WAV digest and language")
        return injection_set, hashlib.sha256(raw).hexdigest(), entries
    manifest, digest = load_takes(path)
    return manifest, digest, generated_takes(manifest)


def export_raw_outputs(takes_path: Path, bundle: Path, output: Path, *, judge_id: str, cache_root: Path,
                       registry_path: Path | None = None) -> dict:
    """One panel judge's raw (L1) output per take, as `detectors.score_take(..., raw=...)` reads it.

    The panel bundle keeps each judge's reduced metrics only; a `raw-output`
    detector (class F's pitch track, class J's speaker windows) reduces the raw
    output itself. As `alignments` does for the aligner, each take's L1 key is
    rebuilt from its evidence (the audio and canonical digests, the judge's
    output identity) and the request `panel_jobs.panel_request` builds, and the
    entry is loaded through the digest-verified `DeliveryAnalysisCache.load`.
    Only the fields the detectors' reducers read are kept (`RAW_OUTPUT_FIELDS`:
    pYIN's hop, F0 and voicing track; a speaker judge's 2 s window embeddings).
    `takes_path` is the manifest the panel ran over: a cohort or an injection
    set (whose entries are the positives and shams). `cache_root` is the panel's
    own (a confirmation panel's new, empty root), so every exported output is the
    one that panel computed after its plan. The export holds speaker embeddings:
    an untracked build artifact, never written inside the repository outside build/.
    """
    from dataclasses import replace as replace_identity
    from types import SimpleNamespace

    from delivery_analysis_cache import AnalysisCacheError, DeliveryAnalysisCache
    from lib.jsonio import sha256_json
    from lib.qc_pipeline.evidence import BUNDLE_SCHEMA
    from lib.qc_pipeline.layered_cache import L1_LAYER, l1_identity
    from lib.qc_pipeline.panel_jobs import PanelJobError, judge_scope, panel_identity, panel_request, profile

    repository = Path(__file__).resolve().parents[1]
    resolved = Path(output).resolve()
    if resolved.is_relative_to(repository) and not resolved.is_relative_to(repository / "build"):
        raise CalibrationError(f"{output} is inside the repository: raw outputs (speaker embeddings among them) are "
                               "untracked build artifacts; write them under build/")
    manifest, manifest_sha256, takes = _raw_output_takes(takes_path)
    registry_path = registry_path or repository / "config" / "audio-qc-judges.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    judge = (registry.get("judges") or {}).get(judge_id)
    engine = ((judge or {}).get("execution") or {}).get("engine") if isinstance(judge, dict) else None
    if engine not in RAW_OUTPUT_FIELDS:
        raise CalibrationError(f"{judge_id} is not a registered judge whose raw output a detector reduces "
                               f"({', '.join(sorted(RAW_OUTPUT_FIELDS))})")
    try:
        spec = profile(judge_id)
    except PanelJobError as error:
        raise CalibrationError(str(error)) from error
    scope = judge_scope(judge)
    model = panel_identity(judge_id, registry, {"threads": None})
    try:
        bundle_record = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationError(f"the bundle's bundle.json is unreadable ({type(error).__name__})") from error
    body = {key: value for key, value in bundle_record.items() if key != "bundleDigest"}
    if bundle_record.get("schema") != BUNDLE_SCHEMA \
            or bundle_record.get("bundleDigest") != sha256_json(body, ascii=False, allow_nan=False):
        raise CalibrationError(f"the bundle is not a {BUNDLE_SCHEMA} whose digest matches its content")
    evidence: dict[str, dict] = {}
    base = bundle.resolve()
    for entry in bundle_record.get("takes") or []:
        relative = entry.get("evidence") if isinstance(entry, dict) else None
        target = (bundle / str(relative)).resolve()
        if not isinstance(relative, str) or base not in target.parents or not target.is_file() \
                or file_sha256(target) != entry.get("evidenceSHA256"):
            raise CalibrationError(f"take {entry.get('takeID') if isinstance(entry, dict) else '?'}: its evidence "
                                   "file is missing, outside the bundle or changed")
        record = json.loads(target.read_text(encoding="utf-8"))
        evidence[str((record.get("take") or {}).get("takeID"))] = record
    cache = panel_cache(cache_root)
    exported: dict[str, dict] = {}
    identities: set[str] = set()
    for take in takes:
        take_id = take["takeID"]
        base_record = {"language": take["language"], "audioSHA256": take["wavSHA256"]}
        record = evidence.get(take_id)
        if record is None:
            exported[take_id] = {**base_record, "status": "no-evidence"}
            continue
        seen = record.get("take") or {}
        if seen.get("audioSHA256") != take["wavSHA256"]:
            exported[take_id] = {**base_record, "status": "audio-differs"}
            continue
        measurement = next((item for item in record.get("measurements") or [] if item.get("judge") == judge_id), None)
        request = panel_request(spec, scope, {"language": take["language"], "referenceText": None,
                                              "scriptSHA256": None})
        if measurement is None or request is None:
            exported[take_id] = {**base_record, "status": "out-of-scope" if request is None else "not-run"}
            continue
        if measurement.get("status") != "complete":
            status = measurement.get("status") if measurement.get("status") in RAW_OUTPUT_STATUSES else "unavailable"
            exported[take_id] = {**base_record, "status": status}
            continue
        identity = replace_identity(model, output_identity=measurement["outputIdentity"])
        canonical = SimpleNamespace(original_wav_sha256=seen["audioSHA256"],
                                    canonical_derivative_sha256=seen["canonicalPCMSHA256"])
        key = l1_identity(canonical, identity, request)
        try:
            payload = cache.load(key)
        except AnalysisCacheError:
            exported[take_id] = {**base_record, "status": "cache-entry-invalid"}
            continue
        if payload is None:
            exported[take_id] = {**base_record, "status": "not-in-cache", "l1Key": key.key}
            continue
        identities.add(identity.output_identity)
        exported[take_id] = {**base_record, "status": "complete", "canonicalPCMSHA256": seen["canonicalPCMSHA256"],
                             "outputIdentity": identity.output_identity, "l1Key": key.key,
                             "output": _plain({field: payload.get(field) for field in RAW_OUTPUT_FIELDS[engine]})}
    refuse_cache_gaps(exported, f"raw outputs of {judge_id}")
    statuses = Counter(record["status"] for record in exported.values())
    export = {
        "schemaVersion": 1, "kind": RAW_OUTPUTS_KIND, "generator": GENERATOR,
        "privacy": "raw judge outputs (a pitch track, speaker window embeddings), ids and digests: no text, "
                   "transcript or path; an untracked build artifact, never committed",
        "takesManifest": {"sha256": manifest_sha256, "kind": manifest.get("kind"), "runID": manifest.get("runID")},
        "bundle": {"bundleDigest": bundle_record.get("bundleDigest"), "runID": bundle_record.get("runID"),
                   "manifestSHA256": bundle_record.get("manifestSHA256")},
        "judge": {"judge": judge_id, "engine": engine, "layer": f"{L1_LAYER}:{judge_id}", "modelID": model.model_id,
                  "modelRevision": model.model_revision, "weightsSHA256": model.weights_sha256,
                  "outputIdentities": sorted(identities), "fields": list(RAW_OUTPUT_FIELDS[engine])},
        "counts": {"takes": len(exported), "byStatus": dict(sorted(statuses.items()))},
        "takes": exported, "takesSHA256": json_digest(exported),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(export, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, output)
    return export


# --------------------------------------------------------------------------- #
# Sampling
# --------------------------------------------------------------------------- #

def _sample_rank(seed: int, key: str, kind: str, value: str) -> str:
    return hashlib.sha256("|".join((SAMPLE_SCHEMA, str(seed), key, kind, value)).encode("utf-8")).hexdigest()


def stratified_sample(pool: dict[str, str], count: int, *, seed: int, key: str) -> list[str]:
    """`count` families of `pool` (family -> language), as even across languages as the pool allows.

    Within a language, families go in ascending seeded rank; the quotas fill
    round-robin over the languages in their own seeded order until `count` is
    reached or every language is exhausted. Deterministic in (pool, count,
    seed, key); the result is sorted.
    """
    by_language: dict[str, list[str]] = {}
    for family, language in pool.items():
        by_language.setdefault(language, []).append(family)
    for language, families in by_language.items():
        families.sort(key=lambda family: _sample_rank(seed, key, "family", family))
    order = sorted(by_language, key=lambda language: _sample_rank(seed, key, "language", language))
    quota = dict.fromkeys(order, 0)
    left = count
    while left > 0:
        progressed = False
        for language in order:
            if left and quota[language] < len(by_language[language]):
                quota[language] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return sorted(family for language in order for family in by_language[language][:quota[language]])


def build_sampling(takes: list[dict], plan: list[dict], *, per_cell: int, seed: int,
                   usable_words: set[str] | None, voice_labels: dict[str, dict | None] | None = None) -> dict:
    """One seeded, language-stratified family sample per injector, shared by its sham and every severity.

    `usable_words`: the takes whose alignment is usable, when the set has word
    intervals; a word-level injector draws only from their families. A donor
    splice draws only from sources with a donor of every relation it needs (a
    voice donor's among the takes' `voice_labels`), a seam injector only from
    sources that declare seams, and IDN-IMPOSTOR only from sources with both of
    its donors.
    """
    languages: dict[str, str] = {}
    for take in takes:
        languages.setdefault(take["family"], str(take.get("language")))
    swap_families = {take["family"] for take in language_swap.eligible_sources(takes)}
    impostor_families = {take["family"] for take in speaker_donors.DonorPool(takes).sources()}
    seamed = {take["family"] for take in takes if take_seams(take)}
    worded = None if usable_words is None else {take["family"] for take in takes if take["takeID"] in usable_words}
    chosen: dict[str, dict] = {}
    for row in plan:
        if row["status"] == "out-of-scope" or row["variant"] is None or row["injector"] in chosen:
            continue
        # An extra variant draws from the sweep's families (and is not applicable where it needs more), so the
        # pool, and each cell's sample, is the one the sweep alone would draw.
        rows = [other for other in plan if other["injector"] == row["injector"] and other["variant"] is not None
                and other["status"] != "out-of-scope" and not other.get("extra")]
        if row["injectorID"] == language_swap.INJECTOR_ID:
            needs = ["parallel recordings"]
            pool = {family: language for family, language in languages.items() if family in swap_families}
        elif row["injectorID"] == speaker_donors.IMPOSTOR_ID:
            needs = ["speaker donors"]
            pool = {family: language for family, language in languages.items() if family in impostor_families}
        else:
            needs = sorted({need for other in rows for need in injectors.needs(
                other["injectorID"], injectors.CATALOG[other["injectorID"]].variant(other["variant"]).parameters)})
            pool = dict(languages)
            if "words" in needs and worded is not None:
                pool = {family: language for family, language in pool.items() if family in worded}
            if "seams" in needs:
                pool = {family: language for family, language in pool.items() if family in seamed}
            if injectors.DONOR_NEEDS & set(needs):
                relations = donor_relations(plan, row["injectorID"])
                donors = splice_pool(takes, relations, usable_words if "words" in needs else None, voice_labels)
                served = {take["family"] for take in donors.sources(relations)}
                pool = {family: language for family, language in pool.items() if family in served}
        families = stratified_sample(pool, per_cell, seed=seed, key=row["injector"])
        chosen[row["injector"]] = {
            "needs": needs, "eligible": dict(sorted(Counter(pool.values()).items())),
            "chosen": dict(sorted(Counter(pool[family] for family in families).items())),
            "families": families, "familiesSHA256": json_digest(families),
        }
    return {
        "schema": SAMPLE_SCHEMA, "perCell": per_cell, "seed": seed, "unit": "source family", "stratum": "language",
        "rank": f"within each language, ascending SHA-256('{SAMPLE_SCHEMA}|<seed>|<injector>|family|<family>'); "
                f"quotas fill round-robin over the languages in ascending SHA-256('{SAMPLE_SCHEMA}|<seed>|<injector>|"
                "language|<language>') until perCell families or the eligible pool runs out",
        "shared": "one sample per injector: its sham and every severity use the same families, so each (injector, "
                  "severity) cell and its sham hold the same families (for LNG-SWAP and IDN-IMPOSTOR, the same "
                  "source families; each clip's family is its donor audio's)",
        "injectors": chosen,
    }


def recording_variants_description() -> list[dict]:
    return [{"injector": injector.key, "variants": [
        {"name": variant.name, "severity": variant.severity, "parameters": dict(variant.parameters)}
        for variant in injector.recording_variants]}
        for injector in injectors.CATALOG.values() if injector.recording_variants]


def _reason(error: Exception, fixture_id: str, key: str, variant: str) -> str:
    """A refusal without the take's id or the variant, so reasons aggregate across takes and variants."""
    return (str(error).replace(f"{fixture_id}: ", "").replace(f"{key} {variant} ", "")
            .replace(fixture_id, "the take"))


# --------------------------------------------------------------------------- #
# Parallel map with progress
# --------------------------------------------------------------------------- #

def parallel(function: Callable[[Any], Any], tasks: list[Any], jobs: int, label: str) -> Iterator[Any]:
    """Results in task order (deterministic for any job count), with progress on stderr."""
    total = len(tasks)
    started = time.monotonic()
    step = max(1, total // 20)

    def progress(done: int) -> None:
        if done % step and done != total:
            return
        elapsed = time.monotonic() - started
        left = elapsed / done * (total - done) if done else 0.0
        log(f"{label}: {done}/{total} ({elapsed:.0f} s elapsed, about {left:.0f} s left)")

    if jobs <= 1 or total <= 1:
        for done, task in enumerate(tasks, 1):
            yield function(task)
            progress(done)
        return
    with get_context().Pool(min(jobs, total)) as pool:
        for done, result in enumerate(pool.imap(function, tasks, chunksize=1), 1):
            yield result
            progress(done)


# --------------------------------------------------------------------------- #
# inject
# --------------------------------------------------------------------------- #

def output_long_form(take: dict, samples: np.ndarray, seams: Iterable[int]) -> dict | None:
    """The `longForm` block an entry built from `take` records for its output (`LONG_FORM_ENTRY_RULE`).

    When the output keeps one seam per seam of the take's block (moved by
    SEAM-DISC or a whole-segment SEAM-VOICE splice, or where they were), the
    block of the output: its frame count, its seams and the largest step its
    PCM16 takes at them, as `score` measures it on the clip. Otherwise the
    take's block as it is (no seam mapping follows the edit, and `score`
    describes no block for it); None without a block, and the take's block
    when its seams are its own `seamSamples`, not its block's.
    """
    block = take.get("longForm")
    if not isinstance(block, dict) or take.get("seamSamples") is not None:
        return block
    seams = [int(seam) for seam in seams]
    recorded = block.get("seamFrames")
    if block.get("sampleRate") != recordings.ENGINE_SAMPLE_RATE or not isinstance(recorded, list) \
            or not seams or len(seams) != len(recorded):
        return block
    pcm = to_pcm16(samples).astype(np.float64) / recordings.PCM16_FULL_SCALE
    return {**block, "outputFrameCount": int(samples.size), "seamFrames": seams,
            "maximumSegmentBoundaryJump": boundary_jump(pcm, seams)}


def _entry(take: dict, injection: injectors.Injection, clip_id: str, wav_path: str, wav_sha256: str,
           source_wav_sha256: str, rate: int, source_resampling: dict | None = None, *, embed_text: bool = False,
           source_alignment: dict | None = None, donor: dict | None = None,
           source_seams: tuple[int, ...] = ()) -> dict:
    injector = injectors.CATALOG[injection.injector.split("@")[0]]
    # The source's seams stay behind: the entry carries its own output's (none where the edit moved them).
    entry = {key: value for key, value in take.items() if key not in ("text", "seamSamples")}
    block = output_long_form(take, injection.samples, injection.seams)
    if block is not None:
        entry["longForm"] = block
    entry.update(
        takeID=clip_id, sourceTakeID=take["takeID"], family=take["family"], status="generated",
        wavPath=wav_path, wavSHA256=wav_sha256, durationSeconds=round(injection.samples.size / rate, 6),
        textSHA256=hashlib.sha256(take["text"].encode("utf-8")).hexdigest(),
    )
    if injection.seams:
        entry["seamSamples"] = list(injection.seams)
    if embed_text:
        entry["text"] = take["text"]
    entry["injection"] = {
        "mechanism": injectors.MECHANISM, "catalogVersion": injectors.CATALOG_VERSION,
        "injector": injection.injector, "injectorID": injector.injector_id, "injectorVersion": injector.version,
        "classes": list(injector.classes), "variant": injection.variant, "severity": injection.severity,
        "population": "P1" if injection.positive else "S", "parameters": injection.parameters,
        "seed": injection.seed, "sourceWAVSHA256": source_wav_sha256, "sourcePCMSHA256": injection.source_digest,
        "outputPCMSHA256": injection.digest, "labels": list(injection.labels),
    }
    if source_resampling is not None:
        # The source reached the engine rate through this resampler; sourcePCMSHA256 is the resampled PCM's.
        entry["injection"]["sourceResampling"] = source_resampling
    if source_alignment is not None:
        # The source carried the aligner's word and pause intervals (`recordings.word_alignment`).
        entry["injection"]["sourceAlignment"] = source_alignment
    if source_seams:
        # The source's long-form seams, which a seam injector draws from.
        entry["injection"]["sourceSeams"] = list(source_seams)
    if donor is not None:
        # The donor recording a splice drew its words from (`speaker_donors`).
        entry["injection"]["donor"] = donor
    return _plain(entry)


def _swap_entry(take: dict, donor: dict, variant: str, clip_id: str, wav_path: str, wav_sha256: str,
                samples: np.ndarray, source_pcm_sha256: str, seed: int, *, embed_text: bool) -> dict:
    """A language swap: the donor's audio and identity, presented with the source's language and text."""
    entry = {key: value for key, value in donor.items() if key != "text"}
    entry.update(
        takeID=clip_id, sourceTakeID=take["takeID"], family=donor["family"], language=take["language"],
        status="generated", wavPath=wav_path, wavSHA256=wav_sha256,
        durationSeconds=round(samples.size / recordings.ENGINE_SAMPLE_RATE, 6), textSHA256=text_sha256(take["text"]),
    )
    if embed_text:
        entry["text"] = take["text"]
    entry["injection"] = language_swap.injection(
        variant=variant, source=take, donor=donor, seed=seed, source_pcm_sha256=source_pcm_sha256,
        output_pcm_sha256=pcm_digest(samples), frames=int(samples.size))
    return _plain(entry)


def _impostor_entry(take: dict, donor: dict, variant: str, clip_id: str, wav_path: str, wav_sha256: str,
                    samples: np.ndarray, source_pcm_sha256: str, seed: int, *, embed_text: bool) -> dict:
    """An impostor: the donor's audio and its own text, presented as the source speaker (`speaker`)."""
    entry = {key: value for key, value in donor.items() if key != "text"}
    entry.update(
        takeID=clip_id, sourceTakeID=take["takeID"], family=donor["family"], speaker=take["speaker"],
        gender=take["gender"], language=take["language"], status="generated", wavPath=wav_path,
        wavSHA256=wav_sha256, durationSeconds=round(samples.size / recordings.ENGINE_SAMPLE_RATE, 6),
        textSHA256=text_sha256(donor["text"]),
    )
    if embed_text:
        entry["text"] = donor["text"]
    entry["injection"] = speaker_donors.impostor_injection(
        variant=variant, source=take, donor=donor, seed=seed, source_pcm_sha256=source_pcm_sha256,
        output_pcm_sha256=pcm_digest(samples), frames=int(samples.size))
    return _plain(entry)


def presented_text(entry: dict, takes: dict[str, dict]) -> str:
    """The text an entry is presented with: the source take's, or for an impostor the donor's own."""
    injection = entry.get("injection") or {}
    if injection.get("injectorID") == speaker_donors.IMPOSTOR_ID:
        return takes[str(injection.get("donorTakeID"))]["text"]
    return takes[entry["sourceTakeID"]]["text"]


def _source_fixture(task: dict) -> tuple[Any, str, dict | None, str | None]:
    """The take as an injector source: its fixture, WAV digest, word alignment (if usable) and why not."""
    take = task["take"]
    fixture, digest = recordings.load_recording(Path(task["wav"]), take_id=take["takeID"], family=take["family"],
                                                stratum=stratum(take), text=take["text"],
                                                expected_sha256=take["wavSHA256"], source_rate=source_rate(take),
                                                seams=take_seams(take))
    context = task.get("alignment")
    if context is None:
        return fixture, digest, None, None
    record = context["record"]
    if record is None:
        return fixture, digest, None, context["status"]
    alignment = recordings.word_alignment(interval_pairs(record), frames=fixture.samples.size)
    if not alignment.usable:
        return fixture, digest, None, f"alignment refused: {alignment.issue}"
    description = {**alignment.describe(), "recordSHA256": json_digest(record)}
    return recordings.with_alignment(fixture, alignment), digest, description, None


def _needs_words(injector_id: str, variant: str) -> bool:
    return "words" in injectors.needs(injector_id, injectors.CATALOG[injector_id].variant(variant).parameters)


def donor_block(item: dict, relation: str, fixture: Any, digest: str, alignment: dict | None) -> dict:
    """The donor a splice entry records: a speaker donor's speaker and alignment, or a voice donor's voice
    label and the seams its audio was drawn at."""
    take = item["take"]
    if relation in speaker_donors.VOICE_RELATIONS:
        return {"takeID": take["takeID"], "family": take["family"], "voice": item.get("voice"), "relation": relation,
                "wavSHA256": digest, "pcmSHA256": fixture.digest, "seamSamples": list(fixture.seams)}
    return {"takeID": take["takeID"], "family": take["family"], "speaker": take.get("speaker"),
            "relation": relation, "wavSHA256": digest, "pcmSHA256": fixture.digest, "alignment": alignment}


class _Donors:
    """A task's chosen splice donors, each loaded once (with its usable word intervals)."""

    def __init__(self, task: dict) -> None:
        self.chosen = task.get("donors") or {}
        self.issues = task.get("donorIssues") or {}
        self.loaded: dict[str, tuple] = {}

    def get(self, injector_id: str, relation: str) -> tuple[Any, dict | None, str | None]:
        """(fixture, recipe block, None), or (None, None, why there is no donor)."""
        item = (self.chosen.get(injector_id) or {}).get(relation)
        if item is None:
            return None, None, self.issues.get(injector_id) or "no donor was chosen for this take"
        take = item["take"]
        if take["takeID"] not in self.loaded:
            self.loaded[take["takeID"]] = _source_fixture(item)
        fixture, digest, alignment, _status = self.loaded[take["takeID"]]
        return fixture, donor_block(item, relation, fixture, digest, alignment), None


def _inject_take(task: dict) -> dict:
    take = task["take"]
    rate = source_rate(take)
    fixture, digest, source_alignment, word_status = _source_fixture(task)
    source_resampling = recordings.resampling_recipe(rate)
    output = Path(task["output"])
    embed_text = bool(task.get("embedText"))
    donors = _Donors(task)
    entries, skips = [], []
    written = 0
    for injector_id, variant in task["schedule"]:
        key = injectors.CATALOG[injector_id].key
        seed = derive_seed(digest, key, task["catalogSeed"])
        relation = injectors.CATALOG[injector_id].variant(variant).parameters.get("donor")
        donor, donor_record, donor_issue = donors.get(injector_id, relation) if relation else (None, None, None)
        try:
            injection = injectors.inject(injector_id, variant, fixture, seed, donor=donor)
        except injectors.InjectorNotApplicable as error:
            reason = _reason(error, fixture.fixture_id, key, variant)
            if word_status is not None and _needs_words(injector_id, variant):
                reason = f"{reason} ({word_status})"
            if donor_issue is not None:
                reason = f"{reason} ({donor_issue})"
            skips.append([key, variant, reason])
            continue
        clip_id = f"{take['takeID']}__{injector_id}__{variant}"
        relative = f"wav/{clip_id}.wav"
        wav_sha256 = recordings.write_pcm16_wav(output / relative, injection.samples,
                                                sample_rate=fixture.sample_rate)
        written += (output / relative).stat().st_size
        entries.append(_entry(take, injection, clip_id, relative, wav_sha256, digest, fixture.sample_rate,
                              source_resampling, embed_text=embed_text, source_alignment=source_alignment,
                              donor=donor_record, source_seams=fixture.seams))
    for swap in task.get("languageSwap") or ():
        donor, variant = swap["donor"], swap["variant"]
        donor_wav = Path(swap["wav"])
        if not donor_wav.is_file() or file_sha256(donor_wav) != donor["wavSHA256"]:
            raise recordings.RecordingError(f"{donor['takeID']}: its WAV is missing or differs from the manifest")
        clip_id = f"{take['takeID']}__{language_swap.INJECTOR_ID}__{variant}"
        relative = f"wav/{clip_id}.wav"
        language_swap.copy_as_is(donor_wav, output / relative)
        samples = recordings.read_pcm16_wav(output / relative)
        written += (output / relative).stat().st_size
        entries.append(_swap_entry(take, donor, variant, clip_id, relative, file_sha256(output / relative), samples,
                                   fixture.digest, task["sampleSeed"], embed_text=embed_text))
    for impostor in task.get("impostor") or ():
        donor, variant = impostor["donor"], impostor["variant"]
        donor_wav = Path(impostor["wav"])
        if not donor_wav.is_file() or file_sha256(donor_wav) != donor["wavSHA256"]:
            raise recordings.RecordingError(f"{donor['takeID']}: its WAV is missing or differs from the manifest")
        clip_id = f"{take['takeID']}__{speaker_donors.IMPOSTOR_ID}__{variant}"
        relative = f"wav/{clip_id}.wav"
        language_swap.copy_as_is(donor_wav, output / relative)
        samples = recordings.read_pcm16_wav(output / relative)
        written += (output / relative).stat().st_size
        entries.append(_impostor_entry(take, donor, variant, clip_id, relative, file_sha256(output / relative),
                                       samples, fixture.digest, task["sampleSeed"], embed_text=embed_text))
    return {"takeID": take["takeID"], "entries": [_with_reference(entry, task) for entry in entries], "skips": skips,
            "bytes": written}


def _with_reference(entry: dict, task: dict) -> dict:
    """The reference clip a speaker judge scores an entry against, its path relative to the set: an impostor's
    is its source take (the speaker it is presented as); any other entry keeps the one its audio's take declares
    (a relative path there is relative to the cohort manifest)."""
    output = Path(task["output"]).resolve()
    if (entry.get("injection") or {}).get("injectorID") == speaker_donors.IMPOSTOR_ID:
        take = task["take"]
        return {**entry, "reference": {"takeID": take["takeID"], "wavSHA256": take["wavSHA256"],
                                       "wavPath": os.path.relpath(Path(task["wav"]).resolve(), output)}}
    reference = entry.get("reference")
    if not isinstance(reference, dict) or not isinstance(reference.get("wavPath"), str) or "manifestDir" not in task:
        return entry
    path = Path(reference["wavPath"])
    path = path if path.is_absolute() else Path(task["manifestDir"]) / path
    return {**entry, "reference": {**reference, "wavPath": os.path.relpath(path.resolve(), output)}}


def _write_streamed(path: Path, head: dict, key: str, items: Iterable[dict], tail: Callable[[str], dict]) -> str:
    """Write {head..., key: [items...], tail...} with one item per line; returns the items' json_digest.

    `canonical_json` of a list is "[" + ",".join(item encodings) + "]", so the
    digest is taken while streaming, never holding every item in memory.
    """
    digest = hashlib.sha256(b"[")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _stream_json(temporary, head, key, items, tail, digest)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    return digest.hexdigest()


def _stream_json(temporary: Path, head: dict, key: str, items: Iterable[dict], tail: Callable[[str], dict],
                 digest: Any) -> None:
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write("{\n")
        for name, value in sorted(head.items()):
            stream.write(f"  {json.dumps(name)}: {json.dumps(value, sort_keys=True, allow_nan=False)},\n")
        stream.write(f"  {json.dumps(key)}: [")
        first = True
        for item in items:
            digest.update(b"" if first else b",")
            digest.update(canonical_json(item))
            stream.write(("\n    " if first else ",\n    ") + json.dumps(item, sort_keys=True, allow_nan=False))
            first = False
        stream.write("\n  ],\n" if not first else "],\n")
        digest.update(b"]")
        closing = tail(digest.hexdigest())
        body = [f"  {json.dumps(name)}: {json.dumps(value, sort_keys=True, allow_nan=False)}"
                for name, value in sorted(closing.items())]
        stream.write(",\n".join(body) + "\n}\n")


def default_classes(manifest: dict) -> tuple[str, ...]:
    return DEFAULT_N2_CLASSES if manifest["kind"] == N2_KIND else DEFAULT_CLASSES


def impostor_issue(manifest: dict) -> str | None:
    """Why an impostor cannot be built from this manifest (None: it can)."""
    issue = IMPOSTOR_ISSUES[manifest["kind"]]
    if issue is None and not any(speaker_donors.labelled(take) for take in generated_takes(manifest)):
        return NO_LABELLED_TAKES
    return issue


def plan_for(manifest: dict, classes: Iterable[str], *, words: bool) -> list[dict]:
    cohort = manifest["kind"] in COHORT_KINDS
    seams = any(take_seams(take) for take in generated_takes(manifest))
    # Natural takes with long-form seams: the voice each was generated with is its speaker label.
    return build_plan(classes, words=words, language_swap_issue=LANGUAGE_SWAP_ISSUES[manifest["kind"]],
                      language_swap_rows=cohort, seams=seams, impostor_issue=impostor_issue(manifest),
                      impostor_rows=cohort, voice_donors=manifest["kind"] == TAKES_KIND and seams)


def identity_swap_status(manifest: dict) -> dict:
    if manifest["kind"] not in COHORT_KINDS:
        return {**DONOR_SWAP_STATUS, "donorPairs": donor_pairs(manifest)}
    labelled = any(speaker_donors.labelled(take) for take in generated_takes(manifest))
    return dict(LABELLED_SWAP_STATUS if labelled else COHORT_SWAP_STATUS)


def _sampled(sources: list[dict], sampling: dict | None, key: str) -> list[dict]:
    if sampling is None:
        return sources
    families = set((sampling["injectors"].get(key) or {}).get("families") or ())
    return [take for take in sources if take["family"] in families]


def splice_donors(generated: list[dict], plan: list[dict], sampling: dict | None, usable_words: set[str] | None, *,
                  seed: int, voice_labels: dict[str, dict | None] | None = None) -> dict[str, dict[str, dict[str, str]]]:
    """Per donor-splice injector: source takeID -> {relation: donor takeID}, re-derivable by `verify`.

    The sources are the takes with a donor of every relation the injector's
    scheduled variants need (within its sampled families), in manifest order;
    a speaker donor must carry a usable alignment when the set has alignments,
    a voice donor (`voice_labels`) must declare seams.
    """
    chosen: dict[str, dict[str, dict[str, str]]] = {}
    for injector_id in dict.fromkeys(row_id for row_id, _ in schedule(plan)):
        relations = donor_relations(plan, injector_id)
        if not relations:
            continue
        pool = splice_pool(generated, relations, usable_words, voice_labels)
        sources = _sampled(pool.sources(relations), sampling, injectors.CATALOG[injector_id].key)
        chosen[injector_id] = pool.choose([take["takeID"] for take in sources], seed=seed,
                                          key=injectors.CATALOG[injector_id].key, relations=relations)
    return chosen


def impostor_relations(variants: Iterable[str]) -> tuple[str, ...]:
    wanted = {speaker_donors.IMPOSTOR_VARIANTS[variant]["donor"] for variant in variants}
    return tuple(relation for relation in speaker_donors.RELATIONS if relation in wanted)


def impostor_donors(generated: list[dict], plan: list[dict], sampling: dict | None, *,
                    seed: int) -> dict[str, dict[str, str]]:
    """Source takeID -> {relation: donor takeID} for the scheduled impostor variants, re-derivable by `verify`."""
    variants = impostors_scheduled(plan)
    if not variants:
        return {}
    relations = impostor_relations(variants)
    pool = speaker_donors.DonorPool(generated)
    sources = _sampled(pool.sources(relations), sampling, speaker_donors.IMPOSTOR_KEY)
    return pool.choose([take["takeID"] for take in sources], seed=seed, key=speaker_donors.IMPOSTOR_KEY,
                       relations=relations)


def _donor_item(take: dict, takes_path: Path, alignments: dict | None, voice: dict | None = None) -> dict:
    item = {"take": take, "wav": str(take_wav(takes_path, take))}
    if alignments is not None:
        item["alignment"] = alignment_context(alignments["takes"].get(take["takeID"]))
    if voice is not None:
        # A voice donor's recorded voice label (`speaker_donors.voice_label`).
        item["voice"] = voice["label"]
    return item


def needs_voice_labels(plan: list[dict]) -> bool:
    """Some scheduled splice draws voice donors."""
    return any(voice_relations(donor_relations(plan, injector_id))
               for injector_id in dict.fromkeys(row_id for row_id, _ in schedule(plan)))


def splice_items(by_id: dict[str, dict], picks: dict[str, str], takes_path: Path, alignments: dict | None,
                 labels: dict[str, dict | None] | None) -> dict[str, dict]:
    """A source's chosen donors, relation -> the item `_Donors` loads (a voice donor's with its voice label)."""
    return {relation: _donor_item(by_id[donor_id], takes_path, alignments,
                                  (labels or {}).get(donor_id) if relation in speaker_donors.VOICE_RELATIONS else None)
            for relation, donor_id in picks.items()}


def usable_word_takes(generated: list[dict], alignments: dict | None) -> set[str] | None:
    if alignments is None:
        return None
    usable = set()
    for take in generated:
        preview = preview_alignment(take, alignments["takes"].get(take["takeID"]))
        if preview is not None and preview.usable:
            usable.add(take["takeID"])
    return usable


def swap_sources(generated: list[dict], plan: list[dict], sampling: dict | None) -> list[str]:
    """The takes that receive language swaps, in manifest order (sampled when the set samples)."""
    if not swaps_scheduled(plan):
        return []
    eligible = language_swap.eligible_sources(generated)
    if sampling is not None:
        families = set((sampling["injectors"].get(language_swap.KEY) or {}).get("families") or ())
        eligible = [take for take in eligible if take["family"] in families]
    return [take["takeID"] for take in eligible]


def run_inject(takes_path: Path, output: Path, *, catalog_seed: int, classes: Iterable[str] | None, jobs: int,
               alignments_path: Path | None = None, sample_per_cell: int | None = None,
               sample_seed: int = DEFAULT_SAMPLE_SEED, embed_text: bool | None = None) -> dict:
    manifest, manifest_sha256 = load_takes(takes_path)
    population = population_of(manifest)
    classes = tuple(sorted(set(classes if classes is not None else default_classes(manifest))))
    per_cell = DEFAULT_SAMPLE_PER_CELL[population] if sample_per_cell is None else sample_per_cell
    embed = (manifest["kind"] in COHORT_KINDS) if embed_text is None else bool(embed_text)
    alignments, alignments_sha256 = (None, None)
    if alignments_path is not None:
        alignments, alignments_sha256 = load_alignments(alignments_path, manifest_sha256)
    plan = plan_for(manifest, classes, words=alignments is not None)
    scheduled = schedule(plan)
    generated = generated_takes(manifest)
    usable = usable_word_takes(generated, alignments)
    labels = voice_labels(generated, voice_genders()) if needs_voice_labels(plan) else None
    sampling = build_sampling(generated, plan, per_cell=per_cell, seed=sample_seed, usable_words=usable,
                              voice_labels=labels) if per_cell else None
    by_id = {take["takeID"]: take for take in generated}
    sources = swap_sources(generated, plan, sampling)
    donors = language_swap.choose_donors(generated, sources, seed=sample_seed)
    swap_variants = swaps_scheduled(plan)
    splices = splice_donors(generated, plan, sampling, usable, seed=sample_seed, voice_labels=labels)
    pools = {injector_id: splice_pool(generated, donor_relations(plan, injector_id), usable, labels)
             for injector_id in splices}
    impostor_variants = impostors_scheduled(plan)
    impostors = impostor_donors(generated, plan, sampling, seed=sample_seed)
    chosen = {key: set(value["families"]) for key, value in (sampling or {}).get("injectors", {}).items()}
    tasks = []
    for take in generated:
        task = {"take": take, "wav": str(take_wav(takes_path, take)), "output": str(output),
                "manifestDir": str(takes_path.parent), "schedule": scheduled, "catalogSeed": catalog_seed}
        if sampling is not None:
            task["schedule"] = [(injector_id, variant) for injector_id, variant in scheduled
                                if take["family"] in chosen[injectors.CATALOG[injector_id].key]]
        if alignments is not None:
            task["alignment"] = alignment_context(alignments["takes"].get(take["takeID"]))
        if embed:
            task["embedText"] = True
        if take["takeID"] in donors:
            task["sampleSeed"] = sample_seed
            task["languageSwap"] = [{"variant": variant, "donor": by_id[donors[take["takeID"]][variant]],
                                     "wav": str(take_wav(takes_path, by_id[donors[take["takeID"]][variant]]))}
                                    for variant in swap_variants]
        scheduled_ids = {injector_id for injector_id, _ in task["schedule"]}
        for injector_id, by_source in splices.items():
            if injector_id not in scheduled_ids:
                continue
            picks = by_source.get(take["takeID"])
            if picks is None:
                task.setdefault("donorIssues", {})[injector_id] = pools[injector_id].issue(
                    take, donor_relations(plan, injector_id)) or "no donor was chosen for this take"
                continue
            task.setdefault("donors", {})[injector_id] = splice_items(by_id, picks, takes_path, alignments, labels)
        if take["takeID"] in impostors:
            task["sampleSeed"] = sample_seed
            picks = impostors[take["takeID"]]
            task["impostor"] = [
                {"variant": variant, "donor": by_id[picks[speaker_donors.IMPOSTOR_VARIANTS[variant]["donor"]]],
                 "wav": str(take_wav(takes_path, by_id[picks[speaker_donors.IMPOSTOR_VARIANTS[variant]["donor"]]]))}
                for variant in impostor_variants]
        if sampling is None or task["schedule"] or task.get("languageSwap") or task.get("impostor"):
            tasks.append(task)
    log(f"inject: {len(tasks)} of {len(generated)} generated takes x {len(scheduled)} scheduled variants"
        + (f" ({per_cell} families per cell)" if sampling is not None else "") + f", {jobs} jobs")
    skipped: dict[str, dict[str, Counter]] = {}
    counts = Counter()
    written = 0

    def entries() -> Iterator[dict]:
        nonlocal written
        for result in parallel(_inject_take, tasks, jobs, "inject"):
            written += result["bytes"]
            for key, variant, reason in result["skips"]:
                skipped.setdefault(key, {}).setdefault(variant, Counter())[reason] += 1
            for entry in result["entries"]:
                counts[entry["injection"]["population"]] += 1
                yield entry

    head = {
        "schemaVersion": 1, "kind": SET_KIND, "generator": GENERATOR,
        "sourceManifest": {"sha256": manifest_sha256, "kind": manifest["kind"], "runID": manifest.get("runID"),
                           "planDigest": manifest.get("planDigest"), "poolDigest": manifest.get("poolDigest"),
                           "split": manifest.get("split")},
        "catalogVersion": injectors.CATALOG_VERSION, "catalogSeed": catalog_seed,
        "mechanism": injectors.MECHANISM, "classes": sorted(set(classes)),
        "seedDerivation": f"{SEED_SCHEMA}: first 48 bits of SHA-256('{SEED_SCHEMA}|<source WAV SHA-256>|"
                          "<injector@version>|<catalog seed>'), big-endian; the variant is not an input, so a "
                          "sham draws the same positions as its positives",
        "schedule": {"version": SCHEDULE_VERSION, "rule": SCHEDULE_RULE,
                     "extras": {injectors.CATALOG[injector_id].key: list(names)
                                for injector_id, names in SCHEDULE_EXTRAS.items()}},
        "plan": plan, "recordingVariants": recording_variants_description(),
        "identitySwap": identity_swap_status(manifest),
        "textPolicy": TEXT_POLICY_EMBEDDED if embed else TEXT_POLICY_N3,
    }
    if manifest["kind"] in COHORT_KINDS:
        head["sourceManifest"]["population"] = population
    if any(isinstance(take.get("longForm"), dict) for take in generated):
        head["longForm"] = LONG_FORM_ENTRY_RULE
    speaker_splices = {injector_id: by_source for injector_id, by_source in splices.items()
                       if not voice_relations(donor_relations(plan, injector_id))}
    voice_splices = {injector_id: by_source for injector_id, by_source in splices.items()
                     if voice_relations(donor_relations(plan, injector_id))}
    if speaker_splices or impostor_variants:
        head["speakerDonors"] = {
            "schema": speaker_donors.CHOICE_SCHEMA, "seed": sample_seed, "choice": speaker_donors.CHOICE_RULE,
            "pool": "this cohort manifest (one split): takes of the source's language and gender that name their "
                    "speaker; another speaker's for a positive, another utterance of the source speaker for a sham; "
                    "a splice's donors only among takes whose alignment is usable",
            "labelledTakes": sum(1 for take in generated if speaker_donors.labelled(take)),
            "splices": {injectors.CATALOG[injector_id].key: {"relations": list(donor_relations(plan, injector_id)),
                                                             "sources": len(by_source)}
                        for injector_id, by_source in speaker_splices.items()},
        }
    if voice_splices:
        head["voiceDonors"] = {
            "schema": speaker_donors.CHOICE_SCHEMA, "seed": sample_seed, "choice": speaker_donors.CHOICE_RULE,
            "label": speaker_donors.VOICE_LABEL_RULE, "pool": speaker_donors.VOICE_POOL_RULE,
            "genders": "config/audio-qc-calibration-takes.json (speakerGenders; a Voice Design brief's gender where "
                       "it declares one)",
            "voices": voice_table(labels or {}),
            "labelledTakes": sum(1 for label in (labels or {}).values() if label is not None),
            "splices": {injectors.CATALOG[injector_id].key: {"relations": list(donor_relations(plan, injector_id)),
                                                             "sources": len(by_source)}
                        for injector_id, by_source in voice_splices.items()},
        }
    if impostor_variants:
        head["impostor"] = {**speaker_donors.describe_impostor(), "seed": sample_seed,
                            "eligibleSources": len(speaker_donors.DonorPool(generated).sources(
                                impostor_relations(impostor_variants))),
                            "sources": len(impostors)}
    if alignments is not None:
        head["alignments"] = {
            "sha256": alignments_sha256, "takesSHA256": alignments["takesSHA256"],
            "aligner": alignments.get("aligner"), "wordRule": alignments.get("wordRule"),
            "usableTakes": len(usable or ()),
            "note": "word-level variants run on the takes whose alignment is usable (recordings.word_alignment); "
                    "each such entry records sourceAlignment",
        }
    if sampling is not None:
        head["sampling"] = sampling
    if swap_variants:
        head["languageSwap"] = {**language_swap.describe(), "seed": sample_seed,
                                "eligibleSources": len(language_swap.eligible_sources(generated)),
                                "sources": len(donors),
                                "pool": "this cohort manifest (one split): donors share the source's FLoRes "
                                        "sentence (scriptID)"}

    def tail(entries_sha256: str) -> dict:
        not_applicable = {key: {"count": sum(sum(reasons.values()) for reasons in variants.values()),
                                "byVariant": {variant: dict(sorted(reasons.items()))
                                              for variant, reasons in sorted(variants.items())}}
                          for key, variants in sorted(skipped.items())}
        summary = {"entriesSHA256": entries_sha256, "notApplicable": not_applicable,
                   "counts": {"generatedTakes": len(generated),
                              "missingTakes": sum(1 for take in manifest["takes"] if take["status"] != "generated"),
                              "ineligibleTakes": len(ineligible_takes(manifest)),
                              "shams": counts["S"], "positives": counts["P1"], "wavBytes": written}}
        if sampling is not None:
            summary["counts"]["sourceTakes"] = len(tasks)
        return summary

    path = output / "injection-set.json"
    _write_streamed(path, head, "entries", entries(), tail)
    summary = json.loads(path.read_text(encoding="utf-8"))
    log(f"inject: wrote {summary['counts']['shams']} shams and {summary['counts']['positives']} positives "
        f"({written / 1e6:.1f} MB of WAV) and {path.name}")
    return summary


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def load_set(path: Path) -> dict:
    injection_set = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(injection_set, dict) or injection_set.get("kind") != SET_KIND \
            or injection_set.get("schemaVersion") != 1 or not isinstance(injection_set.get("entries"), list):
        raise CalibrationError(f"{path.name} is not an {SET_KIND} schema 1 file")
    return injection_set


def _verify_swap(entry: dict, task: dict, fixture_digest: str, digest: str) -> str | None:
    """A language swap: the donor the choice re-derives, its audio as it is, and what it was presented as."""
    take = task["take"]
    recipe = entry.get("injection") or {}
    variant = str(recipe.get("variant"))
    swap = (task.get("swaps") or {}).get(variant)
    if variant not in language_swap.VARIANTS or swap is None:
        return "no such language swap was chosen for this source"
    donor = swap["donor"]
    output = Path(task["setDir"]) / entry["wavPath"]
    if not output.is_file() or file_sha256(output) != entry.get("wavSHA256"):
        return "output WAV is missing or its file digest differs"
    donor_wav = Path(swap["wav"])
    samples = recordings.read_pcm16_wav(output)
    expected = language_swap.injection(
        variant=variant, source=take, donor=donor, seed=task["swapSeed"], source_pcm_sha256=fixture_digest,
        output_pcm_sha256=pcm_digest(samples), frames=int(samples.size))
    checks = [
        (recipe == _plain(expected), "the recipe differs from the re-derived swap (donor, digests or labels)"),
        (donor_wav.is_file() and file_sha256(donor_wav) == donor["wavSHA256"], "the donor WAV differs"),
        (entry.get("wavSHA256") == donor["wavSHA256"], "the clip is not the donor's audio as it is"),
        (recipe.get("sourceWAVSHA256") == digest, "source WAV digest differs"),
        (entry.get("family") == donor["family"], "family differs from the donor recording's"),
        (entry.get("language") == take["language"], "the presented language is not the source's"),
    ]
    problems = [message for ok, message in checks if not ok]
    return "; ".join(problems) if problems else None


def _verify_impostor(entry: dict, task: dict, fixture_digest: str, digest: str) -> str | None:
    """An impostor: the donor the choice re-derives, its audio and text as they are, presented as the source speaker."""
    take = task["take"]
    recipe = entry.get("injection") or {}
    variant = str(recipe.get("variant"))
    item = (task.get("impostors") or {}).get(variant)
    if variant not in speaker_donors.IMPOSTOR_VARIANTS or item is None:
        return "no such impostor was chosen for this source"
    donor = item["donor"]
    output = Path(task["setDir"]) / entry["wavPath"]
    if not output.is_file() or file_sha256(output) != entry.get("wavSHA256"):
        return "output WAV is missing or its file digest differs"
    donor_wav = Path(item["wav"])
    samples = recordings.read_pcm16_wav(output)
    expected = speaker_donors.impostor_injection(
        variant=variant, source=take, donor=donor, seed=task["impostorSeed"], source_pcm_sha256=fixture_digest,
        output_pcm_sha256=pcm_digest(samples), frames=int(samples.size))
    checks = [
        (recipe == _plain(expected), "the recipe differs from the re-derived impostor (donor, digests or labels)"),
        (donor_wav.is_file() and file_sha256(donor_wav) == donor["wavSHA256"], "the donor WAV differs"),
        (entry.get("wavSHA256") == donor["wavSHA256"], "the clip is not the donor's audio as it is"),
        (recipe.get("sourceWAVSHA256") == digest, "source WAV digest differs"),
        (entry.get("family") == donor["family"], "family differs from the donor recording's"),
        ((entry.get("speaker"), entry.get("gender")) == (take["speaker"], take["gender"]),
         "the presented speaker is not the source's"),
        ((entry.get("reference") or {}).get("wavSHA256") == take["wavSHA256"],
         "its reference clip is not its source take"),
        (entry.get("textSHA256") == text_sha256(donor["text"]) and entry.get("text", donor["text"]) == donor["text"],
         "its text is not its donor's own"),
    ]
    problems = [message for ok, message in checks if not ok]
    return "; ".join(problems) if problems else None


def _verify_donor(recipe: dict, task: dict, injector_id: str, relation: str) -> tuple[Any, str | None]:
    """The donor fixture of a splice entry, or why its recorded donor is not the one the choice re-derives."""
    item = ((task.get("donors") or {}).get(injector_id) or {}).get(relation)
    if item is None:
        return None, "no such donor was chosen for this source"
    try:
        fixture, digest, alignment, _status = _source_fixture(item)
    except recordings.RecordingError as error:
        return None, f"donor: {error}"
    if recipe.get("donor") != _plain(donor_block(item, relation, fixture, digest, alignment)):
        return None, "the donor differs from the re-derived choice (take, digests, alignment, voice or seams)"
    return fixture, None


def _verify_take(task: dict) -> list[list[str]]:
    take = task["take"]
    failures: list[list[str]] = []
    rate = source_rate(take)
    try:
        fixture, digest, source_alignment, _status = _source_fixture(task)
    except recordings.RecordingError as error:
        return [[entry["takeID"], f"source: {error}"] for entry in task["entries"]]
    for entry in task["entries"]:
        clip = entry["takeID"]
        recipe = entry.get("injection") or {}
        if recipe.get("injectorID") == speaker_donors.IMPOSTOR_ID:
            # An impostor carries its donor's own text, never the source's.
            problem = _verify_impostor(entry, task, fixture.digest, digest)
            if problem:
                failures.append([clip, problem])
            continue
        if entry.get("textSHA256") != text_sha256(take["text"]) or ("text" in entry and entry["text"] != take["text"]):
            failures.append([clip, "its text is not its source take's"])
            continue
        if recipe.get("injectorID") == language_swap.INJECTOR_ID:
            problem = _verify_swap(entry, task, fixture.digest, digest)
            if problem:
                failures.append([clip, problem])
            continue
        try:
            injector = injectors.CATALOG[str(recipe.get("injectorID"))]
            variant = injector.variant(str(recipe.get("variant")))
        except KeyError:
            failures.append([clip, "the catalog has no such injector or variant"])
            continue
        relation = variant.parameters.get("donor")
        checks = [
            (recipe.get("injector") == injector.key, "injector version differs from the catalog"),
            (recipe.get("catalogVersion") == injectors.CATALOG_VERSION, "catalog version differs"),
            (recipe.get("severity") == variant.severity, "severity differs from the catalog"),
            (recipe.get("parameters") == _plain(dict(variant.parameters)), "parameters differ from the catalog"),
            (recipe.get("sourceWAVSHA256") == digest, "source WAV digest differs"),
            (recipe.get("sourceResampling") == recordings.resampling_recipe(rate), "source resampling differs"),
            (recipe.get("seed") == derive_seed(digest, injector.key, task["catalogSeed"]),
             "seed differs from its derivation"),
            (entry.get("family") == take["family"], "family differs from the source take's"),
            (recipe.get("sourceAlignment") == _plain(source_alignment), "source word alignment differs"),
            (recipe.get("sourceSeams", []) == list(fixture.seams), "source seams differ"),
            (relation is not None or "donor" not in recipe, "a donor on a variant that splices none"),
        ]
        problems = [message for ok, message in checks if not ok]
        if problems:
            failures.append([clip, "; ".join(problems)])
            continue
        donor = None
        if relation is not None:
            donor, problem = _verify_donor(recipe, task, injector.injector_id, relation)
            if problem:
                failures.append([clip, problem])
                continue
        replay = injectors.inject(injector.injector_id, variant.name, fixture, int(recipe["seed"]), donor=donor)
        if replay.digest != recipe.get("outputPCMSHA256") or _plain(list(replay.labels)) != recipe.get("labels"):
            failures.append([clip, "replay differs from the recorded output digest or labels"])
            continue
        if entry.get("seamSamples", []) != list(replay.seams):
            failures.append([clip, "its seams differ from the replay's"])
            continue
        if task.get("longFormRule") \
                and entry.get("longForm") != _plain(output_long_form(take, replay.samples, replay.seams)):
            failures.append([clip, "its longForm block does not describe the replay's output"])
            continue
        output = Path(task["setDir"]) / entry["wavPath"]
        if not output.is_file() or file_sha256(output) != entry.get("wavSHA256"):
            failures.append([clip, "output WAV is missing or its file digest differs"])
            continue
        if pcm_digest(recordings.read_pcm16_wav(output)) != replay.digest:
            failures.append([clip, "output WAV PCM differs from the replay"])
    return failures


def run_verify(set_path: Path, takes_path: Path, *, jobs: int, alignments_path: Path | None = None) -> dict:
    injection_set = load_set(set_path)
    manifest, manifest_sha256 = load_takes(takes_path)
    version = injection_set.get("catalogVersion")
    if version != injectors.CATALOG_VERSION:
        # Refused whole: this code replays only its own catalog version. Version 3 left every version 2
        # output unchanged, but a replay under another catalog is not the verification of the set's own.
        return {"entries": len(injection_set["entries"]), "sources": 0, "verified": False,
                "failures": [["<set>", f"the set was built with injector catalog version {version}; this code "
                                       f"replays version {injectors.CATALOG_VERSION} only: verify it with the "
                                       "code of its version, or rebuild it"]]}
    failures: list[list[str]] = []
    if injection_set.get("sourceManifest", {}).get("sha256") != manifest_sha256:
        failures.append(["<set>", "the set was built from another takes manifest"])
    if json_digest(injection_set["entries"]) != injection_set.get("entriesSHA256"):
        failures.append(["<set>", "entriesSHA256 differs from the entries"])
    generated = generated_takes(manifest)
    takes = {take["takeID"]: take for take in generated}
    alignments = None
    declared = injection_set.get("alignments")
    if declared is not None:
        if alignments_path is None:
            failures.append(["<set>", "the set used the aligner's word intervals; verify needs its --alignments"])
        else:
            alignments, digest = load_alignments(alignments_path, manifest_sha256)
            if digest != declared.get("sha256"):
                failures.append(["<set>", "the alignments differ from the ones the set was built with"])
                alignments = None
    sampling = injection_set.get("sampling")
    plan = injection_set.get("plan") or []
    # The voice labels a voice-donor splice drew from, from the committed take policy's genders.
    labels = voice_labels(generated, voice_genders()) if needs_voice_labels(plan) else None
    voices = injection_set.get("voiceDonors")
    if voices is not None and voices.get("voices") != _plain(voice_table(labels or {})):
        failures.append(["<set>", "the voices or their genders differ from the take policy's (voiceDonors.voices)"])
    if sampling is not None and (declared is None or alignments is not None):
        redrawn = build_sampling(generated, plan, per_cell=int(sampling.get("perCell") or 0),
                                 seed=int(sampling.get("seed") or 0),
                                 usable_words=usable_word_takes(generated, alignments), voice_labels=labels)
        if _plain(redrawn) != sampling:
            failures.append(["<set>", "the sampled families differ from a redraw with the set's seed"])
    swap = injection_set.get("languageSwap")
    donors: dict[str, dict[str, str]] = {}
    if swap is not None:
        donors = language_swap.choose_donors(generated, swap_sources(generated, plan, sampling),
                                             seed=int(swap.get("seed") or 0))
    # The speaker and voice donors, re-derived as `inject` chose them (a splice's pool depends on the alignments).
    chooser = injection_set.get("speakerDonors") or voices
    splices: dict[str, dict[str, dict[str, str]]] = {}
    if chooser is not None and (declared is None or alignments is not None):
        splices = splice_donors(generated, plan, sampling, usable_word_takes(generated, alignments),
                                seed=int(chooser.get("seed") or 0), voice_labels=labels)
    impostor = injection_set.get("impostor")
    impostors = {} if impostor is None else impostor_donors(generated, plan, sampling,
                                                            seed=int(impostor.get("seed") or 0))
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for entry in injection_set["entries"]:
        source = entry.get("sourceTakeID")
        if source not in takes:
            failures.append([str(entry.get("takeID")), "its source take is not a generated take of the manifest"])
            continue
        grouped.setdefault(source, []).append(entry)
    tasks = []
    for source, entries in grouped.items():
        task = {"take": takes[source], "wav": str(take_wav(takes_path, takes[source])), "entries": entries,
                "setDir": str(set_path.parent), "catalogSeed": injection_set.get("catalogSeed")}
        if injection_set.get("longForm") is not None:
            # The set records each entry's longForm block for its own output (LONG_FORM_ENTRY_RULE).
            task["longFormRule"] = True
        if alignments is not None:
            task["alignment"] = alignment_context(alignments["takes"].get(source))
        if source in donors:
            task["swapSeed"] = int(swap["seed"])
            task["swaps"] = {variant: {"donor": takes[donor], "wav": str(take_wav(takes_path, takes[donor]))}
                             for variant, donor in donors[source].items()}
        for injector_id, by_source in splices.items():
            if source in by_source:
                task.setdefault("donors", {})[injector_id] = splice_items(takes, by_source[source], takes_path,
                                                                          alignments, labels)
        if source in impostors:
            task["impostorSeed"] = int(impostor["seed"])
            task["impostors"] = {
                variant: {"donor": takes[impostors[source][speaker_donors.IMPOSTOR_VARIANTS[variant]["donor"]]],
                          "wav": str(take_wav(takes_path, takes[impostors[source][
                              speaker_donors.IMPOSTOR_VARIANTS[variant]["donor"]]]))}
                for variant in impostors_scheduled(plan)}
        tasks.append(task)
    # Completeness (review of 6b1135e9): every scheduled T1 variant is accounted for on exactly its cell's
    # sampled families, as an entry or a recorded not-applicable skip, and no entry comes from outside them.
    # A set filtered after the fact, even with a recomputed entriesSHA256, fails here.
    if sampling is not None:
        skipped = injection_set.get("notApplicable") or {}
        cells = sampling.get("injectors") or {}
        family_takes: dict[str, set[str]] = {}
        for take in generated:
            family_takes.setdefault(take["family"], set()).add(take["takeID"])
        recorded: dict[tuple[str, str], list[str]] = {}
        for entry in injection_set["entries"]:
            injection = entry.get("injection") or {}
            if injection.get("injectorID") in (language_swap.INJECTOR_ID, speaker_donors.IMPOSTOR_ID):
                continue
            recorded.setdefault((str(injection.get("injector")), str(injection.get("variant"))), []).append(
                str(entry.get("sourceTakeID")))
        for row in plan:
            if row["status"] == "out-of-scope" or row["variant"] is None \
                    or row["injectorID"] not in injectors.CATALOG:
                continue
            key, variant = row["injector"], row["variant"]
            families = (cells.get(key) or {}).get("families") or []
            sampled = {take_id for family in families for take_id in family_takes.get(family, ())}
            sources = recorded.get((key, variant), [])
            outside = sorted(set(sources) - sampled)
            if outside:
                failures.append(["<set>", f"{key} {variant}: {len(outside)} entries come from families outside "
                                          "its sample"])
            skips = sum(((skipped.get(key) or {}).get("byVariant", {}).get(variant) or {}).values())
            if len(set(sources)) + skips != len(sampled) or len(set(sources)) != len(sources):
                failures.append(["<set>", f"{key} {variant}: {len(sources)} entries and {skips} skips account for "
                                          f"{len(sampled)} sampled sources"])
    expected_swaps = len(swaps_scheduled(plan)) * len(donors)
    recorded_swaps = sum(1 for entry in injection_set["entries"]
                         if (entry.get("injection") or {}).get("injectorID") == language_swap.INJECTOR_ID)
    if recorded_swaps != expected_swaps:
        failures.append(["<set>", f"{recorded_swaps} language swaps recorded, {expected_swaps} re-derived"])
    expected_impostors = len(impostors_scheduled(plan)) * len(impostors)
    recorded_impostors = sum(1 for entry in injection_set["entries"]
                             if (entry.get("injection") or {}).get("injectorID") == speaker_donors.IMPOSTOR_ID)
    if recorded_impostors != expected_impostors:
        failures.append(["<set>", f"{recorded_impostors} impostors recorded, {expected_impostors} re-derived"])
    for result in parallel(_verify_take, tasks, jobs, "verify"):
        failures.extend(result)
    return {"entries": len(injection_set["entries"]), "sources": len(tasks), "failures": failures,
            "verified": not failures}


# --------------------------------------------------------------------------- #
# score
# --------------------------------------------------------------------------- #

def generation_evidence(source: dict, *, own_generation: bool) -> dict:
    """What a clip carries of the generation beside Fast QC, from its take or entry.

    `own_generation` says the clip's audio is the generation's own output (a
    clean take, a byte-copied donor, a T2 replay or a T3 knob take), so its
    engine introspection summary describes it; a T1 PCM construction changed
    the audio after generation and carries none. A `longForm` block
    (`audio_qc_calibration_takes.long_form_block`) gives the seams: the clean
    take's must describe its WAV exactly, while a T1 construction keeps them
    only if it kept the output's length (see `_long_form`).
    """
    import audio_qc_calibration_takes as takes_tool  # deferred: only long-form and introspection takes need it

    evidence: dict[str, Any] = {}
    introspection = source.get("engineIntrospection")
    if own_generation and introspection is not None:
        if issues := takes_tool.introspection_issues(introspection):
            raise CalibrationError(f"{source.get('takeID')}: {issues[0]}")
        if introspection.get("wavSHA256") != source.get("wavSHA256"):
            # A summary binds the WAV its generation wrote; an entry that copied its source's fields does not.
            raise CalibrationError(f"{source.get('takeID')}: its introspection summary describes other audio than "
                                   "its WAV (a T2 or T3 entry records its own generation's summary)")
        evidence["introspection"] = introspection
    block = source.get("longForm")
    if block is not None:
        if issues := takes_tool.long_form_issues(block):
            raise CalibrationError(f"{source.get('takeID')}: {issues[0]}")
        evidence.update(longForm=block, longFormRecorded=own_generation)
    return evidence


def boundary_jump(samples: np.ndarray, seams: Iterable[int]) -> int:
    """The assembler's maximum segment-boundary jump, read back from the joined PCM16: the largest step
    between each seam's first frame and the frame before it (the previous content's last frame or the pause's
    last zero), in PCM16 units (LongFormAssembly.swift `write`)."""
    pcm = np.rint(np.asarray(samples, dtype=np.float64) * recordings.PCM16_FULL_SCALE).astype(np.int64)
    return max((int(abs(pcm[seam] - pcm[seam - 1])) for seam in seams), default=0)


def _long_form(task: dict, samples: np.ndarray) -> dict | None:
    """The clip's long-form block with its boundary jump measured on its own PCM, or None.

    A clean take's recorded block must describe its WAV (length, rate, the
    assembler's jump); a T1 construction that kept the length keeps the seams,
    and its jump is measured on the constructed PCM. One that moved them
    (SEAM-DISC removes samples after a seam) is described at the seams its
    entry records, one per seam of its source; one that recorded none (an edit
    whose timeline no seam mapping follows) has no block, so a seam detector
    abstains on it.
    """
    block = task.get("longForm")
    if block is None:
        return None
    fits = block["sampleRate"] == recordings.ENGINE_SAMPLE_RATE and block["outputFrameCount"] == samples.size
    if not fits:
        if task["longFormRecorded"]:
            raise CalibrationError(f"{task['clipID']}: its longForm block does not describe its WAV (length or rate)")
        seams = [int(seam) for seam in task.get("seams") or ()]
        if block["sampleRate"] != recordings.ENGINE_SAMPLE_RATE or len(seams) != len(block["seamFrames"]) \
                or not seams or seams[-1] >= samples.size:
            return None
        block = {**block, "outputFrameCount": int(samples.size), "seamFrames": seams}
    jump = boundary_jump(samples, block["seamFrames"])
    if task["longFormRecorded"] and jump != block["maximumSegmentBoundaryJump"]:
        raise CalibrationError(f"{task['clipID']}: its PCM steps {jump} at the recorded seams, the assembler "
                               f"recorded {block['maximumSegmentBoundaryJump']}")
    return {**block, "maximumSegmentBoundaryJump": jump}


def _score_clip(task: dict) -> dict:
    path = Path(task["wav"])
    if not path.is_file() or file_sha256(path) != task["wavSHA256"]:
        raise CalibrationError(f"{task['clipID']}: its WAV is missing or differs from its digest")
    rate = int(task.get("sourceRate") or recordings.ENGINE_SAMPLE_RATE)
    samples = recordings.read_pcm16_wav(path, sample_rate=rate)
    if recordings.resampling_recipe(rate) is not None:
        # An N1 recording reaches the engine rate as it does before any injector (recordings.load_recording).
        samples = polyphase_resample(samples, rate, recordings.ENGINE_SAMPLE_RATE)
    long_form = _long_form(task, samples)
    # A long-form clip's seams feed the Stage 0 seam z-score (no v8 flag or verdict reads them): its longForm
    # block when the block still describes the PCM, else the seams an injection entry records (SEAM-DISC
    # shortens the audio and records its shifted seams).
    seams = long_form["seamFrames"] if long_form else (task.get("seams") or ())
    report = audio_qc.fast_qc_v8(samples, sample_rate=recordings.ENGINE_SAMPLE_RATE, text=task["text"], signal=True,
                                 seam_offsets=seams)
    fast = {"verdict": report["verdict"], "instabilityVerdict": report["instabilityVerdict"],
            "writtenOutputVerdict": report["writtenOutputVerdict"], "flags": list(report["flags"]),
            "flagLevels": dict(report["flagLevels"])}
    fast.update({field: report.get(field) for field in FASTQC_FIELDS})
    clip = {**task["meta"], "wavSHA256": task["wavSHA256"], "pcmSHA256": pcm_digest(samples),
            "fastQC": fast, "observations": report["signal"],
            # The PCM shape measures the `pcm` detector source reads, stamped with their code's digest (an N1
            # recording's are measured after its resampling, so its flat tops and zero runs are not its own).
            "pcmMeasures": pcm_measures.measure(samples, recordings.ENGINE_SAMPLE_RATE)}
    # The Stage 0 blocks the `introspection` and `longform` detector sources read (absent otherwise).
    if task.get("introspection") is not None:
        clip["introspection"] = task["introspection"]
    if long_form is not None:
        clip["longForm"] = long_form
    return _plain(clip)


def _meta(take: dict, clip_id: str, population: str, injection: dict | None, *, family: str | None = None) -> dict:
    # A clip's family is its entry's: the source take's for a T1 construction, the donor's for a language swap.
    return {
        "clipID": clip_id, "population": population, "family": family or take["family"],
        "sourceTakeID": take["takeID"],
        "scriptID": take.get("scriptID"), "language": take.get("language"), "mode": take.get("mode"),
        "takeVariant": take.get("variant"), "voice": voice_label(take), "seed": take.get("seed"),
        "injection": None if injection is None else {
            "injector": injection["injector"], "injectorID": injection["injectorID"],
            "variant": injection["variant"], "severity": injection["severity"],
            "classes": injection["classes"], "outputPCMSHA256": injection["outputPCMSHA256"]},
    }


def _reduced(measurement: dict) -> dict:
    """What the report reads of one clip: no flags text beyond families, no digests."""
    injection = measurement["injection"] or {}
    return {
        "clipID": measurement["clipID"], "population": measurement["population"],
        "family": measurement["family"], "sourceTakeID": measurement["sourceTakeID"],
        "language": measurement["language"], "injector": injection.get("injector"),
        "injectorID": injection.get("injectorID"), "variant": injection.get("variant"),
        "severity": injection.get("severity"), "verdict": measurement["fastQC"]["verdict"],
        "flagLevels": measurement["fastQC"]["flagLevels"],
        "observations": {name: measurement["observations"].get(name) for name in OBSERVATION_MEASURES},
    }


def _family_rate(units: Iterable[tuple[str, bool]]) -> dict:
    return m1._family_rate(units)


def _family_detection(units: Iterable[tuple[str, bool]]) -> dict:
    """Positives: a family is detected only if every one of its clips is (a miss on any is a miss)."""
    counts = resampling.family_counts(list(units))
    return Rate(sum(1 for events, total in counts.values() if events == total), len(counts)).as_dict()


def _overlap(first: dict, second: dict) -> bool | None:
    if not first["units"] or not second["units"]:
        return None
    return m1._overlap(first, second)


def _at_level(value: str | None, level: str) -> bool:
    return value == "fail" if level == "fail" else value in ("warn", "fail")


def _flag_rates(records: list[dict]) -> dict:
    return {flag: {("fail" if level == "fail" else "warnOrWorse"):
                   _family_rate((record["family"], _at_level(record["flagLevels"].get(flag), level))
                                for record in records)
                   for level in levels}
            for flag, levels in audio_qc.FASTQC_V8_FLAGS.items()}


def _targets(injector_id: str | None) -> tuple[str, ...]:
    return m1.TARGETS.get(injector_id or "", ())


def _hit(record: dict, targets: tuple[str, ...]) -> bool:
    return bool(set(record["flagLevels"]) & set(targets))


def _alarm(record: dict) -> bool:
    return record["verdict"] != "pass"


def _grouped(records: list[dict]) -> "OrderedDict[tuple[str, str], list[dict]]":
    groups: "OrderedDict[tuple[str, str], list[dict]]" = OrderedDict()
    for record in records:
        groups.setdefault((record["injector"], record["variant"]), []).append(record)
    return groups


def _median(values: list[float]) -> float | None:
    return round(float(np.median(values)), 6) if values else None


LABELED_NOTES = {
    "N2": "N2 negatives are human recordings with published text (T4) resynthesized through the codec: a flag on "
          "one is a false alarm, so the flag rate's one-sided CP upper bound bounds FAR directly (A2); shown for "
          "the calibration cohort, report-only until a pre-registered plan scores the confirmation cohort (A5)",
    "N1": "N1 negatives are human recordings with published text (T4): a flag on one is a false alarm, so the flag "
          "rate's one-sided CP upper bound bounds FAR directly; N1 alone never qualifies a fail (A2)",
}
COHORT_CAVEATS = {
    "N2": "Nothing here qualifies anything: a record needs a pre-registered plan scored once on the confirmation "
          "cohort (A5), TPR on two mechanisms (A3) and shams that stay with the clean rate (A4). Fast QC v8's "
          "bounds stay legacy-unqualified (A10).",
    "N1": "Nothing here qualifies anything: N1 alone never qualifies a fail (A2), and a record needs N2, a "
          "pre-registered plan (A5) and TPR on two mechanisms (A3). Fast QC v8's bounds stay legacy-unqualified "
          "(A10).",
}


def clean_population(report: dict) -> str:
    """The report's clean population: N3, or N1/N2 for a cohort."""
    return next(name for name in report["populations"] if name not in ("S", "P1"))


def build_report(records: list[dict], *, inputs: dict, injection_set: dict, population: str = "N3") -> dict:
    clean_key = population.lower()
    negatives = [record for record in records if record["population"] == population]
    shams = [record for record in records if record["population"] == "S"]
    positives = [record for record in records if record["population"] == "P1"]
    clean_by_take = {record["sourceTakeID"]: record for record in negatives}
    skipped = injection_set.get("notApplicable", {})

    def skips(key: str, variant: str) -> int:
        return sum((skipped.get(key, {}).get("byVariant", {}).get(variant) or {}).values())

    n3_alarm = _family_rate((record["family"], _alarm(record)) for record in negatives)
    rejected = [record for record in negatives if record.get("engineRejected")]
    n3 = {
        "clips": len(negatives), "families": len({record["family"] for record in negatives}),
        "engineRejected": {
            "takes": len(rejected),
            "rate": _family_rate((record["family"], bool(record.get("engineRejected"))) for record in negatives),
            "flags": dict(sorted(Counter(flag for record in rejected for flag in record["flagLevels"]).items())),
            "note": "refused by the engine's mandatory Fast QC, so no audio exists; each counts as a v8 fail "
                    "with the flag families it recorded, and carries no Stage 0 observation",
        },
        "alarm": n3_alarm, "fail": _family_rate((record["family"], record["verdict"] == "fail")
                                                for record in negatives),
        "flags": _flag_rates(negatives),
    }
    if population == "N3":
        n3["unlabeledBound"] = {
            "note": "N3 carries no labels: FAR <= f / (1 - pi_max), f the flag rate and pi_max the maximum "
                    "defect prevalence; shown for the flag rate's one-sided CP upper bound",
            "flagRateUpper": n3_alarm["upper"],
            "farBoundAtPiMax": {str(pi): (None if n3_alarm["upper"] is None
                                          else round(min(1.0, n3_alarm["upper"] / (1.0 - pi)), 6))
                                for pi in PI_MAX},
        }
    else:
        n3["labeledBound"] = {"note": LABELED_NOTES[population], "farUpper": n3_alarm["upper"]}

    sham_rows = []
    for (key, variant), group in _grouped(shams).items():
        injector_id = group[0]["injectorID"]
        targets = _targets(injector_id)
        families = {record["family"] for record in group}
        same = [record for record in negatives if record["family"] in families]
        alarm = _family_rate((record["family"], _alarm(record)) for record in group)
        clean_alarm = _family_rate((record["family"], _alarm(record)) for record in same)
        row = {"injector": key, "variant": variant, "targets": list(targets), "units": alarm["units"],
               "notApplicable": skips(key, variant), "alarm": alarm, "cleanAlarmSameFamilies": clean_alarm,
               "alarmOverlaps": _overlap(alarm, clean_alarm),
               "flags": dict(sorted(Counter(flag for record in group for flag in record["flagLevels"]).items()))}
        if targets:
            target = _family_rate((record["family"], _hit(record, targets)) for record in group)
            clean_target = _family_rate((record["family"], _hit(record, targets)) for record in same)
            row["a4"] = {"basis": "target-flags", "sham": target, "cleanSameFamilies": clean_target,
                         "overlaps": _overlap(target, clean_target)}
        else:
            row["a4"] = {"basis": "not-applicable", "reason": "v8 has no detector for this family",
                         "overlaps": None}
        sham_rows.append(row)
    sham_pooled = _family_rate((record["family"], _alarm(record)) for record in shams)
    sham_flags = _flag_rates(shams)
    flags = []
    for flag, levels in audio_qc.FASTQC_V8_FLAGS.items():
        level = "warnOrWorse" if "warn" in levels else "fail"
        n3_rate, sham_rate = n3["flags"][flag][level], sham_flags[flag][level]
        flags.append({"flag": flag, "levels": list(levels), "basis": level, clean_key: n3["flags"][flag],
                      "shams": sham_flags[flag], "overlaps": _overlap(sham_rate, n3_rate),
                      "targetedBy": sorted(injector for injector, targets in m1.TARGETS.items()
                                           if flag in targets)})

    detection = []
    for (key, variant), group in _grouped(positives).items():
        injector_id = group[0]["injectorID"]
        targets = _targets(injector_id)
        deltas = {}
        for name in OBSERVATION_MEASURES:
            values = []
            for record in group:
                source = clean_by_take.get(record["sourceTakeID"])
                clip, clean = record["observations"].get(name), (source or {}).get("observations", {}).get(name)
                if clip is not None and clean is not None:
                    values.append(clip - clean)
            deltas[name] = _median(values)
        detection.append({
            "injector": key, "variant": variant, "severity": group[0]["severity"],
            "classes": list(injector_classes(injector_id)), "targets": list(targets),
            "units": len({record["family"] for record in group}), "notApplicable": skips(key, variant),
            "target": _family_detection((record["family"], _hit(record, targets)) for record in group)
            if targets else None,
            "alarm": _family_detection((record["family"], _alarm(record)) for record in group),
            "fail": _family_detection((record["family"], record["verdict"] == "fail") for record in group),
            "flags": dict(sorted(Counter(flag for record in group for flag in record["flagLevels"]).items())),
            "observationMedianDelta": deltas,
        })

    languages = sorted({record["language"] for record in records})
    confidence = bonferroni_confidence(DEFAULT_CONFIDENCE, max(1, len(languages)))
    per_language = {}
    for language in languages:
        clean = [record for record in negatives if record["language"] == language]
        units = [(record["family"], _alarm(record)) for record in clean]
        severe: dict[str, list[dict]] = {}
        for record in positives:
            if record["language"] == language and record["severity"] == "severe" and _targets(record["injectorID"]):
                severe.setdefault(record["injector"], []).append(record)
        per_language[language] = {
            f"{clean_key}Families": len({record["family"] for record in clean}),
            "alarm": _family_rate(units),
            "alarmSimultaneous": Rate(*resampling.family_level_events(units), confidence=confidence).as_dict(),
            "fail": _family_rate((record["family"], record["verdict"] == "fail") for record in clean),
            "shamAlarm": _family_rate((record["family"], _alarm(record)) for record in shams
                                      if record["language"] == language),
            "severeTargetDetection": {key: _family_detection(
                (record["family"], _hit(record, _targets(record["injectorID"]))) for record in group)
                for key, group in sorted(severe.items())},
        }
    judged = [(language, entry) for language, entry in per_language.items() if entry["alarm"]["units"]]
    worst_alarm = max(judged, key=lambda item: (item[1]["alarm"]["upper"], item[0]), default=None)
    # For each injector v8 detects at all when severe, the language where it detects least.
    worst_detection = []
    for row in detection:
        if row["severity"] != "severe" or not row["target"] or not row["target"]["events"]:
            continue
        rates = [(language, entry["severeTargetDetection"][row["injector"]])
                 for language, entry in per_language.items() if row["injector"] in entry["severeTargetDetection"]]
        language, rate = min(rates, key=lambda item: (item[1]["lower"], item[0]))
        worst_detection.append({"injector": row["injector"], "language": language, **rate})

    observations = {}
    for name in OBSERVATION_MEASURES:
        observations[name] = {
            population: m1._summary([record["observations"][name] for record in negatives
                                     if record["observations"].get(name) is not None]),
            "S": m1._summary([record["observations"][name] for record in shams
                              if record["observations"].get(name) is not None]),
        }

    report = {
        "schema": REPORT_SCHEMA, "generator": GENERATOR, "phase": "M2", "reportOnly": True,
        "subject": {"detector": m1.SUBJECT, "mirror": audio_qc.FASTQC_V8_MIRROR,
                    "observations": audio_qc_observations.OBSERVATIONS_MIRROR, "calibration": "legacy-unqualified"},
        "inputs": inputs,
        "populations": {
            population: {"clips": len(negatives), "families": n3["families"], "engineRejected": len(rejected)},
            "S": {"clips": len(shams), "families": len({record["family"] for record in shams})},
            "P1": {"clips": len(positives), "families": len({record["family"] for record in positives})},
        },
        "unit": "source family (policy thresholdDerivation.unitOfRates): a negative family errs if any of its "
                "clips alarms; a positive family is detected only if every one of its clips is",
        clean_key: n3,
        "flags": flags,
        "shams": sham_rows,
        "shamsPooled": {"alarm": sham_pooled, f"{clean_key}Alarm": n3_alarm,
                        "overlaps": _overlap(sham_pooled, n3_alarm),
                        "clusterBootstrap": resampling.cluster_bootstrap_rate(
                            [(record["family"], _alarm(record)) for record in shams], label="calibration-shams")},
        "detection": detection,
        "languages": {"rows": per_language, "simultaneousConfidence": round(confidence, 6),
                      f"worst{population}Alarm": None if worst_alarm is None else
                      {"language": worst_alarm[0], **worst_alarm[1]["alarm"]},
                      "worstSevereDetection": worst_detection},
        "observations": observations,
        "notApplicable": skipped,
        "plan": injection_set.get("plan", []),
        "identitySwap": injection_set.get("identitySwap"),
        "caveats": [
            "N3 is unlabeled: a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), pi_max being "
            "the maximum defect prevalence among natural takes.",
            "Nothing here qualifies anything. T1 on N3 is report-only: a fail bound needs FAR confirmed on N2 "
            "and a plan committed before its confirmation cohort is scored (A2, A5), and TPR on two "
            "mechanisms (A3). Fast QC v8's bounds stay legacy-unqualified (A10).",
            "Recorded takes carry no word intervals, so word-aligned variants are not applicable. The take-* "
            "variants are declared word-free constructions: clicks anywhere, a dropout centred on the take, "
            "noise against the whole take's RMS, a cut at a fraction of the take (which can remove only the "
            "trailing pause) and a run-on of a middle span appended after the take's end.",
            "Per-injection seeds derive from the source WAV digest, the injector and the catalog seed, not "
            "the variant, so a sham draws the same positions as its positives (injectors.inject).",
            "Fast QC runs each clip through the v8 mirror's limiter as if the engine had produced it, as M1 "
            "does; the Stage 0 observations read the PCM16 that limiter writes.",
            "Identity swaps from the donor pairs are deferred (identitySwap).",
            "Takes the engine's mandatory Fast QC refused have no audio: they count in the N3 rates as v8 fails "
            "with the flag families the engine recorded (a warn-or-fail family counts at fail only when it alone "
            "caused the fail), carry no Stage 0 observation, and are no source of any injection.",
        ],
    }
    if population != "N3":
        report["caveats"] = [
            LABELED_NOTES[population] + ".",
            COHORT_CAVEATS[population],
            "Word-level variants run on the takes whose forced alignment is usable (sourceAlignment in the set); "
            "without it they are not applicable. The take-* variants are declared constructions: word-free ones, "
            "and donor splices that need the word intervals of both recordings.",
            "Injections cover a seeded, language-stratified sample of source families per injector when the set "
            "samples (sampling in the set); the clean rates cover every eligible recording.",
            "A language swap (LNG-SWAP) is another recording's audio as it is, presented with the source's "
            "language and text; its family is that recording's, and v8 has no language detector.",
            "Per-injection seeds derive from the source WAV digest, the injector and the catalog seed, not "
            "the variant, so a sham draws the same positions as its positives (injectors.inject).",
            "Fast QC runs each clip through the v8 mirror's limiter as if the engine had produced it, as M1 "
            "does; the Stage 0 observations read the PCM16 that limiter writes.",
        ]
        if population == "N1":
            report["caveats"].append("N1 recordings are 16 kHz and reach 24 kHz through the Kaiser-5 polyphase "
                                     "resampler before Fast QC, as they do before any injector.")
        if injection_set.get("speakerDonors") is not None:
            report["caveats"].append(
                "Speaker donors come from this cohort (speakerDonors in the set): an impostor (IDN-IMPOSTOR) is "
                "another speaker's recording as it is, presented as the source speaker with its own text, its "
                "family that recording's; a donor splice keeps the source's family and text, so its sham (the "
                "source speaker's other utterance) changes the words as much as the positive. v8 has no identity "
                "detector.")
    report["headline"] = headline(report)
    return report


def headline(report: dict) -> list[str]:
    fraction, bound = m1._fraction, m1._bound
    population = clean_population(report)
    key = population.lower()
    n3 = report[key]
    if population == "N3":
        lines = [f"N3 natural takes: v8 alarmed on {fraction(n3['alarm'])} families (flag rate <= "
                 f"{bound(n3['alarm'])}, one-sided CP 95%) and failed {fraction(n3['fail'])}; unlabeled, so FAR <= "
                 f"{n3['unlabeledBound']['farBoundAtPiMax'].get('0.1')} if at most 10% of takes are defective."]
    else:
        lines = [f"{population} human recordings: v8 alarmed on {fraction(n3['alarm'])} families (FAR <= "
                 f"{bound(n3['alarm'])}, one-sided CP 95%) and failed {fraction(n3['fail'])}."]
    if n3["engineRejected"]["takes"]:
        lines.append(f"The engine's mandatory Fast QC refused {n3['engineRejected']['takes']} of these takes "
                     f"(no audio; counted as v8 fails).")
    frequent = sorted(((row[key][row["basis"]]["events"], row["flag"]) for row in report["flags"]
                       if row[key][row["basis"]]["events"]), reverse=True)[:3]
    if frequent:
        lines.append(f"Most frequent {population} flags: "
                     + ", ".join(f"{flag} {events}" for events, flag in frequent) + ".")
    pooled = report["shamsPooled"]
    departing = [row for row in report["shams"] if row["a4"]["overlaps"] is False]
    judged = [row for row in report["shams"] if row["a4"]["overlaps"] is not None]
    lines.append(f"Shams: {fraction(pooled['alarm'])} families alarmed against {fraction(pooled[f'{key}Alarm'])} on "
                 f"{population} (intervals {'overlap' if pooled['overlaps'] else 'do not overlap' if pooled['overlaps'] is False else 'n/a'}); "
                 f"{len(departing)} of {len(judged)} sham rows depart on their target flags (A4)"
                 + (": " + ", ".join(f"{row['injector']} {row['variant']}" for row in departing) if departing else "")
                 + ".")
    severe = [row for row in report["detection"] if row["severity"] == "severe" and row["target"]]
    if severe:
        lines.append("Severe positives, target flags: " + ", ".join(
            f"{row['injector'].split('@')[0]} {fraction(row['target'])} (TPR >= {bound(row['target'], 'lower')})"
            for row in severe) + ".")
    blind = sorted({row["injector"].split("@")[0] for row in report["detection"] if not row["target"]})
    if blind:
        lines.append(f"No v8 detector: {', '.join(blind)} (their alarms are incidental).")
    worst = report["languages"][f"worst{population}Alarm"]
    if worst:
        lines.append(f"Worst language on {population}: {worst['language']} ({worst['events']}/{worst['units']} "
                     f"families, flag rate <= {worst['upper']:.3f}).")
    lines.append({"N3": "Report-only: T1 on N3 qualifies nothing (A2, A5).",
                  "N2": "Report-only: nothing qualifies before a pre-registered plan scores the confirmation "
                        "cohort (A5).",
                  "N1": "Report-only: N1 alone never qualifies a fail (A2)."}[population])
    return lines


def markdown(report: dict) -> str:
    fraction, bound = m1._fraction, m1._bound
    yes = {True: "yes", False: "NO", None: "n/a"}
    population = clean_population(report)
    key = population.lower()
    subject = {"N3": "natural takes", "N2": "N2 codec resyntheses", "N1": "N1 human recordings"}[population]
    out = [
        "<!-- Generated by scripts/audio_qc_calibration_set.py score. Do not edit. -->",
        f"## Audio QC calibration set M2: Fast QC v8 on {subject}, shams and T1 injections",
        "",
        f"Subject `{report['subject']['detector']}` through `{report['subject']['mirror']}` and "
        f"`{report['subject']['observations']}`; calibration `{report['subject']['calibration']}` (A10). "
        "Report-only: nothing here qualifies a bound. Rates are k/n source families with one-sided "
        "Clopper-Pearson 95% bounds.",
        "",
        "### Headline",
        "",
        *[f"- {line}" for line in report["headline"]],
        "",
        "### Populations",
        "",
        "| Population | Clips | Families |", "|---|---|---|",
        *[f"| {name} | {entry['clips']} | {entry['families']} |" for name, entry in report["populations"].items()],
        "",
        f"### Flags: {population} rate and shams (A4)",
        "",
        f"| Flag | Level | {population} | {population} upper | Shams | Shams upper | Overlap | Targeted by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["flags"]:
        n3, sham = row[key][row["basis"]], row["shams"][row["basis"]]
        out.append(f"| {row['flag']} | {row['basis']} | {fraction(n3)} | {bound(n3)} | {fraction(sham)} | "
                   f"{bound(sham)} | {yes[row['overlaps']]} | {', '.join(row['targetedBy']) or 'none'} |")
    clean = report[key]
    if population == "N3":
        bound_row = clean["unlabeledBound"]
        out += ["", f"Any flag on N3: {fraction(clean['alarm'])} (upper {bound(clean['alarm'])}); "
                    f"FAR bound f/(1 - pi_max): " + ", ".join(f"{value} at pi_max {pi}" for pi, value in
                                                            bound_row["farBoundAtPiMax"].items()) + "."]
    else:
        out += ["", f"Any flag on {population}: {fraction(clean['alarm'])} (FAR upper {bound(clean['alarm'])}; "
                    "labeled negatives, so the flag rate bounds FAR directly)."]
    out += ["", f"### Shams (A4, against {population} on the same families)", "",
            f"| Injector | Variant | Families | Not applicable | Alarm | {population} alarm | Overlap | Target flags | "
            f"Sham target | {population} target | A4 overlap |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in report["shams"]:
        a4 = row["a4"]
        out.append(f"| {row['injector']} | {row['variant']} | {row['units']} | {row['notApplicable']} | "
                   f"{fraction(row['alarm'])} | {fraction(row['cleanAlarmSameFamilies'])} | "
                   f"{yes[row['alarmOverlaps']]} | {', '.join(row['targets']) or 'none'} | "
                   f"{fraction(a4.get('sham'))} | {fraction(a4.get('cleanSameFamilies'))} | {yes[a4['overlaps']]} |")
    out += ["", f"### Detection of {'T1 ' if population == 'N3' else ''}injections on {subject} (P1)", "",
            "| Injector | Variant | Severity | Families | Not applicable | Target v8 flags | Detected | TPR lower | "
            "Any alarm | Fail |", "|---|---|---|---|---|---|---|---|---|---|"]
    for row in report["detection"]:
        out.append(f"| {row['injector']} | {row['variant']} | {row['severity']} | {row['units']} | "
                   f"{row['notApplicable']} | {', '.join(row['targets']) or 'none (no v8 detector)'} | "
                   f"{fraction(row['target'])} | {bound(row['target'], 'lower')} | {fraction(row['alarm'])} | "
                   f"{fraction(row['fail'])} |")
    languages = report["languages"]
    out += ["", "### Languages", "",
            f"Simultaneous per-language bounds use Bonferroni confidence {languages['simultaneousConfidence']}.",
            "", f"| Language | {population} families | {population} alarm | Upper | Upper (simultaneous) | Fail | "
                "Sham alarm | Severe positives detected by their target flags |", "|---|---|---|---|---|---|---|---|"]
    for language, row in languages["rows"].items():
        severe = ", ".join(f"{injector.split('@')[0]} {fraction(rate)}"
                           for injector, rate in row["severeTargetDetection"].items()) or "none"
        out.append(f"| {language} | {row[f'{key}Families']} | {fraction(row['alarm'])} | {bound(row['alarm'])} | "
                   f"{bound(row['alarmSimultaneous'])} | {fraction(row['fail'])} | {fraction(row['shamAlarm'])} | "
                   f"{severe} |")
    worst = languages[f"worst{population}Alarm"]
    if worst:
        out += ["", f"Worst stratum on {population}: {worst['language']} (alarm {worst['events']}/{worst['units']}, "
                    f"upper {worst['upper']:.3f})."]
    if languages["worstSevereDetection"]:
        out += ["", "Worst stratum per detected severe injector: " + ", ".join(
            f"{entry['injector'].split('@')[0]} {entry['language']} {entry['events']}/{entry['units']} "
            f"(TPR >= {entry['lower']:.3f})" for entry in languages["worstSevereDetection"]) + "."]
    measures = list(OBSERVATION_MEASURES)
    out += ["", "### Stage 0 observations", "", f"{population} distribution (median / p90 / max):", "",
            f"| Measure | {population} median | {population} p90 | {population} max | Sham median |",
            "|---|---|---|---|---|"]
    for name in measures:
        entry = report["observations"][name]
        n3, sham = entry[population] or {}, entry["S"] or {}
        out.append(f"| {name} | {n3.get('median', 'n/a')} | {n3.get('p90', 'n/a')} | {n3.get('max', 'n/a')} | "
                   f"{sham.get('median', 'n/a')} |")
    out += ["", "Median paired change (positive minus its source take):", "",
            "| Injector | Variant | " + " | ".join(measures) + " |", "|---|---|" + "---|" * len(measures)]
    for row in report["detection"]:
        values = [row["observationMedianDelta"].get(name) for name in measures]
        out.append(f"| {row['injector']} | {row['variant']} | "
                   + " | ".join("n/a" if value is None else f"{value:.3g}" for value in values) + " |")
    out += ["", "### Plan and not-applicable variants", "",
            "| Injector | Severity | Status | Variant | Catalog variant needs | Skips on takes |",
            "|---|---|---|---|---|---|"]
    for row in report["plan"]:
        skipped = (report["notApplicable"].get(row["injector"], {}).get("byVariant", {})
                   .get(row.get("variant") or "", {}))
        reasons = "; ".join(f"{count}: {reason}" for reason, count in skipped.items()) or "none"
        needs = ", ".join(row["catalogNeeds"]) or "nothing"
        out.append(f"| {row['injector']} | {row['severity']} | {row['status']} | {row.get('variant') or 'n/a'} | "
                   f"{needs} | {reasons} |")
    swap = report.get("identitySwap") or {}
    if swap:
        pairs = f" ({swap.get('donorPairs', 0)} donor pairs in the manifest)" if "donorPairs" in swap else ""
        out += ["", f"Identity swap ({swap.get('injector')}): {swap.get('status')}; {swap.get('reason')}{pairs}."]
    out += ["", "### Caveats", "", *[f"- {caveat}" for caveat in report["caveats"]], "",
            f"Inputs: takes manifest `{report['inputs']['takesManifestSHA256'][:12]}`, injection set entries "
            f"`{(report['inputs']['entriesSHA256'] or 'none')[:12]}`, "
            f"measurements `{report['inputs']['measurementsSHA256'][:12]}`, "
            f"policy `{report['inputs']['policySHA256'][:12]}`, catalog v{report['inputs']['catalogVersion']}, "
            f"NumPy {report['inputs']['numpy']}.", ""]
    return "\n".join(out)


def run_score(takes_path: Path, set_path: Path | None, output: Path, *, jobs: int) -> dict:
    """Score the clean takes (N3, or N1/N2 for a cohort) and, with a set, its shams and positives."""
    manifest, manifest_sha256 = load_takes(takes_path)
    population = population_of(manifest)
    injection_set: dict = {"entries": [], "entriesSHA256": None}
    if set_path is not None:
        injection_set = load_set(set_path)
        if injection_set.get("sourceManifest", {}).get("sha256") != manifest_sha256:
            raise CalibrationError("the injection set was built from another takes manifest")
        if json_digest(injection_set["entries"]) != injection_set.get("entriesSHA256"):
            raise CalibrationError("the injection set's entries differ from its entriesSHA256")
    takes = {take["takeID"]: take for take in generated_takes(manifest)}
    tasks = []
    for take_id, take in takes.items():
        task = {"clipID": take_id, "wav": str(take_wav(takes_path, take)), "wavSHA256": take["wavSHA256"],
                "text": take["text"], "meta": _meta(take, take_id, population, None),
                **generation_evidence(take, own_generation=True)}
        if source_rate(take) != recordings.ENGINE_SAMPLE_RATE:
            task["sourceRate"] = source_rate(take)
        if take_seams(take):
            task["seams"] = list(take_seams(take))
        tasks.append(task)
    for entry in injection_set["entries"]:
        take = takes.get(entry.get("sourceTakeID"))
        if take is None:
            raise CalibrationError(f"{entry.get('takeID')}: its source take is not a generated take")
        injection = entry["injection"]
        # A T1 PCM construction changed the audio after generation; a byte-copied donor, a T2 replay or a T3
        # knob take is a generation's own output (an entry copies its source's or donor's fields).
        own = injection.get("mechanism") not in (None, injectors.MECHANISM)
        task = {"clipID": entry["takeID"], "wav": str(_relative_path(set_path.parent, entry["wavPath"],
                                                                      f"{entry['takeID']}: wavPath")),
                "wavSHA256": entry["wavSHA256"], "text": presented_text(entry, takes),
                "meta": _meta(take, entry["takeID"], injection["population"], injection, family=entry.get("family")),
                **generation_evidence(entry, own_generation=own)}
        if entry.get("seamSamples"):
            task["seams"] = list(entry["seamSamples"])
        tasks.append(task)
    rejected = rejected_takes(manifest)
    log(f"score: {len(takes)} {population} takes ({len(rejected)} engine-rejected, no audio) and "
        f"{len(injection_set['entries'])} injected clips, {jobs} jobs")
    records: list[dict] = []

    def measured() -> Iterator[dict]:
        for measurement in parallel(_score_clip, tasks, jobs, "score"):
            records.append(_reduced(measurement))
            yield measurement

    # When measuring started (UTC), outside clipsSHA256: a confirmation's measurements must postdate its
    # committed plan (A5), as its panel bundles must (audio_qc_detector_calibration.py).
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1e6):06d}Z"
    head = {"schemaVersion": 1, "kind": MEASUREMENTS_KIND, "generator": GENERATOR,
            "privacy": "ids and digests only: no text, transcript or path", "startedAt": started_at,
            "takesManifestSHA256": manifest_sha256, "entriesSHA256": injection_set["entriesSHA256"],
            "subject": {"detector": m1.SUBJECT, "mirror": audio_qc.FASTQC_V8_MIRROR,
                        "observations": audio_qc_observations.OBSERVATIONS_MIRROR}}
    measurements_sha256 = _write_streamed(output / "measurements.json", head, "clips", measured(),
                                          lambda digest: {"clipsSHA256": digest, "clipCount": len(records)})
    for take in rejected:
        records.append({**{key: value for key, value in _meta(take, take["takeID"], population, None).items()
                           if key in ("clipID", "population", "family", "sourceTakeID", "language")},
                        "injector": None, "injectorID": None, "variant": None, "severity": None,
                        "verdict": "fail", "engineRejected": True,
                        "flagLevels": rejection_levels(take["rejection"]["audioQCFlags"]),
                        "observations": {name: None for name in OBSERVATION_MEASURES}})
    inputs = {"takesManifestSHA256": manifest_sha256,
              "injectionSetSHA256": None if set_path is None else file_sha256(set_path),
              "entriesSHA256": injection_set["entriesSHA256"], "measurementsSHA256": measurements_sha256,
              "policySHA256": policy_module.policy_digest(),
              # The set's own catalog version (a set built by other code keeps its version).
              "catalogVersion": injection_set.get("catalogVersion", injectors.CATALOG_VERSION),
              "catalogSeed": injection_set.get("catalogSeed"), "numpy": np.__version__}
    report = build_report(records, inputs=inputs, injection_set=injection_set, population=population)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                        encoding="utf-8")
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _classes(value: str) -> tuple[str, ...]:
    classes = tuple(sorted({item.strip().upper() for item in value.split(",") if item.strip()}))
    if not classes or not set(classes) <= set("ABCDEFGHIJ"):
        raise argparse.ArgumentTypeError("classes are letters A-J, comma-separated")
    return classes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    inject = commands.add_parser("inject", help="build the injection set from natural takes")
    inject.add_argument("--takes", type=Path, required=True)
    inject.add_argument("--output", type=Path, required=True)
    inject.add_argument("--catalog-seed", type=int, default=DEFAULT_CATALOG_SEED)
    inject.add_argument("--classes", type=_classes, default=None,
                        help="defect classes to inject (default A,C,F; A,B,C,D,F on an N2 cohort)")
    inject.add_argument("--alignments", type=Path,
                        help="an `alignments` export for this manifest: word-level variants on its usable takes")
    inject.add_argument("--sample-per-cell", type=int, default=None,
                        help="source families per (injector, severity) cell, stratified by language; 0 is every "
                             "source (default 150 on an N2 cohort, every source otherwise)")
    inject.add_argument("--sample-seed", type=int, default=DEFAULT_SAMPLE_SEED,
                        help=f"seed of the family draw and the language-swap donors (default {DEFAULT_SAMPLE_SEED})")
    inject.add_argument("--embed-text", action="store_true", default=None,
                        help="carry each entry's text on an N3 set too (N1 and N2 sets always carry it)")
    verify = commands.add_parser("verify", help="replay every recipe and compare output digests")
    verify.add_argument("--set", type=Path, required=True)
    verify.add_argument("--takes", type=Path, required=True)
    verify.add_argument("--alignments", type=Path, help="the alignments the set was built with, if any")
    score = commands.add_parser("score", help="run Fast QC v8 and Stage 0 over the clean takes, shams and positives")
    score.add_argument("--takes", type=Path, required=True)
    score.add_argument("--set", type=Path, help="the injection set (omit it to score the clean takes alone)")
    score.add_argument("--output", type=Path, required=True)
    alignments = commands.add_parser("alignments", help="export the forced aligner's word intervals from L1")
    alignments.add_argument("--takes", type=Path, required=True, help="the cohort manifest the panel ran over")
    alignments.add_argument("--bundle", type=Path, required=True, help="the panel's private bundle directory")
    alignments.add_argument("--output", type=Path, required=True)
    alignments.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT,
                            help="the orchestrator's analysis cache (default build/cache/delivery-analysis or "
                                 "$QVOICE_DELIVERY_ANALYSIS_CACHE)")
    raw_outputs = commands.add_parser("raw-outputs", help="export a panel judge's raw outputs (pitch track, speaker "
                                                          "windows) from L1")
    raw_outputs.add_argument("--takes", type=Path, required=True,
                             help="the cohort manifest or injection set the panel ran over")
    raw_outputs.add_argument("--bundle", type=Path, required=True, help="the panel's private bundle directory")
    raw_outputs.add_argument("--judge", required=True, help="pitch.pyin@1 or speaker.campplus-voxceleb@1")
    raw_outputs.add_argument("--output", type=Path, required=True)
    raw_outputs.add_argument("--cache-root", type=Path, required=True,
                             help="the panel's own cache root (a confirmation panel's new, empty one), never a "
                                  "shared cache that may hold entries from before its plan")
    for command in (inject, verify, score):
        command.add_argument("--jobs", type=int, default=default_jobs(),
                             help="worker processes (default: half the cores)")
    args = parser.parse_args(argv)
    if getattr(args, "jobs", 1) < 1:
        parser.error("--jobs must be positive")
    try:
        if args.command == "alignments":
            with shared_analysis_lock():
                export = export_alignments(args.takes, args.bundle, args.output, cache_root=args.cache_root)
            print(json.dumps(export["counts"], sort_keys=True))
            return 0
        if args.command == "raw-outputs":
            with shared_analysis_lock():
                export = export_raw_outputs(args.takes, args.bundle, args.output, judge_id=args.judge,
                                            cache_root=args.cache_root)
            print(json.dumps(export["counts"], sort_keys=True))
            return 0
        if args.command == "inject":
            if args.catalog_seed < 0:
                parser.error("--catalog-seed must be non-negative")
            if args.sample_per_cell is not None and args.sample_per_cell < 0:
                parser.error("--sample-per-cell must be non-negative")
            run_inject(args.takes, args.output, catalog_seed=args.catalog_seed, classes=args.classes, jobs=args.jobs,
                       alignments_path=args.alignments, sample_per_cell=args.sample_per_cell,
                       sample_seed=args.sample_seed, embed_text=args.embed_text)
            return 0
        if args.command == "verify":
            result = run_verify(args.set, args.takes, jobs=args.jobs, alignments_path=args.alignments)
            for clip, reason in result["failures"][:20]:
                print(f"FAIL {clip}: {reason}", file=sys.stderr)
            status = "PASS" if result["verified"] else "FAIL"
            print(f"verify: {status}: {result['entries']} entries from {result['sources']} source takes, "
                  f"{len(result['failures'])} failures")
            return 0 if result["verified"] else 1
        report = run_score(args.takes, args.set, args.output, jobs=args.jobs)
        for line in report["headline"]:
            print(f"- {line}")
        print(f"wrote {m1._display(args.output / 'report.json')} and {m1._display(args.output / 'report.md')}")
        return 0
    except (CalibrationError, recordings.RecordingError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
