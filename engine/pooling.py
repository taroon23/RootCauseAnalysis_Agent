"""
Pooled multi-month baseline construction.

Pooling is intentionally trivial at the ticket level: concatenate the raw
ticket rows from every source month into one aggregate period, then let the
normal per-queue KPI computation (generator.kpi.compute_kpis_by_queue) treat
it exactly like any other single period. Its queue shares and per-queue
metric values naturally come out as the *blended* values across all pooled
months — no separate "average of averages" logic needed anywhere else.

Parameterized by an explicit list of month keys so this generalizes as more
months get added later — nothing here hardcodes "months 1-3".
"""
from __future__ import annotations

import pathlib

import pandas as pd

from engine.data import DATA_DIR, load_month


def build_pooled_period(month_keys: list[str], data_dir: pathlib.Path = DATA_DIR) -> pd.DataFrame:
    """Concatenate raw ticket-level data from an arbitrary list of months
    into a single pooled period DataFrame.
    """
    if not month_keys:
        raise ValueError("month_keys must be a non-empty list")
    frames = [load_month(m, data_dir) for m in month_keys]
    pooled = pd.concat(frames, ignore_index=True)
    return pooled


def pooled_period_label(month_keys: list[str]) -> str:
    """A readable label for a pooled period, used in output JSON."""
    return "pooled(" + "+".join(month_keys) + ")"
