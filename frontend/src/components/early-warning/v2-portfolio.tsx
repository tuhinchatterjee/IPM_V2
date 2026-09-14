"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  api,
  type EarlyWarningV2BorrowerRow,
  type EarlyWarningV2Segments,
  type EwsDashboard,
  type EwsFilterContract,
} from "@/lib/api";
import { saveBlob } from "@/lib/downloads";
import { EwsFilterBar } from "@/components/early-warning/filter-bar";
import * as flt from "@/components/early-warning/filters";
import { money, moneyCell, MONEY_COLUMN_UNIT } from "@/lib/early-warning-format";
import { useAsync } from "@/lib/hooks";
import { BorrowerDrilldown } from "@/components/early-warning/borrower-drilldown";
import { InterpretationPanel } from "@/components/early-warning/interpretation-panel";
import { EarlyWarningChat } from "@/components/early-warning/ews-chat";
import { PortfolioInsight } from "@/components/early-warning/portfolio-insight";
import { LevelView } from "@/components/early-warning/level-view";
import { TrendChart } from "@/components/analytics/charts";
import * as sel from "@/components/early-warning/selection";

/**
 * Early Warning V2 — the consolidated portfolio view.
 *
 * This is the ONE canonical Early Warning experience (spec Section D): the
 * classifier/trigger/accelerator/network engine in backend/early_warning/
 * scored against the actual workbook mathematics, not the legacy fitted
 * Forward Risk Signal or the separate rule-based taxonomy shown further
 * down this page while that migration completes.
 */

const BAND_VARIANT: Record<string, "negative" | "warning" | "info" | "positive" | "default"> = {
  VERY_HIGH: "negative",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "default",
  VERY_LOW: "positive",
};

const BAND_LABEL: Record<string, string> = {
  VERY_HIGH: "Very High",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  VERY_LOW: "Very Low",
};

/**
 * Enough of the filter registry to read the address on the FIRST render,
 * before the contract has arrived. The server's registry is still the
 * authority — this is only what a link is allowed to have carried, and a key
 * it does not name is simply not seeded.
 */
const SEED_COLUMNS: flt.FilterColumn[] = [
  ...["segment", "ews_band", "ta_band", "classifier_band", "dominant_driver"]
    .map((key) => ({ key, label: key, kind: "multi" as const, field: key, choices: [], unit: "" })),
  ...["exposure", "dpd", "ews_score", "ta_score", "classifier_score"]
    .map((key) => ({ key, label: key, kind: "range" as const, field: key, choices: [], unit: "" })),
];

function BandBadge({ band }: { band: string }) {
  return (
    <Badge variant={BAND_VARIANT[band] ?? "default"}>{BAND_LABEL[band] ?? band}</Badge>
  );
}

/**
 * Selection state lives in the URL query string (`?band=&segment=&customer=`)
 * — the same convention the legacy Early Warning screen already proves out
 * with `?facility=`. That is what lets Back, Forward and a shared link carry
 * a reader from the portfolio into a band, into a segment, into a borrower,
 * and back out again, with no bespoke history machinery of its own.
 *
 * Each selection is PUSHED, not replaced. Replacing writes the URL without
 * creating a history entry, which makes a shared link work and Back a lie:
 * the readiness run found that walking back from a band, a segment and a
 * grade left the Early Warning page entirely on the first press, because
 * three selections had left no trace to walk. A reader who drills four
 * levels deep and wants the third one back presses Back, and it has to be
 * there.
 *
 * And because the URL is pushed rather than navigated, React is not told
 * when the browser walks it — so `popstate` reads the query string back
 * into state. Without that the address bar and the screen disagree after
 * every Back, which is worse than no history at all.
 */
