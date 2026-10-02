"use client";

/**
 * Trace > LLM Exchange for one Cockpit run. Reached from the governance
 * record (`/cockpit/trace/[runId]`) and from the AI Model Lab.
 */

import { Suspense, use } from "react";

import { LlmExchangeView } from "@/components/llm-exchange/llm-exchange-view";
import { OriginBackLink } from "@/components/workspace/origin-back";

export default function LlmExchangePage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8">
      <header className="mb-4">
        <h1 className="text-lg font-semibold text-text-primary">Trace · LLM Exchange</h1>
        <p className="mono mt-0.5 text-xs text-text-muted">{runId}</p>
        <Suspense fallback={null}>
          <OriginBackLink fallback={`/cockpit/trace/${encodeURIComponent(runId)}`} fallbackLabel="the governance record" testId="llm-exchange-back" />
        </Suspense>
      </header>
      <Suspense fallback={null}>
        <LlmExchangeView runId={runId} />
      </Suspense>
    </main>
  );
}
