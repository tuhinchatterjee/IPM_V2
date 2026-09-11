"""
The browser driver the retail functionality audit runs on.

One authenticated Chromium session against the SAME frontend and backend the
retail launcher serves. No test-only route, no injected answer, no mocked
provider: a case passes here only if an ordinary user clicking the same controls
would see the same thing.

Everything a case needs is here so the individual suites stay about behaviour:
sign-in, the two composers, bounded waiting for an answer, network capture,
screenshots, and a small assertion recorder that writes one JSON evidence file
per suite.
"""

from __future__ import annotations

import glob
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "retail_functionality"
SHOTS = EVIDENCE / "screens"

FRONTEND = "http://localhost:5328"
BACKEND = "http://localhost:8328"
DEMO_USER = "retail.demo"
DEMO_PASSWORD = "RetailDemo!2026"

COCKPIT_COMPOSER = 'textarea[aria-label="Ask CreditProbe a question about the portfolio"]'
WHATIF_COMPOSER = 'textarea[data-testid="whatif-composer"]'

#: The submit button BELONGING to each composer, found from the composer
#: itself. A page-wide `button:has-text("Ask")` matched "Ask about this" in the
#: result above the box first: a whole conversation was driven by clicking a
#: suggestion, and the transcript recorded questions nobody typed.
SUBMIT_OF: dict[str, str] = {
    COCKPIT_COMPOSER: ('xpath=//textarea[@aria-label="Ask CreditProbe a question '
                       'about the portfolio"]/following-sibling::div//button'),
    WHATIF_COMPOSER: 'xpath=//textarea[@data-testid="whatif-composer"]/../button',
}

PASS, FAIL, BLOCKED, NOT_RUN, NA = "PASS", "FAIL", "BLOCKED", "NOT RUN", "NOT APPLICABLE"


def chromium_path() -> str | None:
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


@dataclass
class Case:
    """One functional case and what actually happened."""

    id: str
    module: str
    title: str
    status: str = NOT_RUN
    detail: str = ""
    expected: Any = None
    actual: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    defect: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "module": self.module, "title": self.title,
            "status": self.status, "detail": self.detail,
            "expected": self.expected, "actual": self.actual,
            "evidence": self.evidence, "seconds": round(self.seconds, 1),
            "defect": self.defect,
        }


class Recorder:
    """Collects cases and writes one evidence file per suite."""

    def __init__(self, suite: str):
        self.suite = suite
        self.cases: list[Case] = []
        self.started = time.time()

    def add(self, case: Case) -> Case:
        self.cases.append(case)
        mark = {PASS: "PASS", FAIL: "FAIL", BLOCKED: "BLOCKED",
                NOT_RUN: "NOT RUN", NA: "N/A"}[case.status]
        print(f"  [{mark:8s}] {case.id} {case.title[:66]}")
        if case.status not in (PASS, NA):
            print(f"             {case.detail[:200]}")
        return case

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, FAIL: 0, BLOCKED: 0, NOT_RUN: 0, NA: 0}
        for c in self.cases:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def write(self) -> Path:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE / f"{self.suite}.json"
        path.write_text(json.dumps({
            "suite": self.suite,
            "frontend": FRONTEND, "backend": BACKEND,
            "elapsed_seconds": round(time.time() - self.started, 1),
            "counts": self.counts(),
            "cases": [c.to_dict() for c in self.cases],
        }, indent=2, default=str))
        c = self.counts()
        print()
        print(f"  {c[PASS]} passed, {c[FAIL]} failed, {c[BLOCKED]} blocked, "
              f"{c[NOT_RUN]} not run, {c[NA]} n/a  ({time.time() - self.started:.0f}s)")
        print(f"  evidence {path.relative_to(ROOT)}")
        return path


