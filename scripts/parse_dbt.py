"""Reproducible offline dbt parse without persisting credentials."""
import os
import tempfile
from pathlib import Path
from dbt.cli.main import dbtRunner

root=Path(__file__).resolve().parents[1]/'hospitality-snowflake-data-platform'/'dbt'
with tempfile.TemporaryDirectory() as directory:
    Path(directory,'profiles.yml').write_text((root/'profiles.yml.example').read_text())
    os.environ.update(SNOWFLAKE_ACCOUNT='offline_parse',SNOWFLAKE_USER='offline_parse',SNOWFLAKE_PASSWORD='offline_placeholder')
    result=dbtRunner().invoke(['parse','--no-partial-parse','--project-dir',str(root),'--profiles-dir',directory])
    if result.exception: print(result.exception)
    raise SystemExit(0 if result.success else 1)
