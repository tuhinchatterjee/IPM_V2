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
  Borrower360Workspace,
  Borrower360Similar,
} from "@/lib/api";
import { byUnit, humanise } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
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
  onSaved,
}: {
  meta: Borrower360Meta;
  period: string;
  onPick: (id: string) => void;
  onSaved: () => void;
}) {
  const [term, setTerm] = React.useState("");
  const [result, setResult] = React.useState<Borrower360Search | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [saveAs, setSaveAs] = React.useState("");
  const [saveProblem, setSaveProblem] = React.useState("");
  const [saved, setSaved] = React.useState("");

  async function save() {
    setSaveProblem("");
    setSaved("");
    try {
      // The search TEXT is what is kept, not the borrowers it matched.
      // Running this cohort next quarter answers the same question about a
      // book that has moved, which is the only version worth saving.
      const kept = await api.borrower360SaveCohort({
        label: saveAs,
        query: { text: term },
      });
      setSaved(kept.cohort.label);
      setSaveAs("");
      onSaved();
    } catch (caught) {
      setSaveProblem(refusalOrFailure(caught, "save that search"));
    }
  }

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

      {term.trim() ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={saveAs}
            onChange={(event) => setSaveAs(event.target.value)}
            placeholder="Save this search as…"
            aria-label="Name for the saved cohort"
            className={cn(
              "flex-1 rounded border border-[var(--line)] bg-transparent",
              "px-2 py-1 text-xs outline-none focus:border-[var(--accent)]",
            )}
          />
          <button
            type="button"
            disabled={!saveAs.trim()}
            onClick={() => void save()}
            className={cn(
              "rounded border border-[var(--line)] px-2 py-1 text-xs",
              "hover:border-[var(--accent)] disabled:opacity-40",
            )}
          >
            Save cohort
          </button>
        </div>
      ) : null}
      {saved ? (
        <p className="mt-1 text-[11px] text-[var(--muted)]">
          Saved as “{saved}”. It keeps the search, not today&rsquo;s matches.
        </p>
      ) : null}
      {saveProblem ? (
        <p className="mt-1 text-[11px] text-[var(--negative)]">
          {saveProblem}
        </p>
      ) : null}

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

/**
 * A refusal and a failure are different sentences.
 *
 * A 403 means the panel exists and this reader may not see it, which is a
 * fact about the reader. Anything else means the panel could not be built,
 * which is a fact about the system. Rendering both as an empty panel would
 * make either read as a fact about the BORROWER.
 */
