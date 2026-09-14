"use client";

/**
 * The pieces every level of the Early Warning Score workspace is built from.
 *
 * Kept together so a KPI tile, a severity badge and a layer chip look the
 * same at portfolio, product, sub-product and customer level — which is what
 * lets a reader carry one visual vocabulary all the way down the hierarchy
 * without re-learning it at each step.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { FlaskConical, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type {
  EwsCounts, EwsInterpretation, EwsMateriality, EwsMaterialityShare,
  EwsReason, EwsTrendPoint,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import { Spark } from "./spark";

/** The four layers, in the order the model declares them. */
export const LAYERS: { key: string; name: string; short: string }[] = [
  { key: "behavioural", name: "Behavioural Intelligence", short: "Behavioural" },
  { key: "affordability", name: "Affordability & Cash Flow Intelligence",
    short: "Affordability" },
  { key: "bureau", name: "Bureau & External Credit Intelligence",
    short: "Bureau" },
  { key: "facility", name: "Facility & Exposure Intelligence",
    short: "Facility" },
];

export function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1e9) return `SAR ${(n / 1e9).toFixed(2)}bn`;
  if (Math.abs(n) >= 1e6) return `SAR ${(n / 1e6).toFixed(1)}mn`;
  if (Math.abs(n) >= 1e3) return `SAR ${(n / 1e3).toFixed(0)}k`;
  return `SAR ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function count(value: number | null | undefined): string {
  return value == null ? "—" : Number(value).toLocaleString();
}

export function signed(value: number | null | undefined, places = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(places)}`;
}

export function bandTone(band: string): string {
  switch ((band || "").toUpperCase()) {
    case "CRITICAL":
      return "bg-negative-subtle text-negative border-negative/30";
    case "HIGH":
      return "bg-warning-subtle text-warning border-warning/30";
    case "MEDIUM":
      return "bg-accent-subtle text-accent border-accent/30";
    default:
      return "bg-surface-muted text-text-secondary border-border";
  }
}

export function Severity({ band, className }: {
  band: string; className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px]"
        + " font-semibold uppercase tracking-[0.08em]",
        bandTone(band), className)}
      data-testid={`ews-severity-${(band || "").toLowerCase()}`}
    >
      {band || "—"}
    </span>
  );
}

/** A layer's current score, as a chip that carries its own colour. */
export function LayerChip({ layer, value, testId }: {
  layer: { key: string; short: string }; value: number; testId?: string;
}) {
  const band = value >= 70 ? "CRITICAL" : value >= 45 ? "HIGH"
    : value >= 20 ? "MEDIUM" : "LOW";
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded border px-1.5"
                    + " py-0.5 text-[10px]", bandTone(band))}
      title={`${layer.short}: ${value.toFixed(1)}`}
      data-testid={testId}
    >
      {layer.short}
      <span className="tabular-nums font-semibold">{value.toFixed(0)}</span>
    </span>
  );
}

export function Kpi({
  label, value, sub, testId, tone, onClick, hint,
}: {
  label: string; value: React.ReactNode; sub?: React.ReactNode;
  testId?: string; tone?: "negative" | "warning" | "default";
  onClick?: () => void; hint?: string;
}) {
  const body = (
    <>
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
        {label}
      </p>
      <p className={cn(
        "mt-1 text-[22px] font-semibold leading-tight tabular-nums",
        tone === "negative" && "text-negative",
        tone === "warning" && "text-warning")}>
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[11px] text-text-muted">{sub}</p> : null}
      {onClick ? (
        <p className="mt-1 text-[10px] text-accent">{hint ?? "Open"}</p>
      ) : null}
    </>
  );
  if (!onClick) {
    return <Card className="p-3.5" data-testid={testId}>{body}</Card>;
  }
  return (
    <Card className="p-0" data-testid={testId}>
      <button type="button" onClick={onClick}
              className="w-full p-3.5 text-left transition-colors hover:bg-surface-muted/60">
        {body}
      </button>
    </Card>
  );
}

