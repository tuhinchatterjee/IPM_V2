"use client";

import * as React from "react";

import type { RiskCase } from "@/lib/api";

/**
 * The stacked evidence panels a story's drawer adds. U02.
 *
 * WHY THESE ARE PANELS AND NOT PARAGRAPHS
 *
 * The drawer's bottom line already says what happened in a sentence. The
 * failure this guards against is the reader believing it: a percentage with
 * no denominator beside it, a probability with no horizon, an expected loss
 * with no statement of which facilities it is the loss on, a score movement
 * with no statement of whether the same customers were observed twice.
 *
 * So each panel carries its own denominator, its own comparator and its own
 * coverage, and none of them is a number on its own. Where a figure does not
 * apply — a forward probability of default for a cohort that has already
 * defaulted — the panel says so in the place the figure would have been,
 * rather than leaving a blank a reader will fill in optimistically.
 *
 * Everything rendered here is SYNTHETIC demonstration data.
 */

type Drawer = {
  affected?: number;
  eligible?: number;
  rate?: number | null;
  multiple?: number | null;
  points?: number | null;
  exposure_sar?: number | null;
  grain?: string;
  comparator?: {
    label?: string;
    basis?: string;
    as_of?: string;
    eligible?: number;
    issue?: number;
    rate?: number | null;
  };
  concentration?: {
    pocket_label?: string;
    pocket?: Record<string, number | null>;
    outside?: Record<string, number | null>;
    rate_ratio?: number | null;
  };
  risk?: {
    as_of?: string;
    previous?: string;
    cohort?: number;
    comparable_cohort?: number;
    impaired_now?: number;
    forward_pd_applies?: boolean;
    forward_pd_note?: string;
    pd_12m?: Movement & { basis?: string; cohort?: number };
    pd_lifetime?: Movement & { basis?: string };
    lgd?: Movement & { basis?: string };
    ecl?: Movement;
    gca?: Movement;
    stage?: { now?: Record<string, number>; before?: Record<string, number> };
    coverage?: Coverage;
  };
  scores?: {
    diagnosis_model?: string;
    behaviour?: {
      reference_month?: string;
      now?: number | null;
      before?: number | null;
      change?: number | null;
      cohort?: number;
      coverage?: Coverage;
    };
    application?: {
      pocket?: number | null;
      outside?: number | null;
      issue?: number | null;
      note?: string;
    };
  };
  predicate?: { describes?: string; clauses?: Clause[] };
  countercheck?: string;
  policy?: { policy_id?: string; version?: string; clauses?: string[]; status?: string };
  research?: string[];
  sources?: Record<string, string | undefined>;
};

type Movement = { now?: number | null; before?: number | null };
type Coverage = {
  covered?: number;
  eligible?: number;
  coverage_pct?: number | null;
  complete?: boolean;
  missing_reasons?: Record<string, string>;
};
type Clause = { field?: string; op?: string; value?: unknown; label?: string; role?: string };

const pct = (value?: number | null, digits = 1) =>
  value === null || value === undefined ? "not available" : `${(value * 100).toFixed(digits)}%`;
const sar = (value?: number | null) =>
  value === null || value === undefined
    ? "not available"
    : `SAR ${Math.round(value).toLocaleString("en-GB")}`;
const num = (value?: number | null) =>
  value === null || value === undefined ? "—" : value.toLocaleString("en-GB");

