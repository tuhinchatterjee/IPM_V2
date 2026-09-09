"use client";

/**
 * The macro variables, and the three things a person may do with one.
 *
 * A card here is not a read-only tile. Every macro variable carries a declared
 * CreditProbe sensitivity — an assumption somebody set, not a coefficient
 * anybody measured — and the honest version of that screen has to let a reader
 * do three things with it: use it, check it against what this installation's
 * history actually shows, or replace it with their own.
 *
 * The three are never allowed to look alike. A reference sensitivity, an
 * estimate from sixteen quarters, and something a user typed are different
 * kinds of claim, and every one of them is labelled by source wherever the
 * number appears. A user-defined sensitivity is never called required,
 * regulatory, approved or empirical.
 *
 * Nothing here edits the governed matrix. An override is in force FOR THE
 * THREAD, and the screen says so on the same line as the number.
 */

import * as React from "react";

import { TrendChart } from "@/components/analytics/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import type {
  WhatIfMacro,
  WhatIfMacroAnalysis,
  WhatIfMacroVariable,
  WhatIfSensitivity,
  WhatIfState,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { readWhatIfError } from "@/lib/whatif-errors";

/** The badge tone for each kind of claim. They must not read alike. */
function sourceTone(source: string): "accent" | "outline" | "negative" {
  if (source === "reference") return "accent";
  if (source === "empirical") return "outline";
  return "negative";
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function signed(value: number, digits = 2): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/**
 * One variable's card. Shows the level, the declared sensitivity, and the
 * three things that can be done about it.
 */
function VariableCard({
  variable,
  override,
  active,
  onOpen,
}: {
  variable: WhatIfMacroVariable;
  override?: WhatIfSensitivity;
  active: boolean;
  onOpen: () => void;
}) {
  const observed = variable.has_observed_level;
  return (
    <button
      type="button"
      data-macro={variable.key}
      data-macro-open={active ? "true" : "false"}
      onClick={onOpen}
      className={cn(
        "rounded-md border p-3 text-left transition-colors",
        "hover:border-border-strong focus:outline-none focus-visible:ring-2",
        "focus-visible:ring-accent",
        active ? "border-accent bg-surface" : "border-border bg-surface",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[12px] font-medium text-text-primary">
          {variable.name}
        </span>
        {override ? (
          <Badge variant={sourceTone(override.source)} data-macro-overridden>
            {override.source_label}
          </Badge>
        ) : null}
      </div>
      <div className="mt-1 text-[11px] text-text-muted">
        {observed
          ? `Latest ${num(variable.observed_level)} ${variable.unit}`
          : "No observed level in this installation"}
      </div>
      <div className="mt-2 flex gap-3 text-[11px]">
        <span className="text-text-secondary">
          PD ×{override ? num(override.pd_response, 3) : variable.pd_multiplier}
        </span>
        <span className="text-text-secondary">
          LGD +{override ? num(override.lgd_response, 2) : variable.lgd_change_pp}pp
        </span>
      </div>
      <div className="mt-0.5 text-[10px] text-text-muted">
        {variable.adverse_label}
        {variable.history.length
          ? ` · ${variable.history.length} quarters observed`
          : " · no observed series"}
      </div>
    </button>
  );
}

/**
 * What the history shows, beside what the matrix assumes.
 *
 * The estimate is never presented as the better number. Fifteen quarterly
 * changes tell you whether the relationship runs the way the assumption says
 * and roughly how hard; they are not a calibration, and the panel says so in
 * the same breath as it shows the slope.
 */
function Analysis({
  analysis,
  onChoose,
  busy,
}: {
  analysis: WhatIfMacroAnalysis;
  onChoose: (choice: string) => void;
  busy: boolean;
}) {
  const fit = analysis.fit;
  const series = fit.series.map((point) => ({
    period: point.period,
    macro: point.macro,
    pd: point.weighted_pd_pct,
  }));
  // Fixed slots: the variable is always drawn in the same colour as the book's
  // PD moves under it, whichever variable is open.
  const lines = [
    { key: "macro", label: `${fit.variable_name} (${fit.unit})`, slot: 0 },
    { key: "pd", label: "Exposure-weighted 12m PD %", slot: 1 },
  ];
  return (
    <div className="space-y-3" data-testid="whatif-macro-analysis">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label={`PD move per ${fit.unit === "percent" ? "adverse %" : "adverse unit"}`}
          value={`${signed(fit.slope_pct_per_unit)}%`}
        />
        <Figure label="Implied multiplier" value={num(fit.implied_pd_multiplier, 3)} />
        <Figure label="Configured" value={num(fit.configured_pd_multiplier, 3)} />
        <Figure label="R²" value={num(fit.r_squared, 3)} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={fit.direction_agrees ? "accent" : "negative"}>
          {fit.direction_agrees
            ? "Direction consistent with the configured sensitivity"
            : "Direction OPPOSITE to the configured sensitivity"}
        </Badge>
        <Badge variant="outline">{fit.strength}</Badge>
        <Badge variant="outline">{fit.points} quarterly changes</Badge>
      </div>
      <p className="text-[12px] leading-relaxed text-text-secondary">{fit.note}</p>
      {series.length ? (
        <TrendChart data={series} xKey="period" series={lines} height={220} />
      ) : null}
      <div className="rounded-md border border-border bg-surface-sunken p-3">
        <div className="text-[12px] font-medium text-text-primary">
          Recommended: {analysis.recommendation.recommends === "reference"
            ? "keep the configured sensitivity"
            : analysis.recommendation.recommends}
        </div>
        <p className="mt-1 text-[12px] leading-relaxed text-text-secondary">
          {analysis.recommendation.because}
        </p>
      </div>
      <p className="text-[11px] leading-relaxed text-warning" data-testid="whatif-macro-small-sample">
        {fit.small_sample}
      </p>
      <div className="flex flex-wrap gap-2">
        {analysis.choices.map((choice) => (
          <Button
            key={choice.choice}
            size="sm"
            variant={choice.choice === "reference" ? "default" : "outline"}
            data-macro-choice={choice.choice}
            disabled={busy || choice.available === false}
            onClick={() => onChoose(choice.choice)}
          >
            {choice.label}
          </Button>
        ))}
      </div>
      {analysis.choices.some((c) => c.available === false) ? (
        <p className="text-[11px] text-text-muted">
          The estimated relationship is not offered because there is not enough
          overlapping history to fit one.
        </p>
      ) : null}
      <p className="text-[11px] text-text-muted">
        Measured over {analysis.population}.
      </p>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-2">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="mt-0.5 text-[14px] font-medium text-text-primary">{value}</div>
    </div>
  );
}

/**
 * Defining your own relationship.
 *
 * Deliberately plain, and deliberately labelled. Whatever is typed here is a
 * user-defined assumption in force for this thread, and it is stamped that way
 * on every figure it produces.
 */
function OwnRelationship({
  variable,
  onDefine,
  busy,
}: {
  variable: WhatIfMacroVariable;
  onDefine: (body: Partial<WhatIfSensitivity>) => void;
  busy: boolean;
}) {
  const [pdKind, setPdKind] = React.useState<"multiplier" | "absolute_pp">("multiplier");
  const [pd, setPd] = React.useState(String(variable.pd_multiplier));
  const [lgd, setLgd] = React.useState(String(variable.lgd_change_pp));
  const [note, setNote] = React.useState("");
  const invalid = Number.isNaN(Number(pd)) || Number.isNaN(Number(lgd));
  return (
    <div className="space-y-3" data-testid="whatif-macro-own">
      <p className="text-[12px] leading-relaxed text-text-secondary">
        What do you assume one adverse unit ({variable.adverse_label}) of{" "}
        {variable.name} does? This is in force for this thread only. The
        CreditProbe reference sensitivity is not edited and still applies
        everywhere else.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="PD response">
          <Select
            value={pdKind}
            data-macro-pd-kind
            onChange={(e) =>
              setPdKind(e.target.value as "multiplier" | "absolute_pp")}
          >
            <option value="multiplier">Multiplied by</option>
            <option value="absolute_pp">Moved by, in points</option>
          </Select>
        </Field>
        <Field label={pdKind === "multiplier" ? "PD multiplier" : "PD change (pp)"}>
          <Input value={pd} data-macro-pd onChange={(e) => setPd(e.target.value)} />
        </Field>
        <Field label="LGD change (pp)">
          <Input value={lgd} data-macro-lgd onChange={(e) => setLgd(e.target.value)} />
        </Field>
      </div>
      <Field label="Why (optional, kept with the scenario)">
        <Input
          value={note}
          data-macro-note
          placeholder="e.g. our own downturn study puts it higher"
          onChange={(e) => setNote(e.target.value)}
        />
      </Field>
      <Button
        size="sm"
        data-macro-define
        disabled={busy || invalid}
        onClick={() =>
          onDefine({
            variable: variable.key,
            source: "user",
            name: variable.name,
            pd_response_kind: pdKind,
            pd_response: Number(pd),
            lgd_response_kind: "absolute_pp",
            lgd_response: Number(lgd),
            note: note || undefined,
          })}
      >
        Use this for this thread
      </Button>
      {invalid ? (
        <p className="text-[11px] text-negative">
          Both responses have to be numbers.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The macro lab: ten cards, and everything that opens off one.
 */
export function MacroLab({
  macro,
  state,
  onState,
}: {
  macro: WhatIfMacro;
  state: WhatIfState;
  onState?: (state: WhatIfState, message: string) => void;
}) {
  const [open, setOpen] = React.useState<string>("");
  const [tab, setTab] = React.useState<"analyse" | "own">("analyse");
  const [analysis, setAnalysis] = React.useState<WhatIfMacroAnalysis | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [inForce, setInForce] = React.useState<Record<string, WhatIfSensitivity>>({});

  const opened = macro.variables.find((v) => v.key === open);

  async function openVariable(key: string) {
    if (key === open) {
      setOpen("");
      return;
    }
    setOpen(key);
    setTab("analyse");
    setAnalysis(null);
    setError("");
    setBusy(true);
    try {
      setAnalysis(await api.whatIfMacroAnalyse(key, state));
    } catch (e) {
      setError(readWhatIfError(e).message);
    } finally {
      setBusy(false);
    }
  }

  async function put(sensitivity: Partial<WhatIfSensitivity>) {
    setBusy(true);
    setError("");
    try {
      const body = await api.whatIfMacroConfigure(sensitivity, state);
      setInForce((held) => ({ ...held, [body.sensitivity.variable]: body.sensitivity }));
      onState?.(body.state, body.message);
    } catch (e) {
      setError(readWhatIfError(e).message);
    } finally {
      setBusy(false);
    }
  }

  function choose(choice: string) {
    if (!analysis) return;
    if (choice === "user") {
      setTab("own");
      return;
    }
    if (choice === "reference") {
      // Keeping the configured sensitivity is not a change. Saying so beats
      // writing the reference back as though it were an override.
      setOpen("");
      onState?.(state, `The CreditProbe reference sensitivity stays in force for ${analysis.fit.variable_name}.`);
      return;
    }
    void put(analysis.estimated);
  }

  return (
    <Card data-testid="whatif-macro-lab">
      <CardHeader>
        <CardTitle className="text-[14px]">
          Macroeconomic variables — v{macro.version}
        </CardTitle>
        <p className="mt-0.5 text-[11px] text-text-muted">{macro.basis}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-text-muted">
          Select a variable to see what this installation&rsquo;s history shows
          for it, or to define your own relationship for this thread.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {macro.variables.map((variable) => (
            <VariableCard
              key={variable.key}
              variable={variable}
              override={inForce[variable.key]}
              active={variable.key === open}
              onOpen={() => void openVariable(variable.key)}
            />
          ))}
        </div>
        {opened ? (
          <div
            className="rounded-md border border-border-strong p-4"
            data-testid="whatif-macro-detail"
            data-macro-detail={opened.key}
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h4 className="text-[13px] font-semibold text-text-primary">
                  {opened.name}
                </h4>
                <p className="text-[11px] text-text-muted">{opened.note}</p>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={tab === "analyse" ? "default" : "outline"}
                  data-macro-tab="analyse"
                  onClick={() => setTab("analyse")}
                >
                  What the history shows
                </Button>
                <Button
                  size="sm"
                  variant={tab === "own" ? "default" : "outline"}
                  data-macro-tab="own"
                  onClick={() => setTab("own")}
                >
                  Define my own
                </Button>
              </div>
            </div>
            {inForce[opened.key] ? (
              <p
                className="mb-3 text-[12px] text-text-secondary"
                data-testid="whatif-macro-in-force"
              >
                In force for this thread:{" "}
                {inForce[opened.key].description}. The CreditProbe reference
                sensitivity is unchanged.
              </p>
            ) : null}
            {error ? (
              <p className="mb-3 text-[12px] text-negative" role="alert">
                {error}
              </p>
            ) : null}
            {tab === "own" ? (
              <OwnRelationship variable={opened} onDefine={put} busy={busy} />
            ) : busy && !analysis ? (
              <p className="text-[12px] text-text-muted">
                Measuring {opened.name} against the book…
              </p>
            ) : analysis && analysis.fit.variable === opened.key ? (
              <Analysis analysis={analysis} onChoose={choose} busy={busy} />
            ) : (
              <p className="text-[12px] text-text-muted">
                No measurement is available for {opened.name}.
              </p>
            )}
          </div>
        ) : null}
        <p className="text-[11px] text-warning">{macro.limitation}</p>
      </CardContent>
    </Card>
  );
}
