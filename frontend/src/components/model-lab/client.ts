/**
 * Model-lab API client. Lab-only; talks to /api/v1/model-lab on the same
 * origin the frozen Cockpit client uses. Never sees a provider credential:
 * the server holds every key and endpoint secret.
 */

export const LAB_PREFIX = "/api/v1/model-lab";

export function labEnabled(): boolean {
  return (
    process.env.NEXT_PUBLIC_COCKPIT_V4_LAB === "true" &&
    Boolean(process.env.NEXT_PUBLIC_COCKPIT_V4_API?.trim())
  );
}

function base(): string {
  const configured = process.env.NEXT_PUBLIC_COCKPIT_V4_API?.trim() ?? "";
  if (configured === "same-origin") return "";
  return configured.replace(/\/$/, "");
}

export function labUrl(path: string): string {
  return `${base()}${LAB_PREFIX}${path}`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(labUrl(path), {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* not JSON */
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw Object.assign(new Error(`lab request failed (${response.status})`), {
      status: response.status,
      detail,
    });
  }
  return body as T;
}

export type Metric = {
  value: number | string | null;
  unit: string;
  status: string;
  source: string;
  missing_reason: string;
  definition: string;
};

export type Readiness = {
  profile_id: string;
  status: string;
  reasons: string[];
  recovery: string;
};

export type Profile = {
  profile_id: string;
  display_name: string;
  role: string;
  family: string;
  registry_id: string;
  route: string;
  readiness: Readiness;
  limitations?: string[];
  description?: string;
  profile_digest: string;
};

export type Preset = {
  preset_id: string;
  name: string;
  profiles: string[];
  comparator: string;
  execution_mode: string;
  deployment: string;
  trial_count: number;
  group_spend_cap_usd: number;
  group_wall_clock_s: number;
  note?: string;
};

export type Stage = {
  status: string;
  note?: string;
  calls: string[];
  shared_calls: string[];
  checks: string[];
  evidence_confidence: string;
};

export type Check = {
  check_id: string;
  stage: string;
  kind: string;
  outcome: string;
  expected: unknown;
  actual: unknown;
  tolerance?: unknown;
  truth_source: string;
  severity: string;
  status: string;
  note?: string;
  evidence_ref: Record<string, unknown> | null;
  detail?: unknown;
  review?: { decision: string; reason: string };
};

export type Claim = {
  claim_id: string;
  extracted_text: string;
  claim_type: string;
  asserted_value: number | null;
  units: string | null;
  verification_status: string;
  evidence_status?: string;
  row_label?: string | null;
  frozen_validation?: { status: string; message: string } | null;
  extraction_method: string;
  extraction_confidence_class: string;
  explanation: string;
  reviewer_status: string;
  review?: { decision: string; reason: string; automatic_status: string };
};

export type Call = {
  call_id: string;
  run_id: string;
  seq: number;
  purpose: string;
  phase: string;
  stage_tags: string[];
  tool_names: string[];
  tool_names_source?: string;
  evidence_status?: string;
  tool_names_disagree?: string[];
  outcome: string;
  usable: boolean;
  stop_reason: string;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  token_status: string;
  token_source: string;
  errors_returned: string[];
  protocol_flag: string;
};

export type Failure = {
  primary_category: string;
  supporting_categories: string[];
  symptom: string;
  failed_requirement: string;
  likely_owner: string;
  origin_confidence: string;
  affected_stages: string[];
  inherited_effects: string[];
  severity: string;
  next_diagnostic: string;
  intervention_category: string;
  approval_needed: string;
  model_failure: boolean;
};

export type MatchStage = {
  pct: number | null;
  display: string;
  reason?: string;
  assessed?: number;
  defined?: number;
  checks: {
    check_id: string;
    description: string;
    weight: number;
    agree: boolean | null;
  }[];
};

export type ChildEval = {
  child_run_id: string;
  profile_id: string;
  display_name: string;
  fixture: boolean;
  execution_state: string;
  frozen_state?: string;
  error_code?: string;
  reason: string;
  requested_model: string;
  identity: { status: string; resolved?: string[] };
  answer: {
    disposition?: string;
    narrative?: string;
    clarification_question?: string;
    limitations?: string[];
    tables?: {
      title?: string;
      columns?: string[];
      rows?: { display?: Record<string, unknown> }[];
    }[];
  } | null;
  turns: { run_id: string; kind: string; question: string; frozen_state: string }[];
  calls: Call[];
  app_lane: {
    kind: string;
    status: string;
    start_ms: number;
    end_ms: number;
    duration_ms: number;
    message: string;
  }[];
  checks: Check[];
  claims: Claim[];
  claim_rates: Record<string, { display: string; numerator: number; denominator: number } | number | string>;
  repair: {
    status: string;
    opportunities: number;
    attempts: number;
    valid_repairs: number;
    business_correct_recoveries: number | null;
    note: string;
    chains: {
      call_id: string;
      error_code: string;
      feedback: string;
      revalidation: string;
      diff?: { unified: string } | null;
    }[];
  };
  stages: Record<string, Stage>;
  metrics: Record<string, Metric | string | number>;
  failures: Failure[];
  first_divergence: { stage: string; summary: string; confidence: string } | null;
  opus_match: Record<string, MatchStage> | null;
};

export type Evaluation = {
  comparison_id: string;
  evaluator_version: string;
  oracle_version: string;
  comparator: {
    profile_id: string;
    is_opus: boolean;
    is_fixture: boolean;
    status: string;
    note: string;
  };
  task: { task_id: string; description: string } | null;
  reference: { period: string; unit: string; largest: string } | null;
  comparison_elapsed_ms: Metric;
  children: ChildEval[];
  summary: Record<string, number | string>;
  comparison_class: string[];
  release_claim: string;
};

export type ComparisonChild = {
  child_run_id: string;
  profile_id: string;
  display_name: string;
  state: string;
  reason: string;
  fixture: boolean;
  lane: string;
  turns: { kind: string; state: string | null }[];
};

export type Comparison = {
  comparison_id: string;
  state: string;
  spec: { question_text: string; comparator_id: string; data_snapshot_id: string };
  children: ComparisonChild[];
  evaluation: Evaluation | null;
  evaluation_revision: number | null;
  export: { state: string; revision: number; sha256: string } | null;
};

export type PreflightRow = {
  profile_id: string;
  display_name: string;
  status: string;
  reasons: string[];
  recovery: string;
  eligible: boolean;
  fixture: boolean;
  lane: string;
  price: { status: string; basis: string };
};

export type Preflight = {
  ok: boolean;
  errors: string[];
  profiles: PreflightRow[];
  comparator: { profile_id: string; ready: boolean; status: string };
  estimates: { paid_children: number; reserve_usd: number; group_spend_cap_usd: number };
};

export type CompareInput = {
  question: string;
  profile_ids: string[];
  comparator_id: string;
  preset_id: string;
  deployment: string;
  trial_count: number;
  group_spend_cap_usd: number;
  group_wall_clock_s: number;
};

export const readProfiles = () =>
  call<{ profiles: Profile[]; presets: Preset[] }>("/model-profiles");
export const preflight = (input: CompareInput) =>
  call<Preflight>("/comparisons/preflight", {
    method: "POST",
    body: JSON.stringify(input),
  });
export const createComparison = (input: CompareInput, key: string) =>
  call<Comparison>("/comparisons", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Idempotency-Key": key },
  });
export const readComparison = (id: string) =>
  call<Comparison>(`/comparisons/${encodeURIComponent(id)}`);
export const listComparisons = () =>
  call<{ comparisons: { comparison_id: string; state: string; question: string; created_at: number }[] }>(
    "/comparisons",
  );
export const cancelComparison = (id: string) =>
  call<Comparison>(`/comparisons/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
export const answerClarification = (id: string, text: string, childIds: string[]) =>
  call<Comparison>(`/comparisons/${encodeURIComponent(id)}/clarifications`, {
    method: "POST",
    body: JSON.stringify({ text, child_ids: childIds }),
  });
export const addReview = (
  id: string,
  target: string,
  decision: string,
  reason: string,
) =>
  call<{ review_id: string }>(`/comparisons/${encodeURIComponent(id)}/reviews`, {
    method: "POST",
    body: JSON.stringify({ target, decision, reason }),
  });
export const exportUrl = (id: string) =>
  labUrl(`/comparisons/${encodeURIComponent(id)}/export`);
