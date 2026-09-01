"""External intelligence: what is happening outside the bank, governed.

Why this exists
---------------
An analyst asked to explain why a sector deteriorated has two kinds of
evidence. The portfolio says WHAT changed. Something outside the portfolio
says why it might have. Without the second, the product either says nothing
about causes or invents them — and an invented cause quoted with a real
figure beside it is the most dangerous output a credit platform can produce.

So the external world becomes governed data: rated, dated, sourced, and
linked to borrowers by an explicit table rather than by the model's memory.
The AI may then reason about it, but it can only reason about what is here.

FACT and HYPOTHESIS
-------------------
Every event row carries `evidence_type`. `FACT_IN_CREDITPROBE_DATA` means the
event is recorded here with a date and a source. `ANALYTICAL_HYPOTHESIS`
means a link between an event and a borrower is an inference, not an
observation. The distinction is a column because a distinction that lives
only in a prompt is a distinction that will be lost.

The demonstration scenario
--------------------------
The headline story in this book is a SYNTHETIC DEMONSTRATION SCENARIO: a
disruption to shipping through the Strait of Hormuz, and what it does to
borrowers who move goods through it. It is labelled synthetic on every row
(`scenario_status = "SYNTHETIC DEMONSTRATION SCENARIO"`) and dated inside the
demonstration book's own window. It is not a claim about the world, and
nothing in the product may present it as one.

It exists because a good demonstration needs a story with a causal spine — an
external shock, a transmission path, and a portfolio consequence that a credit
officer can follow and argue with. The chain is explicit in
`sector_sensitivity` and `borrower_external_event_link` so that every step can
be inspected rather than asserted.

Everything here is SYNTHETIC and marked as such on every dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FACT = "FACT_IN_CREDITPROBE_DATA"
HYPOTHESIS = "ANALYTICAL_HYPOTHESIS"

#: Stamped on every row of the scenario, and repeated in each event headline,
#: so no rendering of this data can lose the label.
SYNTHETIC = "SYNTHETIC DEMONSTRATION SCENARIO"

#: The external rating scale, strongest first.
EXTERNAL_SCALE = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C",
]

OUTLOOKS = ["Positive", "Stable", "Negative", "Developing"]

#: Rating agencies as ROLES rather than names. A synthetic book that quotes a
#: real agency's opinion about a fictional borrower is a misrepresentation of
#: that agency, whatever the disclaimer says.
AGENCIES = ["External Agency A", "External Agency B", "External Agency C"]


# --------------------------------------------------------------- the events


def _events(periods: list[str]) -> pd.DataFrame:
    """The governed external event log, hand-written and dated.

    Written out rather than generated: an event log is a set of claims, and a
    claim nobody wrote is a claim nobody can be held to. Every row names its
    category, its severity, the periods it spans and whether it is a recorded
    fact or an analytical reading.
    """
    recent = periods[-6:] if len(periods) >= 6 else periods
    q = {i: p for i, p in enumerate(recent)}
    rows: list[dict] = []

    def add(event_id, category, headline, detail, severity, first, last,
            sectors, direction="adverse", evidence=FACT, scenario=""):
        rows.append({
            "event_id": event_id,
            "category": category,
            "headline": f"{SYNTHETIC}: {headline}",
            "detail": detail,
            "severity": severity,
            "direction": direction,
            "first_period": first,
            "last_period": last,
            "sectors_affected": ", ".join(sectors),
            "evidence_type": evidence,
            "scenario_status": SYNTHETIC,
            "scenario": scenario,
            "source": "CreditProbe demonstration scenario library",
        })

    hormuz = "Strait of Hormuz shipping disruption"
    shipping_sectors = ["Shipping", "Transport & Logistics", "Petrochemicals",
                        "Wholesale & Retail Trade", "Manufacturing"]

    # --- the scenario spine, in the order the transmission runs
    add("EV-HORMUZ-01", "Geopolitical",
        "Transit through the Strait of Hormuz restricted",
        "Vessel transits through the strait are curtailed, and operators "
        "re-route or wait. The first-order effect is time, not price.",
        "Severe", q.get(len(recent) - 4, recent[0]), recent[-1],
        shipping_sectors, scenario=hormuz)
    add("EV-HORMUZ-02", "Shipping",
        "Freight rates on affected routes rise sharply",
        "Charter and spot rates on routes through the strait rise as capacity "
        "is absorbed by longer voyages.",
        "Severe", q.get(len(recent) - 4, recent[0]), recent[-1],
        shipping_sectors, scenario=hormuz)
    add("EV-HORMUZ-03", "Shipping",
        "War-risk insurance premiums increase on affected routes",
        "Hull and cargo war-risk cover repriced for transits through the "
        "affected waters, adding a per-voyage cost.",
        "Material", q.get(len(recent) - 4, recent[0]), recent[-1],
        ["Shipping", "Transport & Logistics"], scenario=hormuz),
    add("EV-HORMUZ-04", "Shipping",
        "Delivery times extend on re-routed cargo",
        "Re-routing adds transit days, which lands in the buyer's working "
        "capital before it lands in anybody's income statement.",
        "Material", q.get(len(recent) - 3, recent[0]), recent[-1],
        shipping_sectors, scenario=hormuz)
    add("EV-HORMUZ-05", "Commodity",
        "Petrochemical feedstock and product prices move on the disruption",
        "Feedstock and product prices move with the freight and delivery "
        "picture rather than with demand.",
        "Material", q.get(len(recent) - 3, recent[0]), recent[-1],
        ["Petrochemicals", "Manufacturing"], scenario=hormuz)
    add("EV-HORMUZ-06", "Sector",
        "Working capital stretches for importers and exporters",
        "Longer voyages mean goods and receivables are in transit for longer, "
        "so the same trade ties up more cash.",
        "Material", q.get(len(recent) - 2, recent[0]), recent[-1],
        shipping_sectors, evidence=HYPOTHESIS, scenario=hormuz)
    add("EV-HORMUZ-07", "Sector",
        "Facility utilisation rises among affected borrowers",
        "Working-capital lines are drawn harder to bridge the longer cycle. "
        "This is an ANALYTICAL READING of the portfolio beside the event, not "
        "an observation of the event itself.",
        "Material", q.get(len(recent) - 2, recent[0]), recent[-1],
        shipping_sectors, evidence=HYPOTHESIS, scenario=hormuz)
    add("EV-HORMUZ-08", "Sector",
        "Refinancing conditions tighten for exposed borrowers",
        "Lenders shorten tenors into the disruption, which front-loads the "
        "maturity ladder for the borrowers least able to carry it.",
        "Material", q.get(len(recent) - 1, recent[-1]), recent[-1],
        ["Shipping", "Transport & Logistics"], evidence=HYPOTHESIS,
        scenario=hormuz)

    # --- unrelated external context, so the scenario is not the only thing
    #     the domain can talk about and a correlation with it is arguable.
    add("EV-RATE-01", "Macro",
        "Policy rate held at the cycle peak",
        "Funding costs stay where they are; floating-rate borrowers see no "
        "relief in debt service.",
        "Moderate", recent[0], recent[-1], ["Real Estate", "Contracting"],
        direction="adverse")
    add("EV-CONSTR-01", "Sector",
        "Contract awards slow in the construction pipeline",
        "New awards slow, which shows up first in receivable days and only "
        "later in revenue.",
        "Material", q.get(len(recent) - 3, recent[0]), recent[-1],
        ["Contracting", "Real Estate"])
    add("EV-TOUR-01", "Sector",
        "Visitor numbers ahead of plan",
        "Hospitality occupancy and average rates run ahead of budget.",
        "Moderate", q.get(len(recent) - 2, recent[0]), recent[-1],
        ["Hospitality & Tourism"], direction="favourable")
    add("EV-UTIL-01", "Macro",
        "Regulated tariff review concluded without change",
        "Utility revenue certainty is unchanged for the period.",
        "Low", recent[-2] if len(recent) > 1 else recent[-1], recent[-1],
        ["Utilities"], direction="neutral")
    return pd.DataFrame(rows)


# ------------------------------------------------------------- the datasets


def build(customers: pd.DataFrame, facility: pd.DataFrame,
          ratings: pd.DataFrame, periods: list[str],
          rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """The ten external-intelligence datasets."""
    events = _events(list(periods))
    external = _external_ratings(customers, ratings, rng)
    return {
        "external_rating_history": external,
        "external_rating_outlook": _outlooks(external, rng),
        "sector_events": _by_category(events, ("Sector",)),
        "macro_events": _by_category(events, ("Macro",)),
        "geopolitical_events": _by_category(events, ("Geopolitical",)),
        "commodity_events": _by_category(events, ("Commodity",)),
        "shipping_events": _by_category(events, ("Shipping",)),
        "borrower_external_event_link": _links(facility, events, rng),
        "sector_sensitivity": _sector_sensitivity(events),
        "borrower_macro_sensitivity": _borrower_sensitivity(facility, rng),
    }


def _by_category(events: pd.DataFrame,
                 categories: tuple[str, ...]) -> pd.DataFrame:
    out = events[events["category"].isin(categories)].copy()
    return out.reset_index(drop=True)


def _external_ratings(customers: pd.DataFrame, ratings: pd.DataFrame,
                      rng: np.random.Generator) -> pd.DataFrame:
    """An external agency view per borrower per rating cycle.

    Anchored on the bank's own internal rating and then moved: an external
    view that agreed with the internal one everywhere would answer no
    question. The gap between them is the point — it is what a rating-lag
    signal reads.
    """
    have = [c for c in ("customer_id", "period", "risk_rating",
                        "internal_grade", "rating_grade")
            if c in ratings.columns]
    frame = ratings[have].copy()
    if "period" not in frame.columns:
        frame["period"] = ""
    n = len(frame)

    # Place the borrower on the external scale from its internal grade where
    # one is readable, and from the middle of the scale where it is not.
    grade = None
    for column in ("risk_rating", "internal_grade", "rating_grade"):
        if column in frame.columns:
            grade = frame[column].astype(str)
            break
    if grade is None:  # pragma: no cover - ratings always carry one
        grade = pd.Series(["7"] * n)
    numeric = pd.to_numeric(grade.str.extract(r"(\d+)")[0], errors="coerce")
    spread = numeric.fillna(numeric.median() if numeric.notna().any() else 7.0)
    lo, hi = float(spread.min()), float(spread.max())
    scaled = ((spread - lo) / max(hi - lo, 1e-9)) * (len(EXTERNAL_SCALE) - 5)
    notch = np.clip(np.round(scaled.to_numpy() + rng.normal(1.5, 1.6, n)),
                    0, len(EXTERNAL_SCALE) - 1).astype(int)

    frame["agency"] = rng.choice(AGENCIES, n)
    frame["external_rating"] = [EXTERNAL_SCALE[i] for i in notch]
    frame["external_rating_notch"] = notch
    frame["investment_grade"] = notch <= EXTERNAL_SCALE.index("BBB-")
    frame["rated"] = True
    frame["evidence_type"] = FACT
    frame["scenario_status"] = SYNTHETIC
    del customers
    keep = ["customer_id", "period", "agency", "external_rating",
            "external_rating_notch", "investment_grade", "evidence_type",
            "scenario_status"]
    return frame[[c for c in keep if c in frame.columns]].reset_index(drop=True)


def _outlooks(external: pd.DataFrame,
              rng: np.random.Generator) -> pd.DataFrame:
    """The outlook attached to each external rating.

    Weighted by where the borrower sits on the scale: a CCC does not carry a
    positive outlook, and a AA rarely carries a negative one.
    """
    out = external[["customer_id", "period", "agency", "external_rating",
                    "external_rating_notch"]].copy()
    n = len(out)
    weak = out["external_rating_notch"].to_numpy() / max(
        len(EXTERNAL_SCALE) - 1, 1)
    draw = rng.random(n)
    outlook = np.where(
        draw < 0.10 + 0.34 * weak, "Negative",
        np.where(draw < 0.20 + 0.38 * weak, "Developing",
                 np.where(draw < 0.30 - 0.12 * weak, "Positive", "Stable")))
    out["outlook"] = outlook
    out["on_watch"] = (outlook == "Negative") & (rng.random(n) < 0.28)
    out["evidence_type"] = FACT
    out["scenario_status"] = SYNTHETIC
    return out.reset_index(drop=True)


def _sector_sensitivity(events: pd.DataFrame) -> pd.DataFrame:
    """How much each event is expected to move each sector it names.

    This table IS the transmission path. It is written down so that the chain
    from an external event to a portfolio consequence can be inspected step by
    step, rather than asserted in a sentence a reader has to take on trust.
    """
    rows: list[dict] = []
    weights = {"Severe": 1.0, "Material": 0.65, "Moderate": 0.35, "Low": 0.15}
    channels = {
        "Geopolitical": "route availability",
        "Shipping": "freight cost and transit time",
        "Commodity": "input and output prices",
        "Macro": "funding cost and demand",
        "Sector": "working capital and utilisation",
    }
    for _, event in events.iterrows():
        named = [s.strip() for s in str(event["sectors_affected"]).split(",")
                 if s.strip()]
        for rank, sector in enumerate(named):
            # The first sector named is the one the event bites hardest.
            decay = 1.0 - 0.16 * rank
            rows.append({
                "event_id": event["event_id"],
                "sector": sector,
                "category": event["category"],
                "transmission_channel": channels.get(
                    str(event["category"]), "general"),
                "sensitivity": round(
                    weights.get(str(event["severity"]), 0.3) * max(decay, 0.2),
                    3),
                "direction": event["direction"],
                "evidence_type": event["evidence_type"],
                "scenario": event["scenario"],
                "scenario_status": SYNTHETIC,
            })
    return pd.DataFrame(rows)


def _links(facility: pd.DataFrame, events: pd.DataFrame,
           rng: np.random.Generator) -> pd.DataFrame:
    """Which borrowers each event plausibly reaches, and on what basis.

    Every row is an ANALYTICAL_HYPOTHESIS. The bank observes that a borrower
    is in an affected sector and that its utilisation rose; it does not
    observe that the one caused the other. Recording the link as an inference
    is the difference between an analyst's reading and a fabricated fact.
    """
    latest = facility["period"].astype(str).max()
    book = facility[facility["period"].astype(str) == latest]
    keep = [c for c in ("customer_id", "sector", "utilisation_pct", "dscr",
                        "exposure") if c in book.columns]
    book = book[keep].groupby("customer_id", observed=True).agg(
        sector=("sector", "first"),
        utilisation_pct=("utilisation_pct", "mean"),
        exposure=("exposure", "sum")).reset_index()

    rows: list[dict] = []
    for _, event in events.iterrows():
        named = {s.strip() for s in str(event["sectors_affected"]).split(",")
                 if s.strip()}
        exposed = book[book["sector"].isin(named)]
        if exposed.empty:
            continue
        # Not every borrower in a sector is reached by every event. The ones
        # drawing hardest on their lines are the ones a credit officer would
        # look at first, so those are linked with the higher confidence.
        used = exposed["utilisation_pct"].to_numpy(dtype=float)
        rank = (used - np.nanmin(used)) / max(
            float(np.nanmax(used) - np.nanmin(used)), 1e-9)
        keep_it = rng.random(len(exposed)) < np.clip(0.25 + 0.55 * rank, 0, 1)
        for (_, borrower), take, score in zip(
                exposed.iterrows(), keep_it, rank, strict=False):
            if not take:
                continue
            rows.append({
                "event_id": event["event_id"],
                "customer_id": borrower["customer_id"],
                "sector": borrower["sector"],
                "period": latest,
                "link_basis": "sector exposure and facility utilisation",
                "confidence": round(float(0.35 + 0.5 * score), 3),
                # Never FACT. The bank did not watch the event happen to
                # this borrower; it inferred that it would.
                "evidence_type": HYPOTHESIS,
                "scenario": event["scenario"],
                "scenario_status": SYNTHETIC,
            })
    return pd.DataFrame(rows)


def _borrower_sensitivity(facility: pd.DataFrame,
                          rng: np.random.Generator) -> pd.DataFrame:
    """How much each borrower's quality moves with the macro cycle.

    A beta per borrower, so "which names are most exposed to a rate move?"
    has an answer that is not a sector average applied to everybody in it.
    """
    latest = facility["period"].astype(str).max()
    book = facility[facility["period"].astype(str) == latest]
    out = book.groupby("customer_id", observed=True).agg(
        sector=("sector", "first"),
        exposure=("exposure", "sum"),
        utilisation_pct=("utilisation_pct", "mean"),
        dscr=("dscr", "mean")).reset_index()
    n = len(out)
    used = np.clip(out["utilisation_pct"].to_numpy(dtype=float) / 100.0, 0, 1.2)
    cover = np.nan_to_num(out["dscr"].to_numpy(dtype=float), nan=1.4)
    out["macro_beta"] = np.round(
        np.clip(0.75 + 0.55 * used - 0.18 * np.clip(cover - 1.0, 0, 2)
                + rng.normal(0, 0.12, n), 0.15, 2.4), 3)
    out["rate_sensitivity"] = np.round(
        np.clip(out["macro_beta"] * rng.uniform(0.5, 1.1, n), 0.05, 2.2), 3)
    out["fx_sensitivity"] = np.round(
        np.clip(rng.normal(0.5, 0.28, n), 0.0, 1.8), 3)
    out["commodity_sensitivity"] = np.round(
        np.clip(rng.normal(0.45, 0.32, n), 0.0, 2.0), 3)
    out["period"] = latest
    out["evidence_type"] = HYPOTHESIS
    out["scenario_status"] = SYNTHETIC
    return out


#: (catalogue domain, business name, purpose, grain, primary keys, owner).
DOMAINS: dict[str, tuple[str, str, str, str, list[str], str]] = {
    "external_rating_history": (
        "External Intelligence", "External Rating History",
        "The external agency view of each borrower per rating cycle, on the "
        "agency scale, beside the bank's own. The GAP between them is what a "
        "rating-lag signal reads.",
        "One row per borrower per rating cycle.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "external_rating_outlook": (
        "External Intelligence", "External Rating Outlook",
        "The outlook and watch status attached to each external rating.",
        "One row per borrower per rating cycle.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "sector_events": (
        "External Intelligence", "Sector Events",
        "Governed external events affecting a named sector, each labelled as "
        "a recorded fact or an analytical reading.",
        "One row per event.",
        ["event_id"], "Credit Research"),
    "macro_events": (
        "External Intelligence", "Macroeconomic Events",
        "Governed macroeconomic events — policy rates, demand, regulated "
        "prices — and the sectors they reach.",
        "One row per event.",
        ["event_id"], "Credit Research"),
    "geopolitical_events": (
        "External Intelligence", "Geopolitical Events",
        "Governed geopolitical events and the sectors they reach.",
        "One row per event.",
        ["event_id"], "Credit Research"),
    "commodity_events": (
        "External Intelligence", "Commodity Events",
        "Governed commodity price and availability events.",
        "One row per event.",
        ["event_id"], "Credit Research"),
    "shipping_events": (
        "External Intelligence", "Shipping and Freight Events",
        "Governed shipping events — route availability, freight rates, "
        "insurance cost, transit times.",
        "One row per event.",
        ["event_id"], "Credit Research"),
    "borrower_external_event_link": (
        "External Intelligence", "Borrower to External Event Links",
        "Which borrowers each external event plausibly reaches, on what "
        "basis, and with what confidence. Every row is an analytical "
        "hypothesis: the bank inferred the link, it did not observe it.",
        "One row per event per borrower.",
        ["event_id", "customer_id"], "Credit Research"),
    "sector_sensitivity": (
        "External Intelligence", "Sector Sensitivity to External Events",
        "How much each event is expected to move each sector it names, and "
        "through which channel. This table is the transmission path, written "
        "down so the chain can be inspected step by step.",
        "One row per event per sector.",
        ["event_id", "sector"], "Credit Research"),
    "borrower_macro_sensitivity": (
        "External Intelligence", "Borrower Macro Sensitivity",
        "A macro, rate, currency and commodity beta per borrower, so a "
        "question about exposure to a move has an answer that is not a sector "
        "average applied to everybody in it.",
        "One row per borrower.",
        ["customer_id"], "Credit Risk Analytics"),
}


__all__ = ["AGENCIES", "DOMAINS", "EXTERNAL_SCALE", "FACT", "HYPOTHESIS",
           "OUTLOOKS", "SYNTHETIC", "build"]
