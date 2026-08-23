/**
 * The backend API client.
 *
 * Every call to the FastAPI backend goes through here. One place that knows the
 * base URL, sets the headers, applies a timeout, and turns a failure into a
 * typed error — rather than each screen inventing its own `fetch`.
 *
 * The types below mirror backend/api/schemas.py. When that file changes, this
 * one changes with it; keeping them adjacent and named identically is what makes
 * the drift obvious in review.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const API_PREFIX = "/api/v1";
const DEFAULT_TIMEOUT_MS = 15_000;

// ---------------------------------------------------------------------------
// Types — mirror backend/api/schemas.py
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
}

export interface EngineLibraryResponse {
  total: number;
  certified: number;
  analyses: AnalysisSummary[];
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * A failed API call.
 *
 * `message` is always safe and useful to show a user: either the backend's own
 * explanation, or a plain-English description of why we could not reach it.
 * Screens render `error.message` directly rather than inventing their own copy.
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

  /** True when the backend could not be reached at all, rather than refusing. */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

// ---------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------

interface RequestOptions extends Omit<RequestInit, "signal"> {
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...init } = options;

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
        "Content-Type": "application/json",
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
    // The backend returns a consistent error shape; fall back gracefully if
    // something upstream (a proxy, say) returned HTML instead.
    let code = "http_error";
    let message = `Request failed with status ${response.status}.`;
    let detail: Record<string, unknown> = {};
    try {
      const body = await response.json();
      code = body.error ?? code;
      message = body.message ?? message;
      detail = body.detail ?? {};
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

export const api = {
  /** System health. Polled by the status indicator in the header. */
  health: (timeoutMs?: number) =>
    request<HealthResponse>("/health", { timeoutMs: timeoutMs ?? 8_000 }),

  /** The governed data catalogue — the Data Dictionary. */
  catalog: () => request<CatalogResponse>("/catalog"),

  /** Registered analytical capabilities — the Engine Builder Analysis Library. */
  engineLibrary: () => request<EngineLibraryResponse>("/engine/library"),
};
