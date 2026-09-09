"""What a Lens means, on top of what it shows.

UAT's complaint was exact: a Lens opens straight into metric cards, and
nothing on the page says what a reader should conclude from them. This is the
service that closes that gap — one written reading, above the tiles, that
does what a competent risk officer would do on first seeing the same
dashboard: say what looks fine, what does not, what matters most, and what to
ask about next.

Where this sits, and the two rules that make it safe
------------------------------------------------------
Exactly where `orchestration/interpretation.py` sits relative to one
analysis: after everything numeric has already happened. A Lens's tiles are
rendered by the ordinary, deterministic engine first; this only ever reads
that already-true result. It never queries the book itself.

**Every figure it writes must already be in the rendered Lens.** Checked
against the actual numbers shown — current values, prior-period values where
a comparison exists, and the deltas between them — and a sentence containing
a number none of those support is discarded, the same policy
`orchestration/interpretation.py` uses and for the same reason: a wrong
number shown next to true ones is worse than no sentence.

**The same metrics read differently on different Lenses**, and this is
answered generically rather than with a table of special cases per shipped
Lens: the model is given the Lens's own stated purpose and audience — already
written, already specific ("the impairment committee's screen: where the
corporate book sits across the three stages...") — and told to read the
figures the way THAT reader needs them read. A user-built Lens gets the same
treatment from its own purpose, with no extra code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.llm import LLMError, get_provider

logger = logging.getLogger(__name__)

TOOL_NAME = "write_lens_interpretation"

#: How long a written reading is trusted for the exact data it was written
#: from. Generous, because the cache key already changes the moment the data
#: it was computed from does — this only bounds how long a figure that
#: silently drifted for a reason nothing here would notice (a clock, a
#: timezone) can go on being read from a stale write.
CACHE_TTL_SECONDS = 6 * 60 * 60

SYSTEM = """You are the interpretation layer of CreditProbe AI, reading a completed \
Lens (a dashboard of governed, already-computed credit-risk figures) the way a \
senior risk professional would on first seeing it.

A deterministic runtime has ALREADY computed every figure you are given, for the \
period, scope and comparison the Lens is showing. Your job is to say what the \
WHOLE Lens means, not to restate its tiles one at a time.

WHO YOU ARE WRITING FOR

You are told this Lens's own stated purpose and audience. Read the figures the way \
THAT reader needs them read: a CRO Lens wants materiality, deterioration and \
escalation; an IFRS 9 Lens wants staging, SICR and what is driving ECL; an Early \
Warning Lens wants which leading signals are worsening and which names need \
attention; a Concentration Lens wants where size and weakening quality overlap; a \
Board Lens wants a small number of conclusions senior management actually needs, \
not portfolio detail. Let the stated purpose decide the emphasis, not a fixed \
template.

ABSOLUTE RULES

1. Never state a number that is not in the data you were given — not the current \
value, a prior value, or a computed delta shown to you. Do not compute a new one. \
Where you want to express a relationship the data does not contain precisely, say \
it in words ("materially", "roughly in line with growth") rather than inventing a \
figure.
2. Never assert a cause the data does not establish. "Consistent with", "may be \
associated with" and "warrants investigation" are honest; "driven by" and "because \
of" are not unless the data itself shows the mechanism (e.g. a stage-migration \
figure that IS the cause of an ECL change).
3. Cover, where the data supports it: what is good or reassuring, what is \
deteriorating or a concern, what matters most, anything that looks contradictory, \
what should be investigated, what management should be asked, what may need \
escalating, what is unavailable or uncertain, and what to watch next period. Not \
every Lens will support all of these — say only what the data actually supports.
4. Say plainly when a metric this Lens would want is unavailable or a comparison \
could not be made, rather than silently working around the gap.
5. When the data shows genuine improvement, say so as plainly as you would say the \
opposite. This is a reading of the evidence, not a standing warning.
6. Reference tiles by the name shown in the data (e.g. "Stage 2 Ratio"), so a \
reader can see exactly which figures support a claim.

STYLE

