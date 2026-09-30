"use client";

import { Suspense } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { ScenarioBuilder } from "@/components/scenarios/scenario-builder";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function NewScenarioPage() {
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[90rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? (
        <Suspense fallback={null}>
          <ScenarioBuilder />
        </Suspense>
      ) : (
        <GuidedOff what="The scenario builder" />
      )}
    </main>
  );
}
