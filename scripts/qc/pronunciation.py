"""Bounded French pronunciation diagnostics over existing CTC evidence.

This module performs no inference, cache I/O, linguistic acceptance or accent
classification. G2P optionality is a heuristic hypothesis, never a statement
that a liaison is linguistically optional. Raw tokens and narrow distinctions
remain visible even when only one recognizer notices an unusual realization.
"""
from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, Sequence

import numpy as np

from qc import phones

SCHEMA = "vocello.qc.pronunciation-evidence/1"
DEFAULT_LIMITS = {"paths": 16, "tokenizations": 16, "frames": 20000,
                  "phones": 512, "operations": 256, "cells": 2000000, "vocab": 4096}
ROLES = ("phones", "phonesB")


def _narrow(items: Sequence[str]) -> list[str]:
    return [part for token in items for part in phones.segment_ipa(token)]


def _valid_tokens(value: Any, limit: int) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) <= limit
            and all(isinstance(p, str) and 0 < len(p) <= 64 for p in value))


def _limits(overrides: Mapping[str, int] | None) -> dict[str, int]:
    result = dict(DEFAULT_LIMITS)
    for key, value in (overrides or {}).items():
        if key not in result or type(value) is not int or not 1 <= value <= result[key]:
            raise ValueError("limits may only lower a known positive integer bound")
        result[key] = value
    return result


def _paths(expected: list[str], words: Sequence[Mapping[str, Any]],
           alternatives: Sequence[Mapping[str, Any]], limits: dict) -> tuple[list[dict], list[str]]:
    paths = [{"id": "canonical", "phones": expected, "origin": "g2p-canonical"}]
    reasons: list[str] = []
    seen = {tuple(expected)}
    identities = {"canonical"}

    def add(value: list[str], identity: str, origin: str, reason: str | None = None) -> None:
        if tuple(value) in seen:
            return
        if not isinstance(identity, str) or not 0 < len(identity) <= 64 or identity in identities:
            reasons.append("invalid-or-duplicate-alternative-id")
            return
        if not value or len(value) > limits["phones"]:
            reasons.append("invalid-alternative-length")
        elif len(paths) >= limits["paths"]:
            reasons.append("path-budget-exceeded")
        else:
            paths.append({"id": identity, "phones": value, "origin": origin, "reason": reason})
            seen.add(tuple(value))
            identities.add(identity)

    if not isinstance(alternatives, (list, tuple)):
        alternatives = []
        reasons.append("invalid-reviewed-alternatives")
    if len(alternatives) > limits["paths"]:
        reasons.append("path-budget-exceeded")
    for index, alternative in enumerate(alternatives[:limits["paths"]]):
        if not isinstance(alternative, Mapping):
            reasons.append("invalid-reviewed-alternative")
            continue
        value = alternative.get("phones")
        if (not _valid_tokens(value, limits["phones"])
                or not isinstance(alternative.get("reason"), str)
                or not 0 < len(alternative["reason"].strip()) <= 512):
            reasons.append("invalid-reviewed-alternative")
            continue
        add(_narrow(value), alternative.get("id", f"reviewed-{index}"),
            "reviewed-alternative", alternative["reason"])

    if not words:
        return paths, list(dict.fromkeys(reasons))
    if not isinstance(words, (list, tuple)) or len(words) > limits["phones"]:
        return paths, list(dict.fromkeys(reasons + ["invalid-g2p-words"]))
    flattened, optional = [], []
    for word in words:
        if not isinstance(word, Mapping):
            return paths, list(dict.fromkeys(reasons + ["invalid-g2p-words"]))
        value = word.get("phones") or []
        marked = word.get("optional") or []
        if (not _valid_tokens(value, limits["phones"])
                or not isinstance(marked, (list, tuple))
                or any(type(i) is not int or i < 0 or i >= len(value) for i in marked)):
            reasons.append("invalid-g2p-optionality")
            return paths, list(dict.fromkeys(reasons))
        for index, token in enumerate(value):
            parts = phones.segment_ipa(token)
            optional.extend(range(len(flattened), len(flattened) + len(parts)) if index in marked else [])
            flattened.extend(parts)
            if len(flattened) > limits["phones"]:
                return paths, list(dict.fromkeys(reasons + ["g2p-word-coverage-mismatch"]))
    if flattened != expected:
        reasons.append("g2p-word-coverage-mismatch")
        return paths, list(dict.fromkeys(reasons))
    # Enumerate by omission count: retained prefixes stay predictable if capped.
    emitted = 0
    for size in range(1, len(optional) + 1):
        for omitted in itertools.combinations(optional, size):
            if emitted >= limits["paths"]:
                reasons.append("path-budget-exceeded")
                return paths, list(dict.fromkeys(reasons))
            emitted += 1
            add([p for i, p in enumerate(expected) if i not in omitted],
                "g2p-omit-" + "-".join(map(str, omitted)), "g2p-optional-heuristic",
                "espeak optional flags; not reviewed liaison/register permission")
    return paths, list(dict.fromkeys(reasons))