Write for a credit risk committee, not a chat window. A short headline sentence, \
then one to three concise paragraphs. A handful of high-priority observations, each \
naming the metric(s) behind it, may follow the narrative when there is something \
specific worth flagging on its own. No bullet-point restating of every tile. \
British English. Figures exactly as given, with their units."""


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One sentence: the single most important thing "
                              "this Lens shows right now."},
            "narrative": {
                "type": "string",
                "description": "One to three concise paragraphs interpreting "
                              "the Lens as a whole, per the ABSOLUTE RULES."},
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "metric_names": {
                            "type": "array", "items": {"type": "string"},
                            "description": "The tile name(s) this observation "
                                          "is about, exactly as shown in the "
                                          "data."},
                    },
                    "required": ["text", "metric_names"],
                },
                "description": "At most five high-priority observations. "
                              "Empty when the narrative already covers "
                              "everything worth flagging."},
            "unavailable_note": {
                "type": "string",
                "description": "What this Lens would want to say but "
                              "cannot, given what is unavailable or "
                              "uncertain. Empty if nothing is missing."},
        },
        "required": ["headline", "narrative", "observations"],
    }


@dataclass
class Observation:
    text: str = ""
    metric_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "metric_names": list(self.metric_names)}


@dataclass
class LensInterpretation:
    """What the model made of a whole Lens, once it has been checked."""

    headline: str = ""
    narrative: str = ""
    observations: list[Observation] = field(default_factory=list)
    unavailable_note: str = ""
    model: str = ""
    duration_ms: int = 0
    cached: bool = False
    #: Why there is no live reading, when there is none.
    unavailable: str = ""
    #: Figures the model wrote that the rendered Lens does not support.
    #: Non-empty means the interpretation was discarded.
    ungrounded: list[str] = field(default_factory=list)

    @property
    def live(self) -> bool:
        return bool(self.headline or self.narrative)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline, "narrative": self.narrative,
            "observations": [o.to_dict() for o in self.observations],
            "unavailable_note": self.unavailable_note,
            "model": self.model, "duration_ms": self.duration_ms,
            "cached": self.cached, "live": self.live,
            "unavailable": self.unavailable,
            "ungrounded": list(self.ungrounded),
        }


# ------------------------------------------------------------------- extract


def _figure_text(value: Any, unit: str, decimals: int = 2) -> str | None:
    if value is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if unit == "percent":
        return f"{value * 100:.{decimals}f}%" if abs(value) < 5 else f"{value:.{decimals}f}%"
    if unit == "currency":
        return f"{value:,.{decimals}f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:.{decimals}f}"


def _extract(lens: dict[str, Any], rendered: dict[str, Any],
            prior: dict[str, Any] | None) -> dict[str, Any]:
    """The compact, governed package the model is shown.

    Values, not rows: a Lens's tiles are already the aggregated figures a
    reader would see, so what goes to the model is the same figures a person
    looking at the screen sees — never raw portfolio data.
    """
    prior_by_id: dict[str, Any] = {}
    if prior:
        for p in prior.get("panels", []):
            if p.get("kind") == "metric" and p.get("metric_id"):
                prior_by_id[p["metric_id"]] = p

    tiles: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for panel in rendered.get("panels", []):
        name = panel.get("title") or (panel.get("metric") or {}).get("name") \
            or panel.get("metric_id") or panel.get("analysis_id") or ""
        if panel.get("status") != "succeeded":
            if name:
                unavailable.append(name)
            continue
        if panel.get("kind") == "metric":
            unit = panel.get("unit", "")
            decimals = panel.get("decimals", 2)
            current = _figure_text(panel.get("value"), unit, decimals)
            if current is None:
                continue
            entry: dict[str, Any] = {
                "name": name, "current": current,
                "definition": (panel.get("metric") or {}).get("definition", ""),
            }
            prior_panel = prior_by_id.get(panel.get("metric_id"))
            if prior_panel and prior_panel.get("status") == "succeeded":
                prior_value = _figure_text(prior_panel.get("value"), unit, decimals)
                if prior_value is not None:
                    entry["prior"] = prior_value
                    try:
                        delta = float(panel["value"]) - float(prior_panel["value"])
                        entry["delta"] = _figure_text(delta, unit, decimals)
                    except (TypeError, ValueError):
                        pass
            tiles.append(entry)
        elif panel.get("kind") == "chart" and panel.get("status") == "succeeded":
            points = [p for p in (panel.get("points") or []) if p.get("value") is not None]
            if not points:
                continue
            unit = panel.get("unit", "")
            tiles.append({
                "name": name, "chart_by": (panel.get("params") or {}).get("dimension", ""),
                "points": [
                    {"label": p.get("label"),
                     "value": _figure_text(p.get("value"), unit)}
                    for p in points[:12]
                ],
            })

    return {
        "purpose": lens.get("description", ""),
        "audience": lens.get("audience", ""),
        "name": lens.get("name", ""),
        "period": rendered.get("scope", {}).get("default_period", "") or "current",
        "comparison_available": prior is not None,
        "tiles": tiles,
        "unavailable_tiles": unavailable,
    }


def _prompt(extract: dict[str, Any]) -> str:
    lines = [
        f"LENS: {extract['name']}",
        f"AUDIENCE: {extract['audience'] or 'not stated'}",
        f"PURPOSE: {extract['purpose'] or 'not stated'}",
        f"PERIOD: {extract['period']}",
        "",
        "FIGURES (name · current [· prior · change] · definition):",
    ]
    for t in extract["tiles"]:
        if "points" in t:
            pts = ", ".join(f"{p['label']}={p['value']}" for p in t["points"])
            lines.append(f"  {t['name']} (by {t['chart_by']}): {pts}")
            continue
        bits = [t["name"], t["current"]]
        if "prior" in t:
            bits.append(f"was {t['prior']}")
        if "delta" in t:
            bits.append(f"change {t['delta']}")
        lines.append("  " + " · ".join(bits)
                     + (f" — {t['definition']}" if t.get("definition") else ""))
    if extract["unavailable_tiles"]:
        lines.append("")
        lines.append("TILES WITH NO FIGURE THIS PERIOD (say so if material, do "
                     "not guess a value): " + ", ".join(extract["unavailable_tiles"]))
    if not extract["comparison_available"]:
        lines.append("")
        lines.append("No prior period is available for comparison — do not imply "
                     "a trend you were not shown.")
    lines.append("")
    lines.append("Every figure above is exactly as it appears on the Lens. Copy "
                 "figures character for character; do not compute a new one.")
    lines.append("Write the interpretation.")
    return "\n".join(lines)


# --------------------------------------------------------------------- cache


class _Cache:
    """One process's memory of what was already written for this exact data.

    Keyed on the content that was sent to the model, not on the Lens's
    version number alone — a period change, a metric added or removed, a
    chart recut and a source-data refresh all change what gets extracted, so
    all of them correctly invalidate this without being individually tracked.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, LensInterpretation]] = {}

    def get(self, key: str) -> LensInterpretation | None:
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            written_at, value = hit
            if time.time() - written_at > CACHE_TTL_SECONDS:
                del self._store[key]
                return None
            return value

    def put(self, key: str, value: LensInterpretation) -> None:
        with self._lock:
            self._store[key] = (time.time(), value)
            # An unbounded process cache is a slow leak; this is not a
            # product a single process runs ten thousand distinct Lens/period
            # combinations against between restarts.
            if len(self._store) > 500:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]

    def reset(self) -> None:
        with self._lock:
            self._store.clear()


