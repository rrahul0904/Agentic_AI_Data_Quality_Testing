#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from agentic_data_platform.certification import CertificationRunner


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "artifacts"))
    args = parser.parse_args()
    runner = CertificationRunner()
    report = runner.run(live=args.live)
    paths = runner.write_report(report, args.output)
    print(f"certification: {report['status']} mode={report['mode']} counts={report['counts']}")
    for path in paths:
        print(path)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
