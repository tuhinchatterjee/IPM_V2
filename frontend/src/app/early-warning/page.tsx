"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import {
  ChevronDown,
  FlaskConical,
  Radar,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import {
  api,
  type EarlyWarningScores,
  type FactorFamilyDef,
  type ScoredFacility,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import {
  facilityAnchor,
  fromBorrower,
  linkBack,
  useAnchorScroll,
} from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * Early Warning.
 *
 * Three questions, not one score. "Will this get worse" means something
 * different to the officer monitoring a performing book, the one worried about
 * a sudden default, and the one setting a provision — so the signal is fitted
 * three times and the screen makes you choose which question you are asking.
 *
 * Every number on this page is a PROTOTYPE result on synthetic data, and the
 * page says so above the fold rather than in a footnote. The words "validated",
 * "production model" and "regulatory model" are derived on the backend from a
 * validation record and cannot appear without one.
 *
 * The row expansion is the point of the whole module. A score nobody can take
 * apart is a score nobody should act on, so opening a facility shows every
 * factor, its value, how unusual that value is, and exactly how much of the
 * score it accounts for — and those contributions add up to the score.
 */
export default function EarlyWarningPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <EarlyWarning />
    </React.Suspense>
  );
}

/**
 * The opened borrower lives in the address.
 *
 * §5: "Early Warning → Borrower → Trace → Back to Borrower". A borrower here is
 * an expanded row rather than a page, so the only way a return link can name
 * one is for the selection to be part of the URL. Without it, "Back to Al Rajhi
 * Contracting" returns a reader to a hundred collapsed rows and leaves them to
 * find it again.
 */
function EarlyWarning() {
  const overview = useAsync(() => api.earlyWarning(), []);
  const query = useSearchParams();
  const [targetId, setTargetId] = React.useState<string | null>(null);

  const targets = overview.data?.targets ?? [];
  const active = targetId ?? targets[0]?.id ?? null;
  const target = targets.find((t) => t.id === active) ?? null;

  return (
    <div className="space-y-7">
      <PageHeader
        title="Early Warning"
        description="A forward-looking estimate of the chance that a facility moves to a worse IFRS 9 stage next quarter. Fitted separately for three transitions, because they have different drivers and different base rates."
        status="partial"
        phase="Prototype signal on synthetic data"
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning/lab">
              <FlaskConical aria-hidden />
              Model Lab
            </Link>
          </Button>
        }
      />

      {overview.data && <PrototypeNotice notice={overview.data.notice} />}

      {overview.loading && <Skeleton className="h-64 w-full" />}
      {overview.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {overview.error}
        </Card>
      )}

      {targets.length > 0 && (
        <>
          <Tabs
            active={active ?? ""}
            onChange={setTargetId}
            tabs={targets.map((t) => ({
              id: t.id,
              label: t.label,
              count: t.versions || undefined,
            }))}
          />

          {target && (
            <div className="space-y-6">
              <div className="max-w-3xl">
                <p className="text-sm leading-relaxed text-text-secondary">
                  {target.definition}
                </p>
                <p className="mt-1.5 text-xs text-text-muted">
                  {target.eligible_note} Horizon: {target.horizon}.
                </p>
              </div>

              {target.active ? (
                <TargetScores
                  targetId={target.id}
                  families={overview.data?.families ?? []}
                  modelName={target.active.display_name}
                  version={target.active.version}
                  opened={query.get("facility")}
                />
              ) : (
                <EmptyState
                  icon={Radar}
                  title="No model fitted for this transition yet"
                  description="An administrator can fit one in the Model Lab. Fitting takes a few seconds and holds the last three quarters back to test on."
                  action={
                    <Button size="sm" asChild>
                      <Link href="/early-warning/lab">Open the Model Lab</Link>
                    </Button>
                  }
                />
              )}

              <FactorArchitecture families={overview.data?.families ?? []} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ notice */

export function PrototypeNotice({ notice }: { notice: string }) {
  return (
    <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <p className="text-xs leading-relaxed text-warning">{notice}</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ scores */

function TargetScores({
  targetId,
  families,
  modelName,
  version,
  opened,
}: {
  targetId: string;
  families: FactorFamilyDef[];
  modelName: string;
  version: number;
  /** The facility a return link asked to be shown, if any. */
  opened: string | null;
}) {
  const scores = useAsync(
    () => api.earlyWarningScores(targetId, { limit: 100 }),
    [targetId],
  );
  // Land on the borrower a return link names, once the rows exist to land on.
  useAnchorScroll(Boolean(scores.data));

  if (scores.loading) return <Skeleton className="h-72 w-full" />;
  if (scores.error) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {scores.error}
      </Card>
    );
  }
  if (!scores.data) return null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
        <span className="font-medium text-text-secondary">{modelName}</span>
        <span>version {version}</span>
        <span>{scores.data.period}</span>
        <span>{scores.data.facilities.toLocaleString()} eligible facilities</span>
      </div>

      <BandSummary bands={scores.data.bands} total={scores.data.facilities} />
      <ScoreTable
        scores={scores.data}
        families={families}
        opened={opened}
      />
    </div>
  );
}

const BAND_CLASS: Record<string, string> = {
  Severe: "text-negative",
  High: "text-negative",
  Elevated: "text-warning",
  Moderate: "text-text-secondary",
  Low: "text-text-muted",
};

const BAND_ORDER = ["Severe", "High", "Elevated", "Moderate", "Low"];

function BandSummary({
  bands,
  total,
}: {
  bands: EarlyWarningScores["bands"];
  total: number;
}) {
  const ordered = BAND_ORDER.map((band) =>
    bands.find((b) => b.band === band),
  ).filter(Boolean) as EarlyWarningScores["bands"];

  return (
    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
      {ordered.map((band) => (
        <Card key={band.band} className="p-4">
          <p className={cn("text-[11px] font-medium", BAND_CLASS[band.band])}>
            {band.band}
          </p>
          <p className="mt-1 text-[20px] font-semibold tabular text-text-primary">
            {band.facilities.toLocaleString()}
          </p>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {total > 0 ? ((100 * band.facilities) / total).toFixed(1) : "0.0"}% ·{" "}
            {band.ead.toLocaleString(undefined, { maximumFractionDigits: 0 })} USD mn
          </p>
        </Card>
      ))}
    </div>
  );
}

function ScoreTable({
  scores,
  families,
  opened,
}: {
  scores: EarlyWarningScores;
  families: FactorFamilyDef[];
  /** The account a return link asked to be shown, if any. */
  opened: string | null;
}) {
  const [open, setOpen] = React.useState<string | null>(opened);

  // Opening a borrower rewrites the address without a navigation, so a link
  // taken from inside the expansion carries the borrower it came from.
  const choose = React.useCallback((accountId: string | null) => {
    setOpen(accountId);
    const url = new URL(window.location.href);
    if (accountId) url.searchParams.set("facility", accountId);
    else url.searchParams.delete("facility");
    window.history.replaceState(window.history.state, "", url);
  }, []);

  if (scores.scored.length === 0) {
    return (
      <EmptyState
        icon={Radar}
        title="Nothing eligible this period"
        description={scores.message ?? "No facility is in the starting stage for this transition."}
      />
    );
  }

  return (
    <Card className="divide-y divide-border">
      <div className="flex items-center gap-3 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        <span className="min-w-0 flex-1">Borrower</span>
        <span className="hidden w-32 shrink-0 sm:block">Sector</span>
        <span className="w-20 shrink-0 text-right">EAD</span>
        <span className="w-20 shrink-0 text-right">Signal</span>
        <span className="w-16 shrink-0 text-right">Band</span>
        <span className="w-4 shrink-0" />
      </div>

      {scores.scored.map((facility) => (
        <div
          key={facility.account_id}
          id={facilityAnchor(facility.account_id)}
          className="scroll-mt-24"
        >
          <button
            type="button"
            onClick={() =>
              choose(open === facility.account_id ? null : facility.account_id)
            }
            className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-text-primary">
                {facility.borrower_name}
              </span>
              <span className="block truncate text-[11px] text-text-muted">
                {facility.account_id}
              </span>
            </span>
            <span className="hidden w-32 shrink-0 truncate text-xs text-text-muted sm:block">
              {facility.sector}
            </span>
            <span className="w-20 shrink-0 text-right text-sm tabular text-text-secondary">
              {facility.ead.toFixed(1)}
            </span>
            <span className="w-20 shrink-0 text-right text-sm font-medium tabular text-text-primary">
              {facility.probability_pct.toFixed(1)}%
            </span>
            <span
              className={cn(
                "w-16 shrink-0 text-right text-xs font-medium",
                BAND_CLASS[facility.band],
              )}
            >
              {facility.band}
            </span>
            <ChevronDown
              className={cn(
                "size-3.5 shrink-0 text-text-muted transition-transform",
                open === facility.account_id && "rotate-180",
              )}
              aria-hidden
            />
          </button>

          {open === facility.account_id && (
            <Decomposition
              facility={facility}
              families={families}
              period={scores.period}
            />
          )}
        </div>
      ))}
    </Card>
  );
}

/**
 * Why this facility scored what it scored.
 *
 * The arithmetic is shown, not summarised: intercept plus every contribution
 * equals the score, and a reader with a calculator can check it. That is the
 * whole reason the model is additive.
 */
function Decomposition({
  facility,
  families,
  period,
}: {
  facility: ScoredFacility;
  families: FactorFamilyDef[];
  period: string;
}) {
  const largest = Math.max(
    ...facility.contributions.map((c) => Math.abs(c.contribution)),
    0.0001,
  );

  // §5 asks for Early Warning → Borrower → Trace → Back to Borrower. A signal
  // score is a fitted model rather than a governed engine run, so it has no
  // Trace of its own to open — what it has is a borrower worth investigating.
  // Asking opens an Investigation, which produces the certified analyses and
  // the Trace, and carries this exact row as its Back.
  const investigate = linkBack(
    `/?focus=ask&q=${encodeURIComponent(
      `What has changed for ${facility.borrower_name} over the last four quarters?`,
    )}`,
    fromBorrower(facility.account_id, facility.borrower_name),
  );

  return (
    <div className="space-y-5 border-t border-border bg-surface-sunken px-4 py-4">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-xs">
        <span className="text-text-muted">
          Starting point{" "}
          <span className="tabular text-text-secondary">
            {facility.intercept.toFixed(3)}
          </span>
        </span>
        <span className="text-text-muted">
          plus contributions{" "}
          <span className="tabular text-text-secondary">
            {facility.contributions
              .reduce((sum, c) => sum + c.contribution, 0)
              .toFixed(3)}
          </span>
        </span>
        <span className="font-medium text-text-primary">
          = score <span className="tabular">{facility.score.toFixed(3)}</span>
        </span>
        <span className="text-text-muted">
          → {facility.probability_pct.toFixed(2)}% over the next quarter
        </span>
        <span className="text-text-muted">{period}</span>
        <Button variant="ghost" size="sm" asChild className="ml-auto">
          <Link href={investigate}>
            <Sparkles aria-hidden />
            Investigate this borrower
          </Link>
        </Button>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          By family
        </p>
        <div className="flex flex-wrap gap-x-5 gap-y-1.5">
          {facility.family_contributions.map((family) => (
            <span key={family.family} className="text-xs">
              <span className="text-text-muted">{family.label} </span>
              <span
                className={cn(
                  "tabular font-medium",
                  family.contribution > 0.001
                    ? "text-negative"
                    : family.contribution < -0.001
                      ? "text-positive"
                      : "text-text-muted",
                )}
              >
                {family.contribution > 0 ? "+" : ""}
                {family.contribution.toFixed(3)}
              </span>
            </span>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Factor by factor
          <InfoPopover title="Reading this">
            <p>
              Every row is one factor: its value for this facility, how unusual
              that value is against the fitting population, and how much of the
              score it accounts for.
            </p>
            <p>
              The contributions add up to the score exactly. Nothing here is an
              approximation of the model&rsquo;s reasoning — it is the model.
            </p>
          </InfoPopover>
        </p>
        <div className="space-y-1">
          {facility.contributions.map((contribution) => (
            <div
              key={contribution.factor_id}
              className="flex items-center gap-3 text-xs"
            >
              <span className="w-44 shrink-0 truncate text-text-secondary">
                {contribution.label}
              </span>
              <span className="w-24 shrink-0 text-right tabular text-text-muted">
                {contribution.value.toFixed(2)}
                {contribution.unit ? ` ${contribution.unit}` : ""}
              </span>
              <span className="hidden w-16 shrink-0 text-right tabular text-text-muted sm:block">
                {contribution.standardised > 0 ? "+" : ""}
                {contribution.standardised.toFixed(2)}σ
              </span>
              <span className="relative h-3 min-w-0 flex-1">
                <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <span
                  className={cn(
                    "absolute inset-y-0.5 rounded-sm",
                    contribution.contribution >= 0 ? "bg-negative/50" : "bg-positive/50",
                  )}
                  style={
                    contribution.contribution >= 0
                      ? {
                          left: "50%",
                          width: `${(50 * Math.abs(contribution.contribution)) / largest}%`,
                        }
                      : {
                          right: "50%",
                          width: `${(50 * Math.abs(contribution.contribution)) / largest}%`,
                        }
                  }
                />
              </span>
              <span
                className={cn(
                  "w-16 shrink-0 text-right tabular font-medium",
                  contribution.contribution > 0.001
                    ? "text-negative"
                    : contribution.contribution < -0.001
                      ? "text-positive"
                      : "text-text-muted",
                )}
              >
                {contribution.contribution > 0 ? "+" : ""}
                {contribution.contribution.toFixed(3)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-text-muted">
        {families.length} factor families.{" "}
        {facility.contributions.length} factors. A positive contribution pushes
        this facility towards migrating; a negative one holds it back.
      </p>
    </div>
  );
}

/* ------------------------------------------------------ factor architecture */

function FactorArchitecture({ families }: { families: FactorFamilyDef[] }) {
  if (families.length === 0) return null;

  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          What the signal is built from
        </h2>
        <InfoPopover title="Factor families">
          <p>
            Factors are grouped into families so a score can be discussed. Six
            families can be argued about in a credit committee; eighteen loose
            variables cannot.
          </p>
          <p>
            Each factor declares the direction a credit officer would expect. Any
            fitted weight that disagrees is flagged in the Model Lab rather than
            left to be discovered.
          </p>
        </InfoPopover>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {families.map((family) => (
          <Card key={family.id} className="p-4">
            <h3 className="text-sm font-semibold text-text-primary">
              {family.label}
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">
              {family.definition}
            </p>
            {family.factors && family.factors.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-border pt-2.5">
                {family.factors.map((factor) => (
                  <li key={factor.id} className="flex items-baseline gap-2 text-xs">
                    <span className="min-w-0 flex-1 truncate text-text-secondary">
                      {factor.label}
                    </span>
                    <Badge variant="outline">
                      {factor.direction === "up-is-worse" ? "↑ worse" : "↑ better"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </section>
  );
}
