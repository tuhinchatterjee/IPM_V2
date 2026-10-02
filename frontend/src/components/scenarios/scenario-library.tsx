"use client";

/**
 * The Scenario Library (§44, P4): it never opens empty. Templates, your own
 * drafts and combined scenarios in one searchable catalogue; tick two or more
 * to combine them into a NEW scenario after an overlap/conflict matrix and an
 * explicit composition choice. Nothing on this page executes a scenario.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { useSingleFlight } from "@/lib/workspace/single-flight";
import { Copy, GitMerge, Loader2, Plus, Search } from "lucide-react";

import { PreviewPanel } from "@/components/scenarios/preview-panel";
import { Badge } from "@/components/ui/badge";
import { SEVERITY_TONE } from "@/lib/workspace/scenario-figures";
import {
  cloneScenario,
  combinePreview,
  combineScenarios,
  listScenarios,
  type Listing,
  type Preview,
  type Resolution,
  type ScenarioCard,
} from "@/lib/workspace/scenarios";
import { cn } from "@/lib/utils";
import { urlWith, withBack } from "@/lib/workspace/nav";

const OWNERS = [
  ["", "All"],
  ["template", "Templates"],
  ["mine", "Mine"],
  ["shared", "Shared with me"],
] as const;
const SEVERITIES = ["upside", "mild", "moderate", "severe"];
const SELECTION_KEY = "gw.scenario-library.selection";

/** `raw` when it is one of `allowed`, else "" (an unknown URL value is ignored). */
function pick(raw: string | null, allowed: readonly string[]): string {
  return raw && allowed.includes(raw) ? raw : "";
}

function readSelection(): ScenarioCard[] {
  try {
    const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(SELECTION_KEY);
    const v = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(v) ? (v as ScenarioCard[]).filter((c) => c && typeof c.object_id === "string") : [];
  } catch {
    return [];
  }
}

function writeSelection(cards: ScenarioCard[]) {
  try {
    if (cards.length) window.sessionStorage.setItem(SELECTION_KEY, JSON.stringify(cards));
    else window.sessionStorage.removeItem(SELECTION_KEY);
  } catch {
    /* storage unavailable: the selection simply does not survive navigation */
  }
}

