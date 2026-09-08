"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { CockpitV2Badge } from "@/components/ask/cockpit-v2";
import {
  CockpitV3Answer,
  CockpitV3Badge,
  CockpitV3Progress,
} from "@/components/ask/cockpit-agentic";
import { Composer, useGreeting } from "@/components/ask/composer";
import { PendingOfficer } from "@/components/agentic/pending";
import { RequiresAttention } from "@/components/attention/requires-attention";
import { EarlyWarningStrip } from "@/components/early-warning/cockpit-strip";
import { BackLink } from "@/components/layout/back-link";
import { useGreetingName } from "@/components/system/auth";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import type {
  CockpitV2Diagnostics,
  CockpitV3Answer as CockpitV3AnswerPayload,
  CockpitV3Diagnostics,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { fromCockpit, linkBack, useReturnTo } from "@/lib/return-to";

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
  // The question actually submitted, kept separately from what is in the
  // composer: `start` is also called with a suggestion, and the officer
  // indicator has to name the officer for the question that is RUNNING.
  const [asked, setAsked] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // The Cockpit is itself reachable with a return context — "Investigate this
  // borrower" on Early Warning lands here. When it is, the investigation that
  // opens inherits that context rather than the Cockpit, so Back from the
  // answer returns to the borrower the reader started from rather than to a
  // Cockpit they only passed through.
  const arrivedFrom = useReturnTo(fromCockpit());
  const cameFromElsewhere = arrivedFrom.href !== "/";
  const openFrom = cameFromElsewhere ? arrivedFrom : fromCockpit();

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
      setAsked(trimmed);
      setOpening(true);
      setError(null);
      try {
        const turn = await api.startThread({ question: trimmed });
        // The investigation opens with Back pointing at the Cockpit, because
        // that is where the reader came from. Without it, Back lands on the
        // Investigations index — a screen they never visited.
        router.push(linkBack(`/investigations/${turn.thread.id}`, openFrom));
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "CreditProbe could not open that investigation.",
        );
        setOpening(false);
      }
    },
    [router, opening, openFrom],
  );

  // The reporting period the Cockpit is about. Still read from the briefing,
  // which is where the governed calendar lives; the attention LIST no longer
  // comes from it — Risk Cases do.
  const period = briefing.data?.period ?? "";

  // The Cockpit V2 diagnostic badge. Brief §1.3 asks for something that makes
  // it possible to PROVE which backend and which data the browser is using,
  // and a demonstration where nobody can tell which build answered is a
  // demonstration of nothing. Fetched once; the badge renders nothing at all
  // when the switch is off, which is every other deployment.
  const [cockpitV2, setCockpitV2] =
    React.useState<CockpitV2Diagnostics | null>(null);
  const [cockpitV2Quarter, setCockpitV2Quarter] = React.useState<string>("");
  React.useEffect(() => {
    let live = true;
    api
      .cockpitV2Diagnostics()
      .then((found) => {
        if (live) setCockpitV2(found);
      })
      .catch(() => {
        // A deployment without Cockpit V2 has no such endpoint. That is the
        // ordinary case and it is not an error the reader needs to see.
        if (live) setCockpitV2(null);
      });
    return () => {
      live = false;
    };
  }, []);

  // Cockpit Agentic V3. Its own state, its own endpoint, and — the point of
  // the whole branch — no path from here back into the deterministic answer
  // path or the legacy analyst. When the switch is off none of this renders.
  const [cockpitV3, setCockpitV3] =
    React.useState<CockpitV3Diagnostics | null>(null);
  const [v3Answer, setV3Answer] =
    React.useState<CockpitV3AnswerPayload | null>(null);
  const [v3Steps, setV3Steps] = React.useState<string[]>([]);
  const [v3Running, setV3Running] = React.useState(false);
  const [v3Mode, setV3Mode] = React.useState<string>("standard");
  const v3RequestId = React.useRef<string>("");

  React.useEffect(() => {
    let live = true;
    api
      .cockpitV3Diagnostics()
      .then((found) => {
        if (live) {
          setCockpitV3(found);
          if (found?.default_mode) setV3Mode(found.default_mode);
        }
      })
      .catch(() => {
        // A deployment without the agentic Cockpit has no such endpoint. That
        // is the ordinary case, not an error the reader needs to see.
        if (live) setCockpitV3(null);
      });
    return () => {
      live = false;
    };
  }, []);

  const askV3 = React.useCallback(
    async (text: string) => {
      if (!cockpitV3?.available) return;
      const requestId = `req-${Date.now().toString(36)}`;
      v3RequestId.current = requestId;
      setV3Running(true);
      setV3Answer(null);
      setV3Steps(["Reading the question"]);
      try {
        const found = await api.cockpitV3Ask({
          question: text,
          mode: v3Mode,
          thread_id: "cockpit-web",
          request_id: requestId,
        });
        setV3Answer(found);
        // The progress the server actually recorded, not a guess made here.
        setV3Steps(found.states?.progress ?? []);
      } catch {
        setV3Steps([]);
      } finally {
        setV3Running(false);
      }
    },
    [cockpitV3, v3Mode],
  );

  const cancelV3 = React.useCallback(() => {
    if (v3RequestId.current) void api.cockpitV3Cancel(v3RequestId.current);
  }, []);

  return (
    <div className="space-y-10">
      {/* A Back control only where there is somewhere to go back to. The
          Cockpit is the root of the product, so a permanent Back on it would
          be a lie; one that appears only when a link brought the reader here
          is the whole return-context contract in one control. */}
      {cameFromElsewhere && (
        <BackLink href={arrivedFrom.href} label={arrivedFrom.label} />
      )}

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

        <CockpitV2Badge
          diagnostics={cockpitV2}
          selectedQuarter={cockpitV2Quarter}
          onSelectQuarter={setCockpitV2Quarter}
        />
        <CockpitV3Badge diagnostics={cockpitV3} />

        {cockpitV3?.available && (
          <div className="mb-3 flex items-center gap-2 text-[11px] text-slate-600">
            <span>Depth</span>
            {(cockpitV3.modes ?? ["standard", "deep"]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setV3Mode(m)}
                className={`rounded border px-2 py-0.5 capitalize ${
                  v3Mode === m
                    ? "border-slate-800 bg-slate-800 text-white"
                    : "border-slate-300 bg-white text-slate-700"
                }`}
              >
                {m}
              </button>
            ))}
            <span className="text-slate-400">
              Deep is never selected for you.
            </span>
          </div>
        )}

        <CockpitV3Progress
          steps={v3Steps}
          running={v3Running}
          onCancel={cancelV3}
        />

        {v3Answer && (
          <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
            <CockpitV3Answer
              payload={v3Answer}
              onAsk={(q) => {
                setQuestion(q);
                void askV3(q);
              }}
              onNavigate={(route) => {
                window.location.href = route;
              }}
            />
          </div>
        )}

        <div className="mt-5">
          <Composer
            value={question}
            onChange={setQuestion}
            onSubmit={(q) => {
              if (cockpitV3?.available) {
                void askV3(q);
                return;
              }
              void start(q);
            }}
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

        {/* §6, §8: an officer, named, directly below the composer — not a
            spinner. What was here was `Loader2` and the sentence "Opening the
            investigation and running the analyses…", which is the gaming
            spinner §6 forbids and says the same thing for a metadata lookup
            and for a whole-book review. `PendingOfficer` previews the SAME
            deterministic selection the run is created with, so the title a
            reader sees first is never contradicted by the one they see next. */}
        {opening && <PendingOfficer question={asked} className="mt-3" />}
        {error && (
          <Card className="mt-4 border-negative/40 p-4 text-sm text-negative">
            {error}
          </Card>
        )}
      </section>

      {/* -------------------------------------------------- requires attention */}
      {/* Rebuilt for §40–§47. What used to be here was one hard-coded list —
          the five borrowers whose ECL rose most — produced by one registered
          analysis. It is now the Risk Case list: four levels, governed
          severity, a grounded summary sentence, and a drawer carrying the
          evidence and the actions.

          The section stays the same SIZE. §40 asks the Cockpit to remain calm
          and §63 asks this to fit above the fold at 1440×900, so the filters
          are chips rather than tabs and the rows are one line each. */}
      <section>
        <SectionHeading
          title="Requires attention"
          meta={period ? `Reporting period ${period}` : undefined}
          info={
            <p>
              Risk Cases raised by CreditProbe&rsquo;s governed review of each
              published period: portfolio movements, segments moving more than
              the book, the borrowers driving them, and data that is missing.
              Severity is computed by a published formula, never by a model.
            </p>
          }
        />
        <RequiresAttention
          period={period}
          onInvestigate={(id) =>
            router.push(linkBack(`/investigations/${id}`, fromCockpit()))
          }
        />
      </section>

      {/* ------------------------------------------------------ early warning */}
      {/* §36. One line, six counts, a link — and deliberately no colour. A row
          of red numbers on a home page is a row people stop seeing by the
          second week, and the module's whole argument is that these are
          countable conditions rather than an alarm.

          Counts of SITUATIONS, not of signals: "new conditions: 4,812" tells
          nobody anything, while "borrowers with a new condition: 214" is a
          queue somebody can work through. */}
      <section>
        <SectionHeading
          title="Early warning"
          info={
            <p>
              The governed early-warning taxonomy applied to every borrower on
              the book: named conditions, in families, each with a threshold
              somebody owns. Deliberately not a score — the Signals screen
              shows which conditions fired for whom, and what could not be
              tested.
            </p>
          }
        />
        <EarlyWarningStrip period={period} />
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
            The book itself is CreditProbe&rsquo;s synthetic data
            until client data is onboarded and marked authoritative in Data
            Builder.
          </p>
        </InfoPopover>
        Synthetic data. Every figure carries a Trace.
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
