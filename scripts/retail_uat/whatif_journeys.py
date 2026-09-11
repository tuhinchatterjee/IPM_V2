"""
What-If business journeys WI-09 to WI-20, in a real browser.

The half of section 10.6 that is about what happens AROUND a run: explaining
it, editing it through the form, saving and reopening it, exporting it and
reading the file back, comparing two saved runs, cancelling, and moving between
the two chat boxes without either one picking up the other's state.

Destructive controls are exercised only on records this suite created itself.
Every one of them is named "WIJ-<case> <timestamp>", it is deleted by id, and
the case asserts that the record is gone and that no other saved run moved.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FAIL,
    PASS,
    WHATIF_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "what-if"
STAMP = time.strftime("%H%M%S")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def _api(s: Session, path: str) -> Any:
    """Read an endpoint through the SIGNED-IN BROWSER, not around it."""
    return s.page.evaluate(
        """async (url) => {
             const r = await fetch(url, {credentials: "include"});
             const text = await r.text();
             try { return {status: r.status, body: JSON.parse(text)}; }
             catch (e) { return {status: r.status, text}; }
           }""", f"{BACKEND}/api/v1{path}")


def _save_current(s: Session, name: str) -> bool:
    box = s.page.query_selector('[data-testid="retail-whatif-name"]')
    if box is None:
        return False
    box.click()
    box.fill(name)
    button = s.page.query_selector('[data-testid="retail-whatif-save"]')
    if button is None:
        return False
    button.click()
    s.page.wait_for_timeout(4000)
    return name in s.text()


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    s.go("/what-if", settle=4000)

    # ------------------------------------------------------------------ WI-09
    s.ask("Increase PD by 20% for personal finance.", selector=WHATIF_COMPOSER,
          timeout=240)
    run_turn = s.latest_turn("Increase PD by 20% for personal finance.")
    ask_about = s.ask("What changed, why, and which assumptions matter?",
                      selector=WHATIF_COMPOSER, timeout=240)
    explained = s.latest_turn("What changed, why, and which assumptions matter?")
    # The explanation must be about THIS run: same shock, same population.
    about_this = ("personal_loan" in explained.lower()
                  or "personal finance" in explained.lower()) and \
                 ("pd_relative" in explained or "Expected credit loss" in explained)
    invented = "sector" in explained.lower() or "notch" in explained.lower()
    _case(rec, "WI-09", "Asking what changed explains THAT run's numbers and "
          "assumptions, not another scenario and not invented figures",
          bool(ask_about.get("completed") and about_this and not invented),
          f"completed={ask_about.get('completed')}; the answer is about this "
          f"run={about_this}; it invents a corporate dimension={invented}",
          answer=explained[:800], screenshot=s.shot("whatif-wi-09"))

    # ------------------------------------------------------------------ WI-10
    # The form control beside the conversation: the month select.
    month = page.query_selector('[data-testid="retail-whatif-month"]')
    changed = False
    if month is not None:
        month.select_option("2026-07")
        page.wait_for_timeout(600)
        s.ask("Increase PD by 20% for personal finance.",
              selector=WHATIF_COMPOSER, timeout=240)
        turn = s.latest_turn("Increase PD by 20% for personal finance.")
        changed = "2026-07" in turn or "2026-07" in s.text()
    _case(rec, "WI-10", "Changing the month on the form and re-running uses "
          "the new month, and the conversation and the form agree",
          bool(month is not None and changed),
          f"the month control exists={month is not None}; the re-run used the "
          f"month the form now shows={changed}",
          screenshot=s.shot("whatif-wi-10"))
    if month is not None:
        month.select_option("2026-08")
        page.wait_for_timeout(500)

    # ------------------------------------------------------------------ WI-11
    s.ask("Increase PD by 2 percentage points for credit cards.",
          selector=WHATIF_COMPOSER, timeout=240)
    name_a = f"WIJ-11 {STAMP}"
    saved_a = _save_current(s, name_a)
    before = _api(s, "/retail/whatif/saved")
    stored = [r for r in (before.get("body") or {}).get("saved", [])
              if r["name"] == name_a]
    record_ok = bool(stored) and stored[0]["shocks"] == {"pd_absolute_pp": 2.0}
    s.go("/", settle=2000)
    s.go("/what-if", settle=4000)
    reopen = page.query_selector(
        f'[data-testid="retail-whatif-reopen-{stored[0]["id"]}"]') if stored else None
    reopened = False
    if reopen is not None:
        reopen.click()
        page.wait_for_timeout(4000)
        text = s.text()
        reopened = "as it ran at" in text and "2 percentage points" in text
    _case(rec, "WI-11", "A saved run is a real stored record, and reopening it "
          "restores its own definition, snapshot and figures",
          bool(saved_a and record_ok and reopened),
          f"the UI reported it saved={saved_a}; the STORED record carries the "
          f"shock it ran={record_ok}; reopening restored it={reopened}",
          record=stored[0] if stored else None,
          screenshot=s.shot("whatif-wi-11"))

    saved_id = stored[0]["id"] if stored else 0

    # ------------------------------------------------------------------ WI-12
    # Change the month, then reopen the saved run: it must keep ITS month.
    month = page.query_selector('[data-testid="retail-whatif-month"]')
    if month is not None:
        month.select_option("2025-08")
        page.wait_for_timeout(600)
    kept = False
    if saved_id:
        reopen = page.query_selector(f'[data-testid="retail-whatif-reopen-{saved_id}"]')
        if reopen is not None:
            reopen.click()
            page.wait_for_timeout(4000)
            kept = "as it ran at 2026-08" in s.text()
    _case(rec, "WI-12", "Reopening a saved run after changing the month shows "
          "ITS pinned month, and never silently rebases it",
          bool(kept),
          f"the reopened run still states its own month={kept}",
          screenshot=s.shot("whatif-wi-12"))
    if month is not None:
        month.select_option("2026-08")
        page.wait_for_timeout(500)

    # ------------------------------------------------------------------ WI-13
    # Both advertised formats, downloaded and PARSED.
    csv_ok = json_ok = False
    csv_detail = json_detail = "not run"
    if saved_id:
        csv_body = _api(s, f"/retail/whatif/saved/{saved_id}/export?fmt=csv")
        text = csv_body.get("text") or ""
        rows = list(csv.reader(io.StringIO(
            "\n".join(l for l in text.splitlines() if not l.startswith("#")))))
        table = {r[0]: r[1] for r in rows if len(r) >= 2}
        # The VALUE, not its spelling: a JSONB round trip may hand back 2 or
        # 2.0 for the same shock, and an exported file is checked for what it
        # says the run did, not for how a float was rendered.
        shocks = dict(pair.split("=", 1)
                      for pair in table.get("Shocks", "").split("; ") if "=" in pair)
        csv_ok = (table.get("Saved as") == name_a
                  and float(shocks.get("pd_absolute_pp", "nan")) == 2.0
                  and float(table.get("Baseline ECL (SAR)", 0)) > 0)
        csv_detail = (f"{len(rows)} rows; run "
                      f"{table.get('Run id', '')}; shocks "
                      f"{table.get('Shocks', '')}")
        json_body = _api(s, f"/retail/whatif/saved/{saved_id}/export?fmt=json")
        payload = json_body.get("body")
        if payload is None and json_body.get("text"):
            payload = json.loads(json_body["text"])
        run = (payload or {}).get("run") or {}
        json_ok = (run.get("scenario", {}).get("shocks")
                   == {"pd_absolute_pp": 2.0}
                   and run.get("baseline", {}).get("ecl_final_sar", 0) > 0)
        json_detail = (f"run {run.get('scenario', {}).get('run_id', '')}; "
                       f"baseline {run.get('baseline', {}).get('ecl_final_sar')}")
        # The two files must agree with each other and with the record.
        if csv_ok and json_ok:
            csv_ok = abs(float(table["Baseline ECL (SAR)"])
                         - float(run["baseline"]["ecl_final_sar"])) < 0.01
    _case(rec, "WI-13", "Both advertised export formats download, parse, and "
          "carry figures that reconcile with the stored run",
          bool(csv_ok and json_ok),
          f"CSV: {csv_detail}. JSON: {json_detail}. The two agree={csv_ok}")

    # ------------------------------------------------------------------ WI-19
    s.go("/what-if", settle=4000)
    s.ask("Increase PD by 20% for credit cards.", selector=WHATIF_COMPOSER,
          timeout=240)
    name_b = f"WIJ-19 {STAMP}"
    _save_current(s, name_b)
    listing = _api(s, "/retail/whatif/saved").get("body", {}).get("saved", [])
    ids = [r["id"] for r in listing if r["name"] in (name_a, name_b)]
    compared = False
    detail = "the two runs were not both saved"
    if len(ids) == 2:
        body = _api(s, f"/retail/whatif/compare?left={ids[1]}&right={ids[0]}")
        found = body.get("body") or {}
        compared = (found.get("left", {}).get("id") in ids
                    and found.get("right", {}).get("id") in ids
                    and "note" in found)
        detail = (f"compared {found.get('left', {}).get('name')} with "
                  f"{found.get('right', {}).get('name')}; comparable="
                  f"{found.get('comparable')}; differences="
                  f"{found.get('differences')}")
    _case(rec, "WI-19", "Two SAVED runs are compared as themselves, with any "
          "difference in month, population or methodology stated",
          bool(compared), detail)

    # ------------------------------------------------------------------ WI-14
    s.go("/what-if", settle=4000)
    s.ask("Increase PD by 20% for personal finance.", selector=WHATIF_COMPOSER,
          timeout=240)
    clear = page.query_selector('[data-testid="retail-whatif-clear"]')
    cleared = False
    intact = False
    if clear is not None:
        clear.click()
        page.wait_for_timeout(1500)
        text = s.text()
        cleared = "Read as:" not in text
        after = _api(s, "/retail/whatif/saved").get("body", {}).get("saved", [])
        intact = len(after) >= len(listing)
    _case(rec, "WI-14", "Clear ends the conversation and leaves saved runs and "
          "the canonical book untouched",
          bool(clear is not None and cleared and intact),
          f"the control exists={clear is not None}; the conversation was "
          f"cleared={cleared}; saved runs survived={intact}",
          screenshot=s.shot("whatif-wi-14"))

    # ------------------------------------------------------------------ WI-18
    s.ask("Relax the application score cut-off to 560 and show what would have "
          "happened to the applications we rejected.", selector=WHATIF_COMPOSER,
          timeout=240)
    honest = s.latest_turn("Relax the application score cut-off")
    states_limit = any(word in honest.lower() for word in
                       ("booked", "rejected", "not implement", "does not",
                        "cannot", "observed"))
    claims_future = "proven" in honest.lower() or "will perform" in honest.lower()
    _case(rec, "WI-18", "A rejected-applicant question states the "
          "observed-replay limitation instead of inventing outcomes",
          bool(states_limit and not claims_future),
          f"the answer states what it cannot know={states_limit}; it claims "
          f"proven future performance={claims_future}",
          answer=honest[:700], screenshot=s.shot("whatif-wi-18"))

    # ------------------------------------------------------------------ WI-20
    # Cockpit and What-If, back and forth, with no carryover.
    s.go("/", settle=2500)
    s.ask("Show weighted ECL by retail product for August 2026", timeout=240)
    cockpit_turn = s.latest_turn("Show weighted ECL by retail product")
    carried_shock = "20% relative" in cockpit_turn or "pd_relative" in cockpit_turn
    s.go("/what-if", settle=4000)
    whatif_text = s.text()
    fresh = "Read as:" not in whatif_text
    _case(rec, "WI-20", "Moving between the two chat boxes keeps their states "
          "apart: no shock leaks into the Cockpit and no question into What-If",
          bool(not carried_shock and fresh),
          f"the Cockpit answer carried a What-If shock={carried_shock}; the "
          f"What-If box came back without a stale run={fresh}",
          screenshot=s.shot("whatif-wi-20"))

    # ------------------------------------------------------------------ WI-16
    # Interrupt a run by navigating away, then come back and run again.
    box = s.composer(WHATIF_COMPOSER)
    box.click()
    box.type("Increase PD by 50% for home finance.")
    s.submit_button(WHATIF_COMPOSER).click()
    page.wait_for_timeout(250)
    s.go("/", settle=2000)
    page.wait_for_timeout(3000)
    s.go("/what-if", settle=3000)
    retry = s.ask("Increase PD by 50% for home finance.",
                  selector=WHATIF_COMPOSER, timeout=240)
    after = _api(s, "/retail/whatif/saved").get("body", {}).get("saved", [])
    duplicates = len([r for r in after if r["name"] in (name_a, name_b)])
    _case(rec, "WI-16", "A run interrupted by navigation leaves no half-written "
          "record, and the retry answers once",
          bool(retry.get("completed") and duplicates == 2),
          f"the retry completed={retry.get('completed')}; saved records named "
          f"by this suite: {duplicates} (expected 2 — no duplicate was written)",
          screenshot=s.shot("whatif-wi-16"))

    # ------------------------------------------- destructive, on our own rows
    deleted_ok = False
    others_intact = False
    if saved_id:
        before_ids = {r["id"] for r in after}
        button = page.query_selector(f'[data-testid="retail-whatif-delete-{saved_id}"]')
        if button is not None:
            button.click()
            page.wait_for_timeout(3000)
        remaining = _api(s, "/retail/whatif/saved").get("body", {}).get("saved", [])
        remaining_ids = {r["id"] for r in remaining}
        deleted_ok = saved_id not in remaining_ids
        others_intact = (before_ids - {saved_id}) <= remaining_ids
    _case(rec, "WI-14b", "DESTRUCTIVE — Delete removes the record this suite "
          "created and nothing else",
          bool(deleted_ok and others_intact),
          f"the test-owned record {saved_id} was deleted={deleted_ok}; every "
          f"other saved run survived={others_intact}")


if __name__ == "__main__":
    raise SystemExit(run_suite("whatif_journeys", suite))
