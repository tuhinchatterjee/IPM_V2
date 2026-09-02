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

import { filenameFrom } from "@/lib/downloads";

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
  API_BASE_URL ||
  "this page's own address, forwarded to the CreditProbe backend";

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

export interface DemoPostureResponse {
  demo_mode: boolean;
  label: string;
  detail: string;
  data_release: string;
  guarantees: Record<string, boolean>;
  guarantee_means: Record<string, string>;
  demo_safe_mode: boolean;
  version: string;
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
  datasets?: {
    dataset: string;
    version: string;
    origin: string;
    periods: string[];
  }[];
  relationships_used?: {
    relationship_id: number;
    version: number;
    cardinality: string;
  }[];
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
  /**
   * What the governed visualisation gate decided about this result: whether a
   * chart should OPEN, or whether the table is the answer and the chart is
   * offered beside it. The screen used to re-derive this from the column
   * shape alone, which is blind to what was asked — so "which datasets carry
   * exposure?" came back drawn as a bar chart because its two columns
   * happened to look like axes.
   */
  visual?: { chart?: string; chart_first?: boolean; reason?: string } | null;
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

export type Lifecycle =
  | "draft"
  | "mapped"
  | "validated"
  | "published"
  | "archived";

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

/**
 * What one question cost. R2 §16.
 *
 * No model id: the model serving a request is not shown in the product. The
 * administrator's cost trace is served from the same endpoint with the ids
 * included, which is a different surface with a different permission.
 */
export interface QuestionCost {
  version: string;
  question_class: string;
  class_label: string;
  class_reason: string;
  path: string;
  reproduced: boolean;
  model_calls: number;
  models?: string[];
  tool_calls: number;
  repeated_tool_calls: number;
  loop_steps: number;
  retries: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cached_share: number;
  metadata_tokens: number;
  evidence_tokens: number;
  cost_units: number;
  duration_ms: number;
  calls: Array<{
    purpose: string;
    role: string;
    model?: string;
    tier: string;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    attempts: number;
    retries: number;
    duration_ms: number;
    ok: boolean;
    cost_units: number;
  }>;
  question?: string;
}

export interface CostClassSummary {
  class: string;
  label: string;
  questions: number;
  model_calls: number;
  avg_model_calls: number;
  avg_cost_units: number;
  avg_duration_ms: number;
  avg_input_tokens: number;
  avg_output_tokens: number;
}

export interface CostTrace {
  summary: {
    version: string;
    questions: number;
    answered: number;
    reproduced: number;
    cache_hit_rate: number;
    cost_units: number;
    cost_units_avoided: number;
    model_calls: number;
    by_class: Record<string, CostClassSummary>;
  };
  questions: QuestionCost[];
}

/** One party in a borrower's group structure. R2 §2. */
export interface RelatedParty {
  node_id: string;
  label: string;
  node_type: string;
  detail: string;
  direction: "UPSTREAM" | "DOWNSTREAM" | "LATERAL";
  depth: number;
  relationship: string;
  edge_type: string;
  ownership_pct: number | null;
  voting_pct: number | null;
  amount: number | null;
  instrument: string;
  source: string;
  confidence: number | null;
  via: string[];
  is_borrower: boolean;
  exposure: number | null;
  controls: boolean;
  significant: boolean;
}

export interface RelationshipGroup {
  direction: "UPSTREAM" | "DOWNSTREAM" | "LATERAL";
  label: string;
  question: string;
  count: number;
  parties: RelatedParty[];
}

export interface RelationshipNetwork {
  version: string;
  centre: string;
  centre_label: string;
  period: string;
  as_of: string;
  view: string;
  depth: number;
  party_count: number;
  groups: RelationshipGroup[];
  edges: Array<Record<string, unknown>>;
  group_exposure: number;
  centre_exposure: number | null;
  group_borrowers: number;
  exposure_is_floor: boolean;
  truncated: boolean;
  truncation_note: string;
}

/** One part of a borrower's credit story. R2 §5. */
export interface StorySection {
  key: string;
  heading: string;
  question: string;
  body: string[];
  evidence: Array<Record<string, unknown>>;
  unavailable: string;
  empty: boolean;
}

export interface StoryFamily {
  family: string;
  label: string;
  means: string;
  severity: string;
  fired: SignalObservation[];
  untested: SignalObservation[];
  quiet: boolean;
  reading: string;
}

export interface BorrowerStory {
  version: string;
  borrower_id: string;
  period: string;
  sections: StorySection[];
  families: StoryFamily[];
  standing: SignalStanding;
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

/**
 * What one objective of a compound request ended up as. §11, §39.
 *
 * The distinction between COMPLETE and PARTIAL is the one that matters on
 * screen: PARTIAL means the clause was folded into a combined analysis and
 * not separately verified, which is a different thing from answered and a
 * different thing from dropped.
 */
export interface ObjectiveCoverageEntry {
  objective_id: string;
  description: string;
  action: string;
  status: string;
  note: string;
  planned_task: string;
}

export interface ObjectiveCoverage {
  total: number;
  complete: number;
  presentable: boolean;
  by_status: Record<string, number>;
  sentence: string;
  headline: string;
  objectives: ObjectiveCoverageEntry[];
  unmet: string[];
  unsettled: string[];
  failed: string[];
}

/** §38: how much analysis was done and how much prose came back, and why. */
export interface LengthPolicy {
  band: string;
  analysis_count: number;
  task_count: number;
  depth: string;
  paragraphs: [number, number];
  paragraph_band: string;
  words: [number, number];
  max_visualizations: number;
  needs_clarification: boolean;
  layout: string;
  reasons: string[];
}

/** §12: one analysis the planner weighed. */
export interface PortfolioDecision {
  analysis_id: string;
  title: string;
  question: string;
  concept_id: string;
  objective_id: string;
  datasets: string[];
  depends_on: string[];
  because: string;
  validation_only: boolean;
  selected: boolean;
  primary: boolean;
  reason: string;
  score: {
    relevance: number;
    availability: number;
    independence: number;
    cost: number;
    expected_value_of_information: number;
    value_per_cost: number;
  };
}

export interface AnalysisPortfolio {
  request: string;
  candidate_analyses: PortfolioDecision[];
  selected_analyses: PortfolioDecision[];
  rejected_analyses: PortfolioDecision[];
  selection_reason: string;
  expected_value_of_information: number;
  cost_estimate: number;
  dependency_graph: Record<string, string[]>;
  layers: string[][];
  parallelism: number;
  primary: string[];
  supporting: string[];
  validation_only: string[];
  uncovered_objectives: Record<string, string>;
}

/**
 * §11, §12, §35-§40. What was asked, what ran, and what came back.
 *
 * `available: false` is not the same as an absent block. It means the
 * coverage of this request could not be established - which the interface
 * has to say, because silence would read as "everything was answered".
 */
export interface CompoundAnswer {
  available: boolean;
  why?: string;
  questions_answered?: string;
  coverage?: ObjectiveCoverage;
  shared_scope?: {
    cohort_id: string;
    population: string;
    grain: string;
    divergent: string[];
    shared: boolean;
  };
  length_policy?: LengthPolicy;
  layout?:
    | "single"
    | "primary_and_supporting"
    | "grouped"
    | "investigation_review";
  analyses_performed?: number;
  suggested?: string[];
  is_compound?: boolean;
  portfolio?: AnalysisPortfolio;
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
  compound?: CompoundAnswer;
  /**
   * The analyst's own investigation of the same question, when one ran.
   * R2 §9 and §23: the reading it formed is carried apart from the answer so
   * the screen can mark it as a reading rather than as a measurement.
   */
  analyst?: AnalystInvestigation;
}

/** What the governed investigation loop produced. R2 §9, §23. */
export interface AnalystInvestigation {
  path: string;
  outcome?: string;
  answer?: string;
  findings?: string[];
  unavailable?: string[];
  limitations?: string[];
  /** The reading, kept apart from the facts it rests on. */
  interpretation?: string;
  alternatives?: string[];
  confirm_or_refute?: string[];
  external_context?: string[];
  analyst_available?: boolean;
  why?: string;
  cost?: QuestionCost;
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
  available_versions: {
    version: number;
    label: string;
    created_at: string | null;
  }[];
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
  operation: {
    kind: string;
    payload: Record<string, unknown>;
    description: string;
  } | null;
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
  hash_diff: {
    added: string[];
    removed: string[];
    changed: string[];
    unchanged: string[];
  };
  available_versions: {
    version: number;
    label: string;
    created_at: string | null;
  }[];
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

/* ---------------------------------------------------------------- agentic */

/**
 * What the working indicator polls. §8.
 *
 * Deliberately small — see `api.agenticLive`. Everything here is a structured
 * stage or a count the run recorded; there is no field carrying a model's
 * intermediate reasoning, and §7 forbids one.
 */
export interface OfficerLive {
  run_id: number;
  run_key: string;
  stage: string;
  label: string;
  caption: string;
  detail: string;
  officer_title: string;
  officer_level: number;
  status_line: string;
  specialists: string[];
  agent_count: number;
  elapsed_ms: number;
  active: boolean;
  terminal: boolean;
  completed: string[];
  history: { stage: string; at: string; detail?: string }[];
  sequence: string[];
  selection_reason: string;
  escalation_line: string;
  failure: string;
  assurance: string;
  analysis_run_id: number | null;
}

/** The agentic block an Ask response carries. §11, §53, §54. */
export interface AgenticBlock {
  run_id: number | null;
  run_key: string;
  coordinated: boolean;
  escalated: boolean;
  officer_level: number;
  officer_title: string;
  remit?: string;
  selection_reason: string;
  complexity_score: number;
  risk_score: number;
  score: number;
  agent_count: number;
  planned_task_count: number;
  status_line: string;
  reasons: { id: string; weight: number; detail: string; kind: string }[];
  escalation_line: string;
  completion_line: string;
  specialists?: string[];
  summary?: string;
  findings?: {
    agent_id: string;
    agent_name: string;
    finding: string;
    analysis_run_id: number | null;
  }[];
  conflicts?: {
    about: string;
    between: string[];
    resolved: boolean;
    sentence: string;
  }[];
  limitations?: string[];
  assurance?: {
    status: string;
    meaning: string;
    weakest: string;
    passed: number;
    checked: number;
    components: { key: string; label: string; state: string; detail: string }[];
  };
}

/** What `previewOfficer` returns: an officer, before any work has started. */
export interface OfficerPreview {
  officer_level: number;
  officer_title: string;
  remit: string;
  selection_reason: string;
  complexity_score: number;
  risk_score: number;
  status_line: string;
  provisional: boolean;
  stage: string;
  caption: string;
}

export interface AgentRunSummary {
  id: number;
  run_key: string;
  trigger: string;
  trigger_label: string;
  question: string;
  period: string;
  officer_level: number;
  officer_title: string;
  orchestrator: string;
  specialists: string[];
  agent_count: number;
  task_count: number;
  status: string;
  stage: string;
  stage_label: string;
  assurance: string;
  usage: string;
  failure: string;
  failure_kind: string;
  analysis_run_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string | null;
}

export interface AgentTaskView {
  task_key: string;
  agent_id: string;
  agent_name: string;
  purpose: string;
  depends_on: string[];
  layer: number;
  tool: string;
  status: string;
  analysis_run_id: number | null;
  finding: string;
  validation_state: string;
  tool_calls: Record<string, unknown>[];
  retry_count: number;
  error: string;
  error_category: string;
  approval_state: string;
  duration_ms: number | null;
}

export interface AgentRunDetail extends AgentRunSummary {
  selection_reason: string;
  complexity_score: number;
  risk_score: number;
  plan: Record<string, unknown>;
  task_graph: Record<string, unknown>;
  budgets: Record<string, unknown>;
  versions: Record<string, unknown>;
  findings: Record<string, unknown>[];
  conflicts: Record<string, unknown>[];
  handoffs: Record<string, unknown>[];
  validation: Record<string, unknown>;
  assurance_detail: Record<string, unknown>;
  synthesis: string;
  stage_history: { stage: string; at: string; detail?: string }[];
  trace_id: string;
  build_sha: string;
  config_fingerprint: string;
  service_identity: string;
  tasks: AgentTaskView[];
  approvals: AgentApproval[];
}

export interface AgentDefinition {
  agent_id: string;
  business_name: string;
  purpose: string;
  when_to_use: string[];
  when_not_to_use: string[];
  allowed_capabilities: string[];
  allowed_tools: string[];
  allowed_data_domains: string[];
  domain_labels: string[];
  allowed_methods: string[];
  maximum_steps: number;
  timeout_seconds: number;
  autonomy_level: number;
  human_approval_requirements: string[];
  escalation_rules: string[];
  validation_requirements: string[];
  model_role_preference: string;
  owner: string;
  version: string;
  status: string;
  evaluation_score: number;
  certification_state: string;
}

export interface AgentCatalogue {
  version: string;
  fingerprint: string;
  agents: AgentDefinition[];
  domains: { id: string; label: string; concepts: string[] }[];
  last_runs: Record<string, { at: string | null; tasks: number }>;
  autonomy_levels: { level: number; name: string; meaning: string }[];
}

export interface AgentTool {
  tool_id: string;
  name: string;
  purpose: string;
  service: string;
  parameters: string[];
  required: string[];
  writes: boolean;
  reads_data: boolean;
  cost: string;
}

export interface AgentSchedule {
  id: number;
  name: string;
  description: string;
  trigger: string;
  trigger_label: string;
  scope: string;
  agents: { agent_id: string; name: string }[];
  data_requirement: string[];
  approval_policy: string;
  enabled: boolean;
  last_run_at: string | null;
  last_run_id: number | null;
}

export interface AgentPolicy {
  key: string;
  label: string;
  value: Record<string, unknown>;
  version: number;
  versions: number;
  history: {
    version: number;
    value: Record<string, unknown>;
    active: boolean;
    note: string;
    at: string | null;
  }[];
}

export interface AgentApproval {
  id: number;
  run_id: number | null;
  action: string;
  action_label: string;
  consequence: string;
  autonomy_level: number;
  agent_id: string;
  agent_name: string;
  title: string;
  reason: string;
  proposal: Record<string, unknown>;
  evidence: Record<string, unknown>;
  scope: string;
  objects_affected: Record<string, unknown>[];
  risk: string;
  reversibility: string;
  approver_role: string;
  status: string;
  decided_by: number | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string | null;
  actions: string[];
}

export interface AgentEvent {
  id: number;
  kind: string;
  label: string;
  idempotency_key: string;
  period: string;
  status: string;
  reason: string;
  at: string | null;
}

export interface AgentEvaluation {
  tier: string;
  version: string;
  started_at: string;
  duration_ms: number;
  total: number;
  passed: number;
  accuracy: number;
  certified: boolean;
  verdict: string;
  safety_failures: AgentEvaluationCase[];
  areas: {
    area: string;
    label: string;
    total: number;
    passed: number;
    accuracy: number;
    safety: boolean;
  }[];
  cases: AgentEvaluationCase[];
  tiers: { id: string; label: string; note: string }[];
}

export interface AgentEvaluationCase {
  case_id: string;
  area: string;
  area_label: string;
  title: string;
  expectation: string;
  passed: boolean;
  observed: string;
  safety: boolean;
  duration_ms: number;
  error: string;
}

export interface AgentWorker {
  worker_id: string;
  hostname: string;
  status: string;
  current_job_id: number | null;
  jobs_completed: number;
  jobs_failed: number;
  build_sha: string;
  started_at: string | null;
  heartbeat_at: string | null;
  alive: boolean;
}

/** One Risk Case, as Requires Attention and the drawer read it. §41-§43, §47. */
export interface RiskCase {
  id: number;
  case_key: string;
  title: string;
  level: string;
  level_label: string;
  entity: string;
  entity_id: string;
  entity_kind: string;
  period: string;
  prior_period: string;
  severity: string;
  severity_score: number;
  severity_detail: {
    score: number;
    band: string;
    version: string;
    explanation: string;
    weights: Record<string, number>;
    components: {
      key: string;
      label: string;
      value: number;
      weight: number;
      contribution: number;
      detail: string;
    }[];
  };
  severity_version: string;
  priority: number;
  evidence_coverage: number;
  exposure: number | null;
  exposure_unit: string;
  metrics: Record<string, unknown>[];
  signals: string[];
  conclusion: string;
  why: string;
  evidence: Record<string, unknown>;
  analyses: number[];
  status: string;
  status_label: string;
  open: boolean;
  owner_id: number | null;
  team_id: number | null;
  due_at: string | null;
  overdue: boolean;
  snooze_until: string | null;
  dismiss_reason: string;
  resolution: string;
  investigation_id: number | null;
  project_id: number | null;
  workflow_item_id: number | null;
  agent_run_id: number | null;
  trace_id: string;
  created_at: string | null;
  updated_at: string | null;
  timeline: {
    id: number;
    kind: string;
    from_status: string;
    to_status: string;
    body: string;
    actor_id: number | null;
    actor_agent: string;
    actor_label: string;
    at: string | null;
  }[];
  links: {
    id: number;
    object_type: string;
    object_id: string;
    label: string;
    relation: string;
    at: string | null;
  }[];
  next_actions: { id: string; label: string; note: string }[];
}

export interface RiskCaseList {
  summary: string;
  counts: Record<string, number>;
  filters: { id: string; label: string }[];
  level: string;
  period: string;
  cases: RiskCase[];
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
  plan: {
    operations?: Record<string, unknown>[];
    meta?: Record<string, unknown>;
  } | null;
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


/* ------------------------------------------------------------------ messages
 *
 * The internal workflow surface. Every shape here mirrors what
 * `backend/api/routers/messages.py` returns; keeping the names identical is
 * what makes a drift between the two obvious in review rather than at runtime.
 *
 * Note what a MessageSummary does NOT carry: bodies beyond a short preview,
 * attachment payloads, or participant lists. A fifty-row inbox that loads fifty
 * workbooks to draw itself is a page nobody waits for, so the list endpoint
 * returns counts and kinds and the thread endpoint returns the rest.
 */

export type SenderType = "USER" | "SYSTEM";
export type RequestType = "fyi" | "review" | "action";
export type RequestStatus = "open" | "in_review" | "responded" | "closed";
export type AttachmentType = "investigation" | "analysis" | "report" | "file";
export type Mailbox = "inbox" | "sent" | "drafts" | "archived" | "action";

export interface Person {
  id: number;
  username: string;
  name: string;
  email: string;
  job_title: string;
  department: string;
  team: string;
  role: string;
  is_active: boolean;
}

export interface MessageSender {
  /** SYSTEM messages have no user behind them — `user` is null, by design. */
  type: SenderType;
  name: string;
  user: Person | null;
}

export interface MessageAttachment {
  id: number;
  type: AttachmentType;
  object_id: string;
  /** What the object was when it was sent, not what it is now. */
  object_version: string;
  label: string;
  meta: Record<string, unknown>;
  file?: {
    artifact_id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
    sha256: string;
  };
}

export interface MessageAction {
  action: string;
  label: string;
  href: string;
  context?: Record<string, unknown>;
}

export interface Message {
  id: number;
  thread_id: number;
  parent_id: number | null;
  sender: MessageSender;
  body: string;
  status: "draft" | "sent";
  request_type: RequestType;
  request_status: RequestStatus | null;
  priority: string;
  due_at: string | null;
  actions: MessageAction[];
  context: Record<string, unknown>;
  created_at: string | null;
  sent_at: string | null;
  recipients: Person[];
  attachments: MessageAttachment[];
}

export interface MessageThread {
  id: number;
  subject: string;
  origin: SenderType;
  created_at: string | null;
  last_message_at: string | null;
  participants: Person[];
  messages: Message[];
  read_at: string | null;
  archived: boolean;
}

export interface MessageSummary {
  thread_id: number;
  subject: string;
  origin: SenderType;
  sender: MessageSender;
  preview: string;
  message_count: number;
  attachment_count: number;
  attachment_types: AttachmentType[];
  request_type: RequestType;
  request_status: RequestStatus | null;
  priority: string;
  due_at: string | null;
  last_message_at: string | null;
  unread: boolean;
  archived: boolean;
}

export interface SentSummary {
  message_id: number;
  thread_id: number;
  subject: string;
  preview: string;
  recipients: Person[];
  attachment_count: number;
  attachment_types: AttachmentType[];
  request_type: RequestType;
  request_status: RequestStatus | null;
  sent_at: string | null;
}

export interface DraftSummary {
  message_id: number;
  thread_id: number;
  subject: string;
  preview: string;
  attachment_count: number;
  created_at: string | null;
}

export interface MailboxPage<T> {
  box: Mailbox;
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

/**
 * The one personal-attention summary. Every badge, tab and tile reads it.
 *
 * Each field is a backend predicate, not a client-side filter — see
 * `attention_summary` in the collaboration service for the table of them.
 */
export interface MessageCounts {
  inbox: number;
  unread: number;
  archived: number;
  sent: number;
  drafts: number;
  action_required: number;
  shared_with_me: number;
}

/** One user's operational counts, as the admin Workflow overview shows them. */
export interface UserActivity {
  received: number;
  unread: number;
  read: number;
  sent: number;
  drafts: number;
  action_required: number;
  overdue: number;
  awaiting_others: number;
  shared_with_them: number;
  shared_by_them: number;
}

export interface WorkflowUserRow extends Person {
  status: string;
  last_active: string | null;
  deactivated_at: string | null;
  activity: UserActivity;
}

export interface WorkflowOverview {
  total: number;
  limit: number;
  offset: number;
  users: WorkflowUserRow[];
  totals: {
    users: number;
    active: number;
    suspended: number;
    messages_sent: number;
    unread: number;
    action_required: number;
    overdue: number;
    shares: number;
  };
}

export interface WorkflowUserProfile extends WorkflowUserRow {
  recent_activity: { action: string; object_type: string; at: string | null }[];
}

/** A governed object the signed-in user may attach, offered as a card. */
export interface ShareableObject {
  object_type: string;
  object_id: string;
  object_version: string;
  label: string;
  meta: Record<string, unknown>;
}

export interface SharedObject {
  object_type: string;
  object_id: string;
  object_version: string;
  label: string;
  meta: Record<string, unknown>;
  shared_by: string;
  shared_at: string | null;
}

export interface RequestEvent {
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  actor: string;
  note: string;
  at: string | null;
}

export interface AttachmentSpec {
  type: AttachmentType;
  object_id?: string;
  artifact_id?: number;
  label?: string;
}

export interface SendMessageInput {
  to: number[];
  cc?: number[];
  subject?: string;
  body?: string;
  attachments?: AttachmentSpec[];
  request_type?: RequestType;
  priority?: string;
  due_at?: string | null;
  thread_id?: number | null;
  draft_id?: number | null;
  /**
   * Generated once per press of Send. Sending it twice — a double-click, or a
   * request the browser retried after a timeout it never saw the answer to —
   * returns the first message instead of putting a second copy in somebody's
   * inbox.
   */
  client_token?: string;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
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
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
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
    // §9. This used to read `Request failed with status ${response.status}.`
    // and a real acceptance run put "Request failed with status 500." in front
    // of a credit officer. The transport is not the product: a status code
    // names how the message travelled, not what went wrong or what to do
    // about it. The server now returns a written sentence for every status —
    // see backend/api/failures.BY_STATUS — and this is the sentence for the
    // case where even that could not be read, which means the server was not
    // reached at all.
    let message =
      "CreditProbe could not complete that request. Nothing was computed, so " +
      "no figure you are looking at has changed. Try again in a moment.";
    let detail: Record<string, unknown> = { status: response.status };
    try {
      const body = await response.json();
      // Our own envelope is flat: { error, message, detail }. FastAPI's
      // default for a bare HTTPException is { detail: "..." } — a STRING, so
      // `payload.message` was undefined and the fallback above ran. The
      // server no longer emits that shape, and this still reads it, because a
      // route added tomorrow may.
      const payload =
        body.detail && typeof body.detail === "object" ? body.detail : body;
      code = payload.error ?? code;
      if (typeof payload.message === "string" && payload.message.trim()) {
        message = payload.message;
      } else if (typeof body.detail === "string" && body.detail.includes(" ")) {
        message = body.detail;
      }
      detail = { status: response.status, ...payload };
    } catch {
      /* the body was not JSON — the governed sentence above stands */
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

async function download(
  path: string,
  fallback: string,
  timeoutMs = 180_000,
): Promise<DownloadedFile> {
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
    const aborted =
      error instanceof DOMException && error.name === "AbortError";
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
      const payload =
        body.detail && typeof body.detail === "object" ? body.detail : body;
      code = payload.error ?? code;
      message = payload.message ?? message;
      detail = payload;
    } catch {
      /* a non-JSON error body: keep the fallback message */
    }
    throw new ApiError(message, response.status, code, detail);
  }

