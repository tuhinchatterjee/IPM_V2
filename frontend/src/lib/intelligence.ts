/**
 * Document Intelligence, as logic rather than markup.
 *
 * Everything here is React-free and pure, so the judgements the dashboard
 * makes — which tabs a document gets, what counts as red, how a change is
 * worded, when a number should not be shown at all — are unit-testable
 * without rendering anything. The components below it decide layout and
 * nothing else.
 *
 * The rule that runs through the whole file: **never invent a status**. A
 * value the backend did not compute is absent, and absent is rendered as
 * "not known" rather than as zero. A page count of 0 and an unknown page
 * count are different facts, and a committee paper is exactly the place where
 * confusing them matters.
 */

import type {
  PbAction,
  PbComparison,
  PbDashboard,
  PbFinding,
  PbGovernedDecision,
  PbHistoryEntry,
  PbMetric,
  PbReadinessComponent,
  PbSectionRow,
  PbSourceReading,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

export interface TabSpec {
  id: string;
  label: string;
}

/** §11's committee set. */
const COMMITTEE_TABS: TabSpec[] = [
  { id: "pack", label: "Pack" },
  { id: "findings", label: "Findings" },
  { id: "decisions", label: "Decisions & actions" },
  { id: "since", label: "Since last time" },
  { id: "sections", label: "Documents / sections" },
  { id: "history", label: "History" },
];

/** §11's non-committee set. The same components, a different agenda. */
const DOCUMENT_TABS: TabSpec[] = [
  { id: "pack", label: "Overview" },
  { id: "findings", label: "Findings" },
  { id: "sections", label: "Sections" },
  { id: "since", label: "Metrics / since last time" },
  { id: "sources", label: "Sources" },
  { id: "history", label: "History" },
];

export function tabsFor(committee: boolean): TabSpec[] {
  return committee ? COMMITTEE_TABS : DOCUMENT_TABS;
}

/**
 * Where a status card or a blocker sends the reader.
 *
 * A committee document has no Sources tab of its own — sources live under
 * Documents / sections — so a "sources" link has to land somewhere that
 * exists. Silently dropping it would leave a card that looks clickable and
 * does nothing.
 */
export function resolveTab(link: string, committee: boolean): string {
  const tabs = tabsFor(committee).map((t) => t.id);
  if (tabs.includes(link)) return link;
  const fallback: Record<string, string> = {
    sources: committee ? "sections" : "sources",
    metrics: "since",
    overview: "pack",
    readiness: "pack",
    reviews: "sections",
    decisions: committee ? "decisions" : "pack",
  };
  const mapped = fallback[link];
  return mapped && tabs.includes(mapped) ? mapped : tabs[0];
}

// ---------------------------------------------------------------------------
// RAG
// ---------------------------------------------------------------------------

export type Rag = "green" | "amber" | "red" | "unknown";

/** The same bars the backend scores against: 90 green, 60 amber. */
export const GREEN_AT = 90;
export const AMBER_AT = 60;

export function rag(score: number | null | undefined): Rag {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return "unknown";
  }
  if (score >= GREEN_AT) return "green";
  return score >= AMBER_AT ? "amber" : "red";
}

/**
 * The word beside the colour. §10 and §32 both forbid colour alone, and an
 * icon is not enough either for a reader using a screen reader or a
 * black-and-white printout of a committee pack.
 */
export function ragLabel(value: Rag): string {
  return { green: "On track", amber: "Attention", red: "At risk",
    unknown: "Not scored" }[value];
}

// ---------------------------------------------------------------------------
// Approval
// ---------------------------------------------------------------------------

export interface ApprovalBadge {
  label: string;
  tone: Rag;
  detail: string;
}

