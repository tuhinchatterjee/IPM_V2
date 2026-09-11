"""
§21, §22 and §25 — how it LOOKS, what it draws, and how long it takes.

Three things a demonstration is judged on that no API test can see.

**§21 — the screen.** Every route is opened at both laptop sizes and measured,
not eyeballed: does the page scroll sideways, is any text clipped by its own
box, is a control pushed off the viewport, is the composer reachable and its
Send enabled, is anything still a skeleton after the page has settled. The
measurements come from the layout engine — `scrollWidth` against
`clientWidth`, `scrollHeight` against `clientHeight` on each element, and the
bounding box of every button — so a finding is a fact about the rendered page
rather than an opinion about a screenshot. Screenshots are captured anyway,
because a number says something is wrong and a picture says what.

**§22 — chart discipline.** A yes/no answer, a single fact and a conceptual
explanation must NOT come with a chart; a 25-month trend, a product ranking
and a stage composition should. Drawing a bar chart of one number is how a
product looks like it is padding, and answering "what does Gini mean?" with a
graph is how it looks like it did not understand.

**§25 — the clock.** Every journey is timed and recorded. No SLA is invented;
what is asserted is only that nothing hangs for minutes and that a long
analysis says it is working.
"""

from __future__ import annotations

import re
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

MODULE = "visual"

#: The two laptop sizes §21 names.
SIZES = ((1440, 900), (1512, 982))

#: Every route a reader reaches from the navigation.
ROUTES = ("/", "/workspace", "/messages", "/projects", "/investigations",
          "/analyses", "/documents", "/lenses", "/metrics", "/early-warning",
          "/early-warning/signals", "/what-if", "/borrower-360",
          "/scorecard-validation", "/studio", "/data-builder", "/trace",
          "/playbook", "/reviews", "/workflow", "/agent-operations",
          "/ai-studio", "/users", "/settings")

#: What a still-loading screen leaves behind.
STILL_LOADING = ("Loading…", "Loading...", "Please wait", "Working…")

#: JavaScript that measures the page rather than describing it.
MEASURE = """
() => {
  const out = {overflow: document.documentElement.scrollWidth >
                         document.documentElement.clientWidth + 2,
              width: document.documentElement.scrollWidth,
              viewport: document.documentElement.clientWidth,
              clipped: [], offscreen: [], skeletons: 0};
  const seen = new Set();
  for (const el of document.querySelectorAll('*')) {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    if ((el.className || '').toString().includes('skeleton')) out.skeletons++;
    // Screen-reader-only labels are 1x1 with hidden overflow BY DESIGN — that
    // is what makes them invisible and still announced. Measuring them as
    // clipped text reported "Sign out" as a defect on all twenty-four routes,
    // and "Set password", "Deactivate" and "Reactivate" on Users. They are
    // the accessibility layer working, not a layout fault.
    if ((el.className || '').toString().includes('sr-only')) continue;
    if (el.clientWidth <= 1 || el.clientHeight <= 1) continue;
    // Text clipped by its own box, with no scroller and no ellipsis to say so.
    if (el.children.length === 0 && el.textContent.trim().length > 3) {
      const hiddenX = el.scrollWidth > el.clientWidth + 2;
      const hiddenY = el.scrollHeight > el.clientHeight + 2;
      const scrolls = ['auto', 'scroll'].includes(style.overflowX) ||
                      ['auto', 'scroll'].includes(style.overflowY);
      const says = style.textOverflow === 'ellipsis';
      if ((hiddenX || hiddenY) && !scrolls && !says && el.clientHeight > 0) {
        const text = el.textContent.trim().slice(0, 60);
        if (!seen.has(text)) { seen.add(text); out.clipped.push(text); }
      }
    }
    // A control the reader cannot reach because it is off the side.
    if (el.tagName === 'BUTTON' || el.tagName === 'A') {
      const box = el.getBoundingClientRect();
      if (box.width > 0 && (box.right > out.viewport + 2 || box.left < -2)) {
        const text = (el.textContent || '').trim().slice(0, 40);
        if (text) out.offscreen.push(text);
      }
    }
  }
  out.clipped = out.clipped.slice(0, 12);
  out.offscreen = [...new Set(out.offscreen)].slice(0, 12);
  return out;
}
"""


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def ask(s: Session, question: str, timeout: int = 300) -> tuple[str, float]:
    started = time.perf_counter()
    made = s.ask(question, selector=COCKPIT_COMPOSER, timeout=timeout)
    took = time.perf_counter() - started
    turn = s.latest_turn(question) or made.get("after", "")
    return (turn if made.get("completed") else ""), took