  return {
    blob: await response.blob(),
    filename: filenameFrom(
      response.headers.get("content-disposition"),
      fallback,
    ),
  };
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
export type ProjectStatus =
  | "draft"
  | "active"
  | "in_review"
  | "completed"
  | "archived";

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
// ---- early warning: the governed signal taxonomy (§20, §23-§28) ----
//
// A different object from `EarlyWarningScores`. That one is a fitted model
// producing a probability; this one is a list of named conditions with
// thresholds somebody owns. They answer different questions and the product
// deliberately shows both rather than folding one into the other.

export interface SignalObservation {
  signal: string;
  family: string;
  family_label: string;
  label: string;
  fired: boolean;
  lifecycle: string;
  lifecycle_means: string;
  severity: string;
  value: unknown;
  previous: unknown;
  movement: number | null;
  threshold: unknown;
  threshold_version: string;
  threshold_owner: string;
  dataset: string;
  field: string;
  test: string;
  /** What `value`, `previous` and `threshold` are denominated in. R2 §3. */
  unit: string;
  /** The currency a money-denominated value is kept in. */
  currency: string;
  period: string;
  previous_period: string;
  booked_accounting: boolean;
  unavailable: string;
  means: string;
  available: boolean;
  /** §11H. What the BORROWER is doing on this condition, in credit language. */
  state: string;
}

/** §11G. How serious the borrower's position is, and why. */
export interface RiskAssessment {
  level: string;
  means: string;
  reasons: { rule: string; says: string; pushes: string }[];
  mitigating: { rule: string; says: string; pushes: string }[];
  families: string[];
  family_labels: string[];
  /** Families carrying evidence OTHER than the ones the gravity sits in. */
  corroborating: string[];
  patterns: {
    key: string;
    label: string;
    means: string;
    fired: boolean;
    matched: string[];
    corroborated: string[];
    untested: string[];
    why: string;
  }[];
  new: string[];
  persistent: string[];
  worsening: string[];
  resolved: string[];
  improving: string[];
  tac: Record<string, number>;
  primary_concern: string;
  why_now: string;
  owner: string;
  version: string;
}

export interface SignalStanding {
  version: string;
  borrower_id: string;
  period: string;
  sentence: string;
  // Six transparent measures and deliberately no score. §25.
  breadth: number;
  severity: string;
  persistence: number;
  worsening: number;
  improving: number;
  agreement: string[];
  conflict: string[];
  booked_accounting_signals: string[];
  // R2 §25. Severity is about the worst RULE; priority is about the BORROWER,
  // and it is the one an officer working down a list is asking.
  priority: string;
  priority_label: string;
  priority_means: string;
  priority_because: string[];
  priority_reasons: { rule: string; level: string; says: string }[];
  priority_owner: string;
  priority_version: string;
  /** Drawn exposure, in the millions the book is kept in. */
  exposure: number | null;
  material: boolean;
  fired: SignalObservation[];
  cured: SignalObservation[];
  untested: SignalObservation[];
  families: Record<string, string[]>;
  /** §11G. Distinct from severity (about the rule) and priority (about what to do). */
  assessment: RiskAssessment;
  risk_level: string;
}

/** §11C/§11D. One borrower, four layers, every governed condition. */
export interface ScorecardComponent {
  signal: string;
  label: string;
  family: string;
  family_label: string;
  layer: string;
  layer_name: string;
  current: number | string | null;
  previous: number | string | null;
  movement: number | null;
  threshold: number | string | null;
  /** The threshold as a phrase: "at or below 5%", not a signed number. */
  threshold_reads: string;
  unit: string;
  currency: string;
  status: string;
  status_means: string;
  severity: string;
  persistence: string;
  detection: string;
  detection_letter: string;
  detection_means: string;
  state: string;
  state_means: string;
  means: string;
  available: boolean;
  unavailable: string;
}

export interface ScorecardLayer {
  layer: string;
  number: number;
  name: string;
  watches: string;
  matters: string;
  gap: string;
  over: number;
  tested: number;
  untested: number;
  severity: string;
  sentence: string;
  components: ScorecardComponent[];
}

export interface BorrowerScorecard {
  version: string;
  taxonomy_version: string;
  owner: string;
  borrower_id: string;
  period: string;
  currency: string;
  assessment: RiskAssessment;
  risk_level: string;
  /** §11J. Borrower 360, at the borrower AND the reporting date. */
  borrower_360: {
    customer_id: string;
    reporting_period: string;
    href: string;
    label: string;
  };
  columns: string[];
  layers: ScorecardLayer[];
  statement: string;
}

/** §11I. What this borrower has been doing, quarter by quarter. */
export interface BorrowerTimeline {
  version: string;
  borrower_id: string;
  periods: string[];
  entries: {
    period: string;
    on_book: boolean;
    risk_level: string;
    risk_means?: string;
    fired: number;
    families: number;
    new?: number;
    resolved?: number;
    worsening?: number;
    primary_concern: string;
    why_now: string;
    priority?: string;
    sentence: string;
    first?: boolean;
  }[];
  level_changes: number;
  statement: string;
}

/** The Early Warning landing page. R2 §10. */
export interface EarlyWarningDashboard {
  version: string;
  period: string;
  previous_period: string;
  evaluated: number;
  currency: string;
  measures: DashboardMeasure[];
  hotspots: {
    sector: string;
    borrowers: number;
    act_now: number;
    review: number;
    exposure: number;
  }[];
  changes: {
    borrower_id: string;
    borrower_name: string;
    sector: string;
    priority: string;
    priority_label: string;
    exposure: number | null;
    what_changed: string;
    because: string[];
  }[];
  diagnostics: {
    signal: string;
    label: string;
    borrowers: number;
    share_of_book_pct: number;
  }[];
  priority_policy: {
    owner: string;
    version: string;
    levels: { priority: string; label: string; means: string }[];
    material_exposure: number;
  };
  /** §11B/§11G. The book split by overall risk, and the rule that split it. */
  risk_levels: {
    owner: string;
    version: string;
    rule: Record<string, string>;
    levels: {
      level: string;
      means: string;
      borrowers: number;
      share: number;
      exposure: number;
      names: string[];
    }[];
    statement: string;
  };
}

export interface DashboardMeasure {
  key: string;
  label: string;
  means: string;
  value: number | null;
  unit: string;
  currency: string;
  available: boolean;
  /** Why it could not be computed. A measure is never reported as zero. §7. */
  unavailable: string;
  borrowers: string[];
  borrower_count: number;
}

export interface SignalHeadline {
  borrowers: number;
  with_a_new_signal: number;
  worsening: number;
  persisting: number;
  cured: number;
  severe: number;
  multi_family: number;
  booked_stage_2_or_worse: number;
  covenant_pressure: number;
  collateral_pressure: number;
  means: Record<string, string>;
}

export interface SignalPortfolio {
  version: string;
  taxonomy_version?: string;
  period: string;
  previous_period?: string;
  evaluated: number;
  with_signals?: number;
  returned?: number;
  borrowers: SignalStanding[];
  headline?: SignalHeadline;
  signal_count?: number;
  unavailable?: { family: string; family_label: string; means: string }[];
  origin?: string;
  note?: string;
}

export interface SignalTaxonomy {
  version: string;
  owner: string;
  families: {
    id: string;
    label: string;
    means: string;
    signals: SignalDefinition[];
    unavailable: { family: string; family_label: string; means: string }[];
  }[];
  signals: SignalDefinition[];
  unavailable: { family: string; family_label: string; means: string }[];
  signal_count: number;
  severities: string[];
}

export interface SignalDefinition {
  key: string;
  family: string;
  family_label: string;
  label: string;
  means: string;
  dataset: string;
  field: string;
  test: string;
  threshold: unknown;
  against: string;
  severity: string;
  booked_accounting: boolean;
  owner: string;
  version: string;
  sentence: string;
}

export interface ReviewPreview {
  review_version?: string;
  period: string;
  previous_period?: string;
  evaluated: number;
  with_signals?: number;
  qualified: number;
  returned?: number;
  below_the_limit?: number;
  rules: Record<string, number>;
  rule_meanings?: Record<string, string>;
  would_raise: {
    borrower_id: string;
    rule: string;
    why: string;
    standing: SignalStanding;
  }[];
  note?: string;
}

export interface ReviewOutcome {
  review_version: string;
  taxonomy_version: string;
  signals_version: string;
  period: string;
  previous_period: string;
  evaluated: number;
  with_signals: number;
  qualified: number;
  opened: number;
  refreshed: number;
  moved_to_monitoring: number;
  not_opened: number;
  budget: number;
  rules: Record<string, number>;
  bands: Record<string, number>;
  case_ids: number[];
  sentence: string;
}

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
  family_contributions: {
    family: string;
    label: string;
    contribution: number;
  }[];
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
  actions_taken: {
    action: string;
    investigation_id?: number;
    detail?: string;
  }[];
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

// =================================================== What-If / scenarios

export interface WhatIfShock {
  kind: string;
  magnitude: number;
  unit: string;
  target: string;
  description: string;
}

export interface WhatIfScenario {
  key: string;
  name: string;
  severity: string;
  rationale: string;
  period: string;
  description: string;
  shocks: WhatIfShock[];
  population: {
    sectors: string[];
    rating_bands: string[];
    stages: number[];
    borrower_ids: string[];
    watchlist_only: boolean;
    description: string;
  };
  assumptions: {
    reevaluate_sicr: boolean;
    rating_deterioration_sicr: boolean;
    rating_sicr_notches: number;
    collateral_to_lgd: boolean;
  };
}

export interface WhatIfSummary {
  scenario: string;
  population: string;
  borrowers: number;
  period: string;
  currency: string;
  baseline_ead: number;
  stressed_ead: number;
  baseline_ecl: number;
  stressed_ecl: number;
  incremental_ecl: number;
  incremental_ecl_pct: number;
  baseline_coverage_pct: number;
  stressed_coverage_pct: number;
  stage_2_migrations: number;
  stage_3_migrations: number;
  stage_2_baseline: number;
  stage_2_stressed: number;
  borrowers_with_higher_ecl: number;
  downgraded: number;
  collateral_shortfalls: number;
  covenant_breaches: number;
}

export interface WhatIfStep {
  step: string;
  detail: string;
  affected: number;
}

export interface WhatIfSensitivityRow {
  variable: string;
  shock: string;
  scope: string;
  sector_sensitivity: number;
  pd_effect_pct: number;
  lgd_effect_pp: number;
  borrowers: number;
}

export interface WhatIfRun {
  scenario: WhatIfScenario;
  period: string;
  currency: string;
  summary: WhatIfSummary;
  population: number;
  steps: WhatIfStep[];
  sensitivity: WhatIfSensitivityRow[];
  warnings: string[];
  borrowers: { columns: string[]; rows: (string | number)[][] };
  detail: {
    by_sector: Record<string, unknown>[];
    by_rating: Record<string, unknown>[];
    top_contributors: Record<string, unknown>[];
    masterscale: Record<string, unknown>[];
    ifrs9_policy: Record<string, unknown>;
  };
  trace: { nodes: unknown[]; edges: unknown[] };
}

export interface WhatIfConfiguration {
  masterscale: {
    owner: string;
    version: string;
    grades: {
      grade: string;
      pd_floor_pct: number;
      pd_ceiling_pct: number;
      masterscale_pd_pct: number;
    }[];
    bands: Record<string, string[]>;
  };
  sensitivity: {
    owner: string;
    version: string;
    effective_date: string;
    statement: string;
    sectors: string[];
    variables: {
      key: string;
      variable: string;
      unit: string;
      shock_unit: string;
      pd_effect_pct_per_step: number;
      lgd_effect_pp_per_step: number;
      financial_effects: Record<string, number>;
      sector_sensitivity: Record<string, number>;
      basis: string;
      note: string;
    }[];
  };
  ifrs9_policy: {
    owner: string;
    version: string;
    sicr_triggers: { trigger: string; rule: string }[];
    default_presumption: string;
    measurement: Record<string, string>;
    lifetime_horizon_years: number;
    scenario_weights: { scenario: string; weight: number; ecl_multiplier: number }[];
    weighted_factor: number;
  };
  scenarios: WhatIfScenario[];
  currency: string;
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
  /**
   * What this person DOES, beside `role`, which is what they MAY do.
   *
   * A directory in which four people are all "ANALYST" cannot tell a sender
   * which of them owns the shipping book, and sending a review request to the
   * wrong one of them is a real cost of showing only the permission.
   */
  job_title: string;
  department: string;
  last_login_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  /** When the account was suspended. Null while it is active. */
  deactivated_at: string | null;
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

/**
 * What a reader has chosen about how the product looks to them.
 *
 * Presentation only: the greeting name is what the Cockpit prints, and the
 * account, role, permissions and audit identity are untouched by it.
 */
export interface Preferences {
  greeting_name: string;
  greeting_name_is_default: boolean;
  default_greeting_name: string;
  max_length: number;
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
  signOut: () =>
    request<{ signed_out: boolean }>("/auth/logout", { method: "POST" }),

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
    jobTitle?: string;
    department?: string;
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
        job_title: payload.jobTitle ?? "",
        department: payload.department ?? "",
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
      jobTitle?: string;
      department?: string;
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
        job_title: payload.jobTitle ?? null,
        department: payload.department ?? null,
        is_active: payload.isActive ?? null,
      }),
    }),
  setUserPassword: (id: number, password: string) =>
    request<{ user_id: number; password_set: boolean }>(
      `/users/${id}/password`,
      {
        method: "POST",
        body: JSON.stringify({ password }),
      },
    ),