function useUrlSelection() {
  const query = useSearchParams();
  const [state, setState] = React.useState<sel.Selection>(() => ({
    band: query.get("band"),
    segment: query.get("segment"),
    customer: query.get("customer"),
    level: query.get("level"),
  }));

  React.useEffect(() => {
    const walked = () => setState(sel.read(window.location.search));
    window.addEventListener("popstate", walked);
    return () => window.removeEventListener("popstate", walked);
  }, []);

  const patch = React.useCallback(
    (next: Partial<sel.Selection>) => {
      // Read from the URL rather than from state. The URL is what Back and
      // Forward move, so it is the one place that is always current — state
      // mirrors it. That also keeps this callback stable, which matters
      // because it is handed to the level view and both tables.
      const current = sel.read(window.location.search);
      const merged = sel.merge(current, next);
      // A selection that changes nothing is not a step back to anywhere.
      // Pushing it would make Back a no-op the first time it is pressed.
      if (!sel.isAStep(current, merged)) return;
      // Pushed OUTSIDE any state updater. React deliberately calls an
      // updater twice to surface impure ones, and with the push inside it
      // every selection wrote two identical history entries — so the first
      // Back appeared to do nothing at all.
      const url = new URL(window.location.href);
      url.search = sel.write(merged);
      window.history.pushState(window.history.state, "", url);
      setState(merged);
    },
    [],
  );

  return { ...state, patch };
}


/* -------------------------------------------------------------- pieces */

