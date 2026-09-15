import assert from "node:assert/strict";
import { test } from "node:test";

import type {
  PbAction,
  PbComparison,
  PbDashboard,
  PbFinding,
  PbGovernedDecision,
  PbMetric,
  PbReadinessComponent,
} from "../api.ts";
import {
  actionStatus,
  actorLabel,
  approvalBadge,
  compactRows,
  componentViews,
  decisionStatus,
  findingStatus,
  freshness,
  hasStatus,
  isOverdue,
  movement,
  orderActions,
  orderDecisions,
  orderFindings,
  orderMetrics,
  orderMovements,
  orderSources,
  rag,
  ragLabel,
  resolveTab,
  sectionStatus,
  severity,
  statistics,
  statusCards,
  tabsFor,
} from "../intelligence.ts";

// --------------------------------------------------------------------------
// Fixtures
// --------------------------------------------------------------------------

function dashboard(over: Partial<PbDashboard> = {}): PbDashboard {
  return {
    workspace_id: 1,
    artifact_id: 2,
    title: "IFRS 9 Committee Report",
    document_type: "ifrs9_report",
    document_type_label: "IFRS 9 report",
    report_family: "",
    committee_report: true,
    committee_name: "Credit Risk Committee",
    reporting_period: "Q2 2026",
    meeting_date: "2026-09-25",
    owner: "Head of Credit Risk",
    status: "",
    classified_by: "user",
    classification_confidence: "high",
    should_ask_type: false,
    version: 2,
    versions: 2,
    statistics: {
      sections: 7, words: 2400, tables: 1, pages: 12,
      page_count_source: "pdf", formats: ["docx", "pdf"],
      sections_with_sources: 3, substantive_sections: 6,
    },
    metrics: {
      detected: 5, confirmed: 4, suggested: 1, unlinked: 0,
      coverage_pct: 80, review_prompt: "Review 1 suggested metric link",
      inventory: [], suggested_review: [],
    },
    sections: [],
    findings: { total: 4, open: 3, blocking: 1,
      by_severity: { high: 1, medium: 1, low: 1, information: 0 }, items: [] },
    decisions: { total: 2, outstanding: 1, decided: 1, items: [] },
    actions: { total: 2, open: 2, completed: 0, overdue: 1, items: [] },
    reviews: { total: 3, complete: 2, outstanding: 1, items: [] },
    readiness: {
      computed: true, completion_pct: 34, readiness_pct: 54,
      approval_status: "blocked", components: [], completion_components: [],
      blockers: [{ reason: "1 blocking finding", link: "findings" }],
      missing: ["Methodology"],
      statistics: {
        sections: 7, words: 2400, tables: 1, pages: 12,
        page_count_source: "pdf", formats: ["docx", "pdf"],
        sections_with_sources: 3, substantive_sections: 6,
      },
      computed_at: "2026-09-14T18:39:42Z",
    },
    since_last_time: { available: true, rows: [], compared: 4,
      not_comparable: 0, worse: 2, improved: 2 },
    sources: { sources: 3, current: 2, needs_reread: 1,
      message: "1 source needs re-read", items: [] },
    available: true,
    ...over,
  };
}

function comparison(over: Partial<PbComparison> = {}): PbComparison {
  return {
    metric_id: "ifrs9.coverage_ratio",
    label: "Coverage ratio",
    then: { value: "2.09", display: "2.09%", period: "Q1 2026", locator: "",
      version: 1 },
    now: { value: "2.17", display: "2.17%", period: "Q2 2026", locator: "" },
    unit: "percent", currency: "", population: "", segment: "", scenario: "",
    change: "+0.08pp", change_unit: "pp", direction: "worse",
    comparable: true, reason: "", section_key: "s-1",
    lineage: { then: {}, now: {} },
    ...over,
  };
}

