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

async function main() {
  browser = await chromium.launch({ executablePath: CHROME });
  try {
    await p1Journeys();
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
