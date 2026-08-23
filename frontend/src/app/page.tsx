import Link from "next/link";
import { ArrowRight, CheckCircle2, Circle, CircleDashed } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { BackendStatusPanel } from "@/components/system/backend-status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  NAV_GROUPS,
  STATUS_LABEL,
  type CapabilityStatus,
  itemsInGroup,
} from "@/lib/navigation";

const STATUS_ICON: Record<CapabilityStatus, typeof Circle> = {
  live: CheckCircle2,
  partial: CircleDashed,
  preview: CircleDashed,
  planned: Circle,
};

const STATUS_TONE: Record<CapabilityStatus, string> = {
  live: "text-positive",
  partial: "text-accent",
  preview: "text-warning",
  planned: "text-text-muted",
};

/**
 * The landing page.
 *
 * Deliberately a clean, honest overview rather than a fake dashboard. It shows
 * what IPM is, what is actually working right now, and what each area will be —
 * which is the right first impression for an audience that will immediately test
 * whether the product is real.
 */
export default function Home() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="Credit Portfolio Intelligence & Monitoring"
        description="An AI-native credit-risk analytical platform. The language model interprets the question, plans the investigation and writes the explanation. Every figure is produced by a deterministic, versioned, tested engine — and every result is fully traceable."
        status="partial"
        phase="Phase 1 — Foundations"
      />

      {/* The governing rule, stated plainly. It is the product's central claim, so
          it belongs on the first screen rather than buried in documentation. */}
      <Card className="border-accent/30 bg-accent-muted/40">
        <CardHeader>
          <CardTitle>The governing rule</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 sm:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
              The language model
            </p>
            <p className="text-sm leading-relaxed text-text-secondary">
              Understands the question, interprets intent, builds an investigation plan,
              chooses approved IPM analyses, selects parameters, interprets the results
              and writes the narrative.
            </p>
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
              The IPM Engine
            </p>
            <p className="text-sm leading-relaxed text-text-secondary">
              Retrieves, filters and aggregates data; computes portfolio metrics,
              migrations, transition matrices, ECL attribution, deterioration and stress
              outcomes. Deterministic, versioned and tested.
            </p>
          </div>
          <p className="text-sm font-medium text-text-primary sm:col-span-2">
            The model can order from the menu. It cannot cook. No material number in IPM
            is produced by a language model.
          </p>
        </CardContent>
      </Card>

      <BackendStatusPanel />

      <section>
        <h2 className="mb-1 text-sm font-semibold tracking-tight text-text-primary">
          Capabilities
        </h2>
        <p className="mb-5 text-sm text-text-muted">
          Every area of the product, with its honest current state. Nothing here is
          presented as finished before it is.
        </p>

        <div className="space-y-8">
          {NAV_GROUPS.map((group) => (
            <div key={group}>
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                {group}
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                {itemsInGroup(group).map((item) => {
                  const Icon = item.icon;
                  const StatusIcon = STATUS_ICON[item.status];
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="group flex gap-3 rounded-lg border border-border bg-surface p-4 transition-colors hover:bg-surface-hover"
                    >
                      <Icon className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-text-primary">
                            {item.label}
                          </span>
                          <StatusIcon
                            className={`size-3 ${STATUS_TONE[item.status]}`}
                            aria-hidden
                          />
                          <span className="text-[11px] text-text-muted">
                            {STATUS_LABEL[item.status]}
                            {item.status !== "live" ? ` · ${item.phase}` : ""}
                          </span>
                          <ArrowRight
                            className="ml-auto size-3.5 shrink-0 text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
                            aria-hidden
                          />
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-text-muted">
                          {item.description}
                        </p>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold tracking-tight text-text-primary">
          What Phase 1 delivered
        </h2>
        <p className="mb-5 text-sm text-text-muted">
          The foundation everything else is built on. None of it is visible on screen,
          and all of it is load-bearing.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          {[
            {
              title: "Three-layer analytical store",
              body: "The source workbook is converted to Parquet across raw, curated and analytics layers, partitioned by reporting period.",
            },
            {
              title: "Data Access Layer over DuckDB",
              body: "The engine asks for governed datasets by name. Filtering and aggregation are pushed down into DuckDB; only summaries cross into Python. Storage is swappable without touching a calculation.",
            },
            {
              title: "Governed data catalogue",
              body: "65 fields with the source system's own published definitions, types, units and sensitivity — the single definition of every field in IPM.",
            },
            {
              title: "Engine registry and contracts",
              body: "Every analysis declares its datasets, parameters, outputs, validation rules, owner, version and certification. Unknown analyses and bad parameters are rejected before anything runs.",
            },
            {
              title: "Trace graph with content hashing",
              body: "Nodes, edges, layered layout, and hashes that identify exactly which steps a change affects — the mechanism behind editable Trace.",
            },
            {
              title: "PostgreSQL governance schema",
              body: "26 tables: projects, chats, analysis runs, trace versions, engine and data catalogue definitions, stress scenarios and workflow.",
            },
          ].map((item) => (
            <Card key={item.title}>
              <CardHeader className="pb-3">
                <CardTitle>{item.title}</CardTitle>
                <CardDescription className="text-xs leading-relaxed">
                  {item.body}
                </CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>A note on the data</CardTitle>
          <CardDescription className="leading-relaxed">
            The bundled portfolio is <Badge variant="warning">synthetic</Badge> — 6,599
            facility positions across ten quarterly reporting periods from Q4 2023 to
            Q1 2026. The calculations run against it are real; the underlying figures are
            not a real bank&apos;s. Every dataset carries this flag through the catalogue,
            and the interface labels it wherever its numbers appear.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
