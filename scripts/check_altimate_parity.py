#!/usr/bin/env python3
"""Compatibility entry point for the strict Altimate parity gate."""

from __future__ import annotations

import sys

from check_parity_gate import check_ledger


def main() -> int:
    ok, counts, errors = check_ledger("altimate")
    print(f"ALTIMATE PARITY: {'PASS' if ok else 'FAIL'} {counts}")
    for error in errors[:100]:
        print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