function finding(over: Partial<PbFinding> = {}): PbFinding {
  return {
    id: 1, reference: "F-01", title: "Coverage fell", severity: "medium",
    status: "open", rationale: "", metric_id: "", threshold: "",
    previous_value: "", current_value: "", owner: "", answer: "",
    answered_by: "", answered_at: "", resolution: "", resolved_by: "",
    resolved_at: "", origin: "rule", origin_label: "Threshold rule",
    delta: "", blocking: false, unresolved: true, history: [],
    section_key: "",
    ...over,
  };
}

function action(over: Partial<PbAction> = {}): PbAction {
  return {
    id: 1, reference: "A-01", title: "Do the thing", owner: "",
    due_date: "", status: "open", last_update: "", decision_id: null,
    finding_id: null, description: "", completed_by: "", completed_at: "",
    notes: [], history: [], external_system: "", external_ref: "",
    external_status: "",
    ...over,
  };
}

function decision(over: Partial<PbGovernedDecision> = {}): PbGovernedDecision {
  return {
    id: 1, reference: "D-01", question: "Hold?", recommendation: "",
    options: [], current_position: "", proposed_position: "",
    effective_date: "", status: "proposed", outcome: "", decided_by: "",
    decided_at: "", meeting: "", reporting_period: "", rationale: "",
    related_finding_ids: [], history: [],
    ...over,
  };
}

function metric(over: Partial<PbMetric> = {}): PbMetric {
  return {
    id: 1, metric_id: "m.1", label: "Metric", document_label: "",
    value_in_document: "", display_value: "", raw_value: "", unit: "",
    reporting_period: "", population: "", segment: "", source_locator: "",
    source_module: "", section_key: "", method: "from_export",
    method_label: "", confidence: "", confirmed: false, confirmed_by: "",
    governed: true, freshness: "current",
    ...over,
  };
}

// --------------------------------------------------------------------------
// Tabs
// --------------------------------------------------------------------------

test("a committee document gets the committee agenda", () => {
  assert.deepEqual(
    tabsFor(true).map((t) => t.id),
    ["pack", "findings", "decisions", "since", "sections", "history"],
  );
});

test("a non-committee document gets no decisions tab", () => {
  const ids = tabsFor(false).map((t) => t.id);
  assert.ok(!ids.includes("decisions"));
  assert.ok(ids.includes("sources"));
});

test("a link to a tab this document does not have lands somewhere real", () => {
  // A committee document has no Sources tab; sources live under sections.
  assert.equal(resolveTab("sources", true), "sections");
  assert.equal(resolveTab("sources", false), "sources");
});

test("an unknown link falls back to the first tab rather than nowhere", () => {
  assert.equal(resolveTab("somewhere-else", true), "pack");
});

test("a metrics link reaches since-last-time in both agendas", () => {
  assert.equal(resolveTab("metrics", true), "since");
  assert.equal(resolveTab("metrics", false), "since");
});

// --------------------------------------------------------------------------
// RAG
// --------------------------------------------------------------------------

test("the bars are the ones the backend scores against", () => {
  assert.equal(rag(90), "green");
  assert.equal(rag(89), "amber");
  assert.equal(rag(60), "amber");
  assert.equal(rag(59), "red");
});

test("an absent score is not scored, never red", () => {
  assert.equal(rag(null), "unknown");
  assert.equal(rag(undefined), "unknown");
  assert.equal(ragLabel("unknown"), "Not scored");
});

test("every tone carries a word, because colour alone is not a status", () => {
  for (const tone of ["green", "amber", "red", "unknown"] as const) {
    assert.ok(ragLabel(tone).length > 0);
  }
});

// --------------------------------------------------------------------------
// Approval
// --------------------------------------------------------------------------

test("a blocked document names how many items block it", () => {
  const badge = approvalBadge(dashboard());
  assert.equal(badge.label, "Not ready for approval");
  assert.equal(badge.tone, "red");
  assert.equal(badge.detail, "1 blocking item");
});

test("pending is not failure and does not read as red", () => {
  const badge = approvalBadge(
    dashboard({
      readiness: { ...dashboard().readiness, approval_status: "pending",
        blockers: [] },
    }),
  );
  assert.equal(badge.label, "In progress");
  assert.equal(badge.tone, "amber");
});

