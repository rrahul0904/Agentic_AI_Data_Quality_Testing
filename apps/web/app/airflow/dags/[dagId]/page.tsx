import { AirflowDag } from "../../../_components/AirflowWorkspace";
export default async function DagPage({ params }: { params: Promise<{ dagId: string }> }) { const { dagId } = await params; return <AirflowDag dagId={decodeURIComponent(dagId)} />; }
