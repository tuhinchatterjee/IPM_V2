"""A Lens built from what somebody is trying to monitor, not from keywords.

UAT's complaint about the builder was precise: "include all metrics which you
feel are relevant" is a sentence a keyword matcher cannot answer, because
there is no keyword for "relevant." Answering it needs the same judgement a
senior credit-risk analyst brings to the same request — what does a book like
this one actually need watched, given what it is and what somebody suspects
is wrong with it.

Where this sits
----------------
Domain resolution is untouched: `builder.interpret()` already does that
well, deterministically, and is fully tested — this module calls it rather
than duplicating it. What this module adds is the step after: given the
domains and the governed catalogue, which metrics and charts actually answer
the request, organised the way a dashboard should be, with a stated reason
for each and an explicit, truthful account of anything asked for that this
deployment cannot compute.

The two rules that make this safe
----------------------------------
**The model never invents a metric.** It is shown the governed catalogue's
own ids and picks among them; anything it returns that is not one of those
ids is treated exactly like a metric it never should have been able to name
and moved to `unsupported`, not silently kept.

**No provider, no different a Lens.** `plan()` degrades to the existing
deterministic domain/metric matching when no model is configured — the same
few best-matching metrics `interpret()` already finds — so a deployment with
no key still gets a working, honest builder rather than a blocked one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.llm import LLMError, get_provider

logger = logging.getLogger(__name__)

TOOL_NAME = "propose_lens"

#: The sections a Lens is organised into. Fixed, rather than left to the
#: model to name freely, so every plan reads the same way and the frontend
#: can render one layout rather than guessing at arbitrary headings.
SECTIONS = ("headline", "trend", "quality", "concentration", "early_warning",
           "other")

SECTION_LABEL = {
    "headline": "Headline",
    "trend": "Trend",
    "quality": "Quality",
    "concentration": "Concentration",
    "early_warning": "Early Warning",
    "other": "Other",
}

#: How many metrics one plan may propose in total. A request that resolves to
#: sixty tiles is not a dashboard, and the prompt is told to use judgement
#: well below this — this is the hard ceiling behind that judgement, not the
#: target.
MAX_METRICS = 28
MAX_CHARTS = 14

SYSTEM = """You are a senior credit-risk analyst inside CreditProbe, designing a \
monitoring Lens (a dashboard) for another risk professional from a plain-language \
request.

You are given the FULL governed metric catalogue available to this request: every \
metric's id, name, domain, unit and definition. This is the complete set of things \
that can be measured. Nothing else exists.

YOUR JOB

Read the request the way a senior risk officer would: what is this person actually \
trying to monitor, and what would a competent professional put in front of them to \
answer it -- not which words in their sentence match a metric name.

Reason explicitly, in order, before you answer:
1. What is the PURPOSE -- what does this Lens need to let someone conclude?
2. What is the SCOPE -- which domain(s), portfolio, and any named sub-population \
(a sector, a rating band, a size threshold)?
3. What RISK QUESTIONS does answering that purpose require? ("Is quality \
deteriorating faster than the book is growing?", "Where is the exposure \
concentrated?", "Is this a rating problem or a cash-flow problem?")
4. For each risk question, which metrics IN THE CATALOGUE GIVEN TO YOU actually \
answer it, and would a senior risk officer expect to see it move over time \
(propose it as a trend) or only as a current figure (propose it as a headline KPI)?

ABSOLUTE RULES