test("ready says nothing is blocking", () => {
  const badge = approvalBadge(
    dashboard({
      readiness: { ...dashboard().readiness, approval_status: "ready",
        blockers: [] },
    }),
  );
  assert.equal(badge.tone, "green");
});

// --------------------------------------------------------------------------
// Status cards
// --------------------------------------------------------------------------

test("completion and readiness are separate cards and separate numbers", () => {
  const cards = statusCards(dashboard());
  const completion = cards.find((c) => c.id === "completion");
  const readiness = cards.find((c) => c.id === "readiness");
  assert.equal(completion?.value, "34%");
  assert.equal(readiness?.value, "54%");
});

test("an unknown page count shows a dash and says why, never a nought", () => {
  const cards = statusCards(
    dashboard({
      statistics: { ...dashboard().statistics, pages: null,
        page_count_source: "" },
    }),
  );
  const pages = cards.find((c) => c.id === "pages");
  assert.equal(pages?.value, "—");
  assert.match(pages?.detail ?? "", /no rendered file/);
});

test("a blocking finding turns the findings card red", () => {
  const card = statusCards(dashboard()).find((c) => c.id === "findings");
  assert.equal(card?.tone, "red");
  assert.equal(card?.detail, "1 blocking");
});

test("no findings at all is green rather than unscored", () => {
  const card = statusCards(
    dashboard({
      findings: { total: 0, open: 0, blocking: 0, by_severity: {},
        items: [] },
    }),
  ).find((c) => c.id === "findings");
  assert.equal(card?.tone, "green");
});

test("a non-committee document is offered no decisions card", () => {
  const cards = statusCards(dashboard({ committee_report: false }));
  assert.ok(!cards.some((c) => c.id === "decisions"));
});

test("every card points at a tab this document actually has", () => {
  for (const committee of [true, false]) {
    const data = dashboard({ committee_report: committee });
    const ids = tabsFor(committee).map((t) => t.id);
    for (const card of statusCards(data)) {
      assert.ok(ids.includes(card.tab), `${card.id} → ${card.tab}`);
    }
  }
});

test("suggested metrics make the metrics card ask for attention", () => {
  const card = statusCards(dashboard()).find((c) => c.id === "metrics");
  assert.equal(card?.tone, "amber");
  assert.match(card?.detail ?? "", /awaiting confirmation/);
});

// --------------------------------------------------------------------------
// The compact panel
// --------------------------------------------------------------------------

test("an empty workspace is offered no status panel", () => {
  assert.equal(hasStatus(dashboard({ available: false })), false);
  assert.equal(hasStatus(null), false);
});

test("the compact panel stays short and leads with the two percentages", () => {
  const rows = compactRows(dashboard());
  assert.equal(rows[0].label, "Completion");
  assert.equal(rows[1].label, "Readiness");
  assert.ok(rows.length <= 11);
});

test("blocking findings and overdue actions appear only when they exist", () => {
  const quiet = compactRows(
    dashboard({
      findings: { total: 0, open: 0, blocking: 0, by_severity: {},
        items: [] },
      actions: { total: 0, open: 0, completed: 0, overdue: 0, items: [] },
      metrics: { ...dashboard().metrics, suggested: 0 },
    }),
  );
  assert.ok(!quiet.some((r) => r.label === "Blocking findings"));
  assert.ok(!quiet.some((r) => r.label === "Overdue actions"));

  const busy = compactRows(dashboard());
  assert.ok(busy.some((r) => r.label === "Blocking findings"));
  assert.ok(busy.some((r) => r.label === "Overdue actions"));
});

test("metrics that moved are counted from comparable rows only", () => {
  const rows = compactRows(
    dashboard({
      since_last_time: {
        available: true, compared: 2, not_comparable: 1, worse: 1,
        improved: 0,
        rows: [
          comparison({ direction: "worse" }),
          comparison({ metric_id: "b", comparable: false, direction: "" }),
          comparison({ metric_id: "c", direction: "unchanged" }),
        ],
      },
    }),
  );
  const moved = rows.find((r) => r.label === "Metrics that moved");
  assert.equal(moved?.value, "1");
});

