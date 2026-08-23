import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/engine-builder"
      willDo={[
        "Analysis Library — browse every registered capability with its full declared metadata",
        "Analysis Builder — define inputs, datasets, parameters, calculation logic, validation rules and outputs",
        "Testing & Validation — run each capability against its test cases before it may be used",
        "Version & Governance — versioning, ownership, review and certification",
        "Mark validated capabilities IPM Certified with a blue verification tick; user-created ones carry no tick until certified",
      ]}
      builtOn={[
        "Engine registry with declarative contracts, versions and certification status",
        "engine_definitions, engine_versions and engine_tests tables",
        "GET /api/v1/engine/library already serves the Analysis Library",
      ]}
    />
  );
}
