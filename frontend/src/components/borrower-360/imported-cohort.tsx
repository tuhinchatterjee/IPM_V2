"use client";

import * as React from "react";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Pin,
  RefreshCw,
  Save,
  Sigma,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type CohortCustomerPage,
  type CohortCustomerRow,
  type CohortSnapshotView,
  type CohortWhatIfView,
  type InvestigationNoteView,
  type SavedInvestigationView,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Customer 360 in imported-cohort mode. U06, U08, U09.
 *
 * WHAT THIS IS NOT
 *
 * It is not a second customer workspace. A reader who arrives here without a
 * cohort sees the ordinary Customer 360 exactly as it has always been; this
 * appears only when a link carries a snapshot, or when a saved investigation
 * is reopened. The specification is explicit that the enrichment belongs in
 * the exported and saved context and nowhere else.
 *
 * THE THING IT REFUSES TO DO
 *
 * A customer holding a personal loan at 4% and a mortgage at 0.4% does not
 * have a probability of default of 2.2%. There is no such customer. So where
 * the included facilities are different products, no single figure is shown
 * and the row says why — an unexplained average is the specific way this
 * screen would mislead somebody who trusts it.
 *
 * A customer's other facilities are shown as CONTEXT and are not in the
 * financial baseline. Switching to all of them is an explicit choice that
 * writes a new cohort with recomputed counts, because it changes the totals
 * the investigation has been carrying.
 *
 * Everything shown is SYNTHETIC demonstration data.
 */

const PAGE = 50;