  // ---- system ----
  health: (timeoutMs?: number) =>
    request<HealthResponse>("/health", { timeoutMs: timeoutMs ?? 8_000 }),
  /**
   * Whether this deployment is a demonstration. The backend is the single
   * authority: a build-time flag in the browser bundle can disagree with the
   * container it is talking to, and the direction that disagreement runs in
   * is the difference between "labelled synthetic" and "labelled synthetic
   * when it is not".
   */
  demoPosture: () =>
    request<DemoPostureResponse>("/demo", { timeoutMs: 8_000 }),
  catalog: () => request<CatalogResponse>("/catalog"),

  // ---- engine ----
  analyses: (opts: { category?: string; certifiedOnly?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.category) q.set("category", opts.category);
    if (opts.certifiedOnly) q.set("certified_only", "true");
    const qs = q.toString();
    return request<AnalysisLibraryResponse>(
      `/engine/analyses${qs ? `?${qs}` : ""}`,
    );
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
    request<PeriodsResponse>(
      `/engine/periods?dataset=${encodeURIComponent(dataset)}`,
    ),
  dimensions: (dataset = "portfolio_facility", period?: string) => {
    const q = new URLSearchParams({ dataset });
    if (period) q.set("period", period);
    return request<DimensionsResponse>(`/engine/dimensions?${q}`);
  },

  // ---- trace ----
  trace: (runId: number, version?: number) =>
    request<StoredTrace>(
      `/trace/${runId}${version ? `?version=${version}` : ""}`,
    ),

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
  earlyWarningStory: (borrowerId: string, period?: string) =>
    request<BorrowerStory>(
      `/early-warning/story/${encodeURIComponent(borrowerId)}` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  /** How this reader wants the product to look. Presentation only. */
  preferences: () => request<Preferences>("/preferences"),
  setGreetingName: (greeting_name: string) =>
    request<Preferences>("/preferences/greeting-name", {
      method: "PUT",
      body: JSON.stringify({ greeting_name }),
    }),
  resetGreetingName: () =>
    request<Preferences>("/preferences/greeting-name", { method: "DELETE" }),
  askMode: () => request<PlannerMode>("/ask/mode"),
  askCost: (limit = 50) => request<CostTrace>(`/ask/cost?limit=${limit}`),
  askSuggestions: () =>
    request<{ questions: { question: string; note: string }[] }>(
      "/ask/suggestions",
    ),

  // ---------------------------------------------------------------- messages
  messageCounts: () => request<MessageCounts>("/messages/counts"),
  messageDirectory: (q = "", limit = 50) =>
    request<{ users: Person[] }>(
      `/messages/directory?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  mailbox: (
    box: Mailbox = "inbox",
    opts: {
      limit?: number;
      offset?: number;
      q?: string;
      unread?: boolean;
      attachmentType?: string;
    } = {},
  ) => {
    const p = new URLSearchParams({ box });
    if (opts.limit) p.set("limit", String(opts.limit));
    if (opts.offset) p.set("offset", String(opts.offset));
    if (opts.q) p.set("q", opts.q);
    if (opts.unread) p.set("unread", "true");
    if (opts.attachmentType) p.set("attachment_type", opts.attachmentType);
    return request<MailboxPage<MessageSummary | SentSummary | DraftSummary>>(
      `/messages?${p.toString()}`,
    );
  },
  messageThread: (threadId: number) =>
    request<MessageThread>(`/messages/threads/${threadId}`),
  shareableObjects: (objectType: string, q = "", limit = 20) =>
    request<{ items: ShareableObject[] }>(
      `/messages/shareable?object_type=${encodeURIComponent(objectType)}` +
        `&q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  workflowOverview: (opts: { q?: string; limit?: number } = {}) =>
    request<WorkflowOverview>(
      `/messages/admin/overview?q=${encodeURIComponent(opts.q ?? "")}` +
        `&limit=${opts.limit ?? 100}`,
    ),
  workflowUserProfile: (userId: number) =>
    request<WorkflowUserProfile>(`/messages/admin/users/${userId}`),
  sharedWithMe: (limit = 25) =>
    request<{ items: SharedObject[] }>(
      `/messages/shared-with-me?limit=${limit}`,
    ),
  requestHistory: (messageId: number) =>
    request<{ events: RequestEvent[] }>(
      `/messages/requests/${messageId}/history`,
    ),
  createDraft: (body: { subject?: string; body?: string; thread_id?: number }) =>
    request<{ message_id: number; thread_id: number; subject: string }>(
      "/messages/drafts",
      { method: "POST", body: JSON.stringify(body) },
    ),
  updateDraft: (
    messageId: number,
    body: { subject?: string; body?: string; attachments?: AttachmentSpec[] },
  ) =>
    request<{ message_id: number; thread_id: number }>(
      `/messages/drafts/${messageId}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  sendMessage: (body: SendMessageInput) =>
    request<{
      message_id: number;
      thread_id: number;
      subject: string;
      recipients: number[];
      /** True when this was a replay of a send that had already happened. */
      duplicate?: boolean;
    }>("/messages/send", { method: "POST", body: JSON.stringify(body) }),
  replyToThread: (
    threadId: number,
    body: {
      body: string;
      attachments?: AttachmentSpec[];
      request_type?: RequestType;
    },
  ) =>
    request<{ message_id: number; thread_id: number }>(
      `/messages/threads/${threadId}/reply`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  markThreadRead: (threadId: number, read = true) =>
    request<{ thread_id: number; read: boolean }>(
      `/messages/threads/${threadId}/read`,
      { method: "POST", body: JSON.stringify({ read }) },
    ),
  // `archiveThread` already means "archive an investigation" below. Two
  // different objects called a thread is a naming collision the product
  // inherited; the messaging side takes the longer name rather than shadowing
  // the older one.
  archiveMessageThread: (threadId: number, archived = true) =>
    request<{ thread_id: number; archived: boolean }>(
      `/messages/threads/${threadId}/archive`,
      { method: "POST", body: JSON.stringify({ archived }) },
    ),
  changeRequestStatus: (messageId: number, status: RequestStatus, note = "") =>
    request<{ message_id: number; request_status: RequestStatus }>(
      `/messages/requests/${messageId}/status`,
      { method: "POST", body: JSON.stringify({ status, note }) },
    ),
  uploadAttachment: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{
      artifact_id: number;
      filename: string;
      size_bytes: number;
      sha256: string;
    }>("/messages/artifacts", { method: "POST", body: form, rawBody: true });
  },
  /**
   * Where the browser fetches an attached file from.
   *
   * A URL rather than a fetch: the download is authorized per request by the
   * backend against thread participation, so letting the browser navigate to
   * it keeps the file name, the content type and the save dialog native.
   */
  attachmentUrl: (artifactId: number) =>
    `${API_BASE_URL}${API_PREFIX}/messages/artifacts/${artifactId}`,
  briefing: () => request<Briefing>("/ask/briefing", { timeoutMs: 60_000 }),
  recentInvestigations: (limit = 8) =>
    request<{ investigations: RecentInvestigation[] }>(
      `/ask/recent?limit=${limit}`,
    ),
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
  traceVersions: (runId: number) =>
    request<VersionsResponse>(`/trace/${runId}/versions`),
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
  dataset: (name: string) =>
    request<DatasetDetail>(`/data-builder/datasets/${name}`),
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
    request<{
      dataset: string;
      lifecycle: Lifecycle;
      mappings: FieldMappingRow[];
    }>(`/data-builder/datasets/${name}/mappings`, {
      method: "PUT",
      body: JSON.stringify({ mappings }),
    }),
  upsertField: (
    name: string,
    field: Partial<DictionaryField> & { name: string },
  ) =>
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
  addRelationship: (
    payload: Omit<RelationshipRow, "id" | "name"> & { name?: string },
  ) =>
    request<RelationshipRow>("/data-builder/relationships", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  validate: (name: string) =>
    request<ValidationReport>(`/data-builder/datasets/${name}/validate`, {
      method: "POST",
    }),
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
  deleteLens: (id: number) =>
    request<void>(`/lenses/${id}`, { method: "DELETE" }),

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

  // ---- What-If / scenarios ----
  whatIfConfiguration: () =>
    request<WhatIfConfiguration>("/whatif/configuration"),
  whatIfScenarios: () =>
    request<{ scenarios: WhatIfScenario[]; count: number }>("/whatif/scenarios"),
  runWhatIf: (payload: {
    scenario?: string;
    name?: string;
    shocks?: { kind: string; magnitude: number; unit?: string; target?: string }[];
    population?: {
      sectors?: string[];
      rating_bands?: string[];
      stages?: number[];
      borrower_ids?: string[];
      watchlist_only?: boolean;
    };
    assumptions?: {
      reevaluate_sicr?: boolean;
      rating_deterioration_sicr?: boolean;
      rating_sicr_notches?: number;
      collateral_to_lgd?: boolean;
    };
    period?: string;
    limit?: number;
  }) =>
    request<WhatIfRun>("/whatif/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  askWhatIf: (question: string, limit = 100) =>
    request<WhatIfRun & { is_scenario: boolean; message?: string; unread?: string[] }>(
      "/whatif/ask",
      { method: "POST", body: JSON.stringify({ question, limit }) },
    ),
  compareWhatIf: (keys: string[]) =>
    request<{
      columns: string[];
      rows: (string | number)[][];
      currency: string;
      scenarios: WhatIfScenario[];
    }>("/whatif/compare", { method: "POST", body: JSON.stringify(keys) }),

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
  earlyWarningTaxonomy: () =>
    request<SignalTaxonomy>("/early-warning/taxonomy"),
  earlyWarningSignals: (opts: { period?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.period) query.set("period", opts.period);
    if (opts.limit) query.set("limit", String(opts.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<SignalPortfolio>(`/early-warning/signals${suffix}`, {
      timeoutMs: 90_000,
    });
  },
  /** The Early Warning landing page, in business terms. R2 §10. */
  earlyWarningDashboard: (period?: string) =>
    request<EarlyWarningDashboard>(
      `/early-warning/dashboard${period ? `?period=${encodeURIComponent(period)}` : ""}`,
      { timeoutMs: 90_000 },
    ),
  borrowerScorecard: (borrowerId: string, period?: string) =>
    request<BorrowerScorecard>(
      `/early-warning/scorecard/${encodeURIComponent(borrowerId)}` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
      { timeoutMs: 60_000 },
    ),
  borrowerTimeline: (borrowerId: string, period?: string, limit = 8) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (period) query.set("period", period);
    return request<BorrowerTimeline>(
      `/early-warning/timeline/${encodeURIComponent(borrowerId)}?${query}`,
      { timeoutMs: 90_000 },
    );
  },
  /** §11L. The two workbook URLs, for a link the browser downloads. */
  borrowerScorecardWorkbookUrl: (borrowerId: string, period?: string) =>
    `${API_BASE_URL}${API_PREFIX}/early-warning/scorecard/` +
    `${encodeURIComponent(borrowerId)}` +
    `/workbook${period ? `?period=${encodeURIComponent(period)}` : ""}`,
  watchlistWorkbookUrl: (period?: string) =>
    `${API_BASE_URL}${API_PREFIX}/early-warning/watchlist/workbook` +
    (period ? `?period=${encodeURIComponent(period)}` : ""),
  borrowerSignals: (borrowerId: string, period?: string) =>
    request<SignalStanding>(
      `/early-warning/signals/${encodeURIComponent(borrowerId)}` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  earlyWarningReviewPreview: (opts: { period?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (opts.period) query.set("period", opts.period);
    if (opts.limit) query.set("limit", String(opts.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<ReviewPreview>(`/early-warning/review/preview${suffix}`, {
      timeoutMs: 90_000,
    });
  },
  runEarlyWarningReview: (payload: { period?: string; budget?: number } = {}) =>
    request<ReviewOutcome>("/early-warning/review", {
      method: "POST",
      body: JSON.stringify({
        period: payload.period ?? "",
        budget: payload.budget ?? 50,
      }),
      timeoutMs: 180_000,
    }),
  earlyWarning: () => request<EarlyWarningOverview>("/early-warning"),
  earlyWarningMethodology: () =>
    request<EarlyWarningMethodology>("/early-warning/methodology"),
  earlyWarningScores: (
    targetId: string,
    opts: { period?: string; limit?: number } = {},
  ) => {
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
    return request<{
      projects: ProjectRow[];
      statuses: Record<string, string>;
    }>(`/projects${suffix}`);
  },
  project: (id: number) => request<ProjectRow>(`/projects/${id}`),
  projectContents: (id: number) =>
    request<ProjectContents>(`/projects/${id}/contents`),
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
    if (opts.projectId !== undefined)
      query.set("project_id", String(opts.projectId));
    if (opts.scope) query.set("scope", opts.scope);
    if (opts.includeArchived) query.set("include_archived", "true");
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ investigations: ThreadSummary[] }>(
      `/investigations${suffix}`,
    );
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
  copyThread: (
    id: number,
    opts: { projectId?: number | null; title?: string } = {},
  ) =>
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
    opts: {
      projectId?: number;
      investigationId?: number;
      analysisId?: string;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (opts.projectId !== undefined)
      query.set("project_id", String(opts.projectId));
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
    request<{ analyses: SavedAnalysis[]; count: number }>(
      "/analyses/from-message",
      {
        method: "POST",
        body: JSON.stringify({
          investigation_id: payload.investigationId,
          sequence: payload.sequence,
          project_id: payload.projectId ?? null,
          title: payload.title ?? "",
          note: payload.note ?? "",
        }),
      },
    ),
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
  savedInvestigations: (
    params: { projectId?: number; ownerId?: number } = {},
  ) => {
    const query = new URLSearchParams();
    if (params.projectId !== undefined)
      query.set("project_id", String(params.projectId));
    if (params.ownerId !== undefined)
      query.set("owner_id", String(params.ownerId));
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
    request<WorkflowDetail>(`/workspace/workflow/${id}/opened`, {
      method: "POST",
    }),
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
  workflowItem: (id: number) =>
    request<WorkflowDetail>(`/workspace/workflow/${id}`),
  moveWorkflow: (id: number, toState: string, comment = "") =>
    request<WorkflowDetail>(`/workspace/workflow/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ to_state: toState, comment }),
    }),
  comments: (objectType: string, objectId: string) =>
    request<{ comments: CommentRow[] }>(
      `/workspace/comments/${objectType}/${objectId}`,
    ),
  addComment: (
    objectType: string,
    objectId: string,
    body: string,
    notifyUserId?: number,
  ) =>
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
  datasetFamilies: () =>
    request<{ families: DatasetFamily[] }>("/data-builder/families"),
  datasetUsedBy: (name: string) =>
    request<UsedBy>(`/data-builder/datasets/${name}/used-by`),
  syncBundled: () =>
    request<{ synced: string[]; skipped: string[]; message: string }>(
      "/data-builder/sync-bundled",
      { method: "POST" },
    ),
  setDatasetOrigin: (name: string, origin: string) =>
    request<{ dataset: string; origin: string }>(
      `/data-builder/datasets/${name}/origin`,
      {
        method: "POST",
        body: JSON.stringify({ origin }),
      },
    ),
  setAuthoritative: (name: string, purposes: string[]) =>
    request<{
      dataset: string;
      authoritative_for: string[];
      displaced_demo_datasets: string[];
    }>(`/data-builder/datasets/${name}/authoritative`, {
      method: "POST",
      body: JSON.stringify({ purposes }),
    }),
  harmonise: (name: string) =>
    request<Harmonisation>(`/data-builder/datasets/${name}/harmonise`),
  acceptHarmonisation: (name: string, accepted: Record<string, string>) =>
    request<{ dataset: string; accepted: number; still_unmapped: number }>(
      `/data-builder/datasets/${name}/harmonise/accept`,
      { method: "POST", body: JSON.stringify({ accepted }) },
    ),

