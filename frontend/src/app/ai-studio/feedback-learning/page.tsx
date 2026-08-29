"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { figure, summarise } from "@/components/feedback/present";
import { api } from "@/lib/api";
import type { LearningGuard, SatisfactionMetrics } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Feedback & Learning. §16.
 *
 * Why it is here and not in the main navigation
 * ----------------------------------------------
 * §16: "do not clutter ordinary Cockpit navigation; place under AI
 * Intelligence Studio / Administration." A credit officer answering questions
 * has no business in a review queue, and a queue in their sidebar is a queue
 * they will eventually click on and not understand.
 *
 * Seven tabs, and what each is for
 * ---------------------------------
 *   INBOX        every rating and comment, as given
 *   OBSERVATIONS every question, labelled or not — the denominator
 *   CANDIDATES   what corrections have become
 *   REPLAY       production versus a candidate, case by case
 *   RELEASES     what production is running, and what would replace it
 *   MODELS       local auxiliary models and their baselines
 *   METRICS      satisfaction and learning, kept apart from accuracy
 *
 * The eighth thing on the page is not a tab
 * ------------------------------------------
 * The §11 guard, rendered at the top, because it is the claim the whole area
 * rests on: raw feedback cannot change an Assurance status, a score, a plan, a
 * result, a release, a prompt, a routing policy, a model, the ontology or a
 * method. It is shown to any analyst rather than to administrators only —
 * "feedback cannot change the scores" is a promise made to users, and a
 * promise only administrators can verify is a promise.
 */

const TABS = [
  ["inbox", "Feedback inbox", "Every rating and comment, as given."],
  [
    "observations",
    "Observations",
    "Every question asked, whether or not anybody rated the answer. The " +
      "denominator that makes a response rate mean something.",
  ],
  [
    "candidates",
    "Candidate cases",
    "What corrections have become. Nine statuses between a complaint and " +
      "production.",
  ],
  [
    "replay",
    "Replay lab",
    "Current production against a candidate release, case by case. " +
      "Improvements and regressions are never netted.",
  ],
  [
    "releases",
    "Learning releases",
    "What production is running, what would replace it, and the gates in " +
      "between.",
  ],
  [
    "models",
    "Local models",
    "Auxiliary classifiers, their deterministic baselines, and what they " +
      "may never be trained to do.",
  ],
  [
    "metrics",
    "Metrics",
    "Satisfaction and learning effectiveness. Neither is accuracy.",
  ],
] as const;

type TabId = (typeof TABS)[number][0];

export default function FeedbackLearningPage() {
  const [tab, setTab] = React.useState<TabId>("inbox");
  const [guard, setGuard] = React.useState<LearningGuard | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .learningGuard()
      .then((found) => live && setGuard(found))
      .catch(() => live && setGuard(null));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Feedback & Learning"
        description={
          "What users said, what CreditProbe did, and everything that has to " +
          "happen between the two before production changes."
        }
      />

      {guard && (
        <Card
          className={cn(
            "border-l-2 p-3 text-xs",
            guard.ok ? "border-l-emerald-500/60" : "border-l-destructive",
          )}
        >
          <p className="font-medium">
            {guard.ok
              ? "Raw feedback cannot change production"
              : "The §11 guard is reporting a problem"}
          </p>
          <p className="mt-1 text-muted-foreground">{guard.explanation}</p>
          {guard.exemptions.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
              {guard.exemptions.map((one) => (
                <li key={`${one.module}:${one.line}`}>
                  <span className="font-mono">
                    {one.module}:{one.line}
                  </span>{" "}
                  — {one.reason}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <nav className="flex flex-wrap gap-1 border-b border-border/60 pb-1">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-current={tab === id ? "page" : undefined}
            className={cn(
              "rounded px-2 py-1 text-xs transition-colors",
              "focus-visible:outline focus-visible:outline-2",
              "focus-visible:outline-offset-2",
              tab === id
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted/60",
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      <p className="text-xs text-muted-foreground">
        {TABS.find(([id]) => id === tab)?.[2]}
      </p>

      {/* Keyed on the tab so switching REMOUNTS rather than resetting state
          inside an effect. Same visible behaviour, and it is the difference
          between "clear these three pieces of state, then fetch" — which is a
          cascading render and an easy place to forget one — and starting from
          nothing, which cannot forget anything. */}
      <Panel key={tab} tab={tab} />
    </div>
  );
}

function Panel({ tab }: { tab: TabId }) {
  const [rows, setRows] = React.useState<Record<string, unknown>[] | null>(
    null,
  );
  const [note, setNote] = React.useState("");
  const [metrics, setMetrics] = React.useState<SatisfactionMetrics | null>(
    null,
  );

  React.useEffect(() => {
    let live = true;

    const load = async () => {
      if (tab === "inbox") {
        const found = await api.learningInbox();
        return { rows: found.events, note: "" };
      }
      if (tab === "observations") {
        const found = await api.learningObservations();
        return { rows: found.observations, note: found.note };
      }
      if (tab === "candidates") {
        const found = await api.learningCandidates();
        return { rows: found.candidates, note: "" };
      }
      if (tab === "replay") {
        const found = await api.learningReplays();
        return { rows: found.replays, note: "" };
      }
      if (tab === "releases") {
        const found = await api.learningReleases();
        return { rows: found.releases, note: found.note };
      }
      if (tab === "models") {
        const found = await api.learningModels();
        return { rows: found.runs, note: found.note };
      }
      const found = await api.learningSatisfaction();
      if (live) setMetrics(found);
      return { rows: [], note: found.note };
    };

    load()
      .then((found) => {
        if (!live) return;
        setRows(found.rows);
        setNote(found.note);
      })
      .catch(() => {
        if (live) setRows([]);
      });
    return () => {
      live = false;
    };
  }, [tab]);

  if (rows === null) return <Skeleton className="h-32 w-full" />;

  if (tab === "metrics" && metrics) {
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Figure label="Answers given" value={metrics.answers_given} />
          <Figure label="Rated" value={metrics.rated} />
          <Figure
            label="Response rate"
            value={figure(metrics.response_rate_pct, "%")}
          />
          <Figure
            label="Corrections"
            value={metrics.corrections}
          />
        </div>
        <Card className="p-3">
          <p className="text-xs font-medium">By answer</p>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {Object.entries(metrics.by_rating).map(([rating, count]) => (
              <li key={rating}>
                {rating}: {count}
              </li>
            ))}
          </ul>
        </Card>
        <p className="text-[11px] text-muted-foreground">{metrics.note}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {note && <p className="text-[11px] text-muted-foreground">{note}</p>}
      {rows.length === 0 ? (
        <Card className="p-4 text-xs text-muted-foreground">
          Nothing here yet. That is a fact about this deployment rather than a
          problem: an empty inbox means nobody has given feedback, and an empty
          release list means nothing has been proposed for production.
        </Card>
      ) : (
        <ul className="space-y-2">
          {rows.slice(0, 50).map((row, index) => (
            <Card key={index} className="p-3 text-xs">
              <pre className="overflow-x-auto whitespace-pre-wrap break-words text-[11px] text-muted-foreground">
                {summarise(row)}
              </pre>
            </Card>
          ))}
        </ul>
      )}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-medium tabular-nums">{value}</p>
    </Card>
  );
}
