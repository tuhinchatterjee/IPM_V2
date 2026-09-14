"use client";

/**
 * The two books, and what is inside each one.
 *
 * A card per book with its release, its fingerprint, its period range and its
 * size, then a drill into any relation for its columns, their types, their
 * units and what each one means.
 *
 * The two cards are NOT two views of one dataset. Each names a different
 * release with a different fingerprint and a different set of relations, and
 * asking one card for the other's relation is refused by the server rather
 * than answered from the book in front of you.
 *
 * Nothing here writes. There is no button on this page that changes a
 * published release, because a published release is immutable by design and
 * a control that implied otherwise would be describing a capability this
 * build does not have.
 */

import * as React from "react";

import { readDomains, readSchema } from "./client";
import type {
  BookSchema,
  DomainAvailability,
  DomainId,
  DomainStatus,
} from "./client";

export function DataBooks() {
  const [availability, setAvailability] =
    React.useState<DomainAvailability | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    readDomains()
      .then((next) => live && setAvailability(next))
      .catch((exc: unknown) =>
        live && setError(exc instanceof Error ? exc.message : String(exc)),
      );
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <p data-testid="v4-data-unavailable" className="text-sm text-slate-600">
        The books could not be listed: {error}
      </p>
    );
  }
  if (!availability) {
    return <p className="text-sm text-slate-500">Reading the books…</p>;
  }

  return (
    <div data-testid="v4-data-books" className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Data</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Two books, each its own published release. Switching between them
          opens different bytes, not a filter over one dataset. A release is
          immutable once published, so nothing on this page changes one.
        </p>
      </header>
      {availability.domains.map((domain) => (
        <BookCard key={domain.domain_id} domain={domain} />
      ))}
    </div>
  );
}

function BookCard({ domain }: { domain: DomainStatus }) {
  const [schema, setSchema] = React.useState<BookSchema | null>(null);
  const [open, setOpen] = React.useState("");
  const [detail, setDetail] = React.useState<BookSchema | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!domain.ready) return;
    let live = true;
    readSchema(domain.domain_id as DomainId)
      .then((next) => live && setSchema(next))
      .catch((exc: unknown) =>
        live && setError(exc instanceof Error ? exc.message : String(exc)),
      );
    return () => {
      live = false;
    };
  }, [domain.domain_id, domain.ready]);

  const drill = React.useCallback(
    (relation: string) => {
      if (open === relation) {
        setOpen("");
        setDetail(null);
        return;
      }
      setOpen(relation);
      setDetail(null);
      readSchema(domain.domain_id as DomainId, relation)
        .then(setDetail)
        .catch((exc: unknown) =>
          setError(exc instanceof Error ? exc.message : String(exc)),
        );
    },
    [domain.domain_id, open],
  );

  if (!domain.ready) {
    return (
      <section
        data-testid={`v4-book-${domain.domain_id}`}
        data-state="unavailable"
        className="rounded-xl border border-slate-200 bg-white p-5"
      >
        <h2 className="text-lg font-semibold text-slate-900">
          {domain.domain_label}
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          Not published in this runtime: {domain.reason} Nothing was
          substituted for it.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid={`v4-book-${domain.domain_id}`}
      data-state={schema ? "ready" : "loading"}
      data-release={schema?.release_id ?? ""}
      className="rounded-xl border border-slate-200 bg-white p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">
          {domain.domain_label}
        </h2>
        {schema ? (
          <p className="font-mono text-xs text-slate-500">
            {schema.release_id} · {schema.release_fingerprint.slice(0, 16)}
          </p>
        ) : null}
      </div>

      {error ? (
        <p className="mt-2 text-sm text-rose-700">{error}</p>
      ) : null}

      {schema ? (
        <>
          <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-2 text-sm">
            <Fact term="Denomination">
              {schema.reporting_currency} {schema.amount_scale}
            </Fact>
            <Fact term="Frequency">{schema.reporting_frequency}</Fact>
            <Fact term="Periods">
              {schema.reporting_periods.length} to {schema.latest_period}
            </Fact>
            <Fact term="Relations">{schema.relations?.length ?? 0}</Fact>
            <Fact term="Rows">
              {(schema.total_rows ?? 0).toLocaleString("en")}
            </Fact>
          </dl>
          {schema.not_client_data ? (
            <p className="mt-2 text-xs text-slate-500">
              {schema.not_client_data}
            </p>
          ) : null}

          <ul className="mt-4 divide-y divide-slate-100 border-t border-slate-100">
            {(schema.relations ?? []).map((relation) => (
              <li key={relation.relation} className="py-2">
                <button
                  type="button"
                  data-testid={`v4-relation-${relation.relation}`}
                  aria-expanded={open === relation.relation}
                  onClick={() => drill(relation.relation)}
                  className="w-full text-left"
                >
                  <span className="font-mono text-sm text-slate-900">
                    {relation.relation}
                  </span>
                  <span className="ml-2 text-xs text-slate-500">
                    {relation.columns} columns ·{" "}
                    {relation.rows.toLocaleString("en")} rows
                  </span>
                  <span className="block text-xs text-slate-600">
                    {relation.grain}
                  </span>
                </button>
                {open === relation.relation ? (
                  <RelationDetail detail={detail} />
                ) : null}
              </li>
            ))}
          </ul>

          {schema.joins?.length ? (
            <div className="mt-4">
              <h3 className="text-xs uppercase tracking-wide text-slate-500">
                How these join
              </h3>
              <ul className="mt-2 space-y-1.5 text-xs text-slate-600">
                {schema.joins.map((join) => (
                  <li key={`${join.left}-${join.right}`}>
                    <span className="font-mono">{join.left}</span> →{" "}
                    <span className="font-mono">{join.right}</span> on{" "}
                    {join.on.join(", ")}
                    {join.warning ? (
                      <span className="block text-slate-500">
                        {join.warning}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function RelationDetail({ detail }: { detail: BookSchema | null }) {
  if (!detail) {
    return <p className="mt-2 text-xs text-slate-500">Reading columns…</p>;
  }
  return (
    <div
      data-testid={`v4-relation-detail-${detail.relation}`}
      className="mt-3 overflow-x-auto"
    >
      <p className="text-xs text-slate-600">{detail.description}</p>
      <p className="mt-1 text-xs text-slate-500">
        Key: {(detail.key_columns ?? []).join(", ")} · period column{" "}
        {detail.period_column}
      </p>
      <table className="mt-2 w-full min-w-[34rem] text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="py-1 pr-3 font-medium">Column</th>
            <th className="py-1 pr-3 font-medium">Type</th>
            <th className="py-1 pr-3 font-medium">Unit</th>
            <th className="py-1 pr-3 font-medium">Adds up</th>
            <th className="py-1 font-medium">Means</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {(detail.fields ?? []).map((field) => (
            <tr key={field.name}>
              <td className="py-1 pr-3 font-mono text-slate-900">
                {field.name}
              </td>
              <td className="py-1 pr-3 text-slate-600">{field.dtype}</td>
              <td className="py-1 pr-3 text-slate-600">{field.unit || "—"}</td>
              <td className="py-1 pr-3 text-slate-600">
                {field.aggregation === "additive" ? "yes" : "no"}
              </td>
              <td className="py-1 text-slate-600">{field.definition}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Fact({
  term,
  children,
}: {
  term: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {term}
      </dt>
      <dd className="text-slate-900">{children}</dd>
    </div>
  );
}