export function ScenarioLibrary() {
  const router = useRouter();
  // The filters live in the URL (`/scenarios?domain=retail&owner=mine&q=..`):
  // a link can open the library on a book, and browser Back from a scenario
  // returns to the same filtered list. The combine selection survives the
  // round trip in this tab's session storage.
  const params = useSearchParams();
  const asked = params.get("domain");
  const [domain, setDomain] = React.useState(asked === "corporate" || asked === "retail" ? asked : "");
  const [owner, setOwner] = React.useState(() => pick(params.get("owner"), OWNERS.map(([v]) => v)));
  const [severity, setSeverity] = React.useState(() => pick(params.get("severity"), SEVERITIES));
  const [tag, setTag] = React.useState(params.get("tag") ?? "");
  const [q, setQ] = React.useState(params.get("q") ?? "");
  const [query, setQuery] = React.useState(params.get("q") ?? "");
  const [loaded, setLoaded] = React.useState<{ key: string; listing: Listing | null; error: string }>({ key: "", listing: null, error: "" });
  const [selected, setSelectedState] = React.useState<ScenarioCard[]>(readSelection);
  const setSelected = React.useCallback((next: ScenarioCard[] | ((prev: ScenarioCard[]) => ScenarioCard[])) => {
    setSelectedState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      writeSelection(value);
      return value;
    });
  }, []);
  const [actionError, setActionError] = React.useState("");
  const flight = useSingleFlight();
  const [combining, setCombining] = React.useState<{ name: string; preview: Preview | null; error: string; busy: boolean } | null>(null);

  const key = JSON.stringify({ domain, owner, severity, tag, query });
  React.useEffect(() => {
    listScenarios({ domain, owner, severity, tag, q: query })
      .then((listing) => setLoaded({ key, listing, error: "" }))
      .catch((e: unknown) => setLoaded({ key, listing: null, error: e instanceof Error ? e.message : String(e) }));
  }, [domain, owner, severity, tag, query, key]);
  const listing = loaded.key === key ? loaded.listing : null;
  React.useEffect(() => {
    const next = urlWith({ domain, owner, severity, tag, q: query });
    if (next && next !== `${window.location.pathname}${window.location.search}`) router.replace(next, { scroll: false });
  }, [domain, owner, severity, tag, query, router]);
  const here = `/scenarios?${new URLSearchParams(Object.entries({ domain, owner, severity, tag, q: query }).filter(([, v]) => v)).toString()}`;

  function toggle(card: ScenarioCard) {
    setCombining(null);
    setSelected((prev) =>
      prev.some((p) => p.object_id === card.object_id) ? prev.filter((p) => p.object_id !== card.object_id) : [...prev, card].slice(-8),
    );
  }

  const sameBook = selected.length > 0 && selected.every((s) => s.domain_id === selected[0].domain_id);

  async function startCombine() {
    const name = selected.map((s) => s.name).join(" + ");
    setCombining({ name, preview: null, error: "", busy: true });
    try {
      const out = await combinePreview(
        selected.map((s) => ({ object_id: s.object_id, version: s.version })),
        name,
      );
      setCombining({ name, preview: out.preview, error: "", busy: false });
    } catch (e) {
      setCombining({ name, preview: null, error: e instanceof Error ? e.message : String(e), busy: false });
    }
  }

  async function saveCombined(resolutions: Record<string, Resolution>) {
    if (!combining) return;
    const name = combining.name;
    try {
      const out = await flight.run(() =>
        combineScenarios(
          selected.map((s) => ({ object_id: s.object_id, version: s.version })),
          name,
          resolutions,
        ),
      );
      if (out) {
        setSelected([]);
        router.push(withBack(`/scenarios/${out.scenario.object_id}`, here));
      }
    } catch (e) {
      setCombining((c) => (c ? { ...c, error: e instanceof Error ? e.message : String(e) } : c));
    }
  }

  async function cloneCard(objectId: string) {
    setActionError("");
    try {
      const copy = await flight.run(() => cloneScenario(objectId));
      if (copy) router.push(withBack(`/scenarios/${copy.object_id}`, here));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-4" data-testid="scenario-library">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text-primary">Scenario Library</h1>
        <span className="text-xs text-text-muted">
          Governed definitions. Opening, previewing, cloning or combining never calculates ECL.
        </span>
        <Link href={withBack("/scenarios/new", here)} className="ml-auto inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast" data-testid="scenario-new">
          <Plus className="h-4 w-4" /> New scenario
        </Link>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(q);
          }}
          className="flex items-center gap-1 rounded-md border border-border bg-surface px-2"
        >
          <Search className="h-4 w-4 text-text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, scope, component, tag…"
            className="w-72 bg-transparent py-1.5 text-sm outline-none"
            data-testid="scenario-search"
          />
        </form>
        <Segmented value={domain} onChange={setDomain} options={[["", "Both books"], ["corporate", "Corporate"], ["retail", "Retail"]]} testId="scenario-domain" />
        <Segmented value={owner} onChange={setOwner} options={OWNERS as unknown as [string, string][]} testId="scenario-owner" />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm" data-testid="scenario-severity" aria-label="Severity">
          <option value="">Any severity</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {listing && (
          <select value={tag} onChange={(e) => setTag(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm" data-testid="scenario-tag" aria-label="Tag">
            <option value="">Any tag</option>
            {Object.entries(listing.facets.tag)
              .sort((a, b) => b[1] - a[1])
              .map(([t, n]) => (
                <option key={t} value={t}>
                  {t} ({n})
                </option>
              ))}
          </select>
        )}
        {listing && (
          <span className="text-xs text-text-muted" data-testid="scenario-count" data-total={listing.total}>
            {listing.total} scenarios · Corporate {listing.facets.domain.corporate ?? 0} · Retail {listing.facets.domain.retail ?? 0}
          </span>
        )}
      </div>

      {selected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-accent bg-accent-muted p-2 text-sm" data-testid="scenario-selection">
          <span>
            {selected.length} selected: {selected.map((s) => s.template_id || s.name).join(", ")}
          </span>
          <button
            type="button"
            disabled={selected.length < 2 || !sameBook}
            onClick={() => void startCombine()}
            className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1 text-xs font-medium text-accent-contrast disabled:opacity-40"
            data-testid="scenario-combine"
          >
            <GitMerge className="h-3 w-3" /> Combine into a new scenario
          </button>
          {!sameBook && <span className="text-xs text-negative">Scenarios from different books do not combine.</span>}
          <button type="button" onClick={() => setSelected([])} className="text-xs underline">
            Clear
          </button>
        </div>
      )}

      {combining && (
        <section className="space-y-3 rounded-xl border border-border bg-surface-raised p-4" data-testid="scenario-combine-panel">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">Combine — originals are not changed</h2>
            <input
              value={combining.name}
              onChange={(e) => setCombining({ ...combining, name: e.target.value })}
              className="min-w-[20rem] flex-1 rounded border border-border bg-surface px-2 py-1 text-sm"
              data-testid="scenario-combine-name"
              aria-label="Combined scenario name"
            />
          </div>
          {combining.busy && (
            <p className="flex items-center gap-2 text-sm text-text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Building the component and overlap matrix…
            </p>
          )}
          {combining.error && <p className="text-sm text-negative">{combining.error}</p>}
          {combining.preview && (
            <>
              <PreviewPanel
                preview={combining.preview}
                onResolve={saveCombined}
                resolveLabel="Save combined scenario with these policies"
                testId="scenario-combine-preview"
              />
              {combining.preview.overlaps.every((o) => o.status !== "NEEDS_POLICY" && o.status !== "INVALID_POLICY") && (
                <button
                  type="button"
                  onClick={() => void saveCombined({})}
                  disabled={flight.busy}
                  className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-contrast disabled:opacity-50"
                  data-testid="scenario-combine-save"
                >
                  Save combined scenario
                </button>
              )}
            </>
          )}
        </section>
      )}

      {loaded.error && loaded.key === key && <p className="text-sm text-negative">{loaded.error}</p>}
      {actionError && (
        <p role="alert" className="text-sm text-negative" data-testid="scenario-library-error">
          {actionError}
        </p>
      )}
      {!listing && !loaded.error && (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Opening the library…
        </p>
      )}
      {listing && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="scenario-cards">
          {listing.scenarios.map((c) => (
            <ScenarioCardView
              key={c.object_id}
              card={c}
              selected={selected.some((s) => s.object_id === c.object_id)}
              onToggle={() => toggle(c)}
              onClone={() => void cloneCard(c.object_id)}
              back={here}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ScenarioCardView({ card, selected, onToggle, onClone, back }: { card: ScenarioCard; selected: boolean; onToggle: () => void; onClone: () => void; back: string }) {
  return (
    <article
      className={cn("flex flex-col rounded-xl border bg-surface p-3", selected ? "border-accent" : "border-border")}
      data-testid="scenario-card"
      data-object-id={card.object_id}
      data-template-id={card.template_id}
      data-domain={card.domain_id}
    >
      <div className="flex items-start gap-2">
        <input type="checkbox" checked={selected} onChange={onToggle} aria-label={`Select ${card.name}`} className="mt-1" data-testid="scenario-select" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1 text-[11px]">
            {card.template_id && <span className="font-mono text-text-muted">{card.template_id}</span>}
            <Badge variant={SEVERITY_TONE[card.severity] ?? "default"}>{card.severity}</Badge>
            <Badge variant="outline">{card.domain_id}</Badge>
            <Badge variant={card.is_template ? "info" : "accent"}>{card.is_template ? "template" : card.status.toLowerCase()}</Badge>
            <span className="text-text-muted">v{card.version}</span>
          </div>
          <Link href={withBack(`/scenarios/${card.object_id}`, back)} className="mt-1 block font-semibold text-text-primary hover:underline" data-testid="scenario-open">
            {card.name}
          </Link>
        </div>
      </div>
      <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{card.description}</p>
      <dl className="mt-2 space-y-0.5 text-xs">
        <div>
          <dt className="inline text-text-muted">Scope: </dt>
          <dd className="inline">{card.scope_label}</dd>
        </div>
        <div>
          <dt className="inline text-text-muted">Components: </dt>
          <dd className="inline">{card.components.map((c) => c.label).join(" · ")}</dd>
        </div>
        <div>
          <dt className="inline text-text-muted">Methods: </dt>
          <dd className="inline">{card.supported_methods.join(", ")}</dd>
        </div>
        <div className="text-text-muted">
          Owner {card.is_template ? "CreditProbe library" : card.owner_id} · stage {card.stage_policy} · results {card.results}
          {card.parents.length > 0 && ` · from ${card.parents.map((p) => p.name).join(" + ")}`}
        </div>
      </dl>
      <div className="mt-auto flex gap-2 pt-2 text-xs">
        <Link href={withBack(`/scenarios/${card.object_id}`, back)} className="rounded border border-border px-2 py-0.5">
          Open preview
        </Link>
        <button type="button" onClick={onClone} className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5" data-testid="scenario-clone">
          <Copy className="h-3 w-3" /> Clone
        </button>
      </div>
    </article>
  );
}

function Segmented({ value, onChange, options, testId }: { value: string; onChange: (v: string) => void; options: [string, string][]; testId: string }) {
  return (
    <div className="inline-flex rounded-md border border-border bg-surface p-0.5 text-xs" data-testid={testId} data-value={value}>
      {options.map(([v, label]) => (
        <button
          key={v || "all"}
          type="button"
          onClick={() => onChange(v)}
          className={cn("rounded px-2 py-1", value === v ? "bg-accent text-accent-contrast" : "text-text-secondary")}
          data-testid={`${testId}-${v || "all"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
