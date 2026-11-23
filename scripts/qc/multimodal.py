"""Offline, report-only multimodal audio QC complement (`RF-72`).

Prepares strictly blinded, opaque-token audio review packets (`review-packet.json`)
for Gemini 4 Neon via Antigravity's native `read_file` and `run_workflow` tools,
reconciles dual-order A/B swaps and Pass 1/Pass 2 verdicts, joins findings beside
QC v2 objective metrics, and computes privacy-safe Q1/Q2 qualification evaluations.

Design invariants:
- Strictly outside `qc.detectors.SCORING_SOURCES` (existing QC v2 `scoringSHA256`
  and calibrated thresholds never change).
- Strictly report-only advisory (`neverGates: true`): never replaces Fast QC,
  never clears a machine failure, and never overrides `RF-57` decision rules.
- Privacy boundary: refuses personal recordings and paths outside allowlisted
  non-personal roots by default; synthetic confirm batches require explicit
  `allow_synthetic_confirm_batches=True` and enforce `not confirm.is_clone(take)`.
- Zero raw audio, transcripts, prompts or private paths in public eval artifacts.
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from qc import confirm, fit, label, multimodal_audio, store
from qc.store import Layout

RUBRIC_SCHEMA = "vocello.qc.multimodal.rubric/1"
PACKET_SCHEMA = "vocello.qc.multimodal.packet/1"
VERDICTS_SCHEMA = "vocello.qc.multimodal.verdicts/1"
REPORT_SCHEMA = "vocello.qc.multimodal.report/1"
EVAL_SCHEMA = "vocello.qc.multimodal.eval/1"
RUBRIC_FILENAME = "multimodal-rubric-v1.json"
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

EMOTION_BRIEFS = {
    "neutral": "Calm, steady, neutral read narration with no heightened emotion.",
    "angry": "Intense, forceful, angry delivery with clear vocal tension.",
    "happy": "Warm, upbeat, cheerful and joyful delivery.",
    "sad": "Somber, downcast, melancholic delivery with low energy.",
    "fearful": "Anxious, trembling, fearful delivery.",
    "disgusted": "Repulsed, disgusted delivery with clear distaste.",
    "surprised": "Startled, amazed, surprised delivery.",
}

EMOTION_CONTRADICTIONS = {
    "angry": "neutral",
    "neutral": "angry",
    "happy": "sad",
    "sad": "happy",
}


class MultimodalError(ValueError):
    """Invalid multimodal packet, session, verdict or qualification input."""


class PrivacyBoundaryError(MultimodalError):
    """Audio path or take violates the non-personal multimodal privacy boundary."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def validate_session_name(name: str) -> str:
    if not isinstance(name, str) or not SESSION_RE.fullmatch(name):
        raise MultimodalError(f"invalid multimodal session name: {name!r}")
    return name


def multimodal_root(layout: Layout) -> Path:
    return layout.private / "multimodal"


def session_dir(layout: Layout, session: str) -> Path:
    return multimodal_root(layout) / validate_session_name(session)


def load_rubric(layout: Layout) -> tuple[dict[str, Any], str]:
    path = layout.config / RUBRIC_FILENAME
    if not path.is_file():
        raise MultimodalError(f"missing rubric contract: {path}")
    rubric = store.read_json(path)
    if not isinstance(rubric, dict) or rubric.get("schema") != RUBRIC_SCHEMA:
        raise MultimodalError(f"unsupported multimodal rubric schema in {path.name}")
    if rubric.get("neverGates") is not True or rubric.get("status") != "report-only-advisory":
        raise MultimodalError("multimodal rubric must remain strictly report-only and never-gating")
    return rubric, store.sha256_file(path)


def allowlisted_roots(layout: Layout, *, allow_synthetic_confirm_batches: bool = False) -> tuple[Path, ...]:
    roots = [
        (layout.root / "build/cache/audio-qc-corpora").resolve(),
        (layout.root / "build/artifacts").resolve(),
        layout.work.resolve(),
        layout.runs.resolve(),
        (layout.private / "manifests").resolve(),
    ]
    if allow_synthetic_confirm_batches:
        roots.append((layout.private / "confirm").resolve())
    return tuple(roots)


def validate_audio_source(
    layout: Layout,
    source: Path | str,
    *,
    take: dict[str, Any] | None = None,
    allow_synthetic_confirm_batches: bool = False,
) -> Path:
    """Fail closed unless `source` resolves inside an allowlisted non-personal root."""

    if take is not None:
        if take.get("personal") is True or str(take.get("privacy") or "").lower() == "personal":
            raise PrivacyBoundaryError("personal audio takes are forbidden in multimodal cloud review")
        if allow_synthetic_confirm_batches and confirm.is_clone(take):
            raise PrivacyBoundaryError("clone takes are never permitted in synthetic confirm batches")
    raw_path = Path(source)
    if not raw_path.is_file():
        raise MultimodalError(f"audio source does not exist: {raw_path.name}")
    resolved = raw_path.resolve()
    allowed = allowlisted_roots(layout, allow_synthetic_confirm_batches=allow_synthetic_confirm_batches)
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise PrivacyBoundaryError(
            "audio source lies outside allowlisted non-personal QC roots; personal recordings are refused"
        )
    confirm_root = (layout.private / "confirm").resolve()
    if resolved.is_relative_to(confirm_root) and not allow_synthetic_confirm_batches:
        raise PrivacyBoundaryError(
            "synthetic confirm batches require explicit --allow-synthetic-confirm-batches opt-in"
        )
    return resolved


def _opaque_id(prefix: str, rng: random.Random) -> str:
    return f"{prefix}_{rng.getrandbits(48):012x}"


def _marker_from_rubric(rubric: dict[str, Any]) -> np.ndarray:
    cfg = rubric["audio"]
    return multimodal_audio.make_marker_tone(
        rate=int(cfg["sampleRateHz"]),
        silence_s=float(cfg["markerSilenceSeconds"]),
        tone_s=float(cfg["markerToneSeconds"]),
        freq_hz=float(cfg["markerToneHz"]),
        dbfs=float(cfg["markerToneDbfs"]),
        fade_s=float(cfg["markerFadeSeconds"]),
    )


def _stage_array(audio_dir: Path, token: str, samples: np.ndarray, rate: int) -> tuple[Path, dict[str, Any]]:
    target = audio_dir / f"{token}.wav"
    meta = multimodal_audio.write_wav_pcm16(target, samples, rate=rate)
    return target, meta


def _rel(layout: Layout, path: Path) -> str:
    return str(path.resolve().relative_to(layout.root.resolve()))


def _extract_candidate_centers(
    feature_row: dict[str, Any] | None,
    event_row: dict[str, Any] | None,
    *,
    max_windows: int,
    min_spacing_s: float = 1.5,
) -> list[tuple[float, str]]:
    """Pick up to `max_windows` distinct suspicious centers from retained QC v2 evidence."""

    raw_centers: list[tuple[int, float, str]] = []
    if event_row:
        for ev in event_row.get("events") or []:
            start, end = ev.get("start"), ev.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
                cls = str(ev.get("class") or "event")
                priority = {"pronunciation": 0, "boundary-pronunciation": 1, "phonation-anomaly": 2,
                            "short-fragment": 3}.get(cls, 4)
                raw_centers.append((priority, 0.5 * (float(start) + float(end)), cls))
    if feature_row:
        feats = feature_row.get("features") or {}
        for key, priority in (("phones.low_gop_run", 1), ("pause.longest_gap_seconds", 2)):
            item = feats.get(key) or {}
            start, end = item.get("start"), item.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
                raw_centers.append((priority, 0.5 * (float(start) + float(end)), key))
    raw_centers.sort(key=lambda entry: (entry[0], entry[1]))
    chosen: list[tuple[float, str]] = []
    for _, center, reason in raw_centers:
        if all(abs(center - existing) >= min_spacing_s for existing, _ in chosen):
            chosen.append((center, reason))
            if len(chosen) >= max_windows:
                break
    return chosen


def _corpus_manifest(layout: Layout, corpus_name: str) -> tuple[Path, list[dict[str, Any]]]:
    corpus_root = layout.root / "build/cache/audio-qc-corpora" / corpus_name
    manifests = sorted(corpus_root.glob("*/extracted/manifest.json"))
    if len(manifests) != 1:
        raise MultimodalError(f"corpus {corpus_name!r} is not extracted once under build/cache/audio-qc-corpora")
    return manifests[0].parent, store.read_json(manifests[0])["clips"]


