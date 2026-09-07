"use client";

/**
 * The pieces every What-If screen is built from.
 *
 * Two rules hold this file together.
 *
 * A number never appears without what it is a number OF. Every result carries
 * the period, the population, the staging criteria and the ECL methodology,
 * because "provisions rise 38%" invites "on what book, under whose rules, by
 * which model?" and a screen that cannot answer does not survive a committee.
 *
 * Baseline and What-If are visually distinct everywhere. A table with two
 * money columns and no distinction between the reported book and a
 * hypothetical is how somebody quotes the wrong one.
 */

import * as React from "react";
import { useState } from "react";

import { CategoryBarChart } from "@/components/analytics/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  WhatIfContext,
  WhatIfGate,
  WhatIfMigration,
  WhatIfProfileRow,
  WhatIfStaging,
  WhatIfStagingKind,
  WhatIfStagingRuleIn,
  WhatIfStepState,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------ formatting */

/** Money, in the book's own currency, with no decimals it cannot support. */
export function money(value: number | null | undefined, currency = "SAR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const formatted =
    abs >= 1_000_000
      ? `${(value / 1_000_000).toFixed(2)}m`
      : abs >= 1_000
        ? `${(value / 1_000).toFixed(1)}k`
        : value.toFixed(0);
  return `${currency} ${formatted}`;
}

/** A percentage, at the precision the underlying figure actually justifies. */
export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString();
}

/* ---------------------------------------------------------------- pieces */

/** One figure, labelled, with room for the thing that qualifies it. */
export function Figure({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "neutral" | "baseline" | "whatif" | "positive" | "negative";
}) {
  const tones: Record<string, string> = {
    neutral: "text-text-primary",
    baseline: "text-text-secondary",
    whatif: "text-accent",
    positive: "text-positive",
    negative: "text-negative",
  };
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className={cn("mt-1 truncate text-[19px] font-semibold tabular-nums", tones[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div> : null}
    </div>
  );
}

/**
 * The provenance line above every result.
 *
 * This is the component that makes a What-If quotable. Everything in it is a
 * fact about how the number was produced, not about the number.
 */
export function ResultContext({ context }: { context: WhatIfContext }) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px]">
        <span className="font-medium text-text-primary">{context.domain}</span>
        <Badge variant="outline">{context.period}</Badge>
        <span className="text-text-muted">{context.grain}</span>
        <Badge variant="accent">{context.methodology_stamp}</Badge>
        <span className="text-text-muted">
          Staging {context.staging_version}
        </span>
        <span className="text-text-muted">
          Macro sensitivities v{context.macro_version}
        </span>
      </div>
      <div className="mt-2 text-[12px] text-text-secondary">
        <span className="text-text-muted">Scenario: </span>
        {context.scenario}
      </div>
      <div className="text-[12px] text-text-secondary">
        <span className="text-text-muted">Population: </span>
        {context.population} — {count(context.population_count)} borrowers
      </div>
    </div>
  );
}

/** Baseline, What-If, and both forms of the change. */
export function EclHeadline({
  context,
  currency = "SAR",
}: {
  context: WhatIfContext;
  currency?: string;
}) {
  const worse = context.absolute_change > 0;
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Figure
        label="Official baseline ECL"
        value={money(context.baseline_ecl, currency)}
        hint="As reported, including overlay"
        tone="baseline"
      />
      <Figure
        label="What-If ECL"
        value={money(context.whatif_ecl, currency)}
        hint={context.methodology_stamp}
        tone="whatif"
      />
      <Figure
        label="Absolute change"
        value={money(context.absolute_change, currency)}
        tone={worse ? "negative" : "positive"}
      />
      <Figure
        label="Percentage change"
        value={signed(context.percentage_change)}
        tone={worse ? "negative" : "positive"}
      />
    </div>
  );
}

/**
 * The methodology gate.
 *
 * Rendered as buttons because a finite choice deserves buttons, and always
 * alongside the composer, because "use ML but compare it to Delta" is a
 * reasonable thing to want and no button covers it.
 */