function refusalOrFailure(caught: unknown, what: string): string {
  const status =
    caught && typeof caught === "object" && "status" in caught
      ? Number((caught as { status: unknown }).status)
      : 0;
  const message = caught instanceof Error ? caught.message : String(caught);
  if (status === 403) {
    return `${message} You are not permitted to see ${what}, which is not the same as there being none.`;
  }
  return `${what} could not be loaded: ${message}`;
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
function WorkingSet({
  workspace,
  period,
  onPick,
  onChanged,
}: {
  workspace: Borrower360Workspace | null;
  period: string;
  onPick: (id: string) => void;
  onChanged: () => void;
}) {
  const [ran, setRan] = React.useState<{
    reference: string;
    label: string;
    borrowers: Borrower360Search["borrowers"];
    matched: number;
  } | null>(null);
  const [problem, setProblem] = React.useState("");

  if (!workspace) return null;
  const empty =
    workspace.pins.length === 0 && workspace.cohorts.length === 0;

  async function forget(kind: "pin" | "cohort", reference: string) {
    setProblem("");
    try {
      if (kind === "pin") await api.borrower360Unpin(reference);
      else await api.borrower360ForgetCohort(reference);
      if (ran?.reference === reference) setRan(null);
      onChanged();
    } catch (caught) {
      setProblem(refusalOrFailure(caught, "remove that"));
    }
  }

  async function run(reference: string) {
    setProblem("");
    try {
      const answer = await api.borrower360RunCohort(reference, period);
      setRan({
        reference,
        label: answer.cohort.label,
        borrowers: answer.result.borrowers ?? [],
        matched: answer.result.matched ?? 0,
      });
    } catch (caught) {
      setRan(null);
      setProblem(refusalOrFailure(caught, "run that cohort"));
    }
  }

  return (
    <Card className="p-4">
      <h3 className="text-sm font-medium">Your working set</h3>
      <p className="mt-1 text-xs text-[var(--muted)]">{workspace.note}</p>

      {empty ? (
        <p className="mt-3 text-xs text-[var(--muted)]">
          Nothing kept yet. Pin a borrower from its header, or save a search
          you will want to run again.
        </p>
      ) : null}

      {workspace.pins.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
            Pinned borrowers
          </p>
          <ul className="mt-2 space-y-1">
            {workspace.pins.map((kept) => (
              <li
                key={kept.reference}
                className="flex items-start justify-between gap-3 text-sm"
              >
                <button
                  type="button"
                  onClick={() => onPick(kept.reference)}
                  className="text-left hover:text-[var(--accent)]"
                >
                  {kept.label || kept.reference}
                  {kept.noted ? (
                    <span className="block text-xs text-[var(--muted)]">
                      when pinned: {kept.noted}
                    </span>
                  ) : null}
                </button>
                <button
                  type="button"
                  onClick={() => void forget("pin", kept.reference)}
                  className="text-xs text-[var(--muted)] hover:text-[var(--fg)]"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {workspace.cohorts.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
            Saved cohorts
          </p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            The search is saved, not the borrowers it matched. Running one
            answers the question against the book as it is now.
          </p>
          <ul className="mt-2 space-y-1">
            {workspace.cohorts.map((kept) => (
              <li
                key={kept.reference}
                className="flex items-start justify-between gap-3 text-sm"
              >
                <span>
                  {kept.label}
                  <span className="block text-xs text-[var(--muted)]">
                    {Object.entries(kept.query.facets ?? {})
                      .map(([key, value]) => `${key} = ${String(value)}`)
                      .join(", ") || "search text"}
                  </span>
                </span>
                <span className="flex shrink-0 gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => void run(kept.reference)}
                    className="hover:text-[var(--accent)]"
                  >
                    Run
                  </button>
                  <button
                    type="button"
                    onClick={() => void forget("cohort", kept.reference)}
                    className="text-[var(--muted)] hover:text-[var(--fg)]"
                  >
                    Forget
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {problem ? (
        <p className="mt-3 text-xs text-[var(--danger,#b91c1c)]">{problem}</p>
      ) : null}

      {ran ? (
        <div className="mt-4 border-t border-[var(--line)] pt-3">
          <p className="text-xs text-[var(--muted)]">
            {ran.label} — {ran.matched} borrower
            {ran.matched === 1 ? "" : "s"} as at{" "}
            {period || "the latest quarter"}
          </p>
          <ul className="mt-2 space-y-1">
            {ran.borrowers.slice(0, 10).map((entry) => (
              <li key={entry.borrower_id}>
                <button
                  type="button"
                  onClick={() => onPick(entry.borrower_id)}
                  className="text-sm hover:text-[var(--accent)]"
                >
                  {entry.display_name ?? entry.legal_name ?? entry.borrower_id}
                </button>
              </li>
            ))}
          </ul>
          {ran.matched > 10 ? (
            <p className="mt-1 text-xs text-[var(--muted)]">
              Showing 10 of {ran.matched}.
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

function PinButton({
  borrowerId,
  label,
  noted,
  pinned,
  onChanged,
}: {
  borrowerId: string;
  label: string;
  noted: string;
  pinned: boolean;
  onChanged: () => void;
}) {
  const [problem, setProblem] = React.useState("");

  async function toggle() {
    setProblem("");
    try {
      if (pinned) await api.borrower360Unpin(borrowerId);
      else await api.borrower360Pin({ borrower_id: borrowerId, label, noted });
      onChanged();
    } catch (caught) {
      setProblem(refusalOrFailure(caught, pinned ? "unpin" : "pin"));
    }
  }

  return (
    <span className="flex flex-col items-end">
      <button
        type="button"
        onClick={() => void toggle()}
        className={cn(
          "rounded border px-3 py-2 text-sm",
          pinned
            ? "border-[var(--accent)] text-[var(--accent)]"
            : "border-[var(--line)] hover:border-[var(--accent)]",
        )}
      >
        {pinned ? "Pinned" : "Pin"}
      </button>
      {problem ? (
        <span className="mt-1 text-xs text-[var(--danger,#b91c1c)]">
          {problem}
        </span>
      ) : null}
    </span>
  );
}

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

/* ------------------------------------------------------- the landing table */

/**
 * The book, ranked, before anybody types anything. §18.
 *
 * Borrower 360 opened on a search box. A screen that will not show you a
 * borrower until you can name one is a screen that assumes you already know
 * which borrower is the problem — and the names worth knowing are exactly the
 * ones a ranking would have put at the top.
 *
 * So it opens on all eligible borrowers at the latest reporting period,
 * ordered by 12-month PD, highest first, with the borrower id as the tie-break
 * so the tenth row is the same tenth row on a second visit (§11).
 *
 * The presets are ORDERINGS AND FILTERS over governed fields, never scores.
 * "Liquidity pressure" sorts by single-name limit utilisation; it does not
 * invent a liquidity score, because a number a bank cannot explain to its
 * regulator is worse than no number — and §18 says so.
 */
const PRESETS: {
  id: string;
  label: string;
  orderBy?: string;
  descending?: boolean;
  flags?: { watchlist_flag?: boolean; breach_flag?: boolean };
  stage?: string;
  means: string;
}[] = [
  {
    id: "pd",
    label: "Highest PD",
    orderBy: "pd_12m",
    means: "12-month probability of default, highest first.",
  },
  {
    id: "ead",
    label: "Largest exposure",
    orderBy: "ifrs9_ead",
    means: "Exposure at default, largest first.",
  },
  {
    id: "ecl",
    label: "Highest ECL",
    orderBy: "final_ecl",
    means: "The booked impairment charge, largest first.",
  },
  {
    id: "stage2",
    label: "Stage 2",
    stage: "2",
    orderBy: "final_ecl",
    means: "Booked at IFRS 9 stage 2, ordered by ECL.",
  },
  {
    id: "stage3",
    label: "Stage 3",
    stage: "3",
    orderBy: "final_ecl",
    means: "Booked at IFRS 9 stage 3, ordered by ECL.",
  },
  {
    id: "watchlist",
    label: "Watchlist",
    flags: { watchlist_flag: true },
    orderBy: "pd_12m",
    means: "On the watchlist, ordered by PD.",
  },
  {
    id: "arrears",
    label: "In arrears",
    orderBy: "current_dpd",
    means: "Days past due, worst first.",
  },
  {
    id: "liquidity",
    label: "Liquidity pressure",
    orderBy: "single_name_utilisation_pct",
    means:
      "Single-name limit utilisation, highest first. An ordering over a " +
      "governed field, not a liquidity score.",
  },
  {
    id: "covenant",
    label: "Covenant pressure",
    orderBy: "average_headroom_pct",
    descending: false,
    means: "Average covenant headroom, lowest first.",
  },
  {
    id: "collateral",
    label: "Collateral pressure",
    orderBy: "collateral_coverage_pct",
    descending: false,
    means: "Collateral coverage, lowest first.",
  },
];

const PAGE = 25;

function PortfolioTable({
  period,
  onPick,
}: {
  period: string;
  onPick: (id: string) => void;
}) {
  const [preset, setPreset] = React.useState(PRESETS[0]);
  // The page size is keyed by the preset rather than reset in an effect:
  // pressing "Watchlist" while showing seventy-five rows should show
  // twenty-five of the watchlist, and deriving that during render is both
  // correct and one fewer render than resetting it afterwards.
  const [paging, setPaging] = React.useState({ preset: PRESETS[0].id, shown: PAGE });
  const shown = paging.preset === preset.id ? paging.shown : PAGE;

  const found = useAsync(
    () =>
      api.borrower360Cohort({
        period,
        order_by: preset.orderBy,
        descending: preset.descending,
        stage: preset.stage,
        ...(preset.flags ?? {}),
        limit: 200,
      }),
    [period, preset.id],
  );
  const rows: Borrower360Search | null = found.data ?? null;
  const busy = found.loading;
  const error = found.error ?? "";

  const borrowers = (rows?.borrowers ?? []).slice(0, shown);

  return (
    <Card className="mt-6 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Borrowers</h2>
        <p className="text-xs text-[var(--muted)]">
          {rows ? `${rows.matched.toLocaleString()} on book at ${rows.period}` : ""}
          {rows?.order_label ? ` · ${rows.order_label}` : ""}
          {rows?.ordered_by
            ? rows.ordered_descending
              ? ", highest first"
              : ", lowest first"
            : ""}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {PRESETS.map((option) => (
          <button
            key={option.id}
            type="button"
            title={option.means}
            onClick={() => setPreset(option)}
            className={cn(
              "rounded-md border px-2 py-1 text-[11px] transition-colors",
              option.id === preset.id
                ? "border-[var(--accent)] bg-[var(--accent)]/10"
                : "border-[var(--border)] hover:bg-[var(--surface-hover)]",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-[var(--muted)]">{preset.means}</p>

      {error ? <p className="mt-3 text-sm">{error}</p> : null}
      {busy && !rows ? <Skeleton className="mt-3 h-40 w-full" /> : null}

      {rows ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[52rem] text-left text-xs">
            <thead className="text-[var(--muted)]">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Borrower</th>
                <th className="py-1.5 pr-3 font-medium">Customer ID</th>
                <th className="py-1.5 pr-3 font-medium">Sector</th>
                <th className="py-1.5 pr-3 font-medium">Rating</th>
                <th className="py-1.5 pr-3 font-medium">Stage</th>
                <th className="py-1.5 pr-3 text-right font-medium">12m PD</th>
                <th className="py-1.5 pr-3 text-right font-medium">EAD</th>
                <th className="py-1.5 pr-3 text-right font-medium">ECL</th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  Utilisation
                </th>
                <th className="py-1.5 font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {borrowers.map((borrower) => (
                <tr
                  key={borrower.borrower_id}
                  onClick={() => onPick(borrower.borrower_id)}
                  className="cursor-pointer border-t border-[var(--border)] hover:bg-[var(--surface-hover)]"
                >
                  <td className="py-1.5 pr-3">
                    {borrower.display_name ??
                      borrower.legal_name ??
                      borrower.borrower_id}
                  </td>
                  <td className="py-1.5 pr-3 font-mono text-[11px] text-[var(--muted)]">
                    {borrower.borrower_id}
                  </td>
                  <td className="py-1.5 pr-3">{borrower.sector ?? ""}</td>
                  <td className="py-1.5 pr-3">
                    {borrower.internal_rating ?? ""}
                  </td>
                  <td className="py-1.5 pr-3">{borrower.stage ?? ""}</td>
                  <td className="tabular py-1.5 pr-3 text-right">
                    {byUnit(borrower.pd_12m, "%")}
                  </td>
                  <td className="tabular py-1.5 pr-3 text-right">
                    {byUnit(borrower.ifrs9_ead, "SAR mn")}
                  </td>
                  <td className="tabular py-1.5 pr-3 text-right">
                    {byUnit(borrower.final_ecl, "SAR mn")}
                  </td>
                  <td className="tabular py-1.5 pr-3 text-right">
                    {byUnit(borrower.single_name_utilisation_pct, "%")}
                  </td>
                  <td className="py-1.5">
                    <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                      {[
                        borrower.watchlist_flag ? "watchlist" : "",
                        borrower.breach_flag ? "breach" : "",
                        borrower.default_flag ? "default" : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {rows.borrowers.length > shown ? (
            <button
              type="button"
              onClick={() =>
              setPaging({ preset: preset.id, shown: shown + PAGE })
            }
              className="mt-3 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--surface-hover)]"
            >
              Show {Math.min(PAGE, rows.borrowers.length - shown)} more
            </button>
          ) : null}
          {rows.truncated ? (
            <p className="mt-2 text-[11px] text-[var(--muted)]">
              {rows.matched.toLocaleString()} borrowers match. The first{" "}
              {rows.returned} are shown — narrow with a preset or a search
              rather than scrolling a book this size.
            </p>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}


export default function Borrower360Page() {
  const [meta, setMeta] = React.useState<Borrower360Meta | null>(null);
  const [metaError, setMetaError] = React.useState("");
  const [period, setPeriod] = React.useState("");
  const [borrowerId, setBorrowerId] = React.useState("");
  const [row, setRow] = React.useState<Borrower360Row | null>(null);
  const [groups, setGroups] = React.useState<Borrower360Groups | null>(null);
  const [similar, setSimilar] = React.useState<Borrower360Similar | null>(null);
  const [groupsProblem, setGroupsProblem] = React.useState("");
  const [similarProblem, setSimilarProblem] = React.useState("");
  const [quality, setQuality] = React.useState<Borrower360Quality | null>(null);
  const [tab, setTab] = React.useState("overview");
  const [workspace, setWorkspace] =
    React.useState<Borrower360Workspace | null>(null);
  const [workspaceTick, setWorkspaceTick] = React.useState(0);
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

  // The working set is the reader's own and does not depend on which
  // borrower is open, so it loads once and reloads only when they change it.
  // A failure here leaves it null rather than showing an empty list: an
  // empty list reads as "you kept nothing", which is a claim about them.
  React.useEffect(() => {
    let live = true;
    api
      .borrower360Workspace()
      .then((found) => {
        if (live) setWorkspace(found);
      })
      .catch(() => {
        if (live) setWorkspace(null);
      });
    return () => {
      live = false;
    };
  }, [workspaceTick]);

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
    // A 403 is expected - the graph and the people behind it are narrower
    // permissions than the borrower itself - and is recorded as a refusal
    // rather than as a failure. Anything else is a failure and says so: a
    // bare `.catch(() => setNull())` turns a 500 into an empty panel, and an
    // empty panel reads as "this borrower has no group".
    api
      .borrower360Groups(borrowerId, period)
      .then((found) => {
        if (live) {
          setGroups(found);
          setGroupsProblem("");
        }
      })
      .catch((caught) => {
        if (!live) return;
        setGroups(null);
        setGroupsProblem(refusalOrFailure(caught, "the group view"));
      });
    api
      .borrower360Similar(borrowerId, period)
      .then((found) => {
        if (live) {
          setSimilar(found);
          setSimilarProblem("");
        }
      })
      .catch((caught) => {
        if (!live) return;
        setSimilar(null);
        setSimilarProblem(
          refusalOrFailure(caught, "hidden relationship candidates"));
      });
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

      <div className="mt-6 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <SearchPanel
          meta={meta}
          period={period}
          onPick={setBorrowerId}
          onSaved={() => setWorkspaceTick((n) => n + 1)}
        />
        <WorkingSet
          workspace={workspace}
          period={period}
          onPick={setBorrowerId}
          onChanged={() => setWorkspaceTick((n) => n + 1)}
        />
      </div>

      {rowError ? (
        <Card className="mt-6 p-4">
          <p className="text-sm">{rowError}</p>
        </Card>
      ) : null}

      {/* §18. Below the search, and only when no borrower is open: a screen
          showing one borrower's whole position does not also need the book
          underneath it. */}
      {!row && !rowError ? (
        <PortfolioTable period={period} onPick={setBorrowerId} />
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
            <div className="flex shrink-0 items-start gap-2">
              <PinButton
                borrowerId={row.borrower_id}
                label={String(
                  row.fields.display_name?.value ?? row.borrower_id,
                )}
                noted={String(
                  row.fields.group_limit_status?.value ??
                    row.fields.network_risk_score?.value ??
                    "",
                )}
                pinned={(workspace?.pins ?? []).some(
                  (kept) => kept.reference === row.borrower_id,
                )}
                onChanged={() => setWorkspaceTick((n) => n + 1)}
              />
              <PackButton borrowerId={row.borrower_id} period={period} />
            </div>
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
            {tab === "group" ? (
              groups ? (
                <GroupsPanel groups={groups} />
              ) : (
                <Card className="border-[var(--warning)] p-4">
                  <p className="text-sm">
                    {groupsProblem || "Loading the group view…"}
                  </p>
                </Card>
              )
            ) : tab === "network" ? (
              <>
                <GraphPanel
                  meta={meta}
                  borrowerId={row.borrower_id}
                  period={period}
                />
                {similar ? (
                  <SimilarPanel similar={similar} />
                ) : similarProblem ? (
                  <Card className="mt-4 border-[var(--warning)] p-4">
                    <p className="text-sm">{similarProblem}</p>
                  </Card>
                ) : null}
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
