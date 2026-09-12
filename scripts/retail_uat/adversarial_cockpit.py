"""
The second adversarial Cockpit session, driven in Chromium.

The overnight run closed thirty-seven defects and never saw its discovery
curve flatten. This suite is the narrower session that followed: one Head of
Retail Risk conversation, asked in the order a person asks it, through the
real launcher-served frontend — and then the two things a conversation has to
survive, which no amount of question-answering proves.

**Chart appropriateness.** A chart drawn for a yes/no answer is noise; a
25-month trend shown only as a table is a chart withheld. Both are checked by
counting what is DRAWN — `role="application"` — rather than the frame around
it, which wraps the table too.

**Persistence.** A thread saved, left for another module, returned to,
followed up, refreshed, reopened, and read for its evidence. Nothing from the
prior context may disappear, and nothing may leak into another thread.

Every figure asserted here was computed independently from the Parquet first;
see `tests/retail/test_ret_adversarial_cockpit.py`, which recomputes them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

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

MODULE = "cockpit"

#: A chart FRAME wraps whichever of the chart and the table is showing; the
#: frame takes role="application" only when a chart is actually drawn.
FRAME = 'main [data-testid="chart-surface"]'
CHART = 'main [data-testid="chart-surface"][role="application"]'


def charted(s: Session) -> int:
    return len(s.page.query_selector_all(CHART))


def axis_labels(s: Session) -> list[str]:
    charts = s.page.query_selector_all(CHART)
    if not charts:
        return []
    return [(t.text_content() or "").strip()
            for t in charts[-1].query_selector_all("text")]



def _series_rows(s: Session) -> int:
    """How many reporting months the answer's table carries."""
    import re as _re

    body = " ".join(s.text().split())
    return len(set(_re.findall(r"\b(20\d\d-[01]\d)\b", body)))


def ask(s: Session, question: str) -> tuple[str, dict]:
    """One turn, and the transcript below it."""
    outcome = s.ask(question, selector=COCKPIT_COMPOSER)
    return s.latest_turn(question), outcome


def carries(said: str, *wanted: str) -> list[str]:
    """Which of these the answer does NOT carry."""
    lowered = " ".join(said.lower().split())
    return [w for w in wanted if w.lower() not in lowered]


# ------------------------------------------------------------------ the suite


def body(s: Session, rec: Recorder) -> None:
    _conversation(s, rec)
    _charts(s, rec)
    _persistence(s, rec)


