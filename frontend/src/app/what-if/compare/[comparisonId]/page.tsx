"use client";

import { use } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { ComparisonPage } from "@/components/whatif/comparison-view";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function WhatIfComparisonPage({ params }: { params: Promise<{ comparisonId: string }> }) {
  const { comparisonId } = use(params);
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? <ComparisonPage comparisonId={comparisonId} /> : <GuidedOff what="Scenario comparisons" />}
    </main>
  );
}
