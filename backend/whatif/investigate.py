"""
The What-If investigation brain: what a question is, and what it is answered from.

Why this module exists
----------------------
A What-If thread had one reading of a message: is this a scenario? Anything
that was not a scenario fell through, so "Why did Stage 3 ECL increase?" either
did nothing or, worse, was read as another shock and quietly changed the answer
it was asking about.

A credit officer does not use a scenario tool by stating scenarios. They state
one, then interrogate it. So every message in a thread is one of three things,
and which one it is decides whether the scenario STATE may be touched:

  EXPLAIN    "Why did Stage 3 ECL increase?" "How much is due to Stage
             migration?" "Which borrowers caused this?"
             — answered from the result already computed. State unchanged.

  VIEW       "Show this by sector." "Give me a table." "Chart it by rating."
             — a different cut of the same result. State unchanged.

  MODIFY     "Now increase LGD by 5 points." "Undo the last step."
             — the scenario changes and the book is priced again.

The division is not cosmetic. An EXPLAIN that recomputed would be answering a
question about a result that no longer exists, and a MODIFY that did not would
be lying about what it did.

Where the numbers come from
---------------------------
Every figure in an answer is computed HERE, from the borrower-level before and
after the engine already produced. Nothing is estimated, and nothing is left to
a language model to recall: the model's job is to read the question and to put
the returned numbers into a sentence, and a number it has not been handed is a
number it must not write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

INVESTIGATE_VERSION = "1.0.0"

EXPLAIN = "explain"
VIEW = "view"
MODIFY = "modify"
INTENTS: tuple[str, ...] = (EXPLAIN, VIEW, MODIFY)

# ------------------------------------------------------------- classifying

#: Asking WHY, WHO, HOW MUCH about a result that already exists. These never
#: touch the scenario.
_EXPLAIN = re.compile(
    r"\bwhy\b|\bwhat\s+(?:caused|drove|explains)\b|\bexplain\b|\bbecause\b"
    r"|\bhow\s+much\s+(?:of|is|was|comes)\b|\bhow\s+many\b|\bwhich\s+borrowers?\b"
    r"|\bwhich\s+(?:sectors?|names?|customers?|grades?|ratings?)\s+"
    r"(?:contributed|drove|caused|explain)"
    r"|\bwho\b|\bresponsible\b|\bcontributed\b|\bdriver\b|\bdrivers\b"
    r"|\battribut\w+|\bdue\s+to\b|\breconcile\b|\bmakes?\s+up\b"
    r"|\bwhat\s+happened\s+to\b|\bcompare\b|\bdifference\s+between\b"
    r"|\bwhy\s+is\s+ml\b|\bhow\s+come\b",
    re.IGNORECASE)

#: Asking to SEE the same result differently.
_VIEW = re.compile(
    r"\bshow\b|\bbreak\s*(?:it|this)?\s*down\b|\bbreakdown\b|\bby\s+"
    r"(?:sector|segment|stage|rating|grade|customer|borrower|period)\b"
    r"|\bas\s+a\s+(?:chart|table|graph)\b|\bchart\b|\btable\b|\blist\b"
    r"|\bgive\s+me\b|\btop\s+\d+\b|\bdisplay\b",
    re.IGNORECASE)

#: Unmistakably changing the scenario.
_MODIFY = re.compile(
    r"\bundo\b|\breset\b|\bremove\b|\bdrop\s+the\b|\bdelete\b|\bstart\s+again\b"
    r"|\bnow\s+(?:increase|decrease|raise|reduce|lower|cut|add|apply|downgrade|"
    r"upgrade|move|shock|stress)\b"
    r"|\bchange\s+the\s+\w+\s+to\b|\balso\s+(?:increase|decrease|raise|reduce|"
    r"lower|cut|add|apply|downgrade|upgrade|move|shock)\b"
    r"|\bwhat\s+(?:happens|if)\s+i\s+now\b|\bkeep\s+the\b.{0,40}\bremove\b",
    re.IGNORECASE)

#: What a breakdown is asked for BY.
_DIMENSION: tuple[tuple[str, str, str], ...] = (
    (r"\bsector\b", "sector", "Sector"),
    (r"\bsegment\b", "segment", "Segment"),
    (r"\bstages?\b", "stage_baseline", "Opening stage"),
    (r"\b(?:rating|grade)s?\b", "opening_rating", "Opening rating"),
    (r"\b(?:customers?|borrowers?|names?|clients?)\b", "display_name", "Borrower"),
)


@dataclass
class Reading:
    """What the message is, and what it asks about."""

    intent: str = MODIFY
    dimension: str = ""
    dimension_label: str = ""
    #: A specific Stage the question is about, where it names one.
    stage: int = 0
    #: What the question wants explained, where it is one of the known topics.
    topic: str = ""
    wants_chart: bool = False
    wants_table: bool = False
    #: Whether the message points at the result on screen rather than at the
    #: book. "Show this by sector" is a cut of the scenario; "show Stage 1 PD
    #: by sector" is a question about the reported book, and answering the
    #: second from a scenario's figures would be a different answer entirely.
    about_the_result: bool = False
    question: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def changes_state(self) -> bool:
        return self.intent == MODIFY

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "dimension": self.dimension,
                "dimension_label": self.dimension_label, "stage": self.stage,
                "topic": self.topic, "wants_chart": self.wants_chart,
                "wants_table": self.wants_table,
                "about_the_result": self.about_the_result,
                "notes": list(self.notes)}


#: A sentence that OPENS with one of these is a question about something,
#: never an instruction to do it.
_INTERROGATIVE = re.compile(
    r"\s*(?:why|what|which|who|whom|whose|how|was|were|is|are|am|did|does|do|"
    r"can|could|would|should|has|have|had|will)\b",
    re.IGNORECASE)

#: Except when the question IS the scenario. "What if I downgrade everyone two
#: notches?" opens with an interrogative and is an instruction.
_HYPOTHETICAL = re.compile(
    r"\bwhat\s*[- ]?\s*if\b|\bwhat\s+happens?\s+(?:if|when)\b"
    r"|\bwhat\s+would\s+happen\b|\bsuppose\b|\bassume\b",
    re.IGNORECASE)

#: Pointing at the result rather than at the book.
_DEICTIC = re.compile(
    r"\bthis\b|\bthat\b|\bit\b|\bthem\b|\bthese\b|\bthose\b"
    r"|\bthe\s+(?:result|scenario|movement|increase|decrease|change|rise|"
    r"fall|impact|effect|shock|what[- ]if)\b",
    re.IGNORECASE)

#: Topics an EXPLAIN question can be about, in the order they are tested.
_TOPIC: tuple[tuple[str, str], ...] = (
    (r"\bmeasurement\s+basis\b|\blifetime\s+pd\s+replac\w+|\b12[- ]?m(?:onth)?\s+"
     r"pd\s+(?:to|into|replaced|became)\b|\bbasis\s+change\b"
     r"|\blifetime\s+pd\b.{0,30}\binstead\b|\bbecause\s+lifetime\b"
     # The question people actually ask, which never uses the words
     # "measurement basis": why does crossing into Stage 2 cost anything at
     # all when nothing about the borrower changed?
     r"|\bmov\w+\s+(?:in)?to\s+stage\s*2\b.{0,30}\b(?:cost|worth|expensive)"
     r"|\bwhy\s+does\s+stage\s*2\s+cost\b"
     r"|\blifetime\s+pd\b.{0,40}\b(?:used|applied|apply|instead|rather)\b",
     "basis"),
    (r"\bstage\s*3\b|\bstage\s+three\b", "stage3"),
    (r"\bstage\s+migration\b|\bstage\s+movement\b|\bmoved?\s+from\s+stage\b"
     r"|\bstage\s*1\s*(?:to|->)\s*stage\s*2\b", "stage_migration"),
    (r"\bml\b|\bxgboost\b|\bmodel\s+differ\w*|\bdelta\s+vs\b|\bvs\.?\s+delta\b"
     r"|\bcompare\s+delta\b|\bmethodolog\w+|\bboth\s+models?\b"
     r"|\bdelta\s+model\b", "methodology"),
    (r"\blgd\b|\bloss\s+given\s+default\b", "lgd"),
    (r"\bead\b|\bexposure\s+at\s+default\b|\bccf\b", "ead"),
    (r"\brating\b|\bnotch\w*\b|\bdowngrade\b", "rating"),
    (r"\bmacro\b|\beconom\w+|\bunemployment\b|\boil\b|\bgdp\b", "macro"),
    (r"\bpd\b|\bprobability\s+of\s+default\b", "pd"),
    (r"\bborrowers?\b|\bnames?\b|\bcustomers?\b|\bwho\b|\bresponsible\b",
     "borrowers"),
    (r"\bsector\b", "sector"),
)


def classify(question: str) -> Reading:
    """Which of the three things this message is.

    Order matters, and every step of it was a defect first.

    An INTERROGATIVE is never an instruction. "Was any of this the rating
    downgrade?" was read as a scenario and downgraded the entire book — a
    question about a result became the thing it was asking about. So a sentence
    that opens with an interrogative and is not a hypothetical is a question,
    whatever verbs it contains.

    EXPLAIN before VIEW. "Show me the borrowers responsible" contains "show",
    but it asks who caused something, and answering it with a plain table
    would drop the question.

    A FULL SCENARIO before VIEW. "Stress the top 50 exposures by two notches"
    contains "top 50" and was read as a request to see a list; it states a
    magnitude and a direction, so it is an instruction.
    """
    said = str(question or "").strip()
    reading = Reading(question=said)
    if not said:
        return reading

    from backend.whatif import language as lang

    asked = bool(_INTERROGATIVE.match(said)) and not _HYPOTHETICAL.search(said)
    if _MODIFY.search(said) and not asked:
        reading.intent = MODIFY
        return reading

    explains = bool(_EXPLAIN.search(said))
    views = bool(_VIEW.search(said))
    if explains or asked:
        reading.intent = EXPLAIN
    elif lang.read(said).scenario is not None:
        reading.intent = MODIFY
    elif views:
        reading.intent = VIEW
    else:
        # Neither signal. Ask the scenario reader: a sentence it can read as a
        # What-If is one — including "stress the real estate portfolio", which
        # names no magnitude and has to be ASKED how big rather than answered
        # as though it were a question about a result. Everything else is a
        # question, which is the safer of the two readings because it cannot
        # silently change a number.
        reading.intent = (MODIFY
                          if getattr(lang.read(said), "opens_whatif", False)
                          else EXPLAIN)

    for pattern, column, label in _DIMENSION:
        if re.search(pattern, said, re.IGNORECASE):
            reading.dimension, reading.dimension_label = column, label
            break
    stage = re.search(r"\bstage\s*([123])\b", said, re.IGNORECASE)
    if stage:
        reading.stage = int(stage.group(1))
    for pattern, topic in _TOPIC:
        if re.search(pattern, said, re.IGNORECASE):
            reading.topic = topic
            break
    reading.wants_chart = bool(re.search(r"\bchart\b|\bgraph\b|\bplot\b",
                                         said, re.IGNORECASE))
    reading.wants_table = bool(re.search(r"\btable\b|\blist\b", said,
                                         re.IGNORECASE))
    reading.about_the_result = bool(_DEICTIC.search(said))
    return reading


# --------------------------------------------------------------- answering


def _frame(result: Any) -> pd.DataFrame:
    """The borrower-level before and after, as the result holds it."""
    frame = getattr(result, "borrowers", None)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _money(value: float, currency: str = "SAR") -> str:
    return f"{currency} {value:,.1f}m"


def _by(frame: pd.DataFrame, column: str, label: str,
        limit: int = 25) -> dict[str, Any]:
    """The ECL movement grouped by one dimension, largest contribution first."""
    if column not in frame.columns:
        return {"available": False,
                "why": f"This result does not carry {label.lower()}."}
    work = frame.copy()
    for money in ("ecl_baseline", "ecl_stressed", "ead"):
        if money in work.columns:
            work[money] = pd.to_numeric(work[money], errors="coerce").fillna(0.0)
    grouped = (work.groupby(work[column].astype(str))
               .agg(borrowers=("borrower_id", "size"),
                    exposure=("ead", "sum"),
                    ecl_before=("ecl_baseline", "sum"),
                    ecl_after=("ecl_stressed", "sum"))
               .reset_index().rename(columns={column: "label"}))
    grouped["change"] = grouped["ecl_after"] - grouped["ecl_before"]
    grouped["change_pct"] = np.where(
        grouped["ecl_before"] > 0,
        grouped["change"] / grouped["ecl_before"] * 100.0, 0.0)
    total = float(grouped["change"].sum())
    grouped["share_pct"] = (grouped["change"] / total * 100.0) if total else 0.0
    grouped = grouped.reindex(
        grouped["change"].abs().sort_values(ascending=False).index)
    return {"available": True, "dimension": label,
            "rows": grouped.head(limit).round(4).to_dict(orient="records"),
            "total_change": total, "groups": int(len(grouped))}


def _contributors(frame: pd.DataFrame, limit: int = 20) -> dict[str, Any]:
    """The borrowers that moved the provision most, largest first."""
    if frame.empty or "ecl_increase" not in frame.columns:
        return {"available": False, "why": "No borrower-level result."}
    work = frame.copy()
    work["ecl_increase"] = pd.to_numeric(work["ecl_increase"],
                                         errors="coerce").fillna(0.0)
    total = float(work["ecl_increase"].sum())
    top = work.reindex(
        work["ecl_increase"].abs().sort_values(ascending=False).index).head(limit)
    columns = [c for c in ("borrower_id", "display_name", "sector",
                           "opening_rating", "stressed_rating",
                           "stage_baseline", "stage_stressed", "ead",
                           "ecl_baseline", "ecl_stressed", "ecl_increase",
                           "primary_driver") if c in top.columns]
    rows = top[columns].round(4).to_dict(orient="records")
    for row in rows:
        row["share_pct"] = (round(float(row.get("ecl_increase", 0.0))
                                  / total * 100.0, 3) if total else 0.0)
    return {"available": True, "rows": rows, "total_change": total,
            "shown": len(rows), "of": int(len(work))}


def _stage_three(frame: pd.DataFrame, currency: str = "SAR") -> dict[str, Any]:
    """Whether Stage 3 moved, and if so exactly which borrowers and why.

    Stage 3 is the question people ask about most and trust least, because a
    provision on defaulted names moving under a Stage 1 shock looks wrong. It
    usually IS wrong, so this reports the mechanism or reports that there is
    none.
    """
    if frame.empty or "stage_baseline" not in frame.columns:
        return {"available": False, "why": "No borrower-level result."}
    work = frame.copy()
    for column in ("ecl_baseline", "ecl_stressed", "ead"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column],
                                         errors="coerce").fillna(0.0)
    before = pd.to_numeric(work["stage_baseline"], errors="coerce").fillna(1)
    after = pd.to_numeric(work.get("stage_stressed", before),
                          errors="coerce").fillna(before)

    was_three = before >= 3
    now_three = after >= 3
    entered = (~was_three) & now_three
    left = was_three & (~now_three)
    stayed = was_three & now_three

    change = float(work.loc[now_three, "ecl_stressed"].sum()
                   - work.loc[was_three, "ecl_baseline"].sum())
    within = float(work.loc[stayed, "ecl_stressed"].sum()
                   - work.loc[stayed, "ecl_baseline"].sum())
    arriving = float(work.loc[entered, "ecl_stressed"].sum())
    leaving = float(work.loc[left, "ecl_baseline"].sum())

    drivers = []
    if abs(arriving) > 1e-9:
        drivers.append({
            "driver": "Borrowers migrating INTO Stage 3",
            "borrowers": int(entered.sum()),
            "exposure": float(work.loc[entered, "ead"].sum()),
            "effect": arriving})
    if abs(leaving) > 1e-9:
        drivers.append({
            "driver": "Borrowers leaving Stage 3",
            "borrowers": int(left.sum()),
            "exposure": float(work.loc[left, "ead"].sum()),
            "effect": -leaving})
    if abs(within) > 1e-9:
        moved = work[stayed & (work["ecl_stressed"] != work["ecl_baseline"])]
        drivers.append({
            "driver": "Names already in Stage 3, re-measured",
            "borrowers": int(len(moved)),
            "exposure": float(moved["ead"].sum()),
            "effect": within})

    if not drivers:
        return {
            "available": True, "moved": False, "change": 0.0,
            "borrowers_before": int(was_three.sum()),
            "borrowers_after": int(now_three.sum()),
            "note": (
                f"Stage 3 did not move. {int(was_three.sum()):,} borrowers "
                "were in Stage 3 before this scenario and the same are in it "
                "after, at the same provision. A scenario does not cure a "
                "default and does not create one, so unless the shock reached "
                "their exposure, their security or their recovery, their "
                "expected credit loss is unchanged."),
        }
    return {
        "available": True, "moved": True, "change": change,
        "borrowers_before": int(was_three.sum()),
        "borrowers_after": int(now_three.sum()),
        "drivers": drivers,
        "note": (
            f"Stage 3 expected credit loss moved by "
            f"{_money(change, currency)}. Every part of that movement has a "
            "named mechanism below: names arriving, names leaving, or names "
            "already there whose exposure, security or loss rate the scenario "
            "changed."),
    }


def _pd_versus_ecl(frame: pd.DataFrame) -> dict[str, Any]:
    """Why the provision moved by more than the PD did.

    The commonest confusion on a What-If, and it has an arithmetic answer: the
    provision is a product, and a Stage crossing changes which PD is in it.
    """
    if frame.empty:
        return {"available": False}
    work = frame.copy()
    for column in ("pd_12m", "pd_stressed", "ecl_baseline", "ecl_stressed",
                   "ead"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column],
                                         errors="coerce").fillna(0.0)
    weight = work["ead"] if work.get("ead") is not None else None
    weights = weight if weight is not None and weight.sum() > 0 else None
    pd_before = float(np.average(work["pd_12m"], weights=weights))
    pd_after = float(np.average(work["pd_stressed"], weights=weights))
    ecl_before = float(work["ecl_baseline"].sum())
    ecl_after = float(work["ecl_stressed"].sum())
    return {
        "available": True,
        "pd_before": round(pd_before, 4),
        "pd_after": round(pd_after, 4),
        "pd_change_pct": round((pd_after / pd_before - 1) * 100.0, 3)
        if pd_before else 0.0,
        "ecl_change_pct": round((ecl_after / ecl_before - 1) * 100.0, 3)
        if ecl_before else 0.0,
    }


def answer(reading: Reading, result: Any) -> dict[str, Any]:
    """The deterministic answer to an EXPLAIN or VIEW question.

    Computed from the result already on screen. Nothing here re-runs the
    scenario, and nothing here is estimated: every figure is a sum or an
    average over the borrower rows the engine produced.
    """
    frame = _frame(result)
    currency = getattr(result, "currency", "SAR") or "SAR"
    summary = dict(getattr(result, "summary", {}) or {})
    attribution = dict(getattr(result, "attribution", {}) or {})
    body: dict[str, Any] = {
        "version": INVESTIGATE_VERSION,
        "intent": reading.intent,
        "topic": reading.topic,
        "question": reading.question,
        "state_changed": False,
        "headline": {
            "baseline_ecl": summary.get("baseline_ecl", 0.0),
            "whatif_ecl": summary.get("stressed_ecl", 0.0),
            "change": summary.get("incremental_ecl", 0.0),
            "change_pct": summary.get("incremental_ecl_pct", 0.0),
            "currency": currency,
        },
    }

    if reading.intent == VIEW or (reading.dimension and not reading.topic):
        column = reading.dimension or "sector"
        label = reading.dimension_label or "Sector"
        body["breakdown"] = _by(frame, column, label)
        body["explanation"] = (
            f"The same result, cut by {label.lower()}. Nothing about the "
            "scenario changed — this is the figures already computed, grouped "
            "differently.")
        return body

    topic = reading.topic
    if topic == "stage3" or reading.stage == 3:
        body["stage_3"] = _stage_three(frame, currency)
        body["explanation"] = body["stage_3"].get("note", "")
        return body
    if topic == "basis":
        body["measurement_basis"] = attribution.get("measurement_basis", {})
        body["explanation"] = body["measurement_basis"].get("note", "")
        return body
    if topic in ("stage_migration",):
        body["stage_movement"] = dict(getattr(result, "stage_movement", {}) or {})
        body["measurement_basis"] = attribution.get("measurement_basis", {})
        body["explanation"] = body["measurement_basis"].get("note", "")
        return body
    if topic == "borrowers" or reading.dimension == "display_name":
        body["contributors"] = _contributors(frame)
        body["explanation"] = (
            "The borrowers whose provision moved most, largest first. The "
            "share column is that borrower's part of the whole movement.")
        return body
    if topic == "methodology":
        body["methodology"] = {
            "chosen": summary.get("methodology_label", ""),
            "version": summary.get("methodology_version", ""),
            "model_adjustment": attribution.get("model_adjustment"),
        }
        body["explanation"] = (
            (attribution.get("model_adjustment") or {}).get("note")
            or "This result was priced on one methodology; ask to compare to "
               "see the other.")
        return body
    if topic in ("pd", "lgd", "ead", "rating", "macro", "sector"):
        body["drivers"] = attribution.get("drivers", [])
        body["pd_versus_ecl"] = _pd_versus_ecl(frame)
        if topic == "sector":
            body["breakdown"] = _by(frame, "sector", "Sector")
        body["explanation"] = (
            "Every driver of the movement, split by an exact order-neutral "
            "Shapley value, so the parts add to the whole.")
        return body

    # A general "why". Give the whole decomposition, which is what the
    # question is really asking for.
    body["drivers"] = attribution.get("drivers", [])
    body["measurement_basis"] = attribution.get("measurement_basis", {})
    body["pd_versus_ecl"] = _pd_versus_ecl(frame)
    body["explanation"] = (
        "The movement, split across the drivers that caused it. The effects "
        "sum to the total, and a driver the scenario did not touch is exactly "
        "zero.")
    return body


def describe() -> dict[str, Any]:
    """What the thread does with a message, for the configuration screen."""
    return {
        "version": INVESTIGATE_VERSION,
        "intents": [
            {"intent": EXPLAIN, "label": "Explain or investigate",
             "changes_state": False,
             "examples": ["Why did Stage 3 ECL increase?",
                          "How much is due to Stage migration?",
                          "Which borrowers contributed most?"]},
            {"intent": VIEW, "label": "View or break down",
             "changes_state": False,
             "examples": ["Show this by sector.", "Break it down by rating.",
                          "Give me a table."]},
            {"intent": MODIFY, "label": "Change the scenario",
             "changes_state": True,
             "examples": ["Now increase LGD by 5 percentage points.",
                          "Undo the last step.", "Remove the macro shock."]},
        ],
        "statement": (
            "Every message is one of three things, and only one of them may "
            "touch the scenario. An explanation is answered from the result "
            "already computed, so asking why cannot change the number you are "
            "asking about."),
    }


__all__ = [
    "EXPLAIN", "INTENTS", "INVESTIGATE_VERSION", "MODIFY", "Reading", "VIEW",
    "answer", "classify", "describe",
]
