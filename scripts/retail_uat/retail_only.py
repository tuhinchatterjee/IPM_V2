"""
The retail-only content sweep RO-01 to RO-12, in a real browser.

Revision 3 §4 asks that no corporate example, seed, team, prompt or dataset
remain REACHABLE. Reading the code answers a different question. Three of the
findings this suite exists for were invisible to a code search that looked only
at the navigation:

* The **CRO Portfolio Lens** was a card on the Lenses index — one click from a
  navigation item — rendering "the wholesale book", sector concentration and
  largest-obligor share.
* **Agent Operations** published Ratings & Financials, Covenant & Collateral and
  the Relationship Graph as ACTIVE teams, in a product whose active catalogue
  publishes not one of the concepts they read.
* The **document library** shipped a Real Estate Sector Review owned by a Sector
  Credit Head.

Every case here opens the screen the way a user does and reads what is on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    BACKEND,
    FAIL,
    PASS,
    Case,
    Recorder,
    Session,
    run_suite,
)

MODULE = "retail-only"

#: Wording that means a corporate surface is on screen. Each is a phrase a
#: retail book cannot produce — not a word that merely appears in prose.
CORPORATE_PHRASES = (
    "wholesale book", "rating notch", "master scale", "sector stress",
    "largest obligor", "Ratings & Financials", "Covenant & Collateral",
    "Relationship Graph", "Real Estate", "Sector Credit Head",
    "Corporate Credit Committee", "Corporate IFRS 9", "XGBoost",
)

#: The routes a reader reaches from the navigation, and what each must not show.
ROUTES = (
    "/", "/lenses", "/documents", "/what-if", "/early-warning",
    "/early-warning/signals", "/borrower-360", "/playbook", "/projects",
    "/delivery", "/analyses", "/investigations", "/metrics", "/workspace",
    "/reviews", "/studio", "/ai-studio", "/scorecard-validation", "/trace",
    "/messages", "/workflow", "/data-builder",
)


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def _api(s: Session, path: str) -> dict:
    return s.page.evaluate(
        """async (url) => {
             const r = await fetch(url, {credentials: "include"});
             const t = await r.text();
             try { return {status: r.status, body: JSON.parse(t)}; }
             catch (e) { return {status: r.status, text: t.slice(0, 200)}; }
           }""", f"{BACKEND}/api/v1{path}")


def suite(s: Session, rec: Recorder) -> None:
    page = s.page
    origin = page.url.split("/")[0] + "//" + page.url.split("/")[2]

    # ------------------------------------------------ RO-01 the Lenses index
    opened = s.go("/lenses")
    body = s.text()
    offers_cro = bool(page.query_selector('a[href="/lenses/cro"]'))
    _case(rec, "RO-01",
          "The Lenses index does not offer the CRO Portfolio Lens, which reads "
          "the wholesale book",
          bool(opened) and not offers_cro,
          f"opened={opened}; CRO card offered={offers_cro}",
          screenshot=s.shot("ro-01-lenses"))

    # ------------------------------------------- RO-02 the CRO route directly
    page.goto(f"{origin}/lenses/cro", wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(2500)
    text = page.inner_text("body")
    fallback = page.query_selector('[data-testid="retired-screen"]')
    back = page.query_selector('[data-testid="retired-instead"]')
    wholesale = "The wholesale book as at" in text
    _case(rec, "RO-02",
          "A direct link to the CRO Portfolio Lens answers with a fallback "
          "rather than rendering the wholesale book",
          bool(fallback) and bool(back) and not wholesale,
          f"fallback={bool(fallback)}; link back={bool(back)}; "
          f"wholesale view rendered={wholesale}",
          screenshot=s.shot("ro-02-cro"))

    # --------------------------------------------- RO-03 the agent catalogue
    catalogue = _api(s, "/agentic/agents")
    payload = catalogue.get("body") or {}
    names = [a.get("business_name") for a in payload.get("agents", [])]
    labels = [d.get("label") for d in payload.get("domains", [])]
    retired = [n for n in ("Ratings & Financials", "Covenant & Collateral",
                           "Relationship Graph") if n in names or n in labels]
    _case(rec, "RO-03",
          "Agent Operations publishes no team whose subject matter this book "
          "does not contain",
          catalogue.get("status") == 200 and not retired,
          f"status={catalogue.get('status')}; {len(names)} teams served; "
          f"retired teams still published={retired}",
          teams=names, domains=labels)

    # ---------------------------------------------- RO-04 the Agent Ops page
    opened = s.go("/agent-operations")
    if not opened:
        page.goto(f"{origin}/agent-operations", wait_until="networkidle",
                  timeout=90_000)
        page.wait_for_timeout(3000)
    text = s.text()
    on_screen = [p for p in ("Ratings & Financials", "Covenant & Collateral",
                             "Relationship Graph") if p in text]
    _case(rec, "RO-04",
          "None of the retired teams is named on the Agent Operations screen",
          not on_screen, f"retired teams on screen={on_screen}",
          screenshot=s.shot("ro-04-agent-ops"))

    # -------------------------------------------------- RO-05 the Documents
    opened = s.go("/documents")
    text = s.text()
    corporate = [p for p in CORPORATE_PHRASES if p.lower() in text.lower()]
    names_book = "retail_facility_month" in text
    _case(rec, "RO-05",
          "Every seeded committee paper is retail and names the book and month "
          "it is drawn from",
          bool(opened) and not corporate and names_book,
          f"opened={opened}; corporate wording={corporate}; "
          f"dataset named on the cards={names_book}",
          screenshot=s.shot("ro-05-documents"))

    # ------------------------------------------- RO-06 one document workspace
    first = page.query_selector('a[href^="/documents/"]')
    if first:
        first.click()
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        text = s.text()
        corporate = [p for p in CORPORATE_PHRASES if p.lower() in text.lower()]
        back = page.query_selector('[data-testid="back-link"]')
        _case(rec, "RO-06",
              "An opened paper is retail throughout, and Back returns to the "
              "library",
              not corporate and bool(back),
              f"corporate wording={corporate}; back control={bool(back)}",
              screenshot=s.shot("ro-06-document"))
    else:
        _case(rec, "RO-06", "An opened paper is retail throughout", False,
              "no document card to open")

    # --------------------------------- RO-07..RO-12 every navigable route
    for index, route in enumerate(ROUTES, start=7):
        cid = f"RO-{index:02d}"
        opened = s.go(route)
        if not opened:
            page.goto(f"{origin}{route}", wait_until="networkidle",
                      timeout=90_000)
            page.wait_for_timeout(3000)
        text = s.text()
        found = [p for p in CORPORATE_PHRASES if p.lower() in text.lower()]
        _case(rec, cid,
              f"{route} shows no corporate example, team or terminology",
              not found, f"corporate wording found={found}" if found
              else "none of the retired vocabulary is on screen",
              route=route,
              screenshot=s.shot(f"{cid.lower()}{route.replace('/', '-') or '-home'}"))


if __name__ == "__main__":
    raise SystemExit(run_suite("retail_only", suite))
