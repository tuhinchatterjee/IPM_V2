"use client";

/**
 * Cockpit Agentic V3 on screen.
 *
 * Four pieces:
 *
 * `CockpitV3Badge` proves which build, which release and which LIMITS answered.
 * The last of those is the one that matters most: a demonstration run under a
 * raised per-call cap must not read as though it had been obtained under the
 * specification's own numbers, so any override is shown, not buried.
 *
 * `CockpitV3Progress` names the actual work — checking functionality, planning,
 * executing submission n of 5, reviewing round n of 3. It never says "analysis
 * complete" while computation is pending.
 *
 * `CockpitV3Answer` renders whichever of the four envelopes came back: an
 * answer, a referral with a real navigation button, a clarification with
 * clickable choices and free text, or an honest stop.
 *
 * Nothing here computes. Every number is rendered exactly as the backend sent
 * it, and a chart is a declarative specification — model-provided HTML and
 * JavaScript are never executed, and there is no path here that could.
 */

import * as React from "react";

import type {
  CockpitV3Alternative,
  CockpitV3Answer as CockpitV3AnswerPayload,
  CockpitV3Chart,
  CockpitV3Diagnostics,
  CockpitV3Envelope,
  CockpitV3Table,
} from "@/lib/api";

function Pill({ label, value, tone = "slate" }: {
  label: string; value: React.ReactNode; tone?: "slate" | "amber" | "red";
}) {
  const border = tone === "amber" ? "border-amber-300 bg-amber-50"
    : tone === "red" ? "border-red-300 bg-red-50"
    : "border-slate-200 bg-white";
  return (
    <span className={`inline-flex items-baseline gap-1 rounded border px-2 py-0.5 text-[11px] ${border}`}>
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800">{value}</span>
    </span>
  );
}

// --------------------------------------------------------------- the badge

