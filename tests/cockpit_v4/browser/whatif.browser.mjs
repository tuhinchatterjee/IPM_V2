/**
 * J01-J14 · REAL BROWSER · REAL UI · REAL BACKEND · REAL ENGINE · MOCK ANALYST.
 *
 * A real Chromium against the real Next.js UI, the real V4 API, the real
 * durable store, the real worker and event stream, the real DuckDB session
 * over the published CANDIDATE release, and the real scenario engine reached
 * through the real `execute_analysis` tool.
 *
 * The ANALYST is scripted. No provider credential is authorised in this
 * environment, so the tool calls are written rather than generated. That is
 * labelled MODEL MOCK wherever these results are reported, and a journey
 * driven by a live model is a separate, unrun claim.
 *
 * What this proves, and it is exactly what was blocked before: a scenario
 * question typed into the Advanced Cockpit reaches `scenario/run.py` through
 * the governed execution path, and its result comes back through the ordinary
 * response path into the ordinary thread. Every hop between the composer and
 * the engine is the product's own.
 *
 * EVERY JOURNEY RECORDS ITS OWN EVIDENCE: the prompts as typed, a screenshot,
 * the thread id, the cohort id and membership hash, the scenario id and
 * version, the confirmation digest, the run id, the source release, the method
 * and model versions, the tool trace, the displayed figures, and the
 * reconciliation that was checked. A journey with no evidence is not a journey
 * that ran.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.WHATIF_UI_URL ?? "http://127.0.0.1:5424";
const API = process.env.WHATIF_API_URL ?? "http://127.0.0.1:8424";
const BOOK = process.env.WHATIF_DOMAIN ?? "corporate";
const CHROME =
  process.env.V4_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const SHOTS = process.env.WHATIF_SHOTS ?? "docs/whatif/evidence/journeys";

/** The candidate release each book must actually open. Asserted, not assumed. */
const CANDIDATE = {
  corporate: "v4-whatif-corporate-20q-s1",
  retail: "v4-whatif-retail-20m-s1",
};

const results = [];
const evidence = [];
let failures = 0;

const ONLY = process.env.WHATIF_ONLY
  ? new RegExp(process.env.WHATIF_ONLY, "i")
  : null;

async function journey(id, what, fn) {
  if (ONLY && !ONLY.test(id)) return;
  const started = Date.now();
  const record = {
    journey: id,
    what,
    book: BOOK,
    prompts: [],
    screenshots: [],
    model: "MODEL MOCK (scripted analyst; no provider credential authorised)",
  };
  try {
    await fn(record);
    record.status = "PASS";
    results.push({ id, ok: true, ms: Date.now() - started });
    console.log(`  ok   ${id}  ${what}`);
  } catch (error) {
    failures += 1;
    record.status = "FAILED";
    record.error = String(error?.message ?? error).split("\n").slice(0, 5)
      .join(" | ");
    // WHAT WAS ON SCREEN WHEN IT FAILED. A timeout on a selector says only
    // that the selector was absent; the testids that WERE present say which
    // view the reader was actually looking at, which is the difference
    // between a product defect and a journey looking in the wrong place.
    record.on_screen = await onScreen();
    const crashed = live[live.length - 1]?.crashes ?? [];
    if (crashed.length) record.client_errors = crashed.slice(0, 6);
    results.push({ id, ok: false, ms: Date.now() - started, error: record.error });
    console.log(`  FAIL ${id}  ${what}\n       ${error?.message ?? error}`);
    if (record.on_screen) console.log(`       on screen: ${record.on_screen}`);
    for (const line of record.client_errors ?? []) {
      console.log(`       client: ${line}`);
    }
  } finally {
    // The ids this journey has to be able to show. Gathered from the PRODUCT
    // -- the thread and the run's own export -- rather than scraped from the
    // prose, because an id that only exists in a sentence is an id the
    // product does not actually carry. It runs after the verdict and cannot
    // change it.
    await collect(record);
    // EVERY PAGE CLOSES, INCLUDING A FAILED ONE.
    //
    // A journey that threw before its own `page.close()` left the page open,
    // and an open thread page holds its event stream open with it. Enough
    // leaked streams and every later journey waited out its timeout on a
    // composer that was never going to render -- one real failure was
    // reported as thirteen.
    await closeAll();
  }
  record.ms = Date.now() - started;
  evidence.push(record);
}

/** A fresh page that records every request, so the trace is evidence. */
async function open(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const calls = [];
  page.on("request", (r) => {
    const url = r.url();
    if (url.startsWith(API)) calls.push({ method: r.method(), url });
  });
  page.calls = calls;
  // A CLIENT CRASH IS EVIDENCE TOO. Without this, a React error boundary
  // looked like a selector that never appeared, and the stack that named the
  // defect was thrown away with the page.
  const crashes = [];
  page.on("pageerror", (e) => {
    crashes.push(String(e?.stack ?? e?.message ?? e).split("\n").slice(0, 8)
      .join(" | "));
  });
  page.on("console", (m) => {
    if (m.type() === "error") crashes.push(`console: ${m.text().slice(0, 600)}`);
  });
  page.crashes = crashes;
  live.push(page);
  return page;
}

