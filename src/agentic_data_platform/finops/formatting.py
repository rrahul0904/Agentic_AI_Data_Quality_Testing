"""Formatting helpers used by FinOps tool output."""

from __future__ import annotations

import math
import re


def format_bytes(value: float | int) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0 B"
    if number == 0 or not math.isfinite(number):
        return "0 B"
    absolute = abs(number)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = max(
        0,
        min(
            int(math.floor(math.log(absolute, 1024))),
            len(units) - 1,
        ),
    )
    scaled = number / (1024 ** index)
    return (
        f"{scaled:.0f} {units[index]}"
        if index == 0
        else f"{scaled:.2f} {units[index]}"
    )


def truncate_query(text: str, max_len: int) -> str:
    if not text:
        return "(empty)"
    one_line = re.sub(r"\s+", " ", text).strip()
    if not one_line:
        return "(empty)"
    bounded = int(max_len)
    if bounded <= 0:
        return ""
    if bounded < 4:
        return one_line[:bounded]
    if len(one_line) <= bounded:
        return one_line
    return one_line[: bounded - 3] + "..."
