"""
Everything the Early Warning Score workspace reads, served from one domain.

Every function here reads `retail_ews_score` and the model configuration, and
nothing else. That is not a convention: it is what makes the chat's domain
scope enforceable, because the chat calls these functions and has no other way
to reach a dataset.

The levels are the user journey, in order:

    portfolio()   total retail: headline KPIs and four product cards
    product()     one product: its KPIs and its sub-product cards
    sub_product() one sub-portfolio: its KPIs, signals and commentary
    customers()   the filtered customer list, with six-month mini series
    customer()    one customer: four layers, sublayers, variables, triggers,
                  action dimensions, facilities, exposure shares
    signals()     the rules view
    model()       the model tree, with live hit counts against it

Counting rules, applied everywhere
----------------------------------
A CUSTOMER count is `nunique` over customer ids, never a row count. A customer
holding a card and a mortgage is one customer at portfolio level and appears
once in each product. Exposure sums facility rows, because exposure IS a
facility measure. A customer's score is the worst of their facilities: a clean
mortgage must not average away a card that is ninety days down.

ODR has a denominator and says so. It is facilities entering default in the
month over facilities that were not in default at its start, computed here and
never stored against a customer.
"""

from __future__ import annotations

from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_score as S

#: The cohorts the customer list offers. Each is a governed classification.
COHORTS: tuple[tuple[str, str, str], ...] = (
    ("all", "All warned customers",
     "Every customer whose Early Warning Score is at or above the warning "
     "cutoff."),
    ("current_bad", "Currently bad / delinquent", S.CURRENT_BAD_RULE
     + " Listed whether or not a trigger also fired against them."),
    ("forward_risk", "Performing — high forward risk", S.FORWARD_RISK_RULE),
    ("critical", "Critical", "Early Warning Score in the CRITICAL band."),
    ("high", "High", "Early Warning Score in the HIGH band."),
    ("everyone", "Every customer",
     "The whole eligible population, warned or not."),
)


# --------------------------------------------------------------- helpers

def _money(value: Any) -> float:
    return round(float(value or 0.0), 2)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _num_or_none(value: Any) -> float | None:
    import math

    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    text = str(value if value is not None else "")
    return "" if text.lower() in ("nan", "none", "<na>", "nat") else text


def latest_month() -> str:
    every = S.panel_months()
    return every[-1] if every else ""


def _at(month: str = "") -> str:
    every = S.panel_months()
    if not every:
        return ""
    return month if month in every else every[-1]


def _per_customer(frame: Any) -> Any:
    """One row per customer: their worst facility, and their total exposure.

    A customer's Early Warning Score is the worst of the facilities they hold.
    Averaging would let a large clean mortgage hide a card that is ninety days
    down, which is the whole point of not doing it.
    """
    import pandas as pd

    if not len(frame):
        return frame
    # `sort_values` here moved all 483 columns of the panel and cost half a
    # second on a month; the portfolio screen calls this thirty times and took
    # thirteen seconds to draw. `idxmax` reads one column and takes the rows
    # by position, which is the same answer with a defined tie-break — the
    # first facility in panel order, rather than whatever an unstable sort
    # happened to leave on top.
    worst = frame.loc[
        frame.groupby("customer_id")["ews_score"].idxmax()
    ].set_index("customer_id")
    totals = frame.groupby("customer_id").agg(
        customer_exposure_sar=("gross_carrying_amount_sar", "sum"),
        facilities=("facility_id", "nunique"),
        customer_dpd=("dpd", "max"),
        customer_stage=("ifrs9_stage", "max"),
        customer_triggers=("triggers_fired", "sum"),
        # Each layer at the customer's WORST facility for that layer, which is
        # not necessarily the facility carrying their highest overall score.
        # Read off the worst-overall row instead, the list and the customer's
        # own page disagreed: RC-0025457 read bureau 0.0 in the list and 42.4
        # on their page, because their card and their loan were seen by the
        # bureau at different pulls.
        **{f"layer_{one.key}": (one.score_column, "max") for one in M.LAYERS},
        # Over ALL of the customer's facilities, not the worst-scoring one.
        # Taken from the worst row it under-counted the already-bad by one at
        # 2026-08: a customer can be thirty days down on a facility that is
        # not the one carrying their highest score.
        any_current_bad=("current_bad_flag", "any"),
    )
    joined = worst.join(totals, how="left").reset_index()
    for one in M.LAYERS:
        joined[one.score_column] = joined[f"layer_{one.key}"]
    joined["current_bad_flag"] = joined["any_current_bad"].fillna(False)
    joined["forward_risk_flag"] = (
        (~joined["current_bad_flag"])
        & joined["ews_severity"].isin(("HIGH", "CRITICAL")))
    del pd
    return joined


def _counts(frame: Any, *, book_exposure: float | None = None) -> dict[str, Any]:
    """The headline block for any population, counted the same way every time."""
    import pandas as pd

    if not len(frame):
        return {
            "customers": 0, "customers_warned": 0, "high_or_critical": 0,
            "current_bad": 0, "forward_risk": 0, "facilities": 0,
            "exposure_sar": 0.0, "exposure_warned_sar": 0.0,
            "exposure_warned_pct": 0.0, "ews_score": 0.0,
            "severity_band": "LOW", "severity": {b: 0 for _, b in M.SEVERITY_BANDS},
            "triggers_fired": 0, "default_entries": 0, "odr_pct": 0.0,
            "dpd_30_plus_pct": 0.0,
        }
    people = _per_customer(frame)
    warned = people[people["ews_score"] >= M.SCALE.warning_cutoff]
    exposure_all = _money(frame["gross_carrying_amount_sar"].sum())
    warned_ids = set(warned["customer_id"])
    exposure_warned = _money(
        frame[frame["customer_id"].isin(warned_ids)][
            "gross_carrying_amount_sar"].sum())
    base = book_exposure if book_exposure is not None else exposure_all

    bands = people["ews_score"].map(M.band_of).value_counts()
    severity = {band: _int(bands.get(band, 0)) for _, band in M.SEVERITY_BANDS}

    eligible = _int(frame.get("eligible_for_default_this_month",
                              pd.Series(dtype=bool)).sum())
    entries = _int(frame.get("default_entry_this_month",
                             pd.Series(dtype=bool)).sum())
    dpd = pd.to_numeric(frame["dpd"], errors="coerce").fillna(0.0)

    score = _population_score(frame, people)
    return {
        "customers": _int(frame["customer_id"].nunique()),
        "customers_warned": _int(warned["customer_id"].nunique()),
        "high_or_critical": severity.get("HIGH", 0) + severity.get("CRITICAL", 0),
        "current_bad": _int(
            people[people["current_bad_flag"].fillna(False)]["customer_id"]
            .nunique()),
        "forward_risk": _int(
            people[people["forward_risk_flag"].fillna(False)]["customer_id"]
            .nunique()),
        "facilities": _int(frame["facility_id"].nunique()),
        "exposure_sar": exposure_all,
        "exposure_warned_sar": exposure_warned,
        "exposure_warned_pct": round(exposure_warned / base * 100, 4)
                               if base else 0.0,
        "ews_score": score,
        "severity_band": M.population_band_of(score),
        # The same band, read with its distance to the next one, so a
        # portfolio sitting just under HIGH is not reported as a flat MEDIUM.
        "severity_reading": M.population_band_reading(score),
        "severity": severity,
        "triggers_fired": _int(frame["triggers_fired"].sum()),
        "default_entries": entries,
        "default_eligible": eligible,
        "odr_pct": round(entries / eligible * 100, 4) if eligible else 0.0,
        "dpd_30_plus_pct": round(float((dpd >= 30).mean()) * 100, 4),
    }


def _population_score(frame: Any, people: Any = None) -> float:
    """A population's Early Warning Score: exposure-weighted over EVERYONE.

    Over everyone in the population, including the customers with nothing
    firing, because they are part of the product and a product where nine in
    ten customers are clean is not as bad as one where half are not.

    Averaging only the WARNED was tried first and cannot discriminate: it
    measures the severity of the warned customers and says nothing about how
    many of them there are, so every product came out between 49 and 65 and
    all four wore a CRITICAL badge. Weighted across the whole population the
    four products separate — this book runs 14.0 to 17.1 — and the population
    band table is set at that scale. How MANY are warned is reported beside
    it as the warned count and the share of exposure under warning.
    """
    if not len(frame):
        return 0.0
    # Taken from the caller where it has one: `_counts` already built it, and
    # building it twice was half the cost of every figure on the screen.
    if people is None:
        people = _per_customer(frame)
    weight = people["customer_exposure_sar"].fillna(0.0)
    total = float(weight.sum())
    if total <= 0:
        return round(float(people["ews_score"].mean()), 2)
    return round(float((people["ews_score"] * weight).sum() / total), 2)


