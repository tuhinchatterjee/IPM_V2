/**
 * LIVE-PROVIDER UAT · L1-L8 · REAL BROWSER · REAL UI · REAL BACKEND ·
 * REAL ENGINE · **REAL MODEL**.
 *
 * This is the one suite in this deliverable that is NOT MODEL MOCK. Every
 * other journey scripts the analyst's tool calls; here the provider generates
 * them, from the reader's own words, and the question under test is whether
 * arbitrary natural language is reliably converted into the correct governed
 * deterministic scenario contract.
 *
 * IT IS NOT A TEST OF THE PROSE. A beautiful paragraph over the wrong cohort
 * is a failure; a plain sentence over the right frozen cohort, the right
 * mapping and the right arithmetic is a pass. So every assertion here is
 * about the CONTRACT -- which book, which cohort, which field, which
 * operation, whether the preview came before the calculation, whether the
 * confirmation bound what ran -- and never about wording, except where the
 * wording is the product's own governed label.
 *
 * REFUSES TO RUN WITHOUT A CREDENTIAL. `WHATIF_LIVE=1` and a server whose
 * `credential_status()` is PRESENT are both required. A live suite that
 * quietly fell back to a stub would produce evidence that says "live" over
 * journeys that were not, which is the one outcome worse than not running it.
 *
 * Measured on GENERATED books. Nothing here is bank output, an accounting
 * figure, or a bank-validated model.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.WHATIF_UI_URL ?? "http://127.0.0.1:5424";
const API = process.env.WHATIF_API_URL ?? "http://127.0.0.1:8424";
const CHROME =
  process.env.V4_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const SHOTS = process.env.WHATIF_SHOTS ?? "docs/whatif/evidence/live";

/** The candidate release each book must actually open. */
const CANDIDATE = {
  corporate: "v4-whatif-corporate-20q-s1",
  retail: "v4-whatif-retail-20m-s1",
};

/** A live turn is a model turn: it takes as long as the model takes. */
const SETTLE_MS = 420_000;

const results = [];
const evidence = [];
let failures = 0;

const ONLY = process.env.WHATIF_ONLY
  ? new RegExp(process.env.WHATIF_ONLY, "i")
  : null;

const live = [];

async function refuseWithoutACredential() {
  if (process.env.WHATIF_LIVE !== "1") {
    throw new Error(
      "WHATIF_LIVE=1 is required. This suite is the only one that claims a " +
      "live model, so it will not run by accident.");
  }
  const health = await (await fetch(`${API}/api/v1/health`)).json();
  const status = JSON.stringify(health);
  if (!/"credential"\s*:\s*"PRESENT"/.test(status)
      && !/PRESENT/.test(status)) {
    throw new Error(
      "the server reports no provider credential. A live UAT cannot be run " +
      "here, and running it against a stub would produce evidence that " +
      "says live over journeys that were not. Set " +
      "COCKPIT_ANTHROPIC_API_KEY in the shell that starts the candidate.");
  }
}

async function journey(id, book, what, fn) {
  if (ONLY && !ONLY.test(id)) return;
  const started = Date.now();
  const record = {
    journey: id, book, what, prompts: [], screenshots: [],
    model: "REAL PROVIDER — the analyst's tool calls were generated, not " +
           "scripted. Measured on a generated book.",
  };
  try {
    await fn(record);
    record.status = "PASS";
    results.push({ id, ok: true, ms: Date.now() - started });
    console.log(`  ok   ${id}  ${what}`);
  } catch (error) {
    failures += 1;
    record.status = "FAILED";
    record.error = String(error?.message ?? error).split("\n").slice(0, 6)
      .join(" | ");
    results.push({ id, ok: false, ms: Date.now() - started,
                   error: record.error });
    console.log(`  FAIL ${id}  ${what}\n       ${error?.message ?? error}`);
  } finally {
    await collect(record);
    while (live.length) {
      const page = live.pop();
      try { if (!page.isClosed()) await page.close(); } catch { /* gone */ }
    }
  }
  record.ms = Date.now() - started;
  evidence.push(record);
}