def _ci_summary(successes: int, trials: int) -> dict[str, Any]:
    if trials <= 0:
        return {"n": 0, "successes": 0, "rate": None, "lower": None, "upper": None}
    lo, hi = fit.clopper_pearson(successes, trials)
    return {
        "n": int(trials),
        "successes": int(successes),
        "rate": round(successes / trials, 4),
        "lower": round(lo, 4) if lo is not None else None,
        "upper": round(hi, 4) if hi is not None else None,
    }


def _usable_from_judgments(blind: dict[str, Any] | None, diction: dict[str, Any] | None,
                           delivery: dict[str, Any] | None, clone: dict[str, Any] | None) -> str:
    """Conservative rollup of Pass 2 axis verdicts into a single clip-level usability call."""

    verdicts = [
        item.get("overallUsability")
        for item in (diction, delivery, clone)
        if isinstance(item, dict) and item.get("overallUsability")
    ]
    if "unusable" in verdicts:
        return "unusable"
    if "borderline" in verdicts:
        return "borderline"
    if "usable" in verdicts:
        return "usable"
    if "uncertain" in verdicts:
        return "uncertain"
    if blind and any(d.get("severity") == "severe" for d in blind.get("audibleDefects") or []):
        return "unusable"
    return "uncertain"


# --- Packet preparation --------------------------------------------------------


def prepare_qc_run(
    layout: Layout,
    run_id: str,
    *,
    session: str | None = None,
    limit: int | None = None,
    seed: int = 0,
    include_local_zoom: bool = True,
) -> dict[str, Any]:
    """Prepare a blinded review packet from an existing QC v2 run directory."""

    rubric, rubric_sha = load_rubric(layout)
    run_dir = layout.runs / run_id
    if not run_id or Path(run_id).name != run_id or not (run_dir / "takes.json").is_file():
        raise MultimodalError(f"QC run {run_id!r} not found under build/private/qc/runs")
    takes_doc = store.read_json(run_dir / "takes.json")
    features_by_token = {
        row["token"]: row
        for row in (store.read_json(run_dir / "features.json").get("takes") or [])
    } if (run_dir / "features.json").is_file() else {}
    events_by_token = {
        row["token"]: row
        for row in (store.read_json(run_dir / "events.json").get("takes") or [])
    } if (run_dir / "events.json").is_file() else {}
    flags_by_token = {
        row["token"]: row
        for row in (store.read_json(run_dir / "flags.json").get("takes") or [])
    } if (run_dir / "flags.json").is_file() else {}

    takes = list(takes_doc.get("takes") or [])
    rng = random.Random(f"vocello.qc.multimodal.run/1:{run_id}:{seed}")
    if limit is not None and limit > 0 and len(takes) > limit:
        # Prioritize flagged takes first, then fill evenly across remaining takes.
        flagged = [t for t in takes if (flags_by_token.get(t["token"]) or {}).get("flags")]
        unflagged = [t for t in takes if t not in flagged]
        rng.shuffle(flagged)
        rng.shuffle(unflagged)
        takes = (flagged + unflagged)[:limit]
    rng.shuffle(takes)

    session_name = validate_session_name(session or f"run-{run_id}-{utc_stamp()}")
    out_dir = session_dir(layout, session_name)
    if out_dir.exists():
        raise FileExistsError(f"multimodal session already exists: {session_name}")
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=False)

    rate = int(rubric["audio"]["sampleRateHz"])
    marker = _marker_from_rubric(rubric)
    zoom_s = float(rubric["audio"]["localZoomWindowSeconds"])
    max_zooms = int(rubric["audio"]["maxLocalZoomWindows"])
    ref_max_s = float(rubric["audio"]["cloneReferenceMaxSeconds"])
    lf_slice_s = float(rubric["audio"]["longformSliceSeconds"])
    lf_min_s = float(rubric["audio"]["longformMinDurationSeconds"])

    blind_tasks: list[dict[str, Any]] = []
    audit_tasks: list[dict[str, Any]] = []
    private_items: dict[str, Any] = {}
    qc_context: dict[str, Any] = {}

    for take in takes:
        src = validate_audio_source(layout, take["audio"], take=take)
        samples = multimodal_audio.load_normalized_16k(src, target_rate=rate)
        tok = _opaque_id("t", rng)
        staged, meta = _stage_array(audio_dir, tok, samples, rate)

        zoom_paths: list[dict[str, Any]] = []
        if include_local_zoom:
            centers = _extract_candidate_centers(
                features_by_token.get(take["token"]),
                events_by_token.get(take["token"]),
                max_windows=max_zooms,
            )
            for idx, (center_s, _) in enumerate(centers, start=1):
                crop, start_s, end_s = multimodal_audio.crop_window(samples, rate, center_s, window_s=zoom_s)
                ztok = _opaque_id("z", rng)
                zpath, zmeta = _stage_array(audio_dir, ztok, crop, rate)
                zoom_paths.append({
                    "zoomToken": ztok,
                    "audioPath": _rel(layout, zpath),
                    "windowStartSeconds": start_s,
                    "windowEndSeconds": end_s,
                    "durationSeconds": zmeta["durationSeconds"],
                    "index": idx,
                })

        clone_pair_path: str | None = None
        clone_timeline: list[dict[str, float]] | None = None
        if take.get("reference"):
            ref_src = validate_audio_source(layout, take["reference"], take=take)
            ref_samples = multimodal_audio.load_normalized_16k(ref_src, target_rate=rate, max_seconds=ref_max_s)
            stitched, clone_timeline = multimodal_audio.stitch_segments([ref_samples, samples], rate=rate, marker=marker)
            ctok = _opaque_id("c", rng)
            cpath, _ = _stage_array(audio_dir, ctok, stitched, rate)
            clone_pair_path = _rel(layout, cpath)

        longform_path: str | None = None
        if meta["durationSeconds"] >= lf_min_s:
            slices = multimodal_audio.build_longform_slices(
                samples, rate=rate, slice_s=lf_slice_s, min_duration_s=lf_min_s
            )
            if len(slices) > 1:
                lf_stitched, _ = multimodal_audio.stitch_segments(slices, rate=rate, marker=marker)
                ltok = _opaque_id("l", rng)
                lpath, _ = _stage_array(audio_dir, ltok, lf_stitched, rate)
                longform_path = _rel(layout, lpath)

        blind_tasks.append({
            "taskId": f"blind-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "durationSeconds": meta["durationSeconds"],
            "kind": "single",
        })
        audit_tasks.append({
            "taskId": f"audit-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "localZooms": zoom_paths,
            "clonePairAudioPath": clone_pair_path,
            "cloneTimeline": clone_timeline,
            "longformConsistencyAudioPath": longform_path,
            "durationSeconds": meta["durationSeconds"],
            "language": take.get("language"),
            "intendedText": take.get("text"),
            "effectiveBrief": take.get("delivery") or take.get("voiceDescription") or "neutral",
            "hasReference": bool(clone_pair_path),
            "axes": ["diction", "delivery"] + (["clone"] if clone_pair_path else []),
        })
        private_items[tok] = {
            "takeToken": take["token"],
            "takeID": take.get("takeID"),
            "language": take.get("language"),
            "mode": take.get("mode"),
            "audioSHA256": take.get("audioSHA256"),
            "stagedSHA256": meta["sha256"],
        }
        feat_map = (features_by_token.get(take["token"]) or {}).get("features") or {}
        qc_context[tok] = {
            "flags": [f.get("detector") for f in (flags_by_token.get(take["token"]) or {}).get("flags") or []],
            "asrPhoneticErrorMin": (feat_map.get("asr.phonetic_error_min") or {}).get("value"),
            "speakerWholeDistance": (feat_map.get("speaker.whole_distance") or {}).get("value"),
            "pitchRegisterOffsetSt": (feat_map.get("pitch.register_offset_st") or {}).get("value"),
        }

    packet = {
        "schema": PACKET_SCHEMA,
        "session": session_name,
        "kind": "qc-run",
        "createdAt": utc_now(),
        "rubricSchema": RUBRIC_SCHEMA,
        "rubricSHA256": rubric_sha,
        "targetModel": rubric["targetModel"],
        "advisoryOnly": True,
        "neverGates": True,
        "blindTasks": blind_tasks,
        "auditTasks": audit_tasks,
        "pairwiseTasks": [],
    }
    store.write_json_atomic(out_dir / "review-packet.json", packet)
    store.write_json_atomic(out_dir / "private-key.json", {
        "session": session_name, "kind": "qc-run", "sourceRun": run_id, "items": private_items,
    })
    store.write_json_atomic(out_dir / "qc-context.json", {"session": session_name, "context": qc_context})
    return {
        "session": session_name,
        "packetPath": _rel(layout, out_dir / "review-packet.json"),
        "takes": len(blind_tasks),
        "clonePairs": sum(1 for item in audit_tasks if item["hasReference"]),
        "localZooms": sum(len(item["localZooms"]) for item in audit_tasks),
    }


