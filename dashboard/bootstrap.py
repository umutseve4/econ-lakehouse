"""Cold-start bootstrap for the dashboard.

Streamlit Community Cloud (and any fresh container) starts from a clean
checkout: the DuckDB warehouse does not exist yet. This module builds it on
first request by invoking the same single-entrypoint orchestrator used by
Docker and CI (orchestrate.py) — live EVDS mode when EVDS_API_KEY is set,
synthetic fixture mode otherwise.

Provenance-aware self-healing: orchestrate.py records how the warehouse was
built in warehouse/provenance.json. If a previous boot built the warehouse
from the synthetic fixture (e.g. the container started before the API-key
secret was configured) and a key is available now, the stale fixture
warehouse is wiped and rebuilt live instead of being served forever.

Kept free of any Streamlit import so it is unit-testable in isolation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "warehouse" / "econ.duckdb"


def _target(db_path: str | os.PathLike | None) -> Path:
    return Path(db_path) if db_path else DEFAULT_DB


def provenance_path(db_path: str | os.PathLike | None = None) -> Path:
    """provenance.json lives next to the warehouse file."""
    return _target(db_path).parent / "provenance.json"


def read_provenance(db_path: str | os.PathLike | None = None) -> dict | None:
    """Return the persisted build provenance, or None if absent/corrupt."""
    path = provenance_path(db_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _wipe_warehouse(target: Path) -> None:
    """Remove the warehouse artifacts so the pipeline rebuilds from scratch.

    Bronze must go too: ingest appends, so a live rebuild on top of fixture
    bronze would blend synthetic and real rows in the gold mart.
    """
    target.unlink(missing_ok=True)
    provenance_path(target).unlink(missing_ok=True)
    bronze = target.parent / "bronze"
    if bronze.exists():
        shutil.rmtree(bronze)


def _run_pipeline(target: Path) -> None:
    proc = subprocess.run([sys.executable, str(ROOT / "orchestrate.py")], cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"pipeline bootstrap failed (exit {proc.returncode})")
    if not target.exists():
        raise RuntimeError(f"pipeline succeeded but warehouse missing at {target}")


def ensure_warehouse(db_path: str | os.PathLike | None = None) -> str:
    """Build the warehouse via orchestrate.py if needed.

    Returns one of:
      "exists"        — warehouse present and no rebuild required
      "built-live"    — first build, live EVDS data
      "built-fixture" — first build, synthetic fixture
      "rebuilt-live"  — stale fixture warehouse wiped and rebuilt live

    Raises RuntimeError if the pipeline fails or produces no warehouse.
    """
    target = _target(db_path)
    key_set = bool(os.environ.get("EVDS_API_KEY", "").strip())

    if target.exists():
        prov = read_provenance(db_path)
        if key_set and prov is not None and prov.get("mode") == "fixture":
            # Self-heal: fixture warehouse but a live key is available now.
            _wipe_warehouse(target)
            _run_pipeline(target)
            return "rebuilt-live"
        return "exists"

    mode = "live" if key_set else "fixture"
    _run_pipeline(target)
    return f"built-{mode}"
