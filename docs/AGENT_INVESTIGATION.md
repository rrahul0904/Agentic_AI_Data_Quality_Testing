# Agent Investigation Lifecycle

The durable state machine is:

```text
DETECTED → INVESTIGATING → EVIDENCE_COLLECTION → RCA → IMPACT_ANALYSIS
→ REMEDIATION_PROPOSED → AWAITING_APPROVAL → REMEDIATING → VERIFYING
→ RECERTIFYING → RESOLVED
```

BLOCKED and FAILED are terminal alternatives.

The flagship scenario models Airflow and dbt both reporting SUCCESS while payment completeness degrades. Quality logic detects the anomaly; Supervisor delegates context, lineage, mapping, bounded planning and evidence collection; RCA evaluates competing hypotheses; Impact calculates blast radius; Remediation proposes a bounded recovery.

API:

- `GET /api/v1/agents/roster`
- `GET /api/v1/investigations/scenarios`
- `POST /api/v1/investigations/{scenario_id}/start`
- `GET /api/v1/investigations/{incident_id}`
- `POST /api/v1/investigations/{incident_id}/approve`
- `POST /api/v1/investigations/{incident_id}/execute`
- `POST /api/v1/investigations/{incident_id}/reject`

Approval and execution are separate operations.
