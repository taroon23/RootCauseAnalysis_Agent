"""Ticket-level data loading, shared across the engine's entrypoints."""
from __future__ import annotations

import pathlib

import pandas as pd

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# Canonical chronological order of generated months. Used by anomaly/ to auto-derive
# "immediately preceding month" and "all months before this one" (for pooled baselines)
# without hardcoding month-specific logic anywhere. Append new months here as they're
# generated -- everything downstream (Step 3's detector, future steps) reads from this
# single source of truth rather than re-deriving month order independently.
CANONICAL_MONTH_ORDER = [
    "month_1_baseline",
    "month_2_scenario_mixshift",
    "month_3_scenario_genuine",
    "month_4_scenario_mixed",
    "month_5_baseline_null",
]


def load_month(month_key: str, data_dir: pathlib.Path = DATA_DIR) -> pd.DataFrame:
    """Load one month's raw ticket-level CSV."""
    return pd.read_csv(data_dir / f"{month_key}.csv", parse_dates=["date"])


def months_before(month_key: str, month_order: list[str] = CANONICAL_MONTH_ORDER) -> list[str]:
    """All months strictly before `month_key` in the canonical sequence."""
    idx = month_order.index(month_key)
    return month_order[:idx]


def immediately_preceding_month(month_key: str, month_order: list[str] = CANONICAL_MONTH_ORDER) -> str | None:
    """The single month immediately before `month_key`, or None if it's the first."""
    idx = month_order.index(month_key)
    return month_order[idx - 1] if idx > 0 else None
