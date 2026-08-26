"use client";

import * as React from "react";
import { Activity, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRole } from "@/components/system/role-switcher";
import {
  ComponentBreakdown,
  ValidationCaseDetail,
  toneOf,
  verdictTone,
} from "@/components/system/validation-case";
import { api, ApiError } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import type { AiStatus, ValidationCase, ValidationRun } from "@/lib/api";

/**
 * AI POWERED — a claim the product has to be able to back.
 *
 * The chip says one of these, and every one of them is earned rather than
 * configured:
 *
 *   AI POWERED            nothing has been checked yet
 *   AI POWERED · HIGH     a check scored 90 or above
 *   AI POWERED · GOOD     75–89
 *   AI POWERED · LIMITED  60–74
 *   AI POWERED · DEGRADED below 60
 *   AI POWERED · STALE    the model, build, benchmark or data has moved on
 *   AI UNVERIFIED         a key is configured and no case reached the model
 *   AI OFFLINE            no provider is configured at all
 *
 * The last two matter most. A check where every case fell through to the
 * deterministic reader can still score a hundred — it measures the governed
 * runtime, which is worth knowing and is not what the button claims. So it does
 * not get a band, and the panel says "governed runtime only" beside the number.
 *
 * Pressing it opens the check: three hidden benchmark threads, run through the
 * live path, each scored against an independently computed reference. Every
 * case is clickable, and what opens shows the question, CreditProbe's actual
 * answer — including a bad one — the reference, and why the score was not 100%.
 *
 * It runs when somebody presses the button. Not on a timer, not on page load:
 * a hidden benchmark makes real model calls and reads the whole analytical
 * layer, and spending a bank's provider budget on a number nobody asked for is
 * not a feature.
 */
export function AiPowerControl() {
  const [open, setOpen] = React.useState(false);
  const status = useAsync(() => api.aiStatus(), []);

  const label = status.data?.label ?? "AI POWERED";
  const tone = status.data?.tone ?? "neutral";
  const offline = status.data?.ai.state === "offline";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="AI validation — run an intelligence check"
        className={cn(
          "flex h-8 items-center gap-1.5 rounded-md border px-2 text-[11px] font-medium transition-colors",
          "border-border bg-surface-sunken hover:bg-surface-hover",
          chipTone(tone, offline),
        )}
      >
        <Sparkles className="size-3.5" aria-hidden />
        <span className="hidden font-display tracking-[0.02em] sm:inline">
          {offline ? "AI OFFLINE" : label}
        </span>
      </button>

      {open && <ValidationPanel status={status.data} onClose={() => setOpen(false)} />}
    </>
  );
}

function chipTone(tone: string, offline: boolean): string {
  if (offline) return "text-text-muted";
  switch (tone) {
    case "green":
      return "text-positive";
    case "teal":
      return "text-info";
    case "amber":
      return "text-warning";
    case "red":
      return "text-negative";
    default:
      return "text-text-secondary";
  }
}

