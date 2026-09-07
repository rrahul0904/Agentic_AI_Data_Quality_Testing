import { ToolRegistry } from '../core/tool-registry.mjs';
import { sqlAnalyze, sqlExecute, sqlLineage } from './sql.mjs';
import { piiScan } from './pii.mjs';
import { fileList, fileRead, fileWrite } from './files.mjs';
import { dbtInspect } from './dbt.mjs';
import { dbtQualityAudit, dbtParse, dbtTest, dbtBuild } from './dbt-quality.mjs';
import { airflowAudit, airflowStatus, airflowDagTest } from './airflow.mjs';
import { snowflakeConfigAudit, snowflakePing, snowflakeQuery } from './snowflake.mjs';
import { qualityPipeline } from './quality.mjs';
import { stackDiscover } from './discover.mjs';

export function createRegistry(mode) {
  const r = new ToolRegistry(mode);
  [
    sqlAnalyze, sqlExecute, sqlLineage,
    piiScan,
    fileList, fileRead, fileWrite,
    dbtInspect, dbtQualityAudit, dbtParse, dbtTest, dbtBuild,
    airflowAudit, airflowStatus, airflowDagTest,
    snowflakeConfigAudit, snowflakePing, snowflakeQuery,
    qualityPipeline,
    stackDiscover
  ].forEach(t => r.register(t));
  return r;
}
