import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/cockpit"
      willDo={[
        "Accept a question in plain language, such as \"Why has Stage 2 increased?\"",
        "Show the interpreted intent and the investigation plan before running anything",
        "Execute the plan step by step against governed data, reporting progress",
        "Return charts, tables and a narrative that quotes only engine-produced figures",
        "Offer follow-up questions, and a Trace button on every result",
      ]}
      builtOn={[
        "Engine registry — the planner may only choose registered, runnable analyses",
        "Contract validation — a plan with an unknown analysis or bad parameter is rejected before execution",
        "Data Access Layer — governed datasets queried through DuckDB with pushdown",
      ]}
    />
  );
}
