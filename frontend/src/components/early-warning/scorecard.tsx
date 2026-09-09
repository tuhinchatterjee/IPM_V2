"use client";

import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import type {
  BorrowerScorecard,
  BorrowerTimeline,
  RiskAssessment,
  ScorecardComponent,
  ScorecardLayer,
} from "@/lib/api";
import { api } from "@/lib/api";
import * as ew from "@/lib/early-warning-format";
import { cn } from "@/lib/utils";

import { LEVEL_INK, LEVEL_TONE, RiskLevelBadge } from "./risk-levels";

/**
 * One borrower's four-layer Early Warning scorecard. Sections 11C, 11D, 11G,
 * 11I and 11J.
 *
 * The screen used to show which signals fired and how bad the worst one was.
 * It did not show, for any single condition, what the value is now, what it
 * was last time, which way it moved, what the line is, or whether it has been
 * true before — so a reader could not tell a name that has just crossed a line
 * from one that has been over it for a year.
 *
 * Order matters here. The ASSESSMENT comes first: the level, what it means,
 * and the sentences that put it there. A reader who stops after the first
 * screen should still have the answer rather than the workings.
 */

const OVER = "Over threshold";

function Movement({ value }: { value: number | null }) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className="text-text-muted">—</span>;
  }
  if (value === 0) return <span className="text-text-muted">no change</span>;
  const up = value > 0;
  return (
    <span className={cn("tabular-nums", up ? "text-negative" : "text-positive")}>
      {up ? "▲" : "▼"} {Math.abs(value).toLocaleString("en-US", {
        maximumFractionDigits: 2,
      })}
    </span>
  );
}

function Cell({
  value,
  unit,
  currency,
}: {
  value: number | string | null;
  unit: string;
  currency: string;
}) {
  return (
    <span className="tabular-nums">
      {ew.showValue(value, unit, currency || "SAR")}
    </span>
  );
}

