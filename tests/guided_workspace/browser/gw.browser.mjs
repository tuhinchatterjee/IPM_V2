/**
 * Guided Risk Workspace journeys · REAL BROWSER · REAL UI · REAL API · REAL
 * STORES · REAL ENGINE · MOCK ANALYST.
 *
 * Real Chromium against the real Next.js UI and the real V4 API with every
 * Guided Workspace flag on (`scripts/guided_workspace/gw_stub_server.py`).
 * Only the analyst's tool calls are scripted: this is labelled MODEL MOCK
 * everywhere it is reported, and the live-provider Mac UAT is a separate gate.
 *
 * Each journey records its own evidence (prompts, screenshots, ids, what was
 * displayed, API calls) into GW_EVIDENCE. A journey that asserted nothing is
 * not a journey: each one ends in assertions against the product's own state.
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.GW_UI_URL ?? "http://127.0.0.1:5444";
const API = process.env.GW_API_URL ?? "http://127.0.0.1:8444";
const CHROME = process.env.V4_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const SHOTS = process.env.GW_SHOTS ?? "docs/guided_workspace/evidence/journeys";
const EVIDENCE = process.env.GW_EVIDENCE ?? "docs/guided_workspace/evidence/journeys.json";
const ONLY = process.env.GW_ONLY ? new RegExp(process.env.GW_ONLY, "i") : null;
const WS = `${API}/api/v1/cockpit-v4/workspace`;

const evidence = [];
let failures = 0;
const live = [];
let browser;

async function journey(id, what, fn) {
  if (ONLY && !ONLY.test(id)) return;
  const started = Date.now();
  const record = { journey: id, what, prompts: [], screenshots: [], model: "MODEL MOCK (scripted analyst)" };
  try {
    await fn(record);
    record.status = "PASS";
    console.log(`  ok   ${id}  ${what}`);
  } catch (error) {
    failures += 1;
    record.status = "FAILED";
    record.error = String(error?.message ?? error).split("\n").slice(0, 6).join(" | ");
    record.on_screen = await onScreen();
    const crashed = live[live.length - 1]?.crashes ?? [];
    if (crashed.length) record.client_errors = crashed.slice(0, 6);
    console.log(`  FAIL ${id}  ${what}\n       ${record.error}`);
    if (record.on_screen) console.log(`       on screen: ${record.on_screen}`);
    for (const line of record.client_errors ?? []) console.log(`       client: ${line}`);
  } finally {
    collectInstrumentation(record);
    await closeAll();
  }
  record.ms = Date.now() - started;
  evidence.push(record);
}

async function open() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const calls = [];
  page.on("request", (r) => {
    if (r.url().startsWith(API)) calls.push(`${r.method()} ${r.url().replace(API, "")}`);
  });
  const crashes = [];
  page.on("pageerror", (e) => crashes.push(String(e?.stack ?? e).split("\n").slice(0, 6).join(" | ")));
  page.on("console", (m) => {
    if (m.type() === "error") crashes.push(`console: ${m.text().slice(0, 400)}`);
  });
  // Validation instrumentation: which controls were actually clicked (by the
  // nearest data-testid), and every console error/warning, page error,
  // failed request and 4xx/5xx API response, per journey.
  const clicked = new Set();
  const consoleLog = [];
  const http = [];
  await page.exposeFunction("__gwClicked", (id) => clicked.add(String(id)));
  await page.addInitScript(() => {
    window.addEventListener(
      "click",
      (e) => {
        const el = e.target instanceof Element ? e.target.closest("[data-testid]") : null;
        if (el) window.__gwClicked?.(el.getAttribute("data-testid"));
      },
      true,
    );
  });
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") consoleLog.push(`${m.type()}: ${m.text().slice(0, 300)}`);
  });
  page.on("pageerror", (e) => consoleLog.push(`pageerror: ${String(e?.message ?? e).slice(0, 300)}`));
  page.on("requestfailed", (r) => {
    if (r.url().startsWith(API)) http.push(`FAILED ${r.method()} ${r.url().replace(API, "")} ${r.failure()?.errorText ?? ""}`);
  });
  page.on("response", (r) => {
    if (r.url().startsWith(API) && r.status() >= 400) http.push(`${r.status()} ${r.request().method()} ${r.url().replace(API, "")}`);
  });
  const urls = new Set();
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame() && f.url().startsWith(UI)) urls.add(new URL(f.url()).pathname);
  });
  page.calls = calls;
  page.crashes = crashes;
  page.urls = urls;
  page.clicked = clicked;
  page.consoleLog = consoleLog;
  page.http = http;
  live.push(page);
  return page;
}

function collectInstrumentation(record) {
  const clicked = new Set(record.controls_clicked ?? []);
  const consoleLog = [...(record.console ?? [])];
  const http = [...(record.http_errors ?? [])];
  const urls = new Set(record.urls ?? []);
  for (const page of live) {
    for (const u of page.urls ?? []) urls.add(u);
    for (const id of page.clicked ?? []) clicked.add(id);
    consoleLog.push(...(page.consoleLog ?? []));
    http.push(...(page.http ?? []));
  }
  record.controls_clicked = [...clicked].sort();
  record.urls = [...urls].sort();
  record.console = [...new Set(consoleLog)].slice(0, 80);
  record.http_errors = [...new Set(http)].slice(0, 80);
}

async function onScreen() {
  const page = live[live.length - 1];
  if (!page || page.isClosed()) return "";
  try {
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[data-testid]"))
        .map((n) => n.getAttribute("data-testid"))
        .filter((v, i, a) => a.indexOf(v) === i)
        .slice(0, 50));
    return `${page.url()} :: ${ids.join(" ")}`;
  } catch {
    return "";
  }
}

async function closeAll() {
  while (live.length) {
    const page = live.pop();
    try {
      if (!page.isClosed()) await page.close();
    } catch {
      /* already gone */
    }
  }
}

async function shot(page, record, name) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${record.journey}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  record.screenshots.push(path.relative(process.cwd(), file));
}

async function api(pathname, init) {
  const r = await fetch(`${WS}${pathname}`, init);
  const text = await r.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  return { status: r.status, body };
}

async function v4(pathname) {
  const r = await fetch(`${API}/api/v1/cockpit-v4${pathname}`);
  return r.ok ? r.json() : null;
}

async function pickBook(page, book) {
  const button = `[data-testid="domain-${book}"]`;
  await page.waitForSelector(button, { timeout: 90_000 });
  await page.waitForFunction((sel) => !document.querySelector(sel)?.hasAttribute("disabled"), button, {
    timeout: 90_000,
  });
  await page.click(button);
  await page.waitForFunction(
    ([sel, b]) => document.querySelector(sel)?.getAttribute("data-domain") === b,
    ['[data-testid="domain-switch"]', book],
    { timeout: 30_000 },
  );
}

/** Ask from the Cockpit home and wait for the first answer to settle. */
async function askFromHome(page, record, question, book = "corporate") {
  await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="cockpit-v4-home"]', { timeout: 120_000 });
  await pickBook(page, book);
  await page.fill('[data-testid="cockpit-v4-question"]', question);
  record.prompts.push(question);
  await page.click('[data-testid="cockpit-v4-ask"]');
  await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
  const match = /\/threads?\/([A-Za-z0-9-]+)/.exec(page.url());
  if (match) record.thread_id = match[1];
  await settle(page, 0);
}

async function settle(page, after = 0, timeout = 240_000) {
  await page.waitForFunction(
    (seen) => {
      const all = document.querySelectorAll('[data-testid="v4-turn-assistant"]');
      const last = all.length ? all[all.length - 1] : null;
      if (all.length <= seen || !last) return false;
      return Boolean(
        last.querySelector('[data-testid="v4-response"]') ||
          last.querySelector('[data-testid="v4-clarification"]') ||
          last.querySelector('[data-testid="v4-terminal-failure"]'),
      );
    },
    after,
    { timeout },
  );
}

async function latestRun(threadId) {
  const thread = await v4(`/threads/${threadId}`);
  const ids = JSON.stringify(thread ?? {}).match(/run-[0-9a-f]{32}/g) ?? [];
  return ids.at(-1) ?? "";
}

// =========================================================================
// P1 — Full LLM Exchange Trace
// =========================================================================

async function p1Journeys() {
  await journey(
    "GW-P1-01",
    "Cockpit question → governance record → Trace › LLM Exchange shows every call, stage and panel",
    async (record) => {
      const page = await open();
      await askFromHome(page, record, "Show me construction exposure by sector");
      record.run_id = await latestRun(record.thread_id);
      assert.ok(record.run_id, "the question produced a run");
      await page.goto(`${UI}/cockpit/trace/${record.run_id}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('[data-testid="trace-llm-exchange-link"]', { timeout: 90_000 });
      await page.click('[data-testid="trace-llm-exchange-link"]');
      await page.waitForSelector('[data-testid="llm-exchange"]', { timeout: 90_000 });
      const cards = await page.$$('[data-testid^="llm-call-"][data-testid$="1"], [data-testid="llm-call-2"]');
      assert.ok(cards.length >= 2, "at least two model calls are shown");
      await page.click('[data-testid="llm-call-1"] >> text=Canonical request');
      await page.waitForSelector('[data-testid="llm-call-1-canonical"]');
      const canonical = await page.textContent('[data-testid="llm-call-1-canonical"]');
      for (const key of ["system", "messages", "tools", "tool_choice"]) {
        assert.ok(canonical.includes(key), `the canonical request shows ${key}`);
      }
      await shot(page, record, "calls");
      await page.click("text=Data visibility");
      await page.waitForSelector('[data-testid="llm-visibility"]');
      const vis = await page.textContent('[data-testid="llm-visibility"]');
      assert.ok(vis.includes("AVAILABLE TO CREDITPROBE") && vis.includes("ACTUALLY TRANSMITTED TO THE MODEL"));
      await shot(page, record, "visibility");
      await page.click("text=Context growth");
      await page.waitForSelector('[data-testid="llm-growth"][data-rendered="true"]', { timeout: 60_000 });
      await page.click('[data-testid="llm-growth-view-data"]');
      await page.waitForSelector('[data-testid="llm-growth-table"]');
      await shot(page, record, "growth");
      await page.click("text=Calls");
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 60_000 }),
        page.click('[data-testid="llm-exchange-export"]'),
      ]);
      record.export = download.suggestedFilename();
      assert.match(record.export, /^llm_exchange_run-[0-9a-f]{32}\.zip$/);
      const view = await api(`/llm-exchange/runs/${record.run_id}`);
      record.calls_recorded = view.body?.recorder?.calls_recorded;
      assert.ok(view.body.calls.every((c) => !JSON.stringify(c).includes("sk-ant")), "no credential in any record");
    },
  );

  await journey("GW-P1-02", "Reopening a trace makes zero model calls", async (record) => {
    const page = await open();
    await askFromHome(page, record, "Show me construction exposure by sector");
    record.run_id = await latestRun(record.thread_id);
    const before = (await api(`/model-lab/exchanges?limit=1000`)).body.exchanges.length;
    for (let i = 0; i < 2; i += 1) {
      await page.goto(`${UI}/trace/llm-exchange/${record.run_id}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('[data-testid="llm-exchange"]', { timeout: 90_000 });
    }
    const after = (await api(`/model-lab/exchanges?limit=1000`)).body.exchanges.length;
    record.exchanges_before = before;
    record.exchanges_after = after;
    assert.equal(after, before, "opening the trace twice recorded no new model call");
  });

  await journey("GW-P1-03", "AI Model Lab reads the same records and compares two calls", async (record) => {
    const page = await open();
    await page.goto(`${UI}/ai-model-lab`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="ai-model-lab"]');
    await page.waitForSelector("table input[type=radio]", { timeout: 60_000 });
    const radiosA = await page.$$('input[name="a"]');
    const radiosB = await page.$$('input[name="b"]');
    assert.ok(radiosA.length >= 2, "recorded calls are listed");
    await radiosA[0].check();
    await radiosB[1].check();
    await page.click("text=Compare A and B");
    await page.waitForSelector('[data-testid="ai-model-lab-compare"]');
    const text = await page.textContent('[data-testid="ai-model-lab-compare"]');
    assert.ok(text.includes("System identical"));
    const replay = await page.$$eval("button", (bs) =>
      bs.filter((b) => b.textContent.includes("Replay A on")).map((b) => ({ t: b.textContent, d: b.disabled })),
    );
    record.replay_buttons = replay;
    assert.ok(replay.some((b) => b.t.includes("not configured") && b.d), "an unconfigured target cannot be pressed");
    await shot(page, record, "compare");
  });
}


// =========================================================================
// P3 — Guided Cockpit: Requires Attention, investigation path, drill
// =========================================================================

async function openHome(page, book) {
  await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="cockpit-v4-home"]', { timeout: 120_000 });
  await pickBook(page, book);
  await page.waitForSelector('[data-testid="requires-attention"]', { timeout: 120_000 });
}

async function turns(page) {
  return page.$$eval('[data-testid="v4-turn-assistant"]', (n) => n.length);
}

async function p3Journeys() {
  for (const book of ["corporate", "retail"]) {
    const tag = book === "corporate" ? "CORP" : "RET";
    await journey(
      `GW-P3-01-${tag}`,
      `${book}: landing shows Requires Attention AND the free Ask box; cards carry measured evidence`,
      async (record) => {
        const page = await open();
        await openHome(page, book);
        const count = Number(await page.getAttribute('[data-testid="requires-attention"]', "data-count"));
        record.issue_count = count;
        assert.ok(count >= 1, "at least one issue is shown");
        assert.ok(await page.isVisible('[data-testid="cockpit-v4-question"]'), "the Ask box is on the landing");
        const first = page.locator('[data-testid="issue-card"]').first();
        for (const id of ["issue-title", "issue-current", "issue-affected", "issue-interpretation", "issue-investigate", "issue-save-cohort"]) {
          assert.ok(await first.locator(`[data-testid="${id}"]`).count(), `the card carries ${id}`);
        }
        const feed = (await api(`/issues?domain=${book}`)).body;
        record.release_id = feed.release_id;
        record.titles = feed.issues.slice(0, 5).map((i) => i.title);
        assert.equal(feed.issues.length, count, "the page shows the server's feed, no more and no fewer");
        assert.ok(feed.issues.every((i) => i.detection_rule?.id && i.materiality && i.evidence?.series?.length), "every issue is measured");
        await shot(page, record, "landing");
      },
    );
  }

  await journey("GW-P3-02", "Issue card → Investigate → an ordinary thread with the path and NBQ chips; a chip runs a normal turn in the SAME thread", async (record) => {
    const page = await open();
    await openHome(page, "corporate");
    const issueId = await page.locator('[data-testid="issue-card"]').first().getAttribute("data-issue-id");
    record.issue_id = issueId;
    await page.locator('[data-testid="issue-investigate"]').first().click();
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
    const match = /\/thread\/([A-Za-z0-9-]+)/.exec(page.url());
    record.thread_id = match?.[1];
    assert.ok(record.thread_id, "a thread opened");
    await page.waitForSelector('[data-testid="investigation-bar"]', { timeout: 60_000 });
    const steps = await page.$$eval('[data-testid="investigation-path"] li', (ls) => ls.map((l) => [l.getAttribute("data-step"), l.getAttribute("data-status")]));
    record.path = steps;
    assert.deepEqual(steps.map((s) => s[0]), ["Issue", "Evidence", "Driver", "Cohort", "Finding", "Scenario/Decision"]);
    const chips = await page.$$eval('[data-testid="nbq-chip"]', (bs) => bs.map((b) => ({ text: b.textContent, type: b.getAttribute("data-suggestion-type") })));
    record.chips = chips;
    assert.ok(chips.length >= 2 && chips.length <= 5, "2-5 next-best questions");
    assert.ok(!chips.some((c) => c.type === "run_whatif"), "no What-If chip before a finding exists");
    await shot(page, record, "path");
    const before = await turns(page);
    const chip = page.locator('[data-testid="nbq-chip"][data-suggestion-type="driver"], [data-testid="nbq-chip"][data-suggestion-type="contribution"], [data-testid="nbq-chip"]').first();
    const asked = (await chip.textContent()).trim();
    record.prompts.push(`chip: ${asked}`);
    await chip.click();
    await settle(page, before);
    const after = /\/thread\/([A-Za-z0-9-]+)/.exec(page.url())?.[1];
    assert.equal(after, record.thread_id, "the chip ran in the same thread");
    const inv = (await api(`/investigations/by-thread/${record.thread_id}`)).body;
    record.investigation_id = inv.investigation_id;
    record.clicks_recorded = inv.clicks ?? [];
    assert.ok((inv.clicks ?? []).some((s) => s.suggestion_id && s.rationale && s.exact_request === asked), "the click was recorded with its rationale and exact request");
    const answered = await page.$$eval('[data-testid="v4-turn-assistant"]', (n) => n.at(-1).textContent);
    assert.ok(!/Terminal|failed/i.test(answered.slice(0, 80)), "the chip's turn answered");
    await shot(page, record, "chip-answered");

    // Free-form still works in the same thread.
    const beforeFree = await turns(page);
    const free = "Which sectors carry the most reported ECL?";
    record.prompts.push(free);
    await page.fill('[data-testid="v4-composer-input"]', free);
    await page.click('[data-testid="v4-composer-send"]');
    await settle(page, beforeFree);
    assert.ok((await turns(page)) > beforeFree, "a free-form question answered in the same thread");
    await shot(page, record, "free-form");
  });

  await journey("GW-P3-03", "Issue detail: charts are Plotly; clicking a driver bar narrows the governed grid server-side", async (record) => {
    const feed = (await api(`/issues?domain=corporate`)).body;
    const issue = feed.issues.find((i) => (i.evidence?.breakdown ?? []).length >= 2) ?? feed.issues[0];
    record.issue_id = issue.issue_id;
    const page = await open();
    await page.goto(`${UI}/issues/${issue.issue_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="issue-detail"]', { timeout: 120_000 });
    await page.waitForSelector('[data-testid="issue-drivers"][data-rendered="true"]', { timeout: 60_000 });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") || 0) > 0, null, { timeout: 60_000 });
    const totalBefore = Number(await page.getAttribute('[data-testid="issue-grid"]', "data-total"));
    await page.locator('[data-testid="issue-drivers"]').scrollIntoViewIfNeeded();
    const box = await page.locator('[data-testid="issue-drivers"] g.point path').first().boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(250);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForFunction(
      (n) => {
        const t = Number(document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") || 0);
        return t > 0 && t !== n;
      },
      totalBefore,
      { timeout: 30_000 },
    ).catch(() => undefined);
    const chips = await page.$$eval('[data-testid="issue-grid"] [data-testid="grid-filter-chip"]', (c) => c.map((x) => x.textContent));
    record.filter_chips = chips;
    const totalAfter = Number(await page.getAttribute('[data-testid="issue-grid"]', "data-total"));
    record.rows_before = totalBefore;
    record.rows_after = totalAfter;
    const labels = issue.evidence.breakdown.map((b) => String(b.label));
    record.clicked = chips.find((c) => labels.some((l) => c.includes(l))) ?? "";
    assert.ok(record.clicked, "the clicked bar became a server-side filter on its own label");
    assert.ok(totalAfter > 0 && totalAfter <= totalBefore, "the grid narrowed");
    await page.click('[data-testid="issue-drivers-view-data"]');
    await page.waitForSelector('[data-testid="issue-drivers-table"]');
    await shot(page, record, "drilled");
  });

  await journey("GW-P3-04", "Early Warning (retail) → save cohort → investigate opens a Cockpit thread over that exact population", async (record) => {
    const page = await open();
    await page.goto(`${UI}/early-warning`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="early-warning-v4"]', { timeout: 120_000 });
    await page.waitForSelector('[data-testid="ew-band-critical"]', { timeout: 120_000 });
    await page.click('[data-testid="ew-save-cohort"]');
    await page.waitForSelector('[data-testid="ew-note"]', { timeout: 60_000 });
    record.note = await page.textContent('[data-testid="ew-note"]');
    const cohortId = /\b(coh[-_][0-9A-Za-z_-]+)/.exec(record.note)?.[1];
    record.cohort_id = cohortId;
    assert.ok(cohortId, "a governed cohort id was returned");
    const cohort = (await api(`/objects/${cohortId}`)).body;
    record.cohort_entities = cohort.body.counts.entities;
    assert.ok(cohort.body.membership_hash, "the cohort is frozen with a membership hash");
    await shot(page, record, "ew");
    await page.click('[data-testid="ew-investigate"]');
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
    record.thread_id = /\/thread\/([A-Za-z0-9-]+)/.exec(page.url())?.[1];
    assert.ok(record.thread_id, "the investigation opened as a thread");
    const thread = await v4(`/threads/${record.thread_id}`);
    record.thread_domain = thread?.domain_id ?? thread?.thread?.domain_id;
    assert.equal(record.thread_domain, "retail", "the thread reads the retail book");
    await shot(page, record, "thread");
  });
}

// =========================================================================
// P4 — Scenario Library
// =========================================================================

async function libraryCards(page) {
  await page.waitForSelector('[data-testid="scenario-count"]', { timeout: 120_000 });
  return Number(await page.getAttribute('[data-testid="scenario-count"]', "data-total"));
}

async function openLibrary(page) {
  await page.goto(`${UI}/scenarios`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="scenario-library"]', { timeout: 120_000 });
  return libraryCards(page);
}

async function waitPreview(page, testId = "scenario-preview") {
  await page.waitForSelector(`[data-testid="${testId}"]`, { timeout: 120_000 });
  return page.getAttribute(`[data-testid="${testId}"]`, "data-readiness");
}

async function build(page, record, { name, domain = "corporate", filter, components }) {
  await page.goto(`${UI}/scenarios/new?domain=${domain}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="scenario-builder"]', { timeout: 120_000 });
  await page.fill('[data-testid="builder-name"]', name);
  if (filter) {
    await page.click('[data-testid="builder-scope-filters"]');
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="builder-filter-column"] option').length > 5, null, { timeout: 60_000 });
    await page.selectOption('[data-testid="builder-filter-column"]', filter.column);
    await page.fill('[data-testid="builder-filter-value"]', filter.value);
  }
  // Replace the default component with the requested ones.
  await page.click('[data-testid="builder-component"] button[aria-label="Remove component"]');
  for (const c of components) {
    await page.click(`[data-testid="builder-add-${c.kind}"]`);
    const row = page.locator('[data-testid="builder-component"]').last();
    if (c.field) await row.locator('[data-testid="builder-component-field"]').selectOption(c.field);
    if (c.factor) await row.locator('[data-testid="builder-component-factor"]').fill(c.factor);
    if (c.operation) await row.locator("select").nth(c.kind === "parameter" ? 1 : 0).selectOption(c.operation);
    await row.locator('[data-testid="builder-component-value"]').fill(c.value);
  }
  record.prompts.push(`builder: ${name}`);
  await page.click('[data-testid="builder-preview"]');
  const readiness = await waitPreview(page, "builder-preview-panel");
  await page.click('[data-testid="builder-save-saved"]');
  await page.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 });
  const id = await page.getAttribute('[data-testid="scenario-detail"]', "data-object-id");
  return { id, readiness };
}

