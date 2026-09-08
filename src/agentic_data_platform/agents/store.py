from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_data_platform.agents.contracts import (
    AgentHypothesis,
    AgentResult,
    EvidenceRecord,
    IncidentState,
    InvestigationTransition,
    RemediationPlan,
)
from agentic_data_platform.models import new_id, utc_now


_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  title TEXT NOT NULL,
  affected_asset TEXT NOT NULL,
  state TEXT NOT NULL,
  mode TEXT NOT NULL,
  anomaly_json TEXT NOT NULL,
  first_divergence TEXT,
  root_cause TEXT,
  root_cause_confidence REAL NOT NULL DEFAULT 0,
  blast_radius_json TEXT NOT NULL DEFAULT '[]',
  certification TEXT NOT NULL DEFAULT 'FAILED',
  approved INTEGER NOT NULL DEFAULT 0,
  execution_result_json TEXT NOT NULL DEFAULT '{}',
  verification_result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_transitions (
  transition_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_evidence (
  evidence_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  tier INTEGER NOT NULL,
  kind TEXT NOT NULL,
  source TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  correlation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_hypotheses (
  hypothesis_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  name TEXT NOT NULL,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  supporting_json TEXT NOT NULL,
  contradictory_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_agent_runs (
  result_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remediation_plans (
  plan_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  status TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT
);
CREATE TABLE IF NOT EXISTS incident_mappings (
  mapping_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  source_asset TEXT NOT NULL,
  target_asset TEXT NOT NULL,
  mapping_type TEXT NOT NULL,
  expression_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incident_transition_incident ON incident_transitions(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incident_evidence_incident ON incident_evidence(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incident_agent_run_incident ON incident_agent_runs(incident_id, created_at);
"""


_ALLOWED: dict[IncidentState, set[IncidentState]] = {
    IncidentState.DETECTED: {IncidentState.INVESTIGATING, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.INVESTIGATING: {IncidentState.EVIDENCE_COLLECTION, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.EVIDENCE_COLLECTION: {IncidentState.RCA, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.RCA: {IncidentState.IMPACT_ANALYSIS, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.IMPACT_ANALYSIS: {IncidentState.REMEDIATION_PROPOSED, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.REMEDIATION_PROPOSED: {IncidentState.AWAITING_APPROVAL, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.AWAITING_APPROVAL: {IncidentState.REMEDIATING, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.REMEDIATING: {IncidentState.VERIFYING, IncidentState.BLOCKED, IncidentState.FAILED},
    IncidentState.VERIFYING: {IncidentState.RECERTIFYING, IncidentState.FAILED},
    IncidentState.RECERTIFYING: {IncidentState.RESOLVED, IncidentState.FAILED},
    IncidentState.RESOLVED: set(),
    IncidentState.BLOCKED: set(),
    IncidentState.FAILED: set(),
}


class InvestigationStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.connection.executescript(_SCHEMA)
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(incident_evidence)").fetchall()
        }
        if "correlation_json" not in columns:
            self.connection.execute(
                "ALTER TABLE incident_evidence ADD COLUMN correlation_json TEXT NOT NULL DEFAULT '{}'"
            )
        self.connection.commit()

    def create_incident(
        self,
        scenario_id: str,
        title: str,
        affected_asset: str,
        anomaly: dict[str, Any],
        *,
        mode: str = "LOCAL_PROVING_GROUND",
    ) -> str:
        incident_id = new_id("incident")
        now = utc_now()
        with self.lock:
            self.connection.execute(
                "INSERT INTO incidents (incident_id,scenario_id,title,affected_asset,state,mode,anomaly_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (incident_id, scenario_id, title, affected_asset, IncidentState.DETECTED.value, mode, json.dumps(anomaly, sort_keys=True), now, now),
            )
            self.connection.commit()
        return incident_id

    def incident(self, incident_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(f"incident not found: {incident_id}")
        result = dict(row)
        result["anomaly"] = json.loads(result.pop("anomaly_json"))
        result["blast_radius"] = json.loads(result.pop("blast_radius_json"))
        result["execution_result"] = json.loads(result.pop("execution_result_json"))
        result["verification_result"] = json.loads(result.pop("verification_result_json"))
        result["approved"] = bool(result["approved"])
        return result

    def list_incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT incident_id FROM incidents ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
        return [self.incident(row["incident_id"]) for row in rows]

    def transition(self, incident_id: str, target: IncidentState, reason: str) -> InvestigationTransition:
        current = IncidentState(self.incident(incident_id)["state"])
        if target not in _ALLOWED[current]:
            raise ValueError(f"invalid incident transition: {current.value} -> {target.value}")
        item = InvestigationTransition(incident_id, current, target, reason)
        with self.lock:
            self.connection.execute(
                "INSERT INTO incident_transitions VALUES (?,?,?,?,?,?)",
                (item.transition_id, incident_id, current.value, target.value, reason, item.created_at),
            )
            self.connection.execute(
                "UPDATE incidents SET state=?,updated_at=? WHERE incident_id=?",
                (target.value, utc_now(), incident_id),
            )
            self.connection.commit()
        return item

    def transitions(self, incident_id: str) -> list[InvestigationTransition]:
        rows = self.connection.execute(
            "SELECT * FROM incident_transitions WHERE incident_id=? ORDER BY created_at,rowid",
            (incident_id,),
        ).fetchall()
        return [
            InvestigationTransition(
                row["incident_id"],
                IncidentState(row["from_state"]) if row["from_state"] else None,
                IncidentState(row["to_state"]),
                row["reason"],
                row["transition_id"],
                row["created_at"],
            )
            for row in rows
        ]

    def save_evidence(self, incident_id: str, evidence: EvidenceRecord) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO incident_evidence VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    evidence.evidence_id, incident_id, int(evidence.tier), evidence.kind, evidence.source,
                    evidence.summary, json.dumps(evidence.payload, default=str, sort_keys=True),
                    json.dumps(evidence.correlation, default=str, sort_keys=True), evidence.created_at,
                ),
            )
            self.connection.commit()

    def save_agent_result(self, incident_id: str, result: AgentResult) -> None:
        payload = result.public()
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO incident_agent_runs VALUES (?,?,?,?,?,?)",
                (result.result_id, incident_id, result.role.value, result.status, json.dumps(payload, default=str, sort_keys=True), result.created_at),
            )
            self.connection.commit()

    def save_mappings(self, incident_id: str, mappings: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.lock:
            for mapping in mappings:
                self.connection.execute(
                    "INSERT INTO incident_mappings VALUES (?,?,?,?,?,?,?)",
                    (
                        new_id("mapping"),
                        incident_id,
                        str(mapping["source"]),
                        str(mapping["target"]),
                        str(mapping.get("mapping_type") or "lineage"),
                        json.dumps(mapping.get("expression") or {}, default=str, sort_keys=True),
                        now,
                    ),
                )
            self.connection.commit()

    def mappings(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM incident_mappings WHERE incident_id=? ORDER BY rowid",
            (incident_id,),
        ).fetchall()
        return [
            {
                "mapping_id": row["mapping_id"],
                "source": row["source_asset"],
                "target": row["target_asset"],
                "mapping_type": row["mapping_type"],
                "expression": json.loads(row["expression_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_hypothesis(self, incident_id: str, item: AgentHypothesis) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO incident_hypotheses VALUES (?,?,?,?,?,?,?,?)",
                (
                    item.hypothesis_id, incident_id, item.name, item.statement, item.status.value, item.confidence,
                    json.dumps(list(item.supporting_evidence_ids)), json.dumps(list(item.contradictory_evidence_ids)),
                ),
            )
            self.connection.commit()

    def save_remediation(self, incident_id: str, plan: RemediationPlan) -> None:
        with self.lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO remediation_plans (plan_id,incident_id,plan_json,status) VALUES (?,?,?,'PROPOSED')",
                (plan.plan_id, incident_id, json.dumps(asdict(plan), default=str, sort_keys=True)),
            )
            self.connection.commit()

    def approve(self, incident_id: str, *, approved_by: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT plan_id FROM remediation_plans WHERE incident_id=? ORDER BY rowid DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no remediation plan for incident: {incident_id}")
        current = IncidentState(self.incident(incident_id)["state"])
        if current is not IncidentState.AWAITING_APPROVAL:
            raise ValueError(f"incident is {current.value}, not AWAITING_APPROVAL")
        now = utc_now()
        with self.lock:
            self.connection.execute(
                "UPDATE remediation_plans SET status='APPROVED',approved_by=?,approved_at=? WHERE plan_id=?",
                (approved_by, now, row["plan_id"]),
            )
            self.connection.execute(
                "UPDATE incidents SET approved=1,updated_at=? WHERE incident_id=?",
                (now, incident_id),
            )
            self.connection.commit()
        return {"incident_id": incident_id, "plan_id": row["plan_id"], "approved": True, "approved_by": approved_by, "approved_at": now}

    def update_outcome(
        self,
        incident_id: str,
        *,
        first_divergence: str | None = None,
        root_cause: str | None = None,
        root_cause_confidence: float | None = None,
        blast_radius: list[str] | tuple[str, ...] | None = None,
        certification: str | None = None,
        execution_result: dict[str, Any] | None = None,
        verification_result: dict[str, Any] | None = None,
    ) -> None:
        current = self.incident(incident_id)
        values = {
            "first_divergence": first_divergence if first_divergence is not None else current["first_divergence"],
            "root_cause": root_cause if root_cause is not None else current["root_cause"],
            "root_cause_confidence": root_cause_confidence if root_cause_confidence is not None else current["root_cause_confidence"],
            "blast_radius": list(blast_radius) if blast_radius is not None else current["blast_radius"],
            "certification": certification if certification is not None else current["certification"],
            "execution_result": execution_result if execution_result is not None else current["execution_result"],
            "verification_result": verification_result if verification_result is not None else current["verification_result"],
        }
        with self.lock:
            self.connection.execute(
                """UPDATE incidents SET first_divergence=?,root_cause=?,root_cause_confidence=?,
                blast_radius_json=?,certification=?,execution_result_json=?,verification_result_json=?,updated_at=?
                WHERE incident_id=?""",
                (
                    values["first_divergence"], values["root_cause"], values["root_cause_confidence"],
                    json.dumps(values["blast_radius"]), values["certification"],
                    json.dumps(values["execution_result"], default=str, sort_keys=True),
                    json.dumps(values["verification_result"], default=str, sort_keys=True),
                    utc_now(), incident_id,
                ),
            )
            self.connection.commit()

    def agent_results(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT result_json FROM incident_agent_runs WHERE incident_id=? ORDER BY created_at,rowid",
            (incident_id,),
        ).fetchall()
        return [json.loads(row["result_json"]) for row in rows]

    def evidence(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM incident_evidence WHERE incident_id=? ORDER BY tier,created_at,rowid",
            (incident_id,),
        ).fetchall()
        return [
            {
                "evidence_id": row["evidence_id"],
                "tier": f"T{row['tier']}",
                "kind": row["kind"],
                "source": row["source"],
                "summary": row["summary"],
                "payload": json.loads(row["payload_json"]),
                "correlation": json.loads(row["correlation_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def hypotheses(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM incident_hypotheses WHERE incident_id=? ORDER BY confidence DESC,name",
            (incident_id,),
        ).fetchall()
        return [
            {
                "hypothesis_id": row["hypothesis_id"], "name": row["name"], "statement": row["statement"],
                "status": row["status"], "confidence": row["confidence"],
                "supporting_evidence_ids": json.loads(row["supporting_json"]),
                "contradictory_evidence_ids": json.loads(row["contradictory_json"]),
            }
            for row in rows
        ]

    def remediation(self, incident_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM remediation_plans WHERE incident_id=? ORDER BY rowid DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            **json.loads(row["plan_json"]),
            "status": row["status"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
        }