export function ComponentTable({
  layer,
  columns,
  currency,
}: {
  layer: ScorecardLayer;
  columns: string[];
  currency: string;
}) {
  const [showAll, setShowAll] = React.useState(false);
  const rows = showAll
    ? layer.components
    : layer.components.filter((c) => c.status === OVER || !c.available);
  const hidden = layer.components.length - rows.length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-text-secondary">{layer.sentence}</p>
        {hidden > 0 || showAll ? (
          <Button
            variant="link"
            className="h-auto p-0 text-xs"
            onClick={() => setShowAll((was) => !was)}
          >
            {showAll
              ? "Show only what is over the line"
              : `Show ${hidden} condition${hidden === 1 ? "" : "s"} within threshold`}
          </Button>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="rounded border border-border bg-surface-raised p-4 text-xs text-text-muted">
          Every tested condition in this layer is within its threshold.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[52rem] text-xs">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="py-2 pr-3 font-medium">Condition</th>
                {columns.slice(0, 8).map((name) => (
                  <th key={name} className="py-2 pr-3 font-medium">
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((component) => (
                <ComponentRow
                  key={component.signal}
                  component={component}
                  currency={currency}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-text-muted">
        {layer.matters}
      </p>
      {layer.gap ? (
        <p className="rounded border border-border bg-surface-raised p-3 text-[11px] leading-relaxed text-text-muted">
          {layer.gap}
        </p>
      ) : null}
    </div>
  );
}

function ComponentRow({
  component,
  currency,
}: {
  component: ScorecardComponent;
  currency: string;
}) {
  const over = component.status === OVER;
  return (
    <>
      <tr className={cn("border-b border-border", over && "bg-negative-muted")}>
        <td className="py-2 pr-3 font-medium">{component.label}</td>
        <td className="py-2 pr-3">
          <Cell
            value={component.current}
            unit={component.unit}
            currency={currency}
          />
        </td>
        <td className="py-2 pr-3 text-text-secondary">
          <Cell
            value={component.previous}
            unit={component.unit}
            currency={currency}
          />
        </td>
        <td className="py-2 pr-3">
          <Movement value={component.movement} />
        </td>
        <td className="py-2 pr-3 text-text-secondary">
          {/* The phrase, not the signed number: a ratio test encodes "at or
              below 5%" as -5.0, and printing that beside a current value of
              2.6% marked "over threshold" asks the reader to reconcile three
              things that do not add up. */}
          {component.threshold_reads || (
            <Cell
              value={component.threshold}
              unit={component.unit}
              currency={currency}
            />
          )}
        </td>
        <td className="py-2 pr-3">
          <span className={over ? "text-negative" : "text-text-secondary"}>
            {component.status}
          </span>
        </td>
        <td className="py-2 pr-3 text-text-secondary">{component.severity}</td>
        <td className="py-2 pr-3 text-text-secondary">
          {component.persistence}
        </td>
        <td className="py-2 pr-3" title={component.detection_means}>
          <Badge variant="outline">{component.detection_letter}</Badge>
        </td>
      </tr>
      <tr className={cn("border-b border-border", over && "bg-negative-muted")}>
        <td colSpan={9} className="pb-3 pr-3 text-[11px] leading-relaxed text-text-muted">
          {component.available ? component.means : component.unavailable}
        </td>
      </tr>
    </>
  );
}

export function Assessment({ found }: { found: RiskAssessment }) {
  return (
    <Card
      className={cn("p-5", LEVEL_TONE[found.level] ?? LEVEL_TONE.LOW)}
    >
      <div className="flex flex-wrap items-center gap-3">
        <RiskLevelBadge level={found.level} />
        <p className={cn("text-sm font-medium", LEVEL_INK[found.level])}>
          {found.primary_concern}
        </p>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-text-secondary">
        {found.means}
      </p>
      {found.why_now ? (
        <p className="mt-3 text-xs leading-relaxed">{found.why_now}</p>
      ) : null}

      <div className="mt-5 space-y-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Why
          </p>
          <ul className="mt-2 space-y-2">
            {found.reasons.map((reason) => (
              <li
                key={reason.rule}
                className="text-xs leading-relaxed text-text-secondary"
              >
                {reason.says}
              </li>
            ))}
          </ul>
        </div>

        {found.mitigating.length ? (
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
              Evidence the other way
            </p>
            <ul className="mt-2 space-y-2">
              {found.mitigating.map((reason) => (
                <li
                  key={reason.rule}
                  className="text-xs leading-relaxed text-text-secondary"
                >
                  {reason.says}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <p className="mt-5 text-[11px] text-text-muted">
        {found.family_labels.length} famil
        {found.family_labels.length === 1 ? "y" : "ies"} carrying evidence ·{" "}
        {found.corroborating.length} corroborating · owned by {found.owner}
      </p>
    </Card>
  );
}

export function Timeline({ timeline }: { timeline: BorrowerTimeline }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium">How this developed</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-xs">
          <thead>
            <tr className="border-b border-border text-left text-text-muted">
              <th className="py-2 pr-3 font-medium">Period</th>
              <th className="py-2 pr-3 font-medium">Risk</th>
              <th className="py-2 pr-3 font-medium">Conditions firing</th>
              <th className="py-2 pr-3 font-medium">Families</th>
              <th className="py-2 pr-3 font-medium">Primary concern</th>
              <th className="py-2 pr-3 font-medium">What changed</th>
            </tr>
          </thead>
          <tbody>
            {timeline.entries.map((entry) => (
              <tr key={entry.period} className="border-b border-border">
                <td className="py-2 pr-3 font-medium">{entry.period}</td>
                <td className="py-2 pr-3">
                  {entry.on_book ? (
                    <RiskLevelBadge level={entry.risk_level} />
                  ) : (
                    <span className="text-text-muted">not on book</span>
                  )}
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {entry.on_book ? entry.fired : "—"}
                </td>
                <td className="py-2 pr-3 tabular-nums">
                  {entry.on_book ? entry.families : "—"}
                </td>
                <td className="py-2 pr-3 text-text-secondary">
                  {entry.primary_concern || "—"}
                </td>
                <td className="py-2 pr-3 text-text-secondary">
                  {entry.why_now || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-relaxed text-text-muted">
        {timeline.statement}
      </p>
    </section>
  );
}

export function BorrowerScorecardView({
  card,
  timeline,
}: {
  card: BorrowerScorecard;
  timeline?: BorrowerTimeline | null;
}) {
  const [layer, setLayer] = React.useState(card.layers[0]?.layer ?? "");
  const active =
    card.layers.find((entry) => entry.layer === layer) ?? card.layers[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">{card.borrower_id}</h2>
          <p className="text-xs text-text-muted">
            {card.period} · thresholds owned by {card.owner}, version{" "}
            {card.taxonomy_version}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline">
            <Link href={card.borrower_360.href}>{card.borrower_360.label}</Link>
          </Button>
          <Button asChild variant="outline">
            <a
              href={api.borrowerScorecardWorkbookUrl(
                card.borrower_id,
                card.period,
              )}
            >
              Download the scorecard
            </a>
          </Button>
        </div>
      </div>

      <Assessment found={card.assessment} />

      <section className="space-y-4">
        <h3 className="text-sm font-medium">Every governed condition</h3>
        <Tabs
          active={active?.layer ?? ""}
          onChange={setLayer}
          tabs={card.layers.map((entry) => ({
            id: entry.layer,
            label: `${entry.number}. ${entry.name.split(",")[0]}`,
            count: entry.over,
          }))}
        />
        {active ? (
          <ComponentTable
            layer={active}
            columns={card.columns}
            currency={card.currency}
          />
        ) : null}
        <p className="text-[11px] leading-relaxed text-text-muted">
          {card.statement}
        </p>
      </section>

      {timeline ? <Timeline timeline={timeline} /> : null}
    </div>
  );
}