async function p4Journeys() {
  await journey("GW-P4-01", "Scenario Library opens populated: >=36 templates, 18 per book, searchable, every card previews without calculating", async (record) => {
    const page = await open();
    const total = await openLibrary(page);
    record.total = total;
    assert.ok(total >= 36, "at least 36 scenarios on first launch");
    const text = await page.textContent('[data-testid="scenario-count"]');
    assert.match(text, /Corporate 1[8-9]|Corporate [2-9]\d/);
    assert.match(text, /Retail 1[8-9]|Retail [2-9]\d/);
    await shot(page, record, "library");
    await page.click('[data-testid="scenario-domain-retail"]');
    // Non-empty AND all retail: an empty list mid-refetch satisfies every().
    await page.waitForFunction(() => {
      const cards = [...document.querySelectorAll('[data-testid="scenario-card"]')];
      return cards.length > 0 && cards.every((c) => c.getAttribute("data-domain") === "retail");
    }, null, { timeout: 60_000 });
    record.retail_cards = await page.locator('[data-testid="scenario-card"]').count();
    assert.ok(record.retail_cards >= 18);
    await page.click('[data-testid="scenario-domain-all"]');
    await page.fill('[data-testid="scenario-search"]', "hospitality");
    await page.press('[data-testid="scenario-search"]', "Enter");
    await page.waitForFunction(() => document.querySelector('[data-testid="scenario-count"]')?.getAttribute("data-total") === "1", null, { timeout: 60_000 });
    const hit = await page.getAttribute('[data-testid="scenario-card"]', "data-template-id");
    assert.equal(hit, "CORP-12");
    await page.click('[data-testid="scenario-open"]');
    await waitPreview(page);
    const statement = await page.textContent('[data-testid="scenario-not-calculated"]');
    assert.match(statement, /Nothing has been calculated/);
    assert.ok(await page.isVisible('[data-testid="scenario-component-matrix"]'));
    assert.ok(await page.isVisible('[data-testid="scenario-equation"]') && (await page.isVisible('[data-testid="scenario-contract"]')));
    await page.waitForSelector('[data-testid="scenario-stage-mix"][data-rendered="true"]', { timeout: 60_000 });
    await shot(page, record, "detail");
    // A Retail template: ML is shown and unavailable, never substituted.
    const ret = (await api(`/scenarios?domain=retail&q=RET-01`)).body.scenarios[0];
    await page.goto(`${UI}/scenarios/${ret.object_id}`, { waitUntil: "domcontentloaded" });
    await waitPreview(page);
    const ml = await page.getAttribute('[data-testid="scenario-method-ml"]', "data-status");
    record.retail_ml = ml;
    assert.equal(ml, "UNAVAILABLE");
    assert.match(await page.textContent('[data-testid="scenario-method-ml"]'), /G4/);
    await shot(page, record, "retail-ml-unavailable");
  });

  await journey("GW-P4-02", "Create A (sector PD/LGD) and B (macro) without executing; combine A+B -> overlap matrix -> explicit policy -> C saved; A and B unchanged", async (record) => {
    const page = await open();
    const a = await build(page, record, {
      name: `GW sector stress ${Date.now()}`,
      filter: { column: "sector", value: "Construction" },
      components: [
        { kind: "parameter", field: "pd_pit_12m", operation: "relative_pct", value: "20" },
        { kind: "parameter", field: "lgd_pct", operation: "relative_pct", value: "10" },
      ],
    });
    const b = await build(page, record, {
      name: `GW macro downside ${Date.now()}`,
      components: [{ kind: "macro", factor: "MEV01", operation: "percentage_points", value: "-1.5" }],
    });
    record.a = a;
    record.b = b;
    const before = {
      a: (await api(`/objects/${a.id}/history`)).body,
      b: (await api(`/objects/${b.id}/history`)).body,
    };
    assert.equal((await api(`/objects/${a.id}`)).body.status, "SAVED");
    const results = (await api(`/scenarios?owner=mine`)).body.scenarios.filter((c) => c.results > 0);
    assert.equal(results.length, 0, "saving executed nothing");

    await openLibrary(page);
    await page.click('[data-testid="scenario-owner-mine"]');
    for (const id of [a.id, b.id]) {
      await page.waitForSelector(`[data-object-id="${id}"] [data-testid="scenario-select"]`, { timeout: 60_000 });
      await page.check(`[data-object-id="${id}"] [data-testid="scenario-select"]`);
    }
    await page.click('[data-testid="scenario-combine"]');
    const readiness = await waitPreview(page, "scenario-combine-preview");
    assert.equal(readiness, "BLOCKED", "overlapping PD/LGD rules block until a policy is chosen");
    const pending = await page.locator('[data-testid="overlap-policy-select"]').count();
    record.overlaps_needing_policy = pending;
    assert.ok(pending >= 1);
    await shot(page, record, "overlap-matrix");
    const selects = page.locator('[data-testid="overlap-policy-select"]');
    for (let i = 0; i < pending; i += 1) await selects.nth(i).selectOption("compound");
    await page.click('[data-testid="overlap-resolve"]');
    await page.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 });
    const c = await page.getAttribute('[data-testid="scenario-detail"]', "data-object-id");
    record.c = c;
    assert.notEqual(c, a.id);
    const r = await waitPreview(page);
    record.c_readiness = r;
    assert.notEqual(r, "BLOCKED");
    const lineage = await page.textContent('[data-testid="scenario-lineage"]');
    assert.ok(lineage.includes("GW sector stress") && lineage.includes("GW macro downside"), "C names its parents");
    await shot(page, record, "combined");
    const after = {
      a: (await api(`/objects/${a.id}/history`)).body,
      b: (await api(`/objects/${b.id}/history`)).body,
    };
    assert.deepEqual(after, before, "the source scenarios were not modified");
  });

  await journey("GW-P4-03", "A seeded conflict template is blocked; choosing policies records them on YOUR copy and leaves the template untouched", async (record) => {
    const tpl = (await api(`/scenarios?domain=retail&q=RET-18`)).body.scenarios[0];
    const page = await open();
    await page.goto(`${UI}/scenarios/${tpl.object_id}`, { waitUntil: "domcontentloaded" });
    assert.equal(await waitPreview(page), "BLOCKED");
    assert.ok(await page.isVisible('[data-testid="scenario-blocking"]'));
    await page.selectOption('[data-testid="overlap-policy-select"]', "max");
    await shot(page, record, "blocked-template");
    await page.click('[data-testid="overlap-resolve"]');
    await page.waitForFunction((id) => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id") !== id, tpl.object_id, { timeout: 120_000 });
    const copy = await page.getAttribute('[data-testid="scenario-detail"]', "data-object-id");
    record.copy = copy;
    assert.notEqual(await waitPreview(page), "BLOCKED");
    const again = (await api(`/scenarios/${tpl.object_id}`)).body;
    assert.equal(again.scenario.version, 1);
    assert.equal(again.scenario.status, "TEMPLATE");
    await shot(page, record, "resolved-copy");
  });

  await journey("GW-P4-04", "Rename makes a new version; Share sends the reference and version, not data", async (record) => {
    const page = await open();
    const made = await build(page, record, {
      name: `GW share me ${Date.now()}`,
      components: [{ kind: "parameter", field: "pd_pit_12m", operation: "relative_pct", value: "15" }],
    });
    await page.click('[data-testid="scenario-action-rename"]');
    await page.fill('[data-testid="scenario-rename-input"]', "GW renamed scenario");
    await page.click('[data-testid="scenario-rename-submit"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-version") === "2", null, { timeout: 60_000 });
    await page.click('[data-testid="scenario-action-share"]');
    await page.fill('[data-testid="scenario-share-input"]', "colleague");
    await page.click('[data-testid="scenario-share-submit"]');
    await page.waitForSelector('[data-testid="scenario-note"]', { timeout: 60_000 });
    record.note = await page.textContent('[data-testid="scenario-note"]');
    assert.match(record.note, /reference, never the data/);
    const versions = (await api(`/objects/${made.id}/history`)).body.versions;
    record.versions = versions.map((v) => [v.version, v.lineage?.reason]);
    assert.ok(versions.length >= 3, "rename and share each made a version; the original stays");
    assert.ok(versions[0].title.startsWith("GW share me"), "version 1 keeps its original name");
    await shot(page, record, "shared");
  });
}

// =========================================================================
// P5 — What-If Analysis workspace
// =========================================================================

async function openWhatIf(page, query = "") {
  await page.goto(`${UI}/what-if${query}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="whatif-workspace"]', { timeout: 120_000 });
  await gridTotal(page);
}

async function gridTotal(page, testId = "whatif-grid") {
  await page.waitForFunction(
    (id) => Number(document.querySelector(`[data-testid="${id}"]`)?.getAttribute("data-total") || 0) > 0,
    testId,
    { timeout: 120_000 },
  );
  return Number(await page.getAttribute(`[data-testid="${testId}"]`, "data-total"));
}

/** Click the Plotly bar whose category is `label`, with a real mouse. */
async function clickBar(page, chartTestId, label) {
  const chart = `[data-testid="${chartTestId}"]`;
  await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 60_000 });
  const index = await page.evaluate(
    ([sel, want]) => (document.querySelector(sel)?.data?.[0]?.x ?? []).map(String).indexOf(want),
    [chart, label],
  );
  assert.ok(index >= 0, `${label} is a bar of ${chartTestId}`);
  // Centre the chart: "if needed" scrolling can leave it under the What-If
  // selection bar (sticky, z-10), so a coordinate click lands on the overlay
  // and the bar never receives it (GW-P5-06 in candidate G's regression).
  await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView({ block: "center" }), chart);
  await page.waitForTimeout(300);
  const box = await page.locator(`${chart} g.point path`).nth(index).boundingBox();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const onChart = await page.evaluate(
    ([sel, px, py]) => Boolean(document.querySelector(sel)?.contains(document.elementFromPoint(px, py))),
    [chart, x, y],
  );
  assert.ok(onChart, `the ${label} bar of ${chartTestId} is covered by another element at (${x}, ${y})`);
  await page.mouse.move(x, y);
  await page.waitForTimeout(250);
  await page.mouse.click(x, y);
}

async function waitSelectionEntities(page, n) {
  await page.waitForFunction(
    (want) => document.querySelector('[data-testid="whatif-selection-summary"]')?.getAttribute("data-entities") === String(want),
    n,
    { timeout: 60_000 },
  );
}

async function p5Journeys() {
  await journey("GW-P5-01", "What-If Analysis replaces Stress Testing; /stress redirects; Ask box on top; book toggle changes period and grain; Retail ML visibly unavailable", async (record) => {
    const page = await open();
    await page.goto(`${UI}/stress?from=bookmark`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/what-if\?from=bookmark/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="whatif-workspace"]', { timeout: 120_000 });
    const nav = await page.textContent("nav, aside");
    record.nav_has_whatif = nav.includes("What-If Analysis");
    record.nav_has_stress = nav.includes("Stress Testing");
    assert.ok(record.nav_has_whatif && !record.nav_has_stress, "one label, What-If Analysis");
    const askY = (await page.locator('[data-testid="whatif-ask-box"]').boundingBox()).y;
    const gridY = (await page.locator('[data-testid="whatif-grid"]').boundingBox()).y;
    assert.ok(askY < gridY, "the Ask box is above the grid");
    record.corporate_total = await gridTotal(page);
    assert.equal(record.corporate_total, 2996);
    assert.match(await page.textContent('[data-testid="whatif-book"]'), /quarter 2026Q2/);
    await shot(page, record, "corporate");
    await page.click('[data-testid="ws-domain-retail"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "6702", null, { timeout: 120_000 });
    assert.match(await page.textContent('[data-testid="whatif-book"]'), /month 2026-08/);
    assert.equal(await page.getAttribute('[data-testid="whatif-method-ml"]', "data-status"), "UNAVAILABLE");
    assert.match(await page.textContent('[data-testid="whatif-ml-unavailable"]'), /G4/);
    await shot(page, record, "retail");
  });

  await journey("GW-P5-02", "Explorer click cross-filters the grid; box/lasso selects several; select-all-filtered binds the complete cohort; saved cohort reconciles", async (record) => {
    const page = await open();
    await openWhatIf(page);
    await clickBar(page, "whatif-chart-dimension", "Construction");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "248", null, { timeout: 60_000 });
    record.after_click = 248;
    const chips = await page.$$eval('[data-testid="whatif-grid"] [data-testid="grid-filter-chip"]', (c) => c.map((x) => x.textContent));
    record.filter_chips = chips;
    assert.ok(chips.some((c) => c.includes("Construction")), "the click became a grid filter");
    // Click again: the filter clears (toggle).
    await clickBar(page, "whatif-chart-dimension", "Construction");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "2996", null, { timeout: 60_000 });
    // Box-select the first two bars.
    const chart = '[data-testid="whatif-chart-dimension"]';
    const b0 = await page.locator(`${chart} g.point path`).nth(0).boundingBox();
    const b1 = await page.locator(`${chart} g.point path`).nth(1).boundingBox();
    // A box from above the tallest of the two bars down to the axis.
    await page.mouse.move(b0.x - 4, Math.min(b0.y, b1.y) - 8);
    await page.mouse.down();
    await page.mouse.move(b1.x + b1.width + 4, b0.y + b0.height - 2, { steps: 12 });
    await page.mouse.up();
    await page.waitForFunction(() => {
      const t = Number(document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") || 0);
      return t > 0 && t < 2996;
    }, null, { timeout: 60_000 });
    const boxed = await page.$$eval('[data-testid="whatif-grid"] [data-testid="grid-filter-chip"]', (c) => c.map((x) => x.textContent));
    record.box_select_chips = boxed;
    record.after_box = Number(await page.getAttribute('[data-testid="whatif-grid"]', "data-total"));
    assert.ok(boxed.some((c) => c.split(",").length === 2), "two categories from one box selection");
    await shot(page, record, "box-select");
    // Back to Construction only, then select everything the filter matches.
    await page.goto(`${UI}/what-if`, { waitUntil: "domcontentloaded" });
    await gridTotal(page);
    await clickBar(page, "whatif-chart-dimension", "Construction");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "248", null, { timeout: 60_000 });
    await page.click('[data-testid="whatif-grid-select-all-filtered"]');
    await waitSelectionEntities(page, 248);
    const text = await page.textContent('[data-testid="whatif-selection-summary"]');
    record.summary = text;
    assert.match(text, /248 facilities/);
    assert.match(text, /100 borrowers/);
    await page.click('[data-testid="whatif-save-cohort"]');
    await page.fill('[data-testid="whatif-save-form-input"]', "GW Construction (grid)");
    await page.click('[data-testid="whatif-save-form-submit"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 60_000 });
    const cohortId = await page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id");
    record.cohort_id = cohortId;
    const cohort = (await api(`/objects/${cohortId}`)).body;
    assert.equal(cohort.body.counts.entities, 248);
    assert.equal(cohort.body.member_ids.length, 248, "the whole filtered cohort, not the page");
    await shot(page, record, "saved");
  });

  await journey("GW-P5-03", "One row, several rows, clear selection", async (record) => {
    const page = await open();
    await openWhatIf(page);
    await page.locator('[data-testid="whatif-grid"] [data-testid="grid-row"] input[type="checkbox"]').first().check();
    await waitSelectionEntities(page, 1);
    for (let i = 1; i < 4; i += 1) await page.locator('[data-testid="whatif-grid"] [data-testid="grid-row"] input[type="checkbox"]').nth(i).check();
    await waitSelectionEntities(page, 4);
    record.summary = await page.textContent('[data-testid="whatif-selection-summary"]');
    await page.click('[data-testid="whatif-clear"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-selection"]')?.getAttribute("data-mode") === "none", null, { timeout: 30_000 });
    assert.equal(await page.locator('[data-testid="whatif-grid"] [data-testid="grid-row"] input[type="checkbox"]:checked').count(), 0);
  });

  await journey("GW-P5-04", "Manual selection -> Ask -> the conversation binds the SAME governed cohort; adopting it returns the identical contract", async (record) => {
    const page = await open();
    await openWhatIf(page);
    for (let i = 0; i < 5; i += 1) await page.locator('[data-testid="whatif-grid"] [data-testid="grid-row"] input[type="checkbox"]').nth(i).check();
    await waitSelectionEntities(page, 5);
    const question = "Increase PD by 20% and LGD by 10% for this selection";
    record.prompts.push(question);
    await page.fill('[data-testid="whatif-ask-input"]', question);
    await page.click('[data-testid="whatif-ask"]');
    await page.waitForSelector('[data-testid="whatif-conversation"]', { timeout: 90_000 });
    const cohortId = await page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id");
    record.manual_cohort = cohortId;
    assert.ok(cohortId, "the manual selection was frozen before the question ran");
    await settle(page, 0);
    record.thread_id = await page.getAttribute('[data-testid="whatif-conversation"]', "data-thread-id");
    const conversational = (await api(`/whatif/threads/${record.thread_id}/cohort`)).body;
    const manual = (await api(`/objects/${cohortId}`)).body;
    record.conversation_membership = conversational.membership_hash;
    record.manual_membership = manual.body.membership_hash;
    assert.equal(conversational.has_cohort, true);
    assert.equal(conversational.entities, 5);
    assert.equal(conversational.membership_hash, manual.body.membership_hash, "one cohort contract, two routes");
    await shot(page, record, "conversation");
    await page.click('[data-testid="whatif-adopt-cohort"]');
    await page.waitForSelector('[data-testid="whatif-note"]', { timeout: 60_000 });
    const adoptedId = await page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id");
    const adopted = (await api(`/objects/${adoptedId}`)).body;
    record.adopted = adoptedId;
    assert.equal(adopted.body.membership_hash, manual.body.membership_hash);
    assert.equal(adopted.body.source.kind, "conversation");
  });

  await journey("GW-P5-05", "Load a scenario from the library and Apply it to the active cohort: bound, previewed, not calculated; Scenario Library 'Open in What-If' lands here with the same object", async (record) => {
    const page = await open();
    await openWhatIf(page);
    await clickBar(page, "whatif-chart-dimension", "Construction");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "248", null, { timeout: 60_000 });
    await page.click('[data-testid="whatif-grid-select-all-filtered"]');
    await waitSelectionEntities(page, 248);
    await page.click('[data-testid="whatif-load-scenario"]');
    await page.fill('[data-testid="whatif-scenario-filter"]', "CORP-02");
    await page.click('[data-testid="whatif-scenario-pick"][data-template-id="CORP-02"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id"), null, { timeout: 60_000 });
    await page.click('[data-testid="whatif-apply"]');
    await page.waitForSelector('[data-testid="whatif-preview"]', { timeout: 120_000 });
    const statement = await page.textContent('[data-testid="whatif-preview"] [data-testid="scenario-not-calculated"]');
    assert.match(statement, /Nothing has been calculated/);
    const kpis = await page.textContent('[data-testid="whatif-preview"] [data-testid="scenario-scope-kpis"]');
    record.kpis = kpis;
    assert.match(kpis, /248/);
    const boundId = await page.getAttribute('[data-testid="whatif-application"]', "data-scenario-id");
    const bound = (await api(`/scenarios/${boundId}`)).body.scenario;
    record.bound = `${boundId} v${bound.version}`;
    assert.equal(bound.body.scope.type, "cohort");
    const template = (await api(`/scenarios/scn-tpl-corp-02`)).body.scenario;
    assert.equal(template.version, 1, "the library template was not changed");
    await shot(page, record, "applied");
    // The Scenario Library's handoff opens the SAME object here.
    await page.goto(`${UI}/scenarios/${boundId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="scenario-open-whatif"]', { timeout: 60_000 });
    await page.click('[data-testid="scenario-open-whatif"]');
    await page.waitForSelector('[data-testid="whatif-workspace"]', { timeout: 120_000 });
    await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") === id, boundId, { timeout: 60_000 });
  });

  await journey("GW-P5-06", "Investigate in Cockpit from a What-If selection opens a thread seeded with the exact cohort", async (record) => {
    const page = await open();
    await openWhatIf(page, "?domain=retail");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "6702", null, { timeout: 120_000 });
    await clickBar(page, "whatif-chart-dimension", "Credit Card");
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "1772", null, { timeout: 60_000 });
    await page.click('[data-testid="whatif-grid-select-all-filtered"]');
    await waitSelectionEntities(page, 1772);
    await page.click('[data-testid="whatif-investigate"]');
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
    record.thread_id = /\/thread\/([A-Za-z0-9-]+)/.exec(page.url())?.[1];
    const thread = await v4(`/threads/${record.thread_id}`);
    assert.equal(thread?.domain_id ?? thread?.thread?.domain_id, "retail");
    await shot(page, record, "thread");
  });
}


// =========================================================================
// P6 — Method gate, dual-scope decomposition, lineage
// =========================================================================

async function waitRunState(page, state, timeout = 120_000) {
  await page.waitForFunction(
    (want) => document.querySelector('[data-testid="whatif-run"]')?.getAttribute("data-state") === want,
    state,
    { timeout },
  );
}

async function startScenarioRun(page, query) {
  await openWhatIf(page, query);
  await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
  await page.click('[data-testid="whatif-run-start"]');
}

async function confirmAndChoose(page, record, methods) {
  await waitRunState(page, "SCENARIO_PREVIEW");
  await page.click('[data-testid="whatif-run-confirm"]');
  await waitRunState(page, "METHOD_SELECTION");
  for (const m of methods) await page.check(`[data-testid="whatif-method-pick-${m}"]`);
  await page.click('[data-testid="whatif-run-execute"]');
}

async function resultRendered(page) {
  await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 180_000 });
  await page.waitForSelector('[data-testid="whatif-waterfall-selected"][data-rendered="true"]', { timeout: 60_000 });
  // Two bridges (a subset of the book) -- or ONE bridge with the proven
  // "Selected scope = Total book" panel (DECOMP21) when the population is
  // the whole book.
  await page.waitForSelector('[data-testid="whatif-waterfall-total"][data-rendered="true"], [data-testid="whatif-scope-equivalence"]', { timeout: 60_000 });
}

