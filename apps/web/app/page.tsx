import OperatorConsole from "./_components/OperatorConsole";

// Keep the legacy landing route's surface contract explicit while the
// canonical demo lives in Automated Data Quality UI Draft. These labels are
// navigation metadata, not a second implementation of the workspaces.
export const OPERATOR_SURFACES = [
  "Overview", "Agent", "Assets", "Lineage", "SQL Intelligence", "dbt", "Airflow",
  "Data Quality", "Reconciliation", "Warehouses", "Connections", "Metadata", "Data Diff",
  "Migration", "Cost / FinOps", "Governance / PII", "PR Reviews", "Skills", "Training",
  "Providers", "MCP", "Jobs", "Traces", "Settings / Doctor",
] as const;

// DomainView remains the shared fallback for surfaces that do not yet have a
// dedicated route in the legacy shell.

export default function HomePage() {
  return <OperatorConsole />;
}
