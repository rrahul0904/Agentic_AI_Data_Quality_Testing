#!/usr/bin/env python3
"""Generate idempotent Snowflake CDC apply SQL for the synthetic RGA workload."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "artifacts" / "rga_cdc" / "change_events.jsonl"
DEFAULT_OUTPUT = ROOT / "snowflake" / "rga_testbed" / "003_apply_cdc.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def render(input_path: Path, database: str) -> str:
    local_path = input_path.resolve().as_posix()
    return f"""-- Generated CDC apply plan for deterministic synthetic RGA change events.
-- Supported events: policies UPDATE, premiums UPDATE, claims INSERT.
USE DATABASE {database};

PUT 'file://{local_path}' @RAW.RGA_CDC_STAGE
  AUTO_COMPRESS=FALSE
  OVERWRITE=FALSE;

COPY INTO RAW.RGA_CDC_EVENTS (EVENT, _SOURCE_FILE)
FROM (
  SELECT $1, METADATA$FILENAME
  FROM @RAW.RGA_CDC_STAGE
)
FILE_FORMAT=(FORMAT_NAME=RAW.FF_RGA_JSON)
ON_ERROR=ABORT_STATEMENT
FORCE=FALSE;

CREATE OR REPLACE TEMP TABLE TMP_RGA_CDC_PENDING AS
SELECT EVENT, _SOURCE_FILE, _INGESTED_AT
FROM (
  SELECT
    EVENT,
    _SOURCE_FILE,
    _INGESTED_AT,
    ROW_NUMBER() OVER (
      PARTITION BY EVENT:event_id::VARCHAR
      ORDER BY _INGESTED_AT DESC
    ) AS RN
  FROM RAW.RGA_CDC_EVENTS
)
WHERE RN = 1
  AND NOT EXISTS (
    SELECT 1
    FROM AUDIT.CDC_EVENT_APPLICATIONS A
    WHERE A.EVENT_ID = EVENT:event_id::VARCHAR
      AND A.STATUS = 'APPLIED'
  );

-- Policy status/update corrections.
MERGE INTO RAW.POLICIES T
USING (
  SELECT
    EVENT:event_id::VARCHAR AS EVENT_ID,
    EVENT:after:policy_id::VARCHAR AS POLICY_ID,
    EVENT:after:treaty_id::VARCHAR AS TREATY_ID,
    EVENT:after:cedant_id::VARCHAR AS CEDANT_ID,
    EVENT:after:product_id::VARCHAR AS PRODUCT_ID,
    EVENT:after:insured_id::VARCHAR AS INSURED_ID,
    EVENT:after:issue_date::DATE AS ISSUE_DATE,
    EVENT:after:policy_status::VARCHAR AS POLICY_STATUS,
    EVENT:after:sum_assured::NUMBER(18,2) AS SUM_ASSURED,
    EVENT:after:annual_premium::NUMBER(18,2) AS ANNUAL_PREMIUM,
    EVENT:after:currency_code::VARCHAR AS CURRENCY_CODE,
    EVENT:after:_generation_id::VARCHAR AS GENERATION_ID
  FROM TMP_RGA_CDC_PENDING
  WHERE EVENT:entity::VARCHAR = 'policies'
    AND EVENT:operation::VARCHAR = 'UPDATE'
) S
ON T.POLICY_ID = S.POLICY_ID
WHEN MATCHED THEN UPDATE SET
  T.TREATY_ID = S.TREATY_ID,
  T.CEDANT_ID = S.CEDANT_ID,
  T.PRODUCT_ID = S.PRODUCT_ID,
  T.INSURED_ID = S.INSURED_ID,
  T.ISSUE_DATE = S.ISSUE_DATE,
  T.POLICY_STATUS = S.POLICY_STATUS,
  T.SUM_ASSURED = S.SUM_ASSURED,
  T.ANNUAL_PREMIUM = S.ANNUAL_PREMIUM,
  T.CURRENCY_CODE = S.CURRENCY_CODE,
  T._GENERATION_ID = S.GENERATION_ID,
  T._SOURCE_FILE = 'cdc:' || S.EVENT_ID,
  T._INGESTED_AT = CURRENT_TIMESTAMP();

-- Premium corrections.
MERGE INTO RAW.PREMIUMS T
USING (
  SELECT
    EVENT:event_id::VARCHAR AS EVENT_ID,
    EVENT:after:premium_txn_id::VARCHAR AS PREMIUM_TXN_ID,
    EVENT:after:policy_id::VARCHAR AS POLICY_ID,
    EVENT:after:treaty_id::VARCHAR AS TREATY_ID,
    EVENT:after:cedant_id::VARCHAR AS CEDANT_ID,
    EVENT:after:accounting_date::DATE AS ACCOUNTING_DATE,
    EVENT:after:gross_premium::NUMBER(18,2) AS GROSS_PREMIUM,
    EVENT:after:ceded_premium::NUMBER(18,2) AS CEDED_PREMIUM,
    EVENT:after:currency_code::VARCHAR AS CURRENCY_CODE,
    EVENT:after:_generation_id::VARCHAR AS GENERATION_ID
  FROM TMP_RGA_CDC_PENDING
  WHERE EVENT:entity::VARCHAR = 'premiums'
    AND EVENT:operation::VARCHAR = 'UPDATE'
) S
ON T.PREMIUM_TXN_ID = S.PREMIUM_TXN_ID
WHEN MATCHED THEN UPDATE SET
  T.POLICY_ID = S.POLICY_ID,
  T.TREATY_ID = S.TREATY_ID,
  T.CEDANT_ID = S.CEDANT_ID,
  T.ACCOUNTING_DATE = S.ACCOUNTING_DATE,
  T.GROSS_PREMIUM = S.GROSS_PREMIUM,
  T.CEDED_PREMIUM = S.CEDED_PREMIUM,
  T.CURRENCY_CODE = S.CURRENCY_CODE,
  T._GENERATION_ID = S.GENERATION_ID,
  T._SOURCE_FILE = 'cdc:' || S.EVENT_ID,
  T._INGESTED_AT = CURRENT_TIMESTAMP();

