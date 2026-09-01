"use client";

import Link from "next/link";
import * as React from "react";
import {
  Archive,
  ArrowRight,
  Database,
  Inbox,
  MoreHorizontal,
  Pencil,
  Plus,
  Share2,
  ShieldCheck,
  Table2,
  Trash2,
  type LucideIcon,
} from "lucide-react";

import {
  ControlPlanePanel,
  MetadataAssistant,
} from "@/components/data-builder/control-plane";
import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DomainOverview, type Lifecycle } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { domainHref } from "@/lib/links";
import { cn } from "@/lib/utils";

/**
 * Data Builder landing.
 *
 * Domains first, because that is how a data office thinks about its estate: a
 * domain has an owner and a quality position, and datasets live inside it. Each
 * card reports what is actually in the database rather than a fixed list.
 *
 * The seven domains below are the standard CreditProbe starting set. Any that do not yet
 * exist are shown as available to create rather than hidden, so the intended
 * shape of the estate is visible from the first screen.
 */

//: How many installed datasets a card lists before it says "and N more".
//: Eight fills the card without making the grid scroll; the domain page shows
//: all of them.
const INSTALLED_SHOWN = 8;

const STANDARD_DOMAINS = [
  {
    name: "Core Portfolio / Facility",
    description: "Facilities, limits, exposure, utilisation, collateral and staging.",
    owner: "Credit Risk Analytics",
  },
  {
    name: "IFRS 9 / ECL",
    description: "Staging, PD, LGD, EAD, expected credit loss, overlays and coverage.",
    owner: "Group Finance",
  },
  {
    name: "Corporate Ratings",
    description: "Internal grades, external ratings, notch gaps and rating history.",
    owner: "Credit Risk Analytics",
  },
  {
    name: "Retail / SME Scorecards",
    description: "Scorecard outputs and behavioural indicators for the retail book.",
    owner: "Retail Risk",
  },
  {
    name: "Documents",
    description: "Document metadata and the links between papers and the analysis inside them.",
    owner: "Group Data Office",
  },
  {
    name: "Policies / Knowledge",
    description: "Policy text, the limits framework and methodology notes.",
    owner: "Credit Policy",
  },
  {
    name: "CreditProbe Operational Metadata",
    description: "Runs, traces, versions, usage and audit produced by CreditProbe itself.",
    owner: "Risk Technology",
  },
];

export const LIFECYCLE_ORDER: Lifecycle[] = ["draft", "mapped", "validated", "published"];

export function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  const variant =
    lifecycle === "published"
      ? "positive"
      : lifecycle === "validated"
        ? "accent"
        : lifecycle === "mapped"
          ? "info"
          : "default";
  return <Badge variant={variant}>{lifecycle}</Badge>;
}

