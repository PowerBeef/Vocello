"""Phones: G2P, IPA normalization, phone alignment, CTC goodness of pronunciation, stutter features.

Word-level ASR turns a stutter into plausible words ("les branches des vieux ormes" heard as "les
proches des vieux hommes"). This module compares what a phone recognizer with no external language
model or lexicon heard (ZIPA, and wav2vec2-espeak as the second recognizer) with what the script
says, phone by phone. A recognizer still carries the habits of its training data (ZIPA prints French
silent letters on native speech), so an insertion counts only when both recognizers make it
(`agreement`):

1. `g2p(text, language)`: the expected phones, from espeak-ng (decision D5), cached under
   `build/cache/qc/results/g2p/`. The onnx runtime ships espeak-ng through the `espeakng-loader`
   wheel and calls it in-process; the G2P job (`python -m qc.runners.espeak_g2p --job job.json`,
   or `python -m qc.phones --g2p-job job.json`) fills the cache there, so the repository's python
   only reads it.
2. `segment_ipa` and `normalize`: split IPA into phones and map espeak, ZIPA and wav2vec2-espeak IPA
   onto one broad inventory (no stress, length, ties or tones; affricates and diphthongs as their
   parts; one rhotic unless `keep_rhotics`, the flap ɾ among them only in Spanish, Italian and
   Portuguese).
3. `ctc_greedy`: recognized phones with frame times from a CTC model's log-posteriors.
4. `align(expected, recognized, optional=)`: weighted edit distance whose substitution cost is the
   PanPhon feature distance (MIT data, read from its pinned CSV files; no pip package). An optional
   expected phone (a French liaison consonant, a final schwa) costs nothing to leave out.
5. `gop(logprobs, vocab, expected)`: segmentation-free goodness of pronunciation per expected phone.
6. `stutter_features(ops)`: deletion rate, repeated-syllable runs, insertion bursts, low-GOP spans.

`compare` runs 2-6 for one take and one recognizer; `agreement` keeps the insertions both
recognizers made. Standard library plus NumPy only.

Known G2P limits (espeak-ng): Japanese kanji have no readings (kana only), Chinese polyphones take
one reading, and Korean uses espeak's rule set. Treat ja, zh and ko phone results as report-only.
"""

from __future__ import annotations

import csv
import functools
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
# The G2P registry entry pins PanPhon's feature CSVs as its files, so they land here.
G2P_MODEL_ID = "g2p.espeak-ng"
G2P_MODEL_DIR = REPO_ROOT / "build/cache/qc/models" / G2P_MODEL_ID
PANPHON_TABLE = "panphon/data/ipa_all.csv"
# Repeat-run near-identity per distance scale (see stutter_features).
COARSE_NEAR = 0.25
PANPHON_NEAR = 0.06
PANPHON_WEIGHTS = "panphon/data/feature_weights.csv"

LANGUAGES = (
    "chinese", "english", "french", "german", "italian",
    "japanese", "korean", "portuguese", "russian", "spanish",
)
# espeak-ng 1.52 voice names (matched against each voice identifier's last component).
ESPEAK_VOICES = {
    "chinese": "cmn", "english": "en-us", "french": "fr", "german": "de", "italian": "it",
    "japanese": "ja", "korean": "ko", "portuguese": "pt-br", "russian": "ru", "spanish": "es",
}

# --------------------------------------------------------------------------------------------
# IPA segmentation and normalization
# --------------------------------------------------------------------------------------------

STRESS = frozenset("ˈˌ")
LENGTH = frozenset("ːˑ")
TIES = frozenset("͜͡‿")
TONES = frozenset("˥˦˧˨˩¹²³⁴⁵0123456789")
# Word and syllable boundaries, recognizer boundary tokens and stray ASCII from espeak's
# X-SAMPA-flavoured labels in the wav2vec2 vocabulary ("s.", "t[", "s^", "??").
SEPARATORS = frozenset(" \t\r\n.|▁_-,;!?\"'()[]^…·")
# Diacritics the broad inventory keeps: nasal, ejective, aspirated, labialized, palatalized.
KEPT_MARKS = "̃ʼʰʷʲ"
RHOTICS = frozenset("rɾɹʁʀɻɽɺ")
# The flap ɾ is a rhotic only where it is an /r/ (Spanish, Italian, Portuguese); in American English
# it is the flapped /t/ or /d/ of "butter", so it keeps its own symbol there.
FLAP = "ɾ"
FLAP_RHOTIC_LANGUAGES = frozenset({"spanish", "italian", "portuguese", "es", "it", "pt"})
VOWELS = frozenset("iyɨʉɯuɪʏʊeøɘɵɤoəɛœɜɞʌɔæɐaɶɑɒ")
# Applied after NFD decomposition, in order. NFD splits ç into c + cedilla, which is restored.
REPLACEMENTS = (
    ("ç", "ç"),
    ("ʧ", "tʃ"), ("ʤ", "dʒ"), ("ʦ", "ts"), ("ʣ", "dz"), ("ʨ", "tɕ"), ("ʥ", "dʑ"),
    ("ɡ", "g"), ("ɚ", "ə˞"), ("ɝ", "ɜ˞"), ("ɫ", "lˠ"), ("ᵻ", "ɪ"), ("ᵿ", "ʊ"), ("ɩ", "ɪ"), ("ɷ", "ʊ"),
    (":", "ː"), ("S", "ʃ"), ("Z", "ʒ"), ("N", "ŋ"), ("X", "χ"),
)
LANGUAGE_SWITCH = re.compile(r"\([a-z]{2,3}(?:-[a-z0-9]+)?\)", re.IGNORECASE)


def _clean(ipa: str) -> str:
    text = unicodedata.normalize("NFD", ipa)
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return LANGUAGE_SWITCH.sub(" ", text)


def _is_mark(char: str) -> bool:
    return char in LENGTH or unicodedata.category(char) in ("Mn", "Mc", "Me", "Lm", "Sk")