-- Late-arriving claims.
MERGE INTO RAW.CLAIMS T
USING (
  SELECT
    EVENT:event_id::VARCHAR AS EVENT_ID,
    EVENT:after:claim_id::VARCHAR AS CLAIM_ID,
    EVENT:after:policy_id::VARCHAR AS POLICY_ID,
    EVENT:after:treaty_id::VARCHAR AS TREATY_ID,
    EVENT:after:insured_id::VARCHAR AS INSURED_ID,
    EVENT:after:event_date::DATE AS EVENT_DATE,
    EVENT:after:reported_date::DATE AS REPORTED_DATE,
    EVENT:after:claim_status::VARCHAR AS CLAIM_STATUS,
    EVENT:after:cause_code::VARCHAR AS CAUSE_CODE,
    EVENT:after:claim_amount::NUMBER(18,2) AS CLAIM_AMOUNT,
    EVENT:after:ceded_claim_amount::NUMBER(18,2) AS CEDED_CLAIM_AMOUNT,
    EVENT:after:currency_code::VARCHAR AS CURRENCY_CODE,
    EVENT:after:_generation_id::VARCHAR AS GENERATION_ID
  FROM TMP_RGA_CDC_PENDING
  WHERE EVENT:entity::VARCHAR = 'claims'
    AND EVENT:operation::VARCHAR = 'INSERT'
) S
ON T.CLAIM_ID = S.CLAIM_ID
WHEN NOT MATCHED THEN INSERT (
  CLAIM_ID,
  POLICY_ID,
  TREATY_ID,
  INSURED_ID,
  EVENT_DATE,
  REPORTED_DATE,
  CLAIM_STATUS,
  CAUSE_CODE,
  CLAIM_AMOUNT,
  CEDED_CLAIM_AMOUNT,
  CURRENCY_CODE,
  _GENERATION_ID,
  _SOURCE_FILE,
  _INGESTED_AT
) VALUES (
  S.CLAIM_ID,
  S.POLICY_ID,
  S.TREATY_ID,
  S.INSURED_ID,
  S.EVENT_DATE,
  S.REPORTED_DATE,
  S.CLAIM_STATUS,
  S.CAUSE_CODE,
  S.CLAIM_AMOUNT,
  S.CEDED_CLAIM_AMOUNT,
  S.CURRENCY_CODE,
  S.GENERATION_ID,
  'cdc:' || S.EVENT_ID,
  CURRENT_TIMESTAMP()
);

-- Audit only supported events after all mutations above succeed.
INSERT INTO AUDIT.CDC_EVENT_APPLICATIONS (
  EVENT_ID,
  ENTITY,
  OPERATION,
  BUSINESS_KEY,
  SCENARIO,
  EFFECTIVE_AT,
  SOURCE_FILE,
  STATUS,
  EVENT
)
SELECT
  EVENT:event_id::VARCHAR,
  EVENT:entity::VARCHAR,
  EVENT:operation::VARCHAR,
  EVENT:business_key::VARCHAR,
  EVENT:scenario::VARCHAR,
  EVENT:effective_at::TIMESTAMP_TZ,
  _SOURCE_FILE,
  'APPLIED',
  EVENT
FROM TMP_RGA_CDC_PENDING
WHERE (
    EVENT:entity::VARCHAR = 'policies'
    AND EVENT:operation::VARCHAR = 'UPDATE'
  )
  OR (
    EVENT:entity::VARCHAR = 'premiums'
    AND EVENT:operation::VARCHAR = 'UPDATE'
  )
  OR (
    EVENT:entity::VARCHAR = 'claims'
    AND EVENT:operation::VARCHAR = 'INSERT'
  );

-- Operator evidence: any rows here are unsupported and were deliberately not marked APPLIED.
SELECT
  EVENT:event_id::VARCHAR AS EVENT_ID,
  EVENT:entity::VARCHAR AS ENTITY,
  EVENT:operation::VARCHAR AS OPERATION,
  EVENT:scenario::VARCHAR AS SCENARIO
FROM TMP_RGA_CDC_PENDING
WHERE NOT (
    (EVENT:entity::VARCHAR = 'policies' AND EVENT:operation::VARCHAR = 'UPDATE')
    OR (EVENT:entity::VARCHAR = 'premiums' AND EVENT:operation::VARCHAR = 'UPDATE')
    OR (EVENT:entity::VARCHAR = 'claims' AND EVENT:operation::VARCHAR = 'INSERT')
  )
ORDER BY EVENT_ID;
"""


def generate(input_path: Path, output: Path, database: str) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(input_path, database), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    path = generate(args.input, args.output, args.database)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