CHART = ("main svg.recharts-surface, main .recharts-wrapper, "
         'main [data-testid^="chart"]')


def charted(s: Session) -> int:
    """How many drawn visuals are on screen.

    Counted the way the cockpit suite counts them — the same selector, so the
    two suites cannot disagree about whether a chart exists. Reading it with a
    selector of its own found none where the cockpit found five.
    """
    return len(s.page.query_selector_all(CHART))


def axis_labels(s: Session) -> list[str]:
    """The x-axis tick text of the last chart drawn.

    A 25-month trend names two months in its PROSE and twenty-five on its
    axis, so a check that reads only the text sees a two-point series.
    """
    ticks = s.page.query_selector_all(
        "main .recharts-xAxis .recharts-cartesian-axis-tick-value")
    return [(t.inner_text() or "").strip() for t in ticks]


def suite(s: Session, rec: Recorder) -> None:
    timings: dict[str, float] = {}

    # ===================================================== §21 both viewports
    for width, height in SIZES:
        s.page.set_viewport_size({"width": width, "height": height})
        label = f"{width}x{height}"
        overflowing: dict[str, int] = {}
        clipped: dict[str, list[str]] = {}
        offscreen: dict[str, list[str]] = {}
        stuck: list[str] = []
        for route in ROUTES:
            started = time.perf_counter()
            s.go(route, settle=3000)
            s.settle_for(lambda: len(s.text()) > 400, seconds=45)
            timings[f"{route} @{label}"] = round(time.perf_counter() - started, 1)
            measured = s.page.evaluate(MEASURE)
            if measured["overflow"]:
                overflowing[route] = measured["width"] - measured["viewport"]
            if measured["clipped"]:
                clipped[route] = measured["clipped"]
            if measured["offscreen"]:
                offscreen[route] = measured["offscreen"]
            body = s.text()
            if any(w in body for w in STILL_LOADING) or measured["skeletons"]:
                # Give a slow route a second chance before calling it stuck:
                # a skeleton one second after navigation is the product
                # working, and only one that outlives the wait is a defect.
                s.page.wait_for_timeout(6000)
                again = s.page.evaluate(MEASURE)
                if any(w in s.text() for w in STILL_LOADING) or again["skeletons"]:
                    stuck.append(route)
            s.shot(f"vis-{label}-{route.strip('/').replace('/', '-') or 'home'}")

        _case(rec, f"VIS-{label}-01",
              f"No screen scrolls sideways at {label}", not overflowing,
              f"routes wider than the viewport={overflowing or 'none'}",
              overflow=overflowing)
        _case(rec, f"VIS-{label}-02",
              f"No text is clipped by its own box at {label}", not clipped,
              f"routes with clipped text={sorted(clipped) or 'none'}",
              clipped=clipped)
        _case(rec, f"VIS-{label}-03",
              f"No control is pushed off the screen at {label}",
              not offscreen,
              f"routes with an unreachable control={sorted(offscreen) or 'none'}",
              offscreen=offscreen)
        _case(rec, f"VIS-{label}-04",
              f"No screen is still loading after it has settled at {label}",
              not stuck, f"routes still loading={stuck or 'none'}")

    s.page.set_viewport_size({"width": SIZES[0][0], "height": SIZES[0][1]})

    # ----------------------------------------- the composer, at both sizes
    unreachable: list[str] = []
    for width, height in SIZES:
        s.page.set_viewport_size({"width": width, "height": height})
        s.go("/", settle=4000)
        s.settle_for(lambda: s.composer() is not None, seconds=45)
        composer = s.composer()
        if composer is None:
            unreachable.append(f"{width}x{height}: no composer")
            continue
        box = composer.bounding_box() or {}
        if box.get("y", 0) + box.get("height", 0) > height + 2 or box.get("x", 0) < 0:
            unreachable.append(f"{width}x{height}: the composer is off-screen")
        composer.fill("What is ECL coverage?")
        button = s.submit_button()
        if button is not None and not button.is_enabled():
            unreachable.append(f"{width}x{height}: Send is disabled with text typed")
        composer.fill("")
    _case(rec, "VIS-05", "The composer is reachable and its Send is live at "
          "both laptop sizes", not unreachable,
          f"problems={unreachable or 'none'}", screenshot=s.shot("vis-05"))

    s.page.set_viewport_size({"width": SIZES[0][0], "height": SIZES[0][1]})

    # ============================================== §22 chart discipline
    s.go("/", settle=5000)
    quiet = [
        ("CHT-01", "Are there any Stage 3 home-finance facilities in August "
                   "2026?", "a yes/no question"),
        ("CHT-02", "What does Gini mean?", "a conceptual explanation"),
        ("CHT-03", "What is ECL coverage at August 2026?", "a single fact"),
    ]
    for cid, question, why in quiet:
        before = charted(s)
        answer, took = ask(s, question)
        timings[question] = round(took, 1)
        drawn = charted(s) > before
        _case(rec, cid, f"No chart is drawn for {why}",
              bool(answer) and not drawn,
              f"answered={bool(answer)}; charts before={before} after="
              f"{charted(s)}",
              question=question, answer=answer[:700],
              screenshot=s.shot(cid.lower()))

    drawn_expected = [
        ("CHT-04", "Show the 25-month weighted ECL trend for credit cards.",
         "a 25-month trend"),
        ("CHT-05", "Show expected credit loss by product at August 2026.",
         "a product ranking"),
        ("CHT-06", "Break August 2026 exposure into Stage 1, Stage 2 and "
                   "Stage 3.", "a stage composition"),
    ]
    for cid, question, why in drawn_expected:
        before = charted(s)
        answer, took = ask(s, question)
        timings[question] = round(took, 1)
        s.settle_for(lambda: charted(s) > before, seconds=30)
        drawn = charted(s) > before
        _case(rec, cid, f"A chart is offered for {why}",
              bool(answer) and drawn,
              f"answered={bool(answer)}; charts before={before} after="
              f"{charted(s)}",
              question=question, answer=answer[:700],
              screenshot=s.shot(cid.lower()))

    # The trend must read in date order, not in the order the rows arrived.
    # Read off the chart's AXIS: the prose names the endpoints and the axis
    # carries the series, so a check that reads the text sees two points.
    before = charted(s)
    ask(s, "Show the 25-month weighted ECL trend for credit cards.")
    s.settle_for(lambda: charted(s) > before, seconds=30)
    labels = [t for t in axis_labels(s) if t]
    months = [t for t in labels if re.fullmatch(r"\d{4}-\d{2}", t)]
    ordered = months == sorted(months)
    _case(rec, "CHT-07", "The trend reads in date order",
          bool(months) and ordered,
          f"{len(months)} months on the axis, in order={ordered}; "
          f"axis reads {labels[:4]} … {labels[-2:]}",
          months=months, screenshot=s.shot("cht-07"))

    # ==================================================== §25 the clock
    for route, question in (("/early-warning/signals", None),
                            ("/borrower-360", None),
                            ("/scorecard-validation", None),
                            ("/what-if", None)):
        started = time.perf_counter()
        s.go(route, settle=2500)
        s.settle_for(lambda: len(s.text()) > 900, seconds=90)
        timings[f"{route} (cold)"] = round(time.perf_counter() - started, 1)

    slow = {k: v for k, v in timings.items() if v > 120}
    _case(rec, "PERF-01", "Nothing takes minutes", not slow,
          f"journeys over two minutes={slow or 'none'}", timings=timings)

    worst = sorted(timings.items(), key=lambda kv: -kv[1])[:8]
    _case(rec, "PERF-02", "The slowest journeys are recorded for the handover",
          True, "; ".join(f"{k} {v}s" for k, v in worst), all_timings=timings)


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_visual", suite))
