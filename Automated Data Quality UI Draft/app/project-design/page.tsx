"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ProjectManagementShell from "../ProjectManagementShell";
import styles from "../workflow.module.css";
import local from "./project-design.module.css";
import type {
  AnalysisDecisions,
  AnalysisEvidence,
  AILineageReview,
  AnalysisNode,
  AssetClassification,
  ProjectAnalysisReport,
  ProjectAnalysisWorkspace,
  RelationshipClassification,
} from "../../lib/project-analysis";
import type { OnboardingBootstrap, SelectedSourceTable } from "../../lib/onboarding";
import { scopedApiUrl } from "../../lib/client-workspace";
import { useDrawerFocus } from "../components/ui";

type View = "roles" | "map";
type ProjectDesignProps = { defaultView?: View; navActive?: "design" | "map"; contextOnly?: boolean };
type InspectorTab = "metadata" | "definition" | "evidence" | "children" | "history";
type AssetSource = {
  status: string;
  asset: AnalysisNode;
  classification?: AssetClassification;
  path?: string;
  language: string;
  content?: string;
  content_scope?: "OBJECT_DEFINITION" | "FULL_FILE" | "NOT_AVAILABLE";
  full_content?: string;
  full_content_available?: boolean;
  reason?: string;
  read_only: boolean;
};

const roleOptions = ["source", "landing", "orchestration", "orchestration_task", "ingestion_process", "transformation_input", "transformation", "quality_check", "audit", "target", "quality_metric", "consumer", "data_element", "unknown"];
const relationshipOptions = ["contains", "triggers", "feeds", "reads_from", "writes_to", "transforms_into", "validates", "depends_on", "consumed_by", "represents", "references"];
const layerOrder = ["Sources", "Ingestion", "Transformation", "Targets", "Quality / other"];
const PAGE_SIZE = 24;

async function requestAnalysis(init?: RequestInit): Promise<Record<string, unknown>> {
  const response = await fetch(scopedApiUrl("/api/project-analysis"), { ...init, cache: "no-store" });
  const value = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.error === "string" ? value.error : `Request failed (${response.status})`);
  return value;
}

function technology(node: AnalysisNode): string {
  const value = String(node.properties.connection_kind || "repository");
  return value === "dbt" ? "dbt" : value === "files" ? "Files" : value.charAt(0).toUpperCase() + value.slice(1);
}

function isTopLevel(node: AnalysisNode): boolean {
  return node.properties.is_top_level !== false && !node.properties.parent_discovery_asset_id;
}

function layer(node: AnalysisNode, role: string): string {
  const proposed = String(node.properties.proposed_layer || "");
  if (node.kind === "source_table") return "Sources";
  if (node.kind === "warehouse_table" || node.kind === "mart") return "Targets";
  if (node.kind === "dbt_test" || ["quality_check", "audit", "quality_metric", "data_element"].includes(role)) return "Quality / other";
  if (["airflow_dag", "airflow_task"].includes(node.kind)) return "Ingestion";
  if (["dbt_model", "dbt_snapshot"].includes(node.kind)) return "Transformation";
  if (role === "source") return "Sources";
  if (["landing", "orchestration", "orchestration_task", "ingestion_process"].includes(role)) return "Ingestion";
  if (["transformation_input", "transformation"].includes(role)) return "Transformation";
  if (["target", "consumer"].includes(role)) return "Targets";
  if (["Sources", "Ingestion", "Transformation", "Targets"].includes(proposed)) return proposed;
  return "Quality / other";
}

function decisionStatus(classification: { status: string }, decision?: { status: string }): string {
  return decision?.status || classification.status || "DETERMINISTIC";
}

function tone(status: string): string {
  if (["USER_VERIFIED", "PASS", "DETERMINISTIC", "COMPLETED", "NOT_REQUIRED", "OBSERVED", "AI_REVIEWED"].includes(status)) return local.good;
  if (["REJECTED", "ERROR", "FAIL", "UNAVAILABLE", "NOT_CONFIGURED"].includes(status)) return local.bad;
  return local.review;
}

function aiStatusLabel(status?: string, busy = false, availability?: string): string {
  if (busy) return "RUNNING";
  const normalized = status?.toUpperCase();
  if (normalized === "DISABLED" || normalized === "UNAVAILABLE" || normalized === "NOT_CONFIGURED") {
    return ["READY", "CONFIGURED"].includes(String(availability || "").toUpperCase()) ? "READY TO REVIEW" : "UNAVAILABLE";
  }
  if (!normalized) return ["READY", "CONFIGURED"].includes(String(availability || "").toUpperCase()) ? "NOT INVOKED" : "UNAVAILABLE";
  return normalized.replaceAll("_", " ");
}

function evidenceFor(report: ProjectAnalysisReport, ids: string[]): AnalysisEvidence[] {
  const selected = new Set(ids);
  return report.evidence.filter((item) => selected.has(item.evidence_id));
}

function uniqueRelationships(edges: RelationshipClassification[]): RelationshipClassification[] {
  const byId = new Map<string, RelationshipClassification>();
  for (const edge of edges) {
    const current = byId.get(edge.edge_id);
    if (!current || edge.confidence > current.confidence) byId.set(edge.edge_id, edge);
  }
  return [...byId.values()];
}

function assetIdentity(node: AnalysisNode): string {
  return String(node.properties.discovery_asset_id || node.node_id);
}

function nodeTableId(node: AnalysisNode): string {
  return String(node.properties.source_table_id || node.properties.sourceTableId || "");
}

function nodeBelongsToTable(node: AnalysisNode, tableId: string, tables: SelectedSourceTable[]): boolean {
  if (!tableId) return true;
  const direct = nodeTableId(node);
  if (direct) return direct === tableId;
  const table = tables.find((item) => item.id === tableId);
  if (!table) return false;
  const needle = table.table.toLowerCase();
  return [node.name, node.properties.detail, node.properties.evidence_location, node.properties.discovery_asset_id]
    .map((value) => String(value || "").toLowerCase())
    .some((value) => value.includes(needle));
}