def _layer_means(frame: Any) -> dict[str, float]:
    """Each layer's exposure-weighted score across the whole population."""
    if not len(frame):
        return {layer.key: 0.0 for layer in M.LAYERS}
    people = _per_customer(frame)
    weight = people["customer_exposure_sar"].fillna(0.0)
    total = float(weight.sum()) or 1.0
    return {layer.key: round(
        float((people[layer.score_column].fillna(0.0) * weight).sum() / total), 2)
        for layer in M.LAYERS}


def _where(frame: Any, *, product: str = "", classification: str = "",
           sub_product: str = "") -> Any:
    if product:
        frame = frame[frame["product_code"] == str(product).upper()]
    if classification:
        frame = frame[frame["classification"] == str(classification).upper()]
    if sub_product:
        frame = frame[frame["sub_product"] == str(sub_product).upper()]
    return frame


#: Computed series, keyed by what they were computed over. The panel is
#: immutable between builds, so a month already counted cannot change; this is
#: cleared with the panel itself in `forget()`.
_SERIES: dict[tuple[Any, ...], list[dict[str, Any]]] = {}


def _salary_transfer_pct(rows: Any) -> float:
    """What share of this slice routes salary through the bank.

    Reported BESIDE the classification, never as it: a self-employed customer
    can transfer income here and a salaried one can be paid elsewhere, so the
    two facts answer different questions.
    """
    column = rows.get("salary_transfer_flag") if len(rows) else None
    if column is None or not len(rows):
        return 0.0
    return round(float(column.fillna(False).astype(bool).mean()) * 100, 2)


def _materiality(rows: Any, parents: dict[str, Any]) -> dict[str, Any]:
    """What share of each parent this slice is, on all three counts.

    Customers, accounts and exposure, because they answer different
    questions: a segment can be two per cent of the customers and a fifth of
    the money. Every card carries all three so that "small" and "immaterial"
    cannot be confused for each other.
    """
    mine = {
        "customers": _int(rows["customer_id"].nunique()) if len(rows) else 0,
        "accounts": _int(rows["facility_id"].nunique()) if len(rows) else 0,
        "exposure_sar": _money(rows["gross_carrying_amount_sar"].sum())
                        if len(rows) else 0.0,
    }
    out: dict[str, Any] = {"of": mine}
    for name, parent in parents.items():
        if parent is None or not len(parent):
            continue
        whole = {
            "customers": _int(parent["customer_id"].nunique()),
            "accounts": _int(parent["facility_id"].nunique()),
            "exposure_sar": _money(parent["gross_carrying_amount_sar"].sum()),
        }
        out[name] = {
            "customers_pct": round(mine["customers"] / whole["customers"] * 100, 2)
                             if whole["customers"] else 0.0,
            "accounts_pct": round(mine["accounts"] / whole["accounts"] * 100, 2)
                            if whole["accounts"] else 0.0,
            "exposure_pct": round(
                mine["exposure_sar"] / whole["exposure_sar"] * 100, 2)
                if whole["exposure_sar"] else 0.0,
            "parent": whole,
        }
    return out


def _trend(months: list[str], *, product: str = "", classification: str = "",
           sub_product: str = "") -> list[dict[str, Any]]:
    """The three six-month series every card carries, one point per month."""
    key = (tuple(months), product, classification, sub_product)
    held = _SERIES.get(key)
    if held is not None:
        return held
    points: list[dict[str, Any]] = []
    for month in months:
        try:
            frame = _where(S.read(month), product=product,
                           classification=classification,
                           sub_product=sub_product)
        except FileNotFoundError:
            continue
        counts = _counts(frame)
        points.append({
            "month": month,
            "ews_score": counts["ews_score"],
            "severity": counts["severity_band"],
            "customers_warned": counts["customers_warned"],
            "current_bad": counts["current_bad"],
            "forward_risk": counts["forward_risk"],
            "high_or_critical": counts["high_or_critical"],
            "odr_pct": counts["odr_pct"],
            "default_entries": counts["default_entries"],
            "exposure_warned_sar": counts["exposure_warned_sar"],
        })
    if len(_SERIES) > 200:
        _SERIES.clear()
    _SERIES[key] = points
    return points


def _top_reasons(frame: Any, limit: int = 5,
                 before: Any = None) -> list[dict[str, Any]]:
    """The triggers behind a population, most customers first."""
    out: list[dict[str, Any]] = []
    if not len(frame):
        return out
    for trigger in M.evaluated_triggers():
        column = f"trg_{trigger.key}_fired"
        if column not in frame.columns:
            continue
        hit = frame[frame[column].fillna(False)]
        if not len(hit):
            continue
        was = 0
        if before is not None and len(before) and column in before.columns:
            was = _int(before[before[column].fillna(False)]["customer_id"]
                       .nunique())
        customers = _int(hit["customer_id"].nunique())
        layer = M.layer_of_trigger(trigger.key)
        sub = M.sublayer_of_trigger(trigger.key)
        out.append({
            "key": trigger.key,
            "reason_code": trigger.reason_code,
            "name": trigger.name,
            "severity": trigger.severity,
            "layer": layer.key if layer else "",
            "layer_name": layer.name if layer else "",
            "sublayer": sub.key if sub else "",
            "sublayer_name": sub.name if sub else "",
            "customers": customers,
            "facilities": _int(len(hit)),
            "exposure_sar": _money(hit["gross_carrying_amount_sar"].sum()),
            "previous_customers": was,
            "change": customers - was,
        })
    out.sort(key=lambda row: -row["customers"])
    return out[:limit]


# ------------------------------------------------------------- commentary

def commentary(label: str, now: dict[str, Any], was: dict[str, Any] | None,
               layers_now: dict[str, float], layers_was: dict[str, float],
               reasons: list[dict[str, Any]]) -> str:
    """What changed, in English, built from the computed movements.

    Every clause comes from a figure above it. There is no template with a
    name dropped into it: a population that did not move says so, the layers
    named as drivers are the layers that moved WITH the score, and anything
    that pulled the other way is reported as that rather than as a driver.
    """
    if was is None:
        return (f"{label} scores {now['ews_score']:.1f} "
                f"({now['severity_band'].title()}) with "
                f"{now['customers_warned']:,} customers warned. There is no "
                "prior month in the domain to compare it with.")

    parts: list[str] = []
    moved = now["ews_score"] - was["ews_score"]
    if was["severity_band"] != now["severity_band"]:
        parts.append(
            f"{label} moved from {was['severity_band'].title()} to "
            f"{now['severity_band'].title()}, with the Early Warning Score at "
            f"{now['ews_score']:.1f} against {was['ews_score']:.1f} last month")
    elif abs(moved) < 0.05:
        parts.append(f"{label} is unchanged at {now['ews_score']:.1f} "
                     f"({now['severity_band'].title()})")
    else:
        parts.append(
            f"{label} {'rose' if moved > 0 else 'fell'} from "
            f"{was['ews_score']:.1f} to {now['ews_score']:.1f} "
            f"({now['severity_band'].title()}), a move of {moved:+.1f}")

    movements = sorted(
        ((key, round(layers_now.get(key, 0.0) - layers_was.get(key, 0.0), 2))
         for key in (one.key for one in M.LAYERS)),
        key=lambda pair: -abs(pair[1]))
    material = [(k, d) for k, d in movements if abs(d) >= 0.05]

    def named(key: str) -> str:
        found = M.layer(key)
        return found.name.lower() if found else key

    if material and abs(moved) >= 0.05:
        same = [(k, d) for k, d in material if (d > 0) == (moved > 0)][:2]
        against = [(k, d) for k, d in material if (d > 0) != (moved > 0)][:1]
        if same:
            parts.append("driven by " + " and ".join(
                f"{named(k)} ({d:+.1f})" for k, d in same))
        if against:
            key, delta = against[0]
            parts.append(f"{named(key)} moved the other way ({delta:+.1f})")

    if reasons:
        worst = reasons[0]
        share = (worst["customers"] / now["customers_warned"] * 100
                 if now["customers_warned"] else 0.0)
        moved_by = worst["change"]
        clause = (f"the largest single signal is {worst['name'].lower()}, on "
                  f"{worst['customers']:,} of the {now['customers_warned']:,} "
                  f"warned customers ({share:.0f}%)")
        if moved_by:
            clause += f", {moved_by:+,} on last month"
        parts.append(clause)

    # Broad or concentrated, measured rather than asserted.
    if now["customers_warned"] and reasons:
        top_three = sum(r["customers"] for r in reasons[:3])
        concentration = top_three / max(1, sum(r["customers"] for r in reasons))
        parts.append(
            "the deterioration is concentrated: the top three signals carry "
            f"{concentration:.0%} of the warned population"
            if concentration >= 0.75 else
            "the deterioration is broad rather than concentrated in one "
            "signal")

    counts: list[str] = []
    if now["current_bad"] != was["current_bad"]:
        counts.append(f"customers already bad went from {was['current_bad']:,} "
                      f"to {now['current_bad']:,}")
    if now["forward_risk"] != was["forward_risk"]:
        counts.append("customers still performing but at high forward risk "
                      f"went from {was['forward_risk']:,} to "
                      f"{now['forward_risk']:,}")
    if now["odr_pct"] or was["odr_pct"]:
        counts.append(
            f"the default-entry rate is {now['odr_pct']:.2f}% against "
            f"{was['odr_pct']:.2f}% last month")

    said = ". ".join(part[0].upper() + part[1:] for part in parts) + "."
    if counts:
        # These clauses are written to be joined with semicolons, so the first
        # of them starts a sentence and has to be capitalised: the screen was
        # reading "... in one signal. customers still performing but at high
        # forward risk went from 27 to 28".
        tail = "; ".join(counts)
        said += " " + tail[0].upper() + tail[1:] + "."
    return said