export function Figure({ label, value, tone }: {
  label: string; value: React.ReactNode;
  tone?: "negative" | "warning";
}) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[9px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
      </p>
      <p className={cn("text-[13px] font-medium tabular-nums",
                       tone === "negative" && "text-negative",
                       tone === "warning" && "text-warning")}>{value}</p>
    </div>
  );
}

/** The counts every product and sub-product card carries, laid out once. */
export function CountsRow({ counts }: { counts: EwsCounts }) {
  return (
    <div className="grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-5">
      <Figure label="Customers" value={count(counts.customers)} />
      <Figure label="Warned" value={count(counts.customers_warned)} />
      <Figure label="High or critical" value={count(counts.high_or_critical)}
              tone="warning" />
      <Figure label="Already bad" value={count(counts.current_bad)}
              tone="negative" />
      <Figure label="Forward risk" value={count(counts.forward_risk)}
              tone="warning" />
      <Figure label="Exposure" value={money(counts.exposure_sar)} />
      <Figure label="Exposure warned" value={money(counts.exposure_warned_sar)} />
      <Figure label="% exposure warned"
              value={`${counts.exposure_warned_pct.toFixed(1)}%`} />
      <Figure label="Default-entry rate"
              value={`${counts.odr_pct.toFixed(2)}%`} />
      <Figure label="30+ DPD"
              value={`${counts.dpd_30_plus_pct.toFixed(1)}%`} />
    </div>
  );
}

/**
 * The three six-month charts §7 asks for on every product and sub-product
 * card: the warned-customer count, the default-entry rate, and the score.
 */
export function CardTrends({ trend, testId }: {
  trend: EwsTrendPoint[]; testId?: string;
}) {
  return (
    <div className="grid grid-cols-3 gap-4" data-testid={testId}>
      <Spark label="Warned customers"
             points={trend.map((p) => ({ month: p.month,
                                         value: p.customers_warned }))}
             tone="warning" height={40} testId={`${testId}-warned`} />
      <Spark label="Default-entry rate" unit="%"
             points={trend.map((p) => ({ month: p.month, value: p.odr_pct }))}
             tone="negative" height={40} testId={`${testId}-odr`} />
      <Spark label="EWS score"
             points={trend.map((p) => ({ month: p.month, value: p.ews_score }))}
             tone="accent" height={40} testId={`${testId}-score`} />
    </div>
  );
}

/** The top five warning reasons, with what each did on the month. */
export function TopReasons({ reasons, onOpen, testId }: {
  reasons: EwsReason[];
  onOpen?: (reasonCode: string) => void;
  testId?: string;
}) {
  if (!reasons.length) {
    return <p className="text-xs text-text-muted">No trigger fired here.</p>;
  }
  return (
    <div className="space-y-1" data-testid={testId}>
      {reasons.map((reason) => {
        const body = (
          <>
            <span className="flex min-w-0 items-center gap-1.5">
              <Severity band={reason.severity} />
              <span className="truncate text-text-primary">{reason.name}</span>
              <span className="shrink-0 font-mono text-[10px] text-text-muted">
                {reason.reason_code}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2 tabular-nums">
              <span className="text-text-primary">
                {count(reason.customers)}
              </span>
              <span className="w-12 text-right text-text-muted">
                {money(reason.exposure_sar)}
              </span>
              <span className={cn(
                "w-10 text-right",
                reason.change > 0 ? "text-negative"
                  : reason.change < 0 ? "text-positive" : "text-text-muted")}>
                {reason.change > 0 ? "+" : ""}{reason.change}
              </span>
            </span>
          </>
        );
        const className = "flex w-full items-center justify-between gap-3"
          + " rounded px-1.5 py-1 text-[11px]";
        return onOpen ? (
          <button key={reason.key} type="button"
                  onClick={() => onOpen(reason.reason_code)}
                  data-testid={`ews-reason-${reason.reason_code}`}
                  className={cn(className, "transition-colors"
                                + " hover:bg-surface-muted")}>
            {body}
          </button>
        ) : (
          <div key={reason.key} className={className}
               data-testid={`ews-reason-${reason.reason_code}`}>
            {body}
          </div>
        );
      })}
      <p className="px-1.5 pt-0.5 text-[10px] text-text-muted">
        Customers · exposure · change on last month.
      </p>
    </div>
  );
}