async function p6Journeys() {
  await journey("GW-P6-01", "UAT-01 in What-If: Construction 248 facilities / 100 borrowers, PD x1.20, LGD x1.10, stages fixed, CONFIRMED with NO method -> stops at METHOD SELECTION; nothing executed; then Delta runs and the dual-scope Plotly decomposition reconciles", async (record) => {
    const page = await open();
    await startScenarioRun(page, "?scenario=scn-tpl-corp-02&from=library");
    await waitRunState(page, "SCENARIO_PREVIEW");
    const pop = page.locator('[data-testid="whatif-run-population"]');
    record.entities = await pop.getAttribute("data-entities");
    record.owners = await pop.getAttribute("data-owners");
    assert.equal(record.entities, "248");
    assert.equal(record.owners, "100");
    assert.match(await page.textContent('[data-testid="whatif-run-preview"]'), /Stages frozen/);
    await page.click('[data-testid="whatif-run-confirm"]');
    await waitRunState(page, "METHOD_SELECTION");
    record.headline = await page.textContent('[data-testid="whatif-method-headline"]');
    assert.match(record.headline, /confirmed — NOT executed/);
    for (const m of ["delta", "ml", "user_defined", "compare"]) await page.waitForSelector(`[data-testid="whatif-method-${m}"]`);
    const picked = await page.$$eval('[data-testid^="whatif-method-pick-"]', (els) => els.filter((e) => e.checked).length);
    assert.equal(picked, 0, "no method is preselected");
    const runId = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    record.run_id = runId;
    const forced = await api(`/whatif/runs/${runId}/execute`, { method: "POST" });
    record.forced_execute_status = forced.status;
    assert.equal(forced.status, 409, "a crafted execute without a method is refused");
    const results = (await api(`/scenarios/scn-tpl-corp-02/results`)).body.results;
    assert.equal(results.filter((r) => r.run_id === runId).length, 0, "nothing was executed");
    await shot(page, record, "method-selection");
    // Reopening the run keeps it at method selection.
    await page.goto(`${UI}/what-if?run=${runId}`, { waitUntil: "domcontentloaded" });
    await waitRunState(page, "METHOD_SELECTION");
    await page.check('[data-testid="whatif-method-pick-delta"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const decomp = page.locator('[data-testid="whatif-decomposition"]');
    record.reconciles = await decomp.getAttribute("data-reconciles");
    assert.equal(record.reconciles, "true");
    assert.equal(await page.getAttribute('[data-testid="whatif-cross-scope"]', "data-reconciles"), "true");
    const rows = await page.$$eval('[data-testid="whatif-decomp-table"] tr[data-component]', (els) => els.map((e) => [e.dataset.component, e.dataset.status, e.dataset.selected]));
    record.components = rows.length;
    assert.equal(rows.length, 20, "every taxonomy component is listed");
    const pd = rows.find((r) => r[0] === "pd");
    const lgd = rows.find((r) => r[0] === "lgd");
    assert.ok(Number(pd[2]) > 0 && Number(lgd[2]) > 0, "PD and LGD bars carry the movement");
    // Same component, same colour and x in both scope charts.
    const colours = await page.evaluate(() =>
      ["selected", "total"].map((n) => {
        const d = document.querySelector(`[data-testid="whatif-waterfall-${n}"]`)?.data?.[0];
        return JSON.stringify([d?.x, d?.marker?.color]);
      }),
    );
    assert.equal(colours[0], colours[1]);
    record.distinct_colours = new Set(JSON.parse(colours[0])[1]).size;
    assert.ok(record.distinct_colours >= 15, "varied colours, not one blue");
    record.strip_method = await page.getAttribute('[data-testid="whatif-strip-method"]', "data-methods");
    assert.equal(record.strip_method, "delta");
    await shot(page, record, "decomposition");
  });

  await journey("GW-P6-02", "Retail ML is visibly unavailable (G4) and refused without a Delta fallback; the same confirmed scenario then runs with Delta", async (record) => {
    const page = await open();
    await startScenarioRun(page, "?domain=retail&scenario=scn-tpl-ret-01&from=library");
    await waitRunState(page, "SCENARIO_PREVIEW");
    await page.click('[data-testid="whatif-run-confirm"]');
    await waitRunState(page, "METHOD_SELECTION");
    record.ml_status = await page.getAttribute('[data-testid="whatif-method-ml"]', "data-status");
    record.ml_reason = await page.textContent('[data-testid="whatif-method-reason-ml"]');
    assert.equal(record.ml_status, "UNAVAILABLE");
    assert.match(record.ml_reason, /G4/);
    await page.check('[data-testid="whatif-method-pick-ml"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "METHOD_UNAVAILABLE");
    record.gate = await page.textContent('[data-testid="whatif-method-gate"]');
    assert.match(record.gate, /nothing is substituted/);
    assert.equal(await page.$('[data-testid="whatif-result"]'), null);
    await shot(page, record, "ml-refused");
    await page.uncheck('[data-testid="whatif-method-pick-ml"]');
    await page.check('[data-testid="whatif-method-pick-delta"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    assert.equal(await page.getAttribute('[data-testid="whatif-result"]', "data-methods-ran"), "delta");
  });

  await journey("GW-P6-03", "A second scenario asks ORIGINAL baseline or LAYER on the latest; A, then B layered on A, then C layered on A+B: lineage persists and the book starts where its ancestors left it", async (record) => {
    const page = await open();
    await startScenarioRun(page, "?scenario=scn-tpl-corp-01&from=library");
    await confirmAndChoose(page, record, ["delta"]);
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const runA = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    // B: another scenario in the same session -> the question, never assumed.
    await page.goto(`${UI}/what-if?scenario=scn-tpl-corp-06`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
    await page.click('[data-testid="whatif-run-start"]');
    await waitRunState(page, "WAITING_BASELINE_CHOICE");
    const options = await page.$$eval('[data-testid="whatif-baseline-option"]', (els) => els.map((e) => [e.dataset.mode, e.dataset.parent]));
    record.options_b = options;
    assert.deepEqual(options[0], ["SOURCE_BASELINE", ""]);
    assert.ok(options.some((o) => o[1] === runA), "layer on A is offered");
    await shot(page, record, "baseline-question");
    await page.check(`[data-testid="whatif-baseline-option"][data-parent="${runA}"]`);
    await page.click('[data-testid="whatif-baseline-choose"]');
    await confirmAndChoose(page, record, ["delta"]);
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const runB = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    assert.equal(await page.getAttribute('[data-testid="whatif-result-baseline"]', "data-mode"), "PRIOR_SCENARIO");
    // C on A+B.
    await page.goto(`${UI}/what-if?scenario=scn-tpl-corp-05`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
    await page.click('[data-testid="whatif-run-start"]');
    await waitRunState(page, "WAITING_BASELINE_CHOICE");
    await page.check(`[data-testid="whatif-baseline-option"][data-parent="${runB}"]`);
    await page.click('[data-testid="whatif-baseline-choose"]');
    await confirmAndChoose(page, record, ["delta"]);
    await waitRunState(page, "EXECUTED", 240_000);
    await resultRendered(page);
    const runC = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    const c = (await api(`/whatif/runs/${runC}`)).body;
    record.chain = c.body.chain.map((l) => l.executed_run_id);
    assert.deepEqual(record.chain, [runA, runB]);
    const result = (await api(`/objects/${c.body.result_id}`)).body.body;
    record.layered_book_baseline = result.book.baseline;
    assert.equal(result.decomposition.delta.cross_scope.reconciles, true);
    await shot(page, record, "abc");
  });

  await journey("GW-P6-04", "UAT-01 in the Cockpit conversation: preview with no method -> 'Yes, confirm the scenario' -> METHOD SELECTION, NOT executed -> Delta chosen as an ordinary turn -> the governed Plotly decomposition opens", async (record) => {
    const page = await open();
    await askFromHome(page, record, "For the Construction borrowers, PD x1.20 and LGD x1.10, stages fixed.");
    await page.waitForFunction(() => {
      const all = document.querySelectorAll('[data-testid="v4-turn-assistant"]');
      return /Nothing has been calculated/.test(all[all.length - 1]?.textContent ?? "");
    }, null, { timeout: 60_000 });
    const shown = await page.locator('[data-testid="v4-turn-assistant"]').last().textContent();
    record.preview_text = shown.slice(0, 400);
    assert.match(shown, /Nothing has been calculated/);
    assert.match(shown, /confirm the scenario/i);
    let turnsNow = await turns(page);
    await page.fill('[data-testid="v4-composer-input"]', "Yes, confirm the scenario");
    record.prompts.push("Yes, confirm the scenario");
    await page.click('[data-testid="v4-composer-send"]');
    await settle(page, turnsNow);
    await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-method-state") === "METHOD_SELECTION_REQUIRED", null, { timeout: 60_000 });
    const state = (await api(`/whatif/threads/${record.thread_id}/cohort`)).body;
    record.method_state = state.method_state;
    record.entities = state.entities;
    assert.equal(state.entities, 248);
    assert.equal(state.has_result, false, "confirmed, NOT executed");
    await shot(page, record, "method-selection");
    turnsNow = await turns(page);
    await page.click('[data-testid="thread-whatif-method-delta"]');
    record.prompts.push("Run the confirmed scenario with the Delta method.");
    await settle(page, turnsNow);
    await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-has-result") === "true", null, { timeout: 60_000 });
    await page.click('[data-testid="thread-whatif-open-result"]');
    await page.waitForURL(/\/what-if\/result\/res-/, { timeout: 60_000 });
    await resultRendered(page);
    assert.equal(await page.getAttribute('[data-testid="whatif-decomposition"]', "data-reconciles"), "true");
    assert.equal(await page.getAttribute('[data-testid="whatif-result"]', "data-methods-ran"), "delta");
    await shot(page, record, "cockpit-decomposition");
    // Back to the conversation that executed it: a live link, not a dead one.
    await page.click('[data-testid="whatif-result-open-thread"]');
    await page.waitForURL(new RegExp(`/cockpit/thread/${record.thread_id}`), { timeout: 60_000 });
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 60_000 });
  });
}


// =========================================================================
// P7 — Messages, tree, comparison, lineage
// =========================================================================

async function openMessage(page, kind) {
  await page.goto(`${UI}/messages`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="message-item"]', { timeout: 120_000 });
  await page.click(`[data-testid="message-item"][data-kind="${kind}"][data-seeded="true"]`);
  await page.waitForSelector('[data-testid="message-view"][data-accessible="true"]', { timeout: 60_000 });
}

async function apiRun(scenarioId, session, methods = ["delta"]) {
  let run = (await api("/whatif/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ scenario_id: scenarioId, session_id: session }) })).body;
  run = (await api(`/whatif/runs/${run.object_id}/confirm`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ digest: run.body.contract.digest }) })).body;
  run = (await api(`/whatif/runs/${run.object_id}/method`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ methods }) })).body;
  return (await api(`/whatif/runs/${run.object_id}/execute`, { method: "POST" })).body;
}

async function p7Journeys() {
  await journey("GW-P7-01", "Messages first launch holds synthetic shared definition, result and cohort; the recipient runs the shared DEFINITION as their own run: preview → confirm → METHOD SELECTION → Delta → a new result linked to the shared definition", async (record) => {
    const page = await open();
    await page.goto(`${UI}/messages`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="message-item"]', { timeout: 120_000 });
    const kinds = await page.$$eval('[data-testid="message-item"][data-seeded="true"]', (els) => els.map((e) => e.dataset.kind));
    record.seeded_kinds = kinds;
    for (const k of ["scenario", "scenario_result", "cohort"]) assert.ok(kinds.includes(k), `seeded ${k}`);
    const nav = await page.textContent("nav, aside");
    assert.ok(nav.includes("Messages"), "Messages is in the navigation");
    await openMessage(page, "scenario");
    assert.match(await page.textContent('[data-testid="message-view"]'), /SYNTHETIC DEMO/);
    const actions = await page.$$eval('[data-testid="message-actions"] button', (els) => els.map((e) => e.dataset.testid));
    record.actions = actions;
    for (const a of ["open", "run", "duplicate", "comment"]) assert.ok(actions.includes(`message-action-${a}`), a);
    await shot(page, record, "definition");
    await page.click('[data-testid="message-action-run"]');
    await page.click('[data-testid="message-run-go"]');
    await page.waitForURL(/\/what-if\?run=wrun-/, { timeout: 60_000 });
    // A second run from the same message is asked for its baseline (the
    // stub's store persists between evidence runs); never assumed.
    await page.waitForFunction(() => ["SCENARIO_PREVIEW", "WAITING_BASELINE_CHOICE"].includes(document.querySelector('[data-testid="whatif-run"]')?.getAttribute("data-state")), null, { timeout: 120_000 });
    if ((await page.getAttribute('[data-testid="whatif-run"]', "data-state")) === "WAITING_BASELINE_CHOICE") {
      record.baseline_asked = true;
      await page.check('[data-testid="whatif-baseline-option"][data-mode="SOURCE_BASELINE"]');
      await page.click('[data-testid="whatif-baseline-choose"]');
    }
    await waitRunState(page, "SCENARIO_PREVIEW");
    await page.click('[data-testid="whatif-run-confirm"]');
    await waitRunState(page, "METHOD_SELECTION");
    await page.check('[data-testid="whatif-method-pick-delta"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const runId = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    const run = (await api(`/whatif/runs/${runId}`)).body;
    record.shared_from = run.body.shared_from;
    assert.equal(run.body.shared_from.kind, "scenario");
    const result = (await api(`/objects/${run.body.result_id}`)).body;
    assert.equal(result.body.shared_from.object_id, run.body.shared_from.object_id, "the result is linked to the shared definition");
    await shot(page, record, "own-result");
  });

  await journey("GW-P7-02", "A shared executed RESULT: open the analysis, compare with my own result (comparison page: KPIs + component-by-component Plotly), save a copy, comment on the shared version", async (record) => {
    const mine = await apiRun("scn-tpl-corp-01", `gw-p7-02-${Date.now()}`);
    record.my_result = mine.result.object_id;
    const page = await open();
    await openMessage(page, "scenario_result");
    const card = await page.textContent('[data-testid="message-object"]');
    assert.match(card, /Method\(s\): delta/);
    await page.click('[data-testid="message-action-compare"]');
    await page.waitForSelector(`[data-testid="message-compare-option"][data-result-id="${record.my_result}"]`, { timeout: 60_000 });
    await page.check(`[data-testid="message-compare-option"][data-result-id="${record.my_result}"]`);
    await page.click('[data-testid="message-compare-go"]');
    await page.waitForURL(/\/what-if\/compare\/cmp-/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="comparison-chart"][data-rendered="true"]', { timeout: 60_000 });
    record.items = await page.getAttribute('[data-testid="comparison"]', "data-items");
    assert.equal(record.items, "2");
    const traces = await page.evaluate(() => document.querySelector('[data-testid="comparison-chart"]')?.data?.length);
    assert.equal(traces, 2);
    await shot(page, record, "comparison");
    await openMessage(page, "scenario_result");
    await page.click('[data-testid="message-action-save"]');
    await page.waitForSelector('[data-testid="message-note-link"]', { timeout: 60_000 });
    await page.click('[data-testid="message-note-link"]');
    await page.waitForURL(/\/what-if\/result\/res-/, { timeout: 60_000 });
    await resultRendered(page);
    await openMessage(page, "scenario_result");
    await page.fill('[data-testid="message-comment-input"]', "GW-P7-02 comment on the shared version");
    await page.click('[data-testid="message-comment-send"]');
    await page.waitForFunction(() => /GW-P7-02 comment/.test(document.querySelector('[data-testid="message-comments"]')?.textContent ?? ""), null, { timeout: 60_000 });
    await page.click('[data-testid="message-action-open"]');
    await page.waitForURL(/\/what-if\/result\/res-/, { timeout: 60_000 });
    await resultRendered(page);
  });

  await journey("GW-P7-03", "Scenario tree in What-If: A, B layered on A, a method variant of A; compare two nodes from the tree; share a result and see it in Sent", async (record) => {
    const page = await open();
    await startScenarioRun(page, "?scenario=scn-tpl-corp-01");
    await confirmAndChoose(page, record, ["delta"]);
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const runA = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    // Method variant of A: same confirmed contract, User-defined.
    await page.click('[data-testid="whatif-run-rerun"]');
    await waitRunState(page, "METHOD_SELECTION");
    const variant = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    await page.check('[data-testid="whatif-method-pick-user_defined"]');
    await page.fill('[data-testid="whatif-ud-value"]', "12");
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "EXECUTED", 180_000);
    // B layered on A.
    await page.goto(`${UI}/what-if?scenario=scn-tpl-corp-12`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
    await page.click('[data-testid="whatif-run-start"]');
    await waitRunState(page, "WAITING_BASELINE_CHOICE");
    await page.check(`[data-testid="whatif-baseline-option"][data-parent="${runA}"]`);
    await page.click('[data-testid="whatif-baseline-choose"]');
    await confirmAndChoose(page, record, ["delta"]);
    await waitRunState(page, "EXECUTED", 180_000);
    await resultRendered(page);
    const runB = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="whatif-tree"]')?.getAttribute("data-nodes") || 0) >= 3, null, { timeout: 60_000 });
    record.variant_parent = await page.getAttribute(`[data-testid="tree-node"][data-node-id="${variant}"]`, "data-variant-of");
    record.b_parent = await page.getAttribute(`[data-testid="tree-node"][data-node-id="${runB}"]`, "data-parent");
    assert.equal(record.variant_parent, runA);
    assert.equal(record.b_parent, runA);
    await shot(page, record, "tree");
    // A and B share Delta (the UD variant would not share a method with B).
    const aResult = (await api(`/whatif/runs/${runA}`)).body.body.result_id;
    const bResult = (await api(`/whatif/runs/${runB}`)).body.body.result_id;
    await page.check(`[data-testid="tree-compare-pick"][data-result-id="${aResult}"]`);
    await page.check(`[data-testid="tree-compare-pick"][data-result-id="${bResult}"]`);
    await page.click('[data-testid="tree-compare"]');
    await page.waitForURL(/\/what-if\/compare\/cmp-/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="comparison-chart"][data-rendered="true"]', { timeout: 60_000 });
    // Share the layered result and find it in Sent.
    await page.goto(`${UI}/what-if/result/${bResult}`, { waitUntil: "domcontentloaded" });
    await resultRendered(page);
    await page.click('[data-testid="whatif-result-share-open"]');
    await page.fill('[data-testid="whatif-result-share-to"]', "head-of-corporate-credit.synthetic");
    await page.fill('[data-testid="whatif-result-share-message"]', "Layered on A — GW-P7-03");
    await page.click('[data-testid="whatif-result-share-send"]');
    await page.waitForSelector('[data-testid="whatif-result-share-done"]', { timeout: 60_000 });
    await page.goto(`${UI}/messages?box=sent`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="message-item"]', { timeout: 60_000 });
    const sent = await page.$$eval('[data-testid="message-item"]', (els) => els.map((e) => e.textContent));
    assert.ok(sent.some((t) => /head-of-corporate-credit/.test(t)), "the share is in Sent");
  });

  await journey("GW-P7-04", "A shared COHORT opens in What-If with the same membership, and Investigate opens a Cockpit thread about it without rebuilding the population", async (record) => {
    const page = await open();
    await openMessage(page, "cohort");
    const objectId = await page.getAttribute('[data-testid="message-object"]', "data-object-id");
    const cohort = (await api(`/objects/${objectId}`)).body;
    record.membership = cohort.body.membership_hash;
    await page.click('[data-testid="message-action-open"]');
    await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 60_000 });
    await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === id, objectId, { timeout: 120_000 });
    await openMessage(page, "cohort");
    await page.click('[data-testid="message-action-investigate"]');
    await page.waitForURL(/\/cockpit\/thread\/th-/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 60_000 });
    await shot(page, record, "investigate");
  });
}


// =========================================================================
// P8 — Metric Catalogue
// =========================================================================

async function p8Journeys() {
  await journey("GW-P8-01", "Metric Catalogue first launch: >=50 persisted governed metrics; a definition shows every field, live values on both books, trend, breakdown whose bar click drills to the exact rows, lineage and users", async (record) => {
    const page = await open();
    await page.goto(`${UI}/metrics?m=M005`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="metric-count"]')?.getAttribute("data-count") || 0) > 0, null, { timeout: 120_000 });
    record.count = Number(await page.getAttribute('[data-testid="metric-count"]', "data-count"));
    assert.ok(record.count >= 50, `${record.count} metrics`);
    const api_ = (await api("/metrics")).body;
    assert.equal(api_.count, record.count, "the page shows the persisted count");
    const nav = await page.textContent("nav, aside");
    assert.ok(nav.includes("Metric Catalogue"));
    await page.waitForSelector('[data-testid="metric-detail"][data-metric-id="M005"]', { timeout: 60_000 });
    await page.waitForFunction(() => document.querySelector('[data-testid="metric-value-corporate"] [data-raw]')?.getAttribute("data-raw") !== "" && document.querySelector('[data-testid="metric-value-retail"] [data-raw]'), null, { timeout: 60_000 });
    record.corporate_raw = await page.getAttribute('[data-testid="metric-value-corporate"] [data-raw]', "data-raw");
    const definition = await page.textContent('[data-testid="metric-definition"]');
    for (const label of ["Formula", "Null policy", "Period semantics", "Grain", "Thresholds / materiality", "Drill-down dimensions", "Direction"]) assert.ok(definition.includes(label), label);
    await page.waitForSelector(`[data-testid="metric-trend-corporate"][data-rendered="true"]`, { timeout: 60_000 });
    await page.waitForSelector(`[data-testid="metric-trend-retail"][data-rendered="true"]`, { timeout: 60_000 });
    await clickBar(page, "metric-breakdown", "Construction");
    await page.waitForSelector('[data-testid="metric-drill"]', { timeout: 60_000 });
    record.drill_total = await page.getAttribute('[data-testid="metric-drill"]', "data-total");
    assert.equal(record.drill_total, "248");
    const lineage = await page.textContent('[data-testid="metric-lineage"]');
    assert.match(lineage, /corp_facility_quarter|stage|ead/);
    await shot(page, record, "M005");
    // Search narrows; an empty search says why it is empty.
    await page.fill('[data-testid="metric-search"]', "coverage");
    const items = await page.$$eval('[data-testid="metric-item"]', (els) => els.map((e) => e.dataset.metricId));
    assert.ok(items.includes("M052"));
    await page.fill('[data-testid="metric-search"]', "zzz-no-such-metric");
    await page.waitForSelector('[data-testid="metric-empty-by-filter"]');
    // Requires Attention uses M001: its users list says so.
    await page.goto(`${UI}/metrics?m=M001`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="metric-used-by"]', { timeout: 60_000 });
    assert.match(await page.textContent('[data-testid="metric-used-by"]'), /Requires Attention detectors: [A-Z]/);
  });
}


// =========================================================================
// P9 — Lenses 2.0
// =========================================================================