  // ---- relationships ----
  relationshipMap: () =>
    request<RelationshipMap>("/data-builder/relationships/map"),
  seedRelationships: () =>
    request<{ declared: string[]; skipped: string[]; total: number }>(
      "/data-builder/relationships/seed",
      { method: "POST" },
    ),
  relationship: (id: number) =>
    request<RelationshipDetail>(`/data-builder/relationships/${id}`),
  proposeRelationships: (dataset: string) =>
    request<RelationshipProposals>(
      `/data-builder/relationships/propose?dataset=${encodeURIComponent(dataset)}`,
      { timeoutMs: 120_000 },
    ),
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
      },
    ),
  validateRelationship: (id: number, period = "") =>
    request<{ relationship: RelationshipEdge; report: RelationshipValidation }>(
      `/data-builder/relationships/${id}/validate${period ? `?period=${encodeURIComponent(period)}` : ""}`,
      { method: "POST", timeoutMs: 120_000 },
    ),
  setRelationshipLifecycle: (id: number, lifecycle: string, note = "") =>
    request<{
      relationship: RelationshipEdge;
      versions: RelationshipVersionEntry[];
    }>(`/data-builder/relationships/${id}/lifecycle`, {
      method: "POST",
      body: JSON.stringify({ lifecycle, note }),
    }),

