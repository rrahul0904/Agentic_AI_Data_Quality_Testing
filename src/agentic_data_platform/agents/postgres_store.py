from __future__ import annotations

import json
import threading
from dataclasses import asdict
from typing import Any

from agentic_data_platform.agents.contracts import (
    AgentHypothesis,
    AgentResult,
    EvidenceRecord,
    IncidentState,
    InvestigationTransition,
    RemediationPlan,
)
from agentic_data_platform.agents.store import _ALLOWED
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
  root_cause_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
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
  confidence DOUBLE PRECISION NOT NULL,
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
  approved_at TEXT,
  created_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS asset_certifications (
  certification_id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  asset TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  evaluated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incident_transition_incident ON incident_transitions(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incident_evidence_incident ON incident_evidence(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_incident_agent_run_incident ON incident_agent_runs(incident_id, created_at);
CREATE INDEX IF NOT EXISTS idx_remediation_incident ON remediation_plans(incident_id, created_at);
"""


class PostgresInvestigationStore:
    """PostgreSQL implementation of the durable InvestigationStore contract."""

    def __init__(self, dsn: str) -> None:
        if not dsn.startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgresInvestigationStore requires a postgres:// or postgresql:// DSN")
        self.dsn = dsn
        self._connection: Any | None = None
        self.lock = threading.Lock()
        self.initialize()

    def _conn(self) -> Any:
        if self._connection is None:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - optional cloud dependency
                raise RuntimeError("PostgreSQL investigations require psycopg; install the 'cloud' extra") from exc
            self._connection = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)
        return self._connection

    def initialize(self) -> None:
        with self.lock:
            with self._conn().cursor() as cursor:
                for statement in _SCHEMA.split(";"):
                    sql = statement.strip()
                    if sql:
                        cursor.execute(sql)

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

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
        self._execute(
            """
            INSERT INTO incidents (
              incident_id,scenario_id,title,affected_asset,state,mode,anomaly_json,created_at,updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                incident_id,
                scenario_id,
                title,
                affected_asset,
                IncidentState.DETECTED.value,
                mode,
                json.dumps(anomaly, sort_keys=True),
                now,
                now,
            ),
        )
        return incident_id

    def incident(self, incident_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM incidents WHERE incident_id=%s", (incident_id,))
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
        rows = self._fetchall(
            "SELECT incident_id FROM incidents ORDER BY created_at DESC, incident_id DESC LIMIT %s",
            (max(1, min(limit, 1000)),),
        )
        return [self.incident(row["incident_id"]) for row in rows]

    def transition(self, incident_id: str, target: IncidentState, reason: str) -> InvestigationTransition:
        current = IncidentState(self.incident(incident_id)["state"])
        if target not in _ALLOWED[current]:
            raise ValueError(f"invalid incident transition: {current.value} -> {target.value}")
        item = InvestigationTransition(incident_id, current, target, reason)
        with self.lock:
            conn = self._conn()
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO incident_transitions VALUES (%s,%s,%s,%s,%s,%s)",
                        (item.transition_id, incident_id, current.value, target.value, reason, item.created_at),
                    )
                    cursor.execute(
                        "UPDATE incidents SET state=%s,updated_at=%s WHERE incident_id=%s",
                        (target.value, utc_now(), incident_id),
                    )
        return item

    def transitions(self, incident_id: str) -> list[InvestigationTransition]:
        rows = self._fetchall(
            "SELECT * FROM incident_transitions WHERE incident_id=%s ORDER BY created_at,transition_id",
            (incident_id,),
        )
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
        try:
            self._execute(
                "INSERT INTO incident_evidence VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    evidence.evidence_id,
                    incident_id,
                    int(evidence.tier),
                    evidence.kind,
                    evidence.source,
                    evidence.summary,
                    json.dumps(evidence.payload, default=str, sort_keys=True),
                    json.dumps(evidence.correlation, default=str, sort_keys=True),
                    evidence.created_at,
                ),
            )
        except Exception as exc:
            # psycopg exposes SQLSTATE 23505 on duplicate primary keys. Avoid
            # importing psycopg error classes at module import time so local mode
            # retains a dependency-free import path.
            if getattr(exc, "sqlstate", None) == "23505":
                raise ValueError(f"immutable evidence already exists: {evidence.evidence_id}") from exc
            raise

    def save_agent_result(self, incident_id: str, result: AgentResult) -> None:
        payload = result.public()
        self._execute(
            """
            INSERT INTO incident_agent_runs (result_id,incident_id,role,status,result_json,created_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (result_id) DO UPDATE
            SET incident_id=EXCLUDED.incident_id,
                role=EXCLUDED.role,
                status=EXCLUDED.status,
                result_json=EXCLUDED.result_json,
                created_at=EXCLUDED.created_at
            """,
            (
                result.result_id,
                incident_id,
                result.role.value,
                result.status,
                json.dumps(payload, default=str, sort_keys=True),
                result.created_at,
            ),
        )

    def save_certification(
        self,
        incident_id: str,
        asset: str,
        status: str,
        reason: str,
        *,
        evidence_ids: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if status not in {"UNKNOWN", "AT_RISK", "FAILED", "CERTIFIED"}:
            raise ValueError(f"invalid certification status: {status}")
        item = {
            "certification_id": new_id("certification"),
            "incident_id": incident_id,
            "asset": asset,
            "status": status,
            "reason": reason,
            "evidence_ids": list(evidence_ids),
            "evaluated_at": utc_now(),
        }
        self._execute(
            "INSERT INTO asset_certifications VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                item["certification_id"],
                incident_id,
                asset,
                status,
                reason,
                json.dumps(item["evidence_ids"]),
                item["evaluated_at"],
            ),
        )
        return item

    def certifications(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM asset_certifications WHERE incident_id=%s ORDER BY evaluated_at,certification_id",
            (incident_id,),
        )
        return [
            {
                "certification_id": row["certification_id"],
                "incident_id": row["incident_id"],
                "asset": row["asset"],
                "status": row["status"],
                "reason": row["reason"],
                "evidence_ids": json.loads(row["evidence_ids_json"]),
                "evaluated_at": row["evaluated_at"],
            }
            for row in rows
        ]

    def latest_certifications(self, incident_id: str) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for item in self.certifications(incident_id):
            latest[item["asset"]] = item
        return sorted(latest.values(), key=lambda item: item["asset"])

    def save_mappings(self, incident_id: str, mappings: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.lock:
            conn = self._conn()
            with conn.transaction():
                with conn.cursor() as cursor:
                    for mapping in mappings:
                        cursor.execute(
                            "INSERT INTO incident_mappings VALUES (%s,%s,%s,%s,%s,%s,%s)",
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

    def mappings(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM incident_mappings WHERE incident_id=%s ORDER BY created_at,mapping_id",
            (incident_id,),
        )
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
        self._execute(
            """
            INSERT INTO incident_hypotheses (
              hypothesis_id,incident_id,name,statement,status,confidence,supporting_json,contradictory_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (hypothesis_id) DO UPDATE
            SET incident_id=EXCLUDED.incident_id,
                name=EXCLUDED.name,
                statement=EXCLUDED.statement,
                status=EXCLUDED.status,
                confidence=EXCLUDED.confidence,
                supporting_json=EXCLUDED.supporting_json,
                contradictory_json=EXCLUDED.contradictory_json
            """,
            (
                item.hypothesis_id,
                incident_id,
                item.name,
                item.statement,
                item.status.value,
                item.confidence,
                json.dumps(list(item.supporting_evidence_ids)),
                json.dumps(list(item.contradictory_evidence_ids)),
            ),
        )

    def save_remediation(self, incident_id: str, plan: RemediationPlan) -> None:
        self._execute(
            """
            INSERT INTO remediation_plans (plan_id,incident_id,plan_json,status,created_at)
            VALUES (%s,%s,%s,'PROPOSED',%s)
            ON CONFLICT (plan_id) DO UPDATE
            SET incident_id=EXCLUDED.incident_id,
                plan_json=EXCLUDED.plan_json,
                status='PROPOSED',
                approved_by=NULL,
                approved_at=NULL,
                created_at=EXCLUDED.created_at
            """,
            (plan.plan_id, incident_id, json.dumps(asdict(plan), default=str, sort_keys=True), utc_now()),
        )

    def approve(self, incident_id: str, *, approved_by: str) -> dict[str, Any]:
        row = self._fetchone(
            """
            SELECT plan_id FROM remediation_plans
            WHERE incident_id=%s ORDER BY created_at DESC,plan_id DESC LIMIT 1
            """,
            (incident_id,),
        )
        if row is None:
            raise KeyError(f"no remediation plan for incident: {incident_id}")
        current = IncidentState(self.incident(incident_id)["state"])
        if current is not IncidentState.AWAITING_APPROVAL:
            raise ValueError(f"incident is {current.value}, not AWAITING_APPROVAL")
        now = utc_now()
        with self.lock:
            conn = self._conn()
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE remediation_plans SET status='APPROVED',approved_by=%s,approved_at=%s WHERE plan_id=%s",
                        (approved_by, now, row["plan_id"]),
                    )
                    cursor.execute(
                        "UPDATE incidents SET approved=1,updated_at=%s WHERE incident_id=%s",
                        (now, incident_id),
                    )
        return {
            "incident_id": incident_id,
            "plan_id": row["plan_id"],
            "approved": True,
            "approved_by": approved_by,
            "approved_at": now,
        }

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
        self._execute(
            """
            UPDATE incidents SET first_divergence=%s,root_cause=%s,root_cause_confidence=%s,
              blast_radius_json=%s,certification=%s,execution_result_json=%s,verification_result_json=%s,updated_at=%s
            WHERE incident_id=%s
            """,
            (
                values["first_divergence"],
                values["root_cause"],
                values["root_cause_confidence"],
                json.dumps(values["blast_radius"]),
                values["certification"],
                json.dumps(values["execution_result"], default=str, sort_keys=True),
                json.dumps(values["verification_result"], default=str, sort_keys=True),
                utc_now(),
                incident_id,
            ),
        )

    def agent_results(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT result_json FROM incident_agent_runs WHERE incident_id=%s ORDER BY created_at,result_id",
            (incident_id,),
        )
        return [json.loads(row["result_json"]) for row in rows]

    def evidence(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM incident_evidence WHERE incident_id=%s ORDER BY tier,created_at,evidence_id",
            (incident_id,),
        )
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
        rows = self._fetchall(
            "SELECT * FROM incident_hypotheses WHERE incident_id=%s ORDER BY confidence DESC,name,hypothesis_id",
            (incident_id,),
        )
        return [
            {
                "hypothesis_id": row["hypothesis_id"],
                "name": row["name"],
                "statement": row["statement"],
                "status": row["status"],
                "confidence": row["confidence"],
                "supporting_evidence_ids": json.loads(row["supporting_json"]),
                "contradictory_evidence_ids": json.loads(row["contradictory_json"]),
            }
            for row in rows
        ]

    def remediation(self, incident_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT * FROM remediation_plans
            WHERE incident_id=%s ORDER BY created_at DESC,plan_id DESC LIMIT 1
            """,
            (incident_id,),
        )
        if row is None:
            return None
        return {
            **json.loads(row["plan_json"]),
            "status": row["status"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
        }