/** The generated commentary, set apart so nobody mistakes it for a caption. */
export function Commentary({ text, testId }: {
  text: string; testId?: string;
}) {
  return (
    <p className="rounded-md border border-border bg-surface-muted/40 p-2.5
                  text-[12px] leading-relaxed text-text-secondary"
       data-testid={testId}>
      {text}
    </p>
  );
}

/** The chips saying what the screen is currently filtered to. */
export function ActiveFilters({ chips, testId }: {
  chips: { label: string; onClear?: () => void }[];
  testId?: string;
}) {
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={testId}>
      <span className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
        Showing
      </span>
      {chips.map((chip) => (
        chip.onClear ? (
          <button key={chip.label} type="button" onClick={chip.onClear}
                  className="rounded-full border border-accent bg-accent-subtle
                             px-2 py-0.5 text-[11px] text-accent">
            {chip.label} ✕
          </button>
        ) : (
          <span key={chip.label}
                className="rounded-full border border-border px-2 py-0.5
                           text-[11px] text-text-secondary">
            {chip.label}
          </span>
        )
      ))}
    </div>
  );
}

/**
 * What share of its parents a segment is, on all three counts.
 *
 * Customers, accounts and exposure together, because they answer different
 * questions: a sub-portfolio can be two per cent of the customers and a fifth
 * of the money, and a reader deciding where to spend a collections team's
 * week needs to see which one they are looking at.
 */