export default function DataBuilderPage() {
  const canEdit = useCanEditData();
  const datasets = useAsync(() => api.datasets(), []);
  const catalog = useAsync(() => api.catalog(), []);
  const [nonce, setNonce] = React.useState(0);

  // Re-read after a rename, archive or delete. The counts and coverage on these
  // cards are read from the lake, so re-fetching is the only honest way to
  // reflect a change — patching them locally would invent a number.
  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);
  const domains = useAsync(() => api.domainOverview(), [nonce]);

  const all = domains.data?.domains ?? [];
  // §7: "Show the DATA DOMAINS. Under each domain show WHAT DATASETS HAVE
  // BEEN INSTALLED."
  //
  // The page rendered every domain row the API returns. On a bootstrapped
  // installation that is forty-five cards, thirty-eight of them archived
  // remnants of the bundled catalogue's own headings, and the summary tile
  // read "Domains defined 45 of 7" - a number that is both wrong-looking and
  // useless. A retired heading is not a data domain a client is looking for.
  //
  // Retired is not DELETED, and it is not hidden either: a steward can still
  // see and restore one below. It is off the primary screen because the
  // primary screen answers "what data does CreditProbe hold", and thirty-eight
  // empty headings are not an answer to that.
  const live = all.filter((d) => d.status !== "ARCHIVED");
  const retired = all.filter((d) => d.status === "ARCHIVED");

  const known = new Set(live.map((d) => d.name));
  const missing = STANDARD_DOMAINS.filter((s) => !known.has(s.name));

  const loading = domains.loading && !domains.data;
  const totalPublished = (datasets.data?.datasets ?? []).filter(
    (d) => d.lifecycle === "published",
  ).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Builder"
        description="Define what data exists and what it means. A steward brings a file in, maps it to governed fields, documents it, validates it and publishes it — at which point, and not before, the analytical engine can read it."
        status="live"
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link href="/data-builder/relationships">
                <Share2 aria-hidden />
                Relationships
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/data-builder/inbox">
                <Inbox aria-hidden />
                Data Inbox
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/data-builder/browse">
                <Table2 aria-hidden />
                Browse the data
              </Link>
            </Button>
            {canEdit && (
              <Button size="sm" asChild>
                <Link href="/data-builder/new">
                  <Plus aria-hidden />
                  Add dataset
                </Link>
              </Button>
            )}
          </>
        }
      />

      {!canEdit && <ReadOnlyNotice action="create, edit or publish datasets" />}

      {domains.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{domains.error}</Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryTile
              label="Domains defined"
              value={live.length}
              of={STANDARD_DOMAINS.length}
              loading={loading}
            />
            <SummaryTile
              label="Datasets published"
              value={totalPublished}
              of={datasets.data?.count ?? 0}
              loading={loading}
            />
            <SummaryTile
              label="Governed fields"
              value={catalog.data?.field_count ?? 0}
              loading={catalog.loading}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {loading
              ? [0, 1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-56 w-full" />
                ))
              : live.map((domain) => (
                  <DomainCard
                    key={domain.name}
                    domain={domain}
                    canEdit={canEdit}
                    onChanged={refresh}
                  />
                ))}
            {!loading &&
              missing.map((domain) => (
                <UncreatedDomainCard key={domain.name} domain={domain} />
              ))}
          </div>

          {!loading && retired.length > 0 && canEdit && (
            <details className="rounded-lg border border-border bg-surface-sunken px-4 py-3">
              <summary className="cursor-pointer list-none text-xs font-medium text-text-secondary hover:text-text-primary">
                Retired domains
                <span className="ml-2 font-normal text-text-muted">
                  {retired.length} heading{retired.length === 1 ? "" : "s"} from
                  the bundled catalogue, now empty
                </span>
              </summary>
              <p className="mt-2.5 max-w-prose text-xs text-text-muted">
                These held datasets that have since been filed under a business
                domain. They are kept rather than deleted so lineage on an
                older analysis still resolves, and a steward can restore one.
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {retired.map((domain) => (
                  <span
                    key={domain.name}
                    className="rounded border border-border bg-surface px-2 py-1 text-xs text-text-muted"
                  >
                    {domain.name}
                  </span>
                ))}
              </div>
            </details>
          )}

          {datasets.data?.count === 0 && (
            <EmptyState
              icon={Database}
              title="No datasets onboarded yet"
              description="The bundled portfolio was built by the data-lake script and is already governed. Use Add Dataset to bring a new source file in through the full workflow."
              action={
                canEdit ? (
                  <Button asChild size="sm">
                    <Link href="/data-builder/new">
                      <Plus aria-hidden />
                      Add Dataset
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          )}
        </>
      )}

      <MetadataAssistant scope="data" />

      {/*
        Governed-purpose resolution — which dataset answers each purpose, and
        which purposes nothing answers.

        This used to open the screen. It rendered as a wall of forty rows,
        most of them a purpose name beside a red "Unresolved" badge, above
        the domains a reader had come to look at. It is genuine and important
        diagnostic information: an unresolved purpose means every analysis
        needing it refuses to run. It is also the wrong first thing to show
        somebody, and on a deployment mid-onboarding it reads as a broken
        product rather than an unfinished estate.

        So it moved to the bottom, collapsed, and only for the two roles that
        can act on it. Nothing was removed and nothing is hidden from the
        people whose job it is: a Data Steward opens one disclosure. An
        Analyst, who cannot mark a dataset authoritative anyway, is no longer
        shown a diagnostic they cannot act on.
      */}
      {canEdit && (
        <details className="group rounded-lg border border-border bg-surface-sunken">
          <summary className="cursor-pointer list-none px-5 py-3 text-sm font-medium text-text-secondary hover:text-text-primary">
            Advanced diagnostics — governed purpose resolution
            <span className="ml-2 text-xs font-normal text-text-muted">
              which dataset answers each governed purpose
            </span>
          </summary>
          <div className="border-t border-border p-5">
            <ControlPlanePanel />
          </div>
        </details>
      )}

      <Card className="p-5">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">
          <ShieldCheck className="size-4 text-text-muted" aria-hidden />
          The publication gate
        </h3>
        <p className="text-sm leading-relaxed text-text-secondary">
          A dataset becomes visible to the analytical engine only when it is{" "}
          <strong>published</strong>. Draft and partially-mapped datasets cannot leak into an
          analysis, and a dataset with blocking quality errors cannot be published at all. The
          uploaded source file is kept unchanged, so any published figure can always be
          re-derived from exactly what the source system sent.
        </p>
      </Card>
    </div>
  );
}