def segment_ipa(ipa: str) -> list[str]:
    """Narrow phones: one base letter each, with its diacritics and length mark.

    Stress, ties, tones and boundaries are dropped, so `t͡ʃ` and `tʃ` both give `t`, `ʃ`, and a
    diphthong gives its two vowels. A mark after a boundary has no phone to attach to and is dropped.
    """

    phones: list[str] = []
    attach = False
    for char in _clean(ipa):
        if char in STRESS or char in TIES or char in TONES:
            continue
        if char in SEPARATORS or char.isspace():
            attach = False
            continue
        if _is_mark(char):
            if phones and attach:
                phones[-1] += char
            continue
        phones.append(char)
        attach = True
    return phones


def rhotics(language: str | None = None) -> frozenset[str]:
    """The rhotics that fold into `r` for a language: ɾ only in Spanish, Italian and Portuguese, or
    when the language is unknown (the language-free behaviour)."""

    if language is None or language in FLAP_RHOTIC_LANGUAGES:
        return RHOTICS
    return RHOTICS - {FLAP}


def normalize_phone(phone: str, *, keep_rhotics: bool = False, language: str | None = None) -> list[str]:
    """The broad phones of one narrow phone (several when it holds several base letters).

    Length and every diacritic outside `KEPT_MARKS` go; the rhotics of `rhotics(language)` become
    `r` unless `keep_rhotics` (the accent detector keeps them to see /ʁ/ → /ɹ/).
    """

    folded = rhotics(language)
    broad = []
    for part in segment_ipa(phone):
        base, marks = part[0], part[1:]
        if not keep_rhotics and base in folded:
            base = "r"
        kept = sorted({mark for mark in marks if mark in KEPT_MARKS}, key=KEPT_MARKS.index)
        broad.append(base + "".join(kept))
    return broad


def normalize(phones: Iterable[str], *, keep_rhotics: bool = False, language: str | None = None) -> list[str]:
    """Broad phones for a sequence; one per narrow phone from `segment_ipa`."""

    return [item for phone in phones
            for item in normalize_phone(phone, keep_rhotics=keep_rhotics, language=language)]


def normalize_with_owners(phones: Sequence[str], *, keep_rhotics: bool = False, language: str | None = None
                          ) -> tuple[list[str], list[int]]:
    """`normalize`, with the index of the narrow phone each broad phone came from."""

    broad: list[str] = []
    owners: list[int] = []
    for index, phone in enumerate(phones):
        parts = normalize_phone(phone, keep_rhotics=keep_rhotics, language=language)
        broad += parts
        owners += [index] * len(parts)
    return broad, owners


# --------------------------------------------------------------------------------------------
# CTC vocabularies and greedy decoding
# --------------------------------------------------------------------------------------------

BLANK_TOKENS = ("<blk>", "<blank>", "<pad>", "<eps>", "<b>", "<ctc_blank>")
BOUNDARY_TOKENS = frozenset({"▁", "|", "_", "<space>"})
_SPECIAL = re.compile(r"^<[^<>]*>$")


def blank_index(vocab: Sequence[str]) -> int:
    for name in BLANK_TOKENS:
        if name in vocab:
            return list(vocab).index(name)
    return 0


def token_kind(token: str) -> str:
    """`special`, `boundary`, `modifier` (attaches to the previous phone) or `phone`."""

    if not token or _SPECIAL.match(token):
        return "special"
    if token in BOUNDARY_TOKENS or token.isspace():
        return "boundary"
    cleaned = [char for char in _clean(token) if not (char in SEPARATORS or char.isspace())]
    if not cleaned or all(char in STRESS or char in TONES or char in TIES for char in cleaned):
        return "special"
    if all(_is_mark(char) or char in STRESS or char in TONES or char in TIES for char in cleaned):
        return "modifier"
    return "phone"


def ctc_greedy(logprobs: np.ndarray, vocab: Sequence[str], frame_seconds: float) -> list[dict[str, Any]]:
    """Best-path CTC decoding into `{phone, start, end, prob}` with the frame span of each phone.

    Repeated frames collapse and blanks drop as usual. A modifier token (ZIPA emits `̃`, `ʰ` or `ː`
    as tokens of their own) joins the phone before it; boundary and special tokens are skipped.
    `prob` is the mean posterior of the phone's frames (the lowest of its tokens when merged).
    """

    scores = np.asarray(logprobs, dtype=np.float32)
    if scores.ndim != 2 or scores.shape[1] != len(vocab):
        raise ValueError("logprobs must be [frames x vocab]")
    best = scores.argmax(axis=1)
    blank = blank_index(vocab)
    phones: list[dict[str, Any]] = []
    attach = False
    frame = 0
    while frame < len(best):
        token = int(best[frame])
        end = frame
        while end + 1 < len(best) and best[end + 1] == token:
            end += 1
        if token != blank:
            kind = token_kind(vocab[token])
            prob = float(np.exp(scores[frame:end + 1, token]).mean())
            start_seconds, end_seconds = round(frame * frame_seconds, 3), round((end + 1) * frame_seconds, 3)
            if kind == "phone":
                phones.append({"phone": vocab[token], "start": start_seconds, "end": end_seconds,
                               "prob": round(prob, 4)})
                attach = True
            elif kind == "modifier" and phones and attach:
                phones[-1]["phone"] += vocab[token]
                phones[-1]["end"] = end_seconds
                phones[-1]["prob"] = round(min(phones[-1]["prob"], prob), 4)
            elif kind == "boundary":
                attach = False
        frame = end + 1
    return phones


def recognized_phones(phones: Iterable[Mapping[str, Any] | str], *, keep_rhotics: bool = False,
                      language: str | None = None) -> list[dict[str, Any]]:
    """Broad recognized phones with times; a multi-phone token ("aɪ") splits its span evenly."""

    result = []
    for item in phones:
        if isinstance(item, str):
            item = {"phone": item, "start": None, "end": None, "prob": None}
        parts = normalize_phone(str(item["phone"]), keep_rhotics=keep_rhotics, language=language)
        start, end = item.get("start"), item.get("end")
        for index, part in enumerate(parts):
            if start is not None and end is not None:
                step = (float(end) - float(start)) / len(parts)
                span = (round(float(start) + index * step, 3), round(float(start) + (index + 1) * step, 3))
            else:
                span = (None, None)
            result.append({"phone": part, "start": span[0], "end": span[1], "prob": item.get("prob")})
    return result