export function ImportedCohort({
  snapshotId,
  onClear,
}: {
  snapshotId: string;
  onClear?: () => void;
}) {
  const [snapshot, setSnapshot] = React.useState<CohortSnapshotView | null>(null);
  const [page, setPage] = React.useState<CohortCustomerPage | null>(null);
  const [offset, setOffset] = React.useState(0);
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = React.useState<Set<string>>(() => new Set());
  const [allFacilities, setAllFacilities] = React.useState(false);
  const [saved, setSaved] = React.useState<SavedInvestigationView | null>(null);
  const [notes, setNotes] = React.useState<InvestigationNoteView[]>([]);
  const [noteDraft, setNoteDraft] = React.useState("");
  const [whatIf, setWhatIf] = React.useState<CohortWhatIfView | null>(null);
  const [busy, setBusy] = React.useState("");
  const [problem, setProblem] = React.useState("");
  const [current, setCurrent] = React.useState(snapshotId);

  React.useEffect(() => setCurrent(snapshotId), [snapshotId]);

  React.useEffect(() => {
    let live = true;
    setProblem("");
    api
      .cohort(current)
      .then((found) => live && setSnapshot(found.snapshot))
      .catch((caught) =>
        live &&
        setProblem(caught instanceof Error ? caught.message : String(caught)),
      );
    return () => {
      live = false;
    };
  }, [current]);

  React.useEffect(() => {
    let live = true;
    api
      .cohortCustomers(current, offset, PAGE)
      .then((found) => live && setPage(found))
      .catch(() => live && setPage(null));
    return () => {
      live = false;
    };
  }, [current, offset]);

  React.useEffect(() => {
    let live = true;
    api
      .retailRecentInvestigations(20)
      .then((found) => {
        if (!live) return;
        const mine = found.rows.find((r) => r.snapshot_id === current);
        if (mine) {
          setSaved(mine);
          setNotes(mine.notes ?? []);
        }
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [current]);

  React.useEffect(() => {
    let live = true;
    api
      .cohortWhatIf(current)
      .then((found) => live && setWhatIf(found))
      .catch(() => live && setWhatIf(null));
    return () => {
      live = false;
    };
  }, [current]);

  async function applySelection(mode: string) {
    if (!snapshot) return;
    setBusy("selecting");
    setProblem("");
    try {
      const found = await api.cohortSelect(current, {
        customer_ids: Array.from(selected),
        facility_mode: mode,
      });
      setCurrent(found.snapshot.snapshot_id);
      setSnapshot(found.snapshot);
      setOffset(0);
      setSelected(new Set());
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function saveNamed() {
    if (!saved) return;
    setBusy("saving");
    try {
      const found = await api.retailSaveInvestigation(saved.saved_id, {
        title: saved.title,
        pinned: true,
      });
      setSaved(found.saved);
    } finally {
      setBusy("");
    }
  }

  async function addNote() {
    if (!saved || !noteDraft.trim()) return;
    setBusy("noting");
    try {
      const found = await api.retailAddInvestigationNote(
        saved.saved_id,
        noteDraft.trim(),
      );
      setNotes((was) => [...was, found.note]);
      setNoteDraft("");
    } finally {
      setBusy("");
    }
  }

  async function refreshToLatest() {
    if (!saved) return;
    setBusy("refreshing");
    try {
      const found = await api.retailRefreshInvestigation(saved.saved_id);
      setSaved(found.saved);
      setCurrent(found.saved.snapshot_id);
    } finally {
      setBusy("");
    }
  }

  async function toWhatIf() {
    setBusy("whatif");
    setProblem("");
    try {
      const found = await api.cohortToWhatIf(current);
      window.location.href = `/early-warning/whatif/${found.selection_id}`;
    } catch (caught) {
      setProblem(
        caught instanceof Error
          ? caught.message
          : "The scope did not reconcile, so it was not handed to What-If.",
      );
    } finally {
      setBusy("");
    }
  }

  if (problem && !snapshot) {
    return (
      <Card className="border-negative/40">
        <CardContent className="pt-4 text-sm text-negative">{problem}</CardContent>
      </Card>
    );
  }
  if (!snapshot) return <Skeleton className="h-64 w-full" />;

  const rows = page?.rows ?? [];
  const total = page?.total ?? snapshot.customer_count;

  return (
    <div className="space-y-4" data-testid="imported-cohort">
      {/* The banner. Where this list came from, at what date, on which build. */}
      <Card className="border-accent/40 bg-accent/5">
        <CardContent className="space-y-2 pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-accent">
                Imported investigation
              </p>
              <h3 className="text-sm font-semibold text-text-primary">
                {saved?.issue || snapshot.case_id} — {snapshot.step_id}
              </h3>
            </div>
            {onClear ? (
              <button
                type="button"
                onClick={onClear}
                className="text-xs text-text-muted underline underline-offset-2"
              >
                Leave imported mode
              </button>
            ) : null}
          </div>
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
            <Fact label="Case" value={snapshot.case_id} />
            <Fact label="Source step" value={snapshot.step_id} />
            <Fact label="Reporting date" value={snapshot.source_as_of} />
            <Fact
              label="Scope"
              value={snapshot.scope || snapshot.root_scope}
            />
            <Fact
              label="Selected"
              value={`${snapshot.customer_count.toLocaleString("en-GB")} customers · ${snapshot.facility_count.toLocaleString("en-GB")} facilities`}
            />
            <Fact
              label="Facilities included"
              value={
                snapshot.facility_mode === "flagged_only"
                  ? "flagged only"
                  : "all authorised"
              }
            />
            <Fact label="Source bundle" value={snapshot.source_bundle_id || "—"} />
            <Fact
              label="Snapshot"
              value={`${snapshot.snapshot_id} · ${snapshot.content_hash.slice(0, 12)}`}
            />
            <Fact
              label="Steps carried"
              value={(snapshot.visited_steps ?? []).join(", ")}
            />
          </dl>
          {snapshot.restricted_count > 0 ? (
            <p className="text-xs text-warning">
              {snapshot.restricted_count.toLocaleString("en-GB")} identifiers in
              this cohort are withheld from you by field permissions. They are
              counted in the totals and are not listed.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {/* Actions. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 pt-4">
          <span className="text-xs text-text-secondary">
            {selected.size
              ? `${selected.size.toLocaleString("en-GB")} selected`
              : `all ${total.toLocaleString("en-GB")} matched`}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={!selected.size || busy !== ""}
            onClick={() => applySelection(snapshot.facility_mode)}
          >
            Narrow to selection
          </Button>
          <label className="inline-flex items-center gap-1.5 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={allFacilities}
              onChange={(e) => {
                setAllFacilities(e.target.checked);
                applySelection(
                  e.target.checked
                    ? "all_authorised_facilities"
                    : "flagged_only",
                );
              }}
            />
            Include all authorised facilities of these customers
          </label>
          <Button size="sm" variant="outline" disabled={busy !== ""} onClick={saveNamed}>
            {saved?.state === "saved" ? (
              <Pin className="mr-1.5 size-3.5" aria-hidden />
            ) : (
              <Save className="mr-1.5 size-3.5" aria-hidden />
            )}
            {saved?.state === "saved" ? "Saved" : "Save investigation"}
          </Button>
          <Button size="sm" variant="outline" disabled={busy !== ""} onClick={refreshToLatest}>
            <RefreshCw className="mr-1.5 size-3.5" aria-hidden />
            Refresh to latest
          </Button>
          <a
            className="inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-xs text-text-secondary hover:bg-surface-hover"
            href={`/api/v1/retail/cohorts/${current}/workbook.xlsx`}
          >
            <Download className="size-3.5" aria-hidden />
            Export Excel
          </a>
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== "" || whatIf?.may_simulate === false}
            onClick={toWhatIf}
            title={
              whatIf?.may_simulate === false
                ? "The imported scope does not reconcile with the investigation it came from."
                : undefined
            }
          >
            <Sigma className="mr-1.5 size-3.5" aria-hidden />
            Export to What-If
          </Button>
          {problem ? (
            <span className="text-xs text-negative">{problem}</span>
          ) : null}
        </CardContent>
      </Card>

      {whatIf && !whatIf.may_simulate ? (
        <Card className="border-warning/50">
          <CardContent className="pt-4 text-xs text-warning">
            {whatIf.stale_bundle ||
              whatIf.reconciliation?.because ||
              "This scope does not reconcile with the investigation it came from, so it cannot be simulated."}
            {whatIf.reconciliation?.differences?.length ? (
              <ul className="mt-1 list-disc pl-5">
                {whatIf.reconciliation.differences.map((d, i) => (
                  <li key={i}>{JSON.stringify(d)}</li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* The list. */}
      <Card>
        <CardContent className="pt-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
                <th className="w-8 py-1.5" />
                <th className="py-1.5">Customer</th>
                <th className="py-1.5">Facilities</th>
                <th className="py-1.5 text-right">Exposure</th>
                <th className="py-1.5 text-right">Loss</th>
                <th className="py-1.5 text-right">Worst stage</th>
                <th className="py-1.5 text-right">Max DPD</th>
                <th className="py-1.5 text-right">Behavioural</th>
                <th className="py-1.5 text-right">Application</th>
                <th className="py-1.5">Early Warning</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <CustomerRows
                  key={row.customer_id}
                  row={row}
                  checked={selected.has(row.customer_id)}
                  open={expanded.has(row.customer_id)}
                  onCheck={(on) =>
                    setSelected((was) => {
                      const next = new Set(was);
                      if (on) next.add(row.customer_id);
                      else next.delete(row.customer_id);
                      return next;
                    })
                  }
                  onToggle={() =>
                    setExpanded((was) => {
                      const next = new Set(was);
                      if (next.has(row.customer_id)) next.delete(row.customer_id);
                      else next.add(row.customer_id);
                      return next;
                    })
                  }
                />
              ))}
            </tbody>
          </table>

          <div className="mt-3 flex items-center justify-between text-[11px] text-text-muted">
            <span>
              Showing {offset + 1}–{Math.min(offset + PAGE, total)} of{" "}
              {total.toLocaleString("en-GB")}. {page?.pagination_note}
            </span>
            <span className="flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(offset - PAGE, 0))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </Button>
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Notes. */}
      <Card>
        <CardContent className="space-y-2 pt-4">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Notes
          </h4>
          {notes.map((note) => (
            <div key={`${note.note_id}-${note.version}`} className="text-xs">
              <p className="whitespace-pre-wrap text-text-primary">{note.body}</p>
              <p className="text-[11px] text-text-muted">
                {note.author || "unknown"} · {note.created_at} · version{" "}
                {note.version}
              </p>
            </div>
          ))}
          {!notes.length ? (
            <p className="text-xs text-text-muted">No notes yet.</p>
          ) : null}
          <div className="flex gap-2">
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              rows={2}
              placeholder="What you concluded, and what still has to be checked…"
              className="flex-1 rounded border border-border bg-surface px-2 py-1 text-xs"
            />
            <Button size="sm" variant="outline" disabled={busy !== ""} onClick={addNote}>
              Add note
            </Button>
          </div>
          <p className="text-[11px] text-text-muted">
            A note is kept with its author, its time and its earlier versions. It
            is content, not an instruction: nothing written here changes a
            permission, a policy or what this product will do.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function CustomerRows({
  row,
  checked,
  open,
  onCheck,
  onToggle,
}: {
  row: CohortCustomerRow;
  checked: boolean;
  open: boolean;
  onCheck: (on: boolean) => void;
  onToggle: () => void;
}) {
  const money = (value?: number | null) =>
    value === null || value === undefined
      ? "—"
      : Math.round(value).toLocaleString("en-GB");

  return (
    <>
      <tr className="border-b border-border/60">
        <td className="py-1.5">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onCheck(e.target.checked)}
            aria-label={`Select ${row.customer_id}`}
          />
        </td>
        <td className="py-1.5">
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex items-center gap-1 text-text-primary"
          >
            {open ? (
              <ChevronDown className="size-3" aria-hidden />
            ) : (
              <ChevronRight className="size-3" aria-hidden />
            )}
            <span className="mono">{row.customer_id}</span>
          </button>
          {row.state !== "covered" ? (
            <span className="ml-2 rounded bg-warning/15 px-1 text-[10px] text-warning">
              {row.because || row.state}
            </span>
          ) : null}
        </td>
        <td className="py-1.5">
          {row.included_facilities ?? 0} included
          {row.context_facilities ? ` · ${row.context_facilities} context` : ""}
        </td>
        <td className="py-1.5 text-right tabular-nums">{money(row.gca_sar)}</td>
        <td className="py-1.5 text-right tabular-nums">{money(row.ecl_sar)}</td>
        <td className="py-1.5 text-right tabular-nums">{row.worst_stage ?? "—"}</td>
        <td className="py-1.5 text-right tabular-nums">{row.max_dpd ?? "—"}</td>
        <td className="py-1.5 text-right tabular-nums">
          {row.behavioural_score ?? "—"}
        </td>
        <td className="py-1.5 text-right tabular-nums">
          {row.application_score ?? "—"}
        </td>
        <td className="py-1.5">
          <Sparkline points={row.ews?.series ?? []} />
        </td>
      </tr>
      {open ? (
        <tr className="border-b border-border/60 bg-surface-subtle">
          <td />
          <td colSpan={9} className="py-2">
            <p className="mb-1 text-[11px] text-text-muted">
              {row.pd_12m_basis}
            </p>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-text-muted">
                  <th className="py-1">Facility</th>
                  <th className="py-1">In the baseline</th>
                  <th className="py-1 text-right">Stage</th>
                  <th className="py-1 text-right">DPD</th>
                  <th className="py-1 text-right">Exposure</th>
                  <th className="py-1 text-right">PD 12m</th>
                  <th className="py-1 text-right">LGD</th>
                  <th className="py-1 text-right">Loss</th>
                </tr>
              </thead>
              <tbody>
                {row.facilities.map((facility) => (
                  <tr
                    key={facility.facility_id}
                    className={cn(!facility.included && "text-text-muted")}
                  >
                    <td className="py-1 mono">{facility.facility_id}</td>
                    <td className="py-1">
                      {facility.included ? "included" : "context only"}
                      <span className="ml-1 text-text-muted">
                        — {facility.included_because}
                      </span>
                    </td>
                    <td className="py-1 text-right">{facility.stage ?? "—"}</td>
                    <td className="py-1 text-right">{facility.dpd ?? "—"}</td>
                    <td className="py-1 text-right tabular-nums">
                      {money(facility.gca_sar)}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {facility.pd_12m === null || facility.pd_12m === undefined
                        ? "—"
                        : `${(facility.pd_12m * 100).toFixed(2)}%`}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {facility.lgd === null || facility.lgd === undefined
                        ? "—"
                        : `${(facility.lgd * 100).toFixed(1)}%`}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {money(facility.ecl_sar)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * The Early Warning series. A month with no observation is a GAP, drawn as a
 * gap: a flat line through a missing month is how a coverage problem becomes
 * a statement that nothing was wrong.
 */
function Sparkline({
  points,
}: {
  points: Array<{ month: string; score: number | null; band: string; state: string }>;
}) {
  if (!points.length) {
    return <span className="text-[11px] text-text-muted">no history</span>;
  }
  const scores = points
    .map((p) => p.score)
    .filter((s): s is number => s !== null);
  const top = scores.length ? Math.max(...scores, 1) : 1;
  return (
    <span className="inline-flex items-end gap-0.5" title={points
      .map((p) => `${p.month}: ${p.score ?? "no observation"}`)
      .join("\n")}>
      {points.map((point) => (
        <span
          key={point.month}
          className={cn(
            "w-1.5 rounded-sm",
            point.score === null
              ? "h-3 border border-dashed border-text-muted"
              : "bg-accent/70",
          )}
          style={
            point.score === null
              ? undefined
              : { height: `${Math.max((point.score / top) * 18, 2)}px` }
          }
          aria-label={
            point.score === null
              ? `${point.month}: no observation`
              : `${point.month}: ${point.score}`
          }
        />
      ))}
    </span>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd className="text-xs text-text-primary">{value}</dd>
    </div>
  );
}
