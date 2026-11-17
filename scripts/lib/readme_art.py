"""The README's branded art, drawn as deterministic SVG.

Every image the README shows is a self-contained card on Vocello's charcoal canvas
(the maintainer's choice of 2026-11-17: identical in GitHub's light and dark themes,
as the app is dark-first). The palette and type stacks are website/src/tokens.css;
the lockup is the app's own VocelloLaunchLogo, embedded as a data URI rather than
redrawn. Nothing here reads a record: scripts/generate_readme_charts.py passes the
measured numbers in, so `--check` keeps the art and its numbers together.

Output rules: stdlib only, no scripts, no external fonts or images (GitHub renders
README SVGs as images), fixed number formatting so a rebuild is byte-identical, and
a title and description on every image.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

# --- tokens (website/src/tokens.css) ---------------------------------------

CANVAS = "#16181E"
CARD = "#1C1E26"
DEEP = "#111318"
RAISED = "#23262F"
FIELD = "#2A2C36"
LINE = "#3A3D48"
TEXT = "#F5F6F8"
SECONDARY = "#C9CBD4"
MUTED = "#8C8F9B"
GOLD = "#EDCC8A"
GOLD_DEEP = "#B5832E"
LAVENDER = "#BFAADB"
TERRACOTTA = "#DBA887"
MODE_COLORS = {"custom": GOLD, "design": LAVENDER, "clone": TERRACOTTA}
MODE_NAMES = {"custom": "Built-in Voice", "design": "Voice Design", "clone": "Voice Cloning"}
MODES = ("custom", "design", "clone")

DISPLAY = "ui-rounded, 'SF Pro Rounded', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
BODY = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace"

WIDE = 880
NARROW = 400

LOCKUP = Path("Sources/Assets.xcassets/VocelloLaunchLogo.imageset/vocello_launch_logo@3x.png")
LOCKUP_SIZE = (744, 288)

# 24-unit line icons in the docs/readme/icons style: round caps, drawn in one stroke color.
ICONS = {
    "voice": ('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19.5c0-3.3 2.5-5.6 5.5-5.6s5.5 2.3 5.5 5.6"/>'
              '<path d="M16.6 6.6a5 5 0 0 1 0 6.8"/><path d="M19.3 4.2a8.6 8.6 0 0 1 0 11.6"/>'),
    "design": ('<path d="M11 3.5l1.7 4.6 4.6 1.7-4.6 1.7L11 16.1l-1.7-4.6-4.6-1.7 4.6-1.7z"/>'
               '<path d="M18 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>'),
    "clone": ('<path d="M2.5 13.5h2.3l1.9-4.3 2.7 8.6 2.7-11.6 2.5 10 1.8-2.7h2.1"/>'
              '<path d="M7 6.5h1.6M16 6.5h5M18.5 4v5" stroke-opacity="0.6"/>'),
    "script": ('<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4.5"/>'),
    "globe": ('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>'
              '<path d="M12 3.5c2.6 2.4 3.9 5.2 3.9 8.5s-1.3 6.1-3.9 8.5c-2.6-2.4-3.9-5.2-3.9-8.5s1.3-6.1 3.9-8.5z"/>'),
    "library": ('<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-3.8L6 20V5a1 1 0 0 1 1-1z"/>'),
    "history": ('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
    "shield": ('<path d="M12 3.5l7 2.8v5.2c0 4.3-2.9 7.6-7 9-4.1-1.4-7-4.7-7-9V6.3z"/>'
               '<path d="M9 12.2l2.1 2.1 4-4.3"/>'),
    "lock": ('<rect x="6" y="10.5" width="12" height="9.5" rx="2.2"/>'
             '<path d="M8.8 10.5V8a3.2 3.2 0 0 1 6.4 0v2.5"/><path d="M12 14.2v2.2"/>'),
    "terminal": ('<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M7.5 10l2.8 2.5-2.8 2.5"/>'
                 '<path d="M12.5 15.5h4"/>'),
    "update": ('<path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19 4.5v3.5h-3.5"/>'),
    "mac": ('<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>'),
    "phone": ('<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="M11 18h2"/>'),
    "download": ('<path d="M12 4v11"/><path d="M7.5 11l4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>'),
}


@dataclass(frozen=True)
class Measured:
    """The numbers the performance card shows, already reduced from records."""

    seconds_per_minute: float     # warm generation time for one minute of speech (median take)
    first_audio_low: float        # fastest mode's median seconds from submit to the first audio
    first_audio_high: float       # slowest mode's median seconds from submit to the first audio
    peak_low_gb: float            # lowest per-mode peak footprint while generating, GiB
    peak_high_gb: float           # highest per-mode peak footprint while generating, GiB
    hardware: str                 # "Mac mini M6, 16 GB"
    release: str                  # "Vocello 3.1"
    provenance: str               # "median of 2 records through 0b6bc26b"
    memory_record: str            # the memory record's short id


@dataclass(frozen=True)
class Release:
    version: str                  # "3.1.0"
    mac_minimum: str              # "26"
    ios_minimum: str              # "26"


# --- primitives ------------------------------------------------------------

def num(value: float) -> str:
    """A fixed, short decimal: rebuilds stay byte-identical."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def text_width(value: str, size: float, *, bold: bool = False) -> float:
    """A conservative width estimate for SF Pro (layout only; nothing depends on it exactly)."""
    narrow = sum(value.count(c) for c in "ilI.,:;'|!·( )")
    wide = sum(value.count(c) for c in "MWmw@")
    regular = len(value) - narrow - wide
    unit = 0.58 if bold else 0.55
    return size * (regular * unit + narrow * 0.3 + wide * 0.85)