// --------------------------------------------------------------------------
// Movements
// --------------------------------------------------------------------------

test("a percentage-point move is never restated as a percentage", () => {
  const view = movement(comparison());
  assert.equal(view.change, "+0.08pp");
  assert.ok(!view.change.endsWith("%"));
});

test("not comparable says so and shows no change at all", () => {
  const view = movement(
    comparison({ comparable: false, change: "+0.08pp",
      reason: "population differs" }),
  );
  assert.equal(view.label, "Not comparable");
  assert.equal(view.change, "");
});

test("worse is red and improved is green", () => {
  assert.equal(movement(comparison({ direction: "worse" })).tone, "red");
  assert.equal(movement(comparison({ direction: "improved" })).tone, "green");
});

test("worse sorts first and not-comparable second", () => {
  const ordered = orderMovements([
    comparison({ metric_id: "d", label: "D", direction: "unchanged" }),
    comparison({ metric_id: "c", label: "C", direction: "improved" }),
    comparison({ metric_id: "b", label: "B", comparable: false,
      direction: "" }),
    comparison({ metric_id: "a", label: "A", direction: "worse" }),
  ]);
  assert.deepEqual(ordered.map((r) => r.label), ["A", "B", "C", "D"]);
});

// --------------------------------------------------------------------------
// Ordering
// --------------------------------------------------------------------------

test("blocking findings come first, then by severity", () => {
  const ordered = orderFindings([
    finding({ reference: "F-01", severity: "low" }),
    finding({ reference: "F-02", severity: "high" }),
    finding({ reference: "F-03", severity: "medium", blocking: true }),
  ]);
  assert.deepEqual(ordered.map((f) => f.reference), ["F-03", "F-02", "F-01"]);
});

test("decisions still to take come before ones already taken", () => {
  const ordered = orderDecisions([
    decision({ reference: "D-01", status: "decided" }),
    decision({ reference: "D-02", status: "ready_for_decision" }),
    decision({ reference: "D-03", status: "proposed" }),
  ]);
  assert.deepEqual(ordered.map((d) => d.reference), ["D-02", "D-03", "D-01"]);
});

test("overdue actions come first", () => {
  const today = new Date("2026-09-15T00:00:00Z");
  const ordered = orderActions(
    [
      action({ reference: "A-01", due_date: "2026-12-01" }),
      action({ reference: "A-02", due_date: "2026-09-01" }),
      action({ reference: "A-03", due_date: "" }),
    ],
    today,
  );
  assert.deepEqual(ordered.map((a) => a.reference), ["A-02", "A-01", "A-03"]);
});

test("a completed action is never overdue, whatever its due date", () => {
  const today = new Date("2026-09-15T00:00:00Z");
  assert.equal(
    isOverdue(action({ due_date: "2026-01-01", status: "completed" }), today),
    false,
  );
  assert.equal(isOverdue(action({ due_date: "2026-01-01" }), today), true);
});

test("suggestions sort to the top of the metric inventory", () => {
  const ordered = orderMetrics([
    metric({ id: 1, label: "Governed", governed: true }),
    metric({ id: 2, label: "Unlinked", governed: false, method: "unlinked" }),
    metric({ id: 3, label: "Suggested", governed: false,
      method: "suggested" }),
  ]);
  assert.deepEqual(ordered.map((m) => m.label),
    ["Suggested", "Governed", "Unlinked"]);
});

test("stale sources sort first", () => {
  const ordered = orderSources([
    { source_id: 1, filename: "b.xlsx", format: "xlsx", revision: 1,
      parser_version: "2", schema_version: "2", current_parser_version: "2",
      status: "parsed", chunk_count: 3, stale: false, reason: "",
      reason_label: "", improvements: [], parsed_at: "" },
    { source_id: 2, filename: "a.xlsx", format: "xlsx", revision: 1,
      parser_version: "1", schema_version: "2", current_parser_version: "2",
      status: "parsed", chunk_count: 3, stale: true, reason: "behind",
      reason_label: "Older reader", improvements: [], parsed_at: "" },
  ]);
  assert.deepEqual(ordered.map((s) => s.filename), ["a.xlsx", "b.xlsx"]);
});

