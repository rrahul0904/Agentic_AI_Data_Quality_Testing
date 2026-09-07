# Implementation Provenance

Reference Altimate commit: `9361e0b11e247c2964b04fb068b52e854ddc861d`.

| Component | Provenance |
| --- | --- |
| Existing Python control plane / ToolRegistry / permissions | Existing project functionality |
| Existing SQLGlot analysis and first-generation lineage | Existing project functionality |
| Existing dbt manifest graph | Existing project functionality |
| Existing Airflow intelligence | Existing project functionality; independent beyond-Altimate scope |
| Existing quality/reconciliation/data-diff | Existing project functionality |
| Existing ShiftForge migration engine | Existing project functionality |
| Full-parity ledger and gate | Independently implemented against behavioral inventory |
| New parity work | Default: independently implemented from documented/observed behavior; record any direct adapted code separately |

No direct copy from the Altimate repository should be assumed merely because behavior or command names are compatible. If substantial upstream source is reused later, add an explicit row here with source path and license obligations.
