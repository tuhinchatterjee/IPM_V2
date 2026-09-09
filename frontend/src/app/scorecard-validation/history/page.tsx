"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { ResultCard, StateChip }
  from "@/components/scorecard-validation/result-card";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  ScvComparedTest,
  ScvComparison,
  ScvOverview,
  ScvReportHeader,
  ScvRunHeader,
  ScvStoredRun,
} from "@/lib/api";
import { count, technical } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Validation History — the runs, as they were.
 *
 * The cockpit answers "what does this scorecard look like now". This screen
 * answers a different question, and it is the one model-risk governance
 * actually turns on: what did the validation the committee approved say, on
 * the day they approved it?
 *
 * Nothing here recalculates
 * --------------------------
 * Every figure on this page came out of a database row that was written when
 * the run was made. Opening a run from March shows March's numbers against
 * March's limits, computed by March's kernel, over the data as it stood then.
 * If the lake has since gained three months and a threshold has been revised,
 * none of that moves what is on this screen — and the run says so, in its own
 * words, rather than leaving the reader to assume it.
 *
 * `Re-run using current data` therefore does not refresh anything. It creates
 * a NEW run and leaves this one exactly as it is, so the two can be compared.
 * A comparison between a remembered number and a fresh one measures the
 * passage of time and the movement of code at once and cannot separate them;
 * a comparison between two stored runs can, and says which of the five
 * versions moved.
 *
 * What a reader is not allowed to do
 * -----------------------------------
 * Edit a result. There is no control on this page that writes to a stored
 * value, because a validation result somebody can adjust after the fact is
 * not evidence of anything. Corrections are new runs.
 */

const NOTHING_HERE_RECALCULATES =
  "Every figure on this screen was computed when its run was made and has "
  + "been read back unchanged. Re-running produces a new run and leaves this "
  + "one alone.";

// ------------------------------------------------------------ small pieces

function Field({ label, value, hint }: {
  label: string; value: React.ReactNode; hint?: string;
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      <p className="text-sm text-text">{value || "—"}</p>
      {hint && <p className="text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}

function when(stamp: string): string {
  if (!stamp) return "—";
  const at = new Date(stamp);
  if (Number.isNaN(at.getTime())) return stamp;
  return at.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/**
 * How a run was scoped, in the words the reader chose.
 *
 * "Full" and "Discrimination" rather than FULL and CATEGORY: the stored
 * vocabulary is for the database, not for a person reading a list.
 */
function scopeOf(run: ScvRunHeader): string {
  if (run.scope === "FULL") return "Every category";
  if (run.scope === "CATEGORY") {
    return run.requested_categories
      .map((c) => c.charAt(0).toUpperCase() + c.slice(1))
      .join(", ") || "One category";
  }
  if (run.scope === "TEST") return run.requested_tests.join(", ") || "One test";
  return run.scope;
}

const REPORT_TONE: Record<string, string> = {
  FINAL: "border-state-pass/40 bg-state-pass/10 text-state-pass",
  DRAFT: "border-border bg-surface text-text-muted",
  SUPERSEDED: "border-border bg-surface text-text-muted line-through",
};

function ReportChip({ report }: { report: ScvReportHeader }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px]",
        REPORT_TONE[report.status] ?? REPORT_TONE.DRAFT,
      )}
    >
      v{report.version} {report.status}
    </span>
  );
}

// ------------------------------------------------------------- the list

