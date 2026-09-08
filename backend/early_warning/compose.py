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
    return (f"{high} obligors carry "
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


def _drill(label: str) -> str:
    return label


# --------------------------------------------------------- portfolio-level


def portfolio(pack: ff.FactPack) -> Composed:
    f = pack.figures
    move = f.get("movement")
    conc = f.get("concentration") or {}

    direct = (f"The portfolio early warning score is "
              f"{_band_phrase(f['portfolio_ews'], f['band'])} on an "
              f"exposure-weighted basis, with {f['high_plus_count']} of "
              f"{f['obligors']} obligors at high severity or above carrying "
              f"{_money(f['high_plus_exposure'])}, "
              f"{f['high_plus_exposure_pct']}% of exposure.")

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
                f"obligors carry {conc['top_n_share_pct']}% of the high-risk "
                f"exposure, led by {names}. That makes this a name-level "
                f"review rather than a reason to tighten appetite across the "
                f"book — the population average is being pulled by those "
                f"names rather than by a common condition.")
        else:
            paras.append(
                f"The risk is spread rather than concentrated: the largest "
                f"{conc['top_n']} names carry {conc['top_n_share_pct']}% of "
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
    f, rows = pack.figures, pack.rows
    label = f["level_label"].lower()
    weakest = rows[0] if rows else None
    field_name = f["level_field"]

    direct = (f"Grouped by {label}, the weakest is "
              f"{weakest[field_name]} at "
              f"{_band_phrase(weakest['portfolio_ews'], weakest['band'])} "
              f"across {weakest['obligors']} obligors and "
              f"{_money(weakest['exposure'])}." if weakest else
              f"There is nothing to group by {label} this period.")

    paras: list[str] = []
    if weakest:
        top = rows[:3]
        listed = _list_of([f"{r[field_name]} at {r['portfolio_ews']:.1f}" for r in top])
        carrying = f.get("top_three_exposure",
                         sum(r["exposure"] for r in top))
        paras.append(
            f"The three weakest are {listed}, together carrying "
            f"{_money(carrying)}. The comparison worth making is not the "
            f"ranking but whether each group's average reflects a common "
            f"condition or one or two names: a group whose high-risk exposure "
            f"sits in a minority of obligors is a single-name problem wearing "
            f"a group's label.")

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

    points = [_population_escalation_line(f)] if weakest else []
    follow_ups = ([f"Open {weakest[field_name]}.",
                   "What is common across the high-risk names?",
                   "Group by another field."] if weakest else [])
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=follow_ups, caveats=pack.caveats,
                    chart={"kind": "comparison", "reason": "a ranking across groups"})


def group(pack: ff.FactPack) -> Composed:
    f = pack.figures
    conc = f.get("concentration") or {}
    move = f.get("movement")
    layers = f.get("layers") or {}

    direct = (f"{pack.label} is at "
              f"{_band_phrase(f['portfolio_ews'], f['band'])}, "
              f"{f['obligors']} obligors and {_money(f['exposure'])}, "
              f"{f['high_plus_count']} at high or above.")

    paras: list[str] = []
    if conc.get("high_plus_count"):
        if conc.get("is_concentrated"):
            paras.append(
                f"The weakness is concentrated rather than broad-based: "
                f"{conc['high_plus_count']} of {f['obligors']} obligors sit at "
                f"high or above and carry {conc['top_n_share_pct']}% of the "
                f"high-risk exposure. That distinction decides the response — "
                f"the evidence supports targeted borrower intervention rather "
                f"than a sector-wide limit action. If the same drivers begin "
                f"appearing across more obligors, it becomes a portfolio "
                f"question instead.")
        else:
            paras.append(
                f"The weakness is spread across the group rather than sitting "
                f"in one or two names: {conc['high_plus_count']} obligors are "
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


def layer(pack: ff.FactPack) -> Composed:
    f = pack.figures
    worst = f.get("worst_node")
    scores = [s for s in (f.get("ta_score"), f.get("c_score")) if s is not None]
    direct = (f"{f['layer_name']} scores "
              f"{_list_of([f'{s:.1f}' for s in scores])} for "
              f"{f['customer_name']}.")
    paras = []
    if worst:
        paras.append(
            f"The dominant node is {worst['code']} {worst['name']} at "
            f"{worst['score']:.0f}: {worst['reason'].lower()}. That is the "
            f"reading to verify before acting on the layer as a whole.")
    action = act.for_subcategory(worst["code"]) if worst else None
    points = [_action_line(action)] if action else []
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
        f"{left['high_plus_count']} obligors at high or above against "
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
    direct = (f"Across {root['obligors']} obligors in {f['population']}, "
              f"the strongest partition is {f['strongest_split']}.")
    paras = [f["reading"]]
    if leaves:
        worst = leaves[0]
        paras.append(
            f"The action that follows is aimed at \"{worst['label']}\" — "
            f"{worst['obligors']} obligors carrying "
            f"{_money(worst['exposure'])}, {worst['high_plus']} of them at "
            f"high or above. Confirm the hypothesis on those names before "
            f"acting on the population as a whole.")
    points = [
        f"Minimum leaf {f['min_leaf']} obligors "
        f"({int(f['min_leaf_share'] * 100)}% of the population), depth "
        f"{f['max_depth']}.",
    ]
    return Composed(direct=direct, interpretation=_sentence(paras), points=points,
                    follow_ups=["Show me the obligors in that leaf.",
                                "Run the diagnosis on a segment instead."],
                    caveats=pack.caveats,
                    chart={"kind": "distribution",
                           "reason": "a population partition"})


#: Which composer answers which scope.
COMPOSERS = {
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
           "borrower", "layer", "evidence", "movement", "comparison"]