def _labels(vocab: list[str]) -> tuple[list[str], list[list[int]], list[int]]:
    """A narrow scoring view: no broad rhotic, length or diacritic folding.

    Original IPA remains separate. As with segment_ipa, stress, boundaries,
    ties and tones do not enter the CTC phone transcript.
    """
    blank = phones.blank_index(vocab)
    groups: dict[str, list[int]] = {}
    folded = [blank]
    for index, token in enumerate(vocab):
        if index == blank:
            continue
        kind = phones.token_kind(token)
        label = "".join(phones.segment_ipa(token))
        if kind == "modifier":
            label = phones._clean(token)  # standalone marks belong to the preceding base
        if kind in ("special", "boundary") or not label:
            folded.append(index)
        else:
            groups.setdefault(label, []).append(index)
    labels = sorted(groups)
    return labels, [groups[label] for label in labels], folded


def _tokenizations(expected: Sequence[str], labels: list[str], limit: int) -> tuple[list[list[int]], bool]:
    """Exact full coverage; never skip an unknown phone/mark as _tokenize does.

    Multiple vocabulary tokenizations (a nasal token versus base + nasal mark)
    are retained, with an explicit incomplete result when their budget is hit.
    """
    text = "".join(expected)
    states: list[list[tuple[int, ...]]] = [[] for _ in range(len(text) + 1)]
    states[0] = [()]
    truncated = False
    for position in range(len(text)):
        if not states[position]:
            continue
        for index, label in enumerate(labels, 1):
            if text.startswith(label, position):
                target = states[position + len(label)]
                for prefix in states[position]:
                    if len(target) >= limit:
                        truncated = True
                        break
                    target.append(prefix + (index,))
    return [list(item) for item in states[-1]], truncated


