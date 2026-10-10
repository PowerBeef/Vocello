"""Uncalibrated, narrow phonetic evidence. Never native-accent acceptance.

Keep the recognizers' original IPA tokens (including stress/length/diacritics),
and align a narrow view without broad-rhotic folding, near-identity forgiveness,
or optional liaison/schwa removal. Disagreement is recognizer evidence, not a
pronunciation verdict; two recognizers can share errors. No inferred L1 label.
"""
from __future__ import annotations
import math
import numpy as np
from qc import phones

SCHEMA = "vocello.qc.phonetic-evidence/1"


def french(expected: list[str] | None, outputs: dict) -> dict:
    result = {"schema": SCHEMA, "qualification": "uncalibrated",
              "nativeAccentDecision": "not-assessed", "roles": {}, "agreedEvents": [],
              "limitations": ["recognizer-bias", "g2p-variant-bias", "target-dialect-unspecified",
                              "no-validated-accent-or-local-defect-threshold"]}
    if not expected:
        result["inputStatus"] = "unavailable"
        result["reason"] = "missing-expected-phones"
        return result
    narrow = [part for token in expected for part in phones.segment_ipa(token)]
    result["expectedTokens"] = expected
    event_maps = []
    for role in ("phones", "phonesB"):
        output = outputs.get(role)
        if not isinstance(output, dict) or not output.get("phones"):
            result["roles"][role] = {"inputStatus": "unavailable"}
            continue
        original = output["phones"]
        heard = []
        for token in original:
            token = {"phone": token} if isinstance(token, str) else token
            parts = phones.segment_ipa(token["phone"])
            for part in parts:
                heard.append(dict(token, phone=part))
        ops = phones.align(narrow, heard, distance=lambda a, b: float(a != b))
        events = [op for op in ops if op["op"] != "match"]
        result["roles"][role] = {"inputStatus": "complete", "originalTokens": original,
                                  "events": events, "expectedCount": len(narrow), "heardCount": len(heard)}
        # Insertions match by the preceding expected position, not by output array index.
        position, positions = -1, []
        for op in ops:
            if op.get("expectedIndex") is not None:
                position = op["expectedIndex"]
            if op["op"] != "match":
                positions.append(((op["op"], position, op.get("expected"), op.get("recognized")), op))
        event_maps.append(dict(positions))
    available = sum(item["inputStatus"] == "complete" for item in result["roles"].values())
    result["inputStatus"] = "complete" if available == 2 else "partial" if available else "unavailable"
    if len(event_maps) == 2:
        for key in sorted(event_maps[0].keys() & event_maps[1].keys(), key=str):
            a, b = event_maps[0][key], event_maps[1][key]
            if a.get("start") is not None and b.get("start") is not None and abs(a["start"] - b["start"]) > .06:
                continue  # no temporal consensus from distinct locations
            result["agreedEvents"].append({"operation": key[0], "expectedIndex": key[1],
                "expected": key[2], "recognized": key[3], "evidence": {"phones": a, "phonesB": b}})
    return result


def local_acoustics(outputs: dict, profile: dict, speech_median: float | None) -> dict:
    """Descriptive energy/periodicity on recognized French vowel/sonorant windows.

    Recognizer timing is approximate; low energy/periodicity alone never proves
    a whispered or missing syllable. Keep fricatives and stop closures out of
    the voiced-target view. These statistics need no additional model.
    """
    result = {"qualification": "uncalibrated", "decision": "not-assessed", "roles": {},
              "limitations": ["recognizer-timing-approximate", "periodicity-range-60-to-400Hz",
                              "no-qualified-whisper-threshold"]}
    voiced_targets = set("aeiouyɑɒæəɛɜɞɐɔœøɶɨɪʉʊʌɯɤmnɲŋlʎʁɹrjɥw")
    for role in ("phones", "phonesB"):
        windows = []
        for token in (outputs.get(role) or {}).get("phones") or []:
            if not isinstance(token, dict):
                continue
            narrow = phones.segment_ipa(token.get("phone", ""))
            if not narrow or narrow[0][0] not in voiced_targets:
                continue
            start, end = token.get("start"), token.get("end")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end)) or end <= start:
                continue
            mask = (profile["time"] >= max(0, start)) & (profile["time"] < end)
            if not mask.any():
                continue
            level = float(np.median(profile["level"][mask]))
            windows.append({"phone": token["phone"], "start": start, "end": end,
                "frames": int(mask.sum()), "medianLevelDbfs": round(level, 4),
                "levelRelativeSpeechDb": round(level - speech_median, 4) if speech_median is not None else None,
                "medianPeriodicity": round(float(np.median(profile["periodicity"][mask])), 4),
                "medianCentroidHz": round(float(np.median(profile["centroid"][mask])), 3)})
        result["roles"][role] = {"inputStatus": "complete" if windows else "unavailable", "windows": windows}
    return result