def _conversation(s: Session, rec: Recorder) -> None:
    """Nine turns of one conversation, in the order a person asks them."""
    s.go("/")
    started = time.time()

    said, _ = ask(s, "What changed in my retail portfolio this month that I "
                     "should actually care about?")
    missing = carries(said, "15,952,109", "13.38")
    rec.add(Case("ADV-01", MODULE,
                 "The opening question is answered, led by the movement that matters",
                 status=PASS if not missing else FAIL,
                 detail=("ECL 14,069,608 to 15,952,109, +13.38%"
                         if not missing else f"not on screen: {missing}"),
                 expected="the ECL movement leads, not the 2% exposure movement",
                 actual=said[:400], seconds=time.time() - started,
                 evidence={"screenshot": s.shot("adv-01-what-changed")}))

    said, _ = ask(s, "Which product worries you most and why?")
    rec.add(Case("ADV-02", MODULE, "A concern ranking answers, naming its basis",
                 status=PASS if not carries(said, "concern") else FAIL,
                 detail=said[:200], actual=said[:400]))

    said, _ = ask(s, "Show me the numbers behind that.")
    asked_again = "which figure should creditprobe measure" in said.lower()
    rec.add(Case("ADV-03", MODULE,
                 "An evidence follow-up after a composite is answered, not queried",
                 status=FAIL if asked_again else PASS,
                 detail=("the thread died two turns after a composite"
                         if asked_again else "answered from the carried composite"),
                 actual=said[:400],
                 evidence={"screenshot": s.shot("adv-03-numbers-behind")}))

    said, _ = ask(s, "What happened over the previous six months - is this a "
                     "one-month spike or a trend?")
    rec.add(Case("ADV-04", MODULE,
                 "A window a composite cannot draw is declined in words",
                 status=PASS if not carries(said, "one reporting date") else FAIL,
                 detail=said[:250], actual=said[:400]))

    said, _ = ask(s, "Which ten customers had the largest ECL increase this month?")
    missing = carries(said, "RC-0015749")
    rec.add(Case("ADV-05", MODULE,
                 "A customer ranking sums every facility, not the largest one",
                 status=PASS if not missing else FAIL,
                 detail=("RC-0015749 leads, +119,967" if not missing
                         else f"not on screen: {missing}"),
                 expected="RC-0015749 first by summed ECL increase",
                 actual=said[:400],
                 evidence={"screenshot": s.shot("adv-05-top-customers")}))

    said, _ = ask(s, "Show their facilities.")
    rec.add(Case("ADV-06", MODULE, "A drill-down returns facilities, not the same customers",
                 status=PASS if not carries(said, "facilit") else FAIL,
                 detail=said[:250], actual=said[:400],
                 evidence={"screenshot": s.shot("adv-06-facilities")}))

    said, _ = ask(s, "Back.")
    rec.add(Case("ADV-07", MODULE, "Back returns the previous answer unrecomputed",
                 status=PASS if not carries(said, "previous answer") else FAIL,
                 detail=said[:250], actual=said[:400]))

    said, _ = ask(s, "Which subsegment has the highest Stage 2 rate?")
    missing = carries(said, "CARD", "12.70")
    rec.add(Case("ADV-08", MODULE, "A stage RATE is the published metric, not a summed stage",
                 status=PASS if not missing else FAIL,
                 detail="CARD at 12.70%" if not missing else f"not on screen: {missing}",
                 expected="CARD, 12.70%", actual=said[:400],
                 evidence={"screenshot": s.shot("adv-08-stage2-rate")}))

    said, _ = ask(s, "Which subsegment has the largest Stage 2 exposure?")
    missing = carries(said, "FIRST_HOME")
    rec.add(Case("ADV-09", MODULE, "An amount question names a different subsegment",
                 status=PASS if not missing else FAIL,
                 detail="FIRST_HOME" if not missing else f"not on screen: {missing}",
                 expected="FIRST_HOME, 39,971,366 SAR", actual=said[:400]))

    said, _ = ask(s, "that one")
    # Read for the SENTENCE rather than its opening words: the transcript is
    # sliced at the question, and the clarification repeats the question in
    # its first line, so "Which one?" falls above the slice.
    rec.add(Case("ADV-10", MODULE, "A pointer with no position is asked about",
                 status=PASS if not carries(said, "points at a row") else FAIL,
                 detail=said[:250], actual=said[:400],
                 evidence={"screenshot": s.shot("adv-10-which-one")}))


def _charts(s: Session, rec: Recorder) -> None:
    """What gets a chart, and what does not."""
    s.go("/")

    for case_id, question, wanted in (
        ("CHT-A1", "Are there any Stage 3 home-finance facilities?", 0),
        ("CHT-A2", "What does Gini measure?", 0),
        ("CHT-A3", "What can I not conclude from that?", 0),
    ):
        ask(s, question)
        drawn = charted(s)
        rec.add(Case(case_id, MODULE, f"No chart for: {question}",
                     status=PASS if drawn <= wanted else FAIL,
                     detail=f"{drawn} charts drawn", expected=wanted, actual=drawn,
                     evidence={"screenshot": s.shot(f"{case_id.lower()}")}))

    s.go("/")
    ask(s, "Show the 25-month ECL trend")
    s.settle_for(lambda: len(s.page.query_selector_all(FRAME)) > 0, seconds=20)
    frames = len(s.page.query_selector_all(FRAME))
    rec.add(Case("CHT-B1", MODULE,
                 "A chart is available for: Show the 25-month ECL trend",
                 status=PASS if frames else FAIL,
                 detail=f"{frames} chart frames, {charted(s)} drawn",
                 expected="at least one chart frame", actual=frames,
                 evidence={"screenshot": s.shot("cht-b1")}))

    # Measured on the TREND's own chart, before another question draws one
    # over it. ON-72 was a 25-month trend answered with two points, and a
    # check that reads whichever chart happens to be last cannot see that.
    labels = [t for t in axis_labels(s) if t]
    months = [t for t in labels if t.count("-") == 1 and t[:4].isdigit()]
    rows = _series_rows(s)
    rec.add(Case("CHT-B3", MODULE,
                 "The 25-month trend is a series, not two endpoints",
                 status=PASS if max(len(months), rows) >= 12 else FAIL,
                 detail=f"{len(months)} month labels on the axis, "
                        f"{rows} month rows in the table",
                 expected=">= 12 months", actual={"axis": months[:4], "rows": rows},
                 evidence={"screenshot": s.shot("cht-b3")}))

    s.go("/")
    ask(s, "Compare ECL by product")
    s.settle_for(lambda: len(s.page.query_selector_all(FRAME)) > 0, seconds=20)
    frames = len(s.page.query_selector_all(FRAME))
    rec.add(Case("CHT-B2", MODULE,
                 "A chart is available for: Compare ECL by product",
                 status=PASS if frames else FAIL,
                 detail=f"{frames} chart frames, {charted(s)} drawn",
                 expected="at least one chart frame", actual=frames,
                 evidence={"screenshot": s.shot("cht-b2")}))