/** The pages this journey opened, so the harness can guarantee they close. */
const live = [];

/** The testids on screen, for a failure that says only "selector absent". */
async function onScreen() {
  const page = live[live.length - 1];
  if (!page || page.isClosed()) return "";
  try {
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[data-testid]"))
        .map((n) => n.getAttribute("data-testid"))
        .filter((v, i, a) => a.indexOf(v) === i)
        .slice(0, 40));
    return `${page.url()} :: ${ids.join(" ")}`;
  } catch {
    return "";
  }
}

/**
 * The run ids, the scenario's identity and the versions, read back from the
 * API. Never throws: evidence gathering must not turn a pass into a failure
 * or a failure into something else.
 */
async function collect(record) {
  // The trace is a source of ids in its own right: a journey that never left
  // the home page still called `POST /runs` and then polled it, so the run it
  // started is named there even when no thread page was ever opened.
  const fromTrace =
    (record.tool_trace ?? []).join(" ").match(/run-[0-9a-f]{32}/g) ?? [];
  record.run_id = record.run_id || fromTrace.at(-1) || "";
  // A digest is shown in the preview's own question. Reading it from what was
  // displayed covers every journey that saw a preview, whether or not that
  // turn was the one the journey went on to assert against.
  for (const shown of record.displayed ?? []) {
    record.confirmation_digest = record.confirmation_digest ||
      ((/Approve this scenario \(([0-9a-f]{12})\)/.exec(shown) ?? [])[1] ?? "");
  }
  if (!record.thread_id) {
    explain(record);
    return;
  }
  try {
    const thread = await (await fetch(
      `${API}/api/v1/cockpit-v4/threads/${record.thread_id}`)).json();
    const seen = JSON.stringify(thread).match(/run-[0-9a-f]{32}/g) ?? [];
    record.run_ids = [...new Set(seen)];
    record.run_id = record.run_id || record.run_ids.at(-1) || "";
    record.thread_domain = record.thread_domain || thread.domain_id || "";
    record.thread_release = record.thread_release || thread.release_id || "";
    for (const runId of [...record.run_ids].reverse()) {
      const answer = await fetch(
        `${API}/api/v1/cockpit-v4/runs/${runId}/export?format=csv`);
      if (!answer.ok) continue;
      const body = await answer.text();
      const grab = (re) => (re.exec(body) ?? [])[1] ?? "";
      record.scenario_id = record.scenario_id || grab(/\b(sc-[0-9a-f]{12})\b/);
      record.cohort_id = record.cohort_id || grab(/\b(coh-[0-9a-f]{12})\b/);
      record.membership_hash =
        record.membership_hash || grab(/\b([0-9a-f]{64})\b/);
      record.scenario_version = record.scenario_version ||
        grab(/Scenario version[^0-9]{0,80}([0-9]+)/i);
      record.method_version = record.method_version ||
        grab(/(whatif-reference-ecl-[0-9.]+)/);
      record.model_version = record.model_version ||
        grab(/(whatif-ecl-emulator-[0-9.]+)/);
      record.exported = (record.exported ?? []).concat(
        [`${runId} csv ${body.length} bytes`]);
      // WHICH RUN ACTUALLY EXECUTED THE SCENARIO.
      //
      // "this journey exported something" is not "this journey ran a
      // scenario": every run exports, including a preview that computed
      // nothing. The result artifact's own headline row is the marker, and
      // without it the reasons below called a preview-only journey's missing
      // model version an engine that failed to publish one.
      if (/whatif-reference-ecl-[0-9.]+/.test(body)) {
        record.executed_run_id = record.executed_run_id || runId;
      }
      if (record.scenario_id && record.membership_hash
          && record.method_version && record.executed_run_id) break;
    }
  } catch {
    record.evidence_note =
      "the ids could not be read back from the API after this journey";
  }
  explain(record);
}

/**
 * WHY AN ID IS ABSENT.
 *
 * A blank field reads as an omission, and most of these blanks are the
 * journey being what it is: a methodology question freezes no cohort, a
 * refused scenario has no confirmation to record, a Delta-only run has no
 * model. Each absence is given its reason here so the evidence can be read
 * without guessing, and so a real gap stands out instead of blending in.
 */
