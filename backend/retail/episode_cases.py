"""The nine stories as Risk Cases, from one adapter rather than nine templates.

The defect this exists for
--------------------------
"Ten attention cards" is easy to fake and the fake is easy to spot from the
second question onwards. So there is no per-story card text here at all: one
function reads a story's measured populations out of `episode_measures` and
writes a Draft from them. A sentence in a conclusion is assembled from the
figures it quotes, so it cannot disagree with them, and an episode whose
numbers moved produces a card whose words moved with them.

Severity is arithmetic, not a label
-----------------------------------
The governed `backend.agentic.severity` score, over five components, each
carrying the raw figure it was computed from so a reader can redo it:

* **materiality** — the exposure the issue population carries, against the
  eligible population's;
* **magnitude** — how far above the comparator the rate sits;
* **concentration** — the share of the cases the named pocket holds;
* **persistence** — how many of the last six month-ends it has been rising;
* **data confidence** — the share of alerts that survived corroboration.

Nothing here moves a threshold to turn a card red. A story whose figures do
not reach a band does not get that band, and two of the nine do not.

Idempotence
-----------
The dedupe key is (SEGMENT, case id, period, about), so replaying a review for
the same month refreshes the card it already made rather than opening a second
one. The human state on it — owner, status, comments — is never touched by a
refresh; that is `agentic.cases.upsert`'s contract and this relies on it.

Everything read here is SYNTHETIC demonstration data.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agentic import cases as rc
from backend.agentic import severity as sv
from backend.retail import episode_measures as em
from backend.retail import episodes as ep

logger = logging.getLogger(__name__)

VERSION = "retail-episode-cases-1.0.0"

#: Every card this module raises carries this, so the orchestrator can route a
#: question asked inside one of these investigations to the right reader and
#: nowhere else.
ABOUT = "retail_episode"

#: A card is not raised for a story whose figures do not reach these. They are
#: synthetic demonstration thresholds and bank-configurable; none is a policy.
MIN_MULTIPLE = 1.5
MIN_AFFECTED = 20


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _sar(value: float | None) -> str:
    return "n/a" if value is None else f"SAR {value:,.0f}"


def _severity(*, drawer: dict[str, Any], rising: int,
              corroborated_share: float) -> sv.Score:
    """Five components, each with the figure behind it."""
    affected = drawer["affected"]
    eligible = max(drawer["eligible"], 1)
    multiple = drawer.get("multiple") or 1.0
    pocket = drawer["concentration"]["pocket"]
    case_share = pocket.get("share_of_cases") or 0.0
    exposure = drawer.get("exposure_sar") or 0.0
    totals = drawer.get("totals") or {}

    materiality = min(affected / (eligible * 0.20), 1.0)
    magnitude = min(max(multiple - 1.0, 0.0) / 3.0, 1.0)
    concentration = min(case_share, 1.0)
    persistence = min(rising / 4.0, 1.0)
    confidence = min(max(corroborated_share, 0.0), 1.0)

    components = [
        sv.Component(
            key=sv.MATERIALITY, value=materiality, weight=0.26,
            detail=(f"{affected:,} of {eligible:,} eligible observations, "
                    f"against a 20% cap, carrying {_sar(exposure)}"),
            observed=affected),
        sv.Component(
            key=sv.MAGNITUDE, value=magnitude, weight=0.28,
            detail=(f"{multiple:.2f} times the comparator rate, with the "
                    f"first multiple scoring nothing and 4x scoring full"),
            observed=round(multiple, 4)),
        sv.Component(
            key=sv.CONCENTRATION, value=concentration, weight=0.20,
            detail=(f"{case_share * 100:.0f}% of the cases sit in the named "
                    f"pocket, which is {pocket.get('eligible', 0):,} of "
                    f"{eligible:,} eligible observations"),
            observed=round(case_share, 4)),
        sv.Component(
            key=sv.PERSISTENCE, value=persistence, weight=0.14,
            detail=f"{rising} of the last month-ends rose, capped at 4",
            observed=rising),
        sv.Component(
            key=sv.DATA_CONFIDENCE, value=confidence, weight=0.12,
            detail=(f"{corroborated_share * 100:.0f}% of the alerts survived "
                    f"independent corroboration"),
            observed=round(corroborated_share, 4)),
    ]
    total = sum(c.value * c.weight for c in components)
    band = next(name for floor, name in sv.BANDS if total >= floor)
    return sv.Score(score=round(total, 4), band=band, components=components)


def _rising_months(trend: dict[str, Any]) -> int:
    rows = [r for r in (trend.get("rows") or []) if r.get("rate_pct") is not None]
    run = 0
    for earlier, later in zip(rows, rows[1:], strict=False):
        run = run + 1 if later["rate_pct"] > earlier["rate_pct"] else 0
    return run


def _evidence_shares(month: str, case_id: str) -> tuple[float, int, int]:
    """What share of the alerts survived verification and corroboration."""
    data = em.frame(month)
    issue = em.issue_mask(data, case_id) & em.eligible_mask(data, case_id)
    total = int(issue.sum())
    if not total:
        return 0.0, 0, 0
    verified = int((issue & em.evidence_mask(data, ep.EV_VERIFIED)).sum())
    corroborated = int(
        (issue & em.evidence_mask(data, ep.EV_CORROBORATED)).sum())
    return corroborated / total, verified, corroborated


def draft(period: str = "", case_id: str = "") -> rc.Draft | None:
    """One story's card, from its measured figures. None when it does not hold.

    Returning None is not a failure path that never runs: two of the nine sit
    close to the raising thresholds, and a demonstration in which every card
    always appears whatever the book says is a demonstration of nothing.
    """
    if case_id == "C01":
        # Alpha is raised by `review._early_delinquency` against its own
        # accepted calibration. The refusal belongs HERE rather than in
        # `drafts()`, because a caller that asks this function directly would
        # otherwise get a second card for a finding that already has one —
        # and `dedupe_key` would not catch it, since the two carry different
        # `about` values and are therefore different findings as far as the
        # Risk Case store is concerned.
        return None
    episode = ep.by_id(case_id)
    if episode is None:
        return None
    view = em.drawer(period, case_id)
    if not view.get("available"):
        return None

    at = view["as_of"]
    against = view["comparator"]
    multiple = view.get("multiple")
    if view["affected"] < MIN_AFFECTED or not multiple \
            or multiple < MIN_MULTIPLE:
        logger.info("episode %s does not reach the raising thresholds at %s "
                    "(%s affected, %sx the comparator)",
                    case_id, at, view["affected"], multiple)
        return None

    trend = view["trend"]
    rising = _rising_months(trend)
    corroborated_share, verified_n, corroborated_n = _evidence_shares(at, case_id)
    pocket = view["concentration"]["pocket"]
    outside = view["concentration"]["outside"]
    risk = view["risk"]
    scores = view["scores"]

    rate = view["rate"]
    ecl_before, ecl_now = risk["ecl"]["before"], risk["ecl"]["now"]
    pd_before = risk["pd_12m"]["before"]
    pd_now = risk["pd_12m"]["now"]

    # The forward-PD sentence, or the honest refusal of one. An already
    # impaired cohort is not a prediction about whether it will default.
    if risk["forward_pd_applies"] and pd_before is not None \
            and pd_now is not None:
        pd_sentence = (
            f"Over the {risk['comparable_cohort']:,} of them that are not "
            f"already credit-impaired, the 12-month probability of default "
            f"moves from {_pct(pd_before)} to {_pct(pd_now)}, "
            f"exposure-weighted and point-in-time.")
    else:
        pd_sentence = (
            f"All {risk['cohort']:,} are already credit-impaired, so a "
            f"comparable forward probability of default does not apply to "
            f"them. Stage and recovery are shown instead: "
            + ", ".join(f"{k.replace('_', ' ')} {v:,}"
                        for k, v in (risk["stage"]["now"] or {}).items())
            + ".")

    behaviour = scores["behaviour"]
    if behaviour["change"] is not None:
        score_sentence = (
            f"The same {behaviour['cohort']:,} facilities' median behavioural "
            f"score moves {behaviour['change']:+.0f} points since "
            f"{behaviour['reference_month']}, to {behaviour['now']:.0f}. "
            f"Their original application scores are unchanged, because an "
            f"origination value is fixed at its own decision date.")
    else:
        score_sentence = (
            "Behavioural scores are not comparable for this cohort at this "
            "date; the coverage panel says for how many.")

    conclusion = (
        f"{view['card_measure']}: {view['affected']:,} of "
        f"{view['eligible']:,} eligible observations meet the issue rule at "
        f"{at} — {_pct(rate)} against {_pct(against.get('rate'))} in "
        f"{against.get('label')}, {multiple:.2f} times it and "
        f"{view['points']:+.1f} percentage points. They carry "
        f"{_sar(view['exposure_sar'])} of gross exposure. For those same "
        f"facilities, expected credit loss moves from {_sar(ecl_before)} to "
        f"{_sar(ecl_now)}. {pd_sentence} {score_sentence} "
        f"The named pocket — {episode.pocket_label} — holds "
        f"{pocket.get('eligible', 0):,} of the eligible observations "
        f"({_pct(pocket.get('share_of_eligible'))}) and "
        f"{pocket.get('issue', 0):,} of the cases "
        f"({_pct(pocket.get('share_of_cases'))}): an incidence of "
        f"{_pct(pocket.get('incidence'))} inside it against "
        f"{_pct(outside.get('incidence'))} outside, a "
        f"{view['concentration'].get('rate_ratio')}x rate ratio. "
        f"{episode.countercheck}")

    why = (
        f"Raised because {view['affected']:,} eligible observations meet a "
        f"written rule — {view['predicate']['describes']} — at the reporting "
        f"date, at {multiple:.2f} times its comparator. The comparator is "
        f"{against.get('label')}, which is stated because three different "
        f"things are called a comparator in this product and a figure "
        f"quoted against an unnamed one cannot be checked. "
        f"Of the {view['affected']:,} alerts, {verified_n:,} survive "
        f"verification and {corroborated_n:,} are independently corroborated; "
        f"the investigation narrows to those rather than acting on the alert "
        f"count. Thresholds are synthetic demonstration settings and "
        f"bank-configurable: at least {MIN_AFFECTED} affected observations "
        f"and at least {MIN_MULTIPLE:.1f} times the comparator. None of them "
        f"is a policy, and the policy clauses this case cites are clearly "
        f"marked demonstration drafts that no bank has approved.")

    metrics: list[dict[str, Any]] = [
        {"label": "Affected observations", "value": view["affected"],
         "unit": "count", "period": at},
        {"label": "Eligible observations", "value": view["eligible"],
         "unit": "count", "period": at},
        {"label": "Issue rate", "value": round((rate or 0) * 100, 3),
         "unit": "%", "period": at},
        {"label": "Comparator rate",
         "value": round((against.get("rate") or 0) * 100, 3), "unit": "%",
         "period": against.get("as_of") or at},
        {"label": "Against the comparator", "value": multiple, "unit": "x"},
        {"label": "Gross exposure", "value": view["exposure_sar"],
         "unit": "SAR", "period": at},
        {"label": "Expected credit loss, same facilities",
         "value": ecl_now, "unit": "SAR", "period": at},
        {"label": "Expected credit loss, prior month, same facilities",
         "value": ecl_before, "unit": "SAR", "period": risk.get("previous")},
        {"label": "Pocket share of cases",
         "value": round((pocket.get("share_of_cases") or 0) * 100, 2),
         "unit": "%", "period": at},
        {"label": "Incidence inside the pocket",
         "value": round((pocket.get("incidence") or 0) * 100, 2), "unit": "%"},
        {"label": "Incidence outside the pocket",
         "value": round((outside.get("incidence") or 0) * 100, 2), "unit": "%"},
        {"label": "Corroborated alerts", "value": corroborated_n,
         "unit": "count", "period": at},
    ]
    if risk["forward_pd_applies"] and pd_now is not None:
        metrics.append({"label": "12-month PD, non-impaired issue cohort",
                        "value": round(pd_now * 100, 3), "unit": "%",
                        "period": at})
    if behaviour.get("now") is not None:
        metrics.append({"label": "Behavioural score, median",
                        "value": behaviour["now"], "unit": "points",
                        "period": at})

    signals = [
        f"{_pct(pocket.get('incidence'))} incidence inside "
        f"{episode.pocket_label} against {_pct(outside.get('incidence'))} "
        f"outside it",
        f"{corroborated_n:,} of {view['affected']:,} alerts independently "
        f"corroborated",
        f"expected credit loss on the same facilities "
        f"{_sar(ecl_before)} to {_sar(ecl_now)}",
    ]
    if rising:
        signals.append(f"the rate rose at {rising} of the last month-ends")
    if not risk["forward_pd_applies"]:
        signals.append(risk["forward_pd_note"])

    return rc.Draft(
        level=rc.SEGMENT,
        title=f"{episode.title}: {episode.card_measure.lower()}",
        period=at,
        prior_period=risk.get("previous") or "",
        entity=episode.pocket_label,
        entity_id=case_id,
        entity_kind="episode",
        about=ABOUT,
        conclusion=conclusion,
        why=why,
        exposure=round((view["exposure_sar"] or 0) / 1_000_000, 4),
        exposure_unit="SAR mn",
        metrics=metrics,
        signals=signals,
        evidence={
            "dataset": em.BOOK,
            "case_id": case_id,
            "product": episode.product,
            "product_family": episode.product_family,
            "grain": episode.grain,
            "rule": f"retail.episode.{case_id.lower()}",
            "predicate": view["predicate"],
            "thresholds": view["thresholds"],
            "comparator": against,
            "countercheck": episode.countercheck,
            "drawer": view,
            "chart": {
                "title": trend.get("title"),
                "unit": trend.get("unit"),
                "denominator": trend.get("denominator"),
                "rows": trend.get("rows"),
                "series": ["rate_pct"],
            },
            "evidence_attrition": {
                "alerts": view["affected"],
                "verified": verified_n,
                "corroborated": corroborated_n,
            },
            "policy": view["policy"],
            "research": view["research"],
            "sources": view["sources"],
            "narrative": episode.countercheck,
            "threshold_source": (
                f"Synthetic demonstration thresholds, bank-configurable: at "
                f"least {MIN_AFFECTED} affected observations and at least "
                f"{MIN_MULTIPLE:.1f} times the comparator."),
        },
        evidence_coverage=round(corroborated_share, 4),
        score=_severity(drawer=view, rising=rising,
                        corroborated_share=corroborated_share),
    )


def drafts(period: str = "") -> list[rc.Draft]:
    """Every story that holds at this month, in the order the cases are numbered.

    C01 is not here. Alpha is raised by `review._early_delinquency` against its
    own accepted calibration, and moving it into this adapter would change the
    card a signed-off demonstration opens on.
    """
    out: list[rc.Draft] = []
    for case_id in ep.case_ids():
        made = draft(period, case_id)
        if made is not None:
            out.append(made)
    return out


def rule(period: str) -> list[rc.Draft]:
    """The review's entry point. Never raises: a story that cannot be measured
    is left out with a log line rather than taking the whole review down."""
    try:
        return drafts(period)
    except em.MissingEpisodeColumns as exc:
        logger.warning("the episodes cannot be measured on this book: %s", exc)
        return []