async function openLens(page, objectId) {
  await page.goto(`${UI}/lenses/${objectId}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="lens-view"]', { timeout: 120_000 });
}

async function lensCrossCount(page) {
  return Number(await page.getAttribute('[data-testid="lens-state"]', "data-cross"));
}

async function p9Journeys() {
  await journey("GW-P9-01", "Lens Library first launch: >=18 populated persona Lenses; a Lens renders governed KPIs and Plotly visuals; a category click cross-filters charts and the table; a trend point moves the Lens period; refresh records what changed and which rules breach", async (record) => {
    const page = await open();
    await page.goto(`${UI}/lenses`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="lens-library"]')?.getAttribute("data-total") || 0) > 0, null, { timeout: 120_000 });
    record.total = Number(await page.getAttribute('[data-testid="lens-library"]', "data-total"));
    assert.ok(record.total >= 18, `${record.total} Lenses`);
    const ids = await page.$$eval('[data-testid="lens-card"]', (els) => els.map((e) => e.dataset.lensId));
    for (let i = 1; i <= 18; i += 1) assert.ok(ids.includes(`LENS-${String(i).padStart(2, "0")}`), `LENS-${i}`);
    await shot(page, record, "library");
    await page.click('[data-testid="lens-card"][data-lens-id="LENS-02"]');
    await page.waitForSelector('[data-testid="lens-view"]', { timeout: 120_000 });
    const kpis = await page.$$eval('[data-testid="lens-kpi"]', (els) => els.map((e) => [e.dataset.metricId, e.dataset.raw]));
    record.kpis = kpis;
    assert.ok(kpis.length >= 5 && kpis.every(([m, raw]) => /^M\d{3}$/.test(m) && raw !== ""), "governed KPIs with values");
    await page.waitForSelector('[data-testid="lens-visual-v06"][data-rendered="true"]', { timeout: 60_000 });
    await shot(page, record, "lens-02");
    await clickBar(page, "lens-visual-v06", "Construction");
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="lens-state"]')?.getAttribute("data-cross")) === 1, null, { timeout: 60_000 });
    await page.waitForFunction(() => {
      const cells = [...document.querySelectorAll('[data-testid="lens-table-row"]')].map((r) => r.children[1]?.textContent);
      return cells.length > 0 && cells.every((c) => c === "Construction");
    }, null, { timeout: 60_000 });
    record.cross_filtered_rows = await page.getAttribute('[data-testid^="lens-table-"][data-total]', "data-total");
    assert.equal(record.cross_filtered_rows, "248");
    await shot(page, record, "cross-filtered");
    // A trend point moves the Lens to that period, and the state says so.
    const trend = '[data-testid="lens-visual-v08"]';
    await page.waitForSelector(`${trend}[data-rendered="true"]`, { timeout: 60_000 });
    await page.locator(trend).scrollIntoViewIfNeeded();
    const pts = page.locator(`${trend} g.points path`);
    const box = await pts.nth(0).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(250);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForFunction(() => /not latest/.test(document.querySelector('[data-testid="lens-period-corporate"]')?.textContent ?? ""), null, { timeout: 60_000 });
    record.moved_to = await page.getAttribute('[data-testid="lens-period-corporate"]', "data-period");
    await page.click('[data-testid="lens-reset"]');
    await page.waitForFunction(() => /\(latest\)/.test(document.querySelector('[data-testid="lens-period-corporate"]')?.textContent ?? ""), null, { timeout: 60_000 });
    assert.equal(await lensCrossCount(page), 0);
    await page.click('[data-testid="lens-refresh"]');
    await page.waitForSelector('[data-testid="lens-note"]', { timeout: 60_000 });
    record.refresh_note = await page.textContent('[data-testid="lens-note"]');
    const rules = await page.$$eval('[data-testid="lens-rule"]', (els) => els.map((e) => e.dataset.breached));
    assert.ok(rules.length >= 1, "breach rules are shown");
    // KPI → the governed definition.
    await page.click('[data-testid="lens-kpi"] >> nth=0');
    await page.waitForURL(/\/metrics\?m=M\d{3}/, { timeout: 60_000 });
  });

  await journey("GW-P9-02", "One-prompt Lens: a PREVIEW (KPIs, charts, tables, refresh rule) is shown and NOT saved until confirmed; refine by asking; save opens a live Lens; editing writes a new version", async (record) => {
    const before = (await api("/lenses")).body.total;
    const page = await open();
    await page.goto(`${UI}/lenses`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="lens-prompt"]', { timeout: 120_000 });
    const prompt = "Credit card risk with Stage 2 EAD share, weekly";
    record.prompts.push(prompt);
    await page.fill('[data-testid="lens-prompt"]', prompt);
    await page.click('[data-testid="lens-propose"]');
    await page.waitForSelector('[data-testid="lens-preview"]', { timeout: 60_000 });
    record.preview = await page.textContent('[data-testid="lens-preview-summary"]');
    assert.match(record.preview, /KPIs · \d+ charts · \d+ tables .* refresh Weekly/);
    assert.equal((await api("/lenses")).body.total, before, "a preview is not saved");
    await shot(page, record, "preview");
    await page.fill('[data-testid="lens-prompt"]', "add default-entry rate");
    await page.click('[data-testid="lens-propose"]');
    await page.waitForFunction(() => /M012/.test(document.querySelector('[data-testid="lens-preview"]')?.textContent ?? ""), null, { timeout: 60_000 });
    await page.click('[data-testid="lens-save"]');
    await page.waitForURL(/\/lenses\/lens-[0-9a-f]{12}/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="lens-kpi"]', { timeout: 120_000 });
    assert.equal((await api("/lenses")).body.total, before + 1);
    record.saved = /\/lenses\/(lens-[0-9a-f]{12})/.exec(page.url())[1];
    await page.click('[data-testid="lens-edit"]');
    await page.fill('[data-testid="lens-edit-name"]', "GW-P9-02 card Lens (edited)");
    await page.click('[data-testid="lens-edit-save"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="lens-view"]')?.getAttribute("data-version") === "2", null, { timeout: 60_000 });
  });

  await journey("GW-P9-03", "Box-select categories on a Lens chart → temporary cohort → What-If with that governed cohort; a Cockpit analysis is saved as a Lens from the thread", async (record) => {
    const page = await open();
    await openLens(page, "lens-02");
    const chart = '[data-testid="lens-visual-v06"]';
    await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 60_000 });
    await page.locator(chart).scrollIntoViewIfNeeded();
    const b0 = await page.locator(`${chart} g.point path`).nth(0).boundingBox();
    const b1 = await page.locator(`${chart} g.point path`).nth(1).boundingBox();
    // Start inside the plot area (the tallest bar may touch its top edge,
    // where Plotly's axis-drag handle would take the gesture instead).
    const plot = await page.locator(`${chart} rect.nsewdrag`).boundingBox();
    await page.mouse.move(Math.max(b0.x - 4, plot.x + 2), plot.y + 3);
    await page.mouse.down();
    await page.mouse.move(b1.x + b1.width + 4, b0.y + b0.height - 2, { steps: 12 });
    await page.mouse.up();
    await page.waitForSelector('[data-testid="lens-selection"]', { timeout: 60_000 });
    record.selection = await page.textContent('[data-testid="lens-selection"]');
    assert.match(record.selection, /sector ∈ [^,]+, /);
    await page.click('[data-testid="lens-selection-whatif"]');
    await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 60_000 });
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
    // Cockpit → Save this analysis as a Lens.
    await askFromHome(page, record, "Which sectors carry the most reported ECL?");
    await page.click('[data-testid="thread-save-as-lens"]');
    await page.waitForURL(/\/lenses(\?|$)/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="lens-preview"]', { timeout: 60_000 });
    // The origin is consumed once proposed: Back to /lenses never re-proposes.
    await page.waitForFunction(() => !location.search.includes("from_thread"), null, { timeout: 30_000 });
    await page.click('[data-testid="lens-save"]');
    await page.waitForURL(/\/lenses\/lens-[0-9a-f]{12}/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="lens-kpi"]', { timeout: 120_000 });
    const saved = (await api(`/objects/${/\/lenses\/(lens-[0-9a-f]{12})/.exec(page.url())[1]}`)).body;
    record.source = saved.body.source;
    assert.equal(saved.body.source.kind, "cockpit");
  });
}


// =========================================================================
// P10 — Monitoring Centre
// =========================================================================

async function p10Journeys() {
  await journey("GW-P10-01", "Monitoring Centre first launch: live breaches and labelled historical replay; an alert shows rule/Lens/metric versions and history; Open Lens restores the triggering period and population; acknowledging needs a note; Investigate opens Cockpit", async (record) => {
    const page = await open();
    await page.goto(`${UI}/monitoring`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="monitoring-list"]')?.getAttribute("data-count") || 0) > 0, null, { timeout: 180_000 });
    const nav = await page.textContent("nav, aside");
    assert.ok(nav.includes("Monitoring Centre"));
    // The stub store persists between evidence runs: reopen the target alert
    // if an earlier run acknowledged or resolved it.
    const sector = (await api("/monitoring?view=all&lens=lens-15")).body.alerts.find((a) => a.rule_id === "R15-1" && !a.demo_historical);
    if (sector && !["NEW", "ACTIVE", "WORSENING"].includes(sector.state)) {
      await api(`/monitoring/alerts/${sector.alert_id}/reopen`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ note: "GW-P10-01 rerun" }) });
      await page.reload();
      await page.waitForSelector('[data-testid="monitoring-alert"]', { timeout: 60_000 });
    }
    record.active = await page.getAttribute('[data-testid="monitoring-list"]', "data-count");
    await page.click('[data-testid="monitoring-view-history"]');
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="monitoring-alert"]')].length > 0 && [...document.querySelectorAll('[data-testid="monitoring-alert"]')].every((r) => r.dataset.historical === "true"), null, { timeout: 60_000 });
    assert.match(await page.textContent('[data-testid="monitoring-list"]'), /HISTORICAL · demo/);
    await page.click('[data-testid="monitoring-view-active"]');
    await page.waitForSelector('[data-testid="monitoring-alert"][data-type="breach"][data-historical="false"]', { timeout: 60_000 });
    const target = page.locator('[data-testid="monitoring-alert"][data-type="breach"]', { hasText: "Sector Watch" }).first();
    await target.click();
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 60_000 });
    const panel = await page.textContent('[data-testid="alert-panel"]');
    assert.match(panel, /R15-1 v\d/);
    assert.match(panel, /M064 v1/);
    assert.match(panel, /Status history/);
    await shot(page, record, "alert");
    await page.click('[data-testid="alert-acknowledge"]');
    await page.waitForSelector('[data-testid="alert-error"]', { timeout: 30_000 });
    await page.fill('[data-testid="alert-note"]', "GW-P10-01 reviewing with the sector team");
    await page.click('[data-testid="alert-acknowledge"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="alert-panel"]')?.getAttribute("data-state") === "ACKNOWLEDGED", null, { timeout: 60_000 });
    await page.click('[data-testid="alert-open-lens"]');
    await page.waitForURL(/\/lenses\/lens-15\?alert=alr-/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="lens-alert-banner"]', { timeout: 120_000 });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="lens-state"]')?.getAttribute("data-cross")) >= 1, null, { timeout: 60_000 });
    record.lens_state = await page.textContent('[data-testid="lens-state"]');
    assert.match(record.lens_state, /Construction/);
    await shot(page, record, "lens-at-trigger");
    await page.goBack();
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 60_000 });
    await page.click('[data-testid="alert-investigate"]');
    await page.waitForURL(/\/cockpit\/thread\/th-/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 60_000 });
  });

  await journey("GW-P10-02", "Follow a Lens → its refresh raises a breach → an Inbox card from Monitoring with Open Lens / Investigate / What-If → What-If opens with the alert's population", async (record) => {
    const page = await open();
    // Close LENS-03's open alerts so this refresh raises fresh ones.
    const open_ = (await api("/monitoring?view=all&lens=lens-03")).body.alerts.filter((a) => ["NEW", "ACTIVE", "WORSENING", "ACKNOWLEDGED"].includes(a.state) && !a.demo_historical);
    for (const a of open_) await api(`/monitoring/alerts/${a.alert_id}/resolve`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ note: "GW-P10-02 reset" }) });
    await openLens(page, "lens-03");
    if ((await page.getAttribute('[data-testid="lens-follow"]', "data-following")) !== "true") {
      await page.click('[data-testid="lens-follow"]');
      await page.waitForFunction(() => document.querySelector('[data-testid="lens-follow"]')?.getAttribute("data-following") === "true", null, { timeout: 60_000 });
    }
    await page.click('[data-testid="lens-refresh"]');
    await page.waitForSelector('[data-testid="lens-note"]', { timeout: 60_000 });
    record.note = await page.textContent('[data-testid="lens-note"]');
    assert.match(record.note, /alert\(s\) raised/);
    await page.goto(`${UI}/messages`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="message-item"][data-kind="alert"]', { timeout: 60_000 });
    await page.click('[data-testid="message-item"][data-kind="alert"] >> nth=0');
    await page.waitForSelector('[data-testid="message-alert"]', { timeout: 60_000 });
    const actions = await page.$$eval('[data-testid="message-actions"] button', (els) => els.map((e) => e.dataset.testid));
    record.actions = actions;
    for (const a of ["open", "open_monitoring", "investigate", "whatif", "comment"]) assert.ok(actions.includes(`message-action-${a}`), a);
    await shot(page, record, "inbox-alert");
    await page.click('[data-testid="message-action-whatif"]');
    await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 60_000 });
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
  });

  await journey("GW-P10-03", "The scheduler's step on demand: due Lenses refresh (idempotent on unchanged releases) and the refresh-health table shows cadence, last success and what is due", async (record) => {
    const page = await open();
    await page.goto(`${UI}/monitoring`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="monitoring-health-row"]', { timeout: 180_000 });
    await page.click('[data-testid="monitoring-tick"]');
    await page.waitForSelector('[data-testid="monitoring-note"]', { timeout: 120_000 });
    record.note = await page.textContent('[data-testid="monitoring-note"]');
    assert.match(record.note, /Lens\(es\) refreshed/);
    const rows = await page.$$eval('[data-testid="monitoring-health-row"]', (els) => els.map((e) => [e.dataset.lensId, e.dataset.stale]));
    record.health_rows = rows.length;
    assert.ok(rows.length >= 18 && rows.every((r) => r[1] === "false"));
    await shot(page, record, "health");
  });
}

// =========================================================================
// P11 — Product-wide Plotly contract
// =========================================================================

async function gridIs(page, n) {
  await page.waitForFunction((want) => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === String(want), n, { timeout: 60_000 });
}

async function p11Journeys() {
  await journey("GW-P11-01", "What-If heatmap and stage-migration Sankey: server-aggregated (small payload), reconcile to the filtered book, a flow click and a heatmap cell (via the keyboard on its data row) filter the grid; the same key again clears it", async (record) => {
    const page = await open();
    const sizes = [];
    page.on("response", async (r) => {
      if (r.url().includes("/grid/group2")) {
        try {
          sizes.push((await r.body()).length);
        } catch {
          /* navigated away */
        }
      }
    });
    await openWhatIf(page);
    await page.waitForSelector('[data-testid="whatif-chart-heatmap"][data-rendered="true"]', { timeout: 60_000 });
    await page.waitForSelector('[data-testid="whatif-chart-sankey"][data-rendered="true"]', { timeout: 60_000 });
    record.heatmap_reconciles = await page.getAttribute('[data-testid="whatif-heatmap-reconcile"]', "data-ok");
    record.sankey_reconciles = await page.getAttribute('[data-testid="whatif-sankey-reconcile"]', "data-ok");
    assert.equal(record.heatmap_reconciles, "true");
    assert.equal(record.sankey_reconciles, "true");
    assert.match(await page.textContent('[data-testid="whatif-sankey-reconcile"]'), /2,996 exposures/);
    record.group2_payload_bytes = sizes;
    assert.ok(sizes.length >= 2 && Math.max(...sizes) < 40_000, `aggregates only, never the book: ${sizes}`);
    await page.locator('[data-testid="whatif-chart-sankey-card"]').scrollIntoViewIfNeeded();
    await shot(page, record, "matrices");
    // A real mouse click on a flow whose centre is its own path.
    const target = await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll('[data-testid="whatif-chart-sankey"] path.sankey-link'));
      for (const link of links) {
        const b = link.getBoundingClientRect();
        const cx = b.x + b.width / 2;
        const cy = b.y + b.height / 2;
        if (b.width > 20 && document.elementFromPoint(cx, cy) === link) return { cx, cy };
      }
      return null;
    });
    assert.ok(target, "a clickable flow");
    await page.mouse.move(target.cx, target.cy);
    await page.waitForTimeout(250);
    await page.mouse.click(target.cx, target.cy);
    await page.waitForFunction(() => {
      const t = Number(document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") || 0);
      return t > 0 && t < 2996;
    }, null, { timeout: 60_000 });
    const chips = await page.$$eval('[data-testid="whatif-grid"] [data-testid="grid-filter-chip"]', (c) => c.map((x) => x.textContent));
    record.flow_chips = chips;
    record.after_flow = Number(await page.getAttribute('[data-testid="whatif-grid"]', "data-total"));
    const flowRows = await page.evaluate(() => document.querySelector('[data-testid="whatif-chart-sankey"]').data[0].link.customdata.map((c) => c.slice(0, 3)));
    assert.ok(flowRows.some((c) => Number(String(c[2]).replace(/,/g, "")) === record.after_flow), "grid = the clicked flow's exposures");
    assert.ok(chips.some((c) => /stage/i.test(c)), "the flow became a stage filter");
    await shot(page, record, "flow-filtered");
    // Clear, then the keyboard route on the heatmap's data table.
    await page.locator('[data-testid="whatif-grid"] button', { hasText: "Clear all filters" }).click();
    await gridIs(page, 2996);
    await page.click('[data-testid="whatif-chart-heatmap-view-data"]');
    const row = page.locator('[data-testid="whatif-chart-heatmap-table"] tr[data-activatable="true"]').first();
    const cells = await row.locator("td").allTextContents();
    record.keyboard_row = cells.slice(0, 3);
    await row.focus();
    await page.keyboard.press("Enter");
    await gridIs(page, Number(cells[2]));
    record.after_keyboard = Number(cells[2]);
    await shot(page, record, "keyboard-cell");
    await row.focus();
    await page.keyboard.press(" ");
    await gridIs(page, 2996);
  });

  await journey("GW-P11-02", "The shared chart contract on one screen: role=img labels, hover shows units, legend isolate is visual only (no refetch, totals unchanged), drag-zoom and mode-bar reset, CSV carries release/fingerprint/period/filters, PNG downloads", async (record) => {
    const page = await open();
    await openWhatIf(page);
    await page.waitForSelector('[data-testid="whatif-chart-stage"][data-rendered="true"]', { timeout: 60_000 });
    await page.waitForSelector('[data-testid="whatif-chart-heatmap"][data-rendered="true"]', { timeout: 60_000 });
    const labels = await page.$$eval('[data-plotly="true"]', (els) => els.map((e) => [e.getAttribute("role"), e.getAttribute("aria-label") ?? ""]));
    record.charts_on_screen = labels.length;
    assert.ok(labels.length >= 4 && labels.every(([r, l]) => r === "img" && l.length > 10), "every chart is a labelled image");
    // Hover: the tooltip names the unit.
    const box = await page.locator('[data-testid="whatif-chart-dimension"] g.point path').first().boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForSelector('[data-testid="whatif-chart-dimension"] .hoverlayer .hovertext', { timeout: 10_000 });
    record.hover = (await page.textContent('[data-testid="whatif-chart-dimension"] .hoverlayer')).slice(0, 160);
    assert.match(record.hover, /SAR|exposures/);
    // Legend isolate: visual only.
    const before = page.calls.length;
    const total = await page.getAttribute('[data-testid="whatif-grid"]', "data-total");
    record.step = "legend";
    await page.locator('[data-testid="whatif-chart-stage"] g.legend rect.legendtoggle').first().click();
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-chart-stage"]').data.some((t) => t.visible === "legendonly"), null, { timeout: 10_000 });
    await page.waitForTimeout(500);
    record.api_calls_on_legend_toggle = page.calls.length - before;
    assert.equal(record.api_calls_on_legend_toggle, 0, "hiding a series refetches nothing");
    assert.equal(await page.getAttribute('[data-testid="whatif-grid"]', "data-total"), total, "and changes no total");
    // It survives a re-render with fresh figure objects (uirevision).
    await page.selectOption('[data-testid="whatif-chart-dimension-card"] ~ * select, select[aria-label="Measure"]', "ead_sar_mn");
    await page.waitForTimeout(1200);
    record.hidden_after_rerender = await page.evaluate(() => document.querySelector('[data-testid="whatif-chart-stage"]').data.filter((t) => t.visible === "legendonly").length);
    assert.equal(record.hidden_after_rerender, 1, "the hidden series stays hidden across a re-render");
    // Zoom and reset on the heatmap (not a population chart, so drag = zoom).
    record.step = "zoom";
    const heat = await page.locator('[data-testid="whatif-chart-heatmap"] .nsewdrag').first().boundingBox();
    await page.mouse.move(heat.x + heat.width * 0.2, heat.y + heat.height * 0.2);
    await page.mouse.down();
    await page.mouse.move(heat.x + heat.width * 0.6, heat.y + heat.height * 0.6, { steps: 10 });
    await page.mouse.up();
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-chart-heatmap"]')._fullLayout.xaxis.autorange === false, null, { timeout: 10_000 });
    record.zoomed_range = await page.evaluate(() => document.querySelector('[data-testid="whatif-chart-heatmap"]')._fullLayout.xaxis.range);
    record.step = "reset";
    // Reset through the mode bar (a double-click on a click-to-filter chart
    // would also register as a cell click).
    await page.mouse.move(heat.x + heat.width / 2, heat.y + 10);
    await page.locator('[data-testid="whatif-chart-heatmap"] .modebar-btn[data-title="Reset axes"]').click();
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-chart-heatmap"]')._fullLayout.xaxis.autorange === true, null, { timeout: 10_000 });
    assert.equal(await page.getAttribute('[data-testid="whatif-grid"]', "data-total"), total, "zoom filters nothing");
    // CSV: the governed context travels with the numbers.
    const [csv] = await Promise.all([page.waitForEvent("download", { timeout: 30_000 }), page.click('[data-testid="whatif-chart-heatmap-csv"]')]);
    const text = fs.readFileSync(await csv.path(), "utf8");
    record.csv_header = text.split("\n").filter((l) => l.startsWith("#"));
    for (const k of ["# release:", "# fingerprint:", "# period:"]) assert.ok(text.includes(k), k);
    const dataLines = text.split("\n").filter((l) => l && !l.startsWith("#")).length - 1;
    const cellsDrawn = await page.evaluate(() => document.querySelector('[data-testid="whatif-chart-heatmap"]').data[0].z.flat().filter((v) => v !== null).length);
    record.csv_rows = dataLines;
    record.cells_drawn = cellsDrawn;
    assert.equal(dataLines, cellsDrawn, "the CSV is exactly what is drawn");
    const [png] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.locator('[data-testid="whatif-chart-heatmap-card"] button', { hasText: "PNG" }).click()]);
    record.png = png.suggestedFilename();
    assert.match(record.png, /\.png$/);
    await shot(page, record, "contract");
  });

  await journey("GW-P11-03", "An executed Delta result adds the segment Pareto (cumulative share ends at 100%) and the per-exposure change distribution, each with its exact data", async (record) => {
    const done = await apiRun("scn-tpl-corp-01", `gw-p11-03-${Date.now()}`);
    const result = done.result?.object_id;
    record.result_id = result;
    assert.ok(result, `a result: ${JSON.stringify(done).slice(0, 200)}`);
    const page = await open();
    await page.goto(`${UI}/what-if/result/${result}`, { waitUntil: "domcontentloaded" });
    await resultRendered(page);
    await page.waitForSelector('[data-testid="whatif-result-pareto"][data-rendered="true"]', { timeout: 60_000 });
    await page.waitForSelector('[data-testid="whatif-result-distribution"][data-rendered="true"]', { timeout: 60_000 });
    const cum = await page.evaluate(() => document.querySelector('[data-testid="whatif-result-pareto"]').data[1].y);
    record.pareto_last_cumulative_pct = cum[cum.length - 1];
    assert.ok(Math.abs(cum[cum.length - 1] - 100) < 0.05, "the cumulative share closes at 100%");
    await page.click('[data-testid="whatif-result-distribution-view-data"]');
    const rows = await page.$$eval('[data-testid="whatif-result-distribution-table"] tbody tr', (els) => els.map((e) => Array.from(e.children).map((c) => c.textContent)));
    record.distribution_rows = rows.length;
    assert.ok(rows.some((r) => /not moved/.test(r[0])), "unmoved exposures are accounted for in the data");
    await page.locator('[data-testid="whatif-result-pareto-card"]').scrollIntoViewIfNeeded();
    await shot(page, record, "pareto");
  });
}

async function p11bJourneys() {
  await journey("GW-P11-04", "Early Warning: clicking a warning reason cross-filters the bands, segments and underlying grid on the server; the keyboard does the same from the data row; Save cohort carries the reason", async (record) => {
    const page = await open();
    await page.goto(`${UI}/early-warning`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="ew-reasons"][data-rendered="true"]', { timeout: 120_000 });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="ew-grid"]')?.getAttribute("data-total") || 0) > 0, null, { timeout: 120_000 });
    const whole = Number(await page.getAttribute('[data-testid="ew-grid"]', "data-total"));
    record.severe_all = whole;
    const feed = (await api("/early-warning?domain=retail")).body;
    // A rule that narrows the severe population (some rules are tripped by
    // every high/critical exposure), clicked with a real mouse; bars are
    // drawn reversed, so rule i is bar (len - 1 - i).
    let pick = -1;
    for (let i = 0; i < feed.reasons.length && pick < 0; i += 1) {
      const f = (await api(`/early-warning?domain=retail&reason=${encodeURIComponent(feed.reasons[i].reason)}`)).body;
      const n = f.bands.filter((b) => ["critical", "high"].includes(b.value)).reduce((a, b) => a + b.n, 0);
      if (n > 0 && n < whole) pick = i;
    }
    assert.ok(pick >= 0, "a rule that narrows the severe population");
    const top = feed.reasons[pick];
    const bars = page.locator('[data-testid="ew-reasons"] g.point path');
    const box = await bars.nth(feed.reasons.length - 1 - pick).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(250);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForSelector(`[data-testid="ew-reason-filter"]`, { timeout: 60_000 });
    record.reason = await page.getAttribute('[data-testid="ew-reason-filter"]', "data-reason");
    assert.equal(record.reason, top.reason);
    const filtered = (await api(`/early-warning?domain=retail&reason=${encodeURIComponent(top.reason)}`)).body;
    const severe = filtered.bands.filter((b) => ["critical", "high"].includes(b.value)).reduce((a, b) => a + b.n, 0);
    await page.waitForFunction((n) => document.querySelector('[data-testid="ew-grid"]')?.getAttribute("data-total") === String(n), severe, { timeout: 60_000 });
    record.severe_tripping_reason = severe;
    assert.ok(severe < whole, "the grid narrowed to the reason");
    const critical = Number((await page.textContent('[data-testid="ew-band-critical"] .text-lg')).replace(/,/g, ""));
    assert.equal(critical, filtered.bands.find((b) => b.value === "critical")?.n ?? 0, "the band tiles follow the reason");
    await shot(page, record, "reason");
    await page.click('[data-testid="ew-save-cohort"]');
    await page.waitForSelector('[data-testid="ew-note"]', { timeout: 60_000 });
    const cohortId = /\b(coh[-_][0-9A-Za-z_-]+)/.exec(await page.textContent('[data-testid="ew-note"]'))?.[1];
    const cohort = (await api(`/objects/${cohortId}`)).body;
    record.cohort = [cohortId, cohort.body.counts.entities, cohort.body.name];
    assert.equal(cohort.body.counts.entities, severe, "the saved cohort is the filtered population");
    assert.ok(cohort.body.name.includes(top.reason));
    // Clear, then the keyboard route: Enter on the second rule's data row.
    await page.click('[data-testid="ew-reason-clear"]');
    await page.waitForFunction((n) => document.querySelector('[data-testid="ew-grid"]')?.getAttribute("data-total") === String(n), whole, { timeout: 60_000 });
    await page.click('[data-testid="ew-reasons-view-data"]');
    const other = pick === 0 ? 1 : 0;
    const row = page.locator('[data-testid="ew-reasons-table"] tr[data-activatable="true"]').nth(other);
    await row.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction((want) => document.querySelector('[data-testid="ew-reason-filter"]')?.getAttribute("data-reason") === want, feed.reasons[other].reason, { timeout: 60_000 });
    record.keyboard_reason = feed.reasons[other].reason;
    await shot(page, record, "keyboard");
  });

  await journey("GW-P11-05", "Legacy Recharts routes are not reachable as live charts with the guided flag on: /lenses/cro opens the governed Plotly CRO Lens, /stress opens What-If", async (record) => {
    const page = await open();
    await page.goto(`${UI}/lenses/cro?from=bookmark`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/lenses\/lens-01\?from=bookmark/, { timeout: 60_000 });
    await page.waitForSelector('[data-plotly="true"][data-rendered="true"]', { timeout: 120_000 });
    record.cro_lens = page.url().replace(UI, "");
    record.recharts_on_page = await page.locator(".recharts-wrapper").count();
    assert.equal(record.recharts_on_page, 0);
    await shot(page, record, "cro-lens");
    await page.goto(`${UI}/stress`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/what-if/, { timeout: 60_000 });
    record.stress = page.url().replace(UI, "");
  });
}

// =========================================================================
// P12 — Trace, exports, governance
// =========================================================================

async function readZip(file) {
  // Minimal ZIP reader via the system unzip (the browser saved the file).
  const { execFileSync } = await import("node:child_process");
  const list = execFileSync("unzip", ["-Z1", file]).toString().trim().split("\n");
  const read = (name) => execFileSync("unzip", ["-p", file, name], { maxBuffer: 64 * 1024 * 1024 });
  return { list, read };
}

async function p12Journeys() {
  await journey("GW-P12-01", "Result → Export package (the page's own Plotly charts attached as SVG + figure spec; every file hash-listed) → Trace: integrity verified, versions in the hash chain, lineage to the scenario, the run's method decisions → tenant ledger verifies → the downloaded package verifies against the store", async (record) => {
    const { createHash } = await import("node:crypto");
    const done = await apiRun("scn-tpl-corp-01", `gw-p12-01-${Date.now()}`);
    const result = done.result?.object_id;
    record.result_id = result;
    assert.ok(result, "a result");
    const page = await open();
    await page.goto(`${UI}/what-if/result/${result}`, { waitUntil: "domcontentloaded" });
    await resultRendered(page);
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 120_000 }),
      page.click('[data-testid="whatif-result-export-go"]'),
    ]);
    const file = await download.path();
    record.package = download.suggestedFilename();
    assert.match(record.package, new RegExp(`^creditprobe_${result}_v\\d+\\.zip$`));
    const zip = await readZip(file);
    const manifest = JSON.parse(zip.read("manifest.json").toString());
    record.files = zip.list.length;
    record.snapshots = manifest.snapshots.map((s) => s.path);
    assert.ok(record.snapshots.includes("snapshots/whatif-waterfall-selected.svg"), "the waterfall as drawn");
    assert.ok(record.snapshots.includes("snapshots/whatif-waterfall-selected.plotly.json"), "and its Plotly figure");
    for (const [name, sha] of Object.entries(manifest.files)) {
      assert.equal(createHash("sha256").update(zip.read(name)).digest("hex"), sha, name);
    }
    assert.ok(zip.list.includes("tables/decomposition_delta_selected.csv"));
    assert.equal(manifest.root.object_id, result);
    await page.waitForSelector('[data-testid="whatif-result-export-note"]', { timeout: 30_000 });
    await page.click('[data-testid="whatif-result-export-trace"]');
    await page.waitForSelector('[data-testid="object-trace"][data-integrity="true"]', { timeout: 60_000 });
    record.versions = await page.locator('[data-testid="trace-version"]').count();
    const ledgerOk = await page.$$eval('[data-testid="trace-version"] [data-ledger-ok]', (els) => els.map((e) => e.getAttribute("data-ledger-ok")));
    assert.ok(ledgerOk.length >= 1 && ledgerOk.every((v) => v === "true"), "each version links in the hash chain");
    const ancestors = await page.$$eval('[data-testid="trace-ancestor"]', (els) => els.map((e) => e.textContent));
    record.ancestors = ancestors;
    assert.ok(ancestors.some((a) => a.startsWith("scenario")) && ancestors.some((a) => a.startsWith("run")), "lineage to the run and the scenario");
    await shot(page, record, "result-trace");
    await page.click('[data-testid="trace-verify-ledger"]');
    await page.waitForSelector('[data-testid="trace-ledger-result"][data-ok="true"]', { timeout: 60_000 });
    record.ledger = await page.textContent('[data-testid="trace-ledger-result"]');
    await page.setInputFiles('[data-testid="trace-verify-package"]', file);
    await page.waitForSelector('[data-testid="trace-package-result"][data-ok="true"]', { timeout: 60_000 });
    record.package_verify = await page.textContent('[data-testid="trace-package-result"]');
    await shot(page, record, "verified");
    // The run's own Trace carries the method decision.
    await page.locator('[data-testid="trace-ancestor"]', { hasText: /^run/ }).first().click();
    await page.waitForSelector('[data-testid="object-trace"][data-kind="run"]', { timeout: 60_000 });
    const states = await page.$$eval('[data-testid="trace-event"][data-type="run_state"]', (els) => els.map((e) => e.textContent));
    record.run_states = states.length;
    assert.ok(states.some((t) => /METHOD_SELECTION/.test(t)) && states.some((t) => /method chosen: Method 1 — Delta/.test(t)) && states.some((t) => /EXECUTED/.test(t)));
    await shot(page, record, "run-trace");
  });

  await journey("GW-P12-02", "Lens and alert: Export package from the Lens view; the Lens Trace lists its refreshes, each in the hash chain; an alert's Trace lists its state history", async (record) => {
    const page = await open();
    await page.goto(`${UI}/lenses/lens-01`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="lens-export-go"]', { timeout: 120_000 });
    await page.waitForSelector('[data-plotly="true"][data-rendered="true"]', { timeout: 120_000 });
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click('[data-testid="lens-export-go"]')]);
    const zip = await readZip(await download.path());
    const manifest = JSON.parse(zip.read("manifest.json").toString());
    record.lens_snapshots = manifest.snapshots.length;
    assert.ok(manifest.snapshots.length >= 2 && zip.list.includes("tables/observations.csv"));
    await page.click('[data-testid="lens-export-trace"]');
    await page.waitForSelector('[data-testid="object-trace"][data-kind="lens"]', { timeout: 60_000 });
    const refreshes = await page.$$eval('[data-testid="trace-event"][data-type="lens_refresh"] [data-ledger-ok]', (els) => els.map((e) => e.getAttribute("data-ledger-ok")));
    record.lens_refreshes = refreshes.length;
    assert.ok(refreshes.length >= 1 && refreshes.every((v) => v === "true"));
    await shot(page, record, "lens-trace");
    const alerts = (await api("/monitoring?view=all")).body;
    const alert = (alerts.alerts ?? alerts.items ?? []).find((a) => !a.demo_historical) ?? (alerts.alerts ?? alerts.items ?? [])[0];
    assert.ok(alert, "an alert");
    await page.goto(`${UI}/trace/object/${alert.alert_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="object-trace"][data-kind="alert"]', { timeout: 60_000 });
    const events = await page.$$eval('[data-testid="trace-event"][data-type="alert_state"]', (els) => els.map((e) => e.textContent));
    record.alert_events = events.length;
    assert.ok(events.length >= 1 && events.some((t) => /NEW/.test(t)));
    await shot(page, record, "alert-trace");
  });

  await journey("GW-P12-03", "LLM Exchange, one recorder: a Cockpit call reads as SYSTEM / USER / ASSISTANT / TOOL CALL / TOOL RESULT / VALIDATOR in the order sent, beside canonical → translated → raw → normalized; the AI Model Lab lists the SAME exchange records (no second recorder)", async (record) => {
    const page = await open();
    await askFromHome(page, record, "Show me construction exposure by sector");
    record.run_id = await latestRun(record.thread_id);
    await page.goto(`${UI}/trace/llm-exchange/${record.run_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="llm-exchange"]', { timeout: 90_000 });
    await page.click('[data-testid="llm-call-2"] button[aria-expanded="false"]');
    await page.waitForSelector('[data-testid="llm-call-2"] button[aria-expanded="true"]', { timeout: 10_000 });
    const stages = await page.textContent('[data-testid="llm-call-2"]');
    for (const s of ["Canonical request", "Translated provider request", "Raw provider response", "Normalized response"]) assert.ok(stages.includes(s), s);
    await page.waitForSelector('[data-testid="llm-call-2"] [data-testid="llm-segment"]', { timeout: 30_000 });
    const kinds = await page.$$eval('[data-testid="llm-call-2"] [data-testid="llm-segment"]', (els) => els.map((e) => e.getAttribute("data-kind")));
    record.segment_kinds = [...new Set(kinds)];
    for (const k of ["SYSTEM", "USER", "TOOL CALL", "TOOL RESULT"]) assert.ok(kinds.includes(k), k);
    const counted = await page.$$eval('[data-testid="llm-call-2"] [data-testid="llm-segment-counts"] [data-kind]', (els) => els.map((e) => e.getAttribute("data-kind")));
    assert.deepEqual(counted, ["SYSTEM", "USER", "ASSISTANT", "TOOL CALL", "TOOL RESULT", "VALIDATOR"]);
    await shot(page, record, "segments");
    const exchange = (await api(`/llm-exchange/runs/${record.run_id}`)).body;
    const ids = exchange.calls.map((c) => c.exchange_id);
    await page.goto(`${UI}/ai-model-lab`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('a[href^="/trace/llm-exchange/"]', { timeout: 90_000 });
    const lab = (await api("/model-lab/exchanges")).body;
    const labIds = new Set((lab.exchanges ?? []).map((e) => e.exchange_id));
    record.lab_rows = labIds.size;
    assert.ok(ids.every((id) => labIds.has(id)), "the Lab lists the very records the Trace shows");
    const hrefs = await page.$$eval('a[href^="/trace/llm-exchange/"]', (els) => els.map((e) => e.getAttribute("href")));
    assert.ok(hrefs.includes(`/trace/llm-exchange/${record.run_id}`), "and links back to the same Trace");
    await shot(page, record, "lab");
  });
}

// =========================================================================
// P13 — gap closure before the regression of record
// =========================================================================

async function gridApi(filters, extra = {}) {
  return (await api("/grid/query", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ domain: "corporate", filters, limit: 50, ...extra }) })).body;
}

async function p13Journeys() {
  await journey("GW-P13-01", "GRID07: every visible grid column opens the filter editor its governed kind calls for (text box / value list / min–max / yes–no), on both books", async (record) => {
    const page = await open();
    await openWhatIf(page);
    record.checked = {};
    for (const book of ["corporate", "retail"]) {
      if (book === "retail") {
        await page.click('[data-testid="ws-domain-retail"]');
        await page.waitForFunction(() => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === "6702", null, { timeout: 120_000 });
      }
      const schema = (await api(`/grid/schema?domain=${book}`)).body;
      const visible = schema.columns.filter((c) => c.visible);
      let n = 0;
      for (const c of visible) {
        const btn = page.locator(`[data-testid="whatif-grid"] [data-testid="grid-filter-${c.key}"]`);
        if (!(await btn.count())) throw new Error(`${book}.${c.key} has no filter button`);
        await btn.scrollIntoViewIfNeeded();
        await btn.click();
        const ed = `[data-testid="grid-filter-editor-${c.key}"]`;
        await page.waitForSelector(ed, { timeout: 10_000 });
        const want = { text: `[aria-label="${c.label} contains"]`, category: `[aria-label="Search ${c.label} values"]`, range: `[aria-label="${c.label} maximum"]`, boolean: `select[aria-label="${c.label} value"]` }[c.filter];
        assert.ok(want, `${c.key}: kind ${c.filter} has an editor`);
        assert.ok(await page.locator(`${ed} ${want}`).first().count(), `${book}.${c.key} (${c.filter}) shows its control`);
        assert.ok(await page.locator(`${ed} [aria-label="${c.label} empty values"]`).count(), `${c.key}: the empty-values control`);
        await btn.click();
        n += 1;
      }
      record.checked[book] = n;
      assert.ok(n >= 30, `${book}: ${n} columns checked`);
    }
    await shot(page, record, "editors");
  });

  await journey("GW-P13-02", "GRID11 + GRID13 in the UI: a yes/no filter and an 'only empty' filter narrow the grid to exactly the server's count; sorting by EAD is server-side and page 2 continues page 1's order", async (record) => {
    const page = await open();
    await openWhatIf(page);
    const grid = '[data-testid="whatif-grid"]';
    await page.click(`${grid} [data-testid="grid-filter-watchlist_flag"]`);
    await page.locator('[data-testid="grid-filter-editor-watchlist_flag"] select').first().selectOption("yes");
    await page.click('[data-testid="grid-filter-apply-watchlist_flag"]');
    const yes = (await gridApi([{ column: "watchlist_flag", op: "eq", value: 1 }])).total;
    await page.waitForFunction((n) => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === String(n), yes, { timeout: 60_000 });
    record.watchlist_yes = yes;
    await page.locator(`${grid} button`, { hasText: "Clear all filters" }).click();
    await gridIs(page, 2996);
    await page.click(`${grid} [data-testid="grid-filter-prior_stage"]`);
    await page.selectOption('[data-testid="grid-filter-editor-prior_stage"] [aria-label$="empty values"]', "empty");
    await page.click('[data-testid="grid-filter-apply-prior_stage"]');
    const empty = (await gridApi([{ column: "prior_stage", op: "is_null" }])).total;
    await page.waitForFunction((n) => document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total") === String(n), empty, { timeout: 60_000 });
    record.prior_stage_empty = empty;
    await page.locator(`${grid} button`, { hasText: "Clear all filters" }).click();
    await gridIs(page, 2996);
    // Sort by EAD (server-side), then page 2.
    await page.click(`${grid} [data-testid="grid-sort-ead_sar_mn"]`);
    const ids = async () => page.$$eval(`${grid} [data-testid="grid-row"]`, (els) => els.map((e) => e.getAttribute("data-row-id")));
    const size = (await ids()).length;
    let want = (await gridApi([], { sort: "ead_sar_mn", desc: true, limit: size })).rows.map((r) => r.facility_id);
    await page.waitForFunction((first) => document.querySelector('[data-testid="whatif-grid"] [data-testid="grid-row"]')?.getAttribute("data-row-id") === first, want[0], { timeout: 60_000 });
    assert.deepEqual(await ids(), want, "page 1 is the server's EAD order");
    await page.click(`${grid} [data-testid="whatif-grid-next"]`);
    want = (await gridApi([], { sort: "ead_sar_mn", desc: true, limit: size, offset: size })).rows.map((r) => r.facility_id);
    await page.waitForFunction((first) => document.querySelector('[data-testid="whatif-grid"] [data-testid="grid-row"]')?.getAttribute("data-row-id") === first, want[0], { timeout: 60_000 });
    assert.deepEqual(await ids(), want, "page 2 continues the order");
    record.page_size = size;
    await shot(page, record, "sorted-page-2");
  });

  await journey("GW-P13-03", "MAC07: the macro-sensitivity tornado follows the explorer's population, names the risk parameter on every bar, hovers with the governed fields, and flags the collateral sign for review instead of flipping it", async (record) => {
    const page = await open();
    await openWhatIf(page);
    const chart = '[data-testid="whatif-chart-tornado"]';
    await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 120_000 });
    const labels = await page.evaluate((sel) => document.querySelector(sel).data[1].y, chart);
    record.bars = labels.length;
    assert.ok(labels.length >= 8 && labels.every((l) => /→ (PD 12m|PD lifetime|LGD)/.test(l)));
    await page.locator(chart).scrollIntoViewIfNeeded();
    const bar = page.locator(`${chart} g.point path`).last();
    await bar.scrollIntoViewIfNeeded();
    const box = await bar.boundingBox();
    await page.mouse.move(box.x + Math.max(2, box.width / 2), box.y + box.height / 2);
    await page.waitForSelector(`${chart} .hoverlayer .hovertext`, { timeout: 10_000 });
    const hover = await page.textContent(`${chart} .hoverlayer`);
    record.hover = hover.slice(0, 200);
    for (const k of ["shock", "affects", "coefficient", "sign", "method", "window"]) assert.ok(hover.includes(k), k);
    await page.selectOption('[data-testid="tornado-parameter"]', "lgd");
    await page.waitForFunction((sel) => (document.querySelector(sel)?.data?.[1]?.y ?? []).every((l) => l.includes("→ LGD")), chart, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="tornado-sign-review"]', { timeout: 60_000 });
    record.sign_review = (await page.textContent('[data-testid="tornado-sign-review"]')).slice(0, 160);
    assert.match(record.sign_review, /SIGN_REVIEW/);
    const api_ = (await api("/whatif/sensitivity/tornado", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ domain: "corporate", parameter: "lgd", top: 12 }) })).body;
    const drawn = await page.evaluate((sel) => document.querySelector(sel).data[1].x, chart);
    assert.deepEqual([...drawn].reverse(), api_.rows.map((r) => r.up_pp), "bars are the governed values, signs as fitted");
    await page.locator('[data-testid="whatif-macro-tornado"]').scrollIntoViewIfNeeded();
    await shot(page, record, "tornado-lgd");
    // The population follows the explorer filter.
    await clickBar(page, "whatif-chart-dimension", "Construction");
    await page.waitForFunction(() => /248 exposures/.test(document.querySelector('[data-testid="whatif-chart-tornado-card"]')?.textContent ?? ""), null, { timeout: 60_000 });
  });

  await journey("GW-P13-04", "Method names and 'Selected scope = Total book': a whole-book Delta result says Method 1 — Delta, draws ONE bridge with the scope-equivalence panel (rest-of-book Δ = 0, selected Δ = total Δ) and marks every component identical", async (record) => {
    const done = await apiRun("scn-tpl-corp-05", `gw-p13-04-${Date.now()}`);
    const result = done.result?.object_id;
    assert.ok(result, "a whole-book result");
    record.result_id = result;
    const page = await open();
    await page.goto(`${UI}/what-if/result/${result}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 180_000 });
    assert.equal((await page.textContent('[data-testid="whatif-result-method-delta"]')).trim(), "Method 1 — Delta");
    await page.waitForSelector('[data-testid="whatif-scope-equivalence"]', { timeout: 60_000 });
    record.equivalence = (await page.textContent('[data-testid="whatif-scope-equivalence"]')).slice(0, 240);
    assert.match(record.equivalence, /Selected scope = Total book/);
    assert.match(await page.textContent('[data-testid="whatif-equivalence-rest"]'), /SAR 0/);
    await page.waitForSelector('[data-testid="whatif-waterfall-selected"][data-rendered="true"]', { timeout: 60_000 });
    assert.equal(await page.locator('[data-testid="whatif-waterfall-total"]').count(), 0, "no duplicate bridge");
    const same = await page.$$eval('[data-testid="whatif-decomp-identical"]', (els) => els.map((e) => e.textContent));
    record.components = same.length;
    assert.ok(same.length >= 20 && same.every((t) => t.includes("same population")));
    const n = await page.getAttribute('[data-testid="whatif-equivalence-components"]', "data-identical");
    assert.equal(Number(n), Number(await page.getAttribute('[data-testid="whatif-equivalence-components"]', "data-components")));
    await shot(page, record, "scope-equals-book");
  });

  await journey("GW-P13-05", "VIZ02 responsive: at a 390 px phone viewport the main pages render without horizontal page scroll and every chart fits the screen; at 1440 px the same charts are wider", async (record) => {
    const done = await apiRun("scn-tpl-corp-01", `gw-p13-05-${Date.now()}`);
    const pages = [["/what-if", '[data-testid="whatif-chart-heatmap"][data-rendered="true"]'], [`/what-if/result/${done.result?.object_id}`, '[data-testid="whatif-waterfall-selected"][data-rendered="true"]'], ["/lenses/lens-01", '[data-plotly="true"][data-rendered="true"]'], ["/monitoring", '[data-plotly="true"][data-rendered="true"]'], ["/metrics", '[data-testid="metric-catalogue"], main'], ["/messages", '[data-testid="message-item"]']];
    record.pages = {};
    for (const width of [390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      live.push(page);
      for (const [path_, ready] of pages) {
        await page.goto(`${UI}${path_}`, { waitUntil: "domcontentloaded" });
        await page.waitForSelector(ready, { timeout: 180_000 });
        await page.waitForTimeout(400);
        const m = await page.evaluate(() => {
          const charts = Array.from(document.querySelectorAll('[data-plotly="true"][data-rendered="true"]')).map((e) => e.getBoundingClientRect().width);
          return { scroll: document.documentElement.scrollWidth, inner: window.innerWidth, widest: Math.max(0, ...charts), charts: charts.length };
        });
        record.pages[`${width}:${path_.split("/").slice(0, 3).join("/")}`] = m;
        assert.ok(m.scroll <= m.inner + 1, `${path_} at ${width}px scrolls sideways (${m.scroll} > ${m.inner})`);
        assert.ok(m.widest <= m.inner, `${path_} at ${width}px: a chart is wider than the screen`);
        if (width === 390 && path_ === "/what-if") await shot(page, record, "phone-what-if");
      }
    }
  });
}

