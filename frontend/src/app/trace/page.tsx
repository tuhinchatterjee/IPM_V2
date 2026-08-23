"use client";

import Link from "next/link";
import { GitBranch, Info } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

/**
 * Trace landing.
 *
 * A trace belongs to a specific analysis run, so this page explains what Trace
 * is and points at where traces are reached from — every analytical result — 
 * rather than listing runs out of context.
 */
export default function TracePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Trace & Lineage"
        description="How a particular analysis was created. Not an audit log — an inspectable record of every step from question to chart, emitted by the execution itself."
        status="partial"
        phase="Interactive graph next"
      />

      <Card className="p-6">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">The design rule</h3>
        <p className="max-w-3xl text-sm leading-relaxed text-text-secondary">
          Trace is emitted <strong>by</strong> execution. It is never written afterwards, and it
          is never written by a language model. Each step stamps its own card as it runs — which
          dataset, which variables, which filters, how many rows before and after, which function
          at which version, how long it took. The graph <em>is</em> the execution record, so it
          cannot drift from the truth.
        </p>
      </Card>

      <Card className="flex items-start gap-2.5 border-info/30 bg-info-muted p-4 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          Every analytical result in IPM carries a Trace button in its top-right corner. Open any
          result — a Cockpit card, a CRO Lens tile, an investigation step — and press Trace to see
          the graph behind that specific figure.
        </span>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" asChild>
          <Link href="/lenses/cro">
            <GitBranch aria-hidden />
            Open the CRO Lens
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/analysis/stage_migration?params=%7B%22from_period%22%3A%22previous%22%2C%22to_period%22%3A%22latest%22%7D">
            Run an analysis
          </Link>
        </Button>
      </div>

      <Card className="p-6">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">What arrives next</h3>
        <ul className="space-y-2 text-sm text-text-secondary">
          {[
            "A pannable, zoomable graph with every node clickable to a full inspection panel",
            "Governed nodes drawn distinctly from interpretive ones, so the boundary between engine and model is visible",
            'An "Ask / Modify Trace" prompt that accepts a plain-English change and previews exactly which nodes it affects',
            "Branching to a new version, re-running only the affected steps and preserving the original",
          ].map((line) => (
            <li key={line} className="flex gap-2">
              <span aria-hidden className="text-text-muted">·</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-text-muted">
          The graph model, content hashing and version storage are already built and are what the
          detail view below reads. Only the interactive canvas is outstanding.
        </p>
      </Card>
    </div>
  );
}
