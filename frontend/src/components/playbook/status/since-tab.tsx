"use client";

import * as React from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, MessageSquare } from "lucide-react";

import { Locator, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbComparison, PbSinceLastTime } from "@/lib/api";
import {
  movement,
  notComparableReason,
  orderMovements,
} from "@/lib/intelligence";

/**
 * Since last time. §15.
 *
 * THEN is the frozen value the document actually relied on when that version
 * was written. NOW is the latest governed value for the *same* stable metric
 * identity in the *same* context. Neither is recomputed here — both arrive
 * from the backend, which freezes THEN per version and never rewrites it.
 *
 * Where the two are not the same series, this shows **Not comparable** and
 * names the dimension that differs. It never shows a change. A delta between
 * a retail default rate and an all-lending default rate is not a small error;
 * it is a wrong number that looks right, and it is the specific failure this
 * table exists to refuse.
 */
export function SinceTab({
  since,
  onAsk,
  onAskAll,
}: {
  since: PbSinceLastTime;
  onAsk: (metricId: string) => void;
  onAskAll: () => void;
}) {
  const [expanded, setExpanded] = React.useState<string | null>(null);

  if (!since.available) {
    return (
      <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted"
        data-testid="playbook-since-tab">
        There is nothing to compare yet
        {since.reason ? ` — ${since.reason}.` : "."} A comparison needs a
        version that froze its readings and a current value for the same
        metric.
      </p>
    );
  }

  const rows = orderMovements(since.rows);

  return (
    <div className="space-y-4" data-testid="playbook-since-tab">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3">
        <p className="text-sm text-text-secondary">
          <span className="font-semibold text-text-primary">
            {since.compared}
          </span>{" "}
          compared
          {since.worse > 0 && (
            <span className="ml-2 text-negative">{since.worse} worse</span>
          )}
          {since.improved > 0 && (
            <span className="ml-2 text-positive">
              {since.improved} improved
            </span>
          )}
          {since.not_comparable > 0 && (
            <span className="ml-2 text-warning">
              {since.not_comparable} not comparable
            </span>
          )}
        </p>
        <div className="ml-auto">
          <SmallButton onClick={onAskAll} icon={MessageSquare}
            testId="playbook-since-ask-all">
            Explain these movements
          </SmallButton>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[46rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-sunken text-left">
              <Th>Metric</Th>
              <Th className="text-right">Then</Th>
              <Th className="text-right">Now</Th>
              <Th className="text-right">Change</Th>
              <Th>Status</Th>
              <Th>Source</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row
                key={`${row.metric_id}:${row.section_key}`}
                row={row}
                expanded={expanded === row.metric_id}
                onToggle={() =>
                  setExpanded((k) => (k === row.metric_id ? null : row.metric_id))
                }
                onAsk={() => onAsk(row.metric_id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ children, className = "" }: { children?: React.ReactNode;
  className?: string }) {
  return (
    <th className={
      "px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text-muted " +
      className}>
      {children}
    </th>
  );
}

function Row({
  row,
  expanded,
  onToggle,
  onAsk,
}: {
  row: PbComparison;
  expanded: boolean;
  onToggle: () => void;
  onAsk: () => void;
}) {
  const view = movement(row);
  const Arrow =
    view.direction === "worse"
      ? ArrowDownRight
      : view.direction === "improved"
        ? ArrowUpRight
        : ArrowRight;

  return (
    <>
      <tr className="border-b border-border last:border-b-0"
        data-testid="playbook-since-row">
        <td className="px-3 py-2">
          <p className="font-medium text-text-primary">{row.label}</p>
          <p className="text-[10px] text-text-muted">{row.metric_id}</p>
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-secondary">
          {row.then.display || row.then.value || "—"}
          {row.then.version ? (
            <span className="ml-1 text-[10px] text-text-muted">
              v{row.then.version}
            </span>
          ) : null}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-text-primary">
          {/* Shown even when the two are not comparable. The current reading
              is a real governed value; what is illegitimate is subtracting it
              from THEN, and that is what the change column refuses. Blanking
              it here would make "not the same series" look identical to "no
              current governed value at all", which is a different state with a
              different remedy. */}
          {row.now.display || row.now.value || "—"}
        </td>
        <td className="px-3 py-2 text-right tabular-nums">
          {row.comparable ? (
            <span
              className={
                view.direction === "worse"
                  ? "text-negative"
                  : view.direction === "improved"
                    ? "text-positive"
                    : "text-text-secondary"
              }
            >
              {view.change || "—"}
            </span>
          ) : (
            <span className="text-text-muted">—</span>
          )}
        </td>
        <td className="px-3 py-2">
          {row.comparable ? (
            <StatusChip tone={view.tone}>
              <Arrow className="size-3" aria-hidden />
              {view.label}
            </StatusChip>
          ) : (
            <StatusChip tone="unknown">Not comparable</StatusChip>
          )}
        </td>
        <td className="px-3 py-2">
          <Locator value={row.now.locator || row.then.locator} />
        </td>
        <td className="px-3 py-2 text-right">
          <div className="flex justify-end gap-1.5">
            <SmallButton onClick={onToggle} testId="playbook-since-lineage">
              {expanded ? "Hide" : "Lineage"}
            </SmallButton>
            <SmallButton onClick={onAsk} icon={MessageSquare}>
              Ask
            </SmallButton>
          </div>
        </td>
      </tr>

      {!row.comparable && (
        <tr className="border-b border-border bg-surface-warning">
          <td colSpan={7} className="px-3 py-1.5 text-[11px] text-text-primary">
            {/* The mismatching dimension, named. A delta is deliberately not
                shown: a misleading change is worse than a missing one. */}
            {notComparableReason(row)}
          </td>
        </tr>
      )}

      {expanded && (
        <tr className="border-b border-border bg-surface-sunken">
          <td colSpan={7} className="px-3 py-3">
            <div className="grid gap-4 sm:grid-cols-2">
              <Lineage title="Then — what the document relied on"
                data={row.lineage.then} />
              <Lineage title="Now — where the current value comes from"
                data={row.lineage.now} />
            </div>
            <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-muted">
              {[
                ["Unit", row.unit],
                ["Currency", row.currency],
                ["Population", row.population],
                ["Segment", row.segment],
                ["Scenario", row.scenario],
              ]
                .filter(([, v]) => v)
                .map(([label, value]) => (
                  <div key={label} className="flex gap-1.5">
                    <dt>{label}</dt>
                    <dd className="text-text-secondary">{value}</dd>
                  </div>
                ))}
            </dl>
          </td>
        </tr>
      )}
    </>
  );
}

function Lineage({ title, data }: { title: string;
  data: Record<string, unknown> }) {
  const entries = Object.entries(data ?? {}).filter(
    ([, v]) => v !== null && v !== "" && v !== undefined,
  );
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">
        {title}
      </p>
      {entries.length === 0 ? (
        <p className="mt-1 text-[11px] text-text-muted">Nothing recorded.</p>
      ) : (
        <dl className="mt-1 space-y-0.5">
          {entries.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-[11px]">
              <dt className="text-text-muted">{key.replace(/_/g, " ")}</dt>
              <dd className="min-w-0 break-all text-text-secondary">
                {String(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
