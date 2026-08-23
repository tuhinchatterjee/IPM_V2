import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/trace"
      willDo={[
        "Show how an analysis was created, as a pannable, zoomable graph",
        "Make every node clickable — dataset, fields, filters with row counts, parameters, function version, intermediate and final results",
        "Draw governed nodes distinctly from interpretive ones, so the boundary between engine and model is visible",
        "Accept a plain-English change (\"use EAD rather than borrower count\"), preview exactly which nodes it affects, then branch to a new version",
        "Re-run only the affected steps, and preserve the original Trace unchanged",
      ]}
      builtOn={[
        "Trace graph model — nodes, edges, cycle detection and deterministic layered layout",
        "Content hashing — a change invalidates precisely the nodes downstream of it, and nothing else",
        "trace_versions and trace_modifications tables, so the original is never mutated",
      ]}
    />
  );
}
