#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_generator.faker_config import DEFAULT_SEED
from data_generator.relational_exports import generate_relational_exports


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PostgreSQL digital-platform CDC extracts")
    parser.add_argument("--scale", choices=["small", "medium", "large"], default="small")
    parser.add_argument("--output", type=Path, default=Path("airflow/data/source_exports"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-rows", type=int)
    args = parser.parse_args()
    print(json.dumps(generate_relational_exports("postgres", args.scale, args.output, args.seed, args.max_rows), indent=2))


if __name__ == "__main__":
    main()

