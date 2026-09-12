"""
Writing the reading, from facts that are already true.

What separates this from a table narrator
-----------------------------------------
"Portfolio EWS increased from 45 to 53. Layer 2 is 62." is two figures a
reader can see for themselves, restated. What a credit officer needs is what
those figures mean: whether the movement is broad or concentrated, whether
it is live deterioration or standing weakness, which layer is leading and
what that implies about where the risk is being detected, what to do about
it, who owns that, and where to look next.

So this module does not template a sentence per figure. It reads the pack
and decides what is worth saying: an answer about a concentrated segment
reads differently from one about a broad-based move because the facts
differ, not because a different template was selected. Where the pack holds
nothing on a point, nothing is said about it — the shape of the answer
follows the evidence rather than a fixed skeleton with gaps filled in.

The rules it is built to keep
-----------------------------
Every claim names the node it came from, not just a number. No figure that
the pack does not carry. The source system is named when evidence is asked
for. A score movement is distinguished from a condition movement, always.
Explanations come from the reason code library rather than freehand, so
alert volumes stay reportable by driver. Recommendations come from the
action library only, each with an owner, a timeframe and a closing evidence
test. Every answer offers the specific next drill. The limits of the tool
are stated where the answer leans on them. And the assistant explains and
navigates — it never changes a score, and it escalates rather than resolving.
"""

from __future__ import annotations

from typing import Any

from backend.early_warning import actions as act
from backend.early_warning import escalation as esc
from backend.early_warning import facts as ff
from backend.early_warning import reasons
from backend.early_warning import triggers_v2 as trg
from backend.early_warning import units

BAND_WORD = {
    "VERY_HIGH": "very high", "HIGH": "high", "MEDIUM": "medium",
    "LOW": "low", "VERY_LOW": "very low",
}


class Composed:
    """One written answer, in the parts the answer surface renders."""

    def __init__(self, *, direct: str, interpretation: str = "",
                 points: list[str] | None = None,
                 drivers: list[dict[str, Any]] | None = None,
                 follow_ups: list[str] | None = None,
                 caveats: list[str] | None = None,
                 chart: dict[str, Any] | None = None) -> None:
        self.direct = direct
        self.interpretation = interpretation
        self.points = points or []
        self.drivers = drivers or []
        self.follow_ups = follow_ups or []
        self.caveats = caveats or []
        self.chart = chart or {}

    def to_dict(self) -> dict[str, Any]:
        return {"direct": self.direct, "interpretation": self.interpretation,
                "points": self.points, "drivers": self.drivers,
                "follow_ups": self.follow_ups, "caveats": self.caveats,
                "chart": self.chart}


# --------------------------------------------------------------- helpers


#: Money is written by `units.money()`, which sits below this module so the
#: escalation note can reach it too — `compose` imports `escalation`, so a
#: writer living here was unreachable from there and grew a second
#: convention. Re-exported under both names because this module refers to it
#: throughout and the report builders import it from here.
money = _money = units.money


