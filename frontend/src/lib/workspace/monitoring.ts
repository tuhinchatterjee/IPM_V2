/** Monitoring Centre client (P10). */

import { wsGet, wsSend } from "./client";
import type { Filter, GovernedObject } from "./objects";

export type AlertState = "NEW" | "ACTIVE" | "WORSENING" | "ACKNOWLEDGED" | "RESOLVED" | "SUPPRESSED";

export interface AlertSummary {
  alert_id: string;
  version: number;
  state: AlertState;
  title: string;
  alert_type: "breach" | "change" | "refresh_failure";
  severity: string;
  lens_id: string;
  lens_name: string;
  rule_id: string;
  rule_name: string;
  metric_id: string;
  metric_version: number | null;
  unit?: string;
  domain_id: string;
  comparison: string;
  threshold: number | null;
  observed: number | null;
  prior: number | null;
  period: string;
  first_seen: number;
  last_seen: number;
  assignee: string;
  demo_historical: boolean;
  label: string;
  release_id: string;
}

export interface LensHealth {
  lens_id: string;
  name: string;
  cadence: string;
  last_status: string;
  last_at: number | null;
  last_success_at: number | null;
  stale: boolean;
  due: boolean;
  why: string;
}

export interface MonitoringView {
  view: string;
  alerts: AlertSummary[];
  counts: Record<"new" | "active" | "worsening" | "acknowledged" | "resolved" | "changes" | "history", number>;
  total: number;
  state: string;
  lens_health: LensHealth[];
}

export interface AlertDetail {
  alert: GovernedObject<Record<string, unknown>>;
  events: { event_id: string; from_state: string; to_state: string; actor_id: string; note: string; observed: string; at: number }[];
  open_lens: { lens_id: string; periods: Record<string, string>; filters: (Filter & { domain?: string })[] };
  metric: string | null;
  can_act: boolean;
}

export const readMonitoring = (q: { view?: string; severity?: string; lens?: string; domain?: string; assignee?: string }) => {
  const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
  return wsGet<MonitoringView>(`/monitoring?${p.toString()}`);
};

export const readAlert = (id: string) => wsGet<AlertDetail>(`/monitoring/alerts/${encodeURIComponent(id)}`);

export const actOnAlert = (id: string, action: "acknowledge" | "resolve" | "suppress" | "reopen" | "assign" | "comment", note = "", assignee = "") =>
  wsSend<GovernedObject>(`/monitoring/alerts/${encodeURIComponent(id)}/${action}`, { note, assignee });

export const investigateAlert = (id: string) => wsSend<{ thread_id: string; cohort_id: string }>(`/monitoring/alerts/${encodeURIComponent(id)}/investigate`, {});

export const alertCohort = (id: string) => wsSend<GovernedObject>(`/monitoring/alerts/${encodeURIComponent(id)}/cohort`, {});

export const runDueRefreshes = () => wsSend<{ refreshed: unknown[]; skipped: unknown[]; failed: unknown[] }>("/monitoring/tick", {});
