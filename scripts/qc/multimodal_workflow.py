"""Emit self-contained Antigravity `run_workflow` scripts for multimodal audio QC (`RF-72`).

This module stays valid standard Python 3 (checked by `ruff` and `pyright`) while
emitting a session-local `workflow.py` under git-ignored `build/private/qc/multimodal/`
that uses Antigravity's `run_workflow` DSL (`phase`, `agent`, `parallel`, `log`,
top-level `await`) with read-only `research` workers inheriting Gemini 4 Neon.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qc import multimodal, store
from qc.store import Layout

DEFAULT_CONCURRENCY = 8

_WORKFLOW_TEMPLATE = r'''"""Auto-generated Antigravity run_workflow script for Vocello multimodal audio QC (RF-72)."""

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(WORKSPACES[0]) if WORKSPACES else Path(__SESSION_ROOT__)
SESSION = __SESSION_NAME__
CONCURRENCY = __CONCURRENCY__
MODEL_LABEL = __MODEL_LABEL__

SESSION_DIR = ROOT / "build/private/qc/multimodal" / SESSION
PACKET = json.loads((SESSION_DIR / "review-packet.json").read_text(encoding="utf-8"))
RUBRIC = json.loads((ROOT / "config/qc/multimodal-rubric-v1.json").read_text(encoding="utf-8"))
VERDICTS_PATH = SESSION_DIR / "verdicts.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


if VERDICTS_PATH.is_file():
    state = json.loads(VERDICTS_PATH.read_text(encoding="utf-8"))
else:
    state = {
        "schema": "vocello.qc.multimodal.verdicts/1",
        "session": SESSION,
        "model": MODEL_LABEL,
        "rubricSHA256": PACKET["rubricSHA256"],
        "blind": [],
        "diction": [],
        "delivery": [],
        "clone": [],
        "pairwise": [],
    }

blind_done = {r["opaqueToken"]: r for r in state["blind"]}
diction_done = {r["opaqueToken"]: r for r in state["diction"]}
delivery_done = {r["opaqueToken"]: r for r in state["delivery"]}
clone_done = {r["opaqueToken"]: r for r in state["clone"]}
pairwise_done = {r["orderToken"]: r for r in state["pairwise"]}


def _save() -> None:
    state["blind"] = list(blind_done.values())
    state["diction"] = list(diction_done.values())
    state["delivery"] = list(delivery_done.values())
    state["clone"] = list(clone_done.values())
    state["pairwise"] = list(pairwise_done.values())
    _write_json_atomic(VERDICTS_PATH, state)


STANDING = (
    "You are an offline perceptual audio QC reviewer for Vocello. "
    "STRICT ISOLATION RULES: Call read_file ONLY on the exact .wav path(s) provided in the prompt. "
    "NEVER inspect any other files, scripts, labels, keys, or directories. "
    "Base your judgment strictly on what you actually hear in the audio stream and return the exact schema via finish."
)

PROMPTS = RUBRIC["prompts"]
SCHEMAS = RUBRIC["schemas"]
audit_by_tok = {item["opaqueToken"]: item for item in PACKET.get("auditTasks", [])}
blind_toks = {item["opaqueToken"] for item in PACKET.get("blindTasks", [])}

# --- Phase 1: Blind-first audio perception followed by diction/delivery audit ---
blind_items = list(PACKET.get("blindTasks", []))
pending_blind_items = [
    item for item in blind_items
    if item["opaqueToken"] not in blind_done
    or ("diction" in (audit_by_tok.get(item["opaqueToken"], {}).get("axes") or []) and item["opaqueToken"] not in diction_done)
    or ("delivery" in (audit_by_tok.get(item["opaqueToken"], {}).get("axes") or []) and item["opaqueToken"] not in delivery_done)
]

if pending_blind_items:
    phase(f"Blind + Audit ({len(pending_blind_items)} takes)")

    async def _run_blind_and_audit(b_item: dict) -> dict:
        tok = b_item["opaqueToken"]
        a_item = audit_by_tok.get(tok) or {}
        axes = list(a_item.get("axes") or [])
        abs_wav = str((ROOT / b_item["audioPath"]).resolve())
        reviewer = agent(STANDING, role=f"Audio QC {tok}", type_name="research", workspace="inherit", model="inherit")
        res = {"tok": tok, "blind": None, "diction": None, "delivery": None}
        try:
            p1 = (
                f"{PROMPTS['blind']}\n\n"
                f"Task metadata: taskId={b_item['taskId']}, opaqueToken={tok}, "
                f"durationSeconds={b_item['durationSeconds']}.\n"
                f"Call read_file on this exact WAV path and listen carefully before finishing:\n{abs_wav}"
            )
            b_out = await reviewer(p1, SCHEMAS["blind"])
            b_out["taskId"] = b_item["taskId"]
            b_out["opaqueToken"] = tok
            res["blind"] = b_out

            if "diction" in axes:
                zooms = a_item.get("localZooms") or []
                zoom_block = ""
                if zooms:
                    zlines = [
                        f"- Zoom {z['index']} ({z['windowStartSeconds']}s-{z['windowEndSeconds']}s): "
                        f"{(ROOT / z['audioPath']).resolve()}"
                        for z in zooms
                    ]
                    zoom_block = "\nAlso call read_file on these focused 2.5s local zoom crops:\n" + "\n".join(zlines)
                p2a = (
                    f"{PROMPTS['diction']}\n\n"
                    f"Now compare what you heard in Pass 1 against the intended request:\n"
                    f"- taskId: {a_item['taskId']}\n"
                    f"- opaqueToken: {tok}\n"
                    f"- requestedLanguage: {a_item.get('language')}\n"
                    f"- intendedText: {json.dumps(a_item.get('intendedText'), ensure_ascii=False)}"
                    f"{zoom_block}\n"
                    f"Return the strict diction audit JSON via finish."
                )
                d_out = await reviewer(p2a, SCHEMAS["diction"])
                d_out["taskId"] = a_item["taskId"]
                d_out["opaqueToken"] = tok
                res["diction"] = d_out

            if "delivery" in axes:
                lf_path = a_item.get("longformConsistencyAudioPath")
                lf_block = (
                    f"\nAlso call read_file on this stitched opening/middle/final long-form consistency clip:\n"
                    f"{(ROOT / lf_path).resolve()}"
                    if lf_path else ""
                )
                p2b = (
                    f"{PROMPTS['delivery']}\n\n"
                    f"Audit delivery compliance and consistency for the audio you heard:\n"
                    f"- taskId: {a_item['taskId']}\n"
                    f"- opaqueToken: {tok}\n"
                    f"- requestedLanguage: {a_item.get('language')}\n"
                    f"- effectiveBrief: {json.dumps(a_item.get('effectiveBrief') or 'neutral', ensure_ascii=False)}"
                    f"{lf_block}\n"
                    f"Return the strict delivery audit JSON via finish."
                )
                deliv_out = await reviewer(p2b, SCHEMAS["delivery"])
                deliv_out["taskId"] = a_item["taskId"]
                deliv_out["opaqueToken"] = tok
                res["delivery"] = deliv_out
        finally:
            del reviewer
        return res

    for start in range(0, len(pending_blind_items), CONCURRENCY):
        wave = pending_blind_items[start:start + CONCURRENCY]
        outputs = await parallel(wave, _run_blind_and_audit)
        for out in outputs:
            tok = out["tok"]
            if out["blind"] is not None:
                blind_done[tok] = out["blind"]
            if out["diction"] is not None:
                diction_done[tok] = out["diction"]
            if out["delivery"] is not None:
                delivery_done[tok] = out["delivery"]
        _save()
        log(f"Blind+Audit wave {start + len(wave)}/{len(pending_blind_items)} saved")

# --- Phase 2: Standalone Delivery & Clone Fidelity Tasks ---
standalone_delivery = [
    a for a in PACKET.get("auditTasks", [])
    if a["opaqueToken"] not in blind_toks
    and "delivery" in (a.get("axes") or [])
    and a["opaqueToken"] not in delivery_done
]
if standalone_delivery:
    phase(f"Delivery Audit ({len(standalone_delivery)} takes)")

    async def _run_delivery(a_item: dict) -> dict:
        tok = a_item["opaqueToken"]
        abs_wav = str((ROOT / a_item["audioPath"]).resolve())
        prompt = (
            f"{STANDING}\n\n{PROMPTS['delivery']}\n\n"
            f"- taskId: {a_item['taskId']}\n"
            f"- opaqueToken: {tok}\n"
            f"- requestedLanguage: {a_item.get('language')}\n"
            f"- effectiveBrief: {json.dumps(a_item.get('effectiveBrief') or 'neutral', ensure_ascii=False)}\n"
            f"Call read_file on this exact WAV path before finishing:\n{abs_wav}"
        )
        out = await agent(prompt, schema=SCHEMAS["delivery"], role=f"Delivery {tok}", type_name="research", workspace="inherit", model="inherit")
        out["taskId"] = a_item["taskId"]
        out["opaqueToken"] = tok
        return out

    for start in range(0, len(standalone_delivery), CONCURRENCY):
        wave = standalone_delivery[start:start + CONCURRENCY]
        outputs = await parallel(wave, _run_delivery)
        for out in outputs:
            delivery_done[out["opaqueToken"]] = out
        _save()
        log(f"Delivery wave {start + len(wave)}/{len(standalone_delivery)} saved")

clone_tasks = [
    a for a in PACKET.get("auditTasks", [])
    if "clone" in (a.get("axes") or [])
    and a.get("clonePairAudioPath")
    and a["opaqueToken"] not in clone_done
]
if clone_tasks:
    phase(f"Clone Speaker Fidelity ({len(clone_tasks)} stitched pairs)")

    async def _run_clone(a_item: dict) -> dict:
        tok = a_item["opaqueToken"]
        abs_wav = str((ROOT / a_item["clonePairAudioPath"]).resolve())
        prompt = (
            f"{STANDING}\n\n{PROMPTS['clone']}\n\n"
            f"- taskId: {a_item['taskId']}\n"
            f"- opaqueToken: {tok}\n"
            f"- language: {a_item.get('language')}\n"
            f"- timeline: {json.dumps(a_item.get('cloneTimeline'))}\n"
            f"Call read_file on this exact stitched [Reference | 440 Hz tone | Candidate] WAV before finishing:\n{abs_wav}"
        )
        out = await agent(prompt, schema=SCHEMAS["clone"], role=f"Clone {tok}", type_name="research", workspace="inherit", model="inherit")
        out["taskId"] = a_item["taskId"]
        out["opaqueToken"] = tok
        return out

    for start in range(0, len(clone_tasks), CONCURRENCY):
        wave = clone_tasks[start:start + CONCURRENCY]
        outputs = await parallel(wave, _run_clone)
        for out in outputs:
            clone_done[out["opaqueToken"]] = out
        _save()
        log(f"Clone wave {start + len(wave)}/{len(clone_tasks)} saved")

# --- Phase 3: Fresh-Context Dual-Order Pairwise Tasks ---
pairwise_tasks = [
    p for p in PACKET.get("pairwiseTasks", [])
    if p["orderToken"] not in pairwise_done
]
if pairwise_tasks:
    phase(f"Pairwise A/B ({len(pairwise_tasks)} blinded order tasks)")

    async def _run_pairwise(p_item: dict) -> dict:
        otok = p_item["orderToken"]
        abs_wav = str((ROOT / p_item["audioPath"]).resolve())
        prompt = (
            f"{STANDING}\n\n{PROMPTS['pairwise']}\n\n"
            f"- taskId: {p_item['taskId']}\n"
            f"- orderToken: {otok}\n"
            f"- clipCount: {p_item['clipCount']}\n"
            f"- hasReferenceFirst: {p_item.get('hasReferenceFirst', False)}\n"
            f"- timeline: {json.dumps(p_item.get('timeline'))}\n"
            f"- language: {p_item.get('language')}\n"
            f"- intendedText: {json.dumps(p_item.get('intendedText'), ensure_ascii=False)}\n"
            f"- effectiveBrief: {json.dumps(p_item.get('effectiveBrief') or 'neutral', ensure_ascii=False)}\n"
            f"Call read_file on this exact stitched WAV before finishing:\n{abs_wav}"
        )
        out = await agent(prompt, schema=SCHEMAS["pairwise"], role=f"Pairwise {otok}", type_name="research", workspace="inherit", model="inherit")
        out["taskId"] = p_item["taskId"]
        out["orderToken"] = otok
        return out

    for start in range(0, len(pairwise_tasks), CONCURRENCY):
        wave = pairwise_tasks[start:start + CONCURRENCY]
        outputs = await parallel(wave, _run_pairwise)
        for out in outputs:
            pairwise_done[out["orderToken"]] = out
        _save()
        log(f"Pairwise wave {start + len(wave)}/{len(pairwise_tasks)} saved")

_save()
summary = {
    "session": SESSION,
    "verdictsPath": str(VERDICTS_PATH),
    "counts": {
        "blind": len(blind_done),
        "diction": len(diction_done),
        "delivery": len(delivery_done),
        "clone": len(clone_done),
        "pairwise": len(pairwise_done),
    },
}
print(json.dumps(summary, indent=1, sort_keys=True))
'''


def render_workflow_source(
    layout: Layout,
    session: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_label: str | None = None,
) -> str:
    """Render a self-contained `run_workflow` script bound to `session`."""

    session_name = multimodal.validate_session_name(session)
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 32:
        raise multimodal.MultimodalError("concurrency must be an integer between 1 and 32")
    out_dir = multimodal.session_dir(layout, session_name)
    if not (out_dir / "review-packet.json").is_file():
        raise multimodal.MultimodalError(f"session {session_name!r} has no review-packet.json")
    rubric, _ = multimodal.load_rubric(layout)
    chosen_model = model_label or str(rubric["targetModel"])
    return (
        _WORKFLOW_TEMPLATE
        .replace("__SESSION_ROOT__", json.dumps(str(layout.root.resolve())))
        .replace("__SESSION_NAME__", json.dumps(session_name))
        .replace("__CONCURRENCY__", str(concurrency))
        .replace("__MODEL_LABEL__", json.dumps(chosen_model))
    )


def write_workflow_script(
    layout: Layout,
    session: str,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    model_label: str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Write the session-local `run_workflow` script and return its path metadata."""

    session_name = multimodal.validate_session_name(session)
    source = render_workflow_source(layout, session_name, concurrency=concurrency, model_label=model_label)
    destination = Path(output_path) if output_path else (multimodal.session_dir(layout, session_name) / "workflow.py")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")
    return {
        "session": session_name,
        "workflowPath": str(destination.resolve()),
        "concurrency": concurrency,
        "verdictsPath": str((multimodal.session_dir(layout, session_name) / "verdicts.json").resolve()),
        "rubricSHA256": multimodal.rubric_digest(layout),
        "workflowSHA256": store.sha256_text(source),
    }
