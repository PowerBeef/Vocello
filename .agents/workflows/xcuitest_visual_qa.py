"""Multimodal XCUITest visual QA and run triage workflow for Vocello.

Reads `<run_dir>/screenshots/index.json` (retained by `scripts/ui_test.sh`) and
runs:
  1. `vocello-xcresult-triage` on `<run_dir>` (read-only verdict/log/crash triage)
  2. Parallel multimodal visual checks (`flash` tier, using `read_file` on PNGs)
     for clipped text, truncated controls, Dynamic Type overflow, Dark Mode
     contrast issues, broken localization keys, and unexpected system dialogs.

Args (JSON object):
  - run_dir (str, required): path to a finished `scripts/ui_test.sh` run directory
    (absolute or repo-relative, e.g. `build/artifacts/ui-tests/macos/macos-xcui-smoke-...`).
  - max_screenshots (int, optional): cap on screenshots inspected (default: 16).
"""

import json
from pathlib import Path

ROOT = Path(WORKSPACES[0]) if WORKSPACES else Path.cwd()
raw_run_dir = str(args.get("run_dir") or "").strip()
if not raw_run_dir:
    raise ValueError("Args must include 'run_dir' pointing to a finished scripts/ui_test.sh run directory.")

run_dir = Path(raw_run_dir)
if not run_dir.is_absolute():
    run_dir = (ROOT / run_dir).resolve()
if not run_dir.is_dir():
    raise FileNotFoundError(f"Run directory not found: {run_dir}")

max_screenshots = int(args.get("max_screenshots") or 16)

phase("Discover Retained Screenshots")

index_path = run_dir / "screenshots" / "index.json"
screenshot_entries = []
if index_path.is_file():
    data = json.loads(index_path.read_text(encoding="utf-8"))
    raw_items = data if isinstance(data, list) else data.get("screenshots", data.get("items", []))
    for item in raw_items:
        if isinstance(item, str):
            p = (index_path.parent / item).resolve()
            label = item
        elif isinstance(item, dict):
            rel = item.get("path") or item.get("file") or item.get("filename") or ""
            p = Path(rel) if Path(rel).is_absolute() else (index_path.parent / rel).resolve()
            label = str(item.get("name") or item.get("scenario") or rel)
        else:
            continue
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            screenshot_entries.append({"label": label, "path": str(p)})
else:
    for p in sorted((run_dir / "screenshots").glob("*.png")) if (run_dir / "screenshots").is_dir() else []:
        screenshot_entries.append({"label": p.name, "path": str(p.resolve())})

screenshot_entries = screenshot_entries[:max_screenshots]
log(f"Run dir: {run_dir.name} | screenshots queued: {len(screenshot_entries)}")

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string"},
        "passed": {"type": "boolean"},
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["classification", "passed", "summary", "issues"],
}

VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "status": {"type": "string", "enum": ["OK", "WARNING", "DEFECT"]},
        "observations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["label", "status", "observations"],
}

phase("Run Triage & Visual QA")

triage_task = agent(
    (
        "Read-only triage — never rerun the lane and edit nothing. "
        f"Classify the finished native UI run at `{run_dir}` from its retained verdicts, "
        "step ledger, xcodebuild logs, xcresult and crash artifacts."
    ),
    schema=TRIAGE_SCHEMA,
    role="XCResult Triage",
    type_name="vocello-xcresult-triage",
    workspace="inherit",
    model="inherit",
)

# Group screenshots into small batches of up to 4 images per flash reviewer to stay fast and bounded.
batches = [screenshot_entries[i : i + 4] for i in range(0, len(screenshot_entries), 4)]


async def inspect_batch(batch):
    items_desc = "\n".join(f"- {entry['label']}: {entry['path']}" for entry in batch)
    return await agent(
        (
            "Read-only visual QA — edit nothing, run no commands. "
            "Call `read_file` on each screenshot image below and inspect for: "
            "(1) clipped/truncated labels or buttons, (2) overlapping controls or Dynamic Type overflow, "
            "(3) unreadable Dark/Light contrast, (4) raw localization keys or placeholder strings, "
            "(5) unexpected macOS/iOS permission prompts or system overlays blocking the app. "
            "Never quote any private user paths or sensitive text.\n\n"
            f"Screenshots:\n{items_desc}"
        ),
        schema={"type": "array", "items": VISUAL_SCHEMA},
        role=f"Visual QA ({batch[0]['label']})",
        type_name="research",
        workspace="inherit",
        model="flash",
    )


triage_result = await triage_task
visual_batches = await parallel(batches, inspect_batch) if batches else []

phase("Aggregate Report")

log(f"Triage: {triage_result['classification']} (passed={triage_result['passed']}) — {triage_result['summary']}")
print(f"RUN: {run_dir.name}")
print(f"TRIAGE: {triage_result['classification']} | passed={triage_result['passed']}")
print(f"SUMMARY: {triage_result['summary']}")
if triage_result["issues"]:
    print("TRIAGE ISSUES:")
    for issue in triage_result["issues"]:
        print(f"- {issue}")

visual_items = [item for batch in visual_batches for item in batch]
defects = [item for item in visual_items if item["status"] != "OK"]
print(f"\nVISUAL QA: {len(visual_items)} screenshot(s) inspected, {len(defects)} warning/defect(s)")
for item in visual_items:
    if item["status"] != "OK":
        print(f"- [{item['status']}] {item['label']}: {'; '.join(item['observations'])}")
