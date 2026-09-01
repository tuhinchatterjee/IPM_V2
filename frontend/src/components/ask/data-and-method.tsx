"use client";

import * as React from "react";
import {
  ChevronRight,
  Clock3,
  Database,
  Fingerprint,
  GitMerge,
  Scale,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { EngineResult, JoinPath, JoinStep, ReconciliationStep } from "@/lib/api";

/**
 * Data & method.
 *
 * A multi-dataset answer is only as trustworthy as the joins underneath it, and
 * a reader cannot assess a join they cannot see. So the answer carries four
 * things, in the order a reviewer asks for them:
 *
 *  1. **Which sources**, at which period, and whether they are the bank's own
 *     data or the demonstration book.
 *  2. **How they were joined** — the path, the cardinality, the period rule.
 *     Shown as a compact chain, because "customer_ratings → portfolio_facility,
 *     as-of" is the whole story and a paragraph about it is not.
 *  3. **What happened to the population** at each step. A join that lost a
 *     third of the book is the single most common way a composed analysis
 *     misleads, and it is reported as a count rather than left to be noticed.
 *  4. **What identifies the run**, so two runs that disagree can be compared.
 *
 * Collapsed by default. The claim is that the working is always available, not
 * that everyone must read it before believing the number.
 */

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "1 : 1",
  many_to_one: "many : 1",
  one_to_many: "1 : many",
  many_to_many: "many : many",
};

export function DataAndMethod({ result }: { result: EngineResult }) {
  const joins = result.joins ?? [];
  const reconciliation = result.reconciliation ?? [];
  const plan = result.join_plan ?? null;
  const datasets = result.datasets ?? [];
  const fingerprint = result.fingerprint;

  // A single-dataset answer has no join to explain, and an empty disclosure is
  // worse than none: it implies there is something hidden.
  if (datasets.length < 2 && joins.length === 0) return null;

  return (
    <details className="group border-t border-border bg-surface-sunken px-5 py-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-text-secondary hover:text-text-primary">
        <ChevronRight
          className="size-3.5 transition-transform group-open:rotate-90"
          aria-hidden
        />
        Data &amp; method
        <span className="font-normal text-text-muted">
          {datasets.length} {datasets.length === 1 ? "source" : "sources"}
          {joins.length > 0 && `, ${joins.length} ${joins.length === 1 ? "join" : "joins"}`}
        </span>
        {result.certification_label && (
          <Badge
            variant={result.certification === "certified" ? "accent" : "outline"}
            className="ml-auto"
          >
            {result.certification_label}
          </Badge>
        )}
      </summary>

      <div className="mt-3 space-y-4">
        {datasets.length > 0 && (
          <Block icon={Database} title="Governed sources">
            <div className="flex flex-wrap gap-1.5">
              {datasets.map((name) => (
                <code
                  key={name}
                  className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11px] text-text-secondary"
                >
                  {name}
                </code>
              ))}
            </div>
            {fingerprint?.datasets?.length ? (
              <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
                Read at{" "}
                {fingerprint.datasets
                  .map((d) => `${d.dataset} v${d.version}${d.periods.length ? ` (${d.periods.join(", ")})` : ""}`)
                  .join("; ")}
                .
              </p>
            ) : null}
          </Block>
        )}

        {plan && plan.paths.length > 0 && (
          <Block icon={GitMerge} title="How they were joined">
            <ul className="space-y-1.5">
              {plan.paths.map((path) => (
                <li key={path.target}>
                  <JoinPathChain path={path} />
                </li>
              ))}
            </ul>
            {plan.warnings?.length ? (
              <ul className="mt-2 space-y-1">
                {plan.warnings.map((warning) => (
                  <li
                    key={warning}
                    className="flex items-start gap-1.5 text-[11px] leading-relaxed text-warning"
                  >
                    <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
                    {warning}
                  </li>
                ))}
              </ul>
            ) : null}
          </Block>
        )}

        {reconciliation.length > 0 && (
          <Block icon={Scale} title="What happened to the population">
            <ul className="space-y-1">
              {reconciliation.map((step) => (
                <ReconciliationRow key={step.step} step={step} />
              ))}
            </ul>
            <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
              Counted against the same query that produced the answer, not
              re-derived afterwards.
            </p>
          </Block>
        )}

        {joins.length > 0 && (
          <Block icon={ShieldCheck} title="The relationships used">
            <ul className="space-y-1.5">
              {joins.map((join) => (
                <JoinRow key={join.step} join={join} />
              ))}
            </ul>
          </Block>
        )}

        {fingerprint?.run && (
          <Block icon={Fingerprint} title="What identifies this run">
            <dl className="flex flex-wrap gap-x-4 gap-y-1">
              {(
                [
                  ["Run", fingerprint.run],
                  ["Plan", fingerprint.plan],
                  ["Data", fingerprint.data],
                  ["Relationships", fingerprint.relationships],
                  ["Parameters", fingerprint.parameters],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="flex items-baseline gap-1.5">
                  <dt className="text-[10px] text-text-muted">{label}</dt>
                  <dd className="font-mono text-[10px] text-text-secondary">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
              Hashed separately, so two runs that disagree can say whether the
              analysis changed, the data was restated, a join was re-declared, or
              only the period moved.
            </p>
          </Block>
        )}

        {result.explanation && (
          <p className="whitespace-pre-line border-t border-border pt-3 text-[11px] leading-relaxed text-text-muted">
            {result.explanation}
          </p>
        )}
      </div>
    </details>
  );
}

/**
 * One join path, as a chain.
 *
 * `ifrs9_staging → portfolio_facility` with the cardinality on the arrow reads
 * in one glance; the same thing as a sentence takes a paragraph and is skipped.
 */
export function JoinPathChain({ path }: { path: JoinPath }) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-[11px]">
      {path.edges.map((edge, index) => (
        <React.Fragment key={`${edge.relationship_id}-${index}`}>
          {index === 0 && (
            <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-text-secondary">
              {edge.left}
            </code>
          )}
          <span
            className={cn(
              "px-0.5",
              edge.multiplies_left ? "text-warning" : "text-text-muted",
            )}
            title={edge.semantic || undefined}
          >
            —{CARDINALITY_LABEL[edge.cardinality] ?? edge.cardinality}→
          </span>
          <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-text-secondary">
            {edge.right}
          </code>
        </React.Fragment>
      ))}
      {path.needs_asof && (
        <span className="ml-1 flex items-center gap-1 text-text-muted">
          <Clock3 className="size-3" aria-hidden />
          as-of
        </span>
      )}
      {path.multiplies && (
        <span className="ml-1 text-warning">rolled up before joining</span>
      )}
    </div>
  );
}