async function open(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const calls = [];
  page.on("request", (r) => {
    const url = r.url();
    if (url.startsWith(API)) calls.push({ method: r.method(), url });
  });
  page.calls = calls;
  live.push(page);
  return page;
}

async function shot(page, record, name) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${record.journey}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  record.screenshots.push(file);
}

async function pick(page, record, book) {
  const button = `[data-testid="domain-${book}"]`;
  await page.waitForSelector(button, { timeout: 90_000 });
  await page.waitForFunction(
    (sel) => !document.querySelector(sel)?.hasAttribute("disabled"),
    button, { timeout: 90_000 });
  await page.click(button);
  await page.waitForFunction(
    ([sel, b]) =>
      document.querySelector(sel)?.getAttribute("data-domain") === b,
    [`[data-testid="domain-switch"]`, book], { timeout: 30_000 });
}

/** Open the Cockpit on one book and ask the reader's first question. */
async function start(page, record, book, question) {
  await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="cockpit-v4-home"]',
                             { timeout: 120_000 });
  await pick(page, record, book);
  await page.fill('[data-testid="cockpit-v4-question"]', question);
  record.prompts.push(question);
  await page.click('[data-testid="cockpit-v4-ask"]');
  await page.waitForSelector('[data-testid="cockpit-v4-thread"]',
                             { timeout: 120_000 });
  const match = /\/threads?\/([A-Za-z0-9-]+)/.exec(page.url());
  if (match) record.thread_id = match[1];
  await pinned(page, record, book);
  return settle(page, record, { after: 0 });
}

/** The book and release the THREAD is pinned to -- the binding claim. */
async function pinned(page, record, book) {
  if (!record.thread_id) return;
  const thread = await page.evaluate(async ([api, tid]) => {
    const r = await fetch(`${api}/api/v1/cockpit-v4/threads/${tid}`,
                          { credentials: "include" });
    return r.ok ? r.json() : null;
  }, [API, record.thread_id]);
  record.thread_domain = thread?.domain_id ?? "";
  record.thread_release = thread?.release_id ?? "";
  assert.equal(record.thread_domain, book,
    `this thread is pinned to ${record.thread_domain}, not ${book}`);
  assert.equal(record.thread_release, CANDIDATE[book],
    `this thread opened ${record.thread_release}, not the candidate`);
}

async function turns(page) {
  return page.evaluate(() =>
    document.querySelectorAll('[data-testid="v4-turn-assistant"]').length);
}

async function follow(page, record, question) {
  const before = await turns(page);
  await page.fill('[data-testid="v4-composer-input"]', question);
  record.prompts.push(question);
  await page.click('[data-testid="v4-composer-send"]');
  return settle(page, record, { after: before });
}

/** Wait for a NEW turn to reach a terminal state, and read what it published. */
async function settle(page, record, { after = 0, timeout = SETTLE_MS } = {}) {
  await page.waitForFunction(
    (seen) => {
      const all = document.querySelectorAll('[data-testid="v4-turn-assistant"]');
      const done = all.length;
      const last = done ? all[done - 1] : null;
      const stopped = last?.querySelector('[data-testid="v4-terminal-failure"]');
      if (stopped) {
        const named = /Reason:\s*[A-Z_]{3,}/.test(stopped.innerText || "")
          || Boolean(stopped.querySelector(
               '[data-testid="v4-support-reference"]'));
        if (named) return true;
      }
      if (done <= seen || !last) return false;
      return Boolean(last.querySelector('[data-testid="v4-response"]')
                     || last.querySelector('[data-testid="v4-clarification"]'));
    },
    after, { timeout });
  const text = await page.evaluate(() => document.body.innerText);
  record.displayed = (record.displayed ?? []).concat([text.slice(0, 6000)]);
  record.tool_trace = page.calls.map(
    (c) => `${c.method} ${c.url.replace(API, "")}`);
  return text;
}