export function CockpitV3Badge({ diagnostics }: {
  diagnostics: CockpitV3Diagnostics | null;
}) {
  if (!diagnostics?.cockpit_agentic_v3) return null;

  const quarters = diagnostics.release?.reporting_quarters ?? [];
  const missing = diagnostics.release?.missing_quarters ?? [];
  const overrides = Object.entries(
    diagnostics.standard_overrides_in_force ?? {});

  return (
    <div
      data-testid="cockpit-v3-badge"
      className="mb-4 space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">
          Cockpit Agentic V3
        </span>
        <Pill label="domain" value={diagnostics.domain_id} />
        <Pill label="release" value={diagnostics.dataset_release_id} />
        <Pill
          label="quarters"
          value={
            quarters.length
              ? `${quarters.length}${missing.length ? ` (${missing.length} empty)` : ""}`
              : "—"
          }
        />
        <Pill label="data" value={diagnostics.release?.data_version ?? "—"} />
        {!diagnostics.provider.configured && (
          <Pill label="provider" value="not configured" tone="red" />
        )}
        {!diagnostics.cost_enforced && (
          <Pill label="spend" value="not enforced" tone="amber" />
        )}
      </div>

      {/* A result obtained under a raised limit is not a result obtained under
          the specification's limit, and the screen says which. */}
      {overrides.length > 0 && (
        <p className="text-[11px] leading-snug text-amber-900">
          <span className="font-semibold">Running raised limits:</span>{" "}
          {overrides.map(([name, value], i) => (
            <span key={name}>
              {i > 0 ? ", " : ""}
              {name.replace(/_/g, " ")} {value.specification} →{" "}
              {value.configured}
            </span>
          ))}
          . The five execution submissions and three analysis rounds are not
          configurable at any level.
        </p>
      )}

      {diagnostics.release?.not_client_data && (
        <p className="text-[11px] leading-snug text-amber-900">
          {diagnostics.release.not_client_data}
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- the progress

export function CockpitV3Progress({ steps, running, onCancel }: {
  steps: string[];
  running: boolean;
  onCancel?: () => void;
}) {
  if (!steps.length) return null;
  return (
    <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-600">
          {steps.map((step, i) => (
            <li key={`${step}-${i}`} className="flex items-center gap-2">
              {i > 0 && <span className="text-slate-300">›</span>}
              <span className={i === steps.length - 1 && running
                ? "font-medium text-slate-900" : ""}>
                {step}
              </span>
            </li>
          ))}
        </ol>
        {running && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-100"
          >
            Stop
          </button>
        )}
      </div>
    </div>
  );
}

// -------------------------------------------------------------- the pieces

function Table({ table }: { table: CockpitV3Table }) {
  return (
    <figure className="my-3 overflow-x-auto">
      {table.title && (
        <figcaption className="mb-1 text-xs font-medium text-slate-700">
          {table.title}
        </figcaption>
      )}
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-slate-300">
            {table.columns.map((column) => (
              <th key={column} className="px-2 py-1 text-left font-medium text-slate-600">
                {column}
                {table.units?.[column] && (
                  <span className="ml-1 font-normal text-slate-400">
                    ({table.units[column]})
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 tabular-nums text-slate-800">
                  {cell === null || cell === undefined ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {table.note && (
        <p className="mt-1 text-[11px] text-slate-500">{table.note}</p>
      )}
    </figure>
  );
}

/** A declared chart specification, drawn from its own numbers.
 *  Deliberately simple: the point is that the chart and the table cannot
 *  disagree, because both come from the same result. */
function Chart({ chart }: { chart: CockpitV3Chart }) {
  const points = chart.series.flatMap((s) => {
    const value = Number((s as Record<string, unknown>).value);
    return Number.isFinite(value) ? [{ label: String((s as Record<string, unknown>).label ?? ""), value }] : [];
  });
  if (!points.length) return null;
  const max = Math.max(...points.map((p) => Math.abs(p.value)), 1);

  return (
    <figure className="my-3">
      <figcaption className="mb-1 text-xs font-medium text-slate-700">
        {chart.title}
        {chart.unit && (
          <span className="ml-1 font-normal text-slate-400">({chart.unit})</span>
        )}
      </figcaption>
      <div className="space-y-1">
        {points.map((point, i) => (
          <div key={i} className="flex items-center gap-2 text-[11px]">
            <span className="w-32 shrink-0 truncate text-slate-600">
              {point.label}
            </span>
            <span className="h-3 rounded-sm bg-slate-400"
                  style={{ width: `${(Math.abs(point.value) / max) * 60}%` }} />
            <span className="tabular-nums text-slate-700">{point.value}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function Alternatives({ alternatives, onAsk }: {
  alternatives: CockpitV3Alternative[];
  onAsk?: (question: string) => void;
}) {
  if (!alternatives.length) return null;
  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-slate-700">
        The Cockpit can answer these from its own data:
      </p>
      <ul className="mt-1 space-y-1">
        {alternatives.map((alternative, i) => (
          <li key={i}>
            <button
              type="button"
              disabled={!onAsk}
              onClick={() => onAsk?.(alternative.question)}
              className="w-full rounded border border-slate-200 bg-white px-2 py-1 text-left text-xs text-slate-800 hover:bg-slate-50 disabled:cursor-default"
            >
              {alternative.question}
              {alternative.limitation && (
                <span className="mt-0.5 block text-[11px] text-slate-500">
                  {alternative.limitation}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -------------------------------------------------------------- the answer

export function CockpitV3Answer({ payload, onAsk, onNavigate }: {
  payload: CockpitV3AnswerPayload;
  onAsk?: (question: string) => void;
  onNavigate?: (route: string) => void;
}) {
  const envelope: CockpitV3Envelope = payload.answer;
  const referral = envelope.referral as { destination?: string; route?: string | null;
                                          enabled?: boolean } | undefined;

  return (
    <section data-testid="cockpit-v3-answer" className="space-y-3">
      {!envelope.complete && (
        <p className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
          {envelope.approximate
            ? "This answer is approximate. What could not be isolated is named below."
            : "This answer is partial. What is missing is named below."}
        </p>
      )}

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
        {envelope.narrative}
      </p>

      {envelope.tables.map((table, i) => <Table key={i} table={table} />)}
      {envelope.charts.map((chart, i) => <Chart key={i} chart={chart} />)}

      {/* A referral offers a real route, or says honestly that it cannot. */}
      {envelope.kind === "referral" && referral && (
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
          {referral.enabled && referral.route ? (
            <button
              type="button"
              onClick={() => onNavigate?.(referral.route as string)}
              className="rounded bg-slate-800 px-3 py-1 text-xs font-medium text-white hover:bg-slate-700"
            >
              Open {referral.destination?.replace(/_/g, " ")}
            </button>
          ) : (
            <p className="text-xs text-slate-600">
              That part of CreditProbe is not available in this deployment, so
              there is nothing to open. The explanation above says what it
              would have done.
            </p>
          )}
        </div>
      )}

      {envelope.kind === "clarification" && (
        <div className="rounded border border-slate-200 bg-white px-3 py-2">
          <p className="text-xs font-medium text-slate-700">
            {envelope.clarification_question}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {envelope.clarification_options.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onAsk?.(option)}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 hover:bg-slate-50"
              >
                {option}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Or answer in your own words in the box below.
          </p>
        </div>
      )}

      {envelope.kind === "stop" && (
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
          {envelope.what_was_understood && (
            <p><span className="font-medium">Understood:</span>{" "}
              {envelope.what_was_understood}</p>
          )}
          {envelope.what_was_tried.length > 0 && (
            <div className="mt-1">
              <span className="font-medium">Tried:</span>
              <ul className="ml-4 list-disc">
                {envelope.what_was_tried.map((attempt, i) => (
                  <li key={i}>{attempt}</li>
                ))}
              </ul>
            </div>
          )}
          {envelope.what_would_help && (
            <p className="mt-1"><span className="font-medium">What would help:</span>{" "}
              {envelope.what_would_help}</p>
          )}
        </div>
      )}

      <Alternatives alternatives={envelope.alternatives} onAsk={onAsk} />

      {envelope.hypotheses.length > 0 && (
        <div className="text-xs text-slate-600">
          <p className="font-medium">
            Supported as association, not as cause:
          </p>
          <ul className="ml-4 list-disc">
            {envelope.hypotheses.map((h, i) => <li key={i}>{h}</li>)}
          </ul>
        </div>
      )}

      {(envelope.limitations.length > 0 || envelope.assumptions.length > 0) && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer font-medium">
            Limitations and assumptions
          </summary>
          <ul className="ml-4 mt-1 list-disc">
            {envelope.assumptions.map((a, i) => <li key={`a${i}`}>{a}</li>)}
            {envelope.limitations.map((l, i) => <li key={`l${i}`}>{l}</li>)}
          </ul>
        </details>
      )}

      <details className="text-[11px] text-slate-500">
        <summary className="cursor-pointer">Technical detail</summary>
        <div className="mt-1 space-y-1">
          <p>
            Submissions {payload.budget.submissions_used} of{" "}
            {payload.budget.submissions_used + payload.budget.submissions_remaining},
            rounds {payload.budget.analysis_rounds_used} of{" "}
            {payload.budget.analysis_rounds_used + payload.budget.analysis_rounds_remaining},
            {" "}{payload.budget.tokens_used} tokens, spend{" "}
            {String(payload.budget.spend_usd)}.
          </p>
          {payload.functionality_decision && (
            <p>
              Ownership: {payload.functionality_decision.decision}
              {payload.functionality_decision.best_fit
                ? ` (${payload.functionality_decision.best_fit})`
                : ""}.
            </p>
          )}
          {payload.results.map((result, i) => (
            <pre key={i} className="overflow-x-auto rounded bg-slate-100 p-2">
              {String((result as Record<string, unknown>).status)}
            </pre>
          ))}
        </div>
      </details>
    </section>
  );
}