def _sentence(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _list_of(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _band_phrase(score: float, band: str) -> str:
    return f"{score:.1f} ({BAND_WORD.get(band, band.lower())})"


def _action_line(action: act.Action) -> str:
    """A recommendation is not a recommendation without all four parts."""
    return (f"{action.action}. {action.owner_title}, {action.timeframe}. "
            f"Closes on: {action.evidence_to_close.lower()}.")


def _population_escalation_line(figures: dict[str, Any]) -> str:
    """Escalation for a population, which is not the same question as for an
    obligor.

    Routing an average is meaningless: a book whose exposure-weighted score
    is very low can still hold names that each route to the Head of Credit
    Risk. So a population answer reports how much sits above the escalation
    threshold rather than pretending the population itself has a rung.
    """
    high = figures.get("high_plus_count") or 0
    if not high:
        return ("Nothing in this population is at high severity or above, so "
                "no case is routed for decision this period.")
    return (f"{_count(high, 'obligor')} carry "
            f"{_money(figures.get('high_plus_exposure') or 0.0)} at high "
            f"severity or above and route individually: severity decides how "
            f"fast, exposure decides how high. Open a name to see its rung.")


def _escalation_line(band: str, exposure: float) -> str:
    """What the escalation matrix decides for ONE obligor, said as a reason
    rather than a rule.

    Severity decides urgency and materiality decides altitude, so the
    sentence names both — otherwise the reader cannot tell whether a
    different exposure would have gone somewhere else.
    """
    route = esc.route_for(band, exposure)
    to = route.get("escalated_to") or []
    if not to:
        return ("No escalation is required at this severity. It stays in "
                "periodic monitoring.")
    titles = []
    for level in to:
        for rung in esc.LADDER:
            if rung["level"] == level:
                titles.append(str(rung["role"]))
                break
    notified = route.get("notified") or []
    ack, decide = route.get("ack_sla_days"), route.get("decision_sla_days")
    timing = []
    if ack is not None:
        timing.append("same-day acknowledgement" if ack == 0 else f"{ack}-day acknowledgement")
    if decide is not None:
        timing.append(f"a {decide} working day decision")
    line = (f"At {BAND_WORD.get(band, band.lower())} severity on "
            f"{_money(exposure)} of exposure the decision sits with "
            f"{_list_of(titles)}")
    if timing:
        line += f", with {_list_of(timing)}"
    line += "."
    if notified:
        line += f" {_list_of(notified)} are notified in parallel."
    return line


def _live_or_structural_line(figures: dict[str, Any]) -> str:
    """Whether the weakness is happening now or has been there all along.

    It is not a nuance. An obligor whose transactional and arrears reading is
    clean while its classifier reading is very high has no live deterioration
    to contain, and containment is what most of the action library is for; an
    obligor deteriorating live against a sound structure needs the opposite.
    An action or an escalation that does not say which of the two this is
    invites the reader to apply the wrong half of the library.
    """
    lvs = figures.get("live_versus_structural") or {}
    reading = lvs.get("reading")
    if not reading:
        return ""
    ta, cl = lvs.get("ta_band", ""), lvs.get("classifier_band", "")
    if reading == "structural":
        return (f"This is structural rather than live: the transactional and "
                f"arrears reading is {BAND_WORD.get(ta, ta.lower())} while "
                f"the classifier reading is "
                f"{BAND_WORD.get(cl, cl.lower())}. There is no live "
                f"deterioration to contain, so the actions that matter are "
                f"the ones that re-test the structure rather than the ones "
                f"that stem an outflow.")
    if reading == "live":
        return (f"This is live rather than structural: the transactional and "
                f"arrears reading is {BAND_WORD.get(ta, ta.lower())} against "
                f"a classifier reading of {BAND_WORD.get(cl, cl.lower())}. "
                f"The behaviour is moving now, so containment comes before "
                f"any re-test of the structure.")
    return (f"The weakness is both live and structural — transactional and "
            f"arrears at {BAND_WORD.get(ta, ta.lower())}, classifier at "
            f"{BAND_WORD.get(cl, cl.lower())} — so containing the behaviour "
            f"does not resolve the position underneath it.")


def _count(number: Any, singular: str, plural: str = "") -> str:
    """A number and its noun, agreeing.

    "across 1 obligors" is the kind of thing a reader notices and a test
    does not, and it costs the whole answer its authority: a sentence that
    cannot count to one is not a sentence to act on.
    """
    try:
        value = int(round(float(number or 0)))
    except (TypeError, ValueError):
        value = 0
    word = singular if abs(value) == 1 else (plural or f"{singular}s")
    return f"{value:,} {word}"


def _as_at(pack: "ff.FactPack") -> str:
    """The published month this reading is of.

    Every figure in this product is a figure for ONE month, and an answer
    that does not say which one is an answer the reader cannot file, cannot
    reconcile and cannot repeat next month.
    """
    period = str(getattr(pack, "period", "") or "")
    return f"As at {period}, " if period else ""


def _drill(label: str) -> str:
    return label


# --------------------------------------------------------- portfolio-level


def portfolio(pack: ff.FactPack) -> Composed:
    f = pack.figures
    move = f.get("movement")
    conc = f.get("concentration") or {}

    direct = (f"{_as_at(pack)}the portfolio early warning score is "
              f"{_band_phrase(f['portfolio_ews'], f['band'])} on an "
              f"exposure-weighted basis, with "
              f"{_count(f['high_plus_count'], 'obligor')} of "
              f"{int(f['obligors']):,} at high severity or above carrying "
              f"{_money(f['high_plus_exposure'])}, "
              f"{f['high_plus_exposure_pct']:.1f}% of exposure.")

    paras: list[str] = []

    # Where the movement came from, and what that implies about detection.
    if move and move.get("layers"):
        lead = move["layers"][0]
        direction = "risen" if move["ews_change"] > 0 else "fallen"
        detail = (f"Since {move['from_period']} the score has {direction} by "
                  f"{abs(move['ews_change']):.1f} points. ")
        contributions = [
            f"{l['name']} contributed {l['points_contributed']:+.2f}"
            for l in move["layers"][:3] if abs(l["points_contributed"]) >= 0.01]
        if contributions:
            detail += _list_of(contributions) + ". "
        if lead["layer"] in ("L3", "L4") and lead["points_contributed"] > 0:
            detail += ("Deterioration is therefore being detected outside the "
                       "bank before it appears in account behaviour, which is "
                       "the framework working as designed rather than a data "
                       "problem — but it means the evidence needs verifying "
                       "at source rather than accepting.")
        elif lead["layer"] == "L1" and lead["points_contributed"] > 0:
            detail += ("The movement is led by the obligors' own banking "
                       "behaviour, which is the layer the bank sees first and "
                       "can act on without waiting for external confirmation.")
        elif lead["layer"] == "L2" and lead["points_contributed"] > 0:
            detail += ("The movement is led by credit fundamentals rather "
                       "than by fresh events, which points at the review "
                       "cycle rather than at incident response.")
        paras.append(detail.strip())

    # Whether this is a portfolio problem or a handful of names.
    if conc.get("high_plus_count"):
        if conc.get("is_concentrated"):
            names = _list_of([n["customer_name"] for n in conc["names"][:3]])
            paras.append(
                f"The risk is concentrated rather than systemic: the largest "
                f"{conc['top_n']} of the {conc['high_plus_count']} high-risk "
                f"obligors carry {conc['top_n_share_pct']:.1f}% of the high-risk "
                f"exposure, led by {names}. That makes this a name-level "
                f"review rather than a reason to tighten appetite across the "
                f"book — the population average is being pulled by those "
                f"names rather than by a common condition.")
        else:
            paras.append(
                f"The risk is spread rather than concentrated: the largest "
                f"{_count(conc['top_n'], 'name')} carry "
                f"{conc['top_n_share_pct']:.1f}% of "
                f"the high-risk exposure, so the {conc['high_plus_count']} "
                f"obligors at high or above do not reduce to a handful of "
                f"cases. A population action is likely to be more efficient "
                f"than a series of single-name escalations, and the diagnosis "
                f"tree will say whether they share a driver.")

    points: list[str] = []
    if f.get("dominant_layer_mix"):
        mix = ", ".join(f"{m['obligors']} at {m['layer']}"
                        for m in f["dominant_layer_mix"] if m["layer"] != "none")
        if mix:
            points.append(f"Where risk is being detected, by dominant layer: {mix}.")
    points.append(_population_escalation_line(f))

    follow_ups = [
        "Which layer moved most?",
        "Show me the obligors driving the increase.",
        "Run the diagnosis on the high-risk population.",
        "Group the portfolio by internal grade instead.",
    ]
    chart = {"kind": "trend", "reason": "a movement over time"} if f.get("trend") else {}
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=follow_ups, caveats=pack.caveats, chart=chart)


def level(pack: ff.FactPack) -> Composed:
    """The book cut by one field.

    Three things this reading has to say and did not. WHICH MONTH — every
    figure here is one month's, and an answer that does not date itself
    cannot be reconciled next month. HOW BIG THE WHOLE IS — "10 obligors at
    very high" means one thing out of 300 and another out of 30, and the
    reader cannot supply the denominator. WHAT IT RANKED BY — grouped by
    sector, "highest" can mean the exposure-weighted score, the mean, the
    external-intelligence score or the high-risk exposure, and they do not
    agree with each other.
    """
    f, rows = pack.figures, pack.rows
    label = f["level_label"].lower()
    leader = rows[0] if rows else None
    field_name = f["level_field"]
    ranked_by = str(f.get("ranked_by") or "portfolio_ews")
    measure_label = str(f.get("ranked_by_label")
                        or "exposure-weighted Early Warning score")
    # Grouping the book BY the severity band and then calling the worst band
    # "the weakest group" says nothing: VERY_HIGH is the weakest band by
    # definition. A distribution is a distribution, and reads as one.
    is_distribution = field_name == "ews_band"

    whole = (f"{_as_at(pack)}{_count(f.get('obligors'), 'obligor')} carrying "
             f"{_money(f.get('exposure') or 0.0)}")

    if not leader:
        direct = (f"{_as_at(pack)}the published month has no obligors to "
                  f"group by {label}. Nothing was filtered away and nothing "
                  f"failed — the population itself is empty.")
        return Composed(
            direct=direct,
            interpretation=("An empty population is a finding about the "
                            "month rather than about the book: check that "
                            "the period is the one you meant before reading "
                            "anything into it."),
            follow_ups=["Try the previous published month.",
                        "Show the whole book instead."],
            caveats=pack.caveats, chart={})

    if is_distribution:
        spread = _list_of([
            f"{_count(r['obligors'], 'obligor')} at "
            f"{BAND_WORD.get(str(r[field_name]), str(r[field_name]).lower())}"
            for r in sorted(rows, key=lambda r: (
                ff.BAND_ORDER.index(r[field_name])
                if r[field_name] in ff.BAND_ORDER else -1),
                reverse=True)])
        direct = (f"{whole} split across "
                  f"{_count(f.get('groups'), 'band')}: {spread}.")
    else:
        # "Weakest" belongs to the overall score. A layer score has no
        # weakest — the group with the most external intelligence firing is
        # the HIGHEST on that layer, and may be perfectly sound overall.
        superlative = ("the weakest is" if ranked_by in ("portfolio_ews",
                                                          "mean_ews")
                       else "the highest is")
        direct = (f"{whole}, grouped by {label} into "
                  f"{_count(f.get('groups'), 'group')}. Ranked by "
                  f"{measure_label}, {superlative} {leader[field_name]} at "
                  f"{_leading_value(leader, ranked_by)} across "
                  f"{_count(leader['obligors'], 'obligor')} and "
                  f"{_money(leader['exposure'])}.")

    paras: list[str] = []
    top = rows[:3]
    listed = _list_of([f"{r[field_name]} at {_leading_value(r, ranked_by)}"
                       for r in top])
    carrying = f.get("top_three_exposure", sum(r["exposure"] for r in top))
    if is_distribution:
        high = f.get("high_plus_count") or 0
        paras.append(
            f"{_count(high, 'obligor')} of "
            f"{int(f.get('obligors') or 0):,} sit at high severity or "
            f"above, carrying "
            f"{_money(f.get('high_plus_exposure') or 0.0)} — "
            f"{f.get('high_plus_exposure_pct', 0.0):.1f}% of the exposure in "
            f"this population. A distribution is a shape rather than a "
            f"ranking: what to read from it is how much of the book sits "
            f"above the escalation threshold, not which band is worst.")
    else:
        paras.append(
            f"The three highest by {measure_label} are {listed}, together "
            f"carrying {_money(carrying)}. The comparison worth making is "
            f"not the ranking but whether each group's figure reflects a "
            f"common condition or one or two names: a group whose high-risk "
            f"exposure sits in a minority of obligors is a single-name "
            f"problem wearing a group's label.")

    if field_name == "internal_rating" and f.get("divergence", {}).get("rows"):
        worst = f["divergence"]["rows"][0]
        paras.append(
            f"Grade and early warning diverge most at {worst['customer_name']}, "
            f"internally graded {worst['internal_rating']} and scoring "
            f"{worst['ews_score']:.1f} ({BAND_WORD.get(worst['ews_band'], '')}). "
            f"The grade is a classifier and moves on a review cycle; the score "
            f"is trigger-led and moves monthly, so they are not supposed to "
            f"track each other. Where they disagree materially either the "
            f"grade is stale or the trigger is a false positive, and the "
            f"disagreement is itself what to investigate — not a reason to "
            f"change the grade from this screen.")

    points = [_population_escalation_line(f)]
    follow_ups = ["What is common across the high-risk names?",
                  "Group by another field."]
    if not is_distribution:
        follow_ups.insert(0, f"Open {leader[field_name]}.")
    return Composed(direct=direct, interpretation=_sentence(paras),
                    points=points, follow_ups=follow_ups, caveats=pack.caveats,
                    chart={"kind": "comparison",
                           "reason": "a ranking across groups"})


def _leading_value(row: dict[str, Any], ranked_by: str) -> str:
    """One group's figure, written with the unit it is measured in.

    A bare "22.3" beside a sector name could be a score, a percentage or a
    count. The measure decides, and the sentence says so.
    """
    if ranked_by in ("portfolio_ews", "mean_ews"):
        return _band_phrase(float(row.get(ranked_by) or 0.0),
                            str(row.get("band") or ""))
    if ranked_by == "exposure" or ranked_by.endswith("_exposure"):
        return _money(float(row.get(ranked_by) or 0.0))
    if ranked_by in ("obligors", "high_plus_count"):
        return _count(row.get(ranked_by), "obligor")
    return f"{float(row.get(ranked_by) or 0.0):.1f} points"


def group(pack: ff.FactPack) -> Composed:
    f = pack.figures
    conc = f.get("concentration") or {}
    move = f.get("movement")
    layers = f.get("layers") or {}

    direct = (f"{_as_at(pack)}{pack.label} is at "
              f"{_band_phrase(f['portfolio_ews'], f['band'])}, "
              f"{_count(f['obligors'], 'obligor')} and {_money(f['exposure'])}, "
              f"{_count(f['high_plus_count'], 'obligor')} at high or above.")

    paras: list[str] = []
    if conc.get("high_plus_count"):
        if conc.get("is_concentrated"):
            paras.append(
                f"The weakness is concentrated rather than broad-based: "
                f"{_count(conc['high_plus_count'], 'obligor')} of "
                f"{int(f['obligors']):,} sit at "
                f"high or above and carry {conc['top_n_share_pct']}% of the "
                f"high-risk exposure. That distinction decides the response — "
                f"the evidence supports targeted borrower intervention rather "
                f"than a sector-wide limit action. If the same drivers begin "
                f"appearing across more obligors, it becomes a portfolio "
                f"question instead.")
        else:
            paras.append(
                f"The weakness is spread across the group rather than sitting "
                f"in one or two names: {_count(conc['high_plus_count'], 'obligor')} are "
                f"at high or above and no small subset dominates the exposure. "
                f"That points at a common condition, which is a sector or "
                f"appetite question rather than a series of workouts.")

    ta_layers = {k: v for k, v in layers.items() if k.endswith("_ta")}
    if ta_layers and max(ta_layers.values()) > 0:
        lead_key = max(ta_layers, key=lambda k: ta_layers[k])
        lead = lead_key.split("_")[0].upper()
        paras.append(
            f"{ff.LAYER_NAMES.get(lead, lead)} is the dominant source of "
            f"trigger-side risk here at {ta_layers[lead_key]:.1f}, so that is "
            f"where the evidence to verify sits.")

    if move and move.get("layers"):
        top = move["layers"][0]
        if abs(top["points_contributed"]) >= 0.01:
            paras.append(
                f"Since {move['from_period']} the group has moved "
                f"{move['ews_change']:+.1f} points, with {top['name']} "
                f"contributing {top['points_contributed']:+.2f}.")

    points = [_population_escalation_line(f)]
    weakest = pack.rows[0] if pack.rows else None
    follow_ups = ([f"Why is {weakest['customer_name']} flagged?",
                   "What is common across the high-risk names?",
                   "Download the segment report."] if weakest else [])
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=follow_ups, caveats=pack.caveats,
                    chart={"kind": "distribution", "reason": "a population breakdown"})