def text(x: float, y: float, value: str, *, size: float, fill: str = TEXT, weight: int = 400,
         family: str = BODY, anchor: str = "start", opacity: float | None = None,
         spacing: float | None = None) -> str:
    attributes = [f'x="{num(x)}"', f'y="{num(y)}"', f'font-family="{family}"', f'font-size="{num(size)}"',
                  f'font-weight="{weight}"', f'fill="{fill}"']
    if anchor != "start":
        attributes.append(f'text-anchor="{anchor}"')
    if opacity is not None:
        attributes.append(f'fill-opacity="{num(opacity)}"')
    if spacing is not None:
        attributes.append(f'letter-spacing="{num(spacing)}"')
    return f"<text {' '.join(attributes)}>{escape(value)}</text>"


def icon(name: str, x: float, y: float, *, color: str, size: float = 24, width: float = 1.8) -> str:
    scale = size / 24
    return (f'<g transform="translate({num(x)} {num(y)}) scale({num(scale)})" fill="none" stroke="{color}" '
            f'stroke-width="{num(width)}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def icon_tile(name: str, x: float, y: float, *, color: str, size: float = 44) -> str:
    inner = size * 0.56
    offset = (size - inner) / 2
    return (f'<rect x="{num(x)}" y="{num(y)}" width="{num(size)}" height="{num(size)}" rx="{num(size * 0.28)}" '
            f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-opacity="0.38"/>'
            + icon(name, x + offset, y + offset, color=color, size=inner))


def pill(x: float, y: float, label: str, color: str, *, size: float = 15, height: float = 36) -> tuple[str, float]:
    """A mode pill; returns its markup and width."""
    width = text_width(label, size, bold=True) + 46
    markup = (f'<rect x="{num(x)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" rx="{num(height / 2)}" '
              f'fill="{color}" fill-opacity="0.13" stroke="{color}" stroke-opacity="0.42"/>'
              f'<circle cx="{num(x + 19)}" cy="{num(y + height / 2)}" r="4.5" fill="{color}"/>'
              + text(x + 32, y + height / 2 + size * 0.36, label, size=size, fill=color, weight=600))
    return markup, width


def card(width: float, height: float, *, glows: tuple[tuple[float, float, float, str, float], ...] = ()) -> tuple[str, str]:
    """The charcoal canvas every image sits on: (defs, background)."""
    defs = [f'<linearGradient id="canvas" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{CARD}"/><stop offset="1" stop-color="{DEEP}"/></linearGradient>']
    background = [f'<rect width="{num(width)}" height="{num(height)}" rx="24" fill="url(#canvas)"/>']
    for index, (cx, cy, radius, color, opacity) in enumerate(glows):
        defs.append(f'<radialGradient id="glow{index}" cx="{num(cx)}" cy="{num(cy)}" r="{num(radius)}" '
                    f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{color}" stop-opacity="{num(opacity)}"/>'
                    f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>')
        background.append(f'<rect width="{num(width)}" height="{num(height)}" rx="24" fill="url(#glow{index})"/>')
    background.append(f'<rect x="0.5" y="0.5" width="{num(width - 1)}" height="{num(height - 1)}" rx="23.5" '
                      f'fill="none" stroke="#FFFFFF" stroke-opacity="0.07"/>')
    return "".join(defs), "".join(background)


def svg(width: float, height: float, title: str, description: str, body: list[str], defs: str = "") -> str:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(width)}" height="{num(height)}" '
            f'viewBox="0 0 {num(width)} {num(height)}" role="img" aria-labelledby="title desc">')
    parts = [head, f'<title id="title">{escape(title)}</title>', f'<desc id="desc">{escape(description)}</desc>']
    if defs:
        parts.append(f"<defs>{defs}</defs>")
    parts.extend(body)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def wrap(value: str, size: float, width: float, *, bold: bool = False) -> list[str]:
    """Greedy word wrap against the width estimate."""
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}".strip()
        if current and text_width(candidate, size, bold=bold) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def paragraph(x: float, y: float, value: str, *, size: float, width: float, leading: float,
              fill: str = SECONDARY, anchor: str = "start", weight: int = 400) -> tuple[str, float]:
    """Wrapped lines; returns markup and the baseline after the last line."""
    lines = wrap(value, size, width, bold=weight >= 600)
    markup = "".join(text(x, y + index * leading, line, size=size, fill=fill, anchor=anchor, weight=weight)
                     for index, line in enumerate(lines))
    return markup, y + (len(lines) - 1) * leading