// =========================================================================
// P16 — final gap closure: clicks-only root cause (GX-08) and card wiring
// =========================================================================

async function p16Journeys() {
  await journey("GW-P16-01", "GX-08 by clicks only: Requires Attention card → Investigate → a driver chip answered in the SAME thread → the stress-test chip opens What-If on the investigation's exact cohort → Ask (pre-filled, not typed) → preview → 'Yes, confirm the scenario' button → METHOD SELECTION → Delta button → the governed decomposition reconciles; no keystroke anywhere", async (record) => {
    const page = await open();
    await page.addInitScript(() => {
      window.__keys = 0;
      window.addEventListener("keydown", () => (window.__keys += 1), true);
    });
    await openHome(page, "corporate");
    const card = page.locator('[data-testid="issue-card"]').first();
    record.issue_id = await card.getAttribute("data-issue-id");
    await card.locator('[data-testid="issue-investigate"]').click();
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
    record.thread_id = await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
    await page.waitForSelector('[data-testid="nbq-chip"]', { timeout: 60_000 });
    assert.equal(await page.locator('[data-testid="nbq-chip"][data-suggestion-type="run_whatif"]').count(), 0, "no stress test before a finding");
    const before = await turns(page);
    const driver = page.locator('[data-testid="nbq-chip"][data-suggestion-type="explain_driver"], [data-testid="nbq-chip"]').first();
    record.clicked = [(await driver.textContent()).trim()];
    await driver.click();
    await settle(page, before);
    assert.equal(await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id"), record.thread_id, "the chip ran in the same thread");
    const stress = page.locator('[data-testid="nbq-chip"][data-suggestion-type="run_whatif"]');
    await stress.waitFor({ timeout: 60_000 });
    record.clicked.push((await stress.textContent()).trim());
    const inv = (await api(`/investigations/by-thread/${record.thread_id}`)).body;
    const frozen = (await api(`/objects/${inv.cohort_id}`)).body;
    record.cohort_id = inv.cohort_id;
    record.membership_hash = frozen.body.membership_hash;
    await stress.click();
    await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 60_000 });
    assert.match(page.url(), new RegExp(`cohort=${inv.cohort_id}`), "What-If opens on the investigation's cohort");
    await page.waitForFunction(() => /stress test/i.test(document.querySelector('[data-testid="whatif-ask-input"]')?.value ?? ""), null, { timeout: 60_000 });
    await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === id, inv.cohort_id, { timeout: 60_000 });
    await page.click('[data-testid="whatif-ask"]');
    const confirm = page.locator("button", { hasText: "Yes, confirm the scenario" }).last();
    await confirm.waitFor({ timeout: 240_000 });
    const whatifThread = await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
    record.whatif_thread_id = whatifThread;
    record.clicked.push("Yes, confirm the scenario");
    await confirm.click();
    await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-method-state") === "METHOD_SELECTION_REQUIRED", null, { timeout: 240_000 });
    const state = (await api(`/whatif/threads/${whatifThread}/cohort`)).body;
    record.entities = state.entities;
    assert.equal(state.membership_hash, record.membership_hash, "the scenario runs on exactly the investigated population");
    assert.equal(state.has_result, false, "confirmed, NOT executed");
    record.clicked.push("Method 1 — Delta");
    await page.click('[data-testid="thread-whatif-method-delta"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-has-result") === "true", null, { timeout: 240_000 });
    await page.click('[data-testid="thread-whatif-open-result"]');
    await page.waitForURL(/\/what-if\/result\/res-/, { timeout: 60_000 });
    await resultRendered(page);
    assert.equal(await page.getAttribute('[data-testid="whatif-decomposition"]', "data-reconciles"), "true");
    assert.equal(await page.getAttribute('[data-testid="whatif-result"]', "data-methods-ran"), "delta");
    record.keystrokes = await page.evaluate(() => window.__keys);
    assert.equal(record.keystrokes, 0, "the whole path was completed without typing");
    await shot(page, record, "clicks-only-result");
  });

  await journey("GW-P16-02", "Requires Attention card wiring: the title opens the evidence; the largest-contributor driver opens the issue already narrowed to that driver's population (server count); the card's What-If button freezes the exact issue population and opens What-If on it", async (record) => {
    const page = await open();
    await openHome(page, "corporate");
    const card = page.locator('[data-testid="issue-card"]').filter({ has: page.locator('[data-testid="issue-driver"]') }).first();
    const issueId = await card.getAttribute("data-issue-id");
    record.issue_id = issueId;
    const issue = (await api(`/issues/${issueId}`)).body;
    const driver = (await card.locator('[data-testid="issue-driver"]').textContent()).trim();
    record.driver = driver;
    await card.locator('[data-testid="issue-driver"]').click();
    await page.waitForURL(new RegExp(`/issues/${issueId}\\?driver=`), { timeout: 60_000 });
    await page.waitForSelector('[data-testid="issue-detail"]', { timeout: 60_000 });
    const narrowed = await api("/grid/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ domain: issue.domain_id, filters: [...issue.cohort.filters, { column: issue.evidence.breakdown_dimension, op: "in", values: [driver] }], limit: 1 }),
    });
    record.driver_rows = narrowed.body.total;
    await page.waitForFunction((n) => document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") === String(n), narrowed.body.total, { timeout: 60_000 });
    await shot(page, record, "driver-population");
    await openHome(page, "corporate");
    const again = page.locator(`[data-testid="issue-card"][data-issue-id="${issueId}"]`);
    await again.locator('[data-testid="issue-title"] button').click();
    await page.waitForURL(new RegExp(`/issues/${issueId}$`), { timeout: 60_000 });
    await openHome(page, "corporate");
    await page.locator(`[data-testid="issue-card"][data-issue-id="${issueId}"] [data-testid="issue-whatif"]`).click();
    await page.waitForURL(/\/what-if\?cohort=coh-[0-9a-f]+&from=issue/, { timeout: 60_000 });
    const cohortId = new URL(page.url()).searchParams.get("cohort");
    const saved = (await api(`/objects/${cohortId}`)).body;
    record.cohort_entities = saved.body.counts.entities;
    assert.equal(saved.body.counts.entities, issue.cohort.entities, "the exact issue population, not visible rows");
    await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === id, cohortId, { timeout: 60_000 });
    await shot(page, record, "whatif-handoff");
  });
}

