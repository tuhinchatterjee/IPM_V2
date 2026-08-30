"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  LearningCockpit,
  LearningMeasurementRules,
  LearningPartitions,
  LearningTimeline,
  LearningWindows,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * AI Intelligence Studio → Continuous Learning. §56, §64.
 *
 * The one thing this screen refuses to do
 * ----------------------------------------
 * Add "learning captured" to "measured improvement". They are two blocks
 * with a sentence between them saying why, because the temptation to
 * combine them is enormous and the combination is a lie: an installation
 * that captured four hundred observations and improved by nothing has done
 * something worth knowing, and one number reports it as progress.
 *
 * Why validation is the figure in bold
 * -------------------------------------
 * Development is the set that was tuned against. It always looks better, and
 * a screen that led with it would report every round of tuning as a win. So
 * both are shown, validation is the one the verdict is based on, and where
 * they disagree the sentence says which to believe.
 *
 * What is not on this screen, on purpose
 * ---------------------------------------
 * Any sealed-holdout question or gold answer. §58 names the
 * continuous-learning UI among six places holdout content may never reach —
 * a screen showing the questions is a screen somebody reads before a
 * certification run. The holdout's VERSION appears, which says which exam
 * was sat without circulating it.
 */

const TABS = [
  [
    "cockpit",
    "What has been learned",
    "How much was captured since the baseline, and — separately — how much " +
      "measurably changed.",
  ],
  [
    "dimensions",
    "The six dimensions",
    "Development against validation, dimension by dimension, with the " +
      "sample behind each figure.",
  ],
  [
    "timeline",
    "Timeline",
    "Every measurement in order, marked by whether it followed a change or " +
      "just followed a schedule.",
  ],
  [
    "partitions",
    "Evaluation sets",
    "Development, validation and the sealed holdout: what each is for, and " +
      "whether validation is still out-of-sample.",
  ],
  [
    "rules",
    "What a number may claim",
    "The thresholds and the refusals behind every figure on this screen.",
  ],
] as const;

type TabId = (typeof TABS)[number][0];

