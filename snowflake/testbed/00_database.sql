-- TESTBED-ONLY MUTATION. Rendered and executed only by bootstrap_snowflake.py.
CREATE DATABASE IF NOT EXISTS {{DATABASE}}
  COMMENT = 'ADE reproducible hospitality Snowflake pipeline testbed';

CREATE WAREHOUSE IF NOT EXISTS {{WAREHOUSE}}
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Testbed-only warehouse; safe to suspend when not in use';