function ValidationPanel({
  status,
  onClose,
}: {
  status: AiStatus | null;
  onClose: () => void;
}) {
  const { role } = useRole();
  const isAdministrator = role === "ADMIN";

  const [run, setRun] = React.useState<ValidationRun | null>(status?.latest ?? null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [openCase, setOpenCase] = React.useState<ValidationCase | null>(null);
  const history = useAsync(() => api.validationHistory(10), []);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const start = React.useCallback(async () => {
    setRunning(true);
    setError(null);
    setOpenCase(null);
    try {
      setRun(await api.runValidation());
      history.reload();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "The intelligence check could not be completed.",
      );
    } finally {
      setRunning(false);
    }
  }, [history]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-2xl flex-col overflow-hidden border-l border-border bg-surface shadow-xl"
        role="dialog"
        aria-label="AI validation"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="font-display text-[15px] font-semibold text-text-primary">
              AI validation
            </h2>
            <p className="mt-0.5 text-[12px] text-text-muted">
              {status
                ? `${status.benchmark_count} hidden benchmark threads, ${status.benchmark_turns} turns. Three are drawn at random each time — one about the data, one calculation, one conversation.`
                : "Checking what the AI can actually do."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {openCase ? (
            <ValidationCaseDetail
              detail={openCase}
              onBack={() => setOpenCase(null)}
              isAdministrator={isAdministrator}
            />
          ) : (
            <>
              <ProviderState status={status} />

              <div>
                <Button onClick={start} disabled={running}>
                  <Activity className="size-4" aria-hidden />
                  {running ? "Running the intelligence check…" : "Run intelligence check"}
                </Button>
                {running && (
                  <p className="mt-2 text-[12px] text-text-muted">
                    Three threads are being asked in full and every figure
                    recomputed independently. This takes a minute or two.
                  </p>
                )}
                {error && (
                  <p className="mt-2 text-[12px] text-negative">{error}</p>
                )}
              </div>

              {run ? (
                <RunSummary
                  run={run}
                  onOpenCase={setOpenCase}
                  stale={Boolean(run.stale)}
                />
              ) : (
                <p className="rounded-md border border-border bg-surface-sunken px-3 py-2.5 text-[12px] text-text-secondary">
                  No intelligence check has been run on this installation yet.
                  Nothing about the AI has been verified here, and the control in
                  the header says so rather than implying otherwise.
                </p>
              )}

              <HistoryList runs={history.data?.runs ?? []} current={run?.id ?? null} />
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function ProviderState({ status }: { status: AiStatus | null }) {
  if (!status) return null;
  const ai = status.ai;
  const build = status.build;
  return (
    <section className="rounded-lg border border-border bg-surface-sunken px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={stateVariant(ai.state)}>{ai.label}</Badge>
        {ai.model && (
          <span className="font-mono text-[11px] text-text-muted">{ai.model}</span>
        )}
        <span className="font-mono text-[11px] text-text-muted">
          build {build.short_sha} · v{build.version}
        </span>
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-text-secondary">
        {ai.detail}
      </p>
      {build.stale && (
        <p className="mt-1.5 text-[12px] text-warning">{build.stale_detail}</p>
      )}
      {ai.counts.total > 0 && (
        <p className="mt-1.5 font-mono text-[11px] text-text-muted">
          {ai.counts.succeeded} of {ai.counts.total} model calls succeeded ·
          median {ai.median_latency_ms}ms
          {ai.last_failure ? ` · last failure: ${ai.last_failure.failure_detail}` : ""}
        </p>
      )}
    </section>
  );
}

function stateVariant(state: string) {
  switch (state) {
    case "connected":
      return "positive" as const;
    case "degraded":
      return "negative" as const;
    case "configured":
      return "warning" as const;
    default:
      return "default" as const;
  }
}

function RunSummary({
  run,
  onOpenCase,
  stale,
}: {
  run: ValidationRun;
  onOpenCase: (detail: ValidationCase) => void;
  stale: boolean;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p
            className={cn(
              "font-display text-[13px] font-semibold tracking-[0.04em]",
              graded(run) ? toneOf(run.score) : "text-text-secondary",
            )}
          >
            {stale ? run.stale_label || `${run.label} · STALE` : run.label}
          </p>
          <p className="mt-0.5 text-[12px] text-text-muted">
            {[
              run.provider && run.provider !== "none"
                ? run.model || run.provider
                : "no provider",
              `benchmark v${run.benchmark_version}`,
              run.data_version,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="text-right">
          <p
            className={cn(
              "font-display text-3xl font-semibold tabular-nums",
              graded(run) ? toneOf(run.score) : "text-text-secondary",
            )}
          >
            {Math.round(run.score)}
            <span className="ml-1 text-base text-text-muted">/ 100</span>
          </p>
          {/* A score earned without reaching the model grades the governed
              runtime, not the AI. Saying so beside the number is the difference
              between a measurement and a boast. */}
          {!graded(run) && (
            <p className="mt-0.5 text-[11px] text-text-muted">
              governed runtime only
            </p>
          )}
        </div>
      </div>

      {stale && run.stale_because && run.stale_because.length > 0 && (
        <p className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-[12px] text-warning">
          This score no longer describes what is running —{" "}
          {run.stale_because.join(", ")}. Run the check again.
        </p>
      )}

      {run.notes.map((note, index) => (
        <p
          key={index}
          className="rounded-md border border-border bg-surface-sunken px-3 py-2 text-[12px] text-text-secondary"
        >
          {note}
        </p>
      ))}

      <ComponentBreakdown
        components={run.components}
        overall={run.score}
        verdict={graded(run) ? "PASS" : "FAIL"}
      />

      <div>
        <h3 className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
          Tests run
        </h3>
        <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
          {run.cases.map((detail) => (
            <li key={detail.benchmark_id}>
              <button
                type="button"
                onClick={() => onOpenCase(detail)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface-hover"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
                    {detail.category}
                  </p>
                  <p className="truncate text-[13px] text-text-primary">
                    {summarise(detail)}
                  </p>
                </div>
                <span className="shrink-0 font-mono text-[11px] text-text-muted">
                  {(detail.latency_ms / 1000).toFixed(1)}s
                </span>
                <span
                  className={cn(
                    "w-11 shrink-0 text-right font-display text-[13px] font-semibold tabular-nums",
                    verdictTone(detail.score, detail.verdict),
                  )}
                >
                  {Math.round(detail.score)}%
                </span>
                <Badge
                  variant={
                    detail.verdict === "PASS"
                      ? "positive"
                      : detail.verdict === "PARTIAL"
                        ? "warning"
                        : "negative"
                  }
                >
                  {detail.verdict}
                </Badge>
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[11px] text-text-muted">
          Every row opens. The reference answer inside was computed after the
          case ran, by a separate implementation, and was never shown to the
          model.
        </p>
      </div>
    </section>
  );
}

/** Whether this run actually graded the AI, rather than the runtime beneath it. */
function graded(run: ValidationRun): boolean {
  return run.band !== "OFFLINE" && run.band !== "UNVERIFIED";
}

/** The thread in one line — its first question, and how many followed. */
function summarise(detail: ValidationCase): string {
  const first = detail.turns[0]?.question ?? detail.title;
  const rest = detail.turns.length - 1;
  return rest > 0 ? `${first}  → ${rest} follow-up${rest > 1 ? "s" : ""}` : first;
}

function HistoryList({
  runs,
  current,
}: {
  runs: ValidationRun[];
  current: number | null;
}) {
  const previous = runs.filter((r) => r.id !== current);
  if (previous.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
        Previous checks
      </h3>
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
        {previous.slice(0, 8).map((run) => (
          <li
            key={run.id}
            className="flex items-center gap-3 px-3 py-2 text-[12px]"
          >
            <span className="w-32 shrink-0 font-mono text-[11px] text-text-muted">
              {formatWhen(run.created_at)}
            </span>
            <span className="min-w-0 flex-1 truncate text-text-secondary">
              {run.model || run.provider || "—"}
            </span>
            <span
              className={cn(
                "shrink-0 font-display font-semibold tabular-nums",
                graded(run) ? toneOf(run.score) : "text-text-muted",
              )}
            >
              {Math.round(run.score)}
            </span>
            <span className="w-20 shrink-0 text-right text-text-muted">
              {run.band}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-text-muted">
        A score is only useful next to the last one. A change of model, build,
        benchmark or data marks the previous score stale rather than comparing
        across it.
      </p>
    </section>
  );
}

function formatWhen(iso?: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
