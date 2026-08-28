/**
 * The backend API client.
 *
 * Every call to the FastAPI backend goes through here. One place that knows the
 * base URL, sets the headers, applies a timeout, and turns a failure into a
 * typed error — rather than each screen inventing its own `fetch`.
 *
 * The types below mirror the FastAPI response shapes. When those change, this
 * file changes with them; keeping the names identical is what makes the drift
 * obvious in review.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * The same address, written for a person to read.
 *
 * When CreditProbe runs in Docker the base URL is deliberately empty: the browser calls
 * this page's own origin and the Next.js server forwards it to the backend
 * container. An empty string is correct for `fetch` and useless in a sentence,
 * so anything shown to a user goes through this instead.
 */
export const API_DISPLAY_URL =
  API_BASE_URL || "this page's own address, forwarded to the CreditProbe backend";

const API_PREFIX = "/api/v1";
const DEFAULT_TIMEOUT_MS = 20_000;

/**
 * The caller's role, sent on every request.
 *
 * The backend has no login yet and reads the role from this header (see
 * backend/api/permissions.py). It is a demonstration of the permission model,
 * not authentication — the UI is explicit about that wherever it matters.
 */
export type Role = "ADMIN" | "DATA_STEWARD" | "ANALYST" | "VIEWER";

let activeRole: Role = "ADMIN";
export function setActiveRole(role: Role) {
  activeRole = role;
}
export function getActiveRole(): Role {
  return activeRole;
}

// ---------------------------------------------------------------------------
// Types — mirror the backend response models
// ---------------------------------------------------------------------------

export type ComponentStatus =
  | "ok"
  | "degraded"
  | "unavailable"
  | "not_configured"
  | "empty";

export type OverallStatus = "ok" | "degraded" | "unavailable";

export interface ComponentHealth {
  name: string;
  status: ComponentStatus;
  detail: string;
  data: Record<string, unknown>;
}

export interface HealthResponse {
  status: OverallStatus;
  app: string;
  version: string;
  environment: string;
  phase: string;
  components: ComponentHealth[];
}

export interface AnalyticalDatasetSummary {
  name: string;
  business_name: string;
  domain: string;
  grain: string;
  field_count: number;
  periods: string[];
  is_synthetic: boolean;
}

export interface CatalogResponse {
  dataset_count: number;
  field_count: number;
  domains: Record<string, string[]>;
  datasets: AnalyticalDatasetSummary[];
}

// ---- engine ---------------------------------------------------------------

export interface AnalysisSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  owner: string;
  certification: string;
  is_certified: boolean;
  is_runnable: boolean;
  required_datasets: string[];
  requires_compare_period: boolean;
  supported_visualizations: string[];
  parameter_count: number;
}

export interface AnalysisLibraryResponse {
  total: number;
  certified: number;
  user_defined: number;
  analyses: AnalysisSummary[];
}

export interface ParameterDef {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default: unknown;
  allowed_values: unknown[] | null;
  minimum: number | null;
  maximum: number | null;
}

export interface OutputFieldDef {
  name: string;
  description: string;
  data_type: string;
  unit: string | null;
  precision: number | null;
}

export interface ValidationRuleDef {
  name: string;
  description: string;
  severity: string;
}

export interface AnalysisDetail extends AnalysisSummary {
  required_fields: string[];
  parameters: ParameterDef[];
  outputs: OutputFieldDef[];
  validation_rules: ValidationRuleDef[];
  calculation_description: string;
  datasets: {
    name: string;
    business_name?: string;
    domain?: string;
    grain?: string;
    is_synthetic?: boolean;
    available: boolean;
    note?: string;
  }[];
  validation_status: string;
}

export type Row = Record<string, string | number | boolean | null>;

export type Direction = "up-is-bad" | "up-is-good" | "neutral";

export interface EngineResult {
  rows: Row[];
  values: Record<string, unknown>;
  units: Record<string, string>;
  input_row_count: number;
  warnings: string[];
  meta: Record<string, string>;

  /* A dynamic analysis carries what it was composed from as well as what it
   * returned. Optional, because a certified engine analysis has none of it —
   * its methodology lives in the Engine Registry instead. */
  plan?: AnalyticalPlanPayload;
  query?: { sql: string; parameters: unknown[] } | null;
  reading?: DynamicReading;
  /**
   * What each column is, not only what it is called.
   *
   * The backend's presentation contract: label, semantic type, unit,
   * decimals, alignment, and the role a derived column plays. Rendering from
   * it is what keeps 73391.774000000012 out of a table and puts the reporting
   * date into the heading of an opening-balance column.
   */
  columns?: {
    name: string;
    type?: string;
    label?: string;
    semantic?: string;
    unit?: string;
    currency?: string;
    scale?: string;
    decimals?: number;
    align?: string;
    is_identity?: boolean;
    role?: string;
  }[];
  certification?: string;
  certification_label?: string;
  truncated?: boolean;

  /* A multi-dataset analysis carries how it was assembled: which sources, on
   * which governed joins, how the population changed at each step, and what
   * identifies the run. Absent on a single-dataset analysis, which has no join
   * to explain. */
  datasets?: string[];
  joins?: JoinStep[];
  reconciliation?: ReconciliationStep[];
  join_plan?: JoinPlan | null;
  explanation?: string;
  fingerprint?: RunFingerprint;
}

export interface JoinStep {
  step: string;
  label: string;
  policy: string;
  keys: string[];
  rows_out: number | null;
  rows_lost: number | null;
  lost_pct: number | null;
  temporal_rule: string;
  relationship_id?: number | null;
  relationship_name?: string;
  relationship_version?: number;
  from?: string;
  to?: string;
  cardinality?: string;
  note?: string;
}

export interface ReconciliationStep {
  step: string;
  label: string;
  rows: number;
  lost: number | null;
  lost_pct: number | null;
  reduced_by_design?: boolean;
}

export interface JoinPathEdge {
  relationship_id: number;
  relationship_name: string;
  relationship_version: number;
  left: string;
  left_field: string;
  right: string;
  right_field: string;
  cardinality: string;
  join_policy: string;
  temporal_rule: string;
  semantic: string;
  multiplies_left: boolean;
}

export interface JoinPath {
  target: string;
  hops: number;
  datasets: string[];
  edges: JoinPathEdge[];
  multiplies: boolean;
  needs_asof: boolean;
  score: number;
  reasons: string[];
  description: string;
}

export interface JoinPlan {
  base: string;
  datasets: string[];
  paths: JoinPath[];
  edges: JoinPathEdge[];
  /** Dataset name → why nothing reaches it. */
  unreachable: Record<string, string>;
  /** Dataset name → the materially different paths that reach it. */
  ambiguous: Record<string, JoinPath[]>;
  warnings: string[];
  ok: boolean;
  summary: string;
}

export interface RunFingerprint {
  run: string;
  plan: string;
  data: string;
  relationships: string;
  parameters: string;
  datasets?: { dataset: string; version: string; origin: string; periods: string[] }[];
  relationships_used?: { relationship_id: number; version: number; cardinality: string }[];
}

export interface AnalyticalPlanPayload {
  id?: string;
  operations: {
    id: string;
    op: string;
    inputs?: string[];
    params?: Record<string, unknown>;
    label?: string;
  }[];
  meta?: Record<string, unknown>;
}

export interface DynamicCondition {
  field: string;
  kind: string;
  op: string;
  value: number;
  phrase: string;
  column: string;
  description: string;
}

export interface DynamicReading {
  understood: boolean;
  dataset: string;
  grain: string;
  opening_period: string;
  closing_period: string;
  filters: { field: string; value: string }[];
  conditions: DynamicCondition[];
  columns: string[];
  summary: string;
  reasons: string[];
}

export interface TraceNode {
  id: string;
  type: string;
  label: string;
  config: Record<string, unknown>;
  status: string;
  is_governed: boolean;
  duration_ms: number | null;
  rows_in: number | null;
  rows_out: number | null;
  output_preview: Row[] | null;
  output_summary: Record<string, unknown>;
  warnings: string[];
  error: string | null;
  dataset: string | null;
  fields_used: string[];
  function_id: string | null;
  function_version: string | null;
  content_hash: string | null;
}

export interface TraceGraph {
  nodes: TraceNode[];
  edges: { source: string; target: string; label: string | null }[];
  layers: string[][];
  stats: {
    node_count: number;
    edge_count: number;
    governed_nodes: number;
    interpretive_nodes: number;
  };
}

export interface AnalysisRunResponse {
  analysis_id: string;
  analysis_version: string;
  certification: string;
  status: string;
  params: Record<string, unknown>;
  context: Record<string, unknown>;
  result: EngineResult | null;
  duration_ms: number;
  error: string | null;
  trace: TraceGraph;
  node_hashes: Record<string, string>;
  analysis_run_id: number | null;
}

export interface StoredTrace {
  analysis_run_id: number;
  analysis_id: string | null;
  status: string;
  created_at: string | null;
  duration_ms: number | null;
  context: Record<string, unknown>;
  version: number;
  label: string;
  graph: TraceGraph;
  node_hashes: Record<string, string>;
  available_versions: { version: number; label: string }[];
}

export interface PeriodsResponse {
  dataset: string;
  periods: string[];
  latest: string | null;
  earliest: string | null;
  count: number;
  aliases: Record<string, string | null>;
}

export interface DimensionsResponse {
  dataset: string;
  period: string | null;
  dimensions: {
    field: string;
    business_name: string;
    definition: string;
    data_type: string;
    value_count: number;
    values: string[];
  }[];
}

// ---- data builder ---------------------------------------------------------

export interface DomainSummary {
  name: string;
  description: string;
  owner: string;
  status: DomainStatus;
  sort_order: number;
}

export type DomainStatus = "ACTIVE" | "ARCHIVED";

/**
 * A domain with what is actually in it.
 *
 * Row counts and period coverage come from the published lake, so a domain
 * whose datasets are still in draft reports nothing rather than a number that
 * does not exist yet.
 */
export interface DomainOverview extends DomainSummary {
  dataset_count: number;
  published_count: number;
  row_count: number;
  period_count: number;
  first_period: string | null;
  last_period: string | null;
  datasets: {
    name: string;
    business_name: string;
    lifecycle: Lifecycle;
    is_synthetic: boolean;
    readable: boolean;
  }[];
}

export type Lifecycle = "draft" | "mapped" | "validated" | "published" | "archived";

export interface DatasetSummary {
  name: string;
  domain: string;
  business_name: string;
  purpose: string;
  grain: string;
  owner: string;
  period_field: string;
  primary_keys: string[];
  lifecycle: Lifecycle;
  source_type: string;
  is_synthetic: boolean;
  published_version: number | null;
  published_at: string | null;
  field_count: number;
  upload_count: number;
  storage_location: string;
  created_at: string | null;
}

export interface ColumnProfile {
  name: string;
  inferred_type: string;
  pandas_dtype: string;
  null_count: number;
  null_pct: number;
  unique_count: number;
  suggested_governed_name: string;
  min?: number | string;
  max?: number | string;
  mean?: number;
  negative_count?: number;
  sample_values?: string[];
  is_categorical?: boolean;
}

export interface UploadProfile {
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  period_candidates: string[];
  date_range: Record<string, { min: string; max: string }>;
  preview: Record<string, string>[];
  profiled_at: string;
}

export interface UploadRecord {
  id: number;
  filename: string;
  file_format: string;
  sheet_name: string | null;
  raw_path: string;
  file_sha256: string;
  size_bytes: number;
  row_count: number;
  column_count: number;
  uploaded_at: string | null;
}

export type MappingStatus = "mapped" | "unmapped" | "ignored" | "proposed";

export interface FieldMappingRow {
  source_column: string;
  governed_field: string | null;
  status: MappingStatus;
  confidence: number | null;
  note: string;
}

export interface DictionaryField {
  name: string;
  business_name: string;
  definition: string;
  data_type: string;
  unit: string | null;
  allowed_values: string[] | null;
  sensitivity: string;
  nullable: boolean;
  source_system: string;
  source_field: string;
}

export interface RelationshipRow {
  id?: number;
  name: string;
  from_dataset: string;
  from_field: string;
  to_dataset: string;
  to_field: string;
  cardinality: string;
  kind: string;
  description?: string;
}

export interface DatasetDetail extends DatasetSummary {
  latest_upload: UploadRecord | null;
  mappings: FieldMappingRow[];
  fields: DictionaryField[];
  relationships: RelationshipRow[];
}

