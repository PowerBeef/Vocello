"""Wrong-language positives from FLEURS parallel text (audit section 5.2, LNG-SWAP, class D).

FLoRes sentence ids are shared across languages, so one sentence exists as a
recording in several languages (`scriptID` `flores-<id>`). For a source
recording of language L1 and sentence s:

- the positive (`severe`) is another cohort recording of s in a language L2
  other than L1 (another recording, so another speaker), presented with the
  expected language L1 and the source's L1 text;
- its sham is another L1 recording of s (a same-language swap), presented the
  same way.

Both are a byte copy of the donor's audio file, bound by digest, so `verify`
replays them by digest and by the donor choice. The pool is
the cohort manifest being injected, and only N2 (24 kHz) cohorts qualify: one
manifest is one split, so a confirmation cohort draws only confirmation audio
(FLoRes dev and test sentences are disjoint besides). A source is eligible only
when its sentence has both another L1 recording and a recording in another
language.

Families. A clip's `family` is its audio's own family, the donor recording's:
the unit of independence is the audio, so two sources that draw one donor
count once, and a donor recording's clean N2 take shares its family. The
pairing stays in the recipe (`sourceFamily`, the entry's `sourceTakeID`), so a
source family's sham and positive can still be paired. The positive's family
therefore differs from its sham's: for LNG-SWAP a cell and its sham share their
source families, not their audio families.

Donor choice. For each chosen source in manifest order, the candidate with the
lowest SHA-256(`CHOICE_SCHEMA|seed|variant|source takeID|candidate takeID`)
among those no earlier source drew for that variant, else among all, so donors
repeat only when a sentence runs out of them.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Iterable, Mapping

INJECTOR_ID = "LNG-SWAP"
VERSION = 1
KEY = f"{INJECTOR_ID}@{VERSION}"
MECHANISM = "T1-parallel-corpus"
CLASSES = ("D",)
DEFECT = "wrong language"
CHOICE_SCHEMA = "vocello.audioqc.language-swap-choice/1"
SCRIPT_ID = re.compile(r"flores-[0-9]+\Z")
# The variants in plan order: the sham first, like the catalog's sweep.
VARIANTS = {
    "sham": {"swap": "same-language", "match": "scriptID", "pool": "cohort manifest"},
    "severe": {"swap": "other-language", "match": "scriptID", "pool": "cohort manifest"},
}
DESCRIPTION = ("The source's FLoRes sentence read by another recording in another language (severe) or in the "
               "same language (sham), presented with the source's language and text; the donor's audio as is.")


def describe() -> dict:
    return {"injector": KEY, "defect": DEFECT, "classes": list(CLASSES), "mechanism": MECHANISM,
            "description": DESCRIPTION, "choice": f"lowest SHA-256('{CHOICE_SCHEMA}|<seed>|<variant>|<source takeID>|"
                                                  "<candidate takeID>') among donors no earlier source drew for "
                                                  "that variant, else among all; sources in manifest order",
            "variants": [{"name": name, "severity": name, "parameters": dict(parameters)}
                         for name, parameters in VARIANTS.items()]}


def _candidates(takes: Iterable[Mapping]) -> dict[str, list[Mapping]]:
    by_script: dict[str, list[Mapping]] = {}
    for take in takes:
        script = take.get("scriptID")
        if isinstance(script, str) and SCRIPT_ID.fullmatch(script):
            by_script.setdefault(script, []).append(take)
    return by_script


def donors_for(take: Mapping, by_script: Mapping[str, list[Mapping]]) -> dict[str, list[Mapping]]:
    """The takes that may stand in for `take`: same sentence, another recording, by variant."""
    others = [other for other in by_script.get(str(take.get("scriptID")), ())
              if other["takeID"] != take["takeID"]]
    return {"sham": [other for other in others if other.get("language") == take.get("language")],
            "severe": [other for other in others if other.get("language") != take.get("language")]}


def eligible_sources(takes: Iterable[Mapping]) -> list[Mapping]:
    """Sources with both a same-language and an other-language recording of their sentence."""
    takes = list(takes)
    by_script = _candidates(takes)
    return [take for take in takes if all(donors_for(take, by_script).values())]


def _rank(seed: int, variant: str, source: str, candidate: str) -> str:
    return hashlib.sha256("|".join((CHOICE_SCHEMA, str(seed), variant, source, candidate)).encode("utf-8")).hexdigest()


def choose_donors(takes: Iterable[Mapping], sources: Iterable[str], *, seed: int) -> dict[str, dict[str, str]]:
    """Source takeID -> {variant: donor takeID}, deterministic in the manifest and the seed."""
    takes = list(takes)
    by_script = _candidates(takes)
    by_id = {take["takeID"]: take for take in takes}
    used: dict[str, set[str]] = {variant: set() for variant in VARIANTS}
    chosen: dict[str, dict[str, str]] = {}
    for source_id in sources:
        source = by_id[source_id]
        pools = donors_for(source, by_script)
        if not all(pools.values()):
            continue
        picks = {}
        for variant in VARIANTS:
            ranked = sorted(pools[variant], key=lambda other: _rank(seed, variant, source_id, other["takeID"]))
            fresh = [other for other in ranked if other["takeID"] not in used[variant]]
            donor = (fresh or ranked)[0]
            used[variant].add(donor["takeID"])
            picks[variant] = donor["takeID"]
        chosen[source_id] = picks
    return chosen


def copy_as_is(source: Path, destination: Path) -> None:
    """Place a byte copy of the donor's file at `destination` (atomically).

    A copy, never a hard link: a link would share the cohort's own file, so an
    in-place edit of a set clip would rewrite the source audio. The swaps are a
    few hundred clips, so the copy costs little.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def injection(*, variant: str, source: Mapping, donor: Mapping, seed: int, source_pcm_sha256: str,
              output_pcm_sha256: str, frames: int) -> dict:
    """The recipe of one swap: what was presented, whose audio it is and both source digests."""
    positive = variant == "severe"
    return {
        "mechanism": MECHANISM, "injector": KEY, "injectorID": INJECTOR_ID, "injectorVersion": VERSION,
        "classes": list(CLASSES), "variant": variant, "severity": variant, "population": "P1" if positive else "S",
        "parameters": dict(VARIANTS[variant]), "seed": seed, "scriptID": source["scriptID"],
        "expectedLanguage": source["language"], "audioLanguage": donor["language"],
        "sourceFamily": source["family"], "donorTakeID": donor["takeID"], "donorFamily": donor["family"],
        "sourceWAVSHA256": source["wavSHA256"], "donorWAVSHA256": donor["wavSHA256"],
        "sourcePCMSHA256": source_pcm_sha256, "outputPCMSHA256": output_pcm_sha256,
        "labels": [{"kind": "wrong-language", "startSample": 0, "endSample": frames,
                    "language": donor["language"]}] if positive else [],
    }