def _number(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None and math.isfinite(value) else None


def _windows(scores: np.ndarray, tokens: list[int], expected: list[str], labels: list[str],
             seconds: float | None, limits: dict) -> list[dict]:
    if not tokens or seconds is None:
        return []
    states = np.array([0] + [s for token in tokens for s in (token, 0)])
    if scores.shape[0] * len(states) > limits["cells"]:
        return []
    emissions = scores[:, states]
    skip = np.array([i % 2 == 1 and i >= 3 and states[i] != states[i-2] for i in range(len(states))])
    alpha, beta = phones._ctc_alpha(emissions, skip), phones._ctc_beta(emissions, skip)
    total = float(np.logaddexp(alpha[-1, -1], alpha[-1, -2]))
    if not math.isfinite(total):
        return []
    with np.errstate(invalid="ignore"):
        occupancy = np.exp(alpha[:, 1::2] + beta[:, 1::2] - emissions[:, 1::2] - total)
    occupancy = np.nan_to_num(occupancy, nan=0.0)
    # Character overlap maps base+modifier and multi-phone labels to expected phones.
    starts, cursor = [], 0
    for phone in expected:
        starts.append((cursor, cursor + len(phone)))
        cursor += len(phone)
    token_spans, cursor = [], 0
    for token in tokens:
        label = labels[token - 1]
        token_spans.append((cursor, cursor + len(label)))
        cursor += len(label)
    windows = []
    for index, ((first, last), phone) in enumerate(zip(starts, expected)):
        columns = [i for i, (a, b) in enumerate(token_spans) if a < last and b > first]
        mass = occupancy[:, columns].sum(axis=1)
        held = float(mass.sum())
        if held <= 0 or not math.isfinite(held):
            continue
        cumulative = np.cumsum(mass) / held
        a = int(np.searchsorted(cumulative, .05))
        b = min(len(mass) - 1, int(np.searchsorted(cumulative, .95)))
        windows.append({"expectedIndex": index, "phone": phone, "start": round(a * seconds, 6),
                        "end": round((b + 1) * seconds, 6), "occupancyFrames": round(held, 6),
                        "windowBasis": "canonical-ctc-occupancy-5-to-95-percent",
                        "timingQualification": "approximate-not-forced-truth"})
    return windows


def _posterior(data: Mapping[str, Any] | None, paths: list[dict], limits: dict) -> dict:
    result: dict[str, Any] = {"inputStatus": "unavailable", "reason": "missing-posteriors",
                              "expectedWindows": [], "paths": []}
    if not isinstance(data, Mapping):
        return result
    try:
        raw_vocab = data["vocab"]
        if not isinstance(raw_vocab, (list, tuple, np.ndarray)) or len(raw_vocab) > limits["vocab"] or not all(
                isinstance(p, str) and len(p) <= 64 for p in raw_vocab):
            raise ValueError("invalid-vocabulary")
        vocab = list(raw_vocab)
        raw = np.asarray(data["logprobs"], dtype=np.float64)
        if (raw.ndim != 2 or not vocab or raw.shape[1] != len(vocab)
                or len(vocab) != len(set(vocab)) or not any(p in vocab for p in phones.BLANK_TOKENS)):
            raise ValueError("invalid-posterior-shape-or-vocabulary")
        if not raw.shape[0]:
            raise ValueError("empty-posteriors")
        if raw.shape[0] > limits["frames"] or raw.size > limits["cells"]:
            raise ValueError("posterior-budget-exceeded")
        if np.isnan(raw).any() or np.isposinf(raw).any() or np.any(raw > 1e-5):
            raise ValueError("invalid-log-posteriors")
        if not np.allclose(phones._logsumexp(raw, axis=1), 0.0, atol=.002):
            raise ValueError("unnormalized-log-posteriors")
        labels, groups, folded = _labels(vocab)
        scores = phones.merged_logprobs(raw, groups, folded)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        known = {"invalid-vocabulary", "invalid-posterior-shape-or-vocabulary", "empty-posteriors",
                 "posterior-budget-exceeded", "invalid-log-posteriors", "unnormalized-log-posteriors"}
        result["reason"] = str(error) if str(error) in known else "malformed-posteriors"
        return result
    seconds = data.get("frameSeconds")
    seconds = (float(seconds) if type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0 else None)
    probabilities = np.exp(raw)
    with np.errstate(invalid="ignore"):
        entropy = -np.sum(np.where(probabilities > 0, probabilities * raw, 0.0), axis=1)
    greedy = [int(key) for key, _ in itertools.groupby(np.argmax(scores, axis=1)) if key != 0]
    result.update(inputStatus="complete", reason=None, frames=int(raw.shape[0]),
                  scoreView="narrow-ipa-no-stress-boundaries-ties-tones", inventory=labels,
                  meanEntropyNats=_number(float(np.mean(entropy))),
                  meanBlankPosterior=_number(float(np.exp(scores[:, 0]).mean())),
                  greedyLabels=[labels[i - 1] for i in greedy],
                  greedySequenceLogLikelihood=None, expectedWindowsStatus="unavailable")
    result["greedyPhones"] = phones.segment_ipa("".join(result["greedyLabels"][:limits["phones"]]))
    if len(greedy) <= limits["phones"] and len(scores) * (2 * len(greedy) + 1) <= limits["cells"]:
        result["greedySequenceLogLikelihood"] = _number(phones.ctc_log_likelihood(scores, greedy))
    else:
        result.update(inputStatus="partial", reason="greedy-sequence-budget-exceeded")
        result["greedyLabels"] = result["greedyLabels"][:limits["phones"]]
    best, canonical_tokens = None, None
    for path in paths:
        tokens, truncated = _tokenizations(path["phones"], labels, limits["tokenizations"])
        entry = {"id": path["id"], "origin": path["origin"], "inputStatus": "complete",
                 "fullInventoryCoverage": bool(tokens), "tokenizations": len(tokens),
                 "logLikelihood": None, "perFrameLogLikelihood": None}
        if not tokens:
            entry.update(inputStatus="unavailable", reason="out-of-inventory")
        elif truncated:
            entry.update(inputStatus="partial", reason="tokenization-budget-exceeded")
        fits = []
        for sequence in tokens:
            if len(scores) * (2 * len(sequence) + 1) > limits["cells"]:
                entry.update(inputStatus="partial", reason="ctc-state-budget-exceeded")
                continue
            score = phones.ctc_log_likelihood(scores, sequence)
            if math.isfinite(score):
                fits.append((score, sequence))
        if fits:
            score, sequence = max(fits, key=lambda item: item[0])
            # Sum distinct CTC token sequences representing this one narrow path.
            mass = float(phones._logsumexp(np.array([fit[0] for fit in fits])))
            entry.update(logLikelihood=_number(mass), perFrameLogLikelihood=_number(mass / len(scores)))
            if entry["inputStatus"] == "complete" and (best is None or mass > best[0]):
                best = (mass, path["id"])
            if path["id"] == "canonical" and entry["inputStatus"] == "complete":
                canonical_tokens = sequence
        elif tokens and entry["inputStatus"] == "complete":
            entry.update(inputStatus="unavailable", reason="ctc-impossible")
        result["paths"].append(entry)
    result["bestConstrainedPath"] = best[1] if best else None
    result["bestConstrainedLogLikelihood"] = _number(best[0] if best else None)
    greedy_score = result["greedySequenceLogLikelihood"]
    result["constrainedMinusGreedyLogLikelihood"] = _number(best[0] - greedy_score if best and greedy_score is not None else None)
    result["fitInterpretation"] = "model-transcript-support-not-calibrated-error-probability"
    if any(p["inputStatus"] != "complete" for p in result["paths"]):
        result["inputStatus"] = "partial"
    if canonical_tokens is not None and seconds is not None:
        result["expectedWindows"] = _windows(scores, canonical_tokens, paths[0]["phones"], labels, seconds, limits)
        result["expectedWindowsStatus"] = "complete" if len(result["expectedWindows"]) == len(paths[0]["phones"]) else "partial"
    if seconds is None:
        result["expectedWindowsReason"] = "missing-or-invalid-frame-seconds"
    elif canonical_tokens is None:
        result["expectedWindowsReason"] = "canonical-path-unavailable"
    return result


def analyze(expected: Sequence[str] | None, words: Sequence[Mapping[str, Any]] | None,
            outputs: Mapping[str, Any], *, posteriors: Mapping[str, Mapping[str, Any]] | None = None,
            alternatives: Sequence[Mapping[str, Any]] | None = None,
            limits: Mapping[str, int] | None = None) -> dict:
    """Report narrow per-role diagnostics; every decision remains not-assessed.

    `posteriors[role]` is {logprobs: ndarray, vocab: list[str], frameSeconds: float}.
    Reviewed full paths are {id: str, phones: list[str], reason: str}. Limits may
    lower, never raise, the fixed operation budgets. No cache or model is read.
    """
    bound = _limits(limits)
    result: dict[str, Any] = {"schema": SCHEMA, "qualification": "uncalibrated",
                             "decision": "not-assessed", "nativeAccentDecision": "not-assessed",
                             "inputStatus": "unavailable", "roles": {}, "limits": bound,
                             "limitations": ["recognizer-and-g2p-bias", "optional-flags-are-heuristic",
                                             "target-variety-unspecified", "no-qualified-defect-threshold",
                                             "greedy-is-not-optimal-ctc-transcript"]}
    if not _valid_tokens(expected, bound["phones"]) or not expected:
        result["reason"] = "missing-or-invalid-expected-phones"
        return result
    narrow = _narrow(expected)
    result["expectedTokens"] = list(expected)
    if not narrow or len(narrow) > bound["phones"]:
        result["reason"] = "expected-phone-budget-exceeded"
        return result
    paths, reasons = _paths(narrow, words or [], alternatives or [], bound)
    result["pronunciations"] = paths
    result["pathCoverage"] = {"inputStatus": "partial" if reasons else "complete", "reasons": reasons,
                              "linguisticPermission": "not-assessed"}
    for role in ROLES:
        output = outputs.get(role)
        original = output.get("phones") if isinstance(output, Mapping) else None
        entry: dict[str, Any] = {"inputStatus": "unavailable", "originalTokens": original[:bound["phones"]]
                                 if isinstance(original, (list, tuple)) else None,
                                 "localizedCandidates": [], "narrowAlignment": []}
        if isinstance(original, (list, tuple)) and len(original) <= bound["phones"]:
            heard = []
            valid = True
            for item in original:
                item = {"phone": item} if isinstance(item, str) else item
                if not isinstance(item, Mapping) or not _valid_tokens([item.get("phone")], 1):
                    valid = False
                    break
                start, end = item.get("start"), item.get("end")
                if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0)
                       for v in (start, end)) or (start is not None and end is not None and end < start):
                    valid = False
                    break
                for part in phones.segment_ipa(item["phone"]):
                    heard.append({"phone": part, "start": item.get("start"), "end": item.get("end")})
            if valid and len(heard) <= bound["phones"]:
                ops = phones.align(narrow, heard, distance=lambda a, b: float(a != b))
                entry["inputStatus"] = "complete"
                entry["narrowAlignment"] = ops[:bound["operations"]]
                candidates = [{"type": {"sub": "substitution", "ins": "insertion", "del": "deletion"}[op["op"]],
                               "evidenceStatus": "single-witness", "role": role, **op}
                              for op in ops if op["op"] != "match"]
                repeats = phones.stutter_features(ops, distance=lambda a, b: float(a != b), near=0)["repeatRuns"]
                candidates += [{"type": "repeat", "evidenceStatus": "single-witness", "role": role, **run} for run in repeats]
                entry["localizedCandidates"] = candidates[:bound["operations"]]
                if len(ops) > bound["operations"] or len(candidates) > bound["operations"]:
                    entry.update(inputStatus="partial", reason="operation-budget-exceeded")
            else:
                entry["reason"] = "malformed-or-excessive-recognized-phones"
        else:
            entry["reason"] = "missing-or-excessive-recognized-phones"
        entry["posterior"] = _posterior((posteriors or {}).get(role), paths, bound)
        entry["posteriorGreedyMatchesArtifact"] = (
            [item["phone"] for item in heard] == entry["posterior"].get("greedyPhones")
            if entry["inputStatus"] == "complete" and entry["posterior"].get("greedyPhones") is not None else None)
        result["roles"][role] = entry
    available = sum(role["inputStatus"] == "complete" for role in result["roles"].values())
    posterior_available = any(role["posterior"]["inputStatus"] != "unavailable" for role in result["roles"].values())
    complete = available == 2 and not reasons and all(
        role["posterior"]["inputStatus"] == "complete" for role in result["roles"].values())
    result["inputStatus"] = "complete" if complete else "partial" if available or posterior_available else "unavailable"
    return result
