"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  Borrower360Graph,
  Borrower360Groups,
  Borrower360Meta,
  Borrower360Quality,
  Borrower360Row,
  Borrower360Search,
  Borrower360Similar,
} from "@/lib/api";
import { byUnit, humanise } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Borrower 360 — one corporate borrower, and everything the bank knows.
 *
 * Four things this screen refuses to do
 * --------------------------------------
 * **It never resolves an ambiguous name silently.** Typing a name that
 * matches six borrowers shows six candidates, not the first one. A screen
 * that picks quietly shows somebody else's exposure under the name that was
 * typed, and nothing on it says a choice was made.
 *
 * **It never shows a blank where a number would go.** Four different
 * absences are rendered as four different chips: NOT COMPUTED (the graph did
 * not run for this quarter), NOT_AVAILABLE (it ran and this borrower is not
 * in that graph), NOT_APPLICABLE (the measure does not apply) and
 * DATA_QUALITY_BLOCKED (the input was rejected). One grey dash for all four
 * would conflate a data-quality refusal with a borrower that simply has no
 * suppliers.
 *
 * **It never presents the six groupings as one group.** They answer
 * different questions and do not agree by design. The Group tab shows all
 * six side by side, each with what it is NOT.
 *
 * **It never fetches the whole network.** The graph tab asks the server for
 * a bounded neighbourhood and renders exactly what comes back, including the
 * sentence saying what was left out.
 */

const ABSENT = new Set([
  "NOT COMPUTED",
  "NOT_AVAILABLE",
  "NOT_APPLICABLE",
  "DATA_QUALITY_BLOCKED",
  "PERMISSION_REQUIRED",
]);

const ABSENT_MEANING: Record<string, string> = {
  "NOT COMPUTED": "The derived graph has not been run for this quarter.",
  NOT_AVAILABLE:
    "The derivation ran and this borrower is not in that graph. Not zero — " +
    "a borrower with no financial claims does not have a network score of " +
    "zero, it does not have one.",
  NOT_APPLICABLE: "This measure does not apply to this borrower.",
  DATA_QUALITY_BLOCKED:
    "A data-quality check REJECTED the input, so the computation did not " +
    "run. The reason is on the Data quality tab.",
  PERMISSION_REQUIRED:
    "You are not permitted to see this. That is different from there being " +
    "nothing here.",
};

const ABSENT_TONE: Record<string, string> = {
  "NOT COMPUTED": "border-[var(--line)] text-[var(--muted)]",
  NOT_AVAILABLE: "border-[var(--line)] text-[var(--muted)]",
  NOT_APPLICABLE: "border-[var(--line)] text-[var(--muted)]",
  DATA_QUALITY_BLOCKED:
    "border-[var(--warning)] text-[var(--warning)] bg-[var(--warning)]/5",
  PERMISSION_REQUIRED:
    "border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/5",
};

function AbsentChip({ value }: { value: string }) {
  return (
    <span
      title={ABSENT_MEANING[value] ?? value}
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5",
        "text-[10px] font-medium tracking-wide uppercase",
        ABSENT_TONE[value] ?? "border-[var(--line)] text-[var(--muted)]",
      )}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

function FieldValue({
  value,
  unit,
}: {
  value: string | number | boolean | null;
  unit?: string;
}) {
  if (value === null || value === undefined || value === "") {
    return <AbsentChip value="NOT COMPUTED" />;
  }
  if (typeof value === "string" && ABSENT.has(value)) {
    return <AbsentChip value={value} />;
  }
  if (typeof value === "boolean") {
    return <span>{value ? "Yes" : "No"}</span>;
  }
  const asNumber = typeof value === "number" ? value : Number(value);
  if (!Number.isNaN(asNumber) && typeof value !== "boolean" && unit) {
    return <span className="tabular-nums">{byUnit(asNumber, unit)}</span>;
  }
  return <span className="tabular-nums">{String(value)}</span>;
}

/* ------------------------------------------------------------------ search */

