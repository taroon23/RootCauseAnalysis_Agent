"""Ticket-level data loading, shared across the engine's entrypoints."""
from __future__ import annotations

import pathlib

import pandas as pd

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def load_month(month_key: str, data_dir: pathlib.Path = DATA_DIR) -> pd.DataFrame:
    """Load one month's raw ticket-level CSV."""
    return pd.read_csv(data_dir / f"{month_key}.csv", parse_dates=["date"])
