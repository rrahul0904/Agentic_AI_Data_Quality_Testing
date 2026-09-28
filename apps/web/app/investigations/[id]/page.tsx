import InvestigationWorkspace from "../../_components/InvestigationWorkspace";

export default async function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationWorkspace incidentId={id} />;
}
