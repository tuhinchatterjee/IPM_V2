/**
 * Types and pure helpers for Trace > LLM Exchange and the AI Model Lab.
 * Mirrors `backend/workspace/exchange_api.py`; snake_case as the server sends.
 */

import { qs, workspaceUrl, wsGet, wsSend } from "@/lib/workspace/client";

export interface CompositionPart {
  component: string;
  detail: string;
  bytes: number;
  estimated_tokens: number;
  token_basis: string;
}

export interface ExchangeCall {
  exchange_id: string;
  run_id: string;
  thread_id: string;
  seq: number;
  purpose: string;
  role: string;
  provider: string;
  adapter: string;
  requested_model: string;
  resolved_model: string;
  status: string;
  error: string;
  stop_reason: string;
  request_id: string;
  started_at: number;
  ended_at: number;
  provider_ms: number;
  replay_of: string;
  surface: string;
  settings: Record<string, unknown>;
  canonical_request: Record<string, unknown>;
  adapter_request: unknown[];
  adapter_translation: string[];
  raw_response: unknown[];
  raw_response_available: boolean;
  normalized_response: {
    text?: string;
    tool_calls?: { id: string; name: string; input: unknown }[];
    stop_reason?: string;
    model?: string;
    usage?: Record<string, number>;
  };
  usage: Record<string, number>;
  context_composition: {
    parts: CompositionPart[];
    totals_bytes: Record<string, number>;
    total_bytes: number;
    message_count: number;
    tool_count: number;
  };
  transmitted_data: { tool_results: number; rows: number; bytes: number };
  hashes: Record<string, string>;
  redactions: { path: string; reason: string }[];
  hidden_reasoning_recorded: boolean;
}

export interface GrowthRow {
  seq: number;
  exchange_id: string;
  purpose: string;
  total_bytes: number;
  growth_bytes: number;
  messages: number;
  tools: number;
  system_bytes: number;
  tool_schema_bytes: number;
  tool_result_bytes: number;
  input_tokens_exact: number;
  output_tokens_exact: number;
}

export interface TimelineItem {
  at: number;
  kind: "llm_call" | "creditprobe_event";
  label: string;
  detail: string;
  seq?: number;
  exchange_id?: string;
  event_type?: string;
  stage?: string;
}

export interface RunExchange {
  run_id: string;
  thread_id: string;
  question: string;
  release_id: string;
  recorder: { flag: string; enabled: boolean; record_version: number; calls_recorded: number };
  calls: ExchangeCall[];
  timeline: TimelineItem[];
  context_growth: GrowthRow[];
  data_visibility: {
    available_to_creditprobe: {
      release_id: string;
      release_relations: Record<string, number>;
      release_rows_total: number;
      artifacts: { artifact_id: string; kind: string; rows_stored: number; rows_produced: number; relations: string[] }[];
      artifact_rows_produced: number;
    };
    actually_transmitted_to_model: {
      unique_tool_results: number;
      rows: number;
      bytes: number;
      per_call: { seq: number; tool_results: number; rows: number; bytes: number }[];
      basis: string;
    };
  };
  notes: string[];
}

export const readRunExchange = (runId: string) =>
  wsGet<RunExchange>(`/llm-exchange/runs/${encodeURIComponent(runId)}`);

export const exchangeExportUrl = (runId: string) =>
  workspaceUrl(`/llm-exchange/runs/${encodeURIComponent(runId)}/export`);

export interface LabRow {
  exchange_id: string;
  run_id: string;
  thread_id: string;
  surface: string;
  seq: number;
  purpose: string;
  provider: string;
  adapter: string;
  requested_model: string;
  resolved_model: string;
  status: string;
  stop_reason: string;
  started_at: number;
  provider_ms: number;
  replay_of: string;
}

export const listLabExchanges = (filters: { model?: string; purpose?: string; run_id?: string }) =>
  wsGet<{ exchanges: LabRow[]; models: string[]; source: string }>(`/model-lab/exchanges${qs(filters)}`);

export interface Comparison {
  a: Record<string, unknown>;
  b: Record<string, unknown>;
  request: {
    same_canonical_request: boolean;
    same_system: boolean;
    same_tools: boolean;
    same_tool_choice: boolean;
    messages: { index: number; same: boolean }[];
    note: string;
  };
  response: {
    same_tool_sequence: boolean;
    tool_names_a: string[];
    tool_names_b: string[];
    same_arguments: boolean;
    same_stop_reason: boolean;
  };
}

export const compareExchanges = (a: string, b: string) =>
  wsGet<Comparison>(`/model-lab/compare${qs({ a, b })}`);

export const labTargets = () =>
  wsGet<{ targets: { target: string; label: string; configured: boolean; requires: string }[]; note: string }>(
    "/model-lab/targets",
  );

export const replayExchange = (exchange_id: string, target: string, model = "") =>
  wsSend<{ status: string; error: string; replay_exchange_id: string; replay_of: string }>("/model-lab/replay", {
    exchange_id,
    target,
    model,
  });

export { COMPONENT_ORDER, compositionFigure, growthFigure } from "./llm-exchange-figures.ts";