# ------------------------------------------------------------- the levels

#: Whole answers, keyed by what was asked. The portfolio screen counts every
#: customer in seven months across four products — nine seconds of arithmetic
#: over an immutable panel, given to every reader who opens the page. Held
#: here, and dropped with the panel in `S.forget()`.
_ANSWERS: dict[tuple[Any, ...], dict[str, Any]] = {}


def _held(key: tuple[Any, ...], make: Any) -> dict[str, Any]:
    """`make()`, computed once per key and copied out.

    Copied because the answer leaves this module and a caller that edited one
    in place would edit everybody's.

    Every caller keys on the RESOLVED month. Keyed on the month as asked for,
    "" and "2026-08" are two entries for one answer: the warm-up asks for the
    default and the screen asks for the month it resolved to, so start-up
    computed every level twice over and a reader arriving in the first seconds
    waited for the second computation anyway. `_at` maps both onto the month
    actually read.
    """
    import copy

    answer = _ANSWERS.get(key)
    if answer is None:
        answer = make()
        if len(_ANSWERS) > 60:
            _ANSWERS.clear()
        _ANSWERS[key] = answer
    return copy.deepcopy(answer)


def warm() -> None:
    """Compute the landing figures before anybody asks for them.

    Every level a reader can reach in two clicks: total retail, the four
    products, and both classifications inside each of them.
    """
    portfolio()
    for code in M.ALL_PRODUCTS:
        product(code)
        for one in M.CLASSIFICATIONS:
            classification(code, one.code)


def portfolio(month: str = "") -> dict[str, Any]:
    """Total retail: the headline, and one card per product."""
    return _held(("portfolio", _at(month)), lambda: _portfolio(month))


def _portfolio(month: str = "") -> dict[str, Any]:
    every = S.panel_months()
    if not every:
        return {"available": False,
                "because": ("The Early Warning Score domain has not been "
                            "built. Run "
                            "scripts/bootstrap_retail_installation.py.")}
    at = _at(month)
    index = every.index(at)
    earlier = every[index - 1] if index else ""
    frame = S.read(at)
    before = S.read(earlier) if earlier else None

    head = _counts(frame)
    was = _counts(before) if before is not None else None
    months = S.window(at, S.TREND_MONTHS)

    return {
        "available": True,
        "domain": S.DOMAIN,
        "domain_name": S.DOMAIN_NAME,
        "month": at,
        "previous_month": earlier,
        "months": every,
        "model_version": M.EWS_MODEL_VERSION,
        "panel_version": S.EWS_PANEL_VERSION,
        "rulebook_version": _text(frame["rulebook_version"].iloc[0])
                            if len(frame) else "",
        "headline": head,
        "previous": was,
        "movement": {
            "ews_score": round(head["ews_score"] - was["ews_score"], 3),
            "customers_warned": head["customers_warned"] - was["customers_warned"],
            "current_bad": head["current_bad"] - was["current_bad"],
            "forward_risk": head["forward_risk"] - was["forward_risk"],
            "high_or_critical": head["high_or_critical"] - was["high_or_critical"],
        } if was else None,
        "layers": _layer_means(frame),
        "trend": _trend(months),
        "products": [_product_card(code, at, frame, before, months)
                     for code in M.ALL_PRODUCTS],
        # So a filter chip can say "Signature Card" rather than CC_SIGNATURE.
        "sub_product_labels": dict(M.SUB_PRODUCT_LABELS),
        "definitions": {
            "current_bad": S.CURRENT_BAD_RULE,
            "forward_risk": S.FORWARD_RISK_RULE,
            "odr": S.ODR_DEFINITION,
            "warning_cutoff": (
                f"A customer is warned at an Early Warning Score of "
                f"{M.SCALE.warning_cutoff:g} or above."),
        },
        "synthetic": True,
        "disclaimer": M.DISCLAIMER,
    }


def _product_card(code: str, at: str, frame: Any, before: Any,
                  months: list[str]) -> dict[str, Any]:
    rows = _where(frame, product=code)
    was_rows = _where(before, product=code) if before is not None else None
    head = _counts(rows)
    was = _counts(was_rows) if was_rows is not None and len(was_rows) else None
    layers_now = _layer_means(rows)
    layers_was = (_layer_means(was_rows)
                  if was_rows is not None and len(was_rows) else {})
    reasons = _top_reasons(rows, 5, was_rows)
    label = (_text(rows["product_label"].iloc[0]) if len(rows)
             else code.replace("_", " ").title())
    return {
        "product_code": code,
        "product_label": label,
        "month": at,
        **head,
        "previous": was,
        "movement": {
            "ews_score": round(head["ews_score"] - was["ews_score"], 3),
            "customers_warned": head["customers_warned"] - was["customers_warned"],
            "current_bad": head["current_bad"] - was["current_bad"],
            "forward_risk": head["forward_risk"] - was["forward_risk"],
            "odr_pct": round(head["odr_pct"] - was["odr_pct"], 4),
        } if was else None,
        "layers": layers_now,
        "layer_movement": {k: round(v - layers_was.get(k, 0.0), 3)
                           for k, v in layers_now.items()} if layers_was else {},
        "weights": M.weights_for(code),
        "emphasis": M.PRODUCT_EMPHASIS.get(code, ""),
        "trend": _trend(months, product=code),
        "top_reasons": reasons,
        "commentary": commentary(label, head, was, layers_now, layers_was,
                                 reasons),
        "sub_products": [s.code for s in M.sub_products_of(code)],
    }


def product(code: str, month: str = "") -> dict[str, Any]:
    """One product: its own headline, and a card per sub-product."""
    return _held(("product", str(code).upper(), _at(month)),
                 lambda: _product(code, month))


def _product(code: str, month: str = "") -> dict[str, Any]:
    every = S.panel_months()
    if not every:
        return {"available": False, "because": "The domain has not been built."}
    at = _at(month)
    index = every.index(at)
    earlier = every[index - 1] if index else ""
    whole = S.read(at)
    whole_before = S.read(earlier) if earlier else None
    wanted = str(code).upper()

    frame = _where(whole, product=wanted)
    if not len(frame):
        return {"available": False, "because": f"{wanted} is not in the book."}
    before = (_where(whole_before, product=wanted)
              if whole_before is not None else None)
    months = S.window(at, S.TREND_MONTHS)

    head = _counts(frame)
    was = _counts(before) if before is not None and len(before) else None
    layers_now = _layer_means(frame)
    layers_was = (_layer_means(before)
                  if before is not None and len(before) else {})
    reasons = _top_reasons(frame, 5, before)
    label = _text(frame["product_label"].iloc[0])

    # --- the classification cards: Salaried and Non-Salaried, §5
    #
    # The first cut inside a product, and the one a retail committee reads
    # first, because the two halves of a book behave differently under the
    # same shock. Each carries its materiality against the product and
    # against total Retail, on customers, accounts and exposure.
    whole_retail = S.read(at)
    classes = []
    for one in M.CLASSIFICATIONS:
        rows = _where(frame, classification=one.code)
        if not len(rows):
            continue
        was_rows = (_where(before, classification=one.code)
                    if before is not None else None)
        head_one = _counts(rows)
        was_one = (_counts(was_rows)
                   if was_rows is not None and len(was_rows) else None)
        layers_one = _layer_means(rows)
        layers_one_was = (_layer_means(was_rows)
                          if was_rows is not None and len(was_rows) else {})
        reasons_one = _top_reasons(rows, 5, was_rows)
        classes.append({
            "classification": one.code,
            "classification_label": one.label,
            "meaning": one.meaning,
            "derivation": one.derivation,
            "product_code": wanted,
            "product_label": label,
            "month": at,
            **head_one,
            "previous": was_one,
            "movement": {
                "ews_score": round(head_one["ews_score"]
                                   - was_one["ews_score"], 3),
                "customers_warned": (head_one["customers_warned"]
                                     - was_one["customers_warned"]),
                "current_bad": head_one["current_bad"] - was_one["current_bad"],
                "forward_risk": (head_one["forward_risk"]
                                 - was_one["forward_risk"]),
                "odr_pct": round(head_one["odr_pct"] - was_one["odr_pct"], 4),
            } if was_one else None,
            "layers": layers_one,
            "materiality": _materiality(
                rows, {"product": frame, "retail": whole_retail}),
            "salary_transfer_pct": _salary_transfer_pct(rows),
            "trend": _trend(months, product=wanted, classification=one.code),
            "top_reasons": reasons_one,
            "sub_products": [s.code for s in M.sub_products_of(wanted)],
            "commentary": commentary(f"{label} — {one.label}", head_one,
                                     was_one, layers_one, layers_one_was,
                                     reasons_one),
        })
    classes.sort(key=lambda card: -card["ews_score"])

    cards = []
    for sub in M.sub_products_of(wanted):
        rows = _where(frame, sub_product=sub.code)
        sub_before = (_where(before, sub_product=sub.code)
                      if before is not None else None)
        sub_head = _counts(rows)
        sub_was = (_counts(sub_before)
                   if sub_before is not None and len(sub_before) else None)
        sub_layers = _layer_means(rows)
        sub_layers_was = (_layer_means(sub_before)
                          if sub_before is not None and len(sub_before) else {})
        sub_reasons = _top_reasons(rows, 5, sub_before)
        cards.append({
            "sub_product": sub.code,
            "sub_product_label": sub.label,
            "meaning": sub.meaning,
            "derivation": sub.derivation,
            "month": at,
            **sub_head,
            "previous": sub_was,
            "movement": {
                "ews_score": round(sub_head["ews_score"] - sub_was["ews_score"], 3),
                "customers_warned": (sub_head["customers_warned"]
                                     - sub_was["customers_warned"]),
                "current_bad": sub_head["current_bad"] - sub_was["current_bad"],
                "forward_risk": (sub_head["forward_risk"]
                                 - sub_was["forward_risk"]),
                "odr_pct": round(sub_head["odr_pct"] - sub_was["odr_pct"], 4),
            } if sub_was else None,
            "layers": sub_layers,
            "share_of_product_exposure_pct": round(
                sub_head["exposure_sar"] / head["exposure_sar"] * 100, 2)
                if head["exposure_sar"] else 0.0,
            "materiality": _materiality(
                rows, {"product": frame, "retail": whole_retail}),
            "trend": _trend(months, product=wanted, sub_product=sub.code),
            "top_reasons": sub_reasons,
            "commentary": commentary(sub.label, sub_head, sub_was, sub_layers,
                                     sub_layers_was, sub_reasons),
        })
    cards.sort(key=lambda card: -card["ews_score"])

    return {
        "available": True,
        "month": at,
        "previous_month": earlier,
        "months": every,
        "product_code": wanted,
        "product_label": label,
        "headline": head,
        "previous": was,
        "movement": {
            "ews_score": round(head["ews_score"] - was["ews_score"], 3),
            "customers_warned": head["customers_warned"] - was["customers_warned"],
            "current_bad": head["current_bad"] - was["current_bad"],
            "forward_risk": head["forward_risk"] - was["forward_risk"],
            "odr_pct": round(head["odr_pct"] - was["odr_pct"], 4),
        } if was else None,
        "layers": layers_now,
        "weights": M.weights_for(wanted),
        "emphasis": M.PRODUCT_EMPHASIS.get(wanted, ""),
        "trend": _trend(months, product=wanted),
        "top_reasons": reasons,
        "commentary": commentary(label, head, was, layers_now, layers_was,
                                 reasons),
        "classifications": classes,
        "classification_labels": dict(M.CLASSIFICATION_LABELS),
        "sub_products": cards,
        "sub_product_taxonomy_version": M.SUB_PRODUCT_TAXONOMY_VERSION,
        "materiality": _materiality(frame, {"retail": whole_retail}),
        "definitions": {"current_bad": S.CURRENT_BAD_RULE,
                        "forward_risk": S.FORWARD_RISK_RULE,
                        "odr": S.ODR_DEFINITION},
        "synthetic": True,
    }


# ------------------------------------------------------- the customer list

def _cohort(people: Any, cohort: str) -> Any:
    warned = people[people["ews_score"] >= M.SCALE.warning_cutoff]
    if cohort == "current_bad":
        return people[people["current_bad_flag"].fillna(False)]
    if cohort == "forward_risk":
        return people[people["forward_risk_flag"].fillna(False)]
    if cohort == "critical":
        return warned[warned["ews_severity"] == "CRITICAL"]
    if cohort == "high":
        return warned[warned["ews_severity"] == "HIGH"]
    if cohort == "everyone":
        return people
    return warned


def classification(product_code: str, code: str, month: str = "") -> dict[str, Any]:
    """One classification inside one product, and the sub-products under it."""
    return _held(("classification", str(product_code).upper(),
                  str(code).upper(), _at(month)),
                 lambda: _classification(product_code, code, month))


def _classification(product_code: str, code: str,
                    month: str = "") -> dict[str, Any]:
    every = S.panel_months()
    if not every:
        return {"available": False, "because": "The domain has not been built."}
    at = _at(month)
    index = every.index(at)
    earlier = every[index - 1] if index else ""
    wanted = str(product_code).upper()
    which = str(code).upper()

    declared = next((one for one in M.CLASSIFICATIONS if one.code == which), None)
    if declared is None:
        return {"available": False,
                "because": f"{which} is not a governed classification."}

    whole = S.read(at)
    whole_before = S.read(earlier) if earlier else None
    product_rows = _where(whole, product=wanted)
    frame = _where(product_rows, classification=which)
    if not len(frame):
        return {"available": False,
                "because": f"No {declared.label} facilities in {wanted}."}
    before = (_where(whole_before, product=wanted, classification=which)
              if whole_before is not None else None)

    head = _counts(frame)
    was = _counts(before) if before is not None and len(before) else None
    layers_now = _layer_means(frame)
    layers_was = (_layer_means(before)
                  if before is not None and len(before) else {})
    reasons = _top_reasons(frame, 5, before)
    months = S.window(at, S.TREND_MONTHS)
    label = (_text(frame["product_label"].iloc[0]) if len(frame)
             else wanted.replace("_", " ").title())

    cards = []
    for sub in M.sub_products_of(wanted):
        rows = _where(frame, sub_product=sub.code)
        if not len(rows):
            continue
        sub_before = (_where(before, sub_product=sub.code)
                      if before is not None else None)
        sub_head = _counts(rows)
        sub_was = (_counts(sub_before)
                   if sub_before is not None and len(sub_before) else None)
        sub_layers = _layer_means(rows)
        sub_layers_was = (_layer_means(sub_before)
                          if sub_before is not None and len(sub_before) else {})
        sub_reasons = _top_reasons(rows, 5, sub_before)
        cards.append({
            "sub_product": sub.code,
            "sub_product_label": sub.label,
            "meaning": sub.meaning,
            "derivation": sub.derivation,
            "previous_label": M.SUB_PRODUCT_PREVIOUS_LABELS.get(sub.code, ""),
            "product_code": wanted,
            "classification": which,
            "classification_label": declared.label,
            "month": at,
            **sub_head,
            "previous": sub_was,
            "movement": {
                "ews_score": round(sub_head["ews_score"]
                                   - sub_was["ews_score"], 3),
                "customers_warned": (sub_head["customers_warned"]
                                     - sub_was["customers_warned"]),
                "current_bad": sub_head["current_bad"] - sub_was["current_bad"],
                "forward_risk": (sub_head["forward_risk"]
                                 - sub_was["forward_risk"]),
                "odr_pct": round(sub_head["odr_pct"] - sub_was["odr_pct"], 4),
            } if sub_was else None,
            "layers": sub_layers,
            # Three parents, because §6.1 asks what share of each this is.
            "materiality": _materiality(rows, {
                "classification": frame, "product": product_rows,
                "retail": whole}),
            "salary_transfer_pct": _salary_transfer_pct(rows),
            "trend": _trend(months, product=wanted, classification=which,
                            sub_product=sub.code),
            "top_reasons": sub_reasons,
            "commentary": commentary(sub.label, sub_head, sub_was, sub_layers,
                                     sub_layers_was, sub_reasons),
        })
    cards.sort(key=lambda card: -card["ews_score"])

    return {
        "available": True,
        "month": at,
        "previous_month": earlier,
        "months": every,
        "product_code": wanted,
        "product_label": label,
        "classification": which,
        "classification_label": declared.label,
        "meaning": declared.meaning,
        "derivation": declared.derivation,
        "headline": head,
        "previous": was,
        "movement": {
            "ews_score": round(head["ews_score"] - was["ews_score"], 3),
            "customers_warned": head["customers_warned"] - was["customers_warned"],
            "current_bad": head["current_bad"] - was["current_bad"],
            "forward_risk": head["forward_risk"] - was["forward_risk"],
            "odr_pct": round(head["odr_pct"] - was["odr_pct"], 4),
        } if was else None,
        "layers": layers_now,
        "weights": M.weights_for(wanted),
        "materiality": _materiality(
            frame, {"product": product_rows, "retail": whole}),
        "salary_transfer_pct": _salary_transfer_pct(frame),
        "trend": _trend(months, product=wanted, classification=which),
        "top_reasons": reasons,
        "commentary": commentary(f"{label} — {declared.label}", head, was,
                                 layers_now, layers_was, reasons),
        "sub_products": cards,
        "sub_product_taxonomy_version": M.SUB_PRODUCT_TAXONOMY_VERSION,
        "definitions": {"current_bad": S.CURRENT_BAD_RULE,
                        "forward_risk": S.FORWARD_RISK_RULE,
                        "odr": S.ODR_DEFINITION},
        "synthetic": True,
        "disclaimer": M.DISCLAIMER,
    }


def customers(month: str = "", *, product: str = "", classification: str = "",
              sub_product: str = "",
              cohort: str = "all", reason: str = "", layer: str = "",
              dpd_bucket: str = "", stage: str = "",
              score_min: float | None = None, score_max: float | None = None,
              behavioural_min: float | None = None,
              behavioural_max: float | None = None,
              search: str = "", limit: int = 50, offset: int = 0
              ) -> dict[str, Any]:
    """The customer list, with every filter §10 asks for."""
    import pandas as pd

    every = S.panel_months()
    if not every:
        return {"available": False, "customers": []}
    at = _at(month)
    whole = S.read(at)

    frame = _where(whole, product=product, classification=classification,
                   sub_product=sub_product)
    portfolio_exposure = _money(whole["gross_carrying_amount_sar"].sum())
    product_exposure = _money(
        _where(whole, product=product)["gross_carrying_amount_sar"].sum()
        if product else portfolio_exposure)
    sub_exposure = _money(frame["gross_carrying_amount_sar"].sum())

    if reason:
        column = f"trg_{reason}_fired"
        if column not in frame.columns:
            found = M.trigger_by_reason(reason)
            column = f"trg_{found.key}_fired" if found else ""
        if column and column in frame.columns:
            keep = set(frame[frame[column].fillna(False)]["customer_id"])
            frame = frame[frame["customer_id"].isin(keep)]
    if layer:
        found = M.layer(layer)
        if found:
            keep = set(frame[frame[found.score_column].fillna(0.0) > 0][
                "customer_id"])
            frame = frame[frame["customer_id"].isin(keep)]
    if dpd_bucket:
        frame = frame[frame["dpd_bucket"].astype(str) == str(dpd_bucket)]
    if stage not in ("", None):
        frame = frame[pd.to_numeric(frame["ifrs9_stage"], errors="coerce")
                      == float(stage)]
    if search:
        wanted = str(search).strip().upper()
        keys = (frame["customer_id"].fillna("").str.upper() + "|"
                + frame["facility_id"].fillna("").str.upper() + "|"
                + frame["customer_name"].fillna("").str.upper())
        frame = frame[keys.str.contains(wanted, regex=False)]

    people = _per_customer(frame)
    if len(people):
        if score_min is not None:
            people = people[people["ews_score"] >= float(score_min)]
        if score_max is not None:
            people = people[people["ews_score"] <= float(score_max)]
        if behavioural_min is not None:
            people = people[pd.to_numeric(people["behavioural_score"],
                                          errors="coerce") >= float(behavioural_min)]
        if behavioural_max is not None:
            people = people[pd.to_numeric(people["behavioural_score"],
                                          errors="coerce") <= float(behavioural_max)]

    sizes = {key: _int(_cohort(people, key)["customer_id"].nunique())
             if len(people) else 0 for key, _, _ in COHORTS}
    rows = (_cohort(people, cohort).sort_values(
        ["ews_score", "customer_exposure_sar"], ascending=False)
        if len(people) else people)
    total = _int(len(rows))
    page = rows.iloc[offset: offset + max(1, min(int(limit), 500))]

    # Six months of history for the three mini charts, fetched once for the
    # page rather than once per customer.
    series = _mini_series(list(page["customer_id"]), at) if len(page) else {}

    listed = [_customer_row(row, series.get(str(row["customer_id"]), []),
                            sub_exposure, product_exposure,
                            portfolio_exposure)
              for _, row in page.iterrows()]

    return {
        "available": True,
        "month": at,
        "product_code": str(product).upper() if product else "",
        "sub_product": str(sub_product).upper() if sub_product else "",
        "cohort": cohort,
        "cohorts": [{"key": key, "label": label, "definition": rule,
                     "customers": sizes.get(key, 0)}
                    for key, label, rule in COHORTS],
        "filters": {
            "reason": reason, "layer": layer, "dpd_bucket": dpd_bucket,
            "stage": stage, "score_min": score_min, "score_max": score_max,
            "behavioural_min": behavioural_min,
            "behavioural_max": behavioural_max, "search": search,
        },
        "dpd_buckets": sorted(
            {str(v) for v in whole["dpd_bucket"].dropna().unique()}),
        "total": total,
        "shown": len(listed),
        "limit": limit,
        "offset": offset,
        "customers": listed,
        "definitions": {"current_bad": S.CURRENT_BAD_RULE,
                        "forward_risk": S.FORWARD_RISK_RULE},
        "name_note": S.SYNTHETIC_NAME_NOTE,
        "bureau_note": M.BUREAU_RULE.proxy_label,
    }


def _mini_series(ids: list[str], at: str) -> dict[str, list[dict[str, Any]]]:
    """Six months of score, DPD and behavioural score, per customer.

    Three charts, not four: §11's locked rule is that there is no monthly
    bureau series to draw, because the bank does not receive a monthly file.
    Bureau appears on the row as its last observed value, its date and its
    age.
    """
    import pandas as pd

    wanted = set(str(one) for one in ids)
    out: dict[str, list[dict[str, Any]]] = {who: [] for who in wanted}
    for month in S.window(at, S.TREND_MONTHS):
        try:
            frame = S.read(month)
        except FileNotFoundError:
            continue
        rows = frame[frame["customer_id"].isin(wanted)]
        if not len(rows):
            continue
        grouped = rows.groupby("customer_id").agg(
            ews_score=("ews_score", "max"),
            dpd=("dpd", "max"),
            behavioural_score=("behavioural_score", "min"),
        )
        for who, row in grouped.iterrows():
            out.setdefault(str(who), []).append({
                "month": month,
                "ews_score": _num_or_none(row["ews_score"]) or 0.0,
                "dpd": _num_or_none(row["dpd"]),
                "behavioural_score": _num_or_none(row["behavioural_score"]),
            })
    del pd
    return out


def _customer_row(row: Any, series: list[dict[str, Any]], sub_exposure: float,
                  product_exposure: float, portfolio_exposure: float
                  ) -> dict[str, Any]:
    exposure = float(row.get("customer_exposure_sar") or 0.0)
    reasons = [
        {"code": _text(row.get(f"top_reason_code_{n}")),
         "name": _text(row.get(f"top_reason_name_{n}"))}
        for n in (1, 2, 3)
        if _text(row.get(f"top_reason_code_{n}"))]
    layers = {layer.key: _num_or_none(row.get(layer.score_column)) or 0.0
              for layer in M.LAYERS}
    worst = max(layers, key=lambda key: layers[key]) if layers else ""
    return {
        "customer_id": _text(row.get("customer_id")),
        "customer_name": _text(row.get("customer_name")),
        "product_code": _text(row.get("product_code")),
        "product_label": _text(row.get("product_label")),
        "sub_product": _text(row.get("sub_product")),
        "sub_product_label": _text(row.get("sub_product_label")),
        "facilities": _int(row.get("facilities")),
        "worst_facility_id": _text(row.get("facility_id")),
        "exposure_sar": round(exposure, 2),
        "share_of_sub_product_pct": round(exposure / sub_exposure * 100, 4)
                                    if sub_exposure else 0.0,
        "share_of_product_pct": round(exposure / product_exposure * 100, 4)
                                if product_exposure else 0.0,
        "share_of_portfolio_pct": round(exposure / portfolio_exposure * 100, 4)
                                  if portfolio_exposure else 0.0,
        "dpd": _num_or_none(row.get("customer_dpd")),
        "dpd_bucket": _text(row.get("dpd_bucket")),
        "ifrs9_stage": _num_or_none(row.get("customer_stage")),
        "current_bad": bool(row.get("current_bad_flag")),
        "forward_risk": bool(row.get("forward_risk_flag")),
        "ews_score": _num_or_none(row.get("ews_score")) or 0.0,
        "ews_severity": _text(row.get("ews_severity")),
        "ews_threshold": _num_or_none(row.get("ews_threshold")),
        "hard_trigger_applied": _text(row.get("hard_trigger_applied")),
        "behavioural_score": _num_or_none(row.get("behavioural_score")),
        "behavioural_score_change": _num_or_none(
            row.get("behavioural_score_change")),
        "behavioural_score_band": _text(row.get("behavioural_score_band")),
        "behavioural_score_absent_because": _text(
            row.get("behavioural_score_absent_because")),
        "application_score": _num_or_none(row.get("application_score")),
        "application_score_band": _text(row.get("application_score_band")),
        "bureau_score": _num_or_none(row.get("latest_bureau_score")),
        "bureau_band": _text(row.get("bureau_risk_band")),
        "bureau_last_observed": _text(row.get("bureau_last_observed_date")),
        "bureau_recency_months": _num_or_none(row.get("bureau_recency_months")),
        "layers": layers,
        "primary_layer": worst,
        "primary_layer_name": (M.layer(worst).name if M.layer(worst) else ""),
        "reasons": reasons,
        "triggers_fired": _int(row.get("customer_triggers")),
        "series": series,
    }


# ----------------------------------------------------------- one customer

def customer(customer_id: str, month: str = "") -> dict[str, Any]:
    """One customer, in full: layers, sublayers, triggers, action dimensions."""
    import pandas as pd

    every = S.panel_months()
    if not every:
        return {"available": False}
    at = _at(month)
    wanted = str(customer_id).strip().upper()

    history: list[dict[str, Any]] = []
    for period in every:
        try:
            frame = S.read(period)
        except FileNotFoundError:
            continue
        rows = frame[frame["customer_id"].astype(str).str.upper() == wanted]
        if not len(rows):
            continue
        worst = rows.loc[rows["ews_score"].idxmax()]
        history.append({
            "month": period,
            "ews_score": _num_or_none(rows["ews_score"].max()) or 0.0,
            "severity": M.band_of(float(rows["ews_score"].max())),
            "dpd": _num_or_none(rows["dpd"].max()),
            "ifrs9_stage": _num_or_none(rows["ifrs9_stage"].max()),
            "behavioural_score": _num_or_none(rows["behavioural_score"].min()),
            "exposure_sar": _money(rows["gross_carrying_amount_sar"].sum()),
            "current_bad": bool(rows["current_bad_flag"].any()),
            "forward_risk": bool(rows["forward_risk_flag"].any()),
            "triggers_fired": _int(rows["triggers_fired"].sum()),
            "layers": {layer.key: _num_or_none(rows[layer.score_column].max())
                       or 0.0 for layer in M.LAYERS},
            "reasons": [c for c in (
                _text(worst.get("top_reason_code_1")),
                _text(worst.get("top_reason_code_2")),
                _text(worst.get("top_reason_code_3"))) if c],
        })

    if not history:
        return {"available": False, "customer_id": wanted,
                "because": f"{wanted} is not in the Early Warning Score domain."}

    frame = S.read(at)
    rows = frame[frame["customer_id"].astype(str).str.upper() == wanted]
    if not len(rows):
        rows = frame.iloc[0:0]
    worst_row = rows.loc[rows["ews_score"].idxmax()] if len(rows) else None
    now = history[-1]
    was = history[-2] if len(history) > 1 else None

    portfolio_exposure = _money(frame["gross_carrying_amount_sar"].sum())
    code = _text(worst_row.get("product_code")) if worst_row is not None else ""
    sub = _text(worst_row.get("sub_product")) if worst_row is not None else ""
    product_exposure = _money(
        _where(frame, product=code)["gross_carrying_amount_sar"].sum())
    sub_exposure = _money(
        _where(frame, product=code, sub_product=sub)[
            "gross_carrying_amount_sar"].sum())
    exposure = _money(rows["gross_carrying_amount_sar"].sum())

    layer_detail = []
    for layer in M.LAYERS:
        value = _num_or_none(rows[layer.score_column].max()) or 0.0
        prior = (was or {}).get("layers", {}).get(layer.key)
        sublayers = []
        for sub_layer in layer.sublayers:
            score = _num_or_none(rows[sub_layer.score_column].max()) or 0.0
            sublayers.append({
                "key": sub_layer.key,
                "name": sub_layer.name,
                "purpose": sub_layer.purpose,
                "weight": sub_layer.weight,
                "score": score,
                "classifiers": [
                    {**_classifier_value(sub_layer, one, rows)}
                    for one in sub_layer.classifiers],
                "triggers": [
                    _trigger_value(one, rows) for one in sub_layer.triggers],
            })
        layer_detail.append({
            "key": layer.key,
            "name": layer.name,
            "purpose": layer.purpose,
            "kind": layer.kind,
            "weight": M.weights_for(code).get(layer.key, layer.weight),
            "weight_because": layer.weight_because,
            "refresh": layer.refresh,
            "score": value,
            "severity": M.band_of(value),
            "previous": prior,
            "movement": round(value - prior, 3) if prior is not None else None,
            "dynamic": layer.kind == "dynamic",
            "trend": [{"month": h["month"],
                       "value": h["layers"].get(layer.key, 0.0)}
                      for h in history[-S.TREND_MONTHS:]],
            "sublayers": sublayers,
            "top_sublayer": max(sublayers, key=lambda s: s["score"])["name"]
                            if sublayers else "",
        })

    facilities = [{
        "facility_id": _text(row.get("facility_id")),
        "product_label": _text(row.get("product_label")),
        "sub_product_label": _text(row.get("sub_product_label")),
        "exposure_sar": _money(row.get("gross_carrying_amount_sar")),
        "share_of_customer_pct": round(
            float(row.get("gross_carrying_amount_sar") or 0.0)
            / exposure * 100, 2) if exposure else 0.0,
        "dpd": _num_or_none(row.get("dpd")),
        "ifrs9_stage": _num_or_none(row.get("ifrs9_stage")),
        "ews_score": _num_or_none(row.get("ews_score")) or 0.0,
        "ews_severity": _text(row.get("ews_severity")),
        "months_on_book": _num_or_none(row.get("months_on_book")),
        "utilisation_ratio": _num_or_none(row.get("utilisation_ratio")),
        "secured": bool(row.get("secured_flag")),
        "triggers_fired": _int(row.get("triggers_fired")),
    } for _, row in rows.iterrows()]

    return {
        "available": True,
        "customer_id": wanted,
        "customer_name": _text(worst_row.get("customer_name"))
                         if worst_row is not None else "",
        "name_note": S.SYNTHETIC_NAME_NOTE,
        "month": at,
        "previous_month": was["month"] if was else "",
        "product_code": code,
        "product_label": _text(worst_row.get("product_label"))
                         if worst_row is not None else "",
        "sub_product": sub,
        "sub_product_label": _text(worst_row.get("sub_product_label"))
                             if worst_row is not None else "",
        "customer_segment": _text(worst_row.get("customer_segment"))
                            if worst_row is not None else "",
        "ews_score": now["ews_score"],
        "ews_severity": M.band_of(now["ews_score"]),
        "ews_threshold": M.SCALE.warning_cutoff,
        "movement": round(now["ews_score"] - was["ews_score"], 3)
                    if was else None,
        "current_bad": now["current_bad"],
        "forward_risk": now["forward_risk"],
        "hard_trigger_applied": _text(worst_row.get("hard_trigger_applied"))
                                if worst_row is not None else "",
        "hard_triggers": [
            {"key": h.key, "name": h.name, "condition": h.condition,
             "because": h.because} for h in M.HARD_TRIGGERS],
        "behavioural_score": now["behavioural_score"],
        "behavioural_score_previous": (was or {}).get("behavioural_score"),
        "behavioural_score_band": _text(worst_row.get("behavioural_score_band"))
                                  if worst_row is not None else "",
        "behavioural_score_absent_because": _text(
            worst_row.get("behavioural_score_absent_because"))
            if worst_row is not None else "",
        "application_score": _num_or_none(worst_row.get("application_score"))
                             if worst_row is not None else None,
        "application_score_band": _text(
            worst_row.get("application_score_band"))
            if worst_row is not None else "",
        "bureau": {
            "score": _num_or_none(worst_row.get("latest_bureau_score"))
                     if worst_row is not None else None,
            "band": _text(worst_row.get("bureau_risk_band"))
                    if worst_row is not None else "",
            "at_origination": _num_or_none(
                worst_row.get("bureau_score_at_origination"))
                if worst_row is not None else None,
            "last_observed": _text(worst_row.get("bureau_last_observed_date"))
                             if worst_row is not None else "",
            "recency_months": _num_or_none(
                worst_row.get("bureau_recency_months"))
                if worst_row is not None else None,
            "observed_this_month": bool(worst_row.get("bureau_observed"))
                                   if worst_row is not None else False,
            "external_delinquency": bool(
                worst_row.get("external_delinquency_flag"))
                if worst_row is not None else False,
            "enquiries": _num_or_none(worst_row.get("bureau_enquiry_count"))
                         if worst_row is not None else None,
            "rule": M.BUREAU_RULE.statement,
            "proxy_label": M.BUREAU_RULE.proxy_label,
            "no_trend_because": (
                "No monthly bureau trend is drawn, because the bank does not "
                "receive a monthly bureau file. What is shown is the last "
                "dated observation and how old it is."),
        },
        "exposure_sar": exposure,
        "facilities": facilities,
        "facility_count": len(facilities),
        "exposure_share": {
            "sub_product_pct": round(exposure / sub_exposure * 100, 3)
                               if sub_exposure else 0.0,
            "product_pct": round(exposure / product_exposure * 100, 3)
                           if product_exposure else 0.0,
            "portfolio_pct": round(exposure / portfolio_exposure * 100, 4)
                             if portfolio_exposure else 0.0,
        },
        "layers": layer_detail,
        "history": history,
        "trend": history[-S.TREND_MONTHS:],
        "reasons": [
            {"code": code_, "name": (M.trigger_by_reason(code_).name
                                     if M.trigger_by_reason(code_) else code_)}
            for code_ in now["reasons"]],
        "weights": M.weights_for(code),
        "definitions": {"current_bad": S.CURRENT_BAD_RULE,
                        "forward_risk": S.FORWARD_RISK_RULE},
        "model_version": M.EWS_MODEL_VERSION,
        "domain": S.DOMAIN,
    }


