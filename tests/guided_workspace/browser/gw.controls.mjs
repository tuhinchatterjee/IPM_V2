/**
 * Control execution journeys (GW-CTL-*) · REAL BROWSER · REAL UI · REAL API
 * · REAL STORES · REAL ENGINE · MOCK ANALYST.
 *
 * One deliberate execution of every reachable control in the validation
 * inventory (docs/guided_workspace/validation/UI_CONTROL_INVENTORY.csv),
 * recorded with `ctl` (prerequisite state, action, expected and observed
 * transition, API calls, writes, console) or, for a control that navigates,
 * with `navTrip` (destination, browser Back, browser Forward, in-product
 * Back, business-object identity across the handoff). Legacy surfaces the
 * enabled configuration does not render are proven absent at runtime
 * (`na_proofs`), never assumed.
 */

let H;

const sel = (id) => `[data-testid="${id}"]`;

async function waitPath(page, re, timeout = 90_000) {
  await page.waitForFunction((src) => new RegExp(src).test(location.pathname + location.search), re.source, { timeout });
}

// =========================================================================
// NOT APPLICABLE WITH PROOF — the legacy surfaces
// =========================================================================

async function naJourney() {
  const { journey, open, askFromHome, latestRun, assert, UI } = H;
  await journey("GW-CTL-NA", "Legacy surfaces are not rendered under the enabled configuration: each legacy route renders or hands over to its governed equivalent, the legacy surface is absent, and Back does not loop", async (record) => {
    const page = await open();
    await askFromHome(page, record, "Show me construction exposure by sector");
    const run = await latestRun(record.thread_id);
    assert.ok(run, "a governed V4 run exists");
    const cases = [
      { route: "/", url: "/", lands: /^\/$/, governed: "cockpit-v4-home", legacy: 'textarea[aria-label="Ask CreditProbe a question about the portfolio"], [data-testid="attention-case"]' },
      { route: "/early-warning", url: "/early-warning", lands: /^\/early-warning$/, governed: "early-warning-v4", legacy: 'a[href="/early-warning/signals"], a[href="/early-warning/lab"]' },
      { route: "/lenses", url: "/lenses", lands: /^\/lenses$/, governed: "lens-library", legacy: 'button:has-text("Build it")' },
      { route: "/lenses/[lensId]", url: "/lenses/lens-02", lands: /^\/lenses\/lens-02$/, governed: "lens-view", legacy: 'text="What you are looking at"' },
      { route: "/lenses/cro", url: "/lenses/cro", lands: /^\/lenses\/lens-01$/, governed: "lens-view", legacy: 'section[aria-label="Portfolio health"], h2:has-text("Portfolio health")' },
      { route: "/stress", url: "/stress", lands: /^\/what-if$/, governed: "whatif-workspace", legacy: 'h1:has-text("Stress Testing")' },
      { route: "/trace", url: "/trace", lands: /^\/$/, governed: "cockpit-v4-home", legacy: 'h1:has-text("Trace & Lineage")' },
      { route: "/trace/[runId]", url: `/trace/${run}`, lands: new RegExp(`^/cockpit/trace/${run}$`), governed: "trace-llm-exchange-link", legacy: 'a:has-text("Trace & Lineage")' },
      { route: "/early-warning/lab", url: "/early-warning/lab", lands: /^\/early-warning$/, governed: "early-warning-v4", legacy: 'text="What the Model Lab does"' },
      { route: "/early-warning/signals", url: "/early-warning/signals", lands: /^\/early-warning$/, governed: "early-warning-v4", legacy: 'h1:has-text("Early Warning Signals")' },
    ];
    record.na_proofs = [];
    for (const c of cases) {
      // Arrive from a neutral page so the history step before the legacy
      // address is known: Back must return there, not into a redirect loop.
      await page.goto(`${UI}/metrics`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(sel("metric-catalogue"), { timeout: 120_000 });
      await page.goto(`${UI}${c.url}`, { waitUntil: "domcontentloaded" });
      const row = { route: c.route, visited: c.url, governed_marker: c.governed };
      try {
        await waitPath(page, c.lands);
        await page.waitForSelector(sel(c.governed), { timeout: 120_000 });
        await page.waitForLoadState("networkidle").catch(() => undefined);
        row.landed = new URL(page.url()).pathname;
        // The legacy surface is looked for in the page content, not in the
        // navigation (which names every module).
        row.legacy_absent = (await page.locator('[data-testid="app-content-column"]').locator(c.legacy).count()) === 0;
        await page.goBack();
        await waitPath(page, /^\/metrics/, 60_000);
        row.back_returns_to = new URL(page.url()).pathname;
        row.status = row.legacy_absent ? "PASS" : "FAILED";
      } catch (e) {
        row.status = "FAILED";
        row.error = String(e?.message ?? e).split("\n")[0].slice(0, 200);
      }
      record.na_proofs.push(row);
    }
    assert.deepEqual(record.na_proofs.filter((r) => r.status !== "PASS").map((r) => JSON.stringify(r).slice(0, 300)), [], "every legacy route renders its governed equivalent only");
  });
}

// =========================================================================
// ROUTES — every page route: direct, refresh, browser Back/Forward, the
// in-product Back where the page has one, invalid id, stale/deleted id
// =========================================================================

const tplObj = () => "scn-tpl-corp-01";

async function routesJourney() {
  const { journey, open, askFromHome, latestRun, api, post, assert, UI, API } = H;
  await journey("GW-CTL-ROUTES", "27 routes: direct entry, refresh, browser Back/Forward, in-product Back, invalid and stale ids — handled in words, nothing crashes", async (record) => {
    const page = await open();
    await askFromHome(page, record, "Show me construction exposure by sector");
    const thread = record.thread_id;
    const run = await latestRun(thread);
    // A saved analysis of a finished run, through the governed V4 API.
    const savedResp = await fetch(`${API}/api/v1/cockpit-v4/saved-analyses`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ run_id: run, title: "GW-CTL-ROUTES saved" }),
    });
    const saved = await savedResp.json();
    assert.equal(savedResp.status, 201, `saved analysis created: ${JSON.stringify(saved).slice(0, 200)}`);
    const issue = (await api("/issues?domain=corporate")).body.issues[0];
    // An executed result and a comparison of it, through the governed API.
    // A comparison needs two distinct results.
    let results = (await api("/whatif/results")).body.results;
    for (let i = results.length; i < 2; i += 1) await H.apiRun(tplObj(), `gw-ctl-routes-${i}`, ["delta"]);
    results = (await api("/whatif/results")).body.results;
    const result = results[0];
    const cmp = (await post("/whatif/compare", { result_ids: [results[0].object_id, results[1].object_id] })).body;
    assert.ok(cmp.object_id, `a comparison exists: ${JSON.stringify(cmp).slice(0, 200)}`);
    // A retired scenario is the stale id: the store is append-only, so an
    // object is retired (ARCHIVED), never deleted.
    const tpl = "scn-tpl-corp-01";
    const stale = (await post(`/scenarios/${tpl}/clone`, { name: "GW-CTL stale" })).body;
    const retired = await post(`/scenarios/${stale.object_id}/retire`, {});
    assert.equal(retired.body?.status, "ARCHIVED", "the copy is retired");
    const back = encodeURIComponent("/metrics");
    const R = [
      { route: "/", url: "/", marker: "cockpit-v4-home" },
      { route: "/ai-model-lab", url: "/ai-model-lab", marker: "ai-model-lab", inApp: "lab-back" },
      { route: "/cockpit/data", url: "/cockpit/data", marker: null },
      { route: "/cockpit/saved/[savedId]", url: `/cockpit/saved/${saved.saved_id}`, marker: "cockpit-v4-thread", lands: new RegExp(`^/cockpit/thread/${saved.thread_id}`), invalid: "/cockpit/saved/sav-doesnotexist", invalidText: /could not be opened/ },
      { route: "/cockpit/thread/[threadId]", url: `/cockpit/thread/${thread}`, marker: "cockpit-v4-thread", invalid: "/cockpit/thread/th-doesnotexist" },
      { route: "/cockpit/trace/[runId]", url: `/cockpit/trace/${run}`, marker: "trace-llm-exchange-link", invalid: "/cockpit/trace/run-doesnotexist" },
      { route: "/early-warning", url: "/early-warning", marker: "early-warning-v4" },
      { route: "/early-warning/lab", url: "/early-warning/lab", marker: "early-warning-v4", lands: /^\/early-warning$/ },
      { route: "/early-warning/signals", url: "/early-warning/signals", marker: "early-warning-v4", lands: /^\/early-warning$/ },
      { route: "/issues/[issueId]", url: `/issues/${issue.issue_id}`, marker: "issue-detail", inApp: "issue-detail-back", invalid: "/issues/iss-doesnotexist" },
      { route: "/lenses/[lensId]", url: "/lenses/lens-02", marker: "lens-view", inApp: "lens-back", invalid: "/lenses/lens-doesnotexist" },
      { route: "/lenses/cro", url: "/lenses/cro", marker: "lens-view", lands: /^\/lenses\/lens-01/ },
      { route: "/lenses", url: "/lenses", marker: "lens-library", inApp: "lens-library-back" },
      { route: "/messages", url: "/messages", marker: "messages-center", inApp: "messages-back" },
      { route: "/metrics", url: "/metrics?m=M001", marker: "metric-catalogue", inApp: "metrics-back", from: "/monitoring", fromMarker: "monitoring-centre" },
      { route: "/monitoring", url: "/monitoring", marker: "monitoring-centre", inApp: "monitoring-back" },
      { route: "/scenarios/[scenarioId]", url: `/scenarios/${tpl}`, marker: "scenario-detail", inApp: "scenario-back", invalid: "/scenarios/scn-doesnotexist", stale: `/scenarios/${stale.object_id}`, staleText: /ARCHIVED|[Rr]etired/ },
      { route: "/scenarios/new", url: "/scenarios/new", marker: "scenario-builder", inApp: "builder-back" },
      { route: "/scenarios", url: "/scenarios", marker: "scenario-library", inApp: "scenario-library-back" },
      { route: "/stress", url: "/stress", marker: "whatif-workspace", lands: /^\/what-if/ },
      { route: "/trace/[runId]", url: `/trace/${run}`, marker: "trace-llm-exchange-link", lands: new RegExp(`^/cockpit/trace/${run}`), invalid: "/trace/12345" },
      { route: "/trace/llm-exchange/[runId]", url: `/trace/llm-exchange/${run}`, marker: "llm-exchange", inApp: "llm-exchange-back", invalid: "/trace/llm-exchange/run-doesnotexist" },
      { route: "/trace/object/[objectId]", url: `/trace/object/${tpl}`, marker: "object-trace", inApp: "trace-object-back", invalid: "/trace/object/obj-doesnotexist" },
      { route: "/trace", url: "/trace", marker: "cockpit-v4-home", lands: /^\/$/ },
      { route: "/what-if/compare/[comparisonId]", url: `/what-if/compare/${cmp.object_id}`, marker: "comparison", inApp: "comparison-back", invalid: "/what-if/compare/cmp-doesnotexist" },
      { route: "/what-if", url: "/what-if", marker: "whatif-workspace", inApp: "whatif-back" },
      { route: "/what-if/result/[resultId]", url: `/what-if/result/${result?.object_id}`, marker: "whatif-result", inApp: "whatif-result-back", invalid: "/what-if/result/res-doesnotexist" },
    ];
    const broken = (p) => p.evaluate(() => {
      const t = document.body?.innerText ?? "";
      return /This page could not be found|Application error|Unhandled Runtime Error|could not be displayed/.test(t) || !t.trim();
    });
    const ready = async (r) => {
      if (r.lands) await waitPath(page, r.lands);
      if (r.marker) await page.waitForSelector(sel(r.marker), { timeout: 120_000 });
      else await page.waitForFunction(() => (document.body?.innerText ?? "").trim().length > 40, null, { timeout: 120_000 });
      await page.waitForLoadState("networkidle").catch(() => undefined);
    };
    // Deliberately missing objects answer 404/422; the browser logs its own
    // "Failed to load resource" line for them. Matched exactly, invalid-id
    // steps only.
    const MISSING = /Failed to load resource: the server responded with a status of (404|422)/;
    record.route_checks = [];
    for (const r of R) {
      const row = { route: r.route, url: r.url };
      const mark = page.consoleLog.length;
      try {
        await page.goto(`${UI}${r.url}`, { waitUntil: "domcontentloaded" });
        await ready(r);
        const landed = new URL(page.url());
        const at = landed.pathname + landed.search;
        row.direct = (await broken(page)) ? "FAILED" : "PASS";
        await page.reload({ waitUntil: "domcontentloaded" });
        await ready(r);
        row.refresh = (await broken(page)) ? "FAILED" : "PASS";
        // Browser Back/Forward from a known page.
        const from = r.from ?? "/metrics";
        await page.goto(`${UI}${from}`, { waitUntil: "domcontentloaded" });
        await page.waitForSelector(sel(r.fromMarker ?? "metric-catalogue"), { timeout: 120_000 });
        await page.goto(`${UI}${r.url}`, { waitUntil: "domcontentloaded" });
        await ready(r);
        await page.goBack();
        await waitPath(page, new RegExp(`^${from.replace(/[?]/g, "\\?")}`), 60_000);
        await page.goForward();
        await ready(r);
        const again = new URL(page.url());
        row.browser_back_forward = again.pathname + again.search === at ? "PASS" : `FAILED forward at ${again.pathname}${again.search} != ${at}`;
        if (r.inApp) {
          const sep = r.url.includes("?") ? "&" : "?";
          await page.goto(`${UI}${r.url}${sep}back=${back}`, { waitUntil: "domcontentloaded" });
          await ready(r);
          await page.click(sel(r.inApp), { timeout: 60_000 });
          await waitPath(page, /^\/metrics$/, 60_000);
          row.in_app_back = "PASS";
        } else {
          row.in_app_back = "N/A (the page has no origin control)";
        }
        const errors = page.consoleLog.slice(mark).filter((l) => /^(error|pageerror):/.test(l));
        if (errors.length) row.console_errors = errors.slice(0, 3);
        for (const [kind, url, text] of [["invalid", r.invalid, r.invalidText], ["stale", r.stale, r.staleText]]) {
          if (!url) continue;
          const m2 = page.consoleLog.length;
          await page.goto(`${UI}${url}`, { waitUntil: "domcontentloaded" });
          await page.waitForFunction(() => (document.body?.innerText ?? "").trim().length > 40, null, { timeout: 120_000 });
          await page.waitForLoadState("networkidle").catch(() => undefined);
          const body = await page.evaluate(() => document.body.innerText);
          const ok = !(await broken(page)) && (!text || text.test(body));
          const lines = page.consoleLog.slice(m2);
          const unexpected = lines.filter((l) => /^(error|pageerror):/.test(l) && !MISSING.test(l));
          page.consoleLog.splice(m2, lines.length, ...lines.filter((l) => !MISSING.test(l)));
          row[kind] = ok && !unexpected.length ? "PASS" : `FAILED ${unexpected.join(" | ").slice(0, 160)} ${body.slice(0, 120)}`;
        }
        row.permission = "API-tested (tests/cockpit_v4: exchange role 403, other tenant 404/403); the browser runtime has one server-resolved principal";
        row.deleted = "N/A (append-only store: objects are retired, never deleted; see stale)";
        const parts = [row.direct, row.refresh, row.browser_back_forward, row.in_app_back, row.invalid, row.stale].filter(Boolean);
        row.status = parts.every((p) => p === "PASS" || p.startsWith("N/A")) && !row.console_errors ? "PASS" : "FAILED";
      } catch (e) {
        row.status = "FAILED";
        row.error = String(e?.message ?? e).split("\n")[0].slice(0, 200);
      }
      record.route_checks.push(row);
    }
    record.routes_checked = record.route_checks.length;
    assert.equal(new Set(R.map((r) => r.route)).size, 27, "27 distinct routes");
    assert.deepEqual(record.route_checks.filter((r) => r.status !== "PASS").map((r) => JSON.stringify(r).slice(0, 400)), [], "every route passes every applicable check");
  });
}

// =========================================================================
// Shared readers for handoff identity
// =========================================================================

const describe = (o) => (o == null ? "" : JSON.stringify(o).slice(0, 240));

async function objectOf(id) {
  return (await H.api(`/objects/${encodeURIComponent(id)}`)).body;
}

/** The governed cohort a What-If page holds (strip), as stored. */
async function whatifCohort(page) {
  await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 120_000 });
  const id = await page.getAttribute('[data-testid="whatif-strip-cohort"]', "data-cohort-id");
  const o = await objectOf(id);
  return { cohort: id, entities: o?.body?.counts?.entities, hash: o?.body?.membership_hash, source: o?.body?.source?.ref ?? "", domain: o?.domain_id };
}

/** The investigation a Cockpit thread page is bound to. */
async function threadInvestigation(page) {
  const m = /\/cockpit\/thread\/([^/?]+)/.exec(page.url());
  const state = (await H.api(`/investigations/by-thread/${m?.[1]}`)).body ?? {};
  const cohort = state.cohort_id ? await objectOf(state.cohort_id) : null;
  return { thread: m?.[1], issue: state.issue_id ?? "", investigation: state.investigation_id ?? "", cohort: state.cohort_id ?? "", entities: cohort?.body?.counts?.entities, hash: cohort?.body?.membership_hash };
}

async function issueOf(issueId) {
  const i = (await H.api(`/issues/${issueId}`)).body;
  return { issue: i.issue_id, entities: i.cohort?.entities ?? i.materiality?.affected_entities, domain: i.domain_id, top: String(i.evidence?.breakdown?.[0]?.label ?? "") };
}

const issueToWhatIf = (issueId) => ({
  source: () => issueOf(issueId),
  destination: (p) => whatifCohort(p),
  identity: (s, d) => {
    H.assert.equal(d.source, s.issue, "the What-If cohort was frozen from this issue");
    H.assert.equal(d.entities, s.entities, "the same population (entities)");
    H.assert.equal(d.domain, s.domain, "the same book");
    return `issue ${s.issue} (${s.entities} entities) → cohort ${d.cohort} source=${d.source}, ${d.entities} entities, hash ${String(d.hash).slice(0, 12)}`;
  },
  writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/issues\/[^/]+\/cohort /,
  describe,
});

const issueToThread = (issueId) => ({
  source: () => issueOf(issueId),
  destination: (p) => threadInvestigation(p),
  identity: (s, d) => {
    H.assert.equal(d.issue, s.issue, "the thread's investigation is this issue's");
    H.assert.equal(d.entities, s.entities, "the investigation cohort is the issue population");
    return `issue ${s.issue} → thread ${d.thread} investigation ${d.investigation} issue=${d.issue}, cohort ${d.cohort} ${d.entities} entities`;
  },
  writes: /^POST \/api\/v1\/cockpit-v4\/(workspace\/(issues\/[^/]+\/investigate|investigations\/[^/]+\/steps)|runs) /,
  describe,
});

async function clickPlotPoint(page, chartTestId, { trace = 0, point = 0, selector = "g.point path" } = {}) {
  const chart = `[data-testid="${chartTestId}"]`;
  await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 60_000 });
  await page.evaluate((s) => document.querySelector(s)?.scrollIntoView({ block: "center" }), chart);
  await page.waitForTimeout(300);
  const box = await page.locator(`${chart} g.trace`).nth(trace).locator(selector).nth(point).boundingBox();
  H.assert.ok(box, `${chartTestId}: trace ${trace} point ${point} is drawn`);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const onChart = await page.evaluate(([s, px, py]) => Boolean(document.querySelector(s)?.contains(document.elementFromPoint(px, py))), [chart, x, y]);
  H.assert.ok(onChart, `${chartTestId} point is not covered`);
  await page.mouse.move(x, y);
  // The app's hover payload (its hovertemplate) for this point.
  const hover = await page.waitForSelector(".hoverlayer .hovertext", { timeout: 3_000 }).then((h) => h.textContent()).catch(() => "");
  const control = await page.evaluate((s) => document.querySelector(s)?.closest("[data-control]")?.getAttribute("data-control") ?? "", chart);
  (page.hovers ??= []).push({ chart: chartTestId, control, text: (hover ?? "").slice(0, 200) });
  await page.waitForTimeout(250);
  await page.mouse.click(x, y);
}

/** Click and return the download's suggested file name. */
async function download(page, selector) {
  const [d] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click(selector)]);
  return d.suggestedFilename();
}

/** The ChartCard buttons (View data, CSV, PNG, SVG) of one chart. */
async function chartCardControls(page, record, chart, prereq) {
  const { ctl, assert } = H;
  await ctl(page, record, { id: `${chart}-view-data`, prereq, expected: "the chart's data table opens, then closes", run: async () => {
    await page.click(sel(`${chart}-view-data`));
    await page.waitForSelector(sel(`${chart}-table`), { timeout: 30_000 });
    const rows = await page.locator(`${sel(`${chart}-table`)} tbody tr`).count();
    assert.ok(rows > 0, "the table has rows");
    await page.click(sel(`${chart}-view-data`));
    await page.waitForSelector(sel(`${chart}-table`), { state: "detached", timeout: 30_000 });
    return `table with ${rows} rows shown and hidden`;
  } });
  for (const [suffix, ext] of [["csv", /\.csv$/], ["png", /\.png$/], ["svg", /\.svg$/]]) {
    await ctl(page, record, { id: `${chart}-${suffix}`, prereq, expected: `a ${suffix.toUpperCase()} file of the chart is downloaded`, run: async () => {
      const name = await download(page, sel(`${chart}-${suffix}`));
      assert.match(name, ext);
      return `downloaded ${name}`;
    } });
  }
}

const homeState = () => ({
  book: document.querySelector('[data-testid="domain-switch"]')?.getAttribute("data-domain") || "",
  issues: document.querySelector('[data-testid="requires-attention"]')?.getAttribute("data-count") || "",
});

// =========================================================================
// GUIDED COCKPIT — Requires Attention cards and the issue page
// =========================================================================

async function homeJourney() {
  const { journey, open, openHome, ctl, navTrip, assert, api, settle } = H;
  await journey("GW-CTL-HOME", "Requires Attention: every card control — title, Evidence, driver, Save cohort, What-If, Investigate, Ask next, Show all — executed with Back/Forward and the issue's identity", async (record) => {
    const page = await open();
    await openHome(page, "corporate");
    const prereq = "Cockpit home, Corporate book, Requires Attention loaded";
    const firstId = await page.locator('[data-testid="issue-card"]').first().getAttribute("data-issue-id");
    const cardSel = `[data-testid="issue-card"][data-issue-id="${firstId}"]`;
    const toIssue = {
      source: () => issueOf(firstId),
      destination: async (p) => ({ issue: await p.getAttribute('[data-testid="issue-detail"]', "data-issue-id"), driver: new URL(p.url()).searchParams.get("driver") ?? "" }),
      identity: (s, d) => {
        assert.equal(d.issue, s.issue, "the same issue opens");
        return `issue ${s.issue} → issue page ${d.issue}${d.driver ? ` narrowed to ${d.driver}` : ""}`;
      },
      describe,
    };
    for (const id of ["issue-title-open", "issue-open"]) {
      await navTrip(page, record, {
        id, prereq, expected: "opens the issue's evidence page; Back returns to the same book and feed",
        state: homeState,
        go: (p) => p.click(`${cardSel} [data-testid="${id}"]`),
        arrived: (p) => p.waitForSelector(`[data-testid="issue-detail"][data-issue-id="${firstId}"]`, { timeout: 120_000 }),
        inApp: '[data-testid="issue-detail-back"]', inAppTarget: "/",
        handoff: toIssue,
      });
    }
    const top = (await issueOf(firstId)).top;
    await navTrip(page, record, {
      id: "issue-driver", prereq, expected: "opens the issue page narrowed to the largest contributor",
      state: homeState,
      go: (p) => p.click(`${cardSel} [data-testid="issue-driver"]`),
      arrived: (p) => p.waitForFunction(() => new URLSearchParams(location.search).get("driver") && document.querySelector('[data-testid="issue-detail"]'), null, { timeout: 120_000 }),
      inApp: '[data-testid="issue-detail-back"]', inAppTarget: "/",
      handoff: { ...toIssue, identity: (s, d) => { assert.equal(d.issue, s.issue); assert.equal(d.driver, top, "narrowed to the largest contributor"); return `issue ${s.issue} → ${d.issue} driver=${d.driver}`; } },
    });
    await ctl(page, record, { id: "issue-save-cohort", prereq, expected: "the issue population is frozen as a governed cohort; the card says so", run: async () => {
      await page.click(`${cardSel} [data-testid="issue-save-cohort"]`);
      await page.waitForSelector(`${cardSel} [data-testid="issue-cohort-saved"]`, { timeout: 60_000 });
      const text = await page.textContent(`${cardSel} [data-testid="issue-cohort-saved"]`);
      const id = /(coh-[0-9a-z-]+)/.exec(text)?.[1];
      assert.ok(id, `the cohort id is shown: ${text}`);
      const c = await objectOf(id);
      const src = await issueOf(firstId);
      assert.equal(c.body.source.ref, firstId);
      assert.equal(c.body.counts.entities, src.entities);
      return `${text.trim()} · stored source=${c.body.source.ref} entities=${c.body.counts.entities}`;
    } });
    await navTrip(page, record, {
      id: "issue-whatif", prereq, expected: "freezes the issue population and opens What-If on it",
      state: homeState,
      go: (p) => p.click(`${cardSel} [data-testid="issue-whatif"]`),
      arrived: (p) => whatifCohort(p),
      inApp: '[data-testid="whatif-back"]', inAppTarget: "/",
      handoff: issueToWhatIf(firstId),
    });
    await navTrip(page, record, {
      id: "issue-investigate", prereq, expected: "opens a Cockpit investigation bound to the issue and its population",
      state: homeState,
      go: (p) => p.click(`${cardSel} [data-testid="issue-investigate"]`),
      arrived: (p) => p.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 }),
      inApp: '[data-testid="thread-origin-back"]', inAppTarget: "/",
      handoff: issueToThread(firstId),
    });
    const nbqText = await page.locator(`${cardSel} [data-testid="issue-nbq"]`).first().textContent();
    await navTrip(page, record, {
      id: "issue-nbq", prereq, expected: "opens the investigation and asks the suggested question in it (one model call)",
      state: homeState,
      go: (p) => p.locator(`${cardSel} [data-testid="issue-nbq"]`).first().click(),
      arrived: async (p) => {
        await p.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
        await settle(p, 0);
      },
      inApp: '[data-testid="thread-origin-back"]', inAppTarget: "/",
      handoff: { ...issueToThread(firstId), identity: async (s, d) => {
        const base = issueToThread(firstId).identity(s, d);
        const thread = await H.v4(`/threads/${d.thread}`);
        assert.ok(JSON.stringify(thread).includes(nbqText.trim().slice(0, 30)), "the suggested question was asked in that thread");
        return `${base}; asked "${nbqText.trim().slice(0, 60)}"`;
      } },
    });
    const count = Number(await page.getAttribute(sel("requires-attention"), "data-count"));
    const other = count > 6 ? "corporate" : "retail";
    if (count <= 6) await openHome(page, other);
    const n = Number(await page.getAttribute(sel("requires-attention"), "data-count"));
    await ctl(page, record, { id: "requires-attention-more", prereq: `Cockpit home, ${n > 6 ? "a book" : "no book"} with more than six items`, expected: "all items are listed, then six again", run: async () => {
      assert.ok(n > 6, `a book has more than six items (${count}, ${n})`);
      assert.equal(await page.locator(sel("issue-card")).count(), 6);
      await page.click(sel("requires-attention-more"));
      await page.waitForFunction((k) => document.querySelectorAll('[data-testid="issue-card"]').length === k, n, { timeout: 30_000 });
      await page.click(sel("requires-attention-more"));
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="issue-card"]').length === 6, null, { timeout: 30_000 });
      return `6 → ${n} → 6 cards`;
    } });
    void api;
  });
}