export interface QualityFinding {
  rule: string;
  severity: "error" | "warning";
  detail: string;
  count?: number;
}

export interface ValidationReport {
  dataset: string;
  row_count: number;
  field_count: number;
  checked_at: string;
  findings: QualityFinding[];
  error_count: number;
  warning_count: number;
  passed: boolean;
}

export interface PublishResponse {
  dataset: string;
  version: number;
  row_count: number;
  field_count: number;
  periods: string[];
  analytics_path: string;
  curated_path: string;
  quality_report: ValidationReport;
  published_at: string | null;
  message: string;
}

export interface DataVersionRow {
  version: number;
  row_count: number;
  field_count: number;
  periods: string[];
  analytics_path: string;
  quality_report: ValidationReport;
  published_at: string | null;
}


// ---- Ask CreditProbe --------------------------------------------------------------

export interface PlanStepDef {
  analysis_id: string;
  title: string;
  rationale: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  period: string | null;
  /** Exactly one step answers the question; the rest only help explain it. */
  role?: "primary" | "supporting";
}

/** How CreditProbe read the question. Recorded so a misreading is visible. */
export interface PlanScope {
  focus: string;
  dimension: string | null;
  output: string;
  period_requirement: string;
  period_specified: boolean;
  from_period: string | null;
  to_period: string | null;
  period_source: string;
  filters: Record<string, unknown>;
}

export interface PlanDef {
  question: string;
  intent: string;
  scope?: PlanScope;
  steps: PlanStepDef[];
  planner: string;
  model_name: string | null;
  follow_ups: string[];
  unmatched: boolean;
  notes: string[];
}

/** One option on a clarification, already resolved to real reporting periods. */
/**
 * One thing CreditProbe offers when it asks back.
 *
 * A period clarification carries two periods to compare; an intent or entity
 * clarification carries a question to ask instead. Both shapes travel in the
 * same field, so which of them is populated depends on the clarification's
 * `kind` — and the card that renders them branches on exactly that.
 */
export interface ClarificationOption {
  id: string;
  label: string;
  detail?: string;
  /** Set on a period clarification. */
  from_period?: string;
  to_period?: string;
  /** Set on an intent or entity clarification: ask this instead. */
  question?: string;
}

/** @deprecated The older name, kept for callers written before intent options. */
export type PeriodOption = ClarificationOption;

/**
 * A question CreditProbe asks back instead of guessing.
 *
 * Returned in place of an answer when the analysis spans time and the question
 * did not say which periods to compare.
 */
export interface Clarification {
  /** "period" | "intent" | "entity" | "dataset". */
  kind: string;
  question: string;
  detail: string;
  options: ClarificationOption[];
  because: string;
  allow_custom: boolean;
}

export interface ExecutedStep {
  index: number;
  analysis_id: string;
  title: string;
  rationale: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  period: string | null;
  status: string;
  certification: string;
  analysis_version: string;
  duration_ms: number;
  result: EngineResult | null;
  error: string | null;
  analysis_run_id: number | null;
  trace: TraceGraph | null;
  node_hashes: Record<string, string>;
  reused: boolean;
  role?: "primary" | "supporting";
}

export interface NarrativeMetric {
  label: string;
  value: number | string | null;
  unit: string;
  change: number | null;
  change_unit: string;
  direction: Direction;
  hint: string;
  step: number;
}

/**
 * One figure behind a finding.
 *
 * `direction` is which way is BAD for this measure, taken from the semantic
 * ontology's `higher_is_worse` rather than from the sign of the number. A
 * rising ECL and a rising cure rate are both increases and only one of them is
 * bad news, so the sign alone cannot colour a figure honestly. "neutral" where
 * the meaning is not governed — an uncoloured figure is a smaller failure than
 * one coloured the wrong way.
 */
export interface NarrativeEvidence {
  label: string;
  value: number | string | null;
  unit: string;
  direction?: Direction;
  /** The period the figure covers, where the result stamped one. */
  period?: string;
}

export interface NarrativeFinding {
  text: string;
  tone: "negative" | "warning" | "positive" | "neutral";
  evidence: NarrativeEvidence[];
  step: number;
}

export interface NarrativeDriver {
  name: string;
  value: number | null;
  unit: string;
  measure: string;
  detail?: string;
  step: number;
}

export interface Narrative {
  /** One sentence answering the question. Every figure came from the engine. */
  direct_answer?: string;
  /** Equals direct_answer; kept for callers written before the split. */
  summary: string;
  findings: NarrativeFinding[];
  /** CreditProbe's reading of the figures, as a paragraph. Never a calculation. */
  interpretation?: string;
  /** The same reading as discrete points. */
  interpretation_points?: string[];
  metrics: NarrativeMetric[];
  drivers: NarrativeDriver[];
  caveats: string[];
  /** Why more than one analysis was needed. Empty when only one ran. */
  why_multiple?: string;
  /** What the figures cover: population, window, measures. */
  scope?: string;
}

export interface Stage {
  id: string;
  label: string;
}

/**
 * The four states an AI provider can be in.
 *
 * `configured` is NOT health: it means a key exists and a call can be attempted.
 * Only `connected` means a real structured response has come back. The product
 * used to conflate the two, so a key that could not authenticate reported the
 * product's full intelligence while every question fell through to the offline
 * reader.
 */
export type AiState = "offline" | "configured" | "connected" | "degraded";

export interface AiCall {
  provider: string;
  model: string;
  purpose: string;
  at: string;
  latency_ms: number;
  ok: boolean;
  request_id: string;
  structured_valid: boolean;
  attempts: number;
  input_tokens: number;
  output_tokens: number;
  failure_category: string;
  failure_detail: string;
  failure_reason: string;
  fallback: string;
}

export interface AiHealth {
  provider: string;
  model: string;
  configured: boolean;
  state: AiState;
  label: string;
  live: boolean;
  counts: { total: number; succeeded: number; failed: number };
  median_latency_ms: number;
  consecutive_failures: number;
  last_success: AiCall | null;
  last_failure: AiCall | null;
  recent: AiCall[];
  detail: string;
}

export interface BuildInfo {
  version: string;
  sha: string;
  short_sha: string;
  image_sha: string;
  image_built_at: string;
  source_sha: string;
  source_branch: string;
  source_committed_at: string;
  source_dirty: boolean;
  stale: boolean;
  stale_detail: string;
  notes: string[];
}

export interface PlannerMode {
  /** "model" once a live response has come back; "degraded" when one cannot. */
  mode: "offline" | "model" | "degraded";
  configured: boolean;
  /** Whether a real structured response has actually been received. */
  live: boolean;
  /** "CreditProbe AI", "AI DEGRADED" or "LIMITED OFFLINE MODE". */
  label: string;
  provider: string;
  model_name: string | null;
  state: AiState;
  ai: AiHealth;
  build: BuildInfo;
  state_label: string;
  description: string;
  /** What is constrained when no model is answering. Empty when one is. */
  limitations: string[];
  stages: Stage[];
  capabilities: { id: string; label: string; computes: boolean }[];
  analysis_count: number;
  periods: string[];
  latest_period: string | null;
  dimensions: Record<string, number>;
  supported_modifications: { kind: string; label: string; example: string }[];
}

// ---------------------------------------------------------------- AI checks

export type Verdict = "PASS" | "PARTIAL" | "FAIL";
/**
 * A band grades the AI, so it is only awarded to a run that reached the model.
 * OFFLINE means no provider; UNVERIFIED means one was configured and every case
 * still fell through to the deterministic reader.
 */
export type Band =
  | "HIGH"
  | "GOOD"
  | "LIMITED"
  | "DEGRADED"
  | "OFFLINE"
  | "UNVERIFIED"
  | "";

export interface ReferenceAnswer {
  kind: string;
  values: Record<string, number | string>;
  ids: string[];
  rows: Record<string, unknown>[];
  summary: string;
  /** The SQL or catalogue read that produced it. Administrators only. */
  derivation: string;
  ordered: boolean;
  error: string;
}

export interface ValidationTurn {
  index: number;
  question: string;
  answer: string;
  interpretation: string;
  status: string;
  reading: Record<string, unknown>;
  plan: Record<string, unknown>;
  sql: string;
  rows: Record<string, unknown>[];
  /** Every row the analysis returned. `rows` above is a capped sample. */
  row_count?: number;
  columns: { name: string; label?: string; unit?: string }[];
  values: Record<string, unknown>;
  live: boolean;
  score: number;
  components: Record<string, number>;
  deductions: string[];
  /** Computed AFTER the answer, never before. */
  reference: ReferenceAnswer | null;
  expected: string[];
  error?: string;
}

export interface ValidationCase {
  benchmark_id: string;
  category: string;
  title: string;
  score: number;
  verdict: Verdict;
  latency_ms: number;
  used_fallback: boolean;
  components: Record<string, number>;
  turns: ValidationTurn[];
  deductions: string[];
  reference: ReferenceAnswer | Record<string, never>;
}

export interface ValidationRun {
  id: number | null;
  created_at?: string;
  score: number;
  band: Band;
  tone?: string;
  label: string;
  components: Record<string, number>;
  cases: ValidationCase[];
  provider: string;
  model: string;
  ai_state: AiState;
  build_sha: string;
  app_version: string;
  benchmark_version: string;
  data_version: string;
  duration_ms: number;
  case_count: number;
  passed: number;
  partial: number;
  failed: number;
  notes: string[];
  /** How many cases actually reached the live model. */
  live_cases?: number;
  stored?: boolean;
  stale?: boolean;
  stale_because?: string[];
  stale_label?: string;
}

export interface AiStatus {
  label: string;
  tone: string;
  ai: AiHealth;
  build: BuildInfo;
  latest: ValidationRun | null;
  benchmark_count: number;
  benchmark_turns: number;
  history_available: boolean;
  can_run: boolean;
  /** What a quick check would cost, stated before the button is pressed. */
  quick_check: {
    cases: number;
    turns: number;
    model_calls_if_live: number;
    provider_state: string;
    note: string;
  };
  /**
   * Whether THIS build has been proved against the live model.
   *
   * Distinct from `ai.state`: a configured key says a call COULD be made,
   * CONNECTED says one was, and this says a recorded verification actually
   * ran against this exact commit and this exact model configuration. It goes
   * stale the moment any of that changes — a badge that survives a
   * configuration change is worse than no badge, because somebody believes it.
   */
  live_verification: {
    live_verified: boolean;
    stale: boolean;
    reason: string;
    /** LIVE_VERIFIED | PASSED_NOT_STORED | FAILED | NOT_ELIGIBLE | DRY_RUN */
    status: string;
    verified_at: string;
    mode: string;
    calls: number;
    components: string[];
    /** What the stored report was made against... */
    verified_sha: string;
    verified_short_sha: string;
    verified_fingerprint: string;
    /** ...and what is running now, so STALE can show its own reason. */
    running_sha: string;
    running_short_sha: string;
    running_fingerprint: string;
    role_models: Record<string, string>;
    role_efforts: Record<string, string>;
    caveat: string;
    command: string;
    runnable_here: boolean;
    why: string;
  };
  /**
   * The frozen Intelligence Release, or the honest absence of one.
   *
   * Never runnable from the browser: the sealed holdout lives outside the
   * application and the product may not import it. What this carries is the
   * result of a build-time certification run.
   */
  certification: {
    status: "UNCERTIFIED" | "CERTIFIED" | "NOT_PASSED" | "STALE";
    release_id: string;
    created_at: string;
    certified_sha: string;
    running_sha: string;
    holdout_version: string;
    curriculum_version: string;
    ontology_version: string;
    ontology_fingerprint: string;
    cases: number;
    critical_cases: number;
    observed_precision_pct: number;
    supported_precision_pct: number;
    reportable: boolean;
    critical_failures: string[];
    corrections: { case: string; was: string; now: string; why: string }[];
    sentence: string;
    runnable_here: boolean;
    command: string;
    why_not_runnable: string;
  };
}

export interface InvestigationResponse {
  question: string;
  plan: PlanDef;
  intent: string;
  steps: ExecutedStep[];
  narrative: Narrative;
  /** Set when CreditProbe stopped to ask rather than answering. */
  clarification: Clarification | null;
  follow_ups: string[];
  notes: string[];
  unmatched: boolean;
  trace: TraceGraph;
  node_hashes: Record<string, string>;
  duration_ms: number;
  status: string;
  analysis_run_id: number | null;
  version: number;
  version_label: string;
  rejected: string[];
  mode: RunMode;
  stages: Stage[];
}