def waveform(x: float, y: float, width: float, height: float, *, bars: int, gradient: str) -> str:
    """A symmetric voice waveform: rounded bars under a smooth two-hump envelope."""
    import math
    step = width / bars
    bar = step * 0.52
    parts = []
    for index in range(bars):
        t = index / (bars - 1)
        envelope = 0.16 + 0.84 * (0.55 * math.sin(math.pi * t) ** 1.4 + 0.45 * abs(math.sin(3.1 * math.pi * t)) ** 2)
        ripple = 0.78 + 0.22 * math.sin(index * 1.7) ** 2
        h = max(bar, height * min(1.0, envelope * ripple))
        bx = x + index * step + (step - bar) / 2
        parts.append(f'<rect x="{num(bx)}" y="{num(y + (height - h) / 2)}" width="{num(bar)}" height="{num(h)}" '
                     f'rx="{num(bar / 2)}" fill="url(#{gradient})"/>')
    return "".join(parts)


def mode_gradient(identifier: str, x1: float, x2: float) -> str:
    return (f'<linearGradient id="{identifier}" x1="{num(x1)}" y1="0" x2="{num(x2)}" y2="0" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{GOLD}"/><stop offset="0.5" stop-color="{LAVENDER}"/>'
            f'<stop offset="1" stop-color="{TERRACOTTA}"/></linearGradient>')


def lockup(root: Path, x: float, y: float, width: float) -> str:
    data = base64.b64encode((root / LOCKUP).read_bytes()).decode("ascii")
    height = width * LOCKUP_SIZE[1] / LOCKUP_SIZE[0]
    return (f'<image x="{num(x)}" y="{num(y)}" width="{num(width)}" height="{num(height)}" '
            f'href="data:image/png;base64,{data}"/>')


# --- the images ------------------------------------------------------------

TAGLINE = ("Private text to speech", "for your Mac and iPhone.")
HERO_LINE = "Pick, describe or clone a voice. Vocello speaks your script in seconds, right on your Apple Silicon."


def hero(root: Path) -> str:
    width, height = WIDE, 396
    defs, background = card(width, height, glows=((90, 30, 430, GOLD, 0.2), (830, 110, 380, LAVENDER, 0.15),
                                                   (650, 400, 330, TERRACOTTA, 0.13)))
    defs += mode_gradient("wave", 548, 836)
    body = [background, lockup(root, 34, 22, 360)]
    body.append(text(56, 202, TAGLINE[0], size=34, weight=600, family=DISPLAY))
    body.append(text(56, 242, TAGLINE[1], size=34, weight=600, family=DISPLAY, fill=GOLD))
    line, after = paragraph(56, 278, HERO_LINE, size=16, width=460, leading=23)
    body.append(line)
    body.append(waveform(548, 96, 288, 196, bars=30, gradient="wave"))
    x = 56.0
    for mode in MODES:
        markup, pill_width = pill(x, after + 24, MODE_NAMES[mode], MODE_COLORS[mode], size=14, height=34)
        body.append(markup)
        x += pill_width + 10
    return svg(width, height, "Vocello: private text to speech for your Mac and iPhone",
               "The Vocello logo above the line Private text to speech for your Mac and iPhone, a voice waveform "
               "in gold, lavender and terracotta, and the three modes: Built-in Voice, Voice Design and Voice Cloning.",
               body, defs)


def hero_narrow(root: Path) -> str:
    width = NARROW
    body = [lockup(root, 32, 10, 336)]
    body.append(text(width / 2, 172, TAGLINE[0], size=27, weight=600, family=DISPLAY, anchor="middle"))
    body.append(text(width / 2, 206, TAGLINE[1], size=27, weight=600, family=DISPLAY, anchor="middle", fill=GOLD))
    line, after = paragraph(width / 2, 240, HERO_LINE, size=15, width=330, leading=22, anchor="middle")
    body.append(line)
    body.append(waveform(40, after + 22, 320, 110, bars=24, gradient="wave"))
    y = after + 156
    for mode in MODES:
        label_width = text_width(MODE_NAMES[mode], 14, bold=True) + 46
        markup, _ = pill((width - label_width) / 2, y, MODE_NAMES[mode], MODE_COLORS[mode], size=14, height=34)
        body.append(markup)
        y += 44
    height = y + 18
    defs, background = card(width, height, glows=((40, 20, 300, GOLD, 0.22), (380, 300, 260, LAVENDER, 0.15),
                                                   (120, height, 260, TERRACOTTA, 0.13)))
    defs += mode_gradient("wave", 40, 360)
    return svg(width, height, "Vocello: private text to speech for your Mac and iPhone",
               "The Vocello logo, the line Private text to speech for your Mac and iPhone, a voice waveform and the "
               "three modes.", [background, *body], defs)