/**
 * One domain, with what is in it and what can be done to it.
 *
 * Dataset count, period coverage and row count come from the published lake
 * rather than from the domain's own record, so the card describes the estate as
 * it actually stands. A domain with nothing published says so.
 *
 * Delete is offered only for an empty domain, and the backend refuses it again
 * for a domain that holds datasets — hiding the button is a courtesy, not the
 * control.
 */
function DomainCard({
  domain,
  canEdit,
  onChanged,
}: {
  domain: DomainOverview;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [menu, setMenu] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  const [name, setName] = React.useState(domain.name);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const archived = domain.status === "ARCHIVED";
  const coverage =
    domain.first_period && domain.last_period
      ? domain.first_period === domain.last_period
        ? domain.first_period
        : `${domain.first_period} → ${domain.last_period}`
      : "No published periods";

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      setMenu(false);
      setRenaming(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className={cn("flex h-full flex-col p-5", archived && "opacity-70")}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <Database className="size-5 shrink-0 text-text-muted" aria-hidden />
        <div className="flex items-center gap-1.5">
          {archived && <Badge variant="default">Archived</Badge>}
          <Badge variant={domain.dataset_count ? "positive" : "default"}>
            {domain.dataset_count
              ? `${domain.dataset_count} dataset${domain.dataset_count === 1 ? "" : "s"}`
              : "Empty"}
          </Badge>
          {canEdit && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setMenu((m) => !m)}
                aria-label={`Actions for ${domain.name}`}
                className="rounded p-1 text-text-muted hover:bg-surface-hover hover:text-text-primary"
              >
                <MoreHorizontal className="size-4" aria-hidden />
              </button>
              {menu && (
                <div className="absolute right-0 top-full z-20 mt-1 w-56 rounded-lg border border-border bg-surface py-1 shadow-lg">
                  <MenuItem
                    icon={Pencil}
                    label="Rename"
                    onClick={() => {
                      setRenaming(true);
                      setMenu(false);
                    }}
                  />
                  <MenuItem
                    icon={Archive}
                    label={archived ? "Restore to active" : "Archive"}
                    onClick={() =>
                      void run(() =>
                        api.setDomainStatus(
                          domain.name,
                          archived ? "ACTIVE" : "ARCHIVED",
                        ),
                      )
                    }
                  />
                  <MenuItem
                    icon={Trash2}
                    label="Delete"
                    tone="negative"
                    disabled={domain.dataset_count > 0}
                    hint={
                      domain.dataset_count > 0
                        ? "Move or archive its datasets first"
                        : undefined
                    }
                    onClick={() => void run(() => api.deleteDomain(domain.name))}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {renaming ? (
        <input
          autoFocus
          value={name}
          disabled={busy}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim() && name !== domain.name) {
              void run(() => api.renameDomain(domain.name, name.trim()));
            }
            if (e.key === "Escape") {
              setName(domain.name);
              setRenaming(false);
            }
          }}
          onBlur={() => {
            if (name.trim() && name !== domain.name) {
              void run(() => api.renameDomain(domain.name, name.trim()));
            } else {
              setRenaming(false);
            }
          }}
          aria-label="Domain name"
          className="w-full border-b border-accent bg-transparent text-sm font-semibold text-text-primary focus:outline-none"
        />
      ) : (
        <Link
          href={domainHref(domain.name)}
          className="text-sm font-semibold text-text-primary hover:text-accent"
        >
          {domain.name}
        </Link>
      )}

      <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
        {domain.description || "No description recorded."}
      </p>

      {/*
        What is actually installed in this domain, by name.

        The card used to say "26 datasets" and stop. A reader looking at
        "Core Portfolio / Facility · 26 datasets" cannot tell whether their
        collateral register is in there, which is the only question they came
        to the screen with. A count is a fact about the estate; the names are
        the estate.

        A domain with nothing installed says so plainly, with the reason. That
        is a true statement about the deployment — the Documents domain is
        real and empty until somebody onboards a document — and it is more
        useful than hiding the heading, which would leave a reader unable to
        tell "none installed" from "not supported".
      */}
      <div className="mt-3 flex-1">
        {domain.datasets && domain.datasets.length > 0 ? (
          <ul className="space-y-1">
            {domain.datasets.slice(0, INSTALLED_SHOWN).map((d) => (
              <li key={d.name} className="flex items-baseline gap-1.5 text-xs">
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    d.readable && d.lifecycle === "published"
                      ? "bg-positive"
                      : "bg-text-muted",
                  )}
                  aria-hidden
                />
                <span className="truncate text-text-secondary">
                  {d.business_name || d.name}
                </span>
                {d.is_synthetic && (
                  <span className="shrink-0 text-[10px] uppercase tracking-wide text-text-muted">
                    synthetic
                  </span>
                )}
              </li>
            ))}
            {domain.datasets.length > INSTALLED_SHOWN && (
              <li className="text-xs text-text-muted">
                and {domain.datasets.length - INSTALLED_SHOWN} more
              </li>
            )}
          </ul>
        ) : (
          <p className="text-xs italic text-text-muted">
            Nothing installed in this domain yet.
          </p>
        )}
      </div>

      {error && <p className="mt-2 text-[11px] text-negative">{error}</p>}

      <dl className="mt-4 space-y-1 border-t border-border pt-3 text-[11px]">
        <Row label="Owner" value={domain.owner || "—"} />
        <Row
          label="Published"
          value={
            domain.dataset_count
              ? `${domain.published_count} of ${domain.dataset_count}`
              : "—"
          }
        />
        <Row label="Period coverage" value={coverage} />
        <Row
          label="Rows"
          value={domain.row_count ? domain.row_count.toLocaleString() : "—"}
        />
      </dl>

      <Link
        href={domainHref(domain.name)}
        className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent"
      >
        Open domain
        <ArrowRight className="size-3" aria-hidden />
      </Link>
    </Card>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  tone,
  disabled,
  hint,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  tone?: "negative";
  disabled?: boolean;
  hint?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={hint}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40",
        tone === "negative" ? "text-negative" : "text-text-primary",
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}

