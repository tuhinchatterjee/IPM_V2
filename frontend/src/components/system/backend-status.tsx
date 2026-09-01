"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  ApiError,
  api,
  type ComponentStatus,
  type HealthResponse,
} from "@/lib/api";

const POLL_INTERVAL_MS = 20_000;

type State =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "error"; message: string };

/**
 * Polls the backend and reports what is actually working.
 *
 * The important design choice is honesty. It does not show a single green light
 * that means "probably fine": it names each dependency and repeats the backend's
 * own explanation, because for a non-developer setting CreditProbe up, "PostgreSQL is not
 * configured — start it with docker compose up -d db" is the whole answer.
 */
export function useBackendHealth() {
  const [state, setState] = React.useState<State>({ kind: "loading" });
  // Bumped to force an immediate re-check when the user presses "Try again".
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    // `cancelled` stops a slow reply from overwriting newer state after the
    // component has unmounted or the poll has been superseded.
    let cancelled = false;

    async function poll() {
      try {
        const health = await api.health();
        if (!cancelled) setState({ kind: "ready", health });
      } catch (error) {
        if (cancelled) return;
        setState({
          kind: "error",
          message:
            error instanceof ApiError
              ? error.message
              : "The backend could not be reached.",
        });
      }
    }

    void poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [nonce]);

  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);

  return { state, refresh };
}

const STATUS_STYLE: Record<
  ComponentStatus,
  { label: string; variant: "positive" | "warning" | "negative" | "default" }
> = {
  ok: { label: "Operational", variant: "positive" },
  empty: { label: "No data yet", variant: "default" },
  not_configured: { label: "Not configured", variant: "warning" },
  degraded: { label: "Degraded", variant: "warning" },
  unavailable: { label: "Unavailable", variant: "negative" },
};

/** Compact indicator for the application header. */
export function BackendStatusIndicator() {
  const { state } = useBackendHealth();

  if (state.kind === "loading") {
    return (
      <span className="inline-flex items-center gap-2 text-xs text-text-muted">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        Checking backend
      </span>
    );
  }

  if (state.kind === "error") {
    return (
      <span
        className="inline-flex items-center gap-2 text-xs font-medium text-negative"
        title={state.message}
      >
        <XCircle className="size-3.5" aria-hidden />
        Backend offline
      </span>
    );
  }

  const { status, version } = state.health;
  const Icon =
    status === "ok" ? CheckCircle2 : status === "degraded" ? AlertTriangle : XCircle;
  const tone =
    status === "ok" ? "text-positive" : status === "degraded" ? "text-warning" : "text-negative";

  return (
    <span className={cn("inline-flex items-center gap-2 text-xs font-medium", tone)}>
      <Icon className="size-3.5" aria-hidden />
      {status === "ok" ? "All systems operational" : `Backend ${status}`}
      <span className="font-normal text-text-muted">v{version}</span>
    </span>
  );
}

/** Full panel listing every dependency and what it says about itself. */
export function BackendStatusPanel() {
  const { state, refresh } = useBackendHealth();

  if (state.kind === "loading") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>System status</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  if (state.kind === "error") {
    return (
      <Card className="border-negative/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-negative">
            <XCircle className="size-4" aria-hidden />
            Cannot reach the CreditProbe backend
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-text-secondary">{state.message}</p>
          <div className="rounded-md border border-border bg-surface-sunken p-4">
            <p className="mb-2 text-xs font-medium text-text-secondary">
              Start it by running this in the project folder:
            </p>
            <code className="block font-mono text-xs text-text-primary">
              ./scripts/dev.sh
            </code>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="text-xs font-medium text-accent hover:underline"
          >
            Try again
          </button>
        </CardContent>
      </Card>
    );
  }

  const { health } = state;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>System status</CardTitle>
        <Badge variant={health.status === "ok" ? "positive" : "warning"}>
          {health.status === "ok" ? "Operational" : health.status}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {health.components.map((component) => {
          const style = STATUS_STYLE[component.status];
          return (
            <div
              key={component.name}
              className="flex items-start justify-between gap-4 rounded-md border border-border bg-surface-sunken px-4 py-3"
            >
              <div className="min-w-0">
                <p className="font-mono text-xs font-medium text-text-primary">
                  {component.name}
                </p>
                <p className="mt-0.5 text-xs text-text-muted">{component.detail}</p>
              </div>
              <Badge variant={style.variant}>{style.label}</Badge>
            </div>
          );
        })}
        <p className="pt-2 text-xs text-text-muted">
          {health.phase} · environment: {health.environment} · re-checked every{" "}
          {POLL_INTERVAL_MS / 1000}s
        </p>
      </CardContent>
    </Card>
  );
}