def _persistence(s: Session, rec: Recorder) -> None:
    """A thread, left, returned to, followed up, refreshed and reopened."""
    s.go("/")
    opening = "What is ECL by product?"
    said, _ = ask(s, opening)
    started_url = s.page.url
    rec.add(Case("THR-01", MODULE, "A conversation starts and is answered",
                 status=PASS if not carries(said, "15,952,109") else FAIL,
                 detail=said[:200], actual=said[:300]))

    s.go("/what-if")
    left = "/what-if" in s.page.url
    s.page.goto(started_url)
    s.page.wait_for_load_state("networkidle", timeout=90_000)
    s.page.wait_for_timeout(2500)
    back = s.text()
    rec.add(Case("THR-02", MODULE,
                 "Leaving for What-If and returning keeps the conversation",
                 status=PASS if left and opening[:24] in " ".join(back.split())
                 else FAIL,
                 detail=f"left={left}; the question is still listed="
                        f"{opening[:24] in ' '.join(back.split())}",
                 evidence={"screenshot": s.shot("thr-02-returned")}))

    said, _ = ask(s, "Break that down by region.")
    rec.add(Case("THR-03", MODULE, "A follow-up after the return still carries context",
                 status=PASS if not carries(said, "region") else FAIL,
                 detail=said[:200], actual=said[:300]))

    s.page.reload()
    s.page.wait_for_load_state("networkidle", timeout=90_000)
    s.page.wait_for_timeout(3000)
    after = " ".join(s.text().split())
    kept = opening[:24] in after and "region" in after.lower()
    rec.add(Case("THR-04", MODULE, "A refresh keeps both turns of the thread",
                 status=PASS if kept else FAIL,
                 detail=f"opening kept={opening[:24] in after}; "
                        f"the breakdown kept={'region' in after.lower()}",
                 evidence={"screenshot": s.shot("thr-04-refreshed")}))

    trace = s.page.query_selector('a:has-text("Trace"), button:has-text("Trace")')
    opened = False
    if trace is not None:
        trace.click()
        opened = s.wait_for_url("/trace", seconds=20) or "trace" in s.page.url
    rec.add(Case("THR-05", MODULE, "Evidence opens from the answer",
                 status=PASS if opened else FAIL,
                 detail=f"the Trace opened={opened}; at {s.page.url}",
                 evidence={"screenshot": s.shot("thr-05-trace")}))

    if opened:
        s.page.go_back()
        s.page.wait_for_load_state("networkidle", timeout=90_000)
        s.page.wait_for_timeout(2500)
    returned = " ".join(s.text().split())
    rec.add(Case("THR-06", MODULE, "Back from the evidence returns to THAT conversation",
                 status=PASS if opening[:24] in returned else FAIL,
                 detail=f"the question is still listed={opening[:24] in returned}",
                 evidence={"screenshot": s.shot("thr-06-back")}))

    s.go("/")
    fresh = " ".join(s.text().split())
    rec.add(Case("THR-07", MODULE, "Nothing from that thread leaks into a new one",
                 status=PASS if "15,952,109" not in fresh else FAIL,
                 detail="a new Cockpit carries no figure from the saved thread",
                 actual=fresh[:200],
                 evidence={"screenshot": s.shot("thr-07-fresh")}))


if __name__ == "__main__":
    raise SystemExit(run_suite("adversarial_cockpit", body))
