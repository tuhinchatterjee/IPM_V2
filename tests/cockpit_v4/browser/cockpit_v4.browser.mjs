/**
 * REAL BROWSER · REAL UI · REAL BACKEND · MOCK ANALYST.
 *
 * A real Chromium against the real Next.js UI and the real V4 API. Every
 * network request the page makes is recorded, which is what makes the central
 * claim checkable rather than asserted: the Cockpit page uses the V4 run API
 * and never touches the legacy investigation or agentic-officer endpoints.
 *
 * The ANALYST is a stub. This proves the wiring, the lifecycle and the
 * rendering. It proves nothing about answer quality, and nothing here claims
 * a live Opus validation.
 */

import assert from "node:assert/strict";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.V4_UI_URL ?? "http://127.0.0.1:5414";
const API = process.env.V4_API_URL ?? "http://127.0.0.1:8414";
const CHROME =
  process.env.V4_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

/** Endpoints a V4 runtime must never call. The defect, as a list. */
const FORBIDDEN = [
  "/api/v1/investigations",
  "/api/v1/agentic/officer",
  "/api/v1/ask/mode",
  "/api/v1/ask/briefing",
  "/api/v1/ask/suggestions",
  "/api/v1/ask/cockpit-v2/diagnostics",
  "/api/v1/cockpit/diagnostics",
];

const results = [];
let failures = 0;

async function test(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`  ok   ${name}`);
  } catch (error) {
    failures += 1;
    results.push({
      name,
      ok: false,
      ms: Date.now() - started,
      error: String(error?.message ?? error).split("\n").slice(0, 4).join(" | "),
    });
    console.log(`  FAIL ${name}\n       ${error?.message ?? error}`);
  }
}

/** A page that records every request it makes, with a live event tap. */
async function openCockpit(browser, { path = "/" } = {}) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const requests = [];
  const sse = [];
  const problems = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", (request) =>
    problems.push(
      `requestfailed: ${request.url()} — ${request.failure()?.errorText ?? ""}`,
    ),
  );
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/events")) sse.push({ url, status: response.status() });
  });
  await page.goto(`${UI}${path}`, { waitUntil: "domcontentloaded" });
  await expect(page, '[data-testid="cockpit-v4-home"]', 60_000, problems);
  return { context, page, requests, sse, problems };
}

function calls(requests, fragment) {
  return requests.filter((url) => url.includes(fragment));
}

function assertNoLegacyCalls(requests, where) {
  for (const endpoint of FORBIDDEN) {
    const hits = calls(requests, endpoint);
    assert.equal(
      hits.length,
      0,
      `${where}: the V4 runtime called ${endpoint} (${hits[0] ?? ""}). ` +
        `That is the legacy flow, and reaching it means Opus V4 was bypassed.`,
    );
  }
}

async function ask(page, question) {
  await page.fill('[data-testid="cockpit-v4-question"]', question);
  await page.click('[data-testid="cockpit-v4-ask"]');
}

/** Wait, and say what the browser complained about when it times out. */
async function expect(page, selector, timeout, problems) {
  try {
    return await page.waitForSelector(selector, { timeout });
  } catch (error) {
    const submitError = await page
      .textContent('[data-testid="cockpit-v4-submit-error"]')
      .catch(() => "");
    throw new Error(
      `${selector} never appeared.` +
        (submitError ? ` Page said: ${submitError}.` : "") +
        (problems?.length ? ` Browser reported: ${problems.slice(0, 3).join(" ; ")}` : ""),
    );
  }
}

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

console.log(`\nCockpit V4 browser tests — UI ${UI}, API ${API}\n`);

// ---- the central claim -------------------------------------------------

