"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Route-level error page. The shell stays usable; only this segment failed. */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Card className="border-negative/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-negative">
          <AlertTriangle className="size-4" aria-hidden />
          This page could not be loaded
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-text-secondary">
          Navigation still works — you can move to another area and come back.
        </p>
        <code className="block overflow-x-auto rounded-md border border-border bg-surface-sunken p-3 font-mono text-xs text-text-muted">
          {error.message}
          {error.digest ? ` (${error.digest})` : ""}
        </code>
        <Button variant="outline" size="sm" onClick={reset}>
          <RotateCcw aria-hidden />
          Try again
        </Button>
      </CardContent>
    </Card>
  );
}
