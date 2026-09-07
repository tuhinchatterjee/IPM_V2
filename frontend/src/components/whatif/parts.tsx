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
  WhatIfAttribution,
  WhatIfContext,
  WhatIfDistribution,
  WhatIfInterpretation,
  WhatIfInvestigation,
  WhatIfParameterGroup,
  WhatIfParameterProfile,
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
        {/* Both rule sets, on the result, because a reader has to know which
            one staged the baseline column and which staged the What-If one. */}
        <span className="text-text-muted" data-testid="result-reported-staging">
          Reported book staged {context.reported_staging_version ?? context.staging_version}
        </span>
        <span className="text-text-muted" data-testid="result-whatif-staging">
          What-If staged {context.whatif_staging_version ?? context.staging_version}
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

/**
 * Which driver moved the provision.
 *
 * The split is an exact Shapley value, so the effects sum to the movement and
 * a driver that did not move gets exactly zero. The reconciliation is shown
 * rather than asserted: a table that claims to add up should be checkable
 * without a calculator.
 */
export function DriverAttribution({
  attribution,
  currency = "SAR",
}: {
  attribution: WhatIfAttribution;
  currency?: string;
}) {
  if (!attribution.available) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-[14px]">What moved the provision</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-[12px] text-text-secondary">{attribution.why}</p>
        </CardContent>
      </Card>
    );
  }
  const drivers = attribution.drivers ?? [];
  if (!drivers.length) return null;
  const model = attribution.model_adjustment;
  const check = attribution.reconciliation;
  return (
    <Card data-testid="whatif-attribution">
      <CardHeader>
        <CardTitle className="text-[14px]">What moved the provision</CardTitle>
        <p className="mt-0.5 text-[11px] text-text-muted">
          {attribution.method} · v{attribution.version}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Driver</TableHead>
                <TableHead numeric>Effect on ECL</TableHead>
                <TableHead numeric>Share</TableHead>
                <TableHead numeric>Borrowers moved</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {drivers.map((driver) => (
                <TableRow key={driver.key} data-driver={driver.key}>
                  <TableCell className="font-medium">{driver.label}</TableCell>
                  <TableCell numeric>{money(driver.effect, currency)}</TableCell>
                  <TableCell numeric>{signed(driver.share_pct)}</TableCell>
                  <TableCell numeric>{count(driver.borrowers_moved)}</TableCell>
                </TableRow>
              ))}
              {model ? (
                <TableRow data-driver="model">
                  <TableCell className="font-medium text-text-secondary">
                    {model.label}
                  </TableCell>
                  <TableCell numeric>{money(model.effect, currency)}</TableCell>
                  <TableCell numeric>—</TableCell>
                  <TableCell numeric>—</TableCell>
                </TableRow>
              ) : null}
              <TableRow>
                <TableCell className="font-medium">Total movement</TableCell>
                <TableCell numeric className="font-medium">
                  {money(attribution.total, currency)}
                </TableCell>
                <TableCell numeric>—</TableCell>
                <TableCell numeric>—</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        {model ? (
          <p className="text-[11px] text-text-muted">{model.note}</p>
        ) : null}
        {check ? (
          <p className="text-[11px] text-text-muted" data-testid="attribution-check">
            {check.reconciles
              ? `Reconciles: the drivers add to ${money(check.attributed, currency)} and the movement is ${money(check.reported_movement, currency)}.`
              : `Does not reconcile — ${money(check.difference, currency)} unexplained.`}
          </p>
        ) : null}
        <p className="text-[11px] text-text-muted">{attribution.note}</p>
        {attribution.unmoved?.length ? (
          <p className="text-[11px] text-text-muted">
            Unmoved by this scenario, and therefore exactly zero:{" "}
            {attribution.unmoved.join(", ")}.
          </p>
        ) : null}
      </CardContent>
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

/* ------------------------------------------------------- reading a result */

/**
 * What the result MEANS, beside what it says.
 *
 * A committee does not adjourn on "ECL is up 38%". Somebody has to say
 * whether that is large, what caused most of it, and what to look at next —
 * and if the screen will not, the person reading it invents an answer. Every
 * sentence here is composed from the figures above it; none is a view the
 * numbers do not carry.
 */
export function ResultInterpretation({
  interpretation,
  onAsk,
}: {
  interpretation: WhatIfInterpretation;
  onAsk?: (question: string) => void;
}) {
  const tone =
    interpretation.materiality === "extreme" || interpretation.materiality === "severe"
      ? "negative"
      : interpretation.materiality === "immaterial"
        ? "muted"
        : "accent";
  return (
    <div className="rounded-md border border-border bg-surface-sunken p-4">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="text-[13px] font-semibold text-text-primary">What this means</h4>
        <Badge variant={tone === "negative" ? "negative" : tone === "muted" ? "outline" : "accent"}>
          {interpretation.materiality}
        </Badge>
      </div>
      <ul className="space-y-1.5">
        {interpretation.findings.map((finding, i) => (
          <li key={i} className="text-[12px] leading-relaxed text-text-secondary">
            {finding}
          </li>
        ))}
      </ul>
      {interpretation.next_questions.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {interpretation.next_questions.map((question) => (
            <Button
              key={question}
              variant="outline"
              size="sm"
              data-followup={question}
              onClick={() => onAsk?.(question)}
              disabled={!onAsk}
            >
              {question}
            </Button>
          ))}
        </div>
      ) : null}
      <p className="mt-3 text-[11px] text-text-muted">{interpretation.statement}</p>
    </div>
  );
}