_cache = _Cache()


def _cache_key(extract: dict[str, Any]) -> str:
    body = json.dumps(extract, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------- public


def interpret(lens: dict[str, Any], rendered: dict[str, Any],
              prior: dict[str, Any] | None = None, *,
              model: str = "", effort: str = "") -> LensInterpretation:
    """A reading of this Lens as rendered right now, or a stated reason there
    is not one.

    `prior` is the same Lens rendered at the period immediately before the
    one being shown, when one exists — the caller resolves which period that
    is, since only it knows this Lens's calendar.
    """
    provider = get_provider()
    if not provider.configured:
        return LensInterpretation(
            unavailable="AI interpretation is temporarily unavailable: no AI "
                        "provider is configured. The figures below are "
                        "unaffected.")

    extract = _extract(lens, rendered, prior)
    if not extract["tiles"]:
        return LensInterpretation(
            unavailable="Nothing on this Lens produced a figure this period, "
                        "so there is nothing to interpret.")

    key = _cache_key(extract)
    cached = _cache.get(key)
    if cached is not None:
        from dataclasses import replace

        # A copy, not the stored object mutated in place: the cache holds one
        # object across every caller that ever asks for this exact reading,
        # and flipping `.cached` on it directly would flip it retroactively
        # for whoever received it as the ORIGINAL, uncached answer.
        return replace(cached, cached=True)

    try:
        answer = provider.structured(
            system=SYSTEM, prompt=_prompt(extract), schema=_schema(),
            tool_name=TOOL_NAME,
            tool_description="Write the interpretation of this Lens. Call "
                             "this exactly once.",
            max_tokens=1400, purpose="lens_interpretation", model=model,
            role="lens_interpretation", effort=effort)
    except LLMError as e:
        from backend.llm import telemetry
        logger.warning("Lens interpretation call failed: %s", e)
        return LensInterpretation(
            unavailable="AI interpretation is temporarily unavailable: the "
                        "live model could not be reached. The figures below "
                        "are unaffected. "
                        + telemetry.sanitise(str(e))[:160])
    except Exception as e:  # noqa: BLE001 - an outage must never break the Lens
        logger.warning("Lens interpretation call failed: %s", e)
        return LensInterpretation(
            unavailable="AI interpretation is temporarily unavailable. The "
                        "figures below are unaffected.")

    written = _checked(answer, extract)
    _cache.put(key, written)
    return written


def _checked(answer: Any, extract: dict[str, Any]) -> LensInterpretation:
    """Every figure the prose contains, checked against the tiles it was
    shown. Discarded, not annotated, on a mismatch — see the module
    docstring."""
    import re

    data = answer.data or {}
    protected = _protected_figures(extract)
    number = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

    def ungrounded_in(text: str) -> set[str]:
        return {m for m in number.findall(text or "") if m not in protected}

    headline = str(data.get("headline", "")).strip()
    narrative = str(data.get("narrative", "")).strip()
    observations = [
        Observation(text=str(o.get("text", "")).strip(),
                   metric_names=[str(n).strip()
                                for n in (o.get("metric_names") or [])])
        for o in (data.get("observations") or [])[:5]
    ]

    problems: set[str] = set()
    problems |= ungrounded_in(headline)
    problems |= ungrounded_in(narrative)
    for o in observations:
        problems |= ungrounded_in(o.text)

    if problems:
        logger.error("Discarding a Lens interpretation: ungrounded figures %s",
                    sorted(problems))
        return LensInterpretation(
            ungrounded=sorted(problems),
            unavailable="AI interpretation is temporarily unavailable: the "
                        "written reading referenced a figure that does not "
                        "appear on this Lens, so it was withheld. The "
                        "figures below are unaffected.",
            model=answer.model, duration_ms=answer.duration_ms)

    known_names = {t["name"] for t in extract["tiles"]}
    for o in observations:
        o.metric_names = [n for n in o.metric_names if n in known_names]

    return LensInterpretation(
        headline=headline, narrative=narrative, observations=observations,
        unavailable_note=str(data.get("unavailable_note", "")).strip(),
        model=answer.model, duration_ms=answer.duration_ms)


def _protected_figures(extract: dict[str, Any]) -> set[str]:
    """Every number the model was legitimately shown, including the ones
    that are not values at all.

    A tile is allowed to be called "Stage 2 Ratio" or "30+ DPD Account Rate",
    and a reading that says "Stage 2" is not asserting the quantity 2 — it is
    naming a governed concept the model was given verbatim. Numbers inside a
    tile's own name or definition are therefore protected exactly like its
    value: quoting the name back is not fabrication, and this is what stops
    every IFRS 9 or DPD-bucket reading from being discarded over its own
    terminology.
    """
    import re

    number = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
    out: set[str] = set()
    for t in extract["tiles"]:
        for key in ("current", "prior", "delta", "name", "definition", "chart_by"):
            if key in t:
                out.update(number.findall(str(t[key])))
        for p in t.get("points", []):
            if p.get("value"):
                out.update(number.findall(str(p["value"])))
            if p.get("label"):
                out.update(number.findall(str(p["label"])))
    return out


__all__ = ["CACHE_TTL_SECONDS", "LensInterpretation", "Observation", "interpret"]