1. Use ONLY metric ids from the catalogue you were given. Never write an id that is \
not in that list, under any circumstance -- if nothing in the catalogue answers a \
risk question, that question goes in `unsupported` with a plain reason, and the \
Lens is built from what the catalogue DOES support. A partially-answered request is \
correct; a fabricated metric is not.
2. Do not add a metric because a word in the request matches its name. Add it \
because a senior risk officer would actually want it to answer the purpose you \
identified. Fewer, well-reasoned metrics beat an exhaustive keyword sweep.
3. When the request names something specific you cannot find in the catalogue \
(a named metric, a scenario, a dimension), say so explicitly in `unsupported` with \
the reason -- do not silently omit it and do not approximate it with an unrelated \
metric.
4. Prefer TRENDS over snapshots when the purpose is about deterioration, growth, or \
change -- that is usually the actual question, and a chart over a KPI answers it. \
Charts must use a dimension the catalogue lists for that metric; propose the metric \
as a KPI instead if you are not sure a dimension applies.
5. Match the SIZE of the Lens to the audience. A board-level or CRO request wants a \
small number of highly material views, not forty tiles. A deep monitoring or \
deterioration request can carry more. Say so in `rationale` if you deliberately kept \
it small.
6. Organise every metric into exactly one section: `headline` (the current position, \
as KPIs), `trend` (how it is moving over time), `quality` (staging, ratings, \
watchlist, covenants -- credit quality composition), `concentration` (obligor, \
sector, region concentration), `early_warning` (leading/EWS signals), or `other`.
7. If the request is genuinely ambiguous in a way that changes what should be built \
(not merely under-specified -- "the corporate book" without saying which question \
about it matters, when nothing else in the sentence answers that) say so as one \
short question in `clarify`. Otherwise leave `clarify` empty and build the best Lens \
you can from what was said -- an unnecessary clarifying question is a worse answer \
than a good-faith Lens.