class Session:
    """One signed-in browser session, with the helpers the cases need."""

    def __init__(self, page: Any, context: Any):
        self.page = page
        self.context = context
        self.api: list[tuple[str, str, int]] = []
        self.console_errors: list[str] = []
        page.on("pageerror", lambda e: self.console_errors.append(str(e)[:200]))
        page.on("requestfinished", self._record)

    def _record(self, request: Any) -> None:
        if "/api/v1" not in request.url:
            return
        try:
            status = request.response().status if request.response() else 0
        except Exception:  # noqa: BLE001
            status = 0
        self.api.append((request.method, request.url.split("/api/v1")[-1][:80], status))

    # -- navigation --------------------------------------------------------

    def sign_in(self) -> bool:
        """Sign in, and prove it — the absence of a form proves nothing.

        The failure this prevents: the check used to be "is the username field
        gone?". When the backend refused every CORS preflight the sign-in form
        never rendered at all, so the check passed instantly and a whole suite
        ran, and reported, against an application that was not signed in and
        could not reach its backend. A green run is worse than a red one.
        """
        self.page.goto(FRONTEND, wait_until="networkidle", timeout=90_000)
        self.page.wait_for_timeout(2000)
        if self.page.query_selector("#username") is not None:
            self.page.fill("#username", DEMO_USER)
            self.page.fill("#password", DEMO_PASSWORD)
            self.page.click('button[type="submit"]')
            self.page.wait_for_timeout(8000)
        return self.signed_in()

    def signed_in(self) -> bool:
        """True only when the page is the authenticated application."""
        if self.page.query_selector("#username") is not None:
            return False
        if not self.page.query_selector('a[href="/data-builder"]'):
            return False
        body = self.text()
        if "Cannot reach the CreditProbe backend" in body:
            return False
        return True

    def backend_reachable(self) -> bool:
        """Whether the BROWSER can reach the API — not whether curl can.

        A same-machine curl bypasses the origin check the browser makes, so it
        reports a healthy backend while every call from the page is refused at
        the preflight. This asks the question the user's browser asks.
        """
        return bool(self.page.evaluate(
            """async () => {
                 try {
                   const r = await fetch(%r + "/api/v1/health",
                                         {credentials: "include"});
                   return r.ok;
                 } catch (e) { return false; }
               }""" % BACKEND))

    def go(self, route: str, *, settle: int = 3500) -> bool:
        """Navigate the way a user does — by clicking the navigation link.

        The session lives in memory, so a fresh page load returns to the
        sign-in form; a test that navigated by URL would measure a login page.
        """
        link = self.page.query_selector(f'a[href="{route}"]')
        if link is None:
            return False
        link.click()
        self.page.wait_for_load_state("networkidle", timeout=90_000)
        self.page.wait_for_timeout(settle)
        return True

    def text(self) -> str:
        return self.page.inner_text("body")

    def shot(self, name: str) -> str:
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return str(path.relative_to(ROOT))

    # -- chat --------------------------------------------------------------

    def composer(self, selector: str = COCKPIT_COMPOSER) -> Any:
        return self.page.query_selector(selector)

    def ask(self, question: str, *, selector: str = COCKPIT_COMPOSER,
            send: str = "button", timeout: int = 240, settle_growth: int = 400,
            type_delay: int = 2) -> dict[str, Any]:
        """Type a question, submit it, and wait — bounded — for the answer.

        `send` is "button", "enter" or "none" (type only). Returns what
        happened: the elapsed time, the text before and after, the API calls
        the submission made, and whether it completed or timed out.
        """
        page = self.page
        box = page.query_selector(selector)
        if box is None:
            return {"submitted": False, "reason": "no composer", "seconds": 0.0}
        before = self.text()
        marker = len(before)
        box.click()
        box.type(question, delay=type_delay)
        page.wait_for_timeout(250)
        api_before = len(self.api)
        started = time.time()
        if send == "button":
            btn = self.submit_button(selector)
            if btn is None or not btn.is_enabled():
                return {"submitted": False, "reason": "send disabled",
                        "seconds": 0.0, "before": before}
            btn.click()
        elif send == "enter":
            page.keyboard.press("Enter")
        elif send == "none":
            return {"submitted": False, "reason": "typed only", "seconds": 0.0,
                    "before": before}

        deadline = started + timeout
        settled = False
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            body = self.text()
            if len(body) > marker + settle_growth and not _busy(body):
                settled = True
                break
        elapsed = time.time() - started
        after = self.text()
        return {
            "submitted": True, "completed": settled, "seconds": elapsed,
            "before": before, "after": after,
            "api": self.api[api_before:],
            "question": question,
            # Proof the transcript is answering the question that was typed and
            # not one the product suggested.
            "echoed": question[:60] in " ".join(after.split()),
        }

    def latest_turn(self, question: str) -> str:
        """The transcript BELOW the question just asked.

        A follow-up that says "Personal Finance" proves nothing if the answer
        above it already said so, so every scope assertion is made against this
        rather than against the whole page. Sliced at the question itself: a
        naive diff against the page before the submission drifts on the turn
        counter at the top ("2 messages" becomes "4 messages") and returns the
        whole transcript as though it were new.
        """
        body = self.text()
        needle = " ".join(str(question or "").split())[:70]
        at = body.rfind(needle) if needle else -1
        return body[at + len(needle):] if at >= 0 else body

    def submit_button(self, selector: str = COCKPIT_COMPOSER) -> Any:
        """The send button that belongs to this composer."""
        target = SUBMIT_OF.get(selector)
        return self.page.query_selector(target) if target else None


def _busy(body: str) -> bool:
    return any(w in body for w in ("Thinking", "Working", "Composing", "Running the analysis"))


def answer_region(body: str) -> str:
    """The conversation region of the page, without the shell."""
    start = body.find(" messages")
    if start > 0:
        start = body.rfind("\n", 0, start)
    end = body.find("Every answer carries a Trace")
    if start < 0:
        start = 0
    return body[start:end if end > start else len(body)]


def money(text: str) -> list[float]:
    """Every currency-looking number in a block of text."""
    out: list[float] = []
    for token in re.findall(r"[-+]?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def run_suite(suite: str, body: Callable[[Session, Recorder], None], *,
              viewport: tuple[int, int] = (1440, 900)) -> int:
    """Open one signed-in session and run a suite in it."""
    from playwright.sync_api import sync_playwright

    rec = Recorder(suite)
    exe = chromium_path()
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=exe)
        context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
        page = context.new_page()
        session = Session(page, context)
        if not session.sign_in():
            rec.add(Case("SIGNIN", "shell", "Sign in with the demonstration account",
                         status=FAIL, detail="the sign-in form is still present"))
            rec.write()
            browser.close()
            return 1
        rec.add(Case("SIGNIN", "shell", "Sign in with the demonstration account",
                     status=PASS, detail=f"signed in as {DEMO_USER}",
                     evidence={"screenshot": session.shot(f"{suite}-signed-in")}))
        try:
            body(session, rec)
        except Exception as e:  # noqa: BLE001 - a crash is a result, not a gap
            # Evidence has to survive the crash. A suite that dies halfway and
            # writes nothing leaves the cases it DID run unrecorded, and the
            # ones it never reached indistinguishable from passes.
            import traceback

            rec.add(Case(id="SUITE", module=suite,
                         title="The suite ran to the end",
                         status=FAIL,
                         detail=f"{type(e).__name__}: {e}",
                         evidence={"traceback": traceback.format_exc()[-2000:]}))
        finally:
            browser.close()
    rec.write()
    return 1 if rec.counts()[FAIL] else 0