function SearchPanel({
  meta,
  period,
  onPick,
}: {
  meta: Borrower360Meta;
  period: string;
  onPick: (id: string) => void;
}) {
  const [term, setTerm] = React.useState("");
  const [result, setResult] = React.useState<Borrower360Search | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const run = React.useCallback(
    async (text: string) => {
      if (!text.trim()) {
        setResult(null);
        return;
      }
      setBusy(true);
      setError("");
      try {
        setResult(await api.borrower360Search(text, period, 25));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setBusy(false);
      }
    },
    [period],
  );

  return (
    <Card className="p-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run(term);
        }}
        className="flex gap-2"
      >
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Borrower id, customer number, legal, trading or Arabic name"
          aria-label="Search borrowers"
          className={cn(
            "flex-1 rounded border border-[var(--line)] bg-transparent",
            "px-3 py-2 text-sm outline-none focus:border-[var(--accent)]",
          )}
        />
        <button
          type="submit"
          className={cn(
            "rounded border border-[var(--line)] px-3 py-2 text-sm",
            "hover:border-[var(--accent)]",
          )}
        >
          Search
        </button>
      </form>

      <p className="mt-2 text-[11px] text-[var(--muted)]">
        Searches {meta.searchable_attributes.length} governed attributes.
      </p>

      {busy ? <Skeleton className="mt-3 h-16 w-full" /> : null}
      {error ? (
        <p className="mt-3 text-sm text-[var(--negative)]">{error}</p>
      ) : null}

      {result ? (
        <div className="mt-3">
          {result.matched === 0 ? (
            <p className="text-sm text-[var(--muted)]">
              Nothing matched. A legal-form word on its own — “Company”,
              “LLC” — identifies no borrower here, so it matches none rather
              than all of them.
            </p>
          ) : null}

          {result.ambiguous ? (
            <p className="mb-2 text-sm">
              <strong>{result.matched} borrowers</strong> match that. None has
              been chosen for you — picking the closest and showing it under
              the name you typed is how a screen ends up displaying somebody
              else&rsquo;s exposure.
            </p>
          ) : null}

          {result.resolved ? (
            <p className="mb-2 text-sm text-[var(--muted)]">
              One match.
            </p>
          ) : null}

          <ul className="divide-y divide-[var(--line)]">
            {result.borrowers.map((row) => (
              <li key={row.borrower_id}>
                <button
                  type="button"
                  onClick={() => onPick(row.borrower_id)}
                  className="flex w-full items-baseline justify-between py-2 text-left hover:text-[var(--accent)]"
                >
                  <span className="text-sm">
                    {row.display_name ?? row.legal_name ?? row.borrower_id}
                    <span className="ml-2 text-[11px] text-[var(--muted)]">
                      {row.borrower_id}
                    </span>
                  </span>
                  <span className="text-[11px] text-[var(--muted)]">
                    {[row.sector, row.region, row.internal_rating]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {result.truncated ? (
            <p className="mt-2 text-[11px] text-[var(--muted)]">
              Showing {result.returned} of {result.matched}. Narrow the term.
            </p>
          ) : null}

          {result.not_found?.length ? (
            <p className="mt-2 text-sm text-[var(--warning)]">
              Not on book in {result.period}:{" "}
              {result.not_found.join(", ")}. {result.not_found_note}
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------- tabs */

function FieldTable({
  row,
  fields,
}: {
  row: Borrower360Row;
  fields: string[];
}) {
  if (!fields.length) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No fields on this tab for this borrower.
      </p>
    );
  }
  return (
    <table className="w-full text-sm">
      <tbody className="divide-y divide-[var(--line)]">
        {fields.map((name) => {
          const field = row.fields[name];
          if (!field) return null;
          return (
            <tr key={name} className="align-baseline">
              <th
                scope="row"
                className="w-1/3 py-1.5 pr-4 text-left font-normal text-[var(--muted)]"
              >
                {humanise(name)}
              </th>
              <td className="py-1.5 pr-4">
                <FieldValue value={field.value} unit={field.unit} />
                {field.withheld_reason ? (
                  <span className="ml-2 text-[11px] text-[var(--muted)]">
                    {field.withheld_reason}
                  </span>
                ) : null}
              </td>
              <td className="py-1.5 text-right text-[11px] text-[var(--muted)]">
                {field.source_dataset}
                <span className="ml-1 opacity-60">({field.authority})</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function GroupsPanel({ groups }: { groups: Borrower360Groups }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--muted)]">{groups.note}</p>
      <div className="grid gap-3 md:grid-cols-2">
        {groups.concepts.map((concept) => (
          <Card key={concept.key} className="p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-sm font-medium">{concept.label}</h3>
              <span className="text-sm tabular-nums">
                {ABSENT.has(String(concept.value)) ? (
                  <AbsentChip value={String(concept.value)} />
                ) : (
                  concept.value
                )}
              </span>
            </div>
            {concept.name ? (
              <p className="mt-1 text-sm">
                {concept.name}
                {concept.size ? ` · ${concept.size} members` : ""}
                {concept.role ? ` · ${concept.role}` : ""}
              </p>
            ) : null}
            {concept.utilisation_pct !== undefined &&
            concept.utilisation_pct !== null ? (
              <p className="mt-1 text-sm">
                <span className="tabular-nums">
                  {concept.utilisation_pct.toFixed(2)}%
                </span>{" "}
                of the eligible capital reference · limit{" "}
                {concept.limit_pct}% ·{" "}
                <span
                  className={cn(
                    concept.status === "BREACH" && "text-[var(--negative)]",
                    concept.status === "INVESTIGATE" && "text-[var(--warning)]",
                  )}
                >
                  {concept.status}
                </span>
              </p>
            ) : null}
            <dl className="mt-3 space-y-1.5 text-[11px]">
              <div>
                <dt className="inline text-[var(--muted)]">Answers: </dt>
                <dd className="inline">{concept.question}</dd>
              </div>
              <div>
                <dt className="inline text-[var(--muted)]">Basis: </dt>
                <dd className="inline">{concept.basis}</dd>
              </div>
              <div>
                <dt className="inline font-medium text-[var(--warning)]">
                  Is NOT:{" "}
                </dt>
                <dd className="inline">{concept.is_not}</dd>
              </div>
            </dl>
            {concept.parameter_caveat ? (
              <p className="mt-2 text-[10px] uppercase tracking-wide text-[var(--warning)]">
                {concept.parameter_caveat}
              </p>
            ) : null}
          </Card>
        ))}
      </div>
    </div>
  );
}

function GraphPanel({
  meta,
  borrowerId,
  period,
}: {
  meta: Borrower360Meta;
  borrowerId: string;
  period: string;
}) {
  const [view, setView] = React.useState("ownership");
  const [depth, setDepth] = React.useState(1);
  // One piece of state keyed by the request that produced it, rather than
  // three set synchronously inside the effect. "Busy" is then DERIVED - the
  // answer on screen is not the answer for the request in flight - which
  // avoids the cascading render an in-effect setState causes.
  const [loaded, setLoaded] = React.useState<{
    key: string;
    graph: Borrower360Graph | null;
    error: string;
  }>({ key: "", graph: null, error: "" });

  const requestKey = `${borrowerId}|${view}|${depth}|${period}`;
  const busy = loaded.key !== requestKey;
  const graph = busy ? null : loaded.graph;
  const error = busy ? "" : loaded.error;

  React.useEffect(() => {
    let live = true;
    api
      .borrower360Graph(borrowerId, view, depth, period)
      .then((found) => {
        if (live) setLoaded({ key: requestKey, graph: found, error: "" });
      })
      .catch((caught) => {
        if (live) {
          setLoaded({
            key: requestKey,
            graph: null,
            error: caught instanceof Error ? caught.message : String(caught),
          });
        }
      });
    return () => {
      live = false;
    };
  }, [borrowerId, view, depth, period, requestKey]);

  const chosen = meta.network_views.find((entry) => entry.key === view);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {meta.network_views.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setView(entry.key)}
            title={
              entry.permitted
                ? entry.purpose
                : `${entry.purpose} — requires permission to see natural persons.`
            }
            className={cn(
              "rounded border px-2 py-1 text-xs",
              view === entry.key
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-[var(--line)] text-[var(--muted)]",
              !entry.permitted && "opacity-50",
            )}
          >
            {entry.label}
            {entry.requires_ubo_permission ? " ·" : ""}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-xs text-[var(--muted)]">
          Depth
          <select
            value={depth}
            onChange={(event) => setDepth(Number(event.target.value))}
            className="rounded border border-[var(--line)] bg-transparent px-2 py-1"
          >
            {Array.from({ length: meta.max_graph_depth + 1 }, (_, i) => i).map(
              (value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ),
            )}
          </select>
        </label>
      </div>

      {chosen ? (
        <p className="text-sm text-[var(--muted)]">{chosen.purpose}</p>
      ) : null}

      {busy ? <Skeleton className="h-40 w-full" /> : null}

      {error ? (
        <Card className="border-[var(--warning)] p-4">
          <p className="text-sm">{error}</p>
        </Card>
      ) : null}

      {graph ? (
        <>
          <p className="text-sm">
            <span className="tabular-nums">{graph.node_count}</span> nodes and{" "}
            <span className="tabular-nums">{graph.edge_count}</span> edges,
            expanded {graph.reached_depth} step
            {graph.reached_depth === 1 ? "" : "s"} from {graph.centre} as at{" "}
            {graph.as_of}.
          </p>
          {graph.truncated ? (
            <p className="text-sm text-[var(--warning)]">
              {graph.truncation_note}
            </p>
          ) : null}

          <div className="max-h-96 overflow-auto rounded border border-[var(--line)]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[var(--surface)] text-left text-[var(--muted)]">
                <tr>
                  <th className="px-2 py-1.5 font-normal">Relationship</th>
                  <th className="px-2 py-1.5 font-normal">From</th>
                  <th className="px-2 py-1.5 font-normal">To</th>
                  <th className="px-2 py-1.5 text-right font-normal">Weight</th>
                  <th className="px-2 py-1.5 font-normal">Evidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]">
                {graph.edges.map((edge, index) => {
                  const label = (id: string) =>
                    graph.nodes.find((node) => node.node_id === id)?.label ??
                    id;
                  const weight =
                    edge.ownership_pct ?? edge.amount ?? edge.voting_pct;
                  return (
                    <tr key={edge.edge_id ?? index}>
                      <td className="px-2 py-1.5">{edge.edge_type}</td>
                      <td className="px-2 py-1.5">{label(edge.from_node)}</td>
                      <td className="px-2 py-1.5">{label(edge.to_node)}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">
                        {weight === null || weight === undefined
                          ? "—"
                          : weight.toFixed(2)}
                      </td>
                      <td className="px-2 py-1.5 text-[var(--muted)]">
                        {edge.source ?? "—"}
                        {edge.confidence !== null &&
                        edge.confidence !== undefined
                          ? ` (${edge.confidence.toFixed(2)})`
                          : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

function SimilarPanel({ similar }: { similar: Borrower360Similar | null }) {
  if (!similar) return null;
  return (
    <Card className="mt-4 border-dashed p-4">
      <h3 className="text-sm font-medium">Hidden relationship candidates</h3>
      <p className="mt-1 text-[11px] text-[var(--warning)]">
        {similar.caveat}
      </p>
      {similar.candidates.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--muted)]">
          No borrower shares enough evidence with this one to clear the
          threshold.
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-sm">
          {similar.candidates.map((candidate) => (
            <li key={`${candidate.from_node}-${candidate.to_node}`}>
              <span className="tabular-nums">
                {(candidate.similarity * 100).toFixed(0)}%
              </span>{" "}
              shared evidence with{" "}
              {candidate.from_node === similar.borrower_id
                ? candidate.to_node
                : candidate.from_node}{" "}
              <span className="text-[11px] text-[var(--muted)]">
                ({candidate.shared_evidence_count} shared:{" "}
                {candidate.shared_evidence.slice(0, 3).join(", ")})
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">
        {similar.threshold_status}
      </p>
    </Card>
  );
}

function QualityPanel({ quality }: { quality: Borrower360Quality | null }) {
  if (!quality) return null;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {quality.checks_run} checks · {quality.passed} passed ·{" "}
        {quality.flagged} flagged · {quality.rejected} rejected. Overall{" "}
        <strong>{quality.overall_status}</strong>.
      </p>
      <p className="text-sm text-[var(--muted)]">{quality.blocking_rule}</p>
      <div className="overflow-auto rounded border border-[var(--line)]">
        <table className="w-full text-xs">
          <thead className="text-left text-[var(--muted)]">
            <tr>
              <th className="px-2 py-1.5 font-normal">Check</th>
              <th className="px-2 py-1.5 font-normal">Status</th>
              <th className="px-2 py-1.5 font-normal">Observed</th>
              <th className="px-2 py-1.5 font-normal">Threshold</th>
              <th className="px-2 py-1.5 font-normal">Blocks</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--line)]">
            {quality.issues.map((issue) => (
              <tr key={issue.issue_id}>
                <td className="px-2 py-1.5">
                  {issue.check_id} {issue.check}
                </td>
                <td
                  className={cn(
                    "px-2 py-1.5 font-medium",
                    issue.status === "REJECT" && "text-[var(--negative)]",
                    issue.status === "FLAG" && "text-[var(--warning)]",
                  )}
                >
                  {issue.status}
                </td>
                <td className="px-2 py-1.5 text-[var(--muted)]">
                  {issue.observed}
                </td>
                <td className="px-2 py-1.5 text-[var(--muted)]">
                  {issue.threshold}
                </td>
                <td className="px-2 py-1.5 text-[var(--muted)]">
                  {issue.blocks || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- export */

/**
 * DOWNLOAD BORROWER 360 PACK.
 *
 * A fetch rather than a link, for the same reason as everywhere else in the
 * product: a plain `<a download>` cannot carry the role header the export
 * authorises against, and a 403 arriving through a link is a browser error
 * page rather than a message inside the product. A VIEWER may read this
 * screen and may not export it, so the refusal has to land here.
 */
function PackButton({
  borrowerId,
  period,
}: {
  borrowerId: string;
  period: string;
}) {
  const [phase, setPhase] = React.useState<"idle" | "working" | "failed">(
    "idle",
  );
  const [problem, setProblem] = React.useState("");

  const run = React.useCallback(async () => {
    setPhase("working");
    setProblem("");
    try {
      const { blob, filename } = await api.downloadBorrower360Pack(
        borrowerId,
        period,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setPhase("idle");
    } catch (caught) {
      setPhase("failed");
      setProblem(caught instanceof Error ? caught.message : String(caught));
    }
  }, [borrowerId, period]);

  return (
    <div className="text-right">
      <button
        type="button"
        onClick={() => void run()}
        disabled={phase === "working"}
        className={cn(
          "rounded border border-[var(--line)] px-3 py-1.5 text-xs",
          "hover:border-[var(--accent)] disabled:opacity-60",
        )}
      >
        {phase === "working"
          ? "Preparing workbook…"
          : "Download Borrower 360 pack"}
      </button>
      {problem ? (
        <p className="mt-1 max-w-xs text-[11px] text-[var(--negative)]">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------- page */

export default function Borrower360Page() {
  const [meta, setMeta] = React.useState<Borrower360Meta | null>(null);
  const [metaError, setMetaError] = React.useState("");
  const [period, setPeriod] = React.useState("");
  const [borrowerId, setBorrowerId] = React.useState("");
  const [row, setRow] = React.useState<Borrower360Row | null>(null);
  const [groups, setGroups] = React.useState<Borrower360Groups | null>(null);
  const [similar, setSimilar] = React.useState<Borrower360Similar | null>(null);
  const [quality, setQuality] = React.useState<Borrower360Quality | null>(null);
  const [tab, setTab] = React.useState("overview");
  const [rowError, setRowError] = React.useState("");

  React.useEffect(() => {
    api
      .borrower360Meta()
      .then((found) => {
        setMeta(found);
        setPeriod(found.latest_period ?? "");
      })
      .catch((caught) =>
        setMetaError(caught instanceof Error ? caught.message : String(caught)),
      );
  }, []);

  React.useEffect(() => {
    if (!borrowerId || !period) return;
    let live = true;
    api
      .borrower360Row(borrowerId, period)
      .then((found) => {
        if (live) {
          setRow(found);
          setRowError("");
        }
      })
      .catch((caught) => {
        if (live) {
          setRow(null);
          setRowError(
            caught instanceof Error ? caught.message : String(caught),
          );
        }
      });
    api
      .borrower360Groups(borrowerId, period)
      .then((found) => live && setGroups(found))
      .catch(() => live && setGroups(null));
    api
      .borrower360Similar(borrowerId, period)
      .then((found) => live && setSimilar(found))
      .catch(() => live && setSimilar(null));
    return () => {
      live = false;
    };
  }, [borrowerId, period]);

  React.useEffect(() => {
    if (tab !== "quality" || !period) return;
    api
      .borrower360Quality(period)
      .then(setQuality)
      .catch(() => setQuality(null));
  }, [tab, period]);

  if (metaError) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-8">
        <PageHeader title="Borrower 360" />
        <Card className="mt-6 p-6">
          <p className="text-sm">{metaError}</p>
        </Card>
      </main>
    );
  }

  if (!meta) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-8">
        <PageHeader title="Borrower 360" />
        <Skeleton className="mt-6 h-64 w-full" />
      </main>
    );
  }

  const activeTab = row?.tabs.find((entry) => entry.key === tab);

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <PageHeader
        title="Borrower 360"
        description={
          "One corporate borrower and everything the bank knows about it: " +
          "exposure, ratings, IFRS 9, covenants, collateral, limits, its " +
          "relationship network and the quality of the evidence underneath."
        }
        actions={
          meta.periods.length ? (
            <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
              As at
              <select
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                className="rounded border border-[var(--line)] bg-transparent px-2 py-1"
              >
                {meta.periods.map((entry) => (
                  <option key={entry} value={entry}>
                    {entry}
                  </option>
                ))}
              </select>
            </label>
          ) : null
        }
      />

      <p className="mt-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">
        {meta.origin} — {meta.not_client_data}
      </p>

      <div className="mt-6">
        <SearchPanel meta={meta} period={period} onPick={setBorrowerId} />
      </div>

      {rowError ? (
        <Card className="mt-6 p-4">
          <p className="text-sm">{rowError}</p>
        </Card>
      ) : null}

      {row ? (
        <section className="mt-8">
          <header className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-medium">
                {String(row.fields.display_name?.value ?? row.borrower_id)}
              </h2>
              <p className="text-xs text-[var(--muted)]">
                {row.borrower_id} · {row.period} · as at {row.period_end_date}
                {row.may_see_natural_persons
                  ? ""
                  : " · natural persons withheld by permission"}
              </p>
            </div>
            <PackButton borrowerId={row.borrower_id} period={period} />
          </header>

          <nav className="flex flex-wrap gap-1 border-b border-[var(--line)]">
            {meta.tabs.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setTab(entry.key)}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm",
                  tab === entry.key
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--muted)] hover:text-[var(--fg)]",
                )}
              >
                {entry.label}
              </button>
            ))}
          </nav>

          <div className="mt-5">
            {tab === "group" && groups ? (
              <GroupsPanel groups={groups} />
            ) : tab === "network" ? (
              <>
                <GraphPanel
                  meta={meta}
                  borrowerId={row.borrower_id}
                  period={period}
                />
                <SimilarPanel similar={similar} />
                <p className="mt-4 text-[10px] uppercase tracking-wide text-[var(--warning)]">
                  {meta.network_risk_score_label}
                </p>
                <div className="mt-3">
                  <FieldTable
                    row={row}
                    fields={activeTab?.fields ?? []}
                  />
                </div>
              </>
            ) : tab === "quality" ? (
              <>
                <FieldTable row={row} fields={activeTab?.fields ?? []} />
                <div className="mt-6">
                  <QualityPanel quality={quality} />
                </div>
              </>
            ) : (
              <FieldTable row={row} fields={activeTab?.fields ?? []} />
            )}
          </div>
        </section>
      ) : null}
    </main>
  );
}
