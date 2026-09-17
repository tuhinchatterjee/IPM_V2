"use client";

import * as React from "react";
import { ArrowRight, Check, Download, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The five prompts above the composer, and the toolbar beside them. U04, U05.
 *
 * WHY ABOVE THE COMPOSER AND NOT INSIDE AN ANSWER
 *
 * A reader who has just read an answer is looking at the bottom of it. Putting
 * the next question in the answer's last paragraph means they have to find it
 * there, and means it scrolls away the moment they ask anything else. These
 * sit where the reader's hands already are.
 *
 * WHAT A VISITED MARKER IS FOR
 *
 * The five are an argument in order, not a menu. A reader who has done three
 * of them needs to see which three, because the fourth question only makes
 * sense after the third — and because coming back to a thread a week later
 * without that is starting again.
 *
 * The order never changes under the reader. Reordering by "what you have not
 * done" would make the sequence harder to hold rather than easier.
 *
 * WHY THE EXPORT IS HERE
 *
 * "Export customers to Borrower 360" is available at S0 and at every answered
 * step, not only at the end. A reader who wants the twelve customers behind
 * the first answer should not have to walk to the policy step to get them, and
 * hard-wiring the handoff to the final cohort is how an export quietly becomes
 * a different population from the one on screen.
 *
 * Everything shown is SYNTHETIC demonstration data.
 */

export type Chip = {
  step: string;
  label: string;
  prompt: string;
  chart: string;
  visited: boolean;
  suggested_next: boolean;
  scope: string;
};

export function EpisodeChips({
  caseId,
  threadId,
  visited,
  currentStep,
  onAsk,
  busy,
}: {
  caseId: string;
  threadId: number;
  visited: string[];
  currentStep: string;
  onAsk: (prompt: string) => void;
  busy?: boolean;
}) {
  const [chips, setChips] = React.useState<Chip[] | null>(null);
  const [exporting, setExporting] = React.useState(false);
  const [exported, setExported] = React.useState<{
    snapshotId: string;
    customers: number;
    facilities: number;
    savedId: string;
  } | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api
      .episodeChips(caseId, visited)
      .then((found) => alive && setChips(found.rows))
      .catch(() => alive && setChips([]));
    return () => {
      alive = false;
    };
  }, [caseId, visited.join(",")]);

  async function exportCohort() {
    setExporting(true);
    setError("");
    try {
      const found = await api.cohortFromStep({
        case_id: caseId,
        step: currentStep || "S0",
        thread_id: String(threadId),
      });
      setExported({
        snapshotId: found.snapshot.snapshot_id,
        customers: found.snapshot.customer_count,
        facilities: found.snapshot.facility_count,
        savedId: found.saved.saved_id,
      });
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The customers could not be exported.",
      );
    } finally {
      setExporting(false);
    }
  }

  if (!chips?.length) return null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-text-muted">
          Next questions
        </span>
        {chips.map((chip) => (
          <button
            key={chip.step}
            type="button"
            disabled={busy}
            onClick={() => onAsk(chip.prompt)}
            title={chip.prompt}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition",
              chip.visited
                ? "border-border bg-surface-subtle text-text-muted"
                : "border-border text-text-secondary hover:bg-surface-hover",
              chip.suggested_next &&
                "border-accent/60 bg-accent/10 text-accent hover:bg-accent/15",
              busy && "cursor-not-allowed opacity-60",
            )}
          >
            {chip.visited ? (
              <Check className="size-3" aria-hidden />
            ) : chip.suggested_next ? (
              <ArrowRight className="size-3" aria-hidden />
            ) : null}
            <span className="mono text-[10px] opacity-70">{chip.step}</span>
            {chip.label}
          </button>
        ))}
      </div>

      <p className="text-[11px] leading-snug text-text-muted">
        Each chip asks the full question, which you can read by hovering. Type
        your own instead at any point — a rephrasing reaches the same step, and
        anything else is answered the ordinary way. Figures are computed from
        the published book at the reporting date; none of this is bank-approved
        policy.
      </p>

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2">
        <Button
          size="sm"
          variant="outline"
          onClick={exportCohort}
          disabled={exporting}
        >
          <Users className="mr-1.5 size-3.5" aria-hidden />
          {exporting
            ? "Exporting…"
            : `Export customers to Borrower 360 (${currentStep || "S0"})`}
        </Button>
        {exported ? (
          <>
            <a
              className="text-xs text-accent underline underline-offset-2"
              href={`/borrower-360?snapshot=${exported.snapshotId}`}
            >
              {exported.customers.toLocaleString("en-GB")} customers ·{" "}
              {exported.facilities.toLocaleString("en-GB")} facilities — open in
              Borrower 360
            </a>
            <a
              className="inline-flex items-center gap-1 text-xs text-text-secondary underline underline-offset-2"
              href={`/api/v1/retail/cohorts/${exported.snapshotId}/workbook.xlsx`}
            >
              <Download className="size-3" aria-hidden />
              Excel
            </a>
          </>
        ) : null}
        {error ? <span className="text-xs text-negative">{error}</span> : null}
      </div>
    </div>
  );
}
