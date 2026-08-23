import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/monitor"
      willDo={[
        "Period-over-period movement in exposure, stage distribution, ECL, coverage and NPL",
        "Concentration and limit utilisation against appetite",
        "Composed from certified engine functions, each tile carrying its own Trace",
      ]}
      builtOn={[
        "Ten quarterly reporting periods of facility data, Q4 2023 to Q1 2026",
        "Prior-period rating and utilisation fields, so movement is measured rather than estimated",
      ]}
    />
  );
}