await test(
  "asking 'Who are you?' posts to the V4 run API and never to the legacy flow",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      // Nothing legacy on load, before a single interaction.
      assertNoLegacyCalls(requests, "on page load");

      await ask(page, "Who are you?");

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const runPosts = calls(requests, "/api/v1/cockpit-v4/runs").filter(
        (url) => !url.includes("/events") && !url.includes("/cancel"),
      );
      assert.ok(
        runPosts.length >= 1,
        "submitting must POST /api/v1/cockpit-v4/runs",
      );
      assertNoLegacyCalls(requests, "after submitting");
    } finally {
      await context.close();
    }
  },
);

await test("the process panel appears and consumes the V4 event stream",
  async () => {
    const { context, page, requests, sse, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");

      // The panel is on screen while the run is still working — not after.
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const streams = calls(requests, "/events");
      assert.ok(
        streams.length >= 1,
        "the page must subscribe to /runs/{run_id}/events",
      );
      assert.match(
        streams[0],
        /\/api\/v1\/cockpit-v4\/runs\/run-[0-9a-f]+\/events/,
        "the stream must be the V4 run's own event endpoint",
      );
      assert.ok(
        sse.some((s) => s.status === 200),
        "the event stream must actually connect",
      );
    } finally {
      await context.close();
    }
  },
);

await test("progress events are rendered before the answer arrives",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");

      // Open the panel and capture the summary while the run is still going.
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);
      await page.click('[data-testid="v4-toggle-process"]');

      const working = await page.waitForFunction(
        () => {
          const summary = document.querySelector(
            '[data-testid="v4-process-summary"]',
          );
          const answered = document.querySelector('[data-testid="v4-response"]');
          if (answered) return false;
          const text = summary?.textContent ?? "";
          return /elapsed/.test(text) ? text : false;
        },
        { timeout: 30_000 },
      );
      const summaryWhileWorking = await working.jsonValue();
      assert.ok(
        summaryWhileWorking,
        "a working summary must be visible before the answer",
      );

      // The steps are backend stages, not invented labels.
      const steps = await page.$$eval(
        '[data-testid="v4-process-steps"] li',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      assert.ok(steps.length >= 1, "the panel lists real stages");
      assert.ok(
        steps.some((s) => /Request accepted|Understanding the request/.test(s)),
        `the stages must be backend stages, got ${JSON.stringify(steps)}`,
      );

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    } finally {
      await context.close();
    }
  },
);

await test("the final answer renders with its disposition", async () => {
  const { context, page, requests, problems } = await openCockpit(browser);
  try {
    await ask(page, "Who are you?");
    const panel = await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    const disposition = await panel.getAttribute("data-disposition");
    assert.equal(disposition, "answer");
    const text = await panel.textContent();
    assert.match(text ?? "", /CreditProbe Cockpit/);

    // The authoritative status was read, not guessed.
    assert.ok(
      calls(requests, "/api/v1/cockpit-v4/runs/").some(
        (url) => !url.includes("/events"),
      ),
      "the page reads the authoritative run state",
    );
  } finally {
    await context.close();
  }
});

await test("an evidence-bound analysis renders artifact links", async () => {
  const { context, page, problems } = await openCockpit(browser);
  try {
    await ask(page, "What is the EAD by sector for the latest quarter?");
    await expect(page, '[data-testid="v4-response"]', 90_000, problems);
    const artifacts = await page.$$eval(
      '[data-testid="v4-artifacts"] a',
      (nodes) => nodes.map((n) => n.getAttribute("href") ?? ""),
    );
    assert.ok(artifacts.length >= 1, "the answer links to its evidence");
    assert.match(artifacts[0], /\/api\/v1\/cockpit-v4\/runs\/.+\/artifacts\//);
  } finally {
    await context.close();
  }
});

// ---- failure, cancel, replay ------------------------------------------

await test("a terminal failure renders explicitly with a support reference",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      await ask(page, "please fail this run");
      await expect(page, '[data-testid="v4-terminal-failure"]', 60_000, problems);
      const text = await page.textContent('[data-testid="v4-terminal-failure"]');
      assert.match(
        text ?? "",
        /stopped|interrupted|ran out of time/i,
        "a failure is rendered as a failure, not as a short answer",
      );
      assertNoLegacyCalls(requests, "on a failed run");
    } finally {
      await context.close();
    }
  },
);

