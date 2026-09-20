"""
No component names a colour. It names the job the colour does.

`globals.css` states the rule in its own header -- "a literal colour value
inside a component is a bug" -- and nothing enforced it. The sibling test in
this directory validates the TOKEN VALUES, which is a different question: it
proves the palettes are legible, not that anybody uses them.

So four hundred and forty-eight literal palette classes accumulated, almost
all of them in the Cockpit V4 surface, which had been built as a
self-contained slice with its own markdown renderer, its own charts and its
own tables written in `slate` / `sky` / `amber`. Switching to a dark theme
repainted the canvas to #0a0f16 and left every one of those at its light
value. The answer paragraph was #334155 on #111823. The first chart series
was #0f172a -- near-black, on near-black. There was a `fill="#ffffff"` punched
through the middle of a donut.

None of that is subtle, and none of it was caught, because the only thing
looking at colour was looking at the other end of the pipe.

This test looks at components. A literal here fails the build.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"

#: The surfaces this rule is enforced on today.
#:
#: Deliberately not the whole tree yet. The rest of the product has its own
#: literals -- a page here, an icon there -- and a test that fails for three
#: hundred unrelated reasons is a test somebody switches off. These are the
#: files a reader looks at while reading an answer, which is where an
#: unreadable theme actually costs something, and the set can widen from here.
WATCHED: tuple[str, ...] = (
    "components/cockpit-v4",
    "components/analytics",
    "components/collaboration",
    "components/exports",
)

#: Tailwind's built-in palettes. A component naming one of these has chosen a
#: colour rather than a role, and has therefore chosen it for exactly one
#: theme.
FAMILIES = (
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    "emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)

#: Every utility that takes a colour.
PROPERTIES = (
    "text|bg|border|fill|stroke|ring|ring-offset|divide|outline|decoration|"
    "accent|caret|shadow|from|via|to|placeholder"
)

#: `bg-slate-50`, `marker:text-slate-400`, `hover:border-sky-300`,
#: `dark:text-emerald-400` -- prefixes and all.
PALETTE_CLASS = re.compile(
    rf"(?<![\w-])(?:[a-z-]+:)*(?:{PROPERTIES})-(?:{FAMILIES})-\d{{2,3}}(?![\w-])"
)

#: `text-white`, `bg-black/25`. Black and white are not roles either: the
#: inverse of the text colour is `text-text-inverse`, and a scrim is a
#: token with an alpha.
ABSOLUTE_CLASS = re.compile(
    rf"(?<![\w-])(?:[a-z-]+:)*(?:{PROPERTIES})-(?:white|black)(?:/\d{{1,3}})?(?![\w-])"
)

#: `#0f172a`, `#fff`. Caught anywhere in the file, including inside an SVG
#: `fill=` and a `style={{ }}`, which is where the worst of them were.
HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])")

#: `rgba(15, 23, 42, 0.4)`.
RGB = re.compile(r"\brgba?\(")

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a Tailwind palette class", PALETTE_CLASS),
    ("a literal black or white", ABSOLUTE_CLASS),
    ("a hex colour", HEX),
    ("an rgb()/rgba() colour", RGB),
)

#: A line ending in this comment is exempt, and has to say why in the same
#: breath. An exemption nobody has to justify is a hole.
ALLOW = "colour-literal-ok:"


def watched_files() -> list[Path]:
    found: list[Path] = []
    for area in WATCHED:
        base = ROOT / area
        if not base.exists():  # pragma: no cover - a moved directory
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix in {".tsx", ".ts"} and "__tests__" not in path.parts:
                found.append(path)
    return found


def offences(path: Path) -> list[str]:
    out: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ALLOW in line:
            continue
        for what, pattern in RULES:
            for hit in pattern.findall(line):
                out.append(f"{path.relative_to(ROOT)}:{number}  {what}: {hit}")
    return out


def test_the_watched_surfaces_name_no_colour() -> None:
    files = watched_files()
    assert files, f"nothing to scan under {WATCHED} -- has the tree moved?"

    found = [line for path in files for line in offences(path)]
    assert not found, (
        f"{len(found)} colour literal(s) in components that must follow the "
        f"theme.\n\nUse a token: bg-surface / bg-surface-raised / "
        f"bg-surface-sunken, text-text-primary / -secondary / -muted / "
        f"-inverse, border-border / border-border-strong, text-accent, "
        f"text-positive / -warning / -negative / -info, and "
        f"var(--ipm-chart-1..8) for a series.\n\n"
        + "\n".join(found[:60])
        + (f"\n… and {len(found) - 60} more" if len(found) > 60 else "")
    )


@pytest.mark.parametrize(
    "sample",
    [
        'className="bg-slate-50"',
        'className="marker:text-slate-400"',
        'className="dark:text-emerald-400"',
        'className="hover:border-sky-300"',
        'className="text-white"',
        'className="bg-black/25"',
        'fill="#ffffff"',
        'backgroundColor: `rgba(15, 23, 42, 0.4)`',
    ],
)
def test_the_scanner_catches_what_it_is_for(sample: str) -> None:
    """The scanner is the whole guard, so it is itself checked against the
    exact shapes that were found in the wild."""
    assert any(pattern.search(sample) for _, pattern in RULES), sample


@pytest.mark.parametrize(
    "sample",
    [
        'className="bg-surface text-text-primary"',
        'className="border-border-strong text-text-muted"',
        'fill="var(--ipm-chart-1)"',
        'className="text-negative"',
        'className="grid-cols-2 gap-4 rounded-md px-2 py-1.5"',
        'const TOP_N = 10;',
        'className="text-[0.85em]"',
    ],
)
def test_the_scanner_passes_correct_code(sample: str) -> None:
    """And against the token forms it must never flag -- a guard with false
    positives gets an exemption comment rather than a fix."""
    assert not any(pattern.search(sample) for _, pattern in RULES), sample