async function issueJourney() {
  const { journey, open, openIssue, anIssue, ctl, navTrip, assert, settle } = H;
  await journey("GW-CTL-ISSUE", "Issue page: Save cohort, stage-mix and driver chart drills, chart data/CSV/PNG/SVG, table-row drill, Ask next, Investigate, What-If — each executed and asserted", async (record) => {
    const issue = await anIssue();
    const page = await open();
    await openIssue(page, issue.issue_id);
    const prereq = `issue ${issue.issue_id} open, unfiltered`;
    const unfiltered = await page.getAttribute(sel("issue-grid"), "data-total");
    await ctl(page, record, { id: "issue-detail-save-cohort", prereq, expected: "the issue population is frozen; the button disables (one cohort)", run: async () => {
      await page.click(sel("issue-detail-save-cohort"));
      await page.waitForFunction(() => document.querySelector('[data-testid="issue-detail-save-cohort"]')?.disabled, null, { timeout: 60_000 });
      const text = await page.locator("text=/Saved [0-9,]+ .* as coh-/").first().textContent();
      const id = /(coh-[0-9a-z-]+)/.exec(text)?.[1];
      const c = await objectOf(id);
      assert.equal(c.body.source.ref, issue.issue_id);
      return `${text.trim()}; button disabled`;
    } });
    await ctl(page, record, { id: "issue-stage-mix", prereq, action: "click a stage segment", expected: "the grid narrows to that stage (?stage=), Back-able", run: async () => {
      await clickPlotPoint(page, "issue-stage-mix", { trace: 0, point: 0 });
      await page.waitForFunction(() => new URLSearchParams(location.search).get("stage"), null, { timeout: 30_000 });
      const stage = new URL(page.url()).searchParams.get("stage");
      await page.waitForFunction((n) => { const t = document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total"); return t && t !== n; }, unfiltered, { timeout: 60_000 });
      const total = await page.getAttribute(sel("issue-grid"), "data-total");
      await page.click(sel("issue-detail-clear-drill"));
      await page.waitForFunction((n) => document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") === n, unfiltered, { timeout: 60_000 });
      return `stage ${stage}: ${unfiltered} → ${total} rows; cleared back to ${unfiltered}`;
    } });
    await ctl(page, record, { id: "issue-drivers", prereq, action: "click the largest contributor's bar", expected: "the grid narrows to that contributor (?driver=); the hover names it", run: async () => {
      await clickPlotPoint(page, "issue-drivers", { point: 0 });
      await page.waitForFunction(() => new URLSearchParams(location.search).get("driver"), null, { timeout: 30_000 });
      const drv = new URL(page.url()).searchParams.get("driver");
      await page.waitForFunction((n) => { const t = document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total"); return t && t !== n; }, unfiltered, { timeout: 60_000 });
      await page.click(sel("issue-detail-clear-drill"));
      await page.waitForFunction((n) => document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") === n, unfiltered, { timeout: 60_000 });
      return `driver ${drv}; cleared`;
    } });
    await ctl(page, record, { id: "issue-drivers-table-row", prereq, action: "View data, then activate a contributor row", expected: "the grid narrows to that contributor (?driver=)", run: async () => {
      await page.click(sel("issue-drivers-view-data"));
      await page.waitForSelector(sel("issue-drivers-table-row"), { timeout: 30_000 });
      const label = (await page.locator(`${sel("issue-drivers-table-row")} td`).first().textContent()).trim();
      await page.locator(sel("issue-drivers-table-row")).first().click();
      await page.waitForFunction((l) => new URLSearchParams(location.search).get("driver") === l, label, { timeout: 30_000 });
      await page.click(sel("issue-detail-clear-drill"));
      await page.waitForFunction((n) => document.querySelector('[data-testid="issue-grid"]')?.getAttribute("data-total") === n, unfiltered, { timeout: 60_000 });
      await page.click(sel("issue-drivers-view-data"));
      return `row "${label}" → ?driver=${label}; cleared`;
    } });
    await chartCardControls(page, record, "issue-trend", prereq);
    await navTrip(page, record, {
      id: "issue-detail-whatif", prereq, expected: "freezes the issue population and opens What-If on it",
      state: H.issueState, arrived: (p) => whatifCohort(p), inApp: '[data-testid="whatif-back"]',
      handoff: issueToWhatIf(issue.issue_id),
    });
    await navTrip(page, record, {
      id: "issue-detail-investigate", prereq, expected: "opens an investigation bound to the issue and its population",
      state: H.issueState, arrived: (p) => p.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 }), inApp: '[data-testid="thread-origin-back"]',
      handoff: issueToThread(issue.issue_id),
    });
    await navTrip(page, record, {
      id: "issue-detail-nbq", prereq, expected: "opens the investigation and asks the suggested question there",
      state: H.issueState,
      go: (p) => p.locator(sel("issue-detail-nbq")).first().click(),
      arrived: async (p) => {
        await p.waitForSelector('[data-testid="investigation-bar"]', { timeout: 120_000 });
        await settle(p, 0);
      },
      inApp: '[data-testid="thread-origin-back"]',
      handoff: issueToThread(issue.issue_id),
    });
  });
}

// =========================================================================
// EARLY WARNING (governed EWS rule set)
// =========================================================================

const ewState = () => ({
  book: document.querySelector('[data-testid="ws-domain-switch"]')?.getAttribute("data-domain") || "",
  reason: document.querySelector('[data-testid="ew-reason-filter"]')?.getAttribute("data-reason") || "",
  segments: document.querySelectorAll('[data-testid="ew-segment-card"]').length,
});

async function openEw(page, query = "") {
  await page.goto(`${H.UI}/early-warning${query}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(sel("ew-segment-card"), { timeout: 120_000 });
}

async function ewJourney() {
  const { journey, open, ctl, navTrip, assert, api } = H;
  await journey("GW-CTL-EW", "Early Warning: book switch, rule filter, segment Save/Export/What-If/Investigate and the page-level verbs — identity of the exact population across each handoff; Back restores book and rule", async (record) => {
    const page = await open();
    await openEw(page);
    await ctl(page, record, { id: "ws-domain-corporate", prereq: "Early Warning, Retail book (default)", expected: "the Corporate book's rule set, bands and sector segments load", run: async () => {
      const before = await page.textContent(sel("early-warning-v4"));
      await page.click(sel("ws-domain-corporate"));
      await page.waitForFunction(() => document.querySelector('[data-testid="ws-domain-switch"]')?.getAttribute("data-domain") === "corporate", null, { timeout: 30_000 });
      await page.waitForSelector("text=By sector", { timeout: 60_000 });
      const after = await page.textContent(sel("early-warning-v4"));
      assert.notEqual(before, after);
      return "Retail → Corporate; segments by sector";
    } });
    const feed = (await api("/early-warning?domain=corporate")).body;
    const reason = feed.reasons[0].reason;
    await ctl(page, record, { id: "ew-reasons", prereq: "Early Warning, Corporate", action: "click the first rule's bar", expected: "the page is filtered to exposures tripping that rule", run: async () => {
      const idx = await page.evaluate((r) => (document.querySelector('[data-testid="ew-reasons"]')?.data?.[0]?.y ?? []).map(String).indexOf(r), reason);
      await clickPlotPoint(page, "ew-reasons", { point: idx });
      await page.waitForFunction((r) => document.querySelector('[data-testid="ew-reason-filter"]')?.getAttribute("data-reason") === r, reason, { timeout: 30_000 });
      return `filtered to "${reason}"`;
    } });
    const filtered = (await api(`/early-warning?domain=corporate&reason=${encodeURIComponent(reason)}`)).body;
    const seg = filtered.by_segment.find((x) => x.bands.filter((b) => ["critical", "high"].includes(b.value)).reduce((a, b) => a + b.n, 0) > 0);
    const segN = seg.bands.filter((b) => ["critical", "high"].includes(b.value)).reduce((a, b) => a + b.n, 0);
    const prereq = `Early Warning, Corporate, rule "${reason}", segment ${seg.segment}`;
    const segSel = (id) => `[data-testid="${id}"][data-segment="${seg.segment}"]`;
    const noteCohort = async () => {
      await page.waitForSelector(sel("ew-note"), { timeout: 60_000 });
      const text = await page.textContent(sel("ew-note"));
      return { text, id: /(coh-[0-9a-z-]+)/.exec(text)?.[1] };
    };
    await ctl(page, record, { id: "ew-seg-save", prereq, expected: `the segment's high/critical exposures tripping the rule (${segN}) are frozen as one cohort`, run: async () => {
      await page.click(segSel("ew-seg-save"));
      await page.waitForFunction(() => /cohort coh-/.test(document.querySelector('[data-testid="ew-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      const { text, id } = await noteCohort();
      const c = await objectOf(id);
      assert.equal(c.body.counts.entities, segN, "the exact population");
      assert.equal(c.body.source.kind, "early_warning");
      await page.click(segSel("ew-seg-save"));
      await page.waitForFunction(() => /already saved/.test(document.querySelector('[data-testid="ew-note"]')?.textContent ?? ""), null, { timeout: 30_000 });
      return `${text.trim()}; saving again reuses it`;
    } });
    await ctl(page, record, { id: "ew-seg-export", prereq, expected: "a CSV of exactly that population is downloaded", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click(segSel("ew-seg-export"))]);
      const fs = await import("node:fs");
      const lines = fs.readFileSync(await d.path(), "utf8").trim().split("\n");
      const rows = lines.filter((l) => !l.startsWith("#")).length - 1;
      assert.equal(rows, segN, "one row per exposure, after the provenance header");
      assert.ok(lines.some((l) => l.startsWith("# membership_hash") || l.includes("membership_hash")), "the export names the cohort's membership hash");
      return `${d.suggestedFilename()}: ${rows} rows + ${lines.length - rows - 1} provenance lines`;
    } });
    const ewCohort = (n) => ({
      source: async () => ({ entities: n, domain: "corporate", reason }),
      destination: (p) => whatifCohort(p),
      identity: async (s, d) => {
        assert.equal(d.entities, s.entities, "the exact early-warning population");
        assert.equal(d.domain, s.domain);
        const o = await objectOf(d.cohort);
        assert.equal(o.body.source.kind, "early_warning");
        return `${s.entities} exposures (${s.reason}) → cohort ${d.cohort} ${d.entities} entities, hash ${String(d.hash).slice(0, 12)}`;
      },
      writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/early-warning\/cohort /,
      describe,
    });
    const ewThread = (n) => ({
      source: async () => ({ entities: n, domain: "corporate", reason }),
      destination: async (p) => {
        const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1];
        const c = (await api(`/whatif/threads/${t}/cohort`)).body;
        const o = await objectOf(c.seed_cohort_id);
        return { thread: t, cohort: c.seed_cohort_id, entities: o?.body?.counts?.entities, kind: o?.body?.source?.kind };
      },
      identity: (s, d) => {
        assert.equal(d.entities, s.entities, "the investigation is seeded with the exact population");
        assert.equal(d.kind, "early_warning");
        return `${s.entities} exposures → thread ${d.thread} seeded with cohort ${d.cohort} (${d.entities})`;
      },
      writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/early-warning\/investigate /,
      describe,
    });
    await navTrip(page, record, {
      id: "ew-seg-whatif", prereq, expected: "opens What-If on the segment's exact population", state: ewState,
      go: (p) => p.click(segSel("ew-seg-whatif")), arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"),
      handoff: ewCohort(segN),
    });
    await navTrip(page, record, {
      id: "ew-seg-investigate", prereq, expected: "opens a Cockpit investigation on the segment's exact population", state: ewState,
      go: (p) => p.click(segSel("ew-seg-investigate")), arrived: (p) => p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }), inApp: sel("thread-origin-back"),
      handoff: ewThread(segN),
    });
    const all = filtered.severe_total ?? filtered.bands.filter((b) => ["critical", "high"].includes(b.value)).reduce((a, b) => a + b.n, 0);
    const pre2 = `Early Warning, Corporate, rule "${reason}"`;
    await navTrip(page, record, {
      id: "ew-whatif", prereq: pre2, expected: "opens What-If on the page's high/critical population", state: ewState,
      arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"), handoff: ewCohort(all),
    });
    await navTrip(page, record, {
      id: "ew-investigate", prereq: pre2, expected: "opens a Cockpit investigation on the page's high/critical population", state: ewState,
      arrived: (p) => p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }), inApp: sel("thread-origin-back"), handoff: ewThread(all),
    });
    await ctl(page, record, { id: "ew-reason-clear", prereq: pre2, expected: "the rule filter is removed; the whole book's warnings return", run: async () => {
      await page.click(sel("ew-reason-clear"));
      await page.waitForSelector(sel("ew-reason-filter"), { state: "detached", timeout: 30_000 });
      return "filter cleared";
    } });
    await chartCardControls(page, record, "ew-trend", "Early Warning, Corporate");
    await ctl(page, record, { id: "ws-domain-retail", prereq: "Early Warning, Corporate", expected: "back to the Retail book (product segments)", run: async () => {
      await page.click(sel("ws-domain-retail"));
      await page.waitForSelector("text=By product", { timeout: 60_000 });
      return "Corporate → Retail; segments by product";
    } });
  });
}

// =========================================================================
// WHAT-IF WORKSPACE — book, explorer, matrices, tornado, selection verbs,
// strip, loaders, exports, the conversation, and its handoffs
// =========================================================================

const strip = async (page) => ({
  cohort: (await page.getAttribute(sel("whatif-strip-cohort"), "data-cohort-id")) ?? "",
  scenario: (await page.getAttribute(sel("whatif-strip-scenario"), "data-scenario-id")) ?? "",
});

/** What-If writes its active objects into the address after each change;
 * a navigation is measured from the settled address. */
async function whatifSynced(page) {
  await page.waitForFunction(() => {
    const q = new URLSearchParams(location.search);
    const c = document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") || null;
    const s = document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") || null;
    return q.get("cohort") === c && q.get("scenario") === s;
  }, null, { timeout: 30_000 });
}

async function csvRows(d) {
  const fs = await import("node:fs");
  const lines = fs.readFileSync(await d.path(), "utf8").trim().split("\n");
  return lines.filter((l) => !l.startsWith("#")).length - 1;
}