export default function ContinuousLearningPage() {
  const [tab, setTab] = React.useState<TabId>("cockpit");
  const [window, setWindow] = React.useState(
    "SINCE_CURRENT_INTELLIGENCE_RELEASE",
  );
  const [windows, setWindows] = React.useState<LearningWindows | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .learningWindows()
      .then((found) => live && setWindows(found))
      .catch(() => live && setWindows(null));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Continuous Learning"
        description={
          "What CreditProbe has learned, how much of it reached production, " +
          "and whether any of it made the answers better."
        }
      />

      <div className="flex flex-wrap items-center gap-3">
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

        {windows && (tab === "cockpit" || tab === "dimensions") && (
          <label className="ml-auto text-xs text-muted-foreground">
            Compared over{" "}
            <select
              value={window}
              onChange={(e) => setWindow(e.target.value)}
              className="rounded border border-border bg-transparent px-1.5 py-0.5 text-xs"
            >
              {windows.windows.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.id.replace(/_/g, " ").toLowerCase()}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        {TABS.find(([id]) => id === tab)?.[2]}
      </p>

      <Panel key={`${tab}:${window}`} tab={tab} window={window} />
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <Card className="p-4 text-xs text-muted-foreground">{children}</Card>;
}

function Panel({ tab, window }: { tab: TabId; window: string }) {
  const [state, setState] = React.useState<{
    cockpit?: LearningCockpit;
    timeline?: LearningTimeline;
    partitions?: LearningPartitions;
    rules?: LearningMeasurementRules;
  } | null>(null);
  const [failed, setFailed] = React.useState("");

  React.useEffect(() => {
    let live = true;
    const load = async () => {
      switch (tab) {
        case "cockpit":
        case "dimensions":
          return { cockpit: await api.learningCockpit(window) };
        case "timeline":
          return { timeline: await api.learningTimeline() };
        case "partitions":
          return { partitions: await api.learningPartitions() };
        case "rules":
          return { rules: await api.learningMeasurementRules() };
      }
    };
    load()
      .then((found) => live && setState(found ?? {}))
      .catch((error: unknown) => {
        if (!live) return;
        setFailed(
          error instanceof Error ? error.message : "That did not load.",
        );
        setState({});
      });
    return () => {
      live = false;
    };
  }, [tab, window]);

  if (state === null) return <Skeleton className="h-48 w-full" />;
  if (failed) return <Empty>{failed}</Empty>;

  if (tab === "cockpit" && state.cockpit)
    return <Cockpit data={state.cockpit} />;
  if (tab === "dimensions" && state.cockpit)
    return <Dimensions data={state.cockpit} />;
  if (tab === "timeline" && state.timeline)
    return <Timeline data={state.timeline} />;
  if (tab === "partitions" && state.partitions)
    return <Partitions data={state.partitions} />;
  if (tab === "rules" && state.rules) return <Rules data={state.rules} />;
  return <Empty>Nothing to show here yet.</Empty>;
}

// ------------------------------------------------------------------ §64

function Cockpit({ data }: { data: LearningCockpit }) {
  if (!data.baseline || data.dimensions.length === 0) {
    return (
      <div className="space-y-4">
        <Card className="p-4">
          <h2 className="text-sm font-medium">{data.headline}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{data.why}</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">{data.headline}</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Compared against {data.baseline.comparable_to}.
        </p>
      </Card>

      {/* The two blocks, and the sentence between them. Never one number. */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <h3 className="text-sm font-medium">Learning captured</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {Object.entries(data.learning_captured).map(([key, value]) => (
              <li key={key} className="flex justify-between gap-2">
                <span className="text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="font-medium tabular-nums">{value}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-medium">Measured change</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {Object.entries(data.measured_change)
              .filter(([, value]) => typeof value === "number")
              .map(([key, value]) => (
                <li key={key} className="flex justify-between gap-2">
                  <span className="text-muted-foreground">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span className="font-medium tabular-nums">
                    {String(value)}
                  </span>
                </li>
              ))}
          </ul>
        </Card>
      </div>

      <Empty>{data.these_are_not_the_same_thing}</Empty>

      {data.overfitting && (
        <Card
          className={cn(
            "border-l-2 p-4",
            data.overfitting.possible_overfitting
              ? "border-l-amber-500/60"
              : "border-l-emerald-500/60",
          )}
        >
          <h3 className="text-sm font-medium">
            {data.overfitting.possible_overfitting
              ? "Possible overfitting"
              : "Development and validation moved together"}
          </h3>
          <p className="mt-1 text-xs">
            Development {data.overfitting.development_delta_points.toFixed(1)}{" "}
            pp · validation{" "}
            {data.overfitting.validation_delta_points.toFixed(1)} pp · gap{" "}
            {data.overfitting.gap_points.toFixed(1)} pp
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {data.overfitting.recommended_review}
          </p>
        </Card>
      )}

      {data.release_gate && !data.release_gate.may_activate && (
        <Card className="border-l-2 border-l-destructive p-4">
          <h3 className="text-sm font-medium">This may not be activated</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {data.release_gate.because}
          </p>
        </Card>
      )}

      {data.sealed_holdout && (
        <Empty>
          Sealed holdout version{" "}
          <span className="font-mono">
            {data.sealed_holdout.version || "—"}
          </span>
          . {data.sealed_holdout.why}
        </Empty>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ §62

function Dimensions({ data }: { data: LearningCockpit }) {
  if (data.dimensions.length === 0) {
    return <Empty>{data.why ?? data.headline}</Empty>;
  }
  return (
    <div className="space-y-3">
      {data.dimensions.map((one) => (
        <Card key={one.dimension} className="p-4">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">{one.dimension}</h3>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px]",
                one.verdict === "REGRESSED"
                  ? "bg-destructive/10 text-destructive"
                  : one.verdict === "IMPROVED"
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                    : "bg-muted text-muted-foreground",
              )}
            >
              {one.verdict}
            </span>
          </div>
          <p className="mt-1 text-xs">{one.reads_as}</p>
          <div className="mt-3 grid gap-3 text-[11px] sm:grid-cols-2">
            <Partition label="Development" body={one.development} />
            {/* Validation second and unmuted: it is the figure the verdict
                rests on, because development is the set that was tuned
                against and always looks better. */}
            <Partition label="Validation" body={one.validation} emphasis />
          </div>
        </Card>
      ))}
    </div>
  );
}

function Partition({
  label,
  body,
  emphasis = false,
}: {
  label: string;
  body: Record<string, unknown>;
  emphasis?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded border p-2",
        emphasis ? "border-border" : "border-border/40",
      )}
    >
      <p
        className={cn(
          "font-medium",
          emphasis ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {label}
      </p>
      <p className="mt-0.5 text-muted-foreground">{String(body.reads_as)}</p>
      <p className="mt-1 text-muted-foreground">
        {String(body.evidence)} · {String(body.cases)} case(s)
      </p>
    </div>
  );
}

// ------------------------------------------------------------------ §65

function Timeline({ data }: { data: LearningTimeline }) {
  if (data.points.length === 0) {
    return <Empty>No measurement has been recorded in this window.</Empty>;
  }
  return (
    <div className="space-y-3">
      <Empty>{data.note}</Empty>
      {data.points
        .slice()
        .reverse()
        .map((point) => (
          <Card key={point.snapshot_id} className="p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs font-medium">
                {point.trigger}
                {point.marks_a_change && (
                  <span className="ml-1 text-[11px] text-muted-foreground">
                    (followed a change)
                  </span>
                )}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {point.at.slice(0, 16).replace("T", " ")}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Captured {point.captured} · activated {point.activated} · critical
              validation failures {point.critical_failures_validation}
            </p>
          </Card>
        ))}
    </div>
  );
}

// --------------------------------------------------------------- §58/§72

function Partitions({ data }: { data: LearningPartitions }) {
  return (
    <div className="space-y-4">
      {data.partitions.map((one) => (
        <Card key={one.id} className="p-4">
          <h3 className="text-sm font-medium">{one.id}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{one.means}</p>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Used for: {one.used_for.join(", ")}.
          </p>
          {!one.may_tune_against && (
            <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
              {one.why_not}
            </p>
          )}
        </Card>
      ))}

      <Card
        className={cn(
          "border-l-2 p-4",
          data.hygiene.healthy
            ? "border-l-emerald-500/60"
            : "border-l-amber-500/60",
        )}
      >
        <h3 className="text-sm font-medium">
          {data.hygiene.healthy
            ? "Validation is still out-of-sample"
            : "Validation may be drifting"}
        </h3>
        <p className="mt-1 text-xs">
          In the last {data.hygiene.window_days} days: development{" "}
          {data.hygiene.development_runs}, validation{" "}
          {data.hygiene.validation_runs}, sealed holdout{" "}
          {data.hygiene.sealed_holdout_runs}.
        </p>
        <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
          {data.hygiene.findings.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-muted-foreground">
          {data.hygiene.note}
        </p>
      </Card>

      <Card className="p-4">
        <h3 className="text-sm font-medium">
          Where sealed-holdout content may never appear
        </h3>
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {data.sealed_holdout_never_reaches.map((one) => (
            <li key={one.audience}>
              <span className="font-mono text-[11px]">{one.audience}</span> —{" "}
              {one.because}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Only these fields may be published from it, and only after a
          certification run: {data.aggregate_fields_only.join(", ")}.
        </p>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------ §61/§77

function Rules({ data }: { data: LearningMeasurementRules }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="text-sm font-medium">Thresholds</h3>
        <ul className="mt-2 space-y-1 text-xs">
          <li>
            <span className="text-muted-foreground">
              Below this many cases, a difference is not distinguishable from
              noise:{" "}
            </span>
            <span className="font-medium tabular-nums">
              {data.minimum_cases}
            </span>
          </li>
          <li>
            <span className="text-muted-foreground">
              Below this many, a percentage is not shown at all:{" "}
            </span>
            <span className="font-medium tabular-nums">
              {data.trivial_cases}
            </span>
          </li>
          <li>
            <span className="text-muted-foreground">
              Percentage points below which a change is not material:{" "}
            </span>
            <span className="font-medium tabular-nums">
              {data.material_points}
            </span>
          </li>
          <li>
            <span className="text-muted-foreground">
              Days after which a measurement is stale:{" "}
            </span>
            <span className="font-medium tabular-nums">{data.stale_days}</span>
          </li>
        </ul>
      </Card>

      <Card className="p-4">
        <h3 className="text-sm font-medium">What a number may claim</h3>
        <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
          {Object.entries(data.rules).map(([key, means]) => (
            <li key={key}>{means}</li>
          ))}
        </ul>
      </Card>

      <Card className="p-4">
        <h3 className="text-sm font-medium">Verdicts and evidence levels</h3>
        <p className="mt-2 text-xs text-muted-foreground">
          Verdicts: {data.labels.join(" · ")}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Evidence: {data.evidence_levels.join(" · ")}
        </p>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Attribution sources: {data.attribution_sources.join(", ")}. Only those
          measured in isolation are attributed; the rest go into UNATTRIBUTED /
          INTERACTION.
        </p>
      </Card>
    </div>
  );
}
