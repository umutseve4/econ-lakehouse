"""Cold-start bootstrap for the dashboard.

Streamlit Community Cloud (and any fresh container) starts from a clean
checkout: the DuckDB warehouse does not exist yet. This module builds it on
first request by invoking the same single-entrypoint orchestrator used by
Docker and CI (orchestrate.py) — live EVDS mode when EVDS_API_KEY is set,
synthetic fixture mode otherwise.

Kept free of any Streamlit import so it is unit-testable in isolation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "warehouse" / "econ.duckdb"


def ensure_warehouse(db_path: str | os.PathLike | None = None) -> str:
    """Build the warehouse via orchestrate.py if it does not exist.

    Returns one of:
      "exists"        — warehouse already present, nothing run
      "built-live"    — pipeline ran with live EVDS data
      "built-fixture" — pipeline ran with the synthetic fixture

    Raises RuntimeError if the pipeline fails or produces no warehouse.
    """
    target = Path(db_path) if db_path else DEFAULT_DB
    if target.exists():
        return "exists"

    mode = "live" if os.environ.get("EVDS_API_KEY", "").strip() else "fixture"
    proc = subprocess.run([sys.executable, str(ROOT / "orchestrate.py")], cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"pipeline bootstrap failed (exit {proc.returncode})")
    if not target.exists():
        raise RuntimeError(f"pipeline succeeded but warehouse missing at {target}")
    return f"built-{mode}"
