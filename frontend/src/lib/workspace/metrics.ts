/** Metric Catalogue client (P8): persisted, versioned governed definitions. */

import { wsGet, wsSend } from "./client";
import type { Filter } from "./objects";

export interface MetricDefinition {
  metric_id: string;
  version: number;
  name: string;
  domain: "both" | "corporate" | "retail";
  family: string;
  kind: string;
  definition: string;
  formula: string;
  numerator: string;
  denominator: string;
  num_sql: string;
  den_sql: string;
  evaluator: string;
  relative_to: string;
  unit: string;
  scaling: string;
  aggregation: string;
  grain: string;
  eligible_population: string;
  exclusions: string;
  null_treatment: string;
  period_semantics: string;
  directionality: string;
  thresholds: Record<string, unknown>;
  lineage: string[];
  drilldown_dimensions: string[];
  scenario_interpretation: string;
  example_rendering: string;
  validation_rule: string;
  owner: string;
  status: string;
  catalog_version: string;
  object_id: string;
  object_version: number;
  content_hash: string;
  used_by?: { lenses: { object_id: string; title: string; version: number }[]; breach_rules: { lens_id: string; rule_id: string; title: string }[]; issue_detectors: string[] };
}

export interface MetricValue {
  metric_id: string;
  metric_version: number;
  unit: string;
  period: string;
  prior_period?: string;
  release_id: string;
  value?: number | null;
  numerator?: number | null;
  denominator?: number | null;
  rows?: number;
  groups?: { dimension: string; value: number | null; numerator?: number | null; denominator?: number | null; rows?: number; object_id?: string }[];
  series?: { period: string; value: number | null }[];
  status?: string;
  note?: string;
  latest_result?: string | null;
}

export interface MetricLineage {
  metric_id: string;
  object_id: string;
  version: number;
  content_hash: string;
  sources: { ref: string; relation: string; field: string }[];
  num_sql: string;
  den_sql: string;
  evaluator: string;
  relative_to: string;
  drilldown_dimensions: string[];
  used_by: NonNullable<MetricDefinition["used_by"]>;
  versions: { version: number; content_hash: string; reason: string; created_at: number }[];
}

export const listMetrics = (domain = "") =>
  wsGet<{ catalog_version: string; count: number; metrics: MetricDefinition[]; definition_fields: string[] }>(`/metrics${domain ? `?domain=${domain}` : ""}`);

export const readMetric = (id: string) => wsGet<MetricDefinition>(`/metrics/${encodeURIComponent(id)}`);

export const readMetricLineage = (id: string) => wsGet<MetricLineage>(`/metrics/${encodeURIComponent(id)}/lineage`);

export const evaluateMetric = (domain: string, metricId: string, opts: { group_by?: string; series_periods?: number; filters?: Filter[]; period?: string } = {}) =>
  wsSend<MetricValue>("/metrics/evaluate", { domain, metric_id: metricId, ...opts });

export const metricRows = (metricId: string, domain: string, filters: Filter[] = [], limit = 100) =>
  wsGet<{ rows: Record<string, unknown>[]; total: number; columns?: unknown[] }>(
    `/metrics/${encodeURIComponent(metricId)}/rows?domain=${domain}&limit=${limit}&filters=${encodeURIComponent(JSON.stringify(filters))}`,
  );