def prepare_screen_ab(
    layout: Layout,
    screen_run: Path | str,
    arm_a: str,
    arm_b: str,
    *,
    session: str | None = None,
    limit: int = 24,
    seed: int = 0,
) -> dict[str, Any]:
    """Prepare a blinded, dual-order (AB + BA) pairwise packet from a `quality_screen.py` run."""

    rubric, rubric_sha = load_rubric(layout)
    run_root = Path(screen_run).resolve()
    plan_path = run_root / "plan.json"
    if not plan_path.is_file():
        raise MultimodalError(f"missing plan.json in screen run: {screen_run}")
    plan = store.read_json(plan_path)
    dir_a = run_root / "arms" / arm_a
    dir_b = run_root / "arms" / arm_b
    takes_a = {row["takeID"]: row for row in store.read_json(dir_a / "takes.json")["takes"]}
    takes_b = {row["takeID"]: row for row in store.read_json(dir_b / "takes.json")["takes"]}
    scores_a = (
        {row["takeID"]: row for row in store.read_json(dir_a / "scores.json").get("takes", [])}
        if (dir_a / "scores.json").is_file() else {}
    )
    scores_b = (
        {row["takeID"]: row for row in store.read_json(dir_b / "scores.json").get("takes", [])}
        if (dir_b / "scores.json").is_file() else {}
    )
    voices_by_name = {v["voice"]: v for v in plan.get("voices") or []}

    eligible: list[tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for planned in plan.get("takes") or []:
        tid = planned["takeID"]
        ra, rb = takes_a.get(tid), takes_b.get(tid)
        if not ra or not rb or ra.get("outcome") != "generated" or rb.get("outcome") != "generated":
            continue
        if ra.get("pcmSHA256") and ra.get("pcmSHA256") == rb.get("pcmSHA256"):
            continue  # identical PCM carries no pairwise signal
        # Prioritize takes where objective metrics disagree most, while preserving stratification.
        sa, sb = scores_a.get(tid) or {}, scores_b.get(tid) or {}
        delta = 0.0
        for metric in ("speakerSimilarity", "betterEditRate"):
            va, vb = sa.get(metric), sb.get(metric)
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                delta += abs(float(va) - float(vb))
        eligible.append((delta, planned, ra, rb))
    if not eligible:
        raise MultimodalError(f"no differing generated pairs found between arms {arm_a!r} and {arm_b!r}")

    rng = random.Random(f"vocello.qc.multimodal.screen/1:{plan.get('screen')}:{arm_a}:{arm_b}:{seed}")
    by_lang: dict[str, list[tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]]]] = {}
    for entry in eligible:
        lang = str(entry[1].get("language") or entry[1].get("requestLanguage") or "unknown")
        by_lang.setdefault(lang, []).append(entry)
    for bucket in by_lang.values():
        bucket.sort(key=lambda e: (-e[0], e[1]["takeID"]))
    selected: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    cap = max(1, int(limit)) if limit else len(eligible)
    while len(selected) < cap and any(by_lang.values()):
        for lang in sorted(by_lang):
            if by_lang[lang] and len(selected) < cap:
                _, planned, ra, rb = by_lang[lang].pop(0)
                selected.append((planned, ra, rb))

    session_name = validate_session_name(session or f"screen-{arm_a}-vs-{arm_b}-{utc_stamp()}")
    out_dir = session_dir(layout, session_name)
    if out_dir.exists():
        raise FileExistsError(f"multimodal session already exists: {session_name}")
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=False)

    rate = int(rubric["audio"]["sampleRateHz"])
    marker = _marker_from_rubric(rubric)
    ref_max_s = float(rubric["audio"]["cloneReferenceMaxSeconds"])
    lf_slice_s = float(rubric["audio"]["longformSliceSeconds"])
    lf_min_s = float(rubric["audio"]["longformMinDurationSeconds"])

    pairwise_tasks: list[dict[str, Any]] = []
    private_pairs: dict[str, Any] = {}
    order_lookup: dict[str, Any] = {}

    for planned, ra, rb in selected:
        wav_a = validate_audio_source(layout, dir_a / ra["wav"])
        wav_b = validate_audio_source(layout, dir_b / rb["wav"])
        samp_a = multimodal_audio.load_normalized_16k(wav_a, target_rate=rate)
        samp_b = multimodal_audio.load_normalized_16k(wav_b, target_rate=rate)
        if plan.get("kind") == "long-form":
            slices_a = multimodal_audio.build_longform_slices(samp_a, rate=rate, slice_s=lf_slice_s, min_duration_s=lf_min_s)
            slices_b = multimodal_audio.build_longform_slices(samp_b, rate=rate, slice_s=lf_slice_s, min_duration_s=lf_min_s)
            if len(slices_a) > 1:
                samp_a, _ = multimodal_audio.stitch_segments(slices_a, rate=rate, marker=np.zeros(int(0.25 * rate)))
            if len(slices_b) > 1:
                samp_b, _ = multimodal_audio.stitch_segments(slices_b, rate=rate, marker=np.zeros(int(0.25 * rate)))

        ref_samples = None
        voice_name = planned.get("voice")
        if voice_name and voice_name in voices_by_name:
            ref_path = validate_audio_source(layout, voices_by_name[voice_name]["audio"])
            ref_samples = multimodal_audio.load_normalized_16k(ref_path, target_rate=rate, max_seconds=ref_max_s)

        pair_token = _opaque_id("pair", rng)
        private_pairs[pair_token] = {
            "takeID": planned["takeID"],
            "language": planned.get("language") or planned.get("requestLanguage"),
            "armA": arm_a,
            "armB": arm_b,
            "hasReference": ref_samples is not None,
            "scoresA": scores_a.get(planned["takeID"]),
            "scoresB": scores_b.get(planned["takeID"]),
        }

        for orientation, first_arm, second_arm, s1, s2 in (
            ("ab", arm_a, arm_b, samp_a, samp_b),
            ("ba", arm_b, arm_a, samp_b, samp_a),
        ):
            order_token = _opaque_id("ord", rng)
            segments = [ref_samples, s1, s2] if ref_samples is not None else [s1, s2]
            stitched, timeline = multimodal_audio.stitch_segments(segments, rate=rate, marker=marker)
            staged, meta = _stage_array(audio_dir, order_token, stitched, rate)
            pairwise_tasks.append({
                "taskId": f"pair-{order_token}",
                "orderToken": order_token,
                "audioPath": _rel(layout, staged),
                "durationSeconds": meta["durationSeconds"],
                "clipCount": len(segments),
                "hasReferenceFirst": ref_samples is not None,
                "timeline": timeline,
                "language": planned.get("language") or planned.get("requestLanguage"),
                "intendedText": planned.get("text"),
                "effectiveBrief": planned.get("brief") or planned.get("delivery") or "neutral",
                "kind": "screen-pairwise",
            })
            order_lookup[order_token] = {
                "pairToken": pair_token,
                "orientation": orientation,
                "clip1Arm": first_arm,
                "clip2Arm": second_arm,
            }

    # Shuffle independently so AB and BA never appear adjacent or predictably ordered.
    rng.shuffle(pairwise_tasks)
    packet = {
        "schema": PACKET_SCHEMA,
        "session": session_name,
        "kind": "screen-ab",
        "createdAt": utc_now(),
        "rubricSchema": RUBRIC_SCHEMA,
        "rubricSHA256": rubric_sha,
        "targetModel": rubric["targetModel"],
        "advisoryOnly": True,
        "neverGates": True,
        "blindTasks": [],
        "auditTasks": [],
        "pairwiseTasks": pairwise_tasks,
    }
    store.write_json_atomic(out_dir / "review-packet.json", packet)
    store.write_json_atomic(out_dir / "private-key.json", {
        "session": session_name,
        "kind": "screen-ab",
        "screenRun": _rel(layout, run_root) if run_root.is_relative_to(layout.root.resolve()) else run_root.name,
        "armA": arm_a,
        "armB": arm_b,
        "pairs": private_pairs,
        "orders": order_lookup,
    })
    return {
        "session": session_name,
        "packetPath": _rel(layout, out_dir / "review-packet.json"),
        "pairs": len(private_pairs),
        "pairwiseTasks": len(pairwise_tasks),
    }


