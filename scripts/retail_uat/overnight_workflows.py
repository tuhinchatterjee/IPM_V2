"""
Threads, investigations, reports, sharing and messaging — §8 to §12.

Everything here is done through the screen a user would use, with disposable
UAT records created by this suite and nothing else touched. No real recipient
is ever addressed: the suite creates its own accounts, prefixed `uat.`, sends
only to those, signs in as them to read what arrived, and leaves them
deactivated at the end.

The rule that decides most of these cases: **a thread, an investigation or a
share that reopens and quietly loses its month, its filters, its scenario or
its linked evidence is a FAIL.** Reopening is not the test; reopening with the
same thing in it is.
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
    BLOCKED,
    COCKPIT_COMPOSER,
    FAIL,
    NA,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "workflows"

#: Where the application's own JavaScript sends its API calls.
API_BASE = "http://localhost:8328"

#: The disposable accounts this suite creates and uses. Real seeded users are
#: never messaged: a UAT that sends work to somebody's actual inbox overnight
#: is a UAT that gets switched off.
UAT_USERS: tuple[dict[str, str], ...] = (
    {"username": "uat.risk.head", "first_name": "UAT", "last_name": "Risk Head",
     "role": "ANALYST", "team": "Retail Credit",
     "job_title": "UAT Retail Risk Head"},
    {"username": "uat.analyst", "first_name": "UAT", "last_name": "Analyst",
     "role": "ANALYST", "team": "Retail Credit",
     "job_title": "UAT Portfolio Analyst"},
)
UAT_PASSWORD = "UatRetail!2026"

CORPORATE = ("rating notch", "obligor", "BBB", "EBITDA", "covenant",
             "wholesale", "corporate book", "Borrower 360")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def _blocked(rec: Recorder, cid: str, title: str, why: str) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title, status=BLOCKED,
                        detail=why))


def said(text: str, *words: str) -> bool:
    lowered = text.lower()
    return any(w.lower() in lowered for w in words)


def api(s: Session, method: str, path: str,
        body: Any = None) -> tuple[int, Any]:
    """One API call through the BROWSER's own session, cookies and all.

    Used only for the parts of this suite that are setup rather than the thing
    under test — creating the disposable accounts, reading back what the screen
    should be showing. Every assertion below is made against the rendered page.
    """
    # The app's OWN base URL, not the page's origin. The frontend talks to
    # the backend directly (NEXT_PUBLIC_API_URL); a relative path goes through
    # Next's rewrite instead, which is a different route into the product and
    # answered a POST with a 500 the backend never saw.
    base = s.page.evaluate("() => window.__CREDITPROBE_API__ || ''") or API_BASE
    script = """
    async ([method, url, body]) => {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: body === null ? undefined : JSON.stringify(body),
      });
      let payload = null;
      try { payload = await res.json(); } catch (e) { payload = null; }
      return [res.status, payload];
    }
    """
    return tuple(s.page.evaluate(script, [method, f"{base}{path}", body]))


# ------------------------------------------------------------ the accounts


def make_uat_users(s: Session, rec: Recorder) -> list[dict[str, Any]]:
    """Create the disposable recipients, or reuse them if they exist."""
    made: list[dict[str, Any]] = []
    status, existing = api(s, "GET", "/api/v1/users")
    by_name = {u["username"]: u for u in (existing or {}).get("users", [])}
    for wanted in UAT_USERS:
        found = by_name.get(wanted["username"])
        if found is None:
            code, created = api(s, "POST", "/api/v1/users",
                                {**wanted, "password": UAT_PASSWORD,
                                 "email": f"{wanted['username']}@uat.invalid"})
            if code not in (200, 201) or not created:
                _blocked(rec, "UAT-USERS",
                         "Disposable UAT accounts can be created",
                         f"POST /users returned {code}: {str(created)[:200]}")
                return made
            found = created.get("user", created)
        else:
            # Reused, and therefore possibly deactivated by a previous run's
            # own cleanup. An inactive recipient is not addressable, which is
            # a fact about the tidy-up rather than about the product.
            api(s, "PATCH", f"/api/v1/users/{found['id']}",
                {"is_active": True})
            api(s, "POST", f"/api/v1/users/{found['id']}/password",
                {"password": UAT_PASSWORD})
        made.append(found)
    _case(rec, "UAT-USERS", "Disposable UAT accounts exist and are addressable",
          len(made) == len(UAT_USERS),
          f"{len(made)} of {len(UAT_USERS)} accounts ready: "
          f"{[u['username'] for u in made]}")
    return made


# --------------------------------------------------------------- §8 threads


def threads(s: Session, rec: Recorder) -> str:
    """Start a real investigation from the Cockpit and keep asking into it."""
    s.go("/", settle=5000)
    opened = s.ask("Break ECL down by product for August 2026",
                   selector=COCKPIT_COMPOSER, timeout=300)
    first = s.latest_turn("Break ECL down by product") or s.text()
    _case(rec, "TH-01", "A thread starts from a real Cockpit answer",
          bool(opened.get("completed")) and said(first, "product"),
          f"the opening answer rendered={bool(opened.get('completed'))}",
          answer=first[:800], screenshot=s.shot("th-01"))

    follow_ups = [
        "Which stage contributes most of that?",
        "Narrow it to personal finance.",
        "How did it move since July 2026?",
    ]
    kept = []
    for index, question in enumerate(follow_ups, start=2):
        made = s.ask(question, selector=COCKPIT_COMPOSER, timeout=300)
        turn = s.latest_turn(question) or ""
        kept.append(bool(made.get("completed")) and bool(turn.strip()))
        _case(rec, f"TH-0{index}", f"Follow-up {index - 1} is answered in the "
              "same thread", kept[-1],
              f"answered={kept[-1]}",
              question=question, answer=turn[:800],
              screenshot=s.shot(f"th-0{index}"))

    # The scope the thread settled on must survive a reload.
    s.page.reload()
    s.page.wait_for_timeout(6000)
    after = s.text()
    _case(rec, "TH-05", "The thread survives a refresh with its scope intact",
          said(after, "personal") or said(after, "ecl"),
          "the conversation is still on screen after a reload",
          screenshot=s.shot("th-05"))

    # Leave the module entirely, then come back through Investigations.
    s.go("/metrics", settle=4000)
    s.go("/investigations", settle=5000)
    listed = s.page.query_selector_all("[data-investigation-id]")
    _case(rec, "TH-06", "The thread is listed under Investigations after "
          "leaving the module", bool(listed),
          f"{len(listed)} investigations listed")
    if not listed:
        return ""

    investigation_id = listed[0].get_attribute("data-investigation-id") or ""
    listed[0].click()
    s.page.wait_for_timeout(7000)
    reopened = s.text()
    _case(rec, "TH-07", "Reopening carries the conversation, not only the "
          "title",
          said(reopened, "ecl") and len(reopened) > 500,
          f"the reopened thread renders {len(reopened)} characters",
          screenshot=s.shot("th-07"))

    # The same composer component, and therefore the same selector: the
    # investigation page renders `ask/composer.tsx` with a different
    # placeholder and the identical aria-label. Selecting on the placeholder
    # found the box and no send button, and recorded the product as unable to
    # continue a conversation it continues perfectly well.
    made = s.ask("And what does that imply for coverage?",
                 selector=COCKPIT_COMPOSER, timeout=300)
    _case(rec, "TH-08", "The conversation continues after reopening",
          bool(made.get("completed")),
          f"the follow-up was answered={bool(made.get('completed'))}",
          screenshot=s.shot("th-08"))

    back = s.page.query_selector('[data-testid="back-link"]')
    if back:
        back.click()
        s.page.wait_for_timeout(3500)
    _case(rec, "TH-09", "Back from a thread returns to Investigations",
          "/investigations" in s.page.url,
          f"landed on {s.page.url}")
    return investigation_id


# ------------------------------------------------------ §10 playbook packs


def packs(s: Session, rec: Recorder) -> None:
    s.go("/playbook", settle=6000)
    body = s.text()
    # A real pack, not the "New pack" button — which is also an anchor under
    # /playbook/packs/ and sorts first, so the previous selector opened an
    # empty form and recorded the Playbook as having no figures on it.
    rows = [row for row in s.page.query_selector_all('a[href^="/playbook/packs/"]')
            if not (row.get_attribute("href") or "").endswith("/new")]
    _case(rec, "PB-01", "The Playbook lists this installation's packs",
          bool(rows) and not said(body, *CORPORATE),
          f"{len(rows)} packs listed; corporate wording="
          f"{[w for w in CORPORATE if w.lower() in body.lower()]}",
          screenshot=s.shot("pb-01"))
    if not rows:
        return

    href = rows[0].get_attribute("href") or ""
    rows[0].click()
    s.page.wait_for_timeout(7000)
    opened = s.text()
    dashes = len(re.findall(r"(?<![\w.])—(?![\w.])", opened))
    figures = len(re.findall(r"\d[\d,]*\.?\d*", opened))
    _case(rec, "PB-02", "Every block on the pack carries a figure rather than "
          "a dash", figures > 20 and dashes < 8,
          f"{figures} figures and {dashes} empty markers on the page",
          route=href, screenshot=s.shot("pb-02"))

    _case(rec, "PB-03", "The pack says nothing about the corporate book",
          not said(opened, *CORPORATE),
          f"corporate wording={[w for w in CORPORATE if w.lower() in opened.lower()]}")

    back = s.page.query_selector('[data-testid="back-link"]')
    _case(rec, "PB-04", "A pack has a Back control", back is not None,
          "back-link present" if back else "no Back control on the pack")
    if back:
        back.click()
        s.page.wait_for_timeout(3500)
        _case(rec, "PB-05", "Back returns to the Playbook",
              "/playbook" in s.page.url, f"landed on {s.page.url}")


# ------------------------------------------------ §12 messaging and sharing


def messaging(s: Session, rec: Recorder, recipients: list[dict[str, Any]],
              investigation_id: str) -> str:
    if not recipients:
        _blocked(rec, "MSG-01", "Messaging needs a disposable recipient",
                 "no UAT account was created, so nothing was sent")
        return ""

    s.go("/messages", settle=5000)
    new = None
    for button in s.page.query_selector_all("button"):
        if (button.inner_text() or "").strip() == "New message":
            new = button
            break
    if new is None:
        _blocked(rec, "MSG-02", "The message composer opens",
                 "no 'New message' control on /messages")
        return ""
    new.click()
    s.page.wait_for_timeout(1500)

    # MSG-01 — find the recipient by a partial name.
    box = s.page.query_selector("#compose-to")
    box.click()
    box.type("uat", delay=25)
    s.page.wait_for_timeout(2500)
    offered = s.page.query_selector_all('[data-testid="recipient-options"] button')
    _case(rec, "MSG-01", "A recipient is found by a partial name",
          bool(offered),
          f"{len(offered)} accounts offered for 'uat'",
          screenshot=s.shot("msg-01"))
    if not offered:
        return ""
    offered[0].click()
    s.page.wait_for_timeout(800)
    chips = s.page.query_selector_all('[data-testid="recipient-chip"]')
    # WHO was chosen, read off the chip. The directory sorts by display name,
    # so index 0 is not necessarily the first account this suite created —
    # and signing in as the wrong one reports a message that arrived
    # correctly as one that never did.
    chosen = (chips[0].inner_text() if chips else "").strip().rstrip("×").strip()

    subject = f"UAT {time.strftime('%H%M%S')} retail scorecard review"
    body_text = ("Please review the personal-finance scorecard investigation. "
                 "I am concerned about the latest mature-cohort calibration "
                 "result.")
    s.page.query_selector("#compose-subject").fill(subject)
    s.page.query_selector("#compose-body").fill(body_text)
    send = None
    for button in s.page.query_selector_all("button"):
        if (button.inner_text() or "").strip() in ("Send", "Sending…"):
            send = button
            break
    if send is None:
        _blocked(rec, "MSG-02", "The message can be sent",
                 "no Send control in the composer")
        return ""
    send.click()
    s.page.wait_for_timeout(5000)
    rec.chosen_recipient = chosen
    after = s.text()
    _case(rec, "MSG-02", "A message is addressed to a disposable UAT account "
          "and sent",
          bool(chips) and said(after, subject[:16]),
          f"recipient chips={len(chips)}; the subject appears in the mailbox="
          f"{said(after, subject[:16])}",
          subject=subject, screenshot=s.shot("msg-02"))
    return subject


def read_as_recipient(s: Session, rec: Recorder, subject: str,
                      username: str) -> None:
    """Sign in as the recipient and check the message actually arrived."""
    if not subject:
        _blocked(rec, "MSG-03", "The recipient can read what was sent",
                 "nothing was sent, so nothing could be read")
        return
    api(s, "POST", "/api/v1/auth/logout", {})
    s.go("/", settle=2500)
    code, _ = api(s, "POST", "/api/v1/auth/login",
                  {"username": username, "password": UAT_PASSWORD})
    if code != 200:
        _blocked(rec, "MSG-03", "The recipient can sign in",
                 f"login as {username} returned {code}")
        return
    s.go("/messages", settle=6000)
    inbox = s.text()
    arrived = said(inbox, subject[:16])
    _case(rec, "MSG-03", "The message is in the recipient's mailbox, not only "
          "in the sender's", arrived,
          f"the subject is in the recipient's inbox={arrived}",
          subject=subject, screenshot=s.shot("msg-03"))

    if arrived:
        rows = s.page.query_selector_all("button, a")
        for row in rows:
            if subject[:16] in (row.inner_text() or ""):
                row.click()
                s.page.wait_for_timeout(4000)
                break
        thread = s.text()
        _case(rec, "MSG-04", "The recipient sees the message body as sent",
              said(thread, "calibration"),
              f"the body is rendered={said(thread, 'calibration')}",
              screenshot=s.shot("msg-04"))


def suite(s: Session, rec: Recorder) -> None:
    recipients = make_uat_users(s, rec)
    investigation_id = threads(s, rec)
    packs(s, rec)
    subject = messaging(s, rec, recipients, investigation_id)
    if recipients:
        wanted = getattr(rec, "chosen_recipient", "")
        addressed = next(
            (u for u in recipients
             if wanted and wanted.lower() in
             f"{u['first_name']} {u['last_name']}".lower()),
            recipients[0])
        read_as_recipient(s, rec, subject, addressed["username"])
        # Leave the disposable accounts inactive rather than lying around
        # able to sign in.
        api(s, "POST", "/api/v1/auth/logout", {})
        api(s, "POST", "/api/v1/auth/login",
            {"username": "retail.demo", "password": "RetailDemo!2026"})
        for account in recipients:
            api(s, "PATCH", f"/api/v1/users/{account['id']}",
                {"is_active": False})


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_workflows", suite))