export function EpisodePanels({ found }: { found: RiskCase }) {
  const drawer = (found.evidence?.drawer ?? null) as Drawer | null;
  if (!drawer || !drawer.risk) return null;

  const { comparator, concentration, risk, scores } = drawer;
  const pocket = concentration?.pocket ?? {};
  const outside = concentration?.outside ?? {};

  return (
    <div className="space-y-4">
      <Panel
        title="Affected population"
        note={`Counted at ${drawer.sources?.as_of ?? "the reporting date"} on the case's own grain (${drawer.grain ?? "facility"}).`}
      >
        <Row label="Meeting the issue rule" value={num(drawer.affected)} />
        <Row label="Eligible observations" value={num(drawer.eligible)} emphasis="denominator" />
        <Row label="Rate" value={pct(drawer.rate)} />
        <Row
          label="Comparator"
          value={`${pct(comparator?.rate)} of ${num(comparator?.eligible)}`}
          note={comparator?.label}
        />
        <Row
          label="Against the comparator"
          value={
            drawer.multiple
              ? `${drawer.multiple.toFixed(2)}x, ${(drawer.points ?? 0) >= 0 ? "+" : ""}${(drawer.points ?? 0).toFixed(1)} pp`
              : "—"
          }
        />
        <Row label="Gross exposure" value={sar(drawer.exposure_sar)} />
      </Panel>

      <Panel
        title="Normalised pocket"
        note={concentration?.pocket_label}
      >
        <Row
          label="Share of the eligible book"
          value={`${num(pocket.eligible)} of ${num(drawer.eligible)} (${pct(pocket.share_of_eligible)})`}
        />
        <Row
          label="Share of the cases"
          value={`${num(pocket.issue)} of ${num(drawer.affected)} (${pct(pocket.share_of_cases)})`}
        />
        <Row label="Incidence inside" value={pct(pocket.incidence)} />
        <Row
          label="Incidence outside"
          value={`${pct(outside.incidence)} of ${num(outside.eligible)}`}
          emphasis="denominator"
        />
        <Row
          label="Rate ratio"
          value={concentration?.rate_ratio ? `${concentration.rate_ratio}x` : "—"}
        />
      </Panel>

      <Panel
        title="Probability of default, stage and loss"
        note={`Same facilities at ${risk.previous ?? "the prior month"} and ${risk.as_of ?? "now"}, so a change here is a change in those customers and not in which customers are counted.`}
      >
        {risk.forward_pd_applies ? (
          <>
            <Row
              label="12-month PD"
              value={`${pct(risk.pd_12m?.before, 2)} → ${pct(risk.pd_12m?.now, 2)}`}
              note={`${risk.pd_12m?.basis ?? ""} · ${num(risk.pd_12m?.cohort)} non-impaired of ${num(risk.cohort)}`}
            />
            <Row
              label="Lifetime PD"
              value={`${pct(risk.pd_lifetime?.before, 2)} → ${pct(risk.pd_lifetime?.now, 2)}`}
              note={risk.pd_lifetime?.basis}
            />
          </>
        ) : (
          <Row
            label="12-month PD"
            value="Not applicable"
            note={risk.forward_pd_note}
          />
        )}
        <Row
          label="Loss given default"
          value={`${pct(risk.lgd?.before, 1)} → ${pct(risk.lgd?.now, 1)}`}
          note={risk.lgd?.basis}
        />
        <Row
          label="Expected credit loss"
          value={`${sar(risk.ecl?.before)} → ${sar(risk.ecl?.now)}`}
          note="the same facilities in both months"
        />
        <Row
          label="Gross carrying amount"
          value={`${sar(risk.gca?.before)} → ${sar(risk.gca?.now)}`}
        />
        <Row
          label="IFRS 9 stage"
          value={stageLine(risk.stage?.before)}
          note={`now ${stageLine(risk.stage?.now)}`}
        />
        <CoverageLine coverage={risk.coverage} what="prior-month observations" />
      </Panel>

      <Panel
        title="Scores"
        note={
          scores?.diagnosis_model === "application"
            ? "This story is about the decision, so the original application scorecard is the diagnosis and the behavioural score is context."
            : scores?.diagnosis_model === "recovery"
              ? "This story is about loss severity. The borrower's scores are shown as CONTROLS: if they have barely moved, that is the finding, not a gap in the evidence."
              : "The behavioural score is the same facilities observed through time. The original application score is fixed at each decision."
        }
      >
        <Row
          label={`Behavioural, median (${scores?.behaviour?.reference_month ?? "reference"} → now)`}
          value={`${num(scores?.behaviour?.before)} → ${num(scores?.behaviour?.now)}`}
          note={
            scores?.behaviour?.change === null || scores?.behaviour?.change === undefined
              ? undefined
              : `${scores.behaviour.change >= 0 ? "+" : ""}${scores.behaviour.change.toFixed(0)} points over ${num(scores?.behaviour?.cohort)} facilities`
          }
        />
        <Row
          label="Original application, median"
          value={`${num(scores?.application?.pocket)} in the pocket, ${num(scores?.application?.outside)} outside it`}
          note={scores?.application?.note}
        />
        <CoverageLine coverage={scores?.behaviour?.coverage} what="scored facilities" />
      </Panel>

      {drawer.predicate?.clauses?.length ? (
        <Panel title="The rule that was evaluated" note={drawer.predicate.describes}>
          {drawer.predicate.clauses.map((clause, index) => (
            <Row
              key={index}
              label={clause.role === "scope" ? "Population" : "Condition"}
              value={clause.label ?? `${clause.field} ${clause.op} ${String(clause.value)}`}
            />
          ))}
        </Panel>
      ) : null}

      {drawer.countercheck ? (
        <Panel title="Before acting on this">
          <p className="text-xs leading-relaxed text-text-secondary">
            {drawer.countercheck}
          </p>
        </Panel>
      ) : null}

      <Panel title="Sources and status">
        <Row label="Dataset" value={String(drawer.sources?.dataset ?? "—")} />
        <Row label="Reporting date" value={String(drawer.sources?.as_of ?? "—")} />
        <Row
          label="Policy"
          value={`${drawer.policy?.policy_id ?? "—"} ${drawer.policy?.version ?? ""}`}
          note={drawer.policy?.status}
        />
        <Row
          label="Public research"
          value={(drawer.research ?? []).join(", ") || "—"}
          note="context for the mechanism and the safeguards, not evidence that this occurred"
        />
      </Panel>
    </div>
  );
}

