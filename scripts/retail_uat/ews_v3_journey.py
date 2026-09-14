"""Drive the v3 Early Warning journey in a real browser and report what is on
screen: portfolio interpretation, the Salaried / Non-Salaried levels, the
export into What-If Analysis, a scenario run under both methodologies, the
model tree, the model log and one version's full record.

Run it against a live stack:

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/ews_v3_journey.py

Screenshots land in docs/evidence/retail_ews_v3/. Anything it prints as a
count of zero is a page that did not render what it is supposed to.
"""
import sys, os, time
sys.path.insert(0, "scripts")
from retail_uat.driver import Session, FRONTEND, chromium_path
from playwright.sync_api import sync_playwright

OUT = "docs/evidence/retail_ews_v3"
os.makedirs(OUT, exist_ok=True)

def shot(page, name):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    print("   shot", name)

with sync_playwright() as play:
    b = play.chromium.launch(executable_path=chromium_path())
    ctx = b.new_context(viewport={"width": 1512, "height": 982})
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    s = Session(page, ctx)
    assert s.sign_in(), "sign-in failed"

    def go(route, wait, pause=5000):
        t = time.time()
        page.goto(FRONTEND + route, wait_until="commit")
        page.wait_for_selector(wait, timeout=120_000)
        page.wait_for_timeout(pause)
        print(f"   {route}  {time.time()-t:.2f}s")

    print("1. portfolio + AI interpretation")
    go("/early-warning", '[data-testid="ews-headline"]')
    print("   interpretation:", page.locator('[data-testid="ews-portfolio-interpretation"]').count())
    print("   text:", page.locator('[data-testid="ews-interpretation-text"]').first.inner_text()[:160])
    page.click('[data-testid="ews-interpretation-why"]')
    page.wait_for_timeout(800)
    print("   basis table:", page.locator('[data-testid="ews-interpretation-basis"]').count())
    shot(page, "01-portfolio-interpretation")

    print("2. product -> classifications")
    go("/early-warning?product=CREDIT_CARD", '[data-testid="ews-product-view"]')
    print("   classification cards:", page.locator('[data-testid^="ews-classification-SALARIED"]').count(),
          page.locator('[data-testid^="ews-classification-NON_SALARIED"]').count())
    print("   export buttons:", page.locator('[data-testid^="ews-export-"]').count())
    shot(page, "02-product-classifications")

    print("3. classification -> sub-products")
    go("/early-warning?product=CREDIT_CARD&cls=SALARIED", '[data-testid="ews-classification-view"]')
    print("   materiality:", page.locator('[data-testid="ews-classification-materiality"]').count())
    print("   sub cards:", page.locator('[data-testid^="ews-sub-CC_"]').count())
    shot(page, "03-classification-subproducts")

    print("4. sub-product")
    go("/early-warning?product=CREDIT_CARD&cls=SALARIED&sub=CC_PLATINUM",
       '[data-testid="ews-sub-product-view"]')
    shot(page, "04-subproduct")

    print("5. export to What-If")
    page.click('[data-testid="ews-export-sub-product"]')
    page.wait_for_selector('[data-testid="ews-whatif-thread"]', timeout=120_000)
    page.wait_for_timeout(6000)
    print("   url:", page.url)
    print("   source block:", page.locator('[data-testid="ews-whatif-source"]').count())
    print("   materiality:", page.locator('[data-testid="ews-whatif-materiality"]').inner_text()[:180].replace("\n"," | "))
    print("   baseline:", page.locator('[data-testid="ews-whatif-baseline"]').count(),
          "cuts:", page.locator('[data-testid^="ews-whatif-cut-"]').count())
    shot(page, "05-whatif-imported")

    print("6. run a scenario, both methods")
    page.click('[data-testid="ews-whatif-method-both"]')
    page.fill('[data-testid="ews-whatif-input"]', "Increase PIT 12-month PD by 20%")
    page.click('[data-testid="ews-whatif-run"]')
    page.wait_for_selector('[data-testid="ews-whatif-result"]', timeout=180_000)
    page.wait_for_timeout(4000)
    print("   levels:", page.locator('[data-testid^="ews-whatif-level-"]').count())
    print("   challenger:", page.locator('[data-testid="ews-whatif-challenger"]').count())
    print("   interpretation:", page.locator('[data-testid="ews-whatif-interpretation"]').inner_text()[:200].replace("\n"," "))
    shot(page, "06-whatif-result")

    print("7. model tree")
    go("/early-warning/model/tree", '[data-testid="ews-tree-root"]')
    print("   layers:", page.locator('[data-testid^="ews-tree-layer-"]').count())
    page.click('[data-testid="ews-tree-toggle-bureau"]')
    page.wait_for_timeout(1200)
    print("   bureau decay:", page.locator('[data-testid="ews-tree-bureau-decay"]').count())
    # The curve is drawn against the age of the pull, not as a trend: no
    # "latest value" and no movement, which a sparkline would invent.
    print("   decay curve:", page.locator('[data-testid="ews-tree-bureau-curve"]').count())
    shot(page, "07-model-tree")

    print("8. model log")
    go("/early-warning/model-log", '[data-testid="ews-version-table"]')
    print("   versions:", page.locator('[data-testid^="ews-version-"]').count())
    shot(page, "08-model-log")

    print("9. version detail")
    go("/early-warning/model-log/3.0.0", '[data-testid="ews-model-version-page"]', 8000)
    print("   cohorts:", page.locator('[data-testid^="ews-cohort-"]').count())
    print("   capture block:", page.locator('[data-testid="ews-cohort-capture-hard_trigger"]').count())
    print("   roc/gains/pr:", page.locator('[data-testid^="ews-roc-"]').count(),
          page.locator('[data-testid^="ews-gains-"]').count(),
          page.locator('[data-testid^="ews-pr-"]').count())
    print("   tie note:", page.locator('[data-testid^="ews-lift-note-"]').count())
    print("   comparison:", page.locator('[data-testid="ews-version-comparison"]').count())
    shot(page, "09-version-detail")

    print("10. the first version has nothing to compare against")
    go("/early-warning/model-log/2.0.0", '[data-testid="ews-model-version-page"]', 8000)
    print("   no-comparison notice:",
          page.locator('[data-testid="ews-version-no-comparison"]').count())
    print("   said:", page.locator('[data-testid="ews-version-no-comparison"]')
          .first.inner_text()[:160] if page.locator(
              '[data-testid="ews-version-no-comparison"]').count() else "—")
    shot(page, "10-first-version")

    print("\npage errors:", errs[:5])
    b.close()
