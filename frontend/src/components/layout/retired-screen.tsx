"use client";

/**
 * A screen that belongs to a book this installation does not serve.
 *
 * The retail conversion is a profile, not a fork: the corporate screens are
 * kept as code so the product can be configured back. But "not in the
 * navigation" is not the same as "not reachable" — a bookmark, a pasted link
 * or a browser history entry still opens the route, and what opened was a
 * corporate screen naming rating notches and sector stress, over a book that
 * is retired here, above a 503 from an endpoint with no data behind it.
 *
 * So the route answers. It says which screen was asked for, why this
 * installation does not serve it, and offers the screen that does the same
 * work on the retail book — which is what a direct link with no in-app history
 * needs: somewhere to go that exists.
 */

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/page-header";

export function RetiredScreen({
  title,
  reason,
  insteadHref,
  insteadLabel,
}: {
  title: string;
  reason: string;
  insteadHref: string;
  insteadLabel: string;
}) {
  return (
    <div className="space-y-5" data-testid="retired-screen">
      <PageHeader eyebrow="Not served here" title={title} description={reason} />
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-4">
          <span className="text-[12px] text-text-secondary">
            The retail book does the same work here:
          </span>
          <Button asChild size="sm" data-testid="retired-instead">
            <Link href={insteadHref}>{insteadLabel}</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
