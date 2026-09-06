"use client";

/**
 * What-If Analysis — the landing page.
 *
 * The order is deliberate and is the product's own: the heading, the composer,
 * the six guided starting points, Saved What-Ifs, Model Configuration, Recent
 * What-Ifs.
 *
 * The composer comes FIRST because it is the principal way in. The six cards
 * below it are shortcuts, not a menu — a person can ignore all six and type
 * "downgrade construction borrowers above SAR 100m by two notches and increase
 * LGD five points", which no card covers and the engine handles.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Unavailable } from "@/components/ui/unavailable";
import { Composer, money, signed } from "@/components/whatif/parts";
import type { WhatIfCard } from "@/lib/api";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

const EXAMPLES = [
  "What happens if Stage 1 PD increases 20%?",
  "Downgrade construction borrowers with exposure above SAR 100m by two notches.",
  "Move half the Stage 1 BBB borrowers to Stage 2 and increase LGD by five percentage points.",
  "Show Stage 1 PD by sector.",
];

function ScenarioCard({ card }: { card: WhatIfCard }) {
  const worse = (card.percentage_change ?? 0) > 0;
  return (
    <Link
      href={`/what-if/thread?saved=${card.id}`}
      data-saved-id={card.id}
      className="block rounded-md border border-border bg-surface p-3 transition-colors hover:border-accent hover:bg-surface-hover"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-[13px] font-medium text-text-primary">
          {card.name}
        </span>
        <Badge variant="outline">{card.period}</Badge>
      </div>
      <p className="mt-1 line-clamp-2 text-[11px] text-text-secondary">{card.scenario}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span className="text-text-muted">
          {money(card.baseline_ecl, card.currency)} →{" "}
          <span className="text-text-primary">{money(card.whatif_ecl, card.currency)}</span>
        </span>
        <span className={worse ? "text-negative" : "text-positive"}>
          {signed(card.percentage_change)}
        </span>
        {card.ecl_methodology ? (
          <Badge variant="info">{card.ecl_methodology}</Badge>
        ) : null}
      </div>
    </Link>
  );
}

export default function WhatIfLandingPage() {
  const router = useRouter();
  const landing = useAsync(() => api.whatIfLanding(), []);
  const [question, setQuestion] = React.useState("");

  const ask = React.useCallback(() => {
    const said = question.trim();
    if (!said) return;
    router.push(`/what-if/thread?q=${encodeURIComponent(said)}`);
  }, [question, router]);

  const data = landing.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Intelligence"
        title="What-If Analysis"
        description="Change a risk assumption and see what it does to ECL, and why. Every scenario runs on the Corporate IFRS 9 book, borrower by borrower, against the staging criteria and the ECL methodology the answer names."
      />

      <Unavailable state={landing} what="What-If Analysis" />

      {data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-[18px]">What-If</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Composer
                value={question}
                onChange={setQuestion}
                onSubmit={ask}
                placeholder="Describe a change to the book — or ask about it."
                suggestions={EXAMPLES}
              />
              <p className="text-[11px] text-text-muted">{data.restriction}</p>
            </CardContent>
          </Card>

          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-text-primary">
              Start from a guided scenario
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.journeys.map((journey) => (
                <Link
                  key={journey.key}
                  href={`/what-if/thread?journey=${journey.key}`}
                  data-journey={journey.key}
                  className="rounded-md border border-border bg-surface p-4 transition-colors hover:border-accent hover:bg-surface-hover"
                >
                  <div className="text-[13px] font-medium text-text-primary">
                    {journey.title}
                  </div>
                  <p className="mt-1 text-[12px] text-text-secondary">{journey.summary}</p>
                </Link>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-text-muted">
              These are shortcuts, not restrictions. You can combine several in one
              instruction in the box above.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-text-primary">
              Saved What-Ifs
            </h2>
            {data.persistence.available ? (
              data.saved.length ? (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {data.saved.map((card) => (
                    <ScenarioCard key={card.id} card={card} />
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="Nothing saved yet"
                  description="Run a What-If and choose Save to keep it here, with the scenario, the staging criteria and the methodology that produced it."
                />
              )
            ) : (
              <p className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-[12px] text-text-secondary">
                {data.persistence.unavailable_message}
              </p>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-text-primary">
              Model configuration
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Link
                href="/what-if/models/delta"
                data-model="delta"
                className="rounded-md border border-border bg-surface p-4 transition-colors hover:border-accent hover:bg-surface-hover"
              >
                <div className="text-[13px] font-medium text-text-primary">Delta Model</div>
                <p className="mt-1 text-[12px] text-text-secondary">
                  Transparent deterministic sensitivity: the reported ECL moved by the
                  PD, LGD and EAD factors the scenario implies.
                </p>
              </Link>
              <Link
                href="/what-if/models/ml"
                data-model="ml"
                className="rounded-md border border-border bg-surface p-4 transition-colors hover:border-accent hover:bg-surface-hover"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-text-primary">
                    ML Model — XGBoost
                  </span>
                  <Badge
                    variant={
                      data.models.methods.find((m) => m.key === "ml")?.available
                        ? "positive"
                        : "warning"
                    }
                  >
                    {data.models.methods.find((m) => m.key === "ml")?.available
                      ? `v${data.models.methods.find((m) => m.key === "ml")?.version}`
                      : "not trained"}
                  </Badge>
                </div>
                <p className="mt-1 text-[12px] text-text-secondary">
                  A nonlinear response learned from historical Corporate IFRS 9
                  outcomes, anchored to the official baseline ECL.
                </p>
              </Link>
            </div>
            <p className="mt-2 text-[11px] text-text-muted">{data.models.gate}</p>
          </section>

          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-text-primary">
              Recent What-Ifs
            </h2>
            {data.recent.length ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {data.recent.map((card) => (
                  <ScenarioCard key={card.id} card={card} />
                ))}
              </div>
            ) : (
              <EmptyState
                title="No recent runs"
                description="Scenarios you run appear here even if you do not save them."
              />
            )}
          </section>

          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={landing.reload}>
              Refresh
            </Button>
          </div>
        </>
      ) : null}
    </div>
  );
}
