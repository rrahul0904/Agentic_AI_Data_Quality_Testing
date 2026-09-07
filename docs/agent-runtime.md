# Agent Runtime

The runtime has bounded roles, not an autonomous agent swarm. `PlannerAgent` produces a structured engineering plan including discovery, verification, migration wave, approval, and risk information. It has no execution dependency.

`RepairAgent` runs only caller-provided sandbox proposal and verification callbacks and enforces a configured maximum attempt count (three by default). It records concise diagnosis, artifact reference, verification evidence, and outcome; it does not retain hidden reasoning or recursively create agents.
