"use client";

import Link from "next/link";
import { ArrowRight, LayoutGrid, Lock } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

/**
 * Lens library.
 *
 * A Lens is a saved arrangement of governed analytical outputs with fixed
 * filters. The CRO Lens is built; the others are named so the pattern is clear
 * and are marked as not yet composed.
 */

const LENSES = [
  {
    id: "cro",
    name: "CRO Portfolio Lens",
    description:
      "The monthly executive view: position, staging, coverage, concentration, migration and the names driving deterioration.",
    audience: "Chief Risk Officer · Board Risk Committee",
    tiles: 7,
    live: true,
  },
  {
    id: "ifrs9",
    name: "IFRS 9 Review",
    description:
      "Impairment attribution, staging and coverage by stage, with overlay usage for the IFRS 9 Committee.",
    audience: "IFRS 9 Committee",
    tiles: 5,
    live: false,
  },
  {
    id: "sector",
    name: "Sector Committee",
    description:
      "Concentration, single-name risk and sector deterioration, with downturn sensitivity per sector.",
    audience: "Sector Credit Committee",
    tiles: 6,
    live: false,
  },
];

export default function LensesPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Lenses"
        description="Saved executive views. Each tile is a governed engine result with its own Trace, so a Lens is a arrangement of real analysis rather than a snapshot."
        status="live"
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {LENSES.map((lens) => {
          const body = (
            <Card
              className={`flex h-full flex-col p-5 transition-colors ${
                lens.live ? "hover:bg-surface-hover" : "opacity-70"
              }`}
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <LayoutGrid className="size-5 text-text-muted" aria-hidden />
                {lens.live ? (
                  <Badge variant="positive">Live</Badge>
                ) : (
                  <Badge variant="default">
                    <Lock className="size-3" aria-hidden />
                    Not composed
                  </Badge>
                )}
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{lens.name}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">
                {lens.description}
              </p>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                <span className="text-[11px] text-text-muted">{lens.audience}</span>
                {lens.live && (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-accent">
                    Open
                    <ArrowRight className="size-3" aria-hidden />
                  </span>
                )}
              </div>
            </Card>
          );
          return lens.live ? (
            <Link key={lens.id} href={`/lenses/${lens.id}`}>
              {body}
            </Link>
          ) : (
            <div key={lens.id}>{body}</div>
          );
        })}
      </div>
    </div>
  );
}