export interface Briefing {
  period: string | null;
  summary: AnalysisRunResponse | null;
  attention: AnalysisRunResponse | null;
  trend: AnalysisRunResponse | null;
  errors: string[];
}

export interface RecentInvestigation {
  analysis_run_id: number;
  question: string;
  intent: string;
  status: string;
  summary: string;
  step_count: number;
  created_at: string | null;
  duration_ms: number | null;
}

export interface StoredInvestigation {
  analysis_run_id: number;
  question: string;
  intent: string;
  status: string;
  created_at: string | null;
  duration_ms: number | null;
  context: Record<string, unknown>;
  version: number;
  version_id: number;
  label: string;
  graph: TraceGraph;
  node_hashes: Record<string, string>;
  plan: PlanDef;
  steps: ExecutedStep[];
  narrative: Narrative | Record<string, never>;
  follow_ups: string[];
  available_versions: { version: number; label: string; created_at: string | null }[];
  model_provider: string | null;
  model_name: string | null;
  stages: Stage[];
  mode: RunMode;
}

/** How one run was produced — the same shape wherever a run is returned. */
export interface RunMode {
  mode: string;
  planner?: string;
  configured?: boolean;
  label?: string;
  model_name: string | null;
  description: string;
  execution?: string;
  execution_label?: string;
  intent?: string;
  datasets?: string[];
  /** Set when the composer could not build a plan and the registered
   *  analyses answered instead. */
  fallback?: boolean;
  fallback_reason?: string;
}

export interface SupportedModification {
  kind: string;
  label: string;
  example: string;
}

export interface StepChange {
  index: number;
  analysis_id: string;
  title: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  was?: StepChange;
}

export interface ProposedChange {
  analysis_run_id: number;
  from_version: number;
  request: string;
  understood: boolean;
  applicable: boolean;
  operation: { kind: string; payload: Record<string, unknown>; description: string } | null;
  description: string;
  current_plan: PlanDef;
  proposed_plan: PlanDef;
  changed_steps: StepChange[];
  added_steps: StepChange[];
  removed_steps: StepChange[];
  unchanged_steps: StepChange[];
  affected_nodes: string[];
  downstream_nodes: string[];
  unaffected_nodes: string[];
  rejected: string[];
  supported: SupportedModification[];
}

export interface AppliedModification extends InvestigationResponse {
  from_version: number;
  request: string;
  change: ProposedChange;
  hash_diff: { added: string[]; removed: string[]; changed: string[]; unchanged: string[] };
  available_versions: { version: number; label: string; created_at: string | null }[];
}

export interface VersionsResponse {
  analysis_run_id: number;
  question: string;
  versions: { version: number; label: string; created_at: string | null }[];
  current: number;
  modifications: {
    id: number;
    request: string;
    interpretation: Record<string, unknown>;
    affected_nodes: string[];
    status: string;
    created_at: string | null;
  }[];
  supported: SupportedModification[];
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * A failed API call.
 *
 * `message` is always safe and useful to show a user: either the backend's own
 * explanation, or a plain-English description of why we could not reach it.
 */
/**
 * What the two download buttons may offer for one analysis run.
 *
 * The labels come from the backend so the button in the interface and the file
 * the endpoint produces can never describe themselves differently.
 */
export interface ExportOffer {
  allowed: boolean;
  reason: string;
  label: string;
  href: string;
  /** Full pack only: whether this download carries row-level data. */
  row_level?: boolean;
}

export interface ExportAvailability {
  run_id: number;
  results: ExportOffer;
  calculation_pack: ExportOffer;
}

/** One row of the export audit log, for the Analysis audit view. */
export interface ExportRecord {
  id: number;
  kind: string;
  kind_label: string;
  run_id: number | null;
  trace_version: number | null;
  user_name: string;
  role: string;
  status: string;
  authorization: string;
  reason: string;
  filename: string;
  content_hash: string;
  size_bytes: number | null;
  row_count: number | null;
  duration_ms: number | null;
  datasets: string[];
  redactions: string[];
  at: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(
    message: string,
    status = 0,
    code = "network_error",
    detail: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  get isOffline(): boolean {
    return this.status === 0;
  }

  /** True when the caller's role is not permitted to do this. */
  get isForbidden(): boolean {
    return this.status === 403;
  }
}


export interface RelationshipNode {
  name: string;
  domain: string;
  business_name?: string;
  grain: string;
  period_field?: string;
  field_count: number;
  is_synthetic: boolean;
  authoritative_for?: string[];
  in_catalogue: boolean;
  degree: number;
}

export interface RelationshipEdge {
  id: number;
  name: string;
  from_dataset: string;
  from_field: string;
  to_dataset: string;
  to_field: string;
  cardinality: string;
  kind: string;
  description: string;
  /** What the join means in credit terms, not what it does mechanically. */
  semantic: string;
  lifecycle: string;
  lifecycle_label: string;
  version: number;
  is_preferred: boolean;
  confidence: number;
  join_policy: string;
  temporal_rule: string;
  temporal_label: string;
  match_rate: number | null;
  orphan_rate: number | null;
  duplicate_rate: number | null;
  validated_at: string;
  validation: Record<string, unknown>;
  /** Only an ACTIVE relationship may be joined on by the runtime. */
  is_runnable: boolean;
}

export interface RelationshipProposal {
  from_dataset: string;
  from_field: string;
  to_dataset: string;
  to_field: string;
  cardinality: string;
  kind: string;
  match_rate: number;
  orphan_rate: number;
  duplicate_rate: number;
  left_rows: number;
  right_rows: number;
  why: string;
  safe_to_join: boolean;
  /** Filled in by the steward before accepting, not by the assistant. */
  semantic?: string;
}

export interface RelationshipProposals {
  dataset: string;
  candidates: RelationshipProposal[];
  minimum_coverage: number;
  note: string;
}

export interface RelationshipThresholds {
  min_match_rate: number;
  max_duplicate_rate: number;
  min_confidence: number;
}

export interface RelationshipVersionEntry {
  version: number;
  definition: Record<string, unknown>;
  change_note: string;
  changed_by: number | null;
  created_at: string;
}

export interface RelationshipDetail {
  relationship: RelationshipEdge;
  versions: RelationshipVersionEntry[];
  thresholds: RelationshipThresholds;
}

export interface RelationshipValidation {
  ok: boolean;
  findings: string[];
  match_rate?: number;
  orphan_rate?: number;
  duplicate_rate?: number;
  left_rows?: number;
  right_rows?: number;
  left_period?: string | null;
  right_period?: string | null;
}

export interface RelationshipMap {
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  connected: number;
  unconnected: string[];
  active_count: number;
  lifecycles: { id: string; label: string }[];
  thresholds: RelationshipThresholds;
}

// ---------------------------------------------------------------------------
// Data Inbox
// ---------------------------------------------------------------------------

export interface FieldDrift {
  field: string;
  kind: string;
  severity: "blocking" | "material" | "notable" | "informational";
  detail: string;
  before: unknown;
  after: unknown;
  because: string;
}

export interface DriftReport {
  dataset: string;
  findings: FieldDrift[];
  first_load: boolean;
  previous_row_count: number;
  current_row_count: number;
  blocking_count: number;
  material_count: number;
  clean: boolean;
  summary: string;
}

export interface InboxItem {
  id: number;
  filename: string;
  file_format: string;
  size_bytes: number;
  dataset: string;
  match_confidence: number;
  match_reason: string;
  status: string;
  status_label: string;
  decision: string;
  decision_reason: string;
  drift: DriftReport | Record<string, never>;
  row_count: number;
  column_count: number;
  received_at: string;
  resolved_at: string;
  resolved_by: number | null;
  resolution_note: string;
  profile?: Record<string, unknown>;
}

export interface InboxListing {
  items: InboxItem[];
  counts: Record<string, number>;
  statuses: { id: string; label: string }[];
  auto_publish_confidence: number;
}

// ---------------------------------------------------------------------------
// Analysis Studio
// ---------------------------------------------------------------------------

export interface StudioTestCase {
  id: string;
  name: string;
  purpose: string;
  data: Record<string, unknown>[];
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
  passed: boolean | null;
  note: string;
}

export interface StudioMethodVersion {
  version: string;
  lifecycle: string;
  created_at: string;
  change_note: string;
  certified_at: string;
  certified_by: string;
}

export interface StudioMethodBrief {
  id: string;
  name: string;
  category: string;
  definition: string;
  lifecycle: string;
  lifecycle_label: string;
  is_certified: boolean;
  is_runnable: boolean;
  version: string;
  aliases: string[];
  owner: string;
  source: string;
  test_count: number;
  tests_passing: number;
  tests_failing: number;
}

export interface StudioConcept {
  concept: string;
  label: string;
  dataset: string;
  field: string;
  definition: string;
  unit: string;
  reason: string;
}

export interface StudioRelationshipNeed {
  relationship_id: number;
  name: string;
  version: number;
  left: string;
  right: string;
  cardinality: string;
  join_policy: string;
  temporal_rule: string;
}

export interface StudioPeriodAlignment {
  opening_period?: string;
  closing_period?: string;
  as_of?: { dataset: string; rule: string }[];
  description?: string;
}

export interface StudioMethod extends StudioMethodBrief {
  purpose: string;
  methodology: string;
  when_to_use: string;
  when_not_to_use: string;
  required_grain: string;
  required_history: string;
  required_domains: string[];
  required_fields: string[];
  applicable_segments: string[];
  weighting_options: string[];
  output_type: string;
  interpretation: string;
  limitations: string;
  /* A multi-dataset method carries what it needs before it can be run again:
   * the concepts it measures rather than the columns one dataset happens to
   * call them, the governed joins it walked, and how periods were aligned. */
  required_concepts: StudioConcept[];
  required_relationships: StudioRelationshipNeed[];
  period_alignment: StudioPeriodAlignment;
  plan: { operations?: Record<string, unknown>[]; meta?: Record<string, unknown> } | null;
  engine_analysis: string;
  test_cases: StudioTestCase[];
  versions: StudioMethodVersion[];
  created_at: string;
  updated_at: string;
  certified_at: string;
  certified_by: string;
  forked_from: string;
  fingerprint: string;
  can_certify: boolean;
  certification_gaps: string[];
}

export interface StudioCategoryCount {
  category: string;
  count: number;
  certified: number;
  runnable: number;
}

export interface StudioStats {
  total: number;
  by_lifecycle: Record<string, number>;
  certified: number;
  runnable: number;
  aliases: number;
  categories: number;
  certification_audit: {
    certified: string[];
    certified_count: number;
    downgraded: Record<string, string>;
    downgraded_count: number;
  };
}

export interface StudioLibrary {
  methods: StudioMethodBrief[];
  total_matched: number;
  categories: StudioCategoryCount[];
  lifecycles: { id: string; label: string }[];
  all_categories: string[];
  stats: StudioStats;
}

export interface StudioClarification {
  id: string;
  question: string;
  because: string;
  options: { id: string; label: string; detail?: string }[];
  default: string;
}

export interface StudioReading {
  understood: boolean;
  summary: string;
  kind: string;
  horizon_periods: number;
  detected: Record<string, unknown>;
  clarifications: StudioClarification[];
  note: string;
}

export interface StudioValidationPack {
  method_id: string;
  method_name: string;
  cases: StudioTestCase[];
  dataset: Record<string, unknown>[];
  opening_period: string;
  closing_period: string;
  passed: number;
  failed: number;
  complete: boolean;
  all_passed: boolean;
  note: string;
  sql: string;
  parameters: unknown[];
  actual: Record<string, unknown>;
  ran_at: string;
}

export interface StudioBuildResult {
  method: StudioMethod;
  validation: StudioValidationPack;
  saved: boolean;
  persisted: boolean;
  storage_note: string;
}

// ---------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------

interface RequestOptions extends Omit<RequestInit, "signal"> {
  timeoutMs?: number;
  /** Set for multipart uploads, where the browser must choose the boundary. */
  rawBody?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers, rawBody, ...init } = options;