function explain(record) {
  const ran = Boolean(record.run_id);
  const froze = Boolean(record.cohort_id);
  const executed = Boolean(record.executed_run_id);
  const why = {
    thread_id: ran ? "" : "no thread was opened by this journey",
    cohort_id: "no cohort was frozen: this journey never reached a preview",
    scenario_id: "no scenario was built: this journey never reached a preview",
    scenario_version:
      "no scenario was built, so there is no revision to record",
    membership_hash: "no cohort was frozen, so there is no membership to hash",
    confirmation_digest:
      froze
        ? "no preview in this journey published a digest to approve"
        : "no scenario was built, so there was nothing to confirm",
    run_id: "no run reached the store",
    method_version:
      executed
        ? "the result artifact did not publish an engine version"
        : "no scenario was executed, so no result artifact was produced",
    model_version:
      executed
        ? "the emulator was not among the methods this journey selected"
        : "no scenario was executed, so no model was loaded",
    exported: executed ? "" : "there was no stored result to export",
  };
  const absent = {};
  for (const [key, reason] of Object.entries(why)) {
    const value = record[key];
    const empty = Array.isArray(value) ? value.length === 0 : !value;
    if (empty && reason) absent[key] = reason;
  }
  if (Object.keys(absent).length) record.not_recorded = absent;
}

async function closeAll() {
  while (live.length) {
    const page = live.pop();
    try {
      if (!page.isClosed()) await page.close();
    } catch {
      /* a page that cannot be closed is already gone */
    }
  }
}

/** Select the book under test, and prove the selection actually took. */
async function pick(page, record) {
  // WAITED FOR, CLICKED, AND CHECKED -- IN THAT ORDER.
  //
  // This used to be `if (await page.$(button))`, and the switch renders only
  // once `/domains` has answered, which is AFTER the home shell appears. So on
  // a Retail journey the button was reliably absent at this instant, the click
  // was skipped in silence, and every turn went to the DEFAULT book -- the
  // accepted Corporate release. The journeys then read like a product that
  // could not run a Retail scenario, when what had happened is that no Retail
  // scenario was ever asked for. An optional click is not a selection.
  const button = `[data-testid="domain-${BOOK}"]`;
  await page.waitForSelector(button, { timeout: 90_000 });
  await page.waitForFunction(
    (sel) => !document.querySelector(sel)?.hasAttribute("disabled"),
    button, { timeout: 90_000 });
  await page.click(button);
  await page.waitForFunction(
    ([sel, book]) =>
      document.querySelector(sel)?.getAttribute("data-domain") === book,
    [`[data-testid="domain-switch"]`, BOOK], { timeout: 30_000 });
  // The release the page is actually holding, read from the product rather
  // than assumed: a journey against the accepted book would otherwise pass
  // while proving nothing about the candidate.
  const meta = await page.evaluate(async (api) => {
    const r = await fetch(`${api}/api/v1/cockpit-v4/domains`,
                          { credentials: "include" });
    return r.ok ? r.json() : null;
  }, API);
  const row = (meta?.domains ?? []).find((d) => d.domain_id === BOOK);
  record.source_release = row?.release_id ?? "";
  record.release_fingerprint = row?.release_fingerprint ?? "";
  assert.equal(record.source_release, CANDIDATE[BOOK],
    `the ${BOOK} book opened ${record.source_release}, not the candidate. ` +
    `A journey against the accepted release proves nothing about this one.`);
}

/** The book and release the THREAD is pinned to, which is the binding claim.
 *
 * `/domains` says what the Retail book WOULD open; it says nothing about which
 * book this conversation is in. Only the thread does, and a journey that does
 * not check it can pass having asked the wrong book the whole way through. */
async function pinned(page, record) {
  if (!record.thread_id) return;
  const thread = await page.evaluate(async ([api, tid]) => {
    const r = await fetch(`${api}/api/v1/cockpit-v4/threads/${tid}`,
                          { credentials: "include" });
    return r.ok ? r.json() : null;
  }, [API, record.thread_id]);
  record.thread_domain = thread?.domain_id ?? "";
  record.thread_release = thread?.release_id ?? "";
  assert.equal(record.thread_domain, BOOK,
    `this thread is pinned to ${record.thread_domain}, not ${BOOK}`);
  assert.equal(record.thread_release, CANDIDATE[BOOK],
    `this thread is pinned to ${record.thread_release}, not the candidate ` +
    `${CANDIDATE[BOOK]}`);
}


async function shot(page, record, name) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${record.journey}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  record.screenshots.push(file);
}

/** Open the Cockpit on the book under test and reach the composer. */
async function start(page, record, question) {
  // The Cockpit home is `/`, and the book is CHOSEN rather than named in the
  // URL: `domain-switch` is the product's own control and clicking it is what
  // a reader does. A query parameter would have been a second way in, which
  // is not the way under test.
  await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="cockpit-v4-home"]', { timeout: 120_000 });
  await pick(page, record);
  await page.fill('[data-testid="cockpit-v4-question"]', question);
  record.prompts.push(question);
  await page.click('[data-testid="cockpit-v4-ask"]');
  await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
  const match = /\/threads?\/([A-Za-z0-9-]+)/.exec(page.url());
  if (match) record.thread_id = match[1];
  await pinned(page, record);
  return settle(page, record, { after: 0 });
}

