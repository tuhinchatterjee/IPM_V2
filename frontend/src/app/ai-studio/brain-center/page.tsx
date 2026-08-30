"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  BrainConflictList,
  BrainExportKinds,
  BrainImportList,
  BrainInstallationList,
  BrainLedger,
  BrainOverview,
  BrainSecurity,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The Brain Center. §25.
 *
 * What this screen is for
 * -----------------------
 * CreditProbe learns constantly, and almost none of that learning is visible.
 * Without this screen a reviewer asked "what does this system know, where did
 * it come from, and has any of it been checked?" has no way to answer, and an
 * imported Brain is indistinguishable from a Brain that was always here.
 *
 * Eleven tabs, and why they are separate
 * --------------------------------------
 * They could be three. They are eleven because the questions are different
 * and collapsing them is how the answers get blurred:
 *
 *   CURRENT BRAIN   what is running here, now
 *   LEARNING LEDGER what has been learned, and how little of it is production
 *   EXPORT          what may leave, and in which of three shapes
 *   IMPORTS         what arrived, and how far through the pipeline it got
 *   QUARANTINE      what is sealed off, with nothing reachable from an answer
 *   LIFT LAB        what an import actually measured — or that it measured
 *                   nothing, which is a different fact from measuring zero
 *   MERGE LAB       what two Brains disagree about, before either wins
 *   INSTALLATIONS   §24's timeline
 *   ROLLBACKS       what was undone, and why
 *   COMPATIBILITY   what this receiver can and cannot run
 *   SECURITY        what is enforced, and whose signature is trusted
 *
 * The three numbers this screen refuses to add up
 * ------------------------------------------------
 * Learning CAPTURED, learning APPROVED and learning ACTIVATED. More capture
 * is not improvement, and a headline that summed them would read best on the
 * installation that had learned the least.
 */

const TABS = [
  [
    "current",
    "Current Brain",
    "What is running here now: versions, health, and what this installation " +
      "knows it does badly.",
  ],
  [
    "ledger",
    "Learning ledger",
    "Everything learned here, from any source. Captured, approved and " +
      "activated are three different numbers and are not added together.",
  ],
  [
    "export",
    "Export",
    "The three packages that may leave, what each is for, and what none of " +
      "them ever contains.",
  ],
  [
    "imports",
    "Imports",
    "Every package uploaded here and how far through the fifteen-stage " +
      "pipeline it got.",
  ],
  [
    "quarantine",
    "Quarantine",
    "What is sealed off from production. No candidate is in the retrieval " +
      "path until its installation is active.",
  ],
  [
    "lift",
    "Lift Lab",
    "What an import measured against this installation's own holdout — or " +
      "that it measured nothing, which is not the same as measuring zero.",
  ],
  [
    "merge",
    "Merge Lab",
    "Where an incoming Brain contradicts what is already here, and how each " +
      "contradiction was settled. Recency is never a reason.",
  ],
  [
    "installations",
    "Installations",
    "What Brain was integrated, when, by whom, and how much improvement it " +
      "produced.",
  ],
  [
    "rollbacks",
    "Rollbacks",
    "What was undone and why. A rollback is a record, not a reconstruction.",
  ],
  [
    "compatibility",
    "Compatibility",
    "What this receiver can run, what would run once something is installed, " +
      "and what cannot run here at all.",
  ],
  [
    "security",
    "Security",
    "What is enforced on every package, and which signing keys this " +
      "installation has decided to trust.",
  ],
] as const;

type TabId = (typeof TABS)[number][0];

export default function BrainCenterPage() {
  const [tab, setTab] = React.useState<TabId>("current");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Brain Center"
        description={
          "What CreditProbe knows, where it came from, and what changed when " +
          "somebody else's learning was brought in."
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

      {/* Keyed on the tab so switching REMOUNTS rather than clearing state
          inside an effect — starting from nothing cannot forget a field. */}
      <Panel key={tab} tab={tab} />
    </div>
  );
}

/** A row of label/value pairs. Used wherever the answer is short. */
function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="text-xs">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="mt-0.5 font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <Card className="p-4 text-xs text-muted-foreground">{children}</Card>;
}