export function approvalBadge(dashboard: {
  readiness: { approval_status: string; blockers: { reason: string }[] };
}): ApprovalBadge {
  const blockers = dashboard.readiness.blockers ?? [];
  const count = blockers.length;
  const plural = count === 1 ? "" : "s";
  switch (dashboard.readiness.approval_status) {
    case "approved":
      return { label: "Approved", tone: "green", detail: "" };
    case "ready":
      return { label: "Ready for approval", tone: "green",
        detail: "nothing is blocking" };
    case "blocked":
      return {
        label: "Not ready for approval",
        tone: "red",
        detail: count
          ? `${count} blocking item${plural}`
          : "blocked",
      };
    default:
      return {
        label: "In progress",
        tone: "amber",
        detail: count ? `${count} blocking item${plural}` : "",
      };
  }
}

// ---------------------------------------------------------------------------
// Status cards, §8
// ---------------------------------------------------------------------------

export interface StatusCard {
  id: string;
  label: string;
  /** The headline. "—" where the value is genuinely not known. */
  value: string;
  detail: string;
  tone: Rag;
  /** Which tab this card opens, already resolved for this document. */
  tab: string;
}

export function statusCards(dashboard: PbDashboard): StatusCard[] {
  const committee = dashboard.committee_report;
  const to = (link: string) => resolveTab(link, committee);
  const stats = dashboard.statistics;
  const readiness = dashboard.readiness;

  const cards: StatusCard[] = [
    {
      id: "completion",
      label: "Completion",
      value: `${readiness.completion_pct}%`,
      detail: readiness.missing.length
        ? `${readiness.missing.length} section${
            readiness.missing.length === 1 ? "" : "s"
          } missing`
        : "every required section present",
      tone: rag(readiness.completion_pct),
      tab: to("pack"),
    },
    {
      id: "readiness",
      label: "Readiness",
      value: `${readiness.readiness_pct}%`,
      detail: readiness.blockers.length
        ? `${readiness.blockers.length} blocker${
            readiness.blockers.length === 1 ? "" : "s"
          }`
        : "nothing blocking",
      tone: rag(readiness.readiness_pct),
      tab: to("pack"),
    },
    {
      id: "pages",
      label: "Pages",
      // Never a guess. An unknown page count and a nought-page document are
      // different facts.
      value: stats.pages === null ? "—" : String(stats.pages),
      detail:
        stats.pages === null
          ? "no rendered file has been read back"
          : stats.page_count_source
            ? `from the ${stats.page_count_source.toUpperCase()}`
            : "",
      tone: "unknown",
      tab: to("sections"),
    },
    {
      id: "sections",
      label: "Sections",
      value: `${stats.substantive_sections} / ${stats.sections}`,
      detail: "substantive of total",
      tone: "unknown",
      tab: to("sections"),
    },
    {
      id: "metrics",
      label: "Metrics",
      value: String(dashboard.metrics.detected),
      detail: dashboard.metrics.suggested
        ? `${dashboard.metrics.suggested} awaiting confirmation`
        : `${dashboard.metrics.confirmed} governed`,
      tone: dashboard.metrics.suggested ? "amber" : "unknown",
      tab: to("since"),
    },
    {
      id: "findings",
      label: "Findings",
      value: `${dashboard.findings.open} open`,
      detail: dashboard.findings.blocking
        ? `${dashboard.findings.blocking} blocking`
        : "none blocking",
      tone: dashboard.findings.blocking
        ? "red"
        : dashboard.findings.open
          ? "amber"
          : "green",
      tab: to("findings"),
    },
  ];

  if (committee) {
    cards.push({
      id: "decisions",
      label: "Decisions",
      value: `${dashboard.decisions.outstanding} outstanding`,
      detail: `${dashboard.decisions.decided} recorded`,
      tone: dashboard.decisions.outstanding ? "amber" : "green",
      tab: to("decisions"),
    });
  }

  cards.push(
    {
      id: "actions",
      label: "Actions",
      value: `${dashboard.actions.open} open`,
      detail: dashboard.actions.overdue
        ? `${dashboard.actions.overdue} overdue`
        : "none overdue",
      tone: dashboard.actions.overdue
        ? "red"
        : dashboard.actions.open
          ? "amber"
          : "green",
      tab: to("decisions"),
    },
    {
      id: "review",
      label: "Review",
      value: `${dashboard.reviews.complete} / ${dashboard.reviews.total}`,
      detail: dashboard.reviews.total ? "complete" : "no reviewer assigned",
      tone: dashboard.reviews.total
        ? dashboard.reviews.outstanding
          ? "amber"
          : "green"
        : "unknown",
      tab: to("sections"),
    },
  );

  return cards;
}

