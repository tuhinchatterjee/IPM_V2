"use client";

/**
 * A Scenario Definition applied to the active governed cohort.
 *
 * Applying BINDS the definition to the cohort (a new version of your own
 * scenario, or a bound copy of a library template -- the original is never
 * changed) and previews it against the book. Nothing is calculated here.
 */

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { PreviewPanel } from "@/components/scenarios/preview-panel";
import { RunPanel } from "@/components/whatif/run-panel";
import { count } from "@/lib/viz/format";
import type { Cohort } from "@/lib/workspace/objects";
import type { Run } from "@/lib/workspace/runs";
import {
  bindScenario,
  previewScenario,
  resolveOverlaps,
  type Preview,
  type ScenarioObject,
} from "@/lib/workspace/scenarios";
import { withBack } from "@/lib/workspace/nav";

export function ScenarioApplication({
  cohort,
  scenario,
  entry = "whatif",
  initialRunId = "",
  onRun,
}: {
  cohort: Cohort | null;
  scenario: ScenarioObject;
  entry?: "whatif" | "library" | "cockpit" | "messages";
  initialRunId?: string;
  onRun?: (run: Run | null) => void;
}) {
  const [bound, setBound] = React.useState<ScenarioObject | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    (async () => {
      // No active cohort: the scenario runs on its own declared scope.
      const already = !cohort || (scenario.body.scope.type === "cohort" && scenario.body.scope.cohort_id === cohort.object_id);
      const target = already || !cohort ? scenario : (await bindScenario(scenario.object_id, cohort.object_id)).scenario;
      if (!live) return;
      setBound(target);
      const pv = await previewScenario(target.object_id, target.version);
      if (live) setPreview(pv);
    })().catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [cohort, scenario]);

  async function resolve(resolutions: Parameters<typeof resolveOverlaps>[1]) {
    if (!bound) return;
    const next = await resolveOverlaps(bound.object_id, resolutions);
    setBound(next);
    setPreview(await previewScenario(next.object_id, next.version));
  }

  return (
    <section className="space-y-3 rounded-xl border border-accent bg-surface p-4" data-testid="whatif-application" data-scenario-id={bound?.object_id ?? ""}>
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{cohort ? "Scenario applied to the active cohort" : "Scenario on its own scope"}</h2>
        <span className="text-xs text-text-muted">
          {cohort
            ? `${scenario.body.name} on ${cohort.body.name} (${count(cohort.body.counts.entities)} exposures, ${cohort.object_id})`
            : `${scenario.body.name} · ${scenario.body.scope.label ?? scenario.body.scope.type}`}
        </span>
        {bound && (
          <Link href={withBack(`/scenarios/${bound.object_id}?version=${bound.version}`)} className="ml-auto text-xs text-accent underline" data-testid="whatif-bound-scenario">
            {bound.object_id} v{bound.version}
          </Link>
        )}
      </header>
      {error && (
        <p role="alert" className="text-sm text-negative" data-testid="whatif-application-error">
          {error}
        </p>
      )}
      {!preview && !error && (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Binding the cohort and resolving the scenario against the book…
        </p>
      )}
      {preview && bound && <PreviewPanel preview={preview} definition={bound.body} onResolve={bound.owner_id !== "creditprobe-library" ? resolve : undefined} testId="whatif-preview" />}
      {preview && bound && <RunPanel key={`${bound.object_id}-${bound.version}`} scenario={bound} cohort={cohort} entry={entry} initialRunId={initialRunId} onRun={onRun} />}
    </section>
  );
}
