"""
Section 10.7 — two uninterrupted journeys, one fresh and one resumed.

E2E-01 runs the demonstration end to end in a browser that has never seen the
product: sign in, look at the book, ask a portfolio question, narrow it,
compare two months, open the evidence, come back, and ask a scorecard question.

E2E-02 then destroys the session, signs in again, reopens the SAME conversation
and carries on — which is the part that catches state living only in memory.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    FAIL,
    PASS,
    WHATIF_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "end-to-end"


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    steps: list[str] = []

    # 1. The book, before any question.
    s.go("/data-builder", settle=3000)
    data_builder = s.text()
    sees_book = "Cockpit Data" in data_builder
    steps.append(f"Data Builder shows the Cockpit Data domain={sees_book}")

    # 2. A real portfolio question, and a follow-up.
    s.go("/", settle=2500)
    first = s.ask("Use Cockpit Data for August 2026. Show exposure and weighted "
                  "ECL by retail product.", timeout=300)
    conversation = page.url
    steps.append(f"the portfolio question answered={first.get('completed')}")
    narrowed = s.ask("Now only personal finance", timeout=300)
    steps.append(f"the narrowing answered={narrowed.get('completed')}")
    compared = s.ask("Compare with July 2026", timeout=300)
    steps.append(f"the period comparison answered={compared.get('completed')}")

    # 3. The evidence, and back.
    trace = page.query_selector('a[href^="/trace/"]')
    returned = False
    if trace is not None:
        trace.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        back = page.query_selector('[data-testid="back-link"]')
        if back is not None:
            back.click()
            page.wait_for_load_state("networkidle", timeout=90_000)
            page.wait_for_timeout(2500)
        returned = "/investigations/" in page.url
    steps.append(f"the evidence opened and returned={returned}")

    # 4. A scorecard question with its limitations.
    scorecard = s.ask("Assess the personal finance application scorecard on the "
                      "latest fully observed cohort.", timeout=300)
    said = s.latest_turn("Assess the personal finance application scorecard")
    honest = any(word in said.lower() for word in
                 ("cohort", "observed", "insufficient", "cannot", "gini",
                  "auc", "ks"))
    steps.append(f"the scorecard question answered with its limits={honest}")

    # 5. A scenario, in the other box.
    s.go("/what-if", settle=4000)
    scenario = s.ask("Increase PD by 20% for personal finance.",
                     selector=WHATIF_COMPOSER, timeout=300)
    steps.append(f"the scenario ran={scenario.get('completed')}")

    _case(rec, "E2E-01", "One uninterrupted demonstration journey in a fresh "
          "session: the book, a question, a narrowing, a comparison, the "
          "evidence and back, a scorecard question, and a scenario",
          bool(sees_book and first.get("completed") and narrowed.get("completed")
               and compared.get("completed") and returned and honest
               and scenario.get("completed")),
          "; ".join(steps), screenshot=s.shot("e2e-01"))

    # ------------------------------------------------------------------ E2E-02
    # The session, destroyed and rebuilt. Everything held only in memory dies
    # here — which is the point.
    s.context.clear_cookies()
    page.reload(wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(2500)
    signed_out = page.query_selector("#username") is not None
    signed_in_again = s.sign_in()
    page.goto(conversation, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(4000)
    restored = s.text()
    kept = ("retail product" in restored and "2026-08" in restored
            and "Personal Finance" in restored)
    more = s.ask("Explain that result more simply.", timeout=300)
    _case(rec, "E2E-02", "The same conversation, reopened in a NEW session: the "
          "transcript, the month and the result are restored and it can be "
          "continued",
          bool(signed_out and signed_in_again and kept and more.get("completed")),
          f"the session was really destroyed={signed_out}; signed in "
          f"again={signed_in_again}; the transcript, month and result came "
          f"back={kept}; a further turn answered={more.get('completed')}",
          screenshot=s.shot("e2e-02"))


if __name__ == "__main__":
    raise SystemExit(run_suite("end_to_end", suite))