function Movement({ value, currency }: { value: number | undefined; currency: string }) {
  if (value === undefined || value === null) return <>—</>;
  return (
    <span className={value > 0 ? "text-negative" : value < 0 ? "text-positive" : undefined}>
      {value > 0 ? "+" : ""}
      {money(value, currency)}
    </span>
  );
}

/**
 * The answer to a question about a result.
 *
 * Not a re-run and not a restatement: every figure here was computed from the
 * borrower rows the scenario already produced, which is why asking "why did
 * Stage 3 move?" cannot change what Stage 3 did.
 */
export function InvestigationAnswer({
  answer,
  currency = "SAR",
}: {
  answer: WhatIfInvestigation;
  currency?: string;
}) {
  const unit = answer.headline?.currency ?? currency;
  return (
    <div className="space-y-3 rounded-md border border-border p-4" data-answer={answer.intent}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">
          {answer.intent === "view" ? "Breakdown" : "Explanation"}
        </Badge>
        <span className="text-[11px] text-text-muted">
          Answered from the result already computed — the scenario is unchanged.
        </span>
      </div>

      {answer.explanation ? (
        <p className="text-[12px] leading-relaxed text-text-secondary">{answer.explanation}</p>
      ) : null}

      {answer.stage_3 && answer.stage_3.available ? (
        <div>
          <p className="text-[12px] text-text-secondary">
            {count(answer.stage_3.borrowers_before)} borrowers in Stage 3 before,{" "}
            {count(answer.stage_3.borrowers_after)} after.
          </p>
          {answer.stage_3.drivers?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mechanism</TableHead>
                  <TableHead numeric>Borrowers</TableHead>
                  <TableHead numeric>Exposure</TableHead>
                  <TableHead numeric>Effect on ECL</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {answer.stage_3.drivers.map((driver) => (
                  <TableRow key={driver.driver} data-row={driver.driver}>
                    <TableCell>{driver.driver}</TableCell>
                    <TableCell numeric>{count(driver.borrowers)}</TableCell>
                    <TableCell numeric>{money(driver.exposure, unit)}</TableCell>
                    <TableCell numeric>
                      <Movement value={driver.effect} currency={unit} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
        </div>
      ) : null}

      {answer.drivers?.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Driver</TableHead>
              <TableHead numeric>Effect on ECL</TableHead>
              <TableHead numeric>Share of movement</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {answer.drivers.map((driver) => (
              <TableRow key={driver.key} data-row={driver.key}>
                <TableCell>{driver.label}</TableCell>
                <TableCell numeric>
                  <Movement value={driver.effect} currency={unit} />
                </TableCell>
                <TableCell numeric>{pct(driver.share_pct)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}

      {answer.breakdown?.available && answer.breakdown.rows?.length ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{answer.breakdown.dimension ?? "Group"}</TableHead>
                <TableHead numeric>Borrowers</TableHead>
                <TableHead numeric>Exposure</TableHead>
                <TableHead numeric>ECL before</TableHead>
                <TableHead numeric>ECL after</TableHead>
                <TableHead numeric>Change</TableHead>
                <TableHead numeric>Share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {answer.breakdown.rows.map((row, i) => (
                <TableRow key={i} data-row={String(row.label)}>
                  <TableCell>{String(row.label)}</TableCell>
                  <TableCell numeric>{count(Number(row.borrowers))}</TableCell>
                  <TableCell numeric>{money(Number(row.exposure), unit)}</TableCell>
                  <TableCell numeric>{money(Number(row.ecl_before), unit)}</TableCell>
                  <TableCell numeric>{money(Number(row.ecl_after), unit)}</TableCell>
                  <TableCell numeric>
                    <Movement value={Number(row.change)} currency={unit} />
                  </TableCell>
                  <TableCell numeric>{pct(Number(row.share_pct))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      {answer.contributors?.available && answer.contributors.rows?.length ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Borrower</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead>Rating</TableHead>
                <TableHead numeric>Exposure</TableHead>
                <TableHead numeric>ECL before</TableHead>
                <TableHead numeric>ECL after</TableHead>
                <TableHead numeric>Change</TableHead>
                <TableHead numeric>Share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {answer.contributors.rows.map((row, i) => (
                <TableRow key={i} data-borrower={String(row.borrower_id)}>
                  <TableCell>{String(row.display_name ?? row.borrower_id)}</TableCell>
                  <TableCell>{String(row.sector ?? "—")}</TableCell>
                  <TableCell>
                    {String(row.opening_rating ?? "—")}
                    {row.stressed_rating && row.stressed_rating !== row.opening_rating
                      ? ` → ${String(row.stressed_rating)}`
                      : ""}
                  </TableCell>
                  <TableCell numeric>{money(Number(row.ead), unit)}</TableCell>
                  <TableCell numeric>{money(Number(row.ecl_baseline), unit)}</TableCell>
                  <TableCell numeric>{money(Number(row.ecl_stressed), unit)}</TableCell>
                  <TableCell numeric>
                    <Movement value={Number(row.ecl_increase)} currency={unit} />
                  </TableCell>
                  <TableCell numeric>{pct(Number(row.share_pct))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-1 text-[11px] text-text-muted">
            {count(answer.contributors.shown)} of {count(answer.contributors.of)} borrowers.
          </p>
        </div>
      ) : null}

      {answer.pd_versus_ecl?.available ? (
        <p className="text-[12px] text-text-secondary">
          Exposure-weighted 12-month PD moved from {pct(answer.pd_versus_ecl.pd_before, 3)} to{" "}
          {pct(answer.pd_versus_ecl.pd_after, 3)} ({pct(answer.pd_versus_ecl.pd_change_pct)}),
          while the provision moved {pct(answer.pd_versus_ecl.ecl_change_pct)}. The two differ
          because the provision is a product and a stage crossing changes which PD is in it.
        </p>
      ) : null}

      {answer.notes?.length ? (
        <p className="text-[11px] text-text-muted">{answer.notes.join(" ")}</p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------- risk parameter screens */

/** One distribution, as the six numbers a risk person actually asks for. */
function Spread({
  distribution,
  unit = "%",
  digits = 2,
}: {
  distribution: WhatIfDistribution | undefined;
  unit?: string;
  digits?: number;
}) {
  if (!distribution || !distribution.count) {
    return <p className="text-[12px] text-text-secondary">No values to describe.</p>;
  }
  const show = (value: number | null | undefined) =>
    value === null || value === undefined ? "—" : `${value.toFixed(digits)}${unit}`;
  const cells: { label: string; value: string; strong?: boolean }[] = [
    { label: "Exposure-weighted", value: show(distribution.exposure_weighted_mean), strong: true },
    { label: "Mean", value: show(distribution.mean) },
    { label: "Median", value: show(distribution.median) },
    { label: "10th pct", value: show(distribution.p10) },
    { label: "90th pct", value: show(distribution.p90) },
    { label: "Range", value: `${show(distribution.min)} – ${show(distribution.max)}` },
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
      {cells.map((cell) => (
        <div key={cell.label}>
          <dt className="text-[11px] uppercase tracking-wide text-text-tertiary">
            {cell.label}
          </dt>
          <dd
            className={cn(
              "tabular-nums text-[13px]",
              cell.strong ? "font-semibold text-text-primary" : "text-text-secondary",
            )}
          >
            {cell.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A grouped parameter table: who holds it, how much, and at what level. */
function GroupTable({
  rows,
  first,
  currency = "SAR",
  unit = "%",
  digits = 2,
  limit = 20,
}: {
  rows: WhatIfParameterGroup[] | undefined;
  first: string;
  currency?: string;
  unit?: string;
  digits?: number;
  limit?: number;
}) {
  if (!rows || rows.length === 0) return null;
  const show = (value: number | null | undefined) =>
    value === null || value === undefined ? "—" : `${value.toFixed(digits)}${unit}`;
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{first}</TableHead>
            <TableHead numeric>Accounts</TableHead>
            <TableHead numeric>Exposure</TableHead>
            <TableHead numeric>Exposure-weighted</TableHead>
            <TableHead numeric>Mean</TableHead>
            <TableHead numeric>Median</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, limit).map((row) => (
            <TableRow key={row.label} data-row={row.label}>
              <TableCell>{row.label}</TableCell>
              <TableCell numeric>{count(row.count)}</TableCell>
              <TableCell numeric>{money(row.exposure, currency)}</TableCell>
              <TableCell numeric>{show(row.weighted_mean)}</TableCell>
              <TableCell numeric>{show(row.mean)}</TableCell>
              <TableCell numeric>{show(row.median)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * PD, LGD or CCF for the reported book — read, never dumped.
 *
 * This screen showed the API response as pretty-printed JSON. Everything a
 * credit officer needed was in it and none of it was legible: a person cannot
 * see a distribution in a brace, and a screen that asks them to read one is
 * telling them the product has not finished. The payload has not changed;
 * what it says has.
 *
 * Each parameter gets the shape its own mechanics have. PD is reported per
 * Stage because the Stage decides which PD is measured. LGD is reported
 * secured against unsecured because that is the only thing that moves it.
 * CCF is reported at facility grain with the EAD identity stated, because a
 * CCF change moves exposure and only then moves the provision.
 */
export function RiskParameterPanel({
  profile,
  currency = "SAR",
}: {
  profile: WhatIfParameterProfile;
  currency?: string;
}) {
  const parameter = String(profile.parameter ?? "").toUpperCase();
  const isCcf = parameter === "CCF";
  const unit = isCcf ? "" : "%";
  const digits = isCcf ? 4 : parameter === "PD" ? 3 : 2;
  const scale = (rows: WhatIfParameterGroup[] | undefined) => rows;

  if (parameter === "PD" && profile.blocks) {
    const blocks = [profile.blocks.stage_1, profile.blocks.stage_2,
                    profile.blocks.stage_3].filter(Boolean);
    return (
      <div className="space-y-5">
        <p className="text-[12px] text-text-secondary">
          Probability of default is reported per Stage, because the Stage
          decides which one is measured: Stage 1 on the twelve-month figure,
          Stages 2 and 3 on the lifetime figure. The two are never averaged
          together.
        </p>
        {blocks.map((block) => (
          <div key={block!.stage} className="rounded-md border border-border p-4">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="text-[13px] font-semibold text-text-primary">
                Stage {block!.stage} — measured on {block!.measured_on}
              </h4>
              <span className="text-[12px] text-text-secondary">
                {count(block!.borrowers)} borrowers · {money(block!.exposure, currency)}{" "}
                exposure · {money(block!.ecl, currency)} ECL
              </span>
            </div>
            <Spread distribution={block!.distribution} unit="%" digits={3} />
            {block!.treatment ? (
              <p className="mt-3 text-[12px] text-text-secondary">{block!.treatment}</p>
            ) : null}
            {block!.by_rating && block!.by_rating.length ? (
              <div className="mt-4 space-y-4">
                <div>
                  <h5 className="mb-1 text-[12px] font-medium text-text-primary">
                    By rating
                  </h5>
                  <GroupTable rows={block!.by_rating} first="Rating"
                              currency={currency} unit="%" digits={3} />
                </div>
                <div>
                  <h5 className="mb-1 text-[12px] font-medium text-text-primary">
                    By sector
                  </h5>
                  <GroupTable rows={block!.by_sector} first="Sector"
                              currency={currency} unit="%" digits={3} />
                </div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {profile.note ? (
        <p className="text-[12px] text-text-secondary">{profile.note}</p>
      ) : null}

      <div className="rounded-md border border-border p-4">
        <h4 className="mb-3 text-[13px] font-semibold text-text-primary">
          {isCcf ? "Across every facility" : "Across the book"}
        </h4>
        <Spread distribution={profile.distribution} unit={unit} digits={digits} />
      </div>

      {isCcf ? (
        <div className="rounded-md border border-border p-4">
          <h4 className="mb-3 text-[13px] font-semibold text-text-primary">
            Exposure at default = drawn + CCF × undrawn
          </h4>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            {[
              { label: "Drawn", value: money(profile.drawn_exposure, currency) },
              { label: "Undrawn", value: money(profile.undrawn_commitment, currency) },
              { label: "Exposure at default", value: money(profile.ead, currency) },
              { label: "Facilities", value: count(profile.facility_count) },
            ].map((cell) => (
              <div key={cell.label}>
                <dt className="text-[11px] uppercase tracking-wide text-text-tertiary">
                  {cell.label}
                </dt>
                <dd className="tabular-nums text-[13px] text-text-primary">{cell.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {profile.secured && profile.unsecured ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            { title: "Secured", body: profile.secured },
            { title: "Unsecured", body: profile.unsecured },
          ].map((side) => (
            <div key={side.title} className="rounded-md border border-border p-4">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <h4 className="text-[13px] font-semibold text-text-primary">
                  {side.title}
                </h4>
                <span className="text-[12px] text-text-secondary">
                  {count(side.body.borrowers)} borrowers ·{" "}
                  {money(side.body.exposure, currency)}
                </span>
              </div>
              <Spread distribution={side.body.distribution} unit="%" digits={2} />
            </div>
          ))}
        </div>
      ) : null}

      {profile.collateral_types && profile.collateral_types.length ? (
        <div className="rounded-md border border-border p-4">
          <h4 className="mb-2 text-[13px] font-semibold text-text-primary">
            Collateral behind the secured book
          </h4>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead numeric>Items</TableHead>
                  <TableHead numeric>Borrowers</TableHead>
                  <TableHead numeric>Market value</TableHead>
                  <TableHead numeric>Haircut</TableHead>
                  <TableHead numeric>Eligible value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {profile.collateral_types.map((row) => (
                  <TableRow key={row.collateral_type} data-row={row.collateral_type}>
                    <TableCell>{row.collateral_type}</TableCell>
                    <TableCell numeric>{count(row.items)}</TableCell>
                    <TableCell numeric>{count(row.borrowers)}</TableCell>
                    <TableCell numeric>{money(row.gross_value, currency)}</TableCell>
                    <TableCell numeric>{pct(row.haircut_pct * 100, 1)}</TableCell>
                    <TableCell numeric>{money(row.post_haircut_value, currency)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      ) : null}

      {profile.by_product && profile.by_product.length ? (
        <div>
          <h4 className="mb-1 text-[13px] font-semibold text-text-primary">By product</h4>
          <GroupTable rows={profile.by_product} first="Product" currency={currency}
                      unit={unit} digits={digits} />
        </div>
      ) : null}

      {profile.by_stage && profile.by_stage.length ? (
        <div>
          <h4 className="mb-1 text-[13px] font-semibold text-text-primary">By stage</h4>
          <GroupTable rows={scale(profile.by_stage)} first="Stage" currency={currency}
                      unit={unit} digits={digits} />
        </div>
      ) : null}

      {profile.by_sector && profile.by_sector.length ? (
        <div>
          <h4 className="mb-1 text-[13px] font-semibold text-text-primary">By sector</h4>
          <GroupTable rows={scale(profile.by_sector)} first="Sector" currency={currency}
                      unit={unit} digits={digits} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * A migration matrix with its Total row and column — 20 x 20 for the nineteen
 * governed grades, 4 x 4 for the three Stages.
 *
 * Percentages are ROW shares: each cell is read as "this proportion of the
 * borrowers who started the period on THIS grade ended it on that one", so a
 * row sums to 100%. Shares of the grand total were what the matrix showed
 * first, and they answered a question nobody asks — every cell was a fraction
 * of the whole book, so the diagonal read as tiny and a migration nobody would
 * miss looked like rounding.
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
