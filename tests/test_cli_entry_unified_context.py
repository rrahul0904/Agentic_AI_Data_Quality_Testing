from __future__ import annotations

import json

from agentic_data_platform.cli_entry import main


def test_knowledge_cli_status_and_ingest(tmp_path, capsys):
    document = tmp_path / "rules.md"
    document.write_text("Refunds reduce recognized revenue.\n", encoding="utf-8")

    assert main(["knowledge", "ingest", str(document), "--project", str(tmp_path)]) == 0
    ingest = json.loads(capsys.readouterr().out)
    assert ingest["status"] == "INDEXED"

    assert main(["knowledge", "search", "refunds revenue", "--project", str(tmp_path)]) == 0
    search = json.loads(capsys.readouterr().out)
    assert search["results"]

    assert main(["knowledge", "status", "--project", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["documents"] == 1


def test_existing_canonical_cli_still_delegates(capsys):
    assert main(["sql", "analyze", "--args", '{"sql":"SELECT 1"}']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload
