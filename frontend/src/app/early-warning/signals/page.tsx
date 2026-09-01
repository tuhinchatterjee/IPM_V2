"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { ChevronDown, ListChecks, Radar } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import * as view from "@/components/early-warning/signal-view";
import {
  Landing,
  PriorityBadge,
} from "@/components/early-warning/landing";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { api, type SignalObservation, type SignalStanding } from "@/lib/api";
import { borrower360Href } from "@/lib/borrower-link";
import * as ewFormat from "@/lib/early-warning-format";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Early Warning Signals. §28, §29.
 *
 * A different screen from the fitted model next door, and deliberately so.
 * That one estimates a probability; this one lists named conditions with
 * thresholds somebody owns, and shows them as what they are: evidence, in
 * families, with a lifecycle.
 *
 * There is no score anywhere on this page and no column that could be sorted
 * into one. A borrower is not "0.72 risky" — it has six conditions across
 * four families, two of them worse than last quarter, one of them severe, and
 * every one of those is a number a credit officer can check against the book.
 * Ordering, grouping and wording all come from `signal-view`, which is tested
 * on its own, so a component cannot quietly disagree with the ranking the
 * backend published.
 *
 * The screen also shows what it could NOT test. A watchlist that silently
 * omits a family because a column was never loaded is worse than one that
 * says which family it is missing.
 */
export default function SignalsPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <Signals />
    </React.Suspense>
  );
}

const PAGE = 25;

