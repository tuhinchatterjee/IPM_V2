import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/stress"
      willDo={[
        "Apply named, versioned, parameterised shocks and re-derive portfolio outcomes",
        "Compare scenarios side by side, with sensitivity and reverse stress",
        "Produce a stressed figure that can be reproduced exactly and defended in committee",
      ]}
      builtOn={[
        "stress_scenarios table — scenarios are objects, never free text",
        "The existing scenario presets, each with a stated rationale",
        "The Oman climate stressed-PD engine, validated to 1e-11 against its source workbook",
      ]}
    />
  );
}
