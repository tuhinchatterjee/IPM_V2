/**
 * Scenario Library client (P4). Nothing here executes a scenario: every call
 * saves a definition, makes a new version, or previews a definition against
 * the book. Execution is the METHOD_SELECTION path (P6).
 */

import { wsGet, wsSend } from "./client";
import type { DomainId } from "./objects";

export type Severity = "upside" | "mild" | "moderate" | "severe";

export interface Filter {
  column: string;
  op: string;
  value?: unknown;
  values?: unknown[];
}

export interface Scope {
  type: "whole_book" | "filters" | "top_owners" | "any_of" | "cohort";
  label?: string;
  filters?: Filter[];
  n?: number;
  by?: string;
  scopes?: Scope[];
  cohort_id?: string;
  membership_hash?: string;
}

export interface Component {
  component_id?: string;
  kind: "parameter" | "utilisation" | "rating" | "score" | "delinquency" | "macro" | "collateral" | "overlay";
  label?: string;
  field?: string;
  factor_id?: string;
  score_type?: string;
  asset?: string;
  operation: string;
  value: string;
  where?: Filter[];
  within?: Scope;
  priority?: number;
  source?: { object_id: string; version: number; component_id: string; scenario: string };
}

export interface Resolution {
  policy: string;
  order?: string[];
  chosen_by?: string;
}

export interface Definition {
  name: string;
  domain_id: DomainId;
  description: string;
  risk_thesis: string;
  scope: Scope;
  components: Component[];
  stage_policy: string;
  composition_policy: { resolutions: Record<string, Resolution>; note?: string };
  supported_methods: string[];
  severity: Severity;
  tags: string[];
  assumptions: string[];
  limitations: string[];
  bounds_policy?: Record<string, unknown>;
  template_id?: string;
  cloned_from_template?: string;
  parents?: { object_id: string; version: number; name: string; content_hash: string }[];
  bound_cohort?: Record<string, unknown> | null;
  status?: string;
}

export interface ScenarioCard {
  object_id: string;
  version: number;
  name: string;
  template_id: string;
  domain_id: DomainId;
  description: string;
  risk_thesis: string;
  scope_label: string;
  scope_type: string;
  components: { component_id: string; kind: string; label: string }[];
  supported_methods: string[];
  stage_policy: string;
  severity: Severity;
  tags: string[];
  status: string;
  owner_id: string;
  is_template: boolean;
  can_edit: boolean;
  bound_cohort: Record<string, unknown> | null;
  parents: { object_id: string; version: number; name: string }[];
  resolved_overlaps: number;
  results: number;
  content_hash: string;
  created_at: number;
  release_id: string;
  lineage_origin: string;
}

export interface Listing {
  scenarios: ScenarioCard[];
  total: number;
  facets: Record<"domain" | "severity" | "tag" | "status", Record<string, number>>;
  seed_version: string;
}

export interface ScenarioObject {
  object_id: string;
  version: number;
  title: string;
  status: string;
  owner_id: string;
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  content_hash: string;
  body: Definition;
  lineage: Record<string, unknown>;
  permissions: Record<string, unknown>;
}

export interface ScenarioDetail {
  scenario: ScenarioObject;
  card: ScenarioCard;
  lineage: {
    ancestors: { object_id: string; version: number; title: string }[];
    descendants: { object_id: string; version: number; title: string; operation: string }[];
    versions: { version: number; status: string; reason: string; content_hash: string; created_at: number }[];
  };
  equation: string;
  contract_hash: string;
  comments: { comment_id: string; version: number; author_id: string; body: string; created_at: number }[];
}

export interface Overlap {
  a: string;
  b: string;
  a_label: string;
  b_label: string;
  shared_entities: number;
  variables: string[];
  status: "NO_CONFLICT" | "NEEDS_POLICY" | "RESOLVED" | "RESOLVED_BY_GOVERNED_RULE" | "INVALID_POLICY";
  overlap_id?: string;
  variable?: string;
  policy?: string;
  policy_text?: string;
  order?: string[];
  allowed?: string[];
  reason?: string;
}

export interface AssessedComponent {
  component_id: string;
  kind: string;
  label: string;
  status: string;
  reason?: string;
  sign_review?: boolean;
  families: string[];
  population: { entities: number; owners: number; ead: number; ecl: number; mean_pd: number | null; mean_lgd_pct: number | null };
  methods: Record<string, string>;
  translation: Record<string, unknown> | null;
}