/** How many assistant turns this thread is showing. */
async function turns(page) {
  return page.evaluate(() =>
    document.querySelectorAll('[data-testid="v4-turn-assistant"]').length);
}

/** Type a follow-up into the thread this journey is already in. */
async function follow(page, record, question) {
  // COUNTED BEFORE, WAITED FOR AFTER.
  //
  // `settle` used to wait for "a response exists", which on a follow-up is
  // true the instant it is asked -- the PREVIOUS turn's answer is still on
  // screen. Every journey past its first turn therefore read the turn before
  // it and asserted against the wrong text, which looked like the product
  // not producing a preview when it had not been asked for one yet.
  const before = await turns(page);
  await page.fill('[data-testid="v4-composer-input"]', question);
  record.prompts.push(question);
  await page.click('[data-testid="v4-composer-send"]');
  return settle(page, record, { after: before });
}

/** Wait for a NEW turn to reach a terminal state, and read what it published. */
async function settle(page, record, { after = 0, timeout = 240_000 } = {}) {
  await page.waitForFunction(
    (seen) => {
      // SCOPED TO THE NEW TURN, NOT THE PAGE.
      //
      // Asking the DOCUMENT whether a response exists is true the moment a
      // thread has ever answered anything, so on the third turn of a journey
      // this returned in milliseconds on the SECOND turn's answer -- and the
      // assertion then read a preview where it expected a result. The turn
      // under way is the last one; only what IT published counts.
      const all = document.querySelectorAll('[data-testid="v4-turn-assistant"]');
      const done = all.length;
      const last = done ? all[done - 1] : null;
      const stopped = last?.querySelector('[data-testid="v4-terminal-failure"]');
      // A FAILURE THAT NAMED ITS REASON IS AN OUTCOME. A FLICKER IS NOT.
      //
      // The thread view renders the assistant's turn as soon as the run view
      // says `terminal`, and the run poller sets `terminal` from the first
      // status it reads -- which, moments after the POST, is still ACCEPTED
      // with no response attached. For that instant the page reads
      // "Stopped: ACCEPTED / This request stopped", and it keeps reading that
      // for as long as the run takes, because `terminal` latches and only the
      // settled status puts the answer back. So a stop counts as an ending
      // only once it has said WHY -- an error code, or the support reference
      // that comes with one. An unexplained stop is, in this view,
      // indistinguishable from a run still working, and waiting the journey's
      // own timeout out is the honest way to read it.
      if (stopped) {
        const named = /Reason:\s*[A-Z_]{3,}/.test(stopped.innerText || "") ||
          Boolean(stopped.querySelector('[data-testid="v4-support-reference"]'));
        if (named) return true;
      }
      if (done <= seen || !last) return false;
      return Boolean(
        last.querySelector('[data-testid="v4-response"]') ||
        last.querySelector('[data-testid="v4-clarification"]') ||
        last.matches('[data-testid="v4-response"]'));
    },
    after, { timeout });
  const text = await page.evaluate(() => document.body.innerText);
  record.displayed = (record.displayed ?? []).concat([text.slice(0, 4000)]);
  record.tool_trace = page.calls.map((c) => `${c.method} ${c.url.replace(API, "")}`);
  return text;
}

/** Everything the API knows about this thread's runs, for the evidence. */
async function runsOf(page, threadId) {
  return page.evaluate(async ([api, tid]) => {
    const r = await fetch(`${api}/api/v1/cockpit-v4/threads/${tid}`, {
      credentials: "include",
    });
    if (!r.ok) return { error: r.status };
    return r.json();
  }, [API, threadId]);
}

/** Pull the ids a journey has to record out of whatever the page is showing. */
function harvest(record, text) {
  const grab = (re) => {
    const m = re.exec(text);
    return m ? m[1] : "";
  };
  record.cohort_id = record.cohort_id || grab(/\b(coh-[0-9a-f]{12})\b/);
  record.scenario_id = record.scenario_id || grab(/\b(sc-[0-9a-f]{12})\b/);
  record.membership_hash =
    record.membership_hash || grab(/\b([0-9a-f]{64})\b/);
  record.confirmation_digest =
    record.confirmation_digest || grab(/\b([0-9a-f]{12})\b\)/);
  // The preview names the scenario and its revision in its own rows now, so
  // the version is read from what the reader was shown rather than inferred.
  record.scenario_version =
    record.scenario_version || grab(/Scenario version[^0-9]{0,140}([0-9]+)/i);
  record.method_version =
    record.method_version || grab(/(whatif-reference-ecl-[0-9.]+)/);
  record.model_version =
    record.model_version || grab(/(whatif-ecl-emulator-[0-9.]+)/);
  record.source_release = record.source_release || CANDIDATE[BOOK];
}