function Kpi({ title, value, note }: { title: string; value: string; note?: string }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-2xl font-semibold">
        {value}
        {note && (
          <span className="ml-1 text-sm font-normal text-text-secondary">{note}</span>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * A sortable column heading.
 *
 * The sort is server-side, like the filter: sorting a fetched page puts the
 * largest of twenty at the top and calls it the largest exposure.
 */
function SortHeader({
  field,
  state,
  onSort,
  children,
}: {
  field: string;
  state: flt.FilterState;
  onSort: (next: flt.FilterState) => void;
  children: React.ReactNode;
}) {
  const active = state.sortBy === field;
  return (
    <th
      className="py-1.5 pr-3 font-normal"
      aria-sort={active ? (state.descending ? "descending" : "ascending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(flt.sortOn(state, field))}
        className={`inline-flex items-center gap-1 hover:text-text-primary ${
          active ? "font-medium text-text-primary" : ""
        }`}
      >
        {children}
        {active && <span aria-hidden>{state.descending ? "\u2193" : "\u2191"}</span>}
      </button>
    </th>
  );
}

/**
 * Where the reader is in the result, said in obligors rather than in pages.
 *
 * "51-100 of 213" answers "how much of this have I seen?"; "page 2" does not,
 * because a page is a fact about the fetch.
 */
function Pager({
  offset,
  shown,
  total,
  onPage,
}: {
  offset: number;
  shown: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (total <= shown && offset === 0) return null;
  const size = shown || 50;
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-text-secondary">
      <span className="tabular">
        {offset + 1}\u2013{offset + shown} of {total.toLocaleString()}
      </span>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={offset === 0}
          onClick={() => onPage(Math.max(0, offset - size))}
        >
          Previous
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={offset + shown >= total}
          onClick={() => onPage(offset + size)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function EarlyWarningV2Portfolio() {
  const selection = useUrlSelection();
  const segments = useAsync<EarlyWarningV2Segments>(
    () => api.earlyWarningV2Segments(),
    [],
  );

  // The filter registry drives the controls, so adding a filterable column is
  // one entry in the backend registry and nothing here. §28.
  const contract = useAsync<EwsFilterContract>(
    () => api.earlyWarningV2DashboardContract(),
    [],
  );
  const columns = contract.data?.columns ?? [];

  /**
   * ONE idea of what is being looked at.
   *
   * The band and the segment used to live in their own URL keys, read by
   * their own state, while the table filtered its fetched rows separately —
   * which is how the tiles came to describe the book while the table
   * described a band. They are filters, so they live in the filter state
   * with every other filter, and the band chips and the segment table write
   * into it like the controls above them do.
   *
   * Seeded from the address on the first render only. The URL is written
   * back from the state afterwards; reading it again would be a second
   * opinion about what the reader asked for.
   */
  const [state, setState] = React.useState<flt.FilterState>(() => {
    if (typeof window === "undefined") return flt.EMPTY;
    const query = new URLSearchParams(window.location.search);
    // `?band=` and `?segment=` are the keys the older screen wrote, and
    // links carrying them are still in people's histories and messages.
    const seeded = flt.fromQuery(window.location.search, SEED_COLUMNS);
    for (const [legacy, key] of [["band", "ews_band"], ["segment", "segment"]] as const) {
      const value = query.get(legacy);
      if (value && !seeded.selections[key]) seeded.selections[key] = [value];
    }
    return seeded;
  });

  const chosenSegments = state.selections.segment ?? [];

  // Debounced, because a range box fires on every keystroke and each one is a
  // request against three hundred obligors. §33.
  const [settled, setSettled] = React.useState(state);
  React.useEffect(() => {
    if (flt.sameRequest(settled, state)) return;
    const timer = setTimeout(() => setSettled(state), 250);
    return () => clearTimeout(timer);
  }, [state, settled]);

  const specKey = JSON.stringify(flt.toSpec(settled));
  const dashboard = useAsync<EwsDashboard>(
    () => api.earlyWarningV2Dashboard(flt.toSpec(settled)),
    [specKey],
  );

  // The address carries the filter, so a narrowed view can be shared and
  // walked back to. Replaced rather than pushed: typing into a range box is
  // not four steps a reader wants to press Back through.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const query = new URLSearchParams(flt.toQuery(settled));
    // Everything in the address that is NOT this filter is carried through.
    //
    // An allow-list of the two keys this component happened to know about
    // silently deleted the third: the chat pushed `?thread=` and the very
    // next render of this effect wrote the address back without it, so Back
    // returned to a thread id that was no longer anywhere and the
    // conversation could not be found. A component that writes the whole
    // query string owns every key in it, including the ones it has never
    // heard of.
    const mine = new Set(flt.toQuery({ ...settled, offset: 0 }).length
      ? Array.from(new URLSearchParams(flt.toQuery(settled)).keys()) : []);
    for (const column of SEED_COLUMNS) {
      mine.add(column.key);
      mine.add(`${column.key}_min`);
      mine.add(`${column.key}_max`);
    }
    for (const owned of ["period", "q", "sort", "dir", "band", "segment"]) {
      mine.add(owned);
    }
    for (const [key, value] of url.searchParams.entries()) {
      if (!mine.has(key) && !query.has(key)) query.set(key, value);
    }
    const next = query.toString();
    if (next === url.searchParams.toString()) return;
    url.search = next;
    window.history.replaceState(window.history.state, "", url);
  }, [settled]);

  const [exporting, setExporting] = React.useState(false);
  const [exportError, setExportError] = React.useState("");

  async function exportBook() {
    setExporting(true);
    setExportError("");
    try {
      // The SAME scope the screen is showing. A download that quietly took
      // the unfiltered book would be a different answer under the same button.
      const file = await api.earlyWarningV2Export(flt.toSpec(settled));
      saveBlob(file.blob, file.filename);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  if (dashboard.loading && !dashboard.data) {
    return <Skeleton className="h-96 w-full" />;
  }
  if (dashboard.error && !dashboard.data) {
    return (
      <EmptyState
        title="Early Warning V2 data is not built yet"
        description="Run scripts/build_corporate_universe.py then scripts/build_early_warning_v2.py to generate the governed monthly domain."
      />
    );
  }
  if (!dashboard.data) return <Skeleton className="h-96 w-full" />;

  const { kpis, distribution, trend, rows, row_count, scope } = dashboard.data;
  const chosenBands = state.selections.ews_band ?? [];
  const empty = row_count === 0;

  return (
    <div className="space-y-5">
      <EarlyWarningChat
        customerId={selection.customer}
        scopeLabel={scope.active ? scope.sentence : ""}
        dashboardScope={scope.active ? flt.toSpec(settled) : undefined}
        uiState={{ level: selection.level ?? undefined }}
        onOpenBorrower={(id) => selection.patch({ customer: id })}
      />

      <PortfolioInsight />

      <EwsFilterBar
        columns={columns}
        facets={dashboard.data.facets}
        state={state}
        chips={scope.chips}
        matched={scope.matched}
        population={scope.population}
        busy={dashboard.loading}
        onChange={setState}
        onExport={exportBook}
        exporting={exporting}
        exportError={exportError}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi title="Portfolio EWS, exposure-weighted" value={kpis.portfolio_ews.toFixed(1)} />
        <Kpi
          title={scope.active ? "In scope, at High or above" : "Borrowers at High or above"}
          value={String(kpis.high_plus_count)}
          note={`of ${kpis.borrower_count}`}
        />
        <Kpi title="Exposure at High or above" value={money(kpis.high_plus_exposure)} />
        <Kpi
          title={scope.active ? "Exposure in scope" : "Total exposure"}
          value={money(kpis.total_exposure)}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {distribution.map((band) => (
          <button
            key={band.band}
            type="button"
            onClick={() => setState(flt.toggle(state, "ews_band", band.band))}
            className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
              chosenBands.includes(band.band)
                ? "border-accent bg-accent-muted"
                : "border-border bg-surface hover:border-border-strong"
            }`}
          >
            <div className="flex items-center gap-2 font-medium">
              <BandBadge band={band.band} />
              <span>{band.borrower_count} ({band.borrower_pct.toFixed(1)}%)</span>
            </div>
            <div className="text-text-secondary">
              {money(band.exposure)} · {band.exposure_pct.toFixed(1)}% of exposure
            </div>
          </button>
        ))}
      </div>

      {trend.points.length >= 3 && (
        <Card>
          <CardHeader>
            <CardTitle>
              {trend.basis === "current_snapshot_cohort"
                ? `These ${trend.cohort_size} obligors, month by month`
                : "Portfolio Early Warning score by month"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <TrendChart
              data={trend.points.map((t) => ({
                period: t.period,
                ews: t.portfolio_ews,
                high: t.high_plus_count,
              }))}
              xKey="period"
              series={[
                { key: "ews", label: "Portfolio EWS", slot: 0 },
                { key: "high", label: "Obligors at high or above", slot: 1 },
              ]}
              height={220}
              area
            />
            {/* The basis, printed rather than assumed. A cohort trend shown
                as a portfolio trend is a survivorship claim nobody made. */}
            <p className="mt-2 text-xs text-text-muted">{trend.note}</p>
          </CardContent>
        </Card>
      )}

      {chosenBands.length === 1 && (
        <InterpretationPanel
          band={chosenBands[0]}
          label={`${BAND_LABEL[chosenBands[0]] ?? chosenBands[0]} risk`}
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            {scope.active ? "Borrowers in scope" : "Borrowers by Early Warning score"}
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {empty ? (
            <EmptyState
              title="No obligors match this filter"
              description={`Nothing in ${scope.period || "this month"} matches ${scope.sentence}. Clear a filter to widen the population.`}
              action={
                <Button size="sm" variant="outline" onClick={() => setState(flt.clearAll(state))}>
                  Clear all filters
                </Button>
              }
            />
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-text-secondary">
                    <SortHeader field="customer_name" state={state} onSort={setState}>Customer</SortHeader>
                    <SortHeader field="segment" state={state} onSort={setState}>Segment</SortHeader>
                    <SortHeader field="exposure" state={state} onSort={setState}>
                      Exposure ({MONEY_COLUMN_UNIT})
                    </SortHeader>
                    <SortHeader field="dpd" state={state} onSort={setState}>DPD</SortHeader>
                    <SortHeader field="ews_score" state={state} onSort={setState}>EWS</SortHeader>
                    <SortHeader field="ta_score" state={state} onSort={setState}>T&amp;A</SortHeader>
                    <SortHeader field="classifier_score" state={state} onSort={setState}>
                      Classifier
                    </SortHeader>
                    <SortHeader field="dominant_driver" state={state} onSort={setState}>
                      Dominant driver
                    </SortHeader>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row: EarlyWarningV2BorrowerRow) => (
                    <tr
                      key={row.customer_id}
                      className={`cursor-pointer border-b border-border/60 hover:bg-surface-hover ${
                        selection.customer === row.customer_id ? "bg-accent-muted/40" : ""
                      }`}
                      onClick={() =>
                        selection.patch({
                          customer: selection.customer === row.customer_id ? null : row.customer_id,
                        })
                      }
                    >
                      <td className="py-1.5 pr-3 font-medium text-accent">{row.customer_name}</td>
                      <td className="py-1.5 pr-3 text-text-secondary">{row.segment}</td>
                      <td className="py-1.5 pr-3">{moneyCell(row.exposure)}</td>
                      <td className="py-1.5 pr-3">{row.dpd}</td>
                      <td className="py-1.5 pr-3">
                        <div className="flex items-center gap-1.5">
                          <BandBadge band={row.ews_band} />
                          <span className="text-text-secondary">{row.ews_score.toFixed(1)}</span>
                        </div>
                      </td>
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {row.ta_band} ({row.ta_score.toFixed(1)})
                      </td>
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {row.classifier_band} ({row.classifier_score.toFixed(1)})
                      </td>
                      <td className="py-1.5 pr-3 text-text-secondary">
                        {row.dominant_driver ?? "\u2014"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager
                offset={dashboard.data.offset}
                shown={rows.length}
                total={row_count}
                onPage={(offset) => setState(flt.page(state, offset))}
              />
            </>
          )}
        </CardContent>
      </Card>

      {selection.customer && (
        <BorrowerDrilldown
          customerId={selection.customer}
          onClose={() => selection.patch({ customer: null })}
        />
      )}

      <LevelView
        field={selection.level ?? "segment"}
        onChangeField={(field) => selection.patch({ level: field })}
        onOpenGroup={(field, value) => {
          if (field === "segment") setState(flt.toggle(state, "segment", value));
        }}
      />

      {segments.data && (
        <Card>
          <CardHeader>
            <CardTitle>By segment</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="py-1.5 pr-3">Segment</th>
                  <th className="py-1.5 pr-3">Borrowers</th>
                  <th className="py-1.5 pr-3">Exposure ({MONEY_COLUMN_UNIT})</th>
                  <th className="py-1.5 pr-3">Portfolio EWS</th>
                  <th className="py-1.5 pr-3">High+</th>
                </tr>
              </thead>
              <tbody>
                {segments.data.segments.map((seg) => (
                  <tr
                    key={seg.segment}
                    className={`cursor-pointer border-b border-border/60 hover:bg-surface-hover ${
                      chosenSegments.includes(seg.segment) ? "bg-accent-muted/40" : ""
                    }`}
                    onClick={() => setState(flt.toggle(state, "segment", seg.segment))}
                  >
                    <td className="py-1.5 pr-3 font-medium">{seg.segment}</td>
                    <td className="py-1.5 pr-3">{seg.borrower_count}</td>
                    <td className="py-1.5 pr-3">{moneyCell(seg.exposure)}</td>
                    <td className="py-1.5 pr-3">{seg.portfolio_ews.toFixed(1)}</td>
                    <td className="py-1.5 pr-3">{seg.high_plus_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {chosenSegments.length === 1 && (
        <InterpretationPanel
          segment={chosenSegments[0]}
          label={chosenSegments[0]}
        />
      )}
    </div>
  );
}
