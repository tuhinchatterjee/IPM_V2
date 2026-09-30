/**
 * What-If runs (P6): scenario and METHOD are separate decisions.
 *
 * WAITING_BASELINE_CHOICE -> SCENARIO_PREVIEW -> (confirm) -> METHOD_SELECTION
 * -> [METHOD_INPUT_REQUIRED | METHOD_UNAVAILABLE] -> READY_TO_EXECUTE ->
 * EXECUTED. Confirming never runs anything; the server refuses to execute a
 * run without a chosen, available method.
 */

import { wsGet, wsSend } from "./client";
import type { GovernedObject } from "./objects";
import type { Decomposition, MethodResult, StageRow } from "../viz/decomposition";

export type RunState =
  | "WAITING_BASELINE_CHOICE"
  | "SCENARIO_PREVIEW"
  | "SCENARIO_CONFIRMED"
  | "METHOD_SELECTION"
  | "METHOD_INPUT_REQUIRED"
  | "METHOD_UNAVAILABLE"
  | "READY_TO_EXECUTE"
  | "EXECUTED";

export type MethodId = "delta" | "ml" | "user_defined";

export interface MethodAvailability {
  status: string;
  label: string;
  reason: string;
  runnable: boolean;
}

export interface BaselineChoice {
  mode: "SOURCE_BASELINE" | "PRIOR_SCENARIO";
  parent_run_id?: string;
}

export interface BaselineOption extends BaselineChoice {
  label: string;
  detail: string;
}

export interface RunCohort {
  cohort_id: string;
  membership_hash: string;
  entity_count: number;
  owner_count: number;
  period: string;
  grain: string;
  predicate: string;
  selection: string;
  baseline_ead: string;
  baseline_ecl: string;
  described_as: string;
  description: string;
  object: { cohort_id: string; version: number | null; name: string; source: string };
}

export interface RunBody {
  scenario_id: string;
  scenario_version: number;
  scenario_name: string;
  domain_id: string;
  release_id: string;
  session_id: string;
  entry: string;
  state: RunState;
  cohort: RunCohort;
  baseline: { mode: string; parent_run_id?: string; parent_scenario_id?: string; parent_contract_digest?: string };
  chain: { scenario_id: string; name: string; executed_run_id: string; delta_change: string }[];
  contract: { scenario_id: string; version: number; digest: string; confirmed_digest: string };
  preview?: {
    population: string;
    entities: number;
    owners: number;
    baseline_ead: string;
    baseline_ecl: string;
    period: string;
    components: { component_id: string; label: string; kind: string }[];
    shocks: { field: string; operation: string; value: string; origin: string; reach: number }[];
    compositions: number;
    stage_policy: string;
    overlay_policy: string;
    notes: string[];
    blockers: Record<string, string[]>;
  };
  availability: Record<MethodId | "compare", MethodAvailability>;
  question?: { text: string; options: BaselineOption[] };
  methods_chosen: string[];
  methods_ran: string[];
  methods_unavailable?: Record<string, string>;
  user_assumption: Record<string, string>;
  gate_message?: string;
  result_id: string;
  delta_change: string;
  state_log: { state: RunState; at: number; reason: string }[];
}

export type Run = GovernedObject<RunBody>;

export interface ResultBody {
  /** Where it was executed: a What-If run, or a Cockpit conversation. */
  entry?: "whatif" | "library" | "cockpit" | "messages";
  thread_id?: string;
  scenario_id: string;
  scenario_version: number;
  scenario_name: string;
  run_id: string;
  session_id: string;
  domain_id: string;
  release_id: string;
  period: string;
  cohort: RunCohort;
  baseline: RunBody["baseline"];
  chain: RunBody["chain"];
  contract_digest: string;
  execution_digest: string;
  methods: { chosen: string[]; ran: string[]; unavailable: Record<string, string> };
  user_assumption: Record<string, string>;
  results: Record<string, MethodResult>;
  book: { baseline: string; outside_cohort: string; rows: number };
  decomposition: Record<string, Decomposition>;
  stages: StageRow[];
  top_contributors: { entity_id: string; owner_id: string; group: string; stage: string; ecl_before: string; ecl_after: string; change: string }[];
  notes: string[];
  stage_policy: string;
  evidence: string;
}

export type ScenarioResult = GovernedObject<ResultBody>;

export interface UserAssumption {
  form: "relative" | "absolute" | "target_amount" | "target_rate" | "elasticity";
  value: string;
  driver_move_pct?: string;
  driver_field?: string;
  stated_as?: string;
}

const SESSION_KEY = "gw.whatif.session";

/** The What-If session: runs in one session are asked about their baseline. */
export function whatIfSession(): string {
  try {
    const found = sessionStorage.getItem(SESSION_KEY);
    if (found) return found;
    const made = `wses-${crypto.randomUUID().slice(0, 12)}`;
    sessionStorage.setItem(SESSION_KEY, made);
    return made;
  } catch {
    return "wses-ephemeral";
  }
}

export function newWhatIfSession(): string {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: the next call makes an ephemeral id */
  }
  return whatIfSession();
}

export const startRun = (input: {
  scenario_id: string;
  scenario_version?: number;
  cohort_id?: string;
  cohort_version?: number;
  session_id: string;
  baseline?: BaselineChoice;
  entry?: "whatif" | "library" | "cockpit" | "messages";
}) => wsSend<Run>("/whatif/runs", input);

export const readRun = (id: string) => wsGet<Run>(`/whatif/runs/${encodeURIComponent(id)}`);

export const listSessionRuns = (sessionId: string, domain: string) =>
  wsGet<{ runs: { object_id: string; state: RunState; scenario_name: string; baseline: RunBody["baseline"]; result_id: string; methods_ran: string[] }[] }>(
    `/whatif/runs?session_id=${encodeURIComponent(sessionId)}&domain=${domain}`,
  );

export const chooseBaseline = (id: string, baseline: BaselineChoice) =>
  wsSend<Run>(`/whatif/runs/${encodeURIComponent(id)}/baseline`, { baseline });

export const confirmRun = (id: string, digest: string) => wsSend<Run>(`/whatif/runs/${encodeURIComponent(id)}/confirm`, { digest });

export const chooseMethod = (id: string, methods: string[], userAssumption?: UserAssumption | null) =>
  wsSend<Run>(`/whatif/runs/${encodeURIComponent(id)}/method`, { methods, user_assumption: userAssumption ?? null });

export const executeRun = (id: string) =>
  wsSend<{ run: Run; result: ScenarioResult }>(`/whatif/runs/${encodeURIComponent(id)}/execute`, {});

export const rerunWithAnotherMethod = (id: string) => wsSend<Run>(`/whatif/runs/${encodeURIComponent(id)}/rerun`, {});

export const STATE_TEXT: Record<RunState, string> = {
  WAITING_BASELINE_CHOICE: "Choose the baseline",
  SCENARIO_PREVIEW: "Preview — review and confirm",
  SCENARIO_CONFIRMED: "Scenario confirmed",
  METHOD_SELECTION: "Scenario confirmed — NOT executed. Choose the method.",
  METHOD_INPUT_REQUIRED: "Scenario confirmed — NOT executed. User-defined needs your impact assumption.",
  METHOD_UNAVAILABLE: "Scenario confirmed — NOT executed. The chosen method cannot run; nothing is substituted.",
  READY_TO_EXECUTE: "Method chosen — ready to run",
  EXECUTED: "Executed",
};