/** A domain in the standard set that has not been created here yet. */
function UncreatedDomainCard({
  domain,
}: {
  domain: (typeof STANDARD_DOMAINS)[number];
}) {
  return (
    <Card className="flex h-full flex-col border-dashed p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <Database className="size-5 shrink-0 text-text-muted" aria-hidden />
        <Badge variant="outline">Not created</Badge>
      </div>
      <h3 className="text-sm font-semibold text-text-muted">{domain.name}</h3>
      <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">
        {domain.description}
      </p>
      <dl className="mt-4 space-y-1 border-t border-border pt-3 text-[11px]">
        <Row label="Suggested owner" value={domain.owner} />
      </dl>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-text-muted">{label}</dt>
      <dd className="truncate pl-2 text-text-secondary">{value}</dd>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  of,
  loading,
}: {
  label: string;
  value: number;
  of?: number;
  loading?: boolean;
}) {
  return (
    <Card className="p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <p className="display-num mt-1.5 text-2xl font-semibold text-text-primary tabular">
          {value}
          {/* "9 of 7" is not a fraction, it is a bug that reads as one. The
              comparison only means something while the count is below it. */}
          {of !== undefined && value <= of && (
            <span className="ml-1 text-sm font-normal text-text-muted">of {of}</span>
          )}
        </p>
      )}
    </Card>
  );
}