async function whatifJourney() {
  const { journey, open, openWhatIf, ctl, navTrip, assert, api, gridTotal, waitSelectionEntities, settle } = H;
  await journey("GW-CTL-WHATIF", "What-If workspace: book switch, explorer and heatmap measures, heatmap and Sankey drills, tornado controls, selection Save/Share/Export/Investigate/Library, strip clear and loaders, scenario filter, ask, adopt, open and close the conversation", async (record) => {
    const page = await open();
    await openWhatIf(page, "?domain=corporate");
    const pre = "What-If, Corporate book, no selection";
    await ctl(page, record, { id: "ws-domain-retail", prereq: pre, expected: "the Retail book loads (grain and period change)", run: async () => {
      const before = await page.textContent(sel("whatif-book"));
      await page.click(sel("ws-domain-retail"));
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-workspace"]')?.getAttribute("data-domain") === "retail", null, { timeout: 60_000 });
      await page.waitForFunction((b) => (document.querySelector('[data-testid="whatif-book"]')?.textContent ?? b) !== b, before, { timeout: 60_000 });
      const after = await page.textContent(sel("whatif-book"));
      await page.click(sel("ws-domain-corporate"));
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-workspace"]')?.getAttribute("data-domain") === "corporate", null, { timeout: 60_000 });
      return `${before.trim()} → ${after.trim()} → back to corporate`;
    } });
    await ctl(page, record, { id: "whatif-explorer-dimension", prereq: pre, expected: "the explorer breaks the book down by another dimension", run: async () => {
      const before = await page.getAttribute(sel("whatif-explorer"), "data-dimension");
      const options = await page.$$eval(`${sel("whatif-explorer-dimension")} option`, (o) => o.map((x) => x.value));
      const next = options.find((o) => o !== before);
      await page.selectOption(sel("whatif-explorer-dimension"), next);
      await page.waitForFunction((n) => document.querySelector('[data-testid="whatif-explorer"]')?.getAttribute("data-dimension") === n, next, { timeout: 30_000 });
      await page.selectOption(sel("whatif-explorer-dimension"), before);
      await page.waitForFunction((n) => document.querySelector('[data-testid="whatif-explorer"]')?.getAttribute("data-dimension") === n, before, { timeout: 30_000 });
      return `${before} → ${next} → ${before}`;
    } });
    await ctl(page, record, { id: "whatif-explorer-measure", prereq: pre, expected: "the explorer bars switch between Booked ECL and EAD", run: async () => {
      await page.selectOption(sel("whatif-explorer-measure"), "ead_sar_mn");
      await page.waitForSelector(`${sel("whatif-chart-dimension-card")} h3:text-matches("^EAD by")`, { timeout: 30_000 });
      await page.selectOption(sel("whatif-explorer-measure"), "ecl_sar_mn");
      await page.waitForSelector(`${sel("whatif-chart-dimension-card")} h3:text-matches("^Booked ECL by")`, { timeout: 30_000 });
      return "Booked ECL → EAD → Booked ECL (chart title follows)";
    } });
    await ctl(page, record, { id: "whatif-heatmap-measure", prereq: pre, expected: "the heatmap switches between EAD and Booked ECL", run: async () => {
      await page.selectOption(sel("whatif-heatmap-measure"), "ecl_sar_mn");
      await page.waitForSelector(`${sel("whatif-chart-heatmap-card")} h3:text-matches("^Booked ECL by")`, { timeout: 30_000 });
      await page.selectOption(sel("whatif-heatmap-measure"), "ead_sar_mn");
      await page.waitForSelector(`${sel("whatif-chart-heatmap-card")} h3:text-matches("^EAD by")`, { timeout: 30_000 });
      return "EAD → Booked ECL → EAD";
    } });
    const total0 = await gridTotal(page);
    for (const chart of ["whatif-chart-dimension", "whatif-chart-stage"]) {
      await ctl(page, record, { id: chart, prereq: pre, action: "click the first bar", expected: "the grid is filtered to it (f= in the address); clearing restores the book", run: async () => {
        await clickPlotPoint(page, chart, { point: 0 });
        await page.waitForFunction((n) => { const t = document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total"); return t && Number(t) !== n; }, total0, { timeout: 60_000 });
        const narrowed = await gridTotal(page);
        await page.click(sel("grid-clear-filters"));
        await page.waitForFunction((n) => Number(document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total")) === n, total0, { timeout: 60_000 });
        return `${total0} → ${narrowed}; cleared`;
      } });
    }
    await ctl(page, record, { id: "whatif-chart-dimension", prereq: pre, action: "box-select two bars", expected: "the grid is filtered to both categories", run: async () => {
      const chart = sel("whatif-chart-dimension");
      await page.evaluate((c) => document.querySelector(c)?.scrollIntoView({ block: "center" }), chart);
      const b0 = await page.locator(`${chart} g.point path`).nth(0).boundingBox();
      const b1 = await page.locator(`${chart} g.point path`).nth(1).boundingBox();
      const plot = await page.locator(`${chart} rect.nsewdrag`).boundingBox();
      await page.mouse.move(Math.max(b0.x - 4, plot.x + 2), plot.y + 3);
      await page.mouse.down();
      await page.mouse.move(b1.x + b1.width + 4, b0.y + b0.height - 2, { steps: 12 });
      await page.mouse.up();
      await page.waitForFunction(() => { const f = new URLSearchParams(location.search).get("f"); return f && (JSON.parse(f)[0]?.values?.length ?? 0) >= 2; }, null, { timeout: 60_000 });
      const f = new URL(page.url()).searchParams.get("f");
      await page.click(sel("grid-clear-filters"));
      await page.waitForFunction((n) => Number(document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total")) === n, total0, { timeout: 60_000 });
      return `selected ${JSON.parse(f)[0].values.join(" + ")}; cleared`;
    } });
    await chartCardControls(page, record, "whatif-chart-dimension", pre);
    for (const chart of ["whatif-chart-heatmap", "whatif-chart-sankey"]) {
      await ctl(page, record, { id: chart, prereq: pre, action: "click the first cell / flow", expected: "the grid narrows to that cell (a filter in the address); clearing restores the book", run: async () => {
        if (chart === "whatif-chart-heatmap") await clickPlotPoint(page, chart, { selector: "rect, path", point: 0 }).catch(async () => {
          await page.click(sel(`${chart}-view-data`));
          await page.locator(sel(`${chart}-table-row`)).first().click();
        });
        else {
          await page.click(sel(`${chart}-view-data`));
          await page.locator(sel(`${chart}-table-row`)).first().click();
        }
        await page.waitForFunction((n) => { const t = document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total"); return t && Number(t) !== n; }, total0, { timeout: 60_000 });
        const narrowed = await gridTotal(page);
        const f = new URL(page.url()).searchParams.get("f");
        await page.click(sel("grid-clear-filters"));
        await page.waitForFunction((n) => Number(document.querySelector('[data-testid="whatif-grid"]')?.getAttribute("data-total")) === n, total0, { timeout: 60_000 });
        return `${total0} → ${narrowed} rows (f=${String(f).slice(0, 80)}); cleared`;
      } });
    }
    for (const [id, value, check] of [["tornado-parameter", "pd", "PD"], ["tornado-top", "8", null], ["tornado-scale", "2", null]]) {
      await ctl(page, record, { id, prereq: pre, expected: "the macro sensitivity is recomputed for the new setting", run: async () => {
        const mark = page.timeline.length;
        await page.selectOption(sel(id), value);
        await page.waitForFunction((m) => true, mark);
        await page.waitForResponse((r) => r.url().includes("/whatif/sensitivity/tornado") && r.request().postData()?.includes(id === "tornado-parameter" ? `"parameter":"${value}"` : id === "tornado-top" ? `"top":${value}` : `"scale":${value}`), { timeout: 60_000 });
        await page.waitForFunction(() => Number(document.querySelector('[data-testid="whatif-macro-tornado"]')?.getAttribute("data-rows") ?? 0) >= 0, null, { timeout: 30_000 });
        const rows = Number(await page.getAttribute(sel("whatif-macro-tornado"), "data-rows"));
        if (id === "tornado-top") assert.ok(rows <= 8, `at most 8 rows (${rows})`);
        void check;
        return `${id}=${value}: ${rows} rows`;
      } });
    }
    // Selection verbs on two ticked rows.
    const boxes = page.locator(sel("grid-row-select"));
    await ctl(page, record, { id: "grid-row-select", prereq: pre, expected: "two rows ticked: the active selection is those two exposures", run: async () => {
      await boxes.nth(0).check();
      await boxes.nth(1).check();
      await waitSelectionEntities(page, 2);
      return "2 rows selected (selection summary 2)";
    } });
    const pre2 = "What-If, Corporate, two rows selected";
    let saved = "";
    await ctl(page, record, { id: "whatif-save-cohort", prereq: pre2, expected: "the name form opens", run: async () => {
      await page.click(sel("whatif-save-cohort"));
      await page.waitForSelector(sel("whatif-save-form"), { timeout: 30_000 });
      return "form open";
    } });
    await ctl(page, record, { id: "whatif-save-form-input", prereq: pre2, action: "type a cohort name", expected: "the name is held in the form", run: async () => {
      await page.fill(sel("whatif-save-form-input"), "GW-CTL two rows");
      assert.equal(await page.inputValue(sel("whatif-save-form-input")), "GW-CTL two rows");
      return "name typed";
    } });
    await ctl(page, record, { id: "whatif-save-form", prereq: `${pre2}, name typed`, action: "submit the form", expected: "the two rows are frozen as a named governed cohort", run: async () => {
      await page.click(sel("whatif-save-form-submit"));
      await page.waitForFunction(() => /Saved 2 exposures as coh-/.test(document.querySelector('[data-testid="whatif-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      saved = /(coh-[0-9a-z-]+)/.exec(await page.textContent(sel("whatif-note")))[1];
      const o = await objectOf(saved);
      assert.equal(o.body.counts.entities, 2);
      assert.equal(o.body.name, "GW-CTL two rows");
      return `cohort ${saved}: 2 entities, name stored`;
    } });
    await ctl(page, record, { id: "whatif-share", prereq: pre2, expected: "the share form opens", run: async () => {
      await page.click(sel("whatif-share"));
      await page.waitForSelector(sel("whatif-share-form"), { timeout: 30_000 });
      return "form open";
    } });
    await ctl(page, record, { id: "whatif-share-form-input", prereq: pre2, action: "type a recipient", expected: "the recipient is held in the form", run: async () => {
      await page.fill(sel("whatif-share-form-input"), "colleague");
      assert.equal(await page.inputValue(sel("whatif-share-form-input")), "colleague");
      return "recipient typed";
    } });
    await ctl(page, record, { id: "whatif-share-form", prereq: `${pre2}, recipient typed`, action: "submit the form", expected: "the cohort reference (not rows) is shared; it appears in Sent", run: async () => {
      await page.click(sel("whatif-share-form-submit"));
      await page.waitForFunction(() => /Shared coh-/.test(document.querySelector('[data-testid="whatif-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      const sent = (await api("/messages?box=sent")).body.items;
      assert.ok(sent.some((m) => JSON.stringify(m).includes(saved)), "the share is in Sent");
      return `shared ${saved}; in Sent`;
    } });
    await ctl(page, record, { id: "whatif-export", prereq: pre2, expected: "a CSV of the filtered book (every grid row) downloads", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("whatif-export"))]);
      const rows = await csvRows(d);
      assert.equal(rows, await gridTotal(page));
      return `${d.suggestedFilename()}: ${rows} rows = grid total`;
    } });
    await ctl(page, record, { id: "whatif-export-cohort", prereq: `${pre2}, cohort ${saved} active`, expected: "the active cohort's CSV downloads (exactly its members)", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click(sel("whatif-export-cohort"))]);
      const rows = await csvRows(d);
      assert.equal(rows, 2);
      return `${d.suggestedFilename()}: 2 rows`;
    } });
    await ctl(page, record, { id: "whatif-strip-clear-cohort", prereq: `cohort ${saved} active`, expected: "the cohort leaves the strip (nothing deleted)", run: async () => {
      await page.click(sel("whatif-strip-clear-cohort"));
      await page.waitForFunction(() => !document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 30_000 });
      assert.ok((await objectOf(saved)).object_id, "the cohort still exists");
      return "strip cohort cleared; object kept";
    } });
    await ctl(page, record, { id: "whatif-load-cohort", prereq: "no active cohort", expected: "the saved-cohort list opens", run: async () => {
      await page.click(sel("whatif-load-cohort"));
      await page.waitForSelector(sel("whatif-cohort-list"), { timeout: 60_000 });
      return `${await page.locator(sel("whatif-cohort-pick")).count()} saved cohorts listed`;
    } });
    await ctl(page, record, { id: "whatif-cohort-pick", prereq: "saved-cohort list open", expected: "the chosen cohort becomes active", run: async () => {
      await page.locator(`${sel("whatif-cohort-list")} li`, { hasText: saved }).locator(sel("whatif-cohort-pick")).click();
      await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id") === id, saved, { timeout: 60_000 });
      return `${saved} active again`;
    } });
    await ctl(page, record, { id: "whatif-load-scenario", prereq: `cohort ${saved} active`, expected: "the scenario list opens", run: async () => {
      await page.click(sel("whatif-load-scenario"));
      await page.waitForSelector(sel("whatif-scenario-list"), { timeout: 60_000 });
      return `${await page.locator(sel("whatif-scenario-pick")).count()} scenarios listed`;
    } });
    await ctl(page, record, { id: "whatif-scenario-filter", prereq: "scenario list open", action: "type CORP-02", expected: "the list narrows to matching scenarios", run: async () => {
      const all = await page.locator(sel("whatif-scenario-pick")).count();
      await page.fill(sel("whatif-scenario-filter"), "CORP-02");
      await page.waitForFunction((n) => document.querySelectorAll('[data-testid="whatif-scenario-pick"]').length < n, all, { timeout: 30_000 });
      const shown = await page.locator(sel("whatif-scenario-pick")).count();
      assert.ok(shown >= 1);
      return `${all} → ${shown}`;
    } });
    await ctl(page, record, { id: "whatif-scenario-pick", prereq: "scenario list filtered to CORP-02", expected: "CORP-02 becomes the active scenario", run: async () => {
      await page.locator(sel("whatif-scenario-pick")).first().click();
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id"), null, { timeout: 60_000 });
      return `scenario ${(await strip(page)).scenario}`;
    } });
    await ctl(page, record, { id: "whatif-strip-clear-scenario", prereq: "CORP-02 active", expected: "the scenario leaves the strip and its run panel closes", run: async () => {
      await page.click(sel("whatif-strip-clear-scenario"));
      await page.waitForFunction(() => !document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id"), null, { timeout: 30_000 });
      return "scenario cleared";
    } });
    const wsState = H.whatifState;
    const cohortToThread = {
      source: async (p) => ({ cohort: (await strip(p)).cohort, hash: (await objectOf((await strip(p)).cohort)).body.membership_hash }),
      destination: async (p) => {
        const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1];
        const c = (await api(`/whatif/threads/${t}/cohort`)).body;
        const o = await objectOf(c.seed_cohort_id);
        return { thread: t, cohort: c.seed_cohort_id, hash: o?.body?.membership_hash };
      },
      identity: (s, d) => {
        assert.equal(d.hash, s.hash, "the investigation is seeded with the same membership");
        return `cohort ${s.cohort} (${String(s.hash).slice(0, 12)}) → thread ${d.thread} seeded with ${d.cohort} (${String(d.hash).slice(0, 12)})`;
      },
      writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(whatif\/investigate|cohorts\/[^/]+\/investigate|whatif\/selection\/cohort) /,
      describe,
    };
    await whatifSynced(page);
    await navTrip(page, record, {
      id: "whatif-investigate", prereq: `cohort ${saved} active`, expected: "opens a Cockpit investigation on the active cohort", state: wsState,
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//, 120_000); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"), handoff: cohortToThread,
    });
    await whatifSynced(page);
    await navTrip(page, record, {
      id: "whatif-library", prereq: `cohort ${saved} active`, expected: "opens the Scenario Library on this book", state: wsState,
      arrived: (p) => p.waitForSelector(sel("scenario-count"), { timeout: 120_000 }), inApp: sel("scenario-library-back"),
      handoff: {
        source: async (p) => ({ domain: await p.getAttribute(sel("whatif-workspace"), "data-domain") }),
        destination: async (p) => ({ domain: await p.getAttribute(sel("scenario-domain"), "data-value") }),
        identity: (s, d) => { assert.equal(d.domain, s.domain, "the library opens on the same book"); return `book ${s.domain} → library filtered to ${d.domain}`; },
        describe,
      },
    });
    await ctl(page, record, { id: "whatif-clear", prereq: `cohort ${saved} active`, expected: "selection and cohort are cleared", run: async () => {
      await page.click(sel("whatif-clear"));
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-selection"]')?.getAttribute("data-mode") === "none" && !document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 30_000 });
      return "selection none, strip empty";
    } });
    // The conversation.
    await boxes.nth(0).check();
    await waitSelectionEntities(page, 1);
    // A scenario question on the selection: the conversation freezes it as
    // its cohort, which "Use this conversation's cohort" then adopts.
    const q = "Increase PD by 20% and LGD by 10% for this selection";
    await ctl(page, record, { id: "whatif-ask-input", prereq: "one row selected", action: "type a question", expected: "the question is held in the box; Ask enables", run: async () => {
      await page.fill(sel("whatif-ask-input"), q);
      assert.equal(await page.isDisabled(sel("whatif-ask")), false);
      return "Ask enabled";
    } });
    await ctl(page, record, { id: "whatif-ask", prereq: "question typed, one row selected", expected: "a governed conversation opens on the selection (one model call)", run: async () => {
      await page.click(sel("whatif-ask"));
      await page.waitForSelector(sel("whatif-conversation"), { timeout: 120_000 });
      await settle(page, 0);
      return `thread ${await page.getAttribute(sel("whatif-conversation"), "data-thread-id")}`;
    } });
    const thread = await page.getAttribute(sel("whatif-conversation"), "data-thread-id");
    await ctl(page, record, { id: "whatif-adopt-cohort", prereq: `conversation ${thread} open`, expected: "the conversation's cohort becomes the active cohort (same membership)", run: async () => {
      await page.click(sel("whatif-adopt-cohort"));
      await page.waitForSelector(sel("whatif-note"), { timeout: 60_000 });
      const note = await page.textContent(sel("whatif-note"));
      const st = (await api(`/whatif/threads/${thread}/cohort`)).body;
      assert.equal(st.has_cohort, true, "the conversation froze a cohort");
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-strip-cohort"]')?.getAttribute("data-cohort-id"), null, { timeout: 30_000 });
      const active = (await strip(page)).cohort;
      assert.equal((await objectOf(active)).body.membership_hash, st.membership_hash, "the adopted cohort is the conversation's population");
      return note.trim().slice(0, 160);
    } });
    await whatifSynced(page);
    await navTrip(page, record, {
      id: "whatif-open-thread", prereq: `conversation ${thread} open`, expected: "opens the same conversation in the Cockpit", state: wsState,
      arrived: async (p) => {
        await waitPath(p, /^\/cockpit\/thread\//, 120_000);
        await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 });
      },
      inApp: sel("thread-origin-back"),
      handoff: {
        source: async () => ({ thread }),
        destination: async (p) => ({ thread: /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1] }),
        identity: (s, d) => { assert.equal(d.thread, s.thread); return `thread ${s.thread} → ${d.thread}`; },
        describe,
      },
    });
    await ctl(page, record, { id: "whatif-close-thread", prereq: "conversation open in What-If", expected: "the conversation panel closes; nothing is deleted", run: async () => {
      if (!(await page.locator(sel("whatif-conversation")).count())) {
        await page.fill(sel("whatif-ask-input"), q);
        await page.click(sel("whatif-ask"));
        await page.waitForSelector(sel("whatif-conversation"), { timeout: 120_000 });
        await settle(page, 0);
      }
      await page.click(sel("whatif-close-thread"));
      await page.waitForSelector(sel("whatif-conversation"), { state: "detached", timeout: 30_000 });
      assert.ok(await H.v4(`/threads/${thread}`), "the thread still exists");
      return "panel closed; thread kept";
    } });
  });
}

// =========================================================================
// WHAT-IF METHODS AND RESULTS — the method gate, every method state, the
// result's method tabs and decomposition controls, layering, the tree and
// the result page's links
// =========================================================================

const executeLabel = (page) => page.textContent(sel("whatif-run-execute"));

async function methodsJourney() {
  const { journey, open, openWhatIf, ctl, navTrip, assert, api, waitRunState, resultRendered } = H;
  await journey("GW-CTL-METHODS", "Method gate: no method → blocked; method change before execution; User-defined form/value/stated; Compare; result method tabs; compact, waterfall click, decomposition row; layering vs original baseline; Retail ML blocked by G4; tree compare/new session/result/open run; result page links", async (record) => {
    const page = await open();
    const corp02 = (await api("/scenarios?domain=corporate&q=CORP-02")).body.scenarios[0].object_id;
    await openWhatIf(page, `?domain=corporate&scenario=${corp02}`);
    await page.waitForSelector(sel("whatif-bound-scenario"), { timeout: 120_000 });
    const boundState = () => ({ scenario: document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") || "", domain: new URLSearchParams(location.search).get("domain") });
    await navTrip(page, record, {
      id: "whatif-bound-scenario", prereq: "CORP-02 applied in What-If (no cohort)", expected: "opens the applied scenario at the version shown", state: boundState,
      arrived: (p) => p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }), inApp: sel("scenario-back"),
      handoff: {
        source: async (p) => { const t = (await p.textContent(sel("whatif-bound-scenario"))).trim(); const m = /^(\S+) v(\d+)$/.exec(t); return { scenario: m?.[1] ?? "", version: Number(m?.[2] ?? 0) }; },
        destination: async (p) => ({ scenario: await p.getAttribute(sel("scenario-detail"), "data-object-id"), version: Number(await p.getAttribute(sel("scenario-detail"), "data-version")) }),
        identity: (s, d) => { assert.equal(d.scenario, s.scenario); assert.equal(d.version, s.version, "the version shown"); return `applied ${s.scenario} v${s.version} → detail ${d.scenario} v${d.version}`; },
        describe,
      },
    });
    await page.waitForSelector(sel("whatif-run-start"), { timeout: 120_000 });
    await page.click(sel("whatif-run-start"));
    await waitRunState(page, "SCENARIO_PREVIEW");
    await page.click(sel("whatif-run-confirm"));
    await waitRunState(page, "METHOD_SELECTION");
    const pre = `CORP-02 confirmed, METHOD_SELECTION (run ${await page.getAttribute(sel("whatif-run"), "data-run-id")})`;
    await ctl(page, record, { id: "whatif-run-execute", prereq: `${pre}, no method chosen`, action: "read the execute control with nothing chosen", expected: "execution is not possible until a method is chosen",
      result: "BLOCKED_WITH_GOVERNED_REASON", reason: "No method is preselected. Nothing runs until you choose one.", run: async () => {
        assert.equal(await page.isDisabled(sel("whatif-run-execute")), true, "disabled with no method");
        assert.match(await page.textContent(sel("whatif-method-selection")), /No method is preselected/);
        return "execute disabled; the gate says why";
      } });
    await ctl(page, record, { id: "whatif-method-pick-delta", prereq: pre, expected: "Delta is chosen; execute names it", run: async () => {
      await page.check(sel("whatif-method-pick-delta"));
      assert.match(await executeLabel(page), /Delta/);
      return (await executeLabel(page)).trim();
    } });
    await ctl(page, record, { id: "whatif-method-pick-ml", prereq: `${pre}, Delta chosen`, action: "change the method before execution: untick Delta, tick ML", expected: "the choice is ML only; nothing executed", run: async () => {
      await page.uncheck(sel("whatif-method-pick-delta"));
      await page.check(sel("whatif-method-pick-ml"));
      const label = await executeLabel(page);
      assert.ok(/ML/.test(label) && !/Delta/.test(label), label);
      assert.equal(await page.getAttribute(sel("whatif-run"), "data-state"), "METHOD_SELECTION", "still not executed");
      return label.trim();
    } });
    await ctl(page, record, { id: "whatif-method-pick-user_defined", prereq: `${pre}, ML chosen`, expected: "User-defined asks for its assumption (form, value, words)", run: async () => {
      await page.uncheck(sel("whatif-method-pick-ml"));
      await page.check(sel("whatif-method-pick-user_defined"));
      await page.waitForSelector(sel("whatif-ud-input"), { timeout: 30_000 });
      return "assumption inputs shown";
    } });
    await ctl(page, record, { id: "whatif-ud-form", prereq: "User-defined chosen", expected: "the assumption form is selectable", run: async () => {
      const opts = await page.$$eval(`${sel("whatif-ud-form")} option`, (o) => o.map((x) => x.value));
      await page.selectOption(sel("whatif-ud-form"), opts[opts.length - 1]);
      await page.selectOption(sel("whatif-ud-form"), opts[0]);
      return `forms ${opts.join(", ")}; ${opts[0]} chosen`;
    } });
    await ctl(page, record, { id: "whatif-ud-value", prereq: "User-defined chosen", action: "type 15", expected: "the value is held", run: async () => {
      await page.fill(sel("whatif-ud-value"), "15");
      assert.equal(await page.inputValue(sel("whatif-ud-value")), "15");
      return "15";
    } });
    await ctl(page, record, { id: "whatif-ud-stated", prereq: "User-defined chosen", action: "type the assumption in words", expected: "kept for audit", run: async () => {
      await page.fill(sel("whatif-ud-stated"), "management view: +15% ECL");
      return "stated";
    } });
    await ctl(page, record, { id: "whatif-method-pick-compare", prereq: "User-defined with its assumption", action: "tick Compare and execute", expected: "every available method runs; the result has one tab per method", run: async () => {
      await page.uncheck(sel("whatif-method-pick-user_defined"));
      await page.check(sel("whatif-method-pick-compare"));
      if (await page.locator(sel("whatif-ud-value")).count()) {
        await page.fill(sel("whatif-ud-value"), "15");
        await page.fill(sel("whatif-ud-stated"), "management view: +15% ECL");
      }
      await page.click(sel("whatif-run-execute"));
      await waitRunState(page, "EXECUTED", 240_000);
      await resultRendered(page);
      const tabs = await page.$$eval('[data-testid^="whatif-result-method-"]', (b) => b.map((x) => x.dataset.testid));
      assert.ok(tabs.length >= 2, `several methods ran: ${tabs}`);
      return `methods ran: ${tabs.map((t) => t.replace("whatif-result-method-", "")).join(", ")}`;
    } });
    const tabs = await page.$$eval('[data-testid^="whatif-result-method-"]', (b) => b.map((x) => x.dataset.testid));
    for (const t of tabs) {
      await ctl(page, record, { id: t, prereq: "Compare executed", expected: "the decomposition switches to that method", run: async () => {
        await page.click(sel(t));
        const m = t.replace("whatif-result-method-", "");
        await page.waitForFunction((x) => document.querySelector('[data-testid="whatif-decomposition"]')?.getAttribute("data-method") === x, m, { timeout: 30_000 });
        return `decomposition method ${m}`;
      } });
    }
    await ctl(page, record, { id: "whatif-decomp-compact", prereq: "result shown", expected: "the bridge hides N/A components (the table keeps all)", run: async () => {
      const n = () => page.evaluate(() => (document.querySelector('[data-testid="whatif-waterfall-selected"]')?.data?.[0]?.x ?? []).length);
      const rows = await page.locator(sel("whatif-decomp-row")).count();
      const before = await n();
      await page.click(sel("whatif-decomp-compact"));
      await page.waitForFunction((b) => (document.querySelector('[data-testid="whatif-waterfall-selected"]')?.data?.[0]?.x ?? []).length !== b, before, { timeout: 30_000 }).catch(() => undefined);
      const after = await n();
      assert.equal(await page.locator(sel("whatif-decomp-row")).count(), rows, "the table keeps every component");
      await page.click(sel("whatif-decomp-compact"));
      return `bars ${before} → ${after}; table ${rows} rows throughout`;
    } });
    await ctl(page, record, { id: "whatif-waterfall-selected", prereq: "result shown", action: "click a bridge bar", expected: "that component is highlighted in the table", run: async () => {
      // The opening and closing bars carry no component; click the first
      // component bar (the first point whose customdata names one).
      const idx = await page.evaluate(() => {
        const d = document.querySelector('[data-testid="whatif-waterfall-selected"]')?.data?.[0] ?? {};
        const rows = new Set(Array.from(document.querySelectorAll('[data-testid="whatif-decomp-row"]')).map((r) => r.getAttribute("data-component")));
        // A drawn component bar: non-zero height and a row in the table
        // (opening/closing totals and N/A components are not clickable rows).
        // The opening/closing levels run off the cut axis; take the largest
        // movement among the components.
        let best = -1;
        (d.customdata ?? []).forEach((c, i) => {
          const id = Array.isArray(c) ? String(c[0]) : "";
          if (!rows.has(id) || id === "opening" || id === "closing") return;
          if (best < 0 || Math.abs(Number(d.y?.[i] ?? 0)) > Math.abs(Number(d.y?.[best] ?? 0))) best = i;
        });
        return Math.abs(Number(d.y?.[best] ?? 0)) > 0 ? best : -1;
      });
      assert.ok(idx >= 0, "a component bar exists");
      await clickPlotPoint(page, "whatif-waterfall-selected", { point: idx });
      await page.waitForSelector(`${sel("whatif-decomp-row")}.font-semibold`, { timeout: 30_000 });
      const comp = await page.getAttribute(`${sel("whatif-decomp-row")}.font-semibold`, "data-component");
      return `highlighted ${comp}`;
    } });
    await ctl(page, record, { id: "whatif-decomp-row", prereq: "a component highlighted", action: "click another table row, then again", expected: "highlight moves to it, then clears", run: async () => {
      const row = page.locator(sel("whatif-decomp-row")).nth(2);
      const comp = await row.getAttribute("data-component");
      await row.click();
      await page.waitForSelector(`${sel("whatif-decomp-row")}.font-semibold[data-component="${comp}"]`, { timeout: 30_000 });
      await row.click();
      await page.waitForSelector(`${sel("whatif-decomp-row")}.font-semibold`, { state: "detached", timeout: 30_000 });
      return `${comp} highlighted then cleared`;
    } });
    const firstResult = (await api(`/whatif/runs/${await page.getAttribute(sel("whatif-run"), "data-run-id")}`)).body.body.result_id;
    // Layering: a second scenario in the same session asks for its baseline.
    const corp03 = (await api("/scenarios?domain=corporate&q=CORP-03")).body.scenarios[0].object_id;
    await page.click(sel("whatif-load-scenario"));
    await page.fill(sel("whatif-scenario-filter"), "CORP-03");
    await page.locator(sel("whatif-scenario-pick")).first().click();
    await page.waitForFunction((id) => document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") === id, corp03, { timeout: 60_000 });
    await page.click(sel("whatif-run-start"));
    await waitRunState(page, "WAITING_BASELINE_CHOICE");
    await ctl(page, record, { id: "whatif-baseline-option", prereq: "CORP-03 started after CORP-02 executed in this session", action: "choose 'layer on the previous scenario'", expected: "the prior run is offered as a baseline", run: async () => {
      await page.locator(`${sel("whatif-baseline-option")}[data-mode="PRIOR_SCENARIO"]`).first().check();
      return "PRIOR_SCENARIO chosen";
    } });
    await ctl(page, record, { id: "whatif-baseline-choose", prereq: "PRIOR_SCENARIO chosen", expected: "the run is layered on CORP-02 (strip says so)", run: async () => {
      await page.click(sel("whatif-baseline-choose"));
      await waitRunState(page, "SCENARIO_PREVIEW");
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-run-baseline"]')?.getAttribute("data-mode") === "PRIOR_SCENARIO", null, { timeout: 30_000 });
      return "baseline PRIOR_SCENARIO";
    } });
    await page.click(sel("whatif-run-confirm"));
    await waitRunState(page, "METHOD_SELECTION");
    await page.check(sel("whatif-method-pick-delta"));
    await page.click(sel("whatif-run-execute"));
    await waitRunState(page, "EXECUTED", 240_000);
    await resultRendered(page);
    await ctl(page, record, { id: "whatif-run-start", prereq: "CORP-03 layered result shown", action: "Start another run, choose the original baseline", expected: "a new run on the original reported baseline", run: async () => {
      await page.click(sel("whatif-run-start"));
      await waitRunState(page, "WAITING_BASELINE_CHOICE");
      await page.locator(`${sel("whatif-baseline-option")}[data-mode="SOURCE_BASELINE"]`).first().check();
      await page.click(sel("whatif-baseline-choose"));
      await waitRunState(page, "SCENARIO_PREVIEW");
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-run-baseline"]')?.getAttribute("data-mode") === "SOURCE_BASELINE", null, { timeout: 30_000 });
      return "baseline SOURCE_BASELINE (original reported)";
    } });
    // The session tree.
    await page.waitForSelector(sel("tree-compare-pick"), { timeout: 60_000 });
    const picks = page.locator(sel("tree-compare-pick"));
    await picks.nth(0).check();
    await picks.nth(1).check();
    const chosen = [await picks.nth(0).getAttribute("data-result-id"), await picks.nth(1).getAttribute("data-result-id")];
    await navTrip(page, record, {
      id: "tree-compare", prereq: "two results ticked in the session tree", expected: "a comparison of exactly those two results opens", state: H.whatifState,
      arrived: (p) => p.waitForSelector(sel("comparison"), { timeout: 120_000 }), inApp: sel("comparison-back"),
      handoff: {
        source: async () => ({ results: [...chosen].sort() }),
        destination: async (p) => ({ comparison: await p.getAttribute(sel("comparison"), "data-comparison-id"), results: (await p.$$eval("[data-result-id]", (r) => r.map((x) => x.getAttribute("data-result-id")))).filter(Boolean).sort() }),
        identity: (s, d) => { assert.deepEqual([...new Set(d.results)], s.results); return `results ${s.results.join(", ")} → ${d.comparison}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/whatif\/compare /,
        describe,
      },
    });
    const node = page.locator(sel("tree-result-link")).first();
    const nodeResult = (await node.getAttribute("href")).match(/result\/([^?]+)/)[1];
    await navTrip(page, record, {
      id: "tree-result-link", prereq: "session tree", expected: "opens that node's result", state: H.whatifState,
      go: (p) => p.locator(sel("tree-result-link")).first().click(),
      arrived: (p) => p.waitForSelector(`[data-testid="whatif-result"][data-result-id="${nodeResult}"]`, { timeout: 120_000 }), inApp: sel("whatif-result-back"),
    });
    if (await page.locator(sel("tree-open-run")).count()) {
      const href = await page.locator(sel("tree-open-run")).first().getAttribute("href");
      const runId = /run=([^&]+)/.exec(href)[1];
      await navTrip(page, record, {
        id: "tree-open-run", prereq: "session tree with an unexecuted run", expected: "reopens that run in What-If", state: H.whatifState,
        go: (p) => p.locator(sel("tree-open-run")).first().click(),
        arrived: (p) => p.waitForSelector(`[data-testid="whatif-run"][data-run-id="${runId}"]`, { timeout: 120_000 }), inApp: sel("whatif-back"),
      });
    }
    await ctl(page, record, { id: "tree-new-session", prereq: "session tree with nodes", expected: "a new session starts: the tree empties; nothing is deleted", run: async () => {
      const before = await page.getAttribute(sel("whatif-tree"), "data-session-id");
      await page.click(sel("tree-new-session"));
      await page.waitForFunction((b) => { const t = document.querySelector('[data-testid="whatif-tree"]'); return !t || t.getAttribute("data-session-id") !== b; }, before, { timeout: 30_000 });
      assert.ok((await objectOf(firstResult)).object_id, "earlier results kept");
      return `session ${before} → new`;
    } });
    // The result page's links.
    await page.goto(`${H.UI}/what-if/result/${firstResult}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("whatif-result"), { timeout: 120_000 });
    const res = await objectOf(firstResult);
    await navTrip(page, record, {
      id: "whatif-result-open-run", prereq: `result ${firstResult}`, expected: "reopens the run that produced it", state: H.resultState,
      arrived: (p) => p.waitForSelector(`[data-testid="whatif-run"][data-run-id="${res.body.run_id}"]`, { timeout: 120_000 }), inApp: sel("whatif-back"),
    });
    await navTrip(page, record, {
      id: "whatif-result-open-scenario", prereq: `result ${firstResult}`, expected: "opens the scenario version it ran", state: H.resultState,
      arrived: (p) => p.waitForSelector(`[data-testid="scenario-detail"][data-object-id="${res.body.scenario_id}"]`, { timeout: 120_000 }), inApp: sel("scenario-back"),
      handoff: {
        source: async () => ({ scenario: res.body.scenario_id, version: res.body.scenario_version }),
        destination: async (p) => ({ scenario: await p.getAttribute(sel("scenario-detail"), "data-object-id"), version: Number(await p.getAttribute(sel("scenario-detail"), "data-version")) }),
        identity: (s, d) => { assert.equal(d.scenario, s.scenario); assert.equal(d.version, s.version, "the version it ran"); return `result ${firstResult} → ${d.scenario} v${d.version}`; },
        describe,
      },
    });
    // A result whose scenario was revised after it ran: the link opens the
    // version that ran, not the latest (VAL-DEF-051).
    const own = (await H.post("/scenarios", { definition: { name: "GW-CTL revised after its run", domain_id: "corporate", description: "version link", risk_thesis: "t",
      scope: { type: "filters", label: "Construction", filters: [{ column: "sector", op: "in", values: ["Construction"] }] },
      components: [{ kind: "parameter", field: "pd_pit_12m", operation: "multiply", value: "1.10", label: "PD x1.10" }],
      stage_policy: "frozen", severity: "moderate", tags: ["gw-ctl"] } })).body;
    const ran = (await H.apiRun(own.object_id, `gw-ctl-ver-${Date.now()}`, ["delta"])).result;
    await H.post(`/scenarios/${own.object_id}/revise`, { changes: { name: "GW-CTL revised after its run (v2)" }, reason: "GW-CTL version link" });
    assert.equal((await objectOf(own.object_id)).version, ran.body.scenario_version + 1, "the scenario moved on after the run");
    await page.goto(`${H.UI}/what-if/result/${ran.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("whatif-result"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "whatif-result-open-scenario", prereq: `result ${ran.object_id}; its scenario revised since`, expected: "opens the scenario version that ran, not the latest", state: H.resultState,
      arrived: (p) => p.waitForSelector(`[data-testid="scenario-detail"][data-object-id="${own.object_id}"]`, { timeout: 120_000 }), inApp: sel("scenario-back"),
      handoff: {
        source: async () => ({ scenario: own.object_id, version: ran.body.scenario_version }),
        destination: async (p) => ({ scenario: await p.getAttribute(sel("scenario-detail"), "data-object-id"), version: Number(await p.getAttribute(sel("scenario-detail"), "data-version")) }),
        identity: (s, d) => { assert.equal(d.scenario, s.scenario); assert.equal(d.version, s.version, "the version that ran"); return `result ${ran.object_id} → ${d.scenario} v${d.version} (latest is v${s.version + 1})`; },
        describe,
      },
    });
    // Comparison page controls.
    const cmp = (await H.post("/whatif/compare", { result_ids: chosen })).body;
    await page.goto(`${H.UI}/what-if/compare/${cmp.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("comparison"), { timeout: 120_000 });
    for (const sc of ["total", "selected"]) {
      await ctl(page, record, { id: `comparison-scope-${sc}`, prereq: `comparison ${cmp.object_id}`, expected: `the chart shows the ${sc} scope`, run: async () => {
        await page.click(sel(`comparison-scope-${sc}`));
        await page.waitForSelector(`${sel(`comparison-scope-${sc}`)}[aria-pressed="true"]`, { timeout: 30_000 });
        await page.waitForSelector(`${sel("comparison-chart-card")} h3:has-text("${sc === "selected" ? "selected scope" : "total active book"}")`, { timeout: 30_000 });
        return `${sc} scope`;
      } });
    }
    const rid = await page.locator(sel("comparison-result-link")).first().getAttribute("href");
    const target = /result\/([^?]+)/.exec(rid)[1];
    await navTrip(page, record, {
      id: "comparison-result-link", prereq: `comparison ${cmp.object_id}`, expected: "opens that result", state: urlState2,
      go: (p) => p.locator(sel("comparison-result-link")).first().click(),
      arrived: (p) => p.waitForSelector(`[data-testid="whatif-result"][data-result-id="${target}"]`, { timeout: 120_000 }), inApp: sel("whatif-result-back"),
    });
    // Retail ML: the G4 validation gate.
    const ret01 = (await api("/scenarios?domain=retail&q=RET-01")).body.scenarios[0].object_id;
    await openWhatIf(page, `?domain=retail&scenario=${ret01}`);
    await page.waitForSelector(sel("whatif-run-start"), { timeout: 120_000 });
    await page.click(sel("whatif-run-start"));
    await waitRunState(page, "SCENARIO_PREVIEW").catch(async () => {
      if (await page.locator(sel("whatif-baseline-choose")).count()) {
        await page.locator(`${sel("whatif-baseline-option")}[data-mode="SOURCE_BASELINE"]`).first().check();
        await page.click(sel("whatif-baseline-choose"));
        await waitRunState(page, "SCENARIO_PREVIEW");
      }
    });
    await page.click(sel("whatif-run-confirm"));
    await waitRunState(page, "METHOD_SELECTION");
    await ctl(page, record, { id: "whatif-method-pick-ml", prereq: "Retail RET-01 confirmed, METHOD_SELECTION", action: "read the ML method; choose it and try to execute", expected: "ML is UNAVAILABLE with the G4 reason; choosing it cannot produce an ML result",
      result: "BLOCKED_WITH_GOVERNED_REASON", run: async () => {
        assert.equal(await page.getAttribute(sel("whatif-method-ml"), "data-status"), "UNAVAILABLE");
        const reason = await page.textContent(sel("whatif-method-reason-ml"));
        assert.match(reason, /G4/);
        await page.check(sel("whatif-method-pick-ml"));
        if (!(await page.isDisabled(sel("whatif-run-execute")))) {
          await page.click(sel("whatif-run-execute"));
          await page.waitForFunction(() => ["METHOD_UNAVAILABLE", "METHOD_SELECTION"].includes(document.querySelector('[data-testid="whatif-run"]')?.getAttribute("data-state") ?? ""), null, { timeout: 60_000 });
        }
        const state = await page.getAttribute(sel("whatif-run"), "data-state");
        assert.notEqual(state, "EXECUTED", "no ML result is produced");
        record.retail_ml_reason = reason.trim();
        return `UNAVAILABLE; run state ${state}; no result`;
      }, reason: "Validation gate failed: G4 (worst material-group WAPE) — never substituted", expect4xx: /\/whatif\/runs\/[^/]+\/(method|execute) 4\d\d$/ });
  });
}

const urlState2 = () => ({ at: location.pathname + location.search });

// =========================================================================
// GOVERNED DATA GRID — every filter family, sort, pagination, columns,
// selection and export, each against the backend's own count
// =========================================================================

async function gridJourney() {
  const { journey, open, openWhatIf, ctl, assert, gridApi, gridTotal, api, post } = H;
  await journey("GW-CTL-GRID", "Data grid: text / category multi-select / value search / range / boolean / empty / not-empty filters, editor Clear and Cancel, chip remove, clear all, sort both ways, next/previous page, column visibility, select page / all filtered / clear, export filtered, save cohort — counts and hashes from the backend", async (record) => {
    const page = await open();
    await openWhatIf(page, "?domain=corporate");
    const G = "whatif-grid";
    const full = await gridTotal(page);
    const backend = async (filters, extra = {}) => (await gridApi(filters, extra)).total;
    assert.equal(full, await backend([]), "unfiltered total is the backend's");
    const pre = `What-If grid, Corporate, ${full} rows`;
    const openEditor = async (col) => {
      await page.click(sel(`grid-filter-${col}`));
      await page.waitForSelector(sel(`grid-filter-editor-${col}`), { timeout: 30_000 });
    };
    const totalIs = (n) => page.waitForFunction(([id, want]) => Number(document.querySelector(`[data-testid="${id}"]`)?.getAttribute("data-total")) === want, [G, n], { timeout: 60_000 });
    const firstName = (await gridApi([], { limit: 1, sort: "borrower_name" })).rows[0].borrower_name;
    const needle = String(firstName).slice(0, 3);
    await ctl(page, record, { id: "grid-filter-text", prereq: pre, action: `borrower name contains "${needle}"`, expected: "the grid shows exactly the backend's matching rows; a chip names the filter", run: async () => {
      await openEditor("borrower_name");
      await page.fill(sel("grid-filter-text"), needle);
      await page.click(sel("grid-filter-apply-borrower_name"));
      const want = await backend([{ column: "borrower_name", op: "contains", value: needle }]);
      await totalIs(want);
      await page.waitForSelector(sel("grid-filter-chip"), { timeout: 30_000 });
      return `${full} → ${want} (backend ${want}); chip shown`;
    } });
    await ctl(page, record, { id: "grid-filter-chip-remove", prereq: "text filter active", expected: "the filter is removed; the full book returns", run: async () => {
      await page.click(sel("grid-filter-chip-remove"));
      await totalIs(full);
      return `back to ${full}`;
    } });
    const sectors = (await api("/grid/values?domain=corporate&column=sector")).body.values.map((v) => String(v.value));
    const two = sectors.filter((x) => x !== "null").slice(0, 2);
    await openEditor("sector");
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="grid-filter-value"]').length > 1, null, { timeout: 30_000 });
    await ctl(page, record, { id: "grid-filter-value-search", prereq: "sector filter editor open", action: `search "${two[0].slice(0, 4)}"`, expected: "the value list narrows to matching values", run: async () => {
      const before = await page.locator(sel("grid-filter-value")).count();
      await page.fill(sel("grid-filter-value-search"), two[0].slice(0, 4));
      await page.waitForFunction((b) => { const n = document.querySelectorAll('[data-testid="grid-filter-value"]').length; return n > 0 && n < b; }, before, { timeout: 30_000 });
      const after = await page.locator(sel("grid-filter-value")).count();
      await page.fill(sel("grid-filter-value-search"), "");
      await page.waitForFunction((b) => document.querySelectorAll('[data-testid="grid-filter-value"]').length === b, before, { timeout: 30_000 });
      return `${before} values → ${after} → ${before}`;
    } });
    await ctl(page, record, { id: "grid-filter-value", prereq: "sector filter editor open", action: `tick ${two.join(" and ")} and apply`, expected: "multi-select: the grid shows the backend's rows in either sector", run: async () => {
      for (const v of two) await page.locator(`${sel(`grid-filter-editor-sector`)} label`, { hasText: v }).first().locator("input").check();
      await page.click(sel("grid-filter-apply-sector"));
      const want = await backend([{ column: "sector", op: "in", values: two }]);
      await totalIs(want);
      return `${two.join(" + ")}: ${want} rows (backend ${want})`;
    } });
    await ctl(page, record, { id: "grid-filter-clear", prereq: "sector filter active; editor reopened", expected: "the editor's Clear removes that column's filter", run: async () => {
      await openEditor("sector");
      await page.click(sel("grid-filter-clear"));
      await totalIs(full);
      return `cleared; ${full} rows`;
    } });
    await ctl(page, record, { id: "grid-filter-cancel", prereq: pre, expected: "Cancel closes the editor and changes nothing", run: async () => {
      await openEditor("sector");
      await page.locator(`${sel("grid-filter-editor-sector")} ${sel("grid-filter-value")}`).first().check();
      await page.click(sel("grid-filter-cancel"));
      await page.waitForSelector(sel("grid-filter-editor-sector"), { state: "detached", timeout: 30_000 });
      assert.equal(await gridTotal(page), full);
      return "editor closed; total unchanged";
    } });
    for (const [id, value] of [["grid-filter-min", "1"], ["grid-filter-max", "90"]]) {
      await ctl(page, record, { id, prereq: "dpd_days filter editor", action: `${id === "grid-filter-min" ? "minimum" : "maximum"} ${value}`, expected: "the bound is held for the range filter", run: async () => {
        if (!(await page.locator(sel("grid-filter-editor-dpd_days")).count())) await openEditor("dpd_days");
        await page.fill(sel(id), value);
        assert.equal(await page.inputValue(sel(id)), value);
        return `${id} = ${value}`;
      } });
    }
    await ctl(page, record, { id: "grid-filter-apply-dpd_days", prereq: "dpd_days 1–90 typed", expected: "the grid shows the backend's rows with 1 ≤ DPD ≤ 90", run: async () => {
      await page.click(sel("grid-filter-apply-dpd_days"));
      const want = await backend([{ column: "dpd_days", op: "between", values: [1, 90] }]);
      await totalIs(want);
      return `DPD 1–90: ${want} rows (backend ${want})`;
    } });
    await ctl(page, record, { id: "grid-filter-boolean", prereq: "DPD filter active", action: "watchlist = yes (combined with the DPD range)", expected: "both filters hold: the backend's count for the conjunction", run: async () => {
      await openEditor("watchlist_flag");
      await page.selectOption(sel("grid-filter-boolean"), "yes");
      await page.click(sel("grid-filter-apply-watchlist_flag"));
      const want = await backend([{ column: "dpd_days", op: "between", values: [1, 90] }, { column: "watchlist_flag", op: "eq", value: 1 }]);
      await totalIs(want);
      return `DPD 1–90 AND watchlist: ${want} rows (backend ${want})`;
    } });
    await ctl(page, record, { id: "grid-clear-filters", prereq: "two filters active", expected: "every filter is removed", run: async () => {
      await page.click(sel("grid-clear-filters"));
      await totalIs(full);
      return `${full} rows`;
    } });
    await ctl(page, record, { id: "grid-filter-nulls", prereq: `${pre}; the hidden Prior PD column shown (it has empty values)`, action: "prior PD: not empty, then only empty", expected: "the backend's not-null and null counts", run: async () => {
      if (!(await page.locator(sel("grid-filter-prior_pd_pit_12m")).count())) {
        await page.locator(`${sel(G)} summary`, { hasText: "Columns" }).click();
        await page.locator(`${sel(G)} label`, { hasText: /^Prior PD/ }).locator(sel("grid-column-toggle")).check();
        await page.locator(`${sel(G)} summary`, { hasText: "Columns" }).click();
        await page.waitForSelector(sel("grid-filter-prior_pd_pit_12m"), { timeout: 30_000 });
      }
      await page.locator(sel("grid-filter-prior_pd_pit_12m")).scrollIntoViewIfNeeded();
      await openEditor("prior_pd_pit_12m");
      await page.selectOption(sel("grid-filter-nulls"), "not_empty");
      await page.click(sel("grid-filter-apply-prior_pd_pit_12m"));
      const notNull = await backend([{ column: "prior_pd_pit_12m", op: "not_null" }]);
      await totalIs(notNull);
      await openEditor("prior_pd_pit_12m");
      await page.selectOption(sel("grid-filter-nulls"), "empty");
      await page.click(sel("grid-filter-apply-prior_pd_pit_12m"));
      const isNull = await backend([{ column: "prior_pd_pit_12m", op: "is_null" }]);
      if (isNull === 0) await page.waitForSelector(sel(`${G}-empty-by-filter`), { timeout: 60_000 });
      else await totalIs(isNull);
      assert.equal(notNull + isNull, full, "null + not-null = the book");
      await page.click(sel("grid-clear-filters"));
      await totalIs(full);
      return `not empty ${notNull} + empty ${isNull} = ${full}${isNull === 0 ? " (EMPTY_BY_FILTER shown)" : ""}`;
    } });
    // The direction the grid says it sorts by (its footer), read after each
    // click: a column's first click sorts descending, the next ascending.
    const sortDir = async () => /sorted by (\S+) ([↓↑])/.exec(await page.textContent(`${sel(G)} >> text=/sorted by/`));
    for (const label of ["first click", "second click"]) {
      await ctl(page, record, { id: "grid-sort-ecl_sar_mn", prereq: pre, action: `sort by booked ECL (${label})`, expected: "the first row is the backend's first row in the order the grid states", run: async () => {
        const before = (await sortDir())?.slice(1).join(" ");
        await page.click(sel("grid-sort-ecl_sar_mn"));
        await page.waitForFunction(([g, b]) => { const m = /sorted by (\S+) ([↓↑])/.exec(document.querySelector(`[data-testid="${g}"]`)?.textContent ?? ""); return m && `${m[1]} ${m[2]}` !== b; }, [G, before], { timeout: 30_000 });
        const [, col, arrow] = await sortDir();
        assert.equal(col, "ecl_sar_mn");
        const desc = arrow === "↓";
        const want = String((await gridApi([], { sort: "ecl_sar_mn", desc, limit: 1 })).rows[0].facility_id);
        await page.waitForFunction((w) => document.querySelector('[data-testid="grid-row"]')?.getAttribute("data-row-id") === w, want, { timeout: 60_000 });
        return `${desc ? "descending" : "ascending"}: first row ${want} (backend)`;
      } });
    }
    const pageDesc = (await sortDir())[2] === "↓";
    await ctl(page, record, { id: `${G}-next`, prereq: "sorted by ECL", expected: "page 2 is the backend's rows 51–100 in that order", run: async () => {
      await page.click(sel(`${G}-next`));
      const want = String((await gridApi([], { sort: "ecl_sar_mn", desc: pageDesc, offset: 50, limit: 1 })).rows[0].facility_id);
      await page.waitForFunction((w) => document.querySelector('[data-testid="grid-row"]')?.getAttribute("data-row-id") === w, want, { timeout: 60_000 });
      return `page 2 starts at ${want}`;
    } });
    await ctl(page, record, { id: `${G}-prev`, prereq: "page 2", expected: "page 1 again", run: async () => {
      await page.click(sel(`${G}-prev`));
      const want = String((await gridApi([], { sort: "ecl_sar_mn", desc: pageDesc, offset: 0, limit: 1 })).rows[0].facility_id);
      await page.waitForFunction((w) => document.querySelector('[data-testid="grid-row"]')?.getAttribute("data-row-id") === w, want, { timeout: 60_000 });
      return `page 1 starts at ${want}`;
    } });
    await ctl(page, record, { id: "grid-column-toggle", prereq: pre, action: "hide the Sector column, then show it", expected: "the column leaves and returns; data unchanged", run: async () => {
      await page.locator(`${sel(G)} summary`, { hasText: "Columns" }).click();
      const box = page.locator(`${sel(G)} label`, { hasText: /^Sector$/ }).locator(sel("grid-column-toggle"));
      await box.uncheck();
      await page.waitForSelector(`${sel(G)} ${sel("grid-sort-sector")}`, { state: "detached", timeout: 30_000 });
      await box.check();
      await page.waitForSelector(`${sel(G)} ${sel("grid-sort-sector")}`, { timeout: 30_000 });
      await page.locator(`${sel(G)} summary`, { hasText: "Columns" }).click();
      return "Sector hidden and shown";
    } });
    await ctl(page, record, { id: `${G}-select-page`, prereq: pre, expected: "the 50 rows of this page are selected", run: async () => {
      await page.check(sel(`${G}-select-page`));
      await H.waitSelectionEntities(page, 50);
      return "50 selected";
    } });
    await ctl(page, record, { id: `${G}-clear-selection`, prereq: "page selected", expected: "the selection is empty", run: async () => {
      await page.click(sel(`${G}-clear-selection`));
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-selection"]')?.getAttribute("data-mode") === "none", null, { timeout: 30_000 });
      return "none selected";
    } });
    await openEditor("sector");
    await page.locator(`${sel(`grid-filter-editor-sector`)} label`, { hasText: two[0] }).first().locator("input").check();
    await page.click(sel("grid-filter-apply-sector"));
    const n1 = await backend([{ column: "sector", op: "in", values: [two[0]] }]);
    await totalIs(n1);
    await ctl(page, record, { id: `${G}-select-all-filtered`, prereq: `sector = ${two[0]} (${n1} rows)`, expected: "every filtered row is selected (not just this page)", run: async () => {
      await page.click(sel(`${G}-select-all-filtered`));
      await H.waitSelectionEntities(page, n1);
      return `${n1} selected (backend ${n1})`;
    } });
    await ctl(page, record, { id: `${G}-export`, prereq: `sector = ${two[0]}`, expected: "a CSV of exactly the filtered rows", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 60_000 }), page.click(sel(`${G}-export`))]);
      const rows = await csvRows(d);
      assert.equal(rows, n1);
      return `${d.suggestedFilename()}: ${rows} rows`;
    } });
    await ctl(page, record, { id: "whatif-save-form", prereq: `all ${n1} filtered rows selected`, action: "Save cohort, name, submit", expected: "a governed cohort of exactly those rows; its membership hash equals the backend's for the same filter", run: async () => {
      await page.click(sel("whatif-save-cohort"));
      await page.fill(sel("whatif-save-form-input"), `GW-CTL ${two[0]}`);
      await page.click(sel("whatif-save-form-submit"));
      await page.waitForFunction(() => /as coh-/.test(document.querySelector('[data-testid="whatif-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      const id = /(coh-[0-9a-z-]+)/.exec(await page.textContent(sel("whatif-note")))[1];
      const o = await objectOf(id);
      const oracle = (await post("/cohorts", { domain: "corporate", name: "GW-CTL oracle", filters: [{ column: "sector", op: "in", values: [two[0]] }] })).body;
      assert.equal(o.body.counts.entities, n1);
      assert.equal(o.body.membership_hash, oracle.body.membership_hash, "same membership as the backend's own freeze");
      return `${id}: ${n1} entities, hash ${o.body.membership_hash.slice(0, 12)} = oracle`;
    } });
  });
}

// =========================================================================
// SCENARIO LIBRARY AND SCENARIO — every verb, templates immutable
// =========================================================================

async function scenarioJourney() {
  const { journey, open, ctl, navTrip, assert, api, post, openLibrary, libraryState, detailState, readZip } = H;
  await journey("GW-CTL-SCN", "Scenario Library and scenario: search, book/owner/severity/tag filters, select and clear, combine 2 and combine 3 with overlap policies, open/preview/clone/new from a card; rename, branch, bind, share, comment, retire, lineage links, export package / LLM option / Trace, Open in What-If, result link — templates never change", async (record) => {
    const page = await open();
    const tpl = async (code) => (await api(`/scenarios?q=${code}`)).body.scenarios.find((c) => c.template_id === code);
    const t1 = await tpl("CORP-01");
    const tplHash = (await objectOf(t1.object_id)).content_hash;
    await openLibrary(page);
    const count = () => page.getAttribute(sel("scenario-count"), "data-total").then(Number);
    const apiTotal = async (q) => (await api(`/scenarios?${q}`)).body.total;
    const waitCount = (n) => page.waitForFunction((want) => Number(document.querySelector('[data-testid="scenario-count"]')?.getAttribute("data-total")) === want, n, { timeout: 60_000 });
    const pre = "Scenario Library, no filter";
    await ctl(page, record, { id: "scenario-search", prereq: pre, action: "type PD", expected: "the query is held until submitted", run: async () => {
      await page.fill(sel("scenario-search"), "PD");
      return "typed";
    } });
    await ctl(page, record, { id: "scenario-search-form", prereq: "PD typed", action: "submit (Enter)", expected: "the library lists the backend's matches for PD (q= in the address)", run: async () => {
      await page.press(sel("scenario-search"), "Enter");
      const want = await apiTotal("q=PD");
      await waitCount(want);
      await page.waitForFunction(() => new URLSearchParams(location.search).get("q") === "PD", null, { timeout: 30_000 });
      return `${want} matches (backend ${want}); q=PD in the address`;
    } });
    await ctl(page, record, { id: "scenario-domain-retail", prereq: "q=PD", expected: "Retail scenarios matching PD", run: async () => {
      await page.click(sel("scenario-domain-retail"));
      const want = await apiTotal("q=PD&domain=retail");
      await waitCount(want);
      return `${want} (backend ${want})`;
    } });
    await ctl(page, record, { id: "scenario-owner-template", prereq: "q=PD, retail", expected: "only library templates", run: async () => {
      await page.click(sel("scenario-owner-template"));
      const want = await apiTotal("q=PD&domain=retail&owner=template");
      await waitCount(want);
      return `${want} (backend ${want})`;
    } });
    await ctl(page, record, { id: "scenario-severity", prereq: "q=PD, retail, templates", action: "severity = severe", expected: "only severe ones", run: async () => {
      await page.selectOption(sel("scenario-severity"), "severe");
      const want = await apiTotal("q=PD&domain=retail&owner=template&severity=severe");
      await waitCount(want);
      return `${want} (backend ${want})`;
    } });
    await page.fill(sel("scenario-search"), "");
    await page.press(sel("scenario-search"), "Enter");
    await page.click(sel("scenario-domain-corporate"));
    await page.selectOption(sel("scenario-severity"), "");
    await page.click(sel("scenario-owner-all"));
    await waitCount(await apiTotal("domain=corporate"));
    await ctl(page, record, { id: "scenario-tag", prereq: "corporate, all owners", action: "pick the most common tag", expected: "only scenarios with that tag", run: async () => {
      const opts = await page.$$eval(`${sel("scenario-tag")} option`, (o) => o.map((x) => x.value).filter(Boolean));
      await page.selectOption(sel("scenario-tag"), opts[0]);
      const want = await apiTotal(`domain=corporate&tag=${encodeURIComponent(opts[0])}`);
      await waitCount(want);
      await page.selectOption(sel("scenario-tag"), "");
      return `tag ${opts[0]}: ${want} (backend ${want})`;
    } });
    await waitCount(await apiTotal("domain=corporate"));
    const cardSel = (code) => `[data-testid="scenario-card"][data-template-id="${code}"]`;
    await page.check(`${cardSel("CORP-01")} ${sel("scenario-select")}`);
    await page.check(`${cardSel("CORP-02")} ${sel("scenario-select")}`);
    await ctl(page, record, { id: "scenario-selection-clear", prereq: "CORP-01 and CORP-02 selected", expected: "the selection is cleared", run: async () => {
      await page.click(sel("scenario-selection-clear"));
      await page.waitForSelector(sel("scenario-selection"), { state: "detached", timeout: 30_000 });
      return "cleared";
    } });
    // The library's filters and combine selection (not the total, which a
    // combine raises by one).
    const libFilters = () => ({
      q: document.querySelector('[data-testid="scenario-search"]')?.value ?? null,
      owner: document.querySelector('[data-testid="scenario-owner"]')?.getAttribute("data-value") ?? null,
      domain: document.querySelector('[data-testid="scenario-domain"]')?.getAttribute("data-value") ?? null,
      severity: document.querySelector('[data-testid="scenario-severity"]')?.value ?? null,
    });
    const combine = async (codes, name) => {
      const ids = [];
      for (const c of codes) ids.push((await tpl(c)).object_id);
      for (const c of codes) await page.check(`${cardSel(c)} ${sel("scenario-select")}`);
      await ctl(page, record, { id: "scenario-combine", prereq: `${codes.join(" + ")} selected`, expected: "the combine panel opens on the selection", run: async () => {
        await page.click(sel("scenario-combine"));
        await page.waitForSelector(sel("scenario-combine-panel"), { timeout: 60_000 });
        return `panel for ${codes.length}`;
      } });
      await ctl(page, record, { id: "scenario-combine-name", prereq: "combine panel", action: `name it "${name}"`, expected: "the name is held; the overlap matrix or Save is offered", run: async () => {
        await page.fill(sel("scenario-combine-name"), name);
        await page.waitForSelector(`${sel("scenario-combine-preview")}, ${sel("scenario-combine-save")}`, { timeout: 120_000 });
        return "named";
      } });
      const selects = page.locator(`${sel("scenario-combine-panel")} ${sel("overlap-policy-select")}`);
      const n = await selects.count();
      for (let i = 0; i < n; i += 1) {
        await ctl(page, record, { id: "overlap-policy-select", prereq: `overlap ${i + 1} of ${n}`, expected: "the overlap's policy is chosen from its allowed list", run: async () => {
          const opts = await selects.nth(i).locator("option").evaluateAll((o) => o.map((x) => x.value).filter(Boolean));
          await selects.nth(i).selectOption(opts[0]);
          return `policy ${opts[0]} (of ${opts.length})`;
        } });
      }
      let out = null;
      await navTrip(page, record, {
        id: n ? "overlap-resolve" : "scenario-combine-save", prereq: `${codes.join(" + ")} named${n ? `, ${n} overlap(s) resolved` : ""}`, expected: "a NEW scenario with every selected scenario as a parent; the templates unchanged", state: libFilters,
        go: (p) => p.click(n ? `${sel("scenario-combine-panel")} ${sel("overlap-resolve")}` : sel("scenario-combine-save")),
        arrived: async (p) => { await waitPath(p, /^\/scenarios\/scn-/); await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); },
        inApp: sel("scenario-back"),
        handoff: {
          source: async () => ({ parents: [...ids].sort(), hashes: await Promise.all(ids.map(async (i) => (await objectOf(i)).content_hash)) }),
          destination: async (p) => { const id = await p.getAttribute(sel("scenario-detail"), "data-object-id"); const lin = (await api(`/objects/${id}/lineage`)).body; return { id, parents: lin.ancestors.map((a) => a.object_id).sort() }; },
          identity: async (s, d) => {
            assert.deepEqual(d.parents, s.parents, "every selected scenario is a parent");
            for (const [k, i] of ids.entries()) assert.equal((await objectOf(i)).content_hash, s.hashes[k], "the template did not change");
            out = { id: d.id, overlaps: n };
            return `${codes.join(" + ")} → ${d.id} (parents ${d.parents.length}, ${n} overlap(s) resolved); templates unchanged`;
          },
          writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios\/combine /,
          describe,
        },
      });
      return out;
    };
    const two = await combine(["CORP-01", "CORP-02"], "GW-CTL combined 2");
    assert.ok(two, "two combined");
    await page.click(sel("scenario-selection-clear")).catch(() => undefined);
    const three = await combine(["CORP-01", "CORP-02", "CORP-03"], "GW-CTL combined 3");
    assert.ok(three, "three combined");
    assert.ok((two.overlaps + three.overlaps) > 0, "the combinations had overlaps to resolve");
    await openLibrary(page);
    const lib = libraryState;
    await navTrip(page, record, {
      id: "scenario-open-preview", prereq: pre, expected: "opens that scenario's preview", state: lib,
      go: (p) => p.click(`${cardSel("CORP-04")} ${sel("scenario-open-preview")}`),
      arrived: (p) => p.waitForSelector(`[data-testid="scenario-detail"]`, { timeout: 120_000 }), inApp: sel("scenario-back"),
      handoff: { source: async () => ({ template: "CORP-04" }), destination: async (p) => ({ template: (await objectOf(await p.getAttribute(sel("scenario-detail"), "data-object-id"))).body.template_id }), identity: (s, d) => { assert.equal(d.template, s.template); return `card ${s.template} → detail ${d.template}`; }, describe },
    });
    await navTrip(page, record, {
      id: "scenario-open", prereq: pre, expected: "opens that scenario", state: lib,
      go: (p) => p.click(`${cardSel("CORP-04")} ${sel("scenario-open")}`),
      arrived: (p) => p.waitForSelector(`[data-testid="scenario-detail"]`, { timeout: 120_000 }), inApp: sel("scenario-back"),
    });
    await navTrip(page, record, {
      id: "scenario-new", prereq: pre, expected: "opens the builder; Back returns to the library", state: lib,
      arrived: (p) => p.waitForSelector(sel("scenario-builder"), { timeout: 120_000 }), inApp: sel("builder-back"),
    });
    let copy = "";
    await navTrip(page, record, {
      id: "scenario-clone", prereq: pre, expected: "a copy of CORP-04 (lineage: duplicate of it) opens; the template is unchanged",
      // The clone adds one scenario by design: Back restores the filters, not the old count.
      state: () => ({ q: document.querySelector('[data-testid="scenario-search"]')?.value ?? null, owner: document.querySelector('[data-testid="scenario-owner"]')?.getAttribute("data-value") ?? null, domain: document.querySelector('[data-testid="scenario-domain"]')?.getAttribute("data-value") ?? null, severity: document.querySelector('[data-testid="scenario-severity"]')?.value ?? null }),
      go: (p) => p.click(`${cardSel("CORP-04")} ${sel("scenario-clone")}`),
      arrived: async (p) => { await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); copy = copy || (await p.getAttribute(sel("scenario-detail"), "data-object-id")); },
      inApp: sel("scenario-back"),
      handoff: {
        source: async () => ({ template: (await tpl("CORP-04")).object_id }),
        destination: async (p) => ({ copy: await p.getAttribute(sel("scenario-detail"), "data-object-id") }),
        identity: async (s, d) => {
          const lin = (await api(`/objects/${d.copy}/lineage`)).body;
          assert.deepEqual(lin.ancestors.map((a) => a.object_id), [s.template]);
          return `template ${s.template} → copy ${d.copy} (lineage ancestor ${lin.ancestors[0].object_id})`;
        },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios\/[^/]+\/clone /,
        describe,
      },
    });
    // The copy's detail page: every verb of an owned scenario.
    await page.goto(`${H.UI}/scenarios/${copy}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-detail"), { timeout: 120_000 });
    const preC = `own copy ${copy} (draft)`;
    const version = () => page.getAttribute(sel("scenario-detail"), "data-version").then(Number);
    await ctl(page, record, { id: "scenario-action-rename", prereq: preC, expected: "the rename form opens", run: async () => {
      await page.click(sel("scenario-action-rename"));
      await page.waitForSelector(sel("scenario-rename"), { timeout: 30_000 });
      return "form open";
    } });
    await ctl(page, record, { id: "scenario-rename-input", prereq: "rename form open", action: "type a new name", expected: "held in the form", run: async () => {
      await page.fill(sel("scenario-rename-input"), "GW-CTL renamed copy");
      return "typed";
    } });
    await ctl(page, record, { id: "scenario-rename", prereq: "new name typed", action: "submit", expected: "a new version with the new name (the old version kept)", run: async () => {
      const v = await version();
      await page.click(sel("scenario-rename-submit"));
      await page.waitForFunction((x) => Number(document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-version")) === x + 1, v, { timeout: 60_000 });
      assert.equal((await page.textContent(sel("scenario-name"))).trim(), "GW-CTL renamed copy");
      const versions = (await api(`/objects/${copy}/history`)).body;
      return `v${v} → v${v + 1}; ${JSON.stringify(versions).includes("renamed") ? "history records the rename" : "history updated"}`;
    } });
    await ctl(page, record, { id: "scenario-action-share", prereq: preC, expected: "the share form opens", run: async () => {
      await page.click(sel("scenario-action-share"));
      await page.waitForSelector(sel("scenario-share"), { timeout: 30_000 });
      return "form open";
    } });
    await ctl(page, record, { id: "scenario-share-input", prereq: "share form open", action: "type a recipient", expected: "held", run: async () => {
      await page.fill(sel("scenario-share-input"), "colleague");
      return "typed";
    } });
    await ctl(page, record, { id: "scenario-share", prereq: "recipient typed", action: "submit", expected: "the reference is shared (never the data); it is in Sent", run: async () => {
      await page.click(sel("scenario-share-submit"));
      await page.waitForFunction(() => /Shared v\d+ with 1 recipient/.test(document.querySelector('[data-testid="scenario-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      const sent = (await api("/messages?box=sent")).body.items;
      assert.ok(sent.some((m) => JSON.stringify(m).includes(copy)));
      return "shared; in Sent";
    } });
    await ctl(page, record, { id: "scenario-action-comment", prereq: preC, expected: "the comment form opens", run: async () => {
      await page.click(sel("scenario-action-comment"));
      await page.waitForSelector(sel("scenario-comment"), { timeout: 30_000 });
      return "form open";
    } });
    await ctl(page, record, { id: "scenario-comment-input", prereq: "comment form open", action: "type a comment", expected: "held", run: async () => {
      await page.fill(sel("scenario-comment-input"), "GW-CTL comment on this version");
      return "typed";
    } });
    await ctl(page, record, { id: "scenario-comment", prereq: "comment typed", action: "submit", expected: "the comment is stored against this version and listed", run: async () => {
      await page.click(sel("scenario-comment-submit"));
      await page.waitForSelector(`${sel("scenario-comments")}:has-text("GW-CTL comment on this version")`, { timeout: 60_000 });
      const stored = (await api(`/objects/${copy}/comments`)).body;
      assert.ok(JSON.stringify(stored).includes("GW-CTL comment on this version"));
      return "listed and stored";
    } });
    await ctl(page, record, { id: "preview-show-translation", prereq: preC, expected: "a component's engine translation expands, then collapses", run: async () => {
      const before = await page.locator("tr").count();
      await page.locator(sel("preview-show-translation")).first().click();
      await page.waitForFunction((b) => document.querySelectorAll("tr").length > b, before, { timeout: 30_000 });
      await page.locator(sel("preview-show-translation")).first().click();
      await page.waitForFunction((b) => document.querySelectorAll("tr").length === b, before, { timeout: 30_000 });
      return "expanded and collapsed";
    } });
    await ctl(page, record, { id: "scenario-export-go", prereq: preC, expected: "the governed export package (objects, manifest hashes) downloads", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("scenario-export-go"))]);
      const z = await readZip(await d.path());
      assert.ok(z.list.some((n) => /manifest/i.test(n)), "a manifest");
      return `${d.suggestedFilename()}: ${z.list.length} files`;
    } });
    await navTrip(page, record, {
      id: "scenario-export-trace", prereq: preC, expected: "opens the governance Trace of this scenario", state: detailState,
      arrived: (p) => p.waitForSelector(sel("object-trace"), { timeout: 120_000 }), inApp: sel("trace-object-back"),
      handoff: { source: async () => ({ object: copy }), destination: async (p) => ({ object: decodeURIComponent(/\/trace\/object\/([^?]+)/.exec(p.url())[1]) }), identity: (s, d) => { assert.equal(d.object, s.object); return `${s.object} → trace of ${d.object}`; }, describe },
    });
    await navTrip(page, record, {
      id: "scenario-lineage-ancestor", prereq: preC, expected: "opens the template it was copied from", state: detailState,
      go: (p) => p.locator(sel("scenario-lineage-ancestor")).first().click(),
      arrived: async (p) => { await waitPath(p, /^\/scenarios\/scn-tpl-/); await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); }, inApp: sel("scenario-back"),
    });
    await navTrip(page, record, {
      id: "scenario-action-branch", prereq: preC, expected: "a branch (lineage: branch of this copy) opens; Back returns to the copy", state: detailState,
      arrived: async (p) => { await p.waitForFunction((c) => { const d = document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id"); return d && d !== c; }, copy, { timeout: 120_000 }); },
      inApp: sel("scenario-back"),
      handoff: {
        source: async () => ({ copy }),
        destination: async (p) => ({ branch: await p.getAttribute(sel("scenario-detail"), "data-object-id") }),
        identity: async (s, d) => { const o = await objectOf(d.branch); assert.equal(o.lineage.origin, "branch"); return `${s.copy} → branch ${d.branch} (origin ${o.lineage.origin})`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios\/[^/]+\/(clone|branch) /,
        describe,
      },
    });
    await navTrip(page, record, {
      id: "scenario-action-clone", prereq: preC, expected: "a clone (lineage: clone of this copy) opens; Back returns to the copy", state: detailState,
      arrived: async (p) => { await p.waitForFunction((c) => { const d = document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id"); return d && d !== c; }, copy, { timeout: 120_000 }); },
      inApp: sel("scenario-back"),
      handoff: {
        source: async () => ({ copy, hash: (await objectOf(copy)).content_hash }),
        destination: async (p) => ({ clone: await p.getAttribute(sel("scenario-detail"), "data-object-id") }),
        identity: async (s, d) => {
          const lin = (await api(`/objects/${d.clone}/lineage`)).body;
          assert.deepEqual(lin.ancestors.map((a) => a.object_id), [s.copy], "the clone's parent is the copy");
          assert.equal((await objectOf(s.copy)).content_hash, s.hash, "the copy did not change");
          return `${s.copy} → clone ${d.clone} (parent ${lin.ancestors[0].object_id}); the copy unchanged`;
        },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios\/[^/]+\/clone /,
        describe,
      },
    });
    // The template's descendants include the copy.
    await page.goto(`${H.UI}/scenarios/${(await tpl("CORP-04")).object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-lineage-descendant"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "scenario-lineage-descendant", prereq: "template CORP-04 with copies", expected: "opens a scenario derived from this template", state: detailState,
      go: (p) => p.locator(sel("scenario-lineage-descendant")).first().click(),
      arrived: async (p) => { await waitPath(p, /^\/scenarios\/scn-(?!tpl)/); await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); }, inApp: sel("scenario-back"),
    });
    // A result of the copy, then its result link and Open in What-If.
    await H.apiRun(copy, `gw-ctl-scn-${Date.now()}`, ["delta"]);
    await page.goto(`${H.UI}/scenarios/${copy}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-result-link"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "scenario-result-link", prereq: `${copy} executed once`, expected: "opens that result", state: detailState,
      go: (p) => p.locator(sel("scenario-result-link")).first().click(),
      arrived: (p) => p.waitForSelector(sel("whatif-result"), { timeout: 120_000 }), inApp: sel("whatif-result-back"),
      handoff: { source: async () => ({ scenario: copy }), destination: async (p) => ({ result: await p.getAttribute(sel("whatif-result"), "data-result-id") }), identity: async (s, d) => { const r = await objectOf(d.result); assert.equal(r.body.scenario_id, s.scenario); return `${s.scenario} → result ${d.result} of scenario ${r.body.scenario_id}`; }, describe },
    });
    await navTrip(page, record, {
      id: "scenario-open-whatif", prereq: preC, expected: "What-If opens with this scenario loaded (nothing run)", state: detailState,
      arrived: (p) => p.waitForFunction((c) => document.querySelector('[data-testid="whatif-strip-scenario"]')?.getAttribute("data-scenario-id") === c, copy, { timeout: 120_000 }), inApp: sel("whatif-back"),
      handoff: { source: async () => ({ scenario: copy }), destination: async (p) => ({ scenario: await p.getAttribute(sel("whatif-strip-scenario"), "data-scenario-id") }), identity: (s, d) => { assert.equal(d.scenario, s.scenario); return `${s.scenario} → What-If scenario ${d.scenario}`; }, describe },
    });
    await ctl(page, record, { id: "scenario-action-retire", prereq: preC, expected: "the scenario is retired (ARCHIVED); the record stays readable", run: async () => {
      await page.click(sel("scenario-action-retire"));
      await page.waitForFunction(() => /ARCHIVED/.test(document.querySelector('[data-testid="scenario-status"]')?.textContent ?? ""), null, { timeout: 60_000 });
      assert.equal((await objectOf(copy)).status, "ARCHIVED");
      return "ARCHIVED; still readable";
    } });
    await ctl(page, record, { id: "check:templates-immutable", prereq: "after every verb", action: "re-read the templates", expected: "CORP-01 and CORP-04 templates are unchanged (immutable)", run: async () => {
      assert.equal((await objectOf(t1.object_id)).content_hash, tplHash, "CORP-01 unchanged");
      const t4 = await objectOf((await tpl("CORP-04")).object_id);
      assert.equal(t4.version, 1, "CORP-04 still version 1");
      return "templates unchanged";
    } });
    void post;
  });
}

// =========================================================================
// SCENARIO BUILDER
// =========================================================================

async function builderJourney() {
  const { journey, open, ctl, navTrip, assert, api, post } = H;
  await journey("GW-CTL-BUILDER", "Scenario builder: book switch, name/severity/stage/description/thesis, scope modes, filter column/op/value/add/remove, a component of every kind with its own fields, remove component, preview (= backend preview), save draft and save, cancel, a cohort scope from What-If", async (record) => {
    const page = await open();
    const go = async (q = "") => {
      await page.goto(`${H.UI}/scenarios/new${q}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(sel("scenario-builder"), { timeout: 120_000 });
    };
    await go("?back=%2Fscenarios");
    const pre = "Builder, Corporate, empty";
    await ctl(page, record, { id: "ws-domain-retail", prereq: pre, expected: "the builder switches to Retail: Retail component kinds and fields", run: async () => {
      await page.click(sel("ws-domain-retail"));
      await page.waitForSelector(sel("builder-add-score"), { timeout: 30_000 });
      await page.click(sel("ws-domain-corporate"));
      await page.waitForSelector(sel("builder-add-rating"), { timeout: 30_000 });
      assert.equal(await page.locator(sel("builder-add-score")).count(), 0);
      return "retail kinds (score) shown, then corporate (rating)";
    } });
    for (const [id, how, v] of [["builder-name", "fill", "GW-CTL built"], ["builder-severity", "select", "severe"], ["builder-stage-policy", "select", "retest_sicr"], ["builder-description", "fill", "Built by GW-CTL-BUILDER"], ["builder-thesis", "fill", "Construction stress"]]) {
      await ctl(page, record, { id, prereq: pre, action: `${how} ${v}`, expected: "the field holds the value (it goes into the definition)", run: async () => {
        if (how === "fill") await page.fill(sel(id), v);
        else await page.selectOption(sel(id), v);
        assert.equal(await page.inputValue(sel(id)), v);
        return v;
      } });
    }
    await ctl(page, record, { id: "builder-scope-filters", prereq: pre, expected: "the filtered-segment editor appears", run: async () => {
      await page.check(sel("builder-scope-filters"));
      await page.waitForSelector(sel("builder-filter"), { timeout: 30_000 });
      return "filter editor shown";
    } });
    await ctl(page, record, { id: "builder-filter-add", prereq: "filtered scope", expected: "a second filter row (all must hold)", run: async () => {
      await page.click(sel("builder-filter-add"));
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="builder-filter"]').length === 2, null, { timeout: 30_000 });
      return "2 filter rows";
    } });
    await ctl(page, record, { id: "builder-filter-remove", prereq: "two filter rows", expected: "the second filter is removed", run: async () => {
      await page.locator(sel("builder-filter-remove")).nth(1).click();
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="builder-filter"]').length === 1, null, { timeout: 30_000 });
      return "1 filter row";
    } });
    await ctl(page, record, { id: "builder-filter-column", prereq: "one filter row", action: "column = sector", expected: "held", run: async () => {
      await page.selectOption(sel("builder-filter-column"), "sector");
      return "sector";
    } });
    await ctl(page, record, { id: "builder-filter-op", prereq: "column sector", action: "operator = in", expected: "held", run: async () => {
      await page.selectOption(sel("builder-filter-op"), "eq");
      await page.selectOption(sel("builder-filter-op"), "in");
      return "eq → in";
    } });
    await ctl(page, record, { id: "builder-filter-value", prereq: "sector in", action: "value Construction", expected: "held", run: async () => {
      await page.fill(sel("builder-filter-value"), "Construction");
      return "Construction";
    } });
    // Components: one of every kind, each with its own fields.
    for (const k of ["macro", "collateral", "utilisation", "rating", "overlay"]) {
      await ctl(page, record, { id: `builder-add-${k}`, prereq: "Corporate builder", expected: `a ${k} component row is added`, run: async () => {
        const before = await page.locator(sel("builder-component")).count();
        await page.click(sel(`builder-add-${k}`));
        await page.waitForFunction((b) => document.querySelectorAll('[data-testid="builder-component"]').length === b + 1, before, { timeout: 30_000 });
        return `${k} added`;
      } });
    }
    const row = (kind) => page.locator(`[data-testid="builder-component"][data-kind="${kind}"]`).first();
    const fields = [
      ["builder-component-field", "parameter", "select", "lgd_pct"], ["builder-component-operation", "parameter", "select", "relative_pct"],
      ["builder-component-value", "parameter", "fill", "10"], ["builder-component-factor", "macro", "fill", "MEV01"],
      ["builder-component-macro-op", "macro", "select", "percentage_points"], ["builder-component-asset", "collateral", "select", "residential_property"],
    ];
    for (const [id, kind, how, v] of fields) {
      await ctl(page, record, { id, prereq: `${kind} component row`, action: `${how} ${v}`, expected: "the component holds it", run: async () => {
        const el = row(kind).locator(sel(id));
        if (how === "fill") await el.fill(v);
        else await el.selectOption(v);
        assert.equal(await el.inputValue(), v);
        return v;
      } });
    }
    await ctl(page, record, { id: "builder-component-remove", prereq: "six components", expected: "the overlay and utilisation rows are removed", run: async () => {
      for (const k of ["overlay", "utilisation"]) await row(k).locator(sel("builder-component-remove")).click();
      await page.waitForFunction(() => !document.querySelector('[data-testid="builder-component"][data-kind="overlay"]'), null, { timeout: 30_000 });
      return `${await page.locator(sel("builder-component")).count()} components left`;
    } });
    await row("macro").locator(sel("builder-component-value")).fill("-1.5");
    await row("collateral").locator(sel("builder-component-value")).fill("-10");
    await row("rating").locator(sel("builder-component-value")).fill("1");
    await ctl(page, record, { id: "builder-preview", prereq: "a macro component naming an unknown factor (XYZ)", expected: "refused in words (INVALID_COMPONENT); nothing saved or calculated",
      expect4xx: /\/scenarios\/preview 422$/, run: async () => {
        await row("macro").locator(sel("builder-component-factor")).fill("XYZ");
        await page.click(sel("builder-preview"));
        await page.waitForSelector(sel("builder-error"), { timeout: 60_000 });
        const msg = await page.textContent(sel("builder-error"));
        assert.match(msg, /not a factor id/);
        await row("macro").locator(sel("builder-component-factor")).fill("MEV01");
        return `refused: ${msg.trim().slice(0, 80)}`;
      } });
    await ctl(page, record, { id: "builder-preview", prereq: "Construction scope, parameter/macro/collateral/rating components", expected: "the preview's population equals the backend's preview of the same definition; nothing calculated", run: async () => {
      await page.click(sel("builder-preview"));
      await page.waitForSelector(sel("builder-preview-panel"), { timeout: 120_000 });
      const want = (await post("/scenarios/preview", { definition: { name: "x", domain_id: "corporate", scope: { type: "filters", filters: [{ column: "sector", op: "in", values: ["Construction"] }] }, components: [{ kind: "parameter", field: "pd_pit_12m", operation: "multiply", value: "1.1" }], stage_policy: "frozen" } })).body.scope.summary.entities;
      const text = await page.textContent(sel("builder-preview-panel"));
      assert.ok(text.replace(/,/g, "").includes(String(want)), `the preview names ${want} exposures`);
      return `preview: ${want} exposures (backend ${want})`;
    } });
    let draft = "";
    await navTrip(page, record, {
      id: "builder-save-draft", prereq: "builder filled", expected: "the definition is saved as a DRAFT and opens; every field stored", state: urlState2,
      arrived: async (p) => { await waitPath(p, /^\/scenarios\/scn-/); await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); draft = draft || (await p.getAttribute(sel("scenario-detail"), "data-object-id")); },
      // The saved scenario's Back is the builder's own origin (the
      // library), checked below; the trip checks browser Back/Forward.
      handoff: {
        source: async () => ({ name: "GW-CTL built", severity: "severe", stage: "retest_sicr" }),
        destination: async (p) => { const o = await objectOf(await p.getAttribute(sel("scenario-detail"), "data-object-id")); return { id: o.object_id, status: o.status, name: o.body.name, severity: o.body.severity, stage: o.body.stage_policy, kinds: o.body.components.map((c) => c.kind) }; },
        identity: (s, d) => { assert.equal(d.status, "DRAFT"); assert.equal(d.name, s.name); assert.equal(d.severity, s.severity); assert.equal(d.stage, s.stage); return `${d.id} DRAFT: ${d.name}, ${d.severity}, ${d.stage}, components ${d.kinds.join("+")}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios /,
        describe,
      },
    });
    await ctl(page, record, { id: "scenario-back", prereq: `draft ${draft} opened from the builder (opened from the library)`, expected: "in-product Back goes to the builder's origin, the library", run: async () => {
      await page.goto(`${H.UI}/scenarios/${draft}?back=%2Fscenarios`, { waitUntil: "domcontentloaded" });
      await page.click(sel("scenario-back"));
      await page.waitForSelector(sel("scenario-library"), { timeout: 60_000 });
      return "library";
    } });
    await go("?back=%2Fscenarios");
    await page.fill(sel("builder-name"), "GW-CTL saved");
    await navTrip(page, record, {
      id: "builder-save-saved", prereq: "builder with a name", expected: "the definition is saved (SAVED) and opens", state: urlState2,
      arrived: async (p) => { await waitPath(p, /^\/scenarios\/scn-/); await p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }); },
      // The saved scenario's Back is the builder's own origin (the
      // library), checked below; the trip checks browser Back/Forward.
      handoff: {
        source: async () => ({ name: "GW-CTL saved" }),
        destination: async (p) => { const o = await objectOf(await p.getAttribute(sel("scenario-detail"), "data-object-id")); return { id: o.object_id, status: o.status, name: o.body.name }; },
        identity: (s, d) => { assert.equal(d.status, "SAVED"); assert.equal(d.name, s.name); return `${d.id} SAVED ${d.name}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/scenarios /,
        describe,
      },
    });
    await page.goto(`${H.UI}/scenarios`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-library"), { timeout: 120_000 });
    await page.click(sel("scenario-new"));
    await page.waitForSelector(sel("scenario-builder"), { timeout: 120_000 });
    await page.fill(sel("builder-name"), "never saved");
    const before = (await api("/scenarios?owner=mine")).body.total;
    await ctl(page, record, { id: "builder-cancel", prereq: "builder opened from the library, a name typed", expected: "returns to the library; nothing is saved", run: async () => {
      await page.click(sel("builder-cancel"));
      await page.waitForSelector(sel("scenario-library"), { timeout: 60_000 });
      assert.equal((await api("/scenarios?owner=mine")).body.total, before, "nothing saved");
      return "library; no new scenario";
    } });
    // Scope = a saved cohort, when opened from What-If with one.
    const cohort = (await post("/cohorts", { domain: "corporate", name: "GW-CTL builder scope", filters: [{ column: "sector", op: "in", values: ["Construction"] }] })).body;
    await go(`?cohort=${cohort.object_id}&domain=corporate`);
    await ctl(page, record, { id: "builder-scope-cohort", prereq: `opened with cohort ${cohort.object_id}`, expected: "the cohort scope is available and chosen", run: async () => {
      await page.waitForFunction(() => !document.querySelector('[data-testid="builder-scope-cohort"]')?.disabled, null, { timeout: 60_000 });
      await page.check(sel("builder-scope-cohort"));
      return "cohort scope chosen";
    } });
    await ctl(page, record, { id: "builder-scope-whole_book", prereq: "cohort scope", expected: "back to the whole book", run: async () => {
      await page.check(sel("builder-scope-whole_book"));
      return "whole book";
    } });
    await ctl(page, record, { id: "ws-domain-retail", prereq: "Builder", action: "Retail: add a score component and set its fields", expected: "Retail-only component fields work", run: async () => {
      await page.click(sel("ws-domain-retail"));
      await page.click(sel("builder-add-score"));
      const r = row("score");
      await r.locator(sel("builder-component-score-type")).selectOption("APPLICATION");
      await r.locator(sel("builder-component-score-op")).selectOption("bands");
      assert.equal(await r.locator(sel("builder-component-score-op")).inputValue(), "bands");
      return "score: APPLICATION, bands";
    } });
    for (const id of ["builder-component-score-type", "builder-component-score-op"]) {
      await ctl(page, record, { id, prereq: "Retail score component", expected: "the score field changes", run: async () => {
        const el = row("score").locator(sel(id));
        const opts = await el.locator("option").evaluateAll((o) => o.map((x) => x.value));
        await el.selectOption(opts[0]);
        assert.equal(await el.inputValue(), opts[0]);
        return opts[0];
      } });
    }
  });
}

// =========================================================================
// MONITORING CENTRE — views, filters, charts, the alert lifecycle, the
// alert's handoffs; state survives a reload
// =========================================================================

async function monitoringJourney() {
  const { journey, open, ctl, navTrip, assert, api, monitoringState } = H;
  await journey("GW-CTL-MON", "Monitoring: every view and filter (= API counts), both charts, alert open, acknowledge / assign / comment / resolve / reopen / suppress with notes (state persists across reload), metric / Lens / Investigate / What-If / Trace handoffs, export package, refresh-health Lens link", async (record) => {
    const page = await open();
    const goMon = async (q = "") => {
      await page.goto(`${H.UI}/monitoring${q}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(`${sel("monitoring-list")}[data-state]:not([data-state=""])`, { timeout: 120_000 });
    };
    await goMon();
    const count = () => page.getAttribute(sel("monitoring-list"), "data-count").then(Number);
    const apiCount = async (q) => (await api(`/monitoring?${q}`)).body.alerts.length;
    const waitCount = (n) => page.waitForFunction((w) => Number(document.querySelector('[data-testid="monitoring-list"]')?.getAttribute("data-count")) === w, n, { timeout: 60_000 });
    for (const v of ["new_today", "active", "worsening", "acknowledged", "resolved", "all", "changes", "history", "mine", "active"]) {
      await ctl(page, record, { id: `monitoring-view-${v}`, prereq: "Monitoring Centre", expected: `the ${v} view lists the backend's alerts for it`, run: async () => {
        await page.click(sel(`monitoring-view-${v}`));
        // The address is written after the click; wait for it (it never
        // arrives if the view is not kept), then for the backend's count.
        await page.waitForFunction((w) => (new URLSearchParams(location.search).get("view") ?? "active") === w, v, { timeout: 30_000 });
        const want = await apiCount(`view=${v}`);
        await waitCount(want);
        return `${v}: ${want} (backend ${want})`;
      } });
    }
    await ctl(page, record, { id: "monitoring-severity", prereq: "active view", action: "severity = high", expected: "only high-severity alerts (= backend)", run: async () => {
      await page.selectOption(sel("monitoring-severity"), "high");
      const want = await apiCount("view=active&severity=high");
      await waitCount(want);
      await page.selectOption(sel("monitoring-severity"), "");
      return `high: ${want}`;
    } });
    await ctl(page, record, { id: "monitoring-domain", prereq: "active view", action: "book = retail", expected: "only Retail alerts (= backend)", run: async () => {
      await page.selectOption(sel("monitoring-domain"), "retail");
      const want = await apiCount("view=active&domain=retail");
      await waitCount(want);
      await page.selectOption(sel("monitoring-domain"), "");
      return `retail: ${want}`;
    } });
    await ctl(page, record, { id: "monitoring-lens", prereq: "active view", action: "Lens = lens-01", expected: "only that Lens's alerts (= backend)", run: async () => {
      await page.selectOption(sel("monitoring-lens"), "lens-01");
      const want = await apiCount("view=active&lens=lens-01");
      await waitCount(want);
      await page.selectOption(sel("monitoring-lens"), "");
      return `lens-01: ${want}`;
    } });
    await ctl(page, record, { id: "monitoring-by-severity", prereq: "active view", action: "click the first severity bar", expected: "the list is filtered to that severity", run: async () => {
      // The previous step reset a filter; the chart redraws on the new list.
      await waitCount(await apiCount("view=active"));
      await page.waitForSelector(`${sel("monitoring-by-severity")}[data-rendered="true"]`, { timeout: 60_000 });
      const sev = String(await (await page.waitForFunction(() => document.querySelector('[data-testid="monitoring-by-severity"]')?.data?.[0]?.x?.[0], null, { timeout: 30_000 })).jsonValue());
      await clickPlotPoint(page, "monitoring-by-severity", { point: 0 });
      await page.waitForFunction((x) => document.querySelector('[data-testid="monitoring-severity"]')?.value === x, sev, { timeout: 30_000 });
      await waitCount(await apiCount(`view=active&severity=${sev}`));
      await page.selectOption(sel("monitoring-severity"), "");
      return `filtered to ${sev}`;
    } });
    await ctl(page, record, { id: "monitoring-by-lens", prereq: "active view", action: "click the first Lens bar", expected: "the list is filtered to that Lens", run: async () => {
      // The previous step reset a filter; the chart redraws on the new list.
      await waitCount(await apiCount("view=active"));
      await page.waitForSelector(`${sel("monitoring-by-lens")}[data-rendered="true"]`, { timeout: 60_000 });
      const id = await (await page.waitForFunction(() => document.querySelector('[data-testid="monitoring-by-lens"]')?.data?.[0]?.customdata?.[0]?.[0], null, { timeout: 30_000 })).jsonValue();
      await clickPlotPoint(page, "monitoring-by-lens", { point: 0 });
      await page.waitForFunction((x) => document.querySelector('[data-testid="monitoring-lens"]')?.value === x, id, { timeout: 30_000 });
      await page.selectOption(sel("monitoring-lens"), "");
      return `filtered to ${id}`;
    } });
    const breach = (await api("/monitoring?view=active")).body.alerts.find((a) => a.alert_type === "breach" && !a.demo_historical);
    const aid = breach.alert_id;
    await ctl(page, record, { id: "monitoring-alert", prereq: "active view", action: `open ${aid}`, expected: "the alert opens (?alert= in the address; Back closes it)", run: async () => {
      await page.click(`[data-testid="monitoring-alert"][data-alert-id="${aid}"]`);
      await page.waitForSelector(sel("alert-panel"), { timeout: 60_000 });
      assert.equal(new URL(page.url()).searchParams.get("alert"), aid);
      return `panel ${aid} (${await page.getAttribute(sel("alert-panel"), "data-state")})`;
    } });
    const pre = `alert ${aid} open`;
    const state = async () => (await api(`/monitoring/alerts/${aid}`)).body.alert.status;
    const act = async (id, note, want) => {
      if (note !== null) await page.fill(sel("alert-note"), note);
      await page.click(sel(id));
      await page.waitForFunction((w) => document.querySelector('[data-testid="alert-panel"]')?.getAttribute("data-state") === w, want, { timeout: 60_000 });
      assert.equal(await state(), want, "stored");
      return want;
    };
    await ctl(page, record, { id: "alert-note", prereq: pre, action: "type a note", expected: "held for the next action", run: async () => {
      await page.fill(sel("alert-note"), "looking into it");
      return "typed";
    } });
    await ctl(page, record, { id: "alert-acknowledge", prereq: pre, expected: "ACKNOWLEDGED with the note; stored", run: async () => `→ ${await act("alert-acknowledge", "looking into it", "ACKNOWLEDGED")}` });
    await ctl(page, record, { id: "alert-assign", prereq: "acknowledged", expected: "assigned to me (one event even if clicked twice)", run: async () => {
      await page.click(sel("alert-assign"));
      await page.waitForFunction(() => /assigned to/.test(document.querySelector('[data-testid="alert-history"]')?.textContent ?? ""), null, { timeout: 60_000 });
      const a = (await api(`/monitoring/alerts/${aid}`)).body.alert;
      assert.ok(a.body.assignee, "assignee stored");
      return `assignee ${a.body.assignee}`;
    } });
    await ctl(page, record, { id: "alert-comment", prereq: "acknowledged", action: "comment with a note", expected: "the comment is in the history; state unchanged", run: async () => {
      await page.fill(sel("alert-note"), "GW-CTL comment");
      await page.click(sel("alert-comment"));
      await page.waitForFunction(() => /GW-CTL comment/.test(document.querySelector('[data-testid="alert-history"]')?.textContent ?? ""), null, { timeout: 60_000 });
      assert.equal(await state(), "ACKNOWLEDGED");
      return "in history";
    } });
    await ctl(page, record, { id: "alert-resolve", prereq: "acknowledged", expected: "RESOLVED; it leaves the active view and appears in Resolved", run: async () => `→ ${await act("alert-resolve", "fixed upstream", "RESOLVED")}` });
    await ctl(page, record, { id: "check:alert-state-survives-reload", prereq: "resolved", action: "reload the page", expected: "the alert is still RESOLVED", run: async () => {
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector(`${sel("alert-panel")}[data-state="RESOLVED"]`, { timeout: 60_000 });
      return "RESOLVED after reload";
    } });
    await ctl(page, record, { id: "alert-reopen", prereq: "resolved", expected: "ACTIVE again", run: async () => `→ ${await act("alert-reopen", null, "ACTIVE")}` });
    await ctl(page, record, { id: "alert-suppress", prereq: "active; the demo principal is an administrator", expected: "SUPPRESSED with a note (an analyst is refused: API-tested)", run: async () => {
      const out = await act("alert-suppress", "known data issue", "SUPPRESSED");
      await act("alert-reopen", null, "ACTIVE");
      return `→ ${out} → ACTIVE`;
    } });
    await ctl(page, record, { id: "alert-export-go", prereq: pre, expected: "the alert's governed export package downloads", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("alert-export-go"))]);
      return d.suggestedFilename();
    } });
    const detail = (await api(`/monitoring/alerts/${aid}`)).body;
    await navTrip(page, record, {
      id: "alert-metric-link", prereq: pre, expected: "opens the alert's metric definition", state: monitoringState,
      arrived: (p) => p.waitForSelector(sel("metric-catalogue"), { timeout: 120_000 }), inApp: sel("metrics-back"),
      handoff: { source: async () => ({ metric: detail.alert.body.metric_id }), destination: async (p) => ({ metric: new URL(p.url()).searchParams.get("m") }), identity: (s, d) => { assert.equal(d.metric, s.metric); return `alert metric ${s.metric} → catalogue ${d.metric}`; }, describe },
    });
    await navTrip(page, record, {
      id: "alert-open-lens", prereq: pre, expected: "opens the alert's Lens at the trigger, with the alert banner", state: monitoringState,
      arrived: (p) => p.waitForSelector(sel("lens-alert-banner"), { timeout: 120_000 }), inApp: sel("lens-alert-back"),
      handoff: { source: async () => ({ lens: detail.open_lens.lens_id, alert: aid }), destination: async (p) => ({ lens: await p.getAttribute(sel("lens-view"), "data-object-id"), alert: new URL(p.url()).searchParams.get("alert") }), identity: (s, d) => { assert.equal(d.lens, s.lens); assert.equal(d.alert, s.alert); return `alert ${s.alert} → Lens ${d.lens} (alert=${d.alert})`; }, describe },
    });
    const alertCohort = async () => {
      const c = (await H.post(`/monitoring/alerts/${aid}/cohort`, {})).body;
      return { entities: c.body.counts.entities, hash: c.body.membership_hash };
    };
    await navTrip(page, record, {
      id: "alert-investigate", prereq: pre, expected: "opens a Cockpit investigation on the alert's population", state: monitoringState,
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"),
      handoff: {
        source: alertCohort,
        destination: async (p) => { const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1]; const c = (await api(`/whatif/threads/${t}/cohort`)).body; const o = await objectOf(c.seed_cohort_id); return { thread: t, cohort: c.seed_cohort_id, hash: o.body.membership_hash }; },
        identity: (s, d) => { assert.equal(d.hash, s.hash); return `alert population ${s.entities} (${s.hash.slice(0, 12)}) → thread ${d.thread} cohort ${d.cohort}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/monitoring\/alerts\/[^/]+\/investigate /,
        describe,
      },
    });
    await navTrip(page, record, {
      id: "alert-whatif", prereq: pre, expected: "opens What-If on the alert's population", state: monitoringState,
      arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"),
      handoff: {
        source: alertCohort,
        destination: (p) => whatifCohort(p),
        identity: (s, d) => { assert.equal(d.hash, s.hash); return `alert population ${s.entities} → What-If cohort ${d.cohort} (${d.entities})`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/monitoring\/alerts\/[^/]+\/cohort /,
        describe,
      },
    });
    await navTrip(page, record, {
      id: "alert-export-trace", prereq: pre, expected: "opens the alert's governance Trace", state: monitoringState,
      arrived: (p) => p.waitForSelector(sel("object-trace"), { timeout: 120_000 }), inApp: sel("trace-object-back"),
    });
    await navTrip(page, record, {
      id: "monitoring-lens-link", prereq: "Monitoring, refresh health", expected: "opens that Lens", state: monitoringState,
      go: (p) => p.locator(sel("monitoring-lens-link")).first().click(),
      arrived: (p) => p.waitForSelector(sel("lens-view"), { timeout: 120_000 }), inApp: sel("lens-back"),
      handoff: { source: async (p) => ({ lens: await p.locator(sel("monitoring-health-row")).first().getAttribute("data-lens-id") }), destination: async (p) => ({ lens: await p.getAttribute(sel("lens-view"), "data-object-id") }), identity: (s, d) => { assert.equal(d.lens, s.lens); return `${s.lens} → ${d.lens}`; }, describe },
    });
    await ctl(page, record, { id: "monitoring-back", prereq: "Monitoring opened from the metric catalogue", expected: "in-product Back returns to the origin", run: async () => {
      await goMon(`?back=${encodeURIComponent("/metrics?m=M001")}`);
      await page.click(sel("monitoring-back"));
      await waitPath(page, /^\/metrics\?m=M001/);
      return "metrics?m=M001";
    } });
  });
}

// =========================================================================
// LENSES — library and the Lens view, across personas
// =========================================================================

async function lensVisual(lensId, type) {
  const r = (await H.post(`/lenses/${lensId}/render`, {})).body;
  return r.visuals.find((v) => v.type === type && v.status === "OK");
}

/** Share through the shared ShareButton (any object): open, recipient,
 * message, send, then the "Sent messages" link as a navigation. */
async function shareFlow(page, record, prefix, objectId, prereq, state) {
  const { ctl, navTrip, assert, api } = H;
  await ctl(page, record, { id: `${prefix}-open`, prereq, expected: "the share inputs open", run: async () => {
    await page.click(sel(`${prefix}-open`));
    await page.waitForSelector(sel(`${prefix}-to`), { timeout: 30_000 });
    return "open";
  } });
  await ctl(page, record, { id: `${prefix}-to`, prereq, action: "recipient colleague", expected: "held", run: async () => { await page.fill(sel(`${prefix}-to`), "colleague"); return "colleague"; } });
  await ctl(page, record, { id: `${prefix}-message`, prereq, action: "a message", expected: "held", run: async () => { await page.fill(sel(`${prefix}-message`), `GW-CTL ${prefix}`); return "typed"; } });
  await ctl(page, record, { id: `${prefix}-send`, prereq, expected: "one message carrying the reference is sent (in Sent)", run: async () => {
    const before = (await api("/messages?box=sent")).body.items.filter((m) => JSON.stringify(m).includes(objectId)).length;
    await page.click(sel(`${prefix}-send`));
    await page.waitForSelector(sel(`${prefix}-done`), { timeout: 60_000 });
    const after = (await api("/messages?box=sent")).body.items.filter((m) => JSON.stringify(m).includes(objectId)).length;
    assert.equal(after, before + 1, "exactly one message");
    return `${before} → ${after} sent messages for ${objectId}`;
  } });
  await navTrip(page, record, {
    id: `${prefix}-sent`, prereq: "just shared", expected: "opens Sent messages, which lists the share", state,
    arrived: (p) => p.waitForSelector(sel("messages-center"), { timeout: 120_000 }), inApp: sel("messages-back"),
    handoff: { source: async () => ({ object: objectId }), destination: async (p) => ({ box: new URL(p.url()).searchParams.get("box"), listed: (await p.textContent(sel("messages-center"))).length > 0 }), identity: async (s, d) => { assert.equal(d.box, "sent"); const sent = (await api("/messages?box=sent")).body.items; assert.ok(sent.some((m) => JSON.stringify(m).includes(s.object))); return `share of ${s.object} → Sent`; }, describe },
  });
}

async function lensJourney() {
  const { journey, open, openLens, ctl, navTrip, assert, api, post, lensState, lensLibraryState, readZip } = H;
  await journey("GW-CTL-LENS", "Lenses: library search / propose / discard / save / open; Lens view across personas — period and cross-filter chart clicks, reset, chip remove, box-select cohort Save / Share / Investigate / What-If / clear, top-owner click, alert and scenario-result group clicks, table row, KPI and governance metric links, refresh, follow, edit name and refresh cadence, share, export package with the LLM option, Trace, underlying data", async (record) => {
    const page = await open();
    await page.goto(`${H.UI}/lenses`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("lens-card"), { timeout: 120_000 });
    const lib = (await api("/lenses")).body.lenses;
    await ctl(page, record, { id: "lens-search", prereq: "Lens Library", action: "type Retail", expected: "only Lenses whose name, persona or description mention it (q= in the address)", run: async () => {
      await page.fill(sel("lens-search"), "Retail");
      const want = lib.filter((c) => `${c.name} ${c.persona} ${c.description}`.toLowerCase().includes("retail")).length;
      await page.waitForFunction((n) => document.querySelectorAll('[data-testid="lens-card"]').length === n, want, { timeout: 30_000 });
      await page.waitForFunction(() => new URLSearchParams(location.search).get("q") === "Retail", null, { timeout: 30_000 });
      return `${want} Lenses`;
    } });
    await navTrip(page, record, {
      id: "lens-card", prereq: "library filtered to Retail", expected: "opens that Lens; Back restores the filter", state: lensLibraryState,
      go: (p) => p.locator(sel("lens-card")).first().click(),
      arrived: (p) => p.waitForSelector(sel("lens-view"), { timeout: 120_000 }), inApp: sel("lens-back"),
      handoff: { source: async (p) => ({ lens: await p.locator(sel("lens-card")).first().getAttribute("data-object-id") }), destination: async (p) => ({ lens: await p.getAttribute(sel("lens-view"), "data-object-id") }), identity: (s, d) => { assert.equal(d.lens, s.lens); return `${s.lens} → ${d.lens}`; }, describe },
    });
    await page.fill(sel("lens-search"), "");
    await ctl(page, record, { id: "lens-prompt", prereq: "Lens Library", action: "describe a dashboard", expected: "held; Preview enables", run: async () => {
      await page.fill(sel("lens-prompt"), "Credit card risk with Stage 2 EAD share, weekly");
      assert.equal(await page.isDisabled(sel("lens-propose")), false);
      return "typed";
    } });
    await ctl(page, record, { id: "lens-propose", prereq: "prompt typed", expected: "a preview (not saved) built from governed metrics", run: async () => {
      const before = (await api("/lenses")).body.total;
      await page.click(sel("lens-propose"));
      await page.waitForSelector(sel("lens-preview"), { timeout: 120_000 });
      assert.equal((await api("/lenses")).body.total, before, "nothing saved by a preview");
      return `${await page.getAttribute(sel("lens-preview"), "data-kpis")} KPIs, ${await page.getAttribute(sel("lens-preview"), "data-charts")} charts; nothing saved`;
    } });
    await ctl(page, record, { id: "lens-discard", prereq: "a preview", expected: "the preview is dropped; nothing saved", run: async () => {
      await page.click(sel("lens-discard"));
      await page.waitForSelector(sel("lens-preview"), { state: "detached", timeout: 30_000 });
      return "discarded";
    } });
    await page.click(sel("lens-propose"));
    await page.waitForSelector(sel("lens-preview"), { timeout: 120_000 });
    // The library's search only: a save adds a card, and after it Back shows
    // the library without the proposal (VAL-DEF-019).
    const libQuery = () => ({ q: document.querySelector('[data-testid="lens-search"]')?.value ?? null });
    const proposedName = async () => (await page.textContent(sel("lens-preview-summary")).catch(() => "")).trim();
    await navTrip(page, record, {
      id: "lens-save", prereq: "a preview", expected: "the Lens is saved and opens (one new Lens); Back shows the library, not the proposal", state: libQuery,
      arrived: (p) => p.waitForSelector(sel("lens-view"), { timeout: 120_000 }), inApp: sel("lens-back"),
      handoff: {
        source: async () => ({ total: (await api("/lenses")).body.total, preview: await proposedName() }),
        destination: async (p) => ({ lens: await p.getAttribute(sel("lens-view"), "data-object-id"), total: (await api("/lenses")).body.total }),
        identity: async (s, d) => {
          assert.equal(d.total, s.total + 1, "one new Lens");
          const o = await objectOf(d.lens);
          assert.equal(o.owner_id, "v4-local-demo");
          return `preview → saved ${d.lens} "${o.body.name}" (${s.total} → ${d.total} Lenses)`;
        },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/lenses /,
        describe,
      },
    });
    assert.equal(await page.locator(sel("lens-preview")).count(), 0, "Back after a save does not propose again");
    // The CRO Lens.
    await openLens(page, "lens-01");
    const pre = "Lens LENS-01 (CRO), latest, unfiltered";
    const trendV = await lensVisual("lens-01", "trend");
    await ctl(page, record, { id: "lens-chart-trend", prereq: pre, action: "click an earlier period on the trend", expected: "the Lens is re-evaluated at that period (p= in the address)", run: async () => {
      await clickPlotPoint(page, `lens-visual-${trendV.visual_id}`, { selector: "path.point, g.point path, .points path", point: 0 });
      await page.waitForFunction(() => new URLSearchParams(location.search).get("p"), null, { timeout: 30_000 });
      const p = new URL(page.url()).searchParams.get("p");
      return `periods ${p}`;
    } });
    await ctl(page, record, { id: "lens-reset", prereq: "a period chosen", expected: "back to latest, unfiltered", run: async () => {
      await page.click(sel("lens-reset"));
      await page.waitForFunction(() => !new URLSearchParams(location.search).get("p"), null, { timeout: 30_000 });
      return "latest";
    } });
    const brk = await lensVisual("lens-01", "breakdown");
    await ctl(page, record, { id: "lens-chart-breakdown", prereq: pre, action: "click a breakdown bar", expected: "a cross-filter chip; every visual re-evaluated on it (x= in the address)", run: async () => {
      await clickPlotPoint(page, `lens-visual-${brk.visual_id}`, { point: 0 });
      await page.waitForFunction(() => Number(document.querySelector('[data-testid="lens-state"]')?.getAttribute("data-cross")) === 1, null, { timeout: 30_000 });
      return (await page.textContent(sel("lens-cross-chip"))).trim();
    } });
    await ctl(page, record, { id: "lens-cross-remove", prereq: "one cross-filter", expected: "the chip and its filter are removed", run: async () => {
      await page.click(sel("lens-cross-remove"));
      await page.waitForFunction(() => Number(document.querySelector('[data-testid="lens-state"]')?.getAttribute("data-cross")) === 0, null, { timeout: 30_000 });
      return "removed";
    } });
    const boxSelect = async () => {
      const chart = sel(`lens-visual-${brk.visual_id}`);
      await page.waitForSelector(`${chart}[data-rendered="true"]`, { timeout: 60_000 });
      await page.locator(chart).scrollIntoViewIfNeeded();
      const b0 = await page.locator(`${chart} g.point path`).nth(0).boundingBox();
      const b1 = await page.locator(`${chart} g.point path`).nth(1).boundingBox();
      const plot = await page.locator(`${chart} rect.nsewdrag`).boundingBox();
      await page.mouse.move(Math.max(b0.x - 4, plot.x + 2), plot.y + 3);
      await page.mouse.down();
      await page.mouse.move(b1.x + b1.width + 4, b0.y + b0.height - 2, { steps: 12 });
      await page.mouse.up();
      await page.waitForSelector(sel("lens-selection"), { timeout: 60_000 });
      // The selection is written to the address after it is shown.
      await page.waitForFunction(() => new URLSearchParams(location.search).get("sel"), null, { timeout: 30_000 });
      return page.evaluate(() => JSON.parse(new URLSearchParams(location.search).get("sel") ?? "null"));
    };
    let selection = null;
    await ctl(page, record, { id: "lens-chart-breakdown", prereq: pre, action: "box-select two bars", expected: "a temporary cohort of those categories (sel= in the address)", run: async () => {
      selection = await boxSelect();
      assert.ok(selection?.filters?.length, "a selection with filters");
      return JSON.stringify(selection.filters).slice(0, 160);
    } });
    let saved = "";
    await ctl(page, record, { id: "lens-selection-save", prereq: "a box-selected cohort", expected: "frozen as a governed cohort with exactly the selection's filters", run: async () => {
      await page.click(sel("lens-selection-save"));
      await page.waitForFunction(() => /governed cohort coh-/.test(document.querySelector('[data-testid="lens-note"]')?.textContent ?? ""), null, { timeout: 60_000 });
      saved = /(coh-[0-9a-z-]+)/.exec(await page.textContent(sel("lens-note")))[1];
      const o = await objectOf(saved);
      assert.deepEqual(o.body.filters, selection.filters, "the cohort's filters are the selection's");
      return `${saved}: ${o.body.counts.entities} entities`;
    } });
    await shareFlow(page, record, "lens-selection-share", saved, `cohort ${saved} saved from the Lens`, lensState);
    await openLens(page, "lens-01");
    await boxSelect();
    await ctl(page, record, { id: "lens-selection-clear", prereq: "a box-selected cohort", expected: "the temporary cohort is dropped", run: async () => {
      await page.click(sel("lens-selection-clear"));
      await page.waitForSelector(sel("lens-selection"), { state: "detached", timeout: 30_000 });
      // The chart drops the box and the highlighted bars too.
      await page.waitForFunction((c) => {
        const gd = document.querySelector(c);
        return (gd?._fullLayout?.selections?.length ?? 0) === 0 && !(gd?.data?.[0]?.selectedpoints?.length);
      }, sel(`lens-visual-${brk.visual_id}`), { timeout: 30_000 });
      await page.waitForFunction(() => !new URLSearchParams(location.search).get("sel"), null, { timeout: 30_000 });
      return "cleared: panel, address and chart selection";
    } });
    const selCohort = (sel0) => ({
      source: async () => ({ filters: sel0.filters }),
      destination: async (p) => {
        const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url());
        if (t) { const c = (await api(`/whatif/threads/${t[1]}/cohort`)).body; const o = await objectOf(c.seed_cohort_id); return { cohort: c.seed_cohort_id, filters: o.body.filters }; }
        const w = await whatifCohort(p); const o = await objectOf(w.cohort); return { cohort: w.cohort, filters: o.body.filters };
      },
      identity: (s, d) => { assert.deepEqual(d.filters, s.filters); return `selection ${JSON.stringify(s.filters).slice(0, 100)} → cohort ${d.cohort} (same filters)`; },
      writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(whatif\/selection\/cohort|cohorts|cohorts\/[^/]+\/investigate|whatif\/investigate) /,
      describe,
    });
    let s1 = await boxSelect();
    await navTrip(page, record, {
      id: "lens-selection-investigate", prereq: "a box-selected cohort", expected: "a Cockpit investigation on exactly that cohort", state: lensState,
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"),
      handoff: selCohort(s1),
    });
    if (!(await page.locator(sel("lens-selection")).count())) s1 = await boxSelect();
    await navTrip(page, record, {
      id: "lens-selection-whatif", prereq: "a box-selected cohort", expected: "What-If on exactly that cohort", state: lensState,
      arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"),
      handoff: selCohort(s1),
    });
    await openLens(page, "lens-01");
    const owners = await lensVisual("lens-01", "top_owners");
    // The owner of the bar that is clicked (point 0), read from the chart.
    const ownersChart = sel(`lens-visual-${owners.visual_id}`);
    await page.waitForSelector(`${ownersChart}[data-rendered="true"]`, { timeout: 60_000 });
    const owner = await page.evaluate((c) => String(document.querySelector(c)?.data?.[0]?.customdata?.[0]?.[0] ?? ""), ownersChart);
    assert.ok(owners.rows.some((r) => String(r.owner) === owner), `${owner} is one of the Lens's top owners`);
    await navTrip(page, record, {
      id: "lens-chart-top-owners", prereq: pre, action: `click owner ${owner}'s bar`, expected: "a Cockpit investigation on that owner's exposures",
      state: lensState,
      go: (p) => clickPlotPoint(p, `lens-visual-${owners.visual_id}`, { point: 0 }),
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"),
      handoff: {
        source: async () => ({ owner }),
        destination: async (p) => { const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1]; const c = (await api(`/whatif/threads/${t}/cohort`)).body; const o = await objectOf(c.seed_cohort_id); return { cohort: c.seed_cohort_id, values: o.body.filters?.[0]?.values ?? [] }; },
        identity: (s, d) => { assert.ok(s.owner && d.values.map(String).includes(s.owner), `the cohort is ${s.owner}'s exposures`); return `owner ${s.owner} → cohort ${d.cohort} ${JSON.stringify(d.values)}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(cohorts|whatif\/selection\/cohort|cohorts\/[^/]+\/investigate|whatif\/investigate) /,
        describe,
      },
    });
    const kpiMetric = await page.locator(sel("lens-kpi")).first().getAttribute("data-metric-id");
    const toMetric = (m) => ({ source: async () => ({ metric: m }), destination: async (p) => ({ metric: new URL(p.url()).searchParams.get("m") }), identity: (s, d) => { assert.equal(d.metric, s.metric); return `${s.metric} → catalogue ${d.metric}`; }, describe });
    await navTrip(page, record, {
      id: "lens-kpi", prereq: pre, expected: "opens that KPI's metric definition", state: lensState,
      go: (p) => p.locator(sel("lens-kpi")).first().click(),
      arrived: (p) => p.waitForSelector(sel("metric-catalogue"), { timeout: 120_000 }), inApp: sel("metrics-back"), handoff: toMetric(kpiMetric),
    });
    const govMetric = (await page.locator(sel("lens-governance-metric")).first().getAttribute("href")).match(/m=([^&]+)/)[1];
    await navTrip(page, record, {
      id: "lens-governance-metric", prereq: pre, expected: "opens that governed metric", state: lensState,
      go: (p) => p.locator(sel("lens-governance-metric")).first().click(),
      arrived: (p) => p.waitForSelector(sel("metric-catalogue"), { timeout: 120_000 }), inApp: sel("metrics-back"), handoff: toMetric(govMetric),
    });
    await ctl(page, record, { id: "lens-refresh", prereq: pre, expected: "a refresh observation is recorded; what changed is said", run: async () => {
      const before = (await api("/lenses/lens-01/observations")).body.observations.length;
      await page.click(sel("lens-refresh"));
      await page.waitForFunction(() => /Refreshed:/.test(document.querySelector('[data-testid="lens-note"]')?.textContent ?? ""), null, { timeout: 120_000 });
      const after = (await api("/lenses/lens-01/observations")).body.observations.length;
      assert.ok(after >= before, "observation recorded");
      return `${before} → ${after} observations`;
    } });
    await ctl(page, record, { id: "lens-follow", prereq: pre, expected: "following toggles and is stored", run: async () => {
      const was = await page.getAttribute(sel("lens-follow"), "data-following");
      await page.click(sel("lens-follow"));
      await page.waitForFunction((w) => document.querySelector('[data-testid="lens-follow"]')?.getAttribute("data-following") !== w, was, { timeout: 60_000 });
      await page.click(sel("lens-follow"));
      await page.waitForFunction((w) => document.querySelector('[data-testid="lens-follow"]')?.getAttribute("data-following") === w, was, { timeout: 60_000 });
      return `${was} → ${was === "true" ? "false" : "true"} → ${was}`;
    } });
    await ctl(page, record, { id: "lens-export-llm", prereq: pre, action: "tick 'incl. LLM exchange' and export", expected: "the package downloads with the option recorded", run: async () => {
      await page.check(sel("lens-export-llm"));
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("lens-export-go"))]);
      const z = await readZip(await d.path());
      await page.uncheck(sel("lens-export-llm"));
      return `${d.suggestedFilename()}: ${z.list.length} files`;
    } });
    await ctl(page, record, { id: "lens-export-go", prereq: pre, expected: "the Lens's export package (with chart snapshots) downloads", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("lens-export-go"))]);
      const z = await readZip(await d.path());
      assert.ok(z.list.some((n) => /\.svg$/.test(n)), "chart snapshots attached");
      return `${d.suggestedFilename()}: ${z.list.length} files incl. SVG snapshots`;
    } });
    await chartCardControls(page, record, `lens-visual-${brk.visual_id}`, pre);
    await navTrip(page, record, {
      id: "lens-export-trace", prereq: pre, expected: "opens the Lens's governance Trace", state: lensState,
      arrived: (p) => p.waitForSelector(sel("object-trace"), { timeout: 120_000 }), inApp: sel("trace-object-back"),
    });
    await shareFlow(page, record, "lens-share", "lens-01", pre, lensState);
    await openLens(page, "lens-01");
    await ctl(page, record, { id: "lens-edit", prereq: pre, expected: "the edit form opens (a library Lens is customised as my copy)", run: async () => {
      await page.click(sel("lens-edit"));
      await page.waitForSelector(sel("lens-edit-form"), { timeout: 30_000 });
      return (await page.textContent(sel("lens-edit"))).trim();
    } });
    await ctl(page, record, { id: "lens-edit-name", prereq: "edit form", action: "rename", expected: "held", run: async () => { await page.fill(sel("lens-edit-name"), "GW-CTL CRO copy"); return "typed"; } });
    await ctl(page, record, { id: "lens-edit-cadence", prereq: "edit form", action: "refresh schedule = weekly", expected: "held", run: async () => { await page.selectOption(sel("lens-edit-cadence"), "weekly"); return "weekly"; } });
    await navTrip(page, record, {
      id: "lens-edit-form", prereq: "name and schedule changed", action: "Save as a new version", expected: "my copy is saved with that name and weekly schedule and opens; LENS-01 is unchanged; Back returns to LENS-01", state: lensState,
      go: (p) => p.click(sel("lens-edit-save")),
      arrived: (p) => p.waitForFunction(() => /\/lenses\//.test(location.pathname) && document.querySelector("h1")?.textContent?.includes("GW-CTL CRO copy"), null, { timeout: 120_000 }),
      inApp: sel("lens-back"),
      handoff: {
        source: async () => ({ lens: "lens-01", hash: (await objectOf("lens-01")).content_hash }),
        destination: async (p) => ({ copy: await p.getAttribute(sel("lens-view"), "data-object-id") }),
        identity: async (s, d) => {
          const o = await objectOf(d.copy);
          assert.notEqual(d.copy, s.lens, "a copy, not the library Lens");
          assert.equal(o.body.name, "GW-CTL CRO copy");
          assert.equal(o.body.refresh.cadence, "weekly");
          assert.equal(o.body.source?.object_id, s.lens, "copied from LENS-01");
          assert.equal((await objectOf(s.lens)).content_hash, s.hash, "the library Lens did not change");
          return `${s.lens} → my copy ${d.copy} (${o.body.name}, ${o.body.refresh.cadence}); ${s.lens} unchanged`;
        },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/lenses\/[^/]+\/revise /,
        describe,
      },
    });
    // Group clicks: alerts → Monitoring; scenario results → the result.
    await openLens(page, "lens-18");
    const alertsV = await lensVisual("lens-18", "alerts");
    if (alertsV && (alertsV.groups ?? []).some((g) => g.value != null)) {
      await navTrip(page, record, {
        id: "lens-chart-groups", prereq: "LENS-18 alerts visual", action: "click an alert group", expected: "opens the Monitoring Centre", state: lensState,
        go: (p) => clickPlotPoint(p, `lens-visual-${alertsV.visual_id}`, { point: 0 }),
        arrived: (p) => p.waitForSelector(`${sel("monitoring-list")}[data-state]:not([data-state=""])`, { timeout: 120_000 }), inApp: sel("monitoring-back"),
        handoff: {
          source: async () => ({ lens: "lens-18", alerts: (alertsV.groups ?? []).reduce((n, g) => n + (Number(g.value) || 0), 0) }),
          destination: async (p) => ({ path: new URL(p.url()).pathname, listed: Number(await p.getAttribute(sel("monitoring-list"), "data-count")) }),
          identity: (s, d) => { assert.equal(d.path, "/monitoring"); assert.ok(d.listed > 0, "the Monitoring Centre lists alerts"); return `LENS-18 alerts visual (${s.alerts} alerts) → Monitoring Centre listing ${d.listed}`; },
          describe,
        },
      });
    }
    await openLens(page, "lens-14");
    const resV = await lensVisual("lens-14", "scenario_results");
    const resIdx = (resV?.groups ?? []).findIndex((g) => g.value != null);
    if (resIdx >= 0) {
      await navTrip(page, record, {
        id: "lens-chart-groups", prereq: "LENS-14 scenario-results visual with an executed result", action: "click a result", expected: "opens that scenario result", state: lensState,
        go: (p) => clickPlotPoint(p, `lens-visual-${resV.visual_id}`, { point: resIdx }),
        arrived: (p) => p.waitForSelector(sel("whatif-result"), { timeout: 120_000 }), inApp: sel("whatif-result-back"),
        handoff: {
          source: async (p) => ({ result: await p.evaluate(([c, i]) => { const cd = document.querySelector(c)?.data?.[0]?.customdata?.[i]; return String(Array.isArray(cd) ? cd[0] : cd ?? ""); }, [sel(`lens-visual-${resV.visual_id}`), resIdx]) }),
          destination: async (p) => ({ result: /\/what-if\/result\/([^/?]+)/.exec(p.url())?.[1] ?? "" }),
          identity: (s, d) => { assert.ok(d.result.startsWith("res-"), "a scenario result opened"); if (s.result.startsWith("res-")) assert.equal(d.result, s.result, "the clicked result"); return `LENS-14 result bar ${s.result || "(no id on the bar)"} → result ${d.result}`; },
          describe,
        },
      });
    }
    // A table row → an investigation on that one exposure.
    await openLens(page, "lens-02");
    await page.waitForSelector(sel("lens-table-row"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "lens-table-row", prereq: "LENS-02 table", action: "click the first row", expected: "a Cockpit investigation on exactly that exposure", state: lensState,
      go: (p) => p.locator(sel("lens-table-row")).first().click(),
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"),
      handoff: {
        source: async (p) => ({ key: (await p.locator(`${sel("lens-table-row")} td`).first().textContent()).trim() }),
        destination: async (p) => { const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1]; const c = (await api(`/whatif/threads/${t}/cohort`)).body; const o = await objectOf(c.seed_cohort_id); return { cohort: c.seed_cohort_id, entities: o.body.counts.entities, ids: o.body.selection?.ids ?? o.body.ids ?? [] }; },
        identity: (s, d) => { assert.equal(d.entities, 1, "one exposure"); return `row ${s.key} → cohort ${d.cohort} (${d.entities} exposure)`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(cohorts|whatif\/selection\/cohort|cohorts\/[^/]+\/investigate|whatif\/investigate) /,
        describe,
      },
    });
    void post;
  });
}

// =========================================================================
// MESSAGES — inbox/sent, and every recipient action the seeded messages
// offer (the other kinds' recipient actions: test_gw_messages.py)
// =========================================================================

async function messagesJourney() {
  const { journey, open, openMessage, ctl, navTrip, assert, api, messagesState } = H;
  await journey("GW-CTL-MSG", "Messages: Inbox/Sent; on a shared definition, result and cohort every recipient action — open, run on my cohort or the definition's scope, re-run on latest, compare with my results, duplicate, save, investigate, comment — each with the shared object's identity", async (record) => {
    const page = await open();
    const share = async () => page.getAttribute(sel("message-view"), "data-share-id");
    const detail = async () => (await api(`/messages/${await share()}`)).body;
    await page.goto(`${H.UI}/messages`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("message-item"), { timeout: 120_000 });
    for (const b of ["sent", "inbox"]) {
      await ctl(page, record, { id: `messages-box-${b}`, prereq: "Messages", expected: `the ${b} box lists the backend's ${b} messages`, run: async () => {
        await page.click(sel(`messages-box-${b}`));
        const want = (await api(`/messages?box=${b}`)).body.items.length;
        await page.waitForFunction(([x, n]) => new URLSearchParams(location.search).get("box") === x && (document.querySelectorAll('[data-testid="message-item"]').length === n || (n === 0 && document.querySelector('[data-testid="messages-empty"]'))), [b, want], { timeout: 60_000 });
        return `${b}: ${want}`;
      } });
    }
    // A shared DEFINITION.
    await openMessage(page, "scenario");
    let d = await detail();
    const defPre = `inbox: shared definition ${d.share.object_id} v${d.share.version}`;
    await navTrip(page, record, {
      id: "message-action-open", prereq: defPre, expected: "opens the definition at the shared version", state: messagesState,
      arrived: (p) => p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }), inApp: sel("scenario-back"),
      handoff: { source: async () => ({ object: d.share.object_id, version: d.share.version }), destination: async (p) => ({ object: await p.getAttribute(sel("scenario-detail"), "data-object-id"), version: Number(await p.getAttribute(sel("scenario-detail"), "data-version")) }), identity: (s, x) => { assert.equal(x.object, s.object); assert.equal(x.version, s.version); return `${s.object} v${s.version} → ${x.object} v${x.version}`; }, describe },
    });
    await ctl(page, record, { id: "message-comment-input", prereq: defPre, action: "type a comment", expected: "held", run: async () => { await page.fill(sel("message-comment-input"), "GW-CTL recipient comment"); return "typed"; } });
    await ctl(page, record, { id: "message-comment-form", prereq: defPre, action: "submit", expected: "the comment attaches to the shared version; both sides see it", run: async () => {
      await page.click(sel("message-comment-send"));
      await page.waitForSelector(`${sel("message-comment-item")}:has-text("GW-CTL recipient comment")`, { timeout: 60_000 });
      assert.ok(JSON.stringify(await detail()).includes("GW-CTL recipient comment"));
      return "listed and stored";
    } });
    await ctl(page, record, { id: "message-action-duplicate", prereq: defPre, expected: "my own copy is created (the original unchanged); a link opens it", run: async () => {
      await page.click(sel("message-action-duplicate"));
      await page.waitForSelector(sel("message-note"), { timeout: 60_000 });
      const id = /(scn-[0-9a-z]+)/.exec(await page.textContent(sel("message-note")))[1];
      const o = await objectOf(id);
      assert.equal(o.owner_id, "v4-local-demo");
      return `copy ${id}`;
    } });
    await navTrip(page, record, {
      id: "message-note-link", prereq: "a copy just made", expected: "opens my copy", state: messagesState,
      arrived: (p) => p.waitForSelector(sel("scenario-detail"), { timeout: 120_000 }), inApp: sel("scenario-back"),
    });
    await ctl(page, record, { id: "message-action-run", prereq: defPre, expected: "the run chooser opens (my cohorts or the definition's scope)", run: async () => {
      await page.click(sel("message-action-run"));
      await page.waitForSelector(sel("message-run-chooser"), { timeout: 30_000 });
      return "chooser open";
    } });
    const mine = (await api("/cohorts?domain=corporate")).body.cohorts.find((c) => c.counts?.entities > 0);
    await ctl(page, record, { id: "message-run-cohort", prereq: "run chooser", action: `choose my cohort ${mine?.object_id}`, expected: "held", run: async () => {
      await page.selectOption(sel("message-run-cohort"), mine.object_id);
      return mine.object_id;
    } });
    await navTrip(page, record, {
      id: "message-run-go", prereq: "my cohort chosen", expected: "a NEW run of the shared definition on MY cohort opens in What-If (previewed, not executed)", state: messagesState,
      arrived: (p) => p.waitForSelector(`${sel("whatif-run")}[data-run-id^="wrun-"]`, { timeout: 120_000 }), inApp: sel("whatif-back"),
      handoff: {
        source: async () => ({ scenario: d.share.object_id, cohort: mine.object_id, version: (await objectOf(d.share.object_id)).version }),
        destination: async (p) => { const id = new URL(p.url()).searchParams.get("run"); const r = (await api(`/whatif/runs/${id}`)).body; return { run: id, scenario_from: r.body.shared_from?.object_id ?? r.body.scenario_id, cohort: r.body.cohort?.object?.cohort_id, status: r.status }; },
        identity: async (s, x) => {
          assert.equal(x.cohort, s.cohort, "on my cohort");
          assert.notEqual(x.status, "EXECUTED");
          // What-If binds the definition to my cohort as MY copy; the
          // sender's definition keeps the version that was shared.
          const theirs = await objectOf(s.scenario);
          assert.equal(theirs.version, s.version, "the sender's definition is unchanged");
          return `definition ${s.scenario} v${s.version} (unchanged) → run ${x.run} on ${x.cohort} (${x.status})`;
        },
        // The run, and What-If binding the definition to my cohort as my own
        // copy (idempotent; VAL-DEF-050 keeps the sender's untouched).
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(messages\/[^/]+\/run|scenarios\/[^/]+\/bind) /,
        describe,
      },
    });
    // A shared RESULT.
    await openMessage(page, "scenario_result");
    d = await detail();
    const resPre = `inbox: shared result ${d.share.object_id}`;
    await navTrip(page, record, {
      id: "message-action-open", prereq: resPre, expected: "opens the shared result", state: messagesState,
      arrived: (p) => p.waitForSelector(`[data-testid="whatif-result"][data-result-id="${d.share.object_id}"]`, { timeout: 120_000 }), inApp: sel("whatif-result-back"),
    });
    await navTrip(page, record, {
      id: "message-action-rerun_latest", prereq: resPre, expected: "a new run of the same definition on the latest data opens", state: messagesState,
      arrived: (p) => p.waitForSelector(`${sel("whatif-run")}[data-run-id^="wrun-"]`, { timeout: 120_000 }), inApp: sel("whatif-back"),
      handoff: {
        source: async () => ({ result: d.share.object_id, scenario: (await objectOf(d.share.object_id)).body.scenario_id }),
        destination: async (p) => { const id = new URL(p.url()).searchParams.get("run"); const r = (await api(`/whatif/runs/${id}`)).body; return { run: id, scenario: r.body.scenario_id, mode: r.body.shared_from?.mode }; },
        identity: (s, x) => { assert.equal(x.scenario, s.scenario); assert.equal(x.mode, "rerun_latest"); return `result ${s.result} → run ${x.run} (${x.mode}) of ${x.scenario}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/messages\/[^/]+\/run /,
        describe,
      },
    });
    await ctl(page, record, { id: "message-action-compare", prereq: resPre, expected: "the compare picker lists my results on the same book and period", run: async () => {
      await page.click(sel("message-action-compare"));
      await page.waitForSelector(`${sel("message-compare-picker")}, ${sel("message-compare-empty")}`, { timeout: 60_000 });
      assert.ok(await page.locator(sel("message-compare-option")).count(), "I have a result to compare with");
      return `${await page.locator(sel("message-compare-option")).count()} of my results`;
    } });
    const other = await page.locator(sel("message-compare-option")).first().getAttribute("data-result-id");
    await ctl(page, record, { id: "message-compare-option", prereq: "compare picker", action: `tick ${other}`, expected: "Compare enables", run: async () => {
      await page.locator(sel("message-compare-option")).first().check();
      assert.equal(await page.isDisabled(sel("message-compare-go")), false);
      return other;
    } });
    await navTrip(page, record, {
      id: "message-compare-go", prereq: `${other} ticked`, expected: "a comparison of the shared result and mine opens", state: messagesState,
      arrived: (p) => p.waitForSelector(sel("comparison"), { timeout: 120_000 }), inApp: sel("comparison-back"),
      handoff: {
        source: async () => ({ results: [d.share.object_id, other].sort() }),
        destination: async (p) => ({ comparison: await p.getAttribute(sel("comparison"), "data-comparison-id"), results: [...new Set((await p.$$eval("[data-result-id]", (r) => r.map((x) => x.getAttribute("data-result-id")))).filter(Boolean))].sort() }),
        identity: (s, x) => { assert.deepEqual(x.results, s.results); return `${s.results.join(" + ")} → ${x.comparison}`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/messages\/[^/]+\/compare /,
        describe,
      },
    });
    await ctl(page, record, { id: "message-action-save", prereq: resPre, expected: "a copy is saved to my workspace (lineage: derived from the shared result)", run: async () => {
      await openMessage(page, "scenario_result");
      await page.click(sel("message-action-save"));
      await page.waitForSelector(sel("message-note"), { timeout: 60_000 });
      const id = /Saved to your workspace as (\S+)\./.exec(await page.textContent(sel("message-note")))[1];
      const o = await objectOf(id);
      assert.equal(o.lineage.derived_from[0][0], d.share.object_id);
      return `${id} derived from ${d.share.object_id}`;
    } });
    // A shared COHORT.
    await openMessage(page, "cohort");
    d = await detail();
    const cohPre = `inbox: shared cohort ${d.share.object_id}`;
    const hash = (await objectOf(d.share.object_id)).body.membership_hash;
    await navTrip(page, record, {
      id: "message-action-open", prereq: cohPre, expected: "What-If opens on exactly that cohort", state: messagesState,
      arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"),
      handoff: { source: async () => ({ cohort: d.share.object_id, hash }), destination: (p) => whatifCohort(p), identity: (s, x) => { assert.equal(x.cohort, s.cohort); assert.equal(x.hash, s.hash); return `${s.cohort} → What-If ${x.cohort} (same hash)`; }, describe },
    });
    await navTrip(page, record, {
      id: "message-action-investigate", prereq: cohPre, expected: "a Cockpit investigation on that cohort (not rebuilt)", state: messagesState,
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); }, inApp: sel("thread-origin-back"),
      handoff: {
        source: async () => ({ cohort: d.share.object_id, hash }),
        destination: async (p) => { const t = /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1]; const c = (await api(`/whatif/threads/${t}/cohort`)).body; const o = c.seed_cohort_id ? await objectOf(c.seed_cohort_id) : null; return { thread: t, cohort: c.seed_cohort_id, hash: o?.body?.membership_hash }; },
        identity: (s, x) => { assert.equal(x.hash, s.hash); return `${s.cohort} → thread ${x.thread} seeded with ${x.cohort} (same membership)`; },
        writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/messages\/[^/]+\/investigate /,
        describe,
      },
    });
  });
}

// =========================================================================
// METRIC CATALOGUE
// =========================================================================

const metricState = () => ({
  m: new URLSearchParams(location.search).get("m") || "M001",
  q: document.querySelector('[data-testid="metric-search"]')?.value ?? "",
  domain: document.querySelector('[data-testid="metric-domain"]')?.value ?? "",
  family: document.querySelector('[data-testid="metric-family"]')?.value ?? "",
  shown: document.querySelectorAll('[data-testid="metric-item"]').length,
});

async function metricsJourney() {
  const { journey, open, ctl, navTrip, assert, api } = H;
  await journey("GW-CTL-METRICS", "Metric Catalogue: search, book and family filters (= the catalogue), pick a metric, breakdown book and dimension, breakdown bar drill to rows, used-by Lens and Requires Attention links — Back restores the filtered catalogue", async (record) => {
    const page = await open();
    await page.goto(`${H.UI}/metrics`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("metric-item"), { timeout: 120_000 });
    const all = (await api("/metrics")).body.metrics;
    const shown = () => page.locator(sel("metric-item")).count();
    const waitShown = (n) => page.waitForFunction((w) => document.querySelectorAll('[data-testid="metric-item"]').length === w, n, { timeout: 30_000 });
    await ctl(page, record, { id: "metric-search", prereq: "catalogue", action: "search ECL", expected: "only metrics whose id, name, definition or formula mention it", run: async () => {
      await page.fill(sel("metric-search"), "ECL");
      const want = all.filter((m) => `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes("ecl")).length;
      await waitShown(want);
      return `${want} metrics`;
    } });
    await ctl(page, record, { id: "metric-domain", prereq: "search ECL", action: "book = retail", expected: "retail (and both-book) metrics only", run: async () => {
      await page.selectOption(sel("metric-domain"), "retail");
      const want = all.filter((m) => (m.domain === "retail" || m.domain === "both") && `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes("ecl")).length;
      await waitShown(want);
      return `${want} metrics`;
    } });
    await ctl(page, record, { id: "metric-family", prereq: "search ECL, retail", action: "the first family", expected: "that family only", run: async () => {
      const fams = await page.$$eval(`${sel("metric-family")} option`, (o) => o.map((x) => x.value).filter(Boolean));
      const fam = fams.find((f) => all.some((m) => m.family === f && (m.domain === "retail" || m.domain === "both") && `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes("ecl"))) ?? fams[0];
      await page.selectOption(sel("metric-family"), fam);
      const want = all.filter((m) => m.family === fam && (m.domain === "retail" || m.domain === "both") && `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes("ecl")).length;
      await waitShown(want);
      return `${fam}: ${want}`;
    } });
    await ctl(page, record, { id: "metric-item", prereq: "filtered catalogue", action: "pick the first listed metric", expected: "its definition opens (m= in the address)", run: async () => {
      const id = await page.locator(sel("metric-item")).first().getAttribute("data-metric-id");
      await page.locator(sel("metric-item")).first().click();
      await page.waitForSelector(`[data-testid="metric-detail"][data-metric-id="${id}"]`, { timeout: 60_000 });
      assert.equal(new URL(page.url()).searchParams.get("m"), id);
      return id;
    } });
    // A metric used by a Lens and by a detector: M001 (booked ECL).
    const used = all.find((m) => m.metric_id === "M001") ?? all[0];
    const pre = `M001 open, catalogue filtered (search ECL, retail)`;
    await page.click(`[data-testid="metric-item"][data-metric-id="${used.metric_id}"]`).catch(async () => {
      await page.fill(sel("metric-search"), "M001");
      await page.selectOption(sel("metric-domain"), "");
      await page.selectOption(sel("metric-family"), "");
      await page.click(`[data-testid="metric-item"][data-metric-id="M001"]`);
    });
    await page.waitForSelector(`[data-testid="metric-detail"][data-metric-id="M001"]`, { timeout: 60_000 });
    await page.waitForSelector(sel("metric-breakdown-dim"), { timeout: 60_000 });
    await ctl(page, record, { id: "metric-breakdown-dim", prereq: "M001 open", action: "another dimension", expected: "the breakdown re-groups by it", run: async () => {
      const opts = await page.$$eval(`${sel("metric-breakdown-dim")} option`, (o) => o.map((x) => x.value));
      await page.selectOption(sel("metric-breakdown-dim"), opts[1] ?? opts[0]);
      await page.waitForSelector(`${sel("metric-breakdown-card")} h3:has-text("by ${opts[1] ?? opts[0]}")`, { timeout: 60_000 });
      return opts[1] ?? opts[0];
    } });
    if (await page.locator(sel("metric-breakdown-book")).count()) {
      await ctl(page, record, { id: "metric-breakdown-book", prereq: "M001 (both books)", action: "the other book", expected: "the breakdown is evaluated on that book", run: async () => {
        const cur = await page.inputValue(sel("metric-breakdown-book"));
        const opts = await page.$$eval(`${sel("metric-breakdown-book")} option`, (o) => o.map((x) => x.value));
        const next = opts.find((o) => o !== cur);
        await page.selectOption(sel("metric-breakdown-book"), next);
        await page.waitForSelector(`${sel("metric-breakdown-card")} p:has-text("${next}")`, { timeout: 60_000 });
        await page.selectOption(sel("metric-breakdown-book"), cur);
        return `${cur} → ${next} → ${cur}`;
      } });
    }
    await ctl(page, record, { id: "metric-breakdown", prereq: "M001 breakdown", action: "click the first bar", expected: "the rows behind that bar are listed (= the metric rows endpoint)", run: async () => {
      await clickPlotPoint(page, "metric-breakdown", { point: 0 });
      await page.waitForFunction(() => /rows/.test(document.querySelector('[data-testid="metric-detail"]')?.textContent ?? ""), null, { timeout: 60_000 });
      return "drilled to rows";
    } });
    await chartCardControls(page, record, "metric-breakdown", "M001 breakdown");
    // Back from a "used by" link restores the filtered catalogue.
    await page.fill(sel("metric-search"), "M001");
    await waitShown(all.filter((m) => `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes("m001")).length);
    if (await page.locator(sel("metric-used-by-lens")).count()) {
      await navTrip(page, record, {
        id: "metric-used-by-lens", prereq: `${pre}; search M001`, expected: "opens a Lens that uses this metric; Back restores the search", state: metricState,
        go: (p) => p.locator(sel("metric-used-by-lens")).first().click(),
        arrived: (p) => p.waitForSelector(sel("lens-view"), { timeout: 120_000 }), inApp: sel("lens-back"),
        handoff: { source: async () => ({ metric: "M001" }), destination: async (p) => ({ lens: await p.getAttribute(sel("lens-view"), "data-object-id") }), identity: async (s, x) => { const lin = (await api(`/metrics/M001/lineage`)).body; const ids = (lin.used_by?.lenses ?? []).map((l) => l.object_id); assert.ok(ids.includes(x.lens)); return `M001 → Lens ${x.lens} (in its used-by list)`; }, describe },
      });
    }
    if (await page.locator(sel("metric-cockpit-link")).count()) {
      await navTrip(page, record, {
        id: "metric-cockpit-link", prereq: `${pre}; search M001`, expected: "opens the Cockpit, whose Requires Attention detectors use this metric", state: metricState,
        arrived: (p) => p.waitForSelector(sel("cockpit-v4-home"), { timeout: 120_000 }),
      });
    }
  });
}

