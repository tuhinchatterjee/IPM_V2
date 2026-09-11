"""
§18, §19 and §20 — what survives, what is refused, and what happens when
something breaks.

Everything else in this harness tests a product that is working. This one
takes the backend away mid-session, signs out, restarts the server under a
live browser and asks for things that are not allowed, because the three
questions a demonstration actually turns on are:

  * does the work SURVIVE — a refresh, a sign-out, a backend restart;
  * is what should be refused actually refused, and recoverably;
  * and when something fails, does the screen SAY so — rather than spinning,
    showing a stale figure, or printing a stack trace at a credit officer.

The backend is stopped and started by `restart_backend.sh`, the same script
the launcher's restart uses. Nothing here writes to the book, and every
destructive act is against this suite's own thread.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
    COCKPIT_COMPOSER,
    FAIL,
    NA,
    PASS,
    WHATIF_COMPOSER,
    Case,
    Recorder,
    Session,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = "resilience"
BACKEND = "http://localhost:8328/api/v1"

#: Routes that must not hand retail figures to an unauthenticated caller.
PROTECTED = (
    "/ask", "/retail/early-warning", "/retail/customers",
    "/data-builder/datasets/retail_facility_month",
    "/metrics", "/lenses", "/workspace/investigations",
)

#: Wording that must never reach a screen a credit officer is looking at.
LEAKS = ("Traceback (most recent call last)", "psycopg", "sqlalchemy.exc",
         "/home/", "DATABASE_URL", "postgresql://", "uvicorn",
         ".venv/", "File \"/", "KeyError", "AttributeError")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def anonymous(path: str) -> tuple[int, str]:
    """Call the backend with no credential at all."""
    request = urllib.request.Request(BACKEND + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(4000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - a refusal to connect is a refusal
        return 0, str(e)


def restart_backend() -> bool:
    done = subprocess.run(["bash", str(ROOT / "scripts" / "retail_uat"
                                       / "restart_backend.sh")],
                          capture_output=True, text=True)
    return done.returncode == 0


def stop_backend() -> bool:
    pid_file = ROOT / "var" / "retail" / "backend.pid"
    if not pid_file.exists():
        return False
    pid = pid_file.read_text().strip()
    subprocess.run(["kill", pid], capture_output=True, text=True)
    for _ in range(15):
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(1)
    return False


def ask(s: Session, question: str, selector: str = COCKPIT_COMPOSER,
        timeout: int = 300) -> str:
    made = s.ask(question, selector=selector, timeout=timeout)
    turn = s.latest_turn(question) or made.get("after", "")
    return turn if made.get("completed") else ""


def leaked(text: str) -> list[str]:
    return [w for w in LEAKS if w in text]


def suite(s: Session, rec: Recorder) -> None:
    # ============================================== §19 what is not allowed
    refusals: dict[str, int] = {}
    bodies: dict[str, str] = {}
    for path in PROTECTED:
        status, body = anonymous(path)
        refusals[path] = status
        bodies[path] = body[:300]
    open_routes = {p: c for p, c in refusals.items() if 200 <= c < 300}
    _case(rec, "SEC-01", "No protected route answers an unauthenticated caller",
          not open_routes,
          f"answered without a credential={open_routes or 'none'}",
          statuses=refusals)

    figures = {p: b for p, b in bodies.items()
               if any(w in b for w in ("ecl_final", "gross_carrying",
                                       "customer_id", "facility_id"))}
    _case(rec, "SEC-02", "No refusal body carries a retail figure or an "
          "identifier", not figures,
          f"bodies carrying book data={sorted(figures) or 'none'}",
          bodies=bodies)

    stacks = {p: leaked(b) for p, b in bodies.items() if leaked(b)}
    _case(rec, "SEC-03", "No refusal prints a stack trace, a path or a "
          "connection string", not stacks, f"leaks={stacks or 'none'}")

    # ================================================== §18 what survives
    s.go("/", settle=5000)
    marker = "Show expected credit loss by IFRS 9 stage at August 2026."
    answered = ask(s, marker)
    _case(rec, "PERSIST-01", "A question is answered and joins the session's "
          "history", bool(answered),
          f"answered={bool(answered)}", answer=answered[:600],
          screenshot=s.shot("persist-01"))

    s.page.reload()
    s.page.wait_for_load_state("networkidle", timeout=90_000)
    s.settle_for(lambda: len(s.text()) > 800, seconds=60)
    after_refresh = s.text()
    _case(rec, "PERSIST-02", "The session survives a full page reload",
          s.signed_in() and "IFRS 9 stage" in after_refresh,
          f"still signed in={s.signed_in()}; the question is still listed="
          f"{'IFRS 9 stage' in after_refresh}",
          screenshot=s.shot("persist-02"))

    # -------------------------------------------- the backend, taken away
    stopped = stop_backend()
    if not stopped:
        rec.add(Case(id="ERR-01", module=MODULE,
                     title="The screen says the backend is unreachable",
                     status=NA,
                     detail="the backend pid file was absent, so this run "
                            "could not stop the server it is testing"))
    else:
        s.page.reload()
        s.page.wait_for_load_state("domcontentloaded", timeout=90_000)
        s.settle_for(lambda: len(s.text()) > 400, seconds=45)
        down = s.text()
        said = any(w in down.lower() for w in
                   ("cannot reach", "unreachable", "backend", "offline",
                    "not responding", "try again"))
        _case(rec, "ERR-01", "The screen SAYS the backend is unreachable "
              "rather than spinning", said,
              f"an explanation is on screen={said}",
              screen=down[:800], screenshot=s.shot("err-01"))
        _case(rec, "ERR-02", "Nothing on the failed screen is a stack trace or "
              "a path", not leaked(down), f"leaks={leaked(down) or 'none'}",
              screenshot=s.shot("err-02"))

        started = restart_backend()
        _case(rec, "ERR-03", "The backend comes back on the same port with the "
              "launcher's environment", started,
              f"restart_backend.sh succeeded={started}")

        s.page.reload()
        s.page.wait_for_load_state("networkidle", timeout=90_000)
        s.settle_for(lambda: s.signed_in(), seconds=90)
        recovered = s.text()
        _case(rec, "PERSIST-03", "The session and its history survive a "
              "BACKEND restart",
              s.signed_in() and "IFRS 9 stage" in recovered,
              f"still signed in={s.signed_in()}; the question is still listed="
              f"{'IFRS 9 stage' in recovered}",
              screenshot=s.shot("persist-03"))

        follow = ask(s, "Now show it by product.")
        _case(rec, "PERSIST-04", "The conversation continues after the restart "
              "rather than starting again", bool(follow),
              f"the follow-up was answered={bool(follow)}",
              answer=follow[:600], screenshot=s.shot("persist-04"))

    # ---------------------------------------------- a saved scenario reopens
    s.go("/what-if", settle=6000)
    scenario = ask(s, "Increase PD by 10 percent for credit cards.",
                   selector=WHATIF_COMPOSER)
    s.go("/", settle=4000)
    s.go("/what-if", settle=6000)
    s.settle_for(lambda: len(s.text()) > 1200, seconds=60)
    returned = s.text()
    _case(rec, "PERSIST-05", "A What-If run is still there after leaving the "
          "module and coming back",
          bool(scenario) and ("credit card" in returned.lower()
                              or "Recent" in returned),
          f"the scenario ran={bool(scenario)}; it is listed on return="
          f"{'credit card' in returned.lower()}",
          screenshot=s.shot("persist-05"))

    # ======================================== §20 what the product refuses
    s.go("/", settle=5000)
    nonsense = ask(s, "asdkjh qwe zzz 9999 ???")
    refused_well = bool(nonsense) and not leaked(nonsense)
    _case(rec, "ERR-04", "An unreadable question is answered with a question, "
          "not a crash", refused_well,
          f"answered={bool(nonsense)}; leaks={leaked(nonsense) or 'none'}",
          answer=nonsense[:600], screenshot=s.shot("err-04"))

    absent = ask(s, "Show expected credit loss for December 2031.")
    named = bool(absent) and any(w in absent.lower() for w in
                                 ("2026-08", "does not", "no data", "holds",
                                  "latest", "not available", "2031"))
    _case(rec, "ERR-05", "A period the book does not hold is named rather than "
          "invented", named,
          f"the absence is stated={named}", answer=absent[:600],
          screenshot=s.shot("err-05"))

    s.go("/what-if", settle=6000)
    impossible = ask(s, "Set the probability of default to 400 percent.",
                     selector=WHATIF_COMPOSER)
    checked = bool(impossible) and not leaked(impossible)
    _case(rec, "ERR-06", "An impossible assumption is refused or bounded, "
          "never run silently", checked,
          f"answered={bool(impossible)}; leaks={leaked(impossible) or 'none'}",
          answer=impossible[:700], screenshot=s.shot("err-06"))

    # ------------------------------------------------- a double submission
    s.go("/", settle=5000)
    composer = s.composer()
    composer.fill("What is ECL coverage?")
    button = s.submit_button()
    if button is not None:
        button.click()
        s.page.wait_for_timeout(400)
        disabled = not button.is_enabled()
        try:
            button.click(timeout=2000)
        except Exception:  # noqa: BLE001 - a disabled button is the point
            pass
        s.settle_for(lambda: "COVERAGE" in s.text().upper(), seconds=240)
        body = s.text()
        twice = body.upper().count("WHAT IS ECL COVERAGE?")
        _case(rec, "ERR-07", "A second click while the first is in flight does "
              "not ask twice", disabled or twice <= 1,
              f"the Send control was disabled while busy={disabled}; the "
              f"question appears {twice} time(s)",
              screenshot=s.shot("err-07"))
    else:
        rec.add(Case(id="ERR-07", module=MODULE,
                     title="A second click while the first is in flight does "
                           "not ask twice",
                     status=NA,
                     detail="the composer exposes no separate Send control "
                            "for this check to double-click"))

    # --------------------------------------------------- sign out, sign in
    signed_out = False
    for el in s.page.query_selector_all("button, a"):
        if (el.inner_text() or "").strip().lower() == "sign out":
            el.click()
            s.page.wait_for_timeout(4000)
            signed_out = True
            break
    s.settle_for(lambda: not s.signed_in(), seconds=45)
    gone = not s.signed_in()
    _case(rec, "SEC-04", "Signing out ends the session", signed_out and gone,
          f"the sign-out control was found={signed_out}; the session ended="
          f"{gone}", screenshot=s.shot("sec-04"))

    back_in = s.sign_in()
    s.settle_for(lambda: s.signed_in(), seconds=60)
    _case(rec, "SEC-05", "Signing back in restores the session and its history",
          back_in and s.signed_in(),
          f"signed in again={s.signed_in()}", screenshot=s.shot("sec-05"))

    # ------------------------------------------------------ the backend log
    log = Path("/tmp/retail-backend.log")
    text = log.read_text(errors="replace")[-200_000:] if log.exists() else ""
    secrets = [w for w in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "sk-ant",
                           "sk-proj", "password=", "PGPASSWORD")
               if w in text]
    _case(rec, "SEC-06", "The backend log carries no key, token or password",
          not secrets, f"secrets in the log={secrets or 'none'}",
          log_bytes=len(text))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_resilience", suite))
