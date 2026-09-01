/**
 * Typography, by the job the text is doing.
 *
 * The rule this file exists to enforce
 * ------------------------------------
 * **No component chooses a typeface.** It chooses a role, and the role decides.
 *
 * Before this existed, a font family and a pixel size were picked inline in
 * whichever component was being written that day. The result is the failure mode
 * you can see in any product that has grown for a while: an ordinary screen
 * title at 40px above an analysis title at 15, CreditProbe's prose set in the
 * same face as a column header, and four different ideas about what "small and
 * grey" means. None of that is a decision anyone made — it is the absence of
 * one.
 *
 * Why four typefaces and not one
 * ------------------------------
 * A single family across this product would flatten a distinction that is
 * load-bearing. Four kinds of text appear on the same screen and mean very
 * different things:
 *
 *   what CreditProbe wrote   — an interpretation, which is the machine's opinion
 *   what you asked           — your words, quoted back
 *   what the engine recorded — identifiers, versions, periods, SQL
 *   what you can act on      — a figure to read at a glance, a button to press
 *
 * In a product whose central claim is about *where a number came from*, a reader
 * should be able to tell those four apart without reading any of them. That is
 * what the typeface carries here, and it is why an interpretation is never set
 * in the same face as a figure.
 *
 * Sizes come from the scale in globals.css, never from a literal here.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

type Props<T extends React.ElementType> = {
  as?: T;
  className?: string;
  children?: React.ReactNode;
} & Omit<React.ComponentPropsWithoutRef<T>, "as" | "className" | "children">;

/* -------------------------------------------------------------------------- */
/*  CreditProbe's own voice                                                    */
/* -------------------------------------------------------------------------- */

/**
 * An interpretation, a finding, a narrative — anything the machine wrote.
 *
 * Set to be *read* rather than scanned: 15px, generous leading, and a measure
 * capped near 70 characters. A line of prose stretched across a 1600px monitor
 * is technically legible and nobody finishes it.
 */
export function AIResponse<T extends React.ElementType = "p">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "p") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-prose text-prose leading-[1.55] text-text-primary",
        "max-w-[68ch] [text-wrap:pretty]",
        className,
      )}
      {...rest}
    />
  );
}

/**
 * A second-rank line of CreditProbe prose — a caveat, a note under a figure.
 * Same voice, quieter.
 */
export function AISecondary<T extends React.ElementType = "p">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "p") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-prose text-body leading-[1.5] text-text-secondary",
        "max-w-[72ch] [text-wrap:pretty]",
        className,
      )}
      {...rest}
    />
  );
}

/* -------------------------------------------------------------------------- */
/*  The user's voice                                                           */
/* -------------------------------------------------------------------------- */

/**
 * What the person typed, quoted back to them.
 *
 * Deliberately not a chat bubble. This is an analytical workspace, and a
 * question here is the heading of the work that follows it rather than a
 * message in a thread — so it gets a distinct face and a tighter fit, and no
 * rounded speech shape.
 */
export function UserPrompt<T extends React.ElementType = "p">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "p") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-user font-medium leading-[1.4] tracking-[-0.006em] text-text-primary",
        "text-[0.9375rem]",
        className,
      )}
      {...rest}
    />
  );
}

/* -------------------------------------------------------------------------- */
/*  Titles                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The title of one analysis. Compact on purpose.
 *
 * The thing a reader came for is the figure underneath, and a title set larger
 * than the number it describes inverts that every single time.
 */
export function AnalysisTitle<T extends React.ElementType = "h3">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "h3") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-display text-analysis font-semibold leading-[1.25]",
        "tracking-[-0.011em] text-text-primary",
        className,
      )}
      {...rest}
    />
  );
}

/** A page title. 22px, and never the largest thing a reader has ever seen. */
export function PageTitle<T extends React.ElementType = "h1">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "h1") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-display text-page font-semibold leading-[1.2]",
        "tracking-[-0.016em] text-text-primary",
        className,
      )}
      {...rest}
    />
  );
}

/**
 * The Cockpit greeting, and nothing else in the product.
 *
 * This is the single place large type is allowed. It earns it by being the one
 * moment the product speaks to a person rather than about a portfolio.
 */
export function Greeting<T extends React.ElementType = "h1">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "h1") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-display text-greeting font-semibold leading-[1.12]",
        "tracking-[-0.024em] text-text-primary",
        className,
      )}
      {...rest}
    />
  );
}

/** A section heading inside a page. Small, and structural rather than loud. */
export function SectionTitle<T extends React.ElementType = "h2">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "h2") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-display text-[0.9375rem] font-semibold leading-[1.3]",
        "tracking-[-0.008em] text-text-primary",
        className,
      )}
      {...rest}
    />
  );
}

/* -------------------------------------------------------------------------- */
/*  Figures                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * A number to be read at a glance.
 *
 * Tabular figures are not a nicety here. A column of amounts whose digits do not
 * line up cannot be scanned for magnitude, which is the only reason anyone looks
 * at a column of amounts.
 */
export function MetricValue<T extends React.ElementType = "span">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "span") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-display font-semibold tabular-nums tracking-[-0.014em]",
        "text-text-primary",
        className,
      )}
      {...rest}
    />
  );
}

/** The unit beside a figure. Always present, never competing with the number. */
export function MetricUnit<T extends React.ElementType = "span">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "span") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-mono text-meta font-medium uppercase tracking-[0.06em]",
        "text-text-muted",
        className,
      )}
      {...rest}
    />
  );
}

/* -------------------------------------------------------------------------- */
/*  The machine's record                                                       */
/* -------------------------------------------------------------------------- */

/**
 * A technical label: a lane name, a status, the eyebrow above a page title.
 *
 * Monospace and letterspaced, because this is the register in which the product
 * says "this is what was recorded" rather than "this is what I think".
 */
export function TechnicalLabel<T extends React.ElementType = "span">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "span") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-mono text-eyebrow font-semibold uppercase tracking-[0.1em]",
        "text-text-muted",
        className,
      )}
      {...rest}
    />
  );
}

/**
 * Metadata beside a title: a period, a row count, a timestamp.
 * Quieter than a technical label and not shouted in capitals.
 */
export function MetadataLabel<T extends React.ElementType = "span">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "span") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-mono text-meta tabular-nums text-text-muted",
        className,
      )}
      {...rest}
    />
  );
}

/**
 * Something the reader may need to copy exactly: an identifier, a field name,
 * a version, a fragment of SQL.
 */
export function TraceCode<T extends React.ElementType = "code">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "code") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-mono text-meta text-text-secondary",
        "rounded bg-surface-sunken px-1.5 py-0.5",
        className,
      )}
      {...rest}
    />
  );
}

/** A whole block of it — a query, a plan, a payload. */
export function TraceBlock<T extends React.ElementType = "pre">({
  as,
  className,
  ...rest
}: Props<T>) {
  const Tag = (as ?? "pre") as React.ElementType;
  return (
    <Tag
      className={cn(
        "font-mono text-meta leading-[1.65] text-text-secondary",
        "overflow-x-auto rounded-md bg-surface-sunken p-3",
        "[tab-size:2]",
        className,
      )}
      {...rest}
    />
  );
}
