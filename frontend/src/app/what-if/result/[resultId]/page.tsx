"use client";

import { Suspense, use } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { ResultPage } from "@/components/whatif/result-page";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function WhatIfResultPage({ params }: { params: Promise<{ resultId: string }> }) {
  const { resultId } = use(params);
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? (
        <Suspense fallback={null}>
          <ResultPage resultId={resultId} />
        </Suspense>
      ) : <GuidedOff what="Scenario results" />}
    </main>
  );
}
