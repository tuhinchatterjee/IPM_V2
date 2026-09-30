"use client";

import { Suspense } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { MetricCatalogue } from "@/components/metrics/metric-catalogue";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function MetricsPage() {
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? (
        <Suspense fallback={null}>
          <MetricCatalogue />
        </Suspense>
      ) : (
        <GuidedOff what="The Metric Catalogue" />
      )}
    </main>
  );
}
