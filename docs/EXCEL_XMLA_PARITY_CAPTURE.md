# Excel XMLA parity capture

The governed semantic platform treats Excel as a first-class parity surface. The canonical semantic contract generates one MDX query per verified business question. Those MDX queries target the same governed semantic model that Excel consumes through XMLA; no spreadsheet formula is allowed to reimplement governed metrics.

## What this certifies

A successful capture proves that the configured XMLA/MDX model returns the expected dimensions and metrics for every parity case under the operator-supplied security-context label. The capture does **not** claim that automation opened the interactive Excel desktop UI. It certifies the Excel-compatible XMLA/MDX query path.

## Requirements

The target Snowflake/AtScale XMLA endpoint must be enabled and accessible from the runner host. The runner also needs Microsoft ADOMD.NET (or a compatible custom runner implementing the same JSON protocol).

The supplied PowerShell runner is `scripts/rga_testbed/excel_xmla_runner.ps1`. It reads one JSON request from stdin and returns JSON rows on stdout. Connection credentials are never persisted in evidence.

Configure:

```bash
export EXCEL_XMLA_CONNECTION_STRING='Provider=MSOLAP;Data Source=...;Initial Catalog=...;...'
export EXCEL_XMLA_CUBE='Model'
export EXCEL_XMLA_RUNNER='pwsh -NoProfile -File scripts/rga_testbed/excel_xmla_runner.ps1'
```

The exact connection string depends on the XMLA provider/account configuration. Keep it in a secret store or process environment; do not commit it.

## Build/inspect the capture plan

```bash
python scripts/rga_testbed/generate_parity_suite.py \
  --output artifacts/semantic_platform_demo/release/parity \
  --database RGA_SYNTHETIC_TESTBED

python scripts/rga_testbed/capture_excel_parity_evidence.py \
  --manifest artifacts/semantic_platform_demo/release/parity/parity_manifest.json \
  --evidence-dir artifacts/semantic_platform_demo/external-evidence \
  --security-context ROLE_ANALYST \
  --dry-run
```

Dry-run requires no XMLA credentials.

## Capture real governed rows

```bash
python scripts/rga_testbed/capture_excel_parity_evidence.py \
  --manifest artifacts/semantic_platform_demo/release/parity/parity_manifest.json \
  --evidence-dir artifacts/semantic_platform_demo/external-evidence \
  --security-context ROLE_ANALYST \
  --cube-name "$EXCEL_XMLA_CUBE" \
  --confirm
```

For each case the tool writes `<case>.excel.json` with:

- `capture_status=CAPTURED`;
- the shared security-context label;
- cube/model name;
- MDX template/rendered SHA-256 values;
- non-sensitive runner metadata;
- normalized dimension/metric rows.

The XMLA connection string is never written to evidence. Sensitive runner metadata keys (token, secret, password, credential, connection string) are removed recursively.

## Final parity gate

After Snowflake Semantic View, Cortex Agent/MCP, Power BI, and Excel evidence are all captured under the same security-context label, run the existing consumer parity certification:

```bash
semantic-platform certify-consumers \
  --workspace artifacts/semantic_platform_demo \
  --evidence-dir artifacts/semantic_platform_demo/external-evidence
```

A connectivity-only Excel workbook is not sufficient. Certification requires captured governed XMLA rows matching the canonical case grain and metric values.
