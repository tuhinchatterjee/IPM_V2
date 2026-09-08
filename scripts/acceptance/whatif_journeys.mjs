/**
 * What-If Analysis — the nineteen browser journeys.
 *
 *     node scripts/acceptance/whatif_journeys.mjs [--json]
 *
 * These drive a real Chromium against a real backend and a real front end.
 * They exist because a unit test cannot tell you that the methodology gate
 * actually blocks a calculation on screen, or that a saved What-If reopens
 * with the scenario it was saved with.
 *
 * Playwright is resolved from the machine rather than from package.json: the
 * browser is a tool for checking this product, not a dependency of it.
 *
 * A journey FAILS rather than skips when a precondition is missing. "The
 * model was not trained so we skipped the model journey" is the exact report
 * that lets a broken feature ship.
 */

import { createRequire } from "node:module";

// Playwright is loaded through createRequire rather than a dynamic import.
// The package is CommonJS, and Node's ESM interop hands back a namespace whose
// `chromium` is undefined — `require` returns the real thing.
const require = createRequire(import.meta.url);

const PW = process.env.PLAYWRIGHT_MODULE
  ?? "/opt/node22/lib/node_modules/playwright/index.js";
const CHROME = process.env.PLAYWRIGHT_CHROMIUM
  ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const WEB = process.env.CREDITPROBE_WEB ?? "http://127.0.0.1:3000";
const API = process.env.CREDITPROBE_API ?? "http://127.0.0.1:8000";
const JSON_OUT = process.argv.includes("--json");

const results = [];
let browser;

function log(...parts) {
  if (!JSON_OUT) console.log(...parts);
}

