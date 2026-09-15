#!/usr/bin/env python3
"""Generate an exact-head ADE production/external assurance artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_data_platform.certification.production import (
    load_external_evidence,
    write_production_certification,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", default="artifacts/production/assurance.json")
    parser.add_argument("--external-evidence")
    parser.add_argument("--local-gate-passed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    external = load_external_evidence(args.external_evidence)
    destination = write_production_certification(
        args.output,
        args.commit_sha,
        local_gate_passed=args.local_gate_passed,
        external_evidence=external,
    )
    payload = json.loads(Path(destination).read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "artifact": str(destination),
                "commit_sha": payload["commit_sha"],
                "local_gate_passed": payload["local_gate_passed"],
                "superior": payload["superior"],
                "counts": payload["counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