# ---------------------------------------------------------- borrower-level


def borrower(pack: ff.FactPack) -> Composed:
    f = pack.figures
    lvs = f["live_versus_structural"]
    drivers = f["drivers"]
    move = f.get("movement_1m") or f.get("movement_12m")

    direct = (
        f"{f['customer_name']} scores "
        f"{_band_phrase(f['ews_score'], f['ews_band'])}: an anchor of "
        f"{f['anchor_score']:.0f} from {BAND_WORD[lvs['ta_band']]} trigger and "
        f"accelerator read against {BAND_WORD[lvs['classifier_band']]} "
        f"classifier, then {f['net_notches']:+d} "
        f"{'notch' if abs(f['net_notches']) == 1 else 'notches'}.")

    paras: list[str] = []

    # What is actually driving it, named by node.
    if drivers:
        worst = drivers[0]
        line = (f"The worst node is {worst['code']} {worst['name']} at "
                f"{worst['score']:.0f} ({BAND_WORD.get(worst['band'], '')}): "
                f"{worst['reason'].lower()}.")
        corroborating = [d for d in drivers[1:3] if d["score"] >= 50]
        if corroborating:
            line += (" It is corroborated by " + _list_of(
                [f"{d['code']} {d['name'].lower()} at {d['score']:.0f}"
                 for d in corroborating]) + ".")
        paras.append(line)

    # Live deterioration against standing vulnerability — the distinction the
    # two dimensions exist to make.
    if lvs["reading"] == "structural":
        paras.append(
            f"This is standing vulnerability rather than fresh deterioration: "
            f"the classifier is {_band_phrase(lvs['classifier_score'], lvs['classifier_band'])} "
            f"while the trigger side is only "
            f"{_band_phrase(lvs['ta_score'], lvs['ta_band'])}. The obligor is "
            f"structurally weak without much moving right now, which is a "
            f"monitoring and appetite question rather than an incident.")
    elif lvs["reading"] == "live":
        paras.append(
            f"This is live deterioration rather than standing weakness: the "
            f"trigger side is {_band_phrase(lvs['ta_score'], lvs['ta_band'])} "
            f"against a classifier of "
            f"{_band_phrase(lvs['classifier_score'], lvs['classifier_band'])}. "
            f"Something is happening now to an obligor whose structural "
            f"position had not been the concern, so the priority is verifying "
            f"the event rather than re-reading the fundamentals.")
    else:
        paras.append(
            f"Both dimensions agree: live deterioration at "
            f"{_band_phrase(lvs['ta_score'], lvs['ta_band'])} is landing on an "
            f"obligor whose structural position is already "
            f"{_band_phrase(lvs['classifier_score'], lvs['classifier_band'])}. "
            f"That combination is what the framework is built to catch — the "
            f"breach is not a technical one on an otherwise sound name.")

    # Whether a movement was the obligor or the model.
    if move and move.get("ews_change"):
        if move["driven_by_notches"] and not move["condition_improved"]:
            paras.append(
                f"The score moved {move['ews_change']:+.0f} points between "
                f"{move['from_period']} and {move['to_period']}, but the "
                f"anchor is unchanged at {move['anchor_after']:.0f}: the whole "
                f"move came from notching, worth "
                f"{move['notch_change_points']:+.0f} points. Notches adjust "
                f"confidence in extending the anchor, not the severity behind "
                f"it. The underlying condition has not moved, and a reader who "
                f"treats this as an improvement will draw the wrong conclusion.")
        elif move["condition_improved"]:
            paras.append(
                f"The score moved {move['ews_change']:+.0f} points and the "
                f"anchor moved with it, from {move['anchor_before']:.0f} to "
                f"{move['anchor_after']:.0f}. That is a genuine change in the "
                f"underlying reading rather than a notch effect.")

    if f.get("overrides_applied"):
        paras.append(
            f"A hard override is in force ({_list_of(f['overrides_applied'])}), "
            f"so the final band is set by rule rather than by the roll-up.")

    # What to do, from the library, and what closes it.
    recommended = act.for_drivers([d["code"] for d in drivers])
    points: list[str] = []
    for action in recommended[:3]:
        points.append(_action_line(action))
    first = act.single_highest_value(recommended)
    if first is not None and len(recommended) > 1:
        points.append(
            f"If only one is taken: {first.action.lower()}. It preserves the "
            f"bank's position at the least cost, and the others remain "
            f"available afterwards.")
    points.append(_escalation_line(f["ews_band"], f["exposure"]))

    follow_ups = ["Show me the evidence behind that node.",
                  "What action should I take?",
                  "Draft the escalation note."]
    if move and move.get("ews_change"):
        follow_ups.insert(1, "Why did the score change?")
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    drivers=drivers, follow_ups=follow_ups, caveats=pack.caveats,
                    chart={"kind": "trend", "reason": "a score history"})


def _signal_title(key: str) -> str:
    """A signal under the name the framework gives it.

    `material_litigation` is a column name. "Material litigation" is what
    the workbook calls the signal, and a reader asking what events are
    driving a borrower is owed the second.
    """
    found = trg.BY_KEY.get(str(key))
    return found.name if found else str(key).replace("_", " ").capitalize()


def layer(pack: ff.FactPack) -> Composed:
    """One layer of one obligor, and the events inside it.

    "What external warning events are driving this borrower?" is a question
    about EVENTS. Answering it with the layer's score is answering with the
    total of the thing that was asked about, so the nodes that fired and the
    signals behind them are named — and the ones that did not are counted,
    because "one of five nodes is firing" is a different position from "four
    of five are".
    """
    f = pack.figures
    worst = f.get("worst_node")
    nodes = [n for n in (f.get("sub_categories") or [])
             if float(n.get("score") or 0.0) > 0]
    quiet = len(f.get("sub_categories") or []) - len(nodes)
    scores = [s for s in (f.get("ta_score"), f.get("c_score")) if s is not None]

    if not nodes:
        return Composed(
            direct=(f"{_as_at(pack)}nothing in {f['layer_name']} is firing "
                    f"for {f['customer_name']}. The layer scores "
                    f"{_list_of([f'{s:.1f}' for s in scores]) or '0.0'}."),
            interpretation=("An absent layer is a reading about where the "
                            "risk is not, and says nothing about the other "
                            "three."),
            follow_ups=["What is driving the score overall?",
                        "Show the layer breakdown."],
            caveats=pack.caveats)

    fired = _list_of([f"{n['code']} {n['name'].lower()}" for n in nodes])
    direct = (f"{_as_at(pack)}{f['layer_name']} scores "
              f"{_list_of([f'{s:.1f}' for s in scores])} for "
              f"{f['customer_name']}, on "
              f"{_count(len(nodes), 'node')} of "
              f"{len(f.get('sub_categories') or [])}: {fired}.")

    paras = []
    if worst:
        paras.append(
            f"The dominant node is {worst['code']} {worst['name']} at "
            f"{worst['score']:.0f}: {worst['reason'].lower()}. That is the "
            f"reading to verify before acting on the layer as a whole.")
    if quiet:
        paras.append(
            f"The other {_count(quiet, 'node')} in this layer are quiet, so "
            f"this is a single-node reading rather than a layer that has "
            f"broadly deteriorated.")

    # The events themselves, by name, with the score each carries.
    points: list[str] = []
    for node in nodes:
        for signal in (node.get("signals") or []):
            points.append(
                f"{_signal_title(signal.get('signal_key'))} — "
                f"{float(signal.get('signal_score') or 0.0):.0f} under "
                f"{node['code']} {node['name'].lower()}")
    action = act.for_subcategory(worst["code"]) if worst else None
    if action:
        points.append(_action_line(action))
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=["Show me the evidence behind that node.",
                                "What action should I take?"],
                    caveats=pack.caveats)


def evidence(pack: ff.FactPack) -> Composed:
    """What sits behind one node — never a headline, always the reading."""
    f = pack.figures
    direct = (f"{f['signal_key']} scored {f['signal_score']:.1f} in "
              f"{f.get('snapshot_month')}, from a severity band of "
              f"{f.get('trigger_severity_band')} "
              f"({f.get('trigger_severity_score'):.0f}) scaled by an "
              f"accelerator of {f.get('accelerator_multiplier'):.3f}.")
    paras = [
        f"It comes from {f.get('source_domain')} "
        f"({f.get('source_dataset')}), so that is where an analyst verifies "
        f"it. Signal class {f.get('decay_class')}, half-life "
        f"{f.get('half_life_days')} days.",
    ]
    if not f.get("cured"):
        paras.append(
            f"The decay factor is {f.get('decay_factor'):.2f} because the "
            f"condition remains uncured. Under the persistence hold the decay "
            f"clock only starts on cure, so age has not reduced this signal's "
            f"weight — it is {f.get('age_days')} days old and still carries "
            f"full weight.")
    else:
        paras.append(
            f"The condition cured {f.get('days_since_cure')} days ago, so the "
            f"decay clock has started and the factor has fallen to "
            f"{f.get('decay_factor'):.2f}.")
    bands = _list_of([
        f"magnitude {f.get('magnitude_band')}", f"velocity {f.get('velocity_band')}",
        f"persistence {f.get('persistence_band')}",
        f"repetition {f.get('repetition_band')}",
        f"corroboration {f.get('corroboration_band')}"])
    paras.append(f"Accelerator dimensions: {bands}.")
    return Composed(direct=direct, interpretation=_sentence(paras),
                    follow_ups=["What action should I take?",
                                "Show the other nodes in this layer."],
                    caveats=pack.caveats)


def movement(pack: ff.FactPack) -> Composed:
    f = pack.figures
    if f.get("unavailable"):
        return Composed(direct=f["unavailable"],
                        follow_ups=["Show the periods that are published."])
    lead = f["layers"][0]
    direct = (f"The score moved {f['ews_change']:+.1f} points between "
              f"{f['from_period']} and {f['to_period']}, from "
              f"{f['ews_before']:.1f} to {f['ews_after']:.1f}.")
    contributions = _list_of([
        f"{l['name']} {l['points_contributed']:+.2f}" for l in f["layers"]
        if abs(l["points_contributed"]) >= 0.01])
    paras = [f"By layer: {contributions}." if contributions else
             "No layer moved materially over this window."]
    if abs(lead["points_contributed"]) >= 0.01:
        paras.append(
            f"{lead['name']} accounts for most of it, moving "
            f"{lead['score_change']:+.1f} at a published weight of "
            f"{lead['weight']}.")
    return Composed(direct=direct, interpretation=_sentence(paras),
                    follow_ups=["Show the obligors behind that layer.",
                                "Run the diagnosis on the high-risk population."],
                    caveats=pack.caveats,
                    chart={"kind": "movement", "reason": "a period-on-period change"})


def comparison(pack: ff.FactPack) -> Composed:
    f = pack.figures
    left, right = f["left"], f["right"]
    direct = (f"{left['label']} is at {left['portfolio_ews']:.1f} and "
              f"{right['label']} at {right['portfolio_ews']:.1f}, a gap of "
              f"{abs(f['ews_gap']):.1f} points.")
    paras = [
        f"{f['weaker']} is the weaker of the two. The gap is worth reading "
        f"against size as well as score: {left['label']} carries "
        f"{_count(left['high_plus_count'], 'obligor')} at high or above against "
        f"{right['high_plus_count']} for {right['label']}, so a similar "
        f"average can rest on very different populations.",
    ]
    return Composed(direct=direct, interpretation=_sentence(paras),
                    follow_ups=[f"Open {f['weaker']}.",
                                "What is common across the high-risk names?"],
                    caveats=pack.caveats,
                    chart={"kind": "comparison", "reason": "two groups side by side"})


def action(pack: ff.FactPack) -> Composed:
    """What to do, keyed to the drivers rather than to the score.

    Led by the action rather than by the position, because the reader has
    already been told the position and is now asking what follows from it.
    """
    f = pack.figures
    drivers = f.get("drivers") or []
    # From the pack, so that every figure in the sentences below — the
    # timeframes especially — is one the pack vouches for.
    recommended = act.for_drivers([d["code"] for d in drivers])
    if not recommended:
        return Composed(
            direct=(f"No driver is currently scoring for {f.get('customer_name')}, "
                    f"so the library has nothing keyed to recommend. The "
                    f"position stays in periodic monitoring."),
            follow_ups=["Why is this obligor scored where it is?"],
            caveats=pack.caveats)
    first = act.single_highest_value(recommended)
    direct = (f"{len(recommended)} actions are indicated for "
              f"{f['customer_name']}, keyed to its drivers rather than to its "
              f"score. The priority is: {first.action.lower()}.")
    paras = [
        f"{first.action} is first because it preserves the bank's position at "
        f"the least cost — {first.owner_title} owns it, {first.timeframe}, and "
        f"it closes on {first.evidence_to_close.lower()}. The others gather "
        f"information or reduce exposure, and all of them remain available "
        f"afterwards. Taking the expensive one first forecloses nothing and "
        f"delays the one that does.",
    ]
    live = _live_or_structural_line(f)
    if live:
        paras.insert(0, live)
    points = [_action_line(a) for a in recommended[:4]]
    points.append(_escalation_line(f["ews_band"], f["exposure"]))
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    drivers=drivers,
                    follow_ups=["Draft the escalation note.",
                                "What evidence closes this case?",
                                "Show me the evidence behind that node."],
                    caveats=pack.caveats)


def escalation(pack: ff.FactPack) -> Composed:
    """Whom to tell, and why that rung rather than another."""
    f = pack.figures
    route = esc.route_for(f["ews_band"], f["exposure"])
    to = route.get("escalated_to") or []
    drivers = f.get("drivers") or []
    recommended = act.for_drivers([d["code"] for d in drivers])
    if not to:
        return Composed(
            direct=(f"No escalation is required. At "
                    f"{BAND_WORD.get(f['ews_band'], '')} severity "
                    f"{f['customer_name']} stays in periodic monitoring rather "
                    f"than being routed for a decision."),
            follow_ups=["What action should I take?"], caveats=pack.caveats)
    direct = _escalation_line(f["ews_band"], f["exposure"])
    worst = drivers[0] if drivers else None
    paras = [
        f"The question being put is not whether the obligor is good or bad; "
        f"it is what risk mitigation is proportionate to "
        f"{_money(f['exposure'])} of exposure. Severity decides how fast that "
        f"decision is needed and materiality decides how high it goes, which "
        f"is why a smaller exposure at the same severity would stop lower "
        f"down the ladder.",
    ]
    if worst:
        paras.append(
            f"The escalation should carry the driver rather than the score: "
            f"{worst['code']} {worst['name']} at {worst['score']:.0f}, "
            f"{worst['reason'].lower()}, with the recommended action and the "
            f"evidence that closes it.")
    live = _live_or_structural_line(f)
    if live:
        paras.append(live)
    points = [_action_line(a) for a in recommended[:2]]
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=["Draft the escalation note.",
                                "What action should I take?"],
                    caveats=pack.caveats)


#: What each named part of the model actually does, led by the answer to the
#: question rather than by a description of the framework. A reader asking
#: whether a supplier event is being counted twice needs the deduplication
#: rule, not a tour of the notch model — and a general explanation offered
#: in place of the specific one reads as reassurance, which is the one thing
#: a model explanation must never be.
def _methodology_aspect(aspect: str, f: dict[str, Any]) -> tuple[str, str]:
    """The direct answer and the reading, for the part that was asked about."""
    if aspect == "deduplication":
        return (
            "No. Signals sharing a causal chain are deduplicated before the "
            "sub-category score is formed: only the strongest member of the "
            "chain carries a score and the rest are recorded at zero.",
            "One deterioration reaching the bank through several signals is "
            "one deterioration. A supplier failure that shows up as a "
            "receivable-ageing signal, a utilisation signal and an external "
            "news signal is a single chain, and scoring all three would let "
            "the loudest event outrank a broader one that fired through a "
            "single route. The members are kept rather than discarded, so "
            "the evidence is still there to read — what is set to zero is "
            "their contribution, not their existence.")
    if aspect == "network":
        return (
            f"Connected names are scored by propagation, not by association: "
            f"a counterparty's deterioration reaches an obligor across at "
            f"most {f.get('max_propagation_hops')} hops "
            f"({f.get('max_propagation_hops_with_approval')} with approval), "
            f"and only across edges at confidence band "
            f"{f.get('min_edge_confidence_band')} or better.",
            "The transmitted amount depends on the relationship type, the "
            "number of hops and the confidence in the edge, so a weak link "
            "two hops away moves the score far less than a sole supplier one "
            "hop away. Edges below the confidence band are logged rather "
            "than scored, and an edge is revalidated every "
            f"{f.get('edge_revalidation_months')} months, because a "
            "relationship map nobody re-checks becomes the least reliable "
            "input in the model while still looking like data.")
    if aspect == "limits":
        return (
            "The weights, bands and multipliers are a documented starting "
            "calibration, not estimates fitted to default data, so the model "
            "orders obligors rather than predicting them.",
            "It says which names are deteriorating relative to their own "
            "baseline and to each other; it does not say how likely any of "
            "them is to default, and no output here is a probability. "
            "Layer 3 external intelligence is synthetic in this build and is "
            "marked as such wherever it is shown. Nothing in the tool "
            "changes a score or closes a case: an override is a documented "
            "control and an escalation is a decision the matrix routes to a "
            "person.")
    if aspect == "reliability":
        return (
            "It depends on the source tier and on corroboration, and the "
            "reading says which. A single tier-3 source is a reason to look, "
            "not a finding.",
            "Corroboration is one of the five accelerator dimensions, so a "
            "signal confirmed across independent sources scores higher than "
            "the same signal seen once — the model already discounts what it "
            "cannot corroborate rather than leaving the reader to. Layer 3 "
            "is synthetic in this build, which is stated on every answer "
            "that leans on it, and evidence answers name the source system "
            "so an analyst verifies the reading where it was produced rather "
            "than here.")
    if aspect == "notches":
        return (
            f"{len(f.get('notches') or [])} notch modifiers are applied to "
            f"the anchor, each worth {f.get('points_per_notch')} points, with "
            f"the net capped at plus or minus {f.get('net_notch_cap')}.",
            "The notches adjust for what the two dimension scores cannot see "
            "on their own, and the cap is what stops them from becoming a "
            "second scoring model: a score can move by them, but not far "
            "enough that the anchor stops being the thing that decides the "
            "band. That is also why a fall driven by the notches is not an "
            "improvement in the obligor — the anchor is where a condition "
            "change would show, and the two are reported separately for "
            "exactly that reason.")
    return ("", "")


def borrower_movement(pack: ff.FactPack) -> Composed:
    """Did this obligor improve? Answered, in the first sentence.

    Asked outright and given the obligor's current position instead, a
    reader takes the absence of a "no" for a "yes" — and this is the single
    question where that costs most, because a score can fall while the
    condition behind it worsens. The anchor is where a condition change
    shows; the notches adjust for what the two dimension scores cannot see
    on their own. Reporting them separately is the whole reason the
    distinction is computable at all, so the answer states which moved.
    """
    f = pack.figures
    year = f.get("movement_12m") or {}
    month = f.get("movement_1m") or {}
    move = year if year.get("ews_change") is not None else month
    if not move:
        return borrower(pack)

    change = float(move.get("ews_change") or 0.0)
    anchor_move = float(move.get("anchor_change") or 0.0)
    notch_points = float(move.get("notch_change_points") or 0.0)
    name = f["customer_name"]
    span = f"{move.get('from_period')} to {move.get('to_period')}"

    if change > 0:
        verdict = (f"No. {name}'s score has risen {change:+.1f} points from "
                   f"{span}, to {_band_phrase(f['ews_score'], f['ews_band'])}.")
    elif change < 0:
        # The expensive case: a fall that is not an improvement.
        verdict = (f"The score fell {abs(change):.1f} points from {span}, but "
                   f"that is not the same as the obligor improving."
                   if not move.get("condition_improved") else
                   f"Yes. The score fell {abs(change):.1f} points from {span} "
                   f"and the anchor fell with it, so the underlying condition "
                   f"eased rather than the adjustment moving.")
    else:
        verdict = (f"No. {name}'s score is unchanged at "
                   f"{_band_phrase(f['ews_score'], f['ews_band'])} across "
                   f"{span}.")

    paras: list[str] = []
    # Where the movement actually came from.
    if anchor_move or notch_points:
        parts = []
        if anchor_move:
            parts.append(
                f"the anchor moved {anchor_move:+.0f} points, which is the "
                f"underlying condition")
        if notch_points:
            parts.append(
                f"the notches moved {notch_points:+.0f} points, which is the "
                f"adjustment for what the two dimension scores cannot see on "
                f"their own")
        # "Of that" apportions a movement. Where the score did not move, the
        # components still did, and saying so is the more useful fact: it is
        # the difference between nothing happening and two things cancelling.
        paras.append(f"Of that, {_list_of(parts)}." if change else
                     f"Underneath the unchanged score {_list_of(parts)}.")
    elif not change:
        # Nothing moved, and neither component moved either. Saying so is the
        # useful fact: it separates a genuinely static position from two
        # things that cancelled, and the two call for different attention.
        held = f.get("overrides_applied") or []
        paras.append(
            f"Neither part moved: the anchor is unchanged at "
            f"{f.get('anchor_score', 0):.0f} and the notches are unchanged at "
            f"{f.get('net_notches', 0):+d}. This is a static position rather "
            f"than two movements that cancelled, so there is nothing recent "
            f"to investigate — what there is to act on is the level it has "
            f"been sitting at.")
        if held:
            # And where a rule is what holds it there, the rule is the thing
            # to read: the score cannot come down while it applies, however
            # the anchor and the notches move underneath it.
            paras.append(
                f"The level itself is set by rule rather than by the "
                f"roll-up: {_list_of(list(held))} "
                f"{'is' if len(held) == 1 else 'are'} in force. That is what "
                f"has to stop applying before the score can move at all.")

    # An override sets the band by rule, and when one is in force the anchor
    # and the notches do not add up to the movement. Saying "the anchor moved
    # +4 and the notches -16" about a +48 point rise, and stopping there,
    # presents an incomplete decomposition as a complete one — which is worse
    # than not decomposing it, because the reader has no reason to doubt it.
    overrides = f.get("overrides_applied") or []
    reconciles = abs((anchor_move + notch_points) - change) < 0.5
    if not reconciles and overrides:
        paras.append(
            f"The anchor and the notches do not account for where the score "
            f"ended up, and they are not meant to here: "
            f"{_list_of(list(overrides))} "
            f"{'is' if len(overrides) == 1 else 'are'} in force, so the final "
            f"band is set by rule rather than by the roll-up. The rule is the "
            f"thing to read, and it is the thing that has to stop applying "
            f"before the score can come down.")
    elif not reconciles:
        paras.append(
            "The anchor and the notches do not fully account for that "
            "movement, so a cap or a band floor is also acting on the score. "
            "Open the score composition to see which.")

    if move.get("driven_by_notches") and not move.get("condition_improved") \
            and reconciles:
        direction = "down" if notch_points < 0 else "up"
        paras.append(
            f"The notches are doing more of the work than the condition is, "
            f"and they are pulling the score {direction}. So the score "
            f"{'understates' if notch_points < 0 else 'overstates'} the "
            f"change in the obligor itself: the anchor moved "
            f"{anchor_move:+.0f}, and that is the number to read as the "
            f"condition. A band change driven by a notch is a reason to "
            f"check the notch reason, not evidence that the credit turned.")
    elif move.get("condition_improved"):
        paras.append(
            f"The anchor fell {abs(anchor_move):.0f} points, so this is a "
            f"change in the obligor rather than in the adjustment applied to "
            f"it. Confirm it holds for a second month before acting on it: "
            f"one month of relief is not a trend.")

    worst = (f.get("drivers") or [{}])[0]
    if worst.get("code"):
        paras.append(
            f"The position it is at is still driven by {worst['code']} "
            f"{worst['name']} at {worst['score']:.0f}.")
    # Whether the position is live or standing decides what a reader does
    # next as much as the direction of the movement does.
    live = _live_or_structural_line(f)
    if live:
        paras.append(live)

    return Composed(
        direct=verdict, interpretation=_sentence(paras),
        drivers=f.get("drivers") or [],
        follow_ups=["Show me the notch detail.",
                    "Show me the evidence behind that node.",
                    "What action should I take?"],
        caveats=pack.caveats)


def ambiguous_borrower(matched: str, found: list[dict[str, Any]]) -> Composed:
    """Eleven obligors share a name. That is a question, not an answer.

    Picking the weakest of them and answering as though it were the one
    asked about is a confident wrong answer, which costs more than asking.
    So the candidates are named with their positions — enough for the
    reader to choose without a second round trip — and the weakest is
    pointed out, because that is the one they most likely meant and the one
    that matters if they did not.
    """
    top = found[:6]
    worst = found[0]
    direct = (f"{_count(len(found), 'obligor')} carry the {matched.title()} name. "
              f"The weakest is {worst['customer_name']} at "
              f"{_band_phrase(worst['ews_score'], worst['ews_band'])} on "
              f"{money(worst['exposure'])}. Which one did you mean?")
    listed = _list_of([f"{r['customer_name']} at {r['ews_score']:.1f}"
                       for r in top])
    more = (f" and {len(found) - len(top)} more" if len(found) > len(top)
            else "")
    paras = [
        f"They are separate obligors rather than one group exposure, so "
        f"they are scored separately and none of their positions can be "
        f"read off another's: {listed}{more}. If the name is a group and "
        f"the exposures are related, that relationship belongs in the "
        f"network layer, where it is scored as propagation across "
        f"confidence-rated edges rather than assumed from a shared name.",
    ]
    return Composed(
        direct=direct, interpretation=_sentence(paras),
        drivers=[], follow_ups=[f"How is {r['customer_name']} doing?"
                                for r in top[:4]],
        caveats=["Naming an obligor in full, or opening it from the table, "
                 "answers about that obligor rather than about the name."])


def methodology(pack: ff.FactPack) -> Composed:
    """How the score is built, from the engine rather than from a page.

    Led by the part that was asked about, when one was, and followed by the
    general explanation — so the answer to the question comes first and the
    context comes after, rather than the reader having to find their question
    inside a description of the framework.
    """
    f = pack.figures
    aspect = f.get("aspect")
    if aspect:
        lead, reading = _methodology_aspect(str(aspect), f)
        if lead:
            return Composed(
                direct=lead, interpretation=reading,
                follow_ups=["How is the score built?",
                            "Show me the evidence behind a node.",
                            "What are the limits of this tool?"],
                caveats=pack.caveats)
    direct = (f"The score is built from {f['signals_scored']} scored signals "
              f"of {f['signals_total']} in the inventory, across "
              f"{f['sub_categories']} sub-category nodes, "
              f"{f['classifiers']} classifiers and {f['triggers']} triggers.")
    paras = [
        "Two questions are scored separately and never added together. What "
        "is happening now is the trigger and accelerator dimension: fresh "
        "deterioration measured against the obligor's own baseline, scaled by "
        "an accelerator and decayed by signal class. How vulnerable the "
        "obligor is is the classifier dimension: structural credit quality, "
        "reviewed periodically rather than re-scored daily. Within a "
        "sub-category, variables measuring the same underlying thing combine "
        "worst-of rather than averaging, because averaging three readings of "
        "default proximity dilutes the one that fired.",
        f"The two dimension scores are combined at the last step by reading a "
        f"published five-by-five matrix rather than through an equation, "
        f"producing an anchor. {len(f['notches'])} notch modifiers are then "
        f"applied, each worth {f['points_per_notch']} points and capped at a "
        f"net of plus or minus {f['net_notch_cap']}, before the caps and "
        f"overrides. Every number in a final score can be reconstructed by "
        f"hand from a published table, which is the constraint the framework "
        f"was built to meet.",
    ]
    weights = ", ".join(f"{k} {v}" for k, v in f["ta_layer_weights"].items())
    points = [f"Trigger and accelerator layer weights: {weights}.",
              "Classifier layer weights: " +
              ", ".join(f"{k} {v}" for k, v in f["classifier_layer_weights"].items()) + "."]
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=["Explain the notches.",
                                "Which signals were dropped and why?",
                                "Show the portfolio."],
                    caveats=pack.caveats)


def diagnosis(pack: ff.FactPack) -> Composed:
    """What the population has in common — and what that does not license.

    The reading and the limits arrive together on purpose. A driver tree
    presented without them invites exactly the use it cannot support: taking
    a leaf as a rule for the next obligor rather than a hypothesis about
    these ones.
    """
    f = pack.figures
    if not f.get("root"):
        return Composed(direct=f.get("reading", "There is nothing to describe."),
                        caveats=pack.caveats)
    root = f["root"]
    leaves = f.get("leaves") or []
    direct = (f"Across {_count(root['obligors'], 'obligor')} in {f['population']}, "
              f"the strongest partition is {f['strongest_split']}.")
    paras = [f["reading"]]
    if leaves:
        worst = leaves[0]
        paras.append(
            f"The action that follows is aimed at \"{worst['label']}\" — "
            f"{_count(worst['obligors'], 'obligor')} carrying "
            f"{_money(worst['exposure'])}, {worst['high_plus']} of them at "
            f"high or above. Confirm the hypothesis on those names before "
            f"acting on the population as a whole.")
    points = [
        f"Minimum leaf {_count(f['min_leaf'], 'obligor')} "
        f"({int(f['min_leaf_share'] * 100)}% of the population), depth "
        f"{f['max_depth']}.",
    ]
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=["Show me the obligors in that leaf.",
                                "Run the diagnosis on a segment instead."],
                    caveats=pack.caveats,
                    chart={"kind": "distribution",
                           "reason": "a population partition"})


def ranking(pack: ff.FactPack) -> Composed:
    """Which obligors — by name, in the order that matters.

    The reading a "which names?" question actually asks for, and the one the
    product did not have. Every other scope here answers a question about a
    POPULATION: what is it worth, how has it moved, what does it have in
    common. "Which obligors are High or Very High?" is not that question, and
    answering it with the portfolio's average score answers a different one
    while looking like an answer.

    Ordered by exposure at high severity rather than by score, because the
    reader asking which names drive a book is asking which ones matter, and a
    very high score on a small exposure does not.
    """
    f = pack.figures or {}
    rows = list(pack.rows or [])
    if not rows:
        return Composed(
            direct=("No obligor in this population meets that filter, so "
                    "there are no names to list."),
            interpretation=(
                "That is a finding rather than an empty result: the filter "
                "ran against the published month and matched nothing."),
            follow_ups=["Show the risk-band distribution.",
                        "Widen this to the whole book."],
            caveats=pack.caveats)

    total = f.get("high_plus_count")
    shown = len(rows)
    lead = rows[0]
    lead_name = str(lead.get("customer_name") or lead.get("customer_id") or "")
    exposure = sum(float(r.get("exposure") or 0) for r in rows)

    counted = (f"{_count(total, 'obligor')} in {pack.label} sit at high or above"
               if isinstance(total, (int, float)) and total
               else f"{_count(shown, 'obligor')} in {pack.label} match")
    direct = (
        f"{_as_at(pack)}{counted[0].lower() + counted[1:]}. The {shown} "
        f"largest by exposure are listed, led by "
        f"{lead_name} at "
        f"{_band_phrase(float(lead.get('ews_score') or 0), str(lead.get('ews_band') or ''))} "
        f"on {_money(float(lead.get('exposure') or 0))}; the {shown} together "
        f"carry {_money(exposure)}.")

    paras = [
        "They are ordered by exposure rather than by score: a very high score "
        "on a small line is a smaller problem than a high score on a large "
        "one, and the order a reader acts in follows the money."
    ]
    nodes = [str(r.get("dominant_subcategory") or "") for r in rows
             if r.get("dominant_subcategory")]
    if nodes:
        common = max(set(nodes), key=nodes.count)
        paras.append(
            f"{nodes.count(common)} of the {shown} share {common} as their "
            f"dominant sub-category, which is worth testing as a common "
            f"condition before treating them as unrelated cases.")
    else:
        paras.append(
            "No single sub-category dominates the list, so treat them as "
            "separate cases until a diagnosis says otherwise.")

    points = [
        f"{str(r.get('customer_name') or r.get('customer_id'))} — "
        f"{_band_phrase(float(r.get('ews_score') or 0), str(r.get('ews_band') or ''))}, "
        f"{_money(float(r.get('exposure') or 0))}"
        for r in rows[:10]]

    return Composed(
        direct=direct, interpretation=_sentence(paras), points=points,
        follow_ups=["Why is the first one flagged?",
                    "What should I do about these names?",
                    "Is this concentrated or broad-based?"],
        caveats=pack.caveats,
        # A ranked list is a table. A chart of ten bars sorted by the column
        # they are already sorted by adds nothing the list does not say.
        chart={})


def layer_population(pack: ff.FactPack) -> Composed:
    """The obligors one detection layer has fired for.

    A different question from "who is high risk", and the answer has to look
    different or the reader cannot tell which one they got. It names the
    layer, counts its population against the book, and says how many of the
    names rest on this layer alone — because a single-layer reading is the
    one to verify before acting, and leaving the reader to work that out from
    a table is leaving them to not work it out.
    """
    f = pack.figures or {}
    rows = list(pack.rows or [])
    described = str(f.get("layer_described") or f.get("layer") or "this layer")
    key = str(f.get("layer") or "").lower() + "_ta"

    if not rows:
        return Composed(
            direct=(f"{_as_at(pack)}no obligor in this population carries a "
                    f"live {described} signal. That is a reading, not an "
                    f"empty result: the layer was searched and nothing in it "
                    f"has fired and not yet decayed."),
            interpretation=(
                f"An absence here says where the risk is NOT being detected. "
                f"It does not say the book is sound — the other three layers "
                f"are scored separately and a name can be weak on all of "
                f"them with nothing showing on this one."),
            follow_ups=["Which obligors are High or Very High?",
                        "Show the distribution by risk band.",
                        "Which layer is carrying most of the book's risk?"],
            caveats=pack.caveats, chart={})

    count = int(f.get("obligors") or len(rows))
    lead = rows[0]
    alone = int(f.get("this_layer_alone") or 0)
    high = int(f.get("high_plus_count") or 0)

    # The label carries whatever the question narrowed the population to, so
    # the sentence says which population it is answering about rather than
    # leaving the reader to assume it is all of them.
    qualifier = str(pack.label or "")
    qualifier = qualifier.split(", ", 1)[1] if ", " in qualifier else ""
    direct = (
        f"{_as_at(pack)}{_count(count, 'obligor')} carry a live {described} "
        f"signal"
        + (f" {qualifier}" if qualifier else "")
        + f" — {f.get('share_of_book_obligors_pct', 0.0):.1f}% of the "
        f"{int(f.get('book_obligors') or 0):,} in the book, holding "
        f"{_money(f.get('exposure') or 0.0)}. The highest on that layer is "
        f"{lead.get('customer_name')} at "
        f"{float(lead.get(key) or 0.0):.1f} points, overall "
        f"{_band_phrase(float(lead.get('ews_score') or 0.0), str(lead.get('ews_band') or ''))}.")

    paras = [
        f"They are ordered by the {described} score itself, not by the "
        f"Early Warning score they roll into: a name can carry a live "
        f"external event and still sit low overall, and that name is exactly "
        f"who this question is asking after. {_count(high, 'of them sits', 'of them sit')} "
        f"at high severity or above."
    ]
    corroborated = int(f.get("corroborated_elsewhere") or 0)
    if alone and not corroborated:
        # The list was already drawn on the corroboration test, so saying
        # "all 14 of 14" would be reporting the filter back as a finding.
        paras.append(
            "None of them has any other layer firing — that is the condition "
            "this list was drawn on. Each rests on this layer alone, which "
            "makes every one of them a lead to verify rather than a finding "
            "to act on.")
    elif alone:
        paras.append(
            f"{_count(alone, 'of the names rests', 'of the names rest')} on "
            f"this layer alone, with nothing firing in any other layer. That "
            f"is the set to corroborate before acting: a single-layer reading "
            f"is a lead, not a finding.")
    else:
        paras.append(
            "Every name here has at least one other layer firing as well, so "
            "none of them rests on this layer alone.")

    points = [
        f"{r.get('customer_name')} — {float(r.get(key) or 0.0):.1f} points on "
        f"{described}, overall "
        f"{_band_phrase(float(r.get('ews_score') or 0.0), str(r.get('ews_band') or ''))}, "
        f"{_money(float(r.get('exposure') or 0.0))}"
        + ("" if r.get("corroborated") else " — no other layer firing")
        for r in rows[:10]]

    return Composed(
        direct=direct, interpretation=_sentence(paras), points=points,
        follow_ups=[f"What is driving {lead.get('customer_name')}?",
                    "Show the evidence behind the first one.",
                    "Which sectors carry the most of this?"],
        caveats=pack.caveats, chart={})


def _band_said(value: Any) -> str:
    """A band, or the High-plus pair, as a sentence says it."""
    text = str(value or "").upper()
    if text == "HIGH_PLUS":
        return "high or very high"
    return BAND_WORD.get(text, text.lower().replace("_", " "))