export function MethodologyGate({
  gate,
  onChoose,
  busy,
}: {
  gate: WhatIfGate;
  onChoose: (method: string) => void;
  busy?: boolean;
}) {
  return (
    <Card className="border-accent/40">
      <CardHeader>
        <CardTitle className="text-[15px]">{gate.question}</CardTitle>
        <p className="mt-1 text-[12px] text-text-muted">{gate.why}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          {gate.options.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={!option.available || busy}
              onClick={() => onChoose(option.value)}
              data-methodology={option.value}
              className={cn(
                "rounded-md border border-border bg-surface p-3 text-left transition-colors",
                option.available
                  ? "hover:border-accent hover:bg-surface-hover"
                  : "cursor-not-allowed opacity-60",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium text-text-primary">
                  {option.label}
                </span>
                {option.version ? (
                  <span className="text-[11px] text-text-muted">v{option.version}</span>
                ) : null}
              </div>
              <p className="mt-1 text-[12px] text-text-secondary">{option.summary}</p>
              {option.detail ? (
                <p className="mt-1 text-[11px] text-text-muted">{option.detail}</p>
              ) : null}
              {!option.available && option.unavailable_because ? (
                <p className="mt-1 text-[11px] text-warning">
                  {option.unavailable_because}
                </p>
              ) : null}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-text-muted">{gate.note}</p>
      </CardContent>
    </Card>
  );
}

/** The staging criteria, viewable and editable, near the top of every thread. */
export function StagingRuleTable({
  staging,
  onChange,
  onRemove,
}: {
  staging: WhatIfStaging;
  onChange?: (key: string, changes: WhatIfStagingRuleIn) => void;
  onRemove?: (key: string) => void;
}) {
  const editable = staging.editable !== false && Boolean(onChange);
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Rule</TableHead>
            <TableHead>What it says</TableHead>
            <TableHead numeric>Threshold</TableHead>
            <TableHead>Basis</TableHead>
            <TableHead>On</TableHead>
            {onRemove ? <TableHead /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {staging.rules.map((rule) => (
            <TableRow key={rule.key} data-rule={rule.key} data-scope={staging.scope}>
              <TableCell className="font-medium">{rule.name}</TableCell>
              <TableCell className="text-text-secondary">{rule.rule}</TableCell>
              <TableCell numeric>
                {editable ? (
                  <input
                    type="number"
                    step="0.01"
                    defaultValue={rule.threshold}
                    aria-label={`${rule.name} threshold`}
                    onBlur={(e) => onChange?.(rule.key, { key: rule.key, threshold: Number(e.target.value) })}
                    className="w-20 rounded border border-border bg-surface px-2 py-1 text-right tabular-nums"
                  />
                ) : (
                  rule.threshold
                )}
              </TableCell>
              <TableCell>
                <Badge variant={rule.governed ? "info" : "warning"}>
                  {rule.governed ? "Governed" : "Assumption"}
                </Badge>
              </TableCell>
              <TableCell>
                <input
                  type="checkbox"
                  defaultChecked={rule.enabled}
                  disabled={!editable}
                  aria-label={`${rule.name} enabled`}
                  onChange={(e) => onChange?.(rule.key, { key: rule.key, enabled: e.target.checked })}
                />
              </TableCell>
              {onRemove ? (
                <TableCell>
                  {rule.governed ? (
                    <span className="text-[11px] text-text-muted">kept</span>
                  ) : (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${rule.name}`}
                      onClick={() => onRemove(rule.key)}
                    >
                      Remove
                    </Button>
                  )}
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Compose a new rule. Kept deliberately small: a kind, a number, a name. */
function AddStagingRule({
  kinds,
  onAdd,
}: {
  kinds: WhatIfStagingKind[];
  onAdd: (rule: WhatIfStagingRuleIn) => void;
}) {
  const [kind, setKind] = useState(kinds[0]?.kind ?? "");
  const [threshold, setThreshold] = useState("2");
  const [name, setName] = useState("");
  const chosen = kinds.find((k) => k.kind === kind);
  if (!kinds.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface-subtle p-3" data-testid="staging-add">
      <div className="mb-2 text-[12px] font-medium text-text-primary">Add a rule</div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-text-muted">
          Kind
          <select
            aria-label="New rule kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-[12px] text-text-primary"
          >
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-text-muted">
          Threshold{chosen ? ` (${chosen.threshold_unit})` : ""}
          <input
            type="number"
            step="0.01"
            aria-label="New rule threshold"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            className="w-24 rounded border border-border bg-surface px-2 py-1 text-right tabular-nums"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-text-muted">
          Name
          <input
            type="text"
            aria-label="New rule name"
            placeholder={chosen?.label ?? ""}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-56 rounded border border-border bg-surface px-2 py-1 text-[12px]"
          />
        </label>
        <Button
          size="sm"
          data-testid="staging-add-submit"
          onClick={() => {
            const label = name.trim() || chosen?.label || kind;
            onAdd({
              key: `custom_${kind}_${Date.now().toString(36)}`,
              kind,
              name: label,
              threshold: Number(threshold),
              enabled: true,
              note: "Added for this What-If thread.",
            });
            setName("");
          }}
        >
          Add rule
        </Button>
      </div>
      {chosen ? (
        <p className="mt-2 text-[11px] text-text-muted">
          {chosen.threshold_means}. Needs <code>{chosen.needs}</code>.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The two staging rule sets, side by side.
 *
 * The reported-book set is shown and never edited: it is what staged the
 * accounts, and the baseline column of every What-If ties to it. The What-If
 * set is this thread's, and everything about it can be changed — thresholds,
 * which rules are on, rules added or removed, and whether a borrower needs to
 * trip ANY rule or EVERY rule.
 */
export function StagingCriteria({
  staging,
  reported,
  kinds,
  combinations,
  onChange,
  onAdd,
  onRemove,
  onCombination,
  onReset,
  open,
  onToggle,
}: {
  staging: WhatIfStaging;
  reported?: WhatIfStaging | null;
  kinds?: WhatIfStagingKind[];
  combinations?: string[];
  onChange?: (key: string, changes: WhatIfStagingRuleIn) => void;
  onAdd?: (rule: WhatIfStagingRuleIn) => void;
  onRemove?: (key: string) => void;
  onCombination?: (how: string) => void;
  onReset?: () => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [showReported, setShowReported] = useState(false);
  const options = combinations?.length ? combinations : ["ANY", "ALL"];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <div>
          <CardTitle className="text-[14px]">Staging criteria</CardTitle>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {staging.is_default
              ? "The default What-If rule set: the governed triggers plus Rule A and Rule B."
              : "Overridden for this What-If. Every result says so."}{" "}
            <span className="tabular-nums" data-testid="whatif-staging-version">
              {staging.version}
            </span>
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onToggle} data-testid="staging-toggle">
          {open ? "Hide" : "Define staging criteria"}
        </Button>
      </CardHeader>
      {open ? (
        <CardContent className="space-y-4">
          <div data-testid="whatif-staging" data-scope={staging.scope}>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <div className="text-[12px] font-medium text-text-primary">{staging.label}</div>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1 text-[11px] text-text-muted">
                  Combine with
                  <select
                    aria-label="Combine staging rules"
                    data-testid="staging-combination"
                    value={staging.combination}
                    disabled={!onCombination}
                    onChange={(e) => onCombination?.(e.target.value)}
                    className="rounded border border-border bg-surface px-2 py-1 text-[12px] text-text-primary"
                  >
                    {options.map((how) => (
                      <option key={how} value={how}>
                        {how}
                      </option>
                    ))}
                  </select>
                </label>
                {onReset ? (
                  <Button variant="ghost" size="sm" onClick={onReset} data-testid="staging-reset">
                    Reset
                  </Button>
                ) : null}
              </div>
            </div>
            <p className="mb-2 text-[11px] text-text-muted">{staging.scope_note}</p>
            <p className="mb-2 text-[11px] text-text-muted">{staging.combination_note}</p>
            <StagingRuleTable staging={staging} onChange={onChange} onRemove={onRemove} />
          </div>

          {onAdd && kinds?.length ? <AddStagingRule kinds={kinds} onAdd={onAdd} /> : null}

          {reported ? (
            <div data-testid="reported-staging" data-scope={reported.scope}>
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="text-[12px] font-medium text-text-primary">
                  {reported.label}{" "}
                  <span className="tabular-nums text-[11px] text-text-muted">
                    {reported.version}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  data-testid="reported-staging-toggle"
                  onClick={() => setShowReported((was) => !was)}
                >
                  {showReported ? "Hide" : "Show"}
                </Button>
              </div>
              <p className="mb-2 text-[11px] text-text-muted">{reported.scope_note}</p>
              {showReported ? <StagingRuleTable staging={reported} /> : null}
            </div>
          ) : null}

          <p className="text-[11px] text-text-muted">{staging.default_presumption}</p>
          <p className="text-[11px] text-text-muted">
            Rules marked <strong>Assumption</strong> are CreditProbe What-If settings
            chosen by the person asking. They are not requirements of IFRS 9, and they
            change the What-If column only — never the reported book.
          </p>
        </CardContent>
      ) : null}
    </Card>
  );
}

/** The layered scenario, with the operations a person actually asks for. */
export function ScenarioSteps({
  steps,
  onRemove,
  onReset,
  onUndo,
  canUndo,
}: {
  steps: WhatIfStepState[];
  onRemove: (id: string) => void;
  onReset: () => void;
  onUndo: () => void;
  canUndo: boolean;
}) {
  if (!steps.length) {
    return (
      <p className="text-[12px] text-text-muted">
        No shock applied yet — this is the reported position.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <ol className="space-y-1.5">
        {steps.map((step, index) => (
          <li
            key={step.step_id}
            data-step-kind={step.kind}
            className="flex items-start gap-2 rounded-md border border-border bg-surface px-3 py-2"
          >
            <span className="mt-0.5 text-[11px] tabular-nums text-text-muted">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] text-text-primary">
                {step.interpreted || step.instruction}
              </div>
              {step.label ? (
                <div className="text-[11px] text-text-muted">{step.label}</div>
              ) : null}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemove(step.step_id)}
              aria-label={`Remove step ${index + 1}`}
            >
              Remove
            </Button>
          </li>
        ))}
      </ol>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onUndo} disabled={!canUndo}>
          Undo
        </Button>
        <Button variant="outline" size="sm" onClick={onReset}>
          Reset to baseline
        </Button>
      </div>
    </div>
  );
}

/** A profile table — ratings, stages or sectors — with its totals row. */
export function ProfileTable({
  rows,
  total,
  first = "Rating",
  currency = "SAR",
  extra = [],
}: {
  rows: WhatIfProfileRow[];
  total?: WhatIfProfileRow;
  first?: string;
  currency?: string;
  extra?: { key: string; label: string; format?: (v: unknown) => string }[];
}) {
  const line = (row: WhatIfProfileRow, isTotal = false) => (
    <TableRow
      key={row.label}
      data-row={row.label}
      className={isTotal ? "font-semibold" : undefined}
    >
      <TableCell>{row.label}</TableCell>
      <TableCell numeric>{count(row.count)}</TableCell>
      <TableCell numeric>{pct(row.count_pct)}</TableCell>
      <TableCell numeric>{money(row.exposure, currency)}</TableCell>
      <TableCell numeric>{pct(row.exposure_pct)}</TableCell>
      <TableCell numeric>{pct(row.avg_pd_12m, 3)}</TableCell>
      <TableCell numeric>{pct(row.avg_pd_lifetime, 3)}</TableCell>
      <TableCell numeric>{pct(row.avg_pd_applicable, 3)}</TableCell>
      <TableCell numeric>{pct(row.avg_lgd, 2)}</TableCell>
      <TableCell numeric>
        {row.avg_ccf === null ? "—" : pct(row.avg_ccf * 100, 1)}
      </TableCell>
      <TableCell numeric>{money(row.ecl, currency)}</TableCell>
      <TableCell numeric>{pct(row.ecl_coverage_pct, 3)}</TableCell>
      {extra.map((column) => (
        <TableCell key={column.key} numeric>
          {column.format ? column.format(row[column.key]) : String(row[column.key] ?? "—")}
        </TableCell>
      ))}
    </TableRow>
  );
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{first}</TableHead>
            <TableHead numeric>Accounts</TableHead>
            <TableHead numeric>Accounts %</TableHead>
            <TableHead numeric>Exposure</TableHead>
            <TableHead numeric>Exposure %</TableHead>
            <TableHead numeric>12m PD</TableHead>
            <TableHead numeric>Lifetime PD</TableHead>
            <TableHead numeric>Applicable PD</TableHead>
            <TableHead numeric>LGD</TableHead>
            <TableHead numeric>CCF %</TableHead>
            <TableHead numeric>ECL</TableHead>
            <TableHead numeric>Coverage</TableHead>
            {extra.map((c) => (
              <TableHead key={c.key} numeric>
                {c.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => line(row))}
          {total ? line(total, true) : null}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * A migration matrix with its Total row and column — 15 x 15 for the fourteen
 * governed grades, 4 x 4 for the three Stages.
 */
export function MigrationMatrix({
  migration,
  view,
  onView,
  currency = "SAR",
}: {
  migration: WhatIfMigration;
  view: string;
  onView: (view: string) => void;
  currency?: string;
}) {
  const body = migration.views[view];
  if (!body) return null;
  const isMoney = view === "exposure";
  const isShare = view.endsWith("_pct");
  const show = (value: number) =>
    value === 0
      ? ""
      : isMoney
        ? money(value, currency)
        : isShare
          ? pct(value, 2)
          : count(value);
  const views: { key: string; label: string }[] = [
    { key: "count", label: "Account count" },
    { key: "count_pct", label: "Account %" },
    { key: "exposure", label: "Exposure" },
    { key: "exposure_pct", label: "Exposure %" },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {views.map((option) => (
          <Button
            key={option.key}
            size="sm"
            variant={view === option.key ? "default" : "outline"}
            onClick={() => onView(option.key)}
            data-view={option.key}
          >
            {option.label}
          </Button>
        ))}
        <span className="ml-auto text-[11px] text-text-muted">
          {migration.opening_period} → {migration.closing_period} ·{" "}
          {migration.displayed_shape} displayed
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[11px]" data-testid="migration-matrix">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 border border-border bg-surface-sunken px-2 py-1 text-left">
                From \\ To
              </th>
              {body.labels.map((label) => (
                <th key={label} className="border border-border bg-surface-sunken px-2 py-1">
                  {label}
                </th>
              ))}
              <th className="border border-border bg-surface-sunken px-2 py-1 font-semibold">
                {migration.total_label}
              </th>
            </tr>
          </thead>
          <tbody>
            {body.rows.map((row) => (
              <tr key={row.label}>
                <th className="sticky left-0 z-10 border border-border bg-surface-sunken px-2 py-1 text-left font-medium">
                  {row.label}
                </th>
                {row.cells.map((cell, index) => (
                  <td
                    key={`${row.label}-${index}`}
                    className={cn(
                      "border border-border px-2 py-1 text-right tabular-nums",
                      index === body.labels.indexOf(row.label)
                        ? "bg-surface-sunken font-medium"
                        : cell > 0
                          ? "bg-surface"
                          : "bg-surface text-text-muted",
                    )}
                  >
                    {show(cell)}
                  </td>
                ))}
                <td className="border border-border bg-surface-sunken px-2 py-1 text-right font-semibold tabular-nums">
                  {show(row.total)}
                </td>
              </tr>
            ))}
            <tr>
              <th className="sticky left-0 z-10 border border-border bg-surface-sunken px-2 py-1 text-left font-semibold">
                {migration.total_label}
              </th>
              {body.column_totals.map((value, index) => (
                <td
                  key={`total-${index}`}
                  className="border border-border bg-surface-sunken px-2 py-1 text-right font-semibold tabular-nums"
                >
                  {show(value)}
                </td>
              ))}
              <td className="border border-border bg-surface-sunken px-2 py-1 text-right font-semibold tabular-nums">
                {show(body.grand_total)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-text-muted">
        {migration.note} Continuing {count(migration.continuing.count)} · exited{" "}
        {count(migration.exited.count)} · new {count(migration.new.count)}.
      </p>
    </div>
  );
}

/**
 * Baseline against What-If, for a dimension the scenario actually moved.
 *
 * Two bars per row rather than one, because the whole question is a
 * comparison, and a chart of the stressed position alone answers half of it.
 * Rendered only where the scenario moved something: a Stage chart on a
 * scenario that did not touch staging is noise dressed as evidence.
 */
export function BeforeAfterChart({
  title,
  rows,
  currency = "SAR",
  measure = "ecl",
}: {
  title: string;
  rows: { label: string; before: number; after: number }[];
  currency?: string;
  measure?: "ecl" | "exposure";
}) {
  const moved = rows.filter((r) => r.before !== 0 || r.after !== 0);
  if (!moved.length) return null;
  return (
    <div data-chart={measure}>
      <div className="mb-1 text-[12px] font-medium text-text-primary">{title}</div>
      <CategoryBarChart
        data={moved.map((r) => ({
          label: r.label,
          before: Number(r.before.toFixed(2)),
          after: Number(r.after.toFixed(2)),
        }))}
        xKey="label"
        series={[
          { key: "before", label: "Baseline", slot: 0 },
          { key: "after", label: "What-If", slot: 3 },
        ]}
        units={{ before: currency, after: currency }}
        height={240}
      />
    </div>
  );
}

/** The composer. Always present, never replaced by the buttons beside it. */
export function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  placeholder = "Describe a change — or ask about the book.",
  suggestions = [],
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  placeholder?: string;
  suggestions?: string[];
}) {
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={2}
          placeholder={placeholder}
          data-testid="whatif-composer"
          className="min-h-[52px] flex-1 resize-y rounded-md border border-border bg-surface px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <Button onClick={onSubmit} disabled={busy || !value.trim()} className="self-end">
          {busy ? "Working…" : "Send"}
        </Button>
      </div>
      {suggestions.length ? (
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange(s)}
              className="rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-text-primary"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** A period picker that offers the periods the book actually publishes. */
export function PeriodPicker({
  periods,
  value,
  onChange,
}: {
  periods: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Field label="Reporting period">
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid="period-picker"
      >
        {periods.map((period) => (
          <option key={period} value={period}>
            {period}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export { Input };
