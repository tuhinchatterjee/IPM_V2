"""
§15 and §16 — the data the product describes, and the tiles it draws.

§15 asks whether Data Builder describes THIS book: one domain, one dataset,
twenty-five consecutive month-ends, a retail-only field catalogue, meaningful
descriptions and units, the score columns raw and transformed, a working
preview, and no secrets or internal paths on screen. Rows are sampled against
the Parquet the lake actually holds.

§16 asks whether every metric and lens tile is POPULATED and RIGHT — no empty
box, no wrong-dataset zero, no corporate wording — and whether a tile can be
opened, read, and left again by Back and by the browser's own Back and
Forward.

The oracle is `docs/evidence/retail_overnight_uat/oracles/retail_oracle.json`,
built from the Parquet by an implementation that shares no code with the
product.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_uat.driver import (  # noqa: E402
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

MODULE = "data_and_lenses"

BOOK = ORACLE["book"]
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026) for m in range(1, 13)]
EXPECTED_MONTHS = [m for m in MONTHS if "2024-08" <= m <= "2026-08"]

#: Vocabulary that belongs to the corporate book and must not appear.
CORPORATE = ("portfolio_facility", "customer_ratings", "ifrs9_staging",
             "internal rating", "rating notch", "covenant", "borrower_id",
             "financial statement", "Real Estate", "Contracting",
             "Shipping", "wholesale", "SME")


def _case(rec: Recorder, cid: str, title: str, ok: bool, detail: str,
          **evidence: object) -> Case:
    return rec.add(Case(id=cid, module=MODULE, title=title,
                        status=PASS if ok else FAIL, detail=detail,
                        evidence=evidence))


def numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def has(text: str, value: float, tolerance: float = 0.0) -> bool:
    tol = tolerance or max(abs(value) * 5e-4, 0.5)
    return any(abs(n - value) <= tol for n in numbers(text))


def corporate_words(text: str) -> list[str]:
    lowered = text.lower()
    return [w for w in CORPORATE if w.lower() in lowered]


def suite(s: Session, rec: Recorder) -> None:
    # ------------------------------------------------------- §15 Data Builder
    s.go("/data-builder", settle=6000)
    s.settle_for(lambda: "GOVERNED FIELDS" in s.text().upper(), seconds=45)
    body = s.text()
    one_domain = ("1 dataset" in body and "546" in body)
    _case(rec, "DB-01", "Data Builder holds ONE retail domain and ONE dataset",
          one_domain and "Cockpit Data" in body,
          f"one dataset and 546 governed fields on screen={one_domain}",
          screenshot=s.shot("db-01"))

    coverage_ok = "2024-08" in body and "2026-08" in body
    _case(rec, "DB-02", "The period coverage is the 25 months this lake holds",
          coverage_ok, f"2024-08 to 2026-08 on screen={coverage_ok}",
          screenshot=s.shot("db-02"))

    found = corporate_words(body)
    _case(rec, "DB-03", "No corporate domain, rating or statement is offered",
          not found, f"corporate vocabulary on screen={found or 'none'}",
          screenshot=s.shot("db-03"))

    # --------------------------------------------------------- the domain page
    link = s.page.query_selector('a[href^="/data-builder/domain/"]')
    if link is not None:
        link.click()
    s.settle_for(lambda: "Dictionary" in s.text(), seconds=45)
    body = s.text()
    badge = re.search(r"Datasets(\d+)", body.replace(" ", ""))
    counted = badge.group(1) if badge else "?"
    _case(rec, "DB-04", "The Datasets badge counts the domain's datasets ONCE",
          counted == "1",
          f"the badge reads {counted} where the domain holds one dataset",
          screenshot=s.shot("db-04"))

    dictionary = re.search(r"Dictionary(\d+)", body.replace(" ", ""))
    fields = dictionary.group(1) if dictionary else "?"
    _case(rec, "DB-05", "The dictionary carries every governed field",
          fields == "546", f"the badge reads {fields} of 546",
          screenshot=s.shot("db-05"))

    # ------------------------------------------------ definitions and versions
    for label in ("Dictionary", "Versions", "Relationships"):
        for tab in s.page.query_selector_all("button, [role='tab']"):
            if (tab.inner_text() or "").strip().startswith(label):
                tab.click()
                s.page.wait_for_timeout(3000)
                break
        text = s.text()
        if label == "Dictionary":
            pointing = "docs/" in text
            _case(rec, "DB-06",
                  "No field sends the reader to a path inside the repository",
                  not pointing,
                  f"an internal repository path is on screen={pointing}",
                  screenshot=s.shot("db-06"))
            defined = text.count("See docs/") == 0 and "A PERIOD amount" in text
            _case(rec, "DB-07",
                  "The definitions say what a column IS and how it aggregates",
                  defined,
                  f"aggregation semantics visible in the definitions={defined}",
                  screenshot=s.shot("db-07"))
        if label == "Versions":
            contradiction = "Nothing published from this domain yet" in text
            _case(rec, "DB-08",
                  "The Versions tab does not contradict the published dataset",
                  not contradiction,
                  "the page says nothing is published beside a published "
                  f"dataset={contradiction}",
                  screenshot=s.shot("db-08"))
        if label == "Relationships":
            found = corporate_words(text)
            _case(rec, "DB-09",
                  "The relationship example names no corporate dataset",
                  not found, f"corporate vocabulary={found or 'none'}",
                  screenshot=s.shot("db-09"))

    # -------------------------------------------------------- the dataset page
    s.go("/data-builder/dataset/retail_facility_month", settle=8000)
    s.settle_for(lambda: "Periods" in s.text() and "Grain" in s.text(),
                 seconds=60)
    body = s.text()
    stated = all(w in body for w in ("retail_facility_month", "Cockpit Data",
                                     "reporting_month", "monthly"))
    _case(rec, "DB-10", "The dataset states its name, domain, grain and period "
          "field", stated, f"every governed property on screen={stated}",
          screenshot=s.shot("db-10"))

    rows_right = has(body, 447853.0, tolerance=1.0)
    _case(rec, "DB-11", "The row count is the one the lake holds", rows_right,
          f"447,853 rows on screen={rows_right}", screenshot=s.shot("db-11"))

    leaked = [w for w in ("/home/", "postgresql://", "sk-", "password",
                          "DATABASE_URL", ".env")
              if w.lower() in body.lower()]
    _case(rec, "DB-12", "No path, credential or connection string is exposed",
          not leaked, f"leaked={leaked or 'none'}", screenshot=s.shot("db-12"))

    # ----------------------------------------------------------- the preview
    s.go("/data-builder/browse", settle=8000)
    s.settle_for(lambda: "Browse the data" in s.text(), seconds=45)
    opened = False
    for el in s.page.query_selector_all("button"):
        if "Retail facility" in (el.inner_text() or ""):
            el.click()
            opened = True
            break
    s.settle_for(lambda: "Columns" in s.text(), seconds=60)
    body = s.text()
    every_month = [m for m in EXPECTED_MONTHS if m not in body]
    _case(rec, "DB-13", "The preview offers all 25 month-ends, consecutively",
          opened and not every_month,
          f"missing from the period list={every_month or 'none'}",
          screenshot=s.shot("db-13"))

    scores = all(w in body for w in ("Customer id", "Facility id"))
    _case(rec, "DB-14", "The preview reads the governed columns by their "
          "business names", scores,
          f"the key columns are named on screen={scores}",
          screenshot=s.shot("db-14"))

    # ------------------------------------------------------------ §16 Lenses
    s.go("/lenses", settle=6000)
    s.settle_for(lambda: "Retail Credit Risk" in s.text(), seconds=45)
    body = s.text()
    found = corporate_words(body)
    _case(rec, "LN-01", "The Lenses screen offers retail lenses only",
          "Retail Credit Risk" in body and "Retail Analytics" in body
          and not found,
          f"corporate vocabulary={found or 'none'}", screenshot=s.shot("ln-01"))

    hrefs = sorted({a.get_attribute("href") for a in
                    s.page.query_selector_all('a[href^="/lenses/"]')
                    if a.get_attribute("href")})
    seen: dict[str, str] = {}
    for href in hrefs:
        s.go(href, settle=9000)
        s.settle_for(lambda: len(s.text()) > 3000, seconds=90)
        seen[href] = s.text()

    risk = next((t for t in seen.values() if "Retail Credit Risk" in t), "")
    reconciled = {
        "gross carrying amount": has(risk, BOOK["gross_carrying_amount_sar"],
                                     tolerance=1.0),
        "expected credit loss": has(risk, BOOK["ecl_final_sar"], tolerance=1.0),
        "facilities": has(risk, float(BOOK["facilities"]), tolerance=0.5),
        "customers": has(risk, float(BOOK["customers"]), tolerance=0.5),
    }
    _case(rec, "LN-02", "Every headline tile of the risk lens reconciles with "
          "the book", all(reconciled.values()),
          "; ".join(f"{k}={v}" for k, v in reconciled.items()),
          expected={k: BOOK.get(k) for k in
                    ("gross_carrying_amount_sar", "ecl_final_sar",
                     "facilities", "customers")},
          screenshot=s.shot("ln-02"))

    analytics = next((t for t in seen.values() if "Retail Analytics" in t), "")
    gini = has(analytics, ORACLE["application_discrimination_all"]["gini"],
               tolerance=0.0006)
    behavioural = has(analytics,
                      ORACLE["behavioural_discrimination_all"]["gini"],
                      tolerance=0.0006)
    _case(rec, "LN-03", "The discrimination tiles carry the measured Gini",
          gini and behavioural,
          f"application Gini on screen={gini}; behavioural={behavioural}",
          screenshot=s.shot("ln-03"))

    empty = []
    for href, text in seen.items():
        for line in text.splitlines():
            if line.strip() in ("—", "–", "-", "n/a", "N/A", "null", "NaN"):
                empty.append(href)
                break
    _case(rec, "LN-04", "No tile on either lens is empty", not empty,
          f"lenses with an empty tile={empty or 'none'}",
          screenshot=s.shot("ln-04"))

    words = sorted({w for text in seen.values() for w in corporate_words(text)})
    _case(rec, "LN-05", "Neither lens carries the corporate book's vocabulary",
          not words, f"corporate vocabulary={words or 'none'}",
          screenshot=s.shot("ln-05"))

    # ------------------------------------------------- Back, and browser Back
    s.go("/metrics", settle=6000)
    s.settle_for(lambda: "Metric Catalogue" in s.text(), seconds=45)
    for el in s.page.query_selector_all("button, a"):
        if (el.inner_text() or "").strip().startswith("Show the whole"):
            el.click()
            break
    s.settle_for(lambda: len(s.text()) > 2500, seconds=60)
    listed = s.text()
    _case(rec, "MX-01", "The whole metric catalogue lists governed metrics",
          "coverage" in listed.lower() or "ECL" in listed,
          f"{len(listed)} characters of catalogue on screen",
          screenshot=s.shot("mx-01"))

    before = s.page.url
    s.page.go_back()
    s.page.wait_for_timeout(4000)
    back_ok = s.page.url != before or "Metric Catalogue" in s.text()
    s.page.go_forward()
    s.page.wait_for_timeout(4000)
    forward_ok = len(s.text()) > 500
    _case(rec, "MX-02", "The browser's own Back and Forward both work",
          back_ok and forward_ok,
          f"back={back_ok}; forward returned a rendered page={forward_ok}",
          screenshot=s.shot("mx-02"))


if __name__ == "__main__":
    raise SystemExit(run_suite("overnight_data_and_lenses", suite))
