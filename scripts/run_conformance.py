#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from agentic_data_platform.conformance import ConformanceRunner, load_cases, write_report


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(ROOT / "hospitality-snowflake-data-platform"))
    parser.add_argument("--fixtures", default=str(ROOT / "tests" / "conformance" / "fixtures"))
    parser.add_argument("--output", default=str(ROOT / "artifacts"))
    args = parser.parse_args()
    report = ConformanceRunner(args.project).run(load_cases(args.fixtures))
    paths = write_report(report, args.output)
    print(
        "conformance:",
        report["status"],
        "cases=", report["counts"]["cases"],
        "match=", report["counts"]["match"],
        "divergence=", report["counts"]["divergence"],
        "unsupported=", report["counts"]["unsupported"],
    )
    for path in paths:
        print(path)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
