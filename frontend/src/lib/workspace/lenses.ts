/** Lenses 2.0 client (P9): governed Lens objects rendered on the metric engine. */

import { wsGet, wsSend } from "./client";
import type { Filter, GovernedObject } from "./objects";

export type VisualType = "kpi" | "trend" | "breakdown" | "stage_mix" | "top_owners" | "scenario_results" | "alerts" | "sensitivity" | "table";

export interface LensVisualSpec {
  visual_id: string;
  type: VisualType;
  domain: "corporate" | "retail";
  metric_id?: string;
  metric_ids?: string[];
  group_by?: string;
  title?: string;
  columns?: string[];
  sort?: string;
  periods?: number;
  n?: number;
}

export interface BreachRule {
  rule_id: string;
  name: string;
  metric_id: string;
  domain: string;
  comparison: string;
  threshold: number;
  window: string;
  materiality: number | null;
  dedup_key: string;
  cooldown_hours: number;
  severity: string;
  recipients: string[];
}

export interface LensSpec {
  lens_id?: string;
  name: string;
  description: string;
  persona: string;
  domain_scope: ("corporate" | "retail")[];
  metrics: { metric_id: string; domain: string; version?: number }[];
  visuals: LensVisualSpec[];
  layout: Record<string, string[]>;
  filters: Record<string, Filter[]>;
  refresh: { cadence: string; timezone: string; expected_availability: string };
  breach_rules: BreachRule[];
  audience: string[];
  delivery: { workspace: boolean; inbox: boolean; digest: boolean };
  tags?: string[];
  note?: string;
  source?: Record<string, unknown>;
}

export interface LensCard {
  object_id: string;
  version: number;
  lens_id: string;
  name: string;
  description: string;
  persona: string;
  domain_scope: string[];
  status: string;
  owner_id: string;
  seeded: boolean;
  refresh: LensSpec["refresh"];
  kpis: number;
  charts: number;
  tables: number;
  metrics: number;
  breach_rules: number;
  filters: Record<string, Filter[]>;
  last_refresh: null | { at: number; status: string; material_changes: number; breaches: number };
  content_hash: string;
}

export interface RenderedVisual {
  visual_id: string;
  type: VisualType;
  title: string;
  domain: "corporate" | "retail";
  period?: string;
  prior_period?: string;
  release_id?: string;
  metric_id?: string;
  metric_version?: number;
  unit?: string;
  direction?: string;
  filters_applied?: Filter[];
  filters_skipped?: Filter[];
  status: "OK" | "ERROR";
  message?: string;
  value?: number | null;
  prior?: number | null;
  note?: string;
  spark?: { period: string; value: number | null }[];
  series?: { metric_id: string; metric_version: number; name: string; unit: string; points: { period: string; value: number | null }[] }[];
  group_by?: string;
  groups?: { dimension: string; value: number | null; rows?: number; object_id?: string }[];
  rows?: Record<string, unknown>[];
  columns?: string[];
  total?: number;
  total_ead?: number | null;
  key?: string;
}

export interface Observation {
  observation_id: string;
  lens_version: number;
  trigger: string;
  status: string;
  started_at: number;
  finished_at: number;
  release_id: string;
  period: string;
  body: {
    values: Record<string, Record<string, { value: number | null; prior: number | null; period: string }>>;
    material_changes: { metric_id: string; domain: string; name: string; unit: string; from: number | null; to: number | null }[];
    breaches: { rule_id: string; name: string; metric_id: string; domain: string; comparison: string; threshold: number; severity: string; observed: number | null; breached: boolean }[];
    what_changed: string;
  };
}

export interface RenderedLens {
  lens: LensCard & { body: LensSpec; lineage: Record<string, unknown>; permissions: Record<string, unknown>; can_edit: boolean };
  books: Record<string, { period: string; periods: string[]; latest_period: string; release_id: string; fingerprint: string }>;
  cross_filters: (Filter & { domain?: string })[];
  visuals: RenderedVisual[];
  last_observation: Observation | null;
  server_ms: number;
}

export interface Proposal {
  spec: LensSpec;
  matched_template: string | null;
  reasons: string[];
  summary: { kpis: number; charts: number; tables: number; metrics: number; breach_rules: number; refresh: string };
  saved: false;
  source?: Record<string, unknown>;
}

export const listLenses = (q = "") => wsGet<{ lenses: LensCard[]; total: number; shown: number; state: string }>(`/lenses${q ? `?q=${encodeURIComponent(q)}` : ""}`);

export const renderLens = (id: string, body: { periods?: Record<string, string>; cross_filters?: (Filter & { domain?: string })[]; version?: number } = {}) =>
  wsSend<RenderedLens>(`/lenses/${encodeURIComponent(id)}/render`, body);

export const refreshLens = (id: string) => wsSend<Observation & { idempotent?: boolean }>(`/lenses/${encodeURIComponent(id)}/refresh`, {});

export const lensObservations = (id: string) => wsGet<{ observations: Observation[] }>(`/lenses/${encodeURIComponent(id)}/observations`);

export const proposeLens = (body: { prompt?: string; base?: LensSpec; domain?: string; from_investigation?: string; from_thread?: string }) =>
  wsSend<Proposal>("/lenses/propose", body);

export const saveLens = (spec: LensSpec, source?: Record<string, unknown>) => wsSend<GovernedObject<LensSpec>>("/lenses", { spec, source });

export const reviseLens = (id: string, changes: Partial<LensSpec>, reason: string) =>
  wsSend<GovernedObject<LensSpec>>(`/lenses/${encodeURIComponent(id)}/revise`, { changes, reason });
