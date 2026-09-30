/**
 * Guided Cockpit (P3) and the governed grid, typed as the server sends them.
 */

import { qs, workspaceUrl, wsGet, wsSend } from "@/lib/workspace/client";
import type { DomainId, Filter } from "@/lib/workspace/objects";

export interface Suggestion {
  suggestion_id: string;
  type: string;
  text: string;
  exact_request: string;
  rationale: string;
  source: { issue_id?: string; metric_id?: string; evidence?: string[] };
  required_capability: string;
  predicted_scope: string;
  changes_state: boolean;
  weight: number;
  is_stress_test: boolean;
  suppressed_because?: string;
}

export interface Suggestions {
  primary: Suggestion[];
  more: Suggestion[];
  suppressed: Suggestion[];
}

export interface SeriesPoint {
  period: string;
  value: number | null;
  numerator?: number | null;
  denominator?: number | null;
}

export interface Driver {
  label: string;
  value: number;
  current?: number | null;
  prior?: number | null;
  metric_id: string;
  unit: string;
  display: string;
}

export interface Issue {
  issue_id: string;
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  generated_at: number;
  detection_rule: { id: string; version: string; mode: string };
  title: string;
  severity: "critical" | "high" | "moderate" | "low";
  score: number;
  metric_id: string;
  metric_name: string;
  metric_unit: string;
  segment: { dimension: string; value: string };
  entity_plural: string;
  owner_plural: string;
  materiality: {
    current_value: number | null;
    prior_value: number | null;
    movement_abs: number | null;
    movement_rel: number | null;
    movement_display: string;
    level_display: string;
    book_value: number | null;
    affected_ead: number | null;
    affected_ecl: number | null;
    affected_entities: number;
    affected_owners: number;
    share_of_book_ecl: number;
    stage2_ead: number;
    stage3_ead: number;
  };
  evidence: {
    metric_ids: string[];
    period: string;
    prior_period: string;
    predicate: Filter[];
    series: SeriesPoint[];
    ecl_series: SeriesPoint[];
    breakdown_dimension: string;
    breakdown: Driver[];
    stage_mix: { stage: number; n: number; ead: number; ecl: number }[];
    band_mix: { band: string; n: number; ead: number }[];
  };
  drivers: Driver[];
  interpretation: string;
  fact_vs_inference: { fact: string; inference: string | null; caveat: string };
  cohort: { filters: Filter[]; selection: string; description: string; entities: number; owners: number; ead: number; ecl: number };
  actions: string[];
  next_best_questions: Suggestions;
  context_series?: Record<string, { metric_id: string; name: string; unit: string; points: SeriesPoint[] }>;
}

export interface IssueFeed {
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  prior_period: string;
  ruleset: string;
  generated_at: number;
  issues: Issue[];
  detectors: { rule: string; found: number; error?: string }[];
  counts: { total: number; by_severity: Record<string, number> };
  book: { ead: number; ecl: number; entities: number; owners: number };
  server_ms: number;
  model_calls: number;
}

export const readIssues = (domain: DomainId, refresh = false) =>
  wsGet<IssueFeed>(`/issues${qs({ domain, refresh: refresh || undefined })}`);

export const readIssue = (id: string) => wsGet<Issue>(`/issues/${encodeURIComponent(id)}`);

export const investigateIssue = (id: string) =>
  wsSend<{
    thread_id: string;
    investigation_id: string;
    cohort_id: string;
    suggestions: Suggestions;
  }>(`/issues/${encodeURIComponent(id)}/investigate`, {});

export const saveIssueCohort = (id: string) =>
  wsSend<{ object_id: string; body: { counts: { entities: number } } }>(
    `/issues/${encodeURIComponent(id)}/cohort`,
    {},
  );

export interface InvestigationState {
  investigation_id: string | null;
  thread_id: string;
  title?: string;
  issue_id?: string;
  cohort_id?: string;
  path?: { step: string; status: string; detail: string }[];
  turns_answered?: number;
  suggestions?: Suggestions;
  note?: string;
}

export const readInvestigationByThread = (threadId: string) =>
  wsGet<InvestigationState>(`/investigations/by-thread/${encodeURIComponent(threadId)}`);

export const recordStep = (
  investigationId: string,
  step: { suggestion_id?: string; kind?: string; question?: string },
) => wsSend<InvestigationState>(`/investigations/${encodeURIComponent(investigationId)}/steps`, step);

// ---- the governed grid -----------------------------------------------------

export interface GridColumn {
  key: string;
  label: string;
  type: "string" | "number" | "integer" | "flag";
  unit: string;
  filter: "text" | "category" | "range" | "boolean";
  group: string;
  description: string;
  visible: boolean;
}

export interface GridSchema {
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  prior_period: string;
  periods: string[];
  grain: string;
  grain_plural: string;
  owner_plural: string;
  key: string;
  owner: string;
  columns: GridColumn[];
  ews_ruleset: string;
}

export interface GridSummary {
  entities: number;
  owners: number;
  ead: number;
  ecl: number;
  stage_mix: { stage: number | null; n: number; ead: number; ecl: number }[];
  band_dimension: string;
  band_mix: { band: string | null; n: number; ead: number }[];
  period: string;
}

export interface GridPage {
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  filters: Filter[];
  filter_description: string;
  sort: string;
  desc: boolean;
  offset: number;
  limit: number;
  rows: Record<string, string | number | null>[];
  total: number;
  summary: GridSummary;
  server_ms: number;
}

export const readGridSchema = (domain: DomainId) => wsGet<GridSchema>(`/grid/schema${qs({ domain })}`);

export const queryGrid = (
  input: { domain: DomainId; filters: Filter[]; sort?: string; desc?: boolean; offset?: number; limit?: number },
  signal?: AbortSignal,
) => wsSend<GridPage>("/grid/query", input, "POST", signal);

export const gridValues = (domain: DomainId, column: string, search = "") =>
  wsGet<{ column: string; values: { value: string | number | null; count: number }[] }>(
    `/grid/values${qs({ domain, column, search })}`,
  );

export const gridGroup = (domain: DomainId, dimension: string, filters: Filter[]) =>
  wsSend<{ dimension: string; groups: { value: string | number | null; n: number; ead_sar_mn: number; ecl_sar_mn: number }[] }>(
    "/grid/group",
    { domain, dimension, filters },
  );

/** Two-dimension aggregate for heatmaps and stage flows (server-side,
 * capped; the totals let the chart prove it reconciles to the book). */
export const gridGroup2 = (domain: DomainId, x: string, y: string, filters: Filter[]) =>
  wsSend<{
    x: string;
    y: string;
    period: string;
    truncated: boolean;
    cells: { x: string | number | null; y: string | number | null; n: number; ead_sar_mn: number | null; ecl_sar_mn: number | null }[];
    total: { n: number; ead_sar_mn: number | null; ecl_sar_mn: number | null };
  }>("/grid/group2", { domain, x, y, filters });

export async function downloadGridCsv(domain: DomainId, filters: Filter[]): Promise<void> {
  const response = await fetch(workspaceUrl("/grid/export"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, filters }),
  });
  if (!response.ok) throw new Error(`Export failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `creditprobe_${domain}_grid.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function guidedEnabled(): boolean {
  return process.env.NEXT_PUBLIC_GUIDED_WORKSPACE === "1";
}
