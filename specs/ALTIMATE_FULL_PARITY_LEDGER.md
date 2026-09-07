# Altimate Full Parity Ledger

Reference repository: `AltimateAI/altimate-code`  
Reference commit: `9361e0b11e247c2964b04fb068b52e854ddc861d`  
Target baseline: `960ec69f86b7737f0c9b30e75105dc7e0e5b424c`  
Implementation branch: `altimate-full-parity`

This file is a human summary. The authoritative machine-readable ledger is `specs/ALTIMATE_FULL_PARITY_LEDGER.json`.

## Mechanically discovered reference surface

- tools: **79**
- validators: **7**
- native: **33**
- mcp: **7**
- session: **32**
- provider: **12**
- skills: **21**

## Initial status

- MISSING: **113**
- PARTIAL: **76**
- DONE: **2**

The initial ledger is intentionally conservative. A capability may move to **DONE** only when the target implementation path, symbol, unit tests, and integration evidence are recorded. The parity gate fails while any non-external row remains `MISSING`, `PARTIAL`, `STUB`, or `UNVERIFIED`.

Airflow is outside the Altimate parity requirement for this program; the repository's independent Airflow implementation remains in scope for regression protection and beyond-Altimate integration.