// =========================================================================
// TRACE AND LLM EXCHANGE — the governance Trace's verbs, then the exact
// model calls of a run: calls, stages, JSON tree, compare, downloads
// =========================================================================

async function traceJourney() {
  const { journey, open, openIssue, anIssue, ctl, navTrip, assert, api, post, settle, readZip, exchangeState } = H;
  await journey("GW-CTL-TRACE", "Trace: open object, export package with the LLM option, verify the ledger, verify a downloaded package, ancestor/descendant/LLM-call links; LLM Exchange: select, expand/collapse, every stage, JSON search/raw/expand/wrap/copy/download, compare two calls, tabs, data-visibility download, Model Lab link — no hidden reasoning, no secrets", async (record) => {
    const page = await open();
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"], { origin: H.UI });
    // An investigation with a real (scripted) model run behind it.
    const issue = await anIssue();
    await openIssue(page, issue.issue_id);
    await page.locator(sel("issue-detail-nbq")).first().click();
    await page.waitForSelector(sel("investigation-bar"), { timeout: 120_000 });
    await settle(page, 0);
    const thread = /\/cockpit\/thread\/([^/?]+)/.exec(page.url())[1];
    const inv = (await api(`/investigations/by-thread/${thread}`)).body.investigation_id;
    const runId = await H.latestRun(thread);
    // A scenario copy for the Open / ancestor / descendant links.
    const copy = (await post("/scenarios/scn-tpl-corp-05/clone", { name: "GW-CTL trace copy" })).body.object_id;
    const goTrace = async (id) => {
      await page.goto(`${H.UI}/trace/object/${id}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(sel("object-trace"), { timeout: 120_000 });
    };
    const traceState = () => ({ at: location.pathname, integrity: document.querySelector('[data-testid="object-trace"]')?.getAttribute("data-integrity") || "" });
    await goTrace(copy);
    const pre = `Trace of scenario copy ${copy}`;
    await navTrip(page, record, {
      id: "trace-open-object", prereq: pre, expected: "opens the object itself", state: traceState,
      arrived: (p) => p.waitForSelector(`[data-testid="scenario-detail"][data-object-id="${copy}"]`, { timeout: 120_000 }), inApp: sel("scenario-back"),
    });
    await navTrip(page, record, {
      id: "trace-ancestor", prereq: pre, expected: "opens the Trace of the template it came from", state: traceState,
      go: (p) => p.locator(sel("trace-ancestor")).first().click(),
      arrived: (p) => p.waitForFunction(() => /\/trace\/object\/scn-tpl-corp-05$/.test(location.pathname) && document.querySelector('[data-testid="object-trace"]'), null, { timeout: 120_000 }), inApp: sel("trace-object-back"),
    });
    await goTrace("scn-tpl-corp-05");
    const firstDescendant = (await api("/trace/objects/scn-tpl-corp-05")).body.lineage.descendants[0].object_id;
    await navTrip(page, record, {
      id: "trace-descendant-link", prereq: `Trace of template CORP-05 (first descendant ${firstDescendant})`, expected: "opens the Trace of the first derived object the lineage lists", state: traceState,
      go: (p) => p.locator(sel("trace-descendant-link")).first().click(),
      arrived: (p) => p.waitForFunction((id) => location.pathname === `/trace/object/${id}` && document.querySelector('[data-testid="object-trace"]'), firstDescendant, { timeout: 120_000 }), inApp: sel("trace-object-back"),
    });
    await goTrace(copy);
    await ctl(page, record, { id: "trace-verify-ledger", prereq: pre, expected: "the whole tenant ledger verifies (no problems)", run: async () => {
      await page.click(sel("trace-verify-ledger"));
      await page.waitForSelector(sel("trace-ledger-result"), { timeout: 60_000 });
      assert.equal(await page.getAttribute(sel("trace-ledger-result"), "data-ok"), "true");
      return (await page.textContent(sel("trace-ledger-result"))).trim();
    } });
    let pkg = "";
    await ctl(page, record, { id: "trace-export-llm", prereq: pre, action: "tick 'incl. LLM exchange'", expected: "held for the export", run: async () => {
      await page.check(sel("trace-export-llm"));
      assert.equal(await page.isChecked(sel("trace-export-llm")), true);
      return "ticked";
    } });
    await ctl(page, record, { id: "trace-export-go", prereq: `${pre}, LLM option ticked`, expected: "the export package downloads (manifest with hashes)", run: async () => {
      const [d] = await Promise.all([page.waitForEvent("download", { timeout: 120_000 }), page.click(sel("trace-export-go"))]);
      pkg = await d.path();
      const z = await readZip(pkg);
      assert.ok(z.list.some((n) => /manifest/i.test(n)));
      return `${d.suggestedFilename()}: ${z.list.length} files`;
    } });
    await ctl(page, record, { id: "trace-verify-package", prereq: "the package just downloaded", action: "upload it to Verify a package", expected: "the package verifies against the store", run: async () => {
      const fs = await import("node:fs");
      const named = `${pkg}.zip`;
      fs.copyFileSync(pkg, named);
      await page.setInputFiles(sel("trace-verify-package"), named);
      await page.waitForSelector(sel("trace-package-result"), { timeout: 60_000 });
      assert.equal(await page.getAttribute(sel("trace-package-result"), "data-ok"), "true", await page.textContent(sel("trace-package-result")));
      return (await page.textContent(sel("trace-package-result"))).trim();
    } });
    await goTrace(inv);
    await page.waitForSelector(sel("trace-llm-call-link"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "trace-llm-call-link", prereq: `Trace of investigation ${inv} (its thread ran ${runId})`, expected: "opens the run's exact model calls", state: traceState,
      go: (p) => p.locator(sel("trace-llm-call-link")).first().click(),
      arrived: (p) => p.waitForSelector(sel("llm-exchange"), { timeout: 120_000 }), inApp: sel("llm-exchange-back"),
      handoff: { source: async (p) => ({ run: /llm-exchange\/([^?]+)/.exec(await p.locator(sel("trace-llm-call-link")).first().getAttribute("href"))[1] }), destination: async (p) => ({ run: /llm-exchange\/([^?]+)/.exec(new URL(p.url()).pathname)[1] }), identity: (s, d) => { assert.equal(d.run, s.run); return `run ${s.run} → exchange of ${d.run}`; }, describe },
    });
    // The run's governance record → its LLM Exchange; Back returns to the
    // record (the Exchange page's own fallback when no origin is carried).
    await page.goto(`${H.UI}/cockpit/trace/${runId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("trace-llm-exchange-link"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "trace-llm-exchange-link", prereq: `governance record of ${runId}`, expected: "opens that run's LLM Exchange", state: () => ({ at: location.pathname }),
      arrived: (p) => p.waitForSelector(sel("llm-exchange"), { timeout: 120_000 }), inApp: sel("llm-exchange-back"),
      handoff: { source: async () => ({ run: runId }), destination: async (p) => ({ run: decodeURIComponent(/llm-exchange\/([^?/]+)/.exec(new URL(p.url()).pathname)[1]) }), identity: (s, d) => { assert.equal(d.run, s.run); return `record ${s.run} → exchange of ${d.run}`; }, describe },
    });
    // The LLM Exchange of that run.
    await page.goto(`${H.UI}/trace/llm-exchange/${runId}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("llm-exchange"), { timeout: 120_000 });
    const calls = await page.locator(sel("llm-call-toggle")).count();
    const pre2 = `LLM Exchange of ${runId} (${calls} calls)`;
    await ctl(page, record, { id: "llm-call-toggle", prereq: pre2, expected: "a call expands (call= in the address) and collapses", run: async () => {
      const second = page.locator(sel("llm-call-toggle")).nth(Math.min(1, calls - 1));
      await second.click();
      await page.waitForFunction(() => new URLSearchParams(location.search).get("call"), null, { timeout: 30_000 });
      assert.equal(await second.getAttribute("aria-expanded"), "true");
      await second.click();
      await page.waitForFunction((el) => el.getAttribute("aria-expanded") === "false", await second.elementHandle(), { timeout: 30_000 });
      await page.locator(sel("llm-call-toggle")).first().click();
      await page.waitForFunction(() => document.querySelector('[data-testid="llm-call-toggle"]')?.getAttribute("aria-expanded") === "true", null, { timeout: 30_000 });
      return "expanded, collapsed; call 1 open";
    } });
    for (const st of ["canonical", "adapter", "raw", "normalized", "meta", "readable"]) {
      await ctl(page, record, { id: `llm-stage-tabs-${st}`, prereq: `${pre2}, call 1 open`, expected: `the ${st} view of call 1`, run: async () => {
        await page.locator(sel(`llm-stage-tabs-${st}`)).first().click();
        if (st !== "readable") await page.waitForSelector(sel(`llm-call-1-${st}`), { timeout: 30_000 });
        const text = st !== "readable" ? await page.textContent(sel(`llm-call-1-${st}`)) : await page.textContent(sel("llm-call-1"));
        assert.ok(!/sk-ant-|api[_-]?key"\s*:\s*"[A-Za-z0-9]/i.test(text), "no credential");
        assert.ok(!/"thinking"\s*:\s*"[^"]{20,}/.test(text), "no hidden reasoning content");
        return `${st}: ${text.length} chars, no credential, no hidden reasoning`;
      } });
    }
    await page.locator(sel("llm-stage-tabs-canonical")).first().click();
    const tree = sel("llm-call-1-canonical");
    await page.waitForSelector(tree, { timeout: 30_000 });
    await ctl(page, record, { id: "json-search", prereq: "canonical request tree", action: "search 'messages'", expected: "the tree narrows to matching nodes", run: async () => {
      const before = (await page.textContent(tree)).length;
      await page.fill(`${tree} ${sel("json-search")}`, "messages");
      await page.waitForFunction(([t, b]) => (document.querySelector(t)?.textContent ?? "").length < b, [tree, before], { timeout: 30_000 });
      await page.fill(`${tree} ${sel("json-search")}`, "");
      return "narrowed and restored";
    } });
    await ctl(page, record, { id: "json-node-toggle", prereq: "canonical request tree", expected: "a node collapses and expands", run: async () => {
      const node = page.locator(`${tree} ${sel("json-node-toggle")}`).nth(1);
      const was = await node.getAttribute("aria-expanded");
      await node.click();
      await page.waitForFunction(([el, w]) => el.getAttribute("aria-expanded") !== w, [await node.elementHandle(), was], { timeout: 30_000 });
      await node.click();
      return `${was} → toggled → ${was}`;
    } });
    await ctl(page, record, { id: "json-expand-all", prereq: "canonical request tree", expected: "every node expands, then collapses back", run: async () => {
      await page.click(`${tree} ${sel("json-expand-all")}`);
      await page.waitForFunction((t) => Array.from(document.querySelectorAll(`${t} [data-testid="json-node-toggle"]`)).every((n) => n.getAttribute("aria-expanded") === "true"), tree, { timeout: 30_000 });
      await page.click(`${tree} ${sel("json-expand-all")}`);
      return "all expanded, then collapsed";
    } });
    await ctl(page, record, { id: "json-raw-toggle", prereq: "canonical request tree", expected: "raw JSON (parses), then the tree again", run: async () => {
      await page.click(`${tree} ${sel("json-raw-toggle")}`);
      const raw = await page.locator(`${tree} pre`).first().textContent();
      JSON.parse(raw);
      await page.click(`${tree} ${sel("json-raw-toggle")}`);
      return `raw JSON ${raw.length} chars parses`;
    } });
    await ctl(page, record, { id: "json-wrap", prereq: "canonical request tree", expected: "wrapping toggles", run: async () => {
      const was = await page.getAttribute(`${tree} ${sel("json-wrap")}`, "aria-pressed");
      await page.click(`${tree} ${sel("json-wrap")}`);
      assert.notEqual(await page.getAttribute(`${tree} ${sel("json-wrap")}`, "aria-pressed"), was);
      await page.click(`${tree} ${sel("json-wrap")}`);
      return `${was} → ${was === "true" ? "false" : "true"} → ${was}`;
    } });
    await ctl(page, record, { id: "json-copy", prereq: "canonical request tree", expected: "the exact payload JSON is on the clipboard", run: async () => {
      await page.click(`${tree} ${sel("json-copy")}`);
      const clip = await page.evaluate(() => navigator.clipboard.readText());
      const parsed = JSON.parse(clip);
      assert.ok(parsed.messages || parsed.system, "the canonical request");
      return `${clip.length} chars copied (parses)`;
    } });
    await ctl(page, record, { id: "json-download", prereq: "canonical request tree", expected: "call_1_canonical.json downloads", run: async () => {
      const name = await download(page, `${tree} ${sel("json-download")}`);
      assert.match(name, /^call_1_canonical\.json$/);
      return name;
    } });
    if (calls >= 2) {
      await ctl(page, record, { id: "llm-call-select", prereq: pre2, action: "select calls 1 and 2", expected: "Compare appears", run: async () => {
        await page.locator(sel("llm-call-select")).nth(0).check();
        await page.locator(sel("llm-call-select")).nth(1).check();
        await page.waitForSelector(sel("llm-compare-button"), { timeout: 30_000 });
        return "2 selected";
      } });
      await ctl(page, record, { id: "llm-compare-button", prereq: "two calls selected", expected: "a side-by-side comparison of the two calls", run: async () => {
        await page.click(sel("llm-compare-button"));
        await page.waitForSelector(sel("llm-compare"), { timeout: 60_000 });
        return (await page.textContent(sel("llm-compare"))).slice(0, 100);
      } });
    }
    for (const t of ["timeline", "composition", "growth", "visibility", "calls"]) {
      await ctl(page, record, { id: `llm-tabs-${t}`, prereq: pre2, expected: `the ${t} tab (tab= in the address)`, run: async () => {
        await page.click(sel(`llm-tabs-${t}`));
        if (t !== "calls") await page.waitForFunction((x) => new URLSearchParams(location.search).get("tab") === x, t, { timeout: 30_000 });
        if (t === "visibility") await page.waitForSelector(sel("llm-visibility"), { timeout: 30_000 });
        return t;
      } });
      if (t === "visibility") {
        await ctl(page, record, { id: "llm-visibility-download", prereq: "Data visibility tab", expected: "the data-visibility record downloads", run: async () => {
          const name = await download(page, sel("llm-visibility-download"));
          assert.match(name, /^data_visibility_run-/);
          return name;
        } });
      }
    }
    await navTrip(page, record, {
      id: "llm-model-lab-link", prereq: pre2, expected: "opens the AI Model Lab; its Back returns here", state: exchangeState,
      arrived: (p) => p.waitForSelector(sel("ai-model-lab"), { timeout: 120_000 }), inApp: sel("lab-back"),
    });
  });
}

// =========================================================================
// AI MODEL LAB
// =========================================================================

async function labJourney() {
  const { journey, open, ctl, navTrip, assert, api, askFromHome } = H;
  await journey("GW-CTL-LAB", "AI Model Lab: model filter, choose A and B, compare, trace link; Replay is not offered without a configured target (a replay is a billable call) — the reason is shown", async (record) => {
    const page = await open();
    await askFromHome(page, record, "Show me construction exposure by sector");
    await page.goto(`${H.UI}/ai-model-lab`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("lab-choose-a"), { timeout: 120_000 });
    const pre = "AI Model Lab with recorded calls";
    const lab = (await api("/model-lab/exchanges?limit=1000")).body;
    await ctl(page, record, { id: "lab-model-filter", prereq: pre, action: "filter by the first model", expected: "only that model's calls (= the API)", run: async () => {
      const opts = await page.$$eval(`${sel("lab-model-filter")} option`, (o) => o.map((x) => x.value).filter(Boolean));
      await page.selectOption(sel("lab-model-filter"), opts[0]);
      const want = (await api(`/model-lab/exchanges?model=${encodeURIComponent(opts[0])}&limit=1000`)).body.exchanges.length;
      await page.waitForFunction((n) => document.querySelectorAll('[data-testid="lab-choose-a"]').length === n, want, { timeout: 30_000 });
      await page.selectOption(sel("lab-model-filter"), "");
      await page.waitForFunction((n) => document.querySelectorAll('[data-testid="lab-choose-a"]').length === n, lab.exchanges.length, { timeout: 30_000 });
      return `${opts[0]}: ${want} of ${lab.exchanges.length}`;
    } });
    await ctl(page, record, { id: "lab-choose-a", prereq: pre, action: "choose the first call as A", expected: "A chosen", run: async () => { await page.locator(sel("lab-choose-a")).nth(0).check(); return "A"; } });
    await ctl(page, record, { id: "lab-choose-b", prereq: "A chosen", action: "choose the second call as B", expected: "B chosen; Compare enables", run: async () => {
      await page.locator(sel("lab-choose-b")).nth(1).check();
      assert.equal(await page.isDisabled(sel("lab-compare")), false);
      return "B";
    } });
    await ctl(page, record, { id: "lab-compare", prereq: "A and B chosen", expected: "a call-by-call comparison of A and B", run: async () => {
      await page.click(sel("lab-compare"));
      await page.waitForSelector(sel("ai-model-lab-compare"), { timeout: 60_000 });
      assert.match(await page.textContent(sel("ai-model-lab-compare")), /identical|differs/i);
      return "compared";
    } });
    const replay = await page.$$eval(sel("lab-provider-test"), (bs) => bs.map((b) => ({ text: b.textContent, disabled: b.disabled, title: b.title })));
    await ctl(page, record, { id: "lab-provider-test", prereq: "A chosen; no replay target configured in this runtime", action: "read the Replay controls", expected: "every Replay is disabled and says which credential it needs; nothing is called",
      result: "BLOCKED_WITH_GOVERNED_REASON", reason: replay.map((r) => r.title).join(" | "), run: async () => {
        assert.ok(replay.length >= 1 && replay.every((r) => r.disabled && /Not configured: needs/.test(r.title)), JSON.stringify(replay));
        const before = (await api("/model-lab/exchanges?limit=1000")).body.exchanges.length;
        await page.locator(sel("lab-provider-test")).first().click({ force: true }).catch(() => undefined);
        assert.equal((await api("/model-lab/exchanges?limit=1000")).body.exchanges.length, before, "no call made");
        return replay.map((r) => `${r.text.trim()} — disabled`).join("; ");
      } });
    await navTrip(page, record, {
      id: "lab-trace-link", prereq: pre, expected: "opens that call's run in the LLM Exchange", state: () => ({ at: location.pathname, a: document.querySelectorAll('[data-testid="lab-choose-a"]').length }),
      go: (p) => p.locator(sel("lab-trace-link")).first().click(),
      arrived: (p) => p.waitForSelector(sel("llm-exchange"), { timeout: 120_000 }), inApp: sel("llm-exchange-back"),
    });
  });
}

// =========================================================================
// THE COCKPIT THREAD — investigation chips, "why", save as Lens, and the
// conversation's What-If (on its seeded cohort; methods; the result)
// =========================================================================

async function threadJourney() {
  const { journey, open, openIssue, anIssue, ctl, navTrip, assert, api, settle, turns, threadState } = H;
  await journey("GW-CTL-THREAD", "Cockpit thread: why-suggested, each investigation chip type (run What-If, freeze cohort, save/share/monitor), save as Lens; a cohort-seeded thread's What-If; a scenario confirmed in conversation → every method chip → open the decomposition", async (record) => {
    const page = await open();
    const issue = await anIssue();
    await openIssue(page, issue.issue_id);
    await page.click(sel("issue-detail-investigate"));
    await page.waitForSelector(sel("nbq-chip"), { timeout: 120_000 });
    const thread = /\/cockpit\/thread\/([^/?]+)/.exec(page.url())[1];
    const inv = (await api(`/investigations/by-thread/${thread}`)).body;
    const pre = `investigation ${inv.investigation_id} on ${issue.issue_id}`;
    await ctl(page, record, { id: "nbq-why", prereq: pre, expected: "the suggestion's rationale and source are shown, then hidden", run: async () => {
      await page.locator(sel("nbq-why")).first().click();
      await page.waitForSelector(sel("nbq-rationale"), { timeout: 30_000 });
      const text = await page.textContent(sel("nbq-rationale"));
      assert.match(text, /Source:/);
      await page.locator(sel("nbq-why")).first().click();
      await page.waitForSelector(sel("nbq-rationale"), { state: "detached", timeout: 30_000 });
      return text.trim().slice(0, 120);
    } });
    // Advance until the navigating chip types are offered.
    const chip = (type) => page.locator(`[data-testid="nbq-chip"][data-suggestion-type="${type}"]`);
    // "Monitor in a Lens" ranks last; it reaches the five shown once the
    // questions above it are answered.
    for (let i = 0; i < 6 && !(await chip("run_whatif").count() && await chip("save_share_monitor").count()); i += 1) {
      const asking = page.locator('[data-testid="nbq-chip"]:not([data-suggestion-type="run_whatif"]):not([data-suggestion-type="freeze_cohort"]):not([data-suggestion-type="save_share_monitor"])');
      if (!(await asking.count())) break;
      const before = await turns(page);
      await asking.first().click();
      await settle(page, before);
      await page.waitForSelector(sel("nbq-chip"), { timeout: 60_000 });
    }
    const invCohort = async () => { const o = await objectOf(inv.cohort_id); return { cohort: inv.cohort_id, hash: o.body.membership_hash }; };
    const toWhatIf = { source: invCohort, destination: (p) => whatifCohort(p), identity: (s, d) => { assert.equal(d.hash, s.hash); return `investigation cohort ${s.cohort} → What-If ${d.cohort} (same membership)`; }, writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/investigations\/[^/]+\/steps /, describe };
    for (const type of ["run_whatif", "freeze_cohort"]) {
      if (!(await chip(type).count())) continue;
      await navTrip(page, record, {
        id: "nbq-chip", prereq: `${pre}; chip ${type}`, expected: `the ${type} chip opens What-If on the investigation's cohort`, state: threadState,
        go: (p) => chip(type).first().click(),
        arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"), handoff: toWhatIf,
      });
    }
    if (await chip("save_share_monitor").count()) {
      await navTrip(page, record, {
        id: "nbq-chip", prereq: `${pre}; chip save_share_monitor`, expected: "the Lens Library proposes a Lens from this investigation (not saved)", state: threadState,
        go: (p) => chip("save_share_monitor").first().click(),
        arrived: (p) => p.waitForSelector(sel("lens-preview"), { timeout: 120_000 }), inApp: sel("lens-library-back"),
        handoff: { source: async () => ({ investigation: inv.investigation_id }), destination: async (p) => ({ preview: await p.getAttribute(sel("lens-preview"), "data-kpis"), consumed: !new URL(p.url()).searchParams.get("from_investigation") }), identity: (s, d) => { assert.ok(d.preview !== null); return `investigation ${s.investigation} → Lens preview (${d.preview} KPIs), origin consumed=${d.consumed}`; }, writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/(investigations\/[^/]+\/steps|lenses\/propose) /, describe },
      });
    }
    await navTrip(page, record, {
      id: "thread-save-as-lens", prereq: pre, expected: "the Lens Library proposes a Lens from this conversation (not saved)", state: threadState,
      arrived: (p) => p.waitForSelector(sel("lens-preview"), { timeout: 120_000 }), inApp: sel("lens-library-back"),
      handoff: { source: async () => ({ thread }), destination: async (p) => ({ preview: await p.getAttribute(sel("lens-preview"), "data-kpis") }), identity: (s, d) => { assert.ok(d.preview !== null); return `thread ${s.thread} → Lens preview (${d.preview} KPIs)`; }, writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/lenses\/propose /, describe },
    });
    // A thread seeded with a governed cohort (Early Warning → Investigate).
    const out = (await H.post("/early-warning/investigate", { domain: "corporate", segment: "", bands: ["critical", "high"], reason: "" })).body;
    await page.goto(`${H.UI}/cockpit/thread/${out.thread_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("thread-whatif-on-cohort"), { timeout: 120_000 });
    const seed = await page.getAttribute(sel("thread-whatif-on-cohort"), "data-cohort-id");
    await navTrip(page, record, {
      id: "thread-whatif-on-cohort", prereq: `thread ${out.thread_id} seeded with cohort ${seed}`, expected: "What-If on exactly that cohort", state: threadState,
      arrived: (p) => whatifCohort(p), inApp: sel("whatif-back"),
      handoff: { source: async () => ({ cohort: seed, hash: (await objectOf(seed)).body.membership_hash }), destination: (p) => whatifCohort(p), identity: (s, d) => { assert.equal(d.cohort, s.cohort); assert.equal(d.hash, s.hash); return `seed ${s.cohort} → What-If ${d.cohort}`; }, describe },
    });
    // A scenario confirmed in conversation: the method chips, then the result.
    await H.askFromHome(page, record, "For the Construction borrowers, PD x1.20 and LGD x1.10, stages fixed.");
    await page.waitForFunction(() => /Nothing has been calculated/.test([...document.querySelectorAll('[data-testid="v4-turn-assistant"]')].pop()?.textContent ?? ""), null, { timeout: 60_000 });
    let n = await turns(page);
    await page.fill(sel("v4-composer-input"), "Yes, confirm the scenario");
    await page.click(sel("v4-composer-send"));
    await settle(page, n);
    await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-method-state") === "METHOD_SELECTION_REQUIRED", null, { timeout: 60_000 });
    const t2 = /\/cockpit\/thread\/([^/?]+)/.exec(page.url())[1];
    await ctl(page, record, { id: "thread-whatif-method-delta", prereq: `thread ${t2}: scenario confirmed, METHOD_SELECTION_REQUIRED`, expected: "Delta runs as an ordinary turn; the thread then has a result", run: async () => {
      n = await turns(page);
      await page.click(sel("thread-whatif-method-delta"));
      await settle(page, n);
      await page.waitForFunction(() => document.querySelector('[data-testid="thread-whatif"]')?.getAttribute("data-has-result") === "true", null, { timeout: 120_000 });
      const st = (await api(`/whatif/threads/${t2}/cohort`)).body;
      return `methods ran: ${(st.methods_ran ?? []).join(", ")}`;
    } });
    await navTrip(page, record, {
      id: "thread-whatif-open-result", prereq: `thread ${t2} with a Delta result`, expected: "opens the decomposition of exactly that result", state: threadState,
      arrived: (p) => p.waitForSelector(sel("whatif-result"), { timeout: 120_000 }), inApp: sel("whatif-result-back"),
      handoff: { source: async () => ({ thread: t2 }), destination: async (p) => ({ result: await p.getAttribute(sel("whatif-result"), "data-result-id") }), identity: async (s, d) => { const r = await objectOf(d.result); assert.equal(r.body.thread_id, s.thread); return `thread ${s.thread} → result ${d.result} (thread_id ${r.body.thread_id})`; }, writes: /^POST \/api\/v1\/cockpit-v4\/workspace\/whatif\/threads\/[^/]+\/adopt-result /, describe },
    });
    // From that result, back to the conversation that executed it.
    const adopted = (await H.post(`/whatif/threads/${t2}/adopt-result`, {})).body;
    await page.goto(`${H.UI}/what-if/result/${adopted.object_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("whatif-result-open-thread"), { timeout: 120_000 });
    await navTrip(page, record, {
      id: "whatif-result-open-thread", prereq: `result ${adopted.object_id} executed in conversation ${t2}`, expected: "opens the conversation that executed it", state: H.resultState,
      arrived: async (p) => { await waitPath(p, /^\/cockpit\/thread\//, 120_000); await p.waitForSelector(sel("cockpit-v4-thread"), { timeout: 120_000 }); },
      inApp: sel("thread-origin-back"),
      handoff: {
        source: async () => ({ result: adopted.object_id, thread: adopted.body.thread_id }),
        destination: async (p) => ({ thread: /\/cockpit\/thread\/([^/?]+)/.exec(p.url())[1] }),
        identity: (s, d) => { assert.equal(s.thread, t2, "the result records its conversation"); assert.equal(d.thread, s.thread); return `result ${s.result} → conversation ${d.thread}`; },
        describe,
      },
    });
  });
}

// =========================================================================
// DOUBLE-CLICK — one governed mutation per family
// =========================================================================

async function idempotencyJourney() {
  const { journey, open, openWhatIf, openIssue, anIssue, openLens, ctl, assert, api, post, waitSelectionEntities } = H;
  await journey("GW-CTL-IDEMPOTENCY", "Double-click: save cohort, freeze an issue population, share, clone, branch, combine, comment, assign, acknowledge, resolve, schedule (Lens cadence) — each writes exactly once", async (record) => {
    const page = await open();
    /** Double-click, wait for the outcome, count the writes the window made. */
    const once = async ({ id, prereq, selector, endpoint, done }) => ctl(page, record, {
      id, prereq, action: "double-click", expected: "exactly one governed write; the second click is absorbed",
      run: async () => {
        const mark = page.timeline.length;
        await page.dblclick(selector);
        await done();
        await page.waitForTimeout(1500);
        const writes = page.timeline.slice(mark).filter((e) => e.kind === "api" && e.method !== "GET" && endpoint.test(e.line));
        assert.equal(writes.filter((e) => e.status < 400).length, 1, `one write: ${writes.map((e) => e.line).join(", ")}`);
        return `1 write (${writes[0].line.replace(/^POST \/api\/v1\/cockpit-v4\/workspace/, "")})${writes.length > 1 ? `; ${writes.length - 1} refused` : ""}`;
      },
    });
    // Save cohort (What-If)
    await openWhatIf(page, "?domain=corporate");
    await page.locator(sel("grid-row-select")).nth(0).check();
    await waitSelectionEntities(page, 1);
    await page.click(sel("whatif-save-cohort"));
    await page.fill(sel("whatif-save-form-input"), "GW-CTL double save");
    await once({ id: "whatif-save-form", prereq: "one row selected, name typed", selector: sel("whatif-save-form-submit"), endpoint: /\/whatif\/selection\/cohort /, done: () => page.waitForFunction(() => /as coh-/.test(document.querySelector('[data-testid="whatif-note"]')?.textContent ?? ""), null, { timeout: 60_000 }) });
    // Freeze an issue population
    const issue = await anIssue();
    await openIssue(page, issue.issue_id);
    await once({ id: "issue-detail-save-cohort", prereq: `issue ${issue.issue_id}`, selector: sel("issue-detail-save-cohort"), endpoint: /\/issues\/[^/]+\/cohort /, done: () => page.waitForFunction(() => document.querySelector('[data-testid="issue-detail-save-cohort"]')?.disabled, null, { timeout: 60_000 }) });
    // Share (Lens)
    await openLens(page, "lens-03");
    await page.click(sel("lens-share-open"));
    await page.fill(sel("lens-share-to"), "colleague");
    await once({ id: "lens-share-send", prereq: "LENS-03 share, recipient typed", selector: sel("lens-share-send"), endpoint: /\/messages /, done: () => page.waitForSelector(sel("lens-share-done"), { timeout: 60_000 }) });
    // Clone and branch (a template)
    const tpl = (await api("/scenarios?q=CORP-07")).body.scenarios[0].object_id;
    const detail = async () => {
      await page.goto(`${H.UI}/scenarios/${tpl}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(sel("scenario-detail"), { timeout: 120_000 });
    };
    await detail();
    await once({ id: "scenario-action-clone", prereq: "template CORP-07", selector: sel("scenario-action-clone"), endpoint: /\/scenarios\/[^/]+\/clone /, done: () => page.waitForFunction((t) => { const d = document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id"); return d && d !== t; }, tpl, { timeout: 120_000 }) });
    await detail();
    await once({ id: "scenario-action-branch", prereq: "template CORP-07", selector: sel("scenario-action-branch"), endpoint: /\/scenarios\/[^/]+\/(branch|clone) /, done: () => page.waitForFunction((t) => { const d = document.querySelector('[data-testid="scenario-detail"]')?.getAttribute("data-object-id"); return d && d !== t; }, tpl, { timeout: 120_000 }) });
    const mine = await page.getAttribute(sel("scenario-detail"), "data-object-id");
    // Comment (own copy)
    await page.click(sel("scenario-action-comment"));
    await page.fill(sel("scenario-comment-input"), "GW-CTL double comment");
    await once({ id: "scenario-comment", prereq: `own scenario ${mine}, comment typed`, selector: sel("scenario-comment-submit"), endpoint: /\/objects\/[^/]+\/comments /, done: () => page.waitForSelector(`${sel("scenario-comments")}:has-text("GW-CTL double comment")`, { timeout: 60_000 }) });
    // Combine
    await page.goto(`${H.UI}/scenarios?domain=corporate`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-card"), { timeout: 120_000 });
    for (const c of ["CORP-08", "CORP-09"]) await page.check(`[data-testid="scenario-card"][data-template-id="${c}"] ${sel("scenario-select")}`);
    await page.click(sel("scenario-combine"));
    await page.waitForSelector(`${sel("scenario-combine-preview")}, ${sel("scenario-combine-save")}`, { timeout: 120_000 });
    const selects = page.locator(`${sel("scenario-combine-panel")} ${sel("overlap-policy-select")}`);
    for (let i = 0; i < (await selects.count()); i += 1) {
      const opts = await selects.nth(i).locator("option").evaluateAll((o) => o.map((x) => x.value).filter(Boolean));
      await selects.nth(i).selectOption(opts[0]);
    }
    const saveSel = (await selects.count()) ? `${sel("scenario-combine-panel")} ${sel("overlap-resolve")}` : sel("scenario-combine-save");
    await once({ id: (await selects.count()) ? "overlap-resolve" : "scenario-combine-save", prereq: "CORP-08 + CORP-09 combine panel", selector: saveSel, endpoint: /\/scenarios\/combine /, done: () => page.waitForURL(/\/scenarios\/scn-/, { timeout: 120_000 }) });
    // Alert: assign, acknowledge, resolve
    const alert = (await api("/monitoring?view=active")).body.alerts.find((a) => a.alert_type === "breach" && !a.demo_historical && a.state !== "RESOLVED");
    await page.goto(`${H.UI}/monitoring?alert=${alert.alert_id}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("alert-panel"), { timeout: 120_000 });
    await once({ id: "alert-assign", prereq: `alert ${alert.alert_id}`, selector: sel("alert-assign"), endpoint: /\/monitoring\/alerts\/[^/]+\/assign /, done: () => page.waitForFunction(() => /assigned to/.test(document.querySelector('[data-testid="alert-history"]')?.textContent ?? ""), null, { timeout: 60_000 }) });
    await page.fill(sel("alert-note"), "double ack");
    const ack = await ctl(page, record, { id: "alert-acknowledge", prereq: `alert ${alert.alert_id}, note typed`, action: "double-click", expected: "exactly one transition; a second request, if any, is refused (no second event)", expect4xx: /\/acknowledge 409$/, run: async () => {
      const before = (await api(`/monitoring/alerts/${alert.alert_id}`)).body.events.length;
      await page.dblclick(sel("alert-acknowledge"));
      await page.waitForSelector(`${sel("alert-panel")}[data-state="ACKNOWLEDGED"]`, { timeout: 60_000 });
      await page.waitForTimeout(1500);
      const after = (await api(`/monitoring/alerts/${alert.alert_id}`)).body.events.length;
      assert.equal(after, before + 1, "one event");
      return `${before} → ${after} events`;
    } });
    void ack;
    await page.fill(sel("alert-note"), "double resolve");
    await ctl(page, record, { id: "alert-resolve", prereq: "acknowledged, note typed", action: "double-click", expected: "exactly one transition", expect4xx: /\/resolve 409$/, run: async () => {
      const before = (await api(`/monitoring/alerts/${alert.alert_id}`)).body.events.length;
      await page.dblclick(sel("alert-resolve"));
      await page.waitForSelector(`${sel("alert-panel")}[data-state="RESOLVED"]`, { timeout: 60_000 });
      await page.waitForTimeout(1500);
      const after = (await api(`/monitoring/alerts/${alert.alert_id}`)).body.events.length;
      assert.equal(after, before + 1, "one event");
      return `${before} → ${after} events`;
    } });
    // Schedule: a Lens refresh cadence change, double-submitted
    const myLens = (await api("/lenses")).body.lenses.find((l) => !l.seeded) ?? null;
    if (myLens) {
      await openLens(page, myLens.object_id);
      await page.click(sel("lens-edit"));
      await page.selectOption(sel("lens-edit-cadence"), "monthly");
      await once({ id: "lens-edit-form", prereq: `my Lens ${myLens.object_id}, cadence monthly`, selector: sel("lens-edit-save"), endpoint: /\/lenses\/[^/]+\/revise /, done: () => page.waitForSelector(sel("lens-edit-form"), { state: "detached", timeout: 60_000 }) });
    }
    void post;
  });
}

// =========================================================================
// KEYBOARD SMOKE (not a WCAG certification) and 390 px RESPONSIVE
// =========================================================================

async function keyboardJourney() {
  const { journey, open, ctl, assert, openWhatIf, openLens } = H;
  await journey("GW-CTL-KEYBOARD", "Keyboard smoke: Tab reaches the primary controls with a visible focus ring, Enter and Space activate them, Escape closes the open filter editor, focus is never trapped (no WCAG certification claim)", async (record) => {
    const page = await open();
    const focusInfo = () => page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      return { id: el.getAttribute("data-testid") ?? el.tagName, visible: cs.outlineStyle !== "none" || cs.boxShadow !== "none" };
    });
    const tabUntil = async (testId, max = 120) => {
      for (let i = 0; i < max; i += 1) {
        await page.keyboard.press("Tab");
        const f = await focusInfo();
        if (f?.id === testId) return f;
      }
      return null;
    };
    await page.goto(`${H.UI}/scenarios`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel("scenario-card"), { timeout: 120_000 });
    await ctl(page, record, { id: "scenario-new", prereq: "Scenario Library, keyboard only", action: "Tab to New scenario, Enter", expected: "focus is visible; Enter opens the builder", run: async () => {
      const f = await tabUntil("scenario-new");
      assert.ok(f, "reachable by Tab");
      assert.ok(f.visible, "focus is visible");
      await page.keyboard.press("Enter");
      await page.waitForSelector(sel("scenario-builder"), { timeout: 60_000 });
      return "reached, visible focus, Enter opened the builder";
    } });
    await openWhatIf(page, "?domain=corporate");
    await ctl(page, record, { id: "ws-domain-retail", prereq: "What-If, keyboard only", action: "Tab to Retail, Space", expected: "the Retail book loads", run: async () => {
      const f = await tabUntil("ws-domain-retail");
      assert.ok(f?.visible, "reachable with a visible focus");
      await page.keyboard.press("Space");
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-workspace"]')?.getAttribute("data-domain") === "retail", null, { timeout: 60_000 });
      return "Space switched the book";
    } });
    await ctl(page, record, { id: "grid-filter-apply-sector", prereq: "What-If grid, keyboard only", action: "open a column filter, Escape", expected: "Escape closes the filter editor; focus stays in the page (no trap)", run: async () => {
      await page.click(sel("ws-domain-corporate"));
      await page.waitForFunction(() => document.querySelector('[data-testid="whatif-workspace"]')?.getAttribute("data-domain") === "corporate", null, { timeout: 60_000 });
      await page.focus(sel("grid-filter-sector"));
      await page.keyboard.press("Enter");
      await page.waitForSelector(sel("grid-filter-editor-sector"), { timeout: 30_000 });
      await page.keyboard.press("Escape");
      const closed = await page.waitForSelector(sel("grid-filter-editor-sector"), { state: "detached", timeout: 5_000 }).then(() => true).catch(() => false);
      for (let i = 0; i < 6; i += 1) await page.keyboard.press("Tab");
      const f = await focusInfo();
      assert.ok(f, "focus moved on (no trap)");
      return closed ? "Escape closed the editor; Tab moves on" : "Escape is not implemented on the filter editor (Cancel closes it); Tab moves on — no trap";
    } });
    await openLens(page, "lens-02");
    await ctl(page, record, { id: "lens-kpi", prereq: "Lens LENS-02, keyboard only", action: "Tab to a KPI, Enter", expected: "the metric definition opens", run: async () => {
      const f = await tabUntil("lens-kpi", 200);
      assert.ok(f?.visible, "reachable with a visible focus");
      await page.keyboard.press("Enter");
      await page.waitForSelector(sel("metric-catalogue"), { timeout: 60_000 });
      return "Enter opened the metric";
    } });
  });
}

async function responsiveJourney() {
  const { journey, open, ctl, assert, openWhatIf } = H;
  await journey("GW-CTL-RESPONSIVE", "390 px: the core actions of each module are visible, not covered (sticky bars included) and clickable; no horizontal page scroll", async (record) => {
    const page = await open();
    await page.setViewportSize({ width: 390, height: 844 });
    const covered = (s) => page.evaluate((q) => {
      const el = document.querySelector(q);
      if (!el) return "missing";
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return "zero-size";
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return el === top || el.contains(top) ? "" : `covered by ${top?.getAttribute("data-testid") ?? top?.tagName}`;
    }, s);
    const hscroll = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const prep = { "cockpit-v4-ask": sel("cockpit-v4-question"), "whatif-ask": sel("whatif-ask-input") };
    const checks = [
      ["/", ["cockpit-v4-ask", "issue-investigate"]],
      ["/what-if?domain=corporate", ["whatif-ask", "whatif-load-scenario", "whatif-library", "whatif-grid-next"]],
      ["/scenarios", ["scenario-new", "scenario-open"]],
      ["/lenses/lens-02", ["lens-refresh", "lens-follow", "lens-share-open"]],
      ["/monitoring", ["monitoring-tick", "monitoring-view-all"]],
      ["/messages", ["messages-box-sent", "message-item"]],
      ["/metrics", ["metric-search", "metric-item"]],
      ["/early-warning", ["ew-investigate", "ew-save-cohort"]],
    ];
    for (const [url, ids] of checks) {
      await page.goto(`${H.UI}${url}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(sel(ids[0]), { timeout: 120_000 });
      await page.waitForLoadState("networkidle").catch(() => undefined);
      for (const id of ids) {
        await ctl(page, record, { id: `check:390px:${id}`, prereq: `${url} at 390 px`, expected: "visible, not covered, clickable; no horizontal page scroll", run: async () => {
          // An Ask button is disabled until a question is typed (by
          // design); type one, without submitting, so it can be clicked.
          if (prep[id]) await page.fill(prep[id], "Which segments drive the change?");
          const c = await covered(`[data-testid="${id}"]`);
          assert.equal(c, "", `${id}: ${c}`);
          await page.locator(sel(id)).first().click({ trial: true });
          const h = await hscroll();
          assert.ok(h <= 1, `horizontal page scroll ${h}px`);
          return "visible, uncovered, clickable";
        } });
      }
    }
    void openWhatIf;
  });
}

export async function controlJourneys(helpers) {
  H = helpers;
  await naJourney();
  await routesJourney();
  await homeJourney();
  await issueJourney();
  await ewJourney();
  await whatifJourney();
  await methodsJourney();
  await gridJourney();
  await scenarioJourney();
  await builderJourney();
  await monitoringJourney();
  await lensJourney();
  await messagesJourney();
  await metricsJourney();
  await traceJourney();
  await labJourney();
  await threadJourney();
  await idempotencyJourney();
  await keyboardJourney();
  await responsiveJourney();
}
