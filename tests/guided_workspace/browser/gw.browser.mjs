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
  page.calls = calls;
  page.crashes = crashes;
  live.push(page);
  return page;
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
  await page.locator(chart).scrollIntoViewIfNeeded();
  const box = await page.locator(`${chart} g.point path`).nth(index).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(250);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
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
  await page.waitForSelector('[data-testid="whatif-waterfall-total"][data-rendered="true"]', { timeout: 60_000 });
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
    await page.waitForURL(/\/lenses\?from_thread=/, { timeout: 60_000 });
    await page.waitForSelector('[data-testid="lens-preview"]', { timeout: 60_000 });
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
    assert.ok(states.some((t) => /METHOD_SELECTION/.test(t)) && states.some((t) => /method chosen: Delta/.test(t)) && states.some((t) => /EXECUTED/.test(t)));
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
