"use client";

import { ScenarioLibrary } from "@/components/scenarios/scenario-library";
import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function ScenariosPage() {
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[90rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? <ScenarioLibrary /> : <GuidedOff what="The Scenario Library" />}
    </main>
  );
}