// ---------------------------------------------------------------------------
// The compact panel on the thread, §5
// ---------------------------------------------------------------------------

export interface CompactRow {
  label: string;
  value: string;
  tone: Rag;
}

/**
 * Enough to orient somebody without leaving the chat.
 *
 * Deliberately short. A panel beside a conversation that tries to be the
 * dashboard is a panel that pushes the conversation off the screen.
 */
export function compactRows(dashboard: PbDashboard): CompactRow[] {
  const stats = dashboard.statistics;
  const rows: CompactRow[] = [
    { label: "Completion", value: `${dashboard.readiness.completion_pct}%`,
      tone: rag(dashboard.readiness.completion_pct) },
    { label: "Readiness", value: `${dashboard.readiness.readiness_pct}%`,
      tone: rag(dashboard.readiness.readiness_pct) },
    { label: "Pages", value: stats.pages === null ? "—" : String(stats.pages),
      tone: "unknown" },
    { label: "Sections",
      value: `${stats.substantive_sections} / ${stats.sections}`,
      tone: "unknown" },
    { label: "Metrics", value: String(dashboard.metrics.detected),
      tone: "unknown" },
  ];
  if (dashboard.metrics.suggested) {
    rows.push({ label: "Awaiting confirmation",
      value: String(dashboard.metrics.suggested), tone: "amber" });
  }
  const newer = dashboard.since_last_time.rows?.filter(
    (r) => r.comparable && r.direction && r.direction !== "unchanged",
  ).length ?? 0;
  if (newer) {
    rows.push({ label: "Metrics that moved", value: String(newer),
      tone: "amber" });
  }
  rows.push(
    { label: "Open findings", value: String(dashboard.findings.open),
      tone: dashboard.findings.open ? "amber" : "green" },
  );
  if (dashboard.findings.blocking) {
    rows.push({ label: "Blocking findings",
      value: String(dashboard.findings.blocking), tone: "red" });
  }
  if (dashboard.actions.overdue) {
    rows.push({ label: "Overdue actions",
      value: String(dashboard.actions.overdue), tone: "red" });
  }
  rows.push({ label: "Current version", value: String(dashboard.version),
    tone: "unknown" });
  return rows;
}

/**
 * Whether the thread should offer the status panel at all.
 *
 * §5: do not show meaningless zero-state statistics on an empty Playbook. A
 * workspace with no document, no metric and no finding has nothing to say
 * about itself, and a panel of noughts is worse than no panel.
 */
export function hasStatus(dashboard: PbDashboard | null): boolean {
  return Boolean(dashboard?.available);
}

// ---------------------------------------------------------------------------
// Vocabulary
// ---------------------------------------------------------------------------

const SECTION_STATUS: Record<string, { label: string; tone: Rag }> = {
  draft: { label: "Draft", tone: "unknown" },
  generated: { label: "Generated", tone: "amber" },
  evidence_incomplete: { label: "Evidence incomplete", tone: "red" },
  needs_review: { label: "Needs review", tone: "amber" },
  ready_for_review: { label: "Ready for review", tone: "amber" },
  approved: { label: "Approved", tone: "green" },
  stale: { label: "Stale", tone: "red" },
};

export function sectionStatus(status: string): { label: string; tone: Rag } {
  return SECTION_STATUS[status] ?? { label: humanise(status),
    tone: "unknown" };
}