function HistoryRow({ run, chosen, comparing, onOpen, onCompare }: {
  run: ScvRunHeader;
  chosen: boolean;
  comparing: boolean;
  onOpen: (key: string) => void;
  onCompare: (key: string) => void;
}) {
  const findings = Number(
    (run.findings_summary as { total?: number })?.total ?? 0);
  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 transition-colors",
        chosen
          ? "border-border-strong bg-surface-hover"
          : "border-border bg-surface hover:border-border-strong",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => onOpen(run.run_key)}
          className="min-w-0 flex-1 text-left"
        >
          <span className="block text-sm font-semibold text-text">
            {run.model_name}{" "}
            <span className="font-normal text-text-muted">
              v{run.model_version}
            </span>
          </span>
          <span className="mt-0.5 block text-[11px] text-text-muted">
            {when(run.started_at)} · {scopeOf(run)} ·{" "}
            {run.initiated_by || "unattributed"}
          </span>
          <span className="mt-0.5 block font-mono text-[10px] text-text-muted">
            {run.run_key}
          </span>
        </button>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className="text-[11px] text-text-muted">
            {count(run.measured)} of {count(run.returned)} measured
            {findings > 0 && ` · ${count(findings)} finding${
              findings === 1 ? "" : "s"}`}
          </span>
          <span className="text-[11px] text-text-muted">
            Data as of {run.dataset_as_of || "—"}
          </span>
          <button
            type="button"
            onClick={() => onCompare(run.run_key)}
            className={cn(
              "rounded border px-2 py-0.5 text-[11px] transition-colors",
              comparing
                ? "border-border-strong bg-surface-hover text-text"
                : "border-border text-text-muted hover:border-border-strong hover:text-text",
            )}
          >
            {comparing ? "Comparing" : "Compare"}
          </button>
        </div>
      </div>
      {run.status !== "COMPLETE" && (
        <p className="mt-2 text-[11px] text-state-fail">
          {run.status}
          {run.failure ? `: ${run.failure}` : ""}
        </p>
      )}
    </div>
  );
}

// -------------------------------------------------------- the comparison

const MOVEMENT_TONE: Record<string, string> = {
  MOVED: "text-text",
  UNCHANGED: "text-text-muted",
  APPEARED: "text-text",
  DISAPPEARED: "text-text-muted",
  ABSENT: "text-text-muted",
  VERDICT_CHANGED: "text-state-warning",
  NOT_COMPARABLE: "text-text-muted",
};

/**
 * Four decimals, through the display contract rather than around it.
 *
 * AUC 0.7179 against 0.7104 is the finding; at two decimals both read 0.72
 * and the comparison this screen exists to show would be erased by its own
 * formatting. `technical` is the governed escape for exactly that case — it
 * caps at four decimals and requires the surface to carry a visible technical
 * label, which the column headers here do. Formatting the number directly
 * would print the same characters while bypassing the check that keeps the
 * rest of the product honest, which is why `scripts/check_decimals.py`
 * caught this line the first time round.
 */
function figure(value: number | null): string {
  return technical(value, 4);
}

function ComparisonRow({ row }: { row: ScvComparedTest }) {
  return (
    <tr className="border-t border-border">
      <td className="py-2 pr-4">
        <span className="block text-xs text-text">{row.title}</span>
        <span className="block font-mono text-[10px] text-text-muted">
          {row.test_id}
        </span>
      </td>
      <td className="py-2 pr-4 text-right text-xs tabular-nums text-text-muted">
        {figure(row.before)}
      </td>
      <td className="py-2 pr-4 text-right text-xs tabular-nums text-text">
        {figure(row.after)}
      </td>
      <td className="py-2 pr-4 text-right text-xs tabular-nums">
        <span className={row.adverse ? "text-state-fail" : "text-text-muted"}>
          {figure(row.change)}
        </span>
      </td>
      <td className="py-2 text-xs">
        <span className={MOVEMENT_TONE[row.movement] ?? "text-text-muted"}>
          {row.before_state}
          {row.verdict_changed ? " → " : " · "}
          {row.after_state}
        </span>
      </td>
    </tr>
  );
}

