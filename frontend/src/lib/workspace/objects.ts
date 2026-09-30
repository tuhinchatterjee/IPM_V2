/**
 * Shared governed objects (P2): cohort, finding, investigation, scenario,
 * scenario result, lens, alert. One identity `(object_id, version)` in every
 * module; edits make new versions; duplicates and compositions keep lineage.
 */

import { qs, workspaceUrl, wsGet, wsSend } from "@/lib/workspace/client";

export type DomainId = "corporate" | "retail";

export interface Filter {
  column: string;
  op:
    | "eq"
    | "neq"
    | "gt"
    | "gte"
    | "lt"
    | "lte"
    | "in"
    | "not_in"
    | "contains"
    | "between"
    | "is_null"
    | "not_null"
    | "is_true"
    | "is_false";
  value?: string | number | boolean;
  values?: (string | number | null)[];
}

export interface GovernedObject<B = Record<string, unknown>> {
  object_id: string;
  version: number;
  kind: string;
  title: string;
  status: string;
  domain_id: string;
  release_id: string;
  fingerprint: string;
  period: string;
  owner_id: string;
  body: B;
  lineage: Record<string, unknown>;
  permissions: Record<string, unknown>;
  trace_refs: string[];
  tags: string[];
  content_hash: string;
  seeded: boolean;
  created_at: number;
}

export interface CohortBody {
  name: string;
  description: string;
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  grain: string;
  owner_grain: string;
  selection: "row" | "owner";
  filters: Filter[];
  filter_description: string;
  membership_hash: string;
  predicate_hash: string;
  counts: { entities: number; owners: number };
  ead: number;
  ecl: number;
  stage_mix: { stage: number; n: number; ead: number; ecl: number }[];
  band_mix: { band: string; n: number; ead: number }[];
  band_dimension: string;
  source: { kind: string; ref?: string; label?: string };
  member_ids_preview: string[];
}

export type Cohort = GovernedObject<CohortBody>;

export const freezeCohort = (input: {
  domain: DomainId;
  name: string;
  filters: Filter[];
  selection?: "row" | "owner";
  source?: { kind: string; ref?: string; label?: string };
  description?: string;
  snapshot?: boolean;
}) => wsSend<Cohort>("/cohorts", input);

export const listCohorts = (domain?: DomainId) =>
  wsGet<{ cohorts: (Cohort & { counts: CohortBody["counts"]; ead: number; ecl: number })[] }>(
    `/cohorts${qs({ domain })}`,
  );

export const readObject = <B = Record<string, unknown>>(id: string, version?: number) =>
  wsGet<GovernedObject<B>>(`/objects/${encodeURIComponent(id)}${qs({ version })}`);

export const verifyCohort = (id: string) =>
  wsGet<{ status: string; identical: boolean; message?: string; saved_hash?: string; resolved_hash?: string }>(
    `/cohorts/${encodeURIComponent(id)}/verify`,
  );

export const refreshCohort = (id: string) => wsSend<Cohort>(`/cohorts/${encodeURIComponent(id)}/refresh`, {});

export const objectHistory = (id: string) =>
  wsGet<{ versions: (GovernedObject & { lineage: Record<string, unknown> })[] }>(
    `/objects/${encodeURIComponent(id)}/history`,
  );

export const objectLineage = (id: string) =>
  wsGet<{
    object_id: string;
    ancestors: { object_id: string; version: number; title: string; kind: string }[];
    descendants: { object_id: string; version: number; title: string; kind: string; operation: string }[];
    versions: { version: number; status: string; reason: string; content_hash: string; created_at: number }[];
  }>(`/objects/${encodeURIComponent(id)}/lineage`);

export const addComment = (id: string, body: string, version?: number) =>
  wsSend(`/objects/${encodeURIComponent(id)}/comments`, { body, version });

export const listComments = (id: string) =>
  wsGet<{ comments: { comment_id: string; version: number; author_id: string; body: string; created_at: number }[] }>(
    `/objects/${encodeURIComponent(id)}/comments`,
  );

/** Where a governed object opens in the product. */
export function objectHref(kind: string, id: string, extra: Record<string, string> = {}): string {
  const tail = qs(extra);
  switch (kind) {
    case "cohort":
      return `/what-if${qs({ cohort: id, ...extra })}`;
    case "scenario":
      return `/what-if${qs({ scenario: id, ...extra })}`;
    case "scenario_result":
      return `/what-if${qs({ result: id, ...extra })}`;
    case "lens":
      return `/lenses/${encodeURIComponent(id)}${tail}`;
    case "alert":
      return `/monitoring${qs({ alert: id, ...extra })}`;
    default:
      return `/messages${qs({ object: id })}`;
  }
}

/** Where a saved cohort's CSV export is served (release/fingerprint/predicate in its header). */
export function workspaceCohortExportUrl(id: string): string {
  return workspaceUrl(`/cohorts/${encodeURIComponent(id)}/export`);
}