const SEVERITY: Record<string, { label: string; tone: Rag; rank: number }> = {
  high: { label: "High", tone: "red", rank: 0 },
  medium: { label: "Medium", tone: "amber", rank: 1 },
  low: { label: "Low", tone: "amber", rank: 2 },
  information: { label: "Information", tone: "unknown", rank: 3 },
};

export function severity(value: string) {
  return SEVERITY[value] ?? { label: humanise(value), tone: "unknown" as Rag,
    rank: 4 };
}

const FINDING_STATUS: Record<string, { label: string; tone: Rag }> = {
  open: { label: "Open", tone: "red" },
  answered: { label: "Answered", tone: "amber" },
  accepted: { label: "Accepted", tone: "green" },
  closed: { label: "Closed", tone: "green" },
  deferred: { label: "Deferred", tone: "amber" },
};

export function findingStatus(status: string) {
  return FINDING_STATUS[status] ?? { label: humanise(status),
    tone: "unknown" as Rag };
}

const DECISION_STATUS: Record<string, { label: string; tone: Rag }> = {
  proposed: { label: "Proposed", tone: "unknown" },
  ready_for_decision: { label: "Ready for decision", tone: "amber" },
  decided: { label: "Decided", tone: "green" },
  deferred: { label: "Deferred", tone: "amber" },
  withdrawn: { label: "Withdrawn", tone: "unknown" },
};

export function decisionStatus(status: string) {
  return DECISION_STATUS[status] ?? { label: humanise(status),
    tone: "unknown" as Rag };
}

const ACTION_STATUS: Record<string, { label: string; tone: Rag }> = {
  open: { label: "Open", tone: "amber" },
  in_progress: { label: "In progress", tone: "amber" },
  blocked: { label: "Blocked", tone: "red" },
  completed: { label: "Completed", tone: "green" },
  cancelled: { label: "Cancelled", tone: "unknown" },
};

export function actionStatus(status: string) {
  return ACTION_STATUS[status] ?? { label: humanise(status),
    tone: "unknown" as Rag };
}

const FRESHNESS: Record<string, { label: string; tone: Rag }> = {
  current: { label: "Current", tone: "green" },
  new_data_available: { label: "New data available", tone: "amber" },
  stale: { label: "Stale", tone: "red" },
  unknown: { label: "Unknown", tone: "unknown" },
};

export function freshness(value: string) {
  return FRESHNESS[value] ?? { label: humanise(value),
    tone: "unknown" as Rag };
}