// --------------------------------------------------------------------------
// Vocabulary
// --------------------------------------------------------------------------

test("every status vocabulary has a word and a tone", () => {
  assert.equal(sectionStatus("needs_review").label, "Needs review");
  assert.equal(sectionStatus("approved").tone, "green");
  assert.equal(severity("high").tone, "red");
  assert.equal(findingStatus("open").tone, "red");
  assert.equal(decisionStatus("ready_for_decision").label,
    "Ready for decision");
  assert.equal(actionStatus("in_progress").label, "In progress");
  assert.equal(freshness("new_data_available").label, "New data available");
});

test("an unrecognised status is shown rather than swallowed", () => {
  assert.equal(sectionStatus("something_new").label, "Something new");
  assert.equal(sectionStatus("something_new").tone, "unknown");
});

// --------------------------------------------------------------------------
// Readiness components
// --------------------------------------------------------------------------

function component(over: Partial<PbReadinessComponent> = {}) {
  return {
    name: "Required sections", score: 93, status: "green",
    explanation: "13 of 14 written", blocking: "", applicable: true,
    link: "sections",
    ...over,
  } as PbReadinessComponent;
}

test("a component that does not apply reads n/a, never 0%", () => {
  const [view] = componentViews(
    [component({ score: null, applicable: false, name: "Approval" })],
    true,
  );
  assert.equal(view.display, "n/a");
  assert.equal(view.tone, "unknown");
});

test("an applicable component with no score shows a dash", () => {
  const [view] = componentViews(
    [component({ score: null, applicable: true })], true);
  assert.equal(view.display, "—");
});

test("each component links to a tab this document has", () => {
  const views = componentViews(
    [component({ link: "sources" }), component({ link: "findings" })],
    true,
  );
  const ids = tabsFor(true).map((t) => t.id);
  for (const view of views) assert.ok(ids.includes(view.tab));
});

// --------------------------------------------------------------------------
// Statistics
// --------------------------------------------------------------------------

test("an unknown page count is stated as not known, with the reason", () => {
  const rows = statistics(
    dashboard({
      statistics: { ...dashboard().statistics, pages: null,
        page_count_source: "" },
    }),
  );
  const pages = rows.find((r) => r.label === "Pages");
  assert.equal(pages?.value, "Not known");
  assert.match(pages?.note ?? "", /read back/);
});

test("charts are omitted rather than reported as none", () => {
  // The canonical model has no chart block, so there is no honest number.
  // Printing 0 would describe a document with eight charts as having none.
  const labels = statistics(dashboard()).map((r) => r.label);
  assert.ok(!labels.includes("Charts"));
});

test("evidence items are summed from the sources that were read", () => {
  const rows = statistics(
    dashboard({
      sources: {
        sources: 2, current: 2, needs_reread: 0, message: "",
        items: [
          { source_id: 1, filename: "a", format: "xlsx", revision: 1,
            parser_version: "2", schema_version: "2",
            current_parser_version: "2", status: "parsed", chunk_count: 7,
            stale: false, reason: "", reason_label: "", improvements: [],
            parsed_at: "" },
          { source_id: 2, filename: "b", format: "docx", revision: 1,
            parser_version: "1", schema_version: "2",
            current_parser_version: "1", status: "parsed", chunk_count: 5,
            stale: false, reason: "", reason_label: "", improvements: [],
            parsed_at: "" },
        ],
      },
    }),
  );
  assert.equal(rows.find((r) => r.label === "Evidence items")?.value, "12");
});

// --------------------------------------------------------------------------
// Actors
// --------------------------------------------------------------------------

test("an actor is shown as recorded, never as an invented full name", () => {
  assert.equal(actorLabel("user:7"), "User 7");
  assert.equal(actorLabel("demo:head-of-credit-risk"), "Head Of Credit Risk");
  assert.equal(actorLabel(""), "");
});
