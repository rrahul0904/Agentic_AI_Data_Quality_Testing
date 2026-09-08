# Agent Architecture

The runtime exposes twelve explicit roles: Supervisor, Metadata, Business Context, Lineage, Transformation, Mapping, Quality/Test, Execution Planning, Evidence, RCA, Impact, and Remediation.

The Supervisor dynamically delegates based on evidence. A source-to-RAW divergence can skip Transformation Agent work; a staging-to-intermediate divergence invokes it. Specialist investigation agents have explicit read-only tool allowlists.

Agents reason and propose. Deterministic tools measure and execute. Direct evidence outranks LLM interpretation.

Evidence tiers are T1 direct measurements, T2 runtime metadata, T3 static analysis, T4 historical inference, and T5 LLM interpretation.

Mutating remediation is separated from investigation: an incident must reach AWAITING_APPROVAL, human approval is persisted, and only then can execution begin. Local proving-ground execution is always labeled and is not live Snowflake/Airflow execution.
