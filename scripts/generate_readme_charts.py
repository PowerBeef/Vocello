#!/usr/bin/env python3
"""Generate the README performance charts as deterministic SVGs.

Reads tracked benchmark registry records and emits dark + light SVG variants
under docs/charts/. Output is byte-deterministic (no timestamps, fixed float
formatting), so `--check` can fail-close on staleness exactly like the other
derived artifacts. Python stdlib only — no plotting dependency joins the
toolchain for this.

Data provenance:
  - The RTF chart reads the newest canonical ui-generation record (RTF_RECORD);
    per release policy it moves to the new canonical record with every release
    (docs/reference/macos-release-qa.md "Performance surfaces ship current
    numbers"). The gate-delta chart reads the pinned same-day pre/post pair in
    GATE_RECORDS — a historical A/B isolating the generation performance gate;
    never re-point one side alone and never move it to a different-build record.
  - The long-form memory chart embeds the per-segment table from the local
    lane evidence run named in LONGFORM_RUN_ID (smoke lane
    `--long-form-segments 10`; lane evidence is never a registry record, so
    the privacy-safe numbers are pinned here with their run ID).

Usage:
  python3 scripts/generate_readme_charts.py            # rebuild
  python3 scripts/generate_readme_charts.py --check    # fail if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "charts"

# Newest canonical macOS UI matrix — refresh with every release.
RTF_RECORD = "macos-xcui-benchmark-20260729-023553-111d88c6"
# Pinned 2.1-pipeline vs 2.2-gate same-day A/B; historical, never re-pointed.
GATE_RECORDS = {
    "post": "macos-xcui-benchmark-20260723-083313-d02005ae",
    "pre": "macos-xcui-benchmark-20260723-054315-9b6f267b",
}
GATE_CELL = "custom/long/warm"

LONGFORM_RUN_ID = "macos-xcui-smoke-20260725-062451-8f15c1fd"
# (audio seconds, engine phys-footprint end MB, peak MB) per segment.
LONGFORM_SEGMENTS = (
    (49.9, 2454.7, 3037.4),
    (53.0, 2479.2, 2995.3),
    (61.1, 2507.0, 3040.3),
    (57.4, 2486.4, 3040.2),
    (57.6, 2505.5, 3040.8),
    (48.7, 2301.5, 3040.1),
    (55.8, 2476.3, 3040.9),
    (60.6, 2490.3, 3042.4),
    (56.6, 2302.3, 3041.5),
    (53.3, 2480.9, 3041.1),
    (54.7, 2505.8, 3041.6),
    (17.2, 2427.0, 2952.1),
)

MODES = ("custom", "design", "clone")
MODE_LABELS = {"custom": "Custom Voice", "design": "Voice Design", "clone": "Voice Cloning"}
LENGTHS = ("short", "medium", "long")

# Palette validated with the dataviz six-checks validator against each
# surface (brand hue families deepened until every check passed).
THEMES = {
    "dark": {
        "ink": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#30363d",
        "modes": {"custom": "#BE8A24", "design": "#9070E6", "clone": "#E26034"},
        "series": ("#9070E6", "#E26034"),
        "pre_bar": "#484f58",
        "box_fill": "#161b22",
    },
    "light": {
        "ink": "#1f2328",
        "muted": "#656d76",
        "grid": "#d1d9e0",
        "modes": {"custom": "#8A6410", "design": "#6C47C8", "clone": "#B4471B"},
        "series": ("#6C47C8", "#B4471B"),
        "pre_bar": "#afb8c1",
        "box_fill": "#f6f8fa",
    },
}

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def load_medians(record_id: str) -> dict[str, float]:
    path = ROOT / "benchmarks" / "runs" / "ui-generation" / f"{record_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    medians: dict[str, float] = {}
    for cell in payload["cells"]:
        medians[cell["key"]] = float(cell["statistics"]["rtf"]["median"])
    return medians


def svg_open(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        f'<g font-family="{FONT}">',
    ]


def text(x: float, y: float, value: str, *, fill: str, size: int = 12,
         weight: str = "normal", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{value}</text>'
    )


def rtf_chart(theme_name: str) -> str:
    theme = THEMES[theme_name]
    medians = load_medians(RTF_RECORD)
    width, height = 720, 428
    left, right, top = 110.0, 84.0, 64.0
    x0, x1 = left, width - right
    scale_max = 2.4

    def x_for(value: float) -> float:
        return x0 + (x1 - x0) * min(value, scale_max) / scale_max

    parts = svg_open(width, height)
    parts.append(text(16, 28, "Faster than playback in every mode", fill=theme["ink"], size=16, weight="600"))
    parts.append(text(16, 47, "Warm generation speed, multiples of realtime (higher is faster) · Mac mini M2, 8 GB",
                      fill=theme["muted"], size=12))

    bar_h, in_gap, group_gap = 16.0, 6.0, 26.0
    y = top + 14.0
    for grid_value in (0.5, 1.0, 1.5, 2.0):
        gx = x_for(grid_value)
        emphasized = grid_value == 1.0
        stroke = theme["muted"] if emphasized else theme["grid"]
        dash = "" if emphasized else ' stroke-dasharray="3 3"'
        parts.append(
            f'<line x1="{gx:.1f}" y1="{top:.1f}" x2="{gx:.1f}" y2="{height - 40}" '
            f'stroke="{stroke}" stroke-width="1"{dash}/>'
        )
        label = "1.0× · realtime" if emphasized else f"{grid_value:.1f}×"
        parts.append(text(gx, height - 22, label, fill=theme["muted"], size=11, anchor="middle"))

    for mode in MODES:
        color = theme["modes"][mode]
        parts.append(f'<circle cx="{22}" cy="{y + 2:.1f}" r="5" fill="{color}"/>')
        parts.append(text(32, y + 6, MODE_LABELS[mode], fill=theme["ink"], size=13, weight="600"))
        y += 16.0
        for length in LENGTHS:
            value = medians[f"{mode}/{length}/warm"]
            bw = x_for(value) - x0
            parts.append(text(x0 - 8, y + bar_h - 4, length, fill=theme["muted"], size=11, anchor="end"))
            parts.append(
                f'<path d="M{x0:.1f} {y:.1f} h{bw - 4:.1f} a4 4 0 0 1 4 4 v{bar_h - 8:.1f} '
                f'a4 4 0 0 1 -4 4 h-{bw - 4:.1f} z" fill="{color}"/>'
            )
            parts.append(text(x0 + bw + 6, y + bar_h - 4, f"{value:.2f}×", fill=theme["ink"], size=11))
            y += bar_h + in_gap
        y += group_gap - in_gap
    parts.append(text(width - 16, height - 6,
                      f"record {RTF_RECORD[-8:]} · benchmarks/HISTORY.md",
                      fill=theme["muted"], size=10, anchor="end"))
    parts.extend(("</g>", "</svg>"))
    return "\n".join(parts) + "\n"


def gate_chart(theme_name: str) -> str:
    theme = THEMES[theme_name]
    pre = load_medians(GATE_RECORDS["pre"])[GATE_CELL]
    post = load_medians(GATE_RECORDS["post"])[GATE_CELL]
    delta = 100.0 * (post - pre) / pre
    width, height = 720, 190
    left = 210.0
    x0, x1 = left, width - 130.0
    scale_max = 2.0

    def x_for(value: float) -> float:
        return x0 + (x1 - x0) * min(value, scale_max) / scale_max

    parts = svg_open(width, height)
    parts.append(text(16, 28, "The generation performance gate", fill=theme["ink"], size=16, weight="600"))
    parts.append(text(16, 47, "Same Mac, same take (Custom, long, warm): heavy visual effects now pause while generating",
                      fill=theme["muted"], size=12))
    parts.append(text(width - 16, 40, f"+{delta:.0f}%", fill=theme["modes"]["custom"], size=30,
                      weight="700", anchor="end"))

    bar_h = 18.0
    rows = (("before the gate (2.1 pipeline)", pre, theme["pre_bar"]),
            ("with the gate (2.2)", post, theme["modes"]["custom"]))
    y = 78.0
    realtime_x = x_for(1.0)
    parts.append(
        f'<line x1="{realtime_x:.1f}" y1="{y - 10:.1f}" x2="{realtime_x:.1f}" y2="{y + 2 * bar_h + 20:.1f}" '
        f'stroke="{theme["muted"]}" stroke-width="1"/>'
    )
    parts.append(text(realtime_x, y - 16, "realtime", fill=theme["muted"], size=10, anchor="middle"))
    for label, value, color in rows:
        bw = x_for(value) - x0
        parts.append(text(x0 - 8, y + bar_h - 5, label, fill=theme["muted"], size=11, anchor="end"))
        parts.append(
            f'<path d="M{x0:.1f} {y:.1f} h{bw - 4:.1f} a4 4 0 0 1 4 4 v{bar_h - 8:.1f} '
            f'a4 4 0 0 1 -4 4 h-{bw - 4:.1f} z" fill="{color}"/>'
        )
        parts.append(text(x0 + bw + 6, y + bar_h - 5, f"{value:.2f}×", fill=theme["ink"], size=11))
        y += bar_h + 14.0
    parts.append(text(width - 16, height - 8,
                      f"records {GATE_RECORDS['pre'][-8:]} → {GATE_RECORDS['post'][-8:]}",
                      fill=theme["muted"], size=10, anchor="end"))
    parts.extend(("</g>", "</svg>"))
    return "\n".join(parts) + "\n"


def memory_chart(theme_name: str) -> str:
    theme = THEMES[theme_name]
    width, height = 720, 340
    left, right, top, bottom = 64.0, 44.0, 72.0, 58.0
    x0, x1 = left, width - right
    y0, y1 = float(height - bottom), top
    y_max = 3200.0
    count = len(LONGFORM_SEGMENTS)

    def x_for(index: int) -> float:
        return x0 + (x1 - x0) * index / (count - 1)

    def y_for(mb: float) -> float:
        return y0 - (y0 - y1) * mb / y_max

    ends = [row[1] for row in LONGFORM_SEGMENTS]
    peaks = [row[2] for row in LONGFORM_SEGMENTS]
    growth = 100.0 * (ends[-1] - ends[0]) / ends[0]
    cumulative: list[float] = []
    running = 0.0
    for row in LONGFORM_SEGMENTS:
        running += row[0]
        cumulative.append(running)

    parts = svg_open(width, height)
    parts.append(text(16, 28, "Memory stays flat at audiobook scale", fill=theme["ink"], size=16, weight="600"))
    parts.append(text(16, 47, "Engine physical footprint across a 12-segment long-form project "
                              f"({cumulative[-1] / 60:.1f} min of audio)", fill=theme["muted"], size=12))

    for grid_mb in (1000, 2000, 3000):
        gy = y_for(grid_mb)
        parts.append(
            f'<line x1="{x0:.1f}" y1="{gy:.1f}" x2="{x1:.1f}" y2="{gy:.1f}" '
            f'stroke="{theme["grid"]}" stroke-width="1" stroke-dasharray="3 3"/>'
        )
        parts.append(text(x0 - 8, gy + 4, f"{grid_mb / 1000:.0f} GB", fill=theme["muted"], size=11, anchor="end"))
    parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y0:.1f}" '
                 f'stroke="{theme["grid"]}" stroke-width="1"/>')

    series = (("peak while generating", peaks, theme["series"][1]),
              ("after each segment", ends, theme["series"][0]))
    for label, values, color in series:
        points = " ".join(f"{x_for(i):.1f},{y_for(v):.1f}" for i, v in enumerate(values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" '
                     f'stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(values):
            parts.append(f'<circle cx="{x_for(i):.1f}" cy="{y_for(v):.1f}" r="3" fill="{color}"/>')

    legend_x = x1 - 170.0
    for offset, (label, values, color) in enumerate(series):
        ly = 20.0 + offset * 16
        parts.append(f'<rect x="{legend_x:.1f}" y="{ly - 8:.1f}" width="10" height="10" rx="2" fill="{color}"/>')
        parts.append(text(legend_x + 16, ly + 1, label, fill=theme["muted"], size=11))

    parts.append(text(x_for(count - 1), y_for(ends[-1]) + 20, f"first→last {growth:+.1f}%",
                      fill=theme["ink"], size=11, weight="600", anchor="end"))
    for index in (0, 5, count - 1):
        anchor = "end" if index == count - 1 else ("start" if index == 0 else "middle")
        parts.append(text(x_for(index), y0 + 16, f"seg {index}", fill=theme["muted"], size=11, anchor=anchor))
        parts.append(text(x_for(index), y0 + 30, f"{cumulative[index]:.0f}s audio",
                          fill=theme["muted"], size=10, anchor=anchor))
    parts.append(text(width - 16, height - 6, f"smoke run {LONGFORM_RUN_ID[-8:]} · --long-form-segments 10",
                      fill=theme["muted"], size=10, anchor="end"))
    parts.extend(("</g>", "</svg>"))
    return "\n".join(parts) + "\n"


def architecture_chart(theme_name: str) -> str:
    theme = THEMES[theme_name]
    width, height = 720, 252
    violet = theme["modes"]["design"]
    parts = svg_open(width, height)

    def box(x: float, y: float, w: float, h: float, lines: tuple[str, ...], *,
            stroke: str, title: bool = False) -> None:
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
            f'fill="{theme["box_fill"]}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        line_height = 16.0
        start = y + h / 2 - line_height * (len(lines) - 1) / 2 + 4.5
        for index, label in enumerate(lines):
            weight = "600" if title and index == 0 else "normal"
            fill = theme["ink"] if index == 0 else theme["muted"]
            parts.append(text(x + w / 2, start + index * line_height, label,
                              fill=fill, size=12, weight=weight, anchor="middle"))

    def arrow(x1: float, y1: float, x2: float, y2: float) -> None:
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{theme["muted"]}" stroke-width="1.5"/>')
        if x2 > x1:  # rightward head
            parts.append(f'<path d="M{x2:.1f} {y2:.1f} l-7 -4 v8 z" fill="{theme["muted"]}"/>')
        elif y2 > y1:  # downward head
            parts.append(f'<path d="M{x2:.1f} {y2:.1f} l-4 -7 h8 z" fill="{theme["muted"]}"/>')
        else:  # upward head
            parts.append(f'<path d="M{x2:.1f} {y2:.1f} l-4 7 h8 z" fill="{theme["muted"]}"/>')

    # Owned-runtime group.
    parts.append(
        f'<rect x="356" y="30" width="348" height="164" rx="10" fill="{violet}" '
        f'fill-opacity="0.07" stroke="{violet}" stroke-width="1.5"/>'
    )
    parts.append(text(372, 50, "VocelloQwen3Core", fill=violet, size=12, weight="600"))
    parts.append(text(496, 50, "· the owned runtime", fill=theme["muted"], size=11))

    box(16, 84, 116, 44, ("SwiftUI app",), stroke=theme["grid"], title=True)
    box(180, 84, 132, 44, ("Engine service", "separate process"), stroke=theme["grid"], title=True)
    box(372, 62, 128, 52, ("Engine actor", "owns each session"), stroke=theme["grid"], title=True)
    box(532, 62, 156, 52, ("Qwen3-TTS talker", "+ code predictor"), stroke=theme["grid"], title=True)
    box(532, 128, 156, 48, ("Mimi decoder", "streams audio"), stroke=theme["grid"], title=True)
    box(372, 128, 128, 48, ("MLX · Metal", "unified memory"), stroke=theme["grid"], title=True)

    arrow(132, 106, 176, 106)
    parts.append(text(154, 76, "XPC", fill=theme["muted"], size=11, anchor="middle"))
    arrow(312, 106, 368, 106)
    arrow(500, 88, 528, 88)
    arrow(610, 114, 610, 124)
    # Talker and decoder execute on MLX (plain connector, no direction).
    parts.append(f'<line x1="500" y1="152" x2="528" y2="152" '
                 f'stroke="{theme["muted"]}" stroke-width="1.5" stroke-dasharray="3 3"/>')

    # Streaming return path: decoder → app, chunk by chunk.
    parts.append(
        f'<path d="M610 176 v46 h-536 v-83" fill="none" stroke="{violet}" stroke-width="1.5"/>'
    )
    parts.append(f'<path d="M74 132 l-4 7 h8 z" fill="{violet}"/>')
    parts.append(text(360, 240, "PCM audio streams back chunk by chunk — playback starts before generation finishes",
                      fill=theme["muted"], size=11, anchor="middle"))
    parts.extend(("</g>", "</svg>"))
    return "\n".join(parts) + "\n"


CHARTS = {
    "architecture": architecture_chart,
    "rtf-by-mode": rtf_chart,
    "gate-delta": gate_chart,
    "longform-memory": memory_chart,
}


def render_all() -> dict[str, str]:
    rendered: dict[str, str] = {}
    for chart_name, renderer in sorted(CHARTS.items()):
        for theme_name in ("dark", "light"):
            rendered[f"{chart_name}-{theme_name}.svg"] = renderer(theme_name)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if committed charts are stale")
    args = parser.parse_args()

    rendered = render_all()
    if args.check:
        stale = [
            name for name, content in rendered.items()
            if not (OUTPUT_DIR / name).is_file()
            or (OUTPUT_DIR / name).read_text(encoding="utf-8") != content
        ]
        if stale:
            print(f"error: README charts are stale: {', '.join(sorted(stale))}", file=sys.stderr)
            print("run: python3 scripts/generate_readme_charts.py", file=sys.stderr)
            return 1
        print(f"README charts: fresh ({len(rendered)} files)")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in sorted(rendered.items()):
        (OUTPUT_DIR / name).write_text(content, encoding="utf-8")
    print(f"Rendered {len(rendered)} chart files → {OUTPUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