  // Without a timeout a stopped backend leaves the UI spinning indefinitely,
  // which reads as "broken" rather than "not running".
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
      ...init,
      signal: controller.signal,
      // The session is an HTTP-only cookie, so it only travels if we ask for it.
      // Without this every request is anonymous and the product silently falls
      // back to the header-based demonstration role.
      credentials: "include",
      headers: {
        ...(rawBody ? {} : { "Content-Type": "application/json" }),
        "X-IPM-Role": activeRole,
        ...headers,
      },
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted
        ? `The backend did not respond within ${timeoutMs / 1000} seconds.`
        : `Cannot reach the CreditProbe backend at ${API_DISPLAY_URL}. Is it running?`,
      0,
      aborted ? "timeout" : "network_error",
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed with status ${response.status}.`;
    let detail: Record<string, unknown> = {};
    try {
      const body = await response.json();
      // FastAPI wraps our structured errors in `detail`; ours are flat.
      const payload = body.detail && typeof body.detail === "object" ? body.detail : body;
      code = payload.error ?? code;
      message = payload.message ?? message;
      detail = payload;
    } catch {
      /* keep the fallback message */
    }
    throw new ApiError(message, response.status, code, detail);
  }

  return (await response.json()) as T;
}


/**
 * A file the backend generates, fetched as bytes rather than JSON.
 *
 * Two things a plain `<a download>` cannot do, and both of them matter here:
 * it cannot send the role header or the session cookie the export endpoints
 * authorise against, and it cannot show the user a refusal — a 403 arriving
 * through a link is a browser page, not a message in the product. So the
 * download is a `fetch`, and a failure comes back as an ApiError with the
 * backend's own explanation in it.
 *
 * The filename comes from Content-Disposition, which is where the server put
 * the sanitised name. Guessing one here would produce a second opinion about
 * what the file is called.
 */
export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

const FILENAME = /filename="([^"]+)"/;

async function download(path: string, fallback: string,
                        timeoutMs = 180_000): Promise<DownloadedFile> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
      signal: controller.signal,
      credentials: "include",
      headers: { "X-IPM-Role": activeRole },
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted
        ? "The workbook took too long to generate and the request was stopped."
        : `Cannot reach the CreditProbe backend at ${API_DISPLAY_URL}. Is it running?`,
      0,
      aborted ? "timeout" : "network_error",
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `The workbook could not be generated (status ${response.status}).`;
    let detail: Record<string, unknown> = {};
    try {
      const body = await response.json();
      const payload = body.detail && typeof body.detail === "object" ? body.detail : body;
      code = payload.error ?? code;
      message = payload.message ?? message;
      detail = payload;
    } catch {
      /* a non-JSON error body: keep the fallback message */
    }
    throw new ApiError(message, response.status, code, detail);
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const named = FILENAME.exec(disposition);
  return { blob: await response.blob(), filename: named?.[1] ?? fallback };
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export interface ExecuteOptions {
  params?: Record<string, unknown>;
  period?: string | null;
  filters?: Record<string, unknown>;
  persist?: boolean;
}


// ======================================================== workspace and review

/** A saved investigation: a question with a name, an owner and versions. */
export interface SavedInvestigationSummary {
  id: number;
  title: string;
  question: string;
  status: string;
  project_id: number | null;
  owner_id: number | null;
  version: number;
  answer: string;
  change_narrative: string;
  from_period: string | null;
  to_period: string | null;
  analysis_run_id: number | null;
  updated_at: string | null;
}

export interface InvestigationVersionRow {
  version: number;
  analysis_run_id: number | null;
  from_period: string | null;
  to_period: string | null;
  change_narrative: string;
  created_at: string | null;
}

/** One headline figure, before and after a refresh. */
export interface MetricChangeRow {
  label: string;
  unit: string;
  before: number | null;
  after: number | null;
  change: number | null;
  direction: Direction;
  moved: boolean;
}

export interface SavedInvestigation extends SavedInvestigationSummary {
  scope: PlanScope | Record<string, never>;
  versions: InvestigationVersionRow[];
  narrative: Narrative | Record<string, never>;
  changes: MetricChangeRow[];
  created_at: string | null;
}

export interface WorkflowEventRow {
  from_state: string | null;
  to_state: string;
  to_state_label: string;
  actor_id: number | null;
  comment: string;
  created_at: string | null;
}

/**
 * What is being ASKED FOR, as distinct from where the asking has got to. §43.
 *
 * The distinction matters: "approve" is the request and "Approved" is the
 * outcome, and a list that conflates them cannot tell an approval nobody has
 * looked at from one that has been granted.
 */
export type WorkflowAction =
  | "review"
  | "comment"
  | "approve"
  | "request_changes"
  | "fyi"
  | "sign_off"
  | "assign_action";

export type WorkflowPriority = "low" | "normal" | "high" | "urgent";

export interface WorkflowItemRow {
  id: number;
  object_type: string;
  object_type_label?: string;
  object_id: string;
  /** The object as it was when it was sent, where the object is versioned. */
  object_version?: string | null;
  title: string;
  state: string;
  state_label: string;
  action?: WorkflowAction;
  action_label?: string;
  /** What the sender said when they sent it. */
  message?: string;
  priority?: WorkflowPriority;
  requested_by: number | null;
  assigned_to: number | null;
  due_at: string | null;
  updated_at: string | null;
  /** How many messages are on the item's thread. */
  messages?: number;
}

/** One person or team a workflow item was sent to. */
export interface WorkflowRecipientRow {
  id: number;
  user_id: number | null;
  team_id: number | null;
  /** When this recipient first opened it — §44's OPENED, as an observation. */
  opened_at: string | null;
}

/** One message in the conversation about a workflow item. §45. */
export interface WorkflowMessageRow {
  id: number;
  parent_id: number | null;
  body: string;
  author_id: number | null;
  resolved: boolean;
  mentions: { user_id?: number; team_id?: number }[];
  attachments: { type: string; id: string; label?: string }[];
  created_at: string | null;
}

export interface WorkflowDetail extends WorkflowItemRow {
  created_at: string | null;
  recipients: WorkflowRecipientRow[];
  thread: WorkflowMessageRow[];
  events: WorkflowEventRow[];
  next_states: string[];
  next_state_labels: Record<string, string>;
}

export interface WorkflowInbox {
  /** §46's five views. */
  assigned_to_me: WorkflowItemRow[];
  sent_by_me: WorkflowItemRow[];
  mentions: WorkflowItemRow[];
  due_soon: WorkflowItemRow[];
  completed: WorkflowItemRow[];
  /** The names the first Workflow screen used, kept so it still works. */
  my_work: WorkflowItemRow[];
  states: Record<string, string>;
  actions: Record<string, string>;
  reviewable: Record<string, string>;
}

export interface CommentRow {
  id: number;
  object_type: string;
  object_id: string;
  parent_id: number | null;
  body: string;
  resolved: boolean;
  author_id: number | null;
  created_at: string | null;
}

export interface NotificationRow {
  id: number;
  kind: string;
  title: string;
  body: string;
  object_type: string;
  object_id: string;
  actor_id: number | null;
  read: boolean;
  created_at: string | null;
}

// ========================================================== the control plane

/** One governed purpose, and the dataset currently answering it. */
export interface PurposeResolution {
  purpose: string;
  description: string;
  resolved: boolean;
  dataset: string | null;
  origin: string | null;
  is_demo: boolean;
  family: string;
  alternatives: string[];
  message: string | null;
}

export interface ControlPlane {
  purposes: PurposeResolution[];
  using_demo_data: boolean;
  unresolved: string[];
}

export interface DatasetFamily {
  family: string;
  datasets: {
    name: string;
    business_name: string;
    origin: string;
    lifecycle: string;
    authoritative_for: string[];
  }[];
  has_client_data: boolean;
}

export interface DependantRow {
  kind: string;
  name: string;
  detail: string;
}

export interface UsedBy {
  dataset: string;
  dependants: DependantRow[];
  blocking: DependantRow[];
  safe_to_archive: boolean;
}

/** One column, and the governed field CreditProbe thinks it supplies. */
export interface HarmonisationProposal {
  source_column: string;
  source_type: string;
  governed_field: string | null;
  confidence: number;
  confident: boolean;
  reasons: string[];
  concerns: string[];
  alternatives: string[];
  basis: string;
}

export interface Harmonisation {
  dataset: string;
  proposals: HarmonisationProposal[];
  counts?: {
    columns: number;
    confident: number;
    needs_a_decision: number;
    unmatched: number;
  };
  message: string;
  rule?: string;
}

/** An answer from a metadata assistant. Never a portfolio figure. */
export interface AssistantAnswer {
  text: string;
  references: { kind: string; name: string; dataset?: string }[];
  source: "lookup" | "model";
  unanswered_reason: string;
  rule: string;
}

// ============================================== the hierarchy: Analysis < Investigation < Project

/**
 * Project statuses, as the backend governs them.
 *
 * `in_review` is deliberately never offered in `available_statuses`: it means a
 * review is genuinely outstanding, so it is reached by sending the project for
 * review and left when the reviewer decides.
 */
export type ProjectStatus = "draft" | "active" | "in_review" | "completed" | "archived";

export interface ProjectRow {
  id: number;
  name: string;
  description: string;
  status: ProjectStatus;
  status_label: string;
  instructions: string;
  team_id: number | null;
  created_by: number | null;
  default_context: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  available_statuses: { status: ProjectStatus; label: string }[];
  review_open: boolean;
  review_item_id: number | null;
  investigation_count: number;
  analysis_count: number;
  history: ProjectStatusEventRow[];
}

export interface ProjectStatusEventRow {
  from_status: string | null;
  to_status: string;
  to_label: string;
  actor_id: number | null;
  note: string;
  created_at: string | null;
}

export interface ProjectContents {
  project: ProjectRow;
  investigations: {
    id: number;
    title: string;
    question: string;
    status: string;
    message_count: number;
    last_message_at: string | null;
    updated_at: string | null;
  }[];
  analyses: {
    id: number;
    title: string;
    analysis_id: string;
    certification: string;
    investigation_id: number | null;
    period: Record<string, unknown>;
    created_at: string | null;
  }[];
}

/** One turn of a conversation. An assistant turn carries the whole answer. */
export interface ThreadMessage {
  id: number;
  sequence: number;
  role: "user" | "assistant" | "system";
  content: string;
  payload: Partial<InvestigationResponse> & Record<string, unknown>;
  analysis_run_id: number | null;
  created_by: number | null;
  created_at: string | null;
}

/** An Investigation: a conversation, and what it has settled. */
export interface Thread {
  id: number;
  title: string;
  question: string;
  status: string;
  project_id: number | null;
  owner_id: number | null;
  /**
   * Whether a PROJECT thread also appears in the global Investigations list.
   *
   * §4: work done inside a project belongs to that project until somebody
   * deliberately publishes it. Meaningless for a standalone thread, which is
   * already global.
   */
  published_globally: boolean;
  /** Domain, period and filters the thread has agreed. Asked once, not again. */
  context: Record<string, unknown>;
  message_count: number;
  last_message_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  messages: ThreadMessage[];
}

export interface ThreadSummary {
  id: number;
  title: string;
  question: string;
  status: string;
  project_id: number | null;
  owner_id: number | null;
  /** A project thread that has been published to the global list. §4. */
  published_globally: boolean;
  context: Record<string, unknown>;
  message_count: number;
  last_answer: string;
  last_message_at: string | null;
  updated_at: string | null;
}

/** What comes back from asking inside a thread. */
export interface ThreadTurn {
  status: string;
  run: InvestigationResponse | null;
  thread: Thread;
}

/** A kept calculation. Records a run that already happened; nothing re-runs. */
export interface SavedAnalysis {
  id: number;
  title: string;
  analysis_id: string;
  analysis_version: string;
  certification: string;
  analysis_run_id: number | null;
  investigation_id: number | null;
  project_id: number | null;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  period: Record<string, unknown>;
  result: Record<string, unknown>;
  data_versions: Record<string, unknown>;
  note: string;
  owner_id: number | null;
  created_at: string | null;
}

// ==================================================== early warning: the Forward Risk Signal

/**
 * The signal is a PROTOTYPE. Every response carries `notice`, and the UI shows
 * it — the words "validated", "production model" and "regulatory model" are
 * derived from a validation record on the backend and are unreachable without
 * one.
 */
export interface EarlyWarningTarget {
  id: string;
  label: string;
  definition: string;
  from_stage: number;
  to_stage: number;
  horizon: string;
  action: string;
  eligible_note: string;
}

export interface FactorFamilyDef {
  id: string;
  label: string;
  definition: string;
  factors?: FactorDef[];
}

export interface FactorDef {
  id: string;
  family: string;
  family_label: string;
  label: string;
  definition: string;
  fields: string[];
  direction: "up-is-worse" | "up-is-better";
  unit: string;
  derived: boolean;
  notes: string;
}

export interface FactorContribution {
  factor_id: string;
  label: string;
  family: string;
  family_label: string;
  value: number;
  unit: string;
  standardised: number;
  contribution: number;
}

export interface ScoredFacility {
  account_id: string;
  customer_id: string;
  borrower_name: string;
  sector: string;
  segment: string;
  ead: number;
  stage: number;
  score: number;
  probability_pct: number;
  band: string;
  intercept: number;
  contributions: FactorContribution[];
  family_contributions: { family: string; label: string; contribution: number }[];
}

export interface EarlyWarningScores {
  period: string;
  target: EarlyWarningTarget;
  facilities: number;
  total_ead?: number;
  scored: ScoredFacility[];
  bands: { band: string; facilities: number; ead: number }[];
  families?: FactorFamilyDef[];
  factors?: FactorDef[];
  notice: string;
  message?: string;
}

export interface EarlyWarningOverview {
  capability: string;
  notice: string;
  targets: (EarlyWarningTarget & {
    versions: number;
    active: EarlyWarningModel | null;
  })[];
  families: FactorFamilyDef[];
  factors: FactorDef[];
  methodology: string;
}

export interface EarlyWarningMethodology {
  capability: string;
  notice: string;
  targets: EarlyWarningTarget[];
  families: FactorFamilyDef[];
  bands: { band: string; floor_pct: number }[];
  form: string;
  document: string;
}

export interface SignalWeight {
  factor_id: string;
  label: string;
  family: string;
  family_label: string;
  weight: number;
  mean: number;
  std: number;
  expected_direction: string;
  agrees_with_expectation: boolean;
}

export interface SignalSpecification {
  target_id: string;
  intercept: number;
  weights: SignalWeight[];
  fitted_periods: string[];
  fitted_rows: number;
  fitted_events: number;
  base_rate_pct: number;
  ridge: number;
  notes: string;
  form: string;
}

export interface BacktestResult {
  target_id: string;
  fitted_periods: string[];
  tested_periods: string[];
  facilities: number;
  events: number;
  base_rate_pct: number;
  auc: number | null;
  ks: number | null;
  top_decile_capture_pct: number;
  deciles: {
    decile: number;
    facilities: number;
    events: number;
    rate_pct: number;
    lift: number;
    cumulative_capture_pct: number;
  }[];
  calibration: {
    band: string;
    facilities: number;
    events: number;
    predicted_pct: number;
    observed_pct: number;
    gap_pp: number;
  }[];
  by_period: {
    period: string;
    facilities: number;
    events: number;
    auc: number | null;
    ks: number | null;
    top_decile_capture_pct: number;
  }[];
  verdict: string;
  is_validation: false;
}

export interface EarlyWarningModel {
  id: number;
  target: string;
  target_label: string;
  name: string;
  version: number;
  lifecycle: string;
  lifecycle_stored: string;
  lifecycle_label: string;
  display_name: string;
  notice: string;
  is_active: boolean;
  change_note: string;
  specification: SignalSpecification & { backtest?: BacktestResult };
  validation: Record<string, unknown>;
  created_by: number | null;
  created_at: string | null;
}

export interface FitResponse {
  specification: SignalSpecification;
  backtest: BacktestResult;
  saved: EarlyWarningModel | null;
  notice: string;
}

export interface ImpactAnalysis {
  period: string;
  target: EarlyWarningTarget;
  from_model: { id: number; name: string; version: number };
  to_model: { id: number; name: string; version: number };
  facilities_compared: number;
  unchanged: number;
  moved_to_worse_band: number;
  moved_to_better_band: number;
  ead_to_worse_band: number;
  ead_to_better_band: number;
  biggest_increases: BandMove[];
  biggest_decreases: BandMove[];
  weight_changes: {
    factor_id: string;
    label: string;
    family: string;
    before: number;
    after: number;
    change: number;
  }[];
  summary: string;
}

export interface BandMove {
  account_id: string;
  borrower_name: string;
  sector: string;
  ead: number;
  from_band: string;
  to_band: string;
  from_pct: number;
  to_pct: number;
}

// ============================================================== playbooks

/** A standing instruction the platform carries out. */
export interface Playbook {
  id: number;
  slug: string;
  name: string;
  description: string;
  trigger: string;
  trigger_label: string;
  schedule: string;
  scope: Record<string, unknown>;
  analyses: { analysis_id: string; params?: Record<string, unknown> }[];
  conditions: PlaybookCondition[];
  actions: { create_investigation?: boolean; notify?: number[] };
  status: string;
  origin: string;
  owner: string;
  last_run_at: string | null;
  next_run_hint: string;
  run_count: number;
  last_run: PlaybookRun | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PlaybookCondition {
  metric: string;
  label: string;
  operator: string;
  threshold: number;
  unit: string;
  severity: string;
}

/** One condition, tested against a figure the engine returned. */
export interface PlaybookEvaluation {
  metric: string;
  label: string;
  operator: string;
  operator_label: string;
  threshold: number;
  severity: string;
  value: number | null;
  unit: string;
  met: boolean;
  /** False when no analysis produced the metric — different from "not met". */
  testable: boolean;
  analysis_id: string;
  sentence: string;
}

export interface PlaybookRun {
  id: number | null;
  playbook_id: number;
  status: string;
  period: Record<string, unknown>;
  results: {
    analysis_id: string;
    analysis_run_id: number | null;
    values: Record<string, unknown>;
    units: Record<string, string>;
    row_count: number;
  }[];
  evaluations: PlaybookEvaluation[];
  actions_taken: { action: string; investigation_id?: number; detail?: string }[];
  alerted: boolean;
  summary: string;
  error: string;
  investigation_id: number | null;
}

export interface PlaybookLibrary {
  playbooks: Playbook[];
  triggers: Record<string, string>;
  operators: Record<string, string>;
  severities: string[];
  scope_dimensions: string[];
  statuses: string[];
}

// =================================================== the dataset viewer

export interface DatasetTree {
  domains: {
    domain: string;
    families: {
      family: string;
      datasets: {
        name: string;
        business_name: string;
        purpose: string;
        grain: string;
        origin: string;
        is_synthetic: boolean;
        authoritative_for: string[];
        field_count: number;
        periods: string[];
        period_count: number;
        readable: boolean;
      }[];
    }[];
  }[];
}

/** The part of a grid's state that belongs to the reader rather than the query. */
export interface GridPreferences {
  widths: Record<string, number>;
  hidden: string[];
  frozen: number;
  dense: boolean;
}

export interface DatasetField {
  name: string;
  business_name: string;
  definition: string;
  data_type: string;
  unit: string | null;
  sensitivity: string;
  nullable: boolean;
}

/** What is actually in a column, as opposed to what the dictionary says. */
export interface ColumnProfile {
  dataset: string;
  field: string;
  business_name: string;
  definition: string;
  data_type: string;
  unit: string | null;
  sensitivity: string;
  allowed_values: string[];
  period: string | null;
  rows: number;
  missing: number;
  missing_pct: number;
  distinct: number;
  statistics: {
    min: number;
    p25: number;
    median: number;
    p75: number;
    max: number;
    mean: number;
    sum: number;
  } | null;
  top_values: { value: string; count: number; share_pct: number }[];
}

/** Which columns each published period actually carries. */
export interface SchemaHistory {
  dataset: string;
  business_name: string;
  periods: string[];
  fields: string[];
  presence: Record<string, { rows: number; fields: Record<string, boolean> }>;
  changes: {
    field: string;
    period: string;
    change: "appeared" | "disappeared";
    from_period: string;
  }[];
  stable: boolean;
}

/** What narrows a dataset view: the same shape for reading it and exporting it. */
export interface DatasetQuery {
  period?: string;
  sort?: string;
  descending?: boolean;
  fields?: string[];
  /** Substring match across the shown columns. */
  search?: string;
  /** `field:operator:value`, e.g. `ifrs9_stage:eq:2`. */
  filters?: string[];
}

function datasetQuery(opts: DatasetQuery): URLSearchParams {
  const query = new URLSearchParams();
  if (opts.period) query.set("period", opts.period);
  if (opts.sort) query.set("sort", opts.sort);
  if (opts.descending) query.set("descending", "true");
  if (opts.search) query.set("q", opts.search);
  if (opts.fields?.length) query.set("fields", opts.fields.join(","));
  // Repeated rather than joined: a filter value may itself contain a comma.
  for (const filter of opts.filters ?? []) query.append("filter", filter);
  return query;
}

export interface DatasetPage {
  dataset: string;
  business_name: string;
  domain: string;
  family: string;
  origin: string;
  is_synthetic: boolean;
  grain: string;
  period: string | null;
  periods: string[];
  /** Rows matching the current filters and search. */
  total_rows: number;
  /** Rows in the period before the viewer narrowed them. */
  total_in_period: number;
  filtered: boolean;
  offset: number;
  limit: number;
  returned: number;
  fields: DatasetField[];
  /** Every governed field, including ones not currently shown. */
  all_fields: string[];
  rows: Record<string, string | number | boolean | null>[];
}

// ================================================================== lenses

/** One thing on a Lens: a certified analysis, drawn a particular way. */
export interface LensPanel {
  analysis_id: string;
  title: string;
  visual: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  note: string;
}

export interface Lens {
  id: number;
  slug: string;
  name: string;
  description: string;
  audience: string;
  panels: LensPanel[];
  status: string;
  version: number;
  origin: string;
  project_id: number | null;
  revisions: {
    version: number;
    request: string;
    change_summary: string;
    panel_count: number;
    created_at: string | null;
  }[];
  created_at: string | null;
  updated_at: string | null;
}

export interface RenderedPanel extends LensPanel {
  status: string;
  error: string | null;
  certification?: string;
  analysis_version?: string;
  analysis_run_id?: number | null;
  duration_ms?: number;
  result: EngineResult | null;
}

export interface RenderedLens {
  lens: Lens;
  period: string | null;
  panels: RenderedPanel[];
  failed: number;
  note: string;
}

/** What the platform proposes to do about a request, including what it will not. */
export interface LensProposal {
  panels: LensPanel[];
  change_summary: string;
  refusals: string[];
  matched: string[];
}

// ============================================================ authentication

export interface SignedInUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  display_name: string;
  /** What the Cockpit greets them by. A first name, or the username. */
  greeting_name: string;
  email: string;
  role: Role;
  team: string;
  is_active: boolean;
}

export interface UserRecord extends SignedInUser {
  last_login_at: string | null;
  created_at: string | null;
}

/** One person work can be sent to. §47. */
export interface DirectoryPerson {
  id: number;
  username: string;
  name: string;
  role: Role;
  role_label: string;
  team: string;
}

/** One team work can be sent to. */
export interface DirectoryTeam {
  id: number;
  name: string;
  description: string;
  members: number;
}

export interface Directory {
  people: DirectoryPerson[];
  teams: DirectoryTeam[];
}

export interface RoleDescription {
  role: Role;
  label: string;
  /** One sentence on what this role may do, shown when assigning it. */
  can: string;
}

export const api = {
  // ---- authentication ----
  /**
   * Who is signed in, and whether this backend insists on somebody being.
   *
   * `login_required` comes from the backend rather than a build-time flag on
   * the interface. Two places holding the same setting is two places for it to
   * disagree, and the way they disagree is a login page that never appears in
   * front of a backend refusing every request.
   */
  me: () =>
    request<{
      user: SignedInUser | null;
      authenticated: boolean;
      login_required: boolean;
    }>("/auth/me"),
  signIn: (username: string, password: string) =>
    request<{ user: SignedInUser }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  signOut: () => request<{ signed_out: boolean }>("/auth/logout", { method: "POST" }),

  /**
   * Who work can be sent to. §47's one recipient picker.
   *
   * Deliberately not the admin user listing: choosing a reviewer needs a name
   * and a team, not an email address or a last-login time.
   */
  directory: () => request<Directory>("/users/directory"),

  // ---- user administration (administrators only) ----
  users: () =>
    request<{ users: UserRecord[]; roles: RoleDescription[] }>("/users"),
  createUser: (payload: {
    username: string;
    password: string;
    firstName?: string;
    lastName?: string;
    email?: string;
    role?: Role;
    team?: string;
  }) =>
    request<UserRecord>("/users", {
      method: "POST",
      body: JSON.stringify({
        username: payload.username,
        password: payload.password,
        first_name: payload.firstName ?? "",
        last_name: payload.lastName ?? "",
        email: payload.email ?? "",
        role: payload.role ?? "ANALYST",
        team: payload.team ?? "",
      }),
    }),
  updateUser: (
    id: number,
    payload: {
      firstName?: string;
      lastName?: string;
      email?: string;
      role?: Role;
      team?: string;
      isActive?: boolean;
    },
  ) =>
    request<UserRecord>(`/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        first_name: payload.firstName ?? null,
        last_name: payload.lastName ?? null,
        email: payload.email ?? null,
        role: payload.role ?? null,
        team: payload.team ?? null,
        is_active: payload.isActive ?? null,
      }),
    }),
  setUserPassword: (id: number, password: string) =>
    request<{ user_id: number; password_set: boolean }>(`/users/${id}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  // ---- system ----
  health: (timeoutMs?: number) =>
    request<HealthResponse>("/health", { timeoutMs: timeoutMs ?? 8_000 }),
  catalog: () => request<CatalogResponse>("/catalog"),

  // ---- engine ----
  analyses: (opts: { category?: string; certifiedOnly?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.category) q.set("category", opts.category);
    if (opts.certifiedOnly) q.set("certified_only", "true");
    const qs = q.toString();
    return request<AnalysisLibraryResponse>(`/engine/analyses${qs ? `?${qs}` : ""}`);
  },
  analysis: (id: string) => request<AnalysisDetail>(`/engine/analyses/${id}`),
  execute: (id: string, options: ExecuteOptions = {}) =>
    request<AnalysisRunResponse>(`/engine/analyses/${id}/execute`, {
      method: "POST",
      body: JSON.stringify({
        params: options.params ?? {},
        period: options.period ?? null,
        filters: options.filters ?? {},
        persist: options.persist ?? true,
      }),
      // Migration analyses read two full periods; give them room.
      timeoutMs: 45_000,
    }),
  periods: (dataset = "portfolio_facility") =>
    request<PeriodsResponse>(`/engine/periods?dataset=${encodeURIComponent(dataset)}`),
  dimensions: (dataset = "portfolio_facility", period?: string) => {
    const q = new URLSearchParams({ dataset });
    if (period) q.set("period", period);
    return request<DimensionsResponse>(`/engine/dimensions?${q}`);
  },

  // ---- trace ----
  trace: (runId: number, version?: number) =>
    request<StoredTrace>(`/trace/${runId}${version ? `?version=${version}` : ""}`),

  // ---- AI status and the intelligence check ----
  aiStatus: () => request<AiStatus>("/ai/status"),
  runValidation: () =>
    request<ValidationRun>("/ai/validate", {
      method: "POST",
      // Three benchmark threads, each of several turns, every one of them a
      // real model call and a real governed run.
      timeoutMs: 300_000,
    }),
  latestValidation: () =>
    request<{ run: ValidationRun | null; message?: string }>("/ai/validation"),
  validationHistory: (limit = 20) =>
    request<{ runs: ValidationRun[]; available: boolean }>(
      `/ai/validation/history?limit=${limit}`,
    ),
  validationCase: (runId: number, benchmarkId: string) =>
    request<ValidationCase>(
      `/ai/validation/${runId}/${encodeURIComponent(benchmarkId)}`,
    ),

  // ---- ask CreditProbe ----
  askMode: () => request<PlannerMode>("/ask/mode"),
  askSuggestions: () =>
    request<{ questions: { question: string; note: string }[] }>("/ask/suggestions"),
  briefing: () => request<Briefing>("/ask/briefing", { timeoutMs: 60_000 }),
  recentInvestigations: (limit = 8) =>
    request<{ investigations: RecentInvestigation[] }>(`/ask/recent?limit=${limit}`),
  ask: (
    question: string,
    options: {
      projectId?: number;
      chatId?: number;
      /** Set after the user answers a period clarification. */
      fromPeriod?: string;
      toPeriod?: string;
    } = {},
  ) =>
    request<InvestigationResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        project_id: options.projectId ?? null,
        chat_id: options.chatId ?? null,
        persist: true,
        from_period: options.fromPeriod ?? null,
        to_period: options.toPeriod ?? null,
      }),
      // An investigation can run up to five analyses over two periods each.
      timeoutMs: 120_000,
    }),

  // ---- trace versions and modification ----
  investigation: (runId: number, version?: number) =>
    request<StoredInvestigation>(
      `/trace/${runId}/investigation${version ? `?version=${version}` : ""}`,
    ),
  traceVersions: (runId: number) => request<VersionsResponse>(`/trace/${runId}/versions`),
  previewModification: (runId: number, text: string, version?: number) =>
    request<ProposedChange>(`/trace/${runId}/modify/preview`, {
      method: "POST",
      body: JSON.stringify({ request: text, version: version ?? null }),
    }),
  applyModification: (runId: number, text: string, version?: number) =>
    request<AppliedModification>(`/trace/${runId}/modify/apply`, {
      method: "POST",
      body: JSON.stringify({ request: text, version: version ?? null }),
      timeoutMs: 120_000,
    }),

  // ---- data builder ----
  domains: () => request<{ domains: DomainSummary[] }>("/data-builder/domains"),
  /** Every domain, with its size, coverage, owner and status. */
  domainOverview: () =>
    request<{ domains: DomainOverview[] }>("/data-builder/domains/overview", {
      timeoutMs: 60_000,
    }),
  renameDomain: (name: string, newName: string) =>
    request<DomainSummary>(
      `/data-builder/domains/${encodeURIComponent(name)}/rename`,
      { method: "POST", body: JSON.stringify({ name: newName }) },
    ),
  setDomainStatus: (name: string, status: DomainStatus) =>
    request<{ name: string; status: DomainStatus }>(
      `/data-builder/domains/${encodeURIComponent(name)}/status`,
      { method: "POST", body: JSON.stringify({ status }) },
    ),
  /** Refused by the backend while the domain still holds datasets. */
  deleteDomain: (name: string) =>
    request<{ deleted: string }>(
      `/data-builder/domains/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  createDomain: (payload: Partial<DomainSummary> & { name: string }) =>
    request<DomainSummary>("/data-builder/domains", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  datasets: (opts: { domain?: string; lifecycle?: string } = {}) => {
    const q = new URLSearchParams();
    if (opts.domain) q.set("domain", opts.domain);
    if (opts.lifecycle) q.set("lifecycle", opts.lifecycle);
    const qs = q.toString();
    return request<{ count: number; datasets: DatasetSummary[] }>(
      `/data-builder/datasets${qs ? `?${qs}` : ""}`,
    );
  },
  createDataset: (payload: Record<string, unknown>) =>
    request<DatasetSummary>("/data-builder/datasets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  dataset: (name: string) => request<DatasetDetail>(`/data-builder/datasets/${name}`),
  uploadFile: (name: string, file: File, sheetName?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (sheetName) form.append("sheet_name", sheetName);
    return request<{
      upload: UploadRecord;
      profile: UploadProfile;
      suggested_mappings: FieldMappingRow[];
      lifecycle: Lifecycle;
    }>(`/data-builder/datasets/${name}/upload`, {
      method: "POST",
      body: form,
      rawBody: true,
      timeoutMs: 120_000,
    });
  },
  profile: (name: string) =>
    request<{ dataset: string; upload: UploadRecord; profile: UploadProfile }>(
      `/data-builder/datasets/${name}/profile`,
    ),
  mappings: (name: string) =>
    request<{ dataset: string; mappings: FieldMappingRow[] }>(
      `/data-builder/datasets/${name}/mappings`,
    ),
  setMappings: (name: string, mappings: Partial<FieldMappingRow>[]) =>
    request<{ dataset: string; lifecycle: Lifecycle; mappings: FieldMappingRow[] }>(
      `/data-builder/datasets/${name}/mappings`,
      { method: "PUT", body: JSON.stringify({ mappings }) },
    ),
  upsertField: (name: string, field: Partial<DictionaryField> & { name: string }) =>
    request<{ dataset: string; field: DictionaryField }>(
      `/data-builder/datasets/${name}/fields`,
      { method: "PUT", body: JSON.stringify(field) },
    ),
  seedDictionary: (name: string) =>
    request<{ dataset: string; created: number; fields: string[] }>(
      `/data-builder/datasets/${name}/fields/seed`,
      { method: "POST" },
    ),
  relationships: (dataset?: string) =>
    request<{ count: number; relationships: RelationshipRow[] }>(
      `/data-builder/relationships${dataset ? `?dataset=${dataset}` : ""}`,
    ),
  addRelationship: (payload: Omit<RelationshipRow, "id" | "name"> & { name?: string }) =>
    request<RelationshipRow>("/data-builder/relationships", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  validate: (name: string) =>
    request<ValidationReport>(`/data-builder/datasets/${name}/validate`, { method: "POST" }),
  publish: (name: string) =>
    request<PublishResponse>(`/data-builder/datasets/${name}/publish`, {
      method: "POST",
      timeoutMs: 60_000,
    }),
  versions: (name: string) =>
    request<{ dataset: string; count: number; versions: DataVersionRow[] }>(
      `/data-builder/datasets/${name}/versions`,
    ),

  // ---- lenses ----
  lensList: (status?: string) =>
    request<{
      lenses: Lens[];
      visuals: string[];
      statuses: string[];
      max_panels: number;
    }>(`/lenses${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  lens: (id: number) => request<Lens>(`/lenses/${id}`),
  renderLens: (id: number, period?: string) =>
    request<RenderedLens>(
      `/lenses/${id}/render${period ? `?period=${encodeURIComponent(period)}` : ""}`,
      { timeoutMs: 180_000 },
    ),
  buildLens: (requestText: string, apply = true) =>
    request<{ lens: Lens | null; proposal: LensProposal }>("/lenses/build", {
      method: "POST",
      body: JSON.stringify({ request: requestText, apply }),
      timeoutMs: 60_000,
    }),
  askLens: (id: number, requestText: string, apply = true) =>
    request<{ lens: Lens; proposal: LensProposal }>(`/lenses/${id}/ask`, {
      method: "POST",
      body: JSON.stringify({ request: requestText, apply }),
      timeoutMs: 60_000,
    }),
  restoreLens: (id: number, version: number) =>
    request<Lens>(`/lenses/${id}/restore/${version}`, { method: "POST" }),
  setLensStatus: (id: number, status: string) =>
    request<Lens>(`/lenses/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  deleteLens: (id: number) => request<void>(`/lenses/${id}`, { method: "DELETE" }),

  // ---- the dataset viewer ----
  datasetTree: () => request<DatasetTree>("/data-builder/tree"),
  /**
   * One page of a governed dataset.
   *
   * `filters` are `field:operator:value` strings. Both the field and the
   * operator are checked by the backend against the governed dictionary and a
   * fixed set of comparisons, so this is not a query interface with a friendly
   * name — a rejected filter comes back as a 422 saying which part was refused.
   */
  datasetRows: (
    name: string,
    opts: DatasetQuery & { offset?: number; limit?: number } = {},
  ) => {
    const query = datasetQuery(opts);
    if (opts.offset) query.set("offset", String(opts.offset));
    if (opts.limit) query.set("limit", String(opts.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<DatasetPage>(
      `/data-builder/datasets/${encodeURIComponent(name)}/rows${suffix}`,
      { timeoutMs: 60_000 },
    );
  },
  /**
   * How this person has arranged this dataset's grid.
   *
   * Per user and per dataset, stored on the server rather than in the browser:
   * somebody who spends an afternoon arranging the facility grid should find it
   * arranged the next morning, and on the other machine.
   */
  gridPreferences: (name: string) =>
    request<{ dataset: string; preferences: GridPreferences; stored: boolean }>(
      `/data-builder/datasets/${encodeURIComponent(name)}/grid-preferences`,
    ),
  saveGridPreferences: (name: string, preferences: GridPreferences) =>
    request<{ dataset: string; stored: boolean }>(
      `/data-builder/datasets/${encodeURIComponent(name)}/grid-preferences`,
      { method: "PUT", body: JSON.stringify(preferences) },
    ),
  datasetColumn: (name: string, field: string, period?: string) =>
    request<ColumnProfile>(
      `/data-builder/datasets/${encodeURIComponent(name)}/columns/` +
        `${encodeURIComponent(field)}${period ? `?period=${encodeURIComponent(period)}` : ""}`,
      { timeoutMs: 60_000 },
    ),
  datasetSchemaHistory: (name: string) =>
    request<SchemaHistory>(
      `/data-builder/datasets/${encodeURIComponent(name)}/schema-history`,
      { timeoutMs: 120_000 },
    ),
  /**
   * Where a governed export of the current view lives.
   *
   * A URL rather than a fetch: the browser downloads it directly, so a large
   * file never passes through JavaScript memory on its way to disk.
   */
  datasetExportUrl: (name: string, opts: DatasetQuery = {}) => {
    const query = datasetQuery(opts);
    const suffix = query.toString() ? `?${query}` : "";
    return (
      `${API_BASE_URL}${API_PREFIX}/data-builder/datasets/` +
      `${encodeURIComponent(name)}/export${suffix}`
    );
  },

  // ---- playbooks ----
  playbooks: (status?: string) =>
    request<PlaybookLibrary>(
      `/playbooks${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  playbook: (id: number) => request<Playbook>(`/playbooks/${id}`),
  createPlaybook: (payload: {
    name: string;
    description?: string;
    trigger?: string;
    schedule?: string;
    scope?: Record<string, unknown>;
    analyses: { analysis_id: string; params?: Record<string, unknown> }[];
    conditions?: PlaybookCondition[];
    actions?: { create_investigation?: boolean; notify?: number[] };
  }) =>
    request<Playbook>("/playbooks", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        description: payload.description ?? "",
        trigger: payload.trigger ?? "manual",
        schedule: payload.schedule ?? "",
        scope: payload.scope ?? {},
        analyses: payload.analyses,
        conditions: payload.conditions ?? [],
        actions: payload.actions ?? { create_investigation: false, notify: [] },
      }),
    }),
  setPlaybookStatus: (id: number, status: string) =>
    request<Playbook>(`/playbooks/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  runPlaybook: (id: number, period?: string) =>
    request<PlaybookRun>(`/playbooks/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ period: period ?? null }),
      timeoutMs: 180_000,
    }),
  playbookRuns: (id: number) =>
    request<{ runs: PlaybookRun[] }>(`/playbooks/${id}/runs`),
  deletePlaybook: (id: number) =>
    request<void>(`/playbooks/${id}`, { method: "DELETE" }),

  // ---- early warning ----
  earlyWarning: () => request<EarlyWarningOverview>("/early-warning"),
  earlyWarningMethodology: () =>
    request<EarlyWarningMethodology>("/early-warning/methodology"),
  earlyWarningScores: (targetId: string, opts: { period?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.period) query.set("period", opts.period);
    if (opts.limit) query.set("limit", String(opts.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<EarlyWarningScores>(
      `/early-warning/${encodeURIComponent(targetId)}/scores${suffix}`,
      { timeoutMs: 90_000 },
    );
  },
  earlyWarningModels: (targetId?: string) =>
    request<{ models: EarlyWarningModel[] }>(
      `/early-warning/lab/models${targetId ? `?target_id=${encodeURIComponent(targetId)}` : ""}`,
    ),
  earlyWarningModel: (id: number) =>
    request<EarlyWarningModel>(`/early-warning/lab/models/${id}`),
  fitEarlyWarning: (payload: {
    targetId: string;
    testQuarters?: number;
    name?: string;
    changeNote?: string;
    save?: boolean;
    activate?: boolean;
  }) =>
    request<FitResponse>("/early-warning/lab/fit", {
      method: "POST",
      body: JSON.stringify({
        target_id: payload.targetId,
        test_quarters: payload.testQuarters ?? 3,
        name: payload.name ?? "",
        change_note: payload.changeNote ?? "",
        save: payload.save ?? true,
        activate: payload.activate ?? true,
      }),
      timeoutMs: 180_000,
    }),
  activateEarlyWarningModel: (id: number) =>
    request<EarlyWarningModel>(`/early-warning/lab/models/${id}/activate`, {
      method: "POST",
    }),
  compareEarlyWarningModels: (fromId: number, toId: number, period?: string) =>
    request<ImpactAnalysis>("/early-warning/lab/compare", {
      method: "POST",
      body: JSON.stringify({
        from_model_id: fromId,
        to_model_id: toId,
        period: period ?? null,
      }),
      timeoutMs: 180_000,
    }),

  // ---- projects ----
  projects: (opts: { status?: string; ownerId?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.status) query.set("status", opts.status);
    if (opts.ownerId !== undefined) query.set("owner_id", String(opts.ownerId));
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ projects: ProjectRow[]; statuses: Record<string, string> }>(
      `/projects${suffix}`,
    );
  },
  project: (id: number) => request<ProjectRow>(`/projects/${id}`),
  projectContents: (id: number) => request<ProjectContents>(`/projects/${id}/contents`),
  createProject: (payload: {
    name: string;
    description?: string;
    instructions?: string;
    defaultContext?: Record<string, unknown>;
  }) =>
    request<ProjectRow>("/projects", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name,
        description: payload.description ?? "",
        instructions: payload.instructions ?? "",
        default_context: payload.defaultContext ?? {},
      }),
    }),
  updateProject: (
    id: number,
    payload: {
      name?: string;
      description?: string;
      instructions?: string;
      defaultContext?: Record<string, unknown>;
    },
  ) =>
    request<ProjectRow>(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: payload.name ?? null,
        description: payload.description ?? null,
        instructions: payload.instructions ?? null,
        default_context: payload.defaultContext ?? null,
      }),
    }),
  setProjectStatus: (id: number, status: ProjectStatus, note = "") =>
    request<ProjectRow>(`/projects/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, note }),
    }),
  sendProjectForReview: (id: number, assignedTo: number | null, note = "") =>
    request<ProjectRow>(`/projects/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ assigned_to: assignedTo, note }),
    }),

  // ---- investigations: conversations ----
  /**
   * Investigations.
   *
   * `scope` is the difference between the global list and a project's list.
   * "standalone" (the default the backend applies) is the Cockpit's own
   * conversations — a project's investigations belong to that project and are
   * deliberately absent. Pass a `projectId` with scope "project" for those.
   */
  threads: (
    opts: {
      projectId?: number;
      includeArchived?: boolean;
      scope?: "standalone" | "project" | "all";
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (opts.projectId !== undefined) query.set("project_id", String(opts.projectId));
    if (opts.scope) query.set("scope", opts.scope);
    if (opts.includeArchived) query.set("include_archived", "true");
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ investigations: ThreadSummary[] }>(`/investigations${suffix}`);
  },
  thread: (id: number) => request<Thread>(`/investigations/${id}`),
  startThread: (payload: {
    question: string;
    title?: string;
    projectId?: number | null;
    ask?: boolean;
    fromPeriod?: string;
    toPeriod?: string;
  }) =>
    request<ThreadTurn>("/investigations", {
      method: "POST",
      body: JSON.stringify({
        question: payload.question,
        title: payload.title ?? "",
        project_id: payload.projectId ?? null,
        ask: payload.ask ?? true,
        from_period: payload.fromPeriod ?? null,
        to_period: payload.toPeriod ?? null,
      }),
      timeoutMs: 120_000,
    }),
  askInThread: (
    id: number,
    question: string,
    period?: { from: string; to: string },
  ) =>
    request<ThreadTurn>(`/investigations/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({
        question,
        from_period: period?.from ?? null,
        to_period: period?.to ?? null,
      }),
      timeoutMs: 120_000,
    }),
  setThreadContext: (id: number, context: Record<string, unknown>) =>
    request<Thread>(`/investigations/${id}/context`, {
      method: "POST",
      body: JSON.stringify({ context }),
    }),
  renameThread: (id: number, title: string) =>
    request<Thread>(`/investigations/${id}/rename`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  /** Add a project's investigation to the global list, or take it out. §4. */
  publishThread: (id: number, published: boolean) =>
    request<Thread>(`/investigations/${id}/publish`, {
      method: "POST",
      body: JSON.stringify({ published }),
    }),
  moveThread: (id: number, projectId: number | null) =>
    request<Thread>(`/investigations/${id}/move`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    }),
  copyThread: (id: number, opts: { projectId?: number | null; title?: string } = {}) =>
    request<Thread>(`/investigations/${id}/copy`, {
      method: "POST",
      body: JSON.stringify({
        project_id: opts.projectId ?? null,
        title: opts.title ?? "",
      }),
    }),
  /** Open a project around this conversation, carrying its settled context in. */
  projectFromThread: (
    id: number,
    opts: { name?: string; description?: string; move?: boolean } = {},
  ) =>
    request<{ project: ProjectRow; investigation: Thread }>(
      `/investigations/${id}/project`,
      {
        method: "POST",
        body: JSON.stringify({
          name: opts.name ?? "",
          description: opts.description ?? "",
          move: opts.move ?? true,
        }),
      },
    ),
  archiveThread: (id: number) =>
    request<Thread>(`/investigations/${id}/archive`, { method: "POST" }),

  // ---- saved analyses ----
  savedAnalyses: (
    opts: { projectId?: number; investigationId?: number; analysisId?: string } = {},
  ) => {
    const query = new URLSearchParams();
    if (opts.projectId !== undefined) query.set("project_id", String(opts.projectId));
    if (opts.investigationId !== undefined)
      query.set("investigation_id", String(opts.investigationId));
    if (opts.analysisId) query.set("analysis_id", opts.analysisId);
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ analyses: SavedAnalysis[] }>(`/analyses${suffix}`);
  },
  savedAnalysis: (id: number) => request<SavedAnalysis>(`/analyses/${id}`),
  saveAnalysis: (payload: {
    analysisId: string;
    title?: string;
    result?: Record<string, unknown>;
    params?: Record<string, unknown>;
    filters?: Record<string, unknown>;
    period?: Record<string, unknown>;
    dataVersions?: Record<string, unknown>;
    analysisRunId?: number | null;
    investigationId?: number | null;
    projectId?: number | null;
    note?: string;
  }) =>
    request<SavedAnalysis>("/analyses", {
      method: "POST",
      body: JSON.stringify({
        analysis_id: payload.analysisId,
        title: payload.title ?? "",
        result: payload.result ?? {},
        params: payload.params ?? {},
        filters: payload.filters ?? {},
        period: payload.period ?? {},
        data_versions: payload.dataVersions ?? {},
        analysis_run_id: payload.analysisRunId ?? null,
        investigation_id: payload.investigationId ?? null,
        project_id: payload.projectId ?? null,
        note: payload.note ?? "",
      }),
    }),
  saveAnalysesFromAnswer: (payload: {
    investigationId: number;
    sequence: number;
    projectId?: number | null;
    title?: string;
    note?: string;
  }) =>
    request<{ analyses: SavedAnalysis[]; count: number }>("/analyses/from-message", {
      method: "POST",
      body: JSON.stringify({
        investigation_id: payload.investigationId,
        sequence: payload.sequence,
        project_id: payload.projectId ?? null,
        title: payload.title ?? "",
        note: payload.note ?? "",
      }),
    }),
  moveAnalysis: (id: number, projectId: number | null) =>
    request<SavedAnalysis>(`/analyses/${id}/move`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    }),
  renameAnalysis: (id: number, title: string) =>
    request<SavedAnalysis>(`/analyses/${id}/rename`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deleteAnalysis: (id: number) =>
    request<void>(`/analyses/${id}`, { method: "DELETE" }),

  // ---- workspace: saved investigations ----
  savedInvestigations: (params: { projectId?: number; ownerId?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.projectId !== undefined) query.set("project_id", String(params.projectId));
    if (params.ownerId !== undefined) query.set("owner_id", String(params.ownerId));
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ investigations: SavedInvestigationSummary[] }>(
      `/workspace/investigations${suffix}`,
    );
  },
  saveInvestigation: (payload: {
    question: string;
    title?: string;
    projectId?: number;
    fromPeriod?: string;
    toPeriod?: string;
  }) =>
    request<SavedInvestigation>("/workspace/investigations", {
      method: "POST",
      body: JSON.stringify({
        question: payload.question,
        title: payload.title ?? "",
        project_id: payload.projectId ?? null,
        from_period: payload.fromPeriod ?? null,
        to_period: payload.toPeriod ?? null,
      }),
      timeoutMs: 120_000,
    }),
  savedInvestigation: (id: number, version?: number) =>
    request<SavedInvestigation>(
      `/workspace/investigations/${id}${version ? `?version=${version}` : ""}`,
    ),
  refreshInvestigation: (id: number, period?: { from: string; to: string }) =>
    request<SavedInvestigation>(`/workspace/investigations/${id}/refresh`, {
      method: "POST",
      body: JSON.stringify({
        from_period: period?.from ?? null,
        to_period: period?.to ?? null,
      }),
      timeoutMs: 120_000,
    }),

  // ---- workspace: review, comments, notifications ----
  workflowInbox: () => request<WorkflowInbox>("/workspace/workflow/inbox"),
  /** Send an object to people and/or teams, for a named action. §43, §44. */
  submitForReview: (payload: {
    objectType: string;
    objectId: string;
    objectVersion?: string | null;
    title: string;
    assignedTo?: number;
    recipients?: number[];
    teams?: number[];
    action?: WorkflowAction;
    priority?: WorkflowPriority;
    dueAt?: string | null;
    note?: string;
  }) =>
    request<WorkflowDetail>("/workspace/workflow", {
      method: "POST",
      body: JSON.stringify({
        object_type: payload.objectType,
        object_id: payload.objectId,
        object_version: payload.objectVersion ?? null,
        title: payload.title,
        assigned_to: payload.assignedTo ?? null,
        recipients: payload.recipients ?? [],
        teams: payload.teams ?? [],
        action: payload.action ?? "review",
        priority: payload.priority ?? "normal",
        due_at: payload.dueAt ?? null,
        note: payload.note ?? "",
      }),
    }),
  /** Record that a recipient has looked at it. Idempotent. §44. */
  openWorkflow: (id: number) =>
    request<WorkflowDetail>(`/workspace/workflow/${id}/opened`, { method: "POST" }),
  /** Say something on a workflow item's thread. §45. */
  sayOnWorkflow: (
    id: number,
    payload: {
      body: string;
      parentId?: number | null;
      mentions?: { user_id?: number; team_id?: number }[];
      attachments?: { type: string; id: string; label?: string }[];
    },
  ) =>
    request<WorkflowMessageRow>(`/workspace/workflow/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({
        body: payload.body,
        parent_id: payload.parentId ?? null,
        mentions: payload.mentions ?? [],
        attachments: payload.attachments ?? [],
      }),
    }),
  resolveWorkflowMessage: (messageId: number, resolved = true) =>
    request<WorkflowMessageRow>(
      `/workspace/workflow/messages/${messageId}/resolve`,
      { method: "POST", body: JSON.stringify({ resolved }) },
    ),
  workflowItem: (id: number) => request<WorkflowDetail>(`/workspace/workflow/${id}`),
  moveWorkflow: (id: number, toState: string, comment = "") =>
    request<WorkflowDetail>(`/workspace/workflow/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ to_state: toState, comment }),
    }),
  comments: (objectType: string, objectId: string) =>
    request<{ comments: CommentRow[] }>(`/workspace/comments/${objectType}/${objectId}`),
  addComment: (objectType: string, objectId: string, body: string, notifyUserId?: number) =>
    request<CommentRow>(`/workspace/comments/${objectType}/${objectId}`, {
      method: "POST",
      body: JSON.stringify({ body, notify_user_id: notifyUserId ?? null }),
    }),
  notifications: (unreadOnly = false) =>
    request<{ notifications: NotificationRow[]; unread: number }>(
      `/workspace/notifications${unreadOnly ? "?unread_only=true" : ""}`,
    ),
  markNotificationsRead: (id?: number) =>
    request<{ marked: number; unread: number }>(
      `/workspace/notifications/read${id ? `?notification_id=${id}` : ""}`,
      { method: "POST" },
    ),

  // ---- the data control plane ----
  controlPlane: () => request<ControlPlane>("/data-builder/control-plane"),
  datasetFamilies: () => request<{ families: DatasetFamily[] }>("/data-builder/families"),
  datasetUsedBy: (name: string) => request<UsedBy>(`/data-builder/datasets/${name}/used-by`),
  syncBundled: () =>
    request<{ synced: string[]; skipped: string[]; message: string }>(
      "/data-builder/sync-bundled",
      { method: "POST" },
    ),
  setDatasetOrigin: (name: string, origin: string) =>
    request<{ dataset: string; origin: string }>(`/data-builder/datasets/${name}/origin`, {
      method: "POST",
      body: JSON.stringify({ origin }),
    }),
  setAuthoritative: (name: string, purposes: string[]) =>
    request<{ dataset: string; authoritative_for: string[]; displaced_demo_datasets: string[] }>(
      `/data-builder/datasets/${name}/authoritative`,
      { method: "POST", body: JSON.stringify({ purposes }) },
    ),
  harmonise: (name: string) =>
    request<Harmonisation>(`/data-builder/datasets/${name}/harmonise`),
  acceptHarmonisation: (name: string, accepted: Record<string, string>) =>
    request<{ dataset: string; accepted: number; still_unmapped: number }>(
      `/data-builder/datasets/${name}/harmonise/accept`,
      { method: "POST", body: JSON.stringify({ accepted }) },
    ),

  // ---- relationships ----
  relationshipMap: () => request<RelationshipMap>("/data-builder/relationships/map"),
  seedRelationships: () =>
    request<{ declared: string[]; skipped: string[]; total: number }>(
      "/data-builder/relationships/seed", { method: "POST" }),
  relationship: (id: number) =>
    request<RelationshipDetail>(`/data-builder/relationships/${id}`),
  proposeRelationships: (dataset: string) =>
    request<RelationshipProposals>(
      `/data-builder/relationships/propose?dataset=${encodeURIComponent(dataset)}`,
      { timeoutMs: 120_000 }),
  acceptRelationshipProposal: (proposal: RelationshipProposal) =>
    request<{ relationship: RelationshipEdge; note: string }>(
      "/data-builder/relationships/propose/accept",
      {
        method: "POST",
        body: JSON.stringify({
          from_dataset: proposal.from_dataset,
          from_field: proposal.from_field,
          to_dataset: proposal.to_dataset,
          to_field: proposal.to_field,
          cardinality: proposal.cardinality,
          semantic: proposal.semantic ?? "",
        }),
      }),
  validateRelationship: (id: number, period = "") =>
    request<{ relationship: RelationshipEdge; report: RelationshipValidation }>(
      `/data-builder/relationships/${id}/validate${period ? `?period=${encodeURIComponent(period)}` : ""}`,
      { method: "POST", timeoutMs: 120_000 }),
  setRelationshipLifecycle: (id: number, lifecycle: string, note = "") =>
    request<{ relationship: RelationshipEdge; versions: RelationshipVersionEntry[] }>(
      `/data-builder/relationships/${id}/lifecycle`,
      { method: "POST", body: JSON.stringify({ lifecycle, note }) }),

  // ---- the data inbox ----
  inbox: (status = "") =>
    request<InboxListing>(`/data-builder/inbox${status ? `?status=${status}` : ""}`),
  inboxItem: (id: number) => request<InboxItem>(`/data-builder/inbox/${id}`),
  receiveFile: (file: File, options: { publish?: boolean; sheetName?: string } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("publish", String(options.publish ?? true));
    if (options.sheetName) form.append("sheet_name", options.sheetName);
    return request<InboxItem>("/data-builder/inbox", {
      method: "POST",
      body: form,
      rawBody: true,
      timeoutMs: 120_000,
    });
  },
  resolveInboxItem: (id: number, action: "publish" | "reject", note: string, dataset = "") =>
    request<InboxItem>(`/data-builder/inbox/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, note, dataset }),
      timeoutMs: 120_000,
    }),

  // ---- Analysis Studio ----
  studioLibrary: (params: {
    q?: string;
    category?: string;
    lifecycle?: string;
    certifiedOnly?: boolean;
    runnableOnly?: boolean;
    limit?: number;
  } = {}) => {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.category) query.set("category", params.category);
    if (params.lifecycle) query.set("lifecycle", params.lifecycle);
    if (params.certifiedOnly) query.set("certified_only", "true");
    if (params.runnableOnly) query.set("runnable_only", "true");
    if (params.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return request<StudioLibrary>(`/studio${suffix ? `?${suffix}` : ""}`);
  },
  studioMethod: (id: string) =>
    request<{ method: StudioMethod }>(`/studio/${encodeURIComponent(id)}`),
  studioCertificationAudit: () =>
    request<StudioStats["certification_audit"]>("/studio/certification"),
  studioDescribe: (description: string) =>
    request<{ reading: StudioReading }>("/studio/describe", {
      method: "POST",
      body: JSON.stringify({ description }),
    }),
  studioBuild: (payload: {
    name: string;
    description: string;
    answers: Record<string, string>;
    openingPeriod: string;
    closingPeriod: string;
    dataset?: string;
    save?: boolean;
  }) =>
    request<StudioBuildResult>("/studio/build", {
      method: "POST",
      timeoutMs: 90_000,
      body: JSON.stringify({
        name: payload.name,
        description: payload.description,
        answers: payload.answers,
        opening_period: payload.openingPeriod,
        closing_period: payload.closingPeriod,
        dataset: payload.dataset ?? "portfolio_facility",
        save: payload.save ?? false,
      }),
    }),
  studioValidate: (id: string) =>
    request<{ method: StudioMethod; validation: StudioValidationPack }>(
      `/studio/${encodeURIComponent(id)}/validate`,
      { method: "POST", timeoutMs: 90_000 },
    ),
  studioCertify: (id: string, certifiedBy: string) =>
    request<{ method: StudioMethod; persisted: boolean }>(
      `/studio/${encodeURIComponent(id)}/certify`,
      { method: "POST", body: JSON.stringify({ certified_by: certifiedBy }) },
    ),
  studioFork: (id: string, name: string) =>
    request<{ method: StudioMethod; forked_from: string; persisted: boolean; note: string }>(
      `/studio/${encodeURIComponent(id)}/fork`,
      { method: "POST", body: JSON.stringify({ name }) },
    ),
  studioEdit: (id: string, changes: Record<string, string>, changeNote: string) =>
    request<{ method: StudioMethod; changes: string[]; persisted: boolean }>(
      `/studio/${encodeURIComponent(id)}/edit`,
      { method: "POST", body: JSON.stringify({ changes, change_note: changeNote }) },
    ),
  /**
   * The workbook lives at a URL rather than behind a fetch: the browser's own
   * download is what a person expects from a download button, and streaming it
   * through JavaScript to re-offer it as a blob adds a failure mode for nothing.
   */
  studioSaveDynamic: (payload: {
    name: string;
    question: string;
    summary: string;
    plan: AnalyticalPlanPayload;
  }) =>
    request<{ method: StudioMethod; persisted: boolean; note: string }>(
      "/studio/from-analysis",
      {
        method: "POST",
        body: JSON.stringify({
          name: payload.name,
          question: payload.question,
          summary: payload.summary,
          plan: payload.plan,
        }),
      },
    ),
  studioValidationPackUrl: (id: string) =>
    `${API_BASE_URL}${API_PREFIX}/studio/${encodeURIComponent(id)}/validation-pack.xlsx`,

  // ---- workbook exports ----
  /**
   * What this user may download for this run, and why not where they may not.
   *
   * Asked so a refusal is explained where the button is, rather than discovered
   * as a 403 after a click. The endpoints enforce the same decision for
   * themselves; this is courtesy, not the control.
   */
  exportAvailability: (runId: number) =>
    request<ExportAvailability>(`/analysis-runs/${runId}/export/availability`),
  downloadResults: (runId: number, version?: number) =>
    download(
      `/analysis-runs/${runId}/export/results.xlsx` +
        (version ? `?version=${version}` : ""),
      `CreditProbe_analysis_${runId}_results.xlsx`,
    ),
  downloadCalculationPack: (runId: number, version?: number) =>
    download(
      `/trace/${runId}/export/calculation-pack.xlsx` +
        (version ? `?version=${version}` : ""),
      `CreditProbe_analysis_${runId}_calculation_pack.xlsx`,
    ),
  exportHistory: (runId: number) =>
    request<{ run_id: number; exports: ExportRecord[] }>(
      `/analysis-runs/${runId}/export/history`,
    ),

  // ---- the metadata assistants ----
  askDataBuilder: (question: string) =>
    request<AssistantAnswer>("/data-builder/assistant", {
      method: "POST",
      body: JSON.stringify({ question }),
      timeoutMs: 60_000,
    }),
  askEngineBuilder: (question: string) =>
    request<AssistantAnswer>("/engine/assistant", {
      method: "POST",
      body: JSON.stringify({ question }),
      timeoutMs: 60_000,
    }),
};
