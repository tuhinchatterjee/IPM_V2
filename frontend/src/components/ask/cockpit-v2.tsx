"use client";

/**
 * Cockpit Intelligence V2 on screen.
 *
 * Two pieces, both deliberately small:
 *
 * `CockpitV2Badge` proves which backend and which data the browser is talking
 * to — branch, commit, dataset version, checksum, published quarters and the
 * isolation namespace. A demonstration where nobody can tell which build
 * answered is a demonstration of nothing.
 *
 * `CockpitV2Answer` renders the answer's own structure: each requested output
 * as its own section, the outputs that could NOT be answered stated rather than
 * dropped, the bridge table, the waterfall, the limitations and the evidence.
 *
 * Nothing here computes. Every number is rendered exactly as the backend sent
 * it — see `insight.ts` in this directory for why that boundary is absolute.
 */

import * as React from "react";

import type {
  CockpitV2Answer as CockpitV2AnswerPayload,
  CockpitV2Chart,
  CockpitV2Diagnostics,
  CockpitV2Table,
} from "@/lib/api";

function Pill({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded border border-slate-200 bg-white px-2 py-0.5 text-[11px]">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800">{value}</span>
    </span>
  );
}

export function CockpitV2Badge({
  diagnostics,
  selectedQuarter,
  onSelectQuarter,
}: {
  diagnostics: CockpitV2Diagnostics | null;
  selectedQuarter?: string;
  onSelectQuarter?: (quarter: string) => void;
}) {
  if (!diagnostics?.cockpit_intelligence_v2) return null;

  const quarters = diagnostics.published_quarters ?? [];
  const current = selectedQuarter || diagnostics.selected_quarter_default || "";
  const checksum = current
    ? (diagnostics.dataset_checksums ?? {})[current]
    : undefined;

  return (
    <div
      data-testid="cockpit-v2-badge"
      className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2"
    >
      <span className="rounded bg-amber-600 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
        Cockpit V2
      </span>
      {/* "Synthetic data", not "Synthetic demonstration data". The product
          has one vocabulary for this — the Data Builder badge, the home
          page's SYNTHETIC_SENTENCE and backend/release/product_copy.py all
          say "Synthetic data" — and backend/release/product_copy.py explains
          why the word "demo" is kept off every screen: the switch keeps its
          internal name, but what a reader is shown is the posture it
          produces. The honesty of the label is unchanged; only the word the
          rest of the product does not use is gone. */}
      <span className="text-[11px] font-medium text-amber-900">
        Synthetic data
      </span>

      {diagnostics.branch ? (
        <Pill label="branch" value={diagnostics.branch} />
      ) : null}
      {diagnostics.commit ? (
        <Pill label="commit" value={<code>{diagnostics.commit}</code>} />
      ) : null}
      <Pill label="data" value={diagnostics.data_version ?? "—"} />
      <Pill label="model" value={diagnostics.model_version ?? "—"} />
      <Pill label="policy" value={diagnostics.policy_version ?? "—"} />
      {checksum ? (
        <Pill label="checksum" value={<code>{checksum.slice(0, 10)}</code>} />
      ) : null}
      <Pill label="db" value={diagnostics.isolation?.database_name ?? "—"} />
      <Pill
        label="lake"
        value={(diagnostics.isolation?.analytics_dir ?? []).join("/") || "—"}
      />

      {quarters.length > 0 ? (
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-amber-900">
          Quarter
          <select
            data-testid="cockpit-v2-quarter"
            className="rounded border border-amber-300 bg-white px-1.5 py-0.5 text-[11px] text-slate-800"
            value={current}
            onChange={(e) => onSelectQuarter?.(e.target.value)}
          >
            {quarters.map((q) => (
              <option key={q} value={q}>
                {q === diagnostics.selected_quarter_default
                  ? `${q} (latest)`
                  : q}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <span className="ml-auto text-[11px] text-amber-800">
          No quarter is published in this runtime.
        </span>
      )}
    </div>
  );
}

function Table({ table }: { table: CockpitV2Table }) {
  return (
    <figure className="my-3 overflow-x-auto">
      <figcaption className="mb-1 text-xs font-medium text-slate-700">
        {table.title}
        {table.unit ? (
          <span className="ml-1 font-normal text-slate-500">
            ({table.unit})
          </span>
        ) : null}
      </figcaption>
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-slate-300 text-left">
            {table.columns.map((column) => (
              <th key={column} className="px-2 py-1 font-medium text-slate-600">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index} className="border-b border-slate-100">
              {table.columns.map((column) => {
                const value = row[column];
                return (
                  <td
                    key={column}
                    className={
                      typeof value === "number"
                        ? "px-2 py-1 text-right tabular-nums"
                        : "px-2 py-1"
                    }
                  >
                    {value === null || value === undefined ? "—" : String(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {table.footer ? (
        <figcaption className="mt-1 text-[11px] text-slate-500">
          {table.footer}
        </figcaption>
      ) : null}
    </figure>
  );
}

function Waterfall({ chart }: { chart: CockpitV2Chart }) {
  const steps = chart.steps ?? [];
  if (steps.length === 0) return null;
  const magnitude = Math.max(...steps.map((s) => Math.abs(s.value)), 1);

  return (
    <figure className="my-3" data-testid="cockpit-v2-waterfall">
      <figcaption className="mb-1 text-xs font-medium text-slate-700">
        {chart.title}
        {chart.unit ? (
          <span className="ml-1 font-normal text-slate-500">
            ({chart.unit})
          </span>
        ) : null}
      </figcaption>
      <ul className="space-y-1">
        {steps.map((step, index) => {
          const width = Math.max((Math.abs(step.value) / magnitude) * 100, 1);
          const total = step.kind === "total";
          return (
            <li key={index} className="flex items-center gap-2 text-xs">
              <span className="w-56 shrink-0 truncate text-slate-600">
                {step.label}
              </span>
              <span className="h-3 flex-1 rounded bg-slate-100">
                <span
                  className={`block h-3 rounded ${
                    total
                      ? "bg-slate-500"
                      : step.value >= 0
                        ? "bg-rose-400"
                        : "bg-emerald-500"
                  }`}
                  style={{ width: `${width}%` }}
                />
              </span>
              <span className="w-24 shrink-0 text-right tabular-nums text-slate-800">
                {step.value.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </li>
          );
        })}
      </ul>
      {chart.reconciled !== undefined ? (
        <figcaption className="mt-1 text-[11px] text-slate-500">
          {chart.reconciled
            ? `Reconciled: opening plus every component equals closing (residual ${(chart.residual ?? 0).toExponential(2)}).`
            : "This bridge did NOT reconcile; the residual is shown rather than absorbed into a component."}
        </figcaption>
      ) : null}
    </figure>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  analyst: "Written by the grounded analyst",
  deterministic_v2: "Composed by the governed Cockpit V2 path",
  interpretation: "Written by the interpretation reader",
  deterministic: "Assembled from the deterministic result",
};

export function CockpitV2Answer({
  answer,
  onAsk,
}: {
  answer: CockpitV2AnswerPayload;
  onAsk?: (question: string) => void;
}) {
  // The lead paragraph is already rendered above as the direct answer. Showing
  // it again as the first line of the first section reads as a stutter, and it
  // is what the first browser run looked like.
  const lead = answer.direct_answer.trim();

  return (
    <section data-testid="cockpit-v2-answer" className="space-y-4">
      {answer.sections.map((section, index) => (
        <div key={`${section.output}-${index}`}>
          <h3 className="text-sm font-semibold text-slate-800">
            {section.heading}
            {section.answered ? null : (
              <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-700">
                not answered
              </span>
            )}
          </h3>
          {section.paragraphs
            .filter((paragraph) => paragraph.trim() !== lead)
            .map((paragraph, i) => (
            <p key={i} className="mt-2 text-sm leading-relaxed text-slate-700">
              {paragraph}
            </p>
          ))}
          {section.findings.length > 0 ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-600">
              {section.findings.map((finding, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-slate-400">•</span>
                  <span>{finding}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {section.table ? <Table table={section.table} /> : null}
          {section.chart?.type === "waterfall" ? (
            <Waterfall chart={section.chart} />
          ) : null}
          {section.limitations.length > 0 ? (
            <ul className="mt-2 space-y-1 text-[11px] text-slate-500">
              {section.limitations.map((limitation, i) => (
                <li key={i}>{limitation}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}

      {answer.clarification ? (
        <div
          data-testid="cockpit-v2-clarification"
          className="rounded border border-slate-200 bg-slate-50 p-3"
        >
          <p className="text-sm text-slate-700">
            {answer.clarification.question}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {answer.clarification.choices.map((choice) => (
              <button
                key={choice.output}
                type="button"
                onClick={() => onAsk?.(choice.label)}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
              >
                {choice.label}
              </button>
            ))}
          </div>
          {answer.clarification.free_text ? (
            <p className="mt-2 text-[11px] text-slate-500">
              Or type what you want in your own words.
            </p>
          ) : null}
        </div>
      ) : null}

      {answer.recommendations.length > 0 ? (
        <div className="rounded border border-slate-200 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
            Suggested review actions
          </h4>
          <ul className="mt-2 space-y-2 text-xs text-slate-700">
            {answer.recommendations.map((item, i) => (
              <li key={i}>
                <span className="font-medium">{item.action}</span>
                <span className="text-slate-500"> — {item.because}</span>
                <div className="text-[11px] text-slate-500">
                  Suggested owner: {item.suggested_owner} · Priority:{" "}
                  {item.priority} · Escalate if: {item.escalation_if}
                </div>
                <div className="text-[11px] font-medium text-amber-700">
                  {item.status}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {answer.unanswered.length > 0 ? (
        <div
          data-testid="cockpit-v2-unanswered"
          className="rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600"
        >
          <span className="font-medium">Not answered:</span>
          <ul className="mt-1 space-y-1">
            {answer.unanswered.map((item, i) => (
              <li key={i}>
                {item.output.replace(/_/g, " ")} — {item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
        <span data-testid="cockpit-v2-prose-source">
          {SOURCE_LABEL[answer.prose_source] ?? answer.prose_source}
        </span>
        <span>·</span>
        <span>{answer.evidence.count} governed observation(s)</span>
        <span>·</span>
        <span>{answer.model_calls} model call(s)</span>
        <span>·</span>
        <span>{answer.duration_ms} ms</span>
        {answer.validation ? (
          <>
            <span>·</span>
            <span data-testid="cockpit-v2-validation">
              {answer.validation.ok
                ? "every claim validated against its evidence"
                : `${answer.validation.issues.length} claim(s) withheld`}
            </span>
          </>
        ) : null}
        {answer.fallback_reason ? (
          <>
            <span>·</span>
            <span>{answer.fallback_reason}</span>
          </>
        ) : null}
      </div>
    </section>
  );
}