function Comparison({ view, onClear }: {
  view: ScvComparison; onClear: () => void;
}) {
  const rows = view.moved.length ? view.moved : view.headline;
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-text">
            What changed between two runs
          </h2>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {view.before.run_key} → {view.after.run_key}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
        >
          Close
        </button>
      </div>

      {!view.comparable && (
        <p className="rounded border border-state-warning/40 bg-state-warning/10 px-3 py-2 text-[11px] text-state-warning">
          These two runs were produced by different arithmetic
          {view.version_drift.length
            ? ` — ${view.version_drift.join("; ")}`
            : ""}
          . A difference between them is not only a difference in the model.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Data moved"
          value={view.data_moved ? "Yes" : "No"}
          hint={
            view.data_moved
              ? `${view.before.dataset_as_of} → ${view.after.dataset_as_of}`
              : `Both read data as of ${view.after.dataset_as_of || "—"}`
          }
        />
        <Field
          label="Verdicts changed"
          value={count(view.verdict_changes.length)}
        />
        <Field
          label="Findings"
          value={
            `${count(view.findings_raised.length)} raised, `
            + `${count(view.findings_cleared.length)} cleared`
          }
        />
      </div>

      {rows.length === 0 ? (
        <p className="text-xs text-text-muted">
          Nothing moved. Every test that produced a number in both runs
          produced the same number.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left">
            <thead>
              <tr className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                <th className="pb-2 pr-4">Test</th>
                <th className="pb-2 pr-4 text-right">Before</th>
                <th className="pb-2 pr-4 text-right">After</th>
                <th className="pb-2 pr-4 text-right">Change</th>
                <th className="pb-2">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ComparisonRow key={`${row.test_id}`} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------- the run

function StoredRun({ run, busy, onRerun, onDraft, onFinalise }: {
  run: ScvStoredRun;
  busy: string;
  onRerun: () => void;
  onDraft: () => void;
  onFinalise: (reportKey: string) => void;
}) {
  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-text">
            {run.model_name} · {when(run.started_at)}
          </h2>
          <p className="mt-0.5 font-mono text-[10px] text-text-muted">
            {run.run_key}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRerun}
            disabled={Boolean(busy)}
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-50"
          >
            {busy === "rerun" ? "Running…" : "Re-run using current data"}
          </button>
          <button
            type="button"
            onClick={onDraft}
            disabled={Boolean(busy)}
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-50"
          >
            {busy === "draft" ? "Drafting…" : "Draft a report from this run"}
          </button>
        </div>
      </div>

      <p className="rounded border border-border bg-surface-hover px-3 py-2 text-[11px] leading-relaxed text-text-muted">
        {run.historical}
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Model version" value={run.model_version}
               hint={run.model_kind} />
        <Field label="Dataset" value={run.dataset}
               hint={`as of ${run.dataset_as_of} · ${run.dataset_version}`} />
        <Field label="Matured window" value={run.matured_window}
               hint={`Latest period ${run.latest_period}`} />
        <Field label="Scope" value={scopeOf(run)}
               hint={run.segment || undefined} />
        <Field label="Initiated by"
               value={run.initiated_by || "unattributed"}
               hint={run.initiated_by_role || run.source} />
        <Field label="Measured"
               value={`${count(run.measured)} of ${count(run.returned)}`} />
        <Field label="Test registry" value={run.registry_version}
               hint={`Thresholds ${run.threshold_profile_version}`} />
        <Field label="Calculation kernel" value={run.calculation_version}
               hint={`States ${run.states_version} · findings ${
                 run.findings_version}`} />
      </div>

      {run.development_population && (
        <p className="text-[11px] text-text-muted">
          Development population: {run.development_population}
        </p>
      )}

      {run.reports.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
            Reports from this run
          </p>
          {run.reports.map((report) => (
            <div
              key={report.report_key}
              className="flex flex-wrap items-center justify-between gap-2 rounded border border-border px-3 py-2"
            >
              <div className="min-w-0">
                <span className="block text-xs text-text">
                  {report.opinion || report.title}
                </span>
                <span className="block font-mono text-[10px] text-text-muted">
                  {report.report_key}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <ReportChip report={report} />
                <a
                  href={api.scorecardValidation.storedReportDocxUrl(
                    report.report_key)}
                  className="rounded border border-border px-2 py-0.5 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
                >
                  Word
                </a>
                {report.status === "DRAFT" && (
                  <button
                    type="button"
                    onClick={() => onFinalise(report.report_key)}
                    disabled={Boolean(busy)}
                    className="rounded border border-border px-2 py-0.5 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text disabled:opacity-50"
                  >
                    Finalise
                  </button>
                )}
              </div>
            </div>
          ))}
          <p className="text-[11px] text-text-muted">
            A finalised report is signed evidence and cannot be edited. A
            correction is a new report against a new run.
          </p>
        </div>
      )}

      <div className="space-y-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
          Results, as they were measured
        </p>
        <div className="flex flex-wrap gap-1.5">
          {run.adverse.map((testId) => {
            const found = run.results.find((r) => r.test_id === testId);
            return found
              ? <StateChip key={testId} result={found} />
              : null;
          })}
        </div>
        <div className="space-y-2">
          {run.results.map((result) => (
            <ResultCard key={`${result.test_id}-${result.segment ?? ""}`}
                        result={result} />
          ))}
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- screen

export default function ValidationHistoryPage() {
  const [overview, setOverview] = React.useState<ScvOverview | null>(null);
  const [modelId, setModelId] = React.useState("");
  // `null` means "not fetched yet", which is what the skeleton is for.
  // Distinguishing it from `[]` matters: an empty list is a real answer —
  // this deployment has recorded no runs — and showing a spinner forever in
  // that case would read as a screen that never loads.
  const [rows, setRows] = React.useState<ScvRunHeader[] | null>(null);
  const [total, setTotal] = React.useState(0);
  const [openKey, setOpenKey] = React.useState("");
  const [against, setAgainst] = React.useState("");
  // Both of these are held WITH the key they were fetched for, and rendered
  // only when that key still matches what the reader has chosen. Clearing
  // them the obvious way — setState at the top of the effect — shows the
  // previous run's figures for one render while the next fetch is in flight,
  // and on this screen a figure attributed to the wrong run is the one
  // mistake that matters.
  const [loaded, setLoaded] =
    React.useState<{ key: string; run: ScvStoredRun } | null>(null);
  const [compared, setCompared] =
    React.useState<{ pair: string; view: ScvComparison } | null>(null);
  const open = loaded && loaded.key === openKey ? loaded.run : null;
  const view = compared && compared.pair === `${openKey}|${against}`
    ? compared.view : null;
  const [busy, setBusy] = React.useState("");
  const [problem, setProblem] = React.useState("");
  const loading = rows === null;

  React.useEffect(() => {
    let alive = true;
    api.scorecardValidation.overview()
      .then((body) => { if (alive) setOverview(body); })
      .catch((error: Error) => { if (alive) setProblem(error.message); });
    return () => { alive = false; };
  }, []);

  const load = React.useCallback(async () => {
    try {
      const body = await api.scorecardValidation.runs({ modelId, limit: 50 });
      setRows(body.runs);
      setTotal(body.total);
      setProblem("");
    } catch (error) {
      setRows([]);
      setProblem((error as Error).message);
    }
  }, [modelId]);

  // Written as a promise chain rather than `await` inside the effect so the
  // state updates land in a callback, which is what an effect is for:
  // subscribing to an external system and setting state when IT changes.
  React.useEffect(() => {
    let alive = true;
    api.scorecardValidation.runs({ modelId, limit: 50 })
      .then((body) => {
        if (!alive) return;
        setRows(body.runs);
        setTotal(body.total);
        setProblem("");
      })
      .catch((error: Error) => {
        if (!alive) return;
        setRows([]);
        setProblem(error.message);
      });
    return () => { alive = false; };
  }, [modelId]);

  React.useEffect(() => {
    if (!openKey) return;
    let alive = true;
    api.scorecardValidation.run(openKey)
      .then((body) => { if (alive) setLoaded({ key: openKey, run: body }); })
      .catch((error: Error) => { if (alive) setProblem(error.message); });
    return () => { alive = false; };
  }, [openKey]);

  // A comparison needs two runs, and their order is the order they happened
  // in — not the order they were clicked, which would silently invert every
  // "change" on the screen.
  React.useEffect(() => {
    if (!openKey || !against || openKey === against) return;
    const pair = `${openKey}|${against}`;
    const at = (key: string) =>
      (rows ?? []).find((r) => r.run_key === key)?.started_at ?? "";
    const [older, newer] = at(against) <= at(openKey)
      ? [against, openKey] : [openKey, against];
    let alive = true;
    api.scorecardValidation.compareRuns(older, newer)
      .then((body) => { if (alive) setCompared({ pair, view: body }); })
      .catch((error: Error) => { if (alive) setProblem(error.message); });
    return () => { alive = false; };
  }, [openKey, against, rows]);

  async function rerun() {
    if (!open) return;
    setBusy("rerun");
    try {
      const made = await api.scorecardValidation.rerun(
        open.model_id, open.run_key);
      await load();
      if (made.run_key) setOpenKey(String(made.run_key));
      else setProblem(String(made.recorded_note ?? ""));
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function draft() {
    if (!open) return;
    setBusy("draft");
    try {
      await api.scorecardValidation.draftReport(open.run_key);
      setLoaded({ key: open.run_key,
                  run: await api.scorecardValidation.run(open.run_key) });
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function finalise(reportKey: string) {
    if (!open) return;
    setBusy("finalise");
    try {
      await api.scorecardValidation.finaliseReport(reportKey);
      setLoaded({ key: open.run_key,
                  run: await api.scorecardValidation.run(open.run_key) });
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      <PageHeader
        title="Validation History"
        description={
          "Every validation run this deployment has recorded, as it was "
          + "recorded. Opening a run shows the values it measured at the "
          + "time — not a fresh calculation that happens to agree."
        }
        actions={
          <Link
            href="/scorecard-validation"
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            Back to the cockpit
          </Link>
        }
      />

      {problem && (
        <p className="rounded border border-state-fail/40 bg-state-fail/10 px-3 py-2 text-xs text-state-fail">
          {problem}
        </p>
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              setRows(null);
              setModelId("");
              setOpenKey("");
              setAgainst("");
            }}
            className={cn(
              "rounded border px-3 py-1.5 text-xs transition-colors",
              modelId === ""
                ? "border-border-strong bg-surface-hover text-text"
                : "border-border text-text-muted hover:border-border-strong hover:text-text",
            )}
          >
            All scorecards
          </button>
          {(overview?.scorecards ?? []).map((scorecard) => (
            <button
              key={scorecard.model_id}
              type="button"
              onClick={() => {
                setRows(null);
                setModelId(scorecard.model_id);
                setOpenKey("");
                setAgainst("");
              }}
              className={cn(
                "rounded border px-3 py-1.5 text-xs transition-colors",
                modelId === scorecard.model_id
                  ? "border-border-strong bg-surface-hover text-text"
                  : "border-border text-text-muted hover:border-border-strong hover:text-text",
              )}
            >
              {scorecard.name}
            </button>
          ))}
        </div>
        <p className="max-w-3xl text-[11px] leading-relaxed text-text-muted">
          {NOTHING_HERE_RECALCULATES}
        </p>
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-text">
            {count(total)} run{total === 1 ? "" : "s"}
          </h2>
          {against && (
            <span className="text-[11px] text-text-muted">
              Comparing against {against}
            </span>
          )}
        </div>

        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <Card className="p-5">
            <p className="text-xs text-text-muted">
              No validation runs have been recorded
              {modelId ? " for this scorecard" : ""} yet. Running tests from
              the cockpit records them here.
            </p>
          </Card>
        ) : (
          <div className="space-y-2">
            {(rows ?? []).map((run) => (
              <HistoryRow
                key={run.run_key}
                run={run}
                chosen={run.run_key === openKey}
                comparing={run.run_key === against}
                onOpen={(key) =>
                  setOpenKey((was) => (was === key ? "" : key))}
                onCompare={(key) =>
                  setAgainst((was) => (was === key ? "" : key))}
              />
            ))}
          </div>
        )}
      </section>

      {view && <Comparison view={view} onClear={() => setAgainst("")} />}

      {open && (
        <StoredRun
          run={open}
          busy={busy}
          onRerun={rerun}
          onDraft={draft}
          onFinalise={finalise}
        />
      )}
    </div>
  );
}