/**
 * The CONTRACT the model produced, read off the run rather than the prose.
 *
 * This is the whole point of the suite: the acceptance question is whether
 * free-form language became the right typed operation, and that is visible in
 * the submitted step's own parameters, not in the paragraph above them.
 */
async function contract(record) {
  if (!record.thread_id) return [];
  try {
    const thread = await (await fetch(
      `${API}/api/v1/cockpit-v4/threads/${record.thread_id}`)).json();
    const ids = [...new Set(
      JSON.stringify(thread).match(/run-[0-9a-f]{32}/g) ?? [])];
    record.run_ids = ids;
    record.run_id = record.run_id || ids.at(-1) || "";
    const steps = [];
    for (const runId of ids) {
      const trace = await fetch(
        `${API}/api/v1/cockpit-v4/runs/${runId}/trace`);
      if (!trace.ok) continue;
      const body = await trace.text();
      for (const found of body.matchAll(
             /"language"\s*:\s*"whatif_scenario"[\s\S]{0,4000}?"parameters"\s*:\s*(\{[\s\S]{0,4000}?\})\s*,\s*"purpose"/g)) {
        try { steps.push(JSON.parse(found[1])); } catch { /* not this one */ }
      }
    }
    record.scenario_contracts = steps;
    return steps;
  } catch {
    record.evidence_note = "the submitted contract could not be read back";
    return [];
  }
}

async function collect(record) {
  await contract(record);
  for (const shown of record.displayed ?? []) {
    record.cohort_id = record.cohort_id
      || (/\b(coh-[0-9a-f]{12})\b/.exec(shown) ?? [])[1] || "";
    record.scenario_id = record.scenario_id
      || (/\b(sc-[0-9a-f]{12})\b/.exec(shown) ?? [])[1] || "";
    record.membership_hash = record.membership_hash
      || (/\b([0-9a-f]{64})\b/.exec(shown) ?? [])[1] || "";
    record.confirmation_digest = record.confirmation_digest
      || (/Approve this scenario \(([0-9a-f]{12})\)/.exec(shown) ?? [])[1]
      || "";
  }
  if (!record.run_id) {
    record.run_id = ((record.tool_trace ?? []).join(" ")
      .match(/run-[0-9a-f]{32}/g) ?? []).at(-1) ?? "";
  }
}

/** Every shock the model produced, flattened, so a field can be looked for. */
function shocks(record) {
  return (record.scenario_contracts ?? [])
    .flatMap((c) => c.shocks ?? []);
}

function askedFor(record, field) {
  return shocks(record).some((s) => String(s.field ?? "") === field);
}

function previewedBeforeRunning(record) {
  const kinds = (record.scenario_contracts ?? [])
    .map((c) => String(c.operation ?? ""));
  const preview = kinds.indexOf("preview_scenario");
  const execute = kinds.indexOf("execute_scenario");
  return preview !== -1 && (execute === -1 || preview < execute);
}

