"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { backLabel, safeBack } from "@/lib/workspace/nav";

/**
 * "← Back to <origin>" when the page was opened from another module with a
 * `back=` origin; otherwise `fallback` (the page's logical parent) if given.
 * Rendered as a link, so it is a real navigation the browser can also undo.
 */
export function OriginBackLink({ fallback, fallbackLabel, testId = "origin-back" }: { fallback?: string; fallbackLabel?: string; testId?: string }) {
  const back = safeBack(useSearchParams().get("back"));
  const href = back || fallback || "";
  if (!href) return null;
  const label = back ? backLabel(back) : fallbackLabel ?? backLabel(href);
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-xs text-accent" data-testid={testId} data-back-target={href}>
      <ArrowLeft className="h-3 w-3" /> Back to {label}
    </Link>
  );
}
