"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  RegulatoryAudit,
  RegulatoryConflicts,
  RegulatoryCorrections,
  RegulatoryDrafts,
  RegulatoryRequirements,
  RegulatoryRuns,
  RegulatorySchema,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Analysis Studio → Regulatory Intelligence. §27, §38.
 *
 * Why it lives here and not in the AI Intelligence Studio
 * -------------------------------------------------------
 * §27 splits the ownership and the split is not cosmetic. Analysis Studio
 * owns the source library, the extracted requirements and the promotion into
 * methods. The AI Intelligence Studio owns what the bank LEARNED from them —
 * teaching cases, ontology updates, the Regulatory Release.
 *
 * One screen for both would let a source circular and a certified method
 * look like the same kind of object, which §27 forbids in as many words. The
 * failure it prevents is a bank telling its regulator that a rule is
 * implemented when what actually happened is that somebody uploaded a PDF.
 *
 * Eight tabs
 * ----------
 *   DOCUMENTS          the library, with what kind of instrument each is
 *   PROCESSING         where each document is in the sixteen-stage pipeline
 *   REQUIREMENTS       what the clauses require, and how much was reviewed
 *   REVIEW             one requirement at a time: source, then our reading
 *   CONFLICTS          what disagrees with what, and how it was settled
 *   METHOD CANDIDATES  drafts waiting on five gates. None of them applied
 *   RELEASES           the frozen sets production retrieves from
 *   AUDIT              who decided what, on what basis
 *
 * The one thing this screen must never blur
 * ------------------------------------------
 * AMBIGUOUS is not NOT RELEVANT. A clause that matched no credit cue is
 * waiting for a person, and rendering the two the same way would let a
 * reviewer skim past the clauses whose wording we happened not to recognise
 * — which is exactly the set worth reading.
 */

const TABS = [
  [
    "documents",
    "Documents",
    "The regulatory library: what kind of instrument each document is, who " +
      "it binds, and over what dates.",
  ],
  [
    "processing",
    "Processing",
    "Where each document is in the sixteen-stage pipeline. Nothing reaches " +
      "a live answer before the release stage.",
  ],
  [
    "requirements",
    "Requirements",
    "What the clauses require and what each would touch here. Deferred " +
      "requirements are not counted as reviewed.",
  ],
  [
    "review",
    "Review",
    "One requirement at a time: the regulator's words first, then " +
      "CreditProbe's reading of them, then what disagrees.",
  ],
  [
    "conflicts",
    "Conflicts",
    "Where two regulatory positions cannot both be applied as written, and " +
      "how each was settled. Never by deleting one.",
  ],
  [
    "methods",
    "Method candidates",
    "Draft changes waiting on validation, regression, approval, version and " +
      "release. None of them has changed anything.",
  ],
  [
    "corrections",
    "Corrections",
    "What CreditProbe read, what a reviewer said instead, and both kept. " +
      "One person's correction is not the bank's position.",
  ],
  [
    "audit",
    "Audit",
    "What this document required, who decided what it meant, on what basis, " +
      "and what changed here as a result.",
  ],
] as const;

type TabId = (typeof TABS)[number][0];

export default function RegulatoryIntelligencePage() {
  const [tab, setTab] = React.useState<TabId>("requirements");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Regulatory Intelligence"
        description={
          "What the regulations require, what CreditProbe understands them " +
          "to mean, and what a person decided when the two differed."
        }
      />

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

      <Panel key={tab} tab={tab} />
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <Card className="p-4 text-xs text-muted-foreground">{children}</Card>;
}

/** A confidence, with what was missing behind it rather than a bare number. */
function Confidence({ value, because }: { value: number; because: string[] }) {
  const missing = because.filter((one) => one.startsWith("missing"));
  return (
    <details className="text-[11px]">
      <summary className="cursor-pointer text-muted-foreground">
        Interpretation confidence{" "}
        <span className="font-medium tabular-nums text-foreground">
          {value.toFixed(2)}
        </span>
        {missing.length > 0 && ` — ${missing.length} thing(s) missing`}
      </summary>
      <ul className="mt-1 space-y-0.5 pl-3 text-muted-foreground">
        {because.map((one) => (
          <li key={one}>{one}</li>
        ))}
      </ul>
    </details>
  );
}