  // ---- the data inbox ----
  inbox: (status = "") =>
    request<InboxListing>(
      `/data-builder/inbox${status ? `?status=${status}` : ""}`,
    ),
  inboxItem: (id: number) => request<InboxItem>(`/data-builder/inbox/${id}`),
  receiveFile: (
    file: File,
    options: { publish?: boolean; sheetName?: string } = {},
  ) => {
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
  resolveInboxItem: (
    id: number,
    action: "publish" | "reject",
    note: string,
    dataset = "",
  ) =>
    request<InboxItem>(`/data-builder/inbox/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, note, dataset }),
      timeoutMs: 120_000,
    }),

  // ---- Analysis Studio ----
  studioLibrary: (
    params: {
      q?: string;
      category?: string;
      lifecycle?: string;
      certifiedOnly?: boolean;
      runnableOnly?: boolean;
      limit?: number;
    } = {},
  ) => {
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
    request<{
      method: StudioMethod;
      forked_from: string;
      persisted: boolean;
      note: string;
    }>(`/studio/${encodeURIComponent(id)}/fork`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  studioEdit: (
    id: string,
    changes: Record<string, string>,
    changeNote: string,
  ) =>
    request<{ method: StudioMethod; changes: string[]; persisted: boolean }>(
      `/studio/${encodeURIComponent(id)}/edit`,
      {
        method: "POST",
        body: JSON.stringify({ changes, change_note: changeNote }),
      },
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

  // ---- the governed agentic layer ----
  //
  // `agenticLive` is polled while a question is in flight, so it is
  // deliberately the smallest call in this file: the stage, the officer, the
  // specialists and the elapsed time. The full run document is several
  // kilobytes and none of it is on screen yet.
  agenticLive: (runId: number) =>
    request<OfficerLive>(`/agentic/runs/${runId}/live`, { timeoutMs: 8_000 }),
  agenticRun: (runId: number) =>
    request<AgentRunDetail>(`/agentic/runs/${runId}`),
  agenticRuns: (
    params: {
      limit?: number;
      status?: string;
      trigger?: string;
      mine?: boolean;
    } = {},
  ) =>
    request<{ runs: AgentRunSummary[] }>(
      `/agentic/runs?${new URLSearchParams({
        ...(params.limit ? { limit: String(params.limit) } : {}),
        ...(params.status ? { status_filter: params.status } : {}),
        ...(params.trigger ? { trigger: params.trigger } : {}),
        ...(params.mine ? { mine: "true" } : {}),
      })}`,
    ),
  cancelAgenticRun: (runId: number, reason = "") =>
    request<{ cancelled: boolean; message: string }>(
      `/agentic/runs/${runId}/cancel`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  retryAgenticRun: (runId: number, reason = "") =>
    request<{ job_id: number; queued: boolean; message: string }>(
      `/agentic/runs/${runId}/retry`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  agentRegistry: () => request<AgentCatalogue>("/agentic/agents"),
  agentTools: () =>
    request<{ tools: AgentTool[]; no_tool_exists: string[] }>("/agentic/tools"),
  agentSchedules: () =>
    request<{
      schedules: AgentSchedule[];
      triggers: { id: string; label: string }[];
    }>("/agentic/schedules"),
  setScheduleEnabled: (id: number, enabled: boolean) =>
    request<AgentSchedule>(`/agentic/schedules/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  runSchedule: (id: number) =>
    request<{ job_id: number; queued: boolean; message: string }>(
      `/agentic/schedules/${id}/run`,
      { method: "POST" },
    ),
  agentPolicies: () =>
    request<{ policies: AgentPolicy[] }>("/agentic/policies"),
  agentApprovals: () =>
    request<{ approvals: AgentApproval[]; role: string }>("/agentic/approvals"),
  decideApproval: (id: number, decision: string, note = "") =>
    request<AgentApproval>(`/agentic/approvals/${id}`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  agentEvents: (limit = 50) =>
    request<{ events: AgentEvent[]; kinds: { id: string; label: string }[] }>(
      `/agentic/events?limit=${limit}`,
    ),
  // §26, §27 — the coordination behind an analysis, where one produced it.
  // Returns `found: false` for the ordinary case: most analyses are one
  // person's question, answered by one specialist.
  agenticForAnalysis: (analysisRunId: number) =>
    request<AgentRunDetail & { found: boolean }>(
      `/agentic/for-analysis/${analysisRunId}`,
    ),
  agentEvaluations: (tier = "certification") =>
    request<AgentEvaluation>(`/agentic/evaluations?tier=${tier}`, {
      timeoutMs: 60_000,
    }),
  agentWorkers: () =>
    request<{
      workers: AgentWorker[];
      queue: Record<string, number>;
      alive: number;
    }>("/agentic/workers"),
  // §9's first reading, from the sentence alone. Costs nothing on the server —
  // regular expressions and arithmetic — so the officer indicator can appear
  // the instant Ask is pressed rather than when the answer arrives.
  previewOfficer: (question: string) =>
    request<OfficerPreview>("/agentic/officer", {
      method: "POST",
      body: JSON.stringify({ question }),
      timeoutMs: 8_000,
    }),
  agenticStages: () =>
    request<{
      sequence: string[];
      terminal: string[];
      stages: { id: string; label: string; caption: string }[];
    }>("/agentic/stages"),
  // A whole-book review takes minutes, so it is queued by default and the
  // Cockpit hears about it through the notification centre rather than by
  // holding a request open across a proxy that will time it out.
  startReview: (period = "", background = true) =>
    request<{
      queued: boolean;
      job_id?: number;
      run_id?: number;
      period: string;
      message?: string;
    }>("/agentic/review", {
      method: "POST",
      body: JSON.stringify({ period, background }),
      timeoutMs: background ? 30_000 : 600_000,
    }),

  // ---- risk cases ----
  riskCases: (
    params: {
      level?: string;
      period?: string;
      limit?: number;
      mine?: boolean;
    } = {},
  ) =>
    request<RiskCaseList>(
      `/risk-cases?${new URLSearchParams({
        ...(params.level ? { level: params.level } : {}),
        ...(params.period ? { period: params.period } : {}),
        ...(params.limit ? { limit: String(params.limit) } : {}),
        ...(params.mine ? { mine: "true" } : {}),
      })}`,
    ),
  riskCase: (id: number) => request<RiskCase>(`/risk-cases/${id}`),
  moveRiskCase: (id: number, status: string, note = "") =>
    request<RiskCase>(`/risk-cases/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, note }),
    }),
  assignRiskCase: (id: number, ownerId: number | null, note = "") =>
    request<RiskCase>(`/risk-cases/${id}/assign`, {
      method: "POST",
      body: JSON.stringify({ owner_id: ownerId, note }),
    }),
  snoozeRiskCase: (id: number, days: number, note = "") =>
    request<RiskCase>(`/risk-cases/${id}/snooze`, {
      method: "POST",
      body: JSON.stringify({ days, note }),
    }),
  dismissRiskCase: (id: number, reason: string) =>
    request<RiskCase>(`/risk-cases/${id}/dismiss`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  resolveRiskCase: (id: number, reason: string) =>
    request<RiskCase>(`/risk-cases/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  commentOnRiskCase: (id: number, body: string) =>
    request<RiskCase>(`/risk-cases/${id}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  investigateRiskCase: (id: number, projectId: number | null = null) =>
    request<{ investigation_id: number; created: boolean; question?: string }>(
      `/risk-cases/${id}/investigate`,
      {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
        timeoutMs: 60_000,
      },
    ),
  riskCaseToProject: (id: number, projectId: number | null, name = "") =>
    request<{ project_id: number; created: boolean }>(
      `/risk-cases/${id}/project`,
      { method: "POST", body: JSON.stringify({ project_id: projectId, name }) },
    ),
  sendRiskCaseForReview: (
    id: number,
    body: {
      recipients?: number[];
      teams?: number[];
      action?: string;
      message?: string;
      priority?: string;
      due_at?: string;
    },
  ) =>
    request<{ workflow_item_id: number }>(`/risk-cases/${id}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

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

  // ---- the AI Intelligence Studio (Part C) ----
  //
  // Every one of these is deterministic. §37's rule about the Retrieval Lab
  // holds for the whole Studio: nothing here spends a credit, because a
  // screen that cost money to render is a screen nobody opens twice.
  studioTabs: () => request<StudioTabIndex>("/intelligence/studio/tabs"),
  studioReadiness: () =>
    request<StudioReadiness>("/intelligence/studio/readiness"),
  studioCapabilities: () =>
    request<StudioCapabilityHealth>("/intelligence/studio/capabilities"),
  studioKnowledge: () =>
    request<StudioSections>("/intelligence/studio/knowledge"),
  studioBlueprints: () =>
    request<StudioObjects>("/intelligence/studio/blueprints"),
  studioJudgment: () =>
    request<StudioJudgment>("/intelligence/studio/judgment"),
  studioVisualGrammar: () =>
    request<StudioVisualGrammar>("/intelligence/studio/visual-grammar"),
  studioPermissions: () =>
    request<StudioPermissions>("/intelligence/studio/permissions"),
  studioHoldout: () => request<StudioHoldout>("/intelligence/studio/holdout"),
  studioBadge: () => request<StudioBadge>("/intelligence/studio/badge"),
  studioShapeLab: (body: StudioShapeLabRequest) =>
    request<StudioShapeLabResult>("/intelligence/studio/shape-lab", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  studioTeachingCases: () =>
    request<StudioTeachingCases>("/intelligence/studio/teaching-cases"),
  studioRoutingTab: () =>
    request<StudioRoutingTab>("/intelligence/studio/routing-tab"),
  studioPrompts: () => request<StudioPanel>("/intelligence/studio/prompts"),
  studioEvaluations: () =>
    request<StudioEvaluations>("/intelligence/studio/evaluations"),
  studioReleasesTab: () =>
    request<StudioReleasesTab>("/intelligence/studio/releases-tab"),
  studioLiveHealth: () =>
    request<StudioLiveHealth>("/intelligence/studio/live-health"),
  studioFailures: () =>
    request<StudioFailures>("/intelligence/studio/failures"),
  // ---- Investigation assurance (Part F) ----
  //
  // Also deterministic. An assurance review reads records that were written
  // when the answers were given; nothing here re-scores anything, and
  // nothing here calls a provider.
  investigationReviews: (params: Record<string, string> = {}) =>
    request<InvestigationReviews>(
      `/intelligence/investigation-reviews${
        Object.keys(params).length
          ? `?${new URLSearchParams(params).toString()}`
          : ""
      }`,
    ),
  studioReviewsTab: () =>
    request<StudioReviewsTab>("/intelligence/studio/investigation-reviews"),
  investigationAssurance: (investigationId: string) =>
    request<AssuranceReview | AssuranceNotYet>(
      `/investigations/${encodeURIComponent(investigationId)}/assurance`,
    ),
  assuranceRecord: (investigationId: string, recordId: string) =>
    request<AssuranceReview>(
      `/investigations/${encodeURIComponent(investigationId)}/assurance/${encodeURIComponent(recordId)}`,
    ),

  studioRouteSimulator: (question: string) =>
    request<StudioRouteSimulation>("/intelligence/studio/route-simulator", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // ---- answer feedback (Part E) ----
  //
  // §148 requires the control after every response, so this is open to every
  // signed-in role — the people most likely to notice a wrong answer are the
  // analysts who read them all day.
  feedbackOptions: () => request<FeedbackOptions>("/feedback/options"),
  leaveFeedback: (body: FeedbackRequest) =>
    request<FeedbackReceipt>("/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- §7-§24: the accuracy-and-usefulness prompt, and the learning area ----
  //
  // The placement decision is made by the backend rather than here. §7's
  // suppression rules are the half that protects the user rather than the
  // product, and a client that decided for itself would drift — the
  // suppressions first.
  feedbackPrompt: (params: {
    answer_id: string;
    thread_id?: string;
    complete?: boolean;
    is_error?: boolean;
    is_skeleton?: boolean;
    already_answered?: boolean;
  }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<FeedbackPrompt>(`/learning/prompt?${query.toString()}`);
  },
  leaveAccuracyFeedback: (body: AccuracyFeedbackRequest) =>
    request<AccuracyFeedbackReceipt>("/learning/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  muteFeedbackThread: (threadId: string) =>
    request<{ muted_threads: string[] }>("/learning/preferences/mute-thread", {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId }),
    }),
  learningInbox: (rating = "", limit = 50) =>
    request<{ events: Record<string, unknown>[]; count: number }>(
      `/learning/inbox?rating=${encodeURIComponent(rating)}&limit=${limit}`,
    ),
  learningCandidates: (caseStatus = "") =>
    request<{
      candidates: Record<string, unknown>[];
      count: number;
      statuses: Record<string, string>;
      failure_classes: Record<string, string>;
    }>(`/learning/candidates?case_status=${encodeURIComponent(caseStatus)}`),
  learningObservations: (label = "") =>
    request<{
      observations: Record<string, unknown>[];
      count: number;
      labels: Record<string, string>;
      note: string;
    }>(`/learning/observations?label=${encodeURIComponent(label)}`),
  learningReleases: () =>
    request<{
      releases: Record<string, unknown>[];
      active: string;
      gates: Record<string, string>;
      note: string;
    }>("/learning/releases"),
  learningReplays: () =>
    request<{ replays: Record<string, unknown>[] }>("/learning/replays"),
  learningModels: () =>
    request<{
      runs: Record<string, unknown>[];
      tasks: { task: string; decides: string; baseline: string }[];
      forbidden: Record<string, string>;
      note: string;
    }>("/learning/models"),
  learningSatisfaction: (days = 30) =>
    request<SatisfactionMetrics>(`/learning/metrics/satisfaction?days=${days}`),
  learningMetrics: () =>
    request<Record<string, unknown>>("/learning/metrics/learning"),
  learningGuard: () => request<LearningGuard>("/learning/guard"),

  // ------------------------------------------------- the Brain Center. §25
  //
  // Reading is separated from changing here for the same reason the backend
  // separates the permissions: opening a tab must never be a call that could
  // alter what a Brain is. Every method below that changes something is a
  // POST with a stated reason, and none of them is called on mount.
  brainOverview: () => request<BrainOverview>("/brain/overview"),
  brainLedger: () => request<BrainLedger>("/brain/ledger"),
  brainExportKinds: () => request<BrainExportKinds>("/brain/export/kinds"),
  brainBuildExport: (body: BrainExportRequest) =>
    request<BrainExportReceipt>("/brain/export", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  brainImports: () => request<BrainImportList>("/brain/imports"),
  brainImport: (importId: string) =>
    request<BrainImportDetail>(
      `/brain/imports/${encodeURIComponent(importId)}`,
    ),
  brainCompatibility: (importId: string) =>
    request<Record<string, unknown>>(
      `/brain/imports/${encodeURIComponent(importId)}/compatibility`,
      { method: "POST" },
    ),
  brainLift: (importId: string) =>
    request<BrainLift>(`/brain/lift/${encodeURIComponent(importId)}`),
  brainConflicts: (importId = "") =>
    request<BrainConflictList>(
      `/brain/conflicts?import_id=${encodeURIComponent(importId)}`,
    ),
  brainResolveConflict: (
    conflictId: string,
    body: { resolution: string; reason: string; split_axis?: string },
  ) =>
    request<Record<string, unknown>>(
      `/brain/conflicts/${encodeURIComponent(conflictId)}/resolve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  brainInstallations: () =>
    request<BrainInstallationList>("/brain/installations"),
  brainSecurity: () => request<BrainSecurity>("/brain/security"),

  // ------------------------------- Regulatory Intelligence. §29-§38
  //
  // Analysis Studio owns this: the source library, the extracted
  // requirements and the promotion into methods. §27 keeps it apart from
  // the AI Intelligence Studio's Regulatory LEARNING, because a source
  // circular and a certified method are not the same kind of object.
  regulatorySchema: () =>
    request<RegulatorySchema>("/regulatory-intelligence/schema"),
  regulatoryRuns: (documentId = "") =>
    request<RegulatoryRuns>(
      `/regulatory-intelligence/runs?document_id=${encodeURIComponent(documentId)}`,
    ),
  regulatoryRequirements: (documentId = "") =>
    request<RegulatoryRequirements>(
      `/regulatory-intelligence/requirements?document_id=${encodeURIComponent(documentId)}`,
    ),
  regulatoryReviewPanel: (requirementId: string) =>
    request<RegulatoryReviewPanel>(
      `/regulatory-intelligence/requirements/${encodeURIComponent(requirementId)}/review`,
    ),
  regulatoryDecide: (
    requirementId: string,
    body: { action: string; reason: string; target?: string },
  ) =>
    request<Record<string, unknown>>(
      `/regulatory-intelligence/requirements/${encodeURIComponent(requirementId)}/decide`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  regulatoryCorrect: (
    requirementId: string,
    body: { correction: string; reason: string; user_role?: string },
  ) =>
    request<Record<string, unknown>>(
      `/regulatory-intelligence/requirements/${encodeURIComponent(requirementId)}/correct`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  regulatoryCorrections: (requirementId = "") =>
    request<RegulatoryCorrections>(
      `/regulatory-intelligence/corrections?requirement_id=${encodeURIComponent(requirementId)}`,
    ),
  regulatoryConflicts: (requirementId = "") =>
    request<RegulatoryConflicts>(
      `/regulatory-intelligence/conflicts?requirement_id=${encodeURIComponent(requirementId)}`,
    ),
  regulatoryResolveConflict: (
    contradictionId: string,
    body: {
      resolution: string;
      reason: string;
      effective_from?: string;
      split_axis?: string;
    },
  ) =>
    request<Record<string, unknown>>(
      `/regulatory-intelligence/conflicts/${encodeURIComponent(contradictionId)}/resolve`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  regulatoryDrafts: (requirementId = "") =>
    request<RegulatoryDrafts>(
      `/regulatory-intelligence/drafts?requirement_id=${encodeURIComponent(requirementId)}`,
    ),
  regulatoryAudit: (documentId = "") =>
    request<RegulatoryAudit>(
      `/regulatory-intelligence/audit?document_id=${encodeURIComponent(documentId)}`,
    ),

  // -------------------------------- per-answer feedback. §39-§45
  //
  // The prompt comes from the backend rather than being held here. Two
  // lists of eleven fields in two places become two different lists, and
  // the one users see will be the stale one.
  thumbsPrompt: (answerKind = "analysis", language = "en") =>
    request<ThumbsPrompt>(
      `/feedback/prompt?answer_kind=${encodeURIComponent(answerKind)}&language=${encodeURIComponent(language)}`,
    ),
  leaveThumbs: (body: ThumbsRequest) =>
    request<ThumbsReceipt>("/feedback/thumbs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  thumbsJourney: (feedbackId: string) =>
    request<ThumbsJourney>(
      `/feedback/thumbs/${encodeURIComponent(feedbackId)}`,
    ),

  // ------------------------------------ Continuous Learning. §56-§93
  //
  // Every one of these is deterministic and cheap. Opening the cockpit
  // reads recorded snapshots; it does not run an evaluation and does not
  // spend anything, because a screen that costs money to open is a screen
  // nobody opens — and this one exists to be looked at often.
  learningCockpit: (window = "SINCE_CURRENT_INTELLIGENCE_RELEASE") =>
    request<LearningCockpit>(
      `/continuous-learning/cockpit?window=${encodeURIComponent(window)}`,
    ),
  learningWindows: () =>
    request<LearningWindows>("/continuous-learning/windows"),
  learningTimeline: (window = "LAST_12_MONTHS") =>
    request<LearningTimeline>(
      `/continuous-learning/timeline?window=${encodeURIComponent(window)}`,
    ),
  learningVelocity: (days = 30) =>
    request<Record<string, unknown>>(
      `/continuous-learning/velocity?days=${days}`,
    ),
  learningPartitions: () =>
    request<LearningPartitions>("/continuous-learning/partitions"),
  learningMeasurementRules: () =>
    request<LearningMeasurementRules>("/continuous-learning/measurement-rules"),

  // §84. The questions are answered from persisted snapshots. No model is
  // called on either of these, which is why they are cheap enough to sit
  // on a screen somebody opens every morning.
  learningQuestions: () =>
    request<LearningQuestionCatalogue>("/continuous-learning/questions"),
  askLearningQuestion: (question: string, window?: string) =>
    request<LearningAnswer>("/continuous-learning/questions", {
      method: "POST",
      body: JSON.stringify(window ? { question, window } : { question }),
    }),

  // §68. Deterministic by default and free by default. The live-provider
  // mode exists, refuses without authorization, and is never the default.
  experimentKinds: () =>
    request<ExperimentKinds>("/continuous-learning/experiments"),
  runExperiment: (body: ExperimentRequest) =>
    request<ExperimentResult>("/continuous-learning/experiments", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ------------------------ Retail Scorecard Validation. §17-§36
  //
  // Every one of these reads the Parquet lake and returns summaries. §76:
  // a month is 12,000-19,000 rows and none of them crosses the wire —
  // the aggregation happens on the server and the browser gets band
  // tables and sampled curves.
  // ---- Borrower 360 and the corporate graph. Phase 3.
  borrower360Meta: () => request<Borrower360Meta>("/corporate/meta"),
  borrower360Lineage: () =>
    request<Borrower360Lineage>("/corporate/lineage"),
  borrower360Search: (q: string, period?: string, limit = 25) =>
    request<Borrower360Search>(
      `/corporate/search?q=${encodeURIComponent(q)}&limit=${limit}` +
        (period ? `&period=${encodeURIComponent(period)}` : ""),
    ),
  borrower360Cohort: (params: {
    period?: string;
    sector?: string;
    region?: string;
    segment?: string;
    internal_rating?: string;
    stage?: string;
    watchlist_flag?: boolean;
    breach_flag?: boolean;
    default_flag?: boolean;
    borrower_ids?: string;
    /** A governed orderable field. Empty means 12-month PD. §18. */
    order_by?: string;
    descending?: boolean;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      // `descending: false` is a REQUEST — "lowest first" — and dropping it
      // with the other falsy values turned every ascending preset back into a
      // descending one. Flags are different: `watchlist_flag=false` means "do
      // not filter", so it stays dropped.
      if (value === undefined || value === "") return;
      if (value === false && key !== "descending") return;
      query.set(key, String(value));
    });
    const suffix = query.toString();
    return request<Borrower360Search>(
      `/corporate/cohort${suffix ? `?${suffix}` : ""}`,
    );
  },
  borrower360Row: (borrowerId: string, period?: string) =>
    request<Borrower360Row>(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  borrower360Groups: (borrowerId: string, period?: string) =>
    request<Borrower360Groups>(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}/groups` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  borrower360Graph: (
    borrowerId: string,
    view: string,
    depth: number,
    period?: string,
  ) =>
    request<Borrower360Graph>(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}/graph` +
        `?view=${encodeURIComponent(view)}&depth=${depth}` +
        (period ? `&period=${encodeURIComponent(period)}` : ""),
    ),
  borrower360Relationships: (
    borrowerId: string,
    view: string,
    depth: number,
    period?: string,
  ) =>
    request<RelationshipNetwork>(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}/relationships` +
        `?view=${encodeURIComponent(view)}&depth=${depth}` +
        (period ? `&period=${encodeURIComponent(period)}` : ""),
    ),
  borrower360Similar: (borrowerId: string, period?: string) =>
    request<Borrower360Similar>(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}/similar` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  downloadBorrower360Pack: (borrowerId: string, period?: string) =>
    download(
      `/corporate/borrowers/${encodeURIComponent(borrowerId)}/pack` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
      `borrower-360-${borrowerId}.xlsx`,
    ),
  borrower360Quality: (period?: string) =>
    request<Borrower360Quality>(
      `/corporate/quality` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),
  // A person's own working set. Nothing here is shared, and a saved cohort
  // stores the SEARCH rather than the borrowers it matched - the book is
  // rebuilt every quarter and a stored id list would go stale silently.
  borrower360Workspace: () =>
    request<Borrower360Workspace>("/corporate/workspace"),
  borrower360Pin: (body: {
    borrower_id: string;
    label?: string;
    noted?: string;
  }) =>
    request<{ pin: Borrower360Kept }>("/corporate/workspace/pins", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  borrower360Unpin: (borrowerId: string) =>
    request<{ removed: boolean }>(
      `/corporate/workspace/pins/${encodeURIComponent(borrowerId)}`,
      { method: "DELETE" },
    ),
  borrower360SaveCohort: (body: {
    label: string;
    query: Record<string, unknown>;
  }) =>
    request<{ cohort: Borrower360Kept }>("/corporate/workspace/cohorts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  borrower360ForgetCohort: (reference: string) =>
    request<{ removed: boolean }>(
      `/corporate/workspace/cohorts/${encodeURIComponent(reference)}`,
      { method: "DELETE" },
    ),
  borrower360RunCohort: (reference: string, period?: string) =>
    request<{ cohort: Borrower360Kept; result: Borrower360Search }>(
      `/corporate/workspace/cohorts/${encodeURIComponent(reference)}/run` +
        (period ? `?period=${encodeURIComponent(period)}` : ""),
    ),

  scorecardOverview: () =>
    request<ScorecardOverview>("/scorecard/overview"),
  scorecardPolicy: () => request<ScorecardPolicy>("/scorecard/policy"),
  scorecardMonths: (type: ScorecardType) =>
    request<ScorecardMonths>(`/scorecard/months/${type}`),
  scorecardDashboard: (
    type: ScorecardType,
    options: {
      model?: string;
      month?: string;
      segmentBy?: string;
      curves?: boolean;
    } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.model) query.set("model", options.model);
    if (options.month) query.set("month", options.month);
    if (options.segmentBy) query.set("segment_by", options.segmentBy);
    if (options.curves === false) query.set("curves", "false");
    const suffix = query.toString() ? `?${query}` : "";
    return request<ScorecardDashboard>(`/scorecard/dashboard/${type}${suffix}`);
  },
  scorecardModels: (type: ScorecardType) =>
    request<ScorecardModels>(`/scorecard/models/${type}`),
  scorecardEquation: (type: ScorecardType, model: string) =>
    request<ScorecardEquation>(
      `/scorecard/models/${type}/${encodeURIComponent(model)}/equation`,
    ),
  scorecardBinning: (type: ScorecardType, variable = "") =>
    request<ScorecardBinningSpec>(
      `/scorecard/binning/${type}${
        variable ? `?variable=${encodeURIComponent(variable)}` : ""
      }`,
    ),
  scorecardVariables: (type: ScorecardType) =>
    request<ScorecardVariables>(`/scorecard/variables/${type}`),
  scorecardLowDiscrimination: (
    type: ScorecardType,
    options: { model?: string; month?: string; leaveOneOut?: boolean } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.model) query.set("model", options.model);
    if (options.month) query.set("month", options.month);
    if (options.leaveOneOut === false) query.set("leave_one_out", "false");
    const suffix = query.toString() ? `?${query}` : "";
    return request<ScorecardDiagnosis>(
      `/scorecard/diagnose/${type}/low-discrimination${suffix}`,
    );
  },
  scorecardAccuracy: (
    type: ScorecardType,
    options: { model?: string; month?: string } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.model) query.set("model", options.model);
    if (options.month) query.set("month", options.month);
    const suffix = query.toString() ? `?${query}` : "";
    return request<ScorecardDiagnosis>(
      `/scorecard/diagnose/${type}/accuracy${suffix}`,
    );
  },
  scorecardOdrTrend: (type: ScorecardType, monthsBack = 20, model?: string) =>
    request<ScorecardOdrTrend>(
      `/scorecard/trend/${type}/odr?months_back=${monthsBack}` +
        (model ? `&model=${model}` : ""),
    ),
  scorecardScoreTrend: (type: ScorecardType, monthsBack = 12) =>
    request<ScorecardScoreTrend>(
      `/scorecard/trend/${type}/score?months_back=${monthsBack}`,
    ),
  scorecardDrift: (
    type: ScorecardType,
    options: { model?: string; month?: string; candidates?: boolean } = {},
  ) => {
    const query = new URLSearchParams();
    if (options.model) query.set("model", options.model);
    if (options.month) query.set("month", options.month);
    if (options.candidates) query.set("candidates", "true");
    const suffix = query.toString() ? `?${query}` : "";
    return request<ScorecardDrift>(`/scorecard/drift/${type}${suffix}`);
  },
  scorecardSegments: (
    type: ScorecardType,
    by: string,
    options: { model?: string; month?: string } = {},
  ) => {
    const query = new URLSearchParams({ by });
    if (options.model) query.set("model", options.model);
    if (options.month) query.set("month", options.month);
    return request<ScorecardSegments>(`/scorecard/segments/${type}?${query}`);
  },
  scorecardCandidate: (type: ScorecardType, body: ScorecardCandidateRequest) =>
    request<ScorecardCandidateResult>(`/scorecard/models/${type}/candidate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  scorecardRescore: (
    type: ScorecardType,
    body: ScorecardCandidateRequest & { months: string[] },
  ) =>
    request<ScorecardRescoreResult>(`/scorecard/models/${type}/rescore`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // §51-§56, §82, §83. The validation report and its evidence workbook.
  scorecardGenerateReport: (
    type: ScorecardType,
    body: {
      month?: string;
      model_kind?: string;
      history_months?: number;
      record?: boolean;
    },
  ) =>
    request<ScorecardReport>(`/scorecard/reports/${type}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  scorecardReports: (type: ScorecardType) =>
    request<ScorecardReportLibrary>(`/scorecard/reports/${type}`),
  scorecardReportEvidence: (reportId: string) =>
    request<ScorecardReportEvidenceIndex>(
      `/scorecard/reports/evidence/${encodeURIComponent(reportId)}`,
    ),
  /**
   * The download URL, not the bytes. The file is a browser navigation so
   * the Content-Disposition filename the server chose is the one the user
   * gets; fetching it here and re-naming it in JavaScript would mean two
   * places deciding what §51's filename is.
   */
  scorecardReportDownloadUrl: (
    type: ScorecardType,
    fmt: "docx" | "xlsx",
    params: { month?: string; model_kind?: string; history_months?: number },
  ) => {
    const query = new URLSearchParams({ fmt });
    if (params.month) query.set("month", params.month);
    if (params.model_kind) query.set("model_kind", params.model_kind);
    if (params.history_months) {
      query.set("history_months", String(params.history_months));
    }
    return (
      `${API_BASE_URL}${API_PREFIX}/scorecard/reports/${type}` +
      `/download?${query}`
    );
  },

  // §21/§22. The merge that produces a third Brain from two.
  brainMergePreview: (importId: string) =>
    request<BrainMergePreview>(`/brain/merge/${encodeURIComponent(importId)}`),
  brainBuildMerge: (
    importId: string,
    body: {
      brain_name: string;
      brain_version?: string;
      authored?: Record<string, Record<string, unknown>>;
    },
  ) =>
    request<BrainMergeResult>(`/brain/merge/${encodeURIComponent(importId)}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/** §52. One section of the CBUAE-aligned report, as the API returns it. */
export type ScorecardReportSection = {
  number: string;
  title: string;
  level: number;
  narrative: string;
  tables: {
    caption: string;
    columns: string[];
    rows: string[][];
    note: string;
  }[];
  /** Non-empty when the section could not be computed, and why. */
  unavailable: string;
};

/** §89. Which required topics this report actually addresses. */
export type ScorecardReportCoverage = {
  addressed: Record<string, string>;
  missing: string[];
  complete: boolean;
  topics: number;
};

export type ScorecardReport = {
  report_id: string;
  model_id: string;
  model_version: string;
  model_name: string;
  scorecard_type: ScorecardType;
  model_kind: string;
  period: string;
  title: string;
  structure_version: string;
  generated_at: string;
  generated_by: string;
  opinion: string;
  document_control: string[][];
  sections: ScorecardReportSection[];
  evidence: {
    section: string;
    label: string;
    metric: string;
    value: number | null;
    value_text: string;
    method: string;
    period: string;
    model_version: string;
    validation_state: string;
    workbook_sheet: string;
  }[];
  evidence_count: number;
  content_hash: string;
  disclaimer: string;
  origin: string;
  not_client_data: string;
  coverage: ScorecardReportCoverage;
  downloads: { docx: string; xlsx: string };
};

/** §82. The report library. */
export type ScorecardReportLibrary = {
  scorecard_type: ScorecardType;
  reports: {
    report_id: string;
    model_id: string;
    model_version: string;
    period: string;
    title: string;
    opinion: string;
    status: string;
    structure_version: string;
    generated_by: string;
    generated_at: string;
    sections: number;
    origin: string;
  }[];
  count: number;
  structure_version: string;
};

export type ScorecardReportEvidenceIndex = {
  report_id: string;
  evidence: {
    section: string;
    label: string;
    metric: string;
    value: number | null;
    value_text: string;
    validation_run_id: string;
    analysis_id: string;
    trace_id: string;
    workbook_sheet: string;
    workbook_cell: string;
  }[];
  count: number;
};

/** §84. What the Studio can answer, and where the numbers come from. */
export type LearningQuestionCatalogue = {
  questions: { question_id: string; question: string }[];
  windows_available: string[];
  answered_from: string;
  no_model_involved: string;
};

/**
 * §84. One answered question.
 *
 * `answerable: false` is a real answer, not an error. "Never measured" and
 * "measured and did not move" lead to opposite decisions, and a zero would
 * render as the second when the truth is the first.
 */
export type LearningAnswer = {
  question_id: string;
  asked: string;
  answerable: boolean;
  headline: string;
  detail: string[];
  numbers: {
    label: string;
    value: number | string;
    unit: string;
    source: string;
    reads_as: string;
  }[];
  basis_snapshots: string[];
  missing: string[];
  caveats: string[];
  source: string;
  not_generated: string;
  catalogue?: { question_id: string; question: string }[];
};

/** §68. What an isolation experiment can attribute, and what it costs. */
export type ExperimentKinds = {
  change_kinds: { id: string; attributes_to: string }[];
  modes: string[];
  default_mode: string;
  minimum_cases: number;
  live_provider_rule: string;
  what_isolation_means: string;
};

export type ExperimentArm = {
  label: string;
  changes?: string[];
  scores?: Record<string, number>;
  families?: Record<string, string>;
  dimensions?: Record<string, number>;
  critical_failures?: string[];
  latency_ms?: number;
  cost_units?: number;
};

export type ExperimentRequest = {
  change_kind: string;
  change_id: string;
  baseline: ExperimentArm;
  treatment: ExperimentArm;
  partition?: string;
  mode?: string;
  authorization?: string;
};

export type LearningChange = {
  label: string;
  points: number;
  relative_pct: number;
  error_reduction_pct: number;
  cases: number;
  evidence: string;
  verdict: string;
  reads_as: string;
};

export type ExperimentResult = {
  experiment_id: string;
  change_kind: string;
  change_id: string;
  attributed_source: string;
  partition: string;
  mode: string;
  isolated: boolean;
  why_not_isolated: string;
  overall: LearningChange;
  by_case_family: Record<string, LearningChange>;
  by_dimension: Record<string, LearningChange>;
  critical_regressions: string[];
  critical_fixes: string[];
  latency_delta_ms: number;
  cost_delta_units: number;
  reads_as: string;
  contribution: {
    source: string;
    points: number;
    isolated: boolean;
    evidence: string;
  };
};

/** §21/§22. What a merge would produce, before anybody commits to it. */
export type BrainMergePreview = {
  import_id: string;
  local_brain: string;
  incoming_brain: string;
  kinds: string[];
  local_items: Record<string, number>;
  incoming_items: Record<string, number>;
  conflicts_total: number;
  conflicts_blocking: string[];
  needs_authoring: string[];
  may_merge: boolean;
  contested_items: number;
  why_not: string[];
  note: string;
};

export type ScorecardType = "APPLICATION" | "BEHAVIORAL";

/**
 * §7's three month notions, which the dashboard must show separately.
 *
 * `latest_data_month` is what arrived. `latest_matured_performance_month`
 * is the last one whose performance window closed. Conflating them is how
 * a trend chart shows a fictitious improvement at its right edge.
 */
export type ScorecardContext = {
  scorecard_type: ScorecardType;
  model: string;
  validation_month: string;
  latest_data_month: string;
  latest_matured_performance_month: string;
  performance_horizon_months: number;
  outcome_maturity_status: string;
  reference_population: string;
  what_this_means: string;
};

/** §81's row: metric, observed, limit, status, source. */
export type ScorecardAssessment = {
  metric: string;
  label: string;
  observed: number | null;
  limit_value: number | null;
  status: string;
  source: string | null;
  why: string;
  evidence?: string;
};

export type ScorecardOverview = {
  module: string;
  scorecard_types: ScorecardType[];
  origin: string;
  not_client_data: string;
  scorecards: Record<
    string,
    {
      available: boolean;
      why?: string;
      months?: string[];
      month_count?: number;
      latest_data_month?: string;
      latest_matured_performance_month?: string;
      performance_horizon_months?: number;
      models?: string[];
      candidate_variables?: number;
      families?: string[];
    }
  >;
  domains: {
    domains: Record<string, string>;
    families: Record<string, string[]>;
    not_client_data: string;
  };
};

export type ScorecardPolicy = {
  provenances: string[];
  statuses: string[];
  severities: string[];
  opinions: string[];
  limits: {
    metric: string;
    label: string;
    direction: string;
    breach_at: number;
    watch_at: number | null;
    provenance: string;
    note: string;
  }[];
  every_limit_here_is_demo_policy: boolean;
  why: string;
};

export type ScorecardMonths = {
  scorecard_type: ScorecardType;
  months: {
    month: string;
    matured: boolean;
    outcome_available_from: string;
  }[];
  latest_data_month: string;
  latest_matured_performance_month: string;
  performance_horizon_months: number;
  immature_months_are_stability_only: string;
};

export type ScorecardBand = {
  band: number;
  observations: number;
  events: number;
  observed_default_rate: number;
  average_predicted_pd: number;
  score_from: number;
  score_to: number;
  evidence: string;
};

/**
 * A section the dashboard could not compute.
 *
 * §7: a month whose window has not closed gets this rather than a number.
 * The screen renders `why`, which names the month the window closes.
 */
export type ScorecardUnavailable = {
  available: false;
  section: string;
  why: string;
  latest_matured_month: string;
};

export type ScorecardDiscrimination =
  | ScorecardUnavailable
  | {
      available?: undefined;
      auc: number;
      auc_ci_low: number | null;
      auc_ci_high: number | null;
      gini: number;
      accuracy_ratio: number;
      ks: number;
      ks_at_score: number;
      observations: number;
      events: number;
      evidence: string;
      score_direction: string;
      definitions: Record<string, string>;
      reads_as: string;
      gains: {
        decile: number;
        observations: number;
        events: number;
        bad_rate: number;
        lift: number;
        cumulative_capture_rate: number;
        population_share: number;
        evidence: string;
      }[];
      roc_curve?: { false_positive_rate: number; true_positive_rate: number }[];
      ks_curve?: {
        score: number;
        cumulative_bad: number;
        cumulative_good: number;
        gap: number;
      }[];
      assessments: ScorecardAssessment[];
    };

export type ScorecardCalibration =
  | ScorecardUnavailable
  | {
      available?: undefined;
      observed_default_rate: number;
      average_predicted_pd: number;
      observed_defaults: number;
      expected_defaults: number;
      calibration_in_the_large: number;
      calibration_slope: number | null;
      brier_score: number;
      log_loss: number;
      bucket_rmse: number;
      mape: number | null;
      mape_status: string;
      observations: number;
      evidence: string;
      buckets: ScorecardBand[];
      what_rmse_means_here: string;
      reads_as: string;
      assessments: ScorecardAssessment[];
    };

export type ScorecardShift = {
  kind: string;
  variable: string;
  index: number;
  reference_rows: number;
  current_rows: number;
  bins: {
    bin: string;
    reference_share: number;
    current_share: number;
    shift: number;
    contribution: number;
  }[];
  thresholds_are_policy: string;
  assessment?: ScorecardAssessment;
};

export type ScorecardStability = {
  score_psi: ScorecardShift;
  score_psi_assessment: ScorecardAssessment;
  variable_csi: (ScorecardShift & { why?: string })[];
  special_bin_rates: Record<string, Record<string, number>>;
  baseline: string;
  available_without_outcomes: string;
};

export type ScorecardVariableRow = {
  variable: string;
  measured_on: string;
  auc: number | null;
  gini: number | null;
  ks: number | null;
  observations: number;
  events: number;
  missing_rate?: number;
  special_bin_rate?: number;
  evidence: string;
  why?: string;
  information_value?: number | null;
  woe_monotonic?: boolean | null;
  in_active_model?: boolean;
  coefficient?: number | null;
};

export type ScorecardDashboard = {
  context: ScorecardContext;
  summary: Record<string, unknown> & {
    population: number;
    defaults: number | null;
    observed_default_rate: number | null;
    average_predicted_pd: number;
    average_score: number;
  };
  data_quality: Record<string, unknown> & {
    rows: number;
    duplicate_keys: number;
    defaults: number | null;
    missingness_by_active_variable: Record<string, number>;
    missingness_assessments: ScorecardAssessment[];
    sample_sufficiency: ScorecardAssessment[];
    pd_within_zero_and_one: boolean;
    score_range: { min: number; max: number };
  };
  discrimination: ScorecardDiscrimination;
  calibration: ScorecardCalibration;
  stability: ScorecardStability;
  variables:
    | ScorecardUnavailable
    | {
        available?: undefined;
        scope: string;
        variables: ScorecardVariableRow[];
        active_variables: string[];
        candidate_count: number;
        candidate_is_not_active: string;
      };
  implementation: {
    rows_checked: number;
    max_absolute_logit_difference: number;
    mismatch_count: number;
    mismatch_rate: number;
    status: string;
    why: string;
    assessment: ScorecardAssessment;
  };
  comparison:
    | ScorecardUnavailable
    | {
        available?: undefined;
        population: number;
        period: string;
        models: {
          model: string;
          auc: number;
          gini: number;
          ks: number;
          brier_score: number;
          log_loss: number;
          bucket_rmse: number;
          mape: number | null;
          mape_status: string;
          average_predicted_pd: number;
          observed_default_rate: number;
          auc_ci_low: number | null;
          auc_ci_high: number | null;
          evidence: string;
        }[];
        best_rank_ordering: string;
        best_calibrated: string;
        identical_population: string;
        overlapping_intervals: string;
      };
  segments?:
    | ScorecardUnavailable
    | {
        available?: undefined;
        split_by: string;
        segments: {
          segment: string;
          observations: number;
          events: number;
          observed_default_rate: number;
          average_predicted_pd: number;
          gini: number | null;
          ks?: number;
          evidence: string;
          why_no_gini?: string;
        }[];
        sample_sufficiency: string;
      };
  findings: {
    findings: ScorecardFinding[];
    counts: Record<string, number>;
  };
  performance_limits: ScorecardAssessment[];
  validation_opinion: {
    opinion: string;
    because: string[];
    findings: Record<string, number>;
    breached_metrics: string[];
    metrics_not_measured: string[];
    metrics_with_no_approved_limit: string[];
    how_this_was_decided: string;
    not_a_certification: string;
  } | null;
  origin: string;
  not_client_data: string;
};

export type ScorecardFinding = {
  finding_id: string;
  model_id: string;
  period: string;
  category: string;
  report_section: string;
  title: string;
  description: string;
  severity: string;
  metric: string;
  observed: number | null;
  limit_value: number | null;
  limit_source: string;
  breach: boolean;
  impact: string;
  recommendation: string;
  status: string;
  raised_by: string;
};

export type ScorecardEquationTerm = {
  variable: string;
  coefficient: number;
  transformation: string;
  column: string;
};

export type ScorecardEquation = {
  model_name: string;
  scorecard_type: ScorecardType;
  intercept: number;
  link: string;
  terms: ScorecardEquationTerm[];
  active_variables: string[];
  binning_spec_version: string;
  score_mapping: {
    base_score: number;
    pdo: number;
    base_odds: number;
    score_direction: string;
    factor: number;
    offset: number;
    formula: string;
  } | null;
  reads_as: string;
  pd_from_logit: string;
  validation: {
    valid: boolean;
    blocking: { check: string; severity: string; detail: string }[];
    warnings: { check: string; severity: string; detail: string }[];
    checks_run: number;
    checks: string[];
  };
};

export type ScorecardModels = {
  scorecard_type: ScorecardType;
  default_definition: Record<string, unknown>;
  score_mapping: Record<string, unknown>;
  models: Record<
    string,
    {
      equation: ScorecardEquation;
      fit: Record<string, unknown>;
      active_variables: string[];
    }
  >;
  answered_from_the_registry: string;
};

export type ScorecardBinningSpec = {
  spec_version: string;
  scorecard_type: ScorecardType;
  development_population: string;
  development_rows: number;
  development_bads: number;
  variables: Record<
    string,
    {
      variable: string;
      kind: string;
      information_value: number;
      iv_strength: string;
      iv_strength_is_a_convention: string;
      woe_monotonic: boolean;
      bins: {
        bin_id: string;
        label: string;
        count: number;
        good_count: number;
        bad_count: number;
        bad_rate: number;
        woe: number;
        iv_contribution: number;
        special: boolean;
      }[];
    }
  >;
  frozen: string;
};

export type ScorecardVariables = {
  scorecard_type: ScorecardType;
  candidates: {
    name: string;
    label: string;
    kind: string;
    definition: string;
    risk_direction: string;
    unit: string;
    scoreable: boolean;
  }[];
  candidate_count: number;
  active_by_model: Record<string, string[]>;
  sensitive_excluded_from_scoring: string[];
  candidate_is_not_active: string;
};

/**
 * §28/§29. A diagnosis, with what it did and did not establish.
 *
 * `claim_strength` is the whole point: "associated with" until a
 * leave-one-out actually ran, "accounts for" after.
 */
export type ScorecardDiagnosis = {
  question_as_asked: string;
  question_as_analysed: string;
  why_restated: string;
  steps_run: string[];
  evidence: {
    subject: string;
    measure: string;
    current: number | null;
    baseline: number | null;
    change: number | null;
    weight: number;
    evidence: string;
    reads_as: string;
  }[];
  ranked: {
    rank: number;
    subject?: string;
    root_cause?: string;
    weight: number;
    measures?: string[];
    because?: string;
    means?: string;
  }[];
  claim_strength: string;
  limitations: string[];
  suggested_next_analyses: string[];
  context: Record<string, unknown>;
};

export type ScorecardOdrTrend = {
  scorecard_type: ScorecardType;
  model: string;
  months: {
    month: string;
    observations: number;
    defaults: number;
    observed_default_rate: number;
    average_predicted_pd: number;
    evidence: string;
  }[];
  months_requested: number;
  months_returned: number;
  only_matured: string;
};

export type ScorecardScoreTrend = {
  scorecard_type: ScorecardType;
  model: string;
  baseline: string;
  months: {
    month: string;
    score_psi: number;
    mean_score: number;
    median_score: number;
    p10: number;
    p90: number;
    observations: number;
  }[];
  available_without_outcomes: string;
};

export type ScorecardDrift = {
  scope: string;
  month: string;
  variables: {
    variable: string;
    csi: number | null;
    in_active_model: boolean;
    largest_move: Record<string, unknown> | null;
    why?: string;
  }[];
  measurable: number;
  why_some_are_absent: string;
};

export type ScorecardSegments = {
  split_by: string;
  segments: {
    segment: string;
    observations: number;
    events: number;
    observed_default_rate: number;
    average_predicted_pd: number;
    gini: number | null;
    ks?: number;
    evidence: string;
    why_no_gini?: string;
  }[];
  sample_sufficiency: string;
};

export type ScorecardCandidateRequest = {
  model_name: string;
  intercept: number;
  terms: { variable: string; coefficient: number }[];
  based_on?: string;
};

export type ScorecardCandidateResult = {
  candidate: ScorecardEquation;
  validation: ScorecardEquation["validation"];
  diff: {
    from_model: string;
    to_model: string;
    variables_added: string[];
    variables_removed: string[];
    coefficients_changed: Record<
      string,
      { from: number; to: number; delta: number }
    >;
    intercept: { from: number; to: number; delta: number };
    material: boolean;
    status: string;
  };
  status: string;
  activated: boolean;
  what_happens_next: string;
};

export type ScorecardRescoreResult = ScorecardCandidateResult & {
  compared_against: string;
  months: {
    month: string;
    comparable: boolean;
    why?: string;
    observations?: number;
    candidate?: { gini: number; ks: number; auc: number };
    baseline?: { gini: number; ks: number; auc: number };
    gini_delta?: number;
    evidence?: string;
  }[];
  months_comparable: number;
  mean_gini_delta: number | null;
  nothing_was_written: string;
};

export type BrainMergeResult = {
  package_id: string;
  brain_id: string;
  brain_name: string;
  brain_version: string;
  entry_count: number;
  size_bytes: number;
  evaluated: boolean;
  next_step: string;
};

/** §7's prompt, as the backend decided it. */
export type FeedbackPrompt = {
  show: boolean;
  because: string;
  question: string;
  answers: { value: string; label: string; means: string }[];
  answer_id: string;
  categories: { id: string; label: string; means: string }[];
  consent_question: string;
  consent_options: Record<string, string>;
  detail_on: string[];
  dont_ask_again_in_this_thread: boolean;
};

export type AccuracyFeedbackRequest = {
  rating: string;
  answer_id: string;
  categories?: string[];
  comment?: string;
  correction?: {
    conclusion?: string;
    value?: string;
    preferred_dataset?: string;
    preferred_period?: string;
    preferred_method?: string;
    expected_visualization?: string;
    reference?: string;
  };
  consent?: string;
  surface?: string;
  investigation_id?: string;
  project_id?: string;
  message_id?: string;
  question?: string;
  agentic_run_id?: string;
  plan_fingerprint?: string;
  assurance_record_id?: string;
  build_sha?: string;
  officer_level?: number | null;
};

export type AccuracyFeedbackReceipt = {
  event_id: string;
  acknowledgement: string;
  what_happens_next: string;
  reproducible: boolean;
  may_learn: boolean;
};

export type SatisfactionMetrics = {
  window_days: number;
  answers_given: number;
  feedback_events: number;
  rated: number;
  response_rate_pct: number | null;
  by_rating: Record<string, number>;
  by_issue_category: Record<string, number>;
  corrections: number;
  correction_rate_pct: number | null;
  note: string;
};

export type LearningGuard = {
  ok: boolean;
  explanation: string;
  protected: Record<string, string[]>;
  forbidden_imports: Record<string, string>;
  modules: string[];
  exemptions: { module: string; line: number; reason: string }[];
  findings: { module: string; line: number; explanation: string }[];
};

export type FeedbackOptions = {
  ratings: string[];
  reasons: {
    GOOD: { code: string; label: string }[];
    BAD: { code: string; label: string }[];
  };
  acknowledgement: string;
  bad_reason_encouraged: boolean;
  note: string;
};

export type FeedbackRequest = {
  rating: "GOOD" | "BAD";
  answer_id: string;
  reason_codes?: string[];
  comment?: string;
  expected_behavior?: string;
  selected_fact_ids?: string[];
  selected_chart_element?: string;
  selected_trace_node?: string;
  message_id?: string;
  investigation_id?: string;
  analysis_run_id?: string;
  trace_id?: string;
  agentic_run_id?: string;
  project_id?: string;
  scope?: string;
  language?: string;
};

export type FeedbackReceipt = {
  feedback_id: string;
  status: string;
  acknowledgement: string;
  reproducible: boolean;
  reason_missing: boolean;
  changes_production: boolean;
};

/** A tab payload that is mostly an explanation plus free-form detail. */
export type StudioPanel = {
  purpose: string;
  explanation?: StudioExplanation;
  [key: string]: unknown;
};

export type StudioTeachingCases = StudioPanel & {
  governance: { sentence?: string; [key: string]: unknown };
  summary: Record<string, unknown>;
  filters: string[];
  never_shown: string;
};

export type StudioRoutingTab = StudioPanel & {
  roles: {
    name: string;
    purpose: string;
    configured_model: string;
    effort: string;
    inherited: boolean;
    active: boolean;
  }[];
  why: Record<string, string>;
  fallback_policy: { when_complex_unavailable: string; note: string };
};

export type StudioEvaluations = StudioPanel & {
  subtabs: string[];
  reporting_rules: Record<string, unknown>;
  cost_control: { confirmation_required: boolean; note: string };
};

export type StudioReleasesTab = StudioPanel & {
  gate: { state?: string; reason?: string; [key: string]: unknown };
  manifest: Record<string, unknown>;
  files: string[];
  missing_files: string[];
  actions: { id: string; label: string; needs: string; note?: string }[];
  never: string;
};

/**
 * Part F. The six Intelligence Dimensions and the Investigation Assurance
 * Record.
 *
 * `operational_assurance` is nullable on purpose, at every level. The gates
 * refuse a number more often than they award one, and a type that made it
 * `number` would push every rendering site into inventing a zero — which
 * reads as a very bad score rather than as no score at all.
 */
export type DimensionCell = {
  dimension: string;
  short: string;
  state: "PASSED" | "WARNING" | "FAILED" | "UNMEASURED";
  score?: number | null;
  coverage_pct?: number;
};

export type ReferenceMatch = {
  available: boolean;
  value_pct: number | null;
  source: string;
  why: string;
};

export type ReviewRow = {
  assurance_record_id: string;
  investigation_id: string;
  title: string;
  user_id: number | null;
  project_id: string;
  at: string;
  scope: string;
  language: string;
  turn_index: number;
  officer_level: number;
  model_route: string;
  case_family: string;
  overall_status: string;
  status_now: string;
  operational_assurance: number | null;
  operational_assurance_label: string;
  coverage_pct: number;
  reference_match: ReferenceMatch;
  dimensions: DimensionCell[];
  critical_failures: number;
  warnings: number;
  good_feedback: number;
  bad_feedback: number;
  teaching_release_id: string;
  release_current: boolean;
  stale_reasons: string[];
  superseded_by: string;
  rerun_of: string;
  open_review: boolean;
};

export type InvestigationReviews = {
  view: string;
  view_label: string;
  view_means: string;
  views: { id: string; label: string; means: string }[];
  filters: Record<string, unknown>;
  filter_fields: { field: string; label: string }[];
  rows: ReviewRow[];
  count: number;
  total_visible: number;
  withheld: number;
  presentation: string;
  counts: Record<string, number>;
};

export type DimensionTile = {
  dimension: string;
  label: string;
  answers: string;
  short: string;
  weight: number;
  is_gate: boolean;
  records: number;
  measured_records: number;
  sample: number;
  min_sample: number;
  underpowered: boolean;
  score: number | null;
  score_label: string;
  coverage_pct: number;
  failures: number;
  warnings: number;
  critical_failures: number;
  state: string;
  subcomponents: number;
  worst_subcomponents: { subcomponent: string; failures: number }[];
};

export type StudioReviewsTab = StudioPanel & {
  views: { id: string; count: number }[];
  dimensions: DimensionTile[];
  presentation: string;
  presentation_note: string;
  score_rules: Record<string, boolean>;
};

export type AssuranceDimension = {
  dimension: string;
  label: string;
  answers: string;
  short: string;
  weight: number;
  measured: boolean;
  status: string;
  score: number | null;
  score_label: string;
  coverage_pct: number;
  examines: string[];
  passed: string[];
  warnings: { subcomponent: string; why: string }[];
  failures: { subcomponent: string; why: string; critical: boolean }[];
  skipped: string[];
  why_points_were_lost: {
    subcomponent: string;
    cost: string;
    critical: boolean;
    why: string;
  }[];
  applicability?: { applicable: boolean; reason?: string };
};

/**
 * An Investigation with nothing assured on it yet.
 *
 * Every thread is in this state until its first answer. The endpoint used to
 * report it as a 404 alongside "no such record" and "not yours", so every
 * Investigation page fetched a failure and told the reader the address was
 * wrong. It is neither missing nor refused — it has simply not happened yet,
 * and that is a different sentence.
 */
export type AssuranceNotYet = {
  investigation_id: string;
  assured: false;
  statement: string;
};

export function isNotYetAssured(
  body: AssuranceReview | AssuranceNotYet,
): body is AssuranceNotYet {
  return (body as AssuranceNotYet).assured === false;
}

export type AssuranceReview = {
  version: string;
  button: string;
  tab: string;
  header: {
    assurance_record_id: string;
    investigation_id: string;
    title: string;
    scope: string;
    at: string;
    overall_status: string;
    status_now: string;
    status_means: string;
    operational_assurance: number | null;
    operational_assurance_label: string;
    coverage_pct: number;
    reference_match: ReferenceMatch;
    critical_issues: number;
    warnings: number;
    user_feedback: { good: number; bad: number };
    stale: boolean;
    stale_reasons: string[];
    [key: string]: unknown;
  };
  dimensions: AssuranceDimension[];
  timeline: {
    turn: number;
    assurance_record_id: string;
    question: string;
    answer_type: string;
    at: string;
    overall_status: string;
    operational_assurance: number | null;
    coverage_pct: number;
    dimensions: DimensionCell[];
    repairs: number;
    clarifications: number;
    limitations: string[];
    feedback: { good: number; bad: number };
    actions: string[];
    [key: string]: unknown;
  }[];
  thread: {
    status: string;
    status_means: string;
    turns: number;
    failed_turns: string[];
    averaged: boolean;
    note: string;
  };
  recommended_improvements: {
    subcomponent: string;
    because: string;
    suggestion: string;
  }[];
  feedback: {
    raw_user_feedback: {
      good: number;
      bad: number;
      changes_score: boolean;
      note: string;
    };
    adjudicated_findings: unknown[];
    adjudication_note: string;
  };
  limitations: string[];
  integrity: { intact: boolean; note?: string };
  detail_level?: string;
  detail_note?: string;
};

export type StudioLiveHealth = StudioPanel & {
  provider: { state?: string };
  commands: { what: string; windows: string; unix: string }[];
  never_shown: string[];
};

export type StudioFailures = StudioPanel & {
  categories: {
    id: string;
    stage: string;
    label: string;
    looks_like: string;
    critical: boolean;
  }[];
  items: Record<string, unknown>[];
  no_automatic_learning: boolean;
  note: string;
};

export type StudioRouteSimulation = {
  question: string;
  features: Record<string, unknown>;
  route: Record<string, unknown>;
  called_a_provider: boolean;
  note: string;
};

/** §117: the seven answers every Studio object gives about itself. */
export type StudioExplanation = {
  answers: { id: string; question: string; answer: string }[];
  complete: boolean;
  missing: string[];
};

/** §118: what backs a validation status. A status with no test set is a colour. */
export type StudioValidation = {
  validation_status: string;
  test_set: string;
  case_count: number;
  passed: number;
  failed: number;
  pass_rate: number | null;
  critical_failures: string[];
  last_run: string;
  version: string;
  owner: string;
  known_limitations: string[];
  staleness: string[];
  usage: number;
  trustworthy: boolean;
  sentence: string;
};

export type StudioTabIndex = {
  tabs: {
    id: string;
    label: string;
    purpose: string;
    needs: string;
    visible: boolean;
  }[];
  visible: string[];
};

export type StudioReadiness = {
  state: string;
  means: string;
  reasons: string[];
  to_improve: string[];
  states: string[];
  sentence: string;
};

export type StudioCapabilityHealth = {
  capabilities: {
    capability: string;
    means: string;
    score: {
      point_pct: number;
      lower_pct: number;
      upper_pct: number;
      successes: number;
      total: number;
      reportable: boolean;
      sentence: string;
    };
    case_count: number;
    trend: string;
    critical: boolean;
    critical_failures: string[];
    last_evaluated: string;
    status: string;
    sentence: string;
  }[];
  critical_failures: string[];
  unmeasured: string[];
  failing: string[];
  no_aggregate_score: boolean;
};

export type StudioSections = {
  sections: {
    id: string;
    name: string;
    count: number;
    edit_in: string;
    explanation: StudioExplanation;
    rows: Record<string, unknown>[];
  }[];
};

export type StudioObjects = {
  count: number;
  objects: (Record<string, unknown> & {
    object_id: string;
    name: string;
    explanation: StudioExplanation;
    validation: StudioValidation;
  })[];
  explanation_audit: { total: number; complete: boolean };
};

export type StudioJudgment = {
  subtabs: string[];
  policies: Record<
    string,
    {
      id: string;
      name: string;
      version: string;
      explanation: StudioExplanation;
      rules: Record<string, unknown>;
    }
  >;
};

export type StudioVisualGrammar = {
  explanation: StudioExplanation;
  roles: {
    id: string;
    means: string;
    plottable: boolean;
    labelling: boolean;
    never_drawn: boolean;
  }[];
  mapping: {
    shape: string;
    means: string;
    default: string;
    default_label: string;
    alternatives: string[];
  }[];
  suitability: {
    factors: string[];
    weights: Record<string, number>;
    threshold: number;
    fatal: string[];
  };
  critic: { id: string; asks: string; fatal: boolean; mandatory: boolean }[];
  accessibility: string;
  precision_contract: { max_decimals: number };
  interactions: { chart: string; means: string }[];
};

export type StudioPermissions = {
  permissions: { id: string; means: string; roles: string[] }[];
  separated_duties: { author: string; review: string }[];
  enforced: string;
  yours: string[];
};

export type StudioHoldout = {
  version: string;
  case_count: number | null;
  families: string[] | null;
  critical_count: number | null;
  evaluation_result: string | null;
  fingerprint: string | null;
  shown: string[];
  withheld: string[];
  note: string;
};

export type StudioBadge = {
  release_id: string;
  state: string;
  readiness: string;
};

export type StudioShapeLabRequest = {
  shape: string;
  roles: Record<string, string>;
  categories?: number;
  longest_label?: number;
  periods?: number;
  measures?: number;
  cardinality?: number;
  missing_pct?: number;
  needs_zero_baseline?: boolean;
  zero_baseline_available?: boolean;
  wants_records?: boolean;
  precision_required?: number;
  narrow_device?: boolean;
};

export type StudioShapeLabResult = {
  shape?: string;
  shape_means?: string;
  field_roles?: Record<string, { role: string; means: string }>;
  candidates?: {
    chart: string;
    label: string;
    total: number;
    accepted: boolean;
    rejections: string[];
    factors: Record<string, number>;
  }[];
  chosen?: string;
  chosen_label?: string;
  fell_back?: boolean;
  reason?: string;
  used_live_data?: boolean;
  error?: string;
  shapes?: string[];
  message?: string;
};

// ===========================================================================
// The Brain Center. §13-§26.
//
// The types name what the screen is not allowed to blur. `captured`,
// `approved` and `activated` are three fields rather than one total, and
// `measured` is a boolean rather than a zero — because zero improvement and
// no measurement look identical on a chart and mean opposite things.
// ===========================================================================

/** What is running, and how honest the numbers on the screen are. */
export type BrainOverview = {
  current: {
    ontology_version: string;
    package_schema_version: string;
    ledger_schema_version: string;
    installed_brain: BrainInstallation | null;
  };
  dimensions: string[];
  learning: Record<string, unknown>;
  retrieval_policy: { status: string; retrievable: string; may_tune: string }[];
  installations: number;
  known_limitations: string[];
};

export type BrainLedger = {
  census: Record<string, unknown>;
  sources: string[];
  review_statuses: string[];
  portability_states: string[];
  /** §14's ten conditions. "Not eligible" tells a reviewer nothing. */
  eligibility_conditions: { check: string; means: string }[];
  note: string;
};

export type BrainExportKind = {
  id: string;
  suffix: string;
  label: string;
  purpose: string;
  requires?: string[];
};

export type BrainExportKinds = {
  kinds: BrainExportKind[];
  never_included: string[];
  exportable_case_status: string;
};

export type BrainExportRequest = {
  kind: string;
  brain_id: string;
  brain_name: string;
  brain_version: string;
  baseline_release_id?: string;
  known_limitations?: string[];
};

export type BrainExportReceipt = {
  package_id: string;
  kind: string;
  sha256: string;
  size_bytes: number;
  entry_count: number;
  download: string;
};

export type BrainImportRow = {
  import_id: string;
  package_id: string;
  stage: string;
  state: string;
  blockers: string[];
  approvals: Record<string, unknown>[];
  decision: string;
  uploaded_by: string;
  created_at: string;
  /** Always false before activation, and the screen says so out loud. */
  retrievable: boolean;
};

export type BrainImportList = {
  pipeline: string[];
  quarantined_stages: string[];
  imports: BrainImportRow[];
  note: string;
};

export type BrainImportDetail = {
  import_id: string;
  package_id: string;
  stage: string;
  state: string;
  history: Record<string, unknown>[];
  blockers: string[];
  security: Record<string, unknown>;
  compatibility: Record<string, unknown>;
  diff: Record<string, unknown>;
  evaluation: Record<string, unknown>;
  impact: Record<string, unknown>;
  approvals: Record<string, unknown>[];
  may_activate: boolean;
  activation_blocked_by: string[];
};

export type BrainLift = {
  import_id: string;
  /** Not a score of zero. Nothing was measured. */
  measured: boolean;
  evaluation: Record<string, unknown>;
  impact: Record<string, unknown>;
  rules: {
    minimum_cases: number;
    material_points: number;
    senders_holdout_measures_nothing: boolean;
    critical_regression_overrides_average: boolean;
  };
  note: string;
};

export type BrainConflictRow = {
  conflict_id: string;
  import_id: string;
  conflict_class: string;
  severity: string;
  summary: string;
  incoming: Record<string, unknown>;
  existing: Record<string, unknown>;
  recommendation: string;
  recommendation_reason: string;
  resolution: string;
  resolution_reason: string;
  split_axis: string;
  resolved_by: string;
};

export type BrainConflictList = {
  classes: { id: string; means: string }[];
  /** Eight of them, and none is "newer wins". */
  resolutions: string[];
  conflicts: BrainConflictRow[];
  note: string;
};

export type BrainInstallation = {
  installation_id: string;
  date: string;
  brain: string;
  source_instance: string;
  source_user: string;
  installed_by: string;
  approved_by: string[];
  components: Record<string, unknown>[];
  conflicts: string[];
  baseline_metrics: Record<string, unknown>;
  candidate_metrics: Record<string, unknown>;
  dimension_deltas: Record<string, unknown>;
  critical_fixes: string[];
  critical_regressions: string[];
  release_id: string;
  state: string;
  activated_at: string;
  rolled_back_at: string;
  rollback_reason: string;
  retired_at: string;
  /** One sentence, including when the sentence is "not measured". */
  improvement: string;
};

export type BrainInstallationList = {
  installations: BrainInstallation[];
  rollbacks: BrainInstallation[];
  answers: string;
};

export type BrainSigner = {
  key_id: string;
  label: string;
  organization: string;
  trust_level: string;
  added_by: string;
  added_reason: string;
  revoked_by: string;
  revoked_reason: string;
};

export type BrainSecurity = {
  limits: Record<string, number>;
  allowed_formats: string[];
  never_packaged: string[];
  enforced: string[];
  signers: BrainSigner[];
  untrusted_signer_policy: string;
  permissions: Record<string, string>;
};

// ===========================================================================
// Regulatory Intelligence. §29-§38.
//
// The types name what the screen may not blur. `relevance` has three values
// and the middle one is AMBIGUOUS — a clause that matched no credit cue is
// waiting for a reviewer, not dismissed. `authoritative` on a correction is
// its own field because §33 says a correction from one user is not
// automatically authoritative, and a screen that omitted it would present
// one SME's reading as the bank's position.
// ===========================================================================

export type RegulatorySchema = {
  document_types: { id: string; means: string }[];
  never_in_force: string[];
  requirement_types: { id: string; means: string; configurable: boolean }[];
  credit_topics: string[];
  relevance: string[];
  review_actions: {
    id: string;
    means: string;
    needs_target: boolean;
    counts_as_reviewed: boolean;
  }[];
  contradiction_classes: { id: string; means: string }[];
  resolutions: {
    id: string;
    means: string;
    needs_date: boolean;
    needs_axis: boolean;
    leaves_it_open: boolean;
  }[];
  promotion_targets: string[];
  promotion_gates: { id: string; means: string }[];
  draft_method_parts: string[];
  rules: Record<string, string>;
};

export type RegulatoryRun = {
  run_id: string;
  document_id: string;
  stage: string;
  stage_means: string;
  blockers: string[];
  history: Record<string, unknown>[];
  /** Never true before RELEASED. There is no setting that changes it. */
  retrievable: boolean;
  started_by: string;
  created_at: string;
};

export type RegulatoryRuns = {
  pipeline: {
    stage: string;
    means: string;
    quarantined: boolean;
    optional: boolean;
  }[];
  runs: RegulatoryRun[];
};

export type RegulatoryRequirement = {
  requirement_id: string;
  document_id: string;
  citation: {
    page: number;
    section_number: string;
    section_title: string;
    paragraph: string;
    cited: boolean;
  };
  excerpt: string;
  excerpt_truncated: boolean;
  summary: string;
  requirement_type: string;
  type_means: string;
  relevance: string;
  topics: string[];
  affected: Record<string, string[]>;
  interpretation_confidence: number;
  /** Which pieces of evidence were present, and which were missing. */
  confidence_because: string[];
  validation_status: string;
  reviewer: string;
  decision: string;
  decision_reason: string;
  correction: string;
  version: number;
  conflicts: string[];
  promotion_status: string;
  configurable: boolean;
  promotable: boolean;
};

export type RegulatoryRequirements = {
  progress: {
    total: number;
    reviewed: number;
    /** Deferred and second-review. Not counted as reviewed. */
    parked: number;
    untouched: number;
    complete: boolean;
    note: string;
  };
  census: Record<string, unknown>;
  requirements: RegulatoryRequirement[];
};

export type RegulatoryReviewPanel = {
  requirement_id: string;
  source: Record<string, unknown>;
  understanding: Record<string, unknown>;
  conflicts: Record<string, unknown>[];
  actions: {
    id: string;
    means: string;
    needs_target: boolean;
    counts_as_reviewed: boolean;
  }[];
};

export type RegulatoryCorrections = {
  corrections: {
    correction_id: string;
    requirement_id: string;
    we_read_it_as: string;
    our_confidence: number;
    they_read_it_as: string;
    reason: string;
    by: string;
    role: string;
    /** §33. One user's correction is not the bank's position. */
    authoritative: boolean;
    created_at: string;
  }[];
  note: string;
};

export type RegulatoryConflict = {
  contradiction_id: string;
  requirement_id: string;
  conflict_class: string;
  class_means: string;
  severity: string;
  summary: string;
  incoming: Record<string, unknown>;
  existing: Record<string, unknown>;
  available_resolutions: string[];
  resolution: string;
  resolution_reason: string;
  effective_from: string;
  split_axis: string;
  resolved_by: string;
  resolved: boolean;
};

export type RegulatoryConflicts = {
  classes: { id: string; means: string }[];
  resolutions: {
    id: string;
    means: string;
    needs_date: boolean;
    needs_axis: boolean;
    leaves_it_open: boolean;
  }[];
  conflicts: RegulatoryConflict[];
  outstanding: number;
  note: string;
};

export type RegulatoryDraft = {
  draft_id: string;
  requirement_id: string;
  target: string;
  summary: string;
  status: string;
  gates_passed: string[];
  outstanding_gates: string[];
  governance_owner: string;
  effective_from: string;
  citation: Record<string, unknown>;
  /** Only true at RELEASED. Approval is permission to release, not one. */
  applied: boolean;
  certification: Record<string, unknown>;
};

export type RegulatoryDrafts = {
  targets: string[];
  gates: { id: string; means: string }[];
  drafts: RegulatoryDraft[];
  note: string;
};

export type RegulatoryAudit = {
  document_id: string;
  runs: Record<string, unknown>[];
  decisions: {
    requirement_id: string;
    summary: string;
    page: number;
    section: string;
    decision: string;
    reason: string;
    reviewer: string;
    status: string;
    version: number;
    confidence: number;
  }[];
  undecided: string[];
  corrections: Record<string, unknown>[];
  contradictions: Record<string, unknown>[];
  drafts: Record<string, unknown>[];
  answers: string;
};

// ===========================================================================
// Per-answer feedback. §39-§45.
//
// `validation_score_changed` is a field rather than an omission. §44 says
// raw thumbs do not change validation scores, and a receipt that simply did
// not mention scores would let a screen imply the opposite by silence.
// ===========================================================================

export type ThumbsPrompt = {
  show: boolean;
  answer_kind: string;
  kind_means: string;
  language: string;
  up: { label: string; reasons: { id: string; label: string }[] };
  down: {
    label: string;
    question: string;
    /** "You do not need to provide the numerical answer." */
    explain: string;
    fields: { id: string; label: string; help: string }[];
    anchors: { id: string; means: string }[];
  };
  what_happens_next: {
    immediately: string[];
    through_review: string[];
    path: string[];
    note: string;
  };
};

export type ThumbsRequest = {
  answer_id: string;
  direction: "UP" | "DOWN";
  answer_kind?: string;
  language?: string;
  reasons?: string[];
  correction?: Record<string, string>;
  anchor_kind?: string;
  anchor_ref?: string;
  investigation_id?: string;
  plan_fingerprint?: string;
};

export type ThumbsReceipt = {
  feedback_id: string;
  status: string;
  /** At most two presentation preferences. §42's narrow channel. */
  changed_immediately: Record<string, string>;
  under_review: string[];
  validation_score_changed: false;
  what_happens_next: string;
};

export type ThumbsJourney = {
  feedback_id: string;
  answer_id: string;
  direction: string;
  answer_kind: string;
  status: string;
  status_means: string;
  next_steps: string[];
  history: {
    status: string;
    means: string;
    reason: string;
    by: string;
    linked: { kind: string; id: string };
    release: string;
    score_impact: Record<string, unknown>;
    at: string;
  }[];
  changed_immediately: Record<string, string>;
  under_review: string[];
  governed_path: string[];
  raw_feedback_changed_no_score: boolean;
};

// ===========================================================================
// Continuous Learning. §56-§93.
//
// `learning_captured` and `measured_change` are two fields rather than one
// total, and no component may add them. An installation that captured four
// hundred observations and improved by nothing has done something worth
// knowing, and one number would report it as progress.
// ===========================================================================

export type LearningDimension = {
  dimension: string;
  development: Record<string, unknown>;
  validation: Record<string, unknown>;
  /** IMPROVED, UNCHANGED, MIXED, REGRESSED, INSUFFICIENT EVIDENCE or STALE. */
  verdict: string;
  learning_items_responsible: string[];
  releases_responsible: string[];
  days_since_run: number;
  reads_as: string;
};

export type LearningCockpit = {
  baseline: {
    baseline_id: string;
    comparable_to: string;
    brain?: string;
    created_at: string;
  } | null;
  window: string;
  windows_available: string[];
  headline: string;
  /** §63's quantity. Never added to measured_change. */
  learning_captured: Record<string, number>;
  /** §63's quality. */
  measured_change: Record<string, unknown>;
  dimensions: LearningDimension[];
  overfitting?: {
    possible_overfitting: boolean;
    development_delta_points: number;
    validation_delta_points: number;
    gap_points: number;
    affected_families: string[];
    recent_changes: string[];
    critical_validation_regressions: string[];
    recommended_review: string;
  };
  release_gate?: { may_activate: boolean; because: string };
  hygiene?: Record<string, unknown>;
  sealed_holdout?: {
    version: string;
    /** Always false. §58 names this screen among the six. */
    content_shown: boolean;
    why: string;
  };
  these_are_not_the_same_thing?: string;
  quantity_is_not_quality?: string;
  /** Set when there is no baseline or no snapshot in the window. */
  why?: string;
};

export type LearningWindows = {
  windows: { id: string; anchored: boolean }[];
  triggers: { id: string; marks_a_change: boolean }[];
  note: string;
};

export type LearningTimeline = {
  window: string;
  points: {
    snapshot_id: string;
    at: string;
    trigger: string;
    marks_a_change: boolean;
    development: Record<string, number>;
    validation: Record<string, number>;
    critical_failures_validation: number;
    captured: number;
    activated: number;
  }[];
  note: string;
};

export type LearningPartitions = {
  partitions: {
    id: string;
    means: string;
    used_for: string[];
    may_tune_against: boolean;
    why_not: string;
  }[];
  sealed_holdout_never_reaches: { audience: string; because: string }[];
  aggregate_fields_only: string[];
  hygiene: {
    window_days: number;
    development_runs: number;
    validation_runs: number;
    sealed_holdout_runs: number;
    healthy: boolean;
    findings: string[];
    note: string;
  };
};

export type LearningMeasurementRules = {
  labels: string[];
  evidence_levels: string[];
  minimum_cases: number;
  trivial_cases: number;
  material_points: number;
  stale_days: number;
  attribution_sources: string[];
  rules: Record<string, string>;
};

// ==========================================================================
// Borrower 360 and the corporate relationship graph. Phase 3.

export type Borrower360Tab = {
  key: string;
  label: string;
  datasets: string[];
  is_graph_tab: boolean;
};

export type Borrower360NetworkView = {
  key: string;
  label: string;
  purpose: string;
  requires_ubo_permission: boolean;
  permitted: boolean;
};

export type Borrower360GroupConcept = {
  key: string;
  label: string;
  column: string;
  question: string;
  basis: string;
  /** What this grouping is NOT. The half that stops it being read as one
   *  of the other five. */
  is_not: string;
};

export type Borrower360Kept = {
  id: number;
  kind: string;
  reference: string;
  label: string;
  query: {
    text?: string;
    facets?: Record<string, unknown>;
    flags?: string[];
    borrower_ids?: string[];
  };
  position: number;
  noted: string;
  created_at: string;
};

export type Borrower360Workspace = {
  version: string;
  pins: Borrower360Kept[];
  cohorts: Borrower360Kept[];
  maximum_per_kind: number;
  searchable: string[];
  note: string;
};

export type Borrower360Meta = {
  periods: string[];
  latest_period: string | null;
  tabs: Borrower360Tab[];
  network_views: Borrower360NetworkView[];
  group_concepts: Borrower360GroupConcept[];
  max_graph_depth: number;
  may_see_natural_persons: boolean;
  network_risk_score_label: string;
  searchable_attributes: string[];
  origin: string;
  not_client_data: string;
};

export type Borrower360SearchRow = {
  borrower_id: string;
  legal_name?: string;
  display_name?: string;
  arabic_name?: string;
  segment?: string;
  sector?: string;
  region?: string;
  internal_rating?: string;
  stage?: string;
  /** §18. What a credit officer scans a list of borrowers for. */
  pd_12m?: number;
  ifrs9_ead?: number;
  final_ecl?: number;
  ecl_coverage?: number;
  single_name_utilisation_pct?: number;
  current_dpd?: number;
  arrears_amount?: number;
  average_headroom_pct?: number;
  collateral_coverage_pct?: number;
  connected_group_id?: string;
  group_name?: string;
  watchlist_flag?: boolean;
  breach_flag?: boolean;
  default_flag?: boolean;
};

export type Borrower360Search = {
  search_version: string;
  cohort_kind: string;
  matched: number;
  returned: number;
  truncated: boolean;
  period: string;
  lead_with_aggregate: boolean;
  /** §18. Which governed field the rows are in, and which way round. */
  ordered_by?: string;
  ordered_descending?: boolean;
  order_label?: string;
  borrowers: Borrower360SearchRow[];
  /** Present for a single-name lookup. Never silently resolved. */
  ambiguous?: boolean;
  resolved?: boolean;
  /** Present for a named cohort. The members this quarter does not have. */
  requested?: number;
  not_found?: string[];
  not_found_note?: string;
  aggregate?: Record<string, number | null>;
  origin: string;
};

export type Borrower360Field = {
  value: string | number | boolean | null;
  group: string;
  unit: string;
  authority: string;
  source_dataset: string;
  source_field: string;
  source_period: string;
  /** Set when the caller may not see this field, instead of a zero. */
  withheld_reason?: string;
};

export type Borrower360Row = {
  borrower_id: string;
  period: string;
  period_end_date: string;
  fields: Record<string, Borrower360Field>;
  tabs: { key: string; label: string; fields: string[] }[];
  may_see_natural_persons: boolean;
  origin: string;
  not_client_data: string;
};

export type Borrower360GroupValue = Borrower360GroupConcept & {
  value: string;
  size?: number;
  name?: string;
  role?: string;
  utilisation_pct?: number | null;
  limit_pct?: number;
  status?: string;
  parameter_caveat?: string;
};

export type Borrower360Groups = {
  borrower_id: string;
  period: string;
  as_of?: string;
  status: string;
  reason?: string;
  concepts: Borrower360GroupValue[];
  graph_dq_status?: string;
  note?: string;
  origin: string;
};

export type Borrower360GraphNode = {
  node_id: string;
  node_type: string;
  label: string;
  detail: string;
};

export type Borrower360GraphEdge = {
  edge_id?: string;
  edge_type: string;
  from_node: string;
  to_node: string;
  family: string;
  ownership_pct?: number | null;
  voting_pct?: number | null;
  amount?: number | null;
  role?: string | null;
  source?: string | null;
  confidence?: number | null;
};

export type Borrower360Graph = {
  centre: string;
  period: string;
  as_of: string;
  view: string;
  view_label: string;
  view_purpose: string;
  requested_depth: number;
  reached_depth: number;
  node_count: number;
  edge_count: number;
  truncated: boolean;
  omitted_nodes: number;
  omitted_edges: number;
  truncation_note: string;
  nodes: Borrower360GraphNode[];
  edges: Borrower360GraphEdge[];
  origin: string;
};

export type Borrower360SimilarEdge = {
  edge_type: string;
  from_node: string;
  to_node: string;
  similarity: number;
  shared_evidence: string[];
  shared_evidence_count: number;
  label: string;
  presentation: string;
  creates_control: boolean;
  creates_ubo: boolean;
  creates_group_membership: boolean;
  caveat: string;
  threshold: number;
  threshold_status: string;
};

export type Borrower360Similar = {
  borrower_id: string;
  period: string;
  as_of: string;
  candidates: Borrower360SimilarEdge[];
  candidate_count: number;
  threshold: number;
  threshold_status: string;
  caveat: string;
};

export type Borrower360QualityIssue = {
  issue_id: string;
  period: string;
  check_id: string;
  check: string;
  status: string;
  observed: string;
  threshold: string;
  scope: string;
  affected_entities: number;
  blocks: string;
};

export type Borrower360Quality = {
  period: string;
  checks_run: number;
  passed: number;
  flagged: number;
  rejected: number;
  overall_status: string;
  issues: Borrower360QualityIssue[];
  blocking_rule: string;
  quality_version: string;
};

export type Borrower360LineageField = {
  field: string;
  group: string;
  source_domain: string;
  source_dataset: string;
  source_field: string;
  source_period: string;
  transformation: string;
  authority: string;
  unit: string;
  view_source: { dataset: string; field: string; domain: string };
};

export type Borrower360Lineage = {
  fields: Borrower360LineageField[];
  field_count: number;
  lineage_version: string;
  authoritative_field_count: number;
  note: string;
};