def _classifier_value(sub_layer: M.Sublayer, one: M.Classifier,
                      rows: Any) -> dict[str, Any]:
    value: Any = None
    if one.column in rows.columns and len(rows):
        raw = rows[one.column].iloc[0]
        value = _num_or_none(raw)
        if value is None:
            value = _text(raw)
    return {
        "key": one.key, "name": one.name, "column": one.column,
        "meaning": one.meaning, "source_class": one.source_class,
        "value": value, "absent_because": one.absent_because,
        "sublayer": sub_layer.key,
    }


def _trigger_value(one: M.Trigger, rows: Any) -> dict[str, Any]:
    """One trigger against one customer, with its six action dimensions."""
    fired_column = f"trg_{one.key}_fired"
    present = fired_column in rows.columns and len(rows)
    fired = bool(rows[fired_column].any()) if present else False
    where = (rows[rows[fired_column].fillna(False)].iloc[0] if fired
             else (rows.iloc[0] if present else None))

    def read(suffix: str) -> Any:
        if where is None:
            return None
        return where.get(f"trg_{one.key}_{suffix}")

    layer = M.layer_of_trigger(one.key)
    return {
        "key": one.key,
        "name": one.name,
        "reason_code": one.reason_code,
        "meaning": one.meaning,
        "severity": one.severity,
        "source_class": one.source_class,
        "column": one.column,
        "comparator_column": one.comparator,
        "threshold": one.threshold,
        "threshold_source": M.THRESHOLD_SOURCE,
        "unit": one.unit,
        "expression": M._expression(one),
        "products": list(one.products) or list(M.ALL_PRODUCTS),
        "rule_id": one.rule_id,
        "absent_because": one.absent_because,
        "available": not one.absent_because,
        "needs_new_observation": one.needs_new_observation,
        "layer": layer.key if layer else "",
        "fired": fired,
        "raw_value": _num_or_none(read("value")),
        "comparator_value": _num_or_none(read("comparator")),
        "contribution": _num_or_none(read("contribution")),
        "recommended_review": one.recommended_review,
        "action": {
            "direction": _text(read("direction")),
            "magnitude": _num_or_none(read("magnitude")),
            "velocity": _num_or_none(read("velocity")),
            "momentum": _text(read("momentum")),
            "persistence": _num_or_none(read("persistence")),
            "recency": _num_or_none(read("recency")),
        } if fired else None,
    }


# ---------------------------------------------------------------- signals

def signals(month: str = "", *, product: str = "", classification: str = "",
            sub_product: str = "",
            layer: str = "", severity: str = "", reason: str = "",
            limit: int = 500) -> dict[str, Any]:
    """The rules view: every trigger, what it caught, and what it means."""
    every = S.panel_months()
    if not every:
        return {"available": False, "signals": []}
    at = _at(month)
    index = every.index(at)
    frame = _where(S.read(at), product=product,
                   classification=classification, sub_product=sub_product)
    before = (_where(S.read(every[index - 1]), product=product,
                     sub_product=sub_product) if index else None)

    rows: list[dict[str, Any]] = []
    for trigger in M.all_triggers():
        one_layer = M.layer_of_trigger(trigger.key)
        one_sub = M.sublayer_of_trigger(trigger.key)
        column = f"trg_{trigger.key}_fired"
        hit = (frame[frame[column].fillna(False)]
               if column in frame.columns else frame.iloc[0:0])
        was = 0
        if before is not None and column in before.columns:
            was = _int(before[before[column].fillna(False)]["customer_id"]
                       .nunique())
        customers = _int(hit["customer_id"].nunique()) if len(hit) else 0
        rows.append({
            "key": trigger.key,
            "reason_code": trigger.reason_code,
            "name": trigger.name,
            "meaning": trigger.meaning,
            "severity": trigger.severity,
            "layer": one_layer.key if one_layer else "",
            "layer_name": one_layer.name if one_layer else "",
            "sublayer": one_sub.key if one_sub else "",
            "sublayer_name": one_sub.name if one_sub else "",
            "source_class": trigger.source_class,
            "column": trigger.column,
            "comparator_column": trigger.comparator,
            "threshold": trigger.threshold,
            "threshold_source": M.THRESHOLD_SOURCE,
            "unit": trigger.unit,
            "expression": M._expression(trigger),
            "products": list(trigger.products) or list(M.ALL_PRODUCTS),
            "rule_id": trigger.rule_id,
            "reason_template": trigger.reason_template,
            "recommended_review": trigger.recommended_review,
            "available": not trigger.absent_because,
            "absent_because": trigger.absent_because,
            "needs_new_observation": trigger.needs_new_observation,
            "hits": _int(len(hit)),
            "customers": customers,
            "previous_customers": was,
            "change": customers - was,
            "exposure_sar": _money(hit["gross_carrying_amount_sar"].sum())
                            if len(hit) else 0.0,
            "current_bad": _int(
                hit[hit["current_bad_flag"].fillna(False)]["customer_id"]
                .nunique()) if len(hit) else 0,
            "forward_risk": _int(
                hit[hit["forward_risk_flag"].fillna(False)]["customer_id"]
                .nunique()) if len(hit) else 0,
        })

    if layer:
        rows = [r for r in rows if r["layer"] == layer]
    if severity:
        rows = [r for r in rows if r["severity"] == severity.upper()]
    if reason:
        rows = [r for r in rows if r["reason_code"] == reason
                or r["key"] == reason]
    rows.sort(key=lambda r: -r["hits"])

    total_hits = sum(r["hits"] for r in rows)
    return {
        "available": True,
        "month": at,
        "months": every,
        "product_code": str(product).upper() if product else "",
        "sub_product": str(sub_product).upper() if sub_product else "",
        "filters": {"layer": layer, "severity": severity, "reason": reason},
        "signals": rows[:limit],
        "shown": min(len(rows), limit),
        "total_signals": len(rows),
        "total_hits": total_hits,
        "capped": len(rows) > limit,
        "by_layer": [
            {"layer": one.key, "layer_name": one.name,
             "hits": sum(r["hits"] for r in rows if r["layer"] == one.key)}
            for one in M.LAYERS],
        "by_severity": [
            {"severity": band,
             "hits": sum(r["hits"] for r in rows if r["severity"] == band)}
            for _, band in M.SEVERITY_BANDS],
        "domain": S.DOMAIN,
        "model_version": M.EWS_MODEL_VERSION,
    }


