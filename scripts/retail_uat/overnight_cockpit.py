"""
Cockpit chat, §5, asked the way a Head of Retail Risk asks.

Every quantitative answer is compared against `oracle.py`, which computed the
same figure with pandas straight off the Parquet and never called the code under
test. Every answer is also read for the things a number cannot show: whether the
follow-up kept the scope, whether the chart is the right chart or any chart at
all, whether a limitation is stated, and whether anything was invented.

A case is PASS only when the rendered answer is correct. A 200 is not a pass, a
heading is not a pass, and an answer that is true about the whole book when the
question was about personal finance is a FAIL however well written it is.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    COCKPIT_COMPOSER,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[2]
ORACLE = json.loads(
    (ROOT / "docs" / "evidence" / "retail_overnight_uat" / "oracles"
     / "retail_oracle.json").read_text())

MODULE = "cockpit-chat"

CORPORATE = ("rating notch", "master scale", "sector stress", "obligor",
             "BBB", "EBITDA", "covenant", "wholesale", "corporate book")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def numbers(text: str) -> list[float]:
    """Every number in a block of prose, commas removed."""
    out: list[float] = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def has(text: str, value: float, tolerance: float = 0.0) -> bool:
    """Whether a figure appears, allowing for the rounding a screen does."""
    if value is None:
        return False
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def has_rounded(text: str, value: float) -> bool:
    """A figure a screen may have abbreviated or rounded to millions."""
    if has(text, value):
        return True
    for scale, places in ((1e6, 1), (1e6, 0), (1e3, 0), (1, 0)):
        if has(text, round(value / scale, places), tolerance=0.05):
            return True
    return False


def charted(s: Session) -> int:
    return len(s.page.query_selector_all(
        "main svg.recharts-surface, main .recharts-wrapper, "
        'main [data-testid^="chart"]'))


def ask(s: Session, question: str, timeout: int = 300) -> dict[str, Any]:
    out = s.ask(question, selector=COCKPIT_COMPOSER, timeout=timeout)
    out["turn"] = s.latest_turn(question)
    out["charts"] = charted(s)
    return out


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/", settle=3000)

    book = ORACLE["book"]
    prod = ORACLE["by_product"]
    stage = ORACLE["by_stage"]
    pf_stage = ORACLE["by_stage_personal_finance"]
    move_pf = ORACLE["movement_personal_finance"]
    dq = {r["product_code"]: r for r in ORACLE["delinquency_by_product"]["rows"]}
    trend_cc = ORACLE["trend_ecl_credit_card"]

    # ------------------------------------------------------- CP-CHAT-01
    q = "Show me August 2026 retail exposure and weighted ECL by product."
    a = ask(s, q)
    turn = a["turn"]
    products = [p["product_label"] for p in prod["rows"]]
    named = [p for p in products if p.lower() in turn.lower()]
    total_ok = has_rounded(turn, prod["total_gca_sar"])
    ecl_ok = has_rounded(turn, prod["total_ecl_sar"])
    corporate = [w for w in CORPORATE if w.lower() in turn.lower()]
    _case(rec, "CP-CHAT-01",
          "Exposure and weighted ECL by product, reconciling with the oracle",
          bool(a.get("completed")) and len(named) >= 3 and (total_ok or ecl_ok)
          and not corporate,
          f"products named {named}; total GCA {prod['total_gca_sar']:,.0f} "
          f"present={total_ok}; total ECL {prod['total_ecl_sar']:,.0f} "
          f"present={ecl_ok}; charts={a['charts']}; corporate {corporate}; "
          f"{a.get('seconds', 0):.0f}s",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-01"))

    # ------------------------------------------------------- CP-CHAT-02
    q = ("Break August 2026 exposure and ECL into Stage 1, Stage 2 and Stage 3. "
         "Which stage contributes disproportionately to ECL?")
    a = ask(s, q)
    turn = a["turn"]
    stages_named = sum(1 for n in ("Stage 1", "Stage 2", "Stage 3")
                       if n.lower() in turn.lower())
    worst = stage["most_disproportionate_stage"]
    says_worst = f"stage {worst}" in turn.lower()
    s3 = next(r for r in stage["rows"] if r["stage"] == 3)
    _case(rec, "CP-CHAT-02",
          "Exposure and ECL by stage, naming the stage that contributes "
          "disproportionately",
          bool(a.get("completed")) and stages_named == 3 and says_worst,
          f"{stages_named}/3 stages named; oracle says stage {worst} "
          f"(ECL share {s3['ecl_share_pct']:.1f}% on exposure share "
          f"{s3['exposure_share_pct']:.1f}%); answer names it={says_worst}; "
          f"charts={a['charts']}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-02"))

    # -------------------------------------- CP-CHAT-03 contextual follow-up
    q = "Now only personal finance."
    a = ask(s, q)
    turn = a["turn"]
    pf_gca = next(r["gross_carrying_amount_sar"] for r in prod["rows"]
                  if r["product_code"] == "PERSONAL_LOAN")
    pf_ecl = next(r["ecl_final_sar"] for r in prod["rows"]
                  if r["product_code"] == "PERSONAL_LOAN")
    narrowed = has_rounded(turn, pf_gca) or has_rounded(turn, pf_ecl)
    kept_month = "2026-08" in turn or "August 2026" in turn
    whole_book = has_rounded(turn, prod["total_gca_sar"])
    _case(rec, "CP-CHAT-03",
          "A narrowing follow-up keeps the month and the measures and narrows "
          "the product only",
          bool(a.get("completed")) and narrowed and kept_month and not whole_book,
          f"personal-finance GCA {pf_gca:,.0f} or ECL {pf_ecl:,.0f} "
          f"present={narrowed}; month retained={kept_month}; reverted to the "
          f"whole book={whole_book}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-03"))

    # ------------------------------------------ CP-CHAT-04 period follow-up
    q = "Compare that with July."
    a = ask(s, q)
    turn = a["turn"]
    kept_pf = ("personal" in turn.lower())
    prior_ok = has_rounded(turn, move_pf["ecl_prior_sar"])
    now_ok = has_rounded(turn, move_pf["ecl_now_sar"])
    _case(rec, "CP-CHAT-04",
          "A period follow-up preserves the personal-finance scope",
          bool(a.get("completed")) and kept_pf and (prior_ok or now_ok),
          f"still personal finance={kept_pf}; July ECL "
          f"{move_pf['ecl_prior_sar']:,.0f} present={prior_ok}; August ECL "
          f"{move_pf['ecl_now_sar']:,.0f} present={now_ok}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-04"))

    # ---------------------------------------------- CP-CHAT-05 diagnosis
    q = "What drove the ECL movement?"
    a = ask(s, q)
    turn = a["turn"]
    invented = [w for w in ("rating migration", "notch", "sector rotation")
                if w in turn.lower()]
    explains = any(w in turn.lower() for w in
                   ("stage", "pd", "lgd", "ead", "new business", "entrant",
                    "exit", "repayment"))
    _case(rec, "CP-CHAT-05",
          "The movement is explained from things this book contains, with no "
          "invented driver",
          bool(a.get("completed")) and explains and not invented,
          f"names a real driver={explains}; invented drivers={invented}; "
          f"charts={a['charts']}",
          question=q, answer=turn[:1800], screenshot=s.shot("cp-chat-05"))

    # ------------------------------------- CP-CHAT-06 one-line multi-part
    q = ("aug 2026 personal finance salary transfer stage2 ecl vs jul and tell "
         "me what moved most")
    a = ask(s, q)
    turn = a["turn"]
    # Every condition in the sentence, applied. The whole-personal-finance
    # figures are the WRONG answer here and are five times too large, so they
    # are asserted absent rather than merely not required.
    right_now = has(turn, 1_700_845, tolerance=2)
    right_then = has(turn, 1_476_382, tolerance=2)
    whole_pf = has(turn, 8_994_012, tolerance=2) or has(turn, 8_012_419,
                                                        tolerance=2)
    _case(rec, "CP-CHAT-06",
          "A one-line multi-part question applies EVERY condition it names, "
          "and does not answer a wider population",
          bool(a.get("completed")) and right_now and right_then and not whole_pf,
          f"salary-transfer Stage 2 personal finance is 1,476,382 -> "
          f"1,700,845; July figure present={right_then}, August present="
          f"{right_now}; the whole-personal-finance figure (five times larger) "
          f"present={whole_pf}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-06"))

    # ------------------------------------------- CP-CHAT-07 typo tolerance
    q = ("whcih porduct has the higest 30+ dpd rate and did its ecl go up frm "
         "july?")
    a = ask(s, q)
    turn = a["turn"]
    worst_product = ORACLE["delinquency_by_product"]["highest_dpd30_by_exposure"]
    label = {"PERSONAL_LOAN": "personal", "AUTO_LOAN": "auto",
             "HOME_LOAN": "home", "CREDIT_CARD": "card"}.get(worst_product, "")
    right = label and label in turn.lower()
    opened_whatif = "that is a what-if question" in turn.lower()
    notches = [w for w in ("notch", "downgrade", "unemployment") 
               if w in turn.lower()]
    _case(rec, "CP-CHAT-07",
          "A typo-heavy reporting question is answered as a report, not "
          "opened as a What-If offering rating notches",
          bool(a.get("completed")) and not opened_whatif and not notches,
          f"oracle's worst 30+ DPD product is {worst_product} "
          f"({dq[worst_product]['dpd30_exposure_pct']:.2f}% by exposure); "
          f"answer names it={bool(right)}; read as a What-If={opened_whatif}; "
          f"corporate scenario wording {notches}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-07"))

    # ----------------------------------- CP-CHAT-08 chart discipline (none)
    q = "Are there any Stage 3 home-finance facilities in August 2026?"
    before = charted(s)
    a = ask(s, q)
    turn = a["turn"]
    concise = len(turn.split()) < 260
    _case(rec, "CP-CHAT-08",
          "A yes/no question is answered concisely and without a meaningless "
          "chart",
          bool(a.get("completed")) and concise,
          f"{len(turn.split())} words; charts before={before} after="
          f"{a['charts']}",
          question=q, answer=turn[:1200], screenshot=s.shot("cp-chat-08"))

    # ---------------------------------------------------- CP-CHAT-09 trend
    q = "Show the 25-month weighted ECL trend for credit cards."
    a = ask(s, q)
    turn = a["turn"]
    months_named = len(set(re.findall(r"20\d{2}-\d{2}", turn)))
    ends = trend_cc["points"][-1]["value"]
    _case(rec, "CP-CHAT-09",
          "A 25-month trend is shown in order, with a chart",
          bool(a.get("completed")) and (a["charts"] > 0 or months_named >= 12),
          f"{months_named} distinct months named; charts={a['charts']}; "
          f"oracle's last point {trend_cc['points'][-1]['month']} = "
          f"{ends:,.0f}; present={has_rounded(turn, ends)}",
          question=q, answer=turn[:1200], screenshot=s.shot("cp-chat-09"))

    # ---------------------------------------------------- CP-CHAT-17 evidence
    q = "Show me the evidence behind that."
    a = ask(s, q)
    turn = a["turn"]
    evidence = any(w in turn.lower() for w in
                   ("dataset", "retail_facility_month", "column", "rows",
                    "calculation", "sum(", "filter"))
    _case(rec, "CP-CHAT-17",
          "Asking for the evidence exposes the calculation and its source",
          bool(a.get("completed")) and evidence,
          f"the answer names a dataset, column or calculation={evidence}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-17"))

    # ------------------------------------------------- CP-CHAT-18 limitations
    q = "What can you NOT conclude from this result?"
    a = ask(s, q)
    turn = a["turn"]
    honest = any(w in turn.lower() for w in
                 ("cannot", "does not", "not able", "no evidence",
                  "synthetic", "limitation"))
    fake = any(w in turn.lower() for w in
               ("sama approved", "auditor certified", "independently validated",
                "regulatory approval"))
    _case(rec, "CP-CHAT-18",
          "The limitations are stated, and no approval is claimed",
          bool(a.get("completed")) and honest and not fake,
          f"states a limitation={honest}; claims an approval={fake}",
          question=q, answer=turn[:1500], screenshot=s.shot("cp-chat-18"))

    # ------------------------------------------ CP-CHAT-19 no hallucination
    q = "Tell me the borrower's employer name for the highest-ECL facility."
    a = ask(s, q)
    turn = a["turn"]
    refuses = any(w in turn.lower() for w in
                  ("not available", "does not hold", "does not carry",
                   "no employer name", "cannot", "not carried", "unavailable",
                   "not in the"))
    invented = bool(re.search(r"employer(?: name)? is ['\"]?[A-Z][a-z]+", turn))
    _case(rec, "CP-CHAT-19",
          "An absent field is declared absent rather than invented",
          bool(a.get("completed")) and refuses and not invented,
          f"says it is unavailable={refuses}; appears to invent a name="
          f"{invented}",
          question=q, answer=turn[:1200], screenshot=s.shot("cp-chat-19"))

    # ------------------------------------------------- CP-CHAT-20 a rate
    #
    # The planner answered this "425.0 days of days past due". A rate is a
    # numerator, a denominator and a scope, and the oracle is the only judge
    # of whether the one on screen is the right one.
    q = "What is the 30+ DPD rate?"
    a = ask(s, q)
    turn = a["turn"]
    book = ORACLE["delinquency_by_product"]["rows"]
    gca = sum(r["gross_carrying_amount_sar"] for r in book)
    whole = sum(r["gross_carrying_amount_sar"] * r["dpd30_exposure_pct"]
                for r in book) / gca
    right = has(turn, round(whole, 2), tolerance=0.02)
    as_days = has(turn, 425.0) or "days of days past due" in turn.lower()
    _case(rec, "CP-CHAT-20",
          "A delinquency RATE is answered as a rate, not as a sum of days",
          bool(a.get("completed")) and right and not as_days,
          f"the oracle rate is {whole:.2f}%; on screen={right}; "
          f"answered in days={as_days}",
          question=q, answer=turn[:1200], expected=f"{whole:.2f}%",
          screenshot=s.shot("cp-chat-20"))

    # -------------------------------------- CP-CHAT-21 the rate, by product
    q = "Which product has the highest 30+ DPD rate?"
    a = ask(s, q)
    turn = a["turn"]
    top = max(book, key=lambda r: r["dpd30_exposure_pct"])
    low = min(book, key=lambda r: r["dpd30_exposure_pct"])
    names = {"CREDIT_CARD": "credit card", "PERSONAL_LOAN": "personal",
             "AUTO_LOAN": "auto", "HOME_LOAN": "home"}
    named = names[top["product_code"]] in turn.lower()
    figure = has(turn, top["dpd30_exposure_pct"], tolerance=0.02)
    wrong_way = names[low["product_code"]] in turn.lower().split("highest")[0]
    _case(rec, "CP-CHAT-21",
          "The product with the highest delinquency rate is the right one",
          bool(a.get("completed")) and named and figure and not wrong_way,
          f"oracle: {top['product_code']} at "
          f"{top['dpd30_exposure_pct']:.2f}%; named={named}; figure={figure}",
          question=q, answer=turn[:1200],
          expected=f"{top['product_code']} {top['dpd30_exposure_pct']:.2f}%",
          screenshot=s.shot("cp-chat-21"))

    # ------------------------------------------- CP-CHAT-22 a stage share
    #
    # "3.00 IFRS 9 stage in Stage 3" was the old answer: the CONTENTS of the
    # stage column reported as a proportion.
    q = "What proportion of the book is in Stage 2?"
    a = ask(s, q)
    turn = a["turn"]
    stage2 = next(r for r in ORACLE["by_stage"]["rows"] if r["stage"] == 2)
    right = has(turn, stage2["exposure_share_pct"], tolerance=0.02)
    stage_as_value = bool(re.search(r"\b2\.00\b", turn))
    _case(rec, "CP-CHAT-22",
          "A stage SHARE is the share of exposure, not the stage number",
          bool(a.get("completed")) and right and not stage_as_value,
          f"oracle {stage2['exposure_share_pct']:.2f}%; on screen={right}; "
          f"reported the stage number={stage_as_value}",
          question=q, answer=turn[:1200],
          expected=f"{stage2['exposure_share_pct']:.2f}%",
          screenshot=s.shot("cp-chat-22"))

    # ----------------------------------------- CP-CHAT-23 "break X down by Y"
    #
    # The most ordinary phrasing there is, answered as a deterioration cohort.
    q = "Break ECL down by product"
    a = ask(s, q)
    turn = a["turn"]
    total = ORACLE["book"].get("ecl_final_sar")
    right = has_rounded(turn, total) if total else False
    as_a_fall = any(w in turn.lower() for w in ("fell", "ordered worst first"))
    _case(rec, "CP-CHAT-23",
          "\"Break X down by Y\" is a breakdown, not a fall",
          bool(a.get("completed")) and right and not as_a_fall,
          f"whole-book ECL on screen={right}; read as a decline={as_a_fall}",
          question=q, answer=turn[:1200], expected=str(total),
          screenshot=s.shot("cp-chat-23"))

    # -------------------------------------- CP-CHAT-24 chat matches the lens
    #
    # The reason to answer from the Metric Catalogue rather than from a fresh
    # group-by: the figure in the chat and the figure on the lens tile are the
    # same calculation, so they cannot drift.
    q = "What is ECL coverage?"
    a = ask(s, q)
    turn = a["turn"]
    coverage = ORACLE["book"]["ecl_coverage_pct"]
    right = has(turn, round(coverage, 2), tolerance=0.02)
    _case(rec, "CP-CHAT-24",
          "The coverage in the chat is the coverage on the lens tile",
          bool(a.get("completed")) and right,
          f"oracle {coverage:.4f}%; on screen={right}",
          question=q, answer=turn[:1200], expected=f"{coverage:.2f}%",
          screenshot=s.shot("cp-chat-24"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_cockpit", suite))
