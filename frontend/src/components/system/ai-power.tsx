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
 *   GOVERNED LOCAL READER no external provider is configured at all
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
          {/*
            "AI OFFLINE" described a component as broken. Nothing is broken:
            with no external provider configured the deterministic reader
            parses the question, the governed runtime executes it and the
            answer is traceable — it is a MODE this product supports, and on
            a bank's own network it may be the only permitted one. So the
            chip names the mode the product is actually running in.
          */}
          {offline ? "GOVERNED LOCAL READER" : label}
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

              <QuickCheck
                plan={status?.quick_check ?? null}
                running={running}
                error={error}
                onRun={start}
              />

              <LiveVerification state={status?.live_verification ?? null} />
              <Certification state={status?.certification ?? null} />

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

/**
 * QUICK INTELLIGENCE CHECK — what this installation can do, right now.
 *
 * Three hidden benchmark threads through the live path, against this bank's
 * own data. It answers "is the AI working today", and it is the only one of
 * the two that is a button.
 *
 * The cost is stated before the button, not after. A validation run that
 * quietly makes two hundred model calls is a surprise on somebody's invoice,
 * and one that makes none — because no provider is reachable — must say so
 * rather than returning a score that looks live.
 */
function QuickCheck({
  plan,
  running,
  error,
  onRun,
}: {
  plan: AiStatus["quick_check"] | null;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface-sunken p-3">
      <h3 className="font-display text-[13px] font-semibold text-text-primary">
        Quick intelligence check
      </h3>
      <p className="mt-1 text-[12px] text-text-secondary">
        Three hidden benchmark threads, asked in full through the live path and
        scored against figures recomputed independently.
      </p>

      {plan && (
        <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
          <Fact label="Threads" value="3 of a hidden set" />
          <Fact label="Model calls" value={costOf(plan)} />
        </dl>
      )}
      {plan?.note && (
        <p className="mt-2 text-[11px] text-text-muted">{plan.note}</p>
      )}

      <div className="mt-3">
        <Button onClick={onRun} disabled={running}>
          <Activity className="size-4" aria-hidden />
          {running ? "Running the intelligence check…" : "Run quick check"}
        </Button>
        {running && (
          <p className="mt-2 text-[12px] text-text-muted">
            Three threads are being asked in full and every figure recomputed
            independently. This takes a minute or two.
          </p>
        )}
        {error && <p className="mt-2 text-[12px] text-negative">{error}</p>}
      </div>
    </section>
  );
}

function costOf(plan: AiStatus["quick_check"]): string {
  if (!plan.model_calls_if_live) return "none — no provider reachable";
  return `up to ${plan.model_calls_if_live}`;
}

/**
 * FULL INTELLIGENCE CERTIFICATION — what this BUILD was proved to do.
 *
 * Deliberately not a button. The sealed holdout lives outside the application
 * and the product is forbidden to import it: a product that can reach its own
 * exam has no exam. Certification therefore happens at build time, and what is
 * shown here is the frozen result — or, honestly, that there isn't one.
 *
 * UNCERTIFIED is the normal state of a development image and it says so plainly
 * rather than leaving the space blank, which would read as certified to anyone
 * who did not know to look.
 */
/**
 * Whether the live model path has actually been proved on this build.
 *
 * The distinction this exists to keep visible: a green quick check with no
 * provider configured exercises the deterministic reader and proves nothing
 * about the model. This panel says LIVE VERIFIED only when a recorded
 * verification made real calls, on this commit, with this model
 * configuration — and says NOT VERIFIED, out loud, the rest of the time.
 *
 * The caveat under it is not decoration. A live verification proves the path
 * ran and conformed on the cases it exercised; it is not a measure of
 * accuracy, and a product that lets one be read as the other has mis-sold
 * itself.
 */