function JoinRow({ join }: { join: JoinStep }) {
  return (
    <li className="text-[11px] leading-relaxed">
      <span className="text-text-primary">{join.label}</span>
      {join.relationship_name && (
        <span className="ml-1.5 text-text-muted">
          {join.relationship_name}
          {join.relationship_version !== undefined &&
            ` · v${join.relationship_version}`}
        </span>
      )}
      <div className="text-text-muted">
        {join.keys.length > 0 && (
          <span className="font-mono">{join.keys.join(", ")}</span>
        )}
        {join.cardinality && (
          <span className="ml-1.5">
            {CARDINALITY_LABEL[join.cardinality] ?? join.cardinality}
          </span>
        )}
        {join.policy && <span className="ml-1.5">{join.policy}</span>}
        {join.rows_out !== null && (
          <span className="ml-1.5 tabular">{join.rows_out.toLocaleString()} rows out</span>
        )}
      </div>
      {join.note && <p className="text-text-muted">{join.note}</p>}
    </li>
  );
}

function ReconciliationRow({ step }: { step: ReconciliationStep }) {
  const lost = step.lost ?? 0;
  // A roll-up to customer level is meant to reduce the row count. Flagging it
  // as loss would train a reader to ignore the one number that matters.
  const worrying = !step.reduced_by_design && lost > 0;
  return (
    <li className="flex items-baseline justify-between gap-3 text-[11px] leading-relaxed">
      <span className="min-w-0 text-text-secondary">{step.label || step.step}</span>
      <span className="shrink-0 tabular text-text-muted">
        {step.rows.toLocaleString()} rows
        {lost > 0 && (
          <span className={worrying ? "ml-1.5 text-warning" : "ml-1.5"}>
            {step.reduced_by_design ? "rolled up from" : "−"}
            {" "}
            {lost.toLocaleString()}
            {step.lost_pct !== null && ` (${(step.lost_pct * 100).toFixed(1)}%)`}
          </span>
        )}
      </span>
    </li>
  );
}

function Block({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Database;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
        <Icon className="size-3" aria-hidden />
        {title}
      </p>
      {children}
    </section>
  );
}