MODE_CARDS = (
    ("custom", "voice", "Nine natural voices in ten languages, in the delivery you ask for.",
     "9 voices · 10 languages"),
    ("design", "design", "Describe a voice in plain words, like a warm, clear narrator, and keep the ones you like.",
     "Saved to your library"),
    ("clone", "clone", "A new voice from a short clip of a voice you own or have permission to use.",
     "Follows the reference voice"),
)


def _mode_card(x: float, y: float, w: float, h: float, mode: str, glyph: str, line: str, tag: str,
               *, compact: bool = False) -> str:
    color = MODE_COLORS[mode]
    parts = [f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="18" fill="{RAISED}" '
             f'fill-opacity="0.72" stroke="{color}" stroke-opacity="0.32"/>',
             f'<rect x="{num(x + 24)}" y="{num(y)}" width="{num(w - 48)}" height="3" rx="1.5" fill="{color}"/>']
    if compact:
        parts.append(icon_tile(glyph, x + 20, y + 24, color=color, size=42))
        parts.append(text(x + 78, y + 46, MODE_NAMES[mode], size=19, weight=600, family=DISPLAY))
        parts.append(text(x + 78, y + 66, tag, size=12.5, fill=color, weight=600))
        markup, _ = paragraph(x + 20, y + 98, line, size=14, width=w - 40, leading=20)
        parts.append(markup)
    else:
        parts.append(icon_tile(glyph, x + 22, y + 28, color=color, size=46))
        parts.append(text(x + 22, y + 108, MODE_NAMES[mode], size=21, weight=600, family=DISPLAY))
        markup, _ = paragraph(x + 22, y + 138, line, size=14.5, width=w - 44, leading=21)
        parts.append(markup)
        parts.append(text(x + 22, y + h - 24, tag, size=12.5, fill=color, weight=600))
    return "".join(parts)


def modes() -> str:
    width, height = WIDE, 300
    defs, background = card(width, height)
    body = [background]
    w, gap, margin = 264.0, 16.0, 28.0
    for index, (mode, glyph, line, tag) in enumerate(MODE_CARDS):
        body.append(_mode_card(margin + index * (w + gap), 28, w, 244, mode, glyph, line, tag))
    return svg(width, height, "Three ways to make a voice",
               "Built-in Voice: nine voices in ten languages. Voice Design: describe a voice in plain words. "
               "Voice Cloning: a new voice from a short clip you may use.", body, defs)


def modes_narrow() -> str:
    width, card_height, gap, margin = NARROW, 150.0, 14.0, 24.0
    height = margin * 2 + card_height * 3 + gap * 2
    defs, background = card(width, height)
    body = [background]
    for index, (mode, glyph, line, tag) in enumerate(MODE_CARDS):
        body.append(_mode_card(margin, margin + index * (card_height + gap), width - margin * 2, card_height,
                               mode, glyph, line, tag, compact=True))
    return svg(width, height, "Three ways to make a voice",
               "Built-in Voice, Voice Design and Voice Cloning.", body, defs)


FEATURES = (
    ("script", "Long scripts", "Plays while it generates"),
    ("globe", "Ten languages", "Detected from your script"),
    ("library", "Saved voices", "Design once, reuse often"),
    ("history", "Searchable History", "Every take, kept on device"),
    ("shield", "Marked as AI", "Inaudible AudioSeal mark"),
    ("lock", "Private by design", "No account, no cloud"),
    ("terminal", "CLI and AI agents", "JSON and an MCP server"),
    ("update", "Signed updates", "Notarized, self-updating"),
)


def _feature_tile(x: float, y: float, w: float, h: float, glyph: str, title: str, line: str) -> str:
    return (f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="16" fill="{RAISED}" '
            f'fill-opacity="0.6" stroke="#FFFFFF" stroke-opacity="0.06"/>'
            + icon_tile(glyph, x + 18, y + 18, color=GOLD, size=40)
            + text(x + 18, y + 84, title, size=16, weight=600, family=DISPLAY)
            + text(x + 18, y + 106, line, size=13, fill=MUTED))