// =========================================================================
// VALIDATION — Back navigation (BACK_NAVIGATION_MATRIX): every path is driven
// forward, then browser Back, browser Forward and the in-product Back control
// are each checked against the origin's own state read from the page, and
// the store is checked for objects written by the return trip.
// =========================================================================

const here = (page) => {
  const u = new URL(page.url());
  return `${u.pathname}${u.search}`;
};

/** Writes and model calls a return trip must never make. */
const WRITE_ON_BACK = /^POST \/api\/v1\/cockpit-v4\/(workspace\/(whatif\/runs($|\?|\/[^/]+\/(confirm|method|execute))|cohorts($|\?)|whatif\/selection\/cohort|scenarios\/[^/]+\/(clone|resolve|retire)|scenarios\/combine|messages($|\?)|lenses\/propose|lenses($|\?)|investigations|issues\/[^/]+\/investigate|cohorts\/[^/]+\/investigate)|threads|runs|ask)/;

async function storeCounts() {
  const n = async (p, key) => ((await api(p)).body?.[key] ?? []).length;
  return {
    scenarios: await n("/scenarios?owner=mine", "scenarios"),
    cohorts: await n("/cohorts", "cohorts"),
    results: await n("/whatif/results", "results"),
    lenses: await n("/lenses", "lenses"),
    sent: await n("/messages?box=sent", "items"),
  };
}

/** Wait until the page is at `origin`'s path and `state()` reads `want`. */
async function backAt(page, originPath, stateSrc, want) {
  try {
    await page.waitForFunction((p) => location.pathname === p, originPath, { timeout: 60_000 });
    await page.waitForFunction(
      ([src, expected]) => {
        try {
          // eslint-disable-next-line no-new-func
          return JSON.stringify(new Function(`return (${src})()`)()) === expected;
        } catch {
          return false;
        }
      },
      [stateSrc, JSON.stringify(want)],
      { timeout: 60_000 },
    );
    return "PASS";
  } catch {
    const got = await page.evaluate((src) => {
      try {
        // eslint-disable-next-line no-new-func
        return new Function(`return (${src})()`)();
      } catch (e) {
        return `error: ${e}`;
      }
    }, stateSrc).catch(() => "unreadable");
    return `FAILED at ${here(page)}: state ${JSON.stringify(got).slice(0, 200)} != ${JSON.stringify(want).slice(0, 200)}`;
  }
}

/**
 * One row of the matrix. `state` is a function SOURCE evaluated in the page
 * that reads the origin's business state (filters, selection, objects).
 */
async function backTrip(page, record, { path, state, go, arrived, inApp, inAppTarget, inAppWrites = null }) {
  const stateSrc = state.toString();
  const origin = here(page);
  const originPath = new URL(page.url()).pathname;
  const want = await page.evaluate((src) => new Function(`return (${src})()`)(), stateSrc);
  await go(page);
  await arrived(page);
  const destination = here(page);
  const before = await storeCounts();
  const callMark = page.calls.length;
  const row = { path, origin, destination, origin_state: want };

  await page.goBack();
  row.browser_back = await backAt(page, originPath, stateSrc, want);
  await page.goForward();
  try {
    await arrived(page);
    row.browser_forward = new URL(page.url()).pathname === new URL(`${UI}${destination}`).pathname ? "PASS" : `FAILED at ${here(page)}`;
  } catch (e) {
    row.browser_forward = `FAILED ${String(e.message).slice(0, 120)}`;
  }
  // Browser Back/Forward alone must write nothing; a declared in-app Cancel
  // may then retire what the forward step made.
  const mid = await storeCounts();
  if (inApp) {
    try {
      const target = await page.getAttribute(inApp, "data-back-target", { timeout: 60_000 }).catch(() => null);
      row.in_app_target = target;
      await page.click(inApp, { timeout: 60_000 });
      row.in_app_back = await backAt(page, inAppTarget ?? originPath, stateSrc, want);
    } catch (e) {
      row.in_app_back = `FAILED ${String(e.message).slice(0, 160)}`;
    }
  } else {
    row.in_app_back = "N/A";
  }
  // A Cancel that discards (Clone → "Discard this copy") is a declared,
  // intended write of the in-app control; nothing else may write.
  const writes = page.calls.slice(callMark).filter((c) => WRITE_ON_BACK.test(c) && !(inAppWrites && inAppWrites.test(c)));
  row.declared_in_app_writes = inAppWrites ? page.calls.slice(callMark).filter((c) => inAppWrites.test(c)) : [];
  row.writes_on_return = writes;
  const after = inAppWrites ? mid : await storeCounts();
  row.objects_written_on_return = JSON.stringify(before) === JSON.stringify(after) ? "none" : `${JSON.stringify(before)} -> ${JSON.stringify(after)}`;
  row.status =
    row.browser_back === "PASS" && row.browser_forward === "PASS" && ["PASS", "N/A"].includes(row.in_app_back) && !writes.length && row.objects_written_on_return === "none" ? "PASS" : "FAILED";
  record.back = [...(record.back ?? []), row];
  assert.equal(row.browser_back, "PASS", `${path}: browser Back`);
  assert.equal(row.browser_forward, "PASS", `${path}: browser Forward`);
  assert.ok(["PASS", "N/A"].includes(row.in_app_back), `${path}: in-app Back — ${row.in_app_back}`);
  assert.deepEqual(writes, [], `${path}: no write or model call on the return trip`);
  assert.equal(row.objects_written_on_return, "none", `${path}: no object written on the return trip`);
  return row;
}

const post = (pathname, body) => api(pathname, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });

async function anIssue(domain = "corporate") {
  const feed = (await api(`/issues?domain=${domain}`)).body;
  return feed.issues.find((i) => (i.evidence?.breakdown ?? []).length >= 2) ?? feed.issues[0];
}

