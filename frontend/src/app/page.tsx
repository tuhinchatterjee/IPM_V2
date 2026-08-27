"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { GitBranch, Loader2, TriangleAlert } from "lucide-react";

import { Composer, useGreeting } from "@/components/ask/composer";
import { useGreetingName } from "@/components/system/auth";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type Row } from "@/lib/api";
import { byUnit, delta, money } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

/**
 * The Cockpit.
 *
 * Four things, in this order: a greeting, one line telling you what to do, the
 * box you do it in, and what already needs looking at. Nothing else is above
 * the fold, and there is deliberately no dashboard here.
 *
 * There used to be one — four portfolio figures and a link to the CRO Lens.
 * They are gone. A page whose claim is "ask me anything" that opens with four
 * numbers and a row of suggested questions has answered the question of what it
 * is before the reader gets to the box: it is a dashboard with a search field.
 * The figures still exist, in the Lens that is built to carry them.
 *
 * Asking does not answer here. It opens an Investigation and takes you into it,
 * because the answer is never the end: the follow-up is. A Cockpit that rendered
 * the answer in place would make the second question feel like starting over.
 *
 * Nothing on this page is a hard-coded portfolio figure. Every number comes from
 * a registered analysis executed on request, and carries a Trace.
 */
export default function CockpitPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Cockpit />
    </React.Suspense>
  );
}

