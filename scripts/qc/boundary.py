"""Bounded, report-only French word-join insertion evidence.

G2P optional suffixes widen possible join locations, never license a liaison.
Reviewed full paths are comparisons, not detector labels or permission to
suppress evidence. No inference, audio I/O or linguistic acceptance occurs.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping

from qc import phones

SCHEMA = "vocello.qc.boundary-pronunciation/1"
LIMITS = {"phones": 512, "operations": 256, "candidates": 256,
          "reviewedHypotheses": 16, "seconds": 120, "optionalSuffixPhones": 2}
ROLES = ("phones", "phonesB")


def _tokens(value):
    if (not isinstance(value, (list, tuple)) or not value or len(value) > LIMITS["phones"]
            or any(not isinstance(p, str) or not 0 < len(p) <= 64 for p in value)):
        return None
    result = [part for token in value for part in phones.segment_ipa(token)]
    return result if 0 < len(result) <= LIMITS["phones"] else None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _joins(expected, words):
    if not isinstance(words, (list, tuple)) or not 2 <= len(words) <= LIMITS["phones"]:
        return None
    flattened, result = [], []
    for i, word in enumerate(words):
        if not isinstance(word, Mapping):
            return None
        values = word.get("phones")
        narrow = _tokens(values)
        marked = word.get("optional", [])
        if (narrow is None or not isinstance(marked, (list, tuple)) or len(marked) > len(values)
                or any(type(j) is not int or not 0 <= j < len(values) for j in marked)
                or len(set(marked)) != len(marked)):
            return None
        optional = set()
        word_start = offset = len(flattened)
        for j, token in enumerate(values):
            parts = phones.segment_ipa(token)
            if j in marked:
                optional.update(range(offset, offset + len(parts)))
            offset += len(parts)
        flattened.extend(narrow)
        if len(flattened) > LIMITS["phones"]:
            return None
        if i < len(words) - 1:
            join = len(flattened)
            gaps = [join]
            for gap in range(join - 1, max(word_start + 1, join - LIMITS["optionalSuffixPhones"]) - 1, -1):
                if gap not in optional:
                    break
                gaps.append(gap)
            result.append({"boundaryIndex": join, "leftWordIndex": i, "rightWordIndex": i + 1,
                           "eligibleGaps": gaps, "optionalSuffixHeuristic": len(gaps) > 1})
    return result if flattened == expected else None


def _reviewed(value, expected, joins):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > LIMITS["reviewedHypotheses"]:
        return None
    output, ids = [], set()
    boundaries = {join["boundaryIndex"] for join in joins}
    for hypothesis in value:
        if not isinstance(hypothesis, Mapping):
            return None
        identity, boundary = hypothesis.get("id"), hypothesis.get("boundaryIndex")
        alternative, provenance = _tokens(hypothesis.get("phones")), hypothesis.get("provenance")
        reason = hypothesis.get("reason")
        if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", identity)
                or identity in ids or type(boundary) is not int or boundary not in boundaries
                or alternative is None or not isinstance(reason, str) or not 0 < len(reason.strip()) <= 512
                or not isinstance(provenance, Mapping)
                or provenance.get("kind") != "human-reviewed"
                or not isinstance(provenance.get("sourceSHA256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", provenance["sourceSHA256"])
                or any(not isinstance(provenance.get(key), str)
                       or not 0 < len(provenance[key].strip()) <= 128
                       for key in ("annotationId", "reviewerId", "targetVariety"))):
            return None
        prefix, suffix = expected[:max(0, boundary - 2)], expected[boundary + 2:]
        if (alternative[:len(prefix)] != prefix or len(alternative) < len(prefix) + len(suffix)
                or (suffix and alternative[-len(suffix):] != suffix)):
            return None
        ids.add(identity)
        output.append({"id": identity, "boundaryIndex": boundary, "phones": alternative,
                       "reason": reason, "provenance": {key: provenance[key] for key in
                        ("kind", "sourceSHA256", "annotationId", "reviewerId", "targetVariety")}})
    return output


def _omitted_vowels(reviewed, expected):
    omitted = {}
    for hypothesis in reviewed:
        aligned = phones.align(expected, hypothesis["phones"], distance=lambda a, b: float(a != b))
        join = hypothesis["boundaryIndex"]
        for operation in aligned:
            index = operation["expectedIndex"]
            if (operation["op"] == "del" and operation["expected"][:1] in phones.VOWELS
                    and max(0, join - 2) <= index < min(len(expected), join + 2)):
                omitted.setdefault(index, []).append(hypothesis)
    return omitted


def _operations(value, expected, duration):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= LIMITS["operations"]:
        return None
    ei, ri, output = 0, 0, []
    previous_start, previous_end = 0., 0.
    for operation in value:
        if not isinstance(operation, Mapping):
            return None
        kind = operation.get("op")
        if kind not in ("match", "sub", "del", "ins"):
            return None
        if kind != "ins":
            if (ei >= len(expected) or type(operation.get("expectedIndex")) is not int
                    or operation["expectedIndex"] != ei or operation.get("expected") != expected[ei]):
                return None
            ei += 1
        elif operation.get("expectedIndex") is not None or operation.get("expected") is not None:
            return None
        if kind != "del":
            recognized = _tokens([operation.get("recognized")])
            if (recognized is None or len(recognized) != 1 or recognized[0] != operation["recognized"]
                    or type(operation.get("recognizedIndex")) is not int or operation["recognizedIndex"] != ri
                    or (kind == "match" and operation["recognized"] != operation["expected"])
                    or (kind == "sub" and operation["recognized"] == operation["expected"])):
                return None
            start, end = operation.get("start"), operation.get("end")
            if (any(v is not None and (not _number(v) or not 0 <= v <= duration) for v in (start, end))
                    or (start is not None and end is not None and end < start)
                    or (start is not None and start < previous_start)
                    or (end is not None and end < previous_end)):
                return None
            if start is not None:
                previous_start = start
            if end is not None:
                previous_end = end
            ri += 1
        elif operation.get("recognizedIndex") is not None or operation.get("recognized") is not None:
            return None
        output.append((ei if kind == "ins" else ei - 1, operation))
    return output if ei == len(expected) else None


def analyze(expected, words, pronunciation, *, reviewed_boundaries=None, duration_seconds=None):
    """Nominate vowel insertions and reviewed vowel disagreements at word joins.

    Canonical optional vowels cannot be identified as extra through insertion
    analysis alone. A reviewed path omitting a canonical vowel can nominate a
    timed realization for comparison; it still cannot prove wrong liaison.

    Reviewed hypotheses: bounded {id, boundaryIndex, phones (full path), reason,
    provenance: {kind: human-reviewed, sourceSHA256, annotationId, reviewerId,
    targetVariety}}. boundaryIndex is a gap in flattened narrow canonical phones,
    not a word or raw-token index. Changes must be local to two canonical phones
    either side. Provenance is a caller assertion; this pure function does not
    authenticate reviewers or resolve annotation source bytes. Alternative matches
    mean exact recognizer sequence equality only, never linguistic acceptance.
    """
    result = {"schema": SCHEMA, "inputStatus": "unavailable", "qualification": "uncalibrated",
              "decision": "not-assessed", "nativeAccentDecision": "not-assessed", "reportOnly": True,
              "limits": dict(LIMITS), "settings": {"insertionLocation": "exact-join-or-optional-suffix",
                  "alternativeMatch": "exact-full-recognized-path", "linguisticPermission": "not-assessed"},
              "coverage": {"wordBoundaries": 0, "roles": {}}, "reviewedHypotheses": [], "candidates": [],
              "limitations": ["recognizer-and-g2p-bias", "optional-suffix-is-not-liaison-permission",
                  "single-witness-is-not-confirmed-defect", "alternative-match-is-not-acceptance",
                  "no-qualified-defect-threshold", "unheard-insertions-cannot-be-detected",
                  "canonical-optional-vowel-needs-reviewed-comparison"]}
    canonical = _tokens(expected)
    joins = _joins(canonical, words) if canonical is not None else None
    if joins is None:
        result["reason"] = "missing-invalid-or-incomplete-word-coverage"
        return result
    if (duration_seconds is not None and (not _number(duration_seconds)
            or not 0 < duration_seconds <= LIMITS["seconds"])):
        result["reason"] = "invalid-or-excessive-duration"
        return result
    reviewed = _reviewed(reviewed_boundaries, canonical, joins)
    if reviewed is None:
        result["reason"] = "invalid-or-excessive-reviewed-hypotheses"
        return result
    if (not isinstance(pronunciation, Mapping) or pronunciation.get("expectedTokens") != list(expected)
            or not isinstance(pronunciation.get("roles"), Mapping)):
        result["reason"] = "missing-or-mismatched-pronunciation"
        return result
    result["reviewedHypotheses"] = reviewed
    omitted_vowels = _omitted_vowels(reviewed, canonical)
    result["coverage"]["reviewedHypotheses"] = len(reviewed)
    result["coverage"]["reviewedComparisonStatus"] = "available" if reviewed else "unavailable"
    result["coverage"]["reviewedOmittedCanonicalVowels"] = len(omitted_vowels)
    result["coverage"]["wordBoundaries"] = len(joins)
    result["coverage"]["durationVerified"] = duration_seconds is not None
    complete = 0
    for role in ROLES:
        evidence = pronunciation["roles"].get(role)
        coverage = {"inputStatus": "unavailable", "timedInsertions": 0, "untimedInsertions": 0,
                    "reviewedAlternativeMatches": [], "timedReviewedVowelDisagreements": 0,
                    "untimedReviewedVowelDisagreements": 0}
        result["coverage"]["roles"][role] = coverage
        operations = _operations(evidence.get("narrowAlignment"), canonical,
            duration_seconds if duration_seconds is not None else LIMITS["seconds"]) if isinstance(evidence, Mapping) else None
        if operations is None or evidence.get("inputStatus") != "complete":
            coverage["reason"] = "missing-partial-or-invalid-narrow-alignment"
            continue
        recognized = [op["recognized"] for _, op in operations if op["op"] != "del"]
        matches = [item for item in reviewed if item["phones"] == recognized]
        coverage["reviewedAlternativeMatches"] = [item["id"] for item in matches]
        for gap, operation in operations:
            if operation["op"] != "ins" or operation["recognized"][:1] not in phones.VOWELS:
                continue
            boundaries = [join for join in joins if gap in join["eligibleGaps"]]
            if not boundaries:
                continue
            start, end = operation.get("start"), operation.get("end")
            if (not _number(start) or not _number(end) or not 0 <= start < end
                    or end > (duration_seconds if duration_seconds is not None else LIMITS["seconds"])):
                coverage["untimedInsertions"] += 1
                continue
            if len(result["candidates"]) >= LIMITS["candidates"]:
                coverage["reason"] = "candidate-budget-exceeded"
                break
            coverage["timedInsertions"] += 1
            result["candidates"].append({"id": f"{role}-boundary-{operation['recognizedIndex']}",
                "class": "boundary-pronunciation", "candidateType": "vowel-bearing-boundary-insertion",
                "status": "candidate", "evidenceStatus": "single-witness", "source": role,
                "start": float(start), "end": float(end), "phone": operation["recognized"],
                "recognizedIndex": operation["recognizedIndex"], "expectedGapIndex": gap,
                "boundaries": boundaries, "reviewedAlternativeMatches": [item["id"] for item in matches
                    if item["boundaryIndex"] in {join["boundaryIndex"] for join in boundaries}],
                "timingSource": "recognized-phone", "uncertainty": ["recognizer-timing-approximate",
                    "canonical-alignment-may-be-ambiguous", "vowel-label-is-not-acoustic-verification"]})
        for index, operation in operations:
            hypotheses = omitted_vowels.get(index, []) if operation["op"] == "match" else []
            if not hypotheses:
                continue
            start, end = operation.get("start"), operation.get("end")
            if not _number(start) or not _number(end) or end <= start:
                coverage["untimedReviewedVowelDisagreements"] += 1
                continue
            if len(result["candidates"]) >= LIMITS["candidates"]:
                coverage["reason"] = "candidate-budget-exceeded"
                break
            coverage["timedReviewedVowelDisagreements"] += 1
            result["candidates"].append({"id": f"{role}-reviewed-vowel-{operation['recognizedIndex']}",
                "class": "boundary-pronunciation", "candidateType": "reviewed-boundary-vowel-disagreement",
                "status": "candidate", "evidenceStatus": "single-witness", "source": role,
                "start": float(start), "end": float(end), "phone": operation["recognized"],
                "expectedIndex": index, "recognizedIndex": operation["recognizedIndex"],
                "boundaryIndices": sorted({hypothesis["boundaryIndex"] for hypothesis in hypotheses}),
                "reviewedHypotheses": [hypothesis["id"] for hypothesis in hypotheses],
                "timingSource": "recognized-phone", "uncertainty": ["recognizer-timing-approximate",
                    "reviewed-path-alignment-may-be-ambiguous", "realized-vowel-is-not-wrong-liaison-proof",
                    "vowel-label-is-not-acoustic-verification"]})
        coverage["inputStatus"] = "partial" if (coverage["untimedInsertions"]
            or coverage["untimedReviewedVowelDisagreements"] or coverage.get("reason")) else "complete"
        complete += coverage["inputStatus"] == "complete"
    result["inputStatus"] = "complete" if complete == len(ROLES) else "partial" if any(
        entry["inputStatus"] != "unavailable" for entry in result["coverage"]["roles"].values()) else "unavailable"
    return result