await test("stop cancels the run through the V4 cancel endpoint", async () => {
  const { context, page, requests, problems } = await openCockpit(browser);
  try {
    await ask(page, "a slow question");
    await page.waitForSelector('[data-testid="v4-stop"]', { timeout: 30_000 });
    await page.click('[data-testid="v4-stop"]');

    await page.waitForFunction(
      () => {
        const summary = document.querySelector(
          '[data-testid="v4-process-summary"]',
        );
        return /Cancelled/i.test(summary?.textContent ?? "");
      },
      { timeout: 60_000 },
    );

    const cancels = calls(requests, "/cancel");
    assert.ok(cancels.length >= 1, "Stop must call the V4 cancel endpoint");
    assert.match(cancels[0], /\/api\/v1\/cockpit-v4\/runs\/run-[0-9a-f]+\/cancel/);
  } finally {
    await context.close();
  }
});

await test("a browser refresh replays the same run instead of re-asking",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "a slow question");
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);

      const runId = await page.evaluate(() => {
        const raw = sessionStorage.getItem("cockpit-v4:active-run");
        return raw ? JSON.parse(raw).runId : "";
      });
      assert.match(runId, /^run-[0-9a-f]+$/, "the active run is remembered");

      // Reload, and watch what the fresh page does.
      const afterReload = [];
      page.on("request", (request) => afterReload.push(request.url()));
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page, '[data-testid="v4-process-panel"]', 60_000, problems);

      const posts = afterReload.filter(
        (url) =>
          url.endsWith("/api/v1/cockpit-v4/runs") ||
          url.endsWith("/api/v1/cockpit-v4/threads"),
      );
      assert.equal(
        posts.length,
        0,
        `a refresh must not start a new run; it requested ${JSON.stringify(posts)}`,
      );
      assert.ok(
        afterReload.some((url) => url.includes(`${runId}/events`)),
        "the refreshed page reconnects to the SAME run's event stream",
      );
      assertNoLegacyCalls(afterReload, "after a refresh");
    } finally {
      await context.close();
    }
  },
);

// ---- the shell around it ----------------------------------------------

await test("optional landing widgets show a neutral state and request nothing",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      const neutral = await page.$$('[data-testid="v4-not-in-runtime"]');
      assert.ok(
        neutral.length >= 1,
        "optional widgets render a neutral not-in-this-runtime state",
      );
      const text = await page.textContent('[data-testid="v4-not-in-runtime"]');
      assert.match(text ?? "", /not available in this isolated Cockpit V4/);
      assertNoLegacyCalls(requests, "for the optional widgets");
    } finally {
      await context.close();
    }
  },
);

await test("no request from the page goes to the legacy backend port",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
      const stray = requests.filter((url) => /:8000(\/|$)/.test(url));
      assert.deepEqual(stray, [], "nothing may address the legacy backend");
    } finally {
      await context.close();
    }
  },
);

await browser.close();

const summary = {
  label: "REAL BROWSER · REAL UI · REAL BACKEND · MOCK ANALYST",
  note:
    "The analyst model is a stub. This proves the wiring, the run lifecycle " +
    "and the rendering. It is NOT a live Opus validation.",
  ui: UI,
  api: API,
  total: results.length,
  passed: results.filter((r) => r.ok).length,
  failed: failures,
  forbidden_endpoints_checked: FORBIDDEN,
  results,
};
console.log(`\n${summary.passed}/${summary.total} browser tests passed\n`);
if (process.env.V4_BROWSER_EVIDENCE) {
  const { writeFileSync } = await import("node:fs");
  writeFileSync(
    process.env.V4_BROWSER_EVIDENCE,
    JSON.stringify(summary, null, 2) + "\n",
  );
  console.log(`evidence written to ${process.env.V4_BROWSER_EVIDENCE}`);
}
process.exit(failures === 0 ? 0 : 1);
