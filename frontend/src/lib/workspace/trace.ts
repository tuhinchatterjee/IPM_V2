/**
 * The governance Trace of a workspace object and its governed export
 * package. The Trace only reads; the package is assembled on the server from
 * the stored record, with the page's chart snapshots attached.
 */

import { workspaceUrl, wsGet } from "@/lib/workspace/client";

export interface LedgerLink {
  seq: number;
  record_hash: string;
  chain_hash: string;
  backfilled: boolean;
  links: boolean;
  row_matches: boolean;
}

export interface TraceVersion {
  version: number;
  status: string;
  title: string;
  reason: string;
  operation: string;
  content_hash: string;
  content_verified: boolean;
  release_id: string;
  fingerprint: string;
  period: string;
  created_at: number;
  created_by: string;
  ledger: LedgerLink | null;
}

export interface TraceEvent {
  at: number | null;
  type: string;
  actor: string;
  detail: string;
  version?: number;
  record_id?: string;
  ledger?: LedgerLink | null;
}

export interface ObjectTrace {
  object_id: string;
  kind: string;
  title: string;
  version: number;
  owner_id: string;
  domain_id: string;
  release_id: string;
  fingerprint: string;
  period: string;
  status: string;
  seeded: boolean;
  digests: Record<string, string>;
  versions: TraceVersion[];
  lineage: {
    ancestors: { object_id: string; version: number; depth: number; readable: boolean; kind?: string; title?: string; content_hash?: string; operation?: string }[];
    descendants: { object_id: string; version: number; kind: string; title: string; operation: string }[];
    truncated: boolean;
    max_depth: number;
  };
  events: TraceEvent[];
  llm_exchange: {
    threads: string[];
    visible: boolean;
    note?: string;
    calls: { exchange_id: string; run_id: string; thread_id: string; seq: number; purpose: string; model: string; status: string; started_at: number; replay_of: string; hashes: Record<string, string> }[];
  };
  integrity: { ok: boolean; content_hashes_verified: number; ledger_links: number; unledgered: number; broken: number; note: string; problem?: string; message?: string };
  model_calls: number;
}

export interface LedgerReport {
  tenant_id: string;
  ok: boolean;
  entries: number;
  backfilled: number;
  chain_head: string;
  problems: { seq?: number; record_id: string; record_kind?: string; problem: string }[];
  problem_count: number;
}

export interface PackageReport {
  ok: boolean;
  files_checked: number;
  objects_checked: number;
  problems: { path: string; problem: string; rows?: number }[];
  root: { object_id: string; version: number; kind: string; content_hash: string } | null;
}

export const readTrace = (objectId: string) => wsGet<ObjectTrace>(`/trace/objects/${encodeURIComponent(objectId)}`);
export const verifyLedger = () => wsGet<LedgerReport>("/trace/ledger/verify");

export { shortHash, snapshotName } from "./trace-format";

export interface Snapshot {
  name: string;
  format: "svg" | "png" | "plotly";
  data: unknown;
}

/**
 * Download the governed package for an object. `snapshots` are the page's
 * own rendered charts (SVG) and their Plotly figure specs.
 */
export async function downloadPackage(objectId: string, opts: { includeLlmExchange?: boolean; snapshots?: Snapshot[] } = {}): Promise<{ files: number; rootHash: string }> {
  const response = await fetch(workspaceUrl(`/exports/objects/${encodeURIComponent(objectId)}`), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_llm_exchange: Boolean(opts.includeLlmExchange), snapshots: opts.snapshots ?? [] }),
  });
  if (!response.ok) {
    let message = `Export failed (${response.status})`;
    try {
      const body = await response.json();
      message = body?.detail?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `${objectId}.zip`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { files: Number(response.headers.get("X-Package-Files") ?? 0), rootHash: response.headers.get("X-Package-Root-Hash") ?? "" };
}

export async function verifyPackage(file: Blob): Promise<PackageReport> {
  const response = await fetch(workspaceUrl("/exports/verify"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/zip" },
    body: file,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail?.message ?? `Verify failed (${response.status})`);
  return body as PackageReport;
}