function Panel({ tab }: { tab: TabId }) {
  const [state, setState] = React.useState<{
    overview?: BrainOverview;
    ledger?: BrainLedger;
    kinds?: BrainExportKinds;
    imports?: BrainImportList;
    conflicts?: BrainConflictList;
    installations?: BrainInstallationList;
    security?: BrainSecurity;
  } | null>(null);
  const [failed, setFailed] = React.useState("");

  React.useEffect(() => {
    let live = true;

    const load = async () => {
      switch (tab) {
        case "current":
          return { overview: await api.brainOverview() };
        case "ledger":
          return { ledger: await api.brainLedger() };
        case "export":
          return { kinds: await api.brainExportKinds() };
        case "imports":
        case "quarantine":
        case "lift":
        case "compatibility":
          return { imports: await api.brainImports() };
        case "merge":
          return { conflicts: await api.brainConflicts() };
        case "installations":
        case "rollbacks":
          return { installations: await api.brainInstallations() };
        case "security":
          return { security: await api.brainSecurity() };
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

  if (tab === "current" && state.overview)
    return <Current data={state.overview} />;
  if (tab === "ledger" && state.ledger) return <Ledger data={state.ledger} />;
  if (tab === "export" && state.kinds) return <Export data={state.kinds} />;
  if (tab === "merge" && state.conflicts)
    return <Merge data={state.conflicts} />;
  if (tab === "security" && state.security)
    return <Security data={state.security} />;
  if ((tab === "installations" || tab === "rollbacks") && state.installations) {
    return (
      <History data={state.installations} rollbacksOnly={tab === "rollbacks"} />
    );
  }
  if (state.imports) return <Imports data={state.imports} view={tab} />;
  return <Empty>Nothing to show here yet.</Empty>;
}

// ------------------------------------------------------------ CURRENT BRAIN

function Current({ data }: { data: BrainOverview }) {
  const installed = data.current.installed_brain;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">What is running</h2>
        <div className="mt-3">
          <Facts
            rows={[
              ["Ontology version", data.current.ontology_version],
              ["Package schema", data.current.package_schema_version],
              ["Ledger schema", data.current.ledger_schema_version],
              [
                "Imported Brain",
                installed
                  ? `${installed.brain} — ${installed.improvement}`
                  : "None. Everything running here was built here.",
              ],
            ]}
          />
        </div>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">The six dimensions</h2>
        <ul className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
          {data.dimensions.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Who may retrieve what</h2>
        <table className="mt-2 w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 text-left font-normal">Status</th>
              <th className="py-1 text-left font-normal">Retrievable</th>
              <th className="py-1 text-left font-normal">May tune</th>
            </tr>
          </thead>
          <tbody>
            {data.retrieval_policy.map((row) => (
              <tr key={row.status} className="border-t border-border/40">
                <td className="py-1 font-medium">{row.status}</td>
                <td className="py-1 text-muted-foreground">
                  {row.retrievable}
                </td>
                <td className="py-1 text-muted-foreground">{row.may_tune}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="border-l-2 border-l-amber-500/60 p-4">
        <h2 className="text-sm font-medium">Known limitations</h2>
        <ul className="mt-2 space-y-1.5 text-xs text-muted-foreground">
          {data.known_limitations.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------- LEARNING LEDGER

function Ledger({ data }: { data: BrainLedger }) {
  const census = data.census as Record<string, Record<string, number>>;
  return (
    <div className="space-y-4">
      {Object.entries(census).map(([group, counts]) =>
        counts && typeof counts === "object" ? (
          <Card key={group} className="p-4">
            <h2 className="text-sm font-medium capitalize">
              {group.replace(/_/g, " ")}
            </h2>
            <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-3">
              {Object.entries(counts).map(([key, value]) => (
                <li key={key} className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{key}</span>
                  <span className="font-medium tabular-nums">
                    {String(value)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null,
      )}

      <Card className="p-4">
        <h2 className="text-sm font-medium">
          What an entry must satisfy before it may leave
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          All ten. A missing check counts as failed — &ldquo;nobody
          looked&rdquo; and &ldquo;it passed&rdquo; are different, and
          defaulting the difference towards portable is how a client identifier
          leaves a building.
        </p>
        <ul className="mt-2 space-y-1 text-xs">
          {data.eligibility_conditions.map((one) => (
            <li key={one.check}>
              <span className="font-mono text-[11px]">{one.check}</span>{" "}
              <span className="text-muted-foreground">— {one.means}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Empty>{data.note}</Empty>
    </div>
  );
}

// ------------------------------------------------------------------- EXPORT

function Export({ data }: { data: BrainExportKinds }) {
  return (
    <div className="space-y-4">
      {data.kinds.map((kind) => (
        <Card key={kind.id} className="p-4">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-medium">{kind.label}</h2>
            <span className="font-mono text-[11px] text-muted-foreground">
              {kind.suffix}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{kind.purpose}</p>
          {kind.requires?.length ? (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Requires: {kind.requires.join(", ")}
            </p>
          ) : null}
        </Card>
      ))}

      <Card className="border-l-2 border-l-emerald-500/60 p-4">
        <h2 className="text-sm font-medium">What no package ever contains</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Checked at export as well as at import, so a package this installation
          would refuse to receive is one it refuses to build. Only cases at{" "}
          {data.exportable_case_status} leave here.
        </p>
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {data.never_included.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ------------------------------- IMPORTS / QUARANTINE / LIFT / COMPATIBILITY

function Imports({ data, view }: { data: BrainImportList; view: TabId }) {
  const rows =
    view === "quarantine"
      ? data.imports.filter((one) =>
          data.quarantined_stages.includes(one.stage),
        )
      : data.imports;

  if (rows.length === 0) {
    return (
      <Empty>
        {view === "quarantine"
          ? "Nothing is in quarantine."
          : "No Brain has been uploaded to this installation."}
      </Empty>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">The pipeline</h2>
        <ol className="mt-2 flex flex-wrap gap-1 text-[11px]">
          {data.pipeline.map((stage) => (
            <li
              key={stage}
              className={cn(
                "rounded px-1.5 py-0.5",
                data.quarantined_stages.includes(stage)
                  ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {stage}
            </li>
          ))}
        </ol>
        <p className="mt-2 text-xs text-muted-foreground">{data.note}</p>
      </Card>

      {rows.map((row) => (
        <ImportRow key={row.import_id} row={row} view={view} />
      ))}
    </div>
  );
}

function ImportRow({
  row,
  view,
}: {
  row: BrainImportList["imports"][number];
  view: TabId;
}) {
  const [detail, setDetail] = React.useState<Record<string, unknown> | null>(
    null,
  );

  React.useEffect(() => {
    if (view !== "lift" && view !== "compatibility") return;
    let live = true;
    const load =
      view === "lift"
        ? api.brainLift(row.import_id)
        : api.brainImport(row.import_id);
    load
      .then((found) => live && setDetail(found as Record<string, unknown>))
      .catch(() => live && setDetail({}));
    return () => {
      live = false;
    };
  }, [row.import_id, view]);

  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-mono text-xs">{row.import_id}</h3>
        <span className="text-[11px] text-muted-foreground">{row.state}</span>
      </div>
      <div className="mt-3">
        <Facts
          rows={[
            ["Stage", row.stage],
            ["Uploaded by", row.uploaded_by || "—"],
            [
              "Reachable from a live answer",
              row.retrievable ? "Yes" : "No — this Brain answers nothing",
            ],
            ["Blockers", row.blockers.length ? row.blockers.length : "None"],
          ]}
        />
      </div>
      {row.blockers.length > 0 && (
        <ul className="mt-3 space-y-1 text-[11px] text-muted-foreground">
          {row.blockers.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      )}
      {view === "lift" && detail && <Lift detail={detail} />}
      {view === "compatibility" && detail && <Compatibility detail={detail} />}
    </Card>
  );
}

function Lift({ detail }: { detail: Record<string, unknown> }) {
  const measured = detail.measured === true;
  if (!measured) {
    return (
      <p className="mt-3 border-t border-border/40 pt-3 text-xs text-muted-foreground">
        {String(detail.note ?? "Not measured.")}
      </p>
    );
  }
  const evaluation = (detail.evaluation ?? {}) as Record<string, unknown>;
  const dimensions = (evaluation.dimensions ?? []) as Record<string, unknown>[];
  return (
    <div className="mt-3 border-t border-border/40 pt-3">
      <p className="text-xs font-medium">{String(evaluation.headline ?? "")}</p>
      <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
        {dimensions.map((one) => (
          <li key={String(one.dimension)}>{String(one.reads_as ?? "")}</li>
        ))}
      </ul>
    </div>
  );
}

function Compatibility({ detail }: { detail: Record<string, unknown> }) {
  const report = (detail.compatibility ?? {}) as Record<string, unknown>;
  const findings = (report.findings ?? []) as Record<string, unknown>[];
  if (!report.summary) {
    return (
      <p className="mt-3 border-t border-border/40 pt-3 text-xs text-muted-foreground">
        Compatibility has not been checked for this package yet.
      </p>
    );
  }
  return (
    <div className="mt-3 border-t border-border/40 pt-3">
      <p className="text-xs font-medium">{String(report.summary)}</p>
      <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
        {findings.map((one) => (
          <li key={`${String(one.kind)}:${String(one.name)}`}>
            <span className="font-mono">{String(one.name)}</span> —{" "}
            {String(one.reason)}
            {one.fixable === true && " (would run once installed)"}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- MERGE LAB

function Merge({ data }: { data: BrainConflictList }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">How a contradiction may end</h2>
        <ul className="mt-2 flex flex-wrap gap-1 text-[11px]">
          {data.resolutions.map((one) => (
            <li key={one} className="rounded bg-muted px-1.5 py-0.5">
              {one}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">{data.note}</p>
      </Card>

      {data.conflicts.length === 0 ? (
        <Empty>
          No contradictory learning has been detected. Nothing has been imported
          that disagrees with what is already here.
        </Empty>
      ) : (
        data.conflicts.map((one) => (
          <Card key={one.conflict_id} className="p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-medium">{one.conflict_class}</h3>
              <span className="text-[11px] text-muted-foreground">
                {one.severity}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{one.summary}</p>
            <div className="mt-3">
              <Facts
                rows={[
                  ["Recommended", one.recommendation || "—"],
                  ["Because", one.recommendation_reason || "—"],
                  ["Settled as", one.resolution || "Not yet settled"],
                  ["By", one.resolved_by || "—"],
                ]}
              />
            </div>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------- INSTALLATIONS and ROLLBACKS

function History({
  data,
  rollbacksOnly,
}: {
  data: BrainInstallationList;
  rollbacksOnly: boolean;
}) {
  const rows = rollbacksOnly ? data.rollbacks : data.installations;
  if (rows.length === 0) {
    return (
      <Empty>
        {rollbacksOnly
          ? "Nothing has been rolled back."
          : "No Brain has been installed here. Everything running was built here."}
      </Empty>
    );
  }
  return (
    <div className="space-y-4">
      {!rollbacksOnly && (
        <p className="text-xs text-muted-foreground">{data.answers}</p>
      )}
      {rows.map((row) => (
        <Card key={row.installation_id} className="p-4">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">{row.brain}</h3>
            <span className="text-[11px] text-muted-foreground">
              {row.state}
            </span>
          </div>
          <p className="mt-1 text-xs">{row.improvement}</p>
          <div className="mt-3">
            <Facts
              rows={[
                ["Date", row.date || "—"],
                ["From", row.source_instance || "—"],
                ["Installed by", row.installed_by || "—"],
                [
                  "Approved by",
                  row.approved_by.length ? row.approved_by.join(", ") : "—",
                ],
                ["Components", row.components.length],
                ["Conflicts", row.conflicts.length],
                [
                  "Critical regressions",
                  row.critical_regressions.length
                    ? row.critical_regressions.join(", ")
                    : "None",
                ],
                ["Release", row.release_id || "—"],
              ]}
            />
          </div>
          {row.rollback_reason && (
            <p className="mt-3 border-t border-border/40 pt-3 text-xs text-muted-foreground">
              Rolled back {row.rolled_back_at}: {row.rollback_reason}
            </p>
          )}
        </Card>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------- SECURITY

function Security({ data }: { data: BrainSecurity }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">What is enforced</h2>
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {data.enforced.map((one) => (
            <li key={one}>{one}</li>
          ))}
        </ul>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Limits</h2>
        <div className="mt-3">
          <Facts
            rows={Object.entries(data.limits).map(([key, value]) => [
              key.replace(/_/g, " "),
              <span key={key} className="tabular-nums">
                {value.toLocaleString()}
              </span>,
            ])}
          />
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          Allowed formats: {data.allowed_formats.join(" ")}. An allowlist, not a
          blocklist — a blocklist is a list of the formats somebody thought of.
        </p>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Trusted signers</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {data.untrusted_signer_policy}
        </p>
        {data.signers.length === 0 ? (
          <p className="mt-3 text-xs text-muted-foreground">
            No signing key has been trusted here. Every uploaded package may be
            inspected and evaluated, and none may be activated.
          </p>
        ) : (
          <ul className="mt-3 space-y-2 text-xs">
            {data.signers.map((one) => (
              <li key={one.key_id}>
                <span className="font-mono text-[11px]">{one.key_id}</span>{" "}
                <span className="font-medium">{one.trust_level}</span>
                <span className="text-muted-foreground">
                  {" "}
                  — {one.revoked_reason || one.added_reason}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