export interface MethodStatus {
  status: string;
  reason?: string;
  covers?: string[];
  does_not_cover?: string[];
  model_version?: string;
  requested?: boolean;
}

export interface Preview {
  calculated: false;
  statement: string;
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  scope: Scope & {
    summary: {
      entities: number;
      owners: number;
      ead: number;
      ecl: number;
      stage_mix: { stage: number; n: number; ead: number; ecl: number }[];
      band_dimension: string;
      band_mix: { band: string; n: number; ead: number }[];
      period: string;
    };
    share_of_book_ead: number | null;
    share_of_book_ecl: number | null;
    book: { entities: number; ead: number; ecl: number };
  };
  components: AssessedComponent[];
  overlaps: Overlap[];
  methods: Record<string, MethodStatus> & { selected: null; note: string };
  stage_policy: { policy: string; text: string };
  blocking: { code: string; message: string; overlap_id?: string; component_id?: string }[];
  readiness: "BLOCKED" | "READY_WITH_USER_DEFINED_INPUTS" | "READY_FOR_CONFIRMATION";
  equation: string;
  contract: Record<string, unknown>;
  contract_hash: string;
  object_id?: string;
  version?: number;
}

export interface LibraryMeta {
  kinds: string[];
  policies: string[];
  policy_text: Record<string, string>;
  stage_policies: Record<string, string>;
  severities: string[];
  macro_operations: string[];
}

export function listScenarios(params: Record<string, string> = {}): Promise<Listing> {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "")).toString();
  return wsGet<Listing>(`/scenarios${q ? `?${q}` : ""}`);
}

export const readScenario = (id: string, version?: number) =>
  wsGet<ScenarioDetail>(`/scenarios/${encodeURIComponent(id)}${version ? `?version=${version}` : ""}`);

export const previewScenario = (id: string, version?: number) =>
  wsSend<Preview>(`/scenarios/${encodeURIComponent(id)}/preview${version ? `?version=${version}` : ""}`, {});

export const previewDefinition = (definition: Partial<Definition>) =>
  wsSend<Preview>("/scenarios/preview", { definition });

export const scenarioMeta = () => wsGet<LibraryMeta>("/scenarios/meta");

export const createScenario = (definition: Partial<Definition>, status: "DRAFT" | "SAVED" = "DRAFT") =>
  wsSend<ScenarioObject>("/scenarios", { definition, status });

export const reviseScenario = (id: string, changes: Partial<Definition>, reason: string) =>
  wsSend<ScenarioObject>(`/scenarios/${encodeURIComponent(id)}/revise`, { changes, reason });

export const cloneScenario = (id: string, name = "", branch = false) =>
  wsSend<ScenarioObject>(`/scenarios/${encodeURIComponent(id)}/${branch ? "branch" : "clone"}`, { name });

export const combinePreview = (sources: { object_id: string; version?: number }[], name: string, resolutions: Record<string, Resolution> = {}) =>
  wsSend<{ definition: Definition; preview: Preview }>("/scenarios/combine-preview", { sources, name, resolutions });

export const combineScenarios = (sources: { object_id: string; version?: number }[], name: string, resolutions: Record<string, Resolution> = {}) =>
  wsSend<{ scenario: ScenarioObject; preview: Preview }>("/scenarios/combine", { sources, name, resolutions });

export const resolveOverlaps = (id: string, resolutions: Record<string, Resolution>) =>
  wsSend<ScenarioObject>(`/scenarios/${encodeURIComponent(id)}/resolve`, { resolutions });

export const bindScenario = (id: string, cohortId: string) =>
  wsSend<{ scenario: ScenarioObject; cohort_check: Record<string, unknown> }>(`/scenarios/${encodeURIComponent(id)}/bind`, { cohort_id: cohortId });

export const retireScenario = (id: string) => wsSend<ScenarioObject>(`/scenarios/${encodeURIComponent(id)}/retire`, {});

export const shareScenario = (id: string, to: string[], message: string) =>
  wsSend<{ shared: unknown[] }>(`/scenarios/${encodeURIComponent(id)}/share`, { to, message });

export interface ScenarioResultRow {
  object_id: string;
  version: number;
  created_at: number;
  run_id: string;
  scenario_version: number;
  methods_ran: string[];
  baseline_mode: string;
  cohort: string;
  changes: Record<string, string | null>;
}

export const listScenarioResults = (id: string) =>
  wsGet<{ results: ScenarioResultRow[] }>(`/scenarios/${encodeURIComponent(id)}/results`);