function LiveVerification({
  state,
}: {
  state: AiStatus["live_verification"] | null;
}) {
  if (!state) return null;

  const label = state.live_verified
    ? "LIVE VERIFIED"
    : state.stale
      ? "STALE"
      : "NOT VERIFIED";
  const tone = state.live_verified
    ? "text-positive"
    : state.stale
      ? "text-warning"
      : "text-text-muted";

  return (
    <section className="rounded-lg border border-border bg-surface-sunken p-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-[13px] font-semibold text-text-primary">
          Live model verification
        </h3>
        <span className={cn("font-mono text-[11px] font-semibold", tone)}>
          {label}
        </span>
      </div>

      {state.live_verified ? (
        <>
          <p className="mt-1.5 text-[12px] text-text-secondary">
            {state.calls} live provider {state.calls === 1 ? "call" : "calls"} on
            this build, covering {state.components.join(", ") || "the live path"}.
          </p>
          {/* What it was measured against. A badge whose subject cannot be
              named is a badge nobody can check. */}
          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            <Fact label="Commit" value={state.verified_short_sha} mono />
            <Fact label="Configuration" value={state.verified_fingerprint} mono />
            <Fact label="Mode" value={state.mode} />
            <Fact label="Verified" value={state.verified_at.slice(0, 16).replace("T", " ")} />
          </dl>
          <p className="mt-1.5 text-[11px] text-text-muted">{state.caveat}</p>
        </>
      ) : (
        <>
          <p className="mt-1.5 text-[12px] text-text-secondary">
            {state.reason || "This build has not been verified against the live model."}
          </p>
          {/* Stale means a verification once existed and something moved.
              Showing both sides answers "moved how?" without a second click. */}
          {state.stale && (
            <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
              <Fact label="Verified on" value={state.verified_short_sha} mono />
              <Fact label="Running" value={state.running_short_sha} mono />
              {state.verified_fingerprint !== state.running_fingerprint && (
                <Fact label="Model configuration" value="changed" />
              )}
            </dl>
          )}
          <p className="mt-1.5 text-[11px] text-text-muted">{state.why}</p>
          <code className="mt-2 block rounded bg-surface px-2 py-1 font-mono text-[11px] text-text-secondary">
            {state.command}
          </code>
        </>
      )}
    </section>
  );
}

function Certification({ state }: { state: AiStatus["certification"] | null }) {
  if (!state) return null;

  const tone =
    state.status === "CERTIFIED"
      ? "text-positive"
      : state.status === "NOT_PASSED"
        ? "text-negative"
        : "text-warning";

  return (
    <section className="rounded-lg border border-border bg-surface-sunken p-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-[13px] font-semibold text-text-primary">
          Full intelligence certification
        </h3>
        <span className={cn("font-mono text-[11px] font-semibold", tone)}>
          {state.status.replace("_", " ")}
        </span>
      </div>

      <p className="mt-1.5 text-[12px] text-text-secondary">{state.sentence}</p>

      {state.status === "CERTIFIED" && (
        <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
          <Fact label="Release" value={state.release_id} mono />
          <Fact label="Sealed cases" value={String(state.cases)} />
          <Fact label="Critical" value={String(state.critical_cases)} />
          <Fact label="Holdout" value={state.holdout_version} mono />
        </dl>
      )}

      {state.critical_failures.length > 0 && (
        <ul className="mt-2 space-y-1 text-[11px] text-negative">
          {state.critical_failures.map((failure) => (
            <li key={failure}>{failure}</li>
          ))}
        </ul>
      )}

      {state.corrections.length > 0 && (
        <details className="mt-2.5">
          <summary className="cursor-pointer text-[11px] text-text-muted hover:text-text-secondary">
            {state.corrections.length} sealed expectation
            {state.corrections.length === 1 ? "" : "s"} revised — see why
          </summary>
          <ul className="mt-1.5 space-y-1.5 border-l border-border pl-2.5">
            {state.corrections.map((correction) => (
              <li key={correction.case} className="text-[11px]">
                <span className="font-mono text-text-secondary">
                  {correction.case}
                </span>
                <p className="text-text-muted">{correction.why}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-2.5 text-[11px] text-text-muted">
        {state.why_not_runnable} Run it with{" "}
        <code className="rounded bg-surface px-1 py-0.5 font-mono text-[10px]">
          {state.command}
        </code>
        .
      </p>
    </section>
  );
}

function Fact({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-text-muted">{label}</dt>
      <dd
        className={cn(
          "text-text-primary",
          mono && "font-mono text-[10.5px]",
        )}
      >
        {value}
      </dd>
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