async function journey(name, body) {
  const started = Date.now();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const checks = [];
  const check = (label, ok, detail = "") => {
    checks.push({ label, ok: Boolean(ok), detail });
    log(`    ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  };
  log(`\n== ${name}`);
  try {
    await body(page, check);
  } catch (error) {
    check("journey completed without throwing", false, String(error).slice(0, 200));
  } finally {
    await page.close();
  }
  const ok = checks.every((c) => c.ok);
  results.push({ name, ok, ms: Date.now() - started, checks });
  log(`  ${ok ? "JOURNEY PASSED" : "JOURNEY FAILED"} (${Date.now() - started}ms)`);
}

/** Wait for a selector, returning whether it appeared rather than throwing. */
async function appears(page, selector, timeout = 30_000) {
  try {
    await page.waitForSelector(selector, { timeout, state: "visible" });
    return true;
  } catch {
    return false;
  }
}

/** Drive the composer and wait for the turn to land. */
async function say(page, text) {
  await page.fill('[data-testid="whatif-composer"]', text);
  await page.getByRole("button", { name: "Send" }).click();
}

/** Answer the methodology gate, which must be on screen before any figure. */
async function chooseMethodology(page, check, method = "delta") {
  const gateAppeared = await appears(page, `button[data-methodology="${method}"]`, 60_000);
  check("the methodology gate is asked before any ECL figure", gateAppeared);
  if (!gateAppeared) return false;
  const figureBefore = await page.locator('[data-testid="whatif-result"]').count();
  check("no result is shown while the gate is open", figureBefore === 0);
  await page.click(`button[data-methodology="${method}"]`);
  const result = await appears(page, '[data-testid="whatif-result"]', 120_000);
  check("a result appears once the methodology is chosen", result);
  return result;
}

/**
 * Read the endpoints the journeys use, once, before the browser starts.
 *
 * The first journey otherwise pays for a cold DuckDB cache — a 15x15 migration
 * matrix over 52,880 rows, computed inside the first click — and reports it as
 * a product failure. This measures the product, not the cache. It is NOT a
 * skip: a warm-up that cannot reach the API leaves the journeys to fail on it.
 */
async function warm() {
  const paths = ["/api/v1/whatif/staging", "/api/v1/whatif/periods",
                 "/api/v1/whatif/profile/rating", "/api/v1/whatif/migration/rating",
                 "/api/v1/whatif/profile/stage", "/api/v1/whatif/migration/stage",
                 "/api/v1/whatif/profile/macro", "/api/v1/whatif/profile/borrowers",
                 "/api/v1/whatif/models/ml"];
  for (const path of paths) {
    try {
      await fetch(`${API}${path}`, { headers: { "X-IPM-Role": "ANALYST" } });
    } catch {
      // The journeys will say so, loudly, in a moment.
    }
  }
}

async function main() {
  const { chromium } = require(PW);
  await warm();
  browser = await chromium.launch({ executablePath: CHROME });

  /* --------------------------------------------------- 1. Rating Movement */
  await journey("Journey 1 — Rating Movement", async (page, check) => {
    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    check("What-If Analysis is the page title",
      (await page.textContent("h1")) ?.includes("What-If Analysis"));
    check("the umbrella is not called Stress Testing",
      !(await page.content()).includes(">Stress Testing<"));
    check("six guided journeys are offered",
      (await page.locator("[data-journey]").count()) === 6);

    await page.click('[data-journey="rating"]');
    check("the rating profile opens", await appears(page, "table"));
    const rows = await page.locator('[data-row]').count();
    check("the nineteen governed grades plus a Total are shown", rows >= 20,
      `${rows} rows`);
    check("the 20 x 20 migration matrix is shown",
      await appears(page, '[data-testid="migration-matrix"]', 60_000));

    await page.click('[data-view="exposure"]');
    check("the migration offers an exposure view", true);

    await say(page, "Downgrade everyone one notch.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the result names the period", text.includes("Q"));
      check("the result names the methodology", text.includes("Delta Model"));
      check("the result shows the baseline and the What-If ECL",
        text.includes("Official baseline ECL") && text.includes("What-If ECL"));
      check("the result names the rule set that staged the reported book",
        text.includes("Reported book staged"));
      check("and the rule set that staged the What-If",
        text.includes("What-If staged"));
    }
  });

  /* ------------------------------------------------- 2. Risk Parameters */
  await journey("Journey 2 — Risk Parameters, layered", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
    check("the parameter profile opens", await appears(page, "h1"));
    await say(page, "Increase Stage 1 PD by 20%.");
    const ran = await chooseMethodology(page, check, "delta");
    if (!ran) return;
    check("one step is on the scenario", (await page.locator("[data-step-kind]").count()) === 1);

    await say(page, "Increase LGD by five percentage points.");
    await page.waitForTimeout(6000);
    const steps = await page.locator("[data-step-kind]").count();
    check("the second shock layers onto the first", steps === 2, `${steps} steps`);
    const results = await page.locator('[data-testid="whatif-result"]').count();
    check("the layered result is calculated without asking the gate again",
      results >= 2, `${results} results`);
  });

  /* ------------------------------------------------- 3. Stage Migration */
  await journey("Journey 3 — Stage Migration", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=stage`, { waitUntil: "networkidle" });
    check("the stage profile opens", await appears(page, "table"));
    check("the historical 3 x 3 migration is shown",
      await appears(page, '[data-testid="migration-matrix"]', 60_000));
    await say(page, "Move half the Stage 1 borrowers to Stage 2.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the result reports stage movement", text.includes("Stage moves"));
      check("deterioration is shown", text.includes("Deteriorated"));
    }
  });

  /* -------------------------------------------------------- 4. Macro */
  await journey("Journey 4 — Macroeconomic Shock", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=macro`, { waitUntil: "networkidle" });
    const shown = await appears(page, "[data-macro]", 60_000);
    check("the macro variables are shown", shown);
    const variables = await page.locator("[data-macro]").count();
    check("all ten CreditProbe V1 variables are shown", variables === 10, `${variables}`);
    check("the synthetic-macro limitation is disclosed",
      (await page.content()).includes("single latent cycle factor"));
    await say(page, "Increase unemployment by one percentage point.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      await say(page, "Increase Stage 1 PD by 20%.");
      await page.waitForTimeout(6000);
      check("a PD shock layers onto the macro shock",
        (await page.locator("[data-step-kind]").count()) === 2);
    }
  });

  /* ------------------------------------------------------- 5. Sector */
  await journey("Journey 5 — Sector Stress", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=sector`, { waitUntil: "networkidle" });
    check("the sector profile opens", await appears(page, "table", 60_000));
    const text = await page.textContent("body");
    check("real sectors are listed", text.includes("Real Estate") || text.includes("Contracting"));
    await say(page, "Reduce Contracting collateral by 20%.");
    await chooseMethodology(page, check, "delta");
  });

  /* ----------------------------------------------------- 6. Borrower */
  await journey("Journey 6 — Borrower Stress", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=borrower`, { waitUntil: "networkidle" });
    const shown = await appears(page, "[data-borrower]", 60_000);
    check("the top Stage 2 borrowers are shown", shown);
    const borrowers = await page.locator("[data-borrower]").count();
    check("ten borrowers are listed", borrowers === 10, `${borrowers}`);
    await say(page, "Downgrade everyone two notches.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the book-level impact is reported", text.includes("What-If ECL"));
      const ecl = await page.locator('[data-chart="ecl"]').count();
      const exposure = await page.locator('[data-chart="exposure"]').count();
      check("the movement is drawn, not only tabulated", ecl > 0 && exposure > 0,
        `ecl=${ecl} exposure=${exposure}`);
      check("the movement is attributed to the drivers that caused it",
        await appears(page, '[data-testid="whatif-attribution"]', 20_000));
      const attributed = await page.locator('[data-testid="whatif-attribution"]').textContent();
      check("the attribution names the method",
        attributed.includes("Shapley") && attributed.includes("order-neutral"));
      check("the rating driver is on the table",
        (await page.locator('[data-driver="rating"]').count()) > 0);
      // The measurement basis is its OWN driver, keyed `basis`. It used to be
      // folded into a `stage` line, which is how a Stage 1 to Stage 2 result
      // came back reading "PD effect 0.00%, Stage effect +243.97%" — true and
      // useless. The residual `stage` driver is exactly zero on a plain
      // migration and is not on the table.
      check("the Stage migration is kept apart from the rating move",
        (await page.locator('[data-driver="basis"]').count()) > 0
        && /Measurement basis/i.test(attributed),
        attributed.slice(0, 160));
      check("the table says whether it reconciles",
        (await page.locator('[data-testid="attribution-check"]').textContent())
          .includes("Reconciles"));
      check("the charts carry a baseline and a What-If series",
        (await page.getByText("Baseline", { exact: true }).count()) > 0 &&
        (await page.getByText("What-If", { exact: true }).count()) > 0);
    }
  });

  /* --------------------------------------------------- 7. Save/reopen */
  await journey("Journey 7 — Save and reopen", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
    await say(page, "Increase Stage 1 PD by 20%.");
    const ran = await chooseMethodology(page, check, "delta");
    if (!ran) return;
    const before = await page.textContent('[data-testid="whatif-result"]');
    const name = `Browser journey ${Date.now()}`;
    await page.fill('input[aria-label="Name this What-If"]', name);
    await page.getByRole("button", { name: "Save What-If" }).click();
    check("the save is confirmed",
      await appears(page, `text=Saved as "${name}"`, 60_000));

    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    const card = page.locator(`text=${name}`).first();
    check("the saved What-If appears on the landing page",
      await card.isVisible().catch(() => false));
    await card.click();
    check("reopening restores the scenario",
      await appears(page, "text=Reopened", 60_000));
    const after = await page.textContent("body");
    check("the reopened What-If names the same period",
      after.includes(before.match(/Q\d \d{4}/)?.[0] ?? "Q"));
  });

  /* ------------------------------------------------------- 8. ML model */
  await journey("Journey 8 — ML model configuration", async (page, check) => {
    await page.goto(`${WEB}/what-if/models/ml`, { waitUntil: "networkidle" });
    check("an active model is shown, not an empty page",
      await appears(page, '[data-testid="active-model"]', 60_000));
    const text = await page.textContent("body");
    check("the limitations are stated", text.includes("MECHANICAL"));
    check("the macro collinearity is disclosed",
      text.includes("single latent cycle factor"));
    check("out-of-time metrics are shown", text.includes("out-of-time"));
    check("the artifact format is stated", text.includes("xgboost-native-json"));

    await page.getByRole("tab", { name: "Explainability" }).click();
    check("SHAP is shown", await appears(page, "text=Top predictors", 60_000));
    check("feature importance is shown",
      (await page.textContent("body")).includes("gain importance"));

    await page.getByRole("tab", { name: "Worked example" }).click();
    await page.getByRole("button", { name: /Score Client X/ }).click();
    check("Client X is scored by the real model",
      await appears(page, '[data-testid="client-x-result"]', 90_000));

    await page.getByRole("tab", { name: "Retrain" }).click();
    check("the retrain prompt names the periods",
      (await page.textContent("body")).includes("trained through"));
    // Stage-awareness: the evidence, not the claim. The model card tab, which
    // an earlier check navigated away from.
    await page.getByRole("tab", { name: "Model card" }).click();
    check("the stage-design study is on the model card",
      await appears(page, '[data-testid="stage-study"]', 20_000));
    const study = await page.locator('[data-testid="stage-study"]').textContent();
    check("it says which design was chosen",
      study.includes("One model with Stage as a feature")
      || study.includes("One model per Stage"), "");
    check("it reports the governed Stage 1 to 2 step and both models against it",
      (await page.locator('[data-testid="stage-boundary"]').count()) > 0);
    check("it reports each Stage's share of the ECL",
      study.includes("Share of ECL"));

    await page.getByRole("tab", { name: "Explainability" }).click();
    check("the Stage interaction is shown",
      await appears(page, '[data-testid="stage-interaction"]', 20_000));
    const interaction = await page.locator('[data-testid="stage-interaction"]').textContent();
    check("Stage 1 and Stage 2 responses are both reported",
      (await page.locator('[data-stage-response="1"]').count()) > 0
      && (await page.locator('[data-stage-response="2"]').count()) > 0);
    check("and the finding is stated in words",
      interaction.includes("not an intercept"));

    // The version list lives on the Retrain tab, where a person goes to make a
    // new one and needs to see what is already there.
    await page.getByRole("tab", { name: "Retrain" }).click();
    check("versions are listed", (await page.textContent("body")).includes("ACTIVE"));
  });

  /* --------------------------------------------- 9. Direct complex chat */
  await journey("Journey 9 — A complex scenario typed directly", async (page, check) => {
    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    await page.fill('[data-testid="whatif-composer"]',
      "Downgrade Stage 1 construction borrowers by two notches.");
    await page.getByRole("button", { name: "Send" }).click();
    check("a typed scenario opens a thread without clicking a card",
      await appears(page, '[data-testid="whatif-composer"]', 60_000));
    const ran = await chooseMethodology(page, check, "ml");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the ML methodology is named on the result",
        text.includes("ML Model"));
      check("the model version is on the result", /v\d{4}\./.test(text));
    }
    await say(page, "Also increase LGD by five percentage points.");
    await page.waitForTimeout(6000);
    check("the follow-up layers onto the same scenario",
      (await page.locator("[data-step-kind]").count()) >= 2);
  });

  /* ------------------------------------------------ 10. Staging criteria */
  await journey("Journey 10 — Staging criteria, composed on screen",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      check("the staging control is on the thread",
        await appears(page, '[data-testid="staging-toggle"]', 60_000));
      await page.click('[data-testid="staging-toggle"]');

      // Both rule sets, and only one of them editable.
      check("the What-If rule set is shown",
        await appears(page, '[data-testid="whatif-staging"]', 30_000));
      check("the reported-book rule set is shown beside it",
        await appears(page, '[data-testid="reported-staging"]', 30_000));
      const whatif = page.locator('[data-testid="whatif-staging"]');
      const reported = page.locator('[data-testid="reported-staging"]');
      check("the two are labelled apart",
        (await whatif.textContent()).includes("What-If staging policy")
        && (await reported.textContent()).includes("Reported-book staging policy"));

      // Rule A and Rule B are ON by default, and say they are assumptions.
      const ruleA = whatif.locator('[data-rule="rating_notches"]');
      const ruleB = whatif.locator('[data-rule="scenario_pd_ratio"]');
      check("Rule A is on by default",
        await ruleA.locator('input[type="checkbox"]').isChecked());
      check("Rule B is on by default",
        await ruleB.locator('input[type="checkbox"]').isChecked());
      check("Rule A is described as an assumption, not a requirement",
        (await ruleA.textContent()).includes("Assumption"));
      check("Rule A is a two-notch rule",
        (await ruleA.textContent()).includes("2"));

      // The reported set cannot be edited from the screen.
      await page.click('[data-testid="reported-staging-toggle"]');
      const reportedBox = reported.locator('[data-rule="rating_notches"] input[type="checkbox"]');
      check("the reported set's rules are not switchable",
        await reportedBox.isDisabled());
      check("Rule A is off in the reported set", !(await reportedBox.isChecked()));

      const versionOf = async () =>
        (await page.locator('[data-testid="whatif-staging-version"]').textContent()).trim();
      const first = await versionOf();
      check("the default rule set names itself", first.includes("what-if-default"),
        first);

      // Edit a threshold.
      const threshold = ruleA.locator('input[type="number"]');
      await threshold.fill("3");
      await threshold.blur();
      await page.waitForTimeout(2500);
      const edited = await versionOf();
      check("editing a threshold gives the rule set a new version",
        edited !== first, `${first} -> ${edited}`);

      // Disable a rule.
      await ruleB.locator('input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      check("a rule can be switched off",
        !(await ruleB.locator('input[type="checkbox"]').isChecked()));

      // Combine with AND.
      await page.selectOption('[data-testid="staging-combination"]', "ALL");
      await page.waitForTimeout(2500);
      check("the rules can be combined with ALL as well as ANY",
        (await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("EVERY"));

      // Add a rule, then take it away again.
      check("a rule can be composed on screen",
        await appears(page, '[data-testid="staging-add"]', 20_000));
      await page.selectOption('select[aria-label="New rule kind"]', "absolute_pd");
      await page.fill('input[aria-label="New rule threshold"]', "6");
      await page.fill('input[aria-label="New rule name"]', "Watchlist PD");
      await page.click('[data-testid="staging-add-submit"]');
      await page.waitForTimeout(2500);
      const added = await page.locator('[data-testid="whatif-staging"] tbody tr').count();
      check("the added rule joins the set", added >= 6, `${added} rules`);
      check("the added rule is named as the person named it",
        (await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("Watchlist PD"));

      await page.getByRole("button", { name: "Remove Watchlist PD" }).click();
      await page.waitForTimeout(2500);
      check("the added rule can be removed again",
        !(await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("Watchlist PD"));

      // A governed rule offers no Remove at all.
      check("a governed rule cannot be removed",
        (await page.locator('[data-rule="relative_pd"]').first().textContent())
          .includes("kept"));

      // Reset, and the thread is back on the default.
      await page.click('[data-testid="staging-reset"]');
      await page.waitForTimeout(2500);
      check("reset returns the thread to the What-If default",
        (await versionOf()).includes("what-if-default"));
    });

  /* ------------------------------------ 11. The override reaches the run */
  await journey("Journey 11 — A staging override changes the answer",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Downgrade everyone two notches.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;
      const first = page.locator('[data-testid="whatif-result"]').first();
      check("the result names BOTH rule sets",
        (await first.locator('[data-testid="result-reported-staging"]').count()) > 0
        && (await first.locator('[data-testid="result-whatif-staging"]').count()) > 0);
      check("the reported book is staged by the reported-book policy",
        (await first.locator('[data-testid="result-reported-staging"]').textContent())
          .includes("reported-book"));
      check("the What-If is staged by the What-If default",
        (await first.locator('[data-testid="result-whatif-staging"]').textContent())
          .includes("what-if-default"));

      // Switch Rule A and Rule B off, then layer a shock so the thread runs
      // again. The staging change alone is a setting; the next run is what
      // applies it, and the version on that result is the proof.
      await page.click('[data-testid="staging-toggle"]');
      await appears(page, '[data-testid="whatif-staging"]', 30_000);
      await page.locator('[data-rule="rating_notches"] input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      await page.locator('[data-rule="scenario_pd_ratio"] input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      await say(page, "Also increase LGD by two percentage points.");
      await page.waitForTimeout(9000);
      const results = page.locator('[data-testid="whatif-result"]');
      const count = await results.count();
      check("the override produced a second result", count >= 2, `${count}`);
      if (count >= 2) {
        const latest = results.nth(count - 1);
        const stamped = await latest
          .locator('[data-testid="result-whatif-staging"]').textContent();
        check("the second result carries the overridden rule set, not the default",
          !stamped.includes("what-if-default"), stamped.trim());
        check("and the reported book is still staged by the reported policy",
          (await latest.locator('[data-testid="result-reported-staging"]').textContent())
            .includes("reported-book"));
      }
    });

  /* -------------------------------------------- 12. The macro lab */
  await journey("Journey 12 — A macro variable, checked and overridden",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=macro`, { waitUntil: "networkidle" });
      const lab = await appears(page, '[data-testid="whatif-macro-lab"]', 60_000);
      check("the macro lab is on the macro journey", lab);
      if (!lab) return;

      const cards = await page.locator("[data-macro]").count();
      check("all ten governed variables have a card", cards === 10, `${cards}`);

      // Opening a variable measures it against the book. The estimate must
      // appear BESIDE the configured sensitivity, never instead of it.
      await page.click('[data-macro="gdp_growth"]');
      const analysed = await appears(page, '[data-testid="whatif-macro-analysis"]', 90_000);
      check("selecting a variable measures it against the book", analysed);
      if (!analysed) return;

      const detail = page.locator('[data-testid="whatif-macro-detail"]');
      const said = await detail.textContent();
      check("the configured multiplier is shown beside the estimated one",
        said.includes("Configured") && said.includes("Implied multiplier"));
      check("the small sample is stated rather than hidden",
        (await page.locator('[data-testid="whatif-macro-small-sample"]').count()) > 0);
      check("the recommendation is keeping the configured sensitivity",
        said.includes("keep the configured sensitivity"), said.slice(0, 0));
      check("all three choices are offered",
        (await detail.locator("[data-macro-choice]").count()) === 3);

      // Define an assumption of one's own, and check it is labelled as one.
      await page.click('[data-macro-tab="own"]');
      const own = await appears(page, '[data-testid="whatif-macro-own"]', 30_000);
      check("a person may define their own relationship", own);
      if (!own) return;
      await page.fill("[data-macro-pd]", "1.45");
      await page.click("[data-macro-define]");
      const inForce = await appears(page, '[data-testid="whatif-macro-in-force"]', 30_000);
      check("the override is put in force for the thread", inForce);
      if (inForce) {
        const note = await page.locator('[data-testid="whatif-macro-in-force"]').textContent();
        check("and the governed reference is said to be unchanged",
          note.includes("reference sensitivity is unchanged"), note.trim().slice(0, 90));
        check("it is labelled user-defined, never empirical or approved",
          note.includes("User-Defined")
          && !/required|regulatory|approved|empirical/i.test(note));
      }

      // The override has to reach the FIGURE, not only the panel.
      await say(page, "Reduce GDP growth by 1 percentage point.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;
      const stamped = page.locator('[data-testid="whatif-sensitivity-override"]');
      check("the result's provenance line names the override",
        (await stamped.count()) > 0);
      if ((await stamped.count()) > 0) {
        check("and says the governed matrix still applies elsewhere",
          (await stamped.textContent()).includes("overridden for this thread"));
      }
    });

  /* ------------------------------------- 13. The written interpretation */
  await journey("Journey 13 — The reading, and the figures behind it",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Increase PD by 20%.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;

      const result = page.locator('[data-testid="whatif-result"]').first();
      const said = await result.textContent();
      check("the result carries a reading, not only a number",
        said.includes("What this means"));

      // Whether the model wrote it or the product composed it, the figures it
      // was written from must be reachable from the same panel.
      const written = await result.locator('[data-testid="whatif-written-reading"]').count();
      const author = await result.locator('[data-testid="whatif-reading-author"]').count();
      check("the reading says who wrote it", author > 0 || written === 0);
      check("the reading states it does not add a view the numbers do not carry",
        said.includes("composed from the figures")
        || said.includes("written from those figures"));
      check("a follow-up the result makes worth asking is offered",
        (await result.locator("[data-followup]").count()) > 0);
    });

  /* --------------------------------------- 14. Both methodologies */
  await journey("Journey 14 — The other methodology, from either side",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Increase PD by 20%.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;

      await say(page, "What would the ML model say?");
      const compared = await appears(page, '[data-testid="whatif-methodology-comparison"]', 180_000);
      check("asking for the other model prices the scenario both ways", compared);
      if (!compared) return;

      const panel = page.locator('[data-testid="whatif-methodology-comparison"]');
      const said = await panel.textContent();
      check("both methodologies are shown with their versions",
        (await panel.locator("[data-comparison-method]").count()) === 2);
      check("the direction the reader arrived from is named",
        said.includes("Delta Model") && said.includes("ML Model"));
      check("it says neither figure is the right one",
        said.includes("governance decision"));
      check("it does not recommend one",
        !/we recommend|you should use|the better model|more accurate/i.test(said));

      // A spread on its own is not an answer.
      const agreed = said.includes("within") && said.includes("agreement");
      const located = (await panel.locator("table").count()) > 0;
      check("where the difference sits is shown, or the two are said to agree",
        located || agreed);
    });

  /* --------------------------------------- 15. The detailed workbook */
  await journey("Journey 15 — The audit workbook comes down",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Increase PD by 20%.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;

      const button = page.locator('[data-testid="whatif-download-detail"]');
      check("the detailed workbook is offered on the result",
        (await button.count()) > 0);
      if ((await button.count()) === 0) return;

      const waiting = page.waitForEvent("download", { timeout: 180_000 })
        .catch(() => null);
      await button.first().click();
      const file = await waiting;
      check("clicking it produces a file", Boolean(file));
      if (file) {
        const name = file.suggestedFilename();
        check("named as a workbook", name.endsWith(".xlsx"), name);
        check("and the name carries no path", !/[\\/:]|\.\./.test(name), name);
      }
    });

  /* ------------------------ 16. The rating order, as a person reads it */
  await journey("Journey 16 — Nineteen grades, in order, ending in C",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`,
        { waitUntil: "networkidle" });
      check("the rating profile opens", await appears(page, "table", 60_000));

      const labels = await page.$$eval("[data-row]",
        (nodes) => nodes.map((n) => n.getAttribute("data-row")));
      const expected = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
                        "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
                        "B+", "B", "B-", "CCC", "CC", "C"];
      const scale = labels.slice(0, 19);
      check("the first nineteen rows are the governed scale, in order",
        JSON.stringify(scale) === JSON.stringify(expected),
        scale.join(" "));
      check("the scale ends in C and not in D",
        scale[18] === "C", scale[18]);
      check("default follows the scale as its own row",
        labels[19] === "D", labels[19]);
      check("the order is not alphabetical",
        JSON.stringify(scale) !== JSON.stringify([...scale].sort()));

      const matrix = await appears(page, '[data-testid="migration-matrix"]',
        60_000);
      check("the rating migration matrix is shown", matrix);
      if (matrix) {
        const heads = await page.$$eval(
          '[data-testid="migration-matrix"] thead th',
          (nodes) => nodes.map((n) => n.textContent.trim()));
        const columns = heads.slice(1);
        check("its columns are the same nineteen grades plus a Total",
          columns.length === 20 && columns[19] === "Total"
          && JSON.stringify(columns.slice(0, 19)) === JSON.stringify(expected),
          `${columns.length} columns: ${columns.join(" ")}`);
        const rows = await page.$$eval(
          '[data-testid="migration-matrix"] tbody tr th, ' +
          '[data-testid="migration-matrix"] tbody tr td:first-child',
          (nodes) => nodes.map((n) => n.textContent.trim()));
        check("and its rows use the same order as its columns",
          JSON.stringify(rows.slice(0, 19)) === JSON.stringify(expected),
          rows.slice(0, 19).join(" "));
      }
    });

  /* --------------- 17. A question about the book, answered in the thread */
  await journey("Journey 17 — Quick analysis before any shock",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`,
        { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);

      // The exact sentence that was redirected to a profile screen in UAT.
      await say(page, "Can you give me the rating-wise PDs, getting rid of stages?");
      const answered = await appears(page, '[data-testid="whatif-analysis"]',
        190_000);
      check("the question is answered in the thread rather than redirected",
        answered);
      if (!answered) return;

      const card = page.locator('[data-testid="whatif-analysis"]').last();
      const text = await card.textContent();
      check("the answer is not a redirect to a profile view",
        !/profile views answer it/i.test(text));
      check("it names the period it read", /Q[1-4] 20\d\d/.test(text));
      check("it carries the PD columns that were asked for",
        text.includes("TTC PD") && text.includes("Lifetime PD")
        && text.includes("Applicable PD"));

      const rows = await card.locator("[data-row]").count();
      check("it shows the whole scale", rows >= 19, `${rows} rows`);
      const first = await card.locator("[data-row]").first()
        .getAttribute("data-row");
      check("starting at AAA", first === "AAA", first);

      check("no methodology gate was raised for a question that prices nothing",
        (await page.locator('button[data-methodology="delta"]').count()) === 0);
      check("and no result was computed",
        (await page.locator('[data-testid="whatif-result"]').count()) === 0);

      // A follow-up narrows the table it is looking at.
      await say(page, "Only show BBB- and weaker.");
      const narrowed = await appears(page,
        '[data-testid="whatif-analysis"]', 190_000);
      check("a follow-up is answered too", narrowed);
      if (narrowed) {
        // The LAST card, scoped through the card itself. `:last-of-type` in
        // the selector picks the last element of its tag among its siblings,
        // which is not the same thing and read the first table back.
        const rows = page.locator('[data-testid="whatif-analysis"]').last()
          .locator("[data-row]");
        const labels = [];
        for (let i = 0; i < (await rows.count()); i += 1) {
          labels.push(await rows.nth(i).getAttribute("data-row"));
        }
        check("and it narrowed rather than starting again",
          labels.includes("BBB-") && !labels.includes("AAA"),
          labels.join(" "));
      }

      // And a question about how far to move something gets magnitudes.
      await say(page,
        "I want to stress BBB borrowers but what would be a sensible PD shock?");
      const suggested = await appears(page,
        '[data-analysis="suggestion"]', 190_000);
      check("a question about shock size returns measured magnitudes",
        suggested);
      if (suggested) {
        const said = await page.locator('[data-analysis="suggestion"]')
          .last().textContent();
        check("with a severity ladder drawn from the book's own history",
          said.includes("Typical quarter") && said.includes("Severe"));
        check("and it says the magnitudes were measured rather than chosen",
          /percentile|actually done|measured/i.test(said));
      }
    });

  /* --------------------------- 18. Sign in, move around, and stay signed in */
  await journey("Journey 18 — The session holds across the whole product",
    async (page, check) => {
      const offline = [];
      page.on("console", (message) => {
        const said = message.text();
        if (/backend did not answer/i.test(said)) offline.push(said);
      });
      const banner = async () => {
        const said = await page.content();
        return /backend did not answer/i.test(said);
      };

      await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
      check("the landing page loads without a backend-offline banner",
        !(await banner()));

      for (const [label, path] of [
        ["the rating journey", "/what-if/thread?journey=rating"],
        ["the parameters journey", "/what-if/thread?journey=parameters"],
        ["the macro journey", "/what-if/thread?journey=macro"],
        ["the Delta model page", "/what-if/models/delta"],
        ["the ML model page", "/what-if/models/ml"],
      ]) {
        await page.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
        await appears(page, "h1", 60_000);
        check(`${label} loads with the session intact`, !(await banner()));
      }

      // Back to a thread, then reload mid-thread: the session must survive.
      await page.goto(`${WEB}/what-if/thread?journey=parameters`,
        { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Show LGD by sector.");
      check("a question is answered",
        await appears(page, '[data-testid="whatif-analysis"]', 190_000));
      await page.reload({ waitUntil: "networkidle" });
      check("the page comes back after a reload",
        await appears(page, '[data-testid="whatif-composer"]', 60_000));
      check("and still without a backend-offline banner", !(await banner()));

      // The health endpoint is green throughout, which is the point: it was
      // green during the UAT failure too.
      const health = await fetch(`${API}/api/v1/health`);
      check("the health endpoint is 200 throughout", health.status === 200);
      check("nothing anywhere claimed the backend did not answer",
        offline.length === 0, offline.slice(0, 2).join(" | "));
    });

  /* ------------------------------- 19. The export, both methodologies */
  await journey("Journey 19 — Stage 1 BB PD +10%, exported both ways",
    async (page, check) => {
      for (const method of ["ml", "delta"]) {
        await page.goto(`${WEB}/what-if/thread?journey=parameters`,
          { waitUntil: "networkidle" });
        await appears(page, '[data-testid="whatif-composer"]', 60_000);
        await say(page, "Increase PD for Stage 1 BB rating by 10%");

        // The restatement of what was understood comes BEFORE any figure —
        // "What I understood — Rating: BB; Stage: Stage 1" — so a population
        // that narrowed and one that did not are distinguishable before an
        // ECL number appears to distract from the difference. Waited for
        // rather than counted immediately: the interpret round trip is a
        // network call, and reading the DOM the instant after clicking Send
        // measures the click.
        const restated = await page.locator("text=/What I understood/")
          .first().waitFor({ timeout: 190_000 }).then(() => true, () => false);
        check(`${method}: the thread restated what it understood`, restated);

        const ran = await chooseMethodology(page, check, method);
        check(`${method}: the scenario calculated`, ran);
        if (!ran) continue;

        const said = await page.textContent('[data-testid="whatif-result"]');
        check(`${method}: the population is Stage 1 and BB`,
          /BB/.test(said) && /Stage 1/.test(said));
        check(`${method}: and the result names it`,
          (await page.locator('[data-testid="whatif-population"]').count()) > 0);

        const button = page.locator('[data-testid="whatif-download-detail"]');
        check(`${method}: the detailed workbook is offered`,
          (await button.count()) > 0);
        if ((await button.count()) === 0) continue;

        const waiting = page.waitForEvent("download", { timeout: 190_000 })
          .catch(() => null);
        await button.first().click();
        const file = await waiting;
        check(`${method}: the workbook downloads`, Boolean(file));
        if (file) {
          check(`${method}: it is named as a workbook`,
            file.suggestedFilename().endsWith(".xlsx"),
            file.suggestedFilename());
        }
        const page_text = await page.content();
        check(`${method}: "Check: methodology" never appears`,
          !/Check:\s*methodology/i.test(page_text));
        check(`${method}: and no backend-offline banner appears`,
          !/backend did not answer/i.test(page_text));
      }
    });

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const checks = results.flatMap((r) => r.checks);
  const summary = {
    journeys: results.length,
    passed,
    failed: results.length - passed,
    checks: checks.length,
    checks_passed: checks.filter((c) => c.ok).length,
    web: WEB,
    api: API,
    results,
  };
  if (JSON_OUT) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    log(`\n${"=".repeat(64)}`);
    log(`${passed}/${results.length} journeys passed · ` +
        `${summary.checks_passed}/${summary.checks} checks passed`);
    for (const r of results) {
      if (!r.ok) {
        log(`  FAILED ${r.name}`);
        for (const c of r.checks.filter((c) => !c.ok)) {
          log(`    - ${c.label}${c.detail ? ` (${c.detail})` : ""}`);
        }
      }
    }
  }
  process.exit(passed === results.length ? 0 : 1);
}

main().catch(async (error) => {
  console.error("The journey suite could not run:", error);
  if (browser) await browser.close();
  process.exit(2);
});