def transitions(pack: ff.FactPack) -> Composed:
    """Who crossed a severity band, between which two months.

    Not the score movement. A reader asking how many obligors changed band
    is asking a question with a whole number for an answer, and the number
    they want is a count of names — so the count comes first, the direction
    split comes second, and the names come after that.

    The two months are always stated. A transition figure without its window
    is unusable: "thirty-one moved" means one thing month on month and
    another over a year, and next month's reader cannot tell which they are
    looking at.
    """
    f = pack.figures or {}
    was, now = str(f.get("from_period") or ""), str(f.get("to_period") or "")
    changed = int(f.get("changed") or 0)
    worse = int(f.get("deteriorated") or 0)
    better = int(f.get("improved") or 0)
    same = int(f.get("unchanged") or 0)
    population = int(f.get("obligors_in_both") or 0)
    drilled = int(f.get("drilled") or 0)
    asked = dict(f.get("drill_filter") or {})
    rows = list(pack.rows or [])

    window = f"between {was} and {now}" if was and now else ""

    if f.get("single_period"):
        return Composed(
            direct=(f"There is only one published month, so no band "
                    f"transition can be measured. {now} is the first."),
            interpretation=("A transition needs two months. This is a limit "
                            "of the published data rather than a finding "
                            "about the book."),
            follow_ups=["Show the current distribution by risk band."],
            caveats=pack.caveats, chart={})

    if not changed:
        direct = (f"No obligor changed severity band {window}. All "
                  f"{population:,} in both months held the band they were "
                  f"in.")
    else:
        direct = (f"{_count(changed, 'obligor')} of {population:,} changed "
                  f"severity band {window} — "
                  f"{_count(worse, 'deteriorated', 'deteriorated')} and "
                  f"{_count(better, 'improved', 'improved')}. "
                  f"{_count(same, 'obligor')} held their band.")

    paras: list[str] = []
    into = int(f.get("crossed_into_high_plus") or 0)
    left = int(f.get("left_high_plus") or 0)
    if into or left:
        paras.append(
            f"{_count(into, 'obligor')} crossed into high severity or above "
            f"and {_count(left, 'obligor')} came out of it. Those are the "
            f"crossings the watchlist and the escalation matrix key on: a "
            f"name that crossed is a case to open whether its score moved "
            f"two points or twenty.")
    elif changed:
        paras.append(
            "None of the moves crossed the high-severity threshold, so no "
            "case is opened or closed by this month's transitions on "
            "severity alone.")

    if changed:
        paras.append(
            f"{_money(f.get('exposure_deteriorated') or 0.0)} sits behind "
            f"the names that deteriorated and "
            f"{_money(f.get('exposure_improved') or 0.0)} behind those that "
            f"improved. A band change is discrete: it says a threshold was "
            f"crossed, not how far, so read it beside the score movement "
            f"rather than instead of it.")

    entered = int(f.get("entered_the_book") or 0)
    gone = int(f.get("left_the_book") or 0)
    if entered or gone:
        paras.append(
            f"{_count(entered, 'obligor')} entered the book and "
            f"{_count(gone, 'obligor')} left it between the two months. "
            f"They are excluded from the counts above: appearing is not "
            f"deteriorating.")

    if asked:
        named = ", ".join(f"{k.replace('_band', '')} {_band_said(v)}"
                          for k, v in asked.items())
        if drilled:
            paras.append(
                f"Of those, {_count(drilled, 'obligor')} "
                f"{'matches' if drilled == 1 else 'match'} the move you "
                f"asked about ({named}), carrying "
                f"{_money(f.get('drill_exposure') or 0.0)}.")
        else:
            paras.append(
                f"None of them matches the move you asked about ({named}). "
                f"That is a finding rather than an empty result: the "
                f"crossing was looked for between the two months and did not "
                f"happen.")

    grouped_by = str(f.get("grouped_by") or "")
    if grouped_by:
        # Rolled up rather than named: the question asked which SECTORS
        # migrated, and answering it with a list of obligors is the level
        # below the one that was asked about.
        label = str(f.get("grouped_label") or grouped_by).lower()
        adverse = [r for r in rows if int(r.get("deteriorated") or 0)]
        if adverse:
            worst = adverse[0]
            direct = (f"{_count(changed, 'obligor')} of {population:,} "
                      f"changed severity band {window}, spread across "
                      f"{_count(f.get('groups_with_adverse_moves'), label)} "
                      f"with an adverse move. The most is {worst[grouped_by]} "
                      f"with {_count(worst['deteriorated'], 'obligor')} "
                      f"deteriorating on "
                      f"{_money(worst['exposure_deteriorated'])}.")
        else:
            direct = (f"No {label} had an adverse band migration {window}. "
                      f"{_count(better, 'obligor')} improved and "
                      f"{_count(same, 'obligor')} held their band.")
        paras = [
            f"Adverse migration is counted as obligors crossing DOWN a band "
            f"between the two months, not as a change in the group's average "
            f"score: a {label} whose average worsened while every name held "
            f"its band has migrated nobody.",
        ]
        crossings = sum(int(r.get("crossed_into_high_plus") or 0)
                        for r in rows)
        if adverse and crossings:
            paras.append(
                f"{_count(crossings, 'of the adverse moves crossed', 'of the adverse moves crossed')} "
                f"into high severity or above, which is the crossing that "
                f"opens a case.")
        elif adverse:
            paras.append(
                "None of the adverse moves crossed into high severity or "
                "above, so none of them opens a case on severity alone.")
        points = [
            f"{r[grouped_by]} — {_count(r['deteriorated'], 'obligor')} "
            f"deteriorated, {_count(r['improved'], 'obligor')} improved, "
            f"net {r['net_adverse']:+d}, "
            f"{_money(r['exposure_deteriorated'])} behind the adverse moves"
            for r in rows[:10] if r.get("changed")]
        if not points:
            points = [f"Every {label} held its band composition {window}."]
        return Composed(
            direct=direct, interpretation=_sentence(paras), points=points,
            follow_ups=["Which names moved in the worst one?",
                        "Show the band-transition matrix.",
                        "Why did they move?"],
            caveats=pack.caveats,
            chart={"kind": "comparison",
                   "reason": "adverse migrations across groups"})

    points = [
        f"{r.get('customer_name')} — "
        f"{BAND_WORD.get(str(r.get('from_band')), str(r.get('from_band')).lower())}"
        f" to "
        f"{BAND_WORD.get(str(r.get('to_band')), str(r.get('to_band')).lower())}"
        f", score "
        f"{float(r.get('ews_score_before') or 0):.1f} to "
        f"{float(r.get('ews_score_after') or 0):.1f}, "
        f"{_money(float(r.get('exposure') or 0))}"
        + (" — crossed into high severity" if r.get("crossed_into_high_plus")
           else "")
        for r in rows[:10]]

    if not points and changed:
        points = ["No name matches that particular move, though "
                  f"{_count(changed, 'obligor')} changed band overall."]

    # The matrix itself, when the reader asked to see it. Off-diagonal cells
    # only: the diagonal is the 298 names that did not move, and printing it
    # buries the six that did.
    moved_cells = [c for c in (f.get("matrix") or [])
                   if c["from_band"] != c["to_band"]]
    if moved_cells:
        points += [
            f"{BAND_WORD.get(str(c['from_band']), str(c['from_band']).lower())}"
            f" to "
            f"{BAND_WORD.get(str(c['to_band']), str(c['to_band']).lower())}"
            f": {_count(c['obligors'], 'obligor')}, "
            f"{_money(c['exposure'])}"
            for c in moved_cells]

    return Composed(
        direct=direct, interpretation=_sentence(paras), points=points,
        follow_ups=["Why did the first one move?",
                    "Show the distribution by risk band.",
                    "What should I do about the names that deteriorated?"],
        caveats=pack.caveats, chart={})


#: Which composer answers which scope.
COMPOSERS = {
    "layer_population": layer_population,
    "transitions": transitions,
    "ranking": ranking,
    "portfolio": portfolio, "level": level, "group": group,
    "borrower": borrower, "layer": layer, "evidence": evidence,
    "movement": movement, "comparison": comparison, "diagnosis": diagnosis,
    "action": action, "escalation": escalation, "methodology": methodology,
}


def compose(pack: ff.FactPack) -> Composed:
    """Write the reading for whichever scope this pack carries."""
    writer = COMPOSERS.get(pack.scope)
    if writer is None:
        return Composed(direct=f"There is no reading for a {pack.scope} scope.")
    return writer(pack)


__all__ = ["Composed", "COMPOSERS", "compose", "portfolio", "level", "group",
           "borrower", "layer", "layer_population", "evidence", "movement",
           "comparison", "ranking", "transitions"]
