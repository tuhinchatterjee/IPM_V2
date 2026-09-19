"use client";

/**
 * What the Cockpit is reading, said on the page rather than assumed.
 *
 * A retail-only deployment has no book switcher, so nothing on screen would
 * otherwise name the source. That is the one thing a credit officer must not
 * have to take on trust: every figure below this line comes from the
 * published Cockpit Data domain, at a stated version, over a stated window,
 * in a stated currency.
 *
 * Every value is read from the release through `GET /domains`. Nothing here
 * is a constant, and a field the release does not publish is left out rather
 * than filled in.
 */

import * as React from "react";

import { readDomains, type DomainStatus } from "@/components/cockpit-v4/client";

function coverage(book: DomainStatus): string {
  const periods = book.periods ?? [];
  if (periods.length === 0) return "";
  const noun = book.period_noun || "period";
  const plural = periods.length === 1 ? noun : `${noun}s`;
  return `${periods.length} ${plural} ${periods[0]}–${periods[periods.length - 1]}`;
}

function denomination(book: DomainStatus): string {
  return [book.reporting_currency, book.amount_scale]
    .filter(Boolean)
    .join(" ");
}

export function CockpitSourceBadge() {
  const [book, setBook] = React.useState<DomainStatus | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    readDomains()
      .then((available) => {
        if (!live) return;
        const retail =
          available.domains.find((d) => d.domain_id === "retail") ?? null;
        setBook(retail);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  // Silent while unknown, and silent if it cannot be read. A badge that
  // guesses at the source is worse than no badge.
  if (failed || !book) return null;

  const facts = [
    book.reporting_frequency,
    coverage(book),
    denomination(book),
    book.release_id,
  ].filter(Boolean);

  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs
                 text-muted-foreground"
      data-testid="cockpit-source-badge"
    >
      <span className="font-medium text-foreground">
        Retail Cockpit · {book.domain_label || "Cockpit Data"}
      </span>
      {facts.map((fact) => (
        <span key={fact} className="before:mr-3 before:content-['·']">
          {fact}
        </span>
      ))}
      {book.analysis_ready === false && (
        <span className="text-amber-600 dark:text-amber-500">
          browse only — {book.reason || "analysis is not available"}
        </span>
      )}
    </div>
  );
}

export default CockpitSourceBadge;