function Cockpit() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const focusAsk = searchParams.get("focus") === "ask";
  // A question can arrive in the URL — from a link in a lens, or from a
  // keyboard shortcut. It is offered in the composer rather than run
  // automatically: the user still presses Ask.
  const [question, setQuestion] = React.useState(searchParams.get("q") ?? "");
  const [opening, setOpening] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const greeting = useGreeting();
  // The real first name of whoever is signed in. Empty when nobody is, and the
  // greeting reads correctly without it rather than falling back to "there".
  const name = useGreetingName();
  // A Viewer may read what others have produced but may not execute an analysis.
  // The backend refuses it either way; disabling the composer says so before the
  // question is typed rather than after it is submitted.
  const canRun = useCanRunAnalysis();

  const suggestions = useAsync(() => api.askSuggestions(), []);
  const mode = useAsync(() => api.askMode(), []);
  const briefing = useAsync(() => api.briefing(), []);
  const threads = useAsync(() => api.threads(), []);

  /** Open an Investigation on this question and go and read the answer in it. */
  const start = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || opening) return;
      setOpening(true);
      setError(null);
      try {
        const turn = await api.startThread({ question: trimmed });
        router.push(`/investigations/${turn.thread.id}`);
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "CreditProbe could not open that investigation.",
        );
        setOpening(false);
      }
    },
    [router, opening],
  );

  const period = briefing.data?.period ?? "";
  const attention = briefing.data?.attention;

  return (
    <div className="space-y-10">
      {/* ------------------------------------------------------------ asking */}
      <section>
        <h1 className="text-[30px] font-semibold leading-[1.15] tracking-tight text-text-primary">
          {greeting}
          {name && (
            <>
              ,{" "}
              <em className="font-normal italic text-accent">{name}</em>
            </>
          )}
        </h1>
        <p className="mt-1.5 text-[15px] text-text-secondary">
          What&rsquo;s on your mind?
        </p>

        <div className="mt-5">
          <Composer
            value={question}
            onChange={setQuestion}
            onSubmit={(q) => void start(q)}
            busy={opening || !canRun}
            readOnlyNote={
              canRun
                ? undefined
                : "You are acting as a Viewer. Running an analysis needs the Analyst role or above."
            }
            // Three, from the governed catalogue that is actually loaded.
            //
            // These were deliberately absent, on the grounds that a row of
            // suggested questions teaches people CreditProbe answers a fixed
            // list. That objection was right about a fixed list and these are
            // not one: an installation with different data gets different
            // suggestions, and a question about a dataset nobody has is never
            // offered. An empty composer is its own lesson, and it is the
            // wrong one.
            suggestions={(suggestions.data?.questions ?? []).slice(0, 3)}
            autoFocus={focusAsk}
            // Subtle, but not absent. A user must not believe full
            // natural-language understanding is running when it is not — but
            // the Cockpit is not the place for a paragraph about it, so this
            // is one line and Settings carries the detail.
            modeNote={
              mode.data && !mode.data.configured
                ? `${mode.data.label} — questions are read by a deterministic ` +
                  "semantic planner over the governed catalogue. It understands " +
                  "credit concepts, not arbitrary phrasing."
                : undefined
            }
          />
        </div>

        {opening && (
          <p className="mt-3 flex items-center gap-2 text-sm text-text-muted">
            <Loader2 className="size-3.5 animate-spin text-accent" aria-hidden />
            Opening the investigation and running the analyses…
          </p>
        )}
        {error && (
          <Card className="mt-4 border-negative/40 p-4 text-sm text-negative">
            {error}
          </Card>
        )}
      </section>

      {/* -------------------------------------------------- requires attention */}
      <section>
        <SectionHeading
          title="Requires attention"
          meta={period ? `Reporting period ${period}` : undefined}
          info={
            <p>
              Borrowers whose expected credit loss rose most against the prior
              period, ranked by the engine. Selecting one opens an investigation
              on the full question.
            </p>
          }
          action={
            attention?.analysis_run_id ? (
              <Button variant="ghost" size="sm" asChild>
                <Link href={`/trace/${attention.analysis_run_id}`}>
                  <GitBranch aria-hidden />
                  Trace
                </Link>
              </Button>
            ) : undefined
          }
        />
        <Card className="overflow-hidden">
          {briefing.loading && <Skeleton className="h-40 w-full" />}
          {briefing.error && (
            <p className="px-4 py-4 text-sm text-negative">{briefing.error}</p>
          )}
          {!briefing.loading && attention?.result && (
            <>
              <ul className="divide-y divide-border">
                {(attention.result.rows as Row[]).slice(0, 5).map((row, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      disabled={opening}
                      onClick={() =>
                        void start("Show me the top ten deteriorating borrowers.")
                      }
                      className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover disabled:opacity-60"
                    >
                      <TriangleAlert
                        className="mt-0.5 size-3.5 shrink-0 text-warning"
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-3">
                          <span className="truncate text-sm font-medium text-text-primary">
                            {String(row.borrower_name ?? "—")}
                          </span>
                          <span className="shrink-0 text-sm font-medium text-negative tabular">
                            {delta(Number(row.ecl_change), 1, " USD mn")}
                          </span>
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-text-muted">
                          {String(row.sector ?? "")} ·{" "}
                          {money(Number(row.ead ?? 0), 0)}mn exposure
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="border-t border-border bg-surface-sunken px-4 py-2 text-xs text-text-muted">
                {String(attention.result.values.deteriorated_count ?? "—")} of{" "}
                {String(attention.result.values.borrowers_compared ?? "—")}{" "}
                borrowers deteriorated, adding{" "}
                {byUnit(
                  attention.result.values.total_ecl_increase as number,
                  "USD mn",
                )}{" "}
                USD mn of expected credit loss.
              </p>
            </>
          )}
        </Card>
      </section>

      {/* ------------------------------------------------------- recent work */}
      {/* Deliberately quiet: no card, no second line of preview, no icon per
          row. This is a way back to something, not a thing to read — and it
          sits below the fold precisely so it competes with nothing above it. */}
      <section>
        <div className="mb-2 flex items-baseline justify-between gap-4">
          <div className="flex items-center gap-2">
            <h2 className="meta text-text-muted">Continue where you left off</h2>
            <InfoPopover title="Continue where you left off">
              <p>
                Your investigations, most recently spoken in first. Reopening
                one shows the same figures it showed at the time, with the same
                lineage — nothing is quietly re-run.
              </p>
            </InfoPopover>
          </div>
          {threads.data && threads.data.investigations.length > 0 && (
            <Link
              href="/investigations"
              className="text-[11px] text-text-muted underline-offset-4 hover:text-accent hover:underline"
            >
              All
            </Link>
          )}
        </div>

        {threads.data && threads.data.investigations.length > 0 ? (
          <ul>
            {threads.data.investigations.slice(0, 4).map((thread) => (
              <li key={thread.id}>
                <Link
                  href={`/investigations/${thread.id}`}
                  className="group flex items-baseline gap-3 rounded-md px-2 py-1 -mx-2 transition-colors hover:bg-surface-hover"
                >
                  <span className="min-w-0 flex-1 truncate text-[13px] text-text-secondary group-hover:text-text-primary">
                    {thread.title}
                  </span>
                  <span className="mono shrink-0 text-[10px] text-text-muted">
                    {thread.message_count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-muted">
            Nothing yet. Ask a question above — it opens an investigation you can
            keep asking into.
          </p>
        )}
      </section>

      <p className="flex items-center gap-2 border-t border-border pt-4 text-xs text-text-muted">
        <InfoPopover title="About these figures">
          <p>
            Every number on this page was produced by a registered CreditProbe
            Engine analysis executed against the published data, and carries a
            Trace.
          </p>
          <p>
            The book itself is CreditProbe&rsquo;s synthetic demonstration data
            until client data is onboarded and marked authoritative in Data
            Builder.
          </p>
        </InfoPopover>
        Demonstration data. Every figure carries a Trace.
      </p>
    </div>
  );
}


/**
 * A section heading.
 *
 * The explanation of what a section is lives behind the "i", not underneath the
 * title. Four sections with a line of standfirst each is four paragraphs of
 * furniture between the reader and the figures.
 */
function SectionHeading({
  title,
  info,
  meta,
  action,
}: {
  title: string;
  info?: React.ReactNode;
  /** A small fact about the section, e.g. the period it was run against. */
  meta?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          {title}
        </h2>
        {info && <InfoPopover title={title}>{info}</InfoPopover>}
        {meta && <span className="meta text-text-muted">{meta}</span>}
      </div>
      {action}
    </div>
  );
}
