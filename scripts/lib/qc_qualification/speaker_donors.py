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

Voice donors (SEAM-VOICE's take-voice-* variants, class J). A generated
long-form take (N3) names no corpus speaker, but the voice it was generated
with is its speaker label (lead decision 2026-09-30): a Built-in speaker by id,
a Voice Design brief by its id (a digest of its text when it has none), a clone
reference by its corpus speaker (`voice_label`). Its gender is the one the take
plan records: `speakerGenders` for a Built-in speaker, a brief's `gender` where
the policy declares one, a clone reference's corpus label; otherwise none.
`VoicePool` holds the long-form takes of one manifest (so of one split) by
language: `other-voice` holds the takes of another voice whose gender is not
known to differ (both recorded and equal, or either unrecorded), `same-voice`
the source voice's other takes. The choice is the rule above, over these
relations. A recorded voice label names a Built-in speaker or a brief by its
policy id and a clone reference speaker only by a digest.
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
VOICE_RELATIONS = ("other-voice", "same-voice")
VOICE_RELATION_DESCRIPTIONS = {
    "other-voice": "long-form take of another voice of the same language (and gender, where both record one)",
    "same-voice": "other long-form take of the same voice",
}
NO_VOICE = "the take records no voice identity (a Built-in speaker, a Voice Design brief or a clone reference)"
VOICE_GENDERS = frozenset({"male", "female"})
VOICE_LABEL_RULE = ("a generated long-form take's voice is its speaker label: a Built-in speaker by id, a Voice "
                    "Design brief by its id, a clone reference by its corpus speaker (recorded as a digest); its "
                    "gender is the take plan's speakerGenders entry, a brief's declared gender or a clone "
                    "reference's corpus label, else unrecorded")
VOICE_POOL_RULE = ("this manifest's long-form takes (one split) of the source's language: another voice whose "
                   "gender is not known to differ (both recorded and equal, or either unrecorded) for a positive, "
                   "another take of the source's voice for the sham")
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
        return _choose(self, sources, seed=seed, key=key, relations=tuple(relations))


def voice_label(take: Mapping, *, speaker_genders: Mapping[str, str],
                brief_genders: Mapping[str, str]) -> dict | None:
    """A generated take's voice as its speaker label, or None: its `identity` (kept in memory) and the `label` a
    set records (a Built-in speaker or a brief by its policy id, a clone reference speaker by a digest)."""
    voice = take.get("voice") if isinstance(take.get("voice"), Mapping) else {}
    kind = voice.get("kind")
    identity = label = gender = None
    if kind == "builtin" and isinstance(voice.get("id"), str) and voice["id"]:
        identity, label = f"builtin:{voice['id']}", {"kind": "builtin", "id": voice["id"]}
        gender = speaker_genders.get(voice["id"])
    elif kind == "design" and isinstance(voice.get("briefID"), str) and voice["briefID"]:
        identity, label = f"design:{voice['briefID']}", {"kind": "design", "briefID": voice["briefID"]}
        gender = brief_genders.get(voice["briefID"])
    elif kind == "design" and isinstance(voice.get("brief"), str) and voice["brief"]:
        digest = hashlib.sha256(voice["brief"].encode("utf-8")).hexdigest()
        identity, label = f"design-text:{digest}", {"kind": "design", "briefSHA256": digest}
    elif kind == "clone" and all(isinstance(voice.get(field), str) and voice[field] for field in ("source", "speaker")):
        digest = hashlib.sha256(f"{voice['source']}|{voice['speaker']}".encode("utf-8")).hexdigest()
        identity, label = f"clone:{digest}", {"kind": "clone", "speakerSHA256": digest}
        gender = voice.get("gender")
    if identity is None:
        return None
    gender = gender if gender in VOICE_GENDERS else None
    return {"identity": identity, "gender": gender, "label": {**label, "gender": gender}}


def _genders_agree(first: str | None, second: str | None) -> bool:
    """Not known to differ: both recorded and equal, or either unrecorded."""
    return first is None or second is None or first == second


class VoicePool:
    """The long-form takes of one manifest labelled by their voice, grouped by language (SEAM-VOICE take-voice-*).

    `labels`: takeID -> `voice_label` (None: no voice identity); `eligible`:
    the takeIDs a donor may be (the takes that declare seams); None admits
    every labelled take.
    """

    def __init__(self, takes: Iterable[Mapping], labels: Mapping[str, dict | None], *,
                 eligible: set[str] | None = None) -> None:
        self.takes = list(takes)
        self.by_id = {take["takeID"]: take for take in self.takes}
        self.labels = {take_id: label for take_id, label in labels.items() if label is not None}
        self.groups: dict[object, list[Mapping]] = {}
        for take in self.takes:
            if take["takeID"] in self.labels and (eligible is None or take["takeID"] in eligible):
                self.groups.setdefault(take.get("language"), []).append(take)

    def candidates(self, take: Mapping) -> dict[str, list[Mapping]]:
        """The takes that may stand in for `take`, by relation (never `take` itself)."""
        label = self.labels.get(take["takeID"])
        if label is None:
            return {relation: [] for relation in VOICE_RELATIONS}
        others = [other for other in self.groups.get(take.get("language"), ()) if other["takeID"] != take["takeID"]]
        voices = {other["takeID"]: self.labels[other["takeID"]] for other in others}
        return {"other-voice": [other for other in others if voices[other["takeID"]]["identity"] != label["identity"]
                                and _genders_agree(voices[other["takeID"]]["gender"], label["gender"])],
                "same-voice": [other for other in others if voices[other["takeID"]]["identity"] == label["identity"]]}

    def issue(self, take: Mapping, relations: Iterable[str] = VOICE_RELATIONS) -> str | None:
        """Why `take` gets no voice donor for these relations, or None."""
        if take["takeID"] not in self.labels:
            return NO_VOICE
        found = self.candidates(take)
        missing = [relation for relation in relations if not found[relation]]
        if not missing:
            return None
        return "the manifest holds no " + " and no ".join(VOICE_RELATION_DESCRIPTIONS[relation]
                                                          for relation in missing)

    def sources(self, relations: Iterable[str] = VOICE_RELATIONS) -> list[Mapping]:
        """The takes with a donor for every relation, in manifest order."""
        relations = tuple(relations)
        return [take for take in self.takes if self.issue(take, relations) is None]

    def choose(self, sources: Iterable[str], *, seed: int, key: str,
               relations: Iterable[str] = VOICE_RELATIONS) -> dict[str, dict[str, str]]:
        """Source takeID -> {relation: donor takeID}, drawn as `DonorPool.choose` draws."""
        return _choose(self, sources, seed=seed, key=key, relations=tuple(relations))


def _choose(pool: DonorPool | VoicePool, sources: Iterable[str], *, seed: int, key: str,
            relations: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Per source, per relation: the lowest-ranked candidate no earlier source drew, else the lowest of all."""
    used: dict[str, set[str]] = {relation: set() for relation in relations}
    chosen: dict[str, dict[str, str]] = {}
    for source_id in sources:
        found = pool.candidates(pool.by_id[source_id])
        if not all(found[relation] for relation in relations):
            continue
        picks = {}
        for relation in relations:
            ranked = sorted(found[relation], key=lambda other: _rank(seed, key, relation, source_id, other["takeID"]))
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