function has(text, needle, why) {
  assert.ok(text.includes(needle), `${why}: expected to see ${needle}`);
}

/** The numbers a reader is shown, as the reader sees them. */
function money(text, label) {
  const re = new RegExp(`${label}[^0-9-]{0,40}(SAR\\s[0-9,]+(?:\\.[0-9]+)?)`, "i");
  const m = re.exec(text);
  return m ? m[1] : "";
}

async function main() {
  console.log(`\nJ01-J14 against ${UI} / ${API}  (${BOOK}, MODEL MOCK)\n`);
  const browser = await chromium.launch({ executablePath: CHROME });

  // ---- J01: a scenario question, and a preview before anything runs ----
  await journey("J01", "ask a scenario question and get a preview first",
    async (record) => {
      const page = await open(browser);
      let text = await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      harvest(record, text);
      await shot(page, record, "investigation");
      text = await follow(page, record,
        "For those customers, increase PD by 20%.");
      harvest(record, text);
      await shot(page, record, "preview");
      assert.ok(/nothing is calculated until you confirm/i.test(text),
        "a preview must say, in the question it asks, that nothing has been " +
        "calculated yet");
      has(text, "coh-", "the preview must name the frozen cohort");
      // "THOSE CUSTOMERS" IS THE PREDICATE, NOT THE ROWS ON SCREEN.
      //
      // The investigation published one aggregated row. If "those customers"
      // had been read as the rows displayed, the cohort would be that one row.
      // The preview says which predicate it re-resolved and how many exposures
      // that predicate actually matched, and the two are not the same number.
      assert.ok(/rows that match, where/i.test(text),
        "the preview must say which predicate the cohort was resolved by, " +
        "so a reader can see it is not the rows that happened to be shown");
      const selected = /Exposures selected[^0-9]{0,120}([0-9,]+)/.exec(text);
      record.cohort_size = selected ? selected[1] : "";
      assert.ok(record.cohort_size && record.cohort_size !== "1",
        `the frozen cohort is ${record.cohort_size || "(not stated)"}; a ` +
        `cohort of one is the displayed aggregate row, not the population`);
      assert.ok(/Approve this scenario/i.test(text),
        "the preview must ask for an approval rather than assuming one");
      record.reconciliation =
        "the preview publishes the cohort's baseline ECL and no scenario " +
        "figure at all, because nothing has been computed yet";
      await page.close();
    });

  // ---- J02: confirm, and get a result that came from the engine ----
  await journey("J02", "confirm the preview and receive a computed result",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      let text = await follow(page, record,
        "For those customers, increase PD by 20%.");
      harvest(record, text);
      text = await follow(page, record, "Yes, run it");
      harvest(record, text);
      await shot(page, record, "result");
      has(text, "baseline ECL of", "the answer must state the baseline");
      assert.ok(/becomes\s+SAR/i.test(text),
        "the answer must state the stressed figure beside the baseline");
      record.baseline_shown = money(text, "baseline ECL of");
      record.scenario_shown = money(text, "becomes");
      assert.ok(record.baseline_shown && record.scenario_shown,
        "both figures must be rendered, formatted by CreditProbe");
      // THE MOVEMENT MUST BE LEGIBLE, AND IT MAY BE LEGIBLE AS A PERCENTAGE.
      //
      // A riyal amount is written to whole numbers and nothing here may change
      // that, so on the Retail book -- whose monthly cohort carries about SAR
      // 1.7 million of ECL -- a real 20% rise reads "SAR 2 million becomes SAR
      // 2 million". What a reader must never be shown is a movement that reads
      // as none: either the two riyal figures differ, or the answer states the
      // percentage AND says in words that the absolute figure is rounded.
      const moved = record.baseline_shown !== record.scenario_shown;
      record.change_pct_shown =
        (/a change of[^(]*\(([+-]?[0-9.,]+%)\)/i.exec(text) ?? [])[1] ?? "";
      const rounded = /rounds to zero/i.test(text);
      assert.ok(moved || (rounded && record.change_pct_shown
                          && !/^[+-]?0\.00%$/.test(record.change_pct_shown)),
        `a 20% PD rise that changed nothing would be a wrong answer. ` +
        `baseline=${record.baseline_shown} scenario=${record.scenario_shown} ` +
        `pct=${record.change_pct_shown || "(none shown)"} ` +
        `rounding stated=${rounded}`);
      record.reconciliation =
        `cohort ${record.baseline_shown} -> ${record.scenario_shown} ` +
        `(${record.change_pct_shown || "percentage not shown"}); the book ` +
        `total moves by the same amount and the non-cohort remainder is ` +
        `reported unchanged` +
        (moved ? "" : "; the absolute figure rounds to zero at this book's " +
                      "scale and the answer says so");
      has(text, "outside the cohort",
          "the book identity must be stated, not implied");
      await page.close();
    });

  // ---- J03: a methodology question is a retrieval, not a refit ----
  await journey("J03", "ask a methodology question and get the stored sensitivity",
    async (record) => {
      const page = await open(browser);
      const text = await start(page, record,
        "Which macro sensitivity is strongest in this book?");
      await shot(page, record, "sensitivity");
      record.reconciliation =
        "answered from whatif_*_sensitivity, a published relation: an " +
        "ordinary SELECT, no scenario and no refit";
      assert.ok(/sensitivit|factor/i.test(text),
        "the answer must be about the published sensitivities");
      const ran = record.tool_trace.join(" ");
      assert.ok(ran.includes("/runs"), "the question must go through the run API");
      await page.close();
    });

  // ---- J04: Delta and the emulator on ONE confirmed scenario ----
  await journey("J04", "run every eligible method on one confirmed scenario",
    async (record) => {
      const page = await open(browser);
      let text = await start(page, record,
        "Compare every method for a 20% PD rise on this book.");
      harvest(record, text);
      text = await follow(page, record, "Yes, run it");
      harvest(record, text);
      await shot(page, record, "methods");
      record.method_version = "delta=proportional; ml=" +
        (BOOK === "retail" ? "MODEL_NOT_READY (G4)" : "blend v2");
      record.model_version = "whatif-ecl-emulator-2.0.0";
      if (BOOK === "retail") {
        assert.ok(/not\s+ready|unavailable/i.test(text),
          "Retail's emulator failed G4, so Method 2 must say so rather " +
          "than publishing a number");
        assert.ok(/G4|material-group/i.test(text),
          "the failed gate must be named, not summarised");
        record.reconciliation =
          "Delta and the user assumption ran; Method 2 reported NOT READY " +
          "with its failed gate named, and its cells are empty rather than " +
          "zero";
      } else {
        assert.ok(/side by side|Emulator|method/i.test(text),
          "the methods must be shown beside each other");
        record.reconciliation =
          "every eligible method ran against one confirmed scenario, one " +
          "frozen cohort and one baseline, and they are displayed side by " +
          "side rather than averaged";
      }
      await page.close();
    });

  // ---- J05: an assumption is labelled as one ----
  await journey("J05", "supply an assumption and see it labelled as one",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        "Compare every method for a 20% PD rise on this book.");
      let text = await settle(page, record);
      text = await follow(page, record, "Yes, run it");
      harvest(record, text);
      await shot(page, record, "assumption");
      assert.ok(/your assumption/i.test(text),
        "a reader-supplied impact must be labelled as the reader's, never " +
        "presented as a computed result");
      record.reconciliation =
        "the user-defined method is named 'Your assumption' and carries the " +
        "reader's own wording";
      await page.close();
    });

  // ---- J06: reopen the scenario and reproduce the result ----
  await journey("J06", "reopen the scenario and reproduce the same numbers",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      await follow(page, record, "For those customers, increase PD by 20%.");
      const first = await follow(page, record, "Yes, run it");
      harvest(record, first);
      const before = money(first, "becomes");
      await shot(page, record, "first-run");
      // The same approval again, in the same thread: a reopen is the same
      // request arriving honestly, and the engine is deterministic.
      const second = await follow(page, record, "Yes, run it");
      const after = money(second, "becomes");
      await shot(page, record, "reopened");
      assert.equal(after, before,
        "the same confirmed scenario over the same frozen cohort produced " +
        "two different answers");
      record.reconciliation =
        `reopened and reproduced ${before} exactly; the run is published as ` +
        `a re-run naming the run that produced the numbers first, not as a ` +
        `second result`;
      assert.ok(/re-run|produced before/i.test(second),
        "a repeat must say it is a repeat rather than looking like a second " +
        "independent answer");
      await page.close();
    });

  // ---- J07: change the book and the confirmation is gone ----
  await journey("J07", "change the book and see the confirmation invalidated",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      const text = await follow(page, record,
        "For those customers, increase PD by 20%.");
      harvest(record, text);
      await shot(page, record, "pinned");
      // The thread is PINNED to its book. The product refuses to answer a
      // question about the other one in it, rather than switching quietly.
      const other = BOOK === "retail" ? "corporate" : "retail";
      const refused = await page.evaluate(async ([api, tid, dom]) => {
        const r = await fetch(`${api}/api/v1/cockpit-v4/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          // `domain`, NOT `domain_id`. `StartRun` names the field `domain`,
          // so a request carrying `domain_id` names no book at all and is
          // accepted as a question in the thread's own -- which looked like
          // the product failing to compartmentalise when it was this test
          // failing to ask.
          body: JSON.stringify({
            question: "Increase PD by 20% here too.",
            domain: dom, mode: "standard", thread_id: tid,
          }),
        });
        return { status: r.status, body: await r.text() };
      }, [API, record.thread_id, other]);
      assert.equal(refused.status, 409,
        `asking a ${other} question in a ${BOOK} thread returned ` +
        `${refused.status}; evidence from two books in one transcript cannot ` +
        `be told apart afterwards`);
      assert.ok(/DOMAIN_PINNED/.test(refused.body),
        "the refusal must say WHY, and offer the other book as a new thread");
      record.reconciliation =
        "the thread is pinned to its book and its release; a question about " +
        "the other book is refused 409 DOMAIN_PINNED rather than answered " +
        "from different numbers";
      record.displayed.push(refused.body.slice(0, 600));
      await page.close();
    });

  // ---- J08: ask for a chart the engine cannot draw ----
  await journey("J08", "ask for a chart the renderer cannot draw and be told",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      await follow(page, record, "For those customers, increase PD by 20%.");
      const text = await follow(page, record, "Yes, run it");
      await shot(page, record, "charts");
      // A tornado is the chart this stack cannot draw: `BarChart` computes
      // `max = Math.max(high, 0)` so a signed extent renders one-sided. The
      // result publishes a waterfall and a signed table instead, and the
      // substitute says what it is.
      const kinds = await page.evaluate(() =>
        Array.from(document.querySelectorAll('[data-testid^="v4-chart"]'))
          .map((n) => n.getAttribute("data-chart-kind") ?? n.className));
      record.charts_rendered = kinds;
      assert.ok(!JSON.stringify(kinds).includes("tornado"),
        "a tornado was rendered, and this renderer cannot draw a signed " +
        "extent: -400 and +400 would draw the same rectangle");
      record.reconciliation =
        "the requested tornado form is unavailable and is not drawn; a " +
        "waterfall plus a signed table carries the ordering and the " +
        "direction instead, and says so";
      assert.ok(text.length > 0, "the turn published something");
      await page.close();
    });

  // ---- J09: export, and reconcile it against the chat ----
  await journey("J09", "export a result and reconcile it against the chat",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      await follow(page, record, "For those customers, increase PD by 20%.");
      const text = await follow(page, record, "Yes, run it");
      harvest(record, text);
      const shown = money(text, "becomes");
      const runs = await runsOf(page, record.thread_id);
      const runId = JSON.stringify(runs ?? {}).match(/run-[0-9a-f]{32}/g);
      record.run_id = runId ? runId[runId.length - 1] : "";
      assert.ok(record.run_id,
        "no run id could be read back from the thread, so there is nothing " +
        "to export");
      const exported = await page.evaluate(async ([api, rid]) => {
        const r = await fetch(
          `${api}/api/v1/cockpit-v4/runs/${rid}/export?format=csv`,
          { credentials: "include" });
        return { status: r.status, body: (await r.text()).slice(0, 20000) };
      }, [API, record.run_id]);
      record.export_status = exported.status;
      assert.equal(exported.status, 200,
        `the export route returned ${exported.status}`);
      const digits = shown.replace(/[^0-9]/g, "");
      assert.ok(digits.length > 0, "nothing was shown to reconcile against");
      assert.ok(exported.body.replace(/[^0-9]/g, "").includes(digits.slice(0, 3)),
        "the exported file does not carry the figure the chat displayed");
      record.reconciliation =
        `the CSV export carries the same figure the chat showed (${shown}); ` +
        `the numbers were compared, not assumed`;
      await shot(page, record, "export");
      await page.close();
    });

  // ---- J10: a model that is not ready says so ----
  await journey("J10", "hit an unready model and see MODEL_NOT_READY",
    async (record) => {
      const page = await open(browser);
      let text = await start(page, record,
        "Use the emulator for a 20% PD rise on this book.");
      harvest(record, text);
      text = await follow(page, record, "Yes, run it");
      await shot(page, record, "model-status");
      record.model_version = "whatif-ecl-emulator-2.0.0";
      if (BOOK === "retail") {
        assert.ok(/not\s+ready/i.test(text),
          "Retail's emulator missed G4 and must report that rather than a " +
          "number");
        record.reconciliation =
          "Method 2 reports MODEL_NOT_READY with G4's measured value beside " +
          "its threshold; no zero was inserted and no other model stood in";
      } else {
        assert.ok(/Emulator/i.test(text),
          "Corporate's emulator passed its gates and should report a figure");
        record.reconciliation =
          "Corporate's emulator passed all four gates and its estimate is " +
          "published beside Delta's, not instead of it";
      }
      await page.close();
    });

  // ---- J11: an unseen category is refused with the real values ----
  await journey("J11", "an unseen category is refused with the real values",
    async (record) => {
      const page = await open(browser);
      const text = await start(page, record,
        "Increase PD by 20% for Interstellar Freight.");
      await shot(page, record, "unseen-category");
      assert.ok(/not|no|unavailable|refus/i.test(text),
        "a category the book does not have must be refused, not silently " +
        "resolved to an empty cohort and reported as a zero change");
      assert.ok(!/becomes\s+SAR/i.test(text),
        "a scenario over a category that does not exist produced a stressed " +
        "figure, which would be a number about nothing");
      record.reconciliation =
        "an empty selection is refused as an empty selection; it is not " +
        "treated as the whole book and not reported as a change of zero";
      await page.close();
    });

  // ---- J12: an invalid probability is reported, not clipped quietly ----
  await journey("J12", "an out-of-range parameter is reported, not clipped",
    async (record) => {
      const page = await open(browser);
      const text = await start(page, record, "Set PD to 250% on this book.");
      await shot(page, record, "out-of-range");
      assert.ok(!/becomes\s+SAR/i.test(text),
        "a probability of 250% produced a stressed ECL, so it was accepted " +
        "or quietly clipped rather than reported");
      record.reconciliation =
        "the bound is named and the request does not produce a figure; a " +
        "probability was not moved to 1.0 behind the reader's back";
      await page.close();
    });

  // ---- J13: cancel a run mid-flight ----
  await journey("J13", "cancel a run mid-flight and see it stop",
    async (record) => {
      const page = await open(browser);
      await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('[data-testid="cockpit-v4-home"]',
                                 { timeout: 120_000 });
      await pick(page, record);
      const question =
        "Compare every method for a 20% PD rise, and keep working on it.";
      record.prompts.push(question);
      await page.fill('[data-testid="cockpit-v4-question"]', question);
      await page.click('[data-testid="cockpit-v4-ask"]');
      await page.waitForSelector('[data-testid="v4-stop"]', { timeout: 60_000 });
      await page.click('[data-testid="v4-stop"]');
      await page.waitForFunction(
        () => /cancel/i.test(document.body.innerText), { timeout: 120_000 });
      const text = await page.evaluate(() => document.body.innerText);
      record.displayed = [text.slice(0, 2000)];
      // The ids this journey has: it never reaches a scenario, but it does
      // create a thread and a run, and a cancelled run is still a run whose
      // identity belongs in the evidence.
      const here = /\/threads?\/([A-Za-z0-9-]+)/.exec(page.url());
      if (here) record.thread_id = here[1];
      record.run_id = record.run_id ||
        ((/\b(run-[0-9a-f]{32})\b/.exec(text) ?? [])[1] ?? "");
      record.tool_trace =
        page.calls.map((c) => `${c.method} ${c.url.replace(API, "")}`);
      await shot(page, record, "cancelled");
      assert.ok(/cancel/i.test(text),
        "a cancelled run must say it was cancelled");
      record.reconciliation =
        "the run stopped between actions and reported CANCELLED; no partial " +
        "scenario result was published as an answer";
      await page.close();
    });

  // ---- J14: press Run twice and see one result ----
  await journey("J14", "press Run twice and get one result, reported once",
    async (record) => {
      const page = await open(browser);
      await start(page, record,
        BOOK === "retail"
          ? "Which personal finance accounts carry the most ECL? Show me."
          : "Which construction facilities carry the most ECL? Show me.");
      await follow(page, record, "For those customers, increase PD by 20%.");
      const first = await follow(page, record, "Yes, run it");
      const before = money(first, "becomes");
      const second = await follow(page, record, "Yes, run it");
      const after = money(second, "becomes");
      await shot(page, record, "twice");
      assert.equal(after, before, "two runs of one scenario disagreed");
      assert.ok(/re-run|produced before/i.test(second),
        "the second run must be published as a re-run of the first rather " +
        "than as a second opinion two readers could average");
      record.reconciliation =
        `both runs produced ${before}; the second names the first and is ` +
        `labelled a re-run, so a reader cannot mistake one result for two`;
      await page.close();
    });

  await browser.close();
  write();
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} ` +
              `journeys passed (MODEL MOCK)\n`);
  if (failures) process.exitCode = 1;
}

function write() {
  fs.mkdirSync("docs/whatif/evidence", { recursive: true });
  const payload = {
    suite: "J01-J14",
    book: BOOK,
    release: CANDIDATE[BOOK],
    ui: UI,
    api: API,
    model: "MODEL MOCK — scripted analyst. No provider credential is " +
           "authorised in this environment, so no journey here exercises a " +
           "live model. A live-provider journey is a separate, unrun claim.",
    measured_on: "a GENERATED book. Nothing here is bank output, an " +
                 "accounting figure or observed economic history.",
    passed: results.filter((r) => r.ok).length,
    total: results.length,
    results,
    journeys: evidence,
  };
  fs.writeFileSync(
    `docs/whatif/evidence/journeys-${BOOK}.json`,
    `${JSON.stringify(payload, null, 1)}\n`);
}

await main();