function FlowGraph({ nodes, edges, nodeMap, classifications, decisions, onNodeClick, onEdgeClick, hideQualityChecks }: {
  nodes: AnalysisNode[];
  edges: RelationshipClassification[];
  nodeMap: Map<string, AnalysisNode>;
  classifications: Map<string, AssetClassification>;
  decisions: AnalysisDecisions;
  onNodeClick: (id: string) => void;
  onEdgeClick: (edge: RelationshipClassification) => void;
  hideQualityChecks: boolean;
}) {
  const laneWidth = 208;
  const cardWidth = 180;
  const nodeGap = 104;
  const graphTop = 52;
  const qualityTestNodes = nodes.filter((node) => node.kind === "dbt_test");
  const visibleNodes = hideQualityChecks ? nodes.filter((node) => node.kind !== "dbt_test") : nodes;
  const baseVisibleEdges = hideQualityChecks ? edges.filter((edge) => nodeMap.get(edge.source_asset_id)?.kind !== "dbt_test" && nodeMap.get(edge.target_asset_id)?.kind !== "dbt_test") : edges;
  const qualityCheckGroup: AnalysisNode = { node_id: "quality-checks-group", kind: "quality_group", name: "Quality checks", properties: { is_top_level: true, proposed_layer: "Quality / other", connection_kind: "dbt", runtime_status: "NOT_RUN", detail: `${qualityTestNodes.length} dbt tests grouped for readability` } };
  const renderedNodes = hideQualityChecks && qualityTestNodes.length ? [...visibleNodes, qualityCheckGroup] : visibleNodes;
  const qualityCheckSources = [...new Set(edges.filter((edge) => nodeMap.get(edge.target_asset_id)?.kind === "dbt_test").map((edge) => edge.source_asset_id))];
  const groupedEdges: RelationshipClassification[] = qualityCheckSources.map((sourceId) => ({ edge_id: `quality-checks:${sourceId}`, source_asset_id: sourceId, target_asset_id: qualityCheckGroup.node_id, relationship: "tests", confidence: 1, source: "DETERMINISTIC", evidence_ids: [], rationale: `${qualityTestNodes.length} dbt quality checks grouped for readability.`, requires_review: false, status: "DETERMINISTIC", pipeline_ids: [], lineage_state: "PLANNED", runtime_status: "NOT_RUN" }));
  const visibleEdges = hideQualityChecks ? [...baseVisibleEdges, ...groupedEdges] : baseVisibleEdges;
  const lanes = layerOrder.map((layerName) => ({
    name: layerName,
    nodes: renderedNodes.filter((node) => layer(node, classifications.get(node.node_id)?.roles[0] || "unknown") === layerName),
  }));
  const positionKey = `ade-map-positions:${window.location.search}`;
  const [savedPositions, setSavedPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panStart, setPanStart] = useState<{ x: number; y: number; origin: { x: number; y: number } } | null>(null);
  const [dragging, setDragging] = useState<{ id: string; x: number; y: number; origin: { x: number; y: number } } | null>(null);
  const dragMoved = useRef(false);
  useEffect(() => {
    try { const stored = JSON.parse(window.localStorage.getItem(positionKey) || "{}"); if (stored && typeof stored === "object") setSavedPositions(stored); } catch { /* UI-only positions are optional. */ }
  }, [positionKey]);
  useEffect(() => {
    if (!dragging) return;
    const move = (event: PointerEvent) => {
      const dx = event.clientX - dragging.x;
      const dy = event.clientY - dragging.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved.current = true;
      setSavedPositions((current) => {
        const next = { ...current, [dragging.id]: { x: Math.max(8, dragging.origin.x + dx), y: Math.max(graphTop, dragging.origin.y + dy) } };
        window.localStorage.setItem(positionKey, JSON.stringify(next));
        return next;
      });
    };
    const end = () => { setDragging(null); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); };
  }, [dragging]);
  useEffect(() => {
    if (!panStart) return;
    const move = (event: PointerEvent) => setPan({ x: panStart.origin.x + event.clientX - panStart.x, y: panStart.origin.y + event.clientY - panStart.y });
    const end = () => setPanStart(null);
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); };
  }, [panStart]);
  const fitContent = () => { setZoom(.85); setPan({ x: 0, y: 0 }); };
  const resetLayout = () => { setSavedPositions({}); setZoom(1); setPan({ x: 0, y: 0 }); window.localStorage.removeItem(positionKey); };
  const positions = new Map<string, { x: number; y: number }>();
  lanes.forEach((lane, laneIndex) => lane.nodes.forEach((node, nodeIndex) => {
    positions.set(node.node_id, savedPositions[node.node_id] || { x: laneIndex * laneWidth + 12, y: graphTop + nodeIndex * nodeGap });
  }));
  const maxX = Math.max(lanes.length * laneWidth, ...[...positions.values()].map((item) => item.x + cardWidth + 16));
  const graphWidth = maxX;
  const graphHeight = Math.max(260, Math.max(...lanes.map((lane) => lane.nodes.length), 1) * nodeGap + 84);

  return <div className={local.graphViewport} aria-label="Interactive pipeline graph">
    <header className={local.graphHeader}><div><strong>Lineage graph</strong><span>Drag objects to arrange. Drag the canvas to pan. Click a node or connector to inspect evidence.</span></div><div className={local.graphTools}><button aria-label="Zoom out" onClick={() => setZoom((current) => Math.max(.7, Number((current - .1).toFixed(1))))}>−</button><span className={local.zoomLabel}>{Math.round(zoom * 100)}%</span><button aria-label="Zoom in" onClick={() => setZoom((current) => Math.min(1.4, Number((current + .1).toFixed(1))))}>+</button><button onClick={fitContent}>Fit content</button><button onClick={resetLayout}>Auto-layout</button><span className={local.graphLegend}><i className={local.legendObserved} />Observed <i className={local.legendPlanned} />Planned <i className={local.legendAi} />AI reviewed</span></div></header>
    <div className={local.graphCanvas} onPointerDown={(event) => { if (event.target === event.currentTarget) setPanStart({ x: event.clientX, y: event.clientY, origin: pan }); }} style={{ width: graphWidth, height: graphHeight, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "top left", marginBottom: `${graphHeight * (zoom - 1)}px` }}>
      <svg className={local.graphEdges} width={graphWidth} height={graphHeight} aria-hidden="true">
        <defs><marker id="map-flow-arrow-observed" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#16835a" /></marker><marker id="map-flow-arrow-planned" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#a5b5ad" /></marker></defs>
        {visibleEdges.map((edge) => {
          const source = positions.get(edge.source_asset_id);
          const target = positions.get(edge.target_asset_id);
          if (!source || !target) return null;
          const startX = source.x + cardWidth;
          const startY = source.y + 40;
          const endX = target.x;
          const endY = target.y + 40;
          const bend = Math.max(34, Math.abs(endX - startX) * .45);
          const status = decisionStatus(edge, decisions.relationships[edge.edge_id]);
          const lineageState = edge.lineage_state || "PLANNED";
          return <path key={edge.edge_id} className={`${local.graphEdge} ${lineageState === "OBSERVED" ? local.graphEdgeObserved : local.graphEdgePlanned} ${status === "USER_VERIFIED" ? local.graphEdgeVerified : ""}`} d={`M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`} markerEnd={`url(#map-flow-arrow-${lineageState === "OBSERVED" ? "observed" : "planned"})`} onClick={() => { if (!edge.edge_id.startsWith("quality-checks:")) onEdgeClick(edge); }} />;
        })}
      </svg>
      {lanes.map((lane, laneIndex) => <div className={`${local.graphLane} ${lane.name === "Targets" ? local.graphLaneTarget : ""}`} style={{ left: laneIndex * laneWidth, width: laneWidth }} key={lane.name}>
        <span className={local.graphLaneTitle}>{lane.name}<b>{lane.nodes.length}</b></span>
        {lane.nodes.map((node) => {
          const position = positions.get(node.node_id);
          if (!position) return null;
          const classification = classifications.get(node.node_id);
          const status = classification ? decisionStatus(classification, decisions.assets[node.node_id]) : "DISCOVERED";
          const lineageState = String(node.properties.lineage_state || classification?.lineage_state || "PLANNED");
          const runtimeStatus = String(node.properties.runtime_status || classification?.runtime_status || "NOT_RUN");
          return <button className={local.graphNodeCard} style={{ top: position.y, left: position.x - laneIndex * laneWidth, width: cardWidth }} key={node.node_id} onPointerDown={(event) => { dragMoved.current = false; setDragging({ id: node.node_id, x: event.clientX, y: event.clientY, origin: position }); }} onClick={() => { if (!dragMoved.current) onNodeClick(node.node_id); }} title="Drag to arrange or click to open object evidence">
            <span className={`${local.graphNodeStatus} ${tone(lineageState)}`}>{lineageState.replaceAll("_", " ")}</span>
            <strong>{node.name}</strong>
            <small>{technology(node)} · {node.kind.replaceAll("_", " ")}</small>
            <em className={runtimeStatus === "COMPLETED" ? local.runtimeGood : runtimeStatus === "FAILED" ? local.runtimeBad : local.runtimePending}>Runtime · {runtimeStatus.replaceAll("_", " ")}</em>
          </button>;
        })}
      </div>)}
    </div><div className={local.minimap} aria-label="Graph minimap"><span>MINIMAP</span>{lanes.map((lane, index) => <div className={local.minimapLane} key={lane.name} style={{ left: `${index * 20}%`, width: "20%" }}><b>{lane.nodes.length}</b></div>)}</div>{hideQualityChecks && qualityTestNodes.length > 0 && <div className={local.graphNote}>{qualityTestNodes.length} dbt test{qualityTestNodes.length === 1 ? "" : "s"} grouped into <strong>Quality checks</strong>. Show dbt test links to expand them.</div>}
  </div>;
}

