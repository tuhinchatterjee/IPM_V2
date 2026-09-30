/**
 * What-If Analysis workspace client (P5). The population is a governed
 * cohort; the scenario is a Scenario Library object; a question typed here is
 * an ordinary Cockpit run carrying the active selection by reference.
 */

import { wsGet, wsSend } from "./client";
import type { Cohort, DomainId, Filter } from "./objects";

export interface WhatIfContext {
  domain_id: DomainId;
  release_id: string;
  fingerprint: string;
  period: string;
  period_kind: "quarter" | "month";
  grain: string;
  grain_plural: string;
  owner_plural: string;
  key: string;
  owner: string;
  book: { entities: number; owners: number; ead: number; ecl: number; stage_mix: { stage: number; n: number; ead: number; ecl: number }[] };
  methods: Record<"delta" | "ml" | "user_defined" | "compare", { status: string; label: string; reason?: string; model_version?: string }>;
}

export interface WorkspaceSelection {
  mode: "rows" | "filtered" | "all";
  ids?: string[];
  filters?: Filter[];
}

export interface SelectionSummary {
  entities: number;
  owners: number;
  ead: number;
  ecl: number;
  stage_mix: { stage: number; n: number; ead: number; ecl: number }[];
  band_dimension: string;
  band_mix: { band: string; n: number; ead: number }[];
  period: string;
  filters: Filter[];
  filter_description: string;
  mode: string;
  grain: string;
  grain_plural: string;
  owner_plural: string;
  share_of_book_ead: number | null;
  share_of_book_ecl: number | null;
  book: { entities: number; ead: number; ecl: number };
  release_id: string;
  fingerprint: string;
}

export interface ThreadCohort {
  thread_id: string;
  has_cohort: boolean;
  message?: string;
  entities?: number;
  owners?: number;
  membership_hash?: string;
  described_as?: string;
  scenario_id?: string;
  state?: string;
}

export const readWhatIfContext = (domain: DomainId) => wsGet<WhatIfContext>(`/whatif/context?domain=${domain}`);

export const summariseSelection = (domain: DomainId, selection: WorkspaceSelection) =>
  wsSend<SelectionSummary>("/whatif/selection/summary", { domain, selection });

export const saveSelection = (domain: DomainId, selection: WorkspaceSelection, name: string, byOwner = false) =>
  wsSend<Cohort>("/whatif/selection/cohort", { domain, selection, name, by_owner: byOwner });

export const investigateCohort = (cohortId: string) =>
  wsSend<{ thread_id: string; cohort_id: string }>("/whatif/investigate", { cohort_id: cohortId });

export const readThreadCohort = (threadId: string) => wsGet<ThreadCohort>(`/whatif/threads/${encodeURIComponent(threadId)}/cohort`);

export const adoptThreadCohort = (threadId: string, name = "") =>
  wsSend<Cohort>(`/whatif/threads/${encodeURIComponent(threadId)}/adopt-cohort`, { name });

export const askContext = (cohortId: string, scenarioId: string) =>
  wsSend<Record<string, unknown>>("/whatif/ask-context", { cohort_id: cohortId, scenario_id: scenarioId });

export const shareObject = (objectId: string, to: string[], message = "", version?: number) =>
  wsSend<{ shared: unknown[]; object: Record<string, unknown> }>("/share", { object_id: objectId, to, message, version });

export { EXPLORER_DIMENSIONS, selectedValues, setFilterValues, toggleFilterValue } from "./whatif-filters";