async function openIssue(page, issueId, query = "") {
  await page.goto(`${UI}/issues/${issueId}${query}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="issue-detail"]', { timeout: 120_000 });
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") || 0) > 0, null, { timeout: 120_000 });
}

const issueState = () => ({
  issue: location.pathname,
  drill: new URLSearchParams(location.search).get("driver") || new URLSearchParams(location.search).get("stage") || "",
  rows: document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") || "",
});

const whatifState = () => ({
  domain: document.querySelector('[data-testid="whatif-workspace"]')?.getAttribute("data-domain") || "",
  cohort: document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") || "",
  scenario: document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") || "",
  filters: new URLSearchParams(location.search).get("f") || "",
});

const libraryState = () => ({
  q: document.querySelector('[data-testid="scenario-search"]')?.value ?? null,
  owner: document.querySelector('[data-testid="scenario-owner"]')?.getAttribute("data-value") ?? null,
  domain: document.querySelector('[data-testid="scenario-domain"]')?.getAttribute("data-value") ?? null,
  severity: document.querySelector('[data-testid="scenario-severity"]')?.value ?? null,
  total: document.querySelector('[data-testid="scenario-count"]')?.getAttribute("data-total") ?? null,
});

const detailState = () => ({
  scenario: document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id") || "",
  version: document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-version") || "",
});

const resultState = () => ({
  result: document.querySelector('[data-testid="whatif-result"]')?.getAttribute("data-result-id") || "",
  method: document.querySelector('[data-testid^="whatif-result-method-"][aria-pressed="true"]')?.getAttribute("data-testid") || "",
});

const messagesState = () => ({
  box: new URLSearchParams(location.search).get("box") || "inbox",
  open: document.querySelector('[data-testid="message-view"]')?.getAttribute("data-share-id") || new URLSearchParams(location.search).get("m") || "",
  accessible: document.querySelector('[data-testid="message-view"]')?.getAttribute("data-accessible") || "",
});

const lensLibraryState = () => ({
  q: document.querySelector('[data-testid="lens-search"]')?.value ?? null,
  cards: document.querySelectorAll('[data-testid="lens-card"]').length,
});

const lensState = () => ({
  lens: document.querySelector('[data-testid="lens-view"]')?.getAttribute("data-object-id") || "",
  cross: document.querySelector('[data-testid="lens-state"]')?.getAttribute("data-cross") || "",
  selection: document.querySelector('[data-testid="lens-selection"]')?.textContent?.split("Save")[0]?.trim() || "",
});

const monitoringState = () => ({
  view: new URLSearchParams(location.search).get("view") || "active",
  severity: document.querySelector('[data-testid="monitoring-severity"]')?.value ?? "",
  count: document.querySelector('[data-testid="monitoring-list"]')?.getAttribute("data-count") || "",
  alert: new URLSearchParams(location.search).get("alert") || "",
});

const threadState = () => ({
  thread: document.querySelector('[data-testid="cockpit-v4-thread"]')?.getAttribute("data-thread-id") || "",
  turns: document.querySelectorAll('[data-testid="v4-turn-assistant"]').length,
});

const exchangeState = () => ({
  call: new URLSearchParams(location.search).get("call") || "",
  stage: new URLSearchParams(location.search).get("stage") || "",
  calls: document.querySelectorAll('[data-testid^="llm-call-"]').length,
});

async function waitWhatIfObjects(page, { cohort = "", scenario = "" }) {
  await page.waitForSelector('[data-testid="whatif-workspace"]', { timeout: 120_000 });
  await page.waitForFunction(
    ([c, s]) =>
      (!c || document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === c) &&
      (!s || document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") === s),
    [cohort, scenario],
    { timeout: 120_000 },
  );
}

async function threadFromIssue(page, issueId) {
  await openIssue(page, issueId);
  await page.click('[data-testid="issue-detail-investigate"]');
  await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 90_000 });
  await page.waitForSelector('[data-testid="investigation-bar"]', { timeout: 90_000 });
  await settle(page, 0).catch(() => undefined);
  return page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
}

async function backJourneys() {
  await journey("GW-BACK-01", "Home → Requires Attention issue → Back → Home on the same book", async (record) => {
    const page = await open();
    await openHome(page, "retail");
    await backTrip(page, record, {
      path: "Home → issue → Back",
      state: () => ({ book: document.querySelector('[data-testid="domain-switch"]')?.getAttribute("data-domain") || "", issues: document.querySelector('[data-testid="requires-attention"]')?.getAttribute("data-count") || "" }),
      go: (p) => p.locator('[data-testid="issue-card"]').first().locator('[data-testid="issue-title"] button').click(),
      arrived: (p) => p.waitForSelector('[data-testid="issue-detail"]', { timeout: 120_000 }),
      inApp: '[data-testid="issue-detail-back"]',
      inAppTarget: "/",
    });
  });

  await journey("GW-BACK-02", "Issue → Investigate → Back → the same issue (in-app: the thread's 'Back to the issue')", async (record) => {
    const issue = await anIssue();
    const page = await open();
    await openIssue(page, issue.issue_id);
    await backTrip(page, record, {
      path: "Issue → Investigate → Back",
      state: issueState,
      go: (p) => p.click('[data-testid="issue-detail-investigate"]'),
      arrived: async (p) => {
        await p.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
        await p.waitForSelector('[data-testid="thread-origin-back"]', { timeout: 60_000 });
      },
      inApp: '[data-testid="thread-origin-back"]',
    });
  });

  await journey("GW-BACK-03", "Issue → driver-filtered population → Back → the unfiltered issue (in-app: clear the chart filter)", async (record) => {
    const issue = await anIssue();
    const driver = String(issue.evidence.breakdown[0].label);
    const page = await open();
    await openIssue(page, issue.issue_id);
    const unfiltered = await page.getAttribute('[data-testid="issue-grid"]', "data-total");
    record.unfiltered_rows = unfiltered;
    await backTrip(page, record, {
      path: "Issue → driver → Back",
      state: issueState,
      go: (p) => p.goto(`${UI}/issues/${issue.issue_id}?driver=${encodeURIComponent(driver)}`, { waitUntil: "domcontentloaded" }),
      arrived: (p) => p.waitForFunction((n) => { const t = document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total"); return t && t !== n && new URLSearchParams(location.search).get("driver"); }, unfiltered, { timeout: 120_000 }),
      inApp: '[data-testid="issue-detail-clear-drill"]',
    });
  });

  await journey("GW-BACK-04", "Issue → What-If on this population → Back → the exact issue; What-If's 'Back to the issue' returns too", async (record) => {
    const issue = await anIssue();
    const page = await open();
    await openIssue(page, issue.issue_id);
    const row = await backTrip(page, record, {
      path: "Issue → What-If → Back",
      state: issueState,
      go: (p) => p.click('[data-testid="issue-detail-whatif"]'),
      arrived: async (p) => {
        await p.waitForURL(/\/what-if\?/, { timeout: 120_000 });
        await p.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
      },
      inApp: '[data-testid="whatif-back"]',
    });
    record.cohort_url = row.destination;
  });

  await journey("GW-BACK-05", "Cockpit thread → What-If (investigation chip) → Back → the same thread, no new turn", async (record) => {
    const issue = await anIssue();
    const page = await open();
    record.thread_id = await threadFromIssue(page, issue.issue_id);
    const chip = page.locator('[data-testid="nbq-chip"][data-suggestion-type="freeze_cohort"], [data-testid="nbq-chip"][data-suggestion-type="run_whatif"]');
    if (!(await chip.count())) {
      const before = await turns(page);
      await page.locator('[data-testid="nbq-chip"]').first().click();
      await settle(page, before);
    }
    await chip.first().waitFor({ timeout: 90_000 });
    await backTrip(page, record, {
      path: "Thread → What-If → Back",
      state: threadState,
      go: (p) => p.locator('[data-testid="nbq-chip"][data-suggestion-type="freeze_cohort"], [data-testid="nbq-chip"][data-suggestion-type="run_whatif"]').first().click(),
      arrived: async (p) => {
        await p.waitForURL(/\/what-if\?/, { timeout: 120_000 });
        await p.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
      },
      inApp: '[data-testid="whatif-back"]',
    });
  });

  await journey("GW-BACK-06", "What-If (retail book, cohort, scenario applied) → Scenario Library → Back → the same What-If state, no re-bind and no new run", async (record) => {
    const cohort = (await post("/cohorts", { domain: "retail", name: "BACK-06 credit cards", filters: [{ column: "product", op: "in", values: ["Credit Card"] }] })).body;
    const tpl = (await api("/scenarios?domain=retail&q=RET-01")).body.scenarios[0];
    record.cohort_id = cohort.object_id;
    const page = await open();
    await page.goto(`${UI}/what-if?cohort=${cohort.object_id}&scenario=${tpl.object_id}`, { waitUntil: "domcontentloaded" });
    await waitWhatIfObjects(page, { cohort: cohort.object_id, scenario: tpl.object_id });
    await page.waitForSelector('[data-testid="whatif-preview"]', { timeout: 120_000 });
    await page.waitForFunction(() => new URLSearchParams(location.search).get("domain") === "retail", null, { timeout: 60_000 });
    await backTrip(page, record, {
      path: "What-If → Library → Back",
      state: whatifState,
      go: (p) => p.click('[data-testid="whatif-library"]'),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-count"]', { timeout: 120_000 }),
      inApp: '[data-testid="scenario-library-back"]',
    });
  });

  await journey("GW-BACK-07", "Scenario Library (search + owner + severity) → scenario detail → Back → the same filtered library", async (record) => {
    const page = await open();
    await openLibrary(page);
    await page.fill('[data-testid="scenario-search"]', "PD");
    await page.press('[data-testid="scenario-search"]', "Enter");
    await page.click('[data-testid="scenario-owner-template"]');
    await page.selectOption('[data-testid="scenario-severity"]', "moderate");
    await page.waitForFunction(() => /q=PD/.test(location.search) && /owner=template/.test(location.search) && /severity=moderate/.test(location.search), null, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="scenario-card"]', { timeout: 60_000 });
    await backTrip(page, record, {
      path: "Library → detail → Back",
      state: libraryState,
      go: (p) => p.locator('[data-testid="scenario-open"]').first().click(),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 }),
      inApp: '[data-testid="scenario-back"]',
    });
  });

  await journey("GW-BACK-08", "Scenario detail → Clone → Back → the source scenario; the clone's 'Discard this copy' is the Cancel; Library → New → Cancel writes nothing", async (record) => {
    const tpl = (await api("/scenarios?domain=corporate&q=CORP-02")).body.scenarios[0];
    const page = await open();
    await page.goto(`${UI}/scenarios/${tpl.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 });
    let copy = "";
    await backTrip(page, record, {
      path: "Detail → Clone → Back",
      state: detailState,
      go: (p) => p.click('[data-testid="scenario-action-clone"]'),
      arrived: async (p) => {
        await p.waitForFunction((id) => { const d = document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id"); return d && d !== id; }, tpl.object_id, { timeout: 120_000 });
        copy = await p.getAttribute('[data-testid="scenario-detail"]', "data-object-id");
      },
      inApp: '[data-testid="scenario-action-discard"]',
      inAppWrites: /\/scenarios\/scn-[0-9a-f]+\/retire$/,
    });
    record.copy = copy;
    const discarded = (await api(`/scenarios/${copy}`)).body.scenario;
    assert.equal(discarded.status, "ARCHIVED", "Discard retired the copy");
    // Library → New scenario → Cancel.
    await openLibrary(page);
    await backTrip(page, record, {
      path: "Library → Builder → Cancel",
      state: libraryState,
      go: (p) => p.click('[data-testid="scenario-new"]'),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-builder"]', { timeout: 120_000 }),
      inApp: '[data-testid="builder-cancel"]',
    });
  });

  await journey("GW-BACK-09", "Scenario Library: select two scenarios → Combine preview → Back keeps the selection; the saved combination's Back returns to the library", async (record) => {
    const page = await open();
    await page.goto(`${UI}/scenarios?domain=corporate&owner=template`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="scenario-card"]', { timeout: 120_000 });
    await page.evaluate(() => sessionStorage.removeItem("gw.scenario-library.selection"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="scenario-card"]', { timeout: 120_000 });
    const cards = page.locator('[data-testid="scenario-card"]');
    await cards.nth(0).locator('[data-testid="scenario-select"]').check();
    await cards.nth(1).locator('[data-testid="scenario-select"]').check();
    await page.waitForSelector('[data-testid="scenario-selection"]', { timeout: 30_000 });
    const sel = () => ({ selection: document.querySelector('[data-testid="scenario-selection"]')?.textContent?.split("selected:")[1]?.split("Combine")[0]?.trim() || "", owner: document.querySelector('[data-testid="scenario-owner"]')?.getAttribute("data-value") ?? "" });
    record.selection = await page.evaluate(sel);
    await backTrip(page, record, {
      path: "Library selection → detail → Back (selection kept)",
      state: sel,
      go: (p) => p.locator('[data-testid="scenario-open"]').first().click(),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 }),
      inApp: '[data-testid="scenario-back"]',
    });
    await page.click('[data-testid="scenario-combine"]');
    await page.waitForSelector('[data-testid="scenario-combine-panel"]', { timeout: 120_000 });
    record.combine_preview = await page.getAttribute('[data-testid="scenario-combine-preview"]', "data-readiness").catch(() => "");
  });

  await journey("GW-BACK-10", "What-If result (method tab) → Scenario detail → Back → the same result on the same method", async (record) => {
    const results = [];
    for (const r of (await api("/whatif/results")).body.results) {
      const o = (await api(`/objects/${r.object_id}`)).body;
      if (o.body.entry !== "cockpit") results.push({ ...r, ran: o.body.methods.ran });
    }
    assert.ok(results.length, "a What-If result exists");
    const res = results.find((r) => r.ran.length >= 2) ?? results[0];
    record.result_id = res.object_id;
    const page = await open();
    await page.goto(`${UI}/what-if/result/${res.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 120_000 });
    const methods = await page.$$eval('[data-testid^="whatif-result-method-"]', (b) => b.map((x) => x.getAttribute("data-testid")));
    if (methods.length > 1) {
      await page.click(`[data-testid="${methods.at(-1)}"]`);
      await page.waitForFunction(() => new URLSearchParams(location.search).get("method"), null, { timeout: 30_000 });
    }
    await backTrip(page, record, {
      path: "Result → Scenario → Back",
      state: resultState,
      go: (p) => p.click('[data-testid="whatif-result-open-scenario"]'),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 }),
      inApp: '[data-testid="scenario-back"]',
    });
  });

  await journey("GW-BACK-11", "What-If result → Share → Sent messages → Back → the same result", async (record) => {
    const res = (await api("/whatif/results")).body.results[0];
    const page = await open();
    await page.goto(`${UI}/what-if/result/${res.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 120_000 });
    await page.click('[data-testid="whatif-result-share-open"]');
    await page.fill('[data-testid="whatif-result-share-to"]', "colleague");
    await page.click('[data-testid="whatif-result-share-send"]');
    await page.waitForSelector('[data-testid="whatif-result-share-sent"]', { timeout: 60_000 });
    await backTrip(page, record, {
      path: "Result → share → Messages → Back",
      state: resultState,
      go: (p) => p.click('[data-testid="whatif-result-share-sent"]'),
      arrived: (p) => p.waitForSelector('[data-testid="messages-center"]', { timeout: 120_000 }),
      inApp: '[data-testid="messages-back"]',
    });
  });

  await journey("GW-BACK-12", "Messages (a shared scenario open) → the scenario → Back → Messages with the same message open", async (record) => {
    const page = await open();
    await openMessage(page, "scenario");
    await page.waitForFunction(() => new URLSearchParams(location.search).get("m"), null, { timeout: 30_000 });
    await backTrip(page, record, {
      path: "Messages → shared scenario → Back",
      state: messagesState,
      go: (p) => p.click('[data-testid="message-action-open"]'),
      arrived: (p) => p.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 }),
      inApp: '[data-testid="scenario-back"]',
    });
  });

  await journey("GW-BACK-13", "Messages (a shared Lens open) → the Lens → Back → Messages", async (record) => {
    const lens = (await api("/lenses")).body.lenses.find((l) => l.lens_id === "lens-05") ?? (await api("/lenses")).body.lenses[0];
    const shared = await post("/messages", { object_id: lens.object_id, to: ["colleague"], message: "BACK-13" });
    assert.ok(shared.status < 300, `the Lens is shared (${shared.status})`);
    const page = await open();
    await page.goto(`${UI}/messages?box=sent`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="message-item"][data-kind="lens"]', { timeout: 120_000 });
    await page.locator('[data-testid="message-item"][data-kind="lens"]').first().click();
    await page.waitForSelector('[data-testid="message-view"][data-accessible="true"]', { timeout: 60_000 });
    await backTrip(page, record, {
      path: "Messages → shared Lens → Back",
      state: messagesState,
      go: (p) => p.click('[data-testid="message-action-open"]'),
      arrived: (p) => p.waitForSelector('[data-testid="lens-view"]', { timeout: 120_000 }),
      inApp: '[data-testid="lens-back"]',
    });
  });

  await journey("GW-BACK-14", "Lenses (filtered) → a Lens → Back → the same filtered library", async (record) => {
    const page = await open();
    await page.goto(`${UI}/lenses`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="lens-card"]', { timeout: 120_000 });
    await page.fill('[data-testid="lens-search"]', "credit");
    await page.waitForFunction(() => /q=credit/.test(location.search), null, { timeout: 30_000 });
    await backTrip(page, record, {
      path: "Lenses → Lens → Back",
      state: lensLibraryState,
      go: (p) => p.locator('[data-testid="lens-card"]').first().click(),
      arrived: (p) => p.waitForSelector('[data-testid="lens-view"]', { timeout: 120_000 }),
      inApp: '[data-testid="lens-back"]',
    });
  });

  const lensWithSelection = async (page) => {
    const sel = { domain: "corporate", filters: [{ column: "sector", op: "in", values: ["Construction", "Real Estate"] }], label: "sector ∈ Construction, Real Estate" };
    const cross = [{ column: "stage", op: "in", values: [2], domain: "corporate" }];
    await page.goto(`${UI}/lenses/lens-02?x=${encodeURIComponent(JSON.stringify(cross))}&sel=${encodeURIComponent(JSON.stringify(sel))}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="lens-view"]', { timeout: 120_000 });
    await page.waitForSelector('[data-testid="lens-selection"]', { timeout: 60_000 });
  };

  await journey("GW-BACK-15", "Lens (cross-filter + selection) → underlying metric definition → Back → the same Lens selections", async (record) => {
    const page = await open();
    await lensWithSelection(page);
    await backTrip(page, record, {
      path: "Lens → underlying data → Back",
      state: lensState,
      go: (p) => p.locator('[data-testid="lens-kpi"]').first().click(),
      arrived: (p) => p.waitForSelector('[data-testid="metric-catalogue"]', { timeout: 120_000 }),
      inApp: '[data-testid="metrics-back"]',
    });
  });

  await journey("GW-BACK-16", "Lens selection → Investigate in Cockpit → Back → the same Lens context; Back does not freeze the selection twice", async (record) => {
    const page = await open();
    await lensWithSelection(page);
    await backTrip(page, record, {
      path: "Lens → Investigate → Back",
      state: lensState,
      go: (p) => p.click('[data-testid="lens-selection-investigate"]'),
      arrived: (p) => p.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 120_000 }),
      inApp: '[data-testid="thread-origin-back"]',
    });
  });

  await journey("GW-BACK-17", "Lens selection → What-If → Back → the same Lens context and cohort", async (record) => {
    const page = await open();
    await lensWithSelection(page);
    await backTrip(page, record, {
      path: "Lens → What-If → Back",
      state: lensState,
      go: (p) => p.click('[data-testid="lens-selection-whatif"]'),
      arrived: async (p) => {
        await p.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 120_000 });
        await p.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
      },
      inApp: '[data-testid="whatif-back"]',
    });
  });

  const monitoringFiltered = async (page) => {
    await page.goto(`${UI}/monitoring?view=all`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="monitoring-list"]')?.getAttribute("data-count") || 0) > 0, null, { timeout: 180_000 });
    await page.selectOption('[data-testid="monitoring-severity"]', "high");
    await page.waitForFunction(() => /severity=high/.test(location.search), null, { timeout: 30_000 });
    await page.waitForSelector('[data-testid="monitoring-alert"][data-type="breach"]', { timeout: 60_000 });
  };

  await journey("GW-BACK-18", "Monitoring Centre (view + severity) → a breach → Back → the same filtered list, alert closed", async (record) => {
    const page = await open();
    await monitoringFiltered(page);
    await backTrip(page, record, {
      path: "Monitoring → breach → Back",
      state: monitoringState,
      go: (p) => p.locator('[data-testid="monitoring-alert"][data-type="breach"]').first().click(),
      arrived: (p) => p.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 }),
    });
  });

  await journey("GW-BACK-19", "Breach → Open Lens at the trigger → Back → the breach (filters kept)", async (record) => {
    const page = await open();
    await monitoringFiltered(page);
    await page.locator('[data-testid="monitoring-alert"][data-type="breach"]').first().click();
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
    await backTrip(page, record, {
      path: "Breach → Lens → Back",
      state: monitoringState,
      go: (p) => p.click('[data-testid="alert-open-lens"]'),
      arrived: (p) => p.waitForSelector('[data-testid="lens-alert-banner"]', { timeout: 120_000 }),
      inApp: '[data-testid="lens-back"]',
    });
  });

  await journey("GW-BACK-20", "Breach → Investigate in Cockpit → Back → the breach (filters kept)", async (record) => {
    const page = await open();
    await monitoringFiltered(page);
    await page.locator('[data-testid="monitoring-alert"][data-type="breach"]').first().click();
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
    await backTrip(page, record, {
      path: "Breach → Cockpit → Back",
      state: monitoringState,
      go: (p) => p.click('[data-testid="alert-investigate"]'),
      arrived: async (p) => {
        await p.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 120_000 });
        await p.waitForSelector('[data-testid="thread-origin-back"]', { timeout: 120_000 });
      },
      inApp: '[data-testid="thread-origin-back"]',
    });
  });

  const exchangeRun = async (page, record) => {
    await askFromHome(page, record, "What is the total reported ECL of the corporate book?");
    const runId = await latestRun(record.thread_id);
    assert.ok(runId, "a recorded run");
    record.run_id = runId;
    return runId;
  };

  await journey("GW-BACK-21", "Trace (governance record) → LLM Exchange → Back → the same Trace; the exchange's Back link returns to it", async (record) => {
    const page = await open();
    const runId = await exchangeRun(page, record);
    await page.goto(`${UI}/cockpit/trace/${runId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="trace-llm-exchange-link"]', { timeout: 120_000 });
    await backTrip(page, record, {
      path: "Trace → LLM Exchange call → Back",
      state: () => ({ path: location.pathname, link: Boolean(document.querySelector('[data-testid="trace-llm-exchange-link"]')) }),
      go: (p) => p.click('[data-testid="trace-llm-exchange-link"]'),
      arrived: (p) => p.waitForSelector('[data-testid="llm-call-1"]', { timeout: 120_000 }),
      inApp: '[data-testid="llm-exchange-back"]',
    });
  });

  await journey("GW-BACK-22", "LLM Exchange: open a call's request/response stage → Back → the call list as it was", async (record) => {
    const page = await open();
    const runId = await exchangeRun(page, record);
    await page.goto(`${UI}/trace/llm-exchange/${runId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="llm-call-1"]', { timeout: 120_000 });
    const last = await page.$$eval('[data-testid^="llm-call-"]', (a) => a.at(-1).getAttribute("data-testid"));
    await backTrip(page, record, {
      path: "Trace → request/response view → Back",
      state: exchangeState,
      go: async (p) => {
        await p.locator(`[data-testid="${last}"] header button`).first().click();
        await p.waitForFunction(() => new URLSearchParams(location.search).get("call"), null, { timeout: 30_000 });
      },
      arrived: (p) => p.waitForFunction(() => new URLSearchParams(location.search).get("call"), null, { timeout: 60_000 }),
    });
  });
}

// =========================================================================
// VALIDATION — GOLD cross-module journeys. Each ends on an assertion about
// the business state the journey produced (objects, hashes, lineage, figures),
// never only on a page being visible.
// =========================================================================

async function runHere(page, methods = ["delta"]) {
  await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
  await page.click('[data-testid="whatif-run-start"]');
  await waitRunState(page, "SCENARIO_PREVIEW");
  await page.click('[data-testid="whatif-run-confirm"]');
  await waitRunState(page, "METHOD_SELECTION");
  for (const m of methods) await page.check(`[data-testid="whatif-method-pick-${m}"]`);
  await page.click('[data-testid="whatif-run-execute"]');
  await waitRunState(page, "EXECUTED", 240_000);
  await resultRendered(page);
  const runId = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
  const run = (await api(`/whatif/runs/${runId}`)).body;
  return { runId, run, result: (await api(`/objects/${run.body.result_id}`)).body };
}

function reconciles(result) {
  const d = result.body.decomposition.delta;
  return d.scopes.selected.reconciles === true && d.scopes.total.reconciles === true && d.cross_scope.reconciles === true;
}

async function chipToWhatIf(page) {
  const stress = page.locator('[data-testid="nbq-chip"][data-suggestion-type="run_whatif"]');
  if (!(await stress.count())) {
    const before = await turns(page);
    await page.locator('[data-testid="nbq-chip"][data-suggestion-type="explain_driver"], [data-testid="nbq-chip"]').first().click();
    await settle(page, before);
  }
  await stress.first().waitFor({ timeout: 90_000 });
  await stress.first().click();
  await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 120_000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
  return page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id");
}

async function goldJourneys() {
  await journey("GW-GOLD-01", "Guided Corporate: issue → driver → root cause → frozen cohort → suggested What-If → confirm → method → execute → selected + total bridges → share → recipient's message → Back to Messages", async (record) => {
    const page = await open();
    await openHome(page, "corporate");
    const card = page.locator('[data-testid="issue-card"]').filter({ has: page.locator('[data-testid="issue-driver"]') }).first();
    record.issue_id = await card.getAttribute("data-issue-id");
    await card.locator('[data-testid="issue-driver"]').click();
    await page.waitForURL(/\/issues\/.+\?driver=/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="issue-detail"]', { timeout: 120_000 });
    await page.click('[data-testid="issue-detail-investigate"]');
    await page.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
    record.thread_id = await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
    const inv = (await api(`/investigations/by-thread/${record.thread_id}`)).body;
    record.cohort_id = await chipToWhatIf(page);
    assert.equal(record.cohort_id, inv.cohort_id, "What-If opens on the investigation's frozen cohort");
    const scenario = (await api("/scenarios?domain=corporate&q=CORP-01")).body.scenarios[0];
    await page.goto(`${UI}/what-if?cohort=${record.cohort_id}&scenario=${scenario.object_id}`, { waitUntil: "domcontentloaded" });
    const { run, result } = await runHere(page, ["delta"]);
    record.result_id = result.object_id;
    assert.ok(reconciles(result), "selected, total and cross-scope identities reconcile");
    assert.equal(result.body.cohort.membership_hash, (await api(`/objects/${record.cohort_id}`)).body.body.membership_hash, "executed on exactly the frozen population");
    assert.equal(run.status, "EXECUTED");
    await page.goto(`${UI}/what-if/result/${result.object_id}`, { waitUntil: "domcontentloaded" });
    await resultRendered(page);
    await page.click('[data-testid="whatif-result-share-open"]');
    await page.fill('[data-testid="whatif-result-share-to"]', "colleague");
    await page.click('[data-testid="whatif-result-share-send"]');
    await page.waitForSelector('[data-testid="whatif-result-share-sent"]', { timeout: 60_000 });
    const sent = (await api("/messages?box=sent")).body.items.find((m) => m.object_id === result.object_id);
    assert.ok(sent && sent.to_id === "colleague", "the recipient's message exists, addressed to them");
    record.share_id = sent.share_id;
    await page.click('[data-testid="whatif-result-share-sent"]');
    await page.waitForSelector('[data-testid="messages-center"]', { timeout: 120_000 });
    await page.click(`[data-testid="message-item"][data-share-id="${sent.share_id}"]`);
    await page.waitForSelector('[data-testid="message-view"][data-accessible="true"]', { timeout: 60_000 });
    await page.click('[data-testid="message-action-open"]');
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 120_000 });
    await page.goBack();
    await page.waitForFunction((id) => document.querySelector('[data-testid="message-view"]')?.getAttribute("data-share-id") === id, sent.share_id, { timeout: 60_000 });
    await shot(page, record, "back-to-messages");
  });

  await journey("GW-GOLD-02", "Guided Retail: issue → frozen cohort → scenario → Retail ML requested → explicit UNAVAILABLE, nothing substituted → Delta → decomposition → reopen shows the same executed run", async (record) => {
    const page = await open();
    await openHome(page, "retail");
    const card = page.locator('[data-testid="issue-card"]').first();
    record.issue_id = await card.getAttribute("data-issue-id");
    const issue = (await api(`/issues/${record.issue_id}`)).body;
    await card.locator('[data-testid="issue-whatif"]').click();
    await page.waitForURL(/\/what-if\?cohort=coh-/, { timeout: 120_000 });
    const cohortId = new URL(page.url()).searchParams.get("cohort");
    const cohort = (await api(`/objects/${cohortId}`)).body;
    assert.equal(cohort.body.counts.entities, issue.cohort.entities, "the exact issue population");
    const tpl = (await api("/scenarios?domain=retail&q=RET-01")).body.scenarios[0];
    await page.goto(`${UI}/what-if?cohort=${cohortId}&scenario=${tpl.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="whatif-run-start"]', { timeout: 120_000 });
    await page.click('[data-testid="whatif-run-start"]');
    await waitRunState(page, "SCENARIO_PREVIEW");
    await page.click('[data-testid="whatif-run-confirm"]');
    await waitRunState(page, "METHOD_SELECTION");
    assert.equal(await page.getAttribute('[data-testid="whatif-method-ml"]', "data-status"), "UNAVAILABLE");
    await page.check('[data-testid="whatif-method-pick-ml"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "METHOD_UNAVAILABLE");
    assert.match(await page.textContent('[data-testid="whatif-method-gate"]'), /nothing is substituted/);
    assert.equal(await page.$('[data-testid="whatif-result"]'), null, "no result from an unavailable method");
    await page.uncheck('[data-testid="whatif-method-pick-ml"]');
    await page.check('[data-testid="whatif-method-pick-delta"]');
    await page.click('[data-testid="whatif-run-execute"]');
    await waitRunState(page, "EXECUTED", 240_000);
    await resultRendered(page);
    const runId = await page.getAttribute('[data-testid="whatif-run"]', "data-run-id");
    const run = (await api(`/whatif/runs/${runId}`)).body;
    const result = (await api(`/objects/${run.body.result_id}`)).body;
    assert.deepEqual(result.body.methods.ran, ["delta"]);
    assert.ok(Object.keys(result.body.methods.unavailable ?? {}).includes("ml"), "the result records ML as unavailable");
    assert.ok(reconciles(result));
    // Reopen: the URL carries the run; a fresh load shows the same executed run, no re-execution.
    await page.waitForFunction((id) => new URLSearchParams(location.search).get("run") === id, runId, { timeout: 60_000 });
    const marks = page.calls.length;
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitRunState(page, "EXECUTED", 120_000);
    await resultRendered(page);
    assert.equal(await page.getAttribute('[data-testid="whatif-run"]', "data-run-id"), runId);
    assert.deepEqual(page.calls.slice(marks).filter((c) => WRITE_ON_BACK.test(c)), [], "reopening wrote nothing and ran nothing");
    record.result_id = result.object_id;
  });

  await journey("GW-GOLD-03", "Scenario composition: three scenarios → combine → resolve every overlap → bind a cohort → run Delta and a second method → lineage names all three; the sources are unchanged", async (record) => {
    const page = await open();
    const ids = [];
    for (const t of ["CORP-01", "CORP-05", "CORP-06"]) ids.push((await api(`/scenarios?domain=corporate&q=${t}`)).body.scenarios[0].object_id);
    const before = await Promise.all(ids.map(async (id) => (await api(`/objects/${id}/history`)).body));
    await page.goto(`${UI}/scenarios?domain=corporate&owner=template`, { waitUntil: "domcontentloaded" });
    for (const id of ids) {
      await page.waitForSelector(`[data-object-id="${id}"] [data-testid="scenario-select"]`, { timeout: 120_000 });
      await page.check(`[data-object-id="${id}"] [data-testid="scenario-select"]`);
    }
    await page.click('[data-testid="scenario-combine"]');
    await waitPreview(page, "scenario-combine-preview");
    const selects = page.locator('[data-testid="overlap-policy-select"]');
    const n = await selects.count();
    record.overlaps = n;
    for (let i = 0; i < n; i += 1) {
      const options = await selects.nth(i).locator("option").evaluateAll((os) => os.map((o) => o.value).filter(Boolean));
      await selects.nth(i).selectOption(options.includes("compound") ? "compound" : options[0]);
    }
    if (n) await page.click('[data-testid="overlap-resolve"]');
    else await page.click('[data-testid="scenario-combine-save"]');
    await page.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 });
    const c = await page.getAttribute('[data-testid="scenario-detail"]', "data-object-id");
    record.combined = c;
    assert.notEqual(await waitPreview(page), "BLOCKED", "every overlap carries a chosen policy");
    const cohort = (await post("/cohorts", { domain: "corporate", name: "GOLD-03 Construction", filters: [{ column: "sector", op: "in", values: ["Construction"] }] })).body;
    await page.click('[data-testid="scenario-action-bind"]');
    await page.click(`[data-testid="scenario-bind-choose"][data-cohort-id="${cohort.object_id}"]`);
    await page.waitForFunction((id) => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-version") !== "1" || document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id") !== id, c, { timeout: 120_000 });
    const bound = (await api(`/scenarios/${c}`)).body.scenario;
    assert.equal(bound.body.scope.cohort_id, cohort.object_id, "the combination is bound to the cohort");
    const ctx = (await api("/whatif/context?domain=corporate")).body;
    const second = ctx.methods.ml.status === "AVAILABLE" ? "ml" : "";
    record.second_method = second || "none available (ML not ready in this runtime)";
    await page.goto(`${UI}/what-if?scenario=${c}`, { waitUntil: "domcontentloaded" });
    const { result } = await runHere(page, second ? ["delta", second] : ["delta"]);
    record.result_id = result.object_id;
    assert.ok(reconciles(result));
    if (second) assert.deepEqual([...result.body.methods.ran].sort(), ["delta", second].sort(), "both methods ran on the same contract");
    assert.equal(result.body.cohort.membership_hash, cohort.body.membership_hash);
    await page.goto(`${UI}/scenarios/${c}`, { waitUntil: "domcontentloaded" });
    const lineage = await page.textContent('[data-testid="scenario-lineage"]');
    for (const id of ids) {
      const name = (await api(`/objects/${id}`)).body.body.name;
      assert.ok(lineage.includes(name), `lineage names ${name}`);
    }
    const after = await Promise.all(ids.map(async (id) => (await api(`/objects/${id}/history`)).body));
    assert.deepEqual(after, before, "the three sources are unchanged");
  });

  await journey("GW-GOLD-04", "Lens to decision: CRO/portfolio Lens → box-select a deteriorating segment → the rows → cohort → Investigate → root cause → What-If → executed result on that exact cohort", async (record) => {
    const page = await open();
    await openLens(page, "lens-02");
    const chart = '[data-testid="lens-visual-v06"]';
    await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 120_000 });
    await page.locator(chart).scrollIntoViewIfNeeded();
    const b0 = await page.locator(`${chart} g.point path`).nth(0).boundingBox();
    const b1 = await page.locator(`${chart} g.point path`).nth(1).boundingBox();
    const plot = await page.locator(`${chart} rect.nsewdrag`).boundingBox();
    await page.mouse.move(Math.max(b0.x - 4, plot.x + 2), plot.y + 3);
    await page.mouse.down();
    await page.mouse.move(b1.x + b1.width + 4, b0.y + b0.height - 2, { steps: 12 });
    await page.mouse.up();
    await page.waitForSelector('[data-testid="lens-selection"]', { timeout: 60_000 });
    record.selection = (await page.textContent('[data-testid="lens-selection"]')).split("Save")[0].trim();
    await page.click('[data-testid="lens-selection-save"]');
    await page.waitForFunction(() => new URLSearchParams(location.search).get("cohort"), null, { timeout: 60_000 });
    const cohortId = new URL(page.url()).searchParams.get("cohort");
    const cohort = (await api(`/objects/${cohortId}`)).body;
    const rows = await gridApi(cohort.body.filters, { domain: cohort.domain_id });
    assert.equal(rows.total, cohort.body.counts.entities, "the frozen cohort is exactly the rows the selection names");
    await page.click('[data-testid="lens-selection-investigate"]');
    await page.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
    record.thread_id = await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
    const whatifCohort = await chipToWhatIf(page);
    const frozen = (await api(`/objects/${whatifCohort}`)).body;
    assert.equal(frozen.body.membership_hash, cohort.body.membership_hash, "the investigation's What-If is on the Lens population");
    const scenario = (await api("/scenarios?domain=corporate&q=CORP-01")).body.scenarios[0];
    await page.goto(`${UI}/what-if?cohort=${whatifCohort}&scenario=${scenario.object_id}`, { waitUntil: "domcontentloaded" });
    const { result } = await runHere(page, ["delta"]);
    record.result_id = result.object_id;
    assert.ok(reconciles(result));
    assert.equal(result.body.cohort.membership_hash, cohort.body.membership_hash, "the decision is on the Lens's selected population");
  });

  await journey("GW-GOLD-05", "Monitoring loop: breach → the Lens at the trigger → acknowledge with a note → investigate → What-If → return: the breach is ACKNOWLEDGED with its note and history", async (record) => {
    const page = await open();
    const live = (await api("/monitoring?view=all")).body.alerts.filter((a) => a.type !== "change" && !a.demo_historical && a.alert_type !== "change");
    let alert = live.find((a) => ["NEW", "ACTIVE", "WORSENING"].includes(a.state)) ?? live[0];
    if (!["NEW", "ACTIVE", "WORSENING"].includes(alert.state)) await post(`/monitoring/alerts/${alert.alert_id}/reopen`, { note: "GOLD-05 rerun" });
    record.alert_id = alert.alert_id;
    await page.goto(`${UI}/monitoring?view=all&alert=${alert.alert_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
    await page.click('[data-testid="alert-open-lens"]');
    await page.waitForSelector('[data-testid="lens-alert-banner"]', { timeout: 120_000 });
    await page.click('[data-testid="lens-back"]');
    await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
    const note = `GOLD-05 ${Date.now()}`;
    await page.fill('[data-testid="alert-note"]', note);
    await page.click('[data-testid="alert-acknowledge"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="alert-panel"]')?.getAttribute("data-state") === "ACKNOWLEDGED", null, { timeout: 60_000 });
    const breach = (await api(`/monitoring/alerts/${alert.alert_id}`)).body;
    if (breach.alert.body.alert_type === "breach") {
      await page.click('[data-testid="alert-investigate"]');
      await page.waitForSelector('[data-testid="thread-origin-back"]', { timeout: 120_000 });
      await page.click('[data-testid="thread-origin-back"]');
      await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
      await page.click('[data-testid="alert-whatif"]');
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
      await page.click('[data-testid="whatif-back"]');
      await page.waitForSelector('[data-testid="alert-panel"]', { timeout: 120_000 });
    }
    const after = (await api(`/monitoring/alerts/${alert.alert_id}`)).body;
    record.state = after.alert.status;
    assert.equal(after.alert.status, "ACKNOWLEDGED", "the breach state persists across the loop");
    assert.ok(after.events.some((e) => e.note === note), "the acknowledgement note is in the history");
    assert.equal(await page.getAttribute('[data-testid="alert-panel"]', "data-state"), "ACKNOWLEDGED");
  });

  await journey("GW-GOLD-06", "Early Warning: population → save cohort → export (only its rows) → investigate → What-If on the SAME cohort object → counts reconcile", async (record) => {
    const page = await open();
    await page.goto(`${UI}/early-warning`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="ew-band-critical"]', { timeout: 120_000 });
    await page.click('[data-testid="ew-save-cohort"]');
    await page.waitForSelector('[data-testid="ew-note"]', { timeout: 60_000 });
    const cohortId = /\b(coh-[0-9a-f]+)/.exec(await page.textContent('[data-testid="ew-note"]'))[1];
    const cohort = (await api(`/objects/${cohortId}`)).body;
    record.cohort_id = cohortId;
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click('[data-testid="ew-export"]')]);
    const csvText = fs.readFileSync(await download.path(), "utf8");
    const dataRows = csvText.split("\n").filter((l) => l && !l.startsWith("#")).length - 1;
    record.export_rows = dataRows;
    assert.equal(dataRows, cohort.body.counts.entities, "the export is the cohort's rows, not the book");
    assert.match(await page.textContent('[data-testid="ew-note"]'), new RegExp(cohortId), "export reused the saved cohort");
    await page.click('[data-testid="ew-whatif"]');
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
    assert.equal(await page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id"), cohortId, "What-If opens on the same cohort object (no second freeze)");
    await page.waitForFunction((n) => Number(document.querySelector('[data-testid="whatif-strip-cohort"]')?.textContent?.match(/([\d,]+) exposures/)?.[1]?.replace(/,/g, "") ?? -1) === n, cohort.body.counts.entities, { timeout: 60_000 });
    await page.click('[data-testid="whatif-back"]');
    await page.waitForSelector('[data-testid="ew-investigate"]', { timeout: 120_000 });
    await page.click('[data-testid="ew-investigate"]');
    await page.waitForSelector('[data-testid="cockpit-v4-thread"]', { timeout: 120_000 });
    const thread = await page.getAttribute('[data-testid="cockpit-v4-thread"]', "data-thread-id");
    const inv = (await api(`/investigations/by-thread/${thread}`)).body;
    const invCohort = (await api(`/objects/${inv.cohort_id}`)).body;
    assert.equal(invCohort.body.membership_hash, cohort.body.membership_hash, "the investigation reads the same population");
  });

  await journey("GW-GOLD-07", "Sharing: an unexecuted scenario is shared (reference + version); a received shared definition is duplicated, bound to MY cohort and executed; the shared source is unchanged", async (record) => {
    const page = await open();
    const made = await build(page, record, { name: `GOLD-07 share ${Date.now()}`, components: [{ kind: "parameter", field: "pd_pit_12m", operation: "relative_pct", value: "10" }] });
    await page.click('[data-testid="scenario-action-share"]');
    await page.fill('[data-testid="scenario-share-input"]', "colleague");
    await page.click('[data-testid="scenario-share-submit"]');
    await page.waitForSelector('[data-testid="scenario-note"]', { timeout: 60_000 });
    const sent = (await api("/messages?box=sent")).body.items.find((m) => m.object_id === made.id);
    assert.ok(sent && sent.to_id === "colleague", "shared by reference to the recipient");
    assert.equal((await api(`/scenarios/${made.id}/results`)).body.results.length, 0, "sharing executed nothing");
    // The received half: the seeded definition a colleague shared with this user.
    await openMessage(page, "scenario");
    const sourceId = await page.getAttribute('[data-testid="message-object"]', "data-object-id");
    const sourceBefore = (await api(`/objects/${sourceId}/history`)).body;
    await page.click('[data-testid="message-action-duplicate"]');
    await page.waitForSelector('[data-testid="message-note"]', { timeout: 60_000 });
    const copyId = /\b(scn-[0-9a-f]+)/.exec(await page.textContent('[data-testid="message-note"]'))?.[1];
    assert.ok(copyId && copyId !== sourceId, "a copy of my own");
    const mine = (await post("/cohorts", { domain: "corporate", name: "GOLD-07 mine", filters: [{ column: "sector", op: "in", values: ["Real Estate"] }] })).body;
    await page.goto(`${UI}/scenarios/${copyId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="scenario-detail"]', { timeout: 120_000 });
    await page.click('[data-testid="scenario-action-bind"]');
    await page.click(`[data-testid="scenario-bind-choose"][data-cohort-id="${mine.object_id}"]`);
    await page.waitForFunction(() => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-version") === "2", null, { timeout: 120_000 });
    await page.goto(`${UI}/what-if?scenario=${copyId}`, { waitUntil: "domcontentloaded" });
    const { result } = await runHere(page, ["delta"]);
    assert.equal(result.body.cohort.membership_hash, mine.body.membership_hash, "executed on MY cohort");
    assert.ok(reconciles(result));
    assert.deepEqual((await api(`/objects/${sourceId}/history`)).body, sourceBefore, "the shared source is unchanged");
    record.copy = copyId;
    record.result_id = result.object_id;
  });

  await journey("GW-GOLD-08", "Persistence: a cohort, a scenario, a Lens with a breach rule and a result reopen in a FRESH browser context with the same ids, versions and hashes; reopening makes no model call and no write", async (record) => {
    const cohort = (await post("/cohorts", { domain: "corporate", name: "GOLD-08", filters: [{ column: "sector", op: "in", values: ["Hotels"] }] })).body;
    const tpl = (await api("/scenarios?domain=corporate&q=CORP-02")).body.scenarios[0];
    const result = (await apiRun(tpl.object_id, `gold08-${Date.now()}`)).result;
    const lens = (await api("/lenses")).body.lenses.find((l) => l.lens_id === "lens-02");
    const ids = { cohort: cohort.object_id, scenario: tpl.object_id, result: result.object_id, lens: lens.object_id };
    const snap = {};
    for (const [k, id] of Object.entries(ids)) {
      const o = (await api(`/objects/${id}`)).body;
      snap[k] = [o.object_id, o.version, o.content_hash];
    }
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const calls = [];
    page.on("request", (r) => r.url().startsWith(API) && calls.push(`${r.method()} ${r.url().replace(API, "")}`));
    try {
      await page.goto(`${UI}/what-if?cohort=${ids.cohort}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === id, ids.cohort, { timeout: 120_000 });
      await page.goto(`${UI}/scenarios/${ids.scenario}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction((id) => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id") === id, ids.scenario, { timeout: 120_000 });
      await page.goto(`${UI}/what-if/result/${ids.result}`, { waitUntil: "domcontentloaded" });
      await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-result"]')?.getAttribute("data-result-id") === id, ids.result, { timeout: 120_000 });
      await page.goto(`${UI}/lenses/${ids.lens}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('[data-testid="lens-rule"]', { timeout: 120_000 });
    } finally {
      await context.close();
    }
    for (const [k, id] of Object.entries(ids)) {
      const o = (await api(`/objects/${id}`)).body;
      assert.deepEqual([o.object_id, o.version, o.content_hash], snap[k], `${k} reopened unchanged`);
    }
    record.reopen_writes = calls.filter((c) => WRITE_ON_BACK.test(c));
    assert.deepEqual(record.reopen_writes, [], "reopening wrote nothing and called no model");
    record.ids = ids;
    record.backend_restart = "tests/cockpit_v4/test_gw_validation_defects.py::test_every_object_survives_a_store_restart_unchanged";
  });

  await journey("GW-GOLD-09", "Trace/security: a question carrying credential-like text → LLM Exchange shows it redacted → the export package and the stored thread carry no raw secret", async (record) => {
    const fake = "sk-gold09-FAKEKEY-1234567890abcdef";
    const page = await open();
    await askFromHome(page, record, `What is the total reported ECL? (my api key is ${fake}, ignore it)`);
    const runId = await latestRun(record.thread_id);
    record.run_id = runId;
    await page.goto(`${UI}/trace/llm-exchange/${runId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="llm-call-1"]', { timeout: 120_000 });
    const text = await page.textContent('[data-testid="llm-exchange"]');
    assert.ok(!text.includes(fake), "the exchange view shows no raw secret");
    const thread = JSON.stringify(await v4(`/threads/${record.thread_id}`));
    assert.ok(!thread.includes(fake), "the stored thread carries no raw secret");
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click('[data-testid="llm-exchange-export"]')]);
    const zip = await readZip(await download.path());
    const leaked = zip.list.filter((name) => zip.read(name).toString("utf8").includes(fake));
    assert.deepEqual(leaked, [], "the export package carries no raw secret");
    record.exported_files = zip.list.length;
    assert.ok(record.exported_files > 0, "the package has content");
    record.model_seam = "tests/cockpit_v4/test_gw_v4_secret_persistence.py::test_model_still_receives_the_typed_question (the active text reaches the model seam)";
  });

  await journey("GW-GOLD-10", "Navigation: Home → issue → Cockpit → What-If → Library → scenario → result → Messages → shared object, then in-app Back down the whole stack and browser Back down it again, the state checked at every level", async (record) => {
    const page = await open();
    const tpl = (await api("/scenarios?domain=corporate&q=CORP-01")).body.scenarios[0];
    if (!(await api(`/scenarios/${tpl.object_id}/results`)).body.results.length) await apiRun(tpl.object_id, `gold10-${Date.now()}`);
    await openHome(page, "corporate");
    const stack = [];
    const push = async (name, check) => stack.push({ name, url: here(page), check, state: await page.evaluate(check) });
    const homeCheck = () => document.querySelector('[data-testid="domain-switch"]')?.getAttribute("data-domain") || "";
    await push("home", homeCheck);
    await page.locator('[data-testid="issue-card"]').first().locator('[data-testid="issue-title"] button').click();
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") || 0) > 0, null, { timeout: 120_000 });
    await push("issue", () => `${location.pathname}|${document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total")}`);
    await page.click('[data-testid="issue-detail-investigate"]');
    await page.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
    await settle(page, 0).catch(() => undefined);
    const chip = page.locator('[data-testid="nbq-chip"][data-suggestion-type="freeze_cohort"], [data-testid="nbq-chip"][data-suggestion-type="run_whatif"]');
    if (!(await chip.count())) {
      const before = await turns(page);
      await page.locator('[data-testid="nbq-chip"]').first().click();
      await settle(page, before);
    }
    await push("thread", () => document.querySelector('[data-testid="cockpit-v4-thread"]')?.getAttribute("data-thread-id") || "");
    await chip.first().click();
    await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
    await push("what-if", () => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") || "");
    await page.click('[data-testid="whatif-library"]');
    await page.waitForSelector('[data-testid="scenario-count"]', { timeout: 120_000 });
    await page.fill('[data-testid="scenario-search"]', "CORP-01");
    await page.press('[data-testid="scenario-search"]', "Enter");
    await page.waitForFunction(() => /q=CORP-01/.test(location.search) && document.querySelectorAll('[data-testid="scenario-card"]').length >= 1, null, { timeout: 60_000 });
    await push("library", () => `${document.querySelector('[data-testid="scenario-search"]')?.value}|${document.querySelector('[data-testid="scenario-domain"]')?.getAttribute("data-value")}`);
    await page.locator('[data-testid="scenario-open"]').first().click();
    await page.waitForSelector('[data-testid="scenario-result-link"]', { timeout: 120_000 });
    await push("scenario", () => document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id") || "");
    await page.locator('[data-testid="scenario-result-link"]').first().click();
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 120_000 });
    await push("result", () => document.querySelector('[data-testid="whatif-result"]')?.getAttribute("data-result-id") || "");
    await page.click('[data-testid="whatif-result-share-open"]');
    await page.fill('[data-testid="whatif-result-share-to"]', "colleague");
    await page.click('[data-testid="whatif-result-share-send"]');
    await page.waitForSelector('[data-testid="whatif-result-share-sent"]', { timeout: 60_000 });
    await page.click('[data-testid="whatif-result-share-sent"]');
    await page.waitForSelector('[data-testid="message-item"]', { timeout: 120_000 });
    await page.locator('[data-testid="message-item"]').first().click();
    await page.waitForSelector('[data-testid="message-view"][data-accessible="true"]', { timeout: 60_000 });
    await push("messages", () => document.querySelector('[data-testid="message-view"]')?.getAttribute("data-share-id") || "");
    await page.click('[data-testid="message-action-open"]');
    await page.waitForSelector('[data-testid="whatif-result"]', { timeout: 120_000 });
    record.stack = stack.map((s) => [s.name, s.url, s.state]);

    const backControl = {
      messages: '[data-testid="whatif-result-back"]',
      result: '[data-testid="messages-back"]',
      scenario: '[data-testid="whatif-result-back"]',
      library: '[data-testid="scenario-back"]',
      "what-if": '[data-testid="scenario-library-back"]',
      thread: '[data-testid="whatif-back"]',
      issue: '[data-testid="thread-origin-back"]',
      home: '[data-testid="issue-detail-back"]',
    };
    const levels = [...stack].reverse();
    record.in_app = [];
    for (const level of levels) {
      await page.click(backControl[level.name], { timeout: 60_000 });
      await page.waitForFunction(([src, want]) => JSON.stringify(new Function(`return (${src})()`)()) === want, [level.check.toString(), JSON.stringify(level.state)], { timeout: 60_000 });
      record.in_app.push(level.name);
    }
    // Browser Back down the same stack from its top.
    await page.goto(`${UI}${stack.at(-1).url}`, { waitUntil: "domcontentloaded" });
    record.browser = [];
    for (const level of levels) {
      for (let hops = 0; hops < 40; hops += 1) {
        const at = await page.evaluate(([src, want]) => { try { return JSON.stringify(new Function(`return (${src})()`)()) === want; } catch { return false; } }, [level.check.toString(), JSON.stringify(level.state)]);
        if (at && new URL(page.url()).pathname === new URL(`${UI}${level.url}`).pathname) break;
        if (hops === 39) throw new Error(`browser Back never reached ${level.name}`);
        await page.goBack();
        await page.waitForLoadState("domcontentloaded");
        await page.waitForFunction(([src]) => { try { return new Function(`return (${src})()`)() !== undefined; } catch { return false; } }, [level.check.toString()], { timeout: 60_000 }).catch(() => undefined);
      }
      await page.waitForFunction(([src, want]) => JSON.stringify(new Function(`return (${src})()`)()) === want, [level.check.toString(), JSON.stringify(level.state)], { timeout: 60_000 });
      record.browser.push(level.name);
    }
    assert.equal(record.in_app.length, stack.length);
    assert.equal(record.browser.length, stack.length);
  });
}

// =========================================================================
// VALIDATION — runtime Plotly audit (PLOTLY_AUDIT.csv): every Plotly chart on
// the guided pages, at a desktop and a phone width: rendered, labelled, inside
// the viewport, no page-level horizontal scroll, and the console clean.
// =========================================================================

async function plotlyAudit() {
  await journey("GW-VAL-PLOTLY", "Every Plotly chart on the guided pages renders, is labelled and fits the screen at 1440 px and at 390 px; no page scrolls sideways", async (record) => {
    const issue = await anIssue();
    const results = (await api("/whatif/results")).body.results;
    const pages = [
      ["issue", `/issues/${issue.issue_id}`],
      ["what-if", "/what-if?domain=corporate"],
      ["result", results.length ? `/what-if/result/${results[0].object_id}` : ""],
      ["lens-02", "/lenses/lens-02"],
      ["lens-05", "/lenses/lens-05"],
      ["lens-15", "/lenses/lens-15"],
      ["monitoring", "/monitoring?view=all"],
      ["metrics", "/metrics?m=M001"],
      ["early-warning", "/early-warning"],
      ["scenario", "/scenarios/scn-tpl-corp-01"],
    ].filter(([, u]) => u);
    record.plotly = [];
    for (const width of [1440, 390]) {
      const page = await open();
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      for (const [name, url] of pages) {
        const consoleBefore = page.consoleLog.length;
        await page.goto(`${UI}${url}`, { waitUntil: "domcontentloaded" });
        await page.waitForFunction(() => document.querySelectorAll('[role="img"][data-testid]').length > 0, null, { timeout: 180_000 }).catch(() => undefined);
        await page.waitForFunction(() => [...document.querySelectorAll('[role="img"][data-testid]')].every((c) => c.getAttribute("data-rendered") === "true" || c.closest("[hidden]")), null, { timeout: 180_000 }).catch(() => undefined);
        const charts = await page.evaluate(() => {
          const vw = document.documentElement.clientWidth;
          return [...document.querySelectorAll('[role="img"][data-testid]')].map((c) => {
            const r = c.getBoundingClientRect();
            return { testid: c.getAttribute("data-testid"), rendered: c.getAttribute("data-rendered") === "true", label: (c.getAttribute("aria-label") || "").slice(0, 80), width: Math.round(r.width), fits: r.left >= -1 && r.right <= vw + 1, plotly: Boolean(c.querySelector(".js-plotly-plot, .main-svg")) };
          });
        });
        const pageScroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        const errors = page.consoleLog.slice(consoleBefore).filter((l) => /^(error|pageerror)/.test(l));
        for (const c of charts) {
          const status = c.rendered && c.plotly && c.label && c.fits && pageScroll <= 1 && !errors.length ? "PASS" : "FAILED";
          record.plotly.push({ page: name, url, viewport: width, ...c, page_horizontal_scroll_px: pageScroll, console_errors: errors.length, status });
        }
        if (!charts.length) record.plotly.push({ page: name, url, viewport: width, testid: "(none)", rendered: false, label: "", width: 0, fits: true, plotly: false, page_horizontal_scroll_px: pageScroll, console_errors: errors.length, status: "NO_CHART" });
      }
      await page.close();
    }
    const failed = record.plotly.filter((r) => r.status === "FAILED");
    record.charts_audited = record.plotly.filter((r) => r.testid !== "(none)").length;
    assert.ok(record.charts_audited >= 30, `charts audited: ${record.charts_audited}`);
    assert.deepEqual(failed.map((f) => `${f.page}@${f.viewport}:${f.testid} rendered=${f.rendered} fits=${f.fits} scroll=${f.page_horizontal_scroll_px} errors=${f.console_errors}`), [], "every chart passes");
  });
}

async function main() {
  browser = await chromium.launch({ executablePath: CHROME });
  try {
    await p1Journeys();
    await p3Journeys();
    await p4Journeys();
    await p5Journeys();
    await p6Journeys();
    await p7Journeys();
    await p8Journeys();
    await p9Journeys();
    await p10Journeys();
    await p11Journeys();
    await p11bJourneys();
    await p12Journeys();
    await p13Journeys();
    await p16Journeys();
    await backJourneys();
    await goldJourneys();
    await plotlyAudit();
    for (const extra of globalThis.GW_EXTRA_JOURNEYS ?? []) await extra();
  } finally {
    await browser.close();
  }
  fs.mkdirSync(path.dirname(EVIDENCE), { recursive: true });
  let prior = [];
  if (ONLY && fs.existsSync(EVIDENCE)) {
    try {
      prior = JSON.parse(fs.readFileSync(EVIDENCE, "utf8")).journeys ?? [];
    } catch {
      prior = [];
    }
  }
  const merged = [...prior.filter((p) => !evidence.some((e) => e.journey === p.journey)), ...evidence].sort((a, b) =>
    a.journey.localeCompare(b.journey),
  );
  fs.writeFileSync(
    EVIDENCE,
    JSON.stringify(
      {
        suite: "guided-workspace",
        model: "MODEL MOCK",
        ui: UI,
        api: API,
        passed: merged.filter((e) => e.status === "PASS").length,
        total: merged.length,
        journeys: merged,
      },
      null,
      2,
    ),
  );
  console.log(`\n  ${evidence.length - failures}/${evidence.length} journeys passed this run`);
  process.exit(failures ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