def signal(key: str, month: str = "") -> dict[str, Any]:
    """One trigger, with its own six-month history."""
    found = M.trigger(key) or M.trigger_by_reason(key)
    if found is None:
        return {"available": False, "because": f"No trigger named {key!r}."}
    at = _at(month)
    served = signals(at)
    row = next((r for r in served["signals"] if r["key"] == found.key), None)
    trend = []
    column = f"trg_{found.key}_fired"
    for month_ in S.window(at, S.TREND_MONTHS):
        try:
            frame = S.read(month_)
        except FileNotFoundError:
            continue
        hit = (frame[frame[column].fillna(False)]
               if column in frame.columns else frame.iloc[0:0])
        trend.append({
            "month": month_,
            "customers": _int(hit["customer_id"].nunique()) if len(hit) else 0,
            "hits": _int(len(hit)),
            "exposure_sar": _money(hit["gross_carrying_amount_sar"].sum())
                            if len(hit) else 0.0,
        })
    by_product = []
    frame = S.read(at)
    for code in M.ALL_PRODUCTS:
        rows = _where(frame, product=code)
        hit = (rows[rows[column].fillna(False)]
               if column in rows.columns else rows.iloc[0:0])
        by_product.append({
            "product_code": code,
            "product_label": (_text(rows["product_label"].iloc[0])
                              if len(rows) else code),
            "customers": _int(hit["customer_id"].nunique()) if len(hit) else 0,
            "exposure_sar": _money(hit["gross_carrying_amount_sar"].sum())
                            if len(hit) else 0.0,
        })
    return {"available": True, "month": at, **(row or {}),
            "trend": trend, "by_product": by_product}


# ------------------------------------------------------------- the model

def model(month: str = "") -> dict[str, Any]:
    """The whole model, with LIVE hit counts against each part of it."""
    at = _at(month)
    served = M.to_dict(deep=True)
    served["month"] = at
    served["months_scored"] = len(S.panel_months())
    served["domain"] = S.DOMAIN
    served["domain_name"] = S.DOMAIN_NAME
    served["panel_version"] = S.EWS_PANEL_VERSION
    served["build_date"] = at
    served["definitions"] = {
        "current_bad": S.CURRENT_BAD_RULE,
        "forward_risk": S.FORWARD_RISK_RULE,
        "odr": S.ODR_DEFINITION,
    }
    served["flow"] = [
        {"step": "Customer and facility data",
         "detail": f"The canonical retail book, {S.BOOK}."},
        {"step": "Classifiers",
         "detail": f"{len(M.all_classifiers())} stable context variables that "
                   "set how a trigger is read."},
        {"step": "Dynamic triggers",
         "detail": f"{len(M.evaluated_triggers())} of "
                   f"{len(M.all_triggers())} declared triggers are evaluated; "
                   "the rest state why the book cannot support them."},
        {"step": "Action dimensions",
         "detail": "Direction, magnitude, velocity, momentum, persistence and "
                   "recency, computed over the trigger's own history."},
        {"step": "Sub-layer scores",
         "detail": f"{len(M.all_sublayers())} sublayers: the worst "
                   "contribution in each, plus a tenth of the others."},
        {"step": "Four layer scores",
         "detail": "Each layer's sublayers combined on their weights."},
        {"step": "Overall Early Warning Score",
         "detail": "The four layers combined on the product's own weights, "
                   f"on a {M.SCALE.minimum:g}-{M.SCALE.maximum:g} scale."},
        {"step": "Severity and alert",
         "detail": f"Warned at {M.SCALE.warning_cutoff:g}; "
                   f"{len(M.SEVERITY_BANDS)} severity bands above it; "
                   f"{len(M.HARD_TRIGGERS)} overrides that floor the score."},
        {"step": "Reason codes and drill-down",
         "detail": "The three worst triggers, named on every screen that "
                   "shows the score."},
    ]
    served["lineage"] = {
        "domain": S.DOMAIN,
        "domain_name": S.DOMAIN_NAME,
        "source_dataset": S.BOOK,
        "months": S.panel_months(),
        "grain": "One row per customer per facility per month-end.",
        "model_config": "backend/retail/ews_model.py",
        "scoring_engine": "backend/retail/ews_score.py",
        "serving_layer": "backend/retail/ews_views.py",
        "rulebook": _rulebook_version(),
    }

    # Live counts, so the model screen cannot describe a trigger that is not
    # firing without saying so.
    try:
        frame = S.read(at)
    except FileNotFoundError:
        frame = None
    if frame is not None:
        counts = {}
        for trigger in M.all_triggers():
            column = f"trg_{trigger.key}_fired"
            counts[trigger.key] = (
                _int(frame[frame[column].fillna(False)]["customer_id"].nunique())
                if column in frame.columns else 0)
        for layer in served["layers"]:
            layer_total = 0
            for sub in layer["sublayers"]:
                sub_total = 0
                for trigger in sub["triggers"]:
                    trigger["customers"] = counts.get(trigger["key"], 0)
                    sub_total += trigger["customers"]
                sub["customers"] = sub_total
                layer_total += sub_total
            layer["customers"] = layer_total
    return served


def _rulebook_version() -> str:
    try:
        from backend.retail import ews as rulebook

        return rulebook.RULEBOOK_VERSION
    except Exception:  # noqa: BLE001
        return "unknown"


# ----------------------------------------------------------- the contract

def field_contract() -> dict[str, Any]:
    """What the domain actually holds, read from the parquet rather than told.

    Used by the Data Builder screen and by the acceptance test that checks the
    twenty snapshots carry the field contract rather than a promise of it.
    """
    every = S.panel_months()
    if not every:
        return {"available": False, "because": "The domain has not been built."}
    frame = S.read(every[-1])
    groups: dict[str, list[str]] = {
        "Identity and hierarchy": [], "Exposure and facility": [],
        "Credit status": [], "Existing scores": [], "Bureau classifier": [],
        "Affordability and cash flow": [], "Trigger inputs": [],
        "Action dimensions": [], "Sub-layer scores": [], "Layer scores": [],
        "Overall Early Warning Score": [], "Portfolio contribution": [],
        "Versions": [],
    }
    sublayer_columns = {sub.score_column for sub in M.all_sublayers()}
    layer_columns = {layer.score_column for layer in M.LAYERS}
    action_suffixes = tuple(f"_{d.key}" for d in M.ACTION_DIMENSIONS)
    for column in frame.columns:
        if column in sublayer_columns:
            groups["Sub-layer scores"].append(column)
        elif column in layer_columns:
            groups["Layer scores"].append(column)
        elif column.startswith("trg_") and column.endswith(action_suffixes):
            groups["Action dimensions"].append(column)
        elif column.startswith("trg_"):
            groups["Trigger inputs"].append(column)
        elif column.startswith("ews_") or column.startswith("top_reason") \
                or column in ("current_bad_flag", "forward_risk_flag",
                              "primary_deteriorating_layer",
                              "primary_deteriorating_layer_name",
                              "hard_trigger_applied", "triggers_fired"):
            groups["Overall Early Warning Score"].append(column)
        elif "bureau" in column or "external_" in column:
            groups["Bureau classifier"].append(column)
        elif column.endswith("_version"):
            groups["Versions"].append(column)
        elif any(word in column for word in
                 ("dpd", "stage", "default", "cure", "forbearance",
                  "restructur", "sicr", "collections", "impaired")):
            groups["Credit status"].append(column)
        elif any(word in column for word in
                 ("score", "band")) and "sub" not in column:
            groups["Existing scores"].append(column)
        elif any(word in column for word in
                 ("income", "salary", "obligation", "dbr", "debt", "inflow",
                  "outflow", "balance_buffer", "disposable", "indebted")):
            groups["Affordability and cash flow"].append(column)
        elif any(word in column for word in
                 ("exposure", "amount", "limit", "collateral", "ltv", "tenor",
                  "balloon", "utilis", "secured", "ead", "undrawn",
                  "contract_structure")):
            groups["Exposure and facility"].append(column)
        elif "share" in column:
            groups["Portfolio contribution"].append(column)
        else:
            groups["Identity and hierarchy"].append(column)
    return {
        "available": True,
        "domain": S.DOMAIN,
        "domain_name": S.DOMAIN_NAME,
        "months": every,
        "month_count": len(every),
        "grain": "One row per customer per facility per month-end.",
        "primary_keys": ["reporting_month", "customer_id", "facility_id"],
        "field_count": len(frame.columns),
        "rows_latest_month": _int(len(frame)),
        "groups": [{"group": name, "fields": sorted(fields),
                    "count": len(fields)}
                   for name, fields in groups.items() if fields],
        "synthetic": True,
    }
