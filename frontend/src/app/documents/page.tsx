import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/documents"
      willDo={[
        "Document Library and Document Workspace",
        "Eventually: paragraph-by-paragraph editing, embedded charts and tables that stay linked to their Trace, comments, version history, workflow approval, and export to Word, PowerPoint and PDF",
        "Deliberately a placeholder for this demo — full document editing is explicitly out of scope",
      ]}
      builtOn={[
        "Existing report writers already produce PDF and Word output",
      ]}
    />
  );
}