function ProjectDesignView({ defaultView = "roles", navActive = "design", contextOnly = true }: ProjectDesignProps) {
  const [view, setView] = useState<View>(defaultView);
  const [report, setReport] = useState<ProjectAnalysisReport | null>(null);
  const [decisions, setDecisions] = useState<AnalysisDecisions>({ assets: {}, relationships: {} });
  const [capabilities, setCapabilities] = useState<Record<string, unknown>>({});
  const [query, setQuery] = useState("");
  const [layerFilter, setLayerFilter] = useState("all");
  const [technologyFilter, setTechnologyFilter] = useState("all");
  const [kindFilter, setKindFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pipelineId, setPipelineId] = useState("");
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [sourceTables, setSourceTables] = useState<SelectedSourceTable[]>([]);
  const [tableFilter, setTableFilter] = useState("all");
  const [draftRoles, setDraftRoles] = useState<Record<string, string>>({});
  const [draftRelationships, setDraftRelationships] = useState<Record<string, string>>({});
  const [assetSource, setAssetSource] = useState<AssetSource | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("metadata");
  const [showFullSource, setShowFullSource] = useState(false);
  const [edgeInspector, setEdgeInspector] = useState<RelationshipClassification | null>(null);
  const [addingEdge, setAddingEdge] = useState(false);
  const [proposedEdges, setProposedEdges] = useState<RelationshipClassification[]>([]);
  const [newEdge, setNewEdge] = useState({ source: "", target: "", relationship: "depends_on" });
  const [sourceFilter, setSourceFilter] = useState("all");
  const [targetFilter, setTargetFilter] = useState("all");
  const [mapLayerFilter, setMapLayerFilter] = useState("all");
  const [mapScope, setMapScope] = useState<"selected" | "catalog">("selected");
  const [hideQualityChecks, setHideQualityChecks] = useState(true);
  const [showEdgePanel, setShowEdgePanel] = useState(true);
  const [busy, setBusy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiReview, setAiReview] = useState<AILineageReview | null>(null);
  const [notice, setNotice] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  useDrawerFocus(Boolean(assetSource || edgeInspector || addingEdge), () => { setAssetSource(null); setEdgeInspector(null); setAddingEdge(false); });

  useEffect(() => {
    const requestedView = new URLSearchParams(window.location.search).get("view");
    setView(defaultView === "map" || requestedView === "map" || window.location.pathname === "/map-flows" ? "map" : "roles");
    void fetch(scopedApiUrl("/api/onboarding"), { cache: "no-store" }).then((response) => response.ok ? response.json() as Promise<OnboardingBootstrap> : Promise.reject(new Error("onboarding unavailable"))).then((value) => {
      setSelectedAssetIds(value.selectedAssets ?? []);
      const tables = value.selectedSourceTables?.length ? value.selectedSourceTables : value.selectedSourceTable ? [value.selectedSourceTable] : [];
      setSourceTables(tables);
      if (tables[0]?.id) setTableFilter(tables[0].id);
    }).catch(() => { setSelectedAssetIds([]); setSourceTables([]); });
    requestAnalysis().then((value) => {
      const workspace = value as unknown as ProjectAnalysisWorkspace;
      setReport(workspace.report);
      setDecisions(workspace.decisions);
      setCapabilities(workspace.capabilities);
      const storedReview = workspace.ai_review;
      const currentRunId = workspace.report?.run_id;
      setAiReview(storedReview && (!currentRunId || storedReview.analysis_run_id === currentRunId) ? storedReview : null);
      setPipelineId(workspace.report?.pipelines?.[0]?.pipeline_id || "");
    }).catch((error: Error) => setNotice({ tone: "bad", text: error.message }));
  }, [defaultView]);

  useEffect(() => {
    if (view !== "map" || report?.runtime?.status !== "RUNNING") return;
    const timer = window.setInterval(() => { void refreshRuntime(); }, 15000);
    return () => window.clearInterval(timer);
  }, [view, report?.runtime?.status]);

  const nodeMap = useMemo(() => new Map(report?.graph.nodes.map((node) => [node.node_id, node]) ?? []), [report]);
  const classifications = useMemo(() => new Map(report?.asset_classifications.map((item) => [item.asset_id, item]) ?? []), [report]);
  const childMap = useMemo(() => {
    const result = new Map<string, AnalysisNode[]>();
    for (const node of report?.graph.nodes ?? []) {
      const parent = String(node.properties.parent_discovery_asset_id || "");
      if (parent) result.set(parent, [...(result.get(parent) || []), node]);
    }
    return result;
  }, [report]);

  const topLevelRows = useMemo(() => (report?.asset_classifications ?? []).map((classification) => ({ classification, node: nodeMap.get(classification.asset_id) })).filter((row): row is { classification: AssetClassification; node: AnalysisNode } => Boolean(row.node && isTopLevel(row.node))), [report, nodeMap]);
  const scopedTopLevelRows = useMemo(() => tableFilter === "all" ? topLevelRows : topLevelRows.filter(({ node }) => nodeBelongsToTable(node, tableFilter, sourceTables)), [topLevelRows, tableFilter, sourceTables]);

  const roleRows = useMemo(() => scopedTopLevelRows.filter(({ classification, node }) => {
    const status = decisionStatus(classification, decisions.assets[classification.asset_id]);
    const assignedRole = draftRoles[classification.asset_id] || decisions.assets[classification.asset_id]?.role || classification.roles[0];
    const haystack = `${node.name} ${node.kind} ${technology(node)} ${classification.roles.join(" ")}`.toLowerCase();
    return haystack.includes(query.toLowerCase())
      && (layerFilter === "all" || layer(node, assignedRole) === layerFilter)
      && (technologyFilter === "all" || technology(node) === technologyFilter)
      && (kindFilter === "all" || node.kind === kindFilter)
      && (statusFilter === "all" || status === statusFilter);
  }), [scopedTopLevelRows, decisions, draftRoles, query, layerFilter, technologyFilter, kindFilter, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(roleRows.length / PAGE_SIZE));
  const visibleRoleRows = useMemo(() => roleRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [roleRows, page]);

  useEffect(() => { setPage(1); }, [query, layerFilter, technologyFilter, kindFilter, statusFilter]);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);

  const groupedRoles = useMemo(() => {
    const result = new Map<string, Map<string, typeof visibleRoleRows>>();
    for (const row of visibleRoleRows) {
      const assigned = draftRoles[row.classification.asset_id] || decisions.assets[row.classification.asset_id]?.role || row.classification.roles[0];
      const rowLayer = layer(row.node!, assigned);
      const byTechnology = result.get(rowLayer) || new Map<string, typeof visibleRoleRows>();
      const key = technology(row.node!);
      byTechnology.set(key, [...(byTechnology.get(key) || []), row]);
      result.set(rowLayer, byTechnology);
    }
    return result;
  }, [visibleRoleRows, decisions, draftRoles]);

  const selectedPipeline = report?.pipelines?.find((item) => item.pipeline_id === pipelineId) || report?.pipelines?.[0];

  useEffect(() => {
    if (!report || !selectedPipeline || tableFilter === "all") return;
    const activeTable = sourceTables.find((table) => table.id === tableFilter);
    if (!activeTable) return;
    const pipelineMatchesTable = (pipeline: NonNullable<ProjectAnalysisReport["pipelines"]>[number]) => pipeline.node_ids.some((id) => {
      const node = nodeMap.get(id);
      return Boolean(node && nodeBelongsToTable(node, activeTable.id, sourceTables));
    });
    if (pipelineMatchesTable(selectedPipeline)) return;
    const matchingPipeline = report.pipelines?.find(pipelineMatchesTable);
    if (matchingPipeline && matchingPipeline.pipeline_id !== selectedPipeline.pipeline_id) setPipelineId(matchingPipeline.pipeline_id);
  }, [report, selectedPipeline, tableFilter, sourceTables, nodeMap]);

  const pipelineNodes = (selectedPipeline?.node_ids || []).map((id) => nodeMap.get(id)).filter((item): item is AnalysisNode => Boolean(item && isTopLevel(item)));
  const pipelineEdges = uniqueRelationships([...(report?.relationship_classifications ?? []), ...proposedEdges]).filter((item) => selectedPipeline?.edge_ids.includes(item.edge_id) || item.pipeline_ids.includes(selectedPipeline?.pipeline_id || ""));
  const tableScopedPipelineNodes = tableFilter === "all" ? pipelineNodes : pipelineNodes.filter((node) => nodeBelongsToTable(node, tableFilter, sourceTables));
  const tableScopedNodeIds = new Set(tableScopedPipelineNodes.map((node) => node.node_id));
  const tableScopedPipelineEdges = tableFilter === "all" ? pipelineEdges : pipelineEdges.filter((edge) => tableScopedNodeIds.has(edge.source_asset_id) && tableScopedNodeIds.has(edge.target_asset_id));
  const selectedPipelineNodes = mapScope === "selected" && selectedAssetIds.length > 0
    ? tableScopedPipelineNodes.filter((node) => selectedAssetIds.includes(assetIdentity(node)))
    : tableScopedPipelineNodes;
  const scopedNodeIds = new Set(selectedPipelineNodes.map((node) => node.node_id));
  const mapSources = [...new Set(tableScopedPipelineEdges.map((edge) => edge.source_asset_id))].sort((left, right) => (nodeMap.get(left)?.name || left).localeCompare(nodeMap.get(right)?.name || right));
  const mapTargets = [...new Set(tableScopedPipelineEdges.map((edge) => edge.target_asset_id))].sort((left, right) => (nodeMap.get(left)?.name || left).localeCompare(nodeMap.get(right)?.name || right));
  const visiblePipelineEdges = tableScopedPipelineEdges.filter((edge) => {
    const sourceNode = nodeMap.get(edge.source_asset_id);
    if (!sourceNode) return false;
    const sourceRole = classifications.get(edge.source_asset_id)?.roles[0] || "unknown";
    return scopedNodeIds.has(edge.source_asset_id) && scopedNodeIds.has(edge.target_asset_id)
      && (sourceFilter === "all" || edge.source_asset_id === sourceFilter) && (targetFilter === "all" || edge.target_asset_id === targetFilter) && (mapLayerFilter === "all" || layer(sourceNode, sourceRole) === mapLayerFilter);
  });
  const displayedPipelineEdges = hideQualityChecks
    ? visiblePipelineEdges.filter((edge) => nodeMap.get(edge.source_asset_id)?.kind !== "dbt_test" && nodeMap.get(edge.target_asset_id)?.kind !== "dbt_test")
    : visiblePipelineEdges;
  const groupedQualityLinkCount = hideQualityChecks
    ? new Set(visiblePipelineEdges.filter((edge) => nodeMap.get(edge.target_asset_id)?.kind === "dbt_test").map((edge) => edge.source_asset_id)).size
    : 0;
  const graphLinkCount = displayedPipelineEdges.length + groupedQualityLinkCount;
  const mappedAssetIds = new Set(pipelineNodes.map(assetIdentity));
  const mappedAssetCount = selectedAssetIds.filter((id) => mappedAssetIds.has(id)).length;
  const unmappedAssetCount = Math.max(0, selectedAssetIds.length - mappedAssetCount);
  const connectedTopLevel = new Set(report?.pipelines?.flatMap((item) => item.node_ids) || []);
  const unresolvedNodes = (report?.graph.nodes ?? []).filter((node) => isTopLevel(node) && !connectedTopLevel.has(node.node_id));
  const technologies = [...new Set(scopedTopLevelRows.map(({ node }) => technology(node)))].sort();
  const kinds = [...new Set(scopedTopLevelRows.map(({ node }) => node.kind))].sort();
  const statuses = [...new Set(scopedTopLevelRows.map(({ classification }) => decisionStatus(classification, decisions.assets[classification.asset_id])))].sort();

  const runAnalysis = async () => {
    setBusy(true); setNotice(null);
    try {
      const value = await requestAnalysis({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "analyze" }) });
      const next = value.report as ProjectAnalysisReport;
      setReport(next); setPipelineId(next.pipelines?.[0]?.pipeline_id || "");
      setNotice({ tone: "good", text: `Analysis persisted from ${next.summary.top_level_assets} accepted discovered assets.` });
    } catch (error) { setNotice({ tone: "bad", text: error instanceof Error ? error.message : "Analysis failed" }); }
    finally { setBusy(false); }
  };

  const refreshRuntime = async () => {
    setRuntimeBusy(true); setNotice(null);
    try {
      const value = await requestAnalysis({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "refresh" }) });
      const next = value.report as ProjectAnalysisReport;
      setReport(next); setPipelineId(next.pipelines?.[0]?.pipeline_id || "");
      setNotice({ tone: "good", text: `Runtime evidence refreshed: ${next.runtime?.status || "NOT_RUN"}. No pipeline was started.` });
    } catch (error) { setNotice({ tone: "bad", text: error instanceof Error ? error.message : "Runtime refresh failed" }); }
    finally { setRuntimeBusy(false); }
  };

  const verifyWithAI = async (scope: "proposed" | "all" | "conflicts") => {
    setAiBusy(true); setNotice(null);
    try {
      const value = await requestAnalysis({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "ai-verify", scope }) });
      setAiReview((value as { review?: AILineageReview }).review ?? null);
      const review = (value as { review?: AILineageReview }).review;
      setNotice({ tone: review?.status === "COMPLETED" || review?.status === "NEEDS_HUMAN_APPROVAL" ? "good" : "bad", text: review?.status === "COMPLETED" || review?.status === "NEEDS_HUMAN_APPROVAL" ? "AI review completed; human approval is still required." : (review?.reason || `AI review status: ${review?.status || "UNKNOWN"}`) });
    } catch (error) { setNotice({ tone: "bad", text: error instanceof Error ? error.message : "AI verification failed" }); }
    finally { setAiBusy(false); }
  };

  const submitReview = async (key: string, review: Record<string, unknown>): Promise<boolean> => {
    setReviewBusy(key); setNotice(null);
    try {
      const value = await requestAnalysis({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "review", review }) });
      setDecisions(value.reviews as AnalysisDecisions);
      setNotice({ tone: "good", text: review.status === "RESET" ? "Review reset to automated analysis." : "Review decision persisted in the analysis database." });
      return true;
    } catch (error) { setNotice({ tone: "bad", text: error instanceof Error ? error.message : "Review failed" }); return false; }
    finally { setReviewBusy(null); }
  };

  const openAsset = async (assetId: string) => {
    setReviewBusy(`source:${assetId}`); setNotice(null);
    try {
      const response = await fetch(scopedApiUrl(`/api/project-analysis/source/${encodeURIComponent(assetId)}`), { cache: "no-store" });
      const value = await response.json() as AssetSource & { error?: string };
      if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
      setInspectorTab("metadata");
      setShowFullSource(false);
      setAssetSource(value);
    } catch (error) { setNotice({ tone: "bad", text: error instanceof Error ? error.message : "Unable to load evidence" }); }
    finally { setReviewBusy(null); }
  };

  const addRelationship = () => {
    if (!report || !newEdge.source || !newEdge.target || newEdge.source === newEdge.target) {
      setNotice({ tone: "bad", text: "Choose different upstream and downstream assets." }); return;
    }
    const sourceEvidence = classifications.get(newEdge.source)?.evidence_ids || [];
    const targetEvidence = classifications.get(newEdge.target)?.evidence_ids || [];
    setProposedEdges((current) => [...current, { edge_id: `draft-edge-${Date.now()}`, source_asset_id: newEdge.source, target_asset_id: newEdge.target, relationship: newEdge.relationship, confidence: 0, source: "USER", evidence_ids: [...new Set([...sourceEvidence, ...targetEvidence])], rationale: "User proposed relationship pending explicit evidence review.", requires_review: true, status: "DETERMINISTIC_PROPOSED", pipeline_ids: selectedPipeline ? [selectedPipeline.pipeline_id] : [] }]);
    setAddingEdge(false);
    setNotice({ tone: "good", text: "Mapping proposed locally. Inspect its evidence before verifying it." });
  };

  const verifyRelationship = async (edge: RelationshipClassification, relationship: string) => {
    const saved = await submitReview(edge.edge_id, { subject_type: "relationship", subject_id: edge.edge_id, status: "USER_VERIFIED", value: relationship, source_asset_id: edge.source_asset_id, target_asset_id: edge.target_asset_id, evidence_ids: edge.evidence_ids, note: "User-created relationship from inspected analysis evidence." });
    if (saved && edge.edge_id.startsWith("draft-edge-")) setProposedEdges((current) => current.filter((item) => item.edge_id !== edge.edge_id));
  };

  const openAiStatus = capabilities.openai && typeof capabilities.openai === "object" ? String((capabilities.openai as Record<string, unknown>).status || "UNAVAILABLE") : "UNAVAILABLE";
  const analysisActions = <div className={local.analysisActions}><span className={`${local.status} ${tone(report?.status || "NOT_RUN")}`}>{report?.status || "NOT RUN"}</span><button className={styles.secondary} disabled={busy} onClick={() => void runAnalysis()}>{busy ? "Organizing catalog…" : "Run automated analysis"}</button></div>;

  return <ProjectManagementShell phase={view === "map" ? "map" : "objects"} navActive={view === "map" ? "map" : navActive} contextOnly={contextOnly} title={view === "map" ? "Lineage" : "Catalog"} description={view === "map" ? "Explore evidence-backed relationships one pipeline at a time." : ""} headerActions={analysisActions}>
    {notice && <div className={notice.tone === "good" ? styles.successStrip : styles.dangerStrip}>{notice.text}</div>}

    {!report ? <section className={styles.panel}><header className={styles.panelHead}><div><h2>No catalog analysis yet</h2><p>Run analysis to organize the saved discovery catalog.</p></div><button className={styles.primary} disabled={busy} onClick={() => void runAnalysis()}>{busy ? "Organizing catalog…" : "Run analysis"}</button></header></section> : <>
      <section className={local.metrics}>
        <article><span>Discovered objects</span><strong>{report.summary.top_level_assets}</strong><small>{report.summary.child_assets} columns and job tasks</small></article>
        <article><span>Detected pipeline flows</span><strong>{report.summary.pipelines}</strong><small>{report.summary.relationships} technical links reviewed by rules</small></article>
        <article><span>Not connected yet</span><strong>{unresolvedNodes.length}</strong><small>Visible, but not assigned to a flow without evidence</small></article>
        <article><span>AI verification</span><strong>{aiStatusLabel(aiReview?.status, aiBusy, openAiStatus)}</strong><small>{aiReview ? `${aiReview.scope} review · human approval remains required` : openAiStatus === "READY" ? "Ready; invoke review when you want an AI challenge." : "AI provider is unavailable."}</small></article>
      </section>

      <details className={local.analysisDetails}><summary>Analysis run details <span>How these counts were produced</span></summary><section className={local.analyzers} aria-label="Analyzer results">
        {(report.analyzers ?? []).map((analyzer) => <article key={analyzer.analyzer_id}><span className={`${local.status} ${tone(analyzer.status)}`}>{analyzer.status}</span><div><strong>{analyzer.name}</strong><small>{analyzer.detail}</small></div><b>{analyzer.facts}</b></article>)}
      </section></details>

      {view === "roles" ? <>
        {sourceTables.length > 0 && <section className={local.tableScopeBar}><strong>Table scope</strong><select aria-label="Filter source table" value={tableFilter} onChange={(event) => setTableFilter(event.target.value)}><option value="all">All source tables</option>{sourceTables.map((table) => <option key={table.id} value={table.id}>{table.database}.{table.schema}.{table.table}</option>)}</select><span>{tableFilter === "all" ? "Combined project catalog" : "Showing one isolated table workflow"}</span></section>}
        <section className={local.toolbar}><div><strong>Discovered data and pipeline objects</strong><span>{roleRows.length} of {topLevelRows.length} objects match</span></div><input aria-label="Search objects" placeholder="Search object, type or role" value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Filter layer" value={layerFilter} onChange={(event) => setLayerFilter(event.target.value)}><option value="all">All pipeline layers</option>{layerOrder.map((item) => <option key={item}>{item}</option>)}</select><select aria-label="Filter technology" value={technologyFilter} onChange={(event) => setTechnologyFilter(event.target.value)}><option value="all">All technologies</option>{technologies.map((item) => <option key={item}>{item}</option>)}</select><select aria-label="Filter object type" value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}><option value="all">All object types</option>{kinds.map((item) => <option key={item}>{item.replaceAll("_", " ")}</option>)}</select><select aria-label="Filter review status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All review statuses</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select>{(query || layerFilter !== "all" || technologyFilter !== "all" || kindFilter !== "all" || statusFilter !== "all") && <button onClick={() => { setQuery(""); setLayerFilter("all"); setTechnologyFilter("all"); setKindFilter("all"); setStatusFilter("all"); }}>Clear filters</button>}</section>
        <div className={local.roleWorkspace}>{layerOrder.map((layerName) => {
          const groups = groupedRoles.get(layerName); if (!groups?.size) return null;
          return <section className={local.layer} key={layerName}><header><div><span>PIPELINE LAYER</span><h2>{layerName}</h2></div><b>{[...groups.values()].reduce((sum, rows) => sum + rows.length, 0)}</b></header>{[...groups.entries()].map(([tech, rows]) => <div className={local.technology} key={tech}><div className={local.technologyHead}><strong>{tech}</strong><span>{rows.length} objects</span></div><div className={local.roleGrid}>{rows.map(({ node, classification }) => {
            if (!node) return null;
            const decision = decisions.assets[classification.asset_id];
            const selectedRole = draftRoles[classification.asset_id] || decision?.role || classification.roles[0];
            const status = decisionStatus(classification, decision);
            const children = childMap.get(String(node.properties.discovery_asset_id)) || [];
            const evidence = evidenceFor(report, classification.evidence_ids)[0];
            return <article className={local.assetCard} key={classification.asset_id}><header><button onClick={() => void openAsset(classification.asset_id)} disabled={reviewBusy === `source:${classification.asset_id}`}><strong>{node.name}</strong><small>{node.kind.replaceAll("_", " ")} · {String(node.properties.asset_type || "object")}</small></button><span className={`${local.status} ${tone(status)}`}>{status === "DETERMINISTIC" ? "RULE CLASSIFIED" : status}</span></header><div className={local.assetMeta}><span>{classification.source === "DETERMINISTIC" ? "Rule-derived" : classification.source}</span><span>{Math.round(classification.confidence * 100)}% confidence</span><span>{children.length} columns/tasks</span></div><label>Pipeline role<select value={selectedRole} onChange={(event) => setDraftRoles((current) => ({ ...current, [classification.asset_id]: event.target.value }))}>{roleOptions.map((role) => <option key={role}>{role.replaceAll("_", " ")}</option>)}</select></label><p>{classification.rationale}</p><div className={local.evidenceLine}><span>{evidence?.maturity || "NO EVIDENCE"}</span><small>{evidence?.source || "Evidence unavailable"}</small></div><div className={local.actions}><button disabled={reviewBusy === classification.asset_id} onClick={() => void submitReview(classification.asset_id, { subject_type: "asset", subject_id: classification.asset_id, status: "USER_VERIFIED", value: selectedRole })}>Confirm role</button><button disabled={reviewBusy === classification.asset_id} onClick={() => void submitReview(classification.asset_id, { subject_type: "asset", subject_id: classification.asset_id, status: "REJECTED", value: selectedRole })}>Reject</button>{decision && <button disabled={reviewBusy === classification.asset_id} onClick={() => void submitReview(classification.asset_id, { subject_type: "asset", subject_id: classification.asset_id, status: "RESET" })}>Reset</button>}</div>{children.length > 0 && <details><summary>{children.length} discovered {children[0].kind === "column" ? "columns" : "tasks"}</summary><div className={local.children}>{children.map((child) => <button key={child.node_id} onClick={() => void openAsset(child.node_id)}><strong>{child.name.split(".").pop()}</strong><small>{String(child.properties.detail || child.kind)}</small></button>)}</div></details>}</article>;
          })}</div></div>)}</section>;
        })}</div>
        {roleRows.length === 0 && <section className={local.emptyResult}><strong>No objects match these filters.</strong><span>Clear one or more filters to return to the discovered object catalog.</span></section>}
        {roleRows.length > 0 && <nav className={local.pagination} aria-label="Asset catalog pages"><span>Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, roleRows.length)} of {roleRows.length}</span><div><button disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</button><strong>Page {page} of {pageCount}</strong><button disabled={page === pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>Next</button></div></nav>}
      </> : <>
        {sourceTables.length > 0 && <section className={local.tableScopeBar}><strong>Table scope</strong><select aria-label="Filter lineage by source table" value={tableFilter} onChange={(event) => setTableFilter(event.target.value)}><option value="all">All source tables</option>{sourceTables.map((table) => <option key={table.id} value={table.id}>{table.database}.{table.schema}.{table.table}</option>)}</select><span>{tableFilter === "all" ? "Combined project graph" : "Showing one isolated table lineage"}</span></section>}
        <section className={local.toolbar}><div><strong>Detected pipeline flows</strong><span>Choose one source-rooted flow. The graph uses the accepted analysis relationships.</span></div><select aria-label="Map scope" value={mapScope} onChange={(event) => setMapScope(event.target.value as "selected" | "catalog")}><option value="selected">Selected assets only</option><option value="catalog">Full accepted catalog</option></select><select aria-label="Select detected flow" value={selectedPipeline?.pipeline_id || ""} onChange={(event) => setPipelineId(event.target.value)}>{(report.pipelines ?? []).map((pipeline) => <option value={pipeline.pipeline_id} key={pipeline.pipeline_id}>{pipeline.name} · {pipeline.node_ids.length} objects</option>)}</select><select aria-label="Filter source asset" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">All source assets</option>{mapSources.map((id) => <option key={id} value={id}>{nodeMap.get(id)?.name || id}</option>)}</select><select aria-label="Filter target asset" value={targetFilter} onChange={(event) => setTargetFilter(event.target.value)}><option value="all">All target assets</option>{mapTargets.map((id) => <option key={id} value={id}>{nodeMap.get(id)?.name || id}</option>)}</select><select aria-label="Filter mapping layer" value={mapLayerFilter} onChange={(event) => setMapLayerFilter(event.target.value)}><option value="all">All layers</option>{layerOrder.map((item) => <option key={item}>{item}</option>)}</select><button onClick={() => setHideQualityChecks((current) => !current)}>{hideQualityChecks ? "Show dbt test links" : "Hide dbt test links"}</button><button onClick={() => setShowEdgePanel((current) => !current)}>{showEdgePanel ? "Hide link details" : "Show link details"}</button><button onClick={() => setAddingEdge(true)}>Propose mapping</button></section>
        <section className={local.runtimePanel} aria-label="Runtime evidence">
          <header><div><span>RUNTIME EVIDENCE</span><h2>{report.runtime?.status || "NOT_RUN"}</h2><p>{report.runtime?.note || "Discovery and planned lineage are not execution evidence."}</p></div><button className={styles.secondary} disabled={runtimeBusy} onClick={() => void refreshRuntime()}>{runtimeBusy ? "Refreshing…" : "Refresh runtime evidence"}</button></header>
          <div className={local.runtimeGrid}>{["airflow", "dbt", "snowflake"].map((system) => { const item = report.runtime?.systems?.[system]; return <article key={system}><span>{system}</span><strong>{item?.status || "NOT_RUN"}</strong><small>{item?.completed_at ? `Completed ${new Date(item.completed_at).toLocaleString()}` : "No matching runtime completion observed"}</small></article>; })}</div>
          <footer>{report.runtime?.observed_edge_count || 0} observed edges · {report.runtime?.observed_node_count || 0} observed nodes · {report.runtime?.refreshed_at ? `refreshed ${new Date(report.runtime.refreshed_at).toLocaleString()}` : "not refreshed"}</footer>
        </section>
        <section className={local.aiPanel} aria-label="AI lineage verification"><header><div><span>USER-INVOKED AI REVIEW</span><h2>{aiStatusLabel(aiReview?.status, aiBusy, openAiStatus)}</h2><p>AI can challenge deterministic mappings, but it cannot approve lineage or promote runtime evidence.</p></div><div className={local.aiActions}><button disabled={aiBusy} onClick={() => void verifyWithAI("proposed")}>{aiBusy ? "Reviewing…" : "Verify proposed mappings"}</button><button disabled={aiBusy} onClick={() => void verifyWithAI("all")}>Verify entire graph</button><button disabled={aiBusy} onClick={() => void verifyWithAI("conflicts")}>Review conflicts</button></div></header>{aiReview && <div className={local.aiResult}>
          <span>{aiReview.subjects_requested} relationships reviewed · {aiReview.reviews?.filter((item) => item.needs_human_approval).length || 0} need human approval</span>
          <small>{aiReview.outcome || aiReview.reason || `${aiReview.reviews?.length || 0} AI findings · ${aiReview.created_at ? new Date(aiReview.created_at).toLocaleString() : ""}`}</small>
          <div className={local.aiReviewMeta}><span>Validation: {aiReview.validation?.status || "NOT RUN"}</span><span>Evidence: {aiReview.evidence_state || "NOT CHECKED"}</span><span>Provider: {aiReview.provider || "—"} · {aiReview.model || "—"}</span>{typeof aiReview.latency_ms === "number" && <span>{aiReview.latency_ms} ms</span>}</div>
          {aiReview.uncertainty && <p><strong>Uncertainty:</strong> {aiReview.uncertainty}</p>}
          {aiReview.reviews?.slice(0, 3).map((item) => <article key={item.subject_id}><strong>{item.subject_id}</strong><span>{Math.round(item.confidence * 100)}% evidence coverage · {item.needs_human_approval ? "Needs human approval" : "Review"}</span><small>{item.reasoning}{item.conflicts?.length ? ` Conflicts: ${item.conflicts.join("; ")}` : ""}</small><small>Citations: {item.evidence_links?.length ? item.evidence_links.map((link, index) => <span key={link.evidence_id || index}>{index ? ", " : ""}{link.href ? <a href={link.href} target="_blank" rel="noreferrer">{link.evidence_id}</a> : link.evidence_id}</span>) : "none"} · model score retained as advisory: {Math.round((item.model_confidence ?? 0) * 100)}%</small></article>)}
          <p><strong>Next action:</strong> {aiReview.next_action || "Inspect the cited evidence and review the mapping."}</p>
        </div>}</section>
        {selectedPipeline ? <><section className={local.mapSummary}><article><span>Map scope</span><strong>{mapScope === "selected" ? "Selected" : "Catalog"}</strong><small>{mapScope === "selected" ? `${selectedAssetIds.length} saved asset${selectedAssetIds.length === 1 ? "" : "s"}` : `${report.summary.top_level_assets} accepted objects`}</small></article><article><span>Objects in graph</span><strong>{selectedPipelineNodes.length}</strong><small>Drag to arrange · click to inspect</small></article><article><span>Links in graph</span><strong>{graphLinkCount}</strong><small>{hideQualityChecks ? `${groupedQualityLinkCount} quality-check group link${groupedQualityLinkCount === 1 ? "" : "s"} · detail list collapsed` : "All evidence links shown"}</small></article></section><details className={local.mappingTableDetails}><summary>Open mapping list <span>{displayedPipelineEdges.length} links · optional list view</span></summary><section className={local.mappingTable}><header><div><h2>Asset mappings</h2><p>Use the graph as the primary view. This compact list is available for precise scanning.</p></div><strong>{displayedPipelineEdges.length} links</strong></header><div><table><thead><tr><th>Source asset</th><th>Target asset</th><th>Lineage state</th><th>Runtime</th></tr></thead><tbody>{displayedPipelineEdges.slice(0, 80).map((edge) => <tr key={edge.edge_id}><td>{nodeMap.get(edge.source_asset_id)?.name || edge.source_asset_id}</td><td>{nodeMap.get(edge.target_asset_id)?.name || edge.target_asset_id}</td><td><span className={`${local.status} ${edge.lineage_state === "OBSERVED" ? local.good : local.review}`}>{edge.lineage_state || "PLANNED"}</span></td><td>{edge.runtime_status || "NOT_RUN"}</td></tr>)}</tbody></table>{!displayedPipelineEdges.length && <div className={local.emptyResult}>No evidence-backed mappings match the current filters.</div>}</div></section></details><div className={`${local.mapWorkspace} ${showEdgePanel ? "" : local.mapWorkspaceFull}`}><section className={local.pipelineCanvas}><header><div><span className={`${local.status} ${tone(selectedPipeline.status)}`}>{selectedPipeline.status}</span><h2>{selectedPipeline.name}</h2><p>{selectedPipelineNodes.length} visible nodes · {graphLinkCount} visible links · {selectedPipeline.technology_kinds.join(" → ")}</p></div></header>{selectedPipelineNodes.length ? <FlowGraph nodes={selectedPipelineNodes} edges={visiblePipelineEdges} nodeMap={nodeMap} classifications={classifications} decisions={decisions} hideQualityChecks={hideQualityChecks} onNodeClick={(id) => void openAsset(id)} onEdgeClick={setEdgeInspector} /> : <div className={local.graphEmpty}><strong>No selected assets are in this flow.</strong><span>Switch Map scope to Full accepted catalog or select assets in Discover assets.</span></div>}</section>{showEdgePanel && <section className={local.edgePanel}><header><h3>Link details</h3><span>{displayedPipelineEdges.length}</span></header>{displayedPipelineEdges.map((edge) => {
          const source = nodeMap.get(edge.source_asset_id); const target = nodeMap.get(edge.target_asset_id); const decision = decisions.relationships[edge.edge_id]; const status = decisionStatus(edge, decision); const selected = draftRelationships[edge.edge_id] || decision?.relationship || edge.relationship; const isDraft = edge.edge_id.startsWith("draft-edge-");
          return <article key={edge.edge_id}><button className={local.edgeSummary} onClick={() => setEdgeInspector(edge)}><span className={`${local.status} ${edge.lineage_state === "OBSERVED" ? local.good : local.review}`}>{edge.lineage_state || "PLANNED"}</span><strong>{source?.name || edge.source_asset_id}</strong><i>{selected.replaceAll("_", " ")} · {isDraft ? "PROPOSED" : status} →</i><strong>{target?.name || edge.target_asset_id}</strong></button><select aria-label={`Relationship for ${source?.name || edge.source_asset_id} to ${target?.name || edge.target_asset_id}`} value={selected} onChange={(event) => setDraftRelationships((current) => ({ ...current, [edge.edge_id]: event.target.value }))}>{relationshipOptions.map((item) => <option key={item}>{item}</option>)}</select><div className={local.actions}>{isDraft ? <><button onClick={() => void verifyRelationship(edge, selected)}>Verify and save</button><button onClick={() => setProposedEdges((current) => current.filter((item) => item.edge_id !== edge.edge_id))}>Discard</button></> : <><button onClick={() => void verifyRelationship(edge, selected)}>Verify</button><button onClick={() => void submitReview(edge.edge_id, { subject_type: "relationship", subject_id: edge.edge_id, status: "REJECTED", value: selected })}>Reject</button>{decision && <button onClick={() => void submitReview(edge.edge_id, { subject_type: "relationship", subject_id: edge.edge_id, status: "RESET" })}>Reset</button>}</>}</div></article>;
        })}</section>}</div></> : <section className={styles.panel}><p>No source-rooted pipeline flow was detected. Review unconnected objects instead of accepting an invented path.</p></section>}
        <section className={local.unresolved}><header><div><span>COVERAGE GAPS</span><h2>Objects not connected to a pipeline</h2><p>These discovered objects remain visible until evidence or an operator-reviewed link connects them.</p></div><b>{unresolvedNodes.length}</b></header><div>{unresolvedNodes.slice(0, 80).map((node) => <button key={node.node_id} onClick={() => void openAsset(node.node_id)}><strong>{node.name}</strong><small>{technology(node)} · {node.kind.replaceAll("_", " ")}</small></button>)}</div>{unresolvedNodes.length > 80 && <p>Showing 80 of {unresolvedNodes.length}; use Objects &amp; Roles search to inspect the remainder.</p>}</section>
      </>}
    </>}

    {assetSource && report && (() => {
      const classification = classifications.get(assetSource.asset.node_id);
      const items = evidenceFor(report, classification?.evidence_ids || []);
      const children = childMap.get(String(assetSource.asset.properties.discovery_asset_id)) || [];
      const metadata = Object.entries(assetSource.asset.properties).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value) && value !== "" && value !== null);
      const displayedSource = showFullSource && assetSource.full_content ? assetSource.full_content : assetSource.content;
      return <div className={local.overlay} role="dialog" aria-modal="true" aria-label="Object evidence inspector"><section className={local.inspector}><header><div><span>{assetSource.asset.kind.replaceAll("_", " ")} / READ ONLY</span><h2>{assetSource.asset.name}</h2><p>{assetSource.path || String(assetSource.asset.properties.evidence_location || assetSource.reason || "Live discovery metadata")}</p></div><button onClick={() => setAssetSource(null)}>Close</button></header>
        <nav className={local.inspectorTabs} aria-label="Object evidence views">
          {([['metadata', 'Live metadata'], ['definition', 'Definition'], ['evidence', 'Lineage evidence'], ['children', children[0]?.kind === 'airflow_task' ? 'Tasks' : 'Columns'], ['history', 'Execution history']] as Array<[InspectorTab, string]>).map(([id, label]) => <button className={inspectorTab === id ? local.activeInspectorTab : ""} key={id} onClick={() => setInspectorTab(id)}>{label}{id === "children" && children.length ? ` (${children.length})` : ""}</button>)}
        </nav>
        {inspectorTab === "metadata" && <><div className={local.objectSummary}><div><span>Classification</span><strong>{classification?.roles.map((item) => item.replaceAll("_", " ")).join(", ") || "Not classified"}</strong></div><div><span>Review status</span><strong>{classification ? decisionStatus(classification, decisions.assets[classification.asset_id]) : "DISCOVERED"}</strong></div><div><span>Evidence records</span><strong>{items.length}</strong></div></div><dl className={local.metadataList}>{metadata.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>)}</dl></>}
        {inspectorTab === "definition" && <>{assetSource.content_scope === "FULL_FILE" && <div className={styles.dangerStrip}><strong>Exact definition was not isolated.</strong> This is the attached source file, not a claim that every statement defines the selected object.</div>}{assetSource.content_scope === "OBJECT_DEFINITION" && <div className={styles.successStrip}><strong>Selected object definition isolated.</strong> The code below is the matching definition, not the entire deployment file.</div>}{displayedSource ? <><div className={local.sourceToolbar}><span>{showFullSource ? "Complete source file" : assetSource.content_scope === "OBJECT_DEFINITION" ? "Exact object definition" : "Attached source file"}</span>{assetSource.full_content_available && <button onClick={() => setShowFullSource((current) => !current)}>{showFullSource ? "Show exact definition" : "Open full file"}</button>}</div><pre className={local.code}><code>{displayedSource}</code></pre></> : <div className={styles.dangerStrip}>{assetSource.reason || "No repository definition is attached to this object."}</div>}</>}
        {inspectorTab === "evidence" && <>{items.length ? <div className={local.evidenceGrid}>{items.map((item) => <article key={item.evidence_id}><span>{item.maturity}</span><strong>{item.source}</strong><small>{new Date(item.observed_at).toLocaleString()}</small><p>{String(item.payload.collection_method || "Collection method not recorded")}</p><code>{String(item.payload.location || "No code/metadata location")}</code></article>)}</div> : <div className={styles.dangerStrip}>No relationship evidence is attached to this object.</div>}</>}
        {inspectorTab === "children" && <>{children.length ? <div className={local.childInspector}>{children.map((child) => <button key={child.node_id} onClick={() => void openAsset(child.node_id)}><strong>{child.name.split(".").pop()}</strong><span>{String(child.properties.detail || child.kind)}</span></button>)}</div> : <div className={styles.infoStrip}><span>i</span><div><strong>No child objects discovered</strong><p>No columns or tasks were attached to this object by the current discovery snapshot.</p></div></div>}</>}
        {inspectorTab === "history" && <div className={styles.infoStrip}><span>i</span><div><strong>No object-level execution history is attached here</strong><p>Discovery evidence and runtime history are kept separate. This view will show only backend-sourced runs when an object-level execution reference exists.</p></div></div>}
      </section></div>;
    })()}

    {edgeInspector && report && <div className={local.overlay} role="dialog" aria-modal="true" aria-label="Relationship evidence inspector"><section className={local.inspector}><header><div><span>RELATIONSHIP / {edgeInspector.lineage_state || "PLANNED"} · {edgeInspector.runtime_status || "NOT_RUN"}</span><h2>{nodeMap.get(edgeInspector.source_asset_id)?.name} → {nodeMap.get(edgeInspector.target_asset_id)?.name}</h2><p>{edgeInspector.rationale}</p></div><button onClick={() => setEdgeInspector(null)}>Close</button></header><div className={local.evidenceGrid}>{evidenceFor(report, edgeInspector.evidence_ids).map((item) => <article key={item.evidence_id}><span>{item.maturity}</span><strong>{item.source}</strong><small>{new Date(item.observed_at).toLocaleString()}</small><p>{String(item.payload.collection_method || "Repository/metadata analyzer")}</p><code>{String(item.payload.location || item.evidence_id)}</code></article>)}</div></section></div>}

    {addingEdge && report && <div className={local.overlay} role="dialog" aria-modal="true" aria-label="Add relationship"><section className={local.inspector}><header><div><span>USER-GOVERNED EDGE</span><h2>Propose a relationship</h2><p>This stays local until you inspect the evidence and explicitly verify it.</p></div><button onClick={() => setAddingEdge(false)}>Close</button></header><div className={local.edgeForm}><label>Upstream asset<select value={newEdge.source} onChange={(event) => setNewEdge((current) => ({ ...current, source: event.target.value }))}><option value="">Select upstream</option>{[...classifications.keys()].filter((id) => { const node = nodeMap.get(id); return Boolean(node && isTopLevel(node)); }).map((id) => <option key={id} value={id}>{nodeMap.get(id)?.name}</option>)}</select></label><label>Relationship<select value={newEdge.relationship} onChange={(event) => setNewEdge((current) => ({ ...current, relationship: event.target.value }))}>{relationshipOptions.map((item) => <option key={item}>{item}</option>)}</select></label><label>Downstream asset<select value={newEdge.target} onChange={(event) => setNewEdge((current) => ({ ...current, target: event.target.value }))}><option value="">Select downstream</option>{[...classifications.keys()].filter((id) => { const node = nodeMap.get(id); return Boolean(node && isTopLevel(node)); }).map((id) => <option key={id} value={id}>{nodeMap.get(id)?.name}</option>)}</select></label></div><button className={styles.primary} onClick={addRelationship}>Add local proposal</button></section></div>}
  </ProjectManagementShell>;
}

export default function ProjectDesignPage() {
  return <ProjectDesignView />;
}