Write `rationale` as the explanation a risk officer would want: why these metrics, \
together, answer what was asked."""


def _schema(metric_ids: list[str]) -> dict[str, Any]:
    metric_enum = {"type": "string", "enum": metric_ids} if metric_ids else {
        "type": "string"}
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string",
                      "description": "A short, specific name for this Lens."},
            "purpose": {
                "type": "string",
                "description": "One or two sentences: what this Lens lets someone "
                              "conclude."},
            "scope_summary": {
                "type": "string",
                "description": "The domain, portfolio and any named "
                              "sub-population, in one short phrase, e.g. "
                              "\"Corporate book, contracting sector\"."},
            "risk_questions": {
                "type": "array", "items": {"type": "string"},
                "description": "The specific questions this Lens answers."},
            "metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric_id": metric_enum,
                        "section": {"type": "string", "enum": list(SECTIONS)},
                        "why": {"type": "string",
                               "description": "One sentence: why a senior risk "
                                             "officer would want this here."},
                        "as_chart": {
                            "type": "boolean",
                            "description": "True to show this as a trend/"
                                          "breakdown chart rather than a "
                                          "single current-period KPI."},
                        "dimension": {
                            "type": "string",
                            "description": "Required when as_chart is true: "
                                          "the field to cut it by, e.g. "
                                          "\"period\" for a trend over time, "
                                          "\"sector\", \"region\", "
                                          "\"rating_bucket\". Leave empty "
                                          "when as_chart is false."},
                    },
                    "required": ["metric_id", "section", "why", "as_chart"],
                },
            },
            "unsupported": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requested": {"type": "string"},
                        "because": {"type": "string"},
                    },
                    "required": ["requested", "because"],
                },
                "description": "Anything the request named or implied that the "
                              "given catalogue cannot answer.",
            },
            "rationale": {
                "type": "string",
                "description": "Why this set of metrics, together, answers the "
                              "purpose -- written for the risk officer reading "
                              "the proposal, not for a changelog."},
            "clarify": {
                "type": "string",
                "description": "One short question, ONLY if the request is "
                              "genuinely ambiguous in a way that changes what "
                              "should be built. Empty otherwise."},
        },
        "required": ["title", "purpose", "scope_summary", "risk_questions",
                    "metrics", "unsupported", "rationale"],
    }


@dataclass
class PlannedMetric:
    metric_id: str
    name: str = ""
    unit: str = ""
    domain: str = ""
    section: str = "other"
    why: str = ""
    as_chart: bool = False
    dimension: str = ""
    dimension_label: str = ""
    visual: str = "kpi"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id, "name": self.name, "unit": self.unit,
            "domain": self.domain, "section": self.section,
            "section_label": SECTION_LABEL.get(self.section, "Other"),
            "why": self.why, "as_chart": self.as_chart,
            "dimension": self.dimension, "dimension_label": self.dimension_label,
            "visual": self.visual,
        }


@dataclass
class LensPlan:
    """A proposed Lens: what it is for, what answers that, and what does not."""

    title: str = ""
    purpose: str = ""
    scope_summary: str = ""
    domains: list[dict[str, Any]] = field(default_factory=list)
    portfolios: list[str] = field(default_factory=list)
    risk_questions: list[str] = field(default_factory=list)
    metrics: list[PlannedMetric] = field(default_factory=list)
    unsupported: list[dict[str, str]] = field(default_factory=list)
    rationale: str = ""
    clarify: str = ""
    period: str = ""
    #: True when a live model actually reasoned about this plan. False means
    #: the deterministic keyword fallback ran instead -- still honest, still
    #: usable, just not the richer reasoning.
    understood: bool = False
    #: Why there is no live plan, when there is none.
    unavailable: str = ""
    model: str = ""

    def sections(self) -> dict[str, list[PlannedMetric]]:
        out: dict[str, list[PlannedMetric]] = {s: [] for s in SECTIONS}
        for m in self.metrics:
            out.setdefault(m.section, []).append(m)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "purpose": self.purpose,
            "scope_summary": self.scope_summary,
            "domains": list(self.domains), "portfolios": list(self.portfolios),
            "risk_questions": list(self.risk_questions),
            "metrics": [m.to_dict() for m in self.metrics],
            "sections": {SECTION_LABEL[s]: [m.to_dict() for m in ms]
                        for s, ms in self.sections().items() if ms},
            "unsupported": list(self.unsupported),
            "rationale": self.rationale, "clarify": self.clarify,
            "period": self.period, "understood": self.understood,
            "unavailable": self.unavailable, "model": self.model,
        }


def _catalogue_context(pool: list[Any]) -> list[dict[str, str]]:
    return [
        {"id": m.metric_id, "name": m.name, "domain": m.domain,
         "unit": m.unit, "definition": (m.definition or "")[:180]}
        for m in pool
    ]


def _prompt(request: str, domains: list[str], catalogue: list[dict[str, str]]) -> str:
    import json

    lines = [f"REQUEST: {request}", ""]
    if domains:
        lines.append("DOMAINS ALREADY RESOLVED FOR THIS REQUEST: "
                     + ", ".join(domains))
        lines.append("")
    lines.append(f"GOVERNED CATALOGUE ({len(catalogue)} metrics available):")
    lines.append(json.dumps(catalogue, default=str))
    lines.append("")
    lines.append("Propose the Lens.")
    return "\n".join(lines)


def plan(request: str, *, user_id: int | None = None,
         readable: Any = None, model: str = "", effort: str = "") -> LensPlan:
    """A Lens plan for a broad, natural-language request.

    Domains are resolved first, deterministically, by the same interpreter the
    rest of the builder uses. What differs is everything after: given those
    domains and the governed catalogue, an LLM reasons about which metrics
    actually answer the request, the way a senior risk officer would --
    falling back to the existing keyword matcher when no model is configured,
    so a deployment with no key still gets a working builder.
    """
    from backend.metrics import builder, service

    intent = builder.interpret(request, user_id=user_id, readable=readable)
    domains = [d.name for d in intent.domains if d.chosen] or \
        [d.name for d in intent.domains[:1]]
    portfolios = list(intent.portfolios)

    pool = service.catalogue(user_id=user_id, readable=readable)
    by_id = {m.metric_id: m for m in pool}

    provider = get_provider()
    if not provider.configured:
        return _fallback(request, intent, domains, portfolios, by_id,
                         reason="No AI provider is configured, so this Lens was "
                                "built from the governed catalogue's own keyword "
                                "matcher rather than a full reading of the "
                                "request.")

    catalogue_ctx = _catalogue_context(pool)
    try:
        answer = provider.structured(
            system=SYSTEM,
            prompt=_prompt(request, domains, catalogue_ctx),
            schema=_schema([c["id"] for c in catalogue_ctx]),
            tool_name=TOOL_NAME,
            tool_description="Propose a Lens for this request. Call this "
                             "exactly once.",
            max_tokens=3000, purpose="lens_planning", model=model,
            role="lens_planning", effort=effort)
    except LLMError as e:
        from backend.llm import telemetry
        logger.warning("Lens planning call failed: %s", e)
        return _fallback(request, intent, domains, portfolios, by_id,
                         reason="The live model could not be reached for this "
                                "Lens proposal, so it was built from the "
                                "governed catalogue's own keyword matcher "
                                "instead. " + telemetry.sanitise(str(e))[:160])
    except Exception as e:  # noqa: BLE001 - an outage must never block the builder
        logger.warning("Lens planning call failed: %s", e)
        return _fallback(request, intent, domains, portfolios, by_id,
                         reason="The live model could not be reached for this "
                                "Lens proposal, so it was built from the "
                                "governed catalogue's own keyword matcher "
                                "instead.")

    return _validated(answer, by_id, domains, portfolios, intent)


def _validated(answer: Any, by_id: dict[str, Any], domains: list[str],
              portfolios: list[str], intent: Any) -> LensPlan:
    """Everything the model proposed, checked against the real catalogue.

    Not trust-but-verify -- verify, full stop. A metric id that is not in
    `by_id` did not come from the catalogue the model was shown, whatever the
    model's own schema promised, and is moved to `unsupported` rather than
    kept: the one rule this whole feature cannot compromise on is that
    nothing on a Lens names a metric that does not exist.
    """
    from backend.metrics import service

    data = answer.data or {}
    unsupported: list[dict[str, str]] = [
        {"requested": str(u.get("requested", "")).strip(),
         "because": str(u.get("because", "")).strip()}
        for u in (data.get("unsupported") or [])
        if str(u.get("requested", "")).strip()
    ]

    metrics: list[PlannedMetric] = []
    seen: set[tuple[str, str]] = set()
    for item in (data.get("metrics") or [])[:MAX_METRICS + MAX_CHARTS]:
        metric_id = str(item.get("metric_id", "")).strip()
        metric = by_id.get(metric_id)
        if metric is None:
            unsupported.append({
                "requested": item.get("why", metric_id) or metric_id,
                "because": f"'{metric_id}' is not a metric in the governed "
                          "catalogue, so it was not added.",
            })
            continue
        section = str(item.get("section", "other")).strip().lower()
        if section not in SECTIONS:
            section = "other"
        as_chart = bool(item.get("as_chart"))
        dimension = str(item.get("dimension", "")).strip()
        dimension_label = ""
        if as_chart and dimension:
            available = {d["name"]: d for d in service.dimension_fields(metric)}
            chosen = available.get(dimension)
            if chosen is None:
                # The dimension the model asked for does not exist for this
                # metric. Fall back to a KPI rather than dropping the metric
                # entirely or drawing a chart over a field that is not there.
                as_chart = False
                dimension = ""
            else:
                allowed_types, _ = service.chart_types_for(metric, chosen)
                if not allowed_types:
                    as_chart = False
                    dimension = ""
                else:
                    dimension_label = str(chosen.get("business_name", dimension))
        key = (metric_id, dimension if as_chart else "")
        if key in seen:
            continue
        seen.add(key)
        metrics.append(PlannedMetric(
            metric_id=metric_id, name=metric.name, unit=metric.unit,
            domain=metric.domain, section=section,
            why=str(item.get("why", "")).strip(), as_chart=as_chart,
            dimension=dimension, dimension_label=dimension_label,
            visual=("line" if dimension == "period" else "bar") if as_chart
                   else "kpi",
        ))

    kpi_count = sum(1 for m in metrics if not m.as_chart)
    chart_count = sum(1 for m in metrics if m.as_chart)
    if kpi_count > MAX_METRICS:
        keep = {id(m) for m in [m for m in metrics if not m.as_chart][:MAX_METRICS]}
        metrics = [m for m in metrics if m.as_chart or id(m) in keep]
    if chart_count > MAX_CHARTS:
        keep_charts = {id(m) for m in [m for m in metrics if m.as_chart][:MAX_CHARTS]}
        metrics = [m for m in metrics if not m.as_chart or id(m) in keep_charts]

    return LensPlan(
        title=str(data.get("title", "")).strip(),
        purpose=str(data.get("purpose", "")).strip(),
        scope_summary=str(data.get("scope_summary", "")).strip(),
        domains=[d.to_dict() for d in intent.domains],
        portfolios=portfolios or domains,
        risk_questions=[str(q).strip() for q in (data.get("risk_questions") or [])
                        if str(q).strip()],
        metrics=metrics,
        unsupported=unsupported,
        rationale=str(data.get("rationale", "")).strip(),
        clarify=str(data.get("clarify", "")).strip(),
        understood=True,
        model=answer.model,
    )


def _fallback(request: str, intent: Any, domains: list[str],
             portfolios: list[str], by_id: dict[str, Any], *,
             reason: str) -> LensPlan:
    """The existing deterministic matcher, in the same shape.

    Not a degraded experience so much as the ORIGINAL one: this is exactly
    what `interpret()` already offered before this module existed, and it
    keeps working, unchanged, when there is no model to ask for more.
    """
    metrics = [
        PlannedMetric(metric_id=str(hit.get("metric_id", "")),
                     name=str(hit.get("name", "")), unit=str(hit.get("unit", "")),
                     domain=str(hit.get("domain", "")), section="other",
                     why="Matched the words in the request against the governed "
                         "catalogue.")
        for hit in intent.metrics if hit.get("metric_id") in by_id
    ]
    unsupported = [
        {"requested": str(u.get("name", "")), "because": str(u.get("because", ""))}
        for u in intent.unavailable
    ]
    return LensPlan(
        title="", purpose="", scope_summary=", ".join(domains),
        domains=[d.to_dict() for d in intent.domains],
        portfolios=portfolios or domains, risk_questions=[], metrics=metrics,
        unsupported=unsupported, rationale="", understood=False,
        unavailable=reason,
    )


def to_panels(plan_: LensPlan) -> list[dict[str, Any]]:
    """The accepted plan's metrics, as the panel dicts `POST /lenses` takes.

    Kept separate from `LensPlan` itself so a screen can show the plan, let
    someone untick items, and only turn what is left into panels -- the same
    two-step "propose, then build" the rest of the builder already uses for a
    single metric.
    """
    panels: list[dict[str, Any]] = []
    for m in plan_.metrics:
        if m.as_chart:
            panels.append({
                "kind": "chart", "metric_id": m.metric_id, "visual": m.visual,
                "params": {"dimension": m.dimension, "aggregate": "metric",
                          "sort": "label" if m.dimension == "period" else "value",
                          "direction": "asc" if m.dimension == "period" else "desc",
                          "limit": 20, "compare": ""},
            })
        else:
            panels.append({"kind": "metric", "metric_id": m.metric_id,
                           "visual": "kpi"})
    return panels


__all__ = ["MAX_CHARTS", "MAX_METRICS", "SECTIONS", "LensPlan", "PlannedMetric",
          "plan", "to_panels"]