def prepare_q1_controls(
    layout: Layout,
    *,
    session: str = "q1-controls-v1",
    seed: int = 20261122,
) -> dict[str, Any]:
    """Build the 5-control Q1 bias & capability benchmark purely from cached public corpora."""

    rubric, rubric_sha = load_rubric(layout)
    session_name = validate_session_name(session)
    out_dir = session_dir(layout, session_name)
    if out_dir.exists():
        raise FileExistsError(f"multimodal session already exists: {session_name}")
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=False)

    mls_root, mls_clips = _corpus_manifest(layout, "mls")
    lib_root, lib_clips = _corpus_manifest(layout, "libritts-r")
    emo_root, emo_clips = _corpus_manifest(layout, "emozionalmente")

    rng = random.Random(f"vocello.qc.multimodal.q1/1:{seed}")
    rate = int(rubric["audio"]["sampleRateHz"])
    marker = _marker_from_rubric(rubric)

    fr_clips = [c for c in mls_clips if c.get("language") == "french" and 4.0 <= float(c.get("durationSeconds") or 0) <= 13.0]
    en_clips = [c for c in lib_clips if c.get("language") == "english" and 3.0 <= float(c.get("durationSeconds") or 0) <= 12.0]
    fr_clips.sort(key=lambda c: c["clipID"])
    en_clips.sort(key=lambda c: c["clipID"])
    rng.shuffle(fr_clips)
    rng.shuffle(en_clips)

    def load_clip(root: Path, clip: dict[str, Any], *, max_s: float = 9.0) -> np.ndarray:
        path = validate_audio_source(layout, root / clip["wavPath"])
        return multimodal_audio.load_normalized_16k(path, target_rate=rate, max_seconds=max_s)

    blind_tasks: list[dict[str, Any]] = []
    audit_tasks: list[dict[str, Any]] = []
    pairwise_tasks: list[dict[str, Any]] = []
    truth: dict[str, Any] = {"c1": {}, "c2Pairs": {}, "c2Orders": {}, "c3": {}, "c4": {}, "c5": {}}

    # C1: 12 identical-audio tie pairs (6 French + 6 English).
    for lang, root, pool in (("french", mls_root, fr_clips[:6]), ("english", lib_root, en_clips[:6])):
        for clip in pool:
            samp = load_clip(root, clip, max_s=6.0)
            stitched, timeline = multimodal_audio.stitch_segments([samp, samp], rate=rate, marker=marker)
            otok = _opaque_id("ord", rng)
            staged, meta = _stage_array(audio_dir, otok, stitched, rate)
            pairwise_tasks.append({
                "taskId": f"pair-{otok}",
                "orderToken": otok,
                "audioPath": _rel(layout, staged),
                "durationSeconds": meta["durationSeconds"],
                "clipCount": 2,
                "hasReferenceFirst": False,
                "timeline": timeline,
                "language": lang,
                "intendedText": clip.get("text"),
                "effectiveBrief": "neutral",
                "kind": "pairwise-control",
            })
            truth["c1"][otok] = {"control": "c1", "language": lang, "expected": "tie"}

    # C2: 16 dual-order pairs (8 clear perturbations + 8 clean-vs-clean) = 32 pairwise tasks.
    perturbations = ("heavy_noise", "hard_clip", "mid_dropout_600ms", "speed_1_4x")
    c2_clean_pool = [("french", mls_root, c) for c in fr_clips[6:18]] + [("english", lib_root, c) for c in en_clips[6:18]]
    for idx in range(16):
        pair_token = _opaque_id("pair", rng)
        if idx < 8:
            lang, root, clip = c2_clean_pool[idx]
            clean = load_clip(root, clip, max_s=6.0)
            kind = perturbations[idx % len(perturbations)]
            degraded = multimodal_audio.apply_clear_perturbation(clean, rate, kind, seed=seed + idx)
            arm_a_label, arm_b_label = "clean", f"perturbed:{kind}"
            samp_a, samp_b = clean, degraded
            expected_winner = "clean"
            text_a = clip.get("text")
        else:
            lang1, root1, clip1 = c2_clean_pool[8 + (idx - 8) * 2 % 16]
            lang2, root2, clip2 = c2_clean_pool[9 + (idx - 8) * 2 % 16]
            samp_a = load_clip(root1, clip1, max_s=6.0)
            samp_b = load_clip(root2, clip2, max_s=6.0)
            lang = lang1 if lang1 == lang2 else "mixed"
            arm_a_label, arm_b_label = "clean_1", "clean_2"
            expected_winner = None
            text_a = None
        truth["c2Pairs"][pair_token] = {
            "control": "c2",
            "subtype": "clear_perturbation" if idx < 8 else "clean_pair",
            "language": lang,
            "armA": arm_a_label,
            "armB": arm_b_label,
            "expectedWinner": expected_winner,
        }
        for orientation, c1_arm, c2_arm, s1, s2 in (
            ("ab", arm_a_label, arm_b_label, samp_a, samp_b),
            ("ba", arm_b_label, arm_a_label, samp_b, samp_a),
        ):
            otok = _opaque_id("ord", rng)
            stitched, timeline = multimodal_audio.stitch_segments([s1, s2], rate=rate, marker=marker)
            staged, meta = _stage_array(audio_dir, otok, stitched, rate)
            pairwise_tasks.append({
                "taskId": f"pair-{otok}",
                "orderToken": otok,
                "audioPath": _rel(layout, staged),
                "durationSeconds": meta["durationSeconds"],
                "clipCount": 2,
                "hasReferenceFirst": False,
                "timeline": timeline,
                "language": lang,
                "intendedText": text_a,
                "effectiveBrief": "neutral",
                "kind": "pairwise-control",
            })
            truth["c2Orders"][otok] = {
                "pairToken": pair_token,
                "orientation": orientation,
                "clip1Arm": c1_arm,
                "clip2Arm": c2_arm,
            }

    # C3: 12 adversarial text/language mismatch tasks (6 French + 6 English).
    for idx, (lang, root, clip) in enumerate(
        [("french", mls_root, c) for c in fr_clips[18:24]] + [("english", lib_root, c) for c in en_clips[18:24]]
    ):
        samp = load_clip(root, clip, max_s=7.0)
        tok = _opaque_id("t", rng)
        staged, meta = _stage_array(audio_dir, tok, samp, rate)
        if idx % 3 == 0:
            corrupted_text = (
                "The crimson telescope balanced quietly beside three brass lanterns."
                if lang == "french"
                else "Les montagnes enneigées reflétaient la lumière dorée du matin."
            )
            requested_lang = "english" if lang == "french" else "french"
            corruption = "wrong_language_and_script"
        else:
            words = str(clip.get("text") or "").split()
            if len(words) >= 4:
                words[1] = "crocodile" if lang == "english" else "hélicoptère"
                words[-2] = "telescope" if lang == "english" else "parapluie"
            corrupted_text = " ".join(words)
            requested_lang = lang
            corruption = "substituted_words"
        blind_tasks.append({
            "taskId": f"blind-{tok}", "opaqueToken": tok, "audioPath": _rel(layout, staged),
            "durationSeconds": meta["durationSeconds"], "kind": "single",
        })
        audit_tasks.append({
            "taskId": f"audit-{tok}", "opaqueToken": tok, "audioPath": _rel(layout, staged),
            "localZooms": [], "clonePairAudioPath": None, "cloneTimeline": None,
            "longformConsistencyAudioPath": None, "durationSeconds": meta["durationSeconds"],
            "language": requested_lang, "intendedText": corrupted_text, "effectiveBrief": "neutral",
            "hasReference": False, "axes": ["diction"],
        })
        truth["c3"][tok] = {
            "control": "c3", "actualLanguage": lang, "requestedLanguage": requested_lang, "corruption": corruption,
        }

    # C4: 40 speaker identity stitched pairs (20 same-speaker, 20 different-speaker same-gender/lang).
    def build_speaker_buckets(clips: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for clip in clips:
            spk = str(clip.get("speaker") or "")
            if spk:
                buckets.setdefault(spk, []).append(clip)
        return {spk: items for spk, items in buckets.items() if len(items) >= 2}

    fr_spk = build_speaker_buckets(fr_clips)
    en_spk = build_speaker_buckets(en_clips)
    fr_male = sorted(s for s, items in fr_spk.items() if items[0].get("gender") == "male")
    fr_female = sorted(s for s, items in fr_spk.items() if items[0].get("gender") == "female")
    en_spks = sorted(en_spk)
    rng.shuffle(fr_male)
    rng.shuffle(fr_female)
    rng.shuffle(en_spks)

    c4_specs: list[tuple[str, bool, Path, dict[str, Any], dict[str, Any]]] = []
    # 10 same-speaker French (5M + 5F) + 10 same-speaker English
    for spk in fr_male[:5] + fr_female[:5]:
        c4_specs.append(("french", True, mls_root, fr_spk[spk][0], fr_spk[spk][1]))
    for spk in en_spks[:10]:
        c4_specs.append(("english", True, lib_root, en_spk[spk][0], en_spk[spk][1]))
    # 10 different-speaker same-gender French (5 M-M + 5 F-F) + 10 different-speaker English
    for i in range(5):
        c4_specs.append(("french", False, mls_root, fr_spk[fr_male[i]][0], fr_spk[fr_male[(i + 1) % len(fr_male)]][0]))
        c4_specs.append(("french", False, mls_root, fr_spk[fr_female[i]][0], fr_spk[fr_female[(i + 1) % len(fr_female)]][0]))
    for i in range(10):
        c4_specs.append(("english", False, lib_root, en_spk[en_spks[i]][0], en_spk[en_spks[(i + 1) % len(en_spks)]][0]))

    for lang, is_same, root, clip_a, clip_b in c4_specs:
        sa = load_clip(root, clip_a, max_s=6.0)
        sb = load_clip(root, clip_b, max_s=6.0)
        stitched, timeline = multimodal_audio.stitch_segments([sa, sb], rate=rate, marker=marker)
        tok = _opaque_id("c", rng)
        staged, meta = _stage_array(audio_dir, tok, stitched, rate)
        audit_tasks.append({
            "taskId": f"audit-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "localZooms": [],
            "clonePairAudioPath": _rel(layout, staged),
            "cloneTimeline": timeline,
            "longformConsistencyAudioPath": None,
            "durationSeconds": meta["durationSeconds"],
            "language": lang,
            "intendedText": None,
            "effectiveBrief": "neutral",
            "hasReference": True,
            "axes": ["clone"],
        })
        truth["c4"][tok] = {
            "control": "c4", "language": lang, "sameSpeaker": is_same,
            "gender": clip_a.get("gender"),
        }

    # C5: 12 delivery brief match/mismatch (emozionalmente) + 8 harmless transforms (mls + libritts-r).
    by_emo: dict[str, list[dict[str, Any]]] = {}
    for clip in emo_clips:
        emo = clip.get("emotionCanonical")
        if emo in EMOTION_CONTRADICTIONS and 2.5 <= float(clip.get("durationSeconds") or 0) <= 10.0:
            by_emo.setdefault(str(emo), []).append(clip)
    for bucket in by_emo.values():
        bucket.sort(key=lambda c: c["clipID"])
        rng.shuffle(bucket)

    c5_specs: list[tuple[str, bool, np.ndarray, str, str]] = []
    for emo in ("angry", "happy", "neutral"):
        for clip in by_emo[emo][:2]:
            c5_specs.append(("brief_match", True, load_clip(emo_root, clip, max_s=7.0), "italian", EMOTION_BRIEFS[emo]))
    for emo in ("angry", "neutral", "happy", "sad"):
        count = 2 if emo in ("angry", "neutral") else 1
        opposite = EMOTION_CONTRADICTIONS[emo]
        for clip in by_emo[emo][2:2 + count]:
            c5_specs.append(("brief_mismatch", False, load_clip(emo_root, clip, max_s=7.0), "italian", EMOTION_BRIEFS[opposite]))

    harmless_kinds = ("gain_plus_3db", "gain_minus_3db", "lead_silence_200ms")
    for idx, (lang, root, clip) in enumerate(
        [("french", mls_root, c) for c in fr_clips[24:28]] + [("english", lib_root, c) for c in en_clips[24:28]]
    ):
        base = load_clip(root, clip, max_s=7.0)
        kind = harmless_kinds[idx % len(harmless_kinds)]
        transformed = multimodal_audio.apply_harmless_transform(base, rate, kind)
        c5_specs.append((f"harmless:{kind}", True, transformed, lang, EMOTION_BRIEFS["neutral"]))

    for subtype, should_match, samples, lang, brief in c5_specs:
        tok = _opaque_id("d", rng)
        staged, meta = _stage_array(audio_dir, tok, samples, rate)
        audit_tasks.append({
            "taskId": f"audit-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "localZooms": [],
            "clonePairAudioPath": None,
            "cloneTimeline": None,
            "longformConsistencyAudioPath": None,
            "durationSeconds": meta["durationSeconds"],
            "language": lang,
            "intendedText": None,
            "effectiveBrief": brief,
            "hasReference": False,
            "axes": ["delivery"],
        })
        truth["c5"][tok] = {"control": "c5", "subtype": subtype, "shouldMatch": should_match, "language": lang}

    rng.shuffle(blind_tasks)
    rng.shuffle(audit_tasks)
    rng.shuffle(pairwise_tasks)

    packet = {
        "schema": PACKET_SCHEMA,
        "session": session_name,
        "kind": "q1-controls",
        "createdAt": utc_now(),
        "rubricSchema": RUBRIC_SCHEMA,
        "rubricSHA256": rubric_sha,
        "targetModel": rubric["targetModel"],
        "advisoryOnly": True,
        "neverGates": True,
        "blindTasks": blind_tasks,
        "auditTasks": audit_tasks,
        "pairwiseTasks": pairwise_tasks,
    }
    store.write_json_atomic(out_dir / "review-packet.json", packet)
    store.write_json_atomic(out_dir / "private-key.json", {"session": session_name, "kind": "q1-controls", "truth": truth})
    return {
        "session": session_name,
        "packetPath": _rel(layout, out_dir / "review-packet.json"),
        "c1": len(truth["c1"]),
        "c2Pairs": len(truth["c2Pairs"]),
        "c3": len(truth["c3"]),
        "c4": len(truth["c4"]),
        "c5": len(truth["c5"]),
        "totalTasks": len(blind_tasks) + len(audit_tasks) + len(pairwise_tasks),
    }


def prepare_q2_calibration(
    layout: Layout,
    *,
    session: str = "q2-blind-cal-v1",
    allow_synthetic_confirm_batches: bool = False,
    clean_per_language: int = 15,
    seed: int = 20261122,
) -> dict[str, Any]:
    """Build the Q2 blind calibration packet from retained non-clone confirm batches + clean human controls."""

    if not allow_synthetic_confirm_batches:
        raise PrivacyBoundaryError(
            "prepare-q2 requires explicit --allow-synthetic-confirm-batches opt-in"
        )
    rubric, rubric_sha = load_rubric(layout)
    session_name = validate_session_name(session)
    out_dir = session_dir(layout, session_name)
    if out_dir.exists():
        raise FileExistsError(f"multimodal session already exists: {session_name}")
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=False)

    rate = int(rubric["audio"]["sampleRateHz"])
    rng = random.Random(f"vocello.qc.multimodal.q2/1:{seed}")

    entries: list[dict[str, Any]] = []
    confirm_batches = sorted(
        name for name in label.batch_names(layout) if name.startswith("confirm-")
    )
    if not confirm_batches:
        raise MultimodalError("no confirm-* batches found under build/private/qc/batches")

    for batch_name in confirm_batches:
        batch = label.load_batch(layout, batch_name)
        if batch.get("kind") != confirm.CONFIRM_KIND:
            continue
        lbl_rows = store.read_jsonl(label.labels_path(layout, batch_name))
        latest_labels = {row["token"]: row for row in lbl_rows if isinstance(row, dict) and row.get("token")}
        for item in batch.get("items") or []:
            take = (batch.get("takes") or {}).get(item["takeToken"])
            if take is None:
                continue
            if confirm.is_clone(take):
                raise PrivacyBoundaryError(f"clone take encountered in {batch_name}; refusing Q2 packet")
            wav_path = confirm.confirm_directory(layout, batch_name) / f"{int(item['order']) + 1}.wav"
            validated = validate_audio_source(layout, wav_path, take=take, allow_synthetic_confirm_batches=True)
            lbl = latest_labels.get(item["token"])
            if lbl is None:
                continue
            entries.append({
                "role": "confirm",
                "sourcePath": validated,
                "language": take.get("language"),
                "text": take.get("text"),
                "brief": "neutral",
                "humanVerdict": lbl.get("verdict"),  # acceptable | objectionable | uncertain
                "qcFlagCount": len(item.get("reasons") or []),
                "qcReasons": list(item.get("reasons") or []),
                "batch": batch_name,
            })

    # Clean human read-speech controls (French mls + English libritts-r), speaker-spread.
    mls_root, mls_clips = _corpus_manifest(layout, "mls")
    lib_root, lib_clips = _corpus_manifest(layout, "libritts-r")
    for lang, root, pool in (
        ("french", mls_root, [c for c in mls_clips if c.get("language") == "french" and 4.0 <= float(c.get("durationSeconds") or 0) <= 13.0]),
        ("english", lib_root, [c for c in lib_clips if c.get("language") == "english" and 3.0 <= float(c.get("durationSeconds") or 0) <= 12.0]),
    ):
        pool.sort(key=lambda c: c["clipID"])
        rng.shuffle(pool)
        seen_speakers: set[str] = set()
        picked = 0
        for clip in pool:
            spk = str(clip.get("speaker") or clip["clipID"])
            if spk in seen_speakers:
                continue
            seen_speakers.add(spk)
            validated = validate_audio_source(layout, root / clip["wavPath"])
            entries.append({
                "role": "human_control",
                "sourcePath": validated,
                "language": lang,
                "text": clip.get("text"),
                "brief": "neutral",
                "humanVerdict": "acceptable",
                "qcFlagCount": 0,
                "qcReasons": [],
                "batch": f"human-{lang}",
            })
            picked += 1
            if picked >= clean_per_language:
                break

    # Shuffle all confirm takes and clean human controls together so agents cannot distinguish them.
    rng.shuffle(entries)
    blind_tasks: list[dict[str, Any]] = []
    audit_tasks: list[dict[str, Any]] = []
    private_items: dict[str, Any] = {}

    for entry in entries:
        samples = multimodal_audio.load_normalized_16k(entry["sourcePath"], target_rate=rate, max_seconds=14.0)
        tok = _opaque_id("q2", rng)
        staged, meta = _stage_array(audio_dir, tok, samples, rate)
        blind_tasks.append({
            "taskId": f"blind-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "durationSeconds": meta["durationSeconds"],
            "kind": "single",
        })
        audit_tasks.append({
            "taskId": f"audit-{tok}",
            "opaqueToken": tok,
            "audioPath": _rel(layout, staged),
            "localZooms": [],
            "clonePairAudioPath": None,
            "cloneTimeline": None,
            "longformConsistencyAudioPath": None,
            "durationSeconds": meta["durationSeconds"],
            "language": entry["language"],
            "intendedText": entry["text"],
            "effectiveBrief": entry["brief"],
            "hasReference": False,
            "axes": ["diction", "delivery"],
        })
        private_items[tok] = {
            "role": entry["role"],
            "language": entry["language"],
            "humanVerdict": entry["humanVerdict"],
            "qcFlagCount": entry["qcFlagCount"],
            "qcReasons": entry["qcReasons"],
            "stagedSHA256": meta["sha256"],
        }

    packet = {
        "schema": PACKET_SCHEMA,
        "session": session_name,
        "kind": "q2-calibration",
        "createdAt": utc_now(),
        "rubricSchema": RUBRIC_SCHEMA,
        "rubricSHA256": rubric_sha,
        "targetModel": rubric["targetModel"],
        "advisoryOnly": True,
        "neverGates": True,
        "blindTasks": blind_tasks,
        "auditTasks": audit_tasks,
        "pairwiseTasks": [],
    }
    store.write_json_atomic(out_dir / "review-packet.json", packet)
    store.write_json_atomic(out_dir / "private-key.json", {
        "session": session_name,
        "kind": "q2-calibration",
        "items": private_items,
    })
    return {
        "session": session_name,
        "packetPath": _rel(layout, out_dir / "review-packet.json"),
        "confirmCount": sum(1 for v in private_items.values() if v["role"] == "confirm"),
        "humanControlCount": sum(1 for v in private_items.values() if v["role"] == "human_control"),
        "totalTakes": len(private_items),
    }


