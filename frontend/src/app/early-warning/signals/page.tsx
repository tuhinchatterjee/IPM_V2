"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { ChevronDown, ListChecks, Radar, ShieldQuestion } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import * as view from "@/components/early-warning/signal-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { api, type SignalObservation, type SignalStanding } from "@/lib/api";
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

      {book.data && (
        <>
          <Headline
            period={book.data.period}
            previous={book.data.previous_period ?? ""}
            evaluated={book.data.evaluated}
            headline={headline}
          />

          <NotWatchedFor unavailable={book.data.unavailable ?? []} />

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

/* ------------------------------------------------------- what is not watched */

function NotWatchedFor({
  unavailable,
}: {
  unavailable: { family: string; family_label: string; means: string }[];
}) {
  if (!unavailable.length) return null;
  return (
    <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4">
      <ShieldQuestion
        className="mt-0.5 size-4 shrink-0 text-warning"
        aria-hidden
      />
      <div className="space-y-1 text-xs leading-relaxed text-warning">
        <p className="font-medium">
          What this deployment cannot watch for
        </p>
        {unavailable.map((missing) => (
          <p key={`${missing.family}-${missing.means}`}>
            <span className="font-medium">{missing.family_label}:</span>{" "}
            {missing.means}
          </p>
        ))}
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------- one borrower */

function BorrowerRow({
  standing,
  open,
  onToggle,
}: {
  standing: SignalStanding;
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
        <SeverityBadge severity={standing.severity} />
      </button>

      {open && <BorrowerDetail standing={standing} />}
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
function BorrowerDetail({ standing }: { standing: SignalStanding }) {
  const groups = view.byFamily(standing);
  const booked = view.booked(standing);
  const conflict = view.conflicting(standing);
  const thin = view.notTested(standing);

  return (
    <div className="space-y-5 border-t border-border-subtle bg-surface-subtle px-4 py-4">
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
            href={`/borrower-360?borrower=${encodeURIComponent(standing.borrower_id)}`}
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
function Condition({ observation }: { observation: SignalObservation }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-sm font-medium">{observation.label}</span>
        <Badge variant="outline">
          {view.LIFECYCLE_LABEL[observation.lifecycle] ??
            observation.lifecycle}
        </Badge>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-text-secondary">
        {observation.means}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-4">
        <Figure label="Value" value={observation.value} />
        <Figure label="Previously" value={observation.previous} />
        <Figure label="Threshold" value={observation.threshold} />
        <Figure
          label="Threshold owner"
          value={`${observation.threshold_owner} (v${observation.threshold_version})`}
        />
      </dl>
      <p className="mt-2 text-[11px] text-text-muted">
        Read from {observation.dataset}.{observation.field} at{" "}
        {observation.period}.
      </p>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: unknown }) {
  const shown =
    value === null || value === undefined || value === ""
      ? "—"
      : typeof value === "number"
        ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
        : String(value);
  return (
    <div>
      <dt className="text-text-muted">{label}</dt>
      <dd className="tabular-nums text-text-secondary">{shown}</dd>
    </div>
  );
}
