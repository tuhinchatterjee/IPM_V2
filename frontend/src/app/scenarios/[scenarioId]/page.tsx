"use client";

import { use } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { ScenarioDetail } from "@/components/scenarios/scenario-detail";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function ScenarioPage({ params }: { params: Promise<{ scenarioId: string }> }) {
  const { scenarioId } = use(params);
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[90rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? <ScenarioDetail scenarioId={scenarioId} /> : <GuidedOff what="Scenario definitions" />}
    </main>
  );
}