function Panel({ tab }: { tab: TabId }) {
  const [state, setState] = React.useState<{
    schema?: RegulatorySchema;
    runs?: RegulatoryRuns;
    requirements?: RegulatoryRequirements;
    conflicts?: RegulatoryConflicts;
    drafts?: RegulatoryDrafts;
    corrections?: RegulatoryCorrections;
    audit?: RegulatoryAudit;
  } | null>(null);
  const [failed, setFailed] = React.useState("");

  React.useEffect(() => {
    let live = true;

    const load = async () => {
      switch (tab) {
        case "documents":
          return { schema: await api.regulatorySchema() };
        case "processing":
          return { runs: await api.regulatoryRuns() };
        case "requirements":
        case "review":
          return {
            requirements: await api.regulatoryRequirements(),
            schema: await api.regulatorySchema(),
          };
        case "conflicts":
          return { conflicts: await api.regulatoryConflicts() };
        case "methods":
          return { drafts: await api.regulatoryDrafts() };
        case "corrections":
          return { corrections: await api.regulatoryCorrections() };
        case "audit":
          return { audit: await api.regulatoryAudit() };
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
  }, [tab]);

  if (state === null) return <Skeleton className="h-48 w-full" />;
  if (failed) return <Empty>{failed}</Empty>;

  if (tab === "documents" && state.schema)
    return <Documents schema={state.schema} />;
  if (tab === "processing" && state.runs)
    return <Processing data={state.runs} />;
  if ((tab === "requirements" || tab === "review") && state.requirements)
    return (
      <Requirements
        data={state.requirements}
        schema={state.schema}
        oneByOne={tab === "review"}
      />
    );
  if (tab === "conflicts" && state.conflicts)
    return <Conflicts data={state.conflicts} />;
  if (tab === "methods" && state.drafts) return <Methods data={state.drafts} />;
  if (tab === "corrections" && state.corrections)
    return <Corrections data={state.corrections} />;
  if (tab === "audit" && state.audit) return <Audit data={state.audit} />;
  return <Empty>Nothing to show here yet.</Empty>;
}

// ---------------------------------------------------------------- DOCUMENTS

function Documents({ schema }: { schema: RegulatorySchema }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">
          What kind of instrument a document is
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Stated, never guessed from the filename. A supervisory letter and a
          published rulebook have different confidentiality, different authority
          and different audiences, and a PDF called
          &ldquo;circular_2026.pdf&rdquo; could be either.
        </p>
        <ul className="mt-3 space-y-1.5 text-xs">
          {schema.document_types.map((one) => (
            <li key={one.id}>
              <span className="font-medium">{one.id}</span>{" "}
              <span className="text-muted-foreground">— {one.means}</span>
              {schema.never_in_force.includes(one.id) && (
                <span className="ml-1 text-amber-700 dark:text-amber-400">
                  Never in force, whatever its dates say.
                </span>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card className="border-l-2 border-l-emerald-500/60 p-4">
        <h2 className="text-sm font-medium">The rules this area works under</h2>
        <ul className="mt-2 space-y-2 text-xs text-muted-foreground">
          {Object.entries(schema.rules).map(([key, means]) => (
            <li key={key}>{means}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------- PROCESSING

function Processing({ data }: { data: RegulatoryRuns }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">The pipeline</h2>
        <ol className="mt-2 space-y-1 text-[11px]">
          {data.pipeline.map((stage, index) => (
            <li key={stage.stage} className="flex gap-2">
              <span className="w-5 shrink-0 tabular-nums text-muted-foreground">
                {index + 1}.
              </span>
              <span>
                <span
                  className={cn(
                    "font-medium",
                    stage.quarantined && "text-amber-700 dark:text-amber-400",
                  )}
                >
                  {stage.stage}
                </span>
                {stage.optional && (
                  <span className="ml-1 text-muted-foreground">(optional)</span>
                )}
                <span className="block text-muted-foreground">
                  {stage.means}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </Card>

      {data.runs.length === 0 ? (
        <Empty>No document has been processed yet.</Empty>
      ) : (
        data.runs.map((run) => (
          <Card key={run.run_id} className="p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="font-mono text-xs">{run.document_id}</h3>
              <span className="text-[11px] text-muted-foreground">
                {run.stage}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {run.stage_means}
            </p>
            <p className="mt-2 text-[11px]">
              Reachable from a live answer:{" "}
              <span className="font-medium">
                {run.retrievable ? "Yes" : "No"}
              </span>
            </p>
            {run.blockers.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[11px] text-destructive">
                {run.blockers.map((one) => (
                  <li key={one}>{one}</li>
                ))}
              </ul>
            )}
          </Card>
        ))
      )}
    </div>
  );
}

// ------------------------------------------------------------- REQUIREMENTS

function Requirements({
  data,
  schema,
  oneByOne,
}: {
  data: RegulatoryRequirements;
  schema?: RegulatorySchema;
  oneByOne: boolean;
}) {
  const pending = data.requirements.filter((one) => !one.decision);
  const shown = oneByOne ? pending.slice(0, 1) : data.requirements;

  if (data.requirements.length === 0) {
    return <Empty>No requirements have been extracted yet.</Empty>;
  }
  if (oneByOne && shown.length === 0) {
    return (
      <Empty>
        Every requirement has a decision. {data.progress.parked} were deferred
        or sent for a second review — those are not counted as reviewed, and
        they are still waiting.
      </Empty>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">How much has actually been read</h2>
        <div className="mt-2 flex flex-wrap gap-4 text-xs">
          {(
            [
              ["Reviewed", data.progress.reviewed],
              ["Deferred or second review", data.progress.parked],
              ["Untouched", data.progress.untouched],
              ["Total", data.progress.total],
            ] as [string, number][]
          ).map(([label, value]) => (
            <span key={label}>
              <span className="text-muted-foreground">{label}: </span>
              <span className="font-medium tabular-nums">{value}</span>
            </span>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          {data.progress.note}
        </p>
      </Card>

      {shown.map((one) => (
        <Card key={one.requirement_id} className="space-y-3 p-4">
          {/* SOURCE first, always. A reviewer shown our reading before the
              regulator's sentence is reviewing the reading. */}
          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
              Source
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {one.citation.cited
                ? `Page ${one.citation.page || "—"}, section ${
                    one.citation.section_number || "—"
                  }${one.citation.paragraph ? `, ¶${one.citation.paragraph}` : ""}`
                : "No page, section or paragraph — this requirement cannot be released."}
            </p>
            <blockquote className="mt-2 border-l-2 border-border pl-3 text-xs">
              {one.excerpt}
              {one.excerpt_truncated && (
                <span className="text-muted-foreground"> [excerpt cut]</span>
              )}
            </blockquote>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
              CreditProbe&rsquo;s reading — not the regulator&rsquo;s
            </p>
            <p className="mt-1 text-xs">{one.summary}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="rounded bg-muted px-1.5 py-0.5">
                {one.requirement_type}
              </span>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5",
                  one.relevance === "AMBIGUOUS"
                    ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                    : "bg-muted",
                )}
              >
                {one.relevance === "AMBIGUOUS"
                  ? "AMBIGUOUS — waiting for a person, not dismissed"
                  : one.relevance}
              </span>
              {one.topics.map((topic) => (
                <span key={topic} className="text-muted-foreground">
                  {topic}
                </span>
              ))}
            </div>
            <div className="mt-2">
              <Confidence
                value={one.interpretation_confidence}
                because={one.confidence_because}
              />
            </div>
          </div>

          {one.decision ? (
            <p className="border-t border-border/40 pt-3 text-[11px]">
              <span className="font-medium">{one.decision}</span> by{" "}
              {one.reviewer} — {one.decision_reason}
            </p>
          ) : (
            <div className="border-t border-border/40 pt-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Actions
              </p>
              <ul className="mt-1 space-y-1 text-[11px]">
                {(schema?.review_actions ?? []).map((action) => (
                  <li key={action.id}>
                    <span className="font-medium">{action.id}</span>{" "}
                    <span className="text-muted-foreground">
                      — {action.means}
                    </span>
                    {!action.counts_as_reviewed && (
                      <span className="text-amber-700 dark:text-amber-400">
                        {" "}
                        Does not count as reviewed.
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- CONFLICTS

function Conflicts({ data }: { data: RegulatoryConflicts }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">How a contradiction may end</h2>
        <ul className="mt-2 space-y-1.5 text-xs">
          {data.resolutions.map((one) => (
            <li key={one.id}>
              <span className="font-medium">{one.id}</span>{" "}
              <span className="text-muted-foreground">— {one.means}</span>
              {one.needs_date && (
                <span className="text-muted-foreground">
                  {" "}
                  Requires the date it takes effect.
                </span>
              )}
              {one.leaves_it_open && (
                <span className="text-amber-700 dark:text-amber-400">
                  {" "}
                  Leaves the conflict open.
                </span>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-muted-foreground">{data.note}</p>
      </Card>

      {data.conflicts.length === 0 ? (
        <Empty>
          No contradiction has been detected. Nothing extracted so far disagrees
          with what is already here.
        </Empty>
      ) : (
        data.conflicts.map((one) => (
          <Card key={one.contradiction_id} className="p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-medium">{one.conflict_class}</h3>
              <span className="text-[11px] text-muted-foreground">
                {one.severity}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{one.summary}</p>
            <p className="mt-2 text-[11px] text-muted-foreground">
              {one.class_means}
            </p>
            <p className="mt-3 border-t border-border/40 pt-3 text-[11px]">
              {one.resolved ? (
                <>
                  <span className="font-medium">{one.resolution}</span> by{" "}
                  {one.resolved_by} — {one.resolution_reason}
                  {one.effective_from && ` (from ${one.effective_from})`}
                </>
              ) : (
                <span className="text-amber-700 dark:text-amber-400">
                  Not settled. {one.available_resolutions.length} governed
                  resolution(s) available.
                </span>
              )}
            </p>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------- METHODS

function Methods({ data }: { data: RegulatoryDrafts }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">
          What a draft has to clear before it is anything but a proposal
        </h2>
        <ul className="mt-2 space-y-1 text-xs">
          {data.gates.map((one) => (
            <li key={one.id}>
              <span className="font-medium">{one.id}</span>{" "}
              <span className="text-muted-foreground">— {one.means}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-muted-foreground">{data.note}</p>
      </Card>

      {data.drafts.length === 0 ? (
        <Empty>
          No requirement has been promoted. Approving one creates drafts here;
          it does not change anything.
        </Empty>
      ) : (
        data.drafts.map((one) => (
          <Card key={one.draft_id} className="p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-medium">{one.target}</h3>
              <span className="text-[11px] text-muted-foreground">
                {one.status}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{one.summary}</p>
            <p className="mt-2 text-[11px]">
              In production:{" "}
              <span className="font-medium">
                {one.applied ? "Yes" : "No — nothing has changed"}
              </span>
            </p>
            {one.outstanding_gates.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                {one.outstanding_gates.map((gate) => (
                  <li key={gate}>Outstanding — {gate}</li>
                ))}
              </ul>
            )}
            {one.certification?.why != null && (
              <p className="mt-2 border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
                {String(one.certification.why)}
              </p>
            )}
          </Card>
        ))
      )}
    </div>
  );
}

// ------------------------------------------------------------- CORRECTIONS

function Corrections({ data }: { data: RegulatoryCorrections }) {
  if (data.corrections.length === 0) {
    return (
      <Empty>
        Nobody has corrected a reading yet. That is not the same as every
        reading being right.
      </Empty>
    );
  }
  return (
    <div className="space-y-4">
      <Empty>{data.note}</Empty>
      {data.corrections.map((one) => (
        <Card key={one.correction_id} className="p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                We read it as
              </p>
              <p className="mt-1 text-xs">{one.we_read_it_as}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Confidence {one.our_confidence.toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {one.by} read it as
              </p>
              <p className="mt-1 text-xs">{one.they_read_it_as}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {one.role} — {one.reason}
              </p>
            </div>
          </div>
          <p className="mt-3 border-t border-border/40 pt-2 text-[11px]">
            {one.authoritative
              ? "Released as the bank's position."
              : "Not authoritative. One reviewer's correction is not the bank's position until it has been through review, regression and release."}
          </p>
        </Card>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------- AUDIT

function Audit({ data }: { data: RegulatoryAudit }) {
  return (
    <div className="space-y-4">
      <Empty>{data.answers}</Empty>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Decisions</h2>
        {data.decisions.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            Nothing has been decided yet.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border/40 text-xs">
            {data.decisions.map((one) => (
              <li key={one.requirement_id} className="py-2">
                <p className="font-medium">{one.summary}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  Page {one.page || "—"}, section {one.section || "—"} ·{" "}
                  {one.decision} by {one.reviewer} · confidence{" "}
                  {one.confidence.toFixed(2)} · v{one.version}
                </p>
                <p className="mt-0.5 text-[11px]">{one.reason}</p>
              </li>
            ))}
          </ul>
        )}
        {data.undecided.length > 0 && (
          <p className="mt-3 text-[11px] text-amber-700 dark:text-amber-400">
            {data.undecided.length} requirement(s) still have no decision.
          </p>
        )}
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">
          Corrections, contradictions and drafts
        </h2>
        <div className="mt-2 flex flex-wrap gap-4 text-xs">
          {(
            [
              ["Corrections", data.corrections.length],
              ["Contradictions", data.contradictions.length],
              ["Drafts", data.drafts.length],
              ["Processing runs", data.runs.length],
            ] as [string, number][]
          ).map(([label, value]) => (
            <span key={label}>
              <span className="text-muted-foreground">{label}: </span>
              <span className="font-medium tabular-nums">{value}</span>
            </span>
          ))}
        </div>
      </Card>
    </div>
  );
}