# --------------------------------------------------------------------------------------------
# PanPhon feature distance
# --------------------------------------------------------------------------------------------


def coarse_distance(a: str, b: str) -> float:
    """The fallback substitution cost when a phone has no PanPhon features."""

    if a == b:
        return 0.0
    if a[:1] == b[:1]:
        return 0.25
    if (a[:1] in VOWELS) == (b[:1] in VOWELS):
        return 0.6
    return 1.0


class PhoneFeatures:
    """PanPhon's articulatory feature table (`ipa_all.csv`, 24 features in {-1, 0, +1}).

    `distance(a, b)` is the weighted feature distance in [0, 1]: the sum of PanPhon's feature
    weights times |a - b|, over twice the sum of the weights. A phone missing from the table is
    split into its longest known segments, whose vectors are averaged; a phone with none falls back
    to `coarse_distance`.
    """

    source = "panphon"

    def __init__(self, segments: Mapping[str, np.ndarray], weights: np.ndarray) -> None:
        self.segments = dict(segments)
        self.weights = np.asarray(weights, dtype=np.float64)
        self.scale = 2.0 * float(self.weights.sum())
        self.longest = max(len(key) for key in self.segments)
        self._vectors: dict[str, np.ndarray | None] = {}

    @classmethod
    def from_csv(cls, table: Path | str, weights: Path | str) -> "PhoneFeatures":
        value = {"+": 1.0, "-": -1.0, "0": 0.0}
        with open(table, encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        names = rows[0][1:]
        segments = {unicodedata.normalize("NFD", row[0]): np.array([value[item] for item in row[1:]])
                    for row in rows[1:] if row}
        with open(weights, encoding="utf-8", newline="") as handle:
            weight_rows = list(csv.reader(handle))
        named = dict(zip(weight_rows[0], (float(item) for item in weight_rows[1])))
        # PanPhon weights 22 of the 24 features; the two tone features carry no weight here.
        return cls(segments, np.array([named.get(name, 0.0) for name in names]))

    def vector(self, phone: str) -> np.ndarray | None:
        if phone in self._vectors:
            return self._vectors[phone]
        key = unicodedata.normalize("NFD", phone).replace("g", "ɡ")
        found = []
        if key in self.segments:
            found.append(self.segments[key])
        else:
            position = 0
            while position < len(key):
                for length in range(min(self.longest, len(key) - position), 0, -1):
                    piece = key[position:position + length]
                    if piece in self.segments:
                        found.append(self.segments[piece])
                        position += length
                        break
                else:
                    position += 1
        vector = np.mean(found, axis=0) if found else None
        self._vectors[phone] = vector
        return vector

    def distance(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        first, second = self.vector(a), self.vector(b)
        if first is None or second is None:
            return coarse_distance(a, b)
        return float(np.dot(self.weights, np.abs(first - second)) / self.scale)


@functools.lru_cache(maxsize=4)
def _load_features(directory: str) -> PhoneFeatures | None:
    table, weights = Path(directory) / PANPHON_TABLE, Path(directory) / PANPHON_WEIGHTS
    if table.is_file() and weights.is_file():
        return PhoneFeatures.from_csv(table, weights)
    return None


def load_phone_features(model_dir: Path | str | None = None) -> PhoneFeatures | None:
    """PanPhon's table from the `g2p.espeak-ng` model directory, or None when it is not fetched."""

    return _load_features(str(Path(model_dir) if model_dir else G2P_MODEL_DIR))


def default_distance(model_dir: Path | str | None = None) -> tuple[Callable[[str, str], float], str]:
    features = load_phone_features(model_dir)
    if features is None:
        return coarse_distance, "coarse"
    return features.distance, features.source


# --------------------------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------------------------


def align(expected: Sequence[str], recognized: Sequence[Mapping[str, Any] | str], *,
          distance: Callable[[str, str], float] | None = None, indel: float = 1.0,
          optional: Sequence[bool] | None = None) -> list[dict[str, Any]]:
    """Align expected and recognized phones by weighted edit distance.

    Insertions and deletions cost `indel`; a substitution costs the feature distance (0 for the
    same phone, at most 1). An expected phone flagged in `optional` (one flag per expected phone: a
    French liaison consonant, a final schwa) costs nothing to leave out, and leaving it out is a
    `skip`, which no rate counts. Returns one op per step in order: `{op, expected, recognized,
    expectedIndex, recognizedIndex, cost, start, end}` with `op` in match, sub, del, skip, ins.
    Times are the recognized phone's; a deletion or a skip gets the gap between its recognized
    neighbours.
    """

    if distance is None:
        distance = default_distance()[0]
    rec = [item if isinstance(item, Mapping) else {"phone": item, "start": None, "end": None}
           for item in recognized]
    rec_phones = [str(item["phone"]) for item in rec]
    n, m = len(expected), len(rec_phones)
    pairs: dict[tuple[str, str], float] = {}
    cost = np.zeros((n, m))
    for i, a in enumerate(expected):
        for j, b in enumerate(rec_phones):
            if (a, b) not in pairs:
                pairs[(a, b)] = float(distance(a, b))
            cost[i, j] = pairs[(a, b)]
    deletion = np.full(n, float(indel))  # per expected phone: what leaving it out costs
    if optional is not None:
        flags = np.asarray(list(optional), dtype=bool)
        if flags.size != n:
            raise ValueError("optional needs one flag per expected phone")
        deletion[flags] = 0.0
    table = np.zeros((n + 1, m + 1))
    table[0, :] = np.arange(m + 1) * indel
    table[1:, 0] = np.cumsum(deletion)
    offsets = np.arange(m + 1) * indel
    for i in range(1, n + 1):
        best = np.empty(m + 1)
        best[0] = table[i, 0]
        best[1:] = np.minimum(table[i - 1, :-1] + cost[i - 1], table[i - 1, 1:] + deletion[i - 1])
        # Insertions chain along the row: D[i, j] = min over k <= j of best[k] + (j - k) * indel.
        table[i] = np.minimum.accumulate(best - offsets) + offsets
    ops: list[dict[str, Any]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and math.isclose(table[i, j], table[i - 1, j - 1] + cost[i - 1, j - 1], abs_tol=1e-9):
            kind = "match" if expected[i - 1] == rec_phones[j - 1] else "sub"
            ops.append(_op(kind, expected[i - 1], rec[j - 1], i - 1, j - 1, cost[i - 1, j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and math.isclose(table[i, j], table[i - 1, j] + deletion[i - 1], abs_tol=1e-9):
            kind = "skip" if deletion[i - 1] == 0.0 else "del"
            ops.append(_op(kind, expected[i - 1], None, i - 1, None, deletion[i - 1]))
            i -= 1
        else:
            ops.append(_op("ins", None, rec[j - 1], None, j - 1, indel))
            j -= 1
    ops.reverse()
    _fill_deletion_times(ops)
    return ops


def _op(kind: str, expected: str | None, recognized: Mapping[str, Any] | None, ei: int | None,
        ri: int | None, cost: float) -> dict[str, Any]:
    return {"op": kind, "expected": expected, "recognized": None if recognized is None else str(recognized["phone"]),
            "expectedIndex": ei, "recognizedIndex": ri, "cost": round(float(cost), 4),
            "start": None if recognized is None else recognized.get("start"),
            "end": None if recognized is None else recognized.get("end")}


UNHEARD = ("del", "skip")  # expected phones with no recognized phone


def _fill_deletion_times(ops: list[dict[str, Any]]) -> None:
    for index, op in enumerate(ops):
        if op["op"] not in UNHEARD:
            continue
        before = next((ops[k]["end"] for k in range(index - 1, -1, -1)
                       if ops[k]["op"] not in UNHEARD and ops[k]["end"] is not None), None)
        after = next((ops[k]["start"] for k in range(index + 1, len(ops))
                      if ops[k]["op"] not in UNHEARD and ops[k]["start"] is not None), None)
        op["start"] = before if before is not None else after
        op["end"] = after if after is not None else before


# --------------------------------------------------------------------------------------------
# Segmentation-free goodness of pronunciation (GOP-SF)
# --------------------------------------------------------------------------------------------
#
# After Cao, Fan, Svendsen and Salvi, "Segmentation-free Goodness of Pronunciation"
# (arXiv 2507.16838). With CTC posteriors O and the canonical phones L = l_1..l_N:
#
#     GOP-SF(l_i) = log P(L | O) - log P(l_1..l_{i-1} .* l_{i+1}..l_N | O)
#
# The second term frees phone i: any sequence (including nothing) may stand in its place. It
# sums over every segmentation, so no forced alignment decides where l_i lies. GOP-SF is <= 0:
# near 0 when the canonical phone explains the audio as well as anything else would, strongly
# negative when something else (another phone, a repetition, nothing) explains it better.
#
# Both terms come from one forward (alpha) and one backward (beta) pass over the canonical CTC
# graph. A path through the free graph splits uniquely at t1, the last frame of l_{i-1}'s run,
# and t2, the first frame of l_{i+1}'s run; the frames between are free except that the first
# is not l_{i-1} and the last is not l_{i+1} (which keeps the split unique). So
#
#     P(free) = sum over t1 < t2 of alpha_t1(l_{i-1}) * middle(t1, t2) * beta_t2(l_{i+1}),
#
# computed in O(T) per phone with a cumulative sum. GOP-SF-Norm divides by the phone's expected
# occupancy (frames, floored at 1); `start`/`end` are where its posterior occupancy is >= 0.5,
# the self-alignment (GOP-SA) view of where the model put the phone.

_NEG = -np.inf


def _logsumexp(values: np.ndarray, axis: int | None = None) -> np.ndarray | float:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return _NEG
    peak = np.max(values, axis=axis, keepdims=True)
    peak = np.where(np.isfinite(peak), peak, 0.0)
    with np.errstate(divide="ignore"):
        total = np.log(np.sum(np.exp(values - peak), axis=axis, keepdims=True)) + peak
    return total.item() if axis is None else np.squeeze(total, axis=axis)


def _log1m_exp(values: np.ndarray) -> np.ndarray:
    """log(1 - exp(x)) for log-probabilities x <= 0."""

    with np.errstate(divide="ignore"):
        return np.log1p(-np.exp(np.minimum(values, -1e-12)))


def ctc_labels(vocab: Sequence[str], *, keep_rhotics: bool = True) -> tuple[list[str], list[list[int]], list[int]]:
    """Merge a recognizer vocabulary into broad CTC labels.

    Returns `(labels, groups, folded)`: label strings, the vocabulary indices behind each label
    (wav2vec2's `i`, `iː` and `i5` all become `i`), and the indices folded into blank (the blank,
    special and boundary tokens, and marks the broad inventory drops, like ZIPA's `ː`).
    """

    blank = blank_index(vocab)
    folded = [blank]
    groups: dict[str, list[int]] = {}
    for index, token in enumerate(vocab):
        if index == blank:
            continue
        kind = token_kind(token)
        if kind in ("special", "boundary"):
            folded.append(index)
            continue
        if kind == "modifier":
            label = "".join(char for char in _clean(token) if char in KEPT_MARKS)
        else:
            label = "".join(normalize_phone(token, keep_rhotics=keep_rhotics))
        if label:
            groups.setdefault(label, []).append(index)
        else:
            folded.append(index)
    labels = sorted(groups)
    return labels, [groups[label] for label in labels], folded


def merged_logprobs(logprobs: np.ndarray, groups: Sequence[Sequence[int]], folded: Sequence[int]) -> np.ndarray:
    """[frames x (1 + labels)] log-posteriors: column 0 is the blank with every folded token."""

    scores = np.asarray(logprobs, dtype=np.float64)
    columns = [_logsumexp(scores[:, list(folded)], axis=1)]
    columns += [_logsumexp(scores[:, list(group)], axis=1) for group in groups]
    return np.stack(columns, axis=1)


def _tokenize(expected: Sequence[str], label_index: Mapping[str, int]) -> tuple[list[int], list[tuple[int, int] | None]]:
    """Greedy longest-match of the expected phones onto labels; each phone's token range [p, q)."""

    chars, owner = [], []
    for position, phone in enumerate(expected):
        for char in phone:
            chars.append(char)
            owner.append(position)
    text = "".join(chars)
    longest = max((len(label) for label in label_index), default=1)
    tokens: list[int] = []
    covers: list[tuple[int, int]] = []
    position = 0
    while position < len(text):
        for length in range(min(longest, len(text) - position), 0, -1):
            column = label_index.get(text[position:position + length])
            if column is not None:
                tokens.append(column)
                covers.append((owner[position], owner[position + length - 1]))
                position += length
                break
        else:
            position += 1
    spans: list[tuple[int, int] | None] = []
    for phone in range(len(expected)):
        inside = [k for k, (first, last) in enumerate(covers) if first <= phone <= last]
        spans.append((inside[0], inside[-1] + 1) if inside else None)
    return tokens, spans


def _ctc_alpha(emissions: np.ndarray, skip: np.ndarray) -> np.ndarray:
    frames, states = emissions.shape
    alpha = np.full((frames, states), _NEG)
    alpha[0, 0] = emissions[0, 0]
    alpha[0, 1] = emissions[0, 1]
    with np.errstate(invalid="ignore"):
        for t in range(1, frames):
            previous = alpha[t - 1]
            one = np.concatenate(([_NEG], previous[:-1]))
            two = np.concatenate(([_NEG, _NEG], previous[:-2]))
            two[~skip] = _NEG
            alpha[t] = np.logaddexp(np.logaddexp(previous, one), two) + emissions[t]
    return alpha


def _ctc_beta(emissions: np.ndarray, skip: np.ndarray) -> np.ndarray:
    frames, states = emissions.shape
    beta = np.full((frames, states), _NEG)
    beta[-1, -1] = emissions[-1, -1]
    beta[-1, -2] = emissions[-1, -2]
    skip_ahead = np.concatenate((skip[2:], [False, False]))
    with np.errstate(invalid="ignore"):
        for t in range(frames - 2, -1, -1):
            following = beta[t + 1]
            one = np.concatenate((following[1:], [_NEG]))
            two = np.concatenate((following[2:], [_NEG, _NEG]))
            two[~skip_ahead] = _NEG
            beta[t] = np.logaddexp(np.logaddexp(following, one), two) + emissions[t]
    return beta


def ctc_log_likelihood(scores: np.ndarray, tokens: Sequence[int]) -> float:
    """log P(tokens | scores) under CTC, with blank in column 0 of the merged scores."""

    if not tokens:
        return float(np.sum(scores[:, 0]))
    states = np.array([0] + [item for token in tokens for item in (token, 0)])
    emissions = scores[:, states]
    skip = np.array([s % 2 == 1 and s >= 3 and states[s] != states[s - 2] for s in range(len(states))])
    alpha = _ctc_alpha(emissions, skip)
    return float(np.logaddexp(alpha[-1, -1], alpha[-1, -2]))


def _free_log_prob(alpha: np.ndarray, beta: np.ndarray, scores: np.ndarray, tokens: Sequence[int],
                   first: int, last: int) -> float:
    """log P(prefix .* suffix) with tokens [first, last) freed (see the section comment)."""

    frames = scores.shape[0]
    has_prefix, has_suffix = first > 0, last < len(tokens)
    if not has_prefix and not has_suffix:
        return 0.0
    terms: list[float] = []
    if has_prefix:
        prev = tokens[first - 1]
        head = alpha[:, 2 * (first - 1) + 1]
        head_open = head[:-1] + _log1m_exp(scores[1:, prev])  # t1 = 0..T-2; frame t1+1 is not prev
    if has_suffix:
        nxt = tokens[last]
        tail = beta[:, 2 * last + 1]
        tail_open = tail[1:] + _log1m_exp(scores[:-1, nxt])  # t2 = 1..T-1; frame t2-1 is not nxt
    if has_prefix and has_suffix:
        if prev != nxt and frames >= 2:
            terms.append(_logsumexp(head[:-1] + tail[1:]))  # nothing between
        if frames >= 3:
            middle = np.exp(scores[1:-1, prev]) + (np.exp(scores[1:-1, nxt]) if prev != nxt else 0.0)
            with np.errstate(divide="ignore"):
                single = np.log(np.clip(1.0 - middle, 0.0, None))
            terms.append(_logsumexp(head[:-2] + single + tail[2:]))  # one free frame
        if frames >= 4:
            cumulative = np.logaddexp.accumulate(head_open)
            terms.append(_logsumexp(tail_open[2:] + cumulative[:frames - 3]))  # two or more
    elif has_suffix:
        terms += [float(tail[0]), _logsumexp(tail_open)]
    else:
        terms += [float(head[-1]), _logsumexp(head_open)]
    return float(_logsumexp(np.array(terms)))


def gop(logprobs: np.ndarray, vocab: Sequence[str], expected: Sequence[str], *,
        frame_seconds: float | None = None, keep_rhotics: bool = True, low: float = 0.5) -> dict[str, Any]:
    """GOP-SF for each expected phone from [frames x vocab] CTC log-posteriors.

    `expected` holds narrow or broad phones (one entry per phone); each is normalized
    (`keep_rhotics` by default, to stay accent-sensitive) and tokenized onto the recognizer's
    labels. Returns `{logLikelihood, lpp, frames, phones: [{index, phone, gop, gopNorm,
    occupancy, start, end}]}`; a phone the vocabulary cannot express has `gop` None.
    """

    labels, groups, folded = ctc_labels(vocab, keep_rhotics=keep_rhotics)
    scores = merged_logprobs(logprobs, groups, folded)
    frames = scores.shape[0]
    phones = ["".join(normalize_phone(phone, keep_rhotics=keep_rhotics)) for phone in expected]
    tokens, spans = _tokenize(phones, {label: column + 1 for column, label in enumerate(labels)})
    entries = [{"index": i, "phone": phone, "gop": None, "gopNorm": None, "occupancy": None,
                "start": None, "end": None} for i, phone in enumerate(phones)]
    result = {"logLikelihood": None, "lpp": None, "frames": int(frames), "phones": entries}
    if not tokens or frames == 0:
        return result
    states = np.array([0] + [item for token in tokens for item in (token, 0)])
    emissions = scores[:, states]
    skip = np.array([s % 2 == 1 and s >= 3 and states[s] != states[s - 2] for s in range(len(states))])
    alpha, beta = _ctc_alpha(emissions, skip), _ctc_beta(emissions, skip)
    total = float(np.logaddexp(alpha[-1, -1], alpha[-1, -2]))
    if not math.isfinite(total):
        return result  # too few frames for the canonical sequence
    result["logLikelihood"], result["lpp"] = round(total, 4), round(total / frames, 4)
    with np.errstate(invalid="ignore"):
        occupancy = np.exp(alpha[:, 1::2] + beta[:, 1::2] - emissions[:, 1::2] - total)  # [frames x tokens]
    for entry, span in zip(entries, spans):
        if span is None:
            continue
        first, last = span
        value = min(0.0, total - _free_log_prob(alpha, beta, scores, tokens, first, last))
        posterior = occupancy[:, first:last].sum(axis=1)
        frames_held = float(posterior.sum())
        inside = np.nonzero(posterior >= low)[0]
        if inside.size == 0:
            inside = np.array([int(np.argmax(posterior))])
        entry.update({"gop": round(value, 4), "gopNorm": round(value / max(frames_held, 1.0), 4),
                      "occupancy": round(frames_held, 3)})
        if frame_seconds:
            entry.update({"start": round(int(inside[0]) * frame_seconds, 3),
                          "end": round((int(inside[-1]) + 1) * frame_seconds, 3)})
    return result


# --------------------------------------------------------------------------------------------
# Stutter features
# --------------------------------------------------------------------------------------------


def _similar(first: Sequence[str], second: Sequence[str], distance: Callable[[str, str], float],
             near: float) -> bool:
    return all(distance(a, b) <= near for a, b in zip(first, second))


def _repeat_runs(rec_ops: Sequence[Mapping[str, Any]], distance: Callable[[str, str], float], *,
                 max_n: int, near: float, inserted_share: float,
                 inserted: Sequence[bool] | None = None) -> list[dict[str, Any]]:
    """Back-to-back copies of a recognized n-gram whose every phone is near-identical, longest n
    first. A copy with a differing phone is not a repeat: rhymes and alliteration ("bran" then
    "tran") are words, not stutters. `inserted` marks the phones that count as inserted (default:
    every `ins` op)."""

    phones = [str(op["recognized"]) for op in rec_ops]
    inserted = [op["op"] == "ins" for op in rec_ops] if inserted is None else list(inserted)
    used = [False] * len(phones)
    runs = []
    for n in range(max_n, 0, -1):
        i = 0
        while i + 2 * n <= len(phones):
            if any(used[i:i + 2 * n]) or not _similar(phones[i:i + n], phones[i + n:i + 2 * n], distance, near):
                i += 1
                continue
            copies = 2
            while (i + (copies + 1) * n <= len(phones) and not any(used[i + copies * n:i + (copies + 1) * n])
                   and _similar(phones[i:i + n], phones[i + copies * n:i + (copies + 1) * n], distance, near)):
                copies += 1
            span = range(i, i + copies * n)
            # The script lacks the repetition when at least one copy's worth is inserted; a
            # single repeated phone needs three copies (a doubled consonant can be a geminate).
            enough = sum(inserted[k] for k in span) >= math.ceil(n * inserted_share)
            if enough and (n >= 2 or copies >= 3):
                for k in span:
                    used[k] = True
                runs.append({"start": rec_ops[span[0]]["start"], "end": rec_ops[span[-1]]["end"], "n": n,
                             "copies": copies, "phones": phones[i:i + n]})
                i += copies * n
            else:
                i += 1
    return sorted(runs, key=lambda run: (run["start"] is None, run["start"] or 0.0))


def _runs(ops: Sequence[Mapping[str, Any]], member: Callable[[int, Mapping[str, Any]], bool],
          transparent: tuple[str, ...], minimum: int, field: str) -> list[dict[str, Any]]:
    """Runs of consecutive ops that satisfy `member(index, op)`, looking through `transparent` ops."""

    runs, current = [], []
    for index, op in enumerate(list(ops) + [{"op": "end"}]):
        if op["op"] != "end" and member(index, op):
            current.append(op)
        elif op["op"] in transparent:
            continue
        else:
            if len(current) >= minimum:
                runs.append({"start": current[0]["start"], "end": current[-1]["end"], "count": len(current),
                             "phones": [item[field] for item in current]})
            current = []
    return runs


def stutter_features(ops: Sequence[Mapping[str, Any]], times: Sequence[Mapping[str, Any]] | None = None, *,
                     gop: Mapping[str, Any] | None = None, distance: Callable[[str, str], float] | None = None,
                     max_repeat: int = 6, near: float | None = None, inserted_share: float = 2 / 3,
                     min_burst: int = 3, min_deletion_run: int = 2, low_gop: float = -2.3,
                     insertions: Iterable[int] | None = None) -> dict[str, Any]:
    """Stutter and missing-syllable evidence from an alignment (and optionally GOP).

    - rates: deletions, substitutions and insertions over the expected phones, and their sum (PER).
      A substitution within `near` of its phone (a voicing pair, /e/ for /ɛ/) counts as a match, and
      a `skip` (an optional phone left out) counts nowhere;
    - `repeatRuns`: identical or near-identical recognized phone n-grams (n <= `max_repeat`)
      repeated back to back, where the copies are mostly insertions, i.e. the script lacks them;
    - `insertionBursts` (>= `min_burst` consecutive insertions) and `deletionRuns` (>=
      `min_deletion_run` consecutive deletions: missing syllables);
    - `lowGopSpans`: consecutive expected phones with GOP-SF <= `low_gop` (log 0.1).

    `insertions` (op indices) restricts what counts as inserted to those ops (the insertions a
    second recognizer agrees on, `agreement`); the other `ins` ops stay recognized phones.
    `times` (recognized phones with `start`/`end`) fills op times when the ops lack them.
    """

    if distance is None:
        distance = default_distance()[0]
    if near is None:
        # Near-identity is on the distance's own scale: PanPhon feature distances put voicing pairs near
        # 0.02 and l/r near 0.09, while the coarse fallback gives 0.25 to a shared first character.
        near = COARSE_NEAR if distance is coarse_distance else PANPHON_NEAR
    ops = [dict(op) for op in ops]
    if times is not None:
        for op in ops:
            if op.get("recognizedIndex") is not None and op.get("start") is None:
                op["start"] = times[op["recognizedIndex"]].get("start")
                op["end"] = times[op["recognizedIndex"]].get("end")
        _fill_deletion_times(ops)
    inserted_ops = {index for index, op in enumerate(ops) if op["op"] == "ins"}
    if insertions is not None:
        inserted_ops &= set(insertions)
    near_subs = sum(1 for op in ops if op["op"] == "sub" and float(op["cost"]) <= near)
    counts = {kind: sum(1 for op in ops if op["op"] == kind) for kind in ("match", "sub", "del", "skip")}
    counts["match"] += near_subs
    counts["sub"] -= near_subs
    counts["ins"] = len(inserted_ops)
    expected = counts["match"] + counts["sub"] + counts["del"]
    rate = (lambda value: round(value / expected, 4)) if expected else (lambda value: None)
    rec_indices = [index for index, op in enumerate(ops) if op["op"] not in UNHEARD]
    rec_ops = [ops[index] for index in rec_indices]
    repeats = _repeat_runs(rec_ops, distance, max_n=max_repeat, near=near, inserted_share=inserted_share,
                           inserted=[index in inserted_ops for index in rec_indices])
    features: dict[str, Any] = {
        "expectedCount": expected, "recognizedCount": len(rec_ops),
        "matches": counts["match"], "substitutions": counts["sub"], "deletions": counts["del"],
        "insertions": counts["ins"], "skips": counts["skip"],
        "deletionRate": rate(counts["del"]), "substitutionRate": rate(counts["sub"]),
        "insertionRate": rate(counts["ins"]), "per": rate(counts["del"] + counts["sub"] + counts["ins"]),
        "repeatRuns": repeats, "repeatCount": len(repeats),
        "insertionBursts": _runs(ops, lambda index, op: index in inserted_ops, ("del", "skip"), min_burst,
                                 "recognized"),
        "deletionRuns": _runs(ops, lambda index, op: op["op"] == "del", ("ins", "skip"), min_deletion_run,
                              "expected"),
        "lowGopSpans": [], "lowGopFraction": None, "meanGop": None, "minGop": None,
    }
    features["maxInsertionBurst"] = max((run["count"] for run in features["insertionBursts"]), default=0)
    features["maxDeletionRun"] = max((run["count"] for run in features["deletionRuns"]), default=0)
    entries = [entry for entry in (gop or {}).get("phones", []) if entry.get("gop") is not None]
    if entries:
        values = np.array([entry["gop"] for entry in entries])
        features.update({"lowGopFraction": round(float(np.mean(values <= low_gop)), 4),
                         "meanGop": round(float(values.mean()), 4), "minGop": round(float(values.min()), 4)})
        span: list[Mapping[str, Any]] = []
        for entry in list(entries) + [{"index": -2, "gop": 0.0}]:
            contiguous = span and entry["index"] == span[-1]["index"] + 1
            if entry["gop"] <= low_gop and (not span or contiguous):
                span.append(entry)
                continue
            if span:
                features["lowGopSpans"].append({
                    "start": span[0].get("start"), "end": span[-1].get("end"), "count": len(span),
                    "phones": [item["phone"] for item in span],
                    "meanGop": round(float(np.mean([item["gop"] for item in span])), 4)})
            span = [entry] if entry["gop"] <= low_gop else []
    return features


def compare(expected: Sequence[str], recognized: Iterable[Mapping[str, Any] | str], *,
            logprobs: np.ndarray | None = None, vocab: Sequence[str] | None = None,
            frame_seconds: float | None = None, model_dir: Path | str | None = None,
            language: str | None = None, optional: Sequence[bool] | None = None, low_gop: float = -2.3,
            keep_rhotic_ops: bool = False) -> dict[str, Any]:
    """One take and one recognizer: expected phones (from `g2p`) against a phones result (and its
    posteriors).

    `language` decides whether ɾ is a rhotic; `optional` flags the expected phones that may be left
    out (one per expected phone, from the G2P record's words). GOP-SF scores the expected phones
    minus the optional ones the alignment skipped, and `low_gop` bounds its low spans.

    Returns `{distance, expected, recognized, ops, gop, features}`: the broad phones on both sides,
    their alignment, GOP-SF when posteriors are given, and `stutter_features`. With
    `keep_rhotic_ops`, also `rhoticOps`: the same alignment with the rhotics kept apart (/ʁ/ against
    /ɹ/), for the accent detector's L1 pairs.
    """

    recognized = list(recognized)
    distance, source = default_distance(model_dir)
    broad, owners = normalize_with_owners(expected, language=language)
    flags = None
    if optional is not None:
        optional = list(optional)
        if len(optional) != len(expected):
            raise ValueError("optional needs one flag per expected phone")
        flags = [bool(optional[owner]) for owner in owners]
    heard = recognized_phones(recognized, language=language)
    ops = align(broad, heard, distance=distance, optional=flags)
    scored = None
    if logprobs is not None and vocab is not None:
        skipped = {owners[op["expectedIndex"]] for op in ops if op["op"] == "skip"}
        sounded = [phone for index, phone in enumerate(expected) if index not in skipped]
        scored = gop(logprobs, vocab, sounded, frame_seconds=frame_seconds)
    result = {"distance": source, "expected": broad, "recognized": [item["phone"] for item in heard],
              "ops": ops, "gop": scored,
              "features": stutter_features(ops, gop=scored, distance=distance, low_gop=low_gop)}
    if keep_rhotic_ops:
        kept, _ = normalize_with_owners(expected, keep_rhotics=True, language=language)
        result["rhoticOps"] = align(kept, recognized_phones(recognized, keep_rhotics=True, language=language),
                                    distance=distance, optional=flags)
    return result


def insertion_positions(ops: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """`(op index, position)` of every insertion: the position is the expected index of the nearest
    earlier op that has one (-1 before the first), so two recognizers' alignments of the same
    expected phones place their insertions on one scale."""

    out, position = [], -1
    for index, op in enumerate(ops):
        if op["op"] == "ins":
            out.append((index, position))
        elif op.get("expectedIndex") is not None:
            position = int(op["expectedIndex"])
    return out


def _time_gap(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[float, float] | None:
    """Seconds between two ops' spans (0 when they overlap) and between their midpoints, or None
    when either has no time."""

    if a.get("start") is None or b.get("start") is None:
        return None
    a_start, b_start = float(a["start"]), float(b["start"])
    a_end = float(a["end"]) if a.get("end") is not None else a_start
    b_end = float(b["end"]) if b.get("end") is not None else b_start
    return max(0.0, a_start - b_end, b_start - a_end), abs((a_start + a_end) - (b_start + b_end)) / 2


def agreed_insertions(first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]], *,
                      tolerance: float = 0.06) -> list[int]:
    """The insertions of `first` (op indices) that `second` also made, one for one: first those
    within `tolerance` seconds of each other (closest pairs first), then those at the same expected
    position (the same phone preferred). A run of insertions at one position thus pairs phone with
    phone in time, not in order."""

    mine, theirs = insertion_positions(first), insertion_positions(second)
    pairs = []
    for i, (index, _) in enumerate(mine):
        for k, (other, _) in enumerate(theirs):
            gap = _time_gap(first[index], second[other])
            if gap is not None and gap[0] <= tolerance + 1e-9:
                pairs.append((gap, i, k))
    used_mine: set[int] = set()
    used_theirs: set[int] = set()
    for _, i, k in sorted(pairs):
        if i not in used_mine and k not in used_theirs:
            used_mine.add(i)
            used_theirs.add(k)
    for i, (index, position) in enumerate(mine):
        if i in used_mine:
            continue
        candidates = [k for k, (_, other_position) in enumerate(theirs)
                      if k not in used_theirs and other_position == position]
        same = [k for k in candidates if second[theirs[k][0]]["recognized"] == first[index]["recognized"]]
        if candidates:
            used_mine.add(i)
            used_theirs.add((same or candidates)[0])
    return sorted(mine[i][0] for i in used_mine)


def agreement(first: Mapping[str, Any], second: Mapping[str, Any], *, model_dir: Path | str | None = None,
              tolerance: float = 0.06, **options: Any) -> dict[str, Any]:
    """Two recognizers' comparisons (`compare`) of one take, against the same expected phones.

    A phone recognizer has no external language model or lexicon, but its training data still
    shapes what it prints (ZIPA writes French silent letters on native speech); two recognizers of
    different families rarely share such a habit. Returns `{agreed, features}`: the insertions of
    `first` that `second` also made (`agreed_insertions`), and `stutter_features` over `first`'s
    alignment counting only those (`insertionRate`, `insertionBursts` of one or more, `repeatRuns`).
    """

    distance = default_distance(model_dir)[0]
    agreed = agreed_insertions(first["ops"], second["ops"], tolerance=tolerance)
    options.setdefault("min_burst", 1)
    return {"agreed": agreed,
            "features": stutter_features(first["ops"], distance=distance, insertions=agreed, **options)}



# --------------------------------------------------------------------------------------------
# G2P (espeak-ng): the engine, cache and job live in `qc.runners.espeak_g2p`
# --------------------------------------------------------------------------------------------


class G2PUnavailable(RuntimeError):
    """No espeak-ng engine in this python (run the G2P job in the onnx runtime)."""


class G2PCacheMiss(LookupError):
    """The text has no cached G2P record and computing one was not allowed."""


def g2p(text: str, language: str, *, cache_dir: Path | str | None = None, compute: bool = True,
        engine: Any = None) -> list[str]:
    """The expected narrow phones of a script, from the G2P cache or espeak-ng.

    The cache is `build/cache/qc/results/g2p/<g2p_key>.json`. In the repository's python (no
    espeak-ng) a miss raises `G2PUnavailable`; `compute=False` raises `G2PCacheMiss` instead.
    """

    from qc.runners import espeak_g2p

    return espeak_g2p.g2p(text, language, cache_dir=cache_dir, compute=compute, engine=engine)


def g2p_record(text: str, language: str, **options: Any) -> dict[str, Any]:
    """The whole cached G2P record (`ipa`, `words`, `phones`, engine and voice)."""

    from qc.runners import espeak_g2p

    return espeak_g2p.g2p_record(text, language, **options)


def g2p_espeak(text: str, language: str, *, engine: Any = None) -> list[str]:
    """espeak-ng phones without the cache (decision D5's direct path)."""

    from qc.runners import espeak_g2p

    return espeak_g2p.g2p_espeak(text, language, engine=engine)


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m qc.phones --g2p-job job.json`: the same job as `qc.runners.espeak_g2p --job`."""

    from qc.runners import espeak_g2p

    return espeak_g2p.main(argv)


if __name__ == "__main__":
    sys.exit(main())