function stageLine(stage?: Record<string, number>) {
  if (!stage || !Object.keys(stage).length) return "—";
  return Object.entries(stage)
    .map(([key, value]) => `${key.replace("stage_", "S")} ${value.toLocaleString("en-GB")}`)
    .join(" · ");
}

function CoverageLine({ coverage, what }: { coverage?: Coverage; what: string }) {
  if (!coverage || coverage.eligible === undefined) return null;
  if (coverage.complete) {
    return (
      <p className="pt-1 text-[11px] text-text-muted">
        Complete: all {num(coverage.eligible)} {what} present.
      </p>
    );
  }
  const reasons = Object.values(coverage.missing_reasons ?? {});
  return (
    <p className="pt-1 text-[11px] text-warning">
      Coverage {coverage.coverage_pct?.toFixed(1)}%: {num(coverage.covered)} of{" "}
      {num(coverage.eligible)} {what}.{" "}
      {reasons.length ? reasons.join(" ") : ""} Missing is not zero.
    </p>
  );
}

function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-border bg-surface-subtle p-3">
      <h4 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        {title}
      </h4>
      {note ? (
        <p className="mt-1 text-[11px] leading-relaxed text-text-muted">{note}</p>
      ) : null}
      <dl className="mt-2 space-y-1.5">{children}</dl>
    </section>
  );
}

function Row({
  label,
  value,
  note,
  emphasis,
}: {
  label: string;
  value: string;
  note?: string;
  emphasis?: "denominator";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-text-secondary">
        {label}
        {emphasis === "denominator" ? (
          <span className="ml-1 text-[10px] uppercase tracking-wide text-text-muted">
            denominator
          </span>
        ) : null}
        {note ? (
          <span className="block text-[11px] leading-snug text-text-muted">{note}</span>
        ) : null}
      </dt>
      <dd className="shrink-0 text-xs font-medium tabular-nums text-text-primary">
        {value}
      </dd>
    </div>
  );
}