function Signals() {
  const query = useSearchParams();
  const period = query.get("period") ?? "";
  const landing = useAsync(() => api.earlyWarningDashboard(), []);
  const book = useAsync(
    () => api.earlyWarningSignals({ period, limit: 200 }),
    [period],
  );
  const [lens, setLens] = React.useState<view.LensId>("all");
  const [shown, setShown] = React.useState(PAGE);
  const [opened, setOpened] = React.useState<string | null>(
    query.get("borrower"),
  );

  const all = React.useMemo(
    () => [...(book.data?.borrowers ?? [])].sort(view.byEvidence),
    [book.data],
  );
  const rows = React.useMemo(
    () => all.filter((s) => view.matches(s, lens)),
    [all, lens],
  );

  // Paging is derived, never stored: a lens change that left a stale page
  // count behind would show "showing 75 of 12" and lose a reader's trust in
  // every other number on the screen.
  const visible = rows.slice(0, shown);
  const headline = book.data?.headline;

  return (
    <div className="space-y-7">
      <PageHeader
        title="Early Warning Signals"
        description="The governed conditions this book is watched for, borrower by borrower. Not one score — a list of named tests, each with a threshold, an owner and a version, and each traceable to the field it read."
        status="partial"
        phase="Synthetic book"
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning">
              <Radar aria-hidden />
              Fitted signal
            </Link>
          </Button>
        }
      />

      {book.loading && <Skeleton className="h-64 w-full" />}
      {book.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {book.error}
        </Card>
      )}

      {/* R2 §10. The business measures come first, because they are what a
          credit officer arrives for; the signal counts that used to be here
          are inside the landing's own diagnostics section, collapsed. */}
      {landing.data ? <Landing book={landing.data} /> : null}

      {book.data && (
        <>
          <Headline
            period={book.data.period}
            previous={book.data.previous_period ?? ""}
            evaluated={book.data.evaluated}
            headline={headline}
          />

          <Tabs
            active={lens}
            onChange={(id) => {
              setLens(id as view.LensId);
              setShown(PAGE);
            }}
            tabs={view.LENSES.map((l) => ({
              id: l.id,
              label: l.label,
              count: all.filter((s) => view.matches(s, l.id)).length,
            }))}
          />
          <p className="-mt-3 text-xs text-text-muted">
            {view.LENSES.find((l) => l.id === lens)?.means}
          </p>

          {rows.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title="No borrower matches this view"
              description="Every borrower on the book was evaluated. None of them carries evidence of this kind at this reporting date."
            />
          ) : (
            <Card className="divide-y divide-border-subtle p-0">
              {visible.map((standing) => (
                <BorrowerRow
                  key={standing.borrower_id}
                  standing={standing}
                  period={book.data?.period ?? ""}
                  open={opened === standing.borrower_id}
                  onToggle={() =>
                    setOpened(
                      opened === standing.borrower_id
                        ? null
                        : standing.borrower_id,
                    )
                  }
                />
              ))}
            </Card>
          )}

          <div className="flex items-center justify-between text-xs text-text-muted">
            <span>
              Showing {Math.min(shown, rows.length)} of {rows.length} borrower
              {rows.length === 1 ? "" : "s"} in this view. All{" "}
              {book.data.evaluated} on the book were evaluated.
            </span>
            {shown < rows.length && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShown(shown + PAGE)}
              >
                Show {Math.min(PAGE, rows.length - shown)} more
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- headline */

/**
 * What a head of credit reads first: counts of SITUATIONS, not of signals.
 *
 * "New signals: 4,812" tells nobody anything. "Borrowers with a new
 * condition: 214" is a queue somebody can work.
 */
function Headline({
  period,
  previous,
  evaluated,
  headline,
}: {
  period: string;
  previous: string;
  evaluated: number;
  headline?: {
    with_a_new_signal: number;
    worsening: number;
    persisting: number;
    severe: number;
    multi_family: number;
    booked_stage_2_or_worse: number;
    means: Record<string, string>;
  };
}) {
  if (!headline) return null;
  const cells: { label: string; value: number; means?: string }[] = [
    {
      label: "With a new condition",
      value: headline.with_a_new_signal,
      means: headline.means?.with_a_new_signal,
    },
    { label: "Worsening", value: headline.worsening },
    { label: "Still firing", value: headline.persisting },
    { label: "Carrying a severe condition", value: headline.severe },
    {
      label: "Three or more families",
      value: headline.multi_family,
      means: headline.means?.multi_family,
    },
    {
      label: "Booked stage 2 or worse",
      value: headline.booked_stage_2_or_worse,
      means: headline.means?.booked_stage_2_or_worse,
    },
  ];
  return (
    <section className="space-y-2">
      <p className="text-xs text-text-muted">
        {evaluated.toLocaleString()} borrowers evaluated at {period}
        {previous ? `, against ${previous}` : ""}.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {cells.map((cell) => (
          <Card key={cell.label} className="p-3.5">
            <div className="flex items-start gap-1">
              <p className="text-xs text-text-muted">{cell.label}</p>
              {cell.means && <InfoPopover>{cell.means}</InfoPopover>}
            </div>
            <p className="mt-1 text-xl font-medium tabular-nums">
              {cell.value.toLocaleString()}
            </p>
          </Card>
        ))}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- one borrower */

function BorrowerRow({
  standing,
  period,
  open,
  onToggle,
}: {
  standing: SignalStanding;
  //: The quarter the signal fired in, carried into the Borrower 360 link so
  //: the officer lands on the period they were just reading. §4.
  period: string;
  open: boolean;
  onToggle: () => void;
}) {
  const moved = view.movement(standing);
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-hover"
      >
        <ChevronDown
          aria-hidden
          className={cn(
            "size-4 shrink-0 text-text-muted transition-transform",
            open && "rotate-180",
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {standing.borrower_id}
          </span>
          <span className="block truncate text-xs text-text-muted">
            {view.summary(standing)}
            {moved ? ` — ${moved}` : ""}
          </span>
        </span>
        {standing.exposure !== null && standing.exposure !== undefined ? (
          <span className="hidden shrink-0 text-xs tabular-nums text-text-muted sm:inline">
            {ewFormat.money(standing.exposure)}
          </span>
        ) : null}
        {/* R2 §25: what to DO about this borrower, beside how bad its worst
            individual condition is. They answer different questions. */}
        <PriorityBadge
          priority={standing.priority}
          label={standing.priority_label}
        />
        <SeverityBadge severity={standing.severity} />
      </button>

      {open && <BorrowerDetail standing={standing} period={period} />}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const weight = view.tone(severity);
  return (
    <Badge
      variant={weight === "danger" ? "negative" : weight === "warning" ? "warning" : "outline"}
    >
      {view.SEVERITY_LABEL[severity] ?? severity}
    </Badge>
  );
}

/**
 * §29 — one borrower, in full.
 *
 * Every condition that fired, grouped by family, with the value, the previous
 * value, the threshold it crossed and who owns that threshold. Then what
 * cured, then what could not be tested. A reader who disagrees with the
 * screen can go and check the number, which is the whole point.
 */
function BorrowerDetail({
  standing,
  period,
}: {
  standing: SignalStanding;
  period: string;
}) {
  const groups = view.byFamily(standing);
  const booked = view.booked(standing);
  const conflict = view.conflicting(standing);
  const thin = view.notTested(standing);

  return (
    <div className="space-y-5 border-t border-border-subtle bg-surface-subtle px-4 py-4">
      {/* R2 §25. Why this borrower is at this level, in the words a credit
          officer would use, before any of the individual conditions. */}
      <div className="space-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <PriorityBadge
            priority={standing.priority}
            label={standing.priority_label}
          />
          <span className="text-xs text-text-muted">
            {standing.priority_means}
          </span>
        </div>
        {standing.priority_because.map((said) => (
          <p
            key={said}
            className="text-sm leading-relaxed text-text-secondary"
          >
            {said}
          </p>
        ))}
      </div>

      <p className="text-sm leading-relaxed text-text-secondary">
        {standing.sentence}
      </p>

      {conflict && (
        <p className="text-xs leading-relaxed text-text-muted">{conflict}</p>
      )}

      {booked.length > 0 && (
        <p className="text-xs leading-relaxed text-warning">
          {booked.map((o) => o.label).join(", ")} describe the booked
          accounting position at this reporting date. They are not a prediction
          that this borrower will migrate.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.family} className="space-y-2">
          <h3 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-text-muted">
            {group.label}
            <SeverityBadge severity={group.severity} />
          </h3>
          <div className="space-y-2">
            {group.fired.map((observation) => (
              <Condition key={observation.signal} observation={observation} />
            ))}
          </div>
        </section>
      ))}

      {standing.cured.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Cured since {standing.cured[0]?.previous_period || "last quarter"}
          </h3>
          <ul className="space-y-1 text-xs text-text-secondary">
            {standing.cured.map((observation) => (
              <li key={observation.signal}>{observation.label}</li>
            ))}
          </ul>
        </section>
      )}

      {thin && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
            Not tested
          </h3>
          <p className="text-xs leading-relaxed text-text-muted">{thin}</p>
          <ul className="space-y-1 text-xs text-text-muted">
            {standing.untested.map((observation) => (
              <li key={observation.signal}>
                <span className="text-text-secondary">
                  {observation.label}:
                </span>{" "}
                {observation.unavailable}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        <Button variant="outline" size="sm" asChild>
          <Link
            href={borrower360Href(standing.borrower_id, period)}
          >
            Open Borrower 360
          </Link>
        </Button>
      </div>
    </div>
  );
}

/**
 * One condition, with everything needed to disagree with it.
 *
 * The threshold and its owner are on the row rather than behind a tooltip:
 * "who decided this number" is the first question a credit officer asks about
 * a signal, and a screen that makes them hunt for it teaches them the answer
 * does not matter.
 */
/**
 * One condition, as a credit officer would want it put. R2 §3.
 *
 * Six things, in the order somebody reads them: WHAT HAPPENED, WHY THIS
 * MATTERS, WHAT CHANGED, the THRESHOLD POLICY behind it, how SEVERE it is,
 * and where it came FROM.
 *
 * The card used to show four bare numbers — "Value 75.4  Previously 71.2
 * Threshold 10" — which is unreadable twice over: it does not say what 75.4
 * is, and it puts a column name where a sentence belongs. The value now
 * carries its unit, and the technical provenance sits at the bottom under a
 * heading that says that is what it is.
 */
function Condition({ observation }: { observation: SignalObservation }) {
  const unit = observation.unit;
  const currency = observation.currency || "SAR";
  const value = ewFormat.showValue(observation.value, unit, currency);
  const before = ewFormat.showValue(observation.previous, unit, currency);
  const moved = ewFormat.showMovement(observation.movement, unit, currency);
  const threshold = ewFormat.showValue(observation.threshold, unit, currency);
  const hasBefore = before !== ewFormat.NOTHING;

  return (
    <div className="rounded-md border border-border-subtle bg-surface p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-sm font-medium">{observation.label}</span>
        <span className="tabular-nums text-sm text-text-secondary">
          {value}
        </span>
        <Badge variant="outline">
          {view.LIFECYCLE_LABEL[observation.lifecycle] ??
            observation.lifecycle}
        </Badge>
        <SeverityBadge severity={observation.severity} />
      </div>

      <p className="mt-1 text-xs leading-relaxed text-text-secondary">
        {observation.means}
      </p>

      <dl className="mt-2 space-y-1 text-xs">
        <Line label="What changed">
          {hasBefore
            ? `${before} at ${observation.previous_period || "the previous reporting date"}, ${value} now${moved !== ewFormat.NOTHING ? ` (${moved})` : ""}.`
            : "No comparable figure at the previous reporting date, so this is a level rather than a movement."}
        </Line>
        <Line label="Threshold policy">
          {`${threshold}, set by ${observation.threshold_owner} (policy v${observation.threshold_version}). A seeded materiality, not a regulatory requirement.`}
        </Line>
        <Line label="Source">
          {`${observation.dataset}.${observation.field} at ${observation.period}.`}
        </Line>
      </dl>
    </div>
  );
}

function Line({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="shrink-0 text-text-muted">{label}:</dt>
      <dd className="text-text-secondary">{children}</dd>
    </div>
  );
}