export function Materiality({ materiality, testId }: {
  materiality?: EwsMateriality;
  testId?: string;
}) {
  if (!materiality) return null;
  const rows: { key: string; label: string }[] = [
    { key: "classification", label: "of classification" },
    { key: "product", label: "of product" },
    { key: "retail", label: "of total Retail" },
  ];
  const present = rows.filter((row) =>
    (materiality as unknown as Record<string, unknown>)[row.key]);
  if (!present.length) return null;

  return (
    <div className="rounded-md border border-border bg-surface-muted/30 p-2.5"
         data-testid={testId}>
      <p className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
        Materiality
      </p>
      <table className="mt-1 w-full text-[11px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-[0.06em] text-text-muted">
            <th className="text-left font-medium">Share</th>
            <th className="text-right font-medium">Customers</th>
            <th className="text-right font-medium">Accounts</th>
            <th className="text-right font-medium">Exposure</th>
          </tr>
        </thead>
        <tbody>
          {present.map((row) => {
            const share = (materiality as unknown as
              Record<string, EwsMaterialityShare>)[row.key];
            return (
              <tr key={row.key} data-testid={testId ? `${testId}-${row.key}` : undefined}>
                <td className="py-0.5 text-text-secondary">{row.label}</td>
                <td className="py-0.5 text-right tabular-nums text-text-primary">
                  {share.customers_pct.toFixed(1)}%
                </td>
                <td className="py-0.5 text-right tabular-nums text-text-primary">
                  {share.accounts_pct.toFixed(1)}%
                </td>
                <td className="py-0.5 text-right font-medium tabular-nums text-text-primary">
                  {share.exposure_pct.toFixed(1)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-[10px] text-text-muted">
        {count(materiality.of.customers)} customers ·{" "}
        {count(materiality.of.accounts)} accounts ·{" "}
        {money(materiality.of.exposure_sar)}
      </p>
    </div>
  );
}

/**
 * The management reading of a level, and the framework behind its ranking.
 *
 * The paragraph is written by a deterministic reader from the same figures
 * the screen is showing, so it can be checked against them. "Why this
 * ranking?" opens the six governed criteria and each product's mark, because
 * a ranking a reader cannot interrogate is an opinion wearing a number.
 */
export function Interpretation({ reading, testId }: {
  reading?: EwsInterpretation | null;
  testId?: string;
}) {
  const [open, setOpen] = React.useState(false);
  if (!reading?.available) return null;

  return (
    <Card className="border-accent/30 bg-accent-subtle/20 p-4"
          data-testid={testId ?? "ews-interpretation"}>
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 shrink-0 text-accent" aria-hidden />
        <p className="text-sm font-semibold text-text-primary">
          AI Interpretation
        </p>
        <span className="text-[11px] text-text-muted">{reading.headline}</span>
        <button type="button" onClick={() => setOpen((was) => !was)}
                className="ml-auto rounded-full border border-border px-2.5 py-0.5
                           text-[11px] text-text-secondary
                           transition-colors hover:bg-surface-muted"
                data-testid="ews-interpretation-why">
          Why this ranking?
        </button>
      </div>

      <p className="mt-2 text-[13px] leading-relaxed text-text-primary"
         data-testid="ews-interpretation-text">
        {reading.interpretation}
      </p>

      {open ? (
        <div className="mt-3 space-y-2 border-t border-border pt-3"
             data-testid="ews-interpretation-basis">
          <p className="text-[11px] text-text-secondary">
            {reading.ranking_basis}
          </p>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.06em] text-text-muted">
                <th className="px-1 py-1 text-left font-medium">Criterion</th>
                <th className="px-1 py-1 text-right font-medium">Weight</th>
                {(reading.ranking ?? []).map((one) => (
                  <th key={one.product_code}
                      className="px-1 py-1 text-right font-medium">
                    {one.product_label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {reading.criteria.map((criterion) => (
                <tr key={criterion.key} className="border-t border-border/60">
                  <td className="px-1 py-1 text-text-secondary"
                      title={criterion.meaning}>
                    {criterion.name}
                  </td>
                  <td className="px-1 py-1 text-right tabular-nums text-text-muted">
                    {(criterion.weight * 100).toFixed(0)}%
                  </td>
                  {(reading.ranking ?? []).map((one) => (
                    <td key={one.product_code}
                        className="px-1 py-1 text-right tabular-nums text-text-primary">
                      {(one.marks[criterion.key] ?? 0).toFixed(2)}
                    </td>
                  ))}
                </tr>
              ))}
              {reading.ranking?.length ? (
                <tr className="border-t border-border font-semibold">
                  <td className="px-1 py-1 text-text-primary">Concern</td>
                  <td className="px-1 py-1" />
                  {reading.ranking.map((one) => (
                    <td key={one.product_code}
                        className="px-1 py-1 text-right tabular-nums text-text-primary">
                      {one.concern.toFixed(2)} ({one.rank})
                    </td>
                  ))}
                </tr>
              ) : null}
            </tbody>
          </table>
          <p className="text-[10px] text-text-muted">{reading.provenance}</p>
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Export this exact cohort to What-If Analysis.
 *
 * It does not navigate to a blank What-If screen: it writes a selection set
 * for the customers on this card, with the filters that produced them, and
 * opens the thread on that cohort. What the reader was looking at is what
 * gets stressed.
 */
export function ExportToWhatIf({ scope, label, testId, size = "sm" }: {
  scope: Record<string, unknown>;
  label?: string;
  testId?: string;
  size?: "sm" | "xs";
}) {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState("");

  const go = React.useCallback(async () => {
    setBusy(true);
    setProblem("");
    try {
      const made = await api.ewsExportToWhatIf({
        ...scope,
        route: typeof window === "undefined" ? "" :
          window.location.pathname + window.location.search,
      });
      router.push(`/early-warning/whatif/${made.selection_id}`);
    } catch (failed) {
      setProblem(String(failed));
      setBusy(false);
    }
  }, [router, scope]);

  return (
    <span className="inline-flex flex-col items-start">
      <Button variant="outline" size={size === "xs" ? "sm" : size}
              onClick={() => void go()} disabled={busy}
              data-testid={testId ?? "ews-export-whatif"}>
        {busy ? <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
              : <FlaskConical className="mr-1 size-3.5" aria-hidden />}
        {label ?? "Export to What-If Analysis"}
      </Button>
      {problem ? (
        <span className="mt-1 text-[10px] text-negative">{problem}</span>
      ) : null}
    </span>
  );
}
