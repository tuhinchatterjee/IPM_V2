"use client";

/** A persisted Scenario Result opened on its own (Library, Messages, a link). */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ResultView } from "@/components/whatif/result-view";
import { OriginBackLink } from "@/components/workspace/origin-back";
import { urlWith, withBack } from "@/lib/workspace/nav";
import { readObject } from "@/lib/workspace/objects";
import type { ResultBody, ScenarioResult } from "@/lib/workspace/runs";

export function ResultPage({ resultId }: { resultId: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const [result, setResult] = React.useState<ScenarioResult | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    readObject<ResultBody>(resultId)
      .then((r) => setResult(r as ScenarioResult))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [resultId]);
  if (error)
    return (
      <p role="alert" className="text-sm text-negative" data-testid="whatif-result-error">
        {error}
      </p>
    );
  if (!result) return <p className="text-sm text-text-muted">Loading result…</p>;
  if (result.kind !== "scenario_result")
    return (
      <p role="alert" className="text-sm text-negative">
        {resultId} is not a scenario result.
      </p>
    );
  return (
    <div className="space-y-3">
      <OriginBackLink testId="whatif-result-back" />
      <nav className="flex flex-wrap gap-3 text-xs">
        {result.body.entry === "cockpit" ? (
          <Link href={withBack(`/cockpit/thread/${result.body.thread_id}`)} className="text-accent underline" data-testid="whatif-result-open-thread">
            Open the conversation that executed it
          </Link>
        ) : (
          <>
            <Link href={withBack(`/what-if?run=${result.body.run_id}`)} className="text-accent underline" data-testid="whatif-result-open-run">
              Open the run in What-If
            </Link>
            <Link href={withBack(`/scenarios/${result.body.scenario_id}`)} className="text-accent underline" data-testid="whatif-result-open-scenario">
              Scenario {result.body.scenario_id} v{result.body.scenario_version}
            </Link>
          </>
        )}
      </nav>
      {/* The method tab is part of the address: Back from a destination
          reopens the result on the method that was being read. */}
      <ResultView result={result} initialMethod={params.get("method") ?? undefined} onMethod={(m) => router.replace(urlWith({ method: m }), { scroll: false })} />
    </div>
  );
}
