"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useReturnTo } from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * Back — to wherever you actually came from.
 *
 * Method, Trace, a dataset and a saved analysis are all reachable from a
 * conversation and from their own index, so a fixed "Back to Trace & Lineage"
 * is wrong half the time. This reads the return context the link carried and
 * falls back to the index when there is none.
 *
 * The Suspense boundary is here rather than at every call site: reading the
 * query string suspends during prerender, and the fallback is the plain index
 * link — the correct thing to show while the real destination resolves.
 */
export function BackLink({
  href,
  label,
  className,
}: {
  /** Where Back goes when the screen was opened directly. */
  href: string;
  /** What Back says when the screen was opened directly. */
  label: string;
  className?: string;
}) {
  return (
    <React.Suspense fallback={<Plain href={href} label={label} className={className} />}>
      <Contextual href={href} label={label} className={className} />
    </React.Suspense>
  );
}

function Contextual({
  href,
  label,
  className,
}: {
  href: string;
  label: string;
  className?: string;
}) {
  const back = useReturnTo({ href, label });
  return <Plain href={back.href} label={back.label} className={className} />;
}

function Plain({
  href,
  label,
  className,
}: {
  href: string;
  label: string;
  className?: string;
}) {
  return (
    <Button variant="ghost" size="sm" asChild className={cn("-ml-2", className)}>
      <Link href={href}>
        <ArrowLeft aria-hidden />
        {label}
      </Link>
    </Button>
  );
}