export function humanise(value: string): string {
  const text = (value ?? "").replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

// ---------------------------------------------------------------------------
// Since last time, §15
// ---------------------------------------------------------------------------

export interface MovementView {
  /** "+0.61pp", never "+0.61%" for a difference between two percentages. */
  change: string;
  direction: "improved" | "worse" | "unchanged" | "";
  label: string;
  tone: Rag;
}

/**
 * How a movement reads.
 *
 * The unit is the backend's, untouched: a difference between two percentages
 * is percentage POINTS, and restating it here as a percentage is the slip
 * that survives review and reaches a committee.
 */
export function movement(row: PbComparison): MovementView {
  if (!row.comparable) {
    return { change: "", direction: "", label: "Not comparable",
      tone: "unknown" };
  }
  const unit = row.change_unit && row.change_unit !== "currency"
    ? row.change_unit
    : "";
  const change = row.change ? `${row.change}${unit ? "" : ""}` : "";
  switch (row.direction) {
    case "improved":
      return { change, direction: "improved", label: "Improved",
        tone: "green" };
    case "worse":
      return { change, direction: "worse", label: "Worse", tone: "red" };
    case "unchanged":
      return { change: change || "no change", direction: "unchanged",
        label: "Unchanged", tone: "unknown" };
    default:
      return { change, direction: "", label: "", tone: "unknown" };
  }
}

/**
 * Worse first, then not-comparable, then improved, then unchanged.
 *
 * A reader opening this tab is looking for what got worse. Not-comparable
 * sits second because it is a fact somebody has to act on — a comparison that
 * could not be made is not the same as one that came out flat.
 */
export function orderMovements(rows: PbComparison[]): PbComparison[] {
  const rank = (row: PbComparison) => {
    if (!row.comparable) return 1;
    if (row.direction === "worse") return 0;
    if (row.direction === "improved") return 2;
    return 3;
  };
  return [...rows].sort(
    (a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label),
  );
}

/** The mismatching dimension, in the words §15 asks for. */
export function notComparableReason(row: PbComparison): string {
  return row.reason || "these two readings are not the same series";
}

// ---------------------------------------------------------------------------
// Ordering elsewhere
// ---------------------------------------------------------------------------

/** Blocking first, then by severity, then unresolved before resolved. */
export function orderFindings(items: PbFinding[]): PbFinding[] {
  return [...items].sort(
    (a, b) =>
      Number(b.blocking) - Number(a.blocking) ||
      severity(a.severity).rank - severity(b.severity).rank ||
      Number(b.unresolved) - Number(a.unresolved) ||
      a.reference.localeCompare(b.reference),
  );
}

/** What the committee still has to do, before what it has already done. */
export function orderDecisions(items: PbGovernedDecision[]) {
  const rank: Record<string, number> = {
    ready_for_decision: 0, proposed: 1, deferred: 2, decided: 3, withdrawn: 4,
  };
  return [...items].sort(
    (a, b) =>
      (rank[a.status] ?? 5) - (rank[b.status] ?? 5) ||
      a.reference.localeCompare(b.reference),
  );
}

/** Overdue first — that is the only reason this list is read in a hurry. */
export function orderActions(items: PbAction[], today = new Date()) {
  const stamp = today.toISOString().slice(0, 10);
  const overdue = (a: PbAction) =>
    Boolean(a.due_date) && a.due_date < stamp &&
    !["completed", "cancelled"].includes(a.status);
  return [...items].sort(
    (a, b) =>
      Number(overdue(b)) - Number(overdue(a)) ||
      (a.due_date || "9999").localeCompare(b.due_date || "9999") ||
      a.reference.localeCompare(b.reference),
  );
}

export function isOverdue(action: PbAction, today = new Date()): boolean {
  if (!action.due_date) return false;
  if (["completed", "cancelled"].includes(action.status)) return false;
  return action.due_date < today.toISOString().slice(0, 10);
}

export function orderSections(rows: PbSectionRow[]): PbSectionRow[] {
  return [...rows].sort((a, b) => a.ordinal - b.ordinal);
}

/** Stale sources first: they are the ones with something to do. */
export function orderSources(items: PbSourceReading[]): PbSourceReading[] {
  return [...items].sort(
    (a, b) =>
      Number(b.stale) - Number(a.stale) ||
      a.filename.localeCompare(b.filename),
  );
}

/** Suggestions first, then governed, then unlinked. §16's review queue. */
export function orderMetrics(items: PbMetric[]): PbMetric[] {
  const rank = (m: PbMetric) => {
    if (m.method === "suggested" && !m.confirmed) return 0;
    if (m.governed) return 1;
    return 2;
  };
  return [...items].sort(
    (a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label),
  );
}

// ---------------------------------------------------------------------------
// Readiness components, §10
// ---------------------------------------------------------------------------

export interface ComponentView {
  name: string;
  score: number | null;
  display: string;
  tone: Rag;
  explanation: string;
  blocking: string;
  applicable: boolean;
  tab: string;
}

export function componentViews(
  components: PbReadinessComponent[],
  committee: boolean,
): ComponentView[] {
  return components.map((c) => ({
    name: c.name,
    score: c.score,
    // A component that does not apply says so rather than showing 0%, which
    // would read as "scored, and scored nothing".
    display: c.score === null ? (c.applicable ? "—" : "n/a") : `${c.score}%`,
    tone: c.applicable ? rag(c.score) : "unknown",
    explanation: c.explanation,
    blocking: c.blocking,
    applicable: c.applicable,
    tab: resolveTab(c.link, committee),
  }));
}

// ---------------------------------------------------------------------------
// Statistics, §18
// ---------------------------------------------------------------------------

export interface StatRow {
  label: string;
  value: string;
  note?: string;
}

/**
 * Only what is actually known.
 *
 * §18 asks for charts among the statistics. The canonical document model has
 * no chart block, so there is no honest number to show and the row is omitted
 * rather than printed as nought — a document with eight charts would then be
 * described as having none.
 */
export function statistics(dashboard: PbDashboard): StatRow[] {
  const s = dashboard.statistics;
  const rows: StatRow[] = [
    {
      label: "Pages",
      value: s.pages === null ? "Not known" : String(s.pages),
      note: s.pages === null
        ? "no rendered file has been read back yet"
        : `counted from the rendered ${s.page_count_source.toUpperCase()}`,
    },
    { label: "Words", value: s.words.toLocaleString() },
    { label: "Sections", value: String(s.sections) },
    { label: "Substantive sections", value: String(s.substantive_sections) },
    { label: "Tables", value: String(s.tables) },
    { label: "Metrics tracked", value: String(dashboard.metrics.detected) },
    { label: "Confirmed metrics", value: String(dashboard.metrics.confirmed) },
    { label: "Suggested metrics", value: String(dashboard.metrics.suggested) },
    { label: "Unlinked metrics", value: String(dashboard.metrics.unlinked) },
    { label: "Sources", value: String(dashboard.sources.sources) },
    {
      label: "Evidence items",
      value: String(
        dashboard.sources.items.reduce((n, i) => n + (i.chunk_count ?? 0), 0),
      ),
    },
    { label: "Findings", value: String(dashboard.findings.total) },
    { label: "Blocking findings", value: String(dashboard.findings.blocking) },
    { label: "Decisions", value: String(dashboard.decisions.total) },
    { label: "Open actions", value: String(dashboard.actions.open) },
    { label: "Versions", value: String(dashboard.versions) },
    { label: "Formats", value: s.formats.length
      ? s.formats.map((f) => f.toUpperCase()).join(", ")
      : "none rendered" },
  ];
  return rows;
}

// ---------------------------------------------------------------------------
// History entries
// ---------------------------------------------------------------------------

/**
 * How one entry in a row's trail reads.
 *
 * Two shapes share `PbHistoryEntry` and assuming the wrong one took the whole
 * application down once. A governed object — finding, decision, action —
 * records `act` and `field`. A SECTION records only the move: `from`, `to`,
 * who and why. The section pane read `entry.act.replace(...)`, which is
 * `undefined.replace` on every section entry; it threw, React unmounted the
 * tree, and the dashboard went blank with only the navigation left.
 *
 * So: describe the move where there is one, fall back to the act name where
 * there is one, and assume neither.
 */
export function describeHistoryEntry(entry: PbHistoryEntry): string {
  if (entry.from && entry.to) {
    return `${sectionStatus(entry.from).label} → ${
      sectionStatus(entry.to).label}`;
  }
  if (entry.act) return entry.act.replace(/_/g, " ");
  return "changed";
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

export function shortDate(value: string): string {
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value.slice(0, 10);
  return at.toLocaleDateString("en-GB", { day: "numeric", month: "short",
    year: "numeric" });
}

export function shortDateTime(value: string): string {
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  return `${at.toLocaleDateString("en-GB", { day: "numeric",
    month: "short" })} · ${at.toLocaleTimeString("en-GB", { hour: "2-digit",
    minute: "2-digit" })}`;
}

/**
 * How an actor reads on screen.
 *
 * A governance row records an identity, not a display name. Showing the raw
 * identity is honest; inventing a full name from it would not be.
 */
export function actorLabel(actor: string): string {
  if (!actor) return "";
  const [scope, rest] = actor.split(":");
  if (!rest) return actor;
  if (scope === "user") return `User ${rest}`;
  return rest.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
