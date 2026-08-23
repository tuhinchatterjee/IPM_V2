import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/data-builder"
      willDo={[
        "Data Domains — the top-level organisation of the bank's data",
        "Dataset Designer — datasets, grain, primary keys, fields and types",
        "Data Dictionary — business names, definitions, allowed values, units and sensitivity",
        "Relationships & Lineage — how datasets join, and where each field came from",
        "Data Quality & Governance — rules, thresholds, owners, status and version",
      ]}
      builtOn={[
        "Governed catalogue of 2 datasets and 65 fields, using the source system's own published definitions",
        "Recorded lineage across the raw, curated and analytics layers",
        "data_domains, dataset_definitions, field_definitions and data_quality_rules tables",
        "GET /api/v1/catalog already serves the catalogue",
      ]}
    />
  );
}