def features(columns: int = 4) -> str:
    width = WIDE if columns == 4 else NARROW
    margin, gap, h = (28.0, 14.0, 128.0) if columns == 4 else (22.0, 12.0, 128.0)
    rows = -(-len(FEATURES) // columns)
    w = (width - margin * 2 - gap * (columns - 1)) / columns
    height = margin * 2 + rows * h + (rows - 1) * gap
    defs, background = card(width, height, glows=((width * 0.15, 0, width * 0.7, GOLD, 0.08),))
    body = [background]
    for index, (glyph, title, line) in enumerate(FEATURES):
        row, column = divmod(index, columns)
        body.append(_feature_tile(margin + column * (w + gap), margin + row * (h + gap), w, h, glyph, title, line))
    return svg(width, height, "Made for real projects",
               "Long scripts that play while they generate, ten languages, saved voices, a searchable History, "
               "takes marked as AI-generated, no account or cloud, a command line for scripts and AI agents, "
               "and signed updates.", body, defs)


def _stat(x: float, y: float, value: str, label: str, note: str, color: str, *, room: float,
          largest: float = 50) -> str:
    size = min(largest, room / max(text_width(value, 1, bold=True), 0.01))
    return (text(x, y, value, size=size, weight=700, family=DISPLAY, fill=color, spacing=-0.5)
            + text(x, y + 34, label, size=16, weight=600)
            + text(x, y + 57, note, size=13, fill=MUTED))


def span(low: float, high: float, *, unit: str, digits: int = 1) -> str:
    """'2.5–4.2 GB', or one value when both ends round alike."""
    low_text, high_text = num(round(low, digits)), num(round(high, digits))
    return f"{low_text} {unit}" if low_text == high_text else f"{low_text}–{high_text} {unit}"


def performance_figures(measured: Measured) -> tuple[str, str, str]:
    """The three headline figures, as the card draws them."""
    return (f"{round(measured.seconds_per_minute):d} s",
            span(measured.first_audio_low, measured.first_audio_high, unit="s"),
            span(measured.peak_low_gb, measured.peak_high_gb, unit="GB"))


def performance(measured: Measured, *, narrow: bool = False) -> str:
    minute, first, memory = performance_figures(measured)
    stats = (
        (minute, "to make one minute of speech", "warm median, every mode and length", GOLD),
        (first, "until the first audio is ready", "warm, Built-in Voice to Cloning", LAVENDER),
        (memory, "peak memory while it speaks", "Built-in Voice to Cloning", TERRACOTTA),
    )
    header = f"{measured.release} on a {measured.hardware}"
    source = f"Benchmark records: {measured.provenance}; memory {measured.memory_record}"
    if narrow:
        width, height = NARROW, 506
        defs, background = card(width, height, glows=((0, 0, 320, GOLD, 0.12),))
        body = [background, text(26, 44, header.upper(), size=11.5, fill=MUTED, weight=600, spacing=1.2)]
        for index, (value, label, note, color) in enumerate(stats):
            y = 112 + index * 130
            if index:
                body.append(f'<rect x="26" y="{num(y - 52)}" width="{num(width - 52)}" height="1" fill="{FIELD}"/>')
            body.append(_stat(26, y, value, label, note, color, room=width - 52, largest=46))
        markup, _ = paragraph(26, height - 38, source, size=11.5, width=width - 52, leading=16, fill=MUTED)
        body.append(markup)
    else:
        width, height = WIDE, 270
        defs, background = card(width, height, glows=((60, 0, 420, GOLD, 0.12), (860, 270, 360, TERRACOTTA, 0.09)))
        body = [background, text(36, 50, header.upper(), size=12, fill=MUTED, weight=600, spacing=1.4)]
        column = (width - 72) / 3
        for index, (value, label, note, color) in enumerate(stats):
            x = 36 + index * column
            if index:
                body.append(f'<rect x="{num(x - 18)}" y="96" width="1" height="104" fill="{FIELD}"/>')
            body.append(_stat(x, 132, value, label, note, color, room=column - 30))
        body.append(text(36, height - 26, source, size=11.5, fill=MUTED))
    return svg(width, height, "How Vocello performs",
               f"{measured.release} on a {measured.hardware}: about {minute} to make one minute of speech, "
               f"{first} until the first audio is ready, and {memory} of peak memory while it speaks.",
               body, defs)


def _box(x: float, y: float, w: float, h: float, *, stroke: str = "#FFFFFF", opacity: float = 0.08,
         fill: str = RAISED, fill_opacity: float = 0.75, radius: float = 14) -> str:
    return (f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="{num(radius)}" fill="{fill}" '
            f'fill-opacity="{num(fill_opacity)}" stroke="{stroke}" stroke-opacity="{num(opacity)}"/>')


def _arrow(x1: float, y1: float, x2: float, y2: float, *, color: str = MUTED) -> str:
    return (f'<path d="M{num(x1)} {num(y1)} L{num(x2)} {num(y2)}" stroke="{color}" stroke-width="1.6" '
            f'fill="none" marker-end="url(#arrow)"/>')


ARROW_MARKER = (f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M1 1L9 5L1 9" fill="none" stroke="{MUTED}" '
                f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker>')


def architecture() -> str:
    width, height = WIDE, 600
    defs, background = card(width, height, glows=((440, 330, 420, LAVENDER, 0.08),))
    defs += ARROW_MARKER
    body = [background, text(36, 50, "ONE ENGINE, THREE HOSTS", size=12, fill=MUTED, weight=600, spacing=1.4)]
    hosts = (("mac", "Mac app", "SwiftUI, engine in-process"), ("phone", "iPhone app", "SwiftUI, on-device"),
             ("terminal", "vocello", "Terminal, JSON and MCP"))
    host_w, gap = 252.0, 26.0
    for index, (glyph, title, line) in enumerate(hosts):
        x = 36 + index * (host_w + gap)
        body.append(_box(x, 72, host_w, 74))
        body.append(icon_tile(glyph, x + 16, 87, color=GOLD, size=44))
        body.append(text(x + 74, 104, title, size=17, weight=600, family=DISPLAY))
        body.append(text(x + 74, 126, line, size=13, fill=MUTED))
        body.append(_arrow(x + host_w / 2, 146, x + host_w / 2, 178))
    body.append(_box(36, 184, width - 72, 62, stroke=GOLD, opacity=0.35))
    body.append(text(56, 211, "Engine store", size=17, weight=600, family=DISPLAY, fill=GOLD))
    body.append(text(56, 233, "One engine per process: admission, memory policy, typed cancellation", size=13,
                     fill=SECONDARY))
    body.append(_arrow(width / 2, 246, width / 2, 278))
    body.append(_box(36, 284, width - 72, 160, stroke=LAVENDER, opacity=0.4, fill=DEEP, fill_opacity=0.6))
    body.append(text(56, 314, "VocelloQwen3Engine", size=17, weight=600, family=MONO, fill=LAVENDER))
    body.append(text(width - 56, 314, "an actor on MLX and Metal", size=13, fill=MUTED, anchor="end"))
    stages = (("Talker", "script to codec frames"), ("Code predictor", "fills every frame's codebooks"),
              ("Speech decoder", "codec frames to 24 kHz audio"))
    stage_w, stage_gap = 236.0, 32.0
    for index, (title, line) in enumerate(stages):
        x = 56 + index * (stage_w + stage_gap)
        body.append(_box(x, 334, stage_w, 70, fill=RAISED, fill_opacity=0.85))
        body.append(text(x + 16, 362, title, size=16, weight=600, family=DISPLAY))
        body.append(text(x + 16, 384, line, size=13, fill=MUTED))
        if index < len(stages) - 1:
            body.append(_arrow(x + stage_w + 4, 369, x + stage_w + stage_gap - 6, 369))
    body.append(text(56, 428, "One mixed-precision model per mode: attention at 8 bits, the rest at 4", size=13,
                     fill=SECONDARY))
    body.append(_arrow(width / 2, 444, width / 2, 476))
    body.append(text(width / 2 - 14, 466, "PCM streams chunk by chunk, live preview included", size=12.5,
                     fill=MUTED, anchor="end"))
    body.append(text(width / 2 + 14, 466, "bounded, and never dropped", size=12.5, fill=MUTED))
    outputs = (("Limiter", SECONDARY), ("Atomic WAV", SECONDARY), ("AudioSeal mark", SECONDARY),
               ("Audio check", SECONDARY), ("History", TERRACOTTA))
    out_w, out_gap = 144.0, 20.0
    for index, (title, color) in enumerate(outputs):
        x = 36 + index * (out_w + out_gap)
        body.append(_box(x, 482, out_w, 50, stroke=color, opacity=0.3))
        body.append(text(x + out_w / 2, 512, title, size=14.5, weight=600, anchor="middle", fill=color
                         if color != SECONDARY else TEXT))
        if index < len(outputs) - 1:
            body.append(_arrow(x + out_w + 2, 507, x + out_w + out_gap - 4, 507))
    body.append(text(36, 570, "A take reaches History only after its WAV is written, marked and checked; a "
                     "cancelled take never does.", size=12.5, fill=MUTED))
    return svg(width, height, "How Vocello works",
               "The Mac app, the iPhone app and the vocello command line each host the same engine in-process. "
               "The engine store admits a take and owns cancellation and memory policy; the VocelloQwen3Engine actor "
               "runs the talker, the code predictor and the speech decoder on MLX and Metal; audio streams chunk by "
               "chunk to the live preview, a limiter, an atomic WAV writer with an AudioSeal watermark and an audio "
               "check, and only then to History.", body, defs)


NUMBERS = (
    ("1.7B", "parameters", "in each mode's model", GOLD),
    ("8-bit", "attention layers", "on a 4-bit model", LAVENDER),
    ("36k", "upstream lines removed", "from the owned runtime", TERRACOTTA),
    ("24 kHz", "mono audio", "from a native decoder", GOLD),
    ("Swift 6", "strict concurrency", "actors own the engine", LAVENDER),
    ("0", "lines of Python", "at runtime", TERRACOTTA),
)


def numbers(columns: int = 3) -> str:
    wide = columns == 3
    width = WIDE if wide else NARROW
    margin = 28.0 if wide else 22.0
    rows = -(-len(NUMBERS) // columns)
    cell_h = 124.0 if wide else 116.0
    height = margin * 2 + rows * cell_h
    defs, background = card(width, height, glows=((width, 0, width * 0.7, LAVENDER, 0.08),))
    body = [background]
    cell_w = (width - margin * 2) / columns
    for index, (value, line1, line2, color) in enumerate(NUMBERS):
        row, column = divmod(index, columns)
        x = margin + column * cell_w + (22 if wide else 12)
        y = margin + row * cell_h
        if column:
            body.append(f'<rect x="{num(x - (22 if wide else 12))}" y="{num(y + 20)}" width="1" '
                        f'height="{num(cell_h - 40)}" fill="{FIELD}"/>')
        if row:
            body.append(f'<rect x="{num(x)}" y="{num(y)}" width="{num(cell_w - (44 if wide else 24))}" height="1" '
                        f'fill="{FIELD}"/>')
        body.append(text(x, y + 56, value, size=38 if wide else 30, weight=700, family=DISPLAY, fill=color,
                         spacing=-0.5))
        body.append(text(x, y + 82, line1, size=14 if wide else 13, fill=TEXT, weight=600))
        body.append(text(x, y + 101, line2, size=13 if wide else 12.5, fill=MUTED))
    return svg(width, height, "Vocello by the numbers",
               "1.7 billion parameters in each mode's model; 8-bit attention layers on a 4-bit model; about 36,000 "
               "upstream lines removed from the owned runtime; 24 kHz mono audio from a native decoder; Swift 6 "
               "strict concurrency, with actors owning the engine; no Python at runtime.", body, defs)


def _button(width: float, title: str, line1: str, line2: str, glyph: str, *, primary: bool) -> str:
    fill, stroke, ink = (GOLD, GOLD_DEEP, CANVAS) if primary else (CARD, GOLD, TEXT)
    stroke_opacity = 0.55 if primary else 0.45
    glyph_color = CANVAS if primary else GOLD
    body = [f'<rect x="0.5" y="0.5" width="{num(width - 1)}" height="55" rx="27.5" fill="{fill}" stroke="{stroke}" '
            f'stroke-opacity="{num(stroke_opacity)}"/>',
            icon(glyph, 24, 16, color=glyph_color, size=24, width=2),
            text(60, 25, line1, size=16, weight=600, fill=ink),
            text(60, 42, line2, size=12, weight=500, fill=ink, opacity=0.72 if primary else 0.65)]
    return svg(width, 56, title, title, body)


def buttons(release: Release) -> dict[str, str]:
    """The three calls to action, versioned from config/public-product-facts.json."""
    mac = f"macOS {release.mac_minimum}+"
    return {
        "download-mac.svg": _button(236, f"Download Vocello {release.version} for macOS {release.mac_minimum} or newer",
                                    "Download for Mac", f"Vocello {release.version} · {mac}", "download",
                                    primary=True),
        "install-cli.svg": _button(236, f"Install the vocello {release.version} command line for macOS "
                                        f"{release.mac_minimum} or newer",
                                   "Install the CLI", f"vocello {release.version} · {mac}", "terminal",
                                   primary=False),
        "join-iphone-beta.svg": _button(236, f"Join the Vocello iPhone beta on TestFlight, iOS {release.ios_minimum} "
                                             "or newer",
                                        "Join the iPhone beta", f"TestFlight · iOS {release.ios_minimum}+", "phone",
                                        primary=False),
    }


def architecture_narrow() -> str:
    width = NARROW
    body = [text(24, 44, "ONE ENGINE, THREE HOSTS", size=11.5, fill=MUTED, weight=600, spacing=1.2)]
    hosts = (("mac", "Mac app"), ("phone", "iPhone app"), ("terminal", "vocello"))
    host_w, gap = 108.0, 14.0
    for index, (glyph, title) in enumerate(hosts):
        x = 24 + index * (host_w + gap)
        body.append(_box(x, 62, host_w, 86))
        body.append(icon_tile(glyph, x + (host_w - 38) / 2, 74, color=GOLD, size=38))
        body.append(text(x + host_w / 2, 134, title, size=14, weight=600, family=DISPLAY, anchor="middle"))
    body.append(_arrow(width / 2, 148, width / 2, 176))
    body.append(_box(24, 182, width - 48, 76, stroke=GOLD, opacity=0.35))
    body.append(text(42, 210, "Engine store", size=16, weight=600, family=DISPLAY, fill=GOLD))
    markup, _ = paragraph(42, 232, "Admission, memory policy, typed cancellation", size=13, width=width - 84,
                          leading=18)
    body.append(markup)
    body.append(_arrow(width / 2, 258, width / 2, 286))
    stages = (("Talker", "script to codec frames"), ("Code predictor", "fills each frame's codebooks"),
              ("Speech decoder", "codec frames to 24 kHz audio"))
    body.append(_box(24, 292, width - 48, 330, stroke=LAVENDER, opacity=0.4, fill=DEEP, fill_opacity=0.6))
    body.append(text(42, 322, "VocelloQwen3Engine", size=15, weight=600, family=MONO, fill=LAVENDER))
    body.append(text(42, 343, "an actor on MLX and Metal", size=13, fill=MUTED))
    for index, (title, line) in enumerate(stages):
        y = 362 + index * 78
        body.append(_box(42, y, width - 84, 62, fill=RAISED, fill_opacity=0.85))
        body.append(text(58, y + 27, title, size=15, weight=600, family=DISPLAY))
        body.append(text(58, y + 47, line, size=13, fill=MUTED))
        if index < len(stages) - 1:
            body.append(_arrow(width / 2, y + 62, width / 2, y + 76))
    body.append(text(42, 610, "8-bit attention, 4-bit everything else", size=12.5, fill=SECONDARY))
    body.append(_arrow(width / 2, 622, width / 2, 650))
    body.append(text(width / 2 + 12, 642, "PCM, chunk by chunk", size=12, fill=MUTED))
    outputs = (("Limiter", TEXT), ("Atomic WAV", TEXT), ("AudioSeal mark", TEXT), ("Audio check", TEXT),
               ("History", TERRACOTTA))
    y = 656.0
    for index, (title, color) in enumerate(outputs):
        stroke = color if color != TEXT else "#FFFFFF"
        body.append(_box(84, y, width - 168, 34, stroke=stroke, opacity=0.3 if color != TEXT else 0.08,
                         radius=17))
        body.append(text(width / 2, y + 22, title, size=14, weight=600, anchor="middle", fill=color))
        if index < len(outputs) - 1:
            body.append(_arrow(width / 2, y + 34, width / 2, y + 54))
        y += 56
    markup, end = paragraph(24, y + 6, "A cancelled take never reaches History.", size=12.5, width=width - 48,
                            leading=18, fill=MUTED)
    body.append(markup)
    height = end + 26
    defs, background = card(width, height, glows=((200, 470, 320, LAVENDER, 0.08),))
    defs += ARROW_MARKER
    return svg(width, height, "How Vocello works",
               "The Mac app, the iPhone app and the vocello command line host one engine; the VocelloQwen3Engine "
               "actor runs the talker, code predictor and speech decoder on MLX and Metal; audio streams to the "
               "preview, a limiter, a watermarked WAV and an audio check before History.", [background, *body], defs)


# The README's engineering highlights, as 40-unit tiles: (color, strokes).
HIGHLIGHT_ICONS = {
    "runtime": (GOLD, '<path d="M20 11l9 4.5-9 4.5-9-4.5z"/><path d="M11 20l9 4.5 9-4.5"/>'
                      '<path d="M11 24.5l9 4.5 9-4.5"/>'),
    "precision": (LAVENDER, '<path d="M12 14h16M12 20h16M12 26h16" stroke-opacity="0.45"/>'
                            '<circle cx="24" cy="14" r="2.4"/><circle cx="16" cy="20" r="2.4"/>'
                            '<circle cx="21" cy="26" r="2.4"/>'),
    "streaming": (TERRACOTTA, '<path d="M11 20h2M15 16v8M19 12.5v15M23 15v10M27 18v4"/>'),
    "launches": (GOLD, '<path d="M21.5 10.5L14 21.5h6l-1.5 8 7.5-11h-6z"/>'),
    "reproducible": (LAVENDER, '<path d="M27 16.5A8 8 0 0 0 13.5 15"/><path d="M13 11.5v3.5h3.5"/>'
                               '<path d="M13 23.5A8 8 0 0 0 26.5 25"/><path d="M27 28.5V25h-3.5"/>'),
    "proof": (TERRACOTTA, '<path d="M20 10.5l7.5 3v6c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5v-6z"/>'
                          '<path d="M16.5 20l2.5 2.5 4.5-5"/>'),
}


def highlight_icon(name: str) -> str:
    color, strokes = HIGHLIGHT_ICONS[name]
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">\n'
            f'<rect width="40" height="40" rx="11" fill="{CARD}"/>\n'
            f'<rect x="0.5" y="0.5" width="39" height="39" rx="10.5" fill="none" stroke="{color}" stroke-opacity="0.35"/>\n'
            f'<g fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{strokes}</g>\n</svg>\n')


def render(root: Path, measured: Measured, release: Release) -> dict[str, str]:
    """Every branded README image but the speed chart, by path under docs/readme/."""
    images = {
        "hero.svg": hero(root),
        "hero-narrow.svg": hero_narrow(root),
        "modes.svg": modes(),
        "modes-narrow.svg": modes_narrow(),
        "features.svg": features(4),
        "features-narrow.svg": features(2),
        "performance.svg": performance(measured),
        "performance-narrow.svg": performance(measured, narrow=True),
        "architecture.svg": architecture(),
        "architecture-narrow.svg": architecture_narrow(),
        "numbers.svg": numbers(3),
        "numbers-narrow.svg": numbers(2),
    }
    images.update(buttons(release))
    images.update({f"icons/{name}.svg": highlight_icon(name) for name in HIGHLIGHT_ICONS})
    return images
