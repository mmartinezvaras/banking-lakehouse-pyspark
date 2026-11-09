"""Paths and constants shared by the generator, the pipeline and the dashboard export."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 42

RAW_DIR = Path(os.getenv("LAKEHOUSE_RAW_DIR", ROOT / "data" / "raw"))
LAKE_DIR = Path(os.getenv("LAKEHOUSE_DIR", ROOT / "data" / "lakehouse"))
EXPORT_DIR = Path(os.getenv("LAKEHOUSE_EXPORT_DIR", ROOT / "dashboard" / "data"))

# Raw batches: the first load and the next day's increment (new rows + corrections).
BATCH_1 = "2026-H1.csv"
BATCH_2 = "2026-07-01.csv"