# --- Verdict aggregation & order-swap reconciliation ---------------------------


def reconcile_pairwise_orders(
    orders_map: dict[str, dict[str, Any]],
    pairwise_verdicts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile dual-order AB/BA verdicts and compute exact position-bias rates."""

    by_pair: dict[str, dict[str, tuple[dict[str, Any], dict[str, Any]]]] = {}
    first_chosen = second_chosen = ties = uncertains = 0
    for order_token, meta in orders_map.items():
        verdict = pairwise_verdicts.get(order_token)
        if not verdict:
            continue
        raw_winner = verdict.get("winner")
        if raw_winner == "clip_1":
            first_chosen += 1
        elif raw_winner == "clip_2":
            second_chosen += 1
        elif raw_winner == "tie":
            ties += 1
        else:
            uncertains += 1
        by_pair.setdefault(meta["pairToken"], {})[meta["orientation"]] = (meta, verdict)

    reconciled: dict[str, dict[str, Any]] = {}
    strict_wins = weak_wins = pair_ties = flips = incomplete = 0
    arm_wins: dict[str, int] = {}

    def mapped_arm(meta: dict[str, Any], verdict: dict[str, Any]) -> str:
        w = verdict.get("winner")
        if w == "clip_1":
            return str(meta["clip1Arm"])
        if w == "clip_2":
            return str(meta["clip2Arm"])
        return str(w or "uncertain")

    for pair_token, orientations in sorted(by_pair.items()):
        if "ab" not in orientations or "ba" not in orientations:
            incomplete += 1
            reconciled[pair_token] = {"outcome": "incomplete", "winnerArm": None}
            continue
        meta_ab, v_ab = orientations["ab"]
        meta_ba, v_ba = orientations["ba"]
        w_ab = mapped_arm(meta_ab, v_ab)
        w_ba = mapped_arm(meta_ba, v_ba)
        if w_ab == w_ba:
            if w_ab in ("tie", "uncertain"):
                pair_ties += 1
                reconciled[pair_token] = {"outcome": "tie", "winnerArm": None, "ab": v_ab, "ba": v_ba}
            else:
                strict_wins += 1
                arm_wins[w_ab] = arm_wins.get(w_ab, 0) + 1
                reconciled[pair_token] = {"outcome": "strict_win", "winnerArm": w_ab, "ab": v_ab, "ba": v_ba}
        elif w_ab in ("tie", "uncertain") and w_ba not in ("tie", "uncertain"):
            if v_ba.get("margin") in ("clear", "major"):
                weak_wins += 1
                arm_wins[w_ba] = arm_wins.get(w_ba, 0) + 1
                reconciled[pair_token] = {"outcome": "weak_win", "winnerArm": w_ba, "ab": v_ab, "ba": v_ba}
            else:
                pair_ties += 1
                reconciled[pair_token] = {"outcome": "tie", "winnerArm": None, "ab": v_ab, "ba": v_ba}
        elif w_ba in ("tie", "uncertain") and w_ab not in ("tie", "uncertain"):
            if v_ab.get("margin") in ("clear", "major"):
                weak_wins += 1
                arm_wins[w_ab] = arm_wins.get(w_ab, 0) + 1
                reconciled[pair_token] = {"outcome": "weak_win", "winnerArm": w_ab, "ab": v_ab, "ba": v_ba}
            else:
                pair_ties += 1
                reconciled[pair_token] = {"outcome": "tie", "winnerArm": None, "ab": v_ab, "ba": v_ba}
        else:
            flips += 1
            reconciled[pair_token] = {"outcome": "order_inconsistent", "winnerArm": None, "ab": v_ab, "ba": v_ba}

    complete_pairs = strict_wins + weak_wins + pair_ties + flips
    directional = first_chosen + second_chosen
    return {
        "pairs": reconciled,
        "summary": {
            "completePairs": complete_pairs,
            "incompletePairs": incomplete,
            "strictWins": strict_wins,
            "weakWins": weak_wins,
            "ties": pair_ties,
            "orderInconsistent": flips,
            "orderFlipRate": round(flips / complete_pairs, 4) if complete_pairs else None,
            "armWins": arm_wins,
            "positionBias": {
                "firstChosen": first_chosen,
                "secondChosen": second_chosen,
                "ties": ties,
                "uncertain": uncertains,
                "firstShareOfDirectional": round(first_chosen / directional, 4) if directional else None,
            },
        },
    }


def load_verdicts(path: Path | str) -> dict[str, Any]:
    doc = store.read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != VERDICTS_SCHEMA:
        raise MultimodalError(f"verdicts file must carry schema {VERDICTS_SCHEMA!r}")
    return doc


def aggregate_session(layout: Layout, session: str, verdicts_path: Path | str) -> dict[str, Any]:
    """Join worker verdicts with private key + QC v2 context and write private report.json."""

    out_dir = session_dir(layout, session)
    packet = store.read_json(out_dir / "review-packet.json")
    key_doc = store.read_json(out_dir / "private-key.json")
    qc_ctx = store.read_json(out_dir / "qc-context.json").get("context", {}) if (out_dir / "qc-context.json").is_file() else {}
    verdicts = load_verdicts(verdicts_path)
    if verdicts.get("session") != session:
        raise MultimodalError(f"verdicts session {verdicts.get('session')!r} != {session!r}")

    blind_by_tok = {r["opaqueToken"]: r for r in verdicts.get("blind") or [] if isinstance(r, dict) and r.get("opaqueToken")}
    diction_by_tok = {r["opaqueToken"]: r for r in verdicts.get("diction") or [] if isinstance(r, dict) and r.get("opaqueToken")}
    delivery_by_tok = {r["opaqueToken"]: r for r in verdicts.get("delivery") or [] if isinstance(r, dict) and r.get("opaqueToken")}
    clone_by_tok = {r["opaqueToken"]: r for r in verdicts.get("clone") or [] if isinstance(r, dict) and r.get("opaqueToken")}
    pairwise_by_ord = {r["orderToken"]: r for r in verdicts.get("pairwise") or [] if isinstance(r, dict) and r.get("orderToken")}

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "session": session,
        "kind": packet.get("kind"),
        "createdAt": utc_now(),
        "rubricSHA256": packet.get("rubricSHA256"),
        "model": verdicts.get("model") or packet.get("targetModel"),
        "status": "report-only-advisory",
        "neverGates": True,
    }

    if packet.get("kind") == "screen-ab":
        rec = reconcile_pairwise_orders(key_doc["orders"], pairwise_by_ord)
        pair_rows = []
        for pair_tok, meta in sorted(key_doc["pairs"].items()):
            merged = dict(meta, pairToken=pair_tok, reconciliation=rec["pairs"].get(pair_tok))
            pair_rows.append(merged)
        report["pairwiseSummary"] = rec["summary"]
        report["pairs"] = pair_rows
    elif packet.get("kind") in ("qc-run", "q2-calibration"):
        rows = []
        counts = {"usable": 0, "borderline": 0, "unusable": 0, "uncertain": 0}
        for tok, meta in sorted((key_doc.get("items") or {}).items()):
            b, d, deliv, cl = blind_by_tok.get(tok), diction_by_tok.get(tok), delivery_by_tok.get(tok), clone_by_tok.get(tok)
            overall = _usable_from_judgments(b, d, deliv, cl)
            counts[overall] = counts.get(overall, 0) + 1
            rows.append({
                "opaqueToken": tok,
                "metadata": meta,
                "qcContext": qc_ctx.get(tok),
                "blind": b,
                "diction": d,
                "delivery": deliv,
                "clone": cl,
                "overallUsability": overall,
            })
        report["usabilityCounts"] = counts
        report["items"] = rows
    elif packet.get("kind") == "q1-controls":
        report["q1RawCounts"] = {
            "blind": len(blind_by_tok),
            "diction": len(diction_by_tok),
            "delivery": len(delivery_by_tok),
            "clone": len(clone_by_tok),
            "pairwise": len(pairwise_by_ord),
        }
    else:
        raise MultimodalError(f"unsupported packet kind: {packet.get('kind')!r}")

    store.write_json_atomic(out_dir / "verdicts.json", verdicts)
    store.write_json_atomic(out_dir / "report.json", report)
    return report


# --- Q1 + Q2 Qualification (aggregate-only, safe for Git) ----------------------


def evaluate_q1(layout: Layout, session: str, verdicts_path: Path | str | None = None) -> dict[str, Any]:
    """Score Q1 bias & capability controls against pre-registered bars (aggregates only)."""

    rubric, _ = load_rubric(layout)
    bars = rubric["qualificationBars"]["q1"]
    out_dir = session_dir(layout, session)
    key_doc = store.read_json(out_dir / "private-key.json")
    truth = key_doc["truth"]
    verdicts = load_verdicts(verdicts_path or (out_dir / "verdicts.json"))

    diction_by_tok = {r["opaqueToken"]: r for r in verdicts.get("diction") or []}
    delivery_by_tok = {r["opaqueToken"]: r for r in verdicts.get("delivery") or []}
    clone_by_tok = {r["opaqueToken"]: r for r in verdicts.get("clone") or []}
    pairwise_by_ord = {r["orderToken"]: r for r in verdicts.get("pairwise") or []}

    # C1: identical-audio tie discipline
    c1_total = len(truth["c1"])
    c1_ties = sum(1 for otok in truth["c1"] if (pairwise_by_ord.get(otok) or {}).get("winner") in ("tie", "uncertain"))
    c1_stat = _ci_summary(c1_ties, c1_total)
    c1_pass = c1_stat["rate"] is not None and c1_stat["rate"] >= bars["c1IdenticalTieRateMin"]

    # C2: order-swap symmetry + clear perturbation win rate
    rec = reconcile_pairwise_orders(truth["c2Orders"], pairwise_by_ord)
    c2_complete = rec["summary"]["completePairs"]
    c2_flips = rec["summary"]["orderInconsistent"]
    c2_flip_stat = _ci_summary(c2_flips, c2_complete)
    c2_flip_pass = c2_flip_stat["rate"] is not None and c2_flip_stat["rate"] <= bars["c2OrderFlipRateMax"]
    pert_pairs = [pt for pt, meta in truth["c2Pairs"].items() if meta.get("subtype") == "clear_perturbation"]
    pert_wins = sum(
        1 for pt in pert_pairs
        if (rec["pairs"].get(pt) or {}).get("outcome") in ("strict_win", "weak_win")
        and (rec["pairs"].get(pt) or {}).get("winnerArm") == "clean"
    )
    c2_pert_stat = _ci_summary(pert_wins, len(pert_pairs))
    c2_pert_pass = c2_pert_stat["rate"] is not None and c2_pert_stat["rate"] >= bars["c2ClearPerturbationConsistentWinMin"]

    # C3: adversarial text/language mismatch detection
    c3_total = len(truth["c3"])
    c3_caught = sum(
        1 for tok in truth["c3"]
        if (diction_by_tok.get(tok) or {}).get("contentMatch") in ("major_mismatch", "wrong_language")
        or (diction_by_tok.get(tok) or {}).get("overallUsability") == "unusable"
    )
    c3_stat = _ci_summary(c3_caught, c3_total)
    c3_pass = c3_stat["rate"] is not None and c3_stat["rate"] >= bars["c3AdversarialMismatchDetectionMin"]

    # C4: speaker identity discrimination (same vs different)
    same_toks = [t for t, m in truth["c4"].items() if m["sameSpeaker"]]
    diff_toks = [t for t, m in truth["c4"].items() if not m["sameSpeaker"]]
    tp = sum(1 for t in same_toks if (clone_by_tok.get(t) or {}).get("sameSpeaker") == "yes")
    tn = sum(1 for t in diff_toks if (clone_by_tok.get(t) or {}).get("sameSpeaker") == "no")
    tpr = tp / len(same_toks) if same_toks else 0.0
    tnr = tn / len(diff_toks) if diff_toks else 0.0
    bal_acc = round(0.5 * (tpr + tnr), 4)
    c4_pass = bal_acc >= bars["c4SpeakerBalancedAccuracyMin"]

    # C5: delivery brief match/mismatch + harmless transform false alarms
    mismatch_toks = [t for t, m in truth["c5"].items() if m["subtype"] == "brief_mismatch"]
    match_toks = [t for t, m in truth["c5"].items() if m["subtype"] == "brief_match"]
    harmless_toks = [t for t, m in truth["c5"].items() if str(m["subtype"]).startswith("harmless:")]
    mismatch_caught = sum(
        1 for t in mismatch_toks
        if (delivery_by_tok.get(t) or {}).get("briefCompliance") in ("contradicts", "partial")
        or (delivery_by_tok.get(t) or {}).get("overallUsability") in ("unusable", "borderline")
    )
    match_ok = sum(
        1 for t in match_toks
        if (delivery_by_tok.get(t) or {}).get("briefCompliance") in ("matches", "partial")
        and (delivery_by_tok.get(t) or {}).get("overallUsability") != "unusable"
    )
    harmless_fa = sum(
        1 for t in harmless_toks
        if (delivery_by_tok.get(t) or {}).get("overallUsability") == "unusable"
    )
    c5_mis_stat = _ci_summary(mismatch_caught, len(mismatch_toks))
    c5_match_stat = _ci_summary(match_ok, len(match_toks))
    c5_fa_stat = _ci_summary(harmless_fa, len(harmless_toks))
    c5_pass = (
        c5_mis_stat["rate"] is not None
        and c5_mis_stat["rate"] >= bars["c5BriefMismatchDetectionMin"]
        and c5_fa_stat["rate"] is not None
        and c5_fa_stat["rate"] <= bars["c5HarmlessTransformFalseAlarmMax"]
    )

    return {
        "session": session,
        "c1IdenticalTie": dict(c1_stat, barMin=bars["c1IdenticalTieRateMin"], passed=c1_pass),
        "c2OrderFlip": dict(c2_flip_stat, barMax=bars["c2OrderFlipRateMax"], passed=c2_flip_pass,
                            positionBias=rec["summary"]["positionBias"]),
        "c2ClearPerturbationWin": dict(c2_pert_stat, barMin=bars["c2ClearPerturbationConsistentWinMin"], passed=c2_pert_pass),
        "c3AdversarialMismatch": dict(c3_stat, barMin=bars["c3AdversarialMismatchDetectionMin"], passed=c3_pass),
        "c4SpeakerIdentity": {
            "sameSpeakerRecall": _ci_summary(tp, len(same_toks)),
            "differentSpeakerSpecificity": _ci_summary(tn, len(diff_toks)),
            "balancedAccuracy": bal_acc,
            "barMin": bars["c4SpeakerBalancedAccuracyMin"],
            "passed": c4_pass,
        },
        "c5DeliveryBriefMismatch": dict(c5_mis_stat, barMin=bars["c5BriefMismatchDetectionMin"]),
        "c5DeliveryBriefMatch": c5_match_stat,
        "c5HarmlessTransformFalseAlarm": dict(c5_fa_stat, barMax=bars["c5HarmlessTransformFalseAlarmMax"]),
        "c5Passed": c5_pass,
    }


def evaluate_q2(layout: Layout, session: str, verdicts_path: Path | str | None = None) -> dict[str, Any]:
    """Score Q2 blind maintainer confirmations & clean human controls (aggregates only)."""

    rubric, _ = load_rubric(layout)
    bars = rubric["qualificationBars"]["q2"]
    out_dir = session_dir(layout, session)
    key_doc = store.read_json(out_dir / "private-key.json")
    verdicts = load_verdicts(verdicts_path or (out_dir / "verdicts.json"))

    blind_by_tok = {r["opaqueToken"]: r for r in verdicts.get("blind") or []}
    diction_by_tok = {r["opaqueToken"]: r for r in verdicts.get("diction") or []}
    delivery_by_tok = {r["opaqueToken"]: r for r in verdicts.get("delivery") or []}
    clone_by_tok = {r["opaqueToken"]: r for r in verdicts.get("clone") or []}

    human_total = human_fa = 0
    # Decisive confirmations exclude human 'uncertain' answers (same rule as qc.calibrate.evaluate).
    conf_flagged_total = conf_flagged_unusable = 0
    conf_unflagged_total = conf_unflagged_unusable = 0
    conf_borderline_total = conf_borderline_unusable = 0
    conf_uncertain_human = 0
    by_lang: dict[str, dict[str, int]] = {}

    for tok, meta in (key_doc.get("items") or {}).items():
        if meta.get("role") == "dev_anchor":
            continue  # dev anchors never enter held-out metrics
        overall = _usable_from_judgments(
            blind_by_tok.get(tok), diction_by_tok.get(tok), delivery_by_tok.get(tok), clone_by_tok.get(tok)
        )
        lang = str(meta.get("language") or "unknown")
        if meta.get("role") == "human_control":
            human_total += 1
            if overall == "unusable":
                human_fa += 1
        elif meta.get("role") == "confirm":
            hv = meta.get("humanVerdict")
            if hv == "uncertain":
                conf_uncertain_human += 1
                continue
            is_unusable = hv == "objectionable"
            bucket = by_lang.setdefault(lang, {"flagged": 0, "flaggedUnusable": 0, "unflagged": 0, "unflaggedUnusable": 0})
            if overall == "unusable":
                conf_flagged_total += 1
                bucket["flagged"] += 1
                if is_unusable:
                    conf_flagged_unusable += 1
                    bucket["flaggedUnusable"] += 1
            elif overall == "borderline":
                conf_borderline_total += 1
                if is_unusable:
                    conf_borderline_unusable += 1
            else:
                conf_unflagged_total += 1
                bucket["unflagged"] += 1
                if is_unusable:
                    conf_unflagged_unusable += 1
                    bucket["unflaggedUnusable"] += 1

    # Also compute pooled flagged = unusable OR borderline sensitivity/precision view.
    broad_flagged_total = conf_flagged_total + conf_borderline_total
    broad_flagged_unusable = conf_flagged_unusable + conf_borderline_unusable
    total_decisive_unusable = conf_flagged_unusable + conf_borderline_unusable + conf_unflagged_unusable

    human_fa_stat = _ci_summary(human_fa, human_total)
    strict_prec = _ci_summary(conf_flagged_unusable, conf_flagged_total)
    broad_prec = _ci_summary(broad_flagged_unusable, broad_flagged_total)
    unflagged_rate = _ci_summary(conf_unflagged_unusable, conf_unflagged_total)
    strict_recall = _ci_summary(conf_flagged_unusable, total_decisive_unusable)
    broad_recall = _ci_summary(broad_flagged_unusable, total_decisive_unusable)

    separation_strict = (
        round(strict_prec["rate"] - unflagged_rate["rate"], 4)
        if strict_prec["rate"] is not None and unflagged_rate["rate"] is not None else None
    )
    separation_broad = (
        round(broad_prec["rate"] - unflagged_rate["rate"], 4)
        if broad_prec["rate"] is not None and unflagged_rate["rate"] is not None else None
    )
    human_pass = human_fa_stat["rate"] is not None and human_fa_stat["rate"] <= bars["cleanHumanFalseAlarmRateMax"]
    prec_pass = (
        (strict_prec["rate"] is not None and strict_prec["rate"] >= bars["confirmUnusablePrecisionMin"]
         and separation_strict is not None and separation_strict >= bars["confirmFlaggedMinusUnflaggedMin"])
        or (broad_prec["rate"] is not None and broad_prec["rate"] >= bars["confirmUnusablePrecisionMin"]
            and separation_broad is not None and separation_broad >= bars["confirmFlaggedMinusUnflaggedMin"])
    )
    return {
        "session": session,
        "cleanHumanFalseAlarm": dict(human_fa_stat, barMax=bars["cleanHumanFalseAlarmRateMax"], passed=human_pass),
        "confirmDecisiveTotal": conf_flagged_total + conf_borderline_total + conf_unflagged_total,
        "confirmHumanUncertainExcluded": conf_uncertain_human,
        "confirmStrictUnusablePrecision": strict_prec,
        "confirmStrictUnusableRecall": strict_recall,
        "confirmBroadFlaggedPrecision": broad_prec,
        "confirmBroadFlaggedRecall": broad_recall,
        "confirmUnflaggedUnusableRate": unflagged_rate,
        "separationStrict": separation_strict,
        "separationBroad": separation_broad,
        "historicalQcV2PrecisionBaseline": bars["historicalQcV2PrecisionBaseline"],
        "precisionBarMin": bars["confirmUnusablePrecisionMin"],
        "separationBarMin": bars["confirmFlaggedMinusUnflaggedMin"],
        "confirmPassed": prec_pass,
        "byLanguage": {
            lang: {
                "flaggedPrecision": _ci_summary(b["flaggedUnusable"], b["flagged"]),
                "unflaggedUnusableRate": _ci_summary(b["unflaggedUnusable"], b["unflagged"]),
            }
            for lang, b in sorted(by_lang.items())
        },
    }


def build_qualification_eval(
    layout: Layout,
    *,
    q1_session: str,
    q2_session: str | None = None,
    model_name: str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Combine Q1 (+ optional Q2) into a privacy-safe, Git-committable evaluation artifact."""

    rubric, rubric_sha = load_rubric(layout)
    q1 = evaluate_q1(layout, q1_session)
    q2 = evaluate_q2(layout, q2_session) if q2_session else None

    q2_ok = True if q2 is None else (q2["cleanHumanFalseAlarm"]["passed"] and q2["confirmPassed"])
    axis_status = {
        "diction": "active_advisory" if (q1["c3AdversarialMismatch"]["passed"] and q2_ok) else "abstain_uncalibrated",
        "delivery": "active_advisory" if (q1["c5Passed"] and (q2 is None or q2["cleanHumanFalseAlarm"]["passed"])) else "abstain_uncalibrated",
        "clone": "active_advisory" if q1["c4SpeakerIdentity"]["passed"] else "abstain_uncalibrated",
        "pairwise": (
            "active_advisory"
            if (q1["c1IdenticalTie"]["passed"] and q1["c2OrderFlip"]["passed"] and q1["c2ClearPerturbationWin"]["passed"])
            else "abstain_uncalibrated"
        ),
    }
    document = {
        "schema": EVAL_SCHEMA,
        "createdAt": utc_now(),
        "status": "report-only-advisory",
        "neverGates": True,
        "targetModel": model_name or rubric["targetModel"],
        "rubricSchema": RUBRIC_SCHEMA,
        "rubricVersion": rubric["version"],
        "rubricSHA256": rubric_sha,
        "q1": q1,
        "q2": q2,
        "axisStatus": axis_status,
    }
    if output_path is not None:
        store.write_json_atomic(output_path, document)
    return document


def rubric_digest(layout: Layout) -> str:
    _, digest = load_rubric(layout)
    return digest


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
