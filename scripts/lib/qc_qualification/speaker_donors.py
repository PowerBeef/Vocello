"""Speaker-labelled donors for class E and J positives (audit sections 4.3, 5.2 and 5.7).

A speaker-labelled cohort take names its `speaker` and `gender` (a corpus with
published speaker ids, resynthesized to N2 like FLEURS). Two constructions draw a
second recording of the same cohort manifest, so of the same split:

- IDN-IMPOSTOR (`T1-parallel-corpus`): the positive (`severe`) is a recording of
  another speaker of the source's language and gender, presented as the source
  speaker (`speaker`) against the source take as its reference clip; its sham is
  another utterance of the source speaker, presented the same way. The clip is a
  byte copy of the donor's file carrying the donor's own text, so only the
  speaker is wrong. Its family is the donor recording's, as a language swap's is.
- The donor splices of the T1 catalog (`injectors`: the take-* variants of
  IDN-SWAP, IDN-ONSET and SEAM-VOICE): the donor's words spliced into the source
  at aligned word boundaries. The clip's family stays the source's.

Pools: same language and gender, a speaker label on both takes; `other-speaker`
holds the other speakers' takes, `same-speaker` the source speaker's other
takes. A splice needs the donor's word intervals, so its pool keeps only takes
whose alignment is usable (`eligible`). A source without a speaker label, or with
an empty pool, gets no donor, and its variants are not applicable with that
reason.

Donor choice: for each source in manifest order, the candidate with the lowest
SHA-256(`CHOICE_SCHEMA|seed|injector|relation|source takeID|candidate takeID`)
among those no earlier source drew for that injector and relation, else among
all, so donors repeat only when a pool runs out (as `language_swap` chooses).
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping

IMPOSTOR_ID = "IDN-IMPOSTOR"
IMPOSTOR_VERSION = 1
IMPOSTOR_KEY = f"{IMPOSTOR_ID}@{IMPOSTOR_VERSION}"
MECHANISM = "T1-parallel-corpus"
CLASSES = ("E",)
DEFECT = "impostor speaker"
CHOICE_SCHEMA = "vocello.audioqc.speaker-donor-choice/1"
RELATIONS = ("other-speaker", "same-speaker")
RELATION_DESCRIPTIONS = {
    "other-speaker": "recording of another speaker of the same language and gender",
    "same-speaker": "other utterance of the same speaker",
}
NO_LABEL = "the take carries no speaker label (speaker and gender)"
# The variants in plan order: the sham first, like the catalog's sweep.
IMPOSTOR_VARIANTS = {
    "sham": {"donor": "same-speaker", "reference": "source take", "pool": "cohort manifest"},
    "severe": {"donor": "other-speaker", "reference": "source take", "pool": "cohort manifest"},
}
IMPOSTOR_DESCRIPTION = ("Another speaker's recording of the source's language and gender (severe), or another "
                        "utterance of the source speaker (sham), presented as the source speaker against the source "
                        "take as its reference clip; the donor's audio as is, with its own text.")
CHOICE_RULE = (f"lowest SHA-256('{CHOICE_SCHEMA}|<seed>|<injector@version>|<relation>|<source takeID>|"
               "<candidate takeID>') among donors no earlier source drew for that injector and relation, else among "
               "all; sources in manifest order")


def labelled(take: Mapping) -> bool:
    """A take names its speaker and gender."""
    return all(isinstance(take.get(field), str) and take[field] for field in ("speaker", "gender"))


class DonorPool:
    """The speaker-labelled takes of one cohort manifest, grouped by language and gender.

    `eligible`: the takeIDs a donor may be (a splice's usable alignments); None
    admits every labelled take.
    """

    def __init__(self, takes: Iterable[Mapping], *, eligible: set[str] | None = None) -> None:
        self.takes = list(takes)
        self.by_id = {take["takeID"]: take for take in self.takes}
        self.groups: dict[tuple, list[Mapping]] = {}
        for take in self.takes:
            if labelled(take) and (eligible is None or take["takeID"] in eligible):
                self.groups.setdefault((take.get("language"), take["gender"]), []).append(take)

    def candidates(self, take: Mapping) -> dict[str, list[Mapping]]:
        """The takes that may stand in for `take`, by relation (never `take` itself)."""
        if not labelled(take):
            return {relation: [] for relation in RELATIONS}
        others = [other for other in self.groups.get((take.get("language"), take["gender"]), ())
                  if other["takeID"] != take["takeID"]]
        return {"other-speaker": [other for other in others if other["speaker"] != take["speaker"]],
                "same-speaker": [other for other in others if other["speaker"] == take["speaker"]]}

    def issue(self, take: Mapping, relations: Iterable[str] = RELATIONS) -> str | None:
        """Why `take` gets no donor for these relations, or None."""
        if not labelled(take):
            return NO_LABEL
        found = self.candidates(take)
        missing = [relation for relation in relations if not found[relation]]
        if not missing:
            return None
        return "the cohort holds no " + " and no ".join(RELATION_DESCRIPTIONS[relation] for relation in missing)

    def sources(self, relations: Iterable[str] = RELATIONS) -> list[Mapping]:
        """The takes with a donor for every relation, in manifest order."""
        relations = tuple(relations)
        return [take for take in self.takes if self.issue(take, relations) is None]

    def choose(self, sources: Iterable[str], *, seed: int, key: str,
               relations: Iterable[str] = RELATIONS) -> dict[str, dict[str, str]]:
        """Source takeID -> {relation: donor takeID}, deterministic in the manifest, the seed and the key."""
        relations = tuple(relations)
        used: dict[str, set[str]] = {relation: set() for relation in relations}
        chosen: dict[str, dict[str, str]] = {}
        for source_id in sources:
            source = self.by_id[source_id]
            found = self.candidates(source)
            if not all(found[relation] for relation in relations):
                continue
            picks = {}
            for relation in relations:
                ranked = sorted(found[relation],
                                key=lambda other: _rank(seed, key, relation, source_id, other["takeID"]))
                fresh = [other for other in ranked if other["takeID"] not in used[relation]]
                donor = (fresh or ranked)[0]
                used[relation].add(donor["takeID"])
                picks[relation] = donor["takeID"]
            chosen[source_id] = picks
        return chosen


def _rank(seed: int, key: str, relation: str, source: str, candidate: str) -> str:
    material = "|".join((CHOICE_SCHEMA, str(seed), key, relation, source, candidate))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def describe_impostor() -> dict:
    return {"injector": IMPOSTOR_KEY, "defect": DEFECT, "classes": list(CLASSES), "mechanism": MECHANISM,
            "description": IMPOSTOR_DESCRIPTION, "choice": CHOICE_RULE,
            "variants": [{"name": name, "severity": name, "parameters": dict(parameters)}
                         for name, parameters in IMPOSTOR_VARIANTS.items()]}


def impostor_injection(*, variant: str, source: Mapping, donor: Mapping, seed: int, source_pcm_sha256: str,
                       output_pcm_sha256: str, frames: int) -> dict:
    """The recipe of one impostor clip: whom it is presented as, whose audio it is and both digests."""
    positive = variant == "severe"
    return {
        "mechanism": MECHANISM, "injector": IMPOSTOR_KEY, "injectorID": IMPOSTOR_ID,
        "injectorVersion": IMPOSTOR_VERSION, "classes": list(CLASSES), "variant": variant, "severity": variant,
        "population": "P1" if positive else "S", "parameters": dict(IMPOSTOR_VARIANTS[variant]), "seed": seed,
        "presentedSpeaker": source["speaker"], "audioSpeaker": donor["speaker"], "gender": source["gender"],
        "referenceTakeID": source["takeID"], "sourceFamily": source["family"],
        "donorTakeID": donor["takeID"], "donorFamily": donor["family"],
        "sourceWAVSHA256": source["wavSHA256"], "donorWAVSHA256": donor["wavSHA256"],
        "sourcePCMSHA256": source_pcm_sha256, "outputPCMSHA256": output_pcm_sha256,
        "labels": [{"kind": "impostor", "startSample": 0, "endSample": frames,
                    "speaker": donor["speaker"]}] if positive else [],
    }