async function main() {
  console.log(`\nL1-L8 LIVE PROVIDER against ${UI} / ${API}\n`);
  await refuseWithoutACredential();
  const browser = await chromium.launch({ executablePath: CHROME });

  // ---- L1: a combined two-parameter scenario on a retained cohort ----
  await journey("L1", "corporate",
    "investigate, then raise PD and LGD together on those customers",
    async (record) => {
      const page = await open(browser);
      await start(page, record, "corporate",
        "Investigate deterioration in the portfolio and identify the " +
        "customers driving the issue.");
      await shot(page, record, "investigation");
      let text = await follow(page, record,
        "For those customers increase PD by 20% and LGD by 10%.");
      await shot(page, record, "preview");

      // BOTH parameters, in ONE scenario, over ONE frozen cohort.
      assert.ok(askedFor(record, "pd_pit_12m"),
        `no PD shock reached the engine. Shocks: ` +
        `${JSON.stringify(shocks(record))}`);
      assert.ok(askedFor(record, "lgd_pct"),
        `the LGD half of "PD by 20% and LGD by 10%" was dropped. Shocks: ` +
        `${JSON.stringify(shocks(record))}`);
      assert.ok(previewedBeforeRunning(record),
        "a calculation was run before a preview was shown");
      assert.ok(record.cohort_id, "no frozen cohort was named");
      assert.ok(/Approve this scenario/i.test(text),
        "the preview must ask for approval rather than assume one");

      text = await follow(page, record, "Yes, run it");
      await shot(page, record, "result");
      assert.ok(/becomes\s+SAR/i.test(text),
        "the confirmed scenario produced no stressed figure");
      record.reconciliation =
        `two parameters in one scenario over cohort ${record.cohort_id}; ` +
        `the preview preceded the calculation and the approval bound it`;
      await page.close();
    });

  // ---- L2: a macro sensitivity, then its translation ----
  await journey("L2", "corporate",
    "a stored sensitivity, then a macro move translated into PD, LGD and ECL",
    async (record) => {
      const page = await open(browser);
      let text = await start(page, record, "corporate",
        "What is our sensitivity to unemployment?");
      await shot(page, record, "sensitivity");
      // A methodology question is a RETRIEVAL. It must not refit and must not
      // invent a slope.
      assert.ok(/unemployment/i.test(text),
        "the stored sensitivity for unemployment was not retrieved");
      assert.ok(!(record.scenario_contracts ?? []).length,
        "a methodology question must not execute a scenario");

      text = await follow(page, record,
        "Reduce unemployment by 10% and show me what that does to PD, LGD " +
        "and ECL.");
      await shot(page, record, "translated");
      // RELATIVE, not percentage-point: "by 10%" on a rate is a relative
      // move, and conflating the two is the arithmetic error this book's
      // whole unit vocabulary exists to prevent.
      const moves = shocks(record).map(
        (s) => `${s.field}:${s.operation}:${s.value}`);
      record.interpreted = moves;
      assert.ok(moves.length, `nothing reached the engine. ${text.slice(0, 300)}`);
      assert.ok(moves.some((m) => /relative_pct/.test(m)),
        `"reduce by 10%" must be a RELATIVE move, not a percentage-point ` +
        `one. What was produced: ${JSON.stringify(moves)}`);
      assert.ok(previewedBeforeRunning(record),
        "a macro translation was executed without a preview");
      record.reconciliation =
        `the macro move was translated into ${moves.join(", ")} and ` +
        `previewed before anything was calculated`;
      await page.close();
    });

  // ---- L3: two overlapping rules, resolved rather than double-counted ----
  await journey("L3", "corporate",
    "a sector rule plus a rating overlay, with the overlap resolved",
    async (record) => {
      const page = await open(browser);
      let text = await start(page, record, "corporate",
        "Show me the sectors in this portfolio.");
      await shot(page, record, "sectors");
      text = await follow(page, record,
        "For Construction increase PD by 25%, but for rating grades 7 and " +
        "worse increase it by another 10%.");
      await shot(page, record, "overlap");

      // The engine refuses two rules on one field over overlapping rows
      // (RULE_CONFLICT) and ASKS which applies. Either outcome is correct;
      // silently composing them is not.
      const questioned =
        /which applies|replace the first|compose on|only to the rows/i
          .test(text) || /RULE_CONFLICT/i.test(text);
      const scoped =
        shocks(record).some((s) => Object.keys(s.where ?? {}).length > 0);
      const resolved = questioned || scoped;
      record.interpreted = { questioned, scoped, shocks: shocks(record) };
      assert.ok(resolved,
        `the overlap was neither resolved nor questioned. Shocks: ` +
        `${JSON.stringify(shocks(record))}`);
      assert.ok(!/approximately|roughly doubled/i.test(text),
        "an overlap must not be described as an approximation");
      record.reconciliation =
        "the overlapping rule was either scoped explicitly or refused with " +
        "the question of which applies; it was never silently composed";
      await page.close();
    });

  // ---- L4: three methods on one confirmed Corporate scenario ----
  await journey("L4", "corporate",
    "Delta, the emulator and a reader's assumption, side by side",
    async (record) => {
      const page = await open(browser);
      await start(page, record, "corporate",
        "Which construction facilities carry the most ECL?");
      await follow(page, record,
        "Increase PD by 20% for those customers and compare Delta, the ML " +
        "emulator and my own assumption that ECL rises 15%.");
      const text = await follow(page, record, "Yes, run it");
      await shot(page, record, "three-methods");
      for (const label of ["Delta", "Emulator", "assumption"]) {
        assert.ok(new RegExp(label, "i").test(text),
          `${label} is missing from the comparison`);
      }
      assert.ok(!/averag/i.test(text.replace(/never averaged|rather than averaged/gi, "")),
        "the methods must be shown side by side, never averaged");
      record.reconciliation =
        "three methods against one confirmed scenario, one frozen cohort " +
        "and one baseline, shown side by side";
      await page.close();
    });

  // ---- L5: a behavioural score, not an application score ----
  await journey("L5", "retail",
    "worsen the behavioural score, and not the application score",
    async (record) => {
      const page = await open(browser);
      await start(page, record, "retail",
        "Investigate which retail customers are deteriorating and show me " +
        "the worst cohort.");
      await shot(page, record, "investigation");
      const text = await follow(page, record,
        "For those customers worsen behavioural score by 30 points.");
      await shot(page, record, "behavioural");

      const fields = shocks(record).map((s) => String(s.field ?? ""));
      record.interpreted = fields;
      assert.ok(fields.length,
        `nothing reached the engine. ${text.slice(0, 300)}`);
      assert.ok(fields.some((f) => /behaviour|behavior/i.test(f)),
        `"behavioural score" must map to the BEHAVIOURAL field. What was ` +
        `produced: ${JSON.stringify(fields)}`);
      assert.ok(!fields.some((f) => /application/i.test(f)),
        `the application score is a different mapping and must not be used ` +
        `for a behavioural instruction. Produced: ${JSON.stringify(fields)}`);
      // "by 30 points" is an absolute move on a score, not a relative one.
      const points = shocks(record).filter(
        (s) => /behaviour|behavior/i.test(String(s.field ?? "")));
      assert.ok(points.every((s) => !/relative/i.test(String(s.operation))),
        `30 POINTS on a score is an absolute move. Produced: ` +
        `${JSON.stringify(points)}`);
      record.reconciliation =
        `"behavioural score by 30 points" became ${JSON.stringify(points)} ` +
        `-- the behavioural mapping, as an absolute move`;
      await page.close();
    });

  // ---- L6: every method, with Retail's ML honestly unavailable ----
  await journey("L6", "retail",
    "compare every method and see ML reported NOT READY with its reason",
    async (record) => {
      const page = await open(browser);
      await start(page, record, "retail",
        "Which personal finance accounts carry the most ECL?");
      await follow(page, record,
        "Increase PD by 20% for this cohort and compare every available " +
        "method.");
      const text = await follow(page, record, "Yes, run it");
      await shot(page, record, "methods");

      assert.ok(/Delta/i.test(text), "Delta must be available on Retail");
      assert.ok(/NOT[_ ]READY|UNAVAILABLE|not ready/i.test(text),
        "Retail's emulator failed a predeclared gate and the answer must " +
        "say so rather than quietly leaving it out");
      assert.ok(/G4/.test(text),
        `the failed gate must be named. What was shown: ${text.slice(0, 600)}`);
      assert.ok(/0\.3436|34\.36/.test(text),
        "the measured value must travel with the gate");
      assert.ok(!/Emulator[^.]{0,40}SAR 0/i.test(text),
        "an unavailable method must not be reported as a change of zero");
      record.reconciliation =
        "Delta complete, ML reported NOT READY with G4 and its measured " +
        "value, no zero inserted and no other model substituted";
      await page.close();
    });

  // ---- L7: a scenario as the very first message ----
  await journey("L7", "retail",
    "a first-message scenario, with the cohort shown before confirmation",
    async (record) => {
      const page = await open(browser);
      const text = await start(page, record, "retail",
        "For unsecured personal loans with weak behavioural scores, " +
        "increase PD by 15% and LGD by 5%.");
      await shot(page, record, "first-turn");

      assert.ok(record.cohort_id,
        `the cohort must be frozen and NAMED before approval. ` +
        `${text.slice(0, 400)}`);
      assert.ok(/Approve this scenario/i.test(text),
        "a first-message scenario still needs approval before it runs");
      assert.ok(/nothing is calculated|Nothing has been calculated/i.test(text),
        "the preview must say that nothing has been computed yet");
      assert.ok(askedFor(record, "pd_pit_12m") && askedFor(record, "lgd_pct"),
        `both parameters must reach the engine. Shocks: ` +
        `${JSON.stringify(shocks(record))}`);
      assert.ok(previewedBeforeRunning(record),
        "a first-message scenario was executed without a preview");
      record.reconciliation =
        `no investigation preceded it, and the cohort ${record.cohort_id} ` +
        `with both rules was shown before anything was approved`;
      await page.close();
    });

  // ---- L8: an ambiguous instruction must ask, not guess ----
  await journey("L8", "retail",
    "an ambiguous request draws a clarification, not an invented assumption",
    async (record) => {
      const page = await open(browser);
      await start(page, record, "retail",
        "Which personal finance accounts carry the most ECL?");
      const text = await follow(page, record, "Stress them pretty badly.");
      await shot(page, record, "clarification");

      const asked = /ONE QUESTION FIRST|which|how much|did you mean|clarif/i
        .test(text);
      assert.ok(asked,
        `"pretty badly" names no parameter and no magnitude. The product ` +
        `must ask. What it said: ${text.slice(0, 500)}`);
      // And it must NOT have invented one.
      const invented = shocks(record).filter(
        (s) => String(s.value ?? "") !== "");
      assert.equal(invented.length, 0,
        `a magnitude was invented from "pretty badly": ` +
        `${JSON.stringify(invented)}`);
      assert.ok(!/becomes\s+SAR/i.test(text),
        "nothing may be calculated from an instruction nobody has pinned " +
        "down");
      record.reconciliation =
        "the ambiguous instruction produced a question and no scenario; no " +
        "parameter, magnitude or cohort was guessed at";
      await page.close();
    });

  await browser.close();
  write();
}

function write() {
  fs.mkdirSync("docs/whatif/evidence", { recursive: true });
  fs.writeFileSync("docs/whatif/evidence/live-uat.json",
    `${JSON.stringify({
      suite: "L1-L8 LIVE PROVIDER",
      ui: UI, api: API,
      model: "REAL PROVIDER. The analyst's tool calls were GENERATED from " +
             "the reader's own words, not scripted. This is the only suite " +
             "in this deliverable that claims a live model.",
      acceptance: "Not whether the prose reads well. Whether arbitrary " +
                  "natural language was reliably converted into the correct " +
                  "governed deterministic scenario contract.",
      measured_on: "GENERATED books. Nothing here is bank output, an " +
                   "accounting figure, or a bank-validated model.",
      passed: results.filter((r) => r.ok).length,
      total: results.length,
      results, journeys: evidence,
    }, null, 1)}\n`);
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} ` +
              `live journeys passed (REAL PROVIDER)\n`);
}

await main();
process.exit(failures ? 1 : 0);
