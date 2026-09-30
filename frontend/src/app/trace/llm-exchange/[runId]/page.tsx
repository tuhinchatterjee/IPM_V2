"use client";

/**
 * Trace > LLM Exchange for one Cockpit run. Reached from the governance
 * record (`/cockpit/trace/[runId]`) and from the AI Model Lab.
 */

import { use } from "react";
import Link from "next/link";

import { LlmExchangeView } from "@/components/llm-exchange/llm-exchange-view";

export default function LlmExchangePage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8">
      <header className="mb-4">
        <h1 className="text-lg font-semibold text-text-primary">Trace · LLM Exchange</h1>
        <p className="mono mt-0.5 text-xs text-text-muted">{runId}</p>
        <Link href={`/cockpit/trace/${encodeURIComponent(runId)}`} className="text-xs text-accent underline">
          Back to the governance record
        </Link>
      </header>
      <LlmExchangeView runId={runId} />
    </main>
  );
}
