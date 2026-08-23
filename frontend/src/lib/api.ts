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
  sort_order: number;
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


// ---- Ask IPM --------------------------------------------------------------

export interface PlanStepDef {
  analysis_id: string;
  title: string;
  rationale: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  period: string | null;
}

export interface PlanDef {
  question: string;
  intent: string;
  steps: PlanStepDef[];
  planner: string;
  model_name: string | null;
  follow_ups: string[];
  unmatched: boolean;
  notes: string[];
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

export interface NarrativeFinding {
  text: string;
  tone: "negative" | "warning" | "positive" | "neutral";
  evidence: { label: string; value: number | string | null; unit: string }[];
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
  summary: string;
  findings: NarrativeFinding[];
  metrics: NarrativeMetric[];
  drivers: NarrativeDriver[];
  caveats: string[];
}

export interface Stage {
  id: string;
  label: string;
}

export interface PlannerMode {
  mode: "demo" | "model";
  planner: string;
  model_name: string | null;
  description: string;
  stages: Stage[];
  analysis_count: number;
  periods: string[];
  latest_period: string | null;
  dimensions: Record<string, number>;
  supported_modifications: { kind: string; label: string; example: string }[];
}

export interface InvestigationResponse {
  question: string;
  plan: PlanDef;
  intent: string;
  steps: ExecutedStep[];
  narrative: Narrative;
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
  mode: { mode: string; planner: string; model_name: string | null; description: string };
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
  mode: { mode: string; planner: string; model_name: string | null; description: string };
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
        : `Cannot reach the IPM backend at ${API_BASE_URL}. Is it running?`,
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

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export interface ExecuteOptions {
  params?: Record<string, unknown>;
  period?: string | null;
  filters?: Record<string, unknown>;
  persist?: boolean;
}

export const api = {
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

  // ---- ask IPM ----
  askMode: () => request<PlannerMode>("/ask/mode"),
  askSuggestions: () =>
    request<{ questions: { question: string; note: string }[] }>("/ask/suggestions"),
  briefing: () => request<Briefing>("/ask/briefing", { timeoutMs: 60_000 }),
  recentInvestigations: (limit = 8) =>
    request<{ investigations: RecentInvestigation[] }>(`/ask/recent?limit=${limit}`),
  ask: (question: string, options: { projectId?: number; chatId?: number } = {}) =>
    request<InvestigationResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        project_id: options.projectId ?? null,
        chat_id: options.chatId ?? null,
        persist: true,
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
};
